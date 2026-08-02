import type { VodData } from "../domain/vod.js";
import { formatChatVolume, formatClock, formatDate } from "../lib/formatters.js";

type StreamSummaryProps = {
  vod: VodData;
  durationSec: number;
  playerState: string;
  positionSec: number;
};

export function StreamSummary({ vod, durationSec, playerState, positionSec }: StreamSummaryProps) {
  return (
    <section className="stream-summary" aria-label="この配信について">
      <h3>この配信について</h3>
      <dl>
        <div><dt>配信タイトル</dt><dd>{String(vod.title || "").trim() || "―"}</dd></div>
        <div><dt>配信日時</dt><dd>{formatDate(vod.published_at, { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}</dd></div>
        <div><dt>長さ</dt><dd>{durationSec > 0 ? formatClock(durationSec) : "―"}</dd></div>
        <div><dt>チャット量</dt><dd>{formatChatVolume(vod)}</dd></div>
        <div><dt>再生状態</dt><dd>{playerState}</dd></div>
        <div><dt>再生位置</dt><dd>{formatClock(positionSec)}</dd></div>
      </dl>
    </section>
  );
}
