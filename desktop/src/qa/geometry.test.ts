import { describe, expect, it } from "vitest";

import {
  evaluateWorkspaceGeometry,
  geometryAcceptanceViewports,
  type GeometryMeasurement,
} from "./geometry";

function measurement(overrides: Partial<GeometryMeasurement> = {}): GeometryMeasurement {
  return {
    workspaceCenter: 894,
    liveSeatCenter: 894,
    livePromptCenters: [894],
    composerCenter: 894,
    gutterCenter: 894,
    executorInnerGutter: 34,
    auditorInnerGutter: 34,
    horizontalOverflow: 0,
    ...overrides,
  };
}

describe("packaged geometry evaluation", () => {
  it("accepts the one-pixel centre and mirrored-gutter tolerance", () => {
    expect(evaluateWorkspaceGeometry(measurement({ liveSeatCenter: 893, auditorInnerGutter: 35 }))).toEqual({
      passed: true,
      maximumCenterDrift: 1,
      gutterDifference: 1,
      horizontalOverflow: 0,
    });
  });

  it("enumerates the complete packaged viewport acceptance matrix", () => {
    const viewports = geometryAcceptanceViewports();
    const keys = new Set(viewports.map(({ width, height }) => `${width}x${height}`));
    expect(keys).toContain("720x640");
    expect(keys).toContain("879x820");
    expect(keys).toContain("880x820");
    expect(keys).toContain("881x820");
    expect(keys).toContain("1079x820");
    expect(keys).toContain("1080x820");
    expect(keys).toContain("1081x820");
    expect(keys).toContain("880x720");
    expect(keys).toContain("1180x820");
    expect(keys).toContain("1488x1058");
    expect(keys).toContain("3840x820");
    for (let width = 720; width <= 3840; width += 20) {
      expect(keys).toContain(`${width}x820`);
    }
  });

  it("rejects centre drift, asymmetric gutters, and horizontal overflow", () => {
    expect(evaluateWorkspaceGeometry(measurement({ composerCenter: 896 })).passed).toBe(false);
    expect(evaluateWorkspaceGeometry(measurement({ auditorInnerGutter: 36 })).passed).toBe(false);
    expect(evaluateWorkspaceGeometry(measurement({ horizontalOverflow: 2 })).passed).toBe(false);
  });
});
