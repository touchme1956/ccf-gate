#!/usr/bin/env python3
"""night/edge/fam_fundmom.py — 系統 fundmom（第8回）: 利益の勢いの良い側の三分位（買いだけ） vs 米国市場

事前登録 out/edge_prereg_r8.json の round8_families.fundmom（線・費用・相手・期間は out/edge_prereg.json と同じ・
JKP の作りは out/edge_prereg_r6.json の common と同じ）。
  特徴は4本（JKP 2023 の作り・会計値は公表まで4か月以上遅らせてある）:
    niq_at_chg1  四半期の純利益÷総資産（ROA）の前年同期からの変化        Chan・Jegadeesh・Lakonishok 1996 の利益の勢いの系譜
    niq_be_chg1  四半期の純利益÷自己資本（ROE）の前年同期からの変化      同上
    ocf_at_chg1  営業CF÷総資産の12か月前からの変化（直近4四半期の合計）  Bouchaud・Krueger・Landier・Thesmar 2019（公表は2001年より後）
    saleq_gr1    四半期売上の前年同期比の伸び                              JKP は「低い側が良い」（Lakonishok・Shleifer・Vishny 1994 の系譜）
  良い側（予言の向き）の確かめ方（directions()）:
    (1) JKP の因子 = direction ×（'3.0'−'1.0'）。選定期間の米国で 因子 と '3.0'−'1.0' の相関は
        niq_at_chg1・niq_be_chg1・ocf_at_chg1 が 2重みとも +1.000（direction +1＝変化が大きいほど良い → '3.0'）、
        saleq_gr1 は 2重みとも −1.000（direction −1＝伸びが低いほど良い → '1.0'）。
    (2) 定義（JKP の SAS: accounting_chars.sas）: niq_at_chg1 = ibq÷総資産(3か月前) − 12か月前の同じ値、
        niq_be_chg1 = ibq÷自己資本(3か月前) − 12か月前、ocf_at_chg1 = ocf÷at − 12か月前、saleq_gr1 = saleq÷12か月前の saleq − 1。
    ⚠ saleq_gr1 は JKP の向き（'1.0'＝伸びの低い側）が選定期間の米国で**外れていた**（三分位の平均は '3.0' のほうが高い・因子の平均は負）。
       事前登録 r6 common「予言の向きの良い側（JKP の direction）を買うだけ」に従い、'1.0' を良い側として変種に入れる（'3.0' は変種に入れない）。
  回転の置き値（事前登録 r8）: 四半期の決算の信号 300%/年。
    ocf_at_chg1 は**年次だけではない**——JKP は年次の値と四半期（直近4四半期の合計＝TTM）の値を両方作り、
    四半期のほうが新しければそれを使う（accounting_chars.sas の combine_ann_qtr_chars・main.sas）ので、米国では決算ごと（四半期）に更新される。
    だから 300%/年（保守側）。参考に 50%/年での成績も出す（選定には使わない）。
  ・JKP の三分位の 'ret' は米ドルの**超過リターン**（米国の短期金利を引いたもの）→ 総リターン = ret + French RF
  ・月 m の組は JKP が m−1 月末に組んだ三分位。銘柄数 n も組んだ時点の数。米国は三分位が50社以上の月だけ使う
  ・複数の特徴を等分する変種は、脚を毎月等分へ戻す（戻す売買を回転に足す＝事前登録 r6 の common.費用）
  ・費用: 片道の回転1あたり 0.25%
  ・他の市場: JKP 先進国22か国に同じ特徴・同じ側・同じ重み。三分位20社以上の月。国の相手は JKP の国の mkt（vw）＋米国 RF

使い方: python3 night/edge/fam_fundmom.py           → 変種の表（選定の段・2000-12 まで）
        python3 night/edge/fam_fundmom.py --save    → 選んで凍結（out/edge/spec_fundmom.json）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h
import csv, io, math, statistics as S, zipfile
from concurrent.futures import ThreadPoolExecutor

FAMILY = {
    'key': 'fundmom',
    'name': '利益の勢い（四半期ROA・ROEの前年同期からの改善・営業CF÷資産の改善・四半期売上の伸び〔JKP の向き＝低い側〕の良い三分位）',
    'implement': ('楽天証券の米国株（成長投資枠＝NISA 可・レバレッジではない）で、米国上場の大型・中型株を決算のたび（年4回）に'
                  '「四半期の利益÷総資産（ROA）が前年の同じ四半期からどれだけ改善したか」などで並べ、改善の大きい上位3分の1を'
                  '時価加重（vw_cap なら1社の重みに上限＝巨大株を抑える／vw なら上限なし）で持つ。上位1/3は数百社になるので、'
                  '個人は時価総額の大きい順に30〜50社へ絞る近似になる。回転は 300%/年（決算ごとに半分以上が入れ替わる）と置いた。'
                  '利益の勢いそのものの ETF は楽天の海外ETF一覧（out/broker_lineup.json）に無い（「Quality」「Dividend Growth」は別物）＝'
                  'ETF では実行できず、個別株を決算ごとに入れ替える手間と売買の費用が要る。課税口座なら入れ替えのたびに売却益の税がかかる'
                  '（NISA の成長投資枠は売っても枠が翌年まで戻らないので、年300%の入れ替えには向かない）'),
}

COST = 0.0025                     # 片道の回転1あたり（事前登録: 個別株の組）
TURN = {'niq_at_chg1': 3.0, 'niq_be_chg1': 3.0, 'saleq_gr1': 3.0, 'ocf_at_chg1': 3.0}   # 片道の回転（年）。事前登録 r8 の置き値
TURN_OCF_ANNUAL = 0.5             # 参考（選定に使わない）: ocf_at_chg1 を年次の会計の信号と見なした場合
MIN_N = 50                        # 米国: 三分位の銘柄数がこれ未満の月は使わない
MIN_N_REPL = 20                   # 他の国
CHARS = ['niq_at_chg1', 'niq_be_chg1', 'ocf_at_chg1', 'saleq_gr1']
GOOD = {'niq_at_chg1': '3.0', 'niq_be_chg1': '3.0', 'ocf_at_chg1': '3.0', 'saleq_gr1': '1.0'}   # JKP direction（+1 → '3.0'、−1 → '1.0'）
REPL = ['jpn', 'gbr', 'deu', 'fra', 'can', 'aus', 'che', 'swe', 'nld', 'ita', 'esp', 'hkg', 'sgp', 'dnk', 'nor', 'bel',
        'fin', 'aut', 'irl', 'prt', 'nzl', 'isr']          # 先進国22か国
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
def build(spec, region, rf, min_n, turn=None):
    """spec: {'chars': [...], 'sides': {ch: '1.0'|'3.0'}, 'w': 'vw_cap'|'vw'} → (総リターン {m}, 片道の回転 {m})
    月 m に持つかどうかは、月 m の組（m−1 月末に組まれたもの）の銘柄数 n だけで決まる。
    脚が複数なら等分に持ち、毎月もとの比へ戻す（戻しの売買を回転に足す）。すべての脚がそろう月だけを返す"""
    turn = turn or TURN
    w = spec['w']
    chars = spec['chars']
    sides = spec.get('sides') or {c: GOOD[c] for c in chars}
    L = [legs(region, c, w) for c in chars]
    if not L or any(not x or not x.get(sides[c], ({}, {}))[0] for x, c in zip(L, chars)):
        return {}, {}
    L = [x[sides[c]] for x, c in zip(L, chars)]
    k = len(L)
    tw = 1.0 / k
    base_turn = sum(turn[c] for c in chars) / k / 12       # 脚の置き値の平均（月）
    months = sorted(set.intersection(*[set(x[0]) for x in L]))
    ret, tv, prev = {}, {}, None
    for m in months:
        if m not in rf or any(x[1].get(m, 0) < min_n for x in L):
            prev = None
            continue
        reb = 0.0 if prev is None else 0.5 * sum(abs(p - tw) for p in prev)
        rs = [x[0][m] + rf[m] for x in L]
        ret[m] = sum(rs) / k
        tv[m] = base_turn + reb
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
            out[f'{c}|{w}'] = {'jkp_good_side': '3.0' if r > 0 else '1.0', 'corr_factor_vs_3minus1': round(r, 4), 'months': len(ms),
                               'from': ms[0], 'factor_mean_pct_yr': round(S.mean(f[m] for m in ms) * 1200, 2),
                               'mean_excess_pct_yr': {s: round(S.mean(p[s].values()) * 1200, 2) for s in ('1.0', '2.0', '3.0')}}
    return out


def variants():
    """成績を見る前に決めた変種（16本）。数字や月は振らない——特徴の組と重みの付け方だけ"""
    V = []
    for w in ('vw_cap', 'vw'):
        for c in CHARS:
            V.append((f'{c}|{w}', {'chars': [c], 'sides': {c: GOOD[c]}, 'w': w}))
        V.append((f'all4|{w}', {'chars': list(CHARS), 'sides': dict(GOOD), 'w': w}))                             # 4本の等分
        V.append((f'niq2|{w}', {'chars': ['niq_at_chg1', 'niq_be_chg1'],                                          # 四半期利益の改善（資産・自己資本の両方）
                               'sides': {c: GOOD[c] for c in ('niq_at_chg1', 'niq_be_chg1')}, 'w': w}))
        V.append((f'earn3|{w}', {'chars': ['niq_at_chg1', 'niq_be_chg1', 'ocf_at_chg1'],                          # 利益と現金の改善（売上の向きの割れを除く）
                                'sides': {c: GOOD[c] for c in ('niq_at_chg1', 'niq_be_chg1', 'ocf_at_chg1')}, 'w': w}))
        V.append((f'at2|{w}', {'chars': ['niq_at_chg1', 'ocf_at_chg1'],                                           # 資産で割る2本（利益と現金・自己資本の分母は借金で膨らむので除く）
                              'sides': {c: GOOD[c] for c in ('niq_at_chg1', 'ocf_at_chg1')}, 'w': w}))
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
        st_gross = h.stats(r, mk, rf, b=h.SEL_END)
        ocf50 = None
        if 'ocf_at_chg1' in sp['chars']:
            t50 = dict(TURN, ocf_at_chg1=TURN_OCF_ANNUAL)
            r2, tv2 = build(sp, 'usa', rf, MIN_N, turn=t50)
            s3 = h.stats(r2, mk, rf, b=h.SEL_END, turnover=tv2, cost=COST)
            ocf50 = {'excess': s3['excess'], 't': s3['t']} if s3 else None
        bt, al = beta(r, mk, rf, b=h.SEL_END)
        rows.append({'name': name, 'spec': sp, 'stats': st, 'sub': sub, 'beta': bt, 'alpha_capm': al,
                     'gross_excess': st_gross['excess'] if st_gross else None,
                     'ex_vs_jkp_capped_mkt': st_cap['excess'] if st_cap else None, 'ocf_turn50_ref': ocf50,
                     'turnover_yr': round(sum(tv.values()) / len(tv) * 12, 3) if tv else None})
        print(f"{name:20} {st['from']}〜 ex{st['excess']:+6.2f} t{st['t']:5.2f} (NW{st['t_nw']:5.2f}) 費用前{rows[-1]['gross_excess']:+.2f} "
              f"vol{st['vol']}/{st['bench_vol']} dd{st['maxdd']}/{st['bench_maxdd']} β{bt} α{al:+} 回転{rows[-1]['turnover_yr']} "
              f"対capmkt{rows[-1]['ex_vs_jkp_capped_mkt']:+} 10年窓{st['roll10_win']} 部分{sub} ocf50{ocf50}")
    return rows


# ───────────────────────── 先読みの検査 ─────────────────────────
def lookahead_test(spec):
    """(1) 切り詰め: 脚・銘柄数・RF を月 X で切って作り直しても、X までの規則のリターン・回転が完全一致
       (2) 未来の毒: X より後の脚のリターンと銘柄数を1か月ずらして（壊して）も、X までは不変（後ろは変わる＝検査が空回りしていない）
       (3) 側・特徴・重みは spec の定数（データから推定しない）
       (4) 月合わせ: 月 m の総リターン = 同じ月 m の JKP 脚の超過の平均 + 月 m の RF"""
    mk, rf = h.us_market()
    mn = spec.get('min_n', MIN_N)
    full, ftv = build(spec, 'usa', rf, mn)
    for c in spec['chars']:                                  # 脚を _MEMO に載せておく
        legs('usa', c, spec['w'])
    saved = dict(_MEMO)
    cuts = [197512, 198512, 199012, 199512, 199912]
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
    sides = spec.get('sides') or {}
    res['constants'] = (bool(spec.get('chars')) and all(sides.get(c) in ('1.0', '3.0') for c in spec['chars'])
                        and spec.get('w') in ('vw_cap', 'vw'))
    Ls = [legs('usa', c, spec['w'])[sides[c]][0] for c in spec['chars']]
    res['month_align_maxdiff'] = max(abs(full[m] - rf[m] - sum(x[m] for x in Ls) / len(Ls)) for m in full)
    res['ok'] = res['truncate'] and res['poison_future'] and res['constants'] and res['month_align_maxdiff'] < 1e-12
    return res


LOOKAHEAD = ('(1) 切り詰め: JKP の脚のリターン・銘柄数・RF を 1975-12/1985-12/1990-12/1995-12/1999-12 で切って作り直しても、'
             '切った月までの規則のリターンと回転が完全一致（1e-15）。'
             '(2) 未来の毒: 切った月より後の脚のリターンと銘柄数を1か月ずらして壊しても、それより前は不変（後ろは変わる＝検査が空回りしていない）。'
             '(3) 別プロセスの切り口: EDGE_SEL_END=199012 と 200012 で別々に run() を回し、1990-12 までの規則・相手・RF・回転と'
             '国の系列（24か月の足切りの前の build()）が完全一致することを確かめた（scratchpad の lookahead_fundmom.py）。'
             '(4) 月合わせ: 月 m の総リターン = 月 m の JKP 脚の超過の平均 + 月 m の RF。月 m に持つかは月 m の行の n（JKP が m−1 月末に組んだ時点の数）だけで決める。'
             '側（JKP の direction）・特徴・重みは spec の定数で、データから平均・分位・標準化を一切推定しない。'
             'JKP は月末 t の特徴で組み t+1 のリターンを出し、会計値は公表まで4か月遅らせて使う（main.sas の create_acc_chars の lag_to_public=4・'
             '年次と四半期の両方に掛かる）')


# ───────────────────────── 凍結 ─────────────────────────
def main(save=False):
    D = directions()
    assert all(v['jkp_good_side'] == GOOD[k.split('|')[0]] for k, v in D.items()), D
    for k, v in D.items():
        print(k, v)
    rows = select()
    elig = [r for r in rows if r['stats'] and r['stats']['excess'] >= 1.0]
    if elig:
        best = max(elig, key=lambda r: r['stats']['t'])
        how = '事前登録どおり（選定期間の費用後の超過が +1%/年以上の変種の中で、費用後の超過の t が最大）'
    else:
        best = max(rows, key=lambda r: r['stats']['t'])
        how = 'どの変種も +1%/年 に届かなかった。t が最大の変種を選んだ（線に届かないことを承知で）'
    spec = dict(best['spec'])
    spec.update({'min_n': MIN_N, 'min_n_repl': MIN_N_REPL, 'replicate': REPL,
                 'turn_ann': {c: TURN[c] for c in spec['chars']},
                 'side_note': "'3.0' = 特徴が大きい側（利益・現金の改善が大きい＝JKP direction +1）／ '1.0' = 小さい側（saleq_gr1 の JKP direction −1）"})
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
            't_nw': x['stats']['t_nw'], 'gross_excess': x['gross_excess'], 'vol': x['stats']['vol'], 'maxdd': x['stats']['maxdd'],
            'beta': x['beta'], 'alpha_capm': x['alpha_capm'], 'ex_vs_jkp_capped_mkt': x['ex_vs_jkp_capped_mkt'],
            'sub_periods': x['sub'], 'turnover_yr': x['turnover_yr'], 'ocf_turn50_ref': x['ocf_turn50_ref']} for x in rows]
    print('選んだ:', best['name'], how)
    print('選定期間:', st)
    print('他の市場（選定期間・参考）:', mkt_sel)
    if not save:
        return best, st
    sub = best['sub']
    pos = sum(1 for v in mkt_sel.values() if v['excess'] > 0)
    others = sorted(rows, key=lambda x: -x['stats']['t'])[:5]
    elig_txt = ' / '.join(f'{x["name"]} {x["stats"]["excess"]:+}%（t {x["stats"]["t"]}）' for x in sorted(elig, key=lambda x: -x['stats']['t']))
    ocf50 = best['ocf_turn50_ref']
    sd = D.get('saleq_gr1|vw_cap', {})
    sdv = D.get('saleq_gr1|vw', {})
    rationale = (
        f'【規則】{best["name"]}: 米国上場株を JKP が毎月 m−1 月末に組んだ三分位で見て、'
        + ('営業CF÷総資産が12か月前より大きく改善した三分位（\'3.0\'）だけを' if spec['chars'] == ['ocf_at_chg1'] else
           '・'.join(f"{c} の良い側（{spec['sides'][c]}）" for c in spec['chars']) + ' を等分し（毎月等分へ戻す）')
        + f'{"上限つきの時価加重（JKP vw_cap＝NYSE の80%点で重みに上限）" if spec["w"] == "vw_cap" else "上限なしの時価加重（JKP vw）"}で買いだけで持つ。'
        '【なぜ】2001年より前に公表・理論の筋があった: (1) 利益の勢い——市場は利益の改善をすぐには織り込まず、改善した会社は'
        'その後の数か月〜1年も市場に勝ちやすい（Ball & Brown 1968・Bernard & Thomas 1989・Chan, Jegadeesh & Lakonishok 1996「Momentum strategies」は'
        '利益の驚き・予想の改定の勢いが株価の勢いと別に効くと示した）。(2) 現金の側（営業CF）は発生主義の利益より操作から遠く持続しやすい'
        '（Sloan 1996）＝現金で測った改善は利益で測った改善より本物に近い。'
        '⚠ ocf_at_chg1 を名指しした論文（Bouchaud・Krueger・Landier・Thesmar 2019「Sticky expectations and the profitability anomaly」）は2001年より後の公表。'
        '【選定期間 ' + f'{st["from"]}〜{st["to"]}（{st["years"]}年）】費用後の年率 {st["cagr"]}% 対 French 米国市場 {st["bench_cagr"]}%、'
        f'超過 {st["excess"]:+}%/年、t {st["t"]}（Newey-West {st["t_nw"]}）、費用前の超過 {best["gross_excess"]:+}%/年、'
        f'ぶれ {st["vol"]}% 対 {st["bench_vol"]}%、最大下落 {st["maxdd"]}% 対 {st["bench_maxdd"]}%、転がる10年で勝った窓 {st["roll10_win"]}。'
        f'市場に対するβ {best["beta"]}・CAPM のα {best["alpha_capm"]:+}%/年（超過の一部はβ>1 の分）。'
        f'部分期間: 〜1975 {sub["〜1975"]["excess"]:+}%/年（t {sub["〜1975"]["t"]}）・1976-2000 {sub["1976-2000"]["excess"]:+}%/年（t {sub["1976-2000"]["t"]}）・'
        f'1986-2000 {sub["1986-2000"]["excess"]:+}%/年（t {sub["1986-2000"]["t"]}）＝**上乗せは古い時代に偏り、1986年以降は0前後**。'
        f'JKP の上限つき市場（vw_cap）に対しては {best["ex_vs_jkp_capped_mkt"]:+}%/年。'
        + (f'参考（選定に使わない）: ocf_at_chg1 の回転を年次の置き値 50%/年にすると 超過 {ocf50["excess"]:+}%/年・t {ocf50["t"]}。' if ocf50 else '')
        + f'【選び方】{how}。+1%/年以上の変種: {elig_txt}。t の上位5: '
        + ' / '.join(f'{x["name"]} {x["stats"]["excess"]:+}%（t {x["stats"]["t"]}）' for x in others) + '。'
        '重みは vw_cap が vw より系統的に良かった（上限なしの vw は巨大株の比重が大きく、利益の勢いは小さい会社で強いという既知の形）。'
        f'【向き】saleq_gr1 の JKP の向きは −1（伸びの低い側が良い）で、選定期間の米国では外れていた'
        f'（三分位の平均 vw_cap {sd.get("mean_excess_pct_yr")}・vw {sdv.get("mean_excess_pct_yr")}%/年＝伸びの高い側が上）。'
        '事前登録どおり JKP の向きで変種に入れ、伸びの高い側は変種に入れていない。'
        f'【他の市場（選定期間・参考・多くは1990年前後から）】先進国22か国のうち選定期間で測れた {len(mkt_sel)} か国で超過が正は {pos}。'
        '⚠ 国の相手は JKP の国の mkt（上限なしの vw）なので、1社が巨大な国（フィンランドのノキア 1998-2000 など）では vw_cap の規則と相手の差が信号と無関係に大きく出る。'
        '【予想】事前登録 r8 は「米国のホールドアウトで線を越える見込みは低い」。選定期間の中でも 1986-2000 の上乗せが0前後で、公表後の減衰の形がすでに出ている。'
        '⚠ 変種を固定する前に、三分位の平均の並び（directions() の表＝選定期間の数字）を見た。変種は4本×2重みの単独と、筋の決まった4つの組'
        '（4本の等分・四半期利益の2本・利益と現金の3本・資産で割る2本）×2重みの16本で、数字の刻みは振っていない。'
    )
    extra = {'implement': FAMILY['implement'], 'family_name': FAMILY['name'], 'lookahead_test': LOOKAHEAD,
             'lookahead_result': la, 'directions': D, 'variants_table': tbl, 'markets': list(REPL),
             'markets_selection_period': mkt_sel, 'selection_note': how,
             'benchmark': 'French 米国市場（Mkt-RF＋RF・CRSP 全上場の上限なし時価加重）。他の国は JKP の国の mkt（vw＝上限なし・米ドル超過）＋French RF',
             'cost_note': ('片道の回転100%につき0.25%。回転の置き値は事前登録 r8 の「四半期の決算の信号 300%/年」。'
                           'ocf_at_chg1 は JKP が年次と四半期（直近4四半期の合計）の値を作り新しいほうを使う（accounting_chars.sas の combine_ann_qtr_chars）＝'
                           '米国では決算ごとに更新されるので年次の 50%/年ではなく 300%/年（保守側）。等分の組は毎月等分へ戻す売買を足す'),
             'side_note': ("niq_at_chg1・niq_be_chg1・ocf_at_chg1 は '3.0'（JKP direction +1）、saleq_gr1 は '1.0'（JKP direction −1・"
                           '選定期間の米国では外れていた）'),
             'markets_note': '国は JKP の3文字（run() の markets のキーと同じ）。三分位20社以上の月だけ・24か月未満の国は run() が落とす'}
    doc = h.save_spec('fundmom', spec, rationale, len(rows), st, extra)
    print('凍結:', best['name'], doc['n_variants_tried'])
    return doc


if __name__ == '__main__':
    main(save='--save' in sys.argv)
