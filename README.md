# Twitch Highlights Site

## 公開サイト

[dotitao moments](https://dotitao-moments.onrender.com/)

Twitch VODのコメント量を時間帯ごとに集計し、変化が大きい区間を見どころとして表示する静的サイト基盤です。対象チャンネル、サイト名、公開URLは設定ファイルへ分離されているため、コードを書き換えずに別のTwitchチャンネルへ切り替えられます。

このリポジトリに含まれる`config/site.json`は、現在の公開サイト`dotitao moments`用のインスタンス設定です。汎用ロジック自体は特定の配信者名を前提にしません。

## 主な機能

- Twitch VOD一覧の取得
- コメント量の時系列集計と見どころ抽出
- 見どころへの直接再生
- コメント量の盛り上がりマップ
- 静的公開用の`public/`生成
- GitHub Actionsによる毎日更新

コメント集計と見どころ再生に必要なデータだけを扱います。

## インスタンス設定

`config/site.example.json`を参考に`config/site.json`を編集します。

```json
{
  "site": {
    "name": "Twitch Highlights",
    "description": "Twitch VODのコメント量から見どころを表示する非公式サイトです。",
    "base_url": "https://example.com",
    "language": "ja",
    "analytics": {
      "goatcounter_code": ""
    }
  },
  "twitch": {
    "channel_login": "your_channel",
    "channel_id": ""
  },
  "analysis": {
    "extra_tag_rules": []
  }
}
```

次の環境変数またはGitHub Repository Variablesで、設定ファイルの値を上書きできます。

- `TWITCH_CHANNEL`
- `TWITCH_CHANNEL_ID`
- `SITE_NAME`
- `SITE_DESCRIPTION`
- `SITE_BASE_URL`
- `SITE_LANGUAGE`
- `GOATCOUNTER_CODE`

TwitchのチャンネルIDを設定すると、API取得に失敗した場合のTwitchMetrics補助経路を利用できます。未設定でもTwitch API経路は動作します。

## ローカル表示

Node.js 20以降を使用します。

```powershell
npm ci
npm start
```

表示された`http://localhost:<port>/`をブラウザで開きます。通常はポート8000を使い、使用中の場合は次の空きポートへ移動します。

ローカル開発サーバーは`config/site.json`を読み、`/site-config.json`としてフロントエンドへ渡します。

## 公開ビルド

```bash
bash scripts/build_public.sh
```

`public/`に以下を生成します。

- 静的UI
- 公開用VOD JSON
- 見どころサムネイル
- `site-config.json`
- `robots.txt`
- `sitemap.xml`

## GitHub Actions

`.github/workflows/update-vods.yml`は毎日06:07 JSTに実行されます。手動実行も可能です。

Repository Secretsとして使用する値:

- `TWITCH_CLIENT_ID`
- `TWITCH_CLIENT_SECRET`

## プライバシー

取得したTwitchコメントは解析中のメモリ上だけで処理します。コメント本文、ユーザー名、コメント単位の投稿時刻をリポジトリへ保存しません。公開データには、時間帯ごとの件数や抽出済み見どころなどの集計結果だけを含めます。

詳細は[PRIVACY.md](PRIVACY.md)と[データ契約](docs/data-contract.md)を参照してください。

## テスト

```powershell
python -m unittest discover -s tests -p "test_*.py"
node --test tests/*.test.mjs
npx playwright test
```

## License

[MIT License](LICENSE)
