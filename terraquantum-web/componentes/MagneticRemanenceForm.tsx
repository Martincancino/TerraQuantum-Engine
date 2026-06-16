"use client";

import { useState } from "react";

export type InversionMode = "induced_only" | "total_field" | "amplitude";

export interface MagneticRemanenceParamsUI {
  enabled: boolean;
  /** Ratio Koenigsberger Q = |J_rem| / |J_ind|. 0 = solo inducida. */
  q_ratio: number;
  /** Inclinación de la remanencia [°]. */
  remanence_inc_deg: number;
  /** Declinación de la remanencia [°]. */
  remanence_dec_deg: number;
  /** Modo de inversión. */
  inversion_mode: InversionMode;
  /** Barrer Q de 0 a q_ratio y reportar Q óptimo por misfit. */
  do_q_sweep: boolean;
}

interface MagneticRemanenceFormProps {
  initialParams?: MagneticRemanenceParamsUI;
  onSubmit: (params: MagneticRemanenceParamsUI) => void;
  onCancel: () => void;
}

const MODE_LABELS: Record<InversionMode, string> = {
  induced_only: "Solo inducida (default)",
  total_field: "Campo total (J_ind + Q·J_rem)",
  amplitude: "Amplitud |J_total| — dir.-independiente",
};

export function MagneticRemanenceForm({ initialParams, onSubmit, onCancel }: MagneticRemanenceFormProps) {
  const [params, setParams] = useState<MagneticRemanenceParamsUI>(
    initialParams ?? {
      enabled: false,
      q_ratio: 1.0,
      remanence_inc_deg: -45.0,
      remanence_dec_deg: 0.0,
      inversion_mode: "induced_only",
      do_q_sweep: false,
    }
  );

  function set<K extends keyof MagneticRemanenceParamsUI>(field: K, value: MagneticRemanenceParamsUI[K]) {
    setParams((prev) => ({ ...prev, [field]: value }));
  }

  return (
    <div className="bg-neutral-900 border border-neutral-700 rounded-lg p-5 w-full max-w-sm">
      <h3 className="text-[11px] uppercase tracking-[0.2em] text-[#C2D8C4] font-bold mb-4">
        Remanencia Magnética (Koenigsberger Q)
      </h3>

      <label className="flex items-center gap-2 mb-4 cursor-pointer">
        <input
          type="checkbox"
          checked={params.enabled}
          onChange={(e) => set("enabled", e.target.checked)}
          className="w-4 h-4 accent-orange-500"
        />
        <span className="text-[11px] text-neutral-300">Incluir magnetización remanente</span>
      </label>

      {params.enabled && (
        <div className="flex flex-col gap-4">
          <p className="text-[10px] text-neutral-500">
            Modela J = J_ind + Q·J_rem. Útil para basaltos, magnetita y rocas con NRM fuerte.
          </p>

          <div>
            <label className="block text-[10px] text-neutral-400 mb-1">
              Modo de inversión
            </label>
            <select
              value={params.inversion_mode}
              onChange={(e) => set("inversion_mode", e.target.value as InversionMode)}
              className="w-full bg-neutral-800 border border-neutral-700 text-neutral-300 text-[10px] rounded px-2 py-1.5"
            >
              {(Object.keys(MODE_LABELS) as InversionMode[]).map((m) => (
                <option key={m} value={m}>{MODE_LABELS[m]}</option>
              ))}
            </select>
          </div>

          {params.inversion_mode !== "induced_only" && (
            <>
              <div>
                <label className="block text-[10px] text-neutral-400 mb-1">
                  Q-ratio (|J_rem|/|J_ind|): <span className="text-[#C2D8C4] font-bold">{params.q_ratio.toFixed(1)}</span>
                </label>
                <input
                  type="range"
                  min={0}
                  max={10}
                  step={0.1}
                  value={params.q_ratio}
                  onChange={(e) => set("q_ratio", parseFloat(e.target.value))}
                  className="w-full accent-orange-500"
                />
                <p className="text-[9px] text-neutral-600 mt-1">
                  Q&lt;1 = inducida domina. Q=1 = iguales. Q&gt;1 = remanente domina.
                </p>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[10px] text-neutral-400 mb-1">
                    Inc. rem. [°]: <span className="text-[#C2D8C4] font-bold">{params.remanence_inc_deg}</span>
                  </label>
                  <input
                    type="range"
                    min={-90}
                    max={90}
                    step={5}
                    value={params.remanence_inc_deg}
                    onChange={(e) => set("remanence_inc_deg", parseFloat(e.target.value))}
                    className="w-full accent-orange-500"
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-neutral-400 mb-1">
                    Dec. rem. [°]: <span className="text-[#C2D8C4] font-bold">{params.remanence_dec_deg}</span>
                  </label>
                  <input
                    type="range"
                    min={-180}
                    max={180}
                    step={5}
                    value={params.remanence_dec_deg}
                    onChange={(e) => set("remanence_dec_deg", parseFloat(e.target.value))}
                    className="w-full accent-orange-500"
                  />
                </div>
              </div>

              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={params.do_q_sweep}
                  onChange={(e) => set("do_q_sweep", e.target.checked)}
                  className="w-4 h-4 accent-orange-500"
                />
                <span className="text-[10px] text-neutral-300">Sweep automático de Q (reportar Q óptimo)</span>
              </label>
            </>
          )}
        </div>
      )}

      <div className="flex gap-2 mt-5">
        <button
          onClick={() => onSubmit(params)}
          className="flex-1 py-2 bg-orange-600 hover:bg-orange-500 text-white text-[10px] uppercase tracking-widest font-bold rounded transition-colors"
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
