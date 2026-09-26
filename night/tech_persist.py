#!/usr/bin/env python3
"""night/tech_persist.py — out/tech_persist_prereg.json を書いてあるとおりに測る（読むだけ・合否なし）

過去10年に勝った業種は次の10年/20年も勝つか／テック3業種の時代ごとの超過／最大の1割は市場に勝つか。
データ: Kenneth R. French Data Library（CRSP・時価加重）。出力: out/tech_persist.json
"""
import io, json, math, os, statistics as S, urllib.request, zipfile, datetime
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FR = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{}_CSV.zip'

def block(name, title='Average Value Weighted Returns -- Monthly'):
    z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(FR.format(name), timeout=90).read()))
    L = z.read(z.namelist()[0]).decode('latin-1').split('\n')
    i = next(k for k, l in enumerate(L) if l.strip().startswith(title)) if title else \
        next(k for k, l in enumerate(L) if l.strip().startswith(',') and len(l.split(',')) > 1) - 1
    hdr = [h.strip() for h in L[i + 1].split(',')]; d = {h: {} for h in hdr[1:]}
    for l in L[i + 2:]:
        p = [x.strip() for x in l.split(',')]
        if len(p) < 2 or not (p[0].isdigit() and len(p[0]) == 6): break
        for h, v in zip(hdr[1:], p[1:]):
            if float(v) > -99: d[h][int(p[0])] = float(v) / 100
    return d

def cagr(s, a, b):
    x = [s[m] for m in sorted(s) if a <= m <= b]
    n = (b // 100 - a // 100) * 12 + b % 100 - a % 100 + 1
    return math.prod(1 + v for v in x) ** (12 / len(x)) - 1 if len(x) >= n * .97 else None

def rank(v):
    o = sorted(range(len(v)), key=lambda i: v[i]); r = [0] * len(v)
    for k, i in enumerate(o): r[i] = k
    return r

def spear(a, b):
    ra, rb = rank(a), rank(b); ma, mb = S.mean(ra), S.mean(rb)
    return sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))

