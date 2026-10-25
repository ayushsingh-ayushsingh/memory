import path from "node:path";
import Database from "better-sqlite3";
import { drizzle, type BetterSQLite3Database } from "drizzle-orm/better-sqlite3";

import * as schema from "./schema";

// The SQLite file lives at the project root: chat_app/data/app.db
// (process.cwd() is chat_app/client under Next.js).
const dbPath = process.env.DATABASE_URL ?? path.join(process.cwd(), "..", "data", "app.db");

const globalForDb = globalThis as unknown as {
  __sqlite?: Database.Database;
  __db?: BetterSQLite3Database<typeof schema>;
};

function getSqlite() {
  if (!globalForDb.__sqlite) {
    globalForDb.__sqlite = new Database(dbPath);
    globalForDb.__sqlite.pragma("journal_mode = WAL");
    globalForDb.__sqlite.pragma("foreign_keys = ON");
  }
  return globalForDb.__sqlite;
}

export function getDb() {
  if (!globalForDb.__db) {
    globalForDb.__db = drizzle(getSqlite(), { schema });
  }
  return globalForDb.__db;
}

export type Db = ReturnType<typeof getDb>;
export { dbPath };
