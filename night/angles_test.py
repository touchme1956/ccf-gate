#!/usr/bin/env python3
"""night/angles_test.py — out/angles4_prereg.json を書いてあるとおりに裁く（線は動かさない）

B1 内部者の買い（out/angles_insider.json）・B2 機関の注目度（out/angles_13f.json）・
A1/A2 再投資の余地と資本配分（out/angles_read.json・読解が済んでいれば）。
株価は combo_spy.panel をそのまま使う。出力 out/angles_test.json
"""
import json, math, os, random, statistics, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'out')
sys.path.insert(0, os.path.join(BASE, 'night'))
import combo_spy as cs

B, SEED, ALPHA, MIN_N, TOP1 = 2000, 20260927, 0.0125, 20, 0.5
L = lambda p: json.load(open(os.path.join(OUT, p)))

def ew(ts, M, m): return cs.cagr(sum(M[t] for t in ts) / len(ts), m) if ts else None

def judge(name, anchors, pan, END, spy, SEMI, halves=False):
    """anchors: {label: (k0, pool:set, group:set, note)}。halves=True は1アンカー用（前半・後半も見る）"""
    uni = sorted(pan); rows, obs = {}, []
    for lab, (k0, pool, grp, note) in anchors.items():
        m = END - k0
        M = {t: pan[t][END] / pan[t][k0] for t in uni if k0 in pan[t] and END in pan[t]}
        P = [t for t in pool if t in M]; g = [t for t in P if t in grp]; r = [t for t in P if t not in grp]
        row = dict(note=note, pool=len(P), n=len(g), months=m)
        if g and r:
            d = ew(g, M, m) - ew(r, M, m)
            gains = sorted(((M[t] - 1, t) for t in g), reverse=True); pos = sum(x for x, _ in gains if x > 0)
            spyc = cs.cagr(spy[END] / spy[k0], m); g1 = [t for t in g if t != gains[0][1]]
            gs = [t for t in g if t not in SEMI]; rs = [t for t in r if t not in SEMI]
            row.update(diff=round(d, 4), grp_cagr=round(ew(g, M, m), 4), rest_cagr=round(ew(r, M, m), 4),
                       vs_spy=round(ew(g, M, m) - spyc, 4),
                       lift15=round(sum(cs.cagr(M[t], m) >= .15 for t in g) / len(g) - sum(cs.cagr(M[t], m) >= .15 for t in r) / len(r), 3),
                       tail15=round(sum(cs.cagr(M[t], m) <= -.15 for t in g) / len(g) - sum(cs.cagr(M[t], m) <= -.15 for t in r) / len(r), 3),
                       top1=gains[0][1], top1_share=round(gains[0][0] / pos, 3) if pos > 0 else None,
                       diff_wo_top1=round(ew(g1, M, m) - ew(r, M, m), 4) if g1 else None,
                       diff_wo_semi=round(ew(gs, M, m) - ew(rs, M, m), 4) if gs and rs else None)
            if halves:
                mid = 2020 * 12  # 2020-01
                for hl, a0, a1 in (('前半', k0, mid - 1), ('後半', mid, END)):
                    Mh = {t: pan[t][a1] / pan[t][a0] for t in P if a0 in pan[t] and a1 in pan[t]}
                    gh = [t for t in g if t in Mh]; rh = [t for t in r if t in Mh]
                    row[f'diff_{hl}'] = round(ew(gh, Mh, a1 - a0) - ew(rh, Mh, a1 - a0), 4) if gh and rh else None
            obs.append((g, r, M, m, d))
        rows[lab] = row
    if not obs: return dict(anchors=rows, verdict='検定不能', why='評価できるアンカーが無い')
    stat = statistics.mean(o[-1] for o in obs)
    rng = random.Random(SEED); ge = 0
    for _ in range(B):
        s = uni[:]; rng.shuffle(s); pm = dict(zip(uni, s)); ds = []
        for g, r, M, m, d in obs:
            gg = [pm[t] for t in g if pm[t] in M]; rr = [pm[t] for t in r if pm[t] in M]
            ds.append(ew(gg, M, m) - ew(rr, M, m))
        if statistics.mean(ds) >= stat: ge += 1
    p = (ge + 1) / (B + 1)
    signs = [o[-1] > 0 for o in obs]
    if halves: signs += [(rows[l].get('diff_前半') or -1) > 0 and (rows[l].get('diff_後半') or -1) > 0 for l in rows if 'diff' in rows[l]]
    crit = {'1_差>0（全アンカー' + ('・前半・後半' if halves else '') + '）': all(signs), '2_置換p<0.0125': p < ALPHA,
            '3_群n>=20': all(rows[l]['n'] >= MIN_N for l in rows if 'diff' in rows[l]),
            '4_上位1社<50%': all((rows[l].get('top1_share') or 0) < TOP1 for l in rows if 'diff' in rows[l])}
    return dict(anchors=rows, mean_diff=round(stat, 4), p=round(p, 4), criteria=crit, verdict='合格' if all(crit.values()) else '不合格')

