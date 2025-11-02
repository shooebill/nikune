"""
nikune bot utility functions
共通ユーティリティ関数を提供
"""

import logging
from typing import List

# ロガー設定
logger = logging.getLogger(__name__)


def log_errors(
    errors: List[str], max_errors_to_display: int = 3, indent: str = "   ", error_indent: str = "      "
) -> None:
    """
    エラーリストをログに表示する共通関数

    Args:
        errors: エラーメッセージのリスト
        max_errors_to_display: 表示するエラーの最大数
        indent: エラーヘッダーのインデント
        error_indent: 各エラーのインデント
    """
    if errors:
        logger.warning(f"{indent}⚠️  Errors occurred: {len(errors)}")
        # 大量のエラーでログが埋まるのを防ぐため、最初のmax_errors_to_display件のみ表示
        for error in errors[:max_errors_to_display]:
            logger.warning(f"{error_indent}- {error}")
        if len(errors) > max_errors_to_display:
            logger.warning(f"{error_indent}... and {len(errors) - max_errors_to_display} more errors")
