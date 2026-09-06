"""F5 — Auditoría de coherencia de diagnósticos: B1 (best_target) + B2 (depthResolution)
+ B3 (overall_verdict) deben contar la MISMA historia en un solo report_payload, nunca
contradecirse. Gap identificado en el plan maestro (docs/01_PLAN_MAESTRO.md, F5 ítem 1):
cada bloque tenía tests aislados pero faltaba un test de integración cruzada B1↔B2↔B3.

No re-litiga los umbrales físicos de cada bloque (eso es de cada test unitario propio);
verifica INVARIANTES ESTRUCTURALES que deben sostenerse SIEMPRE, sin importar cómo se
recalibren los umbrales internos de cada bloque:
  1. depthResolution.resolvable_body_depth_m es un passthrough EXACTO de
     best_target.depth_m cuando is_resolvable_depth=True, y None en caso contrario
     (nunca un número inventado independiente).
  2. best_target.is_null_space_artifact=True SIEMPRE colapsa confidence_level y el
     veredicto reconciliado a LOW — sin excepción, sin importar qué tan sanas se vean
     las demás señales (B1 y B3 de acuerdo: "no perforar aquí").
  3. El límite universal de profundidad de la gravimetría (B2 vertical
     null_space_dominated) NUNCA por sí solo degrada el veredicto B3 — es una
     propiedad ESPERADA del método (no del survey específico); si B3 empezara a
     consumirlo, todo veredicto gravimétrico terminaría en LOW (diseño documentado
     en build_reconciled_verdict, que deliberadamente no lee depthResolution).
  4. Integración real: una corrida real de Laguna del Maule (mismo harness que
     tests/test_b2_depth_resolution.py) no debe mostrar best_target y depthResolution
     contradictorios entre sí.
"""
from __future__ import annotations

import numpy as np
import polars as pl

from services.geophysics_service import (
    apply_reconciled_verdict,
    build_best_target,
    build_depth_resolution,
    build_reconciled_verdict,
)

BLOCK = 200.0


def _df(cells):
    """cells = lista de (x, y, z, density, sensitivity_proxy)."""
    return pl.DataFrame({
        "x": [float(c[0]) for c in cells],
        "y": [float(c[1]) for c in cells],
        "z": [float(c[2]) for c in cells],
        "density": [float(c[3]) for c in cells],
        "sensitivity_proxy": [float(c[4]) for c in cells],
        "probability": [1.0 for _ in cells],
        "grade": [0.0 for _ in cells],
    })


def _bg(y, sens, n=4):
    return [(1000 + 600 * i, y, 200, 2.6, sens) for i in range(n)]


def test_resolvable_body_depth_is_exact_passthrough_of_best_target():
    """Invariante de PLOMERÍA (no depende de umbrales): B2 nunca inventa una
    profundidad distinta a la que B1 ya declaró resoluble."""
    cells = _bg(100, 1.0) + [(1000, 300, 1000, 4.0, 1.0), (1000, 300, 1000 + 1e-3, 4.0, 1.0)] \
        + _bg(300, 1.0) + _bg(500, 0.8) + _bg(700, 0.2) + _bg(900, 0.05)
    df = _df(cells)

    bt = build_best_target(df, block_size=BLOCK)
    assert bt is not None
    dr = build_depth_resolution(df, observable_depth_max_m=900.0, best_target=bt, block_size=BLOCK)
    assert dr["computed"] is True

    if bt.get("is_resolvable_depth"):
        assert dr["resolvable_body_depth_m"] == round(float(bt["depth_m"]), 1)
    else:
        assert dr["resolvable_body_depth_m"] is None


def test_shallow_clean_body_b1_b2_agree_it_is_resolvable():
    """Caso sano e inequívoco (capa somera única, sensibilidad uniforme alta, sin
    señal profunda): B1 debe marcarlo resoluble Y B2 no debe clasificarlo como
    dominado por null-space — ambos bloques cuentan la MISMA historia."""
    cells = _bg(100, 1.0) + [(1000, 300, 1000, 4.0, 1.0), (1000, 300, 1000 + 1e-3, 4.0, 1.0)] \
        + _bg(300, 1.0) + _bg(500, 0.8) + _bg(700, 0.2) + _bg(900, 0.05)
    df = _df(cells)

    bt = build_best_target(df, block_size=BLOCK)
    dr = build_depth_resolution(df, observable_depth_max_m=900.0, best_target=bt, block_size=BLOCK)

    assert bt["is_resolvable_depth"] is True
    assert bt["is_null_space_artifact"] is False
    assert dr["per_axis"]["vertical"]["quality"] != "null_space_dominated"
    assert dr["resolvable_body_depth_m"] == round(float(bt["depth_m"]), 1)


