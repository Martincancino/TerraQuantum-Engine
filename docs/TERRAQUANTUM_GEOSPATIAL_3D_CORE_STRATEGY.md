# TerraQuantum V2 — Estrategia Geoespacial 3D

## Principio central
TerraQuantum aumenta la probabilidad de acierto técnico en exploración
minera cruzando evidencia independiente de múltiples fuentes.

No lo hace por verse bonito, sino porque cruza:
- Gravimetría (evidencia del subsuelo)
- Satélite (evidencia superficial)
- Terreno real (contexto geoespacial)
- MS-x focusing (focalización no-lineal del subsuelo)
- Geometría y densidad del cuerpo modelado

Mientras más fuentes independientes coincidan, más confiable
es la interpretación exploratoria.

## Núcleo del sistema: Modelo 3D Geoespacial
El modelo 3D volumétrico es el producto principal de TerraQuantum.
No es una visualización decorativa — es el resultado del análisis.

Debe mostrar:
- Terreno real (DEM + textura satelital)
- Cuerpo modelado correctamente ubicado bajo el terreno
- Gradiente de color por densidad (azul=baja, rojo=alta)
- Cortes X/Y/Z interactivos
- Transparencia del terreno
- Escala, norte, profundidad, coordenadas

## Sistema de coordenadas canónico
Todo proyecto TerraQuantum usa coordenadas locales en metros:
- x_m: eje Este (metros desde origen del survey)
- y_m: eje profundidad (metros desde superficie, positivo hacia abajo)
- z_m: eje Norte (metros desde origen del survey)
- Origen: esquina SW del bounding box del survey
- El backend debe detectar y convertir automáticamente
  desde lat/lon, UTM, o coordenadas locales

## Lo que TerraQuantum NO afirma
- No confirma qué mineral hay
- No reemplaza estudio de factibilidad
- No reemplaza estimación de recursos bajo JORC/NI-43101
- No reemplaza trabajo de campo ni perforaciones

## Lo que TerraQuantum SÍ afirma
- Identifica zonas con anomalía geofísica
- Caracteriza geometría y densidad del cuerpo anómalo
- Cruza evidencia superficial y subsuperficial
- Genera score de favorabilidad exploratoria
- Prioriza objetivos para investigación adicional

## Módulos actuales y su estado en V2

| Módulo | V1 | V2 |
|--------|----|----|
| Figura 3D | Nube de esferas | Cuerpo volumétrico profesional |
| Inversión gravimétrica | LSQR + MS-x opcional | LSQR + MS-x siempre activo |
| Diseño Mina | Módulo central | Fase posterior (Bloque 6) |
| Mapeo IA | Mapas inventados | Eliminado → reemplazado por Satélite real |
| Flota FMS | Demo | Futuro/demo |
| Datos | Historial de corridas | Historial limpio + naming + eliminar corridas |

## Roadmap de bloques V2

### Bloque 0 — Documentación ✅ (esta sesión)
### Bloque 1 — Modelo 3D profesional
### Bloque 2 — Backend auto-adaptativo para cualquier CSV
### Bloque 3 — Satélite y territorio real (reemplaza MapeoIA)
### Bloque 4 — Motor de favorabilidad exploratoria
### Bloque 5 — Multi-física futura (magnetometría, IP, geoquímica, EM)
### Bloque 6 — Diseño mina vuelve desde modelo sólido
### Bloque 7 — Reportes industriales completos
### Bloque 8 — IA minera local y agentes
