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

    # ── 地域のデータ ──
    RG, RM = {}, {}
    for reg in REGIONS:
        RG[reg] = good_series(load_terciles(reg), D)
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

    out['tested'] = tested
    out['n_tested'] = len(tested)
    out['summary'] = summarize(tested)
    M.save(OUT, out)
    print(json.dumps(out['summary'], ensure_ascii=False, indent=1)[:6000])


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
