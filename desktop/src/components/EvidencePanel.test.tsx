import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { EvidenceSummary } from "../protocol/messages";
import { EvidencePanel } from "./EvidencePanel";

describe("read-only evidence panel", () => {
  it("renders gates, counts, capture inventory, and the verified chain head", () => {
    const evidence: EvidenceSummary = {
      schema_version: 1,
      run_id: "run-1",
      run_status: "completed",
      environment_gate: {
        verified: true,
        policy: "allowlist",
        kept: ["HOME", "PATH"],
        dropped_count: 12,
      },
      runtime_gates: [
        {
          runtime_id: "codex",
          catalog_verified: true,
          account_route: "chatgpt:plus",
          runtime_version: "0.145.0",
          turn_revalidated_count: 1,
          model_providers: ["openai"],
        },
      ],
      rate_limits: {
        observed_event_count: 2,
        by_runtime: { codex: 2 },
        warning_count: 0,
        warnings: [],
        capture_parse_failures: 0,
      },
      governance: {
        derived_from_verified_chain: true,
        permission_decisions: { allow: 1, deny: 0, total: 1 },
        audit_counts: { native_auto_permitted: 2, tool_failed: 1 },
      },
      raw_capture: {
        file_count: 3,
        total_bytes: 1234,
        turns_with_capture: 1,
        by_category: { "runtime-events": 1, "permission-payload": 2 },
        contents_exposed: false,
      },
      decision_chain: {
        verified: true,
        record_count: 4,
        head_sha256: "b".repeat(64),
        error: null,
      },
      event_log_readable: true,
    };

    const html = renderToStaticMarkup(
      <EvidencePanel evidence={evidence} source="saved-topic" />,
    );

    expect(html).toContain("Latest run evidence");
    expect(html).toContain("Loaded from the latest saved closed run for this topic");
    expect(html).toContain("Runtime and account gates");
    expect(html).toContain("Environment scrub:");
    expect(html).toContain("HOME, PATH");
    expect(html).toContain("chatgpt:plus");
    expect(html).toContain("Native provider:");
    expect(html).toContain("Permission decisions");
    expect(html).toContain("Inventory only");
    expect(html).toContain("4 decision records verified");
    expect(html).toContain("b".repeat(64));
    expect(html).not.toContain("raw payload content</pre>");
  });

  it("distinguishes a saved-evidence lookup from evidence received in the current session", () => {
    const loading = renderToStaticMarkup(<EvidencePanel evidence={null} source="loading" />);
    expect(loading).toContain("Loading the latest saved closed-run evidence");
    expect(loading).toContain("Please wait while saved evidence is checked");

    const unavailable = renderToStaticMarkup(<EvidencePanel evidence={null} source="unavailable" />);
    expect(unavailable).toContain("No latest closed-run evidence is available");

    const unreadable = renderToStaticMarkup(
      <EvidencePanel evidence={null} source="unavailable" unavailableMessage="The latest saved run exists, but its evidence is unavailable." />,
    );
    expect(unreadable).toContain("latest saved run exists");
  });
});
