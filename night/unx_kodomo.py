#!/usr/bin/env python3
"""night/unx_kodomo.py — こどもNISA の期間（12・15・18年）の積立と、最後の4年の『現金へ寄せる』を測る（事前登録 C・2026-10-14）

読むだけ。門・採点・四関門・席・売却規律・配分・注文書には触れない。
事前登録 out/unexplored_prereg.json（6f534c92）の groups.C_kodomo_and_glide をそのまま実装する（測る前に固定した決まり）。

  設定: 毎月 ¥30,000 の円の積立・総額 ¥6,000,000 で止める（200か月で買い止め・その後は持つだけ）。
        窓の長さ H＝12・15・18年（子どもの今の年齢は書かない＝一般の H）。毎月の積立は月初に買い、その月のリターンを受ける
        （gaps_common.dca・future30.dca_mult と同じ約束）。転がる窓（毎月の起点すべて）。
  戦略: K1 NASDAQ100 100% ／ K2 全世界株 100% ／ K3 S&P500 100% ／
        K4 NASDAQ100・最後の4年は新しいお金を円の現金へ（売らない） ／
        K5 参考: NASDAQ100・最後の4年に毎年保有の1/4を円の現金へ（売る・制度上の可否は未確認）／
        K6 NASDAQ100 50 / 全世界株 50（毎月組み直し）
  費用（事前に固定・年率・毎月 (1−c)^(1/12) を掛ける）: NASDAQ100＝iFreeNEXT の実際 0.62% ／ 全世界＝0.06% ／ S&P500＝0.09% ／ 円の現金＝0。
        ⚠ データの器（QQQ・SPY・VT の調整後終値）は自分の経費率を引いた後の値なので、etf_forward_rank の A1 と同じく
        データの器の経費率を足し戻してから器の費用を引く（二重に引かない）: QQQ 0.20%（0.62% を測ったときの基準
        ＝out/bestfund_vehicles.json の index_for_td『QQQ＋0.002』）・SPY 0.0945%・VT 0.06%（out/etf_profiles.json）。
  データ（円の月次＝ドル建ての配当込みの月次 × FRED DEXJPUS の月末の比）:
        NASDAQ100＝^NDX の価格＋（QQQ − ^NDX の重なる月の平均の差）、QQQ がある月は QQQ（night/wholeshare_buy.py の load と同じ）
        S&P500＝VFINX → SPY（SPY がある月は SPY）
        全世界＝etf_forward_rank の DATA['VT']（2008-06 まで VTSMX と VGTSX の等分・その後 VT）
        円の現金＝FRED IR3TIB01JPM156N（年率%）÷12
  窓: 比べる組ごとのデータの共通の期間（期間と窓の数を出す）。判定は K4 と K1 の共通の期間（円の現金が要る）。
  100年の代用（感度・ドル・為替なし）: Ken French の Mkt と テック（Hardw+Softw+Chips を時価総額で）65%＋Mkt 35%
        （alloc_check.century と同じ）・現金＝French の RF。
  物差し: 最終額÷投じた円 の 中央・下位10%（alloc_check と同じ最近順位）・最悪（起点の月）・元本割れ（<1.0）の割合・0.8倍未満の割合。
  判定（事前登録どおり）: K4 を『考える価値あり』とするのは、H=18 で K1 に比べ 元本割れの割合が5pt 以上下がり、
        かつ中央が10%（相対）以上は下がらないとき（円の歴史と100年の代用の両方で）。H=12・15 は記述。
  C2（参考・記述のみ）: 親の ETF 側 F_now（NDX40/SMH25/ITA5/SHLD5/XLV5/FBT5 を ETF 側で正規化・毎月組み直し）に毎月 ¥170,000
        （入金20万円×ETF側85%）を20年積み、最後の5年の新しいお金を円の現金へ回したときの最終額÷投じた円の中央・下位10%の変化。

キャッシュ: 環境変数 UNX_C_CACHE、無ければ out/_nx_cache/unx/c/（gitignore 済み）。
実行: python3 night/unx_kodomo.py   → out/unx_kodomo.json
"""
import datetime, json, os, statistics as S, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import mw_common as M          # noqa: E402  Yahoo（調整後終値の月次リターン）・French・corr
import gaps_common as G        # noqa: E402  FRED・French の市場とテック
import future30 as F           # noqa: E402  mix（alloc_check.century と同じ）
import etf_forward_rank as R   # noqa: E402  DATA['VT']（全世界のつなぎの定義）

CACHE = os.environ.get('UNX_C_CACHE') or os.path.join(BASE, 'out', '_nx_cache', 'unx', 'c')
os.makedirs(CACHE, exist_ok=True)
M.CACHE = CACHE                 # 既存のキャッシュ（out/_mw_cache・out/_gaps_cache）に書かない
G.CACHE = CACHE

