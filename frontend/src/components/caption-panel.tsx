import { useState } from "react";
import type { AnosaStatement, CaptionWindow } from "../lib/captions.js";

type CaptionPanelProps = {
  window: CaptionWindow;
  anosa: AnosaStatement[];
  onSeekAnosa?: (startSec: number) => void;
};

function CaptionLine({
  label,
  text,
  current = false,
}: {
  label: string;
  text: string;
  current?: boolean;
}) {
  return (
    <div className={current ? "caption-line caption-line--current" : "caption-line"}>
      <span className="caption-label">{label}</span>
      <span className="caption-text">{text || "―"}</span>
    </div>
  );
}

function formatTime(seconds: number): string {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

export function CaptionPanel({ window, anosa, onSeekAnosa }: CaptionPanelProps) {
  const [mode, setMode] = useState<"sync" | "anosa">("sync");
  if (!window.previous && !window.current && !window.next && anosa.length === 0) return null;

  return (
    <section className={mode === "anosa" ? "caption-panel caption-panel--anosa" : "caption-panel"} aria-label="文字起こし">
      <div className="caption-head">
        <strong>文字起こし</strong>
        <div className="caption-tabs" role="tablist" aria-label="文字起こし表示">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "sync"}
            className={mode === "sync" ? "caption-tab is-active" : "caption-tab"}
            onClick={() => setMode("sync")}
          >
            同期字幕
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "anosa"}
            className={mode === "anosa" ? "caption-tab is-active" : "caption-tab"}
            onClick={() => setMode("anosa")}
          >
            あのさ
          </button>
        </div>
      </div>

      {mode === "sync" ? (
        <>
          <CaptionLine label="前" text={window.previous?.text || ""} />
          <CaptionLine label="今" text={window.current?.text || ""} current />
          <CaptionLine label="次" text={window.next?.text || ""} />
        </>
      ) : (
        <div className="anosa-list" role="tabpanel" aria-label="あのさ一覧">
          {anosa.length === 0 ? (
            <p className="anosa-empty">意味が通る「あのさ」発話は見つかりませんでした。</p>
          ) : (
            anosa.map((row, index) => (
              <button
                key={`${row.start_sec}-${index}`}
                type="button"
                className="anosa-row"
                onClick={() => onSeekAnosa?.(row.start_sec)}
              >
                <span className="anosa-time">{formatTime(row.start_sec)}</span>
                <span className="anosa-text">{row.text}</span>
              </button>
            ))
          )}
        </div>
      )}
    </section>
  );
}
