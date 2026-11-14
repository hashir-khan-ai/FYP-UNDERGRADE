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
  Moon,
  ShieldCheck,
  Sparkles,
  Sun,
  TriangleAlert,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { toast } from "sonner";

import { Logo } from "@/components/brand/logo";
import { useTheme } from "@/components/providers/theme-provider";
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
      <span className="mt-0.5 inline-flex size-9 shrink-0 items-center justify-center rounded-[var(--r-md)] bg-surface text-accent-link shadow-[var(--elev-1)]">
        <Icon className="size-4" aria-hidden="true" />
      </span>
      <div>
        <p className="text-xs font-semibold text-ink">{title}</p>
        <p className="mt-0.5 text-xs leading-relaxed text-muted">{description}</p>
      </div>
    </div>
  );
}

export function LoginScreen({ health }: { health: HealthResponse | null }) {
  const router = useRouter();
  const { theme, toggleTheme } = useTheme();
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [usernameTouched, setUsernameTouched] = React.useState(false);
  const [passwordTouched, setPasswordTouched] = React.useState(false);
  const [showPassword, setShowPassword] = React.useState(false);
  const [selectedPersona, setSelectedPersona] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);
  const passwordRef = React.useRef<HTMLInputElement>(null);
  const usernameRef = React.useRef<HTMLInputElement>(null);

  const roleHint = PERSONAS.find((persona) => persona.username === username)?.role;
  const healthy = health?.status === "ok" || health?.status === "healthy";

  const usernameError =
    usernameTouched && username.trim().length > 0 && username.trim().length < 3
      ? "Username must be at least 3 characters."
      : null;

  const passwordError =
    passwordTouched && password.length > 0 && password.length < 6
      ? "Password must be at least 6 characters."
      : null;

  function fillPersona(persona: (typeof PERSONAS)[number]) {
    setUsername(persona.username);
    setSelectedPersona(persona.username);
    setUsernameTouched(true);
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
    <main className="relative min-h-dvh overflow-x-clip">
      <div className="app-atmosphere" aria-hidden="true" />
      <div className="mx-auto grid min-h-dvh w-full max-w-6xl items-center gap-8 px-4 py-8 sm:px-6 lg:grid-cols-[1.05fr_0.95fr] lg:gap-12 lg:py-10">
        <section className="order-2 space-y-6 lg:order-1">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Logo showWordmark className="hidden lg:inline-flex" />
            <div className="flex items-center gap-2">
              <Badge tone="accent">
                <Sparkles /> Local-first intelligence
              </Badge>
              <Button
                variant="secondary"
                size="icon-sm"
                onClick={toggleTheme}
                aria-label={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
                aria-pressed={theme === "light"}
                title={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
                className="hidden lg:inline-flex"
              >
                {theme === "light" ? <Moon className="size-4" /> : <Sun className="size-4" />}
              </Button>
            </div>
          </div>
          <div>
            <h1 className="max-w-xl font-display text-[clamp(2rem,3.6vw,2.75rem)] font-semibold leading-[1.08] tracking-[-0.025em] text-ink">
              Regulatory answers you can defend.
            </h1>
            <p className="mt-3 max-w-lg text-sm leading-relaxed text-muted sm:text-base">
              A compliance workspace that retrieves only what your role may read, verifies every
              citation, and refuses when the corpus does not support an answer.
            </p>
          </div>

          <TrustMap />

          <div className="grid gap-4 sm:grid-cols-3">
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
          <div className="mb-5 flex items-center justify-between gap-3 lg:hidden">
            <Logo showWordmark />
            <Button
              variant="secondary"
              size="icon-sm"
              onClick={toggleTheme}
              aria-label={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
              aria-pressed={theme === "light"}
            >
              {theme === "light" ? <Moon className="size-4" /> : <Sun className="size-4" />}
            </Button>
          </div>
          <div className="rounded-[var(--r-xl)] bg-surface p-6 shadow-[var(--elev-3)] sm:p-7">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 id="sign-in-heading" className="font-display text-xl font-semibold tracking-[-0.02em] text-ink">
                  Sign in to the workspace
                </h2>
                <p className="mt-1 text-xs leading-relaxed text-muted">
                  Synthetic personas only. No real customer or bank data is present.
                </p>
              </div>
              <Badge tone={healthy ? "success" : "warning"}>
                <span
                  className={cn("size-2 rounded-full", healthy ? "bg-success" : "bg-warning")}
                  aria-hidden="true"
                />
                {healthy ? "API online" : "API offline"}
              </Badge>
            </div>

            <div className="mt-5">
              <p className="mb-2.5 font-mono text-xs font-semibold uppercase tracking-[0.08em] text-faint">
                Quick-fill a persona
              </p>
              <div className="grid grid-cols-3 gap-2.5">
                {PERSONAS.map((persona) => {
                  const selected = selectedPersona === persona.username;
                  return (
                    <button
                      key={persona.role}
                      type="button"
                      aria-pressed={selected}
                      onClick={() => fillPersona(persona)}
                      className={cn(
                        "flex min-h-[68px] flex-col items-center gap-1.5 rounded-[var(--r-md)] px-2.5 py-3 text-center transition-[background-color,box-shadow,transform] duration-[var(--duration-fast)] hover:-translate-y-0.5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                        selected
                          ? "bg-accent-soft ring-1 ring-inset ring-line-accent shadow-[var(--elev-1)]"
                          : "bg-inset shadow-[var(--inner-inset)] hover:bg-surface-2",
                      )}
                      title={persona.scope}
                    >
                      <Avatar name={persona.name} size="sm" />
                      <span className="text-xs font-semibold text-ink capitalize">{persona.role}</span>
                      <span className="text-xs text-faint">{persona.username}</span>
                    </button>
                  );
                })}
              </div>
              <p className="mt-2.5 text-xs leading-relaxed text-faint">
                Quick-fill sets the username only. Enter the synthetic demo password from the project
                runbook — it is deliberately not embedded in client code.
              </p>
            </div>

            <form onSubmit={submit} className="mt-5 space-y-4" noValidate>
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
                  onBlur={() => setUsernameTouched(true)}
                  placeholder="analyst_user"
                  className={cn("mt-1.5 min-h-[44px]", usernameError && "border-danger focus:border-danger")}
                  aria-invalid={Boolean(usernameError)}
                  aria-describedby={
                    usernameError ? "username-error" : roleHint ? "role-hint" : undefined
                  }
                  disabled={submitting}
                  required
                />
                {usernameError ? (
                  <p id="username-error" className="mt-1 text-xs font-medium text-danger">
                    {usernameError}
                  </p>
                ) : roleHint ? (
                  <p id="role-hint" className="mt-1 text-xs text-faint">
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
                    className="inline-flex min-h-[44px] items-center gap-1.5 px-2 text-xs text-faint transition-colors hover:text-ink"
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    aria-pressed={showPassword}
                  >
                    {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
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
                  onBlur={() => setPasswordTouched(true)}
                  placeholder="Synthetic demo password"
                  className={cn("mt-1.5 min-h-[44px]", passwordError && "border-danger focus:border-danger")}
                  aria-invalid={Boolean(passwordError)}
                  aria-describedby={passwordError ? "password-error" : undefined}
                  disabled={submitting}
                  required
                />
                {passwordError ? (
                  <p id="password-error" className="mt-1 text-xs font-medium text-danger">
                    {passwordError}
                  </p>
                ) : null}
              </div>

              {error ? (
                <div
                  role="alert"
                  className="flex items-start gap-2 rounded-[var(--r-sm)] border border-danger/35 bg-danger-soft px-3 py-2.5 text-xs leading-relaxed text-danger"
                >
                  <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
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

            <div className="mt-5 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3.5 text-xs text-faint">
              <span className="inline-flex items-center gap-1.5">
                <ShieldCheck className="size-4" aria-hidden="true" />
                Server-side RBAC
              </span>
              <span className="font-mono">Profile: {health?.llm.profile ?? "mock"}</span>
              <span className="tabular font-mono">
                Indexed chunks: {formatNumber(health?.vector_store.total_vectors ?? 0)}
              </span>
            </div>
          </div>

          <p className="mt-3 px-1 text-center text-xs leading-relaxed text-faint lg:text-left">
            By signing in you enter a local demonstration environment. The session cookie is
            httpOnly, SameSite=Lax, and never written to a URL, log or browser-accessible store.
          </p>
        </section>
      </div>
    </main>
  );
}
