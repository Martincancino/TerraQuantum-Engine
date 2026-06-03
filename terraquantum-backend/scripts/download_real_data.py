"""
scripts/download_real_data.py
==============================
Descarga datos geofisicos reales de minas activas para validar TerraQuantum.

DATASETS REALES (no sinteticos):

  1. Osborne Mine — Queensland, Australia
     Tipo: Mina Cu-Au IOCG activa (cobre-oro tipo IOCG)
     Dato: Survey aereo magnetico (Geoscience Australia 1990)
     ~990,000 mediciones, paso de linea 200 m, altura vuelo 80 m
     Ground truth: la mina existe fisicamente. El anomalo magnetico
                   debe ubicarse en lat=-22.0966, lon=140.5716.
     Fuente: CC-BY — Geoscience Australia / Fatiando a Terra
     DOI: https://doi.org/10.5281/zenodo.5882209

  2. Bushveld Igneous Complex — Sudafrica
     Tipo: Mayor deposito de Pt/Pd/Cr del mundo (Complejo igneo)
     Dato: Estaciones gravimetricas terrestres (NOAA NCEI)
     Ground truth: complejo de ~500 km E-O con anomalia Bouguer
                   positiva fuerte (rocas densas: gabro, anortosita).
     Fuente: NOAA NCEI / Fatiando a Terra (Public Domain)
     DOI: https://doi.org/10.5281/zenodo.6511942

OUTPUT:
  tests/data/real_osborne_magnetic.csv   — formato TerraQuantum
  tests/data/real_bushveld_gravity.csv   — formato TerraQuantum
  tests/data/real_osborne_api_payload.json — payload JSON listo para /api/geophysics/invert

USO:
  cd terraquantum-backend
  python scripts/download_real_data.py

DEPENDENCIAS: solo stdlib + pandas + numpy (ya en requirements.txt)
"""

import io
import json
import lzma
import math
import os
import sys
import urllib.request

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Rutas de salida
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(BACKEND_DIR, "tests", "data")

OUT_OSBORNE_CSV = os.path.join(OUT_DIR, "real_osborne_magnetic.csv")
OUT_BUSHVELD_CSV = os.path.join(OUT_DIR, "real_bushveld_gravity.csv")
OUT_OSBORNE_PAYLOAD = os.path.join(OUT_DIR, "real_osborne_api_payload.json")
OUT_BUSHVELD_PAYLOAD = os.path.join(OUT_DIR, "real_bushveld_api_payload.json")

# ---------------------------------------------------------------------------
# URLs directas de descarga (Zenodo CC-BY / Public Domain)
# ---------------------------------------------------------------------------
OSBORNE_URL = (
    "https://zenodo.org/record/5882209/files/osborne-magnetic.csv.xz?download=1"
)
BUSHVELD_URL = (
    "https://zenodo.org/record/6511942/files/bushveld-gravity.csv.xz?download=1"
)

# ---------------------------------------------------------------------------
# Parametros de la mina Osborne (ground truth conocido)
# ---------------------------------------------------------------------------
OSBORNE_MINE_LAT = -22.0966   # grados S
OSBORNE_MINE_LON = 140.5716   # grados E
OSBORNE_RADIUS_KM = 18.0      # radio de corte alrededor de la mina
OSBORNE_TARGET_N = 300        # sensores objetivo tras diezmar

# Parametros del survey Osborne (Geoscience Australia 1990)
OSBORNE_INC_DEG = -55.0       # inclinacion campo geomagnetico Queensland
OSBORNE_DEC_DEG = 4.0         # declinacion
OSBORNE_B0_NT = 56_000.0      # intensidad campo (Australia ~56,000 nT)

