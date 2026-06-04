"""
test_focusing_module.py — Fase 3M.1.1

Valida el módulo exploration/focusing.py de forma aislada.
No depende de datos reales, APIs ni servicios productivos.
No modifica geophysics_service.py, schemas ni frontend.
"""
import sys
import numpy as np
import scipy.sparse as sp
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from exploration.focusing import run_focusing, MSXResult
from exploration.gravimetry import GravimetryForward, GravimetryInversion


# ── Grilla sintética pequeña ─────────────────────────────────────────────────
_NX, _NY, _NZ = 4, 4, 4
_BS = 25.0

_grid_x, _grid_y, _grid_z = np.mgrid[0:_NX, 0:_NY, 0:_NZ]
_ix = _grid_x.flatten(order="F")
_iy = _grid_y.flatten(order="F")
_iz = _grid_z.flatten(order="F")
_x_c = (_ix * _BS) + _BS / 2.0
_y_c = (_iy * _BS) + _BS / 2.0
_z_c = (_iz * _BS) + _BS / 2.0

_sx, _sz = np.meshgrid(
    np.linspace(0, _NX * _BS, 3),
    np.linspace(0, _NZ * _BS, 3),
    indexing="ij",
)
_sensor_coords = np.column_stack([_sx.ravel(), np.zeros(9), _sz.ravel()])

_fwd = GravimetryForward(dx=_BS, dy=_BS, dz=_BS, cutoff_radius=200.0)
_kernel = _fwd.build_sparse_kernel(_x_c, _y_c, _z_c, _sensor_coords)

_rng = np.random.default_rng(42)
_m_true = 0.4 * np.exp(
    -((_x_c - _NX * _BS / 2) ** 2 + (_y_c - _NY * _BS / 2) ** 2 + (_z_c - _NZ * _BS / 2) ** 2)
    / (25.0 ** 2)
)
_g_exact = _kernel @ _m_true
_g_obs   = _g_exact + 0.001 * np.max(np.abs(_g_exact)) * _rng.standard_normal(_g_exact.shape)

_inversor    = GravimetryInversion(_NX, _NY, _NZ, _BS)
_BASE_DENSITY = float(_inversor.base_density)
_est_density  = _BASE_DENSITY + np.clip(_m_true * 0.6, 0.0, 1.6)  # LSQR difuso simulado


# ── Utilidad ─────────────────────────────────────────────────────────────────

def _call_focusing(**kwargs):
    defaults = dict(
        kernel_sparse=_kernel,
        g_obs=_g_obs,
        y_c=_y_c,
        inversor=_inversor,
        est_density=_est_density,
        alpha_spatial=2.0,
        lambda_mag=5e-5,
    )
    defaults.update(kwargs)
    return run_focusing(**defaults)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_output_is_msxresult():
    result = _call_focusing()
    assert isinstance(result, MSXResult), f"Output debe ser MSXResult, got {type(result)}"


def test_m_best_shape():
    result = _call_focusing()
    assert result.m_best.shape == _est_density.shape, (
        f"Shape incorrecto: {result.m_best.shape} vs {_est_density.shape}"
    )


def test_m_best_no_nan_inf():
    result = _call_focusing()
    assert not np.any(np.isnan(result.m_best)), "m_best contiene NaN"
    assert not np.any(np.isinf(result.m_best)), "m_best contiene Inf"


def test_m_best_bounded():
    M_MAX = 1.60
    result = _call_focusing()
    lo = float(np.min(result.m_best))
    hi = float(np.max(result.m_best))
    assert lo >= 0.0,           f"m_best tiene valores negativos: {lo:.4f}"
    assert hi <= M_MAX + 1e-9,  f"m_best supera M_MAX={M_MAX}: {hi:.4f}"


def test_scale_status_valid():
    result = _call_focusing()
    valid = {"OK", "SUPRIMIDA", "INESTABLE"}
    assert result.scale_status in valid, f"scale_status inválido: {result.scale_status!r}"


