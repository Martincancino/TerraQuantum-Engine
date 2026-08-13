"""Fase 3 — el gate de física distingue "no hay dato" de "la física regresionó".

**El problema.** H-4 pedía meter la regresión física de F9 en la CI. Al medirlo
aparecieron dos cosas que el hallazgo no decía:

1. Los 8 tests `validation` llevan **también** el marcador `slow`, así que el
   filtro `-m "not slow"` de la CI los deselecciona *antes* de que el skip de
   `conftest` entre en juego: poner `TQ_RUN_VALIDATION=1` en el job existente no
   habría ejecutado nada.
2. De los 6 casos del gate, **DO-27 y Raglan están versionados** (110,8 MB y
   7,8 MB rastreados) pero **San Nicolás y LdM no**: viven bajo `data/projects/`,
   que `.gitignore` excluye. En un checkout limpio no existen.

Si un dato ausente cuenta como FALLO, el nightly nace rojo por una razón que no
es física — y un gate que está rojo por costumbre deja de leerse. Si cuenta como
PASS, el veredicto miente. La salida es no mentir en ninguna de las dos
direcciones: **el veredicto habla de lo evaluado y el reporte dice qué no se
evaluó.**

Estos tests no invierten nada: sustituyen los casos por funciones falsas y
comprueban la contabilidad, que es lo que decide el color de la CI.
"""
from __future__ import annotations

import pytest

from scripts.validation import f9_regression_lib as F9


def _fake_case(name: str, *, passed: bool = True):
    def fn():
        return F9._case(name, name, "—", "métrica", 1.0, "", "tol", passed)

    fn.__name__ = name
    return fn


def _fake_missing(name: str):
    def fn():
        raise F9.DatosNoVersionados(f"faltan las observaciones de {name}")

    fn.__name__ = name
    return fn


def test_missing_field_data_is_not_a_physics_failure(monkeypatch):
    """San Nicolás y LdM ausentes: PASS sobre lo evaluado, y se dice cuáles no."""
    monkeypatch.setattr(
        F9,
        "ALL_CASES",
        [
            _fake_case("case_synthetic_sphere"),
            _fake_case("case_do27"),
            _fake_case("case_raglan"),
            _fake_missing("case_san_nicolas"),
            _fake_missing("case_ldm"),
        ],
    )
    report = F9.run_all(generated_utc="test")

    assert report["verdict"] == "PASS"
    assert report["n_total"] == 3, "el denominador cuenta lo EVALUADO, no lo intentado"
    assert report["n_pass"] == 3
    assert report["n_skipped"] == 2
    assert set(report["skipped_keys"]) == {"case_san_nicolas", "case_ldm"}


def test_missing_data_of_a_versioned_dataset_is_a_failure(monkeypatch):
    """DO-27 sí está en el repositorio: si falta, el repositorio está roto."""
    monkeypatch.setattr(
        F9,
        "ALL_CASES",
        [_fake_case("case_synthetic_sphere"), _fake_missing("case_do27")],
    )
    report = F9.run_all(generated_utc="test")

    assert report["verdict"] == "FALLO", (
        "Un dataset versionado que desaparece no puede degradarse a 'no "
        "evaluado': sería la puerta trasera para apagar el gate borrando datos."
    )
    assert report["n_skipped"] == 0


def test_a_real_physics_failure_still_fails(monkeypatch):
    """La degradación tiene que seguir poniendo el gate en rojo."""
    monkeypatch.setattr(
        F9,
        "ALL_CASES",
        [
            _fake_case("case_synthetic_sphere", passed=False),
            _fake_missing("case_ldm"),
        ],
    )
    report = F9.run_all(generated_utc="test")

    assert report["verdict"] == "FALLO"
    assert report["n_pass"] == 0
    assert report["n_total"] == 1
    assert report["n_skipped"] == 1


def test_everything_present_behaves_exactly_as_before(monkeypatch):
    """Sin datos ausentes, el contrato del reporte es el de siempre."""
    monkeypatch.setattr(
        F9,
        "ALL_CASES",
        [_fake_case("case_synthetic_sphere"), _fake_case("case_do27")],
    )
    report = F9.run_all(generated_utc="test")

    assert report["verdict"] == "PASS"
    assert (report["n_pass"], report["n_total"], report["n_skipped"]) == (2, 2, 0)


