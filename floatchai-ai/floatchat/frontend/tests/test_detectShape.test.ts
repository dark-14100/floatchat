import { describe, it, expect } from "vitest";
import { detectShape } from "../lib/detectShape";

describe("detectShape", () => {
  it("detects float_trajectory_map", () => {
    const cols = ["latitude", "longitude", "juld"];
    expect(detectShape(cols, [{}])).toEqual({ primary: "float_trajectory_map" });
  });
  it("detects float_position_map", () => {
    const cols = ["lat", "lon"];
    expect(detectShape(cols, [{}])).toEqual({ primary: "float_position_map" });
  });
  it("detects salinity_overlay", () => {
    const cols = ["temperature", "salinity", "pressure"];
    expect(detectShape(cols, [{}])).toEqual({ primary: "salinity_overlay", secondary: "ts_diagram" });
  });
  it("detects ts_diagram", () => {
    const cols = ["temp", "psal"];
    expect(detectShape(cols, [{}])).toEqual({ primary: "ts_diagram" });
  });
  it("detects ocean_profile", () => {
    const cols = ["depth", "oxygen"];
    const rows = [{ depth: 10, oxygen: 5.2 }];
    expect(detectShape(cols, rows)).toEqual({ primary: "ocean_profile" });
  });
  it("detects time_series", () => {
    const cols = ["timestamp", "chlorophyll"];
    const rows = [{ timestamp: "2024-01-01", chlorophyll: 1.2 }];
    expect(detectShape(cols, rows)).toEqual({ primary: "time_series" });
  });
  it("returns null for no match", () => {
    const cols = ["foo", "bar"];
    expect(detectShape(cols, [{}])).toEqual({ primary: null });
  });
});
