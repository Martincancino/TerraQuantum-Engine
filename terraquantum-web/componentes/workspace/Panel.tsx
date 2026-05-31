import React from "react";

/**
 * Panel — superficie premium reutilizable del workspace científico.
 * Presentacional puro (sin estado): se compone en sidebar y analytics.
 */
export default function Panel({
  title,
  subtitle,
  right,
  children,
  className = "",
  bodyClassName = "p-4",
}: {
  title?: string;
  subtitle?: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`tq-panel rounded-2xl overflow-hidden ${className}`}>
      {(title || right) && (
        <header className="flex items-center justify-between gap-3 px-4 py-3 border-b border-white/[0.06]">
          <div className="min-w-0">
            {title && (
              <h3 className="text-[10px] uppercase tracking-[0.22em] text-accent/90 font-semibold truncate">
                {title}
              </h3>
            )}
            {subtitle && (
              <p className="text-[8px] text-white/40 font-mono mt-1 truncate">{subtitle}</p>
            )}
          </div>
          {right && <div className="shrink-0">{right}</div>}
        </header>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}
