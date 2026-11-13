"use client";

import * as React from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Eye,
  EyeOff,
  FileCheck2,
  LoaderCircle,
  LockKeyhole,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { toast } from "sonner";

import { Logo } from "@/components/brand/logo";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { ApiError, api } from "@/lib/api-client";
import { PERSONAS } from "@/lib/constants";
import { formatNumber } from "@/lib/format";
import type { HealthResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

const TrustMap = dynamic(
  () => import("@/components/visual/trust-map").then((module) => module.TrustMap),
  {
    ssr: false,
    loading: () => (
      <div className="skeleton h-48 w-full rounded-[var(--r-md)]" aria-hidden="true" />
    ),
  },
);

function Feature({
  icon: Icon,
  title,
  description,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
}) {
  return (
    <div className="flex gap-3">
      <span className="mt-0.5 inline-flex size-8 shrink-0 items-center justify-center rounded-[var(--r-sm)] border border-line bg-surface-2 text-accent">
        <Icon className="size-4" aria-hidden="true" />
      </span>
      <div>
        <p className="text-xs font-semibold text-ink">{title}</p>
        <p className="mt-0.5 text-[0.6875rem] leading-relaxed text-muted">{description}</p>
      </div>
    </div>
  );
}

export function LoginScreen({ health }: { health: HealthResponse | null }) {
  const router = useRouter();
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [showPassword, setShowPassword] = React.useState(false);
  const [selectedPersona, setSelectedPersona] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);
  const passwordRef = React.useRef<HTMLInputElement>(null);
  const usernameRef = React.useRef<HTMLInputElement>(null);

  const roleHint = PERSONAS.find((persona) => persona.username === username)?.role;
  const healthy = health?.status === "ok" || health?.status === "healthy";

  function fillPersona(persona: (typeof PERSONAS)[number]) {
    setUsername(persona.username);
    setSelectedPersona(persona.username);
    setError(null);
    passwordRef.current?.focus();
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    if (username.trim().length < 3) {
      setError("Enter your synthetic username.");
      usernameRef.current?.focus();
      return;
    }
    if (password.length < 6) {
      setError("Enter your demo password.");
      passwordRef.current?.focus();
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const result = await api.login(username.trim(), password);
      if (result.warning) {
        toast.warning("Signed in with a warning", { description: result.warning, duration: 6000 });
      }
      router.replace("/chat");
      router.refresh();
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message);
      } else {
        setError("Sign-in could not be completed. Check that the compliance API is running.");
      }
      setSubmitting(false);
    }
  }

  return (
    <div className="relative min-h-dvh overflow-hidden">
      <div className="app-atmosphere" aria-hidden="true" />
      <div className="mx-auto grid min-h-dvh w-full max-w-6xl items-center gap-8 px-4 py-8 sm:px-6 lg:grid-cols-[1.05fr_0.95fr] lg:gap-12 lg:py-10">
        <section className="order-2 lg:order-1">
          <Logo showWordmark />
          <Badge tone="accent" className="mt-6">
            <Sparkles /> Local-first regulatory intelligence
          </Badge>
          <h1 className="mt-3 max-w-xl text-[2rem] font-semibold leading-[1.08] tracking-[-0.035em] text-ink sm:text-[2.5rem]">
            Regulatory answers you can defend.
          </h1>
          <p className="mt-3 max-w-lg text-sm leading-relaxed text-muted">
            A compliance workspace that retrieves only what your role may read, verifies every
            citation, and refuses when the corpus does not support an answer.
          </p>

          <div className="mt-6 rounded-[var(--r-lg)] border border-line bg-[rgba(3,6,10,0.3)] p-3.5">
            <TrustMap />
            <p className="mt-1 text-center text-[0.625rem] text-faint">
              Corpus → role gate → relevance grader → verified answer or safe refusal
            </p>
          </div>

          <div className="mt-6 grid gap-3 sm:grid-cols-3">
            <Feature
              icon={ShieldCheck}
              title="Role gate first"
              description="Qdrant and BM25 filters run before any passage reaches the model."
            />
            <Feature
              icon={FileCheck2}
              title="Verified citations"
              description="Unsupported or unpermitted references are dropped, not shown."
            />
            <Feature
              icon={LockKeyhole}
              title="No token exposure"
              description="The bearer token stays in an httpOnly cookie behind a same-origin BFF."
            />
          </div>
        </section>

        <section className="order-1 lg:order-2" aria-labelledby="sign-in-heading">
          <div className="rounded-[var(--r-xl)] border border-line-strong bg-canvas-raised/92 p-5 shadow-[var(--elev-lg)] sm:p-6">
            <div className="flex items-center justify-between gap-2">
              <div>
                <h2 id="sign-in-heading" className="text-base font-semibold tracking-[-0.02em] text-ink">
                  Sign in to the workspace
                </h2>
                <p className="mt-1 text-[0.6875rem] leading-relaxed text-muted">
                  Synthetic personas only. No real customer or bank data is present.
                </p>
              </div>
              <Badge tone={healthy ? "success" : "warning"}>
                <span
                  className={cn("size-1.5 rounded-full", healthy ? "bg-success" : "bg-warning")}
                  aria-hidden="true"
                />
                {healthy ? "API online" : "API offline"}
              </Badge>
            </div>

            <div className="mt-5">
              <p className="mb-2 text-[0.625rem] font-semibold uppercase tracking-[0.09em] text-faint">
                Quick-fill a persona
              </p>
              <div className="grid grid-cols-3 gap-1.5">
                {PERSONAS.map((persona) => {
                  const selected = selectedPersona === persona.username;
                  return (
                    <button
                      key={persona.role}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => fillPersona(persona)}
                      className={cn(
                        "flex flex-col items-center gap-1.5 rounded-[var(--r-md)] border px-2 py-2.5 text-center transition-[border-color,background-color,transform] duration-[var(--duration-fast)] hover:-translate-y-0.5",
                        selected
                          ? "border-line-accent bg-accent-soft"
                          : "border-line bg-surface-2/50 hover:border-line-strong",
                      )}
                      title={persona.scope}
                    >
                      <Avatar name={persona.name} size="sm" />
                      <span className="text-[0.6875rem] font-medium text-ink">{persona.role}</span>
                      <span className="text-[0.625rem] text-faint">{persona.username}</span>
                    </button>
                  );
                })}
              </div>
              <p className="mt-2 text-[0.625rem] leading-relaxed text-faint">
                Quick-fill sets the username only. Enter the synthetic demo password from the project
                runbook — it is deliberately not embedded in client code.
              </p>
            </div>

            <form onSubmit={submit} className="mt-5 space-y-3.5" noValidate>
              <div>
                <Label htmlFor="username">Username</Label>
                <Input
                  ref={usernameRef}
                  id="username"
                  name="username"
                  autoComplete="username"
                  value={username}
                  onChange={(event) => {
                    setUsername(event.target.value);
                    setSelectedPersona(null);
                    setError(null);
                  }}
                  placeholder="analyst_user"
                  className="mt-1.5"
                  aria-describedby={roleHint ? "role-hint" : undefined}
                  disabled={submitting}
                  required
                />
                {roleHint ? (
                  <p id="role-hint" className="mt-1 text-[0.625rem] text-faint">
                    Persona recognised: {roleHint} tier
                  </p>
                ) : null}
              </div>

              <div>
                <div className="flex items-center justify-between">
                  <Label htmlFor="password">Password</Label>
                  <button
                    type="button"
                    onClick={() => setShowPassword((current) => !current)}
                    className="inline-flex items-center gap-1 text-[0.625rem] text-faint transition-colors hover:text-ink"
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    aria-pressed={showPassword}
                  >
                    {showPassword ? <EyeOff className="size-3" /> : <Eye className="size-3" />}
                    {showPassword ? "Hide" : "Show"}
                  </button>
                </div>
                <Input
                  ref={passwordRef}
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => {
                    setPassword(event.target.value);
                    setError(null);
                  }}
                  placeholder="Synthetic demo password"
                  className="mt-1.5"
                  disabled={submitting}
                  required
                />
              </div>

              {error ? (
                <div
                  role="alert"
                  className="flex items-start gap-2 rounded-[var(--r-sm)] border border-[rgba(255,133,133,0.28)] bg-danger-soft px-3 py-2.5 text-[0.6875rem] leading-relaxed text-danger"
                >
                  <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                  <span>{error}</span>
                </div>
              ) : null}

              <Button type="submit" variant="primary" size="lg" className="w-full" disabled={submitting}>
                {submitting ? (
                  <>
                    <LoaderCircle className="animate-spin" /> Signing in…
                  </>
                ) : (
                  <>
                    Enter workspace <ArrowRight />
                  </>
                )}
              </Button>
            </form>

            <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3 text-[0.625rem] text-faint">
              <span className="inline-flex items-center gap-1">
                <ShieldCheck className="size-3" aria-hidden="true" />
                Server-side RBAC
              </span>
              <span>Profile: {health?.llm.profile ?? "mock"}</span>
              <span>
                Indexed chunks: {formatNumber(health?.vector_store.total_vectors ?? 0)}
              </span>
            </div>
          </div>

          <p className="mt-3 px-1 text-center text-[0.625rem] leading-relaxed text-faint lg:text-left">
            By signing in you enter a local demonstration environment. The session cookie is
            httpOnly, SameSite=Lax, and never written to a URL, log or browser-accessible store.
          </p>
        </section>
      </div>
    </div>
  );
}
