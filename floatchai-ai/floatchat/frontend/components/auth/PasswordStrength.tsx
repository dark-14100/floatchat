import { cn } from "@/lib/utils";

type StrengthLevel = "weak" | "fair" | "strong";

interface PasswordStrengthProps {
  password: string;
  className?: string;
}

function getCharacterClassCount(value: string): number {
  let count = 0;
  if (/[a-z]/.test(value)) count += 1;
  if (/[A-Z]/.test(value)) count += 1;
  if (/\d/.test(value)) count += 1;
  if (/[^a-zA-Z\d]/.test(value)) count += 1;
  return count;
}

function getStrength(password: string): { level: StrengthLevel; score: 1 | 2 | 3; label: string } {
  const classCount = getCharacterClassCount(password);

  if (password.length >= 8 && classCount >= 3) {
    return { level: "strong", score: 3, label: "Strong" };
  }

  if (password.length >= 8 && classCount >= 2) {
    return { level: "fair", score: 2, label: "Fair" };
  }

  return { level: "weak", score: 1, label: "Weak" };
}

const activeClassesByLevel: Record<StrengthLevel, string> = {
  weak: "bg-danger",
  fair: "bg-coral",
  strong: "bg-seafoam",
};

export default function PasswordStrength({ password, className }: PasswordStrengthProps) {
  const { level, score, label } = getStrength(password);

  return (
    <div className={cn("space-y-2", className)} aria-live="polite">
      <div className="flex items-center justify-between text-xs">
        <span className="text-text-secondary">Password strength</span>
        <span className="font-medium text-text-primary">{label}</span>
      </div>

      <div className="grid grid-cols-3 gap-1" role="presentation">
        {Array.from({ length: 3 }).map((_, index) => (
          <div
            key={index}
            className={cn(
              "h-1.5 rounded-full bg-bg-subtle transition-colors",
              index < score ? activeClassesByLevel[level] : undefined,
            )}
          />
        ))}
      </div>
    </div>
  );
}
