export type CaptionCue = {
  start_sec: number;
  end_sec: number;
  text: string;
};

export type CaptionData = {
  video_id: string;
  source: "youtube_manual_captions" | "youtube_automatic_captions";
  language: string;
  language_source?: string;
  fetched_at?: string;
  cues: CaptionCue[];
};

export type CaptionWindow = {
  previous: CaptionCue | null;
  current: CaptionCue | null;
  next: CaptionCue | null;
};

export function resolveCaptionWindow(cues: CaptionCue[], positionSec: number): CaptionWindow {
  if (!Array.isArray(cues) || cues.length === 0) {
    return { previous: null, current: null, next: null };
  }

  const position = Math.max(0, Number(positionSec) || 0);
  let low = 0;
  let high = cues.length - 1;
  let candidate = -1;

  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (Number(cues[middle]?.start_sec) <= position) {
      candidate = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }

  if (candidate < 0) {
    return { previous: null, current: null, next: cues[0] || null };
  }

  const cue = cues[candidate];
  const inCue = position <= Number(cue?.end_sec ?? cue?.start_sec ?? 0);
  const currentIndex = inCue ? candidate : -1;
  if (currentIndex >= 0) {
    return {
      previous: cues[currentIndex - 1] || null,
      current: cues[currentIndex] || null,
      next: cues[currentIndex + 1] || null,
    };
  }

  return {
    previous: cues[candidate] || null,
    current: null,
    next: cues[candidate + 1] || null,
  };
}
