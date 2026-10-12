#!/usr/bin/env python3
"""night/future30.py — 今後伸びる産業と30年の複利の構造（2026-10-11・ユーザー「今後伸びる産業を分析して30年投資でも複利を得られる構造にして」）

読むだけ。門・採点・配分には触れない。事前登録 out/future30_prereg.json（aa6405d・測る前に固定）どおり。

  Q1 完全な予知     … 30年先の簿価の伸びを完全に知っていたら、その業種に積み立てた30年は市場より良かったか（起点 1930〜1995・5年ごと）
  Q2 その時の目印   … 直近10年の簿価の伸び・株の勝者・比重の記録で選んで30年持ったら（起点 1936〜1995・毎年）
  Q3 構造の型       … 市場／勝者に集中／入れ替え／芯50／業種を等分／上限つき集中 を30年の毎月の積立で比べる
  Q3b 今の形の写し  … NASDAQ100＝テック65%＋市場35%・SMH＝Chips・ITA＝Aero＋Guns・個別株＝市場（起点 1965〜1995・参考）
  Q5 今の保有の更新力（記述）と、30年で業種の顔ぶれがどれだけ入れ替わったか

データ: Ken French の49業種（mw_common.french_tables の写し）・F-F の市場（gaps_common.french_mkt）・FRED CPIAUCNS。
簿価 BE(会計年 y)＝(Sum BE/Sum ME)_{y+1}×ME(y年12月末)（industry_long.py と同じ式）。
出力: out/future30.json
"""
import datetime, json, math, os, statistics as S, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import mw_common as M          # noqa: E402
import gaps_common as G        # noqa: E402
from tech_persist import spear  # noqa: E402
from industry_trends import JA  # noqa: E402

OUT = os.path.join(BASE, 'out', 'future30.json')
PREREG = 'out/future30_prereg.json（aa6405d）'
MIN_SHARE = 0.005
N = 360


