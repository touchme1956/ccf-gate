#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/retro_kills3_test.py — ROIIC³キルと sht(down/up) を歴史で検定する（2026-09-23新設・ユーザー指示「続きやって」）

**読むだけ。採点・規約・合否には一切触れない。**
事前登録は `out/retro_kills3_prereg.json`（**結果を見る前に**コミット 46aa6537 で固定）。
採用基準と結果の器は night/retro_cliffs_test.py と同一（stat/judge をそのまま使う）。

ROIIC: 採取器 hachimon_fetch の _nopat_ic/_roiic と同じ定義を、SEC companyfacts から**当時読めた数字**
  （filed ≤ fy_end+120日）で作る。系列の取り方は backtest_core の annual_rows / series_pick /
  series_total_or_sum をそのまま使う（再実装しない）。**負債タグ・税タグの無い年は算出不能**（0と読まない）。
  在庫は out/_cf_slim/（使うタグだけを抜いた小さなJSON・gitignore）。
sht: fill_sht.py と同じ式を、同じビンテージの retro_features2 の母集団で作る。

使い方: python3 night/retro_kills3_test.py [--json]
出力  : out/retro_kills3_test.json
"""
import datetime, json, os, statistics, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from retro_cliffs_test import rows, stat, judge, RET          # 同じ器
import backtest_core as BC                                    # 同じ系列の取り方

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HDRS = {"User-Agent": "hachimon-gate fortis5280@gmail.com"}
SLIM = os.path.join(ROOT, 'out', '_cf_slim')
PRIMARY = [2013, 2015, 2018]
WACC = 9.0
TAGS = sorted({'OperatingIncomeLoss', 'NetIncomeLoss', 'ProfitLoss', 'IncomeTaxExpenseBenefit',
               'StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest',
               'Assets', *BC.DEBT_TOTAL, *BC.DEBT_PARTS})


def facts(cik):
    os.makedirs(SLIM, exist_ok=True)
    p = os.path.join(SLIM, '%010d.json' % cik)
    if os.path.exists(p):
        return json.load(open(p))
    u = 'https://data.sec.gov/api/xbrl/companyfacts/CIK%010d.json' % cik
    j = None
    for i in range(4):
        try:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=HDRS), timeout=120).read())
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                j = {}
                break
            time.sleep(2 ** i)
        except Exception:
            time.sleep(2 ** i)
    time.sleep(0.13)                                   # 10req/s を守る
    if j is None:
        return None                                    # 取れなかった＝保存しない（次回また取りに行く）
    g = (j.get('facts') or {}).get('us-gaap') or {}
    slim = {'facts': {'us-gaap': {t: g[t] for t in TAGS if t in g}}}
    json.dump(slim, open(p, 'w'))
    return slim


def roiic_at(f, fy, fy_end):
    """hachimon_fetch._roiic と同じ定義。戻り (r3, r5)。値 / 'na' / None(算出不能)"""
    e = datetime.date.fromisoformat(fy_end) + datetime.timedelta(days=120)
    cut = e.isoformat()
    op = BC.series_pick(f, ['OperatingIncomeLoss'], cut)
    ni = BC.series_pick(f, ['NetIncomeLoss', 'ProfitLoss'], cut)
    tax = BC.series_pick(f, ['IncomeTaxExpenseBenefit'], cut)
    eq = BC.series_pick(f, ['StockholdersEquity',
                            'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'], cut)
    ast = BC.series_pick(f, ['Assets'], cut)
    debt = BC.series_total_or_sum(f, BC.DEBT_TOTAL, BC.DEBT_PARTS, cut)
    if not op:
        return None, None
    y1 = max(op)
    if y1 < int(fy) - 1:
        return None, None                              # 当時点で古いデータしか無い

    def nic(y):
        if y not in op or y not in ni or y not in eq or y not in debt or y not in tax:
            return None                                # タグ不在を0と読まない
        tr = 1 - ni[y] / max(ni[y] + tax[y], 1)
        np_ = op[y] * (1 - max(0, min(0.5, tr)))
        icg = eq[y] + debt[y]
        b = eq[y] if eq[y] > 0 else (ast.get(y) or 0)
        if icg <= 0 or (b > 0 and icg < 0.20 * b):
            return None
        return np_, icg

    def win(w):
        cand = [y for y in op if y <= y1 - w]
        if not cand:
            return None
        a, b = nic(max(cand)), nic(y1)
        if not a or not b:
            return None
        dn, dic = b[0] - a[0], b[1] - a[1]
        if dic <= 0 or dic < 0.10 * a[1]:
            return 'na'
        v = dn / dic * 100
        return 'na' if abs(v) > 150 else round(v, 1)

    r3, r5 = win(3), win(5)
    if isinstance(r3, float) and r3 < 15 and not isinstance(r5, float):
        r3 = 'na'
    return r3, r5


def sht_of(pool, sic):
    """fill_sht.py と同じ式。{ticker: 'down'/'flat'/'up'}"""
    uni = []
    for f in pool:
        c = f.get('cagr5'); s = (sic.get(f['ticker']) or {}).get('sic')
        if c is None or not s:
            continue
        g = c * 100 if -2.0 < c < 3.0 else c
        if -50 < g < 200:
            uni.append((f['ticker'], str(s), g))
    by4, by3 = {}, {}
    for t, s, g in uni:
        by4.setdefault(s, []).append(g); by3.setdefault(s[:3], []).append(g)
    out = {}
    for t, s, g in uni:
        grp = by4.get(s, [])
        if len(grp) < 8:
            grp = by3.get(s[:3], [])
        if len(grp) < 8:
            continue
        med = statistics.median(grp)
        r = ((1 + g / 100) / (1 + med / 100)) ** 5 - 1
        out[t] = 'down' if r <= -0.20 else 'up' if r >= 0.25 else 'flat'
    return out


def main():
    cikmap = json.load(open(os.path.join(ROOT, 'out/_cik_tickers.json')))
    sic = json.load(open(os.path.join(ROOT, 'out/_sic_cache.json')))
    for t, v in sic.items():
        if v.get('cik') and t not in cikmap:
            cikmap[t] = int(v['cik'])

    out = {'generated': datetime.date.today().isoformat(), 'prereg': 'out/retro_kills3_prereg.json',
           'wacc': WACC, 'coverage': {}, 'blocks': {}}
    rec = {}
    for y in PRIMARY:
        F = rows('retro_features2_%d.json' % y)
        R = {r['ticker']: r for r in rows(RET[y]) if not r.get('stale') and r.get('tr_cagr') is not None}
        pool = [f for f in F if f['ticker'] in R]
        sh = sht_of(F, sic)                            # 同業は母集団全体（リターンの有無と無関係）
        rs, n_done = [], 0
        for f in pool:
            t = f['ticker']
            x = {'t': t, 'cagr': R[t]['tr_cagr'], 'sht': sh.get(t), 'r3': None, 'r5': None}
            if t in cikmap and f.get('fy_end') and f.get('fy'):
                fc = facts(int(cikmap[t]))
                if fc:
                    x['r3'], x['r5'] = roiic_at(fc, f['fy'], f['fy_end'])
            rs.append(x)
            n_done += 1
            if n_done % 100 == 0:
                print('  %d: %d/%d' % (y, n_done, len(pool)), flush=True)
        rec[y] = rs
        num = lambda v: isinstance(v, float)
        out['coverage'][y] = {'n': len(rs), 'roiic3_num': sum(num(r['r3']) for r in rs),
                              'roiic3_na': sum(r['r3'] == 'na' for r in rs),
                              'sht': {k: sum(r['sht'] == k for r in rs) for k in ('down', 'flat', 'up')}}

    def block(title, split):
        blk, ok = {'title': title}, []
        for y in PRIMARY:
            bad, good = split(rec[y])
            a, b = stat(bad), stat(good)
            if not a or not b or a['n'] < 20 or b['n'] < 20:
                blk[y] = {'skipped': '群が薄い（<20社）', 'n_stopped': len(bad), 'n_passed': len(good)}
                continue
            blk[y] = judge(a, b)
            ok.append(blk[y]['median_lower'] and blk[y]['damage_denser'])
        blk['verdict'] = 'PASS' if (ok and all(ok)) else ('FAIL' if ok else 'UNTESTABLE')
        return blk

    num = lambda v: isinstance(v, float)
    out['blocks']['E_roiic_kill'] = block('E ROIIC³<WACC → キル（救済なし）', lambda rs: (
        [r for r in rs if num(r['r3']) and r['r3'] < WACC and num(r['r5']) and r['r5'] < WACC],
        [r for r in rs if num(r['r3']) and r['r3'] >= WACC]))
    out['blocks']['F_sht_down'] = block('F sht=down → pm −10（vs flat）', lambda rs: (
        [r for r in rs if r['sht'] == 'down'], [r for r in rs if r['sht'] == 'flat']))
    out['blocks']['G_sht_up'] = block('G sht=up → pm +3（flat を止めた側に置く）', lambda rs: (
        [r for r in rs if r['sht'] == 'flat'], [r for r in rs if r['sht'] == 'up']))

    p = os.path.join(ROOT, 'out/retro_kills3_test.json')
    json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    if '--json' in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str)); return
    print('\n■ 被覆: ' + json.dumps(out['coverage'], ensure_ascii=False))
    for k, blk in out['blocks'].items():
        print('\n%s   判定: **%s**' % (blk['title'], blk['verdict']))
        for y in PRIMARY:
            r = blk[y]
            if 'skipped' in r:
                print('  %d %s（止 %d / 通 %d）' % (y, r['skipped'], r['n_stopped'], r['n_passed'])); continue
            a, b = r['stopped'], r['passed']
            print('  %d 止 %d / %s%% / 毀損%s   通 %d / %s%% / 毀損%s   %s' % (
                y, a['n'], a['med'], a['dmg'], b['n'], b['med'], b['dmg'],
                '✓' if (r['median_lower'] and r['damage_denser']) else '✗'))
    print('\n※ 事前登録 out/retro_kills3_prereg.json（コミット 46aa6537・測定の前）。この道具は読むだけ。')


if __name__ == '__main__':
    main()
