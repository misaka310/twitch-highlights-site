import { LayerCard, Pagination, Tabs } from "@cloudflare/kumo";
import type { HighlightSegment, VodData } from "../domain/vod.js";
import { VOD_PAGE_SIZE } from "../domain/vod.js";
import { formatDate } from "../lib/formatters.js";
import { HighlightList } from "./highlight-list.js";
import { StreamSummary } from "./stream-summary.js";

type VodRailProps = {
  vods: VodData[];
  activeVod: VodData;
  segments: HighlightSegment[];
  activeSegmentId: string;
  durationSec: number;
  playerState: string;
  positionSec: number;
  page: number;
  totalCount: number;
  onSelectVod: (vodId: string) => void;
  onSelectSegment: (segment: HighlightSegment) => void;
  onSetPage: (page: number) => void;
};

export function VodRail({
  vods,
  activeVod,
  segments,
  activeSegmentId,
  durationSec,
  playerState,
  positionSec,
  page,
  totalCount,
  onSelectVod,
  onSelectSegment,
  onSetPage,
}: VodRailProps) {
  const tabItems = vods.map((vod) => ({
    value: vod.vod_id,
    label: formatDate(vod.published_at, { month: "numeric", day: "numeric", weekday: "short" }),
  }));

  return (
    <aside className="highlight-column" aria-label="VODと見どころ一覧">
      <LayerCard>
        <LayerCard.Primary>
          <div className="rail-content">
            <Tabs tabs={tabItems} value={activeVod.vod_id} onValueChange={onSelectVod} />
            <HighlightList
              vodId={activeVod.vod_id}
              segments={segments}
              activeSegmentId={activeSegmentId}
              onSelect={onSelectSegment}
            />
          </div>
        </LayerCard.Primary>
      </LayerCard>

      <LayerCard>
        <LayerCard.Primary>
          <StreamSummary
            vod={activeVod}
            durationSec={durationSec}
            playerState={playerState}
            positionSec={positionSec}
          />
        </LayerCard.Primary>
      </LayerCard>

      <div className="pagination-wrap" aria-label="ページ移動">
        <Pagination
          page={page}
          perPage={VOD_PAGE_SIZE}
          totalCount={totalCount}
          setPage={onSetPage}
          controls="full"
        />
      </div>
    </aside>
  );
}