def load():
    t = M.french_tables('49_Industry_Portfolios')
    vw = t['Average Value Weighted Returns -- Monthly']
    nf = t['Number of Firms in Portfolios']
    sz = t['Average Firm Size']
    bm = t['Sum of BE / Sum of ME']
    cols = vw['cols']
    ret = {c: {} for c in cols}
    for m, row in vw['data'].items():
        for c, x in zip(cols, row):
            if x is not None:
                ret[c][m] = x / 100
    capm = {c: {} for c in cols}          # その月の重み（French の平均時価総額は組入れ時点＝前月末の値）
    for m, row in nf['data'].items():
        srow = sz['data'].get(m)
        if not srow:
            continue
        for c, n, z in zip(cols, row, srow):
            if n and z and n > 0 and z > 0:
                capm[c][m] = n * z
    me = {c: {} for c in cols}            # 12月末の時価総額＝翌年1月の組入れ時点の値ではなく、12月の行（industry_long と同じ）
    for c in cols:
        for m, w in capm[c].items():
            if m % 100 == 12:
                me[c][m // 100] = w
    be = {c: {} for c in cols}
    for tt, row in bm['data'].items():
        y = tt - 1
        for c, r in zip(cols, row):
            if r is not None and r > 0 and y in me[c]:
                be[c][y] = r * me[c][y]
    years = sorted({y for c in cols for y in me[c]})
    tot = {y: sum(me[c].get(y, 0) for c in cols) for y in years}
    share = {c: {y: me[c][y] / tot[y] for y in me[c] if tot[y] > 0} for c in cols}
    mkt, _ = G.french_mkt()
    return cols, ret, capm, me, be, share, mkt


def months(a, n):
    return [G.add_months(a, i) for i in range(n)]


def cagr_m(r, ms):
    if any(m not in r for m in ms):
        return None
    return math.prod(1 + r[m] for m in ms) ** (12 / len(ms)) - 1


def dca_mult(r, ms):
    if any(m not in r for m in ms):
        return None
    v = 0.0
    for m in ms:
        v = (v + 1) * (1 + r[m])
    return v / len(ms)


def dca_irr(r, ms):
    if any(m not in r for m in ms):
        return None
    v = 0.0
    for m in ms:
        v = (v + 1) * (1 + r[m])
    flows = [-1.0] * len(ms) + [0.0]
    flows[-1] += v
    return G.irr_monthly(flows)


def ew(ret, inds, ms):
    """等分・毎月組み直し。その月に値の無い業種は外して残りで等分（全部無ければ欠測）"""
    out = {}
    for m in ms:
        v = [ret[c][m] for c in inds if m in ret[c]]
        if v:
            out[m] = sum(v) / len(v)
    return out


def capw(ret, capm, inds, ms):
    """時価総額で加重（その月の組入れ時点の重み）"""
    out = {}
    for m in ms:
        num = den = 0.0
        for c in inds:
            r, w = ret[c].get(m), capm[c].get(m, 0)
            if r is None or w <= 0:
                continue
            num += w * r
            den += w
        if den > 0:
            out[m] = num / den
    return out


def mix(parts, ms):
    """parts: [(重み, 系列)]・毎月組み直し"""
    out = {}
    for m in ms:
        if all(m in s for _, s in parts):
            out[m] = sum(w * s[m] for w, s in parts)
    return out


def hold_year(wts, series, y):
    """y年の1月に wts={鍵: 重み} で買い、その年の中は持ちっぱなし（重みは値動きで動く）＝『毎年1月に組み直し』の文言どおり。
    その月に値の無い鍵はその月だけ外して残りで割る（重みはそのまま持ち越す）"""
    w = {k: v for k, v in wts.items() if v > 0}
    out = {}
    for m in months(y * 100 + 1, 12):
        live = [k for k in w if m in series[k]]
        tot = sum(w[k] for k in live)
        if tot <= 0:
            continue
        out[m] = sum(w[k] * series[k][m] for k in live) / tot
        for k in live:
            w[k] *= 1 + series[k][m]
    return out


def pct(x, d=2):
    return None if x is None else round(100 * x, d)


def summ(vals, halves=None):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    q = lambda p: v[min(len(v) - 1, max(0, int(round(p * (len(v) - 1)))))]
    d = {'起点の数': len(v), '中央値': round(S.median(v), 3), '市場に勝った割合': round(sum(x > 1 for x in v) / len(v), 3),
         '下位10%点': round(q(0.10), 3), '最悪': round(v[0], 3), '最良': round(v[-1], 3)}
    if halves:
        for lab, hv in halves.items():
            hv = [x for x in hv if x is not None]
            d[f'中央値_{lab}'] = round(S.median(hv), 3) if hv else None
            d[f'勝った割合_{lab}'] = round(sum(x > 1 for x in hv) / len(hv), 3) if hv else None
    return d


def trailing_excess(ret, mkt, c, t):
    ms = months((t - 9) * 100 + 1, 120)
    a, b = cagr_m(ret[c], ms), cagr_m(mkt, ms)
    return None if a is None or b is None else a - b


def main():
    cols, ret, capm, me, be, share, mkt = load()
    endm = max(mkt)
    cpi = G.fred('CPIAUCNS')
    ks = sorted(cpi)
    infl = {k: cpi[k] / cpi[p] - 1 for p, k in zip(ks, ks[1:])}
    real = lambda r: {m: (1 + v) / (1 + infl[m]) - 1 for m, v in r.items() if m in infl}
    out = {'generated': datetime.date.today().isoformat(), 'tool': 'night/future30.py', 'prereg': PREREG,
           'データの期間': f'{min(mkt)}〜{endm}（リターン）・簿価 {min(min(be[c]) for c in cols if be[c])}〜{max(max(be[c]) for c in cols if be[c])}'}

    # ───────── Q1 完全な予知 ─────────
    q1rows, q1rows_all, q1rows_me = [], [], []
    renew = []
    for t in range(1930, 1996, 5):
        ms = months((t + 1) * 100 + 1, N)
        if ms[-1] > endm:
            continue
        mk_d, mk_c = dca_mult(mkt, ms), cagr_m(mkt, ms)

        def one(filter_share, growth):
            U = []
            for c in cols:
                if growth == 'be':
                    a, b = be[c].get(t), be[c].get(t + 30)
                else:
                    a, b = me[c].get(t), me[c].get(t + 30)
                if not a or not b or a <= 0 or b <= 0:
                    continue
                if filter_share and share[c].get(t, 0) < MIN_SHARE:
                    continue
                cg = cagr_m(ret[c], ms)
                if cg is None:
                    continue
                U.append((c, (b / a) ** (1 / 30) - 1, cg - mk_c, dca_mult(ret[c], ms) / mk_d))
            if len(U) < 20:
                return None
            o = sorted(U, key=lambda x: -x[1])
            top, bot = [x[0] for x in o[:10]], [x[0] for x in o[-10:]]
            pt, pb = ew(ret, top, ms), ew(ret, bot, ms)
            pa = ew(ret, [x[0] for x in U], ms)      # 事後: 同じ業種の全部を等分（等分にしただけの効果を切り分ける）
            return {'起点': t, '業種数': len(U), '順位相関(伸び×年率の差)': round(spear([x[1] for x in U], [x[2] for x in U]), 3),
                    '上位10_年率の差(%/年)': pct(cagr_m(pt, ms) - mk_c), '上位10_積立の比': round(dca_mult(pt, ms) / mk_d, 3),
                    '下位10_年率の差(%/年)': pct(cagr_m(pb, ms) - mk_c), '下位10_積立の比': round(dca_mult(pb, ms) / mk_d, 3),
                    '事後_全業種を等分_積立の比(市場との)': round(dca_mult(pa, ms) / mk_d, 3),
                    '事後_上位10÷全業種を等分_積立の比': round(dca_mult(pt, ms) / dca_mult(pa, ms), 3),
                    '事後_上位10−全業種を等分_年率の差(%/年)': pct(cagr_m(pt, ms) - cagr_m(pa, ms)),
                    '伸び上位10': [f"{JA.get(c, c)}({pct(g, 1)}%)" for c, g, _, _ in o[:10]],
                    '伸び上位10の年率の差(%/年)': {JA.get(c, c): pct(x, 1) for c, _, x, _ in o[:10]}}
        r1 = one(True, 'be')
        if r1:
            q1rows.append(r1)
        r2 = one(False, 'be')
        if r2:
            q1rows_all.append({k: r2[k] for k in ('起点', '業種数', '順位相関(伸び×年率の差)', '上位10_年率の差(%/年)', '上位10_積立の比')})
        r3 = one(True, 'me')
        if r3:
            q1rows_me.append({k: r3[k] for k in ('起点', '業種数', '順位相関(伸び×年率の差)', '上位10_年率の差(%/年)', '上位10_積立の比')})
        # 30年で顔ぶれがどれだけ入れ替わったか
        t2 = t + 30
        small = [c for c in cols if share[c].get(t, 0) < MIN_SHARE]
        top5a = sorted(cols, key=lambda c: -share[c].get(t, 0))[:5]
        top5b = sorted(cols, key=lambda c: -share[c].get(t2, 0))[:5]
        renew.append({'起点': t, '30年後': t2,
                      '起点で0.5%未満か無かった業種が30年後に占める割合(%)': pct(sum(share[c].get(t2, 0) for c in small), 1),
                      '起点の上位5のうち30年後も上位5': len(set(top5a) & set(top5b)),
                      '起点の上位5': [f"{JA.get(c, c)} {pct(share[c].get(t, 0), 1)}%" for c in top5a],
                      '30年後の上位5': [f"{JA.get(c, c)} {pct(share[c].get(t2, 0), 1)}%" for c in top5b],
                      '起点の上位5の30年後の比重の合計(%)': pct(sum(share[c].get(t2, 0) for c in top5a), 1),
                      '起点の上位5の起点の比重の合計(%)': pct(sum(share[c].get(t, 0) for c in top5a), 1)})

    def q1sum(rows):
        if not rows:
            return None
        rc = [r['順位相関(伸び×年率の差)'] for r in rows]
        te = [r['上位10_年率の差(%/年)'] for r in rows]
        td = [r['上位10_積立の比'] for r in rows]
        return {'窓の数': len(rows), '順位相関の平均': round(S.mean(rc), 3), '順位相関が正の窓': f'{sum(x > 0 for x in rc)}/{len(rc)}',
                '上位10の年率の差の平均(%/年)': round(S.mean(te), 2), '上位10が積立で市場に勝った窓': f'{sum(x > 1 for x in td)}/{len(td)}',
                '上位10の積立の比の中央値': round(S.median(td), 3)}
    s1 = q1sum(q1rows)
    if s1['順位相関の平均'] >= 0.5 and int(s1['上位10が積立で市場に勝った窓'].split('/')[0]) >= 12 and s1['上位10の年率の差の平均(%/年)'] >= 3:
        j1 = '大きく効く'
    elif s1['順位相関の平均'] < 0.3 or s1['上位10の年率の差の平均(%/年)'] < 1.5:
        j1 = '効きは小さい'
    else:
        j1 = '中間'
    # 伸びを新しい株で賄った分（時価総額の伸び − リターン ≈ 新しい株・新規上場 − 配当）
    iss = []
    t0, t1 = 1995, 2025
    ms = months((t0 + 1) * 100 + 1, N)
    for c in cols:
        a, b = me[c].get(t0), me[c].get(t1)
        cg = cagr_m(ret[c], ms)
        if a and b and cg is not None and share[c].get(t1, 0) >= MIN_SHARE:
            meg = (b / a) ** (1 / 30) - 1
            iss.append((c, meg, cg))
    iss.sort(key=lambda x: -(x[1] - x[2]))
    pq = [r['事後_上位10÷全業種を等分_積立の比'] for r in q1rows]
    q1_post = {'全業種を等分した積立の比の中央値(市場との)': round(S.median(r['事後_全業種を等分_積立の比(市場との)'] for r in q1rows), 3),
               '上位10÷全業種を等分_積立の比の中央値': round(S.median(pq), 3),
               '上位10が全業種の等分に積立で勝った窓': f'{sum(x > 1 for x in pq)}/{len(pq)}',
               '上位10−全業種の等分_年率の差の平均(%/年)': round(S.mean(r['事後_上位10−全業種を等分_年率の差(%/年)'] for r in q1rows), 2),
               '読み方': '上位10は等分（毎月組み直し）・市場は時価加重。等分にしただけで市場に勝つ分（小さい業種・組み直しの上乗せ）を除くと、完全な予知の上乗せはこの差になる'}
    out['Q1_完全な予知'] = {
        '判定（事前登録の決まり）': j1, '主（起点で比重0.5%以上）': s1,
        '事後_等分にしただけの効果を除くと（判定に使わない）': q1_post,
        '感度_比重の下限なし': q1sum(q1rows_all), '感度_伸びを時価総額の合計で（株価を含む＝参考）': q1sum(q1rows_me),
        '窓ごと': q1rows,
        '参考_30年で業種の顔ぶれがどれだけ入れ替わったか': renew,
        '参考_1995→2025 時価総額の伸び−リターン（新しい株・新規上場−配当の目安・%/年）': [
            {'業種': JA.get(c, c), '時価総額の伸び': pct(g, 1), 'リターン': pct(r, 1), '差': pct(g - r, 1)} for c, g, r in iss[:8]] +
            [{'業種': JA.get(c, c), '時価総額の伸び': pct(g, 1), 'リターン': pct(r, 1), '差': pct(g - r, 1)} for c, g, r in iss[-5:]]}
    print('Q1', j1, s1, flush=True)

    # ───────── Q2・Q3 ─────────
    starts = list(range(1936, 1996))
    sig = {'s1 簿価の伸び上位10': [], 's2 株の勝者上位10': [], 's3 比重の記録': [], 's2r 株の勝者を5年ごとに選び直す': []}
    MAIN = ('T0 市場100%', 'T1 勝者3業種70%＋市場30%', 'T2 T1を5年ごとに選び直す', 'T3 市場50%＋勝者3業種50%',
            'T4 業種を等分（毎年1月に組み直し）', 'T5 勝者を市場の比重の1.5倍まで（毎年1月）')
    SENS = ('感度: T4 を毎月等分に戻す', '感度: T5 を毎月戻す')
    typ = {k: [] for k in MAIN + SENS}
    typ_lump = {k: [] for k in typ}
    typ_irr = {k: [] for k in typ}
    typ_irr_real = {k: [] for k in typ}
    picks = []
    sig_vs_ew = {k: [] for k in sig}          # 事後: 目印÷同じ起点の候補の全部を等分（同じ持ち方）
    ewall_vs_mkt = []
    ser = dict(ret)
    ser['_mkt'] = mkt

    def cands(t):
        return [c for c in cols if share[c].get(t, 0) >= MIN_SHARE]

    def winners(t, k):
        cs = [(c, trailing_excess(ret, mkt, c, t)) for c in cands(t)]
        cs = [x for x in cs if x[1] is not None]
        return [c for c, _ in sorted(cs, key=lambda x: -x[1])[:k]]

    for t in starts:
        ms = months((t + 1) * 100 + 1, N)
        if ms[-1] > endm:
            continue
        mk_d, mk_c = dca_mult(mkt, ms), cagr_m(mkt, ms)
        C = cands(t)
        # s1
        g1 = [(c, (be[c][t] / be[c][t - 10]) ** 0.1 - 1) for c in C if be[c].get(t) and be[c].get(t - 10)]
        s1set = [c for c, _ in sorted(g1, key=lambda x: -x[1])[:10]]
        s2set = winners(t, 10)
        s3set = [c for c in C if min(share[c]) <= t - 10 and share[c].get(t, 0) >= max(v for y, v in share[c].items() if y <= t)]
        res = {}
        for lab, st in (('s1 簿価の伸び上位10', s1set), ('s2 株の勝者上位10', s2set), ('s3 比重の記録', s3set)):
            if not st:
                res[lab] = None
                continue
            p = ew(ret, st, ms)
            res[lab] = dca_mult(p, ms) / mk_d if dca_mult(p, ms) else None
        # s2r
        p = {}
        for k in range(6):
            tt = t + 5 * k
            st = winners(tt, 10)
            for m in months((tt + 1) * 100 + 1, 60):
                v = [ret[c][m] for c in st if m in ret[c]]
                if v:
                    p[m] = sum(v) / len(v)
        res['s2r 株の勝者を5年ごとに選び直す'] = dca_mult(p, ms) / mk_d if dca_mult(p, ms) else None
        for lab in sig:
            sig[lab].append((t, res[lab]))
        pe = ew(ret, C, ms)
        de = dca_mult(pe, ms)
        ewall_vs_mkt.append((t, de / mk_d if de else None))
        for lab in sig:
            sig_vs_ew[lab].append((t, res[lab] * mk_d / de if (res[lab] and de) else None))
        # Q3
        w3 = winners(t, 3)
        pw = ew(ret, w3, ms)
        T = {}
        T['T0 市場100%'] = {m: mkt[m] for m in ms}
        T['T1 勝者3業種70%＋市場30%'] = mix([(0.7, pw), (0.3, mkt)], ms)
        p2 = {}
        for k in range(6):
            tt = t + 5 * k
            st = winners(tt, 3)
            sub = months((tt + 1) * 100 + 1, 60)
            e = ew(ret, st, sub)
            for m in sub:
                if m in e and m in mkt:
                    p2[m] = 0.7 * e[m] + 0.3 * mkt[m]
        T['T2 T1を5年ごとに選び直す'] = p2
        T['T3 市場50%＋勝者3業種50%'] = mix([(0.5, pw), (0.5, mkt)], ms)
        p4, p4m = {}, {}
        for y in range(t + 1, t + 31):
            st = cands(y - 1)
            p4.update(hold_year({c: 1.0 for c in st}, ret, y))
            p4m.update(ew(ret, st, months(y * 100 + 1, 12)))
        T['T4 業種を等分（毎年1月に組み直し）'] = p4
        T['感度: T4 を毎月等分に戻す'] = p4m
        p5, p5m = {}, {}
        for y in range(t + 1, t + 31):
            wts = {c: min(0.7 / 3, 1.5 * share[c].get(y - 1, 0)) for c in w3}
            wm = 1 - sum(wts.values())
            p5.update(hold_year({**wts, '_mkt': wm}, ser, y))
            for m in months(y * 100 + 1, 12):
                if m not in mkt:
                    continue
                v = wm * mkt[m]
                miss = 0.0
                for c, w in wts.items():
                    if m in ret[c]:
                        v += w * ret[c][m]
                    else:
                        miss += w
                p5m[m] = v + miss * mkt[m]
        T['T5 勝者を市場の比重の1.5倍まで（毎年1月）'] = p5
        T['感度: T5 を毎月戻す'] = p5m
        for lab, s in T.items():
            d = dca_mult(s, ms)
            typ[lab].append((t, d / mk_d if d else None))
            cg = cagr_m(s, ms)
            typ_lump[lab].append((t, None if cg is None else cg - mk_c))
            typ_irr[lab].append((t, dca_irr(s, ms)))
            typ_irr_real[lab].append((t, dca_irr(real(s), ms)))
        picks.append({'起点': t, '勝者3業種': [JA.get(c, c) for c in w3], 's1': [JA.get(c, c) for c in s1set[:5]],
                      's3（比重の記録）': [JA.get(c, c) for c in s3set]})

    def halves(lst):
        return {'前半(起点1936〜1965)': [v for t, v in lst if t <= 1965], '後半(1966〜1995)': [v for t, v in lst if t >= 1966]}
    q2 = {}
    for lab, lst in sig.items():
        sm = summ([v for _, v in lst], halves(lst))
        if sm is None:
            q2[lab] = None
            continue
        if sm['中央値'] > 1.05 and sm['市場に勝った割合'] >= 0.6 and sm['中央値_前半(起点1936〜1965)'] > 1 and sm['中央値_後半(1966〜1995)'] > 1:
            jj = '効く'
        elif sm['中央値'] < 1.0 and sm['市場に勝った割合'] <= 0.4:
            jj = '逆に効く（避けるべき目印）'
        else:
            jj = 'はっきりしない'
        q2[lab] = dict(判定=jj, **sm)
    q2post = {'候補の全部を等分（同じ持ち方）÷市場': summ([v for _, v in ewall_vs_mkt], halves(ewall_vs_mkt))}
    for lab, lst in sig_vs_ew.items():
        q2post[f'{lab}÷候補の全部を等分'] = summ([v for _, v in lst], halves(lst))
    out['Q2_その時に分かる目印'] = {'目印ごと（30年積立の市場との比）': q2,
                              '事後_等分にしただけの効果を除くと（判定に使わない）': q2post,
                              '起点ごとの選ばれた業種（先頭の数年と5年ごと）': [p for p in picks if p['起点'] % 5 == 0]}
    print('Q2', {k: (v or {}).get('判定') for k, v in q2.items()}, flush=True)
    print('Q2事後', {k: (v or {}).get('中央値') for k, v in q2post.items()}, flush=True)

    q3 = {}
    for lab in typ:
        sm = summ([v for _, v in typ[lab]], halves(typ[lab]))
        lumps = [v for _, v in typ_lump[lab] if v is not None]
        irr = sorted(v for _, v in typ_irr[lab] if v is not None)
        irrr = sorted(v for _, v in typ_irr_real[lab] if v is not None)
        sm['一括の年率の差の中央値(%/年)'] = pct(S.median(lumps))
        sm['30年積立の年率_中央(%)'] = pct(S.median(irr))
        sm['30年積立の年率_最悪(%)'] = pct(irr[0])
        sm['30年積立の実質の年率_中央(%)'] = pct(S.median(irrr))
        sm['30年積立の実質の年率_最悪(%)'] = pct(irrr[0])
        sm['実質の年率がマイナスの起点'] = sum(v < 0 for v in irrr)
        q3[lab] = sm
    ok = [k for k in MAIN if q3[k]['中央値'] >= 0.98]
    best = max(ok, key=lambda k: (q3[k]['下位10%点'], q3[k]['中央値']))
    oks = [k for k in MAIN if q3[k]['中央値'] >= 0.98 and not k.startswith(('T4', 'T5'))] + \
          [k for k in SENS if q3[k]['中央値'] >= 0.98]
    best_s = max(oks, key=lambda k: (q3[k]['下位10%点'], q3[k]['中央値'])) if oks else None
    out['Q3_30年の構造の型'] = {'型ごと': {k: q3[k] for k in MAIN}, '判定（事前登録の決まり）': f'30年に強い型＝{best}（中央値0.98以上の型の中で下位10%点が最も高い）',
                           '30年に強い型': best,
                           '感度（T4・T5 を毎月組み直しで測った版）': {k: q3[k] for k in SENS},
                           '感度での30年に強い型': best_s,
                           '持ち方の注記': 'T1・T3 は選んだ業種を固定して毎月 目標の比へ組み直す（Q2 の持ち方と同じ）。T4・T5 は文言どおり毎年1月に組み直し、年の中は持ちっぱなし。'
                                        '最初に回した版は T4・T5 も毎月組み直していた（文言とずれる）ので、文言どおりに直し、元の版は感度に残した。'
                                        'T5 は勝者の業種の取り分（70%÷3）を市場の比重の1.5倍までに抑える読み（市場の中の同じ業種は数えない）'}
    print('Q3', best, {k: (q3[k]['中央値'], q3[k]['下位10%点']) for k in q3}, flush=True)

    # ───────── Q3b 今の形の写し（参考） ─────────
    tech = G.french_tech()
    dfn = capw(ret, capm, ['Aero', 'Guns'], sorted(mkt))
    chips = ret['Chips']
    allm = sorted(mkt)
    ndx = mix([(0.65, tech), (0.35, mkt)], allm)
    now = mix([(0.50, ndx), (0.20, chips), (0.15, dfn), (0.15, mkt)], allm)
    forms = {'今の形の写し（NASDAQ100 50・SMH 20・ITA 15・個別株 15）': now,
             '芯30（今の形×0.7＋市場0.3）': mix([(0.7, now), (0.3, mkt)], allm),
             '芯50（今の形×0.5＋市場0.5）': mix([(0.5, now), (0.5, mkt)], allm),
             'テックだけ': tech}
    q3b = {}
    for lab, s in forms.items():
        rows = []
        irr, irrr = [], []
        for t in range(1965, 1996):
            ms = months((t + 1) * 100 + 1, N)
            if ms[-1] > endm:
                continue
            d = dca_mult(s, ms)
            rows.append((t, d / dca_mult(mkt, ms) if d else None))
            irr.append(dca_irr(s, ms))
            irrr.append(dca_irr(real(s), ms))
        sm = summ([v for _, v in rows], {'起点1965〜1979': [v for t, v in rows if t <= 1979], '起点1980〜1995': [v for t, v in rows if t >= 1980]})
        irr = sorted(x for x in irr if x is not None)
        irrr = sorted(x for x in irrr if x is not None)
        sm['30年積立の年率_中央(%)'] = pct(S.median(irr))
        sm['30年積立の年率_最悪(%)'] = pct(irr[0])
        sm['30年積立の実質の年率_最悪(%)'] = pct(irrr[0])
        sm['起点ごとの比（5年ごと）'] = {str(t): round(v, 3) for t, v in rows if t % 5 == 0 and v is not None}
        q3b[lab] = sm
    mrows = []
    for t in range(1965, 1996):
        ms = months((t + 1) * 100 + 1, N)
        mrows.append(dca_irr(mkt, ms))
    q3b['参考_市場の30年積立の年率（起点1965〜1995）'] = {'中央(%)': pct(S.median(mrows)), '最悪(%)': pct(min(mrows))}
    out['Q3b_今の形の写し（参考・判定に使わない）'] = q3b
    print('Q3b', {k: (v.get('中央値'), v.get('下位10%点'), v.get('最悪')) for k, v in q3b.items() if isinstance(v, dict) and '中央値' in v}, flush=True)

    # ───────── 事後（判定に使わない）: 等分の上乗せは今も続いているか・実在の器では ─────────
    # P2 全期間の T4（毎年1月に組み直し）を作り、10年・20年の積立の窓を起点の年代ごとに市場と比べる
    t4all = {}
    for y in range(1927, endm // 100 + 1):
        st = cands(y - 1)
        if st:
            t4all.update(hold_year({c: 1.0 for c in st}, ret, y))

    def roll(a, b, n, starts):
        last = min(max(a), max(b))
        res = []
        for s in starts:
            ms = months(s, n)
            if ms[-1] > last:
                continue
            x, z = dca_mult(a, ms), dca_mult(b, ms)
            if x and z:
                res.append((s, x / z))
        return res
    era = {}
    for n, lab in ((120, '10年の積立'), (240, '20年の積立')):
        by = {}
        for s, v in roll(t4all, mkt, n, [y * 100 + 1 for y in range(1927, 2026)]):
            by.setdefault(f'{s // 100 // 10 * 10}年代に始めた', []).append(v)
        era[lab] = {k: {'窓': len(v), '中央値': round(S.median(v), 3), '勝った割合': round(sum(x > 1 for x in v) / len(v), 2)}
                    for k, v in by.items()}
    # P3 実在の器: 9つの業種の SPDR を等分（毎年1月に組み直し）と RSP（S&P500 の等分）を SPY と比べる
    p3 = {}
    try:
        spdr = ['XLB', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLU', 'XLV', 'XLY']
        vs = {k: M.yahoo(k) for k in spdr + ['SPY', 'RSP']}
        sec = {}
        for y in range(1999, 2027):
            if all(y * 100 + 1 in vs[k] for k in spdr):
                sec.update(hold_year({k: 1.0 for k in spdr}, vs, y))
        for lab, a, b in (('9業種の SPDR を等分（毎年1月）÷SPY', sec, vs['SPY']), ('RSP（S&P500 の等分）÷SPY', vs['RSP'], vs['SPY']),
                          ('同じ期間の French: 49業種を等分（T4）÷市場', {m: v for m, v in t4all.items() if m >= 199901}, mkt)):
            common = sorted(set(a) & set(b))
            d = {'期間': f'{common[0]}〜{common[-1]}',
                 '一括の年率の差(%/年)': pct(cagr_m(a, common) - cagr_m(b, common))}
            for n, nl in ((120, '10年'), (180, '15年'), (240, '20年')):
                rr = roll(a, b, n, common)
                v = [x for _, x in rr]
                if v:
                    d[f'{nl}の積立'] = {'窓': len(v), '中央値': round(S.median(v), 3), '勝った割合': round(sum(x > 1 for x in v) / len(v), 2),
                                     '最悪': round(min(v), 3), '最良': round(max(v), 3)}
            for y0 in (2000, 2010, 2016):
                cm = [m for m in common if m >= y0 * 100 + 1]
                d[f'{y0}年1月〜の一括の年率の差(%/年)'] = pct(cagr_m(a, cm) - cagr_m(b, cm))
            p3[lab] = d
    except Exception as e:  # noqa
        p3 = {'取得失敗': str(e)}
    out['事後_等分の上乗せは今も続いているか（判定に使わない）'] = {
        'P2 French の49業種を等分（毎年1月）÷市場・起点の年代ごと': era,
        'P3 実在の器（Yahoo の配当込み・ドル建て・費用はそれぞれの経費率の後）': p3,
        '読み方': '構造の型の一番（T4 業種を等分）は、毎年1月に等分へ戻すことで小さい業種と下げた業種を買い足す形。'
                 'これが2000年以降も効いたか、楽天で買える器で同じことができたかを見る。30年の窓は器の記録（27年）では作れない'}
    print('事後 P2', era, flush=True)
    print('事後 P3', json.dumps(p3, ensure_ascii=False)[:1500], flush=True)

    # ───────── Q5 今の保有の更新力（記述） ─────────
    ex = json.load(open(os.path.join(BASE, 'out', 'industry_exposure.json')))
    def g5(d):
        return {k: d.get(k) for k in ('記録の二業種(ソフトウェア＋半導体・電子部品)_French寄せ', 'テック三業種(ソフトウェア＋半導体・電子部品＋コンピュータ機器)(%)',
                                      '半導体の連鎖(装置・材料を含む・lookthrough の SEMI)(%)', '業種(French寄せ)')}
    out['Q5_今の保有の更新力（記述）'] = {
        '米国市場全体（2025年末）': ex.get('米国市場全体(French・2025年末)'),
        '今の保有': g5(ex.get('今の保有') or {}), '目標の姿（industry_exposure の日付の写真）': g5(ex.get('目標の姿') or {}),
        '器ごとの更新のしかた': {
            'NASDAQ100（iFreeNEXT・QQQM）': 'ナスダック上場の非金融の時価総額上位100社。毎年12月に入れ替え＝伸びた会社は自然に入るが、金融とナスダック以外の会社は入らない',
            'SMH': '米国上場の半導体25社。業種は固定＝半導体が衰えても入れ替わらない',
            'ITA': '米国の航空宇宙・防衛。業種は固定',
            '個別株（門）': '四関門で毎年見直す。業種は選ばない（質で選ぶ）',
            '市場全体（S&P500・全米・全世界）': '伸びた業種・会社が時価総額の分だけ自然に入る＝予想しなくても次の勝者を持つ'},
        'industry_exposure の日付': ex.get('generated')}
    out['⚠'] = json.load(open(os.path.join(BASE, 'out', 'future30_prereg.json')))['注意（測る前から分かっている限界）']
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('書いた', OUT)


if __name__ == '__main__':
    main()
