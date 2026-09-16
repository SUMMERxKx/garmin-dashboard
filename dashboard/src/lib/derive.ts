/**
 * Pulling the shapes the panels need out of the flat list of days.
 *
 * All of it is plain reading and grouping -- sums per week, one metric as a series, a
 * difference between two series. Nothing here decides whether a number is normal: that
 * comes finished from the Python engine in the `baselines` block. Anything that turns
 * numbers into an opinion belongs there, where the method is written down and tested,
 * not in a React helper.
 */

import type { Day } from "@/data/types";
import { daysBetween, parseIsoDay, toIsoDay } from "@/lib/format";

export type Point = {
  day: string;
  value: number;
};

/**
 * One metric pulled out as a series, with the days that have no reading left OUT.
 *
 * Not filled in, and not zeroed. A gap in a line is the honest picture of a night the
 * watch was on the charger; a zero would be a heart rate of nothing.
 */
export function series(days: Day[], read: (day: Day) => number | null): Point[] {
  const points: Point[] = [];

  for (const day of days) {
    const value = read(day);

    if (value !== null) {
      points.push({ day: day.day, value });
    }
  }

  return points;
}

/** The newest value in a series, or null if there are none. */
export function newest(points: Point[]): number | null {
  if (points.length === 0) {
    return null;
  }

  return points[points.length - 1].value;
}

export function mean(values: number[]): number | null {
  if (values.length === 0) {
    return null;
  }

  let total = 0;

  for (const one of values) {
    total = total + one;
  }

  return total / values.length;
}

/** The last `count` points' average, or null if there are fewer than `count`. */
export function recentMean(points: Point[], count: number): number | null {
  if (points.length < count) {
    return null;
  }

  return mean(points.slice(-count).map((one) => one.value));
}

/**
 * Change between the average of the first and last third of a series.
 *
 * Deliberately NOT "latest minus previous". Day-to-day noise is larger than the real
 * movement in almost everything here -- sleep swings about 100 minutes between two
 * ordinary nights -- so a single-day difference mostly measures noise and flips sign at
 * random. Comparing the ends of the window is the cheapest honest answer, and it needs
 * enough readings to be worth showing at all.
 */
export function driftAcross(points: Point[]): number | null {
  if (points.length < 6) {
    return null;
  }

  const third = Math.max(2, Math.floor(points.length / 3));
  const start = mean(points.slice(0, third).map((one) => one.value));
  const end = mean(points.slice(-third).map((one) => one.value));

  if (start === null || end === null) {
    return null;
  }

  return end - start;
}

/**
 * Point-by-point difference of two series, on the days BOTH have a value.
 *
 * Used for energy balance: intake minus burn. A day with only one of the two is left
 * out rather than treated as zero on the missing side.
 */
export function differenceOf(first: Point[], second: Point[]): Point[] {
  const secondByDay = new Map<string, number>();

  for (const one of second) {
    secondByDay.set(one.day, one.value);
  }

  const points: Point[] = [];

  for (const one of first) {
    const other = secondByDay.get(one.day);

    if (other !== undefined) {
      points.push({ day: one.day, value: one.value - other });
    }
  }

  return points;
}

/** Running total of a series, in order. For "how far ahead or behind over the span". */
export function cumulative(points: Point[]): Point[] {
  const out: Point[] = [];
  let total = 0;

  for (const one of points) {
    total = total + one.value;
    out.push({ day: one.day, value: total });
  }

  return out;
}

/** The Monday on or before a day, as ISO. Weeks start on Monday here. */
export function weekStartOf(isoDay: string): string {
  const date = parseIsoDay(isoDay);
  // getDay() is 0 for Sunday. Shift so Monday is 0 and Sunday is 6.
  const daysSinceMonday = (date.getDay() + 6) % 7;
  date.setDate(date.getDate() - daysSinceMonday);

  return toIsoDay(date);
}

