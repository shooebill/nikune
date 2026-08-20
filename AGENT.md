# Agent Settings for Nikune Project

nikune: 「お肉」偏愛キャラクターのTwitter bot。Python + uv管理。

## Project Commands

### Development

すべて `uv run` 経由（venv手動activate不要、uvが自動管理）。

```bash
# システムテスト（初回推奨）
uv run python main.py --test

# システムヘルスチェック
uv run python main.py --health

# 即座に1回投稿
uv run python main.py --post-now
uv run python main.py --post-now --category お肉

# 引用リツイートチェック（お肉＋食・レストラン全般を検出）
uv run python main.py --quote-check
uv run python main.py --quote-check --dry-run   # API呼び出しなしのドライラン

# スケジューラー起動（継続実行、9:00/13:30/19:00投稿）
uv run python main.py --schedule

# DBセットアップ
uv run python main.py --setup-db
uv run python main.py --setup-db --file data/custom.tsv

# 依存関係管理
uv add <package>
uv remove <package>
uv sync
```

### Code Quality

```bash
# 一括チェック（black → isort → flake8 → mypy → mypy --strict → pytest）
./check_code.sh

# 個別実行
uv run black .
uv run isort .
uv run flake8 nikune/ main.py config/ tests/
uv run mypy .
uv run mypy --strict .
```

### Testing

```bash
uv run pytest tests/
uv run pytest tests/test_content_generator.py -v
```

## Environment Setup Notes

- **パッケージ管理**: `uv`（pip/venvの代替）。Python 3.13.x
- **仮想環境**: uvが自動作成・管理（手動activate不要）
- **Twitter API資格情報**: `.env`（プロジェクトルート、gitignore対象）
- **主要依存**: tweepy, schedule, requests, python-dotenv, redis
- **データベース**: SQLite（永続化）＋ Redis（キャッシュ・重複防止）。Redisは`brew services start redis`等で事前起動が必要
- **開発ツール設定**: `pyproject.toml`（black line-length=120, isort, mypy）／`.flake8`（max-line-length=120）。どちらもリポジトリにコミット済みの共有設定
- **NGワード**: `NG_KEYWORDS`環境変数または`ng_keywords.txt`で設定。**2026-08-20時点で未設定**（本番未デプロイのドライラン運用のため実害なし）。本番投稿を開始する前に必ず設定すること

## Project Structure

```
nikune/                        # メインパッケージ
  twitter_client.py            # Twitter API連携
  database.py                  # SQLite + Redis
  content_generator.py         # ツイート/コメント生成（食・レストラン検出ロジック含む）
  auto_quote_retweeter.py      # 自動引用リツイート
  scheduler.py                 # 定期投稿スケジューラー
  health_check.py              # システムヘルスチェック
  utils.py                     # 共通ユーティリティ
config/
  settings.py                  # 環境変数管理
scripts/
  nikune_service_runner.py     # 自動起動・Slack/LINE通知（NotificationManager）
docs/
  CHARACTER_PERSONA_SAMPLE.md  # キャラクターペルソナのサンプル（本番の正ではない、下記参照）
tests/
  test_content_generator.py
  test_auto_quote_retweeter.py
  test_nikune_service_runner.py
data/                          # DB・テンプレートファイル
  category.tsv / tone.tsv / sample_templates.tsv   # マスタデータ（コミット対象）
  tweet_templates.tsv / *.generated.tsv / quote_comments.tsv / templates.db
                                # 実データ（gitignore対象、非公開Google Sheet「tweet_template」由来）
main.py                        # CLIエントリーポイント
check_code.sh                  # 品質チェック一括実行スクリプト
```

## キャラクターペルソナについて

`docs/CHARACTER_PERSONA_SAMPLE.md`はこのコードベースが特定のペルソナに固定されていないことを示す**サンプル**。実際に稼働中のnikuneの本番ペルソナ・ツイート候補文言は、非公開のGoogle Sheet「tweet_template」（`persona`/`tweet_templates`/`category`/`tone`タブ）で管理している。`data/quote_comments.tsv`（gitignore対象）はこのシートのエクスポートで、引用コメント生成時に読み込む。未配置時はペルソナサンプルに公開済みの口癖のみを使った最小限のフォールバックで動作する。

## Development Status（2026-08-20時点）

- 基本機能（定期投稿、引用リツイート、DB、スケジューラー、ヘルスチェック）は実装済み
- 引用リツイートの検出対象を「お肉」から**食・レストラン全般**（寿司・カレー・ラーメン等）に拡張済み
- キャラクターペルソナv1を策定（口調・二人称・感情表現・絵文字ルール等）、コメント生成に反映済み
- テスト: `tests/`に30件（content_generator/auto_quote_retweeter/service_runnerの3ファイル）
- **本番デプロイはまだ行っていない**（ドライラン運用のみ）。ストリームB「軽量」扱いで2026-08-31にgo/no-go判断予定
- 既知の未対応事項: NGワード未設定、季節限定カテゴリ（クリスマス等）の日付フィルタ未実装、通常投稿の絵文字（`_get_random_emoji()`）がペルソナの絵文字ルール未準拠
