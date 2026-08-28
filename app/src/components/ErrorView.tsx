import { CircleAlert, RotateCcw } from "lucide-react";

interface ErrorViewProps {
  message: string;
  onReset: () => void;
}

export function ErrorView({ message, onReset }: ErrorViewProps) {
  return (
    <main className="error-view">
      <CircleAlert size={28} />
      <h2>Stem separation failed</h2>
      <p>{message}</p>
      <button className="primary-button" type="button" onClick={onReset}>
        <RotateCcw size={16} />
        Try another file
      </button>
    </main>
  );
}

