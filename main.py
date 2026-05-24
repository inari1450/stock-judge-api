"""
株式判断補助ツール — バックエンドAPI
Yahoo Finance (yfinance) を使用
デプロイ先: Render.com 無料プラン
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Optional
import asyncio
import time

app = FastAPI(
    title="株式判断補助ツール API",
    description="Yahoo Finance (yfinance) を使った日本株スコアリングAPI",
    version="1.0.0"
)

# CORS設定 — フロントエンドからのアクセスを全許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------- キャッシュ（Render無料プランの制限対策） ---------
_cache: dict = {}
CACHE_TTL = 300  # 5分

def cache_get(key: str):
    if key in _cache:
        val, ts = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return val
    return None

def cache_set(key: str, val):
    _cache[key] = (val, time.time())


# --------- テクニカル計算 ---------

def calc_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = np.mean(gains[-period:])
    al = np.mean(losses[-period:])
    if al == 0:
        return 99.0
    rs = ag / al
    return round(100 - 100 / (1 + rs), 2)

def calc_ma(arr: list, n: int) -> float:
    if len(arr) < n:
        return arr[-1] if arr else 0
    return float(np.mean(arr[-n:]))

def calc_vol_ratio(vols: list) -> float:
    if len(vols) < 2:
        return 1.0
    recent = vols[-1]
    avg = calc_ma(vols[:-1], min(10, len(vols)-1))
    return round(recent / avg, 2) if avg > 0 else 1.0

def calc_vwap(highs, lows, closes, vols, n=5) -> float:
    n = min(n, len(closes))
    tvp = sum((highs[-n:][i]+lows[-n:][i]+closes[-n:][i])/3 * vols[-n:][i] for i in range(n))
    tvol = sum(vols[-n:])
    return round(tvp / tvol, 0) if tvol > 0 else closes[-1]

def calc_score(closes, highs, lows, vols) -> dict:
    last   = closes[-1]
    prev   = closes[-2] if len(closes) >= 2 else last
    base5  = closes[-6] if len(closes) >= 6 else closes[0]
    chg1   = round((last - prev) / prev * 100, 2)
    chg5   = round((last - base5) / base5 * 100, 2)
    rsi    = calc_rsi(closes)
    ma5    = calc_ma(closes, 5)
    ma25   = calc_ma(closes, 25)
    ma5dev = round((last - ma5) / ma5 * 100, 2)
    ma25dev= round((last - ma25) / ma25 * 100, 2)
    volr   = calc_vol_ratio(vols)
    vwap   = calc_vwap(highs, lows, closes, vols)
    vwapdev= round((last - vwap) / vwap * 100, 2)
    hw5    = max(highs[-5:]) if len(highs) >= 5 else last
    high_break = last >= hw5 * 0.995

    # モメンタムスコア (0-100)
    momentum = 0
    if chg5 > 5:   momentum += 28
    elif chg5 > 3: momentum += 20
    elif chg5 > 1: momentum += 12
    elif chg5 > 0: momentum += 5
    if volr > 3:     momentum += 28
    elif volr > 2:   momentum += 20
    elif volr > 1.5: momentum += 13
    elif volr > 1.2: momentum += 6
    if 55 < rsi < 75: momentum += 20
    elif rsi > 50:    momentum += 10
    elif rsi > 40:    momentum += 4
    if ma5dev > 0:   momentum += 12
    if ma25dev > 0:  momentum += 6
    if high_break:   momentum += 6
    momentum = min(100, momentum)

    # 危険度スコア (0-100)
    risk = 0
    if rsi > 78:    risk += 30
    elif rsi > 72:  risk += 18
    if chg5 > 10:   risk += 22
    elif chg5 > 7:  risk += 12
    if volr < 0.7:  risk += 18
    if chg1 < -3:   risk += 20
    upper_shadow = highs[-1] - max(last, prev)
    body = abs(last - prev)
    if body > 0 and upper_shadow > body * 1.5:
        risk += 12
    risk = min(100, risk)

    vol_score = min(20, volr * 6)
    safety = 100 - risk

    return {
        "last":      round(last, 0),
        "chg1":      chg1,
        "chg5":      chg5,
        "rsi":       rsi,
        "ma5dev":    ma5dev,
        "ma25dev":   ma25dev,
        "vol_ratio": volr,
        "vwap":      vwap,
        "vwap_dev":  vwapdev,
        "high_break": high_break,
        "momentum":  momentum,
        "risk":      risk,
        "safety":    safety,
        "vol_score": round(vol_score, 2),
    }

def calc_total_score(sc: dict, market_temp: float) -> int:
    raw = (
        sc["momentum"]  * 0.30 +
        market_temp     * 0.25 +
        sc["vol_score"] * 0.20 +
        sc["safety"]    * 0.15 +
        70              * 0.10
    )
    return max(1, min(99, round(raw)))

def get_action(score: int, risk: int) -> str:
    if risk > 60:  return "撤退"
    if score >= 75: return "買い"
    if score >= 55: return "監視"
    if score >= 35: return "様子見"
    return "見送り"


# --------- 銘柄データ取得 ---------

def fetch_ticker_data(code: str) -> dict:
    """yfinance で日本株データを取得（.T サフィックス付き）"""
    ticker = code if "." in code else f"{code}.T"
    cached = cache_get(ticker)
    if cached:
        return cached

    yf_ticker = yf.Ticker(ticker)
    hist = yf_ticker.history(period="2mo", interval="1d", auto_adjust=True)

    if hist.empty or len(hist) < 5:
        raise ValueError(f"{ticker}: データ取得失敗または件数不足")

    hist = hist.dropna(subset=["Close"])
    closes = hist["Close"].tolist()
    highs  = hist["High"].tolist()
    lows   = hist["Low"].tolist()
    vols   = hist["Volume"].tolist()
    dates  = [d.strftime("%Y-%m-%d") for d in hist.index]

    # 銘柄名取得
    try:
        info = yf_ticker.info
        name = info.get("shortName") or info.get("longName") or code
    except Exception:
        name = code

    sc = calc_score(closes, highs, lows, vols)
    result = {
        "ticker":  code,
        "symbol":  ticker,
        "name":    name,
        "dates":   dates,
        "closes":  [round(c, 0) for c in closes],
        "highs":   [round(h, 0) for h in highs],
        "lows":    [round(l, 0) for l in lows],
        "vols":    vols,
        "score":   sc,
        "fetched_at": datetime.now().isoformat(),
    }
    cache_set(ticker, result)
    return result


# --------- エンドポイント ---------

@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "株式判断補助ツール API",
        "endpoints": ["/quote/{code}", "/quotes", "/score/{code}", "/scores", "/health"]
    }

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

@app.get("/quote/{code}")
def get_quote(code: str):
    """単一銘柄の価格＋テクニカルデータ取得"""
    try:
        data = fetch_ticker_data(code)
        return data
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/quotes")
def get_quotes(codes: str = Query(..., description="カンマ区切り例: 9984,6758,7203")):
    """複数銘柄を一括取得"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    results = []
    errors  = []
    for code in code_list[:20]:  # 最大20銘柄
        try:
            results.append(fetch_ticker_data(code))
        except Exception as e:
            errors.append({"ticker": code, "error": str(e)})
    return {"results": results, "errors": errors, "count": len(results)}

