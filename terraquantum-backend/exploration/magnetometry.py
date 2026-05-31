"""
FASE 9A — Motor de Inversión Magnética Independiente (induced-only).

Motor AISLADO: no importa ni modifica gravimetry.py. Replica su solidez industrial
(KDTree + matrices dispersas CSR, ThreadPool, caché de geometría, acondicionamiento
Wd→Ws→Tikhonov, anclaje de sondajes con relajación del Laplaciano) pero con la física
magnética: kernel dipolar de Intensidad Magnética Total (TMI) y susceptibilidad SI.

──────────────────────────────────────────────────────────────────────────────
MATEMÁTICA DEL KERNEL (magnetización inducida pura, sin remanencia)
──────────────────────────────────────────────────────────────────────────────
Magnetización de una celda:      M = κ · H0,   H0 = (B0/μ0) · f̂
Momento dipolar de la celda:     m = V · M = V · κ · (B0/μ0) · f̂
Campo dipolar en el sensor:      B(r) = (μ0/4π) · [ 3(m·r̂)r̂ − m ] / r³
Anomalía TMI (proyección sobre el campo ambiente, válida si |ΔT| ≪ B0):
    ΔT = f̂ · B  ⇒  μ0 se CANCELA  ⇒

        G_ij = (B0 · V / 4π) · [ 3(f̂·r̂_ij)² − 1 ] / r_ij³
             = (B0 · V / 4π) · [ 3(f̂·r_vec)² − r² ] / r⁵        (forma usada aquí)

con κ adimensional (SI), B0 en nT, V en m³, r en m → ΔT en nT.

Estabilidad numérica (garantiza cond(A) < 1e14 y que LSQR no diverja):
  • μ0 se cancela: sin constantes minúsculas/gigantes que arruinen la escala.
  • Factor angular [3cos²θ − 1] ∈ [−1, 2]: acotado.
  • Caída 1/r³ (más rápida que 1/r² de gravedad): matriz más dispersa y mejor
    condicionada bajo el mismo cutoff_radius y el mismo column-scaling Ws.
  • El signo de r̂ (celda→sensor vs sensor→celda) es IRRELEVANTE: solo aparecen
    (f̂·r_vec)² y r² (potencias pares) y r⁵=|r|⁵. Reusamos dxv = x_cell − x_sensor.

Convención de ejes del backend (idéntica a gravimetry): x=Norte, z=Este,
y=profundidad (+ hacia abajo). El vector unitario del campo inducido es entonces
    f̂ = (cos I · cos D,  sin I,  cos I · sin D)        [orden (x, y, z)]
donde I = inclinación (+ hacia abajo) y D = declinación (+ al Este desde el Norte).
"""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import lsqr
from scipy.spatial import cKDTree

logger = logging.getLogger(__name__)


def field_unit_vector(inclination_deg: float, declination_deg: float) -> np.ndarray:
    """
    Vector unitario f̂ del campo geomagnético inducido en coordenadas del backend
    (x=Norte, z=Este, y=profundidad + hacia abajo).

        f̂ = (cos I · cos D,  sin I,  cos I · sin D)

    Para Chile (hemisferio sur) I≈−30° → la componente vertical (y, hacia abajo)
    es negativa: el campo apunta hacia arriba, como debe ser. Norma exactamente 1.
    """
    I = np.deg2rad(float(inclination_deg))
    D = np.deg2rad(float(declination_deg))
    f = np.array([
        np.cos(I) * np.cos(D),   # x = Norte
        np.sin(I),               # y = profundidad (+ abajo)
        np.cos(I) * np.sin(D),   # z = Este
    ], dtype=np.float64)
    n = np.linalg.norm(f)
    return f / n if n > 0 else f


def _sigma_adaptive(d_observed: np.ndarray) -> np.ndarray:
    """
    Sigma calibrado a la amplitud de los datos (Li & Oldenburg / SimPEG), idéntico
    en forma al de gravimetry: invariante de escala, funciona en nT directamente.

        sigma_i = max(0.02 · |d_obs_i|,  0.01 · data_range)
    """
    data_range = max(float(np.max(d_observed) - np.min(d_observed)), 1e-30)
    sigma = np.maximum(0.02 * np.abs(d_observed), 0.01 * data_range)
    return np.maximum(sigma, 1e-30)


