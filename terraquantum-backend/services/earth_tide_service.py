"""F2B — Marea terrestre (corrección de marea gravimétrica), Longman 1959.

Fórmulas de I.M. Longman, "Formulas for Computing the Tidal Accelerations Due
to the Moon and the Sun", JGR 64(12), 1959 — el estándar de reducción
gravimétrica de campo. Astronomía pura: lat/lon/altura/fecha-hora UTC,
100% offline, sin dependencias nuevas (math/numpy).

Constantes numéricas verificadas contra la implementación de referencia MIT
LongmanTide (J. Leeman, github.com/jrleeman/LongmanTide), cuyo valor de test
publicado se usa como oráculo en tests/test_earth_tide.py (coincidencia a
1e-8 mGal).

CONVENCIÓN (documentada, jamás implícita):
  - `lon` entra en la convención ESTÁNDAR este-positivo (WGS84, −180..180 o
    0..360). Longman define W+ internamente; la conversión vive aquí.
  - El valor devuelto es la ACELERACIÓN de marea vertical g_tide en mGal
    (positivo = la atracción luni-solar AUMENTA g medido). La corrección de
    campo es RESTARLA: g_corregida = g_leída − g_tide.
  - `time_utc` debe ser UTC (naive = se asume UTC; el llamador convierte).
Amplitud física esperada: |g_tide| ≲ 0.3 mGal (chequeado en tests).
"""
from __future__ import annotations

from datetime import datetime
from math import acos, asin, atan, cos, radians, sin, sqrt
from typing import Iterable, List, Sequence, Tuple

import numpy as np

from core.logging import get_logger

_log = get_logger(__name__)

# ── Constantes (Longman 1959; cgs como el paper) ─────────────────────────────
_MU = 6.673e-8        # constante de gravitación [cgs]
_M_MOON = 7.3537e25   # masa de la Luna [g]
_M_SUN = 1.993e33     # masa del Sol [g]
_E_MOON = 0.05490     # excentricidad de la órbita lunar
_M_RATIO = 0.074804   # razón movimiento medio Sol/Luna
_C_MOON = 3.84402e10  # distancia media Tierra-Luna [cm]
_C_SUN = 1.495e13     # distancia media Tierra-Sol [cm]
_H2 = 0.612           # número de Love h₂
_K2 = 0.303           # número de Love k₂
_A_EQ = 6.378270e8    # radio ecuatorial terrestre [cm]
_I_MOON = 0.08979719  # inclinación órbita lunar a la eclíptica [rad]
_OMEGA = radians(23.452)  # oblicuidad de la eclíptica

# Factor gravimétrico (1 + h₂ − 3/2·k₂): Tierra elástica.
_LOVE_FACTOR = 1.0 + _H2 - 1.5 * _K2

# Época de Longman: mediodía del 31 de diciembre de 1899.
_EPOCH = datetime(1899, 12, 31, 12, 0, 0)


def _julian_century_and_hour(time_utc: datetime) -> Tuple[float, float]:
    """Siglo juliano decimal desde la época de Longman + hora UTC decimal."""
    dt = time_utc - _EPOCH
    days = dt.days + dt.seconds / 3600.0 / 24.0
    T = days / 36525.0
    t0 = time_utc.hour + time_utc.minute / 60.0 + time_utc.second / 3600.0
    return T, t0


