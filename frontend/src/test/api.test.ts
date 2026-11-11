import { describe, expect, it } from "vitest";
import { api, ApiError, qs, rowsToCsv } from "../api";
import { mockFetch } from "./helpers";

describe("qs", () => {
  it("drops empty and ALL values", () => {
    expect(qs({ a: "1", b: undefined, c: "", d: "ALL", e: null })).toBe("?a=1");
    expect(qs({})).toBe("");
  });
  it("encodes values", () => expect(qs({ s: "a b&c" })).toBe("?s=a+b%26c"));
});

describe("rowsToCsv", () => {
  it("escapes quotes, commas and newlines and unions columns", () => {
    const csv = rowsToCsv([{ a: 'x,"y"', b: 1 }, { a: "line\nbreak", c: true }], "LABEL");
    expect(csv.split("\n")[0]).toBe("# LABEL");
    expect(csv).toContain("a,b,c");
    expect(csv).toContain('"x,""y""",1,');
    expect(csv).toContain('"line\nbreak",,true');
  });
  it("returns empty string for no rows", () => expect(rowsToCsv([])).toBe(""));
});

describe("api", () => {
  it("throws ApiError with server detail", async () => {
    mockFetch({ "/x": [403, { detail: "missing permission" }] });
    await expect(api("/x")).rejects.toMatchObject({ status: 403, message: "missing permission" });
  });
  it("formats validation problems", async () => {
    mockFetch({ "/v": [422, { detail: { message: "invalid input", problems: ["missing col a"] } }] });
    const e = (await api("/v").catch((x: unknown) => x)) as ApiError;
    expect(e.message).toBe("invalid input: missing col a");
  });
  it("returns JSON on success", async () => {
    mockFetch({ "/ok": { a: 1 } });
    expect(await api("/ok")).toEqual({ a: 1 });
  });
});
