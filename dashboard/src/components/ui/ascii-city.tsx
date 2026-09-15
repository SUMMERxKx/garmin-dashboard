"use client";

import { useEffect, useRef } from "react";

/**
 * The "Sunset" ASCII effect, reimplemented on Canvas2D, over a city-at-night scene.
 *
 * WHY THE SCENE IS DRAWN RATHER THAN LOADED
 * -----------------------------------------
 * The spec names a source photo (`/ascii-editor/demos/generated/ref-046.webp`) that does
 * not exist in this project. Rather than ship a broken <img>, the first stage below
 * *draws* a night skyline into an offscreen canvas -- sky gradient, stars, moon, three
 * depth layers of buildings, lit windows -- and every stage after it treats that canvas
 * exactly as it would treat a photograph. Swap `paintCity` for `drawImage(photo)` and
 * the rest of the pipeline is unchanged.
 *
 * THE PIPELINE, in the order the spec gives
 * -----------------------------------------
 *   1. source scene  ->  offscreen canvas at target size
 *   2. divide into `cellSize` cells, take each cell's average luminance
 *   3. draw one dot per cell, radius scaled by luminance      (renderMode: "dots")
 *   4. colour adjustments: contrast, then `tint` via `overlayBlend`
 *   5. post effects: bloom, vignette
 *   6. animate: "pulse", at `animSpeed` and `animIntensity`
 *
 * WHAT IS AND IS NOT IMPLEMENTED
 * ------------------------------
 * The parameter set is large and this implements the subset the supplied JSON actually
 * switches on: renderMode "dots", bgMode "solid", contrast, tint/overlayBlend, the
 * bloom and vignette post-effects, and the "pulse" animation. The other render modes,
 * the disabled post-effects, `lights`, `mask` and the tone curve are not implemented --
 * the props are typed so adding one is a local change, but pretending they work would
 * be worse than saying they do not.
 *
 * PERFORMANCE
 * -----------
 * A 1920x1080 canvas at cellSize 10 is about 20,000 cells, and 20,000 separate
 * `arc()` + `fill()` calls per frame will drop frames on a laptop. Two things fix that:
 * the luminance grid is sampled ONCE (the scene never changes, only the dots pulse),
 * and dots are bucketed into a handful of brightness bands, each drawn as a single
 * Path2D with one fill. That turns 20,000 fills per frame into six.
 */

type AsciiCityProps = {
  /** Grid cell size in CSS pixels. Smaller means finer detail and more work. */
  cellSize?: number;
  /** Contrast applied to sampled luminance, as a percentage. 100 is unchanged. */
  contrast?: number;
  /** Colour laid over the whole effect. */
  tint?: string;
  /** How strongly the tint shows, 0-100. */
  tintOpacity?: number;
  /** Canvas composite operation used to apply the tint. */
  overlayBlend?: GlobalCompositeOperation;
  /** Vignette strength, 0-100. 0 disables it. */
  vignette?: number;
  /** Bloom strength, 0-100. 0 disables it. */
  bloom?: number;
  /** Animation speed, 0-100. */
  animSpeed?: number;
  /** How far the pulse moves each dot, 0-100. */
  animIntensity?: number;
  /** Fraction of cells drawn at all, 0-100. */
  coverage?: number;
  className?: string;
};

/** How many brightness bands the dots are bucketed into before drawing. */
const BRIGHTNESS_BANDS = 6;

/** Dots dimmer than this are skipped entirely -- night sky is mostly empty. */
const MINIMUM_VISIBLE_LUMINANCE = 0.06;

/**
 * A tiny deterministic pseudo-random generator.
 *
 * `Math.random()` would give a different skyline on every re-render, so a window that
 * was lit a moment ago would go dark for no reason. Seeding it means the city is always
 * the same city.
 */
function makeRandom(seed: number) {
  let state = seed;

  return function next(): number {
    // xorshift32: cheap, no dependencies, and good enough for placing windows.
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;

    return (state >>> 0) / 4294967296;
  };
}

