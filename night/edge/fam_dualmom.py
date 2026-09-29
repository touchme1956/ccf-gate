#!/usr/bin/env python3
"""night/edge/fam_dualmom.py — 系統 dualmom: 二重の勢い（Antonacci 2014『Dual Momentum Investing』の GEM）

事前登録 out/edge_prereg.json（第1回）の一系統。読むだけ・門の採点に不使用。

  規則（毎月末に決めて翌月1か月持つ）:
    ① 絶対の勢い: 米国株の過去 L か月のリターン > 短期金利の過去 L か月 なら株の側へ。そうでなければ降りる。
    ② 相対の勢い: 株の側なら、米国と米国外のうち過去 L か月の良い方を丸ごと持つ。
    ③ 降りた先: 10年国債（FRED DGS10 の月末利回りから作る）／短期金利（French RF）／勢いで国債と短期金利を選ぶ。
  資産:
    米国   = Ken French 米国市場（CRSP 全上場の時価加重・配当込み）＝相手と同じもの
    米国外 = French 21か国（米ドル・時価加重）の等加重（〜1990-06）→ French Developed_ex_US（時価加重・米ドル・1990-07〜）
    国債   = 10年の固定満期の国債を毎月買い直す想定（利付・半年複利の価格式。月末の利回りを使う＝月平均の利回りで作ると
             降りた月に前月後半の金利低下を取り込む偏りが出るので使わない）
    短期金利 = French RF（1か月物の国債）
  先読みの禁止: 月 m の持ち高は m−1 月末までのリターンだけで決める（_weights の中で m−1 までしか見ない）。
             _lookahead_test() が「月 c 以降のデータを乱数に置き換えても、月 c までの持ち高が1つも変わらない」ことを確かめる。
"""
import sys, os, math, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h

FAMILY = {
    'key': 'dualmom',
    'name': '二重の勢い（米国株⇄米国外株⇄債券・Antonacci GEM）',
    'implement': ('楽天証券の特定口座（課税）で、米国株＝VTI（または楽天・全米株式インデックス・ファンド）、'
                  '米国外株＝VEA / VXUS（または eMAXIS Slim 全世界株式〔除く米国〕）、降りた先＝IEF（米国7-10年国債）'
                  'またはSHV/BIL（短期国債）のうち一つを丸ごと持ち、毎月末に1回だけ判定して入れ替える。'
                  'NISA は向かない（売ると枠が翌年まで戻らず、年に数回の全額入れ替えで年間の投資枠を使い切る）。'
                  '入れ替えのたびに売却益に 20.315% の税がかかる（主の判定には入れていない）。'),
}
START = 197601          # 米国外（1975-01〜）の12か月の勢いがそろう最初の月。変種どうしを同じ窓で比べるため全変種この月から
COST = 0.001            # 事前登録: 指数・ETF の入れ替えは片道の回転100%につき 0.10%
SPLICE = 199007         # この月から米国外を French Developed_ex_US（時価加重）へ


# ───────────────────────── 資産の系列 ─────────────────────────
def _par_bond_ret(y0, y1, n=10.0):
    """月初に利回り y0 の利付債（満期 n 年・半年払い・額面で買う）を買い、1か月後に利回り y1 で評価したリターン"""
    c = y0
    T = n - 1 / 12
    k = 2 * T
    if y1 <= 0:
        p = c / 2 * k + 1
    else:
        v = (1 + y1 / 2) ** (-k)
        p = c / y1 * (1 - v) + v
    return p - 1 + c / 12


def bond10():
    """{YYYYMM: 月次リターン} 10年国債（FRED DGS10 の月末値。1962-02〜）"""
    y = h.fred('DGS10')
    out = {}
    for m in sorted(y):
        p = h.add_months(m, -1)
        if p in y:
            out[m] = _par_bond_ret(y[p] / 100, y[m] / 100)
    return out


def bond10_shiller_avg():
    """参考（選ばない）: Shiller の GS10（月平均の利回り）から同じ式で作る版。月平均は前月後半の動きを翌月へ持ち越す"""
    rows = h.shiller()
    y = {r['m']: r['GS10'] for r in rows if r.get('GS10')}
    out = {}
    for m in sorted(y):
        p = h.add_months(m, -1)
        if p in y:
            out[m] = _par_bond_ret(y[p] / 100, y[m] / 100)
    return out


