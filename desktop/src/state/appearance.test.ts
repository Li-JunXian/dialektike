import { describe, expect, it } from "vitest";

import indexMarkup from "../../index.html?raw";
import prehydrateAppearance from "../../public/prehydrate-appearance.js?raw";
import stylesheet from "../styles.css?inline";
import appSource from "../App.tsx?raw";

import {
  APPEARANCE_STORAGE_KEY,
  DARK_THEME_TOKENS,
  HIGH_CONTRAST_OVERRIDES,
  LIGHT_THEME_TOKENS,
  contrastRatio,
  readAppearancePreference,
  resolveAppearance,
  themeTokens,
} from "./appearance";

describe("appearance preferences", () => {
  it("defaults invalid or unavailable storage to System", () => {
    expect(readAppearancePreference(null)).toBe("system");
    expect(readAppearancePreference({ getItem: () => "sepia" })).toBe("system");
    expect(readAppearancePreference({ getItem: (key) => key === APPEARANCE_STORAGE_KEY ? "dark" : null })).toBe("dark");
  });

  it("follows the system only while System is selected", () => {
    expect(resolveAppearance("system", "dark")).toBe("dark");
    expect(resolveAppearance("light", "dark")).toBe("light");
    expect(resolveAppearance("dark", "light")).toBe("dark");
  });

  it("resolves the persisted preference before the application module paints", () => {
    expect(indexMarkup).toContain('<meta name="color-scheme" content="light dark" />');
    const bootstrap = '<script src="/prehydrate-appearance.js"></script>';
    expect(indexMarkup).toContain(bootstrap);
    expect(indexMarkup.indexOf(bootstrap)).toBeLessThan(indexMarkup.indexOf('/src/main.tsx'));

    expect(runPrehydrate(null, true)).toMatchObject({
      appearance: "system",
      effectiveAppearance: "dark",
      colorScheme: "dark",
    });
    expect(runPrehydrate("light", true)).toMatchObject({
      appearance: "light",
      effectiveAppearance: "light",
      colorScheme: "light",
    });
    expect(runPrehydrate("dark", false)).toMatchObject({
      appearance: "dark",
      effectiveAppearance: "dark",
      colorScheme: "dark",
    });
    expect(runPrehydrate("sepia", false)).toMatchObject({
      appearance: "system",
      effectiveAppearance: "light",
      colorScheme: "light",
    });
    expect(runPrehydrate(null, true, true)).toMatchObject({
      appearance: "system",
      effectiveAppearance: "dark",
      colorScheme: "dark",
    });
  });
});

