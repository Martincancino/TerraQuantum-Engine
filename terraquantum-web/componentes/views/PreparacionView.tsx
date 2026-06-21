"use client";

import React, { useState } from "react";

import PrepPanel from "../PrepPanel";
import PrepEnrichPanel from "../PrepEnrichPanel";
import BoreholeUploadPanel from "../BoreholeUploadPanel";
import { boreholeSurveyToIntervals } from "../../lib/terraquantum/frontendApi";

/**
 * PreparacionView — flujo SIMPLE de preparación de datos.
 *
 * El usuario sube gravimetría/magnetometría (+sondajes), declara un contexto
 * opcional (zona UTM + gravímetro) y pulsa «Generar CSV completo». El backend
 * enriquece con física real (DEM/correcciones/IGRF/coords/σ/calidad) y devuelve
 * un CSV descargable + un resumen de qué calculó. Los PARÁMETROS de inversión
 * viven en «Avanzado» (colapsado): el flujo normal no requiere tocarlos. No
 * calcula física: solo orquesta paneles y consume APIs del backend.
 */
export default function PreparacionView() {
  // Sondajes confirmados en BoreholeUploadPanel, en el formato que el payload de
  // inversión consume. Se anexan al paquete (anclaje) en el panel de enriquecimiento.
  const [boreholeIntervals, setBoreholeIntervals] = useState<
    ReturnType<typeof boreholeSurveyToIntervals>
  >([]);

  return (
    <div className="h-full w-full overflow-y-auto custom-scrollbar animate-fadeIn">
      <div className="min-h-full flex flex-col gap-6 px-2 pb-8 pt-4">
        {/* Header de UNA línea */}
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-[#C2D8C4] shadow-[0_0_20px_rgba(194,216,196,0.8)]" />
          <h1 className="text-base font-black tracking-tight text-white">
            Preparación
          </h1>
          <span className="text-[11px] font-mono text-neutral-500">
            Sube tus datos → genera un CSV completo listo para invertir.
          </span>
        </div>

        {/* Flujo principal de enriquecimiento */}
        <section className="rounded-2xl border border-neutral-800 bg-neutral-950/50 p-6">
          <PrepEnrichPanel
            boreholes={boreholeIntervals}
            boreholeNode={
              <BoreholeUploadPanel
                onConfirm={(_survey, intervals) => setBoreholeIntervals(intervals)}
              />
            }
          />
        </section>

        {/* Parámetros de inversión + flujo clásico — COLAPSADO por defecto.
            El flujo normal NO requiere abrirlo (auto-defaults sensatos en el backend). */}
        <details className="rounded-2xl border border-neutral-800 bg-black/30">
          <summary className="cursor-pointer select-none px-6 py-4 text-[11px] uppercase tracking-widest text-neutral-400 hover:text-neutral-200">
            Avanzado · parámetros de inversión y flujo clásico
          </summary>
          <div className="px-6 pb-6 pt-2">
            <p className="text-[11px] font-mono text-neutral-600 leading-5 mb-4">
              Solo para casos especiales: densidad mín/máx, gravímetro como
              parámetro, regularización, límite de preview y empaquetado manual.
              El flujo normal usa valores por defecto sensatos.
            </p>
            <PrepPanel boreholes={boreholeIntervals} />
          </div>
        </details>
      </div>
    </div>
  );
}
