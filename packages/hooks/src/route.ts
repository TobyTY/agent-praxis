// Entry point bundled to plugin/dist/route.mjs. Logic lives in handlers/route.ts.
import { runHook } from "./lib/hook.js";
import { handle } from "./handlers/route.js";

void runHook({ name: "route", budgetMs: 180, handler: handle });
