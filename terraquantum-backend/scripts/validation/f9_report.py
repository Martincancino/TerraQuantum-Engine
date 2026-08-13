# -*- coding: utf-8 -*-
"""F9 — Reporte HTML de la suite de validación física (regresión automática).

Función pura: recibe el dict de resultados producido por `f9_regression_lib`
(o por el gate `f9_gate_regression.py`) y devuelve una página HTML autocontenida,
imprimible (=PDF vía "Imprimir a PDF" del navegador, mismo patrón que F5).

NO ejecuta física: sólo formatea. Es material de credibilidad para F10
(tabla PASS/FAIL con métricas y tolerancias explícitas).
"""
from __future__ import annotations

import html
from typing import Any, Dict, List

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
       color: #1a1f2b; background: #f6f7f9; line-height: 1.5; }
.wrap { max-width: 1080px; margin: 0 auto; padding: 32px 24px 64px; }
h1 { font-size: 1.55rem; margin: 0 0 4px; }
h2 { font-size: 1.05rem; margin: 28px 0 10px; color: #2b3444; }
.sub { color: #5b6472; font-size: .9rem; margin: 0 0 20px; }
.banner { border-radius: 12px; padding: 18px 22px; margin: 8px 0 24px; display: flex;
          align-items: center; gap: 18px; color: #fff; }
.banner.pass { background: linear-gradient(135deg, #1f8a52, #2fae6a); }
.banner.fail { background: linear-gradient(135deg, #b3261e, #d9433a); }
.banner .big { font-size: 2rem; font-weight: 700; letter-spacing: .5px; }
.banner .meta { font-size: .92rem; opacity: .95; }
table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px;
        overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.08); font-size: .9rem; }
th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #eceef1; }
th { background: #f0f2f5; font-weight: 600; color: #333c4a; font-size: .8rem;
     text-transform: uppercase; letter-spacing: .4px; }
td.num { font-variant-numeric: tabular-nums; }
.tag { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: .74rem;
       font-weight: 700; letter-spacing: .3px; }
.tag.pass { background: #d8f2e2; color: #146c3f; }
.tag.fail { background: #fbe0de; color: #a3221b; }
.tag.limit { background: #fdf0d5; color: #8a5a10; }
.card { background: #fff; border-radius: 10px; padding: 16px 18px; margin: 12px 0;
        box-shadow: 0 1px 3px rgba(0,0,0,.06); border-left: 5px solid #cfd4db; }
.card.pass { border-left-color: #2fae6a; }
.card.fail { border-left-color: #d9433a; }
.card.limit { border-left-color: #e0a53a; }
.card h3 { margin: 0 0 4px; font-size: 1rem; }
.card .ds { color: #6b7482; font-size: .82rem; margin: 0 0 8px; }
.card .row { display: flex; flex-wrap: wrap; gap: 20px; font-size: .88rem; }
.card .row b { color: #2b3444; }
.card .note { margin: 10px 0 0; font-size: .84rem; color: #55606f; font-style: italic; }
.sec { margin-top: 6px; font-size: .82rem; color: #6b7482; }
footer { margin-top: 32px; font-size: .78rem; color: #8b939f; }
@media (prefers-color-scheme: dark) {
  body { color: #e7e9ee; background: #14171d; }
  h2 { color: #c7cdd8; } .sub { color: #9aa2b0; }
  table { background: #1c2028; box-shadow: none; }
  th { background: #232833; color: #c7cdd8; } th, td { border-bottom-color: #2b313c; }
  .card { background: #1c2028; box-shadow: none; } .card .ds { color: #9aa2b0; }
  .card .row b { color: #dfe3ea; } .card .note, .sec { color: #9aa2b0; }
}
@media print {
  body { background: #fff; } .wrap { max-width: none; padding: 0; }
  .card, table { box-shadow: none; border: 1px solid #ddd; }
  .banner { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
"""


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:g}"
    return html.escape(str(v))


def _kind_tag(case: Dict[str, Any]) -> str:
    # Fase 3: un caso que no se pudo evaluar NO es un fallo de física, y decir
    # "FALLO" cuando lo que falta es el dato entrena a ignorar el reporte.
    if case.get("skipped"):
        return '<span class="tag limit">NO EVALUADO</span>'
    if case.get("kind") == "documented_limit":
        return '<span class="tag limit">LÍMITE ✓</span>' if case.get("passed") \
            else '<span class="tag fail">LÍMITE ✗</span>'
    return '<span class="tag pass">PASS</span>' if case.get("passed") \
        else '<span class="tag fail">FALLO</span>'


def _card_class(case: Dict[str, Any]) -> str:
    if case.get("skipped"):
        return "limit"
    if not case.get("passed"):
        return "fail"
    return "limit" if case.get("kind") == "documented_limit" else "pass"


def render_html(report: Dict[str, Any]) -> str:
    cases: List[Dict[str, Any]] = report.get("cases", [])
    verdict = report.get("verdict", "FALLO")
    n_pass = report.get("n_pass", sum(1 for c in cases if c.get("passed")))
    n_total = report.get("n_total", len(cases))
    ok = verdict == "PASS"

    rows = []
    for c in cases:
        val = c.get("value")
        val_s = f'{val:g} {c.get("unit","")}'.strip() if isinstance(val, (int, float)) else _fmt(val)
        rows.append(
            f"<tr><td>{_fmt(c.get('title'))}</td>"
            f"<td>{_fmt(c.get('metric'))}</td>"
            f"<td class='num'>{val_s}</td>"
            f"<td class='num'>{_fmt(c.get('tolerance_str'))}</td>"
            f"<td>{_kind_tag(c)}</td>"
            f"<td class='num'>{_fmt(c.get('elapsed_s'))}s</td></tr>"
        )

    cards = []
    for c in cases:
        sec = ""
        if c.get("secondary"):
            items = " · ".join(f"<b>{_fmt(s.get('label'))}:</b> {_fmt(s.get('value'))}"
                               for s in c["secondary"])
            sec = f"<div class='sec'>{items}</div>"
        note = f"<p class='note'>{_fmt(c.get('note'))}</p>" if c.get("note") else ""
        val = c.get("value")
        val_s = f'{val:g} {c.get("unit","")}'.strip() if isinstance(val, (int, float)) else _fmt(val)
        cards.append(
            f"<div class='card {_card_class(c)}'>"
            f"<h3>{_fmt(c.get('title'))} {_kind_tag(c)}</h3>"
            f"<p class='ds'>{_fmt(c.get('dataset'))}</p>"
            f"<div class='row'><span><b>{_fmt(c.get('metric'))}:</b> {val_s}</span>"
            f"<span><b>Tolerancia:</b> {_fmt(c.get('tolerance_str'))}</span></div>"
            f"{sec}{note}</div>"
        )

    banner_cls = "pass" if ok else "fail"
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(report.get('title', 'F9 — Validación física'))}</title>
<style>{_CSS}</style></head>
<body><div class="wrap">
<h1>TerraQuantum — F9: Validación física como regresión automática</h1>
<p class="sub">{html.escape(report.get('subtitle', 'Suite de regresión que congela la física ya validada (DO-27, Raglan, San Nicolás, LdM + sintéticos) con tolerancias explícitas.'))}
&nbsp;·&nbsp; Generado: {html.escape(str(report.get('generated_utc', '—')))}</p>

<div class="banner {banner_cls}">
  <span class="big">{'✓ PASS' if ok else '✗ FALLO'}</span>
  <span class="meta">{n_pass}/{n_total} casos en verde &nbsp;·&nbsp; tiempo total {_fmt(report.get('elapsed_s'))}s<br>
  Una degradación del motor (p.ej. romper W_z) hace fallar esta suite.</span>
</div>

<h2>Resumen</h2>
<table><thead><tr>
  <th>Caso / dataset</th><th>Métrica</th><th>Valor</th><th>Tolerancia</th><th>Estado</th><th>Tiempo</th>
</tr></thead><tbody>
{''.join(rows)}
</tbody></table>

<h2>Detalle por caso</h2>
{''.join(cards)}

<footer>
TerraQuantum · Suite de validación física (F9). Las tolerancias son explícitas y medidas: no se
tunean para pasar. La ambigüedad de profundidad de la gravimetría-sola se reporta como
LÍMITE conocido y esperado (no como fallo). Reporte imprimible → "Imprimir a PDF".
</footer>
</div></body></html>"""


if __name__ == "__main__":  # demo con datos de ejemplo
    demo = {
        "title": "F9 — Validación física", "generated_utc": "2026-07-23T00:00:00Z",
        "verdict": "PASS", "n_pass": 2, "n_total": 2, "elapsed_s": 123.4,
        "cases": [
            {"key": "do27", "title": "DO-27 (kimberlita)", "dataset": "benchmark externo",
             "kind": "regression", "metric": "error horizontal", "value": 53.7, "unit": "m",
             "tolerance_str": "≤ 70 m", "passed": True, "elapsed_s": 42.0,
             "secondary": [{"label": "misfit", "value": "1.1%"}]},
            {"key": "zamb", "title": "Ambigüedad-z (sintético)", "dataset": "límite físico",
             "kind": "documented_limit", "metric": "z-error sin restricción", "value": 2600.0,
             "unit": "m", "tolerance_str": "≥ 400 m (límite esperado)", "passed": True,
             "elapsed_s": 30.0, "note": "gravedad-sola NO resuelve profundidad; documentado."},
        ],
    }
    import pathlib
    out = pathlib.Path(__file__).with_name("f9_report_demo.html")
    out.write_text(render_html(demo), encoding="utf-8")
    print(f"demo → {out}")