/** Draw the night-city scene that the effect samples from. */
function paintCity(context: CanvasRenderingContext2D, width: number, height: number) {
  const random = makeRandom(0x5eed1234);

  // --- sky: deep indigo overhead, warm haze at the horizon -------------------------
  const sky = context.createLinearGradient(0, 0, 0, height);
  sky.addColorStop(0, "#05060f");
  sky.addColorStop(0.45, "#141033");
  sky.addColorStop(0.72, "#3d1a44");
  sky.addColorStop(0.88, "#8a3320");
  sky.addColorStop(1, "#c8531f");
  context.fillStyle = sky;
  context.fillRect(0, 0, width, height);

  // --- stars, thinning out as they approach the bright horizon ---------------------
  const horizon = height * 0.72;

  for (let i = 0; i < 260; i = i + 1) {
    const x = random() * width;
    const y = random() * horizon;
    // Fade with depth so the sky does not look uniformly speckled.
    const fade = 1 - y / horizon;
    const radius = random() * 1.3 + 0.2;

    context.fillStyle = `rgba(255, 245, 225, ${0.15 + fade * 0.7 * random()})`;
    context.beginPath();
    context.arc(x, y, radius, 0, Math.PI * 2);
    context.fill();
  }

  // --- moon, low and large ---------------------------------------------------------
  const moonX = width * 0.76;
  const moonY = height * 0.2;
  const moonRadius = Math.min(width, height) * 0.075;

  const moonGlow = context.createRadialGradient(
    moonX, moonY, moonRadius * 0.4,
    moonX, moonY, moonRadius * 5,
  );
  moonGlow.addColorStop(0, "rgba(255, 230, 190, 0.55)");
  moonGlow.addColorStop(1, "rgba(255, 190, 120, 0)");
  context.fillStyle = moonGlow;
  context.fillRect(0, 0, width, height);

  context.fillStyle = "#fff3dc";
  context.beginPath();
  context.arc(moonX, moonY, moonRadius, 0, Math.PI * 2);
  context.fill();

  // --- three layers of buildings, near ones darker and taller ----------------------
  // Drawn far-to-near so each layer overlaps the one behind it.
  const layers = [
    { baseline: horizon + height * 0.02, minHeight: 0.10, maxHeight: 0.22, width: 0.055, shade: "#1a1330", windowChance: 0.18 },
    { baseline: horizon + height * 0.10, minHeight: 0.16, maxHeight: 0.34, width: 0.075, shade: "#0f0a22", windowChance: 0.26 },
    { baseline: height * 1.02,           minHeight: 0.22, maxHeight: 0.46, width: 0.10,  shade: "#06040f", windowChance: 0.32 },
  ];

  for (const layer of layers) {
    const buildingWidth = width * layer.width;

    for (let x = -buildingWidth; x < width + buildingWidth; x = x + buildingWidth * (0.7 + random() * 0.5)) {
      const buildingHeight =
        height * (layer.minHeight + random() * (layer.maxHeight - layer.minHeight));
      const top = layer.baseline - buildingHeight;
      const thisWidth = buildingWidth * (0.6 + random() * 0.55);

      context.fillStyle = layer.shade;
      context.fillRect(x, top, thisWidth, layer.baseline - top);

      // --- lit windows -------------------------------------------------------------
      const windowSize = Math.max(2, thisWidth * 0.1);
      const gap = windowSize * 0.85;

      for (let wy = top + gap * 2; wy < layer.baseline - gap; wy = wy + windowSize + gap) {
        for (let wx = x + gap; wx < x + thisWidth - windowSize; wx = wx + windowSize + gap) {
          if (random() > layer.windowChance) {
            continue;
          }

          // Most windows are warm tungsten; a few are cold fluorescent. That mix is
          // what stops a skyline reading as a repeating texture.
          const isCold = random() > 0.82;
          const brightness = 0.45 + random() * 0.55;

          context.fillStyle = isCold
            ? `rgba(180, 220, 255, ${brightness})`
            : `rgba(255, 190, 90, ${brightness})`;

          context.fillRect(wx, wy, windowSize, windowSize);
        }
      }
    }
  }
}

/**
 * Average luminance per grid cell, sampled once from the painted scene.
 *
 * Returns a flat array in row-major order, each entry 0..1. Flat rather than nested
 * because it is read once per cell per frame and a single array is markedly faster to
 * walk than an array of arrays.
 */
