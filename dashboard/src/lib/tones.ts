/**
 * The five signal colours, by name, in the three forms a component needs them in.
 *
 * One hue per kind of signal: blue for heart and movement, orange for energy burned,
 * green for energy taken in, violet for sleep, yellow for body battery and weight.
 * Colour is used on marks and rules only -- never on text, which stays in the greys so
 * the eye finds data by colour and reads it in white.
 *
 * The values themselves live in `index.css` as tokens. Written out here in full rather
 * than built from a template string, so Tailwind's scanner sees every class it needs
 * to emit.
 */

export type Tone = "tele" | "plume" | "signal" | "ion" | "solar" | "hull";

export const RULE_TONE: Record<Tone, string> = {
  tele: "bg-tele-400",
  plume: "bg-plume-400",
  signal: "bg-signal-400",
  ion: "bg-ion-400",
  solar: "bg-solar-400",
  hull: "bg-hull-400",
};

export const TEXT_TONE: Record<Tone, string> = {
  tele: "text-tele-400",
  plume: "text-plume-400",
  signal: "text-signal-400",
  ion: "text-ion-400",
  solar: "text-solar-400",
  hull: "text-hull-300",
};

/** The CSS variable for a tone, for SVG attributes that cannot take a class. */
export const COLOUR_OF: Record<Tone, string> = {
  tele: "var(--color-tele-400)",
  plume: "var(--color-plume-400)",
  signal: "var(--color-signal-400)",
  ion: "var(--color-ion-400)",
  solar: "var(--color-solar-400)",
  hull: "var(--color-hull-400)",
};
