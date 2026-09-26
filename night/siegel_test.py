#!/usr/bin/env python3
"""night/siegel_test.py — out/siegel_prereg.json を**書いてあるとおりに**裁く（線は動かさない）

入力: out/siegel_facts.json（S1〜S4）・月次パネル（combo_spy.panel）・ETF 月次（etf_theme.fetch・S5）
出力: out/siegel_test.json
"""
import json, os, random, statistics, sys, time
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'out')
sys.path.insert(0, os.path.join(BASE, 'night'))
import combo_spy as cs

PRE = json.load(open(os.path.join(OUT, 'siegel_prereg.json')))
B, SEED, ALPHA, MIN_N, TOP1 = PRE['null']['B'], PRE['null']['seed'], 0.0125, 20, 0.5

def q(vals, p):
    s = sorted(vals); return s[max(0, min(len(s) - 1, int(round(p * (len(s) - 1)))))]

def groups():
    F = json.load(open(os.path.join(OUT, 'siegel_facts.json')))['anchors']
    G = {k: {} for k in ('S1_dividend_yield', 'S2_shareholder_yield', 'S3_low_pe', 'S4_growth_trap')}
    for Y in (2013, 2018):
        R = F[str(Y)]['rows']
        v = {t: r['dy'] for t, r in R.items() if r.get('dy') is not None}
        th = q(list(v.values()), .75); G['S1_dividend_yield'][Y] = (set(v), {t for t, x in v.items() if x >= th and x > 0}, f'線 dy>={th:.4f}')
        v = {t: r['shy'] for t, r in R.items() if r.get('shy') is not None}
        th = q(list(v.values()), .75); G['S2_shareholder_yield'][Y] = (set(v), {t for t, x in v.items() if x >= th}, f'線 shy>={th:.4f}')
        v = {t: r['per'] for t, r in R.items()}
        th = q(list(v.values()), .25); G['S3_low_pe'][Y] = (set(v), {t for t, x in v.items() if x <= th}, f'線 per<={th:.2f}')
        v = {t: (r['per'], r['cagr5']) for t, r in R.items() if r.get('cagr5') is not None}
        tp, tg = q([a for a, _ in v.values()], .75), q([b for _, b in v.values()], .75)
        G['S4_growth_trap'][Y] = (set(v), {t for t, (a, b) in v.items() if a >= tp and b >= tg}, f'線 per>={tp:.1f} かつ cagr5>={tg:.3f}')
    return G

def ew(ts, M, months):
    return cs.cagr(sum(M[t] for t in ts) / len(ts), months) if ts else None

def stock_tests():
    pan = cs.panel(); spy = {int(k): v for k, v in json.load(open(os.path.join(OUT, '_spy_monthly.json'))).items()}
    END = max(spy); SEMI = cs.semi_set()
    uni = sorted(pan); rng = random.Random(SEED); perms = []
    for _ in range(B):
        s = uni[:]; rng.shuffle(s); perms.append(dict(zip(uni, s)))
    res = {}
    for c, per in groups().items():
        sign = -1 if c == 'S4_growth_trap' else 1
        rows, obs = {}, []
        for Y, (pool, grp, note) in sorted(per.items()):
            k0 = Y * 12 + 6; months = END - k0
            P = [t for t in pool if t in pan and k0 in pan[t] and END in pan[t]]
            M = {t: pan[t][END] / pan[t][k0] for t in uni if k0 in pan[t] and END in pan[t]}
            g = [t for t in P if t in grp]; r = [t for t in P if t not in grp]
            row = dict(note=note, pool=len(P), n=len(g), months=months)
            d = ew(g, M, months) - ew(r, M, months)
            gains = [(M[t] - 1, t) for t in g]; pos = sum(x for x, _ in gains if x > 0); top = max(gains)
            spyc = cs.cagr(spy[END] / spy[k0], months)
            gs = [t for t in g if t not in SEMI]; rs = [t for t in r if t not in SEMI]
            row.update(diff=round(d, 4), grp_cagr=round(ew(g, M, months), 4), rest_cagr=round(ew(r, M, months), 4),
                       vs_spy=round(ew(g, M, months) - spyc, 4),
                       lift15=round(sum(cs.cagr(M[t], months) >= .15 for t in g) / len(g) - sum(cs.cagr(M[t], months) >= .15 for t in r) / len(r), 3),
                       tail15=round(sum(cs.cagr(M[t], months) <= -.15 for t in g) / len(g) - sum(cs.cagr(M[t], months) <= -.15 for t in r) / len(r), 3),
                       top1=top[1], top1_share=round(top[0] / pos, 3) if pos > 0 else None,
                       diff_ex_semi=round(ew(gs, M, months) - ew(rs, M, months), 4) if gs and rs else None)
            obs.append((Y, g, r, M, months, d)); rows[Y] = row
        stat = statistics.mean(d for *_, d in obs)
        ge = 0
        for pm in perms:
            ds = []
            for Y, g, r, M, months, d in obs:
                gg = [pm[t] for t in g if pm[t] in M]; rr = [pm[t] for t in r if pm[t] in M]
                ds.append(ew(gg, M, months) - ew(rr, M, months))
            if sign * statistics.mean(ds) >= sign * stat: ge += 1
        p = (ge + 1) / (B + 1)
        crit = {
            '1_両アンカーで主張の向き': all(sign * d > 0 for *_, d in obs),
            '2_置換p<0.0125': p < ALPHA,
            '3_両アンカーでn>=20': all(rows[Y]['n'] >= MIN_N for Y in rows),
        }
        if sign > 0:
            crit['4_上位1社<50%'] = all((rows[Y].get('top1_share') or 0) < TOP1 for Y in rows)
        res[c] = dict(anchors=rows, mean_diff=round(stat, 4), p=round(p, 4), criteria=crit,
                      verdict='合格' if all(crit.values()) else '不合格')
    return res

