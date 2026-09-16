import { Activity, BatteryCharging, Droplets, HeartPulse, Moon } from "lucide-react";
import { BarChart, Legend, LineChart, type Domain } from "@/components/ui/charts";
import { StatTile } from "@/components/ui/stat-tile";
import { PageTitle, Panel, PanelBody, PanelHeader } from "@/components/ui/surface";
import { COLOUR_OF } from "@/lib/tones";
import { SLEEP_GOAL_MINUTES } from "@/config";
import type { DaysPayload } from "@/data/types";
import { newest, series } from "@/lib/derive";
import { formatDuration, formatNumber } from "@/lib/format";
import { bandFor, summaryFor } from "@/lib/summary";

/**
 * Recovery: the overnight signals, each against your own normal.
 *
 * There is deliberately no single recovery score. Compressing HRV, resting heart rate
 * and sleep into one number would throw away the useful part -- WHICH signal moved --
 * in exchange for false precision. Each chart carries the 30-day band from the engine
 * instead, so "is this unusual for me" is answered per signal, and answered by code that
 * is tested rather than by a colour picked in a browser.
 */
export function RecoveryPage({ payload }: { payload: DaysPayload }) {
  const days = payload.days;
  const domain: Domain = { firstDay: payload.first_day ?? days[0].day, lastDay: payload.last_day ?? days[days.length - 1].day };

  const hrv = series(days, (day) => day.recovery.hrv_last_night);
  const hrvWeekly = series(days, (day) => day.recovery.hrv_weekly_average);
  const garminFloor = newest(series(days, (day) => day.recovery.hrv_baseline));
  const restingHeartRate = series(days, (day) => day.recovery.resting_heart_rate);
  const sleep = series(days, (day) => day.sleep.total_minutes);
  const sleepScore = series(days, (day) => day.sleep.score);
  const charged = series(days, (day) => day.recovery.body_battery_charged);
  const drained = series(days, (day) => day.recovery.body_battery_drained);
  const stress = series(days, (day) => day.recovery.average_stress);

  const daysByDay = new Map(days.map((day) => [day.day, day]));

  const hrvSummary = summaryFor(payload, "hrv_last_night");
  const rhrSummary = summaryFor(payload, "resting_heart_rate");
  const sleepSummary = summaryFor(payload, "sleep_total_minutes");
  const scoreSummary = summaryFor(payload, "sleep_score");
  const batterySummary = summaryFor(payload, "body_battery_charged");
  const stressSummary = summaryFor(payload, "average_stress");

  return (
    <>
      <PageTitle
        code="03 · Recovery"
        title="Overnight signals"
        description="HRV, resting heart rate, sleep, body battery and stress, each drawn over the band of what is normal for you. The band is one standard deviation either side of your 30-day mean, computed by the engine."
        aside={
          payload.baselines?.as_of ? (
            <p className="font-mono text-[0.66rem] text-hull-400">windows end {payload.baselines.as_of}</p>
          ) : undefined
        }
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile label="HRV" tone="tele" value={formatNumber(newest(hrv))} unit="ms" summary={hrvSummary} goodWhenHigh footnote="overnight average" />
        <StatTile label="Resting HR" tone="tele" value={formatNumber(newest(restingHeartRate))} unit="bpm" summary={rhrSummary} goodWhenHigh={false} />
        <StatTile label="Sleep" tone="ion" value={formatDuration(newest(sleep))} goal={formatDuration(SLEEP_GOAL_MINUTES)} summary={sleepSummary} goodWhenHigh />
        <StatTile label="Sleep score" tone="ion" value={formatNumber(newest(sleepScore))} unit="/100" summary={scoreSummary} goodWhenHigh footnote="Garmin's own score" />
        <StatTile label="Body battery" tone="solar" value={formatNumber(newest(charged))} summary={batterySummary} goodWhenHigh footnote="charged overnight" />
        <StatTile label="Stress" tone="ion" value={formatNumber(newest(stress))} summary={stressSummary} goodWhenHigh={false} footnote="daily average, lower is calmer" />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel>
          <PanelHeader
            icon={Activity}
            title="HRV"
            tone="tele"
            note="Higher is better recovered. Garmin's own 7-night average is the dashed line; its 'balanced' floor is the marker."
            meta={`${hrv.length} nights`}
          />
          <PanelBody>
            <LineChart
              series={[
                { name: "last night", points: hrv, colour: COLOUR_OF.tele },
                { name: "Garmin 7-night avg", points: hrvWeekly, colour: "var(--color-hull-300)", dashed: true },
              ]}
              domain={domain}
              height={220}
              band={bandFor(hrvSummary)}
              markers={garminFloor === null ? [] : [{ value: garminFloor, label: "Garmin floor", colour: "var(--color-hull-400)" }]}
              legend={<Legend items={[{ name: "last night", colour: COLOUR_OF.tele }, { name: "Garmin 7-night average", colour: "var(--color-hull-300)" }]} />}
            />
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader icon={HeartPulse} title="Resting heart rate" tone="tele" note="Lower usually means better recovered. A steady metric: a one-beat move is normal noise." meta={`${restingHeartRate.length} days`} />
          <PanelBody>
            <LineChart
              series={[{ name: "resting HR", points: restingHeartRate, colour: COLOUR_OF.tele }]}
              domain={domain}
              height={220}
              band={bandFor(rhrSummary)}
            />
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader icon={Moon} title="Time asleep" tone="ion" note="Against an 8-hour goal and your own 30-day band." meta={`${sleep.length} nights`} />
          <PanelBody>
            <LineChart
              series={[{ name: "asleep", points: sleep, colour: COLOUR_OF.ion }]}
              domain={domain}
              height={220}
              formatValue={formatDuration}
              band={bandFor(sleepSummary)}
              markers={[{ value: SLEEP_GOAL_MINUTES, label: "goal", colour: "var(--color-hull-200)" }]}
            />
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader icon={Moon} title="Sleep stages" tone="ion" note="Deep at the bottom, then light, REM, and time awake on top. Garmin's staging is an estimate from movement and heart rate." />
          <PanelBody>
            <BarChart
              points={series(days, (day) => {
                const one = day.sleep;
                if (one.deep_minutes === null && one.light_minutes === null && one.rem_minutes === null) {
                  return null;
                }
                return (one.deep_minutes ?? 0) + (one.light_minutes ?? 0) + (one.rem_minutes ?? 0) + (one.awake_minutes ?? 0);
              })}
              colour={COLOUR_OF.ion}
              domain={domain}
              height={220}
              formatValue={formatDuration}
              stacks={[
                { name: "deep", colour: COLOUR_OF.ion, read: (day) => daysByDay.get(day)?.sleep.deep_minutes ?? null },
                { name: "light", colour: "color-mix(in oklch, var(--color-ion-400) 55%, var(--color-hull-700))", read: (day) => daysByDay.get(day)?.sleep.light_minutes ?? null },
                { name: "REM", colour: "color-mix(in oklch, var(--color-ion-400) 40%, white)", read: (day) => daysByDay.get(day)?.sleep.rem_minutes ?? null },
                { name: "awake", colour: "var(--color-hull-500)", read: (day) => daysByDay.get(day)?.sleep.awake_minutes ?? null },
              ]}
              legend={
                <Legend
                  items={[
                    { name: "deep", colour: COLOUR_OF.ion },
                    { name: "light", colour: "color-mix(in oklch, var(--color-ion-400) 55%, var(--color-hull-700))" },
                    { name: "REM", colour: "color-mix(in oklch, var(--color-ion-400) 40%, white)" },
                    { name: "awake", colour: "var(--color-hull-500)" },
                  ]}
                />
              }
            />
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader icon={Moon} title="Sleep score" tone="ion" note="Garmin's 0–100 score for the night. Shown for its trend; the minutes above are the measurement." />
          <PanelBody>
            <LineChart series={[{ name: "score", points: sleepScore, colour: COLOUR_OF.ion }]} domain={domain} height={200} band={bandFor(scoreSummary)} />
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader icon={BatteryCharging} title="Body battery" tone="solar" note="What the night put back against what the day took out. A day that drains more than the night charged is a day you ended lower than you started." />
          <PanelBody>
            <LineChart
              series={[
                { name: "charged overnight", points: charged, colour: COLOUR_OF.solar },
                { name: "drained by day", points: drained, colour: "var(--color-hull-300)", dashed: true },
              ]}
              domain={domain}
              height={200}
              band={bandFor(batterySummary, "30d charge")}
              legend={<Legend items={[{ name: "charged overnight", colour: COLOUR_OF.solar }, { name: "drained by day", colour: "var(--color-hull-300)" }]} />}
            />
          </PanelBody>
        </Panel>

        <Panel className="xl:col-span-2">
          <PanelHeader icon={Droplets} title="Stress" tone="ion" note="Garmin's daily average, 0–100, from heart-rate variability through the day. Lower is calmer." />
          <PanelBody>
            <LineChart series={[{ name: "stress", points: stress, colour: COLOUR_OF.ion }]} domain={domain} height={180} band={bandFor(stressSummary)} includeZero />
          </PanelBody>
        </Panel>
      </div>
    </>
  );
}
