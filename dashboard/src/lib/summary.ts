import type { DaysPayload, MetricSummary } from "@/data/types";
import type { Band } from "@/components/ui/charts";

/**
 * Reading the engine's baselines out of the payload, safely.
 *
 * Older exports have no `baselines` block at all, and a metric can be missing from a
 * newer one. Both come back as null here, and every panel treats null as "still
 * building" rather than as an error.
 */
export function summaryFor(payload: DaysPayload, metricName: string): MetricSummary | null {
  if (payload.baselines === null || payload.baselines === undefined) {
    return null;
  }

  const summary = payload.baselines.metrics[metricName];

  if (summary === undefined) {
    return null;
  }

  return summary;
}

/**
 * The 30-day normal as a band a chart can draw: one standard deviation either side of
 * the mean. Null while the window is still building, and the chart simply draws no band.
 */
export function bandFor(summary: MetricSummary | null, label = "30d normal"): Band | undefined {
  if (summary === null || summary.window_30 === null) {
    return undefined;
  }

  const window30 = summary.window_30;

  return {
    low: window30.mean - window30.standard_deviation,
    high: window30.mean + window30.standard_deviation,
    centre: window30.mean,
    label,
  };
}
