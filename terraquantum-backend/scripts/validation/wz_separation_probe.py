# -*- coding: utf-8 -*-
"""FASE 4 (auditoria 06 §10) — Resolver el depth-weighting inerte (H-1).

PREGUNTA QUE ESTA SONDA RESPONDE, MIDIENDO
------------------------------------------
H-1 dice que en `exploration/gravimetry.py` la normalizacion de columnas `Ws` cancela
EXACTAMENTE el depth weighting `Wz`, de modo que `depth_beta` es algebraicamente inerte
y el peso de modelo EFECTIVO no es el de Li & Oldenburg sino la norma de columna del
kernel. La Fase 4 pregunta: **si se separan los dos conceptos hoy fundidos —
normalizacion algebraica (no debe cambiar la solucion) y peso fisico del modelo (si debe
cambiarla)— ¿se recupera capacidad de resolver profundidad?**

LA ALGEBRA, ESCRITA ENTERA (es lo que hace auditable a esta sonda)
------------------------------------------------------------------
Produccion (`solve_inversion_lsqr`, L2, sin padding/anclajes/m_ref) ensambla, en la
variable transformada `m_tilde`:

    [ G_w · Wz · Ws       ]           [ d_w ]
    [ lam_sp · L · Wz · Ws ] m_tilde ~ [  0  ]        con  m = Wz·Ws · m_tilde
    [ diag(lam_eff)       ]           [  0  ]

con `Wz = diag((z+z0)^(+beta/2))` (normalizada a media 1) y
`Ws = diag(1/‖col_j(G_w·Wz)‖) = diag(1/(wz_j·‖col_j(G_w)‖))`.

Luego `Wz·Ws = diag(1/‖col_j(G_w)‖)` — **beta se cancela** — y sustituyendo
`m_tilde = diag(‖col_j(G_w)‖)·m` el sistema en espacio FISICO es:

    ‖G_w·m − d_w‖²  +  lam_sp²·‖L·m‖²  +  lam_eff²·Σ_j (‖col_j(G_w)‖ · m_j)²

Es decir: **produccion SI tiene peso de modelo dependiente de la profundidad, pero es
`u_j = ‖col_j(W_d·G)‖` (ponderacion por sensibilidad, exponente 1), no `(z+z0)^(−beta/2)`.**
Los bounds mapean exactamente: `lb_tilde_j = (rho_min − base)·‖col_j‖` ⇔ box fisico.

Esta sonda reescribe el MISMO problema en espacio fisico y expone DOS ejes que
produccion tiene fundidos:

  1. `u` — **peso de modelo** (entra en el funcional, DEBE cambiar la solucion):
        arm "prod"    : u_j = ‖col_j(G_w)‖                (= produccion, exacto)
        arm "sep@beta": u_j = (z_j+z0)^(−beta/2), reescalado a mean(u) = mean(‖col‖)
        (el reescalado solo recentra la rejilla de lambda; Morozov re-elige lambda en
         cada brazo, asi que cualquier constante global queda absorbida)
  2. `P` — **precondicionador** de columna (NO debe cambiar la solucion):
        "colG": P = diag(1/‖col_j(G_w)‖)      (el de produccion)
        "colA": P = diag(1/‖col_j(A_aug)‖)    (equilibracion de la matriz completa)
     Se resuelve `(A·P)·y ~ b` con bounds `lb/p ≤ y ≤ ub/p` y `m = P·y`: cambio de
     variable biyectivo de TODO el sistema ⇒ mismo minimizador, distinto condicionamiento.

TRES CONTROLES ANTES DE CREERLE UN SOLO NUMERO AL BARRIDO
---------------------------------------------------------
  C1  FIDELIDAD   : sonda(u=‖col‖, P=colG) vs `solve_inversion_lsqr` de produccion.
                    Si no coinciden, la sonda mide otra cosa y el barrido no vale nada.
  C2  INVARIANCIA : sonda(u=‖col‖, P=colG) vs sonda(u=‖col‖, P=colA).
                    Demuestra empiricamente que el precondicionador NO mueve la solucion
                    — la mitad "algebraica" de H-1.
  C3  PERILLA VIVA: sonda(u=(z+z0)^(−beta/2)) con beta distinto DEBE dar modelos
                    distintos. Si sale byte-identico, la separacion esta mal puesta y
                    hay que reubicarla, no seguir midiendo.

DISCIPLINA (docs/07_VALIDATION_FRAMEWORK.md)
--------------------------------------------
* Verdad ANALITICA (esfera enterrada, forma cerrada) ⇒ anti-inverse-crime: el dato NO se
  genera con el operador que invierte.
* Morozov re-elige lambda en AMBOS brazos (la auditoria lo exige: cambiar el funcional
  cambia el lambda que Morozov selecciona; comparar con lambda congelado mide otra cosa).
* >= 5 semillas de ruido por celda del barrido (hay bimodalidad medida por realizacion).
* El veredicto se juzga sobre TODOS los regimenes de profundidad a la vez. Un peso que
  solo acierta a 900 m es un regimen, no un arreglo.
* NO toca el motor. Es un script de validacion, no un cambio de comportamiento.

USO
---
    python scripts/validation/wz_separation_probe.py --controls
    python scripts/validation/wz_separation_probe.py --calibrate
    python scripts/validation/wz_separation_probe.py --sweep
    python scripts/validation/wz_separation_probe.py --sweep --depths 600 --seeds 2
    python scripts/validation/wz_separation_probe.py --sweep --shard 0/4   # paralelizable
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import lsqr

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from exploration.gravimetry import (  # noqa: E402
    GravimetryForward,
    GravimetryInversion,
    _sigma_parametric,
)
from exploration.solver_preconditioned import solve_inversion_pgd_fista  # noqa: E402
from scripts.validation.error_budget import (  # noqa: E402  (linaje explicito del harness)
    _grid_centers_fortran,
    _sphere_gy_ms2,
)
from services.field_validation_service import estimate_location_error  # noqa: E402

# ── Malla del barrido ────────────────────────────────────────────────────────────
# IDENTICA a la de `error_budget.py` (18x14x18 @ 125 m) a proposito: es la malla en la
# que el proyecto ya publico su presupuesto de error, asi que los numeros de esta sonda
# son comparables con los que ya estan documentados, no una isla nueva.
BLOCK = 125.0
NX = NZ = 18          # 2250 m de lado
NY = 14               # 1750 m de profundidad (cubre 900 m + radio 150 con margen)
CUTOFF = 2600.0
MESH_CENTER = NX * BLOCK / 2.0        # 1125 m
BASE_DENSITY = 2.67                   # t/m3 roca caja
DENSITY_MAX = BASE_DENSITY + 2.0

# ── Caso sintetico (verdad analitica) ────────────────────────────────────────────
RADIUS_M = 150.0
DELTA_RHO = 0.6
SPAN_M = 1500.0
N_SIDE = 12
NOISE_MGAL = 0.02
ALPHA_SPATIAL = 1.0

# ── Ejes del barrido (los que fija la Fase 4) ────────────────────────────────────
BETAS = [0.0, 1.0, 1.5, 2.0, 3.0]
DEPTHS = [150.0, 300.0, 600.0, 900.0]
# 8 semillas, no 5. La Fase 4 exige >=5; se usan 8 porque el proyecto tiene MEDIDA una
# bimodalidad por realizacion de ruido (1 de cada 3 realizaciones da un error de
# profundidad ~9x mayor con diagnosticos identicos). Con 5 semillas la mediana de un
# brazo puede decidirse por una sola realizacion afortunada.
SEEDS = [20260801, 20260802, 20260803, 20260804, 20260805, 20260806, 20260807, 20260808]

# ── Morozov: identico al de produccion (geophysics_service.py:3026) ──────────────
MOROZOV_CANDIDATES = [0.01, 0.05623, 0.31623, 1.77828, 10.0]

# Norma de regularizacion del barrido. Produccion empareja Morozov con "L2"
# (csv_package_service.py:76: con auto-lambda de Morozov la norma compacta dispersa el
# ruido en focos). L2 ⇒ un solo solve por lambda, sin bucle IRLS.
REG_NORM = "L2"
COMPACT_MAX_IRLS = 2
COMPACT_EPS = 0.05

# ── Padding (R-02) ───────────────────────────────────────────────────────────────
# En produccion el padding NO es opcional: la ruta gravimetrica llama siempre a
# `build_tensor_mesh_with_padding` (geophysics_service.py:2648) y pasa siempre
# `padding_mask=~is_core` al solver (:3002). El anillo se penaliza kappa=1e5 veces mas
# en la smallness. Aqui se modela sobre malla uniforme —un anillo de PAD_CELLS celdas
# en X/Z y PAD_CELLS capas al fondo en Y— porque lo que este experimento manipula es la
# ESTRUCTURA de la regularizacion (quien pesa cuanto), no el ancho geometrico de las
# celdas de amortiguacion. El barrido se corre con y sin anillo: si el veredicto
# cambiara entre los dos, seria el propio hallazgo.
PAD_CELLS = 2
PADDING_KAPPA = 1e5


# ════════════════════════════════════════════════════════════════════════════════
# 1. El problema (kernel, datos, operadores) — construido con las clases REALES
# ════════════════════════════════════════════════════════════════════════════════
def _padding_mask_full() -> np.ndarray:
    """Anillo de padding sobre malla uniforme, en orden Fortran (igual que los centros)."""
    ix, iy, iz = np.meshgrid(np.arange(NX), np.arange(NY), np.arange(NZ), indexing="ij")
    ix, iy, iz = ix.ravel(order="F"), iy.ravel(order="F"), iz.ravel(order="F")
    is_core = (
        (ix >= PAD_CELLS) & (ix < NX - PAD_CELLS)
        & (iz >= PAD_CELLS) & (iz < NZ - PAD_CELLS)
        & (iy < NY - PAD_CELLS)
    )
    return ~is_core


def build_problem(depth_m: float, seed: int, *, noise_mgal: float = NOISE_MGAL) -> dict:
    """Survey sintetico + kernel + operadores, en espacio FISICO.

    El dato viene de la forma cerrada de la esfera (anti-inverse-crime); el kernel de
    inversion lo construye el forward de produccion.
    """
    rng = np.random.default_rng(seed)
    cx = cz = MESH_CENTER
    by = float(depth_m)

    half = SPAN_M / 2.0
    ax = np.linspace(cx - half, cx + half, N_SIDE)
    gx, gz = np.meshgrid(ax, ax, indexing="ij")
    sensors = np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()]).astype(np.float64)

    g_clean = _sphere_gy_ms2(sensors, cx, by, cz, RADIUS_M, DELTA_RHO)
    noise = noise_mgal * 1e-5
    g_obs = g_clean + noise * rng.standard_normal(g_clean.size)
    sigma_floor = max(noise, 1e-12)

    x_c, y_c, z_c = _grid_centers_fortran(NX, NY, NZ, BLOCK)
    inv = GravimetryInversion(NX, NY, NZ, BLOCK, base_density=BASE_DENSITY)
    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF)

    # ── Celdas activas: topografia plana ⇒ todas (mismo criterio que produccion) ──
    topo_depth = np.zeros(inv.total_voxels, dtype=np.float64)
    active_cells = (y_c - (BLOCK / 2.0)) >= topo_depth
    n_active = int(np.sum(active_cells))

    G_active = fwd._build_sparse_kernel(
        x_c[active_cells], y_c[active_cells], z_c[active_cells], sensors
    )

    # ── R-05 Observable domain: identico a gravimetry.py:~2120 ───────────────────
    col_sens = np.asarray(G_active.power(2).sum(axis=0)).ravel()
    thr = 1e-6 * max(float(np.max(col_sens)), 1e-30)
    obs_in_active = col_sens > thr
    n_dead = n_active - int(np.sum(obs_in_active))
    if n_dead > 0:
        G_active = G_active[:, obs_in_active]
    y_c_sol = y_c[active_cells][obs_in_active]
    topo_sol = topo_depth[active_cells][obs_in_active]
    n_sol = int(np.sum(obs_in_active))

    # ── Pesos de dato (F0.9): sigma parametrico, igual que produccion ────────────
    sigma = _sigma_parametric(g_obs, sigma_floor, 0.02)
    Wd = sp.diags(1.0 / sigma)
    G_w = (Wd @ G_active).tocsr()
    d_w = Wd @ g_obs

    # ── Laplaciano reducido a activas/observables ────────────────────────────────
    L_full = inv._build_laplacian()
    L_active = L_full.tocsr()[active_cells, :][:, active_cells]
    if n_dead > 0:
        L_active = L_active.tocsr()[obs_in_active, :][:, obs_in_active]

    col_norms = np.sqrt(G_w.power(2).sum(axis=0)).A1
    col_norms = np.maximum(col_norms, 1e-12)

    z0 = BLOCK / 2.0
    true_depth = np.clip(y_c_sol - topo_sol, a_min=1.0, a_max=None)
    pad_sol = _padding_mask_full()[active_cells][obs_in_active]

    return {
        "padding_sol": pad_sol,
        "inv": inv, "fwd": fwd, "sensors": sensors, "g_obs": g_obs, "sigma": sigma,
        "sigma_floor": sigma_floor, "G_active": G_active, "G_w": G_w.tocsr(),
        "d_w": np.asarray(d_w, dtype=np.float64), "L_active": L_active.tocsr(),
        "col_norms": col_norms, "true_depth": true_depth, "z0": z0,
        "x_c": x_c, "y_c": y_c, "z_c": z_c, "active_cells": active_cells,
        "obs_in_active": obs_in_active, "n_active": n_active, "n_sol": n_sol,
        "n_sensors": int(sensors.shape[0]),
        # lambda_spatial: gravimetry.py:2280 usa n_active (no n_sol)
        "lambda_spatial": float(ALPHA_SPATIAL) * (int(sensors.shape[0]) / n_active),
        "truth": {"cx": cx, "cy": by, "cz": cz, "radius_m": RADIUS_M,
                  "delta_rho": DELTA_RHO, "top_m": by - RADIUS_M},
        "depth_m": by, "seed": int(seed),
        "peak_mgal": float(np.max(np.abs(g_clean))) / 1e-5,
    }


# ════════════════════════════════════════════════════════════════════════════════
# 2. Peso de modelo u_j (el eje FISICO) y precondicionador P (el eje ALGEBRAICO)
# ════════════════════════════════════════════════════════════════════════════════
def model_weight(prob: dict, arm: str, beta: Optional[float] = None, *,
                 padding: bool = False) -> np.ndarray:
    """Peso de modelo en espacio FISICO. Entra en el funcional: DEBE mover la solucion."""
    if arm == "prod":
        u = prob["col_norms"].copy()
    elif arm == "sep":
        if beta is None:
            raise ValueError("arm 'sep' exige beta")
        u = (prob["true_depth"] + prob["z0"]) ** (-0.5 * float(beta))
        # Reescala a la MISMA media que el peso de produccion: no cambia la fisica del
        # brazo (Morozov re-elige lambda), solo mantiene comparable la rejilla de lambda.
        u = u * (float(np.mean(prob["col_norms"])) / float(np.mean(u)))
    else:
        raise ValueError(f"arm desconocido: {arm!r}")
    if padding:
        # R-02: gravimetry.py:_mk_small sustituye el peso del padding por kappa*lam_eff.
        # En espacio fisico eso equivale a multiplicar u_j por kappa en el anillo.
        u = np.where(prob["padding_sol"], PADDING_KAPPA * u, u)
    return u


def _assemble(prob: dict, u: np.ndarray, lam: float, focus: Optional[np.ndarray]):
    """Sistema aumentado en espacio FISICO m (contraste t/m3).

        [ G_w        ]       [ d_w ]
        [ lam_sp · L ] m  ~  [  0  ]
        [ diag(w_sm) ]       [  0  ]
    """
    # lambda_mag_eff: calibracion N_CALIB=256 de produccion (gravimetry.py:2325)
    lam_eff = float(lam) * np.sqrt(float(prob["n_sol"]) / 256.0)
    w_sm = lam_eff * u
    if focus is not None:
        w_sm = w_sm * focus
    A = sp.vstack([
        prob["G_w"],
        prob["lambda_spatial"] * prob["L_active"],
        sp.diags(w_sm),
    ]).tocsr()
    b = np.concatenate([
        prob["d_w"],
        np.zeros(prob["L_active"].shape[0], dtype=np.float64),
        np.zeros(prob["n_sol"], dtype=np.float64),
    ])
    return A, b, w_sm


def _precond(prob: dict, A: sp.csr_matrix, mode: str) -> np.ndarray:
    """Vector p tal que se resuelve (A·diag(p))·y ~ b y m = p·y. Solo condicionamiento."""
    if mode == "colG":
        return 1.0 / prob["col_norms"]
    if mode == "colA":
        cn = np.sqrt(A.power(2).sum(axis=0)).A1
        return 1.0 / np.maximum(cn, 1e-30)
    if mode == "none":
        return np.ones(prob["n_sol"], dtype=np.float64)
    raise ValueError(f"precond desconocido: {mode!r}")


def _solve_box(A, b, lb, ub, p, *, use_gpcg: bool = True):
    """LSQR + clip + GPCG proyectado sobre el sistema PRECONDICIONADO."""
    Ap = (A @ sp.diags(p)).tocsr()
    lb_y, ub_y = lb / p, ub / p        # p > 0 ⇒ conserva el orden
    res = lsqr(Ap, b, damp=0.0, iter_lim=500, atol=1e-8, btol=1e-8, show=False)
    y = np.clip(res[0], lb_y, ub_y)
    acond = float(res[6])
    info: dict = {}
    if use_gpcg:
        y, info = solve_inversion_pgd_fista(Ap, b, lb_y, ub_y, x0=y)
    return p * y, acond, info


# ════════════════════════════════════════════════════════════════════════════════
# 3. Inversion completa (bucle IRLS opcional) — un punto del barrido
# ════════════════════════════════════════════════════════════════════════════════
def invert(prob: dict, u: np.ndarray, lam: float, *, precond: str = "colA",
           reg_norm: str = REG_NORM, use_gpcg: bool = True,
           padding: bool = False) -> dict:
    lb = np.full(prob["n_sol"], BASE_DENSITY - BASE_DENSITY)   # rho_min = base ⇒ no-negatividad
    ub = np.full(prob["n_sol"], DENSITY_MAX - BASE_DENSITY)
    n_irls = 1 if str(reg_norm).lower() == "l2" else max(1, int(COMPACT_MAX_IRLS))
    focus = None
    eps: Optional[float] = None
    eps_floor = max(float(COMPACT_EPS), 1e-3)
    m = np.zeros(prob["n_sol"], dtype=np.float64)
    acond = float("nan")
    gpcg: dict = {}
    fro_sm = fro_sp = 0.0

    for it in range(n_irls):
        A, b, w_sm = _assemble(prob, u, lam, focus)
        p = _precond(prob, A, precond)
        m, acond, gpcg = _solve_box(A, b, lb, ub, p, use_gpcg=use_gpcg)
        fro_sm = float(np.linalg.norm(w_sm))
        fro_sp = float(sp.linalg.norm(prob["lambda_spatial"] * prob["L_active"]))
        if n_irls == 1:
            break
        # Minimum-support IRLS, misma receta que gravimetry.py:2573-2607. El foco se
        # aplica SOLO a celdas libres del nucleo: el padding conserva su rol de
        # restriccion fuerte L2 (gravimetry.py:2398-2403, `_free_mask`).
        free = ~prob["padding_sol"] if padding else np.ones(prob["n_sol"], dtype=bool)
        if eps is None:
            ref_c = np.abs(m[free]) if free.any() else np.abs(m)
            eps = max(eps_floor, 0.5 * float(np.percentile(ref_c, 90)))
        raw = 1.0 / np.sqrt(m ** 2 + eps ** 2)
        den = float(np.mean(raw[free])) if free.any() else float(np.mean(raw))
        fw = np.clip(raw / (den if den > 1e-12 else 1.0), 0.05, 20.0)
        focus = np.where(free, fw, 1.0)
        eps = max(eps * 0.7, eps_floor)

    residual = prob["g_obs"] - prob["G_active"] @ m
    chi2 = float(np.sum((residual / prob["sigma"]) ** 2)) / max(prob["n_sensors"], 1)
    denom = float(np.linalg.norm(prob["g_obs"]))
    misfit = float(np.linalg.norm(residual) / denom * 100.0) if denom > 0 else float("nan")
    return {
        "m": m, "chi2": chi2, "misfit_pct": misfit, "acond": acond,
        "smallness_over_smoothness": (fro_sm / fro_sp) if fro_sp > 0 else None,
        "gpcg_iters": gpcg.get("n_iter"),
    }


def morozov(prob: dict, u: np.ndarray, *, precond: str = "colA",
            reg_norm: str = REG_NORM, use_gpcg: bool = True,
            padding: bool = False) -> dict:
    """Discrepancia de Morozov replicando geophysics_service.py:3019-3070 (5 + 1 solves)."""
    trials, best = [], None

    def _try(lam: float):
        nonlocal best
        r = invert(prob, u, lam, precond=precond, reg_norm=reg_norm,
                   use_gpcg=use_gpcg, padding=padding)
        c = r["chi2"]
        score = abs(np.log10(c)) if np.isfinite(c) and c > 0 else float("inf")
        trials.append({"lambda": float(lam), "chi2": float(c),
                       "misfit_pct": r["misfit_pct"],
                       "s_over_s": r["smallness_over_smoothness"]})
        if best is None or score < best["score"]:
            best = {"score": score, "lambda": float(lam), "res": r}
        return c

    scan = [_try(lc) for lc in MOROZOV_CANDIDATES]
    for i in range(len(MOROZOV_CANDIDATES) - 1):
        c1, c2 = scan[i], scan[i + 1]
        if np.isfinite(c1) and np.isfinite(c2) and (c1 - 1.0) * (c2 - 1.0) < 0:
            _try(float(np.sqrt(MOROZOV_CANDIDATES[i] * MOROZOV_CANDIDATES[i + 1])))
            break

    warnings = []
    finite = [c for c in scan if np.isfinite(c)]
    if finite and all(c > 1.0 for c in finite):
        warnings.append("morozov_underfit_floor")
    if finite and all(c < 1.0 for c in finite):
        warnings.append("morozov_overfit_ceiling")
    return {"lambda": best["lambda"], "res": best["res"], "trials": trials,
            "warnings": warnings, "n_solves": len(trials)}


# ════════════════════════════════════════════════════════════════════════════════
# 4. Metricas contra la verdad
# ════════════════════════════════════════════════════════════════════════════════
def metrics(prob: dict, m_sol: np.ndarray) -> dict:
    """Errores de localizacion contra la esfera analitica. m_sol vive en espacio observable."""
    t = prob["truth"]
    contrast_active = np.zeros(prob["n_active"], dtype=np.float64)
    contrast_active[prob["obs_in_active"]] = m_sol
    rho = np.full(prob["inv"].total_voxels, np.nan, dtype=np.float64)
    rho[prob["active_cells"]] = np.clip(
        BASE_DENSITY + contrast_active, BASE_DENSITY, DENSITY_MAX
    )

    loc = estimate_location_error(
        rho, prob["x_c"], prob["y_c"], prob["z_c"],
        (t["cx"], t["cy"], t["cz"]), base_density=BASE_DENSITY,
    )
    c = np.abs(np.nan_to_num(rho, nan=BASE_DENSITY) - BASE_DENSITY)
    peak_depth = rec_top = None
    if float(np.max(c)) > 0:
        ipk = int(np.argmax(c))
        peak_depth = float(prob["y_c"][ipk])
        strong = c > 0.5 * float(np.max(c))
        rec_top = float(np.min(prob["y_c"][strong]))
    rec_peak_contrast = float(np.nanmax(rho - BASE_DENSITY))
    return {
        "horizontal_m": loc.get("horizontal_error_m"),
        "depth_centroid_m": loc.get("depth_error_m"),
        "recovered_centroid_m": loc.get("recovered_y_m"),
        "recovered_peak_depth_m": None if peak_depth is None else round(peak_depth, 1),
        "depth_peak_m": None if peak_depth is None else round(abs(peak_depth - t["cy"]), 1),
        "top_depth_m": None if rec_top is None else round(abs(rec_top - t["top_m"]), 1),
        "n_strong": loc.get("n_strong"),
        "density_recovery_frac": round(rec_peak_contrast / max(t["delta_rho"], 1e-9), 3),
    }


# ════════════════════════════════════════════════════════════════════════════════
# 5. CONTROLES — se corren antes de creerle nada al barrido
# ════════════════════════════════════════════════════════════════════════════════
def _prod_reference(prob: dict, lam: float, reg_norm: str = REG_NORM,
                    bounded: bool = True) -> dict:
    """Inversion de PRODUCCION (`solve_inversion_lsqr`) sobre el MISMO problema.

    `bounded` elige el solver interno de produccion, que depende del tamano del modelo:
      True  -> TRF/`lsq_linear` (la ruta de produccion para n_active <= 8.000)
      False -> LSQR + clip + GPCG proyectado (la ruta de produccion para mallas grandes,
               y la MISMA que usa esta sonda)
    Correr los dos permite separar "diferencia de formulacion" de "diferencia de solver".
    """
    import core.config as _cfg
    _prev = _cfg.USE_BOUNDED_SOLVER
    _cfg.USE_BOUNDED_SOLVER = bool(bounded)   # gravimetry lo importa dentro del bucle
    meta: dict = {}
    try:
        rho, _score, misfit, _sens = prob["inv"].solve_inversion_lsqr(
            prob["g_obs"], None, prob["y_c"], lambda_mag=lam, alpha_spatial=ALPHA_SPATIAL,
            forward_model=prob["fwd"], sensor_coords=prob["sensors"],
            x_c=prob["x_c"], z_c=prob["z_c"],
            density_min=BASE_DENSITY, density_max=DENSITY_MAX,
            noise_floor=prob["sigma_floor"], noise_pct=0.02, auto_kappa=True,
            prune_observable_domain=True, regularization_norm=reg_norm,
            compact_max_irls=COMPACT_MAX_IRLS, solver_meta=meta,
        )
    finally:
        _cfg.USE_BOUNDED_SOLVER = _prev
    contrast = np.nan_to_num(np.asarray(rho, dtype=np.float64), nan=BASE_DENSITY) - BASE_DENSITY
    return {"rho": np.asarray(rho, dtype=np.float64),
            "contrast_full": contrast, "misfit_pct": float(misfit), "meta": meta}


def _contrast_full_from_sol(prob: dict, m_sol: np.ndarray) -> np.ndarray:
    ca = np.zeros(prob["n_active"], dtype=np.float64)
    ca[prob["obs_in_active"]] = m_sol
    full = np.zeros(prob["inv"].total_voxels, dtype=np.float64)
    full[prob["active_cells"]] = np.clip(ca, 0.0, DENSITY_MAX - BASE_DENSITY)
    return full


def _rel_diff(a: np.ndarray, b: np.ndarray) -> dict:
    scale = max(float(np.max(np.abs(b))), 1e-30)
    d = np.abs(a - b)
    return {"max_abs_t_m3": float(np.max(d)),
            "max_rel_vs_peak": float(np.max(d) / scale),
            "l2_rel": float(np.linalg.norm(a - b) / max(np.linalg.norm(b), 1e-30))}


def run_controls(lam: float = 0.31623, depth_m: float = 600.0, seed: int = SEEDS[0]) -> dict:
    print("=" * 78)
    print("CONTROLES DE LA SONDA (antes de creerle un solo numero al barrido)")
    print("=" * 78, flush=True)
    prob = build_problem(depth_m, seed)
    print(f"malla {NX}x{NY}x{NZ}@{BLOCK:.0f}m | n_sol={prob['n_sol']:,} | "
          f"{prob['n_sensors']} estaciones | esfera a {depth_m:.0f} m | "
          f"pico {prob['peak_mgal']:.3f} mGal | lambda={lam:g}\n", flush=True)

    u_prod = model_weight(prob, "prod")

    t = time.time()
    ref_trf = _prod_reference(prob, lam, bounded=True)
    t_ref = time.time() - t
    print(f"  [prod ] solve_inversion_lsqr TRF      misfit={ref_trf['misfit_pct']:.3f}% "
          f"chi2={ref_trf['meta'].get('chi2_final'):.4f} ({t_ref:.0f}s)", flush=True)

    t = time.time()
    ref_lsqr = _prod_reference(prob, lam, bounded=False)
    print(f"  [prod ] solve_inversion_lsqr LSQR+GPCG misfit={ref_lsqr['misfit_pct']:.3f}% "
          f"chi2={ref_lsqr['meta'].get('chi2_final'):.4f} ({time.time()-t:.0f}s)", flush=True)

    t = time.time()
    a = invert(prob, u_prod, lam, precond="colG")
    print(f"  [C1   ] sonda u=||col||  P=colG        misfit={a['misfit_pct']:.3f}% "
          f"chi2={a['chi2']:.4f} ({time.time()-t:.1f}s)", flush=True)

    t = time.time()
    b = invert(prob, u_prod, lam, precond="colA")
    print(f"  [C2   ] sonda u=||col||  P=colA        misfit={b['misfit_pct']:.3f}% "
          f"chi2={b['chi2']:.4f} ({time.time()-t:.1f}s)", flush=True)

    m_a = _contrast_full_from_sol(prob, a["m"])
    # C1b aisla la FORMULACION: mismo solver interno (LSQR+GPCG) en sonda y produccion.
    # C1a incluye ademas la diferencia entre los dos solvers con bounds de produccion.
    c1 = _rel_diff(m_a, ref_lsqr["contrast_full"])
    c1_trf = _rel_diff(m_a, ref_trf["contrast_full"])
    # Cuanto se separan los DOS solvers de produccion entre si: es la vara con la que
    # hay que leer C1a (una sonda no puede parecerse mas al motor que el motor a si mismo).
    c1_prod_spread = _rel_diff(ref_trf["contrast_full"], ref_lsqr["contrast_full"])
    c2 = _rel_diff(_contrast_full_from_sol(prob, b["m"]), m_a)

    # C3 — perilla viva: la separacion debe hacer que beta MUEVA el modelo.
    c3_rows, c3_models = [], {}
    for beta in (0.0, 2.0):
        t = time.time()
        r = invert(prob, model_weight(prob, "sep", beta), lam, precond="colA")
        mm = metrics(prob, r["m"])
        c3_models[beta] = _contrast_full_from_sol(prob, r["m"])
        c3_rows.append({"beta": beta, "chi2": r["chi2"], "misfit_pct": r["misfit_pct"],
                        "peak_depth_m": mm["recovered_peak_depth_m"],
                        "centroid_m": mm["recovered_centroid_m"]})
        print(f"  [C3   ] sonda u=(z+z0)^-{beta/2:.1f}  beta={beta:<4g} "
              f"pico={mm['recovered_peak_depth_m']} m centroide={mm['recovered_centroid_m']} m "
              f"chi2={r['chi2']:.4f} ({time.time()-t:.0f}s)", flush=True)
    c3 = _rel_diff(c3_models[2.0], c3_models[0.0])

    def _fmt(tag, d):
        print(f"  {tag}: max|d|={d['max_abs_t_m3']:.3e} t/m3 "
              f"({d['max_rel_vs_peak']:.2%} del pico) L2rel={d['l2_rel']:.3e}")

    print()
    _fmt("C1b FIDELIDAD  sonda(colG) vs produccion LSQR+GPCG (mismo solver)", c1)
    _fmt("C1a            sonda(colG) vs produccion TRF                     ", c1_trf)
    _fmt("  vara         produccion TRF vs produccion LSQR+GPCG            ", c1_prod_spread)
    _fmt("C2  INVARIANCIA colG vs colA (mismo funcional, otro precond.)    ", c2)
    _fmt("C3  PERILLA     beta=0 vs beta=2 con la separacion               ", c3)

    verdict_c1 = c1["max_rel_vs_peak"] < 0.02
    # C1a solo puede exigirse hasta donde los propios solvers de produccion coinciden.
    verdict_c1a = c1_trf["max_rel_vs_peak"] <= max(2.0 * c1_prod_spread["max_rel_vs_peak"], 0.02)
    verdict_c2 = c2["max_rel_vs_peak"] < 0.02
    verdict_c3 = c3["max_rel_vs_peak"] > 0.05
    print()
    print(f"  C1b {'PASA' if verdict_c1 else 'FALLA'}  — la sonda reproduce el motor a igual solver")
    print(f"  C1a {'PASA' if verdict_c1a else 'FALLA'}  — y no se aparta del TRF mas que el propio motor")
    print(f"  C2  {'PASA' if verdict_c2 else 'FALLA'}  — el precondicionador NO mueve la solucion")
    print(f"  C3  {'PASA' if verdict_c3 else 'FALLA'}  — con la separacion, beta SI mueve la solucion")
    print("=" * 78, flush=True)

    out = {
        "kind": "wz_separation_controls",
        "config": {"mesh": [NX, NY, NZ], "block_m": BLOCK, "n_sol": prob["n_sol"],
                   "lambda": lam, "depth_m": depth_m, "seed": seed,
                   "reg_norm": REG_NORM},
        "prod_reference_trf": {"misfit_pct": ref_trf["misfit_pct"],
                               "chi2": ref_trf["meta"].get("chi2_final")},
        "prod_reference_lsqr_gpcg": {"misfit_pct": ref_lsqr["misfit_pct"],
                                     "chi2": ref_lsqr["meta"].get("chi2_final")},
        "C1b_fidelity_same_solver": c1, "C1a_fidelity_vs_trf": c1_trf,
        "C1_prod_solver_spread": c1_prod_spread,
        "C2_precond_invariance": c2, "C3_knob_alive": c3, "C3_rows": c3_rows,
        "verdict": {"C1b_fidelity": bool(verdict_c1), "C1a_vs_trf": bool(verdict_c1a),
                    "C2_invariance": bool(verdict_c2), "C3_knob_alive": bool(verdict_c3)},
        "elapsed_prod_trf_solve_s": round(t_ref, 1),
    }
    _write(out, "wz_separation_controls_report.json")
    return out


# ════════════════════════════════════════════════════════════════════════════════
# 6. BARRIDO
# ════════════════════════════════════════════════════════════════════════════════
def _arm_label(arm: str, beta: Optional[float]) -> str:
    return "prod" if arm == "prod" else f"sep_b{beta:g}"


def run_sweep(depths, betas, seeds, *, shard=None, reg_norm=REG_NORM, padding=False,
              out_name="wz_separation_sweep_report.json") -> dict:
    arms = [("prod", None)] + [("sep", b) for b in betas]
    combos = [(d, s, a, b) for d in depths for s in seeds for (a, b) in arms]
    if shard is not None:
        k, n = shard
        combos = [c for i, c in enumerate(combos) if i % n == k]
    print(f"BARRIDO FASE 4 — {len(combos)} puntos Morozov "
          f"({len(depths)} prof x {len(seeds)} semillas x {len(arms)} brazos)"
          + (f" [shard {shard[0]}/{shard[1]}]" if shard else ""))
    print(f"malla {NX}x{NY}x{NZ}@{BLOCK:.0f}m | norma={reg_norm} | "
          f"padding={'SI (kappa=%.0e)' % PADDING_KAPPA if padding else 'NO'} | "
          f"Morozov {MOROZOV_CANDIDATES}\n", flush=True)

    rows, t0 = [], time.time()
    cache_key, prob = None, None
    for i, (d, s, arm, beta) in enumerate(combos, 1):
        if cache_key != (d, s):
            prob = build_problem(d, s)
            cache_key = (d, s)
        u = model_weight(prob, arm, beta, padding=padding)
        t = time.time()
        mz = morozov(prob, u, precond="colA", reg_norm=reg_norm, padding=padding)
        mm = metrics(prob, mz["res"]["m"])
        row = {
            "arm": _arm_label(arm, beta), "beta": beta, "depth_m": d, "seed": s,
            "lambda_selected": mz["lambda"], "chi2": round(mz["res"]["chi2"], 4),
            "misfit_pct": round(mz["res"]["misfit_pct"], 3),
            "s_over_s": (None if mz["res"]["smallness_over_smoothness"] is None
                         else round(mz["res"]["smallness_over_smoothness"], 4)),
            "morozov_warnings": mz["warnings"], "n_solves": mz["n_solves"],
            "trials": mz["trials"], "elapsed_s": round(time.time() - t, 1),
            **mm,
        }
        rows.append(row)
        print(f"[{i:>3}/{len(combos)}] {row['arm']:<9s} prof={d:>4.0f} sem={s} "
              f"lam={row['lambda_selected']:<8.4g} chi2={row['chi2']:<8.4g} "
              f"pico={row['recovered_peak_depth_m']} (err {row['depth_peak_m']}) "
              f"cent_err={row['depth_centroid_m']} horiz={row['horizontal_m']} "
              f"rho={row['density_recovery_frac']} ({row['elapsed_s']}s)", flush=True)

    report = {
        "kind": "wz_separation_sweep",
        "config": {"mesh": [NX, NY, NZ], "block_m": BLOCK, "cutoff_m": CUTOFF,
                   "base_density": BASE_DENSITY, "density_max": DENSITY_MAX,
                   "radius_m": RADIUS_M, "delta_rho": DELTA_RHO, "span_m": SPAN_M,
                   "n_side": N_SIDE, "noise_mgal": NOISE_MGAL,
                   "alpha_spatial": ALPHA_SPATIAL, "reg_norm": reg_norm,
                   "padding": bool(padding), "pad_cells": PAD_CELLS,
                   "padding_kappa": PADDING_KAPPA if padding else None,
                   "n_padding_cells": (int(np.sum(prob["padding_sol"])) if prob else None),
                   "morozov_candidates": MOROZOV_CANDIDATES,
                   "depths": list(depths), "betas": list(betas), "seeds": list(seeds),
                   "shard": list(shard) if shard else None},
        "n_points": len(rows), "elapsed_s": round(time.time() - t0, 1), "rows": rows,
    }
    _write(report, out_name)
    return report


def _write(obj: dict, name: str) -> Path:
    out = Path(__file__).resolve().parent / name
    out.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=float),
                   encoding="utf-8")
    print(f"\nReporte -> {out}", flush=True)
    return out


def run_weight_shape(depth_m: float = 600.0, seed: int = SEEDS[0]) -> dict:
    """¿Que FORMA tiene el peso de modelo que produccion aplica de verdad?

    La auditoria infirio (§6.2, punto 3) que `‖col_j‖` decae "aproximadamente como 1/z²,
    un peso mucho mas agresivo y **de forma distinta** al estandar industrial". Esto lo
    mide en vez de inferirlo: ajusta `‖col_j(W_d·G)‖` a la parametrizacion de
    Li & Oldenburg `(z+z0)^(−beta/2)` y reporta el beta equivalente y lo bien que ajusta.
    """
    prob = build_problem(depth_m, seed)
    u, z, z0 = prob["col_norms"], prob["true_depth"], prob["z0"]
    zs = np.unique(z)
    med = np.array([float(np.median(u[z == zz])) for zz in zs])
    slope, icept = np.polyfit(np.log(zs + z0), np.log(med), 1)
    beta_eq = float(-2.0 * slope)
    pred = np.exp(np.polyval([slope, icept], np.log(zs + z0)))
    dev = float(np.max(np.abs(pred / med - 1.0)))

    print(f"FORMA DEL PESO DE MODELO EFECTIVO (malla {NX}x{NY}x{NZ}@{BLOCK:.0f} m, "
          f"esfera a {depth_m:.0f} m)")
    print(f"  capa (m):        " + " ".join(f"{v:>7.0f}" for v in zs))
    print(f"  ||col_j|| norm.: " + " ".join(f"{v:>7.3f}" for v in med / med[0]))
    print(f"\n  Ajuste a (z+z0)^(-beta/2):  beta_equivalente = {beta_eq:.2f}  "
          f"(desviacion max {dev:.1%})")
    print(f"  Estandar industrial Li & Oldenburg: beta = 2.0")
    print(f"\n  => El peso efectivo NO tiene 'forma distinta' al estandar: es una ley de")
    print(f"     potencia de la MISMA familia, con exponente {beta_eq:.2f} en vez de 2.")
    print(f"     El problema de H-1 no es la forma del peso, es que no es ajustable ni")
    print(f"     esta declarado: el codigo dice aplicar (z+z0)^(-beta/2) con beta=2.0 y")
    print(f"     lo que aplica es beta={beta_eq:.2f}, fijado por el kernel y no por nadie.")
    out = {"kind": "wz_effective_weight_shape",
           "depth_m": depth_m, "layers_m": zs.tolist(),
           "col_norm_median_normalized": (med / med[0]).tolist(),
           "beta_equivalent": beta_eq, "max_deviation_from_power_law": dev,
           "industrial_standard_beta": 2.0}
    _write(out, "wz_effective_weight_shape_report.json")
    return out


def run_calibrate() -> dict:
    """Cronometra un solve y un Morozov para dimensionar el barrido antes de lanzarlo."""
    prob = build_problem(600.0, SEEDS[0])
    u = model_weight(prob, "prod")
    t = time.time(); invert(prob, u, 0.31623, precond="colA"); t_solve = time.time() - t
    t = time.time(); mz = morozov(prob, u, precond="colA"); t_mz = time.time() - t
    n_pts = len(DEPTHS) * len(SEEDS) * (1 + len(BETAS))
    print(f"n_sol={prob['n_sol']:,} | 1 solve = {t_solve:.1f}s | "
          f"1 Morozov ({mz['n_solves']} solves) = {t_mz:.1f}s")
    print(f"barrido completo = {n_pts} puntos ~ {n_pts * t_mz / 60:.0f} min "
          f"(1 proceso) / ~{n_pts * t_mz / 60 / 4:.0f} min (4 shards)")
    return {"n_sol": prob["n_sol"], "t_solve_s": t_solve, "t_morozov_s": t_mz,
            "n_points": n_pts}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Fase 4 — sonda de separacion Ws/W_z")
    ap.add_argument("--controls", action="store_true", help="corre C1/C2/C3")
    ap.add_argument("--weight-shape", action="store_true",
                    help="mide la FORMA del peso de modelo que produccion aplica de verdad")
    ap.add_argument("--calibrate", action="store_true", help="cronometra y dimensiona")
    ap.add_argument("--sweep", action="store_true", help="corre el barrido")
    ap.add_argument("--depths", type=float, nargs="*", default=DEPTHS)
    ap.add_argument("--betas", type=float, nargs="*", default=BETAS)
    ap.add_argument("--seeds", type=int, nargs="*", default=SEEDS)
    ap.add_argument("--reg-norm", default=REG_NORM, choices=["L2", "compact"])
    ap.add_argument("--padding", action="store_true",
                    help="anillo de padding kappa=1e5 (el punto de operacion de produccion)")
    ap.add_argument("--shard", default=None, help="k/n para paralelizar por proceso")
    ap.add_argument("--out", default="wz_separation_sweep_report.json")
    ap.add_argument("--lam", type=float, default=0.31623, help="lambda de los controles")
    args = ap.parse_args()

    if not (args.controls or args.calibrate or args.sweep or args.weight_shape):
        ap.error("elige --controls, --weight-shape, --calibrate o --sweep")
    if args.weight_shape:
        run_weight_shape()
    if args.calibrate:
        run_calibrate()
    if args.controls:
        run_controls(lam=args.lam)
    if args.sweep:
        shard = None
        if args.shard:
            k, n = args.shard.split("/")
            shard = (int(k), int(n))
        run_sweep(args.depths, args.betas, args.seeds, shard=shard,
                  reg_norm=args.reg_norm, padding=args.padding, out_name=args.out)


if __name__ == "__main__":
    main()
