import { useEffect, useRef, useState, type ReactNode } from "react";
import { niceTicks, rangeOf, splitOnGaps, type Point, type Range } from "@/lib/derive";
import { daysBetween, formatShortDay, parseIsoDay } from "@/lib/format";

/**
 * The two real charts: a line for things measured at a moment, bars for things counted
 * over a day. Both are plain SVG drawn at the container's pixel width, so text stays
 * crisp and nothing is stretched.
 *
 * WHAT EVERY CHART HERE DOES
 * --------------------------
 *   - Positions by DATE, not by index. A ten-day gap is ten days wide, so a break in the
 *     record is visible as a break, and every chart on a page shares the same x-axis when
 *     it is given the same `domain`.
 *   - Leaves gaps as gaps. A line is split wherever more than two days pass with no
 *     reading; bars simply are not drawn.
 *   - Carries a y-axis with round ticks and a hairline grid, so a shape can be read as a
 *     size. A shape with no scale can be read as any size of change at all.
 *   - Answers hover with a crosshair and a readout, so any value can be read exactly
 *     without cluttering the plot with a number on every point.
 *
 * The baseline BAND -- the 30-day mean with a standard deviation either side -- is drawn
 * as a wash behind the line, and comes finished from the Python engine. The chart does
 * not compute it; it only draws where it was told.
 */

const LEFT_GUTTER = 56;
const RIGHT_GUTTER = 12;
const TOP_GUTTER = 10;
const BOTTOM_GUTTER = 24;

const MILLISECONDS_PER_DAY = 24 * 60 * 60 * 1000;

export type Domain = {
  firstDay: string;
  lastDay: string;
};

export type Series = {
  name: string;
  points: Point[];
  colour: string;
  /** Drawn dashed: for a comparison line rather than a measurement. */
  dashed?: boolean;
};

export type Band = {
  low: number;
  high: number;
  /** The centre line, drawn solid through the band. */
  centre: number;
  label: string;
};

export type Marker = {
  value: number;
  label: string;
  colour?: string;
};

/** Measure the width of a container, so the SVG can be drawn at real pixels. */
function useWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const element = ref.current;

    if (element === null) {
      return;
    }

    setWidth(element.clientWidth);

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setWidth(entry.contentRect.width);
      }
    });

    observer.observe(element);

    return () => observer.disconnect();
  }, []);

  return [ref, width];
}

/** Map days to x pixels across the plot area. */
function makeXScale(domain: Domain, width: number) {
  const firstTime = parseIsoDay(domain.firstDay).getTime();
  const lastTime = parseIsoDay(domain.lastDay).getTime();
  const span = Math.max(lastTime - firstTime, MILLISECONDS_PER_DAY);
  const plotWidth = width - LEFT_GUTTER - RIGHT_GUTTER;

  return function toX(day: string): number {
    const share = (parseIsoDay(day).getTime() - firstTime) / span;
    return LEFT_GUTTER + share * plotWidth;
  };
}

function makeYScale(range: Range, height: number) {
  const plotHeight = height - TOP_GUTTER - BOTTOM_GUTTER;
  const span = range.highest - range.lowest || 1;

  return function toY(value: number): number {
    const share = (value - range.lowest) / span;
    return TOP_GUTTER + (1 - share) * plotHeight;
  };
}

/** Which days get a date label along the bottom: about six, evenly spaced. */
function pickDateTicks(domain: Domain): string[] {
  const total = daysBetween(domain.firstDay, domain.lastDay);
  const wanted = Math.min(6, total + 1);

  if (wanted <= 1) {
    return [domain.firstDay];
  }

  const step = total / (wanted - 1);
  const ticks: string[] = [];
  const first = parseIsoDay(domain.firstDay);

  for (let i = 0; i < wanted; i = i + 1) {
    const date = new Date(first);
    date.setDate(first.getDate() + Math.round(i * step));
    ticks.push(
      `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`,
    );
  }

  return ticks;
}

/** The nearest day to a mouse x position, among the days that have a point. */
function nearestDay(days: string[], toX: (day: string) => number, mouseX: number): string | null {
  let best: string | null = null;
  let bestDistance = Number.POSITIVE_INFINITY;

  for (const day of days) {
    const distance = Math.abs(toX(day) - mouseX);

    if (distance < bestDistance) {
      best = day;
      bestDistance = distance;
    }
  }

  return best;
}

