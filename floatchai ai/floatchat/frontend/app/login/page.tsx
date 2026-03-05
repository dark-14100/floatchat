"use client";

import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import AuthCard from "@/components/auth/AuthCard";
import PasswordInput from "@/components/auth/PasswordInput";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuthStore } from "@/store/authStore";
import type { AuthResponse, User } from "@/types/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function getLegacyUserId(): string {
  if (typeof window === "undefined") return "";
  const existing = localStorage.getItem("floatchat_user_id");
  if (existing) return existing;
  const generated = crypto.randomUUID();
  localStorage.setItem("floatchat_user_id", generated);
  return generated;
}

async function parseErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string; message?: string };
    return payload.detail ?? payload.message ?? "Sign in failed";
  } catch {
    return "Sign in failed";
  }
}

function toUser(payload: AuthResponse): User {
  return {
    user_id: payload.user_id,
    name: payload.name,
    email: payload.email,
    role: payload.role,
  };
}

function LoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const setAuth = useAuthStore((state) => state.setAuth);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [migrationNotice, setMigrationNotice] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const redirectTo = useMemo(() => searchParams.get("redirect") ?? "/chat", [searchParams]);

  useEffect(() => {
    if (searchParams.get("message") === "password-updated") {
      setSuccess("Password updated. Please sign in.");
    }
  }, [searchParams]);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSuccess(null);
    setMigrationNotice(null);
    setIsSubmitting(true);

    try {
      const response = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-User-ID": getLegacyUserId(),
        },
        body: JSON.stringify({ email, password }),
      });

      if (!response.ok) {
        const message = await parseErrorMessage(response);
        setError(message);
        return;
      }

      const payload = (await response.json()) as AuthResponse;
      setAuth(toUser(payload), payload.access_token);
      localStorage.removeItem("floatchat_user_id");

      if (payload.migrated_sessions_count > 0) {
        setMigrationNotice("Your previous conversations have been linked to your account.");
        setTimeout(() => router.push(redirectTo), 1200);
        return;
      }

      router.push(redirectTo);
    } catch {
      setError("Unable to sign in right now. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthCard>
      {migrationNotice ? (
        <div className="mb-4 rounded-md border border-border-subtle bg-bg-surface px-3 py-2 text-sm text-text-primary">
          {migrationNotice}
        </div>
      ) : null}

      {success ? (
        <div className="mb-4 rounded-md border border-seafoam/40 bg-seafoam/10 px-3 py-2 text-sm text-text-primary">
          {success}
        </div>
      ) : null}

      <form onSubmit={onSubmit} className="space-y-4">
        <div className="space-y-2">
          <label htmlFor="login-email" className="text-sm font-medium text-text-primary">
            Email
          </label>
          <Input
            id="login-email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={isSubmitting}
            required
          />
        </div>

        <PasswordInput
          id="login-password"
          label="Password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={isSubmitting}
          required
        />

        {error ? <p className="text-sm text-danger">{error}</p> : null}

        <Button type="submit" className="w-full" disabled={isSubmitting}>
          {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Sign in
        </Button>
      </form>

      <div className="mt-4 text-right">
        <Link
          href="/forgot-password"
          className="text-sm text-text-secondary transition-colors hover:text-text-primary"
        >
          Forgot password?
        </Link>
      </div>

      <div className="my-5 flex items-center gap-3 text-xs text-text-muted">
        <div className="h-px flex-1 bg-border" />
        <span>or</span>
        <div className="h-px flex-1 bg-border" />
      </div>

      <Button asChild variant="outline" className="w-full">
        <Link href="/signup">Create an account</Link>
      </Button>
    </AuthCard>
  );
}

function LoginFallback() {
  return (
    <AuthCard>
      <div className="flex items-center justify-center py-4 text-sm text-text-secondary">Loading…</div>
    </AuthCard>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<LoginFallback />}>
      <LoginContent />
    </Suspense>
  );
}
