"""
Genera un CSV de prueba REALISTA para el flujo completo de TerraQuantum.

Modela la anomalía de Bouguer de una ESFERA densa enterrada (física exacta de
masa puntual: g = G·Δm·z/r³), sobre una grilla de estaciones de superficie en
coordenadas UTM realistas. NO inventa números: la anomalía corresponde a un
cuerpo real recuperable por el motor.

Cuerpo objetivo (tipo sulfuro/magnetita, ALTA densidad → anomalía POSITIVA):
  - centro en el medio del survey, profundidad al centro = 250 m
  - radio 120 m, contraste de densidad +0.60 g/cc
  - pico esperado ~0.7 mGal (anomalía clara, recuperable)

El CSV sale "limpio y auto-mapeable": encabezados en inglés que el detector
fuzzy reconoce, decimal con PUNTO, y una columna gravity_type=bouguer_anomaly
para que el enriquecimiento NO re-reduzca (evita el doble-Bouguer).
"""
import numpy as np

# ── Constantes ───────────────────────────────────────────────────────────────
G = 6.67430e-11  # m³ kg⁻¹ s⁻²

# ── Geometría del survey (UTM 19S, norte de Chile, realista) ─────────────────
E0, N0 = 360_000.0, 7_350_000.0   # esquina SO del survey (m)
SPACING = 80.0                    # m entre estaciones
NX, NY = 20, 20                   # 400 estaciones, 1520 × 1520 m
ELEV = 1500.0                     # cota media (m s.n.m.), plana para simplicidad

# ── Cuerpo enterrado (esfera densa) ──────────────────────────────────────────
R = 120.0                         # radio (m)
DRHO = 600.0                      # contraste de densidad (kg/m³) = +0.60 g/cc
DEPTH = 250.0                     # profundidad al CENTRO (m bajo superficie)
# centro del cuerpo = centro del survey
CX = E0 + (NX - 1) * SPACING / 2.0
CY = N0 + (NY - 1) * SPACING / 2.0
mass = (4.0 / 3.0) * np.pi * R**3 * DRHO   # exceso de masa (kg)

# ── Estaciones ───────────────────────────────────────────────────────────────
rng = np.random.default_rng(42)
rows = []
sid = 1
for j in range(NY):
    for i in range(NX):
        e = E0 + i * SPACING
        n = N0 + j * SPACING
        # distancia 3D estación(superficie) → centro de la esfera (a profundidad DEPTH)
        dx = e - CX
        dy = n - CY
        dz = DEPTH                      # el cuerpo está DEPTH metros bajo la superficie
        r = np.sqrt(dx*dx + dy*dy + dz*dz)
        # componente vertical de la gravedad de una esfera = masa puntual en su centro
        g_ms2 = G * mass * dz / r**3    # m/s²
        g_mgal = g_ms2 * 1e5            # → mGal
        # ruido instrumental realista (CG-6 ~ 0.01 mGal)
        g_mgal += rng.normal(0.0, 0.01)
        rows.append((sid, round(e, 2), round(n, 2), round(ELEV, 1),
                     round(g_mgal, 4)))
        sid += 1

# ── Escribir CSV (encabezados ingleses auto-mapeables, decimal punto) ────────
out = "prueba_gravimetria_LISTO.csv"
with open(out, "w", encoding="utf-8") as f:
    f.write("station_id,easting,northing,elevation,bouguer_mgal,gravity_type\n")
    for sid, e, n, el, g in rows:
        f.write(f"{sid},{e},{n},{el},{g},bouguer_anomaly\n")

peak = max(r[4] for r in rows)
print(f"Escrito: {out}")
print(f"  {len(rows)} estaciones | grilla {NX}x{NY} @ {SPACING}m")
print(f"  cuerpo: esfera R={R}m, Δρ=+{DRHO/1000:.2f} g/cc, centro a {DEPTH}m")
print(f"  centro UTM=({CX:.0f}, {CY:.0f}) | pico Bouguer ≈ {peak:.3f} mGal")
print(f"  rango anomalía: [{min(r[4] for r in rows):.3f}, {peak:.3f}] mGal")
