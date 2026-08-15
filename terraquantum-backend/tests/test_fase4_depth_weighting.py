# -*- coding: utf-8 -*-
"""FASE 4 — red que impide que el depth-weighting vuelva a mentir sobre si mismo.

La Fase 4 (auditoria 06 §10, hallazgo H-1) midio que en `GravimetryInversion.
solve_inversion_lsqr` el depth weighting `W_z` se cancelaba EXACTAMENTE contra la
normalizacion de columnas `Ws`, dejando `depth_beta` sin efecto fisico y el funcional
de regularizacion real distinto del documentado.

Estos tests convierten el resultado de la fase en invariantes ejecutables. No repiten
la medicion (eso vive en `scripts/validation/wz_separation_probe.py`); fijan las tres
afirmaciones de las que depende todo lo que la fase concluyo:

  1. El peso de modelo EFECTIVO del solver de grilla regular es `‖col_j(W_d·G)‖`
     (ponderacion por sensibilidad), no `(z+z0)^(-beta/2)`. Se comprueba resolviendo
     el MISMO problema escrito a mano en espacio fisico y exigiendo que coincida.
     Si alguien reintroduce un peso de profundidad en la cadena, este test cae.
  2. `depth_beta` ya no existe en la firma del solver de grilla regular. Un parametro
     que no hace nada es peor que no tenerlo: promete un control que no existe.
  3. `solve_inversion_treemesh` SI tiene un peso de profundidad VIVO y se queda como
     esta. Sin este test, el punto 2 invita a "limpiar por analogia" un solver donde
     el parametro si cambia la fisica.

    python -m pytest tests/test_fase4_depth_weighting.py -v
"""
from __future__ import annotations

import contextlib
import importlib
import inspect
import os
import sys

import numpy as np
import pytest
import scipy.sparse as sp
from scipy.sparse.linalg import lsqr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exploration.gravimetry import (  # noqa: E402
    GravimetryForward,
    GravimetryInversion,
    _sigma_parametric,
    solve_inversion_treemesh,
)
from exploration.solver_preconditioned import solve_inversion_pgd_fista  # noqa: E402
from exploration.treemesh import TreeMesh  # noqa: E402

NX = NZ = 8
NY = 6
BLOCK = 100.0
BASE_DENSITY = 2.67
DENSITY_MAX = BASE_DENSITY + 1.5
LAMBDA_MAG = 0.31623
ALPHA_SPATIAL = 1.0
CUTOFF = 3000.0


def _centers(nx, ny, nz, bs):
    ix, iy, iz = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    return ((ix.ravel(order="F") + 0.5) * bs,
            (iy.ravel(order="F") + 0.5) * bs,
            (iz.ravel(order="F") + 0.5) * bs)


def _case():
    """Cuerpo enterrado + survey. Pequeno a proposito: el test corre en segundos."""
    rng = np.random.default_rng(20260814)
    x_c, y_c, z_c = _centers(NX, NY, NZ, BLOCK)
    cx = cz = NX * BLOCK / 2.0
    ax = np.linspace(BLOCK, (NX - 1) * BLOCK, 7)
    gx, gz = np.meshgrid(ax, ax, indexing="ij")
    sensors = np.column_stack([gx.ravel(), np.zeros(gx.size), gz.ravel()]).astype(np.float64)

    contrast = np.zeros(x_c.size, dtype=np.float64)
    body = ((np.abs(x_c - cx) <= BLOCK) & (np.abs(z_c - cz) <= BLOCK)
            & (y_c >= 2 * BLOCK) & (y_c <= 3 * BLOCK))
    contrast[body] = 0.8
    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF)
    g = np.asarray(fwd._build_sparse_kernel(x_c, y_c, z_c, sensors) @ contrast).ravel()
    g = g + 0.01 * float(np.max(np.abs(g))) * rng.standard_normal(g.size)
    return x_c, y_c, z_c, sensors, g, 0.02 * float(np.max(np.abs(g)))


