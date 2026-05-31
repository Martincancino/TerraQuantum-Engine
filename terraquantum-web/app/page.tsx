"use client";

import React, { useState } from "react";
import { useAppStore } from "../store/useAppStore";

// Componentes de Layout
import WelcomeScreen from "../componentes/layout/WelcomeScreen";
import NavBar from "../componentes/layout/NavBar";

// Vistas Principales
import HomeView from "../componentes/views/HomeView";
import IAChatView from "../componentes/views/IAChatView";
import Exploration3DView from "../componentes/views/Exploration3DView";

// Dashboards
import DatosView from "../componentes/DatosView";
import HistorialView from "../componentes/views/HistorialView";

export default function Home() {
  const { view } = useAppStore();
  const [appInitialized, setAppInitialized] = useState(false);

  const normalizedView = String(view || "inicio").toLowerCase().trim();

  if (!appInitialized) {
    return <WelcomeScreen onEnter={() => setAppInitialized(true)} />;
  }

  return (
    <main className="h-screen w-screen bg-black text-white font-sans overflow-hidden flex flex-col p-6 relative">
      <NavBar />

      <section className="flex-grow relative overflow-hidden flex flex-col z-0">
        {normalizedView === "inicio" && <HomeView />}

        {normalizedView === "ia geológica" && <IAChatView />}

        {normalizedView === "figura 3d" && <Exploration3DView />}

        {normalizedView === "datos" && <DatosView />}

        {normalizedView === "historial" && <HistorialView />}

        {!["inicio", "ia geológica", "figura 3d", "datos", "historial"].includes(
          normalizedView
        ) && <HomeView />}
      </section>
    </main>
  );
}
