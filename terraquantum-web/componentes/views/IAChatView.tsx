import React, { useState, useRef, useEffect } from "react";
import { useAppStore } from "../../store/useAppStore";

type ChatMode = "explicar" | "redactar" | "ensenar";

interface GroundingMeta {
  redacted: boolean;
  ungrounded: string[];
}

interface ChatMessage {
  role: "user" | "model";
  content: string;
  grounding?: GroundingMeta;
}

const MODE_LABELS: { key: ChatMode | null; label: string; hint: string }[] = [
  { key: null, label: "General", hint: "Chat libre anclado a la corrida" },
  { key: "explicar", label: "Explicar", hint: "Explica el veredicto y las métricas de esta corrida" },
  { key: "redactar", label: "Redactar", hint: "Borrador de sección de informe (lo editas y firmas tú)" },
  { key: "ensenar", label: "Enseñar", hint: "Glosario minero-geofísico en español simple" },
];

const QUICK_ACTIONS: { label: string; mode: ChatMode; text: string; needsRun: boolean }[] = [
  {
    label: "Explícame el veredicto",
    mode: "explicar",
    text: "¿Por qué el veredicto de esta corrida es el que es? Explícamelo apoyándote en la trilogía B1/B2/B3 y el χ².",
    needsRun: true,
  },
  {
    label: "Borrador de informe",
    mode: "redactar",
    text: "Redacta un borrador de la sección de resultados del informe geofísico para esta corrida.",
    needsRun: true,
  },
  {
    label: "¿Qué es el χ² reducido?",
    mode: "ensenar",
    text: "¿Qué es el χ² reducido y cómo lo interpreto en una inversión gravimétrica?",
    needsRun: false,
  },
];

const KEY_STORAGE = "tq_gemini_api_key";

