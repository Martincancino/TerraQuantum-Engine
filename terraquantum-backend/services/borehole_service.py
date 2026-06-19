"""
FASE 20 — Integración de Sondajes (Borehole Integration)

Capa de servicio que conecta los datos de sondaje (CSV crudo) con el motor de
inversión existente. NO duplica la física: el anclaje real (strong soft constraint)
ya vive en `exploration/gravimetry.py` (FASE 8 Q4). Aquí se cubre todo lo que rodea
ese anclaje y que faltaba para un flujo industrial:

  1. Parseo de CSV de sondajes con auto-detección de columnas y unidades
     (metros / pies → metros).
  2. Mapeo profundidad → vóxeles de la grilla (mismo criterio que usa el solver),
     expuesto como función pura reutilizable.
  3. Detección de conflictos post-inversión: ρ_predicho[vóxel] vs ρ_sondaje.
  4. Litología → priors petrofísicos (PGI / GMM).

Convención de ejes del backend: x, z son horizontales (planta); y = profundidad,
positivo hacia abajo. Los sondajes soportados son VERTICALES (collar fijo en (x,z)).
"""
from __future__ import annotations

import csv
import io
import math
import re
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np

from schemas.geophysics_schema import BoreholeSample, BoreholeSurvey

# Conversión de unidades de longitud → metros
FEET_TO_M = 0.3048

# ── Tabla petrofísica por litología (FASE 20 Tarea 6) ───────────────────────
# Densidad (t/m³) y susceptibilidad magnética (SI) representativas. Valores de
# referencia bibliográfica (Telford et al. 1990; Clark 1997). Se usan para:
#   • Construir priors PGI cuando el sondaje trae litología pero no densidad.
#   • Completar density/susc faltante con un valor petrofísico razonable (flag).
# Las claves cubren español e inglés; la búsqueda es case-insensitive y por
# subcadena (p.ej. "magnetita masiva" → "magnetita").
LITHOLOGY_PROPERTIES: dict[str, dict[str, float]] = {
    # ── Roca huésped félsica ──
    "granite":     {"density_t_m3": 2.67, "susceptibility_si": 100e-6},
    "granito":     {"density_t_m3": 2.67, "susceptibility_si": 100e-6},
    "granodiorite":{"density_t_m3": 2.73, "susceptibility_si": 150e-6},
    "granodiorita":{"density_t_m3": 2.73, "susceptibility_si": 150e-6},
    "rhyolite":    {"density_t_m3": 2.55, "susceptibility_si": 50e-6},
    "riolita":     {"density_t_m3": 2.55, "susceptibility_si": 50e-6},
    # ── Roca intermedia / máfica ──
    "diorite":     {"density_t_m3": 3.10, "susceptibility_si": 200e-6},
    "diorita":     {"density_t_m3": 3.10, "susceptibility_si": 200e-6},
    "andesite":    {"density_t_m3": 2.70, "susceptibility_si": 1000e-6},
    "andesita":    {"density_t_m3": 2.70, "susceptibility_si": 1000e-6},
    "basalt":      {"density_t_m3": 2.90, "susceptibility_si": 2500e-6},
    "basalto":     {"density_t_m3": 2.90, "susceptibility_si": 2500e-6},
    "gabbro":      {"density_t_m3": 3.00, "susceptibility_si": 3000e-6},
    "gabro":       {"density_t_m3": 3.00, "susceptibility_si": 3000e-6},
    # ── Sedimentarias ──
    "sandstone":   {"density_t_m3": 2.45, "susceptibility_si": 30e-6},
    "arenisca":    {"density_t_m3": 2.45, "susceptibility_si": 30e-6},
    "limestone":   {"density_t_m3": 2.60, "susceptibility_si": 10e-6},
    "caliza":      {"density_t_m3": 2.60, "susceptibility_si": 10e-6},
    # ── Mena / minerales densos ──
    "magnetite":   {"density_t_m3": 4.80, "susceptibility_si": 0.5},
    "magnetita":   {"density_t_m3": 4.80, "susceptibility_si": 0.5},
    "hematite":    {"density_t_m3": 4.90, "susceptibility_si": 5e-3},
    "hematita":    {"density_t_m3": 4.90, "susceptibility_si": 5e-3},
    "pyrite":      {"density_t_m3": 4.90, "susceptibility_si": 1.5e-3},
    "pirita":      {"density_t_m3": 4.90, "susceptibility_si": 1.5e-3},
    "chalcopyrite":{"density_t_m3": 4.20, "susceptibility_si": 400e-6},
    "calcopirita": {"density_t_m3": 4.20, "susceptibility_si": 400e-6},
    "chromite":    {"density_t_m3": 4.55, "susceptibility_si": 3e-3},
    "cromita":     {"density_t_m3": 4.55, "susceptibility_si": 3e-3},
}

