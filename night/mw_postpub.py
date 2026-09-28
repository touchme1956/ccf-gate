#!/usr/bin/env python3
"""night/mw_postpub.py — 市場に勝てる歴史検証（角度 postpub: 公表の実時間での採用と、公表後の減衰）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて」。読むだけ（門・採点・配分には不使用）。
事前登録: out/mw_postpub_prereg.json（この道具の最初の版と一緒に、測る前にコミット）。線は out/mw_prereg.json。

問い: 論文が公表された特徴（153個・JKP）の『良い側』（公表された向き）の三分位を、公表された年の翌年から
      順に持っていく投資家（実時間の採用者）は、上場廃止も含む米国の純粋な時価加重市場（French Mkt）に勝ったか。

データ: JKP 米国 all_factors の三分位ポートフォリオ（'vw'＝上限なしの時価加重・超過リターン・〜2025-12）、
        JKP Factor Details（出典・公表年・標本期間・t値・向き・群）、French の Mkt-RF と RF。
        地域: JKP 'world_ex_us' / 'developed'（米国を含まないことを確認済み）/ 'jpn' / 'emerging' の同じ三分位と地域の 'vw' 市場。

使い方: python3 night/mw_postpub.py --check   … データと解析だけ確かめる（戦略と市場の比較は計算しない）
        python3 night/mw_postpub.py           … 全部計算して out/mw_postpub.json へ
"""
import sys, os, re, json, math, collections, subprocess, statistics as S, argparse, csv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402


class _FastStats:
    """mw_common.excess_stats は β の式の中で S.mean を要素ごとに呼び直す（O(n²)）うえ、標準の statistics は
    分数の厳密計算で遅い（1200か月で1回数秒）。mw_common は他の道具と共有なので書き換えず、ここで
    mw_common が参照する統計の関数だけを math.fsum の同じ式に差し替える（値は丸めた桁で一致を確認: 合成データで
    excess_stats の全項目が同一）。平均は同じリストの呼び直しをその場で覚える（リストは書き換えられない）"""
    _last = None

    @staticmethod
    def mean(x):
        c = _FastStats._last
        if c is not None and c[0] is x:
            return c[1]
        xs = x if isinstance(x, (list, tuple)) else list(x)
        v = math.fsum(xs) / len(xs)
        if isinstance(x, (list, tuple)):
            _FastStats._last = (x, v)
        return v

    @staticmethod
    def pvariance(x):
        m = math.fsum(x) / len(x)
        return math.fsum((v - m) ** 2 for v in x) / len(x)

    @staticmethod
    def stdev(x):
        m = math.fsum(x) / len(x)
        return math.sqrt(math.fsum((v - m) ** 2 for v in x) / (len(x) - 1))


M.S = _FastStats  # 逸脱として記録（out/mw_postpub.json の deviations）

PREREG = 'mw_postpub_prereg.json'
OUT = 'mw_postpub.json'
COST = 0.003          # 片道売買100%あたり 0.30%（事前登録）
NMIN = 20             # 良い側の三分位の銘柄数がこれ未満の月は欠測扱い（0 と読まない）
MIN_ADOPTED = 3       # 採用が3特徴以上になった最初の月から評価を始める
REGIONS = ['world_ex_us', 'developed', 'jpn', 'emerging']
REG_START = 199001    # 地域の評価の始まり
DATA_END = 202512     # JKP の終わり
THEMES = ['Momentum', 'VALUE', 'INVESTMENT', 'Profitability', 'INTANGIBLES', 'TRADING FRICTIONS']
DETAILS = os.path.join(M.CACHE, 'jkp_factor_details.xlsx')
DETAILS_URL = 'https://raw.githubusercontent.com/bkelly-lab/ReplicationCrisis/master/GlobalFactors/Factor%20Details.xlsx'
OAP = os.path.join(M.CACHE, 'oap_SignalDoc.csv')

# ─────────── 回転率の仮定（年間・片道・三分位ポートフォリオ）＝事前登録の表 ───────────
TURN_RULES = [
    ('seas', lambda a: a.startswith('seas_'), 6.0, '季節性（同じ暦月の過去リターン・毎月ほぼ入れ替わる）'),
    ('ret21', lambda a: a in ('ret_1_0', 'rmax1_21d', 'rmax5_21d', 'rskew_21d', 'iskew_capm_21d', 'iskew_ff3_21d',
                              'iskew_hxz4_21d', 'coskew_21d'), 6.0, '21日のリターン系（持続性が低い）'),
    ('vol21', lambda a: a in ('rvol_21d', 'ivol_ff3_21d', 'ivol_capm_21d', 'ivol_hxz4_21d', 'beta_dimson_21d',
                              'bidaskhl_21d', 'zero_trades_21d', 'rmax5_rvol_21d'), 2.0, '21日の変動・流動性系（持続性あり）'),
    ('mom3', lambda a: a == 'ret_3_1', 2.5, '3か月の勢い'),
    ('mom', lambda a: a in ('ret_6_1', 'ret_9_1', 'ret_12_1', 'ret_12_7', 'resff3_6_1', 'resff3_12_1',
                            'prc_highprc_252d'), 1.5, '6〜12か月の勢い・52週高値'),
    ('surprise', lambda a: a in ('niq_su', 'saleq_su', 'ni_inc8q'), 1.5, '決算サプライズ（四半期）'),
    ('qacct', lambda a: a in ('niq_be', 'niq_at', 'niq_be_chg1', 'niq_at_chg1', 'saleq_gr1', 'ocfq_saleq_std'), 0.8,
     '四半期の会計値'),
    ('trade', lambda a: a in ('turnover_126d', 'turnover_var_126d', 'dolvol_126d', 'dolvol_var_126d', 'ami_126d',
                              'zero_trades_126d', 'zero_trades_252d', 'ivol_capm_252d', 'betadown_252d'), 0.6,
     '半年〜1年の売買・リスク系'),
    ('long', lambda a: a in ('ret_60_12', 'beta_60m', 'betabab_1260d', 'corr_1260d', 'market_equity', 'prc', 'age'), 0.3,
     '長期の価格・規模・年齢'),
    ('composite', lambda a: a in ('qmj', 'qmj_prof', 'qmj_growth', 'qmj_safety', 'mispricing_perf', 'mispricing_mgmt',
                                  'f_score', 'o_score', 'z_score', 'kz_index'), 0.6, '合成指標'),
]
TURN_DEFAULT = ('annual', 0.4, '年次の会計値・割安の比率（遅い）')


def turnover(abr):
    for key, f, t, desc in TURN_RULES:
        if f(abr):
            return t, key
    return TURN_DEFAULT[1], TURN_DEFAULT[0]


