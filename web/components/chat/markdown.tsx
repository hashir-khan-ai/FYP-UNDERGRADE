"use client";

import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { safeHttpUrl } from "@/lib/citations";

/**
 * Markdown is rendered from untrusted model output. Raw HTML is never enabled;
 * links are restricted to absolute http(s) URLs and open without a referrer.
 */
export const Markdown = React.memo(function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a({ href, children: linkChildren }) {
          const safe = safeHttpUrl(href);
          if (!safe) return <span>{linkChildren}</span>;
          return (
            <a href={safe} target="_blank" rel="noopener noreferrer nofollow">
              {linkChildren}
            </a>
          );
        },
        table({ children: tableChildren }) {
          return (
            <div className="overflow-x-auto">
              <table>{tableChildren}</table>
            </div>
          );
        },
      }}
    >
      {children}
    </ReactMarkdown>
  );
});