function sampleLuminance(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  cellSize: number,
  contrast: number,
): { grid: Float32Array; columns: number; rows: number } {
  const columns = Math.ceil(width / cellSize);
  const rows = Math.ceil(height / cellSize);
  const grid = new Float32Array(columns * rows);

  const image = context.getImageData(0, 0, width, height);
  const pixels = image.data;

  // Contrast as the usual around-the-midpoint scale: 115% pushes lights up and darks
  // down about the 0.5 line, which is what stops the dots reading as uniform grey.
  const contrastFactor = contrast / 100;

  for (let row = 0; row < rows; row = row + 1) {
    for (let column = 0; column < columns; column = column + 1) {
      const startX = column * cellSize;
      const startY = row * cellSize;
      const endX = Math.min(startX + cellSize, width);
      const endY = Math.min(startY + cellSize, height);

      let total = 0;
      let counted = 0;

      // Step by 2 rather than 1: sampling every fourth pixel is visually identical at
      // this cell size and quarters the work of the one expensive pass.
      for (let y = startY; y < endY; y = y + 2) {
        for (let x = startX; x < endX; x = x + 2) {
          const offset = (y * width + x) * 4;
          // Rec. 601 luma: the eye is far more sensitive to green than to blue, so a
          // plain (r+g+b)/3 would make blue windows look brighter than they are.
          total =
            total +
            (pixels[offset] * 0.299 + pixels[offset + 1] * 0.587 + pixels[offset + 2] * 0.114) / 255;
          counted = counted + 1;
        }
      }

      const average = counted > 0 ? total / counted : 0;
      const adjusted = (average - 0.5) * contrastFactor + 0.5;

      grid[row * columns + column] = Math.min(1, Math.max(0, adjusted));
    }
  }

  return { grid, columns, rows };
}

