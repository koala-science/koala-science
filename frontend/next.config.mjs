/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  experimental: {
    missingSuspenseWithCSRBailout: false,
  },
  // The page was published at /constitution before it was renamed; links to it
  // exist outside this repo.
  async redirects() {
    return [{ source: '/constitution', destination: '/quality-checks', permanent: true }];
  },
};

export default nextConfig;
