# 🐻 Nikune Twitter Bot

お肉が大好きなキャラクター「nikune」が、お肉のおいしさを自動投稿するTwitterボット

[![Python](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## ✨ 概要

- **性格**: お肉に偏愛を持つキャラクター。丁寧語を使わず、断定的な口調が特徴
- **機能**: 定期ツイート投稿、フォロー中ユーザーの食関連ツイートへの自動引用リツイート、重複防止、動的コンテンツ生成
- **開発状況**: 2026-08-31にgo/no-go判断予定。**現在は本番デプロイ前のドライラン運用のみ**

キャラクターの人格・口調のサンプルは [`docs/CHARACTER_PERSONA_SAMPLE.md`](docs/CHARACTER_PERSONA_SAMPLE.md) を参照。このコードベースは特定のペルソナに固定されているわけではなく、任意のペルソナ定義に差し替えて動かせる設計を想定している。

### 🚀 主な機能

- ✅ **定期ツイート投稿**: スケジューラーによる自動投稿（デフォルト 09:00 / 13:30 / 19:00）
- ✅ **自動引用リツイート**: フォロー中ユーザーの食関連ツイート（お肉＋食・レストラン全般）を検出し、優先度に応じてコメント付きで引用リツイート
- ✅ **重複防止**: Redisキャッシュ＋処理済みID追跡によるテンプレート・ツイートの重複回避
- ✅ **動的コンテンツ**: 時間・挨拶の自動挿入
- ✅ **カテゴリ・トーン管理**: 柔軟なテンプレート分類
- ✅ **ドライランモード**: 実際の投稿・API呼び出しを行わない安全なテスト実行
- ✅ **自動起動・監視**: launchd/systemd常駐、異常終了時の自動再起動、Slack/LINE通知
- ✅ **クロスプラットフォーム対応**: Windows/Mac/Linux対応

## 🛠️ セットアップ

### 📋 前提条件

- **Python 3.13以上**（`uv`が自動管理するため個別インストール不要）
- **[uv](https://docs.astral.sh/uv/)**（パッケージ・仮想環境管理）
- **Redis Server**（必須：重複防止機能とシステム安定性に必要）
- **Twitter API v2** アクセス権限

### 1. 🐍 環境準備

```bash
# uvが依存関係と仮想環境を自動的に用意する（手動activate不要）
uv sync
```

### 2. 🔗 Redis セットアップ（必須）

> ⚠️ **重要**: Redisはシステム動作に必須です。接続できない場合、アプリケーションは起動しません。

```bash
# macOS (Homebrew)
brew install redis
brew services start redis

# Ubuntu/Debian
sudo apt update && sudo apt install -y redis-server
sudo systemctl start redis-server

# Docker（プラットフォーム共通）
docker run -d -p 6379:6379 redis:alpine
```

接続確認: `redis-cli ping` → `PONG` が返ればOK

### 3. 🔑 環境変数の設定

`.env` ファイルをプロジェクトルートに作成する（`.gitignore`対象、リポジトリにはコミットしない）：

```env
# Twitter API v2 設定
TWITTER_API_KEY=your_api_key
TWITTER_API_SECRET=your_api_secret
TWITTER_ACCESS_TOKEN=your_access_token
TWITTER_ACCESS_TOKEN_SECRET=your_access_token_secret
TWITTER_BEARER_TOKEN=your_bearer_token

# Redis設定
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# NGワード（本番投稿前に必須。カンマ区切り、または NG_KEYWORDS_FILE でファイル指定）
NG_KEYWORDS=

# 通知（任意、自動起動時のみ使用）
# SLACK_WEBHOOK_URL=
# LINE_CHANNEL_ACCESS_TOKEN=
# LINE_TARGET_IDS=
```

### 4. 🗄️ データベースの初期化

```bash
# 全システムテスト（推奨：環境確認）
uv run python main.py --test

# サンプルデータでデータベースを初期化
uv run python main.py --setup-db --file data/sample_templates.tsv
```

### ⚡ クイックスタート（ドライラン確認）

```bash
uv sync
brew services start redis   # 環境に応じたRedis起動方法を使用
uv run python main.py --test
uv run python main.py --post-now --dry-run
uv run python main.py --quote-check --dry-run
```

## 🎮 使用方法

```bash
# 🧪 全システムテスト（推奨：最初に実行）
uv run python main.py --test

# 💚 システムヘルスチェック
uv run python main.py --health

# 🐻 即座に1回ツイート投稿
uv run python main.py --post-now
uv run python main.py --post-now --category お肉
uv run python main.py --post-now --text "カスタムテキスト"
uv run python main.py --post-now --dry-run

# 🍽️ 食関連ツイート（お肉＋食・レストラン全般）をチェックして引用リツイート
uv run python main.py --quote-check
uv run python main.py --quote-check --dry-run

# ⏰ スケジューラーを開始（デフォルト：09:00, 13:30, 19:00 投稿、10:30/15:00/21:00 引用チェック）
uv run python main.py --schedule

# 📥 テンプレートインポート
uv run python main.py --setup-db --file data/your_templates.tsv
```

## データファイル

### リポジトリに含まれるファイル（マスタ・サンプルのみ）

- `data/sample_templates.tsv` — サンプルテンプレート
- `data/category.tsv` — カテゴリマスタデータ
- `data/tone.tsv` — トーンマスタデータ

### 実データファイル（`.gitignore`対象、非公開Google Sheet「tweet_template」由来）

このリポジトリはPUBLICであり、未公開のツイート候補文言・キャラクターの具体的なセリフは一切コミットしない方針。実データは非公開スプレッドシートで管理し、以下はそのエクスポート：

- `data/templates.db` — SQLiteデータベース
- `data/tweet_templates.tsv` — 手入力テンプレート
- `data/tweet_templates.generated.tsv` — AI生成テンプレート（ドラフト）
- `data/quote_comments.tsv` — 引用リツイート時のコメント文言（未配置時は最小限のフォールバックのみで動作）
- `data/exported_templates.tsv` — エクスポートされたテンプレート

## 📁 プロジェクト構造

```
nikune/
├── 📄 main.py                        # メインエントリーポイント（CLI）
├── 📁 config/
│   └── settings.py                   # 環境変数管理
├── 📁 nikune/
│   ├── content_generator.py          # 🎨 ツイート/引用コメント生成、食関連キーワード検出
│   ├── auto_quote_retweeter.py       # 🔄 自動引用リツイート
│   ├── database.py                   # 🗄️ SQLite + Redis管理
│   ├── scheduler.py                  # ⏰ 自動投稿スケジューラー
│   ├── twitter_client.py             # 🐦 Twitter API v2クライアント
│   ├── health_check.py               # 💚 システムヘルスチェック
│   └── utils.py                      # 共通ユーティリティ
├── 📁 scripts/
│   └── nikune_service_runner.py      # 自動起動ラッパー・Slack/LINE通知
├── 📁 docs/
│   └── CHARACTER_PERSONA_SAMPLE.md   # キャラクターペルソナのサンプル
├── 📁 tests/
│   ├── test_content_generator.py
│   ├── test_auto_quote_retweeter.py
│   └── test_nikune_service_runner.py
├── 📁 data/                          # マスタ・サンプル（実データはgitignore対象）
├── ⚙️ pyproject.toml                  # 依存関係・Black/isort/mypy/pytest設定
├── 🔧 .flake8                        # コード品質設定
├── ✅ check_code.sh                   # 品質チェック一括実行（black/isort/flake8/mypy/pytest）
├── 🎯 .gitattributes                  # Git属性（LF統一）
├── 🚫 .gitignore
└── 🐍 .python-version
```

## 💻 開発環境

### 🔧 コード品質チェック

```bash
# 一括実行（black → isort → flake8 → mypy → mypy --strict → pytest）
./check_code.sh

# 個別実行
uv run black .
uv run isort .
uv run flake8 nikune/ main.py config/ tests/
uv run mypy .
uv run mypy --strict .
uv run pytest tests/
```

設定ファイル: `pyproject.toml`（Black line-length=120, isort, mypy, pytest）、`.flake8`（120文字制限）。両方リポジトリにコミット済みの共有設定。

### 🌍 クロスプラットフォーム対応

- ✅ **Windows**: WSL2 + Redis対応
- ✅ **macOS**: Homebrew + Redis対応
- ✅ **Linux**: 直接Redis使用
- ✅ **改行コード**: LF統一（`.gitattributes`）

### テンプレート・カテゴリの追加

1. 実データは非公開スプレッドシートで起草・管理し、`data/*.tsv`としてエクスポートする
2. `uv run python main.py --setup-db` でデータベースを更新
3. カテゴリ・トーンのマスタ拡張は `data/category.tsv` / `data/tone.tsv` を編集

## 🔧 トラブルシューティング

#### Redis接続エラー
```bash
redis-cli ping   # PONGが返らない場合は起動していない
brew services start redis        # macOS
sudo systemctl start redis-server # Linux
```

#### Twitter API認証エラー
- `.env`ファイルの設定を確認
- Twitter Developer Portalでトークンを再生成

#### NGワード未設定の警告
- `⚠️ NGワードリストが見つかりませんでした` はドライラン時は無害だが、**本番投稿を開始する前に`NG_KEYWORDS`または`ng_keywords.txt`を必ず設定する**

#### 依存関係エラー
```bash
uv sync --frozen
```

## 🤝 コントリビューション

1. このリポジトリをフォーク
2. 機能ブランチを作成: `git checkout -b feature/amazing-feature`
3. コード品質チェック: `./check_code.sh`
4. 変更をコミット: `git commit -m 'feat: add amazing feature'`
5. ブランチをプッシュ: `git push origin feature/amazing-feature`
6. Pull Requestを作成

### 📝 コミット規約

- `feat:` 新機能
- `fix:` バグ修正
- `chore:` 雑務・設定変更
- `docs:` ドキュメント更新

## 📄 ライセンス

MIT License - 詳細は [LICENSE](LICENSE) ファイルを参照

## ⚠️ 注意事項

- 🔒 このリポジトリは**PUBLIC**。未公開のツイート候補文言・キャラクターの具体的なセリフはコミットしない（実データファイル・`.env`は`.gitignore`対象）
- 🐦 Twitter API利用規約を遵守してください
- 🔧 本番投稿を開始する前に、`NG_KEYWORDS`の設定を必ず確認すること

## 🛡️ 自動起動と監視

### 1. Slack 通知の準備
- Slack の Incoming Webhook URL を取得し、環境変数 `SLACK_WEBHOOK_URL` に設定（任意で `SLACK_WEBHOOK_USERNAME`, `SLACK_WEBHOOK_ICON_EMOJI` も使用可）
- 通知が不要な場合は設定不要（Webhook が未設定なら Slack 通知は送信されません）

### 2. LINE 通知の準備（任意）
- LINE Developers で Messaging API を構築し、チャネルアクセストークンを取得
- `.env` などに `LINE_CHANNEL_ACCESS_TOKEN` を保存
- 送信先となる `userId` や `groupId` を取得し、カンマ区切りで `LINE_TARGET_IDS` に設定
  例: `LINE_TARGET_IDS=Uxxxxxxxxx,Uyyyyyyyyy`
- どちらも未設定なら LINE 通知は送信されません

### 3. サービスラッパーの利用
- `uv run python scripts/nikune_service_runner.py` でスケジューラーが常駐起動します
- 既定では `main.py --schedule` を実行し、異常終了時に 5 秒待って自動再起動します
- 主な環境変数
  - `NIKUNE_SERVICE_COMMAND`: 実行コマンドを上書きしたい場合（例: `"uv run python main.py --schedule"`）
  - `NIKUNE_RESTART_DELAY`: 再起動までの待機秒数（既定: 5）
  - `NIKUNE_MAX_RESTARTS`: 再起動上限を設定したい場合

### 4. macOS (launchd) で常駐起動
1. `~/Library/LaunchAgents/com.nikune.bot.plist` を作成し、以下の内容を保存

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.nikune.bot</string>
    <key>ProgramArguments</key>
    <array>
      <string>/usr/bin/env</string>
      <string>python3</string>
      <string>/path/to/nikune/scripts/nikune_service_runner.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/nikune</string>
    <key>EnvironmentVariables</key>
    <dict>
      <key>SLACK_WEBHOOK_URL</key>
      <string>https://hooks.slack.com/services/xxxxx/yyyyy/zzzzz</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/path/to/nikune/logs/nikune.launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/path/to/nikune/logs/nikune.launchd.err</string>
  </dict>
</plist>
```

2. ログ用ディレクトリが未作成なら `mkdir -p /path/to/nikune/logs`
3. `launchctl load ~/Library/LaunchAgents/com.nikune.bot.plist`
4. 停止・再起動は `launchctl unload` / `launchctl kickstart` で実施

### 5. Linux (systemd) への転用（参考）
- `/etc/systemd/system/nikune.service` の例

```ini
[Unit]
Description=nikune Twitter bot (scheduler)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/nikune
Environment=SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxxxx/yyyyy/zzzzz
ExecStart=/usr/bin/python3 /opt/nikune/scripts/nikune_service_runner.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- `sudo systemctl daemon-reload && sudo systemctl enable --now nikune.service` で有効化
- 詳細な監視条件や通知拡張は Slack 通知を基点に追加実装可能
