#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/retro_nde_kill85.py — **財務キル(nde>4)は irr=85 の中で仕事をしていたか**を歴史で検定する
（2026-08-09新設・ユーザー指示「財務キルが irr85 の銘柄で必要だったのかを歴史的に検証して」）

【問いの立て方】門は irr=85 でも `純有利子負債/EBITDA > 4` を財務キルとして必ず適用する
  （v9.9.119 で別枠85を作ったとき、ユーザーの明示判断でこのキルだけは残した）。
  その根拠は「2018-2026 は**信用収縮がゼロの窓**なので、キルが守る事態がそもそも標本に無い」だった。
  ここで測るのは**その留保が正しいか**ではなく、**標本の中でキルが何をしたか**——
  (a)高レバの irr=85 は実際に劣後したか (b)キルは**何を止め**、その止めた社はどうなったか。

【遮断器の物差しで裁く】キルは選別器ではなく遮断器なので、通した側の平均ではなく
  **止めた側の左尾（恒久毀損 P(年率≤−15%)）**で見る（v9.9.98 で E[r] を外したときと同じ作法）。

【look-ahead を構造で防ぐ】レバレッジは**提出日 filed ≤ {asof}-07-01 の事実だけ**から作る。
  既存の out/retro_features_2018.json の nde18 はFY2018を無条件に採っており、
  12月決算社では2018-07時点で未公表＝数ヶ月の look-ahead が残る。ここでは使わない。
  式とタグは retro_features_2018.py と**同一**にする（基準の違う二つを作らないため）。

【限界（先に書く）】irr=85 は母集団の1〜3%しか出ない稀なラベルで、
  3ビンテージ合計でも のべ40件程度。**nde>4 の側は片手で数えられる**。
  この検定は「効果の有無を決める」のではなく「**標本の中で何が起きたか**」を出すだけ。

使い方: python3 night/retro_nde_kill85.py [--json] [--line 4.0]
出力: out/retro_nde_kill85.json
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
LINE = float(sys.argv[sys.argv.index('--line') + 1]) if '--line' in sys.argv else 4.0
H = 0.15

# retro_features_2018.py と同一のタグ（式も同一: (LT+Cur−Cash)/(OP+Dep+Amo)）
OP = ["OperatingIncomeLoss"]
DEBT_LT = ["LongTermDebtNoncurrent", "LongTermDebt", "DebtAndCapitalLeaseObligations",
           "LongTermDebtAndCapitalLeaseObligations"]
DEBT_C = ["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings",
          "LongTermDebtAndCapitalLeaseObligationsCurrent"]
CASH = ["CashAndCashEquivalentsAtCarryingValue"]
DEP = ["DepreciationDepletionAndAmortization", "Depreciation"]
AMO = ["AmortizationOfIntangibleAssets"]
EQ = ["StockholdersEquity"]

VINT = [('2013', 'out/retro_returns_2013_all.json', 13.09,
         ['out/retro_moat_2013.json', 'out/retro_moat_2013q.json']),
        ('2015', 'out/retro_returns_2015_q.json', 11.10,
         ['out/retro_moat_2015.json', 'out/retro_moat_2015q.json', 'out/retro_moat_2015qb.json']),
        ('2018', 'out/retro_returns_2018.json', 8.09,
         ['out/retro_moat_2018.json', 'out/retro_moat_2018_rest.json'])]


def http(url, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120)
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


def series(facts, tags, deadline, instant):
    """**提出日で切った**年次の系列 {会計年: 値}。同じ年は提出が新しいほうを採る。
    instant=True は残高（期末時点）、False はフロー（12ヶ月）。"""
    out, best = {}, {}
    for tg in tags:
        js = (facts.get('us-gaap') or {}).get(tg)
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
            break            # 候補は代替＝優先順の最上位が取れたら以降は見ない
    return out


