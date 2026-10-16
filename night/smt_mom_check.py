#!/usr/bin/env python3
"""night/smt_mom_check.py — SMT 米国株式モメンタムファンドを今の配分に足すのは？（2026-10-16・ユーザー「SMTモメンタムETFをポートフォリオに
入れようと思うけどモメンタムETFを入れることについてどう評価する？」）

読むだけ。門・採点・配分（portfolio.json）・注文書には触れない。事前登録 out/smt_mom_prereg.json（eb119b72）どおり。
  SMT_MOM の行: night/unx_assets.build の MTUM の行と毎月の値を写し、費用の差 年0.62pt（SMT 0.77 − MTUM 0.15）だけ引く
    （A1・B・C・D。A1_gross と毎月の値はそのまま＝measure の adj が 0.62pt 深くなる）。etf_forward_rank の fee_back と同じ考え。
  確かめ SMT_CONC: 毎月の値を French 25_Portfolios_ME_Prior_12_2 の BIG HiPRIOR（大型の上位20%×勢いの上位20%・時価加重・費用前）に替える
    （French が 2026-08 までなので 2026-09 は MTUM の本物 + 0.15%/12）。fee_back＝−0.77%。B・C・D・K4・外国税は SMT_MOM と同じ。
  形: 今（NASDAQ100 40 / SMH 25 / ITA 5 / SHLD 5 / XLV 7.5 / FBT 7.5）・+SMT_MOM・+SMT_CONC・+MTUM・+GDX（各 NASDAQ100 から5）。
    判定は etf_add・avuv と同じ（etf_ita_xlk.verdict・感度5本・保険の3条件）。
  100年の代用の (3): MTUM・SMT_MOM は French 6_Portfolios_ME_Prior_12_2 の BIG HiPRIOR、SMT_CONC は 25-port の BIG HiPRIOR で写す
    （SMT の2本は毎月 0.62%/12 を引く）。unx_assets.century_parts の部品にこの道具の中だけで足す。
回帰の検査: ① 今・+GDX が out/etf_add_check.json と小数1桁で一致 ② 感度の主が measure と 1e-9 以内（USD・円）
  ③ SMT_MOM の行が MTUM の行と費用の差だけ違う。どれかが外れれば止める。
参考（判定に使わない）: SMT の本物の記録（円・9か月）・長い歴史の手がかり（勢い・長期の反転・短期の反転・勢いの崩れ）・集中と重なり・費用。
使い方: python3 night/smt_mom_check.py → out/smt_mom_check.json
"""
import datetime, json, math, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))

OUT = os.path.join(BASE, 'out', 'smt_mom_check.json')
PREREG = os.path.join(BASE, 'out', 'smt_mom_prereg.json')
SMT_ER, MTUM_ER = 0.0077, 0.0015
FEE_GAP = SMT_ER - MTUM_ER                 # 0.0062
SMT_ISIN, SMT_ASSOC = 'JP90C000SCM7', '6431225C'
FR_LAST = 202608                           # French の最後の月
SLOT = 5
CUR = '今'
K = {'SMT_MOM': '+SMT_MOM（NASDAQ100 から5）', 'SMT_CONC': '+SMT_CONC（確かめ・集中型の代理）',
     'MTUM': '+MTUM（参考・同じ賭けの安い器・楽天で買えない）', 'GDX': '+GDX（参考・etf_add の勧め）'}
ETF_ADD_KEYS = {CUR: '今', K['GDX']: '+GDX'}
FRAMES = ('USD・崩れあり（主）', 'USD・ドットコム級なし', '円・崩れあり')
# 交付目論見書（2026-09-15）の「主要な資産の状況」2026-07-31（ティッカーは名前から当てた）
SMT_TOP10 = [('WDC', 'WESTERN DIGITAL CORP', 5.9, 'テクノロジー・ハードウェアおよび機器'),
             ('TER', 'TERADYNE INC', 5.8, '半導体・半導体製造装置'),
             ('STX', 'SEAGATE TECHNOLOGY HOLDINGS', 5.7, 'テクノロジー・ハードウェアおよび機器'),
             ('DELL', 'DELL TECHNOLOGIES -C', 5.7, 'テクノロジー・ハードウェアおよび機器'),
             ('FIX', 'COMFORT SYSTEMS USA INC', 5.5, '資本財'),
             ('HOOD', 'ROBINHOOD MARKETS INC - A', 5.4, '金融サービス'),
             ('MU', 'MICRON TECHNOLOGY', 5.3, '半導体・半導体製造装置'),
             ('CRDO', 'CREDO TECHNOLOGY GROUP HOLDI', 5.0, '半導体・半導体製造装置'),
             ('CVNA', 'CARVANA CO', 5.0, '一般消費財・サービス流通・小売り'),
             ('LITE', 'LUMENTUM HOLDINGS INC', 4.8, 'テクノロジー・ハードウェアおよび機器')]