# ---------------------------------------------------------------------------
# Parametros del Bushveld (subset representativo)
# ---------------------------------------------------------------------------
BUSHVELD_CENTER_LAT = -25.0
BUSHVELD_CENTER_LON = 27.5
BUSHVELD_RADIUS_KM = 180.0    # radio de corte (complejo mide ~500 km E-O)
BUSHVELD_TARGET_N = 400       # estaciones objetivo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print(msg: str):
    """Print compatible con Windows cp1252 (sin emojis)."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode())


def download_xz_csv(url: str, label: str) -> pd.DataFrame:
    """Descarga un CSV.xz desde URL y lo retorna como DataFrame."""
    _print(f"\n[DESCARGA] {label}")
    _print(f"  URL: {url}")
    _print("  Descargando...")

    req = urllib.request.Request(url, headers={"User-Agent": "TerraQuantum/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        compressed = resp.read()

    _print(f"  Comprimido: {len(compressed)/1024:.1f} KB")
    raw = lzma.decompress(compressed)
    _print(f"  Descomprimido: {len(raw)/1024:.0f} KB")

    df = pd.read_csv(io.BytesIO(raw))
    _print(f"  Filas: {len(df):,}  |  Columnas: {list(df.columns)}")
    return df


def latlon_to_local_xy(lat: np.ndarray, lon: np.ndarray,
                        lat0: float, lon0: float):
    """
    Convierte lat/lon a coordenadas locales en metros.
    Sistema: x_m = Este (positivo E), z_m = Norte (positivo N)
    Origen (0,0) = esquina SW del subset.
    Aproximacion plana (valida para areas < 300 km).
    """
    M_PER_DEG_LAT = 111_111.0
    M_PER_DEG_LON = 111_111.0 * math.cos(math.radians(lat0))
    x_m = (lon - lon0) * M_PER_DEG_LON
    z_m = (lat - lat0) * M_PER_DEG_LAT   # positivo hacia el Norte
    return x_m, z_m


def crop_and_decimate(df: pd.DataFrame, center_lat: float, center_lon: float,
                       radius_km: float, target_n: int,
                       lat_col: str = "latitude", lon_col: str = "longitude"):
    """Recorta un circulo alrededor del centro y diezma a target_n filas."""
    M_PER_DEG_LAT = 111_111.0
    lat0 = center_lat
    dlat_m = (df[lat_col].values - lat0) * M_PER_DEG_LAT
    dlon_m = (df[lon_col].values - center_lon) * 111_111.0 * math.cos(math.radians(lat0))
    dist_m = np.sqrt(dlat_m**2 + dlon_m**2)

    mask = dist_m <= radius_km * 1000.0
    sub = df[mask].copy()
    _print(f"  Filas en radio {radius_km} km: {len(sub):,}")

    if len(sub) > target_n:
        step = max(1, len(sub) // target_n)
        sub = sub.iloc[::step].copy()
        _print(f"  Diezmado (paso={step}): {len(sub):,} sensores")

    return sub.reset_index(drop=True)


# ---------------------------------------------------------------------------
# DATASET 1: Osborne Mine — magnetometria aerea
# ---------------------------------------------------------------------------

def process_osborne(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Procesa el survey de Osborne Mine y genera:
      - CSV en formato TerraQuantum
      - payload JSON para /api/geophysics/invert
    """
    _print("\n[OSBORNE] Procesando survey magnetico...")
    _print(f"  Columnas originales: {list(df.columns)}")

    # Recortar alrededor de la mina
    sub = crop_and_decimate(
        df, OSBORNE_MINE_LAT, OSBORNE_MINE_LON,
        OSBORNE_RADIUS_KM, OSBORNE_TARGET_N,
    )

    # Coordenadas locales (SW corner como origen)
    lat_sw = sub["latitude"].min()
    lon_sw = sub["longitude"].min()
    x_m, z_m = latlon_to_local_xy(
        sub["latitude"].values, sub["longitude"].values, lat_sw, lon_sw
    )

    # Ubicacion conocida de la mina en coordenadas locales
    mine_x, mine_z = latlon_to_local_xy(
        np.array([OSBORNE_MINE_LAT]), np.array([OSBORNE_MINE_LON]), lat_sw, lon_sw
    )
    _print(f"  Mina Osborne en coords locales: x={mine_x[0]:.0f} m, z={mine_z[0]:.0f} m")
    _print(f"  Dominio: {x_m.max():.0f} m (E-O) x {z_m.max():.0f} m (N-S)")

    mag_nt = sub["total_field_anomaly_nt"].values.astype(float)
    height_m = sub["height_orthometric_m"].values.astype(float)

    _print(f"  TMI anomalia: [{mag_nt.min():.1f}, {mag_nt.max():.1f}] nT")
    _print(f"  Altura sensor: [{height_m.min():.0f}, {height_m.max():.0f}] m")

    # CSV para TerraQuantum
    out_df = pd.DataFrame({
        "station_id": [f"OSB_{i:04d}" for i in range(len(sub))],
        "x_m":        np.round(x_m, 2),
        "y_m":        0.0,   # sensores en superficie (profundidad = 0)
        "z_m":        np.round(z_m, 2),
        "g":          0.0,   # sin gravedad en este survey
        "unit":       "mGal",
        "uncertainty": 50.0,  # 50 nT incertidumbre tipica survey aereo
        "quality_flag": "OK",
        "gravity_type": "magnetic_only",
        "magnetic_nT":  np.round(mag_nt, 2),
        "sensor_elevation_masl": np.round(height_m, 1),
    })

    # Payload JSON para /api/geophysics/invert
    domain_x = float(x_m.max())
    domain_z = float(z_m.max())
    block_size = max(200, int(min(domain_x, domain_z) / 20))
    nx = max(8, min(30, int(domain_x / block_size)))
    nz = max(8, min(30, int(domain_z / block_size)))
    ny = max(8, min(20, int(OSBORNE_RADIUS_KM * 500 / block_size)))

    observations = [
        {"x_m": float(r.x_m), "y_m": 0.0, "z_m": float(r.z_m), "g": 0.0}
        for r in out_df.itertuples()
    ]

    payload = {
        "project_id": "real_osborne_v1",
        "run_id": "magnetic_run_01",
        "depth": int(OSBORNE_RADIUS_KM * 600),
        "nir": 20, "fe": 60,
        "region": "Mt Isa Inlier, Queensland, Australia",
        "lat": str(OSBORNE_MINE_LAT), "lon": str(OSBORNE_MINE_LON),
        "nx": nx, "ny": ny, "nz": nz,
        "block_size": block_size,
        "cutoff_radius": float(OSBORNE_RADIUS_KM * 900),
        "lambda_mag": 0.0,
        "alpha_spatial": 1.0,
        "auto_lambda": True,
        "observations": observations,
        "magnetic_nt": [float(v) for v in mag_nt],
        "sensor_elevations_masl": [float(v) for v in height_m],
        "inclination_deg": OSBORNE_INC_DEG,
        "declination_deg": OSBORNE_DEC_DEG,
        "field_intensity_nt": OSBORNE_B0_NT,
        "susc_min": 0.0,
        "susc_max": 1.0,
        "_ground_truth": {
            "note": "Mine location in LOCAL coordinates",
            "mine_x_m": float(mine_x[0]),
            "mine_z_m": float(mine_z[0]),
            "mine_lat": OSBORNE_MINE_LAT,
            "mine_lon": OSBORNE_MINE_LON,
            "deposit_type": "IOCG Cu-Au (Iron Oxide Copper Gold)",
            "validation_criterion": (
                "best_target debe estar dentro de "
                f"{block_size*2} m de (x={mine_x[0]:.0f}, z={mine_z[0]:.0f})"
            ),
        },
    }

    return out_df, payload


