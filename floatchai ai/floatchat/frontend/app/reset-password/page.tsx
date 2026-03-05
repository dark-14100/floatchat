"use client";

import { FormEvent, Suspense, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import AuthCard from "@/components/auth/AuthCard";
import PasswordInput from "@/components/auth/PasswordInput";
import PasswordStrength from "@/components/auth/PasswordStrength";
import { Button } from "@/components/ui/button";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function parseErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string; message?: string };
    return payload.detail ?? payload.message ?? "Unable to reset password";
  } catch {
    return "Unable to reset password";
  }
}

function ResetPasswordContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const token = useMemo(() => searchParams.get("token") ?? "", [searchParams]);

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [invalidLink, setInvalidLink] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!token || invalidLink) {
    return (
      <AuthCard>
        <div className="space-y-5 text-center">
          <h1 className="font-display text-2xl font-semibold text-text-primary">
            This reset link is invalid or has expired.
          </h1>
          <Button asChild variant="outline" className="w-full">
            <Link href="/forgot-password">Request a new one</Link>
          </Button>
        </div>
      </AuthCard>
    );
  }

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setInvalidLink(false);

    if (newPassword !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setIsSubmitting(true);
    try {
      const response = await fetch(`${API_BASE}/api/v1/auth/reset-password`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ token, new_password: newPassword }),
      });

      if (!response.ok) {
        const message = await parseErrorMessage(response);
        if (response.status === 400 && message.toLowerCase().includes("invalid or has expired")) {
          setInvalidLink(true);
          return;
        }
        setError(message);
        return;
      }

      router.push("/login?message=password-updated");
    } catch {
      setError("Unable to reset password right now. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthCard>
      <div className="mb-5 space-y-2 text-center">
        <h1 className="font-display text-2xl font-semibold text-text-primary">Set a new password</h1>
      </div>

      <form onSubmit={onSubmit} className="space-y-4">
        <PasswordInput
          id="reset-new-password"
          label="New password"
          autoComplete="new-password"
          value={newPassword}
          onChange={(event) => setNewPassword(event.target.value)}
          disabled={isSubmitting}
          required
        />

        <PasswordStrength password={newPassword} />

        <PasswordInput
          id="reset-confirm-password"
          label="Confirm password"
          autoComplete="new-password"
          value={confirmPassword}
          onChange={(event) => setConfirmPassword(event.target.value)}
          disabled={isSubmitting}
          error={confirmPassword.length > 0 && confirmPassword !== newPassword ? "Passwords do not match." : undefined}
          required
        />

        {error ? <p className="text-sm text-danger">{error}</p> : null}

        <Button type="submit" className="w-full" disabled={isSubmitting}>
          {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Set new password
        </Button>
      </form>
    </AuthCard>
  );
}

function ResetPasswordFallback() {
  return (
    <AuthCard>
      <div className="flex items-center justify-center py-4 text-sm text-text-secondary">Loading…</div>
    </AuthCard>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<ResetPasswordFallback />}>
      <ResetPasswordContent />
    </Suspense>
  );
}
