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
uv run python main.py --quote-check --chance 0.5   # 1日1回までの抽選モード（今日未引用なら50%で引用RTを探す）

# ログ確認（その回に異常があればSlackへ通知。--dry-runで送らずに通知文を表示）
uv run python scripts/check_logs.py post 09:00
uv run python scripts/check_logs.py quote 12:30 --log-file /path/to/test.log --dry-run

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
- **主要依存**: tweepy, schedule, requests, python-dotenv, redis, anthropic。これらは実行時依存として`pyproject.toml`の`[project.dependencies]`に、black/isort/flake8/mypy等の開発ツールは`[dependency-groups].dev`に、すべて明示的にバージョン固定で宣言済み。**`uv sync`だけで**（`.venv`を新規作成した状態からでも）実行・品質チェックに必要な全パッケージが揃う。手動での`uv pip install`や個別のバージョン合わせは不要
- **写真チェック (Claude)**: 引用RT候補に写真が付いていれば1枚目を本文と一緒にClaudeに見せ、食べ物の写真か・肉が写っているか・何の料理かを判定する（`nikune/photo_checker.py`。文章は生成させない）。選んだセリフが投稿の内容と食い違っていないかも、投稿の前に同じモジュールで確かめる（確かめる回数は1回の実行で`COMMENT_CHECK_MAX_PER_RUN`回まで、既定6）。`ANTHROPIC_API_KEY`（`.env`、gitignore対象）が未設定なら写真は見ず、本文だけで従来どおり動作する。API失敗時も本文だけのルールで続行。モデルは`PHOTO_CHECK_MODEL`（既定`claude-opus-5-5`）、1回の実行で見るのは`PHOTO_CHECK_MAX_PER_RUN`件（既定5）まで。キーはログ・通知に出さないこと。実キーでの動作確認は`uv run python scripts/check_photo.py <画像URL> --text <本文> --comment <セリフ>`（`--text`と`--comment`は任意。画像なしでセリフだけ確かめることもできる）
- `requirements.txt`は廃止済み（旧・手動`pip install`用のフリーズ出力で、`pyproject.toml`/`uv.lock`と情報源が重複し乖離の原因になっていたため削除）。本番サーバー（wren）等へのデプロイでpip形式の一覧が必要な場合は、都度`uv export --no-dev --format requirements-txt`等で生成すること（常設ファイルとしては持たない）
- **データベース**: SQLite（永続化）＋ Redis（キャッシュ・重複防止）。Redisは`brew services start redis`等で事前起動が必要
- **開発ツール設定**: `pyproject.toml`（black line-length=120, isort, mypy）／`.flake8`（max-line-length=120）。どちらもリポジトリにコミット済みの共有設定
- **NGワード**: `NG_KEYWORDS`環境変数または`ng_keywords.txt`で設定。**設定済み**（約420語、ローカル・本番サーバー（wren）双方に配置済み。`.gitignore`対象の実データのためファイル自体はコミットされない）
- **TypeSafe (Jev)**: 引用RT候補の二次フィルタ（`nikune/quote_safety.py`）と、自分の投稿の投稿直前チェック（`nikune/post_safety.py`、現状は警告ログのみで投稿は止めない。API失敗時もそのまま投稿）に使用。投稿直前チェックの「キャラクターの口調・世界観に沿っているか」は本番ペルソナ`data/persona.tsv`（非公開シートのpersonaタブのエクスポート、gitignore対象）がある場合のみ行う。`TYPESAFE_API_KEY`（`.env`、gitignore対象）が未設定なら判定なしで従来どおり動作。モデルは`TYPESAFE_MODEL`（既定`jev-1.13.0`でバージョン固定）。キーはログ・通知に出さないこと

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
  post_safety.py               # 自分の投稿の投稿直前チェック（警告のみ。止めるかどうかはshould_post()で切替）
  photo_checker.py             # 引用RT候補の写真をClaudeに見せて判定（失敗しても例外を投げない）
  emoji_rules.py               # 通常投稿の絵文字ルール（許可リスト方式: 文頭🐻 1つ＋🥩/🍖合わせて1つまで）
  notifications.py             # Slack/LINE通知の共通部品（NotificationManager。全チャネル失敗時はマーカーファイル）
config/
  settings.py                  # 環境変数管理
scripts/
  check_logs.py                # cron運用時のログ確認。その回のログを読み、異常時のみ通知（本番はこちら）
  check_photo.py               # 写真チェックとセリフの照合を手元で試す（実キーでの動作確認用）
  nikune_service_runner.py     # 常駐運用（--schedule）時の自動起動・異常終了時の通知（本番では未使用）
docs/
  CHARACTER_PERSONA_SAMPLE.md  # キャラクターペルソナのサンプル（本番の正ではない、下記参照）
tests/
  test_auto_quote_retweeter.py
  test_check_logs.py
  test_content_generator.py
  test_database.py
  test_health_check.py
  test_jev_checker.py
  test_logging_config.py
  test_main.py
  test_nikune_service_runner.py
  test_photo_checker.py
  test_post_safety.py
  test_scheduler.py
  test_twitter_client.py
