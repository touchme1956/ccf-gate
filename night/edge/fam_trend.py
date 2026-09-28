#!/usr/bin/env python3
"""night/edge/fam_trend.py — 系統 trend: 米国市場のトレンドで 市場⇄短期金利（Faber 2007）

事前登録 out/edge_prereg.json（第1回）の一系統。読むだけ・門の採点に不使用。
  ・データは night/edge/harness.py の読み込み関数だけで読む（EDGE_PHASE=select の間は 2000-12 で切れる）
  ・月 m の持ち高は m−1 月末（日次なら m−1 月の最終営業日の終値）までのデータだけで決める
  ・降りた先は短期金利（French の RF＝米国 T-bill 1か月）。相手は French の米国市場（配当込み・時価加重）
  ・費用: 持ち高の変化 |w_m − w_{m−1}| を片道の回転とし、回転1あたり 0.10%

spec の形（すべて月末に判定・翌月に適用）:
  {'kind':'sma',   'n':10, 'band':0.0}        配当込み指数の水準 vs 過去 n か月（当月末を含む）の月末水準の平均
  {'kind':'mom',   'n':12, 'vs':'rf'|'zero'}  過去 n か月の配当込みリターン > 同じ期間の短期金利（または 0）
  {'kind':'xover', 'fast':3, 'slow':12}        月末水準の fast か月平均 > slow か月平均
  {'kind':'dsma',  'n':200, 'band':0.0}       日次の配当込み指数（月の最終営業日の終値）vs 過去 n 営業日の平均
  {'kind':'combo', 'mode':'both'|'either'|'avg', 'parts':[spec, ...]}
      both＝全部が上向きなら持つ／either＝どれか一つでも／avg＝上向きの割合だけ持つ（0〜1 の端数の持ち高）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h  # noqa: E402

FAMILY = {
    'key': 'trend',
    'name': '米国株のトレンドで 市場⇄短期金利（Faber 型のタイミング）',
    'implement': ('月末に一度だけ判定し、翌月の頭に入れ替える。上向きなら米国株全体の ETF（VTI・または S&P500 の VOO/IVV）を全額、'
                  '下向きなら全額を短期の米国債 ETF（BIL・SGOV・SHV など）かドルの MMF へ移す。楽天証券の米国株口座（特定口座）で実行できる。'
                  'NISA 成長投資枠でも VTI/VOO と SGOV/BIL は買えるが、NISA は売った枠が翌年まで戻らない（年の枠を超える入れ替えは不可）ので、'
                  '年に数回入れ替えるこの規則は実質的に課税口座向け。課税口座では降りるたびに含み益に約20%の税がかかる（主の判定には入れていない）。'
                  '円の投資信託（eMAXIS Slim 米国株式 等）とドル MMF でも形は作れるが、投信は約定が翌営業日以降で、月末判定→翌月適用の近似になる'),
}

COST = 0.001            # 事前登録: 指数・ETF の入れ替えは片道の回転100%につき 0.10%
US_START = 192707       # 米国の比較の始まり（どの変種も同じ月から比べる＝最長の準備期間12か月の後）
WARM = 12               # 他の市場: 最初のデータ月から12か月は準備（変種によらず同じ）


# ───────────────────────── 信号（月末に判定） ─────────────────────────
def _levels(ret):
    """月次 → 月末の配当込み指数の水準 {YYYYMM: 水準}（最初の月の前の月末を 1 とする）"""
    lv, v = {}, 1.0
    for m in sorted(ret):
        v *= 1 + ret[m]
        lv[m] = v
    return lv


def _sig_monthly(spec, ret, rf):
    """月末 k に判定した上向きの度合い {k: 0〜1}（k 月末までのデータだけを使う）"""
    ks = sorted(ret)
    lv = _levels(ret)
    kind = spec['kind']
    out = {}
    if kind == 'sma':
        n, band = spec['n'], spec.get('band', 0.0)
        state = None
        for i in range(n - 1, len(ks)):
            k = ks[i]
            avg = sum(lv[ks[j]] for j in range(i - n + 1, i + 1)) / n
            x = lv[k]
            if band <= 0:
                state = 1.0 if x > avg else 0.0
            else:                                   # 帯つき: 帯の外へ出たときだけ切り替える（初回は帯なしで決める）
                if state is None:
                    state = 1.0 if x > avg else 0.0
                elif x > avg * (1 + band):
                    state = 1.0
                elif x < avg * (1 - band):
                    state = 0.0
            out[k] = state
    elif kind == 'mom':
        n, vs = spec['n'], spec.get('vs', 'rf')
        for i in range(n - 1, len(ks)):
            w = ks[i - n + 1:i + 1]
            g = 1.0
            for m in w:
                g *= 1 + ret[m]
            if vs == 'rf':
                if any(m not in rf for m in w):
                    continue
                gr = 1.0
                for m in w:
                    gr *= 1 + rf[m]
            else:
                gr = 1.0
            out[ks[i]] = 1.0 if g > gr else 0.0
    elif kind == 'xover':
        f, s = spec['fast'], spec['slow']
        for i in range(s - 1, len(ks)):
            af = sum(lv[ks[j]] for j in range(i - f + 1, i + 1)) / f
            asl = sum(lv[ks[j]] for j in range(i - s + 1, i + 1)) / s
            out[ks[i]] = 1.0 if af > asl else 0.0
    else:
        raise ValueError(kind)
    return out


def _sig_daily(spec, daily):
    """日次 → 月の最終営業日に判定 {YYYYMM: 0/1}（その日の終値までを使う）"""
    n, band = spec['n'], spec.get('band', 0.0)
    ds = sorted(daily)
    v, lv = 1.0, []
    for d in ds:
        v *= 1 + daily[d]
        lv.append(v)
    # 転がる和
    out, state, run = {}, None, 0.0
    for i, d in enumerate(ds):
        run += lv[i]
        if i >= n:
            run -= lv[i - n]
        last_of_month = (i == len(ds) - 1) or (ds[i + 1] // 100 != d // 100)
        if not last_of_month or i < n - 1:
            continue
        # ⚠ データの最後の日が月の途中なら、その月は判定しない（月末の終値ではないので）
        if i == len(ds) - 1 and not _month_complete(d):
            continue
        avg = run / n
        x = lv[i]
        if band <= 0 or state is None:
            state = 1.0 if x > avg else 0.0
        elif x > avg * (1 + band):
            state = 1.0
        elif x < avg * (1 - band):
            state = 0.0
        out[d // 100] = state
    return out


def _month_complete(d):
    """日次データの最後の日が、その月の最終営業日とみなせるか（25日以降なら月末とみなす）"""
    return d % 100 >= 25


def signals(spec, ret, rf, daily=None):
    """月末 k の上向きの度合い {k: 0〜1}"""
    kind = spec['kind']
    if kind in ('sma', 'mom', 'xover'):
        return _sig_monthly(spec, ret, rf)
    if kind == 'dsma':
        if daily is None:
            raise ValueError('dsma には日次が要る')
        return _sig_daily(spec, daily)
    if kind == 'combo':
        parts = [signals(p, ret, rf, daily) for p in spec['parts']]
        ks = set(parts[0])
        for p in parts[1:]:
            ks &= set(p)
        mode = spec['mode']
        out = {}
        for k in ks:
            xs = [p[k] for p in parts]
            if mode == 'both':
                out[k] = 1.0 if all(x >= 1 for x in xs) else 0.0
            elif mode == 'either':
                out[k] = 1.0 if any(x >= 1 for x in xs) else 0.0
            else:
                out[k] = sum(xs) / len(xs)
        return out
    raise ValueError(kind)


def positions(spec, ret, rf, daily=None):
    """月 m の株の持ち高 {m: 0〜1} ＝ m−1 月末の信号（1か月ずらすのはここだけ）"""
    sig = signals(spec, ret, rf, daily)
    return {h.add_months(k, 1): w for k, w in sig.items()}


def apply(pos, ret, rf, start=None):
    """持ち高 → 規則のリターン（費用の前）と片道の回転。回転は |w_m − w_{m−1}|（最初の月は 0）"""
    ms = [m for m in sorted(pos) if m in ret and m in rf and (start is None or m >= start)]
    r, tv, prev = {}, {}, None
    for m in ms:
        w = pos[m]
        r[m] = w * ret[m] + (1 - w) * rf[m]
        tv[m] = 0.0 if prev is None else abs(w - prev)
        prev = w
    return r, tv


def _needs_daily(spec):
    if spec['kind'] == 'dsma':
        return True
    if spec['kind'] == 'combo':
        return any(_needs_daily(p) for p in spec['parts'])
    return False


# ───────────────────────── 本体 ─────────────────────────
def _markets(spec, us_rf):
    """同じ凍結した規則を他の市場へ（信号はその市場の米ドル建て配当込み指数・現金は米国の短期金利・相手はその市場）"""
    out = {}
    daily = _needs_daily(spec)
    if not daily:                                  # 21か国は月次しか無い → 日次の規則は当てられない
        for c, r in sorted(h.french_countries('Dollar').items()):
            if len(r) < WARM + 24:
                continue
            ks = sorted(r)
            start = h.add_months(ks[0], WARM)
            pos = positions(spec, r, us_rf)
            ret, tv = apply(pos, r, us_rf, start)
            out[f'country:{c}'] = {'ret': ret, 'bench': {m: r[m] for m in ret}, 'rf': us_rf, 'turnover': tv, 'cost': COST}
    for reg in ('Developed_ex_US', 'Japan', 'Europe', 'Asia_Pacific_ex_Japan'):
        mk, rf = h.french_region(reg)
        if len(mk) < WARM + 24:
            continue
        dd = None
        if daily:
            dd, _ = h.french_region(reg, daily=True)
        ks = sorted(mk)
        start = h.add_months(ks[0], WARM)
        pos = positions(spec, mk, rf, dd)
        ret, tv = apply(pos, mk, rf, start)
        out[f'region:{reg}'] = {'ret': ret, 'bench': {m: mk[m] for m in ret}, 'rf': rf, 'turnover': tv, 'cost': COST}
    return out


def run(spec):
    mkt, rf = h.us_market()
    daily = None
    if _needs_daily(spec):
        daily, _ = h.us_market_daily()
    pos = positions(spec, mkt, rf, daily)
    ret, tv = apply(pos, mkt, rf, US_START)
    return {'ret': ret, 'bench': {m: mkt[m] for m in ret}, 'rf': rf, 'turnover': tv, 'cost': COST,
            'markets': _markets(spec, rf)}


# ───────────────────────── 先読みの検査 ─────────────────────────
def lookahead_test(spec, n_cuts=40, seed=7):
    """(1) 切り詰め: データを k 月末で切って計算し直しても、k+1 月までの持ち高が全データの計算と一致するか
       (2) 撹乱: k 月（と日次の k 月の全営業日）以降のリターンを乱しても、k 月までの持ち高が変わらないか
       (3) ずらし: 持ち高 m は m−1 月末の信号そのものか（信号の月 = 持ち高の月 − 1）
    米国（月次・日次）と、日次を使わない規則なら国の系列一つでも確かめる。→ {'ok': bool, 'checked': 件数, 'fail': [...]}"""
    import random
    rnd = random.Random(seed)
    mkt, rf = h.us_market()
    daily = h.us_market_daily()[0] if _needs_daily(spec) else None
    full = positions(spec, mkt, rf, daily)
    ks = sorted(mkt)
    cuts = sorted(rnd.sample(ks[24:-1], min(n_cuts, len(ks) - 25)))
    fail, checked = [], 0
    for k in cuts:
        # (1) 切り詰め
        m2 = {m: v for m, v in mkt.items() if m <= k}
        r2 = {m: v for m, v in rf.items() if m <= k}
        d2 = {d: v for d, v in daily.items() if d // 100 <= k} if daily else None
        p2 = positions(spec, m2, r2, d2)
        for m in full:
            if m <= h.add_months(k, 1):
                checked += 1
                if p2.get(m) != full[m]:
                    fail.append(('truncate', k, m, full[m], p2.get(m)))
        # (2) 撹乱（k 月以降を別の値へ）
        m3 = {m: (v if m < k else rnd.uniform(-0.3, 0.3)) for m, v in mkt.items()}
        r3 = {m: (v if m < k else rnd.uniform(0, 0.02)) for m, v in rf.items()}
        d3 = {d: (v if d // 100 < k else rnd.uniform(-0.1, 0.1)) for d, v in daily.items()} if daily else None
        p3 = positions(spec, m3, r3, d3)
        for m in full:
            if m <= k:
                checked += 1
                if p3.get(m) != full[m]:
                    fail.append(('perturb', k, m, full[m], p3.get(m)))
    # (3) ずらし
    sig = signals(spec, mkt, rf, daily)
    for m, w in full.items():
        checked += 1
        if sig.get(h.add_months(m, -1)) != w:
            fail.append(('shift', m, w))
    # 国の系列（月次の規則だけ）
    if not _needs_daily(spec):
        c = h.french_countries('Dollar')['Japan']
        fc = positions(spec, c, rf)
        for k in sorted(rnd.sample(sorted(c)[24:-1], 15)):
            p2 = positions(spec, {m: v for m, v in c.items() if m <= k}, {m: v for m, v in rf.items() if m <= k})
            for m in fc:
                if m <= h.add_months(k, 1):
                    checked += 1
                    if p2.get(m) != fc[m]:
                        fail.append(('truncate-japan', k, m))
    return {'ok': not fail, 'checked': checked, 'fail': fail[:10]}