def nonus(kind='splice'):
    """{YYYYMM: 月次リターン（米ドル）} 米国外の株。
    'ew'     = French 21か国（米国を含まない）の等加重（その月に値がある国だけ・毎月等加重に戻す）。1975-01〜
    'splice' = 'ew' を 1990-06 まで、1990-07 から French Developed_ex_US（時価加重＝VEA に近い）"""
    c = h.french_countries('Dollar')
    months = sorted(set().union(*[set(v) for v in c.values()]))
    ew = {}
    for m in months:
        xs = [v[m] for v in c.values() if m in v]
        if len(xs) >= 10:
            ew[m] = sum(xs) / len(xs)
    if kind == 'ew':
        return ew
    dx, _ = h.french_region('Developed_ex_US')
    out = {m: v for m, v in ew.items() if m < SPLICE}
    out.update({m: v for m, v in dx.items() if m >= SPLICE})
    return out


def inputs(nonus_kind='splice', bond_kind='fred'):
    us, rf = h.us_market()
    return {'US': us, 'RF': rf, 'XUS': nonus(nonus_kind),
            'BOND': bond10() if bond_kind == 'fred' else bond10_shiller_avg()}


# ───────────────────────── 規則 ─────────────────────────
def _cum(r, m, L, skip=0):
    """月 m の判定に使う過去リターン: 月 m−L … m−1−skip の複利。欠けがあれば None（m 以降は見ない）"""
    g = 1.0
    for k in range(skip + 1, L + 1):
        mm = h.add_months(m, -k)
        if mm not in r:
            return None
        g *= 1 + r[mm]
    return g - 1


def _score(r, m, spec):
    """勢いの点。lookback が数なら L か月、'blend' なら 3・6・12 か月の平均"""
    lb = spec.get('lookback', 12)
    skip = spec.get('skip', 0)
    Ls = (3, 6, 12) if lb == 'blend' else (lb,)
    xs = [_cum(r, m, L, skip) for L in Ls]
    if any(x is None for x in xs):
        return None
    return sum(xs) / len(xs)


def _pick_one(inp, m, spec):
    """月 m に持つ一つの資産（'US'|'XUS'|'BOND'|'RF'）。m−1 月末までのリターンだけを使う。決められなければ None"""
    s = {k: _score(inp[k], m, spec) for k in ('US', 'XUS', 'RF', 'BOND')}
    mode = spec.get('mode', 'gem')
    safe = spec.get('safe', 'bond')
    need = ['US', 'RF'] + (['XUS'] if mode != 'abs_only' else []) + (['BOND'] if safe in ('bond', 'bondmom') else [])
    if any(s[k] is None for k in need):
        return None
    if safe == 'bond':
        off = 'BOND'
    elif safe == 'rf':
        off = 'RF'
    else:                                             # 'bondmom': 国債の勢い > 短期金利 なら国債、そうでなければ短期金利
        off = 'BOND' if s['BOND'] > s['RF'] else 'RF'
    if mode == 'rel_only':                            # 参考: 相対だけ（いつも株）
        return 'US' if s['US'] >= s['XUS'] else 'XUS'
    if mode == 'abs_only':                            # 参考: 絶対だけ（米国⇄降りた先）
        return 'US' if s['US'] > s['RF'] else off
    best = 'US' if s['US'] >= s['XUS'] else 'XUS'
    if mode == 'abs_on_best':                         # 絶対の勢いを「選んだ方」で測る
        return best if s[best] > s['RF'] else off
    return best if s['US'] > s['RF'] else off         # GEM（Antonacci）: 絶対の勢いは米国で測る


def _weights(inp, spec, months):
    """{m: {資産: 重み}}。'ensemble' は lookback 3・6・12 の三つの GEM の持ち高を 1/3 ずつ（ずらした平均）"""
    lag = spec.get('signal_lag', 0)                   # 参考（選ばない）: 判定を lag か月遅らせる（実行の遅れの上限の目安）
    out = {}
    for m in months:
        ms = h.add_months(m, -lag)
        if spec.get('lookback') == 'ensemble':
            w = {}
            ok = True
            for L in (3, 6, 12):
                a = _pick_one(inp, ms, dict(spec, lookback=L))
                if a is None:
                    ok = False
                    break
                w[a] = w.get(a, 0.0) + 1 / 3
            if not ok:
                continue
            out[m] = w
        else:
            a = _pick_one(inp, ms, spec)
            if a is not None:
                out[m] = {a: 1.0}
    return out