def _solve_physical_space(x_c, y_c, z_c, sensors, g_obs, noise_floor):
    """El MISMO problema, escrito a mano en espacio fisico con u_j = ‖col_j(W_d·G)‖.

    Sin cambio de variable y sin depth weighting: solo la ponderacion por sensibilidad
    que la Fase 4 midio como el peso de modelo realmente aplicado. `Ws` entra aqui como
    precondicionador de columna sobre TODOS los bloques, que es lo que un precondicionador
    debe ser: algebra, no fisica.
    """
    inv = GravimetryInversion(NX, NY, NZ, BLOCK, base_density=BASE_DENSITY)
    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF)
    active = (y_c - BLOCK / 2.0) >= 0.0
    n_active = int(np.sum(active))

    G_act = fwd._build_sparse_kernel(x_c[active], y_c[active], z_c[active], sensors)
    col_sens = np.asarray(G_act.power(2).sum(axis=0)).ravel()
    obs = col_sens > 1e-6 * max(float(np.max(col_sens)), 1e-30)
    if int(np.sum(obs)) != n_active:
        G_act = G_act[:, obs]
    n_sol = int(np.sum(obs))

    sigma = _sigma_parametric(g_obs, noise_floor, 0.02)
    G_w = (sp.diags(1.0 / sigma) @ G_act).tocsr()
    d_w = sp.diags(1.0 / sigma) @ g_obs

    L = inv._build_laplacian().tocsr()[active, :][:, active]
    if n_sol != n_active:
        L = L.tocsr()[obs, :][:, obs]

    u = np.maximum(np.sqrt(G_w.power(2).sum(axis=0)).A1, 1e-12)   # <-- el peso EFECTIVO
    lam_sp = float(ALPHA_SPATIAL) * (len(g_obs) / n_active)
    lam_eff = float(LAMBDA_MAG) * np.sqrt(float(n_sol) / 256.0)

    A = sp.vstack([G_w, lam_sp * L, sp.diags(lam_eff * u)]).tocsr()
    b = np.concatenate([d_w, np.zeros(L.shape[0]), np.zeros(n_sol)])
    lb = np.zeros(n_sol)
    ub = np.full(n_sol, DENSITY_MAX - BASE_DENSITY)

    p = 1.0 / u                                   # precondicionador de columna
    Ap = (A @ sp.diags(p)).tocsr()
    y = lsqr(Ap, b, damp=0.0, iter_lim=500, atol=1e-8, btol=1e-8, show=False)[0]
    y = np.clip(y, lb / p, ub / p)
    y, _ = solve_inversion_pgd_fista(Ap, b, lb / p, ub / p, x0=y)

    contrast_full = np.zeros(x_c.size, dtype=np.float64)
    idx = np.where(active)[0][obs] if n_sol != n_active else np.where(active)[0]
    contrast_full[idx] = np.clip(p * y, lb[0], ub[0])
    return contrast_full


@contextlib.contextmanager
def _pinned_solver_path():
    """Fija las TRES perillas que eligen el solver interno, y las restaura.

    Sin esto el test es orden-dependiente: pasa aislado y falla en suite. Dos razones,
    las dos MEDIDAS (no supuestas) mientras se cerraba la Fase 4:

    1. `solve_inversion_lsqr` elige entre TRF / LSMR / LSQR leyendo `core.config` **en cada
       llamada**. Si producción toma un camino iterativo distinto del de la referencia de
       abajo, la comparación mide el SOLVER en vez del FUNCIONAL — justo lo que este test
       no quiere medir. Con `USE_PROJECTED_SOLVER=False` la diferencia medida fue del 76 %.

    2. **El módulo hay que resolverlo AQUÍ, no al importar.** `tests/test_fase2_arranque.py`
       hace `sys.modules.pop("core.config")` + `importlib.import_module(...)`, lo que crea un
       objeto de módulo NUEVO y deja huérfana cualquier referencia tomada antes. Un
       `import core.config as cfg` a nivel de módulo parchea entonces un fantasma: el motor
       resuelve el módulo vivo y ve otros valores. Medido: `id()` distinto, la perilla en
       False en el huérfano y en True en el vivo, producción cogiendo TRF, y 1,8e-03 de
       diferencia. Por eso se pide el módulo por `sys.modules` en cada uso.
    """
    cfg_live = importlib.import_module("core.config")   # el VIVO, no el del import inicial
    prev = (cfg_live.USE_BOUNDED_SOLVER, cfg_live.USE_PROJECTED_SOLVER,
            cfg_live.USE_LSMR_LARGE)
    cfg_live.USE_BOUNDED_SOLVER = False   # no TRF: converge distinto y es 40x más lento
    cfg_live.USE_PROJECTED_SOLVER = True  # GPCG proyectado, igual que la referencia
    cfg_live.USE_LSMR_LARGE = False       # no LSMR: la referencia usa LSQR
    try:
        yield
    finally:
        (cfg_live.USE_BOUNDED_SOLVER, cfg_live.USE_PROJECTED_SOLVER,
         cfg_live.USE_LSMR_LARGE) = prev


