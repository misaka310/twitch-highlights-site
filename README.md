# Twitch Highlights Site

## 公開サイト

https://dotitao-moments.onrender.com/

Twitch VODのコメント量を時間帯ごとに集計し、変化が大きい区間を見どころとして表示する静的サイト基盤です。現在の公開インスタンスは`dotitao moments`です。対象チャンネル、サイト名、公開URLは`config/site.json`、チャンネル固有の追加タグ規則は`config/tag-rules.json`へ分離されているため、汎用ロジックを書き換えずに別のTwitchチャンネルへ切り替えられます。

> **非公式・非提携について**
> このプロジェクトは独立して開発された非公式ツールであり、Twitchまたは対象チャンネル・配信者の公式製品、提携製品、承認製品、スポンサー製品ではありません。Twitch、チャンネル名、配信者名および関連する名称・商標・コンテンツの権利は各権利者に帰属します。

このリポジトリに含まれる`config/site.json`は、現在の公開サイト`dotitao moments`用のサイト基本設定です。`config/tag-rules.json`は、現在のチャンネルにだけ追加するタグ規則です。汎用ロジック自体は特定の配信者名を前提にしません。

## 主な機能

- Twitch VOD一覧の取得
- コメント量の時系列集計と見どころ抽出
- Groqを利用した見どころ見出し生成とフォールバック
- Whisperを利用できる内部エンリッチメント処理
- 見どころを1クリックで音声付き再生
- 同一VODでのプレイヤー再利用とseek
- コメント量の盛り上がりマップ
- デスクトップ・スマートフォン対応
- 静的公開用`public/`の再現可能な生成
- GitHub Actionsによる定期データ更新

## 構成

```text
frontend/                    React + TypeScript + Vite + Cloudflare Kumoの公開UI
scripts/                     VOD更新、集計、見出し生成、公開ビルド（責務別moduleを含む）
data/                        公開可能な集計データとサムネイル
config/site.json             現在の公開インスタンスのサイト基本設定
config/tag-rules.json        現在のチャンネル固有の追加タグ規則
public/                      公開ビルドの生成先
```

公開UIは`frontend/`を正本とします。`scripts/build_public.sh`が本番バンドルを生成し、許可したVOD集計JSONと見どころサムネイルだけを`public/data/`へコピーします。

公開サイト全体の製品仕様は[`docs/PUBLIC_SITE_SPEC.md`](docs/PUBLIC_SITE_SPEC.md)を正本とします。UIや表示内容を変更する前に、ルートの[`AGENTS.md`](AGENTS.md)とあわせて確認してください。

## 再生仕様

- 初期表示では自動再生せず、ミュート状態で準備します。
- 見どころ、VODタブ、盛り上がりマップを押すと音声付きで再生します。
- 同じVOD内の移動はTwitch Player SDKのseekを使います。
- プレイヤー準備中は最後の操作を優先します。
- 10秒戻るは可能な限り実際の再生位置を基準にします。
- SDKを読み込めない場合はTwitch iframeへフォールバックします。

詳細は[`docs/PLAYBACK_SPEC.md`](docs/PLAYBACK_SPEC.md)を参照してください。

## インスタンス設定

`config/site.example.json`を参考に`config/site.json`へサイト名、公開URL、Twitchチャンネル、アクセス解析を設定します。`config/tag-rules.example.json`を参考に`config/tag-rules.json`へ、そのチャンネルにだけ必要な追加タグ規則を設定します。共通タグ規則はコード側に保持し、チャンネル固有の語だけを`tag-rules.json`へ追加します。

次の環境変数またはGitHub Repository Variablesでサイト基本設定を上書きできます。

- `TWITCH_CHANNEL`
- `TWITCH_CHANNEL_ID`
- `SITE_NAME`
- `SITE_DESCRIPTION`
- `SITE_BASE_URL`
- `SITE_LANGUAGE`
- `GOATCOUNTER_CODE`

## ローカル表示

Node.js 20以降を使用します。

```powershell
npm ci --prefix frontend
npm start
```

`http://localhost:4174/`を開きます。開発サーバーはリポジトリの`data/`を`/data/`として読み取り専用で配信します。

## VOD更新・文字起こしのローカル準備

公開画面だけを確認する場合、この追加準備は不要です。VOD更新、Whisper文字起こし、Groq見出し生成、場面サムネイル生成をローカルで実行する場合は、Python 3.11、FFmpeg、TwitchDownloaderCLI 1.56.4を用意し、次を実行します。

```powershell
python -m pip install -r requirements-transcribe.txt
Copy-Item .env.example .env
```

`.env`へTwitch API資格情報を設定します。Groqを使う場合だけ`GROQ_API_KEY`も設定します。依存バージョンとGitHub Actions上のTwitchDownloaderCLIアーカイブは固定・検証されています。

## 公開ビルド

```bash
sh scripts/build_public.sh
```

`public/`にはViteの静的バンドル、公開用VOD JSON、見どころサムネイル、`site-config.json`、favicon、robots、sitemapを生成します。Renderは`render.yaml`に従い`public/`を公開します。

## テスト

```powershell
npm run setup
npm run verify
```

Twitch実サービスとデプロイ済みRenderを確認する場合は、通常ゲート成功後に`npm run verify:live`を実行します。対象URLは`config/site.json`の`site.base_url`を正本とし、別環境を確認する場合だけ`LIVE_BASE_URL`で上書きします。

フロントE2EはTwitch SDK互換の偽プレイヤーを使い、初期再生方針、音声付きクリック再生、同一VODのseek、別VOD切替、last-click-wins、10秒戻る、PC・スマホ表示を外部通信なしで検証します。

## プライバシー

取得したTwitchコメントは解析中のメモリ上だけで処理します。コメント本文、ユーザー名、コメント単位の投稿時刻をリポジトリへ保存しません。公開データには時間帯ごとの件数、抽出済み見どころ、生成済み見出し、サムネイルなどの集計結果だけを含めます。

詳細は[`PRIVACY.md`](PRIVACY.md)と[`docs/data-contract.md`](docs/data-contract.md)を参照してください。

## License

[MIT License](LICENSE)