export default function AsciiCity({
  cellSize = 10,
  contrast = 115,
  tint = "#ff3b1f",
  tintOpacity = 32,
  overlayBlend = "overlay",
  vignette = 55,
  bloom = 45,
  animSpeed = 100,
  animIntensity = 60,
  coverage = 100,
  className,
}: AsciiCityProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;

    if (canvas === null) {
      return;
    }

    const context = canvas.getContext("2d");

    if (context === null) {
      return;
    }

    let animationFrame = 0;
    let sampled: { grid: Float32Array; columns: number; rows: number } | null = null;
    let width = 0;
    let height = 0;

    /** Repaint the scene and re-sample it. Called on mount and on every resize. */
    function rebuild() {
      const parent = canvas!.parentElement;
      // Render at CSS pixels rather than device pixels. This is a background behind a
      // dot grid; the extra sharpness of a 2x buffer is invisible and costs four times
      // the sampling work.
      width = Math.max(1, parent?.clientWidth ?? window.innerWidth);
      height = Math.max(1, parent?.clientHeight ?? window.innerHeight);

      canvas!.width = width;
      canvas!.height = height;

      const scene = document.createElement("canvas");
      scene.width = width;
      scene.height = height;

      const sceneContext = scene.getContext("2d", { willReadFrequently: true });

      if (sceneContext === null) {
        return;
      }

      paintCity(sceneContext, width, height);
      sampled = sampleLuminance(sceneContext, width, height, cellSize, contrast);
    }

    /** One animated frame. */
    function draw(timestamp: number) {
      if (sampled === null) {
        animationFrame = requestAnimationFrame(draw);
        return;
      }

      const { grid, columns, rows } = sampled;
      const context2d = context!;

      // --- stage 1: the solid background (bgMode "solid") ---------------------------
      context2d.globalCompositeOperation = "source-over";
      context2d.fillStyle = "#05060f";
      context2d.fillRect(0, 0, width, height);

      // --- stage 6: the pulse --------------------------------------------------------
      // A slow global breath, plus a per-cell phase offset so the grid shimmers rather
      // than throbbing as one flat sheet.
      const seconds = timestamp / 1000;
      const speed = (animSpeed / 100) * 1.4;
      const amplitude = (animIntensity / 100) * 0.45;

      // --- stage 3: one dot per cell, bucketed by brightness -------------------------
      // Each band gets its own Path2D so the whole grid is six fills, not twenty
      // thousand.
      const bands: Path2D[] = [];

      for (let i = 0; i < BRIGHTNESS_BANDS; i = i + 1) {
        bands.push(new Path2D());
      }

      const maximumRadius = cellSize * 0.48;
      const coverageThreshold = coverage / 100;

      for (let row = 0; row < rows; row = row + 1) {
        for (let column = 0; column < columns; column = column + 1) {
          const luminance = grid[row * columns + column];

          if (luminance < MINIMUM_VISIBLE_LUMINANCE) {
            continue;
          }

          // Deterministic per-cell "is this cell drawn at all", so coverage below 100
          // removes a stable set of cells rather than flickering a random set.
          if (coverageThreshold < 1) {
            const hash = ((row * 73856093) ^ (column * 19349663)) >>> 0;
            if ((hash % 1000) / 1000 > coverageThreshold) {
              continue;
            }
          }

          const phase = (row + column) * 0.35;
          const pulse = 1 + Math.sin(seconds * speed + phase) * amplitude;

          const radius = Math.max(0.3, luminance * maximumRadius * pulse);
          const band = Math.min(
            BRIGHTNESS_BANDS - 1,
            Math.floor(luminance * BRIGHTNESS_BANDS),
          );

          const centreX = column * cellSize + cellSize / 2;
          const centreY = row * cellSize + cellSize / 2;

          bands[band].moveTo(centreX + radius, centreY);
          bands[band].arc(centreX, centreY, radius, 0, Math.PI * 2);
        }
      }

      for (let i = 0; i < BRIGHTNESS_BANDS; i = i + 1) {
        const bandBrightness = (i + 1) / BRIGHTNESS_BANDS;
        // Warm white, brightening with the band. The tint below does the colouring.
        const channel = Math.round(150 + bandBrightness * 105);
        context2d.fillStyle = `rgba(${channel}, ${Math.round(channel * 0.88)}, ${Math.round(channel * 0.72)}, ${0.35 + bandBrightness * 0.65})`;
        context2d.fill(bands[i]);
      }

      // --- stage 5a: bloom -----------------------------------------------------------
      // Redraw the brightest bands blurred and additive, which is what makes lit
      // windows spill light the way they do through a camera.
      if (bloom > 0) {
        const strength = bloom / 100;
        context2d.save();
        context2d.globalCompositeOperation = "lighter";
        context2d.filter = `blur(${Math.max(1, cellSize * 0.6 * strength)}px)`;
        context2d.globalAlpha = strength * 0.55;

        for (let i = BRIGHTNESS_BANDS - 2; i < BRIGHTNESS_BANDS; i = i + 1) {
          context2d.fillStyle = "rgba(255, 190, 120, 1)";
          context2d.fill(bands[i]);
        }

        context2d.restore();
      }

      // --- stage 4: the tint, via the requested blend --------------------------------
      if (tintOpacity > 0) {
        context2d.save();
        context2d.globalCompositeOperation = overlayBlend;
        context2d.globalAlpha = tintOpacity / 100;
        context2d.fillStyle = tint;
        context2d.fillRect(0, 0, width, height);
        context2d.restore();
      }

      // --- stage 5b: vignette --------------------------------------------------------
      if (vignette > 0) {
        const strength = vignette / 100;
        const edge = context2d.createRadialGradient(
          width / 2, height / 2, Math.min(width, height) * 0.2,
          width / 2, height / 2, Math.max(width, height) * 0.75,
        );
        edge.addColorStop(0, "rgba(0, 0, 0, 0)");
        edge.addColorStop(1, `rgba(0, 0, 0, ${strength})`);

        context2d.save();
        context2d.globalCompositeOperation = "source-over";
        context2d.fillStyle = edge;
        context2d.fillRect(0, 0, width, height);
        context2d.restore();
      }

      animationFrame = requestAnimationFrame(draw);
    }

    rebuild();
    animationFrame = requestAnimationFrame(draw);

    // Re-sampling is the expensive half, so it only happens when the size actually
    // changes rather than on every frame.
    const observer = new ResizeObserver(rebuild);

    if (canvas.parentElement !== null) {
      observer.observe(canvas.parentElement);
    }

    return () => {
      cancelAnimationFrame(animationFrame);
      observer.disconnect();
    };
  }, [cellSize, contrast, tint, tintOpacity, overlayBlend, vignette, bloom, animSpeed, animIntensity, coverage]);

  return <canvas ref={canvasRef} className={className} aria-hidden="true" />;
}
