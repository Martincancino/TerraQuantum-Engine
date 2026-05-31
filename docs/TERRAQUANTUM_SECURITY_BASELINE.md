# TerraQuantum — Security Baseline (CORE-SEC)

Versión: FASE 8.5 | Fecha: 2026-05-16
Alcance: Backend FastAPI. Autenticación JWT: pendiente CORE-INFRA-13.

---

## 1. Validación de Inputs — Tabla de Límites

| Endpoint | Campo | Tipo | Rango / Límite | Dónde se valida |
|----------|-------|------|----------------|-----------------|
| /geophysics-invert | nx, ny, nz | int | 4 ≤ x ≤ 80 | geophysics_service.py:63-66 |
| /geophysics-invert | nx×ny×nz | int | ≤ 200,000 vóxeles | geophysics_service.py:68-70 |
| /geophysics-invert | observations | list | ≥ 10 observaciones | geophysics_service.py:47-50 |
| /geophysics-invert | block_size | int | 0 < x ≤ 1000 m | geophysics_service.py:72-73 |
| /geophysics-invert | depth | int | 0 < x ≤ 5000 m | geophysics_service.py:76-77 |
| /geophysics-invert | nir | int | 0 ≤ x ≤ 100 | geophysics_service.py:87-88 |
| /geophysics-invert | fe | int | 0 ≤ x ≤ 100 | geophysics_service.py:89-90 |
| /geophysics-invert | lat | float | -90 ≤ x ≤ 90 | geophysics_service.py:37-38 |
| /geophysics-invert | lon | float | -180 ≤ x ≤ 180 | geophysics_service.py:40-41 |
| /gravity-import/* | archivo CSV | bytes | ≤ CSV_MAX_BYTES (default 10 MB) | gravity_import_api.py |

## 2. Rate Limiting

| Endpoint | Límite | Clave |
|----------|--------|-------|
| POST /geophysics-invert | 10 req/min | IP del cliente |
| POST /gravity-import/invert | 10 req/min | IP del cliente |
| POST /scenario-sweep | 5 req/min | IP del cliente |

## 3. Configuración CORS

- Origins permitidos: definidos en variable de entorno `CORS_ALLOWED_ORIGINS`
- Default seguro: solo localhost:3000 y localhost:3001
- Wildcard `"*"` explícitamente prohibido (incompatible con allow_credentials=True)
- Métodos permitidos: GET, POST, OPTIONS
- Headers permitidos: Content-Type, Accept, Authorization

## 4. Política de Datos Sensibles

### Datos confidenciales
- Archivos CSV de exploración del cliente (datos gravimétricos con coordenadas reales)
- Block models generados (modelos de densidad con coordenadas del depósito)
- Resultados de diseño de pit (geometría del recurso minero)
- Parámetros económicos ingresados (precio Cu, costos mina)

### Ubicación en disco
- `terraquantum-backend/data/projects/{project_id}/` — models, parquets, GLBs
- `terraquantum-backend/tmp/` — archivos temporales de exportación GLB

### Control de acceso actual
Sin autenticación (CORE-INFRA-13 pendiente). El backend es accesible desde cualquier
proceso que tenga red al host. En uso local/demo esto es aceptable.

### Eliminación de datos
Manual: borrar la carpeta `data/projects/{project_id}/` del servidor.
No existe endpoint de eliminación automática (pendiente CORE-INFRA-13).

## 5. Variables de Entorno Sensibles

| Variable | Sensibilidad | Notas |
|----------|-------------|-------|
| CORS_ALLOWED_ORIGINS | Baja | No es secreto, pero controla acceso CORS |
| CSV_MAX_BYTES | Baja | Parámetro operativo |
| TERRAQUANTUM_HOST | Baja | Configuración de red |
| TERRAQUANTUM_PORT | Baja | Configuración de red |

Ninguna variable actual es un secreto criptográfico. Cuando se integre LLM_API_KEY
o credenciales GEE, deben gestionarse con un secrets manager (CORE-INFRA-13).

## 6. Qué NO cubre este baseline (CORE-INFRA-13)
- Autenticación de usuarios (JWT / OAuth)
- Control de acceso por roles
- Auditoría de acceso a datos
- Encriptación de archivos en disco
- Secrets manager para API keys
