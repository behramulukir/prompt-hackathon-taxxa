import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * `cn` — the standard shadcn/ui className merge helper.
 * Combines clsx (conditional classes) + tailwind-merge (resolves conflicting utilities).
 *
 * @example
 *   cn("p-4", isActive && "bg-accent", "p-6") // → "bg-accent p-6"
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/**
 * Format a number in cents as a euro-cent string with sensible precision.
 *   formatCents(0.47) // → "0.47 ¢"
 *   formatCents(15.0) // → "15 ¢"
 */
export function formatCents(cents: number): string {
  if (cents < 1) return `${cents.toFixed(2)} ¢`;
  if (cents < 10) return `${cents.toFixed(1)} ¢`;
  return `${Math.round(cents)} ¢`;
}

/**
 * Format an ISO date string as "1 January 2026" (or "Tammikuu" if FI).
 */
export function formatDate(iso: string, lang: "fi" | "sv" | "en" = "en"): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const locale = lang === "fi" ? "fi-FI" : lang === "sv" ? "sv-SE" : "en-GB";
  return d.toLocaleDateString(locale, { year: "numeric", month: "long", day: "numeric" });
}
