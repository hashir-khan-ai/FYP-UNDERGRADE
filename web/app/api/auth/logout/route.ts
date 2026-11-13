import { NextResponse } from "next/server";
import { cookies } from "next/headers";

import { SESSION_COOKIE } from "@/lib/auth";
import { backendBaseUrl } from "@/lib/server/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** Revoke the upstream token and clear the httpOnly cookie. */
export async function POST() {
  const store = await cookies();
  const token = store.get(SESSION_COOKIE)?.value;

  if (token) {
    try {
      await fetch(`${backendBaseUrl()}/api/v1/auth/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
        cache: "no-store",
        signal: AbortSignal.timeout(8000),
      });
    } catch {
      // Local sign-out must still succeed if the API is offline.
    }
  }

  const response = NextResponse.json(
    { status: "ok" },
    { headers: { "Cache-Control": "no-store" } },
  );
  response.cookies.set({
    name: SESSION_COOKIE,
    value: "",
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.COOKIE_SECURE === "true",
    path: "/",
    maxAge: 0,
  });
  return response;
}
