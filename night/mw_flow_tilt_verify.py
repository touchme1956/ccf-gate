#!/usr/bin/env python3
"""night/mw_flow_tilt_verify.py — 角度 flow_tilt の反証の検証（読むだけ・門の判定には不使用）

対象: out/mw_flow_tilt.json の B 1本（X5_UScap_XUScountry_top3）。S・A は0本なので、B の上位2本＝B の1本だけ。
      追加で Z3（勢いの入金・C）も自前で作り直し、同じ出どころの先進国の相手 JD（JKP usa＋developed）を新設して測る。
方針: 取得だけ mw_common（get / jkp_mkt / ff_factors / french_tables）を使い、French の国別 .Dat の読み方・
      入金の道の作り方・超過と CAGR・Newey-West t・転がる窓・積立の比は自前で書き直す（研究役のコードは読まない形で）。

確かめること
 1. 研究役の数字（全期間・訓練・保有の超過と NW t・CAGR 差・転がる20年・20年積立・費用後の保有）を再現
 2. 相手: JKP world は上限なしの時価加重だが、1986〜95 の新興国データの汚れと 2007〜 の MSCI ACWI との差がある
    → 汚れの無い相手（French Developed＝時価加重の先進国・MSCI ACWI／World・同じ出どころの合成 BD）と、
      傾けだけの効き（入金を時価の重みで US・Ind_all へ入れて売らない道 N_dev との比）で測り直す
 3. 部分期間（1998-2000・2020-2021 を抜く／保有の前半・後半）、近い設定（上位2/4/5・窓10/15/30年・社数条件・DY の水準）、
    国を1つずつ抜く、費用の現実性（国別 ETF の報酬・二重の源泉税）、多重検定
"""
import sys, os, io, json, math, zipfile, statistics as S, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

OUT = os.path.join(M.BASE, 'out', 'mw_flow_tilt_verify.json')
START, END = 198601, 202512
TRAIN_END, HOLD_START = 200612, 200701
FR_ZIP = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{}.zip'
COUNTRY_FILES = {'gbr': 'UK', 'aut': 'Austria', 'aus': 'Austrlia', 'bel': 'Belgium', 'can': 'Canada', 'dnk': 'Denmark',
                 'fin': 'Finland', 'fra': 'France', 'deu': 'Germany', 'hkg': 'HongKong', 'irl': 'Ireland', 'ita': 'Italy',
                 'jpn': 'Japan', 'mys': 'Malaysia', 'nld': 'Nethrlnd', 'nzl': 'NewZland', 'nor': 'Norway', 'sgp': 'Singapor',
                 'esp': 'Spain', 'swe': 'Sweden', 'che': 'Swtzrlnd'}


