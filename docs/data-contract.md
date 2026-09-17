# Data contract

## YouTube provider

providerがyoutubeのVODでは、vod_idとvod_urlがYouTubeの公開再生対象を指す。Twitchの既存データではproviderを省略し、Twitchを既定値として扱う。

公開UIの表示対象はproviderを限定しない。TwitchとYouTubeのVODを同じ一覧・ページャー・VOD切替で扱い、providerに応じて再生経路を選ぶ。

YouTube Oracle出力に含まれるvideoOffsetTimeMsecは取得時だけcontent_offset_secondsへ変換し、保存対象は集計後の数値と見どころだけに限定する。

YouTube live_chatの実取得は、確定済みOracle VM（`64.110.102.170` / `ubuntu`）へSSHし、既存のOracle取得スクリプトを実行する経路だけを許可する。ローカルyt-dlpの直接実行結果をOracle取得結果として扱わず、Oracleスクリプトのログと一時TSVはメモリ上で解析する。一時TSVのコメント本文は見どころ判定中だけに使い、公開データへ保存しない。反応タグだけから見出しを生成してはならず、見出しは後段のWhisper/内容エンリッチメント結果から作る。

## 原則

公開データには、コメントを集計して得た数値、見どころ区間、区間を説明する短い見出し、場面サムネイルを保存します。コメント本文、投稿者情報、文字起こし本文、Oracleの生レスポンスは保存しません。再生に必要な`vod_id`と`vod_url`はproviderごとの公開再生参照として保持します。

## `data/processed_vods.json`

日次更新の再利用キャッシュです。

各VODで保持するフィールド:

- `provider`（YouTubeでは`youtube`、Twitchでは省略可）
- `vod_id`
- `vod_url`
- `title`
- `published_at`
- `thumbnail_url`
- `duration_sec`
- `count`
- `chat_total`
- `comments_per_hour`
- `items`
- `activity_map`
- `analysis_version`
- `analyzed_at`

`items[]`で保持するフィールド:

- `rank`
- `id`
- `start_sec`
- `end_sec`
- `duration_sec`
- `start_time`
- `end_time`
- `reason`
- `headline`
- `tags`
- `watch_url`
- `screenshot_url`

保存処理はホワイトリスト方式です。上記以外のキーは既存キャッシュに存在しても次回保存時に削除されます。

## `data/vods.json`

最新3件をトップ画面へ表示する公開データです。各VODは次のフィールドだけを持ちます。

- `provider`（YouTubeでは`youtube`、Twitchでは省略可）
- `vod_id`
- `vod_url`
- `title`
- `published_at`
- `thumbnail_url`
- `duration_sec`
- `count`
- `chat_total`
- `comments_per_hour`
- `items`
- `activity_map`

`items[]` の `headline` は内部エンリッチメントの結果です。YouTubeで文字起こし不能などにより生成できない場合、公開UIは見出し未生成として扱い、`reason` を表示用見出しへ変換しません。既存Twitchデータは互換維持のため、`headline` 欠損時に従来の `reason` 整形表示を許容します。YouTubeの `headline` が欠損する項目は公開準備未完了として扱い、生成済み `headline` は公開品質検証を通過している必要があります。

## `data/vod_index.json`

公開期間内のVOD一覧です。各行は次のフィールドだけを持ちます。

- `provider`（YouTubeでは`youtube`、Twitchでは省略可）
- `vod_id`
- `vod_url`
- `title`
- `published_at`
- `thumbnail_url`
- `duration_sec`
- `count`
- `chat_total`
- `comments_per_hour`
- `detail_path`

## `data/vods/{vod_id}.json`

個別VODの公開データです。構造は`data/vods.json`内の各VODと同一です。

## `activity_map`

- `bucket_sec`: 集計間隔。通常10秒
- `duration_sec`: VODまたはコメント分布の対象時間
- `last_comment_sec`: 最後にコメントが存在した時刻
- `buckets`: 時間帯ごとのコメント件数

## 保存禁止

次の情報はリポジトリへ保存しません。

- コメント本文、投稿者名、ユーザーID、コメント単位の投稿時刻
- 音声や文字起こし本文
- Oracleの生レスポンス、取得用コマンド、照合用の一時フィールド
- 見出し生成に使った入力文、候補、プロンプト、モデル応答
- raw chatアーカイブ
