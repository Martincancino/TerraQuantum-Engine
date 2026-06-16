import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
import numpy as np
import polars as pl
import scipy.sparse as sp
from scipy.sparse.linalg import lsqr
from scipy.spatial import cKDTree  # F0.2: HPC KDTree kernel híbrido

logger = logging.getLogger(__name__)


def _sigma_adaptive(g_observed: np.ndarray) -> np.ndarray:
    """
    R-04: Sigma calibrado a la amplitud de los datos (Li & Oldenburg / SimPEG).

    Formulación:  sigma_i = max(0.02 * |d_obs_i|,  0.01 * data_range)

    Reemplaza el noise_floor=0.02 absoluto en SI (m/s²) que equivale a
    ~2000 mGal — varios órdenes de magnitud sobre la señal gravimétrica típica
    (0.001–0.1 mGal). La nueva formulación es invariante de escala: funciona
    tanto si los datos están en m/s² como en mGal, o cualquier otra unidad.

    Referencia: Li & Oldenburg 1998; SimPEG noise_floor + relative_error.
    """
    data_range = max(float(np.max(g_observed) - np.min(g_observed)), 1e-30)
    sigma = np.maximum(0.02 * np.abs(g_observed), 0.01 * data_range)
    return np.maximum(sigma, 1e-30)


def _sigma_parametric(g_observed: np.ndarray, noise_floor: float, noise_pct: float) -> np.ndarray:
    """
    Sigma con piso instrumental explícito (flujo de datos de campo).

        sigma_i = max(noise_floor, noise_pct * |d_obs_i|)

    noise_floor es un PISO (no se suma): para anomalías de Bouguer bien
    corregidas el ruido restante es instrumental (CG-6 ≈ 0.005 mGal) y el
    término relativo solo domina cuando |d| es grande. La forma aditiva
    anterior (floor + pct·|d|) sobreestimaba sigma ~|d|/floor veces para
    datos de campo, colapsando chi²_red a ~0.

    Unidades: las mismas de g_observed (el caller convierte mGal → m/s²).
    """
    sigma = np.maximum(float(noise_floor), float(noise_pct) * np.abs(g_observed))
    return np.maximum(sigma, 1e-30)


def hutchinson_diag_inv(
    A,
    n_probes: int = 32,
    cg_maxiter: int = 300,
    cg_rtol: float = 1e-6,
    seed: int = 0,
) -> np.ndarray:
    """
    Estimador estocástico de Hutchinson de diag(A^{-1}) para A dispersa SPD.

        diag(A^{-1}) ≈ (1/N) Σ_k  z_k ⊙ (A^{-1} z_k),   z_k ~ Rademacher (±1)

    Cada A^{-1} z_k se resuelve por Gradiente Conjugado (A debe ser SPD). El
    estimador es INSESGADO: como E[z zᵀ] = I, se cumple
        E[z ⊙ (A^{-1} z)] = diag(A^{-1}).
    El error decae como O(1/√N). Es el método estándar para la diagonal de la
    covarianza posterior en problemas inversos lineales gaussianos a gran escala
    (Bekas, Kokiopoulou & Saad, 2007), sin formar A^{-1} explícitamente.

    Parameters
    ----------
    A          : scipy.sparse SPD (n×n).
    n_probes   : número de vectores sonda (más sondas → menos varianza del estimador).
    cg_maxiter : tope de iteraciones del CG por sonda.
    cg_rtol    : tolerancia relativa del CG.
    seed       : semilla RNG (reproducibilidad determinística).

    Returns
    -------
    diag_est : ndarray (n,) — estimación de diag(A^{-1}), recortada a ≥ 0.
    """
    from scipy.sparse.linalg import cg, LinearOperator

    A = A.tocsr()
    n = A.shape[0]
    if A.shape[0] != A.shape[1]:
        raise ValueError("A debe ser cuadrada para estimar diag(A^{-1}).")

    rng = np.random.default_rng(seed)

    # Preacondicionador de Jacobi (diagonal): acelera CG, no cambia el resultado.
    diag_A = A.diagonal()
    diag_A_safe = np.where(np.abs(diag_A) > 1e-30, diag_A, 1.0)
    M = LinearOperator((n, n), matvec=lambda v: v / diag_A_safe)

    acc = np.zeros(n, dtype=np.float64)
    for _ in range(int(n_probes)):
        z = rng.integers(0, 2, size=n).astype(np.float64) * 2.0 - 1.0  # Rademacher ±1
        x, _info = cg(A, z, rtol=cg_rtol, atol=0.0, maxiter=cg_maxiter, M=M)
        acc += z * x

    diag_est = acc / float(n_probes)
    return np.clip(diag_est, a_min=0.0, a_max=None)


