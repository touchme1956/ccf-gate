#!/usr/bin/env python3
"""night/mw_inside_tech.py — 角度 inside_tech（読むだけ・門の判定には不使用）

問い: NASDAQ100＋SMH というハイテク・半導体の賭けを手放さずに、その『中で』選び方（勢い・割安・割安＋勢い・等分）を
      変えると、時価加重のハイテクの塊そのものに勝てるか。楽天で買える器はその上乗せを取れているか。

事前登録: out/mw_inside_tech_prereg.json（測る前にコミット）。線は out/mw_prereg.json（C1〜C8）を mw_common.grade で当てる。

族
  L（主・格付け・Holm）: French 49 の {Chips, Hardw, Softw, LabEq} の中で、12-1 勢い／割安（Sum BE/Sum ME）／順位の和 の
                        上位1・上位2（時価加重）と、業種の等分。相手は時価加重の塊。C5 は別の3つの業種の塊で同じ規則
  S（報告）: SEC XBRL パネル 2010〜 の FF12 BusEq の中で 割安(E/P,B/P)・勢い・粗利 の上位1/3（巨大6社あり/なし）
  E（報告）: 実在の器 vs 親（QQQE/QTEC→QQQ・FXL→XLK・FTXL→SMH・RSP→SPY ほか）
  I（報告）: 新規資金だけを勢いの最上位へ振り向ける積立（売らない）vs 固定の割合

段
  run : 全部を計算して out/mw_inside_tech.json
"""
import sys, os, json, math, gzip, time, subprocess, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

PRE_NAME = 'mw_inside_tech_prereg.json'
OUT_NAME = 'mw_inside_tech.json'
START = 196607
POSTPUB = 200001
MIN_FIRMS = 5
COST = 0.001
CLUSTERS = {'tech': ['Chips', 'Hardw', 'Softw', 'LabEq'],
            'health': ['Drugs', 'MedEq', 'Hlth'],
            'resources': ['Oil', 'Coal', 'Mines', 'Gold'],
            'staples': ['Food', 'Beer', 'Smoke', 'Hshld']}
REPL = ['health', 'resources', 'staples']
L_RULES = ['L_mom_T1', 'L_mom_T2', 'L_val_T1', 'L_val_T2', 'L_combo_T1', 'L_combo_T2', 'L_EW']
DESC = {
    'L_mom_T1': 'ハイテク4業種のうち12-1の勢いが最上位の1業種（毎月）',
    'L_mom_T2': '勢いの上位2業種を時価加重（毎月）',
    'L_val_T1': '割安（Sum BE/Sum ME）が最上位の1業種',
    'L_val_T2': '割安の上位2業種を時価加重',
    'L_combo_T1': '勢いの順位＋割安の順位の和が最良の1業種',
    'L_combo_T2': '順位の和の上位2業種を時価加重',
    'L_EW': '選べるハイテク業種を等分（毎月組み直し）',
}


