import { Flame, Utensils } from "lucide-react";
import { BarChart, Legend, LineChart, type Domain } from "@/components/ui/charts";
import { Reading, SourceTag, StatTile } from "@/components/ui/stat-tile";
import { PageTitle, Panel, PanelBody, PanelHeader } from "@/components/ui/surface";
import { COLOUR_OF } from "@/lib/tones";
import type { DaysPayload, MacroTarget } from "@/data/types";
import { cumulative, differenceOf, newest, recentMean, series } from "@/lib/derive";
import { formatDay, formatNumber, formatShortDay, formatSigned, NOTHING } from "@/lib/format";
import { summaryFor } from "@/lib/summary";

/**
 * Energy: what went in, what Garmin says went out, and the difference over time.
 *
 * The difference is labelled a BALANCE and never a deficit. Garmin's burn overstates
 * lifting -- your own data has 45 minutes at 124 bpm scored as 312 active kcal -- and
 * an intake figure is only as good as what got recorded. Their gap is a direction. The
 * running total at the bottom is the one worth watching: a single day's balance is
 * noise, but if the total keeps sloping the same way for weeks, that is real.
 */
export function EnergyPage({ payload }: { payload: DaysPayload }) {
  const days = payload.days;
  const domain: Domain = { firstDay: payload.first_day ?? days[0].day, lastDay: payload.last_day ?? days[days.length - 1].day };
  const target = payload.macro_target;

  const burned = series(days, (day) => day.energy.total_kilocalories);
  const active = series(days, (day) => day.energy.active_kilocalories);
  const resting = series(days, (day) => day.energy.resting_kilocalories);
  const intake = series(days, (day) => day.intake?.kilocalories ?? null);
  const balance = differenceOf(intake, burned);
  const runningBalance = cumulative(balance);

  const latestIntakeDay = [...days].reverse().find((day) => day.intake !== null);
  const latestIntake = latestIntakeDay?.intake ?? null;

  const intakeSourceOn = new Map<string, "logged" | "manual" | "carried">();
  const daysByDay = new Map(days.map((day) => [day.day, day]));

  for (const day of days) {
    if (day.intake !== null) {
      intakeSourceOn.set(day.day, day.intake.source);
    }
  }

  const carriedCount = [...intakeSourceOn.values()].filter((source) => source === "carried").length;

  const latestLoggedDay = [...days].reverse().find((day) => day.food !== null);

  const recentDays = [...days].reverse().slice(0, 14);

  return (
    <>
      <PageTitle
        code="02 · Energy"
        title="In against out"
        description="Intake beside Garmin's estimate of burn, day by day, and the running total of the difference. Both sides are estimates; the total's slope is the honest signal."
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile label="Burned" tone="plume" value={formatNumber(newest(burned))} unit="kcal" summary={summaryFor(payload, "total_kilocalories")} footnote="Garmin total, resting included" />
        <StatTile label="Active" tone="plume" value={formatNumber(newest(active))} unit="kcal" summary={summaryFor(payload, "active_kilocalories")} footnote="movement and training" />
        <StatTile label="Resting" tone="hull" value={formatNumber(newest(resting))} unit="kcal" footnote="Garmin's basal estimate" />
        <StatTile
          label="Intake"
          tone="signal"
          value={latestIntake === null ? NOTHING : formatNumber(latestIntake.kilocalories)}
          unit="kcal"
          goal={target === null ? undefined : formatNumber(target.kilocalories)}
          tag={latestIntake === null ? undefined : <SourceTag source={latestIntake.source} fromDay={latestIntake.from_day} />}
          footnote={latestIntake?.source === "carried" ? `assumed from ${formatDay(latestIntake.from_day)}` : undefined}
        />
        <StatTile label="Balance" tone="hull" value={formatSigned(newest(balance))} unit="kcal" footnote="last day with both sides" />
        <StatTile label="7-day balance" tone="hull" value={formatSigned(recentMean(balance, 7))} unit="kcal/day" footnote={balance.length < 7 ? `${balance.length} of 7 days` : "average of the last seven"} />
      </div>

      <Panel className="mt-4">
        <PanelHeader
          icon={Flame}
          title="Intake and burn, per day"
          tone="signal"
          note={`Hollow bars are assumed from the last recorded day${carriedCount > 0 ? ` (${carriedCount} of ${intake.length} days)` : ""}. The dashed line is your target.`}
        />
        <PanelBody>
          <BarChart
            points={intake}
            colour={COLOUR_OF.signal}
            domain={domain}
            height={260}
            styleOf={(day) => (intakeSourceOn.get(day) === "carried" ? "hollow" : "solid")}
            goal={target === null ? undefined : { value: target.kilocalories, label: "target" }}
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

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel>
          <PanelHeader title="Daily balance" tone="hull" note="Intake minus burn. Below the line means less went in than Garmin thinks went out." meta={`${balance.length} days`} />
          <PanelBody>
            <BarChart points={balance} colour={COLOUR_OF.tele} domain={domain} height={200} formatValue={(value) => formatSigned(value)} />
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader title="Running balance" tone="hull" note="The daily balances added up across the span. Slope is the signal; the level depends on where the span starts." />
          <PanelBody>
            <LineChart
              series={[{ name: "running balance", points: runningBalance, colour: COLOUR_OF.tele }]}
              domain={domain}
              height={200}
              formatValue={(value) => formatSigned(value)}
              includeZero
            />
          </PanelBody>
        </Panel>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel>
          <PanelHeader title="Burn, split" tone="plume" note="Resting is what the body costs lying still. Active is everything on top, and it is where Garmin's estimate is least certain." />
          <PanelBody>
            <BarChart
              points={burned}
              colour={COLOUR_OF.plume}
              domain={domain}
              height={200}
              stacks={[
                { name: "resting", colour: "var(--color-hull-500)", read: (day) => daysByDay.get(day)?.energy.resting_kilocalories ?? null },
                { name: "active", colour: COLOUR_OF.plume, read: (day) => daysByDay.get(day)?.energy.active_kilocalories ?? null },
              ]}
              legend={<Legend items={[{ name: "resting", colour: "var(--color-hull-500)" }, { name: "active", colour: COLOUR_OF.plume }]} />}
            />
          </PanelBody>
        </Panel>

        <Panel>
          <PanelHeader
            icon={Utensils}
            title="Macros, last logged day"
            tone="signal"
            meta={latestLoggedDay === undefined ? "no log" : formatDay(latestLoggedDay.day)}
            note="Only an itemised log knows the split. A typed total does not, so this shows the last day the log was kept."
          />
          <PanelBody>
            {latestLoggedDay === undefined || latestLoggedDay.food === null ? (
              <p className="py-3 font-mono text-xs text-hull-400">no itemised food log in the span</p>
            ) : (
              <MacroMeters totals={latestLoggedDay.food.totals} target={target} />
            )}
          </PanelBody>
        </Panel>
      </div>

      <Panel className="mt-4">
        <PanelHeader title="Last fourteen days" tone="hull" />
        <PanelBody className="overflow-x-auto pt-2">
          <table className="tabular w-full min-w-[36rem] text-sm">
            <thead>
              <tr className="readout-label text-left">
                <th className="py-2 pr-3 font-semibold">Day</th>
                <th className="py-2 pr-3 text-right font-semibold">In</th>
                <th className="py-2 pr-3 font-semibold">Source</th>
                <th className="py-2 pr-3 text-right font-semibold">Out</th>
                <th className="py-2 pr-3 text-right font-semibold">Active</th>
                <th className="py-2 pr-3 text-right font-semibold">Balance</th>
                <th className="py-2 text-right font-semibold">Steps</th>
              </tr>
            </thead>
            <tbody>
              {recentDays.map((day) => {
                const out = day.energy.total_kilocalories;
                const inn = day.intake?.kilocalories ?? null;
                const diff = inn !== null && out !== null ? inn - out : null;

                return (
                  <tr key={day.day} className="border-t border-hull-700 text-hull-100">
                    <td className="py-2 pr-3 text-hull-300">{formatShortDay(day.day)}</td>
                    <td className="py-2 pr-3 text-right">{formatNumber(inn)}</td>
                    <td className="py-2 pr-3">{day.intake === null ? <span className="text-hull-500">{NOTHING}</span> : <SourceTag source={day.intake.source} fromDay={day.intake.from_day} />}</td>
                    <td className="py-2 pr-3 text-right">{formatNumber(out)}</td>
                    <td className="py-2 pr-3 text-right text-hull-300">{formatNumber(day.energy.active_kilocalories)}</td>
                    <td className="py-2 pr-3 text-right">{formatSigned(diff)}</td>
                    <td className="py-2 text-right text-hull-300">{formatNumber(day.energy.steps)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </PanelBody>
      </Panel>
    </>
  );
}

/**
 * Protein, carbohydrate and fat against target, as three meters.
 *
 * The unfilled track is a darker step of the same colour, so the state reads across the
 * whole bar. Over target is shown, not clipped -- a meter that stops at 100% hides the
 * one thing you would want to know.
 */
function MacroMeters({
  totals,
  target,
}: {
  totals: { kilocalories: number; protein_grams: number; carbohydrate_grams: number; fat_grams: number };
  target: MacroTarget | null;
}) {
  const rows = [
    { name: "Calories", have: totals.kilocalories, want: target?.kilocalories ?? null, unit: "kcal" },
    { name: "Protein", have: totals.protein_grams, want: target?.protein_grams ?? null, unit: "g" },
    { name: "Carbohydrate", have: totals.carbohydrate_grams, want: target?.carbohydrate_grams ?? null, unit: "g" },
    { name: "Fat", have: totals.fat_grams, want: target?.fat_grams ?? null, unit: "g" },
  ];

  return (
    <div className="flex flex-col gap-3.5">
      {rows.map((row) => {
        const share = row.want === null || row.want === 0 ? null : row.have / row.want;

        return (
          <div key={row.name}>
            <div className="flex items-baseline justify-between gap-3">
              <Reading label={row.name} value={formatNumber(row.have, row.unit === "g" ? 1 : 0)} unit={row.unit} />
              <span className="tabular font-mono text-[0.66rem] text-hull-400">
                {row.want === null ? "no target" : `of ${formatNumber(row.want)} ${row.unit} · ${share === null ? "" : `${Math.round(share * 100)}%`}`}
              </span>
            </div>
            <div className="mt-1.5 h-1.5 w-full bg-hull-700">
              <div
                className="h-full bg-signal-400"
                style={{ width: `${share === null ? 0 : Math.min(share, 1) * 100}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
