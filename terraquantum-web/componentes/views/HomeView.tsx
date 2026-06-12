"use client";

import React from "react";
import { useAppStore } from "../../store/useAppStore";

export default function HomeView() {
  const { setView } = useAppStore();

  return (
    <div className="h-full w-full overflow-y-auto custom-scrollbar animate-fadeIn">
      <div className="min-h-full flex flex-col gap-8 px-2 pb-8">
        <section className="relative overflow-hidden rounded-[2rem] border border-neutral-800 bg-[#05070d] shadow-2xl">
          <div className="absolute inset-0 opacity-40">
            <div className="absolute -top-32 -right-32 w-96 h-96 bg-[#C2D8C4]/10 blur-3xl rounded-full" />
            <div className="absolute bottom-0 left-0 w-96 h-96 bg-blue-500/10 blur-3xl rounded-full" />
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(255,255,255,0.04),transparent_45%)]" />
          </div>

          <div className="relative z-10 grid grid-cols-1 xl:grid-cols-[1.2fr_0.8fr] gap-10 p-8 xl:p-12">
            <div className="flex flex-col justify-center gap-8">
              <div className="flex items-center gap-3">
                <div className="w-2 h-2 rounded-full bg-[#C2D8C4] shadow-[0_0_20px_rgba(194,216,196,0.8)]" />
                <span className="text-[10px] uppercase tracking-[0.35em] text-[#C2D8C4] font-black">
                  TerraQuantum Mining Intelligence
                </span>
              </div>

              <div>
                <h1 className="text-4xl xl:text-6xl font-black tracking-[-0.06em] text-white leading-[0.95]">
                  Del dato físico
                  <br />
                  al modelo 3D.
                </h1>

                <p className="mt-6 max-w-2xl text-neutral-400 text-sm leading-7 font-mono">
                  Plataforma de exploración que conecta datos gravimétricos de
                  campo, correcciones geofísicas, inversión 3D con incertidumbre
                  y block model industrial en un solo flujo visual.
                </p>
              </div>

              <div className="flex flex-wrap gap-3">
                <button
                  onClick={() => setView("figura 3d")}
                  className="px-7 py-4 bg-[#C2D8C4] text-black rounded-full text-[10px] uppercase tracking-[0.25em] font-black hover:bg-white transition-all active:scale-95 shadow-[0_0_30px_rgba(194,216,196,0.2)]"
                >
                  Iniciar exploración →
                </button>

                <button
                  onClick={() => setView("datos")}
                  className="px-7 py-4 bg-neutral-900 border border-neutral-700 text-white rounded-full text-[10px] uppercase tracking-[0.25em] font-black hover:bg-white hover:text-black transition-all active:scale-95"
                >
                  Ver Datos y Calidad
                </button>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-4">
                <MetricCard label="Geofísica" value="LSQR" />
                <MetricCard label="Modelo" value="3D Voxels" />
                <MetricCard label="Validación" value="Obs vs Calc" />
                <MetricCard label="Export" value="UBC + VTK" />
              </div>
            </div>

            <div className="relative min-h-[420px] rounded-[2rem] border border-neutral-800 bg-black/50 overflow-hidden p-6 flex flex-col justify-between">
              <div className="absolute inset-0 opacity-30 bg-[linear-gradient(120deg,transparent,rgba(194,216,196,0.12),transparent)]" />

              <div className="relative z-10 flex justify-between items-start">
                <div>
                  <p className="text-[9px] uppercase tracking-[0.3em] text-neutral-500 font-bold">
                    Módulos del flujo
                  </p>
                  <h2 className="text-2xl font-black text-white mt-2">
                    Pipeline TerraQuantum
                  </h2>
                </div>

                <span className="px-3 py-1 rounded-full border border-[#C2D8C4]/40 bg-[#C2D8C4]/10 text-[#C2D8C4] text-[8px] uppercase tracking-widest font-black">
                  Plataforma lista
                </span>
              </div>

              <div className="relative z-10 space-y-3">
                <PipelineStep index="01" title="Survey gravimétrico" desc="CSV de campo: g_raw o anomalía corregida" />
                <PipelineStep index="02" title="Correcciones" desc="GRS80, Free-Air, Bouguer y terreno" />
                <PipelineStep index="03" title="Inversión 3D" desc="Densidad, DOI e incertidumbre" />
                <PipelineStep index="04" title="Block model" desc="Parquet industrial + Obs vs Calc" />
                <PipelineStep index="05" title="Export" desc="UBC-GIF (SimPEG), VTK (ParaView), reporte" />
              </div>

              <div className="relative z-10 grid grid-cols-3 gap-3">
                <MiniStatus label="Backend" value="FastAPI" />
                <MiniStatus label="Frontend" value="Next.js" />
                <MiniStatus label="3D" value="R3F" />
              </div>
            </div>
          </div>
        </section>

        <section className="grid grid-cols-1 xl:grid-cols-3 gap-5">
          <InfoPanel
            title="Exploración"
            subtitle="Figura 3D"
            text="Genera un cuerpo anómalo preliminar a partir de observaciones gravimétricas, densidad invertida y probabilidad espacial."
            button="Abrir Figura 3D"
            onClick={() => setView("figura 3d")}
          />

          <InfoPanel
            title="Calidad"
            subtitle="Datos y Misfit"
            text="Revisa observaciones, correcciones aplicadas, ajuste Observed vs Calculated y diagnósticos de incertidumbre del modelo."
            button="Abrir Datos"
            onClick={() => setView("datos")}
          />

          <InfoPanel
            title="Trazabilidad"
            subtitle="Historial"
            text="Compara corridas, recupera modelos anteriores y audita parámetros de inversión de cada run del proyecto."
            button="Abrir Historial"
            onClick={() => setView("historial")}
          />
        </section>

        <section className="rounded-[2rem] border border-neutral-800 bg-neutral-950/50 p-8">
          <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-6">
            <div>
              <p className="text-[10px] uppercase tracking-[0.35em] text-blue-400 font-black">
                Flujo recomendado
              </p>
              <h3 className="text-2xl font-black text-white mt-2">
                Flujo completo para exploración técnica
              </h3>
              <p className="text-neutral-500 text-xs font-mono mt-3 max-w-3xl leading-6">
                Cargar CSV gravimétrico → Aplicar correcciones → Validar e invertir →
                Analizar modelo 3D y DOI → Revisar Obs vs Calc → Exportar UBC/VTK y reporte.
              </p>
            </div>

            <button
              onClick={() => setView("figura 3d")}
              className="shrink-0 px-7 py-4 bg-white text-black rounded-full text-[10px] uppercase tracking-[0.25em] font-black hover:bg-[#C2D8C4] transition-all active:scale-95"
            >
              Ejecutar flujo →
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-black/40 border border-neutral-800 rounded-2xl p-4">
      <p className="text-[8px] uppercase tracking-widest text-neutral-500 font-bold">
        {label}
      </p>
      <p className="text-sm text-white font-black mt-2">{value}</p>
    </div>
  );
}