class MagnetometryForward:
    """
    FORWARD MODEL magnético: kernel dipolar TMI como matriz dispersa CSR.

    Modelo invertido = SUSCEPTIBILIDAD κ (SI, adimensional). Referencia base κ=0
    (roca huésped no magnética), por lo que el "contraste" coincide con κ.

    Convención espacial (igual que gravimetry):
      - x: Norte (horizontal)
      - y: profundidad positiva hacia abajo
      - z: Este (horizontal)
    """

    def __init__(
        self,
        dx=10.0,
        dy=10.0,
        dz=10.0,
        cutoff_radius=800.0,
        inclination_deg=-30.0,
        declination_deg=2.0,
        field_intensity_nt=23500.0,
    ):
        self.dx = float(dx)
        self.dy = float(dy)
        self.dz = float(dz)
        self.voxel_volume = self.dx * self.dy * self.dz
        self.cutoff_radius = float(cutoff_radius)

        self.inclination_deg = float(inclination_deg)
        self.declination_deg = float(declination_deg)
        self.field_intensity_nt = float(field_intensity_nt)
        self.f_hat = field_unit_vector(inclination_deg, declination_deg)

        # Prefactor escalar C = B0 · V / 4π  (nT · m³). μ0 ya cancelado.
        self.C = self.field_intensity_nt * self.voxel_volume / (4.0 * np.pi)

        # Caché de UNA geometría (misma estrategia que gravimetry): el kernel depende
        # SOLO de geometría + (f̂, B0), NO de λ/ruido/anclajes. Validación por
        # np.array_equal (sin colisión de hash), uso read-only.
        self._kernel_cache = None
        self._kernel_cache_mat = None
        self.kernel_build_count = 0

    def _build_sparse_kernel(self, x_c_act, y_c_act, z_c_act, sensor_coords):
        """
        Construye G_active (n_obs × n_active) del kernel dipolar TMI DIRECTAMENTE
        para las celdas activas.

        Régimen ÚNICO (dipolo puro): para cada par sensor–celda dentro de
        cutoff_radius,
            G = C · (3·(f̂·r_vec)² − r²) / r⁵.
        Vóxeles fuera del cutoff: contribución 0 (no se almacenan). Acumulación por
        triplets CSR (rows, cols, data) con ThreadPool. dtype float64.

        NOTA: el dipolo es una aproximación de campo medio/lejano; supone que el
        sensor NO está dentro del vóxel. Con sensores en superficie y celdas en
        subsuelo r ≥ dy/2, por lo que no hay singularidad (igual se inyecta eps).
        """
        x_c_act = np.asarray(x_c_act, dtype=np.float64)
        y_c_act = np.asarray(y_c_act, dtype=np.float64)
        z_c_act = np.asarray(z_c_act, dtype=np.float64)
        sensor_coords = np.asarray(sensor_coords, dtype=np.float64)

        # ── Caché de UNA entrada (geometría + campo) ─────────────────────────
        geom_key = (
            self.dx, self.dy, self.dz, self.cutoff_radius,
            float(self.f_hat[0]), float(self.f_hat[1]), float(self.f_hat[2]),
            self.field_intensity_nt, x_c_act.shape, sensor_coords.shape,
        )
        if (
            self._kernel_cache_mat is not None
            and self._kernel_cache is not None
            and self._kernel_cache[0] == geom_key
            and np.array_equal(self._kernel_cache[1], x_c_act)
            and np.array_equal(self._kernel_cache[2], y_c_act)
            and np.array_equal(self._kernel_cache[3], z_c_act)
            and np.array_equal(self._kernel_cache[4], sensor_coords)
        ):
            print("[MAG FORWARD] Cache HIT: G_active reutilizado (misma geometría/campo).")
            return self._kernel_cache_mat

        n_active = len(x_c_act)
        n_obs = len(sensor_coords)

        eps = 1e-10 * min(self.dx, self.dy, self.dz)
        t_start = time.perf_counter()
        max_workers = max(1, (os.cpu_count() or 2) - 1)

        print(
            f"[MAG FORWARD] Kernel dipolar TMI (KDTree + ThreadPool({max_workers}w). "
            f"n_active={n_active:,} | n_obs={n_obs:,} | cutoff={self.cutoff_radius:.0f}m | "
            f"I={self.inclination_deg:.1f} D={self.declination_deg:.1f} B0={self.field_intensity_nt:.0f}nT"
        )

        voxel_centers = np.column_stack([x_c_act, y_c_act, z_c_act])
        tree = cKDTree(voxel_centers)

        t_q0 = time.perf_counter()
        cutoff_lists = tree.query_ball_point(sensor_coords, r=self.cutoff_radius)
        t_q1 = time.perf_counter()

        _x, _y, _z = x_c_act, y_c_act, z_c_act
        _fx, _fy, _fz = float(self.f_hat[0]), float(self.f_hat[1]), float(self.f_hat[2])
        _C = self.C

        def _sensor_row(i):
            """Triplets (rows, cols, data) para el sensor i — sin escrituras compartidas."""
            sx, sy, sz = sensor_coords[i]
            idx = np.asarray(cutoff_lists[i], dtype=np.int32)
            if len(idx) == 0:
                return (
                    np.empty(0, dtype=np.int32),
                    np.empty(0, dtype=np.int32),
                    np.empty(0, dtype=np.float64),
                )
            dxv = _x[idx] - sx
            dyv = _y[idx] - sy
            dzv = _z[idx] - sz
            r2 = dxv * dxv + dyv * dyv + dzv * dzv + eps     # eps anti-singularidad
            fdot = _fx * dxv + _fy * dyv + _fz * dzv
            r5 = r2 ** 2.5                                    # |r|⁵
            data = _C * (3.0 * fdot * fdot - r2) / r5         # nT por unidad de κ
            return (
                np.full(len(idx), i, dtype=np.int32),
                idx,
                data.astype(np.float64),
            )

        t_k0 = time.perf_counter()
        rows_chunks, cols_chunks, data_chunks = [], [], []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
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
            f"[MAG FORWARD] G_active CSR: NNZ={G_active.nnz:,} | Fill={fill_rate:.4%} | "
            f"t_total={t_end-t_start:.2f}s (query={t_q1-t_q0:.3f}s, kernel={t_k1-t_k0:.3f}s)"
        )

        if G_active.nnz == 0:
            raise ValueError(
                "El kernel magnético G_active quedó vacío. "
                "Revisa cutoff_radius, coordenadas de sensores y active_cells."
            )

        self._kernel_cache = (
            geom_key, x_c_act.copy(), y_c_act.copy(), z_c_act.copy(), sensor_coords.copy(),
        )
        self._kernel_cache_mat = G_active
        self.kernel_build_count += 1
        return G_active

    def build_sparse_kernel(self, x_vox, y_vox, z_vox, sensor_coords):
        """API pública: trata TODOS los vóxeles como activos. Delega en _build_sparse_kernel."""
        x_vox = np.asarray(x_vox, dtype=np.float64)
        y_vox = np.asarray(y_vox, dtype=np.float64)
        z_vox = np.asarray(z_vox, dtype=np.float64)
        sensor_coords = np.asarray(sensor_coords, dtype=np.float64)

        if len(x_vox) == 0:
            raise ValueError("No hay vóxeles para construir el kernel magnético.")
        if len(sensor_coords) == 0:
            raise ValueError("No hay sensores para construir el kernel magnético.")
        if not (np.isfinite(x_vox).all() and np.isfinite(y_vox).all() and np.isfinite(z_vox).all()):
            raise ValueError("Las coordenadas de vóxeles contienen NaN o Inf.")
        if not np.isfinite(sensor_coords).all():
            raise ValueError("Las coordenadas de sensores contienen NaN o Inf.")

        return self._build_sparse_kernel(x_vox, y_vox, z_vox, sensor_coords)


