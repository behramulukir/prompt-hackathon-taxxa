/**
 * TailwindSafelist - works around an intermittent Tailwind v4 + Next 15
 * (Webpack) + Windows content-scanning issue where some responsive classes
 * defined in nested route folders (e.g. app/ask/page.tsx) are not picked up
 * even with explicit @source globs.
 *
 * We render this component once from app/layout.tsx, hidden with display:none,
 * so React doesn't paint it but Tailwind's source scanner sees every class
 * string in this file and generates the corresponding CSS.
 *
 * NOTE: This is purely a build-time hack. The component returns nothing at
 * runtime (display:none, aria-hidden, suppress hydration), and the elements
 * are never reachable by users or screen readers.
 */
export function TailwindSafelist() {
  return (
    <div
      aria-hidden="true"
      suppressHydrationWarning
      className="hidden"
      style={{ display: "none" }}
    >
      {/* Responsive flex utilities */}
      <div className="md:flex md:flex-row md:flex-col md:hidden md:block lg:flex lg:flex-row lg:flex-col sm:flex sm:flex-row" />
      {/* Base + responsive grid columns */}
      <div className="grid-cols-1 grid-cols-2 grid-cols-3 grid-cols-4 grid-cols-6 grid-cols-12" />
      <div className="sm:grid-cols-1 sm:grid-cols-2 sm:grid-cols-3 sm:grid-cols-4" />
      <div className="md:grid-cols-1 md:grid-cols-2 md:grid-cols-3 md:grid-cols-4 md:grid-cols-12" />
      <div className="lg:grid-cols-1 lg:grid-cols-2 lg:grid-cols-3 lg:grid-cols-4 lg:grid-cols-12" />
      {/* Responsive col spans (methodology chapter layout) */}
      <div className="md:col-span-1 md:col-span-2 md:col-span-3 md:col-span-4 md:col-span-5 md:col-span-6 md:col-span-7 md:col-span-8 md:col-span-9 md:col-span-10 md:col-span-11 md:col-span-12" />
      <div className="lg:col-span-3 lg:col-span-4 lg:col-span-5 lg:col-span-6 lg:col-span-7 lg:col-span-8 lg:col-span-9" />
      {/* Responsive widths (side rail on /ask) */}
      <div className="md:w-72 md:w-80 md:w-96 lg:w-72 lg:w-80 lg:w-96" />
      {/* Responsive paddings */}
      <div className="md:pl-10 md:pl-4 md:pr-10 md:py-10 lg:py-20 lg:py-10" />
      {/* Responsive heights */}
      <div className="lg:h-[400px] lg:h-[600px]" />
    </div>
  );
}
