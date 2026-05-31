# Auditoría Conceptual de Separación de Modelos (Fase 6.1) - TerraQuantum

## 1. Propósito de Fase 6.1
El propósito de esta fase es establecer una separación semántica y arquitectónica clara entre el **modelo físico geofísico** (derivado puramente de los cálculos matemáticos de inversión gravimétrica) y la **interpretación minera preliminar** (inferencias exploratorias derivadas del modelo). El objetivo es salvaguardar el rigor científico de TerraQuantum, impidiendo que la plataforma sugiera certezas geológicas que la gravimetría por sí sola no puede confirmar.

## 2. Estado Actual del Flujo
Actualmente, el sistema ejecuta de forma inmaculada la matemática de inversión, pero agrupa las respuestas bajo estructuras que pueden inducir a confusión semántica:

```text
CSV Gravity v1
  ↓
observations (Validación estricta de formato y unidades)
  ↓
inversión (Proceso matemático ForTran/C)
  ↓
voxels (Resultados 3D en malla)
  ↓
report (Métricas combinadas físicas y mineras)
  ↓
best_target (Identificador agnóstico que mezcla densidad con "grade")
  ↓
visualización 3D (Renderizado de la anomalía)
```

## 3. Qué es Físicamente Válido desde Gravimetría
A partir de mediciones gravimétricas de alta precisión, la inversión matemática está capacitada y legitimada para inferir:
*   **Anomalías de densidad**: Distribución espacial volumétrica.
*   **Contrastes relativos**: Diferenciales de densidad respecto a la roca huésped.
*   **Posibles cuerpos de distinta densidad**: Morfología teórica del causante de la anomalía.
*   **Residuales entre observado y modelado**: Mapa de error o ajuste.
*   **Incertidumbre**: Variabilidad o falta de sensibilidad en ciertas profundidades.
*   **Zonas objetivo para investigar**: Coordenadas espaciales de interés máximo (targets ciegos).

## 4. Qué NO debe afirmarse desde Gravimetría Sola
La gravimetría es un método de campo potencial y, por tanto, presenta ambigüedad inherente. **Bajo ningún escenario** TerraQuantum debe afirmar o sugerir desde la inversión gravimétrica:
*   **Mineral confirmado**: La densidad no define la mineralogía.
*   **Ley real confirmada ("grade")**: Imposible de inferir sin geoquímica o perforación.
*   **Reserva mineral**: Término estrictamente reservado para recursos económicamente viables tras modelamiento intensivo (NI 43-101 / JORC).
*   **Rentabilidad económica**: Depende de metalurgia, opex, capex, no de la anomalía.
*   **Tipo exacto de mena sin soporte adicional**: Un cuerpo denso puede ser magnetita estéril o sulfuros masivos económicos.
*   **Perforación obligatoria**: La recomendación es un hito de exploración probabilístico, no un mandato definitivo.

## 5. Separación Conceptual Propuesta

A continuación se propone el cisma semántico para los atributos de salida:

| Modelo físico geofísico (Físico empírico) | Interpretación minera preliminar (Inferencia) |
| :--- | :--- |
| `density` | `target_score` |
| `density_contrast` | `drill_recommendation` |
| `modeled_gravity` | `confidence_level` |
| `residual` | `evidence_summary` |
| `fit_quality` | `recommended_next_steps` |
| `uncertainty_level` | `economic_placeholder` |
| `sensor_quality_flags` | |
| `anomaly_score` | |

## 6. Auditoría de Campos Actuales

Se revisan conceptualmente los campos empleados en la salida JSON del Reporte/Voxel:

*   `density`: **Físico aceptable** (Siempre y cuando refiera a densidad relativa o modelada).
*   `grade`: **Requiere renombrado**. Induce fuertemente a pensar en "Ley real" de cobre/oro.
*   `probability`: **Pendiente de validación**. ¿Probabilidad matemática de ajuste o probabilidad de mineral? Sugiere renombrado a `anomaly_intensity` o requerir disclaimer.
*   `recommendation`: **Interpretación preliminar aceptable** (Útil para flujo de trabajo si indica "Sugerencia exploratoria").
*   `best_target`: **Interpretación preliminar aceptable** (Término estándar en exploración para anomalías destacadas).
*   `risk_level`: **Requiere disclaimer**. Debe aclarar que es riesgo exploratorio/inversión, no geotécnico ni financiero.
*   `anomaly_score`: **Físico aceptable**.
*   `avg_grade`: **Requiere renombrado**. Extremadamente engañoso. Reemplazar por índice gravimétrico.
*   `estimated_total_tonnage`: **Requiere disclaimer** / **Pendiente de validación**. Debe aclararse como "Tonelaje anómalo teórico", no tonelaje de mena.