function Axes({
  width,
  height,
  domain,
  range,
  toX,
  toY,
  formatValue,
}: {
  width: number;
  height: number;
  domain: Domain;
  range: Range;
  toX: (day: string) => number;
  toY: (value: number) => number;
  formatValue: (value: number) => string;
}) {
  const yTicks = niceTicks(range, 4);
  const dateTicks = pickDateTicks(domain);

  return (
    <g className="text-hull-400" fontSize="10" fontFamily="var(--font-mono)">
      {yTicks.map((tick) => (
        <g key={tick}>
          <line
            x1={LEFT_GUTTER}
            x2={width - RIGHT_GUTTER}
            y1={toY(tick)}
            y2={toY(tick)}
            stroke="var(--color-hull-700)"
            strokeWidth="1"
          />
          <text x={LEFT_GUTTER - 6} y={toY(tick)} dy="3.5" textAnchor="end" fill="currentColor">
            {formatValue(tick)}
          </text>
        </g>
      ))}

      {dateTicks.map((day, index) => {
        // The first and last labels hug their edge rather than centring on it, or the
        // last one runs off the right of the plot and reads "Sep 1" for "Sep 15".
        let anchor: "start" | "middle" | "end" = "middle";

        if (index === 0) {
          anchor = "start";
        } else if (index === dateTicks.length - 1) {
          anchor = "end";
        }

        return (
          <text key={day} x={toX(day)} y={height - 6} textAnchor={anchor} fill="currentColor">
            {formatShortDay(day)}
          </text>
        );
      })}
    </g>
  );
}

/** The hover readout: a small box near the cursor listing each series' value that day. */
function Readout({
  x,
  width,
  day,
  rows,
}: {
  x: number;
  width: number;
  day: string;
  rows: { colour: string; name: string; value: string }[];
}) {
  // Flip to the left of the cursor in the right half, so it never runs off the edge.
  const onRight = x < width / 2;

  return (
    <div
      className="pointer-events-none absolute top-1 z-10 border border-hull-600 bg-hull-950/95 px-2.5 py-2 font-mono text-[0.66rem] shadow-lg"
      style={onRight ? { left: x + 10 } : { right: width - x + 10 }}
    >
      <p className="text-hull-300">{formatShortDay(day)}</p>
      {rows.map((row) => (
        <p key={row.name} className="tabular mt-0.5 flex items-center gap-1.5 text-hull-100">
          <span className="inline-block size-1.5" style={{ backgroundColor: row.colour }} />
          <span className="text-hull-300">{row.name}</span>
          <span className="ml-auto pl-3 font-medium">{row.value}</span>
        </p>
      ))}
    </div>
  );
}

