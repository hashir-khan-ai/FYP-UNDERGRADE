import { NextResponse } from "next/server";

import {
  SESSION_COOKIE,
  SESSION_MAX_AGE_SECONDS,
} from "@/lib/auth";
import { backendBaseUrl } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface LoginBody {
  username?: unknown;
  password?: unknown;
}

function errorResponse(status: number, code: string, message: string) {
  return NextResponse.json(
    { error: { code, message, details: null } },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}

/**
 * Authentication BFF. The FastAPI bearer token is placed in an httpOnly,
 * SameSite=Lax cookie and never returned in the JSON body or a URL.
 */
export async function POST(request: Request) {
  let body: LoginBody;
  try {
    body = (await request.json()) as LoginBody;
  } catch {
    return errorResponse(400, "BAD_REQUEST", "Send a JSON username and password.");
  }

  const username = typeof body.username === "string" ? body.username.trim() : "";
  const password = typeof body.password === "string" ? body.password : "";

  if (username.length < 3 || username.length > 50) {
    return errorResponse(422, "VALIDATION_ERROR", "Enter a valid username.");
  }
  if (password.length < 6 || password.length > 200) {
    return errorResponse(422, "VALIDATION_ERROR", "Enter a valid password.");
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${backendBaseUrl()}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ username, password }),
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
    });
  } catch {
    return errorResponse(
      503,
      "BACKEND_UNREACHABLE",
      "The compliance API is not reachable. Start FastAPI on 127.0.0.1:8000 and try again.",
    );
  }

  if (!upstream.ok) {
    let code = "UNAUTHENTICATED";
    let message = "Invalid username or password.";
    try {
      const payload = (await upstream.json()) as {
        error?: { code?: string; message?: string };
      };
      code = payload.error?.code ?? code;
      message = payload.error?.message ?? message;
    } catch {
      // Keep the sanitized defaults.
    }
    return errorResponse(upstream.status, code, String(message).slice(0, 400));
  }

  let payload: {
    access_token?: unknown;
    user?: { id?: unknown; username?: unknown; full_name?: unknown; role?: unknown };
  };
  try {
    payload = (await upstream.json()) as typeof payload;
  } catch {
    return errorResponse(502, "BAD_UPSTREAM_RESPONSE", "The compliance API returned an invalid response.");
  }

  const token = typeof payload.access_token === "string" ? payload.access_token : "";
  const user = payload.user;
  if (
    !token ||
    !user ||
    typeof user.id !== "number" ||
    typeof user.username !== "string" ||
    typeof user.full_name !== "string" ||
    typeof user.role !== "string"
  ) {
    return errorResponse(502, "BAD_UPSTREAM_RESPONSE", "The compliance API returned an invalid session.");
  }

  // Guarantee a session exists so the workspace never opens empty, providing
  // a guaranteed initial session. Failures here do not block sign-in.
  let warning: string | undefined;
  const authHeaders = {
    Authorization: `Bearer ${token}`,
    Accept: "application/json",
  };
  try {
    const listed = await fetch(`${backendBaseUrl()}/api/v1/sessions`, {
      headers: authHeaders,
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
    });
    if (listed.ok) {
      const data = (await listed.json()) as { sessions?: unknown };
      const sessions = Array.isArray(data.sessions) ? data.sessions : [];
      if (sessions.length === 0) {
        const created = await fetch(`${backendBaseUrl()}/api/v1/sessions`, {
          method: "POST",
          headers: { ...authHeaders, "Content-Type": "application/json" },
          body: JSON.stringify({ title: "New Compliance Session" }),
          cache: "no-store",
          signal: AbortSignal.timeout(8000),
        });
        if (!created.ok) {
          warning = "Signed in, but the first session could not be created.";
        }
      }
    }
  } catch {
    warning = "Signed in, but sessions could not be loaded yet.";
  }

  const response = NextResponse.json(
    {
      user: {
        id: user.id,
        username: user.username,
        full_name: user.full_name,
        role: user.role,
      },
      ...(warning ? { warning } : {}),
    },
    { headers: { "Cache-Control": "no-store" } },
  );

  response.cookies.set({
    name: SESSION_COOKIE,
    value: token,
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.COOKIE_SECURE === "true",
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS,
  });

  return response;
}
