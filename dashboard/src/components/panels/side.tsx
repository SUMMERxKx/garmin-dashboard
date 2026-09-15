import { Scale, Salad } from "lucide-react";
import { MiniChart } from "@/components/ui/mini-chart";
import { TrendBadge } from "@/components/ui/stat-card";
import { series } from "@/lib/derive";
import type { DaysPayload, FoodTotals, MacroTarget } from "@/data/types";
import { formatDay, formatNumber, NOTHING } from "@/lib/format";

/**
 * Today's nutrition against target.
 *
 * Bars rather than numbers alone because four macros compared against four targets is
 * exactly the comparison a bar makes instantly and a table makes slowly.
 *
 * Over-target is drawn as overflow rather than clipped at 100%. Clipping would make
 * 3,000 kcal against a 2,350 target look identical to hitting it exactly, which is the
 * single most misleading thing a progress bar can do.
 */
export function NutritionCard({ payload }: { payload: DaysPayload }) {
  const target = payload.macro_target;

  // The most recent day that actually has a log. Showing today when today is empty
  // would report "0 of 2350" as though nothing had been eaten, when the truth is that
  // nothing has been written down yet.
  const logged = payload.days.filter((one) => one.food !== null);
  const latest = logged[logged.length - 1];

  return (
    <section className="rounded-3xl border border-white/6 bg-night-850/70 p-5 backdrop-blur-md shadow-[0_1px_0_0_rgba(255,255,255,0.04)_inset,0_18px_40px_-28px_rgba(0,0,0,0.9)]">
      <header className="flex items-center gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-leaf-400/16 text-leaf-400 ring-1 ring-leaf-400/25">
          <Salad className="size-5" strokeWidth={2.2} aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <h3 className="text-[0.95rem] font-medium text-blossom-100/85">Nutrition</h3>
          <p className="truncate text-xs text-blossom-100/45">
            {latest === undefined ? "nothing logged yet" : formatDay(latest.day)}
            {target !== null && ` · ${target.goal}`}
          </p>
        </div>
      </header>

      <div className="my-3.5 border-t border-dashed border-white/10" />

      {latest?.food == null || target === null ? (
        <EmptyNutrition hasTarget={target !== null} />
      ) : (
        <MacroBars totals={latest.food.totals} target={target} />
      )}
    </section>
  );
}

function EmptyNutrition({ hasTarget }: { hasTarget: boolean }) {
  return (
    <p className="py-6 text-center text-xs leading-relaxed text-blossom-100/40">
      {hasTarget
        ? "No food logged for any recent day."
        : "No macro target set in the food library."}
    </p>
  );
}

const MACROS = [
  { key: "kilocalories", label: "Calories", unit: "kcal", colour: "var(--color-blossom-400)" },
  { key: "protein_grams", label: "Protein", unit: "g", colour: "var(--color-leaf-400)" },
  { key: "carbohydrate_grams", label: "Carbs", unit: "g", colour: "var(--color-sky-400)" },
  { key: "fat_grams", label: "Fat", unit: "g", colour: "var(--color-amber-400)" },
] as const;

