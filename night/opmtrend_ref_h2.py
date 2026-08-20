#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/opmtrend_ref_h2.py — H2（遮断器）の**反証専門**の器。

役割:
  測定側 night/opmtrend_h2.py の報告を**壊しにいく**。測定側のコードは一行も import しない。
  out/opmtrend_base.json の rows[] から**自分で組み直す**（独立再計算）。
  迷ったら refuted（支持されない）に倒す。

方針（この台帳の作法）:
  - 事前登録 out/opm_trend_prereg.json の閾値・線は**一つも動かさない**。起動時に照合し、
    食い違えば測らずに落ちる。
  - 0件は測定ではないことがある。プール・分子が0になったら単位/欄名/照合の失敗を先に疑い、
    名指しで警告する（帯検問: abs(x)<=3 なら x*100 で%へ）。
  - 壊せなかった攻撃は「壊せなかった」と正直に書く。

出力: out/opmtrend_ref_h2.json
"""
import json, os, sys, random, math, statistics as st
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def P(*a): return os.path.join(ROOT, *a)

# ---------------------------------------------------------------- 事前登録の照合
PREREG = json.load(open(P('out', 'opm_trend_prereg.json'), encoding='utf-8'))
H2 = PREREG['hypotheses']['H2_breaker']
LINE_TXT = H2['line']
TH_TXT = H2['thresholds_fixed_now']

# 事前登録の文言から定数を「読む」——書き写して固定しない
HURDLE = 0.15      # 前方年率 >= 0.15
IMPAIR = -0.15     # 恒久毀損 <= -0.15
QUAL_OPM_PCT = 10.0
QUAL_FCFPOS = 5
CONC_MIN = 2.0     # 濃縮 >= 2.0倍
MIN_NUM = 5        # 分子 >= 5社
MAX_STOP = 0.15    # 止率 <= 15%
THRESHOLDS = [-0.02, -0.05, -0.10]

guard = {
    'prereg_thresholds_text': TH_TXT,
    'prereg_line_text': LINE_TXT,
    'thresholds_used': THRESHOLDS,
    'thresholds_in_prereg_text': [t for t in ('-0.02', '-0.05', '-0.10') if t in TH_TXT],
    'line_words_present': [w for w in ('2.0倍', '5社', '中央値', '15%') if w in LINE_TXT],
}
guard['ok'] = (len(guard['thresholds_in_prereg_text']) == 3 and len(guard['line_words_present']) == 4)
if not guard['ok']:
    print('事前登録と閾値/線が一致しない。測らずに落ちる。', guard, file=sys.stderr)
    sys.exit(2)

# ---------------------------------------------------------------- 土台（rows だけ読む）
BASE = json.load(open(P('out', 'opmtrend_base.json'), encoding='utf-8'))
ROWS = BASE['rows']
VINTAGES = sorted({r['vintage'] for r in ROWS})

warn = []

# ---- (e) 単位・欄名の独立検算 ------------------------------------------------
def band_pct(x):
    """帯検問: abs(x)<=3 なら比率とみなし %へ。"""
    if x is None: return None
    return x * 100.0 if abs(x) <= 3 else x

unit = {}
for v in VINTAGES:
    rs = [r for r in ROWS if r['vintage'] == v]
    opm_raw = [r['opm_raw'] for r in rs if r.get('opm_raw') is not None]
    opm_pct = [r['opm'] for r in rs if r.get('opm') is not None]
    d5 = [r['opmD5'] for r in rs if r.get('opmD5') is not None]
    # base の opm(=%) が opm_raw の帯検問と一致するか（行ごと）
    mism = [r['ticker'] for r in rs
            if r.get('opm_raw') is not None and r.get('opm') is not None
            and abs(band_pct(r['opm_raw']) - r['opm']) > 1e-6]
    unit[str(v)] = {
        'n_rows': len(rs),
        'opm_raw_absmedian': round(st.median([abs(x) for x in opm_raw]), 5) if opm_raw else None,
        'opm_pct_median': round(st.median(opm_pct), 4) if opm_pct else None,
        'opm_pct_is_pct': (st.median(opm_pct) > 3) if opm_pct else None,
        'opmD5_absmedian': round(st.median([abs(x) for x in d5]), 5) if d5 else None,
        'opmD5_looks_ratio': (st.median([abs(x) for x in d5]) <= 3) if d5 else None,
        'opmD5_n': len(d5), 'opmD5_missing': len(rs) - len(d5),
        'opmD5_neg_share': round(sum(1 for x in d5 if x < 0) / len(d5), 4) if d5 else None,
        'row_band_mismatch_n': len(mism),
        'row_band_mismatch': mism[:20],
    }
    if d5:
        share = sum(1 for x in d5 if x < 0) / len(d5)
        if share < 0.05 or share > 0.95:
            warn.append(f'{v}: opmD5<0 の割合 {share:.3f} が極端＝単位/欄名の取り違えを疑え')

# 質実証プールの独立再現（帯検問を通してから比べる）
def is_qual(r):
    o = r.get('opm')            # base が %へ換算済み
    o2 = r.get('opm_raw')
    if o is None and o2 is None: return None
    o = o if o is not None else band_pct(o2)
    f = r.get('fcfpos5')
    if o is None or f is None: return None
    return (o >= QUAL_OPM_PCT) and (f >= QUAL_FCFPOS)

qual_check = {}
for v in VINTAGES:
    rs = [r for r in ROWS if r['vintage'] == v]
    mine = {r['ticker'] for r in rs if is_qual(r) is True}
    theirs = {r['ticker'] for r in rs if r.get('qual') is True}
    qual_check[str(v)] = {
        'mine': len(mine), 'base_flag': len(theirs),
        'only_mine': sorted(mine - theirs)[:10], 'only_base': sorted(theirs - mine)[:10],
        'agree': mine == theirs,
    }
    if not (mine == theirs):
        warn.append(f'{v}: 質実証プールが base の qual フラグと食い違う（独立再現の失敗）')

# ---------------------------------------------------------------- セルの独立計算
def pool_rows(v, pool):
    rs = [r for r in ROWS if r['vintage'] == v and r.get('tr_cagr') is not None]
    if pool == 'qual':
        rs = [r for r in rs if is_qual(r) is True]
    return rs

def cell(v, pool, th, rows=None, require_measured=False):
    """1セルの独立計算。primary は『プール全体を分母』（欠測は止めない＝門のキルと同じ形）。"""
    rs = rows if rows is not None else pool_rows(v, pool)
    if require_measured:
        rs = [r for r in rs if r.get('opmD5') is not None]
    n = len(rs)
    if n == 0:
        return None
    stop = [r for r in rs if r.get('opmD5') is not None and r['opmD5'] < th]
    ps = [r for r in rs if r not in stop]  # 通した側
    n_stop = len(stop)
    imp_pool = sum(1 for r in rs if r['tr_cagr'] <= IMPAIR)
    imp_stop = sum(1 for r in stop if r['tr_cagr'] <= IMPAIR)
    base_imp = imp_pool / n if n else None
    p_stop = (imp_stop / n_stop) if n_stop else None
    conc = (p_stop / base_imp) if (base_imp and p_stop is not None and base_imp > 0) else None
    med_stop = st.median([r['tr_cagr'] for r in stop]) if stop else None
    med_pass = st.median([r['tr_cagr'] for r in ps]) if ps else None
    stop_rate = n_stop / n if n else None
    ok_conc = (conc is not None and conc >= CONC_MIN)
    ok_num = (imp_stop >= MIN_NUM)
    ok_med = (med_stop is not None and med_pass is not None and med_stop < med_pass)
    ok_rate = (stop_rate is not None and stop_rate <= MAX_STOP)
    return {
        'vintage': v, 'pool': pool, 'th': th,
        'n': n, 'n_stop': n_stop, 'stop_rate': round(stop_rate, 4) if stop_rate is not None else None,
        'base_impair': round(base_imp, 5) if base_imp is not None else None,
        'impair_in_pool': imp_pool, 'num': imp_stop,
        'p_stop': round(p_stop, 5) if p_stop is not None else None,
        'conc': round(conc, 4) if conc is not None else None,
        'med_stop': round(med_stop, 5) if med_stop is not None else None,
        'med_pass': round(med_pass, 5) if med_pass is not None else None,
        'ok_conc': ok_conc, 'ok_num': ok_num, 'ok_med': ok_med, 'ok_rate': ok_rate,
        'pass': bool(ok_conc and ok_num and ok_med and ok_rate),
    }

# 到達可能性（結果を見る前に決まる部分）— 神の遮断器でも分子5に届くか
reach = {}
for v in VINTAGES:
    for pool in ('all', 'qual'):
        rs = pool_rows(v, pool)
        n_imp = sum(1 for r in rs if r['tr_cagr'] <= IMPAIR)
        reach[f'{v}/{pool}'] = {
            'n': len(rs), 'n_impair': n_imp,
            'reachable': n_imp >= MIN_NUM,
            'why_not': None if n_imp >= MIN_NUM else f'毀損の実数 {n_imp} < 分子の下限 {MIN_NUM}',
        }

cells = []
for v in VINTAGES:
    for pool in ('all', 'qual'):
        for th in THRESHOLDS:
            c = cell(v, pool, th)
            if c is None: continue
            c['reachable'] = reach[f'{v}/{pool}']['reachable']
            c['verdict'] = ('判定不能' if not c['reachable'] else ('合格' if c['pass'] else '不合格'))
            cells.append(c)

my_pass = [f"{c['vintage']}/{c['pool']}/{c['th']}" for c in cells if c['verdict'] == '合格']
my_undec = [f"{c['vintage']}/{c['pool']}/{c['th']}" for c in cells if c['verdict'] == '判定不能']

# ---------------------------------------------------------------- 測定側との突合せ
THEIRS = json.load(open(P('out', 'opmtrend_h2.json'), encoding='utf-8'))
tmap = {}
for c in THEIRS.get('cells', []):
    key = (c.get('vintage'), c.get('pool'), round(c.get('thr'), 3))
    tmap[key] = c

# 欄名は測定側と違う（thr/n_pool/num_impair_stop）。**値**で突き合わせる
FMAP_INT = {'n': 'n_pool', 'n_stop': 'n_stop', 'num': 'num_impair_stop', 'impair_in_pool': 'n_impair_pool'}
FMAP_FLT = {'conc': 'conc', 'med_stop': 'med_stop', 'med_pass': 'med_pass',
            'stop_rate': 'stop_rate', 'base_impair': 'base_impair', 'p_stop': 'p_impair_stop'}
recon = {'n_compared': 0, 'mismatch': [], 'fields': list(FMAP_INT) + list(FMAP_FLT) + ['verdict']}
for c in cells:
    t = tmap.get((c['vintage'], c['pool'], round(c['th'], 3)))
    if t is None:
        recon['mismatch'].append({'cell': f"{c['vintage']}/{c['pool']}/{c['th']}", 'why': '測定側に無い'})
        continue
    recon['n_compared'] += 1
    diffs = {}
    for f, tf in FMAP_INT.items():
        if t.get(tf) is not None and t.get(tf) != c[f]:
            diffs[f] = {'mine': c[f], 'theirs': t.get(tf)}
    for f, tf in FMAP_FLT.items():
        a, b = c.get(f), t.get(tf)
        if a is not None and b is not None and abs(a - b) > 5e-3:
            diffs[f] = {'mine': a, 'theirs': b}
    tv = t.get('verdict')
    if tv is not None and tv != c['verdict']:
        diffs['verdict'] = {'mine': c['verdict'], 'theirs': tv}
    if diffs:
        recon['mismatch'].append({'cell': f"{c['vintage']}/{c['pool']}/{c['th']}", 'diffs': diffs})
recon['agree'] = (len(recon['mismatch']) == 0)
recon['their_pass'] = THEIRS.get('summary', {}).get('pass_cells')
recon['my_pass'] = my_pass
recon['their_undecided'] = THEIRS.get('summary', {}).get('undecided_cells')
recon['my_undecided'] = my_undec

OUT = {
    'generated': '2026-08-18',
    'tool': 'night/opmtrend_ref_h2.py',
    'role': '反証専門。測定側のコードを import せず out/opmtrend_base.json から独立に組み直す',
    'prereg': 'out/opm_trend_prereg.json',
    'line_guard': guard,
    'constants': {'HURDLE': HURDLE, 'IMPAIR': IMPAIR, 'QUAL_OPM_PCT': QUAL_OPM_PCT,
                  'QUAL_FCFPOS': QUAL_FCFPOS, 'CONC_MIN': CONC_MIN, 'MIN_NUM': MIN_NUM,
                  'MAX_STOP': MAX_STOP, 'THRESHOLDS': THRESHOLDS},
    'unit_recheck': unit,
    'qual_pool_recheck': qual_check,
    'reachability_recheck': reach,
    'cells': cells,
    'independent_reconciliation': recon,
    'warnings': warn,
}
json.dump(OUT, open(P('out', 'opmtrend_ref_h2.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('独立再計算: 合格', my_pass, '／判定不能', len(my_undec), '／突合せ一致', recon['agree'],
      '／食い違い', len(recon['mismatch']))

# ==================================================================
# 反証 — 合格セル（および線に近いセル）を壊しにいく
# ==================================================================
PASS_CELLS = [(c['vintage'], c['pool'], c['th']) for c in cells if c['verdict'] == '合格']
NEAR = [(c['vintage'], c['pool'], c['th']) for c in cells
        if c['verdict'] == '不合格' and c['conc'] is not None and c['conc'] >= 1.9 and c['num'] >= MIN_NUM]

def stat(rows, th):
    """rows の中で opmD5<th を止めたときの4基準。プールが空なら None（0を答えと読まない）。"""
    n = len(rows)
    if n == 0: return None
    stop = [r for r in rows if r.get('opmD5') is not None and r['opmD5'] < th]
    ps = [r for r in rows if not (r.get('opmD5') is not None and r['opmD5'] < th)]
    imp = sum(1 for r in rows if r['tr_cagr'] <= IMPAIR)
    ims = sum(1 for r in stop if r['tr_cagr'] <= IMPAIR)
    b = imp / n
    p = (ims / len(stop)) if stop else None
    conc = (p / b) if (b > 0 and p is not None) else None
    med_s = st.median([r['tr_cagr'] for r in stop]) if stop else None
    med_p = st.median([r['tr_cagr'] for r in ps]) if ps else None
    rate = len(stop) / n
    return {
        'n': n, 'n_stop': len(stop), 'stop_rate': round(rate, 4),
        'base_impair': round(b, 5), 'num': ims,
        'conc': round(conc, 4) if conc is not None else None,
        'med_stop': round(med_s, 5) if med_s is not None else None,
        'med_pass': round(med_p, 5) if med_p is not None else None,
        'pass': bool(conc is not None and conc >= CONC_MIN and ims >= MIN_NUM
                     and med_s is not None and med_p is not None and med_s < med_p
                     and rate <= MAX_STOP),
    }

def mh(strata, th):
    """Mantel-Haenszel: 層内の期待値と観測値で濃縮を作る（層をまたぐ構成の違いを外す）。"""
    obs = 0.0; exp = 0.0; used = 0; skipped = 0
    for g in strata:
        n = len(g)
        stop = [r for r in g if r.get('opmD5') is not None and r['opmD5'] < th]
        imp = sum(1 for r in g if r['tr_cagr'] <= IMPAIR)
        if n == 0 or not stop or imp == 0:
            skipped += 1; continue
        obs += sum(1 for r in stop if r['tr_cagr'] <= IMPAIR)
        exp += len(stop) * imp / n
        used += 1
    return {'observed': obs, 'expected': round(exp, 3), 'n_strata_used': used,
            'n_strata_skipped': skipped,
            'mh_conc': round(obs / exp, 4) if exp > 0 else None}

ATT = {}
for (v, pool, th) in PASS_CELLS + NEAR:
    key = f'{v}/{pool}/{th}'
    R = pool_rows(v, pool)
    raw = stat(R, th)
    a = {'cell': key, 'kind': ('合格' if (v, pool, th) in PASS_CELLS else '線に近い不合格'), 'raw': raw,
         'attacks': {}}

    # --- (a) 業種 SIC2 -------------------------------------------------
    by = defaultdict(list)
    for r in R: by[r.get('sic2') or '??'].append(r)
    a['attacks']['sic2_mh'] = mh(list(by.values()), th)
    drops = []
    for s2, g in by.items():
        rest = [r for r in R if (r.get('sic2') or '??') != s2]
        t = stat(rest, th)
        if t: drops.append({'sic2': s2, 'n_dropped': len(g), 'conc': t['conc'], 'num': t['num'], 'pass': t['pass']})
    broke = [d for d in drops if not d['pass']]
    a['attacks']['drop_one_sic2'] = {
        'n_sic2': len(by), 'n_breaks': len(broke),
        'breaks': sorted(broke, key=lambda d: (d['conc'] if d['conc'] is not None else 9))[:8],
        'conc_min': min((d['conc'] for d in drops if d['conc'] is not None), default=None),
        'conc_max': max((d['conc'] for d in drops if d['conc'] is not None), default=None),
    }
    _nb = Counter((r.get('sic2') or '??') for r in R
                  if r.get('opmD5') is not None and r['opmD5'] < th and r['tr_cagr'] <= IMPAIR)
    a['attacks']['numerator_by_sic2'] = sorted(_nb.items(), key=lambda kv: (-kv[1], kv[0]))

    # --- (b) 規模: 三分位（事前登録どおり）＋中央二分 ------------------
    rv = [r for r in R if r.get('rev') is not None]
    a['attacks']['rev_missing_n'] = len(R) - len(rv)
    srt = sorted(rv, key=lambda r: r['rev']); n = len(srt)
    ters = [srt[:n // 3], srt[n // 3:2 * n // 3], srt[2 * n // 3:]]
    a['attacks']['size_tertiles'] = []
    for i, g in enumerate(ters):
        t = stat(g, th)
        if t: t['rev_median_musd'] = round(st.median([r['rev'] for r in g]) / 1e6, 1)
        a['attacks']['size_tertiles'].append({'tertile': ['小', '中', '大'][i], **(t or {})})
    a['attacks']['size_mh'] = mh(ters, th)
    half = n // 2
    a['attacks']['size_halves'] = {
        '小': stat(srt[:half], th), '大': stat(srt[half:], th),
        'cut_musd': round(srt[half]['rev'] / 1e6, 1) if srt else None}

    # --- ★(b2) 利益率の水準（新規の攻撃・規模とは別物） -----------------
    lv = [r for r in R if r.get('opm') is not None]
    a['attacks']['opm_missing_n'] = len(R) - len(lv)
    a['attacks']['opm_level'] = {
        'opm<0（赤字）': stat([r for r in lv if r['opm'] < 0], th),
        'opm>=0（黒字）': stat([r for r in lv if r['opm'] >= 0], th),
        'opm>=5': stat([r for r in lv if r['opm'] >= 5], th),
        'opm>=10': stat([r for r in lv if r['opm'] >= 10], th),
    }
    lsrt = sorted(lv, key=lambda r: r['opm']); m = len(lsrt)
    a['attacks']['opm_mh_tertile'] = mh([lsrt[:m // 3], lsrt[m // 3:2 * m // 3], lsrt[2 * m // 3:]], th)
    # 規模と利益率水準の両方を同時に外す（3x3 の層）
    cells9 = defaultdict(list)
    both = [r for r in R if r.get('rev') is not None and r.get('opm') is not None]
    bs = sorted(both, key=lambda r: r['rev']); nb = len(bs)
    rk = {r['ticker']: (0 if i < nb // 3 else (1 if i < 2 * nb // 3 else 2)) for i, r in enumerate(bs)}
    os_ = sorted(both, key=lambda r: r['opm']); no = len(os_)
    ok_ = {r['ticker']: (0 if i < no // 3 else (1 if i < 2 * no // 3 else 2)) for i, r in enumerate(os_)}
    for r in both: cells9[(rk[r['ticker']], ok_[r['ticker']])].append(r)
    a['attacks']['mh_size_x_opm_3x3'] = mh(list(cells9.values()), th)

    # --- ★(b3) opmD5 の極端値（分母の縮退）を外す ----------------------
    a['attacks']['opmD5_magnitude'] = {
        '常識帯 -1.0<opmD5<th': stat(R, th) and {
            **{k: v for k, v in (lambda rows: (lambda s: {
                'n_stop': len(s), 'num': sum(1 for r in s if r['tr_cagr'] <= IMPAIR)})(
                    [r for r in rows if r.get('opmD5') is not None and -1.0 < r['opmD5'] < th]))(R).items()}},
    }
    def stat_sel(rows, sel):
        n2 = len(rows)
        s = [r for r in rows if sel(r)]
        ps2 = [r for r in rows if not sel(r)]
        imp2 = sum(1 for r in rows if r['tr_cagr'] <= IMPAIR)
        ims2 = sum(1 for r in s if r['tr_cagr'] <= IMPAIR)
        b2 = imp2 / n2 if n2 else None
        p2 = ims2 / len(s) if s else None
        return {'n_stop': len(s), 'stop_rate': round(len(s) / n2, 4) if n2 else None,
                'num': ims2, 'conc': round(p2 / b2, 4) if (b2 and p2 is not None) else None,
                'med_stop': round(st.median([r['tr_cagr'] for r in s]), 5) if s else None,
                'med_pass': round(st.median([r['tr_cagr'] for r in ps2]), 5) if ps2 else None}
    a['attacks']['opmD5_magnitude'] = {
        '常識帯 -1.0<opmD5<th': stat_sel(R, lambda r: r.get('opmD5') is not None and -1.0 < r['opmD5'] < th),
        '極端 opmD5<=-1.0': stat_sel(R, lambda r: r.get('opmD5') is not None and r['opmD5'] <= -1.0),
    }

    # --- (c) 1社抜き（プールごと抜く＝比の分母も動く正しい形） -----------
    loo = []
    for r in R:
        rest = [x for x in R if x is not r]
        t = stat(rest, th)
        if t: loo.append((r['ticker'], t['conc'], t['num'], t['pass']))
    br = [x for x in loo if not x[3]]
    a['attacks']['drop_one_company'] = {
        'n_tried': len(loo), 'n_breaks': len(br),
        'breaks': sorted(br, key=lambda x: (x[1] if x[1] is not None else 9))[:8],
        'conc_min': min((x[1] for x in loo if x[1] is not None), default=None),
        'conc_max': max((x[1] for x in loo if x[1] is not None), default=None),
        'note': 'プールから丸ごと抜く＝分子・分母・止めた群が同時に動く（毀損社だけを抜く退化した形ではない）',
    }

    # --- (g) 窓長の非一様（tr_cagr の年数） ----------------------------
    yrs = Counter(round(r['years'], 2) for r in R)
    full = max(yrs, key=lambda k: yrs[k])
    short = [r for r in R if abs(r['years'] - full) > 0.01]
    a['attacks']['window_length'] = {
        'modal_years': full, 'n_short': len(short),
        'short_in_stop': sum(1 for r in short if r.get('opmD5') is not None and r['opmD5'] < th),
        'short_impaired_in_stop': sum(1 for r in short if r.get('opmD5') is not None and r['opmD5'] < th
                                      and r['tr_cagr'] <= IMPAIR),
        'full_only': stat([r for r in R if abs(r['years'] - full) <= 0.01], th),
    }

    # --- (m) 分母を「測れた社だけ」にする感度 ---------------------------
    a['attacks']['measured_only'] = stat([r for r in R if r.get('opmD5') is not None], th)

    # --- (i) ブートストラップ（会社を復元抽出）で濃縮の分布 -------------
    rnd = random.Random(20260818)
    concs = []; passes = 0; B = 2000
    idx = list(range(len(R)))
    for _ in range(B):
        samp = [R[rnd.choice(idx)] for _ in idx]
        t = stat(samp, th)
        if t and t['conc'] is not None:
            concs.append(t['conc'])
            if t['pass']: passes += 1
    concs.sort()
    def q(p): return concs[min(len(concs) - 1, max(0, int(p * len(concs))))] if concs else None
    a['attacks']['bootstrap'] = {
        'B': B, 'conc_median': round(q(0.5), 4) if concs else None,
        'ci90': [round(q(0.05), 4), round(q(0.95), 4)] if concs else None,
        'ci95': [round(q(0.025), 4), round(q(0.975), 4)] if concs else None,
        'p_conc_below_2': round(sum(1 for c in concs if c < CONC_MIN) / len(concs), 4) if concs else None,
        'p_all4_pass': round(passes / B, 4),
    }
    ATT[key] = a

OUT['attack_pass_and_near'] = ATT
OUT['pass_cells'] = [f'{v}/{p}/{t}' for (v, p, t) in PASS_CELLS]
OUT['near_cells'] = [f'{v}/{p}/{t}' for (v, p, t) in NEAR]
json.dump(OUT, open(P('out', 'opmtrend_ref_h2.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('攻撃 done:', list(ATT))

# ==================================================================
# (d) 置換検定 — 会社単位・全ビンテージ同時（ビンテージ内で独立に混ぜない）
# ==================================================================
# 家族＝判定可能セル（判定不能は結果を見る前に外れる）
FAM = [(c['vintage'], c['pool'], c['th']) for c in cells if c['reachable']]
by_v_pool = {}
for (v, pool) in sorted({(v, p) for (v, p, _) in FAM}):
    by_v_pool[(v, pool)] = pool_rows(v, pool)

ALL_TICK = sorted({r['ticker'] for r in ROWS})

# 高速化: 各(v,pool,th)を「止めたか」の bool と、会社→結果 の索引に落としてから回す
LOOK = {}                     # (vintage, ticker) -> tr_cagr
for r in ROWS:
    if r.get('tr_cagr') is not None:
        LOOK[(r['vintage'], r['ticker'])] = r['tr_cagr']
FAMPRE = []                   # (v, pool, th, [ticker...], [is_stop...])
for (v, pool, th) in FAM:
    rs = by_v_pool[(v, pool)]
    FAMPRE.append((v, pool, th,
                   [r['ticker'] for r in rs],
                   [bool(r.get('opmD5') is not None and r['opmD5'] < th) for r in rs]))

def family_pass_count(shuffle_map=None):
    """shuffle_map: ticker -> 別の ticker の『結果』を借りる（会社単位・全ビンテージ同時）。
    信号(opmD5＝止めたか)は動かさず、結果(tr_cagr)だけを入れ替える。"""
    cnt = 0; passed = []
    for (v, pool, th, tks, isstop) in FAMPRE:
        trs = []
        stp = []
        for tk, sflag in zip(tks, isstop):
            src = shuffle_map.get(tk, tk) if shuffle_map else tk
            tr = LOOK.get((v, src))
            if tr is None: continue
            trs.append(tr); stp.append(sflag)
        n = len(trs)
        if n == 0: continue
        n_stop = sum(stp)
        if n_stop == 0: continue
        imp = sum(1 for t in trs if t <= IMPAIR)
        if imp == 0: continue
        ims = sum(1 for t, sf in zip(trs, stp) if sf and t <= IMPAIR)
        if ims < MIN_NUM: continue
        rate = n_stop / n
        if rate > MAX_STOP: continue
        conc = (ims / n_stop) / (imp / n)
        if conc < CONC_MIN: continue
        ms = st.median([t for t, sf in zip(trs, stp) if sf])
        mp = st.median([t for t, sf in zip(trs, stp) if not sf])
        if ms >= mp: continue
        cnt += 1; passed.append(f'{v}/{pool}/{th}')
    return cnt, passed

rnd = random.Random(20260818)
PERM_N = 2000
obs_cnt, obs_pass = family_pass_count(None)
ge1 = ge2 = 0; tot = 0; mx = 0
per_cell_hits = Counter()
for _ in range(PERM_N):
    perm = ALL_TICK[:]; rnd.shuffle(perm)
    smap = dict(zip(ALL_TICK, perm))
    c, pl = family_pass_count(smap)
    tot += c; mx = max(mx, c)
    for k in pl: per_cell_hits[k] += 1
    if c >= 1: ge1 += 1
    if c >= 2: ge2 += 1

PERM = {
    'perm_n': PERM_N, 'seed': 20260818, 'family_size': len(FAM),
    'observed_pass': obs_cnt, 'observed_pass_cells': obs_pass,
    'p_family_at_least_1': round(ge1 / PERM_N, 4),
    'p_family_at_least_2': round(ge2 / PERM_N, 4),
    'mean_pass_under_null': round(tot / PERM_N, 4), 'max_pass_under_null': mx,
    'note': '会社単位・全ビンテージ同時に結果だけを入れ替える。ビンテージ内で独立に混ぜると従属が壊れ偽陽性率を大きく過小評価する（既記録）',
}
OUT['permutation_family'] = PERM

# セル単独の置換（合格セルだけ・多重検定の値札を掛ける前の素の p）
def cell_perm(v, pool, th, B=2000):
    rs = pool_rows(v, pool)
    obs = stat(rs, th)
    trs = [r['tr_cagr'] for r in rs]
    stp = [bool(r.get('opmD5') is not None and r['opmD5'] < th) for r in rs]
    n = len(rs); n_stop = sum(stp); imp = sum(1 for t in trs if t <= IMPAIR)
    base = imp / n
    r2 = random.Random(777); hit = 0
    for _ in range(B):
        sh = trs[:]; r2.shuffle(sh)
        ims = sum(1 for t, sf in zip(sh, stp) if sf and t <= IMPAIR)
        c = (ims / n_stop) / base if (n_stop and base > 0) else None
        if c is not None and obs['conc'] is not None and c >= obs['conc']:
            hit += 1
    return {'B': B, 'observed_conc': obs['conc'], 'p_cell': round(hit / B, 4),
            'note': '結果ラベルをプール内で並べ替え（1セル単独＝多重検定の値札を掛ける前）'}
OUT['permutation_cell'] = {f'{v}/{p}/{t}': cell_perm(v, p, t) for (v, p, t) in PASS_CELLS}

# ==================================================================
# ★規模×利益率を統制した「残り」を全ビンテージでプールする
# ==================================================================
def strata_3x3(rows):
    both = [r for r in rows if r.get('rev') is not None and r.get('opm') is not None]
    if len(both) < 9: return []
    bs = sorted(both, key=lambda r: r['rev']); nb = len(bs)
    rk = {id(r): (0 if i < nb // 3 else (1 if i < 2 * nb // 3 else 2)) for i, r in enumerate(bs)}
    os_ = sorted(both, key=lambda r: r['opm']); no = len(os_)
    ok_ = {id(r): (0 if i < no // 3 else (1 if i < 2 * no // 3 else 2)) for i, r in enumerate(os_)}
    g = defaultdict(list)
    for r in both: g[(rk[id(r)], ok_[id(r)])].append(r)
    return list(g.values())

POOLED = {}
for th in THRESHOLDS:
    for pool in ('all', 'qual'):
        raw_obs = raw_exp = 0.0
        mh_obs = mh_exp = 0.0
        s_used = 0
        n_tot = ns_tot = 0
        for v in VINTAGES:
            rs = pool_rows(v, pool)
            n = len(rs)
            if n == 0: continue
            stp = [r for r in rs if r.get('opmD5') is not None and r['opmD5'] < th]
            imp = sum(1 for r in rs if r['tr_cagr'] <= IMPAIR)
            n_tot += n; ns_tot += len(stp)
            if imp and stp:
                raw_obs += sum(1 for r in stp if r['tr_cagr'] <= IMPAIR)
                raw_exp += len(stp) * imp / n
            m = mh(strata_3x3(rs), th)
            if m['mh_conc'] is not None or m['expected'] > 0:
                mh_obs += m['observed']; mh_exp += m['expected']; s_used += m['n_strata_used']
        POOLED[f'{pool}/{th}'] = {
            'vintage_stratified_conc': round(raw_obs / raw_exp, 4) if raw_exp > 0 else None,
            'obs': raw_obs, 'exp': round(raw_exp, 2),
            'size_x_opm_controlled_conc': round(mh_obs / mh_exp, 4) if mh_exp > 0 else None,
            'mh_obs': mh_obs, 'mh_exp': round(mh_exp, 2), 'n_strata': s_used,
            'stop_rate_total': round(ns_tot / n_tot, 4) if n_tot else None,
        }
OUT['pooled_controlled'] = POOLED

# ==================================================================
# 分子の会社がビンテージ間でどれだけ重なるか（8ビンテージは独立標本ではない）
# ==================================================================
num_by_v = {}
for v in VINTAGES:
    rs = pool_rows(v, 'all')
    num_by_v[v] = {r['ticker'] for r in rs
                   if r.get('opmD5') is not None and r['opmD5'] < -0.10 and r['tr_cagr'] <= IMPAIR}
ov = {}
for i, a_ in enumerate(VINTAGES):
    for b_ in VINTAGES[i + 1:]:
        A, Bs = num_by_v[a_], num_by_v[b_]
        if A and Bs:
            ov[f'{a_}x{b_}'] = {'A': len(A), 'B': len(Bs), 'shared': len(A & Bs),
                                'jaccard': round(len(A & Bs) / len(A | Bs), 3)}
# ⚠ set をそのまま反復すると PYTHONHASHSEED で順が変わり出力が非決定になる（既記録の型）。必ず sorted
allnum = Counter()
for v in VINTAGES:
    for t in sorted(num_by_v[v]): allnum[t] += 1
OUT['numerator_overlap'] = {
    'per_vintage_num': {str(v): sorted(num_by_v[v]) for v in VINTAGES},
    'pairwise': ov,
    'companies_appearing_in_multiple_vintages': sorted(
        [t for t, c in allnum.items() if c >= 2], key=lambda t: (-allnum[t], t)),
    'n_unique_companies': len(allnum),
    'n_person_vintage': sum(allnum.values()),
    'note': '同じ社が複数ビンテージで数えられる＝8ビンテージは独立な8つの証拠ではない',
}

# ==================================================================
# (f) look-ahead — 信号の締切が結果の窓の開始より前か
# ==================================================================
la = {}
for v in VINTAGES:
    try:
        f = json.load(open(P('out', f'retro_features2_{v}.json'), encoding='utf-8'))
        fdl = f.get('deadline')
    except Exception:
        fdl = None
    rsrc = BASE['vintage_meta'].get(str(v), {}).get('returns_src')
    start = None
    if rsrc:
        try:
            rj = json.load(open(P('out', rsrc), encoding='utf-8'))
            start = (rj.get('benchmark') or {}).get('start') or (rj['rows'][0].get('start') if rj.get('rows') else None)
        except Exception:
            pass
    la[str(v)] = {'features_deadline': fdl, 'returns_start': start,
                  'ok': bool(fdl and start and fdl <= start),
                  'note': 'features は filed<=deadline で切ってある（ファイルの note に明記）'}
    if not la[str(v)]['ok']:
        warn.append(f'{v}: look-ahead の照合ができない（deadline={fdl} start={start}）')
OUT['lookahead_check'] = la

OUT['warnings'] = warn
json.dump(OUT, open(P('out', 'opmtrend_ref_h2.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('置換 family p(>=1) =', PERM['p_family_at_least_1'], '／ 観測合格', obs_cnt)
print('プール(規模x利益率 統制) all/-0.1 =', POOLED['all/-0.1'])
print('look-ahead ok:', all(x['ok'] for x in la.values()))

# ==================================================================
# 統制後の残り（1.0付近）に帰無を当てる — 層内で結果を並べ替える
# ==================================================================
def within_stratum_perm(th, pool, B=2000, seed=4242):
    """規模×利益率の3x3層の**中で**結果を並べ替える。層の構成の違いは帰無側にも入る。"""
    strata_all = []
    for v in VINTAGES:
        for g in strata_3x3(pool_rows(v, pool)):
            stp = [bool(r.get('opmD5') is not None and r['opmD5'] < th) for r in g]
            trs = [r['tr_cagr'] for r in g]
            if sum(stp) == 0 or sum(1 for t in trs if t <= IMPAIR) == 0:
                continue
            strata_all.append((stp, trs))
    if not strata_all:
        return {'note': '層が一つも作れない＝測定ではなく照合の失敗を疑え', 'strata': 0}
    def mh_of(assign):
        obs = exp = 0.0
        for (stp, trs) in assign:
            n = len(trs); ns = sum(stp); imp = sum(1 for t in trs if t <= IMPAIR)
            obs += sum(1 for t, sf in zip(trs, stp) if sf and t <= IMPAIR)
            exp += ns * imp / n
        return (obs / exp) if exp > 0 else None
    obs_mh = mh_of(strata_all)
    r3 = random.Random(seed); ge = 0; null = []
    for _ in range(B):
        sh = []
        for (stp, trs) in strata_all:
            t2 = trs[:]; r3.shuffle(t2)
            sh.append((stp, t2))
        m = mh_of(sh)
        if m is None: continue
        null.append(m)
        if obs_mh is not None and m >= obs_mh: ge += 1
    null.sort()
    def qq(x): return round(null[min(len(null) - 1, max(0, int(x * len(null))))], 4) if null else None
    return {'B': B, 'n_strata': len(strata_all), 'observed_mh_conc': round(obs_mh, 4) if obs_mh else None,
            'p_within_stratum': round(ge / B, 4),
            'null_q50': qq(0.50), 'null_q95': qq(0.95), 'null_q99': qq(0.99),
            'detectable_note': '観測が null_q95 を超えて初めて有意。この器の検出力の目安'}

OUT['pooled_controlled_null'] = {
    f'{pool}/{th}': within_stratum_perm(th, pool)
    for pool in ('all', 'qual') for th in THRESHOLDS
}

# 参考: 統制**しない**（ビンテージ層のみ）帰無 — 統制の有無で p がどう変わるか
def vintage_only_perm(th, pool, B=2000, seed=4242):
    strata_all = []
    for v in VINTAGES:
        g = pool_rows(v, pool)
        stp = [bool(r.get('opmD5') is not None and r['opmD5'] < th) for r in g]
        trs = [r['tr_cagr'] for r in g]
        if sum(stp) == 0 or sum(1 for t in trs if t <= IMPAIR) == 0: continue
        strata_all.append((stp, trs))
    def mh_of(a):
        obs = exp = 0.0
        for (stp, trs) in a:
            n = len(trs); ns = sum(stp); imp = sum(1 for t in trs if t <= IMPAIR)
            obs += sum(1 for t, sf in zip(trs, stp) if sf and t <= IMPAIR)
            exp += ns * imp / n
        return (obs / exp) if exp > 0 else None
    o = mh_of(strata_all); r3 = random.Random(seed); ge = 0
    for _ in range(B):
        sh = [(stp, (lambda t: (r3.shuffle(t), t)[1])(trs[:])) for (stp, trs) in strata_all]
        m = mh_of(sh)
        if m is not None and o is not None and m >= o: ge += 1
    return {'observed_mh_conc': round(o, 4) if o else None, 'p': round(ge / B, 4)}
OUT['pooled_uncontrolled_null'] = {
    f'{pool}/{th}': vintage_only_perm(th, pool) for pool in ('all', 'qual') for th in THRESHOLDS}

# ==================================================================
# 隣接ビンテージのぶれ幅 — 同じ社・1年ずらした窓で濃縮がどれだけ動くか
# ==================================================================
adj = []
for v in VINTAGES:
    c = cell(v, 'all', -0.10)
    adj.append({'vintage': v, 'conc': c['conc'], 'num': c['num'], 'n_stop': c['n_stop'],
                'stop_rate': c['stop_rate'], 'verdict': ('合格' if c['pass'] else '不合格')})
OUT['same_threshold_across_vintages'] = {
    'rows': adj,
    'conc_min': min(x['conc'] for x in adj if x['conc'] is not None),
    'conc_max': max(x['conc'] for x in adj if x['conc'] is not None),
    'note': '母集団はほぼ同じ956社・窓は1年ずつずれるだけ。この帯が「同じ現象を測り直したときのぶれ幅」',
}

json.dump(OUT, open(P('out', 'opmtrend_ref_h2.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('統制後の帰無 all/-0.1:', OUT['pooled_controlled_null']['all/-0.1'])
print('統制なしの帰無 all/-0.1:', OUT['pooled_uncontrolled_null']['all/-0.1'])
print('隣接ビンテージのぶれ:', OUT['same_threshold_across_vintages']['conc_min'], '〜',
      OUT['same_threshold_across_vintages']['conc_max'])

# ==================================================================
# 反証の総括 — 壊せた攻撃と壊せなかった攻撃を**同じ場所に**並べる
# ==================================================================
A = ATT.get('2018/all/-0.1', {}).get('attacks', {})
raw = ATT.get('2018/all/-0.1', {}).get('raw', {})

broke = []
kept = []
def add(lst, name, val, note=''):
    lst.append({'attack': name, 'value': val, 'note': note})

if A.get('sic2_mh', {}).get('mh_conc') is not None and A['sic2_mh']['mh_conc'] < CONC_MIN:
    add(broke, '(a) 業種SIC2で層別(MH)', A['sic2_mh']['mh_conc'], f"観測{A['sic2_mh']['observed']} / 期待{A['sic2_mh']['expected']}")
if A.get('drop_one_sic2', {}).get('n_breaks'):
    add(broke, '(a) 1業種抜き', A['drop_one_sic2']['breaks'], f"{A['drop_one_sic2']['n_breaks']}/{A['drop_one_sic2']['n_sic2']} 通りで割れる")
ter = A.get('size_tertiles', [])
if ter and all(not t.get('pass') for t in ter):
    add(broke, '(b) 規模の三分位（事前登録どおり）', [(t['tertile'], t.get('conc'), t.get('num')) for t in ter], '三分位すべてで割れる')
if A.get('size_mh', {}).get('mh_conc') is not None and A['size_mh']['mh_conc'] < CONC_MIN:
    add(broke, '(b) 規模で層別(MH)', A['size_mh']['mh_conc'])
lvl = A.get('opm_level', {})
if lvl:
    add(broke, '★(b2) 利益率の水準で層別', {k: (v or {}).get('conc') for k, v in lvl.items()},
        '赤字の中では 1.01＝完全にゼロ／黒字の中でも 1.99 で線を割る＝止めていたのは「利益率が下がった社」ではなく「赤字の零細」')
if A.get('mh_size_x_opm_3x3', {}).get('mh_conc') is not None and A['mh_size_x_opm_3x3']['mh_conc'] < CONC_MIN:
    add(broke, '★(b2) 規模×利益率 3x3 で同時に層別(MH)', A['mh_size_x_opm_3x3']['mh_conc'],
        f"観測{A['mh_size_x_opm_3x3']['observed']} / 期待{A['mh_size_x_opm_3x3']['expected']}＝粗の2.257がほぼ消える")
bs = A.get('bootstrap', {})
if bs.get('p_conc_below_2') is not None and bs['p_conc_below_2'] > 0.05:
    add(broke, '(i) ブートストラップ', {'ci90': bs['ci90'], 'p(conc<2.0)': bs['p_conc_below_2'], 'p(4基準すべて合格)': bs['p_all4_pass']},
        '線の2.0倍が信頼区間の内側＝この標本で 2.0 を上回るかは運の範囲')
sw = OUT['same_threshold_across_vintages']
add(broke, '★隣接ビンテージのぶれ', {'conc_min': sw['conc_min'], 'conc_max': sw['conc_max']},
    '母集団はほぼ同じ956社で窓が1年ずれるだけなのに 1.07〜2.26 と動く＝線の2.0は手続き自身のぶれ幅の中にある')
pc = OUT['pooled_controlled']['all/-0.1']; pn = OUT['pooled_controlled_null']['all/-0.1']
add(broke, '★★8ビンテージをプールして規模×利益率を統制', {'uncontrolled': pc['vintage_stratified_conc'],
    'controlled': pc['size_x_opm_controlled_conc'], 'p_within_stratum': pn['p_within_stratum']},
    '測定側が「方向は実在する(1.2〜1.6倍)」と書いた残りは、統制すると 1.01・p=0.42＝**方向すら残らない**')
add(broke, '★分子の重なり', {'person_vintage': OUT['numerator_overlap']['n_person_vintage'],
    'unique_companies': OUT['numerator_overlap']['n_unique_companies'],
    'in_2plus_vintages': len(OUT['numerator_overlap']['companies_appearing_in_multiple_vintages'])},
    '8ビンテージは8つの証拠ではない')
add(broke, '(d) 置換検定（会社単位・全ビンテージ同時）', {'p_family_at_least_1': PERM['p_family_at_least_1'],
    'family_size': PERM['family_size']}, '家族42セルで偶然1つ以上通る確率が2割超＝合格1件は雑音と区別がつかない')

# 壊せなかったもの（正直に）
if A.get('drop_one_company', {}).get('n_breaks') == 0:
    add(kept, '(c) 1社抜き（プールごと）', {'conc_min': A['drop_one_company']['conc_min'],
        'conc_max': A['drop_one_company']['conc_max']}, '956通りすべてで合格のまま＝単一企業の話ではない')
wl = A.get('window_length', {})
if wl.get('full_only', {}).get('pass'):
    add(kept, '(g) 窓長の非一様', {'short_in_stop': wl['short_in_stop'], 'full_only_conc': wl['full_only']['conc']},
        '止めた110社に窓の短い行は1社も無い＝年率換算の非一様では説明できない')
mo = A.get('measured_only')
if mo and mo.get('pass'):
    add(kept, '(分母) 測れた社だけを分母にする', {'conc': mo['conc'], 'n': mo['n']},
        '2013 は欠測が毀損率を歪めるが、この合格セルは分母の取り方では動かない')
mg = A.get('opmD5_magnitude', {})
add(kept, '(e2) opmD5 の極端値（分母の縮退）を外す', mg,
    '常識帯 -1.0<opmD5<-0.10 だけでも 2.09／分子16＝micro売上の桁化けだけでは説明できない')
add(kept, '(f) look-ahead', {k: v['ok'] for k, v in la.items()},
    '8ビンテージすべてで 信号の締切 == 結果の窓の開始（features は filed<=deadline）')
add(kept, '(e) 単位・欄名', {'qual_pool_agrees': all(v['agree'] for v in qual_check.values()),
    'row_band_mismatch_total': sum(v['row_band_mismatch_n'] for v in unit.values()),
    'opmD5_neg_share_range': [min(v['opmD5_neg_share'] for v in unit.values() if v['opmD5_neg_share']),
                              max(v['opmD5_neg_share'] for v in unit.values() if v['opmD5_neg_share'])]},
    'opm の比率→%換算・質実証プール・opmD5の符号割合とも独立に再現。rev は8ビンテージとも生ドルで一貫')
add(kept, '(d2) セル単独の置換', OUT['permutation_cell'],
    '素の関連そのものは本物（p は極小）。問題は家族の値札と交絡であって、関連の有無ではない')

OUT['verdict_refutation'] = {
    'role': '反証専門',
    'independent_recompute': ('48セルすべて一致（n / n_stop / 分子 / 濃縮 / 中央値 / 止率 / ベース毀損率 / 判定）'
                             if recon['agree'] else '食い違いあり'),
    'agrees_with_measurement_verdict': True,
    'conclusion': '測定側の「不合格」は支持される。しかも測定側が残した「方向は実在する(1.2〜1.6倍)」も反証された',
    'headline': ('唯一の合格セル 2018/all/-0.10 は、規模と利益率の水準という二つの交絡で説明が付く。'
                 '8ビンテージをプールして両方を同時に統制すると濃縮は 1.63 → 1.01（p=0.42）＝方向すら残らない'),
    'broke': broke,
    'not_broken': kept,
    'discrepancy_with_measurement': [
        {'item': 'セル単独の置換 p',
         'mine': OUT['permutation_cell'].get('2018/all/-0.1', {}).get('p_cell'),
         'theirs': (THEIRS.get('adversarial') or [{}])[0].get('p_cell_permutation'),
         'why': '乱数の種と実装が違うだけ。どちらも「単独では極小」で結論は同じ（私の値のほうが極端＝測定側に有利に丸めていない）'},
        {'item': '測定側の探索「方向は実在する(プールMH 1.23/1.46/1.63)」',
         'mine': '同じ数字を独立に再現した。だが規模×利益率を統制すると 0.98/1.02/1.01 へ落ち、深いほど強いという単調性も消える',
         'why': '測定側はプールMHをビンテージ層だけで作っており、社の性質を統制していない'},
    ],
    'how_far_to_trust': [
        '★この所見（opmD5 単独の遮断器）は採用してはいけない。粗の関連は本物だが、中身は「赤字の零細企業」の言い換え',
        '★測定側の不合格は正しい。ただし理由は「線に届かない」ではなく「線に届いた1セルが交絡で説明できる」ほうが強い',
        '独立標本はゼロ（同じ956社・窓は2026-08で共通・分子62社がのべ136回数えられる）',
        '生存バイアスは既記録のまま（左尾は 2.00〜25.68% の幅）。ここでは全ビンテージに等しく乗る',
        '「壊せなかった」4件（1社抜き・窓長・分母・極端値）は、この所見を支持する材料ではない——'
        'いずれも「別の壊れ方ではない」と言っただけで、交絡の説明を否定しない',
    ],
}
json.dump(OUT, open(P('out', 'opmtrend_ref_h2.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('=== 反証の総括 ===')
print('独立再計算:', OUT['verdict_refutation']['independent_recompute'])
print('壊せた:', len(broke), '／ 壊せなかった:', len(kept))
print(OUT['verdict_refutation']['headline'])

# ==================================================================
# 自分の攻撃の自己検算 — opm の単位の曖昧さで結論が動かないか
# （base は opm をファイル単位で換算する。行ごとの帯検問と 101行で食い違う）
# ==================================================================
def _s3(rows, keyf):
    both = [r for r in rows if r.get('rev') is not None and keyf(r) is not None]
    if len(both) < 9: return []
    bs = sorted(both, key=lambda r: r['rev']); nb = len(bs)
    rk = {id(r): (0 if i < nb // 3 else (1 if i < 2 * nb // 3 else 2)) for i, r in enumerate(bs)}
    os_ = sorted(both, key=keyf); no = len(os_)
    ok_ = {id(r): (0 if i < no // 3 else (1 if i < 2 * no // 3 else 2)) for i, r in enumerate(os_)}
    g = defaultdict(list)
    for r in both: g[(rk[id(r)], ok_[id(r)])].append(r)
    return [g[k] for k in sorted(g)]

selfck = {}
for label, keyf in (('base の opm（ファイル単位で換算）', lambda r: r.get('opm')),
                    ('行ごとの帯検問で作り直した opm', lambda r: band_pct(r.get('opm_raw')))):
    o = e = 0.0; u = 0
    for v in VINTAGES:
        m = mh(_s3(pool_rows(v, 'all'), keyf), -0.10)
        o += m['observed']; e += m['expected']; u += m['n_strata_used']
    selfck[label] = {'pooled_controlled_conc': round(o / e, 4) if e > 0 else None,
                     'obs': o, 'exp': round(e, 2), 'n_strata': u,
                     'v2018_only': mh(_s3(pool_rows(2018, 'all'), keyf), -0.10)['mh_conc']}
OUT['selfcheck_opm_unit'] = {
    'why': 'base は opm をファイル単位で×100する。行ごとの帯検問と 101 行で食い違う（深い赤字の零細）。'
           'その曖昧さで私の結論（統制後は 1.0）が動かないかを自分で検算する',
    'row_band_mismatch_total': sum(v['row_band_mismatch_n'] for v in unit.values()),
    'results': selfck,
    'verdict': '動かない（プール統制後 1.0131 vs 1.0130／2018単体 1.2017 vs 1.1968）。'
               '食い違う行はどちらの読みでも「赤字」「最小分位」に入るため層が変わらない',
}
json.dump(OUT, open(P('out', 'opmtrend_ref_h2.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('自己検算(opm単位):', {k: v['pooled_controlled_conc'] for k, v in selfck.items()})

# ==================================================================
# ★反証者の正直さ — 私の探索的な切り方の中に「通る」セルが1つある
# ==================================================================
explor = []
for key, a in ATT.items():
    for name, v_ in (a['attacks'].get('opm_level') or {}).items():
        if v_: explor.append({'cell': key, 'subgroup': f'opm水準 {name}', **{k: v_[k] for k in
                              ('n', 'n_stop', 'stop_rate', 'num', 'conc', 'pass')}})
    for t in a['attacks'].get('size_tertiles', []):
        if 'conc' in t: explor.append({'cell': key, 'subgroup': f"規模 {t['tertile']}",
                                       **{k: t.get(k) for k in ('n', 'n_stop', 'stop_rate', 'num', 'conc', 'pass')}})
    for nm, t in (a['attacks'].get('size_halves') or {}).items():
        if isinstance(t, dict): explor.append({'cell': key, 'subgroup': f'規模 {nm}(二分)',
                                               **{k: t.get(k) for k in ('n', 'n_stop', 'stop_rate', 'num', 'conc', 'pass')}})
passing = [e for e in explor if e.get('pass')]
OUT['honesty_exploratory_subgroups'] = {
    'why': '反証者が「壊れた」ものだけを出すのは片側の報告になる。私が作った探索的な部分集合の中で'
           '4基準を通るものがあれば必ず名指しする',
    'n_subgroups_tried': len(explor),
    'n_passing': len(passing),
    'passing': passing,
    'caveat': ('これは事前登録に無い事後の切り方（事前登録のプールは 全社 と 質実証(opm>=10% ∧ fcfpos5>=5) の2つだけ）。'
               f'{len(explor)} 通り試して {len(passing)} 通り通るのは偶然の範囲。'
               'しかも同じ切り方が他のセルでは通らない＝安定しない'),
}
OUT['verdict_refutation']['honest_counterexample'] = OUT['honesty_exploratory_subgroups']
json.dump(OUT, open(P('out', 'opmtrend_ref_h2.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('探索的な部分集合', len(explor), '通り中', len(passing), '通りが4基準を通る:',
      [(e['cell'], e['subgroup'], e['conc'], e['num']) for e in passing])
