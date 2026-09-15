"use client";

import { useEffect, useRef } from "react";

/**
 * Falling cherry blossom, on Canvas2D.
 *
 * Replaces the night-city effect: the same idea -- an animated background sampled onto
 * the page -- but the city was hard-edged and orange, which fought a soft pink theme
 * rather than supporting it.
 *
 * WHAT MAKES PETALS READ AS PETALS
 * --------------------------------
 * Three things, and none of them is the shape:
 *
 *   1. They FALL AND SWAY, not drop. A petal is light enough that air pushes it
 *      sideways, so the horizontal drift is a slow sine rather than a straight line.
 *   2. They TUMBLE. Each one spins on its own axis at its own rate, and the width is
 *      scaled by the cosine of that spin, so a petal periodically turns edge-on and
 *      nearly vanishes. Without this they look like falling confetti discs.
 *   3. They are AT DIFFERENT DEPTHS. Near petals are bigger, faster, and more opaque;
 *      far ones are small, slow and faint. A single depth reads as a screensaver.
 *
 * PERFORMANCE AND RESPECT
 * -----------------------
 * Petal count scales with the viewport area rather than being a fixed number, so a
 * phone is not asked to animate a desktop's worth of them. The whole animation is
 * skipped when the reader has asked for reduced motion -- a decorative background is
 * exactly the kind of thing that setting exists for, and it can genuinely make people
 * unwell.
 */

type Petal = {
  x: number;
  y: number;
  /** Half-width in pixels. Depth is expressed through this. */
  size: number;
  /** Downward speed, pixels per second. */
  fallSpeed: number;
  /** How far the sway carries it sideways. */
  swayRange: number;
  /** Where in its sway cycle it currently is. */
  swayPhase: number;
  swaySpeed: number;
  /** Current rotation and how fast it tumbles. */
  spin: number;
  spinSpeed: number;
  opacity: number;
  hue: number;
};

/** Petals per million square pixels. Tuned by eye: dense enough to read, sparse enough
 *  to ignore. Higher than first guessed, because the cards cover most of the viewport --
 *  only the margins and the gaps between panels ever show this, so the effective density
 *  a reader sees is a fraction of the number here. */
const PETAL_DENSITY = 120;

/** Never fewer than this, or a small window looks broken rather than calm. */
const MINIMUM_PETALS = 30;

/** Never more than this, whatever the screen size. */
const MAXIMUM_PETALS = 180;

function makeRandom(seed: number) {
  let state = seed;

  return function next(): number {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;

    return (state >>> 0) / 4294967296;
  };
}

function createPetal(random: () => number, width: number, height: number, startAbove: boolean): Petal {
  // Depth drives everything else, so it is drawn first and the rest derive from it.
  const depth = random();

  return {
    x: random() * width,
    // On first fill, scatter them through the height so the screen is not empty for the
    // first few seconds. After that, new petals enter from just above the top edge.
    y: startAbove ? -20 - random() * height * 0.4 : random() * height,
    size: 5 + depth * 11,
    fallSpeed: 14 + depth * 46,
    swayRange: 12 + depth * 34,
    swayPhase: random() * Math.PI * 2,
    swaySpeed: 0.35 + random() * 0.55,
    spin: random() * Math.PI * 2,
    spinSpeed: (random() - 0.5) * 1.7,
    opacity: 0.5 + depth * 0.45,
    // A narrow hue band around blossom pink. Wider and it stops looking like one tree.
    hue: 338 + random() * 22,
  };
}

/**
 * Draw one petal: a rounded lens shape, two arcs meeting at a point at each end.
 *
 * Simpler than a botanically correct five-lobed blossom and reads better at 6 pixels,
 * which is the size most of these are actually drawn at.
 */
