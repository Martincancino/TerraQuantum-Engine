"""
Genera un PAQUETE TQPKG válido (cargable directo en el paso "Carga 3D") con el
MISMO cuerpo esférico denso del CSV de prueba. Usa build_package_text del backend
para garantizar el formato exacto (encabezado #TQPKG + cuerpo importable).
"""
import os
import sys
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from schemas.geophysics_schema import GravityObservation
from services.csv_package_service import build_package_text

# ── Constantes / geometría (idénticas al CSV de prueba) ──────────────────────
G = 6.67430e-11
E0, N0 = 360_000.0, 7_350_000.0
SPACING = 80.0
NX, NY = 20, 20
ELEV = 1500.0
R, DRHO, DEPTH = 120.0, 600.0, 250.0
CX = E0 + (NX - 1) * SPACING / 2.0
CY = N0 + (NY - 1) * SPACING / 2.0
mass = (4.0 / 3.0) * np.pi * R**3 * DRHO

rng = np.random.default_rng(42)
obs, elevs, sigmas = [], [], []
for j in range(NY):
    for i in range(NX):
        e = E0 + i * SPACING
        n = N0 + j * SPACING
        r = np.sqrt((e - CX) ** 2 + (n - CY) ** 2 + DEPTH ** 2)
        g_ms2 = G * mass * DEPTH / r ** 3          # m/s² (la esfera = masa puntual)
        g_ms2 += rng.normal(0.0, 0.01) * 1e-5      # ruido 0.01 mGal en m/s²
        # x_m = Este, z_m = Norte, y_m = 0 (estación en superficie), g en m/s²
        obs.append(GravityObservation(x_m=float(e), y_m=0.0, z_m=float(n), g=float(g_ms2)))
        elevs.append(ELEV)
        sigmas.append(0.01)

res = SimpleNamespace(
    observations=obs,
    station_elevations=elevs,
    station_uncertainties=sigmas,
    magnetic_values=None,
    raw_latlon_elev=None,
)

text = build_package_text(
    primary_result=res,
    data_type="gravity",
    config={"region": "norte_chile"},
    boreholes=[],
    plan={"route": "gravity_only", "confidence": 0.8},
)

out = "prueba_gravimetria.tqpkg"
with open(out, "w", encoding="utf-8") as f:
    f.write(text)

lines = text.splitlines()
print("Escrito:", out)
print("  primeras 4 lineas de encabezado/cuerpo:")
for ln in lines[:6]:
    print("   ", ln[:90])
print(f"  total filas estacion: {len(obs)}")
gvals = [o.g * 1e5 for o in obs]
print(f"  rango Bouguer: [{min(gvals):.3f}, {max(gvals):.3f}] mGal (pico = cuerpo)")
