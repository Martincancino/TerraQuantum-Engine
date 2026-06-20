"""
FASE 25B — Tests de la VALIDACIÓN CRUZADA LEAVE-ONE-OUT.

El gate de densidad de la Fase 25 mide la densidad en los intervalos de sondaje,
que en el combo son las celdas ANCLADAS → validar ahí es circular (pasa por
construcción). Leave-one-out ancla con N−1 sondajes y valida el sondaje OCULTO N.

Estos tests cubren la RUTA leave-one-out del harness:
  1. _loo_boreholes genera ≥3 sondajes con ground-truth/etiquetas correctas.
  2. _summarize_loo agrega los folds y emite el veredicto correcto (función pura).
  3. run_leave_one_out exige ≥3 sondajes (guard).
  4. run_leave_one_out (inversión L2 rápida) NO ancla el sondaje oculto
     (no-circularidad estructural) y reporta densidad predicha + profundidad.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from schemas.geophysics_schema import BoreholeInterval
from scripts.validation.field_validation_harness import (
    FieldProject,
    BASE_DENSITY,
    LOO_DENSITY_TOL_T_M3,
    LOO_GATE_FRACTION,
    _loo_boreholes,
    _summarize_loo,
    _render_loo_table,
    _simulate_observations,
    _invert,
    _boreholes_to_anchor_array,
    run_leave_one_out,
)


# ── Proyecto pequeño y RÁPIDO (L2, malla chica) para ejercitar la ruta real ──
def _tiny_loo_project() -> FieldProject:
    # Grilla 5³ @30m = 150m; cuerpo en el centro de celda (75,75,75), radio 35 para
    # que los sondajes de cuerpo (offset ±30) caigan dentro y los de roca caja fuera.
    return FieldProject(
        name="LOO-Tiny", nx=6, ny=6, nz=6, block_size=25.0,
        body_center_xyz=(62.5, 62.5, 62.5), body_radius_m=35.0,
        body_contrast=0.8, forward_block=12.5, sensor_half_span_m=90.0,
        n_sensors_side=6, regularization_norm="l2", data_quality_score=85.0,
    )


def _clean_tiny_items(p: FieldProject):
    """Sondajes DELGADOS sobre centros de celda → 1 vóxel cada uno, SIN solapes
    (evita el clamping a borde de _loo_boreholes en grillas chicas). 5 cuerpo + 2
    roca caja en columnas distintas → leave-one-out limpio y rápido (L2)."""
    cx, cy, cz = p.body_center_xyz
    rho_body = round(BASE_DENSITY + p.body_contrast, 3)
    d = p.block_size

    def _thin(x, z, rho):
        return BoreholeInterval(
            x_m=float(x), z_m=float(z),
            y_from_m=float(cy - 1.0), y_to_m=float(cy + 1.0),
            density_t_m3=float(rho),
        )

    return [
        {"interval": _thin(cx, cz, rho_body), "label": "BODY-C", "kind": "body"},
        {"interval": _thin(cx + d, cz, rho_body), "label": "BODY-E", "kind": "body"},
        {"interval": _thin(cx - d, cz, rho_body), "label": "BODY-W", "kind": "body"},
        {"interval": _thin(cx, cz + d, rho_body), "label": "BODY-N", "kind": "body"},
        {"interval": _thin(cx, cz - d, rho_body), "label": "BODY-S", "kind": "body"},
        # roca caja: columnas centro-de-celda lejanas (dist > radio), 1 vóxel c/u.
        {"interval": _thin(cx + 3 * d, cz, BASE_DENSITY), "label": "HOST-E", "kind": "host"},
        {"interval": _thin(cx - 2 * d, cz, BASE_DENSITY), "label": "HOST-W", "kind": "host"},
    ]


# ─────────────────────────────────────────────────────────────────────────
#  1) Generación de sondajes para leave-one-out
# ─────────────────────────────────────────────────────────────────────────
def test_loo_boreholes_structure():
    p = _tiny_loo_project()
    items = _loo_boreholes(p)
    assert len(items) >= 3, "leave-one-out necesita ≥3 sondajes"
    kinds = {it["kind"] for it in items}
    assert "body" in kinds and "host" in kinds, "deben existir sondajes de cuerpo y de roca caja"

    rho_body = BASE_DENSITY + p.body_contrast
    for it in items:
        iv = it["interval"]
        # Ground-truth coherente con la etiqueta.
        if it["kind"] == "body":
            assert abs(iv.density_t_m3 - rho_body) < 1e-9
            # el sondaje de cuerpo cae dentro del radio horizontal
            assert (iv.x_m - p.body_center_xyz[0]) ** 2 + (iv.z_m - p.body_center_xyz[2]) ** 2 \
                <= p.body_radius_m ** 2 + 1e-6
        else:
            assert abs(iv.density_t_m3 - BASE_DENSITY) < 1e-9
            assert (iv.x_m - p.body_center_xyz[0]) ** 2 + (iv.z_m - p.body_center_xyz[2]) ** 2 \
                > p.body_radius_m ** 2
        # dentro de la grilla
        assert 0.0 < iv.x_m < p.nx * p.block_size
        assert 0.0 < iv.z_m < p.nz * p.block_size


# ─────────────────────────────────────────────────────────────────────────
#  2) Agregación de folds (función pura)
# ─────────────────────────────────────────────────────────────────────────
def _fold(label, kind, abs_err, depth_err, within):
    return {
        "held_out_label": label, "kind": kind,
        "held_out_xz_m": [0.0, 0.0], "held_out_depth_m": 75.0,
        "density_measured_t_m3": 3.4 if kind == "body" else 2.6,
        "density_predicted_t_m3": None,
        "density_abs_err_t_m3": abs_err,
        "within_0_3": within,
        "status": "EVALUATED", "body_depth_err_m": depth_err,
        "n_anchored_vox": 4, "misfit": 0.01,
    }


def test_summarize_loo_go():
    p = _tiny_loo_project()
    folds = [
        _fold("BODY-C", "body", 0.10, 8.0, True),
        _fold("BODY-E", "body", 0.20, 9.0, True),
        _fold("BODY-W", "body", 0.25, 10.0, True),
        _fold("HOST-E", "host", 0.05, None, True),
    ]
    s = _summarize_loo(p, folds)
    assert s["n_body_folds"] == 3
    assert s["frac_within_0_3_body"] == 1.0
    assert s["median_body_depth_err_m"] <= s["depth_target_m"]
    assert s["density_thesis_met"] is True
    assert s["depth_thesis_met"] is True
    assert s["verdict"] == "GO"


def test_summarize_loo_no_go_density_and_depth():
    p = _tiny_loo_project()
    # Densidad fuera de tolerancia en el cuerpo + profundidad por encima del objetivo.
    folds = [
        _fold("BODY-C", "body", 0.6, 25.0, False),
        _fold("BODY-E", "body", 0.7, 28.0, False),
        _fold("HOST-E", "host", 0.05, None, True),
    ]
    s = _summarize_loo(p, folds)
    assert s["frac_within_0_3_body"] == 0.0
    assert s["density_thesis_met"] is False
    assert s["depth_thesis_met"] is False
    assert s["verdict"] == "NO_GO"
    # La roca caja (predicha trivialmente) NO debe inflar el gate de cuerpo.
    assert s["n_host_folds"] == 1


def test_render_loo_table_smoke():
    folds = [_fold("BODY-C", "body", 0.1, 8.0, True),
             _fold("HOST-E", "host", 0.05, None, True)]
    md = _render_loo_table("X", folds)
    assert "Leave-one-out" in md and "BODY-C" in md and "HOST-E" in md


# ─────────────────────────────────────────────────────────────────────────
#  3) Guard: < 3 sondajes
# ─────────────────────────────────────────────────────────────────────────
def test_loo_requires_three_boreholes():
    p = _tiny_loo_project()
    two = _loo_boreholes(p)[:2]
    with pytest.raises(ValueError):
        run_leave_one_out(p, bh_items=two)


# ─────────────────────────────────────────────────────────────────────────
#  4) Ruta real (inversión L2 rápida): NO-circularidad + reporte
# ─────────────────────────────────────────────────────────────────────────
def test_loo_run_excludes_held_out_and_reports():
    p = _tiny_loo_project()
    items = _clean_tiny_items(p)
    n = len(items)
    result = run_leave_one_out(p, bh_items=items)

    assert result["n_folds"] == n
    assert len(result["folds"]) == n
    # Las etiquetas ocultas recorren TODOS los sondajes, una por fold (sin repetir).
    held_labels = [f["held_out_label"] for f in result["folds"]]
    assert sorted(held_labels) == sorted(it["label"] for it in items)

    # NO-CIRCULARIDAD: anclar TODOS los sondajes ancla na_all vóxeles. Dejar uno
    # fuera DEBE anclar estrictamente menos (el oculto, en su columna distinta, no
    # entra). Si fuera circular (ancla el oculto igual), na_fold == na_all.
    sensors, g_obs, sigma_noise = _simulate_observations(p)
    all_arr = _boreholes_to_anchor_array([it["interval"] for it in items])
    _d, _x, _y, _z, meta_all, _m = _invert(p, sensors, g_obs, sigma_noise, all_arr)
    na_all = meta_all.get("n_anchored_voxels")
    assert na_all is not None and na_all > 0
    for f in result["folds"]:
        na = f["n_anchored_vox"]
        assert na is not None and na < na_all, (
            f"fold '{f['held_out_label']}' ancló {na} vóxeles; anclar todos ancla "
            f"{na_all}. No se está excluyendo el sondaje oculto (circular)."
        )

    # El sondaje oculto se evalúa (cae en un vóxel con densidad) y se reporta el error.
    body_folds = [f for f in result["folds"] if f["kind"] == "body"]
    assert body_folds, "debe haber folds de cuerpo"
    for f in body_folds:
        assert f["status"] == "EVALUATED"
        assert f["density_predicted_t_m3"] is not None
        assert f["density_abs_err_t_m3"] is not None
        assert f["within_0_3"] in (True, False)

    # El veredicto del proyecto es uno de los dos válidos (se MIDE, no se fuerza).
    assert result["summary"]["verdict"] in ("GO", "NO_GO")
    assert result["summary"]["density_tol_t_m3"] == LOO_DENSITY_TOL_T_M3
    assert result["summary"]["gate_fraction"] == LOO_GATE_FRACTION