class MagnetometryInversion:
    """
    INVERSE MODEL magnético: LSQR + regularización espacial Tikhonov 3D sobre la
    SUSCEPTIBILIDAD (SI). Replica la lógica de acondicionamiento de gravimetry
    (Wd → Ws → sistema aumentado) y el anclaje de sondajes con relajación del
    Laplaciano, pero con física magnética:

      - base_susc = 0.0           (la susceptibilidad ES el contraste)
      - bounds [susc_min, susc_max] con susc_min=0 (no-negatividad física)
      - depth weighting β=1.5     (FASE 9B: β=3 sobre-compensa frente a la
                                   regularización Tikhonov+Laplaciano ya presente y
                                   hunde el pico; β=1.5 lo mantiene a profundidad real)

    Convención de memoria order='F'; índice plano = ix + nx·iy + nx·ny·iz.
    """

    def __init__(self, nx=100, ny=50, nz=100, block_size=10.0):
        self.nx = int(nx)
        self.ny = int(ny)
        self.nz = int(nz)
        self.dx = float(block_size)
        self.dy = float(block_size)
        self.dz = float(block_size)
        self.base_susc = 0.0
        self.total_voxels = self.nx * self.ny * self.nz

        if self.nx <= 0 or self.ny <= 0 or self.nz <= 0:
            raise ValueError("nx, ny y nz deben ser mayores que 0.")
        if self.dx <= 0:
            raise ValueError("block_size debe ser mayor que 0.")

    def _build_laplacian(self, hx=None, hy=None, hz=None):
        """
        Laplaciano 3D puro (sin wrap-around) como CSR, orden F. Pesos de arista
        físicos para malla no-uniforme: w_ij = 2/(h_i + h_j). hx/hy/hz=None → uniforme.

        Geometría pura (sin física): re-implementado aquí para mantener el motor
        magnético totalmente desacoplado de gravimetry.
        """
        idx_grid = np.arange(self.total_voxels, dtype=np.int64).reshape(
            (self.nx, self.ny, self.nz), order="F"
        )
        row_parts, col_parts, data_parts = [], [], []

        def add_edges(a_idx, b_idx, weights):
            a = a_idx.ravel(order="F")
            b = b_idx.ravel(order="F")
            w = weights.ravel()
            row_parts.append(a); col_parts.append(b); data_parts.append(w)
            row_parts.append(b); col_parts.append(a); data_parts.append(w)

        if self.nx > 1:
            if hx is not None:
                wx_1d = 2.0 / (hx[:-1] + hx[1:])
                wx = np.broadcast_to(wx_1d[:, None, None], (self.nx - 1, self.ny, self.nz)).copy()
            else:
                wx = np.ones((self.nx - 1, self.ny, self.nz), dtype=np.float64)
            add_edges(idx_grid[:-1, :, :], idx_grid[1:, :, :], wx)

        if self.ny > 1:
            if hy is not None:
                wy_1d = 2.0 / (hy[:-1] + hy[1:])
                wy = np.broadcast_to(wy_1d[None, :, None], (self.nx, self.ny - 1, self.nz)).copy()
            else:
                wy = np.ones((self.nx, self.ny - 1, self.nz), dtype=np.float64)
            add_edges(idx_grid[:, :-1, :], idx_grid[:, 1:, :], wy)

        if self.nz > 1:
            if hz is not None:
                wz_1d = 2.0 / (hz[:-1] + hz[1:])
                wz = np.broadcast_to(wz_1d[None, None, :], (self.nx, self.ny, self.nz - 1)).copy()
            else:
                wz = np.ones((self.nx, self.ny, self.nz - 1), dtype=np.float64)
            add_edges(idx_grid[:, :, :-1], idx_grid[:, :, 1:], wz)

        if not row_parts:
            raise ValueError("Grilla demasiado pequeña para construir el regularizador espacial.")

        rows = np.concatenate(row_parts)
        cols = np.concatenate(col_parts)
        data = np.concatenate(data_parts)
        off_diag = sp.coo_matrix((data, (rows, cols)), shape=(self.total_voxels, self.total_voxels))
        diag_data = -np.asarray(off_diag.sum(axis=1)).ravel()
        diag_mat = sp.diags(diag_data, 0, dtype=np.float64)
        L = (off_diag + diag_mat).tocsr()
        print(f"[MAG INVERSIÓN] Laplaciano CSR creado. NNZ: {L.nnz:,}")
        return L

    def solve_magnetic_inversion_lsqr(
        self,
        d_observed,                     # anomalía TMI observada (nT), una por sensor
        y_c,
        lambda_mag=1e-4,
        alpha_spatial=1.0,
        topography_elevations=None,
        sensor_coords=None,
        x_c=None,
        z_c=None,
        forward_model=None,             # MagnetometryForward (requerido)
        # ── Bound petrofísico sobre la susceptibilidad recuperada (SI) ───────
        susc_min: float = 0.0,
        susc_max: float = 1.0,
        # ── Tensor mesh (Laplaciano no-uniforme) ─────────────────────────────
        hx=None, hy=None, hz=None,
        # ── Data weighting ───────────────────────────────────────────────────
        noise_floor=0.02,
        noise_pct=0.02,
        # ── Depth weighting (FASE 9B: β=1.5 calibrado) ───────────────────────
        # β=3 (Li & Oldenburg 1996, magnetics) sobre-compensa AQUÍ porque ya hay
        # regularización espacial (Tikhonov + Laplaciano 3D): el peso ~1/depth³
        # empuja la masa hacia el fondo y hunde el pico (p.ej. y≈75 cuando la
        # anomalía real está en y≈40). β=1.5 estabiliza sin sobre-profundizar.
        depth_beta: float = 1.5,
        # ── Anclaje por sondajes (boreholes) — susceptibilidad medida ────────
        # boreholes: array (n,5) [x_m, z_m, y_from_m, y_to_m, susc_SI] o None.
        # Strong soft constraint (smallness × anchor_kappa) + relajación local del
        # Laplaciano (filas × laplacian_relax_alpha), idéntico a la FASE 8 de gravedad
        # pero anclando SUSCEPTIBILIDAD en vez de densidad.
        boreholes: Optional[np.ndarray] = None,
        anchor_kappa: float = 1e4,      # NO usar 1e6: degradaría cond(A)
        laplacian_relax_alpha: float = 0.2,
        # ── OUT: diagnósticos numéricos ──────────────────────────────────────
        solver_meta: Optional[dict] = None,
    ):
        """
        LSQR + Tikhonov 3D sobre susceptibilidad. Mismo pipeline de acondicionamiento
        que gravimetry: Wd (sigma adaptivo) → Ws (column scaling) → sistema aumentado
        vstack([G_scaled, λ_spatial·L_scaled]) → smallness (damp o bloque diferencial
        cuando hay anclajes).

        Devuelve una tupla (longitud total_voxels, NaN en celdas de aire):
            susceptibility_full     : κ recuperada (SI), clip a [susc_min, susc_max].
            relative_score_full     : score de ranking [0,1] (NO probabilidad).
            misfit_percent          : ‖d − Gm‖ / ‖d‖ × 100.
            normalized_sensitivity  : proxy de sensibilidad (columna de G) normalizado.
        """
        print("[MAG INVERSIÓN] Preparando solver LSQR + Tikhonov (kernel dipolar TMI).")

        d_observed = np.asarray(d_observed, dtype=np.float64)
        y_c = np.asarray(y_c, dtype=np.float64)

        if forward_model is None or sensor_coords is None or x_c is None or z_c is None:
            raise ValueError(
                "solve_magnetic_inversion_lsqr requiere forward_model, sensor_coords, x_c, z_c."
            )
        if not np.isfinite(d_observed).all():
            raise ValueError("d_observed (TMI) contiene NaN o Inf.")
        if lambda_mag <= 0:
            raise ValueError("lambda_mag debe ser mayor que 0.")
        if alpha_spatial < 0:
            raise ValueError("alpha_spatial no puede ser negativo.")
        if susc_max <= susc_min:
            raise ValueError("susc_max debe ser mayor que susc_min.")

        # ── Máscara de celdas activas (topografía; y positivo hacia abajo) ───
        if topography_elevations is None:
            topo_depth = np.zeros(self.total_voxels, dtype=np.float64)
        else:
            topo_depth = np.asarray(topography_elevations, dtype=np.float64)
            if topo_depth.shape[0] != self.total_voxels:
                raise ValueError(
                    f"topography_elevations debe tener {self.total_voxels} elementos, "
                    f"got {topo_depth.shape[0]}."
                )

        voxel_top = y_c - (self.dy / 2.0)
        active_cells = voxel_top >= topo_depth
        n_active = int(np.sum(active_cells))
        n_air = self.total_voxels - n_active
        if n_active == 0:
            raise ValueError("Ningún vóxel activo bajo la topografía dada.")

        print(
            f"[MAG INVERSIÓN] Active cells: {n_active:,} / {self.total_voxels:,} "
            f"({100.0 * n_active / self.total_voxels:.1f}% activo, {n_air:,} de aire)"
        )

        n_sensors = len(d_observed)
        y_c_active = y_c[active_cells]
        x_c_arr = np.asarray(x_c, dtype=np.float64)
        z_c_arr = np.asarray(z_c, dtype=np.float64)

        # ── Kernel directo sobre celdas activas ──────────────────────────────
        G_active = forward_model._build_sparse_kernel(
            x_c_arr[active_cells], y_c_active, z_c_arr[active_cells],
            np.asarray(sensor_coords, dtype=np.float64),
        )
        if G_active.nnz == 0:
            raise ValueError("Kernel magnético vacío: ningún vóxel activo es sensible a los sensores.")

        # ── Anclaje por sondajes: mapeo de intervalos → vóxeles activos ──────
        # (idéntico a la FASE 8 de gravedad; col 5 = susceptibilidad SI)
        _anchor_active = None
        _anchor_value_active = None
        if boreholes is not None and len(boreholes) > 0:
            _bh = np.asarray(boreholes, dtype=np.float64)
            if _bh.ndim != 2 or _bh.shape[1] != 5:
                raise ValueError(
                    "boreholes debe tener shape (n,5): [x_m, z_m, y_from_m, y_to_m, susc_SI]."
                )
            _anchor_mask_full = np.zeros(self.total_voxels, dtype=bool)
            _anchor_value_full = np.zeros(self.total_voxels, dtype=np.float64)
            _tol_xz = self.dx / 2.0
            for _bx, _bz, _yf, _yt, _bsusc in _bh:
                if _yt < _yf:
                    _yf, _yt = _yt, _yf
                _col = (np.abs(x_c_arr - _bx) <= _tol_xz) & (np.abs(z_c_arr - _bz) <= _tol_xz)
                if not np.any(_col):
                    continue
                _seg = _col & (y_c >= _yf) & (y_c <= _yt)
                if not np.any(_seg):
                    _ymid = 0.5 * (_yf + _yt)
                    _cidx = np.where(_col)[0]
                    _near = int(_cidx[int(np.argmin(np.abs(y_c[_cidx] - _ymid)))])
                    _seg = np.zeros(self.total_voxels, dtype=bool)
                    _seg[_near] = True
                _anchor_mask_full[_seg] = True
                _anchor_value_full[_seg] = float(_bsusc) - self.base_susc
            _anchor_active = _anchor_mask_full[active_cells]
            _anchor_value_active = _anchor_value_full[active_cells]

        _has_anchors = _anchor_active is not None and bool(np.any(_anchor_active))
        if _has_anchors:
            print(
                f"[MAG FASE 8] Anclaje sondajes: {int(np.sum(_anchor_active)):,} vóxeles | "
                f"kappa={anchor_kappa:.0e} | lap_relax={laplacian_relax_alpha}"
            )

        # ── Formal Data Weighting Wd — sigma adaptivo ────────────────────────
        if noise_floor == 0.02 and noise_pct == 0.02:
            sigma = _sigma_adaptive(d_observed)
        else:
            sigma = np.maximum(noise_floor + noise_pct * np.abs(d_observed), 1e-30)
        Wd = sp.diags(1.0 / sigma)
        G_w = Wd @ G_active
        d_w = Wd @ d_observed

        # ── Sensitivity proxy (DOI) ──────────────────────────────────────────
        _sensitivity = np.sqrt(G_w.power(2).sum(axis=0)).A1
        max_sens = float(np.max(_sensitivity)) if len(_sensitivity) > 0 else 0.0
        normalized_sensitivity_active = _sensitivity / max_sens if max_sens > 0 else np.zeros_like(_sensitivity)

        # ── Column scaling Ws ────────────────────────────────────────────────
        col_norms = np.maximum(np.sqrt(G_w.power(2).sum(axis=0)).A1, 1e-12)
        Ws = sp.diags(1.0 / col_norms)
        G_scaled = G_w @ Ws

        # ── Laplaciano reducido a celdas activas ─────────────────────────────
        L_full = self._build_laplacian(hx=hx, hy=hy, hz=hz)
        L_active = L_full.tocsr()[active_cells, :][:, active_cells]

        # Relajación local del Laplaciano en filas ancladas (mitiga halos/bullseyes).
        if _has_anchors:
            _lap_row_scale = np.ones(n_active, dtype=np.float64)
            _lap_row_scale[_anchor_active] = float(laplacian_relax_alpha)
            L_active = (sp.diags(_lap_row_scale) @ L_active).tocsr()

        # ── Depth Weighting (FASE 9B: β=1.5, z0 ligado a la grilla) ──────────
        # z0 es el desplazamiento que estabiliza el peso cerca de la superficie y
        # evita la singularidad 1/depth^β en la primera capa. Formulación de Li &
        # Oldenburg: z0 debe ser PEQUEÑO y del orden del tamaño de celda (medio
        # voxel), NO un valor grande arbitrario. Aquí z0 = 0.5·dy.
        z0 = 0.5 * self.dy
        true_depth = np.clip(y_c_active - topo_depth[active_cells], a_min=1.0, a_max=None)
        w_depth = (true_depth + z0) ** float(depth_beta)
        w_reg = 1.0 / w_depth
        w_reg = w_reg / np.mean(w_reg)
        W_m = sp.diags(w_reg) @ L_active
        L_scaled = W_m @ Ws

        # ── Sistema aumentado ────────────────────────────────────────────────
        lambda_spatial = float(alpha_spatial) * (n_sensors / n_active)

        # RHS de regularización: 0, salvo desplazamiento hacia el valor del sondaje
        # en las filas ancladas (igual que gravedad con m_ref por celda).
        if _has_anchors:
            m_ref_sol = np.zeros(n_active, dtype=np.float64)
            m_ref_sol[_anchor_active] = _anchor_value_active[_anchor_active]
            d_reg = lambda_spatial * (W_m @ m_ref_sol)
        else:
            d_reg = np.zeros(n_active, dtype=np.float64)

        G_aug = sp.vstack([G_scaled, lambda_spatial * L_scaled]).tocsr()
        d_aug = np.concatenate([d_w, d_reg])

        print(
            f"[MAG INVERSIÓN] Ejecutando LSQR. "
            f"lambda_mag={lambda_mag:.2e} | lambda_spatial={lambda_spatial:.2e} | depth_beta={depth_beta}"
        )

        # Smallness: damp uniforme, o bloque diferencial cuando hay anclajes
        # (κ·λ_mag en celdas ancladas, apuntando al valor del sondaje).
        if _has_anchors:
            _w_small = np.full(n_active, float(lambda_mag), dtype=np.float64)
            _w_small = np.where(_anchor_active, float(anchor_kappa) * float(lambda_mag), _w_small)
            _small_block = sp.diags(_w_small) @ Ws
            _small_target = np.zeros(n_active, dtype=np.float64)
            _small_target[_anchor_active] = _anchor_value_active[_anchor_active]
            _d_small = _w_small * _small_target
            A_sys = sp.vstack([G_aug, _small_block]).tocsr()
            b_sys = np.concatenate([d_aug, _d_small])
            result = lsqr(A_sys, b_sys, damp=0.0, iter_lim=500, atol=1e-8, btol=1e-8, show=False)
        else:
            result = lsqr(G_aug, d_aug, damp=float(lambda_mag), iter_lim=500, atol=1e-8, btol=1e-8, show=False)

        m_tilde = result[0]
        _acond = float(result[6])
        susc_contrast_active = Ws @ m_tilde

        if len(susc_contrast_active) != n_active:
            raise RuntimeError("LSQR devolvió un vector de susceptibilidad con tamaño incorrecto.")
        if not np.isfinite(susc_contrast_active).all():
            raise RuntimeError("LSQR devolvió susceptibilidades no finitas.")

        if _acond > 1e12:
            print(
                f"[MAG INVERSIÓN] WARN cond(A)={_acond:.2e} > 1e12. "
                f"Revisar lambda_mag={lambda_mag:.2e} / anchor_kappa={anchor_kappa:.0e}."
            )

        # ── Reconstrucción física: NaN en celdas de aire, clip a bounds ──────
        susc_raw = self.base_susc + susc_contrast_active
        _sat_lower = susc_raw < susc_min
        _sat_upper = susc_raw > susc_max
        n_sat_lower = int(np.sum(_sat_lower))
        n_sat_upper = int(np.sum(_sat_upper))
        n_clipped = n_sat_lower + n_sat_upper
        clip_fraction = n_clipped / max(1, n_active)

        susceptibility_full = np.full(self.total_voxels, np.nan, dtype=np.float64)
        susceptibility_full[active_cells] = np.clip(susc_raw, susc_min, susc_max)
        if clip_fraction > 0.0:
            print(
                f"[MAG INVERSIÓN] Bound susc [{susc_min:.3f}, {susc_max:.3f}] SI: "
                f"{n_clipped:,}/{n_active:,} saturadas (low={n_sat_lower} high={n_sat_upper}) "
                f"= {clip_fraction:.1%}."
                + (" WARN alta saturación: revisar lambda/kappa/bounds." if clip_fraction > 0.10 else "")
            )

        normalized_sensitivity = np.full(self.total_voxels, np.nan, dtype=np.float64)
        normalized_sensitivity[active_cells] = normalized_sensitivity_active

        # ── Misfit + score relativo de objetivo ──────────────────────────────
        d_model = G_active @ susc_contrast_active
        residual_sensor = d_observed - d_model
        voxel_error_active = np.abs(G_active.T @ residual_sensor)

        residual_error = float(np.linalg.norm(residual_sensor))
        observed_norm = float(np.linalg.norm(d_observed))
        misfit_percent = 0.0 if observed_norm <= 0 else float((residual_error / observed_norm) * 100.0)

        max_voxel_error = float(np.max(voxel_error_active)) if n_active > 0 else 0.0
        relative_score_full = np.full(self.total_voxels, np.nan, dtype=np.float64)
        if max_voxel_error <= 0 or not np.isfinite(max_voxel_error):
            relative_score_full[active_cells] = 1.0
        else:
            relative_score_full[active_cells] = np.clip(1.0 - (voxel_error_active / max_voxel_error), 0.0, 1.0)

        _sigma_diag = _sigma_adaptive(d_observed) if (noise_floor == 0.02 and noise_pct == 0.02) \
            else np.maximum(noise_floor + noise_pct * np.abs(d_observed), 1e-30)
        _chi2_final = float(np.sum((residual_sensor / _sigma_diag) ** 2)) / max(n_sensors, 1)

        print(
            f"[MAG INVERSIÓN] Convergencia. Residual L2: {residual_error:.4e} | "
            f"Misfit: {misfit_percent:.2f}% | chi2_final={_chi2_final:.4f} | cond(A)~{_acond:.2e}"
        )

        if solver_meta is not None:
            solver_meta["acond"] = float(_acond)
            solver_meta["chi2_final"] = float(_chi2_final)
            solver_meta["n_sat_lower"] = n_sat_lower
            solver_meta["n_sat_upper"] = n_sat_upper
            solver_meta["n_sat_total"] = n_clipped
            solver_meta["n_active"] = n_active
            solver_meta["sat_fraction"] = float(clip_fraction)
            solver_meta["susc_min"] = float(susc_min)
            solver_meta["susc_max"] = float(susc_max)
            solver_meta["depth_beta"] = float(depth_beta)
            solver_meta["n_anchored_voxels"] = int(np.sum(_anchor_active)) if _anchor_active is not None else 0
            solver_meta["anchor_kappa"] = float(anchor_kappa) if _has_anchors else None
            solver_meta["laplacian_relax_alpha"] = float(laplacian_relax_alpha) if _has_anchors else None
            solver_meta["field_unit_vector"] = [float(v) for v in forward_model.f_hat]

        return susceptibility_full, relative_score_full, misfit_percent, normalized_sensitivity


