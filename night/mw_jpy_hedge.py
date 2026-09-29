#!/usr/bin/env python3
"""night/mw_jpy_hedge.py — 『市場に勝てる歴史検証』角度 jpy_hedge: 円の投資家の為替ヘッジ規則は、ヘッジなしの米国株（円建て）に勝つか
（読むだけ・門の判定には不使用）

事前登録: out/mw_jpy_hedge_prereg.json（規則・線は測る前に固定。ここで動かさない）
出力    : out/mw_jpy_hedge.json

問い: 円で暮らす投資家の本当の相手は『ヘッジなしの米国株を円で見たもの』。為替は株とほぼ無相関の年10%前後のぶれで、
      これまでの mw の検証（すべてドル建て）は一度も触っていない。事前に決めたヘッジの規則
      （実質為替の割高さ V・12か月の円高 M・金利差 C・その組み合わせ VM）で、ヘッジなしに円建てで勝てるか。
      実装は2つ: FLOW（毎月の新しいお金だけをヘッジあり／なしのどちらへ入れるかを決め、持っている分は売らない）と
      STOCK（持ち分ぜんぶを毎月切り替える）。

約束: 月次リターンは小数。総リターンどうしで比べる（円建ての戦略 − 円建てのヘッジなし）。欠測を0で埋めない（その月は捨てる）。
      信号は月末 t に分かる値だけで作り、t+1 月のリターンに当てる。物価は1か月遅れ（四半期の物価は2か月遅れ）で使う。

使い方: python3 night/mw_jpy_hedge.py --check   （データの有無だけ・戦略と市場を比べた数字は出さない）
        python3 night/mw_jpy_hedge.py           （全部測って out/mw_jpy_hedge.json）
"""
import csv, io, json, math, os, subprocess, sys, statistics as S

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402

PREREG = 'mw_jpy_hedge_prereg.json'
PREREG2 = 'mw_jpy_hedge_prereg2.json'
OUT = 'mw_jpy_hedge.json'
END_M = 202608                 # French の終わり
START_JP = 198101              # 円の主の標本の始まり（1980-12 の外為法改正＝資本規制の撤廃の翌月）
POSTPUB = 201401               # Asness-Moskowitz-Pedersen (2013) の公表の翌年
BASIS_FROM = 200801            # ベーシス（ドル調達のプレミアム）を掛け始める月
BASIS = 0.003                  # 既定 年0.3%
BASIS_STRESS = 0.006           # ストレス 年0.6%
COST_UNIT = 0.001              # 切り替え1回（持ち分100%の入れ替え）あたり 0.10%
HEDGE_FEE = 0.0012             # ヘッジあり投信の信託報酬の上乗せ 年0.12%（たわら先進国 0.22% − ヘッジなし 0.0989%）
TAX = 0.20315
LOG = []

FRED = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id={}'
BOJ = 'https://www.stat-search.boj.or.jp/api/v1/getDataCode?format=json&lang=en&db=FM02&code={}&startDate={}&endDate=202612'
ESTAT_CPI = 'https://www.e-stat.go.jp/stat-search/file-download?statInfId=000032103842&fileKind=1'
OECD_CPI = ('https://sdmx.oecd.org/public/rest/data/OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0/'
            'JPN+USA+CHE+DEU+GBR+CAN+AUS+SWE+NOR+NZL+EA20+FRA+ITA+NLD+ESP+DNK.M+Q.N.CPI.IX._T.N._Z?startPeriod=1955-01&format=csvfilewithlabels')

# 投資家の通貨（C5 の8通貨＋円）。fx=FRED の日次、quote=per_usd（1ドル=何単位）か usd_per（1単位=何ドル）
# rate=短期金利の候補（先頭＝翌日物コール、無い月だけ次の3か月物）。start=資本規制の撤廃・変動相場の後の最初の月
CUR = {
    'CHF': {'fx': 'DEXSZUS', 'quote': 'per_usd', 'rate': ['IRSTCI01CHM156N', 'IR3TIB01CHM156N'], 'cpi': ('CHE', 'M'), 'start': 198101, 'jkp': 'che'},
    'EUR': {'fx': 'DEXUSEU', 'quote': 'usd_per', 'rate': ['IRSTCI01DEM156N', 'IR3TIB01DEM156N'], 'cpi': ('DEU', 'M'), 'start': 199901, 'jkp': 'deu'},
    'GBP': {'fx': 'DEXUSUK', 'quote': 'usd_per', 'rate': ['IRSTCI01GBM156N', 'IR3TIB01GBM156N'], 'cpi': ('GBR', 'M'), 'start': 198101, 'jkp': 'gbr'},
    'CAD': {'fx': 'DEXCAUS', 'quote': 'per_usd', 'rate': ['IRSTCI01CAM156N', 'IR3TIB01CAM156N'], 'cpi': ('CAN', 'M'), 'start': 198101, 'jkp': 'can'},
    'AUD': {'fx': 'DEXUSAL', 'quote': 'usd_per', 'rate': ['IRSTCI01AUM156N', 'IR3TIB01AUM156N'], 'cpi': ('AUS', 'Q'), 'start': 198401, 'jkp': 'aus'},
    'SEK': {'fx': 'DEXSDUS', 'quote': 'per_usd', 'rate': ['IRSTCI01SEM156N', 'IR3TIB01SEM156N'], 'cpi': ('SWE', 'M'), 'start': 198907, 'jkp': 'swe'},
    'NOK': {'fx': 'DEXNOUS', 'quote': 'per_usd', 'rate': ['IRSTCI01NOM156N', 'IR3TIB01NOM156N'], 'cpi': ('NOR', 'M'), 'start': 199007, 'jkp': 'nor'},
    'NZD': {'fx': 'DEXUSNZ', 'quote': 'usd_per', 'rate': ['IRSTCI01NZM156N', 'IR3TIB01NZM156N'], 'cpi': ('NZL', 'Q'), 'start': 198504, 'jkp': 'nzl'},
}
USD_RATE = 'IRSTCI01USM156N'   # 米国の翌日物（FF金利の月平均）
PRIMARY_SIGS = ['V', 'M', 'C', 'VM']
E1_SIGS = ['VOTE2', 'VAMP', 'MAMP', 'RISK12']
E2_SIGS = ['TREND3', 'DIFF12', 'MRISK']       # 第2回の登録（out/mw_jpy_hedge_prereg2.json）
E3_SIGS = ['OLS3']                            # 第3回の登録（out/mw_jpy_hedge_prereg3.json）
PREREG3 = 'mw_jpy_hedge_prereg3.json'


def log(*a):
    s = ' '.join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


