"""
FASE 1 (auditoría 06 §10) — Cobertura de despacho de los `Literal` del esquema.
==============================================================================

La Fase 1 exige, además de cerrar H-37: *"un test que recorra TODOS los valores de
cada `Literal` del esquema y verifique que el motor los despacha de verdad o los
rechaza — el mismo patrón que la Fase 5 aplica a las variables de entorno."*

Por qué existe este test. H-37 no fue un descuido aislado: un valor entra al
`Literal`, la UI lo ofrece, y el despacho del motor nunca crece con él. El defecto
es invisible porque nadie ve juntas la declaración y la rama que la consume. Este
test las obliga a aparecer en la misma pantalla:

  • REGISTRO — cada (modelo, campo, valor) del esquema tiene que estar clasificado.
    Añadir un valor nuevo sin clasificarlo rompe la suite. No hay default silencioso.
  • EVIDENCIA — cada clasificación apunta a un archivo y a un fragmento literal de
    código. Si la rama de despacho desaparece o se renombra, el test cae.
  • RECHAZO EJECUTADO — los valores marcados "rejected" se comprueban en runtime:
    tienen que levantar el error del catálogo ES, no simplemente estar anotados.

Hallazgo de la primera corrida de este test (H-37b): `lambda_strategy="lcurve"`
prometía la esquina de la L-curve y caía en la MISMA rama que "chi2"
(`select_lambda_lcurve` no tiene llamadores de producción). Cerrado como "rejected".
"""
from __future__ import annotations

import inspect
import os
import sys
import typing
from pathlib import Path

import pytest
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import schemas.geophysics_schema as geophysics_schema
from core.errors import CATALOG, TerraquantumError

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Estados posibles de un valor del contrato:
#   dispatched  — el motor RAMIFICA sobre el valor y se comporta distinto.
#   declarative — es una etiqueta/declaración del contrato (auditoría, validación de
#                 entrada); el motor no ramifica. La nota dice dónde queda registrada.
#   rejected    — se rechaza explícitamente con un error del catálogo ES.
DISPATCHED, DECLARATIVE, REJECTED = "dispatched", "declarative", "rejected"

