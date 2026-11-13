import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ChatView } from "@/components/chat/chat-view";
import { buttonVariants } from "@/components/ui/button";
import { getServerConfig, getServerMessages } from "@/lib/server/data";
import { getSessionUser } from "@/lib/server/session";

export const metadata: Metadata = { title: "Conversation" };
export const dynamic = "force-dynamic";

const UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

export default async function ChatSessionPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = await params;
  if (!UUID.test(sessionId)) notFound();

  const user = await getSessionUser();
  if (!user) redirect("/login");

  const [messagesResult, config] = await Promise.all([
    getServerMessages(sessionId),
    getServerConfig(),
  ]);

  if (messagesResult.status === 401) redirect("/login");
  if (messagesResult.status === 404) notFound();

  if (messagesResult.status !== 200) {
    return (
      <div className="mx-auto flex min-h-[60dvh] max-w-md flex-col items-center justify-center px-4 text-center">
        <h1 className="text-base font-semibold text-ink">This conversation could not be loaded</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          The compliance API returned an error. Your session is still signed in; try reopening the
          conversation or start a new one.
        </p>
        <div className="mt-5 flex gap-2">
          <Link href="/chat" className={buttonVariants({ variant: "secondary", size: "sm" })}>
            Back to chat
          </Link>
          <Link href="/login" className={buttonVariants({ variant: "primary", size: "sm" })}>
            Sign in again
          </Link>
        </div>
      </div>
    );
  }

  return (
    <ChatView
      key={sessionId}
      sessionId={sessionId}
      user={user}
      initialMessages={messagesResult.messages}
      profile={config?.profile ?? "mock"}
    />
  );
}
