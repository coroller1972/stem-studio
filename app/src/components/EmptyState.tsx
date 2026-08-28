import { AudioLines, Upload } from "lucide-react";

interface EmptyStateProps {
  isDragging: boolean;
  onImport: () => void;
}

export function EmptyState({ isDragging, onImport }: EmptyStateProps) {
  return (
    <main className={`empty-state ${isDragging ? "is-dragging" : ""}`}>
      <div className="empty-visual" aria-hidden="true">
        <AudioLines size={30} />
      </div>
      <h2>{isDragging ? "Drop to separate" : "Open an audio file"}</h2>
      <p>Drop an MP3 or WAV here, or choose a file to separate it into four stems.</p>
      <button className="primary-button" type="button" onClick={onImport}>
        <Upload size={17} />
        Choose audio file
      </button>
      <span className="format-note">MP3 · WAV</span>
    </main>
  );
}