def _returns(inp, W):
    """持ち高 W から 月次リターンと片道の回転（前月の持ち高を月中の値動きで流した後との差の半分）"""
    ret, tv = {}, {}
    prev = None
    for m in sorted(W):
        w = W[m]
        if any(m not in inp[a] for a in w):
            break                                     # 持つ資産のリターンが無い月で止める（ゼロで埋めない）
        ret[m] = sum(wt * inp[a][m] for a, wt in w.items())
        if prev is None:
            tv[m] = 0.0                               # 最初の月の買い付けは相手（買って持つ）と同じ扱いで数えない
        else:
            pm, pw = prev
            g = sum(wt * (1 + inp[a][pm]) for a, wt in pw.items())
            drift = {a: wt * (1 + inp[a][pm]) / g for a, wt in pw.items()}
            keys = set(drift) | set(w)
            tv[m] = 0.5 * sum(abs(w.get(a, 0.0) - drift.get(a, 0.0)) for a in keys)
        prev = (m, w)
    return ret, tv


def run(spec):
    inp = inputs(spec.get('nonus', 'splice'), spec.get('bond_src', 'fred'))
    us, rf = inp['US'], inp['RF']
    months = [m for m in sorted(us) if m >= START and m in rf]
    W = _weights(inp, spec, months)
    ret, tv = _returns(inp, W)
    return {'ret': ret,
            'bench': {m: us[m] for m in ret},
            'rf': {m: rf[m] for m in ret},
            'turnover': tv, 'cost': COST, 'markets': {},
            'weights': W}


# ───────────────────────── 先読みの検査 ─────────────────────────
def _lookahead_test(spec, n_cuts=40, seed=7):
    """月 c 以降の全資産のリターンを乱数に置き換えても、月 c までの持ち高が1つも変わらないこと。
    陽性の対照: 月 c−1 を置き換えると、どこかの c で月 c の持ち高が変わること（検査に感度があること）"""
    rng = random.Random(seed)
    inp = inputs(spec.get('nonus', 'splice'), spec.get('bond_src', 'fred'))
    months = [m for m in sorted(inp['US']) if m >= START and m in inp['RF']]
    W0 = _weights(inp, spec, months)
    cuts = sorted(rng.sample([m for m in months if START + 200 <= m <= months[-1]], n_cuts))
    bad, sens = 0, 0
    for c in cuts:
        pert = {k: {m: (rng.gauss(0, 0.08) if m >= c else v) for m, v in s.items()} for k, s in inp.items()}
        W1 = _weights(pert, spec, months)
        for m in months:
            if m > c:
                break
            if W0.get(m) != W1.get(m):
                bad += 1
        pc = h.add_months(c, -1 - spec.get('skip', 0))       # 規則が見る最新の月（skip なら m−2）
        pert2 = {k: {m: (rng.gauss(0, 0.3) if m >= pc else v) for m, v in s.items()} for k, s in inp.items()}
        W2 = _weights(pert2, spec, months)
        if W2.get(c) != W0.get(c):
            sens += 1
    # 1か月ずらしの検査: 全資産のリターンを1か月後ろへずらすと、持ち高もちょうど1か月後ろへずれる
    sh = {k: {h.add_months(m, 1): v for m, v in s.items()} for k, s in inp.items()}
    Ws = _weights(sh, spec, [h.add_months(m, 1) for m in months])
    shift_bad = sum(1 for m in months if m in W0 and Ws.get(h.add_months(m, 1)) != W0[m])
    return {'cuts': n_cuts, 'past_changed': bad, 'sensitive_cuts': sens, 'shift_mismatch': shift_bad}


if __name__ == '__main__':
    import json
    sp = {'lookback': 12, 'safe': 'bond', 'mode': 'gem', 'nonus': 'splice'}
    r = run(sp)
    print(json.dumps(h.stats(r['ret'], r['bench'], r['rf'], turnover=r['turnover'], cost=r['cost']), ensure_ascii=False))
    print(_lookahead_test(sp))
