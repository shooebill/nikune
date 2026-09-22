"""
ロギング設定に関するテスト

過去に発生したバグ:
  nikune/content_generator.py・nikune/database.py・nikune/twitter_client.py が
  モジュール読み込み時（import時）にフォーマット指定なしで
  logging.basicConfig(level=logging.INFO) を呼んでいたため、main.py が
  自身のエントリポイント（main()関数内）でタイムスタンプ付きフォーマットを設定しても
  無視されていた。logging.basicConfig() は「最初に呼ばれた設定だけが有効」という
  Pythonの仕様があり、これらのモジュールをimportした時点（main.pyがimportするより先）で
  フォーマット指定なしの設定が既に確定してしまうことが原因だった。

  このテストファイルでは、再発防止のために以下を確認する:
    1. ライブラリ側モジュールをimportするだけではロギングの基本設定
       （ハンドラ追加）が行われないこと
    2. main.py側のロギング設定関数がタイムスタンプ・ロガー名を含む
       フォーマットを設定すること
"""

import logging
import subprocess
import sys
from pathlib import Path
from unittest import TestCase

import main as main_module

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# import時にlogging.basicConfig()を呼んでいないことを確認したいライブラリ側モジュール
LIBRARY_MODULES = [
    "nikune.content_generator",
    "nikune.database",
    "nikune.twitter_client",
]


class LibraryModulesDoNotConfigureLoggingTests(TestCase):
    """
    ライブラリ側モジュールのimportがロギングの基本設定に影響を与えないことを確認する。

    サブプロセスで新しいPythonインタプリタを起動し、対象モジュールをimportした直後の
    ルートロガーのハンドラ数を検証する。もしlogging.basicConfig()がモジュール読み込み時に
    呼ばれていれば、何もハンドラを追加していなくてもルートロガーにハンドラが1つ追加される。
    """

    def _root_logger_handler_count_after_import(self, module_name: str) -> int:
        script = "import logging\n" f"import {module_name}\n" "print(len(logging.getLogger().handlers))\n"
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, msg=f"{module_name} のimportに失敗: {result.stderr}")
        return int(result.stdout.strip())

    def test_importing_library_modules_does_not_add_root_handler(self) -> None:
        for module_name in LIBRARY_MODULES:
            with self.subTest(module=module_name):
                handler_count = self._root_logger_handler_count_after_import(module_name)
                self.assertEqual(
                    handler_count,
                    0,
                    msg=(
                        f"{module_name} のimportでルートロガーにハンドラが追加されました。"
                        "モジュールレベルでlogging.basicConfig()を呼んでいないか確認してください。"
                    ),
                )


class MainLoggingConfigurationTests(TestCase):
    """main.pyのロギング設定関数（configure_logging）の動作を確認する。"""

    def setUp(self) -> None:
        root = logging.getLogger()
        self._original_handlers = root.handlers[:]
        self._original_level = root.level
        root.handlers.clear()

    def tearDown(self) -> None:
        root = logging.getLogger()
        root.handlers[:] = self._original_handlers
        root.setLevel(self._original_level)

    def test_configure_logging_sets_timestamp_and_name_format(self) -> None:
        main_module.configure_logging(verbose=False)

        root = logging.getLogger()
        self.assertEqual(len(root.handlers), 1)
        self.assertEqual(root.level, logging.INFO)

        formatter = root.handlers[0].formatter
        if formatter is None:
            self.fail("ハンドラにFormatterが設定されていません")

        record = logging.LogRecord(
            name="nikune.some_module",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="テストメッセージ",
            args=None,
            exc_info=None,
        )
        formatted = formatter.format(record)

        # タイムスタンプ（YYYY-MM-DD HH:MM:SS,mmm 形式）が含まれること
        self.assertRegex(formatted, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
        # どのモジュールのログかが分かるよう、ロガー名が含まれること
        self.assertIn("nikune.some_module", formatted)
        self.assertIn("INFO", formatted)
        self.assertIn("テストメッセージ", formatted)

    def test_configure_logging_verbose_sets_debug_level(self) -> None:
        main_module.configure_logging(verbose=True)
        self.assertEqual(logging.getLogger().level, logging.DEBUG)
