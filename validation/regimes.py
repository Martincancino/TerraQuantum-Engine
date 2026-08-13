"""
Los 15 regímenes de `scripts/validation/error_budget.py`, DESCOMPUESTOS en
World × Campaign (P2).

Hoy, en `error_budget.Case`, conviven en un solo dataclass:
    mundo    -> depth_m, radius_m, delta_rho
    campaña  -> span_m, n_side, noise_mgal, seed

Esa mezcla impide el experimento que más importa: el MISMO cuerpo medido de varias
maneras. Aquí se separan, de modo que "profundidad" varía mundos y "cobertura",
"SNR" y "extensión" varían campañas sobre el mismo mundo.

DIFERENCIA DELIBERADA CON EL HARNESS ANTIGUO — y es el punto del Sprint 2:
`error_budget.py` fija λ=1e-3, que `docs/05` §A′ midió como NO representativo
(sobreajusta en profundo y fabricó el artefacto de "la profundidad nunca se
recupera"). Aquí se usa la configuración de PRODUCCIÓN (Morozov con σ declarado).
Se espera que varias celdas cambien; documentarlo es el entregable.
"""
from __future__ import annotations

from .contract import (Acceptance, Body, Campaign, DomainProps, GenerationMethod,
                       Geometry, NoiseModel, Properties, Provenance, Sphere,
                       SurveyDesign, Threshold, Topography, World, WorldMetadata)

# ── Malla IDÉNTICA a la de error_budget.py, para que las diferencias vengan del
#    RÉGIMEN y de la CONFIGURACIÓN, no de la discretización ──────────────────
BLOCK_M = 125.0
NX = NZ = 18
NY = 14
CENTER = NX * BLOCK_M / 2.0          # 1125 m
BOUNDS = (0.0, 0.0, 0.0, NX * BLOCK_M, NY * BLOCK_M, NZ * BLOCK_M)

BASE_DENSITY = 2.67
BASE_RADIUS_M = 150.0
BASE_DEPTH_M = 400.0
BASE_CONTRAST = 0.6

SEEDS = (20260805, 11, 202, 3003, 40004)      # P7: la varianza ES el hallazgo

WORLD_SCHEMA, CAMPAIGN_SCHEMA, ACCEPTANCE_SCHEMA = "world/1", "campaign/1", "acceptance/1"


def _world(wid: str, depth_m: float, delta_rho: float, axis: str, notes: str,
           regime: str) -> World:
    return World(
        schema_version=WORLD_SCHEMA, id=wid, instance_version=1,
        geometry=Geometry(
            bounds_m=BOUNDS,
            topography=Topography(kind="flat", elevation_m=0.0),
            bodies=(Body(id="b1",
                         shape=Sphere(cx_m=CENTER, cy_m=depth_m, cz_m=CENTER,
                                      radius_m=BASE_RADIUS_M),
                         domain="ore"),),
        ),
        properties=Properties(
            background=DomainProps(density_t_m3=BASE_DENSITY),
            domains={"ore": DomainProps(density_t_m3=BASE_DENSITY + delta_rho)},
        ),
        metadata=WorldMetadata(name=wid, axis=axis, regime=regime, notes=notes),
        provenance=Provenance(seed=0, generator_version="regimes/1"),
    ).freeze()


def _campaign(cid: str, world: World, seed: int, span_m: float = 1500.0,
              n_side: int = 12, noise_mgal: float = 0.02) -> Campaign:
    return Campaign(
        schema_version=CAMPAIGN_SCHEMA, id=cid, world_id=world.id,
        world_instance_version=world.instance_version,
        survey=SurveyDesign(span_m=span_m, n_side=n_side, height_m=0.0),
        noise=NoiseModel(instrument_mgal=noise_mgal, position_m=0.0),
        generation_method=GenerationMethod.THIRD_PARTY,
        generation_detail="choclo.point.gravity_u (masa puntual = exacta para esfera)",
        provenance=Provenance(seed=seed, generator_version="regimes/1"),
    )


# ═══════════════════════════════════════════════════════════════════════════
# MUNDOS — varían profundidad y contraste (propiedades del subsuelo)
# ═══════════════════════════════════════════════════════════════════════════

W_BASE = _world("w_base", BASE_DEPTH_M, BASE_CONTRAST, "baseline",
                "somero-moderado, contraste fuerte", "moderado")
W_DEPTH = {d: _world(f"w_depth_{d}", d, BASE_CONTRAST, "profundidad",
                     f"extent/depth={1500/d:.2f}",
                     "somero" if d <= 250 else "moderado" if d <= 400
                     else "profundo")
           for d in (250, 400, 600, 900)}
W_CONTRAST = {c: _world(f"w_contrast_{c}", BASE_DEPTH_M, c, "contraste",
                        f"contraste debil {c}", "moderado")
              for c in (0.4, 0.2)}


# ═══════════════════════════════════════════════════════════════════════════
# REGÍMENES — (mundo, constructor de campaña, eje, etiqueta)
# El mismo mundo `w_base` se mide de 8 maneras distintas: eso es lo que la
# estructura antigua no permitía expresar.
# ═══════════════════════════════════════════════════════════════════════════

def build_regimes():
    R = []
    R.append(("baseline", W_BASE, dict(), "baseline"))

    for d in (250, 400, 600, 900):
        R.append((f"depth_{d}m", W_DEPTH[d], dict(), "profundidad"))

    for n, lbl in ((14, "densa"), (9, "media"), (6, "dispersa")):
        R.append((f"coverage_{n}", W_BASE, dict(n_side=n), "cobertura"))

    for c in (0.4, 0.2):
        R.append((f"contrast_{c}", W_CONTRAST[c], dict(), "contraste"))

    for nz in (0.05, 0.15):
        R.append((f"noise_{nz}", W_BASE, dict(noise_mgal=nz), "SNR"))

    for s in (1200, 800):
        R.append((f"span_{s}m", W_BASE, dict(span_m=float(s)), "extension"))

    R.append(("worst_ldm_like", W_DEPTH[900],
              dict(n_side=6, noise_mgal=0.05), "compuesto"))
    return R


REGIMES = build_regimes()


def campaigns_for(name: str, world: World, kw: dict, seeds=SEEDS):
    return [_campaign(f"c_{name}_s{s}", world, s, **kw) for s in seeds]


# ── Aceptación DIAGNÓSTICA para el barrido ─────────────────────────────────
# El Sprint 2 MIDE; no puede gatear con umbrales que aún no se han medido (P3).
# Se declara un único piso de sanidad, con su justificación explícita, y los
# umbrales por régimen se derivan DE ESTE BARRIDO en el propio Sprint 2.
DIAGNOSTIC = Acceptance(
    schema_version=ACCEPTANCE_SCHEMA, applies_to="*",
    thresholds=(
        Threshold(
            metric="horizontal_error_m", op="<=", value=2500.0,
            justification=("Piso de SANIDAD, no de calidad: 2500 m excede el lado del "
                           "dominio (2250 m), así que solo falla si la recuperación es "
                           "degenerada o el modelo sale vacío. El Sprint 2 mide para "
                           "PODER fijar umbrales por régimen; gatear antes de medir "
                           "sería exactamente el vicio que P3 prohíbe."),
            measured_on="dominio de la malla (18x125 m)", measured_value=2250.0,
        ),
    ),
)