export function LineChart({
  series,
  domain,
  height = 200,
  formatValue = (value) => String(Math.round(value)),
  band,
  markers = [],
  includeZero = false,
  legend,
}: {
  series: Series[];
  domain: Domain;
  height?: number;
  formatValue?: (value: number) => string;
  /** The engine's normal, drawn as a wash behind the line. */
  band?: Band;
  /** Horizontal reference lines: a goal, Garmin's own baseline. */
  markers?: Marker[];
  /** Force the axis to start at zero. Off by default so a resting heart rate fills the plot. */
  includeZero?: boolean;
  /** Shown above the plot. Required from two series up; a single series is named by its panel. */
  legend?: ReactNode;
}) {
  const [containerRef, width] = useWidth();
  const [hoverDay, setHoverDay] = useState<string | null>(null);

  const everyPoint: Point[] = [];

  for (const one of series) {
    everyPoint.push(...one.points);
  }

  // The band and the markers must be inside the axis, or they are drawn off the plot.
  const extraValues: Point[] = [];

  if (band !== undefined) {
    extraValues.push({ day: domain.firstDay, value: band.low }, { day: domain.firstDay, value: band.high });
  }

  for (const marker of markers) {
    extraValues.push({ day: domain.firstDay, value: marker.value });
  }

  if (includeZero) {
    extraValues.push({ day: domain.firstDay, value: 0 });
  }

  const range = rangeOf([...everyPoint, ...extraValues]);

  if (everyPoint.length === 0) {
    return <EmptyPlot height={height} />;
  }

  const toX = makeXScale(domain, width);
  const toY = makeYScale(range, height);
  const days = [...new Set(everyPoint.map((one) => one.day))].sort();

  function onMove(event: React.MouseEvent<HTMLDivElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    setHoverDay(nearestDay(days, toX, event.clientX - bounds.left));
  }

  const hoverRows =
    hoverDay === null
      ? []
      : series.flatMap((one) => {
          const point = one.points.find((candidate) => candidate.day === hoverDay);
          return point === undefined ? [] : [{ colour: one.colour, name: one.name, value: formatValue(point.value) }];
        });

  return (
    <div>
      {legend}
      <div
        ref={containerRef}
        className="relative w-full"
        style={{ height }}
        onMouseMove={onMove}
        onMouseLeave={() => setHoverDay(null)}
      >
        {width > 0 && (
          <svg width={width} height={height} role="img" aria-label={`${series.map((one) => one.name).join(", ")} over time`}>
            {band !== undefined && (
              <g>
                <rect
                  x={LEFT_GUTTER}
                  width={width - LEFT_GUTTER - RIGHT_GUTTER}
                  y={toY(band.high)}
                  height={Math.max(0, toY(band.low) - toY(band.high))}
                  fill="var(--color-hull-100)"
                  opacity="0.05"
                />
                <line
                  x1={LEFT_GUTTER}
                  x2={width - RIGHT_GUTTER}
                  y1={toY(band.centre)}
                  y2={toY(band.centre)}
                  stroke="var(--color-hull-300)"
                  strokeWidth="1"
                />
                <text
                  x={width - RIGHT_GUTTER}
                  y={toY(band.centre) - 4}
                  textAnchor="end"
                  fontSize="9"
                  fontFamily="var(--font-mono)"
                  fill="var(--color-hull-300)"
                >
                  {band.label}
                </text>
              </g>
            )}

            <Axes width={width} height={height} domain={domain} range={range} toX={toX} toY={toY} formatValue={formatValue} />

            {markers.map((marker) => (
              <g key={marker.label}>
                <line
                  x1={LEFT_GUTTER}
                  x2={width - RIGHT_GUTTER}
                  y1={toY(marker.value)}
                  y2={toY(marker.value)}
                  stroke={marker.colour ?? "var(--color-hull-300)"}
                  strokeWidth="1"
                  strokeDasharray="3 4"
                />
                <text
                  x={LEFT_GUTTER + 4}
                  y={toY(marker.value) - 4}
                  fontSize="9"
                  fontFamily="var(--font-mono)"
                  fill={marker.colour ?? "var(--color-hull-300)"}
                >
                  {marker.label}
                </text>
              </g>
            ))}

            {series.map((one) =>
              splitOnGaps(one.points).map((segment, index) => (
                <polyline
                  key={`${one.name}-${index}`}
                  points={segment.map((point) => `${toX(point.day)},${toY(point.value)}`).join(" ")}
                  fill="none"
                  stroke={one.colour}
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeDasharray={one.dashed ? "4 4" : undefined}
                />
              )),
            )}

            {/* A lone reading has no line to be part of, so it gets a dot or it vanishes. */}
            {series.map((one) =>
              splitOnGaps(one.points)
                .filter((segment) => segment.length === 1)
                .map((segment) => (
                  <circle
                    key={`${one.name}-lone-${segment[0].day}`}
                    cx={toX(segment[0].day)}
                    cy={toY(segment[0].value)}
                    r="3"
                    fill={one.colour}
                  />
                )),
            )}

            {series.map((one) => {
              const last = one.points[one.points.length - 1];

              if (last === undefined) {
                return null;
              }

              return (
                <circle
                  key={`${one.name}-end`}
                  cx={toX(last.day)}
                  cy={toY(last.value)}
                  r="4"
                  fill={one.colour}
                  stroke="var(--color-hull-900)"
                  strokeWidth="2"
                />
              );
            })}

            {hoverDay !== null && (
              <g>
                <line
                  x1={toX(hoverDay)}
                  x2={toX(hoverDay)}
                  y1={TOP_GUTTER}
                  y2={height - BOTTOM_GUTTER}
                  stroke="var(--color-hull-300)"
                  strokeWidth="1"
                />
                {series.map((one) => {
                  const point = one.points.find((candidate) => candidate.day === hoverDay);

                  if (point === undefined) {
                    return null;
                  }

                  return (
                    <circle
                      key={`${one.name}-hover`}
                      cx={toX(point.day)}
                      cy={toY(point.value)}
                      r="4"
                      fill={one.colour}
                      stroke="var(--color-hull-900)"
                      strokeWidth="2"
                    />
                  );
                })}
              </g>
            )}
          </svg>
        )}

        {hoverDay !== null && hoverRows.length > 0 && (
          <Readout x={toX(hoverDay)} width={width} day={hoverDay} rows={hoverRows} />
        )}
      </div>
    </div>
  );
}