# ───────────────────────── 出典の表 ─────────────────────────
def _tnum(v):
    """標本内 t値: 数字が複数あれば絶対値の最小（控えめ）。N/A・None は不明（None）"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return abs(float(v))
    nums = re.findall(r'-?\d+(?:\.\d+)?', str(v))
    return min(abs(float(x)) for x in nums) if nums else None


def details():
    import openpyxl
    if not os.path.exists(DETAILS):
        M.get(DETAILS_URL, name='jkp_factor_details.xlsx', max_age_days=3650)
    wb = openpyxl.load_workbook(DETAILS, read_only=True)
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    h = rows[0]
    D = {}
    for r in rows[1:]:
        d = dict(zip(h, r))
        a = d.get('abr_jkp')
        if not a:
            continue
        cite = d.get('cite')
        m = re.search(r'\((\d{4})\)', cite or '')
        pub = int(m.group(1)) if m else None
        ys = re.findall(r'(\d{4})', str(d.get('in-sample period') or ''))
        is0, is1 = (int(ys[0]), int(ys[1])) if len(ys) >= 2 else (None, None)
        D[a] = {'cite': cite, 'pub': pub, 'is_start': is0, 'is_end': is1, 't_abs': _tnum(d.get('t-stat')),
                't_raw': d.get('t-stat'), 'group': (d.get('group') or '').strip(), 'direction': int(d['direction']),
                'significance': d.get('significance'), 'name': d.get('name_new') or d.get('name')}
        D[a]['good_pf'] = '3.0' if D[a]['direction'] == 1 else '1.0'
        D[a]['turn'], D[a]['turn_class'] = turnover(a)
    return D


def oap_crosscheck(D):
    """Open Source Asset Pricing の SignalDoc と公表年を照合（参考・判定には不使用）"""
    if not os.path.exists(OAP):
        try:
            M.get('https://raw.githubusercontent.com/OpenSourceAP/CrossSection/master/SignalDoc.csv', name='oap_SignalDoc.csv', max_age_days=3650)
        except Exception as e:  # noqa
            return {'status': f'取得失敗 {e}'}
    rows = list(csv.DictReader(open(OAP, encoding='utf-8', errors='replace')))
    out = {'matched': 0, 'same_year': 0, 'diff': []}
    for a, d in D.items():
        if not d['cite'] or not d['pub']:
            continue
        first = re.split(r'[ ,]', d['cite'].strip())[0].lower().replace('assness', 'asness').replace('jegedeesh', 'jegadeesh')
        cands = [r for r in rows if r.get('Authors', '').lower().startswith(first) and r.get('Year', '').isdigit()]
        if not cands:
            continue
        yrs = sorted(set(int(r['Year']) for r in cands), key=lambda y: abs(y - d['pub']))
        out['matched'] += 1
        if yrs[0] == d['pub']:
            out['same_year'] += 1
        else:
            out['diff'].append([a, d['cite'], yrs[0]])
    out['diff'] = out['diff'][:40]
    return out


# ───────────────────────── データ ─────────────────────────
def load_terciles(region):
    """{特徴: {'1.0': {ym: r}, '2.0': …, '3.0': …}}（超過・n≥NMIN の月だけ・欠測は入れない）"""
    P = collections.defaultdict(lambda: collections.defaultdict(dict))
    for r in M.jkp_rows(region, 'all_factors', 'portfolios', 'vw'):
        if r['ret'] in ('', 'NA', 'na') or r['n'] in ('', 'NA'):
            continue
        if float(r['n']) < NMIN:
            continue
        ym = M._ym(r['date'])
        if ym > DATA_END:
            continue
        P[r['name']][r['pf']][ym] = float(r['ret'])
    return P


def good_series(P, D):
    return {a: dict(P[a][D[a]['good_pf']]) for a in D if a in P and P[a].get(D[a]['good_pf'])}


# ───────────────────────── 実時間の採用者 ─────────────────────────
def adopter(G, D, chars, adopt, balanced=False, start_min=None):
    """chars のうち adopt[a]（yyyymm）以降の月に値のある特徴を等分で持つ。
    返り値: (リターン {ym: r}, 月ごとの採用数 {ym: n}, 月ごとの回転率(年・片道) {ym: t})。
    評価の始まり = 採用数が MIN_ADOPTED 以上になった最初の月（start_min があればそれ以降）"""
    months = sorted(set().union(*[set(G[a]) for a in chars if a in G])) if chars else []
    ret, cnt, trn = {}, {}, {}
    started = False
    for m in months:
        if start_min and m < start_min:
            continue
        act = [a for a in chars if a in G and adopt.get(a) is not None and adopt[a] <= m and m in G[a]]
        if not started:
            if len(act) < MIN_ADOPTED:
                continue
            started = True
        if not act:
            continue  # 欠測（0 と読まない）
        if balanced:
            gs = collections.defaultdict(list)
            for a in act:
                gs[D[a]['group']].append(a)
            wg = 1 / len(gs)
            w = {a: wg / len(v) for v in gs.values() for a in v}
        else:
            w = {a: 1 / len(act) for a in act}
        ret[m] = math.fsum(w[a] * G[a][m] for a in act)
        cnt[m] = len(act)
        trn[m] = math.fsum(w[a] * D[a]['turn'] for a in act)
    return ret, cnt, trn


def adopt_dates(D, lag=0):
    return {a: (d['pub'] + 1 + lag) * 100 + 1 for a, d in D.items() if d['pub']}


# ───────────────────────── 評価 ─────────────────────────
def to_total(ex, rf):
    return {k: v + rf[k] for k, v in ex.items() if k in rf}


def evaluate(s_ex, b_ex, rf, turn_hold, start=None):
    """s_ex・b_ex は超過（同じ基準）。総リターンへ直して比べる（算術の差は同じ・幾何の差を正しく）"""
    s, b = to_total(s_ex, rf), to_total(b_ex, rf)
    ks = sorted(set(s) & set(b))
    if start:
        ks = [k for k in ks if k >= start]
    if not ks:
        return None
    s = {k: s[k] for k in ks}; b = {k: b[k] for k in ks}
    e = {
        'full': M.excess_stats(s, b),
        'train': M.excess_stats(s, b, z=M.TRAIN_END),
        'hold': M.excess_stats(s, b, a=M.HOLD_START),
        'recent': M.excess_stats(s, b, a=M.RECENT_START),
        'turnover_hold': round(turn_hold, 3) if turn_hold is not None else None,
    }
    e['cost_hold'] = M.excess_stats(M.apply_cost(s, turn_hold, COST), b, a=M.HOLD_START) if turn_hold is not None else None
    e['cost_full'] = M.excess_stats(M.apply_cost(s, turn_hold, COST), b) if turn_hold is not None else None
    e['roll20'] = M.rolling(s, b, 20)
    e['dca20'] = M.dca(s, b, 20)
    e['maxdd_s'] = round(M.maxdd(s) * 100, 1)
    e['maxdd_b'] = round(M.maxdd(b) * 100, 1)
    return e


def mean_turn(trn, a=M.HOLD_START, z=None):
    v = [t for k, t in trn.items() if k >= a and (z is None or k <= z)]
    return S.mean(v) if v else None


def git_sha(path):
    try:
        return subprocess.check_output(['git', 'log', '-n1', '--format=%H', '--', path], cwd=M.BASE).decode().strip() or None
    except Exception:  # noqa
        return None


# ───────────────────────── 検査だけ ─────────────────────────
def check():
    D = details()
    print('特徴', len(D), '公表年あり', sum(1 for d in D.values() if d['pub']), '公表年なし',
          [a for a, d in D.items() if not d['pub']])
    print('標本期間あり', sum(1 for d in D.values() if d['is_end']))
    print('|t|≥3', sum(1 for d in D.values() if d['t_abs'] is not None and d['t_abs'] >= 3),
          'tあり', sum(1 for d in D.values() if d['t_abs'] is not None))
    print('群', collections.Counter(d['group'] for d in D.values()))
    print('回転率の区分', collections.Counter(d['turn_class'] for d in D.values()))
    for key, *_ in TURN_RULES:
        print(' ', key, [a for a, d in D.items() if d['turn_class'] == key])
    yrs = collections.Counter(d['pub'] for d in D.values() if d['pub'])
    acc = 0
    for y in sorted(yrs):
        acc += yrs[y]
        print(y, yrs[y], '累計', acc, end=' | ')
    print()
    print('OAP 照合', json.dumps(oap_crosscheck(D), ensure_ascii=False)[:1500])


# ───────────────────────── 本体 ─────────────────────────
def main():
    D = details()
    ff = M.ff_factors()
    rf, mktrf = ff['rf'], ff['mktrf']
    P = load_terciles('usa')
    G = good_series(P, D)
    assert len(G) == 153, len(G)
    out = {'angle': 'postpub', 'prereg': PREREG, 'prereg_commit': git_sha(os.path.join('out', PREREG)),
           'benchmark': 'French Mkt（Mkt-RF + RF）。JKP の三分位（超過）に French RF を足して総リターンで比べる',
           'cost_per_100pct_oneway': COST, 'n_min_stocks': NMIN, 'data_end': DATA_END}

    # ── 健全性の検査 ──
    san = {}
    san['french_mkt_cagr_full'] = round(M.cagr(ff['mkt']) * 100, 2)
    san['french_mkt_cagr_2007'] = round(M.cagr(M.window(ff['mkt'], M.HOLD_START)) * 100, 2)
    jm = M.jkp_mkt('usa', 'vw')
    ks = sorted(set(jm) & set(mktrf))
    san['jkp_usa_vw_mkt_minus_french_mktrf_ann'] = round(S.mean([jm[k] - mktrf[k] for k in ks]) * 1200, 2)
    san['jkp_usa_vw_mkt_minus_french_mktrf_ann_2007'] = round(S.mean([jm[k] - mktrf[k] for k in ks if k >= M.HOLD_START]) * 1200, 2)
    # 三分位の番号: 符号つき因子 = 向き ×（第3 − 第1）の相関
    F = collections.defaultdict(dict)
    for r in M.jkp_rows('usa', 'all_factors', 'factor', 'vw'):
        if r['ret'] not in ('', 'NA'):
            F[r['name']][M._ym(r['date'])] = float(r['ret'])
    cs = []
    for a in D:
        p1, p3 = P[a].get('1.0', {}), P[a].get('3.0', {})
        kk = sorted(set(p1) & set(p3) & set(F[a]))
        cs.append(M.corr([D[a]['direction'] * (p3[k] - p1[k]) for k in kk], [F[a][k] for k in kk]))
    san['tercile_numbering_corr_min'] = round(min(cs), 4)
    san['tercile_numbering_note'] = '符号つき因子と 向き×(第3−第1) の相関の最小値。1.0 なら『第3＝特徴が最も大きい』・良い側＝向きで確定'
    # 地域の developed が米国を含まないこと
    dv, wx = M.jkp_mkt('developed', 'vw'), M.jkp_mkt('world_ex_us', 'vw')
    kk = sorted(set(dv) & set(jm) & set(wx))
    san['developed_corr_usa'] = round(M.corr([dv[k] for k in kk], [jm[k] for k in kk]), 3)
    san['developed_corr_world_ex_us'] = round(M.corr([dv[k] for k in kk], [wx[k] for k in kk]), 3)
    san['oap_year_crosscheck'] = oap_crosscheck(D)
    out['sanity'] = san
    out['deviations'] = ['mw_common.excess_stats の β の式が S.mean を要素ごとに呼び直す O(n²)・標準 statistics の分数計算で1回数秒かかるため、mw_common が参照する統計関数（mean/pvariance/stdev）だけを math.fsum の同じ式へ差し替えて実行（mw_common は書き換えていない・合成データで全項目一致を確認）']

    # ── 地域のデータ ──
    RG, RM, RP = {}, {}, {}
    for reg in REGIONS:
        RP[reg] = load_terciles(reg)
        RG[reg] = good_series(RP[reg], D)
        RM[reg] = M.jkp_mkt(reg, 'vw')

    tested = []

    # ── 主の族: 実時間の採用者 ──
    known = [a for a, d in D.items() if d['pub']]
    ad0, ad3 = adopt_dates(D, 0), adopt_dates(D, 3)
    t3 = [a for a in known if D[a]['t_abs'] is not None and D[a]['t_abs'] >= 3]
    specs = [
        ('P1_RT_all', '公表年の翌年1月から、公表年の分かる全特徴（142）の良い側の三分位を等分で持つ', known, ad0, False),
        ('P2_RT_t3', '同じ。ただし論文の標本内 |t|≥3 と書かれた特徴だけ（公表時に分かる情報）', t3, ad0, False),
        ('P3_RT_lag3', '同じ全特徴。ただし公表の3年後（公表年+4年の1月）から持つ（裁定で薄まる期間を避ける）', known, ad3, False),
        ('P4_RT_balanced', '全特徴。群（7つ）ごとに等分→群の中で等分（数の多い群に偏らない）', known, ad0, True),
    ]
    for g in THEMES:
        specs.append((f'T_{g.replace(" ", "_")}', f'群「{g}」の特徴だけの実時間の採用者', [a for a in known if D[a]['group'] == g], ad0, False))
    prim = {}
    for name, desc, chars, adopt, bal in specs:
        r, cnt, trn = adopter(G, D, chars, adopt, bal)
        th = mean_turn(trn)
        e = evaluate(r, mktrf, rf, th)
        # 地域での再現（同じ公表日・地域の vw 市場）
        rep = {}
        for reg in REGIONS:
            rr, rc, rt = adopter(RG[reg], D, chars, adopt, bal, start_min=REG_START)
            if not rr:
                rep[reg] = None
                continue
            ee = {'full': M.excess_stats(to_total(rr, rf), to_total(RM[reg], rf), a=REG_START),
                  'hold': M.excess_stats(to_total(rr, rf), to_total(RM[reg], rf), a=M.HOLD_START),
                  'n_chars_avg': round(S.mean(rc.values()), 1)}
            rep[reg] = ee
        pos = sum(1 for v in rep.values() if v and v['full'] and v['full']['ex_ann'] > 0)
        nreg = sum(1 for v in rep.values() if v and v['full'])
        ks = sorted(r)
        prim[name] = {'name': name, 'family': 'primary', 'primary': True, 'description': desc, 'n_chars': len(chars),
                      'start': ks[0] if ks else None, 'n_adopted_first': cnt[ks[0]] if ks else None,
                      'n_adopted_2006': cnt.get(200612), 'n_adopted_2025': cnt.get(202512),
                      'eval': e, 'repl': {'regions': nreg, 'positive': pos, 'detail': rep},
                      'annual': annual_table(r, mktrf)}
    hp = M.holm({k: (v['eval']['hold'] or {}).get('p') for k, v in prim.items()})
    for k, v in prim.items():
        v['holm_p_hold'] = hp.get(k)
        finalize(v)
        tested.append(v)

    # ── 探索の族: 特徴ごとの良い側（153・Holm は153で） ──
    cen = {}
    for a, d in D.items():
        g = G[a]
        e = evaluate(g, mktrf, rf, d['turn'])
        rep = {}
        for reg in REGIONS:
            rg = RG[reg].get(a)
            if not rg:
                rep[reg] = None
                continue
            f = M.excess_stats(to_total(rg, rf), to_total(RM[reg], rf), a=REG_START)
            rep[reg] = {'full_ex': f['ex_ann'] if f else None, 't': f['t'] if f else None}
        pos = sum(1 for v in rep.values() if v and v['full_ex'] is not None and v['full_ex'] > 0)
        nreg = sum(1 for v in rep.values() if v and v['full_ex'] is not None)
        post = None
        if d['pub']:
            s_tot, b_tot = to_total(g, rf), to_total(mktrf, rf)
            post = M.excess_stats(s_tot, b_tot, a=(d['pub'] + 1) * 100 + 1)
        cen[a] = {'name': f'C_{a}', 'family': 'census', 'primary': False,
                  'description': f'{d["name"]}（{d["cite"]}・向き{d["direction"]:+d}・群 {d["group"]}）の良い側の三分位',
                  'pub': d['pub'], 'clean_holdout': bool(d['pub'] and d['pub'] <= 2006),
                  'turnover': d['turn'], 'eval': e, 'post_pub': post, 'repl': {'regions': nreg, 'positive': pos, 'detail': rep}}
    hp = M.holm({k: (v['eval']['hold'] or {}).get('p') for k, v in cen.items()})
    for k, v in cen.items():
        v['holm_p_hold'] = hp.get(k)
        finalize(v)
        v['win_eligible'] = v['clean_holdout'] and v['grade'] in ('S', 'A')
        tested.append(v)

    # ── 報告のみ: McLean-Pontiff 型の減衰 ──
    out['decay'] = decay_report(G, D, mktrf)

    # ── 探索2（事前登録2）: 実時間で学ぶ採用者 ──
    if os.path.exists(os.path.join(M.BASE, 'out', PREREG2)):
        out['prereg2'] = PREREG2
        out['prereg2_commit'] = git_sha(os.path.join('out', PREREG2))
        t2, rep2 = part2(D, P, G, mktrf, rf, RP, RG, RM)
        tested += t2
        out['post_hoc_regional_adopter'] = rep2
    # ── 事後の診断（結果1・2を見た後に計算・判定に使わない） ──
    out['post_hoc_diagnostics'] = diagnostics(D, P, G, mktrf, rf, RP, RM, tested)
    # ── 探索3（事前登録3）: 米国外での確かめ・標本後の確かめ ──
    if os.path.exists(os.path.join(M.BASE, 'out', PREREG3)):
        out['prereg3'] = PREREG3
        out['prereg3_commit'] = git_sha(os.path.join('out', PREREG3))
        tested += part3(D, P, G, mktrf, rf, RP, RG, RM)
    # ── 探索4（事前登録4）: 国ごとの実時間の採用者（まだ見ていない国のデータ） ──
    if os.path.exists(os.path.join(M.BASE, 'out', PREREG4)):
        out['prereg4'] = PREREG4
        out['prereg4_commit'] = git_sha(os.path.join('out', PREREG4))
        t4, rep4 = part4(D, P, G, mktrf, rf)
        tested += t4
        out['countries'] = rep4

    out['tested'] = tested
    out['n_tested'] = len(tested)
    out['summary'] = summarize(tested)
    M.save(OUT, out)
    print(json.dumps(out['summary'], ensure_ascii=False, indent=1)[:6000])


# ───────────────────────── 探索2: 実時間で学ぶ採用者（out/mw_postpub_prereg2.json）─────────────────────────
PREREG2 = 'mw_postpub_prereg2.json'
P2_START_US = 198001


def ym_add(t, n):
    y, m = divmod(t // 100 * 12 + (t % 100 - 1) + n, 12)
    return y * 100 + m + 1


def prev_months(t, L):
    return [ym_add(t, -i) for i in range(L, 0, -1)]


class Hist:
    """特徴ごとの（良い側−市場）の履歴。t より前の月だけを返す（後知恵なし）"""
    def __init__(self, G, mkt):
        import bisect
        self.b = bisect
        self.ks, self.cs, self.cq = {}, {}, {}
        for a, g in G.items():
            ks = sorted(k for k in g if k in mkt)
            xs = [g[k] - mkt[k] for k in ks]
            cs, cq, s1, s2 = [0.0], [0.0], 0.0, 0.0
            for x in xs:
                s1 += x; s2 += x * x
                cs.append(s1); cq.append(s2)
            self.ks[a], self.cs[a], self.cq[a] = ks, cs, cq

    def before(self, a, t, since=None):
        """(n, 和, 二乗和) for months since <= m < t"""
        ks = self.ks.get(a)
        if not ks:
            return 0, 0.0, 0.0
        j = self.b.bisect_left(ks, t)
        i = self.b.bisect_left(ks, since) if since else 0
        if j <= i:
            return 0, 0.0, 0.0
        return j - i, self.cs[a][j] - self.cs[a][i], self.cq[a][j] - self.cq[a][i]


def run_rule(rule, D, P, G, mkt, start, adopt, wait_min=0):
    """rule(t) → {スロット: 重み}（スロット＝(特徴, 三分位) か 'MKT'）。当月のリターンと回転率（選び直し＋構成）。
    wait_min>0 なら、市場以外のスロットが wait_min 以上になった最初の月から始める（探索3）"""
    months = sorted(k for k in mkt if k >= start and k <= DATA_END)
    ret, trn, sel_m, nh = {}, {}, {}, {}
    prev = None
    started = wait_min == 0
    for t in months:
        w = rule(t)
        if not started:
            if not w or sum(1 for k in w if k != 'MKT') < wait_min:
                continue
            started = True
        if not w:
            w = {'MKT': 1.0}
        r = 0.0
        comp = 0.0
        for s_, x in w.items():
            if s_ == 'MKT':
                r += x * mkt[t]
            else:
                a, pf = s_
                r += x * P[a][pf][t]
                comp += x * D[a]['turn'] * (2.0 if pf == '2.0' else 1.0)
        sel = 0.5 * math.fsum(abs(w.get(k, 0.0) - prev.get(k, 0.0)) for k in set(w) | set(prev)) if prev is not None else 0.0
        ret[t] = r
        trn[t] = comp + 12 * sel
        sel_m[t] = sel
        nh[t] = sum(1 for k in w if k != 'MKT')
        prev = w
    return ret, trn, nh


def eq(slots):
    slots = list(slots)
    return {s_: 1 / len(slots) for s_ in slots} if slots else None


def make_rules(D, P, G, mkt, adopt):
    H = Hist(G, mkt)
    gp = {a: D[a]['good_pf'] for a in G}
    adopted = lambda t: [a for a in G if adopt.get(a) is not None and adopt[a] <= t and t in G[a]]
    # 符号つきロング・ショート（向き×(第3−第1)）
    LS = {}
    for a in P:
        p1, p3 = P[a].get('1.0', {}), P[a].get('3.0', {})
        LS[a] = {k: D[a]['direction'] * (p3[k] - p1[k]) for k in p1 if k in p3}

    def fm(L, q):
        def rule(t):
            pm = prev_months(t, L)
            cand = []
            for a in adopted(t):
                if all(m in G[a] and m in mkt for m in pm):
                    cand.append((-math.fsum(G[a][m] - mkt[m] for m in pm), a))
            if len(cand) < 3:
                return None
            k = max(3, math.ceil(q * len(cand)))
            return eq((a, gp[a]) for _, a in sorted(cand)[:k])
        return rule

    def tsfm(L):
        def rule(t):
            pm = prev_months(t, L)
            slots = []
            for a in adopted(t):
                if all(m in LS[a] for m in pm):
                    on = math.fsum(LS[a][m] for m in pm) > 0
                else:
                    on = True
                slots.append((a, gp[a]) if on else 'MKT')
            if not slots:
                return None
            w = collections.Counter()
            for s_ in slots:
                w[s_] += 1 / len(slots)
            return dict(w)
        return rule

    def surv(minm):
        def rule(t):
            keep = []
            for a in adopted(t):
                n, s1, _ = H.before(a, t, since=adopt[a])
                if n < minm or s1 > 0:
                    keep.append((a, gp[a]))
            return eq(keep)
        return rule

    def rtt(thr, minm=60):
        def rule(t):
            keep = []
            for a in adopted(t):
                n, s1, s2 = H.before(a, t)
                if n < minm:
                    continue
                m = s1 / n
                var = (s2 - n * m * m) / (n - 1)
                if var > 0 and m / math.sqrt(var / n) >= thr:
                    keep.append((a, gp[a]))
            return eq(keep)
        return rule

    def age(fresh, yrs=10):
        def rule(t):
            keep = []
            for a in adopted(t):
                young = t < ym_add(adopt[a], 12 * yrs)
                if young == fresh:
                    keep.append((a, gp[a]))
            return eq(keep)
        return rule

    def both(L, q):
        def rule(t):
            pm = prev_months(t, L)
            cand = []
            for a in P:
                for pf, g in P[a].items():
                    if t in g and all(m in g and m in mkt for m in pm):
                        cand.append((-math.fsum(g[m] - mkt[m] for m in pm), a, pf))
            if len(cand) < 3:
                return None
            k = max(3, math.ceil(q * len(cand)))
            return eq((a, pf) for _, a, pf in sorted(cand)[:k])
        return rule

    return [
        ('X1_FM12_top20', '実時間の採用者のうち、直前12か月の（良い側−市場）の和が上位20%の特徴だけ等分（因子の勢い・Gupta-Kelly 2019／Arnott ほか 2023）', fm(12, 0.2)),
        ('X2_FM1_top20', '同じ・直前1か月で上位20%（1か月の因子の勢い・Arnott ほか）', fm(1, 0.2)),
        ('X3_TSFM12', '採用済みの各特徴について、直前12か月の符号つきロング・ショートの和が正なら良い側、負なら市場を持つ（時系列の因子の勢い・Ehsani-Linnainmaa 2022）', tsfm(12)),
        ('X4_SURV36', '公表後36か月以上たった特徴は、公表後の（良い側−市場）の平均が正のときだけ持つ（公表を生き残った特徴）', surv(36)),
        ('X5_RTT2', 'データの始まりから前月までの（良い側−市場）の t 値（単純）が2以上の採用済み特徴だけ（実時間の再現の確かめ・60か月以上）', rtt(2.0)),
        ('X6_RTT3', '同じ・t≥3（Harvey-Liu-Zhu の線）', rtt(3.0)),
        ('X7_FRESH10', '採用から10年以内の特徴だけ（裁定が進む前）', age(True)),
        ('X8_SEASONED10', '採用から10年以上たった特徴だけ（公表の山が過ぎた後）', age(False)),
        ('X9_FM12_both5', '公表と向きを使わず、153特徴×3つの三分位（459）を直前12か月の（三分位−市場）の和で並べ上位5%を等分（ポートフォリオの勢い）', both(12, 0.05)),
    ]


def part2(D, P, G, mktrf, rf, RP, RG, RM):
    ad0 = adopt_dates(D, 0)
    rules = make_rules(D, P, G, mktrf, ad0)
    reg_rules = {reg: dict((n, f) for n, _, f in make_rules(D, RP[reg], RG[reg], RM[reg], ad0)) for reg in REGIONS}
    res = {}
    for name, desc, rule in rules:
        r, trn, nh = run_rule(rule, D, P, G, mktrf, P2_START_US, ad0)
        th = mean_turn(trn)
        e = evaluate(r, mktrf, rf, th)
        rep = {}
        for reg in REGIONS:
            rr, rt, rn = run_rule(reg_rules[reg][name], D, RP[reg], RG[reg], RM[reg], REG_START, ad0)
            rep[reg] = {'full': M.excess_stats(to_total(rr, rf), to_total(RM[reg], rf), a=REG_START),
                        'hold': M.excess_stats(to_total(rr, rf), to_total(RM[reg], rf), a=M.HOLD_START),
                        'mkt_months': sum(1 for k in rn if rn[k] == 0), 'turnover_hold': round(mean_turn(rt), 2)}
        pos = sum(1 for v in rep.values() if v['full'] and v['full']['ex_ann'] > 0)
        nreg = sum(1 for v in rep.values() if v['full'])
        res[name] = {'name': name, 'family': 'explore2', 'primary': False, 'description': desc, 'start': P2_START_US,
                     'months_all_market': sum(1 for k in nh if nh[k] == 0), 'held_avg': round(S.mean(nh.values()), 1),
                     'held_2006': nh.get(200612), 'held_2025': nh.get(202512),
                     'eval': e, 'repl': {'regions': nreg, 'positive': pos, 'detail': rep}, 'annual': annual_table(r, mktrf)}
    hp = M.holm({k: (v['eval']['hold'] or {}).get('p') for k, v in res.items()})
    for k, v in res.items():
        v['holm_p_hold'] = hp.get(k)
        finalize(v)
    # 事後（判定に使わない）: 主の族の採用者を米国外の地域で単独の戦略として見る
    rep2 = {'label': '事後（結果1で地域の数字を見た後に、同じ規則を地域の投資家の戦略として並べ直しただけ・判定に使わない）', 'rows': {}}
    known = [a for a, d in D.items() if d['pub']]
    for reg in REGIONS:
        for nm, bal in (('P1_RT_all', False), ('P4_RT_balanced', True)):
            rr, rc, rt = adopter(RG[reg], D, known, ad0, bal, start_min=REG_START)
            s_, b_ = to_total(rr, rf), to_total(RM[reg], rf)
            ks = sorted(set(s_) & set(b_))
            s_ = {k: s_[k] for k in ks}; b_ = {k: b_[k] for k in ks}
            rep2['rows'][f'{reg}:{nm}'] = {'full': M.excess_stats(s_, b_), 'train': M.excess_stats(s_, b_, z=M.TRAIN_END),
                                          'hold': M.excess_stats(s_, b_, a=M.HOLD_START),
                                          'cost_hold': M.excess_stats(M.apply_cost(s_, mean_turn(rt), COST), b_, a=M.HOLD_START),
                                          'roll20': M.rolling(s_, b_, 20), 'dca20': M.dca(s_, b_, 20)}
    return list(res.values()), rep2


# ───────────────────────── 事後の診断 ─────────────────────────
def tilt_series(P, D):
    """特徴の傾き＝良い側 − 3つの三分位の等分平均（3つとも値がある月だけ）。
    地域の三分位の等分平均は地域の vw 市場より構造的に高い（小型寄り）ので、市場ではなくこれを中立の基準にする"""
    T = {}
    for a in D:
        if a not in P or not all(pf in P[a] for pf in ('1.0', '2.0', '3.0')):
            continue
        g = P[a][D[a]['good_pf']]
        ks = set(P[a]['1.0']) & set(P[a]['2.0']) & set(P[a]['3.0'])
        T[a] = {k: g[k] - (P[a]['1.0'][k] + P[a]['2.0'][k] + P[a]['3.0'][k]) / 3 for k in ks}
    return T


def diagnostics(D, P, G, mktrf, rf, RP, RM, tested):
    out = {'label': '事後（結果1・2を見た後に計算した診断・判定には使わない）'}
    known = [a for a, d in D.items() if d['pub']]
    ad0 = adopt_dates(D, 0)
    # (1) 三分位の等分平均 vs 市場（構造の偏り）: 良い側・悪い側・真ん中の採用者
    rows = {}
    for reg, PP_, mk in [('usa', P, mktrf)] + [(r, RP[r], RM[r]) for r in REGIONS]:
        rr = {}
        for lab in ('good', 'bad', 'mid'):
            sel = (lambda a: D[a]['good_pf']) if lab == 'good' else (lambda a: '1.0' if D[a]['good_pf'] == '3.0' else '3.0') if lab == 'bad' else (lambda a: '2.0')
            Gx = {a: PP_[a][sel(a)] for a in known if a in PP_ and sel(a) in PP_[a]}
            r, c, t = adopter(Gx, D, known, ad0, False, start_min=REG_START)
            f = M.excess_stats(to_total(r, rf), to_total(mk, rf), a=REG_START)
            h = M.excess_stats(to_total(r, rf), to_total(mk, rf), a=M.HOLD_START)
            rr[lab] = {'full_ex': f['ex_ann'], 'full_t': f['t'], 'hold_ex': h['ex_ann'], 'hold_t': h['t']}
        rows[reg] = rr
    out['tercile_side_adopters_1990on'] = {'note': '同じ採用の規則で、良い側・悪い側・真ん中の三分位を持った場合の対 地域vw市場（1990-01〜）。地域では真ん中・3つの平均も市場に勝つ＝三分位を等分に持つこと自体が小型寄りの傾きを生む（米国外は小型が大型に勝った）。地域の C5 の超過はこの分だけ甘い', 'rows': rows}
    # (2) census: 公表2006以前（83本）の保有期間の分布と、訓練期間の t が保有期間を当てるか
    cen = [v for v in tested if v['family'] == 'census' and v['clean_holdout'] and v['eval']['hold']]
    h = [v['eval']['hold']['ex_ann'] for v in cen]
    tr = [v['eval']['train']['t'] for v in cen]
    out['census_clean'] = {'n': len(cen), 'hold_mean': round(S.mean(h), 2), 'hold_median': round(S.median(h), 2),
                           'hold_positive': sum(1 for x in h if x > 0), 'hold_t_ge_1_65': sum(1 for v in cen if (v['eval']['hold']['t'] or 0) >= 1.65),
                           'expected_t_ge_1_65_if_null': round(0.05 * len(cen), 1),
                           'corr_train_t_vs_hold_ex': round(M.corr(tr, h), 3),
                           'hold_mean_train_t_ge3': round(S.mean([v['eval']['hold']['ex_ann'] for v in cen if v['eval']['train']['t'] >= 3]), 2),
                           'n_train_t_ge3': sum(1 for v in cen if v['eval']['train']['t'] >= 3)}
    # (3) census の S/A を、地域の傾き（良い側−3つの平均）で数え直した C5
    RT = {reg: tilt_series(RP[reg], D) for reg in REGIONS}
    c5 = {}
    for v in tested:
        if v['family'] != 'census' or v['grade'] not in ('S', 'A'):
            continue
        a = v['name'][2:]
        row = {}
        for reg in REGIONS:
            x = [RT[reg][a][k] for k in sorted(RT[reg].get(a, {})) if k >= REG_START]
            row[reg] = [round(S.mean(x) * 1200, 2), round(M.nw_t(x), 2)] if len(x) >= 24 else None
        c5[a] = {'grade': v['grade'], 'clean': v['clean_holdout'], 'tilt_vs_avg3': row,
                 'positive': sum(1 for r in row.values() if r and r[0] > 0)}
    out['census_SA_C5_tilt_check'] = c5
    return out


# ───────────────────────── 探索3: 米国外での確かめ・標本後の確かめ（out/mw_postpub_prereg3.json）─────────────────────────
PREREG3 = 'mw_postpub_prereg3.json'


class HistX:
    def __init__(self, X):
        # Hist は g−mkt を取るので、全月が 0 の辞書を渡して X そのものの履歴にする
        z = {}
        for a, x in X.items():
            for k in x:
                z[k] = 0.0
        self.h = Hist(X, z)

    def t_before(self, a, t, minm=60):
        n, s1, s2 = self.h.before(a, t)
        if n < minm:
            return None
        m = s1 / n
        var = (s2 - n * m * m) / (n - 1)
        return m / math.sqrt(var / n) if var > 0 else None


def make_rules3(D, G, mkt, adopt, T_home, T_other, US_G, US_mkt):
    """T_home: その地域の傾き系列・T_other: 確かめに使う別の地域の傾き系列（米国なら world_ex_us、地域なら米国）"""
    gp = {a: D[a]['good_pf'] for a in G}
    adopted = lambda t: [a for a in G if adopt.get(a) is not None and adopt[a] <= t and t in G[a]]
    Ho, Hh = HistX(T_other), HistX(T_home)

    def intl(thr):
        def rule(t):
            keep = []
            for a in adopted(t):
                x = Ho.t_before(a, t)
                if x is not None and x >= thr:
                    keep.append((a, gp[a]))
            return eq(keep)
        return rule

    # 標本後〜公表の窓（米国の論文の標本の後・公表の前＝採用の時点で閉じている窓）の米国の（良い側−市場）
    ps_ok = {}
    for a, d in D.items():
        if not (d['pub'] and d['is_end']) or a not in US_G:
            continue
        xs = [US_G[a][k] - US_mkt[k] for k in US_G[a] if k in US_mkt and d['is_end'] < k // 100 <= d['pub']]
        ps_ok[a] = True if len(xs) < 12 else (math.fsum(xs) > 0)

    def postsample():
        def rule(t):
            return eq((a, gp[a]) for a in adopted(t) if ps_ok.get(a, True))
        return rule

    def double(thr):
        def rule(t):
            keep = []
            for a in adopted(t):
                x, y = Ho.t_before(a, t), Hh.t_before(a, t)
                if x is not None and y is not None and x >= thr and y >= thr:
                    keep.append((a, gp[a]))
            return eq(keep)
        return rule

    return [
        ('Y1_INTL_RT2', '採用済みの特徴のうち、別の地域（米国なら world_ex_us）での傾き（良い側−3つの三分位の平均）の t（前月まで・60か月以上）が2以上のものだけ', intl(2.0)),
        ('Y3_POSTSAMPLE', '公表年の翌年に採用するとき、論文の標本の後〜公表までの米国の（良い側−市場）の和が負なら採用しない（窓が12か月未満なら採用）', postsample()),
        ('Y4_DOUBLE2', '自分の地域の傾きの t≥2 と別の地域の傾きの t≥2 の両方（前月まで・60か月以上）', double(2.0)),
    ]


def part3(D, P, G, mktrf, rf, RP, RG, RM):
    ad0 = adopt_dates(D, 0)
    TU = tilt_series(P, D)
    RT = {reg: tilt_series(RP[reg], D) for reg in REGIONS}
    rules = make_rules3(D, G, mktrf, ad0, TU, RT['world_ex_us'], G, mktrf)
    reg_rules = {reg: dict((n, f) for n, _, f in make_rules3(D, RG[reg], RM[reg], ad0, RT[reg], TU, G, mktrf)) for reg in REGIONS}
    res = {}
    for name, desc, rule in rules:
        r, trn, nh = run_rule(rule, D, P, G, mktrf, P2_START_US, ad0, wait_min=MIN_ADOPTED)
        e = evaluate(r, mktrf, rf, mean_turn(trn))
        rep = {}
        for reg in REGIONS:
            rr, rt, rn = run_rule(reg_rules[reg][name], D, RP[reg], RG[reg], RM[reg], REG_START, ad0, wait_min=MIN_ADOPTED)
            if not rr:
                rep[reg] = {'full': None, 'hold': None}
                continue
            b = to_total(RM[reg], rf)
            # 基準は地域の vw 市場（事前登録どおり）。三分位の等分の偏りを除いた参考として『真ん中の三分位の採用者』との差も
            rep[reg] = {'full': M.excess_stats(to_total(rr, rf), b), 'hold': M.excess_stats(to_total(rr, rf), b, a=M.HOLD_START),
                        'start': min(rr), 'mkt_months': sum(1 for k in rn if rn[k] == 0)}
        pos = sum(1 for v in rep.values() if v['full'] and v['full']['ex_ann'] > 0)
        nreg = sum(1 for v in rep.values() if v['full'])
        res[name] = {'name': name, 'family': 'explore3', 'primary': False, 'description': desc, 'start': min(r) if r else None,
                     'months_all_market': sum(1 for k in nh if nh[k] == 0), 'held_avg': round(S.mean(nh.values()), 1) if nh else None,
                     'held_2006': nh.get(200612), 'held_2025': nh.get(202512),
                     'eval': e, 'repl': {'regions': nreg, 'positive': pos, 'detail': rep}, 'annual': annual_table(r, mktrf)}
    hp = M.holm({k: (v['eval']['hold'] or {}).get('p') for k, v in res.items()})
    for k, v in res.items():
        v['holm_p_hold'] = hp.get(k)
        finalize(v)
    return list(res.values())


# ───────────────────────── 探索4: 国ごとの実時間の採用者（out/mw_postpub_prereg4.json）─────────────────────────
PREREG4 = 'mw_postpub_prereg4.json'
COUNTRIES = ['gbr', 'deu', 'fra', 'can', 'aus', 'che', 'ita', 'esp', 'nld', 'swe', 'hkg', 'sgp', 'kor', 'twn', 'ind', 'chn',
             'bel', 'dnk', 'nor', 'fin', 'aut', 'nzl', 'zaf', 'mex', 'mys', 'tha', 'idn', 'phl', 'tur', 'pol', 'chl', 'grc']
MATURE_CHARS = 50


def tilt_market(mkt, T, D, chars, adopt, start):
    """市場 + 採用済み特徴の傾き（良い側−3つの平均）の等分平均。傾きが3つ以上ある月から"""
    out, cnt = {}, {}
    started = False
    for m in sorted(k for k in mkt if k >= start and k <= DATA_END):
        act = [a for a in chars if a in T and adopt.get(a) is not None and adopt[a] <= m and m in T[a]]
        if not started:
            if len(act) < MIN_ADOPTED:
                continue
            started = True
        out[m] = mkt[m] + (math.fsum(T[a][m] for a in act) / len(act) if act else 0.0)
        cnt[m] = len(act)
    return out, cnt


def part4(D, P, G, mktrf, rf):
    known = [a for a, d in D.items() if d['pub']]
    ad0 = adopt_dates(D, 0)
    fam = {'Z': {}, 'ZT': {}}
    info = {}
    for c in COUNTRIES:
        Pc = load_terciles(c)
        Gc = good_series(Pc, D)
        mk = M.jkp_mkt(c, 'vw')
        cnt = collections.Counter(k for a in Pc for k in Pc[a].get('3.0', {}))  # 第3三分位に値のある特徴の数（銘柄数20以上）
        mature = min([k for k, v in cnt.items() if v >= MATURE_CHARS], default=None)
        if mature is None or mature > 199912:
            info[c] = {'excluded': f'成熟（{MATURE_CHARS}特徴）が2000年以降: {mature}'}
            continue
        start = max(REG_START, mature)
        r, rc, rt = adopter(Gc, D, known, ad0, False, start_min=start)
        th = mean_turn(rt)
        # 構造の偏りの目安: 真ん中の三分位の採用者
        Gm = {a: Pc[a]['2.0'] for a in known if a in Pc and '2.0' in Pc[a]}
        rm, _, _ = adopter(Gm, D, known, ad0, False, start_min=start)
        Tc = tilt_series(Pc, D)
        zt, ztc = tilt_market(mk, Tc, D, known, ad0, start)
        for fk, series, desc in (('Z', r, f'{c}: 実時間の採用者（米国の公表日・良い側の三分位を等分）対 {c} の vw 市場'),
                                 ('ZT', zt, f'{c}: 市場＋採用済み特徴の傾き（良い側−3つの三分位の平均）の等分平均（三分位の等分の小型寄りを除いた版・ほぼ買いだけ）')):
            e = evaluate(series, mk, rf, th)
            fam[fk][c] = {'name': f'{fk}_{c}', 'family': 'explore4_' + fk, 'primary': False, 'description': desc, 'country': c,
                          'start': min(series) if series else None, 'eval': e, 'annual': annual_table(series, mk)}
        fm = M.excess_stats(to_total(rm, rf), to_total(mk, rf))
        hm = M.excess_stats(to_total(rm, rf), to_total(mk, rf), a=M.HOLD_START)
        info[c] = {'start': start, 'mature': mature, 'n_adopted_2006': rc.get(200612), 'n_adopted_2025': rc.get(202512),
                   'mid_adopter_vs_mkt': {'full_ex': fm['ex_ann'] if fm else None, 'hold_ex': hm['ex_ann'] if hm else None}}
    tested = []
    for fk, rows in fam.items():
        # C5 = 同じ族の他の国のうち、全期間の算術平均の超過が正の国の割合
        full_pos = {c: bool(v['eval']['full'] and v['eval']['full']['ex_ann'] > 0) for c, v in rows.items()}
        hp = M.holm({c: (v['eval']['hold'] or {}).get('p') for c, v in rows.items()})
        for c, v in rows.items():
            others = [full_pos[o] for o in rows if o != c]
            v['repl'] = {'regions': len(others), 'positive': sum(others), 'detail': '同じ族の他の国（全期間の超過が正か）'}
            v['holm_p_hold'] = hp.get(c)
            finalize(v)
            tested.append(v)
    # 要約
    for fk, rows in fam.items():
        hs = [v['eval']['hold'] for v in rows.values() if v['eval']['hold']]
        fs = [v['eval']['full'] for v in rows.values() if v['eval']['full']]
        info[f'summary_{fk}'] = {'countries': len(rows), 'full_positive': sum(1 for f in fs if f['ex_ann'] > 0),
                                 'hold_positive': sum(1 for h in hs if h['ex_ann'] > 0),
                                 'hold_t_ge_1_65': sum(1 for h in hs if (h['t'] or 0) >= 1.65),
                                 'hold_mean_ex': round(S.mean(h['ex_ann'] for h in hs), 2) if hs else None,
                                 'hold_median_ex': round(S.median(h['ex_ann'] for h in hs), 2) if hs else None,
                                 'grades': dict(collections.Counter(v['grade'] for v in rows.values()))}
    return tested, info


def annual_table(r, mktrf):
    """暦年ごとの超過（算術の和の近似ではなく複利: (1+s)/(1+b)−1 ではなく 年の複利の差）"""
    ys = collections.defaultdict(list)
    for k in sorted(r):
        if k in mktrf:
            ys[k // 100].append((r[k], mktrf[k]))
    out = {}
    for y, v in ys.items():
        if len(v) == 12:
            gs = math.prod(1 + a for a, _ in v) - 1
            gb = math.prod(1 + b for _, b in v) - 1
            out[y] = round((gs - gb) * 100, 1)
    return out


def finalize(v):
    e = v['eval']
    g, c = M.grade(e['full'], e['train'], e['hold'], e['roll20'], cost_hold=e['cost_hold'],
                   repl={'regions': v['repl']['regions'], 'positive': v['repl']['positive']} if v['repl']['regions'] else None,
                   family_holm_p=v.get('holm_p_hold'))
    v['grade'], v['criteria'] = g, c


def decay_report(G, D, mktrf):
    """特徴ごと: 標本内・標本後〜公表・公表後 の良い側の超過。束ね方は (a) 月ごとの等分の束（NW t）(b) 特徴の平均の横断 t"""
    per = {}
    states = ('pre_sample', 'in_sample', 'post_sample', 'post_pub')
    pooled = {s: collections.defaultdict(list) for s in states}
    for a, d in D.items():
        if not (d['pub'] and d['is_start'] and d['is_end']):
            continue
        ex = {k: G[a][k] - mktrf[k] for k in G[a] if k in mktrf}
        st = {}
        for k, x in ex.items():
            y = k // 100
            s = 'pre_sample' if y < d['is_start'] else 'in_sample' if y <= d['is_end'] else 'post_sample' if y <= d['pub'] else 'post_pub'
            st.setdefault(s, []).append(x)
            pooled[s][k].append(x)
        per[a] = {s: {'months': len(v), 'ex_ann': round(S.mean(v) * 1200, 2)} for s, v in st.items() if len(v) >= 12}
    res = {'n_chars': len(per)}
    for s in states:
        ser = {k: S.mean(v) for k, v in pooled[s].items()}
        ks = sorted(ser)
        xs = [ser[k] for k in ks]
        t = M.nw_t(xs) if len(xs) >= 24 else None
        means = [p[s]['ex_ann'] for p in per.values() if s in p]
        res[s] = {'pooled_months': len(xs), 'pooled_ex_ann': round(S.mean(xs) * 1200, 2) if xs else None,
                  'pooled_nw_t': round(t, 2) if t else None,
                  'chars': len(means), 'cross_mean': round(S.mean(means), 2) if means else None,
                  'cross_naive_t': round(S.mean(means) / (S.stdev(means) / math.sqrt(len(means))), 2) if len(means) > 2 and S.stdev(means) else None,
                  'cross_positive': sum(1 for m in means if m > 0)}
    # 公表後を 〜2006 と 2007〜 に分ける（公表後の中で時代が効くか）
    for lab, lo, hi in (('post_pub_to2006', 0, 200612), ('post_pub_2007on', 200701, 999999)):
        ser = {k: S.mean(v) for k, v in pooled['post_pub'].items() if lo <= k <= hi}
        xs = [ser[k] for k in sorted(ser)]
        t = M.nw_t(xs) if len(xs) >= 24 else None
        res[lab] = {'pooled_months': len(xs), 'pooled_ex_ann': round(S.mean(xs) * 1200, 2) if xs else None, 'pooled_nw_t': round(t, 2) if t else None}
    both = [(p['in_sample']['ex_ann'], p['post_pub']['ex_ann']) for p in per.values() if 'in_sample' in p and 'post_pub' in p]
    if both:
        res['decay_ratio_cross'] = round(1 - S.mean(b for _, b in both) / S.mean(a for a, _ in both), 3) if S.mean(a for a, _ in both) else None
        res['decay_n'] = len(both)
    res['per_char'] = per
    return res


def summarize(tested):
    rows = []
    for v in tested:
        e = v['eval']
        f, h = e['full'] or {}, e['hold'] or {}
        rows.append((v['name'], v['family'], v['grade'], f.get('ex_ann'), f.get('t'), h.get('ex_ann'), h.get('t'), h.get('cagr_diff'),
                     (e['cost_hold'] or {}).get('ex_ann'), (e['roll20'] or {}).get('win_rate'), f'{v["repl"]["positive"]}/{v["repl"]["regions"]}'))
    g = collections.Counter((r[1], r[2]) for r in rows)
    prim = [r for r in rows if r[1] == 'primary']
    cen = sorted([r for r in rows if r[1] == 'census'], key=lambda r: -(r[5] if r[5] is not None else -99))
    return {'grades': {f'{a}:{b}': n for (a, b), n in sorted(g.items())},
            'cols': ['name', 'family', 'grade', 'full_ex', 'full_t', 'hold_ex', 'hold_t', 'hold_cagr_diff', 'net_hold_ex', 'roll20_win', 'repl'],
            'primary': prim, 'census_top15_by_hold': cen[:15]}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    check() if a.check else main()
