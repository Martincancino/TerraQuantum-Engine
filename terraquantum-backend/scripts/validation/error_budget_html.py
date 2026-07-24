# -*- coding: utf-8 -*-
"""Renderiza el reporte del presupuesto de error (Parte A) a HTML imprimible.

Función pura: recibe el dict de `error_budget.py` (o su JSON) y devuelve la tabla
honesta `error × régimen`. Uso:
    python scripts/validation/error_budget_html.py   # lee error_budget_report.json → .html
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin:0; font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
       color:#1a1f2b; background:#f6f7f9; line-height:1.45; }
.wrap { max-width:1150px; margin:0 auto; padding:32px 22px 64px; }
h1 { font-size:1.5rem; margin:0 0 4px; } h2 { font-size:1.05rem; margin:26px 0 8px; color:#2b3444; }
.sub { color:#5b6472; font-size:.9rem; margin:0 0 18px; }
.cards { display:flex; gap:14px; flex-wrap:wrap; margin:14px 0 6px; }
.kpi { flex:1 1 200px; background:#fff; border-radius:10px; padding:14px 16px; box-shadow:0 1px 3px rgba(0,0,0,.08); }
.kpi .lbl { font-size:.78rem; color:#6b7482; text-transform:uppercase; letter-spacing:.4px; }
.kpi .val { font-size:1.5rem; font-weight:700; margin-top:2px; }
.kpi.good .val { color:#1f8a52; } .kpi.bad .val { color:#c0392b; } .kpi.warn .val { color:#b9770f; }
.kpi .note { font-size:.8rem; color:#6b7482; margin-top:4px; }
.scroll { overflow-x:auto; }
table { width:100%; border-collapse:collapse; background:#fff; border-radius:10px; overflow:hidden;
        box-shadow:0 1px 3px rgba(0,0,0,.08); font-size:.86rem; min-width:820px; }
th,td { padding:8px 10px; text-align:right; border-bottom:1px solid #eceef1; font-variant-numeric:tabular-nums; }
th:first-child, td:first-child { text-align:left; }
th { background:#f0f2f5; font-weight:600; color:#333c4a; font-size:.74rem; text-transform:uppercase; letter-spacing:.3px; }
tr.axis td { background:#eef1f6; font-weight:700; color:#2b3444; text-transform:uppercase; font-size:.72rem; letter-spacing:.5px; }
.g { color:#1f8a52; font-weight:600; } .r { color:#c0392b; font-weight:600; } .w { color:#b9770f; font-weight:600; }
footer { margin-top:28px; font-size:.8rem; color:#8b939f; }
@media (prefers-color-scheme: dark) {
  body { color:#e7e9ee; background:#14171d; } h2 { color:#c7cdd8; } .sub { color:#9aa2b0; }
  .kpi, table { background:#1c2028; box-shadow:none; } th { background:#232833; color:#c7cdd8; }
  th,td { border-bottom-color:#2b313c; } tr.axis td { background:#242a35; color:#dfe3ea; }
}
@media print { body { background:#fff; } .wrap { max-width:none; padding:0; } .kpi,table { box-shadow:none; border:1px solid #ddd; } }
"""


def _n(v, suf="", dash="—"):
    if v is None:
        return dash
    return (f"{v:g}{suf}")


def _cls_horiz(v, spacing):
    if v is None:
        return "r"
    return "g" if v <= max(spacing, 200.0) else ("w" if v <= 2 * max(spacing, 200.0) else "r")


