import { PlayIcon } from "@phosphor-icons/react";
import { formatUpdate } from "../lib/formatters.js";

type SiteHeaderProps = {
  siteName: string;
  updatedAt: string;
  nextUpdateAt: string;
};

export function SiteHeader({ siteName, updatedAt }: SiteHeaderProps) {
  return (
    <header className="site-header">
      <div>
        <div className="brand-line">
          <PlayIcon weight="fill" aria-hidden="true" />
          <h1>{siteName}</h1>
        </div>
        <p>現在サブスク限定公開のため、新しい見どころは利用できません［非公式ファンサイト］</p>
      </div>
      <div className="update-stack" aria-label="更新情報">
        <span>データ更新: {formatUpdate(updatedAt)}</span>
        <span>自動更新: 一時停止中</span>
      </div>
    </header>
  );
}
