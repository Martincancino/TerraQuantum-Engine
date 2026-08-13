"""
CONTRATO DEL VALIDATION FRAMEWORK — las cuatro entidades.

Diseño: docs/07_VALIDATION_FRAMEWORK.md §2.

Cada entidad responde UNA pregunta:
    World       -> qué hay ahí abajo (la verdad)
    Campaign    -> cómo lo medí
    Acceptance  -> qué considero bueno
    Result      -> qué obtuve

Principios que el TIPO impone (no la disciplina humana):
    P1  la verdad es una sola cosa      -> no existe campo `ground_truth`
    P2  el mundo no sabe cómo se mide   -> survey/ruido viven en Campaign
    P3  umbrales justificados           -> Threshold.justification es obligatorio
    P4  anti-inverse-crime declarado    -> Campaign.generation_method
    P6  procedencia completa            -> Provenance en World, Campaign y Result
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional

# ═══════════════════════════════════════════════════════════════════════════
# Procedencia (P6)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Provenance:
    """Sin esto, 'reproducible' es una aspiración."""
    seed: int
    generator_version: str
    created_by: str = "validation-framework"
    content_hash: str = ""          # se rellena con freeze()

    def with_hash(self, payload: dict) -> "Provenance":
        blob = json.dumps(payload, sort_keys=True, default=str).encode()
        return Provenance(
            seed=self.seed,
            generator_version=self.generator_version,
            created_by=self.created_by,
            content_hash=hashlib.blake2b(blob, digest_size=16).hexdigest(),
        )


# ═══════════════════════════════════════════════════════════════════════════
# World — la verdad (P1, P2)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Sphere:
    """Forma PARAMÉTRICA, no una máscara de vóxeles: permite evaluar la verdad
    a cualquier resolución sin atar el mundo a una malla concreta."""
    kind: str = "sphere"
    cx_m: float = 0.0
    cy_m: float = 0.0          # profundidad del centro (y positivo HACIA ABAJO, como TQ)
    cz_m: float = 0.0
    radius_m: float = 100.0

    def contains(self, x, y, z):
        return ((x - self.cx_m) ** 2 + (y - self.cy_m) ** 2
                + (z - self.cz_m) ** 2) <= self.radius_m ** 2

    @property
    def volume_m3(self) -> float:
        return 4.0 / 3.0 * 3.141592653589793 * self.radius_m ** 3

    @property
    def top_depth_m(self) -> float:
        return self.cy_m - self.radius_m


@dataclass(frozen=True)
class Prism:
    kind: str = "prism"
    x0_m: float = 0.0
    x1_m: float = 0.0
    y0_m: float = 0.0          # techo (y positivo hacia abajo)
    y1_m: float = 0.0          # base
    z0_m: float = 0.0
    z1_m: float = 0.0

    def contains(self, x, y, z):
        return ((x >= self.x0_m) & (x <= self.x1_m)
                & (y >= self.y0_m) & (y <= self.y1_m)
                & (z >= self.z0_m) & (z <= self.z1_m))

    @property
    def volume_m3(self) -> float:
        return ((self.x1_m - self.x0_m) * (self.y1_m - self.y0_m)
                * (self.z1_m - self.z0_m))

    @property
    def top_depth_m(self) -> float:
        return self.y0_m


Shape = Sphere | Prism


@dataclass(frozen=True)
class Body:
    id: str
    shape: Shape
    domain: str                 # clave hacia Properties.domains


@dataclass(frozen=True)
class Topography:
    """'flat' = superficie plana en y=0. Otros modos se añadirán con su verdad."""
    kind: str = "flat"
    elevation_m: float = 0.0


@dataclass(frozen=True)
class Geometry:
    bounds_m: tuple            # (x0, y0, z0, x1, y1, z1); y positivo hacia ABAJO
    topography: Topography
    bodies: tuple[Body, ...]


@dataclass(frozen=True)
class DomainProps:
    density_t_m3: float
    susceptibility_si: float = 0.0


@dataclass(frozen=True)
class Properties:
    background: DomainProps
    domains: dict[str, DomainProps]


@dataclass(frozen=True)
class WorldMetadata:
    name: str
    axis: str                   # qué eje de régimen aísla este mundo
    regime: str                 # somero | moderado | profundo | ...
    notes: str = ""


@dataclass(frozen=True)
class World:
    """La realidad del subsuelo. Inmutable. NO sabe que existe un survey (P2).
    NO tiene campo `ground_truth`: los derivados se calculan (P1)."""
    schema_version: str
    id: str
    instance_version: int
    geometry: Geometry
    properties: Properties
    metadata: WorldMetadata
    provenance: Provenance

    def freeze(self) -> "World":
        """Sella el mundo con el hash de su contenido (detecta fixture drift)."""
        payload = {
            "id": self.id,
            "instance_version": self.instance_version,
            "geometry": asdict(self.geometry),
            "properties": asdict(self.properties),
        }
        return World(
            schema_version=self.schema_version, id=self.id,
            instance_version=self.instance_version, geometry=self.geometry,
            properties=self.properties, metadata=self.metadata,
            provenance=self.provenance.with_hash(payload),
        )


# ═══════════════════════════════════════════════════════════════════════════
# Campaign — cómo se midió (P2, P4)
# ═══════════════════════════════════════════════════════════════════════════


class GenerationMethod(str, Enum):
    """P4: el anti-inverse-crime pasa de disciplina a invariante.

    Orden de preferencia (de más fuerte a más débil):
      THIRD_PARTY       implementación externa e independiente (choclo/Fatiando)
      ANALYTIC          forma cerrada (esfera, prisma, dipolo)
      FORWARD_ALT_MESH  motor propio, malla DISTINTA a la de inversión
      INVERSE_CRIME     PROHIBIDO en gates — solo diagnóstico
    """
    THIRD_PARTY = "third_party_forward"
    ANALYTIC = "analytic"
    FORWARD_ALT_MESH = "forward_alt_mesh"
    INVERSE_CRIME = "INVERSE_CRIME"

    @property
    def admissible_in_gate(self) -> bool:
        return self is not GenerationMethod.INVERSE_CRIME


@dataclass(frozen=True)
class SurveyDesign:
    span_m: float              # extensión del survey (lado del cuadrado)
    n_side: int                # estaciones por lado
    height_m: float = 0.0      # altura del sensor sobre la superficie


@dataclass(frozen=True)
class NoiseModel:
    instrument_mgal: float = 0.0     # ruido instrumental gaussiano (mGal)
    position_m: float = 0.0          # error de posicionamiento (m)


@dataclass(frozen=True)
class Campaign:
    schema_version: str
    id: str
    world_id: str
    world_instance_version: int      # detecta desfase mundo/campaña
    survey: SurveyDesign
    noise: NoiseModel
    generation_method: GenerationMethod
    provenance: Provenance
    generation_detail: str = ""      # p.ej. "choclo.prism.gravity_u v0.3.2"


# ═══════════════════════════════════════════════════════════════════════════
# SolverConfig — cómo se configuró el sistema bajo prueba
#
# Añadida tras el Sprint 2, que MIDIÓ que `density_min` cambia el resultado de
# forma material y ADEMÁS altera el λ que Morozov selecciona en un orden de
# magnitud — con el efecto INVERTIDO según el régimen (mejora la malla fina,
# hunde la gruesa). Un parámetro así no puede vivir como default del runner.
#
# Es P3/P6 aplicado a la configuración: lo que cambia el resultado se DECLARA.
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class SolverConfig:
    schema_version: str
    id: str
    lambda_mode: str                 # "morozov" (producción con σ) | "fixed"
    density_min_rel_base: float      # relativo a la densidad de fondo del mundo
    density_max_rel_base: float
    regularization_norm: str         # "L2" | "compact" | "mixed"
    rationale: str                   # POR QUÉ esta config — obligatorio
    provenance: Provenance
    lambda_fixed: Optional[float] = None

    def __post_init__(self):
        if not self.rationale.strip():
            raise ValueError(
                f"SolverConfig({self.id}): `rationale` es obligatorio. "
                "El Sprint 2 midió que estos parámetros cambian el resultado y el "
                "propio λ elegido; una configuración sin razón declarada produce "
                "números incomparables."
            )
        if self.lambda_mode not in ("morozov", "fixed"):
            raise ValueError(f"lambda_mode inválido: {self.lambda_mode!r}")
        if self.lambda_mode == "fixed" and not self.lambda_fixed:
            raise ValueError("lambda_mode='fixed' exige lambda_fixed > 0")

    def density_bounds(self, base_density: float) -> tuple[float, float]:
        return (base_density + self.density_min_rel_base,
                base_density + self.density_max_rel_base)


# ═══════════════════════════════════════════════════════════════════════════
# Acceptance — qué se considera bueno (P3)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Threshold:
    """P3: no se puede construir un umbral sin la medición que lo respalda.
    `justification` y `measured_value` son OBLIGATORIOS a nivel de tipo."""
    metric: str
    op: str                     # "<=" | ">="
    value: float
    justification: str
    measured_on: str
    measured_value: float

    def __post_init__(self):
        if not self.justification.strip():
            raise ValueError(
                f"Threshold({self.metric}): `justification` es obligatorio (P3). "
                "Un umbral sin la medición que lo respalda es contabilidad, no ciencia."
            )
        if self.op not in ("<=", ">="):
            raise ValueError(f"op inválido: {self.op!r}")

    def passes(self, observed: float) -> bool:
        if observed != observed:            # NaN
            return False
        return observed <= self.value if self.op == "<=" else observed >= self.value


@dataclass(frozen=True)
class Acceptance:
    schema_version: str
    applies_to: str             # world_id | regime:<nombre> | "*"
    thresholds: tuple[Threshold, ...]


# ═══════════════════════════════════════════════════════════════════════════
# Result — qué se obtuvo (P5, P6)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Metrics:
    # Independientes del umbral — PRIMARIAS para comparar versiones (D2)
    pr_auc: float = float("nan")
    iou_auc: float = float("nan")
    # De localización
    horizontal_error_m: float = float("nan")
    depth_error_centroid_m: float = float("nan")
    depth_error_top_m: float = float("nan")
    # De campo
    pearson_r: float = float("nan")
    chi2_red: float = float("nan")
    misfit_pct: float = float("nan")
    # Dependientes del umbral — SECUNDARIAS, nunca comparan versiones (D2)
    iou_at_tau: float = float("nan")
    tau_used: float = float("nan")
    volume_error_pct: float = float("nan")


@dataclass(frozen=True)
class CalibrationReport:
    """D3: tríada estándar de calibración en vez de un contador de fallos.
    La confianza de TQ es ORDINAL (HIGH/MEDIUM/LOW); cada nivel es un bin."""
    declared_confidence: str = "UNKNOWN"
    declared_depth_confidence: str = "UNKNOWN"
    is_null_space_artifact: bool = False
    actual_horizontal_error_m: float = float("nan")
    actual_depth_error_m: float = float("nan")
    quadrant: str = "UNKNOWN"       # CALIBRADO | SOBRECONFIADO | CONSERVADOR


@dataclass(frozen=True)
class Result:
    schema_version: str
    run_id: str
    world_id: str
    world_instance_version: int
    world_content_hash: str
    campaign_id: str
    generation_method: str
    solver_config_id: str            # ningun Result es comparable sin esto
    tq_version: str
    tq_config: dict                  # configuración EFECTIVA, no la pedida (H-38)
    entry_point: str                 # "production_flow" | "direct_solver" (P5)
    metrics: Metrics
    calibration: CalibrationReport
    verdict: str                     # PASS | FAIL | EXCLUDED_INVERSE_CRIME | ERROR
    failed_thresholds: tuple[str, ...]
    runtime_s: float
    provenance: Provenance
    error: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["failed_thresholds"] = list(self.failed_thresholds)
        return d