# ---------------------------------------------------------------------------
# DATASET 2: Bushveld Complex — gravimetria terrestre
# ---------------------------------------------------------------------------

def process_bushveld(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Procesa las estaciones de gravedad del Complejo Bushveld y genera:
      - CSV en formato TerraQuantum
      - payload JSON para /api/geophysics/invert
    """
    _print("\n[BUSHVELD] Procesando estaciones gravimetricas...")
    _print(f"  Columnas originales: {list(df.columns)}")

    sub = crop_and_decimate(
        df, BUSHVELD_CENTER_LAT, BUSHVELD_CENTER_LON,
        BUSHVELD_RADIUS_KM, BUSHVELD_TARGET_N,
    )

    lat_sw = sub["latitude"].min()
    lon_sw = sub["longitude"].min()
    x_m, z_m = latlon_to_local_xy(
        sub["latitude"].values, sub["longitude"].values, lat_sw, lon_sw
    )

    # Usa gravedad Bouguer (ya corregida por topografia)
    g_col = "gravity_bouguer_mgal"
    if g_col not in sub.columns:
        # Fallback si el nombre cambia
        candidates = [c for c in sub.columns if "bouguer" in c.lower() or "gravity" in c.lower()]
        g_col = candidates[0] if candidates else "gravity_mgal"
        _print(f"  [WARN] Usando columna de gravedad: {g_col}")

    g_vals = sub[g_col].values.astype(float)
    height_m = sub["height_sea_level_m"].values.astype(float) if "height_sea_level_m" in sub.columns else np.zeros(len(sub))

    _print(f"  Gravedad Bouguer: [{g_vals.min():.2f}, {g_vals.max():.2f}] mGal")
    _print(f"  Altura estacion: [{height_m.min():.0f}, {height_m.max():.0f}] m")

    out_df = pd.DataFrame({
        "station_id": [f"BSH_{i:04d}" for i in range(len(sub))],
        "x_m":        np.round(x_m, 2),
        "y_m":        0.0,
        "z_m":        np.round(z_m, 2),
        "g":          np.round(g_vals, 4),
        "unit":       "mGal",
        "uncertainty": 0.05,
        "quality_flag": "OK",
        "gravity_type": "bouguer_mgal",
    })

    domain_x = float(x_m.max())
    domain_z = float(z_m.max())
    block_size = max(5000, int(min(domain_x, domain_z) / 30))
    nx = max(8, min(40, int(domain_x / block_size)))
    nz = max(8, min(40, int(domain_z / block_size)))
    ny = max(8, min(25, int(50_000 / block_size)))

    observations = [
        {"x_m": float(r.x_m), "y_m": 0.0, "z_m": float(r.z_m), "g": float(r.g)}
        for r in out_df.itertuples()
    ]

    payload = {
        "project_id": "real_bushveld_v1",
        "run_id": "gravity_run_01",
        "depth": 80000,
        "nir": 5, "fe": 80,
        "region": "Bushveld Igneous Complex, South Africa",
        "lat": str(BUSHVELD_CENTER_LAT), "lon": str(BUSHVELD_CENTER_LON),
        "nx": nx, "ny": ny, "nz": nz,
        "block_size": block_size,
        "cutoff_radius": float(BUSHVELD_RADIUS_KM * 800),
        "lambda_mag": 0.0,
        "alpha_spatial": 1.0,
        "auto_lambda": True,
        "observations": observations,
        "_ground_truth": {
            "note": (
                "El Complejo Bushveld ocupa ~500 km E-O y ~300 km N-S. "
                "La anomalia Bouguer positiva (+20 a +50 mGal) cubre "
                "toda la extension del complejo igneo. "
                "Las rocas densas (gabro, norita, anortosita, cromitita) "
                "generan el alto gravitacional."
            ),
            "validation_criterion": (
                "best_target debe caer dentro del area del complejo "
                f"(x=[0, {domain_x:.0f}] m, z=[0, {domain_z:.0f}] m). "
                "La densidad invertida debe ser > 2.8 t/m3 en el nucleo."
            ),
            "expected_density_range_t_m3": [2.8, 3.5],
            "deposit_type": "Layered Igneous Complex (PGE / Chromite / Vanadium)",
        },
    }

    return out_df, payload


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    _print("=" * 65)
    _print("TerraQuantum — Descarga de Datos Reales")
    _print("Fuente: Geoscience Australia + NOAA NCEI (licencia publica)")
    _print("=" * 65)

    os.makedirs(OUT_DIR, exist_ok=True)

    # ---- OSBORNE MINE --------------------------------------------------------
    try:
        df_osborne = download_xz_csv(OSBORNE_URL, "Osborne Mine (magnetometria aerea)")
        out_osborne, payload_osborne = process_osborne(df_osborne)
        out_osborne.to_csv(OUT_OSBORNE_CSV, index=False)
        with open(OUT_OSBORNE_PAYLOAD, "w", encoding="utf-8") as f:
            json.dump(payload_osborne, f, indent=2, ensure_ascii=False)
        _print(f"\n  [OK] {os.path.basename(OUT_OSBORNE_CSV)} ({len(out_osborne)} sensores)")
        _print(f"  [OK] {os.path.basename(OUT_OSBORNE_PAYLOAD)}")
    except Exception as exc:
        _print(f"\n  [ERROR] Osborne: {exc}")
        _print("  Verifica tu conexion a internet e intenta nuevamente.")

    # ---- BUSHVELD COMPLEX ----------------------------------------------------
    try:
        df_bushveld = download_xz_csv(BUSHVELD_URL, "Bushveld Complex (gravedad terrestre)")
        out_bushveld, payload_bushveld = process_bushveld(df_bushveld)
        out_bushveld.to_csv(OUT_BUSHVELD_CSV, index=False)
        with open(OUT_BUSHVELD_PAYLOAD, "w", encoding="utf-8") as f:
            json.dump(payload_bushveld, f, indent=2, ensure_ascii=False)
        _print(f"\n  [OK] {os.path.basename(OUT_BUSHVELD_CSV)} ({len(out_bushveld)} estaciones)")
        _print(f"  [OK] {os.path.basename(OUT_BUSHVELD_PAYLOAD)}")
    except Exception as exc:
        _print(f"\n  [ERROR] Bushveld: {exc}")
        _print("  Verifica tu conexion a internet e intenta nuevamente.")

    # ---- RESUMEN -------------------------------------------------------------
    _print("\n" + "=" * 65)
    _print("SIGUIENTES PASOS")
    _print("=" * 65)
    _print("""
OPCION A: Subir CSV por la web (Bushveld - gravedad)
  1. Abre TerraQuantum en el navegador
  2. Nuevo Proyecto -> Importar CSV
  3. Sube: tests/data/real_bushveld_gravity.csv
  4. Parametros sugeridos: nx=20, ny=15, nz=20, block_size=10000
  5. Corre la inversion
  6. Valida: el best_target debe tener densidad > 2.8 t/m3

OPCION B: API directa (Osborne - magnetometria)
  curl -X POST http://localhost:8010/api/geophysics/invert \\
       -H "Content-Type: application/json" \\
       -d @tests/data/real_osborne_api_payload.json \\
       -o tests/data/real_osborne_result.json

  Valida con:
  python scripts/validation/validate_output.py \\
         --input tests/data/real_osborne_result.json

GROUND TRUTH (como validar si el resultado es correcto):
  Osborne Mine:
    - La mina existe fisicamente: lat=-22.0966, lon=140.5716
    - El anomalo magnetico DEBE estar centrado sobre esas coords
    - Susceptibilidad esperada: > 0.02 SI (magnetita en IOCG)

  Bushveld:
    - El complejo cubre todo el dominio descargado
    - Densidad esperada: 2.8 - 3.5 t/m3
    - Anomalia positiva (+20 a +50 mGal) en todo el dominio
""")
    _print("=" * 65)


if __name__ == "__main__":
    main()
