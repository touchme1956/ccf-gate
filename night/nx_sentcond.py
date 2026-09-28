#!/usr/bin/env python3
"""night/nx_sentcond.py — 角度 nx_sentcond（投資家の心理で『堅い株』と市場を切り替える）を事前登録どおりに測る
（読むだけ・門の判定には不使用）

問い: Baker-Wurgler の心理指数を、月末 t までに分かる成分だけの拡大窓の主成分で毎月作り直し（公表の遅れも足す）、
      その値が正（窓の平均より上＝心理が高い）なら t+1 月は堅い株（French の既成の時価加重ポートフォリオ）を、
      それ以外なら市場（French Mkt）を持つ（買いだけ・常に株100%）規則は、訓練（1970-08〜2006-12）でも
      保有（2007-01〜2026-02）でも費用後に市場に勝ち、シャープでも市場を上回るか。
事前登録: out/nx_sentcond_prereg.json（commit 330f348c・測る前）。線は out/nx_prereg.json（C1〜C8・S/A/B/C）。
データ: night/nx_sentcond_data.py（信号 out/_nx_cache/nx_sentcond_signals.json・regime_sha256 を最初に確かめる）。
出力: out/nx_sentcond.json（tested に 主5・探索14 の全規則＝負けも残す。対照・偽の信号・実物の ETF は報告だけ）

約束（事前登録どおり）
- 主の族 P1〜P5（Holm は5本の中・C5 は米国外7か国）／探索の族 E1〜E14（Holm は14本の中・C5 は N/A）
- C1・C2・C3・C7 は費用前、C4・C6・C8 は費用後（判定の費用 c=0.10%・投機的な組は 0.30%）
- 切替えの型なので C8（訓練・保有の両方でシャープが Mkt を上回る）は必須
- 結果を見た後の分析は post_hoc に置き『事後』と明記し、格付けには使わない
"""
import sys, os, json, math, hashlib, subprocess, datetime, statistics as _stat

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N  # noqa: E402
import nx_sentcond_data as D  # noqa: E402
import numpy as np  # noqa: E402


class _StatShim:
    """速さだけの細工（数値は1ビットも変えない。nx_stack.py と同じ）: nx_common.excess_stats は β の和の中で
    S.mean(sv)・S.mean(bv) を要素ごとに計算し直す（O(n²)・分数の厳密計算）。同じ list への mean の答えを覚えて返す。
    nx_common.py 自体は書き換えない（他の角度と同じ物差しを保つ）"""

    def __init__(self):
        self._last = []

    def mean(self, x):
        for o, ln, r in self._last:
            if o is x and ln == len(x):
                return r
        r = _stat.mean(x)
        self._last = ([(x, len(x), r)] + self._last)[:4]
        return r

    def __getattr__(self, name):
        return getattr(_stat, name)


N.S = _StatShim()

BASE = N.BASE
PREREG_PATH = os.path.join(BASE, 'out', 'nx_sentcond_prereg.json')
PR = json.load(open(PREREG_PATH))
OUTNAME = 'nx_sentcond.json'
TE, HS, RS = N.TRAIN_END, N.HOLD_START, N.RECENT_START
add, months = D.add, D.months


def _hex64(s):
    return s.strip()[:64]


EXP_REGIME_SHA = _hex64(PR['tools']['regime_sha256'])
EXP_REGIME_SHA19 = _hex64(PR['tools']['regime_sha256_2019'])
EXP_DATA_TOOL_SHA = _hex64(PR['tools']['data_tool_sha256'])
EXP_XLSX_SHA = _hex64(PR['data']['sentiment']['sha256'])

# ───────────────────────── 信号（最初に sha を確かめる＝結果を見てから作り直していない証明） ─────────────────────────
SIGF = json.load(open(D.OUT))
if SIGF['regime_sha256'] != EXP_REGIME_SHA:
    sys.exit(f'止まる: 信号の regime_sha256 {SIGF["regime_sha256"]} が事前登録 {EXP_REGIME_SHA} と違う')
if D.regime_sha(SIGF['signals']) != EXP_REGIME_SHA:
    sys.exit('止まる: 保存された信号から計算し直した regime_sha256 が事前登録と違う')
if SIGF['regime_sha256_2019'] != EXP_REGIME_SHA19 or D.regime_sha(SIGF['signals_2019']) != EXP_REGIME_SHA19:
    sys.exit('止まる: 2019 年版の信号の sha256 が事前登録と違う')
SIG = {k: {int(t): v for t, v in s.items()} for k, s in SIGF['signals'].items()}
SIG.update({k: {int(t): v for t, v in s.items()} for k, s in SIGF['signals_2019'].items()})


def regime(name, thr='zero'):
    """判断の月 t → 心理が高いか（'zero': S_rt>0／'median': 窓の中央値より上）"""
    s = SIG[name]
    if thr == 'zero':
        return {t: bool(v['S'] > 0) for t, v in s.items()}
    return {t: bool(v['above_median']) for t, v in s.items()}


# ───────────────────────── リターン（French・総リターン・小数） ─────────────────────────
FF = N.ff_factors()
MKT, RF = FF['mkt'], FF['rf']
ME_OP = N.french_series('6_Portfolios_ME_OP_2x3', 'Average Value Weighted Returns -- Monthly')
VAR = N.french_series('Portfolios_Formed_on_VAR', 'Value Weighted Returns -- Monthly')
BETA = N.french_series('Portfolios_Formed_on_BETA', 'Value Weighted Returns -- Monthly')
DP = N.french_series('Portfolios_Formed_on_D-P', 'Value Weight Returns -- Monthly')
RESVAR = N.french_series('Portfolios_Formed_on_RESVAR', 'Value Weighted Returns -- Monthly')
LAST = max(MKT)


def eqw(series_list):
    ks = set.intersection(*[set(s) for s in series_list])
    return {k: sum(s[k] for s in series_list) / len(series_list) for k in ks}


def payers():
    """E14: D-P の Lo 30・Med 40・Hi 30 を、判断の月 t の行の社数×平均の時価で重みづけして t+1 月に持つ"""
    tb = N.french_tables('Portfolios_Formed_on_D-P')
    nf, sz = tb['Number of Firms in Portfolios'], tb['Average Firm Size']
    ci = {c: i for i, c in enumerate(nf['cols'])}
    si = {c: i for i, c in enumerate(sz['cols'])}
    out, wlog = {}, {}
    for m in sorted(DP['Lo 30']):
        t = add(m, -1)
        if t not in nf['data'] or t not in sz['data']:
            continue
        w = {}
        for c in ('Lo 30', 'Med 40', 'Hi 30'):
            n_, s_ = nf['data'][t][ci[c]], sz['data'][t][si[c]]
            if n_ is None or s_ is None or m not in DP[c]:
                break
            w[c] = n_ * s_
        else:
            tot = sum(w.values())
            out[m] = sum(w[c] * DP[c][m] for c in w) / tot
            wlog[m] = {c: round(w[c] / tot, 4) for c in w}
    return out, wlog


PAYERS, PAYERS_W = payers()
LEGR = {
    'Mkt': MKT,
    'BIGHiOP': ME_OP['BIG HiOP'], 'SMALLLoOP': ME_OP['SMALL LoOP'],
    'VARLo20': VAR['Lo 20'], 'VARHi20': VAR['Hi 20'],
    'BETALo20': BETA['Lo 20'], 'BETAHi20': BETA['Hi 20'],
    'DPHi30': DP['Hi 30'], 'DPle0': DP['<= 0'],
    'RESVARLo20': RESVAR['Lo 20'],
    'PAYERS': PAYERS,
}
LEGR['HARD4'] = eqw([LEGR['BIGHiOP'], LEGR['VARLo20'], LEGR['BETALo20'], LEGR['DPHi30']])
LEGR['SPEC4'] = eqw([LEGR['SMALLLoOP'], LEGR['VARHi20'], LEGR['BETAHi20'], LEGR['DPle0']])
# 事前登録 cost_assumption.f_assumed（組の中身が1年に入れ替わる割合の仮置き）と c の区分
LEGMETA = {
    'Mkt': ('mkt', 0.0),
    'BIGHiOP': ('hard', 0.30), 'VARLo20': ('hard', 1.00), 'BETALo20': ('hard', 0.40), 'DPHi30': ('hard', 0.35),
    'HARD4': ('hard', 0.51), 'RESVARLo20': ('hard', 1.00), 'PAYERS': ('hard', 0.10),
    'SMALLLoOP': ('spec', 0.60), 'VARHi20': ('spec', 2.00), 'BETAHi20': ('spec', 0.50), 'DPle0': ('spec', 0.40), 'SPEC4': ('spec', 0.875),
}
# 片側 100% あたりの費用: 判定（大型・市場 0.10%／投機的 0.30%）・感度（0.30%／0.50%）・判定の2倍・費用なし
COSTS = {
    'none': {'mkt': 0.0, 'hard': 0.0, 'spec': 0.0},
    'judgment': {'mkt': 0.001, 'hard': 0.001, 'spec': 0.003},
    'sensitivity': {'mkt': 0.003, 'hard': 0.003, 'spec': 0.005},
    'double': {'mkt': 0.002, 'hard': 0.002, 'spec': 0.006},
}
LEG_LABEL = {'Mkt': 'French Mkt', 'BIGHiOP': 'BIG HiOP（6_Portfolios_ME_OP_2x3）', 'SMALLLoOP': 'SMALL LoOP',
             'VARLo20': 'VAR Lo 20', 'VARHi20': 'VAR Hi 20', 'BETALo20': 'BETA Lo 20', 'BETAHi20': 'BETA Hi 20',
             'DPHi30': 'D-P Hi 30', 'DPle0': 'D-P <= 0（無配）', 'RESVARLo20': 'RESVAR Lo 20',
             'PAYERS': '配当を払う会社全体（D-P Lo30・Med40・Hi30 を社数×平均時価で）', 'HARD4': 'HARD4（4つの堅い組の等分）',
             'SPEC4': 'SPEC4（4つの投機的な組の等分）'}

