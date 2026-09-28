#!/usr/bin/env python3
"""night/nx_jpfunds.py — nx 角度 jpfunds の測定（読むだけ・門の判定には不使用）

日本の公募投信（追加型・ETF 除く）の株式の5分類（国内株式・米国株式・日本を除く世界・日本を含む世界・新興国）で、
毎年9月末に過去3年（5年）の分配金再投資の累積リターンが分類の中で上位1/4の能動の投信を等分で1年持つと、
同じ分類の指数型の投信（その時点で買えた器のうち今の信託報酬が最も安いもの）に勝つか（Carhart の持続の日本版）。

事前登録: out/nx_jpfunds_prereg.json（測る前に固定・書き換えない）／全体の線: out/nx_prereg.json（criteria_short_sample）
データと規則の台帳: night/nx_jpfunds_data.py（RULES・一覧・CSV・MSCI・JITA・三菱UFJ の償還ファンド）。
  universe_sha256・rules_sha256・extract_sha256 が事前登録と一致しなければ止まる。
統計・格付け: nx_common.excess_stats / p_one / holm / grade_short / sharpe / maxdd をそのまま使う。
  積立（dca）と転がる窓（rolling）は nx_common の関数が勝ちを**丸めた後**に数えるので、ここでは丸める前の値で勝ちを数える
  （nx_common と同じ窓の作り方を写した dca_raw / rolling_raw。数字の表示は nx_common と同じ丸め）。

使い方:
  python3 night/nx_jpfunds.py --checks   データの検査だけ（sha・生き残り・CSV の期間・相手の相関・為替の検査・重複の除去・外れ値）。成績は計算しない
  python3 night/nx_jpfunds.py            全規則を測って out/nx_jpfunds.json へ（tested に P2・C3・X4 と報告の族を1本残らず）
"""
import sys, os, json, math, collections, statistics as S, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import nx_common as N  # noqa: E402
import nx_jpfunds_data as D  # noqa: E402

PRE_P = os.path.join(N.BASE, 'out', 'nx_jpfunds_prereg.json')
OUT_NAME = 'nx_jpfunds.json'
CATS = ('JP', 'US', 'GLX', 'GLW', 'EM')
FOREIGN = ('US', 'GLX', 'GLW', 'EM')
END = D.CUTOFF // 100          # 202608
TAU = 0.20315                  # 課税口座（R4）
FX_MIN = 0.5                   # 為替の係数の閾値（RULES.universe_filter.fx_exposure_check）
DEDUPE_RHO = 0.995             # RULES.selection.share_class_dedupe
MIN_GROUP = 8                  # RULES.selection.min_group
BIG_NA = 10000.0               # X3: 100億円 = 10,000 百万円
RETENTION = 0.003              # RULES.costs.sell
LB_HIT = 0.30                  # RULES.lower_bound（q × 0.30）
LB_MILD = 0.10                 # RULES.lower_bound.mild_report
R9_FEE = 0.001                 # R9: ACWI − 0.10%/年
OUTLIER = 0.30                 # criteria.missing_rules.outliers


