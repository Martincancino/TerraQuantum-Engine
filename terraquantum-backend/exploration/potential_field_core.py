# -*- coding: utf-8 -*-
"""Núcleo compartido de los dos motores de campo potencial (gravimetría · magnetometría).

FASE 7 de la auditoría 06 (§10), derivada de H-9 y H-33.

**Por qué existe este módulo.** La auditoría midió 228 ventanas de código duplicado
entre `exploration/gravimetry.py` y `exploration/magnetometry.py`, y observó que la
decisión arquitectónica correcta ya se había tomado — existía
`exploration/geophysics_weights.py` — pero se había abandonado a un 3% del camino.
No hay que diseñar nada nuevo: hay que terminar.

**Y por qué es más que anti-duplicación.** H-33 midió que el MISMO parámetro
`depth_beta` tiene TRES comportamientos según qué opciones estén activas:

  | Motor / ruta                          | ¿`depth_beta` actúa? | Por qué                        |
  |---------------------------------------|----------------------|--------------------------------|
  | Gravimetría (grilla regular)          | ❌ nunca             | el peso de modelo es `‖col‖`   |
  | Magnetometría RUTA A (sin padding…)   | ✅ sí                | la smallness NO lleva `W`      |
  | Magnetometría RUTA B (producción)     | ❌ no                | TODOS los bloques llevan `W`   |

Nadie elegía ese comportamiento: lo elegía la presencia del padding, y nada en la
salida de la corrida lo declaraba. Este módulo concentra la decisión en un solo
sitio —:func:`build_model_weights` — y la hace **declarable** —
:func:`declare_functional`—, que es exactamente lo que la Fase 7 pide.

**La regla, en una línea:** un peso de modelo `W` que multiplica *todos* los bloques
del sistema aumentado es un **cambio de variable puro** y no cambia la solución
física; sólo actúa si algún bloque —en la práctica, la smallness— queda SIN él.
Esa única regla reproduce las tres filas de la tabla de arriba.

**Contrato de byte-identidad.** Cada función de aquí reproduce la aritmética de sus
call-sites originales *en el mismo orden*, no una versión «equivalente». La red que
lo verifica es `scripts/validation/fase7_byte_identity.py` (31 casos, SHA-256 sobre
los bits de float64). Si se cambia el orden de una multiplicación, el hash cambia y
el arnés lo dice.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np
import scipy.sparse as sp

from exploration.geophysics_weights import sigma_parametric

__all__ = [
    "sigma_adaptive",
    "sigma_parametric",
    "resolve_sigma",
    "SIGMA_SENTINEL",
    "active_cells_from_topography",
    "observable_domain_mask",
    "map_intervals_to_cells",
    "ModelWeights",
    "build_model_weights",
    "depth_row_weights",
    "declare_functional",
    "estimate_cond_from_columns",
    "irls_focus_weights",
    "robust_amplitude",
    "resolve_reference_model",
    "MODEL_WEIGHT_SENSITIVITY",
    "MODEL_WEIGHT_DEPTH",
    "SMALLNESS_IDENTITY_IN_TILDE",
    "SMALLNESS_SCALED_BY_W",
]

#: Valor centinela histórico de (noise_floor, noise_pct) que significa «no me
#: declararon el ruido: calíbralo con la amplitud del dato» (sigma adaptativo).
SIGMA_SENTINEL = (0.02, 0.02)

MODEL_WEIGHT_SENSITIVITY = "sensitivity"
MODEL_WEIGHT_DEPTH = "depth_li_oldenburg"

SMALLNESS_IDENTITY_IN_TILDE = "identity_in_tilde"
SMALLNESS_SCALED_BY_W = "scaled_by_W"


# ══════════════════════════════════════════════════════════════════════════════
# 1. Pesos de datos (sigma)
# ══════════════════════════════════════════════════════════════════════════════

def sigma_adaptive(d_observed, detect_outliers: bool) -> tuple:
    """Sigma calibrado a la amplitud del dato (Li & Oldenburg / SimPEG), robusto.

        sigma_i = max(0.02·|d_i|, 0.01·rango)

    Versión robusta: detecta outliers por MAD (`|d−mediana| > 3·1.4826·MAD`), los
    downpesa 10× para que no dilaten el sigma global, y calcula el rango con
    percentiles p5–p95 en vez de min–max cuando los hay.

    CAVEAT: el downweighting 10× es heurístico. Para surveys muy anómalos (>10%
    outliers) el usuario debe inspeccionar el CSV o bajar el umbral.

    Referencia: Li & Oldenburg 1998; Hampel et al. 1986 (estadística robusta).

    `detect_outliers` es OBLIGATORIO y sin defecto **a propósito**: los dos motores
    traían defectos distintos (gravimetría `True`, magnetometría `False`) y unificar
    a uno de ellos habría cambiado en silencio el sigma del otro. La asimetría vive
    ahora en los dos wrappers finos que quedan en cada motor, donde es visible.

    Returns
    -------
    sigma      : np.ndarray
    is_outlier : np.ndarray[bool]
    """
    d = np.asarray(d_observed, dtype=np.float64)

    if detect_outliers:
        median = np.median(d)
        mad = np.median(np.abs(d - median))
        sigma_est = 1.4826 * mad
        outlier_threshold = 3.0 * sigma_est
        is_outlier = np.abs(d - median) > outlier_threshold

        if is_outlier.any():
            clean = d[~is_outlier]
            data_range = max(
                float(np.percentile(clean, 95) - np.percentile(clean, 5)),
                1e-30,
            )
        else:
            data_range = max(float(np.max(d) - np.min(d)), 1e-30)
    else:
        data_range = max(float(np.max(d) - np.min(d)), 1e-30)
        is_outlier = np.zeros(len(d), dtype=bool)

    sigma = np.maximum(0.02 * np.abs(d), 0.01 * data_range)

    if is_outlier.any():
        sigma[is_outlier] = 10.0 * sigma[is_outlier]

    return np.maximum(sigma, 1e-30), is_outlier


def resolve_sigma(d_observed, noise_floor, noise_pct, detect_outliers: bool = False):
    """El despacho centinela adaptativo/paramétrico, escrito una sola vez.

    Estaba copiado en ocho sitios entre los dos motores, siempre con la misma forma:
    si `(noise_floor, noise_pct)` siguen en el centinela `(0.02, 0.02)`, el ruido no
    fue declarado y se calibra con la amplitud del dato; si no, se usa el piso
    instrumental declarado. Vale la pena que esté escrito una vez porque **el
    centinela es una comparación de floats por igualdad**: repetirla ocho veces es
    ocho oportunidades de escribir `>=` o de cambiar el valor en un solo sitio.
    """
    if noise_floor == SIGMA_SENTINEL[0] and noise_pct == SIGMA_SENTINEL[1]:
        return sigma_adaptive(d_observed, detect_outliers=detect_outliers)[0]
    return sigma_parametric(d_observed, noise_floor, noise_pct)


# ══════════════════════════════════════════════════════════════════════════════
# 2. Geometría del dominio activo
# ══════════════════════════════════════════════════════════════════════════════

def active_cells_from_topography(y_c, dy: float, total_voxels: int,
                                 topography_elevations=None, *, contexto: str = ""):
    """Celdas bajo la topografía: `techo_del_voxel >= profundidad_del_terreno`.

    Devuelve `(topo_depth, active_cells, n_active)`. `topography_elevations=None`
    equivale a terreno plano a cota 0 — que es el fallback silencioso que H-27
    señaló; aquí no se cambia el comportamiento, sólo deja de estar escrito seis
    veces.
    """
    if topography_elevations is None:
        topo_depth = np.zeros(total_voxels, dtype=np.float64)
    else:
        topo_depth = np.asarray(topography_elevations, dtype=np.float64)
    voxel_top = np.asarray(y_c, dtype=np.float64) - (float(dy) / 2.0)
    active_cells = voxel_top >= topo_depth
    n_active = int(np.sum(active_cells))
    if n_active == 0:
        raise ValueError(
            f"{contexto}No hay celdas activas bajo la topografía dada."
            if contexto else "No hay celdas activas bajo la topografía dada."
        )
    return topo_depth, active_cells, n_active


def observable_domain_mask(G_active, *, rel_threshold: float = 1e-6):
    """R-05 — celdas con sensibilidad no nula a ALGÚN sensor.

    Las columnas nulas de `G` (celdas más allá del cutoff para todos los sensores)
    sólo añaden plateau de mínima norma y saturación espuria en el bound.
    """
    col_sens = np.asarray(G_active.power(2).sum(axis=0)).ravel()
    thr = rel_threshold * max(float(np.max(col_sens)), 1e-30)
    return col_sens > thr


def map_intervals_to_cells(
    intervals,
    x_c_arr, y_c, z_c_arr,
    *,
    total_voxels: int,
    tol_xz: float,
    n_cols: int,
    nombre: str,
    mensaje_shape: str,
):
    """Mapea intervalos verticales de sondaje (o de unidad litológica) a vóxeles.

    Es **geometría pura, sin física**: por eso los dos motores lo tenían idéntico
    salvo el significado de las columnas de valor (contraste de densidad en uno,
    susceptibilidad en el otro). Selecciona la columna de vóxeles dentro de `tol_xz`
    en X/Z, recorta al tramo `[y_from, y_to]` y, si el intervalo es más corto que
    `dy` y no toca ningún centro, cae al vóxel más cercano al punto medio — que es
    lo que evita que un tramo de sondaje corto se pierda en silencio.

    Devuelve `(mask_full, valores_full)` donde `valores_full` tiene `n_cols - 4`
    columnas (1 para sondajes, 2 para bounds litológicos) y `NaN`/0 fuera de la
    máscara según el caso del llamador (ver `relleno`).

    Yields
    ------
    (indices_seleccionados, valores_de_la_fila) por cada intervalo, para que el
    llamador decida qué escribe. Mantener la escritura fuera preserva la aritmética
    exacta de cada motor.
    """
    arr = np.asarray(intervals, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != n_cols:
        raise ValueError(mensaje_shape)

    y_arr = np.asarray(y_c, dtype=np.float64)
    for fila in arr:
        _bx, _bz, _yf, _yt = fila[0], fila[1], fila[2], fila[3]
        if _yt < _yf:
            _yf, _yt = _yt, _yf
        _col = (np.abs(x_c_arr - _bx) <= tol_xz) & (np.abs(z_c_arr - _bz) <= tol_xz)
        if not np.any(_col):
            continue
        _seg = _col & (y_arr >= _yf) & (y_arr <= _yt)
        if not np.any(_seg):
            # Intervalo más corto que dy → vóxel de la columna más cercano al midpoint.
            _ymid = 0.5 * (_yf + _yt)
            _cidx = np.where(_col)[0]
            _near = int(_cidx[int(np.argmin(np.abs(y_arr[_cidx] - _ymid)))])
            _seg = np.zeros(total_voxels, dtype=bool)
            _seg[_near] = True
        yield _seg, fila[4:]


# ══════════════════════════════════════════════════════════════════════════════
# 3. EL peso de modelo — la pieza central de la Fase 7
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ModelWeights:
    """El peso de modelo `W` del cambio de variable `m_físico = W · m̃`.

    Los dos motores resuelven en una variable escalada `m̃` y destransforman al
    final. Lo que **difiere** entre ellos es la identidad de `W`, y eso es
    exactamente lo que nadie declaraba:

      * gravimetría: `W = diag(1/‖col_j(W_d·G)‖)` — ponderación por SENSIBILIDAD;
      * magnetometría: `W = diag((z+z₀)^{+β/2}) / media` — Li & Oldenburg.

    `diag` es el vector de la diagonal; el resto son vistas sobre él.
    """

    kind: Literal["sensitivity", "depth_li_oldenburg"]
    diag: np.ndarray
    depth_beta: Optional[float] = None
    z0: Optional[float] = None

    @property
    def W(self):
        """`sp.diags(diag)` — el operador `m = W·m̃`."""
        return sp.diags(self.diag)

    def scale(self, B):
        """`B · W`: lleva un bloque escrito en espacio FÍSICO al espacio `m̃`."""
        return B @ self.W

    def to_physical(self, m_tilde):
        """`m = W · m̃`."""
        return self.diag * np.asarray(m_tilde, dtype=np.float64)

    def to_tilde(self, m_phys, *, piso: float = 1e-12):
        """`m̃ = m / diag(W)`, con el mismo blindaje del divisor que los call-sites."""
        d = np.asarray(self.diag, dtype=np.float64)
        d_safe = np.where(np.abs(d) < piso, piso, d)
        return np.asarray(m_phys, dtype=np.float64) / d_safe

    def effective_depth_exponent(self, depths, z0: Optional[float] = None) -> dict:
        """Mide a qué Li & Oldenburg equivale ESTE peso, ajustando una ley de potencia.

        La Fase 4 midió que la ponderación por sensibilidad de gravimetría —que no
        se parece a un depth weighting— resulta ser en la práctica una ley de
        potencia limpia equivalente a **β ≈ 2,63**. Ese número se midió una vez, a
        mano, sobre una malla concreta. Aquí la corrida lo mide sobre SU malla y lo
        publica: es la diferencia entre «se parece a Li & Oldenburg» y «se parece a
        Li & Oldenburg con β=2,63 y 5,3 % de desviación en esta malla».

        El peso de PENALIZACIÓN en espacio físico es `u_j = 1/diag_j`, y Li &
        Oldenburg lo escribe `u_j ∝ (z_j+z₀)^{−β/2}`, de donde
        `β = −2 · pendiente(log u vs log(z+z₀))`.
        """
        d = np.asarray(depths, dtype=np.float64)
        z0_eff = float(z0 if z0 is not None else (self.z0 if self.z0 is not None else 0.0))
        x = np.log(np.maximum(d + z0_eff, 1e-30))
        u = 1.0 / np.maximum(np.abs(np.asarray(self.diag, dtype=np.float64)), 1e-300)
        y = np.log(np.maximum(u, 1e-300))
        if x.size < 2 or float(np.ptp(x)) <= 0.0:
            return {"beta_equivalente": None, "desviacion_max_pct": None}
        pend, corte = np.polyfit(x, y, 1)
        pred = pend * x + corte
        # Desviación relativa máxima en el espacio del peso, no del logaritmo:
        # es la que le importa a quien lee «¿es una ley de potencia limpia?».
        dev = float(np.max(np.abs(np.expm1(y - pred)))) * 100.0
        return {
            "beta_equivalente": float(-2.0 * pend),
            "desviacion_max_pct": dev,
        }


def build_model_weights(
    kind: str,
    *,
    G_w=None,
    depths=None,
    z0: Optional[float] = None,
    depth_beta: Optional[float] = None,
    piso_col: float = 1e-12,
) -> ModelWeights:
    """Construye EL peso de modelo. Es el único sitio donde se elige cuál.

    Parameters
    ----------
    kind
        ``"sensitivity"`` — `diag = 1/max(‖col_j(G_w)‖, piso)`. Requiere `G_w`
        (el kernel YA pesado por `W_d`; pesarlo después cambiaría el resultado).
        ``"depth_li_oldenburg"`` — `diag = (depth+z₀)^{+β/2}`, normalizado a media 1.
        Requiere `depths`, `z0` y `depth_beta`.

    Notas de byte-identidad
    -----------------------
    El orden de las operaciones reproduce el de los call-sites originales:
    `sqrt(sum(G_w²))` → `maximum(·, 1e-12)` → `1/·` para sensibilidad; y
    `clip(depth,1,None)` → `(·+z₀)**(0.5·β)` → `/mean` para profundidad. Cambiar
    el orden cambia el último bit, y el arnés de la Fase 7 lo detecta.
    """
    if kind == MODEL_WEIGHT_SENSITIVITY:
        if G_w is None:
            raise ValueError("build_model_weights('sensitivity') requiere G_w.")
        col_norms = np.sqrt(G_w.power(2).sum(axis=0)).A1
        col_norms = np.maximum(col_norms, piso_col)
        return ModelWeights(kind=MODEL_WEIGHT_SENSITIVITY, diag=1.0 / col_norms,
                            depth_beta=None, z0=None)

    if kind == MODEL_WEIGHT_DEPTH:
        if depths is None or z0 is None or depth_beta is None:
            raise ValueError(
                "build_model_weights('depth_li_oldenburg') requiere depths, z0 y depth_beta."
            )
        true_depth = np.clip(np.asarray(depths, dtype=np.float64), a_min=1.0, a_max=None)
        wz = (true_depth + float(z0)) ** (0.5 * float(depth_beta))
        wz = wz / np.mean(wz)
        return ModelWeights(kind=MODEL_WEIGHT_DEPTH, diag=wz,
                            depth_beta=float(depth_beta), z0=float(z0))

    raise ValueError(
        f"kind de peso de modelo desconocido: {kind!r}. "
        f"Use {MODEL_WEIGHT_SENSITIVITY!r} o {MODEL_WEIGHT_DEPTH!r}."
    )


def depth_row_weights(depths, z0: float, beta: float = 2.0):
    """`w_reg = 1/(z+z₀)^β` normalizado a media 1 — peso de FILA, no cambio de variable.

    Ojo con no confundirlo con :func:`build_model_weights`: éste multiplica las
    FILAS de un bloque de regularización (relaja la penalización en profundidad) y
    **no** se deshace al destransformar, porque no es un cambio de variable. Lo usan
    la σ posterior, los dos live-update y los dos selectores de λ.

    Que existan los dos —peso de columna y peso de fila— con la misma etiqueta
    mental de «depth weighting» es la raíz de H-33: son cosas distintas y el código
    las llamaba igual.
    """
    true_depth = np.clip(np.asarray(depths, dtype=np.float64), a_min=1.0, a_max=None)
    w_depth = (true_depth + float(z0)) ** float(beta)
    w_reg = 1.0 / w_depth
    return w_reg / np.mean(w_reg)


#: Códigos `istop` de `scipy.sparse.linalg.lsqr` que NO son convergencia:
#: 3 = se superó `conlim` (cond(A) demasiado alto); 7 = se agotó `iter_lim`.
LSQR_ISTOP_NO_CONVERGE = (3, 7)


def solver_converged(istop: Optional[int]) -> Optional[bool]:
    """¿El LSQR terminó por criterio de solución, o se quedó sin cuerda?

    Importa más de lo que parece: cuando el peso de modelo es un cambio de variable
    puro, es también un **precondicionador por la derecha**, y un precondicionador
    sólo es inocuo si el solver LLEGA. Si trunca, cambia el punto en el que se
    detiene — y entonces un parámetro «inerte» mueve el resultado igualmente.
    """
    if istop is None:
        return None
    return int(istop) not in LSQR_ISTOP_NO_CONVERGE


def declare_functional(
    weights: ModelWeights,
    *,
    smallness: str,
    depths=None,
    depth_beta_solicitado: Optional[float] = None,
    smoothness_row_weight: bool = False,
    lsqr_istop: Optional[int] = None,
    lsqr_iters: Optional[int] = None,
) -> dict:
    """Qué funcional de regularización usó ESTA corrida. Para publicar en la salida.

    La regla algebraica, que es la mitad de la física de esta función:

      * si **todos** los bloques del sistema aumentado llevan `W`
        (`smallness == "scaled_by_W"`), entonces `W` es un cambio de variable puro:
        la solución EXACTA en espacio físico no depende de `W` y el peso no actúa;
      * si la smallness es identidad en `m̃` (`"identity_in_tilde"`), el peso `W`
        entra en el funcional y penaliza `‖W⁻¹·m‖²`.

    Con eso salen solas las tres filas que H-33 midió, sin depender de que alguien
    se acuerde de mirar si el padding está encendido.

    **La otra mitad, y por qué la declaración no puede quedarse en el álgebra.**
    §9G.1 de la auditoría dejó escrito este caveat sin cuantificar:

        «en la ruta B, `Wz_inv` sigue siendo un precondicionador por la derecha
         legítimo — cambia la trayectoria de LSQR. […] si trunca por iteraciones,
         habría un efecto residual de regularización implícita por parada
         temprana. No lo cuantifiqué.»

    **[MEDIDO, Fase 7]** Sobre la malla de prueba del motor magnético, en ruta B:
    la solución EXACTA (`lstsq` denso) es invariante en `β` a **1e-11** —H-33 tiene
    razón sobre el funcional—, pero el solve iterativo del motor termina con
    `istop=7` (límite de iteraciones) en **500/500** para todo `β`, y queda a
    **54 %–269 %** de la exacta. Mover `β` de 0,5 a 3,0 cambia entonces la
    susceptibilidad recuperada un **66 %–86 %**. No es un residuo de redondeo: es
    casi toda la señal, y viene de dónde se detiene el solver, no del funcional.

    Por eso, cuando el peso es un cambio de variable puro **y el solver no
    convergió**, esta función declara `depth_beta_has_effect=True` con
    `effect_mechanism="early_stopping"`. Declarar «inerte» ahí sería exacto sobre el
    álgebra y falso sobre la corrida — y la corrida es lo que el usuario ve.
    """
    if smallness not in (SMALLNESS_IDENTITY_IN_TILDE, SMALLNESS_SCALED_BY_W):
        raise ValueError(
            f"smallness debe ser {SMALLNESS_IDENTITY_IN_TILDE!r} o "
            f"{SMALLNESS_SCALED_BY_W!r}, no {smallness!r}."
        )

    cambio_de_variable_puro = (smallness == SMALLNESS_SCALED_BY_W)
    peso_actua = not cambio_de_variable_puro
    es_profundidad = (weights.kind == MODEL_WEIGHT_DEPTH)
    beta = (depth_beta_solicitado if depth_beta_solicitado is not None
            else weights.depth_beta)

    convergio = solver_converged(lsqr_istop)
    # Un cambio de variable puro sólo es inocuo si el solver LLEGA. Si truncó, el
    # peso sigue moviendo el resultado por regularización implícita de parada
    # temprana — medido en 66 %–86 % en la ruta B magnética.
    por_parada_temprana = bool(cambio_de_variable_puro and convergio is False)
    mecanismo = ("functional" if peso_actua
                 else ("early_stopping" if por_parada_temprana else "none"))

    if es_profundidad and peso_actua:
        explicacion = (
            f"Peso de profundidad Li & Oldenburg ACTIVO (beta={beta}): la smallness "
            f"es identidad en m~, asi que (z+z0)^(beta/2) entra en el funcional y las "
            f"celdas profundas se penalizan menos."
        )
    elif es_profundidad and not peso_actua and not por_parada_temprana:
        explicacion = (
            f"Peso de profundidad INERTE (beta={beta} declarado): todos los bloques "
            f"—datos, suavidad y smallness— llevan el mismo W, de modo que W es un "
            f"cambio de variable puro y la solucion fisica no depende de beta. "
            f"Es la RUTA B de H-33, la que produccion usa cuando hay padding, "
            f"anclajes o IRLS compacto. El solver convergio, asi que la inercia del "
            f"funcional es tambien la inercia del resultado."
        )
    elif es_profundidad and not peso_actua:
        explicacion = (
            f"Peso de profundidad inerte EN EL FUNCIONAL pero NO en este resultado "
            f"(beta={beta}). Todos los bloques llevan el mismo W (RUTA B de H-33), "
            f"asi que la solucion EXACTA no depende de beta; pero el solver termino "
            f"sin converger (lsqr istop={lsqr_istop}, {lsqr_iters} iteraciones), y W "
            f"es ademas un precondicionador por la derecha: cambia DONDE se detiene. "
            f"Medido en la Fase 7: hasta 86% de diferencia en la susceptibilidad al "
            f"mover beta, con la solucion exacta invariante a 1e-11. Este resultado "
            f"depende de beta por parada temprana, no por fisica."
        )
    elif peso_actua:
        explicacion = (
            "Ponderacion por SENSIBILIDAD activa: la smallness penaliza "
            "||col_j(Wd.G)|| * m_j. No es un depth weighting ajustable — lo fija el "
            "kernel, no un parametro (hallazgo H-1, medido en la Fase 4)."
        )
    else:
        explicacion = (
            "Ponderacion por sensibilidad neutralizada: todos los bloques llevan W, "
            "luego es un cambio de variable puro y no entra en el funcional."
        )

    salida = {
        "model_weight_kind": weights.kind,
        "smallness_block": smallness,
        "model_weight_is_pure_change_of_variable": bool(cambio_de_variable_puro),
        "model_weight_enters_functional": bool(peso_actua),
        "depth_weighting_active": bool(es_profundidad and peso_actua),
        "depth_beta_declared": (float(beta) if beta is not None else None),
        # Lo que le importa a quien lee el reporte: ¿este número dependía de beta?
        # Incluye el camino por parada temprana, que el álgebra sola no ve.
        "depth_beta_has_effect": bool(es_profundidad
                                      and (peso_actua or por_parada_temprana)),
        "effect_mechanism": mecanismo,
        "solver_converged": convergio,
        "lsqr_istop": (int(lsqr_istop) if lsqr_istop is not None else None),
        "lsqr_iters": (int(lsqr_iters) if lsqr_iters is not None else None),
        "smoothness_row_weight_applied": bool(smoothness_row_weight),
        "explanation_es": explicacion,
    }

    if depths is not None:
        try:
            salida.update({
                f"effective_{k}": v
                for k, v in weights.effective_depth_exponent(depths).items()
            })
        except Exception:      # una declaración nunca debe tumbar una inversión
            salida["effective_beta_equivalente"] = None
            salida["effective_desviacion_max_pct"] = None
    return salida


# ══════════════════════════════════════════════════════════════════════════════
# 4. Diagnóstico numérico y bucle IRLS
# ══════════════════════════════════════════════════════════════════════════════

def estimate_cond_from_columns(A) -> Optional[float]:
    """cond(A) estimado por ratio máx/mín de normas-columna al cuadrado.

    `O(nnz)`, sin SVD. Es el estimador que ambos motores usan para decidir si hay
    que reescalar los kappas (FASE 16 / FASE 20B Tarea 5). Devuelve `None` cuando
    todas las columnas son nulas — que es «no se puede estimar», no «está sano».
    """
    col_sq = np.array(A.power(2).sum(axis=0)).ravel()
    nz = col_sq > 0.0
    if not nz.any():
        return None
    mx = float(np.max(col_sq))
    mn = float(np.min(col_sq[nz]))
    if mn <= 0.0:
        return None
    return float(np.sqrt(mx / mn))


def irls_focus_weights(contraste, free_mask, eps: float,
                       *, lo: float = 0.05, hi: float = 20.0):
    """Reponderación minimum-support (Last & Kubik 1983; Portniaguine & Zhdanov 1999).

    `f_i = 1/√(c_i² + ε²)`, normalizada a media 1 **sobre las celdas libres** y
    recortada a `[lo, hi]`: concentra la penalización donde el contraste es ~0
    (vacía el fondo) y la relaja donde hay cuerpo. La normalización a media 1
    conserva la magnitud global de la regularización, así que redistribuye el foco
    sin degradar el misfit.
    """
    c = np.asarray(contraste, dtype=np.float64)
    raw = 1.0 / np.sqrt(c ** 2 + eps ** 2)
    den = float(np.mean(raw[free_mask])) if np.any(free_mask) else float(np.mean(raw))
    den = den if den > 1e-12 else 1.0
    return np.clip(raw / den, lo, hi)


def initial_irls_eps(contraste_libre, eps_floor: float) -> float:
    """ε inicial del IRLS: mitad del percentil 90 del contraste libre, con piso."""
    c = np.asarray(contraste_libre, dtype=np.float64)
    if c.size == 0:
        return eps_floor
    return max(eps_floor, 0.5 * float(np.percentile(c, 90)))


def build_smoothing_operator(L_active, weights: ModelWeights, smooth_strength,
                             n_active: int, cg_maxiter: int):
    """Operador `(I + γ·L̃ᵀL̃)⁻¹` matrix-free, para suavizar las direcciones del shuttle.

    `L̃ = L_active · W`. Se resuelve por CG con precondicionador de Jacobi. Devuelve
    `None` si `smooth_strength` es 0 o None — que es «sin suavizado», no un error.
    """
    from scipy.sparse.linalg import LinearOperator as _LO
    from scipy.sparse.linalg import cg as _cg

    if not smooth_strength or smooth_strength <= 0:
        return None
    L_scaled = weights.scale(L_active).tocsr()
    LtL = (L_scaled.T @ L_scaled).tocsr()
    S = (sp.identity(n_active, format="csr") + float(smooth_strength) * LtL).tocsr()
    diag_S = np.maximum(S.diagonal(), 1e-30)
    M_s = _LO((n_active, n_active), matvec=lambda v: v / diag_S)

    def _smooth(v):
        x, _ = _cg(S, v, rtol=1e-6, atol=0.0, maxiter=cg_maxiter, M=M_s)
        return x

    return _LO((n_active, n_active), matvec=_smooth)


def assemble_shuttle_ensemble(m0_active, directions, weights: ModelWeights, amp: float,
                              *, total_voxels: int, active_cells, lo=None, hi=None):
    """Construye el abanico de modelos alternativos del null-space shuttle.

    Cada dirección vive en espacio escalado `m̃`; se lleva a físico con `W`, se
    normaliza a la amplitud robusta `amp` y se suma al modelo base. El recorte al
    box petrofísico se aplica al miembro, no a la dirección — así el abanico mide
    no-unicidad DENTRO de lo físicamente admisible.

    Devuelve `(ensemble, ensemble_std, ensemble_mean)` con `NaN` en celdas de aire.
    """
    n = int(len(directions))
    ensemble = np.full((n, total_voxels), np.nan, dtype=np.float64)
    for k in range(n):
        d_phys = weights.diag * directions[k]
        peak = np.max(np.abs(d_phys))
        if peak > 1e-300:
            d_phys = d_phys * (amp / peak)
        member = m0_active + d_phys
        if lo is not None:
            member = np.maximum(member, float(lo))
        if hi is not None:
            member = np.minimum(member, float(hi))
        ensemble[k, active_cells] = member

    ens_active = ensemble[:, active_cells]
    ensemble_std = np.full(total_voxels, np.nan, dtype=np.float64)
    ensemble_mean = np.full(total_voxels, np.nan, dtype=np.float64)
    ensemble_std[active_cells] = np.std(ens_active, axis=0)
    ensemble_mean[active_cells] = np.mean(ens_active, axis=0)
    return ensemble, ensemble_std, ensemble_mean


def validate_live_update_args(m0, *, total_voxels: int, forward_model, sensor_coords,
                              x_c, z_c, lambda_mag, nombre: str,
                              new_sensor_coords=None, new_obs=None,
                              exigir_region: bool = False, region_mask=None,
                              region_center=None, region_radius=None):
    """Validación de entrada compartida por los cuatro métodos de update/UQ.

    Devuelve `k` (nº de observaciones nuevas) cuando se pasan datos nuevos, o `None`.
    Falla temprano y con el nombre del método: un `m0` de longitud equivocada, si no
    se detecta aquí, revienta 200 líneas más abajo en un `matmul` cuyo mensaje no
    dice nada de lo que el usuario hizo mal.
    """
    if forward_model is None or sensor_coords is None or x_c is None or z_c is None:
        raise ValueError(f"{nombre} requiere forward_model, sensor_coords, x_c, z_c.")
    m0 = np.asarray(m0, dtype=np.float64)
    if m0.shape[0] != total_voxels:
        raise ValueError(
            f"m0 debe tener total_voxels={total_voxels} elementos, tiene {m0.shape[0]}."
        )
    if lambda_mag is not None and lambda_mag <= 0:
        raise ValueError("lambda_mag debe ser > 0 (garantiza A SPD).")
    if exigir_region and region_mask is None and (region_center is None
                                                  or region_radius is None):
        raise ValueError(
            "Define la sub-región: 'region_mask' (bool) o 'region_center'+'region_radius'."
        )
    if new_sensor_coords is None or new_obs is None:
        return None
    k = int(np.atleast_2d(np.asarray(new_sensor_coords, dtype=np.float64)).shape[0])
    n_obs = int(np.atleast_1d(np.asarray(new_obs, dtype=np.float64)).ravel().shape[0])
    if n_obs != k:
        raise ValueError(
            f"el dato nuevo debe tener {k} elementos (uno por sensor nuevo), tiene {n_obs}."
        )
    return k


def combine_existing_and_new_data(sensor_coords, obs, new_sensor_coords, new_obs):
    """Concatena survey existente + observaciones nuevas para el re-solve local.

    Devuelve `(sensores, dato)`. Sin dato nuevo devuelve el existente tal cual, de
    modo que el sub-octree sirve también para «re-resolver esta zona con lo que ya
    tengo», que es el caso de uso de afinar un objetivo antes de perforar.
    """
    sensors = np.asarray(sensor_coords, dtype=np.float64)
    data = obs
    if new_sensor_coords is None or new_obs is None:
        return sensors, data
    ns = np.atleast_2d(np.asarray(new_sensor_coords, dtype=np.float64))
    no = np.atleast_1d(np.asarray(new_obs, dtype=np.float64)).ravel()
    if no.shape[0] != ns.shape[0]:
        raise ValueError("el dato nuevo debe tener un valor por sensor nuevo.")
    return np.vstack([sensors, ns]), np.concatenate([obs, no])


def split_region_response(G_all, S_local, m0_active, data):
    """Separa la respuesta del FONDO congelado de la que la sub-región debe explicar.

    `d_res = data − G[:, fuera_de_S] · m0[fuera_de_S]`: el resto del modelo se toma
    como dado y sólo `S` se re-resuelve. Devuelve `(G_S, d_res)`.
    """
    G_S = G_all[:, S_local].tocsr()
    bg_local = ~S_local
    d_bg = G_all[:, bg_local] @ np.asarray(m0_active, dtype=np.float64)[bg_local]
    return G_S, data - d_bg


def woodbury_update_from_new_rows(
    A, m0_active, weights: ModelWeights, G_new, new_obs, *,
    noise_floor, noise_pct, cg_maxiter, cg_rtol, lo=None, hi=None,
    woodbury_fn,
):
    """Incorpora `k` observaciones nuevas a un modelo ya resuelto, sin re-invertir.

    Las filas nuevas se escalan con el MISMO `W` que produjo `A` —ése es todo el
    truco: `A` queda congelada y sólo se resuelven `k` sistemas CG contra ella—, se
    aplica el update de rango `k` de Woodbury y se vuelve a espacio físico.

    Devuelve `(m1_active, info, misfit_antes, misfit_despues)`. Los dos misfits se
    miden con el kernel FÍSICO sin escalar, que es la única forma de que el número
    signifique «cuánto mejoró el ajuste al dato nuevo» y no «cuánto se movió `m̃`».
    """
    obs = np.asarray(new_obs, dtype=np.float64)
    m_tilde0 = np.asarray(m0_active, dtype=np.float64) / weights.diag
    sigma_new = sigma_parametric(obs, noise_floor, noise_pct)
    U_scaled = weights.scale(sp.diags(1.0 / sigma_new) @ G_new).toarray()
    d_tilde_new = obs / sigma_new

    G_new_phys = G_new.tocsr()
    misfit_before = relative_misfit(G_new_phys @ m0_active, obs)

    m_tilde1, info = woodbury_fn(A, m_tilde0, U_scaled, d_tilde_new,
                                 cg_maxiter=cg_maxiter, cg_rtol=cg_rtol)

    m1_active = clip_to_bounds(weights.to_physical(m_tilde1), lo, hi)
    misfit_after = relative_misfit(G_new_phys @ m1_active, obs)
    return m1_active, info, misfit_before, misfit_after


def inject_extra_reg_blocks(G_aug, d_aug, extra_reg_blocks, extra_reg_rhs,
                            weights: ModelWeights, *, hint_mask: str):
    """Apila los bloques de regularización externa (cross-gradient) del joint.

    Los bloques llegan en ESPACIO FÍSICO del modelo; el solver trabaja en `m̃` con
    `m = W·m̃`, así que cada bloque `B` entra como `B·W` — igual que el Laplaciano.
    El RHS se apila tal cual porque vive en el espacio de residual del bloque.

    La comprobación de columnas no es cosmética: con poda observable activa el
    llamador debe recortar `B[:, obs_mask]`, y si no lo hace el `vstack` produce una
    matriz con dimensiones que sólo revientan mucho más abajo.
    """
    if not extra_reg_blocks:
        return G_aug, d_aug
    n_cols = int(weights.diag.shape[0])
    mats = [G_aug]
    rhs = [d_aug]
    for i, blk in enumerate(extra_reg_blocks):
        blk = sp.csr_matrix(blk)
        if blk.shape[1] != n_cols:
            raise ValueError(
                f"extra_reg_blocks[{i}] tiene {blk.shape[1]} columnas; se esperaban "
                f"{n_cols} (modelo activo post-poda). Recorta columnas al dominio "
                f"observable: B[:, {hint_mask}]."
            )
        mats.append(weights.scale(blk))
        if extra_reg_rhs is not None and i < len(extra_reg_rhs):
            rhs.append(np.asarray(extra_reg_rhs[i], dtype=np.float64).ravel())
        else:
            rhs.append(np.zeros(blk.shape[0], dtype=np.float64))
    return sp.vstack(mats).tocsr(), np.concatenate(rhs)


def solve_local_region_cg(A_S, b_S, weights_S: ModelWeights, n_S: int,
                          *, cg_rtol, cg_maxiter, lo=None, hi=None):
    """Resuelve el sistema SPD pequeño de la sub-región por CG con Jacobi.

    Devuelve el modelo de la región en unidades FÍSICAS, ya recortado al box.
    """
    from scipy.sparse.linalg import LinearOperator as _LO
    from scipy.sparse.linalg import cg as _cg

    diagA = np.maximum(A_S.diagonal(), 1e-30)
    M = _LO((n_S, n_S), matvec=lambda v: v / diagA)
    m_tilde1_S, _info = _cg(A_S, b_S, rtol=cg_rtol, atol=0.0, maxiter=cg_maxiter, M=M)
    return clip_to_bounds(weights_S.to_physical(m_tilde1_S), lo, hi)


def normal_equations(G_scaled, L_scaled, lambda_spatial: float, lambda_diag: float,
                     n: int):
    """`A = G̃ᵀG̃ + λ_sp²·L̃ᵀL̃ + λ²·I` — la matriz de información, SPD por el último término.

    La usan la σ posterior y los dos live-update, en los dos motores, con la misma
    forma. Es SPD **gracias** a `λ² I`: por eso los llamadores exigen `λ > 0` en vez
    de dejar que el CG falle a mitad de camino.
    """
    return (
        (G_scaled.T @ G_scaled)
        + (float(lambda_spatial) ** 2) * (L_scaled.T @ L_scaled)
        + (float(lambda_diag) ** 2) * sp.identity(n, format="csr", dtype=np.float64)
    ).tocsr()


def clip_to_bounds(m, lo=None, hi=None):
    """Recorte al box petrofísico, con `None` = «sin bound por ese lado»."""
    out = np.asarray(m, dtype=np.float64)
    if lo is not None:
        out = np.maximum(out, float(lo))
    if hi is not None:
        out = np.minimum(out, float(hi))
    return out


def relative_misfit(pred, obs, *, weight=None) -> float:
    """`‖W(pred−obs)‖ / ‖W·obs‖`, con piso en el denominador para dato degenerado."""
    p = np.asarray(pred, dtype=np.float64)
    o = np.asarray(obs, dtype=np.float64)
    if weight is None:
        den = max(float(np.linalg.norm(o)), 1e-30)
        return float(np.linalg.norm(p - o)) / den
    den = max(float(np.linalg.norm(weight @ o)), 1e-30)
    return float(np.linalg.norm(weight @ (p - o))) / den


def select_subregion(S_mask_full, region_center, region_radius, *,
                     x_a, y_a, z_a, active_cells, total_voxels: int, contexto: str = ""):
    """Sub-región S del live-update local, en índices LOCALES dentro de las activas.

    Admite máscara explícita (`total_voxels`) o esfera (`centro`, `radio`). Que la
    región quede vacía es un error del llamador, no un caso a ignorar: re-resolver
    cero celdas devolvería el modelo intacto fingiendo que hizo algo.
    """
    if S_mask_full is not None:
        mask = np.asarray(S_mask_full, dtype=bool).ravel()
        if mask.shape[0] != total_voxels:
            raise ValueError("region_mask debe tener total_voxels elementos.")
        S_local = (mask & active_cells)[active_cells]
    else:
        cx, cy, cz = (float(region_center[0]), float(region_center[1]),
                      float(region_center[2]))
        r2 = float(region_radius) ** 2
        S_local = ((x_a - cx) ** 2 + (y_a - cy) ** 2 + (z_a - cz) ** 2) <= r2
    n_S = int(np.sum(S_local))
    if n_S == 0:
        raise ValueError(f"{contexto}La sub-región no contiene celdas activas.")
    return S_local, n_S


def robust_amplitude(m0_active, shuttle_scale: float, piso: float = 1e-6) -> float:
    """Escala robusta del modelo (MAD→σ) con piso, para dimensionar los shuttles."""
    m = np.asarray(m0_active, dtype=np.float64)
    med = np.median(m)
    robust = 1.4826 * np.median(np.abs(m - med))
    return float(shuttle_scale) * max(robust, piso)


def resolve_reference_model(m_ref, *, total_voxels: int, n_active: int,
                            active_cells, obs_in_active=None, n_dead: int = 0):
    """Normaliza `m_ref` (grilla completa o activas) al dominio del solver.

    Acepta longitud `total_voxels` o `n_active`, recorta al dominio observable si
    hubo poda R-05, y **rechaza NaN/Inf** en vez de propagarlos: un modelo de
    referencia con NaN envenena el RHS de la suavidad en silencio.
    """
    if m_ref is None:
        return None
    arr = np.asarray(m_ref, dtype=np.float64)
    # Siempre una copia: los llamadores sobre-escriben las celdas ancladas sobre el
    # resultado, y devolver la vista del array del usuario mutaría su entrada.
    if arr.shape[0] == total_voxels:
        out = arr[active_cells].copy()
    elif arr.shape[0] == n_active:
        out = arr.copy()
    else:
        raise ValueError(
            f"m_ref debe tener longitud {total_voxels} (grilla completa) "
            f"o {n_active} (celdas activas), got {arr.shape[0]}."
        )
    if n_dead > 0 and obs_in_active is not None:
        out = out[obs_in_active]
    if not np.isfinite(out).all():
        raise ValueError("m_ref contiene NaN o Inf.")
    return out
