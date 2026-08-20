# -*- coding: utf-8 -*-
"""
Nikune Twitter Bot - メインエントリーポイント

可愛い子熊「nikune」がお肉のおいしさを自動投稿するTwitterボット
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, Optional

from config.settings import BOT_NAME
from nikune.auto_quote_retweeter import AutoQuoteRetweeter
from nikune.content_generator import ContentGenerator
from nikune.database import DatabaseManager
from nikune.health_check import HealthChecker
from nikune.scheduler import SchedulerManager
from nikune.twitter_client import TwitterClient
from nikune.utils import log_errors

# 定数定義
MAX_ERRORS_TO_DISPLAY = 3  # 表示するエラーの最大数

# ロガー設定
logger = logging.getLogger(__name__)


def setup_sample_data(db_manager: DatabaseManager) -> bool:
    """
    サンプルデータをセットアップ

    Args:
        db_manager: データベースマネージャー

    Returns:
        セットアップ成功かどうか
    """
    try:
        # 既存のテンプレート数をチェック
        existing_templates = db_manager.get_templates()

        if len(existing_templates) == 0:
            logger.info("🔧 No templates found, setting up sample data...")

            # ContentGeneratorを使ってサンプルテンプレートを追加
            with ContentGenerator(db_manager) as generator:
                added_count = generator.add_sample_templates()
                logger.info(f"✅ Added {added_count} sample templates")
                return added_count > 0
        else:
            logger.info(f"📝 Found {len(existing_templates)} existing templates")
            return True

    except Exception as e:
        logger.error(f"❌ Failed to setup sample data: {e}")
        return False


def test_all_components(dry_run: bool = False) -> bool:
    """全コンポーネントのテスト実行"""
    print(f"🐻 {BOT_NAME} - Full System Test")
    if dry_run:
        print("🎭 Running in DRY RUN mode")
    print("=" * 50)

    try:
        # ヘルスチェッカーを使用した包括的テスト
        health_checker = HealthChecker(dry_run=dry_run)
        health_results = health_checker.check_all_components()

        print("1. System Health Check...")
        if not health_results["overall"]:
            print("❌ System health check failed")
            return False
        print("✅ System health: OK")

        # データベース接続テスト
        print("\n2. Testing Database Connection...")
        with DatabaseManager() as db_manager:
            # サンプルデータセットアップ
            if not setup_sample_data(db_manager):
                print("❌ Failed to setup sample data")
                return False

            templates = db_manager.get_templates()
            print(f"✅ Database: {len(templates)} templates available")

        # Twitter接続テスト
        print("\n3. Testing Twitter API Connection...")
        if dry_run:
            print("✅ Twitter API: Mock connection successful (dry run)")
        else:
            twitter_client = TwitterClient()
            if twitter_client.test_connection():
                print("✅ Twitter API: Connection successful")
            else:
                print("❌ Twitter API: Connection failed")
                return False

        # コンテンツ生成テスト
        print("\n4. Testing Content Generation...")
        with ContentGenerator() as generator:
            content = generator.generate_tweet_content()
            if content:
                print("✅ Content Generation: OK")
                print(f"📝 Sample: {content}")
            else:
                print("❌ Content Generation: Failed")
                return False

        # スケジューラーテスト
        print("\n5. Testing Scheduler...")
        with SchedulerManager(dry_run=dry_run) as scheduler:
            # テスト用スケジュール設定
            test_config = {
                "daily_posts": 1,
                "post_times": ["12:00"],
                "categories": ["お肉"],
                "random_delay": False,
            }
            scheduler.setup_schedule(test_config)

            status = scheduler.get_schedule_status()
            print(f"✅ Scheduler: {status['total_jobs']} jobs scheduled")

        print("\n🎉 All tests completed successfully!")
        return True

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        return False


def post_now_command(
    category: Optional[str] = None,
    tone: Optional[str] = None,
    text: Optional[str] = None,
    dry_run: bool = False,
) -> bool:
    """即座に1回ツイート投稿"""
    if dry_run:
        print(f"🐻 {BOT_NAME} - Dry run mode (no actual posting)")
    else:
        print(f"🐻 {BOT_NAME} - Posting tweet now...")

    try:
        with SchedulerManager(dry_run=dry_run) as scheduler:
            # カスタムテキストが指定された場合
            if text:
                print(f"📝 Custom tweet: {text}")
                if dry_run:
                    print("🔍 [DRY RUN] Would post this custom tweet")
                    return True
                else:
                    success = scheduler.post_custom_tweet(text)
            else:
                # サンプルデータがない場合はセットアップ
                if not setup_sample_data(scheduler.db_manager):
                    print("❌ Failed to setup sample data")
                    return False

                if dry_run:
                    # ドライランモード: コンテンツ生成のみ
                    content = scheduler.content_generator.generate_tweet_content(category, tone)
                    if content:
                        print(f"🔍 [DRY RUN] Would post: {content}")
                        return True
                    else:
                        print("❌ [DRY RUN] Failed to generate content")
                        return False
                else:
                    # 通常の投稿（テンプレートから生成）
                    success = scheduler.post_now(category=category, tone=tone)

            if success:
                if dry_run:
                    print("✅ [DRY RUN] Content generation successful!")
                else:
                    print("🎉 Tweet posted successfully!")
                return True
            else:
                if dry_run:
                    print("❌ [DRY RUN] Content generation failed")
                else:
                    print("❌ Failed to post tweet")
                return False

    except Exception as e:
        print(f"❌ Post now failed: {e}")
        return False


def start_scheduler_command(config_file: Optional[str] = None) -> bool:
    """スケジューラーを開始"""
    print(f"🐻 {BOT_NAME} - Starting scheduler...")

    try:
        with SchedulerManager() as scheduler:
            # サンプルデータがない場合はセットアップ
            if not setup_sample_data(scheduler.db_manager):
                print("❌ Failed to setup sample data")
                return False

            # スケジュール設定
            if config_file:
                # TODO: 設定ファイルからの読み込み実装
                print(f"📁 Loading config from: {config_file}")
                pass

            # デフォルト設定でスケジュール開始
            scheduler.setup_schedule()

            print("🚀 Scheduler started successfully!")
            print("📅 Default schedule: 09:00, 13:30, 19:00 daily")
            print("⏹️ Press Ctrl+C to stop")

            # ブロッキングモードでスケジューラー実行
            scheduler.start_scheduler(blocking=True)

    except KeyboardInterrupt:
        print("\n⏹️ Scheduler stopped by user")
    except Exception as e:
        print(f"❌ Scheduler failed: {e}")
        return False

    return True


def import_templates_command(file_path: Optional[str] = None) -> bool:
    """テンプレートインポート（自動検出 or ファイル指定）"""
    print(f"🐻 {BOT_NAME} - Importing templates...")

    try:
        with DatabaseManager() as db_manager:
            total_imported = 0

            if file_path:
                # ファイル指定モード
                if Path(file_path).exists():
                    print(f"📁 Importing from specified file: {file_path}")
                    count = db_manager.import_templates_from_tsv(file_path, clear_existing=False)
                    total_imported += count
                    print(f"✅ Imported {count} templates from {file_path}")
                else:
                    print(f"❌ File not found: {file_path}")
                    return False
            else:
                # 自動検出モード
                # 手入力テンプレートの自動検出
                # データベースを完全にクリア
                print("🗑️ Clearing existing database...")
                db_manager.clear_all_templates()
                print("✅ Database cleared")

                manual_tsv = "data/tweet_templates.tsv"
                if Path(manual_tsv).exists():
                    print(f"📝 Found manual templates: {manual_tsv}")
                    manual_count = db_manager.import_templates_from_tsv(manual_tsv, clear_existing=False)
                    total_imported += manual_count
                    print(f"✅ Imported {manual_count} manual templates")
                else:
                    print(f"⚠️ Manual templates not found: {manual_tsv}")

                # 自動生成テンプレートの自動検出
                generated_tsv = "data/tweet_templates.generated.tsv"
                if Path(generated_tsv).exists():
                    print(f"🤖 Found generated templates: {generated_tsv}")
                    generated_count = db_manager.import_templates_from_tsv(generated_tsv, clear_existing=False)
                    total_imported += generated_count
                    print(f"✅ Imported {generated_count} generated templates")
                else:
                    print(f"⚠️ Generated templates not found: {generated_tsv}")

            # 統計情報表示
            templates = db_manager.get_templates()
            print(f"📊 Total templates: {len(templates)}")

            # カテゴリ別統計
            categories: Dict[str, int] = {}
            for template in templates:
                cat = template["category"]
                categories[cat] = categories.get(cat, 0) + 1

            for category, count in categories.items():
                print(f"   - {category}: {count} templates")

            if total_imported > 0:
                print("✅ Template import completed!")
            else:
                print("⚠️ No templates imported")

            return True

    except Exception as e:
        print(f"❌ Template import failed: {e}")
        return False


def check_quote_retweet_command(dry_run: bool = False) -> bool:
    """
    Quote Retweet チェック・実行コマンド

    Args:
        dry_run: True の場合、実際には投稿せずにログ出力のみ

    Returns:
        実行成功かどうか
    """
    try:
        logger.info("🔄 Starting quote retweet check...")

        with DatabaseManager() as db_manager:
            # Auto Quote Retweeter 作成（dry_runモード対応）
            retweeter = AutoQuoteRetweeter(db_manager, dry_run=dry_run)

            # ステータス表示
            status = retweeter.get_status()
            logger.info(f"📊 Quote retweeter status: {status}")

            # レート制限チェック
            if not status["can_quote_now"]:
                if status["next_available_time"]:
                    logger.info(f"⏰ Next quote available at: {status['next_available_time']}")
                else:
                    logger.info("⏰ Quote tweets temporarily limited")
                return True  # エラーではないのでTrueを返す

            # Quote Retweet実行
            results = retweeter.check_and_quote_tweets()

            # 結果表示
            if results["success"]:
                logger.info("✅ Quote retweet check completed:")
                logger.info(f"   📊 Checked tweets: {results['checked_tweets']}")
                logger.info(f"   🍽️ Food-related found: {results['food_related_found']}")
                logger.info(f"   🔄 Quote tweets posted: {results['quote_posted']}")

                errors = results.get("errors", [])
                if errors:
                    log_errors(errors, MAX_ERRORS_TO_DISPLAY)

                return True
            else:
                logger.error(f"❌ Quote retweet check failed: {results.get('error', 'Unknown error')}")
                return False

    except Exception as e:
        logger.error(f"❌ Failed to execute quote retweet command: {e}")
        return False


def setup_database_command() -> bool:
    """データベースセットアップ（レガシー関数）"""
    print(f"🐻 {BOT_NAME} - Setting up database...")

    try:
        with DatabaseManager() as db_manager:
            # サンプルデータセットアップ
            if not setup_sample_data(db_manager):
                print("❌ Failed to setup sample data")
                return False

            # 統計情報表示
            templates = db_manager.get_templates()
            print(f"📊 Total templates: {len(templates)}")

            # カテゴリ別統計
            categories: Dict[str, int] = {}
            for template in templates:
                cat = template["category"]
                categories[cat] = categories.get(cat, 0) + 1

            for category, count in categories.items():
                print(f"   - {category}: {count} templates")

            print("✅ Database setup completed!")
            return True

    except Exception as e:
        print(f"❌ Database setup failed: {e}")
        return False


def main() -> None:
    """メイン関数"""
    parser = argparse.ArgumentParser(
        description=f"{BOT_NAME} - 可愛い子熊のお肉ツイートボット",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python main.py --test                    # 全コンポーネントテスト
  python main.py --health                  # システム健全性チェック
  python main.py --post-now                # 即座に1回投稿
  python main.py --post-now --dry-run      # ドライランモード（投稿せず内容のみ表示）
  python main.py --post-now --category お肉 # カテゴリ指定で投稿
  python main.py --post-now --text "こんにちは！" # カスタムテキストで投稿
  python main.py --post-now --text "テスト" --dry-run # カスタムテキストのドライラン
  python main.py --quote-check              # お肉関連ツイートをチェック・Quote Retweet
  python main.py --quote-check --dry-run    # Quote Retweetのドライラン
  python main.py --schedule                # スケジューラー開始
  python main.py --setup-db                # データベースセットアップ（自動テンプレートインポート）
  python main.py --setup-db --file data/custom.tsv # 指定ファイルからインポート
        """,
    )

    # 実行モードオプション
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--test", action="store_true", help="全コンポーネントのテスト実行")
    group.add_argument("--health", action="store_true", help="システム健全性チェック")
    group.add_argument("--post-now", action="store_true", help="即座に1回ツイート投稿")
    group.add_argument("--quote-check", action="store_true", help="お肉関連ツイートをチェック・Quote Retweet")
    group.add_argument("--schedule", action="store_true", help="スケジューラーを開始")
    group.add_argument("--setup-db", action="store_true", help="データベースセットアップ")

    # オプションパラメータ
    parser.add_argument("--category", type=str, help="投稿カテゴリ指定（お肉、日常、季節）")
    parser.add_argument("--tone", type=str, help="投稿トーン指定（可愛い、元気、癒し）")
    parser.add_argument("--text", type=str, help="カスタムツイート内容（--post-now用）")
    parser.add_argument("--file", type=str, help="テンプレートファイルパス（--setup-db用、TSV形式）")
    parser.add_argument("--config", type=str, help="設定ファイルパス（--schedule用）")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際の投稿は行わず、内容のみ表示（--post-now用）",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="詳細ログを出力")

    args = parser.parse_args()

    # ログレベル設定
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(asctime)s - %(levelname)s - %(message)s")

    # 開始メッセージ
    logger.info(f"🐻 {BOT_NAME} started")

    try:
        success = False

        if args.test:
            success = test_all_components(dry_run=args.dry_run)
        elif args.health:
            health_checker = HealthChecker(dry_run=args.dry_run)
            health_checker.run_diagnostic()
            success = True
        elif args.post_now:
            success = post_now_command(
                category=args.category,
                tone=args.tone,
                text=args.text,
                dry_run=args.dry_run,
            )
        elif args.quote_check:
            success = check_quote_retweet_command(dry_run=args.dry_run)
        elif args.schedule:
            success = start_scheduler_command(config_file=args.config)
        elif args.setup_db:
            success = import_templates_command(file_path=args.file)

        if success:
            logger.info("✅ Operation completed successfully")
            sys.exit(0)
        else:
            logger.error("❌ Operation failed")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("⏹️ Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
