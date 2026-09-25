#!/usr/bin/env python3
"""night/moat_dr.py — 事前登録 out/moat_dr_prereg.json（前受収益の倍率）を採取して、書いてあるとおりに裁く

採取は retro_features2 の関数（期限・年次・インスタント照合）を、株価と検定は combo_spy の関数をそのまま使う。
使い方: python3 night/moat_dr.py   出力: out/moat_dr.json
"""
import json, os, random, statistics, sys, zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'out')
sys.path.insert(0, os.path.join(BASE, 'night'))
import retro_features2 as rf
import combo_spy as cs

PRE = json.load(open(os.path.join(OUT, 'moat_dr_prereg.json')))
ANCH = [int(a[:4]) for a in PRE['anchors']]
TOTALS = PRE['definition']['totals_first']
PARTS = [('ContractWithCustomerLiabilityCurrent', 'ContractWithCustomerLiabilityNoncurrent'),
         ('DeferredRevenueCurrent', 'DeferredRevenueNoncurrent')]
B, SEED, ALPHA, MIN_N, TOP1 = PRE['null']['B'], PRE['null']['seed'], 0.01, 20, 0.5

def dr_value(g, dl, fe):
    for tag in TOTALS:
        v = rf.inst_at(g, [tag], dl, fe)
        if v is not None: return v, tag
    for cur, non in PARTS:  # 構成要素＝和（代替ではない）
        c = rf.inst_at(g, [cur], dl, fe)
        if c is not None:
            n = rf.inst_at(g, [non], dl, fe)
            return c + (n or 0), cur + ('+' + non if n is not None else '')
    return None, None

def collect():
    tick = [r['ticker'] for r in json.load(open(os.path.join(OUT, 'retro_features2_2018.json')))['rows']]
    cik = json.load(open(os.path.join(OUT, '_cik_tickers.json')))
    for f in ('retro_cohort_2015.json', 'retro_cohort_2013.json'):
        for r in json.load(open(os.path.join(OUT, f)))['rows']:
            if r.get('ticker') and r.get('cik') and r['ticker'] not in cik: cik[r['ticker']] = r['cik']
    z = zipfile.ZipFile(os.path.join(BASE, 'companyfacts.zip')); have = set(z.namelist())
    rows = {}
    for t in tick:
        c = cik.get(t); nm = f'CIK{int(c):010d}.json' if c else None
        if not nm or nm not in have: continue
        g = json.loads(z.read(nm)).get('facts', {}).get('us-gaap', {})
        rec = {}
        for Y in ANCH:
            dl = f'{Y}-07-01'
            rev_get, maps = rf.flow_maps(g, rf.REV, dl, mode='max')
            ends = [v[2] for m in maps for v in m.values()]
            if not ends: continue
            fe = max(ends, key=rf.d2); a = int(fe[:4]); rev = rev_get(a)
            v, tag = dr_value(g, dl, fe)
            if v is not None and rev and rev > 0 and v >= 0:
                rec[str(Y)] = dict(dr_r=round(v / rev, 4), tag=tag, fy_end=fe)
        rows[t] = rec
    return rows

def ew(ts, M, m): return cs.cagr(sum(M[t] for t in ts) / len(ts), m) if ts else None