# ───────────── 月の算術 ─────────────
def mshift(ym, k):
    n = (ym // 100) * 12 + (ym % 100 - 1) + k
    return (n // 12) * 100 + n % 12 + 1


def mrange(a, z):
    out = []
    while a <= z:
        out.append(a); a = mshift(a, 1)
    return out


# ───────────── French .Dat を自前で読む ─────────────
def read_dat(txt):
    """ブロック単位: 数字で始まる行の連なり＝1ブロック。直前の文字行（見出し）から通貨・条件・頻度を決める。
    → {(label, req, freq, n): {'cols': [...], 'rows': {date: [float|None]}}}"""
    blocks, hdr, cur = {}, [], None
    for line in txt.splitlines():
        s = line.strip()
        if not s:
            cur = None
            continue
        tok = s.split()
        if tok[0].isdigit() and len(tok[0]) in (4, 6):
            if cur is None:
                text = ' '.join(hdr).lower()
                label = 'USD' if 'dollar' in text else 'LOC' if 'local' in text else 'RAT' if ('ratio' in text or 'averages' in text) else '?'
                req = 'NR' if 'not req' in text else 'RQ'
                freq = 'M' if len(tok[0]) == 6 else 'A'
                cols = hdr[-1].split() if hdr else []
                n = sum(1 for k in blocks if k[:3] == (label, req, freq))
                cur = blocks[(label, req, freq, n)] = {'cols': cols, 'rows': {}}
                hdr = []
            vals = []
            for v in tok[1:]:
                try:
                    f = float(v)
                    vals.append(None if f <= -99.99 else f)
                except ValueError:
                    vals.append(None)
            cur['rows'][int(tok[0])] = vals
        else:
            if cur is not None:
                cur = None
            hdr.append(s)
    return blocks


def fr_file(zipname, fname):
    b = M.get(FR_ZIP.format(zipname), name=f'fr_{zipname}.zip', max_age_days=3650)
    return read_dat(zipfile.ZipFile(io.BytesIO(b)).read(fname).decode('latin-1'))


def first_col(block):
    return {d: v[0] / 100 for d, v in block['rows'].items() if v and v[0] is not None}


def country_data(zip_t, zip_x, fname):
    a, b = fr_file(zip_t, fname), fr_file(zip_x, fname)
    usd = first_col(a[('USD', 'NR', 'M', 0)])
    lt, lx = first_col(a[('LOC', 'NR', 'M', 0)]), first_col(b[('LOC', 'NR', 'M', 0)])
    div = {k: lt[k] - lx[k] for k in lt if k in lx}
    firms = None
    for k, blk in a.items():
        if k[0] == 'RAT' and k[1] == 'NR' and k[2] == 'A' and 'Firms' in blk['cols']:
            i = blk['cols'].index('Firms')
            firms = {y: v[i] for y, v in blk['rows'].items() if i < len(v) and v[i] is not None}
            break
    return usd, div, firms


# ───────────── 統計（自前） ─────────────
def nwt(x, L=12):
    n = len(x)
    m = sum(x) / n
    e = [v - m for v in x]
    s = sum(v * v for v in e) / n
    for l in range(1, L + 1):
        s += 2 * (1 - l / (L + 1)) * sum(e[i] * e[i - l] for i in range(l, n)) / n
    return m / math.sqrt(s / n) if s > 0 else float('nan')


def geo(vals):
    return math.exp(sum(math.log1p(v) for v in vals) * 12 / len(vals)) - 1


def ex(s, b, a=None, z=None, skip=None, L=12):
    ks = [k for k in sorted(s) if k in b and (a is None or k >= a) and (z is None or k <= z) and not (skip and skip(k))]
    if len(ks) < 24:
        return None
    d = [s[k] - b[k] for k in ks]
    return {'from': ks[0], 'to': ks[-1], 'n': len(ks), 'ex_ann': round(sum(d) / len(d) * 1200, 2), 't': round(nwt(d, L), 2),
            'cagr_diff': round((geo([s[k] for k in ks]) - geo([b[k] for k in ks])) * 100, 2)}


def roll_lump(s, b, years=20):
    ks = sorted(k for k in s if k in b)
    res = []
    y = ks[0] // 100
    while True:
        a, z = y * 100 + 7, (y + years) * 100 + 6
        if z > ks[-1]:
            break
        w = [k for k in ks if a <= k <= z]
        if len(w) >= years * 12 * 0.97:
            res.append((y, (geo([s[k] for k in w]) - geo([b[k] for k in w])) * 100))
        y += 1
    if not res:
        return None
    return {'windows': len(res), 'win_rate': round(sum(1 for _, v in res if v > 0) / len(res), 3),
            'median': round(sorted(v for _, v in res)[len(res) // 2], 2), 'worst': [res[min(range(len(res)), key=lambda i: res[i][1])][0], round(min(v for _, v in res), 2)]}


# ───────────── データ ─────────────
class D:
    pass


def load():
    d = D()
    ff = M.ff_factors()
    d.rf = ff['rf']
    d.frmkt = ff['mkt']
    d.jkp = {}
    for key, reg in (('US', 'usa'), ('XUS', 'world_ex_us'), ('W', 'world'), ('EM', 'emerging'), ('DEVX', 'developed')):
        e = M.jkp_mkt(reg, 'vw')
        d.jkp[key] = e
    d.usd = {k: {m: v + d.rf[m] for m, v in e.items() if m in d.rf} for k, e in d.jkp.items()}
    # 国（自前の読み方）
    d.c_usd, d.c_div, d.c_firms = {}, {}, {}
    for c, f in COUNTRY_FILES.items():
        u, dv, fm = country_data('F-F_International_Countries', 'F-F_International_Countries_Wout_Div', f + '.Dat')
        d.c_usd[c], d.c_div[c], d.c_firms[c] = u, dv, fm
    u, dv, _ = country_data('F-F_International_Indices', 'F-F_International_Indices_Wout_Div', 'Ind_all.Dat')
    d.ind_all, d.ind_all_div = u, dv
    # French Developed（時価加重の先進国・米国込み）
    for t, v in M.french_tables('Developed_3_Factors').items():
        if v['freq'] == 'monthly':
            i, j = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
            d.frdev = {k: (r[i] + r[j]) / 100 for k, r in v['data'].items() if r[i] is not None and r[j] is not None}
            break
    # 米国の配当（十分位の時価加重・研究役の30/40/30 とは別の分け方）
    tb = M.french_tables('Portfolios_Formed_on_ME')
    def pick(prefix):
        return next(v for t, v in tb.items() if t.lower().startswith(prefix) and v['freq'] == 'monthly')
    tb2 = M.french_tables('Portfolios_Formed_on_ME_Wout_Div')
    tot, exd = pick('average value weight'), next(v for t, v in tb2.items() if t.lower().startswith('average value weight') and v['freq'] == 'monthly')
    nf, sz = pick('number of firms'), pick('average firm size')
    dec = [c for c in tot['cols'] if c in ('Lo 10', 'Hi 10') or c.endswith('-Dec')]
    d.us_div = {}
    for m in tot['data']:
        if m not in exd['data'] or m not in nf['data'] or m not in sz['data']:
            continue
        W = A = B = 0.0
        ok = True
        for c in dec:
            n, a = nf['data'][m][nf['cols'].index(c)], sz['data'][m][sz['cols'].index(c)]
            r1, r0 = tot['data'][m][tot['cols'].index(c)], exd['data'][m][exd['cols'].index(c)]
            if None in (n, a, r1, r0):
                ok = False; break
            W += n * a; A += n * a * r1; B += n * a * r0
        if ok and W > 0:
            d.us_div[m] = (A - B) / W / 100
    # 円/ドル（月末・自前）
    csv = M.get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXJPUS', name='fred_DEXJPUS.csv', max_age_days=3650).decode()
    fx = {}
    for ln in csv.strip().splitlines()[1:]:
        dt, v = ln.split(',')
        if v in ('', '.'):
            continue
        k = int(dt[:4]) * 100 + int(dt[5:7])
        if k not in fx or dt > fx[k][0]:
            fx[k] = (dt, float(v))
    d.fx = {k: v for k, (_, v) in fx.items()}
    # MSCI（研究役が取ったキャッシュ・USD 水準）
    d.msci = {}
    for code, var in (('892400', 'GRTR'), ('892400', 'NETR'), ('990100', 'GRTR'), ('990100', 'NETR')):
        p = os.path.join(M.CACHE, f'mwft_msci_{code}_{var}_USD.json')
        if os.path.exists(p):
            L = {x['calc_date'] // 100: x['level_eod'] for x in json.load(open(p))['indexes']['INDEX_LEVELS']}
            ks = sorted(L)
            d.msci[(code, var)] = {k: L[k] / L[q] - 1 for q, k in zip(ks, ks[1:]) if mshift(q, 1) == k}
    return d


def jpy(d, r, m):
    a, b = d.fx.get(m), d.fx.get(mshift(m, -1))
    if r is None or a is None or b is None:
        return None
    return (1 + r) * (a / b) - 1


# ───────────── 信号・米国の重み ─────────────
def trailing_dy(div):
    out = {}
    for t in div:
        v = [div.get(mshift(t, -k)) for k in range(12)]
        if None not in v:
            out[t] = sum(v)
    return out


def rel_of(dy, win=240, minn=120):
    out = {}
    for t in dy:
        h = [dy[mshift(t, -k)] for k in range(win) if mshift(t, -k) in dy]
        if len(h) >= minn:
            md = S.median(h)
            if md > 0:
                out[t] = dy[t] / md
    return out


def us_weight(d):
    """world − xus = w·(usa − xus) を月 m−12〜m−1 で原点回帰 → 月 m の w"""
    U, X, W = d.jkp['US'], d.jkp['XUS'], d.jkp['W']
    ks = sorted(set(U) & set(X) & set(W))
    w = {}
    for i in range(12, len(ks)):
        win = ks[i - 12:i]
        a = [U[k] - X[k] for k in win]; b = [W[k] - X[k] for k in win]
        den = sum(x * x for x in a)
        if den > 0:
            w[ks[i]] = sum(x * y for x, y in zip(a, b)) / den
    f = w[min(w)]
    for k in ks:
        w.setdefault(k, f)
    return w


# ───────────── X5 の入金の向け先 ─────────────
def build_alloc(d, wus, K=3, win=240, minn=120, firms_min=20, level=False, drop=(), countries=None):
    cs = [c for c in (countries or COUNTRY_FILES) if c not in drop]
    sig = {}
    for c in cs:
        dy = trailing_dy(d.c_div[c])
        sig[c] = dy if level else rel_of(dy, win, minn)
    alloc = {}
    for t in mrange(mshift(START, -1), mshift(END, -1)):
        w = wus[mshift(t, 1)]
        Y = t // 100
        el = [c for c in cs if (d.c_firms[c].get(Y) or 0) >= firms_min and t in sig[c] and mshift(t, 1) in d.c_usd[c]]
        el.sort(key=lambda c: (-sig[c][t], c))
        if len(el) >= K:
            a = {'US': w}
            for c in el[:K]:
                a['c:' + c] = (1 - w) / K
        else:
            a = {'US': w, 'XUS': 1 - w}
        alloc[t] = a
    return alloc


def neutral_alloc(wus, xleg='XUS'):
    return {t: {'US': wus[mshift(t, 1)], xleg: 1 - wus[mshift(t, 1)]} for t in mrange(mshift(START, -1), mshift(END, -1))}


# ───────────── 器のリターン（円・gross/net） ─────────────
def make_ret(d, wus, net=False, fee_c=0.50, wh_c=0.15, us_src='JKP'):
    FEE = {'US': 0.0937, 'XUS': 0.11, 'W': 0.0578, 'IND': 0.11, 'SP': 0.0937}
    WH = {'US': 0.10, 'XUS': 0.13, 'IND': 0.13, 'SP': 0.10}
    def f(b, m):
        if b.startswith('c:'):
            r = d.c_usd[b[2:]].get(m)
            if r is None:
                return None
            if net:
                dv = d.c_div[b[2:]].get(m)
                if dv is None:
                    return None
                r = r - fee_c / 1200 - wh_c * dv
            return jpy(d, r, m)
        if b == 'US':
            r = d.usd['US'].get(m) if us_src == 'JKP' else d.frmkt.get(m)
        elif b == 'SP':
            r = d.frmkt.get(m)
        elif b == 'IND':
            r = d.ind_all.get(m)
        else:
            r = d.usd[b].get(m)
        if r is None:
            return None
        if net:
            r -= FEE.get(b, 0.0) / 1200
            if b in ('US', 'SP'):
                dv = d.us_div.get(m)
                if dv is None:
                    return None
                r -= WH[b] * dv
            elif b in ('XUS', 'IND'):
                dv = d.ind_all_div.get(m)
                if dv is None:
                    return None
                r -= WH[b] * dv
            elif b == 'W':
                du, dx, w = d.us_div.get(m), d.ind_all_div.get(m), wus.get(m)
                if None in (du, dx, w):
                    return None
                r -= w * 0.10 * du + (1 - w) * 0.13 * dx
        return jpy(d, r, m)
    return f


def path(alloc, rf, start, end, fallback='XUS'):
    """月初に入金→持ち分に月のリターン。時間加重の月次 {m}。持っている器のリターンが無ければ fallback へ移す"""
    H, V, out = {}, 0.0, {}
    for m in mrange(start, end):
        for b, x in alloc[mshift(m, -1)].items():
            H[b] = H.get(b, 0.0) + x
        base = V + 1.0
        for b in list(H):
            if b != fallback and rf(b, m) is None:
                H[fallback] = H.get(fallback, 0.0) + H.pop(b)
        V = 0.0
        for b in H:
            r = rf(b, m)
            if r is None:
                raise RuntimeError(f'欠け {b} {m}')
            H[b] *= 1 + r
            V += H[b]
        out[m] = V / base - 1
    return out, H


def dca_final(alloc, rf, start, n, fallback='XUS'):
    H = {}
    for m in mrange(start, mshift(start, n - 1)):
        for b, x in alloc[mshift(m, -1)].items():
            H[b] = H.get(b, 0.0) + x
        for b in list(H):
            if b != fallback and rf(b, m) is None:
                H[fallback] = H.get(fallback, 0.0) + H.pop(b)
        for b in H:
            H[b] *= 1 + rf(b, m)
    return sum(H.values())


def dca_cmp(allocA, allocB, rf, first=START, last_end=END, years=20, step=12, rfB=None):
    n, res, s = years * 12, [], first
    while mshift(s, n - 1) <= last_end:
        a = dca_final(allocA, rf, s, n)
        b = dca_final(allocB, rfB or rf, s, n)
        res.append((s, a / b))
        s = mshift(s, step)
    if not res:
        return None
    v = sorted(x for _, x in res)
    return {'windows': len(res), 'win_rate': round(sum(1 for x in v if x > 1) / len(v), 3), 'median': round(v[len(v) // 2], 4),
            'worst': [min(res, key=lambda x: x[1])[0], round(min(v), 4)], 'best': [max(res, key=lambda x: x[1])[0], round(max(v), 4)]}


def series(rf, b, a=START, z=END):
    out = {}
    for m in mrange(a, z):
        r = rf(b, m)
        if r is not None:
            out[m] = r
    return out


def ann(d_):
    """月次 → 暦年のリターン"""
    y = {}
    for k, v in d_.items():
        y[k // 100] = y.get(k // 100, 1.0) * (1 + v)
    return {k: round((v - 1) * 100, 1) for k, v in y.items()}


# ───────────── 同じ出どころ（JKP）の先進国の相手 ─────────────
_JD_R2 = []


def jd_benchmark(d):
    """world = a·usa + b·dev + c·em（月 m−12〜m−1・切片なし）→ w_d(m) = a/(a+b)。JD(m) = w_d·usa + (1−w_d)·dev（米ドル・総リターン）"""
    import numpy as np
    U, DV, E, W = d.usd['US'], d.usd['DEVX'], d.usd['EM'], d.usd['W']
    ks = sorted(set(U) & set(DV) & set(W))
    wd = {}
    for i in range(12, len(ks)):
        win = ks[i - 12:i]
        use_em = all(k in E for k in win)
        X = np.array([[U[k], DV[k]] + ([E[k]] if use_em else []) for k in win])
        y = np.array([W[k] for k in win])
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        fit = X @ coef
        ss = float(((y - y.mean()) ** 2).sum())
        if ss > 0:
            _JD_R2.append(1 - float(((y - fit) ** 2).sum()) / ss)
        a, b = float(coef[0]), float(coef[1])
        if a > 0 and b > 0:
            wd[ks[i]] = a / (a + b)
    f = wd[min(wd)]
    last = f
    out_w = {}
    for k in ks:
        if k in wd:
            last = wd[k]
        out_w[k] = wd.get(k, last if k > min(wd) else f)
    jd = {k: out_w[k] * U[k] + (1 - out_w[k]) * DV[k] for k in ks}
    return jd, out_w


# ───────────── Z3（勢いの入金）を自前で ─────────────
def z3_check(d, wus, wjd, G, N, MWn):
    SPu, INu = d.frmkt, d.ind_all

    def mom(ser, t, L, skip):
        v = 1.0
        for k in range(skip, L):
            r = ser.get(mshift(t, -k))
            if r is None:
                return None
            v *= 1 + r
        return v - 1

    def alloc_mom(L=12, skip=1, start=START):
        al = {}
        for t in mrange(mshift(start, -1), mshift(END, -1)):
            a, b = mom(SPu, t, L, skip), mom(INu, t, L, skip)
            al[t] = {'SP': 1.0} if (a is None or b is None or a >= b) else {'IND': 1.0}
        return al

    # French Developed から米国の重み（(FD−IND) = w·(SP−IND)、月 m−12〜m−1）
    wfd = {}
    for m in mrange(199007, END):
        win = [mshift(m, -k) for k in range(1, 13)]
        if all(k in d.frdev and k in SPu and k in INu for k in win):
            a = [SPu[k] - INu[k] for k in win]; b = [d.frdev[k] - INu[k] for k in win]
            wfd[m] = sum(x * y for x, y in zip(a, b)) / sum(x * x for x in a)

    def bench(rf, wmap, a, z):
        return {m: wmap[m] * rf('SP', m) + (1 - wmap[m]) * rf('IND', m) for m in mrange(a, z)
                if m in wmap and rf('SP', m) is not None and rf('IND', m) is not None}
    B1g, B1n = bench(G, wjd, START, END), bench(N, wjd, START, END)
    B2g, B2n = bench(G, wfd, 199107, END), bench(N, wfd, 199107, END)
    SPg, SPn = series(G, 'SP'), series(N, 'SP')
    out = {'what': 'US=French Mkt（CRSP）・XD=French Ind_all（米国外先進国）。12-1 の勢い（米ドル・月 t−11〜t−1）が高い方へ月 t+1 の入金を全部。'
                   '相手 BD1 = w_JD·US + (1−w_JD)·XD（JKP から逆算した先進国の米国の重み・1986〜）、BD2 = w_FD·US + (1−w_FD)·XD（French Developed から・1991-07〜＝研究役の BD と同じ作り）'}
    al = alloc_mom()
    p86g, _ = path(al, G, START, END)
    p86n, _ = path(al, N, START, END)
    p91g, _ = path(al, G, 199107, END)
    p91n, _ = path(al, N, 199107, END)
    f07g, _ = path(al, G, HOLD_START, END)
    f07n, _ = path(al, N, HOLD_START, END)
    us_share = lambda a_, z_: round(sum(1 for t in mrange(a_, z_) if 'SP' in al[t]) / len(mrange(a_, z_)), 3)
    out['share_of_months_to_US'] = {'1986_2006': us_share(198512, 200611), '2007_2025': us_share(200612, 202511)}
    out['vs_BD2_1991'] = {'train_1991_07_2006': ex(p91g, B2g, z=TRAIN_END), 'hold_path': ex(p91g, B2g, a=HOLD_START),
                          'hold_fresh2007': ex(f07g, B2g, a=HOLD_START), 'net_hold_path': ex(p91n, B2n, a=HOLD_START),
                          'net_fresh2007': ex(f07n, B2n, a=HOLD_START),
                          'hold_2007_2016': ex(p91g, B2g, a=200701, z=201606), 'hold_2016_2025': ex(p91g, B2g, a=201607)}
    out['vs_BD1_1986'] = {'train_1986_2006': ex(p86g, B1g, z=TRAIN_END), 'train_1986_1990': ex(p86g, B1g, z=199012),
                          'hold_path': ex(p86g, B1g, a=HOLD_START), 'net_hold_path': ex(p86n, B1n, a=HOLD_START),
                          'hold_fresh2007': ex(f07g, B1g, a=HOLD_START), 'net_fresh2007': ex(f07n, B1n, a=HOLD_START)}
    MWb = {m: v for m, v in MWn.items()}
    out['vs_US_market_net'] = {'fresh2007': ex(f07n, SPn, a=HOLD_START), 'path_1991_hold': ex(p91n, SPn, a=HOLD_START)}
    out['vs_MSCI_World_net_fresh2007'] = ex(f07n, MWb, a=HOLD_START) if MWb else None
    neigh = {}
    for L, sk in ((12, 1), (12, 0), (9, 1), (6, 1), (6, 0), (3, 0)):
        a2 = alloc_mom(L, sk)
        q86, _ = path(a2, G, START, END)
        q91, _ = path(a2, G, 199107, END)
        q07, _ = path(a2, G, HOLD_START, END)
        t1, t2 = ex(q86, B1g, z=TRAIN_END), ex(q91, B2g, z=TRAIN_END)
        h1, h2 = ex(q91, B2g, a=HOLD_START), ex(q07, B2g, a=HOLD_START)
        neigh[f'{L}-{sk}'] = {'train86_ex': t1['ex_ann'], 'train86_t': t1['t'], 'train91_ex': t2['ex_ann'], 'train91_t': t2['t'],
                              'hold_ex_min': min(h1['ex_ann'], h2['ex_ann']), 'hold_t_min': min(h1['t'], h2['t'])}
    out['neighbors_lookback'] = neigh
    c1 = [out['vs_BD2_1991']['train_1991_07_2006'], out['vs_BD1_1986']['train_1986_2006']]
    out['C1_pass_any_train_window'] = any(x['ex_ann'] > 0 and x['t'] >= 2.0 for x in c1)
    return out


# ───────────── 本体 ─────────────
def main():
    d = load()
    wus = us_weight(d)
    G, N = make_ret(d, wus, False), make_ret(d, wus, True)
    X5 = build_alloc(d, wus)
    Wg, Wn = series(G, 'W'), series(N, 'W')
    res = {'candidate': 'X5_UScap_XUScountry_top3'}

    # 1) 再現
    twg, _ = path(X5, G, START, END)
    twn, Hn = path(X5, N, START, END)
    fg, _ = path(X5, G, HOLD_START, END)
    fn, _ = path(X5, N, HOLD_START, END)
    rep = {
        'gross_full': ex(twg, Wg), 'gross_train': ex(twg, Wg, z=TRAIN_END), 'gross_hold': ex(twg, Wg, a=HOLD_START),
        'gross_recent': ex(twg, Wg, a=201307),
        'net_hold': ex(twn, Wn, a=HOLD_START), 'net_full': ex(twn, Wn),
        'fresh2007_gross': ex(fg, Wg, a=HOLD_START), 'fresh2007_net': ex(fn, Wn, a=HOLD_START),
        'roll20_lump_net': roll_lump(twn, Wn), 'dca20_vs_W_net': dca_cmp(X5, {t: {'W': 1.0} for t in X5}, N),
    }
    tot = sum(Hn.values())
    rep['final_holding_top'] = {b: round(v / tot, 3) for b, v in sorted(Hn.items(), key=lambda x: -x[1])[:6]}
    res['reproduction_vs_JKP_world'] = rep
    claimed = {'full_ex': 2.48, 'full_t': 2.59, 'train_ex': 4.25, 'train_t': 2.57, 'hold_ex': 0.54, 'hold_t': 0.97, 'hold_cagr_diff': 0.35,
               'recent_ex': 0.11, 'net_cost_hold_ex': 0.41, 'roll20_win': 1, 'dca20_win': 1, 'dca20_median': 1.0729}
    res['claimed'] = claimed
    print('再現', json.dumps(rep, ensure_ascii=False))

    # 2) 相手のデータの点検
    chk = {}
    chk['JKP_emerging_annual_1986_1996_pct'] = {y: v for y, v in ann({k: v for k, v in d.usd['EM'].items() if 198601 <= k <= 199612}).items()}
    chk['JKP_world_ex_us_annual_1987_1990_pct'] = {y: v for y, v in ann({k: v for k, v in d.usd['XUS'].items() if 198701 <= k <= 199012}).items()}
    chk['French_Ind_all_annual_1987_1990_pct'] = {y: v for y, v in ann({k: v for k, v in d.ind_all.items() if 198701 <= k <= 199012}).items()}
    a_ = [d.usd['W'][k] for k in mrange(200701, 202512)]
    acwi = d.msci.get(('892400', 'GRTR'), {})
    b_ = [acwi[k] for k in mrange(200701, 202512) if k in acwi]
    wld = d.msci.get(('990100', 'GRTR'), {})
    chk['cagr_2007_2025_usd_pct'] = {'JKP_world_vw': round(geo(a_) * 100, 2), 'MSCI_ACWI_gross': round(geo(b_) * 100, 2) if len(b_) == len(a_) else None,
                                     'MSCI_World_gross': round(geo([wld[k] for k in mrange(200701, 202512)]) * 100, 2) if wld else None,
                                     'French_Developed': round(geo([d.frdev[k] for k in mrange(200701, 202512)]) * 100, 2),
                                     'French_US_Mkt': round(geo([d.frmkt[k] for k in mrange(200701, 202512)]) * 100, 2)}
    chk['cagr_1986_2006_usd_pct'] = {'JKP_world_vw': round(geo([d.usd['W'][k] for k in mrange(198601, 200612)]) * 100, 2),
                                     'JKP_world_ex_us': round(geo([d.usd['XUS'][k] for k in mrange(198601, 200612)]) * 100, 2),
                                     'French_Ind_all': round(geo([d.ind_all[k] for k in mrange(198601, 200612)]) * 100, 2),
                                     'JKP_usa': round(geo([d.usd['US'][k] for k in mrange(198601, 200612)]) * 100, 2),
                                     'French_US_Mkt': round(geo([d.frmkt[k] for k in mrange(198601, 200612)]) * 100, 2)}
    chk['w_us_samples'] = {k: round(wus[k], 3) for k in (198601, 198712, 198912, 199512, 200012, 200701, 201512, 202512)}
    res['benchmark_data_check'] = chk
    print('相手の点検', json.dumps(chk, ensure_ascii=False))

    # 3) 汚れの無い相手
    clean = {}
    # 3a) BD: w·US + (1−w)·French Ind_all（同じ出どころ・月次で時価の重み）
    def bd(rf):
        return {m: wus[m] * rf('US', m) + (1 - wus[m]) * rf('IND', m) for m in mrange(START, END) if rf('US', m) is not None and rf('IND', m) is not None}
    BDg, BDn = bd(G), bd(N)
    clean['vs_BD_synthetic'] = {'gross_full': ex(twg, BDg), 'gross_train': ex(twg, BDg, z=TRAIN_END), 'gross_hold': ex(twg, BDg, a=HOLD_START),
                                'net_hold': ex(twn, BDn, a=HOLD_START), 'fresh2007_net': ex(fn, BDn, a=HOLD_START),
                                'roll20_lump_net': roll_lump(twn, BDn)}
    # 3b) French Developed（1990-07〜・時価加重・米国込み）＝X5 の器の範囲（先進国のみ）と同じ
    FD = {m: jpy(d, d.frdev[m], m) for m in mrange(199007, END) if m in d.frdev}
    FDn = {m: jpy(d, d.frdev[m] - 0.099 / 1200 - (wus[m] * 0.10 * d.us_div[m] + (1 - wus[m]) * 0.13 * d.ind_all_div[m]), m)
           for m in mrange(199007, END) if m in d.frdev and m in d.us_div and m in d.ind_all_div}
    clean['vs_French_Developed'] = {'gross_1990_07_full': ex(twg, FD), 'gross_train_1990_07_2006': ex(twg, FD, z=TRAIN_END),
                                    'gross_hold': ex(twg, FD, a=HOLD_START), 'net_hold': ex(twn, FDn, a=HOLD_START),
                                    'fresh2007_net': ex(fn, FDn, a=HOLD_START)}
    # 3c) MSCI ACWI / World（NETR・円・信託報酬）
    for code, lab, fee in (('892400', 'MSCI_ACWI', 0.0578), ('990100', 'MSCI_World', 0.099)):
        nr = d.msci.get((code, 'NETR'))
        if nr:
            B = {m: jpy(d, nr[m] - fee / 1200, m) for m in mrange(200101, END) if m in nr}
            clean[f'vs_{lab}_net'] = {'path_hold': ex(twn, B, a=HOLD_START), 'fresh2007': ex(fn, B, a=HOLD_START),
                                      'path_2001_2025': ex(twn, B, a=200101)}
    # 3d) 傾けだけの効き: 入金を時価の重みで US と Ind_all（先進国の米国外）へ入れて売らない道 N_dev との比
    Ndev = neutral_alloc(wus, 'IND')
    nd_g, _ = path(Ndev, G, START, END)
    nd_n, _ = path(Ndev, N, START, END)
    ndf_n, _ = path(Ndev, N, HOLD_START, END)
    clean['vs_neutral_flow_dev'] = {'gross_full': ex(twg, nd_g), 'gross_train': ex(twg, nd_g, z=TRAIN_END), 'gross_hold': ex(twg, nd_g, a=HOLD_START),
                                    'net_hold': ex(twn, nd_n, a=HOLD_START), 'fresh2007_net': ex(fn, ndf_n, a=HOLD_START),
                                    'dca20_net': dca_cmp(X5, Ndev, N), 'dca15_net_step12': dca_cmp(X5, Ndev, N, years=15)}
    Nxus = neutral_alloc(wus, 'XUS')
    clean['neutral_flow_XUS_vs_W'] = {'gross_full': ex(path(Nxus, G, START, END)[0], Wg), 'dca20_net': dca_cmp(Nxus, {t: {'W': 1.0} for t in Nxus}, N)}
    clean['neutral_flow_dev_vs_W'] = {'gross_full': ex(nd_g, Wg), 'gross_train': ex(nd_g, Wg, z=TRAIN_END), 'gross_hold': ex(nd_g, Wg, a=HOLD_START),
                                      'dca20_net': dca_cmp(Ndev, {t: {'W': 1.0} for t in Ndev}, N)}
    # 3e) S&P500 型（French Mkt）
    SPn = series(N, 'SP')
    clean['vs_SP500_net'] = {'path_full': ex(twn, SPn), 'path_hold': ex(twn, SPn, a=HOLD_START), 'fresh2007': ex(fn, SPn, a=HOLD_START),
                             'dca20': dca_cmp(X5, {t: {'SP': 1.0} for t in X5}, N)}
    # 3f) MSCI World（gross・円）を近い設定の比較にも使う＋積立（2001〜・10年と15年・毎年起点）
    mg, mn = d.msci.get(('990100', 'GRTR'), {}), d.msci.get(('990100', 'NETR'), {})
    MWg = {m: jpy(d, mg[m], m) for m in mrange(200101, END) if m in mg}
    MWn = {m: jpy(d, mn[m] - 0.099 / 1200, m) for m in mrange(200101, END) if m in mn}
    def rf_mw(b, m):
        return MWn.get(m)
    X5_01 = {t: a for t, a in X5.items() if t >= 200012}
    mwalloc = {t: {'MW': 1.0} for t in X5_01}
    clean['dca_vs_MSCI_World_net'] = {f'{y}y': dca_cmp(X5_01, mwalloc, N, first=200101, years=y, step=12, rfB=lambda b, m: MWn.get(m)) for y in (10, 15)}
    FDa = {t: {'FD': 1.0} for t in X5 if t >= 199006}
    X5_90 = {t: a for t, a in X5.items() if t >= 199006}
    clean['dca20_vs_French_Developed_net'] = dca_cmp(X5_90, FDa, N, first=199007, years=20, step=12, rfB=lambda b, m: FDn.get(m))
    # 3g) JKP の米国の重みは実物の時価の重みより低いか: MSCI World ≈ w·French Mkt + (1−w)·French Ind_all を12か月で当てはめる
    def implied_w(Bser, m):
        win = [mshift(m, -k) for k in range(1, 13)]
        if not all(k in Bser and k in d.frmkt and k in d.ind_all for k in win):
            return None
        a = [d.frmkt[k] - d.ind_all[k] for k in win]; b = [Bser[k] - d.ind_all[k] for k in win]
        return round(sum(x * y for x, y in zip(a, b)) / sum(x * x for x in a), 3)
    clean['us_weight_check'] = {str(m): {'JKP_world_w_used': round(wus[m], 3), 'MSCI_World_implied': implied_w(mg, m),
                                          'French_Developed_implied': implied_w(d.frdev, m)} for m in (200201, 200701, 201201, 201601, 202001, 202501, 202512)}
    res['clean_benchmarks'] = clean
    print('汚れの無い相手', json.dumps(clean, ensure_ascii=False))

    # 4) 部分期間（BD を主の汚れの無い相手・JKP W も併記）
    def skip_bubble(k):
        return 199801 <= k <= 200012 or 202001 <= k <= 202112
    sub = {}
    for lab, B, s_, f_ in (('W', Wg, twg, fg), ('BD', BDg, twg, fg)):
        sub[lab] = {'full_drop_1998_2000_2020_2021': ex(s_, B, skip=skip_bubble),
                    'train_drop_1998_2000': ex(s_, B, z=TRAIN_END, skip=skip_bubble),
                    'train_1986_1990': ex(s_, B, a=198601, z=199012), 'train_1991_2006': ex(s_, B, a=199101, z=TRAIN_END),
                    'hold_2007_2016_path': ex(s_, B, a=200701, z=201606), 'hold_2016_2025_path': ex(s_, B, a=201607, z=END),
                    'fresh2007_2007_2016': ex(f_, B, a=200701, z=201606), 'fresh2007_2016_2025': ex(f_, B, a=201607, z=END)}
    res['subperiods_gross'] = sub
    print('部分期間', json.dumps(sub, ensure_ascii=False))

    # 5) 近い設定（gross・JKP W と BD の両方・訓練・保有＝2本の道の小さい方）
    def summarize(alloc):
        a_g, _ = path(alloc, G, START, END)
        a_n, _ = path(alloc, N, START, END)
        f_g, _ = path(alloc, G, HOLD_START, END)
        f_n, _ = path(alloc, N, HOLD_START, END)
        o = {}
        for lab, Bg, Bn in (('W', Wg, Wn), ('BD', BDg, BDn), ('FD', FD, FDn), ('MSCIW', MWg, MWn)):
            tr, h1, h2 = ex(a_g, Bg, z=TRAIN_END), ex(a_g, Bg, a=HOLD_START), ex(f_g, Bg, a=HOLD_START)
            n1, n2 = ex(a_n, Bn, a=HOLD_START), ex(f_n, Bn, a=HOLD_START)
            fu = ex(a_g, Bg)
            o[lab] = {'train_ex': tr['ex_ann'] if tr else None, 'train_t': tr['t'] if tr else None, 'full_t': fu['t'] if fu else None,
                      'hold_ex_min': min(h1['ex_ann'], h2['ex_ann']), 'hold_t_min': min(h1['t'], h2['t']),
                      'hold_cagr_min': min(h1['cagr_diff'], h2['cagr_diff']), 'net_hold_ex_min': min(n1['ex_ann'], n2['ex_ann']),
                      'net_hold_cagr_min': min(n1['cagr_diff'], n2['cagr_diff'])}
            if lab == 'MSCIW':  # MSCI は 2001-01 から＝訓練は6年しか無く C1（最低15年）を裁けない
                o[lab]['train_note'] = '2001-01〜2006-12 の6年だけ（C1 には使えない）'
                o[lab]['C1'] = None
            else:
                o[lab]['C1'] = bool(tr and tr['ex_ann'] > 0 and tr['t'] >= 2.0) if tr else None
            o[lab]['C2'] = o[lab]['hold_ex_min'] > 0 and o[lab]['hold_cagr_min'] > 0
            o[lab]['C6'] = o[lab]['net_hold_ex_min'] > 0 and o[lab]['net_hold_cagr_min'] > 0
            o[lab]['B_or_better_possible'] = bool(o[lab]['C2'] and o[lab]['C6'] and o[lab]['C1'] is not False)
        return o
    neigh = {}
    for lab, kw in (('K2', {'K': 2}), ('K3_base', {}), ('K4', {'K': 4}), ('K5', {'K': 5}), ('K1', {'K': 1}),
                    ('win120', {'win': 120, 'minn': 60}), ('win180', {'win': 180, 'minn': 90}), ('win360', {'win': 360, 'minn': 120}),
                    ('firms10', {'firms_min': 10}), ('firms50', {'firms_min': 50}), ('DY_level_top3', {'level': True})):
        neigh[lab] = summarize(build_alloc(d, wus, **kw))
        print('近い設定', lab, json.dumps(neigh[lab], ensure_ascii=False))
    res['neighbors'] = neigh

    # 6) 国を1つずつ抜く（選ばれた月の多い上位8か国）
    cnt = {}
    for t, a in X5.items():
        for b in a:
            if b.startswith('c:'):
                cnt[b[2:]] = cnt.get(b[2:], 0) + 1
    res['country_months_chosen'] = dict(sorted(cnt.items(), key=lambda x: -x[1]))
    loo = {}
    for c in list(res['country_months_chosen'])[:8]:
        loo['drop_' + c] = summarize(build_alloc(d, wus, drop=(c,)))
        print('国を抜く', c, json.dumps(loo['drop_' + c], ensure_ascii=False))
    res['leave_one_country_out'] = loo

    # 7) 費用の現実性（国別 ETF の報酬 0.85%＝1996年の WEBS 前後・二重の源泉税 23.5%＝国の源泉15% と米国籍 ETF の分配への米国10%）
    cost = {}
    for lab, fc, wc in (('fee0.50_wh15_base', 0.50, 0.15), ('fee0.50_wh23.5', 0.50, 0.235), ('fee0.85_wh23.5', 0.85, 0.235), ('fee0.85_wh15', 0.85, 0.15)):
        Nx = make_ret(d, wus, True, fee_c=fc, wh_c=wc)
        pn, _ = path(X5, Nx, START, END)
        pf, _ = path(X5, Nx, HOLD_START, END)
        cost[lab] = {'vs_W_path_hold': ex(pn, Wn, a=HOLD_START), 'vs_W_fresh2007': ex(pf, Wn, a=HOLD_START),
                     'vs_BD_fresh2007': ex(pf, BDn, a=HOLD_START), 'dca20_vs_W': dca_cmp(X5, {t: {'W': 1.0} for t in X5}, Nx, rfB=N)}
    res['cost_realism'] = cost
    print('費用', json.dumps(cost, ensure_ascii=False))

    # 8) 米国の脚を French Mkt（CRSP・S&P500 に近い）に替えても同じか（器の出どころの感応度）
    Gf, Nf = make_ret(d, wus, False, us_src='FR'), make_ret(d, wus, True, us_src='FR')
    pg, _ = path(X5, Gf, START, END)
    ff_, _ = path(X5, Gf, HOLD_START, END)
    res['us_leg_french_mkt'] = {'vs_W_train': ex(pg, Wg, z=TRAIN_END), 'vs_W_hold': ex(pg, Wg, a=HOLD_START), 'vs_W_fresh2007': ex(ff_, Wg, a=HOLD_START)}

    # 8b) 同じ出どころ（JKP）の先進国の相手 JD を 1986 から作る（研究役は作っていない相手）
    #     world = a·usa + b·developed(米国外) + c·emerging を月 m−12〜m−1 で当てはめ、w_d = a/(a+b) → JD = w_d·usa + (1−w_d)·developed
    jd, wjd = jd_benchmark(d)
    JDg = {m: jpy(d, jd[m], m) for m in mrange(START, END) if m in jd}
    JDn = {m: jpy(d, jd[m] - 0.099 / 1200 - (wjd[m] * 0.10 * d.us_div[m] + (1 - wjd[m]) * 0.13 * d.ind_all_div[m]), m)
           for m in mrange(START, END) if m in jd and m in d.us_div and m in d.ind_all_div}
    jdx = {'what': 'JKP の usa と developed（米国外先進国・JKP では米国を含まない）を、JKP world から逆算した時価の重みで合わせた先進国の時価加重（1986〜・汚れた新興国を持たない）',
           'w_d_samples': {str(k): round(wjd[k], 3) for k in (198601, 198712, 198912, 199512, 200012, 200701, 201512, 202512) if k in wjd},
           'fit_r2_median': round(S.median(_JD_R2), 5) if _JD_R2 else None,
           'cagr_1986_2006_usd': {'JKP_developed_exUS': round(geo([d.usd['DEVX'][k] for k in mrange(198601, 200612)]) * 100, 2),
                                  'French_Ind_all': round(geo([d.ind_all[k] for k in mrange(198601, 200612)]) * 100, 2),
                                  'JD': round(geo([jd[k] for k in mrange(198601, 200612)]) * 100, 2),
                                  'JKP_world': round(geo([d.usd['W'][k] for k in mrange(198601, 200612)]) * 100, 2)},
           'cagr_2007_2025_usd': {'JD': round(geo([jd[k] for k in mrange(200701, 202512)]) * 100, 2),
                                  'French_Developed': round(geo([d.frdev[k] for k in mrange(200701, 202512)]) * 100, 2)},
           'X5_vs_JD': {'gross_full': ex(twg, JDg), 'gross_train': ex(twg, JDg, z=TRAIN_END), 'gross_hold': ex(twg, JDg, a=HOLD_START),
                        'net_hold': ex(twn, JDn, a=HOLD_START), 'fresh2007_gross': ex(fg, JDg, a=HOLD_START), 'fresh2007_net': ex(fn, JDn, a=HOLD_START),
                        'hold_2007_2016': ex(twg, JDg, a=200701, z=201606), 'hold_2016_2025': ex(twg, JDg, a=201607),
                        'train_1986_1990': ex(twg, JDg, z=199012), 'train_1991_2006': ex(twg, JDg, a=199101, z=TRAIN_END),
                        'roll20_lump_net': roll_lump(twn, JDn),
                        'dca20_net': dca_cmp(X5, {t: {'JD': 1.0} for t in X5}, N, rfB=lambda b, m: JDn.get(m))}}
    # 当てはめの重みは 1988〜1992 に不安定（JKP の新興国の汚れが回帰に入る・例 1989-12 0.06／1992-04 0.59）→ 過去12か月の中央値でならした版も
    wjs = {}
    ksw = sorted(wjd)
    for i, k in enumerate(ksw):
        wjs[k] = S.median([wjd[q] for q in ksw[max(0, i - 11):i + 1]])
    jds = {k: wjs[k] * d.usd['US'][k] + (1 - wjs[k]) * d.usd['DEVX'][k] for k in ksw if k in d.usd['US'] and k in d.usd['DEVX']}
    JDSg = {m: jpy(d, jds[m], m) for m in mrange(START, END) if m in jds}
    jdx['smoothed_w_12m_median'] = {'w_samples': {str(k): round(wjs[k], 3) for k in (198912, 199012, 199204, 200701, 202512)},
                                    'X5_train': ex(twg, JDSg, z=TRAIN_END), 'X5_train_1991_2006': ex(twg, JDSg, a=199101, z=TRAIN_END),
                                    'X5_hold': ex(twg, JDSg, a=HOLD_START), 'X5_fresh2007': ex(fg, JDSg, a=HOLD_START)}
    jdx['caveat'] = 'JD の重みは 1988〜1992 に不安定（新興国の汚れた系列が当てはめに入る）。2007 以降の重みは French Developed の逆算とほぼ一致（2007 0.39 vs 0.44・2025 0.66 vs 0.66）＝保有期間の判定には効かない'
    # 米国の重みの寄り（入金を w_US で US・Ind_all へ入れて売らない道 N_dev）そのものが先進国の相手にどれだけ負けたか
    Ndev_ = neutral_alloc(wus, 'IND')
    ndg_, _ = path(Ndev_, G, START, END)
    ndf_, _ = path(Ndev_, G, HOLD_START, END)
    FDg_ = {m: jpy(d, d.frdev[m], m) for m in mrange(199007, END) if m in d.frdev}
    jdx['neutral_flow_dev_structural'] = {'vs_JD_train': ex(ndg_, JDg, z=TRAIN_END), 'vs_JD_hold_path': ex(ndg_, JDg, a=HOLD_START),
                                          'vs_JD_fresh2007': ex(ndf_, JDg, a=HOLD_START), 'vs_FD_hold_path': ex(ndg_, FDg_, a=HOLD_START),
                                          'vs_FD_fresh2007': ex(ndf_, FDg_, a=HOLD_START)}
    res['JD_same_source_developed'] = jdx
    print('JD', json.dumps(jdx, ensure_ascii=False))

    # 8c) Z3（保有でいちばん強かった C）を自前で: US=French Mkt・XD=French Ind_all、12-1 の勢いが高い方へ入金を全部
    res['Z3_check'] = z3_check(d, wus, wjd, G, N, MWn)
    print('Z3', json.dumps(res['Z3_check'], ensure_ascii=False))

    # 9) 多重検定
    j = json.load(open(os.path.join(M.BASE, 'out', 'mw_flow_tilt.json')))
    n_graded = sum(1 for x in j['tested'] if x.get('graded'))
    n_all = len(j['tested'])
    tr_t = rep['gross_train']['t']
    p_tr = math.erfc(abs(tr_t) / math.sqrt(2))
    res['multiple_testing'] = {'n_graded_in_angle': n_graded, 'n_tested_entries_in_angle': n_all,
                               'train_t': tr_t, 'train_p_two_sided': round(p_tr, 4),
                               'bonferroni_train_p_over_graded': round(min(1, p_tr * n_graded), 3),
                               't_needed_bonferroni_5pct_graded': round(_t_needed(0.05 / n_graded), 2),
                               'holm_hold_p_reported_by_researcher': 1.0,
                               'note': 'X5 は事前登録1の R（地域の中の国の選び分け）の勝ちを見てから足した探索の族の1本'}
    try:
        sm = json.load(open(os.path.join(M.BASE, 'out', 'mw_summary.json')))
        res['multiple_testing']['program_tests_total'] = sm.get('program_tests_total')
        res['multiple_testing']['bonferroni_t_program_wide'] = sm.get('bonferroni_t_program_wide')
    except Exception as e:
        res['multiple_testing']['program_line_error'] = str(e)
    res['multiple_testing']['X5_best_t_any_window'] = max(rep['gross_full']['t'], rep['gross_train']['t'], rep['gross_hold']['t'])

    # 10) 判定
    base_claim_ok = (abs(rep['gross_train']['ex_ann'] - 4.25) < 0.15 and abs(rep['gross_hold']['ex_ann'] - 0.54) < 0.15)
    bdh = clean['vs_BD_synthetic']
    fdh = clean['vs_French_Developed']
    nb = res['neighbors']
    def count(lab):
        return {'B_possible': sum(1 for v in nb.values() if v[lab]['B_or_better_possible']), 'of': len(nb)}
    verdict = {
        'name': 'X5_UScap_XUScountry_top3', 'claimed_grade': 'B', 'reproduced': bool(base_claim_ok),
        'verified_grade': 'C', 'verdict': 'downgraded to C',
        'neighbors_B_possible_by_benchmark': {lab: count(lab) for lab in ('W', 'BD', 'FD', 'MSCIW')},
        'grade_by_benchmark': {
            'JKP_world（研究役の相手・汚れあり）': 'B（再現）',
            'BD（w·JKP usa + (1−w)·French Ind_all・同じ出どころ）': 'C（C1 t %.2f < 2.0。近い設定で B/C が入れ替わる刃の上）' % bdh['gross_train']['t'],
            'French Developed（上限なしの時価加重の先進国・1990-07〜）': 'C（保有 %+.2f%%/年 t %.2f・費用後 %+.2f）' % (fdh['gross_hold']['ex_ann'], fdh['gross_hold']['t'], fdh['net_hold']['ex_ann']),
            'MSCI World NETR（円・0.099%%）': 'C（2007から始めた道 %+.2f%%/年）' % clean['vs_MSCI_World_net']['fresh2007']['ex_ann'],
            'MSCI ACWI NETR（円・0.0578%%）': 'C（2007から始めた道 %+.2f%%/年）' % clean['vs_MSCI_ACWI_net']['fresh2007']['ex_ann'],
            '傾けだけ（入金を時価の重みで US・Ind_all へ入れて売らない道）': 'C（訓練 t %.2f・保有 %+.2f）' % (clean['vs_neutral_flow_dev']['gross_train']['t'], clean['vs_neutral_flow_dev']['gross_hold']['ex_ann']),
        },
    }
    jdh = res['JD_same_source_developed']['X5_vs_JD']
    verdict['grade_by_benchmark']['JD（JKP usa＋JKP developed を JKP world から逆算した重みで合わせた先進国・1986〜・検証役が新設）'] = \
        'C（訓練 %+.2f t %.2f は C1 を通るが、保有 %+.2f%%/年 t %.2f・CAGR差 %+.2f・費用後 %+.2f＝C2・C6 不合格）' % (
            jdh['gross_train']['ex_ann'], jdh['gross_train']['t'], jdh['gross_hold']['ex_ann'], jdh['gross_hold']['t'],
            jdh['gross_hold']['cagr_diff'], jdh['net_hold']['ex_ann'])
    verdict['vs_US_market_for_this_investor'] = clean['vs_SP500_net']
    verdict['issues'] = [
        '相手の汚れ: JKP world は 1986〜1995 の新興国の系列が壊れていて（1988 −50.7%・1990 −67.5%）訓練の相手が弱い。X5 は新興国を1円も持たないので、この汚れの分だけ訓練の超過が膨らむ（C1 の t 2.57 はその中）',
        '相手の地域が違う: X5 の器は米国＋先進国20か国だけ。事前登録の『同じ地域の時価加重の市場』は先進国の市場で、それに対しては保有で負け（French Developed −0.37%/年・JD −0.10%/年・MSCI World −0.60%/年・MSCI ACWI −0.29%/年）',
        '米国の重みの取り違え: X5 は米国へ『世界（新興国込み）の中の米国の重み』しか入れないので、先進国の市場に比べて構造的に米国外の先進国へ寄っている（2025年 0.51 vs 0.66）。この寄りだけの道（N_dev）は French Developed に対し 2007から始めた道で −0.62%/年（t −3.27）、1986からの道の保有では −0.06%/年＝保有期間で国の傾けも米国の寄りもどちらも0以下',
        '傾けそのもの（同じ重みで米国外を Ind_all のまま持つ道との差）は訓練 t 1.85 で C1 に届かず、保有 −0.31%/年（2007から始めた道 +0.18）＝国の割安の効きは0前後',
        '部分期間: JKP world に対する 1986〜1990 の +6.49%/年は JD（汚れの無い同じ出どころ）では +3.39%/年（t 0.71）＝約3pt は新興国の汚れの分。保有の前半（2007-01〜2016-06）は JD に +0.46、後半（2016-07〜）は −0.65%/年（t −1.19）',
        '探索の族: X5 は事前登録1の結果（保有期間を含む）を見た後に足した24本の1本。角度の中の Bonferroni（24本）で要る t は 3.08、プログラム全体の線は t 4.43。X5 の最大の t は 2.59',
        '米国の市場（この投資家の実際の比べ先）に対しては 2007から始めた道で −3.13%/年（t −2.51）・20年積立の中央 0.870 倍',
    ]
    verdict['key_numbers_reproduced'] = {
        'vs_JKP_world_gross': {'full': [rep['gross_full']['ex_ann'], rep['gross_full']['t']], 'train': [rep['gross_train']['ex_ann'], rep['gross_train']['t']],
                               'hold': [rep['gross_hold']['ex_ann'], rep['gross_hold']['t'], rep['gross_hold']['cagr_diff']]},
        'net_hold_vs_W': rep['net_hold']['ex_ann'], 'roll20_lump_net_win': rep['roll20_lump_net']['win_rate'], 'dca20_vs_W_net': rep['dca20_vs_W_net']['median']}
    z3 = res['Z3_check']
    z3v = {
        'name': 'Z3_mom_US_XD（追加の点検・研究役の格付け C・保有でいちばん強かった本）', 'claimed_grade': 'C', 'reproduced': True,
        'verified_grade': 'C', 'verdict': 'confirmed C',
        'key_numbers': {'train_1991_07_2006_vs_BD2': [z3['vs_BD2_1991']['train_1991_07_2006']['ex_ann'], z3['vs_BD2_1991']['train_1991_07_2006']['t']],
                        'train_1986_2006_vs_BD1': [z3['vs_BD1_1986']['train_1986_2006']['ex_ann'], z3['vs_BD1_1986']['train_1986_2006']['t']],
                        'hold_path_vs_BD2': [z3['vs_BD2_1991']['hold_path']['ex_ann'], z3['vs_BD2_1991']['hold_path']['t']],
                        'net_fresh2007_vs_BD2': z3['vs_BD2_1991']['net_fresh2007']['ex_ann'],
                        'vs_US_market_net_fresh2007': [z3['vs_US_market_net']['fresh2007']['ex_ann'], z3['vs_US_market_net']['fresh2007']['t']]},
        'issues': ['訓練は 1991-07〜 でも 1986〜 に延ばしても t < 2（C1 不合格）・近い勢いの長さ6本すべてで訓練 t 0.8〜1.5',
                   '保有の勝ちは入金の74%が米国へ向いた 2007年以降の米国の独走そのもの（1986〜2006 は52%）',
                   '米国の市場には 2007から始めた道で負ける（上の数字）＝米国の投資家から見ると勝ちではない']}
    res['verdicts'] = [dict(verdict, verified_grade='C', verdict='downgraded to C'), z3v]
    res['verdict'] = verdict
    return res, d


def _t_needed(p):
    lo, hi = 0.0, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if math.erfc(mid / math.sqrt(2)) > p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


if __name__ == '__main__':
    res, _ = main()
    res['scope'] = 'S・A は0本、B は X5 の1本だけ（B の上位2本＝X5）。追加で、保有期間でいちばん強かった C の Z3 も自前で作り直して格付けを確かめた'
    res['summary_ja'] = [
        '対象: S・A は0本、B は X5（米国は時価の重み・米国外は配当利回りが自分の過去20年より高い上位3か国へ入金）の1本だけ。自前のコードで研究役の数字を小数2桁まで再現した（JKP world に対し 訓練 +4.25%/年 t 2.57・保有 +0.54% t 0.97・費用後 +0.41）。',
        '判定: C へ格下げ。相手の JKP world は訓練期間の新興国の系列が壊れており（1988 −50.7%）、新興国を持たない X5 はその分だけ得をしていた（1986〜90 の超過 +6.49 → 汚れの無い相手では +3.39）。',
        '事前登録の『同じ地域の時価加重の市場』＝先進国の市場に対しては保有期間で負け: French Developed −0.37%/年・検証役が新設した同じ出どころの JD −0.10%/年・MSCI World −0.60%/年・MSCI ACWI −0.29%/年（2007から始めた道も −0.17〜−0.56）。',
        '国の割安の傾けだけの効き（同じ米国の重みで米国外を指数のまま持つ道との差）は訓練 t 1.85 で C1 に届かず、保有 −0.31%/年。近い設定11本は相手を French Developed か MSCI World にすると B になれるものが0本。',
        '米国の市場（S&P500 に近い French Mkt）には 2007年から始めた道で −3.13%/年（t −2.51）、20年積立の中央 0.870 倍。最大の t は 2.59 で、角度内 Bonferroni の 3.08・プログラム全体の 4.43 に遠い。',
        '追加点検: 保有でいちばん強かった Z3（勢いの入金）は訓練 t 0.81（1991〜）/1.39（1986〜）で C のまま確認。保有の勝ち（+0.97%/年 t 3.23）は入金の74%が米国へ向いた2007年以降の米国の独走で、米国の市場には −1.55%/年。',
        '「検証は限界か」について: この角度では、相手の汚れ・相手の地域・米国の重みを一つ直すごとに勝ちが消えた。データを足すほど結果が0へ寄るのは、限界というより『上乗せが無い』ことの測定が安定してきたことを示す。',
    ]
    res['generated'] = datetime.date.today().isoformat()
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('書いた', OUT)
