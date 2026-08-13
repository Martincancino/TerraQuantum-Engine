"""
Catálogo de mundos, campañas y criterios de aceptación.

Regla para añadir un mundo (§6, Sprint 5 del diseño): debe responder a
"¿qué eje aísla este mundo que ningún otro aísla?". Si no hay respuesta, no entra.
"""
from __future__ import annotations

from .contract import (Acceptance, Body, Campaign, DomainProps, GenerationMethod,
                       Geometry, NoiseModel, Properties, Provenance, Sphere,
                       SurveyDesign, Threshold, Topography, World, WorldMetadata)

WORLD_SCHEMA = "world/1"
CAMPAIGN_SCHEMA = "campaign/1"
ACCEPTANCE_SCHEMA = "acceptance/1"

# Parámetros de evaluación declarados (auditables, no escondidos en el comparador)
TAU_FRAC_OF_PEAK = 0.50          # solo para métricas SECUNDARIAS (D2)
ERROR_LARGE_ABOVE_M = 200.0      # frontera "error grande" para la matriz de honestidad


# ═══════════════════════════════════════════════════════════════════════════
# w001 — esfera única, somera. Eje aislado: NINGUNO (es el caso de control).
# ═══════════════════════════════════════════════════════════════════════════

W001 = World(
    schema_version=WORLD_SCHEMA,
    id="w001_single_sphere",
    instance_version=1,
    geometry=Geometry(
        bounds_m=(0.0, 0.0, 0.0, 2000.0, 1000.0, 2000.0),   # y = profundidad
        topography=Topography(kind="flat", elevation_m=0.0),
        bodies=(
            Body(id="b1",
                 shape=Sphere(cx_m=1000.0, cy_m=300.0, cz_m=1000.0, radius_m=150.0),
                 domain="ore"),
        ),
    ),
    properties=Properties(
        background=DomainProps(density_t_m3=2.67),
        domains={"ore": DomainProps(density_t_m3=3.27)},     # contraste +0.6
    ),
    metadata=WorldMetadata(
        name="Esfera única somera",
        axis="control",
        regime="somero",
        notes=("Caso de control del framework. Cuerpo compacto, poco profundo, "
               "alto contraste: el régimen donde el producto declara su fortaleza "
               "(targeting horizontal). Si esto falla, nada más tiene sentido."),
    ),
    provenance=Provenance(seed=20260805, generator_version="catalog/1"),
).freeze()


C001_CLEAN = Campaign(
    schema_version=CAMPAIGN_SCHEMA,
    id="c001_dense_clean",
    world_id="w001_single_sphere",
    world_instance_version=1,
    survey=SurveyDesign(span_m=1600.0, n_side=16, height_m=0.0),
    noise=NoiseModel(instrument_mgal=0.01, position_m=0.0),
    generation_method=GenerationMethod.THIRD_PARTY,
    generation_detail="choclo.point.gravity_u v0.3.2 (masa puntual = exacta para esfera)",
    provenance=Provenance(seed=20260805, generator_version="catalog/1"),
)


# ── Umbrales: cada uno con la medición que lo respalda (P3) ─────────────────
# Nota honesta: en el Sprint 1 estos umbrales se anclan a los benchmarks EXTERNOS
# ya medidos del proyecto, no a una corrida de este framework (que aún no existía
# cuando se escribieron).
#
# ACTUALIZACIÓN 2026-08-06 — el re-anclaje se hizo, pero NO aquí, y el motivo importa:
# el barrido de 150 corridas midió los mundos de `regimes.py` sobre malla de 125 m.
# `w001` es otro mundo y se corre con otra malla, así que copiarle esas medianas sería
# anclar a una medición que no lo midió. Los umbrales medidos viven en
# `acceptance_measured.py` (15 regímenes, generados desde los datos crudos).
# A001 se queda anclado a los benchmarks externos, con ese hecho declarado, hasta que
# w001 entre en un barrido propio.

A001 = Acceptance(
    schema_version=ACCEPTANCE_SCHEMA,
    applies_to="w001_single_sphere",
    thresholds=(
        Threshold(
            metric="horizontal_error_m", op="<=", value=150.0,
            justification=("Régimen somero con cobertura densa y señal clara. "
                           "DO-27 (kimberlita real, benchmark externo) dio 53.7 m y "
                           "Raglan 212 m con dato de campo crudo; el presupuesto de "
                           "error interno midió 2 m en somero-denso-limpio y 26 m en "
                           "cobertura densa. 150 m = ~1 radio del cuerpo, holgado "
                           "frente a lo medido y aún accionable para perforar."),
            measured_on="F9 gate DO-27 (53.7 m) + error_budget.py somero/denso (2-26 m)",
            measured_value=53.7,
        ),
        Threshold(
            metric="pr_auc", op=">=", value=0.30,
            justification=("Métrica primaria independiente del umbral (D2). Sin línea "
                           "base previa en el repo: 0.30 se fija como piso de SANIDAD "
                           "(muy por encima del azar, que para esta fracción de cuerpo "
                           "es ~0.02) para detectar una recuperación degenerada, no "
                           "para certificar calidad. Se re-ancla en el Sprint 2 con la "
                           "mediana de 5 semillas."),
            measured_on="sin línea base previa — piso de sanidad, no de calidad",
            measured_value=0.02,
        ),
    ),
)


SMOKE = [(W001, C001_CLEAN, A001)]
