"""
FASE 7 (God-Tier) — Geología implícita: campo escalar implícito φ por HRBF.

Primer slice ADITIVO y DEPENDENCY-FREE del plan God-Tier Fase 7 ("RBF
Hermite-Birkhoff φ desde sondajes+orientaciones"). TerraQuantum hoy NO tiene
geología explícita: toda "estructura" es emergente de la inversión. Este módulo
construye, a partir de datos DUROS de geología (contactos de sondaje + medidas
estructurales de orientación), un campo escalar implícito continuo φ(x) cuyo
nivel cero es la superficie geológica y cuyo signo etiqueta unidades.

Método: HRBF (Hermite Radial Basis Function implicits, Macedo et al. 2011) con
kernel triarmónico ψ(r)=r³ (C², gradiente suave en r→0) + deriva polinómica de
grado 1. Interpola SIMULTÁNEAMENTE:
  • valores de φ (puntos dentro/fuera/sobre la superficie), y
  • gradientes de φ (normales = polos a la estratificación de datos de orientación).
Es la formulación de "potential field"/dual-cokriging que usan GemPy/LoopStructural,
pero implementada con numpy puro (sin esas dependencias, prohibidas por CLAUDE.md).

Convención de ejes (consistente con BoreholeInterval del backend):
  x, z = horizontales (planta);  y = profundidad, positiva hacia ABAJO.
Internamente el campo opera en (x, y, z) cartesianos genéricos; el extractor de
sondajes mapea (x_m, profundidad, z_m) → (x, y, z).

LÍMITES HONESTOS DE ESTE SLICE (lo que NO hace, a propósito):
  • NO se cablea al solver (geofísica que deforma φ = level-set inversion, Giraud
    GJI 2024) — eso toca el motor y es el siguiente sub-slice.
  • NO integra fallas (LoopStructural) ni cokriging bayesiano (GemPy) — deps.
  • Modelo categórico binario (unidad objetivo vs resto) para multi-unidad
    secuencial; estratigrafía completa multi-serie = trabajo futuro.
  • Un sondaje vertical muestrea una sola línea: con pocos sondajes la superficie
    3D queda poco restringida (límite de DATO, no del método).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ── Kernel triarmónico ψ(r) = r³ y sus derivadas ───────────────────────────
# Elegido (vs biarmónico r) porque su gradiente 3r(x−c) y su Hessiana son
# continuos en r=0, condición necesaria para imponer constraints de gradiente
# (HRBF). Referencia: Macedo, Gois & Velho (2011), "Hermite RBF Implicits".

def _kernel(r: np.ndarray) -> np.ndarray:
    """ψ(r) = r³."""
    return r ** 3


def _grad_kernel(diff: np.ndarray, r: np.ndarray) -> np.ndarray:
    """∇_x ψ(|x−c|) = 3 r (x−c).  diff = x−c (..,3); r = |diff| (..)."""
    return 3.0 * r[..., None] * diff


def _hess_kernel(diff: np.ndarray, r: np.ndarray) -> np.ndarray:
    """Hessiana H_x ψ = 3 [ r I + (x−c)(x−c)ᵀ / r ].  En r=0 → 0 (límite C²).

    diff: (..,3); r: (..). Devuelve (..,3,3).
    """
    eye = np.eye(3)
    # outer(diff, diff) / r, con r=0 ⇒ término 0 (diff=0 allí de todos modos).
    safe_r = np.where(r > 0.0, r, 1.0)
    outer = diff[..., :, None] * diff[..., None, :] / safe_r[..., None, None]
    outer = np.where((r > 0.0)[..., None, None], outer, 0.0)
    return 3.0 * (r[..., None, None] * eye + outer)


# ── Datos de orientación estructural ───────────────────────────────────────
@dataclass(frozen=True)
class OrientationDatum:
    """Medida estructural: posición + normal unitaria al plano (polo) en el
    marco (x, y=profundidad+abajo, z). El gradiente de φ se ancla a esta normal,
    fijando la escala y la polaridad del campo implícito.
    """
    x: float
    y: float
    z: float
    nx: float
    ny: float
    nz: float

    @classmethod
    def from_dip_azimuth(
        cls, x: float, y: float, z: float, dip_deg: float, azimuth_deg: float
    ) -> "OrientationDatum":
        """Convierte buzamiento (dip desde la horizontal) y dirección de
        buzamiento (azimut en el plano horizontal x–z, medido desde +x hacia +z)
        a la normal (polo) del plano, apuntando hacia ARRIBA (−y).

        El polo de un plano con buzamiento δ y dir. de buzamiento α:
          n = ( sin δ·cos α,  −cos δ,  sin δ·sin α )   (|n|=1, componente y<0 = arriba).
        """
        d = np.radians(dip_deg)
        a = np.radians(azimuth_deg)
        nx = np.sin(d) * np.cos(a)
        ny = -np.cos(d)
        nz = np.sin(d) * np.sin(a)
        return cls(x, y, z, float(nx), float(ny), float(nz))

    def position(self) -> np.ndarray:
        return np.array([self.x, self.y, self.z], dtype=float)

    def normal(self) -> np.ndarray:
        n = np.array([self.nx, self.ny, self.nz], dtype=float)
        norm = np.linalg.norm(n)
        if norm == 0.0:
            raise ValueError("OrientationDatum con normal nula.")
        return n / norm


# ── Interpolante HRBF ──────────────────────────────────────────────────────
class HermiteRBFImplicit:
    """Campo escalar implícito φ(x) interpolando valores y/o gradientes.

    φ(x) = Σ_i α_i ψ(x−P_i) − Σ_k B_kᵀ ∇ψ(x−Q_k) + (c₀ + c₁x + c₂y + c₃z)

    Se resuelve el sistema HRBF simétrico con deriva polinómica de grado 1 y las
    condiciones de ortogonalidad estándar. Las coordenadas se normalizan a una
    caja unitaria internamente para condicionar el kernel triarmónico.
    """

    def __init__(self, smoothing: float = 0.0):
        # smoothing>0 relaja la interpolación a aproximación (ridge en la diagonal).
        self.smoothing = float(smoothing)
        self._fitted = False
        self._center = np.zeros(3)
        self._scale = 1.0
        self._P = np.empty((0, 3))   # puntos de valor (normalizados)
        self._Q = np.empty((0, 3))   # puntos de gradiente (normalizados)
        self._alpha = np.empty(0)
        self._B = np.empty((0, 3))
        self._poly = np.zeros(4)

    def fit(
        self,
        value_points: Optional[np.ndarray] = None,
        values: Optional[np.ndarray] = None,
        gradient_points: Optional[np.ndarray] = None,
        gradients: Optional[np.ndarray] = None,
    ) -> "HermiteRBFImplicit":
        """Ajusta el campo. value_points (n,3)/values (n,) y/o gradient_points
        (m,3)/gradients (m,3). Al menos un punto de valor es requerido."""
        P = np.zeros((0, 3)) if value_points is None else np.asarray(value_points, float).reshape(-1, 3)
        v = np.zeros(0) if values is None else np.asarray(values, float).reshape(-1)
        Q = np.zeros((0, 3)) if gradient_points is None else np.asarray(gradient_points, float).reshape(-1, 3)
        Ng = np.zeros((0, 3)) if gradients is None else np.asarray(gradients, float).reshape(-1, 3)

        if P.shape[0] != v.shape[0]:
            raise ValueError("value_points y values con longitudes distintas.")
        if Q.shape[0] != Ng.shape[0]:
            raise ValueError("gradient_points y gradients con longitudes distintas.")
        if P.shape[0] == 0:
            raise ValueError("HRBF requiere al menos un punto de valor (φ conocido).")

        # Normalización a caja unitaria (condicionamiento del kernel r³).
        allpts = np.vstack([P, Q]) if Q.shape[0] else P
        self._center = allpts.mean(axis=0)
        span = float(np.max(allpts.max(axis=0) - allpts.min(axis=0)))
        self._scale = span if span > 0.0 else 1.0

        Pn = (P - self._center) / self._scale
        Qn = (Q - self._center) / self._scale
        # Gradiente en coords normalizadas: ∇_{x'}φ = scale · ∇_x φ.
        Ngn = Ng * self._scale

        n, m = Pn.shape[0], Qn.shape[0]
        dim = n + 3 * m + 4
        M = np.zeros((dim, dim))
        rhs = np.zeros(dim)

        # Índices de bloques.
        a0, a1 = 0, n                 # α
        b0, b1 = n, n + 3 * m         # B (aplanado)
        p0, p1 = n + 3 * m, dim       # poly

        # --- Bloque valor-valor Avv y valor-poly ---
        diff_PP = Pn[:, None, :] - Pn[None, :, :]      # (n,n,3)
        r_PP = np.linalg.norm(diff_PP, axis=2)
        M[a0:a1, a0:a1] = _kernel(r_PP)
        poly_P = np.column_stack([np.ones(n), Pn])     # (n,4) [1,x,y,z]
        M[a0:a1, p0:p1] = poly_P
        M[p0:p1, a0:a1] = poly_P.T
        rhs[a0:a1] = v

        if m > 0:
            # --- valor-gradiente Avg: φ(P_i) recibe −B_kᵀ∇ψ(P_i−Q_k) ---
            diff_PQ = Pn[:, None, :] - Qn[None, :, :]  # (n,m,3)
            r_PQ = np.linalg.norm(diff_PQ, axis=2)
            gradPQ = _grad_kernel(diff_PQ, r_PQ)       # (n,m,3)
            Avg = -gradPQ.reshape(n, 3 * m)
            M[a0:a1, b0:b1] = Avg
            M[b0:b1, a0:a1] = Avg.T

            # --- gradiente-gradiente Agg: −H_ψ(Q_k−Q_l) ---
            diff_QQ = Qn[:, None, :] - Qn[None, :, :]  # (m,m,3)
            r_QQ = np.linalg.norm(diff_QQ, axis=2)
            Hqq = _hess_kernel(diff_QQ, r_QQ)          # (m,m,3,3)
            Agg = -np.transpose(Hqq, (0, 2, 1, 3)).reshape(3 * m, 3 * m)
            M[b0:b1, b0:b1] = Agg

            # --- gradiente-poly Agp: ∇(c·[1,x,y,z]) = (c1,c2,c3) ---
            Agp = np.zeros((3 * m, 4))
            for k in range(m):
                Agp[3 * k + 0, 1] = 1.0
                Agp[3 * k + 1, 2] = 1.0
                Agp[3 * k + 2, 3] = 1.0
            M[b0:b1, p0:p1] = Agp
            M[p0:p1, b0:b1] = Agp.T

            rhs[b0:b1] = Ngn.reshape(-1)

        # --- Regularización (smoothing) en la diagonal de valor/gradiente ---
        if self.smoothing > 0.0:
            idx = np.arange(b1)
            M[idx, idx] += self.smoothing

        # Resolución robusta (lstsq tolera rangos deficientes / colinealidades).
        sol, *_ = np.linalg.lstsq(M, rhs, rcond=None)

        self._P, self._Q = Pn, Qn
        self._alpha = sol[a0:a1]
        self._B = sol[b0:b1].reshape(m, 3) if m > 0 else np.empty((0, 3))
        self._poly = sol[p0:p1]
        self._fitted = True
        logger.info(
            "HRBF ajustado: %d puntos de valor, %d de gradiente, span=%.3g.",
            n, m, self._scale,
        )
        return self

    def _require_fit(self) -> None:
        if not self._fitted:
            raise RuntimeError("HermiteRBFImplicit no ajustado: llame fit() primero.")

    def evaluate(self, X: np.ndarray, chunk: int = 20000) -> np.ndarray:
        """Evalúa φ en X (N,3). Devuelve (N,)."""
        self._require_fit()
        X = np.asarray(X, float).reshape(-1, 3)
        Xn = (X - self._center) / self._scale
        out = np.empty(Xn.shape[0])
        for s in range(0, Xn.shape[0], chunk):
            xb = Xn[s:s + chunk]
            diff_P = xb[:, None, :] - self._P[None, :, :]
            r_P = np.linalg.norm(diff_P, axis=2)
            phi = _kernel(r_P) @ self._alpha
            if self._Q.shape[0]:
                diff_Q = xb[:, None, :] - self._Q[None, :, :]
                r_Q = np.linalg.norm(diff_Q, axis=2)
                gradQ = _grad_kernel(diff_Q, r_Q)              # (b,m,3)
                phi -= np.einsum("bmd,md->b", gradQ, self._B)
            phi += self._poly[0] + xb @ self._poly[1:]
            out[s:s + chunk] = phi
        return out

    def evaluate_gradient(self, X: np.ndarray) -> np.ndarray:
        """Evalúa ∇φ en X (N,3) en coordenadas FÍSICAS. Devuelve (N,3)."""
        self._require_fit()
        X = np.asarray(X, float).reshape(-1, 3)
        Xn = (X - self._center) / self._scale
        diff_P = Xn[:, None, :] - self._P[None, :, :]
        r_P = np.linalg.norm(diff_P, axis=2)
        g = (_grad_kernel(diff_P, r_P) * self._alpha[None, :, None]).sum(axis=1)  # (N,3)
        if self._Q.shape[0]:
            diff_Q = Xn[:, None, :] - self._Q[None, :, :]
            r_Q = np.linalg.norm(diff_Q, axis=2)
            Hq = _hess_kernel(diff_Q, r_Q)                      # (N,m,3,3)
            g -= np.einsum("nmde,me->nd", Hq, self._B)
        g += self._poly[1:]
        # ∇_x φ = (1/scale) ∇_{x'} φ.
        return g / self._scale


# ── Modelo geológico implícito (orquestador sondajes → grilla) ─────────────
@dataclass
class ImplicitGeologicalModel:
    """Construye φ desde contactos de sondaje + orientaciones y lo evalúa en la
    grilla de inversión. φ ≥ 0 ⇒ unidad objetivo; φ < 0 ⇒ resto."""
    field: HermiteRBFImplicit
    target_lithologies: Tuple[str, ...] = ()
    n_value_points: int = 0
    n_contact_points: int = 0
    n_orientations: int = 0

    @classmethod
    def from_boreholes(
        cls,
        intervals: Sequence,
        target_lithologies: Sequence[str],
        orientations: Optional[Sequence[OrientationDatum]] = None,
        smoothing: float = 1e-6,
    ) -> "ImplicitGeologicalModel":
        """Deriva el campo implícito de una lista de BoreholeInterval (o equivalentes
        con x_m, z_m, y_from_m, y_to_m, lithology).

        Constraints generados:
          • off-surface: el centroide de cada tramo con φ=+1 si su litología está
            en target_lithologies, φ=−1 si no.
          • on-surface: en cada transición objetivo↔no-objetivo a lo largo del pozo,
            un punto φ=0 en la profundidad del contacto.
          • gradiente: cada OrientationDatum ancla ∇φ a su normal (polo).
        """
        targets = tuple(t.strip().lower() for t in target_lithologies)
        vp: List[List[float]] = []
        vv: List[float] = []
        contacts = 0

        # Agrupar por sondaje (x,z) y ordenar por profundidad para detectar contactos.
        by_hole: dict = {}
        for it in intervals:
            key = (round(float(it.x_m), 6), round(float(it.z_m), 6))
            by_hole.setdefault(key, []).append(it)

        for (xh, zh), segs in by_hole.items():
            segs = sorted(segs, key=lambda s: float(s.y_from_m))
            prev_in: Optional[bool] = None
            prev_top: Optional[float] = None
            for s in segs:
                yf, yt = float(s.y_from_m), float(s.y_to_m)
                ymid = 0.5 * (yf + yt)
                lith = (s.lithology or "").strip().lower()
                is_target = lith in targets if lith else False
                vp.append([xh, ymid, zh])
                vv.append(1.0 if is_target else -1.0)
                # Contacto = cambio de pertenencia entre tramos consecutivos.
                if prev_in is not None and prev_in != is_target and prev_top is not None:
                    y_contact = 0.5 * (prev_top + yf)
                    vp.append([xh, y_contact, zh])
                    vv.append(0.0)
                    contacts += 1
                prev_in, prev_top = is_target, yt

        if not vp:
            raise ValueError("Ningún intervalo de sondaje válido para construir φ.")

        gp = None
        gn = None
        n_or = 0
        if orientations:
            gp = np.array([o.position() for o in orientations], float)
            gn = np.array([o.normal() for o in orientations], float)
            n_or = len(orientations)

        field = HermiteRBFImplicit(smoothing=smoothing).fit(
            value_points=np.array(vp, float),
            values=np.array(vv, float),
            gradient_points=gp,
            gradients=gn,
        )
        return cls(
            field=field,
            target_lithologies=targets,
            n_value_points=len(vp),
            n_contact_points=contacts,
            n_orientations=n_or,
        )

    def evaluate_grid(
        self, origin: Sequence[float], spacing: Sequence[float], shape: Sequence[int]
    ) -> np.ndarray:
        """Evalúa φ en los centros de una grilla regular. origin/spacing/shape en
        (x, y, z). Devuelve array (nx, ny, nz)."""
        ox, oy, oz = (float(v) for v in origin)
        dx, dy, dz = (float(v) for v in spacing)
        nx, ny, nz = (int(v) for v in shape)
        xs = ox + (np.arange(nx) + 0.5) * dx
        ys = oy + (np.arange(ny) + 0.5) * dy
        zs = oz + (np.arange(nz) + 0.5) * dz
        gx, gy, gz = np.meshgrid(xs, ys, zs, indexing="ij")
        pts = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])
        return self.field.evaluate(pts).reshape(nx, ny, nz)

    def classify_grid(
        self, origin: Sequence[float], spacing: Sequence[float], shape: Sequence[int]
    ) -> np.ndarray:
        """Máscara booleana (nx,ny,nz): True donde φ ≥ 0 (unidad objetivo)."""
        return self.evaluate_grid(origin, spacing, shape) >= 0.0


# ════════════════════════════════════════════════════════════════════════════
# FASE 7.2 — Geología → geofísica: φ restringe unidades → prior petrofísico
# ════════════════════════════════════════════════════════════════════════════
# El campo implícito φ etiqueta espacialmente cada vóxel (φ≥0 = unidad objetivo).
# Esto se convierte en un PRIOR petrofísico por celda: media de referencia m_ref
# y desviación σ que el motor PGI/anclaje ya sabe consumir (mismo rol que el GMM,
# pero la PERTENENCIA viene de la geología explícita, no del valor invertido).
# Es el lado "φ restringe unidades→GMM" del bucle (Astic-Oldenburg / Giraud 2024).

@dataclass
class SpatialPetrophysicalPrior:
    """Prior por vóxel derivado del campo implícito. Arrays (nx,ny,nz)."""
    mean: np.ndarray         # propiedad de referencia por celda (t/m³ o SI)
    std: np.ndarray          # σ por celda (incertidumbre del prior)
    membership: np.ndarray   # pertenencia suave a la unidad objetivo ∈ [0,1]
    class_label: np.ndarray  # etiqueta dura: 1 objetivo, 0 resto
    origin: Tuple[float, float, float]
    spacing: Tuple[float, float, float]
    shape: Tuple[int, int, int]

    def reference_flat(self, order: str = "F") -> np.ndarray:
        """m_ref aplanado (para alimentar el solver). order F = convención UBC."""
        return self.mean.ravel(order=order)


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -60.0, 60.0)))


def build_spatial_prior_from_implicit(
    phi: np.ndarray,
    *,
    target_mean: float,
    host_mean: float,
    target_std: float,
    host_std: float,
    origin: Sequence[float] = (0.0, 0.0, 0.0),
    spacing: Sequence[float] = (1.0, 1.0, 1.0),
    softness: float = 0.0,
) -> SpatialPetrophysicalPrior:
    """Convierte un campo φ (nx,ny,nz) en un prior petrofísico por celda.

    membership = H(φ): escalón duro si softness=0, o sigmoide φ/softness si >0
    (transición suave en el contacto, evita un salto discontinuo en m_ref).
    mean = host + membership·(target − host);  std interpola igual.
    """
    phi = np.asarray(phi, float)
    if softness > 0.0:
        membership = _sigmoid(phi / softness)
    else:
        membership = (phi >= 0.0).astype(float)
    mean = host_mean + membership * (target_mean - host_mean)
    std = host_std + membership * (target_std - host_std)
    return SpatialPetrophysicalPrior(
        mean=mean,
        std=std,
        membership=membership,
        class_label=(phi >= 0.0).astype(int),
        origin=tuple(float(v) for v in origin),
        spacing=tuple(float(v) for v in spacing),
        shape=tuple(int(s) for s in phi.shape),
    )


# ════════════════════════════════════════════════════════════════════════════
# FASE 7.3 — Geofísica → geología: level-set que deforma φ con el modelo invertido
# ════════════════════════════════════════════════════════════════════════════
# Cierra el bucle (Giraud GJI 2024): el modelo físico recuperado (densidad/susc)
# EMPUJA la superficie geológica. Se evoluciona φ con la ecuación de level-set en
# dirección normal  ∂φ/∂t = F·|∇φ|,  con velocidad F derivada de la geofísica:
# donde la propiedad supera un umbral (hay cuerpo) F>0 y la región φ≥0 CRECE;
# donde no, F<0 y se contrae. Discretización Godunov upwind (Osher–Sethian),
# estable bajo CFL. NumPy puro; NO toca el solver (es un operador sobre grillas).

def speed_from_property(
    property_grid: np.ndarray, threshold: float, scale: Optional[float] = None
) -> np.ndarray:
    """Velocidad F ∈ (−1,1) suave: tanh((propiedad − umbral)/escala). F>0 = crecer."""
    p = np.asarray(property_grid, float)
    if scale is None:
        spread = float(np.std(p))
        scale = spread if spread > 0.0 else 1.0
    return np.tanh((p - threshold) / scale)


def _upwind_grad_norms(phi: np.ndarray, spacing: Sequence[float]) -> Tuple[np.ndarray, np.ndarray]:
    """Normas de gradiente Godunov ∇⁺ y ∇⁻ con BC Neumann (replicación de borde)."""
    gp2 = np.zeros_like(phi)
    gm2 = np.zeros_like(phi)
    for axis, dx in enumerate(spacing):
        pad = [(0, 0)] * phi.ndim
        pad[axis] = (1, 1)
        p = np.pad(phi, pad, mode="edge")
        n = phi.shape[axis]

        def _take(a, b):
            s = [slice(None)] * phi.ndim
            s[axis] = slice(a, b)
            return p[tuple(s)]

        d_fwd = (_take(2, n + 2) - _take(1, n + 1)) / dx  # D⁺
        d_bwd = (_take(1, n + 1) - _take(0, n)) / dx       # D⁻
        gp2 += np.maximum(d_bwd, 0.0) ** 2 + np.minimum(d_fwd, 0.0) ** 2
        gm2 += np.maximum(d_fwd, 0.0) ** 2 + np.minimum(d_bwd, 0.0) ** 2
    return np.sqrt(gp2), np.sqrt(gm2)


def level_set_step(phi: np.ndarray, F: np.ndarray, spacing: Sequence[float], dt: float) -> np.ndarray:
    """Un paso de  ∂φ/∂t = F·|∇φ|  (Godunov upwind)."""
    grad_plus, grad_minus = _upwind_grad_norms(phi, spacing)
    speed_grad = np.maximum(F, 0.0) * grad_plus + np.minimum(F, 0.0) * grad_minus
    return phi + dt * speed_grad


def evolve_level_set(
    phi: np.ndarray,
    F: np.ndarray,
    spacing: Sequence[float],
    iterations: int = 20,
    dt: Optional[float] = None,
    cfl: float = 0.4,
) -> np.ndarray:
    """Evoluciona φ varias iteraciones. dt se fija por CFL si no se da:
    dt = cfl·min(spacing)/max|F|. La geofísica (F) deforma la superficie φ."""
    phi = np.asarray(phi, float).copy()
    Fmax = float(np.max(np.abs(F)))
    if Fmax == 0.0:
        return phi
    if dt is None:
        dt = cfl * min(spacing) / Fmax
    for _ in range(int(iterations)):
        phi = level_set_step(phi, F, spacing, dt)
    return phi


def reinitialize_sdf(
    phi: np.ndarray, spacing: Sequence[float], iterations: int = 5, cfl: float = 0.4
) -> np.ndarray:
    """Reinicializa φ hacia distancia con signo (|∇φ|→1) preservando el nivel cero.
    Resuelve  φ_t = sign(φ₀)(1 − |∇φ|)  unas pocas iteraciones (Sussman et al.)."""
    phi = np.asarray(phi, float).copy()
    phi0 = phi.copy()
    eps = min(spacing)
    sgn = phi0 / np.sqrt(phi0 ** 2 + eps ** 2)  # signo suavizado
    dt = cfl * min(spacing)
    for _ in range(int(iterations)):
        grad_plus, grad_minus = _upwind_grad_norms(phi, spacing)
        # upwind respecto al signo de la fuente
        g = np.where(sgn >= 0.0, grad_plus, grad_minus)
        phi = phi + dt * sgn * (1.0 - g)
    return phi