def etf_test():
    import etf_theme as T, etf_long_windows as E
    c = {}
    for t in ('SPY', 'QQQ', 'XLK', 'SMH', 'VEIEX', 'VGTSX'):
        c[t] = T.fetch(t); time.sleep(.5)
    end = max(m for m in c['SPY'] if m < time.strftime('%Y-%m'))
    base = {'QQQ': 56, 'XLK': 22, 'SMH': 12}
    tot = sum(base.values())
    def mk(extra):
        w = {k: v / tot * 80 for k, v in base.items()}; w.update(extra); return w
    mixes = {'現行(100)': {k: v / tot * 100 for k, v in base.items()},
             '現行80+新興国20(VEIEX)': mk({'VEIEX': 20}), '現行80+米国外20(VGTSX)': mk({'VGTSX': 20})}
    start = max(min(E.mix_series(c, w)) for w in mixes.values())
    out = {'共通の窓': f'{start}→{end}', '案': {}}
    for lab, w in mixes.items():
        ser = E.mix_series(c, w); st = E.stats(ser, c['SPY'], start, end)
        rs = []
        for a in sorted(ser):
            if a < start: continue
            b = E.add_months(a, 240)
            if b > end: break
            s1 = E.stats(ser, c['SPY'], a, b)
            if s1 and s1.get('積立倍率比SPY'): rs.append(s1['積立倍率比SPY'])
        rs.sort()
        out['案'][lab] = dict(重み={k: round(v, 1) for k, v in w.items()}, 全窓=st,
                             転がる20年_積立=dict(n=len(rs), 倍率比_中央=rs[len(rs) // 2] if rs else None, 倍率比_最小=rs[0] if rs else None))
    b0 = out['案']['現行(100)']
    for lab in list(out['案'])[1:]:
        a = out['案'][lab]
        crit = {'年率÷ボラが上がる': a['全窓']['年率÷ボラ'] > b0['全窓']['年率÷ボラ'],
                '最大下落が浅い': a['全窓']['最大下落'] > b0['全窓']['最大下落'],
                '積立20年の中央が下がらない': (a['転がる20年_積立']['倍率比_中央'] or 0) >= (b0['転がる20年_積立']['倍率比_中央'] or 0)}
        a['criteria'] = crit; a['verdict'] = '合格' if all(crit.values()) else '不合格'
    return out

def main():
    res = stock_tests(); res['S5_international'] = etf_test()
    json.dump(dict(generated=__import__('datetime').date.today().isoformat(), tool='night/siegel_test.py',
                   prereg='out/siegel_prereg.json', results=res),
              open(os.path.join(OUT, 'siegel_test.json'), 'w'), ensure_ascii=False, indent=1)
    for c, r in res.items():
        if c == 'S5_international':
            print(f"\n■ {c} 共通の窓 {r['共通の窓']}")
            for lab, a in r['案'].items():
                s = a['全窓']; print(f"  {lab}: 年率{s['年率']} ボラ{s['年率ボラ']} DD{s['最大下落']} 効率{s['年率÷ボラ']} 積立20年中央{a['転がる20年_積立']['倍率比_中央']} {a.get('verdict','')} {a.get('criteria','')}")
            continue
        print(f"\n■ {c}: {r['verdict']}  平均差 {r['mean_diff']}  p {r['p']}  {r['criteria']}")
        for Y, a in r['anchors'].items(): print(f"  {Y}: {a}")

if __name__ == '__main__':
    main()
