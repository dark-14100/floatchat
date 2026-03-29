// cmocean colorscales for FloatChat — hand-coded for Plotly
// See: https://matplotlib.org/cmocean/
// Each scale is a Plotly-compatible [number, string][] array (0-1, hex)

import type { ColorscaleName } from "../types/visualization";
import type { ColorScale } from "plotly.js";

// THERMAL (blue → yellow → red)
export const THERMAL: ColorScale = [
  [0.0, "#0b3c5d"],
  [0.15, "#328cc1"],
  [0.3, "#d9b310"],
  [0.5, "#f4e285"],
  [0.7, "#fa7e23"],
  [1.0, "#c02942"],
];

// HALINE (blue → cyan → white)
export const HALINE: ColorScale = [
  [0.0, "#003366"],
  [0.2, "#336699"],
  [0.4, "#66cccc"],
  [0.7, "#e0f7fa"],
  [1.0, "#ffffff"],
];

// DEEP (navy → teal → white)
export const DEEP: ColorScale = [
  [0.0, "#011f4b"],
  [0.2, "#03396c"],
  [0.4, "#005b96"],
  [0.7, "#6497b1"],
  [1.0, "#b3cde0"],
];

// DENSE (purple → blue → white)
export const DENSE: ColorScale = [
  [0.0, "#3f007d"],
  [0.2, "#54278f"],
  [0.4, "#6a51a3"],
  [0.7, "#807dba"],
  [1.0, "#f2f0f7"],
];

// OXY (blue → green → yellow)
export const OXY: ColorScale = [
  [0.0, "#253494"],
  [0.2, "#2c7fb8"],
  [0.4, "#41b6c4"],
  [0.7, "#a1dab4"],
  [1.0, "#ffffcc"],
];

// MATTER (brown → tan → white)
export const MATTER: ColorScale = [
  [0.0, "#7f3b08"],
  [0.2, "#b35806"],
  [0.4, "#f1a340"],
  [0.7, "#fee0b6"],
  [1.0, "#fff7fb"],
];

export function getColorscale(name: ColorscaleName): ColorScale {
  switch (name) {
    case "thermal": return THERMAL;
    case "haline": return HALINE;
    case "deep": return DEEP;
    case "dense": return DENSE;
    case "oxy": return OXY;
    case "matter": return MATTER;
    default:
      throw new Error(`Unknown colorscale: ${name}`);
  }
}

// ── Variable → colorscale mapping ─────────────────────────────────────────

export const COLORSCALE_FOR_VARIABLE: Record<string, ColorScale> = {
  temperature: THERMAL,
  temp: THERMAL,
  salinity: HALINE,
  psal: HALINE,
  pressure: DEEP,
  pres: DEEP,
  dissolved_oxygen: OXY,
  chlorophyll: MATTER,
};

// ── Map constants ─────────────────────────────────────────────────────────

/** Indian Ocean centroid — default map center for ARGO data. */
export const DEFAULT_MAP_CENTER: [number, number] = [20.0, 60.0];

/** Default zoom level for map components. */
export const DEFAULT_MAP_ZOOM = 4;
