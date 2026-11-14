"use client";

import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { safeHttpUrl } from "@/lib/citations";
import { cn } from "@/lib/utils";

export interface MarkdownProps {
  children: string;
  citationCount?: number;
  activeCiteIndex?: number | null;
  onHoverCite?: (index: number | null) => void;
  onJumpCite?: (index: number) => void;
}

interface CiteContextValue {
  citationCount: number;
  activeCiteIndex: number | null;
  onHoverCite?: (index: number | null) => void;
  onJumpCite?: (index: number) => void;
}

const CiteContext = React.createContext<CiteContextValue>({
  citationCount: 0,
  activeCiteIndex: null,
});

const CITE_TOKEN_RE = /(\[\d+\])/g;

function CitePin({ num }: { num: number }) {
  const { activeCiteIndex, onHoverCite, onJumpCite } = React.useContext(CiteContext);
  const citeIndex = num - 1;
  const isActive = activeCiteIndex === citeIndex;

  return (
    <button
      type="button"
      data-cite-pin={num}
      onMouseEnter={() => onHoverCite?.(citeIndex)}
      onMouseLeave={() => onHoverCite?.(null)}
      onFocus={() => onHoverCite?.(citeIndex)}
      onBlur={() => onHoverCite?.(null)}
      onClick={() => onJumpCite?.(citeIndex)}
      aria-label={`Jump to source ${num}`}
      className={cn(
        "tabular mx-0.5 inline-flex min-h-[24px] min-w-[24px] items-center justify-center rounded-[var(--r-xs)] px-1.5 py-0.5 align-baseline font-mono text-xs font-semibold leading-none transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        isActive
          ? "bg-accent text-accent-ink shadow-[var(--elev-1)]"
          : "bg-accent-soft text-accent-link ring-1 ring-inset ring-line-accent hover:bg-[var(--accent-soft-hover)]",
      )}
    >
      [{num}]
    </button>
  );
}

function renderWithCitations(
  nodes: React.ReactNode,
  citationCount: number,
  hasJump: boolean,
): React.ReactNode {
  if (citationCount <= 0 || !hasJump) return nodes;

  return React.Children.map(nodes, (child) => {
    if (typeof child === "string") {
      if (!child.includes("[")) return child;
      const parts = child.split(CITE_TOKEN_RE);
      return parts.map((part, idx) => {
        const match = /^\[(\d+)\]$/.exec(part);
        if (!match) return part;
        const num = Number(match[1]);
        const citeIndex = num - 1;
        if (citeIndex < 0 || citeIndex >= citationCount) return part;
        return <CitePin key={`cite-pin-${idx}-${num}`} num={num} />;
      });
    }

    if (
      React.isValidElement<{ children?: React.ReactNode }>(child) &&
      child.type !== "code" &&
      child.type !== "pre" &&
      child.type !== "button" &&
      child.type !== "a" &&
      child.type !== CitePin &&
      child.props?.children
    ) {
      return React.cloneElement(child, {
        children: renderWithCitations(child.props.children, citationCount, hasJump),
      });
    }

    return child;
  });
}

function useDecorated(children: React.ReactNode) {
  const { citationCount, onJumpCite } = React.useContext(CiteContext);
  return renderWithCitations(children, citationCount, Boolean(onJumpCite));
}

function MdH2({ children }: { children?: React.ReactNode }) {
  return <h2>{useDecorated(children)}</h2>;
}
function MdH3({ children }: { children?: React.ReactNode }) {
  return <h3>{useDecorated(children)}</h3>;
}
function MdH4({ children }: { children?: React.ReactNode }) {
  return <h4>{useDecorated(children)}</h4>;
}
function MdH5({ children }: { children?: React.ReactNode }) {
  return <h5>{useDecorated(children)}</h5>;
}
function MdP({ children }: { children?: React.ReactNode }) {
  return <p>{useDecorated(children)}</p>;
}
function MdLi({ children }: { children?: React.ReactNode }) {
  return <li>{useDecorated(children)}</li>;
}
function MdBlockquote({ children }: { children?: React.ReactNode }) {
  return <blockquote>{useDecorated(children)}</blockquote>;
}
function MdTd({ children }: { children?: React.ReactNode }) {
  return <td>{useDecorated(children)}</td>;
}
function MdTh({ children }: { children?: React.ReactNode }) {
  return <th>{useDecorated(children)}</th>;
}
function MdA({ href, children }: { href?: string; children?: React.ReactNode }) {
  const safe = safeHttpUrl(href);
  if (!safe) return <span>{children}</span>;
  return (
    <a href={safe} target="_blank" rel="noopener noreferrer nofollow">
      {children}
    </a>
  );
}
function MdTable({ children }: { children?: React.ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table>{children}</table>
    </div>
  );
}

const MARKDOWN_COMPONENTS: React.ComponentProps<typeof ReactMarkdown>["components"] = {
  h1: MdH2,
  h2: MdH3,
  h3: MdH4,
  h4: MdH5,
  p: MdP,
  li: MdLi,
  blockquote: MdBlockquote,
  td: MdTd,
  th: MdTh,
  a: MdA,
  table: MdTable,
};

/**
 * Markdown is rendered from untrusted model output. Raw HTML is never enabled;
 * links are restricted to absolute http(s) URLs and open without a referrer.
 * Headings are normalized downward (h1->h2, h2->h3, h3->h4) to preserve page outline order.
 */
export const Markdown = React.memo(function Markdown({
  children,
  citationCount = 0,
  activeCiteIndex = null,
  onHoverCite,
  onJumpCite,
}: MarkdownProps) {
  const ctxValue = React.useMemo<CiteContextValue>(
    () => ({
      citationCount,
      activeCiteIndex,
      onHoverCite,
      onJumpCite,
    }),
    [citationCount, activeCiteIndex, onHoverCite, onJumpCite],
  );

  return (
    <CiteContext.Provider value={ctxValue}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
        {children}
      </ReactMarkdown>
    </CiteContext.Provider>
  );
});
