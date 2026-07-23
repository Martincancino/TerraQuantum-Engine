"""
FASE 10 — Módulo de interpretación geofísica con LLM (Gemini).

Responsabilidad única: ensamblar el prompt que se enviará al modelo de lenguaje
para generar un "Exploration Geophysical Interpretation Report" a partir del
output estructurado del orquestador de inversión conjunta (Fase 9C-2).

NOTA DE COMPLIANCE:
    Las palabras "JORC", "reservas", "recursos minerales" y "mineral ore" están
    PROHIBIDAS en todo prompt generado por este módulo. El reporte es una
    interpretación geofísica cualitativa, no una estimación de recursos conforme
    a ningún estándar regulatorio de la industria minera.
"""

from __future__ import annotations

import json
import os
from typing import Any, List, Literal

from pydantic import BaseModel, ValidationError

from core.config import GEMINI_REPORT_MODEL


# ─────────────────────────────────────────────────────────────────────────────
# Modelos Pydantic — contrato de salida del agente (validación estructural).
# ─────────────────────────────────────────────────────────────────────────────

class AnomalyInterpretation(BaseModel):
    id: str
    description: str
    density_mean: float
    susceptibility_mean: float
    volume_m3: float
    priority: Literal["HIGH", "MEDIUM", "LOW"]


class ExplorationGeophysicalInterpretationReport(BaseModel):
    executive_summary: str
    anomalies: List[AnomalyInterpretation]
    overall_assessment: str
    limitations: str


# Palabras prohibidas por compliance SEC/JORC (case-insensitive).
# Si alguna aparece en el JSON validado se descarta la respuesta y se retorna fallback.
_BANNED_WORDS: List[str] = [
    "reserve", "resource", "grade", "npv", "irr", "tonnage", "economic value",
]


# ─────────────────────────────────────────────────────────────────────────────
# System prompt del agente (fijo, no depende del run).
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are TerraQuantum GeoInterpreter, an expert geophysical interpretation \
assistant for mineral exploration projects.

Your task is to generate a concise "Exploration Geophysical Interpretation \
Report" based on structured numerical output from a joint gravity-magnetic \
inversion (cross-gradient coupling, Gallardo-Meju methodology).

STRICT RULES:
1. NEVER use the words "JORC", "reserves", "mineral resources", or "ore".
2. ALL quantitative claims must come exclusively from the provided numerical \
data — no invented values.
3. Present findings as geophysical inferences, not economic conclusions.
4. Describe density and susceptibility anomalies as "geophysical targets" or \
"anomalous zones", not as ore bodies.
5. Highlight structural coupling (E_norm) and centroid separation as evidence \
of spatial correlation between the two physical properties.
6. Keep each text field under 300 words.
7. The "limitations" field must note the inherent non-uniqueness of potential \
field inversions.
8. FORBIDDEN WORDS (NEVER use, not even in passing): "reserve", "resource", \
"grade", "NPV", "IRR", "tonnage", "economic value". These terms imply \
regulatory-standard resource estimation (JORC/NI 43-101), which this report \
is NOT.

OUTPUT FORMAT — MANDATORY:
You MUST return a single, valid JSON object with exactly these four keys:
{
  "executive_summary": "<string — overall survey context and key findings>",
  "anomalies": [
    {
      "id": "<anomaly_id string>",
      "description": "<geophysical interpretation of this body>",
      "density_mean": <number>,
      "susceptibility_mean": <number>,
      "volume_m3": <number>,
      "priority": "<HIGH | MEDIUM | LOW>"
    }
  ],
  "overall_assessment": "<string — convergence quality, coupling strength, \
exploration implications>",
  "limitations": "<string — non-uniqueness, depth resolution, data gaps>"
}

