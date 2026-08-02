import { Badge, Empty } from "@cloudflare/kumo";
import { PlayIcon } from "@phosphor-icons/react";
import type { HighlightSegment } from "../domain/vod.js";
import { formatClock, localizeReason } from "../lib/formatters.js";
import { normalizeAssetPath } from "../lib/vod-data.js";

type HighlightListProps = {
  vodId: string;
  segments: HighlightSegment[];
  activeSegmentId: string;
  onSelect: (segment: HighlightSegment) => void;
};

export function HighlightList({ vodId, segments, activeSegmentId, onSelect }: HighlightListProps) {
  return (
    <div className="highlight-list">
      {segments.length > 0 ? segments.map((segment) => {
        const selected = segment.id === activeSegmentId;
        const title = String(segment.headline || localizeReason(segment.reason) || "見どころ").trim();
        return (
          <button
            key={segment.id}
            type="button"
            className={`highlight-item${selected ? " is-selected" : ""}`}
            data-vod-id={vodId}
            data-start-sec={segment.start_sec}
            aria-pressed={selected}
            onClick={() => onSelect(segment)}
          >
            <span className="thumb-wrap">
              {segment.screenshot_url ? (
                <img src={normalizeAssetPath(segment.screenshot_url)} alt="" loading="lazy" />
              ) : (
                <span className="thumb-fallback"><PlayIcon weight="fill" /></span>
              )}
              <span className="time-chip">{segment.start_time || formatClock(segment.start_sec)}</span>
            </span>
            <span className="highlight-copy">
              <strong>{title}</strong>
              <span className="tag-row">
                {(segment.tags || []).slice(0, 2).map((tag) => (
                  <Badge key={tag} className="highlight-tag" variant="neutral">{tag}</Badge>
                ))}
              </span>
            </span>
          </button>
        );
      }) : <Empty title="見どころなし" description="この配信には表示できる見どころがありません。" />}
    </div>
  );
}
