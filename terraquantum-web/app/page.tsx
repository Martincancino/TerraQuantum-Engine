"use client";

import React, { useState } from "react";
import { useAppStore } from "../store/useAppStore";
import { normalizeView } from "../lib/terraquantum/views";
import { usePreferenciasVisuales } from "../lib/preferencias/usePreferenciasVisuales";

// Componentes de Layout
import WelcomeScreen from "../componentes/layout/WelcomeScreen";
import NavBar from "../componentes/layout/NavBar";

// Vistas Principales
import HomeView from "../componentes/views/HomeView";
import PreparacionView from "../componentes/views/PreparacionView";
import IAChatView from "../componentes/views/IAChatView";
import Exploration3DView from "../componentes/views/Exploration3DView";
import SistemaView from "../componentes/views/SistemaView";

// Dashboards
import DatosView from "../componentes/DatosView";
import HistorialView from "../componentes/views/HistorialView";

export default function Home() {
  const { view } = useAppStore();
  const [appInitialized, setAppInitialized] = useState(false);

  // FASE 13 — preferencias de visualización entre sesiones. Va aquí porque es el
  // único componente que vive durante toda la sesión, y ANTES del portón de
  // bienvenida a propósito: la lectura ocurre en un efecto (no en el render), y
  // así las preferencias ya están aplicadas cuando el usuario entra al visor.
  //
  // Lo que NO se restaura, y es una decisión de producto, no un olvido: la
  // pantalla de bienvenida y la vista activa. Saltarse el portón cambiaría la
  // primera impresión del producto y devolver al usuario a «figura 3D» sin
  // modelo lo dejaría mirando un visor vacío. Queda declarado en `docs/06`.
  usePreferenciasVisuales();

  // FASE 9: antes había DOS listas de vistas aquí (los ternarios y la lista de
  // exclusión del fallback) más una tercera en NavBar. `normalizeView` deja una
  // sola fuente: un id desconocido cae a "inicio" de forma explícita, no por que
  // ninguna condición encajara.
  const normalizedView = normalizeView(view);

  if (!appInitialized) {
    return <WelcomeScreen onEnter={() => setAppInitialized(true)} />;
  }

  return (
    <main className="h-screen w-screen bg-black text-white font-sans overflow-hidden flex flex-col p-6 relative">
      <NavBar />

      <section className="flex-grow relative overflow-hidden flex flex-col z-0">
        {normalizedView === "inicio" && <HomeView />}

        {normalizedView === "preparación" && <PreparacionView />}

        {normalizedView === "ia geológica" && <IAChatView />}

        {normalizedView === "figura 3d" && <Exploration3DView />}

        {normalizedView === "datos" && <DatosView />}

        {normalizedView === "historial" && <HistorialView />}

        {normalizedView === "sistema" && <SistemaView />}
      </section>
    </main>
  );
}
