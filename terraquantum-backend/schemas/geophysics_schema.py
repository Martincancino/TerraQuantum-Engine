from pydantic import BaseModel, Field, model_validator
from typing import Any, Dict, List, Optional


class GravityObservation(BaseModel):
    x_m: float
    y_m: float
    z_m: float
    # g: valor de gravedad observada. El kernel interno produce m/s² cuando la
    # densidad está en t/m³. El estimador de sigma es escala-invariante (2% del
    # valor de la señal), por lo que g puede estar en m/s², mGal o µGal siempre
    # que TODAS las observaciones usen la misma unidad. No mezclar unidades.
    g: float


class BoreholeInterval(BaseModel):
    # FASE 8 (Q4): intervalo de sondaje con densidad medida que ancla la inversión.
    #
    # LIMITACIÓN ACTUAL: por ahora SOLO se soportan pozos VERTICALES. El intervalo
    # se define por una posición (x_m, z_m) fija y un rango vertical [y_from_m, y_to_m].
    # La arquitectura (lista de intervalos independientes) está pensada para admitir
    # en el futuro polilíneas 3D (sondajes desviados) sin romper el contrato de la API:
    # bastaría con extender este modelo a un par de puntos extremos por segmento.
    #
    # FASE 9B — Limpieza semántica: un intervalo puede aportar propiedad GRAVIMÉTRICA
    # (density_t_m3) y/o MAGNÉTICA (susceptibility_si). Ambos son opcionales por
    # separado, pero el model_validator exige que al menos uno tenga dato (no se
    # admiten intervalos vacíos). El motor gravimétrico lee density_t_m3 y salta los
    # intervalos sin densidad; el motor magnético lee susceptibility_si y salta los
    # intervalos sin susceptibilidad. Así un mismo sondaje sirve a ambas físicas sin
    # reinterpretar un campo como otro.
    x_m: float = Field(..., description="Coordenada local X del sondaje (m)")
    z_m: float = Field(..., description="Coordenada local Z del sondaje (m)")
    y_from_m: float = Field(..., description="Profundidad inicial del intervalo (m, + hacia abajo)")
    y_to_m: float = Field(..., description="Profundidad final del intervalo (m, + hacia abajo)")
    density_t_m3: Optional[float] = Field(
        default=None, gt=0.0,
        description="Densidad medida del intervalo (t/m³). Opcional: ancla la inversión gravimétrica.",
    )
    susceptibility_si: Optional[float] = Field(
        default=None, ge=0.0,
        description="Susceptibilidad magnética medida (SI, adimensional). Opcional: ancla la inversión magnética.",
    )

    @model_validator(mode="after")
    def _require_at_least_one_property(self):
        """Evita intervalos vacíos: al menos density_t_m3 o susceptibility_si con dato."""
        if self.density_t_m3 is None and self.susceptibility_si is None:
            raise ValueError(
                "Cada intervalo de sondaje debe declarar al menos una propiedad medida: "
                "density_t_m3 (gravimetría) y/o susceptibility_si (magnetometría)."
            )
        return self


