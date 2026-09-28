#!/usr/bin/env python3
"""night/nx_sentcond_data.py — nx 角度 sentcond（投資家の心理で堅い株と市場を切り替える）の**データの取得・整形だけ**
（成績は計算しない・リターンは一切読まない・読むだけ・門の判定には不使用）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて勝てる結果を出して…別のSessionで検証していない新たな分析を」。
事前登録: out/nx_sentcond_prereg.json（測る前に固定）／全体の線: out/nx_prereg.json（C1〜C8・格付け）。

何をするか
  Baker-Wurgler の心理指数（SENT）は、公開の値が**全期間の主成分**で作られている（後から分かる情報を含む）。
  そこで成分（閉鎖型ファンドの割引 cefd・IPO の数 nipo・IPO の初日の上昇 ripo・配当の割増し pdnd・株式の発行割合 s）から、
  **月末 t までに分かる値だけ**で、1965年からの**拡大窓の主成分**を毎月作り直す（その月の載荷量・平均・標準偏差もその窓だけ）。
  その各月の値 S_rt(t) と「高い（>0）か」を out/_nx_cache/nx_sentcond_signals.json に置き、並びの sha256 を出す
  （測る道具はこの sha256 が事前登録の値と一致するかを最初に確かめ、違えば止まる＝結果を見てから信号を作り直していない証明）。

成分の作り方（BW の Stata コード〔GitHub BWInvestorSentimentIndex・2026-01 版と 2019-03 版〕どおり）
  NIPO12(m) = nipo(m−11..m) の和（12か月そろう時だけ）
  RIPOAM(m) = ripo の nipo 加重平均（m−11..m）。nipo が12か月そろう時だけ。
              ★BW のコードは ripo の欠け（nipo>0 なのに ripo が無い月が 13 か月ある）を 0 と置くが、ここでは
               絶対のルール7（欠測を0と読まない）に従い、その月を分子・分母の両方から外す（'exclude'）。
               BW どおりの 'zero' は公開値の再現の検算にだけ使う。
  CEFD(m) = cefd(m)、PDND(m) = pdnd(m)、S(m) = s(m)
  BW の指数の月 m の成分 = (CEFD(m), NIPO12(m), RIPOAM(m−12), PDND(m−12), S(m))  … 'lag0'
  判断の月末 t に使う成分（公表の遅れを足した主の型 'main'）:
       CEFD(t−1), NIPO12(t−1), RIPOAM(t−13), PDND(t−13), S(t−3)
     （閉鎖型ファンドの割引・IPO は1か月、連銀の新規発行の統計は3か月遅らせる。ripo・pdnd は BW の12か月遅れに1か月を足す）
  主成分: 窓（最初にそろう月〜t）の中で各成分を標準化（平均・標本標準偏差）→ 相関行列の第1固有ベクトル w。
          向きは理論の符号（nipo・ripo・s は＋、cefd・pdnd は−＝BW 2006 の式(2)の符号）で Σ 符号×w > 0 にそろえる
          （公開値は『2000-12 が正』でそろえるが、それは 2000年以降にしか分からないので使わない）。
          S_rt(t) = w·z(t) を窓の中の標準偏差で割った値（窓の平均は0なので、> 0 は『窓の平均より上』と同じ）。
          窓は最低60か月（最初の判断は 1970-07 末・最初に持つ月は 1970-08）。

変形（探索・報告用。定義は事前登録に全部書いた）
  'lag0'      : BW の指数どおりの成分（公表の遅れを足さない）
  'nobwlag'   : ripo・pdnd の12か月遅れを外し、他と同じ1か月遅れにする（BW が標本の中で選んだ遅れの構造を使わない版）
  'practical' : BW の公開ファイルは年に1回（3月）の更新＝判断の月 t が4〜12月なら前年12月まで、1〜3月なら前々年12月までしか無い。
                その打ち切りの月 m* までの 'lag0' の成分で拡大窓の主成分を作り、m* の値の符号を使う
  'orth'      : 各成分を、その成分の日付（ただし t−2 より新しくしない）のマクロ5系列（鉱工業生産・雇用・実質の耐久財/非耐久財/
                サービス消費。2026年版の BW と同じく ln − 直前12か月の ln の平均）へ回帰した残差（拡大窓）で主成分。
                景気後退の印（NBER）は発表が6〜21か月遅れるので入れない
  'main_2019' : 2019-03 版のファイル（成分が別の版）で 'main' を作る＝版の違いが信号をどれだけ変えるかの報告用（〜2018-12）

使い方: python3 night/nx_sentcond_data.py            → out/_nx_cache/nx_sentcond_signals.json と sha256・形の要約
        python3 night/nx_sentcond_data.py --selftest → 先読みの検査（t より後の成分を乱数に替えても t までの信号が1つも変わらないか）
        python3 night/nx_sentcond_data.py --fetch    → 取得して期間・欠けの数だけを表示（French・JKP・Yahoo）
"""
import sys, os, io, json, hashlib, math, random, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N  # noqa: E402
import numpy as np  # noqa: E402

