import AnomalyCard from "./AnomalyCard";
import type { GeminiAnomaly } from "./GeophysicalInterpretationSection";

type Props = { anomalies: GeminiAnomaly[] };

export default function AnomaliesGrid({ anomalies }: Props) {
  return (
    <div className="space-y-2">
      <p className="text-[8px] uppercase tracking-widest text-neutral-500 font-bold">
        Cuerpos Geofísicos Anómalos ({anomalies.length})
      </p>
      <div className="grid md:grid-cols-2 gap-3">
        {anomalies.map((a) => (
          <AnomalyCard key={a.id} anomaly={a} />
        ))}
      </div>
    </div>
  );
}
