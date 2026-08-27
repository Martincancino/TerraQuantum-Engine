"""
FASE 19 — La guardia que compara la convención de la INGESTA con la del MOTOR.

Este fichero existe por una razón concreta, escrita en
``docs/11_CONVENCION_DE_EJES.md`` §6: **el defecto real de ACAD-1 no era la
permutación ausente, sino que nada en el árbol comparaba las dos convenciones.**
La Fase 18 lo midió con un experimento (``scripts/validation/
fase18_axis_convention_experiment.py``, tramos B1 y D); la Fase 19 lo convierte
en test, que es lo único que impide que vuelva.

El criterio NO puede ser leer un comentario. Cada test de aquí:
  1. mete un CSV con easting y northing DISTINGUIBLES por la puerta del usuario,
  2. comprueba en qué slot cae cada uno, y
  3. comprueba contra qué componente de ``f̂`` se multiplica ese slot,
     contrastándolo con una referencia geográfica INDEPENDIENTE.

Convención canónica (``docs/11_CONVENCION_DE_EJES.md`` §1):

    x_m / eje 0 = ESTE      y_m / eje 1 = PROFUNDIDAD (+abajo)      z_m / eje 2 = NORTE

Dos trampas deliberadas, las dos medidas por la Fase 18 y las dos necesarias:

  · **La malla de estaciones es asimétrica (21 × 13).** Con una malla cuadrada un
    intercambio de ejes es INVISIBLE. Es la misma lección que el gate del ZIP.
  · **La declinación es 2°, el defecto de producción de Chile.** Con D = 45° el
    defecto de ACAD-1 es EXACTAMENTE cero (medido: 1,9·10⁻¹³ nT), así que un
    test escrito a 45° no defendería nada. ``test_una_declinacion_de_45_grados_
    no_serviria_de_gate`` deja eso pinchado para que nadie "simplifique" el caso.
"""

from __future__ import annotations

import csv
import math
import tempfile
from pathlib import Path

import numpy as np
import pytest

from exploration.magnetometry import MagnetometryForward, field_unit_vector

# ── Sitio: los defaults de producción (schemas/geophysics_schema.py). Chile es el
#    PEOR caso del rango — índice de ceguera √2·cosI·|sinD − cosD| = 1,18 — y es el
#    caso de uso declarado del producto.
INC_CHILE, DEC_CHILE = -30.0, 2.0
B0_NT = 23500.0

# Malla de estaciones DELIBERADAMENTE asimétrica: spans 1200 m (E) × 720 m (N).
N_EAST, N_NORTH, SPACING = 21, 13, 60.0
UTM_E0, UTM_N0 = 380_000.0, 7_400_000.0

KAPPA, DEPTH, CELL = 0.30, 220.0, 50.0
BODY_OFFSET_N, BODY_OFFSET_E = 120.0, -90.0


# ──────────────────────────────────────────────────────────────────────────────
# Referencia INDEPENDIENTE: el dipolo TMI escrito en coordenadas geográficas.
# No llama a `field_unit_vector`. Si lo llamara, el test sería tautológico — el
# vicio exacto que la Fase 17 encontró en 7 tests de este repositorio.
# ──────────────────────────────────────────────────────────────────────────────
def _f_hat_geografico(inclinacion_deg: float, declinacion_deg: float) -> np.ndarray:
    """f̂ en el marco (Norte, Este, Abajo), escrito a mano desde la definición."""
    i = math.radians(float(inclinacion_deg))
    d = math.radians(float(declinacion_deg))
    return np.array([
        math.cos(i) * math.cos(d),   # Norte
        math.cos(i) * math.sin(d),   # Este
        math.sin(i),                 # Abajo (+)
    ], dtype=np.float64)


