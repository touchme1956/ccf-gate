#!/usr/bin/env python3
"""night/bf_forward.py — 角度 bf_forward（前向きの検定・読むだけ・門の判定・採点・配分には不使用）

2026-10-11 ユーザー「時間を使って最高の投資信託かETFを探して。歴史検証そして未来検証全てやって最も良いとあなたが判断するものが何か調べ抜いて。」
事前登録 out/bestfund_prereg.json（d5eab7f）live_forward_test:「最良の1本が既存の前向きの検定（mw_forward の H1・nx_forward）に入っていなければ、
同じ規約で前向きの検定を1本登録する」。bestfund の登録どおりの最良の1本は **iFreeNEXT FANG+インデックス**（out/bestfund.json の verdict）で、
mw_forward（QQQM75/SMH25 ほか）にも nx_forward（業種の勢い・ブランド・日本の能動の投信ほか）にも入っていない。
→ 2026-11 の月次から、この投信が **eMAXIS Slim 米国株式（S&P500）** に勝つかを e過程で毎月追う（作法は nx_forward と同じ）。

段（事前登録 out/bf_forward_prereg.json の順番どおり）
  design   : 設計値（σ_d・μ_d・B・λ）を登録前のデータ（≤2026-09）で計算して表示する＝事前登録に書き写した数字の出どころ
  init     : 事前登録の凍結値を読み、設計を検算し、検出力（numpy）を計算 → out/bf_forward.json（前向きの月は 0）
  update   : 月次。完了した前向きの月（2026-11〜）を古い順に取り込み e を更新 → out/bf_forward.json（標準ライブラリだけで回る）
  selftest : 合成データの点検（e 過程の下限・Ville の不等式の模擬・月の固定・欠測の扱い・基準価額の跳びの検問）

約束（事前登録どおり）
- 比べるのは同じ通貨（円）の基準価額の総リターンどうし（信託報酬は基準価額の中で引かれている＝費用は足さない）。分配金は基準価額で再投資
- 月 m の値は、m より後の月の基準価額の行が出てから取り込む。一度取り込んだ月は固定（後の訂正は反映しない）
- 欠測を 0 と読まない（絶対のルール7）: 値が無い月は待つ。3か月待っても出ない月は『欠測』として飛ばす（e を動かさない）
- 規則・相手・λ・B・μ_d は変えない（変えたら別の新しい登録として e=1 から）。器が償還・指数の変更をしたら止める（差し替えない）
"""
import sys, os, json, math, time, datetime, argparse, statistics as S, hashlib, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N            # noqa: E402
import nx_forward as NF          # noqa: E402  e過程・帯・e-BH は nx_forward（凍結）の定義をそのまま使う＝単一実装

BASE = N.BASE
PREREG = os.path.join(BASE, 'out', 'bf_forward_prereg.json')
OUT_NAME = 'bf_forward.json'
OUT = os.path.join(BASE, 'out', OUT_NAME)
FC = os.path.join(N.CACHE, 'bf_forward')            # この道具だけのキャッシュ（out/_nx_cache は gitignore 済み）
FIRST_FWD = 202611                                  # 最初の前向きの月（登録 2026-10-11 は10月の途中＝10月は使わない）
DESIGN_END = 202609                                 # 設計に使う最後の月（登録の日に完了していた最後の月）
MAX_END = 204610                                    # 20年で打ち切り（2026-11〜2046-10 の240か月・未決なら『証明できず』）
E_IND = 20.0                                        # 1本の線（α=0.05・Ville の不等式）
WAIT_MONTHS = 3                                     # 値が出ない月はこの月数だけ待ってから『欠測』として飛ばす（nx_forward と同じ）
CLIP_K = 4.0                                        # B = 4σ_m を 0.5% 単位で切り上げ
MU_HAIRCUT = 0.5                                    # 公表後の縮み（全セッションの実測 0.44〜0.56）
MU_LO, MU_HI = 0.5, 3.0                             # μ_d の下限・上限（%/年）
MU_FIXED_SUB = 1.0                                  # 副の μ_d（nx_forward の副と同じ＝検出したい最小の上乗せ）
REVIEW_MONTH = 11                                   # 正式に見る月（毎年11月・10月までの前向きの12か月がそろった後）
JUMP_GUARD = (0.6, 1.6)                             # 1日の基準価額の比がこの外なら止める（口数の分割・誤値を黙って読まない）

