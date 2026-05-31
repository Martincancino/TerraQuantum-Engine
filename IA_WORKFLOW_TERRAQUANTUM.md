# FLUJO DE TRABAJO IA - TERRAQUANTUM

Este documento define cómo operar con asistentes de IA (Claude, Gemini, Antigravity, ChatGPT) sobre el proyecto TerraQuantum.

## Prioridades del Proyecto
1. Exactitud técnica.
2. Trazabilidad.
3. Usabilidad.
4. Estética.

## Cómo usar los Modelos
- **Gemini Pro High / Claude Opus:** Para investigación matemática profunda, diseño de algoritmos de inversión gravimétrica, ecuaciones de NPV/LOM y análisis arquitectónico. (Modo Consultivo).
- **Claude 3.5 Sonnet / Antigravity:** Para ejecución rápida, creación de componentes React, integraciones de FastAPI y parseo de datos. (Modo Obrero).
- **Gemini Pro Low / ChatGPT:** Para consultas rápidas, dudas sobre librerías o formateo de documentación.

## Cómo NO Romper el Proyecto
1. **Aislamiento:** Trabaja en un archivo a la vez. No mezcles lógica de estado (Zustand) con lógica física (Python) en el mismo prompt.
2. **Uso de Skills:** Invoca las skills de la carpeta `.claude/skills/` para mantener a la IA enfocada en un contexto reducido.
3. **Validación:** Nunca asumas que el código funciona sin correr los tests en el backend (`test_geophysics_qaqc.py`, etc.) y el linting en el frontend.

## Próximos Pasos Recomendados (Roadmap Inmediato)
1. Investigar formatos reales de gravimetría cuántica.
2. Definir el estándar `TerraQuantum Gravity CSV v1`.
3. Crear el importador CSV/Excel/Parquet en el backend.
4. Implementar generación de reportes técnicos (PDF/HTML).
5. Diseñar la arquitectura base del copiloto IA grounded en datos.