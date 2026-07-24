# -*- coding: utf-8 -*-
"""F9 — Prueba de SENSIBILIDAD del gate: una degradación de la física lo hace FALLAR.

El criterio de salida de F9 (plan maestro) es: "una degradación inyectada a propósito
la hace fallar". Este script lo DEMUESTRA de forma reproducible, sin tocar el motor en
disco (el fallo se inyecta con un monkeypatch de proceso que se revierte al terminar).

HALLAZGO (medido, 2026-07-23): el parámetro `depth_beta` del solver gravimétrico es
ALGEBRAICAMENTE INERTE para el modelo recuperado — la normalización de columnas Ws
(gravimetry.py ~2224) absorbe el cambio de variable W_z, y el objetivo en el espacio del
modelo queda invariante a beta. Por eso "romper W_z" vía depth_beta NO cambia nada
(beta=0 y beta=2 dan resultados byte-idénticos). La palanca REAL de la física es el
operador forward. Aquí se degrada la GEOMETRÍA del kernel (los vóxeles se desplazan
800 m) y se comprueba que el targeting de Raglan colapsa y el caso FALLA.

Uso (desde terraquantum-backend):
    python scripts/validation/f9_degradation_check.py
    # exit 0 si la suite detecta la degradación (sano PASS → roto FALLO); 1 si no.
"""
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

import numpy as np  # noqa: E402

from exploration.magnetometry import MagnetometryForward  # noqa: E402
from scripts.validation import f9_regression_lib as F9      # noqa: E402

VOXEL_OFFSET_M = 800.0   # desplaza los vóxeles en el kernel → geometría forward rota


def _install_fault():
    """Patch: el kernel se construye con vóxeles desplazados 800 m (geometría rota)."""
    originals = {}
    for name in ("_build_sparse_kernel", "build_sparse_kernel"):
        orig = getattr(MagnetometryForward, name, None)
        if orig is None:
            continue
        originals[name] = orig

        def _make(orig):
            def broken(self, x_vox, y_vox, z_vox, sensors, *a, **k):
                return orig(self, np.asarray(x_vox, dtype=float) + VOXEL_OFFSET_M,
                            y_vox, z_vox, sensors, *a, **k)
            return broken

        setattr(MagnetometryForward, name, _make(orig))
    return originals


def _remove_fault(originals):
    for name, orig in originals.items():
        setattr(MagnetometryForward, name, orig)


def main() -> int:
    print("=" * 74)
    print("F9 — Prueba de sensibilidad del gate (una degradación física lo hace FALLAR)")
    print("=" * 74)

    healthy = F9.case_raglan()
    print(f"\n[SANO ]  Raglan  {healthy['metric']}={healthy['value']} m  "
          f"→ {'PASS' if healthy['passed'] else 'FALLO'}  (tol {healthy['tolerance_str']})")

    originals = _install_fault()
    try:
        broken = F9.case_raglan()
    finally:
        _remove_fault(originals)
    print(f"[ROTO ]  Raglan  {broken['metric']}={broken['value']} m  "
          f"→ {'PASS' if broken['passed'] else 'FALLO'}  (kernel con vóxeles +{VOXEL_OFFSET_M:.0f} m)")

    detected = healthy["passed"] and not broken["passed"]
    print("\n" + "=" * 74)
    print(f"DEGRADACIÓN DETECTADA POR LA SUITE: {'SÍ ✓ (sano PASS → roto FALLO)' if detected else 'NO ✗'}")
    print("Nota: depth_beta es inerte (Ws absorbe W_z); la palanca real es el operador forward.")
    print("=" * 74)
    return 0 if detected else 1


if __name__ == "__main__":
    sys.exit(main())
