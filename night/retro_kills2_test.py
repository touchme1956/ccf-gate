#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/retro_kills2_test.py — 未検定の崖4本を歴史で検定する（2026-09-23新設・ユーザー指示「つづきやって」）
  A `GP/A<15 → −5` ／ B `債務超過 → キル` ／ C `Z''<1.1 → キル` ／ D `1.1≤Z''<2.6 → −6`

**読むだけ。採点・規約・合否には一切触れない。**
事前登録は `out/retro_kills2_prereg.json`（**結果を見る前に**コミット 8d260d9a で固定）。
採用基準と結果の器は night/retro_cliffs_test.py と同一（stat/judge をそのまま使う＝基準の違う二つを作らない）。

採取: SEC XBRL frames（companyfacts.zip を落とさない・retro_gwg_vintages.py と同じ作法）。
  瞬時値は CY{y}Q{q}I を年4本、各社の fy_end±45日で拾う。営業利益は CY{y}（年次の期間値）を end±45日で拾う。
  **タグが無い社は 0 と読まずに群から外す**（絶対のルール7）。在庫は out/_frames_cache/ に置く（gitignore）。

使い方: python3 night/retro_kills2_test.py [--json]
出力  : out/retro_kills2_test.json
"""
import datetime, json, os, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from retro_cliffs_test import rows, stat, judge, RET  # 同じ器

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HDRS = {"User-Agent": "hachimon-gate fortis5280@gmail.com"}
WIN = 45
CACHE = os.path.join(ROOT, 'out', '_frames_cache')
PRIMARY = [2013, 2015, 2018]
SUPP_GPA = [2016, 2017, 2019, 2020, 2021]
INSTANT = ['Assets', 'AssetsCurrent', 'LiabilitiesCurrent', 'Liabilities', 'RetainedEarningsAccumulatedDeficit',
           'StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest']
DURATION = ['OperatingIncomeLoss']


def d2(s):
    return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def frame(tag, period):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, '%s_%s.json' % (tag, period))
    if os.path.exists(p):
        return json.load(open(p))
    u = 'https://data.sec.gov/api/xbrl/frames/us-gaap/%s/USD/%s.json' % (tag, period)
    for i in range(4):
        try:
            r = urllib.request.urlopen(urllib.request.Request(u, headers=HDRS), timeout=120)
            data = json.loads(r.read()).get('data', [])
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:           # その期のフレームが存在しない＝空（0ではない）
                data = []
                break
            if i == 3:
                raise
            time.sleep(2 ** i)
        except Exception:
            if i == 3:
                raise
            time.sleep(2 ** i)
    json.dump(data, open(p, 'w'))
    time.sleep(0.15)
    return data


def build_lookup(years):
    """{tag: {cik: [(end_date, val)]}}"""
    L = {}
    for tag in INSTANT:
        m = L.setdefault(tag, {})
        for y in years:
            for q in (1, 2, 3, 4):
                for e in frame(tag, 'CY%dQ%dI' % (y, q)):
                    m.setdefault(e['cik'], []).append((d2(e['end']), e['val']))
        print('  %-72s 社数 %d' % (tag, len(m)))
    for tag in DURATION:
        m = L.setdefault(tag, {})
        for y in years:
            for e in frame(tag, 'CY%d' % y):
                m.setdefault(e['cik'], []).append((d2(e['end']), e['val']))
        print('  %-72s 社数 %d' % (tag, len(m)))
    return L


def at(L, tag, cik, fe):
    best = None
    for d, v in L[tag].get(cik, []):
        dd = abs((d - fe).days)
        if dd <= WIN and (best is None or dd < best[0]):
            best = (dd, v)
    return best[1] if best else None


def fundamentals(L, cik, fe):
    A = at(L, 'Assets', cik, fe)
    eq = at(L, 'StockholdersEquity', cik, fe)
    if eq is None:
        eq = at(L, 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest', cik, fe)
    eqn = at(L, 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest', cik, fe)
    tl = at(L, 'Liabilities', cik, fe)
    if tl is None and A is not None and (eqn if eqn is not None else eq) is not None:
        tl = A - (eqn if eqn is not None else eq)
    ca, cl = at(L, 'AssetsCurrent', cik, fe), at(L, 'LiabilitiesCurrent', cik, fe)
    re_, ebit = at(L, 'RetainedEarningsAccumulatedDeficit', cik, fe), at(L, 'OperatingIncomeLoss', cik, fe)
    z = None
    if None not in (A, ca, cl, re_, ebit, eq, tl) and A > 0 and tl > 0:
        z = 6.56 * (ca - cl) / A + 3.26 * re_ / A + 6.72 * ebit / A + 1.05 * eq / tl
    return {'eq': eq, 'z': z}


def main():
    cikmap = json.load(open(os.path.join(ROOT, 'out/_cik_tickers.json')))
    sic = json.load(open(os.path.join(ROOT, 'out/_sic_cache.json')))
    for t, v in sic.items():                     # 退場した社の CIK も拾う（現行の対応表に無い）
        if v.get('cik') and t not in cikmap:
            cikmap[t] = int(v['cik'])

    def load(y):
        F = rows('retro_features2_%d.json' % y)
        R = {r['ticker']: r for r in rows(RET[y]) if not r.get('stale') and r.get('tr_cagr') is not None}
        return [(f, R[f['ticker']]['tr_cagr']) for f in F if f['ticker'] in R]

    data = {y: load(y) for y in PRIMARY + SUPP_GPA}
    fys = sorted({int(f['fy']) for y in PRIMARY for f, _ in data[y] if f.get('fy')})
    print('■ SEC frames を取得（暦年 %s）' % fys)
    L = build_lookup(fys)

    out = {'generated': datetime.date.today().isoformat(), 'prereg': 'out/retro_kills2_prereg.json',
           'coverage': {}, 'blocks': {}}
    rec = {}
    for y in PRIMARY:
        rs, nz, ne = [], 0, 0
        for f, c in data[y]:
            t = f['ticker']
            x = {'t': t, 'cagr': c, 'gpa': None, 'eq': None, 'z': None}
            gm, at_ = f.get('gm'), f.get('aturn')
            if gm is not None and at_ is not None:
                g = gm if gm <= 1.5 else gm / 100.0
                x['gpa'] = g * at_ * 100
            if t in cikmap and f.get('fy_end'):
                fu = fundamentals(L, int(cikmap[t]), d2(f['fy_end']))
                x.update(fu)
            nz += x['z'] is not None
            ne += x['eq'] is not None
            rs.append(x)
        rec[y] = rs
        out['coverage'][y] = {'n': len(rs), 'z': nz, 'eq': ne,
                              'gpa': sum(1 for r in rs if r['gpa'] is not None)}
    for y in SUPP_GPA:
        rs = []
        for f, c in data[y]:
            gm, at_ = f.get('gm'), f.get('aturn')
            if gm is not None and at_ is not None:
                g = gm if gm <= 1.5 else gm / 100.0
                rs.append({'t': f['ticker'], 'cagr': c, 'gpa': g * at_ * 100})
        rec[y] = rs

    def block(title, years, split, primary=True):
        blk, ok = {'title': title}, []
        for y in years:
            bad, good = split(rec[y])
            a, b = stat(bad), stat(good)
            if not a or not b or a['n'] < 20 or b['n'] < 20:
                blk[y] = {'skipped': '群が薄い（<20社）', 'n_stopped': len(bad), 'n_passed': len(good)}
                continue
            blk[y] = judge(a, b)
            ok.append(blk[y]['median_lower'] and blk[y]['damage_denser'])
        if primary:
            blk['verdict'] = 'PASS' if (ok and all(ok)) else ('FAIL' if ok else 'UNTESTABLE')
        else:
            blk['verdict'] = '補助（採否に使わない）: %d/%d 年で両方向' % (sum(ok), len(ok))
        return blk

    has = lambda k: (lambda rs: [r for r in rs if r.get(k) is not None])
    out['blocks']['A_gpa15'] = block('A GP/A<15 → −5', PRIMARY,
        lambda rs: ([r for r in has('gpa')(rs) if r['gpa'] < 15], [r for r in has('gpa')(rs) if r['gpa'] >= 15]))
    out['blocks']['A_gpa15_supp'] = block('A- 同じ線を補助ビンテージへ', SUPP_GPA,
        lambda rs: ([r for r in has('gpa')(rs) if r['gpa'] < 15], [r for r in has('gpa')(rs) if r['gpa'] >= 15]), False)
    out['blocks']['B_eqneg'] = block('B 債務超過（自己資本<0）→ キル', PRIMARY,
        lambda rs: ([r for r in has('eq')(rs) if r['eq'] < 0], [r for r in has('eq')(rs) if r['eq'] >= 0]))
    out['blocks']['C_z_distress'] = block("C Z''<1.1 → キル（vs Z''≥2.6）", PRIMARY,
        lambda rs: ([r for r in has('z')(rs) if r['z'] < 1.1], [r for r in has('z')(rs) if r['z'] >= 2.6]))
    out['blocks']['D_z_grey'] = block("D 1.1≤Z''<2.6 → −6（vs Z''≥2.6）", PRIMARY,
        lambda rs: ([r for r in has('z')(rs) if 1.1 <= r['z'] < 2.6], [r for r in has('z')(rs) if r['z'] >= 2.6]))

    p = os.path.join(ROOT, 'out/retro_kills2_test.json')
    json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    if '--json' in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str)); return
    print('\n■ 被覆（主ビンテージ）: ' + '  '.join('%d: 全%d／GP/A %d／自己資本 %d／Z\'\' %d' % (
        y, c['n'], c['gpa'], c['eq'], c['z']) for y, c in out['coverage'].items()))
    for k, blk in out['blocks'].items():
        print('\n%s   判定: **%s**' % (blk['title'], blk['verdict']))
        print('  %-6s%-30s%-30s%8s' % ('年', '止めた側 n/中央値/毀損', '通した側 n/中央値/毀損', '両方向'))
        for y in sorted(x for x in blk if isinstance(x, int)):
            r = blk[y]
            if 'skipped' in r:
                print('  %-6s%s（止 %d / 通 %d）' % (y, r['skipped'], r['n_stopped'], r['n_passed'])); continue
            a, b = r['stopped'], r['passed']
            print('  %-6s%-30s%-30s%8s' % (y, '{} / {}% / {}'.format(a['n'], a['med'], a['dmg']),
                  '{} / {}% / {}'.format(b['n'], b['med'], b['dmg']),
                  '✓' if (r['median_lower'] and r['damage_denser']) else '✗'))
    print('\n※ 事前登録 out/retro_kills2_prereg.json（コミット 8d260d9a・測定の前）。この道具は読むだけ。')


if __name__ == '__main__':
    main()
