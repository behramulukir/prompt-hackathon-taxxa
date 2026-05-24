"use client";

/**
 * LanguageToggle — FI / SV / EN selector matching Taxxa's product
 * positioning. The query stays in the input language; the Drafter renders
 * the answer in the selected language. Maps 1:1 to the testimonial use
 * case from Rantalainen: "write my question in Swedish and receive an
 * English answer."
 */

import { cn } from "@/lib/utils";

export type Lang = "fi" | "sv" | "en";

interface LanguageToggleProps {
  value: Lang;
  onChange: (lang: Lang) => void;
}

const LABELS: Record<Lang, string> = {
  fi: "FI",
  sv: "SV",
  en: "EN",
};

export function LanguageToggle({ value, onChange }: LanguageToggleProps) {
  return (
    <div
      role="radiogroup"
      aria-label="Answer language"
      className="inline-flex overflow-hidden rounded-md border border-stroke-subtle text-xs font-mono"
    >
      {(["fi", "sv", "en"] as Lang[]).map((lang, i) => {
        const active = lang === value;
        return (
          <button
            key={lang}
            role="radio"
            aria-checked={active}
            onClick={() => onChange(lang)}
            className={cn(
              "px-2.5 py-1 transition",
              active
                ? "bg-accent text-bg-base"
                : "text-text-tertiary hover:bg-bg-panel hover:text-text-primary",
              i > 0 && "border-l border-stroke-subtle"
            )}
          >
            {LABELS[lang]}
          </button>
        );
      })}
    </div>
  );
}