/**
 * Group a daily series into weeks, summing or averaging each.
 *
 * Returned keyed by the Monday that starts each week, oldest first. A week with no
 * readings does not appear, rather than appearing as zero.
 */
export function byWeek(points: Point[], how: "sum" | "mean"): Point[] {
  const buckets = new Map<string, number[]>();

  for (const one of points) {
    const weekStart = weekStartOf(one.day);
    const existing = buckets.get(weekStart);

    if (existing === undefined) {
      buckets.set(weekStart, [one.value]);
    } else {
      existing.push(one.value);
    }
  }

  const weeks: Point[] = [];

  for (const [weekStart, values] of [...buckets.entries()].sort()) {
    let total = 0;

    for (const value of values) {
      total = total + value;
    }

    weeks.push({ day: weekStart, value: how === "sum" ? total : total / values.length });
  }

  return weeks;
}

export type Range = {
  lowest: number;
  highest: number;
};

/** The span a series covers, padded slightly so points never sit on the frame. */
export function rangeOf(points: Point[], padding = 0.08): Range {
  if (points.length === 0) {
    return { lowest: 0, highest: 1 };
  }

  const values = points.map((one) => one.value);
  const lowest = Math.min(...values);
  const highest = Math.max(...values);

  // A flat series has no range at all, and dividing by that zero later would put every
  // point at the same place or produce NaN. Give it an arbitrary but sane band.
  if (lowest === highest) {
    return { lowest: lowest - 1, highest: highest + 1 };
  }

  const margin = (highest - lowest) * padding;

  // Padding the low end can push it below zero, and most quantities here -- minutes
  // asleep, body battery, steps, heart rate -- are non-negative. A chart axis reading
  // "-3m" is nonsense, so the floor is clamped whenever the readings never went below
  // zero. A series that genuinely contains negatives (a balance) keeps its padded floor.
  const paddedLowest = lowest - margin;
  const flooredLowest = lowest >= 0 ? Math.max(0, paddedLowest) : paddedLowest;

  return { lowest: flooredLowest, highest: highest + margin };
}

/**
 * Split a series wherever the gap between readings is longer than `maximumGapDays`.
 *
 * Each returned run of points is drawn as its own line. Connecting across a ten-day
 * hole would draw a confident straight line through days nothing was measured, which is
 * the chart telling a story the data does not support.
 */
export function splitOnGaps(points: Point[], maximumGapDays = 2): Point[][] {
  if (points.length === 0) {
    return [];
  }

  const segments: Point[][] = [[points[0]]];

  for (let i = 1; i < points.length; i = i + 1) {
    const gap = daysBetween(points[i - 1].day, points[i].day);

    if (gap > maximumGapDays) {
      segments.push([points[i]]);
    } else {
      segments[segments.length - 1].push(points[i]);
    }
  }

  return segments;
}

/**
 * Round axis ticks: "0 / 1,000 / 2,000", never "0 / 1,137 / 2,274".
 *
 * Picks a step from the 1-2-5 sequence that gives roughly `wanted` ticks, then walks
 * from the first multiple at or below the low end to the first at or above the high end.
 */
export function niceTicks(range: Range, wanted = 4): number[] {
  const span = range.highest - range.lowest;

  if (span <= 0) {
    return [range.lowest];
  }

  const roughStep = span / wanted;
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  const candidates = [1, 2, 2.5, 5, 10].map((multiplier) => multiplier * magnitude);

  let step = candidates[candidates.length - 1];

  for (const candidate of candidates) {
    if (candidate >= roughStep) {
      step = candidate;
      break;
    }
  }

  const ticks: number[] = [];
  const first = Math.ceil(range.lowest / step) * step;

  for (let tick = first; tick <= range.highest + step * 0.001; tick = tick + step) {
    // Snap away floating-point dust like 0.30000000000000004.
    ticks.push(Number(tick.toFixed(6)));
  }

  return ticks;
}