OUT = os.path.join(BASE, 'out', 'unx_kodomo.json')
PREREG = 'out/unexplored_prereg.json（6f534c92）'
CUTOFF = 202609                 # 事前登録 common.data_cutoff（途中の 2026-10 は使わない）
MONTHLY = 30000.0
CAP_TOTAL = 6_000_000.0
NBUY = int(CAP_TOTAL // MONTHLY)          # 200か月
HS = (12, 15, 18)
GLIDE_K = 48                               # 最後の4年
COST = {'NDX': 0.0062, 'ACWI': 0.0006, 'SP500': 0.0009, 'CASH': 0.0}
FEE_BACK = {'NDX': 0.0020, 'SP500': 0.000945, 'ACWI': 0.0006}
GATE = 0.90                                # common.proxy_gate
STRATS = ('K1', 'K2', 'K3', 'K4', 'K5', 'K6')
LAB = {'K1': 'NASDAQ100 100%', 'K2': '全世界株 100%', 'K3': 'S&P500 100%',
       'K4': 'NASDAQ100・最後の4年は新しいお金を円の現金へ（売らない）',
       'K5': '参考: NASDAQ100・最後の4年に毎年保有の1/4を円の現金へ（売る）＝各年の初めに株の保有の 1/4・1/3・1/2・全部（始めの保有を4等分）・その4年の新しいお金も円の現金へ',
       'K5b': '参考（K5 の別の読み）: 最後の4年に毎年その時の株の保有の1/4を円の現金へ（4年後も約32%が株）・その4年の新しいお金も円の現金へ',
       'K6': 'NASDAQ100 50 / 全世界株 50（毎月組み直し）'}
# C2（親の ETF 側 F_now）
C2_MONTHLY = 170000.0
C2_N = 240
C2_GLIDE = 60
C2_FORM = {'NDX': 40, 'SMH': 25, 'ITA': 5, 'SHLD': 5, 'XLV': 5, 'FBT': 5}
C2_CHAIN = {'SMH': ('SMH', 'FSELX'), 'ITA': ('ITA', 'FSDAX'), 'XLV': ('XLV', 'FSPHX'), 'FBT': ('FBT', 'FBIOX')}
K_TAX = 0.10                               # 米国上場の本の NISA で戻らない配当の外国税（etf_forward_rank の k）


def ym(m):
    return f'{m // 100:04d}-{m % 100:02d}'


def mrange(a, b):
    return G.month_range(a, b)


def cut(r):
    return {k: v for k, v in r.items() if k <= CUTOFF}


_YH = {}


def yh(t):
    if t not in _YH:
        _YH[t] = cut(M.yahoo(t))
        time.sleep(0.35)
    return _YH[t]


def gate(name, main_r, proxy_r, proxy_label, main_label, ov):
    if len(ov) < 24:
        return dict(series=name, main=main_label, proxy=proxy_label, overlap_months=len(ov), corr=None, used=False,
                    reason='重なる月が24か月未満＝代理を使わない')
    cr = M.corr([main_r[k] for k in ov], [proxy_r[k] for k in ov])
    return dict(series=name, main=main_label, proxy=proxy_label, overlap=f'{ym(ov[0])}〜{ym(ov[-1])}', overlap_months=len(ov),
                corr=round(cr, 4), used=cr >= GATE,
                geo_main=round(R.geo(main_r, ov) * 100, 2), geo_proxy=round(R.geo(proxy_r, ov) * 100, 2),
                reason=('相関 ≥ 0.90＝代理を使う' if cr >= GATE else f'相関 {cr:.3f} < 0.90＝代理を使わない（common.proxy_gate）'))


def splice_first(main_r, proxy_r):
    """本物がある月は本物、無い月は代理（wholeshare_buy と同じ: 代理のある月の上で）。本物だけの月も残す"""
    out = {m: (main_r[m] if m in main_r else proxy_r[m]) for m in proxy_r}
    for m in main_r:
        out[m] = main_r[m]
    return out


def load_usd():
    gates, notes = [], {}
    # NASDAQ100（wholeshare_buy.load と同じ）
    q, n = yh('QQQ'), yh('^NDX')
    ov = sorted(m for m in q if m in n)
    g = S.mean(q[m] - n[m] for m in ov)
    ndx = {m: (q[m] if m in q else n[m] + g) for m in n}
    ndx_g = {m: n[m] + g for m in n}
    gates.append(gate('NDX', q, ndx_g, '^NDX の価格＋平均の差 g', 'QQQ', ov))
    notes['ndx_g_month'] = round(g, 6)
    # S&P500（VFINX → SPY）
    spy, vf = yh('SPY'), yh('VFINX')
    ov = sorted(m for m in spy if m in vf)
    gates.append(gate('SP500', spy, vf, 'VFINX', 'SPY', ov))
    sp = splice_first(spy, vf)
    # 全世界（etf_forward_rank の DATA['VT'] と同じつなぎ）
    main_t, proxy_t, last = R.DATA['VT']
    assert proxy_t == 'BLEND_VTSMX_VGTSX' and last == 200806, R.DATA['VT']
    vt = dict(yh(main_t))
    a, b = yh('VTSMX'), yh('VGTSX')
    p = {k: 0.5 * a[k] + 0.5 * b[k] for k in a if k in b}
    ov = sorted(k for k in vt if k in p and k > last)
    gates.append(gate('ACWI', vt, p, 'VTSMX 50%＋VGTSX 50%（2008-06 まで）', 'VT', ov))
    for k, v in p.items():
        if k <= last:
            vt[k] = v
    for k in [k for k in vt if k <= last and k not in p]:
        del vt[k]
    used = {x['series']: x['used'] for x in gates}
    if not used['NDX']:
        ndx = dict(q)
    if not used['SP500']:
        sp = dict(spy)
    if not used['ACWI']:
        vt = {k: v for k, v in vt.items() if k > last}
    return dict(NDX=ndx, SP500=sp, ACWI=vt), gates, notes


def net(r, key, fee_back=None, cost=None):
    fb = FEE_BACK.get(key, 0.0) if fee_back is None else fee_back
    c = COST[key] if cost is None else cost
    f = ((1 - c) / (1 - fb)) ** (1 / 12)
    return {m: (1 + v) * f - 1 for m, v in r.items()}


def to_yen(r, fxr):
    return {m: (1 + v) * fxr[m] - 1 for m, v in r.items() if m in fxr}


def fx_ratio():
    fx = G.fred('DEXJPUS')
    out = {}
    for m in sorted(fx):
        pm = G.add_months(m, -1)
        if pm in fx and m <= CUTOFF:
            out[m] = fx[m] / fx[pm]
    return out


def cash_yen():
    s = G.fred('IR3TIB01JPM156N')
    return {m: v / 100 / 12 for m, v in s.items() if m <= CUTOFF}


def common_months(*series, lo=None, hi=None):
    ks = set(series[0])
    for s in series[1:]:
        ks &= set(s)
    ks = sorted(k for k in ks if (lo is None or k >= lo) and (hi is None or k <= hi))
    # 最も長い連続区間（途中に穴があれば最後の連続区間ではなく、全体を使えるかを確かめる）
    runs, cur = [], [ks[0]] if ks else []
    for a, b in zip(ks, ks[1:]):
        if G.add_months(a, 1) == b:
            cur.append(b)
        else:
            runs.append(cur)
            cur = [b]
    if cur:
        runs.append(cur)
    return max(runs, key=len) if runs else []


# ───────────────────────── 積立の模擬 ─────────────────────────
def sim(eq, cash, ms, kind, monthly=MONTHLY, nbuy=NBUY, glide=GLIDE_K):
    """eq: 株の月次リターン（費用の後）・cash: 現金の月次リターン（kind が現金を使うときだけ）。
    月初に（K5 なら売って）入金→その月のリターン。→ (最終額÷投じた円, 投じた円)"""
    N = len(ms)
    g0 = N - glide
    e = c = contrib = 0.0
    for i, m in enumerate(ms):
        gl = kind in ('K4', 'K5', 'K5b') and i >= g0
        if kind in ('K5', 'K5b') and gl and (i - g0) % 12 == 0:
            k = (i - g0) // 12
            frac = 1.0 / (4 - k) if kind == 'K5' else 0.25
            c += e * frac
            e -= e * frac
        if i < nbuy:
            contrib += monthly
            if gl:
                c += monthly
            else:
                e += monthly
        e *= 1 + eq[m]
        if c:
            c *= 1 + cash[m]
    return (e + c) / contrib, contrib


def qtile(xs, p):
    return xs[min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))]


