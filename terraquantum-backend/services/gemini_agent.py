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

Este módulo solo construye strings. NO realiza llamadas HTTP a la API de Gemini.
Esa integración se completará cuando las credenciales estén disponibles.
"""

from __future__ import annotations

import os
from typing import Any


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
6. Keep the report under 600 words. Use structured sections.
7. End with a "Limitations and Next Steps" section noting the inherent \
non-uniqueness of potential field inversions.

OUTPUT FORMAT:
## 1. Survey Overview
## 2. Inversion Convergence Summary
## 3. Gravity Anomaly Interpretation
## 4. Magnetic Susceptibility Interpretation
## 5. Joint Structural Coupling Assessment
## 6. Priority Geophysical Targets
## 7. Limitations and Next Steps
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
        "Report following the format defined in your instructions. "
        "Use the DISCRETE GEOLOGICAL BODIES section as the primary basis for section "
        "'## 6. Priority Geophysical Targets'. "
        "Do not invent any numerical values not present in this summary.",
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Llamada a la API de Gemini.
# Requiere: pip install google-generativeai
# ─────────────────────────────────────────────────────────────────────────────
def request_gemini_interpretation(report: dict) -> str:
    """Llama a Gemini 1.5 Pro y retorna el reporte de interpretación como string.

    Lee la clave desde la variable de entorno GEMINI_API_KEY.
    Si no está configurada, retorna un mensaje de fallback amigable sin crashear.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return "Gemini API key not configured. Mock report generated."

    user_prompt = build_interpretation_prompt(report)

    try:
        import google.generativeai as genai  # noqa: PLC0415

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name="gemini-1.5-pro",
            system_instruction=SYSTEM_PROMPT,
        )
        response = model.generate_content(
            user_prompt,
            generation_config={"temperature": 0.1},
        )
        return response.text
    except Exception as exc:
        return f"Gemini API error: {exc}. Mock report generated."
