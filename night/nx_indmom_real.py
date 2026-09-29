#!/usr/bin/env python3
"""night/nx_indmom_real.py — nx 角度 indmom_real（楽天証券で実際に買える米国上場の業種・セクター ETF〔1業種1本〕で
『業種の勢い』を毎月回したら SPY〔配当込み〕に勝ったか）の**測る道具**（読むだけ・門の判定には不使用）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて勝てる結果を出して…探し続けて」。
ただし線を下げて勝ちを作らない。事前登録 out/nx_indmom_real_prereg.json（測る前に固定・この道具はそれを書き換えない）と
全体の線 out/nx_prereg.json（criteria_short_sample）をそのまま当てる。統計と格付けは night/nx_common.py。

何をするか
  1) 事前登録の指紋（データ道具 night/nx_indmom_real_data.py の sha256・RULES の sha・抽出の sha）を照合し、違えば止まる。
     データ道具の selftest（9項目）も走らせる。
  2) 組み立て（規則 → 毎月の持ち物 → 月次リターン・回転・費用）を**合成データで先に点検**する
     （t より後のリターンを書き換えても t+1 までの持ち物が変わらない・回転は 0〜1・選んだ本数が K・和が 1・P3 の組は 1/6 ずつ）。
     課税口座の模擬も合成データで点検する（税 0・費用 0 なら総リターンの積と一致・利益の税と損の繰越の手計算）。
  3) 実データの形の点検（評価の始まりと各月の候補の数が事前登録の形と ±0 で一致・SPY と French Mkt の相関・
     |月次| > 40% の月を日足と突き合わせる・欠けを 0 で埋めない）。
  4) 主の5本（P1〜P5・U_all）・探索の5本（E1〜E5・U_sector）・対照3本（REF）を測り、grade_short で格付け
     （Holm は P の5本の中・E の5本の中で別々）。報告 R1〜R16 をすべて出す（格付けには使わない）。

C4 に当たる転がる20年窓・20年積立の勝ちは丸める前の差で数える（兄弟の nx_leadlag.rolling_exact と同じ。
nx_common.rolling は小数2桁の%に丸めてから数える）。丸めた数え方も併記する。

使い方: python3 night/nx_indmom_real.py            → out/nx_indmom_real.json
"""
import sys, os, io, json, math, hashlib, time, random, bisect, contextlib, collections, statistics as S

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as C  # noqa: E402
import nx_indmom_real_data as D  # noqa: E402

PRE = os.path.join(C.BASE, 'out', 'nx_indmom_real_prereg.json')
DATA_TOOL = os.path.join(C.BASE, 'night', 'nx_indmom_real_data.py')
OUTNAME = 'nx_indmom_real.json'
COST, COST_SENS = 0.001, 0.003
H_LB = 0.015                    # 下限版の生き残りの偏りの見当（年）
H_LB_SENS = (0.0075, 0.03)      # R12
TAX_JP, WH_US = 0.20315, 0.10
MIN_EVAL = 180
T0 = time.time()


def log(*a):
    print(f'[{time.time() - T0:6.1f}s]', *a, flush=True)


madd, months = D.madd, D.months


def fmt(m):
    return f'{m // 100}-{m % 100:02d}'


def ikeys(d):
    return {int(k): v for k, v in d.items()}


# ───────────────────────── 照合 ─────────────────────────
def verify(pre):
    exp_tool = pre['tools']['data_tool_sha256']
    exp_rules = pre['tools']['rules_sha256']
    exp_ext = pre['tools']['extract_sha256']
    got_tool = hashlib.sha256(open(DATA_TOOL, 'rb').read()).hexdigest()
    if got_tool != exp_tool:
        raise SystemExit(f'データ道具の sha が登録と違う: {got_tool} ≠ {exp_tool} → 止まる')
    if D.rules_sha() != exp_rules:
        raise SystemExit(f'RULES の sha が登録と違う: {D.rules_sha()} ≠ {exp_rules} → 止まる')
    data = D.load_extract(check_sha=exp_ext)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ok = D.selftest()
    lines = [x for x in buf.getvalue().splitlines() if x.strip()]
    if not ok or len(lines) != 9:
        raise SystemExit(f'selftest が通らない: {lines}')
    return data, {'verified': True, 'data_tool_sha256': got_tool, 'rules_sha256': D.rules_sha(), 'extract_sha256': exp_ext,
                  'selftest': lines}


# ───────────────────────── 規則の組み立て ─────────────────────────
REF_SPECS = {
    'REF_EW_menu': {'kind': 'ew', 'H': 1},
    'REF_bridge_eknzbh_K3_R12': {'kind': 'topk', 'L': 12, 'skip': 0, 'K': 3, 'H': 1},
    'REF_bridge_eknzbh_K3_BL': {'kind': 'bl', 'K': 3, 'H': 1},
}


def cum(r, a, z):
    x = 1.0
    for m in months(a, z):
        x *= 1 + r[m]
    return x - 1


def pct_ranks(vals):
    """{k: v} → {k: (順位−1)/(N−1)}（昇順＝高いほど 1 に近い・同順位は平均順位）"""
    items = sorted(vals.items(), key=lambda x: x[1])
    n = len(items)
    rk, i = {}, 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        avg = (i + j) / 2 + 1
        for q in range(i, j + 1):
            rk[items[q][0]] = avg
        i = j + 1
    return {k: ((r - 1) / (n - 1) if n > 1 else 0.5) for k, r in rk.items()}


def scores(spec, rets, cands, t):
    kind = spec['kind']
    if kind == 'topk':
        z = madd(t, -spec['skip'])
        a = madd(z, -(spec['L'] - 1))
        return {k: cum(rets[k], a, z) for k in cands}
    if kind == 'multi':
        per = [pct_ranks({k: cum(rets[k], madd(t, -(L - 1)), t) for k in cands}) for L in spec['windows']]
        return {k: sum(p[k] for p in per) / len(per) for k in cands}
    if kind == 'bl':
        return {k: sum(cum(rets[k], madd(t, -(L - 1)), t) for L in (1, 3, 6, 12)) / 4 for k in cands}
    raise ValueError(kind)


def pick(sc, K):
    return [k for k, _ in sorted(sc.items(), key=lambda x: (-x[1], x[0]))[:K]]


def build(spec, rets, starts, form_months, k_fn=None):
    """形成の月 t（form_months・連続）ごとに候補（D.eligible＝t−12〜t の13か月・版の始まり以降）から選び、t+1 月の目標の重みを作る。
    H>1（P3）は直近 H 個の組（t−H+1〜t に作った組・評価の最初の月からだけ作る＝組がそろうまでは既にある組で等分）を 1/組数 ずつ。
    k_fn(spec, N, t) で K を差し替えられる（紙の双子の割合版）。戻り: w{hold_m: {記号: 重み}}・N{t}・K{t}・picks{t}"""
    H = spec.get('H', 1)
    W, Ns, Ks, P = {}, {}, {}, {}
    formed = []
    for t in form_months:
        cands = D.eligible(rets, t, starts)
        N = len(cands)
        Ns[t] = N
        if spec['kind'] == 'ew':
            picks = list(cands)
        else:
            K = k_fn(spec, N, t) if k_fn else D.k_of(spec, N)
            K = min(K, N)
            picks = pick(scores(spec, rets, cands, t), K)
        Ks[t] = len(picks)
        P[t] = picks
        formed.append(picks)
        act = [c for c in formed[-H:] if c]
        w = {}
        for c in act:
            for k in c:
                w[k] = w.get(k, 0.0) + 1.0 / len(act) / len(c)
        W[madd(t, 1)] = w
    return {'w': W, 'N': Ns, 'K': Ks, 'picks': P}


def run(W, hold_ret, cost=COST):
    """目標の重み W{m} と持つ月のリターン hold_ret{記号: {m: r}} → 月次の費用前・費用後・回転・実際の重み。
    持った器の月が欠けたら 0 と読まず外して残りで等分し件数を記録する（ルール7）。回転＝½Σ|新−前月の重みを当月のリターンで流した重み|・最初の月は 1"""
    gross, net, turn, weff, miss = {}, {}, {}, {}, []
    prev = None
    for m in sorted(W):
        w = W[m]
        avail = {k: v for k, v in w.items() if m in hold_ret.get(k, {})}
        if len(avail) < len(w):
            miss.append((m, sorted(set(w) - set(avail))))
        tw = sum(avail.values())
        if tw <= 0:
            raise SystemExit(f'{fmt(m)} に持てる器が無い')
        w2 = {k: v / tw for k, v in avail.items()}
        to = 1.0 if prev is None else 0.5 * sum(abs(w2.get(k, 0.0) - prev.get(k, 0.0)) for k in set(w2) | set(prev))
        g = math.fsum(v * hold_ret[k][m] for k, v in w2.items())
        gross[m], net[m], turn[m], weff[m] = g, g - to * cost, to, w2
        tot = math.fsum(v * (1 + hold_ret[k][m]) for k, v in w2.items())
        prev = {k: v * (1 + hold_ret[k][m]) / tot for k, v in w2.items()}
    return {'gross': gross, 'net': net, 'turn': turn, 'weff': weff, 'missing': miss}


def net_with(res, cost):
    return {m: res['gross'][m] - res['turn'][m] * cost for m in res['gross']}


def contributions(res, hold_ret, bench):
    c = collections.defaultdict(float)
    for m, w in res['weff'].items():
        for k, v in w.items():
            c[k] += v * (hold_ret[k][m] - bench[m])
    return dict(c)


# ───────────────────────── 統計の束 ─────────────────────────
def exact(s, b, a=None, z=None):
    ks = sorted(k for k in set(s) & set(b) if (a is None or k >= a) and (z is None or k <= z))
    if len(ks) < 24:
        return None
    ex = [s[k] - b[k] for k in ks]
    gs, gb = C.cagr([s[k] for k in ks]), C.cagr([b[k] for k in ks])
    return {'ex_ann_pct': S.mean(ex) * 1200, 'nw_t': C.nw_t(ex), 'cagr_diff_pct': (gs - gb) * 100}