class GravimetryForward:
    """
    FORWARD MODEL:
    Construye el kernel gravitacional como matriz dispersa CSR.

    Convención espacial:
    - x: eje horizontal
    - y: profundidad positiva hacia abajo
    - z: eje horizontal
    - densidad de entrada de la inversión: t/m3
    """

    def __init__(self, dx=10.0, dy=10.0, dz=10.0, cutoff_radius=800.0):
        self.dx = float(dx)
        self.dy = float(dy)
        self.dz = float(dz)
        self.voxel_volume = self.dx * self.dy * self.dz
        self.G = 6.67430e-11
        self.cutoff_radius = float(cutoff_radius)
        # T3.3 — Caché de G_active de UNA entrada (la última geometría).
        # El kernel depende SOLO de la geometría (coords activas, sensores, dx/dy/dz,
        # cutoff), NO de lambda/m_ref/ruido. Dentro de un run, solve/L-curve/DOI/UQ
        # reusan la misma geometría → se evita reconstruir el KDTree. La validación es
        # por np.array_equal (sin riesgo de colisión de hash) y el uso es read-only.
        self._kernel_cache = None  # (geom_key_tuple) | None
        self._kernel_cache_mat = None
        self.kernel_build_count = 0  # diagnóstico/test: nº de construcciones reales

    @staticmethod
    def _nagy_prism_safe(dx_vec, dy_vec, dz_vec, dx, dy, dz, G_const):
        """
        F0.2: Calcula g_y (componente vertical) exacto para prismas rectangulares (Nagy, 1966).

        Anti-singularity improvements:
        - eps ajustado a la escala del vóxel (1e-10 * min_dim) en vez de eps fijo.
        - Inyección eps en el radio: r = sqrt(x²+y²+z²+eps) — evita r=0 en sensor=centroide.
        - arctan2 OBLIGATORIO: arctan2(xz, yr+eps) — evita división por cero en y=0.
        - LOG SEGURO: log(maximum(arg, eps)) — evita log(0) en lugar de abs+eps.
        - dtype float64 obligatorio.
        """
        total_g = np.zeros_like(dx_vec, dtype=np.float64)
        # eps escala con la dimensión mínima del vóxel. np.minimum soporta tanto
        # dx/dy/dz escalares (ruta uniforme, resultado idéntico a min()) como
        # arrays por-celda (ruta TreeMesh con celdas de tamaño variable).
        eps = 1e-10 * np.minimum(np.minimum(dx, dy), dz)

        for i, sign_x in enumerate([-1, 1]):
            x = dx_vec + sign_x * (dx / 2.0)
            for j, sign_y in enumerate([-1, 1]):
                y = dy_vec + sign_y * (dy / 2.0)
                for k, sign_z in enumerate([-1, 1]):
                    z = dz_vec + sign_z * (dz / 2.0)

                    sign = (-1) ** (i + j + k)

                    # Anti-singularity: inyección eps en el radio
                    r = np.sqrt(x*x + y*y + z*z + eps)
                    # Log seguro: maximum en lugar de abs+eps
                    log_zr = np.log(np.maximum(z + r, eps))
                    log_xr = np.log(np.maximum(x + r, eps))
                    # arctan2 obligatorio: evita arctan(xz/yr) con yr→0
                    atan_term = np.arctan2(x * z, y * r + eps)

                    kernel = x * log_zr + z * log_xr - y * atan_term
                    total_g += sign * kernel

        # 1000.0: conversión densidad t/m³ → kg/m³
        return G_const * 1000.0 * total_g

    def _build_sparse_kernel(self, x_c_act, y_c_act, z_c_act, sensor_coords,
                             cell_dx=None, cell_dy=None, cell_dz=None):
        """
        F0.2 HPC: Construye G_active (n_obs × n_active) DIRECTAMENTE para las celdas activas.

        Arquitectura:
        - KDTree construido ÚNICAMENTE sobre los centros de vóxeles activos.
        - Campo cercano (r ≤ threshold = 4·a_eq): Nagy exacto (_nagy_prism_safe).
        - Campo lejano  (threshold < r ≤ cutoff_radius): Masa Puntual (vectorizado).
        - Vóxeles fuera del cutoff_radius: contribución = 0, no se almacenan.
        - Acumulación por CSR triplets (rows, cols, data) — cero fancy indexing global.
        - Retorna sp.csr_matrix shape=(n_obs, n_active) dtype=float64.

        SPRINT 3A — Celdas de tamaño variable (TreeMesh):
        Si se proveen cell_dx/cell_dy/cell_dz (arrays 1D de longitud n_active con la
        extensión física de CADA celda), el kernel usa el tamaño y volumen POR CELDA
        en lugar del escalar uniforme self.dx/dy/dz. Esta ruta es ADITIVA y opt-in:
        con cell_d* = None el comportamiento es byte-idéntico a la versión uniforme
        (incluida la caché de geometría). La ruta variable omite la caché.
        """
        x_c_act = np.asarray(x_c_act, dtype=np.float64)
        y_c_act = np.asarray(y_c_act, dtype=np.float64)
        z_c_act = np.asarray(z_c_act, dtype=np.float64)
        sensor_coords = np.asarray(sensor_coords, dtype=np.float64)

        # ── SPRINT 3A: ruta de celdas variables (TreeMesh) ───────────────────
        _variable = cell_dx is not None or cell_dy is not None or cell_dz is not None
        if _variable:
            return self._build_sparse_kernel_variable(
                x_c_act, y_c_act, z_c_act, sensor_coords,
                cell_dx, cell_dy, cell_dz,
            )

        # ── T3.3: caché de UNA entrada (geometría) — kernel independiente de
        # λ/m_ref/ruido. Validación por np.array_equal (sin colisión de hash).
        geom_key = (self.dx, self.dy, self.dz, self.cutoff_radius,
                    x_c_act.shape, sensor_coords.shape)
        if (
            self._kernel_cache_mat is not None
            and self._kernel_cache is not None
            and self._kernel_cache[0] == geom_key
            and np.array_equal(self._kernel_cache[1], x_c_act)
            and np.array_equal(self._kernel_cache[2], y_c_act)
            and np.array_equal(self._kernel_cache[3], z_c_act)
            and np.array_equal(self._kernel_cache[4], sensor_coords)
        ):
            print("[FORWARD HPC] Cache HIT: G_active reutilizado (misma geometría, sin KDTree).")
            return self._kernel_cache_mat

        n_active = len(x_c_act)
        n_obs = len(sensor_coords)

        a_eq = np.sqrt(self.dx**2 + self.dy**2 + self.dz**2)
        threshold = min(4.0 * a_eq, self.cutoff_radius)

        t_start = time.perf_counter()
        max_workers = max(1, (os.cpu_count() or 2) - 1)

        print(
            f"[FORWARD HPC] KDTree Híbrido + ThreadPool({max_workers}w). "
            f"n_active={n_active:,} | n_obs={n_obs:,} | "
            f"threshold={threshold:.1f}m | cutoff={self.cutoff_radius:.0f}m"
        )

        voxel_centers = np.column_stack([x_c_act, y_c_act, z_c_act])
        tree = cKDTree(voxel_centers)

        # Bulk query: 2 calls for ALL sensors (vs 2×n_obs calls in the serial loop)
        t_q0 = time.perf_counter()
        near_lists   = tree.query_ball_point(sensor_coords, r=threshold)
        cutoff_lists = tree.query_ball_point(sensor_coords, r=self.cutoff_radius)
        t_q1 = time.perf_counter()

        # Capture read-only refs for workers — no shared mutable state
        _x, _y, _z  = x_c_act, y_c_act, z_c_act
        _dx, _dy, _dz, _G, _vol = self.dx, self.dy, self.dz, self.G, self.voxel_volume
        _nagy = self._nagy_prism_safe  # staticmethod — thread-safe, no GIL contention

        def _sensor_row(i):
            """Returns (rows_arr, cols_arr, data_arr) for sensor i — no shared writes."""
            sx, sy, sz = sensor_coords[i]
            near_idx   = np.asarray(near_lists[i],   dtype=np.int32)
            cutoff_idx = np.asarray(cutoff_lists[i], dtype=np.int32)
            far_idx    = np.setdiff1d(cutoff_idx, near_idx, assume_unique=True)

            r_parts, c_parts, d_parts = [], [], []

            if len(far_idx) > 0:
                dxv = _x[far_idx] - sx
                dyv = _y[far_idx] - sy
                dzv = _z[far_idx] - sz
                r3  = (dxv**2 + dyv**2 + dzv**2) ** 1.5
                r_parts.append(np.full(len(far_idx), i, dtype=np.int32))
                c_parts.append(far_idx)
                d_parts.append((_G * _vol * 1000.0 * dyv) / r3)

            if len(near_idx) > 0:
                dxv = _x[near_idx] - sx
                dyv = _y[near_idx] - sy
                dzv = _z[near_idx] - sz
                r_parts.append(np.full(len(near_idx), i, dtype=np.int32))
                c_parts.append(near_idx)
                d_parts.append(_nagy(dxv, dyv, dzv, _dx, _dy, _dz, _G))

            if not r_parts:
                return (
                    np.empty(0, dtype=np.int32),
                    np.empty(0, dtype=np.int32),
                    np.empty(0, dtype=np.float64),
                )
            return (
                np.concatenate(r_parts),
                np.concatenate(c_parts),
                np.concatenate(d_parts),
            )

        t_k0 = time.perf_counter()
        rows_chunks: list = []
        cols_chunks: list = []
        data_chunks: list = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit in index order; collect in the same order — deterministic triplets
            futures = [executor.submit(_sensor_row, i) for i in range(n_obs)]
            for fut in futures:
                r, c, d = fut.result()
                rows_chunks.append(r)
                cols_chunks.append(c)
                data_chunks.append(d)

        t_k1 = time.perf_counter()

        rows_arr = np.concatenate(rows_chunks) if rows_chunks else np.empty(0, np.int32)
        cols_arr = np.concatenate(cols_chunks) if cols_chunks else np.empty(0, np.int32)
        data_arr = np.concatenate(data_chunks) if data_chunks else np.empty(0, np.float64)

        G_active = sp.csr_matrix(
            (data_arr, (rows_arr, cols_arr)),
            shape=(n_obs, n_active),
            dtype=np.float64,
        )

        t_end = time.perf_counter()
        fill_rate = G_active.nnz / max(1, n_obs * n_active)

        print(
            f"[FORWARD HPC] G_active CSR: NNZ={G_active.nnz:,} | Fill={fill_rate:.4%} | "
            f"Sensores={n_obs:,} | ActiveCells={n_active:,} | Workers={max_workers} | "
            f"t_total={t_end-t_start:.2f}s "
            f"(query={t_q1-t_q0:.3f}s, kernel={t_k1-t_k0:.3f}s)"
        )

        if G_active.nnz == 0:
            raise ValueError(
                "El kernel G_active quedó vacío. "
                "Revisa cutoff_radius, coordenadas de sensores y active_cells."
            )

        # ── T3.3: guardar en caché (copias de las coords como clave; matriz como
        # valor read-only). Reemplaza la entrada previa (caché de UNA geometría).
        self._kernel_cache = (
            geom_key, x_c_act.copy(), y_c_act.copy(), z_c_act.copy(), sensor_coords.copy(),
        )
        self._kernel_cache_mat = G_active
        self.kernel_build_count += 1

        return G_active

    def _build_sparse_kernel_variable(
        self, x_c_act, y_c_act, z_c_act, sensor_coords,
        cell_dx, cell_dy, cell_dz,
    ):
        """
        SPRINT 3A — Kernel gravitacional para celdas de tamaño VARIABLE (TreeMesh).

        Misma física que la ruta uniforme (Nagy 1966 campo cercano + masa puntual
        campo lejano) pero con tamaño y volumen POR CELDA. La frontera near/far se
        decide por celda con su propio a_eq: una celda es campo cercano si
            r ≤ 4·a_eq_celda,   a_eq_celda = sqrt(dx²+dy²+dz²).
        Para celdas uniformes esto reproduce exactamente el split de la ruta escalar
        (pixel-perfect): todas las celdas dentro de 4·a_eq → Nagy; el resto → masa
        puntual; idéntico conjunto y valores que _build_sparse_kernel uniforme.

        No usa la caché de geometría (la caché está validada solo para la ruta
        uniforme; en 3A la malla adaptativa no está en el lazo caliente de producción).
        """
        n_active = len(x_c_act)
        n_obs = len(sensor_coords)

        # ── Validación + broadcast de tamaños por celda ──────────────────────
        def _as_cell_array(v, name):
            if v is None:
                # Si solo se dieron algunos ejes, completar con el escalar uniforme.
                return np.full(n_active, getattr(self, name), dtype=np.float64)
            arr = np.asarray(v, dtype=np.float64)
            if arr.ndim == 0:
                arr = np.full(n_active, float(arr), dtype=np.float64)
            if arr.shape[0] != n_active:
                raise ValueError(
                    f"{name} debe tener longitud n_active={n_active}, got {arr.shape[0]}."
                )
            return arr

        cdx = _as_cell_array(cell_dx, "dx")
        cdy = _as_cell_array(cell_dy, "dy")
        cdz = _as_cell_array(cell_dz, "dz")
        if not (np.isfinite(cdx).all() and np.isfinite(cdy).all() and np.isfinite(cdz).all()):
            raise ValueError("cell_dx/cell_dy/cell_dz contienen NaN o Inf.")
        if (cdx <= 0).any() or (cdy <= 0).any() or (cdz <= 0).any():
            raise ValueError("cell_dx/cell_dy/cell_dz deben ser positivos.")

        cell_vol = cdx * cdy * cdz                         # (n_active,)
        a_eq_cell = np.sqrt(cdx**2 + cdy**2 + cdz**2)      # (n_active,)
        near_thr_cell = 4.0 * a_eq_cell                    # frontera near/far por celda

        t_start = time.perf_counter()
        max_workers = max(1, (os.cpu_count() or 2) - 1)

        print(
            f"[FORWARD HPC/TreeMesh] KDTree variable-cell + ThreadPool({max_workers}w). "
            f"n_active={n_active:,} | n_obs={n_obs:,} | "
            f"cell_size∈[{cdx.min():.1f},{cdx.max():.1f}]m | cutoff={self.cutoff_radius:.0f}m"
        )

        voxel_centers = np.column_stack([x_c_act, y_c_act, z_c_act])
        tree = cKDTree(voxel_centers)
        cutoff_lists = tree.query_ball_point(sensor_coords, r=self.cutoff_radius)

        _x, _y, _z = x_c_act, y_c_act, z_c_act
        _G = self.G
        _nagy = self._nagy_prism_safe

        def _sensor_row(i):
            sx, sy, sz = sensor_coords[i]
            idx = np.asarray(cutoff_lists[i], dtype=np.int64)
            if len(idx) == 0:
                return (
                    np.empty(0, dtype=np.int32),
                    np.empty(0, dtype=np.int32),
                    np.empty(0, dtype=np.float64),
                )
            dxv = _x[idx] - sx
            dyv = _y[idx] - sy
            dzv = _z[idx] - sz
            r = np.sqrt(dxv**2 + dyv**2 + dzv**2)

            near = r <= near_thr_cell[idx]
            far = ~near

            r_parts, c_parts, d_parts = [], [], []
            if np.any(far):
                fidx = idx[far]
                r3 = (dxv[far]**2 + dyv[far]**2 + dzv[far]**2) ** 1.5
                r_parts.append(np.full(len(fidx), i, dtype=np.int32))
                c_parts.append(fidx.astype(np.int32))
                d_parts.append((_G * cell_vol[fidx] * 1000.0 * dyv[far]) / r3)
            if np.any(near):
                nidx = idx[near]
                r_parts.append(np.full(len(nidx), i, dtype=np.int32))
                c_parts.append(nidx.astype(np.int32))
                d_parts.append(_nagy(
                    dxv[near], dyv[near], dzv[near],
                    cdx[nidx], cdy[nidx], cdz[nidx], _G,
                ))
            return (
                np.concatenate(r_parts),
                np.concatenate(c_parts),
                np.concatenate(d_parts),
            )

        rows_chunks, cols_chunks, data_chunks = [], [], []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_sensor_row, i) for i in range(n_obs)]
            for fut in futures:
                r, c, d = fut.result()
                rows_chunks.append(r)
                cols_chunks.append(c)
                data_chunks.append(d)

        rows_arr = np.concatenate(rows_chunks) if rows_chunks else np.empty(0, np.int32)
        cols_arr = np.concatenate(cols_chunks) if cols_chunks else np.empty(0, np.int32)
        data_arr = np.concatenate(data_chunks) if data_chunks else np.empty(0, np.float64)

        G_active = sp.csr_matrix(
            (data_arr, (rows_arr, cols_arr)),
            shape=(n_obs, n_active),
            dtype=np.float64,
        )

        fill_rate = G_active.nnz / max(1, n_obs * n_active)
        print(
            f"[FORWARD HPC/TreeMesh] G_active CSR: NNZ={G_active.nnz:,} | "
            f"Fill={fill_rate:.4%} | t_total={time.perf_counter()-t_start:.2f}s"
        )

        if G_active.nnz == 0:
            raise ValueError(
                "El kernel G_active (TreeMesh) quedó vacío. "
                "Revisa cutoff_radius, sensores y centros de celda."
            )
        return G_active

    def build_kernel_from_treemesh(self, mesh, sensor_coords):
        """
        SPRINT 3A — API pública: construye el kernel gravitacional desde una TreeMesh.

        Extrae centros y tamaños por celda de la malla adaptativa y delega en la ruta
        de celdas variables. Retorna sp.csr_matrix shape=(n_sensors, mesh.n_cells).
        """
        centers = mesh.get_cell_centers()
        sizes = mesh.get_cell_sizes()
        sensor_coords = np.asarray(sensor_coords, dtype=np.float64)
        if not np.isfinite(centers).all():
            raise ValueError("Los centros de celda de la TreeMesh contienen NaN o Inf.")
        if not np.isfinite(sensor_coords).all():
            raise ValueError("Las coordenadas de sensores contienen NaN o Inf.")
        return self._build_sparse_kernel_variable(
            centers[:, 0], centers[:, 1], centers[:, 2], sensor_coords,
            sizes[:, 0], sizes[:, 1], sizes[:, 2],
        )

    def build_sparse_kernel(self, x_vox, y_vox, z_vox, sensor_coords):
        """
        API pública (backward compatible). Trata TODOS los vóxeles como activos.
        Delega internamente a _build_sparse_kernel (F0.2 KDTree + CSR triplets).
        Retorna kernel shape=(n_sensors, n_voxels) — misma firma que versiones anteriores.
        """
        print(f"[FORWARD] Construyendo Kernel Disperso CSR. Cutoff: {self.cutoff_radius} m")

        x_vox = np.asarray(x_vox, dtype=np.float64)
        y_vox = np.asarray(y_vox, dtype=np.float64)
        z_vox = np.asarray(z_vox, dtype=np.float64)
        sensor_coords = np.asarray(sensor_coords, dtype=np.float64)

        if len(x_vox) == 0:
            raise ValueError("No hay vóxeles para construir el kernel.")
        if len(sensor_coords) == 0:
            raise ValueError("No hay sensores para construir el kernel.")
        if not np.isfinite(x_vox).all() or not np.isfinite(y_vox).all() or not np.isfinite(z_vox).all():
            raise ValueError("Las coordenadas de vóxeles contienen NaN o Inf.")
        if not np.isfinite(sensor_coords).all():
            raise ValueError("Las coordenadas de sensores contienen NaN o Inf.")

        # Delegar a _build_sparse_kernel (F0.2): todos los vóxeles son "activos" aquí
        kernel_sparse = self._build_sparse_kernel(x_vox, y_vox, z_vox, sensor_coords)

        n_sensors = len(sensor_coords)
        n_voxels = len(x_vox)
        fill_rate = kernel_sparse.nnz / max(1, n_sensors * n_voxels)

        print(
            f"[FORWARD] Kernel CSR creado. "
            f"Sensores: {n_sensors:,} | Vóxeles: {n_voxels:,} | "
            f"NNZ: {kernel_sparse.nnz:,} | Fill rate: {fill_rate:.4%}"
        )

        return kernel_sparse


