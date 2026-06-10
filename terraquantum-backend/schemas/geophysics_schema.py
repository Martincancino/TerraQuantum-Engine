from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Any, Dict, List, Literal, Optional


class GmmComponent(BaseModel):
    """Una componente de la Mixtura Gaussiana petrológica (Fase 11 — PGI)."""
    mean_density_t_m3: float = Field(
        ..., ge=0.5, le=8.0,
        description="Densidad media de la litología (t/m³).",
    )
    std_density_t_m3: float = Field(
        ..., gt=0.0, le=2.0,
        description="Desviación estándar de la densidad (t/m³).",
    )
    weight: float = Field(
        ..., gt=0.0, le=1.0,
        description="Proporción volumétrica de la litología (suma de pesos debe ser ~1).",
    )


class PgiParams(BaseModel):
    """Parámetros de la Inversión Guiada Petrológica — Fase 11 (Astic & Oldenburg 2019).

    El GMM ancla el modelo invertido a K clases petrológicas con distribuciones
    Gaussianas conocidas (de sondaje o bibliografía). Mínimo 2 componentes.
    Cuando `fit_from_model=True`, los campos components son ignorados y el GMM
    se estima automáticamente de la inversión inicial (baja confiabilidad).
    """
    components: List[GmmComponent] = Field(
        ..., min_length=2, max_length=10,
        description="Componentes del GMM (K ≥ 2). Pesos normalizados internamente.",
    )
    alpha_pgi: float = Field(
        default=0.1, gt=0.0, le=100.0,
        description="Peso del término PGI en la función objetivo (mayor = más adherencia al GMM).",
    )
    max_iter: int = Field(
        default=10, ge=1, le=50,
        description="Iteraciones máximas del bucle de actualización m_PGI (criterio de parada).",
    )
    convergence_tol: float = Field(
        default=1e-3, gt=0.0,
        description="Tolerancia relativa de convergencia ||Δm_pgi|| / ||m_pgi||.",
    )
    fit_from_model: bool = Field(
        default=False,
        description="Si True, estima el GMM desde la inversión inicial (ignora components).",
    )
    n_components_auto: int = Field(
        default=3, ge=2, le=10,
        description="Número de componentes del GMM cuando fit_from_model=True.",
    )


