#!/usr/bin/env python3
"""night/industry_long.py — 業種の伸びを約100年（1926〜）で見る（読むだけ・判定に不使用）

ユーザー（2026-09-28）「もっと長い期間で用意できない？」への答え。SEC の決算（industry_trends.py）は2009年から。
事前登録: out/industry_long_prereg.json（測る前に固定）

Ken French 49業種の『社数・平均時価総額（月次）』と『Sum of BE / Sum of ME（年次）』から
  時価総額の合計 ME(12月末) = 社数 × 平均時価総額
  簿価の合計  BE(会計年 y)  = (BE/ME)_{y+1} × ME(y年12月末)
を復元する（French の BE/ME は y+1年6月の組入れ時点で、BE は y年の会計年度・ME は y年12月末）。
出力: out/industry_long.json（industry.html の「100年で見る」が読む）
"""
import io, json, math, os, sys, zipfile, datetime, statistics as S, time, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
from tech_persist import cagr as rcagr, spear
from industry_trends import JA

URL = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{}_CSV.zip'
OUT = os.path.join(BASE, 'out', 'industry_long.json')


def lines(name):
    for i in range(4):
        try:
            z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(URL.format(name), timeout=120).read()))
            return z.read(z.namelist()[0]).decode('latin-1').split('\n')
        except Exception:
            if i == 3:
                raise
            time.sleep(5 * (i + 1))


def block(L, title):
    """見出し title の次の行を列名に、日付(4桁の年 or 6桁の年月)で始まる行を読む。-99.99/-999 は欠測"""
    i = next(k for k, l in enumerate(L) if l.strip().startswith(title))
    hdr = [h.strip() for h in L[i + 1].split(',')]
    d = {h: {} for h in hdr[1:]}
    for l in L[i + 2:]:
        p = [x.strip() for x in l.split(',')]
        if len(p) < 2 or not p[0].isdigit():
            break
        for h, v in zip(hdr[1:], p[1:]):
            try:
                f = float(v)
            except ValueError:
                continue
            if f > -99:
                d[h][int(p[0])] = f
    return d


