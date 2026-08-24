"use client";

/**
 * FASE 14 — Prior geológico implícito (φ HRBF) desde los contactos de sondaje.
 *
 * El usuario marca qué litología de SUS sondajes es la unidad objetivo; el backend
 * construye el campo implícito φ (Hermite-RBF, Macedo 2011) con los contactos que
 * ya viajan en el paquete y lo inyecta como modelo de referencia (m_ref).
 *
 * Este formulario NO calcula física: ni φ, ni la clasificación, ni la densidad de
 * referencia. La lista de litologías sale de los sondajes cargados y la densidad
 * propuesta de `/borehole/lithology-properties` (tabla del backend).
 *
 * Lo que este formulario SÍ hace, y es deliberado, es no prometer de más:
 *  · sin sondajes con litología el prior no se puede pedir, y se dice por qué;
 *  · con UN solo sondaje se avisa de lo que está MEDIDO que pasa (el campo
 *    degenera a un plano extrapolado a toda la malla);
 *  · el aviso de que esto NO es modelamiento geológico está en el propio panel,
 *    no escondido en la documentación.
 */

import { useEffect, useMemo, useState } from "react";
import { fetchLithologyProperties, type LithologyEntry } from "@/lib/terraquantum/frontendApi";

export interface ImplicitGeologyUI {
  enabled: boolean;
  /** Litologías (tal como aparecen en los sondajes) que forman la unidad objetivo. */
  target_lithologies: string[];
  /** Densidad de referencia de la unidad objetivo (t/m³). */
  target_density_t_m3: number;
  /** Densidad de referencia de la roca caja (t/m³). null → base_density del input. */
  host_density_t_m3: number | null;
  /** 0 = contacto escalón; >0 = transición sigmoide. */
  softness: number;
}

export const IMPLICIT_GEOLOGY_INICIAL: ImplicitGeologyUI = {
  enabled: false,
  target_lithologies: [],
  target_density_t_m3: 3.0,
  host_density_t_m3: null,
  softness: 0,
};

interface Props {
  /** Litologías presentes en los sondajes ya cargados (sin repetir). */
  litologiasDisponibles: string[];
  /** Cuántos collares distintos hay: con 1 el campo implícito degenera. */
  nCollares: number;
  initialParams?: ImplicitGeologyUI;
  onSubmit: (params: ImplicitGeologyUI) => void;
  onCancel: () => void;
}

