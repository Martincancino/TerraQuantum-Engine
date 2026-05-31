import { memo } from "react";

type Props = { summary: string };

const ExecutiveSummaryPanel = memo(function ExecutiveSummaryPanel({ summary }: Props) {
  return (
    <div className="bg-neutral-950/30 border border-neutral-800 rounded-2xl p-5 relative">
      <div className="absolute top-0 left-0 w-1 h-full bg-accent/40 rounded-l-2xl" />
      <p className="text-[8px] uppercase tracking-widest text-accent mb-3 ml-2">
        Resumen Ejecutivo
      </p>
      <p className="text-[11px] text-neutral-300 leading-loose font-light ml-2">
        {summary}
      </p>
    </div>
  );
});

export default ExecutiveSummaryPanel;
