#!/usr/bin/env python3
"""night/edge/fam_bigmom.py — 系統 bigmom：大型株の買いだけ（French の 規模×特徴 の大型の組）

事前登録 out/edge_prereg.json（第1回）の一系統。読むだけ・門の採点に不使用。
  ・データは harness の french() / us_market() / french_region() だけで読む（選定の段では 2000-12 で切れる）
  ・組の中身は French が作る（勢い＝t−12〜t−2 の株価・毎月組み替え／簿価時価・収益性・投資＝毎年6月に前年度の決算で組み替え）
    ＝月 m のリターンに使う銘柄の選び方は m−1 月末までの情報だけ。この module が自分で作る信号は
    (a) 「悪い3割を除く」組の時価の重み（m−1 行の 社数×平均時価）と (b) 特徴の組どうしの勢い（m−1 月までのリターン）だけ。
    どちらも weights[m] が m−1 月までのデータだけで決まることを lookahead_test() で確かめる
  ・費用: 回転1あたり 0.25%（個別株の組）。回転は 勢い 200%/年・簿価時価/収益性/投資 50%/年 を月割り（事前登録どおり）＋
    組どうしの持ち高の戻し（実額）＋組の入れ替え（実額）
  ・相手: 米国市場（h.us_market）。他の市場: French の国際版の同じ組、相手はその地域の市場（h.french_region）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h

FAMILY = {
    'key': 'bigmom',
    'name': '大型株の勢いと割安を半分ずつ（買いだけ・毎月戻す）',
    'implement': ('米国の大型株（NYSE の中央値より大きい株）のうち、①直近12か月（最後の1か月を除く）の値上がりが上位3割の株の時価加重と、'
                  '②簿価時価比率が上位3割の株の時価加重を、半分ずつ持ち毎月半々へ戻す。'
                  '割安の側は楽天証券の米国ETF（成長投資枠でNISA可）の VTV・MGV・VOOV/SPYV が近い代わりになる。'
                  '勢いの側は楽天の米国ETF一覧（out/broker_lineup.json・742本）に MTUM・SPMO 等の勢いのETFが無く、'
                  'S&P500 の中で勢いの上位3割（約150社）を自分で組んで毎月入れ替えるしかない（回転が年200%前後なので NISA の枠を食い、実際は課税の特定口座）。'
                  '他社（SBI・マネックス）で勢いのETFを扱うかは未確認'),
}

VW = 'Average Value Weighted Returns -- Monthly'
COST = 0.0025                      # 回転1あたり（個別株の組）
# 袖: (米国のファイル, 良い側, 中, 悪い側, 年の回転)
SLEEVES = {
    'mom':   ('6_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 'ME2 PRIOR2', 'BIG LoPRIOR', 2.0),
    'val':   ('6_Portfolios_2x3', 'BIG HiBM', 'ME2 BM2', 'BIG LoBM', 0.5),
    'op':    ('6_Portfolios_ME_OP_2x3', 'BIG HiOP', 'ME2 OP2', 'BIG LoOP', 0.5),
    'inv':   ('6_Portfolios_ME_INV_2x3', 'BIG LoINV', 'ME2 INV2', 'BIG HiINV', 0.5),
    'mom25': ('25_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', None, None, 2.0),   # 最大の2割 × 勢いの上位2割
    'val25': ('25_Portfolios_5x5', 'BIG HiBM', None, None, 0.5),                # 最大の2割 × 簿価時価の上位2割
}
# 国際版のファイル名（French のサイトの実物で確認済み: {地域}_6_Portfolios_ME_Prior_12_2 / _ME_BE-ME / _ME_OP / _ME_INV）
INTL = {'mom': '{r}_6_Portfolios_ME_Prior_12_2', 'val': '{r}_6_Portfolios_ME_BE-ME',
        'op': '{r}_6_Portfolios_ME_OP', 'inv': '{r}_6_Portfolios_ME_INV',
        'mom25': '{r}_25_Portfolios_ME_Prior_12_2', 'val25': '{r}_25_Portfolios_ME_BE-ME'}
REGIONS = ['Developed_ex_US', 'Europe', 'Japan', 'Asia_Pacific_ex_Japan', 'North_America']


# ───────────────────────── 読み込み ─────────────────────────
def _table(d, want):
    for t in d:
        if want(t):
            return d[t]
    return None


def _monthly(s):
    return {k: v / 100 for k, v in s.items() if 99999 < k < 1000000}


def load_sleeve(name, fname):
    """→ {'hi': ret, 'mid': ret, 'n_hi','sz_hi','n_mid','sz_mid'}（リターンは小数・社数と平均時価は生値）"""
    _, hi, mid, lo, _ = SLEEVES[name]
    d = h.french(fname)
    vw = d[VW]
    out = {'hi': _monthly(vw[hi])}
    if mid:
        out['mid'] = _monthly(vw[mid])
        nf = _table(d, lambda t: t.startswith('Number of Firms'))
        sz = _table(d, lambda t: 'Firm Size' in t or 'Market Cap' in t)
        if nf and sz:
            for tag, col in (('hi', hi), ('mid', mid)):
                out['n_' + tag] = {k: v for k, v in nf[col].items() if k > 99999}
                out['sz_' + tag] = {k: v for k, v in sz[col].items() if k > 99999}
    return out


def load_us(names):
    return {n: load_sleeve(n, SLEEVES[n][0]) for n in names}


def load_region(region, names):
    return {n: load_sleeve(n, INTL[n].format(r=region)) for n in names}


# ───────────────────────── 規則の組み立て（純関数） ─────────────────────────
def sleeve_series(sd, form):
    """袖1本の月次リターン。form='hi'＝良い3割だけ／'exlow'＝悪い3割を除く（良い＋中を前月の時価で加重）。
    'exlow' の重み: 月 m は (社数×平均時価) の m−1 行 → m−1 月末より前の情報だけ（French の行が月初・月末どちらの時価でも安全側）"""
    if form == 'hi' or 'mid' not in sd:
        return dict(sd['hi']), None
    r, w = {}, {}
    for m in sd['hi']:
        if m not in sd['mid']:
            continue
        p = h.add_months(m, -1)
        try:
            ch = sd['n_hi'][p] * sd['sz_hi'][p]
            cm = sd['n_mid'][p] * sd['sz_mid'][p]
        except KeyError:
            continue
        if ch <= 0 or cm <= 0:
            continue
        a = ch / (ch + cm)
        w[m] = a
        r[m] = a * sd['hi'][m] + (1 - a) * sd['mid'][m]
    return r, w


def build(spec, data):
    """data: {袖: load_sleeve の出力} → {'ret','turnover','weights'}（費用の前）。
    spec: {'sleeves': [...], 'form': 'hi'|'exlow', 'rebalance': 'monthly'|'annual',
           'rotate': None | {'lookback': L, 'top': k}}"""
    names = spec['sleeves']
    form = spec.get('form', 'hi')
    ser, turn = {}, {}
    for n in names:
        ser[n], _ = sleeve_series(data[n], form)
        turn[n] = SLEEVES[n][4]
    ms = sorted(set.intersection(*[set(ser[n]) for n in names]))
    rot = spec.get('rotate')
    reb = spec.get('rebalance', 'monthly')
    ret, tov, wts = {}, {}, {}
    cur = None                       # 月初の実際の重み（前月の値動きで漂った後）
    for i, m in enumerate(ms):
        # ── 目標の重み（m−1 月までの情報だけ） ──
        if rot:
            L, k = rot['lookback'], rot['top']
            past = [h.add_months(m, -j) for j in range(1, L + 1)]
            if not all(p in ser[n] for n in names for p in past):
                continue                                    # 勢いを測れない月は持たない（系列の始まり）
            score = {}
            for n in names:
                g = 1.0
                for p in past:
                    g *= 1 + ser[n][p]
                score[n] = g
            pick = sorted(names, key=lambda n: (-score[n], names.index(n)))[:k]
            tgt = {n: (1.0 / k if n in pick else 0.0) for n in names}
        else:
            tgt = {n: 1.0 / len(names) for n in names}
        # 年1回の戻し: 1月にだけ目標へ戻す（それ以外は漂うまま）
        if reb == 'annual' and cur is not None and m % 100 != 1 and not rot:
            w = dict(cur)
        else:
            w = tgt
        # ── 回転: 袖の中（年率の置き値を月割り）＋ 袖どうしの戻し・入れ替え（実額） ──
        inner = sum(w[n] * turn[n] / 12 for n in names)
        if cur is None:
            shift = 0.0
        else:
            shift = 0.5 * sum(abs(w[n] - cur.get(n, 0.0)) for n in names)
        tov[m] = inner + shift
        r = sum(w[n] * ser[n][m] for n in names)
        ret[m] = r
        wts[m] = dict(w)
        # 月末の漂った重み
        tot = sum(w[n] * (1 + ser[n][m]) for n in names)
        cur = {n: w[n] * (1 + ser[n][m]) / tot for n in names} if tot > 0 else dict(w)
    return {'ret': ret, 'turnover': tov, 'weights': wts}


# ───────────────────────── run（統括が選定・検定の両方で呼ぶ） ─────────────────────────
def run(spec):
    names = spec['sleeves']
    us = load_us(names)
    b = build(spec, us)
    mkt, rf = h.us_market()
    out = {'ret': b['ret'], 'bench': mkt, 'rf': rf, 'turnover': b['turnover'], 'cost': COST, 'markets': {}}
    if all(n in INTL for n in names):
        for reg in REGIONS:
            try:
                d = load_region(reg, names)
                bb = build(spec, d)
                rm, rrf = h.french_region(reg)
            except Exception as e:                            # 取れない地域は黙って捨てず名前を残す
                out.setdefault('markets_missing', {})[reg] = str(e)[:120]
                continue
            if bb['ret']:
                out['markets'][reg] = {'ret': bb['ret'], 'bench': rm, 'rf': rrf, 'turnover': bb['turnover'], 'cost': COST}
    return out


# ───────────────────────── 先読みの検査 ─────────────────────────
def lookahead_test(spec, data, cuts=(195012, 197006, 198512, 199606), seed=7):
    """(1) m 以降の全データ（リターン・社数・時価）を乱しても、weights[m] と m より前のリターンが変わらない
         ＝月 m の持ち方は m−1 月までの情報だけで決まる
       (2) データを m−1 で切って組み立てても、m−1 までのリターン・重みが全データの場合と一致する
    → 失敗した項目の一覧（空なら合格）"""
    import random
    rnd = random.Random(seed)
    base = build(spec, data)
    bad = []
    for X in cuts:
        pert = {}
        for n, sd in data.items():
            pert[n] = {key: {m: (v * (1 + rnd.uniform(-0.9, 0.9)) + rnd.uniform(-0.05, 0.05) if m >= X else v)
                             for m, v in s.items()} for key, s in sd.items()}
        pb = build(spec, pert)
        for m in base['weights']:
            if m <= X:
                if m not in pb['weights'] or any(abs(base['weights'][m][k] - pb['weights'][m][k]) > 1e-12 for k in base['weights'][m]):
                    bad.append(f'perturb {X}: weights[{m}] changed')
                    break
        for m in base['ret']:
            if m < X and abs(base['ret'][m] - pb['ret'].get(m, 9)) > 1e-12:
                bad.append(f'perturb {X}: ret[{m}] changed')
                break
        tr = {n: {key: {m: v for m, v in s.items() if m < X} for key, s in sd.items()} for n, sd in data.items()}
        tb = build(spec, tr)
        for m in tb['ret']:
            if abs(tb['ret'][m] - base['ret'][m]) > 1e-12 or abs(tb['turnover'][m] - base['turnover'][m]) > 1e-12:
                bad.append(f'truncate {X}: month {m} differs')
                break
    return bad