MAIN_A, MAIN_Z = 197008, 202602  # 主の型の持つ月（事前登録 signal.span・criteria.which）


# ───────────────────────── 規則の組み立て ─────────────────────────
def choice_switch(reg, high_leg, low_leg, a, z):
    """持つ月 m の持ち物 = 判断の月 m−1 の信号で決める。信号なし＝Mkt（欠測を『心理が低い』と読まない）"""
    ch, src = {}, {}
    for m in months(a, z):
        t = add(m, -1)
        assert t < m
        if t in reg:
            ch[m] = high_leg if reg[t] else low_leg
            src[m] = t
        else:
            ch[m] = 'Mkt'
            src[m] = None
    return ch, src


def choice_annual(reg, high_leg, low_leg, a, z):
    """E8: 暦年 Y の12か月は前年12月末の判断 S_rt(Y−1年12月) で決める"""
    ch, src = {}, {}
    for m in months(a, z):
        t = (m // 100 - 1) * 100 + 12
        assert t < m
        if t in reg:
            ch[m] = high_leg if reg[t] else low_leg
            src[m] = t
        else:
            ch[m] = 'Mkt'
            src[m] = None
    return ch, src


def simulate(ch, cost):
    """ch: {持つ月: 組}。→ (費用前, 費用後, 帳簿)。切替え1回 = 売る側の c ＋ 買う側の c を新しい組の最初の月から引く。
    持っている月ごとに 2×c×f/12（組の中の入れ替え）。最初の月の買いは相手（Mkt）と同じく費用を掛けない"""
    gross, net = {}, {}
    prev = None
    book = {'switches': 0, 'switch_cost': 0.0, 'turnover_cost': 0.0}
    for m in sorted(ch):
        leg = ch[m]
        r = LEGR[leg].get(m)
        if r is None:
            raise RuntimeError(f'{leg} の {m} のリターンが無い（米国の French の組は欠けない前提）')
        cat, f = LEGMETA[leg]
        cst = 0.0
        if prev is not None and leg != prev:
            sc = cost[LEGMETA[prev][0]] + cost[cat]
            cst += sc
            book['switches'] += 1
            book['switch_cost'] += sc
        tc = 2 * cost[cat] * f / 12
        cst += tc
        book['turnover_cost'] += tc
        gross[m], net[m] = r, r - cst
        prev = leg
    return gross, net, book


def switch_stats(ch, reg_src, a, z):
    ms = [m for m in sorted(ch) if a <= m <= z]
    if not ms:
        return None
    legs = [ch[m] for m in ms]
    sw = sum(1 for x, y in zip(legs, legs[1:]) if x != y)
    # 信号が高い（high 側の組）の割合と連続
    hi = [reg_src[m] for m in ms]
    runs, cur, curv = [], 0, None
    for v in hi:
        if v == curv:
            cur += 1
        else:
            if curv is not None:
                runs.append((curv, cur))
            curv, cur = v, 1
    runs.append((curv, cur))
    hr = [n for v, n in runs if v == 'high']
    lr = [n for v, n in runs if v == 'low']
    return {'months': len(ms), 'switches': sw, 'switches_per_year': round(sw / (len(ms) / 12), 3),
            'high_share': round(sum(1 for v in hi if v == 'high') / len(ms), 3),
            'no_signal_months': sum(1 for v in hi if v == 'none'),
            'high_runs': len(hr), 'high_run_median_months': sorted(hr)[len(hr) // 2] if hr else None, 'high_run_max_months': max(hr) if hr else None,
            'low_runs': len(lr), 'low_run_median_months': sorted(lr)[len(lr) // 2] if lr else None, 'low_run_max_months': max(lr) if lr else None}


def es(s, b, a=None, z=None):
    return N.excess_stats(s, b, a, z)


def raw_t(s, b, a, z):
    ks = sorted(k for k in set(s) & set(b) if a <= k <= z)
    return N.nw_t([s[k] - b[k] for k in ks], 12)


def shp(r, a=None, z=None):
    return N.sharpe(r, RF, a, z)


def mkt_span(a, z):
    return N.window(MKT, a, z)


def evaluate(rule):
    """1本の規則を全部の物差しで測る"""
    ch, src_t, a, z = rule['choice'], rule['src'], rule['a'], rule['z']
    reg = rule['reg']
    reg_src = {m: ('none' if src_t[m] is None else ('high' if reg[src_t[m]] else 'low')) for m in ch}
    sims = {k: simulate(ch, c) for k, c in COSTS.items()}
    g = sims['none'][0]
    n = sims['judgment'][1]
    b = mkt_span(a, z)
    # 費用の帳簿の検算: 費用前−費用後 = 切替えの費用 + 組の中の入れ替え
    for k, (gg, nn, bk) in sims.items():
        diff = math.fsum(gg[m] - nn[m] for m in gg)
        assert abs(diff - (bk['switch_cost'] + bk['turnover_cost'])) < 1e-12, (rule['id'], k)
        assert abs(gg[max(gg)] - g[max(g)]) < 1e-15
    pub = rule.get('post_pub', HS)
    periods = {'full': (a, z), 'train': (a, TE), 'hold': (HS, z), 'recent_2013_07': (RS, z),
               'p1970_1989': (a, 198912), 'p1990_2006': (199001, TE), 'post_publication': (pub, z)}
    if rule.get('post_pub_extra'):
        periods['post_publication_paper'] = (rule['post_pub_extra'], z)
    gross = {p: es(g, b, x, y) for p, (x, y) in periods.items()}
    net = {p: es(n, b, x, y) for p, (x, y) in periods.items()}
    cost_sens = {}
    for k, (gg, nn, bk) in sims.items():
        cost_sens[k] = {'c_pct': {kk: round(v * 100, 2) for kk, v in COSTS[k].items()},
                        'full': es(nn, b, a, z), 'hold': es(nn, b, HS, z), 'train': es(nn, b, a, TE),
                        'switches': bk['switches'], 'switch_cost_pct_total': round(bk['switch_cost'] * 100, 3),
                        'turnover_cost_pct_total': round(bk['turnover_cost'] * 100, 3),
                        'avg_cost_pct_per_year': round((bk['switch_cost'] + bk['turnover_cost']) * 100 / (len(gg) / 12), 3)}
    sh = {}
    for p in ('full', 'train', 'hold', 'recent_2013_07'):
        x, y = periods[p]
        sh[p] = {'rule_net': shp(n, x, y), 'rule_gross': shp(g, x, y), 'mkt': shp(b, x, y)}
    t_hold = raw_t(g, b, HS, z)
    res = {
        'id': rule['id'], 'family': rule['family'], 'text': rule['text'], 'signal': rule['signal_name'], 'threshold': rule['thr'],
        'high_leg': LEG_LABEL[rule['high']], 'low_leg': LEG_LABEL[rule['low']], 'paper': rule.get('paper'),
        'span': f'{a}〜{z}', 'train': f'{a}〜{TE}', 'hold': f'{HS}〜{z}', 'post_publication_from': pub,
        'gross': gross, 'net': net,
        'roll20_net': N.rolling(n, b, 20, 7), 'roll20_gross': N.rolling(g, b, 20, 7),
        'dca20_net_ratio': N.dca(n, b, 20, 12),
        'maxdd_pct': {'rule_net_full': round(N.maxdd(n) * 100, 1), 'mkt_full': round(N.maxdd(b) * 100, 1),
                      'rule_net_hold': round(N.maxdd(N.window(n, HS, z)) * 100, 1), 'mkt_hold': round(N.maxdd(N.window(b, HS, z)) * 100, 1),
                      'rule_net_train': round(N.maxdd(N.window(n, a, TE)) * 100, 1), 'mkt_train': round(N.maxdd(N.window(b, a, TE)) * 100, 1)},
        'sharpe': sh,
        'cost_sensitivity': cost_sens,
        'switch_count': {'full': switch_stats(ch, reg_src, a, z), 'train': switch_stats(ch, reg_src, a, TE), 'hold': switch_stats(ch, reg_src, HS, z)},
        'hold_t_raw': t_hold, 'hold_p_two_raw': N.p_two(t_hold),
        '_g': g, '_n': n,
    }
    return res


# ───────────────────────── 規則の一覧（事前登録 families） ─────────────────────────
PFAM = PR['families']['P_primary']
XFAM = PR['families']['X_exploratory']


def mk(rid, family, reg, signal_name, thr, high, low, a=MAIN_A, z=MAIN_Z, annual=False, text=None, paper=None, post_pub=HS, post_pub_extra=None):
    ch, src = (choice_annual if annual else choice_switch)(reg, high, low, a, z)
    first = min(m for m in ch if src[m] is not None)
    return {'id': rid, 'family': family, 'reg': reg, 'signal_name': signal_name, 'thr': thr, 'high': high, 'low': low,
            'choice': ch, 'src': src, 'a': a, 'z': z, 'text': text, 'paper': paper, 'post_pub': post_pub,
            'post_pub_extra': post_pub_extra, 'first_signal_hold_month': first}


def build_rules():
    main = regime('main')
    R = []
    P = [('P1_BIGHiOP', 'BIGHiOP'), ('P2_VARLo20', 'VARLo20'), ('P3_BETALo20', 'BETALo20'), ('P4_DPHi30', 'DPHi30'), ('P5_HARD4', 'HARD4')]
    for rid, leg in P:
        d = PFAM[rid]
        pp = int(str(d['post_publication_from']).replace('-', ''))
        R.append(mk(rid, 'P', main, 'main', 'S_rt>0', leg, 'Mkt', text=f"high → {d['high']}、それ以外 → {d['else']}", paper=d['paper'],
                    post_pub=HS, post_pub_extra=pp if pp != HS else None))
    X = XFAM
    R.append(mk('E1_BOTH_BIGHiOP', 'E', main, 'main', 'S_rt>0', 'BIGHiOP', 'SMALLLoOP', text=X['E1_BOTH_BIGHiOP']))
    R.append(mk('E2_BOTH_VAR', 'E', main, 'main', 'S_rt>0', 'VARLo20', 'VARHi20', text=X['E2_BOTH_VAR']))
    R.append(mk('E3_BOTH_BETA', 'E', main, 'main', 'S_rt>0', 'BETALo20', 'BETAHi20', text=X['E3_BOTH_BETA']))
    R.append(mk('E4_BOTH_DP', 'E', main, 'main', 'S_rt>0', 'DPHi30', 'DPle0', text=X['E4_BOTH_DP']))
    R.append(mk('E5_BOTH_HARD4', 'E', main, 'main', 'S_rt>0', 'HARD4', 'SPEC4', text=X['E5_BOTH_HARD4']))
    R.append(mk('E6_LOWSPEC_ONLY', 'E', main, 'main', 'S_rt>0', 'Mkt', 'SPEC4', text=X['E6_LOWSPEC_ONLY']))
    R.append(mk('E7_MEDIAN_HARD4', 'E', regime('main', 'median'), 'main', 'S_rt>窓の中央値', 'HARD4', 'Mkt', text=X['E7_MEDIAN_HARD4']))
    R.append(mk('E8_ANNUAL_HARD4', 'E', main, 'main（12月末だけ）', 'S_rt(前年12月)>0', 'HARD4', 'Mkt', annual=True, text=X['E8_ANNUAL_HARD4']))
    R.append(mk('E9_ORTH_HARD4', 'E', regime('orth'), 'orth', 'S_rt>0', 'HARD4', 'Mkt', text=X['E9_ORTH_HARD4']))
    R.append(mk('E10_PRACTICAL_HARD4', 'E', regime('practical'), 'practical', 'S(m*)>0', 'HARD4', 'Mkt', a=197105, z=LAST, text=X['E10_PRACTICAL_HARD4']))
    R.append(mk('E11_NOBWLAG_HARD4', 'E', regime('nobwlag'), 'nobwlag', 'S_rt>0', 'HARD4', 'Mkt', text=X['E11_NOBWLAG_HARD4']))
    R.append(mk('E12_LAG0_HARD4', 'E', regime('lag0'), 'lag0', 'S_rt>0', 'HARD4', 'Mkt', text=X['E12_LAG0_HARD4']))
    R.append(mk('E13_RESVAR', 'E', main, 'main', 'S_rt>0', 'RESVARLo20', 'Mkt', text=X['E13_RESVAR'], post_pub_extra=201601))
    R.append(mk('E14_PAYERS', 'E', main, 'main', 'S_rt>0', 'PAYERS', 'Mkt', text=X['E14_PAYERS']))
    return R


# ───────────────────────── C5（米国外7か国・米国の実時間の心理で切り替える） ─────────────────────────
C5_CHARS = {'P1_BIGHiOP': [('ope_be', '3.0')], 'P2_VARLo20': [('rvol_21d', '1.0')], 'P3_BETALo20': [('beta_60m', '1.0')],
            'P4_DPHi30': [('div12m_me', '3.0')],
            'P5_HARD4': [('ope_be', '3.0'), ('rvol_21d', '1.0'), ('beta_60m', '1.0'), ('div12m_me', '3.0')]}
C5_COUNTRIES = PR['criteria']['C5_independent_unit']['unit'].split('（')[1].split('）')[0].split('・')
assert C5_COUNTRIES == D.JKP_COUNTRIES, C5_COUNTRIES
C5_END = 202512


def c5_side_check():
    """JKP の堅い側のラベルを jkp_good_side(upto=200612) で確かめる。1つでも食い違えば止まる"""
    out = {}
    for c in C5_COUNTRIES:
        for ch, side in {'ope_be': '3.0', 'rvol_21d': '1.0', 'beta_60m': '1.0', 'div12m_me': '3.0'}.items():
            g, _ = N.jkp_good_side(c, ch, 'vw_cap', upto=200612)
            out[f'{c}|{ch}'] = {'theory': side, 'machine': g, 'match': g == side}
            if g != side:
                sys.exit(f'止まる: JKP の堅い側が理論と食い違う {c} {ch} 理論 {side} 機械 {g}')
    return out


def c5_eval():
    main = regime('main')
    res = {}
    cache = {}
    for c in C5_COUNTRIES:
        jm = N.jkp_mkt(c, 'vw_cap')
        for ch in ('ope_be', 'rvol_21d', 'beta_60m', 'div12m_me'):
            cache[(c, ch)] = N.jkp_portfolios(c, ch, 'vw_cap')
        for rid, legs in C5_CHARS.items():
            sers = [cache[(c, ch)][side] for ch, side in legs]
            # 堅い側の系列が始まる月（P5 は4つそろう月）と 1970-08 の遅いほう
            common = sorted(set.intersection(*[set(s) for s in sers]))
            a = max(common[0], MAIN_A)
            z = min(C5_END, max(jm))
            rule, gaps, hi_m = {}, 0, 0
            prev, sw = None, 0
            net = {}
            for m in months(a, z):
                if m not in jm:
                    continue
                t = add(m, -1)
                hard = None
                if all(m in s for s in sers):
                    hard = sum(s[m] for s in sers) / len(sers)
                if t in main and main[t]:
                    hi_m += 1
                    if hard is None:
                        gaps += 1
                        r, leg = jm[m], 'mkt'
                    else:
                        r, leg = hard, 'hard'
                else:
                    r, leg = jm[m], 'mkt'
                rule[m] = r
                cst = 0.0
                if prev is not None and leg != prev:
                    sw += 1
                    cst += 0.002
                net[m] = r - cst
                prev = leg
            st = es(rule, jm, a, z)
            res[f'{c}|{rid}'] = {'country': c, 'rule': rid, 'from': a, 'to': z, 'legs': [f'{ch} pf{side}' for ch, side in legs],
                                 'gross_vs_country_mkt': st, 'positive': bool(st and st['cagr_diff'] > 0),
                                 'net_switch_only_0.20pct_vs_country_mkt': es(net, jm, a, z),
                                 'high_months': hi_m, 'hard_missing_in_high_months_held_mkt': gaps, 'switches': sw}
    summ = {}
    for rid in C5_CHARS:
        pos = [c for c in C5_COUNTRIES if res[f'{c}|{rid}']['positive']]
        summ[rid] = {'regions': len(C5_COUNTRIES), 'positive': len(pos), 'positive_countries': pos,
                     'pass_ge_5_of_7': len(pos) >= 5}
    return res, summ


# ───────────────────────── 対照・偽の信号・実物（報告だけ） ─────────────────────────
def nw_reg_dummy(y, d, lag=12):
    """y = a + b·d の OLS と Newey-West（Bartlett・ラグ12）の t（b）"""
    y = np.asarray(y, float)
    X = np.column_stack([np.ones(len(y)), np.asarray(d, float)])
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    e = y - X @ beta
    n = len(y)
    Xe = X * e[:, None]
    Sm = Xe.T @ Xe / n
    for L in range(1, lag + 1):
        w = 1 - L / (lag + 1)
        G = Xe[L:].T @ Xe[:-L] / n
        Sm += w * (G + G.T)
    V = n * XtX_inv @ Sm @ XtX_inv
    se = math.sqrt(V[1, 1]) if V[1, 1] > 0 else None
    return float(beta[0]), float(beta[1]), (float(beta[1]) / se if se else None)


def cond_spread():
    main = regime('main')
    out = {}
    for leg in ('BIGHiOP', 'VARLo20', 'BETALo20', 'DPHi30', 'HARD4'):
        out[leg] = {}
        for p, (a, z) in {'train': (MAIN_A, TE), 'hold': (HS, MAIN_Z), 'full': (MAIN_A, MAIN_Z)}.items():
            ys, ds = [], []
            for m in months(a, z):
                t = add(m, -1)
                if t not in main:
                    continue
                ys.append(LEGR[leg][m] - MKT[m])
                ds.append(1.0 if main[t] else 0.0)
            a0, b1, tb = nw_reg_dummy(ys, ds)
            nh = int(sum(ds))
            mh = sum(y for y, d in zip(ys, ds) if d) / nh if nh else None
            ml = sum(y for y, d in zip(ys, ds) if not d) / (len(ys) - nh) if len(ys) > nh else None
            out[leg][p] = {'months': len(ys), 'high_months': nh,
                           'mean_ex_high_pct_ann': round(mh * 1200, 2) if mh is not None else None,
                           'mean_ex_low_pct_ann': round(ml * 1200, 2) if ml is not None else None,
                           'diff_high_minus_low_pct_ann': round(b1 * 1200, 2), 'nw_t_diff': round(tb, 2) if tb is not None else None}
    return out


def static_controls():
    out = {}
    for leg in ('BIGHiOP', 'VARLo20', 'BETALo20', 'DPHi30', 'HARD4', 'SPEC4'):
        ch = {m: leg for m in months(MAIN_A, MAIN_Z)}
        g, n, bk = simulate(ch, COSTS['judgment'])
        b = mkt_span(MAIN_A, MAIN_Z)
        out[leg] = {'label': LEG_LABEL[leg], 'gross': {p: es(g, b, x, y) for p, (x, y) in {'full': (MAIN_A, MAIN_Z), 'train': (MAIN_A, TE), 'hold': (HS, MAIN_Z), 'recent_2013_07': (RS, MAIN_Z)}.items()},
                    'net_hold': es(n, b, HS, MAIN_Z), 'net_full': es(n, b, MAIN_A, MAIN_Z),
                    'sharpe': {p: {'static_net': shp(n, x, y), 'mkt': shp(b, x, y)} for p, (x, y) in {'train': (MAIN_A, TE), 'hold': (HS, MAIN_Z)}.items()},
                    'roll20_net': N.rolling(n, b, 20, 7)}
    return out


def brief(rule_res):
    keep = ('gross', 'net', 'sharpe', 'roll20_net', 'maxdd_pct', 'switch_count')
    out = {k: rule_res[k] for k in keep}
    out['gross'] = {p: rule_res['gross'][p] for p in ('full', 'train', 'hold', 'recent_2013_07')}
    out['net'] = {p: rule_res['net'][p] for p in ('full', 'train', 'hold')}
    return out


def placebo_shift(k_min=24):
    main = regime('main')
    dec = sorted(t for t in main if MAIN_A <= add(t, 1) <= MAIN_Z)
    hold = [add(t, 1) for t in dec]
    seq = np.array([1.0 if main[t] else 0.0 for t in dec])
    hard = np.array([LEGR['HARD4'][m] for m in hold])
    mk_ = np.array([MKT[m] for m in hold])
    Nn = len(seq)
    gb = math.exp(np.mean(np.log1p(mk_)) * 12) - 1

    def stats(h):
        r = mk_ + h * (hard - mk_)
        gs = math.exp(np.mean(np.log1p(r)) * 12) - 1
        return (gs - gb) * 100, float(np.mean(r - mk_) * 1200)

    real_c, real_a = stats(seq)
    dist = []
    for k in range(k_min, Nn - k_min + 1):
        h = np.roll(seq, k)
        dist.append((k,) + stats(h))
    cd = np.array([x[1] for x in dist])
    ad = np.array([x[2] for x in dist])
    return {'n_shifts': len(dist), 'k_range': [k_min, Nn - k_min], 'months': Nn,
            'real_cagr_diff_pct': round(real_c, 3), 'real_ex_ann_pct': round(real_a, 3),
            'share_of_shifts_with_cagr_diff_ge_real': round(float(np.mean(cd >= real_c)), 4),
            'share_of_shifts_with_ex_ann_ge_real': round(float(np.mean(ad >= real_a)), 4),
            'shift_cagr_diff_pct': {'p05': round(float(np.percentile(cd, 5)), 3), 'p50': round(float(np.percentile(cd, 50)), 3),
                                    'p95': round(float(np.percentile(cd, 95)), 3), 'min': round(float(cd.min()), 3), 'max': round(float(cd.max()), 3)},
            'shift_ex_ann_pct': {'p05': round(float(np.percentile(ad, 5)), 3), 'p50': round(float(np.percentile(ad, 50)), 3),
                                 'p95': round(float(np.percentile(ad, 95)), 3)},
            'note': '費用前・全期間 1970-08〜2026-02。main の high/low の並び（判断の月 1970-07〜2026-01）を k か月循環ずらし（np.roll）。心理の持続の長さと high の割合を保ったまま時期だけを壊す'}


def controls():
    out = {}
    main = regime('main')
    # 逆
    r = mk('CTRL_invert_HARD4', 'CTRL', {t: not v for t, v in main.items()}, 'main（反転）', 'S_rt<=0', 'HARD4', 'Mkt', text=PR['families']['controls_report_only']['CTRL_invert_HARD4'])
    out['CTRL_invert_HARD4'] = brief(evaluate(r))
    # 公開の SENT・SENT_ORTH（全期間の主成分＝後知恵あり）
    d, _ = D.load_bw()
    for nm, col in (('CTRL_pub_SENT_HARD4', 'SENT'), ('CTRL_pub_ORTH_HARD4', 'SENT_ORTH')):
        reg = {t: bool(v > 0) for t, v in d[col].items()}
        r = mk(nm, 'CTRL', reg, f'公開の {col}', f'{col}(t)>0', 'HARD4', 'Mkt', text=PR['families']['controls_report_only'][nm])
        out[nm] = brief(evaluate(r))
        out[nm]['no_signal_months'] = sum(1 for m in r['src'] if r['src'][m] is None)
    # 2019 年版の成分（main_2019）と、同じ期間の main
    reg19 = regime('main_2019')
    z19 = add(max(reg19), 1)
    r19 = mk('CTRL_vintage2019_HARD4', 'CTRL', reg19, 'main_2019', 'S_rt>0', 'HARD4', 'Mkt', z=z19, text=PR['families']['controls_report_only']['CTRL_vintage2019_HARD4'])
    rm = mk('P5_HARD4_same_span_as_2019', 'CTRL', main, 'main', 'S_rt>0', 'HARD4', 'Mkt', z=z19)
    e19, em = evaluate(r19), evaluate(rm)
    common = [t for t in reg19 if t in main and MAIN_A <= add(t, 1) <= z19]
    agree = sum(1 for t in common if reg19[t] == main[t])
    out['CTRL_vintage2019_HARD4'] = {'span': f'{MAIN_A}〜{z19}', 'vintage2019': brief(e19), 'main_same_span': brief(em),
                                     'regime_agreement_share': round(agree / len(common), 4), 'decision_months_compared': len(common)}
    out['PLACEBO_shift_HARD4'] = placebo_shift()
    return out


def real_etf_checks():
    out = {}
    spy = N.yahoo('SPY')
    main, prac = regime('main'), regime('practical')
    for rid, tk in (('R1_VIG', 'VIG'), ('R2_DVY', 'DVY'), ('R3_USMV', 'USMV')):
        e = N.yahoo(tk)
        for sname, reg, zmax in (('main', main, MAIN_Z), ('practical_E10', prac, LAST)):
            ks = sorted(m for m in e if m in spy and m <= zmax and add(m, -1) in reg)
            if len(ks) < 24:
                out[f'{rid}|{sname}'] = None
                continue
            a, z = ks[0], ks[-1]
            g, n, prev, sw = {}, {}, None, 0
            for m in months(a, z):
                if m not in e or m not in spy:
                    continue
                t = add(m, -1)
                leg = tk if (t in reg and reg[t]) else 'SPY'
                r = e[m] if leg == tk else spy[m]
                c = 0.0
                if prev is not None and leg != prev:
                    sw += 1
                    c = 0.002
                g[m], n[m] = r, r - c
                prev = leg
            b = {m: spy[m] for m in g}
            out[f'{rid}|{sname}'] = {'etf': tk, 'signal': sname, 'from': a, 'to': z, 'switches': sw,
                                     'gross_vs_SPY': es(g, b), 'net_vs_SPY_switch_0.20pct': es(n, b),
                                     'hold_2007_net_vs_SPY': es(n, b, HS, z) if a < HS else None,
                                     'static_etf_vs_SPY': es({m: e[m] for m in g}, b),
                                     'sharpe_net': shp(n), 'sharpe_spy': shp(b),
                                     'maxdd_net_pct': round(N.maxdd(n) * 100, 1), 'maxdd_spy_pct': round(N.maxdd(b) * 100, 1)}
    out['note'] = 'Yahoo の調整後終値（配当込み）。今も在る ETF だけ（生き残り）。USMV は楽天の海外ETF一覧に無い。切替え1回 0.20%。税は入れていない（課税口座では売るたびに 20.315%、NISA の成長投資枠は売った枠が翌年まで戻らない）'
    return out


# ───────────────────────── 検算 ─────────────────────────
def git_sha(path):
    try:
        return subprocess.run(['git', 'log', '-1', '--format=%H', '--', path], cwd=BASE, capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa
        return None


def data_sanity(rules):
    s = {}
    tool_sha = hashlib.sha256(open(os.path.join(BASE, 'night', 'nx_sentcond_data.py'), 'rb').read()).hexdigest()
    s['data_tool_sha256'] = {'now': tool_sha, 'prereg': EXP_DATA_TOOL_SHA, 'match': tool_sha == EXP_DATA_TOOL_SHA}
    s['regime_sha256'] = {'stored': SIGF['regime_sha256'], 'recomputed_from_stored_signals': D.regime_sha(SIGF['signals']),
                          'prereg': EXP_REGIME_SHA, 'match': True}
    s['regime_sha256_2019'] = {'stored': SIGF['regime_sha256_2019'], 'prereg': EXP_REGIME_SHA19, 'match': True}
    # 信号を今の道具と今の xlsx で作り直し、保存された信号と1つ残らず一致するか（キャッシュが道具の出力そのものか）
    d, xsha = D.load_bw()
    s['sentiment_xlsx_sha256'] = {'now': xsha, 'prereg': EXP_XLSX_SHA, 'match': xsha == EXP_XLSX_SHA}
    rebuilt = D.build(d)
    s['rebuilt_regime_sha256'] = D.regime_sha(rebuilt)
    s['rebuilt_matches_prereg'] = s['rebuilt_regime_sha256'] == EXP_REGIME_SHA
    maxdiff = 0.0
    for k, sv in rebuilt.items():
        for t, v in sv.items():
            maxdiff = max(maxdiff, abs(v['S'] - SIG[k][t]['S']))
    s['rebuilt_vs_stored_max_abs_S_diff'] = maxdiff
    assert s['rebuilt_matches_prereg'] and maxdiff < 1e-9
    # main の各判断に使った成分の月（cefd・nipo ≤ t−1、ripo・pdnd ≤ t−13、s ≤ t−3、窓の終わり = t）
    spec = D.SPECS['main']
    want = {'cefd': 1, 'nipo12': 1, 'ripoam': 13, 'pdnd': 13, 's': 3}
    assert spec == want, spec
    P = D.proxies(d, 'exclude')
    V = D.vectors(P, spec)
    vt = sorted(V)
    log = {}
    for t, v in SIG['main'].items():
        comp = {k: add(t, -spec[k]) for k in D.PROXIES}
        assert comp['cefd'] <= add(t, -1) and comp['nipo12'] <= add(t, -1) and comp['ripoam'] <= add(t, -13) and comp['pdnd'] <= add(t, -13) and comp['s'] <= add(t, -3)
        assert V[t] == [P[k][comp[k]] for k in D.PROXIES]
        assert v['n'] == sum(1 for x in vt if x <= t), (t, v['n'])  # 窓 = そろう最初の月〜t
        log[t] = comp
    s['main_component_months_checked'] = len(log)
    s['main_component_months_example'] = {str(t): {k: m for k, m in log[t].items()} for t in (min(log), 200612, max(log))}
    s['main_window_first_month'] = vt[0]
    s['main_window_min_months'] = min(v['n'] for v in SIG['main'].values())
    # 持つ月は判断の月の後だけ
    for r in rules:
        for m, t in r['src'].items():
            assert t is None or t < m
    s['hold_month_after_decision'] = '全規則の全月で 判断の月 < 持つ月 を確かめた（choice_switch・choice_annual の assert）'
    # 系列の範囲と欠け
    cov = {}
    for k, ser in LEGR.items():
        ms = [m for m in months(MAIN_A, LAST)]
        cov[k] = {'first': min(ser), 'last': max(ser), 'missing_in_1970-08..2026-08': sum(1 for m in ms if m not in ser)}
    s['legs_coverage'] = cov
    s['benchmark'] = 'French Mkt = Mkt-RF + RF（総リターン）。規則も French の VW の総リターン＝総リターンどうし。C5 は JKP の超過どうし'
    s['french_last_month'] = LAST
    s['payers_weight_example'] = {str(m): PAYERS_W[m] for m in (197008, 200701, 202602) if m in PAYERS_W}
    s['cost_identity'] = '全規則・全費用水準で 費用前−費用後 の合計 = 切替えの費用 + 組の中の入れ替え を確かめた（simulate の帳簿・誤差 < 1e-12）'
    return s


# ───────────────────────── ★事後（結果を見た後に足した診断・格付けには使わない） ─────────────────────────
def _cagr_diff_pct(s, b, ms):
    if not ms:
        return None
    gs = math.exp(math.fsum(math.log1p(s[m]) for m in ms) * 12 / len(ms)) - 1
    gb = math.exp(math.fsum(math.log1p(b[m]) for m in ms) * 12 / len(ms)) - 1
    return round((gs - gb) * 100, 3)


def post_hoc(results):
    """★事後: 全規則が C（C1 の訓練 t≥2 を1本も満たさない）と出た後に、『勝ちの中身』を診断するために足した。
    どれも事前登録に無い切り方で、格付けには一切使わない"""
    ph = {'label': '事後（結果を見た後の診断。格付けには使わない）'}
    byid = {x['id']: x for x in results}
    main = regime('main')
    # PH1: 傾き（いつも持つ分）と時期選び（心理で持つ月を選んだ分）の分解。規則の超過 = D·e（e = 堅い組 − Mkt）
    #      mean(D·e) = mean(D)·mean(e) ＋ cov(D, e)（母共分散）
    dec = {}
    for rid, leg in (('P1_BIGHiOP', 'BIGHiOP'), ('P2_VARLo20', 'VARLo20'), ('P3_BETALo20', 'BETALo20'), ('P4_DPHi30', 'DPHi30'), ('P5_HARD4', 'HARD4'),
                     ('E13_RESVAR', 'RESVARLo20'), ('E14_PAYERS', 'PAYERS')):
        dec[rid] = {}
        for p, (a, z) in {'train': (MAIN_A, TE), 'hold': (HS, MAIN_Z), 'full': (MAIN_A, MAIN_Z)}.items():
            ms = [m for m in months(a, z) if add(m, -1) in main]
            Dv = np.array([1.0 if main[add(m, -1)] else 0.0 for m in ms])
            e = np.array([LEGR[leg][m] - MKT[m] for m in ms])
            dec[rid][p] = {'rule_ex_pct_ann': round(float(np.mean(Dv * e)) * 1200, 2),
                           'tilt_part_pct_ann（high の割合×いつも持つ超過）': round(float(np.mean(Dv) * np.mean(e)) * 1200, 2),
                           'timing_part_pct_ann（cov(D,e)）': round(float(np.mean(Dv * e) - np.mean(Dv) * np.mean(e)) * 1200, 2),
                           'high_share': round(float(np.mean(Dv)), 3), 'static_ex_pct_ann': round(float(np.mean(e)) * 1200, 2)}
    ph['PH1_tilt_vs_timing'] = dec
    # PH2: 偽の信号（循環ずらし）を訓練・保有に分けて（事前登録の PLACEBO は全期間だけ）
    decm = sorted(t for t in main if MAIN_A <= add(t, 1) <= MAIN_Z)
    hold_m = [add(t, 1) for t in decm]
    seq = np.array([1.0 if main[t] else 0.0 for t in decm])
    Nn = len(seq)
    plc = {}
    for leg in ('HARD4', 'BIGHiOP', 'VARLo20', 'BETALo20', 'DPHi30'):
        hard = np.array([LEGR[leg][m] for m in hold_m])
        mk_ = np.array([MKT[m] for m in hold_m])
        idx = {'train': np.array([m <= TE for m in hold_m]), 'hold': np.array([m >= HS for m in hold_m]), 'full': np.ones(Nn, bool)}
        plc[leg] = {}
        for p, msk in idx.items():
            gb = math.exp(np.mean(np.log1p(mk_[msk])) * 12) - 1

            def cd(h):
                r = mk_[msk] + h[msk] * (hard[msk] - mk_[msk])
                return (math.exp(np.mean(np.log1p(r)) * 12) - 1 - gb) * 100
            real = cd(seq)
            dist = np.array([cd(np.roll(seq, k)) for k in range(24, Nn - 24 + 1)])
            plc[leg][p] = {'real_cagr_diff_pct': round(real, 3), 'share_shifts_ge_real': round(float(np.mean(dist >= real)), 4),
                           'shift_p50': round(float(np.median(dist)), 3), 'shift_p95': round(float(np.percentile(dist, 95)), 3), 'n_shifts': len(dist)}
    ph['PH2_placebo_by_period'] = plc
    # PH3: 保有期間の暦年ごとの幾何の超過と、1年抜いた保有期間の幾何の年率差（どの年に勝ちが寄っているか）
    yr = {}
    for rid in ('P1_BIGHiOP', 'P2_VARLo20', 'P4_DPHi30', 'P5_HARD4', 'E3_BOTH_BETA', 'E4_BOTH_DP', 'E5_BOTH_HARD4'):
        g = byid[rid]['_g']
        ms = [m for m in sorted(g) if HS <= m <= MAIN_Z]
        years = sorted(set(m // 100 for m in ms))
        per = {}
        for y in years:
            mm = [m for m in ms if m // 100 == y]
            ws = math.prod(1 + g[m] for m in mm)
            wb = math.prod(1 + MKT[m] for m in mm)
            per[y] = round((ws / wb - 1) * 100, 2)
        loo = {y: _cagr_diff_pct(g, MKT, [m for m in ms if m // 100 != y]) for y in years}
        top = sorted(per.items(), key=lambda kv: -kv[1])[:3]
        worst_loo = min(loo.items(), key=lambda kv: kv[1])
        rr = byid[rid]
        legs_yr = {}
        for y, _ in top:
            mm = [m for m in ms if m // 100 == y]
            legs_yr[y] = {'rule_pct': round((math.prod(1 + g[m] for m in mm) - 1) * 100, 1),
                          'mkt_pct': round((math.prod(1 + MKT[m] for m in mm) - 1) * 100, 1),
                          'high_months': sum(1 for m in mm if main.get(add(m, -1))), 'months': len(mm)}
        yr[rid] = {'hold_cagr_diff_pct': _cagr_diff_pct(g, MKT, ms), 'relative_return_by_year_pct': per,
                   'top3_years': top, 'top3_years_detail': legs_yr, 'drop_one_year_min_cagr_diff': worst_loo,
                   'years_positive': sum(1 for v in per.values() if v > 0), 'years': len(per)}
    ph['PH3_hold_by_year'] = yr
    # PH4: C5 の7か国で、いつも堅い側を持つ（傾き）と、心理で切り替える（規則）の差＝時期選びの分
    c5s = {}
    for c in C5_COUNTRIES:
        jm = N.jkp_mkt(c, 'vw_cap')
        for rid, legs in C5_CHARS.items():
            sers = [N.jkp_portfolios(c, ch, 'vw_cap')[side] for ch, side in legs]
            common = sorted(set.intersection(*[set(s_) for s_ in sers]))
            a = max(common[0], MAIN_A)
            ms = [m for m in months(a, C5_END) if m in jm and all(m in s_ for s_ in sers) and add(m, -1) in main]
            hard = {m: sum(s_[m] for s_ in sers) / len(sers) for m in ms}
            rule = {m: (hard[m] if main[add(m, -1)] else jm[m]) for m in ms}
            c5s[f'{c}|{rid}'] = {'rule_cagr_diff': _cagr_diff_pct(rule, jm, ms), 'static_cagr_diff': _cagr_diff_pct(hard, jm, ms),
                                 'rule_minus_half_static': None}
            Dv = np.array([1.0 if main[add(m, -1)] else 0.0 for m in ms])
            e = np.array([hard[m] - jm[m] for m in ms])
            c5s[f'{c}|{rid}']['timing_part_pct_ann'] = round(float(np.mean(Dv * e) - np.mean(Dv) * np.mean(e)) * 1200, 2)
            c5s[f'{c}|{rid}']['tilt_part_pct_ann'] = round(float(np.mean(Dv) * np.mean(e)) * 1200, 2)
            c5s[f'{c}|{rid}'].pop('rule_minus_half_static')
    summ = {}
    for rid in C5_CHARS:
        xs = [c5s[f'{c}|{rid}'] for c in C5_COUNTRIES]
        summ[rid] = {'static_positive_countries': sum(1 for x in xs if x['static_cagr_diff'] > 0),
                     'timing_part_positive_countries': sum(1 for x in xs if x['timing_part_pct_ann'] > 0),
                     'rule_positive_countries': sum(1 for x in xs if x['rule_cagr_diff'] > 0)}
    ph['PH4_c5_tilt_vs_timing'] = {'summary': summ, 'detail': c5s,
                                   'note': 'JKP の超過どうし・費用前。時期選びの分 = cov(D, 堅い側 − 国の市場)。国の中の期間は C5 と同じ（1982〜1990 起点・2025-12 まで）'}
    return ph


DEVIATIONS = [
    {'item': 'E8（年1回の切替え）の持つ月の範囲', 'prereg': '期間の記載なし（P5 の変形）',
     'implemented': '主の型と同じ 1970-08〜2026-02。前年12月末の判断が無い 1970-08〜12 の5か月は『信号なし＝市場』（事前登録 signal.missing）。2026-03〜08 は信号があるが P5 と比べられるよう 2026-02 で切った',
     'affects_grade': '無し（C1 の訓練 t は 1970-08 起点でも届かない）'},
    {'item': 'E12（lag0）の持つ月の範囲', 'prereg': '期間の記載なし',
     'implemented': 'lag0 の信号は判断 1970-06（持つ月 1970-07）からあるが、主の型と同じ 1970-08 から測った。最後の判断は 2025-12（持つ月 2026-01）なので 2026-02 は信号なし＝市場',
     'affects_grade': '無し'},
    {'item': '規則を始める最初の月の買いの費用', 'prereg': '切替えと組の中の入れ替えの費用だけを定める',
     'implemented': '最初の月の買いには費用を掛けない（相手の Mkt にも掛けない）。掛けても 0.10%〜0.30% を1回だけ',
     'affects_grade': '無し（55年で1回）'},
    {'item': 'C5 の P5（4つの堅い側の等分）の欠け', 'prereg': '『持つはずの堅い側がその月に欠けたら市場を持つ』',
     'implemented': 'P5 は4つそろう月から。high の月にどれかが欠けたら国の市場を持つ（同じ規則を等分にも当てた）。実際の欠けは全国・全規則で0か月',
     'affects_grade': '無し'},
    {'item': 'COND_SPREAD の NW t', 'prereg': 'high の月のダミーへの回帰・NW t・ラグ12',
     'implemented': 'numpy で OLS と HAC（Bartlett・ラグ12・n で割る＝nx_common.nw_t と同じ重み）を自作。小標本の補正なし',
     'affects_grade': '無し（報告だけ）'},
    {'item': 'Holm の元の p', 'prereg': 'p_two(NW t)',
     'implemented': 'excess_stats が丸める前の t（nx_common.nw_t）から p_two を計算した。丸めた p との差は 4桁目以下',
     'affects_grade': '無し'},
    {'item': '実物の ETF の期間', 'prereg': 'VIG 2006-05〜・DVY 2003-11〜・USMV 2011-10〜（設定月）',
     'implemented': 'Yahoo の月次の調整後終値から作ったリターンの最初の月（VIG 2006-06・DVY 2003-12・USMV 2011-11）から。main は 2026-02、practical は 2026-08 まで（2026-09 は途中の月なので使わない）',
     'affects_grade': '無し（報告だけ）'},
]


def build_summary(out):
    T = {x['id']: x for x in out['tested']}

    def g(i, p='hold', k='cagr_diff', src='gross'):
        v = (T[i][src].get(p) or {})
        return v.get(k)

    ctrl = out['controls_report_only']
    plc = ctrl['PLACEBO_shift_HARD4']
    ph = out['post_hoc']
    cs = ctrl['COND_SPREAD']
    diffs = [(leg, p, cs[leg][p]['diff_high_minus_low_pct_ann'], cs[leg][p]['nw_t_diff']) for leg in cs for p in ('train', 'hold', 'full')]
    npos = sum(1 for d_ in diffs if d_[2] > 0)
    grades = out['grade_summary']
    maxtrain = max(out['tested'], key=lambda x: (x['gross']['train'] or {}).get('t') or -9)
    lines = []
    lines.append(f"格付け: 主の族5本・探索の族14本、19本すべて C（S/A/B は0本）。全員が C1（訓練 1970-08〜2006-12 の NW t≥2.0）で落ちた。訓練の t の最大は {maxtrain['id']} の {maxtrain['gross']['train']['t']}。")
    for i in ('P1_BIGHiOP', 'P2_VARLo20', 'P3_BETALo20', 'P4_DPHi30', 'P5_HARD4'):
        x = T[i]
        lines.append(f"{i}: 訓練 {x['gross']['train']['ex_ann']:+}%/年 t{x['gross']['train']['t']}／保有(2007-01〜2026-02) 算術 {x['gross']['hold']['ex_ann']:+} 幾何 {x['gross']['hold']['cagr_diff']:+} t{x['gross']['hold']['t']}（費用後 {x['net']['hold']['cagr_diff']:+}）／全期間 t{x['gross']['full']['t']}／20年窓 {x['roll20_net']['win_rate']}／C5 {x['repl']['positive']}/7／シャープ 訓練 {x['sharpe']['train']['rule_net']} 対 {x['sharpe']['train']['mkt']}・保有 {x['sharpe']['hold']['rule_net']} 対 {x['sharpe']['hold']['mkt']}／Holm {x['family_holm_p']} → {x['grade']}")
    e3 = T['E3_BOTH_BETA']
    y3 = ph['PH3_hold_by_year']['E3_BOTH_BETA']
    t3 = y3['top3_years'][:2]
    d3 = y3['top3_years_detail']
    lines.append(f"探索で保有期間が最も大きかったのは E3（high→BETA Lo 20・low→BETA Hi 20）: 保有 幾何 {e3['gross']['hold']['cagr_diff']:+}%/年 t{e3['gross']['hold']['t']}（費用後 {e3['net']['hold']['cagr_diff']:+}）だが訓練 t{e3['gross']['train']['t']}・全期間の最大下落 {e3['maxdd_pct']['rule_net_full']}%（Mkt {e3['maxdd_pct']['mkt_full']}%）。★事後: 保有の勝ちは " + '・'.join(f"{y} 年（規則 {d3[y]['rule_pct']:+}% 対 Mkt {d3[y]['mkt_pct']:+}%・心理が高い月 {d3[y]['high_months']}/{d3[y]['months']}）" for y, _ in t3) + f" に寄る（1年抜いた最小 {y3['drop_one_year_min_cagr_diff'][1]:+}）。")
    lines.append(f"BW の予言の向き（COND_SPREAD・報告）: 堅い組の対 Mkt の超過は、心理が高い後のほうが低い後より大きい——5組×3期間の {npos}/{len(diffs)} で正（全期間 t {min(d_[3] for d_ in diffs if d_[1]=='full')}〜{max(d_[3] for d_ in diffs if d_[1]=='full')}、保有 t {min(d_[3] for d_ in diffs if d_[1]=='hold')}〜{max(d_[3] for d_ in diffs if d_[1]=='hold')}）。向きは論文（1963〜2001）どおりに保有期間でも続いたが、差は年 {min(d_[2] for d_ in diffs):+}〜{max(d_[2] for d_ in diffs):+}%（算術）で、t が2に届いたのは {sum(1 for d_ in diffs if (d_[3] or 0) >= 2.0)}/{len(diffs)}。")
    lines.append(f"偽の信号（循環ずらし {plc['n_shifts']} 通り・報告）: P5 の全期間の幾何の差 {plc['real_cagr_diff_pct']:+}%/年は、ずらした全 {plc['n_shifts']} 通りより大きい（最大 {plc['shift_cagr_diff_pct']['max']}、中央 {plc['shift_cagr_diff_pct']['p50']}）。★事後で期間を分けると 訓練 {ph['PH2_placebo_by_period']['HARD4']['train']['share_shifts_ge_real']}・保有 {ph['PH2_placebo_by_period']['HARD4']['hold']['share_shifts_ge_real']} の割合のずらしが本物以上＝時期は偶然より当たっているが、ずらしどうしは強く重なり独立な試行ではない。")
    st = ctrl['CTRL_static']['HARD4']
    lines.append(f"無条件に HARD4 を持つ対照: 保有 幾何 {st['gross']['hold']['cagr_diff']:+}（訓練 {st['gross']['train']['cagr_diff']:+}）。★事後の分解（P5）: 時期選びの分 cov(D,e) は 訓練 {ph['PH1_tilt_vs_timing']['P5_HARD4']['train']['timing_part_pct_ann（cov(D,e)）']:+}・保有 {ph['PH1_tilt_vs_timing']['P5_HARD4']['hold']['timing_part_pct_ann（cov(D,e)）']:+}%/年で、傾きの分は {ph['PH1_tilt_vs_timing']['P5_HARD4']['train']['tilt_part_pct_ann（high の割合×いつも持つ超過）']:+}／{ph['PH1_tilt_vs_timing']['P5_HARD4']['hold']['tilt_part_pct_ann（high の割合×いつも持つ超過）']:+}＝勝ちの大半は『心理で選んだ』分。")
    y5 = ph['PH3_hold_by_year']['P5_HARD4']
    lines.append(f"★事後: 保有期間の勝ちは少数の年に寄る——P5 の最大は {y5['top3_years'][0][0]} 年（相対 {y5['top3_years'][0][1]:+}%）、その年を抜くと保有の幾何の差は {y5['drop_one_year_min_cagr_diff'][1]:+}%/年（勝った年は {y5['years_positive']}/{y5['years']}）。P4 は 2022 年を抜くと {ph['PH3_hold_by_year']['P4_DPHi30']['drop_one_year_min_cagr_diff'][1]:+}。")
    v19 = ctrl['CTRL_vintage2019_HARD4']
    lines.append(f"成分の改訂（2019 年版 vs 2026 年版・1970-08〜2019-02）: 信号の一致 {v19['regime_agreement_share']}。P5 の訓練の幾何の差 {v19['vintage2019']['gross']['train']['cagr_diff']:+}（2026 年版 {v19['main_same_span']['gross']['train']['cagr_diff']:+}）、2007-01〜2019-02 は {v19['vintage2019']['gross']['hold']['cagr_diff']:+}（2026 年版 {v19['main_same_span']['gross']['hold']['cagr_diff']:+}）＝改訂だけで結果が約1ポイント動く。")
    ps = ctrl['CTRL_pub_SENT_HARD4']
    lines.append(f"後知恵ありの公開 SENT で切り替えると 全期間 t{ps['gross']['full']['t']}・訓練 t{ps['gross']['train']['t']}（実時間の P5 は {T['P5_HARD4']['gross']['full']['t']}・{T['P5_HARD4']['gross']['train']['t']}）。E10（公開ファイルの年1回更新だけを使う個人の遅れ）は保有 幾何 {g('E10_PRACTICAL_HARD4'):+}・費用後 {g('E10_PRACTICAL_HARD4', src='net'):+}。")
    r = out['real_instrument_check']
    lines.append(f"実物（報告）: main の信号で VIG↔SPY は費用後 {r['R1_VIG|main']['net_vs_SPY_switch_0.20pct']['cagr_diff']:+}%/年（VIG をいつも持つと {r['R1_VIG|main']['static_etf_vs_SPY']['cagr_diff']:+}）、DVY↔SPY {r['R2_DVY|main']['net_vs_SPY_switch_0.20pct']['cagr_diff']:+}（いつも {r['R2_DVY|main']['static_etf_vs_SPY']['cagr_diff']:+}）、USMV↔SPY {r['R3_USMV|main']['net_vs_SPY_switch_0.20pct']['cagr_diff']:+}（いつも {r['R3_USMV|main']['static_etf_vs_SPY']['cagr_diff']:+}）。心理の切替えは『いつも持つ』より負けを小さくするが、SPY に勝つのは VIG だけで僅差。")
    c5p = ph['PH4_c5_tilt_vs_timing']['summary']['P5_HARD4']
    lines.append(f"★事後: C5 の P5 の 7/7 は、堅い側をいつも持つだけでも {c5p['static_positive_countries']}/7 で正（米国外では堅い側の無条件の上乗せが大きい）。時期選びの分 cov(D,e) が正の国は {c5p['timing_part_positive_countries']}/7。")
    p5 = T['P5_HARD4']
    tops = ' と '.join(str(y) for y, _ in y5['top3_years'][:2])
    lines.append(f"結論: 心理の高い後に堅い株へ寄せる規則は、BW の向きどおりに米国の保有期間でも米国外7か国でも小さく働いた（P5 は C5 {p5['repl']['positive']}/7・20年窓 {p5['roll20_net']['win_rate']}・シャープは訓練・保有とも Mkt を上回る）。だが超過は 訓練 {p5['gross']['train']['ex_ann']:+}・保有 {p5['gross']['hold']['ex_ann']:+}%/年（算術）と小さく、訓練期間の t が2に届かず（{p5['gross']['train']['t']}）、保有期間の勝ちも {tops} 年に寄っていて t{p5['gross']['hold']['t']}。線（C1〜C8）では勝ちと言えない＝19本すべて C。線は下げていない。")
    return lines


# ───────────────────────── 本体 ─────────────────────────
def main():
    rules = build_rules()
    sanity = data_sanity(rules)
    side = c5_side_check()
    sanity['jkp_side_check'] = side
    results = [evaluate(r) for r in rules]
    for r, x in zip(rules, results):
        x['first_signal_hold_month'] = r['first_signal_hold_month']
    # Holm（族ごと・保有期間・費用前・両側 p = p_two(NW t)）
    holm = {}
    for fam in ('P', 'E'):
        xs = [x for x in results if x['family'] == fam]
        raw = {x['id']: x['hold_p_two_raw'] for x in xs}
        hp = N.holm(raw)
        holm[fam] = {'n': len(xs), 'raw_p_hold_gross_two_sided': {k: (round(v, 6) if v is not None else None) for k, v in raw.items()}, 'holm_p': hp}
        for x in xs:
            x['family_holm_p'] = hp.get(x['id'])
    c5_detail, c5_sum = c5_eval()
    # 格付け
    for x in results:
        repl = None
        if x['family'] == 'P':
            cs = c5_sum[x['id']]
            repl = {'regions': cs['regions'], 'positive': cs['positive']}
        x['repl'] = repl
        sp = {'train': (x['sharpe']['train']['rule_net'], x['sharpe']['train']['mkt']),
              'hold': (x['sharpe']['hold']['rule_net'], x['sharpe']['hold']['mkt'])}
        g, c = N.grade(full=x['gross']['full'], train=x['gross']['train'], hold=x['gross']['hold'], roll20=x['roll20_net'],
                       cost_hold=x['net']['hold'], repl=repl, family_holm_p=x['family_holm_p'], sharpe_pair=sp, leveraged_or_timing=True)
        x['grade'] = g
        x['criteria'] = c
        x['grade_inputs'] = {'full': '費用前の全期間', 'train': '費用前の訓練', 'hold': '費用前の保有', 'roll20': '費用後（判定の費用）の転がる20年窓',
                             'cost_hold': '費用後（判定の費用）の保有', 'repl': repl, 'family_holm_p': x['family_holm_p'], 'sharpe_pair': sp,
                             'grader': 'nx_common.grade（criteria_long_history）'}
        if x['family'] == 'E':
            x['grade_note'] = '探索（C5 は測らない＝N/A。探索の A には C3 が要る）'
    posthoc = post_hoc(results)
    for x in results:
        x.pop('_g'), x.pop('_n')
    ctrl = {'CTRL_static': static_controls(), 'COND_SPREAD': cond_spread()}
    ctrl.update(controls())
    sw = {}
    for nm in ('main', 'orth', 'practical', 'nobwlag', 'lag0'):
        reg = regime(nm)
        ha, hz = (197105, LAST) if nm == 'practical' else (MAIN_A, MAIN_Z)
        for p, (a, z) in {'train': (ha, TE), 'hold': (HS, hz), 'full': (ha, hz)}.items():
            tt = [add(m, -1) for m in months(a, z) if add(m, -1) in reg]  # 判断の月（持つ月 = 判断の月 + 1）
            v = [reg[t] for t in tt]
            if not v:
                continue
            runs, cur, curv = [], 0, None
            for x in v:
                if x == curv:
                    cur += 1
                else:
                    if curv is not None:
                        runs.append((curv, cur))
                    curv, cur = x, 1
            runs.append((curv, cur))
            hr = [n for q, n in runs if q]
            sw[f'{nm}|{p}'] = {'decision_months': len(v), 'first_hold': add(tt[0], 1), 'last_hold': add(tt[-1], 1),
                               'high_share': round(sum(v) / len(v), 3), 'switches': sum(1 for a_, b_ in zip(v, v[1:]) if a_ != b_),
                               'high_runs': len(hr), 'high_run_lengths_months': hr}
    ctrl['SWITCH_COUNT'] = sw
    real = real_etf_checks()
    grade_summary = {x['id']: x['grade'] for x in results}
    table = []
    for x in results:
        table.append({'id': x['id'], 'grade': x['grade'],
                      'train_ex_ann': (x['gross']['train'] or {}).get('ex_ann'), 'train_t': (x['gross']['train'] or {}).get('t'),
                      'hold_ex_ann': (x['gross']['hold'] or {}).get('ex_ann'), 'hold_cagr_diff': (x['gross']['hold'] or {}).get('cagr_diff'),
                      'hold_t': (x['gross']['hold'] or {}).get('t'),
                      'full_t': (x['gross']['full'] or {}).get('t'),
                      'hold_net_cagr_diff': (x['net']['hold'] or {}).get('cagr_diff'),
                      'roll20_net_win': (x['roll20_net'] or {}).get('win_rate'),
                      'sharpe_train_rule_vs_mkt': [x['sharpe']['train']['rule_net'], x['sharpe']['train']['mkt']],
                      'sharpe_hold_rule_vs_mkt': [x['sharpe']['hold']['rule_net'], x['sharpe']['hold']['mkt']],
                      'repl': x['repl'], 'holm_p': x['family_holm_p'],
                      'criteria': x['criteria']})
    out = {
        'angle': 'nx_sentcond',
        'prereg': {'path': 'out/nx_sentcond_prereg.json', 'commit': git_sha('out/nx_sentcond_prereg.json')},
        'script': {'path': 'night/nx_sentcond.py'},
        'stance': PR['stance_before_results'],
        'benchmark': PR['benchmark'],
        'conventions': [
            '持つ月 m の持ち物は判断の月 m−1 の信号で決める（main の成分は cefd・nipo が t−1、ripo・pdnd が t−13、s が t−3 まで・拡大窓の主成分）',
            '信号の無い月は市場（欠測を『心理が低い』と読まない）',
            '主の型と、その変形（E7・E8・E9・E11・E12・対照）は持つ月 1970-08〜2026-02 で測る（E9 の最後の2か月・E8 の 1970-08〜12・E12 の 2026-02 は信号なし＝市場）。E10 だけ事前登録どおり 1971-05〜2026-08',
            '費用: 切替え1回 = 売る側の c + 買う側の c（新しい組の最初の月から）＋ 持つ月ごとに 2×c×f/12。最初の月の買いには掛けない（相手の Mkt にも掛けない）',
            'Holm の p は p_two(NW t)（丸める前の t）',
            'excess_stats の ex_ann・cagr_diff は %/年、te・vol も %',
        ],
        'deviations_from_prereg': DEVIATIONS,
        'data_sanity': sanity,
        'holm': holm,
        'grade_summary': grade_summary,
        'table': table,
        'tested_count': len(results),
        'tested': results,
        'c5': {'summary': c5_sum, 'detail': c5_detail, 'unit': PR['criteria']['C5_independent_unit']},
        'controls_report_only': ctrl,
        'real_instrument_check': real,
        'post_hoc': posthoc,
        'known_limits': PR['known_limits'],
    }
    out['generated'] = datetime.date.today().isoformat()
    out['summary_ja'] = build_summary(out)
    best = max(results, key=lambda x: ((x['grade'] == 'S') * 4 + (x['grade'] == 'A') * 3 + (x['grade'] == 'B') * 2, sum(1 for v in x['criteria'].values() if v is True)))
    out['best'] = {'id': best['id'], 'grade': best['grade'], 'criteria_passed': sum(1 for v in best['criteria'].values() if v is True),
                   'why': '格付けが最も高く、同じ格付けの中で合格した基準の数が最も多い規則（全部 C なので『最も惜しい』の意味）'}
    out['headline'] = out['summary_ja'][0]
    # 順番を読みやすく
    order = ['generated', 'angle', 'headline', 'summary_ja', 'best', 'grade_summary', 'table', 'deviations_from_prereg', 'prereg', 'script', 'stance',
             'benchmark', 'conventions', 'data_sanity', 'holm', 'c5', 'tested_count', 'tested', 'controls_report_only', 'real_instrument_check', 'post_hoc', 'known_limits']
    return {k: out[k] for k in order if k in out} | {k: v for k, v in out.items() if k not in order}


if __name__ == '__main__':
    t0 = datetime.datetime.now()
    out = main()
    extra = os.environ.get('NX_SENTCOND_EXTRA')
    if extra and os.path.exists(extra):
        out.update(json.load(open(extra)))
    p = N.save(OUTNAME, out)
    print('→', p, '所要', datetime.datetime.now() - t0)
    for r in out['table']:
        print(r['id'], r['grade'], 'train', r['train_ex_ann'], r['train_t'], 'hold', r['hold_ex_ann'], r['hold_cagr_diff'], r['hold_t'],
              'full_t', r['full_t'], 'net_hold', r['hold_net_cagr_diff'], 'roll', r['roll20_net_win'], 'sh', r['sharpe_train_rule_vs_mkt'], r['sharpe_hold_rule_vs_mkt'],
              'repl', r['repl'], 'holm', r['holm_p'])
