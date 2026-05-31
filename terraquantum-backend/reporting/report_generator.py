import hashlib
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.block_model_store import (
    get_run_favorability_path,
    get_run_inputs_path,
    get_run_metrics_path,
    get_run_report_path,
    load_project_meta,
)
from core.config import APP_VERSION


DISCLAIMER_TEXT = """════════════════════════════════════════════════════════════════════════════════
  NO-JORC / NI 43-101 — MODELO CONCEPTUAL EXPLORATORIO — EXPLORATION ONLY
════════════════════════════════════════════════════════════════════════════════

AVISO LEGAL OBLIGATORIO (NI 43-101 / JORC / SAMREC Compliance Notice)

Este reporte fue generado automáticamente por TerraQuantum v{version} y NO
constituye, ni puede interpretarse como, una estimación de Recursos Minerales
o Reservas Minerales bajo ningún estándar regulatorio reconocido, incluyendo
pero no limitado a:
  · NI 43-101 (National Instrument — Canadá)
  · JORC Code 2012 (Australasia Joint Ore Reserves Committee)
  · SAMREC Code (South Africa)
  · SEC Industry Guide 7 / S-K 1300 (Estados Unidos)

Los resultados presentados corresponden a un MODELO CONCEPTUAL PRELIMINAR
basado en inversión gravimétrica 3D (LSQR + regularización Tikhonov).

LIMITACIONES EXPLÍCITAS:
  · "Ley estimada" (grade): PROXY HEURÍSTICO derivado del contraste de
    densidad modelado. NO es ley medida por análisis geoquímico certificado.
  · Tonelaje: ESTIMADO CALCULADO, no muestreado ni estimado por kriging/IK.
  · NPV y LOM: CONCEPTUALES, calculados sobre supuestos editables de precio,
    costo y recuperación metalúrgica. NO constituyen evaluación bancable.
  · Las anomalías identificadas requieren verificación por perforación y
    análisis de laboratorio antes de cualquier declaración pública.

Este reporte NO reemplaza:
  · Estudio de factibilidad técnica-económica (PEA / PFS / FS)
  · Análisis geotécnico o hidrogeológico
  · Evaluación de recursos/reservas por Persona Competente certificada
  · Debida diligencia financiera o ambiental

TerraQuantum es un sistema de EXPLORACIÓN EXPERIMENTAL/CONCEPTUAL.
Toda decisión técnica, económica o de inversión debe basarse exclusivamente en
datos de campo verificados, perforaciones confirmadas y evaluación profesional
independiente por Persona Competente habilitada.

════════════════════════════════════════════════════════════════════════════════"""


def _build_config_hash(inputs: "dict[str, Any]") -> str:
    """
    FASE 11 — Audit Trail: calcula un SHA-256 de los parámetros de inversión.
    Solo incluye las claves relevantes para la física (no metadatos de UI).
    """
    AUDIT_KEYS = [
        "nx", "ny", "nz", "block_size", "cutoff_radius",
        "lambda_mag", "alpha_spatial", "depth", "nir", "fe",
        "enable_focusing", "noise_floor", "noise_pct",
    ]
    stable = {k: inputs.get(k) for k in AUDIT_KEYS if k in inputs}
    payload = json.dumps(stable, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16].upper()


def _system_audit_section_html(
    project_id: str,
    run_id: str,
    inputs: "dict[str, Any]",
    generated_utc: str,
) -> str:
    """
    FASE 11 — Audit Trail: sección SYSTEM AUDIT para compliance.
    Incluye versión del motor y hash de configuración de inversión.
    """
    config_hash = _build_config_hash(inputs)

    lambda_mag_raw = inputs.get("lambda_mag")
    lambda_selected_note = ""
    if inputs.get("lambda_selected_via"):
        lambda_selected_note = f" ({_escape(str(inputs['lambda_selected_via']))})"

    return f"""
  <section id="system-audit" style="
    border: 2px solid #1a3a20;
    background: #0f1f12;
    color: #c2d8c4;
    padding: 16px 20px;
    margin: 24px 0;
    font-family: monospace;
    font-size: 12px;
  ">
    <div style="color: #6aaa78; font-size: 13px; font-weight: 700; letter-spacing: 0.12em;
                text-transform: uppercase; border-bottom: 1px solid #2a4a30; padding-bottom: 8px;
                margin-bottom: 12px;">
      ▸ SYSTEM AUDIT — Trazabilidad de Run (Fase 11)
    </div>
    <table style="width:100%; border-collapse: collapse; color: #c2d8c4;">
      <tr>
        <td style="padding: 3px 8px; color: #6aaa78; white-space: nowrap;">Motor</td>
        <td style="padding: 3px 8px; font-weight: bold;">TerraQuantum Backend v{_escape(APP_VERSION)}
            — GravimetryForward/Inversion (LSQR + Nagy/PointMass Kernel, F0.2 HPC)</td>
      </tr>
      <tr>
        <td style="padding: 3px 8px; color: #6aaa78; white-space: nowrap;">Run ID</td>
        <td style="padding: 3px 8px;">{_escape(run_id)}</td>
      </tr>
      <tr>
        <td style="padding: 3px 8px; color: #6aaa78; white-space: nowrap;">Project ID</td>
        <td style="padding: 3px 8px;">{_escape(project_id)}</td>
      </tr>
      <tr>
        <td style="padding: 3px 8px; color: #6aaa78; white-space: nowrap;">Config Hash</td>
        <td style="padding: 3px 8px; letter-spacing: 0.08em; color: #8ecf9a;" title="SHA-256[:16] de parámetros físicos de inversión">
          SHA256[:{_escape(config_hash)}]
        </td>
      </tr>
      <tr>
        <td style="padding: 3px 8px; color: #6aaa78; white-space: nowrap;">Grilla Inversión</td>
        <td style="padding: 3px 8px;">{_escape(str(inputs.get("nx","?")))}×{_escape(str(inputs.get("ny","?")))}×{_escape(str(inputs.get("nz","?")))}
            | block_size={_escape(str(inputs.get("block_size","?")))}m</td>
      </tr>
      <tr>
        <td style="padding: 3px 8px; color: #6aaa78; white-space: nowrap;">Lambda_mag</td>
        <td style="padding: 3px 8px;">{_escape(str(lambda_mag_raw))}{lambda_selected_note}</td>
      </tr>
      <tr>
        <td style="padding: 3px 8px; color: #6aaa78; white-space: nowrap;">Alpha_spatial</td>
        <td style="padding: 3px 8px;">{_escape(str(inputs.get("alpha_spatial","?")))}</td>
      </tr>
      <tr>
        <td style="padding: 3px 8px; color: #6aaa78; white-space: nowrap;">Generado</td>
        <td style="padding: 3px 8px;">{_escape(generated_utc)}</td>
      </tr>
    </table>
    <div style="margin-top: 10px; color: #4a7a52; font-size: 10px;">
      El config hash permite verificar que los parámetros físicos no fueron
      alterados post-generación. Cualquier cambio en grilla, lambda, alpha o
      block_size producirá un hash diferente.
    </div>
  </section>
"""


