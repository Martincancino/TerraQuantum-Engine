type Props = { assessment: string };

export default function OverallAssessmentPanel({ assessment }: Props) {
  return (
    <div className="bg-neutral-950/60 border border-neutral-800 rounded-2xl p-5">
      <p className="text-[8px] uppercase tracking-widest text-neutral-500 mb-3">
        Evaluación Global del Prospecto
      </p>
      <p className="text-[11px] text-neutral-300 leading-loose font-light">
        {assessment}
      </p>
    </div>
  );
}
