import { Activity, Flame, Scale } from "lucide-react";
import { InsightPanel } from "@/components/panels/insight";
import { BarChart, Legend, LineChart, type Domain } from "@/components/ui/charts";
import { MiniBars, Sparkline } from "@/components/ui/mini-chart";
import { SourceTag, StatTile, TrendBadge } from "@/components/ui/stat-tile";
import { NotEnoughYet, PageTitle, Panel, PanelBody, PanelHeader } from "@/components/ui/surface";
import { COLOUR_OF } from "@/lib/tones";
import { SLEEP_GOAL_MINUTES, STEP_GOAL } from "@/config";
import type { DaysPayload } from "@/data/types";
import { differenceOf, newest, series } from "@/lib/derive";
import {
  formatActivityType,
  formatDay,
  formatDuration,
  formatKilometres,
  formatNumber,
  formatPace,
  formatSigned,
  NOTHING,
} from "@/lib/format";
import { bandFor, summaryFor } from "@/lib/summary";

/**
 * The front page: every headline number at once, each against your own normal.
 *
 * Nothing here is deep. Each tile is the first line of a page you can open from the
 * left, and the two charts are the two questions a cut is about -- did more go in than
 * out, and what did the scale do. Everything else has its own page so that this one
 * stays readable in the time it takes the kettle to boil.
 */
