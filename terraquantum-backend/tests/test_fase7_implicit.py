"""
FASE 7 (God-Tier) — Tests del campo escalar implícito HRBF (geología implícita).

Cubre:
  • Reproducción de valores: φ interpola exactamente los puntos de valor.
  • Reproducción de gradiente: ∇φ recupera las normales impuestas (HRBF).
  • Reconstrucción de geometría conocida (esfera): el nivel cero de φ separa
    interior/exterior dentro de tolerancia.
  • Deriva polinómica: un campo lineal se reproduce exacto (sin término RBF).
  • OrientationDatum.from_dip_azimuth: normal unitaria, polaridad hacia arriba.
  • Extracción desde sondajes: contactos objetivo↔resto + clasificación de grilla.
"""
import numpy as np
import pytest

from exploration.implicit_modeling import (
    HermiteRBFImplicit,
    ImplicitGeologicalModel,
    OrientationDatum,
    SpatialPetrophysicalPrior,
    build_spatial_prior_from_implicit,
    evolve_level_set,
    reinitialize_sdf,
    speed_from_property,
)


def _sphere_phi(shape, spacing, center, radius):
    """φ = R − |x−c| (>0 dentro), muestreado en centros de celda."""
    nx, ny, nz = shape
    dx, dy, dz = spacing
    xs = (np.arange(nx) + 0.5) * dx
    ys = (np.arange(ny) + 0.5) * dy
    zs = (np.arange(nz) + 0.5) * dz
    gx, gy, gz = np.meshgrid(xs, ys, zs, indexing="ij")
    r = np.sqrt((gx - center[0]) ** 2 + (gy - center[1]) ** 2 + (gz - center[2]) ** 2)
    return radius - r


# ── Stub mínimo equivalente a BoreholeInterval (evita acoplar el schema) ────
class _Seg:
    def __init__(self, x_m, z_m, y_from_m, y_to_m, lithology):
        self.x_m = x_m
        self.z_m = z_m
        self.y_from_m = y_from_m
        self.y_to_m = y_to_m
        self.lithology = lithology


def test_hrbf_reproduces_values():
    rng = np.random.default_rng(0)
    P = rng.uniform(-10, 10, size=(12, 3))
    v = rng.uniform(-1, 1, size=12)
    f = HermiteRBFImplicit(smoothing=0.0).fit(value_points=P, values=v)
    got = f.evaluate(P)
    assert np.allclose(got, v, atol=1e-6)


def test_hrbf_reproduces_gradient_constraints():
    # Una superficie plana inclinada: punto en el origen con normal conocida.
    P = np.array([[0.0, 0.0, 0.0]])
    v = np.array([0.0])
    Q = np.array([[0.0, 0.0, 0.0]])
    n = np.array([[0.0, -1.0, 0.0]])  # normal hacia arriba (−y)
    f = HermiteRBFImplicit(smoothing=0.0).fit(
        value_points=P, values=v, gradient_points=Q, gradients=n
    )
    g = f.evaluate_gradient(Q)[0]
    g /= np.linalg.norm(g)
    assert np.allclose(g, [0.0, -1.0, 0.0], atol=1e-5)


def test_hrbf_recovers_sphere_zero_level():
    # Muestreamos el interior (φ=+1) y exterior (φ=−1) de una esfera R=5 y
    # puntos en la superficie (φ=0). El nivel cero debe separar dentro/fuera.
    rng = np.random.default_rng(42)
    R = 5.0
    pts, vals = [], []
    for _ in range(60):
        p = rng.uniform(-9, 9, size=3)
        r = np.linalg.norm(p)
        if abs(r - R) < 0.4:
            continue  # evitar ambigüedad justo en la cáscara
        pts.append(p)
        vals.append(1.0 if r < R else -1.0)
    # Algunos puntos sobre la superficie con φ=0.
    for _ in range(20):
        u = rng.normal(size=3)
        u /= np.linalg.norm(u)
        pts.append(u * R)
        vals.append(0.0)
    f = HermiteRBFImplicit(smoothing=1e-6).fit(
        value_points=np.array(pts), values=np.array(vals)
    )
    # Evaluar en puntos test bien dentro / bien fuera.
    test = rng.uniform(-8, 8, size=(200, 3))
    rt = np.linalg.norm(test, axis=1)
    keep = np.abs(rt - R) > 1.5
    phi = f.evaluate(test[keep])
    inside = rt[keep] < R
    acc = np.mean((phi >= 0) == inside)
    assert acc > 0.9, f"clasificación esfera baja: {acc:.2f}"