def summarize(vals, starts, ref=None):
    xs = sorted(vals)
    i_w = min(range(len(vals)), key=lambda i: vals[i])
    d = {'中央': round(S.median(xs), 3), '下位10%': round(qtile(xs, 0.10), 3), '最悪': round(xs[0], 3),
         '最悪の起点': ym(starts[i_w]), '元本割れの割合': round(sum(x < 1.0 for x in xs) / len(xs), 4),
         '0.8倍未満の割合': round(sum(x < 0.8 for x in xs) / len(xs), 4), '最良': round(xs[-1], 3)}
    if ref is not None:
        rr = sorted(a / b for a, b in zip(vals, ref))
        d['K1との比_窓ごとの中央'] = round(S.median(rr), 3)
        d['K1より上の窓の割合'] = round(sum(x > 1 for x in rr) / len(rr), 3)
    return d


def run_set(series, period, strategies, H, cash_key='CASH', need_cash_everywhere=True):
    """series: {名前: 月次}・period: 使う月の連続区間。各起点で窓 H 年。現金を使う戦略は
    need_cash_everywhere=True なら period の上で（period が現金の月も含む）、False なら現金を持つ月だけ現金のデータを要求"""
    N = H * 12
    pset = set(period)
    starts = [m for m in period if G.add_months(m, N - 1) in pset]
    out_vals = {k: [] for k in strategies}
    used_starts = []
    for s in starts:
        ms = [G.add_months(s, i) for i in range(N)]
        row = {}
        ok = True
        for k in strategies:
            eqk = series['eq_' + k]
            if any(m not in eqk for m in ms):
                ok = False
                break
            if k in ('K4', 'K5', 'K5b'):
                need = ms if need_cash_everywhere else ms[N - GLIDE_K:]
                if any(m not in series[cash_key] for m in need):
                    ok = False
                    break
            row[k] = sim(eqk, series[cash_key], ms, k)[0]
        if not ok:
            continue
        used_starts.append(s)
        for k in strategies:
            out_vals[k].append(row[k])
    if not used_starts:
        return {'窓の数': 0}
    res = {'窓の長さ_年': H, '窓の数': len(used_starts), '起点': f'{ym(used_starts[0])}〜{ym(used_starts[-1])}',
           '終点': f'{ym(G.add_months(used_starts[0], N - 1))}〜{ym(G.add_months(used_starts[-1], N - 1))}',
           '投じた円': min(N, NBUY) * MONTHLY}
    ref = out_vals.get('K1')
    for k in strategies:
        res[k] = summarize(out_vals[k], used_starts, ref if k != 'K1' and ref else None)
    return res, out_vals, used_starts


