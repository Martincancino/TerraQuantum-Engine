# -*- coding: utf-8 -*-
"""F3 → F8 — Calibración del presupuesto de vóxeles (semilla de la matriz F8).

CONCLUSIÓN MEDIDA (2026-07-06, 3 intentos en la máquina de referencia): un
coeficiente CONSTANTE s/vóxel para gravity/magnetic NO existe —
  1. bloques chicos forzados (52 m, cutoff default): gravedad 10.648 vóxeles
     = 880,5 s → 82,7 ms/vóxel (11× el joint del gate);
  2. 50k vóxeles con bloque 31 m → SOLVER_KERNEL_TOO_DENSE (catalogado);
  3. la MISMA malla del gate (48×42×48) en gravity-only también cortó por
     memoria en el proceso síncrono (la RAM disponible del momento importa).
El costo lo dominan la DENSIDAD del kernel (cutoff/block) y la memoria, no
el nº de vóxeles ni de físicas. El estimador de run_queue_service declara su
base (joint MEDIDO 7,16 ms/vóxel; grav/mag heurístico) y las garantías duras
son progreso visible + cancelación + guardia de memoria catalogada. La
matriz sistemática por RÉGIMEN (block/cutoff/estaciones × tamaño) es F8.

Correr desde terraquantum-backend:
    python scripts/validation/f3_budget_calibration.py
"""
import io
import json
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

CORPUS = BACKEND / "tests" / "fixtures" / "csv_reales"

# LECCIÓN MEDIDA (intentos 1-2, 2026-07-06): el costo por vóxel NO es
# constante — lo domina la DENSIDAD del kernel (cutoff_radius/block_size) y
# el nº de estaciones, no el nº de físicas. Con bloques chicos forzados
# (52 m / depth 300) la gravedad de 10,6k vóxeles midió 82,7 ms/vóxel (11×
# el joint del gate) y 50k vóxeles murió con SOLVER_KERNEL_TOO_DENSE
# (catalogado — la guardia de memoria del F2.3 funcionó). Por eso aquí se
# mide el CAMINO DEL PRODUCTO: la MISMA malla del gate F3 (48×42×48, sin
# forzar block/depth — el pipeline elige) con una física a la vez, que es la
# comparación limpia contra el joint medido (7,16 ms/vóxel).
CASES = [
    ("gravity", "multi_gravimetria.csv", "gravity_file",
     {"nx": 48, "ny": 42, "nz": 48}),
    ("magnetic", "multi_magnetometria.csv", "magnetic_file",
     {"nx": 48, "ny": 42, "nz": 48}),
]


def main() -> int:
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    results = []

    for i, (kind, fname, field, mesh) in enumerate(CASES):
        payload = (CORPUS / fname).read_bytes()
        cfg = {**mesh, "utm_zone": "19S"}
        data = {"config_json": json.dumps(cfg)}
        if kind == "magnetic":
            data["data_type"] = "magnetic"
        r = client.post(
            "/v2/gravity-import/enrich-package",
            files={field: (fname, payload, "text/csv")},
            data=data,
        )
        assert r.status_code == 200, r.text[:400]
        pkg = r.json()["package_text"]

        voxels = mesh["nx"] * mesh["ny"] * mesh["nz"]
        t0 = time.monotonic()
        r2 = client.post(
            "/v2/gravity-import/load-package",
            files={"file": (f"cal_{i}.tqpkg.csv", pkg, "text/csv")},
            data={"sync": "true", "project_id": "f3_cal", "run_id": f"cal_{kind}_{voxels}"},
        )
        elapsed = time.monotonic() - t0
        assert r2.status_code == 200, r2.text[:400]
        assert r2.json()["status"] == "done", str(r2.json())[:300]
        ms_per_voxel = elapsed / voxels * 1000
        results.append((kind, voxels, elapsed, ms_per_voxel))
        print(f"{kind:9s} {voxels:7,} vóxeles → {elapsed:7.1f} s  ({ms_per_voxel:.3f} ms/vóxel)")

    print("\nCOEFICIENTES sugeridos (s/vóxel, medidos en el tamaño grande):")
    for kind in ("gravity", "magnetic"):
        big = [r for r in results if r[0] == kind][-1]
        print(f"  {kind}: {big[3] / 1000:.5f}")
    print("  joint: 0.00716 (gate F3, 96.768 vóxeles)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
