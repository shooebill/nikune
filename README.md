# Nikune Twitter Bot

可愛い子熊「nikune」がお肉のおいしさを自動投稿するTwitterボット

## 概要

- **名前**: nikune（にくね）
- **性格**: 可愛い子熊、お肉が大好き
- **機能**: 自動ツイート投稿、スケジューリング、重複防止

## セットアップ

### 1. 環境準備

```bash
# 仮想環境の作成と有効化
python -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate  # Windows

# 依存関係のインストール
pip install -r requirements.txt
```

### 2. 環境変数の設定

`.env` ファイルを作成し、以下の設定を追加：

```env
# Twitter API設定
TWITTER_API_KEY=your_api_key
TWITTER_API_SECRET=your_api_secret
TWITTER_ACCESS_TOKEN=your_access_token
TWITTER_ACCESS_TOKEN_SECRET=your_access_token_secret

# Redis設定（オプション）
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
```

### 3. データベースの初期化

```bash
# サンプルデータでデータベースを初期化
python main.py --setup-db --file data/sample_templates.tsv

# または自動検出（実データファイルがある場合）
python main.py --setup-db
```

## 使用方法

### 基本的なコマンド

```bash
# 即座に1回ツイート投稿
python main.py --post-now

# 特定のカテゴリで投稿
python main.py --post-now --category "お肉"

# カスタムテキストで投稿
python main.py --post-now --text "🐻 今日は特別なお肉を食べたよ！"

# スケジューラーを開始
python main.py --start-scheduler

# 全コンポーネントのテスト
python main.py --test
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

## プロジェクト構造

```
nikune/
├── main.py                 # メインエントリーポイント
├── config/
│   └── settings.py        # 設定ファイル
├── nikune/
│   ├── content_generator.py  # コンテンツ生成
│   ├── database.py          # データベース管理
│   ├── scheduler.py         # スケジューラー
│   └── twitter_client.py    # Twitter API クライアント
├── data/                   # データファイル
└── requirements.txt        # 依存関係
```

## 開発

### コード品質チェック

```bash
# コードフォーマット
black .

# インポート整理
isort .

# リンター
flake8 .

# 型チェック
mypy .
mypy --strict .
```

### テンプレートの追加

1. `data/tweet_templates.tsv` に新しいテンプレートを追加
2. `python main.py --setup-db` でデータベースを更新

### カテゴリ・トーンの追加

1. `data/category.tsv` または `data/tone.tsv` を編集
2. 新しいテンプレートで使用

## ライセンス

MIT License

## 注意事項

- 実データファイルは `.gitignore` によりリポジトリから除外されています
- 本番環境では適切な実データファイルを配置してください
- Twitter APIの利用規約を遵守してください
