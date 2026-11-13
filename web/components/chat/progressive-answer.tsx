"use client";

import * as React from "react";

import { Markdown } from "@/components/chat/markdown";

/**
 * Progressive reveal for a completed answer. This is a presentation effect,
 * not token streaming: the backend returns the verified answer synchronously.
 */
export function ProgressiveAnswer({
  text,
  animate,
  onDone,
}: {
  text: string;
  animate: boolean;
  onDone?: () => void;
}) {
  const [visible, setVisible] = React.useState(() => (animate ? 0 : text.length));
  const doneRef = React.useRef(onDone);
  doneRef.current = onDone;

  React.useEffect(() => {
    if (!animate) {
      setVisible(text.length);
      return;
    }

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced || text.length === 0) {
      setVisible(text.length);
      doneRef.current?.();
      return;
    }

    let frame = 0;
    const duration = Math.min(900, Math.max(280, text.length * 1.6));
    const start = performance.now();

    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / duration);
      setVisible(Math.max(1, Math.floor(progress * text.length)));
      if (progress < 1) {
        frame = requestAnimationFrame(tick);
      } else {
        doneRef.current?.();
      }
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [animate, text]);

  const streaming = animate && visible < text.length;

  return (
    <div className={streaming ? "streaming-caret" : undefined} aria-busy={streaming}>
      <Markdown>{text.slice(0, visible)}</Markdown>
    </div>
  );
}
