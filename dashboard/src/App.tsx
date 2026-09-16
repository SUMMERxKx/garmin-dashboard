import { useCallback, useEffect, useState } from "react";
import { Sidebar } from "@/components/nav/sidebar";
import { ActivityPage } from "@/components/pages/activity";
import { BodyPage } from "@/components/pages/body";
import { EnergyPage } from "@/components/pages/energy";
import { LogPage } from "@/components/pages/log";
import { OverviewPage } from "@/components/pages/overview";
import { RecoveryPage } from "@/components/pages/recovery";
import { loadDays } from "@/data/loadDays";
import type { DataSource, DaysPayload } from "@/data/types";
import { usePage } from "@/lib/router";

/**
 * The shell: a rail of pages on the left, one page on the right.
 *
 * LAYOUT
 * ------
 * From `lg` up the rail is a fixed 14-rem column and the page scrolls beside it. Below
 * that the rail becomes a strip of tabs across the top and everything stacks. Nothing is
 * hidden at small widths -- a dashboard that drops panels on a phone is one you stop
 * trusting, because you can never be sure what you are not being shown.
 *
 * WHY IT SCROLLS SMOOTHLY NOW
 * ---------------------------
 * The background is a still image painted once by CSS. The old one was a Canvas
 * animation redrawing blurred shapes every frame behind panels with `backdrop-blur`, so
 * every scroll tick re-composited the entire viewport. There is nothing left here that
 * costs anything per frame.
 */
export default function App() {
  const [payload, setPayload] = useState<DaysPayload | null>(null);
  const [source, setSource] = useState<DataSource | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [page] = usePage();

  // Fetch, then store. Returned as a promise so the Log page can wait for the fresh
  // payload after a write before it clears its form.
  const reload = useCallback((): Promise<void> => {
    return loadDays()
      .then((loaded) => {
        setPayload(loaded.payload);
        setSource(loaded.source);
        setProblem(null);
      })
      .catch((error: Error) => {
        setProblem(error.message);
      });
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  return (
    <div className="relative min-h-screen w-full text-hull-100">
      <div className="starfield pointer-events-none fixed inset-0 z-0" aria-hidden="true" />

      <div className="relative z-10 flex min-h-screen flex-col lg:flex-row">
        <Sidebar page={page} payload={payload} source={source} />

        <main className="min-w-0 flex-1 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
          <div className="mx-auto w-full max-w-[1500px]">
            {problem !== null && (
              <p className="mb-4 border border-plume-400/50 bg-plume-400/10 px-4 py-3 font-mono text-xs text-hull-100">{problem}</p>
            )}

            {payload === null && problem === null && (
              <p className="font-mono text-xs text-hull-400">acquiring signal…</p>
            )}

            {payload !== null && payload.days.length === 0 && (
              <p className="font-mono text-xs text-hull-400">No days yet. Fetch and import some, then reload.</p>
            )}

            {payload !== null && payload.days.length > 0 && source !== null && (
              <>
                {page === "overview" && <OverviewPage payload={payload} />}
                {page === "energy" && <EnergyPage payload={payload} />}
                {page === "recovery" && <RecoveryPage payload={payload} />}
                {page === "activity" && <ActivityPage payload={payload} />}
                {page === "body" && <BodyPage payload={payload} />}
                {page === "log" && <LogPage payload={payload} source={source} onSaved={reload} />}
              </>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
