"""
FASE 20 — El contraste efectivo deja de ser invisible · backend.
================================================================

La inversión gravimétrica recupera CONTRASTE respecto de `base_density`, pero el bound
petrofísico se declara en densidad ABSOLUTA (`density_min`/`density_max`). El número que
gobierna la física es la resta —`density_min − base_density`— y hasta esta fase no salía
en ninguna parte: ni en el reporte, ni en la UI, ni en un log.

Por qué importa está MEDIDO en `validation/HALLAZGO_2026-08-06_bound_por_defecto.md`
(48 inversiones por HTTP, 6 regímenes): ese piso mueve la recuperación de PR-AUC 0,890 a
0,288 en un régimen y de 247,9 m a 24,0 m de error de profundidad en otro, CAMBIANDO DE
SIGNO entre ellos. El mismo documento **retira por escrito** la recomendación de invertir
el default. Por eso esta fase NO elige el valor: lo DECLARA, publica el % de celdas
pegadas al bound (el indicador que delata el régimen: 91,3 % → 0,0 % entre brazos) y
AVISA cuando el par quedó desacoplado.

El hallazgo también dejó escrito el hueco que estos tests cierran: *"las pruebas propias
del proyecto (`tests/test_bounds_variability.py`) sólo ejercitan pares acoplados
(2,6/2,6 · 4,5/4,5 · 3,0/3,0): **el caso desacoplado no está cubierto por ningún test**"*.

Gate de la fase: una corrida con el par desacoplado produce un aviso que viaja por el
canal que el frontend YA renderiza (`report.warnings[]` →
`lib/terraquantum/runWarnings.ts` → `WarningBanner`), y el reporte declara el contraste
efectivo y el % de celdas en el bound. Si se borra el aviso, estos tests fallan.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas.geophysics_schema import GeophysicsInvertInput
from services.geophysics_service import (
    build_effective_contrast,
    density_bound_decoupling,
    density_bound_run_warnings,
    run_geophysics_inversion,
)

NX, NY, NZ, BLOCK = 6, 8, 6, 20.0


# ─────────────────────────────────────────────────────────────────────────────
# Builders
# ─────────────────────────────────────────────────────────────────────────────

def _gravity_input(*, base_density=None, density_min=None, density_max=None,
                   run_id="f20") -> GeophysicsInvertInput:
    """Input gravimétrico pequeño con un cuerpo compacto sintético (contraste +0,8)."""
    from exploration.gravimetry import GravimetryForward

    gx, gy, gz = np.mgrid[0:NX, 0:NY, 0:NZ]
    x_c = gx.flatten(order="F") * BLOCK + BLOCK / 2
    y_c = gy.flatten(order="F") * BLOCK + BLOCK / 2
    z_c = gz.flatten(order="F") * BLOCK + BLOCK / 2
    r = np.sqrt((x_c - NX * BLOCK / 2) ** 2 + (y_c - 70.0) ** 2 + (z_c - NZ * BLOCK / 2) ** 2)
    contrast = np.where(r <= 25.0, 0.8, 0.0)

    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=4000.0)
    sx, sz = np.meshgrid(
        np.arange(5, NX * BLOCK, BLOCK), np.arange(5, NZ * BLOCK, BLOCK), indexing="ij",
    )
    sensors = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])
    g_obs = fwd.build_sparse_kernel(x_c, y_c, z_c, sensors) @ contrast

    params = GeophysicsInvertInput(
        project_id="pytest_f20", run_id=run_id,
        depth=int(NY * BLOCK), nir=83, fe=79, region="norte_chile",
        lat="-22.28", lon="-68.89",
        nx=NX, ny=NY, nz=NZ, block_size=int(BLOCK), cutoff_radius=int(NX * BLOCK * 2),
        lambda_mag=1e-3, alpha_spatial=1.0,
        observations=[
            {"x_m": float(s[0]), "y_m": 0.0, "z_m": float(s[2]), "g": float(g)}
            for s, g in zip(sensors, g_obs)
        ],
    )
    update = {}
    if base_density is not None:
        update["base_density"] = base_density
    if density_min is not None:
        update["density_min"] = density_min
    if density_max is not None:
        update["density_max"] = density_max
    return params.model_copy(update=update) if update else params


class _Params:
    """Doble mínimo para los tests puros: no vale la pena construir un input completo
    para afirmar una resta. Sin `model_fields` → `_contract_default` cae al fallback."""

    def __init__(self, base_density, density_min, density_max=5.5):
        self.base_density = base_density
        self.density_min = density_min
        self.density_max = density_max


# ═════════════════════════════════════════════════════════════════════════════
# 1. La regla de desacople: dispara donde debe y NO donde no
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("base,dmin", [
    (2.6, 2.6),    # acoplado: no-negatividad estricta
    (4.5, 4.5),    # acoplado: magnetita declarada entera
    (2.6, 0.0),    # permisivo DECLARADO (el default del paquete): régimen, no error
    (2.6, -1.0),   # cavidad/sal: contraste negativo buscado a propósito
])
def test_coherent_pairs_emit_no_warning(base, dmin):
    """El aviso es señal, no decoración: el par coherente no genera ruido.

    En particular el default del camino del paquete (base 2,6 / min 0,0) NO avisa: el
    hallazgo retiró por escrito la recomendación de invertirlo, y avisar en cada corrida
    sería exactamente elegir el valor por el usuario.
    """
    assert density_bound_run_warnings(_Params(base, dmin)) == []
    assert density_bound_decoupling(_Params(base, dmin))["rules"] == []


def test_positive_floor_is_flagged():
    """`density_min > base_density`: la roca caja queda FUERA de la caja permitida.

    Es el caso que produce el camino real de la UI — los presets de litología mueven
    `density_min` a 4,5 y `base_density` no viaja en la configuración del paquete.
    """
    d = density_bound_decoupling(_Params(2.6, 4.5))
    assert d["decoupled"] is True
    assert "positive_floor" in d["rules"]
    assert d["effective_contrast_min_t_m3"] == pytest.approx(1.9)

    avisos = density_bound_run_warnings(_Params(2.6, 4.5))
    assert len(avisos) == 1
    texto = avisos[0]
    # El aviso trae los TRES números con los que se decidió, no un adjetivo.
    assert "4.50" in texto and "2.60" in texto and "+1.90" in texto
    assert "base_density" in texto and "density_min" in texto
    assert len(texto) > 200          # accionable, no un código


def test_base_moved_with_min_at_contract_default_is_flagged():
    """La regla que pide la Fase 20: mover la roca caja sin mover el bound.

    `GeophysicsInvertInput.density_min` tiene default 2.6; si `base_density` se declara
    en 4.5 y el bound se queda en 2.6, el piso de contraste pasa a −1,9 t/m³ sin que
    nada lo diga.
    """
    params = _gravity_input(base_density=4.5, run_id="f20_rule_a")
    d = density_bound_decoupling(params)
    assert d["decoupled"] is True
    assert d["rules"] == ["base_moved_min_at_default"]
    assert d["density_min_t_m3"] == pytest.approx(2.6)     # default de contrato v1
    assert d["effective_contrast_min_t_m3"] == pytest.approx(-1.9)

    avisos = density_bound_run_warnings(params)
    assert len(avisos) == 1
    assert "DESACOPLADOS" in avisos[0]
    assert "4.50" in avisos[0] and "-1.90" in avisos[0]
    # No manda: dice que no hay valor correcto y cita dónde se midió.
    assert "variable de régimen" in avisos[0]
    assert "HALLAZGO_2026-08-06_bound_por_defecto.md" in avisos[0]


def test_contract_default_is_read_per_model_not_hardcoded():
    """v1 y v2 declaran defaults distintos de `density_min` (2.6 vs 0.0).

    La regla pregunta al modelo pydantic en vez de cablear una tabla que se
    desincroniza: con el MISMO valor (0.0) el desacople existe en v1 y no en v2.
    """
    from schemas.geophysics_schema import GeophysicsInvertInputV2

    assert GeophysicsInvertInput.model_fields["density_min"].default == 2.6
    assert GeophysicsInvertInputV2.model_fields["density_min"].default == 0.0

    v1 = _gravity_input(base_density=4.5, density_min=0.0, run_id="f20_v1")
    # base movida, pero density_min TAMBIÉN se movió respecto de su default v1 (2.6)
    assert density_bound_decoupling(v1)["rules"] == []

    v1_default = _gravity_input(base_density=4.5, run_id="f20_v1_def")
    assert density_bound_decoupling(v1_default)["rules"] == ["base_moved_min_at_default"]


def test_both_rules_can_fire_together():
    """base movida a 2.0 con density_min en el default 2.6: piso +0,6 Y desacople."""
    params = _gravity_input(base_density=2.0, run_id="f20_both")
    d = density_bound_decoupling(params)
    assert d["rules"] == ["positive_floor", "base_moved_min_at_default"]
    assert len(density_bound_run_warnings(params)) == 2


# ═════════════════════════════════════════════════════════════════════════════
# 2. La declaración: la resta y el % de celdas en el bound
# ═════════════════════════════════════════════════════════════════════════════

def test_declaration_publishes_the_subtraction_and_the_regime():
    ec = build_effective_contrast(_Params(2.6, 0.0, 5.5), {}, {})
    assert ec["contrast_min"] == pytest.approx(-2.6)
    assert ec["contrast_max"] == pytest.approx(2.9)
    assert ec["unit"] == "t/m3"
    assert ec["regime"] == "contraste_negativo_permitido"
    assert ec["decoupled"] is False

    ec0 = build_effective_contrast(_Params(2.6, 2.6, 5.5), {}, {})
    assert ec0["contrast_min"] == pytest.approx(0.0)
    assert ec0["regime"] == "no_negatividad_estricta"

    ec_pos = build_effective_contrast(_Params(2.6, 4.5, 5.5), {}, {})
    assert ec_pos["regime"] == "piso_de_contraste_positivo"
    assert ec_pos["decoupled"] is True


def test_cells_at_bound_prefers_r03_and_falls_back_to_the_solver():
    """R-03 descuenta los vóxeles muertos (reciben base_density por diseño, no por
    saturación), así que es la fuente preferida; el solver es el respaldo."""
    r03 = {"n_active_total": 1000, "sat_percent_total": 91.3,
           "n_sat_lower": 913, "n_sat_upper": 0}
    meta = {"n_active": 1000, "sat_fraction": 0.5, "n_sat_lower": 500, "n_sat_upper": 0}

    con_r03 = build_effective_contrast(_Params(2.6, 2.6), meta, r03)
    assert con_r03["cells_at_bound_source"] == "r03_saturation"
    assert con_r03["cells_at_bound_pct"] == pytest.approx(91.3)
    assert con_r03["cells_at_lower_bound_pct"] == pytest.approx(91.3)

    sin_r03 = build_effective_contrast(_Params(2.6, 2.6), meta, {})
    assert sin_r03["cells_at_bound_source"] == "solver_meta"
    assert sin_r03["cells_at_bound_pct"] == pytest.approx(50.0)


def test_declaration_survives_a_run_without_any_diagnostic():
    """Sin R-03 ni solver_meta el bloque no inventa un porcentaje: declara None."""
    ec = build_effective_contrast(_Params(2.6, 0.0), {}, {})
    assert ec["cells_at_bound_pct"] is None
    # Tampoco los desgloses: sin celdas activas, un 0,0 % sería un número INVENTADO —
    # "no medido" y "medido y salió cero" son cosas distintas (0,0 % es exactamente lo
    # que devuelve el brazo permisivo, que sí se midió).
    assert ec["cells_at_lower_bound_pct"] is None
    assert ec["cells_at_upper_bound_pct"] is None
    assert ec["n_active_cells"] == 0
    assert ec["contrast_min"] == pytest.approx(-2.6)   # la resta sí se declara siempre


# ═════════════════════════════════════════════════════════════════════════════
# 3. E2E por el motor real — el caso DESACOPLADO que no cubría ningún test
# ═════════════════════════════════════════════════════════════════════════════

def test_decoupled_run_declares_contrast_and_warns_through_the_ui_channel():
    """GATE — corrida real con el par desacoplado (base 2,6 / min 4,5).

    Afirma las tres cosas de la fase a la vez:
      1. el reporte DECLARA el contraste efectivo y el % de celdas en el bound;
      2. el aviso viaja por `warnings[]` y `technicalSummary.warnings[]` — el canal que
         el frontend ya renderiza, así que la fase no toca frontend;
      3. la CONSECUENCIA FÍSICA es real: con el piso en +1,9 t/m³ la roca caja no es
         representable y el modelo entero se recorta al bound inferior.
    """
    res = run_geophysics_inversion(
        _gravity_input(base_density=2.6, density_min=4.5, density_max=5.5,
                       run_id="f20_decoupled"))
    report = res["report"]

    ec = report["effective_contrast"]
    assert ec["base_density"] == pytest.approx(2.6)
    assert ec["density_min"] == pytest.approx(4.5)
    assert ec["contrast_min"] == pytest.approx(1.9)
    assert ec["regime"] == "piso_de_contraste_positivo"
    assert ec["decoupled"] is True
    assert "positive_floor" in ec["decoupling_rules"]

    # El indicador que delata el régimen (su poder de discriminación se mide aparte,
    # en test_cells_at_bound_separates_the_three_regimes).
    assert ec["cells_at_bound_pct"] is not None
    assert ec["cells_at_bound_pct"] > 50.0
    assert ec["n_active_cells"] > 0

    # El aviso llega por el canal del frontend, en los DOS arrays que lee runWarnings.ts.
    avisos = [w for w in report["warnings"] if "Contraste efectivo INCOHERENTE" in w]
    assert len(avisos) == 1, report["warnings"]
    assert avisos[0] in report["technicalSummary"]["warnings"]

    # Consecuencia física, medida sobre el modelo recuperado.
    densidades = np.array(
        [v["density"] for v in res["voxels"] if v.get("density") is not None],
        dtype=float)
    if densidades.size:
        assert float(np.nanmin(densidades)) >= 4.5 - 1e-6


def test_coupled_run_declares_the_contrast_and_stays_quiet():
    """La contraparte: el par por defecto declara igual y NO agrega aviso."""
    res = run_geophysics_inversion(_gravity_input(run_id="f20_coupled"))
    report = res["report"]

    ec = report["effective_contrast"]
    assert ec["decoupled"] is False
    assert ec["decoupling_rules"] == []
    assert ec["contrast_min"] == pytest.approx(0.0)      # defaults v1: 2.6 / 2.6
    assert ec["regime"] == "no_negatividad_estricta"
    assert ec["cells_at_bound_pct"] is not None

    assert not [w for w in report["warnings"] if "Contraste efectivo" in w]
    assert not [w for w in report["warnings"] if "DESACOPLADOS" in w]


def test_cells_at_bound_separates_the_three_regimes():
    """El % de celdas en el bound DISCRIMINA — es lo que lo hace un indicador y no un
    adorno. Mismo mundo, mismo survey, mismo solver; sólo se mueve el piso de contraste.

    Medido en este mundo sintético (6×8×6, cuerpo r=25 m con contraste +0,8):

        piso +1,9 (base 2,6 / min 4,5)  →  76,20 % de celdas activas en el bound
        piso  0,0 (base 2,6 / min 2,6)  →  68,27 %
        piso −2,6 (base 2,6 / min 0,0)  →   0,00 %

    Mismo orden y mismo salto al fondo que el barrido de dos brazos del hallazgo
    (91,3 % → 0,0 %). La afirmación es el ORDEN, no los números: los umbrales absolutos
    dependen del mundo y no se fijan aquí.
    """
    def _pct(**kw):
        rid = "f20_reg_" + str(kw.get("density_min", "def")).replace(".", "_")
        rep = run_geophysics_inversion(_gravity_input(run_id=rid, **kw))["report"]
        return rep["effective_contrast"]["cells_at_lower_bound_pct"]

    permisivo = _pct(density_min=0.0)
    acoplado = _pct()                                   # defaults v1: 2.6 / 2.6
    piso_positivo = _pct(density_min=4.5, density_max=5.5)

    assert permisivo == pytest.approx(0.0, abs=1e-6)
    assert acoplado > 10.0
    assert piso_positivo > acoplado


def test_run_report_declares_the_base_density_it_actually_used():
    """La nota de R-05 decía «base_density=2.60» literal aunque la corrida usara otra."""
    res = run_geophysics_inversion(
        _gravity_input(base_density=3.2, density_min=3.2, run_id="f20_base32"))
    nota = res["report"]["r05_geometry_audit"]["note"]
    assert "base_density=3.20" in nota
    assert "2.60" not in nota


# ═════════════════════════════════════════════════════════════════════════════
# 4. El reporte HTML también lo dice (no sólo el JSON)
# ═════════════════════════════════════════════════════════════════════════════

def test_html_report_renders_the_effective_contrast_section():
    from reporting.report_generator import _effective_contrast_section_html

    html = _effective_contrast_section_html({
        "unit": "t/m3", "base_density": 2.6, "density_min": 4.5, "density_max": 5.5,
        "contrast_min": 1.9, "contrast_max": 2.9,
        "regime": "piso_de_contraste_positivo",
        "regime_note": "El piso de contraste es POSITIVO.",
        "cells_at_bound_pct": 98.7, "cells_at_lower_bound_pct": 98.7,
        "cells_at_upper_bound_pct": 0.0, "n_active_cells": 1000,
        "cells_at_bound_source": "r03_saturation",
        "decoupled": True, "decoupling_rules": ["positive_floor"],
        "note": "nota",
    })
    assert "Contraste Efectivo" in html
    assert "1.9" in html and "98.7" in html
    assert "DESACOPLADOS" in html
    assert "positive_floor" in html


def test_html_section_is_empty_when_the_block_is_absent():
    """Reportes antiguos (sin el bloque) siguen generándose sin sección fantasma."""
    from reporting.report_generator import _effective_contrast_section_html

    assert _effective_contrast_section_html(None) == ""
    assert _effective_contrast_section_html({}) == ""
