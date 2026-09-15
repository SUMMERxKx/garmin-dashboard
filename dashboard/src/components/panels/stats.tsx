import {
  Activity,
  Droplets,
  Flame,
  Footprints,
  HeartPulse,
  Moon,
  Scale,
  Utensils,
  Zap,
} from "lucide-react";
import { StatCard, TrendBadge } from "@/components/ui/stat-card";
import { MiniBars, MiniChart } from "@/components/ui/mini-chart";
import { series, type Point } from "@/lib/derive";
import { SLEEP_GOAL_MINUTES, STEP_GOAL } from "@/config";
import type { DaysPayload } from "@/data/types";
import { formatDuration, formatNumber, NOTHING } from "@/lib/format";

/** The newest value in a series, or null if there are none. */
function newest(points: Point[]): number | null {
  return points.length === 0 ? null : points[points.length - 1].value;
}

/**
 * Change between the average of the first and last third of a series.
 *
 * Deliberately NOT "latest minus previous". Day-to-day noise is larger than the real
 * movement in almost everything here -- sleep swings about 100 minutes between two
 * ordinary nights -- so a single-day difference mostly measures noise and flips sign at
 * random. Comparing the ends of the window is the cheapest honest answer, and it needs
 * enough readings to be worth showing at all.
 */
function driftAcross(points: Point[]): number | null {
  if (points.length < 6) {
    return null;
  }

  const third = Math.max(2, Math.floor(points.length / 3));
  const mean = (values: number[]) =>
    values.reduce((sum, one) => sum + one, 0) / values.length;

  const start = mean(points.slice(0, third).map((one) => one.value));
  const end = mean(points.slice(-third).map((one) => one.value));

  return end - start;
}

