"""
写真チェックとセリフの照合（nikune/photo_checker.py）を手元で試すスクリプト

ANTHROPIC_API_KEY を設定したあと、実際の投稿でどう判定されるかを確かめるために使う。
Xへの投稿・読み取りは行わない（Claude への問い合わせの費用だけかかる）。

使い方:
    # 写真の判定（本文を付けると、写真と本文を合わせて判定する）。写真は投稿の順に複数並べられる
    # （本番と同じく PHOTO_CHECK_MAX_PHOTOS 枚まで見せる）。使った入力トークン数もログに出る
    $ uv run python scripts/check_photo.py https://example.com/photo.jpg
    $ uv run python scripts/check_photo.py https://example.com/photo.jpg --text '投稿の本文'
    $ uv run python scripts/check_photo.py https://example.com/1.jpg https://example.com/2.jpg --text '投稿の本文'

    # セリフが投稿と食い違っていないかの判定（写真はなくてもよい）
    $ uv run python scripts/check_photo.py --text '投稿の本文' --comment '付けるセリフ'

    # 料理の写真がない投稿に付けるセリフを書かせる（本番と同じく、形・NGワード・照合も確かめる）。
    # --model で書かせるモデルを変えられる（既定は QUOTE_COMMENT_MODEL）。--times で何本か書かせる
    $ uv run python scripts/check_photo.py --text '投稿の本文' --write --times 3
    $ uv run python scripts/check_photo.py https://example.com/photo.jpg --text '投稿の本文' --write --model claude-opus-5-5

書かせるには本番ペルソナ data/persona.tsv（gitignore 対象）が必要。Jev の投稿直前チェックは行わない。
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nikune.content_generator import ContentGenerator  # noqa: E402
from nikune.photo_checker import PhotoChecker  # noqa: E402
from nikune.post_safety import load_persona  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="写真チェックとセリフの照合を試す")
    parser.add_argument("image_urls", nargs="*", help="写真の公開URL（投稿の順に複数指定できる）")
    parser.add_argument("--text", default="", help="投稿の本文")
    parser.add_argument("--comment", help="付けるセリフ（指定すると、投稿と食い違っていないかも判定する）")
    parser.add_argument("--write", action="store_true", help="投稿に合わせたセリフを書かせる")
    parser.add_argument("--model", help="セリフを書かせるモデル（既定は QUOTE_COMMENT_MODEL）")
    parser.add_argument("--times", type=int, default=1, help="書かせる本数（--write のとき）")
    args = parser.parse_args()
    if not args.image_urls and not args.comment and not args.write:
        parser.error("画像URL・--comment・--write のどれかを指定してください")

    # 写真の枚数ごとの入力トークン数（📷 ... usage:）を表示する
    usage_logger = logging.getLogger("nikune.photo_checker")
    usage_logger.setLevel(logging.INFO)
    usage_logger.addHandler(logging.StreamHandler())

    checker = PhotoChecker.from_settings()
    if not checker.enabled:
        print("ANTHROPIC_API_KEY が未設定です（.env に設定してください）")
        return 1

    if args.write:
        return write(checker, args)

    if args.image_urls:
        # 料理名の選択肢を得るために生成する（DB・Redisには接続するが、書き込みはしない）
        dish_keywords = ContentGenerator().photo_dish_keywords
        verdict = checker.check(args.image_urls, dish_keywords, args.text)
        if verdict is None:
            print("判定できませんでした（上の警告ログを確認してください）")
            return 1

        print(f"食べ物の写真: {verdict.is_food}")
        print(f"肉が写っている: {verdict.shows_meat}")
        print(f"料理: {verdict.dishes}")
        print(f"肉の種類: {verdict.meats}")
        print(f"食事の種類（本文）: {verdict.meal or '分からない'}")
        print(f"写真の昼夜: {verdict.light or '分からない'}")
        print(f"モデル: {verdict.model}")

    if args.comment:
        fit = checker.comment_fits(args.comment, args.text, args.image_urls)
        if fit is None:
            print("セリフを判定できませんでした（上の警告ログを確認してください）")
            return 1

        print(f"セリフが投稿に合っている: {fit.fits}")
        print(f"理由: {fit.reason}")
    return 0


def write(checker: PhotoChecker, args: argparse.Namespace) -> int:
    """セリフを書かせ、本番と同じ形・NGワード・照合のチェックの結果と並べて表示する"""
    persona = load_persona()
    if persona is None:
        print("data/persona.tsv がありません（非公開シートの persona タブを書き出して配置してください）")
        return 1
    if args.model:
        checker.writer_model = args.model

    generator = ContentGenerator()
    is_meat_topic = generator.get_food_keyword_score(args.text)["is_meat_topic"]
    print(f"書かせるモデル: {checker.writer_model}")
    for i in range(args.times):
        written = checker.write_comment(args.text, persona, generator.quote_comment_examples(), args.image_urls)
        if written is None:
            print("書けませんでした（上の警告ログを確認してください）")
            return 1
        print(f"\n[{i + 1}] {written.text}  (model={written.model})")
        problem = generator.written_quote_comment_problem(written.text)
        if problem:
            print(f"  → 使えない: {problem}")
            continue
        comment = generator.decorate_quote_comment(written.text, is_meat_topic)
        fit = checker.comment_fits(comment, args.text, args.image_urls)
        if fit is None:
            print("  → 照合できませんでした")
            continue
        print(f"  投稿する文: {comment}")
        print(f"  照合: fits={fit.fits} 理由={fit.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
