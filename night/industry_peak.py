#!/usr/bin/env python3
"""night/industry_peak.py — 業種の比重が『過去最大』を付けた後、その業種の株はどうなったか（読むだけ・判定に不使用）

ユーザー（2026-09-28）「これかなり重要なデータでは？」→「やって」。
2025年末、米国株の時価総額に占める比重は ソフトウェア 19.9%・半導体・電子部品 19.3% で、どちらも100年で最大。
事前登録: out/industry_peak_prereg.json（5693cf8・測る前に固定）

★後知恵を入れない: 『最後の最大の年』（後から見て初めて分かる）ではなく、その時点で分かる『新記録』ごとに数える。
  最後の最大の年から数えた版は、偏りの大きさを見せるためだけに並べる（判定には使わない）。
データの復元は night/industry_long.py と同じ（12月の 社数 × 平均時価総額）。
出力: out/industry_peak.json
"""
import json, math, os, sys, datetime, statistics as S

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
from tech_persist import cagr as rcagr
from industry_long import lines, block
from industry_trends import JA

OUT = os.path.join(BASE, 'out', 'industry_peak.json')
PREREG = os.path.join(BASE, 'out', 'industry_peak_prereg.json')


def load():
    L = lines('49_Industry_Portfolios')
    ret = {k: {m: v / 100 for m, v in s.items()} for k, s in block(L, 'Average Value Weighted Returns -- Monthly').items()}
    nf = block(L, 'Number of Firms in Portfolios')
    sz = block(L, 'Average Firm Size')
    F = lines('F-F_Research_Data_Factors')
    i = next(k for k, l in enumerate(F) if l.strip().startswith(',') and 'Mkt-RF' in l)
    mkt = {}
    for l in F[i + 1:]:
        p = [x.strip() for x in l.split(',')]
        if len(p) < 5 or not (p[0].isdigit() and len(p[0]) == 6):
            break
        mkt[int(p[0])] = (float(p[1]) + float(p[4])) / 100
    ME = {k: {} for k in ret}
    for k in ret:
        for m, n in nf[k].items():
            if m % 100 == 12 and m in sz[k] and n > 0:
                ME[k][m // 100] = n * sz[k][m]
    years = sorted({y for k in ME for y in ME[k]})
    tot = {y: sum(ME[k].get(y, 0) for k in ME) for y in years}
    share = {k: {y: ME[k][y] / tot[y] for y in ME[k] if tot[y] > 0} for k in ME}
    return ret, mkt, share, max(mkt), years[-1]


def binom_p(k, n):
    """勝った山の数 k / n の両側の符号検定（参考・判定には使わない）"""
    if n == 0:
        return None
    t = min(k, n - k)
    p = sum(math.comb(n, i) for i in range(0, t + 1)) / 2 ** n * 2
    return round(min(1.0, p), 3)


def main():
    ret, mkt, share, endm, last = load()

    def xs(k, y, H):
        a, b = (y + 1) * 100 + 1, (y + H) * 100 + 12
        if b > endm:
            return None
        r, m = rcagr(ret[k], a, b), rcagr(mkt, a, b)
        return None if r is None or m is None else r - m

    def records(thr, min_hist=10, since=None):
        ev = []
        for k, s in share.items():
            mx, n = None, 0
            for y in sorted(s):
                if n >= min_hist and s[y] > mx and s[y] >= thr and (since is None or y >= since):
                    ev.append((k, y))
                mx = s[y] if mx is None else max(mx, s[y])
                n += 1
        return ev

    def episodes(ev, gap=5):
        by = {}
        for k, y in sorted(ev):
            by.setdefault(k, []).append(y)
        eps = []
        for k, ys in by.items():
            cur = [ys[0]]
            for y in ys[1:]:
                if y - cur[-1] <= gap:
                    cur.append(y)
                else:
                    eps.append((k, cur))
                    cur = [y]
            eps.append((k, cur))
        return sorted(eps, key=lambda e: e[1][0])

    def ep_value(k, ys, H, pick='median'):
        if pick == 'first':
            ys = ys[:1]
        elif pick == 'last':
            ys = ys[-1:]
        v = [x for x in (xs(k, y, H) for y in ys) if x is not None]
        return S.median(v) if v else None

    def summ(vals):
        v = [x for x in vals if x is not None]
        if not v:
            return {'山の数': 0}
        w = sum(x > 0 for x in v)
        return {'山の数': len(v), '中央値(%/年)': round(S.median(v) * 100, 2), '平均(%/年)': round(S.mean(v) * 100, 2),
                '勝った山': f'{w}/{len(v)}', '勝率': round(w / len(v), 3), '符号検定p(参考)': binom_p(w, len(v)),
                '最小': round(min(v) * 100, 1), '最大': round(max(v) * 100, 1)}

    def baseline(thr, H, min_hist=10, since=None):
        rec = set(records(thr, min_hist))
        v = []
        for k, s in share.items():
            ys = sorted(s)
            for i, y in enumerate(ys):
                if i >= min_hist and s[y] >= thr and (k, y) not in rec and (since is None or y >= since):
                    x = xs(k, y, H)
                    if x is not None:
                        v.append(x)
        w = sum(x > 0 for x in v)
        return {'業種の年': len(v), '中央値(%/年)': round(S.median(v) * 100, 2) if v else None,
                '勝率': round(w / len(v), 3) if v else None}

    def study(thr, H=10, gap=5, min_hist=10, since=None, pick='median'):
        eps = episodes(records(thr, min_hist, since), gap)
        return summ([ep_value(k, ys, H, pick) for k, ys in eps])

    # --- 主（事前登録どおり）---
    THR, H = 0.05, 10
    eps = episodes(records(THR))
    prim = study(THR, H)
    base = baseline(THR, H)
    rec_level = [xs(k, y, H) for k, y in records(THR)]
    rv = [x for x in rec_level if x is not None]
    if prim['山の数'] < 8:
        verdict = '判定不能'
    elif prim['中央値(%/年)'] <= -1.0 and prim['勝率'] <= 0.40 and prim['中央値(%/年)'] < base['中央値(%/年)']:
        verdict = '支持'
    elif prim['中央値(%/年)'] >= 0 or prim['勝率'] >= 0.50:
        verdict = '否定'
    else:
        verdict = '弱い'

    # --- 山の一覧 ---
    ep_rows = []
    for k, ys in eps:
        s = share[k]
        nxt = [y for y in sorted(s) if y > ys[-1]]
        ep_rows.append({
            '業種': k, 'ja': JA.get(k, k), '最初の記録': ys[0], '最後の記録': ys[-1], '記録の年数': len(ys),
            '最初の比重': round(s[ys[0]], 4), '最大の比重': round(s[ys[-1]], 4),
            '次の10年の超過(山の中央値・%/年)': (lambda v: None if v is None else round(v * 100, 2))(ep_value(k, ys, 10)),
            '次の20年の超過(山の中央値・%/年)': (lambda v: None if v is None else round(v * 100, 2))(ep_value(k, ys, 20)),
            '最初の記録から10年(%/年)': (lambda v: None if v is None else round(v * 100, 2))(xs(k, ys[0], 10)),
            '最後の記録から10年(%/年)・後知恵': (lambda v: None if v is None else round(v * 100, 2))(xs(k, ys[-1], 10)),
            '記録の年ごとの10年(%/年)': {str(y): (None if xs(k, y, 10) is None else round(xs(k, y, 10) * 100, 1)) for y in ys},
            '10年後の比重÷記録の年(山の中央値)': (lambda v: round(S.median(v), 3) if v else None)(
                [s[y + 10] / s[y] for y in ys if y + 10 in s]),
            '今も続いている': ys[-1] == last})

    # --- 記録の後にもう一度 記録が来たか（その時点の基礎率・後知恵なし）---
    again = []
    for k, y in records(THR):
        if y + 5 <= last:
            again.append(any(k == k2 and y < y2 <= y + 5 for k2, y2 in records(THR)))

    # --- 道筋（1・3・5・10・20年）---
    path = {f'{h}年': study(THR, h) for h in (1, 3, 5, 10, 20)}
    path_base = {f'{h}年': baseline(THR, h) for h in (1, 3, 5, 10, 20)}

    sec = {
        '閾値3%・10年': study(0.03, 10), '閾値3%・20年': study(0.03, 20),
        '閾値10%・10年': study(0.10, 10), '閾値10%・20年': study(0.10, 20),
        '山の最初の記録だけ・10年': study(THR, 10, pick='first'), '山の最初の記録だけ・20年': study(THR, 20, pick='first'),
        '★後知恵: 山の最後の記録(最大の年)・10年': study(THR, 10, pick='last'),
        '★後知恵: 山の最後の記録(最大の年)・20年': study(THR, 20, pick='last'),
        '1950年以降・10年': study(THR, 10, since=1950), '1950年以降・20年': study(THR, 20, since=1950),
        '山のまとめ方2年・10年': study(THR, 10, gap=2), '山のまとめ方10年・10年': study(THR, 10, gap=10),
        '前の年数20年以上・10年': study(THR, 10, min_hist=20),
        '比較群(記録でない・比重5%以上)・20年': baseline(THR, 20),
        '比較群(記録でない・比重5%以上)・1950年以降・10年': baseline(THR, 10, since=1950),
    }
    shr = [r['10年後の比重÷記録の年(山の中央値)'] for r in ep_rows if r['10年後の比重÷記録の年(山の中央値)'] is not None]

    # --- 事後（結果を見た後に足した・判定に使わない）: 今の二つに近い記録だけ ---
    #   2025年のソフトウェアは山の最初の記録から8年目・比重は10年で1.87倍、半導体・電子部品は6年目・2.92倍。
    #   どちらもその時点で分かる性質（後知恵ではない）だが、切り方は結果を見てから決めた。
    def cut(pred, H):
        vals = []
        for k, ys in eps:
            v = [xs(k, y, H) for y in ys if pred(k, y, ys[0])]
            v = [x for x in v if x is not None]
            if v:
                vals.append(S.median(v))
        return summ(vals)

    def rise(k, y):
        s = share[k]
        return s[y] / s[y - 10] if y - 10 in s and s[y - 10] > 0 else None
    post = {}
    for H in (10, 20):
        post[f'山の最初の記録から5年以上たった記録・{H}年'] = cut(lambda k, y, y0: y - y0 >= 5, H)
        post[f'山の最初の記録から5年未満の記録・{H}年'] = cut(lambda k, y, y0: y - y0 < 5, H)
        post[f'比重が10年で2倍以上になった記録・{H}年'] = cut(lambda k, y, y0: (rise(k, y) or 0) >= 2, H)
        post[f'比重の10年の伸びが2倍未満の記録・{H}年'] = cut(lambda k, y, y0: rise(k, y) is not None and rise(k, y) < 2, H)
    no_bub = [ep_value(k, ys, 10) for k, ys in eps if not (1997 <= ys[0] <= 2001)]
    post['1998-2001年のITバブルの山を除く・10年'] = summ(no_bub)
    for k, ys in eps:
        for r in ep_rows:
            if r['業種'] == k and r['最初の記録'] == ys[0]:
                r['記録の年ごとの比重の10年の伸び(倍)'] = {str(y): (None if rise(k, y) is None else round(rise(k, y), 2)) for y in ys}

    # --- 今（最新の年）に記録を付けている業種 ---
    now = []
    for k, s in share.items():
        ys = sorted(s)
        if ys[-1] == last and len(ys) > 10 and s[last] > max(s[y] for y in ys[:-1]):
            e = next((ys_ for k_, ys_ in episodes(records(0.0)) if k_ == k and ys_[-1] == last), None)
            now.append({'業種': k, 'ja': JA.get(k, k), '比重': round(s[last], 4),
                        '前の最大': round(max(s[y] for y in ys[:-1]), 4),
                        '前の最大の年': max(ys[:-1], key=lambda y: s[y]),
                        '今の山の最初の記録': e[0] if e else None, '今の山の記録の年数': len(e) if e else None,
                        '10年前の比重': round(s[last - 10], 4) if last - 10 in s else None,
                        '20年前の比重': round(s[last - 20], 4) if last - 20 in s else None})
    now.sort(key=lambda r: -r['比重'])

    # 過去に記録の比重がどこまで大きくなったか（大きい順）
    biggest = sorted(({'業種': r['業種'], 'ja': r['ja'], '最大の比重': r['最大の比重'], '年': r['最後の記録']} for r in ep_rows),
                     key=lambda r: -r['最大の比重'])[:12]

    doc = {'generated': datetime.date.today().isoformat(), 'tool': 'night/industry_peak.py',
           'prereg': 'out/industry_peak_prereg.json（5693cf8）', 'データの終わり': endm, '比重の最新の年': last,
           '判定': verdict,
           '主_閾値5%・次の10年・山ごと': prim,
           '比較群_記録でない年(比重5%以上)・10年': base,
           '参考_記録の年ごと(重なりあり)・10年': {'年の数': len(rv), '中央値(%/年)': round(S.median(rv) * 100, 2) if rv else None,
                                         '勝率': round(sum(x > 0 for x in rv) / len(rv), 3) if rv else None},
           '記録の後_5年以内にもう一度記録が来た割合(その時点の基礎率)': {'記録の年': len(again),
                                                   '割合': round(sum(again) / len(again), 3) if again else None},
           '道筋_山ごと': path, '道筋_比較群': path_base,
           '副': sec,
           '事後_今の二つに近い記録(結果を見た後に足した・判定に使わない)': post,
           '10年後の比重': {'山の数': len(shr), '下がった山': f'{sum(x < 1 for x in shr)}/{len(shr)}',
                         '中央値(倍)': round(S.median(shr), 3) if shr else None},
           '今_記録を付けている業種': now,
           '過去の記録で比重が大きかった山': biggest,
           '山': ep_rows,
           '⚠限界': json.load(open(PREREG))['limits']}
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)

    print('→', OUT, '判定:', verdict)
    print('主', prim)
    print('比較群', base)
    print('参考(記録の年ごと)', doc['参考_記録の年ごと(重なりあり)・10年'])
    print('もう一度記録', doc['記録の後_5年以内にもう一度記録が来た割合(その時点の基礎率)'])
    for h, v in path.items():
        print('道筋', h, v.get('中央値(%/年)'), v.get('勝った山'), '| 比較群', path_base[h])
    for k, v in sec.items():
        print(k, v)
    for k, v in post.items():
        print('事後', k, v)
    print('10年後の比重', doc['10年後の比重'])
    print('今', now)
    for r in ep_rows:
        print(r['ja'], r['最初の記録'], '→', r['最後の記録'], r['記録の年数'], r['最初の比重'], '→', r['最大の比重'],
              '| 10年', r['次の10年の超過(山の中央値・%/年)'], '20年', r['次の20年の超過(山の中央値・%/年)'],
              '| 最初から', r['最初の記録から10年(%/年)'], '最後から', r['最後の記録から10年(%/年)・後知恵'],
              '| 比重×', r['10年後の比重÷記録の年(山の中央値)'])


if __name__ == '__main__':
    main()
