export interface GeometryMeasurement {
  workspaceCenter: number;
  liveSeatCenter: number;
  livePromptCenters: number[];
  composerCenter: number;
  gutterCenter: number | null;
  executorInnerGutter: number | null;
  auditorInnerGutter: number | null;
  horizontalOverflow: number;
}

export interface GeometryEvaluation {
  passed: boolean;
  maximumCenterDrift: number;
  gutterDifference: number;
  horizontalOverflow: number;
}

export interface GeometryViewport {
  width: number;
  height: number;
  reason: "sweep" | "minimum" | "breakpoint" | "reference";
}

export const GEOMETRY_MINIMUM_WIDTH = 720;
export const GEOMETRY_MAXIMUM_WIDTH = 3840;
export const GEOMETRY_SWEEP_STEP = 20;
export const GEOMETRY_BREAKPOINTS = [880, 1080] as const;

export function geometryAcceptanceViewports(): GeometryViewport[] {
  const viewports = new Map<string, GeometryViewport>();
  const add = (viewport: GeometryViewport) => viewports.set(`${viewport.width}x${viewport.height}`, viewport);

  for (let width = GEOMETRY_MINIMUM_WIDTH; width <= GEOMETRY_MAXIMUM_WIDTH; width += GEOMETRY_SWEEP_STEP) {
    add({ width, height: 820, reason: "sweep" });
  }
  add({ width: 720, height: 640, reason: "minimum" });
  for (const breakpoint of GEOMETRY_BREAKPOINTS) {
    for (const width of [breakpoint - 1, breakpoint, breakpoint + 1]) {
      add({ width, height: 820, reason: "breakpoint" });
    }
  }
  add({ width: 880, height: 720, reason: "reference" });
  add({ width: 1180, height: 820, reason: "reference" });
  add({ width: 1488, height: 1058, reason: "reference" });
  return [...viewports.values()].sort((left, right) => left.width - right.width || left.height - right.height);
}

export function measureWorkspaceGeometry(root: ParentNode = document): GeometryMeasurement {
  const workspace = requiredElement(root, '[data-geometry="workspace"]');
  const liveSeat = requiredElement(root, '[data-geometry="live-seat"]');
  const composer = requiredElement(root, '[data-geometry="live-composer"]');
  const executor = root.querySelector<HTMLElement>('[data-geometry="executor-lane"]');
  const auditor = root.querySelector<HTMLElement>('[data-geometry="auditor-lane"]');
  const prompts = Array.from(root.querySelectorAll<HTMLElement>('[data-geometry="live-prompt"]'));
  const workspaceRect = workspace.getBoundingClientRect();
  const executorRect = executor?.getBoundingClientRect();
  const auditorRect = auditor?.getBoundingClientRect();
  const workspaceCenter = center(workspaceRect);
  const gutterCenter = executorRect && auditorRect ? (executorRect.right + auditorRect.left) / 2 : null;
  return {
    workspaceCenter,
    liveSeatCenter: center(liveSeat.getBoundingClientRect()),
    livePromptCenters: prompts.map((prompt) => center(prompt.getBoundingClientRect())),
    composerCenter: center(composer.getBoundingClientRect()),
    gutterCenter,
    executorInnerGutter: executorRect ? workspaceCenter - executorRect.right : null,
    auditorInnerGutter: auditorRect ? auditorRect.left - workspaceCenter : null,
    horizontalOverflow: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
  };
}

export function evaluateWorkspaceGeometry(
  measurement: GeometryMeasurement,
  tolerance = 1,
): GeometryEvaluation {
  const centers = [
    measurement.liveSeatCenter,
    measurement.composerCenter,
    ...measurement.livePromptCenters,
    ...(measurement.gutterCenter === null ? [] : [measurement.gutterCenter]),
  ];
  const maximumCenterDrift = centers.reduce(
    (maximum, value) => Math.max(maximum, Math.abs(value - measurement.workspaceCenter)),
    0,
  );
  const gutterDifference = measurement.executorInnerGutter === null || measurement.auditorInnerGutter === null
    ? 0
    : Math.abs(measurement.executorInnerGutter - measurement.auditorInnerGutter);
  return {
    passed: maximumCenterDrift <= tolerance && gutterDifference <= tolerance && measurement.horizontalOverflow <= tolerance,
    maximumCenterDrift,
    gutterDifference,
    horizontalOverflow: measurement.horizontalOverflow,
  };
}

function requiredElement(root: ParentNode, selector: string): HTMLElement {
  const element = root.querySelector<HTMLElement>(selector);
  if (!element) throw new Error(`Geometry probe could not find ${selector}.`);
  return element;
}

function center(rect: Pick<DOMRect, "left" | "width">): number {
  return rect.left + rect.width / 2;
}