def ym_add(k, n):
    y, m = divmod(k, 100)
    t = y * 12 + (m - 1) + n
    return (t // 12) * 100 + t % 12 + 1


def months(a, z):
    out, k = [], a
    while k <= z:
        out.append(k)
        k = ym_add(k, 1)
    return out


# ───────────────────────── データ ─────────────────────────
def fred_rows(sid):
    b = M.get(FRED.format(sid), f'fred_{sid}.csv', max_age_days=3650).decode()
    out = []
    for ln in b.strip().splitlines()[1:]:
        d, v = ln.split(',')[:2]
        out.append((d, None if v.strip() in ('', '.') else float(v)))
    return out


def fred_monthly(sid):
    return {int(d[:4]) * 100 + int(d[5:7]): v for d, v in fred_rows(sid) if v is not None}


def fred_monthend(sid):
    """日次の FRED → その月の最後の有効な値（月末の相場）"""
    out = {}
    for d, v in fred_rows(sid):
        if v is not None:
            out[int(d[:4]) * 100 + int(d[5:7])] = v   # 日付順なので最後に書いた値＝最後の営業日
    return out


def boj_monthly(code, start):
    j = json.loads(M.get(BOJ.format(code, start), f'jh_boj_{code}.json', max_age_days=30))
    r = j['RESULTSET'][0]
    return {int(d): float(v) for d, v in zip(r['VALUES']['SURVEY_DATES'], r['VALUES']['VALUES']) if v is not None}


def jpy_rate():
    """円の短期金利（年率%・月平均）: 1985-06 までは有担保コール翌日物、1985-07 からは無担保コール翌日物（日銀 FM02）"""
    col = boj_monthly('STRACLCOON', 196001)
    unc = boj_monthly('STRACLUCON', 198501)
    out = {k: v for k, v in col.items() if k < 198507}
    out.update({k: v for k, v in unc.items() if k >= 198507})
    return out


def jp_cpi():
    """総務省 消費者物価指数（2020年基準・総合）1970-01〜（e-Stat の長期時系列 CSV・Shift_JIS）"""
    t = M.get(ESTAT_CPI, 'jh_estat', max_age_days=30).decode('cp932', 'replace')
    rows = list(csv.reader(io.StringIO(t)))
    assert rows[0][1] == '総合', rows[0][:3]
    out = {}
    for r in rows:
        if r and len(r[0]) == 6 and r[0].isdigit() and r[1].strip():
            out[int(r[0])] = float(r[1])
    return out


def oecd_cpi():
    b = M.get(OECD_CPI, 'jh_oecd_cpi_all.csv', max_age_days=60).decode('utf-8-sig')
    out = {}
    for r in csv.DictReader(io.StringIO(b)):
        if r['OBS_VALUE'] in ('', 'NaN'):
            continue
        p = r['TIME_PERIOD']
        if r['FREQ'] == 'M':
            k = int(p[:4]) * 100 + int(p[5:7])
        else:
            k = int(p[:4]) * 100 + int(p[-1]) * 3   # 四半期は最後の月に置く
        out.setdefault((r['REF_AREA'], r['FREQ']), {})[k] = float(r['OBS_VALUE'])
    return out


def cpi_known(series, freq, t):
    """月末 t に分かっている最新の物価（その時点で公表済みの値だけ）: 月次は t−1 月、無ければ t−2・t−3 月（公表されなかった月＝
    例: 米国 2025-10 は政府閉鎖で集計なし）。四半期は最後の月が t−2 以前の最新の四半期、無ければその前の四半期。
    それより古い値しか無ければ None（欠測を埋めない）"""
    if freq == 'M':
        for i in (1, 2, 3):
            v = series.get(ym_add(t, -i))
            if v is not None:
                return v
        return None
    m2 = ym_add(t, -2)
    y, m = divmod(m2, 100)
    qm = (m // 3) * 3
    k = y * 100 + qm if qm else (y - 1) * 100 + 12
    v = series.get(k)
    return v if v is not None else series.get(ym_add(k, -3))


def rate_series(cands):
    ss = [fred_monthly(c) for c in cands]
    ks = set().union(*[set(s) for s in ss])
    out = {}
    for k in ks:
        for s in ss:
            if k in s:
                out[k] = s[k]
                break
    return out


def load():
    ff = M.ff_factors()
    D = {'mkt': ff['mkt'], 'mktrf': ff['mktrf'], 'rf': ff['rf']}
    D['usd_rate'] = fred_monthly(USD_RATE)
    D['us_cpi'] = fred_monthly('CPIAUCNS')
    oc = oecd_cpi()
    cur = {'JPY': {'S': fred_monthend('DEXJPUS'), 'r': jpy_rate(), 'cpi': jp_cpi(), 'cpi_freq': 'M', 'start': START_JP}}
    for c, cf in CUR.items():
        raw = fred_monthend(cf['fx'])
        S_ = {k: (v if cf['quote'] == 'per_usd' else 1 / v) for k, v in raw.items() if v}
        cur[c] = {'S': S_, 'r': rate_series(cf['rate']), 'cpi': oc.get(cf['cpi'], {}), 'cpi_freq': cf['cpi'][1], 'start': cf['start']}
    D['cur'] = cur
    return D


# ───────────────────────── 信号 ─────────────────────────
def signals(D, c, S_=None, r_c=None, cpi_c=None, cpi_freq=None, r_other=None, cpi_other=None, other_freq='M'):
    """投資家の通貨 c が外貨（既定は米ドル）を持つときの信号。S_ = 外貨1単位あたりの c（高い＝外貨高・c安）。
    戻り値 {名前: {月末 t: True（ヘッジ）/False}}。計算できない月は入れない（欠測を False にしない）"""
    X = D['cur'][c]
    S_ = S_ if S_ is not None else X['S']
    r_c = r_c if r_c is not None else X['r']
    cpi_c = cpi_c if cpi_c is not None else X['cpi']
    cpi_freq = cpi_freq or X['cpi_freq']
    r_o = r_other if r_other is not None else D['usd_rate']
    cpi_o = cpi_other if cpi_other is not None else D['us_cpi']
    ks = sorted(S_)
    q = {}
    for t in ks:
        a, b = cpi_known(cpi_o, other_freq, t), cpi_known(cpi_c, cpi_freq, t)
        if a is not None and b is not None:
            q[t] = S_[t] * a / b          # 実質の外貨の値段（高い＝外貨が実質で割高）
    sig = {k: {} for k in PRIMARY_SIGS + E1_SIGS + E2_SIGS + E3_SIGS}
    mkt_ex = D['mktrf']
    for t in ks:
        # V: 実質の値段が過去60か月（当月を含む）の平均より上ならヘッジ
        w = [q.get(ym_add(t, -i)) for i in range(60)]
        if None not in w:
            sig['V'][t] = q[t] > sum(w) / 60
        # VAMP: 4.5〜5.5年前の平均（t−66〜t−54 の13か月）より実質で高ければヘッジ（AMP 2013 の価値）
        w2 = [q.get(ym_add(t, -i)) for i in range(54, 67)]
        if t in q and None not in w2:
            sig['VAMP'][t] = q[t] > sum(w2) / len(w2)
        # M: 12か月の外貨の変化が負（c 高）ならヘッジ
        p = S_.get(ym_add(t, -12))
        if p:
            sig['M'][t] = S_[t] / p - 1 < 0
        # C: c の短期金利 ≥ 外貨の短期金利ならヘッジ（ヘッジで金利差を払わない時だけ）
        if t in r_c and t in r_o:
            sig['C'][t] = r_c[t] >= r_o[t]
        # MAMP: 外貨を持つ超過リターン（為替＋金利差）の t−11〜t−1（直近1か月を飛ばす11か月）が負ならヘッジ
        ok, g = True, 1.0
        for i in range(1, 12):
            s = ym_add(t, -i); s0 = ym_add(s, -1)
            if s in S_ and s0 in S_ and s0 in r_c and s0 in r_o:
                g *= S_[s] / S_[s0] * (1 + r_o[s0] / 1200) / (1 + r_c[s0] / 1200)
            else:
                ok = False
                break
        if ok:
            sig['MAMP'][t] = g - 1 < 0
        # E2_TREND3: 1・3・12か月のドルを持つ超過リターン（t まで）のうち負の数 ÷ 3 ＝ヘッジの割合（HOP 2017 の混ぜ方）
        neg, ok3 = 0, True
        for L in (1, 3, 12):
            g3 = 1.0
            for i in range(L):
                s = ym_add(t, -i); s0 = ym_add(s, -1)
                if s in S_ and s0 in S_ and s0 in r_c and s0 in r_o:
                    g3 *= S_[s] / S_[s0] * (1 + r_o[s0] / 1200) / (1 + r_c[s0] / 1200)
                else:
                    ok3 = False
                    break
            if not ok3:
                break
            neg += g3 - 1 < 0
        if ok3:
            sig['TREND3'][t] = neg / 3
        # E2_DIFF12: 金利差（外貨 − c）が過去12か月で縮んだらヘッジ
        t12 = ym_add(t, -12)
        if t in r_c and t in r_o and t12 in r_c and t12 in r_o:
            sig['DIFF12'][t] = (r_o[t] - r_c[t]) - (r_o[t12] - r_c[t12]) < 0
        # RISK12: 米国株の12か月（t−11〜t）の超過リターンが負ならヘッジ（MOP 2012 の時系列モメンタム・安全資産の円）
        mm = [mkt_ex.get(ym_add(t, -i)) for i in range(12)]
        if None not in mm:
            sig['RISK12'][t] = math.prod(1 + x for x in mm) - 1 < 0
    for t in ks:
        if t in sig['V'] and t in sig['M']:
            sig['VM'][t] = sig['V'][t] and sig['M'][t]
        if t in sig['V'] and t in sig['M'] and t in sig['C']:
            sig['VOTE2'][t] = (sig['V'][t] + sig['M'][t] + sig['C'][t]) >= 2
        if t in sig['M'] and t in sig['RISK12']:
            sig['MRISK'][t] = sig['M'][t] or sig['RISK12'][t]
    # E3_OLS3: V・M・C の強さで翌月のドルを持つ超過の対数リターンを予想（拡大窓の最小二乗・月末 t までに実現した組だけ）
    xs, ys = {}, {}
    for t in ks:
        w = [q.get(ym_add(t, -i)) for i in range(60)]
        p = S_.get(ym_add(t, -12))
        if None not in w and p and t in r_c and t in r_o:
            xs[t] = (1.0, math.log(q[t] / (sum(w) / 60)), math.log(S_[t] / p), (r_o[t] - r_c[t]) / 1200)
        s0 = ym_add(t, -1)
        if s0 in S_ and s0 in r_c and s0 in r_o:
            ys[t] = math.log(S_[t] / S_[s0] * (1 + r_o[s0] / 1200) / (1 + r_c[s0] / 1200))
    XtX = [[0.0] * 4 for _ in range(4)]; Xty = [0.0] * 4; n = 0
    for t in ks:
        s0 = ym_add(t, -1)
        if s0 in xs and t in ys:                       # 組 (x_{t−1}, y_t) は月末 t に実現している
            x = xs[s0]
            for i in range(4):
                Xty[i] += x[i] * ys[t]
                for j in range(4):
                    XtX[i][j] += x[i] * x[j]
            n += 1
        if n >= 60 and t in xs:
            b = _solve(XtX, Xty)
            if b is not None:
                f = sum(bi * xi for bi, xi in zip(b, xs[t]))
                bas = BASIS if ym_add(t, 1) >= BASIS_FROM else 0.0
                sig['OLS3'][t] = f < -bas / 12
    return sig


def _solve(A, y):
    """4×4 の連立一次方程式（部分ピボットのガウス消去）。特異なら None"""
    n = len(y)
    M_ = [list(A[i]) + [y[i]] for i in range(n)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M_[r][c]))
        if abs(M_[piv][c]) < 1e-18:
            return None
        M_[c], M_[piv] = M_[piv], M_[c]
        for r in range(n):
            if r != c:
                fct = M_[r][c] / M_[c][c]
                for k in range(c, n + 1):
                    M_[r][k] -= fct * M_[c][k]
    return [M_[i][n] / M_[i][i] for i in range(n)]


# ───────────────────────── リターン ─────────────────────────
def returns(R, S_, r_c, r_o, basis=BASIS):
    """外貨建ての資産リターン R（月次）→ 投資家通貨 c のヘッジなし Ru と ヘッジあり Rh。
    Ru = (1+R)(1+x) − 1、Rh = R + R·x + f（月初の元本だけを1か月先渡しで売る＝月中の値上がり分の為替は残る）。
    f = (1 + (r_c − basis)/1200) / (1 + r_o/1200) − 1（金利は前月の月平均・ベーシスは 2008-01 から）"""
    Ru, Rh, rfc = {}, {}, {}
    for t in sorted(R):
        p = ym_add(t, -1)
        if t not in S_ or p not in S_ or p not in r_c or p not in r_o:
            continue
        x = S_[t] / S_[p] - 1
        b = basis if t >= BASIS_FROM else 0.0
        f = (1 + (r_c[p] - b * 100) / 1200) / (1 + r_o[p] / 1200) - 1
        Ru[t] = (1 + R[t]) * (1 + x) - 1
        Rh[t] = R[t] + R[t] * x + f
        rfc[t] = r_c[p] / 1200
    return Ru, Rh, rfc


def contiguous(keys_ok, start, end):
    """start から始めて、欠けた月の手前までの連続した月（欠測を飛ばして繋がない）"""
    out = []
    for k in months(start, end):
        if k not in keys_ok:
            break
        out.append(k)
    return out


def stock_series(sig, Ru, Rh, mlist, fee=0.0):
    """前月末の信号を当月に当てる（後知恵なし）。信号は True/False（全部か無し）か 0〜1 の割合（E2_TREND3）"""
    s, h, sw, prev = {}, {}, 0, None
    for t in mlist:
        st = float(sig[ym_add(t, -1)])
        s[t] = st * (Rh[t] - fee / 12) + (1 - st) * Ru[t]
        h[t] = st
        if prev is not None and st != prev:
            sw += 1
        prev = st
    return s, h, sw


def static_series(w, Ru, Rh, mlist, fee=0.0):
    return {t: w * (Rh[t] - fee / 12) + (1 - w) * Ru[t] for t in mlist}, {t: w for t in mlist}


def flow_sim(sig, Ru, Rh, mlist, fee=0.0):
    """FLOW: 毎月1を、前月末の信号がヘッジならヘッジあり、でなければヘッジなしへ入れる。持ち分は売らない。
    戻り値: (時間加重リターンの系列, ヘッジありの割合, 最終額の比 FLOW÷ヘッジなし積立)"""
    H = U = W = 0.0
    twr, hs = {}, {}
    for t in mlist:
        if sig[ym_add(t, -1)]:
            H += 1
        else:
            U += 1
        W += 1
        h = H / (H + U)
        twr[t] = h * (Rh[t] - fee / 12) + (1 - h) * Ru[t]
        hs[t] = h
        H *= 1 + Rh[t] - fee / 12
        U *= 1 + Ru[t]
        W *= 1 + Ru[t]
    return twr, hs, (H + U) / W if W else None


def flow_windows(sig, Ru, Rh, avail, years=20, start_month=7, step=None, fee=0.0):
    """FLOW の20年窓: 窓ごとに新しく積み立て始め、最終額の比 FLOW÷ヘッジなし積立。
    step=None なら毎年 start_month 月起点（C4 用）、step=12 なら最初の月から12か月おき（dca20 用）"""
    ks = sorted(avail)
    if not ks:
        return None
    n = years * 12
    starts = []
    if step is None:
        for y in range(ks[0] // 100, 2100):
            a = y * 100 + start_month
            starts.append(a)
            if ym_add(a, n - 1) > ks[-1]:
                break
    else:
        starts = ks[::step]
    out = []
    for a in starts:
        w = months(a, ym_add(a, n - 1))
        if any(k not in avail for k in w):
            continue
        out.append((a, round(flow_sim(sig, Ru, Rh, w, fee)[2], 4)))
    if not out:
        return None
    v = sorted(r for _, r in out)
    return {'windows': len(out), 'wins': sum(1 for r in v if r > 1), 'win_rate': round(sum(1 for r in v if r > 1) / len(v), 3),
            'median_ratio': v[len(v) // 2], 'median': v[len(v) // 2], 'worst': min(out, key=lambda x: x[1]), 'best': max(out, key=lambda x: x[1])}


def dca_ratio(s, b, mlist):
    ws = wb = 0.0
    for t in mlist:
        ws = (ws + 1) * (1 + s[t]); wb = (wb + 1) * (1 + b[t])
    return round(ws / wb, 4) if wb else None


# ───────────────────────── 税（報告のみ） ─────────────────────────
def _settle(gain, cf, year, rate=TAX):
    """年の実現損益 gain を3年の繰越損失 cf（[(年, 損)]）で相殺して税額を返す。cf はその場で更新"""
    cf[:] = [(y, l) for y, l in cf if year - y <= 3 and l > 1e-12]
    if gain <= 0:
        if gain < 0:
            cf.append((year, -gain))
        return 0.0
    for i, (y, l) in enumerate(cf):
        u = min(l, gain)
        gain -= u
        cf[i] = (y, l - u)
        if gain <= 0:
            break
    return rate * max(gain, 0.0)


def tax_switch(sig, Ru, Rh, mlist):
    """STOCK を課税口座で『投信を売って乗り換え』で行う: 乗り換えのたびに含み益に 20.315%（年末に年の損益を通算・3年繰越）。
    相手は同じ積立のヘッジなしを持ち続け、最後に一度だけ売る。最後は両方売ったあとの手取りの比"""
    V = B = 0.0; cur = None; rg = 0.0; cf = []; Wb = Bb = 0.0; sw = 0
    for i, t in enumerate(mlist):
        want = 'h' if sig[ym_add(t, -1)] else 'u'
        if cur is None:
            cur = want
        if want != cur and V > 0:
            rg += V - B; B = V; cur = want; sw += 1
        V += 1; B += 1; Wb += 1; Bb += 1
        V *= 1 + (Rh[t] if cur == 'h' else Ru[t])
        Wb *= 1 + Ru[t]
        last = i == len(mlist) - 1
        if t % 100 == 12 and not last:
            tx = _settle(rg, cf, t // 100); rg = 0.0
            if tx > 0 and V > 0:
                B *= (V - tx) / V; V -= tx
    tx = _settle(rg + V - B, cf, mlist[-1] // 100)
    after = V - tx
    after_b = Wb - TAX * max(Wb - Bb, 0.0)
    # 名前の是正（第2回の登録に記録）: 旧 pre_tax_ratio は『途中の税を払った後・最後の売却の税の前』の比だった
    return {'after_tax_ratio': round(after / after_b, 4), 'before_final_tax_ratio': round(V / Wb, 4),
            'no_tax_ratio': dca_ratio(*stock_series(sig, Ru, Rh, mlist)[:1], Ru, mlist), 'switches': sw}


def tax_overlay(s, Ru, mlist):
    """STOCK を『ヘッジなし投信は NISA で持ち続け、課税口座の為替の売り建て（先渡し・FX）で重ねる』で行う:
    重ねた分の損益 (W+1)·(Rs−Ru) を年ごとに通算し 20.315%（3年繰越）、税は年末に資産から払う。相手は NISA のヘッジなし（税なし）"""
    W = Wb = 0.0; pnl = 0.0; cf = []; paid = 0.0
    for i, t in enumerate(mlist):
        W += 1; Wb += 1
        pnl += W * (s[t] - Ru[t])
        W *= 1 + s[t]; Wb *= 1 + Ru[t]
        if t % 100 == 12 or i == len(mlist) - 1:
            tx = _settle(pnl, cf, t // 100); pnl = 0.0
            W -= tx; paid += tx
    return {'after_tax_ratio': round(W / Wb, 4), 'tax_paid_over_final': round(paid / Wb, 4)}


def tax_windows(fn, years=20, start_month=7, avail=None):
    ks = sorted(avail)
    out = []
    for y in range(ks[0] // 100, 2100):
        a = y * 100 + start_month
        w = months(a, ym_add(a, years * 12 - 1))
        if w[-1] > ks[-1]:
            break
        if any(k not in avail for k in w):
            continue
        out.append((a, fn(w)['after_tax_ratio']))
    if not out:
        return None
    v = sorted(r for _, r in out)
    return {'windows': len(out), 'win_rate': round(sum(1 for r in v if r > 1) / len(v), 3), 'median_ratio': v[len(v) // 2],
            'worst': min(out, key=lambda x: x[1]), 'best': max(out, key=lambda x: x[1])}


# ───────────────────────── 評価 ─────────────────────────
def periods(start, end):
    return {'full': (start, end), 'train': (start, M.TRAIN_END), 'hold': (M.HOLD_START, end),
            'recent': (M.RECENT_START, end), 'postpub': (POSTPUB, end)}


def turnover_cost(s, h, a, z):
    """費用: 切り替え1回=持ち分100%の入れ替え×0.10%（mw_common.apply_cost に期間の実績の年率回転を渡す）＋ヘッジ中は信託報酬 年0.12%上乗せ"""
    ks = [k for k in sorted(s) if a <= k <= z]
    if len(ks) < 24:
        return None, None
    sw = sum(abs(h[k] - h[p]) for p, k in zip(ks, ks[1:]))     # 片道の回転（全部か無しなら切り替えの回数と同じ）
    to = sw / (len(ks) / 12)
    c = M.apply_cost({k: s[k] for k in ks}, to, COST_UNIT)
    return {k: c[k] - h[k] * HEDGE_FEE / 12 for k in ks}, round(to, 2)


def eval_stock(name, s, h, Ru, rf, avail_all, start, end, sw_total):
    P = periods(start, end)
    r = {'impl': 'STOCK'}
    for nm, (a, z) in P.items():
        r[nm] = M.excess_stats(s, Ru, a, z)
    hn, to = turnover_cost(s, h, M.HOLD_START, end)
    r['hold_net'] = M.excess_stats(hn, Ru) if hn else None
    r['turnover_hold_oneway_per_yr'] = to
    r['switches_total'] = sw_total
    r['hedged_frac'] = {nm: round(S.mean(h[k] for k in h if a <= k <= z), 3) for nm, (a, z) in P.items() if any(a <= k <= z for k in h)}
    r['roll20'] = M.rolling(s, Ru, 20)
    r['dca20'] = M.dca(s, Ru, 20)
    r['sharpe'] = {nm: (M.sharpe(s, rf, a, z), M.sharpe(Ru, rf, a, z)) for nm, (a, z) in P.items()}
    r['maxdd'] = {nm: (round(M.maxdd(M.window(s, a, z)) * 100, 1), round(M.maxdd(M.window(Ru, a, z)) * 100, 1)) for nm, (a, z) in (('full', P['full']), ('hold', P['hold']))}
    r['dca_terminal_ratio'] = {nm: dca_ratio(s, Ru, [k for k in sorted(s) if a <= k <= z]) for nm, (a, z) in P.items()}
    return r


def eval_flow(name, sig, Ru, Rh, rf, avail, start, end):
    """FLOW は期間ごとに新しく積み立て始める（2007年からの人は2006年までの選択を引き継がない）"""
    P = periods(start, end)
    r = {'impl': 'FLOW'}
    path = {}
    for nm, (a, z) in P.items():
        ml = [k for k in sorted(avail) if a <= k <= z]      # full と train は同じ始まり（train は full の途中まで）
        if len(ml) < 24:
            r[nm] = None
            continue
        twr, hs, ratio = flow_sim(sig, Ru, Rh, ml)
        path[nm] = (twr, hs, ml)
        r[nm] = M.excess_stats(twr, Ru)
        r.setdefault('dca_terminal_ratio', {})[nm] = round(ratio, 4)
        r.setdefault('hedged_share_end', {})[nm] = round(hs[ml[-1]], 3)
        r.setdefault('sharpe', {})[nm] = (M.sharpe(twr, rf), M.sharpe({k: Ru[k] for k in ml}, rf))
    if 'hold' in path:
        twr, hs, ml = path['hold']
        twr_n, _, _ = flow_sim(sig, Ru, Rh, ml, fee=HEDGE_FEE)
        r['hold_net'] = M.excess_stats(twr_n, Ru)
        r['maxdd'] = {'hold': (round(M.maxdd(twr) * 100, 1), round(M.maxdd({k: Ru[k] for k in ml}) * 100, 1))}
    if 'full' in path:
        twr, hs, ml = path['full']
        r.setdefault('maxdd', {})['full'] = (round(M.maxdd(twr) * 100, 1), round(M.maxdd({k: Ru[k] for k in ml}) * 100, 1))
    r['roll20'] = flow_windows(sig, Ru, Rh, set(avail))            # C4（FLOW は一括が定義できないので積立の窓）
    r['dca20'] = flow_windows(sig, Ru, Rh, set(avail), step=12)
    r['roll20_note'] = 'FLOW は一括投資が定義できない（最初の1回の選択だけの賭けになる）ので、C4 は毎年7月起点の20年積立の最終額の比（>1 で勝ち）'
    return r


def build_currency(D, c, basis=BASIS, asset='US', R_asset=None, S_=None, r_o=None, cpi_o=None, o_freq='M', start=None, end=END_M):
    """投資家通貨 c の『ヘッジなし』『ヘッジあり』リターンと信号。asset='US' は French Mkt（米ドル）"""
    X = D['cur'][c]
    R = R_asset if R_asset is not None else D['mkt']
    S_ = S_ if S_ is not None else X['S']
    r_o = r_o if r_o is not None else D['usd_rate']
    Ru, Rh, rfc = returns(R, S_, X['r'], r_o, basis)
    sig = signals(D, c, S_=S_, r_other=r_o, cpi_other=cpi_o, other_freq=o_freq)
    return Ru, Rh, rfc, sig


def avail_for(sig_names, sig, Ru, start, end):
    """start 以降で、リターンと全部の信号がそろう最初の月から、欠けた月の手前までの連続した月"""
    ok = set()
    for t in months(start, end):
        p = ym_add(t, -1)
        if t in Ru and all(p in sig[n] for n in sig_names):
            ok.add(t)
    if not ok:
        return []
    return contiguous(ok, min(ok), end)


def git_sha(path):
    try:
        return subprocess.run(['git', 'log', '-1', '--format=%h', '--', path], cwd=M.BASE, capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa
        return None


# ───────────────────────── 点検（データの有無だけ） ─────────────────────────
def check():
    D = load()
    log('French Mkt', min(D['mkt']), max(D['mkt']), 'RF', min(D['rf']), max(D['rf']))
    log('USD rate', min(D['usd_rate']), max(D['usd_rate']), 'US CPI', min(D['us_cpi']), max(D['us_cpi']))
    for c, X in D['cur'].items():
        log(c, 'FX', min(X['S']), max(X['S']), len(X['S']), '| rate', min(X['r']), max(X['r']), len(X['r']),
            '| CPI', X['cpi_freq'], min(X['cpi']) if X['cpi'] else None, max(X['cpi']) if X['cpi'] else None, len(X['cpi']), '| start', X['start'])
        Ru, Rh, rfc, sig = build_currency(D, c)
        st = max(X['start'], min(Ru))
        av = avail_for(PRIMARY_SIGS, sig, Ru, st, END_M)
        av1 = avail_for(PRIMARY_SIGS + E1_SIGS, sig, Ru, st, END_M)
        log('   primary 評価月', av[0] if av else None, av[-1] if av else None, len(av), '| E1 込み', av1[0] if av1 else None, av1[-1] if av1 else None, len(av1))
    J = D['cur']['JPY']
    for k in (198508, 199504, 201110, 202406, 202608):
        log('USDJPY 月末', k, J['S'].get(k), '円金利', J['r'].get(k), 'JP CPI', J['cpi'].get(k))
    for c, cf in CUR.items():
        log('JKP', cf['jkp'], min(M.jkp_mkt(cf['jkp'], 'vw')), max(M.jkp_mkt(cf['jkp'], 'vw')))


# ───────────────────────── 本番 ─────────────────────────
def run():
    D = load()
    out = {'angle': 'jpy_hedge', 'prereg': PREREG, 'prereg_commit': git_sha(os.path.join('out', PREREG)),
           'prereg2': PREREG2, 'prereg2_commit': git_sha(os.path.join('out', PREREG2)),
           'prereg3': PREREG3, 'prereg3_commit': git_sha(os.path.join('out', PREREG3)), 'tested': [], 'log': LOG}
    J = D['cur']['JPY']
    Ru, Rh, rfj, sig = build_currency(D, 'JPY')
    avail = avail_for(PRIMARY_SIGS + E1_SIGS, sig, Ru, START_JP, END_M)
    assert avail[0] == START_JP and avail[-1] == END_M, (avail[0], avail[-1])
    A = set(avail)

    # ── 点検（再現・整合）
    sc = {}
    m = D['mkt']
    sc['french_mkt_cagr_1926'] = round(M.cagr(m) * 100, 2)
    sc['french_mkt_cagr_2007'] = round(M.cagr(M.window(m, M.HOLD_START)) * 100, 2)
    sc['usdjpy_monthend'] = {str(k): J['S'].get(k) for k in (198508, 199504, 200706, 201110, 201506, 202406, 202608)}
    fx = {t: J['S'][t] / J['S'][ym_add(t, -1)] - 1 for t in avail}
    sc['corr_usdjpy_mktrf_1981'] = round(M.corr([fx[t] for t in avail], [D['mktrf'][t] for t in avail]), 3)
    sc['us_mkt_in_jpy_cagr'] = {nm: round(M.cagr({k: Ru[k] for k in avail if a <= k <= z}) * 100, 2) for nm, (a, z) in periods(START_JP, END_M).items()}
    sc['us_mkt_in_usd_cagr'] = {nm: round(M.cagr({k: m[k] for k in avail if a <= k <= z}) * 100, 2) for nm, (a, z) in periods(START_JP, END_M).items()}
    # 評論の走り書き（1985-08〜2006: ヘッジなし − ヘッジあり = −0.22%/年 t−0.07）との照合
    st = M.excess_stats(Ru, Rh, 198508, M.TRAIN_END)
    sc['critic_repro_unhedged_minus_hedged_198508_2006'] = {'ex_ann': st['ex_ann'], 't': st['t'], 'critic': '−0.22 t−0.07'}
    for a in (M.HOLD_START, M.RECENT_START):
        st = M.excess_stats(Ru, Rh, a, END_M)
        sc[f'unhedged_minus_hedged_{a}'] = {'ex_ann': st['ex_ann'], 't': st['t']}
    sc['critic_other'] = '評論: 2007〜 +3.35 t1.44 / 2013-07〜 +5.74 t2.42'
    # 符号の違いの説明の点検: ドルの金利を FF 金利ではなく T-bill（French RF）にすると、ヘッジの費用が小さくなる側に動く
    tb = {k: v * 1200 for k, v in D['rf'].items()}
    Ru_tb, Rh_tb, _ = returns(D['mkt'], J['S'], J['r'], {ym_add(k, 0): v for k, v in tb.items()})
    st = M.excess_stats(Ru_tb, Rh_tb, 198508, M.TRAIN_END)
    sc['critic_repro_with_tbill_as_usd_rate'] = {'ex_ann': st['ex_ann'], 't': st['t'],
                                                 'note': 'French RF は月 t のリターン＝月初に分かっている T-bill。ここでは前月の値として使うので1か月ずれる（点検のためだけ）'}
    sc['hand_check_198510'] = {'R_usd': round(m[198510], 5), 'S_prev': J['S'][198509], 'S': J['S'][198510], 'r_jpy_prev': J['r'][198509],
                               'r_usd_prev': D['usd_rate'][198509], 'Ru': round(Ru[198510], 5), 'Rh': round(Rh[198510], 5),
                               'Rh_by_hand': round(m[198510] + m[198510] * (J['S'][198510] / J['S'][198509] - 1)
                                                   + (1 + J['r'][198509] / 1200) / (1 + D['usd_rate'][198509] / 1200) - 1, 5)}
    # 日本の物価: e-Stat（2020年基準）と FRED/OECD（2015年基準・2021-06 まで）の前年比の最大差
    fr = fred_monthly('JPNCPIALLMINMEI')
    es = J['cpi']
    dif = [abs((es[k] / es[ym_add(k, -12)]) - (fr[k] / fr[ym_add(k, -12)])) * 100 for k in es if k in fr and ym_add(k, -12) in fr and ym_add(k, -12) in es]
    sc['jp_cpi_yoy_maxdiff_pt_vs_oecd'] = round(max(dif), 2)
    sc['jp_cpi_yoy_meandiff_pt_vs_oecd'] = round(S.mean(dif), 3)
    # 後知恵なし: 信号 t はリターン t+1 にだけ当てる（stock_series / flow_sim の中で ym_add(t,−1) を引く）
    sc['no_lookahead'] = '信号は前月末（ym_add(t,−1)）のものだけを当月に当てる。物価は1か月（四半期は2か月）遅れ。金利は前月の月平均'
    # 恒等: 金利差0・ベーシス0なら Rh = R + R·x
    t0 = avail[100]
    sc['identity_check'] = round(((1 + m[t0]) * (1 + fx[t0]) - 1) - Ru[t0], 12)
    out['sanity'] = sc
    log('点検', json.dumps(sc, ensure_ascii=False))

    # ── C5 と新しい検定のための準備
    cur_data = {}
    for c in CUR:
        X = D['cur'][c]
        cRu, cRh, crf, csig = build_currency(D, c)
        st_ = max(X['start'], ym_add(min(cRu), 1))
        cur_data[c] = (cRu, cRh, crf, csig, st_)

    res = {}
    fam = {'P': {}, 'E1': {}, 'E2': {}, 'E3': {}}
    NEED = {'P': PRIMARY_SIGS, 'E1': PRIMARY_SIGS + E1_SIGS, 'E2': PRIMARY_SIGS + E2_SIGS, 'E3': E3_SIGS}

    def run_one(sid, sname, impl, family):
        avail = avail_for(NEED[family], sig, Ru, START_JP, END_M)    # P・E1・E2 は 1981-01〜、E3 は予想が作れる月から
        A = set(avail)
        if impl == 'STOCK':
            s, h, sw = stock_series(sig[sname], Ru, Rh, avail)
            r = eval_stock(sid, s, h, Ru, rfj, A, avail[0], END_M, sw)
        else:
            r = eval_flow(sid, sig[sname], Ru, Rh, rfj, avail, avail[0], END_M)
        r['eval_from'] = avail[0]
        r['family'] = family
        r['signal'] = sname
        r['latest_signal'] = {'month_end': avail[-1], 'hedge': sig[sname].get(avail[-1])}
        # 基準の割れ（ベーシス 0.6%）
        Ru6, Rh6, _ = returns(D['mkt'], J['S'], J['r'], D['usd_rate'], BASIS_STRESS)
        if impl == 'STOCK':
            s6, _, _ = stock_series(sig[sname], Ru6, Rh6, avail)
            r['hold_basis06'] = M.excess_stats(s6, Ru6, M.HOLD_START, END_M)
        else:
            ml = [k for k in avail if k >= M.HOLD_START]
            r['hold_basis06'] = M.excess_stats(flow_sim(sig[sname], Ru6, Rh6, ml)[0], Ru6)
        # C5: 同じ規則を他の8通貨の投資家（米国株を持つ）に当てる。全期間の超過が正の通貨を数える
        per = {}
        for c, (cRu, cRh, crf, csig, st_) in cur_data.items():
            av = avail_for(NEED[family], csig, cRu, st_, END_M)
            if len(av) < 60:
                continue
            if impl == 'STOCK':
                cs, _, _ = stock_series(csig[sname], cRu, cRh, av)
                full = M.excess_stats(cs, cRu); hold = M.excess_stats(cs, cRu, M.HOLD_START, END_M)
            else:
                full = M.excess_stats(flow_sim(csig[sname], cRu, cRh, av)[0], cRu)
                mh = [k for k in av if k >= M.HOLD_START]
                hold = M.excess_stats(flow_sim(csig[sname], cRu, cRh, mh)[0], cRu) if len(mh) >= 24 else None
            per[c] = {'from': av[0], 'to': av[-1], 'full_ex': full['ex_ann'] if full else None, 'full_t': full['t'] if full else None,
                      'hold_ex': hold['ex_ann'] if hold else None, 'hold_t': hold['t'] if hold else None}
        r['repl_units'] = per
        r['repl'] = {'regions': sum(1 for v in per.values() if v['full_ex'] is not None),
                     'positive': sum(1 for v in per.values() if (v['full_ex'] or 0) > 0)}
        r['repl_hold_reported'] = {'regions': sum(1 for v in per.values() if v['hold_ex'] is not None),
                                   'positive': sum(1 for v in per.values() if (v['hold_ex'] or 0) > 0)}
        # 税（報告のみ・STOCK だけ）
        if impl == 'STOCK':
            s, h, sw = stock_series(sig[sname], Ru, Rh, avail)
            mh = [k for k in avail if k >= M.HOLD_START]
            allornone = all(v in (0.0, 1.0) for v in h.values())
            r['tax'] = {
                'switch_in_taxable_full': tax_switch(sig[sname], Ru, Rh, avail) if allornone else None,
                'switch_in_taxable_hold': tax_switch(sig[sname], Ru, Rh, mh) if allornone else None,
                'switch_in_taxable_20y': tax_windows(lambda w: tax_switch(sig[sname], Ru, Rh, w), avail=A) if allornone else None,
                'overlay_fx_taxable_full': tax_overlay(s, Ru, avail),
                'overlay_fx_taxable_hold': tax_overlay(s, Ru, mh),
                'overlay_fx_taxable_20y': tax_windows(lambda w: tax_overlay(s, Ru, w), avail=A),
                'nisa_switches_per_year_hold': round(sum(1 for p, k in zip(mh, mh[1:]) if h[k] != h[p]) / (len(mh) / 12), 2),
                'note': 'NISA の中で乗り換えると、売った分の枠は翌年まで戻らず、買い直しに年の枠（つみたて120万・成長240万）を使う。持ち分が年の枠を超えた時点で STOCK の乗り換えは NISA の中ではできない'}
        else:
            r['tax'] = {'note': 'FLOW は売らないので税も NISA の枠の使い直しも起きない'}
        res[sid] = r
        fam[family][sid] = (r['hold'] or {}).get('p')
        out['tested'].append({'id': sid, 'family': family, 'impl': impl, 'signal': sname})
        log(sid, 'train', (r['train'] or {}).get('ex_ann'), (r['train'] or {}).get('t'), '| hold', (r['hold'] or {}).get('ex_ann'),
            (r['hold'] or {}).get('t'), (r['hold'] or {}).get('cagr_diff'), '| net', (r['hold_net'] or {}).get('ex_ann'),
            '| full', (r['full'] or {}).get('ex_ann'), (r['full'] or {}).get('t'), '| roll20', (r['roll20'] or {}).get('win_rate'),
            '| C5', r['repl'], 'hold', r['repl_hold_reported'])

    for sname in PRIMARY_SIGS:
        for impl in ('STOCK', 'FLOW'):
            run_one(f'P_{sname}_{impl}', sname, impl, 'P')
    for sname in E1_SIGS:
        run_one(f'E1_{sname}_STOCK', sname, 'STOCK', 'E1')
    # 第2回の登録（out/mw_jpy_hedge_prereg2.json）: E2 は第1回の結果を見た後の探索の族
    for sname in E2_SIGS:
        run_one(f'E2_{sname}_STOCK', sname, 'STOCK', 'E2')
    # 第3回の登録（out/mw_jpy_hedge_prereg3.json）: E3 は回帰で一つの予想にまとめる
    run_one('E3_OLS3_STOCK', 'OLS3', 'STOCK', 'E3')

    # ── 事後の参考（格付けしない）: M と MAMP を資本規制の時代（1974-03〜1980-12）へ後ろに延ばす
    back = {}
    for sname in ('M', 'MAMP'):
        avb = avail_for([sname], sig, Ru, 197403, END_M)
        sb, hb, _ = stock_series(sig[sname], Ru, Rh, avb)
        back[f'BACK_{sname}_STOCK'] = {'from': avb[0], 'pre1981': M.excess_stats(sb, Ru, None, 198012),
                                        'train_extended_1974_2006': M.excess_stats(sb, Ru, None, M.TRAIN_END),
                                        'full_extended_1974_2026': M.excess_stats(sb, Ru),
                                        'note': '事後（第1回の結果を見てから期間を延ばした）・格付けしない。資本規制の下で金利平価が成り立たない時代を含む'}
        out['tested'].append({'id': f'BACK_{sname}_STOCK', 'family': '事後', 'impl': 'STOCK', 'signal': sname, 'graded': False})
        log(f'BACK_{sname}_STOCK', 'pre1981', (back[f'BACK_{sname}_STOCK']['pre1981'] or {}).get('ex_ann'), (back[f'BACK_{sname}_STOCK']['pre1981'] or {}).get('t'),
            '| 延ばした訓練', back[f'BACK_{sname}_STOCK']['train_extended_1974_2006']['ex_ann'], back[f'BACK_{sname}_STOCK']['train_extended_1974_2006']['t'])
    out['post_hoc_back_extension'] = back

    # ── 参考: 常に50%・100%ヘッジ（族の外）
    for w in (0.5, 1.0):
        sid = f'REF_H{int(w * 100)}'
        s, h = static_series(w, Ru, Rh, avail)
        r = eval_stock(sid, s, h, Ru, rfj, A, START_JP, END_M, 0)
        sn, _ = static_series(w, Ru, Rh, [k for k in avail if k >= M.HOLD_START], fee=HEDGE_FEE)
        r['hold_net'] = M.excess_stats(sn, Ru)
        r['family'] = 'REF'
        res[sid] = r
        out['tested'].append({'id': sid, 'family': 'REF', 'impl': 'STATIC', 'signal': f'常に{int(w * 100)}%'})
        log(sid, 'train', r['train']['ex_ann'], r['train']['t'], '| hold', r['hold']['ex_ann'], r['hold']['t'], '| full', r['full']['ex_ann'], r['full']['t'])

    # ── 判定
    for fname, pv in fam.items():
        hol = M.holm(pv)
        for sid in pv:
            r = res[sid]
            sp = {'train': tuple(r['sharpe']['train']) if r['sharpe'].get('train') else None,
                  'hold': tuple(r['sharpe']['hold']) if r['sharpe'].get('hold') else None}
            g, crit = M.grade(r['full'], r['train'], r['hold'], r['roll20'], cost_hold=r['hold_net'], repl=r['repl'],
                              family_holm_p=hol.get(sid), sharpe_pair=sp, leveraged_or_timing=True)
            r.update(grade=g, criteria=crit, holm_p=hol.get(sid))
    for sid in ('REF_H50', 'REF_H100'):
        r = res[sid]
        sp = {'train': tuple(r['sharpe']['train']), 'hold': tuple(r['sharpe']['hold'])}
        g, crit = M.grade(r['full'], r['train'], r['hold'], r['roll20'], cost_hold=r['hold_net'], repl=None,
                          family_holm_p=None, sharpe_pair=sp, leveraged_or_timing=True)
        r.update(grade=g, criteria=crit, holm_p=None, grade_note='族の外の参考（格付けは参考）')

    # ── 新しい検定: 円の投資家が米国以外の先進国（JKP の国の市場・時価加重）を持つ（報告のみ）
    fresh = {}
    rfus = D['rf']
    jr = {}
    for c, cf in CUR.items():
        k = M.jkp_mkt(cf['jkp'], 'vw')
        R_usd = {t: v + rfus[t] for t, v in k.items() if t in rfus}          # JKP は米国短期金利を引いた超過 → 総リターンへ戻す
        Xc = D['cur'][c]
        # 円から見た外貨 c の値段: 1 c = (JPY/USD)/(c/USD) 円。持つ資産の外貨建てリターン = 米ドル建て ÷ (1+ドル/c の変化)
        Sx = {t: J['S'][t] / Xc['S'][t] for t in J['S'] if t in Xc['S']}
        R_loc = {}
        for t, v in R_usd.items():
            p = ym_add(t, -1)
            if t in Xc['S'] and p in Xc['S']:
                y = (1 / Xc['S'][t]) / (1 / Xc['S'][p]) - 1       # 1 c あたりのドルの変化
                R_loc[t] = (1 + v) / (1 + y) - 1
        Ru_c, Rh_c, _ = returns(R_loc, Sx, J['r'], Xc['r'])
        sig_c = signals(D, 'JPY', S_=Sx, r_other=Xc['r'], cpi_other=Xc['cpi'], other_freq=Xc['cpi_freq'])
        st_ = max(START_JP, Xc['start'], ym_add(min(R_loc), 1))
        av = avail_for(PRIMARY_SIGS, sig_c, Ru_c, st_, 202512)
        jr[c] = (Ru_c, Rh_c, sig_c, av)
    for sname in PRIMARY_SIGS:
        for impl in ('STOCK', 'FLOW'):
            sid = f'FRESH_{sname}_{impl}'
            per, exs = {}, {}
            for c, (Ru_c, Rh_c, sig_c, av) in jr.items():
                if len(av) < 60:
                    continue
                if impl == 'STOCK':
                    s_c, _, _ = stock_series(sig_c[sname], Ru_c, Rh_c, av)
                    f_ = M.excess_stats(s_c, Ru_c); h_ = M.excess_stats(s_c, Ru_c, M.HOLD_START, 202512)
                    exs[c] = {k: s_c[k] - Ru_c[k] for k in av}
                else:
                    tw = flow_sim(sig_c[sname], Ru_c, Rh_c, av)[0]
                    f_ = M.excess_stats(tw, Ru_c)
                    mh = [k for k in av if k >= M.HOLD_START]
                    h_ = M.excess_stats(flow_sim(sig_c[sname], Ru_c, Rh_c, mh)[0], Ru_c)
                    exs[c] = {k: tw[k] - Ru_c[k] for k in av}
                per[c] = {'from': av[0], 'to': av[-1], 'full_ex': f_['ex_ann'], 'full_t': f_['t'], 'hold_ex': h_['ex_ann'] if h_ else None, 'hold_t': h_['t'] if h_ else None}
            # 国を等しく混ぜた『米国以外の先進国』（その月にある国の平均の超過）
            allm = sorted(set().union(*[set(v) for v in exs.values()]))
            bask = {k: S.mean(v[k] for v in exs.values() if k in v) for k in allm}
            zero = {k: 0.0 for k in allm}
            fresh[sid] = {'countries': per,
                          'positive_full': [sum(1 for v in per.values() if v['full_ex'] > 0), len(per)],
                          'positive_hold': [sum(1 for v in per.values() if (v['hold_ex'] or 0) > 0), sum(1 for v in per.values() if v['hold_ex'] is not None)],
                          'basket_eq_full': M.excess_stats(bask, zero), 'basket_eq_train': M.excess_stats(bask, zero, None, M.TRAIN_END),
                          'basket_eq_hold': M.excess_stats(bask, zero, M.HOLD_START, None)}
            out['tested'].append({'id': sid, 'family': 'FRESH', 'impl': impl, 'signal': sname, 'graded': False})
            log(sid, '国 全', fresh[sid]['positive_full'], '保', fresh[sid]['positive_hold'], '束 保',
                (fresh[sid]['basket_eq_hold'] or {}).get('ex_ann'), (fresh[sid]['basket_eq_hold'] or {}).get('t'))
    out['fresh_test'] = fresh
    out['results'] = res

    # ── 要約
    summ = []
    for sid, r in res.items():
        summ.append({'id': sid, 'grade': r.get('grade'), 'family': r['family'],
                     'train_ex': (r['train'] or {}).get('ex_ann'), 'train_t': (r['train'] or {}).get('t'),
                     'hold_ex': (r['hold'] or {}).get('ex_ann'), 'hold_t': (r['hold'] or {}).get('t'), 'hold_cagr_diff': (r['hold'] or {}).get('cagr_diff'),
                     'hold_net_ex': (r['hold_net'] or {}).get('ex_ann'), 'full_ex': (r['full'] or {}).get('ex_ann'), 'full_t': (r['full'] or {}).get('t'),
                     'recent_ex': (r['recent'] or {}).get('ex_ann'), 'postpub_ex': (r.get('postpub') or {}).get('ex_ann'),
                     'roll20_win': (r['roll20'] or {}).get('win_rate'), 'dca20_win': (r['dca20'] or {}).get('win_rate'),
                     'dca20_median': (r['dca20'] or {}).get('median_ratio'), 'holm_p': r.get('holm_p'),
                     'repl': r.get('repl'), 'latest_signal': r.get('latest_signal')})
    out['summary'] = sorted(summ, key=lambda x: -(x['hold_ex'] or -99))
    out['counts'] = {'n_tested': len(out['tested']), 'graded': sum(1 for x in out['tested'] if x['family'] in ('P', 'E1', 'E2', 'E3')),
                     'grades': {g: sum(1 for x in summ if x['grade'] == g) for g in 'SABC'}}
    out['deviations'] = [
        'FLOW の C4 は一括の窓ではなく、毎年7月起点で新しく積み立て始める20年窓の最終額の比（FLOW は一括を持たないため・事前登録に明記）',
        '米国の物価 2025-10 は政府閉鎖で公表されなかった → 月末 t の物価は『その時点で公表済みの最新（t−1、無ければ t−2・t−3）』とした（事前登録の段階で決めた・測る前）',
        'DEM の日次（FRED DEXGEUS）は 404 で取れず、C5 の DEM/EUR は EUR（1999-01〜・V がそろう 2004-01 から）だけ',
        'ドルの金利は FF 金利（翌日物）。評論の走り書き（T-bill を使ったとみられる）とは符号が逆に出たが、T-bill に替えると −0.22 t−0.07 で一致（sanity の critic_repro_with_tbill_as_usd_rate）',
        '税の欄の名前の是正: 旧 pre_tax_ratio → before_final_tax_ratio、no_tax_ratio を追加（第2回の登録に記録・数字と判定は不変）',
        'E2・E3 は第1回の結果を見た後の登録（事前登録2・3に明記）。BACK（1974-1980 へ延ばした M・MAMP）は事後で格付けしない',
    ]
    out['conclusion_ja'] = ('格付けした16本（主 P 8・探索 E1 4・E2 3・E3 1）はすべて C。訓練期間（1981〜2006）で t ≥ 2 に届いた規則は一つも無い'
                            '（最大は E3_OLS3 の +3.15%/年 t1.75 で、保有期間は −2.15 t−1.07 に反転）。保有期間で費用後も正だったのは P_M_STOCK（+0.23）・'
                            'E1_MAMP_STOCK（+0.35）・E1_RISK12_STOCK（+0.19）の3本だけで、t はどれも0.5以下。FLOW（新しいお金だけ切り替える）は4本とも保有期間で負。'
                            '常に100%ヘッジは保有期間 −3.76%/年 t−1.63。『為替はヘッジしない』は、この検証の範囲では変える理由が見つからない')
    p = M.save(OUT, out)
    log('書いた', p)


if __name__ == '__main__':
    if '--check' in sys.argv:
        check()
    else:
        run()