FUNDS = {
    'FANG': {'name': 'iFreeNEXT FANG+インデックス', 'isin': 'JP90C000FZD4', 'assoc': '04311181', 'co': '大和アセットマネジメント',
             'fee_pct_tax_incl': 0.7755, 'index': 'NYSE FANG+ 指数（円換算）'},
    'SP500': {'name': 'eMAXIS Slim 米国株式（S&P500）', 'isin': 'JP90C000GKC6', 'assoc': '03311187', 'co': '三菱UFJアセットマネジメント',
              'fee_pct_tax_incl': 0.0814, 'index': 'S&P500（配当込み・円換算）'},
    'NDX': {'name': 'iFreeNEXT NASDAQ100インデックス', 'isin': 'JP90C000GUN2', 'assoc': '04317188', 'co': '大和アセットマネジメント',
            'fee_pct_tax_incl': 0.495, 'index': 'NASDAQ100（配当込み・円換算）'},
    'ACWI': {'name': 'eMAXIS Slim 全世界株式（オール・カントリー）', 'isin': 'JP90C000H1T1', 'assoc': '0331418A', 'co': '三菱UFJアセットマネジメント',
             'fee_pct_tax_incl': 0.05775, 'index': 'MSCI ACWI（配当込み・円換算）'},
}

HYP = {
    'G1_FANG_vs_SP500': {
        'ja': 'iFreeNEXT FANG+インデックス 対 eMAXIS Slim 米国株式（S&P500）（円・基準価額の総リターン・信託報酬を引いた後）',
        'port': 'FANG', 'bench': 'SP500', 'family': 'main', 'reverse': False,
        'mu_rule': ('insample', 'FANG−SP500 の登録前の算術の超過（2018-08〜2026-09）'),
        'why': 'bestfund の登録どおりの最良の1本（CE γ=2 で1位）と、0.2pt 以内で並んだ2位（S&P500 の最安の投信）。つみたて投資枠でどちらも買える'},
    'G1r_SP500_vs_FANG': {
        'ja': '同じ組の逆向き（S&P500 が FANG+ に勝つ・μ0=0）＝『FANG+ を選んだのが外れだった』の側（副・判定に使わない）',
        'port': 'FANG', 'bench': 'SP500', 'family': 'sub', 'reverse': True,
        'mu_rule': ('same_as', 'G1_FANG_vs_SP500'),
        'why': '主の検定は片側（FANG+ の上乗せ）だけを見る。逆の側（S&P500 のほうが良かった）も同じ λ・B の e過程で記録する（報告のみ）'},
    'G2_FANG_vs_NDX': {
        'ja': 'iFreeNEXT FANG+インデックス 対 iFreeNEXT NASDAQ100インデックス（ユーザーの今の主力の器）（副・判定に使わない）',
        'port': 'FANG', 'bench': 'NDX', 'family': 'sub', 'reverse': False,
        'mu_rule': ('fixed', MU_FIXED_SUB), 'why': '今の主力（NASDAQ100）から FANG+ へ替える価値があるか（報告のみ）'},
    'G3_FANG_vs_ACWI': {
        'ja': 'iFreeNEXT FANG+インデックス 対 eMAXIS Slim 全世界株式（オール・カントリー）（副・判定に使わない）',
        'port': 'FANG', 'bench': 'ACWI', 'family': 'sub', 'reverse': False,
        'mu_rule': ('fixed', MU_FIXED_SUB), 'why': '日本で最も多く積み立てられている相手（報告のみ）'},
}
ORDER = list(HYP)
FAMILIES = {'main': [h for h in ORDER if HYP[h]['family'] == 'main'], 'sub': [h for h in ORDER if HYP[h]['family'] == 'sub']}
LINES = {'main': E_IND * len(FAMILIES['main']), 'sub': E_IND * len(FAMILIES['sub'])}
CROSS_SESSION_K = 8 + 8                             # mw_forward（8本）＋ nx_forward（8本）＝全セッションの線の参考


