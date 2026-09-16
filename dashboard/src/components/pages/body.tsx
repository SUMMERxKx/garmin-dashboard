import { Scale, ScanLine, User } from "lucide-react";
import { LineChart, type Domain } from "@/components/ui/charts";
import { Reading, StatTile, TrendBadge } from "@/components/ui/stat-tile";
import { NotEnoughYet, PageTitle, Panel, PanelBody, PanelHeader } from "@/components/ui/surface";
import { COLOUR_OF } from "@/lib/tones";
import { DISPLAY_NAME } from "@/config";
import type { DaysPayload } from "@/data/types";
import { newest, series } from "@/lib/derive";
import { formatDay, formatNumber, formatSigned, NOTHING, parseIsoDay } from "@/lib/format";
import { bandFor, summaryFor } from "@/lib/summary";

/** 365.2425 days, the Gregorian average once leap years are accounted for. */
const MILLISECONDS_IN_AN_AVERAGE_YEAR = 365.2425 * 24 * 60 * 60 * 1000;

/**
 * Body: the weigh-ins, and the one scan that says what the weight is made of.
 *
 * Two kinds of fact, deliberately never mixed. A morning weigh-in is a number read off a
 * scale, typed in, and kept exactly as read. A DEXA scan is a measurement of composition
 * taken on one date; it is shown WITH its date and never spread across the days after
 * it. Between scans the change in weight is reported and its split is not -- a modelled
 * fat/lean split would sit beside measured numbers and read exactly as solid as they are.
 */
