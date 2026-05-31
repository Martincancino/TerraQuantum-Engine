"""
TerraQuantum Synthetic Copper Demo v1 — Dataset Generator

Genera un CSV gravimétrico sintético grande y reproducible,
inspirado conceptualmente en parámetros públicos de rajos cupríferos chilenos.

NO contiene datos reales privados de ninguna minera.
NO afirma representar Candelaria ni ninguna operación real.

El forward se calcula directamente por vóxeles no nulos,
sin construir el kernel CSR completo, para evitar matrices
densas gigantes en memoria.
"""

import os
import numpy as np
import polars as pl


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
SEED = 20260509
G_CONST = 6.67430e-11  # m³/(kg·s²)


def compute_forward_g_chunked(
    sensor_coords: np.ndarray,
    x_vox: np.ndarray,
    y_vox: np.ndarray,
    z_vox: np.ndarray,
    density_contrast: np.ndarray,
    voxel_volume: float,
    sensor_chunk_size: int = 64,
) -> np.ndarray:
    """
    Calcula la componente vertical de gravedad (gz) para cada sensor,
    usando solo los vóxeles con contraste no nulo.

    Replica la convención exacta de GravimetryForward (exploration/gravimetry.py):
        dy_vec = y_vox - sy   (vóxel menos sensor)
        gz_i = G * V * 1000 * sum_j( rho_j * dy_ij / r_ij^3 )

    Convención espacial TerraQuantum:
        - y positivo = profundidad hacia abajo
        - sensores en superficie (y = 0)
        - cuerpo anómalo a profundidad (y > 0)
        - un contraste positivo bajo el sensor produce g positiva

    donde:
        G     = constante gravitacional
        V     = volumen del vóxel (m³)
        1000  = conversión t/m³ → kg/m³
        rho_j = contraste de densidad del vóxel j (t/m³)
        dy_ij = y_vox_j - sy_i  (positivo cuando el vóxel está debajo del sensor)
        r_ij  = distancia euclídea sensor i → vóxel j

    Parámetros
    ----------
    sensor_coords : (N, 3) array de coordenadas de sensores
    x_vox, y_vox, z_vox : coordenadas de vóxeles con contraste > 0
    density_contrast : contrastes de densidad correspondientes (t/m³)
    voxel_volume : volumen de cada vóxel (m³)
    sensor_chunk_size : sensores procesados por iteración

    Retorna
    -------
    gz : (N,) array en m/s² (componente vertical de gravedad)
    """
    n_sensors = len(sensor_coords)
    gz = np.zeros(n_sensors, dtype=np.float64)

    prefactor = G_CONST * voxel_volume * 1000.0  # escala fija

    for start in range(0, n_sensors, sensor_chunk_size):
        end = min(start + sensor_chunk_size, n_sensors)
        chunk = sensor_coords[start:end]  # (C, 3)

        # Diferencias vectoriales: vóxel - sensor (misma convención que GravimetryForward)
        # En gravimetry.py: dx_vec = x_vox - sx; dy_vec = y_vox - sy; dz_vec = z_vox - sz
        dx = x_vox[np.newaxis, :] - chunk[:, 0, np.newaxis]
        dy = y_vox[np.newaxis, :] - chunk[:, 1, np.newaxis]
        dz = z_vox[np.newaxis, :] - chunk[:, 2, np.newaxis]

        r2 = dx**2 + dy**2 + dz**2
        r = np.sqrt(r2)

        # Evitar división por cero (no debería ocurrir, sensores en superficie)
        r = np.maximum(r, 1e-10)

        # gz_ij = prefactor * rho_j * dy_ij / r_ij^3
        contrib = prefactor * density_contrast[np.newaxis, :] * dy / (r**3)
        gz[start:end] = contrib.sum(axis=1)

        if start == 0:
            print(
                f"  Chunk 0: {end - start} sensores × {len(x_vox)} vóxeles activos "
                f"→ bloque {(end - start) * len(x_vox):,} operaciones"
            )

    return gz


