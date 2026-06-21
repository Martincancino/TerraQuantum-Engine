"""FASE R4 — Paquete CSV auto-contenido (ensamblar + leer).

Un "paquete CSV" es UN solo archivo de texto que lleva, en un encabezado de
comentarios, toda la configuración de inversión + los sondajes + el plan
multimodal decidido; y debajo, las filas de estaciones ya normalizadas como un
CSV importable por `import_gravity_csv_v1`. Así la PREPARACIÓN (que decide combo,
normaliza y empaqueta) queda desacoplada de la CARGA 3D (que solo lee el paquete
y rutea al solver correcto).

Formato (líneas de encabezado prefijadas con '#', luego el CSV):

    #TQPKG/1
    #CONFIG {"data_type": "gravity", "region": "norte_chile", ...}
    #BOREHOLES [{"x_m": ..., "z_m": ..., "y_from_m": ..., "y_to_m": ..., "density_t_m3": ...}]
    #PLAN {"route": "gravity_only", "confidence": 0.7, ...}
    station_id,x_m,y_m,z_m,g_mgal,unit,gravity_type,sigma_mgal,elevation_m,magnetic_nt
    ST0001,...

El cuerpo es un CSV VÁLIDO para el import (incluye columnas `unit` y
`gravity_type`, que el import exige en gravimetría). No recalcula física: refleja
exactamente lo que consumirá el solver. La carga separa el encabezado del cuerpo,
escribe el cuerpo como CSV puro y lo pasa por el mismo import que `/invert`.
"""
from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass, field
from typing import Optional

PACKAGE_MAGIC = "#TQPKG"
PACKAGE_VERSION = 1
_MAGIC_LINE = f"{PACKAGE_MAGIC}/{PACKAGE_VERSION}"
_CFG_PREFIX = "#CONFIG "
_BH_PREFIX = "#BOREHOLES "
_PLAN_PREFIX = "#PLAN "

# Marcadores de columnas/valores que garantizan el round-trip por el import.
_UNIT_MGAL = "mGal"
# Anomalía ya corregida: el import NO vuelve a aplicar correcciones sobre ella
# y es un valor válido de ALLOWED_GRAVITY_TYPES.
_GRAVITY_TYPE = "bouguer_anomaly"

# Defaults de configuración (espejo de los Form params de /invert). 0 en grilla =
# el backend deriva el auto_grid del CSV al cargar.
_CONFIG_DEFAULTS: dict = {
    "data_type": "gravity",       # "gravity" | "magnetic"
    "region": "norte_chile",
    "lat": None,
    "lon": None,
    "nir": 83,
    "fe": 79,
    "nx": 0,
    "ny": 0,
    "nz": 0,
    "block_size": 0,
    "depth": 0,
    "cutoff_radius": 0.0,
    "lambda_mag": 0.0,
    "alpha_spatial": 1.0,
    "density_min": 0.0,
    "density_max": 5.5,
    "gravimeter_type": "unknown",
    "inclination_deg": -30.0,
    "declination_deg": 2.0,
    "field_intensity_nt": 23500.0,
    "survey_date": None,  # fecha del survey (año o ISO) para derivar el IGRF offline
    "susc_min": 0.0,
    "susc_max": 1.0,
    "padding_kappa": 1e5,
    "anchor_kappa": 1e4,
    "auto_kappa": True,
    "strict": True,
    "allow_g_raw": False,
    "utm_zone": None,
    "acknowledge_spatial_risk": False,
    "acknowledge_regional_scale": False,
    # Fase 7B — params avanzados (objetos anidados; None = desactivado).
    "pgi_params": None,
    "remanence": None,
}


def merge_config(overrides: "Optional[dict]") -> dict:
    """Config final = defaults + overrides (solo claves conocidas)."""
    cfg = dict(_CONFIG_DEFAULTS)
    for k, v in (overrides or {}).items():
        if k in _CONFIG_DEFAULTS:
            cfg[k] = v
    return cfg


@dataclass
class ParsedPackage:
    config: dict
    boreholes: list = field(default_factory=list)
    plan: dict = field(default_factory=dict)
    body_csv: str = ""

    @property
    def data_type(self) -> str:
        return str(self.config.get("data_type", "gravity"))


def _fmt(v) -> str:
    if v is None:
        return ""
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(fv):
        return ""
    return f"{fv:.6g}"


def _parallel(lst: "Optional[list]", n: int) -> "Optional[list]":
    return lst if (lst is not None and len(lst) == n) else None


