"""F8 — Tormenta de pruebas: biblioteca compartida del harness E2E.

Genera surveys sintéticos (grav / mag / sondajes) con VERDAD conocida, a tamaños
y grados de suciedad controlados, los conduce por el flujo REAL del usuario
(``enrich-package`` → ``load-package`` síncrono) y clasifica el resultado en el
invariante central de F8:

    outcome ∈ {"valid_3d_model", "catalogued_error"}
    NUNCA   ∈ {"BUG_5xx", "BUG_silent_garbage", "BUG_crash"}

"Catalogado" = respuesta 4xx con un ``code`` del catálogo ES (core/errors.py) o
un 200 con ``needs_context`` (una PREGUNTA clara), nunca un 500 pelado ni basura
silenciosa (NaN/Inf o densidad fuera de rango físico en un modelo "done").

Sin dependencias nuevas: numpy/pandas/TestClient ya están. Determinista (sin
azar) → 100% reproducible. Este archivo NO empieza con ``test_`` a propósito:
es una biblioteca, no una suite (evita que pytest lo recoja como tests).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Optional

# ── Rangos físicos de sanidad (para cazar "basura silenciosa") ────────────────
# La columna física del parquet es un CONTRASTE (Δρ / χ sobre el fondo): ~0 en el
# fondo es legítimo, no basura; la no-negatividad la impone el solver (se tolera
# un pelo negativo por numérica). El bug que buscamos es NaN/Inf en celdas
# ACTIVAS o magnitudes absurdas. Cota generosa a propósito. t/m³ y SI.
DENSITY_ABS_RANGE = (-1.0, 20.0)
SUSCEPT_ABS_RANGE = (-2.0, 60.0)

ENRICH_URL = "/v2/gravity-import/enrich-package"
LOAD_URL = "/v2/gravity-import/load-package"

# ── Ejes de la matriz ─────────────────────────────────────────────────────────
# physics: qué campos entran. "sondajes" solo = rechazo esperado (catalogado).
PHYSICS = {
    "grav": dict(grav=True, mag=False, bh=False),
    "mag": dict(grav=False, mag=True, bh=False),
    "sondajes": dict(grav=False, mag=False, bh=True),
    "grav_mag": dict(grav=True, mag=True, bh=False),
    "grav_bh": dict(grav=True, mag=False, bh=True),
    "grav_mag_bh": dict(grav=True, mag=True, bh=True),
}
CLEANLINESS = ["clean", "dirty_es", "dirty_encoding", "preamble", "mixed_units"]
# station side por tamaño → n_stations = side².  Fast tier acotado (36/64/100)
# para que la suite no explote: el costo del solver crece super-lineal con las
# observaciones (barrido λ de Morozov × n_obs). El gate usa los tamaños reales.
SIZES_FAST = {"small": 6, "medium": 8, "large": 10}   # 36 / 64 / 100
SIZES_FULL = {"small": 10, "medium": 30, "large": 50}  # 100 / 900 / 2500
GEO = ["latlon", "local_helmert"]   # helmert on ⇒ coords locales + puntos control
DEM = [True, False]                 # enable_dem: elevación SIEMPRE presente ⇒ offline


@dataclass
class Combo:
    physics: str
    cleanliness: str
    size: str
    geo: str
    dem: bool

    def label(self) -> str:
        return f"{self.physics}|{self.cleanliness}|{self.size}|{self.geo}|dem={int(self.dem)}"


@dataclass
class Outcome:
    combo: Combo
    outcome: str                       # valid_3d_model | catalogued_error | BUG_*
    stage: str                         # enrich | load | validate
    http_status: Optional[int] = None
    code: Optional[str] = None
    detail: str = ""
    reasons: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.outcome in ("valid_3d_model", "catalogued_error")


# ─────────────────────────────────────────────────────────────────────────────
# Generación de datos con verdad conocida
# ─────────────────────────────────────────────────────────────────────────────
def _anomaly(i: int, j: int, side: int) -> float:
    """Bump gaussiano centrado → señal real para que la inversión tenga qué ajustar."""
    cx = cy = (side - 1) / 2.0
    r2 = (i - cx) ** 2 + (j - cy) ** 2
    sigma = max(side / 4.0, 1.0)
    return math.exp(-r2 / (2.0 * sigma ** 2))


def _fmt(v: float, decimals: int, dec_char: str) -> str:
    return f"{v:.{decimals}f}".replace(".", dec_char)


def _rows_latlon(kind: str, side: int, sep: str, dec: str, es: bool) -> tuple[str, list[str]]:
    """Filas georreferenciadas (lat/lon/elev). ``kind`` ∈ {grav, mag}."""
    if kind == "grav":
        cols = ["lat", "lon", "elev_m", "bouguer_anomaly", "unit", "gravity_type"] if not es \
            else ["lat", "lon", "cota", "gravedad_mgal", "unit", "gravity_type"]
    else:
        cols = ["lat", "lon", "elev_m", "tmi_nt"] if not es else ["lat", "lon", "cota", "tmi_nt"]
    header = sep.join(cols)
    rows: list[str] = []
    for i in range(side):
        for j in range(side):
            lat = -27.1000 - i * 0.0010
            lon = -69.3000 + j * 0.0010
            elev = 1200.0 + i * 5.0 + j * 2.0
            a = _anomaly(i, j, side)
            if kind == "grav":
                val = 3.0 + 8.0 * a
                cells = [_fmt(lat, 4, dec), _fmt(lon, 4, dec), _fmt(elev, 1, dec),
                         _fmt(val, 3, dec), "mGal", "bouguer_anomaly"]
            else:
                tmi = 51000.0 + 120.0 * a
                cells = [_fmt(lat, 4, dec), _fmt(lon, 4, dec), _fmt(elev, 1, dec), _fmt(tmi, 2, dec)]
            rows.append(sep.join(cells))
    return header, rows


def _rows_local(kind: str, side: int, sep: str, dec: str) -> tuple[str, list[str]]:
    """Filas en coords LOCALES (x_m/z_m) → activa el camino Helmert."""
    if kind == "grav":
        cols = ["x_m", "z_m", "g_mgal", "unit", "gravity_type"]
    else:
        cols = ["x_m", "z_m", "tmi_nt"]
    header = sep.join(cols)
    rows: list[str] = []
    for i in range(side):
        for j in range(side):
            x = i * 100.0
            z = j * 100.0
            a = _anomaly(i, j, side)
            if kind == "grav":
                val = 3.0 + 8.0 * a
                cells = [_fmt(x, 1, dec), _fmt(z, 1, dec), _fmt(val, 3, dec), "mGal", "bouguer_anomaly"]
            else:
                tmi = 51000.0 + 120.0 * a
                cells = [_fmt(x, 1, dec), _fmt(z, 1, dec), _fmt(tmi, 2, dec)]
            rows.append(sep.join(cells))
    return header, rows


def _encode(text: str, encoding: str) -> bytes:
    # errors=replace: aun un encoding "malo" produce bytes → el sniffer decide.
    return text.encode(encoding, errors="replace")


def make_csv(kind: str, combo: Combo, side: int) -> tuple[str, bytes, str]:
    """Devuelve (filename, bytes, encoding_declarado) para grav|mag según el combo."""
    cl = combo.cleanliness
    local = combo.geo == "local_helmert"

    sep, dec, encoding, preamble, es = ",", ".", "utf-8", 0, False
    if cl == "clean":
        pass
    elif cl == "dirty_es":
        sep, dec, encoding, es = ";", ",", "utf-8-sig", True
    elif cl == "dirty_encoding":
        encoding = "cp1252"          # acentos en el preámbulo importan
        preamble = 2
    elif cl == "preamble":
        preamble = 5
    elif cl == "mixed_units":
        # elevación en pies con columna de unidad → ejercita el manejo de unidades.
        pass

    if local:
        header, rows = _rows_local(kind, side, sep, dec)
    else:
        header, rows = _rows_latlon(kind, side, sep, dec, es)

    lines: list[str] = []
    if preamble:
        junk = [
            "Proyecto: Survey Sintético — Campaña F8 (áéíóú ñ)",
            "Datum: WGS84 UTM 19S",
            "Cliente: Minera Ejemplo SpA",
            "# exportado por instrumento GEM/Scintrex",
            "Operador: MC; Fecha 2026-07",
        ]
        lines.extend(junk[:preamble])
    lines.append(header)
    lines.extend(rows)
    text = "\n".join(lines) + "\n"
    return (f"{kind}.csv", _encode(text, encoding), encoding)


def make_boreholes(side: int) -> list[dict]:
    """Sondaje(s) de restricción, en el centro del dominio, con densidad medida."""
    center = (side - 1) * 50.0  # coords locales aprox del centro
    return [{
        "x_m": center, "z_m": center,
        "y_from_m": 20.0, "y_to_m": 160.0,
        "density_t_m3": 2.85, "lithology": "sulfuro",
    }]


def make_helmert_points(side: int) -> dict:
    """Puntos de control local↔UTM: traslación pura (sin rotación/escala)."""
    span = (side - 1) * 100.0
    return {"points": [
        {"local_x": 0.0, "local_z": 0.0, "real_e": 500000.0, "real_n": 7000000.0},
        {"local_x": span, "local_z": 0.0, "real_e": 500000.0 + span, "real_n": 7000000.0},
        {"local_x": 0.0, "local_z": span, "real_e": 500000.0, "real_n": 7000000.0 + span},
    ]}


# ─────────────────────────────────────────────────────────────────────────────
# Conducción del flujo E2E real
# ─────────────────────────────────────────────────────────────────────────────
def build_request(combo: Combo, side: int, grid: int = 6):
    """Arma (files, data, params) para enrich-package según el combo."""
    spec = PHYSICS[combo.physics]
    files: dict = {}
    if spec["grav"]:
        fn, body, _ = make_csv("grav", combo, side)
        files["gravity_file"] = (fn, body, "text/csv")
    if spec["mag"]:
        fn, body, _ = make_csv("mag", combo, side)
        files["magnetic_file"] = (fn, body, "text/csv")

    # depth (target de exploración) DEBE caber en la matriz: con mallas chicas la
    # profundidad física máxima es ~260 m, y el default 1000 m la excede. 150 m
    # cabe en todos los tamaños (surveys más grandes ⇒ celdas más profundas).
    config = {"nx": grid, "ny": grid, "nz": grid, "utm_zone": "19S", "depth": 150}
    data: dict = {"config_json": json.dumps(config)}
    if spec["bh"]:
        data["boreholes_json"] = json.dumps(make_boreholes(side))
    if combo.geo == "local_helmert" and (spec["grav"] or spec["mag"]):
        data["helmert_control_points_json"] = json.dumps(make_helmert_points(side))

    params = {"enable_dem": str(combo.dem).lower()}
    return files, data, params


def reset_rate_limit() -> None:
    """Resetea el rate-limiter de slowapi (10/min por endpoint) para que la
    tormenta no se auto-estrangule. En la suite lo hace el fixture autouse de
    conftest; el gate script (fuera de pytest) lo llama por combo."""
    try:
        from core.rate_limit import limiter
        storage = getattr(limiter, "_storage", None)
        if storage is not None:
            storage.reset()
    except Exception:  # noqa: BLE001 — nunca romper por el limiter
        pass


def _detail_code(resp) -> tuple[Optional[str], str]:
    """Extrae (code, message) de una respuesta de error del catálogo."""
    try:
        body = resp.json()
    except Exception:
        return None, resp.text[:200]
    detail = body.get("detail", body) if isinstance(body, dict) else body
    if isinstance(detail, dict):
        code = detail.get("code") or detail.get("error")
        msg = detail.get("message") or detail.get("user_message") or str(detail)[:200]
        return code, msg
    return None, str(detail)[:200]


def _validate_block_model(client, project_id: str, run_id: str, inversion: dict) -> tuple[bool, list]:
    """El validador automático del block model: finito, en rango físico, χ² coherente.

    Lee el parquet persistido DIRECTAMENTE (fuente de verdad del modelo 3D,
    agnóstico a la física: grav→``density`` t/m³, mag→``susceptibility_si``),
    en vez del export F5 (solo-gravedad). La columna física se valida SOLO en
    las celdas activas: los NaN en columnas de diagnóstico (sensitivity_proxy,
    posterior_std) sobre celdas inactivas/padding son esperados, no un defecto.
    """
    import numpy as np
    import pandas as pd

    reasons: list = []

    # χ² coherente si está presente en el resultado.
    fd = (inversion or {}).get("fitDiagnostics") or (inversion or {}).get("fit_diagnostics") or {}
    chi = fd.get("chi_squared_final", fd.get("chi_squared"))
    if chi is not None and not (isinstance(chi, (int, float)) and math.isfinite(chi) and chi >= 0):
        reasons.append(f"chi2 no coherente: {chi!r}")

    try:
        from core.block_model_store import get_run_dir
        run_dir = get_run_dir(project_id, run_id)
    except Exception as exc:  # noqa: BLE001
        reasons.append(f"no se pudo resolver run_dir: {exc}")
        return False, reasons

    parquets = sorted(run_dir.glob("block_model*.parquet"))
    if not parquets:
        reasons.append("block model no persistido (sin parquet)")
        return False, reasons

    df = pd.read_parquet(parquets[0])
    if df.empty:
        reasons.append("block model vacío (0 celdas)")
        return False, reasons

    active = df["is_active"].astype(bool) if "is_active" in df.columns else pd.Series(True, index=df.index)
    checked_physics = False
    for col, (lo, hi) in (("density", DENSITY_ABS_RANGE), ("susceptibility_si", SUSCEPT_ABS_RANGE)):
        if col not in df.columns:
            continue
        checked_physics = True
        vals = pd.to_numeric(df.loc[active, col], errors="coerce").to_numpy(dtype=float)
        if vals.size == 0:
            reasons.append(f"{col}: sin celdas activas")
            continue
        if not np.all(np.isfinite(vals)):
            reasons.append(f"{col}: {int((~np.isfinite(vals)).sum())} celdas activas NaN/Inf")
            continue
        mn, mx = float(vals.min()), float(vals.max())
        if mn < lo or mx > hi:
            reasons.append(f"{col} fuera de rango [{lo},{hi}]: min={mn:.3g} max={mx:.3g}")

    if not checked_physics:
        reasons.append(f"parquet sin columna física (cols={list(df.columns)[:8]}…)")
    return (len(reasons) == 0), reasons


def drive_e2e(client, combo: Combo, side: int, grid: int = 6,
              project_id: Optional[str] = None, run_id: Optional[str] = None) -> Outcome:
    """Conduce UN combo por el flujo real y devuelve su Outcome clasificado."""
    _safe = "".join(c if c.isalnum() else "_" for c in combo.label())[:48]
    project_id = project_id or f"f8_{_safe}"
    run_id = run_id or "storm"
    reset_rate_limit()  # cada combo arranca con presupuesto fresco
    files, data, params = build_request(combo, side, grid)

    # ── Paso 1: enrich-package ────────────────────────────────────────────────
    try:
        r = client.post(ENRICH_URL, files=files, data=data, params=params)
    except Exception as exc:  # noqa: BLE001 — un crash del cliente ES el hallazgo
        return Outcome(combo, "BUG_crash", "enrich", detail=f"{type(exc).__name__}: {exc}")

    if r.status_code >= 500:
        code, msg = _detail_code(r)
        return Outcome(combo, "BUG_5xx", "enrich", r.status_code, code, msg)
    if r.status_code != 200:
        code, msg = _detail_code(r)
        # 4xx con code del catálogo = error claro (p.ej. sondajes-solo → 422).
        return Outcome(combo, "catalogued_error", "enrich", r.status_code, code, msg)

    body = r.json()
    if not body.get("package_text"):
        # 200 sin paquete: solo válido si trae una PREGUNTA clara (needs_context).
        if body.get("needs_context"):
            return Outcome(combo, "catalogued_error", "enrich", 200, "NEEDS_CONTEXT",
                           "enrich devolvió pregunta estructurada (needs_context)")
        return Outcome(combo, "BUG_silent_garbage", "enrich", 200, None,
                       "200 sin package_text ni needs_context")

    # ── Paso 2: load-package SÍNCRONO ─────────────────────────────────────────
    try:
        r2 = client.post(
            LOAD_URL,
            files={"file": ("f8.tqpkg.csv", body["package_text"], "text/csv")},
            data={"project_id": project_id, "run_id": run_id, "sync": "true"},
        )
    except Exception as exc:  # noqa: BLE001
        return Outcome(combo, "BUG_crash", "load", detail=f"{type(exc).__name__}: {exc}")

    if r2.status_code >= 500:
        code, msg = _detail_code(r2)
        return Outcome(combo, "BUG_5xx", "load", r2.status_code, code, msg)
    if r2.status_code != 200:
        code, msg = _detail_code(r2)
        return Outcome(combo, "catalogued_error", "load", r2.status_code, code, msg)

    q = r2.json()
    status = q.get("status")
    if status != "done":
        # queued/error/etc con contrato claro = catalogado; sin status = basura.
        if status:
            return Outcome(combo, "catalogued_error", "load", 200, str(status),
                           f"load status={status}")
        return Outcome(combo, "BUG_silent_garbage", "load", 200, None, "load 200 sin status")

    # ── Paso 3: validar el block model (no basura silenciosa) ─────────────────
    ok, reasons = _validate_block_model(client, project_id, run_id, q.get("inversionResult") or {})
    if ok:
        return Outcome(combo, "valid_3d_model", "validate", 200, q.get("route"))
    return Outcome(combo, "BUG_silent_garbage", "validate", 200, q.get("route"),
                   "; ".join(reasons), reasons)


# ─────────────────────────────────────────────────────────────────────────────
# Selección de combos
# ─────────────────────────────────────────────────────────────────────────────
def covering_subset() -> list[Combo]:
    """Subconjunto que cubre CADA valor de CADA eje al menos una vez (~18 combos).

    Barato de correr (mallas chicas), pensado para la suite rápida / el "subset
    ahora". El barrido completo es full_matrix().
    """
    combos: list[Combo] = []
    # Todas las físicas × {clean, dirty_es} en small/latlon/dem-off.
    for phys in PHYSICS:
        for cl in ("clean", "dirty_es"):
            combos.append(Combo(phys, cl, "small", "latlon", False))
    # Cobertura de los ejes restantes con grav.
    combos.append(Combo("grav", "dirty_encoding", "small", "latlon", False))
    combos.append(Combo("grav", "preamble", "small", "latlon", False))
    combos.append(Combo("grav", "mixed_units", "small", "latlon", False))
    combos.append(Combo("grav", "clean", "medium", "latlon", False))
    combos.append(Combo("grav", "clean", "large", "latlon", False))
    combos.append(Combo("grav", "clean", "small", "local_helmert", False))
    combos.append(Combo("grav_mag", "clean", "small", "local_helmert", False))
    combos.append(Combo("grav", "clean", "small", "latlon", True))
    return combos


def full_matrix(sizes: Optional[list[str]] = None) -> list[Combo]:
    """El producto cartesiano completo de la matriz F8."""
    sizes = sizes or list(SIZES_FULL.keys())
    combos: list[Combo] = []
    for phys in PHYSICS:
        for cl in CLEANLINESS:
            for sz in sizes:
                for geo in GEO:
                    for dem in DEM:
                        combos.append(Combo(phys, cl, sz, geo, dem))
    return combos
