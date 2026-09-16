/**
 * The handful of things that are yours rather than the data's.
 *
 * Kept in one file so changing your name or your goals never means reading a component.
 * Everything else on the dashboard comes from the payload.
 */

/** Shown in the sidebar. */
export const DISPLAY_NAME = "Summer";

/**
 * Goals with no source in the data.
 *
 * Calories and macros are NOT here: those come from the dated targets in your food
 * library, so a dashboard for a past day is scored against the target that applied
 * then. These two have no such record, so they live here as plain defaults.
 *
 * There is deliberately no goal weight. That is a personal decision this app should not
 * invent, and a target nobody chose is worse than no target at all.
 */
export const STEP_GOAL = 10_000;
export const SLEEP_GOAL_MINUTES = 8 * 60;