def test_use_mode_valid():
    result = _call_focusing()
    valid = {"physical_mask_candidate", "relative_targeting_score"}
    assert result.use_mode in valid, f"use_mode inválido: {result.use_mode!r}"


def test_safety_labels_not_resource_estimate():
    result = _call_focusing()
    assert "not_resource_estimate" in result.safety_labels, (
        f"safety_labels debe incluir 'not_resource_estimate'. Got: {result.safety_labels}"
    )


def test_history_nonempty():
    result = _call_focusing()
    assert len(result.history) > 0, "history no puede estar vacío"
    for h in result.history:
        assert "iter"        in h, "history entry falta 'iter'"
        assert "rms"         in h, "history entry falta 'rms'"
        assert "max_density" in h, "history entry falta 'max_density'"


def test_best_iter_valid():
    result = _call_focusing()
    assert isinstance(result.best_iter, int), f"best_iter debe ser int, got {type(result.best_iter)}"
    assert 0 <= result.best_iter < result.total_iters, (
        f"best_iter={result.best_iter} fuera de rango [0, {result.total_iters})"
    )


def test_rms_finite_positive():
    result = _call_focusing()
    assert np.isfinite(result.rms_base) and result.rms_base > 0, f"rms_base inválido: {result.rms_base}"
    assert np.isfinite(result.rms_best) and result.rms_best > 0, f"rms_best inválido: {result.rms_best}"


def test_config_summary_structure():
    result = _call_focusing(alpha_spatial=2.0, lambda_mag=5e-5)
    cs = result.config_summary
    assert isinstance(cs, dict), f"config_summary debe ser dict, got {type(cs)}"

    required = [
        "method", "beta_ms", "eps_0", "eps_min", "cooling", "max_irls",
        "depth_beta", "alpha_spatial", "lambda_mag_received",
        "lambda_mag_used_in_msx", "best_iter_selection",
    ]
    for key in required:
        assert key in cs, f"config_summary falta campo: {key!r}"

    assert cs["method"] == "ms_x",                                       "method debe ser 'ms_x'"
    assert cs["lambda_mag_used_in_msx"] == 0,                            "lambda_mag_used_in_msx debe ser 0"
    assert cs["lambda_mag_received"] == 5e-5,                            "lambda_mag_received incorrecto"
    assert cs["alpha_spatial"] == 2.0,                                   "alpha_spatial incorrecto"
    assert cs["best_iter_selection"] == "min_rms_proxy_without_ground_truth", \
        "best_iter_selection incorrecto"


def test_empty_kernel_raises():
    kernel_empty = sp.csr_matrix((9, len(_x_c)))   # nnz = 0
    try:
        run_focusing(kernel_empty, _g_obs, _y_c, _inversor, _est_density)
        raise AssertionError("Debía lanzar ValueError con kernel vacío")
    except ValueError as exc:
        msg = str(exc).lower()
        assert "vacío" in msg or "kernel" in msg, f"Mensaje inesperado: {exc}"


# ── Runner ────────────────────────────────────────────────────────────────────

def run_tests():
    tests = [
        test_output_is_msxresult,
        test_m_best_shape,
        test_m_best_no_nan_inf,
        test_m_best_bounded,
        test_scale_status_valid,
        test_use_mode_valid,
        test_safety_labels_not_resource_estimate,
        test_history_nonempty,
        test_best_iter_valid,
        test_rms_finite_positive,
        test_config_summary_structure,
        test_empty_kernel_raises,
    ]

    print("=" * 70)
    print("test_focusing_module.py — Fase 3M.1.1")
    print("=" * 70)

    passed = 0
    failed = 0

    for fn in tests:
        name = fn.__name__
        try:
            detail = fn()
            print(f"PASS: {name:<44}  {detail}")
            passed += 1
        except AssertionError as exc:
            print(f"FAIL: {name:<44}  {exc}")
            failed += 1
        except Exception as exc:
            print(f"ERROR: {name:<43}  {type(exc).__name__}: {exc}")
            failed += 1

    print("=" * 70)
    print(f"Resultado: {passed} PASS / {failed} FAIL  (total {passed + failed})")
    print("=" * 70)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
