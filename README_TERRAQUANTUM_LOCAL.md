# TerraQuantum — Documentación Local de Desarrollo

> **Versión:** Fase 1 completada + Fase 3 mínima validada  
> **Última actualización:** 2026-04-28  
> **Entorno:** Desarrollo local (Windows)

---

## 1. ¿Qué es TerraQuantum?

TerraQuantum es una plataforma experimental de exploración y diseño minero que integra en un solo flujo visual:

- **Inversión geofísica gravimétrica** — procesa señales físicas del subsuelo para estimar densidades y anomalías.
- **Modelamiento 3D por vóxeles** — construye un bloque modelo tridimensional del cuerpo mineral.
- **Estimación de densidad, probabilidad y ley** — cuantifica el potencial de cada bloque.
- **Visualización de cuerpo mineral** — exporta modelos 3D en formato GLB para revisión interactiva.
- **Telemetría MWD simulada (FMS)** — simula datos de perforación en tiempo real.
- **Diseño matemático de rajo abierto** — genera el pit óptimo a partir del bloque modelo.
- **Optimización tipo Lerchs-Grossmann (LOM)** — maximiza el valor económico del rajo.
- **Planificación Life of Mine** — produce el schedule de producción y métricas por periodo.
- **Métricas económicas** — calcula NPV, tonelaje de mineral y estéril, strip ratio y más.

**Objetivo central:** conectar señales físicas del terreno con decisiones mineras visuales y económicas en un único entorno integrado.

```
Dato físico → Modelo 3D → Target de perforación → Rajo abierto → LOM → Evaluación económica
```

---

## 2. Estructura local del proyecto

```
Documentos/
├── terraquantum-web/               # Frontend Next.js
├── terraquantum-backend/           # Backend FastAPI (Python)
├── start-terraquantum.bat          # Script de inicio todo-en-uno
├── run-terraquantum-smoke-tests.bat# Suite de smoke test automatizado
└── TERRAQUANTUM_DEMO_SCRIPT.md     # Guion de demostración técnica
```

### terraquantum-web/
Aplicación Next.js que actúa como capa de visualización y control. Incluye rutas `/app/api/...` que funcionan como puente (proxy) hacia el backend FastAPI, evitando llamadas directas del navegador al backend y centralizando el control de errores.

### terraquantum-backend/
Servidor FastAPI en Python que contiene toda la lógica de cálculo científico:
- Inversión geofísica gravimétrica
- Block Model con estimación de ley y densidad
- Diseño de rajo abierto (pit shell)
- Optimización LOM (Life of Mine)
- Telemetría FMS simulada

### start-terraquantum.bat
Script de inicio unificado. Ejecuta en orden: backend FastAPI → frontend Next.js → navegador. **No requiere configuración adicional; simplemente hacer doble clic.**

### run-terraquantum-smoke-tests.bat
Suite de smoke test que valida el backend, el frontend, la Validation Suite sintética y el flujo `project_id/run_id`. Debe ejecutarse **después** de que ambos servicios estén en línea.

### TERRAQUANTUM_DEMO_SCRIPT.md
Guion narrativo de demostración técnica. Útil para presentaciones o validaciones con terceros.

---

## 3. Cómo iniciar TerraQuantum (doble clic)

### Paso a paso

1. **Doble clic en `start-terraquantum.bat`** ubicado en la carpeta `Documentos/`.
2. El script **primero inicia el backend** FastAPI en `http://127.0.0.1:8010`.
3. Luego **inicia el frontend** Next.js (espera a que el backend esté listo).
4. Finalmente **abre el navegador** automáticamente apuntando al frontend.

> ⚠️ **No cerrar las ventanas de terminal** que se abren. Cada una mantiene uno de los servicios vivo.

### Requisitos previos

- Python 3.10+ con las dependencias del backend instaladas (`requirements.txt`).
- Node.js 18+ con dependencias del frontend instaladas (`npm install`).
- Google Earth Engine (GEE) es opcional para desarrollo. Si se usa GEE real, `credenciales_gee.json` debe estar fuera del repo y en la ruta configurada (**nunca subirlo al repositorio**).

---

## 4. Puertos y URLs locales

