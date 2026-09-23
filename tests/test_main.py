"""
main.py の CLI ハンドラに関するテスト

このファイルには独立した複数の回帰テストが含まれる。

1. --setup-db（自動検出モード）のサイレント成功（過去に発生したバグ）:
     置き換え用テンプレートファイルが存在しない、またはインポート件数が0件でも
     成功扱いになっていた。

2. --healthの終了コード（過去に発生したバグ）:
     run_diagnostic()の戻り値を無視し、常に終了コード0を返していた。

3. start_scheduler_command()（--scheduleのハンドラ）のdry_run伝播
   （過去に発生したバグ）:
     start_scheduler_command()がdry_runパラメータを受け取らず、SchedulerManagerに
     渡していなかった。一方post_now_command()（--post-nowのハンドラ）は正しく
     dry_runを伝播していたため、この非対称性が見落とされていた。結果として
     `--schedule --dry-run`を実行しても常にdry_run=FalseでSchedulerManagerが
     生成され、9:00/13:30/19:00の通常投稿や引用RTチェックが本番同様に
     実行されてしまう状態だった。
"""

import pathlib
import sys
from typing import Any, Dict, List, Optional
from unittest import TestCase, mock

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main  # noqa: E402
from nikune.content_generator import GeneratedTweetContent  # noqa: E402
from nikune.post_safety import PostSafetyVerdict  # noqa: E402


def _make_db_manager_context(
    import_counts: Optional[List[int]] = None,
    templates: Optional[List[Dict[str, Any]]] = None,
) -> Any:
    """`with DatabaseManager() as db_manager:` を模したコンテキストマネージャーmock"""
    db_manager = mock.MagicMock()
    db_manager.import_templates_from_tsv.side_effect = import_counts or []
    db_manager.get_templates.return_value = templates or []
    context = mock.MagicMock()
    context.__enter__.return_value = db_manager
    context.__exit__.return_value = False
    return context, db_manager


class ImportTemplatesCommandAutoDetectTests(TestCase):
    """--setup-db（自動検出モード）が、置き換え用テンプレートが無い/0件しか
    インポートできない場合にサイレント成功しないことを検証する回帰テスト"""

    def test_returns_false_and_skips_clear_when_no_template_files_found(self) -> None:
        context, db_manager = _make_db_manager_context()
        with (
            mock.patch.object(main, "DatabaseManager", return_value=context),
            mock.patch.object(pathlib.Path, "exists", return_value=False),
        ):
            result = main.import_templates_command(file_path=None)

        self.assertFalse(result)
        db_manager.clear_all_templates.assert_not_called()

    def test_returns_false_when_zero_templates_imported_despite_files_existing(self) -> None:
        context, db_manager = _make_db_manager_context(import_counts=[0, 0])
        with (
            mock.patch.object(main, "DatabaseManager", return_value=context),
            mock.patch.object(pathlib.Path, "exists", return_value=True),
        ):
            result = main.import_templates_command(file_path=None)

        self.assertFalse(result)
        # ファイルは存在するのでクリア自体は実行される
        db_manager.clear_all_templates.assert_called_once()

    def test_returns_true_when_at_least_one_template_imported(self) -> None:
        context, db_manager = _make_db_manager_context(
            import_counts=[3, 0],
            templates=[{"category": "お肉"}] * 3,
        )
        with (
            mock.patch.object(main, "DatabaseManager", return_value=context),
            mock.patch.object(pathlib.Path, "exists", return_value=True),
        ):
            result = main.import_templates_command(file_path=None)

        self.assertTrue(result)

    def test_file_mode_returns_false_when_specified_file_yields_zero_templates(self) -> None:
        context, db_manager = _make_db_manager_context(import_counts=[0])
        with (
            mock.patch.object(main, "DatabaseManager", return_value=context),
            mock.patch.object(pathlib.Path, "exists", return_value=True),
        ):
            result = main.import_templates_command(file_path="data/custom.tsv")

        self.assertFalse(result)


class MainHealthCommandExitCodeTests(TestCase):
    """--healthが診断結果を反映した終了コードで返ることを検証する回帰テスト。
    修正前はrun_diagnostic()の戻り値を無視し常に終了コード0だった。"""

    def test_health_check_failure_results_in_nonzero_exit(self) -> None:
        fake_checker = mock.MagicMock()
        fake_checker.run_diagnostic.return_value = False

        with (
            mock.patch.object(main, "HealthChecker", return_value=fake_checker),
            mock.patch.object(sys, "argv", ["main.py", "--health"]),
        ):
            with self.assertRaises(SystemExit) as ctx:
                main.main()

        self.assertEqual(ctx.exception.code, 1)

    def test_health_check_success_results_in_zero_exit(self) -> None:
        fake_checker = mock.MagicMock()
        fake_checker.run_diagnostic.return_value = True

        with (
            mock.patch.object(main, "HealthChecker", return_value=fake_checker),
            mock.patch.object(sys, "argv", ["main.py", "--health"]),
        ):
            with self.assertRaises(SystemExit) as ctx:
                main.main()

        self.assertEqual(ctx.exception.code, 0)