# ───────────────────────── 月の道具 ─────────────────────────
def ym_add(ym, k):
    y, m = divmod(ym, 100)
    t = y * 12 + m - 1 + k
    return (t // 12) * 100 + t % 12 + 1


def lookback(y, L):
    """振り返り: (y−L) 年10月 〜 y 年9月の L×12 か月（nx_jpfunds_data.show と同じ）"""
    return [ym_add((y - L) * 100 + 10, i) for i in range(L * 12)]


def holding(y):
    """保有: y 年10月 〜 翌9月（最後は 2025-10〜2026-08 の11か月）"""
    return [m for m in (ym_add(y * 100 + 10, i) for i in range(12)) if m <= END]


def hold_year(m):
    """月 m が属する保有年（10月始まり）"""
    return m // 100 if m % 100 >= 10 else m // 100 - 1


# ───────────────────────── 凍結の確認 ─────────────────────────
def verify(pre):
    want = {k: pre['tools'][k].split('（')[0].strip() for k in ('universe_sha256', 'rules_sha256', 'extract_sha256')}
    ex, n = D.extract_sha()
    got = {'universe_sha256': D.universe_sha(), 'rules_sha256': D.rules_sha(), 'extract_sha256': ex}
    bad = {k: (want[k], got[k]) for k in want if want[k] != got[k]}
    if bad:
        raise SystemExit(f'事前登録の凍結と違う → 止まる: {bad}')
    return {'verified': True, **got, 'n_csv': n}


# ───────────────────────── 読み込み ─────────────────────────
def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_library():
    u = D.load_universe()
    rows = u['rows']
    F = {}
    for r in rows:
        a = r['associFundCd']
        if not os.path.exists(D.nav_path(a)):
            continue
        daily = D.load_nav(a)
        F[a] = {'src': 'library', 'row': r, 'name': D.nfkc(r.get('fundNm')), 'cat': D.category(r), 'kind': D.kind(r),
                'ok': D.passes_filter(r), 'mgr': a[:2], 'daily': daily, 'mon': D.monthly_tr(daily),
                'na': D.month_end_net_assets(daily), 'fee': _f(r.get('trustReward')), 'sales_min': r.get('salesFeeMin'),
                'buy_max': _f(r.get('buyFee')), 'retention': r.get('retentionMoneyCd') != '1',
                'n_inst': r.get('nInstitutions') or 0, 'nisa_growth': r.get('nisaGrowthFlg') == '1', 'nisa_tsumitate': r.get('nisaFlg') == '1',
                'established': (r.get('establishedDate') or '')[:10]}
    return u, rows, F


def load_mufg_redeemed():
    sup = json.load(open(D.SUPPORT))
    out, info = {}, []
    for x in sup['mufg_redeemed']:
        if not x['cat'] or x['type'] != 'PublicFund':
            continue
        daily = D.load_mufg_daily(x['fund_cd'])
        rec = {'fund_cd': x['fund_cd'], 'assoc': x['assoc'], 'name': x['name'], 'cat': x['cat'], 'kind': x['kind'],
               'excluded_by_filter': x['excluded_by_filter'], 'redeemed': x['redeemed'],
               'first': daily[0][0] if daily else None, 'last': daily[-1][0] if daily else None}
        info.append(rec)
        if not daily or x['excluded_by_filter'] or x['kind'] != 'active':
            continue
        key = 'MUFGR:' + x['assoc']
        out[key] = {'src': 'mufg_redeemed', 'row': None, 'name': D.nfkc(x['name']), 'cat': x['cat'], 'kind': 'active', 'ok': True,
                    'mgr': x['assoc'][:2], 'daily': daily, 'mon': D.monthly_tr(daily), 'na': D.month_end_net_assets(daily),
                    'fee': None, 'sales_min': None, 'buy_max': None, 'retention': False, 'n_inst': 0,
                    'nisa_growth': False, 'nisa_tsumitate': False, 'established': x['setting_date'], 'redeemed': x['redeemed']}
    return out, info, sup


# ───────────────────────── MSCI と為替 ─────────────────────────
def load_msci():
    J = {c: D.msci_jpy(D.MSCI[c], ccy='JPY') for c in CATS}
    U = {c: D.msci_jpy(D.MSCI[c], ccy='USD') for c in CATS}
    fx = D.usdjpy_change()
    return J, U, fx


def fx_coef(mon, months, cat, U, fx):
    """振り返りの月だけで: ファンドの月次 = a + b1×MSCI(分類・米ドル・NETR) + b2×円/米ドルの変化 → b2"""
    ms = [m for m in months if m in mon and m in U[cat] and m in fx]
    if len(ms) < 12:
        return None
    y = np.array([mon[m] for m in ms])
    X = np.column_stack([np.ones(len(ms)), [U[cat][m] for m in ms], [fx[m] for m in ms]])
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    return float(b[2])


# ───────────────────────── 相手（指数型の器の鎖） ─────────────────────────
def comparator_chain(rows, F, cat, U, fx, min_inst=None):
    """選択の日 t（y 年9月）ごとに、t に月次がある（nx_jpfunds_data.show と同じ判定）指数型の候補のうち
    今の信託報酬が最も安いもの（同じなら設定が古いもの）。外国は為替の係数の検査（振り返り最大36か月・12か月未満は検査なし）を通るもの。
    y=2006 は履歴の最初の月が使えない（最初の日を含む月は捨てる）ので必ず MSCI の補欠になる（X2 の振り返り・R7 だけに効く）"""
    cands = D.comparator_candidates(rows, cat)
    if min_inst is not None:
        cands = [r for r in cands if (r.get('nInstitutions') or 0) >= min_inst]
    chain, fx_rej = {}, []
    for y in range(2006, 2026):
        t = y * 100 + 9
        alive = [r for r in cands if r['associFundCd'] in F and t in F[r['associFundCd']]['mon']]
        alive.sort(key=lambda r: (float(r.get('trustReward') or 9), r.get('establishedDate') or ''))
        pick = None
        for r in alive:
            a = r['associFundCd']
            if cat in FOREIGN:
                c = fx_coef(F[a]['mon'], lookback(y, 3), cat, U, fx)
                if c is not None and c < FX_MIN:
                    fx_rej.append({'year': y, 'assoc': a, 'name': F[a]['name'][:40], 'fx_coef': round(c, 3)})
                    continue
            pick = a
            break
        chain[y] = pick
    return chain, fx_rej


def chain_series(chain, F, cat, J):
    """鎖 → {月: 総リターン}・{月: 出どころ}。器にその月の値が無ければ MSCI（円・NETR）− 0.50%/12（fill を記録）"""
    out, src, fills = {}, {}, []
    for y in range(2006, 2026):
        c = chain.get(y)
        for m in holding(y):
            if c and m in F[c]['mon']:
                out[m], src[m] = F[c]['mon'][m], c
            else:
                out[m], src[m] = J[cat][m] - D.FALLBACK_FEE / 12, 'MSCI'
                if c:
                    fills.append((y, m, c))
    return out, src, fills


def index_ew_series(F, cat, U, fx):
    """R3: 分類の指数型の全部の等分（universe_filter を通る指数型・外国は為替の検査を通るもの）。選択の日 t に月次がある器で固定し、
    保有の月は値のある器だけで割り直す"""
    out, n_by_year = {}, {}
    idx = [a for a, f in F.items() if f['src'] == 'library' and f['cat'] == cat and f['kind'] == 'index' and f['ok']]
    for y in range(2006, 2026):
        t = y * 100 + 9
        mem = []
        for a in idx:
            if t not in F[a]['mon']:
                continue
            if cat in FOREIGN:
                c = fx_coef(F[a]['mon'], lookback(y, 3), cat, U, fx)
                if c is not None and c < FX_MIN:
                    continue
            mem.append(a)
        n_by_year[y] = len(mem)
        for m in holding(y):
            v = [F[a]['mon'][m] for a in mem if m in F[a]['mon']]
            if v:
                out[m] = sum(v) / len(v)
    return out, n_by_year


# ───────────────────────── 選択の土台（振り返り・為替・重複の除去） ─────────────────────────
def cum(mon, months):
    g = 1.0
    for m in months:
        g *= 1 + mon[m]
    return g - 1


def base_pool(F, pool_keys, y, L, U, fx, fx_mode='rule', dedupe_mode='rule'):
    """y 年9月の選択の日: 適格（能動・フィルター・5分類・L×12 か月そろう）→ 外国は為替の検査 → 同じ委託会社で相関 ≥0.995 を束ねる（純資産最大を残す）。
    fx_mode: 'rule'＝振り返りの月（事前登録どおり）／'36m'＝t までの最大36か月（事後の感度）／'none'＝為替の検査なし（事後の感度）"""
    months = lookback(y, L)
    fx_months = months if fx_mode == 'rule' else lookback(y, 3)
    t = y * 100 + 9
    res = {}
    for cat in CATS:
        elig = [a for a in pool_keys if F[a]['cat'] == cat and F[a]['kind'] == 'active' and F[a]['ok']
                and all(m in F[a]['mon'] for m in months)]
        hedged = []
        if cat in FOREIGN and fx_mode != 'none':
            keep = []
            for a in elig:
                c = fx_coef(F[a]['mon'], fx_months, cat, U, fx)
                if c is not None and c < FX_MIN:
                    hedged.append((a, round(c, 3)))
                else:
                    keep.append(a)
            elig = keep
        # 重複の除去（単連結）
        parent = {a: a for a in elig}

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        by_mgr = collections.defaultdict(list)
        for a in elig:
            by_mgr[F[a]['mgr']].append(a)
        for mg, lst in by_mgr.items():
            if len(lst) < 2:
                continue
            if dedupe_mode == 'rule':
                M = np.array([[F[a]['mon'][m] for m in months] for a in lst])
                C = np.corrcoef(M)
            else:   # 事後の感度: t までの最大36か月の共通の月（12か月未満なら振り返りの月）
                C = np.zeros((len(lst), len(lst)))
                for i in range(len(lst)):
                    for j in range(i + 1, len(lst)):
                        cm = [m for m in lookback(y, 3) if m in F[lst[i]]['mon'] and m in F[lst[j]]['mon']]
                        if len(cm) < 12:
                            cm = months
                        C[i, j] = N.corr([F[lst[i]]['mon'][m] for m in cm], [F[lst[j]]['mon'][m] for m in cm])
            for i in range(len(lst)):
                for j in range(i + 1, len(lst)):
                    if C[i, j] >= DEDUPE_RHO:
                        ri, rj = find(lst[i]), find(lst[j])
                        if ri != rj:
                            parent[ri] = rj
        groups = collections.defaultdict(list)
        for a in elig:
            groups[find(a)].append(a)
        after, clusters = [], []
        for g in groups.values():
            rep = max(g, key=lambda a: (F[a]['na'].get(t, -1.0) if F[a]['na'].get(t) is not None else -1.0, a))
            after.append(rep)
            if len(g) > 1:
                clusters.append({'kept': rep, 'members': sorted(g)})
        res[cat] = {'before_dedupe': len(elig), 'after': sorted(after), 'clusters': clusters, 'fx_hedged': hedged,
                    'score': {a: cum(F[a]['mon'], months) for a in after}}
    return res


def pick(F, pool, y, how, comp=None, L=3):
    """pool = base_pool の結果。how: top / bottom / cheap / all / ir / big / decile。min_group と ceil(n/4) を当てる"""
    t = y * 100 + 9
    out, diag = [], {}
    for cat in CATS:
        lst = list(pool[cat]['after'])
        if how == 'big':
            lst = [a for a in lst if (F[a]['na'].get(t) or 0) >= BIG_NA]
        n = len(lst)
        na = lambda a: F[a]['na'].get(t) if F[a]['na'].get(t) is not None else -1.0  # noqa: E731
        if n < MIN_GROUP:
            diag[cat] = {'n': n, 'k': 0, 'used': False}
            continue
        sc = pool[cat]['score']
        if how in ('top', 'big'):
            k = math.ceil(n / 4)
            sel = sorted(lst, key=lambda a: (-sc[a], -na(a), a))[:k]
        elif how == 'decile':
            k = max(2, math.ceil(n / 10))
            sel = sorted(lst, key=lambda a: (-sc[a], -na(a), a))[:k]
        elif how == 'bottom':
            k = math.ceil(n / 4)
            sel = sorted(lst, key=lambda a: (sc[a], -na(a), a))[:k]
        elif how == 'cheap':
            k = math.ceil(n / 4)
            fee = lambda a: F[a]['fee'] if F[a]['fee'] is not None else 99.0  # noqa: E731
            sel = sorted(lst, key=lambda a: (fee(a), -na(a), a))[:k]
        elif how == 'all':
            k = n
            sel = sorted(lst)
        elif how == 'ir':
            k = math.ceil(n / 4)
            months = lookback(y, L)
            ir = {}
            for a in lst:
                ex = [F[a]['mon'][m] - comp[cat][m] for m in months]
                sd = S.stdev(ex)
                ir[a] = S.mean(ex) / sd if sd > 0 else float('-inf')
            sel = sorted(lst, key=lambda a: (-ir[a], -na(a), a))[:k]
        else:
            raise ValueError(how)
        diag[cat] = {'n': n, 'k': k, 'used': True}
        out += sel
    return out, diag


# ───────────────────────── ポートフォリオ ─────────────────────────
def portfolio(F, hold, comp, a=None, z=END, exclude=frozenset(), cats=None):
    """hold = {y: [ファンド]}。月ごとに値のあるファンドで等分。s = ファンドの平均、b = 同じ重みの分類の相手の平均。
    戻り値: s, b, w = {月: {ファンド: 重み}}"""
    s, b, w = {}, {}, {}
    for y in sorted(hold):
        funds = [x for x in hold[y] if x not in exclude and (cats is None or F[x]['cat'] in cats)]
        for m in holding(y):
            if (a is not None and m < a) or m > z:
                continue
            have = [x for x in funds if m in F[x]['mon']]
            if not have:
                continue
            n = len(have)
            s[m] = sum(F[x]['mon'][m] for x in have) / n
            b[m] = sum(comp[F[x]['cat']][m] for x in have) / n
            w[m] = {x: 1 / n for x in have}
    return s, b, w


def sales_fee(F, x, med, which='min'):
    """購入時手数料（小数・税込）。今の販売会社の最小（salesFeeMin）×1.1。販売会社の情報が無い器は同じ分類×種類の中央値（欠測を0と読まない）"""
    if which == 'min':
        v = F[x]['sales_min']
    else:
        v = F[x]['buy_max']
    filled = False
    if v is None:
        v = med[(which, F[x]['cat'], F[x]['kind'])]
        filled = True
    return v / 100 * 1.1, filled


def costs(F, hold, w, chains, med, which='min', buy=True, sell=True):
    """RULES.costs: ファンド側・相手側の費用を {月: 小数} で返す（その月のポートフォリオの重みを掛ける）。
    ・購入: 保有に新しく入った器の最初の月（最初の年は全部）。・留保額: 保有から外れる器の最後の保有月に 0.3%（印があれば）。
    ・相手側: 分類の器（鎖）の単位で同じ規則（MSCI の補欠は費用なし）。最後の月（2026-08）に全部を売る費用は引かない（NISA の持ち続け）"""
    cs, cb = collections.defaultdict(float), collections.defaultdict(float)
    filled = set()
    log = {}
    ys = sorted(y for y in hold if any(m in w for m in holding(y)))
    prev_f, prev_c = set(), set()
    for i, y in enumerate(ys):
        ms = [m for m in holding(y) if m in w]
        if not ms:
            continue
        m0, m1 = ms[0], ms[-1]
        cur = set(x for x in hold[y] if any(x in w[m] for m in ms))
        nxt = set(hold[ys[i + 1]]) if i + 1 < len(ys) else None
        # 相手側の器: 分類ごとの重み
        cw0 = collections.defaultdict(float)
        cw1 = collections.defaultdict(float)
        for x, wt in w[m0].items():
            cw0[F[x]['cat']] += wt
        for x, wt in w[m1].items():
            cw1[F[x]['cat']] += wt
        cur_c = {chains[c].get(y) or f'MSCI:{c}' for c in cw0}
        nxt_c = None
        if nxt is not None:
            nxt_c = {chains[F[x]['cat']].get(ys[i + 1]) or f"MSCI:{F[x]['cat']}" for x in nxt}
        log[y] = {'n_held': len(cur), 'n_new_buy_fee': len(cur - prev_f) if buy else 0,
                  'n_leave_retention_candidates': len(cur - nxt) if nxt is not None else 0,
                  'n_leave_with_retention_flag': sum(1 for x in (cur - nxt) if F[x]['retention']) if nxt is not None else 0,
                  'comparator_new': sorted(i for i in cur_c - prev_c)}
        if buy:
            for x in cur - prev_f:
                if x in w[m0]:
                    fee, fl = sales_fee(F, x, med, which)
                    if fl:
                        filled.add(x)
                    cs[m0] += w[m0][x] * fee
            for c, wt in cw0.items():
                inst = chains[c].get(y) or f'MSCI:{c}'
                if inst not in prev_c and not inst.startswith('MSCI:'):
                    fee, fl = sales_fee(F, inst, med, which)
                    cb[m0] += wt * fee
        if sell and nxt is not None:
            for x in cur - nxt:
                if x in w[m1] and F[x]['retention']:
                    cs[m1] += w[m1][x] * RETENTION
            for c, wt in cw1.items():
                inst = chains[c].get(y) or f'MSCI:{c}'
                if inst not in nxt_c and not inst.startswith('MSCI:') and F[inst]['retention']:
                    cb[m1] += wt * RETENTION
        prev_f, prev_c = cur, cur_c
    costs.last_log = log
    return cs, cb, filled


def net(r, c):
    return {m: v - c.get(m, 0.0) for m, v in r.items()}


def lower(s, h_by_year, frac):
    return {m: v - h_by_year[hold_year(m)] * frac / 12 for m, v in s.items()}


def contributions(F, w, comp):
    con = collections.defaultdict(float)
    for m, ws in w.items():
        for x, wt in ws.items():
            con[x] += wt * (F[x]['mon'][m] - comp[F[x]['cat']][m])
    return con


def halves(s, b):
    ks = sorted(set(s) & set(b))
    n = len(ks)
    k = n // 2
    return (ks[0], ks[k - 1]), (ks[k], ks[-1])


# ───────────────────────── 窓（丸める前に勝ちを数える） ─────────────────────────
def rolling_raw(s, b, years=10, start_month=10):
    """nx_common.rolling と同じ窓（毎年 start_month 月起点・一括）。勝ちは丸める前の差で数える"""
    ks = sorted(set(s) & set(b))
    if not ks:
        return None
    out = []
    y0, last = ks[0] // 100, ks[-1]
    for y in range(y0, 2100):
        a = y * 100 + start_month
        z = (y + years) * 100 + start_month - 1 if start_month > 1 else (y + years - 1) * 100 + 12
        if z > last:
            break
        w = [k for k in ks if a <= k <= z]
        if len(w) < years * 12 * 0.97:
            continue
        gs = math.exp(math.fsum(math.log1p(s[k]) for k in w) / years) - 1
        gb = math.exp(math.fsum(math.log1p(b[k]) for k in w) / years) - 1
        out.append((y, (gs - gb) * 100))
    if not out:
        return None
    v = sorted(c for _, c in out)
    wk = min(out, key=lambda x: x[1])
    bs = max(out, key=lambda x: x[1])
    return {'windows': len(out), 'wins': sum(1 for _, c in out if c > 0), 'win_rate': round(sum(1 for _, c in out if c > 0) / len(out), 3),
            'median': round(v[len(v) // 2], 2), 'worst': [wk[0], round(wk[1], 2)], 'best': [bs[0], round(bs[1], 2)],
            'by_start': [[y, round(c, 3)] for y, c in out]}


def dca_raw(s, b, years=10, step=12):
    """nx_common.dca と同じ窓（毎月同額・step か月ごとに起点をずらす）。勝ちは丸める前の比で数える"""
    ks = sorted(set(s) & set(b))
    n = years * 12
    out = []
    for i in range(0, len(ks) - n + 1, step):
        w = ks[i:i + n]
        ws = wb = 0.0
        for k in w:
            ws = (ws + 1) * (1 + s[k])
            wb = (wb + 1) * (1 + b[k])
        out.append((w[0], ws / wb))
    if not out:
        return None
    v = sorted(r for _, r in out)
    wk = min(out, key=lambda x: x[1])
    bs = max(out, key=lambda x: x[1])
    return {'windows': len(out), 'win_rate': round(sum(1 for r in v if r > 1) / len(v), 3), 'median_ratio': round(v[len(v) // 2], 3),
            'worst': [wk[0], round(wk[1], 3)], 'best': [bs[0], round(bs[1], 3)], 'by_start': [[k, round(r, 4)] for k, r in out]}


# ───────────────────────── 課税口座（R4） ─────────────────────────
def taxed_mon(F, x, cache):
    if x not in cache:
        if x.startswith('MSCI:'):
            cache[x] = None
        else:
            cache[x] = D.monthly_tr([(d, nv, na, dv * (1 - TAU)) for d, nv, na, dv in F[x]['daily']])
    return cache[x]


def spell_gain_tax(F, x, m_start, m_end, series_fallback=None):
    """保有の続いた期間（m_start〜m_end）に、1円で買って分配金（税引後）を再投資した持ち分の、最後の月末の含み益への課税（持ち分に対する割合）。
    簿価 = 1 + 再投資した分配金（全額を普通分配金とみなす）。含み損は 0（損の繰り越し・通算はしない）"""
    if x.startswith('MSCI:') or series_fallback is not None:
        g = 1.0
        for m in sorted(series_fallback):
            if m_start <= m <= m_end:
                g *= 1 + series_fallback[m]
        return TAU * max(g - 1, 0) / g if g > 0 else 0.0
    z = m_end * 100 + 99
    rows = F[x]['daily']
    prev = [r for r in rows if r[0] < m_start * 100 + 1]
    if not prev:
        return 0.0
    nav0 = prev[-1][1]
    u, B = 1.0 / nav0, 1.0
    last_nav = nav0
    for d, nv, _, dv in rows:
        if d < m_start * 100 + 1 or d > z:
            continue
        if dv:
            cash = u * dv * (1 - TAU)
            B += cash
            u += cash / nv
        last_nav = nv
    V = u * last_nav
    return TAU * max(V - B, 0) / V if V > 0 else 0.0


def taxed_portfolio(F, hold, comp_src, comp, chains, J):
    """R4 課税口座: 分配金に 20.315%（払った日）・外れた器の含み益に 20.315%（外れる月）・最後の月に全部売る。相手も同じ"""
    cache = {}
    s, b, w = {}, {}, {}
    closed = collections.defaultdict(float)
    closed_b = collections.defaultdict(float)
    ys = sorted(hold)
    for i, y in enumerate(ys):
        for m in holding(y):
            have = [x for x in hold[y] if m in F[x]['mon']]
            if not have:
                continue
            n = len(have)
            sv, bv = 0.0, 0.0
            for x in have:
                tm = taxed_mon(F, x, cache)
                sv += tm.get(m, F[x]['mon'][m]) / n
                cat = F[x]['cat']
                inst = chains[cat].get(y) or f'MSCI:{cat}'
                if inst.startswith('MSCI:') or comp_src[cat][m] == 'MSCI':
                    bv += comp[cat][m] / n
                else:
                    tc = taxed_mon(F, inst, cache)
                    bv += tc.get(m, comp[cat][m]) / n
            s[m], b[m] = sv, bv
            w[m] = {x: 1 / n for x in have}
    # 期間（spell）を作って、外れる月・最後の月に含み益への課税を引く
    months = sorted(w)
    held_f = collections.defaultdict(list)
    held_c = collections.defaultdict(list)
    cw = {}
    for m in months:
        y = hold_year(m)
        cwm = collections.defaultdict(float)
        for x, wt in w[m].items():
            held_f[x].append(m)
            cat = F[x]['cat']
            inst = chains[cat].get(y) or f'MSCI:{cat}'
            cwm[(inst, cat)] += wt
        for k in cwm:
            held_c[k].append(m)
        cw[m] = cwm

    def spells(ms):
        out, cur = [], [ms[0]]
        for m in ms[1:]:
            if m == ym_add(cur[-1], 1):
                cur.append(m)
            else:
                out.append(cur)
                cur = [m]
        out.append(cur)
        return out
    for x, ms in held_f.items():
        for sp in spells(ms):
            tax = spell_gain_tax(F, x, sp[0], sp[-1])
            closed[sp[-1]] += w[sp[-1]][x] * tax
    for (inst, cat), ms in held_c.items():
        for sp in spells(ms):
            if inst.startswith('MSCI:'):
                tax = spell_gain_tax(F, inst, sp[0], sp[-1], series_fallback={m: comp[cat][m] for m in sp})
            else:
                tax = spell_gain_tax(F, inst, sp[0], sp[-1])
            closed_b[sp[-1]] += cw[sp[-1]][(inst, cat)] * tax
    return net(s, closed), net(b, closed_b)


# ───────────────────────── 検査（成績は計算しない） ─────────────────────────
def checks(pre, rows, F, J, U, fx, chains, chain_rej, mufg_info, sup):
    out = {}
    # 生き残りだけであること
    out['redemption_all_after_snapshot'] = all(str(r.get('redemptionDate') or '99999999') > '20260928' for r in rows)
    out['min_redemptionDate'] = min(str(r.get('redemptionDate') or '99999999') for r in rows)
    # CSV の期間
    firsts = [f['daily'][0][0] for f in F.values() if f['src'] == 'library' and f['daily']]
    lasts = [f['daily'][-1][0] for f in F.values() if f['src'] == 'library' and f['daily']]
    out['csv_first_min'] = min(firsts)
    out['csv_last_max'] = max(lasts)
    out['csv_first_all_on_or_after_20060929'] = min(firsts) >= 20060929
    out['csv_no_rows_after_cutoff'] = max(lasts) <= D.CUTOFF
    # 相手の鎖が事前登録の割り当て（為替の検査の前）と一致するか
    want = pre['data']['shape']['comparator_assignment_before_fx_check']
    mism = []
    for cat in CATS:
        for ys, txt in want[cat]['by_selection_year_before_fx_check'].items():
            y = int(ys)
            got = chains[cat].get(y)
            exp = None if txt.startswith('MSCI') else txt.split()[0]
            if got != exp:
                mism.append({'cat': cat, 'year': y, 'prereg': txt[:50], 'got': got})
    out['comparator_chain_matches_prereg_assignment'] = not mism
    out['comparator_chain_mismatches'] = mism
    out['comparator_fx_rejected'] = chain_rej
    # 相手の器と MSCI（円）の相関（保有の月）
    cc = []
    for cat in CATS:
        insts = collections.defaultdict(list)
        for y in range(2007, 2026):
            c = chains[cat].get(y)
            if c:
                insts[c] += [m for m in holding(y) if m in F[c]['mon']]
        for c, ms in insts.items():
            r = N.corr([F[c]['mon'][m] for m in ms], [J[cat][m] for m in ms]) if len(ms) > 3 else None
            allm = [m for m in F[c]['mon'] if m in J[cat]]
            ra = N.corr([F[c]['mon'][m] for m in allm], [J[cat][m] for m in allm]) if len(allm) > 3 else None
            cc.append({'cat': cat, 'assoc': c, 'name': F[c]['name'][:40], 'months': len(ms), 'corr_with_msci_jpy': round(r, 4) if r is not None else None,
                       'ok_ge_0.90': bool(r is not None and r >= 0.90),
                       'months_full_history': len(allm), 'corr_full_history': round(ra, 4) if ra is not None else None})
    out['comparator_corr_msci'] = cc
    out['comparator_corr_all_ok'] = all(x['ok_ge_0.90'] for x in cc)
    # 為替の検査が効くこと: 名前にヘッジありの外国の器（除外済み）に通すと 0.5 未満
    tests = []
    for a, f in F.items():
        if f['src'] != 'library' or f['cat'] not in FOREIGN or f['kind'] not in ('active', 'index'):
            continue
        fl = D.flags(f['row'])
        if not fl['hedged'] or fl['dc_only'] or fl['wrap_only']:
            continue
        ms = sorted(f['mon'])[-36:]
        if len(ms) < 36:
            continue
        c = fx_coef(f['mon'], ms, f['cat'], U, fx)
        tests.append({'assoc': a, 'name': f['name'][:40], 'cat': f['cat'], 'fx_coef_last36': round(c, 3) if c is not None else None})
    tests.sort(key=lambda x: x['assoc'])
    out['fx_check_on_name_hedged'] = {'n': len(tests), 'n_below_0.5': sum(1 for x in tests if x['fx_coef_last36'] is not None and x['fx_coef_last36'] < FX_MIN),
                                      'examples_first12': tests[:12], 'above_0.5': [x for x in tests if x['fx_coef_last36'] is not None and x['fx_coef_last36'] >= FX_MIN]}
    # 外れ値（ファンドの月次と MSCI 円の差が 30% 以上）: 5分類の能動・指数型（フィルターを通るもの）
    outl = []
    for a, f in F.items():
        if f['cat'] not in CATS or not f['ok']:
            continue
        for m, v in f['mon'].items():
            if m in J[f['cat']] and abs(v - J[f['cat']][m]) >= OUTLIER:
                outl.append({'fund': a, 'name': f['name'][:40], 'src': f['src'], 'cat': f['cat'], 'kind': f['kind'], 'month': m,
                             'r': round(v, 4), 'msci_jpy': round(J[f['cat']][m], 4)})
    out['outliers_ge_30pct_vs_msci'] = sorted(outl, key=lambda x: (x['fund'], x['month']))
    # lower_bound の h_y が事前登録の表と一致すること
    js = sup['jita_survival']
    h = {y: js[str(y - 1)]['q_per_year'] * LB_HIT * 100 for y in range(2006, 2026)}
    tab = pre['criteria']['lower_bound_values_before_results']
    out['lower_bound_matches_prereg'] = all(abs(round(h[int(y)], 2) - v) < 0.006 for y, v in tab.items())
    out['lower_bound_h'] = {y: round(v, 3) for y, v in h.items()}
    # 三菱UFJ の償還ファンドの全履歴の最後の日が償還日の前後5営業日（7暦日）に入ること
    mu = []
    for x in mufg_info:
        if x['last'] is None:
            mu.append({'assoc': x['assoc'], 'ok': False, 'why': '履歴なし'})
            continue
        rd = datetime.date(int(x['redeemed'][:4]), int(x['redeemed'][4:6]), int(x['redeemed'][6:8]))
        ld = D._ymd(x['last'])
        mu.append({'assoc': x['assoc'], 'cat': x['cat'], 'kind': x['kind'], 'excluded_by_filter': x['excluded_by_filter'],
                   'redeemed': x['redeemed'], 'last': x['last'], 'days': (rd - ld).days, 'ok': abs((rd - ld).days) <= 7})
    out['mufg_last_day_near_redemption'] = {'n': len(mu), 'n_ok': sum(1 for x in mu if x['ok']), 'not_ok': [x for x in mu if not x['ok']]}
    return out


# ───────────────────────── 1本の規則を測る ─────────────────────────
def raw_diff(s, b, a=None, z=None):
    """丸める前の幾何の年率差（%）。excess_stats の cagr_diff は小数2桁に丸めるので、0 の近くの符号の確認用"""
    ks = sorted(k for k in set(s) & set(b) if (a is None or k >= a) and (z is None or k <= z))
    if not ks:
        return None
    return (N.cagr([s[k] for k in ks]) - N.cagr([b[k] for k in ks])) * 100


def stats_block(s, b, a=None, z=None):
    return N.excess_stats(s, b, a, z)


def measure_rule(rid, family, desc, F, hold, comp, chains, comp_src, med, h_lb, J, sel_diag, eval_from):
    s, b, w = portfolio(F, hold, comp, a=eval_from)
    ks = sorted(set(s) & set(b))
    full = stats_block(s, b)
    (a1, z1), (a2, z2) = halves(s, b)
    fh, sh = stats_block(s, b, a1, z1), stats_block(s, b, a2, z2)
    cs, cb, filled = costs(F, hold, w, chains, med, 'min')
    cost_log = costs.last_log
    s_c, b_c = net(s, cs), net(b, cb)
    cost_full = stats_block(s_c, b_c)
    s_lb = lower(s, h_lb, LB_HIT)
    lb = stats_block(s_lb, b)
    con = contributions(F, w, comp)
    top = max(con, key=lambda x: con[x])
    s_d, b_d, _ = portfolio(F, hold, comp, a=eval_from, exclude={top})
    drop = stats_block(s_d, b_d)
    yrs = len(ks) / 12
    rank_con = sorted(con.items(), key=lambda x: -x[1])
    rec = {
        'id': rid, 'family': family, 'desc': desc, 'window': [ks[0], ks[-1]], 'months': len(ks),
        'halves_windows': [[a1, z1], [a2, z2]],
        'full': full, 'first_half': fh, 'second_half': sh,
        'train': None, 'train_note': '履歴は 2006-09-29 から＝2006 年以前の訓練期間が無い（短い標本の格付け・事前登録 criteria.which）',
        'hold_2007on': stats_block(s, b, 200701), 'recent_2013_07on': stats_block(s, b, N.RECENT_START),
        'cost': {'rule': 'RULES.costs（購入時手数料＝今の販売会社の最小×1.1 を組み入れの月・留保額の印があれば外れる月に0.3%・相手も同じ）',
                 'after_cost_full': cost_full, 'after_cost_first_half': stats_block(s_c, b_c, a1, z1), 'after_cost_second_half': stats_block(s_c, b_c, a2, z2),
                 'cost_drag_fund_ann_pct': round(sum(cs.values()) / yrs * 100, 3), 'cost_drag_comparator_ann_pct': round(sum(cb.values()) / yrs * 100, 3),
                 'funds_with_sales_fee_filled_by_median': sorted(filled), 'by_year_log': cost_log},
        'lower_bound': lb, 'lower_bound_rule': 'RULES.lower_bound（保有年 y の各月の超過から h_y/12・h_y = q_(y−1)×0.30）',
        'lower_bound_plus_cost': stats_block(lower(s_c, h_lb, LB_HIT), b_c),
        'drop_top': {'dropped': top, 'dropped_name': F[top]['name'][:50], 'dropped_cat': F[top]['cat'],
                     'contrib_ann_pct': round(con[top] / yrs * 100, 3), 'stats': drop,
                     'top5_contrib_ann_pct': [[x, F[x]['name'][:30], F[x]['cat'], round(v / yrs * 100, 3)] for x, v in rank_con[:5]],
                     'bottom5_contrib_ann_pct': [[x, F[x]['name'][:30], F[x]['cat'], round(v / yrs * 100, 3)] for x, v in rank_con[-5:]]},
        'roll20': None, 'dca20_ratio': None,
        'roll20_dca20_note': '評価の期間が 20 年に満たない（最長 2007-10〜2026-08 の約19年）ので 20 年窓・20 年積立は取れない。10 年は報告（事前登録 R6）',
        'roll10_report': rolling_raw(s, b, 10), 'dca10_ratio_report_R6': dca_raw(s, b, 10),
        'dca10_ratio_after_cost_report': dca_raw(s_c, b_c, 10),
        'maxdd': {'rule': round(N.maxdd(s) * 100, 1), 'bench': round(N.maxdd(b) * 100, 1), 'rule_after_cost': round(N.maxdd(s_c) * 100, 1)},
        'sharpe': {'rule': N.sharpe(s, {m: 0.0 for m in s}), 'bench': N.sharpe(b, {m: 0.0 for m in b}),
                   'rule_after_cost': N.sharpe(s_c, {m: 0.0 for m in s_c}), 'bench_after_cost': N.sharpe(b_c, {m: 0.0 for m in b_c}),
                   'note': '無リスク金利 0（円の短期金利は 2009〜2023 年ほぼ 0）。重ねる・借入・時期選びの型ではない＝C8 は該当なし（報告のみ）'},
        'selection_by_year': sel_diag,
        'cagr_diff_unrounded_pct': {k: raw_diff(ss, bb, aa, zz) for k, (ss, bb, aa, zz) in {
            'full': (s, b, None, None), 'first_half': (s, b, a1, z1), 'second_half': (s, b, a2, z2),
            'after_cost_full': (s_c, b_c, None, None), 'lower_bound': (s_lb, b, None, None), 'drop_top': (s_d, b_d, None, None)}.items()},
        'n_distinct_funds_held': len({x for y in hold for x in hold[y]}),
    }
    return rec, (s, b, w, s_c, b_c)


def grade_rec(rec, holm_p):
    g, c = N.grade_short(rec['full'], rec['first_half'], rec['second_half'], rec['drop_top']['stats'],
                         rec['cost']['after_cost_full'], rec['lower_bound'], holm_p)
    rec['grade'] = g
    rec['criteria_short'] = c
    rec['holm_p_one'] = holm_p
    gl, cl = N.grade(rec['full'], None, rec['hold_2007on'], None, rec['cost']['after_cost_full'], None, None, None, False)
    rec['criteria_long_reference'] = {'grade_if_long_history_rules': gl, 'C': cl,
                                      'note': '参考のみ（格付けに使わない）。事前登録は criteria_short_sample（grade_short）を決めた。訓練期間（〜2006）が無く C1 は構造的に不合格、20年窓（C4）も取れない。C5 は短い標本に無い（R1 で分類ごとの向きを見る）、C7 は族の Holm を渡していない、C8 は型に該当しない'}
    return rec


# ───────────────────────── 本体 ─────────────────────────
def run(checks_only=False):
    pre = json.load(open(PRE_P))
    ver = verify(pre)
    print('凍結の確認 OK', ver, file=sys.stderr)
    u, rows, F = load_library()
    J, U, fx = load_msci()
    R, mufg_info, sup = load_mufg_redeemed()
    FA = dict(F)
    FA.update(R)
    # 相手の鎖
    chains, chain_rej, comp, comp_src, fills = {}, [], {}, {}, {}
    for cat in CATS:
        chains[cat], rj = comparator_chain(rows, F, cat, U, fx)
        chain_rej += [dict(x, cat=cat) for x in rj]
        comp[cat], comp_src[cat], fills[cat] = chain_series(chains[cat], F, cat, J)
    chk = checks(pre, rows, F, J, U, fx, chains, chain_rej, mufg_info, sup)
    if checks_only:
        print(json.dumps(chk, ensure_ascii=False, indent=1, default=str))
        return
    # 手数料の中央値（販売会社の情報が無い器の置き値）
    med = {}
    for which, key in (('min', 'sales_min'), ('max', 'buy_max')):
        for cat in CATS:
            for kd in ('active', 'index'):
                v = [f[key] for f in F.values() if f['src'] == 'library' and f['cat'] == cat and f['kind'] == kd and f['ok'] and f[key] is not None]
                med[(which, cat, kd)] = S.median(v) if v else 0.0
    js = sup['jita_survival']
    h_lb = {y: js[str(y - 1)]['q_per_year'] for y in range(2006, 2026)}
    lib_keys = [a for a, f in F.items() if f['src'] == 'library']

    # ── 選択の土台
    pools = {}
    for L, ys in ((1, range(2007, 2026)), (3, range(2009, 2026)), (5, range(2011, 2026))):
        for y in ys:
            pools[(L, y)] = base_pool(F, lib_keys, y, L, U, fx)
    RULESET = [
        ('P1_top_q_3y', 'P', 3, 'top', 2009, '振り返り3年・上位1/4・12か月保有・5分類をまとめて・相手は分類ごとの指数型の投信'),
        ('P2_top_q_5y', 'P', 5, 'top', 2011, '振り返り5年・上位1/4・同じ'),
        ('C1_cheap_q_fee', 'C', 3, 'cheap', 2009, '（対照）同じ適格のうち今の信託報酬が安い1/4（★今の信託報酬で過去を選ぶ後知恵）'),
        ('C2_all_active', 'C', 3, 'all', 2009, '（対照）同じ適格の能動の投信を全部等分'),
        ('C3_bottom_q_3y', 'C', 3, 'bottom', 2009, '（対照）振り返り3年の下位1/4'),
        ('X1_top_q_1y', 'X', 1, 'top', 2007, '（探索）振り返り1年・上位1/4（Carhart 1997 の元の形）'),
        ('X2_top_q_3y_ir', 'X', 3, 'ir', 2009, '（探索）振り返り3年の情報比（相手に対する月次の超過の平均÷標準偏差）の上位1/4'),
        ('X3_top_q_3y_big', 'X', 3, 'big', 2009, '（探索）P1 と同じだが t の純資産 100億円以上だけで並べる'),
        ('X4_top_d_3y', 'X', 3, 'decile', 2009, '（探索）振り返り3年の上位1/10（最低2本）'),
    ]
    holds, diags = {}, {}
    for rid, fam, L, how, y0, desc in RULESET:
        hold, dg = {}, {}
        for y in range(y0, 2026):
            sel, d = pick(F, pools[(L, y)], y, how, comp=comp, L=L)
            hold[y] = sel
            dg[y] = {c: dict(d[c], before_dedupe=pools[(L, y)][c]['before_dedupe'], fx_hedged=len(pools[(L, y)][c]['fx_hedged']),
                             clusters=len(pools[(L, y)][c]['clusters'])) for c in CATS}
        holds[rid], diags[rid] = hold, dg
    # 検査: 選ばれた本数 = k、使わない分類からは選ばない、min_group
    sel_err = []
    for rid, fam, L, how, y0, desc in RULESET:
        for y in range(y0, 2026):
            sel = holds[rid][y]
            for cat in CATS:
                d = diags[rid][y][cat]
                ncat = sum(1 for x in sel if F[x]['cat'] == cat)
                if (d['used'] and (ncat != d['k'] or d['n'] < MIN_GROUP)) or (not d['used'] and ncat):
                    sel_err.append({'rule': rid, 'year': y, 'cat': cat, 'diag': d, 'n_selected': ncat})
    chk['selection_counts_ok'] = not sel_err
    chk['selection_count_errors'] = sel_err
    ex = []
    for y in (2009, 2017, 2025):
        for cat in CATS:
            for cl in pools[(3, y)][cat]['clusters'][:2]:
                ex.append({'year': y, 'cat': cat, 'kept': cl['kept'], 'members': [[a, F[a]['name'][:50]] for a in cl['members']]})
    chk['dedupe_examples_L3'] = ex
    chk['dedupe_clusters_by_year'] = {f'L{L}': {y: {cat: len(pools[(L, y)][cat]['clusters']) for cat in CATS} for (LL, y) in pools if LL == L}
                                      for L in (1, 3, 5)}
    chk['fx_hedged_by_year'] = {f'L{L}': {y: {cat: len(pools[(L, y)][cat]['fx_hedged']) for cat in FOREIGN} for (LL, y) in pools if LL == L}
                                for L in (1, 3, 5)}
    chk['fx_hedged_examples_L3_2025'] = {cat: [[a, F[a]['name'][:50], c] for a, c in pools[(3, 2025)][cat]['fx_hedged'][:8]] for cat in FOREIGN}
    chk['outlier_decision'] = ('外れ値の12か月はどれもデータの誤りではない（SOX の 2026-04 は別の委託会社の SOX の器4本が同じ +43.8〜43.9%・'
                               'テトラ・エクイティの 2020-03 と SMT 全世界株式モメンタムの 2026-07 は日次の基準価額が連続して動いており口数の単位の変更や分割の跳びが無い・'
                               '金鉱株の 2016-02・VR と ブロックチェーンの 2021-01/02 もテーマの実際の値動き）ので、値なしにしたものは無い')
    chk['hedged_regex_false_positive'] = ('RULES の hedged_regex の『ヘッジ型』が『為替ノーヘッジ型』にも当たる: 5分類で1本（79312141 三井住友・NYダウ・ジョーンズ・インデックスファンド(為替ノーヘッジ型)・'
                                          '米国の指数型）がヘッジありとして外れる。RULES は凍結なのでそのまま（相手の候補ではない〔名前に S&P500 が無い〕ので主の相手には効かない・R3 の指数型の全部の等分から1本抜けるだけ）')
    chk['comparator_corr_note'] = ('新興国の2本（たわらノーロード新興国株式 2016-10〜2017-09・eMAXIS Slim 新興国株式 2017-10〜2018-09）の保有の12か月の相関が 0.90 を下回った。'
                                   '同じ月の別の新興国の指数型（02311084）とたわらの相関は 0.999、02311084 と MSCI の相関も同じ12か月で 0.28（Slim の12か月では 0.90）＝器・分類の誤りではなく、'
                                   '新興国が静かに上がり続けた年のばらつきの小ささと、外国の投信の基準価額が1日遅れ（timing.look_ahead_known）で月末の MSCI とずれることによる。'
                                   '全履歴の相関（corr_full_history）はどれも 0.90 以上。直すものは無い')
    recs, series = {}, {}
    for rid, fam, L, how, y0, desc in RULESET:
        rec, ser = measure_rule(rid, fam, desc, F, holds[rid], comp, chains, comp_src, med, h_lb, J, diags[rid], y0 * 100 + 10)
        rec['lookback_years'] = L
        rec['benchmark'] = '分類ごとの指数型の投信の鎖（RULES.comparator）・円・費用後の本物の器'
        recs[rid], series[rid] = rec, ser
    # Holm（族ごと・片側 p）
    holm = {}
    for fam in ('P', 'C', 'X'):
        ps = {rid: N.p_one(recs[rid]['full']['t']) for rid, f, *_ in RULESET if f == fam}
        adj = N.holm(ps)
        holm[fam] = {'p_one': {k: round(v, 5) for k, v in ps.items()}, 'holm': adj}
        for rid in ps:
            grade_rec(recs[rid], adj[rid])
    # ── 報告の族
    rep = {}
    # R1 分類ごと
    r1 = {}
    for rid in ('P1_top_q_3y', 'P2_top_q_5y', 'C1_cheap_q_fee', 'C2_all_active'):
        r1[rid] = {}
        y0 = [x for x in RULESET if x[0] == rid][0][4]
        for cat in CATS:
            s, b, w = portfolio(F, holds[rid], comp, a=y0 * 100 + 10, cats={cat})
            st = N.excess_stats(s, b) if len(s) >= 24 else None
            r1[rid][cat] = {'stats': st, 'months': len(s), 'first': min(s) if s else None}
    rep['R1_by_category'] = r1
    # R2 上位 − 下位
    sP1, sC3 = series['P1_top_q_3y'][0], series['C3_bottom_q_3y'][0]
    rep['R2_spread_P1_minus_C3'] = {'stats': N.excess_stats(sP1, sC3), 'first_half': N.excess_stats(sP1, sC3, *halves(sP1, sC3)[0]),
                                    'second_half': N.excess_stats(sP1, sC3, *halves(sP1, sC3)[1])}
    # R3 相手の感度
    msci_c = {cat: dict(J[cat]) for cat in CATS}
    ew_c, ew_n = {}, {}
    for cat in CATS:
        ew_c[cat], ew_n[cat] = index_ew_series(F, cat, U, fx)
        # 値の無い月は MSCI − 0.5% で埋める（主の相手と同じ補欠）
        for y in range(2006, 2026):
            for m in holding(y):
                if m not in ew_c[cat]:
                    ew_c[cat][m] = J[cat][m] - D.FALLBACK_FEE / 12
    inst5_c, inst5_chain = {}, {}
    for cat in CATS:
        inst5_chain[cat], _ = comparator_chain(rows, F, cat, U, fx, min_inst=5)
        inst5_c[cat], _, _ = chain_series(inst5_chain[cat], F, cat, J)
    r3 = {'comparator_ew_all_index_n_by_year': ew_n,
          'comparator_nInst5_chain': {c: {y: inst5_chain[c].get(y) for y in range(2007, 2026)} for c in CATS}}
    for rid, fam, L, how, y0, desc in RULESET:
        a = y0 * 100 + 10
        out = {}
        for nm, cc in (('msci_jpy_netr_no_cost', msci_c), ('ew_all_index_funds', ew_c), ('nInstitutions_ge_5', inst5_c)):
            s, b, _ = portfolio(F, holds[rid], cc, a=a)
            out[nm] = {'full': N.excess_stats(s, b), 'first_half': N.excess_stats(s, b, *halves(s, b)[0]), 'second_half': N.excess_stats(s, b, *halves(s, b)[1])}
        r3[rid] = out
    rep['R3_paper_and_comparator_sensitivity'] = r3
    # R4 費用の版
    r4 = {}
    for rid, fam, L, how, y0, desc in RULESET:
        s, b, w, _, _ = series[rid]
        cs, cb, _ = costs(F, holds[rid], w, chains, med, 'max')
        cs2, cb2, _ = costs(F, holds[rid], w, chains, med, 'min', buy=False)
        st, bt = taxed_portfolio(F, {y: v for y, v in holds[rid].items()}, comp_src, comp, chains, J)
        st = {m: v for m, v in st.items() if m >= y0 * 100 + 10}
        bt = {m: v for m, v in bt.items() if m >= y0 * 100 + 10}
        r4[rid] = {'buy_fee_upper_x1.1_plus_retention': N.excess_stats(net(s, cs), net(b, cb)),
                   'no_buy_fee_retention_only': N.excess_stats(net(s, cs2), net(b, cb2)),
                   'no_fees_at_all_equals_full': recs[rid]['full'],
                   'taxable_account': N.excess_stats(st, bt),
                   'taxable_note': '分配金は払った日に 20.315%（全額を普通分配金とみなす）・外れた器と最後の月（2026-08）の全部の含み益に 20.315%（含み損の通算なし）。'
                                   '月ごとの等分への持ち直しの売買の課税は数えない（近似）。販売手数料は引かない（主の費用の版と重ねていない）'}
    rep['R4_costs'] = r4
    # R5 下限（ゆるい）
    rep['R5_lower_mild'] = {rid: N.excess_stats(lower(series[rid][0], h_lb, LB_MILD), series[rid][1]) for rid in recs}
    # R6 積立（10年）は各規則の rec に
    rep['R6_dca10'] = {rid: {'pre_cost': recs[rid]['dca10_ratio_report_R6'], 'after_cost': recs[rid]['dca10_ratio_after_cost_report']} for rid in recs}
    # R7 相手の器 − MSCI の紙
    r7 = {}
    for cat in CATS:
        ms = [m for m in comp[cat] if m >= 200710]
        a_ = {m: comp[cat][m] for m in ms}
        b_ = {m: J[cat][m] for m in ms}
        fund_ms = [m for m in ms if comp_src[cat][m] != 'MSCI']
        r7[cat] = {'all_months_incl_fallback': N.excess_stats(a_, b_),
                   'instrument_months_only': N.excess_stats({m: a_[m] for m in fund_ms}, {m: b_[m] for m in fund_ms}) if len(fund_ms) >= 24 else None,
                   'n_fallback_months': sum(1 for m in ms if comp_src[cat][m] == 'MSCI'), 'n_instrument_months': len(fund_ms),
                   'filled_months_inside_instrument_years': len([x for x in fills[cat] if x[0] >= 2007])}
    rep['R7_comparator_drag'] = r7
    # R8 本数
    r8 = {'comparator_by_year': {cat: {y: ({'assoc': chains[cat][y], 'name': F[chains[cat][y]]['name'][:40], 'trustReward': F[chains[cat][y]]['fee'],
                                            'nInstitutions': F[chains[cat][y]]['n_inst']} if chains[cat].get(y) else 'MSCI − 0.50%') for y in range(2007, 2026)} for cat in CATS},
          'comparator_fx_rejected': chain_rej, 'by_rule': {}}
    for rid in recs:
        hold = holds[rid]
        nisa = {}
        for y, sel in hold.items():
            if sel:
                nisa[y] = {'n': len(sel), 'nisa_growth_share': round(sum(1 for x in sel if F[x]['nisa_growth']) / len(sel), 3),
                           'nisa_tsumitate_share': round(sum(1 for x in sel if F[x]['nisa_tsumitate']) / len(sel), 3)}
        r8['by_rule'][rid] = {'selection_by_year': diags[rid], 'nisa_flags_now_of_selected': nisa,
                              'n_selected_by_year': {y: len(v) for y, v in hold.items()}}
    rep['R8_fund_count'] = r8
    # R9 オール・カントリーひとつ
    acwi = {m: J['GLW'][m] - R9_FEE / 12 for m in J['GLW']}
    rep['R9_single_alternative_acwi'] = {rid: {'full': N.excess_stats(series[rid][0], acwi),
                                               'after_cost_fund_side': N.excess_stats(series[rid][3], acwi)} for rid in recs}
    # ── B 族（三菱UFJの償還ファンドを足し戻す）
    b_out = {'n_redeemed_usable_active': len(R), 'redeemed_by_cat': dict(collections.Counter(f['cat'] for f in R.values()))}
    b1, b2 = {}, {}
    mufg_lib = [a for a in lib_keys if a[:2] == '03']
    for rid, L, how in (('P1_top_q_3y', 3, 'top'), ('P2_top_q_5y', 5, 'top'), ('C2_all_active', 3, 'all'), ('C3_bottom_q_3y', 3, 'bottom')):
        for tag, keys, tgt in (('B1', lib_keys, b1), ('B2', mufg_lib, b2)):
            ha, hb, da, dbg = {}, {}, {}, {}
            for y in range(2021, 2026):
                pa = base_pool(FA, keys, y, L, U, fx)
                pb = base_pool(FA, keys + list(R), y, L, U, fx)
                ha[y], da[y] = pick(FA, pa, y, how, comp=comp, L=L)
                hb[y], dbg[y] = pick(FA, pb, y, how, comp=comp, L=L)
            sa, ba, _ = portfolio(FA, ha, comp, a=202110)
            sb, bb, _ = portfolio(FA, hb, comp, a=202110)
            added = sorted({x for y in hb for x in hb[y] if x.startswith('MUFGR:')})
            tgt[rid] = {'a_survivors_only': N.excess_stats(sa, ba), 'b_with_mufg_redeemed': N.excess_stats(sb, bb),
                        'diff_b_minus_a_rule_side_ann_pct': round((N.cagr(sb) - N.cagr(sa)) * 100, 3) if sa and sb else None,
                        'redeemed_funds_selected': [[x, FA[x]['name'][:40], FA[x]['cat'], FA[x]['redeemed']] for x in added],
                        'n_by_year_a': {y: len(v) for y, v in ha.items()}, 'n_by_year_b': {y: len(v) for y, v in hb.items()},
                        'groups_used_a': {y: {c: da[y][c]['used'] for c in CATS} for y in da},
                        'groups_used_b': {y: {c: dbg[y][c]['used'] for c in CATS} for y in dbg}}
    b_out['B1_add_back_mufg'] = b1
    b_out['B2_mufg_only'] = b2
    rep['B_survivorship_check'] = b_out
    # ── Q 族（後知恵の答え合わせ）
    rm = D.report_members(rows)
    tsm = None
    try:
        import nx_stack_data as SD
        d, _ = SD.aqr_generic('Time-Series-Momentum-Factors-Monthly', 'TSMOM Factors',
                              lambda r: r and len(r) > 1 and r[1] is not None and str(r[1]).strip() == 'TSMOM')
        tsm = d.get('TSMOM')
    except Exception as e:  # noqa
        tsm = None
        rep['Q_tsmom_error'] = str(e)[:200]
    qout = {}
    for q, codes in rm.items():
        mem, per, drop = [], [], []
        for a in codes:
            f = F.get(a)
            if f is None or len(f['mon']) < 12:
                drop.append([a, (f or {}).get('name', '')[:40], 'CSV なし' if f is None else f'月次 {len(f["mon"])} か月（12 未満）'])
                continue
            cat = f['cat']
            fxc = fx_coef(f['mon'], sorted(f['mon']), cat, U, fx) if cat in FOREIGN else None
            if cat in FOREIGN and fxc is not None and fxc < FX_MIN:
                drop.append([a, f['name'][:40], f'為替の係数 {round(fxc, 3)} < 0.5（ヘッジありとみなす）'])
                continue
            mem.append(a)
            ccat = 'GLW' if q.startswith('Q1') else cat
            ms = sorted(f['mon'])
            one = N.excess_stats({m: f['mon'][m] for m in ms}, {m: comp[ccat][m] for m in ms}) if len(ms) >= 24 else None
            g = N.cagr({m: f['mon'][m] for m in ms})
            gb = N.cagr({m: comp[ccat][m] for m in ms})
            per.append({'assoc': a, 'name': f['name'][:50], 'cat': cat, 'months': len(ms), 'first': ms[0], 'trustReward': f['fee'],
                        'fx_coef_full': round(fxc, 3) if fxc is not None else None,
                        'cagr_pct': round(g * 100, 2), 'comparator_cagr_pct': round(gb * 100, 2), 'cagr_diff_pct': round((g - gb) * 100, 2),
                        'excess_stats': one})
        s, b, cash = {}, {}, {}
        for m in sorted({m for a in mem for m in F[a]['mon']}):
            have = [a for a in mem if m in F[a]['mon']]
            s[m] = sum(F[a]['mon'][m] for a in have) / len(have)
            b[m] = sum(comp['GLW' if q.startswith('Q1') else F[a]['cat']][m] for a in have) / len(have)
            cash[m] = 0.0
        entry = {'members_used': len(mem), 'dropped': drop, 'per_instrument': per,
                 'portfolio_vs_comparator': N.excess_stats(s, b) if len(s) >= 24 else None,
                 'portfolio_months': len(s), 'portfolio_first': min(s) if s else None}
        if q.startswith('Q1'):
            entry['portfolio_vs_cash_0'] = N.excess_stats(s, cash) if len(s) >= 24 else None
            if tsm:
                ms = [m for m in s if m in tsm]
                entry['portfolio_minus_aqr_tsmom_paper'] = N.excess_stats({m: s[m] for m in ms}, {m: tsm[m] for m in ms}) if len(ms) >= 24 else None
                entry['tsmom_note'] = 'AQR TSMOM は米ドルの超過（資金調達込み）＝為替ヘッジした円の超過の近似。器は円・為替ヘッジの有無が混ざる'
            entry['comparator'] = 'GLW の相手（全世界の指数型の鎖）と円の現金 0%'
        qout[q] = entry
    rep['Q_real_instrument_hindsight'] = qout
    ph = post_hoc(F, FA, R, lib_keys, pools, holds, recs, series, comp, chains, med, h_lb, U, fx, RULESET, holm)
    return pre, ver, chk, recs, holm, rep, RULESET, series, holds, F, comp, J, ph


def by_hold_year(s, b):
    out = {}
    for y in sorted({hold_year(m) for m in s}):
        ms = [m for m in s if hold_year(m) == y and m in b]
        gs = math.prod(1 + s[m] for m in ms) - 1
        gb = math.prod(1 + b[m] for m in ms) - 1
        out[y] = {'months': len(ms), 'rule_pct': round(gs * 100, 2), 'bench_pct': round(gb * 100, 2), 'diff_pct': round((gs - gb) * 100, 2)}
    return out


def post_hoc(F, FA, R, lib_keys, pools, holds, recs, series, comp, chains, med, h_lb, U, fx, RULESET, holm):
    """★事後（結果を見た後の診断）。格付けには使わない。X1（探索）が grade_short で S になったので、その中身を分解する"""
    ph = {'label': '事後（結果を見た後に足した診断・格付けに使わない・事前登録の外）'}
    y0 = {rid: y for rid, f, L, how, y, d in RULESET}
    # PH1 分類ごと（X1・X4・X2・X3・C3 は R1 に無い）
    ph1 = {}
    for rid in ('X1_top_q_1y', 'X2_top_q_3y_ir', 'X3_top_q_3y_big', 'X4_top_d_3y', 'C3_bottom_q_3y'):
        ph1[rid] = {}
        for cat in CATS:
            s_, b_, _ = portfolio(F, holds[rid], comp, a=y0[rid] * 100 + 10, cats={cat})
            ph1[rid][cat] = {'months': len(s_), 'stats': N.excess_stats(s_, b_) if len(s_) >= 24 else None,
                             'first_half': N.excess_stats(s_, b_, *halves(s_, b_)[0]) if len(s_) >= 48 else None,
                             'second_half': N.excess_stats(s_, b_, *halves(s_, b_)[1]) if len(s_) >= 48 else None}
        s_, b_, _ = portfolio(F, holds[rid], comp, a=y0[rid] * 100 + 10, cats=set(FOREIGN))
        ph1[rid]['foreign_4_together'] = {'months': len(s_), 'stats': N.excess_stats(s_, b_) if len(s_) >= 24 else None}
    ph['PH1_by_category'] = ph1
    # PH2 保有年ごと
    ph['PH2_by_holding_year'] = {rid: by_hold_year(series[rid][0], series[rid][1]) for rid in recs}
    ph['PH2_by_holding_year_after_cost'] = {rid: by_hold_year(series[rid][3], series[rid][4]) for rid in ('P1_top_q_3y', 'P2_top_q_5y', 'X1_top_q_1y')}
    # PH3 X1 の選び方の差: 同じ適格（振り返り1年）の能動の全部・下位1/4 と比べる
    hold_all1, hold_bot1 = {}, {}
    for y in range(2007, 2026):
        hold_all1[y], _ = pick(F, pools[(1, y)], y, 'all')
        hold_bot1[y], _ = pick(F, pools[(1, y)], y, 'bottom')
    sA, bA, _ = portfolio(F, hold_all1, comp, a=200710)
    sB, bB, _ = portfolio(F, hold_bot1, comp, a=200710)
    sX = series['X1_top_q_1y'][0]
    ph['PH3_X1_selection_spread'] = {
        'all_active_L1_vs_comparator': N.excess_stats(sA, bA),
        'bottom_q_L1_vs_comparator': N.excess_stats(sB, bB),
        'X1_minus_all_active_L1': N.excess_stats(sX, sA),
        'X1_minus_all_active_L1_halves': [N.excess_stats(sX, sA, *halves(sX, sA)[0]), N.excess_stats(sX, sA, *halves(sX, sA)[1])],
        'X1_minus_bottom_q_L1': N.excess_stats(sX, sB),
        'note': '上位1/4 − 同じ適格の能動の全部＝選ぶことの上乗せ（相手の器の選び方に依らない）'}
    # PH4 為替の検査の感度（振り返り1年の12か月の回帰は雑音が大きく、2021 年の GLW は 119 本をヘッジありとみなした）
    ph4 = {}
    for mode in ('36m', 'none'):
        for rid, L, how, yy in (('X1_top_q_1y', 1, 'top', 2007), ('P1_top_q_3y', 3, 'top', 2009)):
            hold = {}
            nh = {}
            for y in range(yy, 2026):
                pl = base_pool(F, lib_keys, y, L, U, fx, fx_mode=mode)
                hold[y], _ = pick(F, pl, y, how)
                nh[y] = sum(len(pl[c]['fx_hedged']) for c in FOREIGN)
            s_, b_, w_ = portfolio(F, hold, comp, a=yy * 100 + 10)
            cs, cb, _ = costs(F, hold, w_, chains, med, 'min')
            ph4[f'{rid}|fx_{mode}'] = {'full': N.excess_stats(s_, b_), 'halves': [N.excess_stats(s_, b_, *halves(s_, b_)[0]), N.excess_stats(s_, b_, *halves(s_, b_)[1])],
                                       'after_cost': N.excess_stats(net(s_, cs), net(b_, cb)), 'lower_bound': N.excess_stats(lower(s_, h_lb, LB_HIT), b_),
                                       'n_fx_hedged_by_year': nh}
    ph['PH4_fx_check_sensitivity'] = ph4
    # PH5 生き残りの偏り（三菱UFJ の償還ファンドの足し戻し・B 族と同じ形を X1 に）
    mufg_lib = [a for a in lib_keys if a[:2] == '03']
    ph5 = {}
    for tag, keys in (('B1_style_add_back', lib_keys), ('B2_style_mufg_only', mufg_lib)):
        ha, hb = {}, {}
        for y in range(2021, 2026):
            ha[y], _ = pick(FA, base_pool(FA, keys, y, 1, U, fx), y, 'top')
            hb[y], _ = pick(FA, base_pool(FA, keys + list(R), y, 1, U, fx), y, 'top')
        sa, ba, _ = portfolio(FA, ha, comp, a=202110)
        sb, bb, _ = portfolio(FA, hb, comp, a=202110)
        ph5[tag] = {'a_survivors_only': N.excess_stats(sa, ba), 'b_with_mufg_redeemed': N.excess_stats(sb, bb),
                    'diff_b_minus_a_rule_side_ann_pct': round((N.cagr(sb) - N.cagr(sa)) * 100, 3),
                    'redeemed_selected': sorted({x for y in hb for x in hb[y] if x.startswith('MUFGR:')}),
                    'n_by_year_a': {y: len(v) for y, v in ha.items()}, 'n_by_year_b': {y: len(v) for y, v in hb.items()}}
    ph['PH5_X1_survivorship_mufg'] = ph5
    # PH6 Holm を格付けした9本まとめてにした感度
    ps = {rid: N.p_one(recs[rid]['full']['t']) for rid in recs}
    adj = N.holm(ps)
    ph['PH6_holm_all9_one_family'] = {'holm': adj, 'grade_if_one_family': {rid: N.grade_short(recs[rid]['full'], recs[rid]['first_half'], recs[rid]['second_half'],
                                                                                              recs[rid]['drop_top']['stats'], recs[rid]['cost']['after_cost_full'],
                                                                                              recs[rid]['lower_bound'], adj[rid])[0] for rid in recs}}
    # PH7 X1 の最初の年（2007-10〜2008-09・世界金融危機）を抜いた版
    s_, b_ = series['X1_top_q_1y'][0], series['X1_top_q_1y'][1]
    ph['PH7_X1_from_2009_10_same_window_as_P1'] = {'full': N.excess_stats(s_, b_, 200910), 'lower_bound': N.excess_stats(lower(s_, h_lb, LB_HIT), b_, 200910),
                                                   'after_cost': N.excess_stats(series['X1_top_q_1y'][3], series['X1_top_q_1y'][4], 200910)}
    # PH10 X1 の重複の除去を36か月の相関にした感度（12か月の相関は同じ委託会社の別のファンドを単連結で束ねやすい: 2012 年の三菱UFJ の国内株7本など）
    hold10 = {}
    for y in range(2007, 2026):
        hold10[y], _ = pick(F, base_pool(F, lib_keys, y, 1, U, fx, dedupe_mode='36m'), y, 'top')
    s_, b_, w_ = portfolio(F, hold10, comp, a=200710)
    cs, cb, _ = costs(F, hold10, w_, chains, med, 'min')
    ph['PH10_X1_dedupe_36m'] = {'full': N.excess_stats(s_, b_), 'halves': [N.excess_stats(s_, b_, *halves(s_, b_)[0]), N.excess_stats(s_, b_, *halves(s_, b_)[1])],
                                'after_cost': N.excess_stats(net(s_, cs), net(b_, cb)), 'lower_bound': N.excess_stats(lower(s_, h_lb, LB_HIT), b_),
                                'n_selected_by_year': {y: len(v) for y, v in hold10.items()}}
    # PH9 国内株式だけ（事後に選んだ部分集合）: 費用・下限・寄与の最大を抜いた版・保有年
    ph9 = {'note': '★事後。PH1 で X1 の勝ちが国内株式だけから来ると分かった後に切り出した部分集合（格付けに使わない・5分類×9規則から選んだ＝多重検定の数に入る）'}
    for rid in ('X1_top_q_1y', 'P1_top_q_3y', 'P2_top_q_5y', 'X4_top_d_3y', 'C2_all_active'):
        hj = {y: [x for x in v if F[x]['cat'] == 'JP'] for y, v in holds[rid].items()}
        s_, b_, w_ = portfolio(F, hj, comp, a=y0[rid] * 100 + 10)
        cs, cb, _ = costs(F, hj, w_, chains, med, 'min')
        con = contributions(F, w_, comp)
        top = max(con, key=lambda x: con[x])
        sd, bd, _ = portfolio(F, hj, comp, a=y0[rid] * 100 + 10, exclude={top})
        ph9[rid] = {'full': N.excess_stats(s_, b_), 'halves': [N.excess_stats(s_, b_, *halves(s_, b_)[0]), N.excess_stats(s_, b_, *halves(s_, b_)[1])],
                    'after_cost': N.excess_stats(net(s_, cs), net(b_, cb)), 'lower_bound': N.excess_stats(lower(s_, h_lb, LB_HIT), b_),
                    'lower_bound_plus_cost': N.excess_stats(lower(net(s_, cs), h_lb, LB_HIT), net(b_, cb)),
                    'drop_top': {'dropped': top, 'name': F[top]['name'][:40], 'stats': N.excess_stats(sd, bd)},
                    'by_holding_year': {y: v['diff_pct'] for y, v in by_hold_year(s_, b_).items()},
                    'mean_n_funds': round(S.mean(len(v) for v in w_.values()), 1)}
    ph['PH9_JP_only'] = ph9
    # PH8 日本株の部分の超過を日本の因子（French Japan: SMB・HML・WML・RMW・CMA〔米ドルの売り買い＝通貨はほぼ打ち消す〕＋ MSCI Japan 円）で説明できるか
    try:
        ph['PH8_japan_factor_alpha'] = japan_factor_alpha(F, holds, comp, series, pools)
    except Exception as e:  # noqa
        ph['PH8_japan_factor_alpha'] = {'error': str(e)[:300]}
    return ph


def _fr_monthly(name):
    for t, v in N.french_tables(name).items():
        if v['freq'] == 'monthly':
            out = {c: {} for c in v['cols']}
            for d, row in v['data'].items():
                for c, x in zip(v['cols'], row):
                    if x is not None:
                        out[c][d] = x / 100
            return out
    raise KeyError(name)


def ols_nw(y, X, lag=12):
    """OLS（定数あり）と Newey-West の t。y: list、X: list of lists（列）"""
    n = len(y)
    Xm = np.column_stack([np.ones(n)] + [np.array(c) for c in X])
    Y = np.array(y)
    b = np.linalg.lstsq(Xm, Y, rcond=None)[0]
    e = Y - Xm @ b
    XtX_inv = np.linalg.inv(Xm.T @ Xm)
    Sm = np.zeros((Xm.shape[1], Xm.shape[1]))
    for L in range(0, lag + 1):
        w = 1.0 if L == 0 else 1 - L / (lag + 1)
        G = sum(np.outer(Xm[i] * e[i], Xm[i - L] * e[i - L]) for i in range(L, n))
        Sm += w * (G if L == 0 else G + G.T)
    V = XtX_inv @ Sm @ XtX_inv
    se = np.sqrt(np.diag(V))
    r2 = 1 - (e @ e) / ((Y - Y.mean()) @ (Y - Y.mean()))
    return {'n': n, 'alpha_ann_pct': round(float(b[0]) * 1200, 2), 't_alpha': round(float(b[0] / se[0]), 2),
            'betas': [round(float(x), 3) for x in b[1:]], 't_betas': [round(float(x / y_), 2) for x, y_ in zip(b[1:], se[1:])], 'r2': round(float(r2), 3)}


def japan_factor_alpha(F, holds, comp, series, pools):
    f3 = _fr_monthly('Japan_3_Factors')
    mom = _fr_monthly('Japan_Mom_Factor')
    f5 = _fr_monthly('Japan_5_Factors')
    mj = D.msci_jpy(D.MSCI['JP'], ccy='JPY')
    out = {'note': ('★事後。日本株の分類の部分の月次の超過（選んだ能動の投信 − TOPIX の指数型）を、MSCI Japan（円・NETR）と French の日本の SMB・HML・WML'
                    '（＋ RMW・CMA）に回帰した定数（年率%）と Newey-West の t（ラグ12）。French の因子は米ドル建ての売り買い（通貨はほぼ打ち消す）。'
                    '定数が消えれば、選んだ投信の勝ちは小型・割安・勢いなどの型の傾きで説明できる（Carhart 1997 の言い方）')}
    y0 = {'P1_top_q_3y': 2009, 'P2_top_q_5y': 2011, 'X1_top_q_1y': 2007, 'X4_top_d_3y': 2009, 'C2_all_active': 2009}
    for rid, yy in y0.items():
        s_, b_, _ = portfolio(F, holds[rid], comp, a=yy * 100 + 10, cats={'JP'})
        ms = [m for m in sorted(s_) if m in f3['SMB'] and m in mom['WML'] and m in mj]
        ex = [s_[m] - b_[m] for m in ms]
        r4 = ols_nw(ex, [[mj[m] for m in ms], [f3['SMB'][m] for m in ms], [f3['HML'][m] for m in ms], [mom['WML'][m] for m in ms]])
        r4['factors'] = ['MSCI_Japan_JPY', 'SMB', 'HML', 'WML']
        ms5 = [m for m in ms if m in f5['RMW']]
        r6 = ols_nw([s_[m] - b_[m] for m in ms5], [[mj[m] for m in ms5], [f5['SMB'][m] for m in ms5], [f5['HML'][m] for m in ms5],
                                                  [f5['RMW'][m] for m in ms5], [f5['CMA'][m] for m in ms5], [mom['WML'][m] for m in ms5]])
        r6['factors'] = ['MSCI_Japan_JPY', 'SMB', 'HML', 'RMW', 'CMA', 'WML']
        raw = {'n': len(ms), 'mean_ann_pct': round(S.mean(ex) * 1200, 2), 't': round(N.nw_t(ex), 2)}
        out[rid] = {'raw_excess': raw, 'carhart4_jp': r4, 'ff5_plus_wml_jp': r6}
    return out


DEVIATIONS = [
    {'what': '相手の器（指数型）の為替の係数の検査の窓',
     'prereg': 'RULES.universe_filter.fx_exposure_check『相手の指数型と報告の族の外国の器にも同じ検査を当てる』（振り返りの月だけを使う）',
     'done': '相手の器は規則の振り返りに縛られないので、選択の日 t までの最大36か月（12か月未満なら検査しない）で回帰した。報告の族 Q の外国の器は全履歴（報告のみ）',
     'why': '相手は9本の規則で共通の1本で、振り返りの長さ（1・3・5年）が規則ごとに違うため。事前登録の相手の割り当て（為替の検査の前）と一致し、検査で外れた相手は0本',
     'affects_grade': 'なし（相手の鎖は事前登録の表と完全一致）'},
    {'what': '2006 年（2006-10〜2007-09）の相手',
     'prereg': '相手は選択の日 2007-09 から（data.shape.comparator_assignment は 2007 から）',
     'done': 'X2（情報比）の 2009 年の振り返り（2006-10〜2009-09）と R7・Q のために同じ規則を t=2006-09 に当てた。2006-09 は CSV の最初の月で月次が無い（最初の日を含む月は捨てる）ので、規則の補欠どおり MSCI（円・NETR）− 0.50%',
     'affects_grade': 'X2 の 2009 年の並びの最初の12か月の相手だけ（ファンドどうしの並びには同じ分類で共通の相手なので効きは小さい）'},
    {'what': '販売会社の情報が無い器の購入時手数料',
     'prereg': 'RULES.costs.buy『今の販売会社のうち最も安い購入時手数料 ×1.1』',
     'done': '5分類でフィルターを通る器のうち 58本（能動45・指数型13）は販売会社が0社で salesFeeMin・buyFee が空欄。0 と読まず（絶対のルール7）、同じ分類×種類の中央値で埋めた。埋めた器は各規則の cost.funds_with_sales_fee_filled_by_median',
     'affects_grade': '費用後（cost）の値だけ・少数の器'},
    {'what': '留保額を引く月と最後の月',
     'prereg': 'RULES.costs.sell『保有から外れたファンドには…0.3% を外れる月に引く』',
     'done': '売るのは選択の日（9月末）なので、外れる器の最後の保有月（9月）にその月の重みで引いた。評価の最後の月（2026-08）に全部を売る費用は主の費用の版では引かない（NISA で持ち続ける）。課税口座（R4）は最後の月に全部を売る',
     'affects_grade': '費用後の値がわずか（留保額 0.3% × 重み）'},
    {'what': '相手側の費用の単位',
     'prereg': 'RULES.costs.comparator『相手の器が替わった年に新しい器の購入時手数料・古い器の留保額』',
     'done': '分類ごとの相手の器を1つの持ち物とみなし、保有に新しく入った相手の器（最初の年は全部・分類が新しく使われた年も含む）に購入時手数料、翌年に使われない相手の器に留保額（印があれば）。重みはその月の分類の重み。MSCI の補欠は費用なし',
     'affects_grade': '費用後の相手側（年 0.02〜0.03% 程度）'},
    {'what': '重複の除去の範囲',
     'prereg': 'RULES.selection.share_class_dedupe『同じ委託会社（協会コードの先頭2文字）で…相関が 0.995 以上の組』',
     'done': '同じ委託会社 ∧ 同じ分類の中で束ねた（並べるのが分類の中なので）',
     'affects_grade': 'ほぼなし（分類をまたぐ別コースの相関が 0.995 を超える例は想定しにくい）'},
    {'what': '下位1/4（C3）と安い1/4（C1）の同点の扱い',
     'prereg': "RULES.selection.top_quartile『同点は純資産の大きい順』（上位の書き方）",
     'done': 'C3 は振り返りの累積が低い順・同点は純資産の大きい順。C1 は信託報酬の安い順・同点は純資産の大きい順（事前登録どおり）。どちらも最後は協会コード順で決める',
     'affects_grade': 'なし（連続値で同点はほぼ起きない）'},
    {'what': '積立（R6）と10年窓の勝ちの数え方',
     'prereg': 'nx_common.dca(years=10)',
     'done': 'nx_common.dca と同じ窓の作り方を写した dca_raw（勝ちを丸める前の比で数える・表示は同じ丸め）。10年の転がる窓（一括）も同じく rolling_raw で報告',
     'affects_grade': 'なし（報告のみ）'},
]

IMPL_NOTES = [
    '凍結の3つの sha256（universe・rules・extract）を最初に確かめ、事前登録と一致した（frozen_verified）',
    '月次の総リターンは nx_jpfunds_data.monthly_tr（分配金を税引前でその日の基準価額で再投資）。課税口座の版（R4）は分配金を 0.79685 倍にした日次を同じ関数に通した',
    '生き残りの下限は保有年 y の各月の選んだファンドの月次から h_y/12（h_y = q_(y−1) × 0.30）を引いた（超過から引くのと算術で同じ）。h_y は事前登録の表と一致（data_checks.lower_bound_matches_prereg）',
    'drop_top・halves・下限は費用前の系列で、cost は費用後の系列で grade_short に渡した（ev5 と同じ）',
    'シャープは無リスク金利 0（円の短期金利は 2009〜2023 年ほぼ 0・報告のみ）。重ねる・借入・時期選びの型ではないので C8 は該当なし',
    '20 年窓・20 年積立は評価の期間（最長 18.9 年）が足りず None。事前登録の R6 は 10 年の積立',
    '外れ値（MSCI 円と30%以上の差）12か月はどれもデータの誤りではないので値なしにしていない（data_checks.outlier_decision）',
    '新興国の相手2本で保有の12か月の相関が 0.90 を下回った（0.30・0.90）。全履歴の相関は 0.94 前後で、同じ月の別の新興国の指数型とも 0.999 ＝器・分類の誤りではなく、静かな年のばらつきの小ささと1日遅れの基準価額による（data_checks.comparator_corr_note）',
    '為替の係数の検査は、名前にヘッジありのある外国の器148本（除外済み）に当てると 115本（78%）で 0.5 未満＝効くが完全ではない（テーマ型のヘッジありで係数が高く出るものがある）。振り返り1年（X1）では12か月の回帰で雑音が大きく、2021 年の GLW は 119本をヘッジありとみなした（事後の感度 PH4: 36か月の検査・検査なしでも X1 は +2.1・+2.0）',
    'RULES の正規表現の穴を2つ見つけた（凍結なので直していない）: hedged_regex の『ヘッジ型』が『為替ノーヘッジ型』に当たる（指数型1本）／currency_course_regex が『通貨セレクトコース』『米ドル・コース』に当たらない（data_checks.filter_gap_currency_select に選ばれた本数）',
    '重複の除去は振り返りの月の相関（事前登録どおり）。振り返り1年（X1）では12か月の相関 0.995 が同じ委託会社の別のファンドを単連結で束ねることがある（例: 2012 年の三菱UFJ の国内株7本が1組）。事後の感度 PH10 で36か月の相関にした版を並べた',
    'B 族（三菱UFJ の償還ファンド）は 60本の全履歴の最後の日がどれも償還日の7暦日以内。5分類・能動・フィルターを通るのは21本（国内株式19・日本を除く世界2）',
]


def prediction_check(recs, rep):
    r1 = rep['R1_by_category']['P1_top_q_3y']
    order = sorted(((c, v['stats']['cagr_diff']) for c, v in r1.items() if v['stats']), key=lambda x: x[1])
    return {'predicted': '（測る前）P1・P2 は C か B／分類別では米国株式がいちばん悪く、国内株式は時期によって勝つ／C1 は C2 よりよいが指数型に負ける／C3 がいちばん悪い／下限で S はほぼ無い',
            'observed': {'P1': recs['P1_top_q_3y']['grade'], 'P2': recs['P2_top_q_5y']['grade'],
                         'P1_by_category_worst_to_best': order,
                         'C1_vs_C2_full_cagr_diff': [recs['C1_cheap_q_fee']['full']['cagr_diff'], recs['C2_all_active']['full']['cagr_diff']],
                         'C3_full_cagr_diff': recs['C3_bottom_q_3y']['full']['cagr_diff'],
                         'X1_grade': recs['X1_top_q_1y']['grade']},
            'matches': '一部: P1・P2 は B（予想どおり）・C3 がいちばん悪い（予想どおり）・国内株式は前半に大きく勝つ（予想どおり）。外れ: いちばん悪いのは米国株式ではなく日本を除く世界、C1（安い1/4）は C2（能動の全部）より悪かった、探索の X1 が S になった（予想は主の族について S はほぼ無い）'}


def summarize(recs, holm, rep):
    lines = []
    for rid, r in recs.items():
        f, c = r['full'], r['cost']['after_cost_full']
        lines.append(f"{rid}: 格付け {r['grade']}・費用前 超過 {f['ex_ann']}%/年（幾何 {f['cagr_diff']}）t {f['t']}・"
                     f"費用後 幾何 {c['cagr_diff']}・下限 {r['lower_bound']['cagr_diff']}・前半 {r['first_half']['cagr_diff']}／後半 {r['second_half']['cagr_diff']}")
    return lines


def main():
    if '--checks' in sys.argv:
        run(checks_only=True)
        return
    pre, ver, chk, recs, holm, rep, RULESET, series, holds, F, comp, J, ph = run()
    tested = []
    for rid, fam, L, how, y0, desc in RULESET:
        tested.append(recs[rid])
    # 報告の族（格付けしない）と事後の診断も tested に1本残らず（中身は report_only / post_hoc_diagnostics）
    for k in rep:
        tested.append({'id': k, 'family': 'report' if not k.startswith('B_') and not k.startswith('Q_') else ('survivorship_check' if k.startswith('B_') else 'real_instrument_hindsight'),
                       'graded': False, 'grade': '報告（格付けしない・事前登録）', 'where': f'report_only.{k}'})
    for k in ph:
        if k == 'label':
            continue
        tested.append({'id': k, 'family': 'post_hoc', 'graded': False, 'grade': '事後（格付けに使わない）', 'where': f'post_hoc_diagnostics.{k}'})
    fam_name = {'P': 'primary（主）', 'C': 'control（対照）', 'X': 'exploratory（探索）'}
    obj = {
        'angle': 'nx_jpfunds', 'prereg': 'out/nx_jpfunds_prereg.json', 'global_prereg': 'out/nx_prereg.json',
        'frozen_verified': ver, 'grade_function': 'nx_common.grade_short（事前登録 criteria.which = criteria_short_sample）',
        'period_end': END, 'data_checks': chk, 'holm': holm,
        'grades': {r['id']: r['grade'] for r in tested if r.get('graded', True)},
        'families': {r['id']: fam_name[r['family']] for r in tested if r.get('graded', True)},
        'tested': tested, 'report_only': rep, 'post_hoc_diagnostics': ph,
        'holdings_by_rule': {rid: {y: v for y, v in holds[rid].items()} for rid in recs},
        'fund_names': {x: [F[x]['name'][:60], F[x]['cat'], F[x]['fee']] for rid in recs for y in holds[rid] for x in holds[rid][y]},
        'summary_lines': summarize(recs, holm, rep),
    }
    # 実装して見つけたフィルターの穴（凍結の RULES は直さない・何本が選ばれたかを数える）
    gap = {a for a, f in F.items() if f['src'] == 'library' and f['cat'] in CATS and f['ok'] and f['kind'] == 'active'
           and any(k in f['name'] for k in ('通貨セレクト', '米ドル・コース'))}
    chk['filter_gap_currency_select'] = {
        'what': ('RULES の currency_course_regex は『通貨セレクトコース』『米ドル・コース』（中黒つき）に当たらず、通貨選択型の一部が主の母集団に残る'
                 '（名前に『通貨選択型』とある国内株の円コースは事前登録どおり残すので数えない）。RULES は凍結なので直さず、選ばれた本数を数える'),
        'funds': sorted([a, F[a]['name'][:60], F[a]['cat']] for a in gap),
        'fund_years_selected_by_rule': {rid: sum(1 for y in holds[rid] for x in holds[rid][y] if x in gap) for rid in recs},
        'fund_years_total_by_rule': {rid: sum(len(v) for v in holds[rid].values()) for rid in recs}}
    obj['deviations_from_prereg'] = DEVIATIONS
    obj['implementation_notes'] = IMPL_NOTES
    obj['prediction_check'] = prediction_check(recs, rep)
    x1, p1, p2 = recs['X1_top_q_1y'], recs['P1_top_q_3y'], recs['P2_top_q_5y']
    jp = ph['PH9_JP_only']['X1_top_q_1y']
    fa = ph['PH8_japan_factor_alpha']['X1_top_q_1y']['carhart4_jp']
    ex1 = ph['PH1_by_category']['X1_top_q_1y']['foreign_4_together']['stats']
    obj['best'] = ('X1_top_q_1y（探索の族・振り返り1年の上位1/4）が grade_short で S。ただし探索の族で主の結論には使わない（事前登録）。'
                   '主の族 P1・P2 はどちらも B（後半が負・生き残りの下限で負）')
    obj['summary_ja'] = (
        f"日本の公募投信（株式5分類・追加型）で過去の成績の上位1/4を毎年持つ規則（Carhart の持続の日本版）を、事前登録どおり9本測った。"
        f"主の族: P1（振り返り3年）は費用前 幾何 {p1['full']['cagr_diff']}%/年（t {p1['full']['t']}）・費用後 {p1['cost']['after_cost_full']['cagr_diff']}・"
        f"前半 {p1['first_half']['cagr_diff']}／後半 {p1['second_half']['cagr_diff']}・生き残りの下限 {p1['lower_bound']['cagr_diff']} で B。"
        f"P2（5年）も {p2['full']['cagr_diff']}（t {p2['full']['t']}）・後半 {p2['second_half']['cagr_diff']}・下限 {p2['lower_bound']['cagr_diff']} で B。"
        f"対照の C1〜C3（安い1/4・能動の全部・下位1/4）はすべて C（能動の全部 {recs['C2_all_active']['full']['cagr_diff']}・下位1/4 {recs['C3_bottom_q_3y']['full']['cagr_diff']}）。"
        f"探索の X1（振り返り1年＝Carhart 1997 の元の形）は費用前 {x1['full']['cagr_diff']}%/年（t {x1['full']['t']}・族の Holm 後 p {x1['holm_p_one']}）・"
        f"前半 {x1['first_half']['cagr_diff']}／後半 {x1['second_half']['cagr_diff']}・費用後 {x1['cost']['after_cost_full']['cagr_diff']}・下限 {x1['lower_bound']['cagr_diff']}・"
        f"寄与最大の1本を抜いて {x1['drop_top']['stats']['cagr_diff']} で grade_short の S。★ただし探索の族（主の結論には使わない）で、"
        f"下限＋費用では {x1['lower_bound_plus_cost']['cagr_diff']}、購入時手数料の上限では {rep['R4_costs']['X1_top_q_1y']['buy_fee_upper_x1.1_plus_retention']['cagr_diff']}、"
        f"9本をひとつの族にした Holm（事後）なら A。"
        f"★事後の分解: 勝ちは国内株式だけから来る（X1 の国内株式 {jp['full']['cagr_diff']}%/年 t {jp['full']['t']}・前半 {jp['halves'][0]['cagr_diff']}／後半 {jp['halves'][1]['cagr_diff']}・"
        f"費用後 {jp['after_cost']['cagr_diff']}・下限＋費用 {jp['lower_bound_plus_cost']['cagr_diff']}、外国の4分類をまとめると {ex1['cagr_diff']}）。"
        f"日本の Carhart の4因子（MSCI Japan・SMB・HML・WML）で回帰しても定数 {fa['alpha_ann_pct']}%/年（t {fa['t_alpha']}）が残る。"
        f"国内株式の能動の投信の上位は TOPIX の指数型に勝ち続けたが、母集団は生き残りだけ（2009年末の株式投信の 48%）で、三菱UFJ の償還ファンドの足し戻し（2021〜）は X1 を {ph['PH5_X1_survivorship_mufg']['B1_style_add_back']['diff_b_minus_a_rule_side_ann_pct']}%/年動かした。"
        f"門・配分には入れない（測定器）。")
    p = N.save(OUT_NAME, obj)
    print(p, file=sys.stderr)
    for ln in obj['summary_lines']:
        print(ln)


if __name__ == '__main__':
    main()
