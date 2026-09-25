#!/usr/bin/env python3
"""night/etf_longest.py — 長い歴史で高いリターンを出したETF（と、ETFより前を延ばす投信・指数）を測る（2026-09-25・ユーザー指示）

読むだけ。門・配分には触れない。
母集団 A: out/broker_lineup.json（楽天の海外ETF 742本＝今日買えるもの）のうち米国上場。レバレッジ・インバースは名前で除外。
母集団 B（代理）: ETF が無い時代まで延ばすため、同じ分野を長く追う投信・指数（Fidelity Select の分野別・Vanguard の指数投信など）。
  ⚠ B は ETF ではない（アクティブ運用を含む・買えるとは限らない）。**分野そのものの長い成績**を見るための代理。
基準: VFINX（S&P500 の指数投信・配当込み・1976〜）。どの本も**その本の全期間と同じ窓**の VFINX と比べる（設定日の罠を避ける）。
物差し: 全期間の年率と超過 ／ 転がる20年（一括）で S&P500 に勝った割合と最悪の超過 ／ 転がる20年の毎月積立で勝った割合と倍率比 ／ 最大下落・最長の水没
出力: out/etf_longest.json
"""
import datetime, json, os, re, sys, time, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
LEV = re.compile(r'(2x|3x|-1x|-2x|-3x|ultra|inverse|short|bear\b|bull\b|daily|leverag|1\.5x|2\.0x|3\.0x)', re.I)
PROXY = {  # 分野の長い代理（投信・指数）。ETF ではない
    'VFINX': 'S&P500 指数投信', 'VIGRX': 'Vanguard 成長株指数', 'NAESX': 'Vanguard 小型株指数', '^NDX': 'ナスダック100（価格のみ・配当なし）',
    'FSELX': 'Fidelity 半導体', 'FSPTX': 'Fidelity テクノロジー', 'FSCSX': 'Fidelity ソフトウェア', 'FDCPX': 'Fidelity コンピュータ',
    'VGHCX': 'Vanguard ヘルスケア', 'FBIOX': 'Fidelity バイオ', 'FSPHX': 'Fidelity ヘルスケア', 'FSMEX': 'Fidelity 医療機器',
    'FSDAX': 'Fidelity 防衛・航空', 'VGENX': 'Vanguard エネルギー', 'FSRPX': 'Fidelity 小売', 'FDFAX': 'Fidelity 生活必需品',
    'FSCHX': 'Fidelity 化学', 'FCNTX': 'Fidelity Contrafund（大型成長・アクティブ）', 'PRGFX': 'T.Rowe 成長株', 'VWUSX': 'Vanguard 米国成長',
}

def fetch(sym):
    t0 = int(datetime.datetime(1971, 1, 1).timestamp()); t1 = int(time.time())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={t0}&period2={t1}&interval=1mo"
    for a in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                res = (json.loads(r.read()).get("chart", {}).get("result") or [None])[0]
            if not res: return None
            ind = res["indicators"]; ser = (ind.get("adjclose") or [{}])[0].get("adjclose") or ind["quote"][0]["close"]
            gmt = (res.get("meta") or {}).get("gmtoffset") or 0; o = {}
            for t, v in zip(res["timestamp"], ser):
                if v is None or v <= 0: continue
                d = datetime.datetime.utcfromtimestamp(t + gmt); o[f"{d.year:04d}-{d.month:02d}"] = float(v)
            return o or None
        except urllib.error.HTTPError as e:
            if e.code in (400, 404): return None
            time.sleep(2 * (a + 1))
        except Exception:
            time.sleep(2 * (a + 1))
    return None

def mdiff(a, b): return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:]) - int(a[5:])

def metrics(s, bm):
    ks = sorted(k for k in s if k in bm)
    if len(ks) < 120: return None
    a, b = ks[0], ks[-1]; n = mdiff(a, b); yrs = n / 12
    cg = (s[b] / s[a]) ** (12 / n) - 1; bg = (bm[b] / bm[a]) ** (12 / n) - 1
    pk, dd, uw, uwmax, pkk = 0, 0, 0, 0, None
    for k in ks:
        v = s[k]
        if v >= pk: pk, pkk = v, k
        dd = min(dd, v / pk - 1); uwmax = max(uwmax, mdiff(pkk, k))
    out = dict(start=a, years=round(yrs, 1), cagr=round(cg * 100, 2), bench=round(bg * 100, 2), excess=round((cg - bg) * 100, 2),
               max_dd=round(dd * 100, 1), underwater_yrs=round(uwmax / 12, 1))
    L = 240; idx = {k: i for i, k in enumerate(ks)}
    wins, worst, dca_w, dca_r = [], None, [], []
    for i in range(len(ks)):
        j = i + L
        if j >= len(ks) or mdiff(ks[i], ks[j]) != L: continue
        e = ((s[ks[j]] / s[ks[i]]) ** (1 / 20) - (bm[ks[j]] / bm[ks[i]]) ** (1 / 20)) * 100
        wins.append(e > 0); worst = e if worst is None else min(worst, e)
        m1 = sum(s[ks[j]] / s[ks[x]] for x in range(i, j)); m2 = sum(bm[ks[j]] / bm[ks[x]] for x in range(i, j))
        dca_w.append(m1 > m2); dca_r.append(m1 / m2)
    if wins:
        dca_r.sort()
        out.update(roll20_n=len(wins), roll20_win=round(sum(wins) / len(wins), 3), roll20_worst=round(worst, 2),
                   dca20_win=round(sum(dca_w) / len(dca_w), 3), dca20_ratio_med=round(dca_r[len(dca_r) // 2], 3), dca20_ratio_min=round(dca_r[0], 3))
    return out

def main():
    lu = json.load(open(os.path.join(BASE, 'out', 'broker_lineup.json')))['etfs']
    etfs = {t: v['nm'] for t, v in lu.items() if not t[:1].isdigit() and not LEV.search(v.get('nm', ''))}
    bm = fetch('VFINX'); rows, fail = {}, []
    for i, (t, nm) in enumerate(sorted(list(etfs.items()) + [(k, v) for k, v in PROXY.items()])):
        s = fetch(t)
        if not s: fail.append(t); continue
        m = metrics(s, bm)
        if m: m.update(name=nm, kind='proxy' if t in PROXY else 'etf'); rows[t] = m
        if i % 50 == 0: print(i, t, flush=True)
    out = dict(generated=datetime.date.today().isoformat(), tool='night/etf_longest.py', bench='VFINX（S&P500 指数投信・配当込み）',
               universe=f'楽天の海外ETF {len(etfs)}本（レバ・インバース除外）＋代理 {len(PROXY)}本', failed=fail, rows=rows)
    json.dump(out, open(os.path.join(BASE, 'out', 'etf_longest.json'), 'w'), ensure_ascii=False, indent=1)
    print('測れた', len(rows), '取得失敗', len(fail))

if __name__ == '__main__':
    main()
