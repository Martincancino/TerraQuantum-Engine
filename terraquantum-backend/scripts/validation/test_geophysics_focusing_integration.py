"""
test_geophysics_focusing_integration.py — Fase 3M.5

Tests formales de backward compatibility, schema y persistencia para enable_focusing.
Ejecuta run_geophysics_inversion con grilla sintética pequeña (no usa datos reales).
No modifica exploration/focusing.py, exploration/gravimetry.py ni APIs.
"""
import sys
import numpy as np
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from schemas.geophysics_schema import GeophysicsInvertInput
from services.geophysics_service import run_geophysics_inversion


# ── Grilla sintética mínima ──────────────────────────────────────────────────
# nx=4, ny=4, nz=4, block_size=25 → depth_max=100 m, depth=40 ≤ 100 ✓
# 16 sensores → cumple mínimo de 10

_NX, _NY, _NZ, _BS = 4, 4, 4, 25

_rng = np.random.default_rng(7)


def _make_observations(n: int = 16):
    xs = np.linspace(5, _NX * _BS - 5, 4)
    zs = np.linspace(5, _NZ * _BS - 5, 4)
    XG, ZG = np.meshgrid(xs, zs)
    xf = XG.ravel()[:n]
    zf = ZG.ravel()[:n]
    g_vals = 8e-7 + 4e-7 * _rng.standard_normal(n)
    return [
        {"x_m": float(xf[i]), "y_m": 0.0, "z_m": float(zf[i]), "g": float(g_vals[i])}
        for i in range(n)
    ]


def _base_params(**overrides):
    obs = _make_observations(16)
    defaults = dict(
        project_id=None,
        run_id=None,
        depth=40,
        nir=60,
        fe=50,
        region="desconocida",
        lat="-22.0",
        lon="-68.0",
        nx=_NX,
        ny=_NY,
        nz=_NZ,
        block_size=_BS,
        cutoff_radius=200.0,
        lambda_mag=5e-5,
        alpha_spatial=2.0,
        observations=obs,
    )
    defaults.update(overrides)
    return GeophysicsInvertInput(**defaults)


# ── Utilidades ───────────────────────────────────────────────────────────────

