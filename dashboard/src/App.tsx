import { useEffect, useState } from "react";
import AsciiCity from "@/components/ui/ascii-city";
import BentoDashboard from "@/components/ui/bento-dashboard";
import { loadDays } from "@/data/loadDays";
import type { DaysPayload } from "@/data/types";

/**
 * The page.
 *
 * The bento panels below are still the ones from 21st.dev, showing their own invented
 * numbers -- "Weekly Traffic", "System Load". They are here so the look can be judged
 * before any of it is wired to real readings.
 *
 * The strip at the top is NOT invented: it comes from `days.json`, the real export, and
 * it is here to prove the whole path works end to end -- SQLite, the Python contract,
 * the file, the fetch, the types -- before charts are built on top of it.
 */
export default function App() {
  const [payload, setPayload] = useState<DaysPayload | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    loadDays()
      .then(setPayload)
      .catch((error: Error) => setProblem(error.message));
  }, []);

  // Newest weigh-in, or null if there has never been one. Mapping to `.weight` before
  // searching keeps the type honest -- finding a *day* whose weight is set does not
  // tell the compiler anything about that day's `.weight` afterwards.
  const latestWeighing =
    payload?.days
      .map((one) => one.weight)
      .reverse()
      .find((one) => one !== null) ?? null;

  return (
    <div className="relative min-h-screen w-full bg-zinc-100 dark:bg-black">
      {/* The city sits behind everything, only in dark mode -- a night skyline under a
          white page would be unreadable rather than atmospheric. */}
      <div className="fixed inset-0 z-0 hidden dark:block">
        <AsciiCity className="h-full w-full" />
        {/* Held back so the panels in front stay legible. The effect is atmosphere, not
            the subject: a dashboard you cannot read is a poster. */}
        <div className="absolute inset-0 bg-black/55" />
      </div>

      <div className="relative z-10">
        <div className="mx-auto max-w-7xl px-4 pt-6 md:px-12 md:pt-10">
          <div className="border-[3px] border-black bg-white p-4 shadow-[8px_8px_0px_0px_rgba(0,0,0,1)] dark:border-white dark:bg-zinc-900 dark:shadow-[8px_8px_0px_0px_rgba(255,255,255,1)]">
            {problem !== null && (
              <p className="font-mono text-sm font-bold text-red-600 dark:text-red-400">
                {problem}
              </p>
            )}

            {problem === null && payload === null && (
              <p className="font-mono text-sm font-bold text-black dark:text-white">
                Loading your days…
              </p>
            )}

            {payload !== null && (
              <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2 font-mono text-sm font-bold text-black dark:text-white">
                <span className="uppercase tracking-widest text-zinc-500 dark:text-zinc-400">
                  Real data
                </span>
                <span>{payload.days.length} days</span>
                <span>
                  {payload.first_day} → {payload.last_day}
                </span>
                <span>
                  {payload.days.filter((one) => one.weight !== null).length} weigh-ins
                </span>
                <span>
                  {payload.days.filter((one) => one.food !== null).length} days logged
                </span>
                {latestWeighing !== null && (
                  <span className="text-amber-600 dark:text-amber-400">
                    latest {latestWeighing.kilograms} kg
                  </span>
                )}
              </div>
            )}
          </div>
        </div>

        <BentoDashboard />
      </div>
    </div>
  );
}
