"use client";

import { useState, type ComponentProps } from "react";
import { Eye, EyeOff } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface PasswordInputProps extends Omit<ComponentProps<typeof Input>, "type"> {
  label?: string;
  error?: string;
  wrapperClassName?: string;
}

export default function PasswordInput({
  label,
  error,
  id,
  className,
  wrapperClassName,
  ...props
}: PasswordInputProps) {
  const [isVisible, setIsVisible] = useState(false);
  const inputId = id ?? "password";

  return (
    <div className={cn("space-y-2", wrapperClassName)}>
      {label ? (
        <label htmlFor={inputId} className="text-sm font-medium text-text-primary">
          {label}
        </label>
      ) : null}

      <div className="relative">
        <Input
          id={inputId}
          type={isVisible ? "text" : "password"}
          className={cn("pr-10", className)}
          {...props}
        />

        <button
          type="button"
          onClick={() => setIsVisible((current) => !current)}
          className="absolute inset-y-0 right-0 flex items-center px-3 text-text-muted transition-colors hover:text-text-secondary"
          aria-label={isVisible ? "Hide password" : "Show password"}
        >
          {isVisible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>

      {error ? (
        <p className="text-xs text-danger" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
