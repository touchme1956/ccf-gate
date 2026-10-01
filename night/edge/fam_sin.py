#!/usr/bin/env python3
"""night/edge/fam_sin.py — 系統 sin: 罪の株の買いだけ（Hong & Kacperczyk 2009「The price of sin」）

事前登録 out/edge_prereg.json（第1回の枠組み・第3回の系統）の一系統。読むだけ・門の採点に不使用。

  考え方: たばこ・酒・賭博の会社は、社会の規範に縛られる投資家（年金・大学基金・規範を気にする機関）が持たない。
        持つ人が少ないぶん株価は安く（資本コストが高く）据え置かれ、その差が持ち続ける人の上乗せになる
        （Hong & Kacperczyk 2009: 1926-2006 で比較の業種に対し月0.26%前後。訴訟の危険の代金という説明もある）。
        ここでは信号を使わず、罪の業種をいつも持つ（買いだけ・入れ替えなし）。

  データ: Ken French の 49_Industry_Portfolios（業種の中は時価加重・配当込み 'Average Value Weighted Returns -- Monthly'）。
        罪の業種の候補（French の分類は SIC の範囲）:
          Smoke = たばこ（SIC 2100-2199）
          Beer  = ビール・酒（SIC 2080-2085）
          Guns  = 防衛（兵器・弾薬・ミサイル・戦車 SIC 3480-3489, 3760-3769, 3795）＝ 1963-07 から
          Fun   = 娯楽（映画・遊園地・賭博〔SIC 7990-7999〕・玩具の一部）＝賭博だけを切り出せないので粗い代用
  重み: 'ew' = 持つ業種を毎月等分に戻す（回転＝前月の重みを当月のリターンで流した後の重みとの差の半分）
        'vw' = 業種の時価で加重。時価は 'Number of Firms in Portfolios' × 'Average Firm Size' の **m−1 月の行**に
               (1＋m−1 月のリターン) を掛けたもの（indmom と同じ保守的な作り＝m 月の行を一切読まない）
  組入れ: 月 m に持つのは、m−1 月にリターンがある業種だけ（Guns は 1963-08 から自動で入る）。持っている業種の
        m 月のリターンが欠けたら 0 と置く（前もって知らないため）。
  相手: 米国市場（h.us_market＝French の CRSP 全上場の時価加重・配当込み）。費用: 回転1あたり 0.10%（事前登録: 業種の入れ替え）。
  再現: 無し（French の国別には業種の分解が無い）。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h                                                  # noqa: E402
import itertools, math, random

FAMILY = {
    'key': 'sin',
    'name': '罪の株の買いだけ（たばこ・酒・防衛・娯楽の業種をいつも持つ）',
    'implement': ('⚠ たばこ・酒だけの単独ETFは米国にほぼ無い（酒・たばこは消費財ETF XLP・VDC の一部に混ざるだけ）。'
                  '現実的な実行は、楽天証券の米国株口座で**個別株を時価加重で持つ**こと: たばこ＝アルトリア(MO)・'
                  'フィリップモリス(PM)・ブリティッシュ・アメリカン・タバコ(BTI)、酒＝ブラウン・フォーマン(BF.B)・'
                  'コンステレーション(STZ)・モルソン・クアーズ(TAP)・ディアジオ(DEO)・アンハイザー・ブッシュ(BUD)など。'
                  '防衛は業種ETF（ITA・XAR・PPA）、賭博は BJK（賭博ETF・小さい）で代えられる。'
                  '入れ替えが無い（買って持つ）ので NISA の成長投資枠で持てる（個別株・ETF とも対象）。'
                  '等分へ戻す型は毎月の小さな売買が要り、NISA の枠を消費するので年1回程度の戻しで近似することになる')
}

COST = 0.001            # 事前登録: 指数・ETF・業種＝片道の回転100%につき 0.10%
SIN = ('Smoke', 'Beer', 'Guns', 'Fun')

_cache = {}


def _load():
    if 'd' not in _cache:
        d = h.french('49_Industry_Portfolios')
        r = {i: {m: v / 100 for m, v in d['Average Value Weighted Returns -- Monthly'][i].items() if m > 99999} for i in SIN}
        nf = d.get('Number of Firms in Portfolios', {})
        sz = d.get('Average Firm Size', {})
        cap = {}
        for i in SIN:
            a, b = nf.get(i, {}), sz.get(i, {})
            cap[i] = {m: a[m] * b[m] for m in a if m in b and m > 99999 and a[m] > 0 and b[m] > 0}
        _cache['d'] = (r, cap)
    return _cache['d']


def weights(r, cap, m, spec):
    """月 m の持ち高（m−1 月末までのデータだけで決める）"""
    prev = h.add_months(m, -1)
    live = [i for i in spec['inds'] if prev in r[i]]
    if not live:
        return None
    if spec.get('weight', 'ew') == 'vw':
        cw = {i: cap[i].get(prev, 0.0) * (1 + r[i][prev]) for i in live}
        tot = sum(cw.values())
        if tot <= 0:
            return {i: 1 / len(live) for i in live}
        return {i: v / tot for i, v in cw.items() if v > 0}
    return {i: 1 / len(live) for i in live}


def run(spec):
    """spec: {'inds': ['Smoke', 'Beer', ...], 'weight': 'ew'|'vw'}"""
    r, cap = _load()
    mkt, rf = h.us_market()
    months = sorted(set().union(*[set(r[i]) for i in spec['inds']]))
    ret, tv = {}, {}
    w_prev_drift = None
    for m in months:
        w = weights(r, cap, m, spec)
        if w is None:
            continue
        rp = sum(wi * r[i].get(m, 0.0) for i, wi in w.items())
        if w_prev_drift is None:
            tv[m] = 1.0
        else:
            ks = set(w) | set(w_prev_drift)
            tv[m] = 0.5 * sum(abs(w.get(i, 0.0) - w_prev_drift.get(i, 0.0)) for i in ks)
        ret[m] = rp
        w_prev_drift = {i: wi * (1 + r[i].get(m, 0.0)) / (1 + rp) for i, wi in w.items()} if rp > -1 else None
    return {'ret': ret, 'bench': mkt, 'rf': rf, 'turnover': tv, 'cost': COST, 'markets': {}}


# ───────────────────────── 選定の段（2000-12 で切れたデータだけ） ─────────────────────────
def variants():
    """罪の業種の組み合わせ（空でない部分集合 15）×重み（ew/vw）。1業種だけの組は ew=vw なので1つに数える → 26"""
    out = []
    for k in range(1, 5):
        for c in itertools.combinations(SIN, k):
            if k == 1:
                out.append({'inds': list(c), 'weight': 'vw'})
            else:
                out.append({'inds': list(c), 'weight': 'ew'})
                out.append({'inds': list(c), 'weight': 'vw'})
    return out


def label(sp):
    return '+'.join(sp['inds']) + ('' if len(sp['inds']) == 1 else f"({sp['weight']})")


def lookahead_test(spec, cuts=(195012, 197012, 199012), n_month_checks=60, seed=7):
    """(1) 切り詰め検査: French のデータを T 月で切って走らせた成績が、全データ（〜2000-12）で走らせた成績と T 月まで1ビットも違わない
       (2) 持ち高の検査: 無作為の月 m について、データを m−1 月で切って作った持ち高 = 全データで作った持ち高
       (3) 攪乱検査: m 月以降のリターン・社数・規模を乱数で壊しても、m 月の持ち高は変わらない
       → すべて通れば True（h.french を一時的に差し替えるだけ・環境変数は触らない）"""
    orig = h.french
    full = run(spec)
    res = {'cut_ok': True, 'weights_ok': True, 'perturb_ok': True, 'checked_months': 0}

    def cut_french(T):
        def f(name):
            d = orig(name)
            return {t: {c: {k: v for k, v in s.items() if (k // 100 if k > 999999 else (k if k > 9999 else k * 100 + 12)) <= T}
                        for c, s in cols.items()} for t, cols in d.items()}
        return f

    try:
        for T in cuts:
            h.french = cut_french(T)
            _cache.clear()
            part = run(spec)
            for m, v in part['ret'].items():
                if m <= T and abs(full['ret'].get(m, 1e9) - v) > 1e-12:
                    res['cut_ok'] = False
            for m, v in part['turnover'].items():
                if m <= T and abs(full['turnover'].get(m, 1e9) - v) > 1e-12:
                    res['cut_ok'] = False
        h.french = orig
        _cache.clear()
        r, cap = _load()
        rng = random.Random(seed)
        ms = sorted(full['ret'])
        for m in rng.sample(ms[1:], min(n_month_checks, len(ms) - 1)):
            w_full = weights(r, cap, m, spec)
            prev = h.add_months(m, -1)
            r_cut = {i: {k: v for k, v in s.items() if k <= prev} for i, s in r.items()}
            c_cut = {i: {k: v for k, v in s.items() if k <= prev} for i, s in cap.items()}
            w_cut = weights(r_cut, c_cut, m, spec)
            r_bad = {i: {k: (v if k <= prev else rng.uniform(-0.9, 3.0)) for k, v in s.items()} for i, s in r.items()}
            c_bad = {i: {k: (v if k <= prev else rng.uniform(0.001, 1e6)) for k, v in s.items()} for i, s in cap.items()}
            w_bad = weights(r_bad, c_bad, m, spec)
            if w_full != w_cut:
                res['weights_ok'] = False
            if w_full != w_bad:
                res['perturb_ok'] = False
            res['checked_months'] += 1
    finally:
        h.french = orig
        _cache.clear()
    res['ok'] = res['cut_ok'] and res['weights_ok'] and res['perturb_ok']
    return res


def select():
    assert h.PHASE == 'select'
    rows = []
    for sp in variants():
        x = run(sp)
        st = h.stats(x['ret'], x['bench'], x['rf'], turnover=x['turnover'], cost=x['cost'])
        tv = x['turnover']
        yrs = len(tv) / 12
        rows.append({'name': label(sp), 'spec': sp, 'excess': st['excess'], 't': st['t'], 't_nw': st['t_nw'],
                     'from': st['from'], 'to': st['to'], 'cagr': st['cagr'], 'bench_cagr': st['bench_cagr'],
                     'vol': st['vol'], 'bench_vol': st['bench_vol'], 'maxdd': st['maxdd'], 'bench_maxdd': st['bench_maxdd'],
                     'sharpe': st['sharpe'], 'bench_sharpe': st['bench_sharpe'], 'roll10_win': st['roll10_win'],
                     'turnover_per_year': round((sum(tv.values()) - 1) / yrs, 3), 'stats': st})
    return rows


if __name__ == '__main__':
    rows = select()
    for x in sorted(rows, key=lambda z: -(z['t'] or -9)):
        print(f"{x['name']:28s} {x['from']}-{x['to']} ex {x['excess']:6.2f} t {x['t']:5.2f} tNW {x['t_nw']:5.2f} "
              f"cagr {x['cagr']:6.2f}/{x['bench_cagr']:6.2f} vol {x['vol']}/{x['bench_vol']} dd {x['maxdd']}/{x['bench_maxdd']} "
              f"sh {x['sharpe']}/{x['bench_sharpe']} r10 {x['roll10_win']} tv/y {x['turnover_per_year']}")
