/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  experimental: {
    missingSuspenseWithCSRBailout: false,
  },
  async redirects() {
    return [
      { source: '/eval', destination: '/metrics', permanent: true },
    ];
  },
  async rewrites() {
    // Dev-only: proxy /eval/api/* to local Python eval service on :18501
    // In production, Caddy handles this routing.
    if (process.env.NODE_ENV === 'development') {
      return [
        {
          source: '/eval/api/:path*',
          destination: 'http://localhost:18501/api/:path*',
        },
      ];
    }
    return [];
  },
};

export default nextConfig;
