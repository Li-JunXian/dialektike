import { describe, expect, it } from "vitest";

import capabilitySource from "../../src-tauri/capabilities/default.json?raw";
import { isNativeDesktopRuntime } from "./tauri";

describe("Tauri runtime boundary", () => {
  it("recognizes only the native bridge marker", () => {
    expect(isNativeDesktopRuntime({})).toBe(false);
    expect(
      isNativeDesktopRuntime({ __TAURI_INTERNALS__: { invoke() {} } }),
    ).toBe(true);
  });

  it("treats an ordinary browser/global scope as preview mode", () => {
    expect(isNativeDesktopRuntime(null)).toBe(false);
    expect(isNativeDesktopRuntime("browser")).toBe(false);
  });

  it("grants only the two window theme commands used by the appearance bridge", () => {
    const capability = JSON.parse(capabilitySource) as { permissions: string[] };
    expect(capability.permissions).toEqual(expect.arrayContaining([
      "core:window:allow-theme",
      "core:window:allow-set-theme",
    ]));
    expect(capability.permissions).not.toContain("core:window:default");
  });
});
