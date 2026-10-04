// Entry point bundled to plugin/dist/capture.mjs. Logic lives in handlers/capture.ts.
import { runHook } from "./lib/hook.js";
import { handle } from "./handlers/capture.js";

void runHook({ name: "capture", budgetMs: 2000, handler: handle });