function drawPetal(context: CanvasRenderingContext2D, petal: Petal) {
  // The tumble: cos() takes the width through zero twice per rotation, so the petal
  // turns edge-on and back. This is the single detail that sells the effect.
  const widthScale = Math.abs(Math.cos(petal.spin));
  const halfWidth = petal.size * (0.35 + widthScale * 0.65);
  const halfHeight = petal.size;

  context.save();
  context.translate(petal.x, petal.y);
  context.rotate(petal.spin * 0.4);
  context.globalAlpha = petal.opacity;

  const gradient = context.createLinearGradient(0, -halfHeight, 0, halfHeight);
  gradient.addColorStop(0, `hsl(${petal.hue} 95% 92%)`);
  gradient.addColorStop(1, `hsl(${petal.hue} 82% 76%)`);
  context.fillStyle = gradient;

  // A soft bloom around each petal. Pink on plum is a low-contrast pairing and at these
  // sizes the shapes were technically drawn but not actually visible -- the glow is what
  // separates them from the ground without resorting to a brighter, harsher pink.
  context.shadowColor = `hsl(${petal.hue} 90% 80% / 0.75)`;
  context.shadowBlur = petal.size * 2.2;

  context.beginPath();
  context.moveTo(0, -halfHeight);
  context.quadraticCurveTo(halfWidth, -halfHeight * 0.2, 0, halfHeight);
  context.quadraticCurveTo(-halfWidth, -halfHeight * 0.2, 0, -halfHeight);
  context.fill();

  context.restore();
}

export default function Petals({ className }: { className?: string }) {
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

    // A decorative animated background is precisely what this setting is for.
    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const random = makeRandom(0x62105511);
    let petals: Petal[] = [];
    let width = 0;
    let height = 0;
    let animationFrame = 0;
    let lastTimestamp = 0;

    function rebuild() {
      const parent = canvas!.parentElement;
      width = Math.max(1, parent?.clientWidth ?? window.innerWidth);
      height = Math.max(1, parent?.clientHeight ?? window.innerHeight);

      // Petals are soft-edged, so a device-pixel buffer buys nothing visible and costs
      // four times the fill area on a retina screen.
      canvas!.width = width;
      canvas!.height = height;

      const wanted = Math.round((width * height) / 1_000_000 * PETAL_DENSITY);
      const count = Math.min(MAXIMUM_PETALS, Math.max(MINIMUM_PETALS, wanted));

      petals = [];

      for (let i = 0; i < count; i = i + 1) {
        petals.push(createPetal(random, width, height, false));
      }
    }

    function draw(timestamp: number) {
      const elapsed = lastTimestamp === 0 ? 0 : (timestamp - lastTimestamp) / 1000;
      lastTimestamp = timestamp;

      context!.clearRect(0, 0, width, height);

      for (const petal of petals) {
        // Time-based rather than per-frame, so the fall is the same speed on a 60Hz and
        // a 120Hz screen. Clamped because a backgrounded tab resumes with a huge gap,
        // which would teleport every petal off the bottom at once.
        const step = Math.min(elapsed, 0.05);

        petal.y = petal.y + petal.fallSpeed * step;
        petal.swayPhase = petal.swayPhase + petal.swaySpeed * step;
        petal.spin = petal.spin + petal.spinSpeed * step;
        petal.x = petal.x + Math.sin(petal.swayPhase) * petal.swayRange * step;

        if (petal.y - petal.size > height) {
          // Recycle rather than allocate: the count is fixed, so a petal leaving the
          // bottom becomes the next one entering the top.
          const replacement = createPetal(random, width, height, true);
          Object.assign(petal, replacement);
        }

        // Wrap sideways so a long sway never strands one off-screen.
        if (petal.x < -20) {
          petal.x = width + 20;
        } else if (petal.x > width + 20) {
          petal.x = -20;
        }

        drawPetal(context!, petal);
      }

      animationFrame = requestAnimationFrame(draw);
    }

    rebuild();

    if (prefersReducedMotion) {
      // Draw one still frame and stop. The blossom is still there; it just does not move.
      context.clearRect(0, 0, width, height);
      for (const petal of petals) {
        drawPetal(context, petal);
      }
    } else {
      animationFrame = requestAnimationFrame(draw);
    }

    const observer = new ResizeObserver(rebuild);

    if (canvas.parentElement !== null) {
      observer.observe(canvas.parentElement);
    }

    return () => {
      cancelAnimationFrame(animationFrame);
      observer.disconnect();
    };
  }, []);

  return <canvas ref={canvasRef} className={className} aria-hidden="true" />;
}
