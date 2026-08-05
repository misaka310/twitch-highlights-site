# Public Site Operations

この文書は、公開、VOD更新、保護ブランチとGitHub Actionsの運用仕様の正本である。画面仕様は `PUBLIC_SITE_SPEC.md`、再生仕様は `PLAYBACK_SPEC.md` を参照する。

## 標準検証

依存関係は検証と分離し、初回またはlockfile更新時だけ次を実行する。

```text
npm run setup
```

ローカルとPull Request CIの製品必須ゲートは、リポジトリルートの次のコマンドを正本とする。

```text
npm run verify
```

このゲートはfrontendのtypecheck、lint、単体テスト、Pythonテスト、frontend E2E、`public/`生成・内容検証・同一環境での再生成一致、生成済み`public/`の静的配信E2E、repository hygieneを含む。本物のTwitchとデプロイ済みRenderへ依存する検証は含めない。

Twitchプレイヤーまたは公開経路へ影響する変更は、通常ゲート成功後かつデプロイ完了後に次を独立実行する。

```text
npm run verify:live
```

本番URLは`config/site.json`の`site.base_url`から解決し、`LIVE_BASE_URL`が指定された場合だけ上書きする。HTMLは配信基盤が除去する空行を無視して照合し、JavaScript・CSS・設定ファイルは内容hashを一致させる。検証対象URLが空の場合はskipせず設定エラーとして失敗させる。

## 公開フロー

1. `main` から `release/**` ブランチを作る。
2. `npm run verify` を通し、意図したファイルだけをコミットしてpushする。
3. `.github/workflows/publish-release.yml` が同一リポジトリ内のPRを作成する。
4. `public-readiness`、`Frontend CI`、`Repository hygiene`、`Repo Launch Doctor` を対象SHAで確認する。
5. `action_required` のrunは、差分とworkflow変更を確認したうえでActions write権限により承認する。
6. 必須runがすべて成功してからsquash mergeし、releaseブランチを削除する。
7. Render上のHTML、公開データ、PC・スマホ表示を確認し、必要な変更では `npm run verify:live` を通す。

PR番号、run ID、コミットSHAをworkflowへ固定値として残さない。実行時に対象ブランチとhead SHAから解決し、マージ直前にもPR headが変わっていないことを確認する。
PR作成、対象SHAの検証、head SHA確認、squash mergeは`.github/scripts/checked_pr_merge.py`を共通経路とする。通常のrelease PRは`pull_request` runを待ち、`automation/update-vods`はworkflow内tokenから承認待ちrunを参照できないため、3つの必須workflowを`workflow_dispatch`で対象SHAへ明示実行する。

## 定期VOD更新

- `.github/workflows/update-vods.yml` は毎日 **06:07 JST** に処理を開始し、**09:00 JSTまでの公開反映**を目標とする。
- GitHub ActionsのcronはUTCなので、正本は `7 21 * * *` とする。毎時0分を避けて開始遅延を抑える。
- GitHub側の混雑により実際の開始・完了が遅れることはある。画面の「次回更新予定」は処理開始時刻ではなく、公開反映目標の09:00 JSTを表示する。
- 手動更新は `workflow_dispatch` で `main` を指定する。
- `data/vods.json` は公開トップ用の最新3件、`data/vod_index.json` は保持期間内の一覧を持つ。
- 更新データは `automation/update-vods` ブランチとPRを経由し、公開準備チェック成功後にmainへマージする。

## GITHUB_TOKENと連鎖実行

`GITHUB_TOKEN` を使ったpushやmergeが発生させた通常イベントは、別workflowを自動起動しない。後続処理が必要な場合は、対象workflowを `workflow_dispatch` で明示的に実行し、作成されたrunのevent、head SHA、結果を確認する。

workflow badgeやブランチ更新だけで成功判定しない。対象runを特定し、`queued`、`in_progress`、`action_required`、`completed` と最終conclusionを確認する。

## 更新PRが止まった場合

1. `automation/update-vods` のSHAとPR head SHAが一致するか確認する。
2. 必須workflowのrunを対象SHAで列挙する。
3. `action_required` の場合は差分を確認して承認する。
4. 全runの成功後に、head SHA一致条件付きでマージする。
5. main、公開URLの `data/vods.json`、`updated_at`、最新VOD IDを確認する。

一時的なPR番号・run ID専用workflowをmainへ残さない。障害対応で一時ブランチを使った場合は、完了後にリモート・ローカル双方を削除する。

## 完了条件

- mainとorigin/mainが一致している。
- 作業ツリー、stash、一時releaseブランチが残っていない。
- `npm run verify` が成功している。
- 公開URLがKumo版の静的バンドルを返す。
- 公開データの `updated_at` と最新3件がmainと一致する。
- 次回の定期更新が09:00 JSTとして表示される。
