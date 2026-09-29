#!/usr/bin/env python3
"""night/nx_osap_intang.py — 角度 nx_osap_intang（OSAP の無形資産・革新・利益の質）を事前登録どおりに測る（読むだけ・門の判定には不使用）

問い: Chen & Zimmermann の Open Source Asset Pricing（CRSP/Compustat・上場廃止込み）のうち、JKP 153 に無い
      『無形資産・革新・利益の質』の予言変数（組織資本・広告費・ブランド投資・研究開発の腕・研究開発の増加・業界の集中度・
      成長株の中の G スコア・年金の積立状況）の、論文の向きの良い側の組だけを時価加重で買って持つと、French Mkt
      （上限なしの時価加重・S&P500 に近い）に、訓練期間（〜2006-12）でも保有期間（2007-01〜2024-12）でも費用後に勝つか。
事前登録: out/nx_osap_intang_prereg.json（commit 330f348c・測る前）。線は out/nx_prereg.json（C1〜C8・S/A/B/C）。
データ: night/nx_osap_intang_data.py の出力 out/_nx_cache/nx_osap_intang_ports.json（extract_sha256・rules_sha256 を最初に確かめる）。
        R5 の基礎率だけは OSAP の原本 osap_PredictorAltPorts_QuintilesVW.zip（179本）を直接読む（sha256 を事前登録の値と照合）。
出力: out/nx_osap_intang.json（tested に格付けした 27 本すべて＝負けも残す・報告 R1〜R8・事後の診断は post_hoc）

約束（事前登録どおり）
- s = 良い側の組の月次の総リターン（OSAP の % を /100）、b = French Mkt（Mkt-RF + RF・総リターン）。比べるのは 2024-12 まで
- 評価は良い側の銘柄数 Nlong が初めて20以上になった月から。その後に20未満の月は落とす（0で埋めない）
- s_net = s − 回転×0.30%/12（毎月）。合成は 使った脚の回転の平均＋0.10
- C1・C2・C3・C7 は費用前、C4（転がる20年窓）と C6 は費用後。C5・C8 は N/A
- Holm は族ごと（P 8本・X1 5本・X2 5本・X3 4本・X4 5本・両側・保有期間・費用前）
- 結果を見た後の分析は post_hoc に置き『事後』と明記し、格付けには使わない
"""
import sys, os, json, math, statistics as _stat, hashlib, subprocess, datetime, csv, io, zipfile, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N  # noqa: E402
import nx_osap_intang_data as D  # noqa: E402


class _StatShim:
    """速さだけの細工（数値は1ビットも変えない）: nx_common.excess_stats は β の和の中で S.mean(sv)・S.mean(bv) を
    要素ごとに計算し直す（分数の厳密計算 × O(n²)）。同じ list オブジェクトへの mean の答えを覚えて返す。
    list を強参照で持つので id の再利用は起きず、答えは statistics.mean そのもの。nx_common.py 自体は書き換えない"""

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
S = _stat

BASE = N.BASE
PREREG_PATH = os.path.join(BASE, 'out', 'nx_osap_intang_prereg.json')
PR = json.load(open(PREREG_PATH))
OUTNAME = 'nx_osap_intang.json'
PORTS_PATH = os.path.join(N.CACHE, 'nx_osap_intang_ports.json')
TE, HS, RS = N.TRAIN_END, N.HOLD_START, N.RECENT_START
LAST = 202412          # OSAP の最後の月（French はこれより後もあるが比べない）
NMIN = D.NMIN          # 20
UNIT = D.COST_PER_UNIT  # 0.003
FAMS = ['P', 'X1', 'X2', 'X3', 'X4']