class MagneticRemanenceParams(BaseModel):
    """Parámetros de remanencia magnética — Fase 12 (Koenigsberger Q).

    Activa el motor J = J_ind + Q·J_rem en la inversión magnética.
    Con enabled=False o q_ratio=0: comportamiento heredado (solo inducida).
    """
    enabled: bool = Field(
        default=False,
        description="Activar remanencia magnética. False = solo magnetización inducida (comportamiento histórico).",
    )
    q_ratio: float = Field(
        default=1.0, ge=0.0, le=100.0,
        description="Ratio de Koenigsberger Q = |J_rem| / |J_ind|. Q>1: remanencia domina.",
    )
    remanence_inc_deg: float = Field(
        default=-45.0, ge=-90.0, le=90.0,
        description="Inclinación de la remanencia [°]. Para magnetita chilena invertida: ~−60° a −30°.",
    )
    remanence_dec_deg: float = Field(
        default=0.0, ge=-180.0, le=180.0,
        description="Declinación de la remanencia [°]. Para remanencia reversa típica: 180°.",
    )
    inversion_mode: Literal["induced_only", "total_field", "amplitude"] = Field(
        default="induced_only",
        description=(
            "Modo de inversión magnética. "
            "'induced_only': solo J_ind (default, sin remanencia). "
            "'total_field': kernel total G_ind + Q·G_rem con Inc_rem/Dec_rem explícitos. "
            "'amplitude': inversión de amplitud |J_total| dirección-independiente."
        ),
    )
    do_q_sweep: bool = Field(
        default=False,
        description="Si True, barrer Q ∈ [0, q_ratio] en 10 pasos y reportar Q óptimo por misfit.",
    )


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
    depth: int = Field(..., gt=0, le=1_000_000, description="Profundidad objetivo metros: 1-1000000 (escala regional)")
    nir: int = Field(..., ge=0, le=100, description="Índice NIR satélite: 0-100")
    fe: int = Field(..., ge=0, le=100, description="Índice Fe satélite: 0-100")
    region: str
    # lat/lon: metadatos administrativos únicamente (OPCIONALES). No se usan para
    # proyectar la grilla local — la inversión opera en coordenadas locales (metros)
    # definidas por x_m, y_m, z_m de las observaciones. El origen local (0,0,0) no
    # se georreferencia automáticamente a estas coordenadas geográficas.
    # NOTA: Si no tienes lat/lon de los datos crudos del gravímetro, envía null.
    lat: Optional[str] = None
    lon: Optional[str] = None
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
    # H-A0 Bug 3: density_max subido a 5.5 para cubrir magnetita (5.0-5.2),
    # cromita (4.5-4.8) y pirita masiva (4.5-5.0).
    density_min: float = Field(
        2.6,
        ge=-5.0, le=5.0,
        description="Densidad mínima permitida en la inversión (t/m³). Default: 2.6 (roca huésped "
                    "granítica = contraste ≥ 0). Valores < 2.6 permiten contrastes NEGATIVOS "
                    "(magma, sal, cavidades): ej. 2.0 ≡ contraste ≥ -0.6 t/m³.",
    )
    density_max: float = Field(
        5.5,
        ge=1.0, le=8.0,
        description="Densidad máxima permitida en la inversión (t/m³). Default: 5.5 (cubre magnetita, cromita, pirita masiva).",
    )
    # R-A2: Selección automática de lambda vía scan chi²-target (post-auditoría).
    # Cuando True (o lambda_mag==0), escanea [1e-3…1e-6] y elige el lambda que
    # minimice |log10(chi²_final)| sujeto a cond(A) < 1e12. Ignora lambda_mag.
    auto_lambda: bool = Field(
        False,
        description="Selección automática de lambda via scan chi²-target (R-A2). Ignora lambda_mag cuando True.",
    )
    # ── Flujo de datos de campo: sigma por instrumento ─────────────────────────
    # Cuando != "unknown" y el caller no fija noise_floor_mgal explícito (v2),
    # el servicio usa GRAVIMETER_NOISE_FLOOR[gravimeter_type] como piso de sigma:
    # sigma_i = max(noise_floor, noise_pct·|d_i|). "unknown" conserva el
    # comportamiento histórico (sigma adaptivo invariante de escala).
    gravimeter_type: Literal["scintrex_cg6", "zls_burris", "lacoste_romberg", "unknown"] = Field(
        "unknown",
        description="Instrumento usado en el survey. Fija el piso de ruido sigma: "
                    "CG-6=0.005 mGal, ZLS Burris=0.002, LaCoste&Romberg=0.010, unknown=0.020.",
    )
    # Sigma explícito (None = no provisto). Prioridad en el servicio:
    # noise_floor_mgal explícito > gravimeter_type > sentinel adaptivo.
    # La capa de import los puebla automáticamente desde la columna `uncertainty`
    # del CSV (mediana por estación) cuando existe.
    noise_floor_mgal: Optional[float] = Field(
        None, ge=0.0001, le=10.0,
        description="Piso de ruido sigma [mGal]. None = derivar de gravimeter_type o sentinel.",
    )
    noise_pct_v2: Optional[float] = Field(
        None, ge=0.0, le=0.10,
        description="Término relativo de sigma: max(noise_floor, noise_pct·|d|). None = 0 implícito.",
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
    # ── HITO 5 (B-05): Topografía activa ────────────────────────────────────────
    # Elevación MASL de cada sensor de gravedad (m s.n.m.), paralelo a `observations`.
    # Si se provee con la misma longitud que observations, el solver activa la máscara
    # topográfica: vóxeles sobre la superficie son "aire" y quedan excluidos.
    # None → topografía plana (comportamiento histórico, y_datum=0 para todos).
    sensor_elevations_masl: Optional[List[float]] = Field(
        default=None,
        description="Elevación MASL de cada sensor (m s.n.m.), paralelo a observations. "
                    "Activa máscara topográfica en el solver. None = terreno plano.",
    )
    # ── SPRINT 3C: TreeMesh adaptativo (malla Octree sensor-guided) ──────────────────
    # Cuando True, usa malla Octree adaptativa en lugar de grilla regular. La malla
    # se refina automáticamente alrededor de los sensores. Default False → grilla regular.
    use_treemesh: bool = Field(
        False,
        description="Usar malla Octree adaptativa (sensor-guided). Default False = grilla regular.",
    )
    treemesh_max_refine: int = Field(
        2,
        ge=0, le=4,
        description="Profundidad máxima de refinamiento en la malla Octree (0-4). Default 2.",
    )
    # ── FASE 11: Inversión Guiada Petrológica (PGI — Astic & Oldenburg 2019) ──
    # Cuando se provee, el solver ejecuta el bucle alternado PGI: después de cada
    # inversión estándar, se actualiza el modelo de referencia m_PGI asignando cada
    # celda a su litología GMM más probable (MAP), y se re-invierte con el término
    # α_PGI·||m − m_PGI||² adicional. None → comportamiento intacto (sin PGI).
    pgi_params: Optional[PgiParams] = Field(
        default=None,
        description="Parámetros PGI (GMM + α + iteraciones). None = inversión estándar sin guía petrológica.",
    )
    # ── FASE 12: Remanencia Magnética (J = J_ind + J_rem) ────────────────────────
    # Activada cuando magnetic_nt está presente Y remanence.enabled=True.
    # Con remanence=None o remanence.enabled=False: comportamiento heredado (solo inducida).
    remanence: Optional[MagneticRemanenceParams] = Field(
        default=None,
        description="Parámetros de remanencia magnética (Q, Inc_rem, Dec_rem). None = solo inducida (Fase 9A).",
    )

    @model_validator(mode="after")
    def _validate_grid_bounds(self):
        """Cross-field validation: depth must fit dentro de grilla (ny * block_size)."""
        max_depth = self.ny * self.block_size
        if self.depth > max_depth:
            raise ValueError(
                f"depth ({self.depth}m) supera máximo para grilla: "
                f"ny × block_size = {self.ny} × {self.block_size} = {max_depth}m. "
                f"Aumenta ny o block_size."
            )
        return self


class GeophysicsVoxel(BaseModel):
    """Contrato explícito de un vóxel de salida (gravimétrico, magnético o CONJUNTO).

    FASE 10 — Capa de transporte. Cada propiedad física es OPCIONAL por separado
    para que un MISMO array de vóxeles pueda serializar densidad (gravimetría),
    susceptibilidad (magnetometría) o AMBAS a la vez (inversión conjunta Fase 9C-2)
    sin disparar 422. No se calcula física aquí: solo se declara la forma del payload.

    `extra="allow"` conserva los campos enriquecidos del payload gravimétrico
    (density_proxy_index, posterior_std, doi_raw, sensitivity_proxy, …) sin tener que
    enumerarlos, de modo que el contrato es retrocompatible bit a bit con la salida
    actual del motor gravimétrico mientras admite explícitamente los campos del joint.
    """

    model_config = ConfigDict(extra="allow")

    # Schema v3.0 — campos obligatorios en Parquet pero opcionales en JSON
    run_type: Optional[str] = None        # "gravity" | "magnetic" | "joint"
    schema_version: Optional[str] = None  # "v3.0"

    ix: Optional[int] = None
    iy: Optional[int] = None
    iz: Optional[int] = None
    x_m: Optional[float] = None
    y_m: Optional[float] = None
    z_m: Optional[float] = None
    # Gravimetría: densidad absoluta y/o contraste (t/m³). Ambas opcionales.
    density: Optional[float] = None
    density_t_m3: Optional[float] = None
    density_contrast_t_m3: Optional[float] = None
    density_anomaly_score: Optional[float] = None
    # Magnetometría / joint: susceptibilidad magnética recuperada (SI, adimensional).
    susceptibility_si: Optional[float] = None
    susceptibility_score: Optional[float] = None
    # Inversión conjunta (Fase 9C-2): score estructural combinado ρ+χ normalizado.
    joint_structural_score: Optional[float] = None
    is_active: Optional[bool] = None


class GeophysicsInvertInputV2(GeophysicsInvertInput):
    """Endpoint v2 — Inversión con validaciones industriales estrictas.

    Extiende v1 añadiendo:
    - Rechazo de g_raw (datos de campo sin corregir).
    - Confirmación explícita de correcciones aplicadas.
    - Sigma de ruido configurable por tipo de gravímetro.
    - Estrategia de selección de lambda declarable.
    - density_min permite contrastes negativos (cuerpos menos densos que el host).
    """

    # ── Correcciones físicas (obligatorio declarar cuáles fueron aplicadas) ──
    corrections_applied: List[Literal["latitude", "free_air", "bouguer", "terrain"]] = Field(
        default_factory=list,
        description="Correcciones aplicadas antes de la inversión. Lista vacía solo si "
                    "gravity_type ya es complete_bouguer_anomaly o free_air_anomaly.",
    )
    gravity_type_v2: Literal["complete_bouguer_anomaly", "bouguer_anomaly", "free_air_anomaly"] = Field(
        ...,
        alias="gravity_type",
        description="Tipo de anomalía. g_raw rechazado: debe haberse aplicado al menos FAC. "
                    "bouguer_anomaly = FAC+BC sin corrección de terreno (TC).",
    )

    # ── Parámetros de ruido del gravímetro ───────────────────────────────────
    noise_floor_mgal: float = Field(
        default=0.02,
        ge=0.0001, le=1.0,
        description="Ruido de piso del gravímetro [mGal]. "
                    "Scintrex CG-6: 0.005. ZLS Burris: 0.002. LaCoste&Romberg G: 0.010. "
                    "Default 0.02 = conservador para gravímetro desconocido.",
    )
    noise_pct_v2: float = Field(
        default=0.01,
        ge=0.0, le=0.10,
        alias="noise_pct",
        description="Ruido relativo (fracción de amplitud). Típico BA corregida: 0.005-0.02.",
    )

    # ── Estrategia de regularización ─────────────────────────────────────────
    lambda_strategy: Literal["fixed", "lcurve", "chi2"] = Field(
        default="chi2",
        description="Método de selección de lambda: 'fixed' usa lambda_fixed, "
                    "'lcurve' busca la esquina de la L-curve, 'chi2' target chi²≈1.",
    )
    lambda_fixed: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Valor fijo de lambda (solo si lambda_strategy='fixed').",
    )

    # ── density_min ampliado: permite contrastes negativos ────────────────────
    density_min: float = Field(  # type: ignore[assignment]  # override parent field
        default=0.0,
        ge=-5.0, le=5.0,
        description="Contraste mínimo permitido (t/m³). Negativo: detecta cuerpos menos "
                    "densos que el host (cavidades, rocas alteradas, sal). "
                    "0 = no-negatividad (exploración mineral típica).",
    )

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def _v2_cross_validate(self):
        # density_min < density_max
        if self.density_min >= self.density_max:
            raise ValueError(
                f"density_min ({self.density_min}) debe ser menor que density_max ({self.density_max})."
            )
        # len(magnetic_nt) == len(observations) cuando ambos presentes
        if self.magnetic_nt is not None and len(self.magnetic_nt) != len(self.observations):
            raise ValueError(
                f"magnetic_nt tiene {len(self.magnetic_nt)} elementos pero observations tiene "
                f"{len(self.observations)}. Deben tener la misma longitud."
            )
        # lambda_fixed requerido cuando strategy='fixed'
        if self.lambda_strategy == "fixed" and self.lambda_fixed is None:
            raise ValueError(
                "lambda_fixed es obligatorio cuando lambda_strategy='fixed'."
            )
        return self


class GeophysicsInvertResponse(BaseModel):
    # voxels tipado como GeophysicsVoxel (con extra="allow") para que el array
    # transporte densidad y susceptibilidad SIMULTÁNEAMENTE sin romper validación.
    voxels: List[GeophysicsVoxel] = Field(default_factory=list)
    best_target: Optional[Dict[str, Any]] = None
    report: Dict[str, Any] = Field(default_factory=dict)
    misfit_error_percent: Optional[float] = None
