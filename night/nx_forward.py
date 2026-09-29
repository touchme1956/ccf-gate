#!/usr/bin/env python3
"""night/nx_forward.py — 角度 nx_forward（前向きの検定・読むだけ・門の判定・採点・配分には不使用）

2026-09-29（ワークフローの課題文 nx_forward）。ユーザーの依頼「市場に勝てる歴史検証が出るまでいろんな角度から調べて…探し続けて」。
歴史の検証は全セッションで出尽くしつつあり、**誰も見ていないデータは未来だけ**。out/nx_summary.json の winners のうち、
日本の個人（楽天証券・NISA/課税口座）が実際に持てる形の規則を、2026-10 の月末から毎月の実績で検定する。
作法は eknzbh の out/mw_forward_prereg.json（e過程・e≥20）にそろえた: 事前に固定した賭けの大きさ λ・切り詰め B・
逆向きの e（見込みなし）・20年の打ち切り・いつ見ても有効な信頼の帯・族の e-BH と Bonferroni。重なる仮説（同じ規則）は入れていない。

段（事前登録 out/nx_forward_prereg.json の順番どおり）
  --design   : 設計値（σ_d・μ_d・B・λ）を登録前のデータ（≤2026-08）で計算して表示する＝事前登録に書き写した数字の出どころ
               （前向きのデータは使わない）。歴史の再現の検算（nx_indmom_real P2・nx_jpfunds X1 の国内株式）も出す
  --init     : 事前登録の凍結値を読み、2026-09 末の持ち物のうち決まっているものを記録し（決まらないものは『保留』と書く）、
               検出力（numpy）を計算 → out/nx_forward.json（前向きの月は 0・成績はまだ無い）
  --update   : 月次。保留の持ち物を確定（凍結）し、前向きの月（2026-10〜）を順に取り込んで e を更新 → out/nx_forward.json
               （標準ライブラリだけで回る。日本の投信の月は 投信総合検索ライブラリー の基準価額 CSV を取りに行く）
  --selftest : 合成データの点検（先読みなし・回転・e 過程の下限・Ville の不等式の模擬）

約束（事前登録どおり）
- 比べるのは同じ通貨の総リターンどうし（米国の器は米ドル・日本の投信は円）。月 m の値は m の月末が過ぎてから取り込む
- 一度取り込んだ月の値と、一度確定した持ち物は固定（後のデータ改訂は反映しない）＝逐次検定の前提を守る
- 欠測を 0 と読まない（絶対のルール7）: 値が無い月は待つ。3か月待っても出ない月は『欠測』として飛ばす（持ち物の一部が欠けたら外して残りで割り直す）
- 規則・相手・λ・B・μ_d は変えない（変えたら別の新しい登録として e=1 から）
"""
import sys, os, json, math, time, datetime, argparse, collections, statistics as S, urllib.parse, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N

BASE = N.BASE
PREREG = os.path.join(BASE, 'out', 'nx_forward_prereg.json')
OUT_NAME = 'nx_forward.json'
OUT = os.path.join(BASE, 'out', OUT_NAME)
FC = os.path.join(N.CACHE, 'nx_forward')          # この道具だけのキャッシュ（他の角度の凍結した抽出を上書きしない）
FIRST_FWD = 202610                                 # 最初の前向きの月（2026-10 の月次＝2026-09 末に持つ物の成績）
REG_MONTH = 202609                                 # 登録の月（2026-09 末の持ち物がこの登録の出発点）
DESIGN_END = 202608                                # 設計に使う最後の月（登録の日 2026-09-29 に完了していた最後の月）
MAX_END = 204609                                   # 20年で打ち切り（未決なら『証明できず』）
E_IND = 20.0                                       # 1本ずつの線（α=0.05・Ville の不等式）
WAIT_MONTHS = 3                                    # 値が出ない月はこの月数だけ待ってから『欠測』として飛ばす
CLIP_K = 4.0                                       # B = 4σ_m を 0.5% 単位で切り上げ
MU_HAIRCUT = 0.5                                   # 公表後の縮み（全セッションの実測 0.44〜0.56）
MU_LO, MU_HI = 0.5, 3.0                            # μ_d の下限・上限（%/年）
MU_FIXED_SUB = 1.0                                 # 副（QQQ が相手）の μ_d（検証済みの上乗せが無い＝検出したい最小の上乗せ）
REVIEW_MONTH = 10                                  # 正式に見る月（毎年10月・9月末までの12か月がそろった後）

# ───────────────────────── 規則の中身（事前登録と同じ・変えない） ─────────────────────────
# (1) 楽天の業種 ETF 20本（nx_indmom_real の U_all・etf_only の代表・1業種1本）。P2＝12か月（t−11〜t）の上位5本を等分・毎月
IND_NODE = {'INTERNET': 'FDN', 'S_REALEST': 'IYR', 'S_TECH': 'XLK', 'BIOTECH': 'IBB', 'SEMI': 'SMH', 'S_DISCR': 'XLY', 'S_UTIL': 'XLU',
            'S_ENERGY': 'XLE', 'S_MATER': 'XLB', 'S_FIN': 'XLF', 'AERODEF': 'ITA', 'S_HEALTH': 'XLV', 'S_STAPLES': 'XLP', 'S_COMM': 'VOX',
            'S_INDU': 'XLI', 'RETAIL': 'RTH', 'OILSVC': 'OIH', 'MLP': 'MLPA', 'PHARMA': 'PPH', 'MREIT': 'REM'}
IND_ETF = sorted(IND_NODE.values())
IND_START = {'SMH': 201201, 'OIH': 201201, 'PPH': 201201, 'RTH': 201201}   # HOLDRS からの切り替え（2011-12-20）より前は使わない（etf_only）
IND_K, IND_L, IND_ELIG, IND_MIN_N = 5, 12, 13, 10
IND_COST = 0.0010                                  # 片道の回転 100% あたり 0.10%（nx_indmom_real の主の費用）
# (2) Interbrand の最新の一覧の米国の親会社の上位10社をブランド価値で加重（年1回・公開の翌月末に組み替え）
BRAND_TOPN = 10
BRAND_COST = 0.0020                                # 片道の回転 100% あたり 0.20%（nx_brand の米国版の費用）
BRAND_FIRST_FORMATION = 202511                     # 2025年の一覧（公開 2025-10-15）の『公開の翌月末』
BRAND_FIRST_LIST_Y, BRAND_FIRST_RELEASE = 2025, '2025-10-15'
# (3) 日本の能動の投信の過去1年の上位1/4（nx_jpfunds X1・国内株式）。毎年9月の最後の基準価額の日に選び、10月〜翌9月に持つ
JP_RAKUTEN = '楽天証券'
JP_DEDUPE_RHO, JP_MIN_GROUP, JP_RETENTION = 0.995, 8, 0.003
JP_FIRST_Y = 2026                                  # 最初の前向きの選択（2026年9月末）
# (4) 市場＋マネージド・フューチャーズの重ね（実在: RSST = 米国株100%＋マネージド・フューチャーズ100%）
# (5) 国の配当利回りの上位1/3（nx_jst P1 を実在の国別 ETF で・PGAL は上場廃止で Yahoo に無い＝15本）
CTRY_ETF = {'AUS': 'EWA', 'BEL': 'EWK', 'CHE': 'EWL', 'DEU': 'EWG', 'ESP': 'EWP', 'FRA': 'EWQ', 'GBR': 'EWU', 'ITA': 'EWI', 'JPN': 'EWJ',
            'NLD': 'EWN', 'SWE': 'EWD', 'DNK': 'EDEN', 'FIN': 'EFNL', 'NOR': 'ENOR', 'USA': 'SPY'}
CTRY_COST = 0.0010
CTRY_MIN_N = 6
CTRY_FIRST_Y = 2025                                # 登録の月に持っている形成（2025年12月末）

HYP = {
    'F1_indmom_vs_SPY': {
        'ja': '楽天の業種 ETF 20本（1業種1本）で 12か月（t−11〜t）の上位5本を等分・毎月の入れ替え（nx_indmom_real P2 そのまま）対 SPY',
        'port': 'indmom', 'bench': 'SPY', 'family': 'main', 'ccy': 'USD', 'cost': IND_COST,
        'mu_rule': ('counterpart', 'fr49_P2'), 'holdable': '楽天で全部買える（20本と SPY は楽天の海外 ETF の一覧〔ETFD.csv 2026-09-28〕にある）。NISA 成長投資枠でも課税口座でも可。ただし毎月の入れ替えで NISA の枠を食う'},
    'F1b_indmom_vs_QQQ': {
        'ja': '同じ規則 対 QQQ（副・判定に使わない）', 'port': 'indmom', 'bench': 'QQQ', 'family': 'sub', 'ccy': 'USD', 'cost': IND_COST,
        'mu_rule': ('fixed', MU_FIXED_SUB), 'holdable': '同上'},
    'F2_brand10_vs_SPY': {
        'ja': 'Interbrand の最新の一覧の米国の親会社の上位10社をブランド価値で加重・公開の翌月末に年1回組み替え（間は買って持つ）対 SPY（nx_brand P2 の実装できる版）',
        'port': 'brand', 'bench': 'SPY', 'family': 'main', 'ccy': 'USD', 'cost': BRAND_COST,
        'mu_rule': ('insample', 'nx_brand P2'), 'holdable': '楽天の米国株で10社とも買える（米国の超大型株）。NISA 成長投資枠でも課税口座でも可'},
    'F2b_brand10_vs_QQQ': {
        'ja': '同じ規則 対 QQQ（副・判定に使わない）', 'port': 'brand', 'bench': 'QQQ', 'family': 'sub', 'ccy': 'USD', 'cost': BRAND_COST,
        'mu_rule': ('fixed', MU_FIXED_SUB), 'holdable': '同上'},
    'F3_jpX1_rakuten_vs_TOPIX': {
        'ja': '国内株式の能動の投信の過去1年の上位1/4（nx_jpfunds X1 の選び方そのまま・母集団は全部）のうち楽天証券が売るものを等分（毎月等分に戻す）・毎年9月末に選び直し 対 楽天で買える最も安い TOPIX の指数型の投信（円）',
        'port': 'jpx1_rakuten', 'bench': None, 'family': 'main', 'ccy': 'JPY', 'cost': None,
        'mu_rule': ('insample', 'nx_jpfunds X1 国内株式'), 'holdable': '楽天で全部買える（選んだものから楽天が売らない器を外す）。NISA 成長投資枠の対象は約7割（毎月分配型などは対象外＝課税口座）'},
    'F3b_jpX1_all_vs_TOPIX': {
        'ja': '同じ選び方の全部（楽天で買えない器も含む・nx_jpfunds X1 そのまま）対 最も安い TOPIX の指数型（副・判定に使わない）',
        'port': 'jpx1_all', 'bench': None, 'family': 'sub', 'ccy': 'JPY', 'cost': None,
        'mu_rule': ('insample', 'nx_jpfunds X1 国内株式'), 'holdable': '一部は楽天で買えない（約3割）'},
    'F4_RSST_vs_SPY': {
        'ja': '市場＋マネージド・フューチャーズの重ね（実在: RSST＝米国株100%＋マネージド・フューチャーズ100%）対 SPY（参考・楽天で持てない）',
        'port': 'rsst', 'bench': 'SPY', 'family': 'ref', 'ccy': 'USD', 'cost': 0.0,
        'mu_rule': ('counterpart', 'nx_stack P6'), 'holdable': '★楽天では持てない（RSST・DBMF・KMLM・CTA は楽天の海外 ETF の一覧〔2026-09-28〕に無い）。NISA では持てない'},
    'F5_countryDY_vs_ACWI': {
        'ja': '国の配当利回り（直近の暦年の分配÷年末の値）の上位1/3の国別 ETF（15本）を等分・毎年12月末に組み替え（間は買って持つ）対 ACWI（参考・楽天で持てない）',
        'port': 'country', 'bench': 'ACWI', 'family': 'ref', 'ccy': 'USD', 'cost': CTRY_COST,
        'mu_rule': ('counterpart', 'nx_jst P1'), 'holdable': '★楽天では持てない（15本のうち楽天にあるのは EWJ・EWG・SPY だけ）'},
}
ORDER = list(HYP)
FAMILIES = {'main': [h for h in ORDER if HYP[h]['family'] == 'main'],
            'sub': [h for h in ORDER if HYP[h]['family'] == 'sub'],
            'ref': [h for h in ORDER if HYP[h]['family'] == 'ref']}
