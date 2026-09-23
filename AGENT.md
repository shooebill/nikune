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
- **主要依存**: tweepy, schedule, requests, python-dotenv, redis。これらは実行時依存として`pyproject.toml`の`[project.dependencies]`に、black/isort/flake8/mypy等の開発ツールは`[dependency-groups].dev`に、すべて明示的にバージョン固定で宣言済み。**`uv sync`だけで**（`.venv`を新規作成した状態からでも）実行・品質チェックに必要な全パッケージが揃う。手動での`uv pip install`や個別のバージョン合わせは不要
- `requirements.txt`は廃止済み（旧・手動`pip install`用のフリーズ出力で、`pyproject.toml`/`uv.lock`と情報源が重複し乖離の原因になっていたため削除）。本番サーバー（wren）等へのデプロイでpip形式の一覧が必要な場合は、都度`uv export --no-dev --format requirements-txt`等で生成すること（常設ファイルとしては持たない）
- **データベース**: SQLite（永続化）＋ Redis（キャッシュ・重複防止）。Redisは`brew services start redis`等で事前起動が必要
- **開発ツール設定**: `pyproject.toml`（black line-length=120, isort, mypy）／`.flake8`（max-line-length=120）。どちらもリポジトリにコミット済みの共有設定
- **NGワード**: `NG_KEYWORDS`環境変数または`ng_keywords.txt`で設定。**設定済み**（約420語、ローカル・本番サーバー（wren）双方に配置済み。`.gitignore`対象の実データのためファイル自体はコミットされない）
- **TypeSafe (Jev)**: 引用RT候補の二次フィルタ（`nikune/quote_safety.py`）に使用。`TYPESAFE_API_KEY`（`.env`、gitignore対象）が未設定なら判定なしで従来どおり動作。モデルは`TYPESAFE_MODEL`（既定`jev-1.13.0`でバージョン固定）。キーはログ・通知に出さないこと

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
  jev_checker.py               # TypeSafe (Jev) への問い合わせ共通部分（失敗しても例外を投げない）
  quote_safety.py              # 引用RT候補の安全判定（質問・しきい値・判定ルール）
config/
  settings.py                  # 環境変数管理
scripts/
  nikune_service_runner.py     # 自動起動・Slack/LINE通知（NotificationManager）
docs/
  CHARACTER_PERSONA_SAMPLE.md  # キャラクターペルソナのサンプル（本番の正ではない、下記参照）
tests/
  test_auto_quote_retweeter.py
  test_content_generator.py
  test_database.py
  test_health_check.py
  test_jev_checker.py
  test_logging_config.py
  test_main.py
  test_nikune_service_runner.py
  test_scheduler.py
  test_twitter_client.py
data/                          # DB・テンプレートファイル
  category.tsv / tone.tsv / sample_templates.tsv   # マスタデータ（コミット対象）
  tweet_templates.tsv / *.generated.tsv / quote_comments.tsv / templates.db
                                # 実データ（gitignore対象）。tweet_templates.tsv/*.generated.tsv/templates.dbは
                                # 非公開Google Sheet「tweet_template」由来。quote_comments.tsvは対応データが
                                # シート側に未作成のため、実際には常にフォールバックで動作している（詳細は下記参照）
main.py                        # CLIエントリーポイント
check_code.sh                  # 品質チェック一括実行スクリプト
```

## キャラクターペルソナについて

`docs/CHARACTER_PERSONA_SAMPLE.md`はこのコードベースが特定のペルソナに固定されていないことを示す**サンプル**。実際に稼働中のnikuneの本番ペルソナ・ツイート候補文言は、非公開のGoogle Sheet「tweet_template」（`persona`/`tweet_templates`/`category`/`tone`タブ）で管理している。

`data/quote_comments.tsv`（gitignore対象）は、引用RTのコメント文言を`bucket`/`keyword`/`text`形式で管理する想定のファイルだが、対応するデータは非公開シート側にまだ作成されていない（2026年9月時点、該当タブ自体が存在しない）。そのためこのファイルは常に見つからず、コード側のフォールバック文言（公開済みの口癖のみを使った最小限の文言）で動作している。将来、`persona`タブの内容をもとに`bucket`/`keyword`/`text`形式のデータを新規に起草すれば、このファイルとして配置できる。

## Development Status（2026-09-22時点）

- 基本機能（定期投稿、引用リツイート、DB、スケジューラー、ヘルスチェック）は実装済み
- 引用リツイートの検出対象を「お肉」から**食・レストラン全般**（寿司・カレー・ラーメン等）に拡張済み
- キャラクターペルソナv1を策定（口調・二人称・感情表現・絵文字ルール等）、コメント生成に反映済み
- テスト: `tests/`に10ファイル（auto_quote_retweeter/content_generator/database/health_check/jev_checker/logging_config/main/nikune_service_runner/scheduler/twitter_client）＋`conftest.py`（テスト中は`TYPESAFE_API_KEY`を未設定扱いにして実APIを呼ばない）
- **本番デプロイ済み**: 2026年9月21〜22日に本番サーバー（wren）へデプロイ完了。`--schedule`常駐ではなくcronから`main.py --post-now`/`main.py --quote-check`を直接呼ぶ方式で、独り言ツイート・自動引用RTが稼働中
- NGワード（約420語）は設定済み（ローカル・wren双方に配置。詳細は上記Environment Setup Notes参照）
- 通常投稿の絵文字ルールはPR #22（署名🐻の文頭保証機能）で対応済み
- 既知の未対応事項: 季節限定カテゴリ（クリスマス等）の日付フィルタ未実装
- 引用RTコメント文言（`quote_comments.tsv`）の状況は上記「Project Structure」「キャラクターペルソナについて」を参照（非公開シート側に対応データ未作成のため、常にフォールバック文言で動作中）