def _tmi_verdadera(st_n, st_e, cuerpo_n, cuerpo_e, cuerpo_prof,
                   inclinacion_deg, declinacion_deg, kappa, volumen_m3):
    """ΔT = κ·(B0·V/4π)·[3(f̂·r̂)² − 1]/r³ (Blakely 1995, cap. 5), en (N, E, Abajo).

    Sensores en superficie (profundidad 0). μ0 cancela al proyectar sobre el campo
    ambiente, igual que en el motor.
    """
    f = _f_hat_geografico(inclinacion_deg, declinacion_deg)
    d_n = np.asarray(cuerpo_n, dtype=float) - np.asarray(st_n, dtype=float)
    d_e = np.asarray(cuerpo_e, dtype=float) - np.asarray(st_e, dtype=float)
    d_d = float(cuerpo_prof)
    r2 = d_n ** 2 + d_e ** 2 + d_d ** 2
    f_dot_r = f[0] * d_n + f[1] * d_e + f[2] * d_d
    c = B0_NT * float(volumen_m3) / (4.0 * math.pi)
    return float(kappa) * c * (3.0 * f_dot_r ** 2 - r2) / r2 ** 2.5


# ──────────────────────────────────────────────────────────────────────────────
# Geometría compartida
# ──────────────────────────────────────────────────────────────────────────────
def _estaciones():
    eje_e = np.arange(N_EAST) * SPACING
    eje_n = np.arange(N_NORTH) * SPACING
    malla_n, malla_e = np.meshgrid(eje_n, eje_e, indexing="ij")
    return malla_n.ravel(), malla_e.ravel(), eje_n, eje_e


def _esquinas_del_cuerpo(eje_n, eje_e):
    """Cubo de 100 m representado por 8 dipolos de celda de 50 m."""
    cuerpo_n = float(eje_n.mean() + BODY_OFFSET_N)
    cuerpo_e = float(eje_e.mean() + BODY_OFFSET_E)
    return cuerpo_n, cuerpo_e, [
        (cuerpo_n + dn, cuerpo_e + de, DEPTH + dd)
        for dn in (-CELL / 2, CELL / 2)
        for de in (-CELL / 2, CELL / 2)
        for dd in (-CELL / 2, CELL / 2)
    ]


