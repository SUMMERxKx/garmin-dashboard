import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

/**
 * Join class names, letting later Tailwind classes beat earlier ones.
 *
 * This is the helper every shadcn component imports, which is why it has to live at
 * exactly this path. `clsx` handles the conditional bits (`isActive && "border-black"`);
 * `twMerge` resolves the conflicts clsx would otherwise leave behind -- given
 * "p-2 p-6" plain string joining keeps both and CSS picks by source order, which is a
 * coin flip. twMerge knows they are the same property and keeps the last one.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
