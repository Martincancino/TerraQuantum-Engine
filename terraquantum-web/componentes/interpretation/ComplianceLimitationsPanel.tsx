import { memo } from "react";

type Props = { limitations: string };

const ComplianceLimitationsPanel = memo(function ComplianceLimitationsPanel({ limitations }: Props) {
  return (
    <div className="bg-neutral-950/40 border border-neutral-800/60 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[8px] text-neutral-600">⚠</span>
        <p className="text-[7px] uppercase tracking-widest text-neutral-600 font-bold">
          Limitaciones y Compliance
        </p>
      </div>
      <p className="text-[10px] text-neutral-600 leading-relaxed font-light">
        {limitations}
      </p>
    </div>
  );
});

export default ComplianceLimitationsPanel;
