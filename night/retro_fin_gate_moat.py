#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/retro_fin_gate_moat.py — **堀を通った社の中で、財務の線は選別力を持つか**（2026-08-09新設）

発端: 同日の `retro_nde_kill85.py` で、irr=85（のべ40件）の中では
  ・財務キル(nde>4)が止めたのは TDG 一社だけで、それは +21.7% / +20.7% の勝者だった
  ・唯一壊れた CMTL は**純現金**だった
  ・母集団全体では intcov が単調に左尾を分ける（≤1 0.14 → ≥5 0.02）のに nde は非単調
と出た。だが irr=85 は n=40 で、**「堀を通った社の中で財務の線が効かない」と言うには薄すぎる**。
そこで**堀の関門を通った群の歴史側の相当物＝irr≥70（2018年ビンテージは刻みが違うので≥75）**まで
広げて、n を厚くして測り直す。

【なぜこの問いか】この台帳は「価格の線は質・堀の中では選別力を持たない」を**4回**実証している
  （横断面PER 2013/2015・fairPER倍率・E[r]・自己相対）。**財務の線も同じ形かどうか**は、
  規約を一切触らずに測れる。答えが「同じ形」なら、財務の関門は**選別器としては使えない**
  （＝遮断器＝左尾ガードとしてのみ意味を持つ）ことになり、物差しを替える議論の土台が変わる。

【遮断器の物差し】通した側の平均ではなく**止めた側の左尾（恒久毀損 P(年率≤−15%)）**で裁く
  （v9.9.98 で E[r] を外したときと同じ作法）。中央値は「選別力があるか」の側で読む。

【look-ahead を構造で防ぐ】**提出日 filed ≤ {年}-07-01 の事実だけ**。式とタグは
  retro_features_2018.py（nde）／retro_features2.py（intcov）と同一にする。

使い方: python3 night/retro_fin_gate_moat.py [--json] [--limit N]
出力: out/retro_fin_gate_moat.json
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
AS_JSON = '--json' in sys.argv[1:]
LIMIT = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else 0
H = 0.15

OP = ["OperatingIncomeLoss"]
DEBT_LT = ["LongTermDebtNoncurrent", "LongTermDebt", "DebtAndCapitalLeaseObligations",
           "LongTermDebtAndCapitalLeaseObligations"]
DEBT_C = ["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings",
          "LongTermDebtAndCapitalLeaseObligationsCurrent"]
CASH = ["CashAndCashEquivalentsAtCarryingValue"]
DEP = ["DepreciationDepletionAndAmortization", "Depreciation"]
AMO = ["AmortizationOfIntangibleAssets"]
INT = ["InterestExpense", "InterestExpenseDebt", "InterestAndDebtExpense"]
EQ = ["StockholdersEquity"]

# 堀を通った群の歴史側の相当物。2018年ビンテージだけ刻みが 50/75/85 なので線が違う
VINT = [('2013', 'out/retro_returns_2013_all.json', 'irr', 70,
         ['out/retro_moat_2013.json', 'out/retro_moat_2013q.json']),
        ('2015', 'out/retro_returns_2015_q.json', 'irr', 70,
         ['out/retro_moat_2015.json', 'out/retro_moat_2015q.json', 'out/retro_moat_2015qb.json']),
        ('2018', 'out/retro_returns_2018.json', 'irr18', 75,
         ['out/retro_moat_2018.json', 'out/retro_moat_2018_rest.json'])]


def http(url, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180)
            b = r.read()
            if r.headers.get('Content-Encoding') == 'gzip':
                b = gzip.decompress(b)
            return b
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1 + i)
        except Exception:
            time.sleep(1 + i)
    return None


