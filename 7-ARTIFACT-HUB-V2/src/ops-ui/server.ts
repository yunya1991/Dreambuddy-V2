import express from "express";
import { buildOpsRouter } from "./routes/index.js";

export function startOpsUiServer(opts?: { port?: number; host?: string }): void {
  const app = express();
  app.use(express.json({ limit: "2mb" }));
  app.use(buildOpsRouter());

  const port = opts?.port ?? Number(process.env.OPS_UI_PORT || 3457);
  const host = opts?.host ?? String(process.env.OPS_UI_HOST || "127.0.0.1");

  app.listen(port, host);
}

startOpsUiServer();