describe("semantic colour contrast", () => {
  const palettes = [
    ["light", LIGHT_THEME_TOKENS],
    ["dark", DARK_THEME_TOKENS],
  ] as const;

  for (const [name, palette] of palettes) {
    it(`${name} ordinary text and role accents meet WCAG AA`, () => {
      const surfaces = [palette["--color-canvas"], palette["--color-surface"]];
      for (const surface of surfaces) {
        expect(contrastRatio(palette["--color-text-primary"], surface)).toBeGreaterThanOrEqual(4.5);
        expect(contrastRatio(palette["--color-text-secondary"], surface)).toBeGreaterThanOrEqual(4.5);
        expect(contrastRatio(palette["--color-text-tertiary"], surface)).toBeGreaterThanOrEqual(4.5);
        expect(contrastRatio(palette["--color-executor"], surface)).toBeGreaterThanOrEqual(4.5);
        expect(contrastRatio(palette["--color-auditor"], surface)).toBeGreaterThanOrEqual(4.5);
        expect(contrastRatio(palette["--color-danger"], surface)).toBeGreaterThanOrEqual(4.5);
      }
      expect(contrastRatio(palette["--color-focus"], palette["--color-surface"])).toBeGreaterThanOrEqual(3);
      expect(contrastRatio(palette["--color-border-control"], palette["--color-surface"])).toBeGreaterThanOrEqual(3);
      expect(contrastRatio(palette["--color-executor"], palette["--color-executor-soft"])).toBeGreaterThanOrEqual(4.5);
      expect(contrastRatio(palette["--color-auditor"], palette["--color-auditor-soft"])).toBeGreaterThanOrEqual(4.5);
      expect(contrastRatio(palette["--color-danger"], palette["--color-danger-soft"])).toBeGreaterThanOrEqual(4.5);
      expect(contrastRatio(palette["--color-on-executor"], palette["--color-executor"])).toBeGreaterThanOrEqual(4.5);
      expect(contrastRatio(palette["--color-on-auditor"], palette["--color-auditor"])).toBeGreaterThanOrEqual(4.5);
      expect(contrastRatio(palette["--color-on-danger"], palette["--color-danger"])).toBeGreaterThanOrEqual(4.5);
      expect(contrastRatio(palette["--color-code-text"], palette["--color-code-surface"])).toBeGreaterThanOrEqual(4.5);
    });
  }

  it("enhanced contrast never weakens the declared focus or text pairs", () => {
    for (const appearance of ["light", "dark"] as const) {
      const ordinary = themeTokens(appearance, false);
      const enhanced = themeTokens(appearance, true);
      const surface = enhanced["--color-surface"];
      for (const token of ["--color-text-secondary", "--color-text-tertiary", "--color-focus", "--color-border-control"] as const) {
        expect(contrastRatio(enhanced[token], surface)).toBeGreaterThanOrEqual(contrastRatio(ordinary[token], surface));
      }
      expect(HIGH_CONTRAST_OVERRIDES[appearance]).toBeDefined();
    }
  });

  it("keeps pre-hydration CSS tokens identical to the measured TypeScript palettes", () => {
    expect(cssThemeTokens(":root")).toEqual(LIGHT_THEME_TOKENS);
    expect(cssThemeTokens(':root[data-effective-appearance="dark"]')).toEqual(DARK_THEME_TOKENS);
  });

  it("keeps interactive topic and code states on appearance-aware surfaces", () => {
    for (const selector of [
      '.topic-item__menu-button[aria-expanded="true"]',
      ".sidebar-footer-button--active",
      ".code-block__toolbar button:hover",
    ]) {
      const block = cssDeclarationBlockContaining(selector);
      expect(block, selector).toContain("var(--color-surface-muted)");
      expect(block, selector).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    }
  });

  it("keeps Context interactive above the transparent composer overlay and omits the inactive attachment affordance", () => {
    const checkpointIndex = stylesheet.indexOf(".composer-dock .checkpoint-control");
    expect(checkpointIndex).toBeGreaterThanOrEqual(0);
    const start = stylesheet.indexOf("{", checkpointIndex);
    const end = stylesheet.indexOf("}", start);
    expect(stylesheet.slice(start + 1, end)).toContain("pointer-events: auto");
    expect(appSource).not.toContain("Paperclip");
    expect(appSource).not.toContain("Attachments are not available");
  });
});

function cssThemeTokens(selector: string): Record<string, string> {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const body = stylesheet.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`))?.[1];
  if (body === undefined) throw new Error(`Missing CSS theme selector ${selector}`);
  return Object.fromEntries(
    [...body.matchAll(/(--color-[a-z-]+):\s*([^;]+);/g)].map((match) => [match[1], match[2].trim()]),
  );
}

function cssDeclarationBlockContaining(selector: string): string {
  const selectorIndex = stylesheet.indexOf(selector);
  if (selectorIndex < 0) throw new Error(`Missing CSS selector ${selector}`);
  const start = stylesheet.indexOf("{", selectorIndex);
  const end = stylesheet.indexOf("}", start);
  if (start < 0 || end < 0) throw new Error(`Malformed CSS selector ${selector}`);
  return stylesheet.slice(start + 1, end);
}

function runPrehydrate(stored: string | null, systemDark: boolean, storageThrows = false) {
  const root = { dataset: {} as Record<string, string>, style: {} as Record<string, string> };
  const storage = { getItem: () => {
    if (storageThrows) throw new Error("storage denied");
    return stored;
  } };
  const browser = {
    localStorage: storage,
    matchMedia: () => ({ matches: systemDark }),
  };
  Function("window", "document", prehydrateAppearance)(browser, { documentElement: root });
  return {
    ...root.dataset,
    colorScheme: root.style.colorScheme,
  };
}
