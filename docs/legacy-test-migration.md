# Legacy UI Test Migration

この文書は、`site/`を削除する前に旧UIテストの保護対象を失わないための対応表である。

| 旧テスト | 保護していた内容 | 移行先 | PR9での扱い |
|---|---|---|---|
| `tests/formatters.test.mjs` | 時刻・日付・理由文の整形 | `frontend/tests/unit/vod-domain.test.ts` | 一時維持 |
| `tests/site-shell.test.mjs` | 旧HTML/CSS/JSの構造 | 現行仕様では廃止済み | 一時維持 |
| `tests/latest-vods-public.spec.js` | 最新3VOD、見どころ、非公開文字起こし | `frontend/tests/preview.spec.ts`、`tests/public-build.spec.js` | 一時維持 |
| `tests/mobile-click-autoplay.spec.js` | モバイル1クリック再生・音声 | `frontend/tests/preview.spec.ts`のmobile project | 一時維持 |
| `tests/playback-policy.spec.js` | 初期mute、ユーザー操作後unmute、same/cross VOD | frontend unit/E2E | 一時維持 |
| `tests/player-portal.spec.js` | portal寸法、iframe重複、連続操作 | `frontend/tests/preview.spec.ts` | 一時維持 |
| `tests/rewind.spec.js` | 実再生位置基準の10秒戻る | `frontend/tests/preview.spec.ts` | 一時維持 |
| `tests/ui.spec.js` | PC/スマホレイアウト、ページャー、再生回帰 | `frontend/tests/preview.spec.ts` | 一時維持 |
| `tests/real-twitch.spec.js` | 実Twitch再生と描画健全性 | 現行frontend用live testへ移植 | PR10で移植 |
| `tests/production-mobile-playback.spec.js` | デプロイ済みスマホ再生 | 現行live testとして維持 | 維持 |
| `tests/public-build.spec.js` | 生成済み`public/` | 現行public testとして維持 | 維持 |

PR10では「一時維持」の旧テストを削除する前に、上表の移行先が標準`verify`に含まれることを再確認する。理由のない一括削除は禁止する。