class GravimetryInversion:
    """
    INVERSE MODEL:
    Inversión gravimétrica con LSQR + regularización espacial tipo Tikhonov 3D.

    Convención de memoria:
    - TODO el backend usa order='F'
    - índice plano = ix + nx * iy + nx * ny * iz
    """

    def __init__(self, nx=100, ny=50, nz=100, block_size=10.0):
        self.nx = int(nx)
        self.ny = int(ny)
        self.nz = int(nz)
        self.dx = float(block_size)
        self.dy = float(block_size)
        self.dz = float(block_size)
        self.base_density = 2.6
        self.total_voxels = self.nx * self.ny * self.nz

        if self.nx <= 0 or self.ny <= 0 or self.nz <= 0:
            raise ValueError("nx, ny y nz deben ser mayores que 0.")

        if self.dx <= 0:
            raise ValueError("block_size debe ser mayor que 0.")

    def _build_laplacian(self, hx=None, hy=None, hz=None):
        """
        Laplaciano 3D puro (sin depth weighting) como CSR. Orden F.

        F0.9 — Malla No-Uniforme:
        Si hx/hy/hz se proveen (arrays 1D de anchos de celda del tensor mesh),
        cada arista (i, j) recibe un peso físicamente correcto:
            w_ij = 2 / (h_i + h_j)
        donde (h_i + h_j)/2 es la distancia real entre centros de celdas adyacentes.

        Con hx=hy=hz=None el comportamiento es uniforme (backward compatible).
        """
        print(
            "[INVERSIÓN] Construyendo Laplaciano 3D sin wrap-around. Orden F. "
            f"Malla {'no-uniforme (F0.9 Tensor Mesh)' if hx is not None else 'uniforme'}."
        )

        idx_grid = np.arange(self.total_voxels, dtype=np.int64).reshape(
            (self.nx, self.ny, self.nz),
            order="F"
        )

        row_parts  = []
        col_parts  = []
        data_parts = []

        def add_edges(a_idx, b_idx, weights):
            """Aristas bidireccionales con peso w_ij (simétrico)."""
            a = a_idx.ravel(order="F")
            b = b_idx.ravel(order="F")
            w = weights.ravel()
            row_parts.append(a);  col_parts.append(b);  data_parts.append(w)
            row_parts.append(b);  col_parts.append(a);  data_parts.append(w)

        # ── X direction ──────────────────────────────────────────────────────
        if self.nx > 1:
            if hx is not None:
                # w_ij = 1 / dist_centros = 2 / (hx[i] + hx[i+1])
                wx_1d = 2.0 / (hx[:-1] + hx[1:])              # (nx-1,)
                wx = np.broadcast_to(
                    wx_1d[:, np.newaxis, np.newaxis],
                    (self.nx - 1, self.ny, self.nz)
                ).copy()
            else:
                wx = np.ones((self.nx - 1, self.ny, self.nz), dtype=np.float64)
            add_edges(idx_grid[:-1, :, :], idx_grid[1:, :, :], wx)

        # ── Y direction ──────────────────────────────────────────────────────
        if self.ny > 1:
            if hy is not None:
                wy_1d = 2.0 / (hy[:-1] + hy[1:])              # (ny-1,)
                wy = np.broadcast_to(
                    wy_1d[np.newaxis, :, np.newaxis],
                    (self.nx, self.ny - 1, self.nz)
                ).copy()
            else:
                wy = np.ones((self.nx, self.ny - 1, self.nz), dtype=np.float64)
            add_edges(idx_grid[:, :-1, :], idx_grid[:, 1:, :], wy)

        # ── Z direction ──────────────────────────────────────────────────────
        if self.nz > 1:
            if hz is not None:
                wz_1d = 2.0 / (hz[:-1] + hz[1:])              # (nz-1,)
                wz = np.broadcast_to(
                    wz_1d[np.newaxis, np.newaxis, :],
                    (self.nx, self.ny, self.nz - 1)
                ).copy()
            else:
                wz = np.ones((self.nx, self.ny, self.nz - 1), dtype=np.float64)
            add_edges(idx_grid[:, :, :-1], idx_grid[:, :, 1:], wz)

        if not row_parts:
            raise ValueError("No se pudo construir regularizador espacial: grilla demasiado pequeña.")

        rows = np.concatenate(row_parts)
        cols = np.concatenate(col_parts)
        data = np.concatenate(data_parts)

        off_diag = sp.coo_matrix(
            (data, (rows, cols)),
            shape=(self.total_voxels, self.total_voxels)
        )

        diag_data = -np.asarray(off_diag.sum(axis=1)).ravel()
        diag_mat  = sp.diags(diag_data, 0, dtype=np.float64)

        L = (off_diag + diag_mat).tocsr()
        print(f"[INVERSIÓN] Laplaciano CSR creado. NNZ: {L.nnz:,}")
        return L

    def _build_spatial_regularizer(self, x_c=None, y_c=None, z_c=None):
        """
        Mantiene compatibilidad: Laplaciano uniforme + depth weighting sobre grilla completa.
        Si y_c es None (llamada sin args desde focusing.py), usa pesos uniformes
        — el módulo de focusing aplica su propio depth weighting vía _depth_weights().
        """
        L  = self._build_laplacian()     # siempre uniforme en esta ruta legado
        z0 = self.dy / 2.0
        if y_c is not None:
            w_depth = (np.asarray(y_c, dtype=np.float64) + z0) ** 2.0  # Li & Oldenburg 1998: β=2
            w_reg   = 1.0 / w_depth
            w_reg   = w_reg / np.mean(w_reg)
        else:
            w_reg = np.ones(self.total_voxels, dtype=np.float64)
        return sp.diags(w_reg) @ L

    def select_lambda_lcurve(
        self,
        g_observed,
        y_c,
        forward_model,
        sensor_coords,
        x_c,
        z_c,
        n_trials: int = 20,
        lambda_min: float = 1e-4,
        lambda_max: float = 1e2,
        alpha_spatial: float = 1.0,
        noise_floor: float = 0.02,
        noise_pct: float = 0.02,
        topography_elevations=None,
        hx=None, hy=None, hz=None,
    ) -> dict:
        """
        FASE 11 — L-Curve: Selección Automática de lambda_mag.

        Ejecuta n_trials soluciones LSQR con lambdas logarítmicamente espaciados
        entre lambda_min y lambda_max.  Para cada lambda mide:
          - ||d - G*m||₂  (misfit / fidelidad a datos)
          - ||L*m||₂       (roughness / regularización)

        El "corner" de la L-curve es el lambda que maximiza la curvatura
        (aproximación discreta: punto más alejado de la línea que une los extremos).

        Parameters
        ----------
        g_observed : array-like  — datos de gravedad observados
        y_c        : array-like  — profundidades de centros de vóxeles
        forward_model : GravimetryForward
        sensor_coords : ndarray shape=(n_obs, 3)
        x_c, z_c   : coordenadas horizontales de vóxeles
        n_trials    : número de lambdas a probar (default 5)
        lambda_min  : límite inferior del barrido
        lambda_max  : límite superior del barrido
        alpha_spatial, noise_floor, noise_pct : igual que solve_inversion_lsqr

        Returns
        -------
        dict con claves:
            lambda_selected  : float — lambda óptimo elegido
            selection_method : str   — siempre "L-Curve"
            trials           : list  — [{lambda, misfit_norm, roughness_norm}, ...]
            summary          : str   — línea para incluir en el reporte del run
        """
        import scipy.sparse as _sp

        g_observed = np.asarray(g_observed, dtype=np.float64)
        y_c        = np.asarray(y_c,        dtype=np.float64)

        # ── Máscara de celdas activas ─────────────────────────────────────────
        if topography_elevations is None:
            topo_depth = np.zeros(self.total_voxels, dtype=np.float64)
        else:
            topo_depth = np.asarray(topography_elevations, dtype=np.float64)

        voxel_top   = y_c - (self.dy / 2.0)
        active_cells = voxel_top >= topo_depth
        n_active     = int(np.sum(active_cells))

        if n_active == 0:
            raise ValueError("[L-Curve] No hay celdas activas. Revisa topografía y grilla.")

        x_c_arr = np.asarray(x_c, dtype=np.float64)
        z_c_arr = np.asarray(z_c, dtype=np.float64)
        y_c_active = y_c[active_cells]

        # ── Construir G_active UNA sola vez ──────────────────────────────────
        G_active = forward_model._build_sparse_kernel(
            x_c_arr[active_cells], y_c_active, z_c_arr[active_cells],
            np.asarray(sensor_coords, dtype=np.float64),
        )

        # ── Formal data weighting Wd — R-04: sigma adaptivo ──────────────────
        # Si el caller pasa valores distintos al default problemático, se respetan.
        if noise_floor == 0.02 and noise_pct == 0.02:
            sigma = _sigma_adaptive(g_observed)
        else:
            sigma = _sigma_parametric(g_observed, noise_floor, noise_pct)
        Wd    = _sp.diags(1.0 / sigma)
        G_w   = Wd @ G_active
        d_w   = Wd @ g_observed

        # ── Column scaling Ws ─────────────────────────────────────────────────
        col_norms = np.sqrt(G_w.power(2).sum(axis=0)).A1
        col_norms = np.maximum(col_norms, 1e-12)
        Ws        = _sp.diags(1.0 / col_norms)
        G_scaled  = G_w @ Ws

        # ── Laplaciano + depth weighting reducidos a celdas activas ───────────
        L_full   = self._build_laplacian(hx=hx, hy=hy, hz=hz)
        L_active = L_full.tocsr()[active_cells, :][:, active_cells]

        z0 = self.dy / 2.0
        true_depth = y_c_active - topo_depth[active_cells]
        true_depth = np.clip(true_depth, a_min=1.0, a_max=None)
        w_depth    = (true_depth + z0) ** 2.0   # Li & Oldenburg 1998: β=2 estándar industrial
        w_reg      = 1.0 / w_depth
        w_reg      = w_reg / np.mean(w_reg)
        W_m        = _sp.diags(w_reg) @ L_active
        L_scaled   = W_m @ Ws

        n_sensors      = len(g_observed)
        lambda_spatial = float(alpha_spatial) * (n_sensors / n_active)

        # ── H3 (causa J): trial consistente con solve_inversion_lsqr (tras H2) ──
        # solve penaliza la smallness con diag(lambda_mag·w_reg)·m (mismo depth
        # weighting que la suavidad). El trial de la L-curve debe usar la MISMA
        # regularización: bloque diag(lam·w_reg)·Ws con damp=0, no damp=lam uniforme.
        # La parte fija (datos + suavidad, no depende de lam) se construye una vez.
        _Ws_wreg = _sp.diags(w_reg) @ Ws         # diag(w_reg)·Ws (smallness sin lam)
        _G_fixed = _sp.vstack([G_scaled, lambda_spatial * L_scaled]).tocsr()
        _d_fixed = np.concatenate([d_w, np.zeros(n_active, dtype=np.float64)])

        # ── Barrido logarítmico de lambdas ────────────────────────────────────
        lambdas = np.logspace(
            np.log10(lambda_min), np.log10(lambda_max), num=n_trials
        )

        print(
            f"[L-CURVE] Barrido de {n_trials} lambdas: "
            f"{lambda_min:.2e} → {lambda_max:.2e}"
        )

        trials = []
        for lam in lambdas:
            G_aug = _sp.vstack([_G_fixed, float(lam) * _Ws_wreg]).tocsr()
            d_aug = np.concatenate([_d_fixed, np.zeros(n_active, dtype=np.float64)])

            res = lsqr(G_aug, d_aug, damp=0.0, iter_lim=150, show=False)
            m_tilde = res[0]
            m_phys  = Ws @ m_tilde

            # Misfit en espacio de datos originales
            g_pred       = G_active @ m_phys
            misfit_norm  = float(np.linalg.norm(g_observed - g_pred))

            # Roughness = seminorma del término que lam penaliza: ‖diag(w_reg)·m‖
            # (smallness depth-weighted). Antes se medía ‖L_active·m‖ (suavidad,
            # penalizada por lambda_spatial FIJO) — inconsistente con el parámetro
            # lam que se varía, de modo que la esquina elegía un λ no-óptimo.
            roughness_norm = float(np.linalg.norm(w_reg * m_phys))

            print(
                f"  lambda={lam:.2e} | misfit={misfit_norm:.4e} | roughness={roughness_norm:.4e}"
            )
            trials.append({
                "lambda":         float(lam),
                "misfit_norm":    misfit_norm,
                "roughness_norm": roughness_norm,
            })

        # ── Encontrar el "corner" de la L-curve ──────────────────────────────
        lm_arr = np.log10(np.array([t["misfit_norm"]    for t in trials]) + 1e-30)
        lr_arr = np.log10(np.array([t["roughness_norm"] for t in trials]) + 1e-30)

        def _perpendicular_corner(lm, lr):
            """Fallback: índice de máxima distancia perpendicular a la línea extremos."""
            p0 = np.array([lm[0],  lr[0]])
            p1 = np.array([lm[-1], lr[-1]])
            line_vec = p1 - p0
            line_len = np.linalg.norm(line_vec)
            if line_len < 1e-12:
                return len(lm) // 2
            distances = np.array([
                np.abs(np.cross(line_vec, np.array([lm[i], lr[i]]) - p0)) / line_len
                for i in range(len(lm))
            ])
            return int(np.argmax(distances))

        def _menger_corner(lm, lr):
            """
            Curvatura de Menger sobre tríos consecutivos en el plano log-log
            (Hansen 2010, método estándar para la esquina de la L-curve).

            Para tres puntos P_{i-1}, P_i, P_{i+1}:
                κ_i = 4·A / (|P_{i-1}P_i|·|P_iP_{i+1}|·|P_{i+1}P_{i-1}|)
            con A = área del triángulo. Es más robusta que la curvatura por
            diferencias finitas (np.gradient) cuando el espaciado en el eje de
            misfit es muy no-uniforme, caso en que la 2ª derivada discreta degenera.
            La esquina = punto interior de máxima κ.

            Los ejes se normalizan a [0,1] (la curvatura es sensible a la escala
            de cada eje) y se descartan tríos con algún lado despreciable: cuando
            el misfit apenas cambia, varios puntos quedan casi coincidentes y su
            κ es ruido numérico (denominador → 0). Esos tríos no representan una
            esquina real y deben ignorarse.
            """
            n = len(lm)
            if n < 3:
                return n // 2

            def _norm(v):
                v = np.asarray(v, dtype=np.float64)
                span = float(v.max() - v.min())
                return (v - v.min()) / span if span > 1e-30 else np.zeros_like(v)

            pts = np.column_stack([_norm(lm), _norm(lr)])
            min_seg = 1e-3   # lado mínimo (en ejes normalizados) para considerar un trío
            kappa = np.zeros(n, dtype=np.float64)
            for i in range(1, n - 1):
                a, b, c = pts[i - 1], pts[i], pts[i + 1]
                d_ab = np.linalg.norm(b - a)
                d_bc = np.linalg.norm(c - b)
                d_ca = np.linalg.norm(a - c)
                if min(d_ab, d_bc, d_ca) < min_seg:
                    continue
                denom = d_ab * d_bc * d_ca
                # 2·área con signo (producto cruz 2D); |·| = 2·A  ⇒  κ = 2|cross|/denom
                cross = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
                kappa[i] = 2.0 * abs(cross) / denom
            kappa = np.nan_to_num(kappa, nan=0.0, posinf=0.0, neginf=0.0)
            if not np.any(kappa > 0):
                return None
            return int(np.argmax(kappa))

        corner_idx = None
        if len(lr_arr) >= 3:
            try:
                corner_idx = _menger_corner(lm_arr, lr_arr)
                if corner_idx is not None:
                    logger.info(
                        f"L-curve selected lambda={trials[corner_idx]['lambda']:.6g} "
                        f"using Menger-curvature corner detection"
                    )
            except Exception as _exc:
                logger.info(f"L-curve Menger curvature failed ({_exc}); using fallback")
                corner_idx = None

        if corner_idx is None:
            corner_idx = _perpendicular_corner(lm_arr, lr_arr)
            logger.info(
                f"L-curve selected lambda={trials[corner_idx]['lambda']:.6g} "
                f"using perpendicular-distance fallback"
            )

        lambda_selected = trials[corner_idx]["lambda"]
        summary = (
            f"Lambda_mag: {lambda_selected:.2e} "
            f"(Seleccionado via L-Curve, {n_trials} pruebas, "
            f"rango {lambda_min:.0e}–{lambda_max:.0e})"
        )

        print(f"[L-CURVE] Lambda óptimo: {lambda_selected:.2e} (índice {corner_idx}/{n_trials-1})")
        print(f"[L-CURVE] {summary}")

        return {
            "lambda_selected":  lambda_selected,
            "selection_method": "L-Curve",
            "corner_index":     corner_idx,
            "n_trials":         n_trials,
            "trials":           trials,
            "summary":          summary,
        }

    def select_lambda_chi2_target(
        self,
        g_observed,
        y_c,
        forward_model,
        sensor_coords,
        x_c,
        z_c,
        lambda_candidates=None,
        chi2_target: float = 1.0,
        cond_max: float = 1e12,
        alpha_spatial: float = 1.0,
        topography_elevations=None,
        hx=None, hy=None, hz=None,
        padding_mask=None,
        padding_kappa: float = 1e5,
    ) -> dict:
        """
        R-A2 — Selección de lambda por target chi² (post-auditoría).

        Escanea lambda_candidates y selecciona el lambda que minimice
        |log10(chi²_final) - log10(chi2_target)| sujeto a cond(A) < cond_max.

        Candidatos por defecto (rango post-auditoría):
            [1e-3, 5e-4, 1e-4, 5e-5, 1e-5, 5e-6, 1e-6]

        Equivalente a la búsqueda por Discrepancy Principle de Morozov, pero
        usando el estimador de cond(A) de LSQR para la restricción de estabilidad.
        """
        import scipy.sparse as _sp

        if lambda_candidates is None:
            lambda_candidates = [1e-3, 5e-4, 1e-4, 5e-5, 1e-5, 5e-6, 1e-6]

        g_observed = np.asarray(g_observed, dtype=np.float64)
        y_c        = np.asarray(y_c,        dtype=np.float64)

        # ── Máscara de celdas activas ─────────────────────────────────────────
        if topography_elevations is None:
            topo_depth = np.zeros(self.total_voxels, dtype=np.float64)
        else:
            topo_depth = np.asarray(topography_elevations, dtype=np.float64)
        voxel_top    = y_c - (self.dy / 2.0)
        active_cells = voxel_top >= topo_depth
        n_active     = int(np.sum(active_cells))
        if n_active == 0:
            raise ValueError("[chi2-scan] No hay celdas activas.")

        n_sensors  = len(g_observed)
        x_c_arr    = np.asarray(x_c, dtype=np.float64)
        z_c_arr    = np.asarray(z_c, dtype=np.float64)
        y_c_active = y_c[active_cells]

        # ── Construir G_active UNA vez (se almacena en caché del forward) ─────
        G_active = forward_model._build_sparse_kernel(
            x_c_arr[active_cells], y_c_active, z_c_arr[active_cells],
            np.asarray(sensor_coords, dtype=np.float64),
        )

        # ── R-05: Observable Domain (mismo filtro que solve_inversion_lsqr) ──
        _col_sens_r05  = np.asarray(G_active.power(2).sum(axis=0)).ravel()
        _sens_thr_r05  = 1e-6 * max(float(np.max(_col_sens_r05)), 1e-30)
        _obs_in_active = _col_sens_r05 > _sens_thr_r05
        _n_obs_domain  = int(np.sum(_obs_in_active))
        _n_dead        = n_active - _n_obs_domain
        if _n_dead > 0:
            G_active    = G_active[:, _obs_in_active]
            y_c_active  = y_c_active[_obs_in_active]
            _topo_sol   = topo_depth[active_cells][_obs_in_active]
            _n_active_sol = _n_obs_domain
        else:
            _topo_sol     = topo_depth[active_cells]
            _n_active_sol = n_active

        # ── Data weighting — R-04 sigma adaptivo ─────────────────────────────
        sigma   = _sigma_adaptive(g_observed)
        Wd      = _sp.diags(1.0 / sigma)
        G_w     = Wd @ G_active
        d_w     = Wd @ g_observed

        # ── Column scaling ────────────────────────────────────────────────────
        col_norms = np.sqrt(G_w.power(2).sum(axis=0)).A1
        col_norms = np.maximum(col_norms, 1e-12)
        Ws        = _sp.diags(1.0 / col_norms)
        G_scaled  = G_w @ Ws

        # ── Laplaciano + depth weighting reducidos a activas/observables ──────
        L_full   = self._build_laplacian(hx=hx, hy=hy, hz=hz)
        L_active = L_full.tocsr()[active_cells, :][:, active_cells]
        if _n_dead > 0:
            L_active = L_active.tocsr()[_obs_in_active, :][:, _obs_in_active]
        z0           = self.dy / 2.0
        true_depth   = y_c_active - _topo_sol
        true_depth   = np.clip(true_depth, a_min=1.0, a_max=None)
        w_depth      = (true_depth + z0) ** 2.0
        w_reg        = 1.0 / w_depth
        w_reg        = w_reg / np.mean(w_reg)
        W_m          = _sp.diags(w_reg) @ L_active
        L_scaled     = W_m @ Ws

        lambda_spatial = float(alpha_spatial) * (n_sensors / n_active)
        G_aug = _sp.vstack([G_scaled, lambda_spatial * L_scaled]).tocsr()
        d_aug = np.concatenate([d_w, np.zeros(_n_active_sol, dtype=np.float64)])

        # ── Máscara de padding (para smallness diferencial) ───────────────────
        _padding_active = None
        if padding_mask is not None:
            _pm = np.asarray(padding_mask, dtype=bool)
            _padding_active = _pm[active_cells]
            if _n_dead > 0:
                _padding_active = _padding_active[_obs_in_active]

        print(
            f"[chi2-scan] Escaneando {len(lambda_candidates)} lambdas | "
            f"chi²_target={chi2_target:.1f} | cond_max={cond_max:.0e}"
        )

        # H3b (causa J): el trial debe usar la MISMA smallness depth-weighted que
        # solve_inversion_lsqr (tras H2): diag(lam·w_reg)·Ws con damp=0. Antes el
        # core usaba damp=lam (smallness uniforme) → el χ² del trial divergía ~700×
        # del χ² real del solve, invalidando la calibración por chi²-target.
        # padding conserva peso ABSOLUTO (padding_kappa·lam), no se relaja por prof.
        trials = []
        for lam in lambda_candidates:
            _w_sm = float(lam) * w_reg
            if _padding_active is not None:
                _w_sm = np.where(_padding_active, float(padding_kappa) * float(lam), _w_sm)
            _sb   = _sp.diags(_w_sm) @ Ws
            A_sys = _sp.vstack([G_aug, _sb]).tocsr()
            b_sys = np.concatenate([d_aug, np.zeros(_n_active_sol, dtype=np.float64)])
            res   = lsqr(A_sys, b_sys, damp=0.0,
                         iter_lim=500, atol=1e-8, btol=1e-8, show=False)

            m_tilde = res[0]
            acond   = float(res[6])
            m_phys  = Ws @ m_tilde
            residual = g_observed - G_active @ m_phys
            phi_d    = float(np.sum((residual / sigma) ** 2))
            chi2     = phi_d / n_sensors

            log_err  = abs(np.log10(max(chi2, 1e-30)) - np.log10(max(chi2_target, 1e-30)))
            feasible = bool(acond < cond_max)
            status   = "OK" if feasible else "COND_FAIL"
            print(
                f"  lambda={lam:.1e} | chi2={chi2:.4f} | cond(A)~{acond:.2e} | "
                f"|Dlog10(chi2)|={log_err:.4f} | {status}"
            )
            trials.append({
                "lambda":         float(lam),
                "chi2_final":     float(chi2),
                "cond_A":         float(acond),
                "log_chi2_error": float(log_err),
                "feasible":       feasible,
            })

        # ── Selección: minimizar |Δlog10(chi²)| entre lambdas factibles ───────
        feasible_trials = [t for t in trials if t["feasible"]]
        pool = feasible_trials if feasible_trials else trials
        if not feasible_trials:
            print(f"[chi2-scan] WARN: Ningun lambda con cond(A) < {cond_max:.0e}. Usando menor Dlog10.")
        best = min(pool, key=lambda t: t["log_chi2_error"])

        print(
            f"[chi2-scan] OK lambda_opt={best['lambda']:.2e} | "
            f"chi2={best['chi2_final']:.4f} | cond(A)~{best['cond_A']:.2e}"
        )
        return {
            "lambda_selected":  best["lambda"],
            "selection_method": "chi2_target",
            "chi2_target":      float(chi2_target),
            "chi2_achieved":    best["chi2_final"],
            "cond_A_achieved":  best["cond_A"],
            "cond_max":         float(cond_max),
            "feasible":         bool(best["feasible"]),
            "trials":           trials,
            "summary": (
                f"lambda={best['lambda']:.2e} | chi2={best['chi2_final']:.4f} | "
                f"cond(A)~{best['cond_A']:.2e} ({'OK' if best['feasible'] else 'COND_FAIL'})"
            ),
        }

    def solve_inversion_lsqr(
        self,
        g_observed,
        kernel_sparse,          # Caché del kernel disperso (joint mode). Si no-None: se usa como G_active.
        y_c,
        lambda_mag=1e-5,
        alpha_spatial=1.0,
        topography_elevations=None,
        sensor_coords=None,
        x_c=None,
        z_c=None,
        forward_model=None,
        # ── F0.9: Formal Data Weighting ──────────────────────────────────────
        noise_floor=0.02,       # Nivel de ruido absoluto (mismas unidades que g_observed)
        noise_pct=0.02,         # Fracción porcentual del ruido: 2% de |d_obs|
        # ── F0.9: Tensor Mesh — Laplaciano No-Uniforme ───────────────────────
        hx=None,                # Anchos 1D de celda en X (core + padding)
        hy=None,                # Anchos 1D de celda en Y
        hz=None,                # Anchos 1D de celda en Z
        # ── DOI: Modelo de Referencia (Li & Oldenburg 1999) ──────────────────
        m_ref: Optional[np.ndarray] = None,
        # ── Bound petrofísico EXPLÍCITO sobre la densidad recuperada (t/m³) ───
        # H-A0 Bug 3: density_max subido a 5.5 para cubrir magnetita (5.0-5.2),
        # cromita (4.5-4.8) y pirita masiva (4.5-5.0) — minerales objetivo en Chile.
        density_min: float = 2.6,
        density_max: float = 5.5,
        # ── R-02: Penalización diferencial de celdas de padding ──────────────
        # padding_mask: array bool (total_voxels,); True = celda de padding.
        # κ = 10^5 penaliza la smallness del padding 10^5 veces más que el core,
        # sin eliminar el grado de libertad (soft constraint). Ver auditoría R-A1.
        padding_mask: Optional[np.ndarray] = None,
        padding_kappa: float = 1e5,
        # ── FASE 8 (Q4): Anclaje por sondajes (boreholes) ────────────────────
        # boreholes: array (n,5) [x_m, z_m, y_from_m, y_to_m, density_t_m3] o None.
        # Soporta SOLO pozos verticales por ahora (intervalo en Y a (x,z) constante);
        # la arquitectura (mapeo por columna + segmento vertical) admite extensión
        # futura a polilíneas 3D. Para cada intervalo se ancla la densidad medida vía
        # strong soft constraint (smallness × anchor_kappa) + relajación local del
        # Laplaciano (filas × laplacian_relax_alpha) para mitigar halos/bullseyes.
        boreholes: Optional[np.ndarray] = None,
        anchor_kappa: float = 1e4,           # NO usar 1e6: destruiría cond(A)
        laplacian_relax_alpha: float = 0.2,
        # ── OUT: dict mutable donde el solver escribe diagnósticos numéricos ──
        # Si no es None, escribe: acond, chi2_final, n_sat_lower, n_sat_upper.
        solver_meta: Optional[dict] = None,
        # ── FASE 9C-1: Inversión Conjunta (cross-gradient) ───────────────────
        # extra_reg_blocks: lista de matrices sparse (k_i, n_modelo) en ESPACIO
        # FÍSICO del modelo activo; el motor las escala internamente con Ws y las
        # apila en G_aug. extra_reg_rhs: lista de vectores RHS (k_i,) por bloque
        # (None → ceros). prune_observable_domain=False desactiva la poda R-05
        # para que G conserve el tamaño completo de la malla activa y los bloques
        # externos (dimensionados a n_active) sean conformables.
        extra_reg_blocks: Optional[list] = None,
        extra_reg_rhs: Optional[list] = None,
        prune_observable_domain: bool = True,
        # ── AUDIT H-A4: β configurable para test de sensibilidad ─────────────
        depth_beta: float = 2.0,    # Li & Oldenburg: 2.0 = estándar industrial
    ):
        """
        LSQR + Tikhonov 3D. Motor HPC F0.2 EXCLUSIVO.

        Requiere forward_model, sensor_coords, x_c, z_c.
        La ruta legacy (column slicing kernel_sparse[:, active_cells]) ha sido eliminada.

        topography_elevations: array 1D de longitud total_voxels.
            Cada elemento es la coordenada Y (profundidad, positivo hacia abajo)
            de la superficie topográfica en la columna (x,z) del vóxel j.
            None → topografía plana en y=0 (todos los vóxeles son subsuperficie).

        m_ref: modelo de referencia opcional (contraste de densidad t/m³) para el
            funcional de regularización tipo Li & Oldenburg (1999). El término de
            modelo penaliza la rugosidad de (m - m_ref) en lugar de m. Se acepta de
            longitud total_voxels (grilla completa, se enmascara con active_cells) o
            de longitud n_active (ya reducido a celdas activas).
            m_ref is None → comportamiento idéntico al solver actual (RHS reg = 0).

        Devuelve una tupla (longitud total_voxels, NaN en celdas de aire):
            estimated_density_full : densidad recuperada (t/m³).
            relative_score_full    : score de ranking de objetivo [0,1]. NO es una
                                     probabilidad estadística (ver nota interna);
                                     la capa de servicio lo expone como
                                     `relative_target_score` (y `probability` legado).
            misfit_percent         : ‖d−Gm‖ / ‖d‖ × 100.
            normalized_sensitivity : proxy de sensibilidad (columna de G) normalizado.
        """
        print("[INVERSIÓN F0.2] Preparando solver LSQR + Tikhonov (Motor HPC Exclusivo).")

        g_observed = np.asarray(g_observed, dtype=np.float64)
        y_c = np.asarray(y_c, dtype=np.float64)

        # ── Validación F0.2: parámetros HPC requeridos ────────────────────────
        if forward_model is None or sensor_coords is None or x_c is None or z_c is None:
            raise ValueError(
                "Motor HPC F0.2 exclusivo: se requieren forward_model, sensor_coords, x_c, z_c. "
                "La ruta legacy (kernel_sparse[:, active_cells]) ha sido eliminada."
            )

        if not np.isfinite(g_observed).all():
            raise ValueError("g_observed contiene NaN o Inf.")
        if lambda_mag <= 0:
            raise ValueError("lambda_mag debe ser mayor que 0.")
        if alpha_spatial < 0:
            raise ValueError("alpha_spatial no puede ser negativo.")

        # ── Máscara de celdas activas (topografía F0.8) ───────────────────────
        if topography_elevations is None:
            # Topografía plana en y=0: todas las celdas son subsuperficie
            topo_depth = np.zeros(self.total_voxels, dtype=np.float64)
        else:
            topo_depth = np.asarray(topography_elevations, dtype=np.float64)
            if topo_depth.shape[0] != self.total_voxels:
                raise ValueError(
                    f"topography_elevations debe tener {self.total_voxels} elementos, "
                    f"got {topo_depth.shape[0]}."
                )

        # y positivo hacia abajo: TECHO del vóxel = y_center - dy/2
        # Activo = techo del vóxel está a la misma profundidad o por debajo de la superficie
        voxel_top = y_c - (self.dy / 2.0)
        active_cells = voxel_top >= topo_depth
        n_active = int(np.sum(active_cells))
        n_air = self.total_voxels - n_active

        if n_active == 0:
            raise ValueError(
                "Ningún vóxel activo bajo la topografía dada. "
                "Revisa topography_elevations y la grilla."
            )

        print(
            f"[INVERSIÓN F0.2] Active cells: {n_active:,} / {self.total_voxels:,} "
            f"({100.0 * n_active / self.total_voxels:.1f}% activo, "
            f"{n_air:,} celdas de aire enmascaradas)"
        )

        # ── R-02: Máscara de celdas de padding activas ───────────────────────
        _padding_active = None
        if padding_mask is not None:
            _pm = np.asarray(padding_mask, dtype=bool)
            if _pm.shape[0] != self.total_voxels:
                raise ValueError(
                    f"padding_mask debe tener longitud {self.total_voxels}, "
                    f"got {_pm.shape[0]}."
                )
            _padding_active = _pm[active_cells]   # shape=(n_active,)
            _n_pad_active  = int(np.sum(_padding_active))
            _n_core_active = n_active - _n_pad_active
            print(
                f"[R-02] Penalización diferencial padding: "
                f"core={_n_core_active:,} | padding={_n_pad_active:,} | kappa={padding_kappa:.0e}"
            )

        n_sensors = len(g_observed)
        y_c_active = y_c[active_cells]

        # ── F0.2 HPC: G_active directamente sobre celdas activas ─────────────
        # KDTree construido SOLO sobre celdas activas — sin fancy indexing global
        x_c_arr = np.asarray(x_c, dtype=np.float64)
        z_c_arr = np.asarray(z_c, dtype=np.float64)
        if kernel_sparse is not None:
            G_active = kernel_sparse
            print("[GRAV] Usando kernel cacheado (sin reconstrucción).")
        else:
            G_active = forward_model._build_sparse_kernel(
                x_c_arr[active_cells],
                y_c_active,
                z_c_arr[active_cells],
                np.asarray(sensor_coords, dtype=np.float64),
            )

        # ── FASE 8 (Q4): Mapeo de vóxeles anclados por sondaje (full → active) ─
        # Para cada intervalo se localiza la COLUMNA (x,z) cuyos centros caen dentro
        # de la huella del vóxel (tolerancia dx/2) y luego el SEGMENTO vertical cuyos
        # centros y_c ∈ [y_from, y_to]. Si el intervalo es más corto que dy (ningún
        # centro cae dentro), se selecciona el vóxel de la columna más cercano al punto
        # medio del intervalo (garantiza ≥1 vóxel anclado por intervalo válido).
        _anchor_active = None
        _anchor_contrast_active = None
        if boreholes is not None and len(boreholes) > 0:
            _bh = np.asarray(boreholes, dtype=np.float64)
            if _bh.ndim != 2 or _bh.shape[1] != 5:
                raise ValueError(
                    "boreholes debe tener shape (n,5): "
                    "[x_m, z_m, y_from_m, y_to_m, density_t_m3]."
                )
            _anchor_mask_full     = np.zeros(self.total_voxels, dtype=bool)
            _anchor_contrast_full = np.zeros(self.total_voxels, dtype=np.float64)
            _tol_xz = self.dx / 2.0
            for _bx, _bz, _yf, _yt, _brho in _bh:
                if _yt < _yf:
                    _yf, _yt = _yt, _yf
                _col = (np.abs(x_c_arr - _bx) <= _tol_xz) & (np.abs(z_c_arr - _bz) <= _tol_xz)
                if not np.any(_col):
                    continue
                _seg = _col & (y_c >= _yf) & (y_c <= _yt)
                if not np.any(_seg):
                    # Intervalo más corto que dy → vóxel de la columna más cercano al midpoint.
                    _ymid = 0.5 * (_yf + _yt)
                    _cidx = np.where(_col)[0]
                    _near = int(_cidx[int(np.argmin(np.abs(y_c[_cidx] - _ymid)))])
                    _seg = np.zeros(self.total_voxels, dtype=bool)
                    _seg[_near] = True
                _anchor_mask_full[_seg] = True
                _anchor_contrast_full[_seg] = float(_brho) - self.base_density
            _anchor_active          = _anchor_mask_full[active_cells]
            _anchor_contrast_active = _anchor_contrast_full[active_cells]

        # ── Solver Sanity Check ───────────────────────────────────────────────
        if G_active.nnz == 0:
            raise ValueError(
                "Kernel vacío. Ningún vóxel activo tiene sensibilidad a los sensores. "
                "Revisa el Bounding Box o la Topografía."
            )

        # ── R-05: Observable Domain — excluir vóxeles con sensibilidad cero ──
        # Vóxeles más allá del cutoff_radius para TODOS los sensores tienen columnas
        # cero en G_active. Incluirlos produce plateau de chi² por mínima norma y
        # saturación espuria en density_min (confirmado auditoría R-05).
        _col_sens_r05  = np.asarray(G_active.power(2).sum(axis=0)).ravel()
        _sens_thr_r05  = 1e-6 * max(float(np.max(_col_sens_r05)), 1e-30)
        if prune_observable_domain:
            _obs_in_active = _col_sens_r05 > _sens_thr_r05    # (n_active,)
        else:
            # FASE 9C-1: poda desactivada (inversión conjunta). Toda celda activa se
            # considera observable, de modo que el modelo conserva el tamaño completo
            # de la malla activa y los bloques cross-gradient (sized a n_active) conforman.
            _obs_in_active = np.ones(n_active, dtype=bool)
        _dead_in_active = ~_obs_in_active
        _n_obs_domain   = int(np.sum(_obs_in_active))
        _n_dead         = n_active - _n_obs_domain

        # Preservar máscara de padding COMPLETA para diagnóstico de saturación post-solver
        _padding_active_full = _padding_active.copy() if _padding_active is not None else None
        if _n_dead > 0:
            # Conteo de muertos por zona (para solver_meta)
            if _padding_active is not None:
                _n_dead_core_a = int(np.sum(_dead_in_active & ~_padding_active))
                _n_dead_pad_a  = int(np.sum(_dead_in_active &  _padding_active))
            else:
                _n_dead_core_a = _n_dead
                _n_dead_pad_a  = 0
            print(
                f"[R-05] Observable Domain: {_n_obs_domain:,}/{n_active:,} "
                f"({100.0*_n_obs_domain/n_active:.1f}%) | "
                f"Muertos (sens=0): {_n_dead:,} ({100.0*_n_dead/n_active:.1f}%) -> excluidos del solver"
            )
            G_active        = G_active[:, _obs_in_active]
            y_c_active      = y_c_active[_obs_in_active]
            _topo_sol       = topo_depth[active_cells][_obs_in_active]
            if _padding_active is not None:
                _padding_active = _padding_active[_obs_in_active]
            if _anchor_active is not None:
                _anchor_active          = _anchor_active[_obs_in_active]
                _anchor_contrast_active = _anchor_contrast_active[_obs_in_active]
            _n_active_sol   = _n_obs_domain
        else:
            _n_dead_core_a  = 0
            _n_dead_pad_a   = 0
            _topo_sol       = topo_depth[active_cells]
            _n_active_sol   = n_active

        # FASE 8: ¿hay vóxeles anclados observables tras las reducciones?
        _has_anchors = _anchor_active is not None and bool(np.any(_anchor_active))
        if _has_anchors:
            print(
                f"[FASE 8] Anclaje sondajes: {int(np.sum(_anchor_active)):,} voxeles | "
                f"kappa={anchor_kappa:.0e} | lap_relax={laplacian_relax_alpha}"
            )

        # ── Formal Data Weighting Wd — R-04: Sigma Adaptivo ─────────────────
        # noise_floor=0.02 en SI (m/s²) ≈ 2000 mGal >> señal típica (0.001–0.1 mGal).
        # Se reemplaza por sigma_i = max(0.02·|d_i|, 0.01·data_range) — invariante
        # de escala, basado en Li & Oldenburg 1998 / SimPEG noise_floor+relative_error.
        # Se respetan valores explícitos del caller (benchmark, L-curve) para backward compat.
        if noise_floor == 0.02 and noise_pct == 0.02:
            sigma = _sigma_adaptive(g_observed)
        else:
            sigma = _sigma_parametric(g_observed, noise_floor, noise_pct)
        Wd    = sp.diags(1.0 / sigma)
        G_w   = Wd @ G_active
        d_w   = Wd @ g_observed

        # ── Sensitivity DOI proxy (solo celdas observables) ─────────────────
        _sensitivity_obs = np.sqrt(G_w.power(2).sum(axis=0)).A1   # shape (_n_active_sol,)
        max_sens = float(np.max(_sensitivity_obs)) if len(_sensitivity_obs) > 0 else 0.0
        _norm_sens_obs = _sensitivity_obs / max_sens if max_sens > 0 else np.zeros_like(_sensitivity_obs)
        if _n_dead > 0:
            sensitivity_active = np.zeros(n_active, dtype=np.float64)
            sensitivity_active[_obs_in_active] = _sensitivity_obs
            normalized_sensitivity_active = np.zeros(n_active, dtype=np.float64)
            normalized_sensitivity_active[_obs_in_active] = _norm_sens_obs
        else:
            sensitivity_active = _sensitivity_obs
            normalized_sensitivity_active = _norm_sens_obs

        # ── Laplaciano no-uniforme reducido a celdas activas — F0.9 ──────────
        # Si hx/hy/hz provienen del tensor mesh, los pesos reales de arista
        # se propagan al Laplaciano, disipando correctamente en el padding.
        L_full   = self._build_laplacian(hx=hx, hy=hy, hz=hz)
        L_active = L_full.tocsr()[active_cells, :][:, active_cells]
        if _n_dead > 0:
            L_active = L_active.tocsr()[_obs_in_active, :][:, _obs_in_active]

        # ── FASE 8: relajación local del Laplaciano en vóxeles anclados ───────
        # Escalar las FILAS de los vóxeles anclados por alpha (<1) reduce el
        # acoplamiento de suavidad que imponen sobre sus vecinos, mitigando halos /
        # bullseyes; el valor del sondaje queda fijado por el strong soft constraint
        # (smallness × kappa), no por el suavizado. row-scaling diagonal: diag(s)·L
        # conserva la estructura CSR y no altera cond(A) materialmente.
        if _has_anchors:
            _lap_row_scale = np.ones(_n_active_sol, dtype=np.float64)
            _lap_row_scale[_anchor_active] = float(laplacian_relax_alpha)
            L_active = (sp.diags(_lap_row_scale) @ L_active).tocsr()

        # ── H-A0 Bug 1: W_z formal (Li & Oldenburg 1998) — cambio de variable ─
        # Reemplaza column scaling (Ws) + depth weighting separado (w_reg).
        # Wz_inv = diag((depth+z0)^{+β/2}) aplica simétricamente en datos
        # Y regularización → elimina la doble compensación de profundidad.
        # Referencia: test sintético 2026-06-07, pico a 775m vs 400m real (FAIL).
        z0 = self.dy / 2.0
        true_depth = y_c_active - _topo_sol
        true_depth = np.clip(true_depth, a_min=1.0, a_max=None)

        wz_inv_diag = (true_depth + z0) ** (0.5 * float(depth_beta))
        wz_inv_diag = wz_inv_diag / np.mean(wz_inv_diag)   # escala global ~1
        Wz_inv = sp.diags(wz_inv_diag)

        # Bounds en espacio m_tilde: density = base_density + Wz_inv @ m_tilde
        _lb_tilde = (float(density_min) - self.base_density) / np.maximum(wz_inv_diag, 1e-12)
        _ub_tilde = (float(density_max) - self.base_density) / np.maximum(wz_inv_diag, 1e-12)

        G_scaled = G_w @ Wz_inv
        L_scaled = L_active @ Wz_inv

        # ── Column normalization sobre W_z (Li & Oldenburg 1998, combinado) ──
        # Sin normalización, las columnas de G_w@Wz_inv tienen magnitudes SI
        # gravedad (~1e-2 después de Wd), haciendo que lambda=3.0 domine los
        # datos ~14 000×. W_col lleva las columnas a norma unitaria, preservando
        # la calibración N_CALIB=256 del operating point fijo.
        # Cambio de variable combinado: m = Wz_inv_orig @ W_col @ m_tilde.
        _col_norms_wz = np.sqrt(G_scaled.power(2).sum(axis=0)).A1
        _col_norms_wz = np.maximum(_col_norms_wz, 1e-12)
        _W_col        = sp.diags(1.0 / _col_norms_wz)
        G_scaled  = G_scaled @ _W_col
        L_scaled  = L_scaled @ _W_col
        _lb_tilde = _lb_tilde * _col_norms_wz   # bounds en nuevo m_tilde
        _ub_tilde = _ub_tilde * _col_norms_wz
        Wz_inv    = Wz_inv @ _W_col             # m = Wz_inv_combined @ m_tilde

        # ── Sistema augmentado ────────────────────────────────────────────────
        lambda_spatial = float(alpha_spatial) * (n_sensors / n_active)

        # ── Modelo de referencia m_ref (Li & Oldenburg 1999) ──────────────────
        # L_scaled = L_active @ Wz_inv; m = Wz_inv @ m_tilde.
        # Residual de regularización: λ_spatial · L_active · (m − m_ref).
        # RHS de las filas de regularización: λ_spatial · L_active · m_ref.
        # m_ref is None → d_reg = 0 → idéntico al solver sin referencia.
        # m_ref_sol vive en espacio observable (densidad contraste).
        if m_ref is None:
            m_ref_sol = None
        else:
            m_ref = np.asarray(m_ref, dtype=np.float64)
            if m_ref.shape[0] == self.total_voxels:
                m_ref_active = m_ref[active_cells]
            elif m_ref.shape[0] == n_active:
                m_ref_active = m_ref
            else:
                raise ValueError(
                    f"m_ref debe tener longitud {self.total_voxels} (grilla completa) "
                    f"o {n_active} (celdas activas), got {m_ref.shape[0]}."
                )
            if _n_dead > 0:
                m_ref_active = m_ref_active[_obs_in_active]
            if not np.isfinite(m_ref_active).all():
                raise ValueError("m_ref contiene NaN o Inf.")
            m_ref_sol = m_ref_active

        # FASE 8: inyectar anclajes de sondaje en la referencia (override por celda).
        #   m_ref[j] = densidad_sondaje - base_density  para los vóxeles anclados.
        # Esto desplaza el RHS de la regularización (suavidad) hacia el valor del
        # sondaje; el smallness con κ (abajo) lo fija con fuerza.
        if _has_anchors:
            if m_ref_sol is None:
                m_ref_sol = np.zeros(_n_active_sol, dtype=np.float64)
            else:
                m_ref_sol = m_ref_sol.copy()
            m_ref_sol[_anchor_active] = _anchor_contrast_active[_anchor_active]

        if m_ref_sol is None:
            d_reg = np.zeros(_n_active_sol, dtype=np.float64)
        else:
            d_reg = lambda_spatial * (L_active @ m_ref_sol)

        G_aug = sp.vstack([G_scaled, lambda_spatial * L_scaled]).tocsr()
        d_aug = np.concatenate([d_w, d_reg])

        # ── FASE 9C-1: inyección de regularización externa (cross-gradient) ───
        # Los bloques llegan en ESPACIO FÍSICO del modelo (m); el solver trabaja en
        # la variable escalada m_tilde con m = Wz_inv·m_tilde, de modo que cada bloque B
        # se convierte vía B·Wz_inv (igual que L_scaled = L_active·Wz_inv). El RHS se apila tal
        # cual (vive en el espacio de residual del bloque). Requiere
        # prune_observable_domain=False para que las columnas (n_active) conformen.
        if extra_reg_blocks:
            _xg_mats = [G_aug]
            _xg_rhs  = [d_aug]
            for _bi, _blk in enumerate(extra_reg_blocks):
                _blk = sp.csr_matrix(_blk)
                if _blk.shape[1] != Wz_inv.shape[0]:
                    raise ValueError(
                        f"extra_reg_blocks[{_bi}] tiene {_blk.shape[1]} columnas; "
                        f"se esperaban {Wz_inv.shape[0]} (modelo activo). "
                        f"¿Olvidaste prune_observable_domain=False?"
                    )
                _xg_mats.append(_blk @ Wz_inv)
                if extra_reg_rhs is not None and _bi < len(extra_reg_rhs):
                    _xg_rhs.append(np.asarray(extra_reg_rhs[_bi], dtype=np.float64).ravel())
                else:
                    _xg_rhs.append(np.zeros(_blk.shape[0], dtype=np.float64))
            G_aug = sp.vstack(_xg_mats).tocsr()
            d_aug = np.concatenate(_xg_rhs)
            print(f"[FASE 9C-1] Inyectados {len(extra_reg_blocks)} bloque(s) cross-gradient en G_aug.")

        # H-A0 Bug 2: lambda scaling con n_active (calibrado a N_CALIB=256).
        # Con Wz_inv la smallness es uniforme en m_tilde; solo se escala la magnitud.
        _N_CALIB = 256
        lambda_mag_eff = float(lambda_mag) * np.sqrt(float(_n_active_sol) / _N_CALIB)

        print(
            f"[INVERSIÓN F0.2] Ejecutando LSQR (H-A0: W_z formal). "
            f"lambda_mag={lambda_mag:.2e} | lambda_mag_eff={lambda_mag_eff:.2e} "
            f"| lambda_spatial={lambda_spatial:.2e} | depth_beta={depth_beta}"
        )

        # ── Regularización compuesta (objetivo de modelo Li & Oldenburg 1998) ─
        #   φ_m = ‖ lambda_spatial · L_active · Wz_inv · (m_tilde − m_ref_tilde) ‖²   (suavidad)
        #       + ‖ diag(lambda_mag_eff) · m_tilde ‖²   (smallness en espacio transformado)
        # El depth weighting vive en Wz_inv (cambio de variable); el bloque smallness
        # es identidad en m_tilde para no reintroducir doble compensación.
        # padding (R-02) y anclajes (FASE 8) usan RHS en espacio m_tilde.
        _w_small = np.full(_n_active_sol, lambda_mag_eff, dtype=np.float64)
        if _padding_active is not None:
            _w_small = np.where(
                _padding_active,
                float(padding_kappa) * lambda_mag_eff,
                _w_small,
            )
        if _has_anchors:
            _w_small = np.where(
                _anchor_active,
                float(anchor_kappa) * lambda_mag_eff,
                _w_small,
            )
        _small_block = sp.diags(_w_small)   # identidad en m_tilde (no Wz_inv)
        # RHS de smallness: 0 (core/padding → hacia base_density) excepto celdas
        # ancladas, que apuntan al contraste medido del sondaje. El residual de la
        # fila i es w_i·(contraste_i − target_i), por lo que d_small_i = w_i·target_i.
        _small_target = np.zeros(_n_active_sol, dtype=np.float64)
        if _has_anchors:
            _small_target[_anchor_active] = _anchor_contrast_active[_anchor_active]
        _d_small   = _w_small * _small_target
        _G_aug_sm  = sp.vstack([G_aug, _small_block]).tocsr()
        _d_aug_sm  = np.concatenate([d_aug, _d_small])

        from core.config import USE_BOUNDED_SOLVER as _USE_BC
        from core.config import USE_LSMR_LARGE as _USE_LSMR, LSMR_THRESHOLD_N_ACTIVE as _LSMR_THRESH
        # Benchmark empírico (2026-06-01): TRF+LSMR ~40s con NNZ≈213K y n_active≈14K;
        # LSQR <0.1s. Umbral 8000 (HITO 5): demo (~800), medium CSV (~5K) y DOI test
        # (~5K) usan TRF bounded; auto_grid (>8K) usa LSQR+clip como fallback.
        # Fase 10: LSMR para n_active > 50K (mejor convergencia en sistemas mal condicionados).
        _use_trf = _USE_BC and _n_active_sol <= 8_000
        _use_lsmr = (not _use_trf) and _USE_LSMR and (_n_active_sol > _LSMR_THRESH)
        if _use_trf:
            _solver_label = "TRF/bounded"
        elif _use_lsmr:
            _solver_label = f"LSMR (Fase10, n>{_LSMR_THRESH:,})"
        else:
            _solver_label = "LSQR+clip"
        print(
            f"[SOLVER] G_aug=({_G_aug_sm.shape[0]:,}×{_G_aug_sm.shape[1]:,}) "
            f"n_active_sol={_n_active_sol:,} NNZ={_G_aug_sm.nnz:,} "
            f"smallness=W_z-formal(H-A0) lambda_eff={lambda_mag_eff:.2e} "
            f"-> {_solver_label}"
        )
        _t_solve = time.perf_counter()
        if _use_trf:
            from scipy.optimize import lsq_linear as _lsq_linear
            _bc = _lsq_linear(
                _G_aug_sm, _d_aug_sm,
                bounds=(_lb_tilde, _ub_tilde),
                method='trf', lsq_solver='lsmr', tol=1e-6, max_iter=300,
            )
            m_tilde = _bc.x
            _acond = float('nan')
            print(f"[SOLVER] TRF finalizado en {time.perf_counter()-_t_solve:.1f}s.")
        else:
            from core.config import USE_SPARSE_DIRECT as _USE_SPARSE
            if _USE_SPARSE:
                # SPRINT 5A: solver DIRECTO (SuperLU sobre ecuaciones normales).
                # Misma estrategia de bounds que LSQR+clip: solución sin bounds y
                # luego clip al box petrofísico. Reemplaza SOLO el path n>8000;
                # el path TRF bounded (n≤8000) queda intacto.
                m_tilde_raw, _sp_info = solve_sparse_normal_equations(
                    _G_aug_sm, _d_aug_sm
                )
                m_tilde = np.clip(m_tilde_raw, _lb_tilde, _ub_tilde)
                _acond = float('nan')   # SuperLU no expone estimador de cond(A)
                print(
                    f"[SOLVER] SuperLU directo (ecuaciones normales) en "
                    f"{time.perf_counter()-_t_solve:.1f}s. "
                    f"residual={_sp_info['residual_norm']:.3e} "
                    f"fill_nnz={_sp_info['fill_nnz']:,}"
                )
            elif _use_lsmr:
                # Fase 10: LSMR para n_active > 50K.
                # Fong & Saunders (2011): residuo ||r|| monotónicamente decreciente,
                # mejor estabilidad numérica que LSQR para sistemas mal condicionados.
                # NO forma A^T A explícitamente (lección Sprint 5A).
                from exploration.solver_preconditioned import solve_inversion_lsmr as _lsmr_solve
                m_tilde, _acond = _lsmr_solve(
                    _G_aug_sm, _d_aug_sm, _lb_tilde, _ub_tilde,
                    maxiter=1000, tol=1e-8,
                )
                print(
                    f"[SOLVER] LSMR (Fase 10) convergido en "
                    f"{time.perf_counter()-_t_solve:.1f}s. "
                    f"cond(A)~{_acond:.2e}"
                )
            else:
                result = lsqr(
                    _G_aug_sm, _d_aug_sm,
                    damp=0.0,
                    iter_lim=500, atol=1e-8, btol=1e-8, show=False,
                )
                m_tilde = np.clip(result[0], _lb_tilde, _ub_tilde)
                _acond = result[6]
                print(
                    f"[SOLVER] LSQR convergido en {time.perf_counter()-_t_solve:.1f}s. "
                    f"cond(A)~{_acond:.2e}"
                )

            # ── Tier 1 A1: FISTA proyectado (bounds reales para n>8K) ─────────
            # El clip post-hoc descarta masa fuera del box sin redistribuir
            # (misfit degradado ~35% en cuerpos compactos). FISTA parte del
            # clip como warm start → el objetivo solo puede mejorar; rollback
            # exacto con USE_PROJECTED_SOLVER=false.
            from core.config import USE_PROJECTED_SOLVER as _USE_PGD
            if _USE_PGD:
                from exploration.solver_preconditioned import solve_inversion_pgd_fista
                _t_pgd = time.perf_counter()
                m_tilde, _pgd_info = solve_inversion_pgd_fista(
                    _G_aug_sm, _d_aug_sm, _lb_tilde, _ub_tilde, x0=m_tilde,
                )
                print(
                    f"[SOLVER] FISTA proyectado en {time.perf_counter()-_t_pgd:.1f}s "
                    f"(post-{'LSMR' if _use_lsmr else 'LSQR'}+warm-start)."
                )
                if solver_meta is not None:
                    solver_meta["pgd"] = _pgd_info
        if np.isfinite(_acond) and _acond > 1e12:
            print(
                f"[SOLVER] WARN cond(A)={_acond:.2e} > 1e12. "
                f"Revisar padding_kappa={padding_kappa:.0e}, anchor_kappa={anchor_kappa:.0e} "
                f"o lambda_mag={lambda_mag:.2e}."
            )

        density_contrast_active = Wz_inv @ m_tilde

        if len(density_contrast_active) != _n_active_sol:
            raise RuntimeError("LSQR devolvió un vector de densidad activo con tamaño incorrecto.")
        if not np.isfinite(density_contrast_active).all():
            raise RuntimeError("LSQR devolvió densidades no finitas.")

        # R-05: expandir contraste desde espacio observable al espacio activo completo.
        # Vóxeles muertos reciben contraste=0 → density=base_density (no D_min por bound).
        if _n_dead > 0:
            _contrast_sol = density_contrast_active
            density_contrast_active = np.zeros(n_active, dtype=np.float64)
            density_contrast_active[_obs_in_active] = _contrast_sol

        # ── Reconstrucción física: NaN para celdas de aire ────────────────────
        # Bound petrofísico EXPLÍCITO [density_min, density_max]. Diagnóstico de
        # saturación: si una fracción alta de celdas toca el bound, el dato "quería"
        # salir del rango y la restricción está enmascarando contraste real → señal
        # de que el bound debe revisarse para el depósito en cuestión (no es silencioso).
        density_raw = self.base_density + density_contrast_active
        _sat_lower_active = density_raw < density_min
        _sat_upper_active = density_raw > density_max
        n_sat_lower = int(np.sum(_sat_lower_active))
        n_sat_upper = int(np.sum(_sat_upper_active))
        n_clipped = n_sat_lower + n_sat_upper
        clip_fraction = n_clipped / max(1, n_active)
        estimated_density_full = np.full(self.total_voxels, np.nan, dtype=np.float64)
        estimated_density_full[active_cells] = np.clip(density_raw, density_min, density_max)
        if clip_fraction > 0.0:
            print(
                f"[INVERSION F0.2] Bound petrofisico [{density_min:.2f}, {density_max:.2f}] t/m3: "
                f"{n_clipped:,}/{n_active:,} saturadas (low={n_sat_lower} high={n_sat_upper}) "
                f"= {clip_fraction:.1%}."
                + (" WARN alta saturacion: revisar lambda/kappa." if clip_fraction > 0.10 else "")
            )

        normalized_sensitivity = np.full(self.total_voxels, np.nan, dtype=np.float64)
        normalized_sensitivity[active_cells] = normalized_sensitivity_active

        # ── Misfit (F0.2: G_active cubre solo celdas observables) ────────────
        # Usar [_obs_in_active] garantiza shapes consistentes cuando n_dead > 0:
        # G_active es (n_obs, _n_obs_domain); density_contrast_active es (n_active,).
        g_model = G_active @ density_contrast_active[_obs_in_active]
        residual_sensor = g_observed - g_model
        _voxel_err_obs = np.abs(G_active.T @ residual_sensor)   # shape (_n_obs_domain,)
        if _n_dead > 0:
            voxel_error_active = np.zeros(n_active, dtype=np.float64)
            voxel_error_active[_obs_in_active] = _voxel_err_obs
        else:
            voxel_error_active = _voxel_err_obs

        residual_error = float(np.linalg.norm(residual_sensor))
        observed_norm = float(np.linalg.norm(g_observed))
        if observed_norm <= 0 or not np.isfinite(observed_norm):
            # Datos degenerados (vacíos o planos): reportar NaN en vez de fingir ajuste perfecto.
            misfit_percent = float("nan")
        else:
            misfit_percent = float((residual_error / observed_norm) * 100.0)

        # ── Score relativo de objetivo por vóxel (solo celdas activas) ────────
        # ADVERTENCIA: esto NO es una probabilidad estadística. Es un score de
        # ranking normalizado [0,1] derivado del residual proyectado al modelo:
        #     score_j = 1 − |Gᵀ·residual|_j / max_j |Gᵀ·residual|
        # Mide cuán bien explicado queda cada vóxel por el ajuste, relativo al peor
        # vóxel; sirve para ordenar objetivos, no para afirmar confianza estadística.
        # La incertidumbre estadística real (posterior) es el upgrade de la Fase 3
        # (estimador de Hutchinson). El segundo elemento del retorno se mapea en la
        # capa de servicio tanto a `relative_target_score` (canónico) como a
        # `probability` (clave legada, conservada por compatibilidad de front-end).
        max_voxel_error = float(np.max(voxel_error_active)) if n_active > 0 else 0.0

        relative_score_full = np.full(self.total_voxels, np.nan, dtype=np.float64)
        if max_voxel_error <= 0 or not np.isfinite(max_voxel_error):
            # Datos degenerados: NaN en vez de score=1.0 que finge calidad máxima.
            relative_score_full[active_cells] = np.nan
        else:
            relative_active = 1.0 - (voxel_error_active / max_voxel_error)
            relative_score_full[active_cells] = np.clip(relative_active, 0.0, 1.0)

        # ── chi² reducido final ────────────────────────────────────────────────
        _sigma_diag = _sigma_adaptive(g_observed) if (noise_floor == 0.02 and noise_pct == 0.02) \
            else _sigma_parametric(g_observed, noise_floor, noise_pct)
        _phi_d = float(np.sum((residual_sensor / _sigma_diag) ** 2))
        _chi2_final = _phi_d / max(len(g_observed), 1)

        print(
            f"[INVERSION F0.2] Convergencia alcanzada. "
            f"Error residual L2: {residual_error:.4e} | Misfit: {misfit_percent:.2f}% | "
            f"chi2_final={_chi2_final:.4f} | cond(A)~{_acond:.2e}"
        )

        # ── Exponer diagnósticos numéricos al caller vía solver_meta ──────────
        if solver_meta is not None:
            solver_meta["acond"]         = float(_acond)
            solver_meta["chi2_final"]    = float(_chi2_final)
            solver_meta["n_sat_lower"]   = n_sat_lower
            solver_meta["n_sat_upper"]   = n_sat_upper
            solver_meta["n_sat_total"]   = n_clipped
            solver_meta["n_active"]      = n_active
            solver_meta["sat_fraction"]  = float(clip_fraction)
            solver_meta["density_min"]   = float(density_min)
            solver_meta["density_max"]   = float(density_max)
            # R-05: campos de dominio observable (para diagnóstico en el servicio)
            solver_meta["n_dead_voxels"]      = _n_dead
            solver_meta["n_dead_core_active"] = _n_dead_core_a
            solver_meta["n_dead_pad_active"]  = _n_dead_pad_a
            solver_meta["n_observable"]       = _n_obs_domain
            solver_meta["observable_ratio"]   = round(float(_n_obs_domain) / max(n_active, 1), 4)
            # Si padding_mask está activo, desglosar saturación por core/padding
            # Usa _padding_active_full (n_active) en lugar de _padding_active (n_active_sol)
            if _padding_active_full is not None:
                solver_meta["n_sat_lower_core"] = int(np.sum(_sat_lower_active & ~_padding_active_full))
                solver_meta["n_sat_lower_pad"]  = int(np.sum(_sat_lower_active & _padding_active_full))
                solver_meta["n_sat_upper_core"] = int(np.sum(_sat_upper_active & ~_padding_active_full))
                solver_meta["n_sat_upper_pad"]  = int(np.sum(_sat_upper_active & _padding_active_full))
            # FASE 8: anclajes de sondaje aplicados
            solver_meta["n_anchored_voxels"]    = int(np.sum(_anchor_active)) if _anchor_active is not None else 0
            solver_meta["anchor_kappa"]         = float(anchor_kappa) if _has_anchors else None
            solver_meta["laplacian_relax_alpha"] = float(laplacian_relax_alpha) if _has_anchors else None
            solver_meta["lambda_effective"]      = float(lambda_mag_eff)
            # H-C1: datos observed vs calculated para persistir en obs_vs_calc.parquet
            solver_meta["d_obs"]          = g_observed
            solver_meta["d_pred"]         = g_model
            solver_meta["residuals"]      = residual_sensor
            solver_meta["rmse"]           = float(np.sqrt(np.mean(residual_sensor ** 2)))
            solver_meta["station_coords"] = sensor_coords  # (n_sensors, 3) or None

        return estimated_density_full, relative_score_full, misfit_percent, normalized_sensitivity

    def estimate_posterior_std(
        self,
        g_observed,
        y_c,
        forward_model,
        sensor_coords,
        x_c,
        z_c,
        lambda_mag=1e-5,
        alpha_spatial=1.0,
        topography_elevations=None,
        noise_floor=0.02,
        noise_pct=0.02,
        hx=None, hy=None, hz=None,
        n_probes: int = 32,
        cg_maxiter: int = 300,
        cg_rtol: float = 1e-6,
        seed: int = 0,
    ):
        """
        FASE 3 (Track 3) — Incertidumbre posterior por vóxel (estimador de Hutchinson).

        Bajo el modelo lineal gaussiano del problema inverso regularizado, la matriz
        de covarianza posterior del contraste de densidad (en el espacio escalado por
        columnas, m = Ws·m_tilde) es:

            C_tilde = ( Gsᵀ Gs + λ_spatial² · Lsᵀ Ls + λ_mag² · I )⁻¹

        donde Gs = Wd·G·Ws y Ls = W_m·Ws son EXACTAMENTE los operadores que arma
        solve_inversion_lsqr (mismos Wd, Ws, depth weighting Li&Oldenburg β=2,
        Laplaciano no-uniforme, λ_spatial = alpha_spatial·(n_sensores/n_activas) y el
        damping λ_mag). Se estima diag(C_tilde) por Hutchinson y se devuelve la
        desviación estándar EN UNIDADES FÍSICAS deshaciendo el column scaling:

            σ_phys_j = Ws_jj · sqrt( diag(C_tilde)_j )

        Es incertidumbre estadística defendible (1σ por vóxel), a diferencia del score
        de ranking heurístico. ALCANCE HONESTO: es la covarianza posterior LINEAL
        alrededor de la solución regularizada; NO captura la no-unicidad no-lineal, ni
        errores de modelo/topografía, ni el sesgo de profundidad inherente. Debe
        reportarse como "σ posterior lineal", no como verdad absoluta.

        Método de SOLO LECTURA: no altera la solución ni el estado del solver.
        Devuelve un array (total_voxels,) con NaN en celdas de aire.
        """
        g_observed = np.asarray(g_observed, dtype=np.float64)
        y_c = np.asarray(y_c, dtype=np.float64)

        if forward_model is None or sensor_coords is None or x_c is None or z_c is None:
            raise ValueError(
                "estimate_posterior_std requiere forward_model, sensor_coords, x_c, z_c."
            )
        if lambda_mag <= 0:
            raise ValueError(
                "lambda_mag debe ser > 0: garantiza que C sea definida positiva (SPD)."
            )

        # ── Máscara de celdas activas (idéntica a solve_inversion_lsqr) ───────
        if topography_elevations is None:
            topo_depth = np.zeros(self.total_voxels, dtype=np.float64)
        else:
            topo_depth = np.asarray(topography_elevations, dtype=np.float64)
        voxel_top = y_c - (self.dy / 2.0)
        active_cells = voxel_top >= topo_depth
        n_active = int(np.sum(active_cells))
        if n_active == 0:
            raise ValueError("[UQ] No hay celdas activas bajo la topografía dada.")

        n_sensors = len(g_observed)
        y_c_active = y_c[active_cells]
        x_c_arr = np.asarray(x_c, dtype=np.float64)
        z_c_arr = np.asarray(z_c, dtype=np.float64)

        G_active = forward_model._build_sparse_kernel(
            x_c_arr[active_cells], y_c_active, z_c_arr[active_cells],
            np.asarray(sensor_coords, dtype=np.float64),
        )

        # ── Data weighting Wd + column scaling Ws (igual que el solver) — R-04 ─
        if noise_floor == 0.02 and noise_pct == 0.02:
            sigma = _sigma_adaptive(g_observed)
        else:
            sigma = _sigma_parametric(g_observed, noise_floor, noise_pct)
        Wd = sp.diags(1.0 / sigma)
        G_w = Wd @ G_active
        col_norms = np.sqrt(G_w.power(2).sum(axis=0)).A1
        col_norms = np.maximum(col_norms, 1e-12)
        ws_diag = 1.0 / col_norms
        Ws = sp.diags(ws_diag)
        G_scaled = (G_w @ Ws).tocsr()

        # ── Laplaciano + depth weighting, reducido a activas y escalado ───────
        L_full = self._build_laplacian(hx=hx, hy=hy, hz=hz)
        L_active = L_full.tocsr()[active_cells, :][:, active_cells]
        z0 = self.dy / 2.0
        true_depth = np.clip(y_c_active - topo_depth[active_cells], a_min=1.0, a_max=None)
        w_depth = (true_depth + z0) ** 2.0   # Li & Oldenburg 1998: β=2
        w_reg = 1.0 / w_depth
        w_reg = w_reg / np.mean(w_reg)
        L_scaled = ((sp.diags(w_reg) @ L_active) @ Ws).tocsr()

        lambda_spatial = float(alpha_spatial) * (n_sensors / n_active)

        # ── Matriz de información posterior (SPD por el término λ_mag²·I) ─────
        A = (
            (G_scaled.T @ G_scaled)
            + (lambda_spatial ** 2) * (L_scaled.T @ L_scaled)
            + (float(lambda_mag) ** 2) * sp.identity(n_active, format="csr", dtype=np.float64)
        ).tocsr()

        diag_C = hutchinson_diag_inv(
            A, n_probes=n_probes, cg_maxiter=cg_maxiter, cg_rtol=cg_rtol, seed=seed
        )
        std_active = ws_diag * np.sqrt(diag_C)   # deshace el column scaling → t/m³

        posterior_std_full = np.full(self.total_voxels, np.nan, dtype=np.float64)
        posterior_std_full[active_cells] = std_active

        print(
            f"[UQ Hutchinson] sigma posterior: n_probes={n_probes} | "
            f"sigma_med={float(np.median(std_active)):.4g} t/m3 | "
            f"sigma_p95={float(np.percentile(std_active, 95)):.4g} t/m3"
        )
        return posterior_std_full


