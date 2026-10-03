import type { NextConfig } from "next";

const configuredOrigin = process.env.TRIPTAB_API_ORIGIN;
if (process.env.NODE_ENV === "production" && !configuredOrigin) {
  throw new Error("Set the server-only TRIPTAB_API_ORIGIN before production build/start.");
}
const backendOrigin = configuredOrigin ?? "http://127.0.0.1:8000";
let parsedOrigin: URL;
try {
  parsedOrigin = new URL(backendOrigin);
} catch {
  throw new Error("TRIPTAB_API_ORIGIN must be a valid HTTP(S) origin.");
}
if (!["http:", "https:"].includes(parsedOrigin.protocol) || parsedOrigin.username || parsedOrigin.password || parsedOrigin.origin !== backendOrigin) {
  throw new Error("TRIPTAB_API_ORIGIN must be an HTTP(S) origin without credentials or a path.");
}

const nextConfig: NextConfig = {
  agentRules: false,
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "no-referrer" },
      { key: "X-Frame-Options", value: "DENY" },
      // Targeted CSP preserves Next.js hydration without adding inline-script exceptions.
      { key: "Content-Security-Policy", value: "frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'" },
    ] }];
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendOrigin}/api/:path*` }];
  },
};

export default nextConfig;
