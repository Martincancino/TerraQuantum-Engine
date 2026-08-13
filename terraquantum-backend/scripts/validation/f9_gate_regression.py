# -*- coding: utf-8 -*-
"""GATE F9 — Validación física como regresión automática.

Corre A DEMANDA (semanal / pre-release, NO en cada commit) la suite de regresión
física: RE-INVIERTE el motor real sobre los datasets canónicos (DO-27, Raglan,
San Nicolás, LdM) + sintéticos, con tolerancias EXPLÍCITAS, y emite:

  1. Veredicto medido (PASS/FALLO) por consola.
  2. Reporte JSON     → scripts/validation/f9_gate_report.json
  3. Reporte HTML     → scripts/validation/f9_validation_report.html  (imprimible = PDF)

El gate PASA sólo si TODOS los casos cumplen su tolerancia. Una degradación inyectada
a propósito (p.ej. romper W_z) hace fallar la suite — ese es el punto.

Uso (desde terraquantum-backend):
    python scripts/validation/f9_gate_regression.py

La suite equivalente en pytest vive en tests/test_f9_physics_regression.py (marcada
`validation`, saltada por defecto). main()-only: no expone tests a la colección de pytest.
"""
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from scripts.validation import f9_regression_lib as F9  # noqa: E402
from scripts.validation.f9_report import render_html      # noqa: E402


def main() -> int:
    print("=" * 74)
    print("GATE F9 — Validación física como regresión automática")
    print("  (re-invierte el motor real sobre DO-27 / Raglan / San Nicolás / LdM + sintéticos)")
    print("=" * 74)

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = F9.run_all(generated_utc=generated)

    print(f"\n{'Caso':<34} {'Métrica':<28} {'Valor':>12}  {'Tol.':<22} Estado")
    print("-" * 118)
    for c in report["cases"]:
        val = c["value"]
        val_s = f"{val:g}" if isinstance(val, (int, float)) else str(val)
        estado = ("LÍMITE ✓" if c["kind"] == "documented_limit" and c["passed"]
                  else "PASS" if c["passed"] else "FALLO")
        print(f"{c['title'][:33]:<34} {str(c['metric'])[:27]:<28} {val_s:>12}  "
              f"{str(c['tolerance_str'])[:21]:<22} {estado}   ({c.get('elapsed_s')}s)")
        for s in c.get("secondary", []):
            print(f"    · {s['label']}: {s['value']}")
        if c.get("note"):
            print(f"    ↳ {c['note']}")

    verdict = report["verdict"]
    n_skipped = report.get("n_skipped", 0)
    print("\n" + "=" * 74)
    print(f"GATE F9: {verdict}   ({report['n_pass']}/{report['n_total']} casos evaluados en verde · "
          f"{report['elapsed_s']}s)")
    if n_skipped:
        # Fase 3: un PASS parcial se dice en voz alta. La CI corre sobre un
        # checkout limpio y ahí San Nicolás y LdM no existen — quien lea este
        # veredicto tiene que saber qué NO se comprobó.
        print(f"  NO EVALUADOS ({n_skipped}): {', '.join(report.get('skipped_keys', []))}"
              "  — sus datos no están versionados (data/projects/ está en .gitignore)")
    print("=" * 74)

    out_json = BACKEND / "scripts" / "validation" / "f9_gate_report.json"
    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    out_html = BACKEND / "scripts" / "validation" / "f9_validation_report.html"
    out_html.write_text(render_html(report), encoding="utf-8")
    print(f"Reporte JSON → {out_json}")
    print(f"Reporte HTML → {out_html}  (Imprimir a PDF para material de credibilidad)")

    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
