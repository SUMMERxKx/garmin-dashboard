/**
 * Turning numbers into the words a runner actually uses.
 *
 * The payload sends everything raw -- 4.30 km as 4300 metres, a 19.3 minute run as
 * 19.3 -- because a chart has to do arithmetic on it. Every conversion to something
 * human lives here, in one file, so a distance reads the same in every panel.
 */

/** Missing shows as an em dash. Never as 0, which would be a measurement. */
export const NOTHING = "—";

export function kilometres(metres: number | null | undefined, places = 2): string {
  if (metres === null || metres === undefined) {
    return NOTHING;
  }

  return (metres / 1000).toFixed(places);
}

/**
 * Minutes per kilometre, written the way a runner says it: 4:28, not 4.47.
 *
 * Returns null rather than a string for very short distances. A 200 m warm-up logged as
 * its own activity produces an arithmetically valid pace that means nothing, and a
 * nonsense number printed confidently is worse than a blank.
 */
export function paceMinutesPerKm(
  metres: number | null,
  minutes: number | null,
): number | null {
  if (metres === null || minutes === null || metres < 400 || minutes <= 0) {
    return null;
  }

  return minutes / (metres / 1000);
}

export function formatPace(paceInMinutes: number | null): string {
  if (paceInMinutes === null) {
    return NOTHING;
  }

  const wholeMinutes = Math.floor(paceInMinutes);
  const seconds = Math.round((paceInMinutes - wholeMinutes) * 60);

  // 4.999 minutes rounds to 60 seconds, which must read as 5:00 rather than 4:60.
  if (seconds === 60) {
    return `${wholeMinutes + 1}:00`;
  }

  return `${wholeMinutes}:${String(seconds).padStart(2, "0")}`;
}

/** 87.5 minutes -> "1h 28m". Durations over an hour are unreadable in minutes alone. */
export function formatDuration(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) {
    return NOTHING;
  }

  const whole = Math.round(minutes);

  if (whole < 60) {
    return `${whole}m`;
  }

  return `${Math.floor(whole / 60)}h ${String(whole % 60).padStart(2, "0")}m`;
}

export function formatNumber(
  value: number | null | undefined,
  places = 0,
): string {
  if (value === null || value === undefined) {
    return NOTHING;
  }

  return value.toLocaleString("en-CA", {
    minimumFractionDigits: places,
    maximumFractionDigits: places,
  });
}

/** "2026-09-14" -> "Mon 14 Sep". Parsed as local, not UTC -- see below. */
export function formatDay(isoDay: string): string {
  const date = parseIsoDay(isoDay);

  return date.toLocaleDateString("en-CA", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

export function formatShortDay(isoDay: string): string {
  return parseIsoDay(isoDay).toLocaleDateString("en-CA", {
    day: "numeric",
    month: "short",
  });
}

/**
 * Parse "2026-09-14" as a LOCAL date.
 *
 * `new Date("2026-09-14")` is parsed as UTC midnight by the standard, so west of
 * Greenwich it renders as the 13th. Splitting the parts and using the numeric
 * constructor keeps a day meaning the day it says.
 */
export function parseIsoDay(isoDay: string): Date {
  const [year, month, day] = isoDay.split("-").map(Number);

  return new Date(year, month - 1, day);
}

/** Whole days between two ISO dates. */
export function daysBetween(fromIsoDay: string, toIsoDay: string): number {
  const millisecondsPerDay = 24 * 60 * 60 * 1000;
  const difference = parseIsoDay(toIsoDay).getTime() - parseIsoDay(fromIsoDay).getTime();

  return Math.round(difference / millisecondsPerDay);
}
