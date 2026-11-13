import { Skeleton } from "@/components/ui/skeleton";

export default function WorkspaceLoading() {
  return (
    <div className="px-4 py-6 sm:px-6 lg:px-10" aria-busy="true" aria-live="polite">
      <div className="flex items-center justify-between gap-4">
        <div className="space-y-2">
          <Skeleton className="h-2.5 w-24" />
          <Skeleton className="h-5 w-56" />
          <Skeleton className="h-3 w-80 max-w-full" />
        </div>
        <Skeleton className="h-8 w-24" />
      </div>
      <div className="mt-6 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-20 rounded-[var(--r-md)]" />
        ))}
      </div>
      <div className="mt-6 space-y-2">
        {Array.from({ length: 7 }).map((_, index) => (
          <Skeleton key={index} className="h-12 rounded-[var(--r-sm)]" />
        ))}
      </div>
      <span className="sr-only">Loading workspace</span>
    </div>
  );
}