def main():
    L = lines('49_Industry_Portfolios')
    ret = {k: {m: v / 100 for m, v in s.items()} for k, s in block(L, 'Average Value Weighted Returns -- Monthly').items()}
    nf = block(L, 'Number of Firms in Portfolios')
    sz = block(L, 'Average Firm Size')
    bm = block(L, 'Sum of BE / Sum of ME')
    F = lines('F-F_Research_Data_Factors')
    i = next(k for k, l in enumerate(F) if l.strip().startswith(',') and 'Mkt-RF' in l)
    mkt = {}
    for l in F[i + 1:]:
        p = [x.strip() for x in l.split(',')]
        if len(p) < 5 or not (p[0].isdigit() and len(p[0]) == 6):
            break
        mkt[int(p[0])] = (float(p[1]) + float(p[4])) / 100
    endm = max(mkt)
    INDS = list(ret)

    # 12月末の時価総額（百万ドル）と 会計年 y の簿価
    ME, BE = {k: {} for k in INDS}, {k: {} for k in INDS}
    for k in INDS:
        for m, n in nf[k].items():
            if m % 100 == 12 and m in sz[k] and n > 0:
                ME[k][m // 100] = n * sz[k][m]
        for t, r in bm[k].items():
            y = t - 1
            if y in ME[k] and r > 0:
                BE[k][y] = r * ME[k][y]
    years = sorted({y for k in INDS for y in BE[k]})
    tot = {y: sum(ME[k].get(y, 0) for k in INDS) for y in years}

    def g(D, a, b):
        return (D[b] / D[a]) ** (1 / (b - a)) - 1 if a in D and b in D and D[a] > 0 and D[b] > 0 else None

    def xs(k, a, b):
        if b > endm:
            return None
        r, m = rcagr(ret[k], a, b), rcagr(mkt, a, b)
        return (r - m) if r is not None and m is not None else None

    # --- 答え合わせ（事前登録どおり）---
    bt = []
    for t in range(1936, 2100, 5):
        if t + 5 > years[-1] and (t + 6) * 100 + 6 > endm:
            break
        past = {k: g(BE[k], t - 5, t) for k in INDS}
        ks = [k for k in INDS if past[k] is not None]
        if len(ks) < 20:
            continue
        row = {'起点': t, '業種数': len(ks)}
        nxt = {k: g(BE[k], t, t + 5) for k in ks}
        k1 = [k for k in ks if nxt[k] is not None]
        row['問い1_順位相関(次の5年の簿価の成長)'] = round(spear([past[k] for k in k1], [nxt[k] for k in k1]), 3) if len(k1) >= 20 else None
        for H in (5, 10):
            a, b = (t + 1) * 100 + 7, (t + 1 + H) * 100 + 6
            kr = [k for k in ks if xs(k, a, b) is not None]
            if len(kr) < 20:
                row[f'問い2_順位相関(次の{H}年の超過)'] = None
                continue
            row[f'問い2_順位相関(次の{H}年の超過)'] = round(spear([past[k] for k in kr], [xs(k, a, b) for k in kr]), 3)
            o = sorted(kr, key=lambda k: -past[k])
            top, bot = o[:10], o[-10:]
            row[f'上位10−下位10(次の{H}年・%/年)'] = round((S.mean(xs(k, a, b) for k in top) - S.mean(xs(k, a, b) for k in bot)) * 100, 2)
            if H == 5:
                row['簿価の伸び上位5'] = o[:5]
        bt.append(row)

    def summ(key):
        v = [x[key] for x in bt if x.get(key) is not None]
        if not v:
            return None
        return {'起点の数': len(v), '平均': round(S.mean(v), 3), '正の起点': f'{sum(x > 0 for x in v)}/{len(v)}',
                '1990年以降の平均': round(S.mean([x[key] for x in bt if x.get(key) is not None and x['起点'] >= 1990]), 3)
                if any(x.get(key) is not None and x['起点'] >= 1990 for x in bt) else None}

    # --- 業種ごとの100年 ---
    last = years[-1]
    rows = []
    for k in INDS:
        share = {y: ME[k][y] / tot[y] for y in years if y in ME[k] and tot[y] > 0}
        def dec(a, b):
            return xs(k, a * 100 + 1, min(b * 100 + 12, endm))
        rows.append({
            'k': k, 'ja': JA.get(k, k), '最初の年': min(BE[k]) if BE[k] else None,
            '簿価の成長10年': g(BE[k], last - 10, last), '簿価の成長30年': g(BE[k], last - 30, last),
            '簿価の成長全期間': g(BE[k], min(BE[k]), last) if BE[k] else None,
            '時価の比重': {str(y): round(share[y], 5) for y in years if y % 5 == 0 or y == last if y in share},
            '比重の今': share.get(last), '比重の最大': max(share.values()) if share else None,
            '比重が最大だった年': max(share, key=share.get) if share else None,
            '年代ごとの超過(%/年)': {(f'{d}s' if d + 9 <= endm // 100 else f'{d}s(〜{endm // 100})'): (lambda v: None if v is None else round(v * 100, 1))(dec(d, d + 9))
                                 for d in range(1930, (endm // 100) + 1, 10)},
            '全期間の超過(%/年)': (lambda v: None if v is None else round(v * 100, 2))(xs(k, min(ret[k]), endm))})
    for r in rows:
        for key, v in list(r.items()):
            if isinstance(v, float):
                r[key] = round(v, 4)
    rows.sort(key=lambda r: -(r['比重の今'] or 0))
    doc = {'generated': datetime.date.today().isoformat(), 'tool': 'night/industry_long.py', 'prereg': 'out/industry_long_prereg.json',
           '期間': f'{years[0]}〜{last}（簿価）・リターンは{min(mkt)}〜{endm}',
           '答え合わせ': {'起点ごと': bt,
                     '問い1_簿価の伸びは続くか': summ('問い1_順位相関(次の5年の簿価の成長)'),
                     '問い2_次の5年の超過': summ('問い2_順位相関(次の5年の超過)'),
                     '問い2_次の10年の超過': summ('問い2_順位相関(次の10年の超過)'),
                     '上位10−下位10_次の5年(%/年)': summ('上位10−下位10(次の5年・%/年)'),
                     '上位10−下位10_次の10年(%/年)': summ('上位10−下位10(次の10年・%/年)')},
           '⚠限界': json.load(open(os.path.join(BASE, 'out', 'industry_long_prereg.json')))['limits'],
           'rows': rows}
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    a = doc['答え合わせ']
    print('→', OUT, doc['期間'])
    for k in ('問い1_簿価の伸びは続くか', '問い2_次の5年の超過', '問い2_次の10年の超過', '上位10−下位10_次の5年(%/年)', '上位10−下位10_次の10年(%/年)'):
        print(k, a[k])
    for r in rows[:10]:
        print(r['ja'], r['比重の今'], r['比重の最大'], r['比重が最大だった年'], r['簿価の成長30年'], r['全期間の超過(%/年)'])


if __name__ == '__main__':
    main()