export type Stack = {
  name: string;
  colour: string;
  read: (day: string) => number | null;
};

/**
 * A style for one bar, chosen per day. Lets intake bars show their source: a carried
 * figure is drawn hollow so an assumption never looks like a measurement.
 */
export type BarStyle = "solid" | "hollow";

export function BarChart({
  points,
  colour,
  domain,
  height = 200,
  formatValue = (value) => String(Math.round(value)),
  goal,
  stacks,
  styleOf,
  overlay,
  legend,
  daysPerBar = 1,
}: {
  /** The days to draw bars for. With `stacks`, the value here is the total. */
  points: Point[];
  colour: string;
  domain: Domain;
  height?: number;
  formatValue?: (value: number) => string;
  goal?: Marker;
  /** Split each bar into parts, bottom first. */
  stacks?: Stack[];
  styleOf?: (day: string) => BarStyle;
  /** A line drawn over the bars, on the same axis: burn over intake. */
  overlay?: Series;
  legend?: ReactNode;
  /** How many days one bar stands for. 7 for a weekly chart, so the bars get a week's width. */
  daysPerBar?: number;
}) {
  const [containerRef, width] = useWidth();
  const [hoverDay, setHoverDay] = useState<string | null>(null);

  const extraValues: Point[] = [{ day: domain.firstDay, value: 0 }];

  if (goal !== undefined) {
    extraValues.push({ day: domain.firstDay, value: goal.value });
  }

  if (overlay !== undefined) {
    extraValues.push(...overlay.points);
  }

  const range = rangeOf([...points, ...extraValues], 0.08);

  if (points.length === 0) {
    return <EmptyPlot height={height} />;
  }

  const toX = makeXScale(domain, width);
  const toY = makeYScale(range, height);

  // One bar per day of the domain, capped so a short span does not become blocks.
  const totalDays = daysBetween(domain.firstDay, domain.lastDay) + 1;
  const totalBars = Math.max(totalDays / daysPerBar, 1);
  const slotWidth = (width - LEFT_GUTTER - RIGHT_GUTTER) / totalBars;
  const barWidth = Math.min(daysPerBar > 1 ? 40 : 24, Math.max(3, slotWidth - 2));

  const days = points.map((one) => one.day);

  function onMove(event: React.MouseEvent<HTMLDivElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    setHoverDay(nearestDay(days, toX, event.clientX - bounds.left));
  }

  const zeroY = toY(0);

  const hoverRows: { colour: string; name: string; value: string }[] = [];

  if (hoverDay !== null) {
    const point = points.find((one) => one.day === hoverDay);

    if (point !== undefined) {
      if (stacks === undefined) {
        hoverRows.push({ colour, name: "value", value: formatValue(point.value) });
      } else {
        for (const stack of stacks) {
          const part = stack.read(hoverDay);

          if (part !== null) {
            hoverRows.push({ colour: stack.colour, name: stack.name, value: formatValue(part) });
          }
        }

        hoverRows.push({ colour: "var(--color-hull-300)", name: "total", value: formatValue(point.value) });
      }
    }

    if (overlay !== undefined) {
      const overlayPoint = overlay.points.find((one) => one.day === hoverDay);

      if (overlayPoint !== undefined) {
        hoverRows.push({ colour: overlay.colour, name: overlay.name, value: formatValue(overlayPoint.value) });
      }
    }
  }

  return (
    <div>
      {legend}
      <div
        ref={containerRef}
        className="relative w-full"
        style={{ height }}
        onMouseMove={onMove}
        onMouseLeave={() => setHoverDay(null)}
      >
        {width > 0 && (
          <svg width={width} height={height} role="img" aria-label="daily values">
            <Axes width={width} height={height} domain={domain} range={range} toX={toX} toY={toY} formatValue={formatValue} />

            {points.map((one) => {
              const x = toX(one.day) - barWidth / 2;
              const style = styleOf === undefined ? "solid" : styleOf(one.day);
              const isHovered = one.day === hoverDay;

              if (stacks === undefined) {
                // A negative bar hangs from the zero line; a positive one stands on it.
                const top = Math.min(toY(one.value), zeroY);
                const barHeight = Math.max(Math.abs(toY(one.value) - zeroY), 1);

                return (
                  <rect
                    key={one.day}
                    x={x}
                    y={top}
                    width={barWidth}
                    height={barHeight}
                    fill={style === "solid" ? colour : "none"}
                    stroke={style === "hollow" ? colour : "none"}
                    strokeWidth={style === "hollow" ? 1.5 : 0}
                    opacity={isHovered || hoverDay === null ? 0.9 : 0.55}
                  />
                );
              }

              // Stacked: each part sits on the one below, with a 2px surface gap.
              let runningTop = zeroY;
              const parts: ReactNode[] = [];

              for (const stack of stacks) {
                const value = stack.read(one.day);

                if (value === null || value <= 0) {
                  continue;
                }

                const partHeight = zeroY - toY(value);
                const partTop = runningTop - partHeight;

                parts.push(
                  <rect
                    key={`${one.day}-${stack.name}`}
                    x={x}
                    y={partTop + 1}
                    width={barWidth}
                    height={Math.max(partHeight - 2, 0.5)}
                    fill={stack.colour}
                    opacity={isHovered || hoverDay === null ? 0.9 : 0.55}
                  />,
                );

                runningTop = partTop;
              }

              return <g key={one.day}>{parts}</g>;
            })}

            {/* The zero line, drawn over the bars so a balance chart reads at a glance. */}
            {range.lowest < 0 && (
              <line x1={LEFT_GUTTER} x2={width - RIGHT_GUTTER} y1={zeroY} y2={zeroY} stroke="var(--color-hull-300)" strokeWidth="1" />
            )}

            {goal !== undefined && (
              <g>
                <line
                  x1={LEFT_GUTTER}
                  x2={width - RIGHT_GUTTER}
                  y1={toY(goal.value)}
                  y2={toY(goal.value)}
                  stroke={goal.colour ?? "var(--color-hull-200)"}
                  strokeWidth="1"
                  strokeDasharray="3 4"
                />
                <text
                  x={width - RIGHT_GUTTER}
                  y={toY(goal.value) - 4}
                  textAnchor="end"
                  fontSize="9"
                  fontFamily="var(--font-mono)"
                  fill={goal.colour ?? "var(--color-hull-200)"}
                >
                  {goal.label}
                </text>
              </g>
            )}

            {overlay !== undefined &&
              splitOnGaps(overlay.points).map((segment, index) => (
                <polyline
                  key={`overlay-${index}`}
                  points={segment.map((point) => `${toX(point.day)},${toY(point.value)}`).join(" ")}
                  fill="none"
                  stroke={overlay.colour}
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              ))}

            {hoverDay !== null && (
              <line
                x1={toX(hoverDay)}
                x2={toX(hoverDay)}
                y1={TOP_GUTTER}
                y2={height - BOTTOM_GUTTER}
                stroke="var(--color-hull-300)"
                strokeWidth="1"
                opacity="0.6"
              />
            )}
          </svg>
        )}

        {hoverDay !== null && hoverRows.length > 0 && (
          <Readout x={toX(hoverDay)} width={width} day={hoverDay} rows={hoverRows} />
        )}
      </div>
    </div>
  );
}

/** A legend row: a swatch and a name per series. Always shown from two series up. */
export function Legend({ items }: { items: { name: string; colour: string; hollow?: boolean }[] }) {
  return (
    <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1">
      {items.map((item) => (
        <span key={item.name} className="flex items-center gap-1.5 font-mono text-[0.66rem] text-hull-300">
          <span
            className="inline-block size-2"
            style={
              item.hollow
                ? { border: `1.5px solid ${item.colour}` }
                : { backgroundColor: item.colour }
            }
          />
          {item.name}
        </span>
      ))}
    </div>
  );
}

function EmptyPlot({ height }: { height: number }) {
  return (
    <div
      className="flex items-center justify-center border border-hull-700 bg-hull-950/40 font-mono text-xs text-hull-400"
      style={{ height }}
    >
      no readings yet
    </div>
  );
}