OUT = os.path.join(N.CACHE, 'nx_sentcond_signals.json')
BW_URL = 'https://pages.stern.nyu.edu/~jwurgler/data/SENTIMENT.xlsx'
BW_NAME = 'bw_SENTIMENT.xlsx'
BW_2019_NAME = 'bw_sentiment_20190327.xlsx'   # 斥候が取得（README『UPDATED: MARCH 27, 2019』・中に STATA CODE の枚あり）
PROXIES = ['cefd', 'nipo12', 'ripoam', 'pdnd', 's']
THEORY_SIGN = {'cefd': -1, 'nipo12': 1, 'ripoam': 1, 'pdnd': -1, 's': 1}
SPECS = {
    'main':    {'cefd': 1, 'nipo12': 1, 'ripoam': 13, 'pdnd': 13, 's': 3},
    'lag0':    {'cefd': 0, 'nipo12': 0, 'ripoam': 12, 'pdnd': 12, 's': 0},
    'nobwlag': {'cefd': 1, 'nipo12': 1, 'ripoam': 1, 'pdnd': 1, 's': 3},
}
MIN_WIN = 60
MACRO_LAG = 2
MACROS = ['indpro', 'employ', 'consdur', 'consnon', 'consserv']

# C5（米国外）と実物の答え合わせに使う系列（取得して形だけ見る）
FRENCH_FILES = {
    '6_Portfolios_ME_OP_2x3': ('Average Value Weighted Returns -- Monthly', ['BIG HiOP', 'SMALL LoOP']),
    'Portfolios_Formed_on_VAR': ('Value Weighted Returns -- Monthly', ['Lo 20', 'Hi 20']),
    'Portfolios_Formed_on_BETA': ('Value Weighted Returns -- Monthly', ['Lo 20', 'Hi 20']),
    'Portfolios_Formed_on_D-P': ('Value Weight Returns -- Monthly', ['Hi 30', '<= 0', 'Lo 30', 'Med 40']),
    'Portfolios_Formed_on_RESVAR': ('Value Weighted Returns -- Monthly', ['Lo 20']),
    'F-F_Research_Data_Factors': (None, None),
}
JKP_COUNTRIES = ['jpn', 'gbr', 'can', 'fra', 'deu', 'aus', 'che']
JKP_CHARS = {'ope_be': '3.0', 'rvol_21d': '1.0', 'beta_60m': '1.0', 'div12m_me': '3.0'}  # 堅い側（理論で先に決める・JKP の pf は特性の小さい順）
ETFS = ['VIG', 'DVY', 'USMV', 'SPY']


# ───────────────────────── 読み込み ─────────────────────────
def load_bw(name=BW_NAME, url=BW_URL):
    import openpyxl
    if name == BW_NAME:
        b = N.get(url, name=name, max_age_days=3650)
    else:
        b = open(os.path.join(N.CACHE, name), 'rb').read()
    wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
    rows = list(wb['DATA'].iter_rows(values_only=True))
    hdr = [str(c).strip() if c is not None else '' for c in rows[0]]
    d = {h: {} for h in hdr if h}
    for r in rows[1:]:
        if r[0] is None:
            continue
        try:
            ym = int(str(r[0]).strip()[:6])
        except ValueError:
            continue
        for h, v in zip(hdr, r):
            if not h or h == 'yearmo' or v is None or str(v).strip() in ('.', ''):
                continue
            try:
                x = float(v)
            except (TypeError, ValueError):
                continue
            if not math.isnan(x):
                d[h][ym] = x
    return d, hashlib.sha256(b).hexdigest()


