/**
 * The AI reading of the numbers.
 *
 * Deliberately fetched separately from the payload rather than bundled into it. The
 * dashboard has to draw instantly from its own data; a model call takes a second or two
 * and can be unavailable entirely, and neither of those should ever delay a chart.
 */

export type InsightReading = {
  headline: string;
  observations: string[];
  model_id: string;
  input_tokens: number;
  output_tokens: number;
  facts_fingerprint: string;
};

export type InsightAnswer = {
  /**
   * `ready` means there is a reading. `unavailable` means the model could not be
   * reached, which on a new AWS account is simply "not switched on yet". `rejected`
   * means the model wrote a number that was not in the data, so the whole answer was
   * thrown away -- see backend/ai/interpret.py.
   */
  status: "ready" | "unavailable" | "rejected";
  reading: InsightReading | null;
  detail?: string;
  from_cache: boolean;
};

export async function loadInsight(): Promise<InsightAnswer> {
  let response: Response;

  try {
    response = await fetch("/api/insight");
  } catch {
    return { status: "unavailable", reading: null, detail: "Could not reach the API.", from_cache: false };
  }

  if (response.status === 401) {
    const next = encodeURIComponent(window.location.pathname + window.location.hash);
    window.location.replace(`/login.html?next=${next}`);

    return { status: "unavailable", reading: null, from_cache: false };
  }

  if (!response.ok) {
    return {
      status: "unavailable",
      reading: null,
      detail: `The API answered ${response.status}.`,
      from_cache: false,
    };
  }

  return (await response.json()) as InsightAnswer;
}
