import { useEffect, useState } from "react";
import Petals from "@/components/ui/petals";
import { ProfileCard } from "@/components/panels/profile";
import { StatsGrid } from "@/components/panels/stats";
import { BodyCard, EnergyCard } from "@/components/panels/side";
import { loadDays } from "@/data/loadDays";
import type { DaysPayload } from "@/data/types";
import { formatDay } from "@/lib/format";

/**
 * The page.
 *
 * LAYOUT
 * ------
 * A single column on a phone. From `xl` up it becomes a wide main column plus a narrow
 * rail holding nutrition and the daily body log -- the two things you TYPE IN rather
 * than read off the watch, which is why they sit together and stay reachable.
 *
 * Nothing is hidden at small widths. A dashboard that drops panels on mobile is one you
 * stop trusting, because you can never be sure what you are not being shown.
 *
 * Every headline number is sized with `clamp()` against the viewport, so the same page
 * is legible held in one hand and thrown at a projector. The palette is high-contrast
 * for the same reason: projectors wash out mid-tones and grey-on-grey disappears.
 */
export default function App() {
  const [payload, setPayload] = useState<DaysPayload | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    loadDays()
      .then(setPayload)
      .catch((error: Error) => setProblem(error.message));
  }, []);

  return (
    <div className="relative min-h-screen w-full bg-night-900 text-blossom-100">
      {/* Petals drift behind everything. Held back with a scrim so the numbers in front
          stay the thing you look at -- atmosphere, not subject. */}
      <div className="pointer-events-none fixed inset-0 z-0 [transform:translateZ(0)] [will-change:transform]">
        <div className="absolute inset-0 bg-[radial-gradient(120%_90%_at_15%_0%,var(--color-night-800),var(--color-night-900)_58%)]" />
        <Petals className="size-full" />
        <div className="absolute inset-0 bg-night-900/25" />
      </div>

      <main className="relative z-10 mx-auto w-full max-w-[1700px] px-4 py-6 sm:px-6 lg:px-8 lg:py-10">
        <PageHeader payload={payload} problem={problem} />

        {payload !== null && (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_22rem] xl:gap-5">
            <div className="flex flex-col gap-4 xl:gap-5">
              <ProfileCard payload={payload} />
              <StatsGrid payload={payload} />
            </div>

            <aside className="flex flex-col gap-4 xl:gap-5">
              <EnergyCard payload={payload} />
              <BodyCard payload={payload} />
            </aside>
          </div>
        )}
      </main>
    </div>
  );
}

function PageHeader({
  payload,
  problem,
}: {
  payload: DaysPayload | null;
  problem: string | null;
}) {
  const lastDay = payload?.days[payload.days.length - 1];

  return (
    <header className="mb-5 flex flex-wrap items-end justify-between gap-x-6 gap-y-2 lg:mb-7">
      <div>
        <h1 className="text-[clamp(1.6rem,1.2rem+1.6vw,2.5rem)] font-bold leading-none tracking-tight text-white">
          Overview
        </h1>
        {payload !== null && (
          <p className="tabular mt-1.5 text-xs text-blossom-100/45">
            {payload.days.length} days · {payload.first_day} → {payload.last_day}
          </p>
        )}
      </div>

      {lastDay !== undefined && (
        <p className="text-xs font-medium text-blossom-100/45">
          through {formatDay(lastDay.day)}
        </p>
      )}

      {problem !== null && (
        <p className="w-full rounded-2xl border border-blossom-500/40 bg-blossom-600/12 px-4 py-3 text-xs font-medium text-blossom-200">
          {problem}
        </p>
      )}

      {problem === null && payload === null && (
        <p className="w-full text-xs text-blossom-100/45">loading…</p>
      )}
    </header>
  );
}
