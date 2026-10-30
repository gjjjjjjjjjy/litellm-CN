import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DashboardHeader } from "./DashboardHeader";

const state = vi.hoisted(() => ({ pathname: "/ui/logs" }));
vi.mock("next/navigation", () => ({ usePathname: () => state.pathname }));
vi.mock("@/components/CommandPalette/CommandPaletteTrigger", () => ({ CommandPaletteTrigger: () => null }));
vi.mock("@/components/ThemeToggle/ThemeToggle", () => ({ default: () => null }));

beforeEach(() => {
  state.pathname = "/ui/logs";
});

describe("DashboardHeader", () => {
  it.each([
    ["/ui/", "Home"],
    ["/ui/models-and-endpoints", "Models + Endpoints"],
  ])("shows the current page title for %s", (pathname, title) => {
    state.pathname = pathname;
    render(<DashboardHeader />);
    expect(screen.getByText(title)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AI Gateway" })).toHaveAttribute("href", "/ui/");
  });
});