## 7. Problemas de Naming Detectados y Alternativas
La herencia de maquetas anteriores y scripts demo inyectó léxico de planificación minera (ej. `grade`, `avg_grade`) en el corazón de la geofísica.

**Alternativas propuestas para reemplazar "Ley" (Grade):**
1.  `geophysical_score`: Puntaje generalizador del contraste.
2.  `anomaly_intensity`: Índice normalizado de cuán atípica es la celda.
3.  `target_score`: Índice de favorabilidad para interceptar el cuerpo.
4.  `modeled_density_index`: Expresión directa de la física sin matiz de "mineral".
5.  `density_anomaly_score`: Focalizado en el contraste neto.

## 8. Propuesta de Estructura Futura del Resultado

Para futuras refactorizaciones de las respuestas de API de inversión, se sugiere transicionar el JSON hacia esta topología modular:

```json
{
  "physicalModel": {
    "voxels": [...],
    "volume_m3": 5000000,
    "max_density_contrast": 0.8
  },
  "fitDiagnostics": {
    "rmse": 0.05,
    "max_residual": 0.12,
    "fit_level": "High"
  },
  "uncertaintyDiagnostics": {
    "overall_uncertainty": "Moderate",
    "depth_decay_factor": 0.9
  },
  "targetingInterpretation": {
    "best_target_coords": {"x": 100, "y": 250, "z": -150},
    "target_score": 0.88,
    "drill_recommendation": "Perforar anomalía central",
    "confidence_level": "Medium"
  },
  "auditTrail": {
    "source_file": "gravity.csv",
    "schema_version": "v1"
  }
}
```

## 9. Propuesta de Visualización 3D
El frontend debe ofrecer en el visor capas separadas que reflejen esta dicotomía conceptual:
*   `density_model`: Grilla base continua de densidades.
*   `anomaly_model`: Filtrado de celdas que superan un contraste (isosuperficie).
*   `uncertainty_overlay`: Cascarón visual o mapa de opacidad penalizando la base del modelo.
*   `residual_sensors`: Marcadores en el plano XY (superficie) mostrando el desajuste estación por estación.
*   `target_candidates`: Puntos o esferas resaltadas (ej. morado/rojo) sugiriendo cuellos de perforación exploratoria.

## 10. Reglas de UI (Textos y Etiquetas)
El frontend debe imponer un glosario estrictamente controlado.

**Textos Permitidos (Semántica Segura):**
*   “Modelo preliminar de densidad”
*   “Anomalía modelada”
*   “Target preliminar”
*   “Requiere validación”
*   “Recomendación exploratoria”
*   "Contraste relativo"

**Textos Prohibidos (Semántica Engañosa):**
*   “Mineral confirmado”
*   “Ley real” o "Grade"
*   “Reserva”
*   “Yacimiento confirmado”
*   “Perforación garantizada”

## 11. Criterio para Fase 6.2
El siguiente paso natural es la ejecución progresiva de la arquitectura planteada en este documento.

**Fase 6.2 — Renombrar/estructurar salida sin romper compatibilidad:**
1.  Mantener los campos *legacy* actuales (ej. `grade`, `avg_grade`) en el Pydantic Schema de respuesta para evitar que los visualizadores de demo/mock en Frontend colapsen de un plumazo.
2.  Agregar campos paralelos nuevos y limpios (ej. `anomaly_intensity`, `target_score`) derivados de la misma matriz.
3.  Actualizar el frontend incrementalmente (en componentes como `GravityCsvPreviewPanel` y `Exploration3DView`) para que lean de los nuevos campos y utilicen el naming correcto.
4.  Asegurar que los tests existentes de validación local y de integración en Python no se rompan por faltantes de Keys JSON.

## 12. Riesgos
*   **Romper compatibilidad frontend/backend**: Reemplazar campos de golpe generará excepciones de rendering TypeError en el canvas de React/Three.js.
*   **Sobreinterpretar gravimetría**: Que los algoritmos algorítmicos generen "recomendaciones" muy asertivas que el usuario confunda con geología confirmada.
*   **Confundir demo con dato real**: Mezclar mallas sintéticas hardcodeadas de los mocks legacy con los JSON provenientes del CSV validado.
*   **Usar “grade”**: Dejar viva la variable `grade` en la lógica de Fortran/Python puede provocar que a futuro se sume inadvertidamente a métricas de "LOM" o FMS sin control.

## 13. Conclusión
La Fase 5 entregó el músculo logístico y la robustez de ingesta para datos reales; TerraQuantum ahora lee, invierte y persiste datos crudos con fiabilidad demostrable. La Fase 6 debe orientarse a la madurez científica: hacer que el modelo 3D sea más honesto con las limitaciones físicas, visualmente claro para el operador exploratorio, y conceptualmente aislado de promesas mineras prematuras. La estructura propuesta aísla el motor matemático empírico de las conjeturas de prospectividad.
