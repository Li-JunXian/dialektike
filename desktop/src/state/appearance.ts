export const APPEARANCE_STORAGE_KEY = "dialektike.appearance";

export const APPEARANCE_PREFERENCES = ["system", "light", "dark"] as const;
export type AppearancePreference = (typeof APPEARANCE_PREFERENCES)[number];
export type EffectiveAppearance = Exclude<AppearancePreference, "system">;

export interface AccessibilityDisplayState {
  increaseContrast: boolean;
  reduceTransparency: boolean;
  differentiateWithoutColor: boolean;
  reduceMotion: boolean;
}

export const DEFAULT_ACCESSIBILITY_DISPLAY_STATE: AccessibilityDisplayState = Object.freeze({
  increaseContrast: false,
  reduceTransparency: false,
  differentiateWithoutColor: false,
  reduceMotion: false,
});

export const LIGHT_THEME_TOKENS = Object.freeze({
  "--color-canvas": "#f7f5f1",
  "--color-sidebar": "#f4f2ed",
  "--color-surface": "#fbfaf7",
  "--color-surface-elevated": "#fdfcf9",
  "--color-surface-muted": "#eeebe5",
  "--color-surface-subtle": "#f2f0eb",
  "--color-text-primary": "#292724",
  "--color-text-secondary": "#5f5a54",
  "--color-text-tertiary": "#6e6861",
  "--color-border-subtle": "#d8d3cb",
  "--color-border-control": "#817a72",
  "--color-focus": "#315f9c",
  "--color-executor": "#456a9b",
  "--color-executor-soft": "#e6edf5",
  "--color-on-executor": "#ffffff",
  "--color-auditor": "#96513d",
  "--color-auditor-soft": "#f5e8e2",
  "--color-on-auditor": "#ffffff",
  "--color-danger": "#913d32",
  "--color-danger-soft": "#f8e7e3",
  "--color-on-danger": "#ffffff",
  "--color-code-surface": "#ebe8e2",
  "--color-code-text": "#302d29",
  "--color-overlay": "rgba(36, 32, 29, 0.48)",
  "--color-shadow": "rgba(48, 41, 36, 0.14)",
});

export const DARK_THEME_TOKENS = Object.freeze({
  "--color-canvas": "#171816",
  "--color-sidebar": "#1c1d1a",
  "--color-surface": "#22231f",
  "--color-surface-elevated": "#292a25",
  "--color-surface-muted": "#30312b",
  "--color-surface-subtle": "#272823",
  "--color-text-primary": "#e7e3db",
  "--color-text-secondary": "#c1bcb3",
  "--color-text-tertiary": "#aaa49a",
  "--color-border-subtle": "#42443c",
  "--color-border-control": "#8d9085",
  "--color-focus": "#8db5e6",
  "--color-executor": "#91b1d8",
  "--color-executor-soft": "#263547",
  "--color-on-executor": "#18212b",
  "--color-auditor": "#d6967d",
  "--color-auditor-soft": "#432e28",
  "--color-on-auditor": "#251815",
  "--color-danger": "#ee9c8f",
  "--color-danger-soft": "#472b27",
  "--color-on-danger": "#281512",
  "--color-code-surface": "#2e302a",
  "--color-code-text": "#e7e3db",
  "--color-overlay": "rgba(5, 6, 5, 0.68)",
  "--color-shadow": "rgba(0, 0, 0, 0.38)",
});

export const HIGH_CONTRAST_OVERRIDES = Object.freeze({
  light: {
    "--color-text-secondary": "#47433e",
    "--color-text-tertiary": "#514c46",
    "--color-border-subtle": "#8a837a",
    "--color-border-control": "#5d5750",
    "--color-focus": "#174f94",
  },
  dark: {
    "--color-text-secondary": "#d8d3ca",
    "--color-text-tertiary": "#c5c0b7",
    "--color-border-subtle": "#929589",
    "--color-border-control": "#c4c7bb",
    "--color-focus": "#aed0f5",
  },
} as const);

export type ThemeTokenMap = Record<string, string>;

export function isAppearancePreference(value: unknown): value is AppearancePreference {
  return typeof value === "string" && APPEARANCE_PREFERENCES.includes(value as AppearancePreference);
}

export function readAppearancePreference(storage?: Pick<Storage, "getItem"> | null): AppearancePreference {
  if (!storage) return "system";
  try {
    const value = storage.getItem(APPEARANCE_STORAGE_KEY);
    return isAppearancePreference(value) ? value : "system";
  } catch {
    return "system";
  }
}

export function storeAppearancePreference(
  storage: Pick<Storage, "setItem"> | null | undefined,
  preference: AppearancePreference,
): void {
  if (!storage) return;
  try {
    storage.setItem(APPEARANCE_STORAGE_KEY, preference);
  } catch {
    // Appearance remains usable for the current session when storage is denied.
  }
}

export function resolveAppearance(
  preference: AppearancePreference,
  systemAppearance: EffectiveAppearance,
): EffectiveAppearance {
  return preference === "system" ? systemAppearance : preference;
}

export function themeTokens(
  appearance: EffectiveAppearance,
  increaseContrast: boolean,
): ThemeTokenMap {
  return {
    ...(appearance === "dark" ? DARK_THEME_TOKENS : LIGHT_THEME_TOKENS),
    ...(increaseContrast ? HIGH_CONTRAST_OVERRIDES[appearance] : {}),
  };
}

export function applyAppearanceState(
  root: HTMLElement,
  preference: AppearancePreference,
  effective: EffectiveAppearance,
  accessibility: AccessibilityDisplayState,
): void {
  root.dataset.appearance = preference;
  root.dataset.effectiveAppearance = effective;
  root.dataset.increaseContrast = String(accessibility.increaseContrast);
  root.dataset.reduceTransparency = String(accessibility.reduceTransparency);
  root.dataset.differentiateWithoutColor = String(accessibility.differentiateWithoutColor);
  root.dataset.reduceMotion = String(accessibility.reduceMotion);
  root.style.colorScheme = effective;
  for (const [name, value] of Object.entries(themeTokens(effective, accessibility.increaseContrast))) {
    root.style.setProperty(name, value);
  }
}

export function contrastRatio(foreground: string, background: string): number {
  const foregroundLuminance = relativeLuminance(foreground);
  const backgroundLuminance = relativeLuminance(background);
  const lighter = Math.max(foregroundLuminance, backgroundLuminance);
  const darker = Math.min(foregroundLuminance, backgroundLuminance);
  return (lighter + 0.05) / (darker + 0.05);
}

function relativeLuminance(hex: string): number {
  const normalized = hex.replace(/^#/, "");
  if (!/^[0-9a-f]{6}$/i.test(normalized)) {
    throw new Error(`Contrast colours must be six-digit hex values: ${hex}`);
  }
  const channels = [0, 2, 4].map((offset) => Number.parseInt(normalized.slice(offset, offset + 2), 16) / 255);
  const [red, green, blue] = channels.map((channel) => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}
