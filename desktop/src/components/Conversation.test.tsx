import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Conversation } from "./Conversation";

describe("conversation runtime evidence", () => {
  it("shows the authority that distinguishes echoes from accepted requests", () => {
    const html = renderToStaticMarkup(
      <Conversation
        messages={[
          {
            id: "run:1",
            role: "auditor",
            runtime_id: "claude-code",
            text: "Review complete.",
            round: 1,
            effective: {
              model: "claude-opus-5",
              effort: "xhigh",
              serviceTier: null,
              authority:
                "model: runtime echo; effort: catalog-validated request (not echoed)",
            },
          },
        ]}
      />,
    );

    expect(html).toContain("Runtime evidence:");
    expect(html).toContain("Authority:");
    expect(html).toContain("not echoed");
  });

  it("keeps completed turn labels bound to their saved runtime evidence after a seat swap", () => {
    const html = renderToStaticMarkup(
      <Conversation
        runtimeNames={{
          "executor-seat": "Claude Code · Claude Opus 5 · xhigh",
        }}
        runtimeDisplayNames={{ codex: "Codex" }}
        messages={[
          {
            id: "historical-proposal",
            participant_id: "executor-seat",
            role: "executor",
            runtime_id: "codex",
            stage: "proposal",
            text: "Saved before the seat swap.",
            round: 1,
            effective: {
              model: "gpt-5.6-sol",
              effort: "ultra",
              serviceTier: null,
              authority: "runtime echo",
            },
          },
        ]}
      />,
    );

    expect(html).toContain("Codex · gpt-5.6-sol · ultra");
    expect(html).not.toContain("Claude Code · Claude Opus 5 · xhigh");
  });

  it("preserves provider Markdown as semantic, inert response content", () => {
    const html = renderToStaticMarkup(
      <Conversation
        livePrompt="Review this."
        messages={[
          {
            id: "run:proposal",
            participant_id: "codex-executor",
            role: "executor",
            runtime_id: "codex",
            stage: "proposal",
            text: [
              "### Plan",
              "",
              "- Preserve **emphasis**",
              "- Preserve `inline code`",
              "",
              "```ts",
              "const safe = true;",
              "```",
              "",
              "$$E = mc^2$$",
              "",
              "<script>alert('never execute')</script>",
            ].join("\n"),
            round: 1,
          },
        ]}
      />,
    );

    expect(html).toContain("<h3>Plan</h3>");
    expect(html).toContain("<ul>");
    expect(html).toContain("<strong>emphasis</strong>");
    expect(html).toContain("<code>inline code</code>");
    expect(html).toContain("language-ts");
    expect(html).toContain("hljs-keyword");
    expect(html).toContain('class="katex"');
    expect(html).not.toContain("<script>");
  });

  it("places synthesis in the executor follow-up lane after the audit lane", () => {
    const html = renderToStaticMarkup(
      <Conversation
        livePrompt="Resolve the design."
        messages={[
          {
            id: "proposal",
            role: "executor",
            runtime_id: "codex",
            stage: "proposal",
            text: "Proposal.",
            round: 1,
          },
          {
            id: "audit-one",
            role: "auditor",
            runtime_id: "claude-code",
            stage: "audit",
            verdict: "challenge",
            text: "CHALLENGE: first audit.",
            round: 1,
          },
          {
            id: "audit-two",
            role: "auditor",
            runtime_id: "claude-code",
            stage: "audit",
            verdict: "accept",
            text: "ACCEPT: second audit.",
            round: 1,
          },
          {
            id: "synthesis",
            role: "executor",
            runtime_id: "codex",
            stage: "synthesis",
            text: "Synthesis.",
            round: 1,
          },
        ]}
      />,
    );

    const auditorLane = html.indexOf('class="auditor-lane"');
    const synthesisLane = html.indexOf('class="executor-followup-lane"');
    expect(auditorLane).toBeGreaterThan(-1);
    expect(synthesisLane).toBeGreaterThan(auditorLane);
    expect(html).toContain('data-message-stage="synthesis"');
    expect(html).toContain("AUDIT · CHALLENGE");
    expect(html).toContain("AUDIT · ACCEPT");
  });

  it("renders ordered provider blocks inertly while preserving code and diff", () => {
    const html = renderToStaticMarkup(
      <Conversation
        messages={[
          {
            id: "blocks",
            participant_id: "executor-1",
            role: "executor",
            runtime_id: "codex",
            stage: "proposal",
            text: "Authoritative fallback text.",
            blocks: [
              { type: "markdown", text: "**First** <script>unsafe()</script>" },
              { type: "code", code: "const safe = true;", language: "ts", title: "Code" },
              { type: "diff", diff: "- false\n+ true", title: "Diff" },
              { type: "citation", label: "Source", url: "https://example.com/source" },
            ],
            round: 1,
            cycle: 1,
          },
        ]}
      />,
    );

    const markdown = html.indexOf("<strong>First</strong>");
    const code = html.indexOf("const safe = true;");
    const diff = html.indexOf("- false");
    const citation = html.indexOf("Source</a>");
    expect(markdown).toBeGreaterThan(-1);
    expect(code).toBeGreaterThan(markdown);
    expect(diff).toBeGreaterThan(code);
    expect(citation).toBeGreaterThan(diff);
    expect(html).toContain("language-ts");
    expect(html).toContain("language-diff");
    expect(html).not.toContain("<script>");
  });
});