def solve_longman_tide(
    lat_deg: float, lon_deg: float, alt_m: float, time_utc: datetime
) -> Tuple[float, float, float]:
    """Aceleración de marea (Luna, Sol, total) en mGal para un instante UTC.

    Réplica fiel de Longman 1959 (ecuaciones citadas en comentarios). Devuelve
    (g_luna, g_sol, g_total) en mGal, ya multiplicados por el factor
    gravimétrico de Love (Tierra elástica).
    """
    T, t0 = _julian_century_and_hour(time_utc)
    if t0 < 0:
        t0 += 24.0
    if t0 >= 24:
        t0 -= 24.0

    # Longman usa longitud OESTE-positiva; entrada estándar este-positiva.
    L = -1.0 * lon_deg
    lamb = radians(lat_deg)
    H = alt_m * 100.0  # cm

    # ── Luna ─────────────────────────────────────────────────────────────────
    # (s) longitud media de la Luna en su órbita
    s = (4.72000889397 + 8399.70927456 * T + 3.45575191895e-05 * T * T
         + 3.49065850399e-08 * T * T * T)
    # (p) longitud media del perigeo lunar
    p = (5.83515162814 + 71.0180412089 * T + 0.000180108282532 * T * T
         + 1.74532925199e-07 * T * T * T)
    # (h) longitud media del Sol
    h = 4.88162798259 + 628.331950894 * T + 5.23598775598e-06 * T * T
    # (N) longitud del nodo ascendente lunar
    N = (4.52360161181 - 33.757146295 * T + 3.6264063347e-05 * T * T
         + 3.39369576777e-08 * T * T * T)
    # (I) inclinación de la órbita lunar al ecuador
    I = acos(cos(_OMEGA) * cos(_I_MOON) - sin(_OMEGA) * sin(_I_MOON) * cos(N))
    # (nu) longitud en el ecuador celeste de la intersección A
    nu = asin(sin(_I_MOON) * sin(N) / sin(I))
    # (t) ángulo horario del sol medio, medido al oeste del lugar
    t = radians(15.0 * (t0 - 12.0) - L)
    # (chi) ascensión recta del meridiano del lugar desde A
    chi = t + h - nu
    # (alpha) ec. 15-16
    cos_alpha = cos(N) * cos(nu) + sin(N) * sin(nu) * cos(_OMEGA)
    sin_alpha = sin(_OMEGA) * sin(N) / sin(I)
    alpha = 2.0 * atan(sin_alpha / (1.0 + cos_alpha))
    # (xi) longitud en la órbita lunar de su intersección ascendente
    xi = N - alpha
    # (sigma) longitud media de la Luna desde A
    sigma = s - xi
    # (l) longitud de la Luna en su órbita desde la intersección ascendente
    l = (sigma + 2.0 * _E_MOON * sin(s - p)
         + (5.0 / 4.0) * _E_MOON * _E_MOON * sin(2.0 * (s - p))
         + (15.0 / 4.0) * _M_RATIO * _E_MOON * sin(s - 2.0 * h + p)
         + (11.0 / 8.0) * _M_RATIO * _M_RATIO * sin(2.0 * (s - h)))

    # ── Sol ──────────────────────────────────────────────────────────────────
    # (p1) longitud media del perigeo solar
    p1 = (4.90822941839 + 0.0300025492114 * T + 7.85398163397e-06 * T * T
          + 5.3329504922e-08 * T * T * T)
    # (e1) excentricidad de la órbita terrestre
    e1 = 0.01675104 - 0.00004180 * T - 0.000000126 * T * T
    # (chi1) ascensión recta del meridiano desde el equinoccio vernal
    chi1 = t + h
    # (l1) longitud del Sol en la eclíptica
    l1 = h + 2.0 * e1 * sin(h - p1)
    # cos(theta): ángulo cenital de la Luna
    cos_theta = (sin(lamb) * sin(I) * sin(l)
                 + cos(lamb) * (cos(0.5 * I) ** 2 * cos(l - chi)
                                + sin(0.5 * I) ** 2 * cos(l + chi)))
    # cos(phi): ángulo cenital del Sol
    cos_phi = (sin(lamb) * sin(_OMEGA) * sin(l1)
               + cos(lamb) * (cos(0.5 * _OMEGA) ** 2 * cos(l1 - chi1)
                              + sin(0.5 * _OMEGA) ** 2 * cos(l1 + chi1)))

    # ── Distancias ───────────────────────────────────────────────────────────
    # (C) ec. 34; (r) distancia del punto P al centro de la Tierra
    C = sqrt(1.0 / (1.0 + 0.006738 * sin(lamb) ** 2))
    r = C * _A_EQ + H
    # (a', a1') ec. 31
    aprime = 1.0 / (_C_MOON * (1.0 - _E_MOON * _E_MOON))
    aprime1 = 1.0 / (_C_SUN * (1.0 - e1 * e1))
    # (d) distancia Tierra-Luna
    d = 1.0 / ((1.0 / _C_MOON) + aprime * _E_MOON * cos(s - p)
               + aprime * _E_MOON * _E_MOON * cos(2.0 * (s - p))
               + (15.0 / 8.0) * aprime * _M_RATIO * _E_MOON * cos(s - 2.0 * h + p)
               + aprime * _M_RATIO * _M_RATIO * cos(2.0 * (s - h)))
    # (D) distancia Tierra-Sol
    D = 1.0 / ((1.0 / _C_SUN) + aprime1 * e1 * cos(h - p1))

    # ── Aceleraciones verticales (cgs → mGal ×1e3) ───────────────────────────
    gm = ((_MU * _M_MOON * r / (d * d * d)) * (3.0 * cos_theta ** 2 - 1.0)
          + (3.0 / 2.0) * (_MU * _M_MOON * r * r / (d ** 4))
          * (5.0 * cos_theta ** 3 - 3.0 * cos_theta))
    gs = _MU * _M_SUN * r / (D * D * D) * (3.0 * cos_phi ** 2 - 1.0)

    g_moon = gm * 1e3 * _LOVE_FACTOR
    g_sun = gs * 1e3 * _LOVE_FACTOR
    return g_moon, g_sun, g_moon + g_sun


def tide_series_mgal(
    lat_deg: float,
    lon_deg: float,
    alt_m: float,
    times_utc: "Sequence[datetime] | Iterable[datetime]",
) -> np.ndarray:
    """Serie de marea total (mGal) para una lista de instantes UTC.

    Para la corrección de un survey: g_corregida = g_leída − tide[i].
    Estación fija (lat/lon/alt del punto o de la base — a escala de survey
    local la diferencia espacial de la marea es despreciable, <1 µGal/km).
    """
    return np.array(
        [solve_longman_tide(lat_deg, lon_deg, alt_m, t)[2] for t in times_utc],
        dtype=float,
    )


def parse_survey_timestamps(raw_values: Sequence[str]) -> "List[datetime] | None":
    """Parsea timestamps de columna de campo a datetimes (UTC asumido).

    Acepta ISO-8601 (con o sin 'T'), 'YYYY-MM-DD HH:MM[:SS]' y variantes con
    '/' — los formatos reales de gravímetros CG-5/CG-6 exportados a CSV.
    Devuelve None si ALGÚN valor no parsea (todo-o-nada: una serie de tiempo
    a medias produciría una corrección de marea corrupta en silencio).
    """
    out: List[datetime] = []
    for raw in raw_values:
        s = str(raw).strip().replace("/", "-")
        if not s:
            return None
        parsed = None
        for fmt in (
            "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M",
            "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M",
        ):
            try:
                parsed = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            try:
                parsed = datetime.fromisoformat(s)
                if parsed.tzinfo is not None:
                    parsed = parsed.replace(tzinfo=None)
            except ValueError:
                return None
        out.append(parsed)
    return out
