# Data contract

## 原則

公開データには、Twitchコメントを集計して得た数値、見どころ区間、区間を説明する短い見出し、場面サムネイルだけを保存します。コメント本文、投稿者情報、文字起こし本文、外部動画の識別子は保存しません。

## `data/processed_vods.json`

日次更新の再利用キャッシュです。

各VODで保持するフィールド:

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

`items[]` の `headline` は内部エンリッチメントの結果であり、文字起こし不能などで生成できない場合は欠損を許容します。その場合、公開UIは `reason` を表示用見出しへ変換して使用します。`headline` と `reason` の両方が欠損して表示用見出しを解決できない項目は公開準備未完了として扱います。生成済み `headline` が存在する場合は公開品質検証を通過している必要があります。

## `data/vod_index.json`

公開期間内のVOD一覧です。各行は次のフィールドだけを持ちます。

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
- 外部動画のID・URL・照合結果
- 見出し生成に使った入力文、候補、プロンプト、モデル応答
- raw chatアーカイブ
