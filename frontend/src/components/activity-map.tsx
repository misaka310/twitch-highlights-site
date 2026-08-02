import type { MouseEventHandler } from "react";
import { Button, Empty } from "@cloudflare/kumo";
import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react";
import {
  ACTIVITY_CHART_HEIGHT,
  ACTIVITY_CHART_WIDTH,
  type ActivityGeometry,
  type ActivityOverlay,
} from "../lib/activity-geometry.js";
import { formatClock } from "../lib/formatters.js";

type ActivityMapProps = {
  geometry: ActivityGeometry | null;
  overlay: ActivityOverlay;
  positionSec: number;
  onSeek: MouseEventHandler<HTMLButtonElement>;
  onRewind: () => void;
};

export function ActivityMap({ geometry, overlay, positionSec, onSeek, onRewind }: ActivityMapProps) {
  return (
    <div className="activity-card">
      <div className="activity-head">
        <div className="activity-title-row">
          <span className="eyebrow">盛り上がりマップ</span>
          <span className="activity-help">クリックで移動</span>
        </div>
        <div className="activity-actions">
          <div className="activity-times">
            <strong>{formatClock(positionSec)}</strong>
            <span>{formatClock(overlay.durationSec)}</span>
          </div>
          <Button
            className="rewind-button"
            variant="secondary"
            size="sm"
            icon={ArrowCounterClockwiseIcon}
            onClick={onRewind}
          >
            10秒戻る
          </Button>
        </div>
      </div>
      {geometry ? (
        <button className="activity-chart" type="button" onClick={onSeek} aria-label="盛り上がりマップから再生位置を選ぶ">
          <svg viewBox={`0 0 ${ACTIVITY_CHART_WIDTH} ${ACTIVITY_CHART_HEIGHT}`} preserveAspectRatio="none" aria-hidden="true">
            <defs>
              <linearGradient id="activity-fill" x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor="rgba(103, 134, 176, 0.38)" />
                <stop offset="100%" stopColor="rgba(35, 51, 73, 0.04)" />
              </linearGradient>
            </defs>
            <path
              className="activity-progress"
              d={`M 0 ${ACTIVITY_CHART_HEIGHT} L 0 0 L ${(overlay.positionRatio * ACTIVITY_CHART_WIDTH).toFixed(2)} 0 L ${(overlay.positionRatio * ACTIVITY_CHART_WIDTH).toFixed(2)} ${ACTIVITY_CHART_HEIGHT} Z`}
            />
            <path className="activity-area" d={geometry.areaPath} />
            {overlay.segmentRangeWidth > 0 ? (
              <rect
                className="activity-segment-range"
                x={overlay.segmentRangeX}
                y="0"
                width={overlay.segmentRangeWidth}
                height={ACTIVITY_CHART_HEIGHT}
              />
            ) : null}
            {overlay.unavailableWidth > 0 ? (
              <rect
                className="activity-unavailable"
                x={overlay.unavailableX}
                y="0"
                width={overlay.unavailableWidth}
                height={ACTIVITY_CHART_HEIGHT}
              />
            ) : null}
            <line
              className="activity-marker"
              x1={overlay.positionRatio * ACTIVITY_CHART_WIDTH}
              x2={overlay.positionRatio * ACTIVITY_CHART_WIDTH}
              y1="0"
              y2={ACTIVITY_CHART_HEIGHT}
            />
          </svg>
        </button>
      ) : (
        <Empty title="盛り上がりデータなし" description="この配信にはマップ用データがありません。" />
      )}
    </div>
  );
}
