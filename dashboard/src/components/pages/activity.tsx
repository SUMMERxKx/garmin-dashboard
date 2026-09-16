import { Footprints, Route, Timer } from "lucide-react";
import { BarChart, Legend, LineChart, type Domain } from "@/components/ui/charts";
import { StatTile } from "@/components/ui/stat-tile";
import { NotEnoughYet, PageTitle, Panel, PanelBody, PanelHeader } from "@/components/ui/surface";
import { COLOUR_OF } from "@/lib/tones";
import { STEP_GOAL } from "@/config";
import type { Activity, DaysPayload } from "@/data/types";
import { byWeek, newest, series, weekStartOf, type Point } from "@/lib/derive";
import {
  formatActivityType,
  formatClock,
  formatDay,
  formatDuration,
  formatKilometres,
  formatNumber,
  formatPace,
  formatShortDay,
  NOTHING,
  paceMinutesPerKilometre,
} from "@/lib/format";
import { summaryFor } from "@/lib/summary";

/** Garmin's type keys that count as a run, for the running panel. */
const RUNNING_TYPES = new Set(["running", "treadmill_running", "trail_running", "track_running"]);

type Workout = {
  day: string;
  activity: Activity;
};

/**
 * Activity: movement through the day, and the workouts inside it.
 *
 * Steps and distance are Garmin's whole-day counts. The workouts are listed rather than
 * scored: there is no training load here, on purpose, because the FR165 does not produce
 * one and inventing one would be prescribing training, which this dashboard does not do.
 * Running gets its own panel because pace over distance is the one thing a runner
 * genuinely wants to see drift.
 */