data/                          # DB・テンプレートファイル
  category.tsv / tone.tsv / sample_templates.tsv   # マスタデータ（コミット対象）
  tweet_templates.tsv / *.generated.tsv / quote_comments.tsv / persona.tsv / templates.db
                                # 実データ（gitignore対象）。tweet_templates.tsv/*.generated.tsv/templates.dbは
                                # 非公開Google Sheet「tweet_template」由来（quote_comments.tsvは
                                # quote_commentsタブ。詳細は下記参照）
main.py                        # CLIエントリーポイント
check_code.sh                  # 品質チェック一括実行スクリプト
```

## キャラクターペルソナについて

`docs/CHARACTER_PERSONA_SAMPLE.md`はこのコードベースが特定のペルソナに固定されていないことを示す**サンプル**。実際に稼働中のnikuneの本番ペルソナ・ツイート候補文言は、非公開のGoogle Sheet「tweet_template」（`persona`/`tweet_templates`/`category`/`tone`タブ）で管理している。

`data/quote_comments.tsv`（gitignore対象）は、引用RTのコメント文言を`bucket`/`keyword`/`text`形式で持つファイル。実データは非公開シートの`quote_comments`タブ（2026-09-27に`persona`タブをもとに新規起草）で、TSVに書き出してローカル・wrenの`data/`に配置する。ファイルがない環境では、コード側のフォールバック文言（公開済みの口癖のみを使った最小限の文言）で動作する。

時間帯の一言（朝・昼・夜）も同じファイルで持てる。`bucket`を`time_morning`/`time_lunch`/`time_dinner`/`time_other`にした行があれば、その中から選ぶ（複数行あればランダム。行がない時間帯はコード側の文言を使う）。時間帯の一言は、専用コメント（`specific`）が選ばれたときと、セリフが「？」で終わるときには付けない。専用コメントはそれだけで落ちるように書いてあり、一言を足すと語尾が2つ3つ並ぶためである。

文言を書くときは、コードが分かるのは「本文にキーワードの文字列が含まれている」ことだけだと意識する。料理の中身・見た目・お酒の有無などは判定していないので、分からないことは言い切らず「・・・？」の形にする（例: 具材の有無を言い当てるセリフは避ける）。キーワードは部分一致なので、「そば」が「駅のそばで」に当たるような誤検出もありうる。

## Development Status（2026-10-13時点）

- 基本機能（定期投稿、引用リツイート、DB、スケジューラー、ヘルスチェック）は実装済み
- 引用リツイートの検出対象を「お肉」から**食・レストラン全般**（寿司・カレー・ラーメン等）に拡張済み
- キャラクターペルソナv1を策定（口調・二人称・感情表現・絵文字ルール等）、コメント生成に反映済み
- テスト: `tests/`に13ファイル（auto_quote_retweeter/check_logs/content_generator/database/health_check/jev_checker/logging_config/main/nikune_service_runner/photo_checker/post_safety/scheduler/twitter_client）＋`conftest.py`（テスト中は`TYPESAFE_API_KEY`を未設定扱いにして実APIを呼ばない）
- **本番デプロイ済み**: 2026年9月21〜22日に本番サーバー（wren）へデプロイ完了。`--schedule`常駐ではなくcronから`main.py --post-now`/`main.py --quote-check`を直接呼ぶ方式で、独り言ツイート・自動引用RTが稼働中
- **本番の異常通知**: cron方式では見張り役（`nikune_service_runner.py`）を使わないため、見張り役の通知は本番で一度も送られていなかった。各回の数分後に`scripts/check_logs.py`をcronで起動し、その回のログに異常（成功の記録なし・失敗の記録・TypeSafeでチェックできなかった・キー未設定・Jevの警告）があるときだけSlackへ通知する方式にした（通知部品は`nikune/notifications.py`に共通化）。LINEは`LINE_NOTIFY_ENABLED=false`のままオフ。2026-09-23にwrenへ反映し、各回の5分後（独り言は9:05/15:05/19:05、引用RTは8:35/12:35/18:35）にcronで稼働中（結果は`/mnt/data/nikune/logs/check.log`）。テスト用ログでのSlack実送信と、本番の回での通知（Jevの警告）を確認済み
- **引用RTの時刻と回数**: 2026-09-27から、cronで朝・昼・晩（8:30/12:30/18:30）に`--quote-check --chance`を起動し、1日1回までの抽選で引用する（確率0.25/0.3333/0.5で、朝・昼・晩・引用なしが各25%）。引用した記録はSQLiteの`quote_history`に残し、同じツイートの再引用防止と実行をまたいだレート制限に使う（PR #36/#37。それまでは毎日12:30固定で、1回の実行で上限を超えて3件投稿したり、同じツイートを別の日に再度引用したりしていた）
- **引用RTは新しいツイートだけ**: 投稿から3時間（`QUOTE_RETWEET_MAX_TWEET_AGE_HOURS`）を超えたツイートと、フォロー中の人によるリツイート（本文が`RT @`で始まるもの）は引用しない。時間帯の一言（朝・昼・夜）は起動時刻ではなく元ツイートの投稿時刻で決める（それまでは朝8:30の回が前の晩22〜23時台の投稿を朝のあいさつ付きで引用していた）。候補がタイムライン由来か検索API由来かは`quote.log`の`source=timeline/search`で分かる
- **引用RTは肉の話題を優先**: 候補を「肉の話題 → 肉ではないが専用コメント（`quote_comments.tsv`の`specific`）のある食べ物 → それ以外」の順に並べ、同じ順位ではフォロー中タイムラインを検索APIより先に見る。専用コメントのない肉以外の投稿（「ランチ」「グルメ」等だけで拾ったもの）は引用しない。`quote_comments.tsv`がない環境では専用コメントがステーキ・焼肉だけなので、実質肉の話題しか引用しない。肉のキーワードには部位・料理名（牛スジ、牛タン、角煮など）も入れている（それまでは新しい順に見て最初の食の投稿を引用しており、9/28〜10/9の引用10件のうち肉のキーワードで拾えたのは1件だった）
- **引用RTは写真も見る**: 写真付きの候補はClaudeで写真を判定し、候補の順位を「写真に肉が写っている → 本文が肉の話題 → 専用コメントのある食べ物 → それ以外（引用しない）」にする。写真から分かった料理名は本文のキーワードと同じ扱いで、セリフ選びにも使う（本文が店名や日付だけの投稿でも、何の料理かが分かる）。フォロー中タイムラインの投稿は、本文に食のキーワードがなくても写真があれば見る。結果は`quote.log`の`📷 Photo check:`の行に出る
- **引用RTはセリフを投稿と照合する**: 写真の判定には本文も渡し、写真だけでは見分けられない料理（串焼きの肉の種類など）は本文に合わせる。さらに、選んだセリフを本文・写真と並べてClaudeに見せ、料理の取り違えなどの食い違いがないかを投稿の前に確かめる。食い違っていたら専用コメントを使わない汎用の文言で選び直し（肉の話題のときだけ）、それも合わなければその投稿は引用せず次の候補へ進む。判定できなかったとき（キー未設定・API失敗）は選んだセリフをそのまま使う。結果は`quote.log`の`🗣️ Comment check:`の行に出る（それまでは写真だけを見て料理を決め、セリフはキーワードの一致だけで選んでいたため、2026-10-13に「豚肉なのに『やきとり』と呼ぶ」という投稿へ、鶏肉と言い切るセリフを付けた）
- **独り言は最近のセリフを避ける**: 投稿したセリフをSQLiteの`post_history`に残し、直近に使ったセリフ（候補の6割にあたる本数。19本なら11本）と、直近3回の投稿とほぼ同じ文のセリフを外した中から選ぶ（`database.py`の`get_available_template`）。19本・1日3回なら、同じセリフが戻るのは早くても4日後になる。24時間のクールダウン（Redis）も残している（それまでは全体からランダムに選んで24時間以内のものだけ引き直す方式で、同じセリフが28時間後に戻ったり、「肉しか見えない」「肉しか見えていない」が5投稿中3回出たりしていた）
- **独り言の時間帯指定**: シートの`tweet_templates`タブでトーンを「朝活」にしたセリフは5〜10時台（9:00の回）、「夜更かし」にしたセリフは18時〜翌3時台（19:00の回）にだけ選ばれる。それ以外のトーンのセリフはどの回でも選ばれる。対応は`config/settings.py`の`TIME_LIMITED_TONES`。`--post-now --tone 朝活`のようにトーンを明示したときは時間帯の制限をかけない
- **独り言の続きもの（前振り→オチ）**: シートの`tweet_templates`タブの`series`列に同じネタ名、`order`列に順番（1が前振り、2がオチ）を入れた組は、続きものとして扱う。オチ（2番目以降）はふだんの候補に入らず、直前の独り言が同じネタの1つ前だったときだけ、次の回で優先して選ばれる（時間帯の制限と24時間のクールダウンは守る。出せなければ、その回は単発のセリフから選ぶ）。前振りは単発のセリフと同じように選ばれる。`series`/`order`列がないTSVもそのまま取り込める（それまではオチが前振りより先に出ることがあった）
- NGワード（約420語）は設定済み（ローカル・wren双方に配置。詳細は上記Environment Setup Notes参照）
- 通常投稿の絵文字ルールはPR #22（署名🐻の文頭保証機能）で対応済み。許可リスト方式（文頭の署名🐻 1つ＋🥩/🍖を合わせて1つまで、それ以外は警告ログのみ）に拡張済み
- 既知の未対応事項: 季節限定カテゴリ（クリスマス等）の日付フィルタ未実装
- 引用RTコメント文言（`quote_comments.tsv`）は2026-09-27に非公開シートの`quote_comments`タブとして作成し、ローカル・wrenに配置済み（詳細は上記「キャラクターペルソナについて」参照）
