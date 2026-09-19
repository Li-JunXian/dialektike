import { describe, expect, it } from "vitest";

import { transitionTopicView } from "./topics";

describe("topic archive view", () => {
  it("keeps archive, unarchive and Back operable in browser preview", () => {
    const active = { archived: false, query: "api", busy: false };
    const archived = transitionTopicView(active, true, true);
    expect(archived).toEqual({ archived: true, query: "", busy: false });

    const back = transitionTopicView(archived, false, true);
    expect(back).toEqual({ archived: false, query: "", busy: false });
  });

  it("waits for the native archived query before enabling topic controls", () => {
    expect(
      transitionTopicView(
        { archived: false, query: "", busy: false },
        true,
        false,
      ),
    ).toEqual({ archived: true, query: "", busy: true });
  });
});
