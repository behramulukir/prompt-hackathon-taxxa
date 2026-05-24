"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Editorial top bar - sticky surface with backdrop-blur, Material icon brand
 * mark, mono nav links, FI · SV · EN language hint.
 *
 * Active-state matching: exact match for `/`, prefix match for everything
 * else - so `/ask?demo=q4` still highlights `Ask` and `/eval/audit` still
 * highlights `Eval`.
 */
export function Header() {
  const path = usePathname() ?? "/";
  const NAV = [
    { href: "/ask", label: "Ask" },
    { href: "/methodology", label: "Methodology" },
    { href: "/eval", label: "Eval" },
  ];
  const isActive = (href: string) =>
    href === "/" ? path === "/" : path === href || path.startsWith(href + "/");

  return (
    <header className="sticky top-0 z-50 w-full border-b border-outline-variant bg-surface/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-[1440px] items-center justify-between px-6">
        <Link
          href="/"
          aria-label="RAGTAG home"
          className="flex items-center gap-2 transition-opacity hover:opacity-80"
        >
          <span
            className="material-symbols-outlined filled text-secondary"
            style={{ fontSize: "var(--icon-lg)" }}
          >
            account_balance
          </span>
          <span
            className="font-serif text-2xl font-medium uppercase tracking-tight text-on-surface"
            style={{ fontWeight: 500 }}
          >
            RAGTAG
          </span>
        </Link>

        <nav
          className="hidden items-center md:flex"
          style={{ gap: "var(--space-7)" }}
          aria-label="Primary"
        >
          {NAV.map((n) => {
            const active = isActive(n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={active ? "page" : undefined}
                className={
                  "font-mono text-sm transition-colors duration-150 " +
                  (active
                    ? "border-b-2 border-primary pb-1 font-bold text-primary"
                    : "text-on-surface-variant hover:text-primary focus-visible:text-primary")
                }
              >
                {n.label}
              </Link>
            );
          })}
        </nav>

        <div className="hidden font-mono text-xs tracking-wider text-on-surface-variant md:block">
          FI · SV · EN
        </div>
      </div>
    </header>
  );
}
