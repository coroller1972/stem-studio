import type { SeparationQuality } from "../domain/types";

interface QualitySelectorProps {
  value: SeparationQuality;
  disabled: boolean;
  onChange: (quality: SeparationQuality) => void;
}

const QUALITY_OPTIONS: ReadonlyArray<{
  value: SeparationQuality;
  label: string;
  description: string;
}> = [
  { value: "standard", label: "Standard", description: "Faster local separation" },
  { value: "high", label: "High", description: "Higher quality, slower processing" },
];

export function QualitySelector({ value, disabled, onChange }: QualitySelectorProps) {
  return (
    <div className="quality-selector" role="group" aria-label="Separation quality">
      {QUALITY_OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          className={value === option.value ? "is-active" : ""}
          aria-pressed={value === option.value}
          title={option.description}
          disabled={disabled}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