def test_hrbf_reproduces_linear_field_via_drift():
    # φ(x) = 2 + 0.5x − y + 3z es polinómico de grado 1: la deriva lo capta exacto.
    rng = np.random.default_rng(7)
    P = rng.uniform(-5, 5, size=(20, 3))
    v = 2.0 + 0.5 * P[:, 0] - P[:, 1] + 3.0 * P[:, 2]
    f = HermiteRBFImplicit(smoothing=0.0).fit(value_points=P, values=v)
    Xt = rng.uniform(-5, 5, size=(30, 3))
    vt = 2.0 + 0.5 * Xt[:, 0] - Xt[:, 1] + 3.0 * Xt[:, 2]
    assert np.allclose(f.evaluate(Xt), vt, atol=1e-4)


def test_orientation_from_dip_azimuth_unit_upward():
    o = OrientationDatum.from_dip_azimuth(0, 0, 0, dip_deg=30.0, azimuth_deg=90.0)
    n = o.normal()
    assert np.isclose(np.linalg.norm(n), 1.0)
    assert n[1] < 0.0  # polo apunta hacia arriba (−y)
    # azimut 90° → buzamiento hacia +z, sin componente x.
    assert np.isclose(n[0], 0.0, atol=1e-9)
    assert n[2] > 0.0


def test_horizontal_orientation_points_straight_up():
    o = OrientationDatum.from_dip_azimuth(0, 0, 0, dip_deg=0.0, azimuth_deg=0.0)
    assert np.allclose(o.normal(), [0.0, -1.0, 0.0], atol=1e-9)


def test_implicit_model_from_boreholes_contacts_and_classify():
    # Dos sondajes verticales: tramo superior 'waste', inferior 'ore' (objetivo).
    # El contacto está a ~50 m de profundidad en ambos.
    segs = []
    for (xh, zh) in [(0.0, 0.0), (100.0, 0.0), (0.0, 100.0), (100.0, 100.0)]:
        segs.append(_Seg(xh, zh, 0.0, 50.0, "andesite"))
        segs.append(_Seg(xh, zh, 50.0, 120.0, "magnetite"))
    model = ImplicitGeologicalModel.from_boreholes(
        intervals=segs, target_lithologies=["magnetite"], smoothing=1e-6
    )
    assert model.n_contact_points == 4  # un contacto por sondaje
    assert model.n_value_points >= 8

    # Grilla 50x40x50 m de voxel cubriendo el bloque, profundidad 0..120.
    origin = (-20.0, 0.0, -20.0)
    spacing = (20.0, 12.0, 20.0)
    shape = (8, 10, 8)
    mask = model.classify_grid(origin, spacing, shape)
    assert mask.shape == (8, 10, 8)
    # Capa somera (y≈6 m) debe ser mayormente NO objetivo; capa profunda (y≈114) SÍ.
    ys = origin[1] + (np.arange(shape[1]) + 0.5) * spacing[1]
    shallow = np.argmin(np.abs(ys - 6.0))
    deep = np.argmin(np.abs(ys - 114.0))
    assert mask[:, deep, :].mean() > 0.6
    assert mask[:, shallow, :].mean() < 0.4


def test_fit_requires_value_points():
    with pytest.raises(ValueError):
        HermiteRBFImplicit().fit(value_points=None, values=None)


def test_evaluate_before_fit_raises():
    f = HermiteRBFImplicit()
    with pytest.raises(RuntimeError):
        f.evaluate(np.zeros((1, 3)))


# ── FASE 7.2 — geología → prior petrofísico ────────────────────────────────
def test_spatial_prior_hard_step():
    phi = np.array([[[-1.0, 0.5]], [[2.0, -3.0]]])  # (2,1,2)
    prior = build_spatial_prior_from_implicit(
        phi, target_mean=4.6, host_mean=2.7, target_std=0.2, host_std=0.1
    )
    assert isinstance(prior, SpatialPetrophysicalPrior)
    # φ≥0 → target_mean; φ<0 → host_mean.
    assert prior.mean[0, 0, 0] == pytest.approx(2.7)   # φ=-1
    assert prior.mean[0, 0, 1] == pytest.approx(4.6)   # φ=+0.5
    assert prior.mean[1, 0, 0] == pytest.approx(4.6)   # φ=+2
    assert prior.mean[1, 0, 1] == pytest.approx(2.7)   # φ=-3
    assert prior.class_label.sum() == 2
    assert prior.std[1, 0, 0] == pytest.approx(0.2)
    assert prior.shape == (2, 1, 2)


def test_spatial_prior_soft_blends_at_contact():
    phi = np.array([0.0]).reshape(1, 1, 1)
    prior = build_spatial_prior_from_implicit(
        phi, target_mean=4.0, host_mean=2.0, target_std=0.2, host_std=0.1, softness=0.5
    )
    # En φ=0 la membership suave = 0.5 → media a medio camino.
    assert prior.membership[0, 0, 0] == pytest.approx(0.5)
    assert prior.mean[0, 0, 0] == pytest.approx(3.0)


