export const SIDEBAR_VISIBILITY_STORAGE_KEY = "dialektike.sidebar.visibility";

export const SIDEBAR_VISIBILITIES = ["expanded", "collapsed"] as const;
export type SidebarVisibility = (typeof SIDEBAR_VISIBILITIES)[number];

export function isSidebarVisibility(value: unknown): value is SidebarVisibility {
  return typeof value === "string"
    && SIDEBAR_VISIBILITIES.includes(value as SidebarVisibility);
}

export function readSidebarVisibility(
  storage?: Pick<Storage, "getItem"> | null,
): SidebarVisibility {
  if (!storage) return "expanded";
  try {
    const value = storage.getItem(SIDEBAR_VISIBILITY_STORAGE_KEY);
    return isSidebarVisibility(value) ? value : "expanded";
  } catch {
    return "expanded";
  }
}

export function storeSidebarVisibility(
  storage: Pick<Storage, "setItem"> | null | undefined,
  visibility: SidebarVisibility,
): void {
  if (!storage) return;
  try {
    storage.setItem(SIDEBAR_VISIBILITY_STORAGE_KEY, visibility);
  } catch {
    // The control remains usable for the current session when storage is denied.
  }
}
