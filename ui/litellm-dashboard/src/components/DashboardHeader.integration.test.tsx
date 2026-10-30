import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "next-themes";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CommandPaletteProvider } from "@/components/CommandPalette/CommandPaletteProvider";
import { DashboardHeader } from "./DashboardHeader";

vi.mock("next/navigation", () => ({ usePathname: () => "/ui/logs", useRouter: () => ({ push: vi.fn() }) }));

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/get/ui_settings")) return Response.json({ values: {} });
      if (url.endsWith("/litellm/.well-known/litellm-ui-config")) {
        const config = { server_root_path: "", proxy_base_url: "", is_control_plane: false, workers: [] };
        return Response.json(config);
      }
      return Response.json({}, { status: 404 });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.classList.remove("dark");
});

function renderHeader() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider attribute="class" defaultTheme="light" enableSystem={false}>
        <CommandPaletteProvider>
          <DashboardHeader />
        </CommandPaletteProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  );
}

describe("focused dashboard header", () => {
  it("keeps theme switching available without loading gateway tools or product notifications", async () => {
    const user = userEvent.setup();
    renderHeader();
    expect(screen.queryByRole("button", { name: "More options" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Notifications" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "LiteAdmin" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Blog" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Docs" })).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Switch to dark mode (beta)" }));
    expect(await screen.findByRole("button", { name: "Switch to light mode" })).toBeInTheDocument();
    expect(document.documentElement).toHaveClass("dark");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("still opens page search from the compact header", async () => {
    const user = userEvent.setup();
    renderHeader();
    await user.click(screen.getByRole("button", { name: "Search", exact: true }));
    expect(await screen.findByRole("dialog", { name: "Command palette" })).toBeVisible();
    expect(fetch).not.toHaveBeenCalledWith(expect.stringContaining("/public/litellm_blog_posts"), expect.anything());
    expect(fetch).not.toHaveBeenCalledWith(expect.stringContaining("/api/plugins"), expect.anything());
  });
});