@app.get("/score/{code}")
def get_score(code: str, market_temp: float = Query(70.0, ge=0, le=100)):
    """単一銘柄の総合スコアを返す"""
    try:
        data  = fetch_ticker_data(code)
        sc    = data["score"]
        total = calc_total_score(sc, market_temp)
        action = get_action(total, sc["risk"])
        return {
            "ticker":       code,
            "name":         data["name"],
            "total_score":  total,
            "action":       action,
            "breakdown": {
                "地合い":    round(market_temp * 0.25),
                "モメンタム": round(sc["momentum"] * 0.30),
                "出来高":    round(sc["vol_score"] * 0.20),
                "安全性":    round(sc["safety"] * 0.15),
                "セクター":  7,
            },
            "indicators": sc,
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/scores")
def get_scores(
    codes: str = Query(..., description="カンマ区切り例: 9984,6758,7203"),
    market_temp: Optional[float] = None
):
    """
    複数銘柄のスコアを一括計算。
    market_temp 未指定時は全銘柄の平均騰落から自動算出。
    """
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    all_data  = []
    errors    = []

    for code in code_list[:20]:
        try:
            all_data.append(fetch_ticker_data(code))
        except Exception as e:
            errors.append({"ticker": code, "error": str(e)})

    if not all_data:
        return {"results": [], "errors": errors, "market_temp": 50}

    # 市場温度を自動計算（未指定時）
    if market_temp is None:
        scores_list = [d["score"] for d in all_data]
        avg_chg  = np.mean([s["chg5"]      for s in scores_list])
        avg_vol  = np.mean([s["vol_ratio"] for s in scores_list])
        up_ratio = sum(1 for s in scores_list if s["chg5"] > 0) / len(scores_list)
        mt = 50 + avg_chg * 2.5 + (avg_vol - 1) * 10 + (up_ratio - 0.5) * 24
        market_temp = max(0, min(100, round(mt)))

    results = []
    for d in all_data:
        sc     = d["score"]
        total  = calc_total_score(sc, market_temp)
        action = get_action(total, sc["risk"])
        results.append({
            "ticker":      d["ticker"],
            "name":        d["name"],
            "last":        sc["last"],
            "chg5":        sc["chg5"],
            "vol_ratio":   sc["vol_ratio"],
            "rsi":         sc["rsi"],
            "total_score": total,
            "momentum":    sc["momentum"],
            "risk":        sc["risk"],
            "action":      action,
        })

    results.sort(key=lambda x: x["total_score"], reverse=True)

    return {
        "results":     results,
        "errors":      errors,
        "market_temp": market_temp,
        "count":       len(results),
        "summary": {
            "buy":   sum(1 for r in results if r["action"] == "買い"),
            "watch": sum(1 for r in results if r["action"] == "監視"),
            "wait":  sum(1 for r in results if r["action"] == "様子見"),
            "avg_score": round(np.mean([r["total_score"] for r in results])),
        }
    }