export function StatsGrid({ payload }: { payload: DaysPayload }) {
  const days = payload.days;
  const target = payload.macro_target;

  const burned = series(days, (day) => day.energy.total_kilocalories);
  const eaten = series(days, (day) => day.food?.totals.kilocalories ?? null);
  const steps = series(days, (day) => day.energy.steps);
  const sleep = series(days, (day) => day.sleep.total_minutes);
  const restingHeartRate = series(days, (day) => day.recovery.resting_heart_rate);
  const hrv = series(days, (day) => day.recovery.hrv_last_night);
  const bodyBattery = series(days, (day) => day.recovery.body_battery_charged);
  const stress = series(days, (day) => day.recovery.average_stress);

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
      <StatCard
        icon={Flame}
        tone="blossom"
        label="Calories burned"
        value={formatNumber(newest(burned))}
        unit="kcal"
        footnote="Garmin total, resting included"
        chartLabel="Daily burn — higher is up"
        chart={<MiniBars points={burned} colour="var(--color-blossom-400)" />}
      >
        <Footer>
          <TrendBadge change={driftAcross(burned)} unit=" kcal" places={0} />
          <span className="text-xs text-blossom-100/40">across the span</span>
        </Footer>
      </StatCard>

      <StatCard
        icon={Utensils}
        tone="leaf"
        label="Calories eaten"
        value={eaten.length === 0 ? NOTHING : formatNumber(newest(eaten))}
        unit="kcal"
        goal={target === null ? undefined : `${formatNumber(target.kilocalories)} kcal`}
        footnote={
          eaten.length < days.length
            ? `logged on ${eaten.length} of ${days.length} days`
            : undefined
        }
        chartLabel="Intake vs target — higher is more"
        chart={
          <MiniBars
            points={eaten}
            colour="var(--color-leaf-400)"
            goal={target?.kilocalories}
          />
        }
      />

      <StatCard
        icon={Footprints}
        tone="sky"
        label="Steps"
        value={formatNumber(newest(steps))}
        goal={formatNumber(STEP_GOAL)}
        footnote={`${steps.filter((one) => one.value >= STEP_GOAL).length} of ${steps.length} days over goal`}
        chartLabel="Daily steps — higher is up"
        chart={<MiniBars points={steps} colour="var(--color-sky-400)" goal={STEP_GOAL} />}
      />

      <StatCard
        icon={Moon}
        tone="plum"
        label="Sleep"
        value={newest(sleep) === null ? NOTHING : formatDuration(newest(sleep))}
        goal={formatDuration(SLEEP_GOAL_MINUTES)}
        chartLabel="Time asleep — higher is longer"
        chart={
          <MiniChart
            points={sleep}
            colour="var(--color-plum-400)"
            formatValue={(value) => formatDuration(value)}
          />
        }
      >
        <Footer>
          <TrendBadge change={driftAcross(sleep)} unit=" min" places={0} />
          <span className="text-xs text-blossom-100/40">vs start of span</span>
        </Footer>
      </StatCard>

      <StatCard
        icon={HeartPulse}
        tone="blossom"
        label="Resting heart rate"
        value={formatNumber(newest(restingHeartRate))}
        unit="bpm"
        footnote="lower usually means better recovered"
        chartLabel="Resting HR — lower is up"
        chart={
          <MiniChart
            points={restingHeartRate}
            colour="var(--color-blossom-500)"
            lowerIsBetter
          />
        }
      >
        <Footer>
          <TrendBadge change={driftAcross(restingHeartRate)} unit=" bpm" goodWhenDown />
          <span className="text-xs text-blossom-100/40">vs start of span</span>
        </Footer>
      </StatCard>

      <StatCard
        icon={Activity}
        tone="leaf"
        label="HRV"
        value={formatNumber(newest(hrv))}
        unit="ms"
        footnote="overnight average"
        chartLabel="HRV — higher is up"
        chart={<MiniChart points={hrv} colour="var(--color-leaf-400)" />}
      >
        <Footer>
          <TrendBadge change={driftAcross(hrv)} unit=" ms" />
          <span className="text-xs text-blossom-100/40">vs start of span</span>
        </Footer>
      </StatCard>

      <StatCard
        icon={Zap}
        tone="amber"
        label="Body battery"
        value={formatNumber(newest(bodyBattery))}
        footnote="charged overnight"
        chartLabel="Overnight charge — higher is up"
        chart={<MiniChart points={bodyBattery} colour="var(--color-amber-400)" />}
      />

      <StatCard
        icon={Droplets}
        tone="sky"
        label="Stress"
        value={formatNumber(newest(stress))}
        footnote="Garmin daily average, lower is calmer"
        chartLabel="Average stress — lower is up"
        chart={<MiniChart points={stress} colour="var(--color-sky-400)" lowerIsBetter />}
      />

      <Vo2Card />
    </div>
  );
}

/**
 * VO2 max, which this watch does not report.
 *
 * Shown as an empty card rather than left out. You asked for it, and "the card is here
 * and the watch cannot fill it" is a more useful answer than the metric silently not
 * existing -- otherwise the question comes back every few weeks.
 *
 * Confirmed against your own data: `max_metrics` returns an empty list on all 31 days,
 * and `training_status.mostRecentVO2Max` is null on every one of them.
 */
function Vo2Card() {
  return (
    <StatCard
      icon={Scale}
      tone="plum"
      label="VO₂ max"
      value={NOTHING}
      footnote="the FR165 does not report this"
    >
      <div className="mt-4 rounded-xl border border-dashed border-white/10 bg-white/[0.02] p-3">
        <p className="text-xs leading-relaxed text-blossom-100/45">
          Garmin reserves VO₂ max, Training Status and Training Readiness for its higher
          watches. Checked across all 31 days: every reading is null. A lab test or a
          different watch is the only way to fill this.
        </p>
      </div>
    </StatCard>
  );
}

function Footer({ children }: { children: React.ReactNode }) {
  return <div className="mt-3 flex items-center gap-2">{children}</div>;
}
