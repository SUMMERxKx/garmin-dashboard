import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { RULE_TONE, type Tone } from "@/lib/tones";
import { cn } from "@/lib/utils";

/**
 * The panel everything sits in, and the header that names it.
 *
 * Square corners, a hairline border, a flat surface. No blur and no glow: the previous
 * design's blurred backdrops were re-composited on every scroll frame, and that was half
 * of the clunky scroll. A flat panel costs nothing to scroll past.
 *
 * The accent colour appears once per panel, as a short rule beside the title. That is
 * enough to tie a panel to the colour of its chart without tinting the whole thing --
 * panels stay comparable at a glance instead of each reading as its own coloured object.
 */

export function Panel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("flex flex-col border border-hull-700 bg-hull-900", className)}>
      {children}
    </section>
  );
}

export function PanelHeader({
  icon: Icon,
  title,
  tone = "tele",
  meta,
  note,
}: {
  icon?: LucideIcon;
  title: string;
  tone?: Tone;
  /** Right-aligned small print: a date, a count. */
  meta?: ReactNode;
  /** A sentence under the title saying what the panel shows and which way is good. */
  note?: string;
}) {
  return (
    <header className="border-b border-hull-700 px-4 pt-3 pb-2.5">
      <div className="flex items-center justify-between gap-3">
        <span className="flex min-w-0 items-center gap-2.5">
          <span className={cn("h-3 w-0.5 shrink-0", RULE_TONE[tone])} aria-hidden="true" />
          {Icon !== undefined && (
            <Icon className="size-3.5 shrink-0 text-hull-300" strokeWidth={1.75} aria-hidden="true" />
          )}
          <h3 className="readout-label truncate !text-hull-200">{title}</h3>
        </span>
        {meta !== undefined && (
          <span className="tabular shrink-0 font-mono text-[0.66rem] text-hull-400">{meta}</span>
        )}
      </div>
      {note !== undefined && <p className="mt-1 text-[0.7rem] leading-snug text-hull-400">{note}</p>}
    </header>
  );
}

/** Where a panel's content goes. Consistent padding, so panels line up. */
export function PanelBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("flex flex-1 flex-col px-4 pt-3.5 pb-4", className)}>{children}</div>;
}

/** A page title block: what this page is, in the telemetry voice. */
export function PageTitle({
  code,
  title,
  description,
  aside,
}: {
  /** The short uppercase code, like a screen id: "ENERGY". */
  code: string;
  title: string;
  description: string;
  aside?: ReactNode;
}) {
  return (
    <header className="mb-5 flex flex-wrap items-end justify-between gap-x-6 gap-y-3 border-b border-hull-700 pb-4">
      <div>
        <p className="readout-label !text-tele-400">{code}</p>
        <h1 className="mt-1 text-[clamp(1.5rem,1.1rem+1.4vw,2.2rem)] font-semibold leading-none tracking-tight text-white">
          {title}
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-snug text-hull-300">{description}</p>
      </div>
      {aside !== undefined && <div className="shrink-0">{aside}</div>}
    </header>
  );
}

/** Shown in place of a chart when there is not enough to draw one honestly. */
export function NotEnoughYet({
  have,
  need,
  noun,
  why,
}: {
  have: number;
  need: number;
  noun: string;
  why: string;
}) {
  return (
    <div className="border border-hull-700 bg-hull-950/40 px-3 py-4 text-center">
      <p className="tabular font-mono text-xs text-hull-300">
        {have} of {need} {noun}
      </p>
      <p className="mt-1 text-[0.7rem] leading-snug text-hull-400">{why}</p>
    </div>
  );
}