# Litología por defecto (roca huésped/estéril) usada como componente de fondo
# en el GMM cuando el sondaje aporta una sola clase.
_HOST_ROCK_DENSITY = 2.67  # t/m³ (granito/roca caja)


# ─────────────────────────────────────────────────────────────────────────
#  1) Lookup litología → propiedades petrofísicas
# ─────────────────────────────────────────────────────────────────────────
def lithology_properties(lithology: Optional[str]) -> Optional[dict[str, float]]:
    """Devuelve {density_t_m3, susceptibility_si} para una litología, o None.

    Búsqueda case-insensitive y por subcadena, de modo que descripciones
    compuestas ("brecha de magnetita", "granito alterado") resuelven a la clase
    base. None si la litología es desconocida o vacía.
    """
    if not lithology:
        return None
    key = lithology.strip().lower()
    if key in LITHOLOGY_PROPERTIES:
        return dict(LITHOLOGY_PROPERTIES[key])
    # Coincidencia por subcadena (la litología contiene una clave conocida)
    for name, props in LITHOLOGY_PROPERTIES.items():
        if name in key:
            return dict(props)
    return None


# ─────────────────────────────────────────────────────────────────────────
#  2) Parseo de CSV de sondajes
# ─────────────────────────────────────────────────────────────────────────
# Alias de columnas reconocidas (normalizadas a minúsculas, sin espacios).
_COL_ALIASES: dict[str, set[str]] = {
    "hole_id":          {"hole_id", "holeid", "bhid", "hole", "sondaje", "pozo", "dhid", "id"},
    "x_m":              {"x_m", "x", "easting", "este", "east", "x_local", "collar_x"},
    "z_m":              {"z_m", "z", "northing", "norte", "north", "z_local", "collar_z", "y", "y_m"},
    "depth_from_m":     {"depth_from_m", "depth_from", "from", "from_m", "desde", "depthfrom"},
    "depth_to_m":       {"depth_to_m", "depth_to", "to", "to_m", "hasta", "depthto"},
    "density_t_m3":     {"density_t_m3", "density", "densidad", "rho", "dens", "density_gcm3"},
    "density_uncertainty": {"density_uncertainty", "density_unc", "sigma_density", "dens_unc"},
    "lithology":        {"lithology", "litologia", "litho", "lito", "rock", "roca"},
    "susceptibility_si":{"susceptibility_si", "susceptibility", "susc", "suscept", "kappa", "chi"},
    "sample_type":      {"sample_type", "type", "tipo", "muestra"},
    "comment":          {"comment", "comentario", "nota", "notes", "obs"},
}


def _norm_header(name: str) -> str:
    return re.sub(r"[\s\-]+", "_", name.strip().lower())


def _strip_unit_suffix(norm: str) -> str:
    """Quita un sufijo de unidad de longitud del header normalizado para el match.

    p.ej. 'x_ft' → 'x', 'depth_from_feet' → 'depth_from', 'z_meters' → 'z'.
    El sufijo de unidad se usa por separado para la auto-detección de unidades.
    """
    return re.sub(r"_(ft|feet|foot|pies|pie|m|meter|meters|metro|metros)$", "", norm)


def _build_column_map(header: Sequence[str]) -> dict[str, int]:
    """Mapea nombre canónico → índice de columna en el header del CSV."""
    col_map: dict[str, int] = {}
    for idx, raw in enumerate(header):
        norm = _norm_header(raw)
        candidates = {norm, _strip_unit_suffix(norm)}
        for canon, aliases in _COL_ALIASES.items():
            if canon in col_map:
                continue
            if candidates & aliases:
                col_map[canon] = idx
                break
    return col_map


