# LINE 割り勘Bot

LINEグループチャットで割り勘計算・精算管理ができるBotです。

## 機能

| 入力例 | 動作 |
|--------|------|
| `3000円 3人` | その場で割り勘計算（端数処理あり） |
| `人数 4人` | グループの人数をセット |
| `記録 1500円 ランチ` | 支払いを記録 |
| `精算` | 記録した支払いを合計して割り勘計算 |
| `リセット` | 記録をクリア |
| `ヘルプ` | 使い方を表示 |

### 端数処理の例

```
3100円 ÷ 3人
→ 1人: 1,034円
→ 2人: 1,033円
（端数1円を1人に分配）
```

---

## セットアップ

### 1. LINE Developers でチャネルを作成

1. [LINE Developers Console](https://developers.line.biz/) にログイン
2. 新しいプロバイダーを作成
3. **Messaging API** チャネルを作成
4. チャネルシークレットとチャネルアクセストークン（長期）を取得

### 2. ローカル環境の準備

```bash
# リポジトリをクローン（またはフォルダに移動）
cd line-warikan-bot

# 仮想環境を作成・有効化
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 依存パッケージをインストール
pip install -r requirements.txt

# 環境変数ファイルを作成
cp .env.template .env
# .env を編集して LINE_CHANNEL_SECRET と LINE_CHANNEL_ACCESS_TOKEN を設定
```

### 3. ローカルで起動

```bash
uvicorn app.main:app --reload --port 8000
```

---

## デプロイ手順

### A. Railway（推奨・無料枠あり）

1. [Railway](https://railway.app/) でアカウント作成
2. 「New Project」→「Deploy from GitHub repo」
3. このリポジトリを選択
4. 環境変数を設定:
   - `LINE_CHANNEL_SECRET`
   - `LINE_CHANNEL_ACCESS_TOKEN`
5. デプロイ後に発行されたURLを控える（例: `https://xxx.railway.app`）

### B. Render（無料枠あり）

1. [Render](https://render.com/) でアカウント作成
2. 「New Web Service」→ GitHubリポジトリを連携
3. 設定:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Environment Variables に `LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN` を追加
5. デプロイ後のURLを控える

### C. Heroku

```bash
# Heroku CLI でデプロイ
heroku create your-app-name
heroku config:set LINE_CHANNEL_SECRET=xxx LINE_CHANNEL_ACCESS_TOKEN=yyy
git push heroku main
```

---

## Webhook URL の設定

デプロイ後、LINE Developers Console で Webhook を設定します。

1. チャネルの「Messaging API設定」を開く
2. **Webhook URL** に以下を入力:
   ```
   https://<your-app-domain>/webhook
   ```
3. 「検証」ボタンで接続確認
4. **Webhookの利用** を ON にする
5. **応答メッセージ** を OFF にする（Botと競合するため）

---

## ローカルテスト（ngrok を使う場合）

```bash
# ngrok をインストール後
ngrok http 8000

# 表示された https URL を Webhook URL として LINE に設定
# 例: https://xxxx.ngrok.io/webhook
```

---

## テスト実行

```bash
pip install pytest
pytest tests/
```

---

## プロジェクト構成

```
line-warikan-bot/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI アプリ・Webhook エンドポイント
│   ├── line_handler.py  # メッセージ解釈・レスポンス生成
│   ├── warikan.py       # 割り勘計算ロジック
│   └── storage.py       # グループセッション管理（インメモリ）
├── tests/
│   └── test_warikan.py  # ユニットテスト
├── .env.template        # 環境変数テンプレート
├── .gitignore
├── Procfile             # Heroku / Railway 用
├── requirements.txt
└── README.md
```

---

## 注意事項

- `storage.py` はインメモリ実装のため、サーバー再起動で記録がリセットされます
- 永続化が必要な場合は Redis や SQLite に差し替えてください
- `.env` ファイルは絶対にコミットしないでください（`.gitignore` 済み）
