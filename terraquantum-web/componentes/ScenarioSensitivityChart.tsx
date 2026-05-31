"use client";
import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

interface ScenarioPoint {
  price?: number;
  npv?: number;
  tonnage?: number;
  [key: string]: string | number | null | undefined;
}

export default function ScenarioSensitivityChart({ jobId }: { jobId: string | null }) {
  const [data, setData] = useState<ScenarioPoint[]>([]);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    if (!jobId) return;
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/scenario-progress/${jobId}`);
        const json = await res.json();
        if (json.partial_curve) setData(json.partial_curve);
        if (json.progress !== undefined) setProgress(json.progress);
        if (json.status === "done") clearInterval(interval);
      } catch (e: unknown) { console.error(e); }
    }, 1500);
    return () => clearInterval(interval);
  }, [jobId]);

  if (!jobId) return null;

  return (
    <div className="w-full h-full flex flex-col font-sans text-gray-200">
      <div className="mb-3 text-[9px] text-[#348ceb] uppercase tracking-widest font-bold flex justify-between">
        <span>Curva Sensibilidad</span>
        <span>{(progress * 100).toFixed(0)}%</span>
      </div>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <XAxis dataKey="price" stroke="#555" tick={{fontSize: 8}} tickFormatter={(v) => `$${v/1000}k`} />
          <YAxis yAxisId="left" stroke="#22c55e" tick={{fontSize: 8}} tickFormatter={(v) => `${(v/1e6).toFixed(0)}M`} width={35} />
          <Tooltip contentStyle={{ backgroundColor: "#050505", border: "1px solid #333", fontSize: "10px", borderRadius: "8px" }} />
          <Line yAxisId="left" type="monotone" dataKey="npv" stroke="#22c55e" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}