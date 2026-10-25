import { betterAuth } from "better-auth";
import { drizzleAdapter } from "better-auth/adapters/drizzle";
import { nextCookies } from "better-auth/next-js";
import { jwt } from "better-auth/plugins/jwt";

import { getDb } from "@/db";

const trustedOrigins = (process.env.BETTER_AUTH_TRUSTED_ORIGINS ?? "")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);

// The jwt() plugin stores its signing keys in the `jwks` table with the
// private key encrypted by BETTER_AUTH_SECRET. Rotating the secret without
// clearing that table causes:
//   "Failed to decrypt private key... either clean up your JWKS or disable
//    private key encryption."
// So: keep this secret stable per environment. If you must rotate it, delete
// the stale rows first (e.g. `DELETE FROM jwks;`) — keys regenerate on next
// use and only short-lived backend JWTs are invalidated (sessions stay valid).
const secret = process.env.BETTER_AUTH_SECRET;
if (!secret || secret.length < 32) {
  throw new Error(
    "BETTER_AUTH_SECRET must be set to at least 32 characters. " +
      "Generate one with: openssl rand -base64 32. " +
      "Keep it stable — rotating it orphans encrypted JWKS keys.",
  );
}

export const auth = betterAuth({
  appName: "Flow",
  secret,
  database: drizzleAdapter(getDb(), { provider: "sqlite" }),
  socialProviders: {
    github: {
      clientId: process.env.GITHUB_CLIENT_ID ?? "",
      clientSecret: process.env.GITHUB_CLIENT_SECRET ?? "",
    },
    google: {
      clientId: process.env.GOOGLE_CLIENT_ID ?? "",
      clientSecret: process.env.GOOGLE_CLIENT_SECRET ?? "",
    },
  },
  account: {
    // Same email on GitHub + Google links to a single user.
    accountLinking: {
      enabled: true,
      trustedProviders: ["github", "google"],
    },
  },
  session: {
    expiresIn: 60 * 60 * 24 * 7, // 7 days
    updateAge: 60 * 60 * 24, // refresh daily
    cookieCache: {
      enabled: true,
      maxAge: 60 * 5, // 5 minutes
    },
  },
  plugins: [
    // Issues short-lived stateless JWTs (GET /api/auth/token). The Python
    // backend verifies them as `Authorization: Bearer <jwt>` using the
    // shared BETTER_AUTH_SECRET — no session round-trip needed.
    jwt(),
    nextCookies(),
  ],
  trustedOrigins: trustedOrigins.length > 0 ? trustedOrigins : ["http://localhost:3000"],
  rateLimit: {
    enabled: true,
    window: 10,
    max: 100,
  },
});

export type Session = typeof auth.$Infer.Session;
export type User = typeof auth.$Infer.Session.user;
