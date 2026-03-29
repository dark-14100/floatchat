/**
 * LoadingMessage component tests.
 *
 * - Renders thinking state
 * - Renders interpreting state with text
 * - Renders executing state with progress bar
 * - Renders nothing when streamState is null or done
 */

import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import LoadingMessage from "@/components/chat/LoadingMessage";

describe("LoadingMessage", () => {
  it("renders 'Thinking' for thinking state", () => {
    render(<LoadingMessage streamState="thinking" />);
    expect(screen.getByText("Thinking")).toBeInTheDocument();
  });

  it("renders interpretation text for interpreting state", () => {
    render(
      <LoadingMessage
        streamState="interpreting"
        interpretation="Looking for temperature data in the North Atlantic"
      />,
    );
    expect(screen.getByText("Interpreting your query")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Looking for temperature data in the North Atlantic",
      ),
    ).toBeInTheDocument();
  });

  it("renders progress bar for executing state", () => {
    render(<LoadingMessage streamState="executing" />);
    expect(screen.getByText("Running query...")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
  });

  it("renders nothing when streamState is null", () => {
    const { container } = render(<LoadingMessage streamState={null} />);
    expect(container.innerHTML).toBe("");
  });

  it("renders nothing when streamState is done", () => {
    const { container } = render(<LoadingMessage streamState="done" />);
    expect(container.innerHTML).toBe("");
  });

  it("has aria-live polite for accessibility", () => {
    render(<LoadingMessage streamState="thinking" />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
  });
});
