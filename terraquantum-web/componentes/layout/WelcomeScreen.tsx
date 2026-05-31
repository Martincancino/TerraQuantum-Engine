"use client";
import React, { useState, useEffect } from "react";

interface WelcomeScreenProps {
  onEnter: () => void;
}

export default function WelcomeScreen({ onEnter }: WelcomeScreenProps) {
  const word = "BIENVENIDO";
  const [showWelcome, setShowWelcome] = useState(true);
  const [isFading, setIsFading] = useState(false);

  useEffect(() => {
    // Animación de entrada y desvanecimiento
    const timerFade = setTimeout(() => setIsFading(true), 2500);
    const timerHide = setTimeout(() => setShowWelcome(false), 4000);

    return () => {
      clearTimeout(timerFade);
      clearTimeout(timerHide);
    };
  }, []);

  return (
    <main className="h-screen w-screen bg-black text-white flex flex-col items-center justify-center relative overflow-hidden">
      <h1 className="text-7xl font-extrabold tracking-[0.2em] text-transparent bg-clip-text bg-gradient-to-b from-white to-neutral-500">
        TERRAQUANTUM
      </h1>
      
      <button 
        type="button"
        onClick={onEnter} 
        className="mt-16 px-10 py-4 border border-neutral-800 rounded-full hover:bg-white hover:text-black transition-all uppercase text-xs tracking-widest z-[60] relative"
      >
        Entrar a la Plataforma
      </button>

      {/* Capa de Bienvenida con letras cayendo */}
      {showWelcome && (
        <div
          aria-hidden="true"
          className={`pointer-events-none absolute inset-0 z-50 flex flex-col items-center justify-center bg-black transition-opacity duration-1000 ${isFading ? "opacity-0" : "opacity-100"}`}
        >
          <div className="flex overflow-hidden pb-2">
            {word.split("").map((l, i) => (
              <span 
                key={i} 
                className="text-6xl font-light tracking-[0.3em] transition-transform duration-700 translate-y-0" 
                style={{ transitionDelay: `${i * 100}ms` }}
              >
                {l}
              </span>
            ))}
          </div>
        </div>
      )}
    </main>
  );
}
