import { describe, expect, it } from "vitest";

import { computeMenuPosition, topicMenuActionOrder, topicMenuDomId } from "./TopicOverflowMenu";

describe("topic overflow menu positioning", () => {
  it("anchors below the trigger and clamps to the right viewport edge", () => {
    expect(computeMenuPosition(
      { left: 700, right: 730, top: 100, bottom: 130 },
      { width: 160, height: 150 },
      720,
      640,
    )).toEqual({ left: 552, top: 134, placement: "below" });
  });

  it("flips above when the lower edge cannot fit the menu", () => {
    expect(computeMenuPosition(
      { left: 20, right: 50, top: 570, bottom: 600 },
      { width: 160, height: 150 },
      720,
      640,
    )).toEqual({ left: 8, top: 416, placement: "above" });
  });

  it("keeps an oversized menu inside the visible window", () => {
    const position = computeMenuPosition(
      { left: 2, right: 30, top: 2, bottom: 30 },
      { width: 900, height: 900 },
      720,
      640,
    );
    expect(position.left).toBe(8);
    expect(position.top).toBe(8);
  });
});

describe("topic overflow menu actions", () => {
  it("uses the governed action order for ordinary topics", () => {
    expect(topicMenuActionOrder({ archived: false, pinned: false })).toEqual(["rename", "pin", "archive", "delete"]);
    expect(topicMenuActionOrder({ archived: false, pinned: true })).toEqual(["rename", "unpin", "archive", "delete"]);
  });

  it("shows only valid actions in the Archived view", () => {
    expect(topicMenuActionOrder({ archived: true, pinned: false })).toEqual(["unarchive", "delete"]);
  });

  it("gives the trigger and portal menu a safe deterministic accessibility relationship", () => {
    expect(topicMenuDomId("topic/with spaces")).toBe("topic-actions-topic-with-spaces");
  });
});
