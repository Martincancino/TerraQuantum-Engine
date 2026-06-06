#!/usr/bin/env python3
"""
Generar dataset sintético realista pequeño:
- 20×20 km horizontales (escala minería junior Chile)
- Depósito pórfido Cu: 2.5 km ancho, 2 km profundidad
- 150 observaciones de gravedad Bouguer
- Coordenadas: Antofagasta, Chile (UTM 19S)
"""

import json
import math
import csv
from pathlib import Path

def gaussian_anomaly(x_m, y_m, z_m, center_x=10000, center_y=10000, center_z=1500,
                     sigma_x=1500, sigma_y=1500, sigma_z=1000, max_contrast=0.4):
    """Anomalía gravimétrica de Bouguer simulada con gaussiana 3D (depósito pórfido)."""
    dx = (x_m - center_x) / sigma_x
    dy = (y_m - center_y) / sigma_y
    dz = (z_m - center_z) / sigma_z

    amp = max_contrast * math.exp(-(dx**2 + dy**2 + dz**2) / 2)
    return amp

def generate_synthetic_porphyry():
    """Generar observaciones de gravedad sintéticas realistas."""

    # Parámetros del grid de observaciones
    grid_size_x = 20000  # 20 km
    grid_size_y = 20000  # 20 km
    spacing = 1500  # ~1.5 km entre observaciones (13×13 grid ≈ 169 puntos)

    observations = []
    x_coords = [i * spacing for i in range(14) if i * spacing <= grid_size_x]
    y_coords = [i * spacing for i in range(14) if i * spacing <= grid_size_y]

    # Generar observaciones en superficie (z_m = 0, elevación media del terreno)
    for x in x_coords:
        for y in y_coords:
            z = 0  # Superficie

            # Anomalía Bouguer sintética (gaussiana centrada en x=10km, y=10km, profundidad=1.5km)
            anomaly = gaussian_anomaly(x, y, z, center_x=10000, center_y=10000, center_z=1500,
                                      sigma_x=1500, sigma_y=1500, sigma_z=1000, max_contrast=0.4)

            # Ruido realista: ±2 mGal
            noise = (hash(f"{x}_{y}") % 100) / 2500 - 0.02
            g = anomaly + noise

            observations.append({
                'x_m': x,
                'y_m': y,
                'z_m': z,
                'g': g
            })

    return observations

def save_csv(observations, filepath):
    """Guardar observaciones como CSV con todas las columnas requeridas."""
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, 'w', newline='') as f:
        # Agregar columnas requeridas por el validador
        fieldnames = ['station_id', 'x_m', 'y_m', 'z_m', 'g', 'unit', 'gravity_type']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for idx, obs in enumerate(observations):
            row = {
                'station_id': f'STN_{idx:03d}',
                'x_m': obs['x_m'],
                'y_m': obs['y_m'],
                'z_m': obs['z_m'],
                'g': obs['g'],
                'unit': 'mGal',  # miliGal (anomalia de Bouguer)
                'gravity_type': 'bouguer_anomaly'  # formato especifico requerido
            }
            writer.writerow(row)

    print(f"[OK] Guardado: {filepath}")
    print(f"  Observaciones: {len(observations)}")
    spacing_val = observations[1]['x_m'] - observations[0]['x_m'] if len(observations) > 1 else 0
    print(f"  Grid: 20x20 km, spacing {spacing_val:.0f}m")
    print(f"  Columnas: station_id, x_m, y_m, z_m, g, unit, gravity_type")
    return filepath

def save_api_payload(observations, filepath, project_id="demo_porphyry", run_id="run_001"):
    """Guardar payload JSON para POST /geophysics-invert."""

    obs_list = [
        {
            "x_m": float(obs['x_m']),
            "y_m": float(obs['y_m']),
            "z_m": float(obs['z_m']),
            "g": float(obs['g'])
        }
        for obs in observations
    ]

    payload = {
        "project_id": project_id,
        "run_id": run_id,
        "depth": 5000,  # 5 km profundidad objetivo
        "nir": 50,  # dummy satélite
        "fe": 50,   # dummy satélite
        "region": "Antofagasta",
        "lat": None,  # Sin georef (datos de gravímetro crudo)
        "lon": None,
        "nx": 20,
        "ny": 20,
        "nz": 10,
        "block_size": 1000,  # 1 km voxels
        "cutoff_radius": 3000.0,  # 3 km radio de corte
        "lambda_mag": 3.0,  # Operating point
        "alpha_spatial": 10.0,
        "observations": obs_list,
        "remove_regional": False,
        "expose_demo_grade": False,
        "compute_uncertainty": False,
        "density_min": 2.6,
        "density_max": 4.2,
    }

    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, 'w') as f:
        json.dump(payload, f, indent=2)

    print(f"[OK] Payload JSON: {filepath}")
    return filepath

if __name__ == "__main__":
    obs = generate_synthetic_porphyry()

    csv_path = Path(__file__).parent / "synthetic_porphyry_small.csv"
    json_path = Path(__file__).parent / "synthetic_porphyry_api_payload.json"

    save_csv(obs, csv_path)
    save_api_payload(obs, json_path)

    print("\n[OK] Dataset sintetico realista generado:")
    print(f"  - CSV: {csv_path}")
    print(f"  - API Payload: {json_path}")