def nde_at(cik, asof):
    """asof年7月1日までに提出済みの最新の年次から nde を作る（式は retro_features_2018 と同一）"""
    dl = f'{asof}-07-01'
    j = http(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json')
    if not j:
        return None, None, None
    try:
        F = json.loads(j).get('facts') or {}
    except Exception:
        return None, None, None
    op = series(F, OP, dl, False)
    if not op:
        return None, None, None
    y = max(op)
    lt = series(F, DEBT_LT, dl, True).get(y)
    cur = series(F, DEBT_C, dl, True).get(y, 0) or 0
    cash = series(F, CASH, dl, True).get(y)
    dep = series(F, DEP, dl, False).get(y, 0) or 0
    amo = series(F, AMO, dl, False).get(y, 0) or 0
    eq = series(F, EQ, dl, True).get(y)
    ebitda = op[y] + dep + amo
    if lt is None or cash is None or ebitda is None or ebitda <= 0:
        return None, y, (eq if eq is not None else None)
    return (lt + cur - cash) / ebitda, y, eq


def stats(v):
    return dict(n=len(v), med=st.median(v), p15=sum(1 for x in v if x >= H) / len(v),
                loss=sum(1 for x in v if x < 0) / len(v),
                ruin=sum(1 for x in v if x <= -0.15) / len(v), worst=min(v), best=max(v))


def main():
    tk = http("https://www.sec.gov/files/company_tickers.json")
    T2C = {}
    if tk:
        for r in json.loads(tk).values():
            T2C.setdefault(str(r['ticker']).upper(), int(r['cik_str']))

    rows = []
    for v, rp, yrs, moats in VINT:
        R = {r['ticker']: r['tr_cagr'] for r in
             json.load(open(rp, encoding='utf-8'))['rows']}
        for mf in moats:
            if not os.path.exists(mf):
                continue
            for r in json.load(open(mf, encoding='utf-8'))['rows']:
                t = r.get('ticker') or r.get('t')
                grade = r.get('irr', r.get('irr18'))
                if grade != 85 or t not in R or t not in T2C:
                    continue
                if any(x['v'] == v and x['t'] == t for x in rows):
                    continue                      # 同じビンテージの重複読解は1件に
                nd, fy, eq = nde_at(T2C[t], int(v))
                time.sleep(0.1)
                rows.append(dict(v=v, t=t, tr=R[t], years=yrs, nde=nd, fy=fy,
                                 eqneg=(eq is not None and eq < 0),
                                 mech=r.get('mech')))

    got = [r for r in rows if r['nde'] is not None]
    print(f'■ irr=85 の のべ {len(rows)}件（3ビンテージ）。うち **提出日で切った nde が作れたのは {len(got)}件**')
    print(f'   ハードル 年{H:.0%}／恒久毀損 = 年率≤−15%／キルの線 nde>{LINE}')

    print('\n■ 一覧（nde は **{年}-07-01 までに提出済み**の最新年次から）')
    print(f"  {'':<6}{'窓':<6}{'FY':>5}{'nde':>8}{'自己資本':>9}{'実現年率':>10}  機構")
    for r in sorted(rows, key=lambda z: (-(z['nde'] if z['nde'] is not None else -99), z['t'])):
        nd = f"{r['nde']:>7.2f}" if r['nde'] is not None else f"{'—':>8}"
        mark = ' ⛔キル' if (r['nde'] is not None and r['nde'] > LINE) else ''
        if r['eqneg']:
            mark += ' ⛔債務超過'
        print(f"  {r['t']:<6}{r['v']:<6}{str(r['fy'] or '—'):>5}{nd}"
              f"{('負' if r['eqneg'] else '正'):>9}{r['tr']*100:>9.1f}%  {r['mech'] or '—'}{mark}")

    print(f'\n■ 財務キル(nde>{LINE})で**止まる側**と**通る側**')
    hi = [r for r in got if r['nde'] > LINE]
    lo = [r for r in got if r['nde'] <= LINE]
    print(f"  {'':<22}{'n':>4}{'中央値':>9}{'年15%+':>8}{'元本割れ':>9}{'恒久毀損':>9}{'最悪':>9}{'最良':>9}")
    for lab, g in (('⛔止める（高レバ）', hi), ('✓通す', lo), ('全体', got)):
        if not g:
            print(f'  {lab:<21}{0:>4}  （該当なし）')
            continue
        s = stats([r['tr'] for r in g])
        print(f"  {lab:<21}{s['n']:>4}{s['med']*100:>8.1f}%{s['p15']:>8.2f}{s['loss']:>9.2f}"
              f"{s['ruin']:>9.2f}{s['worst']*100:>8.1f}%{s['best']*100:>8.1f}%")

    print('\n■ 帯別（線の位置を変えたらどうか）')
    bands = [(-99, 0, 'nde≤0（純現金）'), (0, 2, '0〜2'), (2, 3, '2〜3'), (3, 4, '3〜4'),
             (4, 5, '4〜5'), (5, 99, '5超')]
    for a, b, lab in bands:
        g = [r for r in got if a < r['nde'] <= b]
        if not g:
            continue
        s = stats([r['tr'] for r in g])
        who = ' '.join(f"{r['t']}({r['v']})" for r in sorted(g, key=lambda z: -z['tr']))
        print(f"  {lab:<16}{s['n']:>3}社 中央値{s['med']*100:>6.1f}% 15%+{s['p15']:>5.2f}"
              f" 毀損{s['ruin']:>5.2f}  {who}")

    print('\n■ 債務超過キルも併せて（門は eq<0 も1件のキルにする）')
    en = [r for r in rows if r['eqneg']]
    if en:
        s = stats([r['tr'] for r in en])
        print(f"  自己資本が負: {s['n']}社 中央値{s['med']*100:.1f}% 15%+{s['p15']:.2f} 毀損{s['ruin']:.2f}"
              f"  {' '.join(r['t']+'('+r['v']+')' for r in en)}")
    else:
        print('  該当なし')

    print('\n■ 二つのキルを合わせて「門が実際に止めたはずの社」')
    blocked = [r for r in rows if (r['nde'] is not None and r['nde'] > LINE) or r['eqneg']]
    passed = [r for r in rows if r not in blocked]
    for lab, g in (('⛔止めた', blocked), ('✓通した', passed)):
        if not g:
            continue
        s = stats([r['tr'] for r in g])
        print(f"  {lab}: {s['n']}社 中央値{s['med']*100:>6.1f}% 15%+{s['p15']:.2f}"
              f" 元本割れ{s['loss']:.2f} 毀損{s['ruin']:.2f} 最悪{s['worst']*100:.1f}%")
    if blocked:
        print('   止めた社の内訳: ' + ' / '.join(
            f"{r['t']}({r['v']}) {r['tr']*100:+.1f}%" for r in sorted(blocked, key=lambda z: -z['tr'])))

    if AS_JSON:
        p = 'out/retro_nde_kill85.json'
        json.dump({'generated': '2026-08-09', 'line': LINE, 'hurdle': H, 'rows': rows},
                  open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
