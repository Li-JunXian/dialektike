import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ContextCheckpointControl } from "../App";

describe("Context checkpoint control", () => {
  it("keeps the Context summary operable while explaining why draft creation is unavailable", () => {
    const html = renderToStaticMarkup(
      <ContextCheckpointControl
        checkpoints={[]}
        activeCheckpointId={null}
        unavailableReason="Available after the Executor completes a Synthesis for this topic."
        controlsDisabled={false}
        busy={false}
        cancelable={false}
        busyAction={null}
        onDraft={() => undefined}
        onActivate={() => undefined}
        onDeactivate={() => undefined}
        onCancel={() => undefined}
      />,
    );

    expect(html).toContain("<summary>");
    expect(html).not.toMatch(/<summary[^>]*disabled/);
    expect(html).toContain("Available after the Executor completes a Synthesis");
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>.*Create checkpoint draft/s);
  });
});
