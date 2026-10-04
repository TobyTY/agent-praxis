// Entry point bundled to plugin/dist/session-end.mjs. Logic lives in handlers/session-end.ts.
import { runHook } from "./lib/hook.js";
import { handle } from "./handlers/session-end.js";

void runHook({ name: "session-end", budgetMs: 1200, handler: handle });