def rolling_exact(s, b, years=20, start_month=7, per_year=12):
    """nx_common.rolling と同じ窓・同じ出力の形。勝ちは丸める前の gs−gb で数える（丸めは表示だけ）。nx_common の数え方も併記"""
    ks = sorted(set(s) & set(b))
    if not ks:
        return None
    raw = []
    y0 = ks[0] // 100
    last = ks[-1]
    for y in range(y0, 2100):
        a, z = y * 100 + start_month, (y + years) * 100 + start_month - 1 if start_month > 1 else (y + years - 1) * 100 + 12
        if z > last:
            break
        w = [k for k in ks if a <= k <= z]
        if len(w) < years * per_year * 0.97:
            continue
        gs = math.exp(math.fsum(math.log1p(s[k]) for k in w) / years) - 1
        gb = math.exp(math.fsum(math.log1p(b[k]) for k in w) / years) - 1
        raw.append((y, gs - gb, len(w)))
    if not raw:
        return None
    wins = sum(1 for _, c, _ in raw if c > 0)
    wins_r = sum(1 for _, c, _ in raw if round(c * 100, 2) > 0)
    v = sorted(c for _, c, _ in raw)
    wy, wc, _ = min(raw, key=lambda x: x[1])
    by, bc, _ = max(raw, key=lambda x: x[1])
    return {'windows': len(raw), 'wins': wins, 'win_rate': round(wins / len(raw), 3),
            'median': round(v[len(v) // 2] * 100, 2), 'worst': (wy, round(wc * 100, 2)), 'best': (by, round(bc * 100, 2)),
            'wins_nx_common_rounded': wins_r, 'win_rate_nx_common_rounded': round(wins_r / len(raw), 3),
            'by_start_year': {str(y): {'diff_pct': round(c * 100, 3), 'months': n} for y, c, n in raw}}


def dca_exact(s, b, years=20, step=12):
    ks = sorted(set(s) & set(b))
    n = years * 12
    raw = []
    for i in range(0, len(ks) - n + 1, step):
        w = ks[i:i + n]
        ws = wb = 0.0
        for k in w:
            ws = (ws + 1) * (1 + s[k]); wb = (wb + 1) * (1 + b[k])
        raw.append((w[0], ws / wb))
    if not raw:
        return None
    v = sorted(r for _, r in raw)
    wy, wr = min(raw, key=lambda x: x[1])
    by, br = max(raw, key=lambda x: x[1])
    wins = sum(1 for r in v if r > 1)
    wins_r = sum(1 for r in v if round(r, 3) > 1)
    return {'windows': len(raw), 'win_rate': round(wins / len(raw), 3), 'median_ratio': round(v[len(v) // 2], 3),
            'worst': (wy, round(wr, 3)), 'best': (by, round(br, 3)), 'win_rate_nx_common_rounded': round(wins_r / len(raw), 3),
            'by_start': {str(a): round(r, 4) for a, r in raw}}


class Ctx:
    pass


def halves(a, z):
    ms = months(a, z)
    h = len(ms) // 2
    return (ms[0], ms[h - 1]), (ms[h], ms[-1])


def stats_block(gross, net, bench, a, z, rf):
    (a1, z1), (a2, z2) = halves(a, z)
    E = C.excess_stats
    out = {
        'window': [a, z], 'months': len(months(a, z)), 'halves_windows': [[a1, z1], [a2, z2]],
        'full': E(gross, bench, a, z), 'first_half': E(gross, bench, a1, z1), 'second_half': E(gross, bench, a2, z2),
        'train_to_2006_12': E(gross, bench, a, C.TRAIN_END), 'hold_2007_on': E(gross, bench, C.HOLD_START, z),
        'recent_2013_07_on': E(gross, bench, C.RECENT_START, z),
        'after_cost': {'full': E(net, bench, a, z), 'first_half': E(net, bench, a1, z1), 'second_half': E(net, bench, a2, z2),
                       'train_to_2006_12': E(net, bench, a, C.TRAIN_END), 'hold_2007_on': E(net, bench, C.HOLD_START, z),
                       'recent_2013_07_on': E(net, bench, C.RECENT_START, z)},
        'unrounded': {'gross_full': exact(gross, bench, a, z), 'gross_first_half': exact(gross, bench, a1, z1),
                      'gross_second_half': exact(gross, bench, a2, z2), 'net_full': exact(net, bench, a, z)},
        'maxdd_pct': {'rule_gross': round(C.maxdd(C.window(gross, a, z)) * 100, 1), 'rule_net': round(C.maxdd(C.window(net, a, z)) * 100, 1),
                      'bench': round(C.maxdd(C.window(bench, a, z)) * 100, 1)},
        'sharpe': {w: {'rule_gross': C.sharpe(gross, rf, x, y), 'rule_net': C.sharpe(net, rf, x, y), 'bench': C.sharpe(bench, rf, x, y)}
                   for w, x, y in (('full', a, z), ('train_to_2006_12', a, C.TRAIN_END), ('hold_2007_on', C.HOLD_START, z))},
    }
    out['sharpe']['note'] = '無リスク金利は French RF（月次）。重ねる・借入・時期選びの型ではない（常に株100%の業種の入れ替え）＝C8 は該当なし・報告のみ'
    return out


def windows_block(gross, net, bench, a, z):
    g, n, b = C.window(gross, a, z), C.window(net, a, z), C.window(bench, a, z)
    return {'roll20_gross': rolling_exact(g, b, 20), 'roll20_net': rolling_exact(n, b, 20),
            'roll10_gross': rolling_exact(g, b, 10), 'roll10_net': rolling_exact(n, b, 10),
            'roll20_nx_common_gross': C.rolling(g, b, 20), 'roll20_nx_common_net': C.rolling(n, b, 20),
            'dca20_gross': dca_exact(g, b, 20), 'dca20_net': dca_exact(n, b, 20),
            'dca10_gross': dca_exact(g, b, 10), 'dca10_net': dca_exact(n, b, 10)}


def turnover_block(res, node_of, a, z):
    ms = [m for m in sorted(res['turn']) if a <= m <= z]
    tv = [res['turn'][m] for m in ms]
    held = collections.Counter()
    entries = collections.defaultdict(int)
    prev = set()
    for m in ms:
        cur = {k for k, v in res['weff'][m].items() if v > 0}
        for k in cur:
            held[k] += 1
        if prev:
            entries[m // 100] += len(cur - prev)
        prev = cur
    yrs = sorted(entries)
    return {'annual_oneway_turnover_incl_first': round(S.mean(tv) * 12, 3),
            'annual_oneway_turnover_excl_first': round(S.mean(tv[1:]) * 12, 3),
            'share_of_months_held': {f'{node_of.get(k, k)}:{k}': round(c / len(ms), 3) for k, c in held.most_common()},
            'new_entries_per_year_mean': round(S.mean(entries[y] for y in yrs), 2) if yrs else None,
            'new_entries_by_year': {str(y): entries[y] for y in yrs},
            'missing_held_months': res['missing']}


# ───────────────────────── 課税口座の模擬（R7） ─────────────────────────
def price_index(cret):
    ks = sorted(cret)
    P = {madd(ks[0], -1): 1.0}
    x = 1.0
    for k in ks:
        x *= 1 + cret[k]
        P[k] = x
    return P


def tax_sim(W, t0, t_end, P, dy, fx, tax=TAX_JP, wh=WH_US, carry=True, cost=COST, initial_cost=True, sell_all_end=False, V0=1_000_000.0):
    """円の課税口座（特定口座・源泉徴収あり）の模擬。W{m}＝月 m に持つ目標の重み（t0 の月末に W[t0+1] を買う）。
    P{記号}{月}＝終値の指数（分割調整済み・配当未調整）、dy{記号}{月}＝その月の配当÷前月末の終値、fx{月}＝円/ドルの月末。
    ・取得価額は移動平均（円）。売るたびに 実現益 = 株数×(値×fx − 平均の取得価額)
    ・年の中は通算し、年の累計の正の分に tax を売った月に引く（損が出たら戻す）。年をまたぐ損は carry=True なら3年繰り越す（年末に相殺して戻す）
    ・配当は (1−wh)(1−tax) を受け取り、その月末に同じ器へ買い足す（取得価額に足す）
    ・売買の費用は 片道の売り額 × cost（最初の買いは initial_cost のときだけ）
    戻り: 最終の円・年ごとの買付額・年ごとの平均の評価額・税の合計"""
    sh, basis = {}, {}
    realized_ytd, tax_ytd = 0.0, 0.0
    pool = []   # [年, 残りの損]
    bought = collections.defaultdict(float)
    vals = collections.defaultdict(list)
    tax_total, div_tax_total, cost_total = 0.0, 0.0, 0.0

    def px(k, m):
        return P[k][m] * fx[m]

    def buy(k, amt, m):
        q = amt / px(k, m)
        s0 = sh.get(k, 0.0)
        basis[k] = (basis.get(k, 0.0) * s0 + amt) / (s0 + q)
        sh[k] = s0 + q

    def year_end(y, realized):
        """年末（または最後の売り）: 繰越の相殺による戻り（正の数＝口座へ戻る円）"""
        nonlocal pool
        refund = 0.0
        if carry:
            pool = [[yy, a] for yy, a in pool if y - yy <= 3 and a > 0]
            if realized < 0:
                pool.append([y, -realized])
            elif realized > 0:
                rem = realized
                for p in pool:
                    use = min(rem, p[1])
                    p[1] -= use
                    rem -= use
                    refund += tax * use
                    if rem <= 0:
                        break
                pool = [p for p in pool if p[1] > 0]
        return refund

    # 最初の買い
    w0 = W[madd(t0, 1)]
    inv = V0 / (1 + cost) if initial_cost else V0
    cost_total += V0 - inv
    for k, v in w0.items():
        buy(k, inv * v, t0)
        bought[t0 // 100] += inv * v
    m = madd(t0, 1)
    while True:
        # 月 m の配当（前月末の株数 × 配当 → 税を引いて同じ器へ）
        for k in list(sh):
            d = dy.get(k, {}).get(m)
            if d:
                gross_div = sh[k] * d * P[k][madd(m, -1)] * fx[m]
                netd = gross_div * (1 - wh) * (1 - tax)
                div_tax_total += gross_div - netd
                buy(k, netd, m)
        V = sum(sh[k] * px(k, m) for k in sh)
        vals[m // 100].append(V)
        if m >= t_end:
            break
        # 月末 m の入れ替え（W[m+1] へ）
        tgt = W[madd(m, 1)]
        cur = {k: sh[k] * px(k, m) for k in sh}
        D_ = {k: tgt.get(k, 0.0) * V for k in set(cur) | set(tgt)}
        sells, realized = 0.0, 0.0
        for k in list(cur):
            if cur[k] > D_[k] + 1e-9:
                x = cur[k] - D_[k]
                q = x / px(k, m)
                realized += q * (px(k, m) - basis[k])
                sh[k] -= q
                sells += x
                if sh[k] <= 1e-12 * max(1.0, V):
                    sh.pop(k); basis.pop(k)
        realized_ytd += realized
        new_tax = tax * max(0.0, realized_ytd)
        tax_cash = new_tax - tax_ytd
        tax_ytd = new_tax
        c = cost * sells
        cost_total += c
        cash = sells - tax_cash - c
        tax_total += tax_cash
        if m % 100 == 12:
            ref = year_end(m // 100, realized_ytd)
            cash += ref
            tax_total -= ref
            realized_ytd, tax_ytd = 0.0, 0.0
        short = {k: D_[k] - cur.get(k, 0.0) for k in tgt if D_[k] > cur.get(k, 0.0) + 1e-9}
        su = sum(short.values())
        if cash > 0:
            if su > 0:
                for k, u in short.items():
                    buy(k, cash * u / su, m)
                    bought[m // 100] += cash * u / su
            else:
                for k, v in tgt.items():
                    buy(k, cash * v, m)
                    bought[m // 100] += cash * v
        m = madd(m, 1)
    V_end = sum(sh[k] * px(k, t_end) for k in sh)
    out = {}
    if sell_all_end:
        realized = sum(sh[k] * (px(k, t_end) - basis[k]) for k in sh)
        ry = realized_ytd + realized
        t_final = tax * max(0.0, ry) - tax_ytd
        ref = year_end(t_end // 100, ry)
        out['V_end_sold'] = V_end - t_final + ref - cost * V_end
        out['final_tax_on_sale'] = t_final - ref
        out['V_end_hold'] = V_end
    else:
        # 最後の年（途中で終わる年）の実現損益にも前の年の繰越を当てる（翌年の申告で戻る分）。含み益には課税しない
        ref = year_end(t_end // 100, realized_ytd)
        out['V_end_hold'] = V_end + ref
        out['final_year_carry_refund'] = ref
    out.update({'bought_by_year': dict(bought), 'avg_value_by_year': {y: S.mean(v) for y, v in vals.items()},
                'tax_on_gains_total': tax_total, 'tax_on_div_total': div_tax_total, 'cost_total': cost_total})
    return out


# ───────────────────────── 合成データの点検 ─────────────────────────
def synthetic_checks():
    rnd = random.Random(20260929)
    ok = []
    tick = [f'S{i:02d}' for i in range(16)]
    R = {k: {m: rnd.gauss(0.008, 0.06) for m in months(200001 + (i % 4) * 3 if i < 12 else 200601, 202012)} for i, k in enumerate(tick)}
    st = {k: min(v) for k, v in R.items()}
    fm = months(200201, 201911)
    specs = dict(D.RULES)
    specs.update(REF_SPECS)
    la_ok, to_ok, k_ok, sum_ok, coh_ok = True, True, True, True, True
    info = []
    for name, sp in specs.items():
        B = build(sp, R, st, fm)
        res = run(B['w'], R)
        for t in (200406, 200912, 201505):
            R2 = {k: {m: (x if m <= t else rnd.gauss(0.0, 0.2)) for m, x in v.items()} for k, v in R.items()}
            B2 = build(sp, R2, st, fm)
            same = all(B['w'][m] == B2['w'][m] for m in B['w'] if m <= madd(t, 1))
            if not same:
                la_ok = False; info.append(('lookahead', name, t))
        if not all(0.0 <= x <= 1.0 + 1e-12 for x in res['turn'].values()):
            to_ok = False; info.append(('turnover', name))
        for t in fm:
            N = B['N'][t]
            if sp['kind'] != 'ew' and B['K'][t] != min(D.k_of(sp, N), N):
                k_ok = False; info.append(('K', name, t))
            if sp['kind'] == 'ew' and B['K'][t] != N:
                k_ok = False
        for m, w in B['w'].items():
            if abs(sum(w.values()) - 1) > 1e-9:
                sum_ok = False; info.append(('sum', name, m))
        if sp.get('H', 1) > 1:
            H = sp['H']
            for t in fm[10:40]:
                m = madd(t, 1)
                cohorts = [B['picks'][u] for u in months(madd(t, -(H - 1)), t)]
                exp = collections.defaultdict(float)
                for c in cohorts:
                    for k in c:
                        exp[k] += 1.0 / H / len(c)
                if len(cohorts) != 6 or any(abs(exp[k] - B['w'][m].get(k, 0.0)) > 1e-12 for k in set(exp) | set(B['w'][m])):
                    coh_ok = False; info.append(('cohort', name, m))
            # 最初の月は1組だけ（組がそろうまでは既にある組で等分）、2か月目は2組を 1/2 ずつ
            m0, m1 = madd(fm[0], 1), madd(fm[1], 1)
            if set(B['w'][m0]) != set(B['picks'][fm[0]]) or any(abs(v - 1 / len(B['picks'][fm[0]])) > 1e-12 for v in B['w'][m0].values()):
                coh_ok = False; info.append(('cohort_first', name))
            exp = collections.defaultdict(float)
            for c in (B['picks'][fm[0]], B['picks'][fm[1]]):
                for k in c:
                    exp[k] += 0.5 / len(c)
            if any(abs(exp[k] - B['w'][m1].get(k, 0.0)) > 1e-12 for k in set(exp) | set(B['w'][m1])):
                coh_ok = False; info.append(('cohort_second', name))
    ok.append({'check': '先読みなし（t より後のリターンを乱しても t+1 までの持ち物が同じ）', 'ok': la_ok})
    ok.append({'check': '回転は 0〜1', 'ok': to_ok})
    ok.append({'check': '選んだ本数が K（割合は max(2, floor(frac·N+0.5))・N を超えない）', 'ok': k_ok})
    ok.append({'check': '等分の和が 1', 'ok': sum_ok})
    ok.append({'check': 'P3 の組は 1/6 ずつ（組の中は等分・組がそろうまでは既にある組で等分）', 'ok': coh_ok})
    # 回転の手計算: 2か月、A 100% → B 100% は回転 1、同じなら 0
    res = run({200101: {'A': 1.0}, 200102: {'B': 1.0}, 200103: {'B': 1.0}}, {'A': {200101: .1, 200102: 0, 200103: 0}, 'B': {200101: 0, 200102: .05, 200103: .02}})
    ok.append({'check': '回転の手計算（最初 1・全入れ替え 1・同じ 0）', 'ok': [res['turn'][m] for m in (200101, 200102, 200103)] == [1.0, 1.0, 0.0]})
    res = run({200101: {'A': .5, 'B': .5}, 200102: {'A': .5, 'B': .5}}, {'A': {200101: .2, 200102: 0}, 'B': {200101: 0, 200102: 0}})
    # 流した重み A 0.6/1.1·… : A=0.6/1.1=0.54545, B=0.45454 → 回転 = 0.04545
    ok.append({'check': '回転の手計算（等分に戻す 0.04545）', 'ok': abs(res['turn'][200102] - 0.5 * (2 * (0.6 / 1.1 - 0.5))) < 1e-12})
    # 欠けの扱い
    res = run({200101: {'A': .5, 'B': .5}}, {'A': {200101: .1}, 'B': {}})
    ok.append({'check': '持った器の欠けは 0 と読まず外して等分・件数を記録', 'ok': abs(res['gross'][200101] - .1) < 1e-12 and res['missing'] == [(200101, ['B'])]})
    # 課税口座の模擬: 税 0・費用 0 なら Π(Σw(1+cret+dy)) と一致
    tk = ['A', 'B', 'C']
    cret = {k: {m: rnd.gauss(0.006, 0.05) for m in months(200001, 200512)} for k in tk}
    dyv = {k: {m: (0.004 if m % 3 == 0 else 0.0) for m in months(200001, 200512)} for k in tk}
    P = {k: price_index(cret[k]) for k in tk}
    fx1 = {m: 1.0 for m in months(199912, 200512)}
    W = {}
    for m in months(200002, 200512):
        a = tk[m % 3]; b = tk[(m + 1) % 3]
        W[m] = {a: .6, b: .4}
    ts = tax_sim(W, 200001, 200512, P, dyv, fx1, tax=0.0, wh=0.0, cost=0.0, initial_cost=False)
    x = 1e6
    for m in months(200002, 200512):
        x *= sum(v * (1 + cret[k][m] + dyv[k][m]) for k, v in W[m].items())
    ok.append({'check': '課税口座の模擬: 税0・費用0 なら総リターンの積と一致', 'ok': abs(ts['V_end_hold'] / x - 1) < 1e-9, 'sim': ts['V_end_hold'], 'product': x})
    # 税の手計算: A が +10%（年1）→ B へ全部入れ替え → B は動かない。税 = 0.20315×10万円
    cret2 = {'A': {200101: .10, 200102: 0.0, 200103: 0.0}, 'B': {200101: 0.0, 200102: 0.0, 200103: 0.0}}
    P2 = {k: price_index(v) for k, v in cret2.items()}
    fx2 = {m: 1.0 for m in months(200012, 200103)}
    ts = tax_sim({200101: {'A': 1.0}, 200102: {'B': 1.0}, 200103: {'B': 1.0}}, 200012, 200103, P2, {}, fx2, cost=0.0, initial_cost=False)
    ok.append({'check': '税の手計算（利益10万円 → 税20,315円）', 'ok': abs(ts['V_end_hold'] - (1.1e6 - 0.20315 * 1e5)) < 1e-6, 'sim': ts['V_end_hold']})
    # 繰越: 年1 に A が −10% で損を確定（12月に入れ替え）、年2 に B が +20% で利益を確定 → 繰越ありなら 12月に相殺
    cret3 = {'A': {m: (-.10 if m == 200106 else 0.0) for m in months(200101, 200212)}, 'B': {m: (.2 if m == 200205 else 0.0) for m in months(200101, 200212)},
             'Z': {m: 0.0 for m in months(200101, 200212)}}
    P3 = {k: price_index(v) for k, v in cret3.items()}
    fx3 = {m: 1.0 for m in months(200012, 200212)}
    W3 = {m: ({'A': 1.0} if m <= 200112 else ({'B': 1.0} if m <= 200206 else {'Z': 1.0})) for m in months(200101, 200212)}
    tc = tax_sim(W3, 200012, 200212, P3, {}, fx3, cost=0.0, initial_cost=False, carry=True)
    tn = tax_sim(W3, 200012, 200212, P3, {}, fx3, cost=0.0, initial_cost=False, carry=False)
    # 年1: 1e6→0.9e6（損 10万）。年2: 0.9e6→1.08e6、B を 6月末に売って益 18万。繰越なし: 税 36,567。繰越あり: 12月に 10万ぶん 20,315 を戻す
    ok.append({'check': '損の3年繰越の手計算（繰越なし 税36,567円・繰越あり 16,252円）',
               'ok': abs(tn['V_end_hold'] - (1.08e6 - 0.20315 * 1.8e5)) < 1e-6 and abs(tc['V_end_hold'] - (1.08e6 - 0.20315 * 0.8e5)) < 1e-6,
               'no_carry': tn['V_end_hold'], 'carry': tc['V_end_hold']})
    return {'all_ok': all(x['ok'] for x in ok), 'checks': ok, 'failures': info[:20]}


# ───────────────────────── 実データの準備 ─────────────────────────
def prepare(data, pre):
    X = Ctx()
    X.data = data
    X.ret = {t: ikeys(v) for t, v in data['ret_m'].items()}
    X.cret = {t: ikeys(v) for t, v in data['close_ret_m'].items()}
    X.dy = {t: ikeys(v) for t, v in data['div_yield_m'].items()}
    X.retd = {t: ikeys(v) for t, v in data['ret_d'].items() if 'error' not in v}
    fr = data['french']
    X.mkt, X.rf = ikeys(fr['mkt']), ikeys(fr['rf'])
    X.ind49 = {c: ikeys(v) for c, v in fr['ind49'].items()}
    X.ind30 = {c: ikeys(v) for c, v in fr['ind30'].items()}
    X.fx = ikeys(data['fx_usdjpy_month_end'])
    U = data['universe']
    X.reps = {v: {n: x['rep'] for n, x in U['reps'][v].items()} for v in ('etf_only', 'spliced')}
    X.starts = {v: {k: int(s) for k, s in U['starts'][v].items() if s is not None} for v in ('etf_only', 'spliced')}
    X.spy, X.qqq = X.ret['SPY'], X.ret['QQQ']
    X.END = data['end']
    return X


def universe(X, variant='etf_only', pick_nodes=lambda n: True, extra=None, drop=()):
    """代表の記号 → リターン（版の始まり以降だけ）と始まり。extra={node: 記号} で node を足す（R16）"""
    reps = {n: t for n, t in X.reps[variant].items() if pick_nodes(n)}
    if extra:
        reps.update(extra)
    reps = {n: t for n, t in reps.items() if t not in drop}
    st = X.starts[variant]
    rets = {t: {m: r for m, r in X.ret[t].items() if m >= st[t] and m <= X.END} for t in reps.values()}
    starts = {t: st[t] for t in reps.values()}
    node_of = {t: n for n, t in reps.items()}
    return rets, starts, node_of


def first_formation(rets, starts, nmin):
    for t in months(199901, madd(D.END, -1)):
        if len(D.eligible(rets, t, starts)) >= nmin:
            return t
    return None


def lag_returns(X, tickers):
    """R5: t+1 月の最初の営業日の引け → t+2 月の最初の営業日の引け（日足の調整後終値）。区間の日は SPY の暦（最初の営業日）で決め、
    各記号は区間の中の自分の日足を複利でつなぐ（Yahoo の日足のリターンは直前の足からなので、足の欠けは次の足に入っている）"""
    spyd = X.retd['SPY']
    days = sorted(spyd)
    first = {}
    for d in days:
        first.setdefault(d // 100, d)
    out, gaps = {}, {}
    ms = sorted(first)
    for t in tickers:
        r = X.retd.get(t)
        if r is None:
            continue
        rd = sorted(r)
        o, g = {}, 0
        for m0, m1 in zip(ms, ms[1:]):
            a, z = first[m0], first[m1]
            i = bisect.bisect_right(rd, a)
            j = bisect.bisect_right(rd, z)
            seg = rd[i:j]
            if not seg or rd[0] > a:
                continue
            n_spy = bisect.bisect_right(days, z) - bisect.bisect_right(days, a)
            if len(seg) < n_spy:
                g += n_spy - len(seg)
            x = 1.0
            for d in seg:
                x *= 1 + r[d]
            o[m0] = x - 1
        out[t], gaps[t] = o, g
    return out, gaps


# ───────────────────────── 測る ─────────────────────────
def drop_top_block(spec, X, rets, starts, a, z, res, bench):
    con = contributions(res, rets, bench)
    top = max(con, key=con.get)
    r2 = {k: v for k, v in rets.items() if k != top}
    s2 = {k: v for k, v in starts.items() if k != top}
    B2 = build(spec, r2, s2, months(madd(a, -1), madd(z, -1)))
    res2 = run(B2['w'], r2)
    return {'contributions_pct_sum': {k: round(v * 100, 2) for k, v in sorted(con.items(), key=lambda x: -x[1])},
            'dropped': top, 'stats_gross': C.excess_stats(res2['gross'], bench, a, z),
            'unrounded_cagr_diff_pct': exact(res2['gross'], bench, a, z)['cagr_diff_pct']}


def paper_twin(spec, X, real_gross, real_net, a, z, table='ind49', k_mode='def', real_B=None):
    """紙の双子: 同じ規則を French 49（か 30）の VW に同じ評価の月で。K は規則の定義どおり（def）か実物と同じ割合（frac）"""
    ind = getattr(X, table)
    rets = {c: v for c, v in ind.items()}
    starts = {c: min(v) for c, v in ind.items()}
    k_fn = None
    if k_mode == 'frac':
        def k_fn(sp, N, t):
            Kr, Nr = real_B['K'][t], real_B['N'][t]
            return max(2, int(math.floor(N * Kr / Nr + 0.5)))
    B = build(spec, rets, starts, months(madd(a, -1), madd(z, -1)), k_fn)
    res = run(B['w'], rets)
    g_gross = {m: (real_gross[m] - X.spy[m]) - (res['gross'][m] - X.mkt[m]) for m in months(a, z)}
    g_net = {m: (real_net[m] - X.spy[m]) - (res['net'][m] - X.mkt[m]) for m in months(a, z)}
    (a1, z1), (a2, z2) = halves(a, z)

    def gb(g, r_real, r_paper):
        out = {}
        for nm, x, y in (('full', a, z), ('first_half', a1, z1), ('second_half', a2, z2), ('hold_2007_on', C.HOLD_START, z)):
            ks = months(x, y)
            ex = [g[m] for m in ks]
            real_d = C.cagr([r_real[m] for m in ks]) - C.cagr([X.spy[m] for m in ks])
            pap_d = C.cagr([r_paper[m] for m in ks]) - C.cagr([X.mkt[m] for m in ks])
            t = C.nw_t(ex)
            out[nm] = {'g_ann_pct': round(S.mean(ex) * 1200, 2), 'nw_t': round(t, 2) if t is not None else None,
                       'geo_real_minus_spy_pct': round(real_d * 100, 2), 'geo_paper_minus_mkt_pct': round(pap_d * 100, 2),
                       'geo_gap_pct': round((real_d - pap_d) * 100, 2)}
        return out
    Ks = sorted(set(B['K'].values()))
    return {'table': table, 'k_mode': k_mode, 'paper_K_values': Ks, 'paper_N_values': sorted(set(B['N'].values())),
            'gross': gb(g_gross, real_gross, res['gross']), 'net': gb(g_net, real_net, res['net']),
            'paper_vs_mkt_gross_full': C.excess_stats(res['gross'], X.mkt, a, z),
            'paper_vs_mkt_net_full': C.excess_stats(res['net'], X.mkt, a, z),
            'paper_vs_spy_gross_full': C.excess_stats(res['gross'], X.spy, a, z),
            'paper_annual_turnover': round(S.mean(res['turn'][m] for m in months(a, z)) * 12, 3)}


def grade_unit(st, drop, net_lb, family_p):
    full = st['full']
    return C.grade_short(full, st['first_half'], st['second_half'], drop['stats_gross'], st['after_cost']['full'], net_lb, family_p)


def lower_bound(res, bench, a, z, h):
    lb = {m: res['net'][m] - h / 12 for m in res['net']}
    return C.excess_stats(lb, bench, a, z), exact(lb, bench, a, z)


def data_checks(X, pre, a_eval):
    out = {}
    # 1) 評価の始まりと各月の候補の数（事前登録の形と ±0）
    shp = pre['data']['shape_menu_and_eval_windows']
    res = {}
    for v in ('etf_only', 'spliced'):
        for un, pk in (('U_all', lambda n: True), ('U_sector', lambda n: n.startswith('S_')), ('U_narrow', lambda n: not n.startswith('S_'))):
            rets, starts, _ = universe(X, v, pk)
            t0 = first_formation(rets, starts, D.MIN_N)
            nby = {str(y): len(D.eligible(rets, y * 100 + 12, starts)) for y in range(1999, 2026)}
            exp = shp[f'{v}:{un}']
            e_from = exp['eval_from']
            got_from = fmt(madd(t0, 1)) if t0 else None
            same = (got_from == e_from) and all(nby[y] == exp['N_eligible_by_year_end'][y] for y in nby)
            res[f'{v}:{un}'] = {'eval_from_got': got_from, 'eval_from_prereg': e_from, 'N_by_year_end_match': same}
    out['menu_matches_prereg'] = res
    out['menu_all_match'] = all(x['N_by_year_end_match'] for x in res.values())
    # 2) SPY と French Mkt
    ks = [k for k in X.spy if k in X.mkt and a_eval <= k <= X.END]
    out['spy_vs_french_mkt_eval'] = {'months': len(ks), 'corr': round(C.corr([X.spy[k] for k in ks], [X.mkt[k] for k in ks]), 4)}
    ks2 = [k for k in X.spy if k in X.mkt and k >= 199401]
    out['spy_vs_french_mkt_1994on'] = {'months': len(ks2), 'corr': round(C.corr([X.spy[k] for k in ks2], [X.mkt[k] for k in ks2]), 4)}
    # 3) |月次| > 40% の月を日足と突き合わせる（使う期間の代表だけ）
    big = []
    reps = set(X.reps['etf_only'].values()) | set(X.reps['spliced'].values()) | {'RWR'}
    for t in sorted(reps):
        st = min(X.starts['etf_only'].get(t, 999999), X.starts['spliced'].get(t, 999999))
        for m, r in sorted(X.ret[t].items()):
            if m < st or m > X.END or abs(r) <= 0.40:
                continue
            dd = X.retd.get(t)
            comp = None
            if dd:
                x = 1.0
                n = 0
                for d, rr in dd.items():
                    if d // 100 == m:
                        x *= 1 + rr; n += 1
                comp = x - 1 if n else None
            big.append({'ticker': t, 'month': m, 'monthly_pct': round(r * 100, 2),
                        'daily_compounded_pct': round(comp * 100, 2) if comp is not None else None,
                        'agree_within_1pt': (abs(comp - r) < 0.01) if comp is not None else None})
    out['abs_month_gt_40pct'] = big
    out['abs_month_gt_40pct_verdict'] = ('すべて日足の複利と1ポイント以内で一致＝データの誤りではない→値をそのまま使う'
                                          if all(b['agree_within_1pt'] for b in big if b['agree_within_1pt'] is not None)
                                          else '日足と合わない月がある（下の一覧）')
    # 4) 欠けを 0 で埋めていない: 代表の月次に None が無い・版の始まり以降に穴が無い
    holes = {}
    for v in ('etf_only', 'spliced'):
        for n, t in X.reps[v].items():
            ks = [m for m in months(X.starts[v][t], X.END)]
            miss = [m for m in ks if m not in X.ret[t]]
            if miss:
                holes[f'{v}:{t}'] = miss
    out['holes_after_start'] = holes
    return out


def implied_dy(X, tickers, a, z):
    """R7 の配当: 使う期間で『終値＋抽出の配当』の積が調整後終値の積から 5% 以上離れる器は、配当の記録が抜けている
    （0 ではない＝ルール7。他の器は ±1% 以内＝再投資の時点の差だけ）。その器だけ、同じ Yahoo の調整後終値から月の配当利回りを
    max(0, 調整後の月次 − 終値の月次) で作る（事前登録からの逸脱・R7 の報告だけ・格付けに無関係）"""
    out, fixed = {}, {}
    for k in tickers:
        dyk = X.dy.get(k, {})
        st = max(a, X.starts['etf_only'].get(k, a))
        ms = [m for m in months(st, z) if m in X.ret[k] and m in X.cret[k]]
        ratio = math.prod(1 + X.ret[k][m] for m in ms) / math.prod(1 + X.cret[k][m] + dyk.get(m, 0.0) for m in ms) if ms else 1.0
        n_ev = sum(1 for m in ms if dyk.get(m))
        if abs(ratio - 1) > 0.05:   # 他の器は ±1% 以内（配当の再投資の時点の差だけ）。5% を超えるのは配当の記録の欠け
            out[k] = {m: max(0.0, X.ret[k][m] - X.cret[k][m]) for m in X.ret[k] if m in X.cret[k] and m >= st}
            out[k].update({m: v for m, v in dyk.items() if m < st})
            fixed[k] = {'used_from': st, 'n_dividend_events_in_extract_in_used_period': n_ev,
                        'n_dividend_events_in_extract_before_used_period': sum(1 for m in dyk if m < st),
                        'adj_over_close_plus_div_product_in_used_period': round(ratio, 4)}
        else:
            out[k] = dyk
    return out, fixed


def tax_report(X, W, t0, t_end, tickers_needed, dy_mode='implied_for_missing'):
    P = {k: price_index(X.cret[k]) for k in tickers_needed}
    if dy_mode == 'as_registered':
        dy = {k: X.dy.get(k, {}) for k in tickers_needed}
    else:
        dy, _ = implied_dy(X, tickers_needed, madd(t0, 1), t_end)
    W_spy = {m: {'SPY': 1.0} for m in months(madd(t0, 1), t_end)}
    yrs = (len(months(madd(t0, 1), t_end))) / 12
    out = {}
    for fx_mode in ('jpy', 'usd'):
        fx = X.fx if fx_mode == 'jpy' else {m: 1.0 for m in X.fx}
        pre_r = tax_sim(W, t0, t_end, P, dy, fx, tax=0.0, wh=0.0)
        pre_s = tax_sim(W_spy, t0, t_end, P, dy, fx, tax=0.0, wh=0.0, initial_cost=False)
        for carry in (True, False):
            for end in ('hold', 'sell'):
                r = tax_sim(W, t0, t_end, P, dy, fx, carry=carry, sell_all_end=(end == 'sell'))
                s = tax_sim(W_spy, t0, t_end, P, dy, fx, carry=carry, initial_cost=False, sell_all_end=(end == 'sell'))
                kr = 'V_end_sold' if end == 'sell' else 'V_end_hold'
                vr, vs = r[kr], s[kr]
                pr = pre_r['V_end_hold'] * (1 - (COST if end == 'sell' else 0.0))
                ps = pre_s['V_end_hold'] * (1 - (COST if end == 'sell' else 0.0))
                ann = lambda v: ((v / 1e6) ** (1 / yrs) - 1) * 100
                d_after = ann(vr) - ann(vs)
                d_pre = ann(pr) - ann(ps)
                out[f'{fx_mode}:{"carry3y" if carry else "no_carry"}:{end}'] = {
                    'rule_final_per_1M': round(vr), 'spy_final_per_1M': round(vs), 'ratio_after_tax': round(vr / vs, 4),
                    'ann_diff_after_tax_pct': round(d_after, 2), 'ann_diff_pre_tax_pct': round(d_pre, 2),
                    'tax_drag_on_diff_pct': round(d_pre - d_after, 2), 'ratio_pre_tax': round(pr / ps, 4),
                    'rule_tax_on_gains_total': round(r['tax_on_gains_total'] + r.get('final_tax_on_sale', 0.0)),
                    'spy_tax_on_gains_total': round(s['tax_on_gains_total'] + s.get('final_tax_on_sale', 0.0)),
                    'rule_tax_on_div_total': round(r['tax_on_div_total']), 'spy_tax_on_div_total': round(s['tax_on_div_total'])}
                if fx_mode == 'jpy' and carry and end == 'hold':
                    nisa = {}
                    for y, b in sorted(r['bought_by_year'].items()):
                        av = r['avg_value_by_year'].get(y)
                        if av:
                            nisa[str(y)] = {'bought_per_1M_start': round(b), 'avg_value': round(av), 'buys_over_avg_value': round(b / av, 2)}
                    ratios = [v['buys_over_avg_value'] for y, v in nisa.items() if int(y) > t0 // 100 and int(y) < t_end // 100]
                    out['nisa'] = {'by_year': nisa, 'median_annual_buys_over_value': S.median(ratios) if ratios else None,
                                   'max_annual_buys_over_value': max(ratios) if ratios else None,
                                   'implied_max_portfolio_jpy_in_2_4M_frame_median': round(2.4e6 / S.median(ratios)) if ratios else None,
                                   'implied_max_portfolio_jpy_in_2_4M_frame_worst_year': round(2.4e6 / max(ratios)) if ratios else None,
                                   'note': 'NISA 成長投資枠は年 240 万円の買付（売った枠は翌年に戻る・生涯 1,200 万円は簿価）。毎月の入れ替えで買うたびに枠を使う＝年の買付が評価額の何倍かで、枠の中で回せる評価額の目安は 240万 ÷ その倍率'}
    # 模擬の点検: 税0・円/ドル=1 の模擬と 費用後の調整後リターンの積の比（配当の扱いの差・費用の掛け方の差の大きさ）
    pre_usd = tax_sim(W, t0, t_end, P, dy, {m: 1.0 for m in X.fx}, tax=0.0, wh=0.0)
    out['sim_vs_adjclose_check_usd_pre_tax'] = {'sim_final': round(pre_usd['V_end_hold']), 'note': '税0・為替なしの模擬の最終額（調整後の月次の積との比は tested の各規則の r7_check に）'}
    return out, pre_usd['V_end_hold']


def main():
    pre = json.load(open(PRE))
    data, frozen = verify(pre)
    log('照合 OK', frozen['extract_sha256'][:12])
    syn = synthetic_checks()
    log('合成データの点検', syn['all_ok'])
    if not syn['all_ok']:
        print(json.dumps(syn, ensure_ascii=False, indent=1, default=str))
        raise SystemExit('合成データの点検が通らない → 止まる')
    X = prepare(data, pre)
    rets_all, starts_all, node_all = universe(X, 'etf_only')
    t0 = first_formation(rets_all, starts_all, D.MIN_N)
    A, Z = madd(t0, 1), X.END
    log('評価', fmt(A), '〜', fmt(Z), len(months(A, Z)), 'か月')
    checks = data_checks(X, pre, A)
    log('形の点検 menu 一致', checks['menu_all_match'], 'corr', checks['spy_vs_french_mkt_eval'])
    if not checks['menu_all_match']:
        raise SystemExit('候補の数が事前登録の形と一致しない → 止まる')
    rets_sec, starts_sec, node_sec = universe(X, 'etf_only', lambda n: n.startswith('S_'))

    desc = {k: v['what'] for k, v in D.RULES.items()}
    units = []
    for rid, sp in D.RULES.items():
        units.append(('P', rid, sp, 'U_all', rets_all, starts_all, node_all, desc[rid]))
    for i, (rid, sp) in enumerate(D.RULES.items(), 1):
        units.append(('E', f'E{i}_{rid[3:]}_U_sector', sp, 'U_sector', rets_sec, starts_sec, node_sec, '探索: ' + desc[rid] + '（U_sector＝11セクターの器だけ）'))
    for rid, sp in REF_SPECS.items():
        units.append(('REF', rid, sp, 'U_all', rets_all, starts_all, node_all, D.REFERENCE[rid]))

    # 1日遅れの約定（R5）の区間リターン
    lagr, lag_gaps = lag_returns(X, sorted(set(rets_all) | {'SPY', 'QQQ'}))
    Zlag = max(m for m in lagr['SPY'] if m <= X.END)
    lag_spy = lagr['SPY']

    M = {}
    for fam, rid, sp, un, rets, starts, node_of, ds in units:
        log('測る', rid)
        B = build(sp, rets, starts, months(t0, madd(Z, -1)))
        res = run(B['w'], rets)
        st = stats_block(res['gross'], res['net'], X.spy, A, Z, X.rf)
        wb = windows_block(res['gross'], res['net'], X.spy, A, Z)
        tb = turnover_block(res, node_of, A, Z)
        u = {'id': rid, 'family': fam, 'desc': ds, 'universe': un + '・etf_only', 'spec': sp,
             'N_range': [min(B['N'].values()), max(B['N'].values())], 'K_values': sorted(set(B['K'].values()))}
        u.update(st)
        u['windows_20y_10y'] = wb
        u['turnover_holdings_R8'] = tb
        u['after_cost_0_30_R6'] = {'full': C.excess_stats(net_with(res, COST_SENS), X.spy, A, Z),
                                   'hold_2007_on': C.excess_stats(net_with(res, COST_SENS), X.spy, C.HOLD_START, Z)}
        lb, lbx = lower_bound(res, X.spy, A, Z, H_LB)
        u['lower_bound'] = {'h_per_year': H_LB, 'stats': lb, 'unrounded_cagr_diff_pct': lbx['cagr_diff_pct'] if lbx else None}
        u['lower_bound_sensitivity_R12'] = {str(h): lower_bound(res, X.spy, A, Z, h)[0] for h in H_LB_SENS}
        u['recent_R10'] = {'gross': C.excess_stats(res['gross'], X.spy, C.RECENT_START, Z), 'net': C.excess_stats(res['net'], X.spy, C.RECENT_START, Z)}
        (a1, z1), (a2, z2) = halves(A, Z)
        u['vs_QQQ_R11'] = {'full': C.excess_stats(res['gross'], X.qqq, A, Z), 'first_half': C.excess_stats(res['gross'], X.qqq, a1, z1),
                           'second_half': C.excess_stats(res['gross'], X.qqq, a2, z2), 'from_2009_04': C.excess_stats(res['gross'], X.qqq, 200904, Z),
                           'net_full': C.excess_stats(res['net'], X.qqq, A, Z)}
        u['vs_French_Mkt'] = {'full': C.excess_stats(res['gross'], X.mkt, A, Z), 'net_full': C.excess_stats(res['net'], X.mkt, A, Z)}
        u['vs_REF_EW_menu'] = None
        # R5
        lz = min(Zlag, Z)
        resl = run({m: w for m, w in B['w'].items() if m <= lz}, {k: lagr.get(k, {}) for k in rets})
        u['lag1_R5'] = {'window': [A, lz], 'gross': C.excess_stats(resl['gross'], lag_spy, A, lz), 'net': C.excess_stats(resl['net'], lag_spy, A, lz),
                        'month_end_same_window_gross': C.excess_stats(res['gross'], X.spy, A, lz),
                        'missing_held_months': resl['missing'][:10], 'n_missing': len(resl['missing'])}
        # drop_top（費用前）
        if fam in ('P', 'E'):
            u['drop_top'] = drop_top_block(sp, X, rets, starts, A, Z, res, X.spy)
            # 紙の双子
            u['paper_twin_R1_ind49'] = paper_twin(sp, X, res['gross'], res['net'], A, Z, 'ind49', 'def')
            u['paper_twin_R1b_ind49_same_fraction'] = paper_twin(sp, X, res['gross'], res['net'], A, Z, 'ind49', 'frac', B)
            u['paper_twin_R2_ind30'] = paper_twin(sp, X, res['gross'], res['net'], A, Z, 'ind30', 'def')
        M[rid] = {'u': u, 'res': res, 'B': B}
    # REF_EW との差
    ew = M['REF_EW_menu']['res']
    for rid, x in M.items():
        if rid != 'REF_EW_menu':
            x['u']['vs_REF_EW_menu'] = {'gross': C.excess_stats(x['res']['gross'], ew['gross'], A, Z), 'net': C.excess_stats(x['res']['net'], ew['net'], A, Z)}
    # Holm と格付け
    holm = {}
    for fam in ('P', 'E'):
        ids = [rid for rid, x in M.items() if x['u']['family'] == fam]
        pv = {rid: (C.p_one(M[rid]['u']['full']['t']) if M[rid]['u']['months'] >= MIN_EVAL else 1.0) for rid in ids}
        holm[fam] = {'p_one': {k: round(v, 5) for k, v in pv.items()}, 'holm': C.holm(pv)}
        # 長い歴史の線（参考・保有期間の片側 p の Holm）
        ph = {rid: C.p_one(M[rid]['u']['hold_2007_on']['t']) for rid in ids}
        holm[fam]['hold_p_one_ref'] = {k: round(v, 5) for k, v in ph.items()}
        holm[fam]['hold_holm_ref'] = C.holm(ph)
    grades = {}
    for rid, x in M.items():
        u = x['u']
        if u['family'] not in ('P', 'E'):
            u['grade'] = 'not_graded（対照・報告）'
            continue
        fp = holm[u['family']]['holm'][rid]
        if u['months'] < MIN_EVAL:
            u['grade'] = 'NA_short'
        else:
            g, cr = grade_unit(u, u['drop_top'], u['lower_bound']['stats'], fp)
            u['grade'], u['criteria_short'] = g, cr
        u['holm_p_one'] = fp
        grades[rid] = u['grade']
        # 丸めで判定が変わるか（丸める前の差での判定）
        ur = u['unrounded']
        u['criteria_short_unrounded_check'] = {
            'halves': ur['gross_first_half']['cagr_diff_pct'] > 0 and ur['gross_second_half']['cagr_diff_pct'] > 0,
            'drop_top': u['drop_top']['unrounded_cagr_diff_pct'] > 0, 'cost': ur['net_full']['cagr_diff_pct'] > 0,
            'lower_bound': (u['lower_bound']['unrounded_cagr_diff_pct'] or -1) > 0,
            'positive': ur['gross_full']['ex_ann_pct'] > 0 and ur['gross_full']['cagr_diff_pct'] > 0}
        # 長い歴史の C1〜C8（参考・格付けに使わない）
        roll = u['windows_20y_10y']['roll20_gross']
        gl, cl = C.grade(u['full'], u['train_to_2006_12'], u['hold_2007_on'], roll, u['after_cost']['hold_2007_on'], None,
                         holm[u['family']]['hold_holm_ref'][rid], None, False)
        u['criteria_long_reference'] = {'grade_if_long_history_lines': gl, 'C': cl,
                                        'note': '参考のみ・格付けに使わない。訓練（2001-08〜2006-12・65か月）は15年に届かない（事前登録 criteria.which）。C4 は丸める前の差で勝ちを数えた転がる20年窓（費用前・6窓・重なる）。C5 は無し（紙の双子は R1 の報告）。C7 の Holm は保有期間の片側 p を族の中で。C8 は該当なし'}
    # ── 報告 ──
    reports = {}
    # R3 spliced
    rets_sp, starts_sp, node_sp = universe(X, 'spliced')
    t0s = first_formation(rets_sp, starts_sp, D.MIN_N)
    As = madd(t0s, 1)
    r3 = {}
    for rid, sp in D.RULES.items():
        B = build(sp, rets_sp, starts_sp, months(t0s, madd(Z, -1)))
        res = run(B['w'], rets_sp)
        B2 = build(sp, rets_sp, starts_sp, months(t0, madd(Z, -1)))
        res2 = run(B2['w'], rets_sp)
        r3[rid] = {'own_window': [As, Z], 'full': C.excess_stats(res['gross'], X.spy, As, Z), 'net_full': C.excess_stats(res['net'], X.spy, As, Z),
                   'hold_2007_on': C.excess_stats(res['gross'], X.spy, C.HOLD_START, Z),
                   'same_window_as_primary': C.excess_stats(res2['gross'], X.spy, A, Z),
                   'same_window_net': C.excess_stats(res2['net'], X.spy, A, Z),
                   'turnover_holdings': turnover_block(res, node_sp, As, Z)['share_of_months_held']}
    reports['R3_spliced'] = {'reps': X.reps['spliced'], 'eval_from': fmt(As), 'by_rule': r3}
    # R13 overlap dedup（SMH を落とす）
    dropped = X.data['universe']['dropped_by_overlap_R13_only']['etf_only']
    drop_t = [v['rep'] for v in dropped.values()]
    rets13, starts13, node13 = universe(X, 'etf_only', drop=tuple(drop_t))
    t013 = first_formation(rets13, starts13, D.MIN_N)
    r13 = {}
    for rid, sp in D.RULES.items():
        B = build(sp, rets13, starts13, months(t0, madd(Z, -1)))
        res = run(B['w'], rets13)
        (a1, z1), (a2, z2) = halves(A, Z)
        r13[rid] = {'full': C.excess_stats(res['gross'], X.spy, A, Z), 'first_half': C.excess_stats(res['gross'], X.spy, a1, z1),
                    'second_half': C.excess_stats(res['gross'], X.spy, a2, z2), 'net_full': C.excess_stats(res['net'], X.spy, A, Z)}
    reports['R13_overlap_dedup'] = {'dropped': dropped, 'first_formation_N_ge_10': fmt(t013), 'eval_window_used': [A, Z], 'by_rule': r13}
    # R16 NODE_MERGE を外す（RWR を EQREIT の代表に）
    rets16, starts16, node16 = universe(X, 'etf_only', extra={'EQREIT': 'RWR'})
    r16 = {}
    for rid, sp in D.RULES.items():
        B = build(sp, rets16, starts16, months(t0, madd(Z, -1)))
        res = run(B['w'], rets16)
        (a1, z1), (a2, z2) = halves(A, Z)
        r16[rid] = {'full': C.excess_stats(res['gross'], X.spy, A, Z), 'first_half': C.excess_stats(res['gross'], X.spy, a1, z1),
                    'second_half': C.excess_stats(res['gross'], X.spy, a2, z2), 'net_full': C.excess_stats(res['net'], X.spy, A, Z),
                    'share_months_RWR_held': round(sum(1 for m in months(A, Z) if res['weff'][m].get('RWR', 0) > 0) / len(months(A, Z)), 3)}
    reports['R16_node_merge_off'] = {'added': {'EQREIT': 'RWR'}, 'RWR_start': starts16['RWR'], 'by_rule': r16}
    # R15 U_narrow
    rets15, starts15, node15 = universe(X, 'etf_only', lambda n: not n.startswith('S_'))
    t015 = first_formation(rets15, starts15, 5)
    A15 = madd(t015, 1)
    r15 = {}
    for rid in ('P3_MG_6_6', 'P5_F3g_12_1_K30'):
        sp = D.RULES[rid]
        B = build(sp, rets15, starts15, months(t015, madd(Z, -1)))
        res = run(B['w'], rets15)
        r15[rid] = {'window': [A15, Z], 'months': len(months(A15, Z)), 'grade': 'NA_short（格付けしない・評価の月 < 180）',
                    'full': C.excess_stats(res['gross'], X.spy, A15, Z), 'net_full': C.excess_stats(res['net'], X.spy, A15, Z),
                    'K_values': sorted(set(B['K'].values())), 'N_values': sorted(set(B['N'].values()))}
    ewn = run(build({'kind': 'ew'}, rets15, starts15, months(t015, madd(Z, -1)))['w'], rets15)
    r15['REF_EW_narrow'] = {'full': C.excess_stats(ewn['gross'], X.spy, A15, Z)}
    reports['R15_narrow_only'] = {'first_formation_N_ge_5': fmt(t015), 'by_rule': r15}
    # R14 node の入り
    Bm = M['REF_EW_menu']['B']
    entry = {}
    for n, t in X.reps['etf_only'].items():
        ms = [m for m in months(199901, madd(Z, -1)) if t in D.eligible({t: rets_all[t]}, m, {t: starts_all[t]})]
        entry[n] = {'rep': t, 'first_formation_as_candidate': fmt(ms[0]) if ms else None}
    reports['R14_node_entry'] = {'entry': entry, 'N_by_formation_month': {fmt(t): n for t, n in sorted(Bm['N'].items())}}
    # R7 税
    r7 = {}
    tick_needed = sorted(set(rets_all) | {'SPY'})
    _, dy_fixed = implied_dy(X, tick_needed, A, Z)
    r7_reg = {}
    for rid in list(D.RULES) + ['REF_EW_menu']:
        W = M[rid]['B']['w']
        prod = 1e6 * math.prod(1 + M[rid]['res']['net'][m] for m in months(A, Z))
        rep, sim_pre_usd = tax_report(X, W, t0, Z, tick_needed)
        rep['r7_check_sim_over_adjclose_net_product'] = round(sim_pre_usd / prod, 4)
        r7[rid] = rep
        rep2, sim2 = tax_report(X, W, t0, Z, tick_needed, dy_mode='as_registered')
        rep2['r7_check_sim_over_adjclose_net_product'] = round(sim2 / prod, 4)
        r7_reg[rid] = {k: rep2[k] for k in ('jpy:carry3y:hold', 'jpy:carry3y:sell', 'jpy:no_carry:hold', 'jpy:no_carry:sell', 'r7_check_sim_over_adjclose_net_product')}
    spy_prod = 1e6 * math.prod(1 + X.spy[m] for m in months(A, Z))
    P_ = {k: price_index(X.cret[k]) for k in tick_needed}
    spy_sim = tax_sim({m: {'SPY': 1.0} for m in months(A, Z)}, t0, Z, P_, {k: X.dy.get(k, {}) for k in tick_needed}, {m: 1.0 for m in X.fx}, tax=0.0, wh=0.0, initial_cost=False)
    reports['R7_tax'] = {'by_rule': r7, 'spy_check_sim_over_adjclose_product': round(spy_sim['V_end_hold'] / spy_prod, 4),
                         'dividends_from_adjclose_for': dy_fixed,
                         'as_registered_dividends_version': r7_reg,
                         'dividend_note': '主の R7 は、配当の記録が欠けている器（OIH・PPH・RTH＝VanEck の旧 HOLDRS の3本。Yahoo の月足の events の配当が ETF になった 2012 年以降ほぼ無い〔OIH は 2025-12 の1件だけ〕のに、調整後終値には毎年の分配が入っている＝使う期間の『終値＋配当』の積が調整後の積より 14〜25% 小さい。他の器は ±1% 以内）の配当を、その期間だけ同じ Yahoo の調整後終値から max(0, 調整後−終値) で作った版。事前登録どおり抽出の配当をそのまま使う版（その3本の配当を 0 と読む＝ルール7に反する）は as_registered_dividends_version に並べた',
                         'model': pre['tax_report_R7']['model'],
                         'keys': 'jpy|usd : carry3y|no_carry : hold|sell（hold＝最後の含み益に課税しない・sell＝2026-08 に全部売る〔規則も SPY も〕）。ann_diff＝規則の年率−SPY の年率（最初の 100 万円・2001-07 末に買う）'}
    # R4 橋渡し（第7族の結果は測った後に読む → post_hoc に）
    reports['R4_bridge_family7'] = {rid: {'full': M[rid]['u']['full'], 'hold_2007_on': M[rid]['u']['hold_2007_on'], 'net_full': M[rid]['u']['after_cost']['full'],
                                          'net_hold_2007_on': M[rid]['u']['after_cost']['hold_2007_on']}
                                    for rid in ('REF_bridge_eknzbh_K3_R12', 'REF_bridge_eknzbh_K3_BL')}
    reports['R5_lag1'] = {'window_end': Zlag, 'daily_gaps_vs_spy_calendar': lag_gaps,
                          'by_rule': {rid: M[rid]['u']['lag1_R5'] for rid in M}}
    reports['R1_R1b_R2_paper_twins'] = {rid: {'R1': M[rid]['u']['paper_twin_R1_ind49']['gross']['full'], 'R1_net': M[rid]['u']['paper_twin_R1_ind49']['net']['full'],
                                              'R1b': M[rid]['u']['paper_twin_R1b_ind49_same_fraction']['gross']['full'],
                                              'R2': M[rid]['u']['paper_twin_R2_ind30']['gross']['full']}
                                        for rid in M if M[rid]['u']['family'] in ('P', 'E')}

    tested = [M[rid]['u'] for rid in M]
    obj = {
        'angle': 'nx_indmom_real', 'prereg': 'out/nx_indmom_real_prereg.json', 'global_prereg': 'out/nx_prereg.json',
        'frozen_verified': frozen, 'grade_function': 'nx_common.grade_short（事前登録 criteria.which = criteria_short_sample）。Holm は P1〜P5 の中・E1〜E5 の中で別々（片側 p＝nx_common.p_one(full t)）',
        'eval_window': [A, Z], 'eval_months': len(months(A, Z)), 'first_formation_N_ge_10': t0,
        'synthetic_checks': syn, 'data_checks': checks,
        'holm': holm, 'grades': grades, 'tested': tested, 'reports': reports,
    }
    return obj, M, X


# ───────────────────────── 事後の診断（結果を見た後・格付けに使わない） ─────────────────────────
MW_ETF_TACTICAL = os.path.join(C.CACHE, 'nx_indmom_real_R4_mw_etf_tactical_eknzbh.json')   # 測った後に git show で取った写し（gitignore）
MW_REF = 'origin/claude/market-winning-backtest-eknzbh:out/mw_etf_tactical.json'


def load_mw():
    if not os.path.exists(MW_ETF_TACTICAL):
        import subprocess
        b = subprocess.run(['git', '-C', C.BASE, 'show', MW_REF], capture_output=True, check=True).stdout
        open(MW_ETF_TACTICAL, 'wb').write(b)
    return json.load(open(MW_ETF_TACTICAL))


def ols_nw(y, cols, lag=12):
    import numpy as np
    Y = np.array(y)
    Xm = np.column_stack([np.ones(len(y))] + [np.array(c) for c in cols])
    b = np.linalg.lstsq(Xm, Y, rcond=None)[0]
    e = Y - Xm @ b
    u = Xm * e[:, None]
    Sm = u.T @ u
    for L in range(1, lag + 1):
        G = u[L:].T @ u[:-L]
        Sm += (1 - L / (lag + 1)) * (G + G.T)
    XtXi = np.linalg.inv(Xm.T @ Xm)
    V = XtXi @ Sm @ XtXi
    se = np.sqrt(np.diag(V))
    return [float(x) for x in b], [float(x) for x in b / se]


def year_excess(g, b, a, z):
    out = {}
    for y in range(a // 100, z // 100 + 1):
        ms = [m for m in months(max(a, y * 100 + 1), min(z, y * 100 + 12))]
        if not ms:
            continue
        rs = math.prod(1 + g[m] for m in ms) - 1
        rb = math.prod(1 + b[m] for m in ms) - 1
        out[str(y)] = {'rule_pct': round(rs * 100, 1), 'spy_pct': round(rb * 100, 1), 'diff_pt': round((rs - rb) * 100, 1), 'months': len(ms)}
    return out


def post_hoc(obj, M, X):
    A, Z = obj['eval_window']
    t0 = madd(A, -1)
    ph = {'label': '事後（結果を見た後に足した診断・格付けに使わない。事前登録の線・規則・母集団は変えていない）'}
    ff = C.ff_factors()
    mom = {k: v[0] / 100 for k, v in [x for x in C.french_tables('F-F_Momentum_Factor').values() if x['freq'] == 'monthly'][0]['data'].items() if v[0] is not None}
    per = {}
    for rid, x in M.items():
        g, n = x['res']['gross'], x['res']['net']
        ms = months(A, Z)
        d = {}
        d['calendar_year_excess_gross'] = year_excess(g, X.spy, A, Z)
        yrs = d['calendar_year_excess_gross']
        d['calendar_years_won'] = f"{sum(1 for v in yrs.values() if v['diff_pt'] > 0)}/{len(yrs)}"
        d['period_split_gross'] = {nm: C.excess_stats(g, X.spy, a, z) for nm, a, z in
                                   (('2001-08..2008-12', A, 200812), ('2009-01..2019-12', 200901, 201912), ('2020-01..2026-08', 202001, Z))}
        d['start_year_sensitivity_cagr_diff_gross'] = {str(y): (exact(g, X.spy, y * 100 + 1, Z) or {}).get('cagr_diff_pct') for y in range(2002, 2016)}
        d['start_year_sensitivity_cagr_diff_gross'] = {k: round(v, 2) for k, v in d['start_year_sensitivity_cagr_diff_gross'].items() if v is not None}
        # 5年の転がる窓（月ごと）の超過が正の割合
        r5 = []
        for i in range(0, len(ms) - 60 + 1):
            w = ms[i:i + 60]
            r5.append(C.cagr([g[m] for m in w]) - C.cagr([X.spy[m] for m in w]))
        d['rolling_5y_monthly_step_gross'] = {'windows': len(r5), 'share_positive': round(sum(1 for v in r5 if v > 0) / len(r5), 3),
                                              'min_pct': round(min(r5) * 100, 2), 'max_pct': round(max(r5) * 100, 2),
                                              'last_window_pct': round(r5[-1] * 100, 2)}
        # CAPM（SPY）と French 3因子＋勢い（UMD）の α（NW t・ラグ12）
        y1 = [g[m] - X.spy[m] for m in ms]
        b, t = ols_nw([g[m] - X.rf[m] for m in ms], [[X.spy[m] - X.rf[m] for m in ms]])
        d['capm_vs_spy'] = {'alpha_ann_pct': round(b[0] * 1200, 2), 'alpha_t': round(t[0], 2), 'beta': round(b[1], 3)}
        b, t = ols_nw([g[m] - ff['rf'][m] for m in ms], [[ff['mktrf'][m] for m in ms], [ff['smb'][m] for m in ms], [ff['hml'][m] for m in ms], [mom[m] for m in ms]])
        d['ff3_plus_umd'] = {'alpha_ann_pct': round(b[0] * 1200, 2), 'alpha_t': round(t[0], 2), 'b_mkt': round(b[1], 3), 'b_smb': round(b[2], 3),
                             'b_hml': round(b[3], 3), 'b_umd': round(b[4], 3), 't_umd': round(t[4], 2)}
        per[rid] = d
    ph['per_rule'] = per
    # 最も勝った暦年を抜く（その年の月を規則と SPY の両方から除く）
    for rid, x in M.items():
        g = x['res']['gross']
        yrs = per[rid]['calendar_year_excess_gross']
        by = max(yrs, key=lambda y: yrs[y]['diff_pt'])
        keep = [m for m in months(A, Z) if str(m // 100) != by]
        gg, bb = {m: g[m] for m in keep}, {m: X.spy[m] for m in keep}
        per[rid]['drop_best_calendar_year'] = {'year': by, 'diff_pt_that_year': yrs[by]['diff_pt'], 'stats_gross': C.excess_stats(gg, bb)}
    # A の二つの条件（片側 p<0.05 ∧ 前半・後半の幾何の超過が正）を、事前登録の外の変形にも当てる（事後・格付けに使わない）
    (a1, z1), (a2, z2) = halves(A, Z)
    lagr, _ = lag_returns(X, sorted(set(universe(X, 'etf_only')[0]) | {'SPY'}))
    lz = max(m for m in lagr['SPY'] if m <= Z)
    (la1, lz1), (la2, lz2) = halves(A, lz)

    def acrit(g, b, a, z, h1, h2):
        f = C.excess_stats(g, b, a, z)
        e1, e2 = C.excess_stats(g, b, *h1), C.excess_stats(g, b, *h2)
        po = C.p_one(f['t'])
        return {'cagr_diff': f['cagr_diff'], 't': f['t'], 'p_one': round(po, 4), 'first_half': e1['cagr_diff'], 'second_half': e2['cagr_diff'],
                'A_conditions_met': bool(po < 0.05 and e1['cagr_diff'] > 0 and e2['cagr_diff'] > 0)}
    rets_all, starts_all, _ = universe(X, 'etf_only')
    rets_sp, starts_sp, _ = universe(X, 'spliced')
    drop_t = [v['rep'] for v in X.data['universe']['dropped_by_overlap_R13_only']['etf_only'].values()]
    rets13, starts13, _ = universe(X, 'etf_only', drop=tuple(drop_t))
    rets16, starts16, _ = universe(X, 'etf_only', extra={'EQREIT': 'RWR'})
    var = {}
    for rid in D.RULES:
        x = M[rid]
        sp = D.RULES[rid]
        fm = months(t0, madd(Z, -1))
        v = {'registered_gross': acrit(x['res']['gross'], X.spy, A, Z, (a1, z1), (a2, z2)),
             'net_0_10': acrit(x['res']['net'], X.spy, A, Z, (a1, z1), (a2, z2)),
             'net_0_30': acrit(net_with(x['res'], COST_SENS), X.spy, A, Z, (a1, z1), (a2, z2))}
        rl = run({m: w for m, w in x['B']['w'].items() if m <= lz}, {k: lagr.get(k, {}) for k in rets_all})
        v['lag1_gross'] = acrit(rl['gross'], lagr['SPY'], A, lz, (la1, lz1), (la2, lz2))
        v['lag1_net_0_10'] = acrit(rl['net'], lagr['SPY'], A, lz, (la1, lz1), (la2, lz2))
        for nm, (rr, ss) in (('spliced_R3', (rets_sp, starts_sp)), ('no_SMH_R13', (rets13, starts13)), ('RWR_separate_R16', (rets16, starts16))):
            res = run(build(sp, rr, ss, fm)['w'], rr)
            v[nm] = acrit(res['gross'], X.spy, A, Z, (a1, z1), (a2, z2))
        v['vs_French_Mkt_gross'] = acrit(x['res']['gross'], X.mkt, A, Z, (a1, z1), (a2, z2))
        var[rid] = v
    ph['A_conditions_under_variants_P'] = {'note': 'A＝片側 p<0.05（調整なし）∧ 前半・後半の幾何の超過が正。登録の格付けは registered_gross だけ。他は事後の頑健さの点検（格付けに使わない）。lag1 は 2001-08〜2026-07 を二分',
                                           'by_rule': var}
    # E（11セクター）を 11セクターの等分と比べる
    rets_sec, starts_sec, _ = universe(X, 'etf_only', lambda n: n.startswith('S_'))
    ews = run(build({'kind': 'ew'}, rets_sec, starts_sec, months(t0, madd(Z, -1)))['w'], rets_sec)
    ph['E_vs_EW_sector'] = {'EW_sector_vs_SPY': C.excess_stats(ews['gross'], X.spy, A, Z),
                            'by_rule': {rid: C.excess_stats(M[rid]['res']['gross'], ews['gross'], A, Z) for rid in M if M[rid]['u']['family'] == 'E'}}
    # 上位2本の寄与を抜く（drop_top の二段）
    rets_all, starts_all, _ = universe(X, 'etf_only')
    dt2 = {}
    for rid, x in M.items():
        if x['u']['family'] != 'P':
            continue
        con = x['u']['drop_top']['contributions_pct_sum']
        top2 = list(con)[:2]
        r2 = {k: v for k, v in rets_all.items() if k not in top2}
        s2 = {k: v for k, v in starts_all.items() if k not in top2}
        res2 = run(build(D.RULES[rid], r2, s2, months(t0, madd(Z, -1)))['w'], r2)
        dt2[rid] = {'dropped': top2, 'stats_gross': C.excess_stats(res2['gross'], X.spy, A, Z), 'first_half': C.excess_stats(res2['gross'], X.spy, *halves(A, Z)[0]),
                    'second_half': C.excess_stats(res2['gross'], X.spy, *halves(A, Z)[1])}
    ph['drop_top2_P'] = dt2
    # 最後の持ち物（2026-08 に持った器・2026-09 に持つ器）
    ph['last_holdings'] = {rid: {'held_2026_08': sorted(x['res']['weff'][Z]), 'picks_formed_2026_07': x['B']['picks'].get(madd(Z, -1))} for rid, x in M.items()}
    # R4: eknzbh 第7族の結果（測った後に読んだ）
    r4 = {'read_after_measuring': True, 'source': 'git show origin/claude/market-winning-backtest-eknzbh:out/mw_etf_tactical.json（2026-09-29 に取得）'}
    try:
        mw = load_mw()
        for x in mw['tested']:
            if x['id'] in ('K1_RAKU_K3_R12', 'K2_RAKU_K6_R12', 'K3_RAKU_K3_BL', 'K4_RAKU_K6_BL', 'K5_RAKU_EW'):
                r4[x['id']] = {'grade_eknzbh': x.get('grade'), 'desc': x.get('description'), 'start': x.get('start'),
                               'vs_french_mkt_full': {k: x['full'][k] for k in ('cagr_diff', 't', 'vol_s')},
                               'vs_spy_full': {k: x['vs_spy_full'][k] for k in ('cagr_diff', 't', 'vol_s')},
                               'vs_spy_hold': {k: x['vs_spy_hold'][k] for k in ('cagr_diff', 't')},
                               'cost_hold_vs_mkt': {k: x['cost_hold'][k] for k in ('cagr_diff', 't')},
                               'maxdd': x.get('maxdd'), 'turnover_oneway_ann': x.get('turnover_oneway_ann'), 'tax_jp_hold': x.get('tax_jp_hold')}
    except Exception as e:  # noqa
        r4['error'] = str(e)
    # 窓をそろえる（検査役の指摘 2026-09-29）: eknzbh 第7族の full は 2002-12〜2026-08（start の月から end まで）。
    # この角度の full は 2001-08〜2026-08 なので、そのまま並べると窓の違いが差に混ざる。比べる値は eknzbh の窓で計算し直し、
    # 登録の窓（2001-08〜）の値は別の欄に残す。保有期間（2007-01〜）はもともと同じ窓。
    ks = [r4[k] for k in ('K1_RAKU_K3_R12', 'K2_RAKU_K6_R12', 'K3_RAKU_K3_BL', 'K4_RAKU_K6_BL', 'K5_RAKU_EW') if k in r4]
    ek_a = max(x['start'] for x in ks) if ks else A
    if ks and len({x['start'] for x in ks}) != 1:
        raise SystemExit(f"R4: eknzbh 第7族の start が族の中でそろっていない {[x['start'] for x in ks]} → 止まる")
    ek_z = Z
    try:
        ek_z = min(Z, max(x['end'] for x in mw['tested'] if x['id'] in ('K1_RAKU_K3_R12', 'K2_RAKU_K6_R12', 'K3_RAKU_K3_BL', 'K4_RAKU_K6_BL', 'K5_RAKU_EW')))
    except Exception:  # noqa
        pass
    r4['comparison_window'] = {'eknzbh_family7_full': [ek_a, ek_z], 'this_angle_registered_full': [A, Z], 'hold': [C.HOLD_START, Z],
                               'note': '比べるのは同じ窓どうし（same_window_as_eknzbh）。registered_window_2001_08_on は登録の窓の値で、eknzbh とは窓が違う（並べて大きさを比べない）'}
    same = {}
    for rid in ('REF_bridge_eknzbh_K3_R12', 'REF_bridge_eknzbh_K3_BL', 'REF_EW_menu'):
        u, res = M[rid]['u'], M[rid]['res']
        tb_same = turnover_block(res, {}, ek_a, ek_z)
        same[rid] = {
            'same_window_as_eknzbh': {'window': [ek_a, ek_z],
                                      'vs_spy_full': {k: C.excess_stats(res['gross'], X.spy, ek_a, ek_z)[k] for k in ('cagr_diff', 't', 'vol_s')},
                                      'vs_french_mkt_full': {k: C.excess_stats(res['gross'], X.mkt, ek_a, ek_z)[k] for k in ('cagr_diff', 't', 'vol_s')},
                                      'maxdd': round(C.maxdd(C.window(res['gross'], ek_a, ek_z)) * 100, 1),
                                      'turnover_oneway_ann': tb_same['annual_oneway_turnover_excl_first']},
            'vs_spy_hold': {k: u['hold_2007_on'][k] for k in ('cagr_diff', 't')},
            'registered_window_2001_08_on': {'window': [A, Z],
                                             'vs_spy_full': {k: u['full'][k] for k in ('cagr_diff', 't', 'vol_s')},
                                             'maxdd': u['maxdd_pct']['rule_gross'],
                                             'turnover_oneway_ann': u['turnover_holdings_R8']['annual_oneway_turnover_excl_first']},
        }
    r4['this_angle_same_shape'] = same
    pairs = (('K1_RAKU_K3_R12', 'REF_bridge_eknzbh_K3_R12'), ('K3_RAKU_K3_BL', 'REF_bridge_eknzbh_K3_BL'), ('K5_RAKU_EW', 'REF_EW_menu'))
    r4['same_window_gap_this_minus_eknzbh'] = {
        f'{rid}−{k}': {'vs_spy_full_cagr_diff_pt': round(same[rid]['same_window_as_eknzbh']['vs_spy_full']['cagr_diff'] - r4[k]['vs_spy_full']['cagr_diff'], 2),
                       'vs_spy_hold_cagr_diff_pt': round(same[rid]['vs_spy_hold']['cagr_diff'] - r4[k]['vs_spy_hold']['cagr_diff'], 2),
                       'same_sign_full': (same[rid]['same_window_as_eknzbh']['vs_spy_full']['cagr_diff'] > 0) == (r4[k]['vs_spy_full']['cagr_diff'] > 0),
                       'same_sign_hold': (same[rid]['vs_spy_hold']['cagr_diff'] > 0) == (r4[k]['vs_spy_hold']['cagr_diff'] > 0)}
        for k, rid in pairs if k in r4}
    ph['R4_family7_comparison'] = r4
    return ph


def finalize(obj, M, X):
    T = {u['id']: u for u in obj['tested']}
    P = [u for u in obj['tested'] if u['family'] == 'P']
    E = [u for u in obj['tested'] if u['family'] == 'E']
    obj['deviations_from_prereg'] = [
        {'what': 'R7（税）の配当: OIH・PPH・RTH', 'prereg': 'tax_report_R7.model『配当: 米国の源泉 10% の後に 20.315%…』（配当は抽出の Yahoo の配当の記録から）',
         'done': '抽出（Yahoo の月足の events）の配当が、使う期間（ETF になった 2012-01 以降）にほぼ無い3本（OIH・PPH・RTH＝VanEck の旧 HOLDRS。OIH は 2025-12 の1件だけ）は、調整後終値には分配が入っていて（使う期間の終値＋配当の積が調整後の積より 14〜25% 小さい・他の器は ±1% 以内）、記録の欠けを 0 と読むとルール7に反する。この3本だけ同じ Yahoo の調整後終値から max(0, 調整後の月次 − 終値の月次) を月の配当利回りとした。事前登録どおりの版（3本の配当 0）も reports.R7_tax.as_registered_dividends_version に並べた',
         'affects_grade': 'なし（R7 は報告のみ）'},
        {'what': 'R5（1営業日遅れ）の最後の月', 'prereg': 'timing.realistic_execution『t+1 月の最初の営業日の引け → t+2 月の最初の営業日の引け』',
         'done': '凍結した抽出の日足は 2026-08-31 で切れていて 2026-09 の最初の営業日が無い＝持つ月 2026-08 の区間を作れない。R5 は 2001-08〜2026-07（300か月）で、同じ窓の月末の約定と並べた',
         'affects_grade': 'なし（R5 は報告のみ）'},
    ]
    obj['implementation_notes'] = [
        'P3（MG 6-6）の組は評価の最初の形成の月 2001-07 から作る（それより前の月は候補が9本＝評価の始まりの条件の前）。2001-08 は1組、2002-01 から6組（事前登録『組がそろうまでは既にある組で等分』の読み）',
        'drop_top は寄与の最大の器を母集団から全期間除き、同じ評価の月（2001-08〜2026-08）で作り直す。除いた器が早い時期の候補だと 2001-07 の候補が9本になる月があるが、評価の月は動かさずそのまま組む（E の XLE・XLK がこれに当たる）',
        '回転は ½Σ|新しい重み − 前月の重みを当月のリターンで流した重み|、最初の月は 1（SPY には最初の買いの費用を引かない）。費用は その月の回転 × 0.10%（R6 は 0.30%）を月のリターンから引く',
        '紙の双子（R1・R2）: 月の差 g_t =（実物_t − SPY_t）−（紙_t − French Mkt_t）。幾何の差は（実物の年率 − SPY の年率）−（紙の年率 − Mkt の年率）。紙の候補も同じ13か月の条件（French は 1998-01 から全業種がそろう）。R1b の紙の K は max(2, floor(49·K実物/N実物 + 0.5))',
        '20年窓は nx_common.rolling と同じ窓（毎年7月起点・97% 以上の月）で、勝ちは丸める前の差で数えた（rolling_exact）。評価が 2001-08 から始まるので、2001-07 起点の窓は 239か月（97% の条件で入る）。nx_common の丸めた数え方も併記',
        'R7 の模擬: 取得価額は移動平均（円）・年の中は通算して源泉徴収（損が出たら戻す）・年をまたぐ損の3年繰越は12月末の入れ替えのときに相殺して戻す（実際は翌年2〜3月の申告）・最後の年（2026年1〜8月）の実現損益にも繰越を当てる・配当はその月末に同じ器へ買い足す（調整後終値は権利落ち日に再投資）・売買の費用は 売り額 × 0.10%（最初の買いも・SPY の最初の買いには引かない）・sell は規則も SPY も 2026-08 に全部売る（0.10% の費用も）・配当と売却損の通算はしない（事前登録のとおり）・税は口座の中から払う',
        'シャープは French RF（月次）で。C8（重ねる・借入・時期選び）は該当なし＝報告のみ',
        '長い歴史の線 C1〜C8 は参考（criteria_long_reference）。訓練が 2001-08〜2006-12 の65か月で15年に届かないので格付けには使わない',
    ]
    pr = obj['holm']['P']['p_one']
    obj['prediction_check'] = {
        'prereg': '主の5本の費用前の超過は 0〜+2%/年、NW t は 1.65 に届かず、A は多くて1本・S は0本。紙との差は −1〜−4%/年。QQQ には 2009年以降の多くの窓で負ける。税引後は税引前より年 0.5〜1.5% 悪い。1日遅れの影響は年 ±0.5% 以内',
        'result': {
            'excess_gross_full_cagr_diff': {u['id']: u['full']['cagr_diff'] for u in P},
            'nw_t_full': {u['id']: u['full']['t'] for u in P},
            'grades': {u['id']: u['grade'] for u in P},
            'paper_gap_geo': {u['id']: u['paper_twin_R1_ind49']['gross']['full']['geo_gap_pct'] for u in P},
            'vs_QQQ_from_2009_04': {u['id']: u['vs_QQQ_R11']['from_2009_04']['cagr_diff'] for u in P},
            'tax_drag_on_diff_jpy_carry_hold': {rid: obj['reports']['R7_tax']['by_rule'][rid]['jpy:carry3y:hold']['tax_drag_on_diff_pct'] for rid in D.RULES},
            'lag1_minus_monthend_same_window': {u['id']: round(u['lag1_R5']['gross']['cagr_diff'] - u['lag1_R5']['month_end_same_window_gross']['cagr_diff'], 2) for u in P},
        },
        'verdict': None,
    }
    res_ = obj['prediction_check']['result']
    ex = list(res_['excess_gross_full_cagr_diff'].values()); ts = list(res_['nw_t_full'].values())
    nA = sum(1 for g in res_['grades'].values() if g == 'A'); nS = sum(1 for g in res_['grades'].values() if g == 'S')
    npo = sum(1 for rid in res_['nw_t_full'] if obj['holm']['P']['p_one'][rid] < 0.05)
    gaps = list(res_['paper_gap_geo'].values()); qq = list(res_['vs_QQQ_from_2009_04'].values())
    drags = [obj['reports']['R7_tax']['by_rule'][rid][k]['tax_drag_on_diff_pct'] for rid in D.RULES for k in ('jpy:carry3y:hold', 'jpy:carry3y:sell', 'jpy:no_carry:hold', 'jpy:no_carry:sell')]
    lags = list(res_['lag1_minus_monthend_same_window'].values())
    obj['prediction_check']['verdict'] = (
        f"費用前の超過は {min(ex):+.2f}〜{max(ex):+.2f}%/年（予想 0〜+2 より上）、NW t は {min(ts)}〜{max(ts)} で片側 p<0.05 が {npo}本（予想: 届かない）、"
        f"A は {nA}本（予想: 多くて1本）・S は {nS}本（予想どおり0＝Holm を通らない）。紙との差は {min(gaps):+.2f}〜{max(gaps):+.2f}%/年（予想 −1〜−4 より小さい）。"
        f"QQQ には 2009-04 以降 {min(qq):+.2f}〜{max(qq):+.2f}%/年で全部負け（予想どおり）。税の引きずり（円・4つの型）は {min(drags):.2f}〜{max(drags):.2f}%/年（予想 0.5〜1.5 より大きい）。"
        f"1日遅れの約定の影響は {min(lags):+.2f}〜{max(lags):+.2f}%/年（予想 ±0.5 を {'超える規則がある' if min(lags) < -0.5 or max(lags) > 0.5 else '超えない'}）")
    # 最良
    best = max(P, key=lambda u: (u['grade'] == 'A', u['full']['t']))
    obj['best'] = (f"{best['id']}（格付け {best['grade']}・短い標本の線）: 楽天で買える業種 ETF 20本（1業種1本）で12か月（t−11〜t）の上位5本を毎月等分。"
                   f"2001-08〜2026-08 に SPY（配当込み）へ 年率差 {best['full']['cagr_diff']:+.2f}%（算術 {best['full']['ex_ann']:+.2f}・NW t {best['full']['t']}・片側 p {obj['holm']['P']['p_one'][best['id']]}）、"
                   f"前半 {best['first_half']['cagr_diff']:+.2f}・後半 {best['second_half']['cagr_diff']:+.2f}、費用後 {best['after_cost']['full']['cagr_diff']:+.2f}、"
                   f"最大寄与 {best['drop_top']['dropped']} を抜いて {best['drop_top']['stats_gross']['cagr_diff']:+.2f}、下限版 {best['lower_bound']['stats']['cagr_diff']:+.2f}。"
                   f"Holm（5本）後 p {obj['holm']['P']['holm'][best['id']]} で S には届かない。2007年以降は {best['hold_2007_on']['cagr_diff']:+.2f}（t {best['hold_2007_on']['t']}）")
    # 要約（数字はこの JSON の値をそのまま）
    ph = obj['post_hoc_diagnostics']
    p2 = T['P2_G3_12_0_top5']
    pr_ = ph['per_rule']['P2_G3_12_0_top5']
    tax = obj['reports']['R7_tax']['by_rule']
    r4 = ph['R4_family7_comparison']
    br = T['REF_bridge_eknzbh_K3_R12']
    gP = obj['grades']
    vn = {'net_0_10': '費用0.10%', 'net_0_30': '費用0.30%', 'lag1_gross': '1日遅れ', 'lag1_net_0_10': '1日遅れ＋費用', 'spliced_R3': 'HOLDRS つなぎ',
          'no_SMH_R13': 'SMH 除外', 'RWR_separate_R16': 'REIT 別 node', 'vs_French_Mkt_gross': 'French Mkt 相手'}
    parts = []
    for rid in ('P2_G3_12_0_top5', 'P3_MG_6_6', 'P4_P9_multi_top5'):
        v = ph['A_conditions_under_variants_P']['by_rule'][rid]
        keep = [vn[k] for k in vn if v[k]['A_conditions_met']]
        lost = [vn[k] for k in vn if not v[k]['A_conditions_met']]
        parts.append(f"{rid.split('_')[0]} は残る: {'・'.join(keep) or 'なし'}／崩れる: {'・'.join(lost) or 'なし'}")
    rob = '事後の頑健さ（格付けに使わない）: A の二条件（片側 p<0.05・前半後半とも正）を事前登録の外の変形に当てた。' + '。'.join(parts)
    # R4 は eknzbh の窓（2002-12〜）にそろえた値で並べる（登録の窓 2001-08〜 の値は JSON の registered_window_2001_08_on）
    sw = r4['this_angle_same_shape']
    k1, k3 = r4['K1_RAKU_K3_R12'], r4['K3_RAKU_K3_BL']
    b12, bbl = sw['REF_bridge_eknzbh_K3_R12'], sw['REF_bridge_eknzbh_K3_BL']
    w_ = b12['same_window_as_eknzbh']['window']
    d12 = b12['same_window_as_eknzbh']['vs_spy_full']['cagr_diff'] - k1['vs_spy_full']['cagr_diff']
    dbl = bbl['same_window_as_eknzbh']['vs_spy_full']['cagr_diff'] - k3['vs_spy_full']['cagr_diff']
    dh = b12['vs_spy_hold']['cagr_diff'] - k1['vs_spy_hold']['cagr_diff']
    sgn = all(v['same_sign_full'] for v in r4['same_window_gap_this_minus_eknzbh'].values())

    def hl(d):
        return f"{abs(d):.2f}pt {'低い' if d < 0 else '高い'}"
    r4line = (f"R4（eknzbh 第7族・測った後に読んだ・窓を eknzbh の {fmt(w_[0])}〜{fmt(w_[1])} にそろえた）: 楽天の業種・テーマ 101本で12か月上位3（K1）は SPY に "
              f"{k1['vs_spy_full']['cagr_diff']:+.2f}（t {k1['vs_spy_full']['t']}・ボラ {k1['vs_spy_full']['vol_s']}%）、同じ形をこの20本で（REF_bridge_K3_R12）"
              f"{b12['same_window_as_eknzbh']['vs_spy_full']['cagr_diff']:+.2f}（t {b12['same_window_as_eknzbh']['vs_spy_full']['t']}・ボラ {b12['same_window_as_eknzbh']['vs_spy_full']['vol_s']}%）。"
              f"(r1+r3+r6+r12)/4 の上位3（K3）は {k3['vs_spy_full']['cagr_diff']:+.2f}（t {k3['vs_spy_full']['t']}）、この20本で {bbl['same_window_as_eknzbh']['vs_spy_full']['cagr_diff']:+.2f}（t {bbl['same_window_as_eknzbh']['vs_spy_full']['t']}）。"
              f"＝{'向きは同じ（どちらも正）' if sgn else '向きが割れる'}だが大きさはそろわない（こちらが K1 型は {hl(d12)}・BL 型は {hl(dbl)}）。"
              f"2007年以降（もともと同じ窓）は K1 {k1['vs_spy_hold']['cagr_diff']:+.2f}（t {k1['vs_spy_hold']['t']}）対 この20本 {b12['vs_spy_hold']['cagr_diff']:+.2f}（t {b12['vs_spy_hold']['t']}）＝{hl(dh)}。"
              f"値動きはテーマ・重複を外した分だけ半分近くに落ちた（登録の窓 2001-08〜 の値を並べて『同じ大きさ』と書いた初版は窓の違いから来た一致で、訂正した）")
    lines = [
        f"格付け（短い標本の線・Holm は主5本の中）: 主 P1 {gP['P1_G3_12_1_top5']}・P2 {gP['P2_G3_12_0_top5']}・P3 {gP['P3_MG_6_6']}・P4 {gP['P4_P9_multi_top5']}・P5 {gP['P5_F3g_12_1_K30']}。"
        f"S は0本（Holm 後の片側 p は {min(obj['holm']['P']['holm'].values())}〜{max(obj['holm']['P']['holm'].values())}）。探索（11セクターの器だけ）E1〜E5 は全部 {sorted(set(gP[u['id']] for u in E))}（後半がすべて負・t≤{max(u['full']['t'] for u in E)}）",
        f"最良 P2（12か月＝t−11〜t の上位5本・毎月等分・20本の業種 ETF）: 2001-08〜2026-08 に SPY へ 年率差 {p2['full']['cagr_diff']:+.2f}%（NW t {p2['full']['t']}）、前半 {p2['first_half']['cagr_diff']:+.2f}・後半 {p2['second_half']['cagr_diff']:+.2f}、"
        f"費用後 {p2['after_cost']['full']['cagr_diff']:+.2f}（片道0.30%なら {p2['after_cost_0_30_R6']['full']['cagr_diff']:+.2f}）、下限版 {p2['lower_bound']['stats']['cagr_diff']:+.2f}、SMH を抜いて {p2['drop_top']['stats_gross']['cagr_diff']:+.2f}。"
        f"2007年以降 {p2['hold_2007_on']['cagr_diff']:+.2f}（t {p2['hold_2007_on']['t']}）・2013-07以降 {p2['recent_2013_07_on']['cagr_diff']:+.2f}（t {p2['recent_2013_07_on']['t']}）。シャープ {p2['sharpe']['full']['rule_gross']} 対 SPY {p2['sharpe']['full']['bench']}・最大下落 {p2['maxdd_pct']['rule_gross']}% 対 {p2['maxdd_pct']['bench']}%",
        f"勝ちの中身（事後）: P2 の超過は 2001-08〜2008-12 に {pr_['period_split_gross']['2001-08..2008-12']['cagr_diff']:+.2f}（t {pr_['period_split_gross']['2001-08..2008-12']['t']}）、2009〜2019 は {pr_['period_split_gross']['2009-01..2019-12']['cagr_diff']:+.2f}、2020〜2026-08 は {pr_['period_split_gross']['2020-01..2026-08']['cagr_diff']:+.2f}（t {pr_['period_split_gross']['2020-01..2026-08']['t']}）。"
        f"最も勝った {pr_['drop_best_calendar_year']['year']} 年（{pr_['drop_best_calendar_year']['diff_pt_that_year']:+.1f}pt・エネルギー）を抜くと {pr_['drop_best_calendar_year']['stats_gross']['cagr_diff']:+.2f}（t {pr_['drop_best_calendar_year']['stats_gross']['t']}）。"
        f"上位2本（{'・'.join(ph['drop_top2_P']['P2_G3_12_0_top5']['dropped'])}）を抜くと {ph['drop_top2_P']['P2_G3_12_0_top5']['stats_gross']['cagr_diff']:+.2f}・後半 {ph['drop_top2_P']['P2_G3_12_0_top5']['second_half']['cagr_diff']:+.2f}。"
        f"French 3因子＋勢いで α {pr_['ff3_plus_umd']['alpha_ann_pct']:+.2f}%/年（t {pr_['ff3_plus_umd']['alpha_t']}・勢いの係数 {pr_['ff3_plus_umd']['b_umd']}）。暦年で SPY に勝った年 {pr_['calendar_years_won']}",
        f"紙との差（R1・French 49・同じ月・同じ規則）: 実物−紙の幾何の差は P1 {T['P1_G3_12_1_top5']['paper_twin_R1_ind49']['gross']['full']['geo_gap_pct']:+.2f}・P2 {p2['paper_twin_R1_ind49']['gross']['full']['geo_gap_pct']:+.2f}・P3 {T['P3_MG_6_6']['paper_twin_R1_ind49']['gross']['full']['geo_gap_pct']:+.2f}・P4 {T['P4_P9_multi_top5']['paper_twin_R1_ind49']['gross']['full']['geo_gap_pct']:+.2f}・P5 {T['P5_F3g_12_1_K30']['paper_twin_R1_ind49']['gross']['full']['geo_gap_pct']:+.2f}%/年（紙そのものは Mkt に +2.7〜+4.1・t 1.5〜1.8）。"
        f"実物に移した目減りは予想（−1〜−4）より小さい。同じ規則を11セクターの器だけで回すと（E）年 {min(u['full']['cagr_diff'] for u in E):+.2f}〜{max(u['full']['cagr_diff'] for u in E):+.2f} に落ちる＝細かい業種の器9本が効いている",
        r4line,
        f"課税口座（R7・円・損の3年繰越・最初の100万円・2001-07末）: P2 は税引前 {tax['P2_G3_12_0_top5']['jpy:carry3y:sell']['ann_diff_pre_tax_pct']:+.2f}%/年 → 税引後 {tax['P2_G3_12_0_top5']['jpy:carry3y:sell']['ann_diff_after_tax_pct']:+.2f}（両方 2026-08 に全部売る）／"
        f"{tax['P2_G3_12_0_top5']['jpy:carry3y:hold']['ann_diff_after_tax_pct']:+.2f}（SPY を売らずに持ち続ける）。P1・P4・P5 は SPY を持ち続ける比較で税引後 {tax['P1_G3_12_1_top5']['jpy:carry3y:hold']['ann_diff_after_tax_pct']:+.2f}・{tax['P4_P9_multi_top5']['jpy:carry3y:hold']['ann_diff_after_tax_pct']:+.2f}・{tax['P5_F3g_12_1_K30']['jpy:carry3y:hold']['ann_diff_after_tax_pct']:+.2f}（負け）。"
        f"毎月の入れ替えは年に評価額の約 {tax['P2_G3_12_0_top5']['nisa']['median_annual_buys_over_value']:.1f} 倍を買う＝NISA の年240万円の枠で回せる評価額は約 {tax['P2_G3_12_0_top5']['nisa']['implied_max_portfolio_jpy_in_2_4M_frame_median'] / 1e4:.0f} 万円まで",
        f"現実の約定（R5・翌月の最初の営業日）: P2 {p2['lag1_R5']['gross']['cagr_diff']:+.2f}（t {p2['lag1_R5']['gross']['t']}）・P3 {T['P3_MG_6_6']['lag1_R5']['gross']['cagr_diff']:+.2f}・P4 {T['P4_P9_multi_top5']['lag1_R5']['gross']['cagr_diff']:+.2f}（同じ窓の月末の約定との差は主5本で {min(lags):+.2f}〜{max(lags):+.2f}pt）。QQQ には 2009-04 以降すべての規則が負け（{min(u['vs_QQQ_R11']['from_2009_04']['cagr_diff'] for u in P):+.2f}〜{max(u['vs_QQQ_R11']['from_2009_04']['cagr_diff'] for u in P):+.2f}%/年）",
        rob,
        "限界: 母集団は楽天の今日の品ぞろえ（生き残り・人気の後知恵）で、独立の試行は25年の1本。勝ちの大半は 2001〜2008（エネルギー・素材・新興国の時代）と 2022（エネルギー）に集まり、2009〜2019 はほぼ0。Holm を通らず S に届かない。門・配分には入れていない",
    ]
    # 検査役の指摘を直した記録（前の数字は初版の out/nx_indmom_real.json・2026-09-29 02:57 の値）
    swf = {rid: v['same_window_as_eknzbh'] for rid, v in r4['this_angle_same_shape'].items()}
    obj['fixes'] = [{
        'date': '2026-09-29',
        'reported_by': '検査役（事前登録との一致と先読み・nx_indmom_real）',
        'what': 'R4（eknzbh 第7族との橋渡し）で比べる二つの窓が違っていた。eknzbh の K1〜K5 の full は 2002-12〜2026-08（285か月）、'
                'この角度の this_angle_same_shape は登録の窓 2001-08〜2026-08（301か月）の値だった。違う窓を並べて要約に『同じ向き・同じ大きさ』と書いていた',
        'verified': True,
        'how_verified': 'eknzbh の mw_etf_tactical.json の K1_RAKU_K3_R12 は start 200212・end 202608・months 285・full.from 200212（読み直して確認）。'
                        'この角度の値は M[rid]["u"]["full"]＝stats_block の (A, Z)＝(200108, 202608)。保有期間（2007-01〜）はどちらも同じ窓',
        'fix': 'this_angle_same_shape の比べる値を eknzbh の start〜end（2002-12〜2026-08）で計算し直した（SPY 相手・French Mkt 相手・最大下落・年の片道の回転）。'
               '登録の窓の値は registered_window_2001_08_on に残した。same_window_gap_this_minus_eknzbh（こちら − eknzbh の差と符号の一致）を足した。'
               '要約の『同じ大きさ』を『向きは同じ・大きさはそろわない』に改めた',
        'before': {'window': [200108, 202608],
                   'REF_bridge_eknzbh_K3_R12': {'vs_spy_full': {'cagr_diff': 3.31, 't': 1.52, 'vol_s': 17.4}, 'maxdd': -38.9, 'turnover_oneway_ann': 3.027},
                   'REF_bridge_eknzbh_K3_BL': {'vs_spy_full': {'cagr_diff': 3.4, 't': 2.0, 'vol_s': 17.3}, 'maxdd': -46.0, 'turnover_oneway_ann': 4.172},
                   'REF_EW_menu': {'vs_spy_full': {'cagr_diff': 0.07, 't': 0.17, 'vol_s': 15.3}, 'maxdd': -48.7, 'turnover_oneway_ann': 0.188},
                   'summary_line': 'R4（eknzbh 第7族・測った後に読んだ）: 楽天の業種・テーマ 101本で12か月上位3（K1）は SPY に +3.52（t 1.79・ボラ 31.1%）。'
                                   '同じ形をこの20本で（REF_bridge_K3_R12）+3.31（t 1.52・ボラ 17.4%）＝同じ向き・同じ大きさで、テーマ・重複を外した分だけ値動きが半分近くに落ちた'},
        'after': {'window': swf['REF_bridge_eknzbh_K3_R12']['window'],
                  **{rid: {k: v[k] for k in ('vs_spy_full', 'maxdd', 'turnover_oneway_ann')} for rid, v in swf.items()},
                  'gap_this_minus_eknzbh': r4['same_window_gap_this_minus_eknzbh'],
                  'summary_line': r4line},
        'affects_grade': 'なし（R4 は報告のみ・REF は格付けしない）。格付け・Holm・主の数字は不変',
        'prereg_rule_changed': False,
    }]
    obj['summary_lines'] = lines
    obj['summary_ja'] = '\n'.join(lines)
    return obj


if __name__ == '__main__':
    obj, M, X = main()
    obj['post_hoc_diagnostics'] = post_hoc(obj, M, X)
    obj = finalize(obj, M, X)
    p = C.save(OUTNAME, obj)
    log('書いた', p)
    for u in obj['tested']:
        f = u['full']
        print(f"{u['id']:34s} {u['grade']:8s} full ex {f['ex_ann']:6.2f} t {f['t']:5.2f} geo {f['cagr_diff']:6.2f} | "
              f"h1 {u['first_half']['cagr_diff']:6.2f} h2 {u['second_half']['cagr_diff']:6.2f} | net {u['after_cost']['full']['cagr_diff']:6.2f}")