def compute_jacobian_dask(
    sensor_coords: np.ndarray,
    voxel_centers: np.ndarray,
    forward_model: "GravimetryForward",
    batch_size: int = 500,
) -> tuple:
    """
    Compute Jacobian (sensitivity) matrix in sensor batches using Dask, write to Zarr.

    Splits sensors into batches of `batch_size`, schedules each batch as a
    dask.delayed task, and streams results to a Zarr store — the full dense
    matrix never lives in RAM simultaneously.

    Parameters
    ----------
    sensor_coords : (n_sensors, 3) float64 — x/y/z of measurement points.
    voxel_centers : (n_voxels, 3) float64 — x/y/z of model cell centres.
    forward_model : GravimetryForward — provides dx/dy/dz and cutoff_radius.
    batch_size    : sensors per Dask task (tune for RAM vs. parallelism).

    Returns
    -------
    (zarr_path, (n_sensors, n_voxels))
    """
    import tempfile
    import dask
    from exploration.storage import save_jacobian_zarr as _save_zarr

    sensor_coords = np.asarray(sensor_coords, dtype=np.float64)
    voxel_centers = np.asarray(voxel_centers, dtype=np.float64)
    n_sensors = sensor_coords.shape[0]
    n_voxels  = voxel_centers.shape[0]

    x_c = voxel_centers[:, 0]
    y_c = voxel_centers[:, 1]
    z_c = voxel_centers[:, 2]

    # Forward model parameters (captured by value — safe to use in Dask workers).
    _dx = forward_model.dx
    _dy = forward_model.dy
    _dz = forward_model.dz
    _cr = forward_model.cutoff_radius

    # Each delayed task builds the kernel for one sensor batch and returns a
    # dense (batch, n_voxels) array. A fresh GravimetryForward per task avoids
    # cache contention between concurrent workers.
    @dask.delayed
    def _batch_kernel(start: int, end: int) -> np.ndarray:
        fm = GravimetryForward(dx=_dx, dy=_dy, dz=_dz, cutoff_radius=_cr)
        G_batch = fm._build_sparse_kernel(
            x_c, y_c, z_c,
            sensor_coords[start:end],
        )
        return G_batch.toarray()   # (end-start, n_voxels)

    # Build batch index list and schedule all tasks.
    batch_ranges = [
        (s, min(s + batch_size, n_sensors))
        for s in range(0, n_sensors, batch_size)
    ]
    delayed_batches = [_batch_kernel(s, e) for s, e in batch_ranges]

    # Fase 10 §10.4 — Out-of-core: cada batch se escribe DIRECTAMENTE a Zarr
    # sin materializar la matriz completa en RAM.
    # Peak RAM = batch_size × n_voxels × 8 bytes (un batch float64 a la vez).
    # En disco: float32 (4 bytes) → 50% menos espacio vs Sprint 2 float64.
    zarr_path = os.path.join(
        tempfile.gettempdir(),
        f"tq_jacobian_{n_sensors}x{n_voxels}.zarr",
    )
    import zarr as _zarr
    z = _zarr.open_array(
        zarr_path,
        mode="w",
        shape=(n_sensors, n_voxels),
        dtype="float32",
        chunks=(min(batch_size, n_sensors), n_voxels),
    )
    for _i, (s, e) in enumerate(batch_ranges):
        # Computa un batch a la vez (synchronous = sin pool anidado)
        batch_result = dask.compute(delayed_batches[_i], scheduler="synchronous")[0]
        z[s:e, :] = batch_result.astype(np.float32)
        del batch_result   # libera inmediatamente

    disk_mb = n_sensors * n_voxels * 4 / 1e6
    print(
        f"[JACOBIAN DASK/OOC] shape=({n_sensors},{n_voxels}) | "
        f"batches={len(batch_ranges)} | batch_size={batch_size} | "
        f"disco={disk_mb:.1f} MB (float32) | zarr={zarr_path}"
    )
    return zarr_path, (n_sensors, n_voxels)


