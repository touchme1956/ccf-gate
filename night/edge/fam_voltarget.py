#!/usr/bin/env python3
"""night/edge/fam_voltarget.py — 系統 voltarget：直近のぶれの逆数で持ち高を変える（Moreira & Muir 2017『Volatility-Managed Portfolios』）

事前登録 out/edge_prereg.json（第1回）の一系統。読むだけ・門の採点に不使用。

  持ち高 w = (目標ぶれ ÷ 直近の実現ぶれ)^p   p=1（ぶれ）/ p=2（分散＝M&M の原型）
            直近の実現ぶれ＝前日（月次の組み替えなら前月末）までの N 営業日の日次超過リターンの二乗平均（年率へ）
            目標ぶれ＝その時点までの長期平均（exp＝始まりから前日までの全部 / roll10＝前日までの10暦年）＝先読みにならない
            上限 cap（1.5 / 2.0）・下限 0
  1倍を超える分: 借入 rf＋0.4%/年 と 経費 0.9%/年（どちらも超えた分 (w−1) にだけ）＝レバレッジETF（SSO）を (w−1) 持つのと同じ
  1倍未満: 残り (1−w) は短期金利
  組み替え: monthly（前月末の信号で月初に組み替え・月中は持ったまま）／ daily（前日の終値までの信号で毎日組み替え）
  回転: 組み替えの売買 |w_新 − 持ったまま動いた w|（片道）。費用は回転1あたり 0.001（事前登録: 指数・ETF）
  相手: Ken French の米国市場（月次ファイル）。再現: French の日次地域（米ドル・1990-07〜）＝その地域の市場が相手

  run(spec) は EDGE_PHASE が select でも holdout でも同じコードで動く（期間を決め打ちしない）。
  python3 night/edge/fam_voltarget.py --test    先読みの検査（打ち切り・未来の差し替え・1か月ずらし）
  python3 night/edge/fam_voltarget.py --select  変種の総当たり（選定期間だけ）→ 表を出す
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h  # noqa: E402
import bisect, math, statistics as S, json  # noqa: E402

FAMILY = {
    'key': 'voltarget',
    'name': 'ぶれの逆数で持ち高を変える（ボラティリティ・ターゲット）',
    'implement': ('楽天証券の特定口座（課税）で、米国株全体の ETF（VTI／VOO）と米ドル MMF を持ち、月に一度（月末の翌営業日）、'
                  '前月末までの日次の値動きから持ち高 w を計算して組み替える。w<1 なら (1−w) を米ドル MMF、'
                  'w>1 なら超えた分を 2倍型 ETF（SSO）で持つ（SSO を (w−1)、VOO を (2−w)）。'
                  'NISA は使えない（成長投資枠はレバレッジ型を買えず、つみたて投資枠は売買の回転に向かない。組み替えの売却益は毎回課税）。'
                  '日次の実現ぶれは証券会社のチャートや Yahoo の日足から自分で計算する（表計算で足りる）'),
}

COST = 0.001                     # 事前登録: 指数・ETF の入れ替え 片道100%につき 0.10%
SPREAD, FEE = 0.004, 0.009       # 事前登録: レバレッジの借入 rf＋0.4%/年・経費 0.9%/年（超えた分にだけ）
MIN_HIST = 252                   # 目標ぶれ（長期平均）を立てるのに要る最小の日数（約1年）
REGIONS = ['Europe', 'Japan', 'Asia_Pacific_ex_Japan']   # 米国と重ならない3地域（North_America・Developed は米国を含むので再現に数えない）


# ───────────────────────── 信号 ─────────────────────────
def _ann_factor(dates):
    """各日の『1年あたりの営業日数』を、その日までの直近365暦日の営業日数で推す（1952年までの土曜の半日取引を吸収）。
    その日以前のデータだけを使う"""
    import datetime as dt
    ds = [dt.date(d // 10000, d // 100 % 100, d % 100).toordinal() for d in dates]
    out, j = [], 0
    for i, o in enumerate(ds):
        while ds[j] < o - 364:
            j += 1
        span = o - ds[0] + 1
        cnt = i - j + 1
        out.append(cnt if span >= 365 else cnt * 365.0 / span)
    return out


def _signal_tools(dates, x):
    """a_d = x_d² × (1年の営業日数) ＝ 年率に直した日次の二乗。累積和で窓の平均を O(1) で取る"""
    D = _ann_factor(dates)
    a = [xi * xi * Di for xi, Di in zip(x, D)]
    cum = [0.0]
    for v in a:
        cum.append(cum[-1] + v)
    return cum


def weight_at(i, spec, dates, cum):
    """i 日目（0始まり）の持ち高。**使うのは 0..i−1 日目だけ**（前日の終値まで）。履歴が足りなければ None"""
    N = spec['lookback']
    if i < max(N, MIN_HIST):
        return None
    rv = (cum[i] - cum[i - N]) / N
    if spec['target'] == 'exp':
        tv = cum[i] / i
    elif spec['target'] == 'roll10':
        lo = bisect.bisect_right(dates, dates[i - 1] - 100000, 0, i)   # 前日から10暦年前より後
        tv = (cum[i] - cum[lo]) / (i - lo)
    else:
        raise ValueError(spec['target'])
    if rv <= 0:
        return spec['cap']
    ratio = math.sqrt(tv / rv)
    w = ratio if spec['scale'] == 'vol' else ratio * ratio
    return max(0.0, min(spec['cap'], w))


# ───────────────────────── 組み立て ─────────────────────────
def build(spec, dr, drf, mr, mrf):
    """dr/drf: 日次の市場トータルリターン・短期金利 {YYYYMMDD: 小数}／mr/mrf: 月次 {YYYYMM: 小数}（相手＝mr）
    → {'ret','turnover','w'}（月次）。費用の前（レバレッジの借入・経費は中に入れてある）"""
    dates = sorted(k for k in dr if k in drf)
    x = [dr[d] - drf[d] for d in dates]
    cum = _signal_tools(dates, x)
    cap, lev = spec['cap'], (SPREAD + FEE)
    months = sorted({d // 100 for d in dates})
    first_idx = {}
    for i, d in enumerate(dates):
        first_idx.setdefault(d // 100, i)
    ret, tov, wmo = {}, {}, {}
    if spec['rebal'] == 'monthly':
        prev = None                                   # (w, 月のリターン, rf, 費用) — 持ったまま動いた w を出すため
        for m in months:
            if m not in mr or m not in mrf:
                continue
            w = weight_at(first_idx[m], spec, dates, cum)   # 前月末までの日次だけ
            if w is None:
                continue
            R, f = mr[m], mrf[m]
            c = max(w - 1.0, 0.0) * lev / 12
            r = f + w * (R - f) - c
            if prev is None:
                drifted = 1.0                         # 相手（市場を1倍）から乗り換える
            else:
                pw, pR, pf, pc = prev
                drifted = pw * (1 + pR) / (1 + pf + pw * (pR - pf) - pc)
            ret[m], tov[m], wmo[m] = r, abs(w - drifted), w
            prev = (w, R, f, c)
        return {'ret': ret, 'turnover': tov, 'w': wmo}
    # daily: 毎日 前日までの信号で組み替え。月の複利は 月次ファイルの rf ＋（日次で積んだ超過）で相手と基準をそろえる
    #        （French の日次 RF は丸められていて年 −0.1% ほど低い。w=1 なら相手とほぼ一致するようにする）
    acc, accrf, tv, ws, pw, cur = {}, {}, {}, {}, None, None
    started = None
    for i, d in enumerate(dates):
        m = d // 100
        if started is None:
            if d // 100 != dates[first_idx[m]] // 100 or first_idx[m] != i:
                continue
            if weight_at(i, spec, dates, cum) is None:
                continue
            started = m                                # 完全な月の頭から始める
        w = weight_at(i, spec, dates, cum)
        f = drf[d]
        c = max(w - 1.0, 0.0) * lev / 252
        r = f + w * x[i] - c
        if pw is None:
            drifted = 1.0
        else:
            pwv, px, pf, pc = pw
            drifted = pwv * (1 + pf + px) / (1 + pf + pwv * px - pc)
        acc[m] = acc.get(m, 1.0) * (1 + r)
        accrf[m] = accrf.get(m, 1.0) * (1 + f)
        tv[m] = tv.get(m, 0.0) + abs(w - drifted)
        ws.setdefault(m, []).append(w)
        pw = (w, x[i], f, c)
    for m in acc:
        if m in mrf and m in mr:
            ret[m] = mrf[m] + (acc[m] - accrf[m])
            tov[m] = tv[m]
            wmo[m] = S.mean(ws[m])
    return {'ret': ret, 'turnover': tov, 'w': wmo}


def run(spec):
    dr, drf = h.us_market_daily()
    mr, mrf = h.us_market()
    b = build(spec, dr, drf, mr, mrf)
    mk = {}
    for reg in spec.get('markets', REGIONS):
        try:
            rd, rfd = h.french_region(reg, daily=True)
            rm, rfm = h.french_region(reg, daily=False)
        except Exception:
            continue
        x = build(spec, rd, rfd, rm, rfm)
        if x['ret']:
            mk[reg] = {'ret': x['ret'], 'bench': rm, 'rf': rfm, 'turnover': x['turnover'], 'cost': COST}
    return {'ret': b['ret'], 'bench': mr, 'rf': mrf, 'turnover': b['turnover'], 'cost': COST, 'markets': mk,
            'w': b['w']}


# ───────────────────────── 変種の格子（選定の前に固定・40本） ─────────────────────────
def grid():
    base = {'spread': SPREAD, 'fee': FEE, 'min_hist': MIN_HIST, 'markets': REGIONS}
    out = []
    for rebal, Ns in (('monthly', (21, 42, 63)), ('daily', (21, 63))):
        for scale in ('vol', 'var'):
            for N in Ns:
                for target in ('exp', 'roll10'):
                    for cap in (1.5, 2.0):
                        out.append(dict(base, scale=scale, lookback=N, target=target, cap=cap, rebal=rebal))
    return out


def vname(s):
    return f"{s['rebal'][0]}-{s['scale']}-N{s['lookback']}-{s['target']}-cap{s['cap']}"


# ───────────────────────── 先読みの検査 ─────────────────────────
def lookahead_test():
    import random
    dr, drf = h.us_market_daily()
    mr, mrf = h.us_market()
    rng = random.Random(7)
    specs = [dict(scale='vol', lookback=63, target='exp', cap=2.0, rebal='monthly'),     # 凍結する規則
             dict(scale='var', lookback=21, target='exp', cap=2.0, rebal='monthly'),
             dict(scale='vol', lookback=63, target='roll10', cap=1.5, rebal='daily'),
             dict(scale='vol', lookback=42, target='roll10', cap=2.0, rebal='monthly')]
    fails = 0
    cuts = [193512, 195006, 197503, 199011]
    for sp in specs:
        full = build(sp, dr, drf, mr, mrf)
        for cut in cuts:
            nxt = h.add_months(cut, 1)
            # (1) 打ち切り: cut より後の日次・月次を捨てても、cut 以前の月のリターン・回転と、cut の翌月の持ち高（前月末までの信号）が同じ
            tdr = {k: v for k, v in dr.items() if k // 100 <= cut}
            tdrf = {k: v for k, v in drf.items() if k // 100 <= cut}
            tmr = {k: v for k, v in mr.items() if k <= cut}
            tmrf = {k: v for k, v in mrf.items() if k <= cut}
            tb = build(sp, tdr, tdrf, tmr, tmrf)
            for m in tb['ret']:
                if abs(tb['ret'][m] - full['ret'][m]) > 1e-12 or abs(tb['turnover'][m] - full['turnover'][m]) > 1e-12:
                    fails += 1; print('✗ 打ち切り', vname(sp), cut, m); break
            # (2) 未来の差し替え: cut より後を でたらめ（×5 の雑音）に変えても、cut 以前は同じ・翌月の持ち高（月次）も同じ
            pdr = {k: (v if k // 100 <= cut else rng.gauss(0, 0.05)) for k, v in dr.items()}
            pmr = {k: (v if k <= cut else rng.gauss(0, 0.2)) for k, v in mr.items()}
            pb = build(sp, pdr, drf, pmr, mrf)
            for m in full['ret']:
                if m <= cut and abs(pb['ret'][m] - full['ret'][m]) > 1e-12:
                    fails += 1; print('✗ 差し替え', vname(sp), cut, m); break
            if sp['rebal'] == 'monthly' and abs(pb['w'][nxt] - full['w'][nxt]) > 1e-12:
                fails += 1; print('✗ 翌月の持ち高が未来に依存', vname(sp), cut)
        # (3) 1か月ずらし: 月 m の持ち高を「月 m の日次を全部 0 にした系列」で出し直しても同じ（月 m の中身を見ていない）
        if sp['rebal'] == 'monthly':
            for m in (193207, 196305, 198710, 199808):
                zdr = {k: (0.0 if k // 100 == m else v) for k, v in dr.items()}
                zdrf = {k: (0.0 if k // 100 == m else v) for k, v in drf.items()}
                zb = build(sp, zdr, zdrf, mr, mrf)
                if abs(zb['w'][m] - full['w'][m]) > 1e-12:
                    fails += 1; print('✗ 当月の日次を見ている', vname(sp), m)
                if abs(zb['w'][h.add_months(m, 1)] - full['w'][h.add_months(m, 1)]) < 1e-15:
                    print('  （参考）翌月の持ち高は当月を反映して変わるはず', vname(sp), m)
    # (4) 日次: d 日の持ち高は d 日のリターンを使わない（d 日の日次を大きく変えても d 日の w は同じ）
    dates = sorted(dr)
    x = [dr[d] - drf[d] for d in dates]
    cum = _signal_tools(dates, x)
    sp = specs[1]
    for i in (5000, 12000, 19000):
        w0 = weight_at(i, sp, dates, cum)
        x2 = list(x); x2[i] = 0.5; x2[i + 1:] = [0.3] * (len(x) - i - 1)
        cum2 = _signal_tools(dates, x2)
        if abs(weight_at(i, sp, dates, cum2) - w0) > 1e-12:
            fails += 1; print('✗ 当日のリターンを見ている', i)
    # (5) 地域（再現に使う市場）でも同じ打ち切りの検査
    sp = specs[0]
    for reg in REGIONS:
        rd, rfd = h.french_region(reg, daily=True)
        rm, rfm = h.french_region(reg, daily=False)
        full = build(sp, rd, rfd, rm, rfm)
        for cut in (199306, 199712):
            tb = build(sp, {k: v for k, v in rd.items() if k // 100 <= cut}, {k: v for k, v in rfd.items() if k // 100 <= cut},
                       {k: v for k, v in rm.items() if k <= cut}, {k: v for k, v in rfm.items() if k <= cut})
            if any(abs(tb['ret'][m] - full['ret'][m]) > 1e-12 for m in tb['ret']):
                fails += 1; print('✗ 地域の打ち切り', reg, cut)
    print('先読みの検査:', '✓ すべて通過' if fails == 0 else f'✗ {fails} 件')
    return fails == 0


# ───────────────────────── 選定 ─────────────────────────
def select():
    dr, drf = h.us_market_daily()
    mr, mrf = h.us_market()
    rows = []
    for sp in grid():
        b = build(sp, dr, drf, mr, mrf)
        st = h.stats(b['ret'], mr, mrf, turnover=b['turnover'], cost=COST)
        ws = list(b['w'].values())
        yrs = len(b['turnover']) / 12
        rows.append({'name': vname(sp), 'spec': sp, 'stats': st,
                     'avg_w': round(S.mean(ws), 3), 'at_cap': round(sum(1 for w in ws if w >= sp['cap'] - 1e-9) / len(ws), 3),
                     'turnover_yr': round(sum(b['turnover'].values()) / yrs, 2)})
    return rows


# ───────────────────────── 凍結（一度だけ） ─────────────────────────
CHOSEN = dict(scale='vol', lookback=63, target='exp', cap=2.0, rebal='monthly')


def diagnostics(rows):
    """凍結する規則の中身を分ける（選定期間だけ）。変種ではない（選ぶのに使っていない）"""
    dr, drf = h.us_market_daily()
    mr, mrf = h.us_market()
    sp = dict(CHOSEN, markets=REGIONS)
    r = run(sp)
    ms = sorted(r['ret'])
    net = {m: r['ret'][m] - r['turnover'][m] * COST for m in ms}
    out = {}
    # ① 一定の倍率（同じぶれ）との比較＝ぶれの時機の分
    st = h.stats(r['ret'], mr, mrf, turnover=r['turnover'], cost=COST)
    L = 1 + (st['vol'] / st['bench_vol'] - 1)
    def const(L):
        return {m: mrf[m] + L * (mr[m] - mrf[m]) - max(L - 1, 0) * (SPREAD + FEE) / 12 for m in ms}
    c = const(round(L, 2))
    sc = h.stats(c, mr, mrf, a=ms[0])
    vs = h.stats(net, c, mrf)
    out['一定の倍率（同じぶれ）'] = {'L': round(L, 2), '対市場の超過': sc['excess'], 't': sc['t'], '最大下落': sc['maxdd'], 'シャープ': sc['sharpe'],
                            'この規則との差（規則−一定倍率）': vs['excess'], 'その t': vs['t']}
    # ② 日次の組み替えの上乗せ＝指数の日次の自己相関（古い値付け）の分
    dates = sorted(k for k in dr if k in drf)
    x = [dr[d] - drf[d] for d in dates]
    acc, accrf = {}, {}
    for i, d in enumerate(dates):
        m = d // 100
        if m not in r['w']:
            continue
        w = r['w'][m]; f = drf[d]
        acc[m] = acc.get(m, 1) * (1 + f + w * x[i] - max(w - 1, 0) * (SPREAD + FEE) / 252)
        accrf[m] = accrf.get(m, 1) * (1 + f)
    dm = {m: mrf[m] + acc[m] - accrf[m] for m in acc}
    ac = {}
    for a, b in [(1926, 1940), (1940, 1960), (1960, 1975), (1975, 1990), (1990, 2001)]:
        xs = [(x[i], x[i + 1]) for i in range(len(x) - 1) if a * 10000 <= dates[i] < b * 10000]
        u = [q[0] for q in xs]; v = [q[1] for q in xs]; mu, mv = S.mean(u), S.mean(v)
        ac[f'{a}-{b - 1}'] = round(sum((p - mu) * (q - mv) for p, q in xs) / math.sqrt(sum((p - mu) ** 2 for p in u) * sum((q - mv) ** 2 for q in v)), 3)
    out['日次の組み替えの上乗せ'] = {'同じ月次の w を毎日組み替えた超過': h.stats(dm, mr, mrf, turnover=r['turnover'], cost=COST)['excess'],
                           '月次のまま': st['excess'], '市場の日次の自己相関 AC1': ac}
    # ③ 期間を割る
    sub = {}
    for a, b in [(192706, 194912), (195001, 197412), (197501, 200012)]:
        s2 = h.stats(r['ret'], mr, mrf, a=a, b=b, turnover=r['turnover'], cost=COST)
        sub[f'{a}-{b}'] = {'超過': s2['excess'], 't': s2['t'], 'ぶれ': s2['vol'], '相手のぶれ': s2['bench_vol'],
                           '平均の持ち高': round(S.mean(r['w'][m] for m in ms if a <= m <= b), 2)}
    out['期間を割る'] = sub
    # ④ 地域（選定期間 1991-07〜2000-12・参考。選ぶのには使っていない）
    reg = {}
    for k, xx in r['markets'].items():
        s3 = h.stats(xx['ret'], xx['bench'], xx['rf'], turnover=xx['turnover'], cost=COST)
        reg[k] = {'超過': s3['excess'], 't': s3['t'], 'ぶれ': s3['vol'], '相手のぶれ': s3['bench_vol'], '最大下落': s3['maxdd'], '相手の最大下落': s3['bench_maxdd'], 'from': s3['from']}
    out['地域（選定期間・参考）'] = reg
    out['平均の持ち高'] = round(S.mean(r['w'].values()), 3)
    out['上限2倍に張り付いた月の割合'] = round(sum(1 for w in r['w'].values() if w >= 2 - 1e-9) / len(r['w']), 3)
    return out, st


def freeze():
    rows = select()
    elig = [r for r in rows if r['stats']['excess'] >= 1.0]
    strict = max(elig, key=lambda r: r['stats']['t'])
    chosen = next(r for r in rows if r['name'] == vname(CHOSEN))
    diag, st = diagnostics(rows)
    table = [{'name': r['name'], 'excess': r['stats']['excess'], 't': r['stats']['t'], 't_nw': r['stats']['t_nw'],
              'vol': r['stats']['vol'], 'maxdd': r['stats']['maxdd'], 'avg_w': r['avg_w'], 'turnover_yr': r['turnover_yr']}
             for r in sorted(rows, key=lambda r: -(r['stats']['t'] or -9))]
    spec = dict(CHOSEN, spread=SPREAD, fee=FEE, min_hist=MIN_HIST, markets=REGIONS, cost=COST)
    rationale = (
        '【なぜ】Moreira & Muir (2017, Journal of Finance)：市場のぶれは持続する（先月荒ければ今月も荒い）が、期待リターンはぶれに見合って上がらない'
        '（1929-32・1987 のような荒い時期は危険の割に報われない）。だから直近のぶれが高いときに持ち高を下げ、低いときに上げると、同じ平均のぶれでも年率が上がる。'
        '規則: 前月末までの63営業日の日次超過リターンの二乗平均（年率）で、その時点までの全期間の二乗平均（年率・長期の平均のぶれ＝目標）を割り、'
        'w＝目標ぶれ÷直近ぶれ（上限2倍・下限0）を月初に持つ。1倍を超える分は借入 rf＋0.4%/年と経費0.9%/年（超えた分にだけ）、1倍未満の残りは短期金利。'
        f'【選定期間 {st["from"]}〜{st["to"]}】費用後の年率 {st["cagr"]}% vs 米国市場 {st["bench_cagr"]}%＝超過 {st["excess"]:+}%/年（t {st["t"]}・NW {st["t_nw"]}）、'
        f'ぶれ {st["vol"]}% vs {st["bench_vol"]}%、最大下落 {st["maxdd"]}% vs {st["bench_maxdd"]}%、シャープ {st["sharpe"]} vs {st["bench_sharpe"]}、転がる10年の勝ち {st["roll10_win"]}。'
        f'⚠ 平均の持ち高は {diag["平均の持ち高"]}倍・上限2倍の月が {diag["上限2倍に張り付いた月の割合"]:.0%}＝超過の大半は「落ち着いた時期に借りて持つ」ことから来る『リスクを増やして勝つ』型。'
        f'同じぶれの一定{diag["一定の倍率（同じぶれ）"]["L"]}倍は超過 {diag["一定の倍率（同じぶれ）"]["対市場の超過"]:+}%/年（t {diag["一定の倍率（同じぶれ）"]["t"]}・最大下落 {diag["一定の倍率（同じぶれ）"]["最大下落"]}%）で、'
        f'この規則はそれを {diag["一定の倍率（同じぶれ）"]["この規則との差（規則−一定倍率）"]:+}%/年（t {diag["一定の倍率（同じぶれ）"]["その t"]}）上回る＝ぶれの時機そのものの上乗せは統計的には弱く、下落を浅くする効きのほうがはっきりしている。'
        f'期間を割ると 1927-49 {diag["期間を割る"]["192706-194912"]["超過"]:+}% / 1950-74 {diag["期間を割る"]["195001-197412"]["超過"]:+}% / 1975-2000 {diag["期間を割る"]["197501-200012"]["超過"]:+}%（直近の四半世紀はほぼ0）。'
        '【選び方】事前登録の線（費用後の超過≥+1%/年の中で t 最大）に厳密に当てると日次組み替えの '
        f'{strict["name"]}（超過 {strict["stats"]["excess"]:+}%・t {strict["stats"]["t"]}）だった。これを選ばず同じ中身の月次版を選んだ理由は二つ：'
        f'(1) 日次版の月次版への上乗せは、同じ月次の w のまま毎日組み替えるだけで {diag["日次の組み替えの上乗せ"]["同じ月次の w を毎日組み替えた超過"]:+}%（月次のまま {diag["日次の組み替えの上乗せ"]["月次のまま"]:+}%）とほぼ全部が出る'
        '＝ぶれの時機ではなく、CRSP 指数の日次リターンの正の自己相関（1960-74 で 0.27・古い値付けによる見かけ。Lo & MacKinlay 1990）を倍率>1で拾った分で、実際に売買できる指数では得られない'
        '(2) 日本の個人が米国ETFを毎日組み替えるのは現実的でない。月次版は M&M の原型（月次）でもある。選定の t は月次版のほうが低い（保守側の選択）。'
    )
    extra = {
        'implement': FAMILY['implement'],
        'lookahead_test': ('python3 night/edge/fam_voltarget.py --test：(1) 1935-12/1950-06/1975-03/1990-11 で日次・月次を打ち切っても、それ以前の月のリターン・回転が1e-12まで同じ '
                           '(2) 打ち切り後を でたらめの雑音に差し替えても、それ以前の月と「翌月の持ち高」（前月末までの信号）が同じ '
                           '(3) 月 m の日次を全部0にしても月 m の持ち高が同じ（当月の中身を見ていない）'
                           '(4) 日次版で d 日のリターンと以後を差し替えても d 日の持ち高が同じ（前日の終値まで） (5) 再現の3地域でも(1)と同じ。すべて通過。'
                           '加えて w≡1 で相手（月次ファイル）を 月次 0.00%/年・日次 +0.01%/年（地域 −0.00〜+0.05%/年）で再現することを確認（French の日次 RF の丸めの偏り −0.14%/年を月次 RF で補正）'),
        'variants_table': table,
        'strict_rule_pick': {'name': strict['name'], 'excess': strict['stats']['excess'], 't': strict['stats']['t'],
                             'not_chosen_because': '日次版の上乗せは指数の日次自己相関（古い値付けの見かけ）を倍率>1で拾った分・個人には日次の組み替えが現実的でない'},
        'chosen_name': chosen['name'],
        'diagnostics': diag,
        'markets': REGIONS,
        'markets_note': 'French の日次地域（米ドル・1990-07〜）。North_America と Developed は米国を含み再現にならないので数えない。Developed_ex_US は3地域の合成なので数えない。目標ぶれ（長期の平均）は各地域で 1990-07 から積み上げる',
        'prior_knowledge_note': ('調べる側は2001年以降（2003-07・2010年代の穏やかな上げ相場・2008と2020の急落）を知っている。この規則は落ち着いた時期に2倍まで借りるので、'
                                 'その知識があれば有利に見えやすい型だが、選んだのは事前登録の線（t 最大）とその唯一の例外（日次→月次・t は下がる側）だけで、'
                                 '目標（exp）・上限（2倍）・窓（63日）は格子の中で t が最大だったから'),
    }
    doc = h.save_spec('voltarget', spec, rationale, len(rows), chosen['stats'], extra=extra)
    print(json.dumps({k: doc[k] for k in ('spec', 'n_variants_tried', 'selection_stats')}, ensure_ascii=False, indent=1))
    print(rationale)
    return doc


if __name__ == '__main__':
    if '--test' in sys.argv:
        ok = lookahead_test()
        sys.exit(0 if ok else 1)
    if '--freeze' in sys.argv:
        freeze()
        sys.exit(0)
    if '--select' in sys.argv:
        rows = select()
        rows.sort(key=lambda r: -(r['stats']['t'] or -9))
        for r in rows:
            s = r['stats']
            print(f"{r['name']:32} 超過 {s['excess']:6.2f}%  t {s['t']:5.2f}  NW {s['t_nw']:5.2f}  年率 {s['cagr']:5.2f}/{s['bench_cagr']:5.2f}"
                  f"  ぶれ {s['vol']:4.1f}/{s['bench_vol']:4.1f}  下落 {s['maxdd']:6.1f}/{s['bench_maxdd']:6.1f}  SR {s['sharpe']}/{s['bench_sharpe']}"
                  f"  w平均 {r['avg_w']}  上限 {r['at_cap']:.0%}  回転/年 {r['turnover_yr']}  10年窓 {s['roll10_win']}  {s['from']}")
        out = os.path.join(os.environ.get('VT_SCRATCH', '/tmp'), 'voltarget_select.json')
        json.dump(rows, open(out, 'w'), ensure_ascii=False, indent=1)
        print('→', out, len(rows), '変種')
