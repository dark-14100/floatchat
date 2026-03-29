import { describe, it, expect } from "vitest";
import { getColorscale, THERMAL, HALINE, DEEP, DENSE, OXY, MATTER } from "../lib/colorscales";

const all = [
  ["thermal", THERMAL],
  ["haline", HALINE],
  ["deep", DEEP],
  ["dense", DENSE],
  ["oxy", OXY],
  ["matter", MATTER],
] as const;

describe("colorscales", () => {
  it("returns correct array length", () => {
    for (const [name, arr] of all) {
      expect(Array.isArray(arr)).toBe(true);
      expect(arr.length).toBeGreaterThanOrEqual(5);
      expect(getColorscale(name as any)).toEqual(arr);
    }
  });
  it("throws on unknown name", () => {
    expect(() => getColorscale("foo" as any)).toThrow();
  });
});
