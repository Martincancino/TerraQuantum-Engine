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


class LithologyBound(BaseModel):
    """FASE 2.3 — Box petrofísico [min,max] de una unidad litológica.

    Se empareja (case-insensitive) contra la `lithology` de los intervalos de
    sondaje. Cada eje (density/susc) es opcional: None = sin restricción en esa
    física. Restringe las celdas de esa unidad al box vía bounds KKT por celda.
    """
    name: str = Field(..., description="Nombre de la litología, p.ej. 'magnetite'. Match case-insensitive.")
    density_min: Optional[float] = Field(default=None, ge=0.0, le=10.0, description="Densidad mínima (t/m³).")
    density_max: Optional[float] = Field(default=None, ge=0.0, le=10.0, description="Densidad máxima (t/m³).")
    susc_min: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Susceptibilidad mínima (SI).")
    susc_max: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Susceptibilidad máxima (SI).")

    @model_validator(mode="after")
    def _validate_box(self):
        if self.density_min is not None and self.density_max is not None and self.density_max < self.density_min:
            raise ValueError(f"density_max < density_min en la litología {self.name}.")
        if self.susc_min is not None and self.susc_max is not None and self.susc_max < self.susc_min:
            raise ValueError(f"susc_max < susc_min en la litología {self.name}.")
        return self


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
    # ── FASE 2.2: GMM dinámico (Astic & Oldenburg 2019, §3.2) ────────────────
    # False (default) = GMM ESTÁTICO histórico (means/stds/weights fijos; el bucle
    #   solo reasigna la clase MAP). Byte-idéntico al comportamiento de Fase 11.
    # True = GMM DINÁMICO: cada iteración re-estima la mixtura del modelo invertido
    #   vía EM MAP regularizado hacia el prior petrofísico (NIW + Dirichlet). Las
    #   componentes se adaptan al dato sin colapsar ni alejarse del prior.
    dynamic_gmm: bool = Field(
        default=False,
        description=(
            "Si True, re-estima el GMM en cada iteración (EM con prior NIW) en vez "
            "de mantenerlo fijo. Permite que las clases petrológicas se adapten al "
            "dato regularizadas hacia el prior. False = GMM estático (Fase 11)."
        ),
    )
    prior_kappa: float = Field(
        default=50.0, gt=0.0, le=1e6,
        description=(
            "Confianza del prior NIW sobre las MEDIAS del GMM dinámico (pseudo-conteos). "
            "Mayor = medias más rígidas (≈ estático). Solo aplica si dynamic_gmm=True."
        ),
    )
    prior_nu: float = Field(
        default=50.0, gt=0.0, le=1e6,
        description=(
            "Confianza del prior NIW sobre las VARIANZAS del GMM dinámico. "
            "Mayor = varianzas más rígidas. Solo aplica si dynamic_gmm=True."
        ),
    )
    weight_concentration: float = Field(
        default=1.0, ge=0.0, le=1e6,
        description=(
            "Pseudo-conteo Dirichlet sobre los PESOS del GMM dinámico (evita "
            "componentes vacías). Solo aplica si dynamic_gmm=True."
        ),
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
    # FASE 2.3: litología del intervalo. Aunque NO haya densidad/susc puntual medida,
    # conocer la unidad geológica permite restringir esas celdas al BOX petrofísico de
    # la unidad (membership dura, bounds KKT) vía la tabla lithology_bounds del input.
    lithology: Optional[str] = Field(
        default=None,
        description="Litología del intervalo (p.ej. 'granite', 'magnetite'). Habilita bounds por unidad (Fase 2.3).",
    )

    @model_validator(mode="after")
    def _require_at_least_one_property(self):
        """Evita intervalos vacíos: al menos density_t_m3, susceptibility_si o lithology."""
        if self.density_t_m3 is None and self.susceptibility_si is None and self.lithology is None:
            raise ValueError(
                "Cada intervalo de sondaje debe declarar al menos una propiedad: "
                "density_t_m3 (gravimetría), susceptibility_si (magnetometría) o lithology (unidad)."
            )
        return self


# ── FASE 20: Esquema enriquecido de sondajes (capa de carga / CSV / litología) ──
# BoreholeInterval (arriba) es el contrato MÍNIMO que consume el solver. BoreholeSample
# y BoreholeSurvey son la capa enriquecida pensada para el flujo de carga de CSV de
# sondajes: añade trazabilidad (hole_id, sample_type, comment), metadatos petrofísicos
# (lithology, density_uncertainty) y de georreferencia (crs, datum_elevation_m). Un
# BoreholeSurvey se "rebaja" a List[BoreholeInterval] vía to_intervals() para alimentar
# la inversión existente sin tocar el contrato del solver.
class BoreholeSample(BaseModel):
    """Una muestra/tramo de sondaje VERTICAL con propiedades petrofísicas medidas.

    El sondaje se asume vertical: collar en (x_m, z_m) local y el tramo cubre
    [depth_from_m, depth_to_m] en profundidad (+ hacia abajo). density_t_m3 y/o
    susceptibility_si anclan respectivamente la inversión gravimétrica/magnética;
    al menos una debe estar presente (igual semántica que BoreholeInterval).
    """
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # F11: ver CONTRATO_SERIALIZADO (schemas/response_schema.py)
    hole_id: str = Field(..., description="Identificador del sondaje, p.ej. 'BH01'.")
    x_m: float = Field(..., description="Coordenada local X del collar (m). Pozo vertical.")
    z_m: float = Field(..., description="Coordenada local Z del collar (m). Pozo vertical.")
    depth_from_m: float = Field(..., ge=0.0, description="Profundidad inicial del tramo (m, + hacia abajo).")
    depth_to_m: float = Field(..., gt=0.0, description="Profundidad final del tramo (m, + hacia abajo).")
    sample_type: Literal["core", "cuttings", "downhole_density", "downhole_susc", "other"] = Field(
        "core", description="Tipo de muestra: testigo, detritus, registro de densidad/susc en pozo, etc.",
    )
    density_t_m3: Optional[float] = Field(
        default=None, gt=0.0, le=10.0,
        description="Densidad medida del tramo (t/m³). Ancla la inversión gravimétrica.",
    )
    density_uncertainty: float = Field(
        0.15, ge=0.0, le=1.0,
        description="Incertidumbre fraccional de la densidad de muestreo (0.15 = 15%).",
    )
    lithology: Optional[str] = Field(
        default=None,
        description="Litología registrada (p.ej. 'granite', 'magnetite', 'diorite'). Alimenta priors PGI.",
    )
    susceptibility_si: Optional[float] = Field(
        default=None, ge=0.0,
        description="Susceptibilidad magnética medida (SI). Ancla la inversión magnética.",
    )
    comment: str = Field("", description="Comentario libre (trazabilidad).")

    @model_validator(mode="after")
    def _validate_sample(self):
        if self.depth_to_m <= self.depth_from_m:
            raise ValueError(
                f"depth_to_m ({self.depth_to_m}) debe ser mayor que depth_from_m "
                f"({self.depth_from_m}) en el sondaje {self.hole_id}."
            )
        if self.density_t_m3 is None and self.susceptibility_si is None and self.lithology is None:
            raise ValueError(
                f"La muestra del sondaje {self.hole_id} no aporta dato útil: declare al menos "
                "density_t_m3, susceptibility_si o lithology."
            )
        return self

    def to_interval(self) -> "BoreholeInterval":
        """Rebaja la muestra al contrato mínimo que consume el solver."""
        return BoreholeInterval(
            x_m=self.x_m,
            z_m=self.z_m,
            y_from_m=self.depth_from_m,
            y_to_m=self.depth_to_m,
            density_t_m3=self.density_t_m3,
            susceptibility_si=self.susceptibility_si,
            lithology=self.lithology,   # FASE 2.3: propaga la unidad geológica
        )


class BoreholeSurvey(BaseModel):
    """Conjunto de sondajes con metadatos de georreferencia (capa de carga FASE 20)."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)  # F11: ver CONTRATO_SERIALIZADO (schemas/response_schema.py)
    holes: List[BoreholeSample] = Field(default_factory=list, description="Muestras/tramos de sondaje.")
    crs: str = Field("local", description="Sistema de referencia, p.ej. 'UTM 19S' o 'local'.")
    datum_elevation_m: float = Field(
        0.0, description="Elevación del datum local (m s.n.m.) para referencia vertical.",
    )

    def to_intervals(self) -> List["BoreholeInterval"]:
        """Convierte el survey a la lista de intervalos que consume la inversión.

        Incluye muestras con propiedad física (density/susc, anclan el solver) Y
        muestras puramente litológicas (FASE 2.3): estas no anclan un valor pero,
        vía la tabla lithology_bounds del input, restringen sus celdas al box
        petrofísico de la unidad (membership dura). Se descartan solo las muestras
        sin densidad, sin susc y sin litología (ya rechazadas por el validador).
        """
        return [h.to_interval() for h in self.holes
                if (h.density_t_m3 is not None or h.susceptibility_si is not None
                    or h.lithology is not None)]


# ── FASE 7 (God-Tier): Geología implícita → prior petrofísico por celda ───────
class StructuralOrientation(BaseModel):
    """FASE 7 — medida estructural (buzamiento/dirección de buzamiento) que ancla el
    GRADIENTE del campo implícito φ (polo del plano). Marco local: x,z horizontales,
    y = profundidad (+ hacia abajo). Mismo convenio que BoreholeInterval."""
    x_m: float = Field(..., description="Coordenada local X de la medida (m).")
    z_m: float = Field(..., description="Coordenada local Z de la medida (m).")
    y_m: float = Field(..., description="Profundidad de la medida (m, + hacia abajo).")
    dip_deg: float = Field(..., ge=0.0, le=90.0, description="Buzamiento desde la horizontal (°).")
    azimuth_deg: float = Field(
        ..., ge=0.0, le=360.0,
        description="Dirección de buzamiento (azimut en el plano x–z desde +x hacia +z, °).",
    )


class ImplicitGeologyParams(BaseModel):
    """FASE 7.2 (God-Tier) — Prior geológico implícito desde sondajes.

    Construye un campo escalar implícito φ (HRBF Hermite, Macedo 2011) a partir de
    los contactos litológicos de los sondajes (+ orientaciones estructurales
    opcionales) y lo convierte en un MODELO DE REFERENCIA petrofísico por celda
    (m_ref, Li & Oldenburg 1999) que sesga la inversión hacia la geología conocida
    DONDE EL DATO ES AMBIGUO (el dato sigue dominando donde restringe). Es el lado
    "geología → geofísica" del bucle (Giraud GJI 2024).

    Requiere sondajes con litología (boreholes[].lithology). Solo gravimetría por
    ahora; el motor magnético ignora este campo (paridad = sub-slice futuro).
    None / enabled=False → comportamiento histórico byte-idéntico.
    """
    enabled: bool = Field(default=True, description="Activa el prior geológico implícito.")
    target_lithologies: List[str] = Field(
        ..., min_length=1,
        description="Litologías consideradas 'unidad objetivo' (φ≥0). Match case-insensitive.",
    )
    target_density_t_m3: float = Field(
        ..., gt=0.0, le=10.0,
        description="Densidad de referencia de la unidad objetivo (t/m³).",
    )
    host_density_t_m3: Optional[float] = Field(
        default=None, gt=0.0, le=10.0,
        description="Densidad de referencia de la roca caja (t/m³). None → base_density del input.",
    )
    target_std_t_m3: float = Field(
        default=0.3, gt=0.0, le=5.0,
        description="Incertidumbre del prior en la unidad objetivo (t/m³, informativa).",
    )
    host_std_t_m3: float = Field(
        default=0.5, gt=0.0, le=5.0,
        description="Incertidumbre del prior en la caja (t/m³, informativa).",
    )
    softness: float = Field(
        default=0.0, ge=0.0, le=10.0,
        description="Suavidad del contacto: 0 = escalón duro; >0 = transición sigmoide φ/softness.",
    )
    smoothing: float = Field(
        default=1e-6, ge=0.0, le=1.0,
        description="Regularización ridge del interpolante HRBF (estabiliza el sistema denso).",
    )
    orientations: Optional[List[StructuralOrientation]] = Field(
        default=None,
        description="Medidas estructurales que anclan el gradiente de φ (opcional).",
    )
    # ── FASE 14 — CÓMO entra el prior al funcional. La perilla existe porque la
    # diferencia entre las dos opciones está MEDIDA y no es de matiz.
    binding: Literal["smoothness", "smallness"] = Field(
        default="smallness",
        description=(
            "Término del funcional donde entra el prior. 'smoothness' (histórico, "
            "Fase 7.2): sólo ‖L·(m − m_ref)‖², es decir sólo la CURVATURA del "
            "contacto, mientras el smallness sigue tirando hacia base_density — "
            "MEDIDO sobre verdad conocida: EMPEORA la recuperación (PR-AUC peor en "
            "25 de 25 semillas). 'smallness' (por defecto): añade α‖m − m_ref‖², "
            "que es donde Li & Oldenburg 1999 pone el modelo de referencia — MEDIDO: "
            "mejora en las cuatro métricas y en todas las semillas, y su control con "
            "geología FALSA es el peor brazo de todos. Ver docs/06 §FASE 14."
        ),
    )
    prior_weight: float = Field(
        default=1.0, gt=0.0, le=1000.0,
        description=(
            "Peso α del prior geológico cuando binding='smallness'. MEDIDO "
            "insensible en una década (α=0,3 y α=3 dan PR-AUC 0,783 y 0,786). "
            "Ignorado con binding='smoothness'."
        ),
    )


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
    # ── Prior de profundidad (docs/05 Parte B). OFF por defecto → byte-idéntico. ──
    # Fuente MEDIDA como confiable = espectro radial de potencia (Euler satura en profundo).
    # Cuando ON: estima la profundidad de la fuente sobre el dato y PROHÍBE contraste somero
    # (ancla dura a densidad-base), reduciendo el sesgo somero de la gravedad-sola (7-18×
    # mejor en profundidad en la validación con verdad conocida). Guardado: si no hay
    # estimación utilizable, se salta sin romper.
    enable_depth_prior: bool = Field(
        False,
        description="Constreñir la profundidad con un prior del espectro radial (docs/05). "
                    "Default False = comportamiento intacto.",
    )
    depth_prior_safety_fraction: float = Field(
        0.7, gt=0.0, le=1.0,
        description="Fracción conservadora de la profundidad estimada usada como horizonte "
                    "(0.7 = prohíbe masa por encima del 70% de la profundidad estimada).",
    )
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
    # ── FASE 8.3 (God-Tier): targeting probabilístico automático ──────────────
    # Ranking 3D de blancos perforables desde el modelo invertido + σ posterior.
    # OFF por defecto (byte-idéntico). Aprovecha la σ de compute_uncertainty si está;
    # si no, cae a una σ homoscedástica del MAD (degradado pero defendible).
    compute_drill_targets: bool = Field(
        False,
        description="FASE 8.3: rankear blancos perforables (prob. de exceedencia + supresión "
                    "de no-máximos 3D) desde el modelo + σ posterior. OFF por defecto.",
    )
    drill_targets_top_n: int = Field(
        10, ge=1, le=200,
        description="FASE 8.3: nº máximo de blancos perforables a devolver.",
    )
    drill_targets_sense: str = Field(
        "positive",
        pattern="^(positive|negative)$",
        description="FASE 8.3: 'positive' = cuerpos de ALTO contraste (densidad/susc); "
                    "'negative' = bajo contraste (kimberlita/sal/cavidad).",
    )
    drill_targets_rank_by: str = Field(
        "expected_exceedance",
        pattern="^(expected_exceedance|exceedance_prob|lower_confidence_bound)$",
        description="FASE 8.3: métrica de orden del ranking de blancos.",
    )
    # ── FASE 8.1 (God-Tier): ensemble null-space (mapa de no-unicidad) ─────────
    # Genera un abanico de modelos data-consistentes por proyección al espacio nulo;
    # su σ por vóxel mide la NO-UNICIDAD (complementa la σ posterior de Hutchinson).
    # OFF por defecto (byte-idéntico). Costo extra (n_shuttles resoluciones CG).
    compute_ensemble_uncertainty: bool = Field(
        False,
        description="FASE 8.1: ensemble null-space (σ de no-unicidad por vóxel). OFF por defecto.",
    )
    ensemble_n_shuttles: int = Field(
        12, ge=2, le=64,
        description="FASE 8.1: nº de direcciones de espacio nulo del ensemble.",
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
    # ── FASE 24B Tarea 1: Norma de regularización (normas compactas) ───────────
    # "L2" (default)  = Tikhonov suave (comportamiento histórico, backward-compat).
    # "compact"       = minimum support IRLS: cuerpos nítidos y bien delimitados,
    #                   mejor error de profundidad/localización en cuerpos compactos
    #                   (Last & Kubik 1983, Portniaguine & Zhdanov 1999).
    # "mixed"         = compact smallness + suavidad edge-preserving (experimental).
    regularization_norm: Literal["L2", "compact", "mixed"] = Field(
        "L2",
        description="Norma de regularización: 'L2' (suave, default), 'compact' (minimum "
                    "support, cuerpos nítidos), 'mixed' (compact + bordes, experimental).",
    )
    # Knobs del IRLS minimum-support (solo aplican a compact/mixed; ignorados en L2).
    # Defaults = defaults del solver gravimétrico → byte-idéntico si no se fijan.
    compact_max_irls: int = Field(
        8, ge=1, le=20,
        description="Nº de reponderaciones IRLS del minimum-support (compact/mixed). "
                    "Más iteraciones → cuerpo más nítido a costa de tiempo. Default 8.",
    )
    compact_eps: float = Field(
        0.05, gt=0.0, le=1.0,
        description="Piso de foco del IRLS (t/m³) que estabiliza la reponderación "
                    "compacta. Default 0.05 (= default del solver gravimétrico).",
    )
    # ── FASE 24B Tarea 4: Topografía fraccionaria (cut-cell, anti-staircase) ────
    # OFF (default) = máscara de aire binaria. ON = celdas de borde ponderan por su
    # fracción de volumen rocoso bajo el DEM → elimina el efecto escalera en terreno
    # rugoso (AUDIT GEMINI P0). Solo aplica al motor de grilla regular (kernel fresco).
    cut_cell_topography: bool = Field(
        False,
        description="Topografía fraccionaria (cut-cell): pondera celdas de borde por su "
                    "fracción de roca bajo el DEM. OFF=máscara binaria (default).",
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
    # Convención de ejes del backend: x=Este, z=Norte, y=profundidad (+ hacia abajo).
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
    # ── FASE 20C: Magnetic Vector Inversion (MVI) — modo OPT-IN ────────────────
    # "scalar" (default) = motor magnético histórico (susceptibilidad escalar, asume
    #            magnetización inducida ∥ B0). Camino byte-idéntico, cero regresión.
    # "vector" = MVI cartesiano lineal: invierte el VECTOR M=(Mx,My,Mz) por celda y
    #            recupera la DIRECCIÓN de magnetización desde los datos (maneja
    #            remanencia oblicua, común en IOCG/magnetita chilena + Falla Atacama,
    #            SIN asumir la dirección). El observable de targeting es la amplitud
    #            |M| (susceptibilidad efectiva). Sugerido cuando sweep_q_ratio (Fase 12)
    #            detecta Q>0.5 (evidencia de remanencia). Lelièvre & Oldenburg 2009.
    magnetization_model: Literal["scalar", "vector"] = Field(
        "scalar",
        description="Modelo de magnetización magnética: 'scalar' (susceptibilidad, "
                    "default, asume inducción) o 'vector' (MVI: invierte Mx,My,Mz y "
                    "recupera la dirección desde los datos → maneja remanencia).",
    )
    # ── FASE 1.1: Régimen del kernel magnético en campo cercano ────────────────
    # 'dipole' (default, histórico): dipolo puro a toda distancia. Byte-idéntico.
    # 'prism' : prisma rectangular exacto (Bhattacharyya/Sharma) para celdas con
    #           r ≤ 4·a_eq y dipolo más lejos. El dipolo sesga la AMPLITUD en cuerpos
    #           someros (sensor a pocas anchuras de celda) porque ignora la extensión
    #           finita del vóxel; el prisma la corrige. Recomendado para targeting de
    #           cuerpos magnéticos someros (kimberlitas, IOCG aflorante).
    magnetic_near_field: Literal["dipole", "prism"] = Field(
        "dipole",
        description="Régimen del kernel magnético inducido en campo cercano: 'dipole' "
                    "(default, histórico, dipolo a toda distancia) o 'prism' (prisma "
                    "exacto Bhattacharyya/Sharma para r≤4·a_eq, corrige el sesgo de "
                    "amplitud del dipolo en cuerpos someros).",
    )
    # ── FASE 1.2: Auto-desmagnetización (self-demagnetization) ─────────────────
    # Factor desmagnetizante N de la forma de la celda. 0.0 (default) = SIN
    # desmagnetización (κ_eff = κ, comportamiento histórico). >0 activa la corrección
    # κ_eff = κ/(1+Nκ): el motor invierte la susceptibilidad APARENTE y se reporta la
    # VERDADERA. Físicamente relevante para κ≳0.1 (magnetita masiva, IOCG, BIF).
    # N≈1/3 (0.333) para celdas equidimensionales/esfera (Blakely 1995 §5). Es la
    # aproximación LOCAL (celda aislada); el solve acoplado finite-volume queda diferido.
    # Solo aplica al modo escalar inducido (no MVI, no remanencia).
    self_demag_factor: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Factor desmagnetizante N para auto-desmagnetización (self-demag). "
                    "0.0 (default) = desactivado. ~0.333 (esfera) activa la corrección "
                    "κ_eff=κ/(1+Nκ) para cuerpos de alta susceptibilidad (κ≳0.1).",
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
    cross_lambda_beta: float = Field(
        0.05, ge=0.0, le=1.0,
        description="Factor adimensional de coupling (0–1). Peso efectivo = β·‖G_scaled‖_F/‖B‖_F. Fase 9C-2.",
    )
    joint_observable_pruning: bool = Field(
        True,
        description=(
            "Joint v1.1: activar poda R-05 en inversión conjunta. "
            "True (default) = excluir vóxeles con sensibilidad cero antes de resolver → "
            "sin vóxeles muertos, mejor condicionamiento. "
            "False = comportamiento v1.0 (sin poda, Tier 0.9 — solo para diagnóstico)."
        ),
    )
    joint_continuation_mode: Literal["step", "log"] = Field(
        "log",
        description=(
            "Forma del ramp-up del peso cross-gradient en el bucle conjunto. "
            "'log' (default, Fase 0): homotopía log 0.01→1.0 en k≥2 (cumple la "
            "promesa de 'continuation exponencial' del docstring; evita el salto "
            "brusco de misfit). 'step': escalón binario histórico (0→1.0 en k≥2), "
            "conservado para rollback."
        ),
    )
    # ── FASE 3.1: Modo de acoplamiento conjunto (PGI dinámico 2D ρ-χ) ────────────
    # Generaliza el acoplamiento de la inversión conjunta más allá del cross-gradient
    # estructural. El PGI conjunto dinámico (Astic & Oldenburg 2021) acopla las dos
    # físicas por PETROFÍSICA: una mixtura Gaussiana 2D en el plano (ρ, χ) cuyas clases
    # tienen centroides correlacionados (p.ej. magnetita = alta densidad Y alta susc).
    # Cada iteración tira de ρ y χ hacia el centroide de su clase conjunta → acopla
    # valores, no solo bordes. Reutiliza los kernels NIW 2D de la Fase 2.2 vía el hook
    # extra_reg_blocks (smallness petrofísica). Default = cross_gradient (histórico).
    joint_coupling_mode: Literal["cross_gradient", "gramian", "pgi_dynamic", "pgi+cross"] = Field(
        "cross_gradient",
        description=(
            "Acoplamiento de la inversión conjunta (Fase 3). "
            "'cross_gradient' (default, histórico): Gallardo–Meju estructural con dirección "
            "unitaria ĝ (acopla bordes, escala-invariante por celda). "
            "'gramian': Gramian de Zhdanov en gradientes (‖∇m_ρ × ∇m_χ‖ con gradiente CRUDO, "
            "pondera el acoplamiento por la magnitud del contraste fijo). "
            "'pgi_dynamic': PGI conjunto dinámico (GMM 2D ρ-χ, Astic & Oldenburg 2021) — "
            "acopla por petrofísica (valores correlacionados), NO solo estructura. "
            "'pgi+cross': cross-gradient + PGI combinados."
        ),
    )
    joint_pgi_alpha: float = Field(
        0.1, ge=0.0, le=100.0,
        description=(
            "Peso del término PGI conjunto (smallness ρ/χ → centroide de su clase 2D). "
            "Mayor = más adherencia a la mixtura petrofísica. Solo aplica si "
            "joint_coupling_mode incluye PGI. Fase 3.1."
        ),
    )
    joint_pgi_n_classes: int = Field(
        3, ge=2, le=10,
        description="Número de clases del GMM 2D ρ-χ (joint PGI). Fase 3.1.",
    )
    joint_pgi_dynamic: bool = Field(
        True,
        description=(
            "Si True (default), re-estima el GMM 2D cada iteración (EM MAP con prior NIW) "
            "regularizado hacia la mixtura bootstrap del warm-up. False = GMM 2D fijo. "
            "Solo aplica si joint_coupling_mode incluye PGI. Fase 3.1."
        ),
    )
    joint_pgi_prior_strength: float = Field(
        10.0, gt=0.0, le=1e6,
        description=(
            "Confianza del prior NIW (κ0=ν0) del GMM 2D dinámico hacia la mixtura "
            "bootstrap. Bajo = sigue el dato; alto ≈ estático. Solo si joint_pgi_dynamic. "
            "Fase 3.1."
        ),
    )
    # ── FASE 3.3: Padding (condición de frontera física) en inversión conjunta ──
    # Históricamente el joint corría sobre la malla CORE pelada (a diferencia de los
    # paths grav/mag AISLADOS de producción, que sí extienden la malla con padding como
    # BC de campos potenciales). Sin padding, una fuente en el borde del survey satura
    # las celdas del core (artefacto de borde, medido en Raglan). Aquí se construye una
    # malla COMPARTIDA con padding para AMBAS físicas, con operadores de gradiente y
    # bloques de acoplamiento definidos sobre esa malla extendida; al final se reduce al
    # core para el bloque 3D de salida. Default False = comportamiento histórico (core).
    joint_padding: bool = Field(
        False,
        description=(
            "Si True, corre la inversión conjunta sobre una malla COMPARTIDA con padding "
            "geométrico (BC física de campos potenciales) y reduce al core para la salida. "
            "False (default) = malla core pelada (histórico, byte-idéntico). Fase 3.3."
        ),
    )
    joint_n_pad: int = Field(
        5, ge=1, le=20,
        description="Número de capas de padding por cara (malla conjunta). Solo si joint_padding. Fase 3.3.",
    )
    joint_pad_factor: float = Field(
        1.3, ge=1.0, le=3.0,
        description="Factor de crecimiento geométrico de las celdas de padding. Solo si joint_padding. Fase 3.3.",
    )
    joint_padding_kappa: float = Field(
        1e5, gt=0.0, le=1e9,
        description=(
            "Penalización smallness diferencial de las celdas de padding (ancla al fondo). "
            "Solo si joint_padding. Fase 3.3."
        ),
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
    # ── FASE 16: Densidad base y kappas configurables ─────────────────────────
    # Pre-sets sugeridos por litología:
    #   Granito:   density_min=2.6, density_max=3.0, base_density=2.6
    #   Magnetita: density_min=4.5, density_max=5.5, base_density=4.5
    #   Cobre:     density_min=4.3, density_max=4.8, base_density=4.3
    base_density: float = Field(
        2.6, ge=1.0, le=6.0,
        description=(
            "Densidad de fondo (host rock) en t/m³. "
            "La inversión recupera el CONTRASTE respecto a este valor. "
            "Default 2.6 = granito/roca huésped típica. Magnetita masiva: 4.5-5.0."
        ),
    )
    # ── Kappas de restricción suave (Fase 16) ────────────────────────────────
    # padding_kappa: penaliza las celdas de borde (padding) 1e5× más que el core
    # para evitar que la masa se escape al dominio de padding (auditoría R-A1).
    # anchor_kappa: fija los vóxeles con dato de sondaje (strong soft constraint).
    # Regla de ajuste: aumentar si cond(A) < 1e6, disminuir si cond(A) > 1e12.
    padding_kappa: float = Field(
        1e5, ge=1e2, le=1e8,
        description=(
            "Peso del soft constraint para celdas de padding (1e2–1e8). "
            "Valores altos evitan mass escape al borde. "
            "Aumentar si cond(A) < 1e6; disminuir si cond(A) > 1e12."
        ),
    )
    anchor_kappa: float = Field(
        1e4, ge=1e2, le=1e8,
        description=(
            "Peso del soft constraint para vóxeles anclados por sondaje (1e2–1e8). "
            "Fija la densidad de los intervalos con dato medido. "
            "NO usar > 1e6: deteriora el condicionamiento de A. "
            "Solo aplica con anchor_mode='soft'."
        ),
    )
    # ── FASE 2.1 (God-Tier): modo de anclaje de sondajes ─────────────────────
    # "soft" (default, histórico) = penalización fuerte (smallness × anchor_kappa);
    #   deja un error residual ~2% en la celda anclada (κ finito, no infinito).
    # "hard" = restricción exacta por eliminación de variables: la celda anclada se
    #   ELIMINA del sistema (su contribución pasa al RHS) y se reinyecta el valor
    #   medido del sondaje sin error. anchor_kappa se ignora en este modo.
    anchor_mode: Literal["soft", "hard"] = Field(
        "soft",
        description=(
            "Modo de anclaje por sondaje. 'soft' (default) = penalización fuerte "
            "(anchor_kappa), error residual ~2%. 'hard' = restricción exacta por "
            "eliminación de variables (celda anclada = valor medido sin error)."
        ),
    )
    # ── FASE 2.3: membership dura por litología (bounds KKT por unidad) ───────
    # Si True, las celdas atravesadas por un intervalo de sondaje con litología
    # conocida se restringen al BOX petrofísico [min,max] de su unidad (no a un
    # valor único como el anclaje): el solver con bounds lo impone vía KKT. La
    # tabla de bounds es LITHOLOGY_BOUNDS_DEFAULTS, sobreescribible con
    # lithology_bounds. Útil incluso sin densidad/susc puntual (solo la unidad).
    lithology_hard_constraint: bool = Field(
        default=False,
        description=(
            "Si True, restringe las celdas con litología conocida al box petrofísico "
            "de su unidad (membership dura, bounds KKT). False = sin restricción por unidad."
        ),
    )
    lithology_bounds: Optional[List["LithologyBound"]] = Field(
        default=None,
        description=(
            "Tabla litología→box [min,max] que sobreescribe/extiende los defaults. "
            "Solo aplica si lithology_hard_constraint=True."
        ),
    )
    # auto_kappa: True → el solver ajusta kappas automáticamente si cond(A) > 1e12.
    auto_kappa: bool = Field(
        True,
        description=(
            "Ajustar kappas automáticamente si el número de condición estimado de A > 1e12. "
            "True (default) = protección automática. "
            "False = usar padding_kappa / anchor_kappa exactamente como declarados."
        ),
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
    # ── FASE 7.2 (God-Tier): Prior geológico implícito (φ HRBF → m_ref) ──────────
    # Cuando se provee y enabled=True, se construye un campo implícito φ desde los
    # contactos litológicos de los sondajes y se inyecta como modelo de referencia
    # petrofísico por celda (m_ref). Sesga la inversión hacia la geología donde el
    # dato es ambiguo. Solo gravimetría por ahora. None → comportamiento histórico.
    implicit_geology: Optional[ImplicitGeologyParams] = Field(
        default=None,
        description="Prior geológico implícito (FASE 7.2). None = inversión sin guía geológica.",
    )
    # ── FASE 12: Remanencia Magnética (J = J_ind + J_rem) ────────────────────────
    # Activada cuando magnetic_nt está presente Y remanence.enabled=True.
    # Con remanence=None o remanence.enabled=False: comportamiento heredado (solo inducida).
    remanence: Optional[MagneticRemanenceParams] = Field(
        default=None,
        description="Parámetros de remanencia magnética (Q, Inc_rem, Dec_rem). None = solo inducida (Fase 9A).",
    )
    # ── FASE 18: Robust sigma (MAD outlier detection) ─────────────────────────
    # Cuando True, el estimador de sigma detecta outliers por MAD (|g_i - median| > 3·MAD)
    # y los downpesa 10× en lugar de dilatar sigma globalmente. Solo activo en el path
    # sentinel adaptivo (noise_floor==0.02 y noise_pct==0.02).
    robust_sigma: bool = Field(
        True,
        description=(
            "Use MAD-based outlier detection in sigma weighting (FASE 18). "
            "Downweights sensors where |g_i - median(g)| > 3·MAD by 10× "
            "to avoid global sigma dilation from single anomalous readings. "
            "Only active in adaptive sentinel path (no explicit noise_floor/gravimeter_type)."
        ),
    )
    # ── FASE 5.2 (God-Tier): Export de volumen volumétrico co-registrado ────────
    # Cuando True, tras escribir el block model la inversión emite un volumen ESPARSO
    # co-registrado (.npz siempre; .vdb si pyopenvdb está instalado) que une densidad,
    # susceptibilidad, incertidumbre y score sobre un solo retículo ix/iy/iz. Si en el
    # run dir ya existe el parquet magnético (joint), se co-registran ambas físicas.
    # Non-fatal y aditivo: OFF (default) = comportamiento histórico byte-idéntico.
    export_coregistered_volume: bool = Field(
        False,
        description="Exportar volumen volumétrico co-registrado (.npz + .vdb opcional) "
                    "tras la inversión. Une densidad/susc/incertidumbre/score sobre un "
                    "retículo compartido. OFF (default) = sin export.",
    )
    # ── FASE 5.3 (God-Tier): Export del modelo categórico comprimido (SVDAG) ────
    # Cuando True, deriva del volumen co-registrado un modelo CATEGÓRICO (binning de
    # cuantiles de la densidad) y lo comprime en un Sparse Voxel DAG (.npz). Implica
    # construir el volumen co-registrado aunque export_coregistered_volume sea False.
    # Non-fatal y aditivo: OFF (default) = comportamiento histórico byte-idéntico.
    export_categorical_svdag: bool = Field(
        False,
        description="Exportar modelo categórico comprimido (Sparse Voxel DAG, .npz) "
                    "derivado del volumen co-registrado por binning de densidad. "
                    "OFF (default) = sin export.",
    )

    @model_validator(mode="after")
    def _validate_grid_bounds(self):
        """Sanidad de profundidad, bounds de densidad y kappas.

        NO se rechaza depth > ny*block_size: a escala regional (Bushveld,
        250 km) es legítimo declarar la extensión física objetivo aunque la
        discretización vertical sea gruesa — esa es una decisión del usuario,
        no un error. El warning de discretización gruesa lo emite el servicio
        (no este validador) para no mutar ni bloquear el input en silencio.
        """
        if self.depth > 500_000:
            raise ValueError(
                f"depth ({self.depth}m) supera el cap de sanidad de 500 km. "
                "Verificar unidades (se esperan metros)."
            )
        if self.density_min >= self.density_max:
            raise ValueError(
                f"density_min ({self.density_min}) debe ser menor que density_max ({self.density_max})."
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


# ── FASE 8.2 (God-Tier): Live Update local (Woodbury / sub-octree) ───────────
# Endpoint STATELESS sobre malla CORE: el cliente envía los params de la inversión
# original (que ya incluyen las observations existentes), el modelo previo (core, el
# que devolvió la inversión) y el dato/sondaje nuevo (o la sub-región). El servidor
# reconstruye el forward/mesh core y aplica la actualización LINEAL local sin re-correr
# el pipeline. No mantiene estado servidor.
class LiveUpdateObservation(BaseModel):
    x_m: float = Field(..., description="Coordenada local X del sensor nuevo (m).")
    y_m: float = Field(..., description="Altura/profundidad del sensor nuevo (m).")
    z_m: float = Field(..., description="Coordenada local Z del sensor nuevo (m).")
    g: float = Field(..., description="Valor observado nuevo (anomalía, m/s² SI).")


class GeophysicsLiveUpdateRequest(BaseModel):
    params: GeophysicsInvertInput = Field(
        ..., description="Params de la inversión original (incluyen las observations existentes).",
    )
    prior_model: List[float] = Field(
        ..., description="Modelo previo en malla CORE (densidad, longitud nx*ny*nz).",
    )
    mode: str = Field(
        "woodbury",
        pattern="^(woodbury|suboctree)$",
        description="'woodbury' = update global rango-k (dato nuevo); 'suboctree' = "
                    "re-solve local de una sub-región con el fondo congelado.",
    )
    new_observations: Optional[List[LiveUpdateObservation]] = Field(
        default=None,
        description="Observaciones nuevas. Obligatorio en 'woodbury'; opcional en 'suboctree'.",
    )
    region_center: Optional[List[float]] = Field(
        default=None, description="[x,y,z] centro de la sub-región (modo 'suboctree').",
    )
    region_radius: Optional[float] = Field(
        default=None, gt=0.0, description="Radio de la sub-región en m (modo 'suboctree').",
    )
    anchor_strength: float = Field(
        1.0, ge=0.0, description="Fuerza del ancla al modelo previo en 'suboctree'.",
    )


class GeophysicsLiveUpdateResponse(BaseModel):
    mode: str
    model: List[float] = Field(default_factory=list, description="Modelo actualizado (core).")
    n_voxels: int
    update_norm: float
    # Woodbury
    capacitance_cond: Optional[float] = None
    new_data_misfit_before: Optional[float] = None
    new_data_misfit_after: Optional[float] = None
    n_new: Optional[int] = None
    # Sub-octree
    region_size: Optional[int] = None
    region_misfit_before: Optional[float] = None
    region_misfit_after: Optional[float] = None
    note: str = ""
