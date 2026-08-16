"use client";
import React from "react";
import { useAppStore } from "../../store/useAppStore";
import { VIEWS } from "../../lib/terraquantum/views";
import ConnectivityIndicator from "./ConnectivityIndicator";

export default function NavBar() {
  const { view, setView } = useAppStore();

  // FASE 9: la lista ya no vive aquí. Estaba duplicada en NavBar y en los dos
  // sitios de `app/page.tsx`, así que añadir una vista y olvidar uno la hacía
  // caer al HomeView en silencio. Ahora la declara `lib/terraquantum/views.ts`.
  const handleNavClick = (item: string) => {
    setView(item);
  };

  return (
    <nav className="flex justify-center mb-6 shrink-0 print:hidden z-10 relative">
      <div className="px-6 py-2 border border-neutral-800 rounded-full bg-neutral-950/80 backdrop-blur-sm flex items-center gap-8">
        {VIEWS.map((item) => (
          <button
            key={item.id}
            onClick={() => handleNavClick(item.label)}
            className={`text-[10px] uppercase tracking-widest transition-colors ${
              view.toLowerCase() === item.id
                ? "text-[#C2D8C4]"
                : "text-neutral-500 hover:text-white"
            }`}
          >
            {item.label}
          </button>
        ))}

        {/* Separador + estado del motor de cálculo, comprobado de verdad. */}
        <span className="h-3 w-px bg-neutral-800" />
        <ConnectivityIndicator />
      </div>
    </nav>
  );
}
