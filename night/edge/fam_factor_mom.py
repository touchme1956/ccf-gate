#!/usr/bin/env python3
"""night/edge/fam_factor_mom.py — 系統 factor_mom（第2回）：因子の勢い＝大型の組の入れ替え

事前登録 out/edge_prereg.json の一系統。読むだけ・門の採点に不使用。
  ・素材は French の 2×3 の組の**大型の側**だけ（8組）:
      BIG HiBM / BIG LoBM（6_Portfolios_2x3・1926-07〜）・BIG HiPRIOR / BIG LoPRIOR（6_Portfolios_ME_Prior_12_2・1927-01〜）・
      BIG HiOP / BIG LoOP（6_Portfolios_ME_OP_2x3・1963-07〜）・BIG LoINV / BIG HiINV（6_Portfolios_ME_INV_2x3・1963-07〜）
    1963 年より前は取れる4組だけで回す（組が増えるのは「その組の過去 J か月がそろった月」から＝月 m−1 までの情報で決まる）
  ・規則: 月 m の持ち方は **m−1 月末までの各組のリターンだけ**で決める（過去 J か月の複利で順位 → 上位 k 組を等分で1か月）
  ・費用: 回転1あたり 0.25%（個別株の組）。回転＝組の入れ替え・戻し（実額。組どうしは重なりが無いと置く＝保守側）
          ＋組の中の回転（勢いの組 200%/年・簿価時価/収益性/投資の組 50%/年 を月割り＝事前登録の置き値）
  ・相手: 米国市場（h.us_market）。他の市場: French の国際版の同じ6組（地域ごと・1990〜）、相手はその地域の市場
  ・データは harness の french() / us_market() / french_region() だけで読む（選定の段では 2000-12 で切れる）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h

FAMILY = {
    'key': 'factor_mom',
    'name': '大型株の「型」の勢いの入れ替え（割安/成長・勢い・収益性・投資の8組から直近の勝ち組を持つ）',
    'implement': ('米国の大型株を8つの「型」（割安・成長〔高PBR〕・勢いの上位/下位・高収益/低収益・投資控えめ/積極）に分け、'
                  '毎月、直近の成績が良かった型を等分で持ち、翌月に入れ替える。'
                  '楽天証券（成長投資枠＝NISA可）の米国ETFで近いもの: 割安 VTV/SPYV・成長 VUG/SPYG・高収益 QUAL（近似）・'
                  '配当/低投資 DGRW（近似）。ただし勢いの上位/下位・低収益・積極投資の型に対応するETFは楽天の一覧（out/broker_lineup.json）に無く、'
                  'その型が選ばれた月は S&P500 の中で自分で銘柄を組むしかない（勢いの型は年200%前後の回転＝課税の特定口座）。'
                  '毎月の入れ替えは NISA の枠（売った枠は翌年まで戻らない）と相性が悪く、実際は特定口座（売買益に20.315%）になる'),
}

VW = 'Average Value Weighted Returns -- Monthly'
COST = 0.0025                     # 回転1あたり（個別株の組・事前登録）
TURN = {'bm': 0.5, 'prior': 2.0, 'op': 0.5, 'inv': 0.5}   # 組の中の片道回転（年）
# (組の名前, ファイルの種類, 列)
BIG8 = [('val_hi', 'bm', 'BIG HiBM'), ('val_lo', 'bm', 'BIG LoBM'),
        ('mom_hi', 'prior', 'BIG HiPRIOR'), ('mom_lo', 'prior', 'BIG LoPRIOR'),
        ('op_hi', 'op', 'BIG HiOP'), ('op_lo', 'op', 'BIG LoOP'),
        ('inv_lo', 'inv', 'BIG LoINV'), ('inv_hi', 'inv', 'BIG HiINV')]
MID4 = [('val_mid', 'bm', 'ME2 BM2'), ('mom_mid', 'prior', 'ME2 PRIOR2'),
        ('op_mid', 'op', 'ME2 OP2'), ('inv_mid', 'inv', 'ME2 INV2')]
US_FILES = {'bm': '6_Portfolios_2x3', 'prior': '6_Portfolios_ME_Prior_12_2',
            'op': '6_Portfolios_ME_OP_2x3', 'inv': '6_Portfolios_ME_INV_2x3'}
INTL_FILES = {'bm': '{p}_6_Portfolios_ME_BE-ME', 'prior': '{p}_6_Portfolios_ME_Prior_12_2',
              'op': '{p}_6_Portfolios_ME_OP', 'inv': '{p}_6_Portfolios_ME_INV'}
# 再現に使う地域（互いに重ならない4つ。North_America は米国と、Developed_ex_US は下の3つと重なるので入れない）
REGIONS = {'Europe': 'Europe', 'Japan': 'Japan', 'Asia_Pacific_ex_Japan': 'Asia_Pacific_ex_Japan',
           'Emerging': 'Emerging_Markets'}
MKT = '__mkt__'                   # 市場（vs_mkt の逃げ場）


# ───────────────────────── 読み込み ─────────────────────────
def _monthly(s):
    return {k: v / 100 for k, v in s.items() if 99999 < k < 1000000}


def _groups(spec):
    return BIG8 + (MID4 if spec.get('universe') == 'big8+mid' else [])


def load(files, groups):
    """files: {種類: French のファイル名} → {'ser': {組: ret}, 'turn': {組: 年回転}, 'order': [...]}"""
    cache, ser, turn, order = {}, {}, {}, []
    for g, kind, col in groups:
        if kind not in cache:
            d = h.french(files[kind])
            cache[kind] = d[VW] if VW in d else d[next(iter(d))]
        s = _monthly(cache[kind][col])
        if s:
            ser[g], turn[g] = s, TURN[kind]
            order.append(g)
    return {'ser': ser, 'turn': turn, 'order': order}


def region_market(region):
    """(mkt, rf)。Emerging は french_region の名前（Emerging_3_Factors）が無いので Emerging_5_Factors から作る"""
    if region != 'Emerging':
        return h.french_region(region)
    d = h.french('Emerging_5_Factors')
    t = next(iter(d))
    mk, rf = d[t]['Mkt-RF'], d[t]['RF']
    return ({k: (mk[k] + rf[k]) / 100 for k in mk if k in rf and 99999 < k < 1000000},
            {k: rf[k] / 100 for k in rf if 99999 < k < 1000000})


# ───────────────────────── 規則（純関数） ─────────────────────────
def _cum(s, past):
    g = 1.0
    for p in past:
        g *= 1 + s[p]
    return g - 1


def _score(spec, s, m):
    """組 s の月 m の点（m−1 月までのデータだけ）。取れなければ None"""
    sc = spec.get('score', 'ret')
    skip = spec.get('skip', 0)
    if sc == 'blend':                               # 3・6・12 か月の順位の平均は _pick で扱う（ここは各窓の複利）
        out = []
        for J in (3, 6, 12):
            past = [h.add_months(m, -j) for j in range(1 + skip, J + 1 + skip)]
            if not all(p in s for p in past):
                return None
            out.append(_cum(s, past))
        return out
    J = spec['lookback']
    past = [h.add_months(m, -j) for j in range(1 + skip, J + 1 + skip)]
    if not all(p in s for p in past):
        return None
    if sc == 'sharpe':                              # 過去 J か月の平均÷ぶれ（ぶれで割った勢い）
        xs = [s[p] for p in past]
        mu = sum(xs) / len(xs)
        sd = (sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5
        return mu / sd if sd > 0 else None
    return _cum(s, past)


def _target(spec, data, m):
    """月 m の目標の重み（m−1 月までの情報だけ）。持てない月は None"""
    ser, order = data['ser'], data['order']
    mode = spec.get('mode', 'cs')
    avail = [g for g in order if m in ser[g]]                    # 月 m にリターンのある組（系列の途中の欠測は無い）
    sc = {}
    for g in avail:
        v = _score(spec, ser[g], m)
        if v is not None:
            sc[g] = v
    cand = [g for g in order if g in sc]
    if mode == 'vs_mkt':
        mk = data.get('mkt') or {}
        if m not in mk:
            return None
        ms = _score(spec, mk, m)
        if ms is None or len(cand) < 2:
            return None
        win = [g for g in cand if sc[g] > ms]
        if not win:
            return {MKT: 1.0}
        return {g: 1.0 / len(win) for g in win}
    k = spec['top']
    if len(cand) <= k:                                          # 選ぶ余地が無い月は持たない（系列の始まり）
        return None
    if spec.get('score') == 'blend':
        rank = {g: 0.0 for g in cand}
        for i in range(3):
            srt = sorted(cand, key=lambda g: (-sc[g][i], order.index(g)))
            for r, g in enumerate(srt):
                rank[g] += r
        pick = sorted(cand, key=lambda g: (rank[g], order.index(g)))[:k]
    else:
        pick = sorted(cand, key=lambda g: (-sc[g], order.index(g)))[:k]
    return {g: 1.0 / k for g in pick}


def build(spec, data):
    """→ {'ret','turnover','weights'}（費用の前）。hold>1 なら hold か月ごとに（系列の最初の月から数えて）入れ替える"""
    ser, turn = data['ser'], dict(data['turn'])
    mk = data.get('mkt') or {}
    turn[MKT] = 0.0
    allm = sorted(set().union(*[set(s) for s in ser.values()]))
    hold = spec.get('hold', 1)
    ret, tov, wts = {}, {}, {}
    cur, age, prev = None, 0, None
    for m in allm:
        if prev is not None and h.add_months(prev, 1) != m:      # 月が飛んだら持ち高を捨てて出直す
            cur, age = None, 0
        tgt = _target(spec, data, m)
        if tgt is None:
            cur, age, prev = None, 0, m
            continue
        if cur is not None and hold > 1 and age % hold != 0:
            w = {g: v for g, v in cur.items() if v > 0}           # 入れ替えない月は漂うまま
            if any(g != MKT and m not in ser[g] or g == MKT and m not in mk for g in w):
                w = tgt
                age = 0
        else:
            w = tgt
            age = 0
        rr = {g: (mk[m] if g == MKT else ser[g][m]) for g in w}
        inner = sum(w[g] * turn[g] / 12 for g in w)
        if cur is None:
            shift = 0.0                                           # 最初の月の建てる費用は数えない（相手も同じ）
        else:
            keys = set(w) | set(cur)
            shift = 0.5 * sum(abs(w.get(g, 0.0) - cur.get(g, 0.0)) for g in keys)
        tov[m] = inner + shift
        ret[m] = sum(w[g] * rr[g] for g in w)
        wts[m] = dict(w)
        tot = sum(w[g] * (1 + rr[g]) for g in w)
        cur = {g: w[g] * (1 + rr[g]) / tot for g in w} if tot > 0 else dict(w)
        age += 1
        prev = m
    return {'ret': ret, 'turnover': tov, 'weights': wts}


# ───────────────────────── run（統括が選定・検定の両方で呼ぶ） ─────────────────────────
def run(spec):
    groups = _groups(spec)
    us = load(US_FILES, groups)
    mkt, rf = h.us_market()
    us['mkt'] = mkt
    b = build(spec, us)
    out = {'ret': b['ret'], 'bench': mkt, 'rf': rf, 'turnover': b['turnover'], 'cost': COST, 'markets': {}}
    for reg, prefix in REGIONS.items():
        try:
            files = {k: v.format(p=prefix) for k, v in INTL_FILES.items()}
            d = load(files, groups)
            rm, rrf = region_market(reg)
            d['mkt'] = rm
            bb = build(spec, d)
        except Exception as e:                                    # 取れない地域は黙って捨てず名前を残す
            out.setdefault('markets_missing', {})[reg] = str(e)[:120]
            continue
        if bb['ret']:
            out['markets'][reg] = {'ret': bb['ret'], 'bench': rm, 'rf': rrf, 'turnover': bb['turnover'], 'cost': COST}
    return out


# ───────────────────────── 先読みの検査 ─────────────────────────
def lookahead_test(spec, data, cuts=(193506, 195012, 196912, 198512, 199606), seed=11):
    """(1) 月 X 以降の全データ（組と市場のリターン）を乱しても、weights[m]（m ≤ X）・回転（m ≤ X）と
           リターン（m < X）が変わらない＝月 m の持ち方は m−1 月までの情報だけで決まる
       (2) データを X−1 月で切って組み立てても、X−1 までのリターン・回転・重みが全データのときと一致する
       (3) 1か月ずらし: 組 g の月 m のリターンだけを変えると、weights[m] は変わらず weights[m+1] 以降だけが動きうる
    → 失敗の一覧（空なら合格）"""
    import random
    rnd = random.Random(seed)
    base = build(spec, data)
    bad = []

    def pert_series(s, X):
        return {m: (v * (1 + rnd.uniform(-0.9, 0.9)) + rnd.uniform(-0.05, 0.05) if m >= X else v) for m, v in s.items()}

    for X in cuts:
        pd = {'ser': {g: pert_series(s, X) for g, s in data['ser'].items()}, 'turn': data['turn'], 'order': data['order'],
              'mkt': pert_series(data.get('mkt') or {}, X)}
        pb = build(spec, pd)
        for m in base['weights']:
            if m <= X and (m not in pb['weights'] or base['weights'][m] != pb['weights'][m]
                           or abs(base['turnover'][m] - pb['turnover'][m]) > 1e-12):
                bad.append(f'perturb {X}: weights/turnover[{m}] changed'); break
        for m in base['ret']:
            if m < X and abs(base['ret'][m] - pb['ret'].get(m, 9)) > 1e-12:
                bad.append(f'perturb {X}: ret[{m}] changed'); break
        td = {'ser': {g: {m: v for m, v in s.items() if m < X} for g, s in data['ser'].items()}, 'turn': data['turn'],
              'order': data['order'], 'mkt': {m: v for m, v in (data.get('mkt') or {}).items() if m < X}}
        td['ser'] = {g: s for g, s in td['ser'].items() if s}
        td['order'] = [g for g in data['order'] if g in td['ser']]
        tb = build(spec, td)
        for m in tb['ret']:
            if (abs(tb['ret'][m] - base['ret'][m]) > 1e-12 or abs(tb['turnover'][m] - base['turnover'][m]) > 1e-12
                    or tb['weights'][m] != base['weights'][m]):
                bad.append(f'truncate {X}: month {m} differs'); break
    # (3) 同じ月のリターンを大きく変えても、その月の重みは変わらない
    ms = sorted(base['weights'])
    for m in ms[len(ms) // 7::max(1, len(ms) // 9)][:8]:
        for g in list(data['ser'])[:8]:
            if m not in data['ser'][g]:
                continue
            pd = {'ser': dict(data['ser']), 'turn': data['turn'], 'order': data['order'], 'mkt': data.get('mkt')}
            s = dict(data['ser'][g]); s[m] = s[m] + 0.5 if s[m] < 0 else s[m] - 0.5
            pd['ser'][g] = s
            pb = build(spec, pd)
            if pb['weights'].get(m) != base['weights'][m]:
                bad.append(f'same-month: weights[{m}] moved when {g} ret[{m}] changed'); break
    return bad