def _run_tests():
    passed = 0
    failed = 0

    def _pass(name, detail=""):
        nonlocal passed
        print(f"PASS: {name:<56}  {detail}")
        passed += 1

    def _fail(name, reason):
        nonlocal failed
        print(f"FAIL: {name:<56}  {reason}")
        failed += 1

    # ── D. Schema ────────────────────────────────────────────────────────────

    name = "schema_default_false"
    try:
        p = GeophysicsInvertInput(
            depth=40, nir=60, fe=50, region="desconocida",
            lat="-22.0", lon="-68.0",
            nx=4, ny=4, nz=4, block_size=25,
            cutoff_radius=200.0, lambda_mag=5e-5, alpha_spatial=2.0,
            observations=_make_observations(16),
        )
        assert p.enable_focusing is False, f"default debe ser False, got {p.enable_focusing}"
        _pass(name, "enable_focusing default=False")
    except Exception as exc:
        _fail(name, str(exc))

    name = "schema_true_accepted"
    try:
        p = GeophysicsInvertInput(
            enable_focusing=True,
            depth=40, nir=60, fe=50, region="desconocida",
            lat="-22.0", lon="-68.0",
            nx=4, ny=4, nz=4, block_size=25,
            cutoff_radius=200.0, lambda_mag=5e-5, alpha_spatial=2.0,
            observations=_make_observations(16),
        )
        assert p.enable_focusing is True, f"debía ser True, got {p.enable_focusing}"
        _pass(name, "enable_focusing=True aceptado")
    except Exception as exc:
        _fail(name, str(exc))

    # ── A. Backward compatibility ────────────────────────────────────────────

    name = "backward_compat_no_focusing_key"
    try:
        params = _base_params()  # enable_focusing no especificado → False por defecto
        result = run_geophysics_inversion(params)
        report = result["report"]
        assert "focusing" not in report, (
            f"'focusing' no debe estar en report cuando enable_focusing=False. Keys: {list(report.keys())}"
        )
        _pass(name, "report sin 'focusing'")
    except Exception as exc:
        _fail(name, str(exc))

    name = "backward_compat_base_outputs_present"
    try:
        params = _base_params()
        result = run_geophysics_inversion(params)
        report = result["report"]
        assert "status" in report,        "falta 'status' en report"
        assert "voxels" in result,         "falta 'voxels' en result"
        assert "best_target" in result,    "falta 'best_target' en result"
        _pass(name, "outputs base presentes")
    except Exception as exc:
        _fail(name, str(exc))

    # ── B. Focusing enabled ──────────────────────────────────────────────────

    result_with_focusing = None

    name = "focusing_key_present_when_enabled"
    try:
        params = _base_params(enable_focusing=True)
        result_with_focusing = run_geophysics_inversion(params)
        report = result_with_focusing["report"]
        assert "focusing" in report, (
            f"'focusing' debe estar en report cuando enable_focusing=True. Keys: {list(report.keys())}"
        )
        _pass(name, "report contiene 'focusing'")
    except Exception as exc:
        _fail(name, str(exc))
        result_with_focusing = None

    if result_with_focusing is not None:
        focusing = result_with_focusing["report"].get("focusing", {})

        name = "focusing_enabled_true_or_nonfatal"
        try:
            assert "enabled" in focusing, "falta campo 'enabled'"
            # Puede ser True (éxito) o False (error no fatal); ambos son válidos
            assert isinstance(focusing["enabled"], bool), "enabled debe ser bool"
            _pass(name, f"enabled={focusing['enabled']}")
        except Exception as exc:
            _fail(name, str(exc))

        name = "focusing_base_outputs_intact"
        try:
            r = result_with_focusing["report"]
            assert "status" in r,     "falta 'status'"
            assert "voxels" in result_with_focusing, "falta 'voxels'"
            _pass(name, "outputs base intactos con focusing habilitado")
        except Exception as exc:
            _fail(name, str(exc))

        if focusing.get("enabled") is True:
            name = "focusing_scale_status_valid"
            try:
                ss = focusing.get("scale_status")
                assert ss in {"OK", "SUPRIMIDA", "INESTABLE"}, f"scale_status invalido: {ss!r}"
                _pass(name, f"scale_status={ss!r}")
            except Exception as exc:
                _fail(name, str(exc))

            name = "focusing_use_mode_valid"
            try:
                um = focusing.get("use_mode")
                assert um in {"physical_mask_candidate", "relative_targeting_score"}, (
                    f"use_mode invalido: {um!r}"
                )
                _pass(name, f"use_mode={um!r}")
            except Exception as exc:
                _fail(name, str(exc))

            name = "focusing_safety_labels_not_resource_estimate"
            try:
                labels = focusing.get("safety_labels", [])
                assert "not_resource_estimate" in labels, (
                    f"'not_resource_estimate' falta en safety_labels: {labels}"
                )
                _pass(name, f"safety_labels={labels}")
            except Exception as exc:
                _fail(name, str(exc))

            name = "focusing_metadata_present"
            try:
                fm = focusing.get("focusing_metadata")
                assert isinstance(fm, dict), "focusing_metadata debe ser dict"
                for key in ("best_iter", "total_iters", "rms_base", "rms_best",
                            "max_density_base", "max_density_msx", "elapsed_seconds"):
                    assert key in fm, f"focusing_metadata falta campo: {key!r}"
                assert fm["best_iter"] >= 0, "best_iter debe ser >= 0"
                _pass(name, f"focusing_metadata OK, best_iter={fm['best_iter']}")
            except Exception as exc:
                _fail(name, str(exc))

            name = "focusing_parquet_path_none_without_run"
            try:
                # Sin project_id/run_id → is_legacy=True → no se persiste → None
                fp = focusing.get("focusing_parquet_path")
                assert fp is None, (
                    f"focusing_parquet_path debe ser None sin project_id/run_id, got {fp!r}"
                )
                _pass(name, "focusing_parquet_path=None (no project_id/run_id)")
            except Exception as exc:
                _fail(name, str(exc))

    # ── C. LSQR base no cambia ───────────────────────────────────────────────

    name = "lsqr_density_unchanged_by_focusing"
    try:
        # Usar la misma semilla de observaciones → mismas g_obs exactas
        obs = _make_observations(16)
        params_off = GeophysicsInvertInput(
            enable_focusing=False,
            depth=40, nir=60, fe=50, region="desconocida",
            lat="-22.0", lon="-68.0",
            nx=_NX, ny=_NY, nz=_NZ, block_size=_BS,
            cutoff_radius=200.0, lambda_mag=5e-5, alpha_spatial=2.0,
            observations=obs,
        )
        params_on = GeophysicsInvertInput(
            enable_focusing=True,
            depth=40, nir=60, fe=50, region="desconocida",
            lat="-22.0", lon="-68.0",
            nx=_NX, ny=_NY, nz=_NZ, block_size=_BS,
            cutoff_radius=200.0, lambda_mag=5e-5, alpha_spatial=2.0,
            observations=obs,  # mismas observaciones
        )
        r_off = run_geophysics_inversion(params_off)
        r_on  = run_geophysics_inversion(params_on)

        # Comparar métricas base del report (densidad estadística del modelo LSQR)
        rep_off = r_off["report"]
        rep_on  = r_on["report"]
        assert abs(rep_off["avg_density"] - rep_on["avg_density"]) < 1e-9, (
            f"avg_density difiere: off={rep_off['avg_density']}, on={rep_on['avg_density']}"
        )
        assert abs(rep_off["max_density"] - rep_on["max_density"]) < 1e-9, (
            f"max_density difiere: off={rep_off['max_density']}, on={rep_on['max_density']}"
        )
        _pass(name, f"avg_density={rep_off['avg_density']}, max_density={rep_off['max_density']}")
    except Exception as exc:
        _fail(name, str(exc))

    # ── Resumen ───────────────────────────────────────────────────────────────

    total = passed + failed
    print("=" * 70)
    print(f"Resultado: {passed} PASS / {failed} FAIL  (total {total})")
    print("=" * 70)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    print("=" * 70)
    print("test_geophysics_focusing_integration.py — Fase 3M.5")
    print("=" * 70)
    _run_tests()
