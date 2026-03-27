import { withSentryConfig } from "@sentry/nextjs";

/** @type {import('next').NextConfig} */
const nextConfig = {};

const sentryWebpackPluginOptions = {
	// Prevent noisy build logs while still enabling sourcemaps in configured environments.
	silent: true,
	// Keeps local builds working when Sentry auth/org/project are not configured.
	dryRun: !process.env.SENTRY_AUTH_TOKEN,
};

export default withSentryConfig(nextConfig, sentryWebpackPluginOptions);
