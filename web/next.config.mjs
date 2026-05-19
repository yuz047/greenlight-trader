/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Allow the build to read the JSON snapshots from the sibling /data folder.
  // We just import them statically from lib/data.ts, so no special config needed.
};

export default nextConfig;
