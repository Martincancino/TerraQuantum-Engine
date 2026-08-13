"""
Generación de observaciones sintéticas con un forward INDEPENDIENTE (P4 / D5).

Oráculo: `choclo` (proyecto Fatiando a Terra) — la librería de kernels de modelado
directo diseñada explícitamente para ser reutilizada por otras librerías (Harmonica,
SimPEG). Que el dato lo produzca código de otros autores convierte el anti-inverse-crime
de PROCEDIMIENTO (usar otra malla y acordarse) en ESTRUCTURA.

CONVENCIONES — verificadas contra la fórmula analítica de masa puntual antes de
escribir este módulo (error 0,002 % en el pico, 0,000 % en campo lejano):

    choclo:  (easting, northing, upward)   upward POSITIVO HACIA ARRIBA
             -> un cuerpo enterrado tiene upward NEGATIVO
             -> devuelve m/s², NEGATIVO para un exceso de masa

    TerraQuantum: (x, y, z) con y POSITIVO HACIA ABAJO (profundidad)
             -> g POSITIVO para un exceso de masa

    Conversión:  easting = x ,  northing = z ,  upward = −y
                 g_tq    = −g_choclo
"""
from __future__ import annotations

import numpy as np

from .contract import Campaign, GenerationMethod, World

GENERATOR_VERSION = "generate/1+choclo0.3.2"

_G = 6.6743e-11          # m³ kg⁻¹ s⁻²
MGAL_PER_SI = 1e5        # 1 m/s² = 1e5 mGal
T_M3_TO_KG_M3 = 1000.0   # 1 t/m³ = 1000 kg/m³


def _stations(campaign: Campaign, center_xz: tuple[float, float]):
    """Rejilla regular de estaciones en superficie, centrada en el mundo."""
    s = campaign.survey
    cx, cz = center_xz
    half = s.span_m / 2.0
    ax = np.linspace(cx - half, cx + half, s.n_side)
    az = np.linspace(cz - half, cz + half, s.n_side)
    xx, zz = np.meshgrid(ax, az, indexing="ij")
    x = xx.ravel()
    z = zz.ravel()
    y = np.full(x.size, -s.height_m)      # y hacia abajo: altura = y negativa
    return x, y, z


def generate_gravity(world: World, campaign: Campaign):
    """Devuelve (x, y, z, g) en convención TerraQuantum; g en m/s².

    Solo admite `THIRD_PARTY` (choclo). Los demás métodos existen en el contrato
    para poder DECLARARLOS, no para que este generador los produzca.
    """
    if campaign.generation_method is not GenerationMethod.THIRD_PARTY:
        raise NotImplementedError(
            f"Este generador solo produce {GenerationMethod.THIRD_PARTY}. "
            f"Recibido: {campaign.generation_method}. "
            "Los demás valores existen para declarar datos generados por otra vía."
        )

    from choclo.point import gravity_u as point_gravity_u
    from choclo.prism import gravity_u as prism_gravity_u

    x0, y0, z0, x1, y1, z1 = world.geometry.bounds_m
    center_xz = (0.5 * (x0 + x1), 0.5 * (z0 + z1))
    xs, ys, zs = _stations(campaign, center_xz)

    # a coordenadas choclo
    e_p, n_p, u_p = xs, zs, -ys

    g_si = np.zeros(xs.size, dtype=np.float64)
    bg = world.properties.background.density_t_m3

    for body in world.geometry.bodies:
        props = world.properties.domains[body.domain]
        contrast_kg = (props.density_t_m3 - bg) * T_M3_TO_KG_M3
        if contrast_kg == 0.0:
            continue
        sh = body.shape

        if sh.kind == "sphere":
            # Masa puntual = solución EXACTA del campo externo de una esfera
            # homogénea (teorema de las capas de Newton). Mejor que aproximar
            # con un prisma.
            mass = contrast_kg * sh.volume_m3
            e_q, n_q, u_q = sh.cx_m, sh.cz_m, -sh.cy_m
            for i in range(xs.size):
                g_si[i] += point_gravity_u(
                    e_p[i], n_p[i], u_p[i], e_q, n_q, u_q, mass
                )
        elif sh.kind == "prism":
            west, east = sh.x0_m, sh.x1_m
            south, north = sh.z0_m, sh.z1_m
            bottom, top = -sh.y1_m, -sh.y0_m      # y abajo -> upward arriba
            for i in range(xs.size):
                g_si[i] += prism_gravity_u(
                    e_p[i], n_p[i], u_p[i],
                    west, east, south, north, bottom, top, contrast_kg,
                )
        else:
            raise NotImplementedError(f"forma no soportada: {sh.kind}")

    g_tq = -g_si                                   # signo: exceso de masa -> g > 0

    # ── Ruido: determinista a partir de la semilla de la CAMPAÑA (P6) ────────
    rng = np.random.default_rng(campaign.provenance.seed)
    if campaign.noise.instrument_mgal > 0:
        g_tq = g_tq + rng.normal(
            0.0, campaign.noise.instrument_mgal / MGAL_PER_SI, size=g_tq.size
        )
    if campaign.noise.position_m > 0:
        xs = xs + rng.normal(0.0, campaign.noise.position_m, size=xs.size)
        zs = zs + rng.normal(0.0, campaign.noise.position_m, size=zs.size)

    return xs, ys, zs, g_tq


def selfcheck_against_analytic(depth_m: float = 400.0, radius_m: float = 100.0,
                               contrast_t_m3: float = 0.6) -> float:
    """Comprueba el oráculo contra la fórmula cerrada. Devuelve el error relativo
    máximo. Se ejecuta en el arranque del smoke: si choclo o las convenciones
    cambian, se detecta antes de medir nada."""
    from choclo.point import gravity_u as point_gravity_u

    mass = contrast_t_m3 * T_M3_TO_KG_M3 * (4.0 / 3.0) * np.pi * radius_m ** 3
    x = np.linspace(-1000.0, 1000.0, 21)
    got = np.array([point_gravity_u(xi, 0.0, 0.0, 0.0, 0.0, -depth_m, mass)
                    for xi in x])
    expected = -_G * mass * depth_m / (x ** 2 + depth_m ** 2) ** 1.5
    return float(np.max(np.abs(got - expected) / np.abs(expected)))
