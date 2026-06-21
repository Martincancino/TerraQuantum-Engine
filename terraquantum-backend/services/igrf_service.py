"""IGRF-14 offline — campo geomagnético de referencia desde armónicos esféricos.

Computa inclinación, declinación e intensidad total del campo principal de la
Tierra en (lat, lon, altitud, fecha) SIN dependencias externas: solo numpy +
los coeficientes públicos IGRF-14 (IAGA, dominio público) bundleados como dato
del repo en ``services/data/igrf14coeffs.txt``.

Esto NO inventa nada: el IGRF es física real (armónicos esféricos de Gauss con
coeficientes medidos por la comunidad geomagnética). El algoritmo de síntesis es
un port fiel de la rutina de referencia ``igrf13syn`` (British Geological Survey /
NOAA), validado contra valores publicados en los tests.

Convenciones (sistema geodético, salida en nT):
  • X = componente norte,  Y = componente este,  Z = componente vertical (hacia abajo +)
  • H = sqrt(X²+Y²)  intensidad horizontal
  • F = sqrt(X²+Y²+Z²)  intensidad total
  • D = atan2(Y, X)  declinación (grados, + hacia el este)
  • I = atan2(Z, H)  inclinación (grados, + hacia abajo)

Validez: 1900.0 ≤ fecha ≤ 2030.0 (modelo principal a 2025.0 + variación secular
2025–2030 para extrapolación). Fuera de ese rango → IgrfOutOfRangeError.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

MODEL_NAME = "IGRF-14"
METHOD_LABEL = "IGRF-14 (armónicos esféricos, offline)"

_COEFF_PATH = Path(__file__).resolve().parent / "data" / "igrf14coeffs.txt"
_REFERENCE_RADIUS_KM = 6371.2  # radio de referencia de los armónicos IGRF

# WGS84 (mismas constantes que igrf13syn, en km²·escala interna del algoritmo).
_A2 = 40680631.6
_B2 = 40408296.0

_DATE_MIN = 1900.0
_DATE_MAX = 2030.0
_LAST_EPOCH = 2025.0  # última época del modelo principal IGRF-14


class IgrfError(Exception):
    """Error base del servicio IGRF."""


class IgrfOutOfRangeError(IgrfError):
    """La fecha pedida cae fuera de la validez del modelo (1900–2030)."""


@dataclass(frozen=True)
class IgrfResult:
    inclination_deg: float
    declination_deg: float
    total_intensity_nt: float
    horizontal_nt: float
    north_nt: float
    east_nt: float
    down_nt: float

    def to_dict(self) -> dict:
        return {
            "inclination_deg": self.inclination_deg,
            "declination_deg": self.declination_deg,
            "field_intensity_nt": self.total_intensity_nt,
            "horizontal_nt": self.horizontal_nt,
            "north_nt": self.north_nt,
            "east_nt": self.east_nt,
            "down_nt": self.down_nt,
        }


@dataclass(frozen=True)
class _CoeffTable:
    """Coeficientes IGRF-14 parseados, en el orden empaquetado de igrf13syn.

    ``order`` lista las claves (tipo, n, m) en el orden del archivo, que coincide
    con el orden de síntesis (para cada n: g(n,0); luego g(n,m), h(n,m) m=1..n).
    ``values`` es [n_coef, n_epochs]; ``sv`` la variación secular por coeficiente.
    """

    epochs: np.ndarray          # [n_epochs] años (1900..2025)
    order: List[Tuple[str, int, int]]
    values: np.ndarray          # [n_coef, n_epochs] nT
    sv: np.ndarray              # [n_coef] nT/año
    nmax: int


_TABLE: Optional[_CoeffTable] = None


def _load_table() -> _CoeffTable:
    """Lee y cachea el archivo de coeficientes IGRF-14 bundleado."""
    global _TABLE
    if _TABLE is not None:
        return _TABLE
    if not _COEFF_PATH.exists():  # pragma: no cover - solo si falta el bundle
        raise IgrfError(
            f"Archivo de coeficientes IGRF no encontrado: {_COEFF_PATH}. "
            "Debe estar bundleado en el repo (services/data/igrf14coeffs.txt)."
        )

    epochs: Optional[np.ndarray] = None
    order: List[Tuple[str, int, int]] = []
    rows: List[List[float]] = []
    svs: List[float] = []
    nmax = 0

    for raw in _COEFF_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tok = line.split()
        if tok[0] == "c/s":
            continue
        if tok[0] == "g/h":
            # Encabezado de épocas: g/h n m <años...> <SV col>.
            yrs = [float(x.split("-")[0]) for x in tok[3:-1]]
            epochs = np.array(yrs, dtype=np.float64)
            continue
        if tok[0] not in ("g", "h"):
            continue
        n = int(tok[1]); m = int(tok[2])
        nums = [float(x) for x in tok[3:]]
        order.append((tok[0], n, m))
        rows.append(nums[:-1])   # valores por época
        svs.append(nums[-1])     # variación secular 2025–2030
        nmax = max(nmax, n)

    if epochs is None or not rows:  # pragma: no cover - archivo corrupto
        raise IgrfError("No se pudieron parsear los coeficientes IGRF (archivo corrupto).")

    values = np.array(rows, dtype=np.float64)
    if values.shape[1] != epochs.shape[0]:  # pragma: no cover
        raise IgrfError(
            f"Inconsistencia coeficientes/épocas: {values.shape[1]} vs {epochs.shape[0]}."
        )

    _TABLE = _CoeffTable(
        epochs=epochs, order=order, values=values,
        sv=np.array(svs, dtype=np.float64), nmax=nmax,
    )
    return _TABLE


def _coeffs_for_year(table: _CoeffTable, year: float) -> np.ndarray:
    """Interpola (o extrapola con SV) los coeficientes a un año decimal.

    1900 ≤ year ≤ 2025  → interpolación lineal entre épocas adyacentes.
    2025 <  year ≤ 2030  → extrapolación con la variación secular (SV).
    """
    epochs = table.epochs
    if year <= epochs[0]:
        return table.values[:, 0].copy()
    if year <= _LAST_EPOCH:
        # Índice del intervalo [epochs[i], epochs[i+1]] que contiene a year.
        i = int(np.searchsorted(epochs, year, side="right")) - 1
        i = max(0, min(i, epochs.shape[0] - 2))
        lo, hi = epochs[i], epochs[i + 1]
        frac = (year - lo) / (hi - lo)
        return (1.0 - frac) * table.values[:, i] + frac * table.values[:, i + 1]
    # Extrapolación lineal con SV desde la última época (2025.0).
    return table.values[:, -1] + (year - _LAST_EPOCH) * table.sv


def decimal_year(value) -> float:
    """Convierte año entero, float o fecha ISO ('YYYY', 'YYYY-MM', 'YYYY-MM-DD') a año decimal."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        raise ValueError("fecha vacía")
    m = re.match(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", s)
    if not m:
        return float(s)  # último recurso: deja que float() levante si no es numérico
    y = int(m.group(1))
    mo = int(m.group(2)) if m.group(2) else 1
    d = int(m.group(3)) if m.group(3) else 1
    mo = min(max(mo, 1), 12)
    d = min(max(d, 1), 28)  # día acotado; el efecto sub-mensual en IGRF es despreciable
    # Fracción del año por día-del-año (calendario civil aproximado, suficiente para IGRF).
    days_before = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    doy = days_before[mo - 1] + (d - 1)
    return y + doy / 365.0


def _synthesize(gh: np.ndarray, nmax: int, alt_km: float, lat_deg: float,
                lon_deg: float) -> Tuple[float, float, float]:
    """Síntesis geocéntrica de X, Y, Z (nT) — port fiel de igrf13syn (itype=1, geodético).

    ``gh`` son los coeficientes de Schmidt en orden empaquetado (g(1,0), g(1,1),
    h(1,1), g(2,0), ...). ``alt_km`` es altitud sobre el elipsoide WGS84.
    """
    colat = 90.0 - lat_deg
    d2r = 0.017453292
    kmx = (nmax + 1) * (nmax + 2) // 2

    p = [0.0] * (kmx + 1)   # 1-indexado (p[0] dummy), como el Fortran
    q = [0.0] * (kmx + 1)
    cl = [0.0] * (nmax + 1)
    sl = [0.0] * (nmax + 1)

    x = y = z = 0.0

    one = colat * d2r
    ct = math.cos(one)
    st = math.sin(one)
    one = lon_deg * d2r
    cl[1] = math.cos(one)
    sl[1] = math.sin(one)

    # Conversión geodética → geocéntrica (elipsoide WGS84).
    o = _A2 * st * st
    t2 = _B2 * ct * ct
    three = o + t2
    rho = math.sqrt(three)
    r = math.sqrt(alt_km * (alt_km + 2.0 * rho) + (_A2 * o + _B2 * t2) / three)
    cd = (alt_km + rho) / r
    sd = (_A2 - _B2) / rho * ct * st / r
    o = ct
    ct = ct * cd - st * sd
    st = st * cd + o * sd

    ratio = _REFERENCE_RADIUS_KM / r
    rr = ratio * ratio

    p[1] = 1.0
    p[3] = st
    q[1] = 0.0
    q[3] = ct

    l = 1
    m = 1
    n = 0
    fn = 0.0
    for k in range(2, kmx + 1):
        if n < m:
            m = 0
            n = n + 1
            rr = rr * ratio
            fn = float(n)
            gn = float(n - 1)
        fm = float(m)
        if m == n:
            if k != 3:
                o = math.sqrt(1.0 - 0.5 / fm)
                j = k - n - 1
                p[k] = o * st * p[j]
                q[k] = o * (st * q[j] + ct * p[j])
                cl[m] = cl[m - 1] * cl[1] - sl[m - 1] * sl[1]
                sl[m] = sl[m - 1] * cl[1] + cl[m - 1] * sl[1]
        else:
            gmm = float(m * m)
            o = math.sqrt(fn * fn - gmm)
            t2 = math.sqrt(gn * gn - gmm) / o
            three = (fn + gn) / o
            i = k - n
            j = i - n + 1
            p[k] = three * ct * p[i] - t2 * p[j]
            q[k] = three * (ct * q[i] - st * p[i]) - t2 * q[j]

        # Síntesis de X, Y, Z (gh ya interpolado a la fecha; gh es 1-indexado).
        one = gh[l] * rr
        if m == 0:
            x = x + one * q[k]
            z = z - (fn + 1.0) * one * p[k]
            l = l + 1
        else:
            two = gh[l + 1] * rr
            three = one * cl[m] + two * sl[m]
            x = x + three * q[k]
            z = z - (fn + 1.0) * three * p[k]
            if st == 0.0:
                y = y + (one * sl[m] - two * cl[m]) * q[k] * ct
            else:
                y = y + (one * sl[m] - two * cl[m]) * fm * p[k] / st
            l = l + 2
        m = m + 1

    # Rotación de geocéntrico de vuelta a geodético.
    one = x
    x = x * cd + z * sd
    z = z * cd - one * sd
    return x, y, z


def igrf_field(lat_deg: float, lon_deg: float, alt_m: float, year) -> IgrfResult:
    """Campo geomagnético IGRF-14 en (lat, lon, altitud, fecha).

    lat_deg/lon_deg geodéticos (lon este +); alt_m metros sobre el nivel del mar
    (aprox. elipsoide); ``year`` año decimal o fecha ISO. Devuelve un IgrfResult
    con inclinación/declinación/intensidad y las componentes X/Y/Z/H.
    """
    yr = decimal_year(year)
    if yr < _DATE_MIN or yr > _DATE_MAX:
        raise IgrfOutOfRangeError(
            f"Fecha {yr:.2f} fuera de validez de {MODEL_NAME} (1900.0–2030.0)."
        )
    if not (-90.0 <= lat_deg <= 90.0):
        raise IgrfError(f"Latitud fuera de rango físico: {lat_deg}")
    if not (-180.0 <= lon_deg <= 360.0):
        raise IgrfError(f"Longitud fuera de rango físico: {lon_deg}")

    table = _load_table()
    coeffs = _coeffs_for_year(table, yr)
    gh = np.empty(coeffs.shape[0] + 1, dtype=np.float64)  # 1-indexado
    gh[0] = 0.0
    gh[1:] = coeffs

    alt_km = float(alt_m) / 1000.0
    x, y, z = _synthesize(gh, table.nmax, alt_km, float(lat_deg), float(lon_deg))

    h = math.hypot(x, y)
    f = math.sqrt(x * x + y * y + z * z)
    dec = math.degrees(math.atan2(y, x))
    inc = math.degrees(math.atan2(z, h))
    return IgrfResult(
        inclination_deg=inc,
        declination_deg=dec,
        total_intensity_nt=f,
        horizontal_nt=h,
        north_nt=x,
        east_nt=y,
        down_nt=z,
    )
