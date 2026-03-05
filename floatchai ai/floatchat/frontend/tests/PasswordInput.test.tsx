import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PasswordInput from "@/components/auth/PasswordInput";

describe("PasswordInput", () => {
  it("renders password field and toggles visibility", async () => {
    const user = userEvent.setup();

    render(<PasswordInput id="password" label="Password" value="secret" onChange={() => {}} />);

    const input = screen.getByLabelText("Password") as HTMLInputElement;
    expect(input.type).toBe("password");

    await user.click(screen.getByRole("button", { name: "Show password" }));
    expect(input.type).toBe("text");

    await user.click(screen.getByRole("button", { name: "Hide password" }));
    expect(input.type).toBe("password");
  });

  it("renders inline error message when provided", () => {
    render(
      <PasswordInput
        id="password"
        label="Password"
        value=""
        onChange={() => {}}
        error="Password is required"
      />,
    );

    expect(screen.getByText("Password is required")).toBeInTheDocument();
  });
});
