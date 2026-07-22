# Site Architecture

## 配置

- `site/`
  - ブラウザ向けの source of truth。
- `site/js/`
  - アプリ本体のブラウザモジュール。
- `public/`
  - `scripts/build_public.sh` が生成する配信用出力。
- `data/`
  - 公開 JSON と内部キャッシュ。
- `index.html`
  - ルートアクセスを `/site/` へ送る軽量 redirect。

## 配信経路

1. 開発中は `npm start` または `npm run dev` で `scripts/dev-server.mjs` を起動する。補足として repo ルート確認だけなら `python -m http.server 8000` も使える。
2. npm scripts のローカルサーバーでは `/` が `site/index.html` を直接返す。repo ルートを静的配信した場合は root `index.html` から `/site/` へ redirect される。
3. `site/index.html` は `./js/app.js` を読み込む。
4. `site/js/config.js` は `../../data/...` を参照する。
5. `scripts/build_public.sh` は `site/` の静的ファイルと `data/` の公開 JSON を `public/` にコピーする。
6. Render は `public/` をそのまま配信する。

## データ読込

- page 1 では `data/vods.json` fallback がある。
- 通常は `data/vod_index.json` を読んでから、対象 page の `detail_path` をたどる。
- detail JSON が 1 件も解決できない場合のみエラー扱いにする。

## プレイヤーまわり

- 画面構成は「左ステージ + 右レール」の 2 カラム。
- プレイヤーは iframe mount と interactive mount の 2 段構え。
- 再生 UX の期待値は `PLAYBACK_SPEC.md` に分けて管理する。

## 注意点

- `public/` は生成物なので、通常の説明は `site/` ベースで書く。
- 実装修正時に root / `site/` / `public/` の役割を混同しない。
