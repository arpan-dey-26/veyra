import type { NextConfig } from "next";

// On a hosting platform the API URL must be configured: never fall back to localhost there.
if (process.env.VERCEL && !process.env.VEYRA_API_INTERNAL_URL) {
  throw new Error("VEYRA_API_INTERNAL_URL must be set for a hosted (Vercel) build");
}
const apiInternalUrl = process.env.VEYRA_API_INTERNAL_URL ?? "http://localhost:8000";
const isDev = process.env.NODE_ENV !== "production";

// Phase 0 CSP. 'unsafe-inline' for scripts is required by Next without nonces;
// tightening to a nonce-based policy is tracked for Phase 11 (see phase-0 report, tech debt).
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self'${isDev ? " ws:" : ""}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  transpilePackages: ["@veyra/api-client", "@veyra/design-tokens"],
  async rewrites() {
    // Same-origin proxy: the browser only ever talks to the web origin, so auth
    // cookies (Phase 1) stay first-party and the API URL is never exposed.
    return [{ source: "/api/:path*", destination: `${apiInternalUrl}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(self), microphone=(), geolocation=()" },
          // HTTPS-only on hosted deployments (never on local http://localhost).
          ...(process.env.VERCEL
            ? [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" }]
            : []),
        ],
      },
    ];
  },
};

export default nextConfig;