def test_spatial_prior_reference_flat_order_f():
    phi = _sphere_phi((4, 4, 4), (1, 1, 1), (2, 2, 2), 1.5)
    prior = build_spatial_prior_from_implicit(
        phi, target_mean=3.0, host_mean=2.0, target_std=0.1, host_std=0.1
    )
    flat = prior.reference_flat(order="F")
    assert flat.shape == (64,)
    assert np.array_equal(flat, prior.mean.ravel(order="F"))


# ── FASE 7.3 — geofísica → level-set deforma φ ─────────────────────────────
def test_speed_positive_where_property_high():
    prop = np.array([0.0, 1.0, 5.0])
    F = speed_from_property(prop, threshold=2.0, scale=1.0)
    assert F[0] < 0 and F[1] < 0 and F[2] > 0  # >umbral → crecer


def test_level_set_grows_body_when_geophysics_says_bigger():
    # φ inicial = esfera R=4; geofísica indica cuerpo mayor (propiedad alta en R=7).
    shape, spacing = (24, 24, 24), (1.0, 1.0, 1.0)
    center = (12.0, 12.0, 12.0)
    phi0 = _sphere_phi(shape, spacing, center, 4.0)
    prop_phi = _sphere_phi(shape, spacing, center, 7.0)  # cuerpo "verdadero" mayor
    F = np.where(prop_phi >= 0.0, 1.0, -1.0)             # dentro crecer, fuera contraer

    vol0 = int((phi0 >= 0).sum())
    phi1 = evolve_level_set(phi0, F, spacing, iterations=30)
    vol1 = int((phi1 >= 0).sum())
    assert vol1 > vol0, f"el cuerpo no creció: {vol0}→{vol1}"
    # No debe desbordar el target (R=7) groseramente.
    vol_true = int((prop_phi >= 0).sum())
    assert vol1 <= vol_true * 1.3


def test_level_set_shrinks_body_when_geophysics_says_smaller():
    shape, spacing = (24, 24, 24), (1.0, 1.0, 1.0)
    center = (12.0, 12.0, 12.0)
    phi0 = _sphere_phi(shape, spacing, center, 7.0)
    prop_phi = _sphere_phi(shape, spacing, center, 4.0)
    F = np.where(prop_phi >= 0.0, 1.0, -1.0)
    vol0 = int((phi0 >= 0).sum())
    phi1 = evolve_level_set(phi0, F, spacing, iterations=30)
    vol1 = int((phi1 >= 0).sum())
    assert vol1 < vol0


def test_level_set_stationary_when_consistent():
    # Si la geofísica concuerda con φ, la frontera apenas se mueve.
    shape, spacing = (20, 20, 20), (1.0, 1.0, 1.0)
    center = (10.0, 10.0, 10.0)
    phi0 = _sphere_phi(shape, spacing, center, 5.0)
    F = np.where(phi0 >= 0.0, 1.0, -1.0)  # crecer dentro, contraer fuera → equilibrio
    vol0 = int((phi0 >= 0).sum())
    phi1 = evolve_level_set(phi0, F, spacing, iterations=15)
    vol1 = int((phi1 >= 0).sum())
    assert abs(vol1 - vol0) <= max(0.1 * vol0, 30)


def test_reinitialize_drives_grad_to_one_near_zero_level():
    # Un φ con pendiente !=1 → reinit lo acerca a distancia con signo (|∇φ|≈1).
    shape, spacing = (24, 24, 24), (1.0, 1.0, 1.0)
    center = (12.0, 12.0, 12.0)
    phi = 3.0 * _sphere_phi(shape, spacing, center, 6.0)  # gradiente ~3
    phi_re = reinitialize_sdf(phi, spacing, iterations=12)
    # El nivel cero se preserva casi en todas las celdas (la reinic. discreta puede
    # mover la frontera < 1 celda; honesto exigir ~todo el signo, no byte-idéntico).
    agree = float(np.mean((phi_re >= 0) == (phi >= 0)))
    assert agree > 0.98, f"reinit movió demasiado el nivel cero: {agree:.3f}"
    # |∇φ| cerca de la banda del nivel cero baja hacia ~1.
    gx, gy, gz = np.gradient(phi_re, *spacing)
    gmag = np.sqrt(gx ** 2 + gy ** 2 + gz ** 2)
    band = np.abs(phi_re) < 2.0
    assert 0.5 < float(gmag[band].mean()) < 1.6