class GeophysicsInvertInput(BaseModel):
    project_id: Optional[str] = None
    run_id: Optional[str] = None
    depth: int = Field(..., gt=0, le=100000, description="Profundidad objetivo metros: 1-100000")
    nir: int = Field(..., ge=0, le=100, description="Índice NIR satélite: 0-100")
    fe: int = Field(..., ge=0, le=100, description="Índice Fe satélite: 0-100")
    region: str
    # lat/lon: metadatos administrativos únicamente. No se usan para proyectar la
    # grilla local — la inversión opera en coordenadas locales (metros) definidas
    # por x_m, y_m, z_m de las observaciones. El origen local (0,0,0) no se
    # georreferencia automáticamente a estas coordenadas geográficas.
    lat: str
    lon: str
    nx: int = Field(..., ge=4, le=80, description="Grilla X: 4-80 voxeles")
    ny: int = Field(..., ge=4, le=80, description="Grilla Y: 4-80 voxeles")
    nz: int = Field(..., ge=4, le=80, description="Grilla Z: 4-80 voxeles")
    block_size: int = Field(..., gt=0, le=10000, description="Tamaño voxel metros: 1-10000")
    cutoff_radius: float = Field(..., gt=0.0, description="Radio de corte: > 0")
    lambda_mag: float = Field(..., ge=0.0, description="Regularización magnitud: ≥ 0")
    alpha_spatial: float = Field(..., ge=0.0, description="Regularización espacial: ≥ 0")
    observations: List[GravityObservation] = Field(..., min_length=10, description="Mínimo 10 observaciones gravimétricas")
    enable_focusing: bool = False  # Deprecated since A1.4; backend always runs MS-x by policy.
    auto_params_metadata: Optional[dict] = None
    # Separación regional-residual (gap industrial #2). OFF por defecto → comportamiento intacto.
    remove_regional: bool = Field(False, description="Restar tendencia regional polinómica antes de invertir")
    regional_order: int = Field(2, ge=1, le=4, description="Grado del polinomio regional: 1-4")
    # Integridad científica (gap #1): el "grade"/ley es un PROXY HEURÍSTICO no físico
    # (no derivable de gravimetría). OFF por defecto → el payload industrial NO emite
    # ley inventada (grade/avg_grade = null); el contraste de densidad real se conserva.
    # ON → reproduce el comportamiento demo heredado con la ley proxy poblada.
    expose_demo_grade: bool = Field(
        False,
        description="Exponer el proxy de ley heurístico (modo demo). OFF=payload industrial sin ley inventada",
    )
    # Incertidumbre posterior por vóxel (Track 3). OFF por defecto (costo extra:
    # ~n_probes solves de CG). Estimador de Hutchinson sobre la covarianza posterior
    # lineal; produce σ (t/m³) por vóxel — incertidumbre estadística, no heurística.
    compute_uncertainty: bool = Field(
        False,
        description="Calcular σ posterior por vóxel (Hutchinson). Costo extra; OFF por defecto",
    )
    # Bound petrofísico explícito sobre la densidad recuperada (t/m³).
    # Defaults preservan el comportamiento histórico (clip implícito [2.6, 4.2]).
    # Para depósitos de magnetita masiva o cromita (densidad > 4.2) aumentar density_max.
    density_min: float = Field(
        2.6,
        ge=0.5, le=5.0,
        description="Densidad mínima permitida en la inversión (t/m³). Default: 2.6 (roca huésped granítica)",
    )
    density_max: float = Field(
        4.2,
        ge=1.0, le=8.0,
        description="Densidad máxima permitida en la inversión (t/m³). Default: 4.2. Usar 5.2 para magnetita masiva.",
    )
    # R-A2: Selección automática de lambda vía scan chi²-target (post-auditoría).
    # Cuando True (o lambda_mag==0), escanea [1e-3…1e-6] y elige el lambda que
    # minimice |log10(chi²_final)| sujeto a cond(A) < 1e12. Ignora lambda_mag.
    auto_lambda: bool = Field(
        False,
        description="Selección automática de lambda via scan chi²-target (R-A2). Ignora lambda_mag cuando True.",
    )
    # ── FASE 8 (Q4): Constraints geológicos por sondaje (boreholes) ───────────
    # Intervalos de densidad medida que anclan la inversión (strong soft constraint).
    # Vacío por defecto → comportamiento intacto. Solo pozos verticales por ahora;
    # la lista de intervalos permite extensión futura a polilíneas 3D.
    boreholes: Optional[List[BoreholeInterval]] = Field(
        default=[],
        description="Intervalos de sondaje (densidad medida) que anclan la inversión. Solo verticales por ahora.",
    )
    # ── FASE 9A: Magnetometría — motor independiente (magnetización inducida) ──
    # magnetic_nt: anomalía de Intensidad Magnética Total (TMI) en nanoTesla, UNA
    # por observación, PARALELA a `observations` (que aporta x_m, y_m, z_m). Cuando
    # se provee y su largo == len(observations), el servicio rutea a
    # solve_magnetic_inversion_lsqr e IGNORA el campo `g` de las observaciones
    # (envíe g=0.0 como placeholder). None → modo gravimétrico 100% intacto.
    # NO se mezcla con gravedad en este input: es un motor aislado (Fase 9A, sin Joint).
    magnetic_nt: Optional[List[float]] = Field(
        default=None,
        description="Anomalía TMI por observación (nT), paralela a observations. Si se provee activa el motor magnético (Fase 9A) e ignora g.",
    )
    # Parámetros del campo geomagnético inducido (defaults razonables para Chile).
    # Convención de ejes del backend: x=Norte, z=Este, y=profundidad (+ hacia abajo).
    inclination_deg: float = Field(
        -30.0, ge=-90.0, le=90.0,
        description="Inclinación del campo inducido (°, + hacia abajo). Default -30 (hemisferio sur).",
    )
    declination_deg: float = Field(
        2.0, ge=-180.0, le=180.0,
        description="Declinación del campo inducido (°, + al Este desde el Norte). Default 2.",
    )
    field_intensity_nt: float = Field(
        23500.0, gt=0.0, le=70000.0,
        description="Intensidad del campo geomagnético B0 (nT). Default 23500 (norte de Chile).",
    )
    # Bounds de susceptibilidad magnética (SI, adimensional). susc_min=0 impone
    # no-negatividad física de la magnetización inducida. Para magnetita masiva,
    # cromita o BIF subir susc_max (la susceptibilidad real puede superar 1.0 SI).
    susc_min: float = Field(
        0.0, ge=0.0, le=10.0,
        description="Susceptibilidad mínima permitida (SI). Default 0.0 (no-negatividad física).",
    )
    susc_max: float = Field(
        1.0, gt=0.0, le=10.0,
        description="Susceptibilidad máxima permitida (SI). Default 1.0. Subir para magnetita masiva.",
    )
    # ── FASE 9C-2: Inversión Conjunta (Joint Inversion / Cross-Gradient) ──────
    # Cuando el input trae A LA VEZ señal gravimétrica real (g≠0) y magnética
    # (magnetic_nt≠0), el servicio rutea al Orquestador de Inversión Conjunta
    # (Gauss-Newton alternado con continuation exponencial del peso cross-gradient).
    # Estos dos parámetros controlan SOLO ese bucle; no afectan los motores aislados.
    joint_max_iter: int = Field(
        15, ge=1, le=100,
        description="Iteraciones máximas del bucle alternado de inversión conjunta (Fase 9C-2).",
    )
    cross_lambda_max: float = Field(
        1e4, ge=0.0,
        description="Peso máximo del acoplamiento cross-gradient (continuation exponencial). Fase 9C-2.",
    )


class GeophysicsInvertResponse(BaseModel):
    voxels: List[Dict[str, Any]] = Field(default_factory=list)
    best_target: Optional[Dict[str, Any]] = None
    report: Dict[str, Any] = Field(default_factory=dict)
    misfit_error_percent: Optional[float] = None
