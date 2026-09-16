import type { ReactNode } from "react";
import type { MetricSummary } from "@/data/types";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import { RULE_TONE, type Tone } from "@/lib/tones";
import { Panel } from "./surface";

/**
 * One readout: a label, a big number, and where it sits against your own normal.
 *
 * The number is the brightest thing in the tile and is set in proportional figures --
 * tabular digits make a large "121" look loose. The verdict underneath comes finished
 * from the Python engine; this component only chooses a colour for it, and it needs to
 * be TOLD which direction is good, because HRV rising and resting heart rate rising are
 * opposite news.
 */
export function StatTile({
  label,
  tone = "tele",
  value,
  unit,
  goal,
  summary,
  goodWhenHigh,
  footnote,
  tag,
  chart,
  className,
}: {
  label: string;
  tone?: Tone;
  /** Already formatted. This component never decides how a number is written. */
  value: string;
  unit?: string;
  /** The "/2,350" half. Omitted entirely when there is no real target. */
  goal?: string;
  /** The engine's summary for this metric, if there is one. */
  summary?: MetricSummary | null;
  /** Whether "above normal" is the good direction. Undefined means neither is. */
  goodWhenHigh?: boolean;
  footnote?: ReactNode;
  /** A small marker beside the value, like the intake source. */
  tag?: ReactNode;
  chart?: ReactNode;
  className?: string;
}) {
  return (
    <Panel className={className}>
      <div className="flex items-center justify-between gap-2 px-3.5 pt-3">
        <span className="flex items-center gap-2">
          <span className={cn("h-2.5 w-0.5", RULE_TONE[tone])} aria-hidden="true" />
          <span className="readout-label">{label}</span>
        </span>
        {tag}
      </div>

      <div className="flex flex-1 flex-col px-3.5 pt-2.5 pb-3.5">
        <p className="flex items-baseline gap-1.5">
          <span className="text-[clamp(1.7rem,1.2rem+1.4vw,2.5rem)] font-semibold leading-none tracking-tight text-white">
            {value}
          </span>
          {unit !== undefined && <span className="text-xs font-medium text-hull-300">{unit}</span>}
          {goal !== undefined && (
            <span className="tabular text-xs font-medium text-hull-400">/{goal}</span>
          )}
        </p>

        {summary !== undefined && summary !== null && (
          <PositionLine summary={summary} goodWhenHigh={goodWhenHigh} />
        )}

        {footnote !== undefined && (
          <p className="mt-1.5 text-[0.7rem] leading-snug text-hull-400">{footnote}</p>
        )}

        {chart !== undefined && <div className="mt-auto pt-3">{chart}</div>}
      </div>
    </Panel>
  );
}

/**
 * "typical for you · 30d 107 ±14" -- the engine's verdict and the normal it was judged
 * against, in one line. While the 30-day window is still building it says so with the
 * count, rather than showing nothing and leaving you to wonder.
 */
export function PositionLine({
  summary,
  goodWhenHigh,
  places = 0,
}: {
  summary: MetricSummary;
  goodWhenHigh?: boolean;
  places?: number;
}) {
  const window30 = summary.window_30;

  if (window30 === null) {
    const window7 = summary.window_7;
    const have = window7 === null ? 0 : window7.sample_size;

    return (
      <p className="mt-1.5 font-mono text-[0.66rem] text-hull-400">
        30-day normal still building{have > 0 ? ` · 7d ${formatNumber(window7?.mean, places)}` : ""}
      </p>
    );
  }

  const position = summary.position_vs_30;

  let colour = "text-hull-300";
  let word = "typical for you";

  if (position === "above" || position === "below") {
    word = `${position} your normal`;

    if (goodWhenHigh !== undefined) {
      const isGood = (position === "above") === goodWhenHigh;
      colour = isGood ? "text-signal-400" : "text-plume-400";
    }
  }

  return (
    <p className="mt-1.5 flex flex-wrap items-baseline gap-x-2 font-mono text-[0.66rem]">
      <span className={cn("font-medium", colour)}>{word}</span>
      <span className="tabular text-hull-400">
        30d {formatNumber(window30.mean, places)} ±{formatNumber(window30.standard_deviation, places)}
      </span>
    </p>
  );
}

/**
 * The small marker that says where an intake figure came from.
 *
 * "assumed" is the one that matters. A carried figure is drawn hollow, in the muted
 * text colour, so it can never be mistaken for a measurement at a glance.
 */
export function SourceTag({ source, fromDay }: { source: "logged" | "manual" | "carried"; fromDay?: string }) {
  if (source === "carried") {
    return (
      <span
        className="border border-hull-500 px-1.5 py-0.5 font-mono text-[0.6rem] uppercase tracking-wider text-hull-300"
        title={fromDay === undefined ? "carried forward" : `carried forward from ${fromDay}`}
      >
        assumed
      </span>
    );
  }

  return (
    <span className="border border-signal-400/40 bg-signal-400/10 px-1.5 py-0.5 font-mono text-[0.6rem] uppercase tracking-wider text-hull-200">
      {source === "manual" ? "typed" : "logged"}
    </span>
  );
}

/**
 * The up/down marker beside a change.
 *
 * `goodWhenDown` exists because the arrow and the colour answer different questions.
 * Resting heart rate falling is good and weight falling is the plan; HRV falling is not.
 * Without the flag every downward arrow would be one colour and half of them wrong.
 */
export function TrendBadge({
  change,
  unit,
  goodWhenDown,
  places = 1,
}: {
  change: number | null;
  unit?: string;
  /** Undefined means neither direction is good news; the badge stays neutral. */
  goodWhenDown?: boolean;
  places?: number;
}) {
  if (change === null) {
    return null;
  }

  const flat = Math.abs(change) < 0.0001;
  const rising = change > 0;

  let colour = "text-hull-300";

  if (!flat && goodWhenDown !== undefined) {
    const good = rising !== goodWhenDown;
    colour = good ? "text-signal-400" : "text-plume-400";
  }

  return (
    <span className={cn("tabular inline-flex items-center gap-1 font-mono text-[0.7rem] font-medium", colour)}>
      <span aria-hidden="true">{flat ? "→" : rising ? "↑" : "↓"}</span>
      {Math.abs(change).toFixed(places)}
      {unit !== undefined && <span className="font-normal opacity-70">{unit}</span>}
    </span>
  );
}

/** A labelled small value, for rows of secondary readings under a chart. */
export function Reading({
  label,
  value,
  unit,
  tone,
}: {
  label: string;
  value: string;
  unit?: string;
  tone?: Tone;
}) {
  return (
    <div className="min-w-0">
      <p className="flex items-center gap-1.5">
        {tone !== undefined && <span className={cn("size-1.5", RULE_TONE[tone])} aria-hidden="true" />}
        <span className="readout-label">{label}</span>
      </p>
      <p className="mt-0.5 flex items-baseline gap-1">
        <span className="tabular text-base font-semibold text-white">{value}</span>
        {unit !== undefined && <span className="text-[0.66rem] text-hull-400">{unit}</span>}
      </p>
    </div>
  );
}
