#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/validate_growth_trend.py — **成長の軌道の測り方を2つ較べ、歴史で選ぶ**（2026-08-09新設）

発端（ユーザー「VISAのような成長が少しずつ鈍化している銘柄を落としたいんだよ」→ 年次を見たら V は
      2023:11.4% / 2024:10.0% / 2025:11.3% で**横ばい**だった）:
  v9.9.123 で入れた `cagrT`（端点どうしのCAGRの差＝歴史検証の accel と同一定義）には
  **1年の暴落・反動に脆い**という欠陥がある。実測で錨の年ごとに中央値がずれた——
    錨2024 −8.4pt(91%減速) / 錨2025 −5.3pt(75%) / 錨2026 −2.0pt(62%)
  錨2025 は c1=CAGR(2020→2023) で**2020のコロナ底が起点**＝反動が c1 を膨らませ、
  「74%が減速」の大半が**窓の置き方の artifact** だった。V の −3.7pt もこれ
  （2022年の +21.6% 反動が c1 に入っている）。

【較べる2つ】同じ窓・同じ向きで、中心の取り方だけ変える:
  A) `accel`  = CAGR(a-5→a-2, 3年) → CAGR(a-2→a, 2年) の差   ← 端点。今の cagrT
  B) `accelM` = median(YoY of a-4..a-2) → median(YoY of a-1..a) の差   ← 中央値。1年の外れに強い

【look-ahead を構造で防ぐ】asof 時点で**提出済み(filed ≤ asof-07-01)**の事実だけを使う
  （retro_features2 と同じ規律。決算期末ではなく**提出日**で切る）。