export function BodyPage({ payload }: { payload: DaysPayload }) {
  const days = payload.days;
  const domain: Domain = { firstDay: payload.first_day ?? days[0].day, lastDay: payload.last_day ?? days[days.length - 1].day };

  const weights = series(days, (day) => day.weight?.kilograms ?? null);
  const scaleFat = series(days, (day) => day.weight?.fat_percent ?? null);
  const scan = payload.latest_scan;

  const latestWeight = newest(weights);
  const weightChange = weights.length > 1 ? weights[weights.length - 1].value - weights[0].value : null;
  const latestWeighDay = weights.length === 0 ? null : weights[weights.length - 1].day;

  const heightCentimetres = payload.profile?.height_centimetres ?? null;
  const bodyMassIndex =
    heightCentimetres !== null && latestWeight !== null ? latestWeight / (heightCentimetres / 100) ** 2 : null;

  const sinceScan =
    scan !== null && scan.total_mass_kilograms !== null && latestWeight !== null && latestWeighDay !== null && latestWeighDay > scan.scan_date
      ? latestWeight - scan.total_mass_kilograms
      : null;

  // Age against the payload's own `generated_at`, not the wall clock, so the whole page
  // is "as of" one moment and the render is the same on every re-render.
  const age =
    payload.profile?.birth_date != null
      ? Math.floor((new Date(payload.generated_at).getTime() - parseIsoDay(payload.profile.birth_date).getTime()) / MILLISECONDS_IN_AN_AVERAGE_YEAR)
      : null;

  return (
    <>
      <PageTitle
        code="05 · Body"
        title="Mass and composition"
        description="Morning weigh-ins as read, and the DEXA scan that says what the weight is made of. Weight is the number that checks every other number on this dashboard."
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile label="Weight" tone="solar" value={formatNumber(latestWeight, 1)} unit="kg" summary={summaryFor(payload, "weight_kilograms")} footnote={latestWeighDay === null ? "no weigh-in yet" : `weighed ${formatDay(latestWeighDay)}`} />
        <StatTile label="Change, span" tone="solar" value={formatSigned(weightChange, 1)} unit="kg" tag={<TrendBadge change={weightChange} goodWhenDown />} footnote={weights.length > 1 ? `first to latest weigh-in, ${weights.length} readings` : "needs two weigh-ins"} />
        <StatTile label="Consistency" tone="hull" value={`${weights.length}/${days.length}`} unit="mornings" footnote="every average below gets worse as this drops" />
        <StatTile label="BMI" tone="hull" value={bodyMassIndex === null ? NOTHING : bodyMassIndex.toFixed(1)} footnote="cannot tell muscle from fat; the scan can" />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[3fr_2fr]">
        <Panel>
          <PanelHeader icon={Scale} title="Weight" tone="solar" note="Exactly as read. Day-to-day movement is mostly water and food weight; only a run of weeks says anything about fat." meta={`${weights.length} weigh-ins`} />
          <PanelBody>
            {weights.length < 4 ? (
              <NotEnoughYet have={weights.length} need={4} noun="mornings" why="A trend through two points is the chart claiming a direction it cannot know." />
            ) : (
              <LineChart
                series={[{ name: "weight", points: weights, colour: COLOUR_OF.solar }]}
                domain={domain}
                height={260}
                formatValue={(value) => value.toFixed(1)}
                band={bandFor(summaryFor(payload, "weight_kilograms"))}
                markers={scan?.total_mass_kilograms == null ? [] : [{ value: scan.total_mass_kilograms, label: `DEXA ${scan.scan_date}`, colour: "var(--color-hull-300)" }]}
              />
            )}

            {scaleFat.length > 0 && (
              <div className="mt-4 border-t border-hull-700 pt-3">
                <p className="readout-label mb-2">Scale body fat</p>
                <LineChart series={[{ name: "scale %", points: scaleFat, colour: COLOUR_OF.solar }]} domain={domain} height={120} formatValue={(value) => `${value.toFixed(1)}%`} />
                <p className="mt-1 text-[0.7rem] text-hull-400">A scale infers this from electrical resistance and it moves with hydration. Useful for trend, not for level.</p>
              </div>
            )}
          </PanelBody>
        </Panel>

        <div className="flex flex-col gap-4">
          <Panel>
            <PanelHeader icon={ScanLine} title="DEXA scan" tone="tele" meta={scan === null ? "none yet" : formatDay(scan.scan_date)} note={scan?.provider ?? undefined} />
            <PanelBody>
              {scan === null ? (
                <p className="py-3 font-mono text-xs text-hull-400">no scan recorded. Add one to docs/personal/dexa-scans.yaml.</p>
              ) : (
                <>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-4">
                    <Reading label="Body fat" value={scan.fat_percent === null ? NOTHING : scan.fat_percent.toFixed(1)} unit="%" tone="tele" />
                    <Reading label="Total mass" value={formatNumber(scan.total_mass_kilograms, 1)} unit="kg" />
                    <Reading label="Fat mass" value={formatNumber(scan.fat_mass_kilograms, 1)} unit="kg" />
                    <Reading label="Lean + bone" value={formatNumber(scan.lean_and_bone_kilograms, 1)} unit="kg" />
                    <Reading label="Visceral fat" value={formatNumber(scan.visceral_fat_grams)} unit="g" />
                    <Reading label="Bone density" value={scan.bone_mineral_density === null ? NOTHING : scan.bone_mineral_density.toFixed(3)} unit="g/cm²" />
                    <Reading label="T-score" value={scan.bmd_t_score === null ? NOTHING : scan.bmd_t_score.toFixed(1)} unit="vs young adult" />
                    <Reading label="Z-score" value={scan.bmd_z_score === null ? NOTHING : scan.bmd_z_score.toFixed(1)} unit="vs your age" />
                  </div>

                  <div className="mt-4 border-t border-hull-700 pt-3">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="readout-label">Weight since scan</span>
                      <span className="tabular text-base font-semibold text-white">
                        {formatSigned(sinceScan, 1)} <span className="text-[0.66rem] font-normal text-hull-400">kg</span>
                      </span>
                    </div>
                    <p className="mt-1.5 text-[0.7rem] leading-snug text-hull-400">
                      Measured, not split. Whether it came off as fat or lean is only known at the next scan. One scan anchors; two measure.
                    </p>
                  </div>
                </>
              )}
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader icon={User} title="Profile" tone="hull" />
            <PanelBody>
              <div className="grid grid-cols-3 gap-4">
                <Reading label="Name" value={DISPLAY_NAME} />
                <Reading label="Age" value={age === null ? NOTHING : String(age)} unit="yrs" />
                <Reading label="Height" value={heightCentimetres === null ? NOTHING : String(heightCentimetres)} unit="cm" />
              </div>
              {payload.macro_target !== null && (
                <p className="mt-3 border-t border-hull-700 pt-3 font-mono text-[0.66rem] text-hull-400">
                  target since {payload.macro_target.effective_from} · {payload.macro_target.goal} · {formatNumber(payload.macro_target.kilocalories)} kcal · {payload.macro_target.protein_grams}P {payload.macro_target.carbohydrate_grams}C {payload.macro_target.fat_grams}F
                </p>
              )}
            </PanelBody>
          </Panel>
        </div>
      </div>
    </>
  );
}
