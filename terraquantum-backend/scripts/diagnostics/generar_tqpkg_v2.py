"""
TQPKG v2 — cuerpo SOMERO y FUERTE que la gravimetría SÍ resuelve, para que el
modelo 3D se vea claramente. Coords LOCALes (0-based, como las que produce
Preparación). Genera paquete directo cargable en Carga 3D.

Cuerpo: esfera densa, centro a 100 m, radio 90 m, Δρ = +1.5 g/cc → pico ~3 mGal.
A esta profundidad la gravimetría recupera contraste alto (densidad ~3.5-4) que
cruza el umbral de visualización (~2.75) → el cuerpo se dibuja en 3D.
"""
import os
import sys
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from schemas.geophysics_schema import GravityObservation
from services.csv_package_service import build_package_text

G = 6.67430e-11
SPACING = 80.0
NX, NY = 20, 20          # 400 estaciones, 1520 x 1520 m (coords locales 0..1520)
ELEV = 1500.0
R, DRHO, DEPTH = 90.0, 1500.0, 100.0     # somero + fuerte
CX = (NX - 1) * SPACING / 2.0            # centro local
CZ = (NY - 1) * SPACING / 2.0
mass = (4.0 / 3.0) * np.pi * R**3 * DRHO

rng = np.random.default_rng(7)
obs, elevs, sigmas = [], [], []
peak = 0.0
for j in range(NY):
    for i in range(NX):
        x = i * SPACING        # local Este
        z = j * SPACING        # local Norte
        r = np.sqrt((x - CX) ** 2 + (z - CZ) ** 2 + DEPTH ** 2)
        g_ms2 = G * mass * DEPTH / r ** 3
        g_ms2 += rng.normal(0.0, 0.01) * 1e-5     # ruido 0.01 mGal
        peak = max(peak, g_ms2 * 1e5)
        obs.append(GravityObservation(x_m=float(x), y_m=0.0, z_m=float(z), g=float(g_ms2)))
        elevs.append(ELEV)
        sigmas.append(0.01)

res = SimpleNamespace(
    observations=obs, station_elevations=elevs, station_uncertainties=sigmas,
    magnetic_values=None, raw_latlon_elev=None,
)

# density_min=2.6 → contraste >= 0 (cuerpo DENSO, recuperación limpia y positiva)
text = build_package_text(
    primary_result=res, data_type="gravity",
    config={"region": "norte_chile", "density_min": 2.6, "density_max": 5.5},
    boreholes=[], plan={"route": "gravity_only", "confidence": 0.8},
)

out = "prueba_gravimetria_v2.tqpkg"
with open(out, "w", encoding="utf-8") as f:
    f.write(text)

print("Escrito:", out)
print(f"  cuerpo: R={R}m, Drho=+{DRHO/1000:.1f} g/cc, centro a {DEPTH}m (techo ~{DEPTH-R:.0f}m)")
print(f"  pico Bouguer ~ {peak:.2f} mGal | 400 estaciones | density_min=2.6")
