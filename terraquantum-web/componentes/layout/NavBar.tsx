"use client";
import React from "react";
import { useAppStore } from "../../store/useAppStore";

export default function NavBar() {
  const { view, setView } = useAppStore();
  
  // Lista centralizada de tu menú
  const menuItems = [
    "inicio",
    "figura 3D",
    "Datos",
    "Historial",
  ];

  // Manejador del click
  const handleNavClick = (item: string) => {
    setView(item);
  };

  return (
    <nav className="flex justify-center mb-6 shrink-0 print:hidden z-10">
      <div className="px-6 py-2 border border-neutral-800 rounded-full bg-neutral-950/80 backdrop-blur-sm flex gap-8">
        {menuItems.map((item) => (
          <button 
            key={item} 
            onClick={() => handleNavClick(item)} 
            className={`text-[10px] uppercase tracking-widest transition-colors ${
              view.toLowerCase() === item.toLowerCase()
                ? "text-[#C2D8C4]"
                : "text-neutral-500 hover:text-white"
            }`}
          >
            {item}
          </button>
        ))}
      </div>
    </nav>
  );
}
