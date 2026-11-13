import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { AuditView } from "@/components/audit/audit-view";
import { RestrictedPanel } from "@/components/workspace/restricted-panel";
import { canViewAudit } from "@/lib/auth";
import { getServerAuditLogs } from "@/lib/server/data";
import { getSessionUser } from "@/lib/server/session";

export const metadata: Metadata = { title: "Audit & RBAC" };
export const dynamic = "force-dynamic";

export default async function AuditPage() {
  const user = await getSessionUser();
  if (!user) redirect("/login");

  if (!canViewAudit(user.role)) {
    return (
      <RestrictedPanel
        title="Audit summaries are restricted"
        description="Only the auditor role may read sanitised audit summaries. Chat and document retrieval remain available for your role."
        requiredRole="Auditor"
      />
    );
  }

  const { logs, status } = await getServerAuditLogs(50);
  if (status === 401) redirect("/login");
  if (status === 403) {
    return (
      <RestrictedPanel
        title="Audit summaries are restricted"
        description="The API rejected this request for your current role. No audit data was returned."
        requiredRole="Auditor"
      />
    );
  }

  return <AuditView user={user} initialLogs={logs} initialStatus={status} />;
}
