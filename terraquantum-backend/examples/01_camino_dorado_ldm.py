"""FASE 11 — Criterio de aceptación: el camino dorado completo en ~20 líneas.

Dato REAL: Laguna del Maule (Miller et al. 2017, 191 estaciones), y no el CSV ya
limpio sino **el que exporta un Excel chileno**: dos líneas de preámbulo,
separador `;`, coma decimal y encabezados en español. Sin tocar la interfaz.

    cd terraquantum-backend
    python examples/01_camino_dorado_ldm.py

Lo que NO hace, a propósito: interpretar el resultado por ti. Imprime el
veredicto reconciliado, el blanco y lo que el dato NO resuelve en profundidad,
que es la trilogía honesta del informe. Un `LOW` aquí es la respuesta correcta
para gravimetría-sola a esta profundidad, no un fallo del script.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import terraquantum as tq  # noqa: E402

# ── El camino dorado ─────────────────────────────────────────────────────────
CSV = tq.backend_root() / "tests/fixtures/csv_reales/LdM_gravimetria_CRUDO_usuario.csv"

paquete = tq.enrich(gravity=CSV, config={"utm_zone": "19S", "nx": 12, "ny": 12, "nz": 8})
corrida = tq.run_inversion(paquete, project_id="laguna_del_maule", run_id="api_v0")

print(f"ruta        {corrida.route}   ({paquete.n_stations} estaciones)")
print(f"veredicto   {corrida.verdict['level']} — {corrida.verdict['headline'][:70]}")
print(f"χ² final    {corrida.fit.get('chi_squared_final')}")
print(f"blanco      x={corrida.best_target['x_m']:.0f} y={corrida.best_target['y_m']:.0f} "
      f"z={corrida.best_target['z_m']:.0f} ρ={corrida.best_target['density']:.2f}")
print(f"profundidad cola null-space = {corrida.depth_resolution['deep_mass_fraction']:.3f}")

paquete.save("salida/laguna_del_maule.tqpkg")     # el experimento, reproducible
corrida.save_bundle("salida/")                    # el entregable del gabinete
# ── Fin del camino dorado ────────────────────────────────────────────────────

for aviso in paquete.warnings:
    print(f"  aviso: {aviso}")
if paquete.needs_context:
    print(f"  sin derivar (NO inventado): {paquete.needs_context}")
