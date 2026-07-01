import { memo, useEffect, useRef } from "react";
import type { RunStatus } from "../lib/types";

const LIVE: RunStatus[] = ["running", "waiting_for_user", "stopping"];

function base64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

/** Live browser panel. Frames arrive as base64 JPEG over the run's WebSocket; each is decoded to
 *  an ImageBitmap and drawImage'd onto a <canvas> — no per-frame data-URL string or <img> load.
 *  Painting is driven imperatively through subscribeFrame, so incoming frames never re-render
 *  React; latest-wins decoding means a burst is coalesced to the freshest frame, never queued. */
export const Viewport = memo(function Viewport({
  subscribeFrame,
  pageUrl,
  status,
  hasFrame,
}: {
  subscribeFrame: (cb: (b64: string) => void) => () => void;
  pageUrl: string | null;
  status: RunStatus;
  hasFrame: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const live = LIVE.includes(status);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    let cancelled = false;
    let decoding = false;
    let pending: string | null = null;

    const paint = (b64: string) => {
      if (decoding) {
        pending = b64; // still decoding the last one — keep only the freshest, drop the rest
        return;
      }
      decoding = true;
      // .buffer is exactly the freshly-allocated bytes; cast past TS's ArrayBufferLike widening.
      const buf = base64ToBytes(b64).buffer as ArrayBuffer;
      createImageBitmap(new Blob([buf], { type: "image/jpeg" }))
        .then((bmp) => {
          if (!cancelled) {
            if (canvas.width !== bmp.width || canvas.height !== bmp.height) {
              canvas.width = bmp.width;
              canvas.height = bmp.height;
            }
            ctx.drawImage(bmp, 0, 0);
          }
          bmp.close?.();
        })
        .catch(() => {})
        .finally(() => {
          decoding = false;
          if (pending !== null && !cancelled) {
            const next = pending;
            pending = null;
            paint(next);
          }
        });
    };

    const unsub = subscribeFrame(paint);
    return () => {
      cancelled = true;
      unsub();
    };
  }, [subscribeFrame]);

  // Clear between runs so a finished run's last frame doesn't linger behind "Waiting…".
  useEffect(() => {
    if (hasFrame) return;
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (canvas && ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
  }, [hasFrame]);

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-line bg-ink">
      <div className="flex items-center gap-2 border-b border-line bg-raised px-3 py-2">
        <span className={`h-2 w-2 rounded-full ${live ? "node-live bg-warn" : "bg-faint"}`} />
        <span className="font-mono text-[10px] uppercase tracking-wider text-faint">
          {live ? "Live" : "Browser"}
        </span>
        <span className="ml-1 min-w-0 flex-1 truncate font-mono text-[12px] text-muted">
          {pageUrl ?? ""}
        </span>
      </div>
      <div className="relative flex min-h-0 flex-1 items-center justify-center bg-black/40">
        <canvas ref={canvasRef} className="max-h-full max-w-full object-contain" />
        {!hasFrame && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
            <div className="node-live mb-3 h-2.5 w-2.5 rounded-full bg-accent" />
            <p className="text-sm text-muted">Waiting for the browser…</p>
          </div>
        )}
      </div>
    </div>
  );
});
