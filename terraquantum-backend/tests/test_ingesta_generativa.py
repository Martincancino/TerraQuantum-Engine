"""F2.6(b) — Tests GENERATIVOS de ingesta: mutador de CSVs válidos con verdad.

GATE F2: 0 excepciones no-catalogadas en ≥10.000 casos y 0 corrupción
silenciosa. El mutador (seed fija → 100% reproducible) toma un survey sintético
con GROUND TRUTH conocido y lo "ensucia" como los archivos reales del corpus:
encoding (UTF-8/BOM/cp1252/latin-1/UTF-16), separador (, ; tab |), decimal
(./,), preámbulos de proyecto, filas rotas, filas de metadata, líneas en
blanco, headers ES/EN con unidad embebida o columna de unidad.

Contrato verificado POR CASO:
  1. import_gravity_csv_v1 JAMÁS lanza (el harness reporta seed reproducible).
  2. status == "ok" (todos los casos son importables por diseño) con TODAS las
     filas válidas recuperadas.
  3. CERO corrupción silenciosa: los valores de gravedad recuperados (mGal) se
     comparan 1:1 contra la verdad del generador (el bug decimal-coma e7d2858
     producía E≈531 con sello "Calidad GOOD" — esto lo cazaría al instante).

Volumen: TQ_GEN_N (default 400 para la suite rápida; el gate corre 10.000).
Sin dependencia de hypothesis: mutador propio determinista (stdlib random).
"""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.gravity_import_service import import_gravity_csv_v1  # noqa: E402

N_CASES = int(os.environ.get("TQ_GEN_N", "400"))
SEED = 20260703

# ── Vocabulario de mutación (todo del corpus real) ───────────────────────────
_GRAV_COLS_MGAL_EMBEDDED = ["g_mgal", "bouguer_mgal", "Anom_Bouguer_mGal", "gravedad_mgal"]
_GRAV_COLS_PLAIN = ["bouguer_anomaly", "gravity_anomaly", "anomalia_bouguer", "gravity"]
_X_COLS = ["x_m"]
_Z_COLS = ["z_m"]
_ELEV_COLS = ["elevation", "cota_msnm", "elevacion_m", "elev_m"]
_STATION_COLS = ["station_id", "Estacion", "punto"]
_UNIT_COLS = ["unit", "Unidad"]
_PREAMBLES = [
    "Proyecto: Survey Sintetico - Campana 2026",
    "Datum: WGS84 UTM 19S",
    "Cliente: Minera Ejemplo SpA;;;;",
    "# comentario de exportador",
    "Fecha: 2026-07;Operador: MC;;",
]
_ENCODINGS = ["utf-8", "utf-8-sig", "cp1252", "latin-1", "utf-16"]
_SEPS = [",", ";", "\t", "|"]


def _fmt_num(value: float, decimals: int, decimal_char: str) -> str:
    s = f"{value:.{decimals}f}"
    return s.replace(".", decimal_char)