# ───────────────────────── 小道具 ─────────────────────────
def git_sha(path):
    try:
        return subprocess.run(['git', 'log', '-1', '--format=%H', '--', path], cwd=BASE, capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa
        return None


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for ch in iter(lambda: f.read(1 << 20), b''):
            h.update(ch)
    return h.hexdigest()


def ym_add(ym, k):
    y, m = divmod(ym, 100)
    t = y * 12 + (m - 1) + k
    return (t // 12) * 100 + t % 12 + 1


def r2(x, n=2):
    return None if x is None else round(x, n)


# ───────────────────────── データ ─────────────────────────
X = json.load(open(PORTS_PATH))
SIG = X['signals']
FF = N.ff_factors()
MKT_ALL, RF_ALL, MKTRF_ALL = FF['mkt'], FF['rf'], FF['mktrf']
MKT = N.window(MKT_ALL, z=LAST)
RF = N.window(RF_ALL, z=LAST)
RULES = {r['id']: r for r in D.RULES}


def pre_sha(key):
    return PR['tools'][key][:64]


def check_sha():
    blob = json.dumps(SIG, sort_keys=True, separators=(',', ':')).encode()
    ext = hashlib.sha256(blob).hexdigest()
    rs = D.rules_sha()
    ok = {'extract_sha256_file': X['extract_sha256'], 'extract_sha256_recomputed': ext, 'extract_sha256_prereg': pre_sha('extract_sha256'),
          'rules_sha256_file': X['rules_sha256'], 'rules_sha256_recomputed': rs, 'rules_sha256_prereg': pre_sha('rules_sha256')}
    good = (X['extract_sha256'] == ext == pre_sha('extract_sha256')) and (X['rules_sha256'] == rs == pre_sha('rules_sha256'))
    ok['ok'] = good
    if not good:
        print(json.dumps(ok, indent=1))
        raise SystemExit('sha が事前登録と一致しない。止まる')
    return ok


def rows_of(sig, file, port):
    return SIG.get(sig, {}).get(file, {}).get(port)


def filt(rows):
    """評価の開始（Nlong≥20 の最初の月）以降で Nlong≥20 の月だけ → ({ym: r}, 開始月, 開始後に落ちた月数)"""
    if not rows:
        return {}, None, None
    st = D.eval_start(rows)
    if st is None:
        return {}, None, None
    s, drop = {}, 0
    for m, r, n in rows:
        if m < st or m > LAST:
            continue
        if n is None or n < NMIN:
            drop += 1
            continue
        s[m] = r
    return s, st, drop


def nlong_median(rows, a=None, z=None):
    v = [n for m, r, n in rows if n is not None and (a is None or m >= a) and (z is None or m <= z)]
    return S.median(v) if v else None


# ───────────────────────── 系列を作る ─────────────────────────
SER = {}   # id → {'s': gross, 'cost': {ym: 月の費用（小数）}, 'turn_ann': 年の回転, 'start':…, 'drop':…, 'nlong_med': …}


def build_single(r):
    rows = rows_of(r['signal'], r['file'], r['port'])
    s, st, drop = filt(rows)
    c = r['turn'] * UNIT / 12
    return {'s': s, 'cost_m': {m: c for m in s}, 'turn_m': {m: r['turn'] for m in s}, 'turn_ann': r['turn'], 'start': st, 'drop': drop,
            'nlong_med_all': nlong_median(rows) if rows else None, 'nlong_med_hold': nlong_median(rows, a=HS) if rows else None,
            'months': len(s)}


def build_composite(r):
    legs = [SER[p] for p in r['parts']]
    turns = [RULES[p]['turn'] for p in r['parts']]
    months = sorted(set().union(*[set(l['s']) for l in legs]))
    s, cost_m, turn_m, nlegs, wsum = {}, {}, {}, {}, {}
    for m in months:
        use = [(l['s'][m], t) for l, t in zip(legs, turns) if m in l['s']]
        if len(use) < r['min_legs']:
            continue
        w = 1.0 / len(use)
        s[m] = math.fsum(w * x for x, _ in use)
        tt = S.mean([t for _, t in use]) + r['turn_add']
        turn_m[m] = tt
        cost_m[m] = tt * UNIT / 12
        nlegs[m] = len(use)
        wsum[m] = w * len(use)
    return {'s': s, 'cost_m': cost_m, 'turn_m': turn_m, 'turn_ann': round(S.mean(turn_m.values()), 4) if turn_m else None,
            'start': min(s) if s else None, 'drop': None, 'nlegs': nlegs, 'wsum': wsum, 'months': len(s),
            'legs_hist': {k: sum(1 for v in nlegs.values() if v == k) for k in sorted(set(nlegs.values()))}}


def net_of(ser, unit=UNIT, turn_mult=1.0):
    return {m: v - ser['turn_m'][m] * turn_mult * unit / 12 for m, v in ser['s'].items()}


# ───────────── 勝ちの数は丸める前の値で数える（検査役の指摘の是正・2026-09-28） ─────────────
# nx_common.rolling は窓ごとの年率差を %・小数2桁に丸めてから『>0 なら勝ち』を数え、nx_common.dca は倍率を小数3桁に
# 丸めてから『>1 なら勝ち』を数える。このため +0.0032%/年 の窓（P4 の 1994-07〜2014-06）が勝ちに入らなかった。
# C4 は「市場に勝った割合」＝差が正の窓の割合なので、数えるのは丸める前の差。丸めは表示（median/worst/best）だけに残す。
# nx_common.py は全角度の共通部品なのでここでは書き換えない（直すなら全角度で同時に＝まとめ役）。
# 窓の切り方は nx_common と同じ式をここに写し、丸めた値が nx_common の戻り値と1窓残らず一致することを毎回確かめる（ずれたら止まる）。
def _roll_exact_diffs(s, b, years, start_month):
    ks = sorted(set(s) & set(b))
    out = []
    y0, last = ks[0] // 100, ks[-1]
    for y in range(y0, 2100):
        a, z = y * 100 + start_month, (y + years) * 100 + start_month - 1 if start_month > 1 else (y + years - 1) * 100 + 12
        if z > last:
            break
        w = [k for k in ks if a <= k <= z]
        if len(w) < years * 12 * 0.97:
            continue
        gs = math.exp(math.fsum(math.log1p(s[k]) for k in w) / years) - 1
        gb = math.exp(math.fsum(math.log1p(b[k]) for k in w) / years) - 1
        out.append((y, gs - gb))
    return out


def rolling_x(s, b, years=20, start_month=7):
    """nx_common.rolling と同じ戻り値。ただし wins / win_rate は丸める前の差 > 0 で数える"""
    ro = N.rolling(s, b, years, start_month)
    if not ro:
        return ro
    d = _roll_exact_diffs(s, b, years, start_month)
    rounded = sorted(round(c * 100, 2) for _, c in d)
    if len(d) != ro['windows'] or rounded[len(rounded) // 2] != ro['median'] or sum(1 for c in rounded if c > 0) != ro['wins']:
        raise SystemExit('rolling_x: 窓の切り方が nx_common.rolling と一致しない')
    we = sum(1 for _, c in d if c > 0)
    if we != ro['wins']:
        ro['wins_nx_common_rounded'] = ro['wins']
        ro['win_rate_nx_common_rounded'] = ro['win_rate']
        ro['wins_changed_by_rounding'] = [[y, c * 100] for y, c in d if c > 0 and round(c * 100, 2) <= 0]
    ro['wins'] = we
    ro['win_rate'] = round(we / len(d), 3)
    return ro


def dca_x(s, b, years=20, step=12):
    """nx_common.dca と同じ戻り値。ただし win_rate は丸める前の倍率 > 1 で数える"""
    ro = N.dca(s, b, years, step)
    if not ro:
        return ro
    ks = sorted(set(s) & set(b))
    n = years * 12
    raw = []
    for i in range(0, len(ks) - n + 1, step):
        ws = wb = 0.0
        for k in ks[i:i + n]:
            ws = (ws + 1) * (1 + s[k]); wb = (wb + 1) * (1 + b[k])
        raw.append((ks[i], ws / wb))
    if len(raw) != ro['windows'] or round(sum(1 for _, r in raw if round(r, 3) > 1) / len(raw), 3) != ro['win_rate']:
        raise SystemExit('dca_x: 窓の切り方が nx_common.dca と一致しない')
    wr = round(sum(1 for _, r in raw if r > 1) / len(raw), 3)
    if wr != ro['win_rate']:
        ro['win_rate_nx_common_rounded'] = ro['win_rate']
        ro['wins_changed_by_rounding'] = [[k, r] for k, r in raw if r > 1 and round(r, 3) <= 1]
    ro['win_rate'] = wr
    return ro


def _ro_brief(ro, keys):
    """報告用に rolling_x の一部だけを残す。丸めで勝ちの数が変わった窓があれば、その記録も残す"""
    if not ro:
        return None
    return {k: ro[k] for k in keys + ('wins_nx_common_rounded', 'win_rate_nx_common_rounded', 'wins_changed_by_rounding') if k in ro}


# ───────────────────────── 測る ─────────────────────────
def maxdd_same(s, b, a=None, z=None):
    ks = sorted(k for k in set(s) & set(b) if (a is None or k >= a) and (z is None or k <= z))
    if not ks:
        return None
    return {'s': r2(N.maxdd({k: s[k] for k in ks}) * 100, 1), 'b': r2(N.maxdd({k: b[k] for k in ks}) * 100, 1)}


def sharpe_block(s, sn, b, a=None, z=None):
    return {'s_gross': N.sharpe(s, RF, a, z), 's_net': N.sharpe(sn, RF, a, z), 'mkt': N.sharpe({k: b[k] for k in s if k in b}, RF, a, z)}


def periods(r, st):
    """期間の切り方（R3 を含む）"""
    P = {'full': (None, LAST), 'train': (None, TE), 'hold': (HS, LAST), 'recent': (RS, LAST)}
    pub, op = r.get('pub'), r.get('op')
    if pub:
        P['post_pub'] = ((pub + 1) * 100 + 1, LAST)
    if op:
        P['op_sample'] = (op[0] * 100 + 1, op[1] * 100 + 12)
        if st is not None and st <= (op[0] - 1) * 100 + 12:
            P['before_op'] = (None, (op[0] - 1) * 100 + 12)
        if pub and op[1] < pub:
            P['after_op_to_pub'] = ((op[1] + 1) * 100 + 1, pub * 100 + 12)
    return P


def evaluate(rid, ser, r):
    s, sn = ser['s'], net_of(ser)
    b = MKT
    P = periods(r, ser['start'])
    gross = {k: N.excess_stats(s, b, a, z) for k, (a, z) in P.items()}
    net = {k: N.excess_stats(sn, b, a, z) for k, (a, z) in P.items()}
    out = {
        'gross': gross, 'net': net,
        'roll20_net': rolling_x(sn, b, 20, 7), 'roll20_gross': rolling_x(s, b, 20, 7),
        'dca20_net': dca_x(sn, b, 20, 12), 'dca20_gross': dca_x(s, b, 20, 12),
        'maxdd': {'full': maxdd_same(s, b), 'hold': maxdd_same(s, b, HS), 'full_net': maxdd_same(sn, b)},
        'sharpe': {'train': sharpe_block(s, sn, b, None, TE), 'hold': sharpe_block(s, sn, b, HS, LAST), 'full': sharpe_block(s, sn, b)},
        'periods_used': {k: [a, z] for k, (a, z) in P.items()},
    }
    return out


def grade_one(x, holm_p):
    g, c = N.grade(full=x['gross']['full'], train=x['gross']['train'], hold=x['gross']['hold'], roll20=x['roll20_net'],
                   cost_hold=x['net']['hold'], repl=None, family_holm_p=holm_p, leveraged_or_timing=False)
    return g, c


# ───────────────────────── 報告 ─────────────────────────
def other_side(r, ser):
    """R4: 悪い側（最小の組）・中の組・LS。悪い側と中は対 French Mkt、LS は自身の平均と NW t（良い側−悪い側）"""
    if 'signal' not in r:
        return None
    ports = SIG[r['signal']][r['file']]
    if r['file'] == 'FF93style':
        bad, mids = ('BL' if r['port'] == 'BH' else 'SL'), (['BM'] if r['port'] == 'BH' else ['SM'])
    else:
        num = sorted(p for p in ports if p != 'LS')
        bad = num[0]
        if r['file'] == 'DecilesVW':
            mids = ['05', '06']
        elif '03' in num and num[-1] != '03':
            mids = ['03']
        else:
            mids = []
    res = {'bad_port': bad, 'mid_ports': mids}
    sb, stb, _ = filt(ports.get(bad))
    res['bad_vs_mkt'] = {k: N.excess_stats(sb, MKT, a, z) for k, (a, z) in (('full', (None, LAST)), ('train', (None, TE)), ('hold', (HS, LAST)))}
    res['bad_eval_start'] = stb
    res['mid_vs_mkt'] = {}
    for mp in mids:
        sm, _, _ = filt(ports.get(mp))
        res['mid_vs_mkt'][mp] = {k: N.excess_stats(sm, MKT, a, z) for k, (a, z) in (('full', (None, LAST)), ('train', (None, TE)), ('hold', (HS, LAST)))}
    # 良い側 − 悪い側（同じ月・両方の Nlong≥20）と OSAP の LS（原本の列）
    ls_raw = {m: v for m, v, n in ports.get('LS', []) if m <= LAST}
    zero = {m: 0.0 for m in ls_raw}
    res['LS_osap_mean_vs_zero'] = {k: N.excess_stats({m: ls_raw[m] for m in ls_raw if m in ser['s']}, zero, a, z)
                                   for k, (a, z) in (('full', (None, LAST)), ('train', (None, TE)), ('hold', (HS, LAST)))}
    res['note'] = 'LS は良い側の評価月（Nlong≥20）に限った OSAP の LS 列の平均（対 0）。excess_stats の cagr_s は LS の複利で意味が薄い（ex_ann と t を読む）'
    return res


def cost_sensitivity(ser, r_is_comp=False):
    out = {}
    for name, unit, tm in (('unit0.10', 0.001, 1.0), ('unit0.60', 0.006, 1.0), ('turn_x0.5', UNIT, 0.5), ('turn_x2', UNIT, 2.0)):
        sn = net_of(ser, unit, tm)
        h = N.excess_stats(sn, MKT, HS, LAST)
        ro = rolling_x(sn, MKT, 20, 7)
        out[name] = {'hold_net': {'ex_ann': h['ex_ann'], 'cagr_diff': h['cagr_diff'], 't': h['t']} if h else None,
                     'C6_net_cost': bool(h and h['ex_ann'] > 0 and h['cagr_diff'] > 0),
                     'roll20_net': _ro_brief(ro, ('wins', 'windows', 'win_rate', 'median')),
                     'C4_roll20': bool(ro and ro['win_rate'] >= 0.8)}
    return out


def size_halves():
    """R2: French の ME 十分位を時価（Number of Firms × Average Firm Size・同じ行＝月初の時価）で合わせた大型の半分（6〜10）・小型の半分（1〜5）"""
    T = N.french_tables('Portfolios_Formed_on_ME')
    vw, nf, sz = T['Average Value Weight Returns -- Monthly'], T['Number of Firms in Portfolios'], T['Average Firm Size']
    cols = vw['cols']
    dec = ['Lo 10', '2-Dec', '3-Dec', '4-Dec', '5-Dec', '6-Dec', '7-Dec', '8-Dec', '9-Dec', 'Hi 10']
    idx = [cols.index(c) for c in dec]
    half = {'small': idx[:5], 'big': idx[5:]}
    out = {'small': {}, 'big': {}}
    for m in sorted(vw['data']):
        if m > LAST:
            continue
        for h, ii in half.items():
            w = [nf['data'][m][j] * sz['data'][m][j] if nf['data'][m][j] is not None and sz['data'][m][j] is not None else None for j in ii]
            rr = [vw['data'][m][j] for j in ii]
            if None in w or None in rr or sum(w) <= 0:
                continue
            out[h][m] = math.fsum(a * x / 100 for a, x in zip(w, rr)) / math.fsum(w)
    # 確かめ: 10十分位の合計（同じ重み）が French Mkt に近いこと
    allm = {}
    for m in sorted(vw['data']):
        if m > LAST:
            continue
        w = [nf['data'][m][j] * sz['data'][m][j] for j in idx]
        allm[m] = math.fsum(a * vw['data'][m][j] / 100 for a, j in zip(w, idx)) / math.fsum(w)
    d = [abs(allm[m] - MKT[m]) for m in allm if m in MKT and m >= 196307]
    chk = {'deciles_all_vs_Mkt_mean_abs_diff_pct_since_1963_07': round(S.mean(d) * 100, 4), 'max_pct': round(max(d) * 100, 3),
           'weight_timing': '同じ行の Number of Firms × Average Firm Size（月初の時価）。前月の行を使うより Mkt に近い（平均の差 0.047% 対 0.051%・事前に確かめた）'}
    return out, chk


def r2_report(halves):
    res = {}
    for sig in ['OrgCap', 'AdExp', 'BrandInvest', 'RDAbility', 'Herf', 'FR']:
        res[sig] = {}
        for port, h in (('BH', 'big'), ('SH', 'small')):
            if sig == 'RDAbility' and port == 'BH':
                res[sig][port] = '外した（事前登録: BH の銘柄数の中央値22社）'
                continue
            rows = rows_of(sig, 'FF93style', port)
            s, st, drop = filt(rows)
            e = {k: N.excess_stats(s, halves[h], a, z) for k, (a, z) in (('full', (None, LAST)), ('train', (None, TE)), ('hold', (HS, LAST)))}
            res[sig][port] = {'eval_start': st, 'dropped': drop, 'vs': f'French の ME 十分位の{"6〜10（大型の半分）" if h == "big" else "1〜5（小型の半分）"}',
                              'excess': e, 'positive_full': bool(e['full'] and e['full']['ex_ann'] > 0 and e['full']['cagr_diff'] > 0),
                              'positive_hold': bool(e['hold'] and e['hold']['ex_ann'] > 0 and e['hold']['cagr_diff'] > 0)}
    both_full = [s for s, v in res.items() if isinstance(v.get('BH'), dict) and v['BH']['positive_full'] and v['SH']['positive_full']]
    both_hold = [s for s, v in res.items() if isinstance(v.get('BH'), dict) and v['BH']['positive_hold'] and v['SH']['positive_hold']]
    res['_count'] = {'variables_with_both_halves': 5, 'both_positive_full': both_full, 'both_positive_hold': both_hold,
                     'SH_positive_full': [s for s in res if not s.startswith('_') and res[s]['SH']['positive_full']],
                     'SH_positive_hold': [s for s in res if not s.startswith('_') and res[s]['SH']['positive_hold']],
                     'BH_positive_full': [s for s in res if not s.startswith('_') and isinstance(res[s]['BH'], dict) and res[s]['BH']['positive_full']],
                     'BH_positive_hold': [s for s in res if not s.startswith('_') and isinstance(res[s]['BH'], dict) and res[s]['BH']['positive_hold']],
                     'positive_definition': '算術平均の超過と幾何の年率差がともに正（費用前・同じ大きさの半分の市場に対して）'}
    return res


# ── R5 基礎率 ──
def jkp_details():
    """JKP の特徴の出典（Factor Details.xlsx・bkelly-lab/ReplicationCrisis）→ [(第1著者の姓 小文字, 年)]。印を付けるだけ（格付けに関係しない）"""
    try:
        import openpyxl
        b = N.get('https://raw.githubusercontent.com/bkelly-lab/ReplicationCrisis/master/GlobalFactors/Factor%20Details.xlsx',
                  name='jkp_factor_details.xlsx', max_age_days=3650)
        wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True)
        rows = list(wb.worksheets[0].iter_rows(values_only=True))
        h = rows[0]
        out = []
        for rr in rows[1:]:
            d = dict(zip(h, rr))
            if not d.get('abr_jkp'):
                continue
            cite = str(d.get('cite') or '')
            m = re.search(r'\((\d{4})\)', cite) or re.search(r'(\d{4})', cite)
            first = re.split(r'[ ,]', cite.strip())[0].lower()
            out.append({'abr': d['abr_jkp'], 'first': first, 'year': int(m.group(1)) if m else None, 'cite': cite})
        return out, None
    except Exception as e:  # noqa
        return [], f'取得失敗 {e}'


def base_rate():
    zp = os.path.join(N.CACHE, 'osap_PredictorAltPorts_QuintilesVW.zip')
    sha = sha256_file(zp)
    want = PR['data']['files']['QuintilesVW']['sha256']
    if sha != want:
        raise SystemExit(f'QuintilesVW の sha が事前登録と違う {sha} != {want}')
    z = zipfile.ZipFile(zp)
    rows = {}
    for r in csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding='utf-8-sig')):
        if r['port'] != '05' or r['ret'] in ('', 'NA', 'NaN'):
            continue
        n = int(float(r['Nlong'])) if r['Nlong'] not in ('', 'NA') else None
        rows.setdefault(r['signalname'], []).append([D.ym(r['date']), float(r['ret']) / 100.0, n])
    doc = {x['Acronym']: x for x in csv.DictReader(open(os.path.join(N.CACHE, 'osap_SignalDoc.csv'), encoding='utf-8-sig'))}
    jk, jerr = jkp_details()
    res, pv = {}, {}
    for sig in sorted(rows):
        rw = sorted(rows[sig])
        s, st, drop = filt(rw)
        ser = {'s': s, 'turn_m': {m: 0.8 for m in s}}
        sn = net_of(ser)
        full = N.excess_stats(s, MKT, None, LAST)
        tr = N.excess_stats(s, MKT, None, TE)
        ho = N.excess_stats(s, MKT, HS, LAST)
        hn = N.excess_stats(sn, MKT, HS, LAST)
        ro = rolling_x(sn, MKT, 20, 7)
        dd = doc.get(sig, {})
        first = re.split(r'[ ,]', (dd.get('Authors') or '').strip())[0].lower()
        yr = int(dd['Year']) if (dd.get('Year') or '').isdigit() else None
        jm = [j['abr'] for j in jk if j['first'] and j['year'] and first and j['first'] == first and j['year'] == yr]
        res[sig] = {'eval_start': st, 'dropped': drop, 'months': len(s), 'full': full, 'train': tr, 'hold': ho, 'hold_net': hn,
                    'roll20_net': _ro_brief(ro, ('wins', 'windows', 'win_rate')),
                    'pub': yr, 'authors': dd.get('Authors'), 'jkp_overlap_by_author_year': jm or None,
                    'in_this_angle': sig in {r['signal'] for r in D.RULES if 'signal' in r}}
        pv[sig] = ho['p'] if ho else None
        res[sig]['_s'] = s
    hp = N.holm(pv)
    counts = {'S': [], 'A': [], 'B': [], 'C': []}
    for sig, x in res.items():
        g, c = N.grade(full=x['full'], train=x['train'], hold=x['hold'], roll20=x['roll20_net'], cost_hold=x['hold_net'],
                       repl=None, family_holm_p=hp.get(sig), leveraged_or_timing=False)
        x['holm_p'] = hp.get(sig)
        x['grade'] = g
        x['criteria'] = c
        counts[g].append(sig)
    return res, counts, sha, jerr


