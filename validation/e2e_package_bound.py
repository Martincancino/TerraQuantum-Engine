"""
E2E por HTTP — cierra el último eslabón del hallazgo del bound por defecto.

Hasta ahora la cadena estaba verificada LEYENDO código (UI -> #CONFIG -> API -> esquema) y la
consecuencia estaba MEDIDA llamando a `run_geophysics_inversion`. Faltaba lo obvio: subir un
paquete por el endpoint real y ver qué sale.

Esto hace exactamente eso:

  1. Construye un paquete `.tqpkg` con el formato documentado en `csv_package_service`.
  2. Lo sube dos veces a `POST /v2/gravity-import/load-package?sync=true`:
       (a) SIN tocar `density_min`  -> el default del paquete es 0.0 ABSOLUTO
       (b) con `density_min = 2.6`  -> igual a `base_density`, contraste >= 0
  3. Lee el block model persistido y mide PR-AUC y centroide contra la verdad conocida.

El mundo usa fondo de **2.6 t/m³ a propósito**: es el `base_density` que el paquete NO puede
cambiar (no existe la clave en `_CONFIG_DEFAULTS`), así que igualarlo elimina cualquier
ambigüedad sobre de dónde sale el contraste permitido.

    # 1) arrancar el backend
    cd terraquantum-backend && python -m uvicorn main:app --host 127.0.0.1 --port 8011
    # 2) correr esto
    python -m validation.e2e_package_bound --port 8011
"""
from __future__ import annotations

import argparse
import csv
import io
import json
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
from .truth import truth_products
from . import runner as R

REPO = Path(__file__).resolve().parents[1]

# Malla idéntica a la del barrido, y fondo 2.6 = el base_density fijo del backend.
NX, NY, NZ = 18, 14, 18
BLOCK_M = 125.0
BASE_DENSITY = 2.6           # <- el que el paquete NO puede cambiar
CONTRAST = 0.6
CENTER = NX * BLOCK_M / 2.0
DEPTH_M = 400.0
SEED = 810845                # semilla que con contraste >= 0 dio 1.1 m en el experimento previo

WORLD = World(
    schema_version="world/1", id="w_e2e_base26", instance_version=1,
    geometry=Geometry(
        bounds_m=(0.0, 0.0, 0.0, NX * BLOCK_M, NY * BLOCK_M, NZ * BLOCK_M),
        topography=Topography(kind="flat", elevation_m=0.0),
        bodies=(Body(id="b1",
                     shape=Sphere(cx_m=CENTER, cy_m=DEPTH_M, cz_m=CENTER, radius_m=150.0),
                     domain="ore"),),
    ),
    properties=Properties(
        background=DomainProps(density_t_m3=BASE_DENSITY),
        domains={"ore": DomainProps(density_t_m3=BASE_DENSITY + CONTRAST)},
    ),
    metadata=WorldMetadata(
        name="E2E bound", axis="e2e", regime="moderado",
        notes=("Fondo 2.6 a proposito: es el base_density que el paquete no puede "
               "cambiar. Asi el contraste permitido = density_min - 2.6, sin ambiguedad."),
    ),
    provenance=Provenance(seed=SEED, generator_version="e2e_package_bound/1"),
).freeze()

CAMPAIGN = Campaign(
    schema_version="campaign/1", id="c_e2e_base26", world_id=WORLD.id,
    world_instance_version=1,
    survey=SurveyDesign(span_m=1500.0, n_side=12, height_m=0.0),
    noise=NoiseModel(instrument_mgal=0.02, position_m=0.0),
    generation_method=GenerationMethod.THIRD_PARTY,
    generation_detail="choclo.point.gravity_u (masa puntual = exacta para esfera)",
    provenance=Provenance(seed=SEED, generator_version="e2e_package_bound/1"),
)

SIGMA_MGAL = 0.02


def _package_text(density_min: float | None, cutoff_radius: float = 0.0,
                  depth: float | None = None, auto_grid: bool = False) -> str:
    """Paquete en el formato de `csv_package_service`. density_min=None => NO se toca
    la clave, para que rija el default del propio servicio.

    `cutoff_radius` es el segundo eje: el default del paquete es 0.0, pero el runner del
    framework venía pasando 2250 m (span x 1.5) — una elección MÍA, no de producción.
    """
    xs, ys, zs, g_si = generate_gravity(WORLD, CAMPAIGN)

    # auto_grid=True => nx/ny/nz/block/depth en 0, que es como los manda el flujo real:
    # el backend deriva la grilla del propio CSV. Es la condición que faltaba medir.
    grid = ({"nx": 0, "ny": 0, "nz": 0, "block_size": 0, "depth": 0} if auto_grid else
            {"nx": NX, "ny": NY, "nz": NZ, "block_size": BLOCK_M,
             "depth": (NY * BLOCK_M if depth is None else depth)})
    cfg = {
        "data_type": "gravity", "region": "norte_chile",
        **grid,
        "cutoff_radius": cutoff_radius,
        "density_max": 5.5, "gravimeter_type": "unknown",
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
                    f"{g_si[i]*1e5:.8f}", "mGal", "bouguer_anomaly", f"{SIGMA_MGAL}"])

    head = ["#TQPKG/1",
            "#CONFIG " + json.dumps(cfg, separators=(",", ":")),
            "#BOREHOLES []",
            "#PLAN {}"]
    return "\n".join(head) + "\n" + buf.getvalue()