def generate_technical_report_html(
    project_id: str,
    run_id: str,
    *,
    report: "dict[str, Any] | None" = None,
    metrics: "dict[str, Any] | None" = None,
    favorability: "dict[str, Any] | None" = None,
    inputs: "dict[str, Any] | None" = None,
) -> str:
    """Lee los JSON persistidos de la corrida y retorna un reporte HTML.

    Los kwargs opcionales report/metrics/favorability/inputs permiten inyectar
    datos pre-cargados (útil en tests) sin leer de disco.
    """
    inputs_path = get_run_inputs_path(project_id=project_id, run_id=run_id)
    report_path = get_run_report_path(project_id=project_id, run_id=run_id)
    metrics_path = get_run_metrics_path(project_id=project_id, run_id=run_id)
    favorability_path = get_run_favorability_path(project_id=project_id, run_id=run_id)

    if inputs is None:
        inputs = _read_required_json(inputs_path, "inputs.json")
    if report is None:
        report = _read_required_json(report_path, "report.json")
    if metrics is None:
        metrics = _read_optional_json(metrics_path)
    if favorability is None:
        favorability = _read_optional_json(favorability_path)

    project_meta = load_project_meta(project_id) or {}
    georef_confidence = project_meta.get("georef_confidence", "MISSING")
    georef_footprint_data = project_meta.get("footprint")
    georef_section = _georef_section_html(georef_confidence, georef_footprint_data)

    fit_diagnostics = _as_dict(report.get("fitDiagnostics"))
    observation_quality = _as_dict(report.get("observationQuality"))
    technical_summary = _as_dict(report.get("technicalSummary"))
    uncertainty_diagnostics = _as_dict(report.get("uncertaintyDiagnostics"))
    best_target = _as_dict(report.get("best_target"))
    misfit_error_percent = report.get("misfit_error_percent")
    if misfit_error_percent is None:
        misfit_error_percent = fit_diagnostics.get("misfit_error_percent")
    residual_map = _as_list(fit_diagnostics.get("residualMap"))
    generated_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    favorability_section = _favorability_section_html(favorability)
    favorability_alert_html = _favorability_alert_html(favorability)

    sr_raw = report.get("spatial_readiness") or _as_dict(report.get("auto_params")).get("spatial_readiness")
    sr_cap_raw = _as_dict(favorability).get("spatial_readiness_cap") if favorability else None
    spatial_readiness_section = _spatial_readiness_section_html(sr_raw)
    spatial_readiness_cap_section = _spatial_readiness_cap_section_html(sr_cap_raw)
    rsp_raw = report.get("regional_scale_preflight")
    ack_regional = report.get("acknowledge_regional_scale")
    regional_scale_preflight_section = _regional_scale_preflight_section_html(rsp_raw, ack_regional)

    # FASE 11 — Audit Trail
    system_audit_section = _system_audit_section_html(
        project_id=project_id,
        run_id=run_id,
        inputs=inputs,
        generated_utc=generated_utc,
    )

    chi_squared_section = _chi_squared_section_html(fit_diagnostics)

    # FASE 11 — Disclaimer con version interpolada
    disclaimer_full = DISCLAIMER_TEXT.replace("{version}", APP_VERSION)

    economic_gate = _check_economic_gate(
        favorability=favorability,
        technical_summary=technical_summary,
        observation_quality=observation_quality,
    )
    priority_class_warnings_html = (
        f"<h3>Alertas de Clasificación de Prioridad</h3>"
        f"{_list_html(report.get('priority_class_warnings'))}"
        if report.get("priority_class_warnings")
        else ""
    )

    mining_section = _mining_section_html(metrics, economic_gate)

    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>{_escape("TerraQuantum — NO-JORC / EXPLORATION ONLY — Reporte Técnico")} - {_escape(project_id)} / {_escape(run_id)}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #172018;
      --muted: #5f6f61;
      --line: #c9d8cb;
      --soft: #eef5ef;
      --accent: #365f3c;
      --warn: #8a3b12;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 40px;
      background: #f8fbf8;
      color: var(--ink);
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.5;
    }}
    main {{
      max-width: 1080px;
      margin: 0 auto;
      background: #ffffff;
      border: 1px solid var(--line);
      padding: 36px;
    }}
    header {{
      border-bottom: 3px solid var(--accent);
      padding-bottom: 20px;
      margin-bottom: 28px;
    }}
    .brand {{
      color: var(--accent);
      font-size: 28px;
      font-weight: 700;
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }}
    .subtitle {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 13px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    h1 {{ font-size: 22px; margin: 22px 0 8px; }}
    h2 {{
      margin: 30px 0 14px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--line);
      color: var(--accent);
      font-size: 16px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    h3 {{
      margin: 18px 0 8px;
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-bottom: 16px;
    }}
    th, td {{
      padding: 10px 12px;
      border: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 13px;
    }}
    th {{
      width: 34%;
      background: var(--soft);
      color: var(--muted);
      font-weight: 700;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .metric {{
      padding: 14px;
      border: 1px solid var(--line);
      background: #fbfdfb;
    }}
    .metric-label {{
      display: block;
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .metric-value {{
      display: block;
      color: var(--ink);
      font-size: 18px;
      font-weight: 700;
    }}
    .disclaimer {{
      margin-top: 32px;
      padding: 18px;
      border: 2px solid var(--warn);
      background: #fff7ef;
      color: #4c250e;
      font-size: 13px;
      white-space: pre-wrap;
    }}
    .fav-disclaimer {{
      margin-bottom: 20px;
      padding: 14px 18px;
      border: 2px solid var(--warn);
      background: #fff3e0;
      color: #4c250e;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.04em;
    }}
    .fav-table th {{ width: auto; }}
    .fav-not-evaluated td {{
      color: var(--muted);
      font-style: italic;
    }}
    footer {{
      margin-top: 28px;
      padding-top: 14px;
      border-top: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
    }}
    ul {{ margin-top: 8px; padding-left: 22px; }}
    li {{ margin-bottom: 6px; }}
    .georef-badge {{
      padding: 10px 16px;
      font-weight: 700;
      font-size: 14px;
      margin-bottom: 14px;
      border-radius: 2px;
      display: inline-block;
    }}
    .georef-HIGH {{ background: #e8f5e9; color: #1b5e20; border: 2px solid #4caf50; }}
    .georef-MEDIUM {{ background: #fff8e1; color: #6d4c00; border: 2px solid #ffc107; }}
    .georef-LOW {{ background: #fff3e0; color: #6d2700; border: 2px solid #ff8f00; }}
    .georef-MISSING {{ background: #ffebee; color: #7f1515; border: 2px solid #e53935; }}
    .georef-warnings {{
      margin: 14px 0;
      padding: 12px 14px;
      background: #fff8f0;
      border-left: 3px solid var(--warn);
    }}
    .georef-disclaimer {{
      margin-top: 12px;
      padding: 14px;
      background: #f8fbf8;
      border: 1px solid var(--line);
      font-size: 13px;
      color: var(--muted);
    }}
    .sr-alert-red {{
      margin: 14px 0;
      padding: 14px 18px;
      border: 2px solid #c62828;
      background: #ffebee;
      color: #7f1515;
      font-size: 13px;
    }}
    .sr-alert-yellow {{
      margin: 14px 0;
      padding: 14px 18px;
      border: 2px solid var(--warn);
      background: #fff3e0;
      color: #4c250e;
      font-size: 13px;
    }}
    .sr-alert-green {{
      margin: 14px 0;
      padding: 14px 18px;
      border: 2px solid #2e7d32;
      background: #e8f5e9;
      color: #1b5e20;
      font-size: 13px;
    }}
    .sr-cap-alert {{
      margin: 14px 0;
      padding: 14px 18px;
      border: 2px solid var(--warn);
      background: #fff3e0;
      color: #4c250e;
      font-size: 13px;
      font-weight: 700;
    }}
    .sr-legacy {{
      margin: 14px 0;
      padding: 12px 16px;
      border: 1px solid var(--line);
      background: #f8fbf8;
      color: var(--muted);
      font-size: 13px;
    }}
    .rs-alert-red {{
      margin: 14px 0;
      padding: 14px 18px;
      border: 2px solid #c62828;
      background: #ffebee;
      color: #7f1515;
      font-size: 13px;
      font-weight: 700;
    }}
    .rs-alert-orange {{
      margin: 14px 0;
      padding: 14px 18px;
      border: 2px solid #e65100;
      background: #fff3e0;
      color: #6d2700;
      font-size: 13px;
    }}
    .rs-alert-yellow {{
      margin: 14px 0;
      padding: 14px 18px;
      border: 2px solid var(--warn);
      background: #fffde7;
      color: #4c370a;
      font-size: 13px;
    }}
    .rs-alert-green {{
      margin: 14px 0;
      padding: 14px 18px;
      border: 2px solid #2e7d32;
      background: #e8f5e9;
      color: #1b5e20;
      font-size: 13px;
    }}
    .rs-legacy {{
      margin: 14px 0;
      padding: 12px 16px;
      border: 1px solid var(--line);
      background: #f8fbf8;
      color: var(--muted);
      font-size: 13px;
    }}
    @media print {{
      body {{ padding: 0; background: #ffffff; }}
      main {{ border: none; }}
    }}
  </style>
</head>
<body>
<main>
  <!-- FASE 11 — Banner NO-JORC/NI 43-101 permanente al tope del reporte -->
  <div style="
    background: #1a0a00;
    border: 2px solid #c75000;
    color: #ff9060;
    padding: 10px 20px;
    font-family: monospace;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.10em;
    text-align: center;
    text-transform: uppercase;
    margin-bottom: 16px;
  ">
    ⚠ NO-JORC / NI 43-101 / EXPLORATION ONLY — Este documento NO constituye declaración de Recursos ni Reservas Minerales ⚠
  </div>

  <header>
    <div class="brand">{_escape("TerraQuantum")}</div>
    <div class="subtitle">{_escape("Reporte Técnico HTML — Exploration Only")}</div>
    <h1>{_escape("1. Encabezado")}</h1>
    <table>
      {_row("Fecha de generación", generated_utc)}
      {_row("Project ID", project_id)}
      {_row("Run ID", run_id)}
      {_row("Región", inputs.get("region"))}
      {_row("Coordenadas", _coords(inputs))}
    </table>
  </header>

{system_audit_section}

{georef_section}

{spatial_readiness_section}

{regional_scale_preflight_section}

  <section>
    <h2>2. Parámetros de Inversión</h2>
    <table>
      {_row("Profundidad", _number(inputs.get("depth"), " m"))}
      {_row("NIR", inputs.get("nir"))}
      {_row("FE", inputs.get("fe"))}
      {_row("Grilla", _grid_value(inputs))}
      {_row("Block Size", _number(inputs.get("block_size"), " m"))}
      {_row("Cutoff Radius", _number(inputs.get("cutoff_radius"), " m"))}
      {_row("Lambda Mag", inputs.get("lambda_mag"))}
      {_row("Alpha Spatial", inputs.get("alpha_spatial"))}
      {_row("Focusing", _bool_value(inputs.get("enable_focusing")))}
    </table>
  </section>

  <section>
    <h2>3. Métricas de Calidad de Inversión</h2>
    <div class="grid">
      {_metric_card("Fit Level", fit_diagnostics.get("fit_level"))}
      {_metric_card("Confidence Level", report.get("confidence_level"))}
      {_metric_card("Quality Score", observation_quality.get("quality_score"))}
      {_metric_card("Quality Level", observation_quality.get("quality_level"))}
      {_metric_card("Observaciones", observation_quality.get("observation_count"))}
      {_metric_card("Misfit Error", _number(misfit_error_percent, "%"))}
      {_metric_card("Residual Map", _number(len(residual_map), " puntos"))}
    </div>
    {favorability_alert_html}
    <table>
      {_row("Residual RMSE", fit_diagnostics.get("residual_rmse"))}
      {_row("Residual MAE", fit_diagnostics.get("residual_mae"))}
      {_row("Residual Bias", fit_diagnostics.get("residual_bias"))}
      {_row("Residual L2", fit_diagnostics.get("residual_l2"))}
      {_misfit_row(misfit_error_percent)}
      {_row("Normalized RMSE", fit_diagnostics.get("normalized_rmse"))}
      {_row("Fit Quality", fit_diagnostics.get("fit_quality"))}
      {_row("Nivel Técnico Global", technical_summary.get("overall_level"))}
      {_priority_class_row(report.get("priority_class"))}
      {_row("Confiabilidad Técnica del Modelo", report.get("model_reliability_level") or report.get("confidence_level"))}
      {_relative_score_row("Score Relativo Máximo", report.get("max_ranking_score") or report.get("max_target_score"))}
      {_row("MS-x Focusing", "Soporte exploratorio; no es estimación de recurso mineral ni densidad física absoluta.")}
      {_row("Resumen Técnico", technical_summary.get("summary"))}
      {_row("Incertidumbre", uncertainty_diagnostics.get("uncertainty_level"))}
      {_row("Acción Recomendada", uncertainty_diagnostics.get("recommended_action"))}
    </table>
    <h3>Hallazgos Clave</h3>
    {_list_html(technical_summary.get("key_findings"))}
    <h3>Warnings</h3>
    {_list_html(technical_summary.get("warnings") or observation_quality.get("warnings"))}
    {priority_class_warnings_html}
    <h3>Recommended Next Steps</h3>
    {_list_html(technical_summary.get("recommended_next_steps"))}
  </section>

{chi_squared_section}

  <section>
    <h2>4. Target Geofísico Principal</h2>
    <table>
      {_row("X", _number(best_target.get("x_m"), " m"))}
      {_row("Y", _number(best_target.get("y_m"), " m"))}
      {_row("Z", _number(best_target.get("z_m"), " m"))}
      {_row("Densidad", best_target.get("density"))}
      {_relative_score_row("Score Relativo del Target", best_target.get("relative_target_score") or best_target.get("target_score") or best_target.get("probability"))}
      {_row("Ley Proxy", _number(best_target.get("grade"), " %"))}
      {_row("Confidence Level", best_target.get("confidence_level"))}
    </table>
  </section>

{favorability_section}

{spatial_readiness_cap_section}

{mining_section}

  <section>
    <h2>7. Disclaimer Obligatorio — NI 43-101 / JORC / SAMREC Compliance</h2>
    <div class="disclaimer">{_escape(disclaimer_full)}</div>
  </section>

  <footer>
    {_escape("TerraQuantum Backend")} v{_escape(APP_VERSION)} | {_escape(generated_utc)}
  </footer>
</main>
</body>
</html>
"""


def _check_economic_gate(
    favorability: dict | None,
    technical_summary: dict | None,
    observation_quality: dict | None,
) -> dict:
    """Evalúa si las métricas económicas/mineras deben mostrarse."""
    if favorability is None:
        return {
            "enabled": False,
            "state": "NOT_EVALUATED",
            "reasons": ["Favorabilidad no evaluada para esta corrida"],
        }

    favorability_data = _as_dict(favorability)
    technical_summary_data = _as_dict(technical_summary)
    observation_quality_data = _as_dict(observation_quality)

    raw_score = favorability_data.get("score", 0)
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        score = 0.0

    score_text = f"{score:g}"
    level = str(favorability_data.get("level") or "").strip().upper()
    overall_level = str(
        technical_summary_data.get("overall_level") or ""
    ).strip().upper()
    quality_label = str(
        observation_quality_data.get("quality_label")
        or observation_quality_data.get("quality_level")
        or ""
    ).strip().upper()

    reasons: list[str] = []
    if score < 25.0 or level == "MUY BAJO":
        reasons.append(f"Favorabilidad MUY BAJA (score={score_text}/100)")
    if overall_level == "LOW":
        reasons.append("Calidad técnica del modelo: BAJA (overall_level=LOW)")
    if quality_label in ("BAJA", "INSUFICIENTE"):
        reasons.append(f"Calidad del dataset de entrada: {quality_label}")

    if reasons:
        return {"enabled": False, "state": "GATE_FAIL", "reasons": reasons}

    return {"enabled": True, "state": "GATE_PASS", "reasons": []}


def _mining_section_html(metrics: dict[str, Any] | None, economic_gate: dict) -> str:
    state = economic_gate.get("state")
    reasons = _as_list(economic_gate.get("reasons"))

    if state == "NOT_EVALUATED":
        return f"""
  <section>
    <h2>6. Evaluación Económica/Minera No Evaluada</h2>
    <p>{_escape("No existe evaluación de favorabilidad suficiente para habilitar métricas económicas/mineras.")}</p>
  </section>
"""

    if state != "GATE_PASS":
        return f"""
  <section>
    <h2>6. Evaluación Económica/Minera No Habilitada</h2>
    <div class="fav-disclaimer">
      {_escape("🚫 Escenario económico/minero no habilitado por evidencia insuficiente.")}
    </div>
    <h3>Motivos del bloqueo</h3>
    {_list_html(reasons)}
    <p><strong>{_escape("No usar para decisión económica, diseño minero, inversión, recursos ni reservas.")}</strong></p>
  </section>
"""

    metrics_data = _as_dict(metrics)
    return f"""
  <section>
    <h2>6. Escenario Minero Conceptual (No Operativo)</h2>
    <div class="fav-disclaimer">
      {_escape("Estos valores son conceptuales y no constituyen una evaluación económica bancable.")}
      <br>
      {_escape("Requieren perforación, geoquímica y estudio profesional.")}
    </div>
    <div class="grid">
      {_metric_card("NPV Conceptual — no validado", _money(metrics_data.get("npv")))}
      {_metric_card("Tonelaje Proxy del Modelo", _number(metrics_data.get("tonnage"), " t"))}
      {_metric_card("Ley Promedio Proxy", _number(metrics_data.get("avg_grade"), " %"))}
      {_metric_card("Strip Ratio Proxy", _number(metrics_data.get("strip_ratio")))}
      {_metric_card("LOM Conceptual", _number(metrics_data.get("lom_years"), " años"))}
      {_metric_card("Cutoff Conceptual", _number(metrics_data.get("cutoff_grade"), " %"))}
      {_metric_card("Ore Proxy no validado", _number(metrics_data.get("ore_tonnage"), " t"))}
      {_metric_card("Waste Proxy no validado", _number(metrics_data.get("waste_tonnage"), " t"))}
      {_metric_card("Bloques Totales", _number(metrics_data.get("total_blocks")))}
      {_metric_card("Pit Mesh Mode", metrics_data.get("pit_mesh_mode"))}
    </div>
  </section>
"""


def _favorability_section_html(favorability: dict[str, Any] | None) -> str:
    if favorability is None:
        return ""

    factors = _as_list(favorability.get("factors"))
    factor_rows = "".join(_fav_factor_row(factor) for factor in factors)
    if not factor_rows:
        factor_rows = (
            '<tr><td colspan="6">'
            f"{_escape('No disponible')}"
            "</td></tr>"
        )

    gates = _as_dict(favorability.get("gates"))
    quality_gate = _as_dict(gates.get("quality_gate"))
    uncertainty_gate = _as_dict(gates.get("uncertainty_gate"))
    scoring_detail = _as_dict(favorability.get("scoring_detail"))

    quality_cap = quality_gate.get("cap")
    quality_cap_text = "sin cap" if quality_cap is None else _fav_number(quality_cap, 1)
    quality_gate_text = (
        f"{_value(quality_gate.get('label'))} "
        f"(×{_fav_number(quality_gate.get('multiplier'), 2)}, cap={quality_cap_text})"
    )
    uncertainty_gate_text = (
        f"score={_fav_number(uncertainty_gate.get('score'), 3)}, "
        f"multiplicador=×{_fav_number(uncertainty_gate.get('multiplier'), 2)}"
    )

    return f"""
  <section>
    <h2>5. Análisis de Favorabilidad Exploratoria</h2>

    <div class="fav-disclaimer">
      {_escape("⚠ Score exploratorio. No confirma mineral, recurso, reserva ni factibilidad económica.")}
    </div>

    <div class="grid">
      {_metric_card("Score Global (0-100)", _fav_number(favorability.get("score"), 1))}
      {_metric_card("Nivel", favorability.get("level"))}
      {_metric_card("Versión", favorability.get("version"))}
      {_metric_card("Calculado", favorability.get("computed_at"))}
    </div>

    <h3>Desglose de Factores</h3>
    <table class="fav-table">
      <thead>
        <tr>
          <th>Factor</th>
          <th>Valor (0-1)</th>
          <th>Peso</th>
          <th>Puntos</th>
          <th>Estado</th>
          <th>Explicación</th>
        </tr>
      </thead>
      <tbody>
        {factor_rows}
      </tbody>
    </table>

    <h3>Quality Gates Aplicados</h3>
    <table>
      {_row("Quality Gate", quality_gate_text)}
      {_row("Fuente Quality Gate", quality_gate.get("source"))}
      {_row("Uncertainty Gate", uncertainty_gate_text)}
      {_row("Fuente Uncertainty Gate", uncertainty_gate.get("source"))}
    </table>

    <h3>Detalle de Cálculo</h3>
    <table>
      {_row("Score evidencia ponderada", _fav_number(scoring_detail.get("weighted_evidence_score"), 3))}
      {_row("Suma pesos evaluados", _fav_number(scoring_detail.get("evaluated_weight_sum"), 3))}
      {_row("Score bruto antes de cap", _fav_number(scoring_detail.get("raw_score_before_cap"), 3))}
      {_row("Score final", _fav_number(scoring_detail.get("final_score"), 1))}
    </table>

    <h3>Advertencias</h3>
    {_list_html(favorability.get("warnings"))}
  </section>
"""


def _fav_factor_row(factor: Any) -> str:
    factor_data = _as_dict(factor)
    status = str(factor_data.get("status") or "").lower()
    is_not_evaluated = status == "not_evaluated"
    row_class = ' class="fav-not-evaluated"' if is_not_evaluated else ""

    value = "—" if is_not_evaluated else _fav_number(factor_data.get("value"), 3)
    points = "—" if is_not_evaluated else _fav_number(factor_data.get("points"), 2)
    state = (
        "No evaluado"
        if is_not_evaluated
        else "Evaluado"
        if status == "evaluated"
        else _value(factor_data.get("status"))
    )

    return (
        f"<tr{row_class}>"
        f"<td>{_escape(_value(factor_data.get('label')))}</td>"
        f"<td>{_escape(value)}</td>"
        f"<td>{_escape(_fav_percent(factor_data.get('weight')))}</td>"
        f"<td>{_escape(points)}</td>"
        f"<td>{_escape(state)}</td>"
        f"<td>{_escape(_value(factor_data.get('explanation')))}</td>"
        "</tr>"
    )


def _fav_number(value: Any, decimals: int) -> str:
    if value is None or value == "":
        return "No disponible"
    if isinstance(value, bool):
        return _bool_value(value)
    if isinstance(value, (int, float)):
        return f"{value:,.{decimals}f}"
    return str(value)


def _fav_percent(value: Any) -> str:
    if value is None or value == "":
        return "No disponible"
    if isinstance(value, bool):
        return _bool_value(value)
    if isinstance(value, (int, float)):
        return f"{value * 100:,.0f}%"
    return str(value)


def _read_required_json(path: Path | None, label: str) -> dict[str, Any]:
    if path is None:
        raise ValueError(f"No se pudo resolver la ruta de {label}.")
    if not path.exists() or not path.is_file():
        raise ValueError(f"No existe el archivo requerido {label}: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError(f"{label} no contiene un objeto JSON válido.")

    return data


def _read_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists() or not path.is_file():
        return None

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    return data


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _value(value: Any) -> str:
    if value is None or value == "":
        return "No disponible"
    return str(value)


def _number(value: Any, suffix: str = "") -> str:
    if value is None or value == "":
        return "No disponible"
    if isinstance(value, bool):
        return _bool_value(value)
    if isinstance(value, (int, float)):
        return f"{value:,.6g}{suffix}"
    return f"{value}{suffix}"


def _money(value: Any) -> str:
    if value is None or value == "":
        return "No disponible"
    if isinstance(value, (int, float)):
        return f"USD {value:,.2f}"
    return str(value)


def _bool_value(value: Any) -> str:
    if isinstance(value, bool):
        return "Sí" if value else "No"
    if value is None:
        return "No disponible"
    return str(value)


def _coords(inputs: dict[str, Any]) -> str:
    lat = _value(inputs.get("lat"))
    lon = _value(inputs.get("lon"))
    return f"Lat {lat}, Lon {lon}"


def _grid_value(inputs: dict[str, Any]) -> str:
    nx = _value(inputs.get("nx"))
    ny = _value(inputs.get("ny"))
    nz = _value(inputs.get("nz"))
    return f"{nx} x {ny} x {nz}"


def _row(label: str, value: Any) -> str:
    return f"<tr><th>{_escape(label)}</th><td>{_escape(_value(value))}</td></tr>"


def _misfit_row(value: Any) -> str:
    return (
        "<tr><th>Misfit</th><td>"
        f"<strong>Error Misfit (Residual):</strong> {_escape(_number(value, '%'))} "
        f"<em>{_escape('(Diferencia matemática entre la gravedad observada y el modelo 3D)')}</em>"
        "</td></tr>"
    )


def _metric_card(label: str, value: Any) -> str:
    return (
        f'<div class="metric">'
        f'<span class="metric-label">{_escape(label)}</span>'
        f'<span class="metric-value">{_escape(_value(value))}</span>'
        f"</div>"
    )


def _list_html(value: Any) -> str:
    items = _as_list(value)
    if not items:
        return f"<p>{_escape('No disponible')}</p>"

    entries = "".join(f"<li>{_escape(_value(item))}</li>" for item in items)
    return f"<ul>{entries}</ul>"


def _priority_class_row(priority_class_val: Any) -> str:
    pc = str(priority_class_val or "UNCLASSIFIED_INSUFFICIENT_CONFIDENCE")
    label_map = {
        "HIGH_RELATIVE_PRIORITY":               "Alta prioridad relativa",
        "MEDIUM_RELATIVE_PRIORITY":             "Prioridad media relativa",
        "LOW_RELATIVE_PRIORITY":                "Baja prioridad relativa",
        "UNCLASSIFIED_INSUFFICIENT_CONFIDENCE": "Sin clasificar — confianza insuficiente",
    }
    display = label_map.get(pc, pc)
    note = (
        "Esta clase no representa una recomendación de perforación. "
        "Es una priorización relativa basada en evidencia geofísica y controles de calidad."
    )
    return (
        f"<tr><th>{_escape('Clase de Prioridad Relativa')}</th>"
        f"<td><strong>{_escape(display)}</strong>"
        f"<br><small style='color:var(--muted)'>{_escape(note)}</small></td></tr>"
    )


def _relative_score_row(label: str, value: Any) -> str:
    note = (
        "Score relativo al modelo generado. "
        "No es probabilidad real de mineralización ni probabilidad de éxito."
    )
    return (
        f"<tr><th>{_escape(label)}</th>"
        f"<td>{_escape(_number(value))}"
        f"<br><small style='color:var(--muted)'>{_escape(note)}</small></td></tr>"
    )


def _georef_section_html(confidence: str, footprint_data: "dict | None") -> str:
    confidence = str(confidence or "MISSING").upper()

    fp = footprint_data if isinstance(footprint_data, dict) else {}

    fp_source = _value(fp.get("source")) if fp else "No disponible"
    fp_type = _value(fp.get("type")) if fp else "No disponible"
    fp_crs = _value(fp.get("crs")) if fp else "No disponible"
    fp_utm_zone_raw = fp.get("utm_zone") if fp else None
    fp_utm_zone = str(fp_utm_zone_raw) if fp_utm_zone_raw else "Desconocida"

    center_lat = fp.get("center_lat") if fp else None
    center_lon = fp.get("center_lon") if fp else None
    if center_lat is not None and center_lon is not None:
        center_str = f"{center_lat:.6f}, {center_lon:.6f}"
    else:
        center_str = "No disponible"

    extent_x = fp.get("extent_x_m") if fp else None
    extent_z = fp.get("extent_z_m") if fp else None
    if extent_x is not None and extent_z is not None:
        extent_str = f"{extent_x:,.0f} m E-O × {extent_z:,.0f} m N-S"
    else:
        extent_str = "No disponible"

    sw = fp.get("sw") if fp else None
    ne = fp.get("ne") if fp else None
    sw_str = "No disponible"
    ne_str = "No disponible"
    if isinstance(sw, dict) and sw.get("lat") is not None and sw.get("lon") is not None:
        sw_str = f"{sw['lat']:.6f}, {sw['lon']:.6f}"
    if isinstance(ne, dict) and ne.get("lat") is not None and ne.get("lon") is not None:
        ne_str = f"{ne['lat']:.6f}, {ne['lon']:.6f}"

    fp_warnings = fp.get("warnings", []) if fp else []
    fp_warnings = [w for w in fp_warnings if w] if isinstance(fp_warnings, list) else []
    fp_notes = fp.get("precision_notes", []) if fp else []
    fp_notes = [n for n in fp_notes if n] if isinstance(fp_notes, list) else []

    badge_label = {
        "HIGH": "Confianza ALTA",
        "MEDIUM": "Confianza MEDIA",
        "LOW": "Confianza BAJA",
        "MISSING": "Sin Georreferenciación",
    }.get(confidence, confidence)

    disclaimers = {
        "HIGH": (
            "Las coordenadas del CSV son lat/lon directas o georreferenciadas con confianza alta. "
            "El footprint representa las observaciones dentro de la precisión declarada del método. "
            "Aun así, requiere validación profesional antes de interpretación geológica."
        ),
        "MEDIUM": (
            "La georreferenciación es aproximada. El footprint es plausible, pero no debe "
            "interpretarse como posición exacta sin revisión profesional."
        ),
        "LOW": (
            "Metros locales anclados a punto central o sistema de baja confianza. "
            "El footprint es una estimación derivada. El terreno visible debe tratarse como "
            "contexto visual, no como topografía co-registrada con el survey."
        ),
        "MISSING": (
            "Sin georreferenciación absoluta disponible. El modelo opera en coordenadas "
            "locales y no puede ubicarse defensablemente en el mapa."
        ),
    }
    disclaimer_text = disclaimers.get(confidence, "Nivel de confianza desconocido.")

    all_warnings = fp_warnings + fp_notes
    if all_warnings:
        warning_items = "".join(
            f"<li>{_escape(w)}</li>" for w in all_warnings
        )
        warnings_html = (
            f'<div class="georef-warnings">'
            f"<strong>{_escape('Advertencias:')}</strong>"
            f"<ul>{warning_items}</ul>"
            f"</div>"
        )
    else:
        warnings_html = ""

    return (
        f'\n  <section id="georef">\n'
        f"    <h2>{_escape('Georreferenciación del Proyecto')}</h2>\n"
        f'    <div class="georef-badge georef-{confidence}">'
        f"{_escape('Nivel de confianza: ' + badge_label)}"
        f"</div>\n"
        f"    <table>\n"
        f"      {_row('Sistema de coordenadas detectado', fp_source)}\n"
        f"      {_row('Tipo de footprint', fp_type)}\n"
        f"      {_row('CRS', fp_crs)}\n"
        f"      {_row('Zona UTM', fp_utm_zone)}\n"
        f"      {_row('Centro geográfico', center_str)}\n"
        f"      {_row('Extensión del survey', extent_str)}\n"
        f"      {_row('Esquina SW', sw_str)}\n"
        f"      {_row('Esquina NE', ne_str)}\n"
        f"    </table>\n"
        f"    {warnings_html}\n"
        f'    <div class="georef-disclaimer">'
        f"{_escape(disclaimer_text)}"
        f"</div>\n"
        f"  </section>\n"
    )


def _favorability_alert_html(favorability: "dict[str, Any] | None") -> str:
    if not favorability:
        return ""
    try:
        score = float(favorability.get("score", 100.0))
    except (TypeError, ValueError):
        return ""
    level = _value(favorability.get("level"))
    if score < 25.0:
        msg = (
            f"Evidencia exploratoria insuficiente para priorización alta: "
            f"score de favorabilidad = {score:.1f}/100 ({level}). "
            "No se puede sustentar una priorización alta con este nivel de evidencia."
        )
        return (
            f'<div class="fav-disclaimer" style="margin-top:12px">'
            f"{_escape('⚠ ' + msg)}"
            f"</div>"
        )
    return ""


def _regional_scale_preflight_section_html(
    rsp_raw: "dict | None",
    ack_regional: "bool | None" = None,
) -> str:
    """R3.7-E — Sección HTML 'Escala del Dataset'."""
    if not rsp_raw:
        return (
            '\n  <section id="regional-scale">\n'
            "    <h2>Escala del Dataset</h2>\n"
            '    <div class="rs-legacy">'
            f"{_escape('Preflight de escala no disponible para esta corrida histórica.')}"
            "</div>\n"
            "  </section>\n"
        )

    rsp = _as_dict(rsp_raw)
    scale_class = str(rsp.get("scale_class") or "UNKNOWN_SCALE")
    can_run = _bool_value(rsp.get("can_run_single_inversion"))
    requires_ack = _bool_value(rsp.get("requires_user_acknowledgement"))
    ack_delivered = _bool_value(ack_regional) if ack_regional is not None else "No aplica"
    recommended_action = _value(rsp.get("recommended_action"))
    rationale = _value(rsp.get("rationale"))

    extent_x = rsp.get("extent_x_m")
    extent_z = rsp.get("extent_z_m")
    area_km2 = rsp.get("area_km2")
    station_count = rsp.get("station_count")
    est_nx = rsp.get("estimated_nx")
    est_ny = rsp.get("estimated_ny")
    est_nz = rsp.get("estimated_nz")
    est_voxel_count = rsp.get("estimated_voxel_count")
    est_depth_m = rsp.get("estimated_depth_m")
    est_block_size = rsp.get("estimated_block_size_m")
    max_nx = rsp.get("max_allowed_nx")
    max_ny = rsp.get("max_allowed_ny")
    max_nz = rsp.get("max_allowed_nz")
    warnings_list = _as_list(rsp.get("warnings"))
    blocked_reasons = _as_list(rsp.get("blocked_reasons"))
    allowed_outputs = _as_list(rsp.get("allowed_outputs"))

    extent_str = (
        f"{extent_x:,.0f} m × {extent_z:,.0f} m"
        if isinstance(extent_x, (int, float)) and isinstance(extent_z, (int, float))
        else "No disponible"
    )
    grid_str = (
        f"{est_nx} × {est_ny} × {est_nz}"
        if est_nx is not None and est_ny is not None and est_nz is not None
        else "No disponible"
    )
    max_grid_str = (
        f"{max_nx} × {max_ny} × {max_nz}"
        if max_nx is not None and max_ny is not None and max_nz is not None
        else "No disponible"
    )

    if scale_class == "TOO_LARGE_SINGLE_INVERSION":
        alert_class = "rs-alert-red"
        alert_msg = (
            "El dataset excede los límites de inversión única. "
            "Use un recorte/subset o tileado."
        )
    elif scale_class == "REGIONAL_SCALE":
        alert_class = "rs-alert-orange"
        alert_msg = (
            "El dataset corresponde a escala regional. La interpretación como modelo minero "
            "local requiere cautela y validación profesional."
        )
    elif scale_class == "DISTRICT_SCALE":
        alert_class = "rs-alert-yellow"
        alert_msg = (
            "El dataset cubre escala distrital; revise profundidad y parámetros antes de "
            "interpretación local."
        )
    elif scale_class == "LOCAL_SURVEY":
        alert_class = "rs-alert-green"
        alert_msg = (
            "La escala del dataset es compatible con una inversión local preliminar, "
            "sujeta a validación profesional."
        )
    else:
        alert_class = "sr-alert-yellow"
        alert_msg = "Clase de escala no determinada. Interpretar con cautela."

    return (
        '\n  <section id="regional-scale">\n'
        "    <h2>Escala del Dataset</h2>\n"
        f'    <div class="{alert_class}">{_escape(alert_msg)}</div>\n'
        "    <table>\n"
        f"      {_row('Clase de escala', scale_class)}\n"
        f"      {_row('Puede ejecutar inversión única', can_run)}\n"
        f"      {_row('Requiere acknowledgement', requires_ack)}\n"
        f"      {_row('Acknowledgement entregado', ack_delivered)}\n"
        f"      {_row('Acción recomendada', recommended_action)}\n"
        f"      {_row('Extensión X × Z', extent_str)}\n"
        f"      {_row('Área km²', _number(area_km2, ' km²'))}\n"
        f"      {_row('Estaciones', _number(station_count))}\n"
        f"      {_row('Grilla estimada (nx×ny×nz)', grid_str)}\n"
        f"      {_row('Vóxeles estimados', _number(est_voxel_count))}\n"
        f"      {_row('Profundidad estimada', _number(est_depth_m, ' m'))}\n"
        f"      {_row('Block size estimado', _number(est_block_size, ' m'))}\n"
        f"      {_row('Límites máximos (nx×ny×nz)', max_grid_str)}\n"
        "    </table>\n"
        "    <h3>Warnings</h3>\n"
        f"    {_list_html(warnings_list)}\n"
        "    <h3>Razones de bloqueo</h3>\n"
        f"    {_list_html(blocked_reasons)}\n"
        "    <h3>Outputs permitidos</h3>\n"
        f"    {_list_html(allowed_outputs)}\n"
        "    <h3>Rationale</h3>\n"
        f"    <p>{_escape(rationale)}</p>\n"
        "  </section>\n"
    )


def _spatial_readiness_section_html(sr_raw: "dict | None") -> str:
    """R3.5-G — Sección HTML 'Contrato Espacial de Entrada'."""
    if not sr_raw:
        return (
            '\n  <section id="spatial-contract">\n'
            "    <h2>Contrato Espacial de Entrada</h2>\n"
            '    <div class="sr-legacy">'
            f"{_escape('Contrato espacial de entrada no disponible para esta corrida histórica.')}"
            "</div>\n"
            "  </section>\n"
        )

    sr = _as_dict(sr_raw)
    level = str(sr.get("level") or "NO_SPATIAL_DATA")
    level_rank = _value(sr.get("level_rank"))
    can_run_3d = _bool_value(sr.get("can_run_3d_inversion"))
    can_use_dem = _bool_value(sr.get("can_use_dem"))
    can_masl = _bool_value(sr.get("can_compute_voxel_masl"))
    can_latlon = _bool_value(sr.get("can_compute_voxel_latlon"))
    requires_ack = _bool_value(sr.get("requires_user_acknowledgement"))
    required_ack = _value(sr.get("required_acknowledgement"))
    max_prio = _value(sr.get("max_priority_class_allowed"))
    max_fav = _fav_number(sr.get("max_favorability_score_allowed"), 1)
    rationale = _value(sr.get("rationale"))
    missing_fields = _as_list(sr.get("missing_fields"))
    allowed_outputs = _as_list(sr.get("allowed_outputs"))
    blocked_outputs = _as_list(sr.get("blocked_outputs"))
    warnings_list = _as_list(sr.get("warnings"))

    _no_spatial = {"NO_SPATIAL_DATA"}
    _conceptual = {"LOCAL_UNANCHORED", "LOCAL_ANCHORED_CENTER", "UTM_NO_ZONE"}
    _preliminary = {"UTM_WITH_ZONE", "GEOGRAPHIC_COORDS", "PROFESSIONAL_SURVEY"}

    if level in _no_spatial:
        alert_class = "sr-alert-red"
        alert_msg = (
            "Este CSV no contiene coordenadas por estación; "
            "no se puede ejecutar una inversión 3D defendible."
        )
    elif level in _conceptual:
        alert_class = "sr-alert-yellow"
        alert_msg = (
            "El modelo está permitido solo bajo condiciones conceptuales/degradadas. "
            "La interpretación espacial absoluta está limitada."
        )
    elif level in _preliminary:
        alert_class = "sr-alert-green"
        alert_msg = (
            "El input contiene geometría suficiente para análisis espacial preliminar, "
            "sujeto a validación profesional."
        )
    else:
        alert_class = "sr-alert-yellow"
        alert_msg = "Nivel espacial no reconocido. Interpretar con cautela."

    return (
        '\n  <section id="spatial-contract">\n'
        "    <h2>Contrato Espacial de Entrada</h2>\n"
        f'    <div class="{alert_class}">{_escape(alert_msg)}</div>\n'
        "    <table>\n"
        f"      {_row('Nivel SpatialReadiness', level)}\n"
        f"      {_row('Rank', level_rank)}\n"
        f"      {_row('Puede ejecutar inversión 3D', can_run_3d)}\n"
        f"      {_row('Puede usar DEM', can_use_dem)}\n"
        f"      {_row('Puede calcular elevación MASL', can_masl)}\n"
        f"      {_row('Puede calcular lat/lon por voxel', can_latlon)}\n"
        f"      {_row('Requiere acknowledgement', requires_ack)}\n"
        f"      {_row('Acknowledgement requerido', required_ack)}\n"
        f"      {_row('Máxima prioridad permitida', max_prio)}\n"
        f"      {_row('Máxima favorabilidad permitida', max_fav)}\n"
        "    </table>\n"
        "    <h3>Campos Faltantes</h3>\n"
        f"    {_list_html(missing_fields)}\n"
        "    <h3>Outputs Permitidos</h3>\n"
        f"    {_list_html(allowed_outputs)}\n"
        "    <h3>Outputs Bloqueados</h3>\n"
        f"    {_list_html(blocked_outputs)}\n"
        "    <h3>Warnings</h3>\n"
        f"    {_list_html(warnings_list)}\n"
        "    <h3>Rationale</h3>\n"
        f"    <p>{_escape(rationale)}</p>\n"
        "  </section>\n"
    )


def _chi_squared_section_html(fit_diagnostics: "dict[str, Any]") -> str:
    """Sección visual de diagnóstico chi-squared con semáforo QA geofísico industrial."""
    chi_sq = fit_diagnostics.get("chi_squared")
    chi_sq_display = "No disponible"
    status = "N/A"
    color = "#6b7280"
    badge_text_color = "#ffffff"
    message = "Run histórico sin métrica chi-squared."

    if chi_sq is not None:
        try:
            chi_sq_val = float(chi_sq)
            chi_sq_display = f"{chi_sq_val:.4f}"
            if chi_sq_val < 1.5:
                status = "ÓPTIMO"
                color = "#22c55e"
                badge_text_color = "#ffffff"
                message = "El modelo reproduce los datos dentro del ruido esperado."
            elif chi_sq_val <= 3.0:
                status = "ALERTA"
                color = "#facc15"
                badge_text_color = "#1a1600"
                message = "Sobreajuste moderado o modelo de ruido subestimado."
            else:
                status = "PELIGRO"
                color = "#ef4444"
                badge_text_color = "#ffffff"
                message = "Inconsistencia grave. No confiar en el resultado sin revisión."
        except (TypeError, ValueError):
            pass

    return f"""
  <section id="fit-diagnostics-chi" style="margin: 24px 0;">
    <h2>Diagnóstico de Ajuste (Fit Diagnostics)</h2>
    <div style="
      background: #0f1a11;
      border: 2px solid {color};
      padding: 18px 22px;
      font-family: monospace;
      font-size: 13px;
    ">
      <div style="display:flex; align-items:center; gap:14px; margin-bottom:16px;">
        <span style="
          background: {color};
          color: {badge_text_color};
          font-weight: 700;
          font-size: 11px;
          padding: 4px 14px;
          letter-spacing: 0.16em;
          text-transform: uppercase;
        ">{_escape(status)}</span>
        <span style="color:#6aaa78; font-size:12px; font-weight:700;
                     letter-spacing:0.12em; text-transform:uppercase;">
          χ² Chi-Squared — QA Geofísico Industrial
        </span>
      </div>
      <table style="width:100%; border-collapse:collapse; color:#c2d8c4;">
        <tr>
          <td style="padding:5px 10px; color:#6aaa78; white-space:nowrap; width:230px;">
            χ² (Chi-Squared)
          </td>
          <td style="padding:5px 10px; font-weight:700; color:{color}; font-size:17px;">
            {_escape(chi_sq_display)}
          </td>
        </tr>
        <tr>
          <td style="padding:5px 10px; color:#6aaa78; white-space:nowrap;">Estado QA</td>
          <td style="padding:5px 10px; font-weight:700; color:{color}; font-size:13px;">
            {_escape(status)}
          </td>
        </tr>
        <tr>
          <td style="padding:5px 10px; color:#6aaa78; white-space:nowrap;">Interpretación</td>
          <td style="padding:5px 10px; color:#c2d8c4;">{_escape(message)}</td>
        </tr>
      </table>
      <div style="margin-top:10px; color:#4a7a52; font-size:10px; border-top:1px solid #1a3a20; padding-top:8px;">
        χ² &lt; 1.5 = ÓPTIMO &nbsp;|&nbsp; 1.5 – 3.0 = ALERTA &nbsp;|&nbsp; &gt; 3.0 = PELIGRO &nbsp;|&nbsp; N/A = run histórico sin esta métrica
      </div>
    </div>
  </section>
"""


def _spatial_readiness_cap_section_html(sr_cap: "dict | None") -> str:
    """R3.5-G — Sección HTML 'Limitación por Suficiencia Espacial'."""
    if not sr_cap:
        return ""

    cap = _as_dict(sr_cap)
    applied = cap.get("applied")
    max_fav_val = cap.get("max_favorability_score_allowed")
    max_prio_val = _value(cap.get("max_priority_class_allowed"))

    if not applied:
        return (
            '\n  <section id="spatial-cap">\n'
            "    <h2>Limitación por Suficiencia Espacial</h2>\n"
            f"    <p>{_escape('Cap espacial no aplicado a esta corrida.')}</p>\n"
            "    <table>\n"
            f"      {_row('Aplicado', _bool_value(applied))}\n"
            f"      {_row('Máxima favorabilidad permitida', _fav_number(max_fav_val, 1))}\n"
            f"      {_row('Máxima prioridad permitida', max_prio_val)}\n"
            "    </table>\n"
            "  </section>\n"
        )

    original = cap.get("original_favorability_score")
    capped = cap.get("capped_favorability_score")
    reason = _value(cap.get("reason"))
    cap_warnings = _as_list(cap.get("warnings"))

    return (
        '\n  <section id="spatial-cap">\n'
        "    <h2>Limitación por Suficiencia Espacial</h2>\n"
        '    <div class="sr-cap-alert">'
        f"{_escape('La favorabilidad/prioridad fue limitada porque el input no tiene suficiencia espacial para una clasificación superior.')}"
        "</div>\n"
        "    <table>\n"
        f"      {_row('Aplicado', _bool_value(applied))}\n"
        f"      {_row('Favorabilidad original', _fav_number(original, 1))}\n"
        f"      {_row('Favorabilidad capada', _fav_number(capped, 1))}\n"
        f"      {_row('Máxima favorabilidad permitida', _fav_number(max_fav_val, 1))}\n"
        f"      {_row('Máxima prioridad permitida', max_prio_val)}\n"
        f"      {_row('Razón', reason)}\n"
        "    </table>\n"
        "    <h3>Warnings del Cap</h3>\n"
        f"    {_list_html(cap_warnings)}\n"
        "  </section>\n"
    )
