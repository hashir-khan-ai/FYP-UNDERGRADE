import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { DocumentsView } from "@/components/documents/documents-view";
import { getServerDocuments } from "@/lib/server/data";
import { getSessionUser } from "@/lib/server/session";

export const metadata: Metadata = { title: "Document catalog" };
export const dynamic = "force-dynamic";

export default async function DocumentsPage() {
  const user = await getSessionUser();
  if (!user) redirect("/login");

  const { documents, status } = await getServerDocuments();
  if (status === 401) redirect("/login");

  return <DocumentsView user={user} initialDocuments={documents} initialStatus={status} />;
}
