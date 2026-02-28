/**
 * ChatInput component tests.
 *
 * - Submits on Enter
 * - Newline on Shift+Enter
 * - Disabled when loading
 * - Shows character count at >450 chars
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import ChatInput from "@/components/chat/ChatInput";

describe("ChatInput", () => {
  it("renders a textarea with placeholder", () => {
    render(<ChatInput onSubmit={vi.fn()} isLoading={false} />);
    expect(
      screen.getByPlaceholderText("Ask about ocean data..."),
    ).toBeInTheDocument();
  });

  it("uses a <textarea> element, not <input> (Hard Rule 6)", () => {
    render(<ChatInput onSubmit={vi.fn()} isLoading={false} />);
    const el = screen.getByRole("textbox");
    expect(el.tagName).toBe("TEXTAREA");
  });

  it("submits on Enter key", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<ChatInput onSubmit={onSubmit} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    await user.click(textarea);
    await user.type(textarea, "Show me ARGO data");
    await user.keyboard("{Enter}");

    expect(onSubmit).toHaveBeenCalledWith("Show me ARGO data");
  });

  it("inserts newline on Shift+Enter", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<ChatInput onSubmit={onSubmit} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    await user.click(textarea);
    await user.type(textarea, "Line 1");
    await user.keyboard("{Shift>}{Enter}{/Shift}");
    await user.type(textarea, "Line 2");

    expect(onSubmit).not.toHaveBeenCalled();
    expect(textarea).toHaveValue("Line 1\nLine 2");
  });

  it("disables textarea and button when isLoading is true", () => {
    render(<ChatInput onSubmit={vi.fn()} isLoading={true} />);
    const textarea = screen.getByRole("textbox");
    expect(textarea).toBeDisabled();
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
  });

  it("does not submit when textarea is empty", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<ChatInput onSubmit={onSubmit} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    await user.click(textarea);
    await user.keyboard("{Enter}");

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("clears textarea after submission", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<ChatInput onSubmit={onSubmit} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    await user.click(textarea);
    await user.type(textarea, "test query");
    await user.keyboard("{Enter}");

    expect(textarea).toHaveValue("");
  });

  it("shows character count when value exceeds 450 characters", async () => {
    render(<ChatInput onSubmit={vi.fn()} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    const longText = "a".repeat(460);
    // Use fireEvent.change to avoid typing 460 chars one-by-one
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(textarea, { target: { value: longText } });

    expect(screen.getByText("460")).toBeInTheDocument();
  });

  it("accepts a custom placeholder", () => {
    render(
      <ChatInput
        onSubmit={vi.fn()}
        isLoading={false}
        placeholder="Custom placeholder"
      />,
    );
    expect(
      screen.getByPlaceholderText("Custom placeholder"),
    ).toBeInTheDocument();
  });
});
