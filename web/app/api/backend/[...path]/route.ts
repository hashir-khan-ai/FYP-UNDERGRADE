import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/auth";
import { backendBaseUrl } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface RouteRule {
  pattern: RegExp;
  methods: ReadonlySet<string>;
  public?: boolean;
}

/**
 * Explicit allowlist. The BFF is not an open proxy: unknown paths, methods and
 * malformed session identifiers are rejected before any network call.
 */
const RULES: RouteRule[] = [
  { pattern: /^health$/, methods: new Set(["GET"]), public: true },
  { pattern: /^auth\/users$/, methods: new Set(["GET"]), public: true },
  { pattern: /^auth\/me$/, methods: new Set(["GET"]) },
  { pattern: /^sessions$/, methods: new Set(["GET", "POST"]) },
  { pattern: /^sessions\/[0-9a-fA-F-]{36}$/, methods: new Set(["DELETE", "PATCH"]) },
  { pattern: /^sessions\/[0-9a-fA-F-]{36}\/messages$/, methods: new Set(["GET"]) },
  { pattern: /^sessions\/[0-9a-fA-F-]{36}\/new-run$/, methods: new Set(["POST"]) },
  { pattern: /^chat\/query$/, methods: new Set(["POST"]) },
  { pattern: /^audit\/logs$/, methods: new Set(["GET"]) },
  { pattern: /^admin\/config$/, methods: new Set(["GET"]) },
  { pattern: /^admin\/health$/, methods: new Set(["GET"]) },
  { pattern: /^admin\/metrics$/, methods: new Set(["GET"]) },
  { pattern: /^documents$/, methods: new Set(["GET"]) },
  { pattern: /^documents\/[^/]+$/, methods: new Set(["GET", "PATCH", "DELETE"]) },
  { pattern: /^documents\/upload$/, methods: new Set(["POST"]) },
  { pattern: /^views$/, methods: new Set(["GET", "POST"]) },
  { pattern: /^views\/[^/]+$/, methods: new Set(["DELETE"]) },
];

function envelope(status: number, code: string, message: string) {
  return Response.json(
    { error: { code, message, details: null } },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}

function resolveRule(path: string): RouteRule | null {
  return RULES.find((rule) => rule.pattern.test(path)) ?? null;
}

async function proxy(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path: segments } = await context.params;
  const path = Array.isArray(segments) ? segments.join("/") : "";

  if (!path || path.includes("..") || path.includes("\\")) {
    return envelope(404, "NOT_FOUND", "Unknown API route.");
  }

  const rule = resolveRule(path);
  if (!rule) {
    return envelope(404, "NOT_FOUND", "Unknown API route.");
  }
  if (!rule.methods.has(request.method)) {
    return envelope(405, "METHOD_NOT_ALLOWED", "This action is not supported.");
  }

  const store = await cookies();
  const token = store.get(SESSION_COOKIE)?.value ?? "";
  if (!rule.public && !token) {
    return envelope(401, "UNAUTHENTICATED", "Sign in again to continue.");
  }

  const search = new URL(request.url).search;
  const target = `${backendBaseUrl()}/api/v1/${path}${search}`;

  let body: ArrayBuffer | undefined;
  if (request.method !== "GET" && request.method !== "HEAD") {
    body = await request.arrayBuffer();
  }

  const headers = new Headers({ Accept: "application/json" });
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const contentType = request.headers.get("content-type");
  if (contentType && body) headers.set("Content-Type", contentType);

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(path === "documents/upload" ? 120000 : 60000),
    });
  } catch {
    return envelope(
      503,
      "BACKEND_UNREACHABLE",
      "The compliance API is not reachable. Start FastAPI on 127.0.0.1:8000 and try again.",
    );
  }

  const buffer = await upstream.arrayBuffer();
  const responseHeaders = new Headers({
    "Content-Type": upstream.headers.get("content-type") ?? "application/json",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  const retryAfter = upstream.headers.get("retry-after");
  if (retryAfter) responseHeaders.set("Retry-After", retryAfter);
  const requestId = upstream.headers.get("x-request-id");
  if (requestId) responseHeaders.set("X-Request-ID", requestId);

  const response = new NextResponse(buffer, {
    status: upstream.status,
    headers: responseHeaders,
  });
  if (upstream.status === 401) {
    response.cookies.set({
      name: SESSION_COOKIE,
      value: "",
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.COOKIE_SECURE === "true",
      path: "/",
      maxAge: 0,
    });
  }
  return response;
}

export async function GET(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  return proxy(request, context);
}

export async function POST(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  return proxy(request, context);
}

export async function PATCH(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  return proxy(request, context);
}

export async function DELETE(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  return proxy(request, context);
}