def solve_inversion_treemesh(
    mesh,
    g_observed,
    sensor_coords,
    forward_model,
    lambda_mag: float = 3.0,
    alpha_spatial: float = 1.0,
    depth_beta: float = 2.0,
    base_density: float = 2.6,
    density_min: float = 2.6,
    density_max: float = 5.5,
    noise_floor: float = 0.02,
    noise_pct: float = 0.02,
    solver_meta: Optional[dict] = None,
    iter_lim: int = 500,
    atol: float = 1e-8,
):
    """
    SPRINT 3B — Solver de inversión gravimétrica MÍNIMO sobre malla Octree.

    Ruta PARALELA y autocontenida: NO toca GravimetryInversion.solve_inversion_lsqr
    (el solver de grilla regular validado por el certificado de recuperación sintética
    permanece intacto). Reproduce SOLO el núcleo físico común a la ruta regular:

        φ(m) = ‖Wd (G m − d)‖²
             + ‖ λ_spatial · diag(w_reg) · L · m ‖²        (suavidad, depth-weighted)
             + ‖ diag(λ_mag · w_reg) · m ‖²                 (smallness, depth-weighted H2)

    con column-scaling (Ws) idéntico, depth weighting Li & Oldenburg
    w_reg = 1/(profundidad + z0)^β normalizado, y bounds petrofísicos en espacio escalado.

    NO incluye (por diseño minimal): topografía/active-cells, padding, anclajes por
    sondaje, m_ref, poda R-05, ni cross-gradient. Esas extensiones viven en el solver
    regular; aquí el dominio es la malla Octree completa (todas las celdas activas).

    Parameters
    ----------
    mesh : TreeMesh
        Malla Octree adaptativa. Provee centros, profundidades, tamaños y el
        Laplaciano adaptativo (mesh.build_laplacian_octree()).
    g_observed : (n_sensors,) array
        Anomalía gravimétrica observada (mismas unidades que el forward).
    sensor_coords : (n_sensors, 3) array
        Coordenadas [x, y, z] de los sensores.
    forward_model : GravimetryForward
        Motor forward; se usa build_kernel_from_treemesh(mesh, sensors).

    Returns
    -------
    estimated_density : (n_cells,) array
        Densidad recuperada por celda (t/m³), bounded a [density_min, density_max].
    relative_score : (n_cells,) array
        Score de ranking de objetivo [0,1] (NO probabilidad estadística), idéntico
        en definición al solver regular: 1 − |Gᵀr|_j / max_j |Gᵀr|.
    misfit_percent : float
        ‖d − Gm‖ / ‖d‖ × 100.
    """
    g_observed = np.asarray(g_observed, dtype=np.float64)
    sensor_coords = np.asarray(sensor_coords, dtype=np.float64)
    if not np.isfinite(g_observed).all():
        raise ValueError("g_observed contiene NaN o Inf.")
    if lambda_mag <= 0:
        raise ValueError("lambda_mag debe ser mayor que 0.")
    if alpha_spatial < 0:
        raise ValueError("alpha_spatial no puede ser negativo.")

    n_cells = mesh.n_cells
    n_sensors = len(g_observed)

    # ── Forward sobre la malla Octree ─────────────────────────────────────────
    G = forward_model.build_kernel_from_treemesh(mesh, sensor_coords)   # (n_sensors, n_cells)
    if G.nnz == 0:
        raise ValueError("Kernel TreeMesh vacío: ninguna celda tiene sensibilidad a los sensores.")

    # ── Data weighting (R-04 sigma adaptativo, idéntico al solver regular) ────
    if noise_floor == 0.02 and noise_pct == 0.02:
        sigma = _sigma_adaptive(g_observed)
    else:
        sigma = _sigma_parametric(g_observed, noise_floor, noise_pct)
    Wd = sp.diags(1.0 / sigma)
    d_w = Wd @ g_observed
    G_w = (Wd @ G).tocsr()

    # ── Column scaling (Ws) ───────────────────────────────────────────────────
    col_norms = np.sqrt(G_w.power(2).sum(axis=0)).A1
    col_norms = np.maximum(col_norms, 1e-12)
    Ws = sp.diags(1.0 / col_norms)
    G_scaled = G_w @ Ws

    _lb_tilde = (float(density_min) - float(base_density)) * col_norms
    _ub_tilde = (float(density_max) - float(base_density)) * col_norms

    # ── Depth weighting (Li & Oldenburg) sobre la malla Octree ────────────────
    depths = mesh.get_cell_depths()
    sizes = mesh.get_cell_sizes()
    # z0 = media de la semi-altura de celda en profundidad (análogo a dy/2 regular,
    # robusto a celdas variables).
    z0 = 0.5 * float(np.mean(sizes[:, 1]))
    true_depth = np.clip(depths, a_min=1.0, a_max=None)
    w_depth = (true_depth + z0) ** depth_beta
    w_reg = 1.0 / w_depth
    w_reg = w_reg / np.mean(w_reg)

    # ── Smallness (depth-weighted, H2) ────────────────────────────────────────
    _w_small = float(lambda_mag) * w_reg
    _small_block = sp.diags(_w_small) @ Ws

    # ── Laplaciano adaptativo (omitido cuando alpha_spatial=0) ────────────────
    # NOTE: build_laplacian_octree usa face_map con clave 1D → O(n·ny·nz) para
    # grillas grandes (bug de escala regional). Omitir cuando alpha_spatial=0 es
    # el workaround del gate test; el fix vectorizado es Sprint 3C.
    lambda_spatial = float(alpha_spatial) * (n_sensors / max(n_cells, 1))
    if alpha_spatial > 0:
        L = mesh.build_laplacian_octree()
        W_m = sp.diags(w_reg) @ L
        L_scaled = W_m @ Ws
        G_aug = sp.vstack([G_scaled, lambda_spatial * L_scaled, _small_block]).tocsr()
        d_aug = np.concatenate([
            d_w,
            np.zeros(n_cells, dtype=np.float64),
            np.zeros(n_cells, dtype=np.float64),
        ])
    else:
        G_aug = sp.vstack([G_scaled, _small_block]).tocsr()
        d_aug = np.concatenate([
            d_w,
            np.zeros(n_cells, dtype=np.float64),
        ])

    print(
        f"[TREEMESH SOLVER] n_cells={n_cells:,} n_sensors={n_sensors:,} "
        f"G_aug=({G_aug.shape[0]:,}×{G_aug.shape[1]:,}) NNZ={G_aug.nnz:,} "
        f"lambda_mag={lambda_mag:.2e} lambda_spatial={lambda_spatial:.2e} beta={depth_beta}"
    )

    result = lsqr(G_aug, d_aug, damp=0.0, iter_lim=iter_lim, atol=atol, btol=atol, show=False)
    m_tilde = np.clip(result[0], _lb_tilde, _ub_tilde)
    _acond = result[6]

    density_contrast = Ws @ m_tilde
    if not np.isfinite(density_contrast).all():
        raise RuntimeError("LSQR (TreeMesh) devolvió densidades no finitas.")

    density_raw = float(base_density) + density_contrast
    estimated_density = np.clip(density_raw, density_min, density_max)

    # ── Misfit y score relativo (definición idéntica al solver regular) ───────
    g_model = G @ density_contrast
    residual_sensor = g_observed - g_model
    residual_error = float(np.linalg.norm(residual_sensor))
    observed_norm = float(np.linalg.norm(g_observed))
    misfit_percent = (float("nan") if observed_norm <= 0 or not np.isfinite(observed_norm)
                      else float((residual_error / observed_norm) * 100.0))

    voxel_error = np.abs(G.T @ residual_sensor)
    max_voxel_error = float(np.max(voxel_error)) if n_cells > 0 else 0.0
    if max_voxel_error <= 0 or not np.isfinite(max_voxel_error):
        relative_score = np.full(n_cells, np.nan, dtype=np.float64)
    else:
        relative_score = np.clip(1.0 - (voxel_error / max_voxel_error), 0.0, 1.0)

    _phi_d = float(np.sum((residual_sensor / sigma) ** 2))
    _chi2_final = _phi_d / max(n_sensors, 1)

    n_sat_lower = int(np.sum(density_raw < density_min))
    n_sat_upper = int(np.sum(density_raw > density_max))

    print(
        f"[TREEMESH SOLVER] Misfit={misfit_percent:.2f}% chi2={_chi2_final:.4f} "
        f"cond(A)~{_acond:.2e} sat=({n_sat_lower}+{n_sat_upper})/{n_cells:,}"
    )

    if solver_meta is not None:
        solver_meta["acond"] = float(_acond)
        solver_meta["chi2_final"] = float(_chi2_final)
        solver_meta["misfit_percent"] = misfit_percent
        solver_meta["n_cells"] = n_cells
        solver_meta["n_sat_lower"] = n_sat_lower
        solver_meta["n_sat_upper"] = n_sat_upper
        solver_meta["mesh_info"] = {
            "n_cells": n_cells,
            "n_levels": int(mesh.max_refinement_depth) + 1,
            "min_cell_size": float(sizes.min()),
        }

    return estimated_density, relative_score, misfit_percent


