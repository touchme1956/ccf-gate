#!/usr/bin/env python3
"""night/edge/fam_hi52.py — 系統 hi52（第6回）: 52週高値に近い株の買いだけ vs 米国市場

事前登録 out/edge_prereg_r6.json の round6_families.hi52（線・費用・相手・期間は out/edge_prereg.json と同じ）。
  ・特徴 = JKP の prc_highprc_252d（株価 ÷ 直近252営業日の最高値。1に近いほど52週高値に近い）。George & Hwang 2004。
  ・良い側 = 高値に近い側。確かめ方（directions()）: (a) JKP の因子 = direction ×（'3.0' − '1.0'）なので、
    選定期間（〜2000-12）の米国で 因子 と '3.0'−'1.0' の相関の符号 (b) 選定期間の三分位の平均の並び。
    JKP の三分位は特徴の小さい順に '1.0'/'2.0'/'3.0' ＝ '3.0' が「高値に近い」。
  ・JKP の三分位の 'ret' は米ドルの**超過リターン**（米国の短期金利を引いたもの）→ 総リターン = ret + French RF
  ・月 m の組は JKP が m−1 月末の特徴（m−1 月末までの252営業日の最高値）で組んだ三分位。銘柄数 n も組んだ時点の数
  ・費用: 片道の回転100%につき 0.25%。回転は 200%/年（事前登録 r6 の価格の信号の置き値）＋ 二つの三分位を等分に持つ変種の戻し
  ・他の市場: JKP の先進国22か国の同じ特徴・同じ側・同じ重み。国の相手は JKP の国の mkt（vw＝上限なしの時価加重・米ドル超過）＋ French RF

使い方: python3 night/edge/fam_hi52.py          → 変種の表（選定の段・2000-12 まで）
        python3 night/edge/fam_hi52.py --save   → 選んで凍結（out/edge/spec_hi52.json）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h
import csv, io, math, random, statistics as S, zipfile
from concurrent.futures import ThreadPoolExecutor

FAMILY = {
    'key': 'hi52',
    'name': '52週高値に近い株の買いだけ（JKP prc_highprc_252d の高値に近い三分位）',
    'implement': ('楽天証券の米国株（個別株。NISA 成長投資枠で買える・レバレッジではない）で、米国上場の大型・中型株を'
                  '「株価 ÷ 直近52週の最高値」で並べ、高値にいちばん近い3分の1を時価加重（上限つきなら1社の重みを抑える）で持ち、'
                  '毎月入れ替える。価格の信号なので回転が大きい（置き値 200%/年）。銘柄数は数百になり個人には重いので、実際には'
                  '時価総額の大きい順に数十社へ絞る近似になる。52週高値への近さそのものを選ぶ ETF は楽天の一覧に見当たらない'
                  '（勢いの ETF〔MTUM・楽天で買える〕は12か月の勢いで選ぶ別の信号で、高値への近さとは重なるが同じではない）。'
                  '課税口座なら毎月の入れ替えで売却益に税が掛かる（主の判定には入れない）'),
}

CHAR = 'prc_highprc_252d'
COST = 0.0025                     # 片道の回転100%につき（事前登録: 個別株の組）
TURN_ANN = 2.0                    # 片道の回転（年）。事前登録 r6 の価格の信号の置き値 200%/年
MIN_N = 50                        # 米国: 三分位の銘柄数がこれ未満の月は使わない
MIN_N_REPL = 20                   # 他の国
REPL = ['jpn', 'gbr', 'deu', 'fra', 'can', 'aus', 'che', 'swe', 'nld', 'ita', 'esp', 'hkg', 'sgp', 'dnk', 'nor', 'bel',
        'fin', 'aut', 'irl', 'prt', 'nzl', 'isr']          # 事前登録 r6 の先進国22か国
JKP = 'https://jkpfactors-data.s3.amazonaws.com/public/'
FAR, MID, NEAR = '1.0', '2.0', '3.0'   # 仮の名札（directions() が確かめる。'3.0' = 特徴が大きい＝高値に近い）

_MEMO = {}


# ───────────────────────── 読み込み ─────────────────────────
def _counts(region, w):
    """三分位の銘柄数 n（h.jkp は返さないので、同じキャッシュを h.cached で読み h.guard を通す）"""
    url = f'{JKP}portfolios/%5B{region}%5D_%5B{CHAR}%5D_%5Bmonthly%5D_%5B{w}%5D.zip'
    z = zipfile.ZipFile(io.BytesIO(h.cached(f'jkp_portfolio_{region}_{CHAR}_{w}.zip', url)))
    out = {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        try:
            out.setdefault(x['pf'], {})[int(x['date'][:4]) * 100 + int(x['date'][5:7])] = int(float(x['n']))
        except (TypeError, ValueError, KeyError):
            continue
    return {k: h.guard(v) for k, v in out.items()}


def legs(region, w):
    """→ {三分位: (超過リターン {m}, 銘柄数 {m})}。取れなければ {}"""
    k = (region, w)
    if k not in _MEMO:
        try:
            p = h.jkp(region, CHAR, 'portfolio', w)
            n = _counts(region, w)
            _MEMO[k] = {s: (p.get(s, {}), n.get(s, {})) for s in (FAR, MID, NEAR)}
        except Exception:
            _MEMO[k] = {}
    return _MEMO[k]


# ───────────────────────── 規則 ─────────────────────────
def build(spec, region, rf, min_n):
    """spec['sides'] の三分位を等分に持つ（1つなら素通し）→ (総リターン {m}, 片道の回転 {m})
    月 m に持つかどうかは、月 m の組（m−1 月末に組まれたもの）の銘柄数 n だけで決まる。等分の組は毎月戻す。
    データから何も推定しない（側と重みは spec の定数）"""
    L = legs(region, spec['w'])
    sides = spec['sides']
    if not L or any(s not in L or not L[s][0] for s in sides):
        return {}, {}
    months = sorted(set.intersection(*[set(L[s][0]) for s in sides]))
    ret, tv, prev = {}, {}, None
    tw = {s: 1 / len(sides) for s in sides}
    turn = spec.get('turn_ann', TURN_ANN)
    for m in months:
        if m not in rf or any(L[s][1].get(m, 0) < min_n for s in sides):
            prev = None
            continue
        reb = 0.0 if prev is None else 0.5 * sum(abs(prev.get(s, 0.0) - tw[s]) for s in tw)
        ret[m] = sum(tw[s] * L[s][0][m] for s in sides) + rf[m]
        tv[m] = turn / 12 + reb
        g = {s: tw[s] * (1 + L[s][0][m] + rf[m]) for s in sides}
        tot = sum(g.values())
        prev = {s: v / tot for s, v in g.items()} if tot > 0 else None
    return ret, tv


def run(spec):
    mk, rf = h.us_market()
    ret, tv = build(spec, 'usa', rf, spec.get('min_n', MIN_N))
    out = {'ret': ret, 'bench': mk, 'rf': rf, 'turnover': tv, 'cost': COST, 'markets': {}}
    regions = spec.get('replicate', [])

    def one(c):
        try:
            jm = h.jkp(c, 'mkt', 'factor', 'vw')          # その国の市場（上限なしの時価加重・米ドルの超過）
        except Exception:
            return c, None
        bench = {m: v + rf[m] for m, v in jm.items() if m in rf}
        r, t = build(spec, c, rf, spec.get('min_n_repl', MIN_N_REPL))
        r = {m: v for m, v in r.items() if m in bench}
        return c, ({'ret': r, 'bench': bench, 'rf': rf, 'turnover': {m: t[m] for m in r}, 'cost': COST}
                   if len(r) >= 24 and bench else None)
    with ThreadPoolExecutor(8) as ex:
        for c, x in ex.map(one, regions):
            if x:
                out['markets'][c] = x
    return out


# ───────────────────────── 選定（2000-12 まで） ─────────────────────────
def _corr(a, b):
    ma, mb = S.mean(a), S.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def directions():
    """良い側の確かめ: (a) JKP 因子（予言の向き済み）と '3.0'−'1.0' の相関の符号 (b) 三分位の平均の並び（選定期間・vw_cap / vw）"""
    assert h.PHASE == 'select'
    out = {}
    for w in ('vw_cap', 'vw'):
        L = legs('usa', w)
        f = h.jkp('usa', CHAR, 'factor', w)
        ms = sorted(set(f) & set(L[FAR][0]) & set(L[NEAR][0]))
        r = _corr([f[m] for m in ms], [L[NEAR][0][m] - L[FAR][0][m] for m in ms])
        means = {s: round(S.mean(L[s][0][m] for m in ms) * 1200, 2) for s in (FAR, MID, NEAR)}
        out[w] = {'corr_factor_vs_3minus1': round(r, 4), 'months': len(ms), 'from': ms[0], 'to': ms[-1],
                  'mean_excess_ann_by_tercile': means,
                  'good_side': NEAR if r > 0 else FAR}
    return out


def variants():
    """成績を見る前に決めた変種（scratchpad の plan_hi52.md どおり）→ [(名前, spec, 選べるか)]"""
    V = []
    for w in ('vw_cap', 'vw'):
        V.append((f'高値に近い三分位・{w}', {'w': w, 'sides': [NEAR]}, True))
    for w in ('vw_cap', 'vw'):
        V.append((f'高値から遠い三分位を避ける（中＋近を等分）・{w}', {'w': w, 'sides': [MID, NEAR]}, True))
    for w in ('vw_cap', 'vw'):
        V.append((f'高値から遠い三分位・{w}（参考・向きの確認）', {'w': w, 'sides': [FAR]}, False))
    return V


def beta(ret, mk, rf, a=None, b=None):
    ms = [m for m in sorted(set(ret) & set(mk)) if (a is None or m >= a) and (b is None or m <= b)]
    x = [mk[m] - rf[m] for m in ms]
    y = [ret[m] - rf[m] for m in ms]
    mx, my = S.mean(x), S.mean(y)
    bt = sum((p - mx) * (q - my) for p, q in zip(x, y)) / sum((p - mx) ** 2 for p in x)
    al = (my - bt * mx) * 1200
    return round(bt, 2), round(al, 2)


SUBS = (('〜1962', None, 196212), ('1963-2000', 196301, 200012), ('1963-1981', 196301, 198112), ('1982-2000', 198201, 200012))


def select():
    assert h.PHASE == 'select'
    mk, rf = h.us_market()
    capm = {m: v + rf[m] for m, v in h.jkp('usa', 'mkt', 'factor', 'vw_cap').items() if m in rf}
    rows = []
    for name, sp, ok in variants():
        r, tv = build(sp, 'usa', rf, MIN_N)
        st = h.stats(r, mk, rf, b=h.SEL_END, turnover=tv, cost=COST)
        sub = {}
        for lab, a, b in SUBS:
            s2 = h.stats(r, mk, rf, a=a, b=min(b, h.SEL_END), turnover=tv, cost=COST)
            sub[lab] = {'excess': s2['excess'], 't': s2['t']} if s2 else None
        st_cap = h.stats(r, capm, rf, b=h.SEL_END, turnover=tv, cost=COST)
        st_gross = h.stats(r, mk, rf, b=h.SEL_END)
        bt, al = beta(r, mk, rf, b=h.SEL_END)
        rows.append({'name': name, 'eligible': ok, 'spec': sp, 'stats': st, 'sub': sub, 'beta': bt, 'alpha_capm_gross': al,
                     'excess_before_cost': st_gross['excess'] if st_gross else None,
                     'ex_vs_jkp_capped_mkt': st_cap['excess'] if st_cap else None,
                     'turnover_yr': round(sum(tv.values()) / len(tv) * 12, 3) if tv else None})
        print(f"{'○' if ok else '参'} {name:34} {st['from']}〜 ex{st['excess']:6} t{st['t']:6} (NW{st['t_nw']}) 費用前{rows[-1]['excess_before_cost']} "
              f"vol{st['vol']}/{st['bench_vol']} dd{st['maxdd']}/{st['bench_maxdd']} β{bt} α{al} 回転{rows[-1]['turnover_yr']} "
              f"対capmkt {rows[-1]['ex_vs_jkp_capped_mkt']} 10年窓{st['roll10_win']}  部分 {sub}")
    return rows


# ───────────────────────── 先読みの検査 ─────────────────────────
def lookahead_test(spec):
    """(1) 切り詰め: 脚・銘柄数・RF を月 X で切って作り直しても、X までの規則のリターンと回転が完全一致（未来のデータを使っていない）
       (2) 未来の毒: X より後の脚のリターン・銘柄数・RF を乱数に置き換えても X までのリターンと回転は不変、後ろは変わる（検査が空回りしていない）
       (3) 1か月ずらし: X より後の脚の値を1か月後ろへずらして壊しても X までは不変
       (4) 月合わせ: 規則の月 m の総リターン − 月 m の RF = 月 m の JKP の脚の超過（等分なら毎月戻した重み）の食い違い
       (5) 側と重みは spec の定数（データから再推定しない）"""
    mk, rf = h.us_market()
    key = ('usa', spec['w'])
    legs('usa', spec['w'])
    saved = {k: v for k, v in _MEMO.items()}
    full, ftv = build(spec, 'usa', rf, spec.get('min_n', MIN_N))
    cuts = [194012, 196212, 197512, 198512, 199512, 199912]
    res = {'cuts': cuts}
    rnd = random.Random(20260928)
    try:
        ok1 = ok2 = ok3 = True
        bite2 = bite3 = True
        for X in cuts:
            base = saved[key]
            # (1) 切り詰め
            _MEMO[key] = {s: ({m: v for m, v in r_.items() if m <= X}, {m: v for m, v in n_.items() if m <= X}) for s, (r_, n_) in base.items()}
            rfX = {m: v for m, v in rf.items() if m <= X}
            part, ptv = build(spec, 'usa', rfX, spec.get('min_n', MIN_N))
            exp = {m for m in full if m <= X}
            ok1 &= set(part) == exp and all(abs(part[m] - full[m]) < 1e-15 and abs(ptv[m] - ftv[m]) < 1e-15 for m in part)
            # (2) 未来の毒（リターン・銘柄数・RF）
            _MEMO[key] = {s: ({m: (v if m <= X else rnd.uniform(-0.3, 0.3)) for m, v in r_.items()},
                              {m: (v if m <= X else rnd.randint(0, 400)) for m, v in n_.items()}) for s, (r_, n_) in base.items()}
            rfP = {m: (v if m <= X else rnd.uniform(0, 0.02)) for m, v in rf.items()}
            part, ptv = build(spec, 'usa', rfP, spec.get('min_n', MIN_N))
            ok2 &= all(m in part and abs(part[m] - full[m]) < 1e-15 and abs(ptv[m] - ftv[m]) < 1e-15 for m in full if m <= X)
            bite2 &= any(abs(part.get(m, 9) - full[m]) > 1e-9 for m in full if m > X) if any(m > X for m in full) else True
            # (3) 1か月ずらし
            _MEMO[key] = {s: ({m: (v if m <= X else r_.get(h.add_months(m, -1), v)) for m, v in r_.items()},
                              {m: (v if m <= X else n_.get(h.add_months(m, -1), v)) for m, v in n_.items()}) for s, (r_, n_) in base.items()}
            part, ptv = build(spec, 'usa', rf, spec.get('min_n', MIN_N))
            ok3 &= all(m in part and abs(part[m] - full[m]) < 1e-15 for m in full if m <= X)
            bite3 &= any(abs(part.get(m, 9) - full[m]) > 1e-12 for m in full if m > X) if any(m > X for m in full) else True
        res.update({'truncate': ok1, 'poison_future': ok2, 'poison_bites': bite2, 'shift_future': ok3, 'shift_bites': bite3})
    finally:
        _MEMO[key] = saved[key]
    # (4) 月合わせ
    L = legs('usa', spec['w'])
    sides = spec['sides']
    d, prev = 0.0, None
    ms = sorted(full)
    for m in ms:
        exr = sum(L[s][0][m] for s in sides) / len(sides)
        d = max(d, abs(full[m] - rf[m] - exr))
    res['month_align_maxdiff'] = d
    res['sides_constant'] = bool(spec.get('sides')) and all(s in (FAR, MID, NEAR) for s in spec['sides'])
    res['n_months'] = len(full)
    res['ok'] = ok1 and ok2 and bite2 and ok3 and bite3 and d < 1e-12 and res['sides_constant']
    return res


# ───────────────────────── 凍結 ─────────────────────────
def main(save=False):
    D = directions()
    print('向き:', D)
    rows = select()
    elig = [r for r in rows if r['eligible'] and r['stats'] and r['stats']['excess'] >= 1.0]
    if elig:
        best = max(elig, key=lambda r: r['stats']['t'])
        how = '事前登録どおり（選定期間の費用後の超過 +1%/年以上の中で t が最大）'
    else:
        cand = [r for r in rows if r['eligible'] and r['spec']['sides'] == [NEAR]]
        best = max(cand, key=lambda r: r['stats']['t'])
        how = ('どの変種も選定期間で +1%/年 に届かなかった。系統の定義（事前登録 r6『高値に近い側』）どおりの一つの三分位の変種の中で'
               ' t が最大のものを選んだ（線に届かないことを承知で、いちばん筋の良い一つ）')
    spec = dict(best['spec'])
    spec.update({'char': CHAR, 'min_n': MIN_N, 'min_n_repl': MIN_N_REPL, 'replicate': REPL, 'turn_ann': TURN_ANN,
                 'side_note': "'3.0' = prc_highprc_252d（株価÷直近252営業日の最高値）が大きい＝52週高値に近い三分位。'2.0' は真ん中"})
    la = lookahead_test(spec)
    print('先読みの検査:', la)
    assert la['ok'], la
    r = run(spec)
    st = h.stats(r['ret'], r['bench'], r['rf'], b=h.SEL_END, turnover=r['turnover'], cost=r['cost'])
    mkt_sel = {}
    for c, x in r['markets'].items():
        s2 = h.stats(x['ret'], x['bench'], x['rf'], b=h.SEL_END, turnover=x['turnover'], cost=x['cost'])
        if s2:
            mkt_sel[c] = {'from': s2['from'], 'years': s2['years'], 'excess': s2['excess'], 't': s2['t']}
    print('選んだ:', best['name'], how)
    print('選定期間:', st)
    print('他の市場（選定期間・参考）:', mkt_sel)
    if not save:
        return best, st, rows, D, mkt_sel
    return freeze(best, how, spec, st, rows, D, mkt_sel, la, r)


def freeze(best, how, spec, st, rows, D, mkt_sel, la, r):
    tbl = [{'name': x['name'], 'eligible': x['eligible'], 'from': x['stats']['from'], 'excess': x['stats']['excess'],
            't': x['stats']['t'], 't_nw': x['stats']['t_nw'], 'excess_before_cost': x['excess_before_cost'],
            'vol': x['stats']['vol'], 'maxdd': x['stats']['maxdd'],
            'beta': x['beta'], 'alpha_capm_gross': x['alpha_capm_gross'], 'ex_vs_jkp_capped_mkt': x['ex_vs_jkp_capped_mkt'],
            'sub_periods': x['sub'], 'turnover_yr': x['turnover_yr']} for x in rows]
    sub = best['sub']
    by = {x['name']: x for x in rows}
    pos = sum(1 for v in mkt_sel.values() if v['excess'] > 0)
    others = '；'.join(f"{x['name']} {x['stats']['excess']:+}%/年（t {x['stats']['t']}）" for x in rows if x is not best)
    subtxt = '・'.join(f"{k} {v['excess']:+}%/年（t {v['t']}）" for k, v in sub.items() if v)
    dv = D[spec['w']]
    rationale = (
        '【規則】米国上場株を「株価 ÷ 直近252営業日の最高値」（JKP の prc_highprc_252d）で三分位に分け、'
        f"{best['name']} を買いだけで持つ。組は JKP が毎月 m−1 月末に組んだものをそのまま使い、月 m のリターンを取る。"
        '【なぜ】George & Hwang 2004（Journal of Finance）: 52週高値に近い株はその後も市場に勝ち、この効きは12か月の勢い（Jegadeesh & Titman 1993）'
        'より強く、長く反転しにくい。経済的な理由は「係留（anchoring）」——投資家は52週高値を錨にして、高値に近づいた株への良い知らせを'
        '織り込むのを控える（高値を抜けるのを怖がる）ので、良い知らせの価格への反映が遅れ、その遅れが後から戻る。遠い側は逆に悪い知らせの反映が遅れる。'
        'この説明は2001年より前の係留の研究（Tversky & Kahneman 1974）と勢いの研究に根があり、論文自体は2004年（データは1963〜2001）。'
        f"【向きの確かめ】JKP の因子（予言の向き済み）と '3.0'−'1.0' の相関は {dv['corr_factor_vs_3minus1']}（{dv['from']}〜{dv['to']}・{dv['months']}か月）＝"
        f"'3.0'（高値に近い）が良い側。選定期間の三分位の平均の超過（年率・費用前・対 短期金利）は 遠い/中/近い = "
        f"{dv['mean_excess_ann_by_tercile']['1.0']} / {dv['mean_excess_ann_by_tercile']['2.0']} / {dv['mean_excess_ann_by_tercile']['3.0']}%。"
        f"【選定期間 {st['from']}〜{st['to']}（{st['years']}年）】費用後（回転 {TURN_ANN*100:.0f}%/年 × 0.25% を引いた後）の年率 {st['cagr']}% 対 French 米国市場 {st['bench_cagr']}%、"
        f"超過 {st['excess']:+}%/年、t {st['t']}（Newey-West {st['t_nw']}）、費用前の超過 {best['excess_before_cost']:+}%/年、"
        f"ぶれ {st['vol']}% 対 {st['bench_vol']}%、最大下落 {st['maxdd']}% 対 {st['bench_maxdd']}%、転がる10年で勝った窓 {st['roll10_win']}。"
        f"市場に対するβ {best['beta']}・CAPM のα（費用前）{best['alpha_capm_gross']:+}%/年。部分期間: {subtxt}。"
        f"JKP の上限つき市場（vw_cap）に対しては {best['ex_vs_jkp_capped_mkt']:+}%/年。"
        f"【他の変種】{others}。"
        f"【選び方】{how}。"
        f"【他の市場（選定期間・参考）】先進国22か国のうち選定期間に測れた {len(mkt_sel)} か国で超過が正は {pos}。国のデータは多くが1980年代後半から。"
        f"【t が最大の変種について】選べる4変種のうち選定期間の t が最大は『高値から遠い三分位を避ける（中＋近を等分）・vw_cap』"
        f"（{by['高値から遠い三分位を避ける（中＋近を等分）・vw_cap']['stats']['excess']:+}%/年・t {by['高値から遠い三分位を避ける（中＋近を等分）・vw_cap']['stats']['t']}）だが、"
        '超過が線（+1%/年）に届かないのは同じで、系統の定義（高値に近い側）から外れる（真ん中の三分位を含む）ので選ばなかった。'
        '【疑う理由】vw_cap では三分位の算術平均が 中 > 近い > 遠い の山形で、高値に近いほど良いという単調な並びになっていない（vw では 近い > 遠い ≈ 中）。'
        '超過の大部分はぶれが市場より小さい（β0.89）ことによる幾何の差で、算術の超過は小さい。'
        '回転 200%/年は置き値で、高値に近い側は勢いと重なるので実際の回転はもっと大きいかもしれない。'
        '勢いの系統（bigmom・jkpmulti の中の勢い）と中身が重なる。調べる側は2009年の勢いの崩れを知っている（高値に近い側は勢いほど崩れないと言われるが、'
        'それも記憶であってこのデータからではない）。'
    )
    extra = {
        'implement': FAMILY['implement'],
        'family_name': FAMILY['name'],
        'lookahead_test': ('module の lookahead_test() で5通り確かめた（すべて通過）: '
                           f"(1) 切り詰め: 脚のリターン・銘柄数・RF を {la['cuts']} の各月で切って作り直しても、その月までの規則のリターンと回転が完全一致 "
                           '(2) 未来の毒: 切った月より後の脚のリターン・銘柄数・RF を乱数に置き換えても前は不変・後ろは変わる（検査が空回りしていない） '
                           '(3) 1か月ずらし: 切った月より後の JKP の値を1か月後ろへずらしても前は不変・後ろは変わる '
                           f"(4) 月合わせ: 月 m の総リターン − 月 m の RF = 月 m の JKP の脚の超過（差の最大 {la['month_align_maxdiff']:.1e}・{la['n_months']}か月） "
                           '(5) 側と重みは spec の定数で、データから再推定しない。'
                           'JKP は月末 t の特徴（t までの252営業日の最高値に対する株価）で組み、t+1 の月のリターンを出す（JKP 2023 の作り方）。'
                           '月 m に持つかどうかは月 m の行の銘柄数 n（m−1 月末に組んだ時点の数）だけで決める。'),
        'directions': D,
        'variants_table': tbl,
        'selection_note': how,
        'markets': list(REPL),
        'markets_note': ('run() は22か国すべてに同じ凍結した規則を当て、三分位が20社以上の月が24か月以上ある国だけを返す。'
                         f"選定期間（〜2000-12）に24か月以上そろったのは {len(r['markets'])} か国（{' '.join(r['markets'])}）。"
                         '国のキーは JKP の3文字で run() の markets のキーと同じ'),
        'markets_selection_period': mkt_sel,
        'benchmark': 'French 米国市場（Mkt-RF＋RF・CRSP 全上場の上限なし時価加重）。他の国は JKP の国の mkt（vw＝上限なし・米ドル超過）＋French RF',
        'cost_note': '片道の回転100%につき0.25%。回転は 200%/年（事前登録 r6 の価格の信号の置き値）＋等分の組の毎月の戻し',
        'eligible_variants': sum(1 for x in rows if x['eligible']), 'reference_variants': sum(1 for x in rows if not x['eligible']),
    }
    doc = h.save_spec('hi52', spec, rationale, len(rows), st, extra)
    print('凍結:', best['name'], '変種の数', len(rows))
    return doc


if __name__ == '__main__':
    main(save='--save' in sys.argv)
