# Auditoría Semántica: Módulo Minero y Económico

## 1. Propósito
Esta auditoría tiene como propósito revisar y evaluar la transición semántica y técnica desde la generación de una anomalía geofísica (modelo gravimétrico) hacia el diseño minero conceptual en TerraQuantum. Busca identificar áreas donde el vocabulario técnico de la plataforma podría inducir a errores de interpretación sobre el grado de certeza geológica y viabilidad económica del yacimiento.

## 2. Problema Central
El flujo actual permite generar diseños de mina, evaluar parámetros económicos y simular extracciones. El problema central radica en que un modelo gravimétrico, por más riguroso que sea, **no equivale automáticamente a un modelo de recursos, reservas, leyes mineralógicas ni mucho menos a mineral económico probado**. Continuar usando terminología propia de etapas avanzadas de factibilidad minera sobre datos puramente exploratorios y geofísicos expone a la plataforma a riesgos de sobrepromesa y confusión conceptual.

## 3. Estado Actual Probable
A nivel de código (backend y frontend) en los módulos de diseño y evaluación, TerraQuantum actualmente es susceptible de utilizar terminología de ingeniería de minas definitiva sobre modelos geofísicos tempranos. Es muy probable encontrar el uso de:
- `grade`
- `avg_grade`
- `tonnage`
- `ore`
- `waste`
- `NPV`
- `ROI`
- `LOM` (Life of Mine)
- `strip ratio`

## 4. Qué Puede Ser Válido Como Demo Conceptual
Para mantener el valor del módulo minero como herramienta de visualización y planificación estratégica sin incurrir en deshonestidad científica, se consideran válidos los siguientes enfoques:
- **Escenario económico exploratorio:** Evaluaciones paramétricas que muestran "qué pasaría si" la anomalía fuese mineral.
- **Rajo conceptual:** Diseños geométricos basados puramente en distribución de densidad.
- **Ranking preliminar de bloques:** Ordenamiento de áreas anómalas por potencial relativo.
- **Sensibilidad económica demo:** Pruebas de estrés de costos sobre la anomalía.
- **LOM conceptual:** Secuenciamiento ilustrativo para entender la profundidad de la anomalía.

## 5. Qué NO Debe Afirmarse
Bajo ninguna circunstancia la plataforma debe sugerir certeza sobre las siguientes métricas en base exclusiva a datos gravimétricos:
- Reservas
- Mineral probado o probable
- Ley real (Grade)
- NPV real bancable
- Rajo final / Ultimate Pit Limit (UPL) definitivo
- Plan minero operativo
- Rentabilidad garantizada

## 6. Tabla de Campos Conflictivos

| Campo Actual | Riesgo Semántico | Alternativa Recomendada | Acción Futura |
| :--- | :--- | :--- | :--- |
| `grade` | Sugiere concentración confirmada por muestreo físico. | `anomaly_intensity` | Migrar frontend a nueva variable, fallback a legacy. |
| `avg_grade` | Sugiere ley media del yacimiento validada. | `avg_anomaly_intensity` | Ajustar UI y reportes conceptuales. |
| `ore_tonnage` | "Ore" implica viabilidad económica probada. | `anomalous_tonnage` | Reemplazar en cálculos de masas anómalas. |
| `waste_tonnage`| "Waste" implica estéril operacional. | `background_tonnage` | Renombrar en métricas volumétricas. |
| `NPV` | Sugiere valor financiero auditable y transable. | `scenario_npv` o `demo_npv` | Cambiar etiquetas UI a "NPV de Escenario Demo". |
| `ROI` | Sugiere retorno garantizado. | `demo_roi` | Re-etiquetar a "ROI Conceptual". |
| `revenue` | Ingresos financieros proyectados reales. | `conceptual_revenue` | Etiquetar como ingreso bajo escenario hipotético. |
| `cost` | Sugiere Capex/Opex de ingeniería de detalle. | `demo_cost` | Añadir disclaimer de "Costos Paramétricos". |
| `pit shell` | Asume diseño geotécnico e hidrogeológico final. | `conceptual_pit_shell` | Renombrar UI a "Rajo Conceptual". |
| `schedule` | Sugiere secuenciamiento a corto/largo plazo validado. | `extraction_sequence_demo`| Renombrar a "Secuencia Ilustrativa". |
| `LOM` | Vida de mina basada en reservas probadas. | `conceptual_lom` | Cambiar a "LOM Conceptual". |

## 7. Propuesta de Lenguaje Seguro
Para las próximas actualizaciones de la interfaz visual del módulo minero, se recomienda adoptar las siguientes etiquetas y descripciones:
- “Escenario conceptual”
- “Modelo económico preliminar”
- “Ranking de bloques anómalos”
- “Tonnage anómalo modelado”
- “NPV de escenario demo”
- “Rajo conceptual”
- “LOM conceptual”
- **Disclaimer Obligatorio:** “No apto para decisión económica sin recursos/reservas validadas mediante perforación y QA/QC.”

## 8. Propuesta Técnica Fase 6.6
Se recomienda iniciar una **Fase 6.6** orientada al refactor semántico del módulo de diseño de mina y economía. Los pasos sugeridos son:
1. **Mantener campos legacy** en el backend para evitar romper vistas antiguas.
2. **Agregar `conceptual_economic_model`** como estructura de datos que envuelva los resultados de evaluación.
3. **Agregar `economic_semantic_note`** en los reportes del backend para propagar disclaimers.
4. **Actualizar UI minera** con los nuevos *disclaimers* y etiquetas de lenguaje seguro propuestos.
5. **Separar `geophysical_block_model` de `economic_demo_model`** para dejar explícito que el primero alimenta al segundo bajo supuestos hipotéticos.

## 9. Riesgos
De no implementarse estas medidas, TerraQuantum enfrenta:
- **Sobrepromesa comercial:** Riesgo legal de sugerir viabilidad minera irreal.
- **Mezclar anomalía con mineral:** Riesgo científico de diluir la diferencia entre densidad gravimétrica y mineralogía económica.
- **Uso de NPV demo como NPV real:** Clientes o inversores tomando decisiones financieras con modelos ilustrativos.
- **Mostrar rajo como diseño final:** Ignorando cruciales variables geotécnicas.
- **Confundir público no técnico:** Inversores asumiendo que el output gráfico es un plan de mina operable.

## 10. Conclusión
TerraQuantum posee un enorme valor integrando el modelamiento geofísico directo con un motor minero/económico como **demostrador conceptual**. Sin embargo, es mandatorio que la plataforma etiquete y aclare que estas simulaciones son hipotéticas. Solo cuando la plataforma logre integrar datos reales de perforación, geoquímica, geotecnia, metalurgia, restricciones ambientales y costos operativos locales, podrá hablar legítimamente de mineral, reservas y NPV operable.
