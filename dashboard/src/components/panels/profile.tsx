import { useState } from "react";
import { AVATAR_URL, DISPLAY_NAME } from "@/config";
import type { DaysPayload } from "@/data/types";
import { formatNumber, NOTHING, parseIsoDay } from "@/lib/format";

/**
 * Who this is, and the four numbers that describe the body rather than the day.
 *
 * BMI is computed here rather than sent, because it is pure arithmetic over two values
 * the payload already carries and adding a field for it would mean two places could
 * disagree about what it is.
 *
 * It is also shown without a healthy/unhealthy badge, which the reference design has.
 * BMI cannot tell muscle from fat -- at 180 cm and 77.7 kg with 19.2% measured body fat,
 * a label calling this "overweight" would be describing the formula's blind spot rather
 * than the body. The DEXA figure beside it is the real answer, so the label is left off.
 */
export function ProfileCard({ payload }: { payload: DaysPayload }) {
  const [avatarFailed, setAvatarFailed] = useState(false);

  const latestWeighing = payload.days
    .map((one) => one.weight)
    .reverse()
    .find((one) => one !== null);

  const heightCentimetres = payload.profile?.height_centimetres ?? null;
  const weightKilograms = latestWeighing?.kilograms ?? null;

  const bodyMassIndex =
    heightCentimetres !== null && weightKilograms !== null
      ? weightKilograms / (heightCentimetres / 100) ** 2
      : null;

  // The scale's own estimate if this morning had one, otherwise the scan's measurement.
  // Which it is gets said out loud, because they are not the same kind of fact.
  const scaleFat = latestWeighing?.fat_percent ?? null;
  const scanFat = payload.latest_scan?.fat_percent ?? null;
  const fatPercent = scaleFat ?? scanFat;
  const fatSource =
    scaleFat !== null
      ? "scale"
      : scanFat !== null
        ? `DEXA ${payload.latest_scan?.scan_date ?? ""}`
        : null;

  const age =
    payload.profile?.birth_date != null
      ? Math.floor(
          (Date.now() - parseIsoDay(payload.profile.birth_date).getTime()) /
            (365.2425 * 24 * 60 * 60 * 1000),
        )
      : null;

  return (
    <section className="rounded-3xl border border-white/6 bg-night-850/70 p-5 backdrop-blur-md shadow-[0_1px_0_0_rgba(255,255,255,0.04)_inset,0_18px_40px_-28px_rgba(0,0,0,0.9)] sm:p-6">
      <div className="flex items-center gap-4 sm:gap-5">
        <div className="relative shrink-0">
          {/* Pixel frame: a hard ring and square corners, so the avatar reads as an
              8-bit portrait rather than a social-media bubble. */}
          <div className="grid size-20 place-items-center overflow-hidden rounded-2xl bg-night-800 ring-2 ring-blossom-400/40 sm:size-24">
            {avatarFailed ? (
              <PixelGoat />
            ) : (
              <img
                src={AVATAR_URL}
                alt=""
                className="pixelated size-full object-cover"
                onError={() => setAvatarFailed(true)}
              />
            )}
          </div>
        </div>

        <div className="min-w-0">
          <p className="text-xs font-medium tracking-wide text-blossom-100/45">Athlete</p>
          <h1 className="truncate text-[clamp(1.5rem,1.2rem+1.4vw,2.25rem)] font-bold leading-tight text-white">
            {DISPLAY_NAME}
          </h1>
          <p className="tabular mt-0.5 text-xs text-blossom-100/45">
            {age !== null && `${age} yrs`}
            {age !== null && heightCentimetres !== null && " · "}
            {heightCentimetres !== null && `${heightCentimetres} cm`}
          </p>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-x-4 gap-y-4 border-t border-dashed border-white/10 pt-5 sm:grid-cols-4">
        <Figure label="Weight" value={formatNumber(weightKilograms, 1)} unit="kg" />
        <Figure
          label="Body fat"
          value={fatPercent === null ? NOTHING : fatPercent.toFixed(1)}
          unit="%"
          note={fatSource ?? undefined}
        />
        <Figure
          label="BMI"
          value={bodyMassIndex === null ? NOTHING : bodyMassIndex.toFixed(1)}
          note="not a body-fat measure"
        />
        <Figure
          label="Lean mass"
          value={
            payload.latest_scan?.lean_and_bone_kilograms == null
              ? NOTHING
              : payload.latest_scan.lean_and_bone_kilograms.toFixed(1)
          }
          unit="kg"
          note={payload.latest_scan ? "incl. bone" : undefined}
        />
      </div>
    </section>
  );
}

function Figure({
  label,
  value,
  unit,
  note,
}: {
  label: string;
  value: string;
  unit?: string;
  note?: string;
}) {
  return (
    <div className="min-w-0">
      <p className="text-xs font-medium text-blossom-100/45">{label}</p>
      <p className="mt-0.5 flex items-baseline gap-1">
        <span className="tabular text-xl font-bold text-white sm:text-2xl">{value}</span>
        {unit !== undefined && (
          <span className="text-xs font-medium text-blossom-100/45">{unit}</span>
        )}
      </p>
      {note !== undefined && (
        <p className="truncate text-[0.65rem] text-blossom-100/30">{note}</p>
      )}
    </div>
  );
}

/**
 * The placeholder that shows until a real photo exists at /avatar.png.
 *
 * A goat, in pixels, because you asked for one. Drawn as a grid of squares rather than
 * shipped as an image file so there is no binary asset to keep track of, and so it
 * recolours with the theme.
 */
function PixelGoat() {
  // Each string is a row; each character a pixel. "." is transparent.
  const ART = [
    "..HH......HH....",
    ".HWWH....HWWH...",
    ".HWWWH..HWWWH...",
    "..HWWWHHWWWH....",
    "...HWWWWWWWH....",
    "..HWWWWWWWWWH...",
    ".HWWWWWWWWWWWH..",
    ".HWWPWWWWPWWWH..",
    ".HWWWWWWWWWWWH..",
    ".HWWWWNNWWWWWH..",
    "..HWWWNNWWWWH...",
    "..HWWWWWWWWH....",
    "...HHWWWWHH.....",
    ".....HHHH.......",
    "....H.....H.....",
    "....H.....H.....",
  ];

  const COLOURS: Record<string, string> = {
    H: "var(--color-night-600)",
    W: "var(--color-blossom-200)",
    P: "var(--color-night-900)",
    N: "var(--color-blossom-500)",
  };

  return (
    <svg viewBox="0 0 16 16" className="size-full" role="img" aria-label="pixel goat">
      {ART.flatMap((row, y) =>
        [...row].map((character, x) =>
          character === "." ? null : (
            <rect
              key={`${x}-${y}`}
              x={x}
              y={y}
              width="1"
              height="1"
              fill={COLOURS[character]}
            />
          ),
        ),
      )}
    </svg>
  );
}
