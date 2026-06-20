"use client";

import React, { useState } from "react";

import GravityCsvPreviewPanel from "../GravityCsvPreviewPanel";
import BoreholeUploadPanel from "../BoreholeUploadPanel";
import MultimodalComboPanel from "../MultimodalComboPanel";
import { boreholeSurveyToIntervals } from "../../lib/terraquantum/frontendApi";

/**
 * PreparacionView — hogar del flujo de preparación de datos (Fase R2).
 *
 * Aloja los paneles que antes vivían en el sidebar de Exploration3DView:
 * importar/validar el survey gravimétrico (CSV), cargar sondajes y planificar
 * el combo multimodal. Al ejecutar la inversión, GravityCsvPreviewPanel navega
 * automáticamente a la vista "figura 3d". No calcula física: solo orquesta los
 * paneles y consume APIs del backend.
 */
export default function PreparacionView() {
  // FASE 20 — Sondajes confirmados en BoreholeUploadPanel, en el formato que el
  // payload de inversión consume. Se pasan a GravityCsvPreviewPanel (anclaje) y al
  // panel multimodal (conteo que decide el combo recomendado).
  const [boreholeIntervals, setBoreholeIntervals] = useState<
    ReturnType<typeof boreholeSurveyToIntervals>
  >([]);

  return (
    <div className="h-full w-full overflow-y-auto custom-scrollbar animate-fadeIn">
      <div className="min-h-full flex flex-col gap-8 px-2 pb-8">
        {/* Encabezado */}
        <section className="rounded-[2rem] border border-neutral-800 bg-[#05070d] p-8">
          <div className="flex items-center gap-3">
            <div className="w-2 h-2 rounded-full bg-[#C2D8C4] shadow-[0_0_20px_rgba(194,216,196,0.8)]" />
            <span className="text-[10px] uppercase tracking-[0.35em] text-[#C2D8C4] font-black">
              Preparación de datos
            </span>
          </div>

          <h1 className="text-3xl xl:text-5xl font-black tracking-[-0.06em] text-white leading-[0.95] mt-6">
            Del CSV crudo
            <br />
            al dato listo para invertir.
          </h1>

          <p className="mt-6 max-w-2xl text-neutral-400 text-sm leading-7 font-mono">
            Importa y valida el survey gravimétrico, carga sondajes para anclar la
            inversión y planifica el combo multimodal. Al ejecutar la inversión se
            abre la vista 3D automáticamente.
          </p>
        </section>

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
          {/* 01 — Survey gravimétrico (CSV) */}
          <Section
            step="01"
            title="Survey gravimétrico (CSV)"
            desc="Importar y validar el survey gravimétrico (CSV) antes de invertir."
          >
            <GravityCsvPreviewPanel boreholes={boreholeIntervals} />
          </Section>

          {/* 02 — Sondajes (Fase 20) */}
          <Section
            step="02"
            title="Sondajes"
            desc="Cargar sondajes para anclar la inversión y validar densidades."
          >
            <BoreholeUploadPanel
              onConfirm={(_survey, intervals) => setBoreholeIntervals(intervals)}
            />
          </Section>

          {/* 03 — Fusión multimodal (Fase 21) */}
          <Section
            step="03"
            title="Fusión multimodal"
            desc="Combo recomendado, confianza y error de profundidad según los datos disponibles. La decisión la calcula el backend."
          >
            <MultimodalComboPanel
              key={`mm-${boreholeIntervals.length}`}
              nBoreholesWithDensity={
                boreholeIntervals.filter((b) => b.density_t_m3 != null).length
              }
            />
          </Section>
        </div>
      </div>
    </div>
  );
}

function Section({
  step,
  title,
  desc,
  children,
}: {
  step: string;
  title: string;
  desc: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-[2rem] border border-neutral-800 bg-neutral-950/50 p-6 flex flex-col">
      <div className="flex items-start gap-4">
        <div className="w-9 h-9 shrink-0 rounded-full flex items-center justify-center text-[9px] font-black border border-neutral-700 text-neutral-500 bg-neutral-900">
          {step}
        </div>

        <div>
          <h3 className="text-lg font-black text-white">{title}</h3>
          <p className="text-neutral-500 text-[11px] font-mono mt-2 leading-6">
            {desc}
          </p>
        </div>
      </div>

      <div className="mt-6">{children}</div>
    </section>
  );
}