if __name__ == "__main__":
    # ── Self-test sintético (round-trip): valida cond(A) sano + recuperación ──
    NX, NY, NZ = 12, 8, 12
    BLOCK = 10.0
    INC, DEC, B0 = -30.0, 2.0, 23500.0

    grid_x, grid_y, grid_z = np.mgrid[0:NX, 0:NY, 0:NZ]
    ix = grid_x.flatten(order="F").astype(np.int32)
    iy = grid_y.flatten(order="F").astype(np.int32)
    iz = grid_z.flatten(order="F").astype(np.int32)
    x_c = (ix * BLOCK) + (BLOCK / 2)
    y_c = (iy * BLOCK) + (BLOCK / 2)
    z_c = (iz * BLOCK) + (BLOCK / 2)

    # Sensores en superficie (y=0), malla 8×8 sobre el dominio
    sx, sz = np.meshgrid(np.linspace(10, 110, 8), np.linspace(10, 110, 8))
    sensor_coords = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])
    print(f"[MAG TEST] {len(sensor_coords)} sensores | grilla {NX}x{NY}x{NZ}")

    forward = MagnetometryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=200.0,
                                  inclination_deg=INC, declination_deg=DEC, field_intensity_nt=B0)

    # Anomalia de susceptibilidad enterrada (k=0.1 SI en una esfera)
    susc_true = np.zeros(len(x_c), dtype=np.float64)
    blob = ((x_c - 60.0) ** 2 + (y_c - 40.0) ** 2 + (z_c - 60.0) ** 2) < 20.0 ** 2
    susc_true[blob] = 0.1
    print(f"[MAG TEST] Voxeles anomalos (k=0.1): {int(np.sum(blob))}")

    G = forward.build_sparse_kernel(x_c, y_c, z_c, sensor_coords)
    d_obs = G @ susc_true   # TMI sintetica (nT)
    print(f"[MAG TEST] TMI sintetica: min={d_obs.min():.3f} max={d_obs.max():.3f} nT")

    inv = MagnetometryInversion(NX, NY, NZ, BLOCK)
    meta = {}
    susc_est, score, misfit, sens = inv.solve_magnetic_inversion_lsqr(
        d_obs, y_c, lambda_mag=1e-4, alpha_spatial=1.0,
        forward_model=forward, sensor_coords=sensor_coords, x_c=x_c, z_c=z_c,
        susc_min=0.0, susc_max=1.0, solver_meta=meta,
    )
    susc_est_clean = np.nan_to_num(susc_est, nan=0.0)
    peak_idx = int(np.argmax(susc_est_clean))
    print("-" * 70)
    print(f"[MAG TEST] cond(A)~{meta['acond']:.2e} (objetivo < 1e14): "
          f"{'OK' if meta['acond'] < 1e14 else 'FAIL'}")
    print(f"[MAG TEST] Misfit: {misfit:.3f}% | chi2_final={meta['chi2_final']:.4f}")
    print(f"[MAG TEST] k recuperada max: {susc_est_clean.max():.4f} SI "
          f"@ (x={x_c[peak_idx]:.0f}, y={y_c[peak_idx]:.0f}, z={z_c[peak_idx]:.0f})")
    print(f"[MAG TEST] Centro verdadero del blob: (60, 40, 60) | "
          f"saturacion bounds: {meta['sat_fraction']:.1%}")
    print("-" * 70)
