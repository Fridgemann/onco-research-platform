import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// connect-src needs ws:// in dev for Next.js hot-reload (HMR websocket)
const connectSrc = isDev
  ? `'self' ${apiUrl} ws://localhost:3000`
  : `'self' ${apiUrl}`;

const csp = [
  "default-src 'self'",
  // unsafe-inline: Next.js bootstrap scripts; unsafe-eval: React dev debugger (dev only)
  // production should replace both with nonces via Next.js middleware
  isDev
    ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
    : "script-src 'self' 'unsafe-inline'",
  // unsafe-inline kept for Next/dev inline styles; remove later if production build works without it
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  `connect-src ${connectSrc}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
