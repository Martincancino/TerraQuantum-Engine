"use client";
import React from "react";
import { useAppStore } from "../../store/useAppStore";

export default function MapeoIAView() {
  const { geologistNote, setGeologistNote, extractedTags, setView } = useAppStore();

  return (
    <div className="h-full flex gap-8 animate-fadeIn">
      {/* Panel Izquierdo: Input del Geólogo */}
      <div className="flex-[1.5] bg-neutral-900/30 border border-neutral-800 rounded-3xl p-8 flex flex-col">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-2 h-2 bg-[#C2D8C4] rounded-full animate-pulse" />
          <h2 className="text-lg font-light tracking-[0.2em] text-[#C2D8C4]">
            DIARIO DE TERRENO (INPUT HUMANO)
          </h2>
        </div>
        <textarea 
          value={geologistNote} 
          onChange={(e) => setGeologistNote(e.target.value)} 
          placeholder="Ej: Fuerte alteración superficial. Vetillas de cuarzo con trazas de cobre..." 
          className="flex-grow bg-black border border-neutral-800 rounded-2xl p-6 text-sm text-neutral-300 font-mono resize-none outline-none focus:border-[#C2D8C4] transition-colors" 
        />
        <div className="mt-6 flex justify-between items-center">
          <span className="text-[10px] text-neutral-500 uppercase tracking-widest">Motor NLP — Vista Conceptual</span>
          <button 
            onClick={() => setView("figura 3D")} 
            className="px-8 py-3 bg-[#C2D8C4] text-black text-[10px] font-bold uppercase tracking-widest rounded-xl hover:bg-white transition-all"
          >
            Ir a Inversión 3D →
          </button>
        </div>
      </div>

      {/* Panel Derecho: NLP Extraído */}
      <div className="flex-1 bg-[#050a05] border border-neutral-800 rounded-3xl p-8 relative overflow-hidden flex flex-col">
        <div className="absolute top-0 left-0 w-1 h-full bg-[#C2D8C4]/50" />
        <h3 className="text-[10px] uppercase tracking-[0.2em] text-[#C2D8C4] font-bold mb-6">
          Vectores NLP Extraídos
        </h3>
        <div className="flex-grow">
          {(!extractedTags || extractedTags.length === 0) ? (
            <div className="h-full flex flex-col items-center justify-center text-center opacity-50">
              <p className="text-[10px] uppercase tracking-widest">Esperando ingreso...</p>
            </div>
          ) : (
            <div className="space-y-6 animate-fadeIn">
              <div className="flex flex-wrap gap-2">
                {extractedTags.map((tag, i) => (
                  <span 
                    key={i} 
                    className={`px-4 py-2 rounded-full text-[10px] font-bold uppercase tracking-widest border ${
                      tag.includes('ALERTA') 
                        ? 'bg-red-900/20 text-red-400 border-red-900/50' 
                        : 'bg-[#C2D8C4]/10 text-[#C2D8C4] border-[#C2D8C4]/30'
                    }`}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}