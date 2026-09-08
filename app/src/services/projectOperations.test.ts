import { describe, expect, it } from "vitest";
import { ProjectOperations } from "./projectOperations";

describe("project operations", () => {
  it("keeps the gate locked until both cancellation and original work finish", async () => {
    const gate = new ProjectOperations();
    const signal = gate.begin()!;
    let stopped!: () => void;
    const cancelling = gate.cancel(() => new Promise<void>((resolve) => { stopped = resolve; }));
    expect(gate.isCurrent(signal)).toBe(false);
    gate.finish(signal);
    expect(gate.begin()).toBeNull();
    stopped();
    await cancelling;
    expect(gate.begin()).not.toBeNull();
  });

  it("keeps the gate locked if the backend acknowledges cancellation before the load settles", async () => {
    const gate = new ProjectOperations();
    const signal = gate.begin()!;
    await gate.cancel(async () => {});
    expect(gate.begin()).toBeNull();
    gate.finish(signal);
    const replacement = gate.begin()!;
    gate.finish(signal);
    expect(gate.isCurrent(replacement)).toBe(true);
  });
});
