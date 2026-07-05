# -*- coding: utf-8 -*-
"""GATE F3 — El caso que mató al proxy: joint ~96k vóxeles, de punta a punta.

Reproduce el flujo del USUARIO con los fixtures multi_* (cuerpo R=170 m a
220 m, 256 estaciones co-localizadas grav+mag):
  1. enrich-package (grav + mag) con malla forzada a ~96k vóxeles.
  2. load-package ASÍNCRONO (default F3) → {queued, budget con AVISO previo}.
  3. Poll GET /geophysics-status imprimiendo el progreso por etapas reales.
  4. Verifica: done + parquet persistido + historial SQLite 'done'.
  5. Mide el tiempo total → calibración del presupuesto de vóxeles.

Correr desde terraquantum-backend:  python scripts/validation/f3_gate_joint96k.py
"""
import io
import json
import os
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

CORPUS = BACKEND / "tests" / "fixtures" / "csv_reales"
PROJECT_ID = "f3_gate"
RUN_ID = "joint96k"


def main() -> int:
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)

    grav = (CORPUS / "multi_gravimetria.csv").read_bytes()
    mag = (CORPUS / "multi_magnetometria.csv").read_bytes()

    # Malla forzada a ~96k vóxeles (48×42×48 = 96.768): el caso real del
    # diagnóstico 2026-06-30 que cortaba el proxy a los 20+ min.
    config = {"nx": 48, "ny": 42, "nz": 48, "utm_zone": "19S"}

    print("1) enrich-package (grav+mag co-localizados, malla 48x42x48)…")
    r = client.post(
        "/v2/gravity-import/enrich-package",
        files={
            "gravity_file": ("multi_gravimetria.csv", grav, "text/csv"),
            "magnetic_file": ("multi_magnetometria.csv", mag, "text/csv"),
        },
        data={"config_json": json.dumps(config)},
    )
    assert r.status_code == 200, r.text[:500]
    body = r.json()
    assert "package_text" in body, str(body)[:500]
    print(f"   paquete listo: {body['n_stations']} estaciones, ruta {body['plan'].get('route')}")

    print("2) load-package ASÍNCRONO (default F3)…")
    t0 = time.monotonic()
    r2 = client.post(
        "/v2/gravity-import/load-package",
        files={"file": ("f3gate.tqpkg.csv", body["package_text"], "text/csv")},
        data={"project_id": PROJECT_ID, "run_id": RUN_ID},
    )
    assert r2.status_code == 200, r2.text[:500]
    q = r2.json()
    assert q["status"] == "queued", str(q)[:300]
    budget = q["budget"]
    print(f"   encolado en {time.monotonic() - t0:.1f}s — presupuesto: "
          f"{budget['voxel_count']:,} vóxeles ruta {budget['route_kind']}, "
          f"~{budget['estimated_minutes']} min estimados")
    if budget["warning"]:
        print(f"   AVISO PREVIO (correcto para este tamaño): {budget['warning'][:120]}…")

    print("3) polling de progreso (cada 5 s)…")
    seen = []
    last_line = ""
    deadline = time.monotonic() + 3600 * 2
    final = None
    while time.monotonic() < deadline:
        rs = client.get(f"/geophysics-status/{PROJECT_ID}/{RUN_ID}")
        if rs.status_code == 200:
            s = rs.json()
            line = f"{s['status']} · {s.get('stage')} · {s.get('progress')} · {str(s.get('message'))[:60]}"
            if line != last_line:
                print(f"   [{time.monotonic() - t0:7.1f}s] {line}")
                last_line = line
                seen.append(s.get("stage"))
            if s["status"] in ("done", "error", "cancelled", "interrumpida"):
                final = s
                break
        time.sleep(5)

    elapsed = time.monotonic() - t0
    assert final is not None, "sin estado terminal en 2 h"
    print(f"4) terminal: {final['status']} en {elapsed / 60:.1f} min "
          f"(estimado: {budget['estimated_minutes']} min)")
    assert final["status"] == "done", f"terminó en {final['status']}: {final.get('error')}"

    from core.block_model_store import get_run_dir
    run_dir = get_run_dir(PROJECT_ID, RUN_ID)
    parquets = list(run_dir.glob("*.parquet"))
    assert parquets, f"sin parquet en {run_dir}"
    print(f"   parquets persistidos: {[p.name for p in parquets]}")

    from services import project_store
    hist = project_store.get_run(PROJECT_ID, RUN_ID)
    assert hist and hist["status"] == "done", str(hist)
    print(f"   historial SQLite: done ({hist['started_at']} → {hist['finished_at']})")

    print(f"\nGATE F3 VERDE: joint {budget['voxel_count']:,} vóxeles completó "
          f"E2E con progreso visible en {elapsed / 60:.1f} min "
          f"(etapas vistas: {sorted(set(x for x in seen if x))}).")
    print(f"CALIBRACIÓN presupuesto: medido {elapsed:.0f}s para "
          f"{budget['voxel_count']} vóxeles joint → "
          f"{elapsed / budget['voxel_count'] * 1000:.2f} ms/vóxel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