def compact_base(res):
    out = {}
    for sig, x in res.items():
        out[sig] = {'grade': x['grade'], 'eval_start': x['eval_start'], 'months': x['months'],
                    'train_ex_ann': (x['train'] or {}).get('ex_ann'), 'train_t': (x['train'] or {}).get('t'),
                    'hold_ex_ann': (x['hold'] or {}).get('ex_ann'), 'hold_t': (x['hold'] or {}).get('t'),
                    'hold_cagr_diff_net': (x['hold_net'] or {}).get('cagr_diff'), 'full_t': (x['full'] or {}).get('t'),
                    'roll20_net_win': (x['roll20_net'] or {}).get('win_rate'), 'holm_p': x['holm_p'],
                    'criteria_passed': [k for k, v in x['criteria'].items() if v is True],
                    'pub': x['pub'], 'jkp_overlap_by_author_year': x['jkp_overlap_by_author_year'], 'in_this_angle': x['in_this_angle']}
    return out


# ── R8 実物 ──
def real_instruments(byser):
    cur = datetime.date.today().year * 100 + datetime.date.today().month
    out = {'note': 'Yahoo の配当込み（調整後終値）。途中の今月（{}）は落とした。生き残りの ETF。格付けに入れない'.format(cur)}
    spy = {k: v for k, v in N.yahoo('SPY').items() if k < cur}
    for t in ('MOAT', 'KOMP'):
        try:
            e = {k: v for k, v in N.yahoo(t).items() if k < cur}
        except Exception as ex:  # noqa
            out[t] = {'error': str(ex)}
            continue
        o = {'first_month': min(e), 'last_month': max(e), 'dropped_partial_month': cur,
             'vs_SPY_all': N.excess_stats(e, spy), 'vs_FrenchMkt_to_2024_12': N.excess_stats(e, MKT, None, LAST),
             'same_months_to_2024_12': {}}
        ks = [k for k in e if k <= LAST and k in MKT]
        a, z = min(ks), max(ks)
        for rid in ('X3a_MIX8', 'P1_OrgCap_q5vw', 'P5_SurpriseRD_vwf'):
            sr = byser[rid]
            o['same_months_to_2024_12'][rid] = {'gross': N.excess_stats(sr['s'], MKT, a, z), 'net': N.excess_stats(net_of(sr), MKT, a, z)}
        o['same_months_to_2024_12']['_window'] = [a, z]
        out[t] = o
    return out


