"""
nikune bot configuration settings
環境変数からAPIキーなどの設定を読み込む
"""

import logging
import os

from dotenv import load_dotenv

# ログ設定（他のモジュールがimportされる前に初期化）
logger = logging.getLogger(__name__)

# .envファイルを読み込み
load_dotenv()

# Twitter API設定
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")

# Bot設定
BOT_NAME = "nikune"
TWEET_INTERVAL_HOURS = 1
MAX_TWEETS_PER_DAY = 12

# 投稿時間設定（24時間制）
ACTIVE_HOURS_START = 9  # 9時から
ACTIVE_HOURS_END = 21  # 21時まで

# Quote Retweet設定
QUOTE_RETWEET_MIN_INTERVAL_MINUTES = int(os.getenv("QUOTE_RETWEET_MIN_INTERVAL_MINUTES", "30"))
QUOTE_RETWEET_MAX_PER_HOUR = int(os.getenv("QUOTE_RETWEET_MAX_PER_HOUR", "2"))
# 投稿からこの時間を超えたツイートは引用しない（前の晩の投稿に翌朝コメントするのを防ぐ）
QUOTE_RETWEET_MAX_TWEET_AGE_HOURS = float(os.getenv("QUOTE_RETWEET_MAX_TWEET_AGE_HOURS", "3"))

# 優先度システム設定
QUOTE_RETWEET_MIN_PRIORITY_SCORE = int(os.getenv("QUOTE_RETWEET_MIN_PRIORITY_SCORE", "1"))  # 最低優先度スコア
QUOTE_RETWEET_HIGH_PRIORITY_LIMIT = int(
    os.getenv("QUOTE_RETWEET_HIGH_PRIORITY_LIMIT", "3")
)  # 高優先度の上限（1時間あたり）

# TypeSafe (Jev) 設定
# - TYPESAFE_API_KEY が未設定（空文字含む）なら Jev による判定はオフになり、従来どおり動作する
# - モデルは alias（jev-latest）ではなくバージョン固定を既定にする。alias はリリースのたびに
#   指す先が変わり、検証済みのしきい値の前提が崩れうるため（公式ドキュメント Models 参照）
TYPESAFE_API_KEY = (os.getenv("TYPESAFE_API_KEY") or "").strip() or None
TYPESAFE_MODEL = (os.getenv("TYPESAFE_MODEL") or "").strip() or "jev-1.13.0"
TYPESAFE_TIMEOUT_SECONDS = float(os.getenv("TYPESAFE_TIMEOUT_SECONDS", "10"))

# 引用RT候補の写真チェック（Claude）設定
# - ANTHROPIC_API_KEY が未設定（空文字含む）なら写真は見ず、本文だけで従来どおり判定する
# - キーの値はログや通知に出さないこと
ANTHROPIC_API_KEY = (os.getenv("ANTHROPIC_API_KEY") or "").strip() or None
PHOTO_CHECK_MODEL = (os.getenv("PHOTO_CHECK_MODEL") or "").strip() or "claude-opus-5-5"
PHOTO_CHECK_TIMEOUT_SECONDS = float(os.getenv("PHOTO_CHECK_TIMEOUT_SECONDS", "30"))
# 1回の実行で写真を見る候補の上限（費用の上限。1候補につき見る写真は1枚目だけ）
PHOTO_CHECK_MAX_PER_RUN = int(os.getenv("PHOTO_CHECK_MAX_PER_RUN", "5"))


# NGワードリスト（環境変数または設定ファイルから読み込み）
def _load_ng_keywords() -> list[str]:
    """
    NGワードリストを環境変数または設定ファイルから読み込みます。
    優先順位:
      1. 環境変数 NG_KEYWORDS（カンマ区切り）
      2. 環境変数 NG_KEYWORDS_FILE で指定されたファイル
      3. デフォルトファイル ng_keywords.txt

    NGワードの選定基準・変更手順についてはREADMEを参照してください。
    """
    env_ng_keywords = os.getenv("NG_KEYWORDS", "")
    if env_ng_keywords:
        return [keyword.strip() for keyword in env_ng_keywords.split(",") if keyword.strip()]

    ng_keywords_file = os.getenv("NG_KEYWORDS_FILE", "ng_keywords.txt")
    if os.path.isfile(ng_keywords_file):
        with open(ng_keywords_file, encoding="utf-8") as f:
            # 空行や#で始まる行は無視
            return [stripped for line in f if (stripped := line.strip()) and not stripped.startswith("#")]

    # NGワードリストが未設定の場合は空リストを返す
    logger.warning(
        f"⚠️ NGワードリストが見つかりませんでした: {ng_keywords_file}。環境変数NG_KEYWORDSまたはファイルで設定してください。"
    )
    return []


NG_KEYWORDS = _load_ng_keywords()

# 時間帯判定用設定（調整可能）
# 独り言ツイートで、出してよい時間帯が決まっているトーン（トーン名 → 出してよい「時」）
# シートの tweet_templates タブで tone 列をこの名前にしたセリフは、その時間帯の回にだけ選ばれる。
# ここにないトーンのセリフは、どの回でも選ばれる
TIME_LIMITED_TONES: dict[str, frozenset[int]] = {
    "朝活": frozenset(range(5, 11)),  # 5時〜10時台（9:00の回）
    "夜更かし": frozenset([18, 19, 20, 21, 22, 23, 0, 1, 2, 3]),  # 18時〜翌3時台（19:00の回）
}

TIME_SETTINGS = {
    "MORNING_START": 6,
    "MORNING_END": 10,
    "LUNCH_START": 11,
    "LUNCH_END": 14,
    "DINNER_START": 17,
    "DINNER_END": 21,
}


# 設定の検証
def validate_config() -> bool:
    """必要な設定がすべて揃っているかチェック"""
    required_vars = [
        TWITTER_API_KEY,
        TWITTER_API_SECRET,
        TWITTER_ACCESS_TOKEN,
        TWITTER_ACCESS_TOKEN_SECRET,
    ]

    missing_vars = []
    for i, var in enumerate(required_vars):
        if not var:
            var_names = [
                "TWITTER_API_KEY",
                "TWITTER_API_SECRET",
                "TWITTER_ACCESS_TOKEN",
                "TWITTER_ACCESS_TOKEN_SECRET",
            ]
            missing_vars.append(var_names[i])

    if missing_vars:
        print("❌ 環境変数が設定されていません")
        print("📝 以下の環境変数を .env ファイルに設定してください：")
        for var in missing_vars:
            print(f"   {var}=your_value_here")
        print("\n💡 .env ファイルの例：")
        print("TWITTER_API_KEY=your_api_key")
        print("TWITTER_API_SECRET=your_api_secret")
        print("TWITTER_ACCESS_TOKEN=your_access_token")
        print("TWITTER_ACCESS_TOKEN_SECRET=your_access_token_secret")
        raise ValueError(f"Missing environment variables: {', '.join(missing_vars)}")

    print(f"✅ {BOT_NAME} configuration loaded successfully")
    return True


if __name__ == "__main__":
    # 設定テスト実行
    validate_config()
