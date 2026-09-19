import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PROJECT_WORKSPACE_RISK_ACKNOWLEDGEMENT } from "../protocol/messages";
import { ProjectSidebarSection, TopicProjectContext } from "./ProjectControls";

const PROJECTS = [
  { id: "project-one", name: "dialektike", available: true },
  { id: "project-two", name: "missing-work", available: false },
];

describe("Project controls", () => {
  it("renders a compact General and folder Project filter without exposing paths", () => {
    const html = renderToStaticMarkup(
      <ProjectSidebarSection
        projects={PROJECTS}
        selectedProjectId="project-one"
        onSelectProject={() => undefined}
        onOpenFolder={() => undefined}
      />,
    );

    expect(html).toContain("Projects");
    expect(html).toContain("General");
    expect(html).toContain("dialektike");
    expect(html).toContain("Folder unavailable");
    expect(html).toContain("Open Folder");
    expect(html).not.toContain("/Users/");
  });

  it("surfaces the active topic folder and fail-closed unavailable state", () => {
    const html = renderToStaticMarkup(
      <TopicProjectContext
        projects={PROJECTS}
        activeTopicProjectId="project-two"
        activeTopic
        onAssignTopic={() => undefined}
      />,
    );

    expect(html).toContain("missing-work");
    expect(html).toContain("This folder is unavailable; runs will fail closed");
    expect(html).toContain('aria-label="Project for current topic"');
  });

  it("keeps the exact governance disclosure in the trusted UI source", () => {
    expect(PROJECT_WORKSPACE_RISK_ACKNOWLEDGEMENT).toBe(
      "Participants use this folder as their native working directory. Actions the native runtime auto-permits may modify it without a Dialektikḗ card; those actions remain audited.",
    );
  });
});
