import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { LoginScreen } from "@/components/auth/login-screen";
import { getServerHealth } from "@/lib/server/data";
import { getSessionUser } from "@/lib/server/session";

export const metadata: Metadata = { title: "Sign in" };
export const dynamic = "force-dynamic";

export default async function LoginPage() {
  const user = await getSessionUser();
  if (user) redirect("/chat");

  const health = await getServerHealth();
  return <LoginScreen health={health} />;
}