function MacroBars({ totals, target }: { totals: FoodTotals; target: MacroTarget }) {
  return (
    <ul className="flex flex-col gap-3.5">
      {MACROS.map((macro) => {
        const eaten = totals[macro.key];
        const goal = target[macro.key];
        const share = goal > 0 ? eaten / goal : 0;

        return (
          <li key={macro.key}>
            <div className="mb-1.5 flex items-baseline justify-between gap-2">
              <span className="text-xs font-medium text-blossom-100/60">{macro.label}</span>
              <span className="tabular text-xs">
                <span className="font-bold text-white">{formatNumber(eaten)}</span>
                <span className="text-blossom-100/40">
                  {" / "}
                  {formatNumber(goal)} {macro.unit}
                </span>
              </span>
            </div>

            <div className="h-2 w-full overflow-hidden rounded-full bg-white/8">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.min(share, 1) * 100}%`,
                  backgroundColor: macro.colour,
                }}
              />
            </div>

            {/* Over target gets said in words rather than drawn, so it cannot be missed
                and cannot be confused with simply reaching the goal. */}
            {share > 1.02 && (
              <p className="tabular mt-1 text-[0.65rem] text-blossom-300">
                {formatNumber(eaten - goal)} {macro.unit} over
              </p>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * The daily weigh-in, and the body-fat reading that rides along with it.
 *
 * Both are things you type in every morning, so this card is as much a record of
 * CONSISTENCY as of the numbers: the "n of m mornings" line is the honest caveat on
 * everything below it. A weight trend from four scattered mornings looks exactly as
 * confident as one from thirty.
 */
export function BodyCard({ payload }: { payload: DaysPayload }) {
  const weights = series(payload.days, (day) => day.weight?.kilograms ?? null);
  const fats = series(payload.days, (day) => day.weight?.fat_percent ?? null);

  const latestWeight = weights.length > 0 ? weights[weights.length - 1].value : null;
  const firstWeight = weights.length > 0 ? weights[0].value : null;
  const weightChange =
    latestWeight !== null && firstWeight !== null && weights.length > 1
      ? latestWeight - firstWeight
      : null;

  const latestFat = fats.length > 0 ? fats[fats.length - 1].value : null;
  const scanFat = payload.latest_scan?.fat_percent ?? null;

  return (
    <section className="rounded-3xl border border-white/6 bg-night-850/70 p-5 backdrop-blur-md shadow-[0_1px_0_0_rgba(255,255,255,0.04)_inset,0_18px_40px_-28px_rgba(0,0,0,0.9)]">
      <header className="flex items-center gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-amber-400/16 text-amber-400 ring-1 ring-amber-400/25">
          <Scale className="size-5" strokeWidth={2.2} aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <h3 className="text-[0.95rem] font-medium text-blossom-100/85">Body</h3>
          <p className="truncate text-xs text-blossom-100/45">
            {weights.length} of {payload.days.length} mornings logged
          </p>
        </div>
      </header>

      <div className="my-3.5 border-t border-dashed border-white/10" />

      <div className="flex items-baseline gap-2">
        <span className="tabular text-[clamp(1.75rem,1.3rem+1.5vw,2.5rem)] font-bold leading-none text-white">
          {formatNumber(latestWeight, 1)}
        </span>
        <span className="text-sm font-medium text-blossom-100/45">kg</span>
        <TrendBadge change={weightChange} unit=" kg" goodWhenDown />
      </div>

      <div className="mt-4">
        <p className="mb-1.5 text-[0.7rem] font-medium tracking-wide text-blossom-100/40">
          Weight — lower is up
        </p>
        {weights.length < 4 ? (
          <NotEnoughYet count={weights.length} />
        ) : (
          <MiniChart
            points={weights}
            colour="var(--color-amber-400)"
            lowerIsBetter
            formatValue={(value) => value.toFixed(1)}
          />
        )}
      </div>

      <div className="mt-5 border-t border-dashed border-white/10 pt-4">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-xs font-medium text-blossom-100/60">Body fat</span>
          <span className="tabular text-sm">
            <span className="font-bold text-white">
              {latestFat === null ? NOTHING : latestFat.toFixed(1)}
            </span>
            <span className="text-blossom-100/40"> % scale</span>
          </span>
        </div>

        {scanFat !== null && (
          <p className="tabular mt-1 text-[0.65rem] text-blossom-100/35">
            DEXA {scanFat.toFixed(1)}% on {payload.latest_scan?.scan_date} — the measured one
          </p>
        )}

        <div className="mt-3">
          {fats.length < 4 ? (
            <NotEnoughYet count={fats.length} noun="readings" />
          ) : (
            <MiniChart
              points={fats}
              colour="var(--color-blossom-400)"
              lowerIsBetter
              formatValue={(value) => `${value.toFixed(1)}%`}
            />
          )}
        </div>
      </div>
    </section>
  );
}

/**
 * Shown instead of a line when there are barely any readings.
 *
 * Drawing a trend through two points is the chart claiming to know a direction it
 * cannot know, and on weight that matters: daily swing is roughly a kilo on water while
 * a real week's change is a few hundred grams.
 */
function NotEnoughYet({ count, noun = "mornings" }: { count: number; noun?: string }) {
  return (
    <div className="rounded-xl border border-dashed border-white/10 bg-white/[0.02] px-3 py-4 text-center">
      <p className="tabular text-xs text-blossom-100/45">
        {count} of 4 {noun}
      </p>
      <p className="mt-1 text-[0.65rem] leading-relaxed text-blossom-100/30">
        daily noise is far larger than the daily signal — a trend needs a dense run
      </p>
    </div>
  );
}
