import { describe, expect, it } from "vitest";
import { assignStemFiles, stemFromFileName } from "./stemFiles";

const named = (...names: string[]) => names.map((name) => ({ name }));

describe("stem file assignment", () => {
  it("maps exported stems and keeps the shared song name", () => {
    const result = assignStemFiles(named("My Song - vocals.m4a", "My Song - drums.m4a", "My Song - bass.m4a", "My Song - other.m4a"));
    expect(result).toMatchObject({
      ok: true,
      sourceName: "My Song",
      files: { vocals: { name: "My Song - vocals.m4a" }, bass: { name: "My Song - bass.m4a" } },
    });
  });

  it("lets the last stem word win over a title that contains one", () => {
    expect(stemFromFileName("All About That Bass - vocals.m4a")).toBe("vocals");
    expect(stemFromFileName("Bassline_other.wav")).toBe("other");
    expect(stemFromFileName("batterie.mp3")).toBe("drums");
    expect(stemFromFileName("cover.jpg")).toBeNull();
  });

  it("explains a missing or duplicated stem", () => {
    expect(assignStemFiles(named("vocals.wav", "drums.wav", "bass.wav"))).toEqual({
      ok: false,
      message: "Missing other. Pick four files named with vocals, drums, bass and other.",
    });
    expect(assignStemFiles(named("a-bass.wav", "b-bass.wav"))).toMatchObject({ ok: false, message: "Two files look like the bass stem." });
  });

  it("falls back to a generic name when the files share none", () => {
    const result = assignStemFiles(named("vocals.wav", "drums.wav", "bass.wav", "other.wav"));
    expect(result.ok && result.sourceName).toBe("Session");
  });
});
