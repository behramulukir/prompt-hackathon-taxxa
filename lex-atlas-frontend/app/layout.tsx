import type { Metadata } from "next";
import { Suspense } from "react";
import { Inter, JetBrains_Mono, EB_Garamond } from "next/font/google";
import Script from "next/script";
import { ThemeProvider } from "@/components/theme-provider";
import { TailwindSafelist } from "@/components/TailwindSafelist";
import { NavigationProgress } from "@/components/NavigationProgress";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  weight: ["400", "500", "600"],
  display: "swap",
  adjustFontFallback: true,
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  weight: ["400", "500", "600"],
  display: "swap",
});

const ebGaramond = EB_Garamond({
  subsets: ["latin"],
  variable: "--font-eb-garamond",
  weight: ["400", "500", "600"],
  style: ["normal", "italic"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "RAGTAG · Retrieval Augmented Graph Tax Answer Generator",
  description:
    "Continuous multi-agent retrieval and reasoning over Finlex + Vero + KHO. Aalto Prompt Finance Hackathon · Challenge by Taxxa AI.",
  metadataBase: new URL(process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000"),
  openGraph: {
    title: "RAGTAG",
    description: "Retrieval Augmented Graph Tax Answer Generator for Finnish tax law.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${inter.variable} ${jetbrainsMono.variable} ${ebGaramond.variable} light`}
    >
      <head>
        {/* Material Symbols — loaded async, won't block paint */}
        <link
          rel="preconnect"
          href="https://fonts.googleapis.com"
        />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin=""
        />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap"
        />
      </head>
      <body className="min-h-screen bg-background text-on-surface antialiased">
        <div className="architectural-grid" aria-hidden />
        <ThemeProvider
          attribute="class"
          defaultTheme="light"
          enableSystem={false}
          disableTransitionOnChange
        >
          <TailwindSafelist />
          {/* Wrapped in Suspense because NavigationProgress reads
              useSearchParams(), which would otherwise force the whole
              tree out of static optimization. */}
          <Suspense fallback={null}>
            <NavigationProgress />
          </Suspense>
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