def main():
    rows = collect()
    pan = cs.panel(); spy = {int(k): v for k, v in json.load(open(os.path.join(OUT, '_spy_monthly.json'))).items()}
    END = max(spy); SEMI = cs.semi_set(); uni = sorted(pan)
    sic = {r['ticker']: (r.get('sic') or '')[:2] for r in json.load(open(os.path.join(OUT, 'retro_sic.json')))['rows']}
    obs, anchors = [], {}
    for Y in ANCH:
        k0 = Y * 12 + 6; m = END - k0
        v = {t: r[str(Y)]['dr_r'] for t, r in rows.items() if str(Y) in r and t in pan and k0 in pan[t] and END in pan[t]}
        if len(v) < 8: anchors[Y] = dict(pool=len(v), note='開示社が少なすぎる'); continue
        th = sorted(v.values())[int(round(.75 * (len(v) - 1)))]
        M = {t: pan[t][END] / pan[t][k0] for t in uni if k0 in pan[t] and END in pan[t]}
        g = [t for t in v if v[t] >= th]; r = [t for t in v if v[t] < th]
        d = ew(g, M, m) - ew(r, M, m)
        gains = sorted(((M[t] - 1, t) for t in g), reverse=True); pos = sum(x for x, _ in gains if x > 0)
        g1 = [t for t in g if t != gains[0][1]]
        gs = [t for t in g if t not in SEMI]; rs = [t for t in r if t not in SEMI]
        # 業種調整（報告だけ）: 各社のCAGRから同じSIC2の開示社の中央値を引いた残差の平均の差
        byind = {}
        for t in v: byind.setdefault(sic.get(t, '?'), []).append(cs.cagr(M[t], m))
        res = lambda ts: statistics.mean(cs.cagr(M[t], m) - statistics.median(byind[sic.get(t, '?')]) for t in ts)
        spyc = cs.cagr(spy[END] / spy[k0], m)
        anchors[Y] = dict(pool=len(v), n=len(g), line=round(th, 4), months=m, diff=round(d, 4),
                          grp_cagr=round(ew(g, M, m), 4), rest_cagr=round(ew(r, M, m), 4), vs_spy=round(ew(g, M, m) - spyc, 4),
                          lift15=round(sum(cs.cagr(M[t], m) >= .15 for t in g) / len(g) - sum(cs.cagr(M[t], m) >= .15 for t in r) / len(r), 3),
                          tail15=round(sum(cs.cagr(M[t], m) <= -.15 for t in g) / len(g) - sum(cs.cagr(M[t], m) <= -.15 for t in r) / len(r), 3),
                          top1=gains[0][1], top1_share=round(gains[0][0] / pos, 3) if pos > 0 else None,
                          diff_wo_top1=round(ew(g1, M, m) - ew(r, M, m), 4),
                          diff_wo_semi=round(ew(gs, M, m) - ew(rs, M, m), 4),
                          diff_industry_adj=round(res(g) - res(r), 4))
        obs.append((Y, g, r, M, m, d))
    stat = statistics.mean(d for *_, d in obs)
    rng = random.Random(SEED); ge = 0
    for _ in range(B):
        s = uni[:]; rng.shuffle(s); pm = dict(zip(uni, s)); ds = []
        for Y, g, r, M, m, d in obs:
            ds.append(ew([pm[t] for t in g if pm[t] in M], M, m) - ew([pm[t] for t in r if pm[t] in M], M, m))
        if statistics.mean(ds) >= stat: ge += 1
    p = (ge + 1) / (B + 1)
    crit = {'1_全アンカーで差>0': all(d > 0 for *_, d in obs), '2_置換p<0.01': p < ALPHA,
            '3_全アンカーでn>=20': all(anchors[Y]['n'] >= MIN_N for Y, *_ in obs),
            '4_上位1社<50%': all((anchors[Y]['top1_share'] or 0) < TOP1 for Y, *_ in obs)}
    out = dict(generated=__import__('datetime').date.today().isoformat(), tool='night/moat_dr.py', prereg='out/moat_dr_prereg.json',
               mean_diff=round(stat, 4), p=round(p, 4), criteria=crit, verdict='合格' if all(crit.values()) else '不合格',
               anchors=anchors, coverage={str(Y): sum(str(Y) in r for r in rows.values()) for Y in ANCH},
               values={t: r for t, r in rows.items() if r})
    json.dump(out, open(os.path.join(OUT, 'moat_dr.json'), 'w'), ensure_ascii=False, indent=1)
    print(f"判定 {out['verdict']}  平均差 {stat:+.4f}  p {p:.4f}  {crit}")
    print('開示社数', out['coverage'])
    for Y, a in anchors.items(): print(Y, a)

if __name__ == '__main__':
    main()
