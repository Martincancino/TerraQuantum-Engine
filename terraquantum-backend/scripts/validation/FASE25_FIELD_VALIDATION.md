# Fase 25 — Validación de Campo (Field Validation)

Entregable de **ingeniería** de la Fase 25: un harness reproducible que valida el
motor de inversión contra sondajes y produce las fichas de caso (case studies),
la tabla resumen y el veredicto GO/NO-GO que pide el roadmap.

> Las partes de **negocio** de la Fase 25 (firmar 5 consultoras Tier-C chilenas,
> recolectar surveys reales nuevos) son acciones del mundo real y NO son código.
> Este harness es la maquinaria que procesa cada proyecto real cuando llega.

## Componentes

| Pieza | Archivo | Rol |
|-------|---------|-----|
| Métricas de validación | `services/field_validation_service.py` | MAE/RMSE/%dentro, error de localización, ficha de caso, agregación GO/NO-GO, tabla Markdown |
| Harness reproducible | `scripts/validation/field_validation_harness.py` | corre proyectos end-to-end (ruteo → inversión → validación → reporte) |
| Tests | `tests/test_field_validation.py` | 18 tests del servicio (deterministas, sin inversión completa) |

## Métricas (roadmap Fase 25)

1. **Densidad vs sondaje** (`validate_against_boreholes`): MAE, RMSE, sesgo y
   fracción de intervalos dentro de 0.2 / 0.3 / 0.5 t/m³. Reutiliza el mapeo
   profundidad→vóxel del solver (`borehole_service.map_interval_to_voxels`).
2. **Localización del cuerpo** (`estimate_location_error`): error HORIZONTAL
   (observable robusto de la gravimetría) y de PROFUNDIDAD del centro de masa del
   cuerpo recuperado (umbral fuerte >50% del máximo, convención de los tests de
   validación analítica del motor).
3. **Profundidad del pico/centroide** (`estimate_depth_error`): diagnóstico
   complementario.

## Gate GO/NO-GO

- **Densidad:** ≥75% de los intervalos de sondaje dentro de **0.3 t/m³**
  (`GATE_THRESHOLD_T_M3=0.3`, `GATE_MIN_FRACTION=0.75`).
- **Confianza predictiva:** correlación (confianza ↔ fracción dentro de umbral) > 0
  a través de los proyectos.

## Hallazgo físico central (honesto)

La gravimetría **sola** localiza muy bien la **posición horizontal** del cuerpo
(error 0.3–4.2 m, sub-celda), pero arrastra el sesgo conocido de **profundidad**
(no-unicidad, 16–32 m) y **subestima la densidad absoluta** del cuerpo (atenuación
por el depth-weighting de Li & Oldenburg: el sondaje del cuerpo mide 3.4 t/m³ y la
inversión predice ~2.63).

## PASO 2 — Resultado MEDIDO del combo grav+sondajes (2026-06-19)

> **La tesis central "grav+sondajes baja la profundidad a <10–15 m y sube el gate de
> densidad a >75%" se MIDIÓ por primera vez (no solo se afirmó). Resultado: NO_GO con
> el motor actual.** Se reporta la verdad medida, sin tunear el test.

`run_combo_comparison()` invierte los MISMOS proyectos sintéticos en dos modos
(grav-sola vs grav+sondajes con anclaje Fase 8/20) bajo anti-inverse-crime:

| Proyecto | y_real | prof_err SOLA | prof_err COMBO | %<0.3 SOLA | %<0.3 COMBO |
|----------|--------|---------------|----------------|------------|-------------|
| Synthetic-Shallow | 150 m | 16.3 m | 16.8 m | 50% | 50% |
| Synthetic-Deep    | 200 m | 32.3 m | 33.9 m | 50% | 50% |
| Synthetic-Noisy   | 150 m | 20.9 m | 13.4 m | 50% | 50% |

Mediana profundidad: SOLA 20.9 m → COMBO 16.8 m (objetivo <15 m → **NO cumple**).
Gate densidad combo: **NO cumple** (sigue 50%). **VEREDICTO: NO_GO.**

### Causa raíz (confirmada por los residuales, no asumida)

El anclaje de sondajes pone el *target* de smallness en unidades de **contraste físico**
(0.8 t/m³) pero lo aplica en el **espacio depth-weighted m̃**. Como densidad = base +
`Wz_inv`·m̃ y `Wz_inv` ≈ 0.02–0.03 a esa profundidad, el anclaje solo mueve la densidad
absoluta ~`Wz_inv`·contraste ≈ **+0.02 t/m³** en lugar de +0.8. Evidencia directa:

- Sondaje de **roca caja** (contraste objetivo 0): COMBO predice 2.6000000000 (residual
  ~1e-11) → el anclaje es exacto cuando el objetivo es 0 en ambos espacios.
- Sondaje de **cuerpo** (medido 3.4): SOLA 2.637 → COMBO 2.622 (residual −0.78) → el
  anclaje **no levanta** la densidad del cuerpo (incluso baja un pelo).

Esto cuantifica end-to-end, por primera vez, la limitación que la memoria Fase 20 ya
anticipaba ("la respuesta en densidad ABSOLUTA es ~2% del contraste anclado").

### Implicación / recomendación

El combo grav+sondajes **NO de-riesga la métrica de densidad mientras el target de
anclaje no se exprese en espacio m̃** (es decir, `target = Wz · contraste_medido` en las
celdas ancladas, para que la densidad recuperada iguale el valor in-situ). Ese cambio
toca física de **Alto Riesgo** (`gravimetry.py`) y existen tests Fase 20 que validan la
dirección/monotonicidad del anclaje actual, no su magnitud → requiere su propia fase
revisada de física (NO se hizo aquí para no tunear el resultado ni romper lo validado).
La gravimetría sola sigue siendo excelente para **geometría/posición horizontal**; la
**densidad absoluta** necesita el anclaje corregido (o un sondaje que el modelo respete
en magnitud, hoy no garantizado).

El harness **mide y reporta** esto por proyecto en vez de ocultarlo; ese es el objetivo
de una validación industrial.

## Cómo validar un proyecto REAL chileno

1. Construir un `FieldProject` desde el CSV de gravimetría (+ magnetometría +
   sondajes). Para datos reales, reemplazar el cuerpo sintético por la inversión
   del CSV real vía el endpoint `/v2/gravity-import/invert-with-corrections` y leer
   el `block_model` resultante.
2. Cargar los sondajes reales (`borehole_service.parse_borehole_csv`) →
   `to_intervals()`.
3. Llamar `validate_against_boreholes(...)` + `estimate_location_error(...)`.
4. Ensamblar un `CaseStudy`, agregar con `aggregate_case_studies(...)` y renderizar
   con `render_case_study_table(...)`.

## Ejecutar la demostración sintética

```bash
cd terraquantum-backend
python scripts/validation/field_validation_harness.py
# → imprime la tabla + localización y escribe field_validation_report.json
```

La demostración usa cuerpos sintéticos con **ground-truth conocido** y protocolo
**anti-inverse-crime** (malla forward fina ≠ malla de inversión), de modo que el
error medido es el error REAL del motor contra una verdad independiente.
