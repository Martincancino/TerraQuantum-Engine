"""
Genera 3 CSV artificiales para probar la ingesta multi-física, TODOS con el MISMO
cuerpo (para poder combinarlos después: joint grav+mag, anclaje con sondajes).

Cuerpo: esfera GRANDE y FUERTE (para muchos vóxeles / figura visible):
  centro del survey, profundidad 350 m, radio 300 m,
  Δρ = +1.2 g/cc  y  κ = 0.08 SI (magnetita-like).
Survey 30×30 = 900 estaciones @ 80 m = 2320 × 2320 m. Coords LOCALes (0-based).
"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from exploration.magnetometry import field_unit_vector

G = 6.67430e-11
SP = 80.0; NX = NY = 30
ELEV = 1000.0
R, DRHO, KAPPA, DEPTH = 300.0, 1200.0, 0.08, 350.0
# campo magnético (defaults del motor → la inversión usará el mismo)
INC, DEC, B0 = -30.0, 2.0, 23500.0
CX = CZ = (NX - 1) * SP / 2.0          # centro del survey (local)
Vol = (4/3) * np.pi * R**3
mass = Vol * DRHO
C = B0 * Vol / (4 * np.pi)             # prefactor dipolo (igual que el motor)
fhat = field_unit_vector(INC, DEC)     # (x=N, y=abajo, z=E)
rng = np.random.default_rng(11)

# ── estaciones ────────────────────────────────────────────────────────────────
grav_rows, mag_rows = [], []
gpk = mpk = 0.0
sid = 1
for j in range(NY):
    for i in range(NX):
        e = i * SP; n = j * SP                       # easting/northing local
        dN = CZ - n; dE = CX - e                     # (ojo: x=N, z=E en el motor)
        # vector cuerpo - estación en coords motor (x=N, y=prof, z=E)
        rvec = np.array([dN, DEPTH, dE])
        r = np.sqrt(rvec @ rvec)
        # gravedad (esfera = masa puntual): componente vertical
        g_mgal = (G * mass * DEPTH / r**3) * 1e5 + rng.normal(0, 0.02)
        gpk = max(gpk, g_mgal)
        grav_rows.append((sid, round(e, 1), round(n, 1), ELEV, round(g_mgal, 4)))
        # magnético TMI (dipolo, misma fórmula del motor): ΔT = κ·C·(3(f̂·r)²−r²)/r⁵
        fdotr = fhat @ rvec
        tmi = KAPPA * C * (3 * fdotr**2 - r**2) / r**5 + rng.normal(0, 2.0)
        mpk = max(mpk, abs(tmi))
        mag_rows.append((sid, round(e, 1), round(n, 1), ELEV, round(tmi, 2)))
        sid += 1

with open("multi_gravimetria.csv", "w", encoding="utf-8") as f:
    f.write("station_id,easting,northing,elevation,bouguer_mgal,gravity_type\n")
    for r_ in grav_rows:
        f.write(f"{r_[0]},{r_[1]},{r_[2]},{r_[3]},{r_[4]},bouguer_anomaly\n")

with open("multi_magnetometria.csv", "w", encoding="utf-8") as f:
    f.write("station_id,easting,northing,elevation,tmi_nt\n")
    for r_ in mag_rows:
        f.write(f"{r_[0]},{r_[1]},{r_[2]},{r_[3]},{r_[4]}\n")

# ── sondajes ──────────────────────────────────────────────────────────────────
# cuerpo entre prof 50 y 650 m (centro 350 ± radio 300). Dentro = magnetita.
d_body = 2.6 + DRHO / 1000.0    # 3.8 t/m3
holes = []
# 2 pozos que ATRAVIESAN el cuerpo (cerca del centro)
for hid, (hx, hz) in [("DDH-01", (CX, CZ)), ("DDH-02", (CX - 120, CZ + 120))]:
    holes.append((hid, hx, hz, 0, 50,  2.70, 0.001, "andesita"))
    holes.append((hid, hx, hz, 50, 650, d_body, KAPPA, "magnetita"))
    holes.append((hid, hx, hz, 650, 800, 2.70, 0.001, "andesita"))
# 2 pozos FUERA del cuerpo (fondo estéril)
for hid, (hx, hz) in [("DDH-03", (300, 300)), ("DDH-04", (2000, 2000))]:
    holes.append((hid, hx, hz, 0, 800, 2.67, 0.0002, "granito"))

with open("multi_sondajes.csv", "w", encoding="utf-8") as f:
    f.write("hole_id,easting,northing,depth_from,depth_to,density,susceptibility,lithology\n")
    for h in holes:
        f.write(f"{h[0]},{h[1]:.1f},{h[2]:.1f},{h[3]},{h[4]},{h[5]},{h[6]},{h[7]}\n")

print("Escritos: multi_gravimetria.csv | multi_magnetometria.csv | multi_sondajes.csv")
print(f"  survey {NX}x{NY}={NX*NY} estaciones @ {SP}m = {(NX-1)*SP:.0f}m")
print(f"  cuerpo: R={R}m centro {DEPTH}m  Δρ=+{DRHO/1000} g/cc  κ={KAPPA} SI")
print(f"  pico gravimétrico ≈ {gpk:.2f} mGal | pico |TMI| ≈ {mpk:.0f} nT")
print(f"  sondajes: {len(holes)} tramos, 4 pozos (2 en cuerpo=magnetita, 2 estériles)")
