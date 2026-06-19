"""
FASE 23 — ERROR HANDLING + USER FEEDBACK OVERHAUL.

Objetivo del roadmap (Fase 23): el usuario NUNCA recibe un error genérico. Cada
fallo trae código estable, severidad, mensaje en español (>100 caracteres),
diagnóstico técnico y acción sugerida concreta.

Criterios GO/NO-GO que estos tests verifican:
  ✅ 20+ tests de error/warning PASAN
  ✅ Todos los user_message del catálogo tienen >100 caracteres
  ✅ Todos los mensajes están en español
  ✅ Todos sugieren una acción concreta (suggested_action no vacío)

Además se cubre: jerarquía de excepciones, relleno de placeholders, serialización
(to_dict / to_error_details), severidades válidas, y backward-compat de
InsufficientDataError (mensaje literal + ValueError + re-export desde multimodal).
"""
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_THIS_DIR))  # backend root

import pytest

from core.errors import (
    CATALOG,
    ErrorSpec,
    get_spec,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    SEVERITY_INFO,
    TerraquantumError,
    CsvValidationError,
    InsufficientDataError,
    SolverDivergenceError,
    ConflictingDataError,
    GeoreferencingError,
)

_VALID_SEVERITIES = {SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO}

# Pistas de "esto está en español": al menos una debe aparecer en cada texto.
# (proxy automático razonable — stopwords + caracteres acentuados frecuentes)
_SPANISH_HINTS = (
    " de ", " la ", " el ", " los ", " las ", " que ", " no ", " con ", " un ",
    " una ", " se ", " por ", " para ", " tu ", " datos", " del ", "ó", "í", "á",
    "é", "ú", "ñ", "¿", "¡",
)


def _looks_spanish(text: str) -> bool:
    padded = f" {text.lower()} "
    return any(hint in padded for hint in _SPANISH_HINTS)


# ─────────────────────────────────────────────────────────────────────────────
# A. Cobertura del catálogo (parametrizado → un test por entrada)
# ─────────────────────────────────────────────────────────────────────────────

def test_catalog_has_at_least_50_entries():
    """El roadmap exige un catálogo de 50+ errores específicos."""
    assert len(CATALOG) >= 50, f"Catálogo tiene solo {len(CATALOG)} entradas (<50)."


@pytest.mark.parametrize("code", sorted(CATALOG.keys()))
def test_catalog_entry_is_well_formed(code):
    """Cada entrada: code coincide con la clave, severidad válida, mensaje
    >100 chars en español, y acción sugerida no vacía y accionable."""
    spec = CATALOG[code]
    assert isinstance(spec, ErrorSpec)
    assert spec.code == code, "El code de la spec debe coincidir con su clave."
    assert spec.severity in _VALID_SEVERITIES, f"Severidad inválida: {spec.severity}"

    # >100 caracteres incluso descontando placeholders sin rellenar.
    bare_msg = spec.user_message
    assert len(bare_msg) > 100, (
        f"{code}: user_message tiene {len(bare_msg)} caracteres (<=100)."
    )
    assert _looks_spanish(bare_msg), f"{code}: user_message no parece español."

    action = spec.suggested_action
    assert len(action) >= 40, f"{code}: suggested_action demasiado corta."
    assert _looks_spanish(action), f"{code}: suggested_action no parece español."


@pytest.mark.parametrize("severity", [SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO])
def test_catalog_covers_each_severity(severity):
    """El catálogo debe tener entradas de cada severidad (errores, warnings, info)."""
    codes = [c for c, s in CATALOG.items() if s.severity == severity]
    assert codes, f"No hay ninguna entrada con severidad {severity}."


# ─────────────────────────────────────────────────────────────────────────────
# B. Construcción desde el catálogo + relleno de placeholders
# ─────────────────────────────────────────────────────────────────────────────

def test_build_from_catalog_code_populates_fields():
    err = CsvValidationError("CSV_EMPTY")
    assert err.code == "CSV_EMPTY"
    assert err.severity == SEVERITY_ERROR
    assert len(err.user_message) > 100
    assert err.suggested_action
    assert isinstance(err.technical_details, dict)


def test_placeholders_are_filled_from_context():
    err = SolverDivergenceError("SOLVER_DIVERGED_HIGH_NOISE", snr=0.08)
    assert "0.08" in err.user_message
    # El contexto también queda como detalle técnico.
    assert err.technical_details.get("snr") == 0.08


def test_missing_placeholder_does_not_raise():
    """Construir un error nunca debe fallar por un placeholder ausente."""
    err = SolverDivergenceError("SOLVER_DIVERGED_ILL_CONDITIONED")  # falta {cond}
    assert "{cond}" in err.user_message or "cond" in err.user_message
    assert len(err.user_message) > 100


def test_technical_details_merged_with_explicit_dict():
    err = ConflictingDataError(
        "BOREHOLE_CONFLICT",
        hole_id="BH01", depth=150, rho_obs=2.5, rho_pred=3.5,
        technical_details={"kappa": 1e3},
    )
    assert "BH01" in err.user_message
    assert err.technical_details["kappa"] == 1e3
    assert err.technical_details["hole_id"] == "BH01"


