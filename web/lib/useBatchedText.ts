"use client";

import { startTransition, useCallback, useEffect, useRef, useState } from "react";

/** Batch high-frequency stream chunks into one render per animation frame. */
export function useBatchedText() {
  const [text, setText] = useState("");
  const pendingRef = useRef("");
  const frameRef = useRef<number | null>(null);

  const flush = useCallback(() => {
    if (frameRef.current !== null) {
      cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }
    const chunk = pendingRef.current;
    pendingRef.current = "";
    if (chunk) {
      startTransition(() => setText((current) => current + chunk));
    }
  }, []);

  const append = useCallback((chunk: string) => {
    pendingRef.current += chunk;
    if (frameRef.current === null) {
      frameRef.current = requestAnimationFrame(() => {
        frameRef.current = null;
        const pending = pendingRef.current;
        pendingRef.current = "";
        if (pending) {
          startTransition(() => setText((current) => current + pending));
        }
      });
    }
  }, []);

  const reset = useCallback(() => {
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    frameRef.current = null;
    pendingRef.current = "";
    setText("");
  }, []);

  useEffect(() => () => {
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
  }, []);

  return { text, append, flush, reset };
}
