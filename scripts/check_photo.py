"""
写真チェックとセリフの照合（nikune/photo_checker.py）を手元で試すスクリプト

ANTHROPIC_API_KEY を設定したあと、実際の投稿でどう判定されるかを確かめるために使う。
Xへの投稿・読み取りは行わない（Claude への問い合わせの費用だけかかる）。

使い方:
    # 写真の判定（本文を付けると、写真と本文を合わせて判定する）
    $ uv run python scripts/check_photo.py https://example.com/photo.jpg
    $ uv run python scripts/check_photo.py https://example.com/photo.jpg --text '投稿の本文'

    # セリフが投稿と食い違っていないかの判定（写真はなくてもよい）
    $ uv run python scripts/check_photo.py --text '投稿の本文' --comment '付けるセリフ'
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nikune.content_generator import ContentGenerator  # noqa: E402
from nikune.photo_checker import PhotoChecker  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="写真チェックとセリフの照合を試す")
    parser.add_argument("image_url", nargs="?", help="写真の公開URL")
    parser.add_argument("--text", default="", help="投稿の本文")
    parser.add_argument("--comment", help="付けるセリフ（指定すると、投稿と食い違っていないかも判定する）")
    args = parser.parse_args()
    if not args.image_url and not args.comment:
        parser.error("画像URLか --comment のどちらかを指定してください")

    checker = PhotoChecker.from_settings()
    if not checker.enabled:
        print("ANTHROPIC_API_KEY が未設定です（.env に設定してください）")
        return 1

    if args.image_url:
        # 料理名の選択肢を得るために生成する（DB・Redisには接続するが、書き込みはしない）
        dish_keywords = ContentGenerator().photo_dish_keywords
        verdict = checker.check(args.image_url, dish_keywords, args.text)
        if verdict is None:
            print("判定できませんでした（上の警告ログを確認してください）")
            return 1

        print(f"食べ物の写真: {verdict.is_food}")
        print(f"肉が写っている: {verdict.shows_meat}")
        print(f"料理: {verdict.dishes}")
        print(f"モデル: {verdict.model}")

    if args.comment:
        fit = checker.comment_fits(args.comment, args.text, args.image_url)
        if fit is None:
            print("セリフを判定できませんでした（上の警告ログを確認してください）")
            return 1

        print(f"セリフが投稿に合っている: {fit.fits}")
        print(f"理由: {fit.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