export function OverviewPage({ payload }: { payload: DaysPayload }) {
  const days = payload.days;
  const domain: Domain = { firstDay: payload.first_day ?? days[0].day, lastDay: payload.last_day ?? days[days.length - 1].day };

  const burned = series(days, (day) => day.energy.total_kilocalories);
  const intake = series(days, (day) => day.intake?.kilocalories ?? null);
  const balance = differenceOf(intake, burned);
  const steps = series(days, (day) => day.energy.steps);
  const sleep = series(days, (day) => day.sleep.total_minutes);
  const hrv = series(days, (day) => day.recovery.hrv_last_night);
  const restingHeartRate = series(days, (day) => day.recovery.resting_heart_rate);
  const bodyBattery = series(days, (day) => day.recovery.body_battery_charged);
  const stress = series(days, (day) => day.recovery.average_stress);
  const weights = series(days, (day) => day.weight?.kilograms ?? null);

  const latestIntakeDay = [...days].reverse().find((day) => day.intake !== null);
  const latestIntake = latestIntakeDay?.intake ?? null;

  const weightChange =
    weights.length > 1 ? weights[weights.length - 1].value - weights[0].value : null;

  const intakeSourceOn = new Map<string, "logged" | "manual" | "carried">();

  for (const day of days) {
    if (day.intake !== null) {
      intakeSourceOn.set(day.day, day.intake.source);
    }
  }

  const recentWorkouts = [...days]
    .reverse()
    .flatMap((day) => day.activities.map((activity) => ({ day: day.day, activity })))
    .slice(0, 5);

  return (
    <>
      <PageTitle
        code="01 · Overview"
        title="All systems"
        description="Every headline reading, each placed against your own 30-day normal. Open a page on the left for the full picture behind any one of them."
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <StatTile
          label="Burned"
          tone="plume"
          value={formatNumber(newest(burned))}
          unit="kcal"
          summary={summaryFor(payload, "total_kilocalories")}
          chart={<MiniBars points={burned} colour={COLOUR_OF.plume} />}
        />
        <StatTile
          label="Intake"
          tone="signal"
          value={latestIntake === null ? NOTHING : formatNumber(latestIntake.kilocalories)}
          unit="kcal"
          goal={payload.macro_target === null ? undefined : formatNumber(payload.macro_target.kilocalories)}
          tag={latestIntake === null ? undefined : <SourceTag source={latestIntake.source} fromDay={latestIntake.from_day} />}
          footnote={
            latestIntake === null
              ? "nothing recorded yet"
              : latestIntake.source === "carried"
                ? `assumed from ${formatDay(latestIntake.from_day)}`
                : `recorded ${formatDay(latestIntakeDay!.day)}`
          }
          chart={<MiniBars points={intake} colour={COLOUR_OF.signal} goal={payload.macro_target?.kilocalories} />}
        />
        <StatTile
          label="Balance"
          tone="hull"
          value={formatSigned(newest(balance))}
          unit="kcal"
          footnote="intake minus Garmin's burn, last day with both. A direction, not a measurement."
          chart={<Sparkline points={balance} colour={COLOUR_OF.hull} formatValue={(value) => formatSigned(value)} />}
        />
        <StatTile
          label="Steps"
          tone="tele"
          value={formatNumber(newest(steps))}
          goal={formatNumber(STEP_GOAL)}
          summary={summaryFor(payload, "steps")}
          chart={<MiniBars points={steps} colour={COLOUR_OF.tele} goal={STEP_GOAL} />}
        />
        <StatTile
          label="Sleep"
          tone="ion"
          value={formatDuration(newest(sleep))}
          goal={formatDuration(SLEEP_GOAL_MINUTES)}
          summary={summaryFor(payload, "sleep_total_minutes")}
          goodWhenHigh
          chart={<Sparkline points={sleep} colour={COLOUR_OF.ion} formatValue={formatDuration} />}
        />
        <StatTile
          label="HRV"
          tone="tele"
          value={formatNumber(newest(hrv))}
          unit="ms"
          summary={summaryFor(payload, "hrv_last_night")}
          goodWhenHigh
          chart={<Sparkline points={hrv} colour={COLOUR_OF.tele} />}
        />
        <StatTile
          label="Resting HR"
          tone="tele"
          value={formatNumber(newest(restingHeartRate))}
          unit="bpm"
          summary={summaryFor(payload, "resting_heart_rate")}
          goodWhenHigh={false}
          chart={<Sparkline points={restingHeartRate} colour={COLOUR_OF.tele} />}
        />
        <StatTile
          label="Body battery"
          tone="solar"
          value={formatNumber(newest(bodyBattery))}
          summary={summaryFor(payload, "body_battery_charged")}
          goodWhenHigh
          footnote="charged overnight"
          chart={<Sparkline points={bodyBattery} colour={COLOUR_OF.solar} />}
        />
        <StatTile
          label="Stress"
          tone="ion"
          value={formatNumber(newest(stress))}
          summary={summaryFor(payload, "average_stress")}
          goodWhenHigh={false}
          footnote="Garmin daily average"
          chart={<Sparkline points={stress} colour={COLOUR_OF.ion} />}
        />
        <StatTile
          label="Weight"
          tone="solar"
          value={formatNumber(newest(weights), 1)}
          unit="kg"
          tag={<TrendBadge change={weightChange} unit=" kg" goodWhenDown />}
          footnote={`${weights.length} of ${days.length} mornings weighed`}
          chart={<Sparkline points={weights} colour={COLOUR_OF.solar} formatValue={(value) => value.toFixed(1)} />}
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[3fr_2fr]">
        <Panel>
          <PanelHeader
            icon={Flame}
            title="Energy · in against out"
            tone="signal"
            note="Bars are what went in; hollow bars are assumed from the last recorded day. The line is Garmin's estimate of what went out."
            meta={`${intake.length} of ${days.length} days`}
          />
          <PanelBody>
            <BarChart
              points={intake}
              colour={COLOUR_OF.signal}
              domain={domain}
              height={220}
              styleOf={(day) => (intakeSourceOn.get(day) === "carried" ? "hollow" : "solid")}
              goal={payload.macro_target === null ? undefined : { value: payload.macro_target.kilocalories, label: "target" }}
              overlay={{ name: "burned", points: burned, colour: COLOUR_OF.plume }}
              legend={
                <Legend
                  items={[
                    { name: "intake, recorded", colour: COLOUR_OF.signal },
                    { name: "intake, assumed", colour: COLOUR_OF.signal, hollow: true },
                    { name: "burned (Garmin)", colour: COLOUR_OF.plume },
                  ]}
                />
              }
            />
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader
            icon={Scale}
            title="Weight"
            tone="solar"
            note="Morning weigh-ins, exactly as read. Nothing is carried forward; a missed morning is a gap."
            meta={`${weights.length} weigh-ins`}
          />
          <PanelBody>
            {weights.length < 4 ? (
              <NotEnoughYet
                have={weights.length}
                need={4}
                noun="mornings"
                why="Daily swing is about a kilo on water. A line through two points would claim a direction it cannot know."
              />
            ) : (
              <LineChart
                series={[{ name: "weight", points: weights, colour: COLOUR_OF.solar }]}
                domain={domain}
                height={220}
                formatValue={(value) => value.toFixed(1)}
                band={bandFor(summaryFor(payload, "weight_kilograms"))}
              />
            )}
          </PanelBody>
        </Panel>
      </div>

      <div className="mt-4">
        <InsightPanel />
      </div>

      <Panel className="mt-4">
        <PanelHeader icon={Activity} title="Recent workouts" tone="tele" meta={`${recentWorkouts.length} shown`} />
        <PanelBody className="pt-2">
          {recentWorkouts.length === 0 ? (
            <p className="py-3 font-mono text-xs text-hull-400">no workouts in the span</p>
          ) : (
            <table className="tabular w-full text-sm">
              <thead>
                <tr className="readout-label text-left">
                  <th className="py-2 pr-3 font-semibold">Day</th>
                  <th className="py-2 pr-3 font-semibold">Type</th>
                  <th className="py-2 pr-3 text-right font-semibold">Duration</th>
                  <th className="py-2 pr-3 text-right font-semibold">Avg HR</th>
                  <th className="py-2 pr-3 text-right font-semibold">Active kcal</th>
                  <th className="py-2 text-right font-semibold">Distance · pace</th>
                </tr>
              </thead>
              <tbody>
                {recentWorkouts.map(({ day, activity }, index) => (
                  <tr key={`${day}-${index}`} className="border-t border-hull-700 text-hull-100">
                    <td className="py-2 pr-3 text-hull-300">{formatDay(day)}</td>
                    <td className="py-2 pr-3">{formatActivityType(activity.type_key)}</td>
                    <td className="py-2 pr-3 text-right">{formatDuration(activity.duration_minutes)}</td>
                    <td className="py-2 pr-3 text-right">{formatNumber(activity.average_heart_rate)}</td>
                    <td className="py-2 pr-3 text-right">{formatNumber(activity.active_kilocalories)}</td>
                    <td className="py-2 text-right">
                      {activity.distance_metres === null || activity.distance_metres <= 0
                        ? NOTHING
                        : `${formatKilometres(activity.distance_metres)} km · ${formatPace(activity.duration_minutes, activity.distance_metres)} /km`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </PanelBody>
      </Panel>
    </>
  );
}