CRITICAL OUTPUT CONSTRAINTS:
- Output ONLY the raw JSON object. No markdown code fences (```json), \
no explanatory text before or after, no comments inside the JSON.
- Every string value must be in English.
- If no discrete anomalies are present, return an empty array for "anomalies".
"""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de formateo.
# ─────────────────────────────────────────────────────────────────────────────
def _fmt(value: Any, decimals: int = 3, fallback: str = "N/A") -> str:
    if value is None:
        return fallback
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return fallback


def _centroid_line(label: str, centroid: dict | None) -> str:
    if centroid is None:
        return f"  {label}: undefined (field amplitude ~0)"
    x = _fmt(centroid.get("x_m"))
    y = _fmt(centroid.get("y_m"))
    z = _fmt(centroid.get("z_m"))
    w = _fmt(centroid.get("total_weight"), decimals=2)
    return f"  {label}: x={x} m, y={y} m, z={z} m (total weight={w})"


def _format_anomalies(anomalies: list | None) -> list[str]:
    """Convierte anomalies_payload en líneas de texto legibles para el prompt."""
    if not anomalies:
        return ["  (no discrete geological bodies detected above threshold)"]
    lines = []
    for a in anomalies:
        aid = a.get("anomaly_id", "?")
        nvox = a.get("voxel_count", "?")
        vol = _fmt(a.get("volume_m3"), decimals=0)
        c = a.get("centroid", {})
        cx = _fmt(c.get("x_m"), decimals=0)
        cy = _fmt(c.get("y_m"), decimals=0)
        cz = _fmt(c.get("z_m"), decimals=0)
        rho_mean = _fmt(a.get("density_mean"), decimals=3)
        rho_max = _fmt(a.get("density_max"), decimals=3)
        chi_mean = _fmt(a.get("susceptibility_mean"), decimals=5)
        chi_max = _fmt(a.get("susceptibility_max"), decimals=5)
        corr = _fmt(a.get("density_susceptibility_correlation"), decimals=3)
        lines.append(
            f"  [{aid}] {nvox} voxels | vol={vol} m³ | "
            f"centroid=({cx}, {cy}, {cz}) m | "
            f"ρ={rho_mean}/{rho_max} t/m³ (mean/max) | "
            f"χ={chi_mean}/{chi_max} SI (mean/max) | "
            f"corr(ρ,χ)={corr}"
        )
    return lines


# ─────────────────────────────────────────────────────────────────────────────
# Ensamblado del prompt de usuario (user turn enviado a la API).
# ─────────────────────────────────────────────────────────────────────────────
def build_interpretation_prompt(report: dict) -> str:
    """Convierte el dict de report del orquestador en el user-turn listo para enviar.

    Recibe el ``report`` tal como lo devuelve ``run_joint_inversion()`` en
    ``result["report"]``. Extrae los campos relevantes y los formatea como un
    resumen estructurado en texto, que el LLM usará como contexto de entrada.

    Returns
    -------
    str
        String completo del user-turn. Combinado con ``SYSTEM_PROMPT``, forma
        el payload de la llamada a la API de Gemini.
    """
    mesh = report.get("mesh", {})
    cont = report.get("continuation", {})
    final = report.get("final", {})
    jm = report.get("joint_metrics", {})
    field = report.get("field", {})

    # Malla y parámetros de campaña
    nx = mesh.get("nx", "?")
    ny = mesh.get("ny", "?")
    nz = mesh.get("nz", "?")
    block_size = mesh.get("block_size", "?")
    n_active = mesh.get("n_active", "?")

    # Convergencia
    iterations_done = cont.get("iterations_done", "?")
    stop_reason = cont.get("stop_reason", "unknown")
    cross_lambda_max = cont.get("cross_lambda_max", "?")
    e_norm_final = _fmt(final.get("E_norm"), decimals=6)
    misfit_g = _fmt(final.get("misfit_gravity_percent"), decimals=3)
    misfit_m = _fmt(final.get("misfit_magnetic_percent"), decimals=3)

    # Métricas conjuntas
    centroid_mass = jm.get("centroid_mass_m")
    centroid_susc = jm.get("centroid_susceptibility_m")
    separation = _fmt(jm.get("centroid_separation_m"), decimals=1)

    # Campo geomagnético de referencia
    incl = _fmt(field.get("inclination_deg"), decimals=1)
    decl = _fmt(field.get("declination_deg"), decimals=1)
    intensity = _fmt(field.get("field_intensity_nt"), decimals=0)

    # Bounds físicos
    density_bounds = report.get("density_bounds_t_m3", [None, None])
    susc_bounds = report.get("susceptibility_bounds_si", [None, None])
    rho_min = _fmt(density_bounds[0] if density_bounds else None)
    rho_max = _fmt(density_bounds[1] if density_bounds else None)
    chi_min = _fmt(susc_bounds[0] if susc_bounds else None, decimals=5)
    chi_max = _fmt(susc_bounds[1] if susc_bounds else None, decimals=5)

    n_obs = report.get("observation_count", "?")
    n_vox = report.get("anomaly_voxels", "?")
    anomalies = report.get("anomalies_payload", None)
    anomaly_lines = _format_anomalies(anomalies)

    lines = [
        "=== JOINT INVERSION STRUCTURED SUMMARY (input for interpretation) ===",
        "",
        "--- SURVEY PARAMETERS ---",
        f"  Grid: {nx} x {ny} x {nz} cells | block_size: {block_size} m | active cells: {n_active}",
        f"  Observations: {n_obs} gravity+magnetic stations",
        f"  Geomagnetic field: inclination={incl}°, declination={decl}°, intensity={intensity} nT",
        f"  Density bounds: [{rho_min}, {rho_max}] t/m³",
        f"  Susceptibility bounds: [{chi_min}, {chi_max}] SI",
        "",
        "--- INVERSION CONVERGENCE ---",
        f"  Iterations executed: {iterations_done}",
        f"  Stop reason: {stop_reason}",
        f"  Cross-gradient coupling (lambda_max): {cross_lambda_max}",
        f"  E_norm (structural dissimilarity, cellwise, grid-independent): {e_norm_final}",
        f"    -> 0.0 = gradients fully aligned; 1.0 = fully orthogonal",
        f"  Gravity data misfit: {misfit_g} %",
        f"  Magnetic data misfit: {misfit_m} %",
        "",
        "--- SPATIAL DISTRIBUTION ---",
        f"  Anomalous voxels returned: {n_vox}",
        _centroid_line("Density anomaly centroid (mass excess)", centroid_mass),
        _centroid_line("Susceptibility anomaly centroid", centroid_susc),
        f"  Centroid separation (ρ vs χ): {separation} m",
        "",
        "--- DISCRETE GEOLOGICAL BODIES (physical clustering, threshold I_joint>0.6) ---",
        f"  Total bodies detected: {len(anomalies) if anomalies else 0}",
        *anomaly_lines,
        "  [Each body: voxel count, volume, centroid, density/susceptibility stats,",
        "   Pearson corr(ρ,χ) within the body — all from inversion output, no extrapolation]",
        "",
        "=== END OF NUMERICAL SUMMARY ===",
        "",
        "Based on the above, generate the Exploration Geophysical Interpretation "
        "Report following the JSON format defined in your instructions. "
        "Use the DISCRETE GEOLOGICAL BODIES section as the primary basis for the "
        "'anomalies' array. "
        "Do not invent any numerical values not present in this summary. "
        "Return ONLY the raw JSON object — no markdown, no prose outside the JSON.",
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Llamada a la API de Gemini (SDK google-genai, F6 — reemplaza el deprecado
# google-generativeai). Requiere: pip install google-genai
# ─────────────────────────────────────────────────────────────────────────────

_GENERATION_CONFIG = {
    "temperature": 0.05,
    "top_p": 0.8,
    "top_k": 20,
    "response_mime_type": "application/json",
}

_FALLBACK_NO_KEY: dict = {
    "executive_summary": "Gemini API key not configured.",
    "anomalies": [],
    "overall_assessment": "N/A — API key missing.",
    "limitations": "N/A",
}


def request_gemini_interpretation(report: dict, api_key: str | None = None) -> dict:
    """Llama a Gemini (tier reporte) y retorna la interpretación como dict.

    Migrado al SDK ``google-genai`` (F6). Usa ``GEMINI_REPORT_MODEL``.

    Parameters
    ----------
    report : dict
        ``result["report"]`` del orquestador de inversión.
    api_key : str | None
        Clave del usuario (BYO-key). Si es ``None`` se lee de ``GEMINI_API_KEY``.
        Si no hay clave por ninguna vía, retorna un fallback sin crashear.

    Returns
    -------
    dict
        Diccionario con claves: executive_summary, anomalies,
        overall_assessment, limitations.
        En caso de error incluye además la clave "error".
    """
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return dict(_FALLBACK_NO_KEY)

    user_prompt = build_interpretation_prompt(report)

    try:
        from google import genai  # noqa: PLC0415
        from google.genai import types  # noqa: PLC0415

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=GEMINI_REPORT_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                **_GENERATION_CONFIG,
            ),
        )
        raw_text = response.text
    except Exception as exc:
        return {
            "error": f"Gemini API error: {exc}",
            "executive_summary": "",
            "anomalies": [],
            "overall_assessment": "",
            "limitations": "",
        }

    # ── Capa 1: parseo JSON ───────────────────────────────────────────────────
    try:
        parsed_json = json.loads(raw_text)
    except json.JSONDecodeError:
        return {
            "error": "Failed to parse interpretation",
            "raw": raw_text[:2000],
            "executive_summary": "",
            "anomalies": [],
            "overall_assessment": "",
            "limitations": "",
        }

    # ── Capa 2: validación estructural Pydantic ───────────────────────────────
    try:
        validated = ExplorationGeophysicalInterpretationReport(**parsed_json)
        validated_data = validated.model_dump()
    except (ValidationError, TypeError, Exception) as exc:
        return {
            "error": f"Validation/Compliance failed: {exc}",
            "raw": str(parsed_json)[:2000],
            "executive_summary": "",
            "anomalies": [],
            "overall_assessment": "",
            "limitations": "",
        }

    # ── Capa 3: compliance — banned words (SEC/JORC) ──────────────────────────
    json_lower = json.dumps(validated_data).lower()
    for word in _BANNED_WORDS:
        if word in json_lower:
            return {
                "error": f"Validation/Compliance failed: banned word detected: '{word}'",
                "raw": json.dumps(validated_data)[:2000],
                "executive_summary": "",
                "anomalies": [],
                "overall_assessment": "",
                "limitations": "",
            }

    validated_data["regulatory_disclaimer"] = (
        "Este informe es una interpretación geofísica preliminar y no constituye "
        "una estimación de recursos minerales bajo NI 43-101 o JORC 2012. "
        "No ha sido revisado por un Qualified Person ni Competent Person. "
        "Requiere validación profesional independiente antes de cualquier uso regulatorio o de inversión."
    )
    return validated_data
