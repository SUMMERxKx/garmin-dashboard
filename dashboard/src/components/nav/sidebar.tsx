import { Flame, Footprints, HeartPulse, LayoutGrid, PenLine, Scale, type LucideIcon } from "lucide-react";
import { DISPLAY_NAME } from "@/config";
import type { DataSource, DaysPayload } from "@/data/types";
import { formatShortDay } from "@/lib/format";
import { hrefFor, type Page } from "@/lib/router";
import { cn } from "@/lib/utils";

/**
 * The left rail on a wide screen; a scrolling tab strip on a narrow one.
 *
 * Six pages, because one screen holding everything was the clutter you did not like.
 * Each page answers one question -- how much energy, how recovered, how much moved, what
 * the body did -- and the Log page is where you type. Nothing is hidden at small widths:
 * every page is still reachable, it just sits in a row instead of a column.
 */

type Item = {
  page: Page;
  label: string;
  code: string;
  icon: LucideIcon;
};

const ITEMS: Item[] = [
  { page: "overview", label: "Overview", code: "01", icon: LayoutGrid },
  { page: "energy", label: "Energy", code: "02", icon: Flame },
  { page: "recovery", label: "Recovery", code: "03", icon: HeartPulse },
  { page: "activity", label: "Activity", code: "04", icon: Footprints },
  { page: "body", label: "Body", code: "05", icon: Scale },
  { page: "log", label: "Log", code: "06", icon: PenLine },
];

export function Sidebar({
  page,
  payload,
  source,
}: {
  page: Page;
  payload: DaysPayload | null;
  source: DataSource | null;
}) {
  return (
    <nav
      aria-label="pages"
      className="flex shrink-0 flex-col border-hull-700 bg-hull-950/80 lg:sticky lg:top-0 lg:h-screen lg:w-56 lg:border-r"
    >
      <div className="border-b border-hull-700 px-5 pt-5 pb-4">
        <p className="readout-label !text-tele-400">Telemetry</p>
        <p className="mt-1 font-condensed text-2xl font-semibold uppercase leading-none tracking-wide text-white">
          {DISPLAY_NAME}
        </p>
      </div>

      <ul className="flex gap-1 overflow-x-auto px-3 py-3 lg:flex-col lg:overflow-visible">
        {ITEMS.map((item) => {
          const active = item.page === page;
          const Icon = item.icon;

          return (
            <li key={item.page} className="shrink-0">
              <a
                href={hrefFor(item.page)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "group flex items-center gap-3 border-l-2 px-3 py-2 text-sm transition-colors",
                  active
                    ? "border-tele-400 bg-hull-800 text-white"
                    : "border-transparent text-hull-300 hover:bg-hull-900 hover:text-hull-100",
                )}
              >
                <span className="font-mono text-[0.6rem] text-hull-400 group-hover:text-hull-300">
                  {item.code}
                </span>
                <Icon className="size-4" strokeWidth={1.75} aria-hidden="true" />
                <span className="font-medium tracking-wide">{item.label}</span>
              </a>
            </li>
          );
        })}
      </ul>

      <div className="mt-auto hidden border-t border-hull-700 px-5 py-4 font-mono text-[0.66rem] leading-relaxed text-hull-400 lg:block">
        <p className="readout-label mb-1.5">Feed</p>
        <p className="flex items-center gap-2">
          <span
            className={cn("inline-block size-1.5", source === "api" ? "bg-signal-400" : "bg-hull-400")}
            aria-hidden="true"
          />
          {source === null ? "connecting…" : source === "api" ? "live · API on :8000" : "file · days.json"}
        </p>
        {payload !== null && payload.first_day !== null && payload.last_day !== null && (
          <>
            <p className="mt-1">
              {payload.days.length} days · {formatShortDay(payload.first_day)} → {formatShortDay(payload.last_day)}
            </p>
            <p className="mt-1 text-hull-500">
              built {payload.generated_at.replace("T", " ").slice(0, 16)}
            </p>
          </>
        )}
      </div>
    </nav>
  );
}
