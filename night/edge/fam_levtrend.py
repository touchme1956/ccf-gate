#!/usr/bin/env python3
"""night/edge/fam_levtrend.py — 系統 levtrend：レバレッジ（毎日リセット）＋トレンドで降りる（Gayed & Bilello 2016）

事前登録 out/edge_prereg.json の round1_families.levtrend。共有部品 night/edge/harness.py だけでデータを読む。
  ・指数＝Ken French の米国市場（Mkt-RF＋RF の日次・配当込み）を複利でつないだ水準
  ・信号は「前日の終値まで」（日次）／「前月末まで」（月次）で作り、当日／当月のリターンに当てる
  ・中に居るあいだは L 倍の毎日リセット（h.lev_daily：借りた分に 短期金利＋0.4%/年・経費 0.9%/年）、
    降りたら短期金利（または spec['out']='1x' なら1倍の市場）
  ・切り替えのたびに 片道の回転 1 × 0.001

使い方（選定の段だけ）:
  python3 night/edge/fam_levtrend.py            変種の表を出す（選定期間 〜2000-12）
  python3 night/edge/fam_levtrend.py --test     先読みの検査
  python3 night/edge/fam_levtrend.py --freeze   事前に決めた選び方で一つ選び out/edge/spec_levtrend.json を書く
run(spec) は統括の evaluate.py が EDGE_PHASE=holdout で呼ぶ（期間は決め打ちしない）。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h  # noqa: E402
import math, statistics as S, random, json  # noqa: E402

FAMILY = {
    'key': 'levtrend',
    'name': 'レバレッジ＋トレンドで降りる（前日の終値が200日平均の上なら L 倍・下なら倍率を外す）',
    'implement': ('課税口座（特定口座）で、S&P500 の前日の終値が200日平均の上にある間は 米国上場の3倍ETF（SPXL・UPRO など'
                  '・経費 年0.9%前後・楽天証券の米国株口座での扱いは要確認）を持ち、割ったら全部売って1倍の S&P500 ETF'
                  '（VOO・IVV など）へ移し、上へ戻ったら3倍へ戻す（spec の out が rf の版なら 1倍の代わりに 短期米国債ETF'
                  ' BIL/SGOV か MMF）。2倍なら SSO や国内投信 iFreeレバレッジ S&P500。1.25倍・1.5倍は単一の商品が無い。'
                  '⚠ 日本からは米国の終値で同じ日に執行できない（信号は朝6時ごろに分かり、発注は当夜の米国の取引時間）＝'
                  '現実には1日遅れ（spec の delay=1 の版を run の robust に併記）。'
                  '⚠ NISA の成長投資枠はレバレッジ型を買えない（デリバティブで倍率を掛ける投資信託・ETFは対象外）＝'
                  '売るたびに利益に 20.315% の税が掛かる。判定は事前登録どおり税の前'),
}

DEFAULT = {'L': 2.0, 'signal': 'd200', 'out': 'rf', 'ma': 200, 'band': 0.0, 'delay': 0,
           'spread': 0.004, 'fee': 0.009, 'cost': 0.001, 'warmup_months': 12}
REGIONS = ['Japan', 'Europe', 'Asia_Pacific_ex_Japan', 'North_America', 'Developed_ex_US']


# ───────────────────────── 部品 ─────────────────────────
def _days_per_year(keys):
    """暦年ごとの取引日数（1952年までは土曜の立会いがあり 1年 ≈ 300日）。端の欠けた年は隣の完全な年の日数を使う"""
    by = {}
    for k in keys:
        by.setdefault(k // 10000, []).append(k)
    full = {y: len(v) for y, v in by.items() if v[0] % 10000 < 110 and v[-1] % 10000 > 1220}
    out = {}
    for y in by:
        if y in full:
            out[y] = full[y]
        else:
            near = min(full, key=lambda z: abs(z - y)) if full else None
            out[y] = full[near] if near is not None else 252
    return out


def _lev(r, rf, L, spread, fee):
    """h.lev_daily を暦年ごとの実際の取引日数で呼ぶ（年率の借入の上乗せ・経費を正しく日割りする）。−100% で打ち止め"""
    if L == 1:
        return dict(r)
    dpy = _days_per_year(sorted(r))
    out = {}
    for y, n in dpy.items():
        sub = {k: v for k, v in r.items() if k // 10000 == y}
        out.update(h.lev_daily(sub, rf, L, spread=spread, fee=fee, days=n))
    return {k: max(-1.0, v) for k, v in out.items()}


def positions(keys, r, rf, spec):
    """各取引日 i の持ち高（1=中・0=降りる・None=まだ決められない）。i の持ち高は i−1 日の終値まで（月次の信号は前月末まで）で決める。
    spec['delay']=d なら持ち高を d 取引日遅らせる（d=1 ＝ 前日の終値の信号を当日の終値で執行＝日本から注文する現実の遅れ）"""
    p = _positions0(keys, r, rf, spec)
    d = int(spec.get('delay', 0) or 0)
    return ([None] * d + p[:len(p) - d]) if d > 0 else p


def _positions0(keys, r, rf, spec):
    sig = spec['signal']
    n = len(keys)
    P = [0.0] * n                                   # i 日の終値の水準（配当込み）
    lv = 1.0
    for i, k in enumerate(keys):
        lv *= 1 + r[k]
        P[i] = lv
    pos = [None] * n
    if sig in ('d200', 'd200b'):
        ma, band = int(spec.get('ma', 200)), float(spec.get('band', 0.0))
        run = 0.0
        state = None
        for i in range(n):
            # 平均は P[i−ma .. i−1]（i 日の値は使わない）
            if i - 1 >= 0:
                run += P[i - 1]
            if i - 1 - ma >= 0:
                run -= P[i - 1 - ma]
            if i < ma:
                continue
            sma = run / ma
            x = P[i - 1]
            if sig == 'd200':
                state = 1 if x > sma else 0
            else:
                if state is None:
                    state = 1 if x > sma else 0
                elif state == 1 and x < sma * (1 - band):
                    state = 0
                elif state == 0 and x > sma * (1 + band):
                    state = 1
            pos[i] = state
        return pos
    # 月次の信号：月末の水準（最初の月の前の月末は 1.0）
    first_m = keys[0] // 100
    me = {h.add_months(first_m, -1): 1.0}
    for i, k in enumerate(keys):
        me[k // 100] = P[i]
    rfm = h.to_monthly(rf)
    mpos = {}
    for m in sorted({k // 100 for k in keys}):
        prev = h.add_months(m, -1)
        if sig == 'm10':
            w = [h.add_months(m, -j) for j in range(1, 11)]
            if all(x in me for x in w):
                mpos[m] = 1 if me[prev] > S.mean(me[x] for x in w) else 0
        elif sig == 'm12':
            base = h.add_months(m, -13)
            ms = [h.add_months(m, -j) for j in range(1, 13)]
            if base in me and all(x in rfm for x in ms):
                cash = math.prod(1 + rfm[x] for x in ms) - 1
                mpos[m] = 1 if me[prev] / me[base] - 1 > cash else 0
        else:
            raise ValueError(sig)
    for i, k in enumerate(keys):
        pos[i] = mpos.get(k // 100)
    return pos


def _rule_on(r, rf, spec):
    """日次の市場 r・短期金利 rf に規則を当てる → 月次の ret・bench・rf・turnover"""
    sp = dict(DEFAULT); sp.update(spec or {})
    keys = sorted(k for k in r if k in rf)
    r = {k: r[k] for k in keys}
    rf = {k: rf[k] for k in keys}
    pos = positions(keys, r, rf, sp)
    if int(sp.get('delay', 0) or 0) > 0:                 # 遅らせた版の開始の境目だけ、遅らせない持ち高（これも前日まででしか決まっていない）で埋める
        p0 = _positions0(keys, r, rf, sp)
        pos = [a if a is not None else b for a, b in zip(pos, p0)]
    lev = _lev(r, rf, float(sp['L']), float(sp['spread']), float(sp['fee']))
    start = h.add_months(keys[0] // 100, int(sp['warmup_months']))      # すべての信号が決まる月（変種に依らない共通の開始）
    daily, tv = {}, {}
    prev = None
    for i, k in enumerate(keys):
        p = pos[i]
        if k // 100 < start:
            prev = p
            continue
        if p is None:
            raise RuntimeError(f'持ち高が決まらない日 {k}（warmup が短い）')
        if p == 1:
            x = lev[k]
        else:
            x = r[k] if sp['out'] == '1x' else rf[k]
        daily[k] = x
        m = k // 100
        tv.setdefault(m, 0.0)
        if prev is not None and p != prev:
            tv[m] += 1.0
        prev = p
    ret = h.to_monthly(daily)
    bench = h.to_monthly({k: r[k] for k in daily})
    rfm = h.to_monthly({k: rf[k] for k in daily})
    return {'ret': ret, 'bench': bench, 'rf': rfm, 'turnover': tv, 'cost': float(sp['cost']),
            '_daily': daily, '_pos': dict(zip(keys, pos))}


def run(spec):
    """事前登録どおり: 相手＝米国市場（1倍・持ち続け・同じ日次データの複利）、費用＝切り替え1回×0.001"""
    r, rf = h.us_market_daily()
    out = _rule_on(r, rf, spec)
    res = {k: out[k] for k in ('ret', 'bench', 'rf', 'turnover', 'cost')}
    mk = {}
    for reg in REGIONS:
        try:
            rr, rrf = h.french_region(reg, daily=True)
        except Exception:
            continue
        if len(rr) < 400:
            continue
        o = _rule_on(rr, rrf, spec)
        mk[reg] = {k: o[k] for k in ('ret', 'bench', 'rf', 'turnover', 'cost')}
    res['markets'] = mk
    # 参考（判定には使わない）: 同じ規則を1取引日遅らせた版＝日本の個人が現実に執行できる形（前日の終値の信号を当日の終値で）
    if int((spec or {}).get('delay', 0) or 0) == 0:
        sp1 = dict(spec or {}); sp1['delay'] = 1
        o1 = _rule_on(r, rf, sp1)
        res['robust'] = {'delay1': {k: o1[k] for k in ('ret', 'bench', 'rf', 'turnover', 'cost')}}
    return res


# ───────────────────────── 選定の段の道具 ─────────────────────────
def variants():
    """★結果を見る前に固定した変種の一覧（40以下）。eligible=False は比較用で選ばない（1倍のトレンド＝系統 trend と重なる／
    トレンド無しのレバレッジ持ち続け＝この系統の考え〔降りる〕を含まない）"""
    V = []
    for sig, extra in (('d200', {}), ('d200b', {'band': 0.01}), ('m10', {}), ('m12', {})):
        for L in (1.25, 1.5, 2.0, 3.0):
            V.append({'name': f'{sig}{"±1%" if extra else ""} L{L} 外=金利', 'spec': dict(L=L, signal=sig, out='rf', **extra), 'eligible': True})
    for L in (1.5, 2.0, 3.0):
        V.append({'name': f'd200 L{L} 外=1倍', 'spec': dict(L=L, signal='d200', out='1x'), 'eligible': True})
    for sig, extra in (('d200', {}), ('d200b', {'band': 0.01}), ('m10', {}), ('m12', {})):
        V.append({'name': f'参考 {sig}{"±1%" if extra else ""} L1 外=金利', 'spec': dict(L=1.0, signal=sig, out='rf', **extra), 'eligible': False})
    for L in (1.25, 1.5, 2.0, 3.0):
        # 持ち続け＝いつも中（信号を常に1にする代わりに out='1x' で L=1… ではなく、別扱い）
        V.append({'name': f'参考 持ち続け L{L}', 'spec': dict(L=L, signal='hold'), 'eligible': False})
    return V


def _hold(spec):
    """参考: トレンド無しの L 倍の持ち続け"""
    sp = dict(DEFAULT); sp.update(spec)
    r, rf = h.us_market_daily()
    keys = sorted(k for k in r if k in rf)
    lev = _lev({k: r[k] for k in keys}, rf, float(sp['L']), sp['spread'], sp['fee'])
    start = h.add_months(keys[0] // 100, int(sp['warmup_months']))
    d = {k: lev[k] for k in keys if k // 100 >= start}
    return {'ret': h.to_monthly(d), 'bench': h.to_monthly({k: r[k] for k in d}),
            'rf': h.to_monthly({k: rf[k] for k in d}), 'turnover': None, 'cost': 0.0}


def eval_variant(v):
    x = _hold(v['spec']) if v['spec'].get('signal') == 'hold' else run(v['spec'])
    st = h.stats(x['ret'], x['bench'], x['rf'], turnover=x['turnover'], cost=x['cost'])
    sw = sum((x['turnover'] or {}).values()) / (len(x['ret']) / 12) if x['turnover'] else 0.0
    return x, st, round(sw, 2)


def dca_multiple(ret, ms, years=20):
    """毎月同額を years 年積み立てた倍率（最終額 ÷ 積んだ総額）。月初に1を足し、その月のリターンを掛ける"""
    n = years * 12
    out = []
    for i in range(0, len(ms) - n + 1):
        w = ms[i:i + n]
        v = 0.0
        for m in w:
            v = (v + 1.0) * (1 + ret[m])
        out.append((w[0], v / n))
    return out


def lookahead_test():
    """先読みの検査: (1) 日 d 以降のリターンを乱数で書き換えても、d 以前の持ち高は変わらない（i の持ち高は i−1 日まで）
    (2) 月 m 以降を書き換えても、m 月の持ち高（月次の信号）は変わらない（前月末まで）
    (3) 書き換えた日そのものの持ち高も変わらない（当日の値を使っていない）"""
    r, rf = h.us_market_daily()
    keys = sorted(k for k in r if k in rf)
    rnd = random.Random(7)
    res = []
    for sig, extra in (('d200', {}), ('d200b', {'band': 0.01}), ('m10', {}), ('m12', {})):
        sp = dict(DEFAULT); sp.update(dict(signal=sig, **extra))
        base = positions(keys, r, rf, sp)
        bad = 0
        for trial in range(6):
            cut = rnd.randrange(len(keys) // 3, len(keys) - 10)
            if sig in ('m10', 'm12'):                         # 月の頭から書き換える
                m0 = keys[cut] // 100
                cut = next(i for i, k in enumerate(keys) if k // 100 == m0)
            r2 = dict(r)
            for k in keys[cut:]:
                r2[k] = rnd.gauss(0, 0.03)
            p2 = positions(keys, r2, rf, sp)
            if p2[:cut + 1] != base[:cut + 1] if sig in ('d200', 'd200b') else \
               [p for k, p in zip(keys, p2) if k // 100 <= keys[cut] // 100] != [p for k, p in zip(keys, base) if k // 100 <= keys[cut] // 100]:
                bad += 1
            # 書き換え後の未来は（ふつうは）変わる＝検査が空回りしていないことの確認
        changed = any(a != b for a, b in zip(base, positions(keys, {k: (-v if i > len(keys) // 2 else v) for i, (k, v) in enumerate(sorted(r.items()))}, rf, sp)))
        res.append((sig, bad, changed))
    # (4) 1日ずらした信号（当日の終値を使う＝先読み）と比べて、使っている信号が「前日まで」であることの確認
    sp = dict(DEFAULT); sp.update(signal='d200')
    pos = positions(keys, r, rf, sp)
    P, lv = [], 1.0
    for k in keys:
        lv *= 1 + r[k]; P.append(lv)
    ok = all(pos[i] == (1 if P[i - 1] > sum(P[i - 201:i - 1]) / 200 else 0) for i in range(300, len(keys), 997))
    return res, ok


def main():
    assert h.PHASE == 'select', '選定の道具は EDGE_PHASE=select でしか動かさない'
    args = sys.argv[1:]
    if '--test' in args:
        res, ok = lookahead_test()
        for sig, bad, changed in res:
            print(f'{sig:6} 未来を書き換えて過去の持ち高が変わった回数 {bad}/6  （未来の持ち高は動く: {changed}）')
        print('d200 の信号＝前日の終値と前日までの200日平均の比較:', ok)
        return
    V = variants()
    rows = []
    for v in V:
        x, st, sw = eval_variant(v)
        rows.append((v, x, st, sw))
        print(f"{'◎' if v['eligible'] else '　'} {v['name']:24} 年率 {st['cagr']:6.2f} vs {st['bench_cagr']:5.2f}  超過 {st['excess']:6.2f}  t {st['t']:5.2f} (NW {st['t_nw']:5.2f})  "
              f"ぶれ {st['vol']:5.1f}/{st['bench_vol']:4.1f}  最大下落 {st['maxdd']:6.1f}/{st['bench_maxdd']:6.1f}  シャープ {st['sharpe']}/{st['bench_sharpe']}  10年窓 {st['roll10_win']}  切替/年 {sw}")
    el = [z for z in rows if z[0]['eligible'] and z[2]['excess'] >= 1.0]
    if el:
        pick = max(el, key=lambda z: z[2]['t'])
        why = '選定期間の費用後の超過が +1%/年以上の変種のうち t が最大'
    else:
        pick = max((z for z in rows if z[0]['eligible']), key=lambda z: z[2]['t'])
        why = '⚠ +1%/年に届く変種が無く、t が最大の変種を選んだ'
    v, x, st, sw = pick
    print('\n★選んだ変種:', v['name'], why)
    if '--freeze' not in args:
        return
    # 積立（選定期間の中だけ）
    ms = sorted(set(x['ret']) & set(x['bench']))
    net = {m: x['ret'][m] - (x['turnover'] or {}).get(m, 0.0) * x['cost'] for m in ms}
    a = dca_multiple(net, ms)
    b = dict(dca_multiple(x['bench'], ms))
    wins = sum(1 for s, v1 in a if v1 > b[s])
    dca = {'about': '選定期間（〜2000-12）の転がる20年・毎月同額の積立の倍率（最終額÷積んだ総額）。規則は費用後・税の前',
           'windows': len(a), 'rule_median': round(S.median(v1 for _, v1 in a), 2), 'rule_min': round(min(v1 for _, v1 in a), 2),
           'hold_median': round(S.median(b.values()), 2), 'hold_min': round(min(b.values()), 2),
           'rule_beats_hold': f'{wins}/{len(a)}',
           'worst_start_rule': min(a, key=lambda z: z[1])[0], 'worst_start_hold': min(b.items(), key=lambda z: z[1])[0]}
    print('積立:', dca)
    res, ok = lookahead_test()
    table = [{'name': z[0]['name'], 'eligible': z[0]['eligible'], 'excess': z[2]['excess'], 't': z[2]['t'], 't_nw': z[2]['t_nw'],
              'vol': z[2]['vol'], 'maxdd': z[2]['maxdd'], 'switches_per_year': z[3]} for z in rows]
    mk_sel = {}
    for nm, y in x['markets'].items():
        s2 = h.stats(y['ret'], y['bench'], y['rf'], turnover=y['turnover'], cost=y['cost'])
        if s2:
            mk_sel[nm] = {k: s2[k] for k in ('from', 'to', 'years', 'cagr', 'bench_cagr', 'excess', 't', 'vol', 'bench_vol', 'maxdd', 'bench_maxdd')}
    spec = dict(DEFAULT); spec.update(v['spec'])
    # 頑健さ（選定には使っていない・結果を読むための参考）: 執行の遅れ・次点の変種
    rob = {}
    for d in (1, 2, 5):
        sp_d = dict(spec); sp_d['delay'] = d
        y = run(sp_d)
        s_d = h.stats(y['ret'], y['bench'], y['rf'], turnover=y['turnover'], cost=y['cost'])
        rob[f'delay{d}'] = {k: s_d[k] for k in ('cagr', 'bench_cagr', 'excess', 't', 'vol', 'maxdd', 'sharpe')}
    ranked = sorted((z for z in rows if z[0]['eligible']), key=lambda z: -z[2]['t'])
    rob['runner_up'] = {'name': ranked[1][0]['name'], 'excess': ranked[1][2]['excess'], 't': ranked[1][2]['t'], 'maxdd': ranked[1][2]['maxdd']}
    print('頑健さ:', rob)
    rationale = RATIONALE.format(name=v['name'], **st, sw=sw) + (
        f"【頑健さ（選定に不使用）】信号を1取引日遅らせる（日本からの現実の執行）と 超過 {rob['delay1']['excess']}%/年・t {rob['delay1']['t']}、"
        f"5日遅らせると {rob['delay5']['excess']}%/年・t {rob['delay5']['t']}。次点は「{rob['runner_up']['name']}」（t {rob['runner_up']['t']}・"
        f"最大下落 {rob['runner_up']['maxdd']}%）で差は誤差の中。")
    extra = {'implement': FAMILY['implement'],
             'lookahead_test': ('(1) 日次の信号（d200・d200±1%）: 日 d 以降のリターンを乱数へ書き換えても d 日までの持ち高が変わらないことを各6回確認。'
                                '(2) 月次の信号（m10・m12）: 月 m の頭から書き換えても m 月までの持ち高が変わらないことを各6回確認。'
                                '(3) d200 の持ち高が「前日の終値 > 前日までの200日の平均」と一致することを抜き取りで確認。'
                                f'結果: {[(s, f"{b}/6") for s, b, _ in res]}・抜き取り {ok}'),
             'variants_table': table, 'markets': list(x['markets']), 'markets_selection_period': mk_sel,
             'dca_20y_selection': dca, 'bench_note': ('相手＝同じ French 日次データ（Mkt-RF＋RF）を月へ複利でつないだ1倍の持ち続け。'
                                                     'French の月次ファイルより 年0.14% 低く出る（日次の RF の丸め）ので、同じデータで比べて見かけの差を作らない'),
             'robustness_selection': rob,
             'tax_note': '課税口座で売るたびに 20.315%。切り替えは年に数回で、利益の繰り延べが効かない分だけ持ち続けより不利（判定には入れない）',
             'selection_rule': why}
    doc = h.save_spec('levtrend', spec, rationale, len(V), st, extra=extra)
    print('凍結:', json.dumps(doc['spec'], ensure_ascii=False))


RATIONALE = (
    '【なぜ】Gayed & Bilello (2016)『Leverage for the Long Run』（Dow Award）：株価が200日平均より上の局面はぶれが小さく上昇が続きやすく、'
    '下の局面はぶれが大きく下げが続きやすい（ぶれの塊・時系列の勢い＝Moskowitz, Ooi & Pedersen 2012・Faber 2007）。'
    '毎日リセットのレバレッジは ぶれが大きいほど複利で目減りする（ぶれの二乗に比例）ので、ぶれの大きい局面だけを避ければ、'
    '倍率の上乗せ（株式の上乗せ×(L−1)）を残したまま目減りと大きな下落を減らせる、という経済的な理由がある。'
    '「外=1倍」の版は、下の局面で倍率だけを外し株式の上乗せ（1倍ぶん）は持ち続ける＝ぶれの大きい局面の目減りだけを避ける形。'
    '【選定期間（1927-07〜2000-12・米国）】選んだのは「{name}」: 年率 {cagr}% vs 持ち続け {bench_cagr}%、'
    '費用後の超過 {excess}%/年（t {t}・Newey-West {t_nw}）、ぶれ {vol}% vs {bench_vol}%、最大下落 {maxdd}% vs {bench_maxdd}%、'
    'シャープ {sharpe} vs {bench_sharpe}、転がる10年の勝ち {roll10_win}、切り替え 年{sw}回。'
    '【注意】t は月次の算術の超過で測るので、倍率を上げるほど株式の上乗せ×(L−1) が超過に入り t も上がりやすい＝'
    'この系統の勝ちは原則「リスクを増やして」の勝ち。検定では ぶれ・最大下落を相手と並べて読むこと。'
)

if __name__ == '__main__':
    main()