def _to_float(value: str) -> Optional[float]:
    if value is None:
        return None
    s = value.strip().replace(",", ".")
    if s == "" or s.lower() in {"na", "nan", "none", "null", "-"}:
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def parse_borehole_csv(
    csv_text: str,
    *,
    length_units: str = "m",
    crs: str = "local",
    datum_elevation_m: float = 0.0,
) -> BoreholeSurvey:
    """Parsea un CSV de sondajes a un BoreholeSurvey validado.

    Args:
        csv_text: contenido del CSV (texto). Detecta delimitador , ; o tab.
        length_units: "m" | "meters" | "ft" | "feet". Convierte x/z/depth a metros.
                      "auto" intenta inferir de la cabecera (sufijo _ft / _feet).
        crs / datum_elevation_m: metadatos de georreferencia.

    Returns:
        BoreholeSurvey con la lista de muestras. Lanza ValueError con mensaje
        descriptivo si faltan columnas obligatorias o no hay filas válidas.
    """
    if not csv_text or not csv_text.strip():
        raise ValueError(
            "El CSV de sondajes está vacío. Debe contener una cabecera y al menos una "
            "fila con hole_id, coordenadas (x/z), profundidad (from/to) y densidad o litología."
        )

    # Detección de delimitador
    sample = csv_text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","

    reader = csv.reader(io.StringIO(csv_text), delimiter=delimiter)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ValueError(
            "El CSV de sondajes no tiene filas de datos (solo cabecera o vacío). "
            "Agregue al menos una muestra de sondaje."
        )

    header = rows[0]
    col_map = _build_column_map(header)

    required = ["hole_id", "x_m", "z_m", "depth_from_m", "depth_to_m"]
    missing = [c for c in required if c not in col_map]
    if missing:
        raise ValueError(
            "Faltan columnas obligatorias en el CSV de sondajes: "
            f"{', '.join(missing)}. Columnas detectadas: {', '.join(header)}. "
            "Se requieren identificador (hole_id), coordenadas del collar (x/easting, z/northing) "
            "y el tramo de profundidad (depth_from, depth_to)."
        )
    if "density_t_m3" not in col_map and "lithology" not in col_map and "susceptibility_si" not in col_map:
        raise ValueError(
            "El CSV de sondajes no tiene ninguna columna de propiedad medida "
            "(density/densidad, susceptibility/susc ni lithology/litología). "
            "Al menos una es necesaria para que el sondaje aporte información."
        )

    # Resolución de unidades de longitud
    units = (length_units or "m").strip().lower()
    if units == "auto":
        joined = " ".join(_norm_header(h) for h in header)
        units = "ft" if re.search(r"(_ft|_feet|pies)\b", joined) else "m"
    if units in {"ft", "feet", "foot", "pies", "pie"}:
        scale = FEET_TO_M
    elif units in {"m", "meter", "meters", "metro", "metros"}:
        scale = 1.0
    else:
        raise ValueError(f"Unidad de longitud no soportada: '{length_units}'. Use 'm' o 'ft'.")

    samples: List[BoreholeSample] = []
    errors: List[str] = []

    def _cell(row: Sequence[str], canon: str) -> Optional[str]:
        idx = col_map.get(canon)
        if idx is None or idx >= len(row):
            return None
        return row[idx]

    for line_no, row in enumerate(rows[1:], start=2):
        hole_id = (_cell(row, "hole_id") or "").strip()
        x = _to_float(_cell(row, "x_m"))
        z = _to_float(_cell(row, "z_m"))
        d_from = _to_float(_cell(row, "depth_from_m"))
        d_to = _to_float(_cell(row, "depth_to_m"))
        if hole_id == "" or x is None or z is None or d_from is None or d_to is None:
            errors.append(f"fila {line_no}: faltan hole_id/coordenadas/profundidad")
            continue

        density = _to_float(_cell(row, "density_t_m3"))
        susc = _to_float(_cell(row, "susceptibility_si"))
        litho_raw = _cell(row, "lithology")
        lithology = litho_raw.strip() if litho_raw and litho_raw.strip() else None
        dens_unc = _to_float(_cell(row, "density_uncertainty"))
        sample_type_raw = (_cell(row, "sample_type") or "core").strip().lower()
        if sample_type_raw not in {"core", "cuttings", "downhole_density", "downhole_susc", "other"}:
            sample_type_raw = "other"
        comment = (_cell(row, "comment") or "").strip()

        # Conversión de unidades (longitudes)
        x *= scale
        z *= scale
        d_from *= scale
        d_to *= scale

        # Validaciones de rango antes de construir el modelo (mensajes claros)
        if d_to <= d_from:
            errors.append(
                f"fila {line_no} ({hole_id}): depth_to ({d_to:.2f}) <= depth_from ({d_from:.2f})"
            )
            continue
        if density is not None and not (0.0 < density <= 10.0):
            errors.append(
                f"fila {line_no} ({hole_id}): densidad {density} fuera de rango físico (0, 10] t/m³"
            )
            continue

        try:
            samples.append(
                BoreholeSample(
                    hole_id=hole_id,
                    x_m=x,
                    z_m=z,
                    depth_from_m=d_from,
                    depth_to_m=d_to,
                    sample_type=sample_type_raw,
                    density_t_m3=density,
                    density_uncertainty=dens_unc if dens_unc is not None else 0.15,
                    lithology=lithology,
                    susceptibility_si=susc,
                    comment=comment,
                )
            )
        except Exception as exc:  # validación pydantic
            errors.append(f"fila {line_no} ({hole_id}): {exc}")

    if not samples:
        raise ValueError(
            "No se pudo parsear ninguna muestra de sondaje válida. Detalles: "
            + "; ".join(errors[:10])
        )

    return BoreholeSurvey(holes=samples, crs=crs, datum_elevation_m=datum_elevation_m)


