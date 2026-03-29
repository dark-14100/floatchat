"use client";

import type { ReactNode } from "react";
import { Waves } from "lucide-react";
import BackgroundIllustration from "@/components/layout/BackgroundIllustration";
import ThemeToggle from "@/components/layout/ThemeToggle";
import { cn } from "@/lib/utils";

interface AuthCardProps {
  children: ReactNode;
  className?: string;
  cardClassName?: string;
  showBranding?: boolean;
  subtitle?: string;
}

export default function AuthCard({
  children,
  className,
  cardClassName,
  showBranding = true,
  subtitle = "Ocean data, in plain English.",
}: AuthCardProps) {
  return (
    <div className={cn("relative min-h-screen bg-bg-base text-text-primary", className)}>
      <BackgroundIllustration />

      <div className="absolute right-4 top-4 z-[2]">
        <ThemeToggle />
      </div>

      <div className="relative z-[1] flex min-h-screen items-center justify-center px-4 py-10">
        <div
          className={cn(
            "w-full max-w-[420px] rounded-2xl border border-border-subtle bg-bg-elevated/95 p-6 shadow-lg backdrop-blur-sm sm:p-8",
            cardClassName,
          )}
        >
          {showBranding && (
            <header className="mb-6 text-center">
              <div className="mb-3 inline-flex items-center gap-2 text-ocean-deep dark:text-moon-silver">
                <Waves className="h-5 w-5" aria-hidden="true" />
                <span className="font-display text-2xl font-semibold">FloatChat</span>
              </div>
              <p className="text-sm text-text-secondary">{subtitle}</p>
            </header>
          )}

          {children}
        </div>
      </div>
    </div>
  );
}
