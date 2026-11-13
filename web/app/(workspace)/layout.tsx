import { redirect } from "next/navigation";

import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { getServerConfig, getServerHealth, getServerSessions } from "@/lib/server/data";
import { getSessionUser } from "@/lib/server/session";

export const dynamic = "force-dynamic";

export default async function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const user = await getSessionUser();
  if (!user) redirect("/login");

  const [sessions, config, health] = await Promise.all([
    getServerSessions(),
    getServerConfig(),
    getServerHealth(),
  ]);

  return (
    <WorkspaceShell user={user} initialSessions={sessions} config={config} health={health}>
      {children}
    </WorkspaceShell>
  );
}
