import type { NextConfig } from "next";

const backendOrigin = process.env.TRIPTAB_API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  agentRules: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendOrigin}/api/:path*` }];
  },
};

export default nextConfig;
