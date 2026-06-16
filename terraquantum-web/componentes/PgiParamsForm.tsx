"use client";

import { useState } from "react";

export interface PgiParamsUI {
  enabled: boolean;
  /** K-classes para fit_from_model=True (2–10). */
  n_components_auto: number;
  /** Peso del término PGI en la función objetivo. */
  alpha_pgi: number;
  /** Iteraciones máximas del bucle PGI. */
  max_iter: number;
}

interface PgiParamsFormProps {
  initialParams?: PgiParamsUI;
  onSubmit: (params: PgiParamsUI) => void;
  onCancel: () => void;
}

export function PgiParamsForm({ initialParams, onSubmit, onCancel }: PgiParamsFormProps) {
  const [params, setParams] = useState<PgiParamsUI>(
    initialParams ?? {
      enabled: false,
      n_components_auto: 3,
      alpha_pgi: 0.1,
      max_iter: 10,
    }
  );

  function set<K extends keyof PgiParamsUI>(field: K, value: PgiParamsUI[K]) {
    setParams((prev) => ({ ...prev, [field]: value }));
  }

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-5 w-full max-w-sm">
      <h3 className="text-[11px] uppercase tracking-[0.2em] text-[#C2D8C4] font-bold mb-4">
        PGI — Inversión Guiada Petrológica
      </h3>

      <label className="flex items-center gap-2 mb-4 cursor-pointer">
        <input
          type="checkbox"
          checked={params.enabled}
          onChange={(e) => set("enabled", e.target.checked)}
          className="w-4 h-4 accent-purple-500"
        />
        <span className="text-[11px] text-neutral-300">Activar PGI (Astic &amp; Oldenburg 2019)</span>
      </label>

      {params.enabled && (
        <div className="flex flex-col gap-4">
          <p className="text-[10px] text-neutral-500">
            El GMM se ajusta automáticamente desde la inversión inicial. Use K-clases para
            controlar cuántos dominios petrológicos puede resolver el modelo.
          </p>

          <div>
            <label className="block text-[10px] text-neutral-400 mb-1">
              K-clases (dominios petrológicos): <span className="text-[#C2D8C4] font-bold">{params.n_components_auto}</span>
            </label>
            <input
              type="range"
              min={2}
              max={10}
              step={1}
              value={params.n_components_auto}
              onChange={(e) => set("n_components_auto", parseInt(e.target.value))}
              className="w-full accent-purple-500"
            />
            <p className="text-[9px] text-neutral-600 mt-1">
              2 = fondo + cuerpo. 3+ para mineralización estratiforme. Máx 10.
            </p>
          </div>

          <div>
            <label className="block text-[10px] text-neutral-400 mb-1">
              Peso PGI (α): <span className="text-[#C2D8C4] font-bold">{params.alpha_pgi.toFixed(2)}</span>
            </label>
            <input
              type="range"
              min={0.01}
              max={5.0}
              step={0.01}
              value={params.alpha_pgi}
              onChange={(e) => set("alpha_pgi", parseFloat(e.target.value))}
              className="w-full accent-purple-500"
            />
            <p className="text-[9px] text-neutral-600 mt-1">
              Mayor α = más adherencia al GMM (puede sobreajustar si hay pocos datos).
            </p>
          </div>

          <div>
            <label className="block text-[10px] text-neutral-400 mb-1">
              Iteraciones PGI: <span className="text-[#C2D8C4] font-bold">{params.max_iter}</span>
            </label>
            <input
              type="range"
              min={1}
              max={50}
              step={1}
              value={params.max_iter}
              onChange={(e) => set("max_iter", parseInt(e.target.value))}
              className="w-full accent-purple-500"
            />
          </div>
        </div>
      )}

      <div className="flex gap-2 mt-5">
        <button
          onClick={() => onSubmit(params)}
          className="flex-1 py-2 bg-purple-600 hover:bg-purple-500 text-white text-[10px] uppercase tracking-widest font-bold rounded transition-colors"
        >
          Aplicar
        </button>
        <button
          onClick={onCancel}
          className="flex-1 py-2 bg-neutral-700 hover:bg-neutral-600 text-neutral-300 text-[10px] uppercase tracking-widest rounded transition-colors"
        >
          Cancelar
        </button>
      </div>
    </div>
  );
}
