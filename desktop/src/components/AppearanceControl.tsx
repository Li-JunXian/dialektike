import { MoonStar, SunMedium, SunMoon } from "lucide-react";

import type { AppearancePreference } from "../state/appearance";

interface AppearanceControlProps {
  value: AppearancePreference;
  onChange: (value: AppearancePreference) => void;
  disabled?: boolean;
}

export function AppearanceControl({ value, onChange, disabled = false }: AppearanceControlProps) {
  return (
    <label className="appearance-control" title="Appearance">
      <AppearanceIcon value={value} />
      <span className="sr-only">Appearance</span>
      <select
        aria-label="Appearance"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.currentTarget.value as AppearancePreference)}
      >
        <option value="system">System</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </label>
  );
}

function AppearanceIcon({ value }: { value: AppearancePreference }) {
  if (value === "light") return <SunMedium size={15} aria-hidden="true" />;
  if (value === "dark") return <MoonStar size={15} aria-hidden="true" />;
  return <SunMoon size={15} aria-hidden="true" />;
}