# ───────────────────────── 確かめ ─────────────────────────
def data_sanity(results):
    chk = {'sha': check_sha()}
    # LS 恒等式
    worst, fails = 0.0, []
    ff93 = 0.0
    for s, v in SIG.items():
        for f, ports in v.items():
            if 'LS' not in ports:
                continue
            LS = {m: r for m, r, n in ports['LS']}
            if f == 'FF93style':
                P = {p: {m: r for m, r, n in ports[p]} for p in ('SH', 'BH', 'SL', 'BL')}
                for m in LS:
                    if all(m in P[p] for p in P):
                        ff93 = max(ff93, abs(LS[m] - (0.5 * (P['SH'][m] + P['BH'][m]) - 0.5 * (P['SL'][m] + P['BL'][m]))))
                continue
            num = sorted(p for p in ports if p != 'LS')
            H = {m: r for m, r, n in ports[num[-1]]}
            L = {m: r for m, r, n in ports[num[0]]}
            for m in LS:
                if m not in H or m not in L:
                    fails.append((s, f, m, 'missing'))
                    continue
                e = abs(LS[m] - (H[m] - L[m]))
                worst = max(worst, e)
                if e >= 1e-6:
                    fails.append((s, f, m, e))
    chk['LS_identity'] = {'max_abs_err_decimal': worst, 'fails': fails[:20], 'ok': not fails,
                          'FF93style_note': 'FF93 型の LS は 最大の組−最小の組 ではなく (SH+BH)/2 − (SL+BL)/2（OSAP 32_Predictor2x3Ports.R）。その式で確かめた',
                          'FF93style_max_abs_err': ff93}
    if fails:
        raise SystemExit(f'LS の恒等式が合わない {fails[:5]}')
    # 単位
    big = [(s, f, p, m, r) for s, v in SIG.items() for f, ports in v.items() for p, rows in ports.items() for m, r, n in rows if abs(r) > 1.0]
    chk['units_abs_gt_1'] = len(big)
    if big:
        raise SystemExit(f'|月次|>100% の月がある {big[:5]}')
    # French
    diff = max(abs(MKT_ALL[k] - (MKTRF_ALL[k] + RF_ALL[k])) for k in MKT_ALL)
    chk['French_Mkt_eq_MktRF_plus_RF_max_abs_err'] = diff
    chk['French_Mkt_last_month_available'] = max(MKT_ALL)
    chk['comparison_last_month'] = max(max(x['s']) for x in SER.values() if x['s'])
    chk['no_month_after_2024_12'] = all(max(x['s']) <= LAST for x in SER.values() if x['s'])
    # Nlong<20 で落ちた月
    want = {'P4_RDAbility_q5vw': 6, 'P5_SurpriseRD_vwf': 39}
    got = {rid: SER[rid]['drop'] for rid in D.MAIN_IDS}
    chk['dropped_nlong_lt20'] = {'got': got, 'prereg': 'P4 6・P5 39・他 0',
                                 'ok': all(got[k] == want.get(k, 0) for k in got)}
    chk['eval_start_main'] = {rid: SER[rid]['start'] for rid in D.MAIN_IDS}
    chk['train_months_main'] = {rid: len([m for m in SER[rid]['s'] if m <= TE]) for rid in D.MAIN_IDS}
    chk['hold_months_main'] = {rid: len([m for m in SER[rid]['s'] if m >= HS]) for rid in D.MAIN_IDS}
    # 特許
    pf = rows_of('PatentsRD', 'PortsFull', '02') or []
    after = [x for x in pf if x[0] >= 200807]
    chk['PatentsRD_port02_after_2008_07'] = {'months': len(after), 'nlong_median': S.median([x[2] for x in after]) if after else None}
    # 合成
    comp = {}
    for rid in ('X3a_MIX8', 'X3b_INTANGCAP', 'X3c_INNOV', 'X3d_QUALITY'):
        sr = SER[rid]
        comp[rid] = {'min_legs_rule': RULES[rid]['min_legs'], 'min_legs_seen': min(sr['nlegs'].values()),
                     'weights_sum_max_abs_err': max(abs(w - 1) for w in sr['wsum'].values()), 'legs_hist': sr['legs_hist'],
                     'ok': min(sr['nlegs'].values()) >= RULES[rid]['min_legs'] and max(abs(w - 1) for w in sr['wsum'].values()) < 1e-12}
    chk['composites'] = comp
    return chk


# ───────────────────────── 事後の診断（格付けに使わない） ─────────────────────────
def ols_nw(y, Xs, lag=12):
    """y = a + Σ b X（月次）。a の年率（%）と NW t。numpy"""
    import numpy as np
    Y = np.array(y)
    Xm = np.column_stack([np.ones(len(y))] + [np.array(x) for x in Xs])
    beta, *_ = np.linalg.lstsq(Xm, Y, rcond=None)
    e = Y - Xm @ beta
    n, k = Xm.shape
    XtX_inv = np.linalg.inv(Xm.T @ Xm)
    Sm = np.zeros((k, k))
    Xe = Xm * e[:, None]
    for L in range(0, lag + 1):
        w = 1.0 if L == 0 else 1 - L / (lag + 1)
        G = Xe[L:].T @ Xe[:n - L]
        Sm += w * (G if L == 0 else G + G.T)
    V = XtX_inv @ Sm @ XtX_inv
    se = np.sqrt(np.diag(V))
    return beta, beta / se