# ─────────────────────────────────────────────────────────────────────────
#  3) Mapeo profundidad → vóxeles (misma regla que el solver, función pura)
# ─────────────────────────────────────────────────────────────────────────
def map_interval_to_voxels(
    x_m: float,
    z_m: float,
    y_from_m: float,
    y_to_m: float,
    x_c: np.ndarray,
    y_c: np.ndarray,
    z_c: np.ndarray,
    dx: float,
) -> np.ndarray:
    """Índices de vóxeles que un intervalo vertical de sondaje ocupa en la grilla.

    Replica EXACTAMENTE el criterio de `solve_inversion_lsqr` (FASE 8 Q4):
      • Columna = vóxeles cuyo centro (x,z) cae dentro de la huella del sondaje
        (tolerancia dx/2 en cada eje horizontal).
      • Segmento = vóxeles de esa columna con centro y_c ∈ [y_from, y_to].
      • Si el intervalo es más corto que la celda (ningún centro cae dentro), se
        devuelve el vóxel de la columna más cercano al punto medio del intervalo
        (garantiza ≥1 vóxel por intervalo válido).

    x_c, y_c, z_c son arrays de la grilla COMPLETA (centros de vóxel). Devuelve un
    array de índices (posiblemente vacío si la columna cae fuera de la grilla).
    """
    x_c = np.asarray(x_c, dtype=np.float64)
    y_c = np.asarray(y_c, dtype=np.float64)
    z_c = np.asarray(z_c, dtype=np.float64)
    if y_to_m < y_from_m:
        y_from_m, y_to_m = y_to_m, y_from_m
    tol = dx / 2.0
    col = (np.abs(x_c - x_m) <= tol) & (np.abs(z_c - z_m) <= tol)
    if not np.any(col):
        return np.empty(0, dtype=np.int64)
    seg = col & (y_c >= y_from_m) & (y_c <= y_to_m)
    if not np.any(seg):
        y_mid = 0.5 * (y_from_m + y_to_m)
        c_idx = np.where(col)[0]
        near = int(c_idx[int(np.argmin(np.abs(y_c[c_idx] - y_mid)))])
        return np.array([near], dtype=np.int64)
    return np.where(seg)[0].astype(np.int64)


