import pathlib
import sys
from typing import Any, Dict, List, Optional
from unittest import TestCase, mock

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main  # noqa: E402


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