| Servicio              | URL                        | Descripción                         |
|-----------------------|----------------------------|-------------------------------------|
| Backend FastAPI       | `http://127.0.0.1:8010`    | API principal de cálculo científico |
| Frontend Next.js      | `http://localhost:3000`    | Interfaz web (puerto por defecto)   |
| Docs Swagger (backend)| `http://127.0.0.1:8010/docs` | Documentación interactiva de la API |

---

## 5. Variables de entorno relevantes

| Variable                    | Valor por defecto              | Descripción                                    |
|-----------------------------|--------------------------------|------------------------------------------------|
| `TERRAQUANTUM_BACKEND_URL`  | `http://127.0.0.1:8010`        | URL base que el frontend usa para llamar al backend |

Esta variable se configura en el archivo `.env.local` del frontend (`terraquantum-web/.env.local`).

> ⚠️ **No subir `.env.local` al repositorio.**

---

## 6. Arquitectura del sistema

```
┌─────────────────────────────────────┐
│         Navegador / Usuario         │
└────────────────┬────────────────────┘
                 │ HTTP
┌────────────────▼────────────────────┐
│      Frontend Next.js               │
│  (terraquantum-web)                 │
│                                     │
│  app/api/*  ←─── Rutas puente       │
│  /api/system-check  (health proxy)  │
│   ↕ proxy hacia backend             │
└────────────────┬────────────────────┘
                 │ HTTP (interno)
                 │ TERRAQUANTUM_BACKEND_URL
┌────────────────▼────────────────────┐
│      Backend FastAPI                │
│  (terraquantum-backend)             │
│                                     │
│  /geophysics-invert  (geofísica)    │
│  /block-model        (block model)  │
│  /generate           (rajo/LOM/FMS) │
│  /health             (liveness)     │
│  /system-status      (health check) │
└─────────────────────────────────────┘
```

### Rol de cada capa

| Capa | Responsabilidad |
|------|-----------------|
| **Frontend** | Visualización 3D, control de parámetros, display de NPV y schedule, interfaz de usuario |
| **app/api (Next.js)** | Puente hacia el backend; evita CORS, centraliza errores, abstrae la URL del backend |
| **Backend FastAPI** | Toda la lógica científica: geofísica, block model, rajo, LOM, FMS |

---

## 7. Checklist de Smoke Test

Antes de dar por operativo el sistema, verificar cada ítem:

### Backend
- [ ] Backend online en `http://127.0.0.1:8010`
- [ ] `/health` responde `200 OK`
- [ ] `/system-status` responde `200 OK`
- [ ] `/geophysics-invert` disponible y aceptando peticiones POST
- [ ] `/block-model` disponible y aceptando peticiones GET
- [ ] `/generate` disponible y aceptando peticiones POST

### Frontend
- [ ] Frontend online en `http://localhost:3000`
- [ ] La UI carga sin errores de consola críticos
- [ ] El frontend puede conectarse al backend a través de las rutas `app/api`

### Flujo end-to-end
- [ ] Se puede generar un modelo 3D (vóxeles con densidad y ley)
- [ ] Se puede generar el diseño de mina (pit shell + rajo)
- [ ] Se visualiza el modelo GLB en el visor 3D
- [ ] Se muestran métricas de NPV y schedule de producción

### Script automatizado
Para correr el smoke test completo:
```
Doble clic en run-terraquantum-smoke-tests.bat
```
> ⚠️ Requiere que `start-terraquantum.bat` esté corriendo previamente.

El smoke test completo ejecuta:

- Backend smoke test.
- Validation Suite sintética.
- Project/run flow.
- Frontend smoke test con rutas project/run.

---

## 8. Validation Suite Sintética

El backend incluye una suite de validación que verifica la inversión gravimétrica con cuerpos geológicos de geometría y densidad **conocidos a priori**. Esto permite detectar regresiones en el motor científico sin necesidad de datos de campo reales.

### ¿Qué valida?

Cada caso construye un modelo sintético (grilla de vóxeles + cuerpo mineral con densidad y posición controladas), realiza el modelado directo (forward), ejecuta la inversión LSQR + Tikhonov y reporta métricas de recuperación:

| Métrica | Descripción |
|---------|-------------|
| `center_error` | Error de localización del centroide recuperado vs. real (metros) |
| `correlation` | Correlación lineal entre densidad verdadera e invertida |
| `top_overlap` | Fracción de vóxeles en el top 5% que coinciden entre modelo verdadero e invertido |

### Casos actuales