def madd(m, k):
    y, mo = divmod(m, 100)
    t = y * 12 + (mo - 1) + k
    return (t // 12) * 100 + t % 12 + 1


def sha_of(path):
    try:
        return subprocess.run(['git', '-C', M.BASE, 'log', '-1', '--format=%H', '--', path], capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa
        return None


# ───────────────────────── French 49 ─────────────────────────
class FR:
    def __init__(self):
        T = M.french_tables('49_Industry_Portfolios')
        vw = T['Average Value Weighted Returns -- Monthly']
        ew = T['Average Equal Weighted Returns -- Monthly']
        self.cols = [c.strip() for c in vw['cols']]

        def monthly(tab, scale):
            return {c: {m: row[j] * scale for m, row in tab['data'].items() if row[j] is not None} for j, c in enumerate(self.cols)}
        self.R = monthly(vw, 0.01)
        self.EW = monthly(ew, 0.01)
        self.N = monthly(T['Number of Firms in Portfolios'], 1)
        SZ = monthly(T['Average Firm Size'], 1)
        # ME_c(m) = 社数(m) × 平均規模(m) ＝ m 月初（m−1 月末）の時価。0・欠測は入れない（点検: 追従のぶれ 0.448%/年）
        self.ME = {c: {m: self.N[c][m] * SZ[c][m] for m in self.N[c] if m in SZ[c] and self.N[c][m] > 0 and SZ[c][m] > 0} for c in self.cols}
        bm = T['Sum of BE / Sum of ME']
        self.BM = {c: {y: row[j] for y, row in bm['data'].items() if row[j] is not None} for j, c in enumerate(self.cols)}
        self.months = sorted(set().union(*[set(self.R[c]) for c in self.cols]))
        # prereg2（探索 X）用: 配当なしの価格リターンと無リスク金利
        W = M.french_tables('49_Industry_Portfolios_Wout_Div')['Average Value Weighted Returns -- Monthly']
        assert [c.strip() for c in W['cols']] == self.cols, '配当なしファイルの列が違う'
        self.RX = monthly(W, 0.01)
        self.RF = M.ff_factors()['rf']

    def mom(self, c, m):
        ks = [madd(m, -k) for k in range(2, 13)]           # m−2 … m−12（11か月・1か月飛ばす）
        assert all(k < m for k in ks)
        r = self.R[c]
        if not all(k in r for k in ks):
            return None
        return math.exp(math.fsum(math.log1p(r[k]) for k in ks)) - 1

    def val(self, c, m):
        t = m // 100 if m % 100 >= 7 else m // 100 - 1       # t 年7月〜t+1 年6月は 行 t（t年6月末に分かる）
        v = self.BM[c].get(t)
        return v if v is not None and v > 0 else None

    def eligible(self, c, m):
        return self.N[c].get(m, 0) >= MIN_FIRMS and m in self.ME[c] and m in self.R[c]

    # ── prereg2 の信号（m より前の月だけ） ──
    def mom6(self, c, m):
        ks = [madd(m, -k) for k in range(1, 7)]
        r = self.R[c]
        if not all(k in r for k in ks):
            return None
        return math.exp(math.fsum(math.log1p(r[k]) for k in ks)) - 1

    def mom1(self, c, m):
        return self.R[c].get(madd(m, -1))

    def hi52(self, c, m):
        rx = self.RX[c]
        ks = [madd(m, -k) for k in range(12, 0, -1)]      # m−12 … m−1
        if not all(k in rx for k in ks):
            return None
        p, px = 1.0, []
        for k in ks:
            p *= 1 + rx[k]; px.append(p)
        return px[-1] / max(px)

    def seas(self, c, m, years=20, need=10):
        r = self.R[c]
        v = [r[madd(m, -12 * k)] for k in range(1, years + 1) if madd(m, -12 * k) in r]
        return S.mean(v) if len(v) >= need else None

    def ts_pass(self, c, m):
        ks = [madd(m, -k) for k in range(1, 13)]
        r = self.R[c]
        if not all(k in r and k in self.RF for k in ks):
            return None
        g = math.fsum(math.log1p(r[k]) for k in ks); gf = math.fsum(math.log1p(self.RF[k]) for k in ks)
        return g > gf


def rank_desc(vals):
    """{c: v} → {c: 順位(1=最大)}。同点は後段の並べ替えで裁くので、ここでは値の大きい順・同値は ME の順を呼び出し側で"""
    ks = sorted(vals, key=lambda c: -vals[c])
    return {c: i + 1 for i, c in enumerate(ks)}


def weights(F, cols, rule, m):
    """月 m に持つ業種の重み {c: w}（m より前に分かる値だけ）。選べるものが無ければ None"""
    el = [c for c in cols if F.eligible(c, m)]
    me = {c: F.ME[c][m] for c in el}
    if rule == 'cap':
        cs = [c for c in cols if m in F.ME[c] and m in F.R[c]]      # 塊の全部（社数の条件なし）
        tot = sum(F.ME[c][m] for c in cs)
        return {c: F.ME[c][m] / tot for c in cs} if tot > 0 else None
    if rule == 'L_EW':
        return {c: 1 / len(el) for c in el} if el else None
    sig, K = rule.split('_')[1], int(rule[-1])
    if sig == 'mom':
        sc = {c: F.mom(c, m) for c in el}
        sc = {c: v for c, v in sc.items() if v is not None}
        order = sorted(sc, key=lambda c: (-sc[c], -me[c]))
    elif sig == 'val':
        sc = {c: F.val(c, m) for c in el}
        sc = {c: v for c, v in sc.items() if v is not None}
        order = sorted(sc, key=lambda c: (-sc[c], -me[c]))
    elif sig == 'combo':
        mo = {c: F.mom(c, m) for c in el}; va = {c: F.val(c, m) for c in el}
        both = [c for c in el if mo[c] is not None and va[c] is not None]
        if not both:
            return None
        rm = rank_desc({c: mo[c] for c in both}); rv = rank_desc({c: va[c] for c in both})
        order = sorted(both, key=lambda c: (rm[c] + rv[c], -mo[c], -me[c]))
    else:
        raise ValueError(rule)
    pick = order[:K]
    if not pick:
        return None
    tot = sum(me[c] for c in pick)
    return {c: me[c] / tot for c in pick}


X_RULES = ['X_mom6_T1', 'X_mom6_T2', 'X_mom1_T1', 'X_mom1_T2', 'X_hi52_T1', 'X_hi52_T2', 'X_seas_T1', 'X_seas_T2',
           'X_mom_T3', 'X_tsmom_excl', 'X_tsmom_mom_T1']
DESC.update({
    'X_mom6_T1': '6か月の勢い（m−6〜m−1）の最上位1業種', 'X_mom6_T2': '6か月の勢いの上位2業種',
    'X_mom1_T1': '先月のリターンの最上位1業種', 'X_mom1_T2': '先月のリターンの上位2業種',
    'X_hi52_T1': '52週高値への近さの最上位1業種', 'X_hi52_T2': '52週高値への近さの上位2業種',
    'X_seas_T1': '同じ暦月の過去20年平均の最上位1業種', 'X_seas_T2': '同じ暦月の過去20年平均の上位2業種',
    'X_mom_T3': '12-1 の最悪1業種だけ外す（上位3を時価加重）',
    'X_tsmom_excl': '12か月の総リターンが無リスク金利を上回る業種だけ時価加重（無ければ全部）',
    'X_tsmom_mom_T1': '無リスク金利を上回る業種の中の 12-1 最上位1業種',
})


def xweights(F, cols, rule, m):
    """prereg2 の探索の規則の重み（m より前に分かる値だけ）"""
    el = [c for c in cols if F.eligible(c, m)]
    me = {c: F.ME[c][m] for c in el}

    def top(sc, K):
        sc = {c: v for c, v in sc.items() if v is not None}
        order = sorted(sc, key=lambda c: (-sc[c], -me[c]))[:K]
        if not order:
            return None
        tot = sum(me[c] for c in order)
        return {c: me[c] / tot for c in order}
    if rule == 'X_mom_T3':
        return top({c: F.mom(c, m) for c in el}, 3)
    if rule in ('X_tsmom_excl', 'X_tsmom_mom_T1'):
        tp = {c: F.ts_pass(c, m) for c in el}
        ok = [c for c in el if tp[c]]
        if rule == 'X_tsmom_excl':
            cs = ok or [c for c in el if tp[c] is not None]
            if not cs:
                return None
            tot = sum(me[c] for c in cs)
            return {c: me[c] / tot for c in cs}
        cand = ok or el
        return top({c: F.mom(c, m) for c in cand}, 1)
    sig, K = rule.split('_')[1], int(rule[-1])
    fn = {'mom6': F.mom6, 'mom1': F.mom1, 'hi52': F.hi52, 'seas': F.seas}[sig]
    return top({c: fn(c, m) for c in el}, K)


def run_rule(F, cols, rule, start=START, end=None, min_elig=1):
    """→ (月次総リターン {m: r}, 年率の片道入れ替え, 保有の記録 {m: [業種]})"""
    out, held, turns = {}, {}, []
    prev = None
    wfn = xweights if rule.startswith('X_') else weights
    for m in F.months:
        if m < start or (end and m > end):
            continue
        if min_elig > 1 and sum(1 for c in cols if F.eligible(c, m)) < min_elig:
            prev = None
            continue
        w = wfn(F, cols, rule, m)
        if not w:
            prev = None
            continue
        r = math.fsum(w[c] * F.R[c][m] for c in w)
        if prev is not None:
            turns.append(0.5 * sum(abs(w.get(c, 0) - prev.get(c, 0)) for c in set(w) | set(prev)))
        out[m] = r
        held[m] = sorted(w)
        prev = {c: w[c] * (1 + F.R[c][m]) / (1 + r) for c in w}
    ann = S.mean(turns) * 12 if turns else 0.0
    return out, ann, held


def stock_ew(F, cols):
    """塊の銘柄等分（49業種の EW を社数で重みづけ）＝紙の脚（捕捉の回帰用・格付けしない）"""
    out = {}
    for m in F.months:
        cs = [c for c in cols if m in F.EW[c] and F.N[c].get(m, 0) > 0]
        n = sum(F.N[c][m] for c in cs)
        if n > 0:
            out[m] = math.fsum(F.N[c][m] * F.EW[c][m] for c in cs) / n
    return out


def block(s, b, turn, mkt=None, postpub=False):
    e = {'full': M.excess_stats(s, b), 'train': M.excess_stats(s, b, z=M.TRAIN_END), 'hold': M.excess_stats(s, b, a=M.HOLD_START),
         'recent': M.excess_stats(s, b, a=M.RECENT_START)}
    if postpub:
        e['postpub_2000'] = M.excess_stats(s, b, a=POSTPUB)
    e['turnover_ann'] = round(turn, 3)
    e['cost_hold'] = M.excess_stats(M.apply_cost(s, turn, COST), b, a=M.HOLD_START)
    e['cost_full'] = M.excess_stats(M.apply_cost(s, turn, COST), b)
    e['roll20'] = M.rolling(s, b, 20)
    e['dca20'] = M.dca(s, b, 20)
    e['maxdd_s'] = round(M.maxdd(s) * 100, 1)
    e['maxdd_b'] = round(M.maxdd({k: b[k] for k in s if k in b}) * 100, 1)
    if mkt:
        e['vs_mkt'] = {'full': M.excess_stats(s, mkt), 'train': M.excess_stats(s, mkt, z=M.TRAIN_END), 'hold': M.excess_stats(s, mkt, a=M.HOLD_START)}
    return e


def L_family(F, mkt, rules=None):
    rules = rules or L_RULES
    res, series = {}, {}
    bench, bturn, _ = run_rule(F, CLUSTERS['tech'], 'cap')
    series['cap'] = bench
    res['cluster_vs_mkt'] = {'full': M.excess_stats(bench, mkt), 'train': M.excess_stats(bench, mkt, z=M.TRAIN_END),
                             'hold': M.excess_stats(bench, mkt, a=M.HOLD_START), 'recent': M.excess_stats(bench, mkt, a=M.RECENT_START),
                             'from_1966_07': M.excess_stats(M.window(bench, START), mkt), 'roll20': M.rolling(M.window(bench, START), mkt, 20)}
    rb = {}
    for cl in REPL:
        rb[cl] = run_rule(F, CLUSTERS[cl], 'cap')[0]
    for rule in rules:
        s, turn, held = run_rule(F, CLUSTERS['tech'], rule)
        series[rule] = s
        e = block(s, bench, turn, mkt, postpub=('mom' in rule or 'combo' in rule or rule.startswith('X_')))
        # 何を持っていたか（業種ごとの月数・期間別）
        cnt = {}
        for m, cs in held.items():
            per = 'train' if m <= M.TRAIN_END else 'hold'
            for c in cs:
                cnt.setdefault(per, {}).setdefault(c, 0)
                cnt[per][c] += 1
        e['months_held'] = cnt
        e['last_12_holdings'] = {m: held[m] for m in sorted(held)[-12:]}
        rep = {}
        for cl in REPL:
            rs, rt, _ = run_rule(F, CLUSTERS[cl], rule)
            rep[cl] = {'full': M.excess_stats(rs, rb[cl]), 'hold': M.excess_stats(rs, rb[cl], a=M.HOLD_START), 'turnover_ann': round(rt, 3)}
        pos = sum(1 for cl in REPL if rep[cl]['full'] and rep[cl]['full']['ex_ann'] > 0)
        e['repl'] = {'regions': len(REPL), 'positive': pos, 'detail': rep, 'rule': '全期間の算術平均の超過が正の塊の数'}
        res[rule] = e
    hp = {r: (res[r]['hold'] or {}).get('p') for r in rules}
    hh = M.holm(hp)
    for r in rules:
        e = res[r]
        e['family_holm_p_hold'] = hh.get(r)
        g, c = M.grade(e['full'], e['train'], e['hold'], e['roll20'], cost_hold=e['cost_hold'], repl=e['repl'], family_holm_p=hh.get(r))
        e['grade'], e['criteria'] = g, c
    return res, series


def P_pre1966(F):
    """prereg2 の報告: 1946-07〜1966-06 の月（選べる業種が2つ以上の月だけ）に同じ規則を当てる"""
    cols = CLUSTERS['tech']
    bench = run_rule(F, cols, 'cap', start=194607, end=196606, min_elig=2)[0]
    out = {'bench_months': [min(bench), max(bench), len(bench)] if bench else None}
    for rule in L_RULES + X_RULES:
        s, turn, held = run_rule(F, cols, rule, start=194607, end=196606, min_elig=2)
        cnt = {}
        for m, cs in held.items():
            for c in cs:
                cnt[c] = cnt.get(c, 0) + 1
        out[rule] = {'stats': M.excess_stats(s, bench), 'months': len(s), 'months_held': cnt}
    return out


# ───────────────────────── Y（prereg3: 時価加重をやめる・国ごとの IT） ─────────────────────────
DEV22 = ['aus', 'aut', 'bel', 'can', 'che', 'deu', 'dnk', 'esp', 'fin', 'fra', 'gbr', 'hkg', 'irl', 'isr', 'ita', 'jpn',
         'nld', 'nor', 'nzl', 'prt', 'sgp', 'swe']


def jkp_it(c, w):
    import io, zipfile, csv
    try:
        b = M.get(f'https://jkpfactors-data.s3.amazonaws.com/public/industry/%5B{c}%5D_%5Bgics%5D_%5Bmonthly%5D_%5B{w}%5D.zip',
                  name=f'jkp_ind_{c}_gics_{w}.zip', tries=3)
    except Exception:  # noqa
        return None
    z = zipfile.ZipFile(io.BytesIO(b))
    out = {}
    for r in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        if r['gics'] == '45' and r['ret'] not in ('', 'NA', 'na'):
            out[M._ym(r['date'])] = float(r['ret'])
    return out


def Y_family(F):
    res = {}
    cost = {'cap': (0.20, 0.001), 'ew': (1.00, 0.003)}
    for lab, w in (('Y_ITcap_usa', 'vw_cap'), ('Y_ITew_usa', 'ew')):
        s, b = jkp_it('usa', w), jkp_it('usa', 'vw')
        turn, cu = cost['cap' if w == 'vw_cap' else 'ew']
        e = {'full': M.excess_stats(s, b), 'train': M.excess_stats(s, b, z=M.TRAIN_END), 'hold': M.excess_stats(s, b, a=M.HOLD_START),
             'recent': M.excess_stats(s, b, a=M.RECENT_START), 'turnover_ann': turn, 'cost_per_unit': cu,
             'cost_hold': M.excess_stats(M.apply_cost(s, turn, cu), b, a=M.HOLD_START), 'roll20': M.rolling(s, b, 20), 'dca20': M.dca(s, b, 20)}
        det = {}
        for c in DEV22:
            sc, bc = jkp_it(c, w), jkp_it(c, 'vw')
            st = M.excess_stats(sc, bc) if sc and bc else None
            if st:
                det[c] = {'ex_ann': st['ex_ann'], 't': st['t'], 'from': st['from'], 'to': st['to'],
                          'hold_ex': (M.excess_stats(sc, bc, a=M.HOLD_START) or {}).get('ex_ann')}
        e['repl'] = {'regions': len(det), 'positive': sum(1 for v in det.values() if v['ex_ann'] > 0), 'detail': det,
                     'rule': '先進22か国のうち24か月以上そろう国・全期間の平均の差が正の国の数'}
        res[lab] = e
    cols = CLUSTERS['tech']
    cap = run_rule(F, cols, 'cap')[0]
    sew = {k: v for k, v in stock_ew(F, cols).items() if k >= START}
    e = {'full': M.excess_stats(sew, cap), 'train': M.excess_stats(sew, cap, z=M.TRAIN_END), 'hold': M.excess_stats(sew, cap, a=M.HOLD_START),
         'recent': M.excess_stats(sew, cap, a=M.RECENT_START), 'turnover_ann': 1.0, 'cost_per_unit': 0.003,
         'cost_hold': M.excess_stats(M.apply_cost(sew, 1.0, 0.003), cap, a=M.HOLD_START), 'roll20': M.rolling(sew, cap, 20), 'dca20': M.dca(sew, cap, 20)}
    det = {}
    for cl in REPL:
        cb = run_rule(F, CLUSTERS[cl], 'cap')[0]
        cs = {k: v for k, v in stock_ew(F, CLUSTERS[cl]).items() if k >= START}
        st = M.excess_stats(cs, cb)
        det[cl] = {'full': st, 'hold': M.excess_stats(cs, cb, a=M.HOLD_START)}
    e['repl'] = {'regions': len(REPL), 'positive': sum(1 for v in det.values() if v['full'] and v['full']['ex_ann'] > 0), 'detail': det,
                 'rule': '3つの塊・全期間の平均の差が正の数'}
    res['Y_FR_stockEW_tech'] = e
    hh = M.holm({k: (v['hold'] or {}).get('p') for k, v in res.items()})
    for k, e in res.items():
        e['family_holm_p_hold'] = hh.get(k)
        g, c = M.grade(e['full'], e['train'], e['hold'], e['roll20'], cost_hold=e['cost_hold'], repl=e['repl'], family_holm_p=hh.get(k))
        e['grade'], e['criteria'] = g, c
        e['role'] = 'exploratory_prereg3（探索）'
    return res


# ───────────────────────── S（SEC 2010〜） ─────────────────────────
def S_family():
    import mw_sec_replication as SR
    panel = SR.build_panel()
    uni, price, diag, sic, tick = SR.build_universe(panel, fetch=False, verbose=False)
    rets = {x: v[0] for x, v in price.items() if v}
    need = {c for t in uni for c, r in uni[t].items() if r.get('ff12') == 'BusEq'}
    ni = {}
    for rec in SR.load_extract():
        c = str(int(rec['cik']))
        if c not in need:
            continue
        rows = rec['t'].get('NetIncomeLoss', [])
        for t in uni:
            r = uni[t].get(c)
            if not r or not r.get('fy_end'):
                continue
            dE = SR._d(r['fy_end']); cutoff = f'{t}-06-30'
            cand = [q for q in rows if q[2] <= cutoff and abs((SR._d(q[0]) - dE).days) <= 3 and SR._num(q[1]) is not None]
            if cand:
                ni[(t, c)] = float(max(cand, key=lambda q: (q[2], q[3]))[1])

    def mom(tk, t):
        r = rets.get(tk, {})
        ks = [madd(t * 100 + 6, -k) for k in range(1, 12)]    # t年5月 … t−1年7月（11か月・6月を飛ばす）
        assert all(k < t * 100 + 7 for k in ks)
        if not all(k in r for k in ks):
            return None
        return math.exp(math.fsum(math.log1p(r[k]) for k in ks)) - 1

    MEGA = SR.MEGA6
    out, info = {}, {'n_buseq': {}, 'n_signal': {}, 'ni_found': {}}
    for drop_lab, drop in (('all', frozenset()), ('ex_mega6', frozenset(MEGA))):
        coh = {k: {} for k in ['bench', 'S_val_T3', 'S_mom_T3', 'S_valmom_T3', 'S_gp_T3', 'S_qvm_T3']}
        for t in sorted(uni):
            u = uni[t]
            B = {c: r for c, r in u.items() if r.get('ff12') == 'BusEq' and r['ticker'] not in drop}
            if not B:
                continue
            ep = {c: ni[(t, c)] / r['fcap'] for c, r in B.items() if (t, c) in ni}
            bp = {c: r['be'] / r['fcap'] for c, r in B.items() if r.get('be')}
            zep, zbp = SR.rank_z(ep), SR.rank_z(bp)
            val = {}
            for c in B:
                parts = [z[c] for z in (zep, zbp) if c in z]
                if parts:
                    val[c] = sum(parts) / len(parts)
            mo = {c: mom(r['ticker'], t) for c, r in B.items()}
            mo = {c: v for c, v in mo.items() if v is not None}
            gp = {c: r['gp_at'] for c, r in B.items() if r.get('gp_at') is not None}
            zv, zm, zg = SR.rank_z(val), SR.rank_z(mo), SR.rank_z(gp)
            vm = {c: (zv[c] + zm[c]) / 2 for c in B if c in zv and c in zm}
            qvm = {}
            for c in B:
                parts = [z[c] for z in (zv, zm, zg) if c in z]
                if len(parts) >= 2:
                    qvm[c] = sum(parts) / len(parts)
            if drop_lab == 'all':
                info['n_buseq'][t] = len(B)
                info['n_signal'][t] = {'EP': len(ep), 'BP': len(bp), 'val': len(val), 'mom': len(mo), 'gp': len(gp), 'valmom': len(vm), 'qvm': len(qvm)}
                info['ni_found'][t] = sum(1 for c in B if (t, c) in ni)
            tk = lambda c: u[c]['ticker']
            coh['bench'][t] = {tk(c): r['fcap'] for c, r in B.items()}
            for nm, sc in (('S_val_T3', val), ('S_mom_T3', mo), ('S_valmom_T3', vm), ('S_gp_T3', gp), ('S_qvm_T3', qvm)):
                sel = SR.top_by(sc, u, frac=1 / 3)
                if sel:
                    coh[nm][t] = {tk(c): u[c]['fcap'] for c in sel}
        bench, _bt, _ = SR.simulate(coh['bench'], rets)
        for nm in ['S_val_T3', 'S_mom_T3', 'S_valmom_T3', 'S_gp_T3', 'S_qvm_T3']:
            s, turn, drops = SR.simulate(coh[nm], rets)
            turn = turn or 0.0
            e = {'full': M.excess_stats(s, bench), 'train': None, 'hold': M.excess_stats(s, bench, a=M.HOLD_START),
                 'recent': M.excess_stats(s, bench, a=M.RECENT_START), 'turnover_ann': round(turn, 3),
                 'cost_hold': M.excess_stats(M.apply_cost(s, turn, COST), bench, a=M.HOLD_START),
                 'roll20': M.rolling(s, bench, 20), 'dca20': M.dca(s, bench, 20), 'drops': drops,
                 'n_names_by_year': {t: len(v) for t, v in coh[nm].items()},
                 'top5_2025': sorted(coh[nm].get(2025, {}), key=lambda x: -coh[nm][2025][x])[:5]}
            g, c = M.grade(e['full'], e['train'], e['hold'], e['roll20'], cost_hold=e['cost_hold'])
            e['grade'], e['criteria'] = g, c
            e['grade_note'] = '訓練期間なし＝C1 が構造的に不合格（報告のみ）'
            out[f'{nm}_{drop_lab}'] = e
        out[f'bench_{drop_lab}_months'] = [min(bench), max(bench)] if bench else None
    return out, info


# ───────────────────────── E（実在の器） ─────────────────────────
E_PAIRS = [('QQQE', 'QQQ', True), ('QTEC', 'QQQ', True), ('FXL', 'XLK', True), ('FTXL', 'SMH', True), ('RSP', 'SPY', True),
           ('QQEW', 'QQQ', False), ('RSPT', 'XLK', False), ('XSD', 'SMH', False), ('PSI', 'SMH', False), ('SOXQ', 'SOXX', False),
           ('SOXX', 'SMH', False)]


def ols(y, x):
    ks = sorted(set(y) & set(x))
    if len(ks) < 24:
        return None
    Y = [y[k] for k in ks]; X = [x[k] for k in ks]
    mx, my = S.mean(X), S.mean(Y)
    vx = sum((a - mx) ** 2 for a in X)
    if vx <= 0:
        return None
    b = sum((a - mx) * (c - my) for a, c in zip(X, Y)) / vx
    return {'n': len(ks), 'beta': round(b, 3), 'corr': round(M.corr(Y, X), 3), 'mean_y_ann': round(my * 1200, 2), 'mean_x_ann': round(mx * 1200, 2),
            'alpha_ann': round((my - b * mx) * 1200, 2)}


def E_family(legs):
    out = {}
    for a, b, hold in E_PAIRS:
        ra, rb = M.yahoo(a), M.yahoo(b)
        d = {k: ra[k] - rb[k] for k in ra if k in rb}
        e = {'holdable_rakuten': hold, 'full': M.excess_stats(ra, rb), 'train': M.excess_stats(ra, rb, z=M.TRAIN_END),
             'hold': M.excess_stats(ra, rb, a=M.HOLD_START), 'recent': M.excess_stats(ra, rb, a=M.RECENT_START),
             'roll20': M.rolling(ra, rb, 20), 'dca20': M.dca(ra, rb, 20), 'dca10': M.dca(ra, rb, 10),
             'cost_hold': M.excess_stats(ra, rb, a=M.HOLD_START),
             'cost_note': 'Yahoo の調整後終値は信託報酬を引いた後。器の中の売買費用も値に入っている',
             'capture': {k: ols(d, leg) for k, leg in legs.items()}}
        g, c = M.grade(e['full'], e['train'], e['hold'], e['roll20'], cost_hold=e['cost_hold'])
        e['grade'], e['criteria'] = g, c
        e['grade_note'] = '訓練期間が無い（または短い）＝構造的に C（報告のみ）。生き残りの偏りあり'
        out[f'E_{a}_{b}'] = e
    return out


# ───────────────────────── I（新規資金の振り向け） ─────────────────────────
def dca_steer(choose, fixed, rets, months, detail=False):
    """毎月1単位。choose(m) → 資産名（振り向け）、fixed = {資産: 割合}（相手）。売らない。→ 最終額 (steer, fixed)"""
    hs, hf, cnt = {}, {}, {}
    for m in months:
        a = choose(m)
        if a is None:
            return None
        hs[a] = hs.get(a, 0.0) + 1.0
        cnt[a] = cnt.get(a, 0) + 1
        for x, w in fixed.items():
            hf[x] = hf.get(x, 0.0) + w
        for x in list(hs):
            if m not in rets[x]:
                return None
            hs[x] *= 1 + rets[x][m]
        for x in list(hf):
            if m not in rets[x]:
                return None
            hf[x] *= 1 + rets[x][m]
    if detail:
        tot = sum(hs.values()); n = sum(cnt.values())
        return {'share_of_contributions': {k: round(v / n, 3) for k, v in sorted(cnt.items())},
                'final_pot_share': {k: round(v / tot, 3) for k, v in sorted(hs.items())}}
    return sum(hs.values()), sum(hf.values())


def steer_windows(choose, fixed, rets, months, years_list=(10, 15, 20), step=12):
    out = {}
    for Y in years_list:
        n = Y * 12
        res = []
        for i in range(0, len(months) - n + 1, step):
            w = months[i:i + n]
            v = dca_steer(choose, fixed, rets, w)
            if v:
                res.append((w[0], round(v[0] / v[1], 3)))
        if res:
            vs = sorted(r for _, r in res)
            out[f'{Y}y'] = {'windows': len(res), 'win_rate': round(sum(1 for r in vs if r > 1) / len(vs), 3), 'median_ratio': vs[len(vs) // 2],
                            'worst': min(res, key=lambda x: x[1]), 'best': max(res, key=lambda x: x[1])}
    v = dca_steer(choose, fixed, rets, months)
    out['all_span'] = {'from': months[0], 'to': months[-1], 'ratio': round(v[0] / v[1], 3) if v else None}
    out['diag_prereg2'] = {'all_span': dca_steer(choose, fixed, rets, months, detail=True)}
    for a0 in (200001, 200607):   # 20年積立の起点の例（診断）
        w = [m for m in months if m >= a0][:240]
        if len(w) == 240:
            out['diag_prereg2'][f'20y_from_{a0}'] = dca_steer(choose, fixed, rets, w, detail=True)
    return out


def I_family(F):
    out = {}
    E = {x: M.yahoo(x) for x in ('QQQ', 'XLK', 'SMH')}

    def emom(x, m):
        ks = [madd(m, -k) for k in range(2, 13)]
        r = E[x]
        if not all(k in r for k in ks):
            return None
        return math.exp(math.fsum(math.log1p(r[k]) for k in ks)) - 1

    def ch_etf(m):
        sc = {x: emom(x, m) for x in E}
        if any(v is None for v in sc.values()):
            return None
        return max(sc, key=lambda x: sc[x])
    ms = sorted(k for k in set(E['QQQ']) & set(E['XLK']) & set(E['SMH']) if ch_etf(k) is not None)
    share = {}
    for m in ms:
        share[ch_etf(m)] = share.get(ch_etf(m), 0) + 1
    out['I_etf_mom_vs_QQQ75_SMH25'] = steer_windows(ch_etf, {'QQQ': 0.75, 'SMH': 0.25}, E, ms)
    out['I_etf_mom_vs_QQQ75_SMH25']['share_of_contributions'] = {k: round(v / len(ms), 3) for k, v in share.items()}
    out['I_etf_mom_vs_QQQ'] = steer_windows(ch_etf, {'QQQ': 1.0}, E, ms)
    # French 版
    cols = CLUSTERS['tech']
    cap = run_rule(F, cols, 'cap')[0]
    R = dict(F.R); R['cap'] = cap
    for lab, rule in (('I_fr_mom', 'L_mom_T1'), ('I_fr_combo', 'L_combo_T1'), ('I_fr_val', 'L_val_T1')):
        def ch(m, rule=rule):
            w = weights(F, cols, rule, m)
            return next(iter(w)) if w else None
        ms2 = [m for m in F.months if m >= START and m in cap and ch(m) is not None]
        out[f'{lab}_vs_cap'] = steer_windows(ch, {'cap': 1.0}, R, ms2)
    return out


# ───────────────────────── 実行 ─────────────────────────
def run():
    t0 = time.time()
    ff = M.ff_factors()
    mkt = ff['mkt']
    checks = {'mkt_cagr_1926': round(M.cagr(mkt) * 100, 2), 'mkt_cagr_2007': round(M.cagr(M.window(mkt, M.HOLD_START)) * 100, 2)}
    F = FR()
    L, series = L_family(F, mkt)
    # 点検: 4業種の塊 vs French 12業種の BusEq
    T12 = M.french_tables('12_Industry_Portfolios')['Average Value Weighted Returns -- Monthly']
    j = [c.strip() for c in T12['cols']].index('BusEq')
    be12 = {m: row[j] / 100 for m, row in T12['data'].items() if row[j] is not None}
    ks = sorted(k for k in series['cap'] if k in be12 and k >= START)
    checks['cluster_vs_ff12_BusEq'] = {'corr': round(M.corr([series['cap'][k] for k in ks], [be12[k] for k in ks]), 4),
                                       'mean_diff_ann': round(S.mean([series['cap'][k] - be12[k] for k in ks]) * 1200, 2), 'n': len(ks)}
    checks['L_start'] = min(series['L_mom_T1'])
    checks['cluster_months'] = [min(series['cap']), max(series['cap'])]
    # 捕捉の回帰の脚
    jv, jc = M.jkp_mkt('usa', 'vw'), M.jkp_mkt('usa', 'vw_cap')
    legs = {'US_mega_vw_minus_vwcap': {k: jv[k] - jc[k] for k in jv if k in jc},
            'L_EW_minus_cap': {k: series['L_EW'][k] - series['cap'][k] for k in series['L_EW'] if k in series['cap']},
            'L_combo_T2_minus_cap': {k: series['L_combo_T2'][k] - series['cap'][k] for k in series['L_combo_T2'] if k in series['cap']},
            'L_mom_T2_minus_cap': {k: series['L_mom_T2'][k] - series['cap'][k] for k in series['L_mom_T2'] if k in series['cap']}}
    sew = stock_ew(F, CLUSTERS['tech'])
    legs['stockEW_minus_cap'] = {k: sew[k] - series['cap'][k] for k in sew if k in series['cap']}
    Ef = E_family(legs)
    Sf, Sinfo = S_family()
    If = I_family(F)
    # prereg2: 探索の族 X と報告 P
    X, xseries = L_family(F, mkt, rules=X_RULES)
    X.pop('cluster_vs_mkt', None)
    for r in X_RULES:
        X[r]['role'] = 'exploratory_prereg2（探索・主の族の格付けを置き換えない）'
    P = P_pre1966(F)
    Y = Y_family(F)
    tested = []
    for r in L_RULES:
        tested.append({'name': r, 'family': 'L', 'role': 'primary', 'grade': L[r]['grade'], 'desc': DESC[r]})
        for cl in REPL:
            tested.append({'name': f'{r}@{cl}', 'family': 'L_repl', 'role': 'C5 の再現（格付けしない）'})
    tested.append({'name': 'cluster_vs_mkt', 'family': 'L', 'role': '報告（ハイテクの塊そのもの vs French Mkt）'})
    for k, v in Sf.items():
        if isinstance(v, dict) and 'grade' in v:
            tested.append({'name': k, 'family': 'S', 'role': 'report', 'grade': v['grade']})
    for k, v in Ef.items():
        tested.append({'name': k, 'family': 'E', 'role': 'report', 'grade': v['grade'], 'holdable_rakuten': v['holdable_rakuten']})
    for k in If:
        tested.append({'name': k, 'family': 'I', 'role': 'report（格付けしない）'})
    for r in X_RULES:
        tested.append({'name': r, 'family': 'X', 'role': 'exploratory_prereg2', 'grade': X[r]['grade'], 'desc': DESC[r]})
        for cl in REPL:
            tested.append({'name': f'{r}@{cl}', 'family': 'X_repl', 'role': 'C5 の再現（格付けしない）'})
    for k, v in Y.items():
        tested.append({'name': k, 'family': 'Y', 'role': 'exploratory_prereg3', 'grade': v['grade']})
        for c in v['repl']['detail']:
            tested.append({'name': f'{k}@{c}', 'family': 'Y_repl', 'role': 'C5 の再現（格付けしない）'})
    for r in L_RULES + X_RULES:
        tested.append({'name': f'{r}@pre1966', 'family': 'P', 'role': 'report_prereg2（1946-07〜1966-06・格付けしない）'})
    obj = {'angle': 'inside_tech', 'tool': 'night/mw_inside_tech.py', 'prereg': PRE_NAME, 'prereg_commit': sha_of(os.path.join('out', PRE_NAME)),
           'global_prereg': 'out/mw_prereg.json', 'checks': checks, 'L': L, 'S': Sf, 'S_info': Sinfo, 'E': Ef, 'I': If, 'X': X, 'P_pre1966': P, 'Y': Y,
           'prereg3': 'mw_inside_tech_prereg3.json', 'prereg3_commit': sha_of(os.path.join('out', 'mw_inside_tech_prereg3.json')),
           'prereg2': 'mw_inside_tech_prereg2.json', 'prereg2_commit': sha_of(os.path.join('out', 'mw_inside_tech_prereg2.json')),
           'tested': tested, 'n_tested': len(tested), 'runtime_s': round(time.time() - t0, 1)}
    f2 = lambda x: None if not x else {'ex_ann': x['ex_ann'], 't': x['t'], 'cagr_diff': x['cagr_diff']}
    graded = {**{r: L[r] for r in L_RULES}, **{r: X[r] for r in X_RULES}, **Y}
    obj['grade_counts'] = {g: sum(1 for v in graded.values() if v['grade'] == g) for g in 'SABC'}
    obj['headline'] = {
        'tech_cluster_vs_mkt': {k: f2(L['cluster_vs_mkt'][k]) for k in ('full', 'train', 'hold', 'recent')},
        'best_primary': {r: {'full': f2(L[r]['full']), 'train': f2(L[r]['train']), 'hold': f2(L[r]['hold']), 'cost_hold': f2(L[r]['cost_hold']),
                             'roll20_win': (L[r]['roll20'] or {}).get('win_rate'), 'repl': f"{L[r]['repl']['positive']}/{L[r]['repl']['regions']}", 'grade': L[r]['grade']}
                         for r in ('L_mom_T1', 'L_combo_T1', 'L_EW', 'L_val_T1')},
        'pre1966_L_mom_T1': f2(P['L_mom_T1']['stats']),
        'etf_hold': {k: f2(v['hold']) for k, v in Ef.items()},
    }
    obj['deviations'] = [
        'E の族の cost_hold は保有期間の超過そのもの（Yahoo の調整後終値は信託報酬と器の中の売買費用を引いた後なので、上乗せの費用は引いていない）',
        'Y_ITcap の C5: bel・dnk・isr・nzl は vw_cap と vw が同じ（NYSE 80%点を超える銘柄が無い）＝差 0.0 を『正でない』と数えた（事前登録どおり・厳しい側）',
        'S の族の E/P は浮動株時価（fcap）で割った（持ち合い・創業者持分の多い社の E/P を大きく見せる）。事前登録どおり',
        'mw_common に不具合は見つからなかった（French Mkt の CAGR 1926〜 10.38%・2007〜 11.13% を再現、4業種の塊は French 12業種 BusEq と相関 0.9998）',
    ]
    obj['caveats'] = [
        '選べる業種は4つ（1966〜1973年は3つ）＝幅が狭い。上位1業種の規則は追従のぶれが大きく、年+4%の上乗せでも t が2に届かない',
        'French の業種は SIC の分類で、Apple・NVIDIA などは Chips に入る。実在の器（SMH・XLK・QQQ）とは中身が違う',
        'E の族は今も在る器だけ（生き残りの偏り）で、始まりは2003年以降＝訓練期間が無く構造的に C',
        'I の族の French 版の振り向け（特に割安）は、1970〜90年代に Softw・Chips に入れた積立が長く複利で育った効果が大きい（期末の山: 割安の振り向けで Chips 63.5%・Softw 28.8%、Softw への積立は5%だけ）',
    ]
    p = M.save(OUT_NAME, obj)
    print('saved', p, 'n_tested', len(tested), 'runtime', obj['runtime_s'])
    for r in L_RULES + X_RULES:
        e = L[r] if r in L else X[r]
        f = lambda x: (x['ex_ann'], x['t']) if x else None
        print(r, e['grade'], 'full', f(e['full']), 'train', f(e['train']), 'hold', f(e['hold']), 'cost', f(e['cost_hold']),
              'roll', (e['roll20'] or {}).get('win_rate'), 'repl', e['repl']['positive'], 'holm', e['family_holm_p_hold'])
    for k, e in Y.items():
        f = lambda x: (x['ex_ann'], x['t']) if x else None
        print(k, e['grade'], 'full', f(e['full']), 'train', f(e['train']), 'hold', f(e['hold']), 'cost', f(e['cost_hold']),
              'roll', (e['roll20'] or {}).get('win_rate'), 'repl', e['repl']['positive'], '/', e['repl']['regions'])


if __name__ == '__main__':
    run()
