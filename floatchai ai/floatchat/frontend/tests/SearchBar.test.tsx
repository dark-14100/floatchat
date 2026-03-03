import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import SearchBar from "@/components/map/SearchBar";

describe("SearchBar", () => {
  it("resolves decimal latitude/longitude input", async () => {
    const user = userEvent.setup();
    const onLocationResolved = vi.fn();
    const onBasinResolved = vi.fn();

    render(
      <SearchBar
        onLocationResolved={onLocationResolved}
        onBasinResolved={onBasinResolved}
      />,
    );

    const input = screen.getByPlaceholderText(/12.5, 80.2/i);
    await user.type(input, "10.5, 72.3");
    await user.keyboard("{Enter}");

    expect(onLocationResolved).toHaveBeenCalledWith(10.5, 72.3, "10.5, 72.3");
    expect(onBasinResolved).not.toHaveBeenCalled();
  });

  it("resolves DMS input", async () => {
    const user = userEvent.setup();
    const onLocationResolved = vi.fn();

    render(
      <SearchBar
        onLocationResolved={onLocationResolved}
        onBasinResolved={vi.fn()}
      />,
    );

    const input = screen.getByPlaceholderText(/12.5, 80.2/i);
    await user.type(input, "10° 30' N, 72° 15' E");
    await user.click(screen.getByRole("button", { name: /go/i }));

    expect(onLocationResolved).toHaveBeenCalledWith(10.5, 72.25, "10° 30' N, 72° 15' E");
  });

  it("resolves basin name before lookup", async () => {
    const user = userEvent.setup();
    const onBasinResolved = vi.fn();

    render(
      <SearchBar
        onLocationResolved={vi.fn()}
        onBasinResolved={onBasinResolved}
      />,
    );

    const input = screen.getByPlaceholderText(/12.5, 80.2/i);
    await user.type(input, "Arabian Sea");
    await user.keyboard("{Enter}");

    expect(onBasinResolved).toHaveBeenCalledWith("Arabian Sea");
  });

  it("shows an error when location cannot be resolved", async () => {
    const user = userEvent.setup();

    render(
      <SearchBar
        onLocationResolved={vi.fn()}
        onBasinResolved={vi.fn()}
      />,
    );

    const input = screen.getByPlaceholderText(/12.5, 80.2/i);
    await user.type(input, "unknown place xyz");
    await user.keyboard("{Enter}");

    expect(screen.getByText("Location not found")).toBeInTheDocument();
  });
});
