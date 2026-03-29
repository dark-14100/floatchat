"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import AuthCard from "@/components/auth/AuthCard";
import PasswordInput from "@/components/auth/PasswordInput";
import PasswordStrength from "@/components/auth/PasswordStrength";
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
    return payload.detail ?? payload.message ?? "Sign up failed";
  } catch {
    return "Sign up failed";
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

export default function SignupPage() {
  const router = useRouter();
  const setAuth = useAuthStore((state) => state.setAuth);

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [migrationNotice, setMigrationNotice] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setMigrationNotice(null);
    setIsSubmitting(true);

    try {
      const response = await fetch(`${API_BASE}/api/v1/auth/signup`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-User-ID": getLegacyUserId(),
        },
        body: JSON.stringify({ name, email, password }),
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
        setTimeout(() => router.push("/chat"), 1200);
        return;
      }

      router.push("/chat");
    } catch {
      setError("Unable to create your account right now. Please try again.");
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

      <form onSubmit={onSubmit} className="space-y-4">
        <div className="space-y-2">
          <label htmlFor="signup-name" className="text-sm font-medium text-text-primary">
            Name
          </label>
          <Input
            id="signup-name"
            type="text"
            autoComplete="name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            disabled={isSubmitting}
            required
          />
        </div>

        <div className="space-y-2">
          <label htmlFor="signup-email" className="text-sm font-medium text-text-primary">
            Email
          </label>
          <Input
            id="signup-email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={isSubmitting}
            required
          />
        </div>

        <PasswordInput
          id="signup-password"
          label="Password"
          autoComplete="new-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={isSubmitting}
          required
        />

        <PasswordStrength password={password} />

        {error ? <p className="text-sm text-danger">{error}</p> : null}

        <Button type="submit" className="w-full" disabled={isSubmitting}>
          {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Create account
        </Button>
      </form>

      <div className="mt-5 text-center text-sm text-text-secondary">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-text-primary hover:underline">
          Sign in
        </Link>
      </div>
    </AuthCard>
  );
}
