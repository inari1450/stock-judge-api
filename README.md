# 株式判断補助ツール — バックエンドAPI

Yahoo Finance (yfinance) を使った日本株スコアリングAPI。  
**完全無料** で Render.com にデプロイできます。

---

## デプロイ手順（5分で完了）

### 1. GitHubにアップロード

```bash
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/あなたのユーザー名/stock-judge-api.git
git push -u origin main
```

### 2. Render.com でデプロイ

1. https://render.com にアクセス → 無料アカウント作成
2. 「New +」→「Web Service」をクリック
3. GitHubリポジトリを接続
4. 以下を設定：
   - **Name**: stock-judge-api（任意）
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: Free
5. 「Create Web Service」をクリック

デプロイ完了後、以下のようなURLが発行されます：  
`https://stock-judge-api.onrender.com`

---

## APIエンドポイント一覧

| エンドポイント | 説明 | 例 |
|---|---|---|
| `GET /` | ルート（API確認） | `/` |
| `GET /health` | ヘルスチェック | `/health` |
| `GET /quote/{code}` | 単一銘柄データ取得 | `/quote/9984` |
| `GET /quotes?codes=` | 複数銘柄一括取得 | `/quotes?codes=9984,6758,7203` |
| `GET /score/{code}` | 単一スコア計算 | `/score/9984` |
| `GET /scores?codes=` | 複数スコア一括計算 | `/scores?codes=9984,6758,8035` |

### レスポンス例 `/scores?codes=9984,6758`

```json
{
  "results": [
    {
      "ticker": "9984",
      "name": "SoftBank Group Corp.",
      "last": 9240,
      "chg5": 3.8,
      "vol_ratio": 3.2,
      "rsi": 71.2,
      "total_score": 87,
      "momentum": 74,
      "risk": 18,
      "action": "買い"
    }
  ],
  "market_temp": 72,
  "summary": {
    "buy": 1, "watch": 1, "wait": 0, "avg_score": 75
  }
}
```

---

## フロントエンドからの接続

デプロイ後、フロントのJSを以下に変更するだけです：

```javascript
const API_BASE = "https://stock-judge-api.onrender.com";

// 複数銘柄スコア取得
const res = await fetch(`${API_BASE}/scores?codes=9984,6758,6857`);
const data = await res.json();
```

---

## 注意事項

- Render無料プランは**15分アクセスがないとスリープ**します（初回アクセスに約30秒かかります）
- yfinanceは非公式APIのため、Yahoo側の変更で動作しなくなる場合があります
- 個人利用・開発用途でご使用ください