def decide(r18, label):
    k1, k4 = r18['K1'], r18['K4']
    d_loss = (k1['元本割れの割合'] - k4['元本割れの割合']) * 100
    rel_med = k4['中央'] / k1['中央'] - 1
    c1 = d_loss >= 5.0
    c2 = rel_med > -0.10
    return {'枠': label, '窓の数': r18['窓の数'], '起点': r18['起点'],
            'K1_元本割れ': k1['元本割れの割合'], 'K4_元本割れ': k4['元本割れの割合'], '元本割れの低下_pt': round(d_loss, 2),
            'K1_中央': k1['中央'], 'K4_中央': k4['中央'], '中央の相対変化': round(rel_med, 4),
            '条件1_元本割れが5pt以上下がる': c1, '条件2_中央の下げが10%未満': c2, '両方': c1 and c2}


def main():
    t0 = time.time()
    usd, gates, notes = load_usd()
    fxr = fx_ratio()
    cash = cash_yen()
    # 円・費用の後
    ndx_y = to_yen(net(usd['NDX'], 'NDX'), fxr)
    sp_y = to_yen(net(usd['SP500'], 'SP500'), fxr)
    ac_y = to_yen(net(usd['ACWI'], 'ACWI'), fxr)
    k6_y = {m: 0.5 * ndx_y[m] + 0.5 * ac_y[m] for m in ndx_y if m in ac_y}
    ser = {'eq_K1': ndx_y, 'eq_K2': ac_y, 'eq_K3': sp_y, 'eq_K4': ndx_y, 'eq_K5': ndx_y, 'eq_K5b': ndx_y, 'eq_K6': k6_y,
           'CASH': cash}
    span = lambda s: f'{ym(min(s))}〜{ym(max(s))}（{len(s)}か月）'
    data_spans = {'NASDAQ100（円・費用の後）': span(ndx_y), 'S&P500（円）': span(sp_y), '全世界（円）': span(ac_y),
                  '円の現金 IR3TIB01JPM156N': span(cash), 'DEXJPUS の月次の比': span(fxr)}

    # 比べる組と共通の期間
    sets = {
        'K1_単独（NASDAQ100 の全期間）': (['K1'], [ndx_y]),
        'K1_K3（S&P500 との共通）': (['K1', 'K3'], [ndx_y, sp_y]),
        'K1_K2_K6（全世界との共通）': (['K1', 'K2', 'K6'], [ndx_y, ac_y]),
        'K1_K4_K5（円の現金との共通・判定）': (['K1', 'K4', 'K5', 'K5b'], [ndx_y, cash]),
        '6戦略すべての共通': (['K1', 'K2', 'K3', 'K4', 'K5', 'K5b', 'K6'], [ndx_y, sp_y, ac_y, cash]),
    }
    yen = {}
    raw_keep = {}
    for nm, (strats, srs) in sets.items():
        per = common_months(*srs)
        blk = {'期間': f'{ym(per[0])}〜{ym(per[-1])}（{len(per)}か月）'}
        for H in HS:
            r = run_set(ser, per, strats, H)
            blk[f'H{H}'] = r[0] if isinstance(r, tuple) else r
            if isinstance(r, tuple) and nm.startswith('K1_K4'):
                raw_keep[H] = r
        yen[nm] = blk
    # 感度（判定に使わない）: 現金は持つ月（最後の4年）だけ要る
    per_ndx = common_months(ndx_y)
    sens = {'期間': f'{ym(per_ndx[0])}〜{ym(per_ndx[-1])}（NASDAQ100 の期間・現金は最後の4年の月だけ要求）'}
    for H in HS:
        r = run_set(ser, per_ndx, ['K1', 'K4', 'K5', 'K5b'], H, need_cash_everywhere=False)
        sens[f'H{H}'] = r[0] if isinstance(r, tuple) else r
    yen['感度_K1_K4_K5（現金は持つ月だけ要る・判定に使わない）'] = sens

    # 100年の代用（ドル・為替なし）
    mkt, rf = G.french_mkt()
    tech = G.french_tech()
    allm = sorted(mkt)
    tp = F.mix([(0.65, tech), (0.35, mkt)], allm)
    cen = {'eq_K1': net(tp, 'NDX', fee_back=0.0), 'eq_K3': net(mkt, 'SP500', fee_back=0.0),
           'eq_K4': net(tp, 'NDX', fee_back=0.0), 'eq_K5': net(tp, 'NDX', fee_back=0.0), 'eq_K5b': net(tp, 'NDX', fee_back=0.0),
           'CASH': rf}
    per_c = common_months(tp, mkt, rf)
    century = {'期間': f'{ym(per_c[0])}〜{ym(per_c[-1])}（{len(per_c)}か月）',
               '写し': 'NASDAQ100＝テック（Hardw+Softw+Chips を前月末の時価総額で加重・gaps_common.french_tech）65%＋Mkt 35%（毎月組み直し・alloc_check.century と同じ）・S&P500＝Mkt（Mkt-RF+RF）・円の現金＝RF（ドル）・費用は同じ年率（French は費用前なので足し戻しなし）',
               'K2・K6': None, 'K2・K6_の理由': '全世界株の100年の月次の写しは事前登録に無い（測れない＝空欄）'}
    for H in HS:
        r = run_set(cen, per_c, ['K1', 'K3', 'K4', 'K5', 'K5b'], H)
        century[f'H{H}'] = r[0] if isinstance(r, tuple) else r

    # 判定
    d_yen = decide(yen['K1_K4_K5（円の現金との共通・判定）']['H18'], '円の歴史（K1 と K4 の共通の期間）')
    d_cen = decide(century['H18'], '100年の代用（ドル・French）')
    worth = d_yen['両方'] and d_cen['両方']
    d_sens = decide(sens['H18'], '感度: 現金は持つ月だけ要る（判定に使わない）')
    decision = {
        '決まり': '事前登録: K4 を『考える価値あり』とするのは、H=18 で K1 に比べ 元本割れの割合が5pt 以上下がり、かつ中央が10%（相対）以上は下がらないとき（円の歴史と100年の代用の両方で）。H=12・15 は記述。',
        '円の歴史': d_yen, '100年の代用': d_cen,
        '判定': 'K4 は考える価値あり' if worth else 'K4 は考える価値なし（事前登録の条件を満たさない）',
        '参考_感度（判定に使わない）': d_sens,
    }

    # C2（親の ETF 側・参考）
    c2 = c2_glide(usd, fxr, cash, gates)

    # 自己検問: NASDAQ100 の円の系列（費用の前）が wholeshare_buy.load と一致するか
    chk = None
    try:
        import wholeshare_buy as WB
        ms_wb, R_wb, g_wb = WB.load()
        mine = to_yen(usd['NDX'], fxr)
        diffs = [abs(mine[m_int] - v) for m, v in zip(ms_wb, R_wb['NDX'])
                 for m_int in [int(m[:4]) * 100 + int(m[5:])] if m_int in mine]
        chk = dict(比べた月=len(diffs), 最大の差=float(f'{max(diffs):.2e}') if diffs else None,
                   wholeshare_の_g=round(g_wb, 6), この道具の_g=notes['ndx_g_month'],
                   一致=bool(diffs) and max(diffs) < 1e-5, 注='差は Yahoo の2つの取り方（etf_longest.fetch と mw_common.yahoo）の調整後終値の桁の丸め＝1e-5 未満なら同じ系列とみなす')
    except Exception as e:   # noqa
        chk = dict(一致=None, 理由=f'wholeshare_buy.load を呼べなかった: {e}')

    out = dict(
        generated=datetime.date.today().isoformat(), tool='night/unx_kodomo.py', prereg=PREREG,
        question='こどもNISA（毎月3万円・総額600万円で止める）を NASDAQ100 100% で積むと、12・15・18年の窓でどう分布するか／最後の4年に新しいお金を円の現金へ回す（K4）は考える価値があるか',
        group='C_kodomo_and_glide',
        inputs={
            'Yahoo 月足（調整後終値＝配当込み・M.yahoo）': 'https://query1.finance.yahoo.com/v8/finance/chart/{QQQ,^NDX,SPY,VFINX,VT,VTSMX,VGTSX,SMH,FSELX,ITA,FSDAX,XLV,FSPHX,FBT,FBIOX}',
            'FRED DEXJPUS（円/ドル・日次→月末）': 'https://fred.stlouisfed.org/series/DEXJPUS',
            'FRED IR3TIB01JPM156N（日本の3か月の銀行間金利・年率%・月次）': 'https://fred.stlouisfed.org/series/IR3TIB01JPM156N',
            'Ken French（F-F_Research_Data_Factors・49_Industry_Portfolios）': 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html',
            'データの期間': data_spans, 'データの締め': ym(CUTOFF),
        },
        method={
            '積立': f'毎月 ¥{int(MONTHLY):,}・月初に買いその月のリターンを受ける・{NBUY}か月（¥{int(CAP_TOTAL):,}）で買い止め・その後は持つだけ。最終額÷投じた円（H=12 は ¥4,320,000・15 は ¥5,400,000・18 は ¥6,000,000）',
            '戦略': LAB,
            '費用': {'年率（事前に固定）': COST, 'データの器の経費率の足し戻し（二重に引かない）': FEE_BACK,
                    '式': '毎月 (1+r)×((1−費用)/(1−足し戻し))^(1/12)−1。円の現金は0。100年の代用は足し戻し0'},
            '円': '円の月次＝(1＋ドル建ての月次)×DEXJPUS(今月末)/DEXJPUS(前月末)−1',
            'つなぎ': {'NASDAQ100': f'QQQ がある月は QQQ、それより前は ^NDX の価格＋g（g＝重なる月の QQQ−^NDX の平均＝{notes["ndx_g_month"]}/月）',
                     'S&P500': 'SPY がある月は SPY、それより前は VFINX', '全世界': '2008-06 まで VTSMX と VGTSX の等分（毎月）・2009-07 から VT（etf_forward_rank の DATA[\'VT\'] と同じ）',
                     'K6': '円・費用の後の NASDAQ100 と全世界を毎月 50/50 に組み直す'},
            '窓': '比べる組ごとのデータの共通の期間（最も長い連続区間）の上の、毎月の起点すべて。下位10%は並べた値の round(0.10×(n−1)) 番目（alloc_check と同じ）',
            '代理の門': gates,
        },
        results={'円の歴史': yen, '100年の代用_ドル': century, 'C2_親のETF側の最後の5年（参考）': c2},
        decision=decision,
        self_checks={'NASDAQ100 の円の系列が wholeshare_buy.load と同じか（費用の前）': chk},
        interpretations=[
            'K5 の『毎年保有の1/4』は (a) 始めの保有を4等分して各年の初めに 1/4・1/3・1/2・全部 を売る（4年後は全部現金）と (b) その時の保有の1/4（4年後も約32%が株）の2通りに読めるので、(a) を K5・(b) を K5b として両方出した（どちらも参考で判定に使わない）。どちらもその4年の新しいお金は K4 と同じく円の現金へ。',
            'K6 は NASDAQ100 と全世界を毎月 50/50 に組み直した系列へ積み立てる（repo の混合の約束 future30.mix と同じ）。',
            '費用は事前に固定した器の費用を引く前に、データの器（QQQ・SPY・VT）の経費率を足し戻した（etf_forward_rank の A1 と同じ作法＝二重に引かない）。NASDAQ100 の 0.62% は QQQ＋0.20% を指数として測った値なので、足し戻しは 0.20%（profiles の 0.18% ではなく）。',
            '円の現金は月 m の年率を月 m に当てた（÷12）。値が負の月（2016〜2024 ごろ）もそのまま使う。',
        ],
        deviations=[],
        caveats=[],
        secs=None,
    )
    # 期間による注意（データを見た後に分かった事実＝決まりは変えていない）
    cp = yen['K1_K4_K5（円の現金との共通・判定）']['期間']
    out['deviations'].append(
        f'円の現金 IR3TIB01JPM156N は {data_spans["円の現金 IR3TIB01JPM156N"]} しか無い（事前登録はこの系列を指定したが、始まりの年は書いていなかった）。'
        f'事前登録どおり K4・K5 と K1 の比べは共通の期間（{cp}）だけで行ったので、判定の円の歴史は 2002-04 以降に始まる窓だけ（H=18 は終点 2020〜2026）。'
        '2000〜2002年・2008年の暴落で終わる窓は判定の円の歴史に入らない。参考に『現金は持つ月（最後の4年）だけ要る』窓（NASDAQ100 の全期間の上）を感度として出した（判定には使わない）。'
        ' また現金の最後の月が 2026-07 なので、現金を含む組の窓の終点は 2026-07 まで（2026-08・09 は使えない）。')
    c2f = [g for g in c2['代理の門'] if not g['used']]
    if c2f:
        out['deviations'].append(
            'C2: 代理の門（相関≥0.90・common.proxy_gate）を ' + '・'.join(f"{g['series']}←{g['proxy']}（相関 {g['corr']}）" for g in c2f)
            + ' が通らなかったので、事前登録どおり代理を使わず本物の期間だけでつないだ。F_now の株の系列は '
            + c2['F_now（主）']['株の系列の期間'] + ' しか無く、20年の窓は ' + str(c2['F_now（主）']['主（現金を含む共通の期間）'].get('窓の数'))
            + ' 個しか作れない（記述としてもほとんど情報が無い）。参考に、門を通らない本を形から外して残りで割り直した別の読みも出した（門の結果を見た後に足した記述・判定は無い）。')
    if not decision['円の歴史']['条件1_元本割れが5pt以上下がる'] and decision['円の歴史']['K1_元本割れ'] == 0 and decision['100年の代用']['K1_元本割れ'] == 0:
        decision['補足'] = 'H=18 では K1 の元本割れの割合が円の歴史・100年の代用（・感度の窓）のどれでも 0% なので、条件1（5pt 以上下がる）は原理的に満たせない。最後の4年の寄せが効くかもしれないのは H=12（・15）の元本割れのある窓だが、事前登録はそこを記述にしている。'
    out['caveats'] += [
        '全世界（0.06%）と S&P500（0.09%）の事前に固定した費用は表の経費率の水準で、配当の外国税（米国の配当10%）を含まない。NASDAQ100 の 0.62% は実際に引かれた費用（外国税を含む）なので、K2・K3・K6 は K1 に比べて年0.1〜0.2pt ほど有利に見えている可能性がある。',
        'つなぎの代理の期間（VFINX〜1993・VTSMX/VGTSX〜2008-06）は、その器の当時の経費率ではなく今の器（SPY・VT）の経費率を足し戻した（etf_forward_rank と同じ近似）。当時の経費率は高かったので、その期間は総リターンを少し低く見ている。',
        '^NDX の価格＋g の期間（1999-02 まで）は配当を平均の差 g で近似している（wholeshare_buy と同じ）。',
        '窓は重なっている（毎月の起点）＝窓の数は独立な試行の数ではない。18年の窓は円の歴史では高々数回の独立な期間しか含まない。',
        '円の歴史は 1985年以降の NASDAQ100（テックが勝った時代）で、100年の代用はテックの写し（業種の合成）であって NASDAQ100 そのものではない。',
        'こどもNISA の制度（12歳から払い出し可・18歳で本人の NISA へ・年60万円・総額600万円）は 2027年1月からの予定。K5（売る）は制度上できるかを確かめていない。',
        '税・手数料（売買）・iFreeNEXT の基準価額の時刻のずれは入れていない。',
    ]
    out['secs'] = round(time.time() - t0, 1)
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(out['decision'], ensure_ascii=False, indent=1))
    print('書いた', OUT, out['secs'], '秒')


