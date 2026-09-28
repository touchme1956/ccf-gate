#!/usr/bin/env python3
"""night/edge/fam_ctrymom.py — 系統 ctrymom: 国の勢いの入れ替え（事前登録 out/edge_prereg.json・第1回）

規則: 毎月末に、各国（French 21か国の時価加重・米ドル建て＋米国市場）の過去 J か月のリターン
（直近 skip か月を飛ばす）を比べ、上位 k 国を等加重で翌1か月持つ。
任意で『自分の12か月が短期金利の12か月を下回る国は、その枠を現金（短期金利）にする』（絶対の勢い）。
相手（主）: 同じ国の集合の等加重（毎月リバランス）。

★先読みの禁止: 月 m の持ち高は m−1 月末までのリターンだけで決める（target_weights は hist の m 未満しか見ない）。
  国の集合（資格）も m−1 月末までに分かること（直近13か月のデータがそろっているか）だけで決める。
  資格のある国の月 m のリターンが欠けていたら、その枠は規則・相手とも現金（短期金利）とする（欠けていることを先に知らない）。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h  # noqa: E402

FAMILY = {
    'key': 'ctrymom',
    'name': '国の勢いの入れ替え（過去の上位国を等加重で1か月持つ）',
    'implement': ('毎月末に各国の株価指数（配当込み・米ドル）の過去リターンを比べ、上位の国の国別ETF（iShares MSCI の EWJ/EWG/EWU/EWA/EWC/EWQ/EWL/EWD…、'
                  '米国は IVV/VTI）を等額で翌月持つ。⚠ 2026-09 時点の楽天証券の米国ETFの取扱では 21か国のうち EWJ/EWG/EWS/EWM（と DAX）しか無い'
                  '（EWU/EWA/EWC/EWQ/EWH 等は無い）ので、楽天だけでは実行できない——国別ETFを広く扱う証券会社（SBI・マネックス等の取扱を要確認）か、'
                  '欠ける国を地域ETF（VGK/EPP/EFA）で代える必要がある。毎月の入れ替えは NISA の成長投資枠を急速に消費する（売っても枠は翌年まで戻らない）ので、'
                  '実務は課税口座（特定口座）。売買益に 20.315% の税（主の判定には入れない）。国別ETFの経費 0.5%/年前後は相手（同じETFの等加重）と相殺する前提'),
}

LOOK_MAX = 13            # 資格: 直近13か月（12か月＋飛ばし1か月）のデータがそろっている国（変種によらず同じ集合＝同じ相手）
COST = 0.001             # 事前登録: 指数・ETF・国の入れ替えは片道の回転100%につき 0.10%


def load(include_us=True):
    """{国: {YYYYMM: 小数}}, rf。French 21か国（米ドル）＋米国市場（1975-01〜にそろえる）"""
    c = h.french_countries('Dollar')
    mkt, rf = h.us_market()
    start = min(min(v) for v in c.values() if v)
    if include_us:
        c = dict(c)
        c['US'] = {m: x for m, x in mkt.items() if m >= start}
    return c, rf


def _cum(ser, ms):
    g = 1.0
    for m in ms:
        g *= 1 + ser[m]
    return g - 1


def eligible(data, m):
    """月 m に持てる国: m−LOOK_MAX … m−1 のリターンがすべてある国（m−1 月末までに分かる）"""
    win = [h.add_months(m, -i) for i in range(1, LOOK_MAX + 1)]
    return sorted(k for k, s in data.items() if all(w in s for w in win))


def signal(ser, m, J, skip):
    """過去 J か月（直近 skip か月を飛ばす）の累積リターン。使う月は m−skip−J … m−skip−1（すべて m 未満）"""
    ms = [h.add_months(m, -(skip + i)) for i in range(1, J + 1)]
    return _cum(ser, ms)


def target_weights(data, rf, m, spec):
    """月 m の持ち高 {国 or 'CASH': 重み}。m 未満のデータしか読まない"""
    univ = eligible(data, m)
    if not univ:
        return {}
    Js = spec['J'] if isinstance(spec['J'], list) else [spec['J']]
    skip = spec.get('skip', 1)
    if len(Js) == 1:
        score = {c: signal(data[c], m, Js[0], skip) for c in univ}
    else:                                               # 複数の窓の順位の平均（窓の選び方への依存を減らす）
        score = {c: 0.0 for c in univ}
        for J in Js:
            r = {c: signal(data[c], m, J, skip) for c in univ}
            order = sorted(univ, key=lambda c: (r[c], c))
            for i, c in enumerate(order):
                score[c] += i / len(Js)
    k = spec['k']
    if isinstance(k, str) and k.startswith('frac'):     # 上位の割合（例 'frac3' = 上位1/3）
        k = max(1, round(len(univ) / int(k[4:])))
    k = min(int(k), len(univ))
    top = sorted(univ, key=lambda c: (-score[c], c))[:k]
    w = {}
    for c in top:
        if spec.get('abs'):
            ms = [h.add_months(m, -(skip + i)) for i in range(1, 13)]
            own = _cum(data[c], ms)
            rfc = _cum(rf, ms) if all(x in rf for x in ms) else 0.0
            if own < rfc:
                w['CASH'] = w.get('CASH', 0.0) + 1 / k
                continue
        w[c] = w.get(c, 0.0) + 1 / k
    return w


def _period_ret(w, data, rf, m):
    """持ち高 w の月 m のリターンと、月末の（値動き後の）重み。月 m のリターンが欠けた国は現金扱い"""
    r_of = {}
    for c in w:
        if c == 'CASH':
            r_of[c] = rf.get(m, 0.0)
        else:
            r_of[c] = data[c].get(m, rf.get(m, 0.0))
    rp = sum(w[c] * r_of[c] for c in w)
    drift = {c: w[c] * (1 + r_of[c]) / (1 + rp) for c in w} if rp > -1 else {}
    return rp, drift


def _turnover(new, old_drift):
    keys = set(new) | set(old_drift)
    return 0.5 * sum(abs(new.get(c, 0.0) - old_drift.get(c, 0.0)) for c in keys)


def backtest(spec, data=None, rf=None):
    include_us = spec.get('us', True)
    if data is None:
        data, rf = load(include_us)
    months = sorted(set().union(*[set(s) for s in data.values()]))
    first = h.add_months(months[0], LOOK_MAX)
    ret, bench, tov, W = {}, {}, {}, {}
    prev = {'CASH': 1.0}
    for m in h.month_range(first, months[-1]):
        univ = eligible(data, m)
        if not univ:
            continue
        w = target_weights(data, rf, m, spec)
        tov[m] = _turnover(w, prev)
        ret[m], prev = _period_ret(w, data, rf, m)
        bw = {c: 1 / len(univ) for c in univ}
        bench[m], _ = _period_ret(bw, data, rf, m)
        W[m] = w
    return ret, bench, tov, W, data, rf


def run(spec):
    ret, bench, tov, W, data, rf = backtest(spec)
    return {'ret': ret, 'bench': bench, 'rf': {m: rf[m] for m in ret if m in rf},
            'turnover': tov, 'cost': COST, 'markets': {}}


def us_compare(spec):
    """事前登録: 米国市場との差も併記（費用後）"""
    r = run(spec)
    mkt, rf = h.us_market()
    return h.stats(r['ret'], mkt, rf, turnover=r['turnover'], cost=r['cost'])


# ───────────────────────── 先読みの検査 ─────────────────────────
def lookahead_test(specs, seed=7):
    """3通りで確かめる（すべての月・与えた全変種で）:
    (1) 月 m 以降のリターン（国・短期金利とも）を乱数に置き換えても、月 m の持ち高が変わらない
    (2) 月 m 以降のデータを消しても（切り詰め）、月 m の持ち高が変わらない
    (3) 末尾に月を足しても（データを1か月ずつ延ばしても）、それまでの月の持ち高・リターン・相手が1つも変わらない"""
    import random
    rnd = random.Random(seed)
    n_chk = 0
    for spec in specs:
        data, rf = load(spec.get('us', True))
        _, _, _, W, _, _ = backtest(spec, data, rf)
        ms = sorted(W)
        for m in ms[::3]:
            noisy = {c: {k: (v if k < m else rnd.uniform(-0.5, 0.5)) for k, v in s.items()} for c, s in data.items()}
            noisy_rf = {k: (v if k < m else rnd.uniform(0, 0.02)) for k, v in rf.items()}
            assert target_weights(noisy, noisy_rf, m, spec) == W[m], ('乱数で変わった', spec, m)
            trunc = {c: {k: v for k, v in s.items() if k < m} for c, s in data.items()}
            trunc_rf = {k: v for k, v in rf.items() if k < m}
            assert target_weights(trunc, trunc_rf, m, spec) == W[m], ('切り詰めで変わった', spec, m)
            n_chk += 2
        cut = ms[len(ms) // 2]
        short = {c: {k: v for k, v in s.items() if k <= cut} for c, s in data.items()}
        r1, b1, t1, W1, _, _ = backtest(spec, short, rf)
        r2, b2, t2, W2, _, _ = backtest(spec, data, rf)
        for m in W1:
            assert W1[m] == W2[m] and r1[m] == r2[m] and b1[m] == b2[m] and t1[m] == t2[m], ('延ばして過去が変わった', spec, m)
            n_chk += 1
    return n_chk


# ───────────────────────── 選定（EDGE_PHASE=select でだけ） ─────────────────────────
def variants():
    V = []
    for J in (3, 6, 12):                                     # 主の格子 18
        for k in (3, 5, 7):
            for ab in (False, True):
                V.append({'J': J, 'skip': 1, 'k': k, 'abs': ab, 'us': True})
    for J in (3, 6, 12):                                     # 飛ばさない 3
        V.append({'J': J, 'skip': 0, 'k': 5, 'abs': False, 'us': True})
    for J, ab in ((12, False), (12, True), (6, False)):      # 米国を入れない 3
        V.append({'J': J, 'skip': 1, 'k': 5, 'abs': ab, 'us': False})
    for k, ab in ((3, False), (5, False), (7, False), (5, True)):   # 3/6/12 の順位の平均 4
        V.append({'J': [3, 6, 12], 'skip': 1, 'k': k, 'abs': ab, 'us': True})
    for J in (6, 12):                                        # 上位1/3 2
        V.append({'J': J, 'skip': 1, 'k': 'frac3', 'abs': False, 'us': True})
    return V


def vname(s):
    J = '+'.join(map(str, s['J'])) if isinstance(s['J'], list) else s['J']
    return f"J{J}-{s['skip']} k{s['k']}{' 絶対' if s['abs'] else ''}{'' if s['us'] else ' 米国なし'}"


if __name__ == '__main__':
    assert h.PHASE == 'select'
    import json
    rows = []
    for s in variants():
        r = run(s)
        st = h.stats(r['ret'], r['bench'], r['rf'], turnover=r['turnover'], cost=r['cost'])
        to = sum(r['turnover'].values()) / len(r['turnover']) * 12
        rows.append((vname(s), s, st, to))
        print(f"{vname(s):28} 超過 {st['excess']:6.2f}  t {st['t']:5.2f}  NW {st['t_nw']:5.2f}  年率 {st['cagr']:6.2f} vs {st['bench_cagr']:6.2f}  "
              f"ぶれ {st['vol']}/{st['bench_vol']}  下落 {st['maxdd']}/{st['bench_maxdd']}  10年 {st['roll10_win']}  回転 {to:.1f}/年  {st['from']}-{st['to']}")
    print('試した数', len(rows))
