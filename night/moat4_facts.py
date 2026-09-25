#!/usr/bin/env python3
"""night/moat4_facts.py — 事前登録 out/moat4_prereg.json の C1（受注残の倍率）と C2（粗利率の安定性）の採取

companyfacts.zip から、各アンカー年-07-01 までに提出されたエントリだけを使う。
期限・年次の判定・インスタント照合は retro_features2.py の関数をそのまま使う（再実装しない）。

使い方: python3 night/moat4_facts.py   出力: out/moat4_facts.json
"""
import json, os, statistics, sys, zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'out')
sys.path.insert(0, os.path.join(BASE, 'night'))
import retro_features2 as rf

RPO = ['RevenueRemainingPerformanceObligation']
C1_ANCHORS = [2019, 2020, 2021]
C2_ANCHORS = [2013, 2016, 2017, 2018]

def anchor(g, dl):
    rev_get, maps = rf.flow_maps(g, rf.REV, dl, mode='max')
    ends = [v[2] for m in maps for v in m.values()]
    if not ends: return None, None, rev_get
    fy_end = max(ends, key=rf.d2)
    return int(fy_end[:4]), fy_end, rev_get

def gm_series(g, dl, years, rev_get):
    gp_get, _ = rf.flow_maps(g, rf.GP, dl)
    ct_get, _ = rf.flow_maps(g, rf.COGS_TOTAL, dl)
    out = {}
    for y in years:
        r = rev_get(y)
        if not r or r <= 0: continue
        gp = gp_get(y)
        if gp is None:
            ct = ct_get(y)
            if ct is None: continue
            gp = r - ct
        v = gp / r
        if -1 <= v <= 1: out[y] = v
    return out

def main():
    tick = [r['ticker'] for r in json.load(open(os.path.join(OUT, 'retro_features2_2018.json')))['rows']]
    cik = json.load(open(os.path.join(OUT, '_cik_tickers.json')))
    for f in ('retro_cohort_2015.json', 'retro_cohort_2013.json'):
        for r in json.load(open(os.path.join(OUT, f)))['rows']:
            if r.get('ticker') and r.get('cik') and r['ticker'] not in cik: cik[r['ticker']] = r['cik']
    z = zipfile.ZipFile(os.path.join(BASE, 'companyfacts.zip')); have = set(z.namelist())
    rows, miss = {}, []
    for t in tick:
        c = cik.get(t); nm = f'CIK{int(c):010d}.json' if c else None
        if not nm or nm not in have: miss.append(t); continue
        g = json.loads(z.read(nm)).get('facts', {}).get('us-gaap', {})
        rec = {}
        for Y in C1_ANCHORS:
            dl = f'{Y}-07-01'; a, fe, rev_get = anchor(g, dl)
            if a is None: continue
            rpo = rf.inst_at(g, RPO, dl, fe); rev = rev_get(a)
            if rpo is not None and rev and rev > 0:
                rec[f'rpo_{Y}'] = round(rpo / rev, 4)
        for Y in C2_ANCHORS:
            dl = f'{Y}-07-01'; a, fe, rev_get = anchor(g, dl)
            if a is None: continue
            s = gm_series(g, dl, range(a - 9, a + 1), rev_get)
            if a in s: rec[f'gm_{Y}'] = round(s[a], 4)
            if len(s) >= 8:
                rec[f'gmsd_{Y}'] = round(statistics.pstdev(s.values()), 4); rec[f'gmn_{Y}'] = len(s)
        rows[t] = rec
    json.dump(dict(generated=__import__('datetime').date.today().isoformat(), tool='night/moat4_facts.py',
                   prereg='out/moat4_prereg.json', missing_facts=miss, rows=rows),
              open(os.path.join(OUT, 'moat4_facts.json'), 'w'), ensure_ascii=False)
    for k in [f'rpo_{Y}' for Y in C1_ANCHORS] + [f'gmsd_{Y}' for Y in C2_ANCHORS]:
        print(k, sum(k in r for r in rows.values()), '社')
    print('facts無し', len(miss))

if __name__ == '__main__':
    main()
