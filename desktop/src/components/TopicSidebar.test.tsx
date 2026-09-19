import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { TopicSidebar } from "./TopicSidebar";

describe("archived topic navigation", () => {
  it("filters topics by the selected Project while keeping General explicit", () => {
    const html = renderToStaticMarkup(
      <TopicSidebar
        topics={[
          { id: "general", title: "General research", pinned: false, archived: false, projectId: null },
          { id: "bound", title: "Dialektike implementation", pinned: false, archived: false, projectId: "project-1" },
        ]}
        projects={[{ id: "project-1", name: "dialektike", available: true }]}
        selectedProjectId="project-1"
        activeTopicId="bound"
        query=""
        archivedView={false}
        onQueryChange={() => undefined}
        onSelect={() => undefined}
        onNewTopic={() => undefined}
        onArchivedViewChange={() => undefined}
        onRename={() => undefined}
        onPin={() => undefined}
        onArchive={() => undefined}
        onDelete={() => undefined}
      />,
    );

    expect(html).toContain("Dialektike implementation");
    expect(html).not.toContain("General research");
    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain("Open Folder");
  });

  it("keeps Back to Topics and archived topic actions operable when idle", () => {
    const html = renderToStaticMarkup(
      <TopicSidebar
        topics={[
          {
            id: "archived-1",
            title: "Archived design",
            pinned: false,
            archived: true,
            projectId: null,
          },
        ]}
        activeTopicId={null}
        query=""
        archivedView
        busy={false}
        onQueryChange={() => undefined}
        onSelect={() => undefined}
        onNewTopic={() => undefined}
        onArchivedViewChange={() => undefined}
        onRename={() => undefined}
        onPin={() => undefined}
        onArchive={() => undefined}
        onDelete={() => undefined}
      />,
    );

    expect(html).toContain("Archived design");
    expect(html).toContain("Back to Topics");
    expect(html).toContain('aria-pressed="true"');
    expect(html).not.toContain('disabled=""');
  });

  it("keeps System, Light, and Dark appearance choices available during a run", () => {
    const html = renderToStaticMarkup(
      <TopicSidebar
        topics={[]}
        activeTopicId={null}
        query=""
        archivedView={false}
        busy
        appearance="system"
        onQueryChange={() => undefined}
        onSelect={() => undefined}
        onNewTopic={() => undefined}
        onArchivedViewChange={() => undefined}
        onRename={() => undefined}
        onPin={() => undefined}
        onArchive={() => undefined}
        onDelete={() => undefined}
      />,
    );

    const appearanceSelect = html.match(/<select aria-label="Appearance"[^>]*>/)?.[0] ?? "";
    expect(appearanceSelect).not.toContain("disabled");
    expect(html).toContain('<option value="system" selected="">System</option>');
    expect(html).toContain('<option value="light">Light</option>');
    expect(html).toContain('<option value="dark">Dark</option>');
  });

  it("renders an uncluttered collapsed rail without removing primary or appearance controls", () => {
    const html = renderToStaticMarkup(
      <TopicSidebar
        topics={[]}
        activeTopicId={null}
        query=""
        archivedView={false}
        collapsed
        appearance="dark"
        onQueryChange={() => undefined}
        onSelect={() => undefined}
        onNewTopic={() => undefined}
        onArchivedViewChange={() => undefined}
        onRename={() => undefined}
        onPin={() => undefined}
        onArchive={() => undefined}
        onDelete={() => undefined}
      />,
    );

    expect(html).toContain('data-sidebar-visibility="collapsed"');
    expect(html).toContain('aria-label="Expand topic sidebar"');
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('aria-label="New topic"');
    expect(html).toContain('aria-label="Appearance"');
    expect(html).toContain('<option value="dark" selected="">Dark</option>');
    expect(html).not.toContain('aria-label="Dialektikḗ"');
  });
});