| Caso | Estado | center_error | correlation | top_overlap |
|------|--------|-------------|-------------|-------------|
| `synthetic_single_body` | ✅ PASS | 1.58 m | 0.3748 | 0.2982 |
| `synthetic_deep_body` | ✅ PASS | 19.04 m | 0.2746 | 0.0702 |
| `synthetic_two_bodies` | ⚠️ WARNING | 0.24 m | 0.1867 | 0.1053 |

**Resumen:** 3 casos | ✅ 2 PASS | ⚠️ 1 WARNING | ❌ 0 FAIL

### Significado de los estados

| Estado | Significado |
|--------|-------------|
| ✅ **PASS** | El caso cumple todos los criterios de precisión definidos |
| ⚠️ **WARNING** | El caso corre sin excepción pero exhibe una limitación técnica conocida (p.ej. dos cuerpos próximos generan interferencia en la inversión) |
| ❌ **FAIL** | El caso lanza una excepción o produce un error crítico que impide la inversión |

> El WARNING en `synthetic_two_bodies` es esperado: la baja correlación (0.19) refleja la dificultad de separar dos cuerpos adyacentes con la regularización actual. No es un bug; es una limitación documentada del algoritmo.

### Cómo ejecutar

```bash
cd terraquantum-backend
python scripts/validation/synthetic_cases.py
```

### Salida generada

```
tmp/validation/validation_summary.json
```

El archivo JSON contiene el detalle de cada caso: parámetros usados, métricas calculadas y estado final. Se regenera en cada ejecución.

> ⚠️ Este script **no requiere** que el backend FastAPI esté corriendo. Se ejecuta directamente con Python y es completamente independiente del servidor.

---

## 9. Persistencia project_id / run_id

TerraQuantum mantiene dos modos de persistencia para el block model generado por el backend.

### Modo legacy

Si no se envían `project_id` y `run_id`, TerraQuantum usa el archivo histórico:

```
data/block_model_001.parquet
```

Este modo se mantiene para compatibilidad con el flujo actual.

### Modo project_run

Si se envían `project_id` y `run_id`, TerraQuantum escribe los archivos de la corrida en:

```
data/projects/<project_id>/runs/<run_id>/
```

Dentro de esa carpeta se generan:

| Archivo | Contenido |
|---------|-----------|
| `block_model.parquet` | Modelo completo de bloques del run |
| `block_model_anomaly.parquet` | Subconjunto/anomalías del run |
| `inputs.json` | Parámetros principales de inversión |
| `observations.json` | Observaciones gravimétricas usadas |
| `report.json` | Reporte geofísico del run |
| `metrics.json` | Métricas económicas/mineras del diseño |
| `schedule.json` | Schedule LOM del run |

### Listado de proyectos/corridas

El backend permite listar proyectos y corridas guardadas, con flags de archivos disponibles por run.

| Capa | Ruta |
|------|------|
| Backend | `GET /project-runs` |
| Frontend proxy | `GET /api/project-runs` |

La UI en `Datos` muestra los proyectos y corridas existentes sin cargar automáticamente modelos.

### Detalle técnico de corrida

Cada corrida puede consultarse en detalle para revisar inputs, observaciones, reporte geofísico, métricas y schedule si esos archivos existen.

| Capa | Ruta |
|------|------|
| Backend | `GET /project-run-detail` |
| Frontend proxy | `GET /api/project-run-detail` |

La UI permite abrir el detalle técnico de un run y muestra “No disponible” cuando un campo no existe.

### Comparación de corridas

La comparación básica usa los JSON persistidos (`report.json`, `metrics.json`, `schedule.json`) y calcula deltas cuando los valores numéricos existen.

| Capa | Ruta |
|------|------|
| Backend | `GET /compare-runs` |
| Frontend proxy | `GET /api/compare-runs` |

La UI permite seleccionar una corrida base y comparar otra corrida contra esa base.

### Exportación ZIP de corrida

Cada run puede exportarse como paquete ZIP con los artefactos disponibles de esa corrida.

| Capa | Ruta |
|------|------|
| Backend | `GET /export-run` |
| Frontend proxy | `GET /api/export-run` |

La UI ofrece descarga ZIP por corrida cuando existe al menos un archivo del run.

### Carga de block model guardado desde la UI

Desde `Datos → Proyectos y corridas`, una corrida con `block_model.parquet` disponible puede cargarse al visor 3D. Esta acción usa el flujo project/run de `/block-model` sin cambiar el modo legacy.

