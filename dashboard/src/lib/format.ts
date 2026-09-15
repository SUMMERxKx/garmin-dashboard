/**
 * Turning numbers into the words a runner actually uses.
 *
 * The payload sends everything raw -- 4.30 km as 4300 metres, a 19.3 minute run as
 * 19.3 -- because a chart has to do arithmetic on it. Every conversion to something
 * human lives here, in one file, so a distance reads the same in every panel.
 */

/** Missing shows as an em dash. Never as 0, which would be a measurement. */
export const NOTHING = "—";
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