使い方: python3 night/validate_growth_trend.py [--asof 2018] [--limit N]
出力: out/growth_trend_validation.json
"""
import gzip
import json
import os
import statistics as st
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
UA = {'User-Agent': 'ccf-gate fortis5280@gmail.com', 'Accept-Encoding': 'gzip'}
ASOF = int(sys.argv[sys.argv.index('--asof') + 1]) if '--asof' in sys.argv else 2018
LIMIT = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 0
DEADLINE = f'{ASOF}-07-01'
REV = ["Revenues", "RegulatedAndUnregulatedOperatingRevenue",
       "RevenueFromContractWithCustomerExcludingAssessedTax",
       "RevenueFromContractWithCustomerIncludingAssessedTax",
       "SalesRevenueNet", "SalesRevenueGoodsNet", "SalesRevenueServicesNet", "Revenue"]


def get(url):
    for i in range(3):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120)
            b = r.read()
            if r.headers.get('Content-Encoding') == 'gzip':
                b = gzip.decompress(b)
            return json.loads(b)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1 + i)
        except Exception:
            time.sleep(1 + i)
    return None


def annual(js):
    """**提出日で切る**（look-aheadを構造で防ぐ）。同じ年は提出が新しいほうを採る"""
    U = (js.get('units') or {})
    if not U:
        return {}
    un = 'USD' if 'USD' in U else max(U, key=lambda k: len(U[k]))
    out, best = {}, {}
    for x in U[un]:
        f, s, e, fd = x.get('form', ''), x.get('start'), x.get('end'), x.get('filed', '')
        if not (f.startswith('10-K') or f.startswith('20-F')) or not s or fd > DEADLINE:
            continue
        m = (int(e[:4]) * 12 + int(e[5:7])) - (int(s[:4]) * 12 + int(s[5:7]))
        if m < 11 or m > 13:
            continue
        y = int(e[:4])
        if y not in best or fd > best[y]:
            best[y], out[y] = fd, x['val']
    return out


def splice(series, anchor=None):
    series = [s for s in series if s]
    if not series:
        return {}
    base = None
    if anchor is not None:
        for s in series:
            if anchor in s:
                base = dict(s)
                break
    if base is None:
        base = dict(max(series, key=lambda s: (max(s) if s else 0, len(s))))
    for s in series:
        ov = [y for y in s if y in base]
        if ov and all(abs(s[y] - base[y]) <= max(abs(base[y]), 1) * 0.005 for y in ov):
            for y, v in s.items():
                base.setdefault(y, v)
    return base


def cagr(v0, v1, n):
    if v0 is None or v1 is None or v0 <= 0 or v1 <= 0:
        return None
    return (v1 / v0) ** (1.0 / n) - 1


def main():
    R = {r['ticker']: r['tr_cagr'] for r in
         json.load(open(f'out/retro_returns_{ASOF}.json', encoding='utf-8'))['rows']}
    F = {r['ticker']: r for r in
         json.load(open(f'out/retro_features2_{ASOF}.json', encoding='utf-8'))['rows']}
    tk = get("https://www.sec.gov/files/company_tickers.json") or {}
    T2C = {}
    for r in tk.values():
        T2C.setdefault(r['ticker'].upper(), int(r['cik_str']))
    ts = [t for t in R if t in T2C]
    if LIMIT:
        ts = ts[:LIMIT]
    print(f'■ asof={ASOF}（提出日 ≤ {DEADLINE} の事実だけ）  対象 {len(ts)}社', file=sys.stderr)

    rows = []
    for i, t in enumerate(ts, 1):
        cf = get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{T2C[t]:010d}.json")
        time.sleep(0.08)
        if not cf:
            continue
        FA = cf.get('facts') or {}
        cand = []
        for ns, tag in ([('us-gaap', x) for x in REV] +
                        [('ifrs-full', x) for x in ('Revenue', 'RevenueFromContractsWithCustomers')]):
            js = (FA.get(ns) or {}).get(tag)
            if js:
                aa = annual(js)
                if aa:
                    cand.append(aa)
        # 錨は「提出済みの中で最新の会計年度」（asofの時点で読めた最後の年）
        pre = splice(cand)
        if not pre:
            continue
        a = max(pre)
        ser = splice(cand, a)
        need = list(range(a - 5, a + 1))
        if any(y not in ser or ser[y] <= 0 for y in need):
            continue
        yoy = {y: (ser[y] / ser[y - 1] - 1) * 100 for y in range(a - 4, a + 1)}
        c1 = cagr(ser[a - 5], ser[a - 2], 3)
        c2 = cagr(ser[a - 2], ser[a], 2)
        if c1 is None or c2 is None:
            continue
        # ── 長い窓（C案 fade8）: 8年の売上＝7つのYoY。**古い3年の中央値 → 新しい3年の中央値**。
        #   5年窓では ADBE(実際に20%台→10%へ固着)と V(11%で横ばい)が**ほぼ同値**になり区別できない。
        #   中央の1年は空けて両半分を分離する。中央値なので1年の暴落・反動に強い。
        fade8, old3, new3 = None, None, None
        if all(y in ser and ser[y] > 0 for y in range(a - 7, a + 1)):
            yy = {y: (ser[y] / ser[y - 1] - 1) * 100 for y in range(a - 6, a + 1)}
            old3 = st.median([yy[a - 6], yy[a - 5], yy[a - 4]])
            new3 = st.median([yy[a - 2], yy[a - 1], yy[a]])
            fade8 = round(new3 - old3, 2)
        rows.append(dict(t=t, a=a,
                         accel=round((c2 - c1) * 100, 2),
                         accelM=round(st.median([yoy[a - 1], yoy[a]])
                                      - st.median([yoy[a - 4], yoy[a - 3], yoy[a - 2]]), 2),
                         fade8=fade8, old3=round(old3, 2) if old3 is not None else None,
                         new3=round(new3, 2) if new3 is not None else None,
                         ret=R[t], opm=F.get(t, {}).get('opm')))
        if i % 100 == 0:
            print(f'  … {i}/{len(ts)}  採用{len(rows)}', file=sys.stderr)

    H = 0.15
    q = [r for r in rows if r['opm'] is not None and r['opm'] >= 0.10]
    print(f'\n■ 採用 {len(rows)}社（うち質実証プール {len(q)}社）')

    def table(pool, key, lab):
        p = sorted(pool, key=lambda r: r[key])
        n = len(p)
        print(f'\n  【{lab}】{key} の四分位 → 前方リターン')
        for i in range(4):
            g = p[i * n // 4:(i + 1) * n // 4]
            v = [x['ret'] for x in g]
            print(f"    Q{i+1} {g[0][key]:>+7.1f}〜{g[-1][key]:>+7.1f}pt  n={len(v):>4}"
                  f"  中央値{st.median(v)*100:>6.1f}%  15%+{sum(1 for x in v if x>=H)/len(v):>5.2f}"
                  f"  毀損{sum(1 for x in v if x<=-0.15)/len(v):>5.2f}")

    for key in ('accel', 'accelM'):
        table(rows, key, '全体')
        table(q, key, '質実証プール')
    f8 = [r for r in rows if r.get('fade8') is not None]
    q8 = [r for r in f8 if r['opm'] is not None and r['opm'] >= 0.10]
    print(f'\n■ C案 fade8（8年窓・古い3年→新しい3年の中央値）  n={len(f8)}（質実証 {len(q8)}）')
    table(f8, 'fade8', '全体')
    table(q8, 'fade8', '質実証プール')
    print('\n■ 線の候補（質実証プール・fade8）')
    for th in (0, -3, -5, -8, -10, -15):
        g = [r for r in q8 if r['fade8'] < th]
        o_ = [r for r in q8 if r['fade8'] >= th]
        if len(g) < 8:
            continue
        gv = [x['ret'] for x in g]
        ov = [x['ret'] for x in o_]
        print(f"  fade8<{th:>4}pt: 止めた{len(g):>4}社 中央値{st.median(gv)*100:>6.1f}% 15%+{sum(1 for x in gv if x>=H)/len(gv):>5.2f} 毀損{sum(1 for x in gv if x<=-0.15)/len(gv):>5.2f}"
              f"  ／ 通過{len(ov):>4}社 中央値{st.median(ov)*100:>6.1f}% 15%+{sum(1 for x in ov if x>=H)/len(ov):>5.2f}")
    print('\n■ 周期の谷との切り分け——fade8が深い群で「新しい3年の水準」別に見る')
    deep = [r for r in q8 if r['fade8'] < -8]
    for lab, fn in (('新3年 <5%', lambda r: r['new3'] < 5), ('5〜12%', lambda r: 5 <= r['new3'] < 12),
                    ('12%+', lambda r: r['new3'] >= 12)):
        g = [r for r in deep if fn(r)]
        if len(g) < 5:
            continue
        v = [x['ret'] for x in g]
        print(f"    {lab:<10}n={len(v):>4}  中央値{st.median(v)*100:>6.1f}%  15%+{sum(1 for x in v if x>=H)/len(v):>5.2f}  毀損{sum(1 for x in v if x<=-0.15)/len(v):>5.2f}")

    print('\n■ どちらが「錨の年のずれ（COVIDの窓）」に強いか——錨の年ごとの中央値')
    from collections import defaultdict
    by = defaultdict(list)
    for r in rows:
        by[r['a']].append(r)
    for a in sorted(by):
        g = by[a]
        if len(g) < 10:
            continue
        print(f"  錨{a}  n={len(g):>4}  accel中央値 {st.median([x['accel'] for x in g]):>+6.1f}pt"
              f"   accelM中央値 {st.median([x['accelM'] for x in g]):>+6.1f}pt")

    json.dump({'generated': '2026-08-09', 'asof': ASOF, 'deadline': DEADLINE, 'rows': rows},
              open('out/growth_trend_validation.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('\n→ out/growth_trend_validation.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