def main():
    ind = block('49_Industry_Portfolios')
    f3 = block('F-F_Research_Data_Factors', None)
    mkt = {m: f3['Mkt-RF'][m] + f3['RF'][m] for m in f3['RF']}
    me = block('Portfolios_Formed_on_ME', 'Average Value Weight Returns -- Monthly')
    end = max(mkt)
    out = {'generated': datetime.date.today().isoformat(), 'prereg': 'out/tech_persist_prereg.json', 'end': end}
    # Q1 業種の持続
    rows = []
    for y0 in range(1936, 2100):
        a, b = (y0 - 10) * 100 + 7, y0 * 100 + 6
        for H in (10, 20):
            c, d = y0 * 100 + 7, (y0 + H) * 100 + 6
            if d > end: continue
            past = {k: cagr(s, a, b) for k, s in ind.items()}; fut = {k: cagr(s, c, d) for k, s in ind.items()}
            ks = [k for k in ind if past[k] is not None and fut[k] is not None]
            if len(ks) < 20: continue
            top = sorted(ks, key=lambda k: -past[k])[:5]; bot = sorted(ks, key=lambda k: past[k])[:5]
            m = cagr(mkt, c, d)
            rows.append({'起点': y0, 'H': H, 'top': top, '上位5の超過': round((S.mean(fut[k] for k in top) - m) * 100, 2),
                         '下位5の超過': round((S.mean(fut[k] for k in bot) - m) * 100, 2),
                         '順位相関': round(spear([past[k] for k in ks], [fut[k] for k in ks]), 3)})
    q1 = {}
    for H in (10, 20):
        r = [x for x in rows if x['H'] == H]; ind10 = [x for x in r if (x['起点'] - 1936) % H == 0]
        def sm(rr):
            if not rr: return None
            u = sorted(x['上位5の超過'] for x in rr); l = sorted(x['下位5の超過'] for x in rr)
            return {'窓': len(rr), '上位5 超過の中央': u[len(u) // 2], '上位5 勝率': round(sum(x > 0 for x in u) / len(u), 2),
                    '下位5 超過の中央': l[len(l) // 2], '下位5 勝率': round(sum(x > 0 for x in l) / len(l), 2),
                    '順位相関の平均': round(S.mean(x['順位相関'] for x in rr), 3)}
        q1[f'次の{H}年'] = {'全起点（重なる）': sm(r), f'{H}年刻み（独立）': sm(ind10), '独立な窓の中身': ind10}
    out['Q1_業種の持続'] = q1
    # 事後（事前登録の外）: 過去10年の『1位』の業種だけ——いまの Chips がこの位置にいるので
    one = []
    for y0 in range(1936, 2100):
        a, b, c, d = (y0 - 10) * 100 + 7, y0 * 100 + 6, y0 * 100 + 7, (y0 + 10) * 100 + 6
        if d > end: break
        past = {k: cagr(s, a, b) for k, s in ind.items()}; ks = [k for k in ind if past[k] is not None and cagr(ind[k], c, d) is not None]
        k1 = max(ks, key=lambda k: past[k]); one.append((y0, k1, round((cagr(ind[k1], c, d) - cagr(mkt, c, d)) * 100, 2)))
    ex = sorted(x[2] for x in one)
    out['事後_過去10年1位の業種の次の10年'] = {'窓': len(one), '中央': ex[len(ex) // 2], '勝率': round(sum(x > 0 for x in ex) / len(ex), 2),
                                        '10年刻み': [x for x in one if (x[0] - 1936) % 10 == 0]}
    # 今の位置（直近10年の業種順位と、最大の1割の直近10年）——基礎率を今日へ当てるための材料
    ye = end // 100 if end % 100 >= 6 else end // 100 - 1
    a, b = (ye - 10) * 100 + 7, ye * 100 + 6
    past = {k: cagr(s, a, b) for k, s in ind.items() if cagr(s, a, b) is not None}
    mk10 = cagr(mkt, a, b)
    out['今の位置'] = {'窓': f'{a}→{b}', '市場年率%': round(mk10 * 100, 1),
                    '上位8業種': [(k, round(v * 100, 1)) for k, v in sorted(past.items(), key=lambda x: -x[1])[:8]],
                    'テック3業種の順位': {k: sorted(past, key=lambda x: -past[x]).index(k) + 1 for k in ('Chips', 'Softw', 'Hardw')},
                    '最大の1割−市場 直近10年%/年': round((cagr(me['Hi 10'], a, b) - mk10) * 100, 2)}
    # テック3業種
    tech = {m: S.mean(ind[k][m] for k in ('Hardw', 'Softw', 'Chips') if m in ind[k]) for m in ind['Chips'] if all(m in ind[k] for k in ('Hardw', 'Softw', 'Chips'))}
    per = {}
    for a, b, nm in ((min(tech), 196912, f'{min(tech)//100}-1969'), (197001, 198912, '1970-1989'), (199001, 199912, '1990-1999'),
                     (200001, 200912, '2000-2009'), (201001, 201912, '2010-2019'), (202001, end, f'2020-{end//100}'), (min(tech), end, '全期間')):
        t, mm = cagr(tech, a, b), cagr(mkt, a, b)
        if t is not None: per[nm] = {'テック年率%': round(t * 100, 1), '市場年率%': round(mm * 100, 1), '差': round((t - mm) * 100, 1)}
    out['テック3業種(Hardw/Softw/Chips 等分)'] = per
    # Q2 最大の1割
    hi = me['Hi 10']; q2 = {}
    for a, b, nm in ((192607, 195612, '1926-1956'), (195701, 198612, '1957-1986'), (198701, 200612, '1987-2006'), (200701, end, f'2007-{end//100}'), (192607, end, '全期間')):
        q2[nm] = round((cagr(hi, a, b) - cagr(mkt, a, b)) * 100, 2)
    after = []
    for y0 in range(1937, 2100):
        a, b, c, d = (y0 - 10) * 100 + 7, y0 * 100 + 6, y0 * 100 + 7, (y0 + 10) * 100 + 6
        if d > end: break
        if cagr(hi, a, b) > cagr(mkt, a, b): after.append(round((cagr(hi, c, d) - cagr(mkt, c, d)) * 100, 2))
    q2['過去10年に市場に勝った後の次の10年'] = {'窓': len(after), '中央': sorted(after)[len(after) // 2] if after else None,
                                         '勝率': round(sum(x > 0 for x in after) / len(after), 2) if after else None}
    out['Q2_最大の1割−市場(%/年)'] = q2
    json.dump(out, open(os.path.join(BASE, 'out', 'tech_persist.json'), 'w'), ensure_ascii=False, indent=1)
    for H in ('次の10年', '次の20年'):
        print(H, {k: v for k, v in q1[H].items() if k != '独立な窓の中身'})
        for x in q1[H]['独立な窓の中身']: print('   ', x['起点'], x['top'], '上位5', x['上位5の超過'], '下位5', x['下位5の超過'], '相関', x['順位相関'])
    print('1位', json.dumps({k: v for k, v in out['事後_過去10年1位の業種の次の10年'].items()}, ensure_ascii=False))
    print('今の位置', json.dumps(out['今の位置'], ensure_ascii=False))
    print('テック', json.dumps(per, ensure_ascii=False)); print('最大の1割', json.dumps(q2, ensure_ascii=False))

if __name__ == '__main__':
    main()
