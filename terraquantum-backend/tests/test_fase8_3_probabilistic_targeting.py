"""
FASE 8.3 (targeting probabilístico automático) — rank_drill_targets.

Ranking 3D de blancos perforables desde un modelo invertido + σ posterior por vóxel.
Motor-agnóstico (densidad o susceptibilidad). Verifica:
 - recupera un cuerpo plantado (blanco #1 sobre el centro del cuerpo);
 - supresión de no-máximos 3D: dos cuerpos separados → dos blancos DISTINTOS; un solo
   cuerpo no genera 50 blancos solapados;
 - la INCERTIDUMBRE importa: con rank_by="lower_confidence_bound", a igual valor el
   vóxel de baja σ le gana al de alta σ;
 - sense="negative" recupera cuerpos de bajo contraste (kimberlita/sal);
 - probabilidades en [0,1], expected_exceedance finito, salida ordenada por score;
 - celdas de aire (NaN) excluidas; validación de tamaños; vacío honesto.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from exploration.gravimetry import rank_drill_targets


NX, NY, NZ, BLOCK = 10, 6, 10, 10.0


def _grid():
    gx, gy, gz = np.mgrid[0:NX, 0:NY, 0:NZ]
    x = gx.ravel().astype(np.float64) * BLOCK + BLOCK / 2
    y = gy.ravel().astype(np.float64) * BLOCK + BLOCK / 2
    z = gz.ravel().astype(np.float64) * BLOCK + BLOCK / 2
    return x, y, z


def _blob(x, y, z, cx, cy, cz, radius, amp):
    m = np.zeros_like(x)
    m[((x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2) < radius ** 2] = amp
    return m


def test_recovers_planted_body():
    x, y, z = _grid()
    cx, cy, cz = 45.0, 25.0, 45.0
    model = _blob(x, y, z, cx, cy, cz, 12.0, 1.0)
    sigma = np.full_like(model, 0.05)
    targets = rank_drill_targets(model, x, y, z, posterior_std=sigma, top_n=5)
    assert len(targets) >= 1
    t0 = targets[0]
    dist = np.sqrt((t0["x"] - cx) ** 2 + (t0["y"] - cy) ** 2 + (t0["z"] - cz) ** 2)
    assert dist < 2 * BLOCK, f"blanco #1 lejos del cuerpo: {dist:.1f} m"
    assert 0.0 <= t0["exceedance_prob"] <= 1.0
    assert t0["exceedance_prob"] > 0.9     # cuerpo fuerte, σ baja → casi seguro


def test_nms_separates_two_bodies():
    x, y, z = _grid()
    a = _blob(x, y, z, 25.0, 25.0, 25.0, 10.0, 1.0)
    b = _blob(x, y, z, 75.0, 25.0, 75.0, 10.0, 1.0)
    model = np.maximum(a, b)
    sigma = np.full_like(model, 0.05)
    targets = rank_drill_targets(
        model, x, y, z, posterior_std=sigma, top_n=10, exclusion_radius=25.0
    )
    assert len(targets) == 2, f"esperaba 2 cuerpos distintos, obtuve {len(targets)}"
    # los dos blancos están lejos entre sí (NMS funcionó).
    d = np.sqrt(
        (targets[0]["x"] - targets[1]["x"]) ** 2
        + (targets[0]["y"] - targets[1]["y"]) ** 2
        + (targets[0]["z"] - targets[1]["z"]) ** 2
    )
    assert d >= 25.0


def test_nms_collapses_single_body_to_one_target():
    x, y, z = _grid()
    model = _blob(x, y, z, 45.0, 25.0, 45.0, 15.0, 1.0)   # cuerpo grande (muchas celdas)
    sigma = np.full_like(model, 0.05)
    targets = rank_drill_targets(
        model, x, y, z, posterior_std=sigma, top_n=10, exclusion_radius=40.0
    )
    assert len(targets) == 1, f"un solo cuerpo debe dar 1 blanco, dio {len(targets)}"


def test_uncertainty_matters_with_lcb():
    """Mismo valor de modelo, distinta σ: con lower_confidence_bound el vóxel
    bien resuelto (σ baja) supera al mal resuelto (σ alta)."""
    # Dos celdas aisladas a igual valor, separadas; resto = fondo 0.
    x = np.array([0.0, 100.0, 50.0])
    y = np.array([0.0, 0.0, 0.0])
    z = np.array([0.0, 0.0, 0.0])
    model = np.array([1.0, 1.0, 0.0])
    sigma = np.array([0.05, 0.8, 0.05])    # celda 0 confiable, celda 1 incierta
    targets = rank_drill_targets(
        model, x, y, z, posterior_std=sigma, threshold=0.3,
        rank_by="lower_confidence_bound", exclusion_radius=10.0, top_n=2,
        min_exceedance_prob=0.5,
    )
    assert len(targets) >= 1
    # El #1 debe ser la celda confiable (x=0), no la incierta (x=100).
    assert abs(targets[0]["x"] - 0.0) < 1e-9, (
        f"esperaba la celda de baja σ primero, obtuve x={targets[0]['x']}"
    )


def test_negative_sense_low_contrast_body():
    x, y, z = _grid()
    # Fondo alto, cuerpo de BAJO contraste (densidad negativa relativa).
    model = np.full_like(x, 1.0)
    mask = ((x - 45.0) ** 2 + (y - 25.0) ** 2 + (z - 45.0) ** 2) < 12.0 ** 2
    model[mask] = -0.5
    sigma = np.full_like(model, 0.05)
    targets = rank_drill_targets(
        model, x, y, z, posterior_std=sigma, sense="negative", top_n=3
    )
    assert len(targets) >= 1
    t0 = targets[0]
    dist = np.sqrt((t0["x"] - 45.0) ** 2 + (t0["y"] - 25.0) ** 2 + (t0["z"] - 45.0) ** 2)
    assert dist < 2 * BLOCK
    assert t0["model_value"] < 0.0


def test_output_well_formed_and_sorted():
    x, y, z = _grid()
    a = _blob(x, y, z, 25.0, 25.0, 25.0, 10.0, 1.0)
    b = _blob(x, y, z, 75.0, 35.0, 75.0, 8.0, 0.6)
    model = np.maximum(a, b)
    sigma = np.full_like(model, 0.05)
    targets = rank_drill_targets(
        model, x, y, z, posterior_std=sigma, top_n=10, exclusion_radius=25.0
    )
    scores = [t["score"] for t in targets]
    assert scores == sorted(scores, reverse=True), "deben venir ordenados por score desc"
    for i, t in enumerate(targets, start=1):
        assert t["rank"] == i
        assert 0.0 <= t["exceedance_prob"] <= 1.0
        assert np.isfinite(t["expected_exceedance"])
        assert t["depth"] == t["y"]
        assert t["model_value_band"][0] <= t["model_value"] <= t["model_value_band"][1]


def test_air_cells_excluded():
    x, y, z = _grid()
    model = _blob(x, y, z, 45.0, 25.0, 45.0, 12.0, 1.0)
    # Marca como aire (NaN) justo el centro del cuerpo → no debe ser elegido.
    center = np.argmin((x - 45.0) ** 2 + (y - 25.0) ** 2 + (z - 45.0) ** 2)
    model[center] = np.nan
    sigma = np.full_like(model, 0.05)
    targets = rank_drill_targets(model, x, y, z, posterior_std=sigma, top_n=5)
    for t in targets:
        assert not (
            abs(t["x"] - x[center]) < 1e-9
            and abs(t["y"] - y[center]) < 1e-9
            and abs(t["z"] - z[center]) < 1e-9
        ), "una celda de aire (NaN) no debe ser un blanco"


def test_empty_when_nothing_exceeds():
    x, y, z = _grid()
    model = np.zeros_like(x)             # nada anómalo
    sigma = np.full_like(model, 1e-6)
    targets = rank_drill_targets(
        model, x, y, z, posterior_std=sigma, threshold=10.0, top_n=5
    )
    assert targets == []


def test_validation_errors():
    x, y, z = _grid()
    model = np.zeros_like(x)
    sigma = np.ones_like(model)
    with np.testing.assert_raises(ValueError):
        rank_drill_targets(model, x[:-1], y, z, posterior_std=sigma)
    with np.testing.assert_raises(ValueError):
        rank_drill_targets(model, x, y, z, posterior_std=sigma[:-1])
    with np.testing.assert_raises(ValueError):
        rank_drill_targets(model, x, y, z, sense="sideways")
    with np.testing.assert_raises(ValueError):
        rank_drill_targets(model, x, y, z, rank_by="vibes")


def test_works_without_posterior_std():
    x, y, z = _grid()
    model = _blob(x, y, z, 45.0, 25.0, 45.0, 12.0, 1.0)
    targets = rank_drill_targets(model, x, y, z, top_n=3)   # σ homoscedástica del MAD
    assert len(targets) >= 1
    assert targets[0]["posterior_std"] is not None
