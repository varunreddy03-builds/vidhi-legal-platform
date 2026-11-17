import { describe, expect, it } from "vitest";
import { isLanguage, LANGUAGE_BY_CODE, LANGUAGES } from "./languages";

describe("the language list", () => {
  it("is English plus the 22 languages of the Eighth Schedule", () => {
    expect(LANGUAGES).toHaveLength(23);
    expect(LANGUAGES[0].code).toBe("en");
  });

  it("has unique codes and a native name for each", () => {
    expect(new Set(LANGUAGES.map((l) => l.code)).size).toBe(LANGUAGES.length);
    for (const l of LANGUAGES) {
      expect(l.native.trim(), l.code).not.toBe("");
      expect(l.english.trim(), l.code).not.toBe("");
    }
  });

  it("reads right to left only for the languages written in the Arabic script", () => {
    expect(LANGUAGES.filter((l) => l.dir === "rtl").map((l) => l.code).sort()).toEqual(["ks", "sd", "ur"]);
  });

  it("marks only English as needing no font download", () => {
    expect(LANGUAGES.filter((l) => !l.font).map((l) => l.code)).toEqual(["en"]);
  });

  it("only calls a language fully translated or core", () => {
    for (const l of LANGUAGES) expect(["full", "core"]).toContain(l.quality);
    expect(LANGUAGE_BY_CODE.get("hi")?.quality).toBe("full");
    expect(LANGUAGE_BY_CODE.get("sat")?.quality).toBe("core");
  });
});

describe("isLanguage", () => {
  it.each([["en", true], ["te", true], ["xx", false], ["", false], [null, false], [undefined, false]])("%j -> %s", (code, expected) => {
    expect(isLanguage(code as string | null | undefined)).toBe(expected);
  });
});
