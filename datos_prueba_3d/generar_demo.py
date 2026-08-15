"""Genera 3 CSV de prueba (gravimetría, magnetometría, sondajes) para el flujo 3D.

Escenario COHERENTE: una esfera densa y susceptible enterrada. La gravimetría y
la magnetometría se calculan por FÍSICA ANALÍTICA (esfera = masa puntual / dipolo
inducido), y los sondajes intersectan el mismo cuerpo. Así la inversión recupera
un cuerpo compacto y las isosuperficies del visor 3D muestran algo claro.

Cuerpo:
  - Centro horizontal (Este, Norte) = (1000, 1000) m
  - Profundidad al centro = 300 m ; radio = 150 m
    → el cuerpo va de ~150 m a ~450 m de profundidad
  - Contraste de densidad Δρ = +1.0 g/cc (fondo 2.70 → cuerpo 3.70)
  - Susceptibilidad κ = 0.15 SI (fondo ~0.0005)

Salidas (mismo formato que las fixtures reales del repo):
  demo_gravimetria.csv   station_id,easting,northing,elevation,bouguer_mgal,gravity_type
  demo_magnetometria.csv station_id,easting,northing,elevation,tmi_nt
  demo_sondajes.csv      hole_id,easting,northing,depth_from,depth_to,density,susceptibility,lithology
"""
import csv
import os

import numpy as np

OUT = os.path.dirname(os.path.abspath(__file__))
rng = np.random.default_rng(42)

# ── Parámetros del cuerpo ────────────────────────────────────────────────────
X0, Y0 = 1000.0, 1000.0     # centro horizontal (m)
ELEV = 1000.0               # superficie plana (m s.n.m.)
DEPTH_C = 300.0             # profundidad al centro del cuerpo (m)
A = 150.0                   # radio (m)
D_RHO = 1.0                 # contraste de densidad (g/cc) → cuerpo 3.70, fondo 2.70
KAPPA = 0.15                # susceptibilidad SI del cuerpo
B0 = 24000.0                # campo geomagnético ambiente (nT), típico Chile
INC = np.radians(-50.0)     # inclinación (hemisferio sur)
DEC = np.radians(0.0)       # declinación

G = 6.674e-11               # constante de gravitación (SI)
RHO_KG = D_RHO * 1000.0     # g/cc → kg/m³
VOL = 4.0 / 3.0 * np.pi * A ** 3
DELTA_M = RHO_KG * VOL      # exceso de masa (kg)

# ── Grilla de estaciones (superficie) ────────────────────────────────────────
N, STEP = 21, 100.0         # 21×21 = 441 estaciones, 0..2000 m
axis = np.arange(N) * STEP
gx, gy = np.meshgrid(axis, axis, indexing="xy")
gx, gy = gx.ravel(), gy.ravel()

dx = gx - X0
dy = gy - Y0

# ── Gravimetría: g_z de una esfera (masa puntual), en mGal ───────────────────
R = np.sqrt(dx ** 2 + dy ** 2 + DEPTH_C ** 2)
gz = 1e5 * G * DELTA_M * DEPTH_C / R ** 3          # mGal (positivo = exceso de masa)
gz += rng.normal(0.0, 0.01, gz.shape)              # ruido realista ±0.01 mGal

# ── Magnetometría: anomalía TMI de una esfera magnetizada por inducción ──────
# ΔT = (a³/3)·κ·B0·(3cos²θ − 1)/r³ ,  θ = ángulo entre el campo y el vector fuente→estación.
b0 = np.array([np.cos(INC) * np.sin(DEC), np.cos(INC) * np.cos(DEC), np.sin(INC)])  # (E,N,Abajo)
rvec = np.stack([dx, dy, -DEPTH_C * np.ones_like(dx)], axis=1)  # estación sobre la fuente → abajo negativo
Rr = np.linalg.norm(rvec, axis=1)
cos_theta = (rvec / Rr[:, None]) @ b0
dT = (A ** 3 / 3.0) * KAPPA * B0 * (3.0 * cos_theta ** 2 - 1.0) / Rr ** 3  # nT
dT += rng.normal(0.0, 1.0, dT.shape)               # ruido realista ±1 nT

# ── Escritura de gravimetría y magnetometría ─────────────────────────────────
with open(os.path.join(OUT, "demo_gravimetria.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["station_id", "easting", "northing", "elevation", "bouguer_mgal", "gravity_type"])
    for i in range(len(gx)):
        w.writerow([i + 1, f"{gx[i]:.1f}", f"{gy[i]:.1f}", f"{ELEV:.1f}",
                    f"{gz[i]:.4f}", "bouguer_anomaly"])

with open(os.path.join(OUT, "demo_magnetometria.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["station_id", "easting", "northing", "elevation", "tmi_nt"])
    for i in range(len(gx)):
        w.writerow([i + 1, f"{gx[i]:.1f}", f"{gy[i]:.1f}", f"{ELEV:.1f}", f"{dT[i]:.2f}"])

# ── Sondajes: verticales; intersección analítica con la esfera ───────────────
# Cuerpo (magnetita/sulfuro): densidad 3.70, κ 0.15. Roca de caja (andesita): 2.70, 0.0005.
HOLE_DEPTH = 600.0
collars = [
    ("DDH-01", 1000.0, 1000.0),  # centro → intersección larga
    ("DDH-02", 900.0, 1000.0),   # offset 100 m
    ("DDH-03", 1100.0, 1100.0),  # offset ~141 m
    ("DDH-04", 1500.0, 1500.0),  # lejos → sin cuerpo (control negativo)
]

rows = []
for hid, cx, cy in collars:
    s = np.hypot(cx - X0, cy - Y0)          # offset horizontal al eje del cuerpo
    if s < A:
        half = np.sqrt(A ** 2 - s ** 2)     # media cuerda vertical
        top = max(0.0, DEPTH_C - half)
        bot = min(HOLE_DEPTH, DEPTH_C + half)
        rows.append((hid, cx, cy, 0.0, round(top, 1), 2.70, 0.0005, "andesita"))
        rows.append((hid, cx, cy, round(top, 1), round(bot, 1), 3.70, 0.15, "magnetita"))
        rows.append((hid, cx, cy, round(bot, 1), HOLE_DEPTH, 2.70, 0.0005, "andesita"))
    else:
        rows.append((hid, cx, cy, 0.0, HOLE_DEPTH, 2.70, 0.0005, "andesita"))

with open(os.path.join(OUT, "demo_sondajes.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["hole_id", "easting", "northing", "depth_from", "depth_to",
                "density", "susceptibility", "lithology"])
    for r in rows:
        w.writerow(list(r))

print(f"Gravimetria: {len(gx)} estaciones | pico g_z ~ {gz.max():.3f} mGal")
print(f"Magnetometria: {len(gx)} estaciones | rango TMI [{dT.min():.1f}, {dT.max():.1f}] nT")
print(f"Sondajes: {len(collars)} pozos, {len(rows)} intervalos")
print(f"Archivos escritos en: {OUT}")