### Validación

El flujo `project_id/run_id` se valida con:

```bash
cd terraquantum-backend
python scripts/validation/test_project_run_flow.py
```

Este test verifica que el modo legacy siga funcionando y que el modo `project_run` cree los archivos esperados por corrida.

---

## 10. Seguridad — Archivos que NUNCA deben subirse al repositorio

| Archivo / patrón            | Motivo                                              |
|-----------------------------|-----------------------------------------------------|
| `credenciales_gee.json`     | Credenciales de Google Earth Engine                 |
| `.env.local`                | Variables de entorno con URLs y claves privadas     |
| `*.pem`, `*.key`, `*.p12`   | Claves privadas de cualquier tipo                   |
| Tokens de API / secrets     | Cualquier token de servicio externo                 |

Verificar que el `.gitignore` de ambos proyectos incluya estos patrones antes de cualquier commit.

---

## 11. Estado actual del proyecto

### ✅ Fase 1 — Estabilización Funcional: CERRADA

- Backend FastAPI operativo con los módulos principales (geofísica, block model, rajo, LOM, FMS).
- Frontend Next.js conectado al backend vía rutas `app/api`.
- Script de inicio unificado (`start-terraquantum.bat`) funcional.
- Suite de smoke test completa disponible: backend, Validation Suite sintética, project/run flow y frontend con rutas project/run.
- Alineación de orden de memoria en la grilla de vóxeles corregida (`order="F"`).
- **Validation Suite v0.2 integrada** — suite sintética y flujo project/run en smoke test.
- **Suite de validación sintética operativa** — 3 casos, 2 PASS, 1 WARNING, 0 FAIL (`scripts/validation/synthetic_cases.py`).
- **Fase 3 mínima validada** — persistencia `project_id/run_id` disponible en versión inicial, con `inputs.json`, `observations.json`, `report.json`, `metrics.json` y `schedule.json` por run.
- **Persistencia por run funcional** — listar proyectos/corridas, ver detalle técnico, comparar corridas y exportar ZIP.
- **UI de corridas disponible** — permite listar, ver detalle, comparar, cargar modelo 3D y descargar ZIP desde `Datos`.
- **Legacy mode validado** — mantiene `data/block_model_001.parquet` para compatibilidad.
- **Project_run mode validado** — crea archivos por corrida en `data/projects/<project_id>/runs/<run_id>/`.

### ⏳ Pendiente

- Validación externa con datos reales de campo.
- Revisión de TypeScript estricto y cobertura de tests en frontend.

---

## 12. Checklist final antes de entrar a Fase 4

- `npm run lint`
- `python scripts/validation/synthetic_cases.py`
- `python scripts/validation/test_project_run_flow.py`
- `run-terraquantum-smoke-tests.bat`
- Prueba manual en UI: `Datos → proyectos/corridas → ver detalle → comparar → cargar modelo 3D → descargar ZIP`

---

## 13. Próximos pasos

| Prioridad | Tarea                                                              |
|-----------|--------------------------------------------------------------------|
| 🟡 Media  | Ampliar Validation Suite: más casos sintéticos (gradiente, ruido, cuerpos complejos) |
| 🟡 Media  | Mejorar validaciones de persistencia                               |
| 🟡 Media  | Validación externa con datos reales de campo                       |
| 🟡 Media  | Mejoras geofísicas Fase 4 (regularización avanzada, mayor resolución) |
| 🟢 Baja   | Reportes técnicos más formales                                     |
| 🟢 Baja   | Deploy/staging                                                     |

---

## Referencias internas

- [TERRAQUANTUM_DEMO_SCRIPT.md](./TERRAQUANTUM_DEMO_SCRIPT.md) — Guion completo de demostración técnica.
- `terraquantum-backend/requirements.txt` — Dependencias Python del backend.
- `terraquantum-web/package.json` — Dependencias Node.js del frontend.
- `terraquantum-backend/scripts/validation/synthetic_cases.py` — Suite de validación sintética.
- `terraquantum-backend/scripts/validation/test_project_run_flow.py` — Validación de persistencia legacy y `project_id/run_id`.
- `terraquantum-backend/tmp/validation/validation_summary.json` — Último resumen de validación (generado en ejecución).

---

*Este documento es para uso local de desarrollo. No contiene credenciales ni información sensible.*
