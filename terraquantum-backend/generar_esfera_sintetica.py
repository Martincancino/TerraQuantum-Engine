"""
SYNTHETIC SPHERE BENCHMARK
===========================
Genera una grilla de sensores gravimétricos y calcula la respuesta analítica
de una esfera enterrada con contraste de densidad conocido.

Sin importaciones de TerraQuantum — solo numpy y pandas.

Uso:
    python generar_esfera_sintetica.py

Salida:
    esfera_sintetica_benchmark.csv
    Columnas (Strict Mode): station_id, x_m, z_m, elevation_m, g, unit, gravity_type
"""

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# 1. PARÁMETROS DE LA GRILLA DE SENSORES
# ─────────────────────────────────────────────────────────────────────────────
X_MIN, X_MAX = 0.0, 2000.0   # Easting  [m]
Y_MIN, Y_MAX = 0.0, 2000.0   # Northing [m]  (Norte, equivalente a latitud en CSV)
SPACING      = 50.0           # Espaciado entre sensores [m]
Z_SENSOR     = 0.0            # Elevación de todos los sensores [m]  (topografía plana)

# Grilla 41 × 41 = 1 681 sensores
x_vals = np.arange(X_MIN, X_MAX + SPACING, SPACING)   # 41 puntos
y_vals = np.arange(Y_MIN, Y_MAX + SPACING, SPACING)   # 41 puntos
XX, YY = np.meshgrid(x_vals, y_vals)                  # (41, 41) cada uno

sensor_x = XX.ravel()   # (1681,)
sensor_y = YY.ravel()   # (1681,)
sensor_z = np.full_like(sensor_x, Z_SENSOR)

print(f"[INFO] Grilla de sensores: {len(sensor_x)} puntos "
      f"({len(x_vals)} en X × {len(y_vals)} en Y)")

# ─────────────────────────────────────────────────────────────────────────────
# 2. PARÁMETROS DE LA ESFERA SINTÉTICA
# ─────────────────────────────────────────────────────────────────────────────
X0    = 1000.0   # Centro Easting  [m]
Y0    = 1000.0   # Centro Northing [m]
Z0    = 400.0    # Profundidad del centro por debajo de la superficie [m]
R     = 150.0    # Radio de la esfera [m]
RHO   = 1.0      # Contraste de densidad [g/cm³ = t/m³]

# Convertir densidad a SI: 1 g/cm³ = 1000 kg/m³
RHO_SI = RHO * 1_000.0   # [kg/m³]

print(f"[INFO] Esfera -> centro=({X0}, {Y0}, -{Z0}) m | R={R} m | "
      f"Drho={RHO} g/cm3 ({RHO_SI} kg/m3)")

# ─────────────────────────────────────────────────────────────────────────────
# 3. CÁLCULO GRAVIMÉTRICO ANALÍTICO
# ─────────────────────────────────────────────────────────────────────────────
G = 6.67430e-11   # Constante gravitacional [m³ kg⁻¹ s⁻²]

# Volumen y masa de la esfera
V = (4.0 / 3.0) * np.pi * R**3          # [m³]
M = V * RHO_SI                           # [kg]

print(f"[INFO] Volumen={V:.4e} m³ | Masa={M:.4e} kg")

# Distancia 3D de cada sensor al centro de la esfera
# (Z0 es la distancia vertical; los sensores están en Z=0 y la esfera en -Z0)
dx = sensor_x - X0
dy = sensor_y - Y0
r  = np.sqrt(dx**2 + dy**2 + Z0**2)   # [m]

# Componente vertical de la gravedad (punto hacia abajo = positivo en convención geofísica)
# g_z = G * M * (Z0 / r³)   [m/s²]
g_z_si = G * M * (Z0 / r**3)          # [m/s²]

# Conversión a mGal: 1 m/s² = 10^5 mGal
MGAL_CONV = 1.0e5
g_z_mgal  = g_z_si * MGAL_CONV        # [mGal]

# ─────────────────────────────────────────────────────────────────────────────
# 4. RUIDO BLANCO GAUSSIANO (evita ceros perfectos para el solucionador LSQR)
# ─────────────────────────────────────────────────────────────────────────────
NOISE_STD = 0.01   # [mGal]
rng        = np.random.default_rng(seed=42)   # semilla fija → reproducible
noise      = rng.normal(0.0, NOISE_STD, size=g_z_mgal.shape)
g_z_noisy  = g_z_mgal + noise

print(f"[INFO] Senal pico: {g_z_mgal.max():.6f} mGal | "
      f"Ruido sigma={NOISE_STD} mGal (SNR~{g_z_mgal.max()/NOISE_STD:.1f})")

# ─────────────────────────────────────────────────────────────────────────────
# 5. EXPORTAR CSV
# ─────────────────────────────────────────────────────────────────────────────
OUTPUT_FILE = "esfera_sintetica_benchmark.csv"

df = pd.DataFrame({
    "station_id"  : np.arange(1, len(sensor_x) + 1, dtype=int),  # correlativo 1..1681
    "x_m"         : sensor_x,        # Easting  [m]
    "z_m"         : sensor_y,        # Northing [m]  (Norte — convencion TerraQuantum)
    "elevation_m" : sensor_z,        # Topografia plana [m]
    "g"           : g_z_noisy,       # Anomalia gravimetrica [mGal]
    "unit"        : "mGal",          # Unidad fija
    "gravity_type": "synthetic_demo",  # Valor exacto en ALLOWED_GRAVITY_TYPES del backend
})

df.to_csv(OUTPUT_FILE, index=False, float_format="%.8f")

print(f"\n[OK] Archivo guardado -> {OUTPUT_FILE}")
print(f"     Filas  : {len(df)}")
print(f"     Columnas: {list(df.columns)}")
print(f"\n--- ESTADISTICAS GRAVITY (mGal) ---")
print(df["g"].describe().to_string())
print(f"\n[BENCHMARK] Maximo teorico en ({X0}, {Y0}) = "
      f"{G * M * Z0 / Z0**3 * MGAL_CONV:.6f} mGal "
      f"(solo si sensor coincide exactamente)")
