"use client";

import { useCallback } from "react";
import { useAppStore } from "../../store/useAppStore";
import { deshacerVisor, rehacerVisor } from "../../store/historialVisor";
import { useAtajosDeHistorial } from "../../lib/historial/useHistorial";
import ControlesHistorial from "../historial/ControlesHistorial";

/**
 * FASE 13 — Deshacer/rehacer del visor 3D.
 *
 * Es el ÚNICO sitio del visor que registra los atajos de teclado, y el único que
 * monta los botones. Se apoya en `store/historialVisor.ts` para todo lo demás.
 *
 * El motivo del bloqueo se calcula aquí porque es lo que se le enseña al
 * usuario; la decisión de bloquear la toma `sePuedeOperarElHistorial()` con las
 * mismas tres banderas, y las dos tienen que coincidir. Se leen por separado (no
 * se llama a la función) para que el componente se re-renderice cuando cambien:
 * una función no es una suscripción.
 */
export default function HistorialVisorControls() {
  const estadoCorrida = useAppStore((s) => s.activeRun.status);
  const cargandoBlockModel = useAppStore((s) => s.isBlockModelLoading);
  const procesandoWorker = useAppStore((s) => s.isWorkerProcessing);

  const bloqueadoPorque =
    estadoCorrida === "loading"
      ? "Hay una inversión en curso: el historial se reanuda al terminar."
      : cargandoBlockModel
        ? "Cargando el modelo de bloques…"
        : procesandoWorker
          ? "Construyendo la geometría del visor…"
          : null;

  const deshacer = useCallback(() => deshacerVisor(), []);
  const rehacer = useCallback(() => rehacerVisor(), []);

  useAtajosDeHistorial({ deshacer, rehacer });

  return (
    <ControlesHistorial
      ambito="visor"
      deshacer={deshacer}
      rehacer={rehacer}
      bloqueadoPorque={bloqueadoPorque}
    />
  );
}
