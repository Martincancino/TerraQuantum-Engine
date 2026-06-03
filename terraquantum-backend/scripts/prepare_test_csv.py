"""
scripts/prepare_test_csv.py
============================
Genera un CSV sintético de prueba con señal gravimétrica y magnética.

Física:
  - Gravedad: anomalía analítica de esfera enterrada (fórmula de Bouguer exacta)
  - Magnetometría: TMI dipolar inducido (proyección campo regional)
  - Ruido: determinístico sin/cos (reproducible, sin random)

Output:
  terraquantum-backend/tests/data/synthetic_survey.csv

Uso:
  cd terraquantum-backend
  python scripts/prepare_test_csv.py
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# ---------------------------------------------------------------------------
# Parámetros del cuerpo sintético (cobre porfírico típico Chile)
# ---------------------------------------------------------------------------
DOMAIN_X = 1000.0    # m (extensión E-O)
DOMAIN_Z = 800.0     # m (extensión N-S)
N_SENSORS_X = 10
N_SENSORS_Z = 8

BODY_CX = 500.0       # m centro X del cuerpo
BODY_CZ = 400.0       # m centro Z del cuerpo
BODY_DEPTH = 250.0    # m profundidad al centro
BODY_RADIUS = 120.0   # m radio de la esfera equivalente

DENSITY_CONTRAST = 0.6   # t/m³  (contraste vs roca huésped 2.6 t/m³)
SUSCEPTIBILITY = 0.05    # SI    (magnetita diseminada en pórfido)

B0_NT = 23500.0          # nT intensidad campo geomagnético (norte Chile)
INC_DEG = -30.0          # ° inclinación (hemisferio sur)
DEC_DEG = 2.0            # ° declinación

NOISE_SCALE_G = 0.01     # 1 % del max señal gravedad
NOISE_SCALE_MAG = 0.005  # 0.5 % del max señal magnética

G_CONST = 6.674e-11      # m³ kg⁻¹ s⁻²

OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "tests", "data", "synthetic_survey.csv"
)


# ---------------------------------------------------------------------------
# Física analítica
# ---------------------------------------------------------------------------

def sphere_gravity_mgal(x_s, z_s, cx, cz, depth, radius, density_contrast_t_m3):
    """Anomalía gravimétrica vertical de esfera enterrada (mGal)."""
    rho_kg_m3 = density_contrast_t_m3 * 1000.0
    vol = (4.0 / 3.0) * np.pi * radius ** 3
    mass_kg = rho_kg_m3 * vol

    r2 = (x_s - cx) ** 2 + depth ** 2 + (z_s - cz) ** 2
    r = np.sqrt(r2)
    # componente vertical (hacia abajo = positivo): G * M * depth / r³
    gz_ms2 = G_CONST * mass_kg * depth / (r ** 3)
    return gz_ms2 * 1.0e5   # m/s² → mGal (1 mGal = 1e-5 m/s²)


def sphere_tmi_nt(x_s, z_s, cx, cz, depth, radius, susceptibility,
                  b0_nt, inc_deg, dec_deg):
    """Anomalía TMI de esfera (dipolo inducido), en nT.

    Física SI correcta:
      H0 = B0 / µ0  [A/m]
      m  = chi * H0 * vol  [A m²]
      B  = (µ0/4π) * dipole(m, r)  [T]  → * 1e9 → nT
    """
    MU0 = 4.0 * np.pi * 1.0e-7    # H/m
    inc = np.radians(inc_deg)
    dec = np.radians(dec_deg)

    # Vector unitario del campo regional (x=Norte, z=Este, y=abajo)
    fx = np.cos(inc) * np.cos(dec)
    fz = np.cos(inc) * np.sin(dec)
    fy = -np.sin(inc)

    # Momento magnético en A·m²
    B0_T = b0_nt * 1.0e-9                         # nT → T
    H0 = B0_T / MU0                               # A/m
    vol = (4.0 / 3.0) * np.pi * radius ** 3       # m³
    m_Am2 = susceptibility * H0 * vol             # A·m²

    # Vectores observación - fuente
    dx = x_s - cx
    dy = np.full_like(dx, depth)   # sensores en y=0, cuerpo en y=depth
    dz = z_s - cz
    r = np.sqrt(dx ** 2 + dy ** 2 + dz ** 2)

    # Campo dipolar en T (µ0/4π = 1e-7)
    k = MU0 / (4.0 * np.pi)       # = 1e-7 T·m/A
    fdotr = fx * dx + fy * dy + fz * dz
    Bx = k * m_Am2 * (3.0 * dx * fdotr / r ** 5 - fx / r ** 3)
    By = k * m_Am2 * (3.0 * dy * fdotr / r ** 5 - fy / r ** 3)
    Bz = k * m_Am2 * (3.0 * dz * fdotr / r ** 5 - fz / r ** 3)

    # Proyección sobre dirección del campo → TMI en nT
    return (Bx * fx + By * fy + Bz * fz) * 1.0e9


def deterministic_noise(signal, scale):
    """Ruido determinístico sin/cos (reproducible, sin random)."""
    idx = np.arange(len(signal), dtype=np.float64)
    amp = scale * float(np.abs(signal).mean())
    return signal + amp * (0.6 * np.sin(idx * 0.71) + 0.4 * np.cos(idx * 1.33))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    # Grilla regular de sensores en superficie (y_m = 0)
    xs = np.linspace(50.0, DOMAIN_X - 50.0, N_SENSORS_X)
    zs = np.linspace(50.0, DOMAIN_Z - 50.0, N_SENSORS_Z)
    XX, ZZ = np.meshgrid(xs, zs)
    x_flat = XX.ravel()
    z_flat = ZZ.ravel()
    y_flat = np.zeros(len(x_flat))
    n = len(x_flat)

    # Señal gravimétrica
    g = sphere_gravity_mgal(
        x_flat, z_flat,
        cx=BODY_CX, cz=BODY_CZ, depth=BODY_DEPTH,
        radius=BODY_RADIUS, density_contrast_t_m3=DENSITY_CONTRAST,
    )
    g = deterministic_noise(g, NOISE_SCALE_G)

    # Señal magnética (TMI relativa al campo regional)
    tmi_anomaly = sphere_tmi_nt(
        x_flat, z_flat,
        cx=BODY_CX, cz=BODY_CZ, depth=BODY_DEPTH,
        radius=BODY_RADIUS, susceptibility=SUSCEPTIBILITY,
        b0_nt=B0_NT, inc_deg=INC_DEG, dec_deg=DEC_DEG,
    )
    magnetic_nt = deterministic_noise(tmi_anomaly, NOISE_SCALE_MAG)

    df = pd.DataFrame({
        "station_id":   [f"SYN_{i:04d}" for i in range(n)],
        "x_m":          x_flat,
        "y_m":          y_flat,
        "z_m":          z_flat,
        "g":            g,
        "unit":         "mGal",
        "uncertainty":  0.02,
        "quality_flag": "OK",
        "gravity_type": "bouguer_mgal",
        "magnetic_nT":  magnetic_nt,
    })

    out = os.path.abspath(OUTPUT_PATH)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    df.to_csv(out, index=False)

    print(f"[OK] CSV listo: {n} sensores")
    print(f"   Grilla: {N_SENSORS_X}x{N_SENSORS_Z} | "
          f"x=[{x_flat.min():.0f}, {x_flat.max():.0f}] m | "
          f"z=[{z_flat.min():.0f}, {z_flat.max():.0f}] m")
    print(f"   Gravedad:  [{g.min():.5f}, {g.max():.5f}] mGal")
    print(f"   Magnetica: [{magnetic_nt.min():.2f}, {magnetic_nt.max():.2f}] nT")
    print(f"   Path: {out}")
    return out


if __name__ == "__main__":
    main()
