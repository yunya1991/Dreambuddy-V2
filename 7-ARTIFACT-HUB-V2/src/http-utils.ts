import type { IncomingMessage, ServerResponse } from "node:http";

export async function readJson<T>(req: IncomingMessage): Promise<T> {
  const chunks: Buffer[] = [];
  for await (const c of req) chunks.push(Buffer.isBuffer(c) ? c : Buffer.from(c));
  const raw = Buffer.concat(chunks).toString("utf-8");
  return JSON.parse(raw) as T;
}

export function sendJson(res: ServerResponse, statusCode: number, body: unknown): void {
  res.statusCode = statusCode;
  res.setHeader("content-type", "application/json; charset=utf-8");
  res.end(JSON.stringify(body));
}

export function notFound(res: ServerResponse): void {
  sendJson(res, 404, { error: "not_found" });
}

export function methodNotAllowed(res: ServerResponse): void {
  sendJson(res, 405, { error: "method_not_allowed" });
}

