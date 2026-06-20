"use client";

import React from "react";

/**
 * PreparacionView — andamiaje (Fase R1).
 *
 * Vista nueva del flujo de preparación de datos (limpieza CSV → georef →
 * revisión previa a la inversión). Por ahora es solo el layout de secciones;
 * cada sección se irá poblando en fases posteriores. No calcula física ni
 * consume APIs todavía.
 */
export default function PreparacionView() {
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
            Limpieza, georreferenciación y revisión del survey antes de la
            inversión 3D. (Andamiaje — secciones en construcción.)
          </p>
        </section>

        {/* Secciones del flujo de preparación (placeholders) */}
        <Section
          step="01"
          title="Carga y limpieza del CSV"
          desc="Importar el survey, mapear columnas y detectar filas inválidas."
        />

        <Section
          step="02"
          title="Georreferenciación"
          desc="Coordenadas por estación o ajuste Helmert con puntos de referencia."
        />

        <Section
          step="03"
          title="Revisión previa"
          desc="Vista de calidad del dato antes de pasar a la inversión 3D."
        />
      </div>
    </div>
  );
}

function Section({
  step,
  title,
  desc,
}: {
  step: string;
  title: string;
  desc: string;
}) {
  return (
    <section className="rounded-[2rem] border border-neutral-800 bg-neutral-950/50 p-8">
      <div className="flex items-start gap-4">
        <div className="w-9 h-9 shrink-0 rounded-full flex items-center justify-center text-[9px] font-black border border-neutral-700 text-neutral-500 bg-neutral-900">
          {step}
        </div>

        <div>
          <h3 className="text-xl font-black text-white">{title}</h3>
          <p className="text-neutral-500 text-xs font-mono mt-2 leading-6">
            {desc}
          </p>
        </div>
      </div>

      <div className="mt-6 rounded-2xl border border-dashed border-neutral-800 bg-black/30 p-8 text-center">
        <p className="text-[9px] uppercase tracking-[0.3em] text-neutral-600 font-black">
          Sección en construcción
        </p>
      </div>
    </section>
  );
}
