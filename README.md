# nikune

お肉が大好きなキャラクター「nikune」として、X（旧Twitter）に独り言を定期投稿し、フォロー中の人の食べ物の投稿にコメントを付けて引用する bot。

[![Python](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

本番で運用している。デプロイの時期や既知の未対応事項は [`AGENT.md`](AGENT.md) の「Development Status」にまとめている。

キャラクターの人格と口調のサンプルは [`docs/CHARACTER_PERSONA_SAMPLE.md`](docs/CHARACTER_PERSONA_SAMPLE.md) にある。コードは特定のペルソナに縛られていない。`data/` に置くテンプレート、引用コメント、ペルソナの TSV を差し替えれば、別のキャラクターでも動く。

## できること

- テンプレートから独り言を選んで投稿する。同じテンプレートが続かないよう、Redis で直近の使用を記録している
- タイムラインと検索から食べ物の投稿（お肉と、寿司・カレー・ラーメンなど食・レストラン全般）を見つけ、キーワードに合わせたコメントを付けて引用する
- 引用は1日1回までの抽選にできる。朝・昼・晩に起動して回ごとの確率を変えると、引用する時間帯がばらける
- 引用候補は TypeSafe の Jev で安全かどうかを判定し、事故や炎上に絡む投稿を避ける。自分の投稿も投稿直前に Jev でチェックする（現状は警告のログを出すだけで、投稿は止めない）
- ドライランで、投稿や API 呼び出しをせずに動きを確かめられる
- cron で動かす場合はログを確認するスクリプトが、常駐させる場合はサービスラッパーが、異常のときだけ Slack（任意で LINE）に通知する

## セットアップ

必要なのは [uv](https://docs.astral.sh/uv/)、Redis、X API v2 のアクセス権である。Python 3.13 は uv が用意するので、別に入れなくてよい。

```bash
uv sync
```

Redis は重複防止に使っていて、つながらないと起動しない。

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

`redis-cli ping` で `PONG` が返れば動いている。

プロジェクトルートに `.env` を作る。`.gitignore` の対象なので、リポジトリには入らない。

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

# TypeSafe (Jev) による引用RT候補の安全判定（任意。未設定なら判定なしで従来どおり動作）
# TYPESAFE_API_KEY=
# TYPESAFE_MODEL=jev-1.13.0        # 既定はバージョン固定。上げるときはしきい値を再検証する
# TYPESAFE_TIMEOUT_SECONDS=10

# 通知（任意。cron運用時のログ確認・常駐時のサービスラッパーで使用）
# SLACK_WEBHOOK_URL=
# LINE_CHANNEL_ACCESS_TOKEN=
# LINE_NOTIFY_ENABLED=false
```

最後に動作を確かめ、サンプルのテンプレートでデータベースを作る。

```bash
uv run python main.py --test
uv run python main.py --setup-db --file data/sample_templates.tsv
uv run python main.py --post-now --dry-run
uv run python main.py --quote-check --dry-run
```

開発は macOS、本番は Linux で動かしている。Windows では WSL2 の上で Redis を使う。改行コードは `.gitattributes` で LF にそろえている。

## 使い方

```bash
# 全コンポーネントのテストと、ヘルスチェック
uv run python main.py --test
uv run python main.py --health

# 独り言を1回投稿する
uv run python main.py --post-now
uv run python main.py --post-now --category お肉
uv run python main.py --post-now --text "カスタムテキスト"
uv run python main.py --post-now --dry-run

# 食べ物の投稿を探して引用する
uv run python main.py --quote-check
uv run python main.py --quote-check --dry-run
uv run python main.py --quote-check --chance 0.5   # 今日まだ引用していなければ、50%の確率で探す

# スケジューラーを常駐させる
uv run python main.py --schedule

# テンプレートを取り込む
uv run python main.py --setup-db --file data/your_templates.tsv
```

`--schedule` で常駐させたときの時刻はコードの既定値で、投稿が 09:00 / 13:30 / 19:00、引用のチェックが 10:30 / 15:00 / 21:00 である。本番は常駐させず、cron から `--post-now` と `--quote-check` を直接呼んでいる。その時刻は [`AGENT.md`](AGENT.md) に書いてある。

`--chance` を付けると、1日1回までの抽選になる。今日すでに引用していれば何もせず、まだなら指定した確率でだけ候補を探す。朝・昼・晩の3回起動するなら、確率を 0.25 / 0.3333 / 0.5 にすると、朝・昼・晩・引用なしがそれぞれ25%になる。

## データファイル

このリポジトリは公開しているので、未公開のツイート文言やキャラクターの具体的なセリフはコミットしない。実データは非公開のスプレッドシート「tweet_template」で管理し、TSV に書き出して `data/` に置く。

リポジトリに入っているのは、マスタとサンプルだけである。

- `data/sample_templates.tsv`（サンプルのテンプレート）
- `data/category.tsv`（カテゴリのマスタ）
- `data/tone.tsv`（トーンのマスタ）

次のファイルは `.gitignore` の対象になっている。

- `data/templates.db`（SQLite のデータベース。テンプレートと引用の履歴を持つ）
- `data/tweet_templates.tsv`（手で書いたテンプレート）
- `data/tweet_templates.generated.tsv`（AI で生成したテンプレートの下書き）
- `data/quote_comments.tsv`（引用するときのコメント文言。スプレッドシートの quote_comments タブから書き出す。ないときはコードの最小限の文言を使う）
- `data/persona.tsv`（投稿直前チェックで口調を照らし合わせるペルソナ）
- `data/exported_templates.tsv`（`nikune/database.py` の `export_templates_to_tsv()` を使ったときだけできる。普段の運用では作られない）

テンプレートを足すときは、スプレッドシートで書いて `data/*.tsv` に書き出し、`uv run python main.py --setup-db` でデータベースを更新する。カテゴリとトーンを増やすときは `data/category.tsv` と `data/tone.tsv` を直接編集する。

## プロジェクト構造

```
nikune/
├── main.py                        # CLI のエントリーポイント
├── config/
│   └── settings.py                # 環境変数の管理
├── nikune/
│   ├── content_generator.py       # 独り言と引用コメントの生成、食べ物キーワードの検出
│   ├── auto_quote_retweeter.py    # 自動引用（レート制限と引用履歴）
│   ├── database.py                # SQLite と Redis の管理
│   ├── scheduler.py               # 常駐時のスケジューラー
│   ├── twitter_client.py          # X API v2 のクライアント
│   ├── jev_checker.py             # TypeSafe (Jev) への問い合わせ
│   ├── quote_safety.py            # 引用候補の安全判定
│   ├── post_safety.py             # 自分の投稿の投稿直前チェック
│   ├── emoji_rules.py             # 独り言の絵文字ルール
│   ├── health_check.py            # ヘルスチェック
│   ├── notifications.py           # Slack と LINE の通知
│   └── utils.py
├── scripts/
│   ├── check_logs.py              # cron 運用時のログ確認（異常のときだけ通知）
│   └── nikune_service_runner.py   # 常駐運用時の自動起動ラッパー
├── docs/
│   └── CHARACTER_PERSONA_SAMPLE.md
├── tests/                         # pytest
├── data/                          # マスタとサンプル（実データは .gitignore の対象）
├── pyproject.toml                 # 依存関係と black / isort / mypy / pytest の設定
├── .flake8
├── check_code.sh                  # 品質チェックの一括実行
└── THIRD_PARTY_LICENSES.md        # NGワード辞書に使った OSS のライセンス表記
```

## 開発

品質チェックは `./check_code.sh` でまとめて走る。black、isort、flake8、mypy、mypy --strict、pytest の順に実行する。

```bash
./check_code.sh

# 個別に実行する場合
uv run black .
uv run isort .
uv run flake8 nikune/ main.py config/ tests/
uv run mypy .
uv run mypy --strict .
uv run pytest tests/
```

設定は `pyproject.toml`（black の行長 120、isort、mypy、pytest）と `.flake8`（120文字）にあり、どちらもコミットしてある。

### NGワード

NGワードは、引用候補の投稿本文を弾くために使う。独り言の投稿には使わない。判定の処理は `nikune/content_generator.py` の `get_food_keyword_score()` にある。

入れるのは、単語だけで不適切と言い切れるもの（性的な表現、差別語、暴言）と、事件や事故や暴力、自傷に関わる語である。スパムや詐欺の定番の語や、ヴィーガンと肉食の論争のように対立を招きやすい話題の語も入れる。「部落」「屠殺」のように日常語や歴史の語と重なるものは、食べ物の投稿まで弾いてしまうおそれが大きいので、安易に足さない。

変えるときは、プロジェクトルートの `ng_keywords.txt`（`.gitignore` の対象）を直接編集する。1行に1語で、`#` で始まる行はコメントになる。公開されている OSS の辞書を取り込むならライセンスを確かめ、[`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md) に出典を書き足す。そのあと `uv run python main.py --quote-check --dry-run` で、実際の候補を誤って弾いていないか確かめる。

## トラブルシューティング

Redis につながらないときは、起動しているかを確かめる。

```bash
redis-cli ping   # PONGが返らない場合は起動していない
brew services start redis        # macOS
sudo systemctl start redis-server # Linux
```

X API の認証で失敗するときは、`.env` の値を見直し、それでも駄目なら Developer Portal でトークンを作り直す。

`⚠️ NGワードリストが見つかりませんでした` という警告は、ドライランでは害がない。本番で投稿を始める前には、`NG_KEYWORDS` か `ng_keywords.txt` を必ず設定する。

依存関係でエラーが出たら、ロックファイルどおりに入れ直す。

```bash
uv sync --frozen
```

## 通知と自動起動

### Slack と LINE

Slack に通知するには、Incoming Webhook の URL を `SLACK_WEBHOOK_URL` に入れる。`SLACK_WEBHOOK_USERNAME` と `SLACK_WEBHOOK_ICON_EMOJI` も使える。URL を設定しなければ、Slack には何も送らない。

LINE は Messaging API の broadcast で、友だち登録した全員に送る。`userId` や `groupId` を登録する必要はない。チャネルアクセストークンを `LINE_CHANNEL_ACCESS_TOKEN` に入れ、`LINE_NOTIFY_ENABLED=true` にしたときだけ送る（既定は `false`）。運用を始めた直後は Slack だけで通知し、見る頻度が落ちてきたら LINE も有効にするつもりでいる。

### cron で動かす場合

cron から `main.py --post-now` や `--quote-check` を1回ずつ起動するなら、サービスラッパーは使わない。代わりに、各回の数分後に `scripts/check_logs.py` を起動してその回のログを確かめ、異常があるときだけ通知する。正常なら何も送らない。

```bash
uv run python scripts/check_logs.py <post|quote> <予定時刻HH:MM>
```

読むログは `--log-file` で指定できる。既定は `$NIKUNE_LOG_DIR/post.log` と `quote.log` で、`NIKUNE_LOG_DIR` の既定は `/mnt/data/nikune/logs` である。`--dry-run` を付けると、通知を送らずに通知文を表示する。

通知するのは次のときである。

- その回に成功の記録がない（cron が動かなかったときや、起動してすぐ落ちたときも含む）
- 失敗の記録（`❌` の失敗メッセージ、`ERROR` 行、`Traceback`）がある
- TypeSafe でチェックできなかった（`UNCHECKED`、`UNAVAILABLE`）
- 投稿直前チェックで API キーが設定されていなかった（`DISABLED`）
- Jev が警告を出した（`WARN`）

`WARNING` の行を一律に通知することはしない。毎回出る既知の警告があるからである。通知文に入れるログ行は、Webhook の URL、トークン、API キーらしきものを伏せ字にしてから送る。

crontab には、予定時刻の5分後に確認する行を足す。

```
5 9 * * * cd $HOME/nikune && $HOME/.local/bin/uv run --no-sync python scripts/check_logs.py post 09:00 >> /path/to/logs/check.log 2>&1
```

### 常駐させる場合

`uv run python scripts/nikune_service_runner.py` でスケジューラーを常駐させる。既定では `main.py --schedule` を実行し、異常終了したら5秒待って起動し直す。動きは次の環境変数で変えられる。

- `NIKUNE_SERVICE_COMMAND`（実行するコマンド。例 `"uv run python main.py --schedule"`）
- `NIKUNE_RESTART_DELAY`（起動し直すまでの秒数。既定は 5）
- `NIKUNE_MAX_RESTARTS`（起動し直す回数の上限）

macOS では launchd で常駐させる。`~/Library/LaunchAgents/com.nikune.bot.plist` に次の内容を保存する。

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

ログのディレクトリがなければ `mkdir -p /path/to/nikune/logs` で作り、`launchctl load ~/Library/LaunchAgents/com.nikune.bot.plist` で読み込む。止めるときは `launchctl unload`、起動し直すときは `launchctl kickstart` を使う。

Linux では systemd に転用できる。`/etc/systemd/system/nikune.service` の例を載せておく。

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

`sudo systemctl daemon-reload && sudo systemctl enable --now nikune.service` で有効にする。

## コントリビューション

フォークして機能ブランチ（例 `feature/amazing-feature`）を作り、`./check_code.sh` が通ることを確かめてから Pull Request を出してほしい。コミットメッセージは `feat:`（新機能）、`fix:`（バグ修正）、`docs:`（ドキュメント）、`chore:`（雑務や設定）で始める。

X の利用規約は守ること。

## ライセンス

MIT License。詳しくは [LICENSE](LICENSE) を参照。
