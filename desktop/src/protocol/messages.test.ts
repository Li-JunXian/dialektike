import { describe, expect, it } from "vitest";
import canonicalFixture from "../../../tests/fixtures/r0-canonical-response.md?raw";

import {
  SIDECAR_PROTOCOL,
  isEventEnvelope,
  parseCapabilityCatalog,
  parseConversationMessage,
  parseEvidenceSummary,
  parsePermissionRequest,
  parseProjectSummaries,
  parseTopicEvidenceLoaded,
  parseTopicEvidenceUnavailable,
  parseTopicSearchOccurrences,
  parseTopicSummary,
} from "./messages";

describe("project and topic linkage", () => {
  it("parses only bounded project metadata and no filesystem path", () => {
    expect(
      parseProjectSummaries([
        {
          id: "project-1",
          name: "dialektike",
          available: true,
          registered_at: "2026-08-21T12:00:00Z",
        },
      ]),
    ).toEqual([
      {
        id: "project-1",
        name: "dialektike",
        available: true,
        registeredAt: "2026-08-21T12:00:00Z",
      },
    ]);
    expect(
      parseProjectSummaries([
        {
          id: "project-1",
          name: "dialektike",
          available: true,
          path: "/private/project",
        },
      ]),
    ).toBeNull();
  });

  it("maps legacy topics to an explicit unassigned project", () => {
    const base = {
      id: "topic-1",
      title: "Topic",
      pinned: false,
      archived: false,
    };
    expect(parseTopicSummary(base)?.projectId).toBeNull();
    expect(
      parseTopicSummary({ ...base, project_id: "project-1" })?.projectId,
    ).toBe("project-1");
    expect(parseTopicSummary({ ...base, project_id: "" })).toBeNull();
  });
});

describe("versioned sidecar events", () => {
  it("accepts only the pinned protocol discriminator", () => {
    expect(
      isEventEnvelope({
        protocol: SIDECAR_PROTOCOL,
        event: "sidecar.ready",
        payload: {},
      }),
    ).toBe(true);
    expect(
      isEventEnvelope({
        protocol: "dialektike.sidecar.v2",
        event: "sidecar.ready",
        payload: {},
      }),
    ).toBe(false);
  });

  it("requires trusted permission fields and preserves the native payload", () => {
    const nativePayload = {
      tool_use_id: "native-tool-id",
      description: "Write one file",
      suggestions: [{ type: "addDirectory", path: "/tmp/example" }],
    };
    const request = parsePermissionRequest({
      protocol: SIDECAR_PROTOCOL,
      event: "permission.request",
      payload: {
        permission_id: "permission-1",
        runtime_id: "claude-code",
        title: "Write",
        card: "FULL VERBATIM CARD",
        native_payload: nativePayload,
        annotations: { path_confined: false },
      },
    });

    expect(request?.card).toBe("FULL VERBATIM CARD");
    expect(request?.native_payload).toEqual(nativePayload);
    expect(request?.annotations).toEqual({ path_confined: false });
    expect(
      parsePermissionRequest({
        protocol: SIDECAR_PROTOCOL,
        event: "permission.request",
        payload: {
          runtime_id: "claude-code",
          title: "Write",
          card: "FULL VERBATIM CARD",
          native_payload: nativePayload,
          annotations: { path_confined: false },
        },
      }),
    ).toBeNull();
  });

  it("preserves effective authority and rejects unauthoritative settings", () => {
    const message = {
      id: "run:1",
      role: "auditor",
      runtime_id: "claude-code",
      text: "Reviewed.",
      round: 1,
      effective: {
        model: "claude-opus-5",
        effort: "xhigh",
        service_tier: null,
        authority:
          "model: runtime echo; effort: catalog-validated request (not echoed)",
      },
    };

    expect(parseConversationMessage(message)?.effective?.authority).toContain(
      "not echoed",
    );
    const withoutAuthority = {
      ...message,
      effective: { ...message.effective, authority: undefined },
    };
    expect(parseConversationMessage(withoutAuthority)).toBeNull();
  });

  it("preserves only a strict boolean partial-turn marker", () => {
    const message = {
      id: "run:partial",
      role: "executor",
      runtime_id: "codex",
      text: "Interrupted synthesis",
      round: 1,
      stage: "synthesis",
      partial: true,
    };
    expect(parseConversationMessage(message)?.partial).toBe(true);
    expect(parseConversationMessage({ ...message, partial: "true" })).toBeNull();
  });

  it("preserves ordered structured blocks and makes unsafe citations inert", () => {
    const base = {
      id: "run:blocks",
      participant_id: "executor-1",
      role: "executor",
      runtime_id: "codex",
      stage: "proposal",
      text: "Firstcode-diffsource",
      round: 1,
      cycle: 1,
    };
    const blocks = [
      { type: "markdown", text: "**First**" },
      { type: "code", code: "const safe = true;", language: "ts", title: "code" },
      { type: "diff", diff: "+ safe", title: "code-diff" },
      { type: "citation", label: "source", url: "https://example.com/source" },
    ];

    expect(parseConversationMessage({ ...base, blocks })?.blocks).toEqual(blocks);
    const unsafe = parseConversationMessage({
      ...base,
      blocks: [{ type: "citation", label: "unsafe", url: "javascript:alert(1)" }],
    });
    expect(unsafe?.blocks).toEqual([{ type: "unknown", sourceType: "citation", label: "Unsupported provider content", text: "unsafe" }]);
    expect(JSON.stringify(unsafe)).not.toContain("javascript:");
  });

  it("preserves the shared canonical UTF-8 fixture through the JSON parser", () => {
    const parsed = parseConversationMessage({
      id: "run:canonical",
      participant_id: "executor-1",
      role: "executor",
      runtime_id: "codex",
      stage: "synthesis",
      text: canonicalFixture,
      blocks: [{ type: "markdown", text: canonicalFixture }],
      round: 1,
      cycle: 1,
    });

    expect(new TextEncoder().encode(canonicalFixture)).toHaveLength(3783);
    expect(parsed?.text).toBe(canonicalFixture);
    expect(parsed?.blocks).toEqual([{ type: "markdown", text: canonicalFixture }]);
    expect(parsed?.text.endsWith("trailing spaces remain  \n")).toBe(true);
  });

  it("parses the backend-authoritative occurrence wire without renaming fields", () => {
    const occurrence = {
      occurrence_id: "topic.synthetic:title:match:1",
      topic_id: "topic.synthetic",
      topic_title: "Synthetic topic",
      archived: false,
      source_kind: "title",
      source_anchor: "topic:topic.synthetic:title",
      source_field: "title",
      stage: null,
      speaker: "Live",
      timestamp: "2026-08-11T00:00:00Z",
      match_start_utf8: 0,
      match_end_utf8: 9,
      snippet_segments: [{ text: "Synthetic", highlighted: true }],
      prefix_truncated: false,
      suffix_truncated: true,
    };

    expect(parseTopicSearchOccurrences([occurrence])?.[0]).toMatchObject({
      occurrenceId: occurrence.occurrence_id,
      speaker: "Live",
      prefixTruncated: false,
      suffixTruncated: true,
    });
    expect(parseTopicSearchOccurrences([{ ...occurrence, prefix_truncated: undefined }])).toBeNull();
  });
});

