"""
FASE 10 — Parte 3: Clustering espacial de cuerpos geológicos.

Responsabilidad única: recibir los arreglos físicos ya invertidos (ρ, χ, coordenadas)
y devolver un payload COMPACTO de anomalías discretas (cuerpos geológicos) listo para
consumo por el prompt de Gemini.

Diseño sin dependencias extra
──────────────────────────────
El clustering usa EXCLUSIVAMENTE scipy (ya presente en el proyecto):
  1. scipy.spatial.KDTree  → vecindad espacial con radio eps.
  2. scipy.sparse.csgraph.connected_components  → etiquetado de componentes conexas.

Esto evita instalar scikit-learn y es agnóstico a la distribución estadística del
dataset: no asume ninguna forma de los cuerpos ni escala de las propiedades.

Score normalizado I_joint
──────────────────────────
Calcula I_ρ y I_χ relativo al fondo estadístico (mediana) y al máximo del campo.
El score conjunto  I_joint = sqrt(I_ρ² + I_χ²) ∈ [0, √2] mide cuánto se aparta
un vóxel del fondo en ambas propiedades simultáneamente. La máscara  I_joint > threshold
filtra la zona anómala antes del clustering espacial.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import scipy.sparse as sp
import scipy.sparse.csgraph as csgraph
from scipy.spatial import KDTree


def extract_geological_bodies(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    density: np.ndarray,
    susceptibility: np.ndarray,
    dx: float,
    dy: float,
    dz: float,
    threshold: float = 0.6,
    eps_factor: float = 1.5,
    min_voxels: int = 5,
) -> list[dict[str, Any]]:
    """Detecta y caracteriza cuerpos geológicos anómalos a partir de la inversión conjunta.

    Parameters
    ----------
    x, y, z : ndarray (nC,)
        Coordenadas de centro de cada vóxel (m).
    density : ndarray (nC,)
        Densidad absoluta recuperada (t/m³).
    susceptibility : ndarray (nC,)
        Susceptibilidad magnética recuperada (SI).
    dx, dy, dz : float
        Tamaño del vóxel en cada eje (m).
    threshold : float
        Umbral de I_joint para la máscara de anomalías (default 0.6).
    eps_factor : float
        Radio del clustering = eps_factor * max(dx, dy, dz) (default 1.5).
    min_voxels : int
        Tamaño mínimo de cluster para considerarlo válido (default 5).

    Returns
    -------
    list[dict]
        Lista ordenada por volumen descendente. Cada dict contiene:
        anomaly_id, voxel_count, volume_m3, centroid, density_mean,
        density_max, susceptibility_mean, susceptibility_max,
        density_susceptibility_correlation.
        Lista vacía si no se detecta ningún cluster válido.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    density = np.asarray(density, dtype=np.float64)
    susceptibility = np.asarray(susceptibility, dtype=np.float64)

    nC = x.size
    if nC == 0:
        return []

    voxel_volume = float(dx) * float(dy) * float(dz)

    # ── 1. Score normalizado I_joint ─────────────────────────────────────────
    rho_bg = float(np.median(density))
    rho_max = float(np.max(density))
    rho_range = rho_max - rho_bg
    if rho_range <= 0.0:
        I_rho = np.zeros(nC)
    else:
        I_rho = np.clip((density - rho_bg) / rho_range, 0.0, 1.0)

    chi_bg = float(np.median(susceptibility))
    chi_max = float(np.max(susceptibility))
    chi_range = chi_max - chi_bg
    if chi_range <= 0.0:
        I_chi = np.zeros(nC)
    else:
        I_chi = np.clip((susceptibility - chi_bg) / chi_range, 0.0, 1.0)

    I_joint = np.sqrt(I_rho ** 2 + I_chi ** 2)

    # ── 2. Máscara de anomalías ──────────────────────────────────────────────
    mask = I_joint > threshold
    idx_anom = np.where(mask)[0]

    if idx_anom.size < min_voxels:
        return []

    # ── 3. Clustering espacial con KDTree + connected_components ────────────
    coords_anom = np.column_stack([x[idx_anom], y[idx_anom], z[idx_anom]])
    eps = eps_factor * max(dx, dy, dz)

    tree = KDTree(coords_anom)
    pairs = tree.query_pairs(eps, output_type="ndarray")  # shape (M, 2)

    n_pts = len(idx_anom)
    if pairs.size > 0:
        data = np.ones(len(pairs), dtype=np.int8)
        adj = sp.csr_matrix(
            (data, (pairs[:, 0], pairs[:, 1])),
            shape=(n_pts, n_pts),
        )
        adj = adj + adj.T
    else:
        adj = sp.csr_matrix((n_pts, n_pts), dtype=np.int8)

    n_components, labels = csgraph.connected_components(
        adj, directed=False, return_labels=True
    )

    # ── 4. Extracción de métricas por cluster ────────────────────────────────
    anomalies = []
    for cid in range(n_components):
        cluster_local = np.where(labels == cid)[0]
        if len(cluster_local) < min_voxels:
            continue

        global_idx = idx_anom[cluster_local]
        cx = x[global_idx]
        cy = y[global_idx]
        cz = z[global_idx]
        rho_c = density[global_idx]
        chi_c = susceptibility[global_idx]

        correlation = float("nan")
        if len(rho_c) > 1:
            rho_std = float(np.std(rho_c))
            chi_std = float(np.std(chi_c))
            if rho_std > 0.0 and chi_std > 0.0:
                correlation = float(np.corrcoef(rho_c, chi_c)[0, 1])

        anomalies.append({
            "voxel_count": int(len(cluster_local)),
            "volume_m3": round(float(len(cluster_local)) * voxel_volume, 2),
            "centroid": {
                "x_m": round(float(np.mean(cx)), 2),
                "y_m": round(float(np.mean(cy)), 2),
                "z_m": round(float(np.mean(cz)), 2),
            },
            "density_mean": round(float(np.mean(rho_c)), 4),
            "density_max": round(float(np.max(rho_c)), 4),
            "susceptibility_mean": round(float(np.mean(chi_c)), 6),
            "susceptibility_max": round(float(np.max(chi_c)), 6),
            "density_susceptibility_correlation": round(correlation, 4)
            if not np.isnan(correlation)
            else None,
        })

    # Ordenar por volumen descendente y asignar IDs legibles.
    anomalies.sort(key=lambda a: a["voxel_count"], reverse=True)
    for i, a in enumerate(anomalies):
        a["anomaly_id"] = f"A{i + 1}"

    # Reordenar campos para que anomaly_id quede primero.
    ordered = []
    for a in anomalies:
        ordered.append({
            "anomaly_id": a["anomaly_id"],
            "voxel_count": a["voxel_count"],
            "volume_m3": a["volume_m3"],
            "centroid": a["centroid"],
            "density_mean": a["density_mean"],
            "density_max": a["density_max"],
            "susceptibility_mean": a["susceptibility_mean"],
            "susceptibility_max": a["susceptibility_max"],
            "density_susceptibility_correlation": a["density_susceptibility_correlation"],
        })

    return ordered