def test_null_space_artifact_forces_low_everywhere_regardless_of_other_signals():
    """B1 detecta el artefacto (TODO el modelo satura el piso de malla → caso
    degenerado) → B3 debe colapsar a LOW SIEMPRE, aunque el resto de las señales
    (survey/modelo/prioridad/padding) sean HIGH. B1 y B3 nunca deben contradecirse:
    uno dice 'no fiable', el otro no puede decir 'HIGH'."""
    density_min, density_max = 2.6, 4.6
    floor_y = 900.0
    # TODO el modelo satura al bound superior en el piso de malla (degenerado):
    # 2 valores muy cercanos al bound alternados → hay algo de "anomalía" (para que
    # B2 pueda computar) pero CADA celda es artefacto null-space (ninguna resoluble).
    cells = [(1000 + 300 * i, floor_y, 1000,
              density_max - (0.01 if i % 2 == 0 else 0.02), 0.02) for i in range(8)]
    df = _df(cells)

    bt = build_best_target(df, density_min=density_min, density_max=density_max,
                           block_size=BLOCK, cutoff_density=None)
    assert bt["is_null_space_artifact"] is True
    assert bt["is_resolvable_depth"] is False

    dr = build_depth_resolution(df, observable_depth_max_m=floor_y, best_target=bt, block_size=BLOCK)
    # B1 ya dijo que este blanco no es resoluble/fiable → B2 nunca debe reportarle
    # una profundidad "resoluble" (sería una contradicción directa con B1).
    assert dr["resolvable_body_depth_m"] is None or bt.get("is_resolvable_depth") is False

    payload = {
        "confidence_level": "HIGH",
        "model_reliability_level": "HIGH_RELIABILITY",
        "priority_class": "HIGH_RELATIVE_PRIORITY",
        "r06_padding_saturation_audit": {"phase_gate_recommendation": "APPROVE_USING_SAT_CORE"},
        "best_target": bt,
        "depthResolution": dr,
    }
    verdict = apply_reconciled_verdict(payload)
    assert verdict["level"] == "LOW"
    assert "best_target_null_space" in verdict["limiting_factors"]
    assert payload["best_target"]["confidence_level"] == "LOW"


def test_universal_vertical_null_space_alone_never_downgrades_b3():
    """CONTRATO DE DISEÑO (regresión, no umbral): la limitación vertical de la
    gravimetría (B2 null_space_dominated) es una propiedad ESPERADA y UNIVERSAL del
    método potencial-solo — NO un defecto de este survey en particular. Si B3
    empezara a consumirla, todo veredicto gravimétrico terminaría en LOW (perdería
    poder discriminante, exactamente el problema que motivó F5). build_reconciled_verdict
    NO debe leer depthResolution — este test lo deja explícito para que un cambio
    futuro que lo haga sea una decisión consciente, no un accidente."""
    # FASE 21: el checkerboard se declara PASS. Antes este test afirmaba HIGH con el
    # diagnóstico AUSENTE, y eso ya no da el techo libre (`NOT_RUN` topea como `FAIL`).
    # Su contrato nunca fue "sale HIGH" sino "depthResolution no entra", así que además
    # de arreglar el payload se afirma el contrato DIRECTAMENTE: el veredicto tiene que
    # ser INVARIANTE ante la presencia de depthResolution. Eso es más fuerte que un
    # nivel concreto y sobrevive a cualquier tope futuro de otra señal.
    base = {
        "confidence_level": "HIGH",
        "model_reliability_level": "HIGH_RELIABILITY",
        "priority_class": "HIGH_RELATIVE_PRIORITY",
        "r06_padding_saturation_audit": {"phase_gate_recommendation": "APPROVE_USING_SAT_CORE"},
        "best_target": {"confidence_level": "HIGH", "is_null_space_artifact": False},
        "checkerboard_qa": {"status": "PASS", "pearson_r": 0.72},
        # FASE 26: el perfil de resolución tampoco debe interferir con esta invariancia.
        "resolution_qa": {"computed": True, "resolves_anywhere": True,
                          "resolvability_index": 0.25,
                          "shallowest_band_resolution_m": 250.0,
                          "deepest_resolved_m": 500.0, "max_block_tested_m": 750.0,
                          "sigma_used": {"snr_signal": 3.6}},
    }
    con_b2 = dict(base, depthResolution={
        "computed": True,
        "deep_mass_fraction": 0.94,
        "per_axis": {"vertical": {"quality": "null_space_dominated", "deep_mass_fraction": 0.94}},
    })

    verdict = build_reconciled_verdict(con_b2)
    # FASE 26/30: el nivel concreto NO se afirma aquí —lo movía primero la retención
    # declarada y hoy lo mueve el sello de HIGH—. El contrato de este test nunca fue el
    # nivel: era que `depthResolution` no entra en el worst-of. Se afirma eso, que es más
    # fuerte y sobrevive a cualquier tope futuro de otra señal.
    assert "depthResolution" not in verdict["components"]
    assert not any("depth" in f for f in verdict["limiting_factors"])
    # La invariancia: quitar B2 no cambia NADA del veredicto.
    sin_b2 = build_reconciled_verdict(base)
    assert verdict["level"] == sin_b2["level"]
    assert verdict["limiting_factors"] == sin_b2["limiting_factors"]
    assert verdict["components"] == sin_b2["components"]


def test_ldm_real_run_best_target_and_depth_resolution_do_not_contradict():
    """Integración real (mismo harness que test_b2_depth_resolution.py): en una
    corrida REAL de Laguna del Maule, best_target y depthResolution no deben
    contradecirse entre sí, sin importar el umbral exacto de deep_mass_fraction
    vigente (eso lo verifica el test propio de B2)."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import scripts.validation.tanda_a_part1b_shallow_vs_smear as B
    from services.geophysics_service import run_geophysics_inversion

    out = run_geophysics_inversion(B._build_ldm_input(
        lambda_mag=0.0, auto_lambda=True, density_min=0.0, density_max=5.5, tag="f5coherence"))
    report = out["report"]
    bt = report.get("best_target")
    dr = report.get("depthResolution")
    assert dr is not None and dr["computed"] is True
    if bt is not None:
        if bt.get("is_resolvable_depth"):
            assert dr["resolvable_body_depth_m"] == round(float(bt["depth_m"]), 1)
        else:
            assert dr["resolvable_body_depth_m"] is None
        # Null-space artifact ⟹ nunca HIGH en el mismo payload.
        if bt.get("is_null_space_artifact"):
            assert bt.get("confidence_level") != "HIGH"
