// Entry point bundled to plugin/dist/session-start.mjs. Logic lives in handlers/session-start.ts.
import { runHook } from "./lib/hook.js";
import { handle } from "./handlers/session-start.js";

void runHook({ name: "session-start", budgetMs: 400, handler: handle });
