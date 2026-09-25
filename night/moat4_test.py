#!/usr/bin/env python3
"""night/moat4_test.py — out/moat4_prereg.json を**書いてあるとおりに**裁く（線は動かさない）

入力: out/moat4_facts.json（C1/C2）・out/moat4_text.json（C3/C4）・月次パネル（combo_spy.panel をそのまま使う）
出力: out/moat4_test.json
"""
import json, os, random, statistics, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'out')
sys.path.insert(0, os.path.join(BASE, 'night'))
import combo_spy as cs

PRE = json.load(open(os.path.join(OUT, 'moat4_prereg.json')))
B, SEED, ALPHA, MIN_N, TOP1 = PRE['null']['B'], PRE['null']['seed'], 0.0125, 20, 0.5

def q(vals, p):
    s = sorted(vals); return s[max(0, min(len(s) - 1, int(round(p * (len(s) - 1)))))]

def groups():
    F = json.load(open(os.path.join(OUT, 'moat4_facts.json')))['rows']
    tp = os.path.join(OUT, 'moat4_text.json')
    T = json.load(open(tp))['rows'] if os.path.exists(tp) else {}
    G = {}  # cand -> {anchor_year: (pool, group, note)}
    def by(key, pick):
        vals = {t: r[key] for t, r in F.items() if r.get(key) is not None}
        return vals
    # C1 受注残: 上位1/4
    G['C1_rpo'] = {}
    for Y in (2019, 2020, 2021):
        v = by(f'rpo_{Y}', None)
        if not v: continue
        th = q(list(v.values()), .75)
        G['C1_rpo'][Y] = (set(v), {t for t, x in v.items() if x >= th}, f'線 rpo_r>={th:.3f}')
    # C2 粗利率の安定性: gm_sd 下位1/4
    G['C2_gm_stability'] = {}
    for Y in (2013, 2016, 2017, 2018):
        v = by(f'gmsd_{Y}', None)
        if not v: G['C2_gm_stability'][Y] = (set(), set(), '8年以上そろう社が0社＝測れない'); continue
        th = q(list(v.values()), .25)
        G['C2_gm_stability'][Y] = (set(v), {t for t, x in v.items() if x <= th}, f'線 gm_sd<={th:.4f}')
    # C3 値上げの記述: 上位1/4（線が0なら >0＝事前登録の修正A1）
    G['C3_pricing_text'] = {}
    for Y in ('2013', '2018'):
        v = {t: r[Y]['hits'] / r[Y]['words'] * 1e5 for t, r in T.items() if isinstance(r.get(Y), dict) and r[Y].get('words', 0) >= 5000}
        if not v: continue
        th = q(list(v.values()), .75)
        grp = {t for t, x in v.items() if (x > 0 if th == 0 else x >= th)}
        G['C3_pricing_text'][int(Y)] = (set(v), grp, f'線 {"price_r>0（修正A1）" if th == 0 else f"price_r>={th:.2f}"}')
    # C4 NRR: 開示社が20社未満なら検定不能
    G['C4_nrr'] = {}
    for Y in ('2013', '2018'):
        v = {t: r[Y]['nrr'] for t, r in T.items() if isinstance(r.get(Y), dict) and r[Y].get('nrr') is not None}
        if len(v) < 20:
            G['C4_nrr'][int(Y)] = (set(v), set(), f'開示社 {len(v)}社 < 20＝検定不能（feasibility_gate）'); continue
        th = statistics.median(v.values())
        G['C4_nrr'][int(Y)] = (set(v), {t for t, x in v.items() if x >= th}, f'線 nrr>={th:.1f}')
    return G, T

def ew(ts, M, months):
    return cs.cagr(sum(M[t] for t in ts) / len(ts), months) if ts else None

