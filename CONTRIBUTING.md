# Contributing

このリポジトリは、公開サイトのソースと再現可能な検証だけを保持します。

## 公開ツリーに含めないもの

- 見出し生成の診断ログ、候補スコア、provider応答の要約
- 一時的な修正適用用・権限確認用・再実行トリガー用のGitHub Actions workflow
- Playwright成果物、テスト結果、ローカルブラウザプロファイル
- AI作業メモ、レビュー受け渡しファイル、ローカル状態
- Twitchコメント本文、ユーザー名、コメント単位の投稿時刻

診断情報が必要な場合は、短い保持期間を設定したGitHub Actions artifactとして保存してください。公開ソースへコミットしてから削除する運用は行いません。

一度だけ実行したい処理は、保守対象のworkflowへ `workflow_dispatch` 入力として追加するか、ローカルで実行してください。一時workflowをmainへ追加して直後に削除しないでください。

## 必須チェック

```bash
npm run setup
npm run verify
```

本物のTwitchとデプロイ済みRenderへ影響する変更だけ、通常ゲート成功後に`npm run verify:live`も実行します。

`check_repository_hygiene.py` は、診断サマリー、一時mutation workflow、ローカル成果物がGit追跡対象へ入っていないことを検証します。

## 履歴方針

既存の公開履歴は、秘密情報の漏洩が確認されていないため保持します。過去の試行コミットを隠す目的だけで履歴を書き換えません。今後はこのガードにより、内部診断や一時workflowを公開履歴へ追加しない運用とします。
