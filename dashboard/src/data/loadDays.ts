import type { DaysPayload } from "./types";

/**
 * The only place in the app that knows where the data comes from.
 *
 * THIS IS THE LINE THAT CHANGES WHEN THE BACKEND MOVES TO AWS.
 *
 * In Phase 1 the payload is a file on disk, written by
 * `.venv/bin/python -m backend.api.export` and served by Vite out of `public/`. In
 * Phase 3 it becomes an HTTPS call to a Lambda that returns the identical JSON. Every
 * chart above this function is written against `DaysPayload` and cannot tell the
 * difference, which is the entire reason the shape was agreed before any of this was
 * built.
 */
const DATA_URL = "/data/days.json";

/** The schema version this app was written against. */
const EXPECTED_SCHEMA_VERSION = 1;

export async function loadDays(): Promise<DaysPayload> {
  const response = await fetch(DATA_URL);

  if (!response.ok) {
    throw new Error(
      `Could not load ${DATA_URL} (HTTP ${response.status}). ` +
        `Run: .venv/bin/python -m backend.api.export`,
    );
  }

  const payload = (await response.json()) as DaysPayload;

  // A mismatch here is the difference between "the dashboard is mysteriously blank" and
  // a sentence saying exactly what is wrong. It is a warning rather than a throw,
  // because a newer payload with extra keys is usually still perfectly readable.
  if (payload.schema_version !== EXPECTED_SCHEMA_VERSION) {
    console.warn(
      `days.json is schema version ${payload.schema_version}, ` +
        `this app expects ${EXPECTED_SCHEMA_VERSION}. Some fields may be missing.`,
    );
  }

  return payload;
}