class TargetingEngine:
    """
    Conecta la inversión geofísica con el modelo económico.

    Importante:
    - Exporta block model COMPLETO a data/block_model_001.parquet.
    - Incluye ix, iy, iz para que main.py pueda hacer reshape correctamente.
    - Devuelve df_anomaly filtrado para la respuesta del endpoint.
    """

    @staticmethod
    def extract_and_export(
        x,
        y,
        z,
        density,
        probability,
        ix=None,
        iy=None,
        iz=None,
        block_size=10.0,
        cutoff_density=2.75,
        export_path="data/block_model_001.parquet",
        posterior_std=None,
    ):
        print("[TARGETING] Modelando clases geometalúrgicas y exportando block model.")

        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        z = np.asarray(z, dtype=np.float64)
        density = np.asarray(density, dtype=np.float64)
        probability = np.asarray(probability, dtype=np.float64)

        n = len(density)

        if not (len(x) == len(y) == len(z) == len(probability) == n):
            raise ValueError("x, y, z, density y probability deben tener el mismo largo.")

        if ix is None:
            ix = np.floor(x / block_size).astype(np.int32)
        else:
            ix = np.asarray(ix, dtype=np.int32)

        if iy is None:
            iy = np.floor(y / block_size).astype(np.int32)
        else:
            iy = np.asarray(iy, dtype=np.int32)

        if iz is None:
            iz = np.floor(z / block_size).astype(np.int32)
        else:
            iz = np.asarray(iz, dtype=np.int32)

        if not (len(ix) == len(iy) == len(iz) == n):
            raise ValueError("ix, iy e iz deben tener el mismo largo que density.")

        if not np.isfinite(density).all():
            raise ValueError("density contiene NaN o Inf.")

        if not np.isfinite(probability).all():
            raise ValueError("probability contiene NaN o Inf.")

        block_size = float(block_size)
        MAX_BLOCK_VOLUME_M3 = 1_000_000  # 100m × 100m × 100m
        block_volume = min(block_size ** 3, MAX_BLOCK_VOLUME_M3)

        density_contrast = density - 2.6
        tonnage = block_volume * density

        targeting_score = density * probability
        target_idx = int(np.argmax(targeting_score))
        target_coords = (
            float(x[target_idx]),
            float(y[target_idx]),
            float(z[target_idx])
        )

        # Normalize posterior_std: None → array de NaN (esquema Arrow estable)
        if posterior_std is not None:
            _std_arr = np.asarray(posterior_std, dtype=np.float64)
            if len(_std_arr) != n:
                _std_arr = np.full(n, np.nan, dtype=np.float64)
        else:
            _std_arr = np.full(n, np.nan, dtype=np.float64)

        # FASE 7 (Q4): nombres de columna no-mineros/compliance-safe en el Parquet.
        #   tonnage         -> bulk_rock_mass_kg
        #   probability     -> relative_target_score
        #   targeting_score -> exploration_index
        # Las variables internas (tonnage/targeting_score) se conservan; solo cambian
        # los nombres exportados y las expresiones de filtrado que los referencian.
        df = pl.DataFrame(
            {
                "ix": ix,
                "iy": iy,
                "iz": iz,
                "x": x,
                "y": y,
                "z": z,
                "density": density,
                "density_contrast": density_contrast,
                "bulk_rock_mass_kg": tonnage,
                "relative_target_score": probability,
                "exploration_index": targeting_score,
                "posterior_std": _std_arr,
            }
        )

        # El filtrado de anomalías sigue la señal primaria de densidad (sin cambios
        # de lógica); solo se actualiza el nombre de columna renombrado.
        df_anomaly = df.filter(pl.col("density") >= cutoff_density)

        os.makedirs(os.path.dirname(export_path), exist_ok=True)

        # OJO: se exporta el modelo completo, no solo anomalías.
        # Esto es necesario para que /generate y /scenario-sweep puedan hacer reshape.
        df.write_parquet(export_path)

        anomaly_path = export_path.replace(".parquet", "_anomaly.parquet")
        df_anomaly.write_parquet(anomaly_path)

        print(
            f"[TARGETING] Target sugerido: {target_coords} | "
            f"Densidad: {density[target_idx]:.3f} t/m3 | "
            f"Probabilidad: {probability[target_idx]:.1%}"
        )

        print(
            f"[TARGETING] Block model completo exportado: {export_path} | "
            f"Bloques totales: {len(df):,} | "
            f"Anomalías: {len(df_anomaly):,}"
        )

        return df_anomaly, target_coords


