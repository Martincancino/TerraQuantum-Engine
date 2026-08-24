"use client";

import { useState } from "react";
import { useAppStore } from "../../store/useAppStore";
import {
  downloadBlockModelCsv,
  downloadRunOmf,
  downloadTechnicalReport,
  exportBundleUrl,
} from "../../lib/terraquantum/frontendApi";

/**
 * F5 — Botonera de descarga unificada: PNG de alta resolución del visor 3D,
 * block model CSV, reporte técnico (HTML imprimible → PDF vía el navegador,
 * sin dependencias nuevas), y bundle ZIP industrial (VTK/UBC/GSLIB/ASEG/CSV).
 * FASE 12 añade OMF, que es el formato con el que se entrega a una minera.
 * Cero física nueva: solo compone/descarga lo que el backend ya calculó.
 */
type ActionState = "idle" | "busy" | "error" | "ok";

// Mismos stops que el legend on-screen (Exploration3DView.tsx) — coherencia visual.
const VIRIDIS_STOPS: Array<[number, string]> = [
  [0.0, "rgb(68,1,84)"],
  [0.125, "rgb(72,36,117)"],
  [0.25, "rgb(65,68,135)"],
  [0.375, "rgb(53,95,141)"],
  [0.5, "rgb(42,120,142)"],
  [0.625, "rgb(33,145,140)"],
  [0.75, "rgb(34,168,132)"],
  [0.875, "rgb(122,209,81)"],
  [1.0, "rgb(253,231,37)"],
];

function drawColorbar(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number
) {
  const gradient = ctx.createLinearGradient(x, 0, x + w, 0);
  for (const [stop, color] of VIRIDIS_STOPS) gradient.addColorStop(stop, color);
  ctx.fillStyle = gradient;
  ctx.fillRect(x, y, w, h);
}

