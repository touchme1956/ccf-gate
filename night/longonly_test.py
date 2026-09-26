#!/usr/bin/env python3
"""night/longonly_test.py — out/longonly_prereg.json を書いてあるとおりに裁く（読むだけ・線は動かさない）

買いだけ（良い側1/3）の対市場超過を、米国の JKP 三分位ポートフォリオで測る。出力: out/longonly_test.json
"""
import csv, io, json, math, os, statistics as S, urllib.request, zipfile, datetime
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRE = json.load(open(os.path.join(BASE, 'out', 'longonly_prereg.json')))
U = 'https://jkpfactors-data.s3.amazonaws.com/public/{d}%5Busa%5D_%5B{k}%5D_%5Bmonthly%5D_%5Bvw_cap%5D.zip'
T_LINE = 2.64

def rd(k, pf):
    z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(U.format(d='portfolios/' if pf else '', k=k), timeout=120).read()))
    d = {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        m = int(x['date'][:4]) * 100 + int(x['date'][5:7])
        d.setdefault(x['pf'] if pf else 'f', {})[m] = float(x['ret'])
    return d

def corr(a, b):
    ma, mb = S.mean(a), S.mean(b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))

def st(ex, a=0, b=999999):
    x = [v for m, v in sorted(ex.items()) if a <= m <= b]
    if len(x) < 36: return None
    mu, sd, n = S.mean(x) * 12, S.stdev(x) * math.sqrt(12), len(x) / 12
    return {'年数': round(n, 1), '超過%/年': round(mu * 100, 2), 'ぶれ%': round(sd * 100, 1), 't': round(mu / (sd / math.sqrt(n)), 2)}

def roll(g, mk, Y):
    ms = sorted(set(g) & set(mk)); wins = []; tot = []
    for y0 in range(ms[0] // 100 + 1, 2100):
        w = [m for m in ms if y0 * 100 + 7 <= m <= (y0 + Y) * 100 + 6]
        if len(w) < 12 * Y or (y0 + Y) * 100 + 6 > ms[-1]: continue
        cg = math.prod(1 + g[m] for m in w) ** (1 / Y) - math.prod(1 + mk[m] for m in w) ** (1 / Y)
        tot.append((y0, round(cg * 100, 2)))
    return {'窓': len(tot), '勝ち': sum(1 for _, c in tot if c > 0), '勝率': round(sum(1 for _, c in tot if c > 0) / len(tot), 3) if tot else None,
            '最悪': min(tot, key=lambda x: x[1]) if tot else None, '中央%/年': sorted(c for _, c in tot)[len(tot) // 2] if tot else None}

def main():
    mk = rd('mkt', False)['f']
    good, res = {}, {}
    names = list(PRE['primary_signals'])[:-1] + list(PRE['reported_only'])
    for k in names:
        p = rd(k, True); f = rd(k, False)['f']
        ms = sorted(set(p['3.0']) & set(p['1.0']) & set(f))
        c = corr([p['3.0'][m] - p['1.0'][m] for m in ms], [f[m] for m in ms])
        side = '3.0' if c > 0 else '1.0'
        good[k] = p[side]
        res[k] = {'良い側': f"第{side[0]}分位（相関 {c:+.2f}）"}
    prim = list(PRE['primary_signals'])[:-1]
    common = sorted(set.intersection(*[set(good[k]) for k in prim]))
    good['blend'] = {m: S.mean(good[k][m] for k in prim) for m in common}
    for k in list(PRE['primary_signals']) + list(PRE['reported_only']):
        g = good[k]; ex = {m: g[m] - mk[m] for m in g if m in mk}
        full, pre, post = st(ex), st(ex, 0, 200612), st(ex, 200701)
        r20 = roll(g, mk, 20); r10 = roll(g, mk, 10)
        r = res.setdefault(k, {})
        r.update({'始まり': min(ex), '全期間': full, '〜2006': pre, '2007〜': post, '転がる20年': r20, '転がる10年': r10})
        if k in PRE['primary_signals']:
            crit = {'1_全期間 正かつt≥2.64': full['超過%/年'] > 0 and full['t'] >= T_LINE, '2_2007〜 正': post['超過%/年'] > 0,
                    '3_20年窓の勝率≥80%': (r20['勝率'] or 0) >= .8}
            r['criteria'] = crit; r['verdict'] = '合格' if all(crit.values()) else '不合格'
    json.dump({'generated': datetime.date.today().isoformat(), 'tool': 'night/longonly_test.py', 'prereg': 'out/longonly_prereg.json',
               'results': res}, open(os.path.join(BASE, 'out', 'longonly_test.json'), 'w'), ensure_ascii=False, indent=1)
    for k, r in res.items():
        f = lambda v: f"{v['超過%/年']:+5.2f}(t{v['t']:+.1f})" if v else '—'
        print(f"■ {k:13} {r.get('verdict','（報告のみ）'):6} {r.get('良い側', '5本を等分')}  {r['始まり']//100}〜 全 {f(r['全期間'])}  〜2006 {f(r['〜2006'])}  2007〜 {f(r['2007〜'])}"
              f"  20年窓 {r['転がる20年']['勝ち']}/{r['転がる20年']['窓']} 最悪{r['転がる20年']['最悪']}  10年窓 {r['転がる10年']['勝ち']}/{r['転がる10年']['窓']}")

if __name__ == '__main__':
    main()
