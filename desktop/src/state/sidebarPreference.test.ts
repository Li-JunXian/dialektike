import { describe, expect, it, vi } from "vitest";
import stylesheet from "../styles.css?inline";

import {
  SIDEBAR_VISIBILITY_STORAGE_KEY,
  isSidebarVisibility,
  readSidebarVisibility,
  storeSidebarVisibility,
} from "./sidebarPreference";

describe("sidebar visibility preference", () => {
  it("accepts only the two authored visibility values", () => {
    expect(isSidebarVisibility("expanded")).toBe(true);
    expect(isSidebarVisibility("collapsed")).toBe(true);
    expect(isSidebarVisibility("compact")).toBe(false);
    expect(isSidebarVisibility(true)).toBe(false);
  });

  it("defaults safely when storage is absent, malformed, or unavailable", () => {
    expect(readSidebarVisibility(null)).toBe("expanded");
    expect(readSidebarVisibility({ getItem: () => "collapsed" })).toBe("collapsed");
    expect(readSidebarVisibility({ getItem: () => "narrow" })).toBe("expanded");
    expect(readSidebarVisibility({ getItem: () => { throw new Error("denied"); } })).toBe("expanded");
  });

  it("persists the validated owner-local value without making storage mandatory", () => {
    const setItem = vi.fn();
    storeSidebarVisibility({ setItem }, "collapsed");
    expect(setItem).toHaveBeenCalledWith(SIDEBAR_VISIBILITY_STORAGE_KEY, "collapsed");
    expect(() => storeSidebarVisibility({ setItem: () => { throw new Error("quota"); } }, "expanded")).not.toThrow();
  });

  it("uses a narrower responsive column and a dedicated compact rail without moving workspace internals", () => {
    expect(stylesheet).toContain("--sidebar-width: 264px");
    expect(stylesheet).toContain("--sidebar-collapsed-width: 62px");
    expect(stylesheet).toContain("grid-template-columns: var(--active-sidebar-width) minmax(0, 1fr)");
    expect(stylesheet).toContain('.app-shell[data-sidebar-collapsed="true"]');
    expect(stylesheet).toContain("--active-sidebar-width: var(--sidebar-collapsed-width)");
    expect(stylesheet).toContain(".topic-sidebar--collapsed .appearance-control:focus-within");
    expect(stylesheet).toMatch(/@media \(max-width: 880px\)[\s\S]*--sidebar-collapsed-width: 58px/);
  });
});
