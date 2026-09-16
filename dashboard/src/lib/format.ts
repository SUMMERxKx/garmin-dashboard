/**
 * Turning numbers into the words a runner actually uses.
 *
 * The payload sends everything raw -- 4.30 km as 4300 metres, a 19.3 minute run as
 * 19.3 -- because a chart has to do arithmetic on it. Every conversion to something
 * human lives here, in one file, so a distance reads the same in every panel.
 */

/** Missing shows as an em dash. Never as 0, which would be a measurement. */
export const NOTHING = "—";

const METRES_PER_KILOMETRE = 1000;
const SECONDS_PER_MINUTE = 60;

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

/** "+312" / "−85". The sign is the information, so it is never dropped. */
export function formatSigned(value: number | null | undefined, places = 0): string {
  if (value === null || value === undefined) {
    return NOTHING;
  }

  const sign = value > 0 ? "+" : value < 0 ? "−" : "";

  return `${sign}${formatNumber(Math.abs(value), places)}`;
}

export function formatKilometres(metres: number | null | undefined, places = 1): string {
  if (metres === null || metres === undefined) {
    return NOTHING;
  }

  return formatNumber(metres / METRES_PER_KILOMETRE, places);
}

/**
 * Minutes per kilometre, the unit a run is read in.
 *
 * Derived from duration and distance rather than from Garmin's speed field, so that the
 * pace on screen always agrees with the two numbers beside it.
 */
export function formatPace(
  durationMinutes: number | null | undefined,
  distanceMetres: number | null | undefined,
): string {
  const minutesPerKilometre = paceMinutesPerKilometre(durationMinutes, distanceMetres);

  if (minutesPerKilometre === null) {
    return NOTHING;
  }

  const wholeMinutes = Math.floor(minutesPerKilometre);
  const seconds = Math.round((minutesPerKilometre - wholeMinutes) * SECONDS_PER_MINUTE);

  return `${wholeMinutes}:${String(seconds).padStart(2, "0")}`;
}

/** The pace as a number, for a chart. Null when there was no distance. */
export function paceMinutesPerKilometre(
  durationMinutes: number | null | undefined,
  distanceMetres: number | null | undefined,
): number | null {
  if (durationMinutes === null || durationMinutes === undefined) {
    return null;
  }

  if (distanceMetres === null || distanceMetres === undefined || distanceMetres <= 0) {
    return null;
  }

  return durationMinutes / (distanceMetres / METRES_PER_KILOMETRE);
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

/** "2026-09-14T18:30:00" -> "18:30". */
export function formatClock(isoDateTime: string | null): string {
  if (isoDateTime === null) {
    return NOTHING;
  }

  const timePart = isoDateTime.split("T")[1];

  if (timePart === undefined) {
    return NOTHING;
  }

  return timePart.slice(0, 5);
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

/** A local Date back to "2026-09-14". */
export function toIsoDay(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");

  return `${year}-${month}-${day}`;
}

/** Whole days between two ISO dates. */
export function daysBetween(fromIsoDay: string, toIsoDay: string): number {
  const millisecondsPerDay = 24 * 60 * 60 * 1000;
  const difference = parseIsoDay(toIsoDay).getTime() - parseIsoDay(fromIsoDay).getTime();

  return Math.round(difference / millisecondsPerDay);
}

/** Garmin's type keys, as words. Anything unknown is shown as it came. */
export function formatActivityType(typeKey: string | null): string {
  if (typeKey === null) {
    return "workout";
  }

  const names: Record<string, string> = {
    strength_training: "Strength",
    running: "Run",
    treadmill_running: "Treadmill run",
    indoor_cardio: "Indoor cardio",
    walking: "Walk",
    cycling: "Ride",
    indoor_cycling: "Indoor ride",
  };

  return names[typeKey] ?? typeKey.replaceAll("_", " ");
}
