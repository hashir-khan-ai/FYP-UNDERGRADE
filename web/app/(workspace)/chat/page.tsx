import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { ChatLanding } from "@/components/chat/chat-landing";
import { getServerSessions } from "@/lib/server/data";
import { getSessionUser } from "@/lib/server/session";

export const metadata: Metadata = { title: "Compliance chat" };
export const dynamic = "force-dynamic";

export default async function ChatIndexPage() {
  const user = await getSessionUser();
  if (!user) redirect("/login");

  const sessions = await getServerSessions();
  if (sessions.length > 0) redirect(`/chat/${sessions[0].id}`);

  return <ChatLanding name={user.full_name} />;
}
