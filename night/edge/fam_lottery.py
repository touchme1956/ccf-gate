#!/usr/bin/env python3
"""night/edge/fam_lottery.py — 系統 lottery（第8回）: 宝くじのような株を避ける（買いだけ・良い側の三分位） vs 米国市場

事前登録 out/edge_prereg_r8.json の round8_families.lottery（線・費用・相手・期間は out/edge_prereg.json と同じ・
JKP の作りは out/edge_prereg_r6.json の common と同じ）。
  特徴は3本（どれも価格の信号＝直近21営業日の日次リターンから作る）:
    rmax1_21d   直近21日の最大の日次リターン                     Bali, Cakici & Whitelaw 2011「Maxing out」
    rmax5_21d   直近21日の上位5日の日次リターンの平均             同上（最大1日の雑音を均した版）
    rskew_21d   直近21日の日次リターンの歪み（実現歪度）         Amaya, Christoffersen, Jacobs & Vasquez 2015 /
                                                                 Boyer, Mitton & Vorkink 2010（期待歪度）・Barberis & Huang 2008（理論）
  良い側 = 特徴が小さい側（'1.0'＝宝くじらしさが小さい）のはず。確かめ方（directions()）:
    (1) JKP の因子 = direction ×（'3.0'−'1.0'）なので、選定期間の米国で 因子 と '3.0'−'1.0' の相関の符号が −1 なら direction −1＝'1.0' が良い側
    (2) 選定期間の三分位の平均の並び（'1.0' ≥ '3.0' か）
    (3) 定義: 最大の日次リターン・歪みが大きい＝右の裾が厚い＝宝くじのような株。宝くじ選好（Kumar 2009）で買われすぎ＝期待リターンが低い
  ・JKP の三分位の 'ret' は米ドルの**超過リターン**（米国の短期金利を引いたもの）→ 総リターン = ret + French RF
    （fam_payout.py・fam_profit.py で確かめ済み: JKP mkt(vw)+RF − French 市場 ≒ 0）
  ・月 m の組は JKP が m−1 月末の特徴で組んだ三分位（21日の窓は m−1 月末で終わる）。銘柄数 n も組んだ時点の数。
    米国は三分位が50社以上の月だけ使う（事前登録 r6 common）
  ・複数の特徴を等分する変種は、脚を毎月等分へ戻す（戻す売買を回転に足す＝事前登録 r6 common.費用）
  ・費用: 片道の回転1あたり 0.25%。回転の置き値 200%/年（事前登録 r8: 価格・取引の信号 rmax）
  ・他の市場: JKP 先進国22か国に同じ特徴・同じ側・同じ重み。三分位20社以上の月。国の相手は JKP の国の mkt（vw）＋米国 RF

使い方: python3 night/edge/fam_lottery.py           → 変種の表（選定の段・2000-12 まで）
        python3 night/edge/fam_lottery.py --save    → 選んで凍結（out/edge/spec_lottery.json）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h
import csv, io, math, random, statistics as S, zipfile
from concurrent.futures import ThreadPoolExecutor

FAMILY = {
    'key': 'lottery',
    'name': '宝くじのような株を避ける（直近21日の最大の日次リターン・上位5日の平均・歪みが小さい三分位）',
    'implement': ('楽天証券の米国株（成長投資枠＝NISA 可・レバレッジではない）で、米国上場の大型・中型株を毎月、'
                  '直近1か月（21営業日）の日次リターンの最大値（または上位5日の平均・歪み）で並べ、宝くじらしさが小さい下位3分の1を'
                  '時価加重（vw_cap なら1社の重みに上限＝巨大株を抑える）で持つ。価格の信号なので毎月入れ替わり、回転は置き値 200%/年'
                  '（実際はもっと大きいかもしれない）。下位1/3は数百〜千社になるので、個人は時価総額の大きい順に30〜50社へ絞る近似になる。'
                  'ETF で近いもの: 最小分散・低ぶれの ETF（USMV〔iShares MSCI USA Min Vol〕・SPLV〔Invesco S&P500 Low Volatility〕）は'
                  '宝くじらしさの小さい株に重なるが、物差しは過去1年のぶれ・相関で、直近21日の最大の日次リターンではない＝この規則の近似でしかない'
                  '（楽天の海外ETF一覧 out/broker_lineup.json で買えるかは別に確かめること）。NISA の成長投資枠で個別株・ETF とも買える'),
}

COST = 0.0025                     # 片道の回転1あたり（事前登録: 個別株の組）
TURN_ANN = 2.0                    # 片道の回転（年）。事前登録 r8: 価格・取引の信号（rmax）200%/年
MIN_N = 50                        # 米国: 三分位の銘柄数がこれ未満の月は使わない（事前登録 r6 common）
MIN_N_REPL = 20                   # 他の国
CHARS = ['rmax1_21d', 'rmax5_21d', 'rskew_21d']
EXPECT_GOOD = '1.0'               # 宝くじらしさが小さい側（directions() で確かめる）
REPL = ['jpn', 'gbr', 'deu', 'fra', 'can', 'aus', 'che', 'swe', 'nld', 'ita', 'esp', 'hkg', 'sgp', 'dnk', 'nor', 'bel',
        'fin', 'aut', 'irl', 'prt', 'nzl', 'isr']          # 先進国22か国（事前登録 r6 common.再現）
JKP = 'https://jkpfactors-data.s3.amazonaws.com/public/'

_MEMO = {}


# ───────────────────────── 読み込み ─────────────────────────
def _counts(region, ch, w):
    """三分位の銘柄数 n（h.jkp は返さないので、同じキャッシュを h.cached で読み h.guard を通す）"""
    url = f'{JKP}portfolios/%5B{region}%5D_%5B{ch}%5D_%5Bmonthly%5D_%5B{w}%5D.zip'
    z = zipfile.ZipFile(io.BytesIO(h.cached(f'jkp_portfolio_{region}_{ch}_{w}.zip', url)))
    out = {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        try:
            out.setdefault(x['pf'], {})[int(x['date'][:4]) * 100 + int(x['date'][5:7])] = int(float(x['n']))
        except (TypeError, ValueError, KeyError):
            continue
    return {k: h.guard(v) for k, v in out.items()}


def legs(region, ch, w):
    """→ {三分位: (超過リターン {m}, 銘柄数 {m})}。取れなければ {}"""
    k = (region, ch, w)
    if k not in _MEMO:
        try:
            p = h.jkp(region, ch, 'portfolio', w)
            n = _counts(region, ch, w)
            _MEMO[k] = {s: (p.get(s, {}), n.get(s, {})) for s in ('1.0', '2.0', '3.0')}
        except Exception:
            _MEMO[k] = {}
    return _MEMO[k]


# ───────────────────────── 規則 ─────────────────────────
def build(spec, region, rf, min_n):
    """spec: {'legs': [[特徴, 側], ...], 'w': 'vw_cap'|'vw', 'turn_ann': 2.0} → (総リターン {m}, 片道の回転 {m})
    月 m に持つかどうかは、月 m の組（m−1 月末に組まれたもの）の銘柄数 n だけで決まる。
    脚が複数なら等分に持ち、毎月もとの比へ戻す（戻しの売買を回転に足す）。すべての脚がそろう月だけを返す。
    データから何も推定しない（特徴・側・重みは spec の定数）"""
    w = spec['w']
    turn = spec.get('turn_ann', TURN_ANN)
    L = []
    for ch, side in spec['legs']:
        x = legs(region, ch, w)
        if not x or not x.get(side, ({}, {}))[0]:
            return {}, {}
        L.append(x[side])
    k = len(L)
    tw = 1.0 / k
    months = sorted(set.intersection(*[set(x[0]) for x in L]))
    ret, tv, prev = {}, {}, None
    for m in months:
        if m not in rf or any(x[1].get(m, 0) < min_n for x in L):
            prev = None
            continue
        reb = 0.0 if prev is None else 0.5 * sum(abs(p - tw) for p in prev)
        rs = [x[0][m] + rf[m] for x in L]
        ret[m] = sum(rs) / k
        tv[m] = turn / 12 + reb
        g = [tw * (1 + r) for r in rs]
        tot = sum(g)
        prev = [v / tot for v in g] if tot > 0 else None
    return ret, tv


def run(spec):
    mk, rf = h.us_market()
    ret, tv = build(spec, 'usa', rf, spec.get('min_n', MIN_N))
    out = {'ret': ret, 'bench': mk, 'rf': rf, 'turnover': tv, 'cost': COST, 'markets': {}}

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
        for c, x in ex.map(one, spec.get('replicate', [])):
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
    """良い側の確かめ: JKP 因子 = direction ×（'3.0'−'1.0'）→ 選定期間の米国で相関の符号。三分位の平均の並びも出す"""
    out = {}
    for c in CHARS:
        for w in ('vw_cap', 'vw'):
            p = h.jkp('usa', c, 'portfolio', w)
            f = h.jkp('usa', c, 'factor', w)
            ms = sorted(set(f) & set(p['1.0']) & set(p['3.0']))
            r = _corr([f[m] for m in ms], [p['3.0'][m] - p['1.0'][m] for m in ms])
            out[f'{c}|{w}'] = {'good_side': '3.0' if r > 0 else '1.0', 'corr_factor_vs_3minus1': round(r, 4), 'months': len(ms),
                               'mean_excess_pct_yr': {s: round(S.mean(p[s].values()) * 1200, 2) for s in ('1.0', '2.0', '3.0')}}
    return out


SHORT = {'rmax1_21d': 'rmax1', 'rmax5_21d': 'rmax5', 'rskew_21d': 'rskew'}


def variants(good):
    """成績を見る前に決めた変種（12本）。数字や月は振らない——特徴の組と重みの付け方だけ。good: {特徴: 良い側}"""
    V = []
    combos = [[c] for c in CHARS] + [
        list(CHARS),                          # 3本の等分
        ['rmax1_21d', 'rskew_21d'],           # Bali ら の MAX ＋ 歪み（右の裾の二つの測り方）
        ['rmax5_21d', 'rskew_21d'],           # 上位5日の平均（MAX の雑音を均した版）＋ 歪み
    ]
    for w in ('vw_cap', 'vw'):
        for cs in combos:
            nm = ('all3' if len(cs) == 3 else '+'.join(SHORT[c] for c in cs)) + f'|{w}'
            V.append((nm, {'legs': [[c, good[c]] for c in cs], 'w': w, 'turn_ann': TURN_ANN}))
    return V


def beta(ret, mk, rf, a=None, b=None):
    ms = [m for m in sorted(set(ret) & set(mk)) if (a is None or m >= a) and (b is None or m <= b)]
    x = [mk[m] - rf[m] for m in ms]
    y = [ret[m] - rf[m] for m in ms]
    mx, my = S.mean(x), S.mean(y)
    bt = sum((p - mx) * (q - my) for p, q in zip(x, y)) / sum((p - mx) ** 2 for p in x)
    return round(bt, 2), round((my - bt * mx) * 1200, 2)


SUBS = (('〜1962', None, 196212), ('1963-2000', 196301, 200012), ('1963-1981', 196301, 198112), ('1982-2000', 198201, 200012))


def select(good):
    assert h.PHASE == 'select'
    mk, rf = h.us_market()
    capm = {m: v + rf[m] for m, v in h.jkp('usa', 'mkt', 'factor', 'vw_cap').items() if m in rf}
    rows = []
    for name, sp in variants(good):
        r, tv = build(sp, 'usa', rf, MIN_N)
        st = h.stats(r, mk, rf, b=h.SEL_END, turnover=tv, cost=COST)
        sub = {}
        for lab, a, b in SUBS:
            s2 = h.stats(r, mk, rf, a=a, b=b, turnover=tv, cost=COST)
            sub[lab] = {'excess': s2['excess'], 't': s2['t']} if s2 else None
        st_cap = h.stats(r, capm, rf, b=h.SEL_END, turnover=tv, cost=COST)
        st_gross = h.stats(r, mk, rf, b=h.SEL_END)
        bt, al = beta(r, mk, rf, b=h.SEL_END)
        rows.append({'name': name, 'spec': sp, 'stats': st, 'sub': sub, 'beta': bt, 'alpha_capm': al,
                     'excess_gross': st_gross['excess'] if st_gross else None,
                     'ex_vs_jkp_capped_mkt': st_cap['excess'] if st_cap else None,
                     'turnover_yr': round(sum(tv.values()) / len(tv) * 12, 3) if tv else None})
        print(f"{name:18} {st['from']}〜 ex{st['excess']:+6.2f} t{st['t']:5.2f} (NW{st['t_nw']:5.2f}) 費用前{rows[-1]['excess_gross']:+.2f} "
              f"vol{st['vol']}/{st['bench_vol']} dd{st['maxdd']}/{st['bench_maxdd']} β{bt} α{al:+} 回転{rows[-1]['turnover_yr']} "
              f"対capmkt{rows[-1]['ex_vs_jkp_capped_mkt']:+} 10年窓{st['roll10_win']} 部分{sub}")
    return rows


# ───────────────────────── 先読みの検査 ─────────────────────────
def lookahead_test(spec):
    """(1) 切り詰め: 脚・銘柄数・RF を月 X で切って作り直しても、X までの規則のリターン・回転が完全一致
       (2) 未来の毒: X より後の脚のリターン・銘柄数・RF を乱数に置き換えても X までは不変（後ろは変わる＝検査が空回りしていない）
       (3) 1か月ずらし: X より後の脚のリターンと銘柄数を1か月後ろへずらして壊しても X までは不変（後ろは変わる）
       (4) 月合わせ: 月 m の総リターン = 同じ月 m の JKP 脚の超過の平均 + 月 m の RF
       (5) 特徴・側・重みは spec の定数（データから推定しない）"""
    mk, rf = h.us_market()
    mn = spec.get('min_n', MIN_N)
    full, ftv = build(spec, 'usa', rf, mn)
    saved = dict(_MEMO)
    cuts = [194012, 196212, 197512, 198512, 199512, 199912]
    rnd = random.Random(20260928)
    res = {'cuts': cuts}
    try:
        ok1 = ok2 = ok3 = bite2 = bite3 = True
        for X in cuts:
            # (1) 切り詰め
            _MEMO.clear()
            for k, v in saved.items():
                _MEMO[k] = {s: ({m: r for m, r in a.items() if m <= X}, {m: r for m, r in n.items() if m <= X}) for s, (a, n) in v.items()}
            part, ptv = build(spec, 'usa', {m: v for m, v in rf.items() if m <= X}, mn)
            ok1 &= set(part) == {m for m in full if m <= X}
            ok1 &= all(abs(part[m] - full[m]) < 1e-15 and abs(ptv[m] - ftv[m]) < 1e-15 for m in part)
            # (2) 未来の毒（リターン・銘柄数・RF を乱数に）
            _MEMO.clear()
            for k, v in saved.items():
                _MEMO[k] = {s: ({m: (r if m <= X else rnd.uniform(-0.3, 0.3)) for m, r in a.items()},
                                {m: (r if m <= X else rnd.randint(0, 400)) for m, r in n.items()}) for s, (a, n) in v.items()}
            rfP = {m: (v if m <= X else rnd.uniform(0, 0.02)) for m, v in rf.items()}
            part, ptv = build(spec, 'usa', rfP, mn)
            ok2 &= all(m in part and abs(part[m] - full[m]) < 1e-15 and abs(ptv[m] - ftv[m]) < 1e-15 for m in full if m <= X)
            if any(m > X for m in full):
                bite2 &= any(abs(part.get(m, 9) - full[m]) > 1e-9 for m in full if m > X)
            # (3) 1か月ずらし
            _MEMO.clear()
            for k, v in saved.items():
                _MEMO[k] = {s: ({m: (r if m <= X else a.get(h.add_months(m, -1), r)) for m, r in a.items()},
                                {m: (r if m <= X else n.get(h.add_months(m, -1), r)) for m, r in n.items()}) for s, (a, n) in v.items()}
            part, ptv = build(spec, 'usa', rf, mn)
            ok3 &= all(m in part and abs(part[m] - full[m]) < 1e-15 and abs(ptv[m] - ftv[m]) < 1e-15 for m in full if m <= X)
            if any(m > X for m in full):
                bite3 &= any(abs(part.get(m, 9) - full[m]) > 1e-12 for m in full if m > X)
        res.update({'truncate': ok1, 'poison_future': ok2, 'poison_bites': bite2, 'shift_future': ok3, 'shift_bites': bite3})
    finally:
        _MEMO.clear()
        _MEMO.update(saved)
    res['constants'] = (bool(spec.get('legs')) and all(s in ('1.0', '2.0', '3.0') and c in CHARS for c, s in spec['legs'])
                        and spec.get('w') in ('vw_cap', 'vw'))
    Ls = [legs('usa', c, spec['w'])[s][0] for c, s in spec['legs']]
    res['month_align_maxdiff'] = max(abs(full[m] - rf[m] - sum(x[m] for x in Ls) / len(Ls)) for m in full)
    res['n_months'] = len(full)
    res['ok'] = (res['truncate'] and res['poison_future'] and res['poison_bites'] and res['shift_future'] and res['shift_bites']
                 and res['constants'] and res['month_align_maxdiff'] < 1e-12)
    return res


LOOKAHEAD = ('(1) 切り詰め: JKP の脚のリターン・銘柄数・RF を 1940-12/1962-12/1975-12/1985-12/1995-12/1999-12 で切って作り直しても、'
             '切った月までの規則のリターンと回転が完全一致（1e-15）。'
             '(2) 未来の毒: 切った月より後の脚のリターン・銘柄数・RF を乱数に置き換えても、それより前は不変（後ろは変わる＝検査が空回りしていない）。'
             '(3) 1か月ずらし: 切った月より後の脚のリターンと銘柄数を1か月後ろへずらして壊しても、それより前は不変（後ろは変わる）。'
             '(4) 別プロセスの切り口: EDGE_SEL_END=199012 と 200012 で別々に run() を回し（EDGE_PHASE は select のまま）、1990-12 までの規則・相手・RF・回転（774か月）と'
             '他の市場（1990年で24か月以上そろう jpn gbr deu fra can）の規則・相手、国の build() の系列（22か国・1990年以前に月がある11か国）が完全一致'
             '（rmax5+rskew|vw_cap・rmax1|vw・all3|vw_cap の3つ・scratchpad の lookahead_lottery.py）。'
             '(5) 月合わせ: 月 m の総リターン = 月 m の JKP 脚の超過の平均 + 月 m の RF。月 m に持つかは月 m の行の n（JKP が m−1 月末に組んだ時点の数）だけで決める。'
             '特徴・側（\'1.0\'）・重みは spec の定数で、データから平均・分位・標準化を一切推定しない。'
             'JKP は月末 t までの21営業日の日次リターンで特徴を作って組み、t+1 の月のリターンを出す（JKP 2023 の作り方）')


# ───────────────────────── 凍結 ─────────────────────────
def main(save=False):
    D = directions()
    for k, v in D.items():
        print('向き', k, v)
    good = {}
    for c in CHARS:
        sides = {D[f'{c}|{w}']['good_side'] for w in ('vw_cap', 'vw')}
        assert len(sides) == 1, (c, sides)
        good[c] = sides.pop()
    print('良い側:', good)
    rows = select(good)
    elig = [r for r in rows if r['stats'] and r['stats']['excess'] >= 1.0]
    if elig:
        best = max(elig, key=lambda r: r['stats']['t'])
        how = '事前登録どおり（選定期間の費用後の超過が +1%/年以上の変種の中で、費用後の超過の t が最大）'
    else:
        best = max(rows, key=lambda r: r['stats']['t'])
        how = 'どの変種も +1%/年 に届かなかった。t が最大の変種を選んだ（線に届かないことを承知で）'
    spec = dict(best['spec'])
    spec.update({'min_n': MIN_N, 'min_n_repl': MIN_N_REPL, 'replicate': REPL, 'turn_ann': TURN_ANN,
                 'side_note': "'1.0' = 特徴が小さい＝宝くじらしさ（直近21日の最大の日次リターン・歪み）が小さい三分位（JKP direction −1）"})
    la = lookahead_test(spec)
    print('lookahead', la)
    assert la['ok'], la
    r = run(spec)
    st = h.stats(r['ret'], r['bench'], r['rf'], b=h.SEL_END, turnover=r['turnover'], cost=r['cost'])
    mkt_sel = {}
    for c, x in r['markets'].items():
        s2 = h.stats(x['ret'], x['bench'], x['rf'], b=h.SEL_END, turnover=x['turnover'], cost=x['cost'])
        if s2:
            mkt_sel[c] = {'from': s2['from'], 'years': s2['years'], 'excess': s2['excess'], 't': s2['t']}
    tbl = [{'name': x['name'], 'from': x['stats']['from'], 'excess': x['stats']['excess'], 't': x['stats']['t'],
            't_nw': x['stats']['t_nw'], 'excess_gross': x['excess_gross'], 'vol': x['stats']['vol'], 'maxdd': x['stats']['maxdd'],
            'beta': x['beta'], 'alpha_capm': x['alpha_capm'], 'ex_vs_jkp_capped_mkt': x['ex_vs_jkp_capped_mkt'],
            'sub_periods': x['sub'], 'turnover_yr': x['turnover_yr']} for x in rows]
    print('選んだ:', best['name'], how)
    print('選定期間:', st)
    print('他の市場（選定期間・参考）:', mkt_sel)
    if not save:
        return best, st
    return freeze(best, how, spec, st, rows, D, mkt_sel, la, tbl, good)


def freeze(best, how, spec, st, rows, D, mkt_sel, la, tbl, good):
    sub = best['sub']
    pos = sum(1 for v in mkt_sel.values() if v['excess'] > 0)
    others = sorted(rows, key=lambda x: -x['stats']['t'])[:4]
    chars = [c for c, _ in spec['legs']]
    dtxt = ' / '.join(f"{k} 相関{v['corr_factor_vs_3minus1']:+} 平均(1/2/3) {v['mean_excess_pct_yr']['1.0']}/{v['mean_excess_pct_yr']['2.0']}/{v['mean_excess_pct_yr']['3.0']}"
                      for k, v in D.items())
    subtxt = '・'.join(f'{lab} {v["excess"]:+}%/年（t {v["t"]}）' for lab, v in sub.items() if v)
    rationale = (
        f'【規則】{best["name"]}: 米国上場株を JKP が毎月 m−1 月末に組んだ三分位で見て、宝くじらしさの小さい三分位（\'1.0\'）だけを'
        f'{"上限つきの時価加重（JKP vw_cap＝NYSE の80%点で重みに上限）" if spec["w"] == "vw_cap" else "上限なしの時価加重（JKP vw）"}で買いだけで持つ'
        f'{"（特徴 " + "・".join(chars) + " の良い側を等分し、毎月等分へ戻す）" if len(chars) > 1 else "（特徴 " + chars[0] + "）"}。'
        '【なぜ】宝くじ選好: 個人は右の裾が厚い（小さい確率で大きく当たる）株を好み、そのぶん高く買う＝期待リターンが低い。'
        '理論は Barberis & Huang 2008（累積プロスペクト理論で正の歪みの証券は割高）・Brunnermeier, Gollier & Parker 2007（歪みへの選好）・'
        'Mitton & Vorkink 2007（分散しない投資家の歪み選好）、実証は Kumar 2009（宝くじのような株を個人が買う）・Boyer, Mitton & Vorkink 2010（期待歪度の高い株は低リターン）・'
        'Bali, Cakici & Whitelaw 2011（直近1か月の最大の日次リターン MAX が高い株は翌月に負ける）・Amaya ら 2015（実現歪度）。'
        '⚠ Bali ら の論文は2011年の公表（事前登録 r8 が明記）で、2001年より後。ただし歪み選好の理論（Kraus & Litzenberger 1976・Arditti 1967）は2000年以前からあった。'
        '裁定の限界: 宝くじらしい株は小型・空売りしにくい株に偏るので、割高が残りうる（Stambaugh, Yu & Yuan 2012 の系譜＝これも後）。'
        f'【向きの確かめ（選定期間）】{dtxt}。どれも JKP の因子と \'3.0\'−\'1.0\' の相関が −1（direction −1）＝小さい側が良い側。'
        f'【選定期間 {st["from"]}〜{st["to"]}（{st["years"]}年）】費用後（回転 {TURN_ANN*100:.0f}%/年 × 0.25% を引いた後）の年率 {st["cagr"]}% 対 French 米国市場 {st["bench_cagr"]}%、'
        f'超過 {st["excess"]:+}%/年（費用前 {best["excess_gross"]:+}%/年）、t {st["t"]}（Newey-West {st["t_nw"]}）、ぶれ {st["vol"]}% 対 {st["bench_vol"]}%、'
        f'最大下落 {st["maxdd"]}% 対 {st["bench_maxdd"]}%、転がる10年で勝った窓 {st["roll10_win"]}。'
        f'市場に対するβ {best["beta"]}・CAPM のα {best["alpha_capm"]:+}%/年。部分期間: {subtxt}。'
        f'JKP の上限つき市場（vw_cap）に対しては {best["ex_vs_jkp_capped_mkt"]:+}%/年。'
        f'【選び方】{how}。t の上位4: ' + ' / '.join(f'{x["name"]} {x["stats"]["excess"]:+}%（t {x["stats"]["t"]}）' for x in others) + '。'
        f'【他の市場（選定期間・参考・多くは1990年前後から）】先進国22か国のうち選定期間で測れた {len(mkt_sel)} か国で超過が正は {pos}。'
        '【予想】事前登録 r8 は「4本とも米国のホールドアウトで線を越える見込みは低い」。宝くじを避ける側は低ぶれ・低ベータの側と重なる'
        '（MAX とぶれの相関は高い）＝第5回の低ベータの系統と中身が近い。この研究の記録（CLAUDE.md）で第1〜7回の検定結果の要約を読める状態で作った回であることを書いておく'
        '（選定には2000-12までの数字しか使っていない。ホールドアウトの数字は選び方にも変種の設計にも使っていない）。'
        '⚠ 回転 200%/年は置き値。21日の窓で毎月組み直すので、実際の片道の回転はもっと大きい可能性がある（費用を過小に見ている向き）。'
        '⚠ 変種（3本×2重みの単独と、筋の決まった3つの組〔3本・rmax1+rskew・rmax5+rskew〕×2重み＝12本）は成績を見る前にコードに書いた。'
        '向きの表（directions()）と成績は同じ一回の実行で初めて見た。数字の刻み・月は振っていない。'
        f'⚠ 上限なしの時価加重（vw）の6変種はすべて +1%/年に届かず（最良 {max((x for x in rows if x["spec"]["w"] == "vw"), key=lambda x: x["stats"]["excess"])["name"]} '
        f'{max(x["stats"]["excess"] for x in rows if x["spec"]["w"] == "vw"):+}%/年）、rskew|vw は 1963-2000 に '
        f'{next(x for x in rows if x["name"] == "rskew|vw")["sub"]["1963-2000"]["excess"]:+}%/年（t {next(x for x in rows if x["name"] == "rskew|vw")["sub"]["1963-2000"]["t"]}）＝'
        '効きは巨大株の外（上限で重みを抑えた中型・大型の下のほう）にある。選んだ変種の 1982-2000 は '
        f'{sub["1982-2000"]["excess"]:+}%/年（t {sub["1982-2000"]["t"]}）で、選定期間の中でも新しい半分ではほぼ0＝t は1926-1981 に支えられている。'
        f'単独の rmax5|vw_cap は超過が最大（{next(x for x in rows if x["name"] == "rmax5|vw_cap")["stats"]["excess"]:+}%/年）で 1982-2000 も '
        f'{next(x for x in rows if x["name"] == "rmax5|vw_cap")["sub"]["1982-2000"]["excess"]:+}%/年だが、β が低く超過のぶれが大きいので t は下（事前登録の選び方に従った）。'
    )
    extra = {'implement': FAMILY['implement'], 'family_name': FAMILY['name'], 'lookahead_test': LOOKAHEAD,
             'lookahead_result': la, 'directions': D, 'good_sides': good, 'variants_table': tbl, 'markets': list(REPL),
             'markets_selection_period': mkt_sel, 'selection_note': how,
             'benchmark': 'French 米国市場（Mkt-RF＋RF・CRSP 全上場の上限なし時価加重）。他の国は JKP の国の mkt（vw＝上限なし・米ドル超過）＋French RF',
             'cost_note': '片道の回転100%につき0.25%。回転は 200%/年（事前登録 r8: 価格の信号の置き値）＋等分の組は毎月等分へ戻す売買',
             'markets_note': '国は JKP の3文字（run() の markets のキーと同じ）。三分位20社以上の月だけ・24か月未満の国は run() が落とす'}
    doc = h.save_spec('lottery', spec, rationale, len(rows), st, extra)
    print('凍結:', best['name'], doc['n_variants_tried'])
    return doc


if __name__ == '__main__':
    main(save='--save' in sys.argv)
