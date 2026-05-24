import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // @react-pdf/renderer uses Node internals and can't be bundled for client / RSC.
  // Same for neo4j-driver. Marking them as external server packages avoids the
  // "Component is not a constructor" runtime error on Next 15 + React 19.
  serverExternalPackages: ["@react-pdf/renderer", "neo4j-driver"],

  experimental: {
    // Allow the SSE Route Handler to keep long-lived connections during agent runs
    proxyTimeout: 60_000,
  },

  // Rewrites: keep the Python agent sidecar behind /agent/* so the UI doesn't
  // need to know its URL (set AGENT_SIDECAR_URL env var on deploy).
  async rewrites() {
    const sidecar = process.env.AGENT_SIDECAR_URL ?? "http://localhost:8000";
    return [
      { source: "/agent/:path*", destination: `${sidecar}/:path*` },
    ];
  },
};

export default nextConfig;