FEES = {'SMT 米国株式モメンタムファンド（投信・楽天○）': 0.77, 'MTUM（楽天×）': 0.15, 'SPMO（楽天×）': 0.13,
        'iFreeNEXT NASDAQ100（今の NASDAQ100 の器）': 0.495, 'QQQM': 0.15, 'SMH': 0.35}


def geo(s, ms):
    return math.exp(sum(math.log1p(s[m]) for m in ms) * 12 / len(ms)) - 1


def months(a, b):
    out, y, m = [], a // 100, a % 100
    while y * 100 + m <= b:
        out.append(y * 100 + m)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def p2(x, k=2):
    return None if x is None else round(100 * x, k)


# ───────────────────────── 長い歴史の手がかり（French） ─────────────────────────
def diff_stats(a, b, ms):
    """a と b（月次・小数）の ms での幾何の年率・差・月次の差の t・月数"""
    d = [a[m] - b[m] for m in ms]
    n = len(d)
    mu = sum(d) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in d) / (n - 1))
    return dict(年率=p2(geo(a, ms)), 相手の年率=p2(geo(b, ms)), 差=p2(geo(a, ms) - geo(b, ms)), t=round(mu / (sd / math.sqrt(n)), 2), 月数=n)


def worst_years(a, b, first, last, k=5):
    out = []
    for y in range(first // 100 + (1 if first % 100 != 1 else 0), last // 100 + 1):
        ms = [y * 100 + i for i in range(1, 13)]
        if all(m in a and m in b for m in ms) and ms[-1] <= last:
            ra = math.prod(1 + a[m] for m in ms) - 1
            rb = math.prod(1 + b[m] for m in ms) - 1
            out.append((round(100 * (ra - rb), 1), y, round(100 * ra, 1), round(100 * rb, 1)))
    out.sort()
    return [dict(年=y, 差=d, 本=ra, 相手=rb) for d, y, ra, rb in out[:k]]


def rel_drawdown(a, b, ms):
    lvl, peak, worst, at, pk_at = 1.0, 1.0, 0.0, None, ms[0]
    cur_pk = ms[0]
    for m in ms:
        lvl *= (1 + a[m]) / (1 + b[m])
        if lvl > peak:
            peak, cur_pk = lvl, m
        dd = lvl / peak - 1
        if dd < worst:
            worst, at, pk_at = dd, m, cur_pk
    return dict(最大の相対下落=p2(worst, 1), 山=pk_at, 谷=at)


def french_evidence(M):
    mkt = M.ff_factors()['mkt']
    s6 = M.french_series('6_Portfolios_ME_Prior_12_2', want='Average Value Weighted Returns')
    s25 = M.french_series('25_Portfolios_ME_Prior_12_2', want='Average Value Weighted Returns')
    l6 = M.french_series('6_Portfolios_ME_Prior_60_13', want='Average Value Weighted Returns')
    r6 = M.french_series('6_Portfolios_ME_Prior_1_0', want='Average Value Weighted Returns')
    vs_mkt = {
        '勢い: 大型×直近12か月（直近1か月を飛ばす）の上位30%（6_Portfolios_ME_Prior_12_2 BIG HiPRIOR）': s6['BIG HiPRIOR'],
        '勢い（集中）: 大型の上位20%×勢いの上位20%（25_Portfolios_ME_Prior_12_2 BIG HiPRIOR）': s25['BIG HiPRIOR'],
        '36か月の部品の手がかり: 大型×過去13〜60か月の勝ち（6_Portfolios_ME_Prior_60_13 BIG HiPRIOR）': l6['BIG HiPRIOR'],
        '直近1か月を飛ばさない部品の手がかり: 大型×直近1か月の勝ち（6_Portfolios_ME_Prior_1_0 BIG HiPRIOR）': r6['BIG HiPRIOR'],
    }
    spreads = {
        '勢いの差: 大型の上位30% − 下位30%（12-2）': (s6['BIG HiPRIOR'], s6['BIG LoPRIOR']),
        '長期の反転: 大型の過去13〜60か月の勝ち − 負け（60-13）': (l6['BIG HiPRIOR'], l6['BIG LoPRIOR']),
        '短期の反転: 大型の直近1か月の勝ち − 負け（1-0）': (r6['BIG HiPRIOR'], r6['BIG LoPRIOR']),
    }

    def periods(first):
        return {'全期間': (first, FR_LAST), '〜2006': (first, 200612), '2007〜': (200701, FR_LAST), '2013-07〜': (201307, FR_LAST)}
    out = {'市場との差（市場＝French の Mkt-RF＋RF・時価加重）': {}, '勝ち − 負け（同じ表の中）': {}}
    for nm, s in vs_mkt.items():
        first = max(min(s), min(mkt))
        d = {pn: diff_stats(s, mkt, months(a, b)) for pn, (a, b) in periods(first).items()}
        d['市場に対して悪かった暦年（差の下位5年）'] = worst_years(s, mkt, first, FR_LAST)
        d['市場に対する最大の相対下落'] = rel_drawdown(s, mkt, months(first, FR_LAST))
        d['最初の月'] = first
        out['市場との差（市場＝French の Mkt-RF＋RF・時価加重）'][nm] = d
    for nm, (hi, lo) in spreads.items():
        first = max(min(hi), min(lo))
        out['勝ち − 負け（同じ表の中）'][nm] = {pn: diff_stats(hi, lo, months(a, b)) for pn, (a, b) in periods(first).items()}
        out['勝ち − 負け（同じ表の中）'][nm]['最初の月'] = first
    return out, s6['BIG HiPRIOR'], s25['BIG HiPRIOR']


# ───────────────────────── SMT の本物の記録（円） ─────────────────────────
def smt_actual(U, M):
    import factor_etf_rakuten as FR
    nav, bad, first_day = FR.nav_monthly(SMT_ISIN, SMT_ASSOC)
    fx, fx_url = U.fred_monthly_last('DEXJPUS')
    ms = months(202601, 202609)
    miss = [m for m in ms if m not in nav]
    if miss:
        raise SystemExit(f'SMT の基準価額の月が欠けている: {miss}')
    usd = {t: M.yahoo(t) for t in ('MTUM', 'SPMO', 'QQQ', 'SPY', 'SMH')}
    ser = {'SMT（本体・円）': nav}
    for t, s in usd.items():
        ser[f'{t}（円）'] = FR.to_jpy(s, fx)
    for nm, s in ser.items():
        if any(m not in s for m in ms):
            raise SystemExit(f'{nm} の月が欠けている')
    cum = {nm: p2(math.prod(1 + s[m] for m in ms) - 1, 1) for nm, s in ser.items()}
    tab = {str(m): {nm: p2(s[m], 1) for nm, s in ser.items()} for m in ms}
    corr = {nm: round(M.corr([nav[m] for m in ms], [s[m] for m in ms]), 2) for nm, s in ser.items() if nm != 'SMT（本体・円）'}
    mx = {nm: p2(FR.mdd(s, ms), 1) for nm, s in ser.items()}
    return dict(窓='2026-01〜2026-09（9か月・設定 2025-12-16 の次の月から）', 累計=cum, 月ごと=tab, SMTとの月次の相関_9点=corr, 最大下落_月末=mx,
                基準価額=f'投信ライブラリーの基準価額 CSV（{SMT_ISIN}・最初の日 {first_day}・読めない行 {bad}・分配金は再投資＝設定来0円）',
                円=f'米国 ETF は月末の FRED DEXJPUS の比（{fx_url}）・投信の月末は米国の前日の終値まで＝月ごとに少しずれる',
                注='9か月＝判断に使えない短さ（月次の相関は9点）')


# ───────────────────────── 集中と重なり ─────────────────────────
def concentration():
    tgt = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    prof = json.load(open(os.path.join(BASE, 'out', 'etf_profiles.json')))['etfs']
    alias = {'IFREE-NDX': 'QQQM'}
    wts = {alias.get(k, k): float(v) for k, v in tgt['ami_weights'].items() if float(v) > 0}
    miss = [k for k in wts if k not in prof]
    assert not miss, f'etf_profiles.json に中身が無い本: {miss}'
    tot_all = 100.0                               # 全体の%（ETF 側の目標は全体の%で書かれている）
    cur, asof, in_etf = {}, {}, {}
    for k, w in wts.items():
        asof[k] = prof[k].get('asof')
        for row in prof[k]['h']:
            t, x = row[0], float(row[1])
            if not t or t == 'n/a':
                continue
            t = 'GOOGL' if t == 'GOOG' else t
            cur[t] = cur.get(t, 0.0) + w / tot_all * x
            in_etf.setdefault(t, {})[k] = round(100 * x, 2)
    rows = []
    for t, nm, w, ind in SMT_TOP10:
        rows.append(dict(ティッカー=t, 名前=nm, SMT内の重さ=w, 業種=ind, 今の資産全体での重さ_ETF経由=p2(cur.get(t, 0.0)), 入っているETF=in_etf.get(t, {}),
                         SMTを5足したときの増え=round(SLOT * w / 100, 2)))
    by_ind = {}
    for t, nm, w, ind in SMT_TOP10:
        by_ind[ind] = round(by_ind.get(ind, 0.0) + w, 1)
    return dict(上位10社=rows, 上位10社の合計=round(sum(x[2] for x in SMT_TOP10), 1), 上位10社の業種=by_ind,
                今のETF側={'目標（全体の%）': wts, '中身の日付': asof},
                注=['21銘柄の等金額＝1社約4.8%・残り11社は開示なし（上位10社は交付目論見書 2026-07-31）',
                    '今の資産全体での重さは ETF 側の目標（全体の%）× 各 ETF の中身（out/etf_profiles.json・本ごとに日付が違う）・個別株10%は数えない'])


# ───────────────────────── 本体 ─────────────────────────
def main():
    import mw_common as M
    import unx_assets as U
    import upside_check as UC
    import ndx_swap_check as N
    import bestpf_eval as E
    t0 = time.time()
    W_CRASH, W_DC = UC.W_CRASH, UC.W_DC
    P = json.load(open(PREREG))
    F = {k: dict(v) for k, v in P['forms_etf_side_percent_of_total'].items()}
    assert set(F) == {CUR} | set(K.values()), sorted(F)

    res = U.build()
    rows, chains = res['rows'], res['chains']
    R = U.R
    if 'MTUM' not in rows or 'MTUM' not in R.C:
        raise SystemExit('MTUM の行が無い（unx_assets.build の R7）')
    if any(m not in chains['MTUM'] for m in months(UC.FIRST, UC.END)):
        raise SystemExit('MTUM の毎月の値が主の窓にそろわない')
    if abs(rows['MTUM']['er_vehicle'] - MTUM_ER) > 1e-12:
        raise SystemExit(f"MTUM の経費率が想定と違う: {rows['MTUM']['er_vehicle']}")

    # ── SMT_MOM（MTUM − 費用の差）──
    Dm, _, _ = E.load_D(rows, ['MTUM'])
    d_mtum = rows['MTUM'].get('D_override', Dm['MTUM'])
    smt = dict(rows['MTUM'])
    smt.update(A1=rows['MTUM']['A1'] - FEE_GAP, A2=rows['MTUM']['A2'] - FEE_GAP, B=rows['MTUM']['B'] - FEE_GAP, C=rows['MTUM']['C'] - FEE_GAP,
               D_override=d_mtum - FEE_GAP, er_vehicle=SMT_ER, ja='SMT 米国株式モメンタムファンド（MTUM の写し − 費用の差）', vehicle='SMT 米国株式モメンタム（投信）')
    rows['SMT_MOM'] = smt
    chains['SMT_MOM'] = dict(chains['MTUM'])
    R.C['SMT_MOM'] = dict(R.C['MTUM'])
    reg3 = dict(A1=rows['MTUM']['A1'] - smt['A1'], B=rows['MTUM']['B'] - smt['B'], C=rows['MTUM']['C'] - smt['C'], D=d_mtum - smt['D_override'],
                A1_gross=rows['MTUM']['A1_gross'] - smt['A1_gross'])
    ok3 = (all(abs(reg3[k] - FEE_GAP) < 1e-12 for k in ('A1', 'B', 'C', 'D')) and abs(reg3['A1_gross']) < 1e-15
           and chains['SMT_MOM'] == chains['MTUM'])

    # ── SMT_CONC（確かめ・集中型の代理）──
    ev, big_hi6, big_hi25 = french_evidence(M)
    conc = {m: v for m, v in big_hi25.items() if m <= FR_LAST}
    if any(m not in conc for m in months(UC.FIRST, FR_LAST)):
        raise SystemExit('25_Portfolios_ME_Prior_12_2 の BIG HiPRIOR が主の窓にそろわない')
    for m in months(FR_LAST + 1 if FR_LAST % 100 != 12 else FR_LAST + 89, UC.END):
        conc[m] = chains['MTUM'][m] + MTUM_ER / 12
    cr = dict(smt)
    a1g = geo(conc, months(UC.FIRST, UC.END))
    a2g = geo(conc, months(*R.A2))
    cr.update(A1_gross=a1g, A2_gross=a2g, A1=a1g - SMT_ER - smt['tax_drag'], A2=a2g - SMT_ER - smt['tax_drag'],
              ja='SMT の確かめ（French 大型×勢い上位20%・時価加重 − 0.77%）', proxy='FRENCH_25_ME5_PRIOR5', proxy_until=FR_LAST,
              vol_A1=None, maxdd_A1=None, vol_A2=None, maxdd_A2=None)   # MTUM の写しの表示用の値を残さない（単体の値は相関の表）
    rows['SMT_CONC'] = cr
    chains['SMT_CONC'] = conc
    R.C['SMT_CONC'] = dict(R.C['MTUM'])
    U.log('SMT_MOM', {k: round(100 * smt[k], 2) for k in ('A1', 'A2', 'B', 'C')}, 'D', round(100 * smt['D_override'], 2),
          '| SMT_CONC adj', round(100 * (cr['A1'] - cr['A1_gross']), 3), 'A1_gross', round(100 * a1g, 2))

    ways = {}
    cur = F[CUR]
    tot = sum(cur.values())
    pp = {c: w * (tot - SLOT) / tot for c, w in cur.items()}; pp['SMT_MOM'] = SLOT
    n10 = dict(cur); n10['QQQM'] -= 2 * SLOT; n10['SMT_MOM'] = 2 * SLOT
    WAYS = {'+SMT_MOM（按分P5・ETF 側全部から5）': pp, '+SMT_MOM（N10・NASDAQ100 から10）': n10}
    allp = dict(F, **WAYS)
    assets = sorted({a for f in allp.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, assets)
    pi, _, _ = E.load_pi()
    _, sim = U.tables()

    U.log('USD の枠（', len(F), '形）')
    tab_usd = U.measure(F, rows, chains, mega=mega)
    ea = json.load(open(os.path.join(BASE, 'out', 'etf_add_check.json')))['results']['機械1 USD・崩れあり（主）']
    reg1, ok1 = {}, True
    for mine, theirs in ETF_ADD_KEYS.items():
        for k in ('P15π', 'P5π（5%未満）', '最悪の世界', '最大下落'):
            a, b = tab_usd[W_CRASH][mine][k], ea[theirs][k]
            same = UC.r1(a) == UC.r1(b)
            reg1[f'{mine}・{k}'] = dict(etf_add=b, この道具=a, 一致=same)
            ok1 = ok1 and same
    k4, chips = N.chips_adj(rows, assets)
    vt_usd = N.variants(allp, rows, chains, k4)
    reg2 = N.regress_variants(vt_usd, tab_usd)
    U.log('回帰の検査', ok1, reg2['max_abs_diff'], ok3)
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/smt_mom_check.py', prereg='out/smt_mom_prereg.json（eb119b72）',
               question=P['question'],
               regression={'① 今・+GDX と out/etf_add_check.json（USD・崩れあり・小数1桁）': dict(ok=ok1, rows=reg1),
                           '② 感度の計算の主と unx_assets.measure（USD・丸める前・1e-9）': {k: v for k, v in reg2.items() if k != 'rows'},
                           '③ SMT_MOM が MTUM と費用の差（0.0062）だけ違う': dict(ok=ok3, 差=reg3)})
    if not (ok1 and reg2['ok'] and ok3):
        doc['decision'] = '回帰の検査に失敗＝止めた'
        json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
        raise SystemExit('回帰の検査に失敗')

    U.log('円の枠')
    ch_jpy, fx_url = U.jpy_chains(chains)
    tab_jpy = U.measure(F, rows, ch_jpy, mega=mega)
    vt_jpy = N.variants(allp, rows, ch_jpy, k4)
    reg4 = N.regress_variants(vt_jpy, tab_jpy)
    doc['regression']['④ 円の枠でも②と同じ'] = {k: v for k, v in reg4.items() if k != 'rows'}
    if not reg4['ok']:
        doc['decision'] = '回帰の検査に失敗（円）＝止めた'
        json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
        raise SystemExit('回帰の検査に失敗（円）')

    # ── 100年の代用（この道具の中だけで部品を足す）──
    C = U.century_parts()
    C['parts']['MTUM'] = dict(big_hi6)
    C['parts']['SMT_MOM'] = {m: v - FEE_GAP / 12 for m, v in big_hi6.items()}
    C['parts']['SMT_CONC'] = {m: v - FEE_GAP / 12 for m, v in big_hi25.items()}
    U.MONTHLY_OK.update({'MTUM', 'SMT_MOM', 'SMT_CONC'})
    cc, seats, cpct = U.castle_copy()
    cent = {nm: U.century_monthly(U.whole(f, cc)) for nm, f in F.items()}

    # ── 判定 ──
    from unx_final import conds
    frames = {FRAMES[0]: (vt_usd, W_CRASH), FRAMES[1]: (vt_usd, W_DC), FRAMES[2]: (vt_jpy, W_CRASH)}
    MAIN_C, CONC_C = 'SMT の価値（+SMT_MOM − 今）', '確かめ: 集中型の代理（+SMT_CONC − 今）'
    VEH_C, MOM_C = '参考: 器の差（+SMT_MOM − +MTUM）', '参考: 勢いの賭けそのもの（+MTUM − 今）'
    GDXV_C, GDX_C = '参考: GDX と比べる（+SMT_MOM − +GDX）', '参考: GDX の価値（+GDX − 今・etf_add と同じ）'
    comps = {MAIN_C: (K['SMT_MOM'], CUR), CONC_C: (K['SMT_CONC'], CUR), VEH_C: (K['SMT_MOM'], K['MTUM']), MOM_C: (K['MTUM'], CUR),
             GDXV_C: (K['SMT_MOM'], K['GDX']), GDX_C: (K['GDX'], CUR)}
    judg, ins = {}, {}
    for cj, (a, b) in comps.items():
        judg[cj] = {fn: N.judge(vt, wn, a, b) for fn, (vt, wn) in frames.items()}
        cu = conds(tab_usd, a, b, cent[a], cent[b])
        c12 = bool(cu[W_CRASH]['(1) P15π の低下 ≤ 1.5pt'] and cu[W_CRASH]['(2) 最悪の世界・P5π・最大下落がすべて良い'])
        c3 = cu['(3) 100年の代用（全体の形）の20年・30年の中央が下がらず下位10%が上がる']
        ins[cj] = dict(USD=cu, 状態=('すべて満たす' if (c12 and c3) else ('(1)(2) を満たす・(3) は測れない' if (c12 and c3 is None) else '満たさない')))

    def main_of(cj):
        return judg[cj][FRAMES[0]]
    m = main_of(MAIN_C)
    others = {fn: judg[MAIN_C][fn]['まとめ'] for fn in FRAMES[1:]}
    if m['まとめ'] == '堅い価値あり':
        g = main_of(GDX_C)
        da, dg = m['感度']['主']['差'], g['感度']['主']['差']
        order = sorted([('SMT', da), ('GDX', dg)], key=lambda t: (-t[1]['平均'], -t[1]['最悪']))
        rd = 'R1: SMT も足す候補（主の Δ平均 の順: ' + ' ＞ '.join(t[0] for t in order) + '）'
        split = {k: v for k, v in others.items() if v != '堅い価値あり'}
        if split:
            rd += '——窓・通貨で割れる（' + '・'.join(f'{k} は {v}' for k, v in split.items()) + '）'
    elif m['まとめ'] == '前提しだい' and ins[MAIN_C]['状態'] == 'すべて満たす':
        rd = 'R2: 保険として足すのは筋が通る（好みの差）'
    else:
        rd = f"R3: 足す根拠はデータに無い（入れるなら好みの賭け）（まとめ {m['まとめ']}・主 {m['主の判定']}・保険 {ins[MAIN_C]['状態']}）"
    v = main_of(VEH_C)
    r4 = (f"R4: 器の差（+SMT_MOM − +MTUM）は {v['まとめ']}（主 {v['主の判定']}・Δ平均 {v['感度']['主']['差']['平均']:+.3f}）——"
          '同じ勢いの賭けなら費用の差の分だけ MTUM が良いが、楽天で買える勢いの器は SMT だけ')
    c = main_of(CONC_C)
    r5 = (f"R5: 代理で割れる（集中型の写しでは {c['まとめ']}・主 {c['主の判定']}）" if c['まとめ'] != m['まとめ']
          else f"R5: 代理を集中型に替えても同じ（{c['まとめ']}）")
    read = dict(R1_R3=rd, R4=r4, R5=r5, R6='楽天で買える勢いの器は SMT（投信・NISA 成長投資枠）だけ——MTUM・SPMO は楽天に無い（判定には入れていない）',
                R7='配分は変えない（報告するだけ）', 確かめの枠=others)

    # ── 参考（判定に使わない）──
    U.log('参考: 上振れ・転がる積立・相関・長い歴史・本物の記録・集中')

    def show(r):
        return {k: r[k] for k in ('P15π', 'P15π（A2を外す）', 'P5π（5%未満）', 'P0π（元本割れ）', '最悪の世界', 'π加重の平均の年率', 'ぶれ', '最大下落',
                                  '崩れ2000型_16〜18年目', '過去の転がる20年で15%以上', '世界ごとの年率')}
    table = {}
    for nm in F:
        r = tab_usd[W_CRASH][nm]
        q, pr_ = UC.upside(sim, r['_raw'], pi)
        table[nm] = dict(show(r), 上振れ=dict(pr_, 内部収益率の分位=q))
    roll = {nm: UC.rolling(f, rows, chains) for nm, f in F.items()}
    for nm, f in WAYS.items():
        j = N.judge(vt_usd, W_CRASH, nm, CUR)
        ways[nm] = dict(まとめ=j['まとめ'], 主の判定=j['主の判定'], 主の差=j['感度']['主']['差'], 感度={k: x['判定'] for k, x in j['感度'].items()})
    q_ = N.monthly_series({'QQQM': 1}, rows, chains, UC.FIRST, UC.END)[1]
    s_ = N.monthly_series({'SMH': 1}, rows, chains, UC.FIRST, UC.END)[1]
    mk = N.monthly_series({'VOO': 1}, rows, chains, UC.FIRST, UC.END)[1]
    corr = {}
    for x in ('SMT_MOM', 'SMT_CONC', 'MTUM', 'GDX'):
        xs = N.monthly_series({x: 1}, rows, chains, UC.FIRST, UC.END)[1]
        corr[x] = {'NASDAQ100（QQQM）': N.corr(xs, q_), 'SMH': N.corr(xs, s_), 'S&P500（VOO）': N.corr(xs, mk), '単体（費用と外国税を引いた後）': N.stats(xs)}
    corr['QQQM'] = {'単体（費用と外国税を引いた後）': N.stats(q_)}
    corr['VOO'] = {'単体（費用と外国税を引いた後）': N.stats(mk)}
    cent_out = {nm: U.strip_century(d) for nm, d in cent.items() if d is not None}
    actual = smt_actual(U, M)
    conc_info = concentration()
    rowinfo = {nm: {k: (round(100 * vv, 3) if isinstance(vv, float) else vv) for k, vv in rows[nm].items()
                    if k in ('A1', 'A2', 'A1_gross', 'A2_gross', 'B', 'C', 'D_override', 'er_vehicle', 'dy_vehicle', 'tax_drag', 'proxy', 'proxy_until',
                             'top_industries', 'vol_A1', 'maxdd_A1')}
               for nm in ('SMT_MOM', 'SMT_CONC', 'MTUM')}
    rowinfo['MTUM']['D（bestpf_cma_2026）'] = round(100 * d_mtum, 3)

    doc.update(
        facts=P['facts_known_before_measuring'], rows=rowinfo,
        K4_半導体の基礎率={c_: dict(Chips=(None if chips[c_] is None else round(chips[c_], 3)), 足す年率=round(100 * k4[c_], 3)) for c_ in assets},
        pi=pi, forms=F, ways_forms=WAYS,
        judgments={cj: {fn: dict(まとめ=j['まとめ'], 主の判定=j['主の判定'], 感度=j['感度']) for fn, j in d.items()} for cj, d in judg.items()},
        insurance=ins, reading=read, ways_to_add=ways,
        results={'USD・崩れあり（主）': table, 'USD・ドットコム級なし': {nm: show(tab_usd[W_DC][nm]) for nm in F},
                 '円・崩れあり': {nm: show(tab_jpy[W_CRASH][nm]) for nm in F}, '過去の転がる積立（USD・2000-09〜2026-09）': roll,
                 '100年の代用（全体の形）': cent_out, '相関と単体の値動き（月次・USD・2000-09〜2026-09）': corr,
                 '長い歴史の手がかり（French・時価加重・〜2026-08）': ev, 'SMT の本物の記録（円）': actual, '集中と重なり': conc_info, '費用（年%・税込）': FEES},
        frames={'USD': 'night/bestpf_check.py と同じ（ドル建て）', '円': f'月次のドル建ての値に FRED DEXJPUS の月末の比（{fx_url}）・B/C/D はドルのまま'},
        castle_copy=dict(seats=seats, castle_pct=cpct),
        caveats=['SMT の 2026 年より前は MTUM の写し（2013-04 より前は French の BIG HiPRIOR）＝SMT の作り方（21社・等金額・6/12/36か月・直近1か月を飛ばさない）の'
                 '違いは主の物差しの外。確かめに集中型（French の大型×勢い上位20%）を当てた',
                 '世界B・C・D は MTUM の値 − 費用の差＝SMT の銘柄の選び方の上乗せ・損は持たない',
                 '年4回の入れ替えの売買の費用は信託報酬の外で測っていない（21社の等金額は入れ替えが多い）',
                 '長い歴史の手がかりは French の表（12-2・60-13・1-0 の窓）＝SMT の窓そのものではない',
                 'ETF 側だけを測る（個別株10は物差しの外）・判定は事前登録どおり・配分は変えない'],
        decision='配分は変えない（報告するだけ・事前登録 R7）', secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    U.log('→', OUT, f'{time.time() - t0:.0f}秒')
    for cj, d in judg.items():
        for fn, j in d.items():
            dd = j['感度']['主']['差']
            U.log(f"{cj[:24]:<24} {fn:<14} {j['まとめ']:<10} 主 {j['主の判定']:<5} Δ平均{dd['平均']:+.3f} Δ最悪{dd['最悪']:+.3f} Δ確率{dd['確率']:+.2f} "
                  f"Δぶれ{dd['ぶれ']:+.2f} Δ5%未満{dd['5%未満']:+.2f} Δ下落{dd['最大下落']:+.2f} | {[x['判定'] for x in j['感度'].values()]}")
        U.log('   保険', ins[cj]['状態'])
    U.log('読み', json.dumps(read, ensure_ascii=False))
    U.log('足し方', json.dumps(ways, ensure_ascii=False)[:1500])
    U.log('本物の記録', json.dumps(actual['累計'], ensure_ascii=False), json.dumps(actual['SMTとの月次の相関_9点'], ensure_ascii=False))


if __name__ == '__main__':
    main()