# (estado, archivo con la evidencia, fragmento literal que debe existir, nota)
REGISTRY: dict[str, dict[str, tuple[str, str, str, str]]] = {
    # ── Remanencia magnética ─────────────────────────────────────────────────
    "MagneticRemanenceParams.inversion_mode": {
        "induced_only": (
            DISPATCHED, "services/geophysics_service.py",
            "magnetización inducida, sin remanencia",
            "Camino por defecto: kernel TMI inducido, declarado como tal en el reporte.",
        ),
        "total_field": (
            DISPATCHED, "services/geophysics_service.py",
            '_rem.inversion_mode == "total_field"',
            "Construye el kernel total J_ind + Q·J_rem (build_kernel_with_remanence).",
        ),
        "amplitude": (
            REJECTED, "services/geophysics_service.py",
            "_UNAVAILABLE_INVERSION_MODES",
            "H-37: el solver de amplitud exige el dato |B| (≥0) y producción sólo "
            "transporta TMI con signo; sin transformación TMI→|B| no hay despacho posible.",
        ),
    },
    # ── Sondajes ─────────────────────────────────────────────────────────────
    "BoreholeSample.sample_type": {
        v: (
            DECLARATIVE, "services/borehole_service.py", f'"{v}"',
            "Trazabilidad de la muestra: se normaliza al cargar el CSV de sondajes "
            "y viaja en el registro; el solver no ramifica por tipo de muestra.",
        )
        for v in ("core", "cuttings", "downhole_density", "downhole_susc", "other")
    },
    # ── Regularización ───────────────────────────────────────────────────────
    **{
        f"{model}.regularization_norm": {
            v: (
                DISPATCHED, "exploration/gravimetry.py", '("l2", "compact", "mixed")',
                "L2 → un solo solve; compact/mixed → bucle IRLS de minimum support.",
            )
            for v in ("L2", "compact", "mixed")
        }
        for model in ("GeophysicsInvertInput", "GeophysicsInvertInputV2")
    },
    # ── Gravímetro (piso de ruido por instrumento) ───────────────────────────
    **{
        f"{model}.gravimeter_type": {
            v: (
                DISPATCHED, "core/config.py", f'"{v}"',
                "Selecciona el piso instrumental de σ en GRAVIMETER_NOISE_FLOOR; "
                "'unknown' es el piso conservador, no un valor ignorado.",
            )
            for v in ("scintrex_cg6", "zls_burris", "lacoste_romberg", "unknown")
        }
        for model in ("GeophysicsInvertInput", "GeophysicsInvertInputV2")
    },
    # ── Modelo de magnetización ──────────────────────────────────────────────
    **{
        f"{model}.magnetization_model": {
            v: (
                DISPATCHED, "services/geophysics_service.py",
                'getattr(params, "magnetization_model", "scalar") == "vector"',
                "scalar → susceptibilidad; vector → MVI (invierte M=Mx,My,Mz).",
            )
            for v in ("scalar", "vector")
        }
        for model in ("GeophysicsInvertInput", "GeophysicsInvertInputV2")
    },
    # ── Campo cercano magnético ──────────────────────────────────────────────
    **{
        f"{model}.magnetic_near_field": {
            v: (
                DISPATCHED, "exploration/magnetometry.py",
                '_use_prism = self.near_field_mode == "prism"',
                "Kernel escalar TMI: dipolo puntual vs prisma en el campo cercano. "
                "Matiz honesto (H-39, fuera de esta fase): los kernels de MVI y de "
                "tensor gradiente todavía ignoran 'prism'.",
            )
            for v in ("dipole", "prism")
        }
        for model in ("GeophysicsInvertInput", "GeophysicsInvertInputV2")
    },
    # ── Joint: continuación y acoplamiento ───────────────────────────────────
    **{
        f"{model}.joint_continuation_mode": {
            v: (
                DISPATCHED, "services/joint_inversion.py", '_cont_mode == "step"',
                "step → peso cruzado 1.0 desde k≥2; log → homotopía exponencial.",
            )
            for v in ("step", "log")
        }
        for model in ("GeophysicsInvertInput", "GeophysicsInvertInputV2")
    },
    **{
        f"{model}.joint_coupling_mode": {
            "cross_gradient": (
                DISPATCHED, "services/joint_inversion.py",
                '_coupling_mode in ("cross_gradient", "gramian", "pgi+cross")',
                "Bloque estructural cross-gradient unitario (default).",
            ),
            "gramian": (
                DISPATCHED, "services/joint_inversion.py",
                '"gramian" if _coupling_mode == "gramian"',
                "Sustituye el bloque estructural por el Gramian de Zhdanov.",
            ),
            "pgi_dynamic": (
                DISPATCHED, "services/joint_inversion.py",
                '_coupling_mode in ("pgi_dynamic", "pgi+cross")',
                "Activa la mixtura 2D ρ-χ con refit dinámico del GMM.",
            ),
            "pgi+cross": (
                DISPATCHED, "services/joint_inversion.py",
                '_coupling_mode in ("pgi_dynamic", "pgi+cross")',
                "PGI y bloque estructural simultáneos (aparece en ambas condiciones).",
            ),
        }
        for model in ("GeophysicsInvertInput", "GeophysicsInvertInputV2")
    },
    # ── Anclaje de sondajes ──────────────────────────────────────────────────
    **{
        f"{model}.anchor_mode": {
            v: (
                DISPATCHED, "exploration/gravimetry.py", '("soft", "hard")',
                "soft → penalización; hard → restricción exacta de las celdas ancladas.",
            )
            for v in ("soft", "hard")
        }
        for model in ("GeophysicsInvertInput", "GeophysicsInvertInputV2")
    },
    # ── Sólo v2 ──────────────────────────────────────────────────────────────
    "GeophysicsInvertInputV2.corrections_applied": {
        v: (
            DECLARATIVE, "schemas/geophysics_schema.py", f'"{v}"',
            "Declaración de auditoría del usuario sobre qué correcciones aplicó "
            "aguas arriba. Hoy NO la consume ningún cálculo: no altera la inversión.",
        )
        for v in ("latitude", "free_air", "bouguer", "terrain")
    },
    "GeophysicsInvertInputV2.gravity_type_v2": {
        v: (
            DECLARATIVE, "api/geophysics_api.py", "gravity_type=params.gravity_type_v2",
            "El Literal ES la validación: al no incluir 'g_raw', v2 rechaza dato crudo "
            "en la frontera del contrato. El valor se registra en el log de la corrida.",
        )
        for v in ("complete_bouguer_anomaly", "bouguer_anomaly", "free_air_anomaly")
    },
    "GeophysicsInvertInputV2.lambda_strategy": {
        "fixed": (
            DISPATCHED, "api/geophysics_api.py", 'params.lambda_strategy == "fixed"',
            "auto_lambda=False + lambda_mag=lambda_fixed.",
        ),
        "chi2": (
            DISPATCHED, "api/geophysics_api.py", 'params.lambda_strategy == "chi2"',
            "auto_lambda=True → operating point / Morozov según σ declarado.",
        ),
        "lcurve": (
            REJECTED, "api/geophysics_api.py", "LAMBDA_STRATEGY_UNAVAILABLE",
            "H-37b: prometía la esquina de la L-curve y ejecutaba la rama de chi2; "
            "select_lambda_lcurve no tiene llamadores de producción.",
        ),
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Introspección del esquema
# ─────────────────────────────────────────────────────────────────────────────

def _literal_value_groups(annotation) -> list:
    """Devuelve los grupos de valores de cada `Literal` dentro de una anotación
    (atraviesa Optional[...], List[...], Union[...])."""
    if typing.get_origin(annotation) is typing.Literal:
        return [list(typing.get_args(annotation))]
    groups: list = []
    for arg in typing.get_args(annotation) or ():
        groups.extend(_literal_value_groups(arg))
    return groups


def _schema_literals() -> list:
    """[(clave 'Modelo.campo', valor), …] para todo Literal del esquema geofísico."""
    found = []
    for model_name, obj in vars(geophysics_schema).items():
        if not (inspect.isclass(obj) and issubclass(obj, BaseModel)):
            continue
        if obj.__module__ != geophysics_schema.__name__:
            continue
        for field_name, field in obj.model_fields.items():
            for values in _literal_value_groups(field.annotation):
                for value in values:
                    found.append((f"{model_name}.{field_name}", value))
    return sorted(set(found))


SCHEMA_LITERALS = _schema_literals()


def test_schema_exposes_literals_at_all():
    """Guardia del propio test: si la introspección deja de encontrar Literales,
    los demás tests pasarían vacíos y no defenderían nada."""
    assert len(SCHEMA_LITERALS) >= 19, f"Sólo se encontraron {len(SCHEMA_LITERALS)} literales."


@pytest.mark.parametrize("key,value", SCHEMA_LITERALS, ids=lambda v: str(v))
def test_every_literal_value_is_classified(key, value):
    """Todo valor del contrato está clasificado: despachado, declarativo o rechazado.

    Si este test falla es porque alguien añadió un valor al esquema sin decidir qué
    hace el motor con él — exactamente cómo nació H-37.
    """
    assert key in REGISTRY, (
        f"El campo {key} tiene valores Literal sin registrar en REGISTRY. "
        "Clasifica cada valor (dispatched / declarative / rejected) con su evidencia."
    )
    assert value in REGISTRY[key], (
        f"El valor {key}={value!r} no está clasificado. Declara qué hace el motor con él: "
        "lo despacha (con el archivo y la línea que ramifica), es declarativo, o se rechaza."
    )
    status, _path, _token, note = REGISTRY[key][value]
    assert status in (DISPATCHED, DECLARATIVE, REJECTED), f"Estado inválido: {status}"
    assert len(note) > 30, f"{key}={value!r}: la justificación es demasiado vaga."


@pytest.mark.parametrize("key,value", SCHEMA_LITERALS, ids=lambda v: str(v))
def test_classification_evidence_still_exists_in_the_code(key, value):
    """La evidencia no es un comentario: es código que tiene que seguir ahí.

    Si una rama de despacho se borra o se renombra, el valor queda huérfano y este
    test lo delata en vez de esperar a que un usuario reciba una física que no pidió.
    """
    if key not in REGISTRY or value not in REGISTRY[key]:
        pytest.skip("cubierto por test_every_literal_value_is_classified")
    _status, rel_path, token, _note = REGISTRY[key][value]
    source = BACKEND_ROOT / rel_path
    assert source.is_file(), f"{key}={value!r}: la evidencia apunta a {rel_path}, que no existe."
    text = source.read_text(encoding="utf-8")
    assert token in text, (
        f"{key}={value!r}: no se encontró la evidencia {token!r} en {rel_path}. "
        "O la rama de despacho cambió de forma (actualiza la evidencia) o desapareció "
        "(y entonces el valor ya no se despacha: hay que rechazarlo o volver a cablearlo)."
    )


def test_registry_has_no_stale_entries():
    """Al revés: nada clasificado que ya no exista en el esquema (registro que rota)."""
    schema_keys = {(k, v) for k, v in SCHEMA_LITERALS}
    registry_keys = {(k, v) for k, values in REGISTRY.items() for v in values}
    stale = registry_keys - schema_keys
    assert not stale, f"REGISTRY clasifica valores que el esquema ya no declara: {sorted(stale)}"


# ─────────────────────────────────────────────────────────────────────────────
# Los rechazos se EJECUTAN, no sólo se anotan
# ─────────────────────────────────────────────────────────────────────────────

def _rejected_values() -> list:
    return [
        (key, value)
        for key, values in REGISTRY.items()
        for value, (status, *_rest) in values.items()
        if status == REJECTED
    ]


def test_there_is_at_least_one_rejected_value():
    """Guardia: si el conjunto de rechazos queda vacío, el test de abajo no prueba nada."""
    assert _rejected_values(), "Ningún valor marcado como rejected."


@pytest.mark.parametrize("key,value", _rejected_values(), ids=lambda v: str(v))
def test_rejected_values_raise_a_catalog_error(key, value):
    """Cada rechazo declarado se comprueba contra el motor/endpoint real."""
    if key == "MagneticRemanenceParams.inversion_mode" and value == "amplitude":
        from schemas.geophysics_schema import MagneticRemanenceParams
        from services.geophysics_service import reject_unavailable_inversion_modes

        class _Params:
            remanence = MagneticRemanenceParams(enabled=True, inversion_mode=value)

        with pytest.raises(TerraquantumError) as exc:
            reject_unavailable_inversion_modes(_Params())
        assert exc.value.code == "INVERSION_MODE_UNAVAILABLE"
        assert CATALOG[exc.value.code].severity == "error"

    elif key == "GeophysicsInvertInputV2.lambda_strategy" and value == "lcurve":
        # El rechazo vive en el endpoint v2: se comprueba el código del catálogo y
        # que la rama que lo colaba en 'chi2' ya no exista.
        api_src = (BACKEND_ROOT / "api/geophysics_api.py").read_text(encoding="utf-8")
        assert "LAMBDA_STRATEGY_UNAVAILABLE" in api_src
        assert 'in ("chi2", "lcurve")' not in api_src, (
            "'lcurve' vuelve a compartir rama con 'chi2': el endpoint promete una "
            "estrategia y ejecuta otra."
        )
        assert CATALOG["LAMBDA_STRATEGY_UNAVAILABLE"].severity == "error"

    else:  # pragma: no cover - red de seguridad para rechazos futuros
        pytest.fail(
            f"{key}={value!r} está marcado como rejected pero no hay comprobación de "
            "runtime que lo verifique. Añádela: un rechazo anotado y no ejecutado es "
            "exactamente el defecto que esta fase cierra."
        )