if __name__ == "__main__":
    NX, NY, NZ = 8, 4, 8
    BLOCK_SIZE = 10.0

    grid_x, grid_y, grid_z = np.mgrid[0:NX, 0:NY, 0:NZ]

    ix = grid_x.flatten(order="F").astype(np.int32)
    iy = grid_y.flatten(order="F").astype(np.int32)
    iz = grid_z.flatten(order="F").astype(np.int32)

    x_c = (ix * BLOCK_SIZE) + (BLOCK_SIZE / 2)
    y_c = (iy * BLOCK_SIZE) + (BLOCK_SIZE / 2)
    z_c = (iz * BLOCK_SIZE) + (BLOCK_SIZE / 2)

    sensor_coords = np.array(
        [
            [5, 0, 5],
            [15, 0, 5],
            [25, 0, 5],
            [35, 0, 5],
            [45, 0, 5],
            [55, 0, 5],
            [65, 0, 5],
            [75, 0, 5],
            [35, 0, 35],
            [45, 0, 35],
        ],
        dtype=np.float64
    )

    print(f"[GEOFÍSICA] Test local con {len(sensor_coords)} sensores.")

    forward = GravimetryForward(
        BLOCK_SIZE,
        BLOCK_SIZE,
        BLOCK_SIZE,
        cutoff_radius=120.0
    )

    kernel_sparse = forward.build_sparse_kernel(
        x_c,
        y_c,
        z_c,
        sensor_coords
    )

    true_density_contrast = np.zeros(len(x_c), dtype=np.float64)
    anomaly_mask = (
        (x_c - 40.0) ** 2
        + (y_c - 20.0) ** 2
        + (z_c - 40.0) ** 2
    ) < 25.0 ** 2

    true_density_contrast[anomaly_mask] = 0.8

    g_observed = kernel_sparse @ true_density_contrast

    inversor = GravimetryInversion(NX, NY, NZ, BLOCK_SIZE)

    est_density, prob, _misfit_percent, _normalized_sensitivity = inversor.solve_inversion_lsqr(
        g_observed,
        None,               # kernel_sparse obsoleto — Motor HPC F0.2 exclusivo
        y_c,
        lambda_mag=5e-5,
        alpha_spatial=1.5,
        forward_model=forward,
        sensor_coords=sensor_coords,
        x_c=x_c,
        z_c=z_c,
    )

    TargetingEngine.extract_and_export(
        x_c,
        y_c,
        z_c,
        est_density,
        prob,
        ix=ix,
        iy=iy,
        iz=iz,
        block_size=BLOCK_SIZE,
        cutoff_density=2.75
    )
