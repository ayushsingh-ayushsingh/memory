import { defineConfig } from "drizzle-kit";

// SQLite database lives at the project root (chat_app/data/app.db) so all
// persisted state — auth + chat history — is shared in one place.
// Run from chat_app/client: `pnpm db:push` (dev) or generate+migrate (prod).
export default defineConfig({
  schema: "./db/schema.ts",
  out: "./drizzle",
  dialect: "sqlite",
  dbCredentials: {
    url: "../data/app.db",
  },
});
