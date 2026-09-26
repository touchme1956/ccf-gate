#!/usr/bin/env python3
"""night/cape_evidence.py — 市場全体の割高さ（Shiller CAPE）とその後10年・20年の実質リターン（読むだけ）

データ: Robert Shiller『Irrational Exuberance』の公開データ ie_data.xls（S&P総合・1871〜・配当再投資の実質トータルリターン）。
問い: いま買う網（指数）の20年は、買った時の CAPE でどれだけ変わるか。毎月積立なら違いは縮むか。
出力: out/cape_evidence.json
"""
import io, json, math, os, statistics as S, urllib.request, datetime
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = 'http://www.econ.yale.edu/~shiller/data/ie_data.xls'

def main():
    import xlrd
    sh = xlrd.open_workbook(file_contents=urllib.request.urlopen(URL, timeout=90).read()).sheet_by_name('Data')
    rows = []
    for i in range(8, sh.nrows):
        r = sh.row_values(i)
        if not isinstance(r[0], float) or not isinstance(r[9], float): continue
        rows.append((r[0], r[9], r[12] if isinstance(r[12], float) else None))
    tr = [x[1] for x in rows]; cape = [x[2] for x in rows]
    def fwd(i, y):
        j = i + 12 * y
        return (tr[j] / tr[i]) ** (1 / y) - 1 if j < len(tr) else None
    def dca(i, y):  # 毎月同額を y 年入れた最終額 ÷ 投下額（実質）
        j = i + 12 * y
        if j >= len(tr): return None
        return sum(tr[j] / tr[k] for k in range(i, j)) / (12 * y)
    pts = [(cape[i], fwd(i, 10), fwd(i, 20), dca(i, 20)) for i in range(len(rows)) if cape[i]]
    out = {'generated': datetime.date.today().isoformat(), 'source': 'Shiller ie_data.xls', 'last_month': rows[-1][0],
           'last_cape': next(c for c in reversed(cape) if c), 'buckets': {}}
    bands = [(0, 10), (10, 15), (15, 20), (20, 25), (25, 30), (30, 99)]
    for lo, hi in bands:
        b = [p for p in pts if lo <= p[0] < hi]
        e = {'月数': len(b)}
        for k, nm in ((1, '10年の実質年率'), (2, '20年の実質年率')):
            v = sorted(p[k] for p in b if p[k] is not None)
            if v: e[nm] = {'n': len(v), '中央%': round(v[len(v) // 2] * 100, 1), '最悪%': round(v[0] * 100, 1), '最良%': round(v[-1] * 100, 1)}
        v = sorted(p[3] for p in b if p[3] is not None)
        if v: e['20年積立の倍率(実質)'] = {'n': len(v), '中央': round(v[len(v) // 2], 2), '最悪': round(v[0], 2)}
        out['buckets'][f'{lo}-{hi}'] = e
    def corr(a, b):
        ma, mb = S.mean(a), S.mean(b)
        return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    for k, nm in ((1, '10年'), (2, '20年'), (3, '20年積立')):
        q = [(math.log(p[0]), p[k]) for p in pts if p[k] is not None]
        out[f'相関 log(CAPE)×{nm}'] = round(corr([a for a, _ in q], [b for _, b in q]), 2)
    json.dump(out, open(os.path.join(BASE, 'out', 'cape_evidence.json'), 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))

if __name__ == '__main__':
    main()
