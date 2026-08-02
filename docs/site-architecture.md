# Site Architecture

## 正本

- `frontend/`
  - React + TypeScript + Vite + Cloudflare Kumoによる公開UIの正本。
- `site/`
  - 移行前UIと互換挙動の参照元。公開UIの直接修正先ではない。
- `public/`
  - `scripts/build_public.sh` が生成する配信用出力。
- `data/`
  - 公開可能な集計JSON、個別VOD JSON、サムネイル、内部再利用キャッシュ。
- `config/site.json`
  - サイト名、説明、公開URL、Twitchチャンネル、アクセス解析設定。

製品仕様の正本は `docs/PUBLIC_SITE_SPEC.md`、再生状態遷移は `docs/PLAYBACK_SPEC.md`、データ形式は `docs/data-contract.md` とする。

## ローカル配信経路

1. `npm start` は `frontend/` のVite開発サーバーを `localhost:4174` で起動する。
2. `frontend/index.html` が `src/main.tsx` を読み込む。
3. `src/main.tsx` がKumo standalone CSS、`src/styles.css`、`App.tsx` を読み込む。
4. Viteプラグインがリポジトリ直下の `data/` を `/data/` として読み取り専用配信する。
5. Viteプラグインが `config/site.json` を `/site-config.json` として返す。
6. Viteプラグインが `site/favicon.svg` を `/favicon.svg` として返す。

## 公開配信経路

1. `scripts/build_public.sh` が `frontend/` をTypeScript・Viteでビルドする。
2. `public/` を再作成し、Viteバンドルを配置する。
3. 公開可能な `data/vod_index.json`、`data/vods.json`、個別VOD JSON、見どころサムネイルをコピーする。
4. `config/site.json` から `public/site-config.json` を生成する。
5. `site/favicon.svg` を `public/favicon.svg` へコピーする。
6. robots.txtとsitemap.xmlを生成する。
7. Renderは `public/` を静的配信する。

## データ読込

1. `data/vod_index.json` を読み、VODを `published_at` の新しい順へ並べる。
2. `page` クエリに応じて3件を選ぶ。
3. 各行の `detail_path` から `data/vods/{vod_id}.json` を読む。
4. 各VODの見どころを `rank`、なければ `start_sec` で並べ、先頭3件を表示する。

## プレイヤー

- Reactツリー内には寸法を決める `.player-frame` を残す。
- Twitchプレイヤー本体はbody直下のポータルへ置き、枠と位置・幅・高さを同期する。
- 初期表示ではiframeを即時表示し、Twitch SDKの準備後にinteractive playerへ移行できる。
- 同一VODの操作はinteractive playerをseekする。
- 別VODでは必要に応じてplayerを再生成する。
- SDKを利用できない場合はiframe表示を維持する。

## レスポンシブ

- PCは左再生領域と右情報レールの2カラム。
- 900px以下は1カラム。
- 600px以下では余白、見どころサムネイル、盛り上がりマップ高さをモバイル用へ縮小する。
- 基準PC `1792 x 864` では縦・横スクロールなしを受入条件とする。

## 注意点

- `public/` は生成物であり、直接修正しない。
- `site/` を公開UIの正本へ戻さない。
- UI変更時は `AGENTS.md` と `docs/PUBLIC_SITE_SPEC.md` を先に確認する。
