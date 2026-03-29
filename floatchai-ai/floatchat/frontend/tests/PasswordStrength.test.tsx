import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import PasswordStrength from "@/components/auth/PasswordStrength";

describe("PasswordStrength", () => {
  it("shows Weak for short/low-variety passwords", () => {
    render(<PasswordStrength password="abc123" />);
    expect(screen.getByText("Weak")).toBeInTheDocument();
  });

  it("shows Fair for 8+ chars with 2 character classes", () => {
    render(<PasswordStrength password="abcdefgh1" />);
    expect(screen.getByText("Fair")).toBeInTheDocument();
  });

  it("shows Strong for 8+ chars with 3+ character classes", () => {
    render(<PasswordStrength password="Abcd1234!" />);
    expect(screen.getByText("Strong")).toBeInTheDocument();
  });
});