# ───────────────────────── 月の小道具（nx_forward と同じ定義・today だけ別の環境変数） ─────────────────────────
months, addm = NF.months, NF.addm


def today():
    v = os.environ.get('BFF_TODAY')                 # 点検だけに使う（通常は空）
    if v:
        return datetime.date.fromisoformat(v)
    return datetime.datetime.now(datetime.timezone.utc).date()


def today_ym():
    d = today()
    return d.year * 100 + d.month


def overdue(m):
    t = today_ym()
    return (t // 100 * 12 + t % 100) - (m // 100 * 12 + m % 100) > WAIT_MONTHS


# ───────────────────────── 基準価額（投信総合検索ライブラリーの CSV） ─────────────────────────
def _J():
    import nx_jpfunds_data as J
    J.CUTOFF = 20991231                             # この工程の中だけ（凍結した nx_jpfunds の測定には触れない）
    return J


def nav_daily(key, max_age_h=12.0, lib=None):
    """→ [(yyyymmdd, 基準価額, 純資産, 分配金)]。この道具のキャッシュが max_age_h 時間より古ければ取り直す。
    HTTP 500（償還・消えた）は前の写しがあればそれ、無ければ None"""
    J = _J()
    f = FUNDS[key]
    os.makedirs(FC, exist_ok=True)
    p = os.path.join(FC, f"{f['assoc']}.csv")
    if not (os.path.exists(p) and time.time() - os.path.getmtime(p) < max_age_h * 3600 and os.path.getsize(p) > 0):
        lib = lib or J.Lib()
        b = lib.csv(f['isin'], f['assoc'])
        time.sleep(1.1)
        if b is None:
            return J.parse_csv(open(p, 'rb').read())[0] if os.path.exists(p) and os.path.getsize(p) > 0 else None
        open(p + '.tmp', 'wb').write(b)
        os.replace(p + '.tmp', p)
    return J.parse_csv(open(p, 'rb').read())[0]


def check_jumps(daily, key):
    """1日の (基準価額＋分配金)÷前日の基準価額 が JUMP_GUARD の外なら例外（分割・誤値を黙って月次にしない）"""
    for (d0, n0, _, _), (d1, n1, _, v1) in zip(daily, daily[1:]):
        if n0 > 0:
            q = (n1 + v1) / n0
            if not (JUMP_GUARD[0] < q < JUMP_GUARD[1]):
                raise RuntimeError(f'{key} の基準価額が {d0}→{d1} で {q:.3f} 倍（分割・誤値の疑い）＝止める')


def nav_months(key, max_age_h=12.0, lib=None):
    """→ ({yyyymm: 月次の総リターン}〔完了した月だけ＝その後の月の行がある月〕, 最後の行の日付, 最後の行から何日たったか)"""
    J = _J()
    daily = nav_daily(key, max_age_h, lib)
    if not daily:
        return {}, None, None
    check_jumps(daily, key)
    mon = J.monthly_tr(daily)
    last_d = daily[-1][0]
    last_m = last_d // 100
    age = (today() - datetime.date(last_d // 10000, last_d // 100 % 100, last_d % 100)).days
    return {m: v for m, v in mon.items() if m < last_m}, last_d, age


# ───────────────────────── 設計（登録前のデータだけ） ─────────────────────────
def active_hist(h, R):
    d = HYP[h]
    a, b = R[d['port']], R[d['bench']]
    ks = [k for k in sorted(set(a) & set(b)) if k <= DESIGN_END]
    return {k: a[k] - b[k] for k in ks}


def design(max_age_h=24.0):
    lib = _J().Lib()
    R = {k: nav_months(k, max_age_h, lib)[0] for k in FUNDS}
    out, hist = {}, {}
    for h in ORDER:
        if HYP[h]['mu_rule'][0] == 'same_as':
            continue
        x = active_hist(h, R)
        ms = sorted(x)
        v = [x[m] for m in ms]
        sd = S.stdev(v) * math.sqrt(12) * 100
        rule = HYP[h]['mu_rule']
        if rule[0] == 'insample':
            pre = S.mean(v) * 1200
            mu_d = min(MU_HI, max(MU_LO, MU_HAIRCUT * pre))
            src = f'{rule[1]} = {pre:+.3f}%/年 × {MU_HAIRCUT} → [{MU_LO}, {MU_HI}] に収める'
        else:
            mu_d = rule[1]
            src = f'fixed {mu_d}（{MU_LO}〜{MU_HI} の中・nx_forward の副と同じ）'
        sm = sd / 100 / math.sqrt(12)
        B = math.ceil(CLIP_K * sm / 0.005 - 1e-12) * 0.005
        lam_k = (mu_d / 100) / (sd / 100) ** 2
        lam = min(lam_k, 1 / (2 * B))
        a, b = HYP[h]['port'], HYP[h]['bench']
        geo_a = math.exp(sum(math.log1p(R[a][k]) for k in ms) * 12 / len(ms)) - 1
        geo_b = math.exp(sum(math.log1p(R[b][k]) for k in ms) * 12 / len(ms)) - 1
        out[h] = {'sigma_d': round(sd, 3), 'sigma_window': [ms[0], ms[-1]], 'n_months': len(ms),
                  'sigma_source': f"{FUNDS[a]['name']} − {FUNDS[b]['name']} の月次の差（基準価額の総リターン・円・信託報酬の後）",
                  'mu_d': round(mu_d, 3), 'mu_source': src, 'B': round(B, 4), 'lambda_kelly': round(lam_k, 4), 'lambda': round(lam, 4),
                  'lambda_capped': lam < lam_k, 'mu_f': round(mu_d, 3), 'clipped_months_hist': sum(1 for q in v if abs(q) > B),
                  'hist_mean_ann_pct': round(S.mean(v) * 1200, 3), 'hist_geo_ann_pct': {'port': round(100 * geo_a, 2), 'bench': round(100 * geo_b, 2),
                                                                                         'diff': round(100 * (geo_a - geo_b), 2)},
                  'hist_nw_t': round(N.nw_t(v), 2) if len(v) >= 24 else None}
        hist[h] = x
    for h in ORDER:
        if HYP[h]['mu_rule'][0] == 'same_as':
            src_h = HYP[h]['mu_rule'][1]
            out[h] = dict(out[src_h], mu_d=0.0, mu_f=None, mu_source=f'逆向き（μ0=0）・λ と B は {src_h} と同じ（futility は持たない）')
            hist[h] = {k: -v for k, v in hist[src_h].items()}
    return out, hist, R


# ───────────────────────── 前向き: 取り込みと e ─────────────────────────
def hyp_x(h, m, R):
    d = HYP[h]
    a, b = R[d['port']].get(m), R[d['bench']].get(m)
    if a is None or b is None:
        miss = [FUNDS[k]['name'] for k, v in ((d['port'], a), (d['bench'], b)) if v is None]
        return ('missing' if overdue(m) else 'wait'), None, {'why': '・'.join(miss) + ' の月次待ち（その後の月の基準価額の行が出てから）'}
    return 'ok', a - b, {'s': round(a, 6), 'b': round(b, 6)}


def evaluate(pr, prev, R, log):
    fz = pr['frozen']['design']
    last_done = addm(today_ym(), -1)
    target = months(FIRST_FWD, min(last_done, MAX_END)) if last_done >= FIRST_FWD else []
    res = {}
    for h in ORDER:
        P = fz[h]
        old = ((prev.get('hypotheses') or {}).get(h) or {}).get('forward') or {}
        locked = {r['m']: r for r in old.get('months', [])}
        rows, waiting, stopped = [], [], None
        for m in target:
            if m in locked:
                rows.append(locked[m]); continue
            if stopped:
                continue
            st, x, rec = hyp_x(h, m, R)
            if st == 'ok':
                rows.append({'m': m, 'x': round(x, 6), **rec, 'locked_on': today().isoformat()})
            elif st == 'missing':
                rows.append({'m': m, 'x': None, 'missing': True, 'note': rec.get('why'), 'locked_on': today().isoformat()})
            else:
                waiting.append({'m': m, 'why': rec.get('why')}); stopped = m
        used = [r for r in rows if r.get('x') is not None]
        # 逆向きの仮説は x を反転して同じ e過程に通す（『S&P500 − FANG+』の切り詰めた平均 ≤ 0 を帰無に）
        sign = -1.0 if HYP[h]['reverse'] else 1.0
        xs = [sign * r['x'] for r in used]
        line = LINES[HYP[h]['family']]
        e, path, first = NF.run_e(xs, P['lambda'], P['B'])
        _, _, first_fam = NF.run_e(xs, P['lambda'], P['B'], line=line)
        if P.get('mu_f') is not None:
            f, fpath, ffirst = NF.run_e(xs, P['lambda'], P['B'], P['mu_f'] / 100 / 12, reverse=True)
        else:
            f, fpath, ffirst = None, [None] * len(xs), None
        for r, ev, fv in zip(used, path, fpath):
            r['e' if not HYP[h]['reverse'] else 'e_rev'] = round(ev, 5)
            if fv is not None:
                r['f'] = round(fv, 5)
        n = len(xs)
        fw = {'n_months': n, 'first_month': used[0]['m'] if used else None, 'last_month': used[-1]['m'] if used else None,
              'e_now': round(e, 5), 'e_max': round(max(path), 5) if path else 1.0, 'line_individual': E_IND, 'line_family': line,
              'crossed_individual_at': used[first]['m'] if first is not None else None,
              'crossed_family_at': used[first_fam]['m'] if first_fam is not None else None,
              'futility_now': None if f is None else round(f, 5), 'futility_at': used[ffirst]['m'] if ffirst is not None else None,
              'mean_active_ann_pct': round(S.mean(xs) * 1200, 3) if n else None, 'clipped_months': sum(1 for q in xs if abs(q) > P['B']),
              'missing_months': [r['m'] for r in rows if r.get('missing')], 'waiting_for': waiting, 'months': rows,
              'cum_active_geo_pct': None}
        if n >= 12:
            lo, hi = NF.cs_bounds(xs, P['lambda'], P['B'])
            fw['cs_trimmed_mean_ann_pct'] = {'lower': lo, 'upper': hi}
        if used:
            gs = math.prod(1 + r['s'] for r in used)
            gb = math.prod(1 + r['b'] for r in used)
            fw['cum_active_geo_pct'] = round(((gb / gs) if HYP[h]['reverse'] else (gs / gb)) * 100 - 100, 3)
        fam = HYP[h]['family']
        if fw['crossed_family_at'] and fam == 'main':
            status = f'勝ち（主の線 e≥{line:g} に {fw["crossed_family_at"]} で到達）'
        elif fw['crossed_family_at']:
            status = f'副の族の線 e≥{line:g} に到達（{fw["crossed_family_at"]}）＝判定の族の外（報告）'
        elif fw['crossed_individual_at']:
            status = f'1本の線 e≥20 には到達（{fw["crossed_individual_at"]}）・副の族の線 {line:g} は未達＝報告だけ'
        elif fw['futility_at']:
            status = f'見込みなし（逆向きの e_f≥20 に {fw["futility_at"]} で到達＝設計の上乗せ μ_d={P["mu_d"]}%/年 は無い）・記録は続ける'
        elif last_done > MAX_END:
            status = '打ち切り（20年で未決＝証明できず）'
        else:
            status = '追跡中' if n else f'前向きの月はまだ無い（最初の月 {FIRST_FWD} は {addm(FIRST_FWD, 1) // 100}-{addm(FIRST_FWD, 1) % 100:02d} の最初の営業日の後に入る）'
        res[h] = {'definition': HYP[h]['ja'], 'family': fam, 'why': HYP[h]['why'], 'frozen': P, 'forward': fw, 'status': status}
    fams = {}
    for fam, hs in FAMILIES.items():
        ev = {h: res[h]['forward']['e_now'] for h in hs}
        fams[fam] = {'K': len(hs), 'line_bonferroni': LINES[fam], 'e_bh_rejected_now': NF.e_bh(ev),
                     'mean_e_now': round(sum(ev.values()) / len(ev), 5)}
    fams['cross_session_reference'] = {'K': len(ORDER) + CROSS_SESSION_K, 'line_bonferroni': E_IND * (len(ORDER) + CROSS_SESSION_K),
                                       'note': 'mw_forward（8本）・nx_forward（8本）と合わせた全セッションの線（参考）'}
    return res, fams


# ───────────────────────── 検出力（numpy・init だけ） ─────────────────────────
def power(des, hist, n=4000, years=40, block=12, seed=20261011):
    import numpy as np
    rng = np.random.default_rng(seed)
    T = years * 12
    out = {}
    for h in ORDER:
        P = des[h]
        x = np.array([hist[h][m] for m in sorted(hist[h])])
        dmean = x - x.mean()
        nb = -(-T // block)
        st = rng.integers(0, len(dmean), size=(n, nb))
        idx = ((st[:, :, None] + np.arange(block)[None, None, :]) % len(dmean)).reshape(n, nb * block)[:, :T]
        base = dmean[idx]
        B, lam = P['B'], P['lambda']
        muf = None if P.get('mu_f') is None else P['mu_f'] / 100 / 12
        line = LINES[HYP[h]['family']]
        rows = {}
        for mu in (-3.0, 0.0, 1.0, 3.0, 6.0, 10.0):
            xs = np.clip(base + mu / 100 / 12, -B, B)
            le = np.cumsum(np.log1p(lam * xs), axis=1)

            def first(mask):
                return np.where(mask.any(axis=1), mask.argmax(axis=1) + 1, 10 ** 6)
            f20, fl = first(le >= math.log(E_IND)), first(le >= math.log(line))
            r = {'p_cross20_by': {f'{y}y': round(float((f20 <= y * 12).mean()), 3) for y in (3, 5, 10, 20)},
                 'p_cross_family_line_by': {f'{y}y': round(float((fl <= y * 12).mean()), 3) for y in (5, 10, 20)},
                 'median_years_to_line': (round(float(np.median(fl)) / 12, 1) if float(np.median(fl)) <= T else f'>{years}'),
                 'oracle_years_6_over_IR2': round(6 / (mu / P['sigma_d']) ** 2, 1) if mu > 0 else None}
            if muf is not None:
                lf = np.cumsum(np.log1p(lam * (muf - xs)), axis=1)
                ff = first(lf >= math.log(E_IND))
                r['p_futility_by'] = {f'{y}y': round(float((ff <= y * 12).mean()), 3) for y in (5, 10, 20)}
            rows[f'{mu:g}'] = r
        need = {}
        sub = base[:1500]
        for yrs in (5, 10, 20):
            need[f'{yrs}y'] = '>30'
            for mu in [g / 2 for g in range(1, 61)]:
                xs = np.clip(sub[:, :yrs * 12] + mu / 100 / 12, -B, B)
                le = np.cumsum(np.log1p(lam * xs), axis=1)
                if float((le >= math.log(line)).any(axis=1).mean()) >= 0.5:
                    need[f'{yrs}y'] = mu
                    break
        out[h] = {'sigma_d': P['sigma_d'], 'lambda': lam, 'B': B, 'mu_d': P['mu_d'], 'line': line, 'hist_months_bootstrapped': len(x),
                  'by_true_edge_pct_per_year': rows, 'edge_needed_for_50pct_line_by_pct_per_year': need}
    return out


# ───────────────────────── 点検 ─────────────────────────
def selftest():
    import random
    ok = []
    rnd = random.Random(7)
    # 1) e過程は負にならない（λ ≤ 1/(2B) なら 1+λx̃ ≥ 0.5）
    lam, B = 1 / (2 * 0.1), 0.1
    xs = [rnd.choice([-1.0, 1.0]) * rnd.random() * 0.5 for _ in range(2000)]
    e, path, _ = NF.run_e(xs, lam, B)
    ok.append(('e は正のまま', min(path) > 0))
    # 2) Ville: 帰無（平均0）で e≥20 に達する割合は 5% 以下
    hits = 0
    for _ in range(2000):
        xs = [rnd.gauss(0, 0.05) for _ in range(240)]
        hits += NF.run_e(xs, 2.0, 0.1)[2] is not None
    ok.append((f'帰無で e≥20 に届いた割合 {hits / 2000:.3f} ≤ 0.05', hits / 2000 <= 0.05))
    # 3) 月の固定: 前の出力にある月は値が変わっても上書きしない
    os.environ['BFF_TODAY'] = '2027-03-10'
    fz = {'frozen': {'design': {h: {'lambda': 1.0, 'B': 0.1, 'mu_d': 3.0, 'mu_f': (None if HYP[h]['reverse'] else 3.0)} for h in ORDER}}}
    R = {k: {m: 0.01 for m in months(202610, 202702)} for k in FUNDS}
    R['FANG'] = {m: 0.03 for m in months(202610, 202702)}
    prev = {'hypotheses': {'G1_FANG_vs_SP500': {'forward': {'months': [{'m': 202611, 'x': -0.05, 's': -0.04, 'b': 0.01, 'locked_on': '2026-12-02'}]}}}}
    res, _ = evaluate(fz, prev, R, [])
    got = [r['x'] for r in res['G1_FANG_vs_SP500']['forward']['months']]
    ok.append((f'固定した月は動かない {got[:2]}', got[0] == -0.05 and abs(got[1] - 0.02) < 1e-12))
    # 4) 欠測: 値の無い月は3か月待つ（待つ間は先へ進まない）、それを過ぎたら欠測として飛ばし e を動かさない
    R2 = {k: dict(v) for k, v in R.items()}
    del R2['SP500'][202701]
    res2, _ = evaluate(fz, {}, R2, [])
    fw2 = res2['G1_FANG_vs_SP500']['forward']
    ok.append(('待つ間は先へ進まない', fw2['last_month'] == 202612 and fw2['waiting_for'] and fw2['waiting_for'][0]['m'] == 202701))
    os.environ['BFF_TODAY'] = '2027-06-10'
    R3 = {}
    for k in R2:
        R3[k] = dict(R2[k])
        for m in months(202703, 202705):
            R3[k][m] = 0.03 if k == 'FANG' else 0.01
    res3, _ = evaluate(fz, {}, R3, [])
    fw3 = res3['G1_FANG_vs_SP500']['forward']
    ok.append((f'3か月を過ぎた月は欠測 {fw3["missing_months"]}', fw3['missing_months'] == [202701] and fw3['last_month'] == 202705))
    # 5) 逆向きは x を反転して同じ e過程（FANG が勝つ月ばかりなら逆向きの e は下がる）
    ok.append(('逆向きの e は下がる', res3['G1r_SP500_vs_FANG']['forward']['e_now'] < 1.0 < res3['G1_FANG_vs_SP500']['forward']['e_now']))
    del os.environ['BFF_TODAY']
    # 6) 基準価額の跳びの検問
    try:
        check_jumps([(20260101, 10000, None, 0.0), (20260102, 1000, None, 0.0)], 'x')
        ok.append(('10分の1の跳びで止まる', False))
    except RuntimeError:
        ok.append(('10分の1の跳びで止まる', True))
    for nm, v in ok:
        print('OK ' if v else 'NG ', nm)
    if not all(v for _, v in ok):
        raise SystemExit(1)


# ───────────────────────── 出力 ─────────────────────────
def sha_of(path):
    try:
        return subprocess.run(['git', '-C', BASE, 'log', '-1', '--format=%H', '--', path], capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa
        return None


def tool_sha():
    return hashlib.sha256(open(os.path.abspath(__file__), 'rb').read()).hexdigest()


def load_prev():
    return json.load(open(OUT)) if os.path.exists(OUT) else {}


def write(obj):
    obj['generated'] = today().isoformat()
    N.save(OUT_NAME, obj)


CI_LINE = ("ops.yml の forward ジョブに1段（mw・nx と同じ形）: `python3 night/forward_run_mark.py bf started` → "
           "`timeout 600 python3 night/bf_forward.py update` → 印。出力 out/bf_forward.json を forward ジョブのコミットに足す。"
           "凍結の検査（out/forward_frozen.json に群 bf・night/check_forward_frozen.py の --group の選択肢）も同時に足す。"
           "★足すかはユーザーの判断（bestfund の事前登録 live_forward_test）")


def do_design():
    des, hist, R = design()
    print(json.dumps(des, ensure_ascii=False, indent=1))
    print('tool_sha256', tool_sha())


def do_init():
    pr = json.load(open(PREREG))
    fz = pr['frozen']
    t0 = time.time()
    des, hist, R = design()
    recheck = {h: {k: (fz['design'][h][k], des[h][k]) for k in ('sigma_d', 'mu_d', 'B', 'lambda')
                   if fz['design'][h][k] is not None and abs(float(fz['design'][h][k]) - float(des[h][k])) > 1e-6} for h in ORDER}
    log = []
    res, fams = evaluate(pr, {}, R, log)
    obj = {'angle': 'bf_forward', 'role': '前向きの検定（登録 2026-10-11・最初の月 2026-11）。読むだけ・門の判定・採点・配分には不使用',
           'prereg': 'out/bf_forward_prereg.json', 'prereg_commit': sha_of('out/bf_forward_prereg.json'),
           'first_forward_month': FIRST_FWD, 'max_end': MAX_END, 'review_month': REVIEW_MONTH,
           'rule': '主（G1）は e ≥ 20 に一度でも達したら『勝ち』。逆向きの e_f ≥ 20 で見込みなし（拘束しない）。副（G1r・G2・G3）は報告だけ（族の線 60）',
           'funds': FUNDS, 'hypotheses': res, 'families': fams, 'log': log,
           'design_recheck_vs_prereg': {h: v for h, v in recheck.items() if v},
           'power': power(fz['design'], hist),
           'ci_suggestion': CI_LINE, 'tool_sha256': tool_sha(), 'tool_sha256_matches_prereg': tool_sha() == fz.get('tool_sha256_at_registration'),
           'runtime_s': round(time.time() - t0, 1)}
    write(obj)
    report(obj)


def do_update():
    pr = json.load(open(PREREG))
    t0 = time.time()
    prev = load_prev()
    if not prev:
        raise SystemExit('先に init を回す')
    log = []
    lib = None
    R = {}
    for k in FUNDS:
        try:
            lib = lib or _J().Lib()
            R[k], last_d, age = nav_months(k, 6.0, lib)
            if age is not None and age > 10:
                log.append(f"{FUNDS[k]['name']}: 最後の基準価額の行 {last_d} から {age} 日（償還・取扱終了の疑い＝事前登録の止める決まりを確かめる）")
        except Exception as e:  # noqa
            R[k] = {}
            log.append(f"{FUNDS[k]['name']}: 取得の失敗 {type(e).__name__}: {e}（その月は待つ）")
    res, fams = evaluate(pr, prev, R, log)
    obj = dict(prev)
    obj.update({'hypotheses': res, 'families': fams, 'log': log, 'prereg_commit': sha_of('out/bf_forward_prereg.json'),
                'tool_sha256': tool_sha(), 'tool_sha256_matches_prereg': tool_sha() == pr['frozen'].get('tool_sha256_at_registration'),
                'runtime_s': round(time.time() - t0, 1)})
    write(obj)
    report(obj)


def report(obj):
    for h in ORDER:
        fw = obj['hypotheses'][h]['forward']
        fut = '—' if fw['futility_now'] is None else f"{fw['futility_now']:.3f}"
        print(f"{h:20s} 月数 {fw['n_months']:3d}  e={fw['e_now']:.3f}  e_f={fut}  {obj['hypotheses'][h]['status']}")
    for x in obj.get('log', [])[-8:]:
        print('  ', x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('step', choices=['design', 'init', 'update', 'selftest'])
    a = ap.parse_args()
    {'design': do_design, 'init': do_init, 'update': do_update, 'selftest': selftest}[a.step]()


if __name__ == '__main__':
    main()