export default function IAChatView() {
  const { activeRun, report } = useAppStore();
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "model",
      content: "Hola. Soy Antigravity IA, tu asistente geológico integrado. Analizo los resultados de la inversión geofísica y reportes técnicos para darte soporte avanzado. ¿En qué te puedo ayudar hoy?"
    }
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [mode, setMode] = useState<ChatMode | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // BYO-key: la clave vive SOLO en este navegador (local-first) y viaja directo a Google.
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(KEY_STORAGE);
      if (stored) setApiKey(stored);
    } catch {
      /* localStorage no disponible: se usa la clave del servidor */
    }
  }, []);

  const handleKeyChange = (value: string) => {
    setApiKey(value);
    try {
      if (value.trim()) window.localStorage.setItem(KEY_STORAGE, value.trim());
      else window.localStorage.removeItem(KEY_STORAGE);
    } catch {
      /* noop */
    }
  };

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const sendMessage = async (text: string, sendMode: ChatMode | null) => {
    if (!text.trim() || isLoading) return;

    const newMessages = [...messages, { role: "user", content: text } as ChatMessage];
    setMessages(newMessages);
    setInput("");
    setIsLoading(true);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: activeRun.projectId || "demo_project",
          run_id: activeRun.runId || "demo_run",
          messages: newMessages.map((m) => ({ role: m.role, content: m.content })),
          mode: sendMode,
          api_key: apiKey.trim() || undefined,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        const detail = typeof data?.detail === "string" ? data.detail : "Error en la respuesta del servidor";
        throw new Error(detail);
      }

      setMessages([
        ...newMessages,
        { role: "model", content: data.response, grounding: data.grounding },
      ]);
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      setMessages([
        ...newMessages,
        { role: "model", content: `Error de conexión con la IA: ${msg}` },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSend = () => sendMessage(input, mode);

  const handleQuickAction = (action: (typeof QUICK_ACTIONS)[number]) => {
    setMode(action.mode);
    sendMessage(action.text, action.mode);
  };

  const isModelLoaded = !!(activeRun.projectId && activeRun.runId);

  return (
    <div className="flex h-full w-full bg-[#050505] text-neutral-200 font-sans overflow-hidden border border-white/5 rounded-2xl shadow-2xl">
      {/* Sidebar: Contexto del Modelo (Modern Glassmorphism) */}
      <div className="w-[300px] shrink-0 bg-[#0a0a0a]/80 backdrop-blur-2xl border-r border-white/5 p-6 flex flex-col gap-6 overflow-y-auto relative z-10">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-2xl bg-gradient-to-tr from-blue-600 via-indigo-600 to-purple-600 flex items-center justify-center shadow-[0_0_20px_rgba(79,70,229,0.3)]">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="white" className="w-5 h-5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5" />
            </svg>
          </div>
          <div>
            <h2 className="text-[10px] uppercase tracking-widest text-neutral-500 font-bold mb-0.5">Contexto IA</h2>
            <div className="text-sm text-white font-medium tracking-wide">Antigravity Engine</div>
          </div>
        </div>

        <div className="flex flex-col gap-3 mt-2">
          <div className="text-[10px] font-bold uppercase tracking-wider text-neutral-500">Workspace Activo</div>
          <div className="bg-white/[0.02] p-4 rounded-2xl border border-white/5 shadow-sm backdrop-blur-md">
            <div className="text-xs flex justify-between items-center">
              <span className="text-neutral-500">Proyecto</span>
              <span className={isModelLoaded ? "text-blue-400 font-medium" : "text-yellow-500"}>
                {activeRun.projectId || "Ninguno"}
              </span>
            </div>
            <div className="text-xs flex justify-between items-center mt-3 pt-3 border-t border-white/5">
              <span className="text-neutral-500">Corrida</span>
              <span className={isModelLoaded ? "text-purple-400 font-medium" : "text-yellow-500"}>
                {activeRun.runId || "Ninguna"}
              </span>
            </div>
          </div>
        </div>

        {/* Acciones rápidas */}
        <div className="flex flex-col gap-3">
          <div className="text-[10px] font-bold uppercase tracking-wider text-neutral-500">Acciones Rápidas</div>
          <div className="flex flex-col gap-2">
            {QUICK_ACTIONS.map((action) => {
              const disabled = isLoading || (action.needsRun && !isModelLoaded);
              return (
                <button
                  key={action.label}
                  onClick={() => handleQuickAction(action)}
                  disabled={disabled}
                  title={action.needsRun && !isModelLoaded ? "Carga una corrida para usar esta acción" : action.text}
                  className="text-left text-xs px-3 py-2.5 rounded-xl bg-white/[0.02] border border-white/5 text-neutral-300 hover:border-blue-500/30 hover:bg-blue-500/[0.06] hover:text-white disabled:opacity-40 disabled:hover:bg-white/[0.02] disabled:hover:border-white/5 disabled:cursor-not-allowed transition-all"
                >
                  {action.label}
                </button>
              );
            })}
          </div>
        </div>

        {report && (
          <div className="flex flex-col gap-3">
            <div className="text-[10px] font-bold uppercase tracking-wider text-neutral-500">Métricas Clave</div>
            <div className="bg-white/[0.02] p-4 rounded-2xl border border-white/5 shadow-sm backdrop-blur-md space-y-3 text-xs">
              <div className="flex justify-between items-center">
                <span className="text-neutral-500">Nivel de Riesgo</span>
                <span className="text-white font-medium bg-red-500/10 text-red-400 px-2 py-0.5 rounded-md border border-red-500/20">{report.risk_level || "N/A"}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-neutral-500">Masa Estimada</span>
                <span className="text-blue-300 font-mono bg-blue-500/10 px-2 py-0.5 rounded-md">
                  {report.masaKg ? `${report.masaKg.toExponential(2)} kg` : "N/A"}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-neutral-500">Confidence</span>
                <span className="text-green-400 font-mono bg-green-500/10 px-2 py-0.5 rounded-md">{report.score || "N/A"}</span>
              </div>
            </div>
          </div>
        )}

        {/* BYO-key: clave de Gemini del consultor (local-first) */}
        <div className="flex flex-col gap-3">
          <div className="text-[10px] font-bold uppercase tracking-wider text-neutral-500">API Key de Gemini</div>
          <div className="bg-white/[0.02] p-4 rounded-2xl border border-white/5 shadow-sm backdrop-blur-md flex flex-col gap-2">
            <div className="relative">
              <input
                type={showKey ? "text" : "password"}
                value={apiKey}
                onChange={(e) => handleKeyChange(e.target.value)}
                placeholder="Pega tu clave (opcional)"
                autoComplete="off"
                spellCheck={false}
                className="w-full bg-black/40 border border-white/10 rounded-lg px-3 py-2 pr-9 text-xs text-white placeholder-neutral-600 outline-none focus:border-blue-500/40 font-mono"
              />
              <button
                type="button"
                onClick={() => setShowKey((s) => !s)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-neutral-500 hover:text-neutral-300 uppercase tracking-wider"
              >
                {showKey ? "ocultar" : "ver"}
              </button>
            </div>
            <div className="flex items-center gap-1.5">
              <span className={`w-1.5 h-1.5 rounded-full ${apiKey.trim() ? "bg-green-400" : "bg-neutral-600"}`}></span>
              <span className="text-[10px] text-neutral-500">
                {apiKey.trim() ? "Usando tu clave" : "Usando la clave del servidor"}
              </span>
            </div>
            <p className="text-[10px] text-neutral-600 leading-relaxed">
              Se guarda solo en este navegador y viaja directo a Google con tu cuenta. Nada se comparte con TerraQuantum.
            </p>
          </div>
        </div>

        <div className="mt-auto pb-4">
          <div className="p-4 rounded-2xl bg-gradient-to-br from-blue-900/10 to-purple-900/10 border border-blue-500/10">
            <p className="text-[10px] text-blue-200/60 leading-relaxed text-center">
              Asistente potenciado por <span className="text-blue-400 font-medium">Antigravity IA</span>.
            </p>
          </div>
        </div>
      </div>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col relative bg-[#050505]">
        {/* Background glow effects */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-3/4 h-32 bg-blue-500/5 blur-[100px] pointer-events-none rounded-full"></div>

        <div className="p-6 flex items-center justify-between bg-transparent z-20">
          <h1 className="text-sm font-semibold tracking-wide text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-400">
            Chat Geológico
          </h1>
          {/* FASE 9 — este badge decía «Online» con un punto verde palpitante y
              NO comprobaba absolutamente nada: era literal, fijo en el JSX. El
              copiloto necesita internet y una clave, así que el único estado
              honesto que esta vista conoce sin salir a la red es de dónde saldría
              la clave. Lo que sí se comprueba de verdad (que el motor de cálculo
              responde) vive en la barra de navegación. */}
          <div
            data-testid="copilot-key-source"
            className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/[0.03] border border-white/5 backdrop-blur-md"
            title={
              apiKey.trim()
                ? "Se usará la clave que pegaste. Requiere internet."
                : "Sin clave propia: se intentará la del servidor, si la hay. Requiere internet."
            }
          >
            <div
              className={`w-1.5 h-1.5 rounded-full ${
                apiKey.trim() ? "bg-green-400 shadow-[0_0_8px_rgba(74,222,128,0.8)]" : "bg-neutral-600"
              }`}
            ></div>
            <span className="text-[10px] font-medium text-neutral-400 uppercase tracking-widest">
              {apiKey.trim() ? "Clave propia" : "Sin clave propia"}
            </span>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 md:px-12 pb-32 space-y-8 scroll-smooth custom-scrollbar" ref={scrollRef}>
          {messages.map((msg, idx) => (
            <div key={idx} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"} animate-fadeIn`}>
              <div className={`flex gap-4 max-w-[85%] ${msg.role === "user" ? "flex-row-reverse" : "flex-row"}`}>

                {/* Avatar */}
                <div className="shrink-0 pt-1">
                  {msg.role === "model" ? (
                    <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-600 to-purple-600 flex items-center justify-center shadow-lg shadow-blue-500/20">
                      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="white" className="w-4 h-4">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
                      </svg>
                    </div>
                  ) : (
                    <div className="w-8 h-8 rounded-full bg-neutral-800 flex items-center justify-center border border-white/10 shadow-inner">
                      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="#a3a3a3" className="w-4 h-4">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
                      </svg>
                    </div>
                  )}
                </div>

                {/* Bubble */}
                <div className="flex flex-col gap-1.5">
                  <div
                    className={`p-5 rounded-3xl ${
                      msg.role === "user"
                        ? "bg-white/[0.05] border border-white/10 text-white rounded-tr-sm"
                        : "bg-gradient-to-b from-blue-900/10 to-transparent border border-blue-500/10 text-neutral-200 rounded-tl-sm"
                    } shadow-lg backdrop-blur-md`}
                  >
                    <div className="whitespace-pre-wrap text-[13px] leading-relaxed font-light">
                      {msg.content}
                    </div>
                  </div>

                  {/* Indicador honesto de anclaje (solo respuestas del modelo con metadata) */}
                  {msg.role === "model" && msg.grounding && (
                    msg.grounding.redacted ? (
                      <span className="self-start text-[10px] px-2 py-0.5 rounded-md bg-red-500/10 text-red-400 border border-red-500/20">
                        Redactado por compliance JORC/NI 43-101
                      </span>
                    ) : msg.grounding.ungrounded.length > 0 ? (
                      <span className="self-start text-[10px] px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-400 border border-amber-500/20">
                        ⚠ {msg.grounding.ungrounded.length} cifra(s) sin anclar a la corrida — verifícalas
                      </span>
                    ) : (
                      <span className="self-start text-[10px] px-2 py-0.5 rounded-md bg-green-500/10 text-green-400 border border-green-500/20">
                        ⚓ Anclado a los datos de esta corrida
                      </span>
                    )
                  )}
                </div>
              </div>
            </div>
          ))}
          {isLoading && (
            <div className="flex justify-start animate-fadeIn">
              <div className="flex gap-4 max-w-[80%] flex-row">
                <div className="shrink-0 pt-1">
                  <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-600 to-purple-600 flex items-center justify-center shadow-lg shadow-blue-500/20">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="white" className="w-4 h-4">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
                    </svg>
                  </div>
                </div>
                <div className="px-6 py-5 rounded-3xl bg-white/[0.02] border border-white/5 rounded-tl-sm flex items-center gap-2 shadow-sm">
                  <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce"></div>
                  <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce delay-100"></div>
                  <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce delay-200"></div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Floating Input Area */}
        <div className="absolute bottom-0 left-0 right-0 p-6 md:px-12 md:pb-8 bg-gradient-to-t from-[#050505] via-[#050505] to-transparent pt-20 pointer-events-none">
          <div className="max-w-4xl mx-auto relative group pointer-events-auto">
            {/* Selector de modo del copiloto */}
            <div className="flex items-center gap-2 mb-3 flex-wrap">
              {MODE_LABELS.map((m) => (
                <button
                  key={m.label}
                  onClick={() => setMode(m.key)}
                  title={m.hint}
                  className={`text-[11px] px-3 py-1.5 rounded-full border transition-all ${
                    mode === m.key
                      ? "bg-blue-500/15 border-blue-500/40 text-blue-300 font-medium"
                      : "bg-white/[0.02] border-white/10 text-neutral-400 hover:text-neutral-200 hover:border-white/20"
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>

            <div className="absolute -inset-0.5 bg-gradient-to-r from-blue-500 to-purple-500 rounded-[28px] blur-md opacity-20 group-hover:opacity-40 transition duration-500"></div>
            <div className="relative flex items-end gap-3 bg-[#0a0a0a] p-2 rounded-[24px] border border-white/10 shadow-2xl focus-within:border-white/20 transition-all">
              <textarea
                className="flex-1 bg-transparent resize-none outline-none max-h-32 text-sm p-3 pl-4 text-white placeholder-neutral-500 font-light scroll-smooth"
                placeholder="Hazle una pregunta a Antigravity IA..."
                rows={1}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
              />
              <button
                onClick={handleSend}
                disabled={isLoading || !input.trim()}
                className="mb-1 mr-1 p-3 bg-white text-black hover:bg-neutral-200 hover:scale-105 disabled:hover:scale-100 disabled:bg-neutral-800 disabled:text-neutral-600 rounded-2xl transition-all shadow-lg active:scale-95 flex items-center justify-center group/btn"
              >
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor" className="w-5 h-5 group-disabled/btn:opacity-50">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 10.5L12 3m0 0l7.5 7.5M12 3v18" />
                </svg>
              </button>
            </div>
            <div className="text-center mt-4 hidden md:block">
              <p className="text-[10px] text-neutral-600 tracking-wide font-light">Antigravity IA puede cometer errores. Considera verificar la información técnica.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
