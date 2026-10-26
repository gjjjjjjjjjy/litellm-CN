import { describe, expect, it } from "vitest";
import { parseHiddenMenuKeys } from "./focusMenu";
import { menuGroups, visibleMenuGroups, type MenuItem, type MenuVisibilityContext } from "./leftnav";

const visibleKeys = (hiddenMenuKeys?: ReadonlySet<string>): string[] => {
  const flatten = (items: readonly MenuItem[]): string[] =>
    items.flatMap((item) => [item.key, ...flatten(item.children ?? [])]);
  const adminContext: MenuVisibilityContext = {
    userRole: "Admin",
    hiddenMenuKeys,
    isViewOnly: false,
    isOrgAdmin: false,
    isTeamAdmin: false,
  };
  return visibleMenuGroups(menuGroups, adminContext).flatMap((group) => flatten(group.items));
};

describe("parseHiddenMenuKeys", () => {
  it("hides nothing when the build sets no list", () => {
    expect(parseHiddenMenuKeys(undefined).size).toBe(0);
  });

  it("trims keys and ignores empty entries", () => {
    expect([...parseHiddenMenuKeys(" agentic, ,tools ,")]).toEqual(["agentic", "tools"]);
  });
});

describe("hidden menu keys", () => {
  it("removes a hidden item together with its children and keeps the rest", () => {
    const full = visibleKeys();
    expect(full).toEqual(expect.arrayContaining(["agentic", "agents", "tools", "search-tools", "models", "qos"]));

    const focused = visibleKeys(new Set(["agentic", "tools"]));
    expect(focused).not.toEqual(expect.arrayContaining(["agentic"]));
    expect(focused.filter((key) => ["agentic", "agents", "tools", "search-tools"].includes(key))).toEqual([]);
    expect(focused).toEqual(expect.arrayContaining(["models", "qos", "logs"]));
  });

  it("shows the service quality page to every role, since it is everyone's landing page", () => {
    const internalContext: MenuVisibilityContext = {
      userRole: "Internal User",
      isViewOnly: false,
      isOrgAdmin: false,
      isTeamAdmin: false,
    };
    const internal = visibleMenuGroups(menuGroups, internalContext).flatMap((group) =>
      group.items.map((item) => item.key),
    );
    expect(internal).toContain("qos");
  });
});