export default function ExportPanel({
  projectId,
  runId,
}: {
  projectId: string;
  runId: string;
}) {
  const capturePngSnapshot = useAppStore((s) => s.capturePngSnapshot);
  const model = useAppStore((s) => s.model) as
    | { densityMin?: number; densityMax?: number }
    | null;

  const [pngState, setPngState] = useState<ActionState>("idle");
  const [csvState, setCsvState] = useState<ActionState>("idle");
  const [reportState, setReportState] = useState<ActionState>("idle");
  const [omfState, setOmfState] = useState<ActionState>("idle");
  const [msg, setMsg] = useState<string | null>(null);

  async function handleDownloadPng() {
    if (!capturePngSnapshot) {
      setPngState("error");
      setMsg("El visor 3D aún no está listo para capturar.");
      return;
    }
    setPngState("busy");
    setMsg(null);
    try {
      const dataUrl = capturePngSnapshot(3840); // objetivo ~4K de ancho
      const img = new Image();
      await new Promise<void>((resolve, reject) => {
        img.onload = () => resolve();
        img.onerror = () => reject(new Error("No se pudo componer la imagen capturada."));
        img.src = dataUrl;
      });

      const footerH = Math.round(img.height * 0.09);
      const canvas = document.createElement("canvas");
      canvas.width = img.width;
      canvas.height = img.height + footerH;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("Canvas 2D no disponible.");

      ctx.fillStyle = "#050505";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0);

      const pad = Math.round(footerH * 0.12);
      const barW = Math.round(canvas.width * 0.28);
      const barH = Math.max(6, Math.round(footerH * 0.16));
      const barX = pad;
      const barY = img.height + pad;
      drawColorbar(ctx, barX, barY, barW, barH);

      const dMin = model?.densityMin;
      const dMax = model?.densityMax;
      const fontSize = Math.max(10, Math.round(footerH * 0.16));
      ctx.fillStyle = "rgba(255,255,255,0.85)";
      ctx.font = `${fontSize}px monospace`;
      ctx.textBaseline = "top";
      ctx.fillText(
        Number.isFinite(dMin) && Number.isFinite(dMax)
          ? `Densidad ${dMin!.toFixed(2)} — ${dMax!.toFixed(2)} t/m³ (Viridis)`
          : "Contraste de densidad (Viridis, escala relativa)",
        barX,
        barY + barH + pad * 0.5
      );

      const title = `TerraQuantum — ${projectId} / ${runId}`;
      const dateStr = new Date().toISOString().slice(0, 19).replace("T", " ") + " UTC";
      ctx.textAlign = "right";
      ctx.fillText(title, canvas.width - pad, img.height + pad);
      ctx.font = `${Math.max(9, fontSize - 2)}px monospace`;
      ctx.fillStyle = "rgba(255,255,255,0.5)";
      ctx.fillText(dateStr, canvas.width - pad, img.height + pad + fontSize + 2);
      ctx.fillStyle = "rgba(255,140,90,0.85)";
      ctx.fillText(
        "NO-JORC / NI 43-101 — EXPLORATION ONLY",
        canvas.width - pad,
        img.height + pad + (fontSize + 2) * 2
      );
      ctx.textAlign = "left";

      await new Promise<void>((resolve, reject) => {
        canvas.toBlob((blob) => {
          if (!blob) {
            reject(new Error("No se pudo generar el PNG."));
            return;
          }
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `terraquantum_${projectId}_${runId}_${Date.now()}.png`;
          document.body.appendChild(a);
          a.click();
          a.remove();
          URL.revokeObjectURL(url);
          resolve();
        }, "image/png");
      });
      setPngState("ok");
    } catch (e: unknown) {
      setPngState("error");
      setMsg(e instanceof Error ? e.message : "Error al exportar PNG.");
    }
  }

  async function handleDownloadCsv() {
    setCsvState("busy");
    setMsg(null);
    const res = await downloadBlockModelCsv(projectId, runId);
    if (!res.ok) {
      setCsvState("error");
      setMsg(res.error);
      return;
    }
    setCsvState("ok");
  }

  async function handleDownloadReport() {
    setReportState("busy");
    setMsg(null);
    const res = await downloadTechnicalReport(projectId, runId);
    if (!res.ok) {
      setReportState("error");
      setMsg(res.error);
      return;
    }
    setReportState("ok");
  }

  function handleOpenBundle() {
    window.open(exportBundleUrl(projectId, runId), "_blank");
  }

  // FASE 12 — el OMF puede fallar con un motivo que el usuario necesita LEER
  // (p. ej. una corrida conjunta cuya malla no es reconstruible), así que se
  // descarga por fetch y el error se muestra aquí, no en una pestaña nueva.
  async function handleDownloadOmf() {
    setOmfState("busy");
    setMsg(null);
    const res = await downloadRunOmf(projectId, runId);
    if (!res.ok) {
      setOmfState("error");
      setMsg(res.error);
      return;
    }
    setOmfState("ok");
  }

  const btnClass = (state: ActionState) =>
    `w-full py-2 rounded-md text-[10px] font-mono uppercase tracking-wider border transition-colors disabled:opacity-40 ${
      state === "error"
        ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
        : "border-white/15 bg-white/[0.02] text-white/60 hover:text-white/85 hover:border-white/30"
    }`;

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={handleDownloadPng}
        disabled={pngState === "busy" || !capturePngSnapshot}
        className={btnClass(pngState)}
      >
        {pngState === "busy" ? "Capturando…" : "PNG alta resolución"}
      </button>

      <button
        type="button"
        onClick={handleDownloadCsv}
        disabled={csvState === "busy"}
        className={btnClass(csvState)}
      >
        {csvState === "busy" ? "Exportando…" : "Block model CSV"}
      </button>

      <button
        type="button"
        onClick={handleDownloadReport}
        disabled={reportState === "busy"}
        className={btnClass(reportState)}
      >
        {reportState === "busy" ? "Generando…" : "Reporte técnico (HTML → PDF)"}
      </button>

      <button
        type="button"
        onClick={handleDownloadOmf}
        disabled={omfState === "busy"}
        className={btnClass(omfState)}
      >
        {omfState === "busy" ? "Generando…" : "OMF (Leapfrog / Vulcan)"}
      </button>

      <button type="button" onClick={handleOpenBundle} className={btnClass("idle")}>
        Bundle ZIP (VTK/UBC/GSLIB/CSV)
      </button>

      <p className="text-[8px] text-white/40 font-mono leading-relaxed">
        El OMF lleva block model, estaciones, sondajes e isosuperficies en un solo
        fichero. Si el proyecto declara zona UTM sale georreferenciado; si no, en
        metros locales, y el propio fichero lo dice.
      </p>

      <p className="text-[8px] text-white/40 font-mono leading-relaxed">
        El reporte técnico se abre como HTML imprimible — usa &quot;Imprimir → Guardar
        como PDF&quot; del navegador para obtener el PDF con portada, veredicto,
        target y obs-vs-calc.
      </p>

      {msg && (
        <p className="text-[8px] font-mono leading-relaxed text-amber-400/80">{msg}</p>
      )}
    </div>
  );
}