def _generate_case(rng: random.Random):
    """Devuelve (payload_bytes, filename, truth) — truth = lista de g_mgal."""
    n = rng.randint(12, 24)
    sep = rng.choice(_SEPS)
    # Decimal coma solo donde no colisiona con el separador.
    decimal_char = rng.choice([".", ","]) if sep != "," else "."
    encoding = rng.choice(_ENCODINGS)
    # cp1252/latin-1 con texto ES real (acentos) para que el encoding importe.
    station_prefix = "Estación" if encoding in ("cp1252", "latin-1", "utf-16") else "ST"

    grav_col = rng.choice(_GRAV_COLS_MGAL_EMBEDDED + _GRAV_COLS_PLAIN)
    unit_embedded = "mgal" in grav_col.lower()
    include_unit_col = (not unit_embedded) or rng.random() < 0.5
    unit_col = rng.choice(_UNIT_COLS) if include_unit_col else None
    include_type_col = rng.random() < 0.5
    # Sin columna de tipo: el nombre debe permitir inferirlo o el import
    # no-estricto sigue igual (tipo None) — ambas rutas son válidas.
    include_elev = rng.random() < 0.6
    elev_col = rng.choice(_ELEV_COLS) if include_elev else None
    station_col = rng.choice(_STATION_COLS)

    headers = [station_col, rng.choice(_X_COLS), rng.choice(_Z_COLS)]
    if elev_col:
        headers.append(elev_col)
    headers.append(grav_col)
    if unit_col:
        headers.append(unit_col)
    if include_type_col:
        headers.append("gravity_type")

    truth: list = []
    data_rows: list = []
    for i in range(n):
        x = i * 100.0 + rng.randint(0, 40)          # únicos → sin duplicados
        z = (i % 6) * 150.0 + (i // 6) * 17.0
        g = round(rng.uniform(-80.0, 80.0), 4)
        truth.append(g)
        row = [f"{station_prefix}-{i:03d}", _fmt_num(x, 1, decimal_char),
               _fmt_num(z, 1, decimal_char)]
        if elev_col:
            row.append(_fmt_num(1000.0 + i * 3.0, 2, decimal_char))
        row.append(_fmt_num(g, 4, decimal_char))
        if unit_col:
            row.append("mGal")
        if include_type_col:
            row.append("bouguer_anomaly")
        data_rows.append(sep.join(row))

    lines: list = []
    # Preámbulo 0-3 líneas (basura de exportador, a veces con el separador).
    for _ in range(rng.randint(0, 3)):
        lines.append(rng.choice(_PREAMBLES))
    lines.append(sep.join(headers))

    body = list(data_rows)
    # Filas ROTAS 0-2: campo-count claramente distinto → pandas/validación las
    # descarta; la verdad NO las incluye.
    for _ in range(rng.randint(0, 2)):
        pos = rng.randint(0, len(body))
        body.insert(pos, sep.join(["basura"] * (len(headers) + 3)))
    # Fila de METADATA 0-1 (texto en columnas de coordenadas → se omite).
    if rng.random() < 0.3:
        meta = ["IGRF aplicado"] + ["n/a"] * (len(headers) - 1)
        body.insert(rng.randint(0, len(body)), sep.join(meta))
    # Líneas en blanco 0-2.
    for _ in range(rng.randint(0, 2)):
        body.insert(rng.randint(0, len(body)), "")

    lines.extend(body)
    text = "\r\n".join(lines) + "\r\n" if rng.random() < 0.5 else "\n".join(lines) + "\n"
    return text.encode(encoding), truth


def test_generative_ingesta_never_crashes_never_corrupts(tmp_path):
    rng = random.Random(SEED)
    failures: list = []
    for case_id in range(N_CASES):
        payload, truth = _generate_case(rng)
        path = tmp_path / f"gen_{case_id}.csv"
        path.write_bytes(payload)
        try:
            res = import_gravity_csv_v1(
                str(path), strict=False, allow_g_raw=True, data_kind="gravity",
            )
        except Exception as exc:  # noqa: BLE001 — el contrato dice JAMÁS
            failures.append(f"case={case_id}: EXCEPCIÓN {type(exc).__name__}: {exc}")
            continue
        finally:
            try:
                path.unlink()
            except OSError:
                pass

        if res.status != "ok":
            failures.append(
                f"case={case_id}: status=error (esperado ok): {res.errors[:2]}"
            )
            continue
        recovered = sorted(round(o.g * 1e5, 4) for o in res.observations)
        expected = sorted(truth)
        if len(recovered) != len(expected):
            failures.append(
                f"case={case_id}: {len(recovered)} obs recuperadas vs "
                f"{len(expected)} en la verdad (filas perdidas o fantasma)"
            )
            continue
        worst = max(
            abs(r - e) for r, e in zip(recovered, expected)
        ) if expected else 0.0
        if worst > 1e-3:
            failures.append(
                f"case={case_id}: CORRUPCIÓN SILENCIOSA — desviación máx "
                f"{worst:.6f} mGal vs verdad (¿decimales partidos?)"
            )

        if case_id and case_id % 1000 == 0:
            print(f"  … {case_id}/{N_CASES} casos verificados")

    assert not failures, (
        f"{len(failures)}/{N_CASES} casos violaron el contrato "
        f"(seed={SEED}, reproducible). Primeros:\n" + "\n".join(failures[:12])
    )
