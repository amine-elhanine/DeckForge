/** @type {import('next').NextConfig} */

// A fully static export: the desktop build ships these files inside the Python
// bundle and FastAPI serves them, so there is no Node process at runtime.
//
// No dev-server rewrite is used to reach the API. Next's proxy buffers
// responses, which silently breaks the Server-Sent Events stream that drives
// live progress; the browser talks to the backend origin directly instead
// (see lib/api.ts and .env.development).
const nextConfig = {
  output: "export",
  reactStrictMode: true,
  trailingSlash: false,
  images: { unoptimized: true },
};

export default nextConfig;
