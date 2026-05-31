# Cierre de Madurez Semántica - Fase 6

## 1. Propósito de la Fase 6
La Fase 6 no buscó hacer más "bonita" la interfaz de TerraQuantum, sino hacerla más **honesta científica y comercialmente**. El propósito principal fue auditar y corregir la manera en que la plataforma se comunica, garantizando que el usuario entienda claramente las diferencias entre la física modelada y una interpretación especulativa o económica.

## 2. Problema que se corrigió
Antes de esta fase, TerraQuantum podía inducir a la sobrepromesa comercial debido a que mezclaba conceptos sin delimitar sus niveles de certeza. La plataforma hablaba indistintamente de:
- Anomalía gravimétrica
- Target geofísico
- Ley mineral (Grade)
- Mineral económico (Ore)
- Rajo final (UPL)
- NPV real

El uso temprano de terminología de ingeniería de minas avanzada sobre un simple modelo de densidad presentaba un enorme riesgo de falsas expectativas, asumiendo validaciones físicas (geología, perforaciones, metalurgia) que aún no existen en el flujo.

## 3. Separación oficial en tres capas
El sistema ahora opera bajo una estructura conceptualmente separada:

**Capa A — Modelo físico geofísico:**
*(Lo que la física realmente midió e invirtió)*
- `density`
- `modeled_density_index`
- `density_anomaly_score`
- `residual`
- `fitDiagnostics`
- `uncertaintyDiagnostics`
- `sensorQualityFlags`
- `observationQuality`

**Capa B — Interpretación exploratoria preliminar:**
*(Lo que infiere el equipo de geociencias de los datos físicos)*
- `anomaly_intensity`
- `target_score`
- `best_target`
- `drill_recommendation`
- `confidence_level`
- `semantic_note`

**Capa C — Escenario minero/económico conceptual:**
*(Proyección estratégica bajo el supuesto "qué pasaría si la anomalía fuera mineral")*
- conceptual pit shell
- anomalous blocks
- background blocks
- demo NPV
- conceptual ROI
- conceptual LOM
- illustrative extraction sequence

## 4. Cambios de backend en Fase 6.2
El motor del backend se actualizó para nutrir esta separación. Se agregaron nuevos campos al modelo de datos geofísicos:
- `anomaly_intensity`, `target_score`, `modeled_density_index`, `density_anomaly_score`, `avg_anomaly_intensity`, `max_target_score`, `drill_recommendation`, `confidence_level`, `semantic_note`.

Es crucial destacar que **se mantuvieron los campos legacy** (`grade`, `avg_grade`, `probability`, `recommendation`) para garantizar la total compatibilidad con proyectos antiguos (backward compatible), evitando así romper el frontend de un momento a otro.

## 5. Cambios de frontend en Fase 6.3
La interfaz de usuario del proceso de validación e inversión CSV fue reescrita para preferir orgánicamente los nuevos campos, relegando las claves legacy a un estricto rol de *fallback*.
Ejemplos de la migración en UI:
- `recommendation` → `drill_recommendation`
- `probability` → `target_score`
- `grade` → `anomaly_intensity`
- `avg_grade` → `avg_anomaly_intensity`

## 6. Cambios del visor 3D en Fase 6.4
El renderizado del gemelo digital geofísico (Visor 3D) fue purificado. Ahora las capas visuales comunican claramente:
- Densidad modelada
- Intensidad de anomalía
- Target score
- Contraste de densidad
- Modelo preliminar
- Requiere validación geológica

Se eliminaron los visuales que afirmaban falsas probabilidades del 100% basadas en la falta de datos, normalizando todo de manera que los cuerpos renderizados correspondan a métricas honestas de soporte visual y densidad anómala.

## 7. Cambios del módulo minero/económico en Fase 6.6
La sección más peligrosa comercialmente se ajustó al lenguaje conceptual. Se actualizaron las etiquetas, textos y botones en toda la UI del módulo para hablar exclusivamente de:
- Diseño minero conceptual
- Rajo conceptual
- Pit shell conceptual
- NPV de escenario demo
- ROI conceptual
- LOM conceptual
- Anomalía
- Fondo
- Resultado económico preliminar

Se incluyeron además advertencias visuales (disclaimers) explícitos en los paneles económicos.

## 8. Glosario permitido
Lista oficial de términos autorizados para su uso en la documentación y UI presente de TerraQuantum:
- modelo preliminar de densidad
- anomalía modelada
- intensidad de anomalía
- target score
- recomendación exploratoria
- rajo conceptual
- NPV demo
- LOM conceptual
- escenario conceptual
- requiere validación

## 9. Glosario prohibido
Lista de términos categóricamente restringidos salvo que se incorporen datos empíricos multi-disciplinarios validados en terreno:
- mineral confirmado
- ley real
- reserva
- recurso medido
- NPV bancable
- rajo final
- plan minero operativo
- rentabilidad garantizada
- mineral probado

## 10. Estado actual honesto de TerraQuantum
TerraQuantum hoy puede generar un flujo trazable desde CSV gravimétrico estructurado hasta modelo 3D preliminar y escenario minero conceptual.

Pero NO debe decir:
- Que ya validó un yacimiento real.
- Que tiene reservas.
- Que tiene NPV real.
- Que reemplaza perforación, geología, geoquímica, geotecnia o metalurgia.

## 11. Riesgos pendientes
A pesar de la madurez lograda, deben observarse los siguientes riesgos vigentes:
- reportes ZIP/PDF futuros podrían seguir usando claves legacy.
- MineExecutiveSummary no fue auditado todavía.
- backend aún mantiene nombres legacy por compatibilidad.
- módulo económico sigue siendo demo/conceptual.
- falta validar con datos reales de campañas.
- falta soporte Excel/Parquet/formatos propietarios.

## 12. Recomendación de siguiente fase
A continuación, tres rutas posibles y lógicas para dar inicio a la Fase 7 de madurez de la plataforma:

**Opción A:**
Fase 7 — Visualización 3D avanzada:
- cortes X/Y/Z
- filtros por densidad
- filtros por target score
- transparencia
- isosuperficies
- comparación visual entre corridas

**Opción B:**
Fase 7 — Rajo conceptual más realista:
- bench_height
- berm_width
- ramp_width
- pit_angle
- geotecnia conceptual
- limitaciones claras

**Opción C:**
Fase 7 — Reportes técnicos exportables:
- HTML/PDF geofísico
- reporte de importación CSV
- reporte de incertidumbre
- reporte minero conceptual

## 13. Conclusión
La Fase 5 hizo el sistema trazable y la Fase 6 hizo el sistema más honesto, seguro y defendible. Ahora la plataforma respeta los estándares de la industria minera, protegiéndose de afirmaciones audaces y estableciendo una base puramente científica e hipotética que deleitará a los equipos de exploraciones sin alienar a los ingenieros ni arriesgar a los inversores.