def _production_contrast(x_c, y_c, z_c, sensors, g_obs, noise_floor):
    """Produccion, por la ruta LSQR+GPCG (la misma que usa la referencia)."""
    inv = GravimetryInversion(NX, NY, NZ, BLOCK, base_density=BASE_DENSITY)
    fwd = GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF)
    with _pinned_solver_path():
        rho, _s, _m, _n = inv.solve_inversion_lsqr(
            g_obs, None, y_c, lambda_mag=LAMBDA_MAG, alpha_spatial=ALPHA_SPATIAL,
            forward_model=fwd, sensor_coords=sensors, x_c=x_c, z_c=z_c,
            density_min=BASE_DENSITY, density_max=DENSITY_MAX,
            noise_floor=noise_floor, noise_pct=0.02,
            prune_observable_domain=True, regularization_norm="L2",
        )
    return np.nan_to_num(np.asarray(rho, dtype=np.float64), nan=BASE_DENSITY) - BASE_DENSITY


def test_effective_model_weight_is_column_sensitivity_not_depth_weighting():
    """El peso de modelo del solver de grilla regular es ‖col_j(W_d·G)‖.

    Este es EL invariante de la Fase 4. Si alguien vuelve a meter un `(z+z0)^(-beta/2)`
    en la cadena de pesos —o cambia el orden de `Ws`— las dos soluciones dejan de
    coincidir y este test lo dice con un numero, no con un comentario.
    """
    x_c, y_c, z_c, sensors, g_obs, nf = _case()
    prod = _production_contrast(x_c, y_c, z_c, sensors, g_obs, nf)
    with _pinned_solver_path():
        phys = _solve_physical_space(x_c, y_c, z_c, sensors, g_obs, nf)

    peak = max(float(np.max(np.abs(prod))), 1e-30)
    rel = float(np.max(np.abs(prod - phys))) / peak
    assert rel < 1e-6, (
        f"El funcional de regularizacion del solver dejo de ser el medido en la Fase 4: "
        f"maxima diferencia relativa {rel:.3e} (tolerancia 1e-6). El peso de modelo "
        f"efectivo ya no es ‖col_j(W_d·G)‖ — revisar la cadena Wd -> Ws en "
        f"solve_inversion_lsqr."
    )


def test_depth_beta_is_gone_from_the_regular_grid_solver():
    """`depth_beta` no puede volver a la firma del solver donde no hace nada.

    Criterio de aceptacion (c) de la Fase 4. Un parametro inerte no es neutro: aparecia
    en el log de cada corrida y en la documentacion como control de profundidad.
    """
    params = inspect.signature(GravimetryInversion.solve_inversion_lsqr).parameters
    assert "depth_beta" not in params, (
        "`depth_beta` volvio a la firma de solve_inversion_lsqr. La Fase 4 midio que "
        "ahi es inerte (Ws cancela Wz exactamente). Si se quiere un depth weighting "
        "REAL hay que meterlo como peso de modelo explicito en el bloque de smallness "
        "-- y entonces hay que volver a correr el barrido que decidio cerrarlo."
    )


@pytest.mark.parametrize("beta_a,beta_b", [(0.0, 2.0)])
def test_treemesh_solver_keeps_a_live_depth_weighting(beta_a, beta_b):
    """El solver Octree SI usa el peso de profundidad: no se limpia por analogia.

    `solve_inversion_treemesh` calcula `Ws` sobre el kernel SIN pesar y aplica `w_reg`
    solo al bloque de smallness (y al de suavidad), asi que ahi `depth_beta` cambia la
    solucion de verdad. Se dispara en produccion por tamano de survey
    (`should_auto_use_treemesh`), no por eleccion del usuario.
    """
    x_c, y_c, z_c, sensors, g_obs, nf = _case()
    mesh = TreeMesh.from_regular_grid(NX, NY, NZ, BLOCK, max_refinement_depth=0)
    out = []
    for beta in (beta_a, beta_b):
        dens, _p, _m = solve_inversion_treemesh(
            mesh=mesh, g_observed=g_obs, sensor_coords=sensors,
            forward_model=GravimetryForward(BLOCK, BLOCK, BLOCK, cutoff_radius=CUTOFF),
            lambda_mag=LAMBDA_MAG, alpha_spatial=ALPHA_SPATIAL, depth_beta=beta,
            base_density=BASE_DENSITY, density_min=BASE_DENSITY,
            density_max=DENSITY_MAX, noise_floor=nf, noise_pct=0.02,
        )
        out.append(np.asarray(dens, dtype=np.float64) - BASE_DENSITY)
    rel = float(np.linalg.norm(out[0] - out[1]) / max(np.linalg.norm(out[1]), 1e-30))
    assert rel > 1e-3, (
        f"`depth_beta` dejo de mover la solucion en solve_inversion_treemesh "
        f"(diferencia relativa {rel:.3e}). Ahi el peso SI es fisico: si se volvio "
        f"inerte, alguien reintrodujo la cancelacion que la Fase 4 quito del otro solver."
    )
