"""Fase 3 (cierre) — la CI se pone roja si la física se DESCALIBRA.

POR QUÉ EXISTE ESTE ARCHIVO
===========================
El criterio de aceptación de la Fase 3 dice: «CI roja si la física regresiona».
El canario que se cableó para eso —`test_synthetic_sphere_recovery`— NO cumple
esa promesa entera, y está MEDIDO (2026-08-13, ver docs/06 §FASE 3):

    mutación                             pearson_r   misfit    veredicto
    ─────────────────────────────────    ─────────   ──────    ─────────
    ninguna (línea base)                 0.7259      0.654%    PASA
    G = 6.67430e-11 → 7.00000e-11        0.7259      0.654%    PASA  ← ciego
    W_z apagado (exponente 0)            0.7259      0.654%    PASA  ← ciego
    lambda_spatial × 500                 —           —         FALLA ← ve

El canario ve regresiones de FORMA (sobre-regularización) y es ciego a las de
ESCALA. La razón no es que Pearson sea invariante al escalado: es que el propio
benchmark genera el dato sintético con la MISMA constante con la que después
invierte, así que un error en G se cancela exactamente. El cartel dice
«ANTI-INVERSE CRIME: mallas y operadores distintos» — y es cierto para la malla,
pero las CONSTANTES son las mismas a ambos lados. En ese eje sigue habiendo
crimen inverso.

Eso importa porque este proyecto YA se descalibró dos veces por ahí: el bug de
mGal×1e-5 (DO-27) y el de la doble corrección de Bouguer (commit 9045719). Los
dos son errores de escala. Ninguno de los dos habría puesto roja la CI.

QUÉ HACE ESTE ARCHIVO
=====================
Contrasta el operador forward de producción contra la verdad ANALÍTICA —una
fórmula escrita aquí, independiente del motor— en el régimen donde esa verdad
es exacta: campo lejano, donde un prisma es indistinguible de una masa puntual.
Cero inversión, cero ajuste, milisegundos.

Verificado 2026-08-13: el acuerdo es de 8 cifras (ratio 1.00000000 en las cuatro
geometrías). La tolerancia de 1e-4 es, por tanto, ~500 veces más estrecha que la
mutación de G del +4,9% que el canario deja pasar.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from exploration.gravimetry import GravimetryForward  # noqa: E402

# CODATA 2018. Escrito AQUÍ a propósito: si alguien toca la constante del motor,
# este valor no se mueve con ella y el test lo delata.
G_CODATA = 6.67430e-11

# El operador entrega m/s² por unidad de densidad en t/m³ (verificado: el kernel
# de un vóxel aislado coincide con G·(ρ·1000)·V/d² a 6 cifras). Si alguien cambia
# la unidad de entrada sin avisar, este factor deja de cuadrar y el test cae.
KG_POR_TONELADA = 1000.0

ARISTA_M = 10.0
PROFUNDIDAD_M = 600.0        # 60 aristas → campo lejano de sobra
TOLERANCIA_RELATIVA = 1e-4


def _kernel_de_un_voxel(sensores: np.ndarray) -> np.ndarray:
    """Columna del kernel de producción para un único vóxel a PROFUNDIDAD_M."""
    fw = GravimetryForward(dx=ARISTA_M, dy=ARISTA_M, dz=ARISTA_M, cutoff_radius=20_000.0)
    K = fw.build_sparse_kernel(
        np.array([0.0]), np.array([PROFUNDIDAD_M]), np.array([0.0]), sensores
    )
    return np.asarray(K.todense()).ravel()


def _masa_puntual(sensores: np.ndarray) -> np.ndarray:
    """Verdad analítica: componente VERTICAL de una masa puntual, en m/s²
    por t/m³ de contraste. `y` es profundidad positiva hacia abajo."""
    masa_kg = KG_POR_TONELADA * ARISTA_M ** 3
    dx = sensores[:, 0] - 0.0
    dy = PROFUNDIDAD_M - sensores[:, 1]
    dz = sensores[:, 2] - 0.0
    r = np.sqrt(dx ** 2 + dy ** 2 + dz ** 2)
    return G_CODATA * masa_kg * dy / r ** 3


# Cuatro geometrías: encima, desplazado en x, desplazado en z, y oblicuo.
# Con una sola (la de encima) un error de eje podría colarse.
SENSORES = np.array([
    [0.0, 0.0, 0.0],
    [200.0, 0.0, 0.0],
    [0.0, 0.0, -350.0],
    [150.0, 0.0, 250.0],
])


def test_el_forward_reproduce_la_masa_puntual_analitica():
    """El kernel de producción == fórmula cerrada, en campo lejano.

    Caza de un golpe: G equivocada, conversión t/m³ ↔ kg/m³ perdida, volumen de
    vóxel mal calculado, factor 1e-5 de mGal colado, y componente/eje cambiado.
    """
    obtenido = _kernel_de_un_voxel(SENSORES)
    esperado = _masa_puntual(SENSORES)

    razones = obtenido / esperado
    peor = float(np.max(np.abs(razones - 1.0)))
    assert peor < TOLERANCIA_RELATIVA, (
        "El operador forward ya no coincide con la masa puntual analítica: "
        f"desviación relativa máxima {peor:.3e} > {TOLERANCIA_RELATIVA:.0e}.\n"
        f"  razones kernel/analítico por sensor: {np.round(razones, 8).tolist()}\n"
        "Esto es una DESCALIBRACIÓN (escala/unidades/constante), no un cambio de "
        "forma: el canario sintético no la vería."
    )


def test_el_forward_es_lineal_en_la_densidad():
    """Superposición: dos vóxeles == la suma de sus columnas.

    Si alguien mete una no-linealidad (un clip, un abs, una saturación) en el
    camino del forward, el modelo directo deja de ser el adjunto del que usa el
    solver, y toda la inversión queda mal planteada sin que nada lo diga.
    """
    fw = GravimetryForward(dx=ARISTA_M, dy=ARISTA_M, dz=ARISTA_M, cutoff_radius=20_000.0)
    xs = np.array([0.0, 120.0])
    ys = np.array([PROFUNDIDAD_M, PROFUNDIDAD_M])
    zs = np.array([0.0, 80.0])

    K_dos = np.asarray(fw.build_sparse_kernel(xs, ys, zs, SENSORES).todense())
    K_a = np.asarray(fw.build_sparse_kernel(xs[:1], ys[:1], zs[:1], SENSORES).todense())
    K_b = np.asarray(fw.build_sparse_kernel(xs[1:], ys[1:], zs[1:], SENSORES).todense())

    assert np.allclose(K_dos[:, [0]], K_a, rtol=1e-12, atol=0.0)
    assert np.allclose(K_dos[:, [1]], K_b, rtol=1e-12, atol=0.0)


def test_la_tolerancia_discrimina_la_descalibracion_que_el_canario_deja_pasar():
    """El test de arriba sólo sirve si su tolerancia es más estrecha que el error
    que queremos cazar. Se comprueba con la mutación REAL que se midió: G a
    7.00000e-11 (+4,9%), que el canario sintético aprueba sin inmutarse.

    No se toca el motor: se descalibra la verdad analítica, que es equivalente
    para juzgar el poder del umbral y no deja nada que revertir.
    """
    obtenido = _kernel_de_un_voxel(SENSORES)
    esperado_descalibrado = _masa_puntual(SENSORES) * (7.00000e-11 / G_CODATA)

    peor = float(np.max(np.abs(obtenido / esperado_descalibrado - 1.0)))
    assert peor > TOLERANCIA_RELATIVA, (
        "La tolerancia es demasiado ancha: no distinguiría un error del 4,9% en "
        f"la constante gravitacional (desviación medida {peor:.3e})."
    )


@pytest.mark.parametrize("profundidad_m", [300.0, 600.0, 1200.0])
def test_el_acuerdo_no_depende_de_la_profundidad(profundidad_m):
    """Un desacuerdo que crece con la profundidad sería otra enfermedad (el
    depth-weighting metido donde no toca), y conviene separarla de la escala."""
    fw = GravimetryForward(dx=ARISTA_M, dy=ARISTA_M, dz=ARISTA_M, cutoff_radius=20_000.0)
    obtenido = np.asarray(
        fw.build_sparse_kernel(
            np.array([0.0]), np.array([profundidad_m]), np.array([0.0]), SENSORES
        ).todense()
    ).ravel()

    masa_kg = KG_POR_TONELADA * ARISTA_M ** 3
    dy = profundidad_m - SENSORES[:, 1]
    r = np.sqrt(SENSORES[:, 0] ** 2 + dy ** 2 + SENSORES[:, 2] ** 2)
    esperado = G_CODATA * masa_kg * dy / r ** 3

    peor = float(np.max(np.abs(obtenido / esperado - 1.0)))
    assert peor < TOLERANCIA_RELATIVA, (
        f"A {profundidad_m:.0f} m el forward se desvía {peor:.3e} de la masa puntual."
    )