def test_field_rerun_raises_the_typed_error_when_data_is_absent():
    """La señal nace donde se lee el disco, no en un `except` genérico."""
    with pytest.raises(F9.DatosNoVersionados) as exc:
        F9._field_rerun("proyecto_que_no_existe", "corrida_que_no_existe", auto_lambda=False)
    assert "faltan las observaciones" in str(exc.value)


# ── Las fixtures que permiten a la CI evaluar los 6 casos ─────────────────────

@pytest.mark.parametrize(
    "pid,rid",
    [("val_san_nicolas", "a407c45e6d"), ("val_ldm", "ldm_v2_lam3p0")],
)
def test_field_fixtures_are_versioned_and_identical_to_the_canonical_run(pid, rid):
    """Sin estas fixtures la CI defendía 4 de 6 casos.

    Y tienen que ser LAS MISMAS observaciones: una fixture que se desvía de la
    corrida canónica convertiría el gate en una regresión contra sí misma.
    """
    import json

    fixture = F9.BACKEND / "tests" / "fixtures" / "f9" / pid / rid
    assert (fixture / "observations.json").is_file(), f"falta la fixture de {pid}"
    assert (fixture / "inputs.json").is_file()

    viva = F9.BACKEND / "data" / "projects" / pid / "runs" / rid
    if not (viva / "observations.json").is_file():
        pytest.skip("la corrida viva no está en esta máquina; nada que comparar")
    for nombre in ("observations.json", "inputs.json"):
        assert json.loads((fixture / nombre).read_text(encoding="utf-8")) == json.loads(
            (viva / nombre).read_text(encoding="utf-8")
        ), f"la fixture {pid}/{nombre} se desvió de la corrida canónica"


def test_the_live_run_wins_over_the_fixture(tmp_path, monkeypatch):
    """En la máquina de desarrollo se mide el artefacto canónico, no la copia."""
    monkeypatch.setattr(F9, "BACKEND", tmp_path)
    viva = tmp_path / "data" / "projects" / "p" / "runs" / "r"
    fixture = tmp_path / "tests" / "fixtures" / "f9" / "p" / "r"
    for carpeta in (viva, fixture):
        carpeta.mkdir(parents=True)
        (carpeta / "observations.json").write_text("[]", encoding="utf-8")
        (carpeta / "inputs.json").write_text("{}", encoding="utf-8")

    assert F9._resolve_field_run("p", "r") == viva


def test_the_fixture_is_used_when_the_live_run_is_absent(tmp_path, monkeypatch):
    """El caso de la CI: checkout limpio, sin data/projects/."""
    monkeypatch.setattr(F9, "BACKEND", tmp_path)
    fixture = tmp_path / "tests" / "fixtures" / "f9" / "p" / "r"
    fixture.mkdir(parents=True)
    (fixture / "observations.json").write_text("[]", encoding="utf-8")
    (fixture / "inputs.json").write_text("{}", encoding="utf-8")

    assert F9._resolve_field_run("p", "r") == fixture


def test_the_html_report_says_not_evaluated_instead_of_failed():
    """El material de credibilidad no puede enseñar FALLO donde faltó un dato."""
    from scripts.validation.f9_report import render_html

    report = {
        "suite": "F9",
        "title": "t",
        "generated_utc": "test",
        "verdict": "PASS",
        "n_pass": 1,
        "n_total": 1,
        "n_skipped": 1,
        "skipped_keys": ["case_ldm"],
        "elapsed_s": 1.0,
        "cases": [
            F9._case("case_synthetic_sphere", "Sintético", "—", "m", 1.0, "", "tol", True),
            {**F9._case("case_ldm", "LdM", "—", "no evaluado", None, "", "—", True),
             "skipped": True},
        ],
    }
    html = render_html(report)
    assert "NO EVALUADO" in html
    assert "FALLO" not in html.split("case_ldm")[-1][:400]
