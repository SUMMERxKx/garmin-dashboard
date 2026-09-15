import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * The card everything is built from.
 *
 * WHAT CHANGED, AND WHY
 * ---------------------
 * The first version put each icon in a tinted circle with a pastel ring, on a rounded
 * card with a soft glow and a blurred backdrop. That combination is the single most
 * recognisable house style of generated dashboards, and it costs real things:
 *
 *   - `backdrop-blur` on a dozen cards makes scrolling stutter, because the compositor
 *     re-blurs what is behind every card on every frame. That was the clunky scroll.
 *   - Soft glows and 24px radii eat vertical space and blur the grid the eye uses to
 *     compare one card against the next.
 *
 * What replaces it is square corners, a hairline border, a flat surface, and a small
 * monochrome icon sitting on the baseline with its label -- no badge, no ring, no glow.
 * The accent colour appears once per card, on a 2px rule under the header, which is
 * enough to group a card with its chart without tinting the whole thing.
 */

export type Tone = "blossom" | "leaf" | "sky" | "amber" | "plum";

/** Written out in full so Tailwind's scanner sees every class it needs to emit. */
const ICON_TONE: Record<Tone, string> = {
  blossom: "text-blossom-300",
  leaf: "text-leaf-400",
  sky: "text-sky-400",
  amber: "text-amber-400",
  plum: "text-plum-400",
};

const RULE_TONE: Record<Tone, string> = {
  blossom: "bg-blossom-400/70",
  leaf: "bg-leaf-400/70",
  sky: "bg-sky-400/70",
  amber: "bg-amber-400/70",
  plum: "bg-plum-400/70",
};

export function Surface({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        // Square, flat, hairline. No blur: this is what made scrolling stutter.
        "flex flex-col border border-white/10 bg-night-850",
        className,
      )}
    >
      {children}
    </section>
  );
}

export function CardHeader({
  icon: Icon,
  label,
  tone = "blossom",
  meta,
}: {
  icon?: LucideIcon;
  label: string;
  tone?: Tone;
  meta?: ReactNode;
}) {
  return (
    <>
      <header className="flex items-center justify-between gap-3 px-4 pt-3.5 pb-2.5">
        <span className="flex min-w-0 items-center gap-2">
          {Icon !== undefined && (
            <Icon
              className={cn("size-3.5 shrink-0", ICON_TONE[tone])}
              strokeWidth={1.75}
              aria-hidden="true"
            />
          )}
          <h3 className="truncate text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-blossom-100/70">
            {label}
          </h3>
        </span>
        {meta !== undefined && (
          <span className="tabular shrink-0 text-[0.7rem] text-blossom-100/35">{meta}</span>
        )}
      </header>
      {/* The one place the accent colour appears. A rule rather than a tint, so cards
          stay comparable at a glance instead of each reading as its own coloured object. */}
      <div className={cn("h-px w-full", RULE_TONE[tone])} />
    </>
  );
}

export function StatCard({
  icon,
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
  icon?: LucideIcon;
  label: string;
  tone?: Tone;
  /** Already formatted. This component never decides how a number is written. */
  value: string;
  unit?: string;
  /** The "/2,350 kcal" half. Omitted entirely when there is no real target. */
  goal?: string;
  footnote?: ReactNode;
  chart?: ReactNode;
  /** Says what the chart is showing and which way is good. Charts without this get misread. */
  chartLabel?: string;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <Surface className={className}>
      <CardHeader icon={icon} label={label} tone={tone} />

      <div className="flex flex-1 flex-col px-4 pt-3.5 pb-4">
        <p className="flex items-baseline gap-1.5">
          <span className="tabular text-[clamp(1.6rem,1.2rem+1.3vw,2.4rem)] font-semibold leading-none tracking-tight text-white">
            {value}
          </span>
          {unit !== undefined && (
            <span className="text-xs font-medium text-blossom-100/40">{unit}</span>
          )}
          {goal !== undefined && (
            <span className="tabular text-xs font-medium text-blossom-100/40">/{goal}</span>
          )}
        </p>

        {footnote !== undefined && (
          <p className="mt-1.5 text-[0.7rem] leading-snug text-blossom-100/40">{footnote}</p>
        )}

        {chart !== undefined && (
          <div className="mt-auto pt-4">
            {chartLabel !== undefined && (
              <p className="mb-1.5 text-[0.65rem] uppercase tracking-[0.1em] text-blossom-100/30">
                {chartLabel}
              </p>
            )}
            {chart}
          </div>
        )}

        {children}
      </div>
    </Surface>
  );
}

/**
 * The up/down marker beside a trend.
 *
 * `goodWhenDown` exists because the arrow and the colour answer different questions.
 * Resting heart rate falling is good and weight falling is the plan; HRV falling is not.
 * Without the flag every downward arrow would be one colour and half of them wrong.
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

  const flat = Math.abs(change) < 0.0001;
  const rising = change > 0;
  const good = flat ? null : rising !== goodWhenDown;

  return (
    <span
      className={cn(
        "tabular inline-flex items-center gap-1 text-[0.7rem] font-semibold",
        good === null && "text-blossom-100/45",
        good === true && "text-leaf-400",
        good === false && "text-blossom-300",
      )}
    >
      <span aria-hidden="true">{flat ? "→" : rising ? "↑" : "↓"}</span>
      {Math.abs(change).toFixed(places)}
      {unit !== undefined && <span className="font-normal opacity-60">{unit}</span>}
    </span>
  );
}
