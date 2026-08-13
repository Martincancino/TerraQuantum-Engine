"""
¿El costo de profundidad del contraste negativo aguanta fuera de un solo régimen?

El E2E multi-semilla midió, con grilla AUTOMÁTICA (flujo real) y cutoff 2250, que permitir
contraste negativo cuesta **profundidad** (247,6 m vs 18,8 m, rangos sin solape) y **no cuesta
horizontal** (13,1 m en ambos). Pero era UN cuerpo: esfera r=150 m a 400 m.

Este barrido mueve los dos ejes que faltaban —profundidad y tamaño— por el endpoint real:

    eje PROFUNDIDAD : r=150 m,  y ∈ {250, 400, 600, 900} m
    eje TAMAÑO      : y=400 m,  r ∈ {100, 250} m

Todo con grilla automática, cutoff 2250, y N semillas por celda. La unidad de reporte es
mediana + rango (P7): con una semilla ya me equivoqué tres veces en esta sesión.

    # backend arriba en otra consola:
    #   cd terraquantum-backend && python -m uvicorn main:app --host 127.0.0.1 --port 8011
    python -m validation.e2e_bound_regimes --seeds 4
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import statistics as st
import sys
import time
from pathlib import Path

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "validation"

from .contract import (Body, Campaign, DomainProps, GenerationMethod, Geometry,
                       NoiseModel, Properties, Provenance, Sphere, SurveyDesign,
                       Topography, World, WorldMetadata)
from .generate import generate_gravity
from . import metrics as M

REPO = Path(__file__).resolve().parents[1]
PROJECTS = REPO / "terraquantum-backend" / "data" / "projects"

BASE_DENSITY = 2.6        # el base_density fijo del backend (el paquete no puede cambiarlo)
CONTRAST = 0.6
SPAN_M = 1500.0
N_SIDE = 12
NOISE_MGAL = 0.02
CUTOFF = 2250.0
CENTER = 1125.0           # centro del survey en el marco de entrada (375..1875)


def _world(depth_m: float, radius_m: float) -> World:
    wid = f"w_reg_d{int(depth_m)}_r{int(radius_m)}"
    return World(
        schema_version="world/1", id=wid, instance_version=1,
        geometry=Geometry(
            bounds_m=(0.0, 0.0, 0.0, 2250.0, 1750.0, 2250.0),
            topography=Topography(kind="flat", elevation_m=0.0),
            bodies=(Body(id="b1",
                         shape=Sphere(cx_m=CENTER, cy_m=depth_m, cz_m=CENTER,
                                      radius_m=radius_m),
                         domain="ore"),),
        ),
        properties=Properties(
            background=DomainProps(density_t_m3=BASE_DENSITY),
            domains={"ore": DomainProps(density_t_m3=BASE_DENSITY + CONTRAST)},
        ),
        metadata=WorldMetadata(name=wid, axis="bound_regimes",
                               regime=("somero" if depth_m <= 250 else
                                       "moderado" if depth_m <= 400 else "profundo"),
                               notes="Barrido de bound por profundidad y tamano, grilla auto."),
        provenance=Provenance(seed=0, generator_version="e2e_bound_regimes/1"),
    ).freeze()


def _campaign(world: World, seed: int) -> Campaign:
    return Campaign(
        schema_version="campaign/1", id=f"c_reg_{world.id}_s{seed}", world_id=world.id,
        world_instance_version=1,
        survey=SurveyDesign(span_m=SPAN_M, n_side=N_SIDE, height_m=0.0),
        noise=NoiseModel(instrument_mgal=NOISE_MGAL, position_m=0.0),
        generation_method=GenerationMethod.THIRD_PARTY,
        generation_detail="choclo.point.gravity_u (masa puntual = exacta para esfera)",
        provenance=Provenance(seed=seed, generator_version="e2e_bound_regimes/1"),
    )


def _package(world: World, campaign: Campaign, density_min: float | None) -> str:
    """Grilla AUTOMATICA (nx/ny/nz/block/depth = 0): el flujo real del usuario."""
    xs, ys, zs, g_si = generate_gravity(world, campaign)
    cfg = {
        "data_type": "gravity", "region": "norte_chile",
        "nx": 0, "ny": 0, "nz": 0, "block_size": 0, "depth": 0,
        "cutoff_radius": CUTOFF, "density_max": 5.5, "gravimeter_type": "unknown",
        "regularization_norm": "L2", "strict": True,
        "acknowledge_spatial_risk": True, "acknowledge_regional_scale": True,
    }
    if density_min is not None:
        cfg["density_min"] = density_min
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["station_id", "x_m", "y_m", "z_m", "g_mgal", "unit",
                "gravity_type", "sigma_mgal"])
    for i in range(xs.size):
        w.writerow([f"ST{i+1:04d}", f"{xs[i]:.4f}", f"{ys[i]:.4f}", f"{zs[i]:.4f}",
                    f"{g_si[i]*1e5:.8f}", "mGal", "bouguer_anomaly", f"{NOISE_MGAL}"])
    head = ["#TQPKG/1", "#CONFIG " + json.dumps(cfg, separators=(",", ":")),
            "#BOREHOLES []", "#PLAN {}"]
    return "\n".join(head) + "\n" + buf.getvalue()


def _measure(world: World, campaign: Campaign, pid: str, rid: str):
    """Mide contra la verdad, trasladada al marco en que TQ invirtio."""
    import polars as pl
    d = PROJECTS / pid / "runs" / rid
    pq = d / "block_model.parquet"
    if not pq.exists():
        return {"error": "sin parquet"}

    # El import RE-ORIGINA las estaciones: el desplazamiento se DERIVA, no se asume.
    dx = dy = dz = 0.0
    obs_p = d / "observations.json"
    if obs_p.exists():
        o = json.loads(obs_p.read_text(encoding="utf-8"))
        obs = o if isinstance(o, list) else (o.get("observations") or [])
        if obs:
            sx, sy, sz, _ = generate_gravity(world, campaign)
            dx = float(min(q["x_m"] for q in obs) - sx.min())
            dy = float(min(q["y_m"] for q in obs) - sy.min())
            dz = float(min(q["z_m"] for q in obs) - sz.min())

    df = pl.read_parquet(pq)
    x, y, z = (df[c].to_numpy().astype(float) for c in ("x", "y", "z"))
    c = (df["density_contrast_t_m3"].to_numpy().astype(float)
         if "density_contrast_t_m3" in df.columns
         else df["density"].to_numpy().astype(float) - BASE_DENSITY)

    b = world.geometry.bodies[0].shape
    cx, cy, cz = b.cx_m + dx, b.cy_m + dy, b.cz_m + dz
    mask = ((x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2) <= b.radius_m ** 2
    n_body = int(mask.sum())
    if n_body == 0:
        # Nunca fallar en silencio: sin celdas de cuerpo las metricas serian ruido.
        return {"error": f"cuerpo FUERA de la malla (y del modelo: {y.min():.0f}-{y.max():.0f} m, "
                         f"cuerpo a {cy:.0f} m)"}
    rc = M.recovered_centroid(c, x, y, z)
    return dict(n_cells=int(c.size), n_body=n_body,
                pr_auc=float(M.pr_auc(c, mask)),
                horizontal_m=float(M.horizontal_error((cx, cy, cz), rc)),
                depth_m=float(M.depth_error((cx, cy, cz), rc)),
                frac_neg=float(np.mean(c < -1e-9)))


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--seeds", type=int, default=4)
    args = ap.parse_args()
    base = f"http://{args.host}:{args.port}"

    import httpx

    seeds = [920_001 + 149 * i for i in range(max(2, args.seeds))]
    regimenes = ([(f"prof_{d}", d, 150.0) for d in (250, 400, 600, 900)] +
                 [(f"radio_{int(r)}", 400.0, r) for r in (100.0, 250.0)])
    brazos = [("default", None), ("estricto", BASE_DENSITY)]

    print("=" * 96)
    print("BARRIDO DE REGIMENES POR HTTP — ¿aguanta el costo de profundidad del bound?")
    print("=" * 96)
    print(f"Grilla AUTOMATICA (flujo real) · cutoff {CUTOFF:.0f} · contraste +{CONTRAST}")
    print(f"{len(regimenes)} regimenes x {len(brazos)} brazos x {len(seeds)} semillas = "
          f"{len(regimenes)*len(brazos)*len(seeds)} inversiones\n")

    try:
        httpx.get(f"{base}/health", timeout=10.0)
    except Exception as exc:
        print(f"!! el backend no responde en {base}: {exc}")
        return 2

    filas, errores, t0 = [], [], time.perf_counter()
    for nombre, depth_m, radius_m in regimenes:
        world = _world(depth_m, radius_m)
        for brazo, dmin in brazos:
            acc = {"pr": [], "hor": [], "prof": [], "neg": []}
            for s in seeds:
                camp = _campaign(world, s)
                tag = f"{nombre}_{brazo}_s{s}"
                pid, rid = f"e2e_reg_{tag}", f"run_{tag}"
                r = httpx.post(
                    f"{base}/v2/gravity-import/load-package",
                    files={"file": (f"{tag}.tqpkg",
                                    _package(world, camp, dmin).encode("utf-8"), "text/csv")},
                    data={"project_id": pid, "run_id": rid, "sync": "true"}, timeout=900.0)
                if r.status_code >= 400:
                    errores.append((tag, f"HTTP {r.status_code}"))
                    continue
                m = _measure(world, camp, pid, rid)
                if "error" in m:
                    errores.append((tag, m["error"]))
                    continue
                acc["pr"].append(m["pr_auc"])
                acc["hor"].append(m["horizontal_m"])
                acc["prof"].append(m["depth_m"])
                acc["neg"].append(m["frac_neg"])
            if not acc["pr"]:
                print(f"  {nombre:10s} {brazo:9s}  SIN RESULTADOS")
                continue
            fila = dict(regimen=nombre, depth_m=depth_m, radius_m=radius_m, brazo=brazo,
                        n=len(acc["pr"]),
                        pr=st.median(acc["pr"]), hor=st.median(acc["hor"]),
                        prof=st.median(acc["prof"]),
                        prof_min=min(acc["prof"]), prof_max=max(acc["prof"]),
                        neg=st.median(acc["neg"]))
            filas.append(fila)
            print(f"  {nombre:10s} {brazo:9s} n={fila['n']}  PR-AUC {fila['pr']:.3f}  "
                  f"horiz {fila['hor']:6.1f}m  prof {fila['prof']:7.1f}m "
                  f"[{fila['prof_min']:.0f}-{fila['prof_max']:.0f}]  neg {100*fila['neg']:.1f}%")

    print("\n" + "=" * 96)
    print(f"{'regimen':11s} {'y':>5s} {'r':>5s} | {'PR-AUC def/est':>16s} | "
          f"{'horiz def/est':>16s} | {'PROFUNDIDAD def/est':>24s} | {'factor':>7s}")
    print("-" * 96)
    for nombre, depth_m, radius_m in regimenes:
        d = {f["brazo"]: f for f in filas if f["regimen"] == nombre}
        if "default" not in d or "estricto" not in d:
            continue
        a, b = d["default"], d["estricto"]
        fac = a["prof"] / b["prof"] if b["prof"] > 1e-9 else float("inf")
        print(f"{nombre:11s} {depth_m:5.0f} {radius_m:5.0f} | "
              f"{a['pr']:7.3f} / {b['pr']:6.3f} | "
              f"{a['hor']:7.1f} / {b['hor']:6.1f} | "
              f"{a['prof']:7.1f} [{a['prof_min']:.0f}-{a['prof_max']:.0f}] / "
              f"{b['prof']:6.1f} [{b['prof_min']:.0f}-{b['prof_max']:.0f}] | {fac:6.1f}x")

    print()
    if errores:
        print(f"!! {len(errores)} corridas sin resultado — el resumen esta INCOMPLETO:")
        for t, e in errores[:10]:
            print(f"   {t}: {e}")
    else:
        print(f"Sin errores: {len(filas)} celdas completas.")
    print(f"Tiempo: {(time.perf_counter()-t0)/60:.1f} min")

    dest = REPO / "validation" / "e2e_bound_regimes_result.json"
    dest.write_text(json.dumps({"cutoff": CUTOFF, "seeds": seeds, "filas": filas,
                                "errores": errores}, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    print(f"Guardado: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
