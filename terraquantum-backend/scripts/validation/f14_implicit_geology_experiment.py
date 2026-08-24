# -*- coding: utf-8 -*-
"""FASE 14 — ¿El contacto geológico implícito MEJORA la inversión, o no?

La Fase 14 de `docs/06_AUDITORIA_TECNICA_INTEGRAL.md` §10 pide cablear el
modelamiento implícito (RBF/HRBF) **como restricción geométrica de la inversión**,
y su criterio de aceptación es explícito:

    «Un contacto geológico mapeado por el usuario acota la inversión y se MIDE la
     mejora contra verdad conocida. Si no mejora, se documenta y no se promete.»

Este es el instrumento de esa medición. NO es una puerta de CI: es un diagnóstico
que responde una pregunta de física con un número, y que puede responder QUE NO
—igual que hizo la Fase 4 con el depth-weighting—.

EL MUNDO. Dique inclinado a 60°, techo a 100 m, espesor 75 m, Δρ = 0,5 t/m³: la
misma geometría que `tests/test_benchmark_dipping_dike.py`, elegida porque el
propio docstring de ese benchmark declara que **el buzamiento NO es recuperable
desde gravimetría de superficie** (no-unicidad de Skeels 1947, Li & Oldenburg
1998). Si una restricción geométrica sirve de algo, tiene que servir aquí.

ANTI-INVERSE-CRIME (P4 de `docs/07_VALIDATION_FRAMEWORK.md`). El dato se genera en
una malla REFINADA ×3 (84×54×12 = 54.432 celdas) y se invierte en la malla gruesa
(28×18×4 = 2.016). La discrepancia fina-vs-gruesa medida es **4,1 % del pico** —
el doble del ruido añadido (2 %), así que el crimen inverso está roto de verdad y
no de palabra.

EL SONDAJE ES DATO, NO ADORNO. Cada pozo se «loguea» leyendo la VERDAD a lo largo
de su vertical: es exactamente lo que un geólogo escribe al describir el testigo.
Ningún brazo ve el modelo verdadero de otra forma.

EL BRAZO DE CONTROL ES LA PIEZA QUE HACE HONESTA LA MEDICIÓN. Los brazos
`CONTROL_falsa_*` usan la MISMA maquinaria con una geología FALSA (el mismo dique
reflejado en x, que buza al revés y que los mismos pozos cortan a profundidades en
orden invertido). Producen 233 celdas objetivo frente a las 234 del prior bueno:
misma *cantidad* de prior, geometría opuesta. Una métrica que «mejora» también en
este brazo no está midiendo geología — está midiendo que hay un prior. Fue así como
se descartó el error de centroide (mejora 14/25 con geología falsa), y así como se
comprobó que el término de smallness sí transporta geología: con la falsa pierde
0/25 en todo.

LOS DOS BINDINGS, EN EL MISMO BARRIDO. `suavidad_*` mide el cableado histórico de
la Fase 7.2 (m_ref sólo en ‖L·(m − m_ref)‖²) y `smallness_*` el default de
producción desde la Fase 14 (además α‖m − m_ref‖²). Están los dos porque la
diferencia entre ellos ES el hallazgo de la fase: por la suavidad el prior EMPEORA
la recuperación (PR-AUC 0/25) y por el smallness la MEJORA (25/25). Y porque este
repositorio ya se equivocó cuatro veces midiendo una configuración y hablando de
otra: si el default cambia, este instrumento tiene que seguir midiendo el que corre
el usuario.

POR QUÉ VARIAS SEMILLAS Y NO UNA. Está medido en este repositorio que el motor es
BIMODAL frente al ruido (memoria `project_techo_medium_checkerboard`: 1 de cada 3
realizaciones da 169 m en vez de 19 m con diagnósticos idénticos). Una corrida no
es evidencia. Todo se reporta PAREADO: misma semilla = mismo ruido en los dos
brazos, y se cuenta en cuántas semillas gana cada brazo.

Correr desde terraquantum-backend:
    python scripts/validation/f14_implicit_geology_experiment.py --seeds 25
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

import numpy as np

# `line_buffering=True` NO es cosmético: sin él este envoltorio se queda con la
# salida en el búfer y un barrido de 25 semillas —media hora— no imprime una
# sola línea hasta el final. Un instrumento que no dice por dónde va invita a
# matarlo pensando que está colgado.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", line_buffering=True)

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

# NO se fuerza el solver: se mide el de PRODUCCIÓN, tal como lo corre el usuario.
# (Poner USE_BOUNDED_SOLVER=False no habría bastado: el despacho al GPCG con bounds
#  lo decide USE_PROJECTED_SOLVER — `exploration/gravimetry.py:2700`. Medido.)

from exploration.gravimetry import GravimetryForward, GravimetryInversion  # noqa: E402
from exploration.implicit_modeling import (  # noqa: E402
    ImplicitGeologicalModel,
    build_spatial_prior_from_implicit,
)

# ── El mundo (idéntico a tests/test_benchmark_dipping_dike.py) ────────────────
BLOCK = 30.0
NX, NY, NZ = 28, 18, 4
DIP = np.radians(60.0)
TOP_Y = 100.0
HALF_THICKNESS = 37.5
DIP_LENGTH = 400.0
X0_DIKE = 200.0
DELTA_RHO = 0.5
LAMBDA = 0.005
NOISE_PCT = 0.02

#: Geología FALSA de control: el mismo dique reflejado en x respecto de este eje.
X_ESPEJO = 600.0


def inside_dike(x, y):
    along = (x - X0_DIKE) * np.cos(DIP) + (y - TOP_Y) * np.sin(DIP)
    perp = np.abs(-(x - X0_DIKE) * np.sin(DIP) + (y - TOP_Y) * np.cos(DIP))
    return (along >= 0) & (along <= DIP_LENGTH) & (perp <= HALF_THICKNESS)


def centers(nx, ny, nz, bs):
    gx, gy, gz = np.mgrid[0:nx, 0:ny, 0:nz]
    return (gx.flatten(order="F") * bs + bs / 2,
            gy.flatten(order="F") * bs + bs / 2,
            gz.flatten(order="F") * bs + bs / 2)


def sensors():
    sx = np.linspace(BLOCK / 2, NX * BLOCK - BLOCK / 2, 20)
    sz = np.linspace(BLOCK / 2, NZ * BLOCK - BLOCK / 2, 4)
    a, b = np.meshgrid(sx, sz, indexing="ij")
    return np.column_stack([a.ravel(), np.zeros(a.size), b.ravel()])


class _Intervalo:
    """Lo mínimo que `ImplicitGeologicalModel.from_boreholes` consume."""

    def __init__(self, x, z, y_from, y_to, lith):
        self.x_m, self.z_m = float(x), float(z)
        self.y_from_m, self.y_to_m = float(y_from), float(y_to)
        self.lithology = lith


def loguear_pozo(x_collar, z_collar, y_max, geologia_falsa=False):
    """Describe el testigo de un pozo vertical leyendo la verdad (o la falsedad)."""
    ys = np.arange(0.5, y_max, 1.0)
    xs = np.full_like(ys, (X_ESPEJO - x_collar) if geologia_falsa else x_collar)
    dentro = inside_dike(xs, ys)
    tramos, actual, inicio = [], dentro[0], 0.0
    for i in range(1, len(ys)):
        if dentro[i] != actual:
            tramos.append(_Intervalo(x_collar, z_collar, inicio, ys[i],
                                     "ore" if actual else "host"))
            inicio, actual = ys[i], dentro[i]
    tramos.append(_Intervalo(x_collar, z_collar, inicio, y_max,
                             "ore" if actual else "host"))
    return tramos


def construir_m_ref(tramos, x_c, y_c, z_c, softness=0.0, amplitud=DELTA_RHO):
    """`amplitud` = contraste que el usuario DECLARA para la unidad objetivo. Se
    parametriza porque en la vida real no se acierta, y saber cuánto importa
    equivocarse es la mitad de la pregunta."""
    modelo = ImplicitGeologicalModel.from_boreholes(tramos, ["ore"])
    phi = modelo.field.evaluate(np.column_stack([x_c, y_c, z_c]))
    prior = build_spatial_prior_from_implicit(
        phi, target_mean=amplitud, host_mean=0.0,
        target_std=0.3, host_std=0.5, softness=softness,
    )
    return prior.mean.astype(float), int((phi >= 0).sum()), modelo


# ── Métricas contra verdad conocida ──────────────────────────────────────────
def pr_auc(score, verdad):
    orden = np.argsort(-score)
    t = verdad[orden].astype(float)
    positivos = t.sum()
    if positivos == 0:
        return float("nan")
    tp, fp = np.cumsum(t), np.cumsum(1 - t)
    recall = tp / positivos
    precision = tp / np.maximum(tp + fp, 1e-12)
    return float(np.sum(np.diff(np.concatenate([[0.0], recall])) * precision))


def medir(contraste_rec, verdad_bin, x_c, y_c):
    s = np.abs(contraste_rec)
    n = int(verdad_bin.sum())
    pred = s >= np.sort(s)[-n]          # umbral de VOLUMEN igualado (sin sintonizar)
    inter = int((pred & verdad_bin).sum())
    union = int((pred | verdad_bin).sum())
    w = s / max(s.sum(), 1e-12)
    return {
        "pr_auc": pr_auc(s, verdad_bin),
        "iou@vol": float(inter / union) if union else float("nan"),
        "dice@vol": float(2 * inter / (int(pred.sum()) + n)) if (pred.sum() + n) else float("nan"),
        "pearson_r": float(np.corrcoef(s, verdad_bin.astype(float))[0, 1]) if s.std() > 0 else float("nan"),
        # Se reporta, pero está MEDIDO que no discrimina: mejora también con la
        # geología FALSA (14/25 semillas). Es el «espejismo del centroide».
        "centroid_err_m": float(np.hypot(
            float(np.sum(w * x_c)) - float(verdad_bin @ x_c) / n,
            float(np.sum(w * y_c)) - float(verdad_bin @ y_c) / n,
        )),
    }


MAS_ES_MEJOR = {"pr_auc": True, "iou@vol": True, "dice@vol": True,
                "pearson_r": True, "centroid_err_m": False}
#: Las métricas que SOBREVIVEN al brazo de control (el centroide no).
METRICAS_QUE_DECIDEN = ("pr_auc", "iou@vol", "dice@vol", "pearson_r")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=25)
    ap.add_argument("--refine", type=int, default=3, help="anti-inverse-crime")
    ap.add_argument("--softness", type=float, default=0.0)
    ap.add_argument("--alpha", type=float, default=1.0,
                    help="peso del prior en el smallness (ImplicitGeologyParams.prior_weight)")
    ap.add_argument("--out", default=str(Path(__file__).with_name("f14_implicit_geology_report.json")))
    args = ap.parse_args()

    x_c, y_c, z_c = centers(NX, NY, NZ, BLOCK)
    verdad = np.where(inside_dike(x_c, y_c), DELTA_RHO, 0.0)
    verdad_bin = verdad > 0
    sens = sensors()
    fwd_grueso = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=2000.0)

    print("FASE 14 — ¿el contacto geológico implícito mejora la inversión?")
    print(f"  mundo: dique 60°, techo {TOP_Y:.0f} m, Δρ {DELTA_RHO} t/m³ — "
          f"{int(verdad_bin.sum())} de {verdad_bin.size} celdas son dique")

    # ── Dato en malla fina (anti-inverse-crime) ──────────────────────────────
    R = args.refine
    bf = BLOCK / R
    x_f, y_f, z_f = centers(NX * R, NY * R, NZ * R, bf)
    verdad_fina = np.where(inside_dike(x_f, y_f), DELTA_RHO, 0.0)
    t0 = time.perf_counter()
    g_limpio = GravimetryForward(bf, bf, bf, cutoff_radius=2000.0).build_sparse_kernel(
        x_f, y_f, z_f, sens) @ verdad_fina
    g_crimen = fwd_grueso.build_sparse_kernel(x_c, y_c, z_c, sens) @ verdad
    discrepancia = 100 * float(np.abs(g_limpio - g_crimen).max() / np.abs(g_limpio).max())
    print(f"  anti-inverse-crime: dato en {NX*R}×{NY*R}×{NZ*R} ({x_f.size} celdas, "
          f"{time.perf_counter()-t0:.0f}s); discrepancia fina-vs-gruesa "
          f"{discrepancia:.2f}% del pico vs {100*NOISE_PCT:.0f}% de ruido")

    y_max = NY * BLOCK
    tres = (loguear_pozo(200, 45, y_max) + loguear_pozo(290, 45, y_max)
            + loguear_pozo(380, 45, y_max))
    falsa = (loguear_pozo(200, 45, y_max, True) + loguear_pozo(290, 45, y_max, True)
             + loguear_pozo(380, 45, y_max, True))
    A = float(args.alpha)

    # Cada brazo = (sondajes, amplitud del prior, alpha del smallness).
    # alpha = 0 → el prior entra SÓLO por la suavidad (binding="smoothness", el
    # cableado histórico de la Fase 7.2). alpha > 0 → además por el smallness, que
    # es el DEFAULT DE PRODUCCIÓN desde la Fase 14. Que los dos estén aquí no es
    # exhaustividad: es la lección que este repositorio ya aprendió cuatro veces —
    # medir una configuración y hablar de otra—. Si el default cambia, este
    # instrumento tiene que seguir midiendo el que corre el usuario.
    brazos: dict = {
        "base": (None, DELTA_RHO, 0.0),
        "suavidad_1pozo": (loguear_pozo(290, 45, y_max), DELTA_RHO, 0.0),
        "suavidad_3pozos": (tres, DELTA_RHO, 0.0),
        "suavidad_3+esteriles": (tres + loguear_pozo(110, 45, y_max)
                                 + loguear_pozo(680, 45, y_max), DELTA_RHO, 0.0),
        "smallness_3pozos": (tres, DELTA_RHO, A),
        # ¿Y si el usuario NO acierta la densidad de la unidad? Es la objeción
        # obvia, y la respuesta medida es que da igual: lo que informa es la
        # geometría del contacto, no su amplitud.
        "smallness_densidad_x2": (tres, 2.0 * DELTA_RHO, A),
        "smallness_densidad_x05": (tres, 0.5 * DELTA_RHO, A),
        "CONTROL_falsa_suavidad": (falsa, DELTA_RHO, 0.0),
        "CONTROL_falsa_smallness": (falsa, DELTA_RHO, A),
    }

    m_refs, alphas, info = {}, {}, {}
    for nombre, (tramos, amplitud, alpha) in brazos.items():
        alphas[nombre] = alpha
        if tramos is None:
            m_refs[nombre] = None
            continue
        m_ref, n_obj, modelo = construir_m_ref(tramos, x_c, y_c, z_c, args.softness,
                                               amplitud=amplitud)
        m_refs[nombre] = m_ref
        rbf_viva = not modelo.field.degenerado_a_plano
        info[nombre] = {"n_pozos": len({(t.x_m, t.z_m) for t in tramos}),
                        "n_contactos": int(modelo.n_contact_points),
                        "celdas_objetivo": n_obj, "rbf_activa": rbf_viva,
                        "binding": "smallness" if alpha > 0 else "smoothness",
                        "alpha": alpha, "amplitud_t_m3": amplitud}
        print(f"  [prior] {nombre:24s} pozos={info[nombre]['n_pozos']} "
              f"contactos={info[nombre]['n_contactos']:2d} "
              f"objetivo={n_obj:4d}/{x_c.size} ({100*n_obj/x_c.size:4.1f}%) "
              f"binding={info[nombre]['binding']:10s} "
              f"RBF_activa={'sí' if rbf_viva else 'NO (campo plano)'}")

    inv = GravimetryInversion(NX, NY, NZ, BLOCK)
    rms = float(np.sqrt(np.mean(g_limpio ** 2)))
    res: dict = {k: [] for k in brazos}
    t0 = time.perf_counter()
    for s in range(args.seeds):
        rng = np.random.default_rng(1000 + s)
        g_ruido = g_limpio + rng.normal(0.0, NOISE_PCT * rms, size=len(g_limpio))
        for nombre in brazos:
            dens, _, _, _ = inv.solve_inversion_lsqr(
                g_ruido, None, y_c, lambda_mag=LAMBDA, alpha_spatial=1.0,
                forward_model=fwd_grueso, sensor_coords=sens, x_c=x_c, z_c=z_c,
                m_ref=m_refs[nombre], geo_prior_alpha=alphas[nombre],
            )
            m = medir(dens - inv.base_density, verdad_bin, x_c, y_c)
            m["seed"] = s
            res[nombre].append(m)
        print(f"    semilla {s+1}/{args.seeds} ({time.perf_counter()-t0:.0f}s)", flush=True)

    cols = list(MAS_ES_MEJOR)
    print("\n=== MEDIANA sobre %d semillas ===" % args.seeds)
    print(f"{'brazo':26s}" + "".join(f"{c:>16s}" for c in cols))
    for nombre in brazos:
        print(f"{nombre:26s}" + "".join(
            f"{np.median([r[c] for r in res[nombre]]):16.4f}" for c in cols))

    print("\n=== PAREADO CONTRA 'base' (misma semilla = mismo ruido) ===")
    veredicto: dict = {}
    for nombre in brazos:
        if nombre == "base":
            continue
        print(f"  -- {nombre}")
        veredicto[nombre] = {}
        for c in cols:
            vb = np.array([r[c] for r in res["base"]], float)
            vk = np.array([r[c] for r in res[nombre]], float)
            d = vk - vb
            gana = int(np.sum(d > 0)) if MAS_ES_MEJOR[c] else int(np.sum(d < 0))
            med = float(np.median(d))
            etiq = "igual" if med == 0 else ("MEJOR" if (med > 0) == MAS_ES_MEJOR[c] else "PEOR")
            veredicto[nombre][c] = {"delta_mediana": med, "gana": gana, "de": args.seeds}
            print(f"     {c:16s} Δmediana={med:+9.4f}  gana {gana:2d}/{args.seeds}  → {etiq}")

    # ── El veredicto, en una frase, y sólo con métricas que sobreviven al control ──
    print("\n=== VEREDICTO ===")
    ctrl = veredicto["CONTROL_geologia_falsa"]
    for c in cols:
        if c in METRICAS_QUE_DECIDEN:
            continue
        g = ctrl[c]["gana"]
        if g > args.seeds / 2:
            print(f"  · '{c}' MEJORA también con la geología FALSA ({g}/{args.seeds}): "
                  f"no mide geología. Descartada como evidencia.")
    mejor = max((n for n in veredicto if not n.startswith("CONTROL")),
                key=lambda n: sum(veredicto[n][c]["gana"] for c in METRICAS_QUE_DECIDEN))
    ganadas = {c: veredicto[mejor][c]["gana"] for c in METRICAS_QUE_DECIDEN}
    total = sum(ganadas.values())
    umbral = 0.5 * len(METRICAS_QUE_DECIDEN) * args.seeds
    print(f"  · mejor brazo con geología VERDADERA: '{mejor}' → {ganadas}")
    if total > umbral:
        print(f"  · MEJORA: gana {total} de {int(2*umbral)} comparaciones pareadas.")
    else:
        print(f"  · NO MEJORA: gana sólo {total} de {int(2*umbral)} comparaciones "
              f"pareadas sobre las métricas que sobreviven al control.")
        print("    Se documenta y NO se promete (criterio de aceptación de la Fase 14).")

    Path(args.out).write_text(json.dumps({
        "config": vars(args),
        "mundo": {"discrepancia_anti_inverse_crime_pct": round(discrepancia, 2),
                  "celdas_dique": int(verdad_bin.sum()), "celdas_total": int(verdad_bin.size)},
        "priors": info, "veredicto": veredicto, "resultados": res,
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nescrito {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