LINES = {'main': E_IND * len(FAMILIES['main']), 'sub': E_IND * len(FAMILIES['sub']), 'ref': E_IND * len(FAMILIES['ref']),
         'all_registered': E_IND * len(ORDER)}
ESKNZBH_K = 8                                      # eknzbh の mw_forward の仮説の数（全セッションの線の参考）


# ───────────────────────── 月の小道具 ─────────────────────────
def nextm(k):
    y, m = divmod(k, 100)
    return (y + 1) * 100 + 1 if m == 12 else k + 1


def addm(k, n):
    y, m = divmod(k, 100)
    m0 = y * 12 + (m - 1) + n
    return (m0 // 12) * 100 + m0 % 12 + 1


def months(a, z):
    out, k = [], a
    while k <= z:
        out.append(k); k = nextm(k)
    return out


def mlen(k):
    y, m = divmod(k, 100)
    return (datetime.date(y + (m == 12), m % 12 + 1, 1) - datetime.date(y, m, 1)).days


def month_end_date(k):
    y, m = divmod(k, 100)
    return datetime.date(y, m, mlen(k))


def today():
    v = os.environ.get('NXF_TODAY')                 # 点検だけに使う（通常は空）
    if v:
        return datetime.date.fromisoformat(v)
    return datetime.datetime.now(datetime.timezone.utc).date()


def today_ym():
    d = today()
    return d.year * 100 + d.month


def overdue(m):
    """月 m の値を WAIT_MONTHS より長く待った（以後は欠測として飛ばしてよい）"""
    t = today_ym()
    return (t // 100 * 12 + t % 100) - (m // 100 * 12 + m % 100) > WAIT_MONTHS


def ymd_int(d):
    return d.year * 10000 + d.month * 100 + d.day


def norm_w(w):
    t = sum(w.values())
    return {k: v / t for k, v in w.items()} if t > 0 else {}


def turnover(new, old):
    """片道の回転 = ½Σ|新しい重み − 持っていた重み（当月のリターンで流した後）|"""
    ks = set(new) | set(old)
    return 0.5 * sum(abs(new.get(k, 0.0) - old.get(k, 0.0)) for k in ks)


def drift(w, r):
    """重み w を当月のリターン r で流す（値の無い器は 0%＝現金のまま）→ 正規化した重み"""
    return norm_w({k: v * (1 + (r.get(k) if r.get(k) is not None else 0.0)) for k, v in w.items()})


# ───────────────────────── Yahoo（日足の調整後終値 → 完了した月の月末） ─────────────────────────
_YH = {}


def yh(ticker, max_age=1.0):
    """→ {'rows': [(yyyymmdd, 調整後終値, 終値)], 'divs': [(yyyymmdd, 分配)]}。欠けた足は捨てる（0 と読まない）"""
    key = (ticker, max_age)
    if key in _YH:
        return _YH[key]
    u = (f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}'
         f'?period1=0&period2={int(time.time())}&interval=1d&events=div%2Csplit')
    safe = ticker.replace('^', 'IDX_').replace('=', '_')
    try:
        j = json.loads(N.get(u, name=f'nxf_yh_{safe}_1d.json', max_age_days=max_age))
        r = j['chart']['result'][0]
    except Exception:  # noqa
        _YH[key] = None
        return None
    ts = r.get('timestamp') or []
    q = r['indicators']['quote'][0]
    adj = (r['indicators'].get('adjclose') or [{}])[0].get('adjclose') or q['close']
    rows = []
    for t_, a, c in zip(ts, adj, q['close']):
        if a is None or a <= 0:
            continue
        d = datetime.datetime.fromtimestamp(t_, datetime.timezone.utc)
        rows.append((ymd_int(d), a, c))
    rows.sort()
    divs = []
    for ev in ((r.get('events') or {}).get('dividends') or {}).values():
        d = datetime.datetime.fromtimestamp(ev['date'], datetime.timezone.utc)
        divs.append((ymd_int(d), float(ev['amount'])))
    divs.sort()
    _YH[key] = {'rows': rows, 'divs': divs}
    return _YH[key]


_ME = {}


def month_ends(ticker, max_age=1.0, upto=None):
    """完了した月だけの月末 {yyyymm: (日付, 調整後, 終値)}。完了 = 当月より前 ∧ 最後の足が月末の5日以内 ∧
    （その後の月の足がある か 月末から5日以上たった）"""
    key = (ticker, max_age, upto)
    if key not in _ME:
        _ME[key] = _month_ends(ticker, max_age, upto)
    return _ME[key]


def _month_ends(ticker, max_age, upto):
    y = yh(ticker, max_age)
    if not y or not y['rows']:
        return {}
    last = {}
    for d, a, c in y['rows']:
        last[d // 100] = (d, a, c)
    mx, td, cur = max(last), today(), today_ym()
    out = {}
    for m, v in last.items():
        if (upto is not None and m > upto) or m >= cur:
            continue
        if v[0] % 100 < mlen(m) - 5:
            continue
        if m < mx or (td - month_end_date(m)).days >= 5:
            out[m] = v
    return out


_MR = {}


def mret(ticker, max_age=1.0, upto=None):
    """→ {yyyymm: 月次の総リターン}（続いた2つの完了した月末の比）"""
    key = (ticker, max_age, upto)
    if key not in _MR:
        me = month_ends(ticker, max_age, upto)
        ks = sorted(me)
        _MR[key] = {b: me[b][1] / me[a][1] - 1 for a, b in zip(ks, ks[1:]) if nextm(a) == b}
    return _MR[key]


def first_bar(ticker, max_age=1.0):
    y = yh(ticker, max_age)
    return y['rows'][0][0] if y and y['rows'] else None


# ───────────────────────── (1) 業種の勢い ─────────────────────────
def ind_start(t, r):
    s = min(r) if r else None
    return None if s is None else max(s, IND_START.get(t, s))


def ind_pick(R, starts, t, univ=None, K=IND_K, min_n=IND_MIN_N):
    """形成の月末 t の持ち物（t までのリターンだけ）。候補 = t−12〜t の13か月すべてに値があり、どれも始まり以降。
    点数 = t−11〜t の12か月の累積。上位 K（同点は記号の順）"""
    univ = univ or IND_ETF
    need = months(addm(t, -(IND_ELIG - 1)), t)
    cands = sorted(k for k in univ if starts.get(k) is not None and need[0] >= starts[k] and all(m in R[k] for m in need))
    if len(cands) < min_n:
        return None, cands, {}
    look = months(addm(t, -(IND_L - 1)), t)
    sc = {k: math.prod(1 + R[k][m] for m in look) - 1 for k in cands}
    sel = sorted(cands, key=lambda k: (-sc[k], k))[:K]
    return sel, cands, sc


def ind_hist(max_age=3.0, univ=None, R=None, a=199901, z=DESIGN_END):
    """歴史（設計用）: {持つ月 m: (規則のリターン, 回転)}。最初の形成の回転は 1（nx_indmom_real と同じ）"""
    univ = univ or IND_ETF
    if R is None:
        R = {k: mret(k, max_age, DESIGN_END) for k in univ}
    starts = {k: ind_start(k, R[k]) for k in univ}
    out, prev = {}, None
    for t in months(a, addm(z, -1)):
        sel, _, _ = ind_pick(R, starts, t, univ)
        if sel is None:
            prev = None
            continue
        m = nextm(t)
        vals = [R[k][m] for k in sel if m in R[k]]
        if not vals:
            continue
        new = {k: 1 / len(sel) for k in sel}
        tv = 1.0 if prev is None else turnover(new, drift({k: 1 / len(prev) for k in prev}, {k: R[k].get(t) for k in prev}))
        out[m] = (sum(vals) / len(vals), tv)
        prev = sel
    return out


def fr49_counterpart():
    """≤2006-12 の紙の相手: French 49 業種（VW・CRSP 全上場）に同じ規則（13か月の条件・12か月の上位5・等分・毎月）− French Mkt"""
    s49 = N.french_series('49_Industry_Portfolios', 'Value Weight')
    mk = N.ff_factors()['mkt']
    univ = sorted(s49)
    R = {k: dict(v) for k, v in s49.items()}
    h = ind_hist(univ=univ, R=R, a=192607, z=200612)
    ms = [m for m in sorted(h) if m in mk and m <= 200612]
    x = [h[m][0] - mk[m] for m in ms]
    return {'mu_pre': round(S.mean(x) * 1200, 3), 'from': ms[0], 'to': ms[-1], 'n': len(ms),
            'te_pre': round(S.stdev(x) * math.sqrt(12) * 100, 3), 't_nw': round(N.nw_t(x), 2),
            'what': 'French 49 業種（Average Value Weighted Returns -- Monthly）に F1 と同じ規則（13か月の条件・12か月＝t−11〜t の上位5・等分・毎月・候補10以上）− French Mkt（Mkt-RF + RF）。費用前'}


# ───────────────────────── (2) ブランド ─────────────────────────
def _B():
    import nx_brand_data as B
    return B


def brand_rank(rows, fm, has_price):
    """一覧の行 → 形成の月 fm の米国の親会社（NYSE/Nasdaq が主な上場）ごとのブランド価値の合計 → 値のある上位 BRAND_TOPN。
    has_price(ticker) = 形成の月末に値があるか（買えない親会社は飛ばして次へ＝常に10社）"""
    B = _B()
    val, tick = {}, {}
    for r in rows:
        pid = B.ib_owner(r['name'], fm)
        p = B.P.get(pid) if pid else None
        if not p or not p['us'] or not p['yahoo']:
            continue
        val[pid] = val.get(pid, 0) + (r['value'] or 0)
    top = []
    for pid in sorted(val, key=lambda k: (-val[k], k)):
        tk = next((t for t in B.P[pid]['yahoo'] if has_price(t)), None)
        if tk is None:
            continue
        top.append(pid); tick[pid] = tk
        if len(top) == BRAND_TOPN:
            break
    return {tick[p]: val[p] for p in top}, {p: tick[p] for p in top}


def brand_hist_forms():
    """設計用: 過去の一覧（nx_brand の凍結の一覧・2015/2017 は持ち越し）→ [(形成の月, 一覧の年, 行)]。
    形成の月 = nx_brand の買う月（公開の後の最初の月末）の翌月＝『公開の翌月末』"""
    d = json.load(open(os.path.join(N.CACHE, 'nx_brand_lists.json')))
    ib = d['interbrand']
    out = []
    for s in ib['schedule']:
        if not s.get('used'):
            continue
        y = s['list_year']
        rows = [{'name': r['name'], 'value': r['value']} for r in ib['years'][str(y)]['rows']]
        out.append((addm(s['buy_month'], 1), y, rows))
    return sorted(out)


def brand_hist(max_age=3.0):
    """設計用の歴史: {m: (規則のリターン, 回転)}（上位10社・ブランド価値の加重・間は買って持つ・値の無い月は 0%＝現金）"""
    forms = brand_hist_forms()
    R, out = {}, {}

    def r_of(t):
        if t not in R:
            R[t] = mret(t, max_age, DESIGN_END)
        return R[t]
    w = None
    for i, (fm, y, rows) in enumerate(forms):
        end = forms[i + 1][0] if i + 1 < len(forms) else DESIGN_END
        tgt, _ = brand_rank(rows, fm, lambda t: fm in month_ends(t, max_age, DESIGN_END))
        tgt = norm_w(tgt)
        tv = 1.0 if w is None else turnover(tgt, w)     # w は形成の月末まで流した重み（2026-09-29 是正: 旧版は同じ月で二度流していた）
        w = tgt
        for m in months(nextm(fm), end):
            r = {k: r_of(k).get(m) for k in w}
            s = sum(v * (r[k] if r[k] is not None else 0.0) for k, v in w.items())
            out[m] = (s, tv if m == nextm(fm) else 0.0)
            w = drift(w, r)
    return out


def ib_api_year(y):
    """Interbrand の API。★year=Y の一覧がまだ無いと、API は最新の年の一覧をそのまま返す（2026-09-29 に year=2026 で 2025 の行が返った）
    ＝行の year がすべて Y で100行あるときだけ『Y の一覧』とみなす"""
    B = _B()
    try:
        j = json.loads(N.get(B.IB_API.format(y=y), name=f'nxf_ib_api_{y}.json', max_age_days=0.5))
    except Exception as e:  # noqa
        return None, f'取得失敗 {e}'
    d = j.get('data') or []
    ys = {x.get('year') for x in d}
    if len(d) == 100 and ys == {y}:
        return [{'rank': x['rank'], 'name': x['brandName'], 'value': x['brandValue']} for x in d], 'ok'
    return None, f'year={y} の一覧は未公開（行 {len(d)}・year の値 {sorted(ys)}）'


# ───────────────────────── (3) 日本の能動の投信（X1・国内株式） ─────────────────────────
def _D():
    import nx_jpfunds_data as D
    D.CUTOFF = 20991231                            # この工程の中だけ（凍結した nx_jpfunds の測定には触れない）
    return D


JP_KEEP = ['associFundCd', 'isinCd', 'fundNm', 'fundNkNm', 'fundCategory', 'supplementKindCd', 'unitOpenDiv', 'dcFundFlg', 'trustReward',
           'establishedDate', 'retentionMoneyCd', 'nisaGrowthFlg', 'nisaFlg', 'redemptionDate', 'buyFee'] + [f'investArea10kindCd{i}' for i in range(1, 11)]


def jp_universe(tag):
    """投信総合検索ライブラリーの今の一覧（全件）を tag（取得日）で保存。販売会社の名前と手数料（institutionInfo）も残す"""
    os.makedirs(FC, exist_ok=True)
    p = os.path.join(FC, f'jp_universe_{tag}.json')
    if os.path.exists(p):
        return json.load(open(p))
    D = _D()
    lib = D.Lib()
    rows, total, std = lib.search_all()
    keep = []
    for r in rows:
        x = {k: r.get(k) for k in JP_KEEP}
        x['inst'] = [[i.get('instName'), i.get('salesFee')] for i in (r.get('institutionInfo') or [])]
        keep.append(x)
    doc = {'fetched_at': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'), 'standardDate': std, 'recordsTotal': total, 'rows': keep}
    tmp = p + '.tmp'
    json.dump(doc, open(tmp, 'w'), ensure_ascii=False)
    os.replace(tmp, p)
    return doc


def jp_nav(assoc, isin, max_age_h=12.0, lib=None):
    """基準価額の CSV（この道具のキャッシュ・max_age_h 時間より古ければ取り直す）→ 日次の行。HTTP 500（償還・消えた）は None"""
    D = _D()
    d = os.path.join(FC, 'jpnav')
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f'{assoc}.csv')
    if not (os.path.exists(p) and time.time() - os.path.getmtime(p) < max_age_h * 3600 and os.path.getsize(p) > 0):
        lib = lib or D.Lib()
        b = lib.csv(isin, assoc)
        time.sleep(1.1)
        if b is None:                                   # HTTP 500（償還・消えた）: 前に取った写しがあればそれを使う（無ければ None）
            return D.parse_csv(open(p, 'rb').read())[0] if os.path.exists(p) and os.path.getsize(p) > 0 else None
        open(p + '.tmp', 'wb').write(b)
        os.replace(p + '.tmp', p)
    return D.parse_csv(open(p, 'rb').read())[0]


def jp_months(daily):
    """日次 → {yyyymm: 月次の総リターン}（完了した月だけ＝その後の月の行がある月）と {yyyymm: 月末の純資産}"""
    D = _D()
    if not daily:
        return {}, {}
    mon = D.monthly_tr(daily)
    last_m = daily[-1][0] // 100
    return {m: v for m, v in mon.items() if m < last_m}, D.month_end_net_assets(daily)


def _sales_fee(row, who):
    fees = []
    for nm, f in row.get('inst') or []:
        if who is not None and nm != who:
            continue
        try:
            fees.append(float(f))
        except (TypeError, ValueError):
            pass
    return min(fees) / 100 * 1.1 if fees else None


def jp_select(y, rows, navs):
    """y 年9月の選択（nx_jpfunds の X1＝振り返り1年・上位1/4 を国内株式で）。navs = {協会コード: (月次, 月末の純資産)}。
    重複の除去は同じ委託会社（協会コードの先頭2文字）で振り返りの月次の相関 ≥0.995 を単連結で束ね、t の純資産が最大の1本を残す"""
    D = _D()
    t = y * 100 + 9
    look = months((y - 1) * 100 + 10, t)
    by = {r['associFundCd']: r for r in rows}
    elig = sorted(a for a, r in by.items() if D.category(r) == 'JP' and D.kind(r) == 'active' and D.passes_filter(r)
                  and a in navs and all(m in navs[a][0] for m in look))
    parent = {a: a for a in elig}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    by_mgr = collections.defaultdict(list)
    for a in elig:
        by_mgr[a[:2]].append(a)
    for lst in by_mgr.values():
        for i in range(len(lst)):
            xi = [navs[lst[i]][0][m] for m in look]
            for j in range(i + 1, len(lst)):
                if N.corr(xi, [navs[lst[j]][0][m] for m in look]) >= JP_DEDUPE_RHO:
                    ri, rj = find(lst[i]), find(lst[j])
                    if ri != rj:
                        parent[ri] = rj
    groups = collections.defaultdict(list)
    for a in elig:
        groups[find(a)].append(a)
    na = lambda a: navs[a][1].get(t) if navs[a][1].get(t) is not None else -1.0  # noqa: E731
    after = sorted(max(g, key=lambda a: (na(a), a)) for g in groups.values())
    score = {a: math.prod(1 + navs[a][0][m] for m in look) - 1 for a in after}
    n = len(after)
    if n < JP_MIN_GROUP:
        return None, {'n': n, 'eligible_before_dedupe': len(elig)}
    k = math.ceil(n / 4)
    sel = sorted(after, key=lambda a: (-score[a], -na(a), a))[:k]
    return sel, {'n': n, 'k': k, 'eligible_before_dedupe': len(elig), 'clusters': sum(1 for g in groups.values() if len(g) > 1),
                 'score_cut_pct': round(score[sel[-1]] * 100, 2) if sel else None}


def jp_comparator(rows, navs, t, rakuten):
    """相手: 国内株式の TOPIX の指数型（nx_jpfunds_data.comparator_candidates の名前の規則）のうち、t に月次があり、
    今の信託報酬（税抜）が最も安いもの（同じなら設定が古いもの）。rakuten=True なら楽天証券が売るものだけ"""
    D = _D()
    c = D.comparator_candidates(rows, 'JP')
    if rakuten:
        c = [r for r in c if any(nm == JP_RAKUTEN for nm, _ in r.get('inst') or [])]
    c = [r for r in c if r['associFundCd'] in navs and t in navs[r['associFundCd']][0]]
    c.sort(key=lambda r: (float(r.get('trustReward') or 9), r.get('establishedDate') or ''))
    return c[0]['associFundCd'] if c else None


def jp_hist_x1_jp():
    """設計用: nx_jpfunds の X1（凍結の選択 holdings_by_rule）の国内株式だけを、同じ道具の基準価額と相手の鎖で作り直す（費用前）"""
    import nx_jpfunds as JF
    D = JF.D
    D.CUTOFF = 20260831
    u, rows, F = JF.load_library()
    chain, _ = JF.comparator_chain(rows, F, 'JP', None, None)
    J = {'JP': D.msci_jpy(939200)}
    comp_s, src, fills = JF.chain_series(chain, F, 'JP', J)
    hold_all = json.load(open(os.path.join(BASE, 'out', 'nx_jpfunds.json')))['holdings_by_rule']['X1_top_q_1y']
    hold = {int(y): [a for a in lst if a in F and F[a]['cat'] == 'JP'] for y, lst in hold_all.items()}
    s, b, w = JF.portfolio(F, hold, {'JP': comp_s}, cats={'JP'})
    return {m: (s[m], b[m]) for m in s}, {'comparator_chain': chain, 'fills': len(fills), 'n_held_2025': len(hold.get(2025, []))}


# ───────────────────────── (5) 国の配当利回り ─────────────────────────
def ctry_dy(tk, y, max_age=1.0):
    """暦年 y の分配の合計 ÷ 12月の最後の終値（未調整）。その年の1月1日より前に上場していた器だけ（1年に満たない分配を使わない）"""
    fb = first_bar(tk, max_age)
    me = month_ends(tk, max_age)
    if fb is None or fb > y * 10000 + 101 or (y * 100 + 12) not in me:
        return None
    dv = sum(a for d, a in yh(tk, max_age)['divs'] if d // 10000 == y)
    c = me[y * 100 + 12][2]
    return dv / c if c else None


def ctry_form(y, max_age=1.0):
    """y 年12月末の形成: 配当利回りの上位 ceil(n/3)（同点は国の記号の順）"""
    dy = {c: ctry_dy(tk, y, max_age) for c, tk in CTRY_ETF.items()}
    el = sorted(c for c, v in dy.items() if v is not None)
    if len(el) < CTRY_MIN_N:
        return None, dy
    sel = sorted(el, key=lambda c: (-dy[c], c))[:math.ceil(len(el) / 3)]
    return sel, dy


def ctry_hist(max_age=3.0, a=2008, bench=None):
    """設計用: {m: (規則のリターン, 回転)}（y 年12月末に組み、翌年は買って持つ）"""
    out, w = {}, None
    R = {c: mret(tk, max_age, DESIGN_END) for c, tk in CTRY_ETF.items()}
    for y in range(a, DESIGN_END // 100 + 1):
        sel, _ = ctry_form(y, max_age)
        ms = [m for m in months((y + 1) * 100 + 1, (y + 1) * 100 + 12) if m <= DESIGN_END]
        if sel is None or not ms:
            continue
        tgt = {c: 1 / len(sel) for c in sel}
        tv = 1.0 if w is None else turnover(tgt, w)     # w は12月末まで流した重み（同上の是正）
        w = tgt
        for m in ms:
            r = {c: R[c].get(m) for c in w}
            out[m] = (sum(v * (r[c] if r[c] is not None else 0.0) for c, v in w.items()), tv if m == ms[0] else 0.0)
            w = drift(w, r)
    return out


def ctry_annual_check(max_age=3.0):
    """検算（報告）: nx_jst の器の答え合わせ（P1・年次・相手は器の等分・1997〜2025）と同じ形を、この道具のデータで作り直す"""
    yr, dy = {}, {}
    for c, tk in CTRY_ETF.items():
        me = month_ends(tk, max_age, DESIGN_END)
        dec = {m // 100: v for m, v in me.items() if m % 100 == 12}
        for y in dec:
            if y - 1 in dec:
                yr.setdefault(c, {})[y] = dec[y][1] / dec[y - 1][1] - 1
            dv = sum(a for d, a in yh(tk, max_age)['divs'] if d // 10000 == y)
            dy.setdefault(c, {})[y] = dv / dec[y][2]
    s, b = {}, {}
    for y in range(1997, 2026):
        xs = [yr[c][y] for c in yr if y in yr[c]]
        if len(xs) < 6:
            continue
        b[y] = S.mean(xs)
        sig = {c: dy[c][y - 1] for c in yr if y in yr[c] and (y - 1) in dy.get(c, {})}
        if len(sig) < 6:
            continue
        sel = sorted(sig, key=lambda c: (-sig[c], c))[:math.ceil(len(sig) / 3)]
        s[y] = S.mean(yr[c][y] for c in sel)
    ks = sorted(set(s) & set(b))
    gs = math.exp(sum(math.log1p(s[k]) for k in ks) / len(ks)) - 1
    gb = math.exp(sum(math.log1p(b[k]) for k in ks) / len(ks)) - 1
    return {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'ex_ann': round(S.mean(s[k] - b[k] for k in ks) * 100, 2),
            'cagr_diff': round((gs - gb) * 100, 2), 'nx_jst_reported': {'ex_ann': -0.39, 'cagr_diff': -0.73, 'from': 1997, 'to': 2025, 'n': 29},
            'note': 'nx_jst は PGAL（ポルトガル）を含む16本・月足・分配は Yahoo の月足の events。ここは PGAL が Yahoo から消えた15本・日足'}


# ───────────────────────── 設計（登録前のデータだけ） ─────────────────────────
def hist_active(h, max_age=3.0, cache=None):
    """設計用の過去の追従差（月次・費用控除後）→ ({m: x}, 出どころ)"""
    cache = cache if cache is not None else {}
    d = HYP[h]
    p = d['port']
    if p == 'indmom':
        if 'indmom' not in cache:
            cache['indmom'] = ind_hist(max_age)
        s = cache['indmom']
        b = mret(d['bench'], max_age, DESIGN_END)
        x = {m: s[m][0] - b[m] - s[m][1] * d['cost'] for m in s if m in b}
        return x, '楽天の業種 ETF 20本の P2 を日足の月末から作り直した（2001-08〜2026-08・etf_only）'
    if p == 'brand':
        if 'brand' not in cache:
            cache['brand'] = brand_hist(max_age)
        s = cache['brand']
        b = mret(d['bench'], max_age, DESIGN_END)
        x = {m: s[m][0] - b[m] - s[m][1] * d['cost'] for m in s if m in b}
        return x, 'nx_brand の凍結の一覧（2007〜2025・2015/2017 は持ち越し）で上位10社版を作り直した（公開の翌月末に組み替え）'
    if p in ('jpx1_rakuten', 'jpx1_all'):
        if 'jp' not in cache:
            cache['jp'] = jp_hist_x1_jp()
        sb, _ = cache['jp']
        return {m: v[0] - v[1] for m, v in sb.items()}, ('nx_jpfunds の X1 の凍結の選択の国内株式だけ・相手は最も安い TOPIX の指数型の鎖（費用前・楽天の絞り込みは過去に遡れないので同じ系列）')
    if p == 'rsst':
        a = mret('RSST', max_age, DESIGN_END)
        b = mret('SPY', max_age, DESIGN_END)
        x1 = {m: a[m] - b[m] for m in a if m in b}
        dm, bl = mret('DBMF', max_age, DESIGN_END), mret('BIL', max_age, DESIGN_END)
        x2 = {m: dm[m] - bl[m] for m in dm if m in bl}
        s1 = S.stdev(x1.values()) if len(x1) > 2 else 0
        s2 = S.stdev(x2.values()) if len(x2) > 2 else 0
        cache['rsst_proxy'] = {'rsst_minus_spy': {'n': len(x1), 'sd_ann_pct': round(s1 * math.sqrt(12) * 100, 3), 'from': min(x1), 'to': max(x1)},
                               'dbmf_minus_bil': {'n': len(x2), 'sd_ann_pct': round(s2 * math.sqrt(12) * 100, 3), 'from': min(x2), 'to': max(x2)}}
        if s2 > s1:
            return x2, 'RSST の履歴（2023-10〜）は35か月しか無いので、追従のぶれの大きい方＝DBMF − BIL（重ねる部分の代わり・2019-06〜）を使う'
        return x1, 'RSST − SPY（2023-10〜）'
    if p == 'country':
        if 'country' not in cache:
            cache['country'] = ctry_hist(max_age)
        s = cache['country']
        b = mret(d['bench'], max_age, DESIGN_END)
        x = {m: s[m][0] - b[m] - s[m][1] * d['cost'] for m in s if m in b}
        return x, '15本の国別 ETF で 2008年末から毎年組み直した（直近の暦年の分配 ÷ 12月末の終値）'
    raise ValueError(p)


def mu_source(h, cps):
    d = HYP[h]
    kind, key = d['mu_rule']
    if kind == 'fixed':
        return key, None
    if key not in cps:
        if key == 'fr49_P2':
            cps[key] = fr49_counterpart()
        elif key == 'nx_brand P2':
            t = [x for x in json.load(open(os.path.join(BASE, 'out', 'nx_brand.json')))['tested'] if x['id'].startswith('P2')][0]
            cps[key] = {'mu_pre': t['full']['ex_ann'], 'from': t['full']['from'], 'to': t['full']['to'],
                        'what': 'nx_brand P2（米国の親会社の全部をブランド価値で加重・2007-09〜2026-08）の算術の超過。★登録前の2007年以降のデータ（歴史の勝ちを選ぶのに使ったのと同じ期間）＝賭けの大きさにだけ効く（有効性には効かない）'}
        elif key == 'nx_jpfunds X1 国内株式':
            ph = json.load(open(os.path.join(BASE, 'out', 'nx_jpfunds.json')))['post_hoc_diagnostics']['PH9_JP_only']['X1_top_q_1y']['full']
            cps[key] = {'mu_pre': ph['ex_ann'], 'from': ph['from'], 'to': ph['to'], 'te': ph['te'],
                        'what': 'nx_jpfunds X1 の国内株式だけ（PH9・事後の部分集合・2007-10〜2026-08）の算術の超過。★登録前の同じ期間＝賭けの大きさにだけ効く'}
        elif key == 'nx_stack P6':
            t = [x for x in json.load(open(os.path.join(BASE, 'out', 'nx_stack.json')))['tested'] if str(x.get('id', '')).startswith('P6')][0]
            g = t['gross']['train']
            cps[key] = {'mu_pre': g['ex_ann'], 'from': g['from'], 'to': g['to'], 'te_pre': g['te'],
                        'what': 'nx_stack P6（AQR の時系列の勢い 58先物・訓練のぶれで10%に合わせて市場に重ねる）の訓練期間 1985-01〜2006-12 の算術の超過（費用前）'}
        elif key == 'nx_jst P1':
            v = [x for x in json.load(open(os.path.join(BASE, 'out', 'nx_jst.json')))['tested'] if x.get('rule') == 'P1_dy_top3rd'][0]['views']['main']['train_gross']
            cps[key] = {'mu_pre': v['ex_ann'], 'from': v['from'], 'to': v['to'], 'te_pre': v['te'],
                        'what': 'nx_jst P1（JST 16か国・年末の配当利回りの上位1/3・等分・実質）の訓練期間 1871〜1949 の算術の超過（費用前・年次）'}
        else:
            raise KeyError(key)
    cp = cps[key]
    return min(MU_HI, max(MU_LO, MU_HAIRCUT * cp['mu_pre'])), key


def design(max_age=3.0):
    out, cps, cache, src = {}, {}, {}, {}
    for h in ORDER:
        x, how = hist_active(h, max_age, cache)
        ms = sorted(x)
        v = [x[m] for m in ms]
        sd = S.stdev(v) * math.sqrt(12) * 100
        mu_d, cp = mu_source(h, cps)
        sm = sd / 100 / math.sqrt(12)
        B = math.ceil(CLIP_K * sm / 0.005 - 1e-12) * 0.005
        lam_k = (mu_d / 100) / (sd / 100) ** 2
        lam = min(lam_k, 1 / (2 * B))
        out[h] = {'sigma_d': round(sd, 3), 'sigma_window': [ms[0], ms[-1]], 'n_months': len(ms), 'sigma_source': how,
                  'mu_d': round(mu_d, 3), 'mu_source': cp if cp else f'fixed {mu_d}', 'B': round(B, 4),
                  'lambda_kelly': round(lam_k, 3), 'lambda': round(lam, 3), 'lambda_capped': lam < lam_k, 'mu_f': round(mu_d, 3),
                  'clipped_months_hist': sum(1 for q in v if abs(q) > B),
                  'hist_mean_ann_pct': round(S.mean(v) * 1200, 3), 'hist_nw_t': round(N.nw_t(v), 2) if len(v) >= 24 else None}
        src[h] = x
    return out, cps, cache, src


def sanity(cache, max_age=3.0):
    """歴史の再現の検算（登録前のデータ）: 規則を正しく写したかを、元の角度の結果と比べる"""
    out = {}
    if 'indmom' in cache:
        s = cache['indmom']
        spy = mret('SPY', max_age, DESIGN_END)
        ms = [m for m in sorted(s) if 200108 <= m <= 202608 and m in spy]
        st = N.excess_stats({m: s[m][0] for m in ms}, {m: spy[m] for m in ms})
        out['F1_vs_nx_indmom_real_P2'] = {'this_tool_gross_2001_08_2026_08': st,
                                          'nx_indmom_real_reported': {'cagr_diff': 3.37, 'ex_ann': 3.09, 't': 2.16, 'te': 7.81, 'months': 301},
                                          'note': 'nx_indmom_real は月足の凍結の抽出・ここは今日の日足の月末（配当の調整の差が出うる）'}
    if 'jp' in cache:
        sb, info = cache['jp']
        st = N.excess_stats({m: v[0] for m, v in sb.items()}, {m: v[1] for m, v in sb.items()})
        out['F3_vs_nx_jpfunds_X1_JP'] = {'this_tool_gross': st, 'nx_jpfunds_PH9_reported': {'ex_ann': 3.5, 't': 3.12, 'te': 5.95, 'cagr_diff': 3.69, 'months': 227},
                                         'n_held_2025_JP': info['n_held_2025']}
    if 'brand' in cache:
        s = cache['brand']
        spy = mret('SPY', max_age, DESIGN_END)
        qqq = mret('QQQ', max_age, DESIGN_END)
        out['F2_top10_history_design_only'] = {'vs_SPY': N.excess_stats({m: v[0] for m, v in s.items()}, spy),
                                               'vs_QQQ': N.excess_stats({m: v[0] for m, v in s.items()}, qqq),
                                               'nx_brand_P2_all_US_reported': {'cagr_diff': 3.1, 'ex_ann': 3.07, 'te': 6.19},
                                               'note': '上位10社版は歴史の角度で測っていない形（課題文の実装できる版）。設計のぶれを出すためだけに作った＝この数字で規則を選んでいない（規則は課題文が先に決めた）'}
    if 'country' in cache:
        s = cache['country']
        acwi = mret('ACWI', max_age, DESIGN_END)
        out['F5_history_design_only'] = {'vs_ACWI': N.excess_stats({m: v[0] for m, v in s.items()}, acwi),
                                         'annual_check_vs_equal_etfs': ctry_annual_check(max_age)}
    if 'rsst_proxy' in cache:
        out['F4_design_series'] = cache['rsst_proxy']
    spy = mret('SPY', max_age, DESIGN_END)
    mk = N.ff_factors()['mkt']
    ms = [k for k in sorted(set(spy) & set(mk)) if k <= DESIGN_END]
    out['spy_vs_french_mkt'] = {'from': ms[0], 'to': ms[-1], 'corr': round(N.corr([spy[k] for k in ms], [mk[k] for k in ms]), 4)}
    return out


# ───────────────────────── e 過程（mw_forward と同じ定義） ─────────────────────────
def run_e(xs, lam, B, mu0_m=0.0, reverse=False, line=E_IND):
    """H0: E[clip(x)] ≤ mu0（reverse=False）／ ≥ mu0（reverse=True）の賭けの資産。λ ≤ 1/(2B)・|μ0| ≤ B/2 で 1+… ≥ 0.25 > 0"""
    e, path, first = 1.0, [], None
    for i, x in enumerate(xs):
        xc = max(-B, min(B, x))
        e *= 1 + lam * ((mu0_m - xc) if reverse else (xc - mu0_m))
        path.append(e)
        if first is None and e >= line:
            first = i
    return e, path, first


def cs_bounds(xs, lam, B):
    """いつ見ても有効な信頼の帯（切り詰めた平均の年率 %・参考・判定に使わない）"""
    lo, hi = None, None
    for k in range(-100, 101):
        mu = k / 10
        mm = mu / 100 / 12
        if abs(mm) > B / 2:
            continue
        if run_e(xs, lam, B, mm)[2] is not None:
            lo = mu if lo is None else max(lo, mu)
        if run_e(xs, lam, B, mm, reverse=True)[2] is not None:
            hi = mu if hi is None else min(hi, mu)
    return lo, hi


def e_bh(evals, alpha=0.05):
    """e-BH（Wang & Ramdas 2022）"""
    K = len(evals)
    items = sorted(evals.items(), key=lambda kv: -kv[1])
    kstar = 0
    for k, (_, e) in enumerate(items, 1):
        if e >= K / (alpha * k):
            kstar = k
    return [n for n, _ in items[:kstar]]


# ───────────────────────── 前向き: 持ち物の確定（凍結） ─────────────────────────
def lock_indmom(P, log):
    """形成の月末 t の持ち物を確定: 2026-08 末（登録の月＝9月の持ち物・参考）から、完了した最後の月まで。
    すべての器の t が出そろってから（前の月に値のあった器が t に値を持たないなら待つ・WAIT を超えたら候補から外す）"""
    R = {k: mret(k, 0.5) for k in IND_ETF}
    starts = {k: ind_start(k, R[k]) for k in IND_ETF}
    spy = mret('SPY', 0.5)
    forms = P.setdefault('forms', {})
    for t in months(addm(REG_MONTH, -1), addm(today_ym(), -1)):
        if str(t) in forms:
            continue
        if t not in spy:
            break
        lag = [k for k in IND_ETF if addm(t, -1) in R[k] and t not in R[k]]
        if lag and not overdue(t):
            log.append(f'indmom: 形成 {t} は {lag} の月末待ち')
            break
        sel, cands, sc = ind_pick(R, starts, t)
        if sel is None:
            forms[str(t)] = {'sel': None, 'why': f'候補 {len(cands)} 本 < {IND_MIN_N}', 'locked_on': today().isoformat()}
            continue
        prev = forms.get(str(addm(t, -1)))
        if prev and prev.get('sel'):
            tv = turnover({k: 1 / len(sel) for k in sel}, drift({k: 1 / len(prev['sel']) for k in prev['sel']}, {k: R[k].get(t) for k in prev['sel']}))
        else:
            tv = None
        forms[str(t)] = {'sel': sel, 'n_candidates': len(cands), 'score_12m_pct': {k: round(sc[k] * 100, 2) for k in sorted(sc, key=lambda k: -sc[k])},
                         'turnover_vs_previous': round(tv, 6) if tv is not None else None, 'dropped_lagging': lag,
                         'data_through': t, 'locked_on': today().isoformat()}
        log.append(f'indmom: 形成 {t} を確定 {sel}')


def lock_brand(P, log, initial_rows=None):
    """一覧の形成を確定。2025年の一覧は事前登録に凍結（BRAND_FIRST_FORMATION）。次の年の一覧は API に Y の100行が現れた日を
    『観測日』として記録し、形成は観測した月の月末（観測が月の26日以降なら翌月末）＝月1回の実行なら『公開の翌月末』"""
    forms = P.setdefault('forms', {})
    obs = P.setdefault('observed_lists', {})
    if str(BRAND_FIRST_FORMATION) not in forms and initial_rows is not None:
        fm = BRAND_FIRST_FORMATION
        w, tick = brand_rank(initial_rows, fm, lambda t: fm in month_ends(t, 0.5))
        forms[str(fm)] = {'list_year': BRAND_FIRST_LIST_Y, 'release_date': BRAND_FIRST_RELEASE, 'values_musd': w, 'weights': {k: round(v, 6) for k, v in norm_w(w).items()},
                          'parent_to_ticker': tick, 'locked_on': today().isoformat()}
    last_year = max([v['list_year'] for v in forms.values()] + [int(k) for k in obs]) if (forms or obs) else BRAND_FIRST_LIST_Y
    y = last_year + 1
    if str(y) not in obs:
        rows, why = ib_api_year(y)
        if rows:
            d = today()
            fm = d.year * 100 + d.month if d.day <= 25 else nextm(d.year * 100 + d.month)
            obs[str(y)] = {'first_seen': d.isoformat(), 'formation_month': fm, 'rows': rows}
            log.append(f'brand: {y} 年の一覧を観測 → 形成 {fm}')
        else:
            log.append(f'brand: {why}')
    for ys, o in obs.items():
        fm = o['formation_month']
        if str(fm) in forms:
            continue
        spy = mret('SPY', 0.5)
        if fm not in spy:
            continue
        w, tick = brand_rank(o['rows'], fm, lambda t: fm in month_ends(t, 0.5))
        forms[str(fm)] = {'list_year': int(ys), 'first_seen': o['first_seen'], 'values_musd': w, 'weights': {k: round(v, 6) for k, v in norm_w(w).items()},
                          'parent_to_ticker': tick, 'locked_on': today().isoformat()}
        log.append(f'brand: 形成 {fm} を確定 {list(w)}')


def lock_country(P, log):
    """y 年12月末の形成を確定（2025年12月末＝登録の月の持ち物。以後は毎年）"""
    forms = P.setdefault('forms', {})
    for y in range(CTRY_FIRST_Y, today().year):
        if str(y) in forms:
            continue
        if (y * 100 + 12) not in month_ends('ACWI', 0.5):
            continue
        lag = [c for c, tk in CTRY_ETF.items() if (y * 100 + 12) not in month_ends(tk, 0.5) and (y * 100 + 11) in month_ends(tk, 0.5)]
        if lag and not overdue(y * 100 + 12):
            log.append(f'country: 形成 {y}-12 は {lag} の月末待ち')
            continue
        sel, dy = ctry_form(y, 0.5)
        forms[str(y)] = {'sel': sel, 'dy_pct': {c: (round(v * 100, 3) if v is not None else None) for c, v in dy.items()},
                         'tickers': {c: CTRY_ETF[c] for c in (sel or [])}, 'locked_on': today().isoformat()}
        log.append(f'country: 形成 {y}-12 を確定 {sel}')


def lock_jp(P, log):
    """y 年9月の選択を確定（2026年9月＝最初の前向きの年）。全部の国内株式の能動の投信と TOPIX の指数型の基準価額を取り、
    9月の月次が出そろってから選ぶ（すべての器に10月の行が出てから・WAIT を超えたら出ている器だけで）"""
    forms = P.setdefault('forms', {})
    D = _D()
    for y in range(JP_FIRST_Y, today().year + 1):
        if str(y) in forms:
            continue
        t = y * 100 + 9
        if today_ym() <= t:
            continue
        tag = today().strftime('%Y%m%d')
        U = jp_universe(tag)
        rows = U['rows']
        need = [r for r in rows if D.category(r) == 'JP' and D.kind(r) in ('active', 'index') and r.get('unitOpenDiv') == '2' and not D.flags(r)['etf']]
        lib = D.Lib()
        navs, gone = {}, []
        for r in need:
            dly = jp_nav(r['associFundCd'], r['isinCd'], 12.0, lib)
            if dly is None:
                gone.append(r['associFundCd'])
                continue
            navs[r['associFundCd']] = jp_months(dly)
        act = [r['associFundCd'] for r in need if D.kind(r) == 'active' and D.passes_filter(r) and r['associFundCd'] in navs]
        late = [a for a in act if addm(t, -1) in navs[a][0] and t not in navs[a][0]]
        if len(late) > 0.05 * max(1, len(act)) and not overdue(t):
            log.append(f'jp: {y}-09 の選択は {len(late)} 本の9月の月次待ち')
            continue
        sel, diag = jp_select(y, rows, navs)
        by = {r['associFundCd']: r for r in rows}
        rk = [a for a in (sel or []) if any(nm == JP_RAKUTEN for nm, _ in by[a].get('inst') or [])]
        comp_all = jp_comparator(rows, navs, t, rakuten=False)
        comp_rk = jp_comparator(rows, navs, t, rakuten=True)
        info = {a: {'name': D.nfkc(by[a].get('fundNm')), 'fee_rakuten': _sales_fee(by[a], JP_RAKUTEN), 'fee_min': _sales_fee(by[a], None),
                    'retention': by[a].get('retentionMoneyCd') != '1', 'nisa_growth': by[a].get('nisaGrowthFlg') == '1',
                    'isin': by[a]['isinCd'], 'trust_fee_pct': by[a].get('trustReward')} for a in set(sel or []) | {comp_all, comp_rk} if a}
        forms[str(y)] = {'selection_month': t, 'sel_all': sel, 'sel_rakuten': rk, 'comp_all': comp_all, 'comp_rakuten': comp_rk,
                         'diag': diag, 'late_funds_excluded': late, 'csv_gone': gone, 'universe_date': U['standardDate'], 'info': info,
                         'locked_on': today().isoformat()}
        log.append(f'jp: {y}-09 の選択を確定 全部 {len(sel or [])} 本・楽天 {len(rk)} 本・相手 {comp_rk}/{comp_all}')


def seed_jp_prev(PS, U, y_prev, comp_all_prev):
    """前向きの最初の年の『前の年の選択』＝nx_jpfunds X1 の y_prev 年9月の選択の国内株式（凍結の holdings_by_rule）を
    規則がすでに回っている状態として置く（最初の10月の手数料は、続けて持つ器には掛けない＝F1 の回転と同じ考え方）。
    楽天の印・手数料・留保額は今日の一覧。楽天の相手は同じ規則（楽天が売る最も安い TOPIX の指数型・y_prev 年9月に月次がある）"""
    D = _D()
    forms = PS.setdefault('forms', {})
    if str(y_prev) in forms:
        return
    rows = U['rows']
    by = {r['associFundCd']: r for r in rows}
    hold = json.load(open(os.path.join(BASE, 'out', 'nx_jpfunds.json')))['holdings_by_rule']['X1_top_q_1y'][str(y_prev)]
    jp = sorted(a for a in hold if a in by and D.category(by[a]) == 'JP')
    rk = [a for a in jp if any(nm == JP_RAKUTEN for nm, _ in by[a].get('inst') or [])]
    navs = {}
    for r in D.comparator_candidates(rows, 'JP'):
        pth = os.path.join(N.CACHE, 'nx_jpfunds_nav', f"{r['associFundCd']}.csv")
        if os.path.exists(pth):
            navs[r['associFundCd']] = jp_months(D.parse_csv(open(pth, 'rb').read())[0])
    comp_rk = jp_comparator(rows, navs, y_prev * 100 + 9, rakuten=True)
    info = {a: {'name': D.nfkc(by[a].get('fundNm')), 'fee_rakuten': _sales_fee(by[a], JP_RAKUTEN), 'fee_min': _sales_fee(by[a], None),
                'retention': by[a].get('retentionMoneyCd') != '1', 'nisa_growth': by[a].get('nisaGrowthFlg') == '1',
                'isin': by[a]['isinCd'], 'trust_fee_pct': by[a].get('trustReward')} for a in set(jp) | {comp_all_prev, comp_rk} if a and a in by}
    forms[str(y_prev)] = {'selection_month': y_prev * 100 + 9, 'sel_all': jp, 'sel_rakuten': rk, 'comp_all': comp_all_prev, 'comp_rakuten': comp_rk,
                          'seeded_from': f'nx_jpfunds X1 の {y_prev} 年9月の選択（凍結）の国内株式。楽天の印・手数料は {U["standardDate"]} の一覧',
                          'info': info, 'locked_on': today().isoformat()}


def jp_prev_holdings_x1_2025(rows_now):
    """参考: 登録の月（2026-09）の持ち物＝nx_jpfunds X1 の 2025年9月の選択の国内株式（凍結の holdings_by_rule）。楽天の印は今日の一覧"""
    D = _D()
    hold = json.load(open(os.path.join(BASE, 'out', 'nx_jpfunds.json')))['holdings_by_rule']['X1_top_q_1y']['2025']
    by = {r['associFundCd']: r for r in rows_now}
    jp = [a for a in hold if a in by and D.category(by[a]) == 'JP']
    rk = [a for a in jp if any(nm == JP_RAKUTEN for nm, _ in by[a].get('inst') or [])]
    return {'selection_month': 202509, 'n_all_categories': len(hold), 'n_JP': len(jp), 'n_JP_rakuten': len(rk),
            'JP': [[a, D.nfkc(by[a].get('fundNm'))[:40]] for a in jp], 'JP_rakuten': rk,
            'note': '2026-09 に持っている物（2025年9月末の選択・参考）。前向きの最初の月（2026-10）の持ち物は 2026年9月末の選択で、--update が確定する'}


# ───────────────────────── 前向き: 月次の持ち物のリターン ─────────────────────────
_JPNAV = {}                                        # 基準価額の日次（この実行の中だけ・出力には書かない）


def port_month(pk, m, PS):
    """ポートフォリオ pk の月 m → ('ok'|'wait'|'missing', 記録)。記録は s（と JP なら b・費用）と、次の月へ流す重み"""
    P = PS.setdefault(pk, {})
    mons = P.setdefault('months', {})
    if str(m) in mons:
        return 'ok', mons[str(m)]
    if pk == 'indmom':
        f = P.get('forms', {}).get(str(addm(m, -1)))
        if not f:
            return 'wait', {'why': f'形成 {addm(m, -1)} が未確定'}
        if not f.get('sel'):
            return 'missing', {'why': f.get('why', '形成なし')}
        r = {k: mret(k, 0.5).get(m) for k in f['sel']}
        miss = [k for k, v in r.items() if v is None]
        if miss and not overdue(m):
            return 'wait', {'why': f'{miss} の月末待ち'}
        have = {k: v for k, v in r.items() if v is not None}
        if not have:
            return 'missing', {'why': '持ち物の値が1本も無い'}
        tv = f.get('turnover_vs_previous') or 0.0
        rec = {'s': sum(have.values()) / len(have), 'r': have, 'missing': miss, 'turnover': tv, 'cost': tv * IND_COST, 'formation': addm(m, -1)}
    elif pk == 'rsst':
        v = mret('RSST', 0.5).get(m)
        if v is None:
            return ('missing' if overdue(m) else 'wait'), {'why': 'RSST の月末待ち'}
        rec = {'s': v, 'r': {'RSST': v}, 'cost': 0.0}
    elif pk in ('brand', 'country'):
        forms = P.get('forms', {})
        if pk == 'brand':
            fms = sorted(int(k) for k in forms if int(k) < m)
            tgt_of = lambda fm: forms[str(fm)]['weights']  # noqa: E731
        else:
            fms = sorted(int(k) * 100 + 12 for k in forms if int(k) * 100 + 12 < m and forms[k].get('sel'))
            tgt_of = lambda fm: {forms[str(fm // 100)]['tickers'][c]: 1 / len(forms[str(fm // 100)]['sel']) for c in forms[str(fm // 100)]['sel']}  # noqa: E731
        if not fms:
            return 'wait', {'why': '形成が未確定'}
        fm = fms[-1]
        if pk == 'brand' and m > addm(fm, 25):         # 最後の形成から24か月を過ぎても新しい一覧が無い＝止める（古い一覧を持ち続けない）
            return 'missing', {'why': f'形成 {fm} から24か月を過ぎても新しい一覧が観測されない（F2 はここで止まる）'}

        def weights_after(form_m, upto):
            """形成 form_m の重みを nextm(form_m)〜upto の値動きで流した重み（確定した月の記録があればそれを使う）。待つなら None"""
            w = norm_w(tgt_of(form_m))
            for k_ in months(nextm(form_m), upto):
                rk_ = mons.get(str(k_))
                if rk_ and rk_.get('formation') == form_m:
                    w = drift(rk_['w_start'], rk_['r'])
                    continue
                rr = {t: mret(t, 0.5).get(k_) for t in w}
                if any(v is None for v in rr.values()) and not overdue(k_):
                    return None
                w = drift(w, rr)
            return w
        if m == nextm(fm):                              # 月 m の直前の月末（fm）に組み替えた
            w0 = norm_w(tgt_of(fm))
            wprev = weights_after(fms[-2], fm) if len(fms) >= 2 else None
            if len(fms) >= 2 and wprev is None:
                return 'wait', {'why': '組み替え前の重みを作る月末待ち'}
            tv = turnover(w0, wprev) if wprev else None
        else:
            w0 = weights_after(fm, addm(m, -1))
            if w0 is None:
                return 'wait', {'why': '重みを流す月末待ち'}
            tv = 0.0
        r = {t: mret(t, 0.5).get(m) for t in w0}
        miss = [t for t, v in r.items() if v is None]
        if miss and not overdue(m):
            return 'wait', {'why': f'{miss} の月末待ち'}
        s = sum(v * (r[t] if r[t] is not None else 0.0) for t, v in w0.items())   # 値の無い器は 0%（現金）＝nx_brand の約束
        cu = BRAND_COST if pk == 'brand' else CTRY_COST
        rec = {'s': s, 'r': {t: v for t, v in r.items()}, 'w_start': {t: round(v, 8) for t, v in w0.items()}, 'missing': miss,
               'turnover': tv, 'cost': (tv or 0.0) * cu, 'formation': fm}
    elif pk in ('jpx1_rakuten', 'jpx1_all'):
        y = m // 100 if m % 100 >= 10 else m // 100 - 1
        jforms = PS.get('jp', {}).get('forms', {})
        f = jforms.get(str(y))
        if not f:
            return 'wait', {'why': f'{y}年9月の選択が未確定'}
        rk = pk == 'jpx1_rakuten'
        sel = f['sel_rakuten'] if rk else f['sel_all']
        comp = f['comp_rakuten'] if rk else f['comp_all']
        if not sel or not comp:
            return 'missing', {'why': '選択か相手が無い'}
        D = _D()
        ended = P.setdefault('ended', {})
        mon = {}
        for a in list(sel) + [comp]:
            if a not in _JPNAV:
                try:
                    if 'lib' not in _JPNAV:
                        _JPNAV['lib'] = D.Lib()
                    _JPNAV[a] = jp_nav(a, f['info'].get(a, {}).get('isin'), 12.0, _JPNAV['lib'])
                except Exception:  # noqa
                    _JPNAV[a] = None
            dly = _JPNAV[a]
            mon[a] = jp_months(dly)[0] if dly else {}
            if dly:
                lastd = dly[-1][0]
                gap = (today() - datetime.date(lastd // 10000, lastd // 100 % 100, lastd % 100)).days
                if m not in mon[a] and lastd // 100 == m and gap >= 10 and today() > month_end_date(m):
                    # 最後の行が m の中で 10日以上行が増えない＝償還・取扱の終わり: m は最後の行までの部分の月（以後は外す）
                    prev_rows = [row for row in dly if row[0] // 100 < m]
                    if prev_rows:
                        g, base = 1.0, prev_rows[-1][1]
                        for _, nav, _, dv in [row for row in dly if row[0] // 100 == m]:
                            g *= (nav + dv) / base; base = nav
                        mon[a][m] = g - 1
                    if a in sel:
                        ended.setdefault(a, m)
                elif lastd // 100 < m and gap >= 10 and a in sel:
                    ended.setdefault(a, lastd // 100)
        rb = mon[comp].get(m)
        live = [a for a in sel if not (a in ended and ended[a] < m)]
        r = {a: mon[a].get(m) for a in live}
        miss = [a for a in live if r[a] is None]
        if (miss or rb is None) and not overdue(m):
            return 'wait', {'why': (f'{len(miss)} 本と相手の月次待ち' if rb is None else f'{len(miss)} 本の月次待ち')}
        if rb is None:
            return 'missing', {'why': '相手の月次が出ない'}
        for a in miss:
            ended.setdefault(a, m)
        have = {a: v for a, v in r.items() if v is not None}
        if not have:
            return 'missing', {'why': '持ち物の値が1本も無い'}
        n = len(have)
        cost = 0.0
        if m % 100 == 10:                               # 選び直した後の最初の月: 入る器の購入時手数料・出る器の留保額（相手も同じ規則）
            prev = jforms.get(str(y - 1)) or {}
            prev_sel = set((prev.get('sel_rakuten') if rk else prev.get('sel_all')) or [])
            fee_key = 'fee_rakuten' if rk else 'fee_min'
            new_in = [a for a in have if a not in prev_sel]
            cost += sum((f['info'][a].get(fee_key) or 0.0) for a in new_in) / n
            if prev_sel:
                out_ = [a for a in prev_sel if a not in set(sel)]
                cost += sum(JP_RETENTION for a in out_ if prev.get('info', {}).get(a, {}).get('retention')) / len(prev_sel)
            prev_comp = prev.get('comp_rakuten' if rk else 'comp_all')
            if prev_comp != comp:
                cost -= (f['info'][comp].get(fee_key) or 0.0)
                if prev_comp and prev.get('info', {}).get(prev_comp, {}).get('retention'):
                    cost -= JP_RETENTION
        rec = {'s': sum(have.values()) / n, 'b': rb, 'n_held': n, 'r': have, 'missing_or_ended': miss, 'cost': cost,
               'comparator': comp, 'selection_year': y}
    else:
        raise ValueError(pk)
    rec['locked_on'] = today().isoformat()
    mons[str(m)] = rec
    return 'ok', rec


def hyp_x(h, m, PS):
    d = HYP[h]
    st, rec = port_month(d['port'], m, PS)
    if st != 'ok':
        return st, None, rec
    if d['bench'] is None:
        b = rec['b']
    else:
        b = mret(d['bench'], 0.5).get(m)
        if b is None:
            return ('missing' if overdue(m) else 'wait'), None, {'why': f"{d['bench']} の月末待ち"}
    x = rec['s'] - b - rec.get('cost', 0.0)
    return 'ok', x, {'s': round(rec['s'], 6), 'b': round(b, 6), 'cost': round(rec.get('cost', 0.0), 6)}


# ───────────────────────── 更新 ─────────────────────────
def evaluate(pr, prev, PS, log):
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
            try:
                st, x, rec = hyp_x(h, m, PS)
            except Exception as e:  # noqa
                st, x, rec = 'wait', None, {'why': f'取得の失敗: {type(e).__name__}: {e}'}
                log.append(f'{h} {m}: 取得の失敗 {type(e).__name__}: {e}')
            if st == 'ok':
                rows.append({'m': m, 'x': round(x, 6), **rec, 'locked_on': today().isoformat()})
            elif st == 'missing' or (st == 'wait' and overdue(m)):
                rows.append({'m': m, 'x': None, 'missing': True, 'note': rec.get('why'), 'locked_on': today().isoformat()})
            else:
                waiting.append({'m': m, 'why': rec.get('why')}); stopped = m
        used = [r for r in rows if r.get('x') is not None]
        xs = [r['x'] for r in used]
        line = LINES[HYP[h]['family']]
        e, path, first = run_e(xs, P['lambda'], P['B'])
        _, _, first_fam = run_e(xs, P['lambda'], P['B'], line=line)
        f, fpath, ffirst = run_e(xs, P['lambda'], P['B'], P['mu_f'] / 100 / 12, reverse=True)
        for r, ev, fv in zip(used, path, fpath):
            r['e'] = round(ev, 5); r['f'] = round(fv, 5)
        n = len(xs)
        fw = {'n_months': n, 'first_month': used[0]['m'] if used else None, 'last_month': used[-1]['m'] if used else None,
              'e_now': round(e, 5), 'e_max': round(max(path), 5) if path else 1.0, 'line_individual': E_IND, 'line_family': line,
              'crossed_individual_at': used[first]['m'] if first is not None else None,
              'crossed_family_at': used[first_fam]['m'] if first_fam is not None else None,
              'futility_now': round(f, 5), 'futility_at': used[ffirst]['m'] if ffirst is not None else None,
              'mean_active_ann_pct': round(S.mean(xs) * 1200, 3) if n else None,
              'cum_active_geo_pct': None, 'clipped_months': sum(1 for q in xs if abs(q) > P['B']),
              'missing_months': [r['m'] for r in rows if r.get('missing')], 'waiting_for': waiting, 'months': rows}
        if n >= 12:
            lo, hi = cs_bounds(xs, P['lambda'], P['B'])
            fw['cs_trimmed_mean_ann_pct'] = {'lower': lo, 'upper': hi}
        if used:
            gs = math.prod(1 + r['s'] - r.get('cost', 0.0) for r in used)
            gb = math.prod(1 + r['b'] for r in used)
            fw['cum_active_geo_pct'] = round((gs / gb - 1) * 100, 3)
        fam = HYP[h]['family']
        if fw['crossed_family_at'] and fam == 'main':
            status = f'勝ち（主の族の線 e≥{line:g} に {fw["crossed_family_at"]} で到達・族で調整済み）'
        elif fw['crossed_family_at']:
            status = f'{"副" if fam == "sub" else "参考"}の族の線 e≥{line:g} に到達（{fw["crossed_family_at"]}）＝判定の族の外'
        elif fw['crossed_individual_at']:
            status = f'1本の線 e≥20 には到達（{fw["crossed_individual_at"]}）・族の線 {line:g} は未達＝勝ちとは言わない'
        elif fw['futility_at']:
            status = f'見込みなし（逆向きの e_f≥20 に {fw["futility_at"]} で到達＝設計の上乗せ μ_d={P["mu_d"]}%/年 は無い）・記録は続ける'
        elif last_done > MAX_END:
            status = '打ち切り（20年で未決＝証明できず）'
        else:
            status = '追跡中'
        res[h] = {'definition': HYP[h]['ja'], 'family': fam, 'holdable': HYP[h]['holdable'], 'ccy': HYP[h]['ccy'], 'frozen': P, 'forward': fw, 'status': status}
    fams = {}
    for fam, hs in FAMILIES.items():
        ev = {h: res[h]['forward']['e_now'] for h in hs}
        fams[fam] = {'K': len(hs), 'line_bonferroni': LINES[fam], 'mean_e_now': round(sum(ev.values()) / len(ev), 5),
                     'global_null_rejected_mean_e': sum(ev.values()) / len(ev) >= E_IND, 'e_bh_rejected_now': e_bh(ev)}
    allv = {h: res[h]['forward']['e_now'] for h in ORDER}
    fams['all_registered'] = {'K': len(ORDER), 'line_bonferroni': LINES['all_registered'], 'e_bh_rejected_now': e_bh(allv),
                              'above_line_now': [h for h, v in allv.items() if v >= LINES['all_registered']]}
    fams['cross_session_reference'] = {'K': len(ORDER) + ESKNZBH_K, 'line_bonferroni': E_IND * (len(ORDER) + ESKNZBH_K),
                                       'note': 'eknzbh の mw_forward（8本）と合わせた全セッションの線（参考）'}
    return res, fams


# ───────────────────────── 検出力（numpy・init だけ） ─────────────────────────
def power(des, hist, n=4000, years=40, block=12, seed=20260929):
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
        B, lam, muf = P['B'], P['lambda'], P['mu_f'] / 100 / 12
        line = LINES[HYP[h]['family']]
        rows = {}
        for mu in (0.0, 0.5, 1.0, 2.0, 3.0):
            xs = np.clip(base + mu / 100 / 12, -B, B)
            le = np.cumsum(np.log1p(lam * xs), axis=1)
            lf = np.cumsum(np.log1p(lam * (muf - xs)), axis=1)

            def first(mask):
                return np.where(mask.any(axis=1), mask.argmax(axis=1) + 1, 10 ** 6)
            f20, fl, ff = first(le >= math.log(E_IND)), first(le >= math.log(line)), first(lf >= math.log(E_IND))
            ir = mu / P['sigma_d'] if P['sigma_d'] else None
            rows[f'{mu:g}'] = {'p_cross20_by': {f'{y}y': round(float((f20 <= y * 12).mean()), 3) for y in (3, 5, 10, 20)},
                               'p_cross_family_line_by': {f'{y}y': round(float((fl <= y * 12).mean()), 3) for y in (3, 5, 10, 20)},
                               'median_years_to_family_line': round(float(np.median(fl)) / 12, 1) if float(np.median(fl)) <= T else f'>{years}',
                               'p_futility_by': {f'{y}y': round(float((ff <= y * 12).mean()), 3) for y in (3, 5, 10, 20)},
                               'oracle_years_6_over_IR2': round(6 / ir ** 2, 1) if ir else None}
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
        out[h] = {'sigma_d': P['sigma_d'], 'lambda': P['lambda'], 'B': P['B'], 'mu_d': P['mu_d'], 'family_line': line,
                  'hist_months_bootstrapped': len(x), 'by_true_edge_pct': rows, 'edge_needed_for_50pct_family_line_by_pct_per_year': need}
    return out


# ───────────────────────── 点検 ─────────────────────────
def selftest():
    import random
    ok = []
    # 1) 先読みなし: t より後のリターンを乱しても t の持ち物は同じ
    rnd = random.Random(1)
    R = {k: {m: rnd.gauss(0.01, 0.05) for m in months(200001, 202012)} for k in IND_ETF}
    starts = {k: ind_start(k, R[k]) for k in IND_ETF}
    a, _, _ = ind_pick(R, starts, 201506)
    R2 = {k: {m: (v if m <= 201506 else rnd.gauss(0, 0.2)) for m, v in r.items()} for k, r in R.items()}
    b, _, _ = ind_pick(R2, starts, 201506)
    ok.append(('ind_pick_no_lookahead', a == b))
    # 2) 始まりの規則: SMH は 13か月（t−12〜t）がすべて 2012-01 以降になる形成 2013-01 から候補（2012-12 はまだ）
    s, c, _ = ind_pick(R, starts, 201301)
    s2, c2, _ = ind_pick(R, starts, 201212)
    ok.append(('ind_start_rule', 'SMH' in c and 'SMH' not in c2))
    # 3) 回転
    ok.append(('turnover_same_0', abs(turnover({'A': .5, 'B': .5}, {'A': .5, 'B': .5})) < 1e-12))
    ok.append(('turnover_full_1', abs(turnover({'A': .5, 'B': .5}, {'C': .5, 'D': .5}) - 1) < 1e-12))
    # 4) e 過程: λ ≤ 1/(2B) なら賭けの係数は正（切り詰め後の x の最悪でも 0.5 以上）
    B, lam = 0.03, 1 / (2 * 0.03)
    e, path, _ = run_e([-10.0] * 5, lam, B)
    ok.append(('e_positive_worst', all(p > 0 for p in path) and abs(path[0] - 0.5) < 1e-12))
    # 5) Ville: 帰無（平均0・独立）で 20年のどこかで e≥20 に達する割合 ≤ 5%（模擬）
    hits = 0
    for i in range(2000):
        xs = [rnd.gauss(0, 0.02) for _ in range(240)]
        if run_e(xs, 0.03 / 0.02 ** 2 / 12, 0.08)[2] is not None:
            hits += 1
    ok.append(('ville_null_rate<=0.05', hits / 2000 <= 0.05, hits / 2000))
    # 6) drift: 値の無い器は 0%（現金）
    w = drift({'A': .5, 'B': .5}, {'A': 1.0, 'B': None})
    ok.append(('drift_missing_is_cash', abs(w['A'] - 2 / 3) < 1e-12))
    # 7) 月の完了: 当月は使わない
    ok.append(('addm', addm(202612, 1) == 202701 and addm(202601, -1) == 202512))
    for x in ok:
        print(('OK  ' if x[1] else 'NG  ') + x[0], *x[2:])
    return all(x[1] for x in ok)



# ───────────────────────── 過去での通し稽古（点検だけ・出力は scratch） ─────────────────────────
def dryrun_past(scratch):
    """登録が 2025-09 だったとして 2025-10〜2026-08 を『前向きの月』として同じ道具（確定→月次→e）に通し、
    設計の歴史の系列（--design と同じ作り方）と月ごとに一致するかを確かめる。本番の出力・キャッシュには触れない"""
    global FC, FIRST_FWD, REG_MONTH, CTRY_FIRST_Y, JP_FIRST_Y, BRAND_FIRST_FORMATION, BRAND_FIRST_LIST_Y, BRAND_FIRST_RELEASE
    import shutil
    os.makedirs(scratch, exist_ok=True)
    FC = os.path.join(scratch, 'fc')
    src = os.path.join(N.CACHE, 'nx_jpfunds_nav')
    dst = os.path.join(FC, 'jpnav')
    os.makedirs(dst, exist_ok=True)
    for fn in os.listdir(src):
        if fn.endswith('.csv') and not os.path.exists(os.path.join(dst, fn)):
            shutil.copy(os.path.join(src, fn), os.path.join(dst, fn))
            os.utime(os.path.join(dst, fn))
    FIRST_FWD, REG_MONTH, CTRY_FIRST_Y, JP_FIRST_Y = 202510, 202509, 2024, 2025
    BRAND_FIRST_FORMATION, BRAND_FIRST_LIST_Y, BRAND_FIRST_RELEASE = 202411, 2024, '2024-10-10'
    des, cps, cache, hist = design(3.0)
    pr = {'frozen': {'design': des}}
    ib = json.load(open(os.path.join(N.CACHE, 'nx_brand_lists.json')))['interbrand']['years']
    rows = {y: [{'name': r['name'], 'value': r['value']} for r in ib[str(y)]['rows']] for y in (2024, 2025)}
    PS, log = {}, []
    lock_indmom(PS.setdefault('indmom', {}), log)
    PS['brand'] = {'observed_lists': {'2025': {'first_seen': '2025-11-02', 'formation_month': 202511, 'rows': rows[2025]}}}
    lock_brand(PS['brand'], log, initial_rows=rows[2024])
    lock_country(PS.setdefault('country', {}), log)
    seed_jp_prev(PS.setdefault('jp', {}), jp_universe(today().strftime('%Y%m%d')), 2024, cache['jp'][1]['comparator_chain'][2024])
    lock_jp(PS.setdefault('jp', {}), log)
    res, fams = evaluate(pr, {}, PS, log)
    cmp = {}
    for h in ORDER:
        fw = {r['m']: r for r in res[h]['forward']['months']}
        hx = hist[h]
        ms = [m for m in months(202510, 202608)]
        diffs = {m: (round(fw[m]['x'] - hx[m], 8) if m in fw and fw[m].get('x') is not None and m in hx else None) for m in ms}
        vals = [abs(v) for v in diffs.values() if v is not None]
        cmp[h] = {'months_forward': len([m for m in ms if m in fw and fw[m].get('x') is not None]), 'months_hist': len([m for m in ms if m in hx]),
                  'max_abs_diff': max(vals) if vals else None, 'diffs': diffs, 'e_now': res[h]['forward']['e_now']}
    jp = PS['jp'].get('forms', {}).get('2025', {})
    x1 = json.load(open(os.path.join(BASE, 'out', 'nx_jpfunds.json')))['holdings_by_rule']['X1_top_q_1y']['2025']
    D = _D()
    U = jp_universe(today().strftime('%Y%m%d'))
    by = {r['associFundCd']: r for r in U['rows']}
    x1_jp = sorted(a for a in x1 if a in by and D.category(by[a]) == 'JP')
    out = {'what': '過去での通し稽古（2025-10〜2026-08 を前向きの月として通す）', 'compare_forward_minus_hist_x': cmp,
           'jp_selection_2025_vs_nx_jpfunds_X1_2025_JP': {'this_tool': len(jp.get('sel_all') or []), 'nx_jpfunds': len(x1_jp),
                                                         'same_set': sorted(jp.get('sel_all') or []) == x1_jp,
                                                         'only_this': sorted(set(jp.get('sel_all') or []) - set(x1_jp)),
                                                         'only_nx_jpfunds': sorted(set(x1_jp) - set(jp.get('sel_all') or [])),
                                                         'rakuten': len(jp.get('sel_rakuten') or []), 'comp_all': jp.get('comp_all'), 'comp_rakuten': jp.get('comp_rakuten')},
           'log': log}
    json.dump(out, open(os.path.join(scratch, 'nx_forward_dryrun.json'), 'w'), ensure_ascii=False, indent=1, default=str)
    for h, v in cmp.items():
        print(f"{h:28s} 前向き {v['months_forward']:2d} / 歴史 {v['months_hist']:2d}  最大差 {v['max_abs_diff']}  e={v['e_now']:.3f}")
    print(json.dumps(out['jp_selection_2025_vs_nx_jpfunds_X1_2025_JP'], ensure_ascii=False))


# ───────────────────────── 段 ─────────────────────────
def sha_of(path):
    try:
        return subprocess.run(['git', '-C', BASE, 'log', '-1', '--format=%H', '--', path], capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa
        return None


CI_LINE = ("ops.yml（毎月2日）に2か所: (1) steps に1段 `- name: 前向きの検定（nx_forward・判定に不使用）` / `continue-on-error: true` / "
           "`run: timeout 1800 python3 night/nx_forward.py --update | tail -14`（日本の投信の選び直しの月＝10月は約500本の基準価額を取るので 15分前後）。"
           "(2) 最後の `ccf_git_add ...` の行の末尾に `out/nx_forward.json` を足す（足さないと『回っているのに残らない』）")


def tool_sha():
    import hashlib
    return hashlib.sha256(open(os.path.abspath(__file__), 'rb').read()).hexdigest()


def load_prev():
    return json.load(open(OUT)) if os.path.exists(OUT) else {}


def write(obj):
    obj['generated'] = today().isoformat()
    N.save(OUT_NAME, obj)


def do_init():
    pr = json.load(open(PREREG))
    fz = pr['frozen']
    t0 = time.time()
    prev = load_prev()
    PS = prev.get('portfolios') or {}
    log = []
    # 設計の再計算（登録の数字と一致するかの検算）
    des, cps, cache, hist = design(3.0)
    recheck = {h: {k: (fz['design'][h][k], des[h][k]) for k in ('sigma_d', 'mu_d', 'B', 'lambda')
                   if abs(float(fz['design'][h][k]) - float(des[h][k])) > 1e-6} for h in ORDER}
    # 2026-09 末の持ち物（決まっているもの）
    lock_indmom(PS.setdefault('indmom', {}), log)
    lock_brand(PS.setdefault('brand', {}), log, initial_rows=fz['brand_list_2025_rows'])
    lock_country(PS.setdefault('country', {}), log)
    try:
        U = jp_universe(today().strftime('%Y%m%d'))
        PS.setdefault('jp', {})['holdings_during_registration_month'] = jp_prev_holdings_x1_2025(U['rows'])
        seed_jp_prev(PS['jp'], U, JP_FIRST_Y - 1, cache['jp'][1]['comparator_chain'][JP_FIRST_Y - 1])
    except Exception as e:  # noqa
        log.append(f'jp: 一覧の取得失敗 {e}')
    lock_jp(PS.setdefault('jp', {}), log)
    res, fams = evaluate(pr, prev, PS, log)
    obj = {'angle': 'nx_forward', 'role': '前向きの検定（登録 2026-09-29・最初の月 2026-10）。読むだけ・門の判定・採点・配分には不使用',
           'prereg': 'out/nx_forward_prereg.json', 'prereg_commit': sha_of('out/nx_forward_prereg.json'),
           'first_forward_month': FIRST_FWD, 'max_end': MAX_END, 'review_month': REVIEW_MONTH,
           'rule': '主の族（F1・F2・F3）は e ≥ 60（=20×3・Bonferroni）に一度でも達したら『勝ち』。1本の線 e≥20 は族の調整の前の参考。逆向きの e_f≥20 で見込みなし（拘束しない）',
           'hypotheses': res, 'families': fams, 'portfolios': PS, 'log': log,
           'registration_month_holdings': registration_view(PS),
           'design_recheck_vs_prereg': {h: v for h, v in recheck.items() if v},
           'power': power(fz['design'], hist), 'sanity': sanity(cache, 3.0),
           'ci_suggestion': CI_LINE, 'tool_sha256': tool_sha(), 'tool_sha256_matches_prereg': tool_sha() == fz.get('tool_sha256_at_registration'),
           'runtime_s': round(time.time() - t0, 1)}
    write(obj)
    report(obj)


def registration_view(PS):
    """登録の月（2026-09）の持ち物と、最初の前向きの月（2026-10）の持ち物（確定したもの・保留のもの）"""
    v = {}
    ind = PS.get('indmom', {}).get('forms', {})
    v['F1_indmom'] = {'held_during_2026_09（2026-08 末の形成）': (ind.get('202608') or {}).get('sel'),
                      'held_during_2026_10（2026-09 末の形成）': (ind.get('202609') or {}).get('sel') or '保留（2026-09-30 の引けの後の最初の --update で確定）'}
    br = PS.get('brand', {})
    f = (br.get('forms') or {}).get(str(BRAND_FIRST_FORMATION)) or {}
    v['F2_brand10'] = {'formation_2025_11（2025年の一覧・公開 2025-10-15 の翌月末）': f.get('weights'),
                       'held_during_2026_10': '2025-11 末の重みを 2026-09 まで値動きで流したもの（2026年の一覧が 2026-10 に観測されれば 2026-10 末に組み替え）'}
    ct = PS.get('country', {}).get('forms', {})
    v['F5_country'] = {'formation_2025_12': (ct.get('2025') or {}).get('sel'), 'dy_pct': (ct.get('2025') or {}).get('dy_pct')}
    v['F4_RSST'] = {'held': {'RSST': 1.0}}
    jp = PS.get('jp', {})
    v['F3_jpX1'] = {'held_during_2026_09': {k: jp.get('holdings_during_registration_month', {}).get(k) for k in ('n_JP', 'n_JP_rakuten', 'selection_month')},
                    'selection_2026_09（2026-10〜2027-09 に持つ）': ({k: jp['forms']['2026'][k] for k in ('sel_rakuten', 'comp_rakuten', 'comp_all', 'diag')}
                                                                if '2026' in jp.get('forms', {}) else '保留（2026-09-30 の基準価額が出た後の最初の --update で確定）')}
    return v


def do_update():
    pr = json.load(open(PREREG))
    t0 = time.time()
    prev = load_prev()
    if not prev:
        raise SystemExit('先に --init を回す')
    PS = prev.get('portfolios') or {}
    log = []
    for fn, key in ((lock_indmom, 'indmom'), (lock_brand, 'brand'), (lock_country, 'country'), (lock_jp, 'jp')):
        try:
            fn(PS.setdefault(key, {}), log)
        except Exception as e:  # noqa
            log.append(f'{key}: 確定の失敗 {e}')
    res, fams = evaluate(pr, prev, PS, log)
    obj = dict(prev)
    obj.update({'hypotheses': res, 'families': fams, 'portfolios': PS, 'log': log, 'registration_month_holdings': registration_view(PS),
                'prereg_commit': sha_of('out/nx_forward_prereg.json'), 'tool_sha256': tool_sha(),
                'tool_sha256_matches_prereg': tool_sha() == pr['frozen'].get('tool_sha256_at_registration'), 'runtime_s': round(time.time() - t0, 1)})
    write(obj)
    report(obj)


def report(obj):
    for h in ORDER:
        fw = obj['hypotheses'][h]['forward']
        print(f"{h:28s} 月数 {fw['n_months']:3d}  e={fw['e_now']:.3f}  e_f={fw['futility_now']:.3f}  {obj['hypotheses'][h]['status']}")
    print('主の族: e-BH', obj['families']['main']['e_bh_rejected_now'], '平均e', obj['families']['main']['mean_e_now'])
    for x in obj.get('log', [])[-12:]:
        print('  ', x)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--design', action='store_true')
    g.add_argument('--init', action='store_true')
    g.add_argument('--update', action='store_true')
    g.add_argument('--selftest', action='store_true')
    g.add_argument('--dryrun-past', metavar='SCRATCH_DIR', help='点検: 登録が 2025-09 だったとして 2025-10〜2026-08 を通す（出力は SCRATCH_DIR）')
    a = ap.parse_args()
    if a.dryrun_past:
        dryrun_past(a.dryrun_past)
        return
    if a.selftest:
        sys.exit(0 if selftest() else 1)
    if a.design:
        des, cps, cache, hist = design(3.0)
        print(json.dumps({'design': des, 'counterparts': cps, 'sanity': sanity(cache, 3.0)}, ensure_ascii=False, indent=1, default=str))
        return
    if a.init:
        do_init()
        return
    do_update()


if __name__ == '__main__':
    main()