def c2_glide(usd, fxr, cash, gates_main):
    """参考: 親の ETF 側 F_now の毎月の積立（20年・¥170,000）と、最後の5年の新しいお金を円の現金へ"""
    prof = json.load(open(os.path.join(BASE, 'out', 'etf_profiles.json'))).get('etfs') or {}

    def er_dy(t):
        p = prof.get(t) or {}
        return p.get('er'), p.get('dy')
    gates, chains = [], {}
    for nm, (main, proxy) in C2_CHAIN.items():
        a, p = yh(main), yh(proxy)
        ov = sorted(m for m in a if m in p)
        gt = gate(nm, a, p, proxy, main, ov)
        gates.append(gt)
        chains[nm] = splice_first(a, p) if gt['used'] else dict(a)
    # 費用（common.costs: 器の経費率・米国上場の本は配当利回り×10%）
    costs = {}
    yen = {}
    # NASDAQ100＝上と同じ（iFreeNEXT 0.62%・QQQ の 0.20% を足し戻す）
    yen['NDX'] = to_yen(net(usd['NDX'], 'NDX'), fxr)
    costs['NDX'] = dict(器='iFreeNEXT NASDAQ100', 費用=COST['NDX'], 足し戻し=FEE_BACK['NDX'], 外国税=0.0, 注='0.62% は外国税を含む実際の費用')
    for nm in ('SMH', 'ITA', 'XLV', 'FBT'):
        er, dy = er_dy(nm)
        tax = K_TAX * (dy or 0.0)
        # データの器＝買う器（本物の期間は経費率を引いた後）→ 足し戻し＝経費率、費用＝経費率＋外国税
        yen[nm] = to_yen(net(chains[nm], 'CASH', fee_back=er or 0.0, cost=(er or 0.0) + tax), fxr)
        costs[nm] = dict(器=nm, 経費率=er, 配当利回り=dy, 外国税=round(tax, 5))
    er_i, _ = er_dy('ITA')
    er_s, dy_s = er_dy('SHLD')
    tax_s = K_TAX * (dy_s or 0.0)
    yen['SHLD'] = to_yen(net(chains['ITA'], 'CASH', fee_back=er_i or 0.0, cost=(er_s or 0.0) + tax_s), fxr)
    costs['SHLD'] = dict(器='SHLD（データは ITA の系列）', 経費率=er_s, 足し戻し_ITA=er_i, 配当利回り=dy_s, 外国税=round(tax_s, 5))
    def form_eq(form):
        tw = sum(form.values())
        w = {k: v / tw for k, v in form.items()}
        return w, F.mix([(w[k], yen[k]) for k in w], sorted(set.intersection(*[set(yen[k]) for k in w])))

    def one(eq, per, need_cash_everywhere):
        N = C2_N
        pset = set(per)
        starts = [m for m in per if G.add_months(m, N - 1) in pset]
        base, gl, st = [], [], []
        for s in starts:
            ms = [G.add_months(s, i) for i in range(N)]
            need = ms if need_cash_everywhere else ms[N - C2_GLIDE:]
            if any(m not in eq for m in ms) or any(m not in cash for m in need):
                continue
            b = sim(eq, cash, ms, 'K1', monthly=C2_MONTHLY, nbuy=N)[0]
            g_ = sim(eq, cash, ms, 'K4', monthly=C2_MONTHLY, nbuy=N, glide=C2_GLIDE)[0]
            base.append(b)
            gl.append(g_)
            st.append(s)
        if not st:
            return {'窓の数': 0, '理由': '窓が作れない'}
        sb, sg = summarize(base, st), summarize(gl, st, base)
        return {'窓の数': len(st), '起点': f'{ym(st[0])}〜{ym(st[-1])}', '終点': f'{ym(G.add_months(st[0], N - 1))}〜{ym(G.add_months(st[-1], N - 1))}',
                '寄せない（毎月その形）': sb, '最後の5年の新しいお金を円の現金へ': sg,
                '変化': {'中央_相対': round(sg['中央'] / sb['中央'] - 1, 4), '下位10%_相対': round(sg['下位10%'] / sb['下位10%'] - 1, 4),
                       '最悪_相対': round(sg['最悪'] / sb['最悪'] - 1, 4)}}

    def block(form):
        w, eq = form_eq(form)
        per_all = common_months(eq, cash)
        per_eq = common_months(eq)
        return {'形（ETF側で正規化・%）': {k: round(v * 100, 2) for k, v in w.items()},
                '株の系列の期間': f'{ym(per_eq[0])}〜{ym(per_eq[-1])}（{len(per_eq)}か月）',
                '主（現金を含む共通の期間）': dict(期間=f'{ym(per_all[0])}〜{ym(per_all[-1])}（{len(per_all)}か月）', **one(eq, per_all, True)),
                '感度（現金は持つ月＝最後の5年だけ要る）': one(eq, per_eq, False)}
    failed = [g['series'] for g in gates if not g['used']]
    out = {
        '決まり': '参考（記述のみ）: ETF 側 F_now の写しに毎月の積立をして、最後の5年の新しいお金を円の現金へ回したときの20年の最終額の中央・下位10%の変化',
        '毎月': C2_MONTHLY, '年数': C2_N // 12, '寄せる期間_月': C2_GLIDE,
        '注': '最終額÷投じた円は毎月の入金額によらない（入金を何倍にしても最終額も同じ倍になる）＝¥200,000×0.85＝¥170,000 で測った。毎月組み直し（future30.mix）。',
        '代理の門': gates, '費用': costs,
        'F_now（主）': block(C2_FORM),
    }
    if failed:
        rest = {k: v for k, v in C2_FORM.items() if k not in failed}
        out['門を通らない本を外した形（読み方の別案・参考）'] = dict(
            外した本=failed,
            理由='common.proxy_gate『満たせない本は名指しして外す』を、代理を使わないだけでなく本そのものを形から外す読みにした場合（残りで割り直す）。主の F_now は本物の期間しか使えず窓がほとんど作れないため',
            **block(rest))
    return out


if __name__ == '__main__':
    main()
