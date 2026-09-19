import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Conversation, reviewTargetForMessage } from "./Conversation";
import { parseConversationMessage, parseParticipantActivity, type ConversationMessage } from "../protocol/messages";

const answer: ConversationMessage = { id: "run-1:1", role: "executor", runtime_id: "codex", participant_id: "speaker", text: "Saved direct answer", round: 1, cycle: 1, stage: "answer" };

describe("direct answers", () => {
  it("parses and renders saved answers with historical attribution and Review", () => {
    const parsed = parseConversationMessage(answer)!;
    expect(parsed.stage).toBe("answer");
    const html = renderToStaticMarkup(<Conversation messages={[parsed]} runtimeDisplayNames={{ codex: "Codex" }} runtimeNames={{ speaker: "Claude after swap" }} onReview={() => {}} />);
    expect(html).toContain('data-message-stage="answer"');
    expect(html).toContain("Saved direct answer");
    expect(html).toContain("Codex");
    expect(html).not.toContain("Claude after swap");
    expect(html).toContain(">Review</button>");
    expect(html).not.toContain('data-message-stage="proposal"');
  });
  it("renders answer activity even before the first completed message", () => {
    const activity = parseParticipantActivity({ run_id: "run-1", participant_id: "speaker", runtime_id: "codex", stage: "answer", status: "running", round: 1, cycle: 1 })!;
    expect(activity.stage).toBe("answer");
    const html = renderToStaticMarkup(<Conversation messages={[]} activities={[activity]} />);
    expect(html).toContain("codex is answering");
  });
  it("targets only saved completed answer, proposal or synthesis records", () => {
    for (const stage of ["answer", "proposal", "synthesis"] as const) expect(reviewTargetForMessage({ ...answer, stage })).toEqual({ cycle_id: "run-1", message_id: "run-1:1" });
    expect(reviewTargetForMessage({ ...answer, stage: "audit" })).toBeNull();
    expect(reviewTargetForMessage({ ...answer, partial: true })).toBeNull();
    expect(reviewTargetForMessage({ ...answer, id: "unknown" })).toBeNull();
  });
});
