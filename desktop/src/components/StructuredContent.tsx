import {
  Braces,
  FileText,
  Image as ImageIcon,
  MonitorPlay,
  Music2,
  Quote,
  Wrench,
} from "lucide-react";
import type { ReactNode } from "react";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import type { StructuredContentBlock } from "../protocol/messages";
import { safeHttpUrl } from "../security/safeHttpUrl";
import { SafeCodeBlock } from "./ModelMarkdown";

interface StructuredContentProps {
  blocks?: readonly StructuredContentBlock[];
  fallbackText?: string;
}

/**
 * Renders normalized provider content without interpreting provider-authored
 * HTML, diagram languages, editor paths, asset identifiers, or unknown blocks
 * as executable application instructions.
 */
export function StructuredContent({ blocks, fallbackText = "" }: StructuredContentProps) {
  if (!blocks || blocks.length === 0) {
    return <StructuredMarkdown text={fallbackText} />;
  }

  return (
    <div className="structured-response">
      {blocks.map((block, index) => (
        <StructuredContentBlockView block={block} key={`${block.type}:${index}`} />
      ))}
    </div>
  );
}

export function StructuredContentBlockView({ block }: { block: StructuredContentBlock }) {
  switch (block.type) {
    case "markdown":
      return <StructuredMarkdown text={block.text} />;
    case "code":
      return <SafeCodeBlock code={block.code} language={block.language} title={block.title} />;
    case "diff":
      return <SafeCodeBlock code={block.diff} language="diff" title={block.title ?? "Changes"} />;
    case "math":
      return <StructuredMarkdown text={mathMarkdown(block.text, block.display)} />;
    case "diagram":
      return (
        <section className="structured-content structured-content--diagram" data-content-type="diagram" aria-label="Diagram source">
          <ContentHeading icon={<Braces size={14} aria-hidden="true" />} title={block.title ?? "Diagram source"} detail={block.language} />
          <SafeCodeBlock code={block.source} language={block.language} title={`${block.language} source`} />
        </section>
      );
    case "tool":
      return (
        <section className="structured-tool" data-content-type="tool" aria-label="Tool activity">
          <ContentHeading icon={<Wrench size={14} aria-hidden="true" />} title={block.title} detail={block.status} />
          {block.summary ? <p>{block.summary}</p> : null}
        </section>
      );
    case "citation": {
      const href = safeStructuredHref(block.url);
      return href ? (
        <a className="structured-citation" data-content-type="citation" href={href} target="_blank" rel="noreferrer noopener">
          <Quote size={13} aria-hidden="true" />
          {block.label}
        </a>
      ) : (
        <section className="structured-tool structured-content--inert" data-content-type="citation" aria-label="Unavailable citation">
          <ContentHeading icon={<Quote size={14} aria-hidden="true" />} title={block.label} detail="Link unavailable" />
        </section>
      );
    }
    case "file":
      return (
        <MetadataBlock
          type="file"
          icon={<FileText size={14} aria-hidden="true" />}
          label={block.name}
          details={[block.mimeType, formatByteSize(block.size), block.assetId ? "Local asset metadata" : undefined]}
        />
      );
    case "media":
      return (
        <MetadataBlock
          type={block.mediaType}
          icon={<MediaIcon type={block.mediaType} />}
          label={block.label}
          details={[block.mimeType, block.assetId ? "Local asset metadata" : undefined]}
          description={block.alt}
        />
      );
    case "editor-reference": {
      const suffix = locationSuffix(block.line, block.column);
      return (
        <section className="structured-tool structured-content--editor-reference" data-content-type="editor-reference" aria-label="Editor reference">
          <ContentHeading icon={<FileText size={14} aria-hidden="true" />} title={block.label} detail="Editor reference" />
          <code>{block.path}{suffix}</code>
        </section>
      );
    }
    case "unknown":
      return (
        <section className="structured-tool structured-content--unknown" data-content-type="unknown" aria-label="Unsupported provider content">
          <ContentHeading icon={<Braces size={14} aria-hidden="true" />} title={block.label} detail={block.sourceType || "unknown"} />
          {block.text ? <p>{block.text}</p> : null}
        </section>
      );
  }
}

/** Markdown is inert: raw HTML is text, remote images are metadata, and only
 * absolute HTTP(S) links become anchors. */
export function StructuredMarkdown({ text }: { text: string }) {
  return (
    <div className="model-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[
          [rehypeHighlight, { ignoreMissing: true }],
          [rehypeKatex, { trust: false, throwOnError: false }],
        ]}
        components={{
          a: ({ children, href }) => {
            const safeHref = safeStructuredHref(href ?? "");
            return safeHref ? (
              <a href={safeHref} target="_blank" rel="noreferrer noopener">{children}</a>
            ) : (
              <span>{children}</span>
            );
          },
          img: ({ alt, title }) => (
            <span className="structured-tool structured-content--inert" data-content-type="image" role="note">
              Remote image omitted{title || alt ? `: ${title || alt}` : ""}
            </span>
          ),
          pre: ({ children }) => (
            <SafeCodeBlock code={textFromNode(children)}>{children}</SafeCodeBlock>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

export function safeStructuredHref(value: string): string | undefined {
  return safeHttpUrl(value);
}

function MetadataBlock({
  type,
  icon,
  label,
  details,
  description,
}: {
  type: "file" | "image" | "audio" | "video";
  icon: ReactNode;
  label: string;
  details: Array<string | undefined>;
  description?: string;
}) {
  const visibleDetails = details.filter((detail): detail is string => Boolean(detail));
  return (
    <section className="structured-tool structured-content--metadata" data-content-type={type} aria-label={`${type} metadata`}>
      <ContentHeading icon={icon} title={label} detail={visibleDetails.join(" · ") || type} />
      {description ? <p>{description}</p> : null}
    </section>
  );
}

function ContentHeading({ icon, title, detail }: { icon: ReactNode; title: string; detail?: string }) {
  return (
    <header>
      <span>{icon}{title}</span>
      {detail ? <small>{detail}</small> : null}
    </header>
  );
}

function MediaIcon({ type }: { type: "image" | "audio" | "video" }) {
  if (type === "image") return <ImageIcon size={14} aria-hidden="true" />;
  if (type === "audio") return <Music2 size={14} aria-hidden="true" />;
  return <MonitorPlay size={14} aria-hidden="true" />;
}

function mathMarkdown(text: string, display: boolean): string {
  return display ? `$$\n${text}\n$$` : `$${text}$`;
}

function formatByteSize(value?: number): string | undefined {
  if (value === undefined || !Number.isFinite(value) || value < 0) return undefined;
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${(value / 1024 ** 3).toFixed(1)} GB`;
}

function locationSuffix(line?: number, column?: number): string {
  if (!line || line < 1) return "";
  if (!column || column < 1) return `:${line}`;
  return `:${line}:${column}`;
}

function textFromNode(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textFromNode).join("");
  if (node && typeof node === "object" && "props" in node) {
    return textFromNode((node as { props?: { children?: ReactNode } }).props?.children);
  }
  return "";
}
