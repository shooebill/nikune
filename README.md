# 🐻 Nikune Twitter Bot

可愛い子熊「nikune」がお肉のおいしさを自動投稿するTwitterボット

[![Python](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## ✨ 概要

- **名前**: nikune（にくね） 🐻
- **性格**: 可愛い子熊、お肉が大好き 🥩
- **機能**: 自動ツイート投稿、スケジューリング、重複防止、動的コンテンツ生成

### 🚀 主な機能

- ✅ **自動ツイート投稿**: スケジューラーによる定期投稿
- ✅ **重複防止**: Redisキャッシュによるテンプレート管理
- ✅ **動的コンテンツ**: 時間・挨拶・絵文字の自動挿入
- ✅ **カテゴリ・トーン管理**: 柔軟なテンプレート分類
- ✅ **ドライランモード**: 安全なテスト実行
- ✅ **クロスプラットフォーム対応**: Windows/Mac/Linux対応

## 🛠️ セットアップ

### 📋 前提条件

- **Python 3.8+** （Python 3.10+推奨）
- **Redis Server** （必須：重複防止機能とシステム安定性に必要）
- **Twitter API v2** アクセス権限

### 1. 🐍 環境準備

#### 方法A: uv使用（モダン・高速）

```bash
# uvがインストール済みの場合
uv python install 3.12  # またはお好みのバージョン
uv sync
```

#### 方法B: 標準的なPython環境（推奨）

```bash
# 仮想環境作成・有効化
python -m venv .venv

# 環境有効化
source .venv/bin/activate    # macOS/Linux
# .venv\Scripts\activate     # Windows

# 依存関係インストール
pip install -r requirements.txt
```

#### 方法C: システムPython（シンプル）

```bash
# 直接インストール（非推奨：テスト用のみ）
pip install -r requirements.txt
```

### 2. 🔗 Redis セットアップ（必須）

> ⚠️ **重要**: Redisはシステム動作に必須です。接続できない場合、アプリケーションは起動しません。

#### 💻 Windows

```bash
# 選択肢1: WSL2 Ubuntu (推奨)
wsl -d Ubuntu-20.04  # またはお使いのディストリビューション
sudo apt update && sudo apt install -y redis-server
sudo service redis-server start
redis-cli ping  # "PONG"が返ればOK

# 選択肢2: Windows版Redis (Memurai)
# https://www.memurai.com/ からダウンロード・インストール

# 選択肢3: Docker
docker run -d -p 6379:6379 redis:alpine
```

#### 🍎 macOS

```bash
# 選択肢1: Homebrew (推奨)
brew install redis
brew services start redis

# 選択肢2: MacPorts
sudo port install redis
sudo port load redis

# 選択肢3: Docker
docker run -d -p 6379:6379 redis:alpine
```

#### 🐧 Linux

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y redis-server
sudo systemctl start redis-server

# CentOS/RHEL
sudo yum install -y redis
sudo systemctl start redis
```

### 3. 🔑 環境変数の設定

`.env` ファイルを作成し、以下の設定を追加：

```env
# Twitter API v2 設定
TWITTER_API_KEY=your_api_key
TWITTER_API_SECRET=your_api_secret
TWITTER_ACCESS_TOKEN=your_access_token
TWITTER_ACCESS_TOKEN_SECRET=your_access_token_secret
TWITTER_BEARER_TOKEN=your_bearer_token

# Redis設定
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
```

### 4. 🗄️ データベースの初期化

```bash
# 全システムテスト（推奨：環境確認）
python main.py --test
# または uv使用時: uv run python main.py --test

# サンプルデータでデータベースを初期化
python main.py --setup-db --file data/sample_templates.tsv
```

### ⚡ クイックスタート（開発・テスト用）

開発やテスト用に最小構成で素早く起動する場合：

```bash
# 1. Redis起動（必須）
# Windows (WSL2): sudo service redis-server start
# macOS: brew services start redis  
# Linux: sudo systemctl start redis-server

# 2. 最小限の.env作成（Twitter APIキー必須）
echo "TWITTER_API_KEY=your_key_here" > .env
echo "TWITTER_API_SECRET=your_secret_here" >> .env
echo "TWITTER_ACCESS_TOKEN=your_token_here" >> .env  
echo "TWITTER_ACCESS_TOKEN_SECRET=your_token_secret_here" >> .env

# 3. 依存関係インストール
pip install -r requirements.txt

# 4. テスト実行（Redis接続確認含む）
python main.py --test

# 5. ドライラン（実際に投稿しない）
python main.py --post-now --dry-run
```

## 🎮 使用方法

### 🚀 基本的なコマンド

```bash
# 🧪 全システムテスト（推奨：最初に実行）
python main.py --test

# 🐻 即座に1回ツイート投稿
python main.py --post-now

# 🥩 特定のカテゴリで投稿
python main.py --post-now --category "お肉"

# 💭 カスタムテキストで投稿
python main.py --post-now --text "🐻 今日は特別なお肉を食べたよ！"

# 🔍 ドライランモード（実際には投稿しない）
python main.py --post-now --dry-run

# ⏰ スケジューラーを開始（デフォルト：09:00, 13:30, 19:00）
python main.py --schedule
```

> 💡 **uv使用時**: 上記コマンドの前に `uv run` を付けてください  
> 例: `uv run python main.py --test`

### 📊 動作確認コマンド

```bash
# データベース接続確認
uv run python main.py --test

# コンテンツ生成テスト
uv run python main.py --post-now --dry-run

# Twitter API接続確認
# （.envファイル設定後に実行）
```

### テンプレート管理

```bash
# テンプレートのインポート
python main.py --setup-db --file data/your_templates.tsv

# データベースのクリアと再インポート
python main.py --setup-db
```

## データファイル

### リポジトリに含まれるファイル

- `data/sample_templates.tsv` - サンプルテンプレート（19個）
- `data/category.tsv` - カテゴリマスタデータ
- `data/tone.tsv` - トーンマスタデータ

### 実データファイル（.gitignore対象）

- `data/templates.db` - SQLiteデータベース
- `data/tweet_templates.tsv` - 手入力テンプレート
- `data/tweet_templates.generated.tsv` - AI生成テンプレート
- `data/exported_templates.tsv` - エクスポートされたテンプレート

## 📁 プロジェクト構造

```
nikune/
├── 📄 main.py                 # メインエントリーポイント
├── 📁 config/
│   ├── __init__.py
│   └── settings.py            # 環境変数管理
├── 📁 nikune/
│   ├── __init__.py
│   ├── content_generator.py   # 🎨 動的コンテンツ生成
│   ├── database.py           # 🗄️ SQLite + Redis管理
│   ├── scheduler.py          # ⏰ 自動投稿スケジューラー
│   └── twitter_client.py     # 🐦 Twitter API v2クライアント
├── 📁 data/
│   ├── category.tsv          # カテゴリマスタ
│   ├── tone.tsv             # トーンマスタ
│   └── sample_templates.tsv  # サンプルテンプレート
├── ⚙️ pyproject.toml          # プロジェクト設定・依存関係
├── 📝 requirements.txt        # pip互換依存関係
├── 🔧 .flake8               # コード品質設定
├── 🎯 .gitattributes         # Git属性（LF統一）
├── 🚫 .gitignore             # Git除外設定
└── 🐍 .python-version        # Pythonバージョン指定
```

### 🔧 設定ファイル詳細

| ファイル | 目的 | 設定内容 |
|----------|------|----------|
| `pyproject.toml` | プロジェクト統合設定 | 依存関係、Black/isort/mypy設定 |
| `.flake8` | コード品質 | 120文字制限、除外パターン |
| `.gitattributes` | Git属性 | LF改行コード統一 |
| `.python-version` | バージョン管理 | Python 3.14指定 |

## 💻 開発環境

### 🔧 開発ツール統合

本プロジェクトは高品質なコード維持のため、以下のツールを統合しています：

```bash
# 🎨 コードフォーマット（120文字制限）
black .

# 📦 インポート整理
isort .

# 🔍 コード品質チェック
flake8

# 🏷️ 型チェック
mypy nikune/ main.py

# 🚀 全品質チェックの実行
black . && isort . && flake8 && mypy nikune/ main.py
```

> 💡 **uv使用時**: 各コマンドの前に `uv run` を付けてください  
> 例: `uv run black .`

### ⚙️ 設定ファイル

- **pyproject.toml**: Black, isort, mypy設定
- **.flake8**: コード品質設定
- **.gitattributes**: 改行コードLF統一
- **.gitignore**: Mac互換性とクリーンな環境

### 🌍 クロスプラットフォーム対応

- ✅ **Windows**: WSL2 + Redis対応
- ✅ **macOS**: Homebrew + Redis対応  
- ✅ **Linux**: 直接Redis使用
- ✅ **改行コード**: LF統一（.gitattributes）

### テンプレートの追加

1. `data/tweet_templates.tsv` に新しいテンプレートを追加
2. `python main.py --setup-db` でデータベースを更新

### カテゴリ・トーンの追加

1. `data/category.tsv` または `data/tone.tsv` を編集
2. 新しいテンプレートで使用

## 🔧 トラブルシューティング

### よくある問題

#### Redis接続エラー
```bash
# WSL2でRedis起動確認
wsl -d Ubuntu-24.04 redis-cli ping

# Redisサービス起動
wsl -d Ubuntu-24.04 sudo service redis-server start
```

#### Twitter API認証エラー
- `.env`ファイルの設定を確認
- Twitter Developer Portalでトークンを再生成

#### 依存関係エラー
```bash
# 標準的な解決方法
pip install -r requirements.txt --force-reinstall

# uv使用時
uv sync --frozen
```

### パフォーマンス最適化

- **データベース**: SQLite + Redisデュアル構成
- **重複防止**: Redisキャッシュによる高速化
- **メモリ効率**: コンテキストマネージャーによるリソース管理

## 🤝 コントリビューション

1. このリポジトリをフォーク
2. 機能ブランチを作成: `git checkout -b feature/amazing-feature`
3. コード品質チェック: `uv run black . && uv run flake8 && uv run mypy nikune/ main.py`
4. 変更をコミット: `git commit -m 'feat: add amazing feature'`
5. ブランチをプッシュ: `git push origin feature/amazing-feature`
6. Pull Requestを作成

### 📝 コミット規約

- `feat:` 新機能
- `fix:` バグ修正
- `chore:` 雑務・設定変更
- `docs:` ドキュメント更新

## 📄 ライセンス

MIT License - 詳細は [LICENSE](LICENSE) ファイルを参照

## ⚠️ 注意事項

- 🔒 実データファイル（`.db`, 個人用`.tsv`）は`.gitignore`により除外
- 🐦 Twitter API利用規約を遵守してください
- 🌍 本プロジェクトはクロスプラットフォーム対応済み
- 🔧 本番環境では適切な`.env`設定が必要

## 🎯 今後の予定

- [ ] Web UI ダッシュボード
- [ ] 投稿パフォーマンス分析
- [ ] AI自動テンプレート生成
- [ ] マルチアカウント対応
