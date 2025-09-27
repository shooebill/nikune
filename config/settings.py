"""
nikune bot configuration settings
環境変数からAPIキーなどの設定を読み込む
"""

import os

from dotenv import load_dotenv

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
        raise ValueError(f"Missing environment variables: {', '.join(missing_vars)}")

    print(f"✅ {BOT_NAME} configuration loaded successfully")
    return True


if __name__ == "__main__":
    # 設定テスト実行
    validate_config()
