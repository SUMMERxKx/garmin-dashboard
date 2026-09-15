import { rangeOf, splitOnGaps, type Point } from "@/lib/derive";
import { formatShortDay } from "@/lib/format";

/**
 * The small plot that sits under a number.
 *
 * Its whole job is to answer "which way is this going", so it is deliberately plain:
 * no axes, no gridlines, no legend. It carries exactly two written values -- the lowest
 * and the highest -- because a shape with no scale can be read as any size of change at
 * all, which is how a chart misleads without containing a single wrong number.
 *
 * Gaps stay gaps. `splitOnGaps` breaks the line wherever more than two days pass with
 * no reading, so a fortnight of missed mornings never becomes a confident straight line
 * through days nothing was measured.
 */

const WIDTH = 320;
const HEIGHT = 64;
const PAD_X = 3;
const PAD_Y = 8;

export function MiniChart({
  points,
  colour,
  /** Flips the axis so "better" is always up: pace, resting heart rate, weight on a cut. */
  lowerIsBetter = false,
  filled = true,
  formatValue,
}: {
  points: Point[];
  colour: string;
  lowerIsBetter?: boolean;
  filled?: boolean;
  formatValue?: (value: number) => string;
}) {
  if (points.length === 0) {
    return (
      <div className="flex h-16 items-center border border-white/8 bg-white/[0.02] px-3 text-xs text-blossom-100/35">
        no readings yet
      </div>
    );
  }

  const range = rangeOf(points);
  const label = formatValue ?? ((value: number) => String(Math.round(value)));

  const firstTime = new Date(points[0].day).getTime();
  const lastTime = new Date(points[points.length - 1].day).getTime();
  const span = lastTime - firstTime || 1;

  // Positioned by date, not by index. Even spacing would squeeze a ten-day gap into the
  // same width as a one-day one and hide every break in the record.
  const toX = (day: string) =>
    PAD_X + ((new Date(day).getTime() - firstTime) / span) * (WIDTH - PAD_X * 2);

  const toY = (value: number) => {
    const share = (value - range.lowest) / (range.highest - range.lowest);
    return PAD_Y + (lowerIsBetter ? share : 1 - share) * (HEIGHT - PAD_Y * 2);
  };

  const segments = splitOnGaps(points);
  const newest = points[points.length - 1];
  const gradientId = `fade-${colour.replace(/[^a-z0-9]/gi, "")}`;

  return (
    <div>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-16 w-full"
        preserveAspectRatio="none"
        role="img"
        aria-label={`trend, ${label(range.lowest)} to ${label(range.highest)}`}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={colour} stopOpacity="0.30" />
            <stop offset="100%" stopColor={colour} stopOpacity="0" />
          </linearGradient>
        </defs>

        {filled &&
          segments.map((segment, index) =>
            segment.length < 2 ? null : (
              <polygon
                key={`fill-${index}`}
                points={[
                  `${toX(segment[0].day)},${HEIGHT}`,
                  ...segment.map((one) => `${toX(one.day)},${toY(one.value)}`),
                  `${toX(segment[segment.length - 1].day)},${HEIGHT}`,
                ].join(" ")}
                fill={`url(#${gradientId})`}
              />
            ),
          )}

        {segments.map((segment, index) => (
          <polyline
            key={index}
            points={segment.map((one) => `${toX(one.day)},${toY(one.value)}`).join(" ")}
            fill="none"
            stroke={colour}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        ))}

        {/* The newest reading gets a dot, because "where am I now" is the first thing
            anyone looks for on a trend. */}
        <circle cx={toX(newest.day)} cy={toY(newest.value)} r="3" fill={colour} />
      </svg>

      <div className="tabular mt-1 flex justify-between text-[0.65rem] text-blossom-100/35">
        <span>{formatShortDay(points[0].day)}</span>
        <span>
          {label(range.lowest)} – {label(range.highest)}
        </span>
        <span>{formatShortDay(newest.day)}</span>
      </div>
    </div>
  );
}

/**
 * A row of bars, for things counted per day rather than measured at a moment.
 *
 * Steps and calories are totals that accumulate, and drawing a total as a continuous
 * line implies you could read a value off it halfway through a day, which you cannot.
 */
export function MiniBars({
  points,
  colour,
  goal,
  formatValue,
}: {
  points: Point[];
  colour: string;
  /** Draws a dashed line at the target, if there is a real one. */
  goal?: number;
  formatValue?: (value: number) => string;
}) {
  if (points.length === 0) {
    return (
      <div className="flex h-16 items-center border border-white/8 bg-white/[0.02] px-3 text-xs text-blossom-100/35">
        no readings yet
      </div>
    );
  }

  const highest = Math.max(...points.map((one) => one.value), goal ?? 0);
  const label = formatValue ?? ((value: number) => String(Math.round(value)));

  return (
    <div>
      <div className="relative flex h-16 items-end justify-start gap-[2px]">
        {goal !== undefined && (
          <div
            className="pointer-events-none absolute inset-x-0 border-t border-dashed border-white/25"
            style={{ bottom: `${(goal / highest) * 100}%` }}
          />
        )}

        {points.map((one) => (
          <div
            key={one.day}
            className="min-w-0 flex-1 transition-opacity hover:opacity-100"
            style={{
              height: `${Math.max((one.value / highest) * 100, 2)}%`,
              // Capped, or a series with one or two readings stretches into a solid
              // block that reads as a filled area rather than as a single day. Food is
              // logged on one day out of thirty-one right now, and an uncapped bar made
              // that look like a chart with no data in it.
              maxWidth: "18px",
              backgroundColor: colour,
              // Older days recede, so the eye lands on the recent end without needing a
              // second colour.
              opacity: goal !== undefined && one.value >= goal ? 0.95 : 0.45,
            }}
            title={`${formatShortDay(one.day)} · ${label(one.value)}`}
          />
        ))}
      </div>

      <div className="tabular mt-1 flex justify-between text-[0.65rem] text-blossom-100/35">
        <span>{formatShortDay(points[0].day)}</span>
        {goal !== undefined && <span>goal {label(goal)}</span>}
        <span>{formatShortDay(points[points.length - 1].day)}</span>
      </div>
    </div>
  );
}
