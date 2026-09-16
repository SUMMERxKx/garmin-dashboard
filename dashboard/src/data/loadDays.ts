import type { DataSource, DaysPayload } from "./types";

/**
 * The only place in the app that knows where the data comes from.
 *
 * Two sources, tried in order:
 *
 *   1. `/api/days` -- the Python server, proxied by Vite. Live, and the only source
 *      that can also accept a write.
 *   2. `/data/days.json` -- the file `backend.api.export` writes. Always there once you
 *      have run the export, and exactly the same shape.
 *
 * The app tells you which one it got, because the difference matters: a number typed
 * into the Log page lands in the database, and the file will not show it until the
 * export is run again.
 *
 * THIS IS THE FILE THAT CHANGES WHEN THE BACKEND MOVES TO AWS. The API address becomes
 * the Lambda's URL and nothing above this function notices.
 */
const API_URL = "/api/days";
const FILE_URL = "/data/days.json";

/** The schema version this app was written against. */
const EXPECTED_SCHEMA_VERSION = 2;

export type Loaded = {
  payload: DaysPayload;
  source: DataSource;
};

export async function loadDays(): Promise<Loaded> {
  const fromApi = await tryFetch(API_URL);

  if (fromApi !== null) {
    return { payload: fromApi, source: "api" };
  }

  const fromFile = await tryFetch(FILE_URL);

  if (fromFile !== null) {
    return { payload: fromFile, source: "file" };
  }

  throw new Error(
    "No data. Start the API (.venv/bin/uvicorn backend.api.server:app --port 8000) " +
      "or write the file (.venv/bin/python -m backend.api.export).",
  );
}

/** Fetch and parse one URL, or null if it is not there. Never throws. */
async function tryFetch(url: string): Promise<DaysPayload | null> {
  let response: Response;

  try {
    response = await fetch(url);
  } catch {
    // The network itself failed -- most likely the dev server's proxy could not reach
    // the Python process. Not an error worth showing; the fallback handles it.
    return null;
  }

  if (!response.ok) {
    return null;
  }

  const payload = (await response.json()) as DaysPayload;

  // A mismatch here is the difference between "the dashboard is mysteriously blank" and
  // a sentence saying exactly what is wrong. It is a warning rather than a throw,
  // because a newer payload with extra keys is usually still perfectly readable.
  if (payload.schema_version !== EXPECTED_SCHEMA_VERSION) {
    console.warn(
      `${url} is schema version ${payload.schema_version}, ` +
        `this app expects ${EXPECTED_SCHEMA_VERSION}. Some fields may be missing.`,
    );
  }

  return payload;
}