def series(F, tags, deadline, instant):
    out, best = {}, {}
    for tg in tags:
        js = (F.get('us-gaap') or {}).get(tg)
        if not js:
            continue
        for un, arr in (js.get('units') or {}).items():
            if un != 'USD':
                continue
            for x in arr:
                f, e, s, fd = x.get('form', ''), x.get('end'), x.get('start'), x.get('filed', '')
                if not (f.startswith('10-K') or f.startswith('20-F')) or not e or fd > deadline:
                    continue
                if instant:
                    if s:
                        continue
                else:
                    if not s:
                        continue
                    m = (int(e[:4]) * 12 + int(e[5:7])) - (int(s[:4]) * 12 + int(s[5:7]))
                    if m < 11 or m > 13:
                        continue
                y = int(e[:4])
                if y not in best or fd > best[y]:
                    best[y], out[y] = fd, x['val']
        if out:
            break
    return out


def fin_at(cik, asof):
    dl = f'{asof}-07-01'
    j = http(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json')
    if not j:
        return {}
    try:
        F = json.loads(j).get('facts') or {}
    except Exception:
        return {}
    op = series(F, OP, dl, False)
    if not op:
        return {}
    y = max(op)
    lt = series(F, DEBT_LT, dl, True).get(y)
    cur = series(F, DEBT_C, dl, True).get(y, 0) or 0
    cash = series(F, CASH, dl, True).get(y)
    dep = series(F, DEP, dl, False).get(y, 0) or 0
    amo = series(F, AMO, dl, False).get(y, 0) or 0
    ie = series(F, INT, dl, False).get(y)
    eq = series(F, EQ, dl, True).get(y)
    r = {'fy': y, 'eqneg': (eq is not None and eq < 0)}
    ebitda = op[y] + dep + amo
    if lt is not None and cash is not None and ebitda and ebitda > 0:
        r['nde'] = (lt + cur - cash) / ebitda
    if ie and ie > 0:                 # 利息ゼロ・タグ無しは欠測（∞のもっともらしい代値を作らない）
        r['intcov'] = op[y] / ie
    return r


def stats(v):
    return dict(n=len(v), med=st.median(v), p15=sum(1 for x in v if x >= H) / len(v),
                ruin=sum(1 for x in v if x <= -0.15) / len(v), worst=min(v))


def show(title, groups):
    print(f'\n{title}')
    print(f"  {'':<26}{'n':>4}{'中央値':>9}{'年15%+':>8}{'恒久毀損':>9}{'最悪':>9}")
    for lab, v in groups:
        if not v:
            print(f'  {lab:<25}{0:>4}  （該当なし）')
            continue
        s = stats(v)
        print(f"  {lab:<25}{s['n']:>4}{s['med']*100:>8.1f}%{s['p15']:>8.2f}"
              f"{s['ruin']:>9.2f}{s['worst']*100:>8.1f}%")


def main():
    tk = http("https://www.sec.gov/files/company_tickers.json")
    T2C = {}
    for r in json.loads(tk).values():
        T2C.setdefault(str(r['ticker']).upper(), int(r['cik_str']))

    want = []
    for v, rp, key, line, moats in VINT:
        R = {r['ticker']: r['tr_cagr'] for r in json.load(open(rp, encoding='utf-8'))['rows']}
        seen = set()
        for mf in moats:
            if not os.path.exists(mf):
                continue
            for r in json.load(open(mf, encoding='utf-8'))['rows']:
                t = r.get('ticker') or r.get('t')
                g = r.get(key)
                if g is None or g < line or t in seen or t not in R or t not in T2C:
                    continue
                seen.add(t)
                want.append(dict(v=v, t=t, irr=g, tr=R[t]))
    if LIMIT:
        want = want[:LIMIT]
    print(f'■ 堀を通った群（irr≥70／2018年ビンテージは≥75）  のべ {len(want)}件', file=sys.stderr)

    cache = {}
    for i, w in enumerate(want, 1):
        k = (w['t'], w['v'])
        if k not in cache:
            cache[k] = fin_at(T2C[w['t']], int(w['v']))
            time.sleep(0.1)
        w.update(cache[k])
        if i % 30 == 0:
            print(f'  … {i}/{len(want)}', file=sys.stderr)

    nd = [w for w in want if w.get('nde') is not None]
    ic = [w for w in want if w.get('intcov') is not None]
    print(f'\n■ 堀を通った群 のべ {len(want)}件（nde が作れた {len(nd)} ／ intcov が作れた {len(ic)}）')
    print(f'   ハードル 年{H:.0%}／恒久毀損 = 年率≤−15%')
    s = stats([w['tr'] for w in want])
    print(f"   ベース: 中央値{s['med']*100:.1f}% ／ 年15%+ {s['p15']:.2f} ／ 恒久毀損 {s['ruin']:.2f}")

    show('■ 純有利子負債/EBITDA（門が殺す変数）',
         [(lab, [w['tr'] for w in nd if a < w['nde'] <= b]) for a, b, lab in
          [(-99, 0, 'nde≤0（純現金）'), (0, 2, '0〜2'), (2, 3, '2〜3'),
           (3, 4, '3〜4 ←門は通す'), (4, 5, '4〜5 ←門は殺す'), (5, 999, '5超 ←門は殺す')]])
    show('■ インタレストカバレッジ（門は使っていない）',
         [(lab, [w['tr'] for w in ic if a < w['intcov'] <= b]) for a, b, lab in
          [(-9e9, 1, 'intcov≤1'), (1, 3, '1〜3'), (3, 5, '3〜5'), (5, 10, '5〜10'),
           (10, 25, '10〜25'), (25, 9e9, '25超')]])

    print('\n■ 線で切ったとき——**止めた側の左尾**で裁く')
    print(f"  {'':<26}{'止めた':>7}{'中央値':>9}{'恒久毀損':>9}  ／{'通した':>7}{'中央値':>9}{'恒久毀損':>9}")
    for lab, pool, f in (('nde>4（現行のキル）', nd, lambda w: w['nde'] > 4),
                         ('nde>5', nd, lambda w: w['nde'] > 5),
                         ('intcov<5', ic, lambda w: w['intcov'] < 5),
                         ('intcov<3', ic, lambda w: w['intcov'] < 3),
                         ('intcov<1', ic, lambda w: w['intcov'] < 1)):
        g = [w['tr'] for w in pool if f(w)]
        o = [w['tr'] for w in pool if not f(w)]
        if not g or not o:
            print(f'  {lab:<25} 該当なし')
            continue
        a, b = stats(g), stats(o)
        print(f"  {lab:<25}{a['n']:>7}{a['med']*100:>8.1f}%{a['ruin']:>9.2f}  ／"
              f"{b['n']:>7}{b['med']*100:>8.1f}%{b['ruin']:>9.2f}")

    print('\n■ 参考: 堀を通らなかった群（irr≤50）と比べる——同じ線が外では効くのか')
    outr = []
    for v, rp, key, line, moats in VINT:
        R = {r['ticker']: r['tr_cagr'] for r in json.load(open(rp, encoding='utf-8'))['rows']}
        seen = set()
        for mf in moats:
            if not os.path.exists(mf):
                continue
            for r in json.load(open(mf, encoding='utf-8'))['rows']:
                t = r.get('ticker') or r.get('t')
                g = r.get(key)
                if g != 50 or t in seen or t not in R or t not in T2C:
                    continue
                seen.add(t)
                outr.append(dict(v=v, t=t, tr=R[t]))
    print(f'   （irr=50 は のべ {len(outr)}件——ここまで採るとSECの取得が数倍になるので、'
          f'今回は数だけ示して測っていない。必要なら --limit を外して別途）')

    if AS_JSON:
        p = 'out/retro_fin_gate_moat.json'
        json.dump({'generated': '2026-08-09', 'hurdle': H, 'rows': want},
                  open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
