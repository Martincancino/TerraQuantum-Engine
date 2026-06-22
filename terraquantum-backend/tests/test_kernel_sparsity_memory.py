"""Dispersión del kernel + red de seguridad de memoria (sin tope de vóxeles).

Cubre el fix del OOM de DO-27 (600 m, 961 estaciones, 160k vóxeles):

  1. cutoff_radius escalado a la profundidad de INVESTIGACIÓN (≈ extensión/3), NO al
     espesor floored del modelo (1000 m). Esto mantiene el kernel disperso.
  2. NO hay regresión en surveys grandes (cutoff == depth_m cuando extensión ≥ ~3 km).
  3. Con el cutoff sano el kernel de DO-27 (160k vóxeles) es DISPERSO y se construye
     sin OOM.
  4. Red de seguridad: un kernel patológicamente denso aborta con un error CLARO
     (SOLVER_KERNEL_TOO_DENSE) en lugar de tumbar el proceso.
  5. NO existe un tope de vóxeles: una malla de cientos de miles de celdas con kernel
     DISPERSO se construye sin problema (el guard depende de la densidad, no del conteo).

Backend-only, sin tunear física.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from core.errors import SolverMemoryError
from exploration.gravimetry import GravimetryForward, _guard_sparse_kernel_memory
from services.grid_calculator_service import (
    DEPTH_SENS_FACTOR,
    MIN_DEPTH_M,
    compute_auto_grid,
)


# ── Helpers ──────────────────────────────────────────────────────────────────
def _grid_centers(nx, ny, nz, block):
    xs = (np.arange(nx) + 0.5) * block
    ys = (np.arange(ny) + 0.5) * block   # y = profundidad hacia abajo
    zs = (np.arange(nz) + 0.5) * block
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    return X.ravel(), Y.ravel(), Z.ravel()


def _surface_sensors(nx, nz, block, n_side):
    xs = np.linspace(block, (nx - 1) * block, n_side)
    zs = np.linspace(block, (nz - 1) * block, n_side)
    XX, ZZ = np.meshgrid(xs, zs)
    return np.column_stack([XX.ravel(), np.zeros(XX.size), ZZ.ravel()])


def _patch_available_ram(monkeypatch, n_bytes):
    """Fuerza psutil.virtual_memory().available a un valor fijo (determinista)."""
    import psutil

    class _VM:
        available = int(n_bytes)

    monkeypatch.setattr(psutil, "virtual_memory", lambda: _VM())


# ── PASO 1: cutoff escalado a la geometría ───────────────────────────────────
def test_cutoff_scaled_to_investigation_depth_small_survey():
    """DO-27 (600 m): cutoff atado a la DOI (~200 m), NO al floor de 1000 m."""
    ag = compute_auto_grid(600.0, 600.0, 961, "BUENA", mean_spacing_m=19.35)
    # El modelo sigue floored a >= MIN_DEPTH_M (mantiene los 160k vóxeles)…
    assert ag.depth_m >= MIN_DEPTH_M
    # …pero el cutoff se ata a la profundidad de investigación = extensión / factor.
    expected_doi = 600.0 / DEPTH_SENS_FACTOR
    assert ag.cutoff_radius_m == pytest.approx(expected_doi, abs=1.0)
    # Clave: cutoff MUCHO menor que el espesor floored → kernel disperso.
    assert ag.cutoff_radius_m < ag.depth_m


def test_cutoff_no_regression_large_survey():
    """Survey ≥ ~3 km: investigation_depth == depth_m → cutoff sin cambio (cero regresión)."""
    ag = compute_auto_grid(9000.0, 9000.0, 400, "BUENA", mean_spacing_m=450.0)
    # max_extent / 3 = 3000 ≥ MIN_DEPTH_M → el término de DOI iguala a depth_m.
    assert ag.cutoff_radius_m >= ag.depth_m - 1.0


# ── PASO 1 (medido): el cutoff sano hace el kernel DISPERSO ───────────────────
def test_scaled_cutoff_makes_kernel_sparse(monkeypatch):
    _patch_available_ram(monkeypatch, 4 * 1024**3)  # 4 GB: aísla de la RAM real
    block = 20.0
    nx = nz = 24
    ny = 50  # depth = 1000 m sobre un survey de 480 m → mismo patrón que DO-27
    x, y, z = _grid_centers(nx, ny, nz, block)
    sensors = _surface_sensors(nx, nz, block, 16)

    doi = (nx * block) / DEPTH_SENS_FACTOR  # ~160 m
    Ks = GravimetryForward(block, block, block, cutoff_radius=doi).build_sparse_kernel(x, y, z, sensors)
    fill_sparse = Ks.nnz / (Ks.shape[0] * Ks.shape[1])

    # cutoff = espesor floored (comportamiento viejo) → kernel mucho más denso.
    Kd = GravimetryForward(block, block, block, cutoff_radius=ny * block).build_sparse_kernel(x, y, z, sensors)
    fill_dense = Kd.nnz / (Kd.shape[0] * Kd.shape[1])

    assert fill_sparse < 0.15
    assert fill_dense > 2.0 * fill_sparse
    # Mismo nº de columnas: el cutoff NO descarta vóxeles del dominio, sólo entradas.
    assert Ks.shape[1] == Kd.shape[1] == nx * ny * nz


# ── PASO 3: red de seguridad (error claro, no OOM) ───────────────────────────
def test_memory_safety_net_raises_clear_error(monkeypatch):
    _patch_available_ram(monkeypatch, 50 * 1024**2)  # sólo 50 MB libres
    block = 20.0
    nx = nz = 24
    ny = 40
    x, y, z = _grid_centers(nx, ny, nz, block)
    sensors = _surface_sensors(nx, nz, block, 16)

    fwd = GravimetryForward(block, block, block, cutoff_radius=ny * block)  # denso
    with pytest.raises(SolverMemoryError) as ei:
        fwd.build_sparse_kernel(x, y, z, sensors)

    err = ei.value
    assert err.code == "SOLVER_KERNEL_TOO_DENSE"
    assert err.severity == "error"
    assert err.suggested_action  # accionable (Fase 23)
    # El mensaje habla de densidad/cutoff, no de un límite de celdas.
    assert "cutoff" in err.suggested_action.lower()


def test_safety_net_does_not_trigger_on_sparse(monkeypatch):
    _patch_available_ram(monkeypatch, 256 * 1024**2)  # 256 MB
    block = 20.0
    nx = nz = 24
    ny = 40
    x, y, z = _grid_centers(nx, ny, nz, block)
    sensors = _surface_sensors(nx, nz, block, 16)

    doi = (nx * block) / DEPTH_SENS_FACTOR
    K = GravimetryForward(block, block, block, cutoff_radius=doi).build_sparse_kernel(x, y, z, sensors)
    assert K.nnz > 0


# ── PASO 3 (red de seguridad ≠ tope de vóxeles) ──────────────────────────────
def test_no_voxel_cap_sparse_kernel_many_cells(monkeypatch):
    """Cientos de miles de celdas + kernel DISPERSO → se construye sin error.

    Prueba explícita de que NO hay un límite de vóxeles: el guard depende de la
    densidad del kernel (geometría × cutoff), no del conteo de celdas.
    """
    _patch_available_ram(monkeypatch, 4 * 1024**3)  # 4 GB
    block = 20.0
    nx = nz = 60
    ny = 60  # 216,000 celdas
    n_cells = nx * ny * nz
    assert n_cells > 200_000  # por encima de cualquier límite histórico de grilla

    x, y, z = _grid_centers(nx, ny, nz, block)
    sensors = _surface_sensors(nx, nz, block, 20)

    fwd = GravimetryForward(block, block, block, cutoff_radius=60.0)  # ~3 celdas → disperso
    K = fwd.build_sparse_kernel(x, y, z, sensors)

    assert K.shape[1] == n_cells  # TODAS las celdas presentes — ninguna recortada
    fill = K.nnz / (K.shape[0] * K.shape[1])
    assert fill < 0.05  # disperso de verdad


# ── Guard helper (unidad) ────────────────────────────────────────────────────
def test_guard_returns_nnz_when_within_budget(monkeypatch):
    from scipy.spatial import cKDTree

    _patch_available_ram(monkeypatch, 4 * 1024**3)
    rng = np.random.RandomState(0)
    pts = rng.rand(2000, 3) * 100.0
    tree = cKDTree(pts)
    sensors = rng.rand(40, 3) * 100.0

    nnz = _guard_sparse_kernel_memory(tree, sensors, 25.0, n_active=2000, n_obs=40)
    assert nnz is not None
    assert nnz >= 0


# ── Integración: DO-27 full-scale carga sin OOM ──────────────────────────────
def test_do27_scale_full_load_builds_sparse_no_oom(monkeypatch):
    """Survey escala DO-27 (600 m, 961 est) vía auto_grid → kernel disperso, sin OOM.

    Antes: cutoff 1000 m → fill ~93%, ~1.7 GB por kernel → OOM con 160k vóxeles.
    Ahora: cutoff escalado a la DOI → fill < 10%, decenas de MB → carga completa.
    """
    _patch_available_ram(monkeypatch, 4 * 1024**3)
    xs = np.linspace(0.0, 600.0, 31)
    zs = np.linspace(0.0, 600.0, 31)
    XX, ZZ = np.meshgrid(xs, zs)
    n = XX.size  # 961
    spacing = math.sqrt((600.0 * 600.0) / n)

    ag = compute_auto_grid(600.0, 600.0, n, "BUENA", mean_spacing_m=spacing)
    assert ag.voxel_count > 50_000          # grilla grande (antes OOM)
    assert ag.cutoff_radius_m < ag.depth_m  # cutoff escalado, no floored

    block = ag.block_size_m
    x, y, z = _grid_centers(ag.nx, ag.ny, ag.nz, block)
    sensors = np.column_stack([XX.ravel(), np.zeros(n), ZZ.ravel()])

    fwd = GravimetryForward(block, block, block, cutoff_radius=ag.cutoff_radius_m)
    K = fwd.build_sparse_kernel(x, y, z, sensors)

    fill = K.nnz / (K.shape[0] * K.shape[1])
    assert fill < 0.10                      # disperso
    assert K.shape[1] == ag.voxel_count     # TODOS los vóxeles, sin tope
