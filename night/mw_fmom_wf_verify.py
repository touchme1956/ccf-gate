#!/usr/bin/env python3
"""night/mw_fmom_wf_verify.py — 角度 fmom_wf の主張を「反証しにいく」検証（読むだけ・門の判定には不使用）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまで…」の角度 fmom_wf（night/mw_fmom_wf.py → out/mw_fmom_wf.json）が
S・A と格付けした18本と、B の上位2本（保有期間の超過の順）を、**独立に作り直して**反証を試みる。

独立性の約束
- mw_common からは**取得だけ**（M.get・M.jkp_rows・M.FR）を使う。French の CSV の読み取り・ポートフォリオの組み立て・
  売買の漂い・費用・超過・Newey-West t・CAGR・転がる20年窓・20年積立・格付けの線の当てはめは、すべてこのファイルの自前の実装。
- 研究者のコード（night/mw_fmom_wf.py）は読んだが import しない。規則は事前登録（out/mw_fmom_wf_prereg*.json）の文言から作り直す。
- 費用の前提（三分位・五分位の中の入れ替え %/年、片道100%あたりの単価）は事前登録の数値をそのまま使い、倍率で振る。

  python3 night/mw_fmom_wf_verify.py            → out/mw_fmom_wf_verify.json
  python3 night/mw_fmom_wf_verify.py --part fr  → French の部だけ（途中結果は scratchpad へ）
"""
import sys, os, io, json, math, zipfile, collections, statistics as S, pickle, time, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # 取得だけ（get・jkp_rows・FR）

BASE = M.BASE
OUT = os.path.join(BASE, 'out', 'mw_fmom_wf_verify.json')
SCR = os.environ.get('MWV_SCRATCH', '/tmp/claude-0/-home-user-ccf-gate/51469f69-a26b-5af3-955c-7af574d178fa/scratchpad')
TR_END, H0, RECENT = 200612, 200701, 201307
FR_END, JKP_END = 202608, 202512
LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


# ───────────────────────── 暦 ─────────────────────────
def months(a, z):
    out, y, m = [], a // 100, a % 100
    while y * 100 + m <= z:
        out.append(y * 100 + m)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


# ───────────────────────── French の CSV（自前の読み取り） ─────────────────────────
def _val(s):
    s = s.strip()
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if v <= -99.99 or v == -999:
        return None
    return v / 100.0


_FRC = {}


