#!/bin/bash
# nikune プロジェクト - コード品質チェックスクリプト

echo "🔍 nikune プロジェクト - コード品質チェック開始"
echo "=================================================="

echo ""
echo "1. Black (コードフォーマッター)"
echo "--------------------------------"
uv run black .
if [ $? -eq 0 ]; then
    echo "✅ Black: 完了"
else
    echo "❌ Black: エラー"
    exit 1
fi

echo ""
echo "2. isort (インポート整理)"
echo "-------------------------"
uv run isort .
if [ $? -eq 0 ]; then
    echo "✅ isort: 完了"
else
    echo "❌ isort: エラー"
    exit 1
fi

echo ""
echo "3. flake8 (リンター)"
echo "--------------------"
uv run flake8 nikune/ main.py config/ tests/
if [ $? -eq 0 ]; then
    echo "✅ flake8: 完了"
else
    echo "❌ flake8: エラー"
    exit 1
fi

echo ""
echo "4. mypy (型チェック)"
echo "--------------------"
uv run mypy .
if [ $? -eq 0 ]; then
    echo "✅ mypy: 完了"
else
    echo "❌ mypy: エラー"
    exit 1
fi

echo ""
echo "5. mypy --strict (厳格な型チェック)"
echo "----------------------------------"
uv run mypy --strict .
if [ $? -eq 0 ]; then
    echo "✅ mypy --strict: 完了"
else
    echo "❌ mypy --strict: エラー"
    exit 1
fi

echo ""
echo "6. pytest (テスト実行)"
echo "----------------------"
uv run pytest tests/
if [ $? -eq 0 ]; then
    echo "✅ pytest: 完了"
else
    echo "❌ pytest: エラー"
    exit 1
fi

echo ""
echo "🎉 すべてのコード品質チェックが完了しました！"
echo "=================================================="