export function ActivityPage({ payload }: { payload: DaysPayload }) {
  const days = payload.days;
  const domain: Domain = { firstDay: payload.first_day ?? days[0].day, lastDay: payload.last_day ?? days[days.length - 1].day };

  const steps = series(days, (day) => day.energy.steps);
  const distance = series(days, (day) => day.energy.distance_metres);
  const moderate = series(days, (day) => day.energy.moderate_intensity_minutes);
  const vigorous = series(days, (day) => day.energy.vigorous_intensity_minutes);
  const intensity = series(days, (day) => {
    if (day.energy.moderate_intensity_minutes === null && day.energy.vigorous_intensity_minutes === null) {
      return null;
    }
    return (day.energy.moderate_intensity_minutes ?? 0) + (day.energy.vigorous_intensity_minutes ?? 0);
  });

  const daysByDay = new Map(days.map((day) => [day.day, day]));
  const weeklyDistance = byWeek(distance, "sum");

  const workouts: Workout[] = [];

  for (const day of days) {
    for (const activity of day.activities) {
      workouts.push({ day: day.day, activity });
    }
  }

  const latestDay = days[days.length - 1].day;
  const thisWeekStart = weekStartOf(latestDay);
  const thisWeekIntensity = intensity.filter((one) => weekStartOf(one.day) === thisWeekStart);
  const thisWeekWorkouts = workouts.filter((one) => weekStartOf(one.day) === thisWeekStart);

  let thisWeekMinutes = 0;

  for (const one of thisWeekIntensity) {
    thisWeekMinutes = thisWeekMinutes + one.value;
  }

  const runs = workouts.filter((one) => one.activity.type_key !== null && RUNNING_TYPES.has(one.activity.type_key));
  const pacePoints: Point[] = [];
  const runDistance: Point[] = [];

  for (const run of runs) {
    const pace = paceMinutesPerKilometre(run.activity.duration_minutes, run.activity.distance_metres);

    if (pace !== null) {
      pacePoints.push({ day: run.day, value: pace });
    }

    if (run.activity.distance_metres !== null) {
      runDistance.push({ day: run.day, value: run.activity.distance_metres });
    }
  }

  const weeklyRunKilometres = byWeek(runDistance, "sum").map((one) => ({ day: one.day, value: one.value / 1000 }));

  const newestFirst = [...workouts].reverse();

  return (
    <>
      <PageTitle
        code="04 · Activity"
        title="Movement"
        description="Steps, distance and intensity minutes as Garmin counts them across the day, then every recorded workout. Runs get their own panel: pace and weekly kilometres."
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Steps" tone="tele" value={formatNumber(newest(steps))} goal={formatNumber(STEP_GOAL)} summary={summaryFor(payload, "steps")} footnote={`${steps.filter((one) => one.value >= STEP_GOAL).length} of ${steps.length} days over goal`} />
        <StatTile label="Distance" tone="tele" value={formatKilometres(newest(distance))} unit="km" footnote="whole day, per Garmin" />
        <StatTile label="Intensity, this week" tone="plume" value={formatNumber(thisWeekMinutes)} unit="min" footnote={`moderate plus vigorous, from ${formatShortDay(thisWeekStart)}`} />
        <StatTile label="Workouts" tone="tele" value={String(workouts.length)} footnote={`${thisWeekWorkouts.length} this week · ${runs.length} runs in the span`} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel>
          <PanelHeader icon={Footprints} title="Steps per day" tone="tele" meta={`${steps.length} days`} />
          <PanelBody>
            <BarChart points={steps} colour={COLOUR_OF.tele} domain={domain} height={220} goal={{ value: STEP_GOAL, label: "goal" }} formatValue={(value) => formatNumber(value)} />
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader icon={Route} title="Distance per week" tone="tele" note="Garmin's whole-day distance, walking included, summed Monday to Sunday. The current week is partial." />
          <PanelBody>
            <BarChart
              points={weeklyDistance}
              colour={COLOUR_OF.tele}
              domain={{ firstDay: weekStartOf(domain.firstDay), lastDay: weekStartOf(domain.lastDay) }}
              height={220}
              formatValue={(value) => `${formatKilometres(value, 0)} km`}
              daysPerBar={7}
            />
          </PanelBody>
        </Panel>

        <Panel className="xl:col-span-2">
          <PanelHeader icon={Timer} title="Intensity minutes" tone="plume" note="Garmin counts a minute as moderate or vigorous by heart rate. Stacked, moderate underneath." />
          <PanelBody>
            <BarChart
              points={intensity}
              colour={COLOUR_OF.plume}
              domain={domain}
              height={180}
              stacks={[
                { name: "moderate", colour: "var(--color-hull-500)", read: (day) => daysByDay.get(day)?.energy.moderate_intensity_minutes ?? null },
                { name: "vigorous", colour: COLOUR_OF.plume, read: (day) => daysByDay.get(day)?.energy.vigorous_intensity_minutes ?? null },
              ]}
              legend={<Legend items={[{ name: "moderate", colour: "var(--color-hull-500)" }, { name: "vigorous", colour: COLOUR_OF.plume }]} />}
            />
            <p className="mt-2 font-mono text-[0.66rem] text-hull-400">
              span totals · moderate {formatNumber(moderate.reduce((sum, one) => sum + one.value, 0))} min · vigorous {formatNumber(vigorous.reduce((sum, one) => sum + one.value, 0))} min
            </p>
          </PanelBody>
        </Panel>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel>
          <PanelHeader title="Running · pace per run" tone="signal" note="Minutes per kilometre for each recorded run. Lower is faster. Derived from duration and distance, so it always agrees with the table." meta={`${pacePoints.length} runs`} />
          <PanelBody>
            {pacePoints.length < 3 ? (
              <NotEnoughYet have={pacePoints.length} need={3} noun="runs" why="Pace drifts over weeks, not runs. A line through two runs would mostly show the difference between routes." />
            ) : (
              <LineChart series={[{ name: "pace", points: pacePoints, colour: COLOUR_OF.signal }]} domain={domain} height={200} formatValue={(value) => formatPace(value, 1000)} />
            )}
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader title="Running · kilometres per week" tone="signal" note="Only recorded runs, not the day's walking." />
          <PanelBody>
            {weeklyRunKilometres.length === 0 ? (
              <p className="py-3 font-mono text-xs text-hull-400">no runs in the span</p>
            ) : (
              <BarChart
                points={weeklyRunKilometres}
                colour={COLOUR_OF.signal}
                domain={{ firstDay: weekStartOf(domain.firstDay), lastDay: weekStartOf(domain.lastDay) }}
                height={200}
                formatValue={(value) => `${value.toFixed(1)} km`}
                daysPerBar={7}
              />
            )}
          </PanelBody>
        </Panel>
      </div>

      <Panel className="mt-4">
        <PanelHeader title="Every workout in the span" tone="tele" meta={`${workouts.length} recorded`} note="Active kcal is Garmin's total less the resting burn that would have happened anyway. Lifting sessions read high: heart rate stays up between sets without the oxygen cost." />
        <PanelBody className="overflow-x-auto pt-2">
          {workouts.length === 0 ? (
            <p className="py-3 font-mono text-xs text-hull-400">no workouts in the span</p>
          ) : (
            <table className="tabular w-full min-w-[44rem] text-sm">
              <thead>
                <tr className="readout-label text-left">
                  <th className="py-2 pr-3 font-semibold">Day</th>
                  <th className="py-2 pr-3 font-semibold">Start</th>
                  <th className="py-2 pr-3 font-semibold">Type</th>
                  <th className="py-2 pr-3 font-semibold">Name</th>
                  <th className="py-2 pr-3 text-right font-semibold">Duration</th>
                  <th className="py-2 pr-3 text-right font-semibold">Avg · max HR</th>
                  <th className="py-2 pr-3 text-right font-semibold">Active kcal</th>
                  <th className="py-2 pr-3 text-right font-semibold">Distance</th>
                  <th className="py-2 text-right font-semibold">Pace</th>
                </tr>
              </thead>
              <tbody>
                {newestFirst.map(({ day, activity }, index) => (
                  <tr key={`${day}-${index}`} className="border-t border-hull-700 text-hull-100">
                    <td className="py-2 pr-3 text-hull-300">{formatDay(day)}</td>
                    <td className="py-2 pr-3 text-hull-300">{formatClock(activity.started_at_local)}</td>
                    <td className="py-2 pr-3">{formatActivityType(activity.type_key)}</td>
                    <td className="max-w-[12rem] truncate py-2 pr-3 text-hull-300">{activity.name ?? NOTHING}</td>
                    <td className="py-2 pr-3 text-right">{formatDuration(activity.duration_minutes)}</td>
                    <td className="py-2 pr-3 text-right">{formatNumber(activity.average_heart_rate)} · {formatNumber(activity.maximum_heart_rate)}</td>
                    <td className="py-2 pr-3 text-right">{formatNumber(activity.active_kilocalories)}</td>
                    <td className="py-2 pr-3 text-right">{activity.distance_metres === null || activity.distance_metres <= 0 ? NOTHING : `${formatKilometres(activity.distance_metres, 2)} km`}</td>
                    <td className="py-2 text-right">{formatPace(activity.duration_minutes, activity.distance_metres)}</td>
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