describe("capability evidence", () => {
  function syntheticProvider() {
    return {
      runtime_id: "unexpected.runtime-7",
      descriptor: {
        schema_version: 1,
        descriptor_version: 1,
        runtime_id: "unexpected.runtime-7",
        vendor_id: "verdant-labs",
        agent_system_id: "agent-system-42",
        relay_provider_id: "unexpected-relay",
        display: {
          name: "Unexpected Runtime",
          short_name: "Unexpected",
          mark: "U",
          icon_token: "provider",
          accent_token: "verdant",
        },
        authentication: {
          label: "Synthetic subscription",
          authority: "adapter-authenticated-discovery",
          not_observable_label: "Authentication not observable",
        },
        version_evidence: {
          label: "Synthetic runtime",
          authority: "adapter-runtime-probe",
          not_observable_label: "Version not observable",
        },
        default_selection: {
          model: null,
          effort: null,
          service_tier: null,
          execution_profile: "governed",
        },
        control_schema: [
          {
            control_id: "response-style",
            label: "Response style",
            group: "turn",
            kind: "select",
            description: "A synthetic provider turn control.",
            authority: "runtime-contract",
            default: "lucid",
            options: [
              {
                value: "lucid",
                label: "Lucid",
                availability: { available: true, reason: null },
              },
              {
                value: "orbital",
                label: "Orbital",
                availability: {
                  available: false,
                  reason: "Not included in this subscription",
                },
              },
            ],
            min_value: null,
            max_value: null,
          },
          {
            control_id: "network-access",
            label: "Network access",
            group: "execution",
            kind: "boolean",
            description: "A synthetic execution control.",
            authority: "runtime-contract",
            default: false,
            options: [],
            min_value: null,
            max_value: null,
          },
        ],
        supported_content_types: ["markdown", "code"],
        execution_profiles: [
          {
            profile_id: "governed",
            label: "Governed",
            description: "Use the reviewed synthetic profile.",
            availability: { available: true, reason: null },
            values: { "network-access": false },
          },
        ],
        runtime_facilities: [
          {
            facility_id: "memory",
            label: "Memory",
            description: "Runtime-managed memory.",
            observability: "not-observable",
            management: "runtime-native",
          },
        ],
        permission_presentations: [
          {
            request_kind: "native/approval",
            title: "Native approval",
            layout: "generic",
            fields: [
              {
                field_id: "operation",
                label: "Operation",
                pointer: "/operation",
                format: "text",
              },
            ],
          },
        ],
        connect: {
          label: "Connect Unexpected Runtime",
          help_text: "Authenticate this reviewed runtime.",
          action: "refresh-capabilities",
        },
      },
      availability: { available: true, reason: null },
      account_route: "synthetic-subscription",
      runtime_version: "synthetic-7",
      models: [
        {
          id: "synthetic-model",
          label: "Synthetic Model",
          availability: { available: true },
          explicit_selectable: true,
          efforts: [
            {
              id: "deliberate",
              label: "Deliberate",
              availability: { available: true },
            },
          ],
          service_tiers: [],
        },
      ],
    };
  }

  it("parses an unanticipated opaque provider and its descriptor controls", () => {
    const catalog = parseCapabilityCatalog([syntheticProvider()]);
    const provider = catalog?.["unexpected.runtime-7"];

    expect(provider?.descriptor.vendorId).toBe("verdant-labs");
    expect(provider?.descriptor.agentSystemId).toBe("agent-system-42");
    expect(provider?.descriptor.controlSchema).toMatchObject([
      {
        controlId: "response-style",
        group: "turn",
        defaultValue: "lucid",
      },
      {
        controlId: "network-access",
        group: "execution",
        defaultValue: false,
      },
    ]);
    expect(provider?.descriptor.executionProfiles[0]).toMatchObject({
      profileId: "governed",
      values: { "network-access": false },
    });
    expect(provider?.models[0].id).toBe("synthetic-model");
  });

  it("accepts a positive reviewed descriptor revision without changing the wire schema", () => {
    const provider = syntheticProvider();
    provider.descriptor.descriptor_version = 2;

    expect(parseCapabilityCatalog([provider])?.["unexpected.runtime-7"].descriptor.descriptorVersion).toBe(2);
  });

  it("rejects non-opaque synthetic runtime and vendor identities", () => {
    const invalidRuntime = syntheticProvider();
    invalidRuntime.runtime_id = "unexpected_runtime";
    invalidRuntime.descriptor.runtime_id = "unexpected_runtime";
    expect(parseCapabilityCatalog([invalidRuntime])).toBeNull();

    const invalidVendor = syntheticProvider();
    invalidVendor.descriptor.vendor_id = "verdant_labs";
    expect(parseCapabilityCatalog([invalidVendor])).toBeNull();
  });

  it("rejects unavailable options without a reason", () => {
    const catalog = {
      codex: {
        runtime_id: "codex",
        account_route: "chatgpt",
        runtime_version: "0.139.0",
        models: [
          {
            id: "gpt-5.6-sol",
            label: "GPT-5.6 Sol",
            availability: { available: true },
            efforts: [
              {
                id: "ultra",
                label: "Ultra",
                availability: { available: false },
              },
            ],
            service_tiers: [],
          },
        ],
      },
    };
    expect(parseCapabilityCatalog(catalog)).toBeNull();
  });
});