def render_html(report: Dict[str, Any]) -> str:
    cases = report.get("cases", [])
    m = report.get("mesh", {})
    base = next((c for c in cases if c["axis"] == "baseline"), None)

    # KPIs headline (baseline + rango).
    bh = base["error"]["horizontal_m"] if base else None
    bd = base["error"]["depth_centroid_m"] if base else None
    horiz_vals = [c["error"]["horizontal_m"] for c in cases if c["error"]["horizontal_m"] is not None]
    dfrac = [c["error"]["density_recovery_frac"] for c in cases if c["error"].get("density_recovery_frac") is not None]

    kpis = f"""
    <div class="cards">
      <div class="kpi good"><div class="lbl">Targeting horizontal — baseline</div>
        <div class="val">{_n(bh,' m')}</div><div class="note">la FORTALEZA: dónde perforar. Rango medido {_n(min(horiz_vals) if horiz_vals else None,' m')}–{_n(max(horiz_vals) if horiz_vals else None,' m')}.</div></div>
      <div class="kpi bad"><div class="lbl">Profundidad — baseline</div>
        <div class="val">{_n(bd,' m')}</div><div class="note">el LÍMITE: la masa se apila somera (sesgo conocido). Peor con profundidad/dispersión.</div></div>
      <div class="kpi warn"><div class="lbl">Densidad recuperada</div>
        <div class="val">{_n(round(min(dfrac)*100) if dfrac else None,'%')}–{_n(round(max(dfrac)*100) if dfrac else None,'%')}</div>
        <div class="note">la magnitud NO es confiable (compact sub-recupera; no-unicidad).</div></div>
    </div>"""

    # Tabla por eje.
    rows = []
    last_axis = None
    axis_labels = {"baseline": "Baseline (bien planteado)", "profundidad": "Eje: profundidad del cuerpo",
                   "cobertura": "Eje: densidad de cobertura", "contraste": "Eje: contraste (Δρ)",
                   "SNR": "Eje: relación señal/ruido", "extensión": "Eje: extensión del survey",
                   "compuesto": "Compuesto peor-caso"}
    for c in cases:
        if c["axis"] != last_axis:
            rows.append(f'<tr class="axis"><td colspan="9">{html.escape(axis_labels.get(c["axis"], c["axis"]))}</td></tr>')
            last_axis = c["axis"]
        e, rg = c["error"], c["regime"]
        hcls = _cls_horiz(e["horizontal_m"], rg["spacing_m"])
        rows.append(
            f"<tr><td>{html.escape(c['name'])}</td>"
            f"<td>{_n(rg['depth_m'],' m')}</td>"
            f"<td>{rg['n_stations']} · {_n(rg['spacing_m'],' m')}</td>"
            f"<td>{_n(rg['snr_peak'])}</td>"
            f"<td class='{hcls}'>{_n(e['horizontal_m'],' m')}</td>"
            f"<td class='r'>{_n(e['depth_centroid_m'],' m')}</td>"
            f"<td>{_n(e['depth_peak_m'],' m')}</td>"
            f"<td class='w'>{_n(round(e['density_recovery_frac']*100) if e.get('density_recovery_frac') is not None else None,'%')}</td>"
            f"<td>{_n(e['misfit_pct'],'%')}</td></tr>"
        )

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TerraQuantum — Presupuesto de error (Parte A)</title><style>{_CSS}</style></head>
<body><div class="wrap">
<h1>TerraQuantum — Presupuesto de error físico (Parte A)</h1>
<p class="sub">¿Cuánto nos equivocamos HOY, y DÓNDE? · Verdad analítica (esfera de forma cerrada = anti-inverse-crime) invertida con el motor real ·
malla {m.get('nx')}×{m.get('ny')}×{m.get('nz')} @ {_n(m.get('block_m'),' m')} · config validada (λ=1e-3, IRLS compacto) · {report.get('n_cases')} casos · {_n(report.get('elapsed_s'),' s')}</p>
{kpis}
<h2>Error medido por régimen</h2>
<div class="scroll"><table><thead><tr>
  <th>Caso</th><th>Prof. verdadera</th><th>Estaciones · espaciado</th><th>SNR pico</th>
  <th>Horizontal</th><th>Prof. centroide</th><th>Prof. pico</th><th>Densidad rec.</th><th>Misfit</th>
</tr></thead><tbody>
{''.join(rows)}
</tbody></table></div>
<footer>
Verde = targeting horizontal ≤ espaciado (o ≤ 200 m) = perforable. La profundidad se reporta como LÍMITE (la masa se apila somera:
el depth-weighting es inerte, hallazgo F9). La densidad recuperada es una fracción de la verdadera (no-unicidad): informativa, no cuantitativa.
Números medidos, sin ajustar. Reproducible con `python scripts/validation/error_budget.py --full`.
</footer>
</div></body></html>"""


def main():
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    d = Path(__file__).resolve().parent / "error_budget_report.json"
    report = json.loads(d.read_text(encoding="utf-8"))
    out = d.with_name("error_budget_report.html")
    out.write_text(render_html(report), encoding="utf-8")
    print(f"HTML -> {out}")


if __name__ == "__main__":
    main()
