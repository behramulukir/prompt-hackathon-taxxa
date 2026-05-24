/**
 * Editorial footer — Stitch port.
 * White surface, hard border-top, mono link nav.
 */
export function Footer() {
  const LINKS = ["API", "Privacy", "Source", "Changelog"];
  return (
    <footer className="mt-auto w-full border-t border-outline-variant bg-surface-container-lowest">
      <div className="mx-auto flex max-w-[1440px] flex-col items-center justify-between gap-4 px-6 py-6 md:flex-row">
        <div className="font-mono text-xs uppercase tracking-widest text-on-surface-variant">
          Lex Atlas © 2026 · Distributed under AGPL-3.0
        </div>
        <nav className="flex items-center gap-6">
          {LINKS.map((l) => (
            <a
              key={l}
              href="#"
              className="font-mono text-xs text-on-surface-variant transition-colors hover:text-on-surface"
            >
              {l}
            </a>
          ))}
        </nav>
      </div>
    </footer>
  );
}