def _frame_shift(project_id: str, run_id: str):
    """Desplazamiento que el IMPORT aplica a las coordenadas de estación.

    MEDIDO 2026-08-06: el import RE-ORIGINA las estaciones al mínimo. Se enviaron en
    x,z ∈ [375, 1875] y quedaron persistidas en [0, 1500]: un corrimiento de −375 m.
    La malla, en cambio, se construye 0..2250. Consecuencia: **el survey no queda
    centrado en la malla**, y una verdad expresada en el marco de entrada apunta al
    sitio equivocado.

    Este bug se comió la primera pasada del E2E (medía PR-AUC 0.003 donde había 1.000).
    Por eso el desplazamiento se DERIVA de los datos persistidos en vez de asumirse.
    """
    p = (REPO / "terraquantum-backend" / "data" / "projects" / project_id /
         "runs" / run_id / "observations.json")
    if not p.exists():
        return 0.0, 0.0, 0.0
    d = json.loads(p.read_text(encoding="utf-8"))
    obs = d if isinstance(d, list) else (d.get("observations") or [])
    if not obs:
        return 0.0, 0.0, 0.0
    px = np.array([o["x_m"] for o in obs], dtype=float)
    py = np.array([o["y_m"] for o in obs], dtype=float)
    pz = np.array([o["z_m"] for o in obs], dtype=float)
    sx, sy, sz, _ = generate_gravity(WORLD, CAMPAIGN)
    return float(px.min() - sx.min()), float(py.min() - sy.min()), float(pz.min() - sz.min())


