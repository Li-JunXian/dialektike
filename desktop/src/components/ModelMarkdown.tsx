import { Check, Copy } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { safeHttpUrl } from "../security/safeHttpUrl";

import "highlight.js/styles/github.css";
import "katex/dist/katex.min.css";

interface ModelMarkdownProps {
  text: string;
}

/**
 * Render provider-authored CommonMark/GFM as structured, inert UI.
 * Raw HTML remains text because rehype-raw is deliberately not installed.
 */
export function ModelMarkdown({ text }: ModelMarkdownProps) {
  return (
    <div className="model-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeHighlight, { ignoreMissing: true }], rehypeKatex]}
        components={{
          a: ({ children, href, ...props }) => {
            const safeHref = safeExternalHref(href);
            return safeHref ? (
              <a {...props} href={safeHref} target="_blank" rel="noreferrer noopener">{children}</a>
            ) : (
              <span>{children}</span>
            );
          },
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

export function SafeCodeBlock({
  code,
  language,
  title,
  children,
}: {
  code: string;
  language?: string;
  title?: string;
  children?: ReactNode;
}) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await copyCodeToClipboard(code);
      setCopied(true);
      globalThis.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  }
  return (
    <div className="code-block">
      <div className="code-block__toolbar">
        <span>{title || language || "Code"}</span>
        <button type="button" aria-label="Copy code" onClick={() => void copy()}>
          {copied ? <Check size={13} aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre>{children ?? <code className={language ? `language-${language}` : undefined}>{code}</code>}</pre>
    </div>
  );
}

function safeExternalHref(value?: string): string | undefined {
  return value ? safeHttpUrl(value) : undefined;
}

export async function copyCodeToClipboard(
  code: string,
  clipboard: Pick<Clipboard, "writeText"> = navigator.clipboard,
): Promise<void> {
  await clipboard.writeText(code);
}

function textFromNode(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textFromNode).join("");
  if (node && typeof node === "object" && "props" in node) {
    return textFromNode((node as { props?: { children?: ReactNode } }).props?.children);
  }
  return "";
}