export function ImplicitGeologyForm({
  litologiasDisponibles,
  nCollares,
  initialParams,
  onSubmit,
  onCancel,
}: Props) {
  const [params, setParams] = useState<ImplicitGeologyUI>(
    initialParams ?? IMPLICIT_GEOLOGY_INICIAL
  );
  const [tabla, setTabla] = useState<LithologyEntry[]>([]);

  useEffect(() => {
    let vivo = true;
    void fetchLithologyProperties().then((filas) => {
      if (vivo) setTabla(filas);
    });
    return () => {
      vivo = false;
    };
  }, []);

  function set<K extends keyof ImplicitGeologyUI>(campo: K, valor: ImplicitGeologyUI[K]) {
    setParams((prev) => ({ ...prev, [campo]: valor }));
  }

  /** Densidad que el backend conoce para una litología, si la conoce. */
  const densidadDeTabla = useMemo(() => {
    const m = new Map<string, number>();
    for (const fila of tabla) {
      if (typeof fila.density_t_m3 === "number") m.set(fila.name.toLowerCase(), fila.density_t_m3);
    }
    return m;
  }, [tabla]);

  function alternarLitologia(nombre: string) {
    const yaEsta = params.target_lithologies.includes(nombre);
    const siguiente = yaEsta
      ? params.target_lithologies.filter((l) => l !== nombre)
      : [...params.target_lithologies, nombre];
    // Al añadir la PRIMERA litología se propone su densidad de tabla. Se propone,
    // no se impone: si el usuario ya tocó el número no se le pisa.
    const propuesta = densidadDeTabla.get(nombre.toLowerCase());
    setParams((prev) => ({
      ...prev,
      target_lithologies: siguiente,
      target_density_t_m3:
        !yaEsta && prev.target_lithologies.length === 0 && propuesta !== undefined
          ? propuesta
          : prev.target_density_t_m3,
    }));
  }

  const sinLitologias = litologiasDisponibles.length === 0;
  const faltaObjetivo = params.enabled && params.target_lithologies.length === 0;
  const puedeGuardar = !params.enabled || !faltaObjetivo;

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-5 w-full max-w-md max-h-[85vh] overflow-y-auto">
      <h3 className="text-[11px] uppercase tracking-[0.2em] text-[#C2D8C4] font-bold mb-1">
        Geología implícita — contacto que acota la inversión
      </h3>
      <p className="text-[9px] text-neutral-500 mb-4 leading-relaxed">
        Usa los contactos litológicos de tus sondajes como <strong>restricción
        geométrica</strong> de la inversión. No es modelamiento geológico: no
        sustituye a Leapfrog ni produce un modelo de bloques geológico.
      </p>

      {sinLitologias ? (
        <p className="text-[10px] text-yellow-400/90 border border-yellow-500/30 rounded px-3 py-2 mb-4 leading-relaxed">
          Ninguno de los sondajes cargados declara litología. El prior geológico
          necesita contactos: sin ellos no se infiere geología.
        </p>
      ) : (
        <label className="flex items-center gap-2 mb-4 cursor-pointer">
          <input
            type="checkbox"
            checked={params.enabled}
            onChange={(e) => set("enabled", e.target.checked)}
            className="w-4 h-4 accent-emerald-500"
          />
          <span className="text-[11px] text-neutral-300">
            Activar prior geológico implícito (HRBF)
          </span>
        </label>
      )}

      {params.enabled && !sinLitologias && (
        <>
          <p className="text-[9px] uppercase tracking-[0.15em] text-neutral-500 mb-2">
            Unidad objetivo
          </p>
          <div className="flex flex-wrap gap-1.5 mb-4">
            {litologiasDisponibles.map((lito) => {
              const activa = params.target_lithologies.includes(lito);
              const conocida = densidadDeTabla.has(lito.toLowerCase());
              return (
                <button
                  key={lito}
                  type="button"
                  onClick={() => alternarLitologia(lito)}
                  title={
                    conocida
                      ? `El backend conoce esta unidad (${densidadDeTabla.get(lito.toLowerCase())} t/m³)`
                      : "Sin densidad tabulada en el backend: escribe tú la de referencia"
                  }
                  className={`px-2 py-1 rounded text-[10px] border transition-colors ${
                    activa
                      ? "bg-emerald-600/25 border-emerald-500/60 text-emerald-200"
                      : "bg-white/[0.03] border-white/10 text-neutral-400 hover:border-white/25"
                  }`}
                >
                  {lito}
                  {conocida ? "" : " *"}
                </button>
              );
            })}
          </div>
          {faltaObjetivo && (
            <p className="text-[9px] text-yellow-400/90 mb-3">
              Elige al menos una litología objetivo.
            </p>
          )}

          <div className="grid grid-cols-2 gap-3 mb-4">
            <label className="block">
              <span className="text-[9px] uppercase tracking-[0.15em] text-neutral-500">
                Densidad objetivo
              </span>
              <input
                type="number"
                step="0.05"
                min="0.1"
                max="10"
                value={params.target_density_t_m3}
                onChange={(e) => set("target_density_t_m3", Number(e.target.value))}
                className="mt-1 w-full bg-black/40 border border-white/10 rounded px-2 py-1 text-[11px] font-mono text-neutral-200"
              />
              <span className="text-[8px] text-neutral-600">t/m³</span>
            </label>
            <label className="block">
              <span className="text-[9px] uppercase tracking-[0.15em] text-neutral-500">
                Densidad caja
              </span>
              <input
                type="number"
                step="0.05"
                min="0.1"
                max="10"
                placeholder="auto"
                value={params.host_density_t_m3 ?? ""}
                onChange={(e) =>
                  set("host_density_t_m3", e.target.value === "" ? null : Number(e.target.value))
                }
                className="mt-1 w-full bg-black/40 border border-white/10 rounded px-2 py-1 text-[11px] font-mono text-neutral-200"
              />
              <span className="text-[8px] text-neutral-600">t/m³ · vacío = base</span>
            </label>
          </div>

          {/* MEDIDO: la regularización sólo ve la DIFERENCIA. Decirlo evita que el
              usuario crea que está fijando dos densidades independientes. */}
          <p className="text-[8px] text-neutral-500 mb-4 leading-relaxed">
            Sólo actúa la <strong>diferencia</strong> entre ambas
            {params.host_density_t_m3 !== null
              ? ` (Δ = ${(params.target_density_t_m3 - params.host_density_t_m3).toFixed(2)} t/m³)`
              : ""}
            : el prior entra por el término de suavidad, que ignora cualquier
            desplazamiento constante del modelo de referencia.
          </p>

          <label className="block mb-4">
            <span className="text-[9px] uppercase tracking-[0.15em] text-neutral-500">
              Suavidad del contacto: {params.softness.toFixed(1)}
            </span>
            <input
              type="range"
              min={0}
              max={5}
              step={0.1}
              value={params.softness}
              onChange={(e) => set("softness", Number(e.target.value))}
              className="mt-1 w-full accent-emerald-500"
            />
            <span className="text-[8px] text-neutral-600">
              0 = contacto neto · valores altos aplanan el prior hasta dejarlo casi sin efecto
            </span>
          </label>

          {nCollares <= 1 && (
            <p className="text-[9px] text-yellow-400/90 border border-yellow-500/30 rounded px-3 py-2 mb-4 leading-relaxed">
              Sólo hay <strong>{nCollares}</strong> sondaje. Está medido que con un
              único collar el campo implícito degenera a un <strong>plano</strong>
              {" "}extrapolado a toda la malla: el resultado dirá dónde está el
              contacto en sitios donde no hay dato. El reporte de la corrida lo
              declara; revísalo antes de decidir.
            </p>
          )}
        </>
      )}

      <div className="flex gap-2 justify-end mt-2">
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-1.5 rounded text-[10px] border border-white/10 text-neutral-400 hover:border-white/25"
        >
          Cancelar
        </button>
        <button
          type="button"
          disabled={!puedeGuardar}
          onClick={() => onSubmit(params)}
          className="px-3 py-1.5 rounded text-[10px] border border-emerald-500/50 bg-emerald-600/20 text-emerald-200 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Guardar
        </button>
      </div>
    </div>
  );
}
