import { FileAudio2, FolderClock, FolderOpen, Save } from "lucide-react";
import type { SeparationQuality } from "../domain/types";
import { QualitySelector } from "./QualitySelector";

interface HeaderProps {
  fileName: string | null;
  quality: SeparationQuality;
  disabled: boolean;
  canSaveSession: boolean;
  onImport: () => void;
  onOpenSession: () => void;
  onSaveSession: () => void;
  onQualityChange: (quality: SeparationQuality) => void;
}

export function Header({
  fileName,
  quality,
  disabled,
  canSaveSession,
  onImport,
  onOpenSession,
  onSaveSession,
  onQualityChange,
}: HeaderProps) {
  return (
    <header className="app-header">
      <div className="brand-lockup">
        <div className="brand-icon" aria-hidden="true">
          <span />
          <span />
          <span />
          <span />
        </div>
        <h1>Stem Studio</h1>
        {fileName ? (
          <div className="source-name" title={fileName}>
            <FileAudio2 size={14} />
            <span>{fileName}</span>
          </div>
        ) : null}
      </div>
      <div className="header-actions">
        <div className="session-actions" aria-label="Session controls">
          <button
            className="header-icon-button"
            type="button"
            onClick={onOpenSession}
            disabled={disabled}
            aria-label="Open saved session"
            title="Open saved session"
          >
            <FolderClock size={16} />
          </button>
          <button
            className="header-icon-button"
            type="button"
            onClick={onSaveSession}
            disabled={disabled || !canSaveSession}
            aria-label="Save session"
            title="Save session"
          >
            <Save size={16} />
          </button>
        </div>
        <QualitySelector value={quality} disabled={disabled} onChange={onQualityChange} />
        <button className="import-button" type="button" onClick={onImport} disabled={disabled}>
          <FolderOpen size={16} />
          Import
        </button>
      </div>
    </header>
  );
}