def _make_scheduler_manager_mock() -> "tuple[mock.MagicMock, mock.MagicMock]":
    """SchedulerManagerのコンテキストマネージャーとしての振る舞いをモックする。"""
    scheduler_instance = mock.MagicMock()
    scheduler_instance.db_manager = mock.MagicMock()
    scheduler_instance.__enter__ = mock.Mock(return_value=scheduler_instance)
    scheduler_instance.__exit__ = mock.Mock(return_value=False)

    manager_cls = mock.MagicMock(return_value=scheduler_instance)
    return manager_cls, scheduler_instance


class StartSchedulerCommandDryRunTests(TestCase):
    """start_scheduler_command() が dry_run を SchedulerManager に伝播することを確認する。"""

    def test_dry_run_true_is_propagated_to_scheduler_manager(self) -> None:
        manager_cls, _scheduler_instance = _make_scheduler_manager_mock()

        with mock.patch.object(main, "SchedulerManager", manager_cls):
            with mock.patch.object(main, "setup_sample_data", return_value=True):
                result = main.start_scheduler_command(dry_run=True)

        self.assertTrue(result)
        manager_cls.assert_called_once_with(dry_run=True)

    def test_dry_run_false_is_propagated_to_scheduler_manager(self) -> None:
        manager_cls, _scheduler_instance = _make_scheduler_manager_mock()

        with mock.patch.object(main, "SchedulerManager", manager_cls):
            with mock.patch.object(main, "setup_sample_data", return_value=True):
                result = main.start_scheduler_command(dry_run=False)

        self.assertTrue(result)
        manager_cls.assert_called_once_with(dry_run=False)

    def test_dry_run_defaults_to_false_when_omitted(self) -> None:
        manager_cls, _scheduler_instance = _make_scheduler_manager_mock()

        with mock.patch.object(main, "SchedulerManager", manager_cls):
            with mock.patch.object(main, "setup_sample_data", return_value=True):
                main.start_scheduler_command()

        manager_cls.assert_called_once_with(dry_run=False)


class MainArgparseScheduleDryRunTests(TestCase):
    """argparseレベルで `--schedule --dry-run` が正しく伝播することを確認する。"""

    def test_schedule_dry_run_flag_calls_start_scheduler_command_with_dry_run_true(self) -> None:
        test_argv = ["main.py", "--schedule", "--dry-run"]

        with mock.patch.object(sys, "argv", test_argv):
            with mock.patch.object(main, "configure_logging"):
                with mock.patch.object(main, "start_scheduler_command", return_value=True) as mocked_start:
                    with self.assertRaises(SystemExit) as exit_ctx:
                        main.main()

        self.assertEqual(exit_ctx.exception.code, 0)
        mocked_start.assert_called_once_with(config_file=None, dry_run=True)

    def test_schedule_without_dry_run_flag_calls_start_scheduler_command_with_dry_run_false(self) -> None:
        test_argv = ["main.py", "--schedule"]

        with mock.patch.object(sys, "argv", test_argv):
            with mock.patch.object(main, "configure_logging"):
                with mock.patch.object(main, "start_scheduler_command", return_value=True) as mocked_start:
                    with self.assertRaises(SystemExit) as exit_ctx:
                        main.main()

        self.assertEqual(exit_ctx.exception.code, 0)
        mocked_start.assert_called_once_with(config_file=None, dry_run=False)


class PostNowCommandDryRunPrePostCheckTests(TestCase):
    """--post-now --dry-run でも投稿直前チェック（Jev）は実行し、Xへの投稿はしない"""

    def test_dry_run_template_post_runs_pre_post_check(self) -> None:
        manager_cls, scheduler = _make_scheduler_manager_mock()
        scheduler.content_generator.generate_tweet_content.return_value = GeneratedTweetContent(
            text="テスト", template_id=3
        )
        scheduler.run_pre_post_check.return_value = PostSafetyVerdict(decision="warn", reasons=["x"])

        with mock.patch.object(main, "SchedulerManager", manager_cls):
            with mock.patch.object(main, "setup_sample_data", return_value=True):
                result = main.post_now_command(dry_run=True)

        self.assertTrue(result)
        scheduler.run_pre_post_check.assert_called_once_with("テスト", route="post_now(dry-run)", template_id=3)
        scheduler.post_now.assert_not_called()
        scheduler.content_generator.record_tweet_usage.assert_not_called()

    def test_dry_run_custom_text_runs_pre_post_check(self) -> None:
        manager_cls, scheduler = _make_scheduler_manager_mock()
        scheduler.run_pre_post_check.return_value = None  # チェック自体が動かなくても止めない

        with mock.patch.object(main, "SchedulerManager", manager_cls):
            result = main.post_now_command(text="テスト", dry_run=True)

        self.assertTrue(result)
        scheduler.run_pre_post_check.assert_called_once_with("テスト", route="custom(dry-run)")
        scheduler.post_custom_tweet.assert_not_called()
