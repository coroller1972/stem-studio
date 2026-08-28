import { LoaderCircle, X } from "lucide-react";
import type { SeparationQuality } from "../domain/types";

interface ProcessingViewProps {
  fileName: string;
  progress: number;
  message: string;
  quality: SeparationQuality;
  onCancel: (() => void) | null;
}

export function ProcessingView({ fileName, progress, message, quality, onCancel }: ProcessingViewProps) {
  const percent = Math.round(progress * 100);
  return (
    <main className="processing-view">
      <div className="processing-heading">
        <LoaderCircle className="spin" size={19} />
        <div>
          <h2>Separating stems</h2>
          <p>{fileName}</p>
        </div>
        <strong>{percent}%</strong>
      </div>
      <div
        className="progress-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <span style={{ width: `${percent}%` }} />
      </div>
      <div className="processing-footer">
        <span>{message}</span>
        {onCancel ? (
          <button type="button" className="ghost-button" onClick={onCancel}>
            <X size={15} />
            Cancel
          </button>
        ) : null}
      </div>
      <p className="processing-note">
        {quality === "high"
          ? "High quality is slower and downloads its model on first use."
          : "Stem Studio can stay in the background while separation is running."}
      </p>
    </main>
  );
}
