"use client";

import React, { useEffect, useMemo, useRef } from "react";

import PrepPanel from "../PrepPanel";
import PrepEnrichPanel from "../PrepEnrichPanel";
import BoreholeUploadPanel from "../BoreholeUploadPanel";
import MultimodalComboPanel from "../MultimodalComboPanel";
import HistorialPrepControls from "../prep/HistorialPrepControls";
import { useAppStore } from "../../store/useAppStore";
import { huellaDeInvalidacion } from "../prep/invalidaResultado";

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
  //
  // FASE 24 (NUEVO-2) — viven en el store. Éste era el ÚNICO `useState` de la
  // vista y era el peor de todos: los intervalos son lo que VIAJA al backend
  // como anclaje, y al perderse el paquete salía sin anclaje mientras la
  // interfaz no decía nada. Que sobrevivan mantiene alineado lo que se ve
  // («N sondaje(s) anclado(s)» en PrepPanel, «+ sondajes (anclaje)» en el combo
  // del flujo principal) con lo que se envía.
  const boreholeIntervals = useAppStore((s) => s.prepSondajes);
  const setBoreholeIntervals = useAppStore((s) => s.setPrepSondajes);

  // FASE 24 — al volver a la pestaña se apaga lo que describiría algo que ya no
  // está pasando: cargas en vuelo sin `AbortController`, errores de un intento
  // abandonado y modales que al re-montarse relanzarían peticiones que nadie
  // pidió. El motivo largo de cada una está en `despertarPreparacion`.
  const despertarPreparacion = useAppStore((s) => s.despertarPreparacion);
  useEffect(() => {
    despertarPreparacion();
  }, [despertarPreparacion]);

  // ── FASE 25 (H-36) — «resultado desactualizado», declarado por tipos ────────
  //
  // El aviso existe desde la Fase 1 (§9H.2) y es de la familia de H-28: mostrar
  // algo que ya no corresponde. El modelo SÍ es de esta corrida, pero el usuario
  // movió parámetros de preparación DESPUÉS de invertir, y la pantalla enseñaba
  // la configuración nueva junto al resultado viejo sin distinguirlos. No se
  // borra el resultado —sigue siendo un dato real—: se MARCA.
  //
  // Vivía dentro de `PrepPanel` y desde ahí sólo alcanzaba a la mitad del
  // problema. Dos medidas de esta fase lo mudaron aquí:
  //
  //   · La lista era A MANO (23 variables en un `JSON.stringify`) y ya se había
  //     quedado atrás: le faltaban `implicitGeologyParams` (FASE 14, la que el
  //     plan nombra), los dos `acknowledge_*`, el CSV corregido y los sondajes.
  //   · `markResultStale()` tenía UN llamador en todo el frontend, y era el
  //     flujo CLÁSICO —el colapsado bajo «Avanzado»—. El flujo PRINCIPAL, por
  //     donde entra el usuario, no marcaba nada aunque seis de sus campos
  //     viajan al backend en cada generación.
  //
  // Esta vista es el padre común de los dos paneles y está montada siempre que
  // cualquiera de los dos puede cambiar: `<details>` colapsa, no desmonta. Y
  // desde la Fase 24 las cuatro máquinas viven en el store, así que aquí se lee
  // el estado entero sin pasar por ningún panel.
  //
  // El QUÉ invalida no se decide aquí: se declara en `prep/invalidaResultado.ts`
  // por tipos, donde un parámetro sin clasificar no compila.
  const prepContexto = useAppStore((s) => s.prepContexto);
  const prepParametros = useAppStore((s) => s.prepParametros);
  const prepAvanzado = useAppStore((s) => s.prepAvanzado);
  const prepEnriquecer = useAppStore((s) => s.prepEnriquecer);
  const latNorth = useAppStore((s) => s.latNorth);
  const latSouth = useAppStore((s) => s.latSouth);
  const lonEast = useAppStore((s) => s.lonEast);
  const lonWest = useAppStore((s) => s.lonWest);
  const fileGravimetry = useAppStore((s) => s.fileGravimetry);
  const fileMagnetometry = useAppStore((s) => s.fileMagnetometry);
  const markResultStale = useAppStore((s) => s.markResultStale);

  const huella = useMemo(
    () =>
      huellaDeInvalidacion({
        contexto: prepContexto,
        parametros: prepParametros,
        avanzado: prepAvanzado,
        enriquecer: prepEnriquecer,
        store: {
          latNorth, latSouth, lonEast, lonWest,
          fileGravimetry, fileMagnetometry,
          prepSondajes: boreholeIntervals,
        },
      }),
    [
      prepContexto, prepParametros, prepAvanzado, prepEnriquecer,
      latNorth, latSouth, lonEast, lonWest,
      fileGravimetry, fileMagnetometry, boreholeIntervals,
    ],
  );
  // La referencia arranca con la huella del PRIMER render, así que volver a la
  // pestaña no marca nada por el mero hecho de montar: sólo un cambio posterior.
  const huellaPrevia = useRef(huella);
  useEffect(() => {
    if (huellaPrevia.current === huella) return;
    huellaPrevia.current = huella;
    // `markResultStale` sólo marca si hay un modelo de una corrida en pantalla.
    markResultStale();
  }, [huella, markResultStale]);

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

        {/* FASE 9 — Combo multimodal (Fase 21) montado por fin.
            Era el ÚNICO consumidor de `/api/multimodal/plan`: la función existía
            entera en el backend, la UI estaba escrita, y nadie la importaba. Va
            aquí porque la pregunta que responde —«con los datos que tengo, qué
            combinación conviene y con qué error de profundidad»— es una decisión
            de PREPARACIÓN, anterior a invertir. Colapsado: no es parte del flujo
            mínimo. El panel no calcula nada: el backend decide el combo. */}
        <details className="rounded-2xl border border-neutral-800 bg-black/30">
          <summary
            data-testid="multimodal-combo-summary"
            className="cursor-pointer select-none px-6 py-4 text-[11px] uppercase tracking-widest text-neutral-400 hover:text-neutral-200"
          >
            Combo multimodal · qué datos conviene combinar
          </summary>
          <div className="px-6 pb-6 pt-2" data-testid="multimodal-combo-panel">
            <MultimodalComboPanel
              nBoreholesWithDensity={boreholeIntervals.length}
            />
          </div>
        </details>

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
            {/* FASE 13 — el deshacer va JUNTO a las perillas que deshace, no en
                una barra global: aquí es donde el usuario está mirando cuando se
                arrepiente. `<details>` no desmonta a sus hijos, así que colapsar
                la sección no pierde el historial. */}
            <HistorialPrepControls />
            <PrepPanel boreholes={boreholeIntervals} />
          </div>
        </details>
      </div>
    </div>
  );
}
