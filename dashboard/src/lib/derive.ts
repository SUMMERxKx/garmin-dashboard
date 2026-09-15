/**
 * Pulling the shapes the panels need out of the flat list of days.
 *
 * All of it is plain reading and grouping -- no smoothing, no scoring, no verdicts.
 * That is deliberate: the decision on this project is that the screen shows what was
 * measured and the person reading it does the judging. Anything that turns numbers into
 * an opinion belongs in the Python engine, where the method is visible and testable,
 * not hidden in a React helper.
 */

import type { Day } from "@/data/types";
import { daysBetween } from "@/lib/format";

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

  // Padding the low end can push it below zero, and every quantity on this dashboard --
  // minutes asleep, body battery, steps, heart rate -- is non-negative. A chart axis
  // reading "-3m - 9h 06m" is nonsense, so the floor is clamped whenever the real
  // readings never went below zero. A series that genuinely contains negatives (a
  // change or a difference) keeps its padded floor.
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
