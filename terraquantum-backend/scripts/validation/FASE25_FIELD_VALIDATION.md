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

La gravimetría **sola** localiza muy bien la **posición horizontal** del cuerpo,
pero arrastra el sesgo conocido de **profundidad** (no-unicidad) y **subestima la
densidad absoluta** del cuerpo (atenuación por el depth-weighting de Li & Oldenburg).
Por eso el gate de densidad estricto (% dentro de 0.2 t/m³) lo cumple de forma
robusta el combo **gravimetría + sondajes** (el sondaje ancla la densidad in-situ),
no la gravimetría aislada — lo que coincide con la confianza del roadmap
(grav-sola 65% vs grav+sondaje 85%, grav+mag+sondaje 90%).

El harness **mide y reporta** esto por proyecto en vez de ocultarlo; ese es el
objetivo de una validación industrial.

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
