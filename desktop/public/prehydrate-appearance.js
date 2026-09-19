(() => {
  const allowed = new Set(["system", "light", "dark"]);
  let preference = "system";
  try {
    const stored = window.localStorage.getItem("dialektike.appearance");
    if (allowed.has(stored)) preference = stored;
  } catch {
    // A denied storage read keeps the native System preference.
  }
  const systemDark = Boolean(
    window.matchMedia?.("(prefers-color-scheme: dark)").matches,
  );
  const effective = preference === "system"
    ? (systemDark ? "dark" : "light")
    : preference;
  const root = document.documentElement;
  root.dataset.appearance = preference;
  root.dataset.effectiveAppearance = effective;
  root.style.colorScheme = effective;
})();