def add(ym, k):
    y, m = divmod(ym, 100)
    n = y * 12 + (m - 1) + k
    return (n // 12) * 100 + n % 12 + 1


def months(a, z):
    out, m = [], a
    while m <= z:
        out.append(m)
        m = add(m, 1)
    return out


# ───────────────────────── 成分 ─────────────────────────
def proxies(d, ripo_missing='exclude'):
    nipo, ripo = d['nipo'], d['ripo']
    lo, hi = min(nipo), max(nipo)
    P = {'cefd': dict(d['cefd']), 'pdnd': dict(d['pdnd']), 's': dict(d['s']), 'nipo12': {}, 'ripoam': {}}
    for m in months(add(lo, 11), hi):
        win = [add(m, -j) for j in range(12)]
        if not all(w in nipo for w in win):
            continue
        P['nipo12'][m] = sum(nipo[w] for w in win)
        num = den = 0.0
        for w in win:
            n = nipo[w]
            if n == 0:
                continue
            if w in ripo:
                r = ripo[w]
            elif ripo_missing == 'zero':
                r = 0.0
            else:
                continue  # 欠測を0と読まない（分子・分母の両方から外す）
            num += n * r; den += n
        if den > 0:
            P['ripoam'][m] = num / den
    return P


def vectors(P, spec):
    """判断の月 t → 成分のベクトル（spec の遅れで）。どれか欠けたら入れない"""
    out = {}
    lo = min(min(v) for v in P.values() if v)
    hi = max(max(v) for v in P.values() if v)
    for t in months(lo, add(hi, 13)):
        v = []
        for k in PROXIES:
            x = P[k].get(add(t, -spec[k]))
            if x is None:
                break
            v.append(x)
        else:
            out[t] = v
    return out


def macro_dev(d):
    """マクロ5系列の ln − 直前12か月（t−12..t−1）の ln の平均（2026年版 BW と同じ・消費は CPI で実質化）。10か月以上そろう時だけ"""
    cpi = d.get('cpi', {})
    lv = {}
    for k in MACROS:
        src = d.get(k, {})
        s = {}
        for m, x in src.items():
            if k.startswith('cons'):
                if m in cpi and cpi[m] > 0 and x > 0:
                    s[m] = math.log(x / cpi[m])
            elif x > 0:
                s[m] = math.log(x)
        lv[k] = s
    M = {}
    ms = sorted(set.intersection(*[set(v) for v in lv.values()]))
    for m in ms:
        row = []
        for k in MACROS:
            prev = [lv[k][add(m, -j)] for j in range(1, 13) if add(m, -j) in lv[k]]
            if len(prev) < 10:
                break
            row.append(lv[k][m] - sum(prev) / len(prev))
        else:
            M[m] = row
    return M


# ───────────────────────── 拡大窓の主成分 ─────────────────────────
def pc1(Xw):
    """Xw: 窓の行列（行=月・列=成分）→ (w, mu, sd, scores)。相関行列の第1固有ベクトルを理論の符号でそろえる"""
    mu = Xw.mean(axis=0)
    sd = Xw.std(axis=0, ddof=1)
    Z = (Xw - mu) / sd
    C = np.corrcoef(Z, rowvar=False)
    val, vec = np.linalg.eigh(C)
    w = vec[:, int(np.argmax(val))]
    if sum(THEORY_SIGN[k] * w[i] for i, k in enumerate(PROXIES)) < 0:
        w = -w
    sc = Z @ w
    return w, mu, sd, sc, float(val.max() / val.sum())


def realtime(V, min_win=MIN_WIN, resid_on=None):
    """V: {t: [5成分]}。各 t で [最初の月, t] の窓だけで主成分を作り、S_rt(t)（窓の標準偏差で割った値）と載荷量を返す。
    resid_on: {t: [[1, マクロ...] × 5成分]} を渡すと、窓の中で各成分をマクロへ回帰した残差で主成分（'orth'）"""
    ts = sorted(V)
    out = {}
    for i, t in enumerate(ts):
        win = ts[:i + 1]
        if resid_on is not None:
            win = [s for s in win if s in resid_on]
            if t not in resid_on:
                continue
        if len(win) < min_win:
            continue
        X = np.array([V[s] for s in win], dtype=float)
        if resid_on is not None:
            R = np.empty_like(X)
            for j in range(X.shape[1]):
                A = np.array([resid_on[s][j] for s in win], dtype=float)
                beta, *_ = np.linalg.lstsq(A, X[:, j], rcond=None)
                R[:, j] = X[:, j] - A @ beta
            X = R
        w, mu, sd, sc, share = pc1(X)
        s_sd = float(np.std(sc, ddof=1))
        med = float(np.median(sc))
        out[t] = {'S': float(sc[-1] / s_sd), 'above_median': bool(sc[-1] > med), 'w': [round(float(x), 6) for x in w],
                  'pc1_share': round(share, 4), 'n': len(win)}
    return out


def orth_regressors(V, spec, M):
    """'orth' の説明変数: 成分 k の日付 d_k(t)=t−off_k。マクロは min(d_k(t), t−MACRO_LAG) の月の値（それより新しいものは使わない）"""
    R = {}
    for t in V:
        rows = []
        for k in PROXIES:
            e = min(add(t, -spec[k]), add(t, -MACRO_LAG))
            if e not in M:
                break
            rows.append([1.0] + M[e])
        else:
            R[t] = rows
    return R


def practical(P):
    """BW の公開ファイルの更新（年1回・3月）で分かる範囲だけ: 判断の月 t（4〜12月→前年12月まで・1〜3月→前々年12月まで）。
    打ち切りの月 m* までの 'lag0' の成分で拡大窓の主成分を作り、m* の値の符号を t の信号にする"""
    V0 = vectors(P, SPECS['lag0'])
    ts = sorted(V0)
    cache, out = {}, {}
    lo, hi = ts[0], add(ts[-1], 16)
    for t in months(lo, hi):
        y, mo = divmod(t, 100)
        mstar = (y - 1) * 100 + 12 if mo >= 4 else (y - 2) * 100 + 12
        if mstar not in cache:
            win = [s for s in ts if s <= mstar]
            if len(win) < MIN_WIN or mstar not in V0:
                cache[mstar] = None
            else:
                X = np.array([V0[s] for s in win], dtype=float)
                w, mu, sd, sc, share = pc1(X)
                cache[mstar] = {'S': float(sc[-1] / np.std(sc, ddof=1)), 'w': [round(float(x), 6) for x in w], 'n': len(win), 'mstar': mstar}
        if cache[mstar] is not None and t > mstar:
            out[t] = dict(cache[mstar])
    return out


def build(d):
    P = proxies(d, 'exclude')
    sig = {}
    for name, spec in SPECS.items():
        sig[name] = realtime(vectors(P, spec))
    Vm = vectors(P, SPECS['main'])
    sig['orth'] = realtime(Vm, resid_on=orth_regressors(Vm, SPECS['main'], macro_dev(d)))
    sig['practical'] = practical(P)
    return sig


def regime_sha(sig):
    """信号の並び（月 → 高い=1/それ以外=0、と above_median）を決まった形で直列化した sha256"""
    canon = {name: {str(t): [int(v['S'] > 0), int(v.get('above_median', False))] for t, v in sorted(s.items())} for name, s in sorted(sig.items())}
    return hashlib.sha256(json.dumps(canon, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def replication_check(d):
    """構成の検算（リターンは使わない）: BW どおりの成分（'lag0'・ripo の欠けは 0）で 1965-07〜2025-12 の全期間の主成分を作り、
    公開の SENT との相関を出す。2000-12 が正になる向きにそろえる（公開値の約束）"""
    res = {}
    for mode in ('zero', 'exclude'):
        P = proxies(d, mode)
        V = vectors(P, SPECS['lag0'])
        ts = [t for t in sorted(V) if 196507 <= t <= 202512]
        X = np.array([V[t] for t in ts], dtype=float)
        w, mu, sd, sc, share = pc1(X)
        sc = sc / np.std(sc, ddof=1)
        if sc[ts.index(200012)] < 0:
            sc = -sc
        pub = [d['SENT'].get(t) for t in ts]
        ok = [i for i, p in enumerate(pub) if p is not None]
        c = float(np.corrcoef([sc[i] for i in ok], [pub[i] for i in ok])[0, 1])
        mad = float(np.max(np.abs(np.array([sc[i] for i in ok]) - np.array([pub[i] for i in ok]))))
        res[mode] = {'months': len(ok), 'corr_with_published_SENT': round(c, 5), 'max_abs_diff': round(mad, 4),
                     'loadings': dict(zip(PROXIES, [round(float(x), 3) for x in w])), 'pc1_share': round(share, 3)}
    return res


# ───────────────────────── 先読みの検査 ─────────────────────────
def selftest():
    d, _ = load_bw()
    rng = random.Random(20260928)
    base = build(d)
    for T0 in (198512, 200612, 201512):
        d2 = {k: dict(v) for k, v in d.items()}
        for k in ('cefd', 'nipo', 'ripo', 'pdnd', 's') + tuple(MACROS) + ('cpi',):
            for m in list(d2.get(k, {})):
                if m > T0:
                    d2[k][m] = d2[k][m] * (1 + rng.uniform(-0.9, 3.0)) + rng.uniform(-5, 5)
        pert = build(d2)
        for name in base:
            # 'main'・'nobwlag'・'orth' は t の判断に t−1 以前の成分しか使わない＝T0+1 の判断まで同じでなければならない
            # 'lag0' は t の成分を使う＝T0 まで。'practical' は打ち切り m* ≤ T0 の判断まで
            lim = {'main': add(T0, 1), 'nobwlag': add(T0, 1), 'orth': add(T0, 1), 'lag0': T0}.get(name)
            for t, v in base[name].items():
                if name == 'practical':
                    if v['mstar'] > T0:
                        continue
                elif t > lim:
                    continue
                assert t in pert[name], (name, t)
                assert abs(pert[name][t]['S'] - v['S']) < 1e-9, ('先読み', name, T0, t)
        # わざと先読みさせた版が検査に落ちること（検査に効き目があること）
        leak = realtime(vectors(proxies(d2, 'exclude'), {'cefd': -1, 'nipo12': 0, 'ripoam': 12, 'pdnd': 12, 's': 0}))
        leak0 = realtime(vectors(proxies(d, 'exclude'), {'cefd': -1, 'nipo12': 0, 'ripoam': 12, 'pdnd': 12, 's': 0}))
        assert any(abs(leak[t]['S'] - leak0[t]['S']) > 1e-9 for t in leak0 if t == T0), '検査に効き目が無い'
        print(f'先読みの検査 T0={T0}: 通過（t より後の成分を乱数に替えても、各型の t までの信号は1つも変わらない。わざと先読みした版は変わる）')
    # 主成分の実装: 合成データで第1主成分の載荷が既知の向きに出るか
    rs = np.random.default_rng(1)
    f = rs.normal(size=400)
    true = np.array([-0.5, 0.5, 0.4, -0.4, 0.3])
    X = np.outer(f, true) + 0.3 * rs.normal(size=(400, 5))
    w, *_ = pc1(X)
    assert np.corrcoef(w, true)[0, 1] > 0.95, w
    print('主成分の実装: 合成データで既知の載荷の向きを再現（相関 > 0.95）')


# ───────────────────────── 形だけの取得 ─────────────────────────
def span(dct):
    ks = sorted(dct)
    return f'{ks[0]}..{ks[-1]} n={len(ks)}' if ks else 'empty'


def fetch_shapes():
    info = {}
    for name, (want, cols) in FRENCH_FILES.items():
        b = N.get(N.FR.format(name), name=f'fr_{name}.zip')
        sha = hashlib.sha256(b).hexdigest()
        if want is None:
            ff = N.ff_factors()
            info[name] = {'sha256': sha, 'mkt': span(ff['mkt']), 'rf': span(ff['rf'])}
        else:
            t = N.french_tables(name)[want]
            idx = {c: i for i, c in enumerate(t['cols'])}
            info[name] = {'sha256': sha, 'table': want}
            for c in cols:
                ser = {d: row[idx[c]] for d, row in t['data'].items() if row[idx[c]] is not None}
                miss = sum(1 for d, row in t['data'].items() if row[idx[c]] is None)
                info[name][c] = f'{span(ser)} missing={miss}'
    for c in JKP_COUNTRIES:
        info[f'jkp_{c}'] = {}
        m = N.jkp_mkt(c, 'vw_cap')
        info[f'jkp_{c}']['mkt_vw_cap'] = span(m)
        for ch, side in JKP_CHARS.items():
            p = N.jkp_portfolios(c, ch, 'vw_cap')
            info[f'jkp_{c}'][f'{ch}_pf{side}'] = span(p.get(side, {}))
    for e in ETFS:
        try:
            r = N.yahoo(e)
            info[f'yahoo_{e}'] = span(r)
        except Exception as ex:  # noqa
            info[f'yahoo_{e}'] = f'取得失敗 {ex}'
    return info


def main():
    if '--selftest' in sys.argv:
        selftest()
        return
    if '--fetch' in sys.argv:
        print(json.dumps(fetch_shapes(), ensure_ascii=False, indent=1))
        return
    d, sha = load_bw()
    d19, sha19 = load_bw(BW_2019_NAME)
    shapes = {k: span(v) for k, v in d.items()}
    rep = replication_check(d)
    sig = build(d)
    # 2019 年版（成分の版の違い）は 'main' だけ（列名が違うので読み替え: 2019版の 'SENT' は公開の素の指数）
    sig19 = {'main_2019': realtime(vectors(proxies(d19, 'exclude'), SPECS['main']))}
    rsha = regime_sha(sig)
    rsha19 = regime_sha(sig19)
    out = {'generated': datetime.date.today().isoformat(),
           'source': {'url': BW_URL, 'sha256_xlsx': sha, 'vintage': 'README『UPDATED: March, 2026』（GitHub BWInvestorSentimentIndex の 7a0165f・2026-04-21 の SENTIMENT.xlsx と全成分・SENT が一致）',
                      'vintage_2019_sha256': sha19},
           'specs': SPECS, 'theory_sign': THEORY_SIGN, 'min_window': MIN_WIN, 'macro_lag': MACRO_LAG,
           'regime_sha256': rsha, 'regime_sha256_2019': rsha19,
           'replication_check': rep,
           'signals': {k: {str(t): v for t, v in s.items()} for k, s in sig.items()},
           'signals_2019': {k: {str(t): v for t, v in s.items()} for k, s in sig19.items()}}
    os.makedirs(N.CACHE, exist_ok=True)
    tmp = OUT + '.tmp'
    json.dump(out, open(tmp, 'w'), ensure_ascii=False)
    os.replace(tmp, OUT)
    # 形だけを表示（信号の値・高い月の割合・切替えの回数は表示しない）
    print('xlsx sha256', sha)
    print('成分の期間', json.dumps({k: shapes[k] for k in ('pdnd', 'ripo', 'nipo', 'cefd', 's', 'SENT', 'SENT_ORTH')}, ensure_ascii=False))
    print('構成の検算（全期間の主成分 vs 公開の SENT・リターンは使わない）', json.dumps(rep, ensure_ascii=False))
    for k, s in sig.items():
        ks = sorted(s)
        print(f'信号 {k}: 判断の月 {ks[0]}..{ks[-1]}（{len(ks)} か月）')
    for k, s in sig19.items():
        ks = sorted(s)
        print(f'信号 {k}: 判断の月 {ks[0]}..{ks[-1]}（{len(ks)} か月）')
    print('regime_sha256', rsha)
    print('regime_sha256_2019', rsha19)
    print('→', OUT)


if __name__ == '__main__':
    main()