def _escribir_csv_magnetico(path, este_utm, norte_utm, tmi_nt, cota=2500.0):
    """CSV con las cabeceras en español del corpus real: el auto-mapeo sin ayuda."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["estacion", "este_utm", "norte_utm", "cota_msnm", "tmi_nt"])
        for i, (e, n, t) in enumerate(zip(este_utm, norte_utm, tmi_nt), start=1):
            w.writerow([f"ST{i:04d}", f"{e:.3f}", f"{n:.3f}", f"{cota:.2f}", f"{t:.6f}"])


@pytest.fixture(scope="module")
def ingesta():
    """Un CSV magnético REAL pasado por ``import_gravity_csv_v1``.

    Es la puerta del usuario: alias en español, auto-mapeo, UTM → frame local.
    Devuelve las observaciones y lo que el CSV llevaba, para poder comparar.
    """
    from services.gravity_import_service import import_gravity_csv_v1

    st_n, st_e, eje_n, eje_e = _estaciones()
    cuerpo_n, cuerpo_e, esquinas = _esquinas_del_cuerpo(eje_n, eje_e)
    volumen = CELL ** 3

    verdad = np.zeros_like(st_n)
    for (b_n, b_e, b_d) in esquinas:
        verdad = verdad + _tmi_verdadera(st_n, st_e, b_n, b_e, b_d,
                                         INC_CHILE, DEC_CHILE, KAPPA, volumen)

    tmpdir = Path(tempfile.mkdtemp(prefix="fase19_ejes_"))
    csv_path = tmpdir / "fase19_chile.csv"
    _escribir_csv_magnetico(csv_path, st_e + UTM_E0, st_n + UTM_N0, verdad)

    resultado = import_gravity_csv_v1(
        str(csv_path), strict=False, allow_g_raw=False, data_kind="magnetic")
    assert str(resultado.status).lower() in ("ok", "success", "warning"), (
        f"el importador rechazó el CSV: status={resultado.status} "
        f"errors={list(resultado.errors)}")

    obs = resultado.observations
    assert len(obs) == N_EAST * N_NORTH

    return {
        "obs": obs,
        "st_n": st_n, "st_e": st_e,
        "cuerpo_n": cuerpo_n, "cuerpo_e": cuerpo_e, "esquinas": esquinas,
        "verdad": verdad, "volumen": volumen,
        # El importador normaliza restando el mínimo de cada eje.
        "este_local": (st_e + UTM_E0) - float(np.min(st_e + UTM_E0)),
        "norte_local": (st_n + UTM_N0) - float(np.min(st_n + UTM_N0)),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. EL CONTRATO DE LA INGESTA — ¿en qué slot cae cada columna del CSV?
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
def test_la_ingesta_pone_el_este_en_x_m_y_el_norte_en_z_m(ingesta):
    """Tramo B1 de la Fase 18, en forma de test. El número, no el comentario.

    Medido entonces: ``|x_m − Este| = 0,00e+00 m`` y ``|x_m − Norte| = 1200 m``.
    """
    obs = ingesta["obs"]
    x_m = np.array([o.x_m for o in obs], dtype=float)
    z_m = np.array([o.z_m for o in obs], dtype=float)

    assert np.max(np.abs(x_m - ingesta["este_local"])) < 1e-6, (
        "el slot x_m dejó de ser el ESTE: la ingesta cambió de convención y "
        "docs/11_CONVENCION_DE_EJES.md ya no describe el código")
    assert np.max(np.abs(z_m - ingesta["norte_local"])) < 1e-6, (
        "el slot z_m dejó de ser el NORTE")

    # Contraprueba: con una malla asimétrica, confundirlos es visible. Si esta
    # afirmación fallara, la malla se habría vuelto cuadrada y el test, ciego.
    assert np.max(np.abs(x_m - ingesta["norte_local"])) > 1.0, (
        "la malla de estaciones dejó de ser asimétrica: el test ya no puede "
        "distinguir Este de Norte. Restaura N_EAST != N_NORTH.")


@pytest.mark.unit
def test_los_spans_del_frame_local_son_los_del_csv(ingesta):
    """Segundo criterio independiente: la FORMA del survey no se transpone."""
    obs = ingesta["obs"]
    span_x = float(np.ptp([o.x_m for o in obs]))
    span_z = float(np.ptp([o.z_m for o in obs]))
    span_este = float(np.ptp(ingesta["este_local"]))
    span_norte = float(np.ptp(ingesta["norte_local"]))

    assert span_este != pytest.approx(span_norte), (
        "los dos spans son iguales: la geometría dejó de discriminar")
    assert span_x == pytest.approx(span_este, abs=1e-6)
    assert span_z == pytest.approx(span_norte, abs=1e-6)


# ══════════════════════════════════════════════════════════════════════════════
# 2. EL MOTOR — ¿contra qué componente de f̂ se multiplica el slot 0?
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.unit
def test_el_campo_del_motor_pone_la_componente_este_en_el_slot_0():
    """La raíz de ACAD-1, aislada: f̂ = (cos I·sin D, sin I, cos I·cos D).

    Comparado contra la definición geográfica escrita a mano, NO contra sí mismo.
    """
    f = field_unit_vector(INC_CHILE, DEC_CHILE)
    geo = _f_hat_geografico(INC_CHILE, DEC_CHILE)   # (Norte, Este, Abajo)

    assert f[0] == pytest.approx(geo[1], abs=1e-12), (
        "la componente 0 de f̂ no es la del ESTE — el motor volvió a creer que "
        "el eje 0 es el Norte (ACAD-1). Ver docs/11_CONVENCION_DE_EJES.md §4.")
    assert f[1] == pytest.approx(geo[2], abs=1e-12), "el eje 1 no es la vertical"
    assert f[2] == pytest.approx(geo[0], abs=1e-12), (
        "la componente 2 de f̂ no es la del NORTE")
    assert float(np.linalg.norm(f)) == pytest.approx(1.0, abs=1e-12)


@pytest.mark.unit
def test_el_camino_completo_csv_a_motor_reproduce_la_fisica_geografica(ingesta):
    """El eslabón que faltaba: ingesta → empalme → motor, contra la verdad.

    El empalme es el literal de ``services/geophysics_service.py`` —
    ``[[o.x_m, o.y_m, o.z_m] for o in obs]``, sin permutar. Si la convención del
    motor y la de la ingesta discrepan, este test se pone rojo aunque cada mitad
    parezca correcta por separado. **Ésa es toda la razón de ser del fichero.**

    Antes de la Fase 19 el error era de **1,45 × la señal** (dos anomalías
    incorreladas, r = −0,05).
    """
    obs = ingesta["obs"]
    sensores = np.array([[o.x_m, o.y_m, o.z_m] for o in obs], dtype=float)

    e0 = float(np.min(ingesta["st_e"] + UTM_E0))
    n0 = float(np.min(ingesta["st_n"] + UTM_N0))

    fwd = MagnetometryForward(
        dx=CELL, dy=CELL, dz=CELL, cutoff_radius=1e9,
        inclination_deg=INC_CHILE, declination_deg=DEC_CHILE,
        field_intensity_nt=B0_NT, near_field_mode="dipole")

    predicho = np.zeros(len(obs))
    for (b_n, b_e, b_d) in ingesta["esquinas"]:
        v_x = np.array([(b_e + UTM_E0) - e0])     # slot 0 = ESTE
        v_y = np.array([b_d])                     # slot 1 = profundidad
        v_z = np.array([(b_n + UTM_N0) - n0])     # slot 2 = NORTE
        predicho = predicho + np.asarray(
            fwd.build_sparse_kernel(v_x, v_y, v_z, sensores).dot(np.array([KAPPA]))
        ).ravel()

    verdad = ingesta["verdad"]
    error_relativo = float(np.max(np.abs(predicho - verdad)) / np.ptp(verdad))
    assert error_relativo < 1e-9, (
        f"el motor no reproduce la física geográfica del dato que la ingesta le "
        f"entrega (error/señal = {error_relativo:.3g}). Las dos convenciones se "
        f"volvieron a separar: ACAD-1 ha vuelto.")


@pytest.mark.unit
def test_devolver_el_defecto_de_acad_1_pone_rojo_el_test_anterior(ingesta, monkeypatch):
    """MUTACIÓN (Parte D de la Fase 18). Un test que sólo sabe decir «sí» no mide.

    Se restaura el f̂ de antes de la Fase 19 y se exige que el criterio del test
    anterior FALLE, y que falle en grande. Si esta mutación no matara, el test de
    arriba estaría pasando por una razón que no es la que dice.
    """
    import exploration.magnetometry as magmod

    def f_hat_de_antes(inclinacion_deg, declinacion_deg):
        i = math.radians(float(inclinacion_deg))
        d = math.radians(float(declinacion_deg))
        return np.array([math.cos(i) * math.cos(d),   # el viejo "# x = Norte"
                         math.sin(i),
                         math.cos(i) * math.sin(d)], dtype=np.float64)

    monkeypatch.setattr(magmod, "field_unit_vector", f_hat_de_antes)

    obs = ingesta["obs"]
    sensores = np.array([[o.x_m, o.y_m, o.z_m] for o in obs], dtype=float)
    e0 = float(np.min(ingesta["st_e"] + UTM_E0))
    n0 = float(np.min(ingesta["st_n"] + UTM_N0))

    fwd = MagnetometryForward(
        dx=CELL, dy=CELL, dz=CELL, cutoff_radius=1e9,
        inclination_deg=INC_CHILE, declination_deg=DEC_CHILE,
        field_intensity_nt=B0_NT, near_field_mode="dipole")

    predicho = np.zeros(len(obs))
    for (b_n, b_e, b_d) in ingesta["esquinas"]:
        predicho = predicho + np.asarray(
            fwd.build_sparse_kernel(
                np.array([(b_e + UTM_E0) - e0]), np.array([b_d]),
                np.array([(b_n + UTM_N0) - n0]), sensores,
            ).dot(np.array([KAPPA]))).ravel()

    verdad = ingesta["verdad"]
    error_relativo = float(np.max(np.abs(predicho - verdad)) / np.ptp(verdad))
    correlacion = float(np.corrcoef(predicho, verdad)[0, 1])

    assert error_relativo > 0.5, (
        f"la mutación NO mata: con el f̂ defectuoso el error sólo sube a "
        f"{error_relativo:.3g}× la señal. El test de arriba no está midiendo "
        f"lo que dice medir.")
    assert correlacion < 0.5, (
        f"con el defecto puesto, la anomalía sigue correlacionada con la verdad "
        f"(r = {correlacion:.3f}); la Fase 18 midió r = −0,05")


@pytest.mark.unit
def test_una_declinacion_de_45_grados_no_serviria_de_gate():
    """La consecuencia falsable que ninguna lectura de código daba.

    El defecto de ACAD-1 es una REFLEXIÓN sobre el azimut 45°, no una rotación:
    ``D_efectiva = 90° − D``. En D = 45° las dos convenciones coinciden
    EXACTAMENTE, así que un test escrito ahí sería ciego. Queda pinchado para que
    nadie "simplifique" los casos de arriba a una declinación cómoda.
    """
    i = math.radians(INC_CHILE)
    d45 = math.radians(45.0)
    canonico = np.array([math.cos(i) * math.sin(d45), math.sin(i), math.cos(i) * math.cos(d45)])
    de_antes = np.array([math.cos(i) * math.cos(d45), math.sin(i), math.cos(i) * math.sin(d45)])

    assert np.max(np.abs(canonico - de_antes)) < 1e-12, (
        "en D=45° las dos convenciones deberían coincidir exactamente")

    # Y en D=2° (producción, Chile) NO coinciden: por eso los tests usan 2°.
    d2 = math.radians(DEC_CHILE)
    canon2 = np.array([math.cos(i) * math.sin(d2), math.sin(i), math.cos(i) * math.cos(d2)])
    antes2 = np.array([math.cos(i) * math.cos(d2), math.sin(i), math.cos(i) * math.sin(d2)])
    separacion = float(np.linalg.norm(canon2 - antes2))
    # Forma cerrada de la Fase 18: √2·cos I·|sin D − cos D| = 1,1813 para Chile.
    esperado = math.sqrt(2.0) * math.cos(i) * abs(math.sin(d2) - math.cos(d2))
    assert separacion == pytest.approx(esperado, rel=1e-12)
    assert separacion > 1.0, "el caso de producción dejó de discriminar"


# ══════════════════════════════════════════════════════════════════════════════
# 3. LA SEGUNDA FUGA — la declinación que MVI publica al usuario
# ══════════════════════════════════════════════════════════════════════════════
def _media_circular(angulos_deg, pesos) -> float:
    """Media de ángulos por vector unitario. La ARITMÉTICA no sirve aquí.

    MEDIDO al ejecutar esta fase: las declinaciones por celda que devuelve MVI
    barren todo el rango ±180°, así que ``np.average`` las cancela entre sí y da
    ≈0 tanto con el código correcto como con el reflejado (−3,2° vs −0,8°). La
    media circular separa los dos casos limpiamente: **9,8° vs 80,2°**, y los dos
    suman 90 — la firma exacta de la reflexión.
    """
    a = np.radians(np.asarray(angulos_deg, dtype=float))
    w = np.asarray(pesos, dtype=float)
    return float(np.degrees(np.arctan2(np.sum(w * np.sin(a)), np.sum(w * np.cos(a)))))


@pytest.fixture(scope="module")
def mvi_induccion_pura():
    """Una inversión MVI pequeña sobre un cuerpo de inducción PURA (M = κ·f̂).

    Sin remanencia, la dirección efectiva recuperada tiene que ser la del campo.
    Malla 10×14×10 y 64 sensores: la corrida entera baja de dos segundos.
    """
    from exploration.magnetometry import MagnetometryInversion

    bloque = 10.0
    gx, gy, gz = np.mgrid[0:10, 0:14, 0:10]
    x_c = gx.flatten(order="F") * bloque + bloque / 2
    y_c = gy.flatten(order="F") * bloque + bloque / 2
    z_c = gz.flatten(order="F") * bloque + bloque / 2
    sx, sz = np.meshgrid(np.linspace(10.0, 100.0, 8), np.linspace(10.0, 100.0, 8))
    sensores = np.column_stack([sx.ravel(), np.zeros(sx.size), sz.ravel()])

    fwd = MagnetometryForward(bloque, bloque, bloque, cutoff_radius=400.0,
                              inclination_deg=INC_CHILE, declination_deg=DEC_CHILE,
                              field_intensity_nt=B0_NT)
    f = field_unit_vector(INC_CHILE, DEC_CHILE)
    kappa = np.zeros(len(x_c))
    kappa[((x_c - 50.0) ** 2 + (y_c - 40.0) ** 2 + (z_c - 50.0) ** 2) < 18.0 ** 2] = 0.25
    gx_k, gy_k, gz_k = fwd.build_mvi_kernels(x_c, y_c, z_c, sensores)
    d_obs = gx_k @ (kappa * f[0]) + gy_k @ (kappa * f[1]) + gz_k @ (kappa * f[2])

    out = MagnetometryInversion(10, 14, 10, bloque).solve_mvi_inversion_lsqr(
        d_obs, y_c, forward_model=fwd, sensor_coords=sensores, x_c=x_c, z_c=z_c,
        lambda_mag=1e-3, alpha_spatial=1.0)
    amp = np.nan_to_num(out["amplitude_full"], nan=0.0)
    fuertes = amp > 0.5 * amp.max()
    assert fuertes.sum() > 0
    return out, amp, fuertes


@pytest.mark.unit
def test_la_declinacion_que_mvi_publica_al_usuario_es_la_verdadera(mvi_induccion_pura):
    """La SEGUNDA fuga de ACAD-1: ``dec_eff = atan2(Mx, Mz)``, no ``atan2(Mz, Mx)``.

    Arreglar f̂ y NO arreglar esto es **peor que no arreglar nada**: el kernel
    queda bien y la dirección publicada sigue reflejada. Este test corre el solver
    de verdad y lee ``declination_full`` — el mismo array que viaja al cliente—,
    así que no puede pasar por reimplementar la fórmula en el test.

    ⚠️ El plan de la Fase 19 daba por hecho que
    ``test_fase20c_mvi.py::test_mvi_amplitude_direction_recovery`` ya cazaba el
    arreglo a medias («excede su margen por 86°»). **No lo hacía**: promediaba
    ángulos con `np.average`, y la media aritmética de ángulos que barren ±180°
    cancela. Con la mutación puesta ese test seguía verde. Medido, no supuesto.
    """
    out, amp, fuertes = mvi_induccion_pura
    dec = _media_circular(out["declination_full"][fuertes], amp[fuertes])
    assert abs(dec - DEC_CHILE) <= 25.0, (
        f"declinación publicada = {dec:.2f}° con D = {DEC_CHILE}°. Si ronda "
        f"{90.0 - DEC_CHILE:.0f}°, alguien arregló f̂ y olvidó "
        f"`dec_eff = arctan2(Mx, Mz)` en magnetometry.py.")


@pytest.mark.unit
def test_la_mutacion_del_arreglo_a_medias_pone_rojo_el_test_anterior(mvi_induccion_pura):
    """Contraprueba: sobre la MISMA corrida, la fórmula reflejada excede el margen.

    Reconstruye la declinación a partir de las componentes que el solver publica
    (`mx_full`, `mz_full`) con el `atan2` invertido — la mutación exacta— y exige
    que el criterio del test anterior la rechace. Sin esto, aquel test podría estar
    pasando por una razón que no es la que dice.
    """
    out, amp, fuertes = mvi_induccion_pura
    reflejada = np.degrees(np.arctan2(out["mz_full"], out["mx_full"]))
    dec_mala = _media_circular(reflejada[fuertes], amp[fuertes])

    assert abs(dec_mala - DEC_CHILE) > 25.0, (
        f"la mutación NO mata: el arreglo a medias da {dec_mala:.2f}°, dentro del "
        f"margen. El test de arriba no defiende nada.")
    dec_buena = _media_circular(out["declination_full"][fuertes], amp[fuertes])
    # Firma de la reflexión: las dos lecturas suman 90°.
    assert (dec_buena + dec_mala) == pytest.approx(90.0, abs=1.0)


@pytest.mark.unit
def test_el_par_inc_dec_es_el_inverso_exacto_de_f_hat():
    """Comprobación algebraica del par (f̂, atan2) — barata y sin solver.

    No sustituye al test de arriba (aquí la fórmula se reimplementa, así que no
    ve una mutación en producción); fija el ÁLGEBRA: la pareja tiene que ser una
    identidad en los cuatro sitios, incluido el D=45° donde el defecto no se ve.
    """
    for inc, dec in [(INC_CHILE, DEC_CHILE), (83.8, 25.4), (83.0, -32.0), (-30.0, 45.0)]:
        f = field_unit_vector(inc, dec)
        mx, my, mz = float(f[0]), float(f[1]), float(f[2])
        assert math.degrees(math.atan2(my, math.hypot(mx, mz))) == pytest.approx(inc, abs=1e-9)
        assert math.degrees(math.atan2(mx, mz)) == pytest.approx(dec, abs=1e-9)
