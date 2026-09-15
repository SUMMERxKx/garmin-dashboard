import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * The card this whole dashboard is built from.
 *
 * Shape borrowed from the reference: a round tinted icon, a label, a dashed rule, then
 * the number -- large and bold, with its unit small and quiet beside it so a column of
 * cards still lines up on the digits.
 *
 * The part added beyond the reference is `chart`: a small labelled plot directly under
 * the number. A single figure tells you where you are and nothing about where you are
 * going, and "77.7 kg" means something quite different depending on whether the last
 * fortnight has been climbing or falling.
 */

export type Tone = "blossom" | "leaf" | "sky" | "amber" | "plum";

/** Each tone's icon colours, written out rather than composed, so Tailwind sees them. */
const TONE_STYLES: Record<Tone, string> = {
  blossom: "bg-blossom-500/18 text-blossom-300 ring-blossom-400/25",
  leaf: "bg-leaf-400/16 text-leaf-400 ring-leaf-400/25",
  sky: "bg-sky-400/16 text-sky-400 ring-sky-400/25",
  amber: "bg-amber-400/16 text-amber-400 ring-amber-400/25",
  plum: "bg-plum-400/18 text-plum-400 ring-plum-400/25",
};

export function StatCard({
  icon: Icon,
  label,
  tone = "blossom",
  value,
  unit,
  goal,
  footnote,
  chart,
  chartLabel,
  className,
  children,
}: {
  icon: LucideIcon;
  label: string;
  tone?: Tone;
  /** Already formatted. This component never decides how a number is written. */
  value: string;
  unit?: string;
  /** The "/2350 kcal" half. Omitted entirely when there is no real target. */
  goal?: string;
  footnote?: ReactNode;
  chart?: ReactNode;
  /** Says what the chart underneath is showing. Charts without labels get misread. */
  chartLabel?: string;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <section
      className={cn(
        "flex flex-col rounded-3xl border border-white/6 bg-night-850/70 p-5 backdrop-blur-md",
        "shadow-[0_1px_0_0_rgba(255,255,255,0.04)_inset,0_18px_40px_-28px_rgba(0,0,0,0.9)]",
        className,
      )}
    >
      <header className="flex items-center gap-3">
        <span
          className={cn(
            "grid size-10 shrink-0 place-items-center rounded-full ring-1",
            TONE_STYLES[tone],
          )}
        >
          <Icon className="size-5" strokeWidth={2.2} aria-hidden="true" />
        </span>
        <h3 className="text-[0.95rem] font-medium text-blossom-100/85">{label}</h3>
      </header>

      <div className="my-3.5 border-t border-dashed border-white/10" />

      <p className="flex items-baseline gap-1.5">
        <span className="tabular text-[clamp(1.75rem,1.3rem+1.5vw,2.75rem)] font-bold leading-none text-white">
          {value}
        </span>
        {unit !== undefined && (
          <span className="text-sm font-medium text-blossom-100/45">{unit}</span>
        )}
        {goal !== undefined && (
          <span className="tabular text-sm font-medium text-blossom-100/45">/{goal}</span>
        )}
      </p>

      {footnote !== undefined && (
        <p className="mt-1.5 text-xs text-blossom-100/45">{footnote}</p>
      )}

      {chart !== undefined && (
        <div className="mt-4">
          {chartLabel !== undefined && (
            <p className="mb-1.5 text-[0.7rem] font-medium tracking-wide text-blossom-100/40">
              {chartLabel}
            </p>
          )}
          {chart}
        </div>
      )}

      {children}
    </section>
  );
}

/**
 * The little up/down badge that sits beside a trend.
 *
 * `goodWhenDown` exists because the arrow direction and the colour are different
 * questions. Resting heart rate falling is good news and weight falling is the plan;
 * HRV falling is not. Without this flag every downward arrow would be red and half of
 * them would be wrong.
 */
export function TrendBadge({
  change,
  unit,
  goodWhenDown = false,
  places = 1,
}: {
  change: number | null;
  unit?: string;
  goodWhenDown?: boolean;
  places?: number;
}) {
  if (change === null) {
    return null;
  }

  const rising = change > 0;
  const flat = Math.abs(change) < 0.0001;
  const good = flat ? null : rising !== goodWhenDown;

  return (
    <span
      className={cn(
        "tabular inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[0.7rem] font-semibold",
        good === null && "bg-white/8 text-blossom-100/55",
        good === true && "bg-leaf-400/14 text-leaf-400",
        good === false && "bg-blossom-500/16 text-blossom-300",
      )}
    >
      <span aria-hidden="true">{flat ? "→" : rising ? "↑" : "↓"}</span>
      {Math.abs(change).toFixed(places)}
      {unit !== undefined && <span className="font-normal opacity-70">{unit}</span>}
    </span>
  );
}
