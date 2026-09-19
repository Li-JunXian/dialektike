import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { RunStatusSurface } from "./RunStatusSurface";

describe("compact run status surfaces", () => {
  it("keeps active governance state persistent without a full-width header row", () => {
    const html = renderToStaticMarkup(
      <RunStatusSurface
        persistent={{ tone: "permission", message: "Waiting for Live's permission decision" }}
        toast={null}
        onDismissToast={() => undefined}
      />,
    );
    expect(html).toContain("run-status-banner--permission");
    expect(html).toContain('role="status"');
    expect(html).toContain("Waiting for Live&#x27;s permission decision");
    expect(html).not.toContain("status-toast");
  });

  it("announces completion as a transient toast", () => {
    const html = renderToStaticMarkup(
      <RunStatusSurface
        persistent={null}
        toast="Cycle completed and saved"
        onDismissToast={() => undefined}
      />,
    );
    expect(html).toContain("status-toast");
    expect(html).toContain("Cycle completed and saved");
    expect(html).not.toContain("run-status-banner");
  });

  it("uses an assertive alert for a failure", () => {
    const html = renderToStaticMarkup(
      <RunStatusSurface
        persistent={{ tone: "error", message: "The run failed safely" }}
        toast={null}
        onDismissToast={() => undefined}
      />,
    );
    expect(html).toContain('role="alert"');
    expect(html).toContain('aria-live="assertive"');
  });

  it("offers an explicit recovery action without implying an automatic retry", () => {
    const html = renderToStaticMarkup(
      <RunStatusSurface
        persistent={{ tone: "error", message: "Governance core unavailable", actionLabel: "Retry governance core" }}
        toast={null}
        onPersistentAction={() => undefined}
        onDismissToast={() => undefined}
      />,
    );
    expect(html).toContain("Retry governance core");
    expect(html).not.toContain("Dismiss status");
  });
});
