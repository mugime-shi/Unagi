/** @type {import('next').NextConfig} */
const nextConfig = {
  // API proxy rewrites (moved from vercel.json)
  async rewrites() {
    const apiDest =
      process.env.NEXT_PUBLIC_API_DEST ||
      "https://5ouka6u81a.execute-api.eu-north-1.amazonaws.com";
    return [
      {
        source: "/api/:path*",
        destination: `${apiDest}/api/:path*`,
      },
      {
        source: "/docs",
        destination: `${apiDest}/docs`,
      },
      {
        source: "/openapi.json",
        destination: `${apiDest}/openapi.json`,
      },
    ];
  },
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