def main():
    pan = cs.panel(); spy = {int(k): v for k, v in json.load(open(os.path.join(OUT, '_spy_monthly.json'))).items()}
    END = max(spy)
    G, T = groups()
    uni = sorted(pan)
    rng = random.Random(SEED)
    perms = []
    for _ in range(B):
        s = uni[:]; rng.shuffle(s); perms.append(dict(zip(uni, s)))
    res = {}
    for c, per in G.items():
        rows, obs, ok_anchor = {}, [], []
        for Y, (pool, grp, note) in sorted(per.items()):
            k0 = Y * 12 + 6; months = END - k0
            P = [t for t in pool if t in pan and k0 in pan[t] and END in pan[t]]
            M = {t: pan[t][END] / pan[t][k0] for t in uni if k0 in pan[t] and END in pan[t]}
            g = [t for t in P if t in grp]; r = [t for t in P if t not in grp]
            row = dict(note=note, pool=len(P), n=len(g), months=months)
            if len(g) >= 1 and len(r) >= 1:
                d = ew(g, M, months) - ew(r, M, months)
                gains = [(M[t] - 1, t) for t in g]; pos = sum(x for x, _ in gains if x > 0)
                top = max(gains)
                spyc = cs.cagr(spy[END] / spy[k0], months)
                row.update(diff=round(d, 4), grp_cagr=round(ew(g, M, months), 4), rest_cagr=round(ew(r, M, months), 4),
                           vs_spy=round(ew(g, M, months) - spyc, 4),
                           lift15=round(sum(cs.cagr(M[t], months) >= .15 for t in g) / len(g) - sum(cs.cagr(M[t], months) >= .15 for t in r) / len(r), 3),
                           tail15=round(sum(cs.cagr(M[t], months) <= -.15 for t in g) / len(g) - sum(cs.cagr(M[t], months) <= -.15 for t in r) / len(r), 3),
                           top1=top[1], top1_share=round(top[0] / pos, 3) if pos > 0 else None)
                obs.append((Y, g, r, M, months, d)); ok_anchor.append(Y)
            rows[Y] = row
        if not obs:
            res[c] = dict(anchors=rows, verdict='検定不能', why='評価できるアンカーが無い'); continue
        stat = statistics.mean(d for *_, d in obs)
        ge = 0
        for pm in perms:
            ds = []
            for Y, g, r, M, months, d in obs:
                gg = [pm[t] for t in g if pm[t] in M]; rr = [pm[t] for t in r if pm[t] in M]
                ds.append(ew(gg, M, months) - ew(rr, M, months))
            if statistics.mean(ds) >= stat: ge += 1
        p = (ge + 1) / (B + 1)
        crit = {
            '1_全アンカーで差>0': all(d > 0 for *_, d in obs),
            '2_置換p<0.0125': p < ALPHA,
            '3_全アンカーでn>=20': all(rows[Y]['n'] >= MIN_N for Y in ok_anchor),
            '4_上位1社<50%': all((rows[Y].get('top1_share') or 0) < TOP1 for Y in ok_anchor),
        }
        res[c] = dict(anchors=rows, mean_diff=round(stat, 4), p=round(p, 4), criteria=crit,
                      verdict='合格' if all(crit.values()) else '不合格')
    # C2 の副次: 粗利率の水準の三分位の中で（報告だけ）
    F = json.load(open(os.path.join(OUT, 'moat4_facts.json')))['rows']
    sec = {}
    for Y in (2016, 2017, 2018):
        k0 = Y * 12 + 6; months = END - k0
        v = {t: (r[f'gmsd_{Y}'], r[f'gm_{Y}']) for t, r in F.items() if f'gmsd_{Y}' in r and f'gm_{Y}' in r and t in pan and k0 in pan[t] and END in pan[t]}
        if len(v) < 30: continue
        M = {t: pan[t][END] / pan[t][k0] for t in v}
        lv = sorted(v, key=lambda t: v[t][1]); n = len(lv); out = []
        for i in range(3):
            part = lv[i * n // 3:(i + 1) * n // 3]; th = q([v[t][0] for t in part], .25)
            g = [t for t in part if v[t][0] <= th]; r = [t for t in part if v[t][0] > th]
            out.append(dict(gm_tercile=i + 1, n=len(g), diff=round(ew(g, M, months) - ew(r, M, months), 4)))
        sec[Y] = out
    res['C2_gm_stability']['secondary_within_gm_level'] = sec
    json.dump(dict(generated=__import__('datetime').date.today().isoformat(), tool='night/moat4_test.py',
                   prereg='out/moat4_prereg.json', results=res), open(os.path.join(OUT, 'moat4_test.json'), 'w'),
              ensure_ascii=False, indent=1)
    for c, r in res.items():
        print(f"\n■ {c}: {r['verdict']}  平均差 {r.get('mean_diff')}  p {r.get('p')}  {r.get('criteria', r.get('why'))}")
        for Y, a in r['anchors'].items():
            print(f"  {Y}: {a}")
    print('\nC2 副次（粗利率の水準の三分位の中で・報告だけ）:', json.dumps(sec, ensure_ascii=False))

if __name__ == '__main__':
    main()
