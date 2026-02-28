/**
 * SuggestedFollowUps component tests.
 *
 * - Renders chips
 * - Click fires callback
 * - Renders nothing when empty
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import SuggestedFollowUps from "@/components/chat/SuggestedFollowUps";

describe("SuggestedFollowUps", () => {
  const suggestions = [
    "What is the temperature at 500m?",
    "Show me salinity profiles",
    "How many floats are active?",
  ];

  it("renders all suggestion chips", () => {
    render(
      <SuggestedFollowUps suggestions={suggestions} onSelect={vi.fn()} />,
    );
    expect(screen.getByText("What is the temperature at 500m?")).toBeInTheDocument();
    expect(screen.getByText("Show me salinity profiles")).toBeInTheDocument();
    expect(screen.getByText("How many floats are active?")).toBeInTheDocument();
  });

  it("fires onSelect callback with the correct query when clicked", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <SuggestedFollowUps suggestions={suggestions} onSelect={onSelect} />,
    );

    await user.click(screen.getByText("Show me salinity profiles"));
    expect(onSelect).toHaveBeenCalledWith("Show me salinity profiles");
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("renders nothing when suggestions array is empty", () => {
    const { container } = render(
      <SuggestedFollowUps suggestions={[]} onSelect={vi.fn()} />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("renders nothing when suggestions is undefined-like empty", () => {
    const { container } = render(
      // @ts-expect-error — testing runtime behavior with null
      <SuggestedFollowUps suggestions={null} onSelect={vi.fn()} />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("renders chips as buttons with correct role", () => {
    render(
      <SuggestedFollowUps suggestions={suggestions} onSelect={vi.fn()} />,
    );
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(3);
  });

  it("has an accessible group role", () => {
    render(
      <SuggestedFollowUps suggestions={suggestions} onSelect={vi.fn()} />,
    );
    expect(screen.getByRole("group")).toHaveAttribute(
      "aria-label",
      "Follow-up suggestions",
    );
  });
});