def _measure(project_id: str, run_id: str):
    """Lee el block model persistido y mide contra la verdad, en el marco de TQ."""
    import polars as pl
    hits = list((REPO / "terraquantum-backend" / "data" / "projects").glob(
        f"{project_id}/runs/{run_id}/block_model.parquet"))
    if not hits:
        return None
    df = pl.read_parquet(hits[0])
    if "density_contrast_t_m3" in df.columns:
        c = df["density_contrast_t_m3"].to_numpy().astype(np.float64)
    else:
        c = df["density"].to_numpy().astype(np.float64) - BASE_DENSITY
    x = df["x"].to_numpy().astype(np.float64)
    y = df["y"].to_numpy().astype(np.float64)
    z = df["z"].to_numpy().astype(np.float64)

    # La verdad es paramétrica (P1): se evalúa en las celdas que devolvió TQ. Y se
    # traslada al MARCO DE TQ, porque el import re-origina las estaciones (ver
    # `_frame_shift`): el cuerpo se mueve con ellas.
    dx, dy, dz = _frame_shift(project_id, run_id)
    b = WORLD.geometry.bodies[0].shape
    cx, cy, cz = b.cx_m + dx, b.cy_m + dy, b.cz_m + dz
    mask = ((x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2) <= b.radius_m ** 2
    true_c = (cx, cy, cz)

    rec_c = M.recovered_centroid(c, x, y, z)
    return dict(
        n_cells=int(c.size), n_body=int(mask.sum()),
        pr_auc=float(M.pr_auc(c, mask)),
        horizontal_m=float(M.horizontal_error(true_c, rec_c)),
        depth_m=float(M.depth_error(true_c, rec_c)),
        recovered_centroid=[round(v, 1) for v in rec_c],
        frac_negativo=float(np.mean(c < -1e-9)),
        min_contrast=float(c.min()), max_contrast=float(c.max()),
    )


def _multi_semilla(base: str, n_seeds: int, httpx) -> int:
    """Grilla AUTOMATICA (flujo real) x 2 bounds x 2 cutoffs x N semillas.

    Con una sola semilla, la diferencia entre 0.808 y 0.842 no significa nada. Esto
    reporta MEDIANA y rango, que es la unidad de reporte del framework (P7).
    """
    import statistics as st

    global CAMPAIGN
    semillas = [910_001 + 173 * i for i in range(n_seeds)]
    combos = [("default", None), ("estricto", 2.6)]
    cutoffs = [0.0, 2250.0]
    acc = {(cb, cut): {"pr": [], "hor": [], "prof": [], "neg": []}
           for cb, _ in combos for cut in cutoffs}

    print(f"MODO MULTI-SEMILLA — grilla AUTOMATICA (flujo real del usuario)")
    print(f"{len(combos)} bounds x {len(cutoffs)} cutoffs x {n_seeds} semillas = "
          f"{len(combos)*len(cutoffs)*n_seeds} inversiones por HTTP\n")

    base_camp = CAMPAIGN
    for s in semillas:
        CAMPAIGN = Campaign(
            schema_version="campaign/1", id=f"c_e2e_ms_s{s}", world_id=WORLD.id,
            world_instance_version=1, survey=base_camp.survey, noise=base_camp.noise,
            generation_method=base_camp.generation_method,
            generation_detail=base_camp.generation_detail,
            provenance=Provenance(seed=s, generator_version="e2e_package_bound/1"),
        )
        for cb, dmin in combos:
            for cut in cutoffs:
                tag = f"ms_{cb}_c{int(cut)}_s{s}"
                pid, rid = f"e2e_{tag}", f"run_{tag}"
                r = httpx.post(
                    f"{base}/v2/gravity-import/load-package",
                    files={"file": (f"{tag}.tqpkg",
                                    _package_text(dmin, cut, None, True).encode("utf-8"),
                                    "text/csv")},
                    data={"project_id": pid, "run_id": rid, "sync": "true"}, timeout=900.0)
                if r.status_code >= 400:
                    print(f"  {tag}: HTTP {r.status_code}")
                    continue
                m = _measure(pid, rid)
                if not m:
                    continue
                a = acc[(cb, cut)]
                a["pr"].append(m["pr_auc"])
                a["hor"].append(m["horizontal_m"])
                a["prof"].append(m["depth_m"])
                a["neg"].append(m["frac_negativo"])
        print(f"  semilla {s} lista")

    CAMPAIGN = base_camp
    print("\n" + "=" * 92)
    print(f"{'bound':10s} {'cutoff':>8s} {'n':>3s} {'PR-AUC med':>11s} {'horiz med':>11s} "
          f"{'PROF med':>10s} {'prof rango':>18s} {'c<0':>7s}")
    print("-" * 92)
    for cut in cutoffs:
        for cb, _ in combos:
            a = acc[(cb, cut)]
            if not a["pr"]:
                continue
            print(f"{cb:10s} {('def(500)' if cut == 0 else '2250'):>8s} {len(a['pr']):3d} "
                  f"{st.median(a['pr']):11.3f} {st.median(a['hor']):10.1f}m "
                  f"{st.median(a['prof']):9.1f}m "
                  f"{min(a['prof']):7.1f}-{max(a['prof']):<8.1f} "
                  f"{100*st.median(a['neg']):6.1f}%")
    dest = REPO / "validation" / "e2e_autogrid_seeds.json"
    dest.write_text(json.dumps({f"{cb}_c{int(cut)}": acc[(cb, cut)]
                                for cb, _ in combos for cut in cutoffs},
                               indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nGuardado: {dest}")
    return 0


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--seeds", type=int, default=1,
                    help=">1 activa el modo MULTI-SEMILLA sobre la grilla AUTOMATICA "
                         "(el flujo real): 2 bounds x 2 cutoffs x N semillas, con mediana. "
                         "Una sola corrida por celda ya me hizo concluir de mas dos veces.")
    args = ap.parse_args()
    base = f"http://{args.host}:{args.port}"

    import httpx

    print("=" * 92)
    print("E2E POR HTTP — el bound por defecto, subiendo un paquete al endpoint real")
    print("=" * 92)
    print(f"Backend        : {base}")
    print(f"Mundo          : esfera r=150 m a {DEPTH_M:.0f} m, fondo {BASE_DENSITY} "
          f"(= base_density fijo del backend), contraste +{CONTRAST}")
    print(f"Malla          : {NX}x{NY}x{NZ} @ {BLOCK_M:.0f} m     semilla {SEED}")
    print()

    try:
        h = httpx.get(f"{base}/health", timeout=10.0)
        print(f"/health -> {h.status_code}")
    except Exception as exc:
        print(f"!! el backend no responde en {base}: {exc}")
        print("   Arrancalo con:  cd terraquantum-backend && "
              "python -m uvicorn main:app --host 127.0.0.1 --port 8011")
        return 2

    # 2x2: el bound (default vs acoplado a base) x el cutoff_radius (default del
    # paquete vs el que el harness venía usando). El segundo eje entra porque la
    # primera pasada E2E destapó que el runner del framework NO usaba el default.
    # (tag, density_min, cutoff_radius, depth). Los dos ultimos casos replican la
    # configuracion que el runner del framework venia usando (cutoff 2250, depth 1)
    # para saber si la diferencia brutal entre las dos rutas viene de ahi.
    if args.seeds > 1:
        return _multi_semilla(base, args.seeds, httpx)

    # (tag, density_min, cutoff_radius, depth, auto_grid)
    casos = [
        # ── grilla FORZADA (18x14x18 @125): aisla el bound y el cutoff ──────────
        ("default_cut0", None, 0.0, None, False),
        ("estricto_cut0", 2.6, 0.0, None, False),
        ("default_cut2250", None, 2250.0, None, False),
        ("estricto_cut2250", 2.6, 2250.0, None, False),
        # ── grilla AUTOMÁTICA: el flujo real del usuario ────────────────────────
        ("auto_default_cut0", None, 0.0, None, True),
        ("auto_estricto_cut0", 2.6, 0.0, None, True),
        ("auto_default_cut2250", None, 2250.0, None, True),
        ("auto_estricto_cut2250", 2.6, 2250.0, None, True),
    ]
    out = {}
    for tag, dmin, cut, dep, auto in casos:
        pid, rid = f"e2e_bound_{tag}", f"run_{tag}"
        txt = _package_text(dmin, cut, dep, auto)
        declared = "(no se envia la clave)" if dmin is None else f"{dmin}"
        print(f"\n--- caso {tag}:  density_min = {declared}   cutoff = {cut:.0f}   "
              f"grilla = {'AUTO (del CSV)' if auto else 'forzada 18x14x18@125'}")
        t0 = time.perf_counter()
        r = httpx.post(
            f"{base}/v2/gravity-import/load-package",
            files={"file": (f"{tag}.tqpkg", txt.encode("utf-8"), "text/csv")},
            data={"project_id": pid, "run_id": rid, "sync": "true"},
            timeout=900.0,
        )
        print(f"    HTTP {r.status_code}   {time.perf_counter()-t0:.0f}s")
        if r.status_code >= 400:
            print(f"    cuerpo: {r.text[:500]}")
            out[tag] = {"http_error": r.status_code, "body": r.text[:500]}
            continue
        m = _measure(pid, rid)
        if m is None:
            print("    !! no se encontro el block model persistido")
            out[tag] = {"error": "sin parquet"}
            continue
        out[tag] = m
        sh = _frame_shift(pid, rid)
        print(f"    marco: el import desplazo las estaciones ({sh[0]:+.0f}, {sh[1]:+.0f}, "
              f"{sh[2]:+.0f}) m -> la verdad se traslada igual")
        print(f"    PR-AUC {m['pr_auc']:.3f}   horizontal {m['horizontal_m']:.1f} m   "
              f"profundidad {m['depth_m']:.1f} m")
        print(f"    contraste recuperado: min {m['min_contrast']:+.3f}  "
              f"max {m['max_contrast']:+.3f}   celdas negativas {100*m['frac_negativo']:.1f}%")

    print("\n" + "=" * 92)
    print(f"{'caso':20s} {'PR-AUC':>8s} {'horizontal':>12s} {'profundidad':>12s} "
          f"{'celdas < 0':>11s}")
    print("-" * 92)
    for tag, *_ in casos:
        m = out.get(tag, {})
        if "pr_auc" not in m:
            print(f"{tag:20s}   (sin resultado)")
            continue
        print(f"{tag:20s} {m['pr_auc']:8.3f} {m['horizontal_m']:11.1f}m "
              f"{m['depth_m']:11.1f}m {100*m['frac_negativo']:10.1f}%")

    def _pr(t):
        return out.get(t, {}).get("pr_auc")

    for pref, etiqueta in (("", "GRILLA FORZADA"), ("auto_", "GRILLA AUTOMATICA (flujo real)")):
        e0, s0 = _pr(f"{pref}default_cut0"), _pr(f"{pref}estricto_cut0")
        e1, s1 = _pr(f"{pref}default_cut2250"), _pr(f"{pref}estricto_cut2250")
        if None in (e0, s0, e1, s1):
            continue
        print(f"\n{etiqueta}")
        print(f"  efecto del BOUND  | cutoff default(500): {e0:.3f} -> {s0:.3f}   "
              f"| cutoff 2250: {e1:.3f} -> {s1:.3f}")
        print(f"  efecto del CUTOFF | estricto: {s0:.3f} -> {s1:.3f}   "
              f"| default: {e0:.3f} -> {e1:.3f}")

    ncel = {t: out.get(t, {}).get("n_cells") for t in ("estricto_cut2250", "auto_estricto_cut2250")}
    if all(ncel.values()):
        print(f"\nCeldas de malla: forzada {ncel['estricto_cut2250']}  "
              f"vs automatica {ncel['auto_estricto_cut2250']}")

    dest = REPO / "validation" / "e2e_package_bound_result.json"
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nGuardado: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
