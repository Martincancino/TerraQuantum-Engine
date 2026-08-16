# -*- coding: utf-8 -*-
"""FASE 8 — arnés de BYTE-IDENTIDAD para partir la espina dorsal.

La Fase 7 dejó un arnés (`fase8_byte_identity.py`'s hermano `fase7_byte_identity.py`)
que congela la salida de los MOTORES (`solve_inversion_lsqr`,
`solve_magnetic_inversion_lsqr`, …). Ese arnés NO defiende los dos primeros pasos
de la Fase 8, que ocurren por encima del motor:

  * `services/geophysics_service.py::run_geophysics_inversion` — 2.030 LOC, CC 183
  * `api/gravity_import_api.py::invert_gravity_csv`            —   927 LOC, 41 args

Medido antes de escribir esto: correr `fase7_byte_identity.py --check` sobre un
`run_geophysics_inversion` mutilado da **34/34 OK**. O sea: el instrumento de la
fase anterior no ve nada de lo que esta fase toca. Por eso existe este segundo
arnés, y por eso se congela ANTES de mover una sola línea.

Qué congela
-----------
1. **Servicio** (`run_geophysics_inversion`): el `result` COMPLETO —vóxeles y
   reporte— serializado de forma canónica y hasheado con SHA-256. Los `float`
   viajan por `repr()` (roundtrip exacto de float64), así que un cambio en el
   último bit rompe el hash igual que en el arnés de la Fase 7.
2. **Parquet de la corrida**: los bits de las columnas numéricas del block model
   escrito en disco (`density`, `doi_index`, `posterior_std`, `sensitivity_proxy`,
   …). Es el producto real, y contiene números que el `result` HTTP no lleva.
3. **API** (`invert_gravity_csv`): la respuesta JSON del endpoint por
   `TestClient`, con el mismo tratamiento. Cubre el paso 2 de la fase —agrupar
   los 41 parámetros— donde lo que hay que defender es el CONTRATO, no sólo la
   aritmética.

Lo volátil se restriega, no se tolera
------------------------------------
Rutas absolutas, timestamps, hash de git y duraciones cambian entre corridas sin
que cambie el resultado. En vez de comparar con tolerancia (que es justo lo que
esconde el error que esta fase puede introducir), se ELIMINAN por nombre de clave
y se normalizan las cadenas que son rutas. Todo lo demás se compara bit a bit.

`TERRAQUANTUM_DATA_DIR` se fija a un directorio de scratch ANTES de importar nada
del proyecto: el arnés no escribe en `data/` del repositorio.

Uso:
    python scripts/validation/fase8_byte_identity.py --freeze   # ANTES de tocar
    python scripts/validation/fase8_byte_identity.py --check    # DESPUÉS
    python scripts/validation/fase8_byte_identity.py --check --only servicio/
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import sys
import traceback
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

# ── aislamiento de disco: ANTES de importar core.config ──────────────────────
_SCRATCH = BACKEND_ROOT / "tmp" / "fase8_byte_identity_data"
os.environ["TERRAQUANTUM_DATA_DIR"] = str(_SCRATCH)
# El middleware de auth se apaga explícitamente: la Fase 5 midió que la variable
# VACÍA lo ENCENDÍA (invert 404→401), y un 401 congelado sería un baseline inútil.
os.environ["TQ_AUTH_ENABLED"] = "false"

import numpy as np  # noqa: E402

BASELINE = Path(__file__).resolve().parent / "fase8_byte_identity_baseline.json"

#: Casos que se MIDEN pero NO deciden, porque son inestables por sí mismos.
#:
#: `api/invert_auto_lambda` (Morozov por HTTP) devuelve dos resultados distintos
#: con entrada byte-idéntica: tres corridas seguidas del MISMO código dieron
#: `76434aaf…`, `f7848157…`, `f7848157…`. No es el refactor de la Fase 8 — dos de
#: las tres reproducen exactamente la línea base anterior a tocar nada, y el caso
#: equivalente a nivel de servicio (`servicio/lambda_morozov`, que también corre
#: Morozov) es estable en todas las corridas medidas.
#:
#: O sea: **el mismo CSV y el mismo formulario pueden dar dos modelos distintos**
#: por la ruta HTTP. Es un hallazgo del producto, no del arnés, y merece su propia
#: investigación (la Fase 8 tiene prohibido cambiar comportamiento). Se deja
#: MIDIÉNDOSE —el hash se imprime y se congela— pero fuera del veredicto: un gate
#: que falla una de cada tres veces sin que nadie haya tocado nada es un gate que
#: se acaba desactivando, y entonces no defiende lo que sí es estable.
INESTABLES = {"api/invert_auto_lambda"}

NX = NY = NZ = 6
BLOCK = 25.0
CUTOFF = 400.0
BASE_DENSITY = 2.6
SEED = 20260815


# ── huella canónica ──────────────────────────────────────────────────────────

# Claves cuyo VALOR cambia entre corridas idénticas (ruta absoluta, reloj, git).
_VOLATILES = {
    "parquet_path", "parquetPath", "anomalyPath", "legacyBlockModelPath",
    "blockModelPath", "block_model_path", "focusing_parquet_path", "vtr_path",
    "zarr_path", "npz_path", "vdb_path", "path", "sourceGravityPath",
    "metadataPath", "elapsed_seconds", "timestamp_utc_start", "timestamp_utc_end",
    "code_version", "stored_at_utc", "created_at", "updated_at", "run_id",
    "project_id", "sha256_parquet", "sha256_csv", "original_filename",
    "stored_source_file",
}

# El endpoint guarda el CSV en `tmp/<uuid>.csv` y publica ese nombre en
# `importMetadata.source_file`: cambia en cada petición sin que cambie nada del
# resultado. Se normaliza el VALOR (no se borra la clave) igual que las fechas.
_UUID = __import__("re").compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

_SUFIJOS_RUTA = (".parquet", ".json", ".csv", ".vtr", ".npz", ".vdb", ".zarr")

# Un reloj no es un resultado. Se NORMALIZA el valor en vez de borrar la clave,
# para que la PRESENCIA del campo siga comparándose (medido: la única fuente de
# no-determinismo del payload era `favorability.computed_at`).
_ISO_FECHA = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")


def _canon(obj):
    """Estructura equivalente sin partes volátiles y con numpy convertido."""
    if isinstance(obj, dict):
        return {k: _canon(v) for k, v in sorted(obj.items()) if k not in _VOLATILES}
    if isinstance(obj, (list, tuple)):
        return [_canon(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return [_canon(v) for v in obj.tolist()]
    if isinstance(obj, Path):
        return "<ruta>"
    if isinstance(obj, str):
        # Una ruta absoluta depende de la máquina; su PRESENCIA sí se conserva.
        if obj.endswith(_SUFIJOS_RUTA) and ("/" in obj or "\\" in obj):
            return "<ruta>"
        if _ISO_FECHA.match(obj):
            return "<fecha>"
        if _UUID.match(obj):
            return "<uuid>"
        return obj
    if hasattr(obj, "model_dump"):
        return _canon(obj.model_dump())
    return obj


def _sha_json(obj) -> str:
    """SHA-256 del JSON canónico. `repr` de float64 es roundtrip exacto."""
    txt = json.dumps(_canon(obj), sort_keys=True, ensure_ascii=False,
                     allow_nan=True, separators=(",", ":"), default=str)
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()


def _sha_arrays(*arrays) -> str:
    h = hashlib.sha256()
    for a in arrays:
        arr = np.ascontiguousarray(np.asarray(a, dtype=np.float64))
        h.update(str(arr.shape).encode("utf-8"))
        h.update(arr.tobytes())
    return h.hexdigest()


def _sha_parquet(path: Path) -> str:
    """Bits de las columnas numéricas del block model (el producto real)."""
    import polars as pl
    df = pl.read_parquet(str(path))
    h = hashlib.sha256()
    for col in sorted(df.columns):
        s = df[col]
        h.update(col.encode("utf-8"))
        if s.dtype.is_numeric():
            h.update(np.ascontiguousarray(
                s.to_numpy().astype(np.float64)).tobytes())
        else:
            h.update(json.dumps(s.to_list(), default=str,
                                ensure_ascii=False).encode("utf-8"))
    return h.hexdigest()


# ── escenario sintético ──────────────────────────────────────────────────────

def _observaciones(amplitud: float = 0.8):
    """Survey + dato gravimétrico sintético reproducible sobre la grilla del servicio.

    El dato se genera con el MISMO operador forward que usa producción: lo que
    importa aquí no es la física (eso lo mide la Fase 4/F9) sino que el solver
    recorra ramas reales y no un caso degenerado.

    `amplitud` existe porque con el contraste débil (0,8) NINGÚN vóxel vivo supera
    el cutoff de 2,75 y el reporte se construye por una rama distinta — medido al
    congelar esta línea base. Con 3,0 la anomalía sí gana y el camino de reporte
    se recorre entero.
    """
    from exploration.gravimetry import GravimetryForward
    from schemas.geophysics_schema import GeophysicsInvertInput, GravityObservation
    from services.geophysics_service import build_voxel_grid

    obs0 = [
        GravityObservation(x_m=20.0 + i * 25.0, y_m=0.0, z_m=20.0 + j * 25.0, g=0.0)
        for i in range(6) for j in range(6)
    ]
    base = GeophysicsInvertInput(
        project_id=None, run_id=None,
        depth=int(NY * BLOCK), nir=50, fe=30, region="desconocida",
        lat="-23.5", lon="-70.2",
        nx=NX, ny=NY, nz=NZ, block_size=BLOCK, cutoff_radius=CUTOFF,
        lambda_mag=0.31623, alpha_spatial=1.0, observations=obs0,
    )
    _ix, _iy, _iz, x_c, y_c, z_c = build_voxel_grid(base)
    sensores = np.array([[o.x_m, o.y_m, o.z_m] for o in obs0], dtype=np.float64)

    cx = cz = NX * BLOCK / 2.0
    cuerpo = ((np.abs(x_c - cx) <= BLOCK) & (np.abs(z_c - cz) <= BLOCK)
              & (y_c >= 2 * BLOCK) & (y_c <= 3 * BLOCK))
    contraste = np.zeros(x_c.size, dtype=np.float64)
    contraste[cuerpo] = amplitud

    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF)
    g = np.asarray(fwd._build_sparse_kernel(x_c, y_c, z_c, sensores) @ contraste).ravel()
    rng = np.random.default_rng(SEED)
    g = g + 0.02 * float(np.max(np.abs(g))) * rng.standard_normal(g.size)

    obs = [
        GravityObservation(x_m=float(sensores[k, 0]), y_m=0.0,
                           z_m=float(sensores[k, 2]), g=float(g[k]))
        for k in range(len(obs0))
    ]
    return obs, sensores, x_c, y_c, z_c, contraste


_ESCENARIOS: dict = {}


def _escenario(amplitud: float = 0.8):
    if amplitud not in _ESCENARIOS:
        _ESCENARIOS[amplitud] = _observaciones(amplitud)
    return _ESCENARIOS[amplitud]


def _input(nombre: str, amplitud: float = 0.8, **kw):
    from schemas.geophysics_schema import GeophysicsInvertInput
    obs, _s, _x, _y, _z, _c = _escenario(amplitud)
    campos = dict(
        project_id="fase8", run_id=nombre.replace("/", "_"),
        depth=int(NY * BLOCK), nir=50, fe=30, region="desconocida",
        lat="-23.5", lon="-70.2",
        nx=NX, ny=NY, nz=NZ, block_size=BLOCK, cutoff_radius=CUTOFF,
        lambda_mag=0.31623, alpha_spatial=1.0, observations=obs,
        base_density=BASE_DENSITY, density_min=2.6, density_max=5.5,
    )
    campos.update(kw)
    return GeophysicsInvertInput(**campos)


def _elevaciones():
    """Relieve determinista por estación (activa la máscara topográfica)."""
    _o, sensores, _x, _y, _z, _c = _escenario()
    return [float(1000.0 + 0.05 * s[0] + 0.03 * s[2]) for s in sensores]


def _sondajes():
    from schemas.geophysics_schema import BoreholeInterval
    cx = cz = NX * BLOCK / 2.0
    return [BoreholeInterval(x_m=cx + BLOCK / 2, z_m=cz + BLOCK / 2,
                             y_from_m=2 * BLOCK, y_to_m=3 * BLOCK,
                             density_t_m3=BASE_DENSITY + 0.8)]


# ── casos de servicio ────────────────────────────────────────────────────────

def _correr_servicio(params) -> str:
    from core.config import PROJECTS_DIR
    from services.geophysics_service import run_geophysics_inversion

    res = run_geophysics_inversion(params)
    huellas = [_sha_json(res)]

    pq = PROJECTS_DIR / str(params.project_id) / "runs" / str(params.run_id) / "block_model.parquet"
    huellas.append(_sha_parquet(pq) if pq.is_file() else "sin_parquet")

    return hashlib.sha256("|".join(huellas).encode("utf-8")).hexdigest()


def _casos_servicio() -> list[tuple[str, callable]]:
    def caso(nombre, **kw):
        def _run():
            return _correr_servicio(_input(nombre, **kw))
        return (f"servicio/{nombre}", _run)

    return [
        # ── ruta base: λ fijo, topografía plana, sin extras ───────────────────
        caso("base"),
        caso("senal_fuerte", amplitud=3.0),
        # ── preparación de malla y topografía ─────────────────────────────────
        # `topografia` queda congelado COMO FALLO a propósito: con señal débil el
        # conjunto de anomalías se queda sólo con celdas de AIRE y el reporte
        # revienta con TypeError (ver el registro de la fase). Congelarlo obliga a
        # que el refactor conserve incluso ese comportamiento; arreglarlo es un
        # cambio de conducta y no entra en una fase de byte-identidad.
        caso("topografia", sensor_elevations_masl=_elevaciones()),
        caso("topografia_fuerte", amplitud=3.0,
             sensor_elevations_masl=_elevaciones()),
        caso("cutcell", sensor_elevations_masl=_elevaciones(),
             cut_cell_topography=True),
        # ── priors y anclajes ─────────────────────────────────────────────────
        caso("sondajes_soft", boreholes=_sondajes()),
        caso("sondajes_hard", boreholes=_sondajes(), anchor_mode="hard"),
        caso("depth_prior", enable_depth_prior=True),
        caso("kappa_no_auto", auto_kappa=False, padding_kappa=1e4,
             anchor_kappa=1e3),
        # ── selección de λ ────────────────────────────────────────────────────
        caso("lambda_operating_point", lambda_mag=0.0),
        caso("lambda_morozov", lambda_mag=0.0, gravimeter_type="scintrex_cg6"),
        caso("sigma_declarado", noise_floor_mgal=0.05, noise_pct_v2=0.01),
        # ── funcional del solver ──────────────────────────────────────────────
        caso("compact", regularization_norm="compact", compact_max_irls=4),
        caso("mixed", regularization_norm="mixed", compact_max_irls=3),
        caso("sin_robust_sigma", robust_sigma=False),
        # ── diagnósticos opt-in ───────────────────────────────────────────────
        caso("uq_posterior", compute_uncertainty=True),
        caso("drill_targets", compute_drill_targets=True, drill_targets_top_n=5),
        caso("ensemble", compute_ensemble_uncertainty=True, ensemble_n_shuttles=3),
        # ── ruteo por física ──────────────────────────────────────────────────
        caso("treemesh", use_treemesh=True),
        caso("magnetico", magnetic_nt=_tmi()),
    ]


def _tmi():
    """TMI sintética para el ruteo magnético (g=0 en el input → motor aislado)."""
    from exploration.magnetometry import MagnetometryForward
    _o, sensores, x_c, y_c, z_c, contraste = _escenario()
    fwd = MagnetometryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF,
                              inclination_deg=-30.0, declination_deg=2.0,
                              field_intensity_nt=23500.0)
    susc = np.where(contraste > 0, 0.05, 0.0)
    d = np.asarray(fwd._build_sparse_kernel(x_c, y_c, z_c, sensores) @ susc).ravel()
    rng = np.random.default_rng(SEED + 1)
    d = d + 0.02 * float(np.max(np.abs(d))) * rng.standard_normal(d.size)
    return [float(v) for v in d]


def _casos_servicio_magnetico() -> list[tuple[str, callable]]:
    """El ruteo magnético vive DENTRO de `run_geophysics_inversion`: g debe ser 0."""
    from schemas.geophysics_schema import GravityObservation

    def _run():
        _o, sensores, _x, _y, _z, _c = _escenario()
        obs = [GravityObservation(x_m=float(s[0]), y_m=0.0, z_m=float(s[2]), g=0.0)
               for s in sensores]
        p = _input("magnetico_aislado", observations=obs, magnetic_nt=_tmi(),
                   lambda_mag=1e-3)
        return _correr_servicio(p)

    return [("servicio/magnetico_aislado", _run)]


# ── casos de API ─────────────────────────────────────────────────────────────

_CSV_FIXTURE = (BACKEND_ROOT / "scripts" / "validation" / "mock_data" /
                "gravity_csv_v1" / "valid_recommended_bouguer_mgal.csv")


def _casos_api() -> list[tuple[str, callable]]:
    """Contrato HTTP de `/gravity-import/invert` — el paso 2 de la fase.

    Agrupar 41 `Form(...)` en objetos Pydantic sólo es legítimo si el formulario
    que viaja por el cable NO cambia. Esto lo mide: mismo multipart, misma
    respuesta JSON bit a bit.
    """
    @contextlib.contextmanager
    def _sin_red():
        """Neutraliza el enriquecimiento R3, que SALE A LA RED (DEM) tras invertir.

        Medido: dos corridas idénticas daban hashes distintos porque
        `get_terrain_data` falla o no según la red, y su mensaje de error viaja
        literal en `r3_enrichment.warnings` y en `warnings[]`. Un gate de
        byte-identidad que depende de internet es un gate que cría lobos y acaba
        desactivado. El enriquecimiento no es lo que la Fase 8 refactoriza, así
        que se fija a una salida constante y se declara aquí.
        """
        import api.gravity_import_api as api_mod
        original = api_mod._run_r3_post_inversion_enrichment
        api_mod._run_r3_post_inversion_enrichment = lambda *a, **k: {
            "attempted": False, "terrain_persisted": False,
            "enrichment_attempted": False, "enrichment_status": None,
            "has_elevation_data": False, "warnings": [],
        }
        # `enrichment_status=None` es un valor que la propia función devuelve
        # (rama `georef MISSING`): el stub tiene que ser válido contra
        # `GravityImportInvertResponse` o el endpoint responde 500 y el arnés
        # congela ese 500 — comprobado.
        try:
            yield
        finally:
            api_mod._run_r3_post_inversion_enrichment = original

    def _post(nombre: str, extra: dict):
        def _run():
            from fastapi.testclient import TestClient
            from main import app

            datos = {
                "project_id": "fase8_api", "run_id": nombre,
                "depth": 100, "nir": 83, "fe": 79, "region": "norte_chile",
                "lat": "-22.28", "lon": "-68.89",
                "nx": 6, "ny": 6, "nz": 6, "block_size": 25,
                "cutoff_radius": 400, "lambda_mag": 0.31623, "alpha_spatial": 1.0,
                "strict": "true", "allow_g_raw": "false",
                # Sin esto el endpoint devuelve 422 en el gate de spatial readiness
                # ANTES de mirar ningún otro parámetro: medido al congelar, los 7
                # casos daban el MISMO hash porque ninguno llegaba a invertir.
                "acknowledge_spatial_risk": "true",
            }
            datos.update(extra)
            with _sin_red(), TestClient(app) as cli, open(_CSV_FIXTURE, "rb") as fh:
                r = cli.post(
                    "/gravity-import/invert",
                    data=datos,
                    files={"file": (_CSV_FIXTURE.name, fh, "text/csv")},
                )
            return _sha_json({"status_code": r.status_code, "body": r.json()})
        return (f"api/{nombre}", _run)

    return [
        _post("invert_base", {}),
        _post("invert_auto_lambda", {"lambda_mag": 0.0,
                                     "gravimeter_type": "scintrex_cg6"}),
        _post("invert_compact", {"regularization_norm": "compact",
                                 "compact_max_irls": 4, "compact_eps": 0.05}),
        _post("invert_bounds", {"density_min": 0.0, "density_max": 4.0,
                                "padding_kappa": 1e4, "anchor_kappa": 1e3,
                                "auto_kappa": "false"}),
        _post("invert_sondajes", {"boreholes_json": json.dumps([{
            "x_m": 75.0, "z_m": 75.0, "y_from_m": 50.0, "y_to_m": 75.0,
            "density_t_m3": 3.4}])}),
        _post("invert_magnetico", {"data_type": "magnetic",
                                   "inclination_deg": -30.0,
                                   "declination_deg": 2.0,
                                   "field_intensity_nt": 23500.0}),
        _post("invert_csv_invalido", {"nx": 0, "ny": 0, "nz": 0}),
    ]


# ── ejecución ────────────────────────────────────────────────────────────────

def medir(solo: str | None = None) -> dict[str, str]:
    if _SCRATCH.exists():
        shutil.rmtree(_SCRATCH, ignore_errors=True)
    _SCRATCH.mkdir(parents=True, exist_ok=True)

    casos = _casos_servicio() + _casos_servicio_magnetico() + _casos_api()
    salida: dict[str, str] = {}
    for nombre, fn in casos:
        if solo and not nombre.startswith(solo):
            continue
        try:
            salida[nombre] = fn()
        except Exception as exc:      # el fallo también es una salida a congelar
            salida[nombre] = f"ERROR::{type(exc).__name__}::{exc}"
            print(f"  [!] {nombre}: {type(exc).__name__}: {exc}", file=sys.stderr)
            traceback.print_exc(limit=4, file=sys.stderr)
        print(f"  {salida[nombre][:16]}  {nombre}", flush=True)
    return salida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--freeze", action="store_true", help="congela la linea base")
    ap.add_argument("--check", action="store_true", help="compara contra la linea base")
    ap.add_argument("--only", default=None, help="prefijo de casos (p.ej. servicio/)")
    args = ap.parse_args()

    medido = medir(args.only)
    n_err = sum(1 for v in medido.values() if v.startswith("ERROR::"))
    print(f"\n{len(medido)} casos medidos ({n_err} con ERROR congelado).")

    if args.freeze:
        previo = {}
        if BASELINE.is_file() and args.only:
            previo = json.loads(BASELINE.read_text(encoding="utf-8"))
        previo.update(medido)
        BASELINE.write_text(json.dumps(previo, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        print(f"Linea base escrita en {BASELINE}")
        return 0

    if args.check:
        if not BASELINE.is_file():
            print(f"FALTA {BASELINE} (corre --freeze antes de tocar la espina)",
                  file=sys.stderr)
            return 1
        base = json.loads(BASELINE.read_text(encoding="utf-8"))
        if args.only:
            base = {k: v for k, v in base.items() if k.startswith(args.only)}
        faltan = sorted(set(base) - set(medido))
        nuevos = sorted(set(medido) - set(base))
        difs = sorted(k for k in set(base) & set(medido) if base[k] != medido[k])
        inestables = [k for k in difs if k in INESTABLES]
        difs = [k for k in difs if k not in INESTABLES]
        for k in inestables:
            print(f"  INESTABLE (no decide) {k}\n"
                  f"           base={base[k][:32]}\n           ahora={medido[k][:32]}")
        for k in faltan:
            print(f"  AUSENTE  {k}", file=sys.stderr)
        for k in nuevos:
            print(f"  NUEVO    {k}  {medido[k][:16]}")
        for k in difs:
            print(f"  DISTINTO {k}\n           base={base[k][:32]}\n"
                  f"           ahora={medido[k][:32]}", file=sys.stderr)
        if difs or faltan:
            print(f"\nBYTE-IDENTIDAD ROTA: {len(difs)} distinto(s), "
                  f"{len(faltan)} ausente(s).", file=sys.stderr)
            return 1
        print(f"\nBYTE-IDENTIDAD OK: {len(base) - len(inestables)} casos identicos "
              f"bit a bit" + (f" ({len(inestables)} inestable(s) medido(s) y no "
                              f"decisorio(s))." if inestables else "."))
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
