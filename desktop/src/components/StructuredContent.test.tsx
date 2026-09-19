import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import canonicalFixture from "../../../tests/fixtures/r0-canonical-response.md?raw";

import type { StructuredContentBlock } from "../protocol/messages";
import {
  safeStructuredHref,
  StructuredContent,
  StructuredContentBlockView,
} from "./StructuredContent";
import { copyCodeToClipboard } from "./ModelMarkdown";

describe("safe structured content", () => {
  it("renders the declared block union in provider order", () => {
    const blocks: StructuredContentBlock[] = [
      { type: "markdown", text: "**Markdown marker**" },
      { type: "code", code: "const codeMarker = true;", language: "ts", title: "Code marker" },
      { type: "diff", diff: "-before\n+diffMarker", title: "Diff marker" },
      { type: "math", text: "mathMarker = x^2", display: true },
      { type: "diagram", source: "A --> diagramMarker", language: "mermaid", title: "Diagram marker" },
      { type: "tool", title: "Tool marker", summary: "Tool summary", status: "completed" },
      { type: "citation", label: "Citation marker", url: "https://example.com/source" },
      { type: "file", name: "File marker", mimeType: "text/plain", size: 2048, assetId: "asset:trusted-1" },
      { type: "media", mediaType: "image", label: "Media marker", mimeType: "image/png", assetId: "asset:trusted-2", alt: "Media description" },
      { type: "editor-reference", label: "Editor marker", path: "src/main.ts", line: 12, column: 4 },
      { type: "unknown", sourceType: "future_block", label: "Unknown marker", text: "Unknown body" },
    ];

    const html = renderToStaticMarkup(<StructuredContent blocks={blocks} />);
    const markers = [
      "Markdown marker",
      "Code marker",
      "Diff marker",
      "mathMarker",
      "Diagram marker",
      "Tool marker",
      "Citation marker",
      "File marker",
      "Media marker",
      "Editor marker",
      "Unknown marker",
    ];
    let cursor = -1;
    for (const marker of markers) {
      const next = html.indexOf(marker);
      expect(next).toBeGreaterThan(cursor);
      cursor = next;
    }
    expect(html).toContain('href="https://example.com/source"');
    expect(html).toContain('rel="noreferrer noopener"');
    expect(html).toContain("2.0 KB");
    expect(html).toContain("src/main.ts:12:4");
  });

  it("keeps raw HTML, unsafe Markdown links, diagram source, and unknown text inert", () => {
    const html = renderToStaticMarkup(
      <StructuredContent
        blocks={[
          { type: "markdown", text: '<script>markdownUnsafe()</script> [bad](javascript:alert(1))' },
          { type: "markdown", text: '![remote image](https://tracking.example/pixel.png "Remote preview")' },
          { type: "math", text: String.raw`\href{javascript:alert(1)}{mathUnsafe}`, display: true },
          { type: "diagram", source: '<svg onload="diagramUnsafe()"></svg>', language: "mermaid" },
          { type: "unknown", sourceType: "future", label: "Unknown", text: '<img src=x onerror="unknownUnsafe()">' },
        ]}
      />,
    );

    expect(html).not.toContain("<script>");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<svg onload");
    expect(html).not.toContain('href="javascript:');
    expect(html).not.toContain("tracking.example");
    expect(html).toContain("Remote image omitted: Remote preview");
    expect(html).toContain("&lt;script&gt;markdownUnsafe()&lt;/script&gt;");
    expect(html).toContain("&lt;svg onload=&quot;diagramUnsafe()&quot;&gt;&lt;/svg&gt;");
    expect(html).toContain("&lt;img src=x onerror=&quot;unknownUnsafe()&quot;&gt;");
  });

  it("does not activate unsafe citations or media and file asset identifiers", () => {
    const unsafeCitation = renderToStaticMarkup(
      <StructuredContentBlockView block={{ type: "citation", label: "Unsafe source", url: "javascript:alert(1)" }} />,
    );
    const metadata = renderToStaticMarkup(
      <StructuredContent
        blocks={[
          { type: "file", name: "document.txt", assetId: "https://attacker.example/file" },
          { type: "media", mediaType: "audio", label: "Recording", assetId: "javascript:alert(1)" },
          { type: "media", mediaType: "video", label: "Clip", assetId: "data:text/html,unsafe" },
        ]}
      />,
    );

    expect(unsafeCitation).not.toContain("<a");
    expect(unsafeCitation).not.toContain("href=");
    expect(unsafeCitation).toContain("Link unavailable");
    expect(metadata).not.toContain("href=");
    expect(metadata).not.toContain("src=");
    expect(metadata).not.toContain("<audio");
    expect(metadata).not.toContain("<video");
    expect(metadata).not.toContain("<img");
  });

  it("escapes executable-looking text in code, tools, metadata, citations, and editor references", () => {
    const html = renderToStaticMarkup(
      <StructuredContent
        blocks={[
          { type: "code", code: "<script>codeUnsafe()</script>", language: "html" },
          { type: "diff", diff: '<img src=x onerror="diffUnsafe()">' },
          { type: "tool", title: "<iframe>Tool</iframe>", summary: "<object>summary</object>" },
          { type: "citation", label: "<img>Source</img>", url: "https://example.com" },
          { type: "file", name: "<script>file.txt</script>", mimeType: "text/plain" },
          { type: "media", mediaType: "video", label: "<video>Clip</video>", alt: "<audio>description</audio>" },
          { type: "editor-reference", label: "Editor", path: '<a href="file:///tmp/private">private</a>', line: 1 },
        ]}
      />,
    );

    for (const tag of ["script", "img", "iframe", "object", "video", "audio"]) {
      expect(html).not.toContain(`<${tag}`);
    }
    expect(html).toContain("&lt;script&gt;codeUnsafe()&lt;/script&gt;");
    expect(html).toContain("&lt;iframe&gt;Tool&lt;/iframe&gt;");
    expect(html).toContain("&lt;a href=&quot;file:///tmp/private&quot;&gt;private&lt;/a&gt;:1");
  });

  it("uses the inert structured Markdown renderer as the text fallback", () => {
    const html = renderToStaticMarkup(
      <StructuredContent fallbackText={'**Fallback** <script>unsafe()</script> [safe](https://example.com)'} />,
    );
    expect(html).toContain("<strong>Fallback</strong>");
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;unsafe()&lt;/script&gt;");
    expect(html).toContain('href="https://example.com/"');
  });

  it("allows only absolute HTTP and HTTPS citation targets", () => {
    expect(safeStructuredHref("https://example.com/path")).toBe("https://example.com/path");
    expect(safeStructuredHref("http://example.com/path")).toBe("http://example.com/path");
    expect(safeStructuredHref("javascript:alert(1)")).toBeUndefined();
    expect(safeStructuredHref("data:text/html,unsafe")).toBeUndefined();
    expect(safeStructuredHref("file:///tmp/private")).toBeUndefined();
    expect(safeStructuredHref("/relative/path")).toBeUndefined();
    expect(safeStructuredHref("https://user:secret@example.com/path")).toBeUndefined();
    expect(safeStructuredHref("https://example.com\\@attacker.test/path")).toBeUndefined();
    expect(safeStructuredHref("https://example.com/path\njavascript:alert(1)")).toBeUndefined();
    expect(safeStructuredHref("https://example.com:invalid/path")).toBeUndefined();
  });

  it("copies authored code bytes without removing a terminal newline", async () => {
    const writeText = vi.fn(async () => undefined);
    const authored = "const exact = true;  \n";

    await copyCodeToClipboard(authored, { writeText });

    expect(writeText).toHaveBeenCalledWith(authored);
  });

  it("renders the one shared canonical fixture without executing authored HTML", () => {
    const html = renderToStaticMarkup(
      <StructuredContent blocks={[{ type: "markdown", text: canonicalFixture }]} />,
    );

    expect(new TextEncoder().encode(canonicalFixture)).toHaveLength(3783);
    expect(html).toContain("leading spaces remain");
    expect(html).toContain("<table>");
    expect(html).toContain('type="checkbox"');
    expect(html).toContain("katex");
    expect(html).toContain("trailing spaces remain");
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;globalThis.__dialektike_executed__ = true&lt;/script&gt;");
    expect(html).not.toContain('href="javascript:');
  });
});
