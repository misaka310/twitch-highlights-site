export type ActivityGeometry = {
  areaPath: string;
};

export type ActivityOverlay = {
  durationSec: number;
  positionRatio: number;
  segmentRangeX: number;
  segmentRangeWidth: number;
  unavailableX: number;
  unavailableWidth: number;
};

export const ACTIVITY_CHART_WIDTH = 1000;
export const ACTIVITY_CHART_HEIGHT = 88;

export function smoothBuckets(buckets: number[], radius: number): number[] {
  const safeRadius = Math.max(0, Math.floor(Number(radius) || 0));
  return buckets.map((_, index) => {
    let total = 0;
    let count = 0;
    for (let offset = -safeRadius; offset <= safeRadius; offset += 1) {
      const value = buckets[index + offset];
      if (value == null) continue;
      total += value;
      count += 1;
    }
    return count > 0 ? total / count : 0;
  });
}

export function downsampleBuckets(buckets: number[], maxPoints: number): number[] {
  const safeMaxPoints = Math.max(1, Math.floor(Number(maxPoints) || 1));
  if (buckets.length <= safeMaxPoints) return buckets;
  const chunkSize = Math.ceil(buckets.length / safeMaxPoints);
  const sampled: number[] = [];
  for (let index = 0; index < buckets.length; index += chunkSize) {
    const chunk = buckets.slice(index, index + chunkSize);
    if (chunk.length > 0) sampled.push(Math.max(...chunk));
  }
  return sampled;
}

export function createActivityGeometry(buckets: number[], compact: boolean): ActivityGeometry | null {
  if (buckets.length === 0) return null;
  const smoothed = smoothBuckets(buckets, compact ? 3 : 2);
  const sampled = downsampleBuckets(smoothed, compact ? 120 : 320);
  const peak = Math.max(1, ...sampled);
  const lastIndex = Math.max(1, sampled.length - 1);
  const points = sampled.map((value, index) => {
    const x = (index / lastIndex) * ACTIVITY_CHART_WIDTH;
    const y = ACTIVITY_CHART_HEIGHT - (Math.max(0, value) / peak) * (ACTIVITY_CHART_HEIGHT - 8);
    return `${x.toFixed(2)} ${y.toFixed(2)}`;
  });
  return {
    areaPath: `M 0 ${ACTIVITY_CHART_HEIGHT} L ${points.join(" L ")} L ${ACTIVITY_CHART_WIDTH} ${ACTIVITY_CHART_HEIGHT} Z`,
  };
}

export function createActivityOverlay(options: {
  durationSec: number;
  positionSec: number;
  segmentStartSec?: number;
  segmentEndSec?: number;
  lastCommentSec?: number;
}): ActivityOverlay {
  const durationSec = Math.max(0, Number(options.durationSec) || 0);
  const positionSec = Math.max(0, Math.min(Number(options.positionSec) || 0, durationSec));
  const positionRatio = durationSec ? Math.min(1, Math.max(0, positionSec / durationSec)) : 0;
  const segmentStartSec = Math.max(0, Math.min(Number(options.segmentStartSec) || 0, durationSec));
  const segmentEndSec = Math.max(0, Math.min(Number(options.segmentEndSec) || 0, durationSec));
  const segmentRangeX = durationSec ? (segmentStartSec / durationSec) * ACTIVITY_CHART_WIDTH : 0;
  const segmentRangeWidth =
    durationSec && segmentEndSec > segmentStartSec
      ? ((segmentEndSec - segmentStartSec) / durationSec) * ACTIVITY_CHART_WIDTH
      : 0;
  const lastCommentValue = Number(options.lastCommentSec);
  const lastCommentSec = Number.isFinite(lastCommentValue) && lastCommentValue >= 0
    ? Math.max(0, Math.min(lastCommentValue, durationSec))
    : durationSec;
  const unavailableX = durationSec ? (lastCommentSec / durationSec) * ACTIVITY_CHART_WIDTH : ACTIVITY_CHART_WIDTH;
  return {
    durationSec,
    positionRatio,
    segmentRangeX,
    segmentRangeWidth,
    unavailableX,
    unavailableWidth: Math.max(0, ACTIVITY_CHART_WIDTH - unavailableX),
  };
}