def _estimate_station_tolerance(primary_obs: list) -> float:
    """Tolerancia de co-localización (m) derivada del espaciamiento del survey.

    Para surveys idénticos (mismas coords) el match es exacto (dist 0); la
    tolerancia solo absorbe ruido de proyección. Heurística: media de las
    distancias al vecino más cercano · 0.5, con piso de 1 m.
    """
    n = len(primary_obs)
    if n < 2:
        return 1.0
    nn = []
    for i, p in enumerate(primary_obs):
        best = None
        for j, q in enumerate(primary_obs):
            if i == j:
                continue
            d = math.hypot(p.x_m - q.x_m, p.z_m - q.z_m)
            if best is None or d < best:
                best = d
        if best is not None and math.isfinite(best):
            nn.append(best)
    if not nn:
        return 1.0
    nn.sort()
    median_nn = nn[len(nn) // 2]
    return max(1.0, 0.5 * median_nn)


def align_magnetic_to_stations(
    primary_obs: list,
    mag_obs: list,
    *,
    tol_m: "Optional[float]" = None,
) -> list:
    """Alinea valores TMI (nT) a las estaciones primarias por COORDENADA (x,z).

    No asume orden ni cardinalidad idéntica: para cada estación gravimétrica busca
    la magnetométrica más cercana y la acepta si cae dentro de `tol_m`. Las
    estaciones magnéticas sobrantes se ignoran. Si alguna estación gravimétrica no
    tiene magnetometría co-localizada dentro de tolerancia, lanza ValueError
    (no se inventa el dato por interpolación).

    Returns:
        Lista de TMI (float) paralela a `primary_obs`.
    """
    if not mag_obs:
        raise ValueError("El CSV magnético no contiene estaciones.")
    if tol_m is None:
        tol_m = _estimate_station_tolerance(primary_obs)

    out: list = []
    unmatched = 0
    for p in primary_obs:
        best = None
        best_d = None
        for m in mag_obs:
            d = math.hypot(p.x_m - m.x_m, p.z_m - m.z_m)
            if best_d is None or d < best_d:
                best_d = d
                best = m
        if best is not None and best_d is not None and best_d <= tol_m:
            out.append(float(best.g))
        else:
            unmatched += 1
            out.append(0.0)
    if unmatched > 0:
        raise ValueError(
            f"{unmatched}/{len(primary_obs)} estaciones gravimétricas no tienen "
            f"magnetometría co-localizada dentro de {tol_m:.1f} m. Para la inversión "
            "conjunta los surveys deben compartir ubicaciones (no se interpola)."
        )
    return out


def build_package_text(
    *,
    primary_result,
    data_type: str,
    config: dict,
    magnetic_values: "Optional[list]" = None,
    boreholes: "Optional[list]" = None,
    plan: "Optional[dict]" = None,
    override_elevations: "Optional[list]" = None,
    override_sigmas: "Optional[list]" = None,
    override_latlon: "Optional[list]" = None,
    override_g_mgal: "Optional[list]" = None,
    gravity_type_out: "Optional[str]" = None,
) -> str:
    """Ensambla el texto del paquete a partir de un GravityImportResult normalizado.

    Args:
        primary_result: GravityImportResult del archivo primario (grav o mag).
        data_type: "gravity" | "magnetic".
        config: dict de configuración (ver _CONFIG_DEFAULTS); se serializa al header.
        magnetic_values: valores TMI (nT) alineados a las estaciones primarias para
            la inversión CONJUNTA (cuando el primario es gravedad y se anexa una
            magnetometría co-localizada). Ignorado en modo magnetic.
        boreholes: lista de intervalos de sondaje (dicts) para el header.
        plan: dict del plan multimodal (advisory) para el header.
        override_elevations / override_sigmas / override_latlon / override_g_mgal:
            columnas DERIVADAS por el pipeline de enriquecimiento (csv_enrichment_
            service). Cuando se proveen (paralelas a las estaciones), tienen prioridad
            sobre lo que trae `primary_result` (p.ej. elevación del DEM, σ del
            gravímetro, gravedad reducida a Bouguer). None = usar el dato original.
        gravity_type_out: tipo de gravedad de salida tras correcciones (p.ej.
            "bouguer_anomaly") cuando `override_g_mgal` lleva la gravedad ya reducida.

    Returns:
        El paquete completo como texto (encabezado de comentarios + CSV).
    """
    is_magnetic = (data_type == "magnetic")
    obs = list(primary_result.observations or [])
    n = len(obs)

    elevs = _parallel(override_elevations, n) or _parallel(
        getattr(primary_result, "station_elevations", None), n
    )
    sigmas = _parallel(override_sigmas, n) or _parallel(
        getattr(primary_result, "station_uncertainties", None), n
    )
    latlon = _parallel(override_latlon, n) or _parallel(
        getattr(primary_result, "raw_latlon_elev", None), n
    )
    g_override = _parallel(override_g_mgal, n)
    gravity_type_value = gravity_type_out or _GRAVITY_TYPE

    # Magnetometría co-localizada para joint: prioridad al argumento explícito,
    # luego a la columna magnética que el import haya capturado del CSV gravimétrico.
    mags = None
    if not is_magnetic:
        mags = magnetic_values if magnetic_values is not None else getattr(primary_result, "magnetic_values", None)
        mags = _parallel(mags, n)

    # ── Columnas del cuerpo ──────────────────────────────────────────────────
    if is_magnetic:
        headers = ["station_id", "x_m", "y_m", "z_m", "tmi_nt"]
    else:
        headers = ["station_id", "x_m", "y_m", "z_m", "g_mgal", "unit", "gravity_type"]
        if sigmas is not None:
            headers.append("sigma_mgal")
    if elevs is not None:
        headers.append("elevation_m")
    if latlon is not None:
        headers += ["lat_deg", "lon_deg"]
    if not is_magnetic and mags is not None:
        headers.append("magnetic_nt")

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(headers)
    for i, o in enumerate(obs):
        if is_magnetic:
            # En modo magnético el import deja la TMI (nT) tal cual en el slot g.
            row = [f"ST{i + 1:04d}", _fmt(o.x_m), _fmt(o.y_m), _fmt(o.z_m), _fmt(o.g)]
        else:
            # En modo gravedad el import almacena g en m/s² → ×1e5 para mGal. Si el
            # enriquecimiento ya redujo la gravedad (Bouguer), se usa override_g_mgal.
            g_val = g_override[i] if g_override is not None else o.g * 1e5
            row = [
                f"ST{i + 1:04d}", _fmt(o.x_m), _fmt(o.y_m), _fmt(o.z_m),
                _fmt(g_val), _UNIT_MGAL, gravity_type_value,
            ]
            if sigmas is not None:
                row.append(_fmt(sigmas[i]))
        if elevs is not None:
            row.append(_fmt(elevs[i]))
        if latlon is not None:
            ll = latlon[i] or {}
            row += [_fmt(ll.get("lat_deg")), _fmt(ll.get("lon_deg"))]
        if not is_magnetic and mags is not None:
            row.append(_fmt(mags[i]))
        writer.writerow(row)

    body_csv = buf.getvalue()

    # ── Encabezado de metadatos ──────────────────────────────────────────────
    cfg = merge_config(config)
    cfg["data_type"] = data_type
    head = io.StringIO()
    head.write(_MAGIC_LINE + "\n")
    head.write(_CFG_PREFIX + json.dumps(cfg, ensure_ascii=False, separators=(",", ":")) + "\n")
    head.write(_BH_PREFIX + json.dumps(boreholes or [], ensure_ascii=False, separators=(",", ":")) + "\n")
    head.write(_PLAN_PREFIX + json.dumps(plan or {}, ensure_ascii=False, separators=(",", ":")) + "\n")
    return head.getvalue() + body_csv


def parse_package_text(text: str) -> ParsedPackage:
    """Separa encabezado (config/boreholes/plan) del cuerpo CSV.

    Lanza ValueError si el archivo no es un paquete TQPKG válido o si falta el
    cuerpo de datos. El cuerpo devuelto es un CSV puro (sin líneas de comentario),
    listo para `import_gravity_csv_v1`.
    """
    lines = (text or "").splitlines()
    if not lines or not lines[0].startswith(PACKAGE_MAGIC):
        raise ValueError("El archivo no es un paquete TQPKG válido (falta encabezado #TQPKG).")

    # Versión: #TQPKG/<n>
    version_token = lines[0].split("/", 1)
    if len(version_token) == 2:
        try:
            ver = int(version_token[1])
        except ValueError:
            ver = None
        if ver is not None and ver != PACKAGE_VERSION:
            raise ValueError(
                f"Versión de paquete no soportada: {ver} (esperada {PACKAGE_VERSION})."
            )

    config: dict = {}
    boreholes: list = []
    plan: dict = {}
    body_lines: list = []

    for ln in lines[1:]:
        if ln.startswith(_CFG_PREFIX):
            config = json.loads(ln[len(_CFG_PREFIX):])
        elif ln.startswith(_BH_PREFIX):
            boreholes = json.loads(ln[len(_BH_PREFIX):])
        elif ln.startswith(_PLAN_PREFIX):
            plan = json.loads(ln[len(_PLAN_PREFIX):])
        elif ln.startswith("#"):
            continue  # comentario desconocido / línea de versión → se ignora
        else:
            body_lines.append(ln)

    # Quita líneas en blanco al final pero conserva la cabecera + filas.
    body_csv = "\n".join(body_lines).strip("\n")
    if not body_csv or len(body_csv.splitlines()) < 2:
        raise ValueError("El paquete no contiene filas de estaciones.")

    return ParsedPackage(
        config=merge_config(config),
        boreholes=boreholes or [],
        plan=plan or {},
        body_csv=body_csv + "\n",
    )
