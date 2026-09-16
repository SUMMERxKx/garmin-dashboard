import { rangeOf, splitOnGaps, type Point } from "@/lib/derive";
import { formatShortDay } from "@/lib/format";

/**
 * The small plot that sits under a number in a tile.
 *
 * Its whole job is to answer "which way is this going", so it is deliberately plain:
 * no axes, no gridlines. It carries exactly two written values -- the lowest and the
 * highest -- because a shape with no scale can be read as any size of change at all.
 * The full chart with axes lives on the metric's own page.
 */

const WIDTH = 320;
const HEIGHT = 44;
const PAD_X = 3;
const PAD_Y = 6;

export function Sparkline({
  points,
  colour,
  formatValue,
}: {
  points: Point[];
  colour: string;
  formatValue?: (value: number) => string;
}) {
  if (points.length === 0) {
    return (
      <div className="flex h-11 items-center border border-hull-700 bg-hull-950/40 px-3 font-mono text-[0.66rem] text-hull-400">
        no readings yet
      </div>
    );
  }

  const range = rangeOf(points);
  const label = formatValue ?? ((value: number) => String(Math.round(value)));

  const firstTime = new Date(points[0].day).getTime();
  const lastTime = new Date(points[points.length - 1].day).getTime();
  const span = lastTime - firstTime || 1;

  // Positioned by date, not by index, so a gap in the record stays a gap.
  const toX = (day: string) =>
    PAD_X + ((new Date(day).getTime() - firstTime) / span) * (WIDTH - PAD_X * 2);

  const toY = (value: number) => {
    const share = (value - range.lowest) / (range.highest - range.lowest);
    return PAD_Y + (1 - share) * (HEIGHT - PAD_Y * 2);
  };

  const segments = splitOnGaps(points);
  const latest = points[points.length - 1];

  // The written values are the real lowest and highest readings, not the padded axis
  // the line is drawn against. "0m" under a sleep chart whose worst night was four
  // hours would be the padding talking, not the data.
  const values = points.map((one) => one.value);
  const lowestReading = Math.min(...values);
  const highestReading = Math.max(...values);

  return (
    <div>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-11 w-full"
        preserveAspectRatio="none"
        role="img"
        aria-label={`trend, ${label(range.lowest)} to ${label(range.highest)}`}
      >
        {segments.map((segment, index) => (
          <polyline
            key={index}
            points={segment.map((one) => `${toX(one.day)},${toY(one.value)}`).join(" ")}
            fill="none"
            stroke={colour}
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
            opacity="0.85"
          />
        ))}
        <circle cx={toX(latest.day)} cy={toY(latest.value)} r="2.5" fill={colour} />
      </svg>

      <div className="tabular mt-1 flex justify-between font-mono text-[0.6rem] text-hull-400">
        <span>{formatShortDay(points[0].day)}</span>
        <span>
          {lowestReading === highestReading
            ? label(lowestReading)
            : `${label(lowestReading)} – ${label(highestReading)}`}
        </span>
        <span>{formatShortDay(latest.day)}</span>
      </div>
    </div>
  );
}

/**
 * A row of thin bars, for things counted per day rather than measured at a moment.
 *
 * Steps and calories accumulate, and a line through totals implies you could read a
 * value halfway through a day, which you cannot.
 */
export function MiniBars({
  points,
  colour,
  goal,
  formatValue,
}: {
  points: Point[];
  colour: string;
  goal?: number;
  formatValue?: (value: number) => string;
}) {
  if (points.length === 0) {
    return (
      <div className="flex h-11 items-center border border-hull-700 bg-hull-950/40 px-3 font-mono text-[0.66rem] text-hull-400">
        no readings yet
      </div>
    );
  }

  const highest = Math.max(...points.map((one) => one.value), goal ?? 0);
  const label = formatValue ?? ((value: number) => String(Math.round(value)));

  return (
    <div>
      <div className="relative flex h-11 items-end gap-[2px]">
        {goal !== undefined && (
          <div
            className="pointer-events-none absolute inset-x-0 border-t border-hull-300"
            style={{ bottom: `${(goal / highest) * 100}%` }}
          />
        )}

        {points.map((one) => (
          <div
            key={one.day}
            className="min-w-0 flex-1"
            style={{
              height: `${Math.max((one.value / highest) * 100, 3)}%`,
              maxWidth: "14px",
              backgroundColor: colour,
              opacity: goal !== undefined && one.value >= goal ? 0.9 : 0.45,
            }}
            title={`${formatShortDay(one.day)} · ${label(one.value)}`}
          />
        ))}
      </div>

      <div className="tabular mt-1 flex justify-between font-mono text-[0.6rem] text-hull-400">
        <span>{formatShortDay(points[0].day)}</span>
        {goal !== undefined && <span>goal {label(goal)}</span>}
        <span>{formatShortDay(points[points.length - 1].day)}</span>
      </div>
    </div>
  );
}