# ─────────────────────────────────────────────────────────────────────────
#  4) Detección de conflictos post-inversión
# ─────────────────────────────────────────────────────────────────────────
def detect_borehole_conflicts(
    intervals: Iterable,
    density_full: np.ndarray,
    x_c: np.ndarray,
    y_c: np.ndarray,
    z_c: np.ndarray,
    dx: float,
    *,
    threshold_t_m3: float = 0.5,
    warn_threshold_t_m3: float = 0.2,
) -> dict:
    """Compara la densidad recuperada con la medida en sondaje y reporta conflictos.

    Args:
        intervals: iterable de objetos con atributos
            x_m, z_m, y_from_m, y_to_m, density_t_m3 (BoreholeInterval) — los que
            no traen densidad se ignoran.
        density_full: densidad recuperada por vóxel (t/m³), grilla COMPLETA. NaN en aire.
        x_c, y_c, z_c, dx: geometría de la grilla COMPLETA.
        threshold_t_m3: |Δρ| por encima del cual se marca CONFLICT (default 0.5).
        warn_threshold_t_m3: |Δρ| por encima del cual se marca WARNING (default 0.2).

    Returns:
        dict con:
          status: "OK" | "WARNING" | "CONFLICT" | "NO_DATA"
          conflicts: lista de dicts por intervalo evaluado (hole_id opcional, profundidad,
                     ρ medida, ρ predicha, Δ, severidad).
          n_evaluated, n_conflicts, n_warnings, max_abs_diff
    """
    density_full = np.asarray(density_full, dtype=np.float64)
    conflicts: List[dict] = []
    n_conflicts = 0
    n_warnings = 0
    max_abs_diff = 0.0

    for it in intervals:
        rho_meas = getattr(it, "density_t_m3", None)
        if rho_meas is None:
            continue
        vox = map_interval_to_voxels(
            getattr(it, "x_m"), getattr(it, "z_m"),
            getattr(it, "y_from_m"), getattr(it, "y_to_m"),
            x_c, y_c, z_c, dx,
        )
        if vox.size == 0:
            conflicts.append({
                "hole_id": getattr(it, "hole_id", None),
                "depth_from_m": float(getattr(it, "y_from_m")),
                "depth_to_m": float(getattr(it, "y_to_m")),
                "density_measured_t_m3": float(rho_meas),
                "density_predicted_t_m3": None,
                "diff_t_m3": None,
                "severity": "OUT_OF_GRID",
                "message": (
                    f"El sondaje en (x={getattr(it, 'x_m'):.1f}, z={getattr(it, 'z_m'):.1f}) "
                    "cae fuera de la grilla de inversión; no se puede validar."
                ),
            })
            continue

        vals = density_full[vox]
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            rho_pred = None
            diff = None
            severity = "AIR_VOXEL"
            message = "Los vóxeles del intervalo quedaron en la máscara de aire (sin densidad)."
        else:
            rho_pred = float(np.mean(vals))
            diff = rho_pred - float(rho_meas)
            abs_diff = abs(diff)
            max_abs_diff = max(max_abs_diff, abs_diff)
            if abs_diff > threshold_t_m3:
                severity = "CONFLICT"
                n_conflicts += 1
                message = (
                    f"Conflicto: el modelo predice ρ={rho_pred:.2f} t/m³ pero el sondaje "
                    f"mide ρ={rho_meas:.2f} t/m³ (Δ={diff:+.2f}). Revise datos o densidades."
                )
            elif abs_diff > warn_threshold_t_m3:
                severity = "WARNING"
                n_warnings += 1
                message = (
                    f"Desacuerdo menor: modelo ρ={rho_pred:.2f} vs sondaje ρ={rho_meas:.2f} t/m³ "
                    f"(Δ={diff:+.2f}). Puede ser heterogeneidad local."
                )
            else:
                severity = "OK"
                message = f"Acuerdo: modelo ρ={rho_pred:.2f} ≈ sondaje ρ={rho_meas:.2f} t/m³."

        conflicts.append({
            "hole_id": getattr(it, "hole_id", None),
            "depth_from_m": float(getattr(it, "y_from_m")),
            "depth_to_m": float(getattr(it, "y_to_m")),
            "density_measured_t_m3": float(rho_meas),
            "density_predicted_t_m3": rho_pred,
            "diff_t_m3": diff,
            "severity": severity,
            "message": message,
        })

    n_evaluated = len(conflicts)
    if n_evaluated == 0:
        status = "NO_DATA"
    elif n_conflicts > 0:
        status = "CONFLICT"
    elif n_warnings > 0:
        status = "WARNING"
    else:
        status = "OK"

    return {
        "status": status,
        "conflicts": conflicts,
        "n_evaluated": n_evaluated,
        "n_conflicts": n_conflicts,
        "n_warnings": n_warnings,
        "max_abs_diff_t_m3": float(max_abs_diff),
        "threshold_t_m3": float(threshold_t_m3),
    }


