"""
写真チェック（nikune/photo_checker.py）を画像URL1つで試すスクリプト

ANTHROPIC_API_KEY を設定したあと、実際の画像でどう判定されるかを確かめるために使う。
Xへの投稿・読み取りは行わない（Claude への問い合わせ1回分の費用だけかかる）。

使い方:
    $ uv run python scripts/check_photo.py https://example.com/photo.jpg
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nikune.content_generator import ContentGenerator  # noqa: E402
from nikune.photo_checker import PhotoChecker  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_photo.py <image-url>")
        return 2

    checker = PhotoChecker.from_settings()
    if not checker.enabled:
        print("ANTHROPIC_API_KEY が未設定です（.env に設定してください）")
        return 1

    # 料理名の選択肢を得るために生成する（DB・Redisには接続するが、書き込みはしない）
    dish_keywords = ContentGenerator().photo_dish_keywords
    verdict = checker.check(sys.argv[1], dish_keywords)
    if verdict is None:
        print("判定できませんでした（上の警告ログを確認してください）")
        return 1

    print(f"食べ物の写真: {verdict.is_food}")
    print(f"肉が写っている: {verdict.shows_meat}")
    print(f"料理: {verdict.dishes}")
    print(f"モデル: {verdict.model}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