def main():
    pan = cs.panel(); spy = {int(k): v for k, v in L('_spy_monthly.json').items()}; END = max(spy); SEMI = cs.semi_set()
    cik = L('_cik_tickers.json'); tick = [r['ticker'] for r in L('retro_features2_2018.json')['rows']]
    res = {}
    # B1 内部者の買い
    ins = L('angles_insider.json'); an = {}
    for Y in ('2013', '2018'):
        filers = set(ins[Y + '_filers'])
        pool = {t for t in tick if t in cik and str(cik[t]) in filers}   # Form 4 を出している社（被覆のある社）
        grp = {t for t in pool if ins[Y].get(str(cik[t]), {}).get('buyers', 0) >= 2}
        an[Y] = (int(Y) * 12 + 6, pool, grp, '2人以上の役員・取締役が市場で買った')
    res['B1_insider_buying'] = judge('B1', an, pan, END, spy, SEMI)
    # B2 注目度（規模で当然多いぶんを除いた残差の下位1/4）
    f13 = L('angles_13f.json'); an = {}
    for Y in ('2016', '2017', '2018'):
        rev = {r['ticker']: r.get('rev') for r in L(f'retro_features2_{Y}.json')['rows']}
        pts = [(t, math.log(rev[t]), math.log(1 + v['holders'])) for t, v in f13[Y].items() if rev.get(t) and rev[t] > 0]
        xs = [p[1] for p in pts]; ys = [p[2] for p in pts]; mx, my = statistics.mean(xs), statistics.mean(ys)
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs); a = my - b * mx
        resid = {t: y - (a + b * x) for t, x, y in pts}
        th = sorted(resid.values())[int(round(.25 * (len(resid) - 1)))]
        an[Y] = (int(Y) * 12 + 6, set(resid), {t for t, v in resid.items() if v <= th},
                 f'規模の割に保有機関が少ない下位1/4（log保有機関数 = {a:.2f} + {b:.3f}×log売上 の残差 <= {th:.3f}）')
    res['B2_attention'] = judge('B2', an, pan, END, spy, SEMI)
    # A1/A2 読解（済んでいれば）
    if os.path.exists(os.path.join(OUT, 'angles_read.json')):
        rd = L('angles_read.json')['rows']
        for key, nm in (('runway', 'A1_runway'), ('capalloc', 'A2_capital_allocation')):
            pool = {t for t, r in rd.items() if r.get(key) in (50, 70, 100)}
            grp = {t for t in pool if rd[t][key] == 100}
            if len(grp) < MIN_N:
                res[nm] = dict(verdict='検定不能', why=f'100 の社が {len(grp)}社 < 20（事前登録どおり線は緩めない）', pool=len(pool))
                continue
            r = judge(nm, {'2013': (2013 * 12 + 6, pool, grp, '読解で 100')}, pan, END, spy, SEMI, halves=True)
            # 漏れの検査（判定には使わない）: 会社を言い当てた社／言い当てなかった社に分けた差
            for lab, sub in (('当てた社', {t for t in pool if rd[t].get('guess_ok')}), ('当てなかった社', {t for t in pool if not rd[t].get('guess_ok')})):
                k0 = 2013 * 12 + 6; M = {t: pan[t][END] / pan[t][k0] for t in sub if t in pan and k0 in pan[t] and END in pan[t]}
                g = [t for t in M if t in grp]; rr = [t for t in M if t not in grp]
                r['leak_' + lab] = dict(n=len(g), pool=len(M), diff=round(ew(g, M, END - k0) - ew(rr, M, END - k0), 4) if g and rr else None)
            res[nm] = r
    json.dump(dict(generated=__import__('datetime').date.today().isoformat(), tool='night/angles_test.py', prereg='out/angles4_prereg.json', results=res),
              open(os.path.join(OUT, 'angles_test.json'), 'w'), ensure_ascii=False, indent=1)
    for k, r in res.items():
        print(f"\n■ {k}: {r['verdict']}  平均差 {r.get('mean_diff')}  p {r.get('p')}  {r.get('criteria', r.get('why'))}")
        for lab, a in (r.get('anchors') or {}).items(): print('  ', lab, a)
        for x in ('leak_当てた社', 'leak_当てなかった社'):
            if x in r: print('  ', x, r[x])

if __name__ == '__main__':
    main()
