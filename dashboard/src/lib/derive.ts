import type { Activity, Day } from "@/data/types";
import { daysBetween, paceMinutesPerKm, parseIsoDay } from "@/lib/format";

/**
 * Pulling the shapes the panels need out of the flat list of days.
 *
 * All of it is plain reading and grouping -- no smoothing, no scoring, no verdicts.
 * That is deliberate: the decision on this project is that the screen shows what was
 * measured and the person reading it does the judging. Anything that turns numbers into
 * an opinion belongs in the Python engine, where the method is visible and testable,
 * not hidden in a React helper.
 */

/** Garmin's type keys for anything that counts as a run. */
const RUNNING_TYPES = ["running", "treadmill_running", "trail_running", "track_running"];

export function isRun(activity: Activity): boolean {
  if (activity.type_key === null) {
    return false;
  }

  return RUNNING_TYPES.includes(activity.type_key);
}

export type DatedActivity = Activity & { day: string };

/** Every activity across the span, newest first, each carrying the day it happened. */
export function allActivities(days: Day[]): DatedActivity[] {
  const activities: DatedActivity[] = [];

  for (const day of days) {
    for (const activity of day.activities) {
      activities.push({ ...activity, day: day.day });
    }
  }

  return activities.reverse();
}

export type Run = DatedActivity & {
  /** Minutes per kilometre, or null when the distance is too short to mean anything. */
  pace: number | null;
};

export function allRuns(days: Day[]): Run[] {
  return allActivities(days)
    .filter(isRun)
    .map((activity) => ({
      ...activity,
      pace: paceMinutesPerKm(activity.distance_metres, activity.duration_minutes),
    }));
}

export type Week = {
  /** ISO date of the Monday this week starts on. */
  startDay: string;
  runDistanceMetres: number;
  runMinutes: number;
  runCount: number;
  strengthMinutes: number;
  otherCardioMinutes: number;
};

/**
 * Group the span into calendar weeks starting on Monday.
 *
 * Weekly distance is the number runners actually plan against -- nobody sets a daily
 * mileage target -- so the week, not the day, is the unit here.
 */
export function weeklyTotals(days: Day[]): Week[] {
  const weeks = new Map<string, Week>();

  for (const day of days) {
    const date = parseIsoDay(day.day);
    // getDay() is 0 for Sunday, so Sunday has to step back six days rather than one.
    const dayOfWeek = date.getDay();
    const stepBack = dayOfWeek === 0 ? 6 : dayOfWeek - 1;

    const monday = new Date(date);
    monday.setDate(date.getDate() - stepBack);

    const startDay = [
      monday.getFullYear(),
      String(monday.getMonth() + 1).padStart(2, "0"),
      String(monday.getDate()).padStart(2, "0"),
    ].join("-");

    let week = weeks.get(startDay);

    if (week === undefined) {
      week = {
        startDay,
        runDistanceMetres: 0,
        runMinutes: 0,
        runCount: 0,
        strengthMinutes: 0,
        otherCardioMinutes: 0,
      };
      weeks.set(startDay, week);
    }

    for (const activity of day.activities) {
      const minutes = activity.duration_minutes ?? 0;

      if (isRun(activity)) {
        week.runDistanceMetres = week.runDistanceMetres + (activity.distance_metres ?? 0);
        week.runMinutes = week.runMinutes + minutes;
        week.runCount = week.runCount + 1;
      } else if (activity.type_key === "strength_training") {
        week.strengthMinutes = week.strengthMinutes + minutes;
      } else {
        week.otherCardioMinutes = week.otherCardioMinutes + minutes;
      }
    }
  }

  return [...weeks.values()].sort((a, b) => a.startDay.localeCompare(b.startDay));
}

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
