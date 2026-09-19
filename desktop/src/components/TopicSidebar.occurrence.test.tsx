import { renderToStaticMarkup } from "react-dom/server";
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react")>();
  return {
    ...actual,
    useEffect: () => undefined,
    useRef: <T,>(initial: T) => ({ current: initial }),
    useState: <T,>(initial: T | (() => T)) => [
      typeof initial === "function" ? (initial as () => T)() : initial,
      () => undefined,
    ],
  };
});

import type { TopicSearchOccurrence } from "../protocol/messages";
import { TopicSidebar } from "./TopicSidebar";

describe("topic occurrence results", () => {
  it("renders highlighted authored segments and forwards the selected occurrence", () => {
    const occurrence: TopicSearchOccurrence = {
      occurrenceId: "occurrence.synthetic.1",
      topicId: "topic.synthetic.1",
      topicTitle: "Synthetic rate-limit review",
      archived: true,
      sourceKind: "conversation_message",
      sourceAnchor: "message.synthetic.1",
      sourceField: "text",
      stage: "audit",
      speaker: "Synthetic Auditor",
      timestamp: "2026-08-10T12:00:00Z",
      matchStartUtf8: 17,
      matchEndUtf8: 27,
      prefixTruncated: true,
      suffixTruncated: true,
      segments: [
        { text: "Review the ", highlighted: false },
        { text: "rate limit", highlighted: true },
        { text: " before release", highlighted: false },
      ],
    };
    const onSelectOccurrence = vi.fn();
    const tree = TopicSidebar({
      topics: [{
        id: "topic.synthetic.1",
        title: "Synthetic rate-limit review",
        pinned: false,
        archived: false,
        projectId: null,
      }],
      activeTopicId: null,
      query: "rate limit",
      archivedView: false,
      searchOccurrences: [occurrence],
      onQueryChange: () => undefined,
      onSelect: () => undefined,
      onSelectOccurrence,
      onNewTopic: () => undefined,
      onArchivedViewChange: () => undefined,
      onRename: () => undefined,
      onPin: () => undefined,
      onArchive: () => undefined,
      onDelete: () => undefined,
    });

    const html = renderToStaticMarkup(tree);
    expect(html).toContain('aria-label="Search results"');
    expect(html).toContain('data-source-anchor="topic:topic.synthetic.1:title"');
    expect(html).toContain("1 occurrence");
    expect(html).toContain("Synthetic rate-limit review");
    expect(html).toContain("Archived");
    expect(html).toContain("Synthetic Auditor");
    expect(html).toContain("audit");
    expect(html).toMatch(/Aug 10|10 Aug/);
    expect(html).toContain("…<span>Review the </span><mark>rate limit</mark><span> before release</span>…");

    const option = collectElements(tree).find((element) => element.props.role === "option");
    expect(option).toBeDefined();
    (option?.props.onClick as (() => void) | undefined)?.();
    expect(onSelectOccurrence).toHaveBeenCalledTimes(1);
    expect(onSelectOccurrence).toHaveBeenCalledWith(occurrence);
  });
});

type TestElement = ReactElement<Record<string, unknown> & { children?: ReactNode }>;

function collectElements(node: ReactNode): TestElement[] {
  if (Array.isArray(node)) return node.flatMap(collectElements);
  if (!isValidElement(node)) return [];
  const element = node as TestElement;
  return [element, ...collectElements(element.props.children)];
}