def post_hoc(results, byser):
    """事後（結果を見た後）の診断。格付けには使わない"""
    ph = {'_note': '事後＝結果を見た後に足した診断。格付けには使わない'}
    # 因子への回帰（FF5 + 勢い）: 良い側 − Mkt の超過は、既知の因子の傾きで説明されるか
    try:
        T5 = N.french_tables('F-F_Research_Data_5_Factors_2x3')
        t5 = next(v for k, v in T5.items() if v['freq'] == 'monthly')
        cols = [c.lower().replace('-', '') for c in t5['cols']]
        F5 = {c: {d: row[i] / 100 for d, row in t5['data'].items() if row[i] is not None} for i, c in enumerate(cols)}
        Tm = N.french_tables('F-F_Momentum_Factor')
        tm = next(v for k, v in Tm.items() if v['freq'] == 'monthly')
        UMD = {d: row[0] / 100 for d, row in tm['data'].items() if row[0] is not None}
        reg = {}
        for x in results:
            rid = x['id']
            s = byser[rid]['s']
            for nm, (a, z) in (('train', (None, TE)), ('hold', (HS, LAST)), ('full', (None, LAST))):
                ks = sorted(k for k in s if k in MKT and k in F5['mktrf'] and k in UMD and (a is None or k >= a) and (z is None or k <= z))
                if len(ks) < 36:
                    continue
                y = [s[k] - MKT[k] for k in ks]
                bb, tt = ols_nw(y, [[F5['mktrf'][k] for k in ks], [F5['smb'][k] for k in ks], [F5['hml'][k] for k in ks],
                                    [F5['rmw'][k] for k in ks], [F5['cma'][k] for k in ks], [UMD[k] for k in ks]])
                reg.setdefault(rid, {})[nm] = {'alpha_ann_pct': round(bb[0] * 1200, 2), 'alpha_t': round(float(tt[0]), 2),
                                               'loadings': {n_: round(float(v), 2) for n_, v in zip(['mktrf', 'smb', 'hml', 'rmw', 'cma', 'umd'], bb[1:])},
                                               'loading_t': {n_: round(float(v), 1) for n_, v in zip(['mktrf', 'smb', 'hml', 'rmw', 'cma', 'umd'], tt[1:])},
                                               'months': len(ks)}
        ph['factor_regression_FF5_UMD'] = {'what': '（良い側 − French Mkt）を FF5（Mkt-RF・SMB・HML・RMW・CMA）と勢い UMD に回帰した切片（年率%・NW t ラグ12）。費用前',
                                           'by_rule': reg}
    except Exception as e:  # noqa
        ph['factor_regression_FF5_UMD'] = {'error': str(e)}
    # 保有期間の超過の年ごとの分解と、上位の年を抜いた版
    yearly = {}
    for x in results:
        rid = x['id']
        s = byser[rid]['s']
        sn = net_of(byser[rid])
        ys = {}
        for k in s:
            if k >= HS:
                ys.setdefault(k // 100, []).append(k)
        yr = {}
        for y, ks in sorted(ys.items()):
            gs = math.prod(1 + s[k] for k in ks) - 1
            gb = math.prod(1 + MKT[k] for k in ks) - 1
            yr[y] = round((gs - gb) * 100, 2)
        wins = sum(1 for v in yr.values() if v > 0)
        top = sorted(yr, key=lambda y: -yr[y])[:2]
        ex_top = {k: v for k, v in sn.items() if k >= HS and k // 100 not in top}
        e_ex = N.excess_stats(ex_top, MKT, HS, LAST)
        h1 = N.excess_stats(sn, MKT, HS, 201512)
        h2 = N.excess_stats(sn, MKT, 201601, LAST)
        yearly[rid] = {'hold_year_excess_pct_gross': yr, 'years_won': f'{wins}/{len(yr)}', 'top2_years': top,
                       'net_hold_ex_top2_years_cagr_diff': e_ex['cagr_diff'] if e_ex else None,
                       'net_hold_2007_2015_cagr_diff': h1['cagr_diff'] if h1 else None, 'net_hold_2016_2024_cagr_diff': h2['cagr_diff'] if h2 else None,
                       'net_hold_2007_2015_t': h1['t'] if h1 else None, 'net_hold_2016_2024_t': h2['t'] if h2 else None}
    ph['hold_by_year'] = {'what': '保有期間の暦年ごとの幾何の超過（費用前・%）・勝った年の数・超過の大きい2年を抜いた費用後の年率差・前半/後半（費用後）',
                          'by_rule': yearly}

    # 母集団の効果か信号の効果か: 良い側 − 同じ変数の全組の等分の平均（母集団の粗い代わり。組の時価が無いので等分）
    uni = {}
    for x in results:
        r = RULES[x['id']]
        if 'signal' not in r:
            continue
        ports = SIG[r['signal']][r['file']]
        names = ['BL', 'BM', 'BH'] if r['port'] == 'BH' else sorted(p for p in ports if p != 'LS' and not p.startswith(('S', 'B')))
        P = {p: {m: v for m, v, n in ports[p] if m <= LAST} for p in names}
        common = set.intersection(*[set(v) for v in P.values()])
        proxy = {m: S.mean([P[p][m] for p in names]) for m in common}
        s = byser[x['id']]['s']
        uni[x['id']] = {'proxy_ports': names,
                        'proxy_vs_mkt': {k: N.excess_stats(proxy, MKT, a, z) for k, (a, z) in (('train', (None, TE)), ('hold', (HS, LAST)))},
                        'good_vs_proxy': {k: N.excess_stats(s, proxy, a, z) for k, (a, z) in (('train', (None, TE)), ('hold', (HS, LAST)))}}
    ph['universe_proxy'] = {'what': '良い側の上乗せのうち『その変数の母集団に居ること』の分（全組の等分の平均 対 Mkt）と、信号の分（良い側 対 全組の等分の平均）。'
                                    '全組の等分は母集団の時価加重ではない（組の時価が無い）ので粗い見当。費用前',
                            'by_rule': uni}

    # テックの傾きで説明できるか: FF5 + UMD + (French 49業種の Chips・Softw・Hardw の等分 − Mkt)
    try:
        ind = N.french_series('49_Industry_Portfolios', want='Average Value Weighted Returns -- Monthly')
        tech = {m: S.mean([ind['Chips'][m], ind['Softw'][m], ind['Hardw'][m]]) - MKT[m] for m in MKT
                if all(m in ind[c] for c in ('Chips', 'Softw', 'Hardw'))}
        T5 = N.french_tables('F-F_Research_Data_5_Factors_2x3')
        t5 = next(v for k, v in T5.items() if v['freq'] == 'monthly')
        cols = [c.lower().replace('-', '') for c in t5['cols']]
        F5 = {c: {d: row[i] / 100 for d, row in t5['data'].items() if row[i] is not None} for i, c in enumerate(cols)}
        Tm = N.french_tables('F-F_Momentum_Factor')
        tm = next(v for k, v in Tm.items() if v['freq'] == 'monthly')
        UMD = {d: row[0] / 100 for d, row in tm['data'].items() if row[0] is not None}
        tr = {}
        for x in results:
            s = byser[x['id']]['s']
            for nm, (a, z) in (('train', (None, TE)), ('hold', (HS, LAST))):
                ks = sorted(k for k in s if k in MKT and k in F5['mktrf'] and k in UMD and k in tech and (a is None or k >= a) and (z is None or k <= z))
                if len(ks) < 36:
                    continue
                y = [s[k] - MKT[k] for k in ks]
                bb, tt = ols_nw(y, [[F5[f][k] for k in ks] for f in ('mktrf', 'smb', 'hml', 'rmw', 'cma')] + [[UMD[k] for k in ks], [tech[k] for k in ks]])
                tr.setdefault(x['id'], {})[nm] = {'alpha_ann_pct': round(bb[0] * 1200, 2), 'alpha_t': round(float(tt[0]), 2),
                                                  'tech_loading': round(float(bb[7]), 2), 'tech_t': round(float(tt[7]), 1), 'months': len(ks)}
        ph['tech_tilt_regression'] = {'what': '（良い側 − Mkt）を FF5 + UMD + テック（French 49業種の Chips・Softw・Hardw の時価加重の等分 − Mkt）に回帰。'
                                              '保有期間の勝ちが『巨大テックの傾き』で説明されるかの見当。費用前・NW t ラグ12',
                                      'by_rule': tr}
    except Exception as e:  # noqa
        ph['tech_tilt_regression'] = {'error': str(e)}
    return ph


# ───────────────────────── 本体 ─────────────────────────
def main():
    check_sha()
    # 系列
    for r in D.RULES:
        if 'signal' in r:
            SER[r['id']] = build_single(r)
    for r in D.RULES:
        if 'parts' in r:
            SER[r['id']] = build_composite(r)

    graded = [r for r in D.RULES if r['fam'] in FAMS]
    results = []
    for r in graded:
        ser = SER[r['id']]
        x = {'id': r['id'], 'family': r['fam'], 'exploratory': r['fam'] != 'P',
             'what': r.get('what') or PR['families'].get({'X1': 'X1_deciles', 'X2': 'X2_bigcap'}.get(r['fam'], ''), {}).get('rules', {}).get(r['id'], {}).get('series'),
             'signal': r.get('signal'), 'file': r.get('file'), 'port': r.get('port'), 'parts': r.get('parts'),
             'turn_assumed': ser['turn_ann'], 'cost_pct_per_year': round(ser['turn_ann'] * UNIT * 100, 4) if ser['turn_ann'] else None,
             'eval_start': ser['start'], 'months': ser['months'], 'dropped_after_start_nlong_lt20': ser['drop'],
             'nlong_median_all': ser.get('nlong_med_all'), 'nlong_median_hold': ser.get('nlong_med_hold'),
             'pub': r.get('pub'), 'op_sample': list(r['op']) if r.get('op') else None}
        x.update(evaluate(r['id'], ser, r if 'signal' in r else {}))
        if 'parts' in r:
            x['legs_hist'] = ser['legs_hist']
            x['cost_note'] = '月ごとに 使った脚の回転の平均＋0.10（等分へ戻す）× 0.30%／12。turn_assumed はその平均'
        results.append(x)

    # Holm（族ごと・両側・保有期間・費用前）
    holm = {}
    for fam in FAMS:
        pv = {x['id']: (x['gross']['hold'] or {}).get('p') for x in results if x['family'] == fam}
        holm[fam] = N.holm(pv)
    for x in results:
        hp = holm[x['family']].get(x['id'])
        x['family_holm_p'] = hp
        g, c = grade_one(x, hp)
        x['grade'] = g
        x['criteria'] = c
        if x['exploratory']:
            x['grade_label'] = f'探索 {g}'

    # 報告
    for x in results:
        r = RULES[x['id']]
        x['R4_other_side'] = other_side(r, SER[x['id']])
        x['R6_cost_sensitivity'] = cost_sensitivity(SER[x['id']])
        x['R7_other'] = {k: (x['gross']['full'] or {}).get(k) for k in ('beta', 'te', 'ir', 'vol_s', 'vol_b')}
        x['R7_other_hold'] = {k: (x['gross']['hold'] or {}).get(k) for k in ('beta', 'te', 'ir', 'vol_s', 'vol_b')}

    # R1 特許（訓練だけ）
    r1 = {}
    for rid in ('R1_PatentsRD_op', 'R1_CitationsRD_op'):
        r = RULES[rid]
        rows = rows_of(r['signal'], r['file'], r['port'])
        s, st, drop = filt([x for x in rows if x[0] <= TE])
        ser = {'s': s, 'turn_m': {m: r['turn'] for m in s}}
        r1[rid] = {'what': r['what'], 'eval_start': st, 'dropped': drop, 'train_months': len(s),
                   'train_gross': N.excess_stats(s, MKT, None, TE), 'train_net': N.excess_stats(net_of(ser), MKT, None, TE),
                   'op_sample_gross': N.excess_stats(s, MKT, r['op'][0] * 100 + 1, TE),
                   'nlong_median_train': nlong_median(rows, z=TE),
                   'why_not_graded': PR['families']['R_report_only']['R1_patents_train_only']['why_not_graded']}

    # R2
    halves, hchk = size_halves()
    r2rep = r2_report(halves)
    r2rep['_size_half_check'] = hchk

    # R5
    base, counts, zsha, jerr = base_rate()
    same = {}
    for rid in ('P1_OrgCap_q5vw', 'P2_AdExp_q5vw', 'P3_BrandInvest_q5vw', 'P4_RDAbility_q5vw', 'P6_Herf_q5vw', 'P8_FR_q5vw'):
        sig = RULES[rid]['signal']
        a, b = SER[rid]['s'], base[sig]['_s']
        same[rid] = {'same_keys': sorted(a) == sorted(b), 'max_abs_diff': max(abs(a[k] - b[k]) for k in a) if sorted(a) == sorted(b) else None}
    for v in base.values():
        v.pop('_s', None)
    main_ids = [x for x in results if x['family'] == 'P']
    hold_ex_all = sorted((v['hold'] or {}).get('ex_ann', -999) for v in base.values() if v['hold'])
    pct = {}
    for x in main_ids:
        h = (x['gross']['hold'] or {}).get('ex_ann')
        if h is not None:
            pct[x['id']] = round(sum(1 for v in hold_ex_all if v < h) / len(hold_ex_all), 3)
    tr_ho = [((v['train'] or {}).get('ex_ann'), (v['hold'] or {}).get('ex_ann')) for v in base.values() if v['train'] and v['hold']]
    r5 = {'what': PR['families']['R_report_only']['R5_base_rate'], 'quintilesvw_sha256': zsha, 'n_signals': len(base),
          'grade_counts': {g: len(v) for g, v in counts.items()}, 'grade_lists': {g: v for g, v in counts.items() if g != 'C'},
          'main8_grades': {x['id']: x['grade'] for x in main_ids},
          'main_hold_gross_ex_ann_percentile_in_179': pct,
          'hold_gross_ex_ann_distribution_179': {'median': S.median(hold_ex_all), 'share_positive': round(sum(1 for v in hold_ex_all if v > 0) / len(hold_ex_all), 3),
                                                  'p10': hold_ex_all[len(hold_ex_all) // 10], 'p90': hold_ex_all[len(hold_ex_all) * 9 // 10]},
          'hold_net_cagr_diff_positive_179': sum(1 for v in base.values() if v['hold_net'] and v['hold_net']['cagr_diff'] > 0),
          'train_C1_pass_179': sum(1 for v in base.values() if v['criteria']['C1_train']),
          'train_vs_hold_ex_ann_corr_179': round(N.corr([a for a, _ in tr_ho], [b for _, b in tr_ho]), 3),
          'sanity_main_quintile_series_identical': same,
          'jkp_mark': {'method': 'JKP の Factor Details.xlsx の cite の第1著者の姓と年が SignalDoc の Authors の第1語と Year に一致したら印（近似・格付けに関係しない）',
                       'error': jerr, 'marked': sum(1 for v in base.values() if v['jkp_overlap_by_author_year'])},
          'cost_used': '一律 回転0.8・片道100%あたり0.30%',
          'by_signal': compact_base(base)}
    if not all(v['same_keys'] and v['max_abs_diff'] == 0 for v in same.values()):
        print('警告: R5 の系列が主の系列と一致しない', same)

    # 是正の記録（丸める前の値で勝ちを数えた結果、nx_common の丸めた数え方と食い違ったところを全部）
    fix_rows = []

    def _log(where, ro, is_c4, grade_now=None, grade_if_rounded=None):
        if not ro or ('wins_nx_common_rounded' not in ro and 'win_rate_nx_common_rounded' not in ro):
            return
        row = {'where': where, 'windows': ro.get('windows'),
               'before_nx_common_rounded': {'wins': ro.get('wins_nx_common_rounded'), 'win_rate': ro.get('win_rate_nx_common_rounded')},
               'after_unrounded': {'wins': ro.get('wins'), 'win_rate': ro.get('win_rate')},
               'windows_that_changed': ro.get('wins_changed_by_rounding')}
        if is_c4:
            row['C4_before'] = (ro.get('win_rate_nx_common_rounded') or 0) >= 0.8
            row['C4_after'] = (ro.get('win_rate') or 0) >= 0.8
        if grade_now is not None:
            row['grade_after'] = grade_now
            row['grade_if_rounded_count'] = grade_if_rounded
        fix_rows.append(row)

    for x in results:
        ro = x['roll20_net']
        g_round = None
        if ro and 'wins_nx_common_rounded' in ro:
            ro_r = dict(ro, wins=ro['wins_nx_common_rounded'], win_rate=ro['win_rate_nx_common_rounded'])
            g_round, _ = N.grade(full=x['gross']['full'], train=x['gross']['train'], hold=x['gross']['hold'], roll20=ro_r,
                                 cost_hold=x['net']['hold'], repl=None, family_holm_p=x['family_holm_p'], leveraged_or_timing=False)
        _log(f"tested.{x['id']}.roll20_net（C4・格付けに使う）", ro, True, x['grade'] if g_round else None, g_round)
        _log(f"tested.{x['id']}.roll20_gross（報告のみ）", x['roll20_gross'], False)
        _log(f"tested.{x['id']}.dca20_net（報告のみ）", x['dca20_net'], False)
        _log(f"tested.{x['id']}.dca20_gross（報告のみ）", x['dca20_gross'], False)
        for k, v in x['R6_cost_sensitivity'].items():
            _log(f"tested.{x['id']}.R6_cost_sensitivity.{k}.roll20_net（報告のみ）", v['roll20_net'], True)
    for sig, v in base.items():
        ro = v['roll20_net']
        g_round = None
        if ro and 'wins_nx_common_rounded' in ro:
            ro_r = dict(ro, wins=ro['wins_nx_common_rounded'], win_rate=ro['win_rate_nx_common_rounded'])
            g_round, _ = N.grade(full=v['full'], train=v['train'], hold=v['hold'], roll20=ro_r, cost_hold=v['hold_net'],
                                 repl=None, family_holm_p=v['holm_p'], leveraged_or_timing=False)
        _log(f"reports.R5_base_rate.{sig}.roll20_net（R5 の格付けに使う）", ro, True, v['grade'] if g_round else None, g_round)
    fixes = [{
        'id': 'F1_rolling_rounding_2026-09-28',
        'reported_by': '検査役（事前登録との一致と先読み・原本から numpy で独立に再計算）',
        'what': 'nx_common.rolling は窓ごとの年率差を %・小数2桁に丸めてから『>0 なら勝ち』を数えていた。+0.0032%/年 の窓（P4 研究開発の腕・費用後・1994-07〜2014-06）が勝ちに入らず、C4 の勝ちの数が 13/28 と出ていた（丸める前は 14/28）',
        'verified': '本当の誤り。C4 は「全期間の転がる20年窓で市場に勝った割合」＝差が正の窓の割合で、丸めは数え方の副作用（事前登録の規則の誤読の是正であって規則は変えていない）。同じ種類の丸め（倍率を小数3桁にしてから >1 を数える）が nx_common.dca にもあったので同時に直した（報告のみの欄）',
        'how': 'この角度の中で rolling_x / dca_x を作り、nx_common と同じ窓で丸める前の差・倍率で勝ちを数える。丸めた値（median・worst・best）は表示にそのまま残す。窓の切り方は nx_common の戻り値と毎回照合（窓数・中央・丸めた勝ちの数が一致しなければ止まる）。nx_common.py は全角度の共通部品なので書き換えていない＝直すならまとめ役が全角度で同時に',
        'changes': fix_rows,
        'grade_changes': [r for r in fix_rows if 'grade_after' in r and r['grade_after'] != r['grade_if_rounded_count']],
        'c4_changes': [r['where'] for r in fix_rows if 'C4_before' in r and r['C4_before'] != r['C4_after']],
        'conclusion': '食い違いは下の changes の全部。C4（≥80%）の合否が変わったものは c4_changes、格付けが変わったものは grade_changes（どちらも空なら格付けは不変）',
    }]
    _c4 = [r for r in fix_rows if 'C4_before' in r]
    fixes[0]['result'] = (f"丸めで勝ちの数が変わった箇所 {len(fix_rows)} 件（うち C4 の勝率に当たる欄 {len(_c4)} 件・格付けに使う欄 {sum(1 for r in fix_rows if 'grade_after' in r)} 件）。"
                          f"C4 の合否が変わったもの {len(fixes[0]['c4_changes'])} 件・格付けが変わったもの {len(fixes[0]['grade_changes'])} 件。"
                          f"主の27本の格付けに使う欄で変わったのは " + ('・'.join(f"{r['where'].split('.')[1]} {r['before_nx_common_rounded']['wins']}/{r['windows']}→{r['after_unrounded']['wins']}/{r['windows']}" for r in fix_rows if r['where'].startswith('tested.') and r['where'].endswith('roll20_net（C4・格付けに使う）')) or 'なし'))

    # R7 訓練と保有の相関（規則をまたいで）
    th = [((x['gross']['train'] or {}).get('ex_ann'), (x['gross']['hold'] or {}).get('ex_ann')) for x in results if x['gross']['train'] and x['gross']['hold']]
    r7 = {'train_vs_hold_ex_ann_corr_27': round(N.corr([a for a, _ in th], [b for _, b in th]), 3),
          'train_vs_hold_ex_ann_corr_179': r5['train_vs_hold_ex_ann_corr_179'],
          'interpretation': '『訓練と保有の相関』は規則をまたいだ相関（訓練の超過が大きい規則ほど保有の超過も大きいか）と読んだ（事前登録に定義が無い）'}

    # R8
    r8 = real_instruments(SER)

    sanity = data_sanity(results)
    ph = post_hoc(results, SER)

    # まとめ
    summ = {}
    for x in results:
        summ.setdefault(x['family'], {}).setdefault(x['grade'], []).append(x['id'])
    headline = []
    for x in results:
        g = x['gross']; n = x['net']
        headline.append({'id': x['id'], 'grade': x['grade'], 'eval_start': x['eval_start'],
                         'train_ex_ann': (g['train'] or {}).get('ex_ann'), 'train_t': (g['train'] or {}).get('t'),
                         'hold_ex_ann': (g['hold'] or {}).get('ex_ann'), 'hold_t': (g['hold'] or {}).get('t'), 'hold_cagr_diff': (g['hold'] or {}).get('cagr_diff'),
                         'hold_cagr_diff_net': (n['hold'] or {}).get('cagr_diff'), 'full_ex_ann': (g['full'] or {}).get('ex_ann'), 'full_t': (g['full'] or {}).get('t'),
                         'roll20_net': f"{(x['roll20_net'] or {}).get('wins')}/{(x['roll20_net'] or {}).get('windows')}" if x['roll20_net'] else None,
                         'dca20_net_median': (x['dca20_net'] or {}).get('median_ratio'), 'holm_p': x['family_holm_p'],
                         'criteria_passed': [k for k, v in x['criteria'].items() if v is True]})

    deviations = [
        'LS の恒等式の確かめ: FF93 型（X2 の元ファイル）の LS は OSAP の定義が『最大の組−最小の組』ではなく (SH+BH)/2 − (SL+BL)/2 なので、その式で確かめた（事前登録は一律に『最大の組−最小の組』と書いていた）。格付けに影響なし',
        'R4 の『中の組』: 十分位は 05 と 06、FF93 型は BM/SM、SurpriseRD（二値）は中が無い。LS は対 French Mkt ではなく自身の平均（対 0）で出した（買い−売りを市場と引き算しても意味が無いため）。報告のみ',
        'R7 の『訓練と保有の相関』は事前登録に定義が無いので、規則をまたいだ訓練の超過と保有の超過の相関（27本・179本）と読んだ。報告のみ',
        'R5 の JKP との重なりの印は、JKP の Factor Details.xlsx の cite と SignalDoc の第1著者の姓・年の一致による近似（同じ論文の別の変数も印が付く・名前の綴りの違いは漏れる）。格付けに関係しない',
        'R6 の合成（X3）の回転×0.5・×2 は、脚の平均＋0.10 の全体に倍率を掛けた。報告のみ',
        'Holm の p は nx_common.excess_stats が返す丸めた p（小数4桁）をそのまま使った（他の角度と同じ物差し）',
        'R1 の評価の開始は訓練期間（〜2006-12）の行だけで Nlong≥20 の最初の月を探した',
        'R2 の『超過が正』は事前登録に定義が無いので、算術平均の超過と幾何の年率差がともに正（費用前・同じ大きさの半分の市場に対して）とした。報告のみ',
        'R3 の公表後・原論文の標本の外は、公表年と標本の年を持つ単一の変数の規則だけ（合成 X3 は脚ごとに年が違うので直近 2013-07〜 だけ）。報告のみ',
        '事後の診断（post_hoc: FF5+勢いの回帰・テックの傾きの回帰・保有期間の年ごとの分解・母集団の粗い代わり〔全組の等分〕）は結果を見た後に足した。格付けには使っていない。FF5 は 1963-07 から始まるので、回帰の訓練期間は 1963-07〜',
        '（逸脱ではない注記）速さのために nx_common の statistics を、同じ list への mean の答えを覚えるだけの薄い包みに差し替えた（nx_common.py は書き換えていない）',
        '（逸脱ではない注記）転がる20年窓・20年積立は、Nlong<20 で落ちた月を s と b の両方から落として（前後をつないで）数える nx_common の窓の切り方をそのまま使った。落ちる月があるのは P4（6か月）・P5（39か月・1950〜60年代）と、それを脚に持つ合成だけ',
        '（規則の誤読の是正・2026-09-28）転がる20年窓（C4）と20年積立の『勝ち』は丸める前の差（>0）・倍率（>1）で数えた。nx_common.rolling / dca は丸めてから数えるため +0.0032%/年 の窓が負けに入っていた。窓の切り方・表示の丸めは nx_common のまま（詳細と前後の数字は fixes）',
    ]

    byid = {x['id']: x for x in results}

    def ex(rid, per='hold', kind='gross'):
        e = byid[rid][kind][per]
        return f"{e['ex_ann']:+.2f}%/年 t{e['t']}" if e else '—'

    def cd(rid, per='hold', kind='net'):
        e = byid[rid][kind][per]
        return f"{e['cagr_diff']:+.2f}%/年" if e else '—'

    def ro(rid):
        v = byid[rid]['roll20_net']
        return f"{v['wins']}/{v['windows']}" if v else '—'

    p1, yb, up, tt = byid['P1_OrgCap_q5vw'], ph['hold_by_year']['by_rule'], ph['universe_proxy']['by_rule'], ph.get('tech_tilt_regression', {}).get('by_rule', {})
    ms = r5['by_signal'].get('MomOffSeason06YrPlus', {})
    summary = [
        f"主の族 P（8本）: S={summ['P'].get('S', [])} / A={summ['P'].get('A', [])} / B={summ['P'].get('B', [])} / C={len(summ['P'].get('C', []))}本。"
        f"探索 X1〜X4（19本）: B={sum((summ[f].get('B', []) for f in ('X1', 'X2', 'X3', 'X4')), [])}・残りは C。A と S は27本の中に0本（事前の予想『C 6〜8・B 0〜2・A/S 0』どおり）",
        f"P1 組織資本（OrgCap）の高い五分位が最良で B: 訓練 {ex('P1_OrgCap_q5vw', 'train')}・全期間 t{p1['gross']['full']['t']}（C7 合格）・費用後の20年窓 {ro('P1_OrgCap_q5vw')}・"
        f"保有 2007-2024 {ex('P1_OrgCap_q5vw')}（C3 の t≥1.65 に届かない）・費用後の保有の年率差 {cd('P1_OrgCap_q5vw')}。"
        f"ただし直近 2013-07〜 {ex('P1_OrgCap_q5vw', 'recent')}・公表後 2014〜 {ex('P1_OrgCap_q5vw', 'post_pub')}＝保有期間の正は 2007-2015（費用後 {yb['P1_OrgCap_q5vw']['net_hold_2007_2015_cagr_diff']:+.2f}%/年）に集中し、"
        f"2016-2024 は {yb['P1_OrgCap_q5vw']['net_hold_2016_2024_cagr_diff']:+.2f}%/年（事後の分解）",
        f"保有期間だけ強い4本は訓練の C1 を落として C: P4 研究開発の腕 保有 {ex('P4_RDAbility_q5vw')}（訓練 {ex('P4_RDAbility_q5vw', 'train')}）・P7 G スコア {ex('P7_MS_vwf')}（訓練 {ex('P7_MS_vwf', 'train')}）・"
        f"P5 研究開発の増加 {ex('P5_SurpriseRD_vwf')}（訓練 {ex('P5_SurpriseRD_vwf', 'train')}）・X3c 革新の合成 {ex('X3c_INNOV')}（族の Holm 後 p={byid['X3c_INNOV']['family_holm_p']}・20年窓 {ro('X3c_INNOV')}・訓練 {ex('X3c_INNOV', 'train')}）。"
        f"事前登録に書いた後知恵の予想（研究開発を伸ばした巨大テックが入る側が保有期間に正）そのもの",
        (f"その勝ちの中身（事後）: P4 は悪い側（組01）も保有 {byid['P4_RDAbility_q5vw']['R4_other_side']['bad_vs_mkt']['hold']['ex_ann']:+.2f}%/年 で、全組の等分（研究開発の厚い会社の母集団の代わり）が対 Mkt "
         f"{up['P4_RDAbility_q5vw']['proxy_vs_mkt']['hold']['ex_ann']:+.2f}%/年＝勝ちの大半は『研究開発の厚い会社に居ること』。テックの傾き（Chips・Softw・Hardw−Mkt）の係数は "
         f"P4 {tt.get('P4_RDAbility_q5vw', {}).get('hold', {}).get('tech_loading')}（t{tt.get('P4_RDAbility_q5vw', {}).get('hold', {}).get('tech_t')}）・X3c {tt.get('X3c_INNOV', {}).get('hold', {}).get('tech_loading')}（t{tt.get('X3c_INNOV', {}).get('hold', {}).get('tech_t')}）、"
         f"FF5+勢い+テックで引いた後の保有の切片 P4 {tt.get('P4_RDAbility_q5vw', {}).get('hold', {}).get('alpha_ann_pct')}%/年 t{tt.get('P4_RDAbility_q5vw', {}).get('hold', {}).get('alpha_t')}・"
         f"X3c {tt.get('X3c_INNOV', {}).get('hold', {}).get('alpha_ann_pct')}%/年 t{tt.get('X3c_INNOV', {}).get('hold', {}).get('alpha_t')}"),
        f"年金の積立状況（FR）は保有期間に負けの側で有意: P8 {ex('P8_FR_q5vw')}・X2 大型の FR {ex('X2_FR_BH')}（族の Holm 後 p={byid['X2_FR_BH']['family_holm_p']}＝負けの向きで C7 を通った）。"
        f"ブランド投資率（P3）は保有 {ex('P3_BrandInvest_q5vw')}・公表後 2015〜 {ex('P3_BrandInvest_q5vw', 'post_pub')}",
        f"探索の B（X1 十分位の OrgCap・X2 大型の OrgCap・X3a 8本の合成）はどれも C3 を落とした: X3a は訓練 {ex('X3a_MIX8', 'train')}・20年窓 {ro('X3a_MIX8')} だが保有 {ex('X3a_MIX8')}・費用後 {cd('X3a_MIX8')}、"
        f"X2 大型 OrgCap は保有 {ex('X2_OrgCap_BH')}",
        f"R5 基礎率（OSAP の連続の予言変数179本すべての良い側・同じ線）: S {r5['grade_counts']['S']}・A {r5['grade_counts']['A']}・B {r5['grade_counts']['B']}・C {r5['grade_counts']['C']}。"
        f"保有期間の超過の中央 {r5['hold_gross_ex_ann_distribution_179']['median']}%/年・正は {r5['hold_gross_ex_ann_distribution_179']['share_positive'] * 100:.1f}%、訓練と保有の超過の相関 {r5['train_vs_hold_ex_ann_corr_179']}。"
        f"主の8本（B 1/8）は基礎率（B 13/179）と同程度。179本の唯一の S は MomOffSeason06YrPlus（季節性の勢い・JKP の seas_6_10 と同じ論文＝他セッションの季節性と重なる・保有 t{ms.get('hold_t')} で線の境界）＝この角度の規則ではなく報告のみ",
        f"R2（大きさの半分の市場に対して）: 全期間で大型・小型の両方で正は {r2rep['_count']['both_positive_full']}、保有期間で両方正は {r2rep['_count']['both_positive_hold']}",
        f"R8 実物: MOAT（2012-05〜）の対 SPY {r8['MOAT']['vs_SPY_all']['cagr_diff']:+.2f}%/年・KOMP（2018-11〜）{r8['KOMP']['vs_SPY_all']['cagr_diff']:+.2f}%/年（幾何の年率差）。同じ規則を個人が持つ手段は無い",
        '結論: この角度では市場（French Mkt）に訓練と保有の両方で線を越えて勝つ規則は見つからなかった（最良は B＝有望・弱い）。保有期間の勝ちは研究開発・成長・テックへの傾きで、訓練期間には効いていなかった。線は動かしていない',
    ]

    obj = {
        'generated': datetime.date.today().isoformat(),
        'angle': 'nx_osap_intang（OSAP の無形資産・革新・利益の質の良い側を時価加重で買って持つ）',
        'prereg': {'path': 'out/nx_osap_intang_prereg.json', 'commit': git_sha(PREREG_PATH), 'global': 'out/nx_prereg.json'},
        'script': 'night/nx_osap_intang.py',
        'stance': '測定器。門・採点・配分には入れない。線（C1〜C8）は結果を見て動かしていない。負けた規則も全部 tested に残す',
        'benchmark': 'French Mkt（Mkt-RF + RF・総リターン）。2024-12 まで（OSAP の終わり）',
        'conventions': {'C1_C2_C3_C7': '費用前（s 対 Mkt）', 'C4_C6': '費用後（s_net 対 Mkt）', 'C5': 'N/A（事前登録）', 'C8': 'N/A（買いだけ・借入なし・時期選びなし）',
                        'cost': '片道の売買回転の置き値 × 0.30%／年（毎月 1/12 を引く）', 'grading': 'nx_common.grade()（criteria_long_history）'},
        'summary_ja': summary,
        'data_sanity': sanity,
        'deviations_from_prereg': deviations,
        'fixes': fixes,
        'holm': holm,
        'grade_summary': summ,
        'headline': headline,
        'tested_count': {'graded': len(results), 'prereg_total_graded': PR['test_count']['total_graded']},
        'tested': results,
        'reports': {'R1_patents_train_only': r1, 'R2_size_halves': r2rep, 'R3_subperiods': 'tested の各規則の gross/net の recent・post_pub・op_sample・before_op・after_op_to_pub',
                    'R4_other_side': 'tested の各規則の R4_other_side', 'R5_base_rate': r5, 'R6_cost_sensitivity': 'tested の各規則の R6_cost_sensitivity',
                    'R7_other_metrics': r7, 'R8_real_instruments': r8},
        'post_hoc': ph,
        'known_limits': PR['known_limits'],
    }
    p = N.save(OUTNAME, obj)
    print('書いた:', p)
    print('格付け:', json.dumps(summ, ensure_ascii=False))
    for h in headline:
        print(json.dumps(h, ensure_ascii=False))
    print('R5:', json.dumps(r5['grade_counts']), r5['grade_lists'])
    return obj


if __name__ == '__main__':
    main()