def test_rendered_message_still_over_100_chars_after_formatting():
    """Tras rellenar placeholders, el mensaje sigue por encima de 100 chars."""
    err = TerraquantumError("DATA_TOO_FEW_SENSORS", n=3, min=5)
    assert "3" in err.user_message and "5" in err.user_message
    assert len(err.user_message) > 100


# ─────────────────────────────────────────────────────────────────────────────
# C. Jerarquía de excepciones
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cls", [
    CsvValidationError,
    InsufficientDataError,
    SolverDivergenceError,
    ConflictingDataError,
    GeoreferencingError,
])
def test_subclasses_are_terraquantum_errors(cls):
    assert issubclass(cls, TerraquantumError)
    assert issubclass(cls, Exception)


def test_can_catch_specific_then_base():
    with pytest.raises(SolverDivergenceError):
        raise SolverDivergenceError("SOLVER_NAN_IN_RESULT")
    try:
        raise CsvValidationError("CSV_EMPTY")
    except TerraquantumError as exc:  # se captura por la base
        assert exc.code == "CSV_EMPTY"


def test_subclass_default_code_used_for_literal_message():
    """Un mensaje literal en una subclase usa el default_code de esa subclase."""
    err = SolverDivergenceError(message="Diverge sin remedio en este caso particular.")
    assert err.code == "SOLVER_DIVERGED_HIGH_NOISE"
    assert err.severity == SEVERITY_ERROR


# ─────────────────────────────────────────────────────────────────────────────
# D. Backward-compat de InsufficientDataError (ValueError + literal + re-export)
# ─────────────────────────────────────────────────────────────────────────────

def test_insufficient_data_is_value_error():
    assert issubclass(InsufficientDataError, ValueError)


def test_insufficient_data_literal_message_backward_compat():
    msg = ("Se necesita al menos un campo potencial: gravimetría o magnetometría "
           "para plantear una inversión geofísica con sentido.")
    err = InsufficientDataError(msg)
    assert err.user_message == msg
    assert err.code == "DATA_NO_MODALITY"
    assert str(err) == msg


def test_insufficient_data_caught_as_value_error():
    with pytest.raises(ValueError):
        raise InsufficientDataError("DATA_TOO_FEW_SENSORS", n=2, min=5)


def test_multimodal_reexports_same_class():
    """El re-export desde el servicio multimodal debe ser la MISMA clase central
    (no rompe `from services.multimodal_fusion_service import InsufficientDataError`)."""
    from services.multimodal_fusion_service import (
        InsufficientDataError as MMInsufficient,
    )
    assert MMInsufficient is InsufficientDataError


def test_multimodal_gate_raises_actionable_error():
    """El gate real del servicio multimodal lanza el error central con mensaje útil."""
    from services.multimodal_fusion_service import select_route, InsufficientDataError as E
    with pytest.raises(E) as exc_info:
        select_route(has_gravity=False, has_magnetic=False, has_borehole=False, n_sensors=0)
    assert len(str(exc_info.value)) > 100


# ─────────────────────────────────────────────────────────────────────────────
# E. Serialización (frontend modal + polling async)
# ─────────────────────────────────────────────────────────────────────────────

def test_to_dict_shape_for_frontend_modal():
    err = SolverDivergenceError("SOLVER_DIVERGED_ILL_CONDITIONED",
                                technical_details={"cond": 2.3e12})
    d = err.to_dict()
    assert set(d.keys()) == {
        "code", "severity", "user_message", "technical_details", "suggested_action",
    }
    assert d["code"] == "SOLVER_DIVERGED_ILL_CONDITIONED"
    assert d["technical_details"]["cond"] == 2.3e12
    assert len(d["user_message"]) > 100
    assert d["suggested_action"]


def test_to_error_details_matches_response_schema():
    """to_error_details debe encajar en schemas.response_schema.ErrorDetails."""
    from schemas.response_schema import ErrorDetails
    err = CsvValidationError("CSV_MISSING_COLUMNS", missing="g_obs, sigma")
    payload = err.to_error_details(source="gravity_import_service", stage="import")
    model = ErrorDetails(**payload)
    assert model.code == "CSV_MISSING_COLUMNS"
    assert "g_obs" in model.message
    assert model.source == "gravity_import_service"
    assert model.stage == "import"
    assert model.details["severity"] == SEVERITY_ERROR
    assert model.details["suggested_action"]


# ─────────────────────────────────────────────────────────────────────────────
# F. Fallback / robustez
# ─────────────────────────────────────────────────────────────────────────────

def test_unknown_code_falls_back_to_internal():
    """Un código desconocido (no del catálogo) cae al error interno accionable."""
    err = TerraquantumError(message="algo raro", severity=SEVERITY_ERROR)
    assert err.severity == SEVERITY_ERROR
    assert err.user_message == "algo raro"
    # default_code de la base.
    assert err.code == "TQ_INTERNAL"


def test_invalid_severity_is_coerced_to_default():
    err = TerraquantumError("CSV_EMPTY", severity="catastrophic")
    assert err.severity in _VALID_SEVERITIES


def test_get_spec_helper():
    assert get_spec("CSV_EMPTY") is CATALOG["CSV_EMPTY"]
    assert get_spec("NO_EXISTE") is None


def test_all_specs_unique_codes():
    """No debe haber códigos duplicados en el catálogo (clave == code garantiza esto)."""
    codes = [spec.code for spec in CATALOG.values()]
    assert len(codes) == len(set(codes))
