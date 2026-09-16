import { PenLine, Scale, Utensils } from "lucide-react";
import { useState, type FormEvent } from "react";
import { SourceTag } from "@/components/ui/stat-tile";
import { PageTitle, Panel, PanelBody, PanelHeader } from "@/components/ui/surface";
import type { DataSource, DaysPayload } from "@/data/types";
import { postIntake, postWeighing, type WriteResult } from "@/data/write";
import { formatDay, formatNumber, NOTHING, toIsoDay } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * The page you type on.
 *
 * Two forms, for the two numbers the watch cannot know: what you ate, and what you
 * weigh. Both post to the Python server, which runs the same checks the terminal does
 * and answers in the same sentences. A refusal is shown beside the form, not swallowed.
 *
 * When the payload came from the exported file rather than the API, the forms are
 * disabled and the terminal commands are shown instead. A form that appears to work and
 * silently goes nowhere is worse than no form.
 */
export function LogPage({
  payload,
  source,
  onSaved,
}: {
  payload: DaysPayload;
  source: DataSource;
  onSaved: () => Promise<void>;
}) {
  const canWrite = source === "api";
  const recent = [...payload.days].reverse().slice(0, 7);

  return (
    <>
      <PageTitle
        code="06 · Log"
        title="Manual entry"
        description="The two numbers the watch cannot know. A day with nothing typed or logged is assumed to be the same as the last day that was -- and is marked as assumed everywhere it appears."
        aside={<FeedStatus source={source} />}
      />

      {!canWrite && (
        <Panel className="mb-4 border-plume-400/40">
          <PanelBody>
            <p className="text-sm text-hull-100">
              The dashboard is reading the exported file, so these forms cannot save. Start the API and reload:
            </p>
            <pre className="mt-2 overflow-x-auto bg-hull-950 px-3 py-2 font-mono text-[0.7rem] text-hull-200">
              .venv/bin/uvicorn backend.api.server:app --reload --port 8000
            </pre>
            <p className="mt-2 text-[0.7rem] text-hull-400">
              Or record from the terminal: <code className="text-hull-200">main.py ate 2100</code> · <code className="text-hull-200">main.py weigh 80.0</code>, then re-run the export.
            </p>
          </PanelBody>
        </Panel>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <IntakeForm enabled={canWrite} onSaved={onSaved} targetKilocalories={payload.macro_target?.kilocalories ?? null} />
        <WeighForm enabled={canWrite} onSaved={onSaved} lastWeight={[...payload.days].reverse().find((day) => day.weight !== null)?.weight?.kilograms ?? null} />
      </div>

      <Panel className="mt-4">
        <PanelHeader icon={PenLine} title="Last seven days, as the dashboard sees them" tone="hull" note="Which figure each day is scored on, and where it came from." />
        <PanelBody className="pt-2">
          <table className="tabular w-full text-sm">
            <thead>
              <tr className="readout-label text-left">
                <th className="py-2 pr-3 font-semibold">Day</th>
                <th className="py-2 pr-3 text-right font-semibold">Intake</th>
                <th className="py-2 pr-3 font-semibold">Source</th>
                <th className="py-2 pr-3 text-right font-semibold">Weight</th>
                <th className="py-2 text-right font-semibold">Garmin fields</th>
              </tr>
            </thead>
            <tbody>
              {recent.map((day) => (
                <tr key={day.day} className="border-t border-hull-700 text-hull-100">
                  <td className="py-2 pr-3 text-hull-300">{formatDay(day.day)}</td>
                  <td className="py-2 pr-3 text-right">{formatNumber(day.intake?.kilocalories)}</td>
                  <td className="py-2 pr-3">
                    {day.intake === null ? (
                      <span className="text-hull-500">nothing yet</span>
                    ) : (
                      <span className="flex items-center gap-2">
                        <SourceTag source={day.intake.source} fromDay={day.intake.from_day} />
                        {day.intake.source === "carried" && <span className="font-mono text-[0.6rem] text-hull-400">from {day.intake.from_day}</span>}
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-right">{day.weight === null ? <span className="text-hull-500">{NOTHING}</span> : `${day.weight.kilograms.toFixed(1)} kg`}</td>
                  <td className="py-2 text-right text-hull-300">{day.fields_found}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </PanelBody>
      </Panel>
    </>
  );
}

function FeedStatus({ source }: { source: DataSource }) {
  return (
    <p className="flex items-center gap-2 border border-hull-700 px-3 py-1.5 font-mono text-[0.66rem] text-hull-300">
      <span className={cn("inline-block size-1.5", source === "api" ? "bg-signal-400" : "bg-plume-400")} aria-hidden="true" />
      {source === "api" ? "API live · writes go to dashboard.db" : "file only · writes disabled"}
    </p>
  );
}

/** The line under a form that says what happened. Green for stored, orange for refused. */
function Outcome({ result }: { result: WriteResult | null }) {
  if (result === null) {
    return null;
  }

  return (
    <p className={cn("mt-3 border-l-2 pl-3 text-sm", result.ok ? "border-signal-400 text-hull-100" : "border-plume-400 text-hull-100")}>
      {result.message}
    </p>
  );
}

function IntakeForm({
  enabled,
  onSaved,
  targetKilocalories,
}: {
  enabled: boolean;
  onSaved: () => Promise<void>;
  targetKilocalories: number | null;
}) {
  const [day, setDay] = useState(toIsoDay(new Date()));
  const [kilocalories, setKilocalories] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<WriteResult | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();

    const value = Number(kilocalories);

    if (!Number.isFinite(value)) {
      setResult({ ok: false, status: 0, message: "Type the day's calories as a number." });
      return;
    }

    setBusy(true);
    const outcome = await postIntake({ day, kilocalories: value, note: note.trim() === "" ? undefined : note.trim() });
    setResult(outcome);
    setBusy(false);

    if (outcome.ok) {
      setKilocalories("");
      setNote("");
      await onSaved();
    }
  }

  return (
    <Panel>
      <PanelHeader icon={Utensils} title="Day's calories" tone="signal" note="One number for the whole day. It overrides the itemised log for that day, and days after it with nothing recorded inherit it as assumed." />
      <PanelBody>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className="readout-label">Day</span>
            <input className="field" type="date" value={day} onChange={(event) => setDay(event.target.value)} required disabled={!enabled} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="readout-label">Kilocalories</span>
            <input
              className="field"
              type="number"
              inputMode="numeric"
              step="1"
              min="1"
              placeholder={targetKilocalories === null ? "2100" : String(Math.round(targetKilocalories))}
              value={kilocalories}
              onChange={(event) => setKilocalories(event.target.value)}
              required
              disabled={!enabled}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="readout-label">Note, optional</span>
            <input className="field" type="text" placeholder="dinner out" value={note} onChange={(event) => setNote(event.target.value)} disabled={!enabled} />
          </label>
          <SubmitButton busy={busy} enabled={enabled} label="Record calories" />
        </form>
        <Outcome result={result} />
      </PanelBody>
    </Panel>
  );
}

function WeighForm({
  enabled,
  onSaved,
  lastWeight,
}: {
  enabled: boolean;
  onSaved: () => Promise<void>;
  lastWeight: number | null;
}) {
  const [day, setDay] = useState(toIsoDay(new Date()));
  const [kilograms, setKilograms] = useState("");
  const [fatPercent, setFatPercent] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<WriteResult | null>(null);

  // Set after a 409, so the next submit sends `force`. Cleared on any change to the
  // number, because the confirmation was for THAT number.
  const [askedToForce, setAskedToForce] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();

    const value = Number(kilograms);

    if (!Number.isFinite(value)) {
      setResult({ ok: false, status: 0, message: "Type your weight in kilograms as a number." });
      return;
    }

    const fat = fatPercent.trim() === "" ? undefined : Number(fatPercent);

    setBusy(true);
    const outcome = await postWeighing({ day, kilograms: value, fat_percent: fat, force: askedToForce });
    setResult(outcome);
    setBusy(false);

    if (outcome.ok) {
      setKilograms("");
      setFatPercent("");
      setAskedToForce(false);
      await onSaved();
      return;
    }

    // The server's "far from your last weigh-in" answer. Offer to send it again.
    setAskedToForce(outcome.status === 409);
  }

  return (
    <Panel>
      <PanelHeader icon={Scale} title="Morning weigh-in" tone="solar" note="Exactly as read. One per day; a second replaces the first. Body fat is the scale's estimate, kept apart from the DEXA figure." meta={lastWeight === null ? undefined : `last ${lastWeight.toFixed(1)} kg`} />
      <PanelBody>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className="readout-label">Day</span>
            <input className="field" type="date" value={day} onChange={(event) => setDay(event.target.value)} required disabled={!enabled} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1">
              <span className="readout-label">Kilograms</span>
              <input
                className="field"
                type="number"
                inputMode="decimal"
                step="0.1"
                min="1"
                placeholder={lastWeight === null ? "80.0" : lastWeight.toFixed(1)}
                value={kilograms}
                onChange={(event) => {
                  setKilograms(event.target.value);
                  setAskedToForce(false);
                }}
                required
                disabled={!enabled}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="readout-label">Scale body fat %, optional</span>
              <input className="field" type="number" inputMode="decimal" step="0.1" min="1" max="70" placeholder="—" value={fatPercent} onChange={(event) => setFatPercent(event.target.value)} disabled={!enabled} />
            </label>
          </div>
          <SubmitButton busy={busy} enabled={enabled} label={askedToForce ? "Yes, record it anyway" : "Record weigh-in"} warn={askedToForce} />
        </form>
        <Outcome result={result} />
      </PanelBody>
    </Panel>
  );
}

function SubmitButton({ busy, enabled, label, warn = false }: { busy: boolean; enabled: boolean; label: string; warn?: boolean }) {
  return (
    <button
      type="submit"
      disabled={busy || !enabled}
      className={cn(
        "mt-1 border px-4 py-2 text-sm font-medium tracking-wide transition-colors disabled:cursor-not-allowed disabled:opacity-40",
        warn
          ? "border-plume-400 bg-plume-400/15 text-hull-100 hover:bg-plume-400/25"
          : "border-tele-400 bg-tele-400/15 text-hull-100 hover:bg-tele-400/25",
      )}
    >
      {busy ? "saving…" : label}
    </button>
  );
}
