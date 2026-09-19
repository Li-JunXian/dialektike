/**
 * Browser-side mirror of the inert-content HTTP(S) boundary. Keep this
 * deliberately narrower than URL(): credentials, controls, whitespace and
 * backslashes are rejected before a provider-authored value can become a link.
 */
export function safeHttpUrl(value: string): string | undefined {
  if (
    !value ||
    value.includes("\\") ||
    [...value].some((character) => {
      const codePoint = character.codePointAt(0) ?? 0;
      return codePoint <= 0x20 || codePoint === 0x7f;
    })
  ) return undefined;
  try {
    const parsed = new URL(value);
    if (
      (parsed.protocol !== "https:" && parsed.protocol !== "http:") ||
      !parsed.hostname ||
      parsed.username ||
      parsed.password
    ) return undefined;
    return parsed.href;
  } catch {
    return undefined;
  }
}
