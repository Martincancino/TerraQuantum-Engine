"use client";

import { useCallback } from "react";
import { useAtajosDeHistorial } from "../../lib/historial/useHistorial";
import { deshacerAmbito, rehacerAmbito } from "../../lib/historial/useReducerConHistorial";
import ControlesHistorial from "../historial/ControlesHistorial";

/**
 * FASE 13 — Deshacer/rehacer de los parámetros de preparación.
 *
 * Es el ámbito de historial que más vale del producto: el usuario de este
 * software es un consultor que mueve estas perillas una y otra vez comparando
 * corridas, y hasta ahora la única forma de volver a un valor era recordarlo.
 *
 * Sólo cubre `contexto` y `parametros`. Lo que queda fuera —el estado de
 * operación, los modales y el CSV corregido— está declarado con su motivo en
 * `deshaciblePrep.ts`, no omitido en silencio.
 *
 * No hay puerta de «corrida en curso» aquí, y es a propósito: estos valores no
 * viajan a ninguna parte hasta que el usuario pulsa «generar paquete», que los
 * lee POR VALOR en ese instante. Deshacer un parámetro mientras algo carga no
 * puede alcanzar a la petición en vuelo.
 */
export default function HistorialPrepControls() {
  const deshacer = useCallback(() => deshacerAmbito("preparacion"), []);
  const rehacer = useCallback(() => rehacerAmbito("preparacion"), []);

  useAtajosDeHistorial({ deshacer, rehacer });

  return (
    <div className="mb-4 flex flex-col gap-2 rounded-lg border border-neutral-800 bg-black/40 p-3">
      <p className="text-[9px] font-mono uppercase tracking-widest text-neutral-500">
        Historial de parámetros
      </p>
      <ControlesHistorial ambito="preparacion" deshacer={deshacer} rehacer={rehacer} />
      <p className="text-[8px] font-mono leading-relaxed text-neutral-600">
        Cubre el contexto del survey y las perillas de inversión. No cubre los
        reconocimientos de riesgo ni el asistente de correcciones, y{" "}
        <strong className="text-neutral-500">se borra al cambiar de archivo</strong>:
        lo que se aceptó sobre un archivo no puede volver sobre otro.
      </p>
    </div>
  );
}
