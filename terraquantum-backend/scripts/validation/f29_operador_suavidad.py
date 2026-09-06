# -*- coding: utf-8 -*-
"""FASE 29 — los dos hallazgos numericos del expediente academico que nadie midio.

ACAD-3 (docs/academic/01_matematica.md §2.7a y §9 Pregunta 1)
    El termino de suavidad penaliza ||L m||^2 con L un Laplaciano de grafo, de modo
    que en las ecuaciones normales aparece L^2: un operador BI-ARMONICO, de cuarto
    orden. La referencia que el codigo cita (Li & Oldenburg 1998,
    exploration/gravimetry.py:1319) usa PRIMERAS diferencias y penaliza ||grad m||^2.
    El expediente lo declara literalmente: "No se ha medido nunca la diferencia de
    resultado entre penalizar ||Lm||^2 y ||grad m||^2 sobre el mismo dato. No existe
    ese experimento." Este es ese experimento.

ACAD-4 (docs/academic/01_matematica.md §2.7c y §9 Pregunta 2)
    L se construye sobre la malla COMPLETA y luego se RECORTA por indexado
    (exploration/gravimetry.py:2246-2247). El recorte borra las entradas fuera de la
    diagonal que apuntaban a celdas inactivas pero CONSERVA la diagonal, asi que las
    filas frontera dejan de sumar cero: es una condicion de Dirichlet homogenea
    implicita — contraste CERO en el aire y en el borde podado. Nadie la eligio;
    emerge del slicing. La alternativa es recalcular la diagonal despues del recorte,
    que es la condicion de Neumann natural. Tampoco se midio nunca.

DISENO — un factorial 2x2, no dos experimentos sueltos, porque las dos preguntas
son ORTOGONALES y su interaccion tambien es una respuesta:

                        frontera Dirichlet        frontera Neumann
    orden 4 (L)      ->  PRODUCCION HOY            L con diagonal recalculada
    orden 1 (B)      ->  B + filas de borde        B sobre el subgrafo activo

    Las cuatro se construyen de la MISMA L_active que arma el motor, asi que
    comparten kernel, pesos, sigma, bounds y solver. Lo unico que cambia es el
    operador de regularizacion. Algebra:
        offdiag O  = L_active sin su diagonal            (w_ij >= 0)
        cortadas_i = -sum_j L_active[i,j]                (peso de aristas hacia celdas MUERTAS)
        L4_dirichlet = L_active                          (produccion)
        L4_neumann   = O - diag(sum_j O_ij)              (filas suman cero)
        B_neumann    = filas sqrt(w_ij)(e_i - e_j)       => B^T B = -L4_neumann
        B_dirichlet  = B_neumann + filas sqrt(cortadas_i) e_i  => B^T B = -L_active
    Es decir: la MISMA frontera en los dos ordenes, y el mismo orden en las dos
    fronteras. Sin esa consistencia el 2x2 no separa nada.

POR QUE SE BARRE lambda Y NO SE COMPARA A alpha_spatial FIJO. Los cuatro operadores
tienen normas distintas, asi que el mismo alpha_spatial NO es la misma cantidad de
regularizacion: comparar a alpha fijo mediria la FUERZA del regularizador, no su
FORMA. Se barre alpha por brazo y se reporta (a) el techo de cada operador sobre el
barrido y (b) el punto de produccion (alpha_spatial=1.0), que es el que corre el
usuario. Este repositorio ya se equivoco cinco veces midiendo una configuracion y
hablando de otra.

EL CONTROL QUE HACE HONESTA LA MEDICION. Si no hay celdas inactivas, L_active == L_full,
sus filas SUMAN CERO y Dirichlet y Neumann son el MISMO operador. El experimento lo
comprueba: en el mundo SIN topografia los dos brazos deben salir IDENTICOS. Un arnes
que "encuentra" diferencia ahi esta midiendo ruido del solver, no la frontera.

Correr desde terraquantum-backend:
    py -3.14 scripts/validation/f29_operador_suavidad.py --seeds 5
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import scipy.sparse as sp

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace", line_buffering=True)

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from exploration.gravimetry import GravimetryForward, GravimetryInversion  # noqa: E402

# -- El mundo: el dique inclinado de tests/test_benchmark_dipping_dike.py ------
BLOCK = 30.0
NX, NY, NZ = 28, 18, 4
DIP = np.radians(60.0)
TOP_Y = 100.0
HALF = 37.5
DIPLEN = 400.0
X0 = 200.0
DELTA_RHO = 0.5
LAMBDA = 0.005
NOISE_PCT = 0.02

MODOS = ("orden4_dirichlet_PRODUCCION", "orden4_neumann",
         "orden1_dirichlet", "orden1_neumann")


def inside_dike(x, y):
    a = (x - X0) * np.cos(DIP) + (y - TOP_Y) * np.sin(DIP)
    p = np.abs(-(x - X0) * np.sin(DIP) + (y - TOP_Y) * np.cos(DIP))
    return (a >= 0) & (a <= DIPLEN) & (p <= HALF)


def centers(nx, ny, nz, bs):
    gx, gy, gz = np.mgrid[0:nx, 0:ny, 0:nz]
    return (gx.flatten(order="F") * bs + bs / 2,
            gy.flatten(order="F") * bs + bs / 2,
            gz.flatten(order="F") * bs + bs / 2)


def sensores():
    sx = np.linspace(BLOCK / 2, NX * BLOCK - BLOCK / 2, 20)
    sz = np.linspace(BLOCK / 2, NZ * BLOCK - BLOCK / 2, 4)
    a, b = np.meshgrid(sx, sz, indexing="ij")
    return np.column_stack([a.ravel(), np.zeros(a.size), b.ravel()])


def operadores(L_active):
    """{nombre: matriz} con la convencion L = W - D (off-diag >= 0, diagonal < 0)."""
    L = sp.csr_matrix(L_active)
    d = L.diagonal()
    O = (L - sp.diags(d)).tocoo()
    sum_off = np.asarray(O.sum(axis=1)).ravel()
    cortadas = np.maximum(-(d + sum_off), 0.0)

    L4_dir = L
    L4_neu = (O.tocsr() - sp.diags(sum_off)).tocsr()

    m = O.row < O.col
    r, c, w = O.row[m], O.col[m], np.maximum(O.data[m], 0.0)
    n_e = len(r)
    n = L.shape[0]
    raiz = np.sqrt(w)
    B_neu = sp.coo_matrix(
        (np.concatenate([raiz, -raiz]),
         (np.concatenate([np.arange(n_e), np.arange(n_e)]),
          np.concatenate([r, c]))),
        shape=(n_e, n)).tocsr()
    idx = np.nonzero(cortadas > 0)[0]
    B_dir = sp.vstack([B_neu, sp.coo_matrix(
        (np.sqrt(cortadas[idx]), (np.arange(len(idx)), idx)),
        shape=(len(idx), n))]).tocsr()

    return ({"orden4_dirichlet_PRODUCCION": L4_dir, "orden4_neumann": L4_neu,
             "orden1_dirichlet": B_dir, "orden1_neumann": B_neu},
            int((cortadas > 0).sum()))


class InversionConOperador(GravimetryInversion):
    """Sustituye SOLO el operador de suavidad; todo lo demas es el motor de produccion."""

    modo = "orden4_dirichlet_PRODUCCION"
    diag: dict = {}

    def _lsqr_cadena_de_pesos(self, cfg, est, g_observed, hx, hy, hz):
        super()._lsqr_cadena_de_pesos(cfg, est, g_observed, hx, hy, hz)
        ops, n_frontera = operadores(est.L_active)
        filas = np.asarray(sp.csr_matrix(est.L_active).sum(axis=1)).ravel()
        InversionConOperador.diag = {
            "n_active": int(est.n_active), "n_dead": int(est.n_dead),
            "n_sol": int(est.n_active_sol),
            "celdas_frontera_con_arista_cortada": n_frontera,
            "max_abs_suma_de_fila_L_active": float(np.max(np.abs(filas))),
        }
        est.L_active = ops[self.modo]
        est.L_scaled = (est.L_active @ est.Ws).tocsr()


def pr_auc(score, verdad):
    orden = np.argsort(-score)
    t = verdad[orden].astype(float)
    pos = t.sum()
    if pos == 0:
        return float("nan")
    tp, fp = np.cumsum(t), np.cumsum(1 - t)
    rec, pre = tp / pos, tp / np.maximum(tp + fp, 1e-12)
    return float(np.sum(np.diff(np.concatenate([[0.0], rec])) * pre))


def nitidez_del_contacto(contraste, verdad_bin, activo, nx, ny, nz):
    """ACAD-3 en una cifra: |salto| medio del modelo A TRAVES del contacto verdadero.

    Un operador que sobre-suaviza reparte el contraste a los dos lados del contacto y
    baja este numero; uno de primer orden deberia conservarlo mejor. Se mide SOLO en
    las aristas que cruzan el contacto (dentro<->fuera), no en todo el volumen.
    """
    c = contraste.reshape((nx, ny, nz), order="F")
    v = verdad_bin.reshape((nx, ny, nz), order="F")
    m = activo.reshape((nx, ny, nz), order="F")
    saltos = []
    for eje in (0, 1, 2):
        if c.shape[eje] < 2:
            continue
        a = np.take(v, range(0, v.shape[eje] - 1), axis=eje)
        b = np.take(v, range(1, v.shape[eje]), axis=eje)
        ma = np.take(m, range(0, m.shape[eje] - 1), axis=eje)
        mb = np.take(m, range(1, m.shape[eje]), axis=eje)
        # SOLO aristas que cruzan el contacto Y con las dos celdas ACTIVAS: en el
        # aire el motor devuelve NaN, y un NaN se propaga a la media entera.
        cruza = (a != b) & ma & mb
        ca = np.take(c, range(0, c.shape[eje] - 1), axis=eje)
        cb = np.take(c, range(1, c.shape[eje]), axis=eje)
        if cruza.any():
            saltos.append(np.abs(cb - ca)[cruza])
    return float(np.mean(np.concatenate(saltos))) if saltos else float("nan")


def medir(contraste, verdad_bin, activo, nx, ny, nz):
    # El motor devuelve NaN en las celdas de AIRE. Medir sobre el vector completo
    # contamina TODO: `np.sort` manda los NaN al final y corre el umbral de volumen,
    # y `corrcoef` devuelve NaN entero. Las metricas de recuperacion se calculan por
    # tanto SOLO sobre el dominio activo, que ademas es el unico donde el modelo
    # existe. (Medido el 2026-09-06: sin esta mascara, el mundo con topografia daba
    # pearson_r=nan y un IoU de 0,0636 que no significaba nada.)
    act = np.asarray(activo, dtype=bool) & np.isfinite(contraste)
    s_all = np.abs(contraste)
    s = s_all[act]
    v = verdad_bin[act]
    n = int(v.sum())
    if n == 0 or s.size == 0:
        return {k: float("nan") for k in COLS}
    pred = s >= np.sort(s)[-n]
    inter = int((pred & v).sum())
    union = int((pred | v).sum())
    c3 = contraste.reshape((nx, ny, nz), order="F")
    v3 = verdad_bin.reshape((nx, ny, nz), order="F")
    a3 = act.reshape((nx, ny, nz), order="F")
    primeras, verdad_primeras = [], []
    for i in range(nx):
        for k in range(nz):
            col = np.nonzero(a3[i, :, k])[0]
            if len(col):
                primeras.append(c3[i, col[0], k])
                verdad_primeras.append(v3[i, col[0], k])
    primeras = np.asarray(primeras, dtype=float)
    verdad_primeras = np.asarray(verdad_primeras, dtype=bool)
    return {
        "pr_auc": pr_auc(s, v),
        "iou@vol": float(inter / union) if union else float("nan"),
        "pearson_r": (float(np.corrcoef(s, v.astype(float))[0, 1])
                      if s.std() > 0 else float("nan")),
        "nitidez_contacto": nitidez_del_contacto(contraste, verdad_bin, act, nx, ny, nz),
        "abs_media_primera_banda": float(np.mean(np.abs(primeras))) if len(primeras) else float("nan"),
        "media_primera_banda_sobre_dique": (float(np.mean(primeras[verdad_primeras]))
                                            if verdad_primeras.any() else float("nan")),
    }


COLS = ("pr_auc", "iou@vol", "pearson_r", "nitidez_contacto",
        "abs_media_primera_banda", "media_primera_banda_sobre_dique")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--refine", type=int, default=3)
    ap.add_argument("--alphas", type=float, nargs="+", default=[0.01, 0.1, 1.0, 10.0, 100.0])
    ap.add_argument("--mundo", choices=["plano", "topografia", "ambos"], default="ambos")
    ap.add_argument("--out", default=str(Path(__file__).with_name("f29_operador_suavidad_report.json")))
    args = ap.parse_args()

    x_c, y_c, z_c = centers(NX, NY, NZ, BLOCK)
    verdad = np.where(inside_dike(x_c, y_c), DELTA_RHO, 0.0)
    verdad_bin = verdad > 0
    sens = sensores()
    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=2000.0)

    print("FASE 29 — ACAD-3 (orden del operador) y ACAD-4 (frontera implicita)")
    print(f"  mundo: dique 60 grados, techo {TOP_Y:.0f} m, "
          f"{int(verdad_bin.sum())}/{verdad_bin.size} celdas son dique")

    R = args.refine
    bf = BLOCK / R
    x_f, y_f, z_f = centers(NX * R, NY * R, NZ * R, bf)
    verdad_fina = np.where(inside_dike(x_f, y_f), DELTA_RHO, 0.0)
    t0 = time.perf_counter()
    g_limpio = GravimetryForward(bf, bf, bf, cutoff_radius=2000.0).build_sparse_kernel(
        x_f, y_f, z_f, sens) @ verdad_fina
    g_crimen = fwd.build_sparse_kernel(x_c, y_c, z_c, sens) @ verdad
    disc = 100 * float(np.abs(g_limpio - g_crimen).max() / np.abs(g_limpio).max())
    print(f"  anti-inverse-crime: dato en malla x{R} ({x_f.size} celdas, "
          f"{time.perf_counter()-t0:.0f}s); discrepancia {disc:.2f}% del pico "
          f"vs {100*NOISE_PCT:.0f}% de ruido")

    topo = np.where(x_c < 300.0, 60.0, 0.0)
    todos = {"plano": None, "topografia": topo}
    mundos = todos if args.mundo == "ambos" else {args.mundo: todos[args.mundo]}

    inv = InversionConOperador(NX, NY, NZ, BLOCK)
    rms = float(np.sqrt(np.mean(g_limpio ** 2)))
    res: dict = {}
    dominio: dict = {}
    for nombre_mundo, te in mundos.items():
        print(f"\n--- mundo '{nombre_mundo}' ---")
        activo = (y_c - BLOCK / 2.0) >= (np.zeros_like(y_c) if te is None else te)
        for s in range(args.seeds):
            rng = np.random.default_rng(1000 + s)
            g_ruido = g_limpio + rng.normal(0.0, NOISE_PCT * rms, size=len(g_limpio))
            for alpha in args.alphas:
                for modo in MODOS:
                    InversionConOperador.modo = modo
                    dens, _, _, _ = inv.solve_inversion_lsqr(
                        g_ruido, None, y_c, lambda_mag=LAMBDA, alpha_spatial=alpha,
                        forward_model=fwd, sensor_coords=sens, x_c=x_c, z_c=z_c,
                        topography_elevations=te,
                        m_ref=np.zeros(NX * NY * NZ, dtype=np.float64),
                    )
                    dominio[nombre_mundo] = InversionConOperador.diag
                    contraste = dens - inv.base_density
                    m = medir(contraste, verdad_bin, activo, NX, NY, NZ)
                    m.update(seed=s, alpha=float(alpha), modo=modo, mundo=nombre_mundo,
                             huella=float(np.nansum(np.abs(dens))))
                    res.setdefault(f"{nombre_mundo}|{modo}|{alpha:g}", []).append(m)
            print(f"    semilla {s+1}/{args.seeds} ({time.perf_counter()-t0:.0f}s)", flush=True)
        print(f"    dominio: {dominio[nombre_mundo]}")

    Path(args.out).write_text(json.dumps(
        {"config": vars(args), "mundo": {"discrepancia_pct": round(disc, 2)},
         "dominio": dominio, "resultados": res}, indent=1, ensure_ascii=False),
        encoding="utf-8")

    print("\n=== CONTROL: sin celdas inactivas la frontera NO EXISTE ===")
    print("  (mundo plano => L_active == L_full => filas suman cero => Dirichlet == Neumann)")
    for alpha in args.alphas:
        a = res.get(f"plano|orden4_dirichlet_PRODUCCION|{alpha:g}")
        b = res.get(f"plano|orden4_neumann|{alpha:g}")
        if a and b:
            d = max(abs(x["huella"] - y["huella"]) for x, y in zip(a, b))
            print(f"  alpha={alpha:<7g} |dif| max Dirichlet vs Neumann = {d:.3e}"
                  f"   {'IDENTICOS (control OK)' if d == 0.0 else '<<< DISTINTOS'}")

    print("\n=== MEDIANAS ===")
    print(f"{'mundo':12s}{'operador':32s}{'alpha':>7s}" + "".join(f"{c[:15]:>17s}" for c in COLS))
    for k in sorted(res):
        mu, modo, alpha = k.split("|")
        v = res[k]
        print(f"{mu:12s}{modo:32s}{alpha:>7s}" +
              "".join(f"{np.median([r[c] for r in v]):17.4f}" for c in COLS))

    print(f"\nescrito {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