def generate_demo_dataset():
    np.random.seed(SEED)

    print("=" * 60)
    print("TerraQuantum — Generador de Dataset Sintético Copper Demo v1")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Grilla de observación superficial (33 × 33 = 1089 estaciones)
    # ------------------------------------------------------------------
    x_obs = np.linspace(0, 800, 33)
    z_obs = np.linspace(0, 800, 33)
    xv, zv = np.meshgrid(x_obs, z_obs, indexing="ij")

    sensor_coords = np.column_stack(
        (xv.ravel(), np.zeros_like(xv.ravel()), zv.ravel())
    )
    n_sensors = len(sensor_coords)
    print(f"\nGrilla observacional: 33 × 33 = {n_sensors} estaciones")
    print(f"Espaciamiento: 25 m | Dominio: X [0–800m], Z [0–800m], Y = 0 (superficie)")

    # ------------------------------------------------------------------
    # 2. Modelo de densidad sintético (grilla fina para evitar inverse crime)
    # ------------------------------------------------------------------
    NX, NY, NZ = 64, 40, 64
    BLOCK_SIZE = 12.5  # m — distinta de la grilla de inversión (25 m)
    VOXEL_VOLUME = BLOCK_SIZE**3

    total_synth_voxels = NX * NY * NZ
    print(f"\nGrilla de verdad sintética: {NX}×{NY}×{NZ} = {total_synth_voxels:,} vóxeles")
    print(f"Tamaño de bloque sintético: {BLOCK_SIZE} m")

    grid_x, grid_y, grid_z = np.mgrid[0:NX, 0:NY, 0:NZ]
    ix = grid_x.flatten(order="F").astype(np.int32)
    iy = grid_y.flatten(order="F").astype(np.int32)
    iz = grid_z.flatten(order="F").astype(np.int32)

    x_c = (ix * BLOCK_SIZE) + (BLOCK_SIZE / 2.0)
    y_c = (iy * BLOCK_SIZE) + (BLOCK_SIZE / 2.0)
    z_c = (iz * BLOCK_SIZE) + (BLOCK_SIZE / 2.0)

    # Cuerpo elipsoidal suave con halo gaussiano
    cx, cy, cz = 420.0, 230.0, 390.0
    rx, ry, rz = 180.0, 140.0, 170.0
    max_contrast = 0.55  # t/m³

    r2_norm = ((x_c - cx) / rx) ** 2 + ((y_c - cy) / ry) ** 2 + ((z_c - cz) / rz) ** 2
    true_density_contrast = max_contrast * np.exp(-r2_norm)
    true_density_contrast[true_density_contrast < 0.05] = 0.0

    nonzero_mask = true_density_contrast > 0
    n_active = int(np.sum(nonzero_mask))
    pct_active = 100.0 * n_active / total_synth_voxels

    print(f"\nCuerpo sintético:")
    print(f"  Centro: ({cx}, {cy}, {cz}) m")
    print(f"  Radios: Rx={rx}, Ry={ry}, Rz={rz} m")
    print(f"  Contraste máximo: {max_contrast} t/m³")
    print(f"  Vóxeles con contraste > 0: {n_active:,} / {total_synth_voxels:,} ({pct_active:.1f}%)")

    # ------------------------------------------------------------------
    # 3. Forward directo (sin kernel CSR)
    # ------------------------------------------------------------------
    print(f"\nCalculando forward directo por vóxeles no nulos...")
    print(f"  Método: direct_chunked_nonzero_voxels")

    g_exact = compute_forward_g_chunked(
        sensor_coords=sensor_coords,
        x_vox=x_c[nonzero_mask],
        y_vox=y_c[nonzero_mask],
        z_vox=z_c[nonzero_mask],
        density_contrast=true_density_contrast[nonzero_mask],
        voxel_volume=VOXEL_VOLUME,
        sensor_chunk_size=64,
    )

    # Convertir m/s² → mGal (1 m/s² = 100 000 mGal)
    g_mgal_exact = g_exact * 1e5

    print(f"  Forward completado.")
    print(f"  g exacto (mGal): min={g_mgal_exact.min():.6f}, max={g_mgal_exact.max():.6f}")

    # ------------------------------------------------------------------
    # 4. Ruido controlado
    # ------------------------------------------------------------------
    noise_sigma = 0.02  # mGal
    noise = np.random.normal(0, noise_sigma, size=n_sensors)
    g_observed = g_mgal_exact + noise

    # ------------------------------------------------------------------
    # 5. Escribir CSV
    # ------------------------------------------------------------------
    quality_flags = ["OK"] * n_sensors
    # Unas pocas estaciones con WARNING para simular realismo QA/QC
    for warn_idx in [12, 456, 1020]:
        if warn_idx < n_sensors:
            quality_flags[warn_idx] = "WARNING"

    df = pl.DataFrame(
        {
            "station_id": [f"ST_{i:04d}" for i in range(n_sensors)],
            "x_m": sensor_coords[:, 0],
            "y_m": sensor_coords[:, 1],
            "z_m": sensor_coords[:, 2],
            "g": g_observed,
            "unit": ["mGal"] * n_sensors,
            "uncertainty": [noise_sigma] * n_sensors,
            "quality_flag": quality_flags,
            "gravity_type": ["synthetic_demo"] * n_sensors,
        }
    )

    out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "demo_data"))
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "tq_synthetic_copper_demo_v1_bouguer_mgal.csv")
    df.write_csv(out_file)

    # ------------------------------------------------------------------
    # Resumen final
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("RESUMEN DATASET SINTÉTICO")
    print("=" * 60)
    print(f"Estaciones generadas   : {n_sensors}")
    print(f"Rango de g (mGal)      : {g_observed.min():.6f}  a  {g_observed.max():.6f}")
    print(f"Promedio de g (mGal)   : {g_observed.mean():.6f}")
    print(f"Sigma ruido (mGal)     : {noise_sigma}")
    print(f"Vóxeles totales synth  : {total_synth_voxels:,}")
    print(f"Vóxeles activos (≠0)   : {n_active:,} ({pct_active:.1f}%)")
    print(f"Método forward         : direct_chunked_nonzero_voxels")
    print(f"Archivo guardado en    : {out_file}")
    print("=" * 60)


if __name__ == "__main__":
    generate_demo_dataset()
