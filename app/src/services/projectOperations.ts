/** One project import (including its dialog) at a time, until all cancellation work settles. */
export class ProjectOperations {
  private active: { controller: AbortController; finished: boolean; stopping: boolean } | null = null;
  private revision = 0;

  get busy(): boolean { return this.active !== null; }

  get version(): number { return this.revision; }

  begin(): AbortSignal | null {
    if (this.active) return null;
    const controller = new AbortController();
    this.active = { controller, finished: false, stopping: false };
    return controller.signal;
  }

  isCurrent(signal: AbortSignal): boolean {
    return this.active?.controller.signal === signal && !signal.aborted;
  }

  projectChanged(): void { this.revision += 1; }

  finish(signal: AbortSignal): void {
    if (this.active?.controller.signal !== signal) return;
    this.active.finished = true;
    if (!this.active.stopping) this.active = null;
  }

  async cancel(stop: () => Promise<void>): Promise<void> {
    const operation = this.active;
    if (!operation || operation.stopping) return;
    operation.stopping = true;
    operation.controller.abort();
    try {
      await stop();
    } finally {
      operation.stopping = false;
      if (operation.finished && this.active === operation) this.active = null;
    }
  }

  dispose(): void {
    this.active?.controller.abort();
    this.active = null;
    this.projectChanged();
  }
}
