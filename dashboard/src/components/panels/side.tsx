import { Flame, Scale } from "lucide-react";
import { MiniChart } from "@/components/ui/mini-chart";
import { CardHeader, Surface, TrendBadge } from "@/components/ui/stat-card";
import { series } from "@/lib/derive";
import type { DaysPayload } from "@/data/types";
import { formatDay, formatNumber, NOTHING } from "@/lib/format";

/**
 * Calories in against calories out, for one day.
 *
 * Reduced to exactly that. It previously drew four macro bars against four targets,
 * which is a different question -- "is the diet composed correctly" -- asked on a screen
 * you open to answer "did I eat more or less than I burned". The macros are still in the
 * payload and still logged; they just do not belong on the front page.
 *
 * The day shown is the most recent one that HAS a food log, not today. Showing today
 * when today is empty would report zero eaten against three thousand burned, which
 * reads as a catastrophic deficit rather than as a day not yet written down.
 *
 * The difference is labelled as a gap in the RECORD, not as a deficit. Garmin's burn is
 * an estimate that overstates resistance training -- your own data has 45 minutes of
 * lifting at 124 bpm scored as 312 active kcal -- and a food log is only as complete as
 * what got typed in. Calling their difference a deficit would present two estimates as
 * one measurement.
 */
export function EnergyCard({ payload }: { payload: DaysPayload }) {
  const logged = payload.days.filter((one) => one.food !== null);
  const latest = logged[logged.length - 1];

  const eaten = latest?.food?.totals.kilocalories ?? null;
  const burned = latest?.energy.total_kilocalories ?? null;
  const difference = eaten !== null && burned !== null ? eaten - burned : null;

  return (
    <Surface>
      <CardHeader
        icon={Flame}
        label="Energy"
        tone="blossom"
        meta={latest === undefined ? "no log" : formatDay(latest.day)}
      />

      <div className="flex flex-col px-4 pt-4 pb-4">
        <div className="grid grid-cols-2 gap-4">
          <Reading label="In" value={formatNumber(eaten)} tone="text-leaf-400" />
          <Reading label="Out" value={formatNumber(burned)} tone="text-blossom-300" />
        </div>

        <div className="mt-4 border-t border-white/10 pt-3">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[0.7rem] uppercase tracking-[0.12em] text-blossom-100/45">
              Difference
            </span>
            <span className="tabular text-lg font-semibold text-white">
              {difference === null
                ? NOTHING
                : `${difference > 0 ? "+" : ""}${formatNumber(difference)}`}
              <span className="ml-1 text-[0.7rem] font-normal text-blossom-100/40">kcal</span>
            </span>
          </div>

          <p className="mt-1.5 text-[0.65rem] leading-snug text-blossom-100/30">
            Logged intake minus Garmin's estimated burn. Both are estimates — treat the
            gap as a direction, not a measurement.
          </p>
        </div>

        {logged.length < payload.days.length && (
          <p className="tabular mt-3 text-[0.65rem] text-blossom-100/30">
            food logged on {logged.length} of {payload.days.length} days
          </p>
        )}
      </div>
    </Surface>
  );
}

function Reading({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: string;
}) {
  return (
    <div>
      <p className="text-[0.7rem] uppercase tracking-[0.12em] text-blossom-100/45">{label}</p>
      <p className="mt-1 flex items-baseline gap-1">
        <span className={`tabular text-[clamp(1.4rem,1.1rem+1vw,2rem)] font-semibold leading-none ${tone}`}>
          {value}
        </span>
        <span className="text-[0.7rem] font-medium text-blossom-100/40">kcal</span>
      </p>
    </div>
  );
}

/**
 * The daily weigh-in and the body-fat reading that rides with it.
 *
 * Both are typed in every morning, so this card is as much a record of CONSISTENCY as of
 * the numbers -- the "n of m mornings" line is the honest caveat on everything below it.
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
    <Surface>
      <CardHeader
        icon={Scale}
        label="Body"
        tone="amber"
        meta={`${weights.length}/${payload.days.length} mornings`}
      />

      <div className="flex flex-col px-4 pt-4 pb-4">
        <div className="flex items-baseline gap-2.5">
          <span className="tabular text-[clamp(1.6rem,1.2rem+1.3vw,2.4rem)] font-semibold leading-none tracking-tight text-white">
            {formatNumber(latestWeight, 1)}
          </span>
          <span className="text-xs font-medium text-blossom-100/40">kg</span>
          <TrendBadge change={weightChange} unit=" kg" goodWhenDown />
        </div>

        <div className="mt-4">
          <p className="mb-1.5 text-[0.65rem] uppercase tracking-[0.1em] text-blossom-100/30">
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

        <div className="mt-4 border-t border-white/10 pt-3.5">
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[0.7rem] uppercase tracking-[0.12em] text-blossom-100/45">
              Body fat
            </span>
            <span className="tabular text-sm">
              <span className="font-semibold text-white">
                {latestFat === null ? NOTHING : latestFat.toFixed(1)}
              </span>
              <span className="text-blossom-100/40"> % scale</span>
            </span>
          </div>

          {scanFat !== null && (
            <p className="tabular mt-1 text-[0.65rem] text-blossom-100/30">
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
      </div>
    </Surface>
  );
}

/**
 * Shown instead of a line when there are barely any readings.
 *
 * Drawing a trend through two points is the chart claiming a direction it cannot know,
 * and on weight that matters: daily swing is roughly a kilo on water while a real week's
 * change is a few hundred grams.
 */
function NotEnoughYet({ count, noun = "mornings" }: { count: number; noun?: string }) {
  return (
    <div className="border border-white/8 bg-white/[0.02] px-3 py-3.5 text-center">
      <p className="tabular text-[0.7rem] text-blossom-100/40">
        {count} of 4 {noun}
      </p>
      <p className="mt-1 text-[0.65rem] leading-snug text-blossom-100/25">
        daily noise is far larger than the daily signal
      </p>
    </div>
  );
}