describe("bounded run evidence", () => {
  function summary() {
    return {
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
        audit_counts: { native_auto_permitted: 2 },
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
        record_count: 3,
        head_sha256: "a".repeat(64),
        error: null,
      },
      event_log_readable: true,
    };
  }

  it("accepts the inert summary and preserves the verified head", () => {
    const parsed = parseEvidenceSummary(summary());

    expect(parsed?.decision_chain.head_sha256).toBe("a".repeat(64));
    expect(parsed?.raw_capture.contents_exposed).toBe(false);
    expect(parsed?.governance.permission_decisions?.allow).toBe(1);
  });

  it("rejects exposure claims and inconsistent chain-derived counts", () => {
    expect(
      parseEvidenceSummary({
        ...summary(),
        raw_capture: {
          ...summary().raw_capture,
          contents_exposed: true,
        },
      }),
    ).toBeNull();
    expect(
      parseEvidenceSummary({
        ...summary(),
        decision_chain: {
          verified: false,
          record_count: null,
          head_sha256: null,
          error: "failed",
        },
      }),
    ).toBeNull();
  });

  it("binds a reloaded evidence summary to its topic event", () => {
    const loaded = parseTopicEvidenceLoaded({
      topic_id: "topic-1",
      summary: summary(),
    });
    expect(loaded?.topicId).toBe("topic-1");
    expect(loaded?.summary.run_id).toBe("run-1");

    expect(parseTopicEvidenceLoaded({ topic_id: "topic-1", summary: {} })).toBeNull();
    expect(
      parseTopicEvidenceUnavailable({
        topic_id: "topic-1",
        message: "No saved governance evidence is available for this topic.",
      }),
    ).toEqual({
      topicId: "topic-1",
      message: "No saved governance evidence is available for this topic.",
    });
  });
});
