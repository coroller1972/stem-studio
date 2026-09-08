import { afterEach, expect, it, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { TauriSeparationService } from "./separationService";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));
afterEach(() => vi.clearAllMocks());

it("does not launch the engine if cancelled while registering progress events", async () => {
  let registered!: (unlisten: () => void) => void;
  vi.mocked(listen).mockReturnValue(new Promise((resolve) => { registered = resolve; }));
  const controller = new AbortController();
  const service = new TauriSeparationService();
  const result = expect(service.separate("/bass.wav", "standard", vi.fn(), controller.signal)).rejects.toMatchObject({ name: "AbortError" });
  controller.abort();
  const unlisten = vi.fn();
  registered(unlisten);
  await result;
  expect(invoke).not.toHaveBeenCalled();
  expect(unlisten).toHaveBeenCalledOnce();
});