function PipelineStep({
  index,
  title,
  desc,
  active,
}: {
  index: string;
  title: string;
  desc: string;
  active?: boolean;
}) {
  return (
    <div className="flex items-center gap-4 bg-neutral-950/70 border border-neutral-800 rounded-2xl p-4">
      <div
        className={`w-9 h-9 rounded-full flex items-center justify-center text-[9px] font-black border ${
          active
            ? "border-[#C2D8C4]/50 text-[#C2D8C4] bg-[#C2D8C4]/10"
            : "border-neutral-700 text-neutral-500 bg-neutral-900"
        }`}
      >
        {index}
      </div>

      <div>
        <p className="text-white text-[11px] font-black uppercase tracking-widest">
          {title}
        </p>
        <p className="text-neutral-500 text-[9px] font-mono mt-1">{desc}</p>
      </div>
    </div>
  );
}

function MiniStatus({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-neutral-950 border border-neutral-800 rounded-xl p-3">
      <p className="text-[7px] uppercase tracking-widest text-neutral-500 font-bold">
        {label}
      </p>
      <p className="text-[10px] text-[#C2D8C4] font-black mt-1">{value}</p>
    </div>
  );
}

function InfoPanel({
  title,
  subtitle,
  text,
  button,
  onClick,
}: {
  title: string;
  subtitle: string;
  text: string;
  button: string;
  onClick: () => void;
}) {
  return (
    <div className="rounded-[2rem] border border-neutral-800 bg-[#05070d] p-6 flex flex-col justify-between gap-8 min-h-[260px] hover:border-[#C2D8C4]/30 transition-colors">
      <div>
        <p className="text-[9px] uppercase tracking-[0.3em] text-neutral-500 font-black">
          {subtitle}
        </p>

        <h3 className="text-2xl font-black text-white mt-3">{title}</h3>

        <p className="text-neutral-400 text-xs font-mono leading-6 mt-4">
          {text}
        </p>
      </div>

      <button
        onClick={onClick}
        className="w-full py-3 rounded-xl bg-neutral-900 border border-neutral-700 text-white text-[9px] uppercase tracking-[0.25em] font-black hover:bg-white hover:text-black transition-all"
      >
        {button}
      </button>
    </div>
  );
}