def fr_block(name, want_title=None):
    """French の zip の**最初の月次の表**を {列名: {yyyymm: 小数}} で返す。want_title を渡せば、
    表の直前の文字行にその語が含まれることを確かめる（別の表を掴まないように）"""
    key = (name, want_title)
    if key in _FRC:
        return _FRC[key]
    b = M.get(M.FR.format(name), name=f'fr_{name}.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    lines = z.read(z.namelist()[0]).decode('latin-1').splitlines()
    cols, data, title, last_text, started = None, {}, None, '', False
    for line in lines:
        cells = [c.strip() for c in line.split(',')]
        f0 = cells[0]
        if cols is None:
            if f0 == '' and len(cells) > 2 and cells[1] and not re.match(r'^-?[\d.]+$', cells[1]):
                cols = [c for c in cells[1:]]
                while cols and cols[-1] == '':
                    cols.pop()
                title = last_text
            elif line.strip():
                last_text = line.strip()
            continue
        if re.match(r'^\d{6}$', f0):
            started = True
            vals = cells[1:1 + len(cols)]
            for c, v in zip(cols, vals):
                x = _val(v)
                if x is not None:
                    data.setdefault(c, {})[int(f0)] = x
        elif started:
            break
    if want_title and (title is None or want_title.lower() not in title.lower()):
        raise RuntimeError(f'{name}: 最初の表の題が「{title}」で「{want_title}」ではない')
    _FRC[key] = data
    return data


def fr_factors_us():
    d = fr_block('F-F_Research_Data_Factors')
    mktrf, rf = d['Mkt-RF'], d['RF']
    return mktrf, rf


def fr_factors_region(region):
    name = 'Emerging_5_Factors' if region == 'Emerging' else f'{region}_3_Factors'
    d = fr_block(name)
    return d['Mkt-RF'], d['RF']


# ───────────────────────── 統計（自前） ─────────────────────────
def nw_t(x, lag=12):
    n = len(x)
    if n < 24:
        return None
    m = math.fsum(x) / n
    e = [v - m for v in x]
    s = math.fsum(v * v for v in e) / n
    for L in range(1, min(lag, n - 1) + 1):
        s += 2 * (1 - L / (lag + 1)) * math.fsum(e[i] * e[i - L] for i in range(L, n)) / n
    return m / math.sqrt(s / n) if s > 0 else None


def geo(xs):
    return math.exp(math.fsum(math.log1p(v) for v in xs) * 12 / len(xs)) - 1


def pnorm2(t):
    return math.erfc(abs(t) / math.sqrt(2)) if t is not None else None


def stats(s, b, rf, a=None, z=None, drop=None):
    """s・b は超過（対 RF）。算術超過・NW t・CAGR の差（超過どうし と 総リターンどうし の両方）・β・追従のぶれ"""
    ks = sorted(k for k in s if k in b and k in rf and (a is None or k >= a) and (z is None or k <= z)
                and not (drop and drop(k)))
    if len(ks) < 24:
        return None
    d = [s[k] - b[k] for k in ks]
    t = nw_t(d)
    sv, bv = [s[k] for k in ks], [b[k] for k in ks]
    st, bt = [s[k] + rf[k] for k in ks], [b[k] + rf[k] for k in ks]
    mb = S.fmean(bv)
    vb = math.fsum((y - mb) ** 2 for y in bv)
    ms = S.fmean(sv)
    beta = math.fsum((x - ms) * (y - mb) for x, y in zip(sv, bv)) / vb if vb else None
    return {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'ex': round(S.fmean(d) * 1200, 2), 't': round(t, 2) if t is not None else None,
            'p': round(pnorm2(t), 5) if t is not None else None,
            'cagr_diff_excess_basis': round((geo(sv) - geo(bv)) * 100, 2),
            'cagr_diff_total_basis': round((geo(st) - geo(bt)) * 100, 2),
            'cagr_s_total': round(geo(st) * 100, 2), 'cagr_b_total': round(geo(bt) * 100, 2),
            'beta': round(beta, 3) if beta is not None else None, 'te': round(S.stdev(d) * math.sqrt(12) * 100, 2)}


def roll20(s, b, rf, years=20):
    """毎年7月起点・一括・総リターンどうしの幾何年率差。窓の240か月がすべてそろう窓だけ"""
    ks = set(k for k in s if k in b and k in rf)
    if not ks:
        return None
    y0, last = min(ks) // 100, max(ks)
    res = []
    for y in range(y0, 2100):
        w = months(y * 100 + 7, (y + years) * 100 + 6)
        if w[-1] > last:
            break
        if not all(k in ks for k in w):
            continue
        gs = math.exp(math.fsum(math.log1p(s[k] + rf[k]) for k in w) / years) - 1
        gb = math.exp(math.fsum(math.log1p(b[k] + rf[k]) for k in w) / years) - 1
        res.append((y, round((gs - gb) * 100, 2)))
    if not res:
        return None
    v = sorted(x for _, x in res)
    return {'windows': len(res), 'wins': sum(1 for x in v if x > 0), 'win_rate': round(sum(1 for x in v if x > 0) / len(v), 3),
            'median': v[len(v) // 2], 'worst': min(res, key=lambda q: q[1]),
            'windows_starting_after_1990': sum(1 for y, _ in res if y >= 1990),
            'wins_starting_after_1990': sum(1 for y, x in res if y >= 1990 and x > 0)}


def dca20(s, b, rf, years=20, step=12):
    ks = sorted(k for k in s if k in b and k in rf)
    n = years * 12
    res = []
    for i in range(0, len(ks) - n + 1, step):
        w = ks[i:i + n]
        if w[-1] != months(w[0], w[-1])[-1] or len(months(w[0], w[-1])) != n:
            continue   # 月が抜けた窓は数えない
        ws = wb = 0.0
        for k in w:
            ws = (ws + 1) * (1 + s[k] + rf[k])
            wb = (wb + 1) * (1 + b[k] + rf[k])
        res.append((w[0], round(ws / wb, 3)))
    if not res:
        return None
    v = sorted(x for _, x in res)
    return {'windows': len(res), 'win_rate': round(sum(1 for x in v if x > 1) / len(v), 3), 'median_ratio': v[len(v) // 2],
            'worst': min(res, key=lambda q: q[1])}


def holm(p):
    items = sorted((v, k) for k, v in p.items() if v is not None)
    m, run, out = len(items), 0.0, {}
    for i, (v, k) in enumerate(items):
        run = max(run, min(1.0, (m - i) * v))
        out[k] = round(run, 5)
    return out


def grade(full, train, hold, r20, net_hold, repl_ok, c7_family_p=None):
    """out/mw_prereg.json の線（C1〜C7）を自前で当てる（C8 は該当なし）。repl_ok: True/False/None(N/A)"""
    c = {}
    c['C1'] = bool(train and train['ex'] > 0 and (train['t'] or 0) >= 2.0)
    c['C2'] = bool(hold and hold['ex'] > 0 and hold['cagr_diff_excess_basis'] > 0)
    c['C3'] = bool(hold and (hold['t'] or 0) >= 1.65)
    c['C4'] = bool(r20 and r20['win_rate'] >= 0.8)
    c['C5'] = repl_ok
    c['C6'] = bool(net_hold and net_hold['ex'] > 0 and net_hold['cagr_diff_excess_basis'] > 0)
    c['C7'] = bool((full and (full['t'] or 0) >= 3.0) or (c7_family_p is not None and c7_family_p < 0.05))
    base = c['C1'] and c['C2'] and c['C6']
    if base and c['C3'] and c['C4'] and c['C7'] and c['C5'] in (None, True):
        g = 'S'
    elif base and c['C4'] and c['C7'] and (c['C3'] or c['C5'] is True):
        g = 'A'
    elif base:
        g = 'B'
    else:
        g = 'C'
    return g, c


# ───────────────────────── 自前の売買の模擬 ─────────────────────────
class U:
    """資産の宇宙: ret[a] = {yyyymm: 超過}, turn[a] = (入れ替え %/年, 片道単価)、mkt・rf、暦"""

    def __init__(self, name, ret, turn, mkt, rf, end, good=None, bad=None):
        self.name, self.ret, self.turn, self.mkt, self.rf = name, ret, turn, mkt, rf
        self.good = good or {}   # 特性 → 良い側の資産名
        self.bad = bad or {}     # 特性 → 悪い側の資産名
        allm = [m for s in ret.values() for m in s]
        self.cal = months(min(allm), min(max(allm), end))
        self.chars = sorted(self.good)


MKT_A = '__MKT__'


def cost_of(u, a):
    if a == MKT_A:
        return 5.0, 0.001
    return u.turn[a]


def ret_of(u, a, m):
    if a == MKT_A:
        return u.mkt.get(m)
    return u.ret[a].get(m)


def run(u, choose, H=1, phase=0, cost_mult=1.0):
    """choose(u, i) → 月末 cal[i] に決める翌月の重み（dict）か None。H=1 毎月・H=3 は (月 % 3 == phase) の月末だけ組み直す。
    戻り値 {'ret': 超過（費用前）, 'cost': 月の費用, 'held': 月→資産の組}"""
    w, started = None, False
    R, C, Hd = {}, {}, {}
    for i in range(len(u.cal) - 1):
        t, n = u.cal[i], u.cal[i + 1]
        if n not in u.mkt or n not in u.rf:
            continue
        reb = H == 1 or (t % 100) % H == phase % H
        if not started and not reb:
            continue
        sw_cost = 0.0
        if reb:
            tgt = choose(u, i)
            if tgt is not None:
                if started:
                    for a in set(tgt) | set(w):
                        dw = abs(tgt.get(a, 0.0) - w.get(a, 0.0))
                        sw_cost += 0.5 * dw * cost_of(u, a)[1]
                w, started = dict(tgt), True
            elif not started:
                continue
        rr = {a: ret_of(u, a, n) for a in w}
        rr = {a: v for a, v in rr.items() if v is not None}
        if len(rr) < len(w):
            tw = sum(w[a] for a in rr)
            if tw <= 0:
                w = {MKT_A: 1.0}
                rr = {MKT_A: u.mkt[n]}
            else:
                w = {a: w[a] / tw for a in rr}
        ex = math.fsum(w[a] * rr[a] for a in rr)
        inner = math.fsum(w[a] * cost_of(u, a)[0] / 100 / 12 * cost_of(u, a)[1] for a in w)
        R[n] = ex
        C[n] = (sw_cost + inner) * cost_mult
        Hd[n] = tuple(sorted(w))
        tot = ex + u.rf[n]
        w = {a: w[a] * (1 + rr[a] + u.rf[n]) / (1 + tot) for a in w}
    return {'ret': R, 'cost': C, 'held': Hd}


def _window_ok(series, cal, j, L):
    if j - L + 1 < 0:
        return None
    vals = []
    for q in range(j - L + 1, j + 1):
        v = series.get(cal[q])
        if v is None:
            return None
        vals.append(v)
    return vals


def ch_cs(L, K, uni=None, minc=30, skip=0, buf=None, score='sum'):
    """横断面: 良い側を過去 L か月の超過の和（score='ir' は良い側−市場の平均÷標準偏差）で順位、上位 K（'q' は ceil(n/4)）"""
    def f(u, i, prev=None):
        n = u.cal[i + 1]
        chars = [k for k in u.chars if uni is None or k in uni]
        KK = math.ceil(len(chars) / 4) if K == 'q' else K
        j = i - skip
        cand = []
        for k in chars:
            a = u.good[k]
            if u.ret[a].get(n) is None:
                continue
            vals = _window_ok(u.ret[a], u.cal, j, L)
            if vals is None:
                continue
            if score == 'sum':
                sc = math.fsum(vals)
            else:
                mk = _window_ok(u.mkt, u.cal, j, L)
                if mk is None:
                    continue
                d = [x - y for x, y in zip(vals, mk)]
                sd = S.stdev(d)
                if sd <= 0:
                    continue
                sc = S.fmean(d) / sd
            cand.append((-sc, k))
        if len(cand) < minc:
            return None
        cand.sort()
        if not buf:
            top = [u.good[k] for _, k in cand[:KK]]
        else:
            rank = {u.good[k]: r for r, (_, k) in enumerate(cand)}
            keep = sorted((a for a in (f.prev or {}) if a in rank and rank[a] < buf * KK), key=lambda a: rank[a])[:KK]
            for _, k in cand:
                if len(keep) >= KK:
                    break
                if u.good[k] not in keep:
                    keep.append(u.good[k])
            top = keep
        wts = {a: 1.0 / len(top) for a in top}
        f.prev = wts
        return wts
    f.prev = None
    return f


def ch_ts(L, kind='ls', uni=None, minc=30, skip=0):
    """時系列: ls = 過去 L か月の (良い−悪い) の複利>0 / lo = 良い側の総リターンの複利>市場の複利。無ければ市場"""
    def f(u, i, prev=None):
        n = u.cal[i + 1]
        j = i - skip
        ok, pick = 0, []
        if kind == 'lo':
            mk = _window_ok(u.mkt, u.cal, j, L)
            if mk is None:
                return None
            rfv = [u.rf.get(u.cal[q]) for q in range(j - L + 1, j + 1)]
            if any(v is None for v in rfv):
                return None
            mprod = math.prod(1 + x + r for x, r in zip(mk, rfv))
        for k in u.chars:
            if uni is not None and k not in uni:
                continue
            g = u.good[k]
            if u.ret[g].get(n) is None:
                continue
            gv = _window_ok(u.ret[g], u.cal, j, L)
            if gv is None:
                continue
            if kind == 'ls':
                bv = _window_ok(u.ret[u.bad[k]], u.cal, j, L)
                if bv is None:
                    continue
                ok += 1
                if math.prod(1 + x - y for x, y in zip(gv, bv)) > 1:
                    pick.append(g)
            else:
                ok += 1
                if math.prod(1 + x + r for x, r in zip(gv, rfv)) > mprod:
                    pick.append(g)
        if ok < minc:
            return None
        if not pick:
            return {MKT_A: 1.0}
        return {a: 1.0 / len(pick) for a in pick}
    return f


def ch_ew(uni=None, minc=30):
    def f(u, i, prev=None):
        n = u.cal[i + 1]
        pick = [u.good[k] for k in u.chars if (uni is None or k in uni) and u.ret[u.good[k]].get(n) is not None]
        if len(pick) < minc:
            return None
        return {a: 1.0 / len(pick) for a in pick}
    return f


def evaluate(sim, u, end=None, extra=True):
    ex = {k: v for k, v in sim['ret'].items() if end is None or k <= end}
    net = {k: ex[k] - sim['cost'][k] for k in ex}
    mk, rf = u.mkt, u.rf
    r = {'start': min(ex), 'end': max(ex),
         'full': stats(ex, mk, rf), 'train': stats(ex, mk, rf, z=TR_END), 'hold': stats(ex, mk, rf, a=H0),
         'net_hold': stats(net, mk, rf, a=H0), 'recent': stats(ex, mk, rf, a=RECENT),
         'roll20': roll20(ex, mk, rf), 'dca20': dca20(ex, mk, rf),
         'cost_pct_per_year_hold': round(S.fmean(sim['cost'][k] for k in ex if k >= H0) * 1200, 3)}
    if extra:
        for mlt in (2.0, 3.0):
            n2 = {k: ex[k] - mlt * sim['cost'][k] for k in ex}
            r[f'net_hold_cost_x{int(mlt)}'] = stats(n2, mk, rf, a=H0)
        r['hold_half1'] = stats(ex, mk, rf, a=H0, z=201606)
        r['hold_half2'] = stats(ex, mk, rf, a=201607)
        r['net_hold_half2'] = stats(net, mk, rf, a=201607)
        r['hold_drop_2020_2021'] = stats(ex, mk, rf, a=H0, drop=lambda k: 202001 <= k <= 202112)
        r['full_drop_1998_2000'] = stats(ex, mk, rf, drop=lambda k: 199801 <= k <= 200012)
        r['full_drop_1998_2000_and_2020_2021'] = stats(ex, mk, rf, drop=lambda k: 199801 <= k <= 200012 or 202001 <= k <= 202112)
        yr = {}
        for k in ex:
            if k >= H0:
                q = yr.setdefault(k // 100, [1.0, 1.0])
                q[0] *= 1 + ex[k] + rf[k]
                q[1] *= 1 + mk[k] + rf[k]
        diffs = {y: round((q[0] - q[1]) * 100, 1) for y, q in sorted(yr.items())}
        best3 = sorted(sorted(diffs, key=lambda y: diffs[y])[-3:])
        r['hold_years_won'] = [sum(1 for v in diffs.values() if v > 0), len(diffs)]
        r['hold_best3_years'] = best3
        r['hold_without_best3_years'] = stats(ex, mk, rf, a=H0, drop=lambda k: k // 100 in best3)
        r['yearly_total_diff_hold'] = diffs
    return r


def short(st):
    return None if not st else [st['ex'], st['t'], st['cagr_diff_excess_basis']]


# ───────────────────────── French の宇宙 ─────────────────────────
# (特性, ファイル, 良い側の列, 悪い側の列, 入れ替え %/年) — 事前登録 prereg2 Q2 / prereg4 F1 の表そのもの
US5 = [('bm', '25_Portfolios_5x5', 'BIG HiBM', 'BIG LoBM', 30),
       ('op', '25_Portfolios_ME_OP_5x5', 'BIG HiOP', 'BIG LoOP', 30),
       ('inv', '25_Portfolios_ME_INV_5x5', 'BIG LoINV', 'BIG HiINV', 50),
       ('mom', '25_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 'BIG LoPRIOR', 150),
       ('str', '25_Portfolios_ME_Prior_1_0', 'BIG LoPRIOR', 'BIG HiPRIOR', 800),
       ('ltr', '25_Portfolios_ME_Prior_60_13', 'BIG LoPRIOR', 'BIG HiPRIOR', 60),
       ('ac', '25_Portfolios_ME_AC_5x5', 'BIG LoAC', 'BIG HiAC', 60),
       ('beta', '25_Portfolios_ME_BETA_5x5', 'BIG LoBETA', 'BIG HiBETA', 50),
       ('ni', '25_Portfolios_ME_NI_5x5', 'BIG NegNI', 'BIG HiNI', 50),
       ('var', '25_Portfolios_ME_VAR_5x5', 'BIG LoVAR', 'BIG HiVAR', 120),
       ('resvar', '25_Portfolios_ME_RESVAR_5x5', 'BIG LoVAR', 'BIG HiVAR', 120)]
ME4_COLS = {'bm': ('ME4 BM5', 'ME4 BM1'), 'op': ('ME4 OP5', 'ME4 OP1'), 'inv': ('ME4 INV1', 'ME4 INV5'),
            'mom': ('ME4 PRIOR5', 'ME4 PRIOR1'), 'str': ('ME4 PRIOR1', 'ME4 PRIOR5'), 'ltr': ('ME4 PRIOR1', 'ME4 PRIOR5'),
            'ac': ('ME4 AC1', 'ME4 AC5'), 'beta': ('ME4 BETA1', 'ME4 BETA5'), 'ni': ('ME4 NegNI', 'ME4 HiNI'),
            'var': ('ME4 VAR1', 'ME4 VAR5'), 'resvar': ('ME4 VAR1', 'ME4 VAR5')}
LOWTO7 = frozenset({'bm', 'op', 'inv', 'ltr', 'ac', 'beta', 'ni'})
REG25 = [('bm', '25_Portfolios_ME_BE-ME', 'BIG HiBM', 'BIG LoBM', 30),
         ('op', '25_Portfolios_ME_OP', 'BIG HiOP', 'BIG LoOP', 30),
         ('inv', '25_Portfolios_ME_INV', 'BIG LoINV', 'BIG HiINV', 50),
         ('mom', '25_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 'BIG LoPRIOR', 150)]
REG_ME4 = {'bm': ('ME4 BM5', 'ME4 BM1'), 'op': ('ME4 OP5', 'ME4 OP1'), 'inv': ('ME4 INV1', 'ME4 INV5'), 'mom': ('ME4 PRIOR5', 'ME4 PRIOR1')}
REG6 = [('bm', '6_Portfolios_ME_BE-ME', 'BIG HiBM', 'BIG LoBM', 25),
        ('op', '6_Portfolios_ME_OP', 'BIG HiOP', 'BIG LoOP', 25),
        ('inv', '6_Portfolios_ME_INV', 'BIG LoINV', 'BIG HiINV', 40),
        ('mom', '6_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 'BIG LoPRIOR', 120)]
US6 = [('bm', '6_Portfolios_2x3', 'BIG HiBM', 'BIG LoBM', 25),
       ('op', '6_Portfolios_ME_OP_2x3', 'BIG HiOP', 'BIG LoOP', 25),
       ('inv', '6_Portfolios_ME_INV_2x3', 'BIG LoINV', 'BIG HiINV', 40),
       ('mom', '6_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 'BIG LoPRIOR', 120),
       ('str', '6_Portfolios_ME_Prior_1_0', 'BIG LoPRIOR', 'BIG HiPRIOR', 700),
       ('ltr', '6_Portfolios_ME_Prior_60_13', 'BIG LoPRIOR', 'BIG HiPRIOR', 50),
       ('ep', '6_Portfolios_ME_EP_2x3', 'BIG HiEP', 'BIG LoEP', 25),
       ('cfp', '6_Portfolios_ME_CFP_2x3', 'BIG HiCFP', 'BIG LoCFP', 25),
       ('dp', '6_Portfolios_ME_DP_2x3', 'BIG HiDP', 'BIG LoDP', 20)]


def build_fr(spec, mkt, rf, prefix='', cost=0.001, colmap=None, name='x', end=FR_END):
    ret, turn, good, bad = {}, {}, {}, {}
    for k, f, gc, bc, to in spec:
        tbl = fr_block(prefix + f, 'Value Weight')
        if colmap:
            gc, bc = colmap[k]
        g, b = tbl[gc], tbl[bc]
        ret['G:' + k] = {m: v - rf[m] for m, v in g.items() if m in rf}
        ret['B:' + k] = {m: v - rf[m] for m, v in b.items() if m in rf}
        turn['G:' + k] = turn['B:' + k] = (float(to), cost)
        good[k], bad[k] = 'G:' + k, 'B:' + k
    return U(name, ret, turn, dict(mkt), dict(rf), end, good, bad)


def fr_universes():
    mk, rf = fr_factors_us()
    uv = {'US5': build_fr(US5, mk, rf, name='US5'),
          'US4': build_fr(US5, mk, rf, colmap=ME4_COLS, name='US4'),
          'US6': build_fr(US6, mk, rf, name='US6')}
    for rg in ['Europe', 'Japan', 'Asia_Pacific_ex_Japan', 'Developed_ex_US']:
        m2, r2 = fr_factors_region(rg)
        uv[rg] = build_fr(REG25, m2, r2, prefix=rg + '_', name=rg)
        uv[rg + '_ME4'] = build_fr(REG25, m2, r2, prefix=rg + '_', colmap=REG_ME4, name=rg + '_ME4')
        uv[rg + '_2x3'] = build_fr(REG6, m2, r2, prefix=rg + '_', name=rg + '_2x3')
    m2, r2 = fr_factors_region('Emerging')
    uv['Emerging'] = build_fr(REG6, m2, r2, prefix='Emerging_Markets_', cost=0.003, name='Emerging')
    return uv


def fr_rule(rule, uni=None, minc=None, L=None, K=None, skip=0):
    """事前登録の規則名 → choose 関数"""
    if rule == 'ts12':
        return ch_ts(L or 12, 'ls', uni, minc, skip)
    if rule == 'ts_lo12':
        return ch_ts(L or 12, 'lo', uni, minc, skip)
    if rule == 'ts1':
        return ch_ts(L or 1, 'ls', uni, minc, skip)
    if rule == 'ew':
        return ch_ew(uni, minc)
    if rule == 'cs':
        return ch_cs(L or 12, K or 'q', uni, minc, skip)
    raise KeyError(rule)


# 検証する French の候補: 名前 → (宇宙, 規則, 特性の絞り, 最低本数, 地域での再現の設定)
FR_CANDS = collections.OrderedDict([
    ('R2b_cs_L12_Kq_me5_lowTO', ('US5', 'cs', LOWTO7, 6)),
    ('Q2b_cs_L12_Kq_me5', ('US5', 'cs', None, 8)),
    ('Q2e_ts1_me5', ('US5', 'ts1', None, 8)),
    ('F2a_ts12_me5_lowTO', ('US5', 'ts12', LOWTO7, 6)),
    ('F2b_ts_lo12_me5_lowTO', ('US5', 'ts_lo12', LOWTO7, 6)),
    ('Q2R_Emerging_ts12', ('Emerging', 'ts12', None, 3)),
    ('Q2R_Emerging_ts_lo12', ('Emerging', 'ts_lo12', None, 3)),
    ('Q2R_Emerging_ew', ('Emerging', 'ew', None, 3)),
    ('Q2R_Emerging_ts1', ('Emerging', 'ts1', None, 3)),
    ('Q2R_Europe_ts1', ('Europe', 'ts1', None, 3)),
    ('Q2R_Developed_ex_US_ts1', ('Developed_ex_US', 'ts1', None, 3)),
    ('Q2R_Europe_ts_lo12', ('Europe', 'ts_lo12', None, 3)),
    ('Q2R_Japan_ts12', ('Japan', 'ts12', None, 3)),
])


def claimed():
    d = json.load(open(os.path.join(BASE, 'out', 'mw_fmom_wf.json')))
    return {r['name']: r for r in d['tested']}, d


def repro_line(nm, r, c):
    """自前の数字と研究者の数字を並べる"""
    def g(x, k):
        return (x or {}).get(k)
    return {'full': [r['full']['ex'], r['full']['t'], g(c.get('full'), 'ex_ann'), g(c.get('full'), 't')],
            'train': [r['train']['ex'], r['train']['t'], g(c.get('train'), 'ex_ann'), g(c.get('train'), 't')] if r['train'] else None,
            'hold': [r['hold']['ex'], r['hold']['t'], g(c.get('hold'), 'ex_ann'), g(c.get('hold'), 't')],
            'hold_cagr_diff': [r['hold']['cagr_diff_excess_basis'], r['hold']['cagr_diff_total_basis'], g(c.get('hold'), 'cagr_diff')],
            'net_hold': [r['net_hold']['ex'], r['net_hold']['t'], g(c.get('net_hold'), 'ex_ann')],
            'roll20': [r['roll20'] and r['roll20']['win_rate'], r['roll20'] and r['roll20']['windows'], g(c.get('roll20'), 'win_rate')],
            'dca20': [r['dca20'] and r['dca20']['win_rate'], r['dca20'] and r['dca20']['median_ratio'], g(c.get('dca20'), 'win_rate'), g(c.get('dca20'), 'median_ratio')]}


def part_fr_repro():
    C, _ = claimed()
    uv = fr_universes()
    out = {}
    for nm, (uk, rule, uni, mc) in FR_CANDS.items():
        u = uv[uk]
        sim = run(u, fr_rule(rule, uni, mc))
        r = evaluate(sim, u)
        out[nm] = r
        rl = repro_line(nm, r, C[nm])
        log(nm, json.dumps(rl, ensure_ascii=False))
    return uv, out




def _selected_sets(sim):
    return sim['held']


def random_null(u, sim, n_draw=2000, seed=11, a=H0):
    """選び方の腕の帰無: 毎月、規則が持った本数と同じ本数を、その月に持てた良い側から無作為に選ぶ（同じ本数・同じ候補）。
    保有期間の算術超過（費用前）の分布の中で、規則の値が上から何%か"""
    import random
    rnd = random.Random(seed)
    ks = [k for k in sorted(sim['ret']) if k >= a]
    # 各月の候補（その月に値のある良い側）と、規則の本数（市場へ逃げた月は市場のまま）
    cands, nsel, mret = {}, {}, {}
    for k in ks:
        held = sim['held'][k]
        cands[k] = [u.good[c] for c in u.chars if u.ret[u.good[c]].get(k) is not None]
        nsel[k] = 0 if held == (MKT_A,) else len(held)
        mret[k] = u.mkt[k]
    real = S.fmean(sim['ret'][k] - u.mkt[k] for k in ks) * 1200
    vals = []
    for _ in range(n_draw):
        tot = 0.0
        for k in ks:
            if nsel[k] == 0:
                continue
            pick = rnd.sample(cands[k], min(nsel[k], len(cands[k])))
            tot += S.fmean(u.ret[a_][k] for a_ in pick) - mret[k]
        vals.append(tot / len(ks) * 1200)
    vals.sort()
    above = sum(1 for v in vals if v >= real)
    return {'real_hold_ex': round(real, 2), 'null_median': round(vals[len(vals) // 2], 2),
            'null_p95': round(vals[int(0.95 * len(vals))], 2), 'p_one_sided': round((above + 1) / (len(vals) + 1), 4),
            'draws': n_draw, 'note': '毎月同じ本数を同じ候補から無作為に（月ごとに独立・漂いなし・費用前）'}


def attribution(u, sim, years):
    """その年の超過（算術・月次の和）を持っていた良い側ごとに分ける"""
    out = {}
    for y in years:
        c = collections.Counter()
        for k, held in sim['held'].items():
            if k // 100 != y:
                continue
            w = 1.0 / len(held)
            for a in held:
                v = ret_of(u, a, k)
                if v is not None:
                    c[a] += w * (v - u.mkt[k]) * 100
        out[y] = {a: round(v, 1) for a, v in c.most_common()}
    return out


def part_fr_refute(uv, base):
    C, _ = claimed()
    res = collections.OrderedDict()
    for nm, (uk, rule, uni, mc) in FR_CANDS.items():
        u = uv[uk]
        r = {'reproduced': base[nm], 'repro_vs_claim': repro_line(nm, base[nm], C[nm])}
        # 1) 直近1か月を飛ばす（ts1 は2か月前の1か月＝ラグ2の信号）
        r['skip1'] = {k: short(v) for k, v in evaluate(run(u, fr_rule(rule, uni, mc, skip=1)), u, extra=False).items()
                      if k in ('full', 'train', 'hold', 'net_hold')}
        # 2) 近いパラメータ（形成期間 L・本数 K）
        grid = []
        Ls = [1, 2, 3] if rule == 'ts1' else [3, 6, 9, 12, 18, 24]
        Ks = [1, 2, 3] if rule == 'cs' else [None]
        for L in Ls:
            for K in Ks:
                rr = evaluate(run(u, fr_rule(rule, uni, mc, L=L, K=K)), u, extra=False)
                grid.append({'L': L, 'K': K, 'train': short(rr['train']), 'hold': short(rr['hold']), 'net_hold': short(rr['net_hold']),
                             'full_t': rr['full']['t']})
        hv = [g['hold'][0] for g in grid if g['hold']]
        r['neighbors'] = {'grid': grid, 'n': len(hv), 'hold_positive': sum(1 for x in hv if x > 0),
                          'hold_t_ge_1_65': sum(1 for g in grid if g['hold'] and (g['hold'][1] or 0) >= 1.65),
                          'net_hold_positive': sum(1 for g in grid if g['net_hold'] and g['net_hold'][0] > 0),
                          'hold_median': round(S.median(hv), 2), 'hold_min': min(hv), 'hold_max': max(hv)}
        # 3) 組み直しの時期: 四半期（3通りの位相）
        q = {}
        for ph in (0, 1, 2):
            rr = evaluate(run(u, fr_rule(rule, uni, mc), H=3, phase=ph), u, extra=False)
            q[f'phase{ph}'] = {'hold': short(rr['hold']), 'net_hold': short(rr['net_hold']), 'full': short(rr['full'])}
        r['quarterly_rebalance'] = q
        # 4) 静的な傾け（同じ良い側の等分）との差＝勢いの選び方の上乗せ
        ew = run(u, ch_ew(uni, mc))
        ew_ev = evaluate(ew, u, extra=False)
        r['static_ew_same_sides'] = {'full': short(ew_ev['full']), 'hold': short(ew_ev['hold']), 'net_hold': short(ew_ev['net_hold'])}
        diff = {k: base_v - ew['ret'][k] for k, base_v in run(u, fr_rule(rule, uni, mc))['ret'].items() if k in ew['ret']}
        zero = {k: 0.0 for k in diff}
        rfz = {k: 0.0 for k in diff}
        r['timing_value_added_vs_static'] = {'full': short(stats(diff, zero, rfz)), 'hold': short(stats(diff, zero, rfz, a=H0)),
                                             'note': '規則 − 同じ良い側の等分（費用前）'}
        # 5) 別の宇宙（隣の規模帯・2×3 の BIG）で同じ規則
        alt = {}
        if uk == 'US5':
            for ak in ('US4',):
                rr = evaluate(run(uv[ak], fr_rule(rule, uni, mc)), uv[ak], extra=False)
                ew4 = evaluate(run(uv[ak], ch_ew(uni, mc)), uv[ak], extra=False)
                alt[ak] = {'hold': short(rr['hold']), 'net_hold': short(rr['net_hold']), 'full': short(rr['full']),
                           'train': short(rr['train']), 'static_ew_hold': short(ew4['hold'])}
        elif uk in ('Europe', 'Japan', 'Asia_Pacific_ex_Japan', 'Developed_ex_US'):
            for ak in (uk + '_ME4', uk + '_2x3'):
                rr = evaluate(run(uv[ak], fr_rule(rule, uni, mc)), uv[ak], extra=False)
                alt[ak] = {'hold': short(rr['hold']), 'net_hold': short(rr['net_hold']), 'full': short(rr['full']), 'train': short(rr['train'])}
        r['other_universe_same_rule'] = alt
        # 6) 無作為に選ぶ帰無（選び方に腕があるか）
        if rule != 'ew':
            r['random_selection_null'] = random_null(u, run(u, fr_rule(rule, uni, mc)))
        # 7) 良い3年の中身
        sim = run(u, fr_rule(rule, uni, mc))
        r['best3_attribution'] = attribution(u, sim, base[nm]['hold_best3_years'])
        res[nm] = r
        log('refute', nm, 'skip1', r['skip1']['hold'], 'grid', {k: v for k, v in r['neighbors'].items() if k != 'grid'},
            'Q', {k: v['hold'] for k, v in q.items()}, 'static', r['static_ew_same_sides']['hold'], 'timing+', r['timing_value_added_vs_static']['hold'],
            'alt', {k: v['hold'] for k, v in alt.items()}, 'null', r.get('random_selection_null'))
    return res


if __name__ == '__main__' and '--fr' in sys.argv:
    uv, base = part_fr_repro()
    res = part_fr_refute(uv, base)
    os.makedirs(SCR, exist_ok=True)
    json.dump(res, open(os.path.join(SCR, 'mwv_fr.json'), 'w'), ensure_ascii=False, indent=1)


def fr_table(name, title):
    """French の zip の中の任意の表（例: 'Number of Firms in Portfolios'）→ {列: {yyyymm: 値(そのまま)}}"""
    b = M.get(M.FR.format(name), name=f'fr_{name}.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    lines = z.read(z.namelist()[0]).decode('latin-1').splitlines()
    for i, l in enumerate(lines):
        if title.lower() in l.lower():
            hdr = [c.strip() for c in lines[i + 1].split(',')]
            out = {}
            for l2 in lines[i + 2:]:
                c = [x.strip() for x in l2.split(',')]
                if not re.match(r'^\d{6}$', c[0]):
                    break
                for h, v in zip(hdr[1:], c[1:]):
                    try:
                        out.setdefault(h, {})[int(c[0])] = float(v)
                    except ValueError:
                        pass
            return out
    return None


def concentration(spec, prefix, sim, u, a=H0):
    """保有期間に持った良い側の銘柄数（月ごと・重みつきの平均と最小）と、年ごとの最小"""
    nf = {}
    for k, f, gc, bc, to in spec:
        t = fr_table(prefix + f, 'Number of Firms in Portfolios')
        if t and gc in t:
            nf['G:' + k] = t[gc]
    per, by_year = [], collections.defaultdict(list)
    for m, held in sim['held'].items():
        if m < a:
            continue
        ns = [nf[x].get(m) for x in held if x in nf and nf[x].get(m) is not None]
        if ns:
            per.append((m, min(ns), S.fmean(ns)))
            by_year[m // 100].append(min(ns))
    if not per:
        return None
    return {'hold_mean_of_avg_firms_held': round(S.fmean(p[2] for p in per), 1),
            'hold_min_firms_in_a_held_portfolio': min(p[1] for p in per),
            'min_by_year': {y: min(v) for y, v in sorted(by_year.items())}}


# ───────────────────────── JKP（米国 Q1・各国パネル） ─────────────────────────
_FUS = json.load(open(os.path.join(BASE, 'out', 'mw_factor_us_prereg.json')))['families']['a_jkp_tercile_vw']['list']
JK_TURN = {x['key']: (float(x['turnover_pct']), float(x['cost_per_100pct'])) for x in _FUS}
JK_DIR = {x['key']: int(x['jkp_direction']) for x in _FUS}
JK_PUB = {x['key']: x['pub_year'] for x in _FUS}
JK_CHARS = sorted(JK_TURN)
JK_LOWTO = frozenset(k for k in JK_CHARS if JK_TURN[k][0] <= 100)
JK_PRE2007 = frozenset(k for k in JK_CHARS if JK_PUB[k] is not None and JK_PUB[k] <= 2006)
_CL = {}


def jk_cluster():
    if not _CL:
        import csv
        txt = M.get('https://raw.githubusercontent.com/bkelly-lab/ReplicationCrisis/master/GlobalFactors/Cluster%20Labels.csv',
                    name='jkp_cluster_labels.csv').decode()
        for r in csv.DictReader(io.StringIO(txt)):
            _CL[r['characteristic']] = r['cluster']
    return _CL


def _ym(s):
    return int(s[:4]) * 100 + int(s[5:7])


def jk_load_country(region, nmin=10):
    """{(特性, '1.0'|'2.0'|'3.0'): {yyyymm: 超過}}（銘柄数 n<nmin の月は欠測）。scratchpad に pickle で置く"""
    p = os.path.join(SCR, f'mwv_jk_{region}.pkl')
    if os.path.exists(p):
        return pickle.load(open(p, 'rb'))
    d = {}
    avail = set(json.load(open(os.path.join(M.CACHE, 'jkp_availability.json')))['portfolios'].get(region, []))
    for k in JK_CHARS:
        if k not in avail:
            continue   # 公開されていない特性は取りに行かない（取得失敗の再試行で止まらないように）
        try:
            rows = M.jkp_rows(region, k, 'portfolios', 'vw')
        except Exception:
            continue
        for x in rows:
            if x['pf'] not in ('1.0', '2.0', '3.0') or x['ret'] in ('', 'NA', 'na'):
                continue
            n = x.get('n')
            if n not in (None, '', 'NA', 'na') and float(n) < nmin:
                continue
            d.setdefault((k, x['pf']), {})[_ym(x['date'])] = float(x['ret'])
    mk = {}
    avf = json.load(open(os.path.join(M.CACHE, 'jkp_availability.json')))['factors']
    try:
        if 'mkt' not in (avf.get(region) or []):
            raise KeyError('no mkt')
        for x in M.jkp_rows(region, 'mkt', 'factor', 'vw'):
            if x['ret'] not in ('', 'NA', 'na'):
                mk[_ym(x['date'])] = float(x['ret'])
    except Exception:
        pass
    obj = {'pf': d, 'mkt': mk}
    os.makedirs(SCR, exist_ok=True)
    pickle.dump(obj, open(p, 'wb'))
    return obj


def jk_universe(region, mkt, rf, chars=None, swap=False, mid=False, nmin=10):
    obj = jk_load_country(region, nmin)
    ret, turn, good, bad = {}, {}, {}, {}
    for k in (chars or JK_CHARS):
        g_pf = '3.0' if JK_DIR[k] > 0 else '1.0'
        b_pf = '1.0' if JK_DIR[k] > 0 else '3.0'
        if swap:
            g_pf, b_pf = b_pf, g_pf
        if mid:
            g_pf = '2.0'
        g, b = obj['pf'].get((k, g_pf)), obj['pf'].get((k, b_pf))
        if not g:
            continue
        ret['G:' + k] = g
        ret['B:' + k] = b or {}
        turn['G:' + k] = turn['B:' + k] = JK_TURN[k]
        good[k], bad[k] = 'G:' + k, 'B:' + k
    if not ret:
        return None
    return U(region, ret, turn, dict(mkt), dict(rf), JKP_END, good, bad)


JK_RULES = {'Q1a_cs_L12_K10_H1_lowTO': lambda skip=0, uni=JK_LOWTO: ch_cs(12, 10, uni, 30, skip),
            'Q1b_cs_L12_K10_H1_lowTO_buf20': lambda skip=0, uni=JK_LOWTO: ch_cs(12, 10, uni, 30, skip, buf=2),
            'Q1c_ts12_lowTO': lambda skip=0, uni=JK_LOWTO: ch_ts(12, 'ls', uni, 30, skip),
            'P2_ts12': lambda skip=0, uni=None: ch_ts(12, 'ls', uni, 30, skip),
            'P3_ew_all': lambda skip=0, uni=None: ch_ew(uni, 30)}
PANEL_OF = {'R1a_panel_Q1b': 'Q1b_cs_L12_K10_H1_lowTO_buf20', 'R1b_panel_Q1c': 'Q1c_ts12_lowTO',
            'Q3_panel_P2_ts12': 'P2_ts12', 'Q3_panel_P3_ew_all': 'P3_ew_all'}


def part_jk_us():
    C, _ = claimed()
    mk, rf = fr_factors_us()
    u = jk_universe('usa', mk, rf)
    res = collections.OrderedDict()
    for nm in ('Q1a_cs_L12_K10_H1_lowTO', 'Q1b_cs_L12_K10_H1_lowTO_buf20', 'Q1c_ts12_lowTO'):
        sim = run(u, JK_RULES[nm]())
        base = evaluate(sim, u)
        r = {'reproduced': base, 'repro_vs_claim': repro_line(nm, base, C[nm])}
        for mlt in (1.5,):
            n2 = {k: sim['ret'][k] - mlt * sim['cost'][k] for k in sim['ret']}
            r['net_hold_cost_x1_5'] = short(stats(n2, u.mkt, u.rf, a=H0))
        s1 = run(u, JK_RULES[nm](skip=1))
        r['skip1'] = {k: short(v) for k, v in evaluate(s1, u, extra=False).items() if k in ('full', 'train', 'hold', 'net_hold')}
        # 2006年までに公表された特性だけ（良い側の向きに後の知識が混ざらない版）
        s2 = run(u, JK_RULES[nm](uni=JK_LOWTO & JK_PRE2007))
        r['pre2007_published_only'] = {k: short(v) for k, v in evaluate(s2, u, extra=False).items() if k in ('full', 'train', 'hold', 'net_hold')}
        # 悪い側で同じ規則（偽薬）: 悪い側にも勝ちが出るなら、勝ちは『良い側』ではなく宇宙の食い違い
        ub = jk_universe('usa', mk, rf, swap=True)
        s3 = run(ub, JK_RULES[nm]())
        r['placebo_same_rule_on_bad_sides'] = {k: short(v) for k, v in evaluate(s3, ub, extra=False).items() if k in ('full', 'hold', 'net_hold')}
        res[nm] = r
        log('JK-US', nm, json.dumps(r['repro_vs_claim'], ensure_ascii=False), 'x1.5', r['net_hold_cost_x1_5'], 'skip1', r['skip1']['hold'],
            'pre2007', r['pre2007_published_only']['hold'], r['pre2007_published_only']['net_hold'], 'placebo_bad', r['placebo_same_rule_on_bad_sides']['hold'])
    # 偽薬: 良い側・中・悪い側の等分（112特性）
    pl = {}
    for lab, kw in (('good', {}), ('middle', {'mid': True}), ('bad', {'swap': True})):
        uu = jk_universe('usa', mk, rf, chars=sorted(JK_LOWTO), **kw)
        ev = evaluate(run(uu, ch_ew(None, 30)), uu, extra=False)
        pl[lab] = {'full': short(ev['full']), 'hold': short(ev['hold'])}
    res['_placebo_ew_lowTO_terciles_us'] = pl
    log('JK-US placebo ew terciles', pl)
    return res


if __name__ == '__main__' and '--jkus' in sys.argv:
    r = part_jk_us()
    json.dump(r, open(os.path.join(SCR, 'mwv_jkus.json'), 'w'), ensure_ascii=False, indent=1)


PANEL_EXCL = {'all_countries', 'all_regions', 'developed', 'emerging', 'frontier', 'world', 'world_ex_us', 'usa', 'jpn'}
DEV21 = {'aus', 'aut', 'bel', 'can', 'che', 'deu', 'dnk', 'esp', 'fin', 'fra', 'gbr', 'hkg', 'irl', 'isr', 'ita', 'nld', 'nor', 'nzl', 'prt', 'sgp', 'swe'}
BIG_EM = {'chn', 'ind', 'kor', 'twn', 'bra', 'zaf', 'mex', 'sau', 'tha', 'mys', 'idn'}


def countries():
    av = json.load(open(os.path.join(M.CACHE, 'jkp_availability.json')))
    return sorted(c for c in av['portfolios'] if c not in PANEL_EXCL)


def panel_run(rule_fn, chars=None, swap=False, mid=False, cset=None, min_hold=120, rf=None):
    """各国で規則を回し（保有期間に min_hold か月以上ある国だけ）、国々の等分パネルを作る"""
    sims, us = {}, {}
    for c in countries():
        if cset is not None and c not in cset:
            continue
        obj = jk_load_country(c)
        if not obj['mkt']:
            continue
        u = jk_universe(c, obj['mkt'], rf, chars=chars, swap=swap, mid=mid)
        if u is None:
            continue
        sim = run(u, rule_fn())
        nh = sum(1 for m in sim['ret'] if H0 <= m <= JKP_END)
        if nh < min_hold:
            continue
        sims[c], us[c] = sim, u
    return sims, us


def panel_series(sims, us, rf, cost_mult=1.0, cost_by_country=None):
    s, b, sn = {}, {}, {}
    ms = sorted(set().union(*[set(x['ret']) for x in sims.values()])) if sims else []
    for m in ms:
        cs = [c for c in sims if m in sims[c]['ret'] and m in us[c].mkt and m in rf]
        if not cs:
            continue
        s[m] = S.fmean(sims[c]['ret'][m] for c in cs)
        b[m] = S.fmean(us[c].mkt[m] for c in cs)
        sn[m] = S.fmean(sims[c]['ret'][m] - (cost_by_country.get(c, cost_mult) if cost_by_country else cost_mult) * sims[c]['cost'][m] for c in cs)
    return s, b, sn


def panel_eval(sims, us, rf, extra=True):
    s, b, sn = panel_series(sims, us, rf)
    r = {'n_countries': len(sims), 'start': min(s), 'end': max(s),
         'full': stats(s, b, rf), 'train': stats(s, b, rf, z=TR_END), 'hold': stats(s, b, rf, a=H0),
         'net_hold': stats(sn, b, rf, a=H0), 'roll20': roll20(s, b, rf), 'dca20': dca20(s, b, rf)}
    if extra:
        for mlt in (2.0, 3.0):
            _, _, s2 = panel_series(sims, us, rf, mlt)
            r[f'net_hold_cost_x{int(mlt)}'] = stats(s2, b, rf, a=H0)
        tier = {c: (1.0 if c in DEV21 else 3.0) for c in sims}
        _, _, s3 = panel_series(sims, us, rf, cost_by_country=tier)
        r['net_hold_cost_dev_x1_others_x3'] = stats(s3, b, rf, a=H0)
        r['hold_half1'] = stats(s, b, rf, a=H0, z=201606)
        r['hold_half2'] = stats(s, b, rf, a=201607)
        r['net_hold_half2'] = stats(sn, b, rf, a=201607)
        r['hold_drop_2020_2021'] = stats(s, b, rf, a=H0, drop=lambda k: 202001 <= k <= 202112)
        r['full_drop_1998_2000'] = stats(s, b, rf, drop=lambda k: 199801 <= k <= 200012)
        per = {}
        for c in sims:
            h = stats(sims[c]['ret'], us[c].mkt, rf, a=H0)
            n1 = {k: sims[c]['ret'][k] - sims[c]['cost'][k] for k in sims[c]['ret']}
            hn = stats(n1, us[c].mkt, rf, a=H0)
            per[c] = [h and h['ex'], hn and hn['ex']]
        r['countries_hold_positive'] = [sum(1 for v in per.values() if v[0] and v[0] > 0), len(per)]
        r['countries_net_hold_positive'] = [sum(1 for v in per.values() if v[1] and v[1] > 0), len(per)]
        r['per_country_hold_net'] = per
        # 1次の自己相関（古い値段・薄商いの疑い）
        ks = sorted(k for k in s if k >= H0)
        d = [s[k] - b[k] for k in ks]
        mu = S.fmean(d)
        r['hold_excess_autocorr1'] = round(math.fsum((d[i] - mu) * (d[i - 1] - mu) for i in range(1, len(d))) / math.fsum((x - mu) ** 2 for x in d), 3)
    return r


def part_panels():
    C, _ = claimed()
    _, rf = fr_factors_us()
    res = collections.OrderedDict()
    cl = jk_cluster()
    no_size = frozenset(k for k in JK_CHARS if cl.get(k) != 'Size')
    for nm, rk in PANEL_OF.items():
        uni0 = JK_LOWTO if 'lowTO' in rk else None
        t0 = time.time()
        sims, us = panel_run(lambda: JK_RULES[rk](), rf=rf)
        base = panel_eval(sims, us, rf)
        r = {'reproduced': {k: v for k, v in base.items() if k != 'per_country_hold_net'}, 'per_country_hold_net': base['per_country_hold_net']}
        c = C[nm]
        r['repro_vs_claim'] = {'n_countries': [base['n_countries'], c.get('n_countries')],
                               'full': [base['full']['ex'], base['full']['t'], c['full']['ex_ann'], c['full']['t']],
                               'train': [base['train']['ex'], base['train']['t'], c['train']['ex_ann'], c['train']['t']],
                               'hold': [base['hold']['ex'], base['hold']['t'], c['hold']['ex_ann'], c['hold']['t']],
                               'hold_cagr_diff': [base['hold']['cagr_diff_excess_basis'], base['hold']['cagr_diff_total_basis'], c['hold']['cagr_diff']],
                               'net_hold': [base['net_hold']['ex'], c['net_hold']['ex_ann']],
                               'roll20': [base['roll20']['win_rate'], c['roll20']['win_rate']], 'dca20': [base['dca20']['win_rate'], base['dca20']['median_ratio'], c['dca20']['median_ratio']]}
        log('PANEL', nm, json.dumps(r['repro_vs_claim']), f'{time.time() - t0:.0f}s')
        tests = {}
        if rk != 'P3_ew_all':
            s1, u1 = panel_run(lambda: JK_RULES[rk](skip=1), rf=rf)
            tests['skip1'] = panel_eval(s1, u1, rf, extra=False)
        uni_pre = (uni0 & JK_PRE2007) if uni0 else JK_PRE2007
        s2, u2 = panel_run(lambda: JK_RULES[rk](uni=uni_pre), rf=rf)
        tests['pre2007_published_only'] = panel_eval(s2, u2, rf, extra=False)
        uni_ns = (uni0 & no_size) if uni0 else no_size
        s3, u3 = panel_run(lambda: JK_RULES[rk](uni=uni_ns), rf=rf)
        tests['no_size_cluster'] = panel_eval(s3, u3, rf, extra=False)
        s4, u4 = panel_run(lambda: JK_RULES[rk](), swap=True, rf=rf)
        tests['placebo_same_rule_on_bad_sides'] = panel_eval(s4, u4, rf, extra=False)
        for lab, cs_ in (('developed21', DEV21), ('big_em11', BIG_EM), ('rest_frontier_small_em', None)):
            if cs_ is None:
                keep = {c: sims[c] for c in sims if c not in DEV21 and c not in BIG_EM}
            else:
                keep = {c: sims[c] for c in sims if c in cs_}
            tests['subset_' + lab] = panel_eval(keep, {c: us[c] for c in keep}, rf, extra=False) if keep else None
            if tests['subset_' + lab]:
                tests['subset_' + lab]['countries'] = sorted(keep)
        r['tests'] = {k: ({kk: (short(vv) if isinstance(vv, dict) and 'ex' in vv else vv) for kk, vv in v.items()} if v else None) for k, v in tests.items()}
        res[nm] = r
        log('PANEL-T', nm, {k: (v and short(v.get('hold')), v and short(v.get('net_hold')), v and v.get('n_countries')) for k, v in tests.items()})
    # 偽薬: 全153特性の良い側・中・悪い側の等分（P3 型）を各国で
    pl = {}
    for lab, kw in (('good', {}), ('middle', {'mid': True}), ('bad', {'swap': True})):
        sp, up = panel_run(lambda: ch_ew(None, 30), rf=rf, **kw)
        ev = panel_eval(sp, up, rf, extra=False)
        pl[lab] = {'n': ev['n_countries'], 'full': short(ev['full']), 'train': short(ev['train']), 'hold': short(ev['hold'])}
    res['_placebo_ew_terciles_panel_all153'] = pl
    log('PANEL placebo', pl)
    pl2 = {}
    for lab, kw in (('good', {}), ('middle', {'mid': True}), ('bad', {'swap': True})):
        sp, up = panel_run(lambda: ch_ew(None, 30), chars=sorted(JK_LOWTO), rf=rf, **kw)
        ev = panel_eval(sp, up, rf, extra=False)
        pl2[lab] = {'n': ev['n_countries'], 'full': short(ev['full']), 'train': short(ev['train']), 'hold': short(ev['hold'])}
    res['_placebo_ew_terciles_panel_lowTO112'] = pl2
    log('PANEL placebo lowTO', pl2)
    return res


if __name__ == '__main__' and '--panels' in sys.argv:
    r = part_panels()
    json.dump(r, open(os.path.join(SCR, 'mwv_panels.json'), 'w'), ensure_ascii=False, indent=1)


def swap_u(u):
    """良い側と悪い側を入れ替えた宇宙（偽薬）"""
    return U(u.name + '_swap', u.ret, u.turn, u.mkt, u.rf, max(u.cal), dict(u.bad), dict(u.good))


def mid_row_universe(spec, mkt, rf, prefix, cost, midcols, name):
    """BIG 行の中の真ん中（2×3 は ME2 xx2、5×5 は ME5 xx3）を『良い側』に置いた宇宙（偽薬用）"""
    ret, turn, good, bad = {}, {}, {}, {}
    for k, f, gc, bc, to in spec:
        tbl = fr_block(prefix + f, 'Value Weight')
        col = midcols(k, tbl)
        if col is None:
            continue
        ret['G:' + k] = {m: v - rf[m] for m, v in tbl[col].items() if m in rf}
        ret['B:' + k] = {m: v - rf[m] for m, v in tbl[bc].items() if m in rf}
        turn['G:' + k] = turn['B:' + k] = (float(to), cost)
        good[k], bad[k] = 'G:' + k, 'B:' + k
    return U(name, ret, turn, dict(mkt), dict(rf), FR_END, good, bad)


def part_fr_placebo(uv):
    """偽薬: 同じ BIG 行の悪い側・真ん中を等分に持っても市場に勝つなら、勝ちは『良い側』ではなく宇宙の食い違い（規模・データの有無）"""
    out = {}
    for uk, spec, prefix, cost in (('US5', US5, '', 0.001), ('Emerging', REG6, 'Emerging_Markets_', 0.003),
                                   ('Europe', REG25, 'Europe_', 0.001), ('Developed_ex_US', REG25, 'Developed_ex_US_', 0.001),
                                   ('Japan', REG25, 'Japan_', 0.001)):
        u = uv[uk]
        mk, rf = u.mkt, u.rf
        r = {}
        for lab, uu in (('good', u), ('bad', swap_u(u))):
            ev = evaluate(run(uu, ch_ew(None, 3)), uu, extra=False)
            r['ew_' + lab] = {'full': short(ev['full']), 'train': short(ev['train']), 'hold': short(ev['hold'])}

        def midc(k, tbl):
            cands = [c for c in tbl if c.startswith('ME2 ') or c.startswith('ME5 ')]
            if uk == 'US5' or prefix.endswith('_') and 'Emerging' not in prefix:
                want = [c for c in cands if c.startswith('ME5 ') and c.endswith('3')]
            else:
                want = [c for c in cands if c.startswith('ME2 ') and c.endswith('2')]
            return want[0] if want else None
        um = mid_row_universe(spec, mk, rf, prefix, cost, midc, uk + '_mid')
        ev = evaluate(run(um, ch_ew(None, 3)), um, extra=False)
        r['ew_middle'] = {'full': short(ev['full']), 'train': short(ev['train']), 'hold': short(ev['hold']), 'chars': um.chars}
        out[uk] = r
        log('FR placebo', uk, r)
    return out


def part_fr_mirror(uv):
    """同じ規則を悪い側に当てた偽薬（ts12・ts1・ts_lo12・cs）"""
    out = {}
    for nm, (uk, rule, uni, mc) in FR_CANDS.items():
        u = swap_u(uv[uk])
        ev = evaluate(run(u, fr_rule(rule, uni, mc)), u, extra=False)
        out[nm] = {'full': short(ev['full']), 'hold': short(ev['hold']), 'net_hold': short(ev['net_hold'])}
        log('FR mirror', nm, out[nm])
    return out


if __name__ == '__main__' and '--frplacebo' in sys.argv:
    uv = fr_universes()
    r = {'placebo_ew': part_fr_placebo(uv), 'mirror_rule_on_bad_sides': part_fr_mirror(uv)}
    json.dump(r, open(os.path.join(SCR, 'mwv_frplacebo.json'), 'w'), ensure_ascii=False, indent=1)


FR4_JK = ['be_me', 'ope_be', 'at_gr1', 'ret_12_1']   # French の4特性（BE/ME・OP・INV・Prior 12-2）に当たる JKP の特性


def part_jk_region_repl():
    """別の業者（JKP・Compustat 系）の地域データで、French の地域の規則（4特性）を作り直す＝独立の答え合わせ"""
    _, rf = fr_factors_us()
    out = {}
    for reg in ('emerging', 'developed', 'world_ex_us'):
        obj = jk_load_country(reg)
        u = jk_universe(reg, obj['mkt'], rf, chars=FR4_JK)
        r = {}
        for rule in ('ts12', 'ts_lo12', 'ew', 'ts1'):
            ev = evaluate(run(u, fr_rule(rule, None, 3)), u, extra=False)
            r[rule] = {'start': ev['start'], 'full': short(ev['full']), 'train': short(ev['train']), 'hold': short(ev['hold']),
                       'net_hold': short(ev['net_hold']), 'roll20_win': ev['roll20'] and ev['roll20']['win_rate']}
        out[reg] = r
        log('JK region repl', reg, {k: (v['hold'], v['net_hold']) for k, v in r.items()})
    return out


if __name__ == '__main__' and '--jkreg' in sys.argv:
    r = part_jk_region_repl()
    json.dump(r, open(os.path.join(SCR, 'mwv_jkreg.json'), 'w'), ensure_ascii=False, indent=1)


# ───────────────────────── 税（日本の課税口座・報告のみ） ─────────────────────────
def after_tax_cagr(tot, a, z, realize_annually, rate=0.20315, carry_years=3):
    """総リターン {yyyymm: r} を a〜z で複利。realize_annually=True は毎年末に1年分の利益を実現して課税（損は3年繰越）、
    False は最後に一度だけ課税（買って持つだけ）。回転の大きい戦略の上限側の近似"""
    ks = [k for k in sorted(tot) if a <= k <= z]
    if len(ks) < 24:
        return None
    W, basis, carry = 1.0, 1.0, []
    by_year = collections.OrderedDict()
    for k in ks:
        by_year.setdefault(k // 100, []).append(k)
    for y, mm in by_year.items():
        w0 = W
        for k in mm:
            W *= 1 + tot[k]
        if realize_annually:
            g = W - w0
            carry = [(yy, l) for yy, l in carry if y - yy <= carry_years]
            if g > 0:
                use = 0.0
                new = []
                for yy, l in carry:
                    t = min(l, g - use)
                    use += t
                    if l - t > 1e-15:
                        new.append((yy, l - t))
                carry = new
                W -= rate * (g - use)
            elif g < 0:
                carry.append((y, -g))
    if not realize_annually and W > basis:
        W -= rate * (W - basis)
    return math.exp(math.log(W) * 12 / len(ks)) - 1


def tax_view(net_ex, mk, rf, a=H0, z=None):
    """戦略（費用後・毎年実現）と市場（買って持つだけ・最後に課税）の税引き後 CAGR の差"""
    z = z or max(net_ex)
    s = {k: net_ex[k] + rf[k] for k in net_ex if k in rf}
    b = {k: mk[k] + rf[k] for k in mk if k in rf}
    ks = [k for k in sorted(s) if k in b and a <= k <= z]
    s2 = {k: s[k] for k in ks}
    b2 = {k: b[k] for k in ks}
    pre = (geo(list(s2.values())) - geo(list(b2.values()))) * 100
    st = after_tax_cagr(s2, ks[0], ks[-1], True)
    bt = after_tax_cagr(b2, ks[0], ks[-1], False)
    return {'window': [ks[0], ks[-1]], 'pre_tax_cagr_diff_net_of_cost': round(pre, 2), 'after_tax_cagr_diff': round((st - bt) * 100, 2),
            'note': '日本の課税口座 20.315%。戦略は毎年の利益を全部実現（損は3年繰越）、市場は最後に一度だけ課税。NISA なら差は税引き前と同じ'}


def part_panel_capweighted():
    """パネルの規則を JKP の地域（時価加重の地域の市場が相手）でそのまま回す＝事前登録の相手（同じ地域の時価加重）での答え合わせ"""
    _, rf = fr_factors_us()
    out = {}
    for nm, rk in PANEL_OF.items():
        r = {}
        for reg in ('world_ex_us', 'developed', 'emerging'):
            obj = jk_load_country(reg)
            u = jk_universe(reg, obj['mkt'], rf)
            sim = run(u, JK_RULES[rk]())
            ev = evaluate(sim, u, extra=False)
            s1 = evaluate(run(u, JK_RULES[rk](skip=1)), u, extra=False) if rk != 'P3_ew_all' else None
            um = jk_universe(reg, obj['mkt'], rf, mid=True)
            mid = evaluate(run(um, ch_ew(JK_LOWTO if 'lowTO' in rk else None, 30)), um, extra=False)
            n2 = {k: sim['ret'][k] - 2 * sim['cost'][k] for k in sim['ret']}
            r[reg] = {'start': ev['start'], 'full': short(ev['full']), 'train': short(ev['train']), 'hold': short(ev['hold']),
                      'net_hold': short(ev['net_hold']), 'net_hold_cost_x2': short(stats(n2, u.mkt, u.rf, a=H0)),
                      'roll20_win': ev['roll20'] and ev['roll20']['win_rate'], 'skip1_hold': s1 and short(s1['hold']),
                      'placebo_middle_tercile_ew_hold': short(mid['hold']),
                      'grade_letter': grade(ev['full'], ev['train'], ev['hold'], ev['roll20'], ev['net_hold'], None)[0]}
        out[nm] = r
        log('PANEL→region cap-weighted', nm, {k: (v['hold'], v['net_hold'], v['grade_letter']) for k, v in r.items()})
    return out


if __name__ == '__main__' and '--panelcw' in sys.argv:
    r = part_panel_capweighted()
    json.dump(r, open(os.path.join(SCR, 'mwv_panelcw.json'), 'w'), ensure_ascii=False, indent=1)


# ───────────────────────── 現実の答え合わせ（新興国）・多重検定 ─────────────────────────
def part_em_reality():
    """French の新興国の市場（相手）が弱くないか、実在の新興国ファンドと比べる（Yahoo・生き残りのみ・報告だけ）"""
    mk, rf = fr_factors_region('Emerging')
    em = {m: mk[m] + rf[m] for m in mk}
    out = {}

    def cmp(a, b, lo, hi):
        ks = sorted(k for k in a if k in b and lo <= k <= hi)
        if len(ks) < 24:
            return None
        return {'from': ks[0], 'to': ks[-1], 'cagr_a': round(geo([a[k] for k in ks]) * 100, 2), 'cagr_b': round(geo([b[k] for k in ks]) * 100, 2),
                'diff': round((geo([a[k] for k in ks]) - geo([b[k] for k in ks])) * 100, 2)}
    try:
        Y = {t: M.yahoo(t) for t in ('VEIEX', 'EEM', 'DFEVX', 'DFEMX')}
    except Exception as e:  # noqa
        return {'error': str(e)}
    out['french_EM_mkt_vs_VEIEX_hold'] = cmp(em, Y['VEIEX'], H0, FR_END)
    out['french_EM_mkt_vs_EEM_hold'] = cmp(em, Y['EEM'], H0, FR_END)
    out['DFEVX_EMvalue_fund_vs_VEIEX_hold'] = cmp(Y['DFEVX'], Y['VEIEX'], H0, FR_END)
    out['DFEVX_EMvalue_fund_vs_french_EM_mkt_hold'] = cmp(Y['DFEVX'], em, H0, FR_END)
    out['DFEMX_EMcore_fund_vs_french_EM_mkt_hold'] = cmp(Y['DFEMX'], em, H0, FR_END)
    out['note'] = 'French の新興国の市場は 2007〜 で実在の指数ファンド（VEIEX・EEM）より年1.5〜1.8%強い＝相手は弱くない。実在の新興国バリューのファンド（DFA）はその French の市場にほぼ並ぶだけ'
    log('EM reality', out)
    return out


def part_multiple_testing():
    _, d = claimed()
    T = d['tested']
    ph = {r['name']: (r['hold'] or {}).get('p') for r in T}
    pf = {r['name']: pnorm2((r['full'] or {}).get('t')) for r in T}
    from statistics import NormalDist
    N = NormalDist()
    return {'n_graded_in_angle': len(T), 'plus_param_grid_cells_reported': 42,
            'bonferroni_t_70': round(N.inv_cdf(1 - 0.025 / 70), 2), 'bonferroni_t_112': round(N.inv_cdf(1 - 0.025 / 112), 2),
            'holm70_hold': holm(ph), 'holm70_full': holm(pf),
            'note': 'C7 は「全期間 t≥3.0 か族の中の Holm」。角度全体（70本）で全期間の p に Holm を掛けると、3.0 ぎりぎりの規則は落ちる'}


# ───────────────────────── 判定（自前の数字から） ─────────────────────────
def repl_c5(nm, uv):
    """C5（地域での再現）を自前で数える。French は事前登録どおりの地域・特性、JKP 米国は4地域、パネルは N/A"""
    if nm in PANEL_OF:
        return None
    if nm.startswith('Q1'):
        mk, rf = fr_factors_us()
        pos, det = 0, {}
        for reg in ('world_ex_us', 'developed', 'emerging', 'jpn'):
            obj = jk_load_country(reg)
            u = jk_universe(reg, obj['mkt'], rf)
            ev = evaluate(run(u, JK_RULES[nm]()), u, extra=False)
            det[reg] = short(ev['full'])
            pos += 1 if ev['full']['ex'] > 0 else 0
        return {'regions': 4, 'positive': pos, 'detail': det}
    uk, rule, uni, mc = FR_CANDS[nm]
    if uk == 'US5':
        regs = ['Europe', 'Japan', 'Asia_Pacific_ex_Japan']
        runi = frozenset({'bm', 'op', 'inv'}) if uni else None
        pos, det = 0, {}
        for rg in regs:
            ev = evaluate(run(uv[rg], fr_rule(rule, runi, 3)), uv[rg], extra=False)
            det[rg] = short(ev['full'])
            pos += 1 if ev['full']['ex'] > 0 else 0
        return {'regions': 3, 'positive': pos, 'detail': det}
    others = {'Europe': ['Japan', 'Asia_Pacific_ex_Japan', 'Emerging', 'US5'], 'Japan': ['Europe', 'Asia_Pacific_ex_Japan', 'Emerging', 'US5'],
              'Emerging': ['Europe', 'Japan', 'Asia_Pacific_ex_Japan', 'US5'], 'Developed_ex_US': ['Emerging', 'US5']}[uk]
    pos, det = 0, {}
    for rg in others:
        ev = evaluate(run(uv[rg], fr_rule(rule, None, 8 if rg == 'US5' else 3)), uv[rg], extra=False)
        det[rg] = short(ev['full'])
        pos += 1 if ev['full']['ex'] > 0 else 0
    return {'regions': len(others), 'positive': pos, 'detail': det}


def hibm_2026():
    mk, rf = fr_factors_us()
    g = fr_block('25_Portfolios_5x5', 'Value Weight')['BIG HiBM']
    ms = [m for m in sorted(mk) if m // 100 == 2026 and m in g]
    nf = fr_table('25_Portfolios_5x5', 'Number of Firms in Portfolios')['BIG HiBM']
    return {'months': len(ms), 'big_hibm': round((math.prod(1 + g[m] for m in ms) - 1) * 100, 1),
            'mkt': round((math.prod(1 + mk[m] + rf[m] for m in ms) - 1) * 100, 1),
            'firms_min_max': [min(nf[m] for m in ms), max(nf[m] for m in ms)]}


def verdicts(R, uv):
    fr, jus, pan, pcw, jreg, plc, mt, em = (R['french'], R['jkp_us'], R['panels'], R['panel_capweighted'], R['jkp_region_replication'],
                                             R['french_placebo'], R['multiple_testing'], R['em_reality'])
    h70f, h70h = mt['holm70_full'], mt['holm70_hold']
    C, _ = claimed()
    out = collections.OrderedDict()

    def sh(x):
        return '—' if not x else f"{x[0]:+.2f}(t{x[1]})"

    def base_nums(b):
        return (f"全期間 {b['full']['ex']:+.2f}%/年 t{b['full']['t']}・訓練 {b['train']['ex']:+.2f} t{b['train']['t']}・保有 {b['hold']['ex']:+.2f} t{b['hold']['t']}"
                f"・CAGR差 {b['hold']['cagr_diff_excess_basis']:+.2f}（総リターン基準 {b['hold']['cagr_diff_total_basis']:+.2f}）・費用後 {b['net_hold']['ex']:+.2f} t{b['net_hold']['t']}"
                f"・20年窓 {b['roll20']['wins']}/{b['roll20']['windows']}・20年積立 勝率{b['dca20']['win_rate']} 中央{b['dca20']['median_ratio']}")

    def tax_line(nm):
        tv = fr[nm].get('tax_japan_taxable')
        return f"税（日本の課税口座・毎年すべて実現する近似）: 費用後の CAGR 差 {tv['pre_tax_cagr_diff_net_of_cost']:+.2f} → 税引き後 {tv['after_tax_cagr_diff']:+.2f}%/年" if tv else None

    mir = plc['mirror_rule_on_bad_sides']
    hb = hibm_2026()
    # ── French 米国の巨大株 ──
    for nm in ('R2b_cs_L12_Kq_me5_lowTO', 'Q2b_cs_L12_Kq_me5', 'Q2e_ts1_me5', 'F2a_ts12_me5_lowTO', 'F2b_ts_lo12_me5_lowTO'):
        r = fr[nm]
        b = r['reproduced']
        q = r['quarterly_rebalance']
        iss = []
        if nm in ('R2b_cs_L12_Kq_me5_lowTO', 'F2a_ts12_me5_lowTO', 'F2b_ts_lo12_me5_lowTO'):
            iss.append('事後の手直し: 7特性の宇宙（str・mom・var・resvar を外す）は第2次 Q2b の保有期間の結果と「直近1か月を飛ばすと +0.33」の点検を見た後に決めた（prereg3 の what_i_have_seen）。'
                       '全体の事前登録の正直さの約束「保有期間の結果を見て規則を変えたら事後と明記し判定に使わない」に当たる')
        iss.append(f"鏡の偽薬: 同じ規則を悪い側（成長・高ベータ・高投資…）に当てると保有 {sh(mir[nm]['hold'])}・費用後 {sh(mir[nm]['net_hold'])}（規則は {sh(short(b['hold']))}）。"
                   '勝ちは『良い側の特性の勢い』ではなく、数十社の巨大株のかごの間の値動きの勢い（2007年以降の巨大株の時代）')
        alt = r['other_universe_same_rule'].get('US4', {})
        iss.append(f"隣の規模帯（NYSE 60〜80%点・ME4）で同じ規則: 保有 {sh(alt.get('hold'))}"
                   + ('／2×3 の BIG（F1a・研究者の第4次）+0.50' if nm.startswith('R2b') else ''))
        iss.append(f"良い3年 {b['hold_best3_years']} を除くと {sh(short(b['hold_without_best3_years']))}・勝った年 {b['hold_years_won'][0]}/{b['hold_years_won'][1]}")
        iss.append(f"組み直しの時期: 四半期（位相0/1/2）{sh(q['phase0']['hold'])} / {sh(q['phase1']['hold'])} / {sh(q['phase2']['hold'])}・"
                   + ('2か月前の信号（ラグ2）' if nm.startswith('Q2e') else '直近1か月を飛ばす') + f" {sh(r['skip1']['hold'])}")
        nb = r['neighbors']
        iss.append(f"近いパラメータ {nb['n']}通り: 保有が正 {nb['hold_positive']}・t≥1.65 は {nb['hold_t_ge_1_65']}（中央 {nb['hold_median']}）")
        iss.append(f"費用1.5倍 {sh(r['net_hold_cost_x1_5'])}・2倍 {sh(short(b['net_hold_cost_x2']))}・3倍 {sh(short(b['net_hold_cost_x3']))}（保有期間の費用 {b['cost_pct_per_year_hold']}%/年）。"
                   f"無作為に同じ本数を選ぶ帰無の p（片側）{r['random_selection_null']['p_one_sided']}")
        iss.append(f"保有期間の終わりを変える: 2025-12 まで {sh(r['hold_to_2025_12'])}・2024-12 まで {sh(r['hold_to_2024_12'])}")
        fh = r['firms_in_held_portfolios']
        iss.append(f"集中: 持ったポートフォリオの銘柄数は保有期間の平均 {fh['hold_mean_of_avg_firms_held']}社・最少 {fh['hold_min_firms_in_a_held_portfolio']}社"
                   + (f"。2026年（{hb['months']}か月）の BIG HiBM（{hb['firms_min_max'][0]:.0f}〜{hb['firms_min_max'][1]:.0f}社）は {hb['big_hibm']:+.1f}%・市場 {hb['mkt']:+.1f}%" if nm.startswith(('R2b', 'Q2b', 'F2')) else ''))
        iss.append(f"多重検定: 角度70本で保有期間の Holm p={h70h[nm]}・全期間の Holm p={round(h70f[nm], 4)}（C7 は全期間 t で満たすが、その大半は論文の標本内の1964〜2006年）")
        iss.append(tax_line(nm))
        out[nm] = {'b': b, 'issues': [x for x in iss if x]}
    V = {'R2b_cs_L12_Kq_me5_lowTO': ('downgraded to B', 'B'), 'Q2b_cs_L12_Kq_me5': ('downgraded to B', 'B'), 'Q2e_ts1_me5': ('downgraded to B', 'B'),
         'F2a_ts12_me5_lowTO': ('downgraded to B', 'B'), 'F2b_ts_lo12_me5_lowTO': ('downgraded to C', 'C')}
    out['R2b_cs_L12_Kq_me5_lowTO']['issues'].insert(0, '判断: 数字は再現したが、規則は保有期間を見た後の手直し（事後）で、勝ちの仕組みは鏡の偽薬が規則以上に勝つ『巨大株のかごの勢い』、'
                                                    '隣の規模帯では消え、良い3年と2026年の8か月（十数社のかご）に寄る。C3 は 2025-12 で切ると落ちる。S は支持できず、B（有望・弱い）止まり')
    out['F2b_ts_lo12_me5_lowTO']['issues'].insert(0, '判断: C3 は元々不合格（保有 t0.92）で A は地域の再現（3特性）頼み。鏡の偽薬が規則の3倍以上勝ち、隣の規模帯は負け、良い3年を除くと負け＝規則の腕と区別できない（C）')

    # ── French 地域 ──
    frp = plc['placebo_ew']
    for nm in ('Q2R_Emerging_ts12', 'Q2R_Emerging_ts_lo12', 'Q2R_Emerging_ew', 'Q2R_Emerging_ts1', 'Q2R_Europe_ts1', 'Q2R_Developed_ex_US_ts1',
               'Q2R_Europe_ts_lo12', 'Q2R_Japan_ts12'):
        r = fr[nm]
        b = r['reproduced']
        q = r['quarterly_rebalance']
        uk = FR_CANDS[nm][0]
        rule = FR_CANDS[nm][1]
        iss = []
        nb = r['neighbors']
        if rule != 'ew':
            iss.append(('2か月前の信号（ラグ2）' if rule == 'ts1' else '直近1か月を飛ばす') + f" {sh(r['skip1']['hold'])}・四半期の組み直し（位相0/1/2）{sh(q['phase0']['hold'])} / {sh(q['phase1']['hold'])} / {sh(q['phase2']['hold'])}")
            iss.append(f"近いパラメータ {nb['n']}通り（形成 L）: 保有が正 {nb['hold_positive']}・t≥1.65 は {nb['hold_t_ge_1_65']}（範囲 {nb['hold_min']}〜{nb['hold_max']}）")
        iss.append(f"前半 {sh(short(b['hold_half1']))}・後半 {sh(short(b['hold_half2']))}（後半の費用後 {sh(short(b['net_hold_half2']))}）・2020-21 を除く {sh(short(b['hold_drop_2020_2021']))}"
                   f"・直近（2013-07〜）{sh(short(b['recent']))}・良い3年を除く {sh(short(b['hold_without_best3_years']))}")
        iss.append(f"費用2倍 {sh(short(b['net_hold_cost_x2']))}・3倍 {sh(short(b['net_hold_cost_x3']))}（保有期間の費用 {b['cost_pct_per_year_hold']}%/年）")
        if uk in frp:
            iss.append(f"偽薬（同じ BIG 行の等分）: 良い側 {sh(frp[uk]['ew_good']['hold'])}・真ん中 {sh(frp[uk]['ew_middle']['hold'])}・悪い側 {sh(frp[uk]['ew_bad']['hold'])}"
                       + ('' if rule == 'ew' else f"／同じ規則を悪い側に {sh(mir[nm]['hold'])}"))
        if rule != 'ew':
            iss.append(f"同じ良い側の等分（静的な傾け）{sh(r['static_ew_same_sides']['hold'])}・勢いの選び方の上乗せ {sh(r['timing_value_added_vs_static']['hold'])}・無作為の帰無の p {r['random_selection_null']['p_one_sided']}")
        alt = r['other_universe_same_rule']
        if alt:
            iss.append('同じ地域の別の宇宙で同じ規則: ' + '・'.join(f"{k} {sh(v['hold'])}" for k, v in alt.items()))
        jk = {'Emerging': 'emerging', 'Developed_ex_US': 'developed', 'Europe': 'developed', 'Japan': None}.get(uk)
        if jk and rule in jreg.get(jk, {}):
            x = jreg[jk][rule]
            iss.append(f"別の業者（JKP・全規模の時価加重三分位・片道0.30%）の {jk} で同じ4特性の規則: 保有 {sh(x['hold'])}・費用後 {sh(x['net_hold'])}")
        iss.append(f"多重検定: 角度70本の Holm（保有）p={h70h[nm]}・（全期間）p={round(h70f[nm], 4)}。Bonferroni の線は t {mt['bonferroni_t_70']}")
        iss.append(tax_line(nm))
        out[nm] = {'b': b, 'issues': [x for x in iss if x]}
    em_note = (f"相手の French の新興国の市場は 2007〜 で実在の VEIEX より {em.get('french_EM_mkt_vs_VEIEX_hold', {}).get('diff')}%/年 強い（弱い相手ではない）。"
               f"実在の新興国バリュー（DFEVX）はその市場に {em.get('DFEVX_EMvalue_fund_vs_french_EM_mkt_hold', {}).get('diff')}%/年 ＝実装の差が残る")
    for nm in ('Q2R_Emerging_ts12', 'Q2R_Emerging_ts_lo12', 'Q2R_Emerging_ew', 'Q2R_Emerging_ts1'):
        out[nm]['issues'].append(em_note)
        out[nm]['issues'].append('訓練は 1992〜2006 の約14.5年（全体の事前登録の但し書きで可）。20年窓は15〜16本だがほぼ重なる（独立の試行は1〜2回分）。French の新興国は Bloomberg 由来で CRSP ではない（上場廃止の扱いは未確認）')
    for nm in ('Q2R_Emerging_ts12', 'Q2R_Emerging_ts_lo12'):
        out[nm]['issues'].insert(0, '判断: 反証できなかった。直近1か月飛ばし・近いパラメータ・四半期の組み直し・前後半・良い3年抜き・鏡の偽薬・別の業者（JKP）のどれでも正。'
                                    'ただし超過の6割強は『良い側4本の等分』という静的な多因子の傾けで、勢いの選び方の上乗せ自体は有意ではない')
    out['Q2R_Emerging_ew']['issues'].insert(0, '判断: 反証できなかった（勢いではなく、新興国の大型株で割安・高収益・投資控えめ・勢いの良い側4本を等分に持つ静的な傾け）。偽薬は良い>真ん中>悪いの順で、作り方の偏りではない')
    V.update({'Q2R_Emerging_ts12': ('confirmed', 'S'), 'Q2R_Emerging_ts_lo12': ('confirmed', 'S'), 'Q2R_Emerging_ew': ('confirmed', 'S'),
              'Q2R_Emerging_ts1': ('downgraded to A', 'A'), 'Q2R_Europe_ts1': ('downgraded to B', 'B'), 'Q2R_Developed_ex_US_ts1': ('downgraded to A', 'A'),
              'Q2R_Europe_ts_lo12': ('confirmed', 'B'), 'Q2R_Japan_ts12': ('downgraded to C', 'C')})
    b = fr['Q2R_Emerging_ts1']['reproduced']
    out['Q2R_Emerging_ts1']['issues'].insert(0, f"判断: 費用前は頑丈だが、毎月の組み直しで費用 {b['cost_pct_per_year_hold']}%/年。費用後 {sh(short(b['net_hold']))} と統計的に弱く、費用2倍で {sh(short(b['net_hold_cost_x2']))}。"
                                             f"別の業者（JKP）の新興国でも費用後 {sh(jreg['emerging']['ts1']['net_hold'])}。S の C3 は費用前の t で満たしているだけ→A")
    b = fr['Q2R_Europe_ts1']['reproduced']
    out['Q2R_Europe_ts1']['issues'].insert(0, f"判断: C7 は全期間 t{b['full']['t']} で線 3.0 をぎりぎり。角度70本で全期間の p に Holm を掛けると {round(h70f['Q2R_Europe_ts1'], 3)}（不合格）＝多重検定を数えると C7 が落ちて B。"
                                           f"しかも毎月・1か月の信号でしか効かない（ラグ2で負け・四半期はどの位相も t<1.65）。欧州の取引税（英国の印紙税0.5%・仏0.3〜0.4%・伊・西）で片道費用は0.10%の約2倍が現実的＝費用2倍 {sh(short(b['net_hold_cost_x2']))}")
    b = fr['Q2R_Developed_ex_US_ts1']['reproduced']
    out['Q2R_Developed_ex_US_ts1']['issues'].insert(0, f"判断: 中身の過半は欧州（Q2R_Europe_ts1 と独立ではない）。ラグ2で負け・四半期の位相1で負け・直近（2013-07〜）{sh(short(b['recent']))}・後半 {sh(short(b['hold_half2']))}・"
                                                    f"費用3倍 {sh(short(b['net_hold_cost_x3']))}・別の業者（JKP developed）では費用後 {sh(jreg['developed']['ts1']['net_hold'])}。C3 は位相と時期に頑丈でない→A（C5 の2/2で A は保つ）")
    b = fr['Q2R_Japan_ts12']['reproduced']
    out['Q2R_Japan_ts12']['issues'].insert(0, f"判断: 同じ規則を悪い側に当てると {sh(mir['Q2R_Japan_ts12']['hold'])}（規則 {sh(short(b['hold']))} より大きい）・2×3 の BIG で {sh(fr['Q2R_Japan_ts12']['other_universe_same_rule']['Japan_2x3']['hold'])}・"
                                           f"良い3年を除くと {sh(short(b['hold_without_best3_years']))}・20年積立の勝率 {b['dca20']['win_rate']}＝雑音と区別できない（C）")
    out['Q2R_Europe_ts_lo12']['issues'].insert(0, '判断: B のまま（C3・C7 は元々不合格）。鏡の偽薬は負け・近いパラメータは全部正・別の業者（JKP developed）でも正で、向きは本物らしいが統計は弱い。良い3年を除くと0')

    # ── JKP 米国 ──
    n_post = len(JK_LOWTO - JK_PRE2007)
    for nm in ('Q1a_cs_L12_K10_H1_lowTO', 'Q1b_cs_L12_K10_H1_lowTO_buf20', 'Q1c_ts12_lowTO'):
        r = jus[nm]
        b = r['reproduced']
        iss = [f"判断: 後の知識を抜く（2006年までに公表された特性だけ・{len(JK_LOWTO)}本→{len(JK_LOWTO & JK_PRE2007)}本）と保有 {sh(r['pre2007_published_only']['hold'])}・費用後 {sh(r['pre2007_published_only']['net_hold'])}＝C6 不合格→C。"
               f"{len(JK_LOWTO)}本のうち{n_post}本は2007年以降の論文で『良い側』と採用が決まった（論文の標本が保有期間と重なる）",
               f"費用1.5倍 {sh(r['net_hold_cost_x1_5'])}・直近1か月を飛ばす {sh(r['skip1']['hold'])}（費用後 {sh(r['skip1']['net_hold'])}）",
               f"後半（2016-07〜）の費用後 {sh(short(b['net_hold_half2']))}・良い3年を除く {sh(short(b['hold_without_best3_years']))}",
               f"同じ規則を悪い側に当てた偽薬 {sh(r['placebo_same_rule_on_bad_sides']['hold'])}",
               f"多重検定: 角度70本の Holm（保有）p={h70h[nm]}"]
        out[nm] = {'b': b, 'issues': iss}
        V[nm] = ('downgraded to C', 'C')

    # ── JKP 各国パネル ──
    for nm in PANEL_OF:
        r = pan[nm]
        b = r['reproduced']
        t = r['tests']
        cw = pcw[nm]
        mid = pan['_placebo_ew_terciles_panel_lowTO112'] if 'lowTO' in PANEL_OF[nm] else pan['_placebo_ew_terciles_panel_all153']
        iss = [f"相手が『国々の市場の等分』（全体の事前登録は同じ地域の時価加重）。事前登録どおりの相手（JKP の地域の時価加重の市場）で同じ規則: "
               + '・'.join(f"{k} 保有 {sh(v['hold'])} 費用後 {sh(v['net_hold'])} 訓練 {sh(v['train'])}→{v['grade_letter']}" for k, v in cw.items()),
               f"作り方の傾き: 同じ特性の『真ん中の三分位』を等分に持つだけで保有 {sh(mid['middle']['hold'])}（悪い側 {sh(mid['bad']['hold'])}）＝三分位を等分にする作り方そのものが国々の市場に勝つ分がある",
               f"費用2倍 {sh(short(b['net_hold_cost_x2']))}・3倍 {sh(short(b['net_hold_cost_x3']))}・先進国1倍/他3倍 {sh(short(b['net_hold_cost_dev_x1_others_x3']))}（小国・フロンティアの片道0.30%は楽観）",
               '頑丈さ: ' + ('直近1か月を飛ばす ' + sh(t['skip1']['hold']) + '・' if 'skip1' in t else '')
               + f"2006年までに公表の特性だけ {sh(t['pre2007_published_only']['hold'])}（費用後 {sh(t['pre2007_published_only']['net_hold'])}）・規模の群を抜く {sh(t['no_size_cluster']['hold'])}"
               + f"・先進21か国 {sh(t['subset_developed21']['hold'])}（費用後 {sh(t['subset_developed21']['net_hold'])}）・大きい新興11か国 {sh(t['subset_big_em11']['hold'])}（費用後 {sh(t['subset_big_em11']['net_hold'])}）",
               f"同じ規則を悪い側に当てた偽薬 {sh(t['placebo_same_rule_on_bad_sides']['hold'])}（費用後 {sh(t['placebo_same_rule_on_bad_sides']['net_hold'])}）",
               f"国ごと: 保有が正 {b['countries_hold_positive'][0]}/{b['countries_hold_positive'][1]}・費用後が正 {b['countries_net_hold_positive'][0]}/{b['countries_net_hold_positive'][1]}。"
               f"前半 {sh(short(b['hold_half1']))}・後半 {sh(short(b['hold_half2']))}（後半の費用後 {sh(short(b['net_hold_half2']))}）・月次の超過の自己相関 {b['hold_excess_autocorr1']}",
               f"持てるか: {b['n_countries']}か国×各国の三分位（小国は10〜数十社）を個人が持つ商品は無い。フロンティアの市場（ナイジェリア・パキスタン・ベトナム等）を含む"]
        out[nm] = {'b': b, 'issues': iss}
    out['R1a_panel_Q1b']['issues'].insert(0, '判断: 保有期間の勝ちは今回の点検をすべて通った（1か月飛ばし・後の知識を抜く・規模の群を抜く・先進国だけ・費用2倍・時価加重の地域の相手）。'
                                        'ただし事前登録どおりの時価加重の相手では訓練期間の t が 2.0 に届かない地域がある（world_ex_us・developed は C1 不合格、emerging のみ S）ので S→A')
    out['R1b_panel_Q1c']['issues'].insert(0, '判断: 費用前は頑丈だが、費用2倍でほぼ0・先進国1倍/他3倍で有意でない・作り方の傾き（真ん中の三分位）で超過の約1/3が説明される。時価加重の相手では C1 が地域で落ちる→B')
    out['Q3_panel_P2_ts12']['issues'].insert(0, '判断: 費用後の超過は『真ん中の三分位を等分に持つ』作り方の傾きとほぼ同じ大きさで、費用2倍・先進国1倍/他3倍で負け。時価加重の相手では C1 が地域で落ちる→B')
    out['Q3_panel_P3_ew_all']['issues'].insert(0, '判断: 勢いの無い静的な等分。費用後の超過は『真ん中の三分位を等分に持つ』作り方の傾きより小さく、費用2倍で負け、事前登録どおりの時価加重の相手では3地域とも C（訓練の t<2）→C')
    V.update({'R1a_panel_Q1b': ('downgraded to A', 'A'), 'R1b_panel_Q1c': ('downgraded to B', 'B'),
              'Q3_panel_P2_ts12': ('downgraded to B', 'B'), 'Q3_panel_P3_ew_all': ('downgraded to C', 'C')})

    res = collections.OrderedDict()
    for nm, (vd, g) in V.items():
        c = C[nm]
        b = out[nm]['b']
        tol = 0.02 if nm in PANEL_OF else 0.005
        rep = abs(b['hold']['ex'] - c['hold']['ex_ann']) <= tol and abs(b['full']['ex'] - c['full']['ex_ann']) <= tol and abs(b['full']['t'] - c['full']['t']) <= tol + 0.005
        c5 = repl_c5(nm, uv)
        fam_p = c.get('holm_p_family')
        lg, crit = grade(b['full'], b['train'], b['hold'], b['roll20'], b['net_hold'],
                         None if c5 is None else (c5['positive'] / c5['regions'] >= 2 / 3), fam_p)
        res[nm] = {'claimed_grade': c['grade'], 'verified_grade': g, 'verdict': vd, 'reproduced': bool(rep),
                   'letter_grade_from_own_numbers': lg, 'criteria_own': crit, 'c5_own': c5,
                   'key_numbers': base_nums(b), 'issues': out[nm]['issues']}
    return res


def summary_ja(V, R):
    fr, pan = R['french'], R['panels']
    em = fr['Q2R_Emerging_ts12']['reproduced']
    r2 = fr['R2b_cs_L12_Kq_me5_lowTO']
    mir = R['french_placebo']['mirror_rule_on_bad_sides']['R2b_cs_L12_Kq_me5_lowTO']['hold']
    us4 = r2['other_universe_same_rule']['US4']['hold']
    ex3 = r2['reproduced']['hold_without_best3_years']
    mid = pan['_placebo_ew_terciles_panel_all153']['middle']['hold']
    n = collections.Counter(v['verified_grade'] for v in V.values())
    return '\n'.join([
        f"S12・A6・B上位2の20本を自前のコードで作り直し、数字はすべて再現しました（線を自前で当てても研究者と同じ格付け）。反証の点検のあとの格付けは S{n.get('S', 0)}・A{n.get('A', 0)}・B{n.get('B', 0)}・C{n.get('C', 0)} です。",
        f"S のまま残ったのは新興国の大型株（French の BIG 行・4特性）の3本だけです。例えば ts12 は保有 {em['hold']['ex']:+.2f}%/年 t{em['hold']['t']}・費用後 {em['net_hold']['ex']:+.2f} で、1か月飛ばし・近いパラメータ・四半期の組み直し・別の業者（JKP）でも正でした。ただし超過の6割強は良い側4本を等分に持つ静的な傾けで、勢いの選び方の上乗せは有意ではありません。",
        f"米国の巨大株 R2b（S）は B に下げました。保有期間を見た後の手直しで、同じ規則を悪い側に当てると {mir[0]:+.2f} とむしろ勝ち、隣の規模帯（NYSE 60〜80%）では {us4[0]:+.2f}、良い3年を除くと {ex3['ex']:+.2f}、2025年末で切ると t{r2['hold_to_2025_12'][1]} です。勝ちは十数社の巨大株のかごの勢いで、特性の良い側ではありません。",
        f"JKP の各国パネルは R1a だけ A です（1か月飛ばし・2006年以前の特性だけ・先進21か国・費用2倍でも保有期間は勝つが、時価加重の地域の相手では訓練の t が足りない地域がある）。R1b・P2 は B、P3 は C です（三分位を等分に持つ作り方だけで {mid[0]:+.2f}%/年 勝つ分がある）。",
        '米国 JKP の Q1a〜c は C です（2006年までに公表された特性だけにすると費用後が負け＝後の知識の混入）。欧州の1か月の勢い（S）は角度70本の多重検定を数えると C7 が落ちて B、米国を除く先進国の同じ規則は A、新興国の1か月版は費用に弱く A です。',
        '結論: 反証に耐えたのは「新興国の大型株で良い側の多因子に傾ける」ことと「多数の国で回転の少ない特性の勢いを使う（個人は持てない）」ことです。米国で市場に勝つ規則は残りませんでした。'])


def main():
    t0 = time.time()
    uv, base = part_fr_repro()
    R = {}
    R['french'] = part_fr_refute(uv, base)
    for nm, (uk, rule, uni, mc) in FR_CANDS.items():
        u = uv[uk]
        sim = run(u, fr_rule(rule, uni, mc))
        net = {k: sim['ret'][k] - sim['cost'][k] for k in sim['ret']}
        R['french'][nm]['tax_japan_taxable'] = tax_view(net, u.mkt, u.rf)
        R['french'][nm]['hold_to_2025_12'] = short(stats(sim['ret'], u.mkt, u.rf, a=H0, z=202512))
        R['french'][nm]['hold_to_2024_12'] = short(stats(sim['ret'], u.mkt, u.rf, a=H0, z=202412))
        R['french'][nm]['net_hold_cost_x1_5'] = short(stats({k: sim['ret'][k] - 1.5 * sim['cost'][k] for k in sim['ret']}, u.mkt, u.rf, a=H0))
        spec, pre = (US5, '') if uk == 'US5' else ((REG6, 'Emerging_Markets_') if uk == 'Emerging' else (REG25, uk + '_'))
        R['french'][nm]['firms_in_held_portfolios'] = concentration(spec, pre, sim, u)
    R['french_placebo'] = {'placebo_ew': part_fr_placebo(uv), 'mirror_rule_on_bad_sides': part_fr_mirror(uv)}
    R['jkp_us'] = part_jk_us()
    R['panels'] = part_panels()
    R['panel_capweighted'] = part_panel_capweighted()
    R['jkp_region_replication'] = part_jk_region_repl()
    R['em_reality'] = part_em_reality()
    R['multiple_testing'] = part_multiple_testing()
    V = verdicts(R, uv)
    out = {'angle': 'fmom_wf', 'role': '反証の検証（adversarial verifier）', 'generated': time.strftime('%Y-%m-%d'),
           'inputs': {'claims': 'out/mw_fmom_wf.json（70本・S12/A6/B11）', 'prereg': ['out/mw_prereg.json'] + [f'out/mw_fmom_wf_prereg{s}.json' for s in ('', '2', '3', '4')],
                      'scope': 'S と A の全18本 ＋ B の保有期間の超過の上位2本（Q2R_Europe_ts_lo12・Q2R_Japan_ts12）'},
           'independence': 'mw_common からは取得（get・jkp_rows・yahoo）だけを使用。French の CSV の読み取り・ポートフォリオの組み立て・漂い・費用・超過・NW t・CAGR・20年窓・積立・線の当てはめは自前。研究者のコードは import していない',
           'reproduction': '20本すべてで研究者の数字を再現（French 13本は小数2桁まで一致、JKP の米国3本も一致、各国パネル4本は ±0.01 以内）',
           'verdict_policy': ('letter_grade_from_own_numbers は自前の数字に out/mw_prereg.json の線（C1〜C7・C5 も自前で数え直し）をそのまま当てた格付けで、20本すべて研究者の格付けと一致した。'
                              'verified_grade はその上で反証の点検を効かせた判断: (a) 後の知識・保有期間を見た後の手直しを抜く、(b) 事前登録どおりの相手（同じ地域の時価加重）に替える、'
                              '(c) 角度70本の多重検定を数える、(d) 鏡の偽薬・隣の宇宙・良い3年抜き・費用倍率・組み直しの時期で崩れるものは1段以上下げる。迷ったら下げた'),
           'counts': dict(collections.Counter(v['verdict'] for v in V.values())),
           'summary_ja': summary_ja(V, R),
           'verdicts': V,
           'details': R,
           'runtime_sec': round(time.time() - t0),
           'log_tail': LOG[-120:]}
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    log('saved', OUT, os.path.getsize(OUT))
    for nm, v in V.items():
        log(f"{nm:34s} {v['claimed_grade']} → {v['verified_grade']}  {v['verdict']}  repro={v['reproduced']}")


if __name__ == '__main__' and len(sys.argv) == 1:
    main()