# ─────────────────────────────────────────────────────────────────────────
#  5) Litología → priors PGI (GMM)
# ─────────────────────────────────────────────────────────────────────────
def lithology_to_pgi_params(
    lithologies: Sequence[str],
    *,
    default_std: float = 0.12,
    counts: Optional[Sequence[int]] = None,
) -> dict:
    """Construye parámetros de GMM (PGI) a partir de litologías de sondaje.

    Cada litología distinta reconocida aporta una componente Gaussiana centrada en
    su densidad petrofísica. Si solo hay una clase distinta se añade la roca huésped
    como componente de fondo (PGIEngine requiere K ≥ 2).

    Args:
        lithologies: lista de nombres de litología (pueden repetirse / desconocerse).
        default_std: σ de densidad por componente (t/m³).
        counts: pesos crudos opcionales (p.ej. nº de muestras por litología); si None
                cada litología distinta pesa por su frecuencia en la lista.

    Returns:
        dict con means, stds, weights (listas de igual longitud K, weights suman 1)
        y `lithologies` (nombres de las componentes, en orden de densidad creciente).
        Lanza ValueError si ninguna litología es reconocida.
    """
    freq: dict[str, float] = {}
    props_by_key: dict[str, dict[str, float]] = {}
    for i, lith in enumerate(lithologies):
        props = lithology_properties(lith)
        if props is None:
            continue
        key = lith.strip().lower()
        w = float(counts[i]) if counts is not None and i < len(counts) else 1.0
        freq[key] = freq.get(key, 0.0) + w
        props_by_key.setdefault(key, props)

    if not props_by_key:
        raise ValueError(
            "Ninguna de las litologías provistas es reconocida. Litologías soportadas: "
            + ", ".join(sorted(LITHOLOGY_PROPERTIES.keys()))
        )

    means: List[float] = []
    stds: List[float] = []
    weights: List[float] = []
    names: List[str] = []
    for key, props in props_by_key.items():
        means.append(float(props["density_t_m3"]))
        stds.append(default_std)
        weights.append(freq[key])
        names.append(key)

    # PGIEngine requiere ≥2 componentes → añadir roca huésped si solo hay una
    if len(means) == 1 and abs(means[0] - _HOST_ROCK_DENSITY) > 1e-6:
        means.append(_HOST_ROCK_DENSITY)
        stds.append(default_std)
        weights.append(max(sum(weights) * 0.5, 1.0))
        names.append("host_rock")

    # Ordenar por densidad creciente (convención del PGIEngine.fit_from_model)
    order = np.argsort(means)
    means = [means[i] for i in order]
    stds = [stds[i] for i in order]
    weights = [weights[i] for i in order]
    names = [names[i] for i in order]

    total = sum(weights)
    weights = [w / total for w in weights]

    return {"means": means, "stds": stds, "weights": weights, "lithologies": names}


def build_pgi_engine_from_lithology(
    lithologies: Sequence[str],
    *,
    alpha_pgi: float = 0.1,
    base_density: float = 2.67,
    default_std: float = 0.12,
):
    """Atajo: devuelve un PGIEngine listo a partir de litologías de sondaje."""
    from exploration.pgi_engine import PGIEngine

    params = lithology_to_pgi_params(lithologies, default_std=default_std)
    return PGIEngine(
        means=params["means"],
        stds=params["stds"],
        weights=params["weights"],
        alpha_pgi=alpha_pgi,
        base_density=base_density,
    )
