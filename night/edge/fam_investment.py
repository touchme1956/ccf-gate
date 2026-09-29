#!/usr/bin/env python3
"""night/edge/fam_investment.py — 系統 investment（第8回）: 資産を膨らませない会社の三分位（買いだけ） vs 米国市場

事前登録 out/edge_prereg_r8.json の round8_families.investment（線・費用・相手・期間は out/edge_prereg.json と同じ・
JKP の作りは out/edge_prereg_r6.json の common と同じ）。
  特徴は3本（どれも年次の会計の信号・JKP 2023 の作り方で会計値は公表まで遅らせてある）:
    at_gr1    総資産の1年の伸び                         Cooper・Gulen・Schill 2008（作業論文 2005）／Fairfield・Whisenant・Yohn 2003
    capx_gr1  設備投資の1年の伸び                       Titman・Wei・Xie 2004（作業論文 2000-2001）「Capital investments and stock returns」
    inv_gr1   在庫の1年の伸び                           Thomas & Zhang 2002（在庫の変化）／Belo & Lin 2012（在庫の伸び）
  良い側 = '1.0'（特徴が小さい＝資産・設備投資・在庫を膨らませていない側）。確かめ方（directions()）:
    (1) JKP の因子 = direction ×（'3.0'−'1.0'）で、選定期間の米国で 因子 と '3.0'−'1.0' の相関が 3本×2重みすべて −1.000
        ＝JKP の direction は −1（低いほど良い）＝良い側は '1.0'。
    (2) 実物: 選定期間の三分位の平均超過（年率）が '1.0' ＞ '3.0'（directions() の mean_excess_pct_yr）。
    (3) 定義: どれも「今年の値 ÷ 前年の値 − 1」＝小さいほど膨らませていない。
  ・JKP の三分位の 'ret' は米ドルの**超過リターン**（米国の短期金利を引いたもの）→ 総リターン = ret + French RF
    （fam_payout.py・fam_old_firms.py で確かめ済み: JKP mkt(vw)+RF − French 市場 ≒ 0）
  ・月 m の組は JKP が m−1 月末に組んだ三分位。銘柄数 n も組んだ時点の数。米国は三分位が50社以上の月だけ使う
  ・複数の特徴を等分する変種は、脚を毎月等分へ戻す（戻す売買を回転に足す＝事前登録 r6 の common.費用）
  ・費用: 片道の回転1あたり 0.25%。回転の置き値 50%/年（事前登録 r8: 年次の会計の信号 at_gr1 など）
  ・他の市場: JKP 先進国22か国に同じ特徴・同じ側・同じ重み。三分位20社以上の月。国の相手は JKP の国の mkt（vw）＋米国 RF

使い方: python3 night/edge/fam_investment.py           → 変種の表（選定の段・2000-12 まで）
        python3 night/edge/fam_investment.py --save    → 選んで凍結（out/edge/spec_investment.json）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h
import csv, io, math, statistics as S, zipfile
from concurrent.futures import ThreadPoolExecutor

FAMILY = {
    'key': 'investment',
    'name': '資産を膨らませない会社（総資産・設備投資・在庫の1年の伸びが低い三分位）',
    'implement': ('楽天証券の米国株（成長投資枠＝NISA 可・レバレッジではない）で、米国上場の大型・中型株を年1回（決算が出そろった後）'
                  '前年からの総資産の伸び（または設備投資・在庫の伸び）で並べ、伸びのいちばん低い3分の1を'
                  '時価加重（JKP vw_cap なら1社の重みに上限＝巨大株を抑える／vw なら上限なし）で持つ。'
                  '三分位は数百社になるので、個人は時価総額の大きい順に30〜50社へ絞る近似になる（回転は 50%/年と置いた）。'
                  'ETF: 「資産の伸びが低い」だけで選ぶ ETF は楽天の海外ETF一覧（out/broker_lineup.json）に無い'
                  '（多因子の中に投資の物差しを混ぜる Dimensional・Vanguard の因子 ETF〔DFAC・VFMF など〕も一覧に無い）。'
                  '＝ETF では実行できず、個別株を20〜50社持つ必要がある。NISA の成長投資枠で個別株として持つのは可'),
}

COST = 0.0025                     # 片道の回転1あたり（事前登録: 個別株の組）
TURN_ANN = 0.5                    # 片道の回転（年）。事前登録 r8: 年次の会計の信号（at_gr1 など）の置き値
MIN_N = 50                        # 米国: 三分位の銘柄数がこれ未満の月は使わない（事前登録 r6 common）
MIN_N_REPL = 20                   # 他の国
CHARS = ['at_gr1', 'capx_gr1', 'inv_gr1']
GOOD = '1.0'                      # 伸びの低い三分位（JKP direction −1）
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
    """spec: {'chars': [...], 'side': '1.0', 'w': 'vw_cap'|'vw'} → (総リターン {m}, 片道の回転 {m})
    月 m に持つかどうかは、月 m の組（m−1 月末に組まれたもの）の銘柄数 n だけで決まる。
    脚が複数なら等分に持ち、毎月もとの比へ戻す（戻しの売買を回転に足す）。すべての脚がそろう月だけを返す"""
    side, w = spec.get('side', GOOD), spec['w']
    L = [legs(region, c, w) for c in spec['chars']]
    if not L or any(not x or not x.get(side, ({}, {}))[0] for x in L):
        return {}, {}
    L = [x[side] for x in L]
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
        tv[m] = TURN_ANN / 12 + reb
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
            n = _counts('usa', c, w)
            out[f'{c}|{w}'] = {'good_side': '3.0' if r > 0 else '1.0', 'corr_factor_vs_3minus1': round(r, 4), 'months': len(ms),
                               'from': ms[0], 'to': ms[-1],
                               'mean_excess_pct_yr': {s: round(S.mean(p[s].values()) * 1200, 2) for s in ('1.0', '2.0', '3.0')},
                               'median_n_side1': int(S.median(n.get('1.0', {0: 0}).values()))}
    return out


def variants():
    """成績を見る前に決めた変種（14本）。数字や月は振らない——特徴の組と重みの付け方だけ
    3本の単独 ＋ 2本ずつの等分3組 ＋ 3本の等分 ＝ 7 × 重み2（vw_cap・vw）"""
    combos = [['at_gr1'], ['capx_gr1'], ['inv_gr1'],
              ['at_gr1', 'capx_gr1'], ['at_gr1', 'inv_gr1'], ['capx_gr1', 'inv_gr1'],
              list(CHARS)]
    V = []
    for w in ('vw_cap', 'vw'):
        for cs in combos:
            nm = cs[0] if len(cs) == 1 else ('all3' if len(cs) == 3 else '+'.join(c.split('_')[0] for c in cs))
            V.append((f'{nm}|{w}', {'chars': list(cs), 'side': GOOD, 'w': w}))
    return V


def beta(ret, mk, rf, a=None, b=None):
    ms = [m for m in sorted(set(ret) & set(mk)) if (a is None or m >= a) and (b is None or m <= b)]
    x = [mk[m] - rf[m] for m in ms]
    y = [ret[m] - rf[m] for m in ms]
    mx, my = S.mean(x), S.mean(y)
    bt = sum((p - mx) * (q - my) for p, q in zip(x, y)) / sum((p - mx) ** 2 for p in x)
    return round(bt, 2), round((my - bt * mx) * 1200, 2)


def select():
    assert h.PHASE == 'select'
    mk, rf = h.us_market()
    capm = {m: v + rf[m] for m, v in h.jkp('usa', 'mkt', 'factor', 'vw_cap').items() if m in rf}
    rows = []
    for name, sp in variants():
        r, tv = build(sp, 'usa', rf, MIN_N)
        st = h.stats(r, mk, rf, b=h.SEL_END, turnover=tv, cost=COST)
        sub = {}
        for lab, a, b in (('〜1975', None, 197512), ('1976-2000', 197601, h.SEL_END), ('1986-2000', 198601, h.SEL_END)):
            s2 = h.stats(r, mk, rf, a=a, b=b, turnover=tv, cost=COST)
            sub[lab] = {'excess': s2['excess'], 't': s2['t']} if s2 else None
        st_cap = h.stats(r, capm, rf, b=h.SEL_END, turnover=tv, cost=COST)
        bt, al = beta(r, mk, rf, b=h.SEL_END)
        rows.append({'name': name, 'spec': sp, 'stats': st, 'sub': sub, 'beta': bt, 'alpha_capm': al,
                     'ex_vs_jkp_capped_mkt': st_cap['excess'] if st_cap else None,
                     'turnover_yr': round(sum(tv.values()) / len(tv) * 12, 3) if tv else None})
        print(f"{name:18} {st['from']}〜 ex{st['excess']:+6.2f} t{st['t']:5.2f} (NW{st['t_nw']:5.2f}) "
              f"vol{st['vol']}/{st['bench_vol']} dd{st['maxdd']}/{st['bench_maxdd']} β{bt} α{al:+} 回転{rows[-1]['turnover_yr']} "
              f"対capmkt{rows[-1]['ex_vs_jkp_capped_mkt']:+} 10年窓{st['roll10_win']} 部分{sub}")
    return rows


def markets_by_variant():
    """参考のみ（選び方には使わない）: 各変種を先進国22か国に当てた選定期間の超過（国の数・正の数・中央値）"""
    out = {}
    for name, sp in variants():
        sp = dict(sp, replicate=REPL)
        r = run(sp)
        ex = [s['excess'] for s in (h.stats(x['ret'], x['bench'], x['rf'], b=h.SEL_END, turnover=x['turnover'], cost=x['cost'])
                                    for x in r['markets'].values()) if s]
        out[name] = {'countries': len(ex), 'positive': sum(e > 0 for e in ex),
                     'median_excess': round(S.median(ex), 2) if ex else None}
    return out


# ───────────────────────── 先読みの検査 ─────────────────────────
def lookahead_test(spec):
    """(1) 切り詰め: 脚・銘柄数・RF を月 X で切って作り直しても、X までの規則のリターン・回転が完全一致
       (2) 未来の毒: X より後の脚のリターンと銘柄数を1か月ずらして（壊して）も、X までは不変（後ろは変わる＝検査が空回りしていない）
       (3) 側・特徴・重みは spec の定数（データから推定しない）
       (4) 月合わせ: 月 m の総リターン = 同じ月 m の JKP 脚の超過の平均 + 月 m の RF"""
    mk, rf = h.us_market()
    mn = spec.get('min_n', MIN_N)
    full, ftv = build(spec, 'usa', rf, mn)
    saved = dict(_MEMO)
    cuts = [196512, 197512, 198512, 199512, 199912]
    res = {}
    try:
        ok1 = True
        for X in cuts:
            _MEMO.clear()
            for k, v in saved.items():
                _MEMO[k] = {s: ({m: r for m, r in a.items() if m <= X}, {m: r for m, r in n.items() if m <= X}) for s, (a, n) in v.items()}
            part, ptv = build(spec, 'usa', {m: v for m, v in rf.items() if m <= X}, mn)
            ok1 &= set(part) == {m for m in full if m <= X}
            ok1 &= all(abs(part[m] - full[m]) < 1e-15 and abs(ptv[m] - ftv[m]) < 1e-15 for m in part)
        res['truncate'] = ok1
        ok2 = True
        for X in cuts:
            _MEMO.clear()
            for k, v in saved.items():
                _MEMO[k] = {s: ({m: (r if m <= X else a.get(h.add_months(m, -1), r)) for m, r in a.items()},
                                {m: (r if m <= X else n.get(h.add_months(m, -1), r)) for m, r in n.items()}) for s, (a, n) in v.items()}
            part, ptv = build(spec, 'usa', rf, mn)
            ok2 &= all(abs(part[m] - full[m]) < 1e-15 and abs(ptv[m] - ftv[m]) < 1e-15 for m in full if m <= X)
            ok2 &= any(abs(part.get(m, 0) - full[m]) > 1e-12 for m in full if m > X)
        res['poison_future'] = ok2
    finally:
        _MEMO.clear()
        _MEMO.update(saved)
    res['constants'] = bool(spec.get('chars')) and spec.get('side') in ('1.0', '2.0', '3.0') and spec.get('w') in ('vw_cap', 'vw')
    Ls = [legs('usa', c, spec['w'])[spec['side']][0] for c in spec['chars']]
    res['month_align_maxdiff'] = max(abs(full[m] - rf[m] - sum(x[m] for x in Ls) / len(Ls)) for m in full)
    res['ok'] = res['truncate'] and res['poison_future'] and res['constants'] and res['month_align_maxdiff'] < 1e-12
    return res


LOOKAHEAD = ('(1) 切り詰め: JKP の脚のリターン・銘柄数・RF を 1965-12/1975-12/1985-12/1995-12/1999-12 で切って作り直しても、'
             '切った月までの規則のリターンと回転が完全一致（1e-15）。'
             '(2) 未来の毒: 切った月より後の脚のリターンと銘柄数を1か月ずらして壊しても、それより前は不変（後ろは変わる＝検査が空回りしていない）。'
             '(3) 別プロセスの切り口: EDGE_SEL_END=199012 と 200012（EDGE_PHASE は select のまま）で別々に run() を回し、'
             '1990-12 までの規則（464か月）・相手・RF（774か月）・回転と、他の市場の規則・相手・回転が完全一致'
             '（凍結した inv_gr1|vw_cap と、ほかに at_gr1|vw・all3|vw の3つ）。1990年で切っても24か月そろう国は can だけで一致、'
             '24か月の足切りの前の国の系列（inv_gr1|vw_cap: jpn 23・gbr 17・can 83・aus 2 か月）も一致'
             '（scratchpad の lookahead_investment.py）。'
             '(4) 月合わせ: 月 m の総リターン = 月 m の JKP 脚の超過の平均 + 月 m の RF。月 m に持つかは月 m の行の n（JKP が m−1 月末に組んだ時点の数）だけで決める。'
             '側（\'1.0\'）・特徴・重みは spec の定数で、データから平均・分位・標準化を一切推定しない。'
             'JKP は月末 t の特徴で組み t+1 のリターンを出し、会計値は公表まで（年次は4か月以上）遅らせて使う（JKP 2023 の作り方）')


# ───────────────────────── 凍結 ─────────────────────────
def main(save=False):
    D = directions()
    for k, v in D.items():
        print('向き', k, v)
    assert all(v['good_side'] == GOOD for v in D.values()), D
    rows = select()
    elig = [r for r in rows if r['stats'] and r['stats']['excess'] >= 1.0]
    if elig:
        best = max(elig, key=lambda r: r['stats']['t'])
        how = '事前登録どおり（選定期間の費用後の超過が +1%/年以上の変種の中で、費用後の超過の t が最大）'
    else:
        best = max(rows, key=lambda r: r['stats']['t'])
        how = 'どの変種も +1%/年 に届かなかった。t が最大の変種を選んだ（線に届かないことを承知で）'
    spec = dict(best['spec'])
    spec.update({'min_n': MIN_N, 'min_n_repl': MIN_N_REPL, 'replicate': REPL, 'turn_ann': TURN_ANN,
                 'side_note': "'1.0' = 特徴が小さい＝総資産・設備投資・在庫の1年の伸びが低い三分位（JKP direction −1）"})
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
            't_nw': x['stats']['t_nw'], 'vol': x['stats']['vol'], 'maxdd': x['stats']['maxdd'], 'beta': x['beta'],
            'alpha_capm': x['alpha_capm'], 'ex_vs_jkp_capped_mkt': x['ex_vs_jkp_capped_mkt'],
            'sub_periods': x['sub'], 'turnover_yr': x['turnover_yr']} for x in rows]
    print('選んだ:', best['name'], how)
    print('選定期間:', st)
    print('他の市場（選定期間・参考）:', mkt_sel)
    if not save:
        return best, st
    sub = best['sub']
    pos = sum(1 for v in mkt_sel.values() if v['excess'] > 0)
    others = sorted(rows, key=lambda x: -x['stats']['t'])[:4]
    rationale = (
        f'【規則】{best["name"]}: 米国上場株を JKP が毎月 m−1 月末に組んだ三分位で見て、'
        f'{"・".join(spec["chars"])} の低い三分位（\'1.0\'＝資産を膨らませていない側）だけを'
        f'{"上限つきの時価加重（JKP vw_cap＝NYSE の80%点で重みに上限）" if spec["w"] == "vw_cap" else "上限なしの時価加重（JKP vw）"}で買いだけで持つ'
        f'{"（特徴の良い側を等分し、毎月等分へ戻す）" if len(spec["chars"]) > 1 else ""}。'
        '【なぜ】2001年より前に公表・理論の筋があった: (1) 投資の q 理論——割引率（期待リターン）が低い会社ほど多くの投資案件が採算に乗るので、'
        '資産を大きく膨らませる会社は期待リターンが低い（Cochrane 1991・Berk・Green・Naik 1999）。'
        '(2) 経営者の帝国建設・過剰投資——手元の現金を採算の悪い投資へ回す（Jensen 1986 の自由現金流）を市場は割り引き足りない'
        '（Titman・Wei・Xie 2004 の作業論文は2000-2001年・設備投資の急増のあとに負けることを示した）。'
        '(3) 市場は過去の成長を外挿しすぎる（Lakonishok・Shleifer・Vishny 1994）。在庫の積み上がりは売れ残り・需要の鈍化の先行信号'
        '（Lev & Thiagarajan 1993・Abarbanell & Bushee 1998 の基礎分析の信号・Thomas & Zhang 2002）。資産の伸び全体は Fairfield ら 2003・Cooper ら 2008 が束ねた。'
        '⚠ 在庫の伸び（inv_gr1）は在庫を持つ会社（製造・小売・卸など）にしか定義されない——在庫の無いソフトウェア・サービス・金融の多くは'
        '三分位の外＝在庫の特徴を含む規則は市場の一部（選定期間の米国で良い側の中央値 約1,250社）から選ぶ。'
        '⚠ Cooper ら 2008 と Belo & Lin 2012 は2001年より後の公表で、Fama-French の CMA（2015）も後。'
        f'【選定期間 {st["from"]}〜{st["to"]}（{st["years"]}年）】費用後の年率 {st["cagr"]}% 対 French 米国市場 {st["bench_cagr"]}%、'
        f'超過 {st["excess"]:+}%/年、t {st["t"]}（Newey-West {st["t_nw"]}）、ぶれ {st["vol"]}% 対 {st["bench_vol"]}%、'
        f'最大下落 {st["maxdd"]}% 対 {st["bench_maxdd"]}%、転がる10年で勝った窓 {st["roll10_win"]}。'
        f'市場に対するβ {best["beta"]}・CAPM のα {best["alpha_capm"]:+}%/年。'
        f'部分期間: 〜1975 {sub["〜1975"]["excess"]:+}%/年（t {sub["〜1975"]["t"]}）・1976-2000 {sub["1976-2000"]["excess"]:+}%/年（t {sub["1976-2000"]["t"]}）・'
        f'1986-2000 {sub["1986-2000"]["excess"]:+}%/年（t {sub["1986-2000"]["t"]}）。'
        f'JKP の上限つき市場（vw_cap）に対しては {best["ex_vs_jkp_capped_mkt"]:+}%/年。'
        f'【選び方】{how}。t の上位4: ' + ' / '.join(f'{x["name"]} {x["stats"]["excess"]:+}%（t {x["stats"]["t"]}）' for x in others) + '。'
        f'【他の市場（選定期間・参考・多くは1990年前後から・選び方には使っていない）】先進国22か国のうち選定期間で測れた {len(mkt_sel)} か国で超過が正は {pos}'
        '——1990年代の米国外では資産を膨らませない側がむしろ負けており、選定期間の中ですでに米国だけの効果に見える（ホールドアウトの再現を疑う理由）。'
        '【予想と後知恵】事前登録 r8 は「米国のホールドアウトで線を越える見込みは低い」。調べる側は、Fama-French の CMA（投資の控えめ）が'
        '米国で2007年以降ほぼ消えたこと（2026-09-26 の測定: 米国 2007〜 +0.1%/年）を知っている——その後知恵があることを書いておく。'
        '⚠ 資産の伸びの低い側は割安（HML）と強く重なる（資産を膨らませない会社は成熟・割安に寄る）＝第1〜5回の割安の系統と独立ではない。'
        '⚠ 変種を固定する前に、三分位の平均の並び（directions() の表＝選定期間の数字）を見た。変種は3本×2重みの単独と、'
        '2本ずつ・3本の等分×2重みで、数字の刻みは振っていない（合計14本）。'
    )
    extra = {'implement': FAMILY['implement'], 'family_name': FAMILY['name'], 'lookahead_test': LOOKAHEAD,
             'lookahead_result': la, 'directions': D, 'variants_table': tbl, 'markets': list(REPL),
             'markets_selection_period': mkt_sel, 'selection_note': how,
             'markets_selection_by_variant_reference': markets_by_variant(),
             'benchmark': 'French 米国市場（Mkt-RF＋RF・CRSP 全上場の上限なし時価加重）。他の国は JKP の国の mkt（vw＝上限なし・米ドル超過）＋French RF',
             'cost_note': '片道の回転100%につき0.25%。回転は 50%/年（事前登録 r8: 年次の会計の信号）＋等分の組は毎月等分へ戻す売買',
             'markets_note': '国は JKP の3文字（run() の markets のキーと同じ）。三分位20社以上の月だけ・24か月未満の国は run() が落とす'}
    doc = h.save_spec('investment', spec, rationale, len(rows), st, extra)
    print('凍結:', best['name'], doc['n_variants_tried'])
    return doc


if __name__ == '__main__':
    main(save='--save' in sys.argv)
