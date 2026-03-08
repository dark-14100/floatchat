import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import ClarificationWidget from "@/components/chat/ClarificationWidget";

describe("ClarificationWidget", () => {
  const baseProps = {
    visible: true,
    isLoading: false,
    originalQuery: "show me ocean data",
    missingDimensions: ["variable", "region"],
    clarificationQuestions: [
      {
        dimension: "variable",
        question_text: "Which variable?",
        options: ["temperature", "salinity"],
      },
      {
        dimension: "region",
        question_text: "Which region?",
        options: ["Arabian Sea", "Indian Ocean"],
      },
    ],
    onAssembledQuery: vi.fn(),
    onSkip: vi.fn(),
    onDismiss: vi.fn(),
  };

  it("renders nothing when not visible", () => {
    const { container } = render(
      <ClarificationWidget
        {...baseProps}
        visible={false}
      />,
    );

    expect(container.innerHTML).toBe("");
  });

  it("requires one selection per missing dimension before run", async () => {
    const user = userEvent.setup();
    const onAssembledQuery = vi.fn();

    render(
      <ClarificationWidget
        {...baseProps}
        onAssembledQuery={onAssembledQuery}
      />,
    );

    const runButton = screen.getByRole("button", { name: /run query/i });
    expect(runButton).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "temperature" }));
    expect(runButton).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Arabian Sea" }));
    expect(runButton).toBeEnabled();

    await user.click(runButton);
    expect(onAssembledQuery).toHaveBeenCalledWith(
      "show me ocean data, specifically variable: temperature, region: Arabian Sea",
    );
  });

  it("fires skip callback", async () => {
    const user = userEvent.setup();
    const onSkip = vi.fn();

    render(
      <ClarificationWidget
        {...baseProps}
        onSkip={onSkip}
      />,
    );

    await user.click(screen.getByRole("button", { name: /skip and run anyway/i }));
    expect(onSkip).toHaveBeenCalledTimes(1);
  });

  it("shows loading state while detection is in flight", () => {
    render(
      <ClarificationWidget
        {...baseProps}
        isLoading
      />,
    );

    expect(screen.getByText(/detecting missing details/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /run query/i })).toBeDisabled();
  });
});
