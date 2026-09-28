#!/usr/bin/env python3
"""night/mw_country.py — 『市場に勝てる歴史検証』の角度 country（国を選ぶ）。読むだけ・門の判定には不使用。

事前登録: out/mw_country_prereg.json（C1〜C8 の線は out/mw_prereg.json・判定は mw_common.grade）
出力:     out/mw_country.json

問い: 国別の株価指数（ドル建て）を、勢い・割安・両方・米国と米国外の相対の勢いで選ぶ規則は、
      時価加重の先進国市場（JKP developed vw）に、費用と国別ETFの信託報酬の差を引いた後も勝つか。

使い方:
  python3 night/mw_country.py --check   # データの配管だけ点検（戦略と市場の比較は出さない）
  python3 night/mw_country.py           # 全部測って out/mw_country.json を書く

約束（mw_common に従う）
- 月次リターンは小数・キーは yyyymm。JKP は超過（米国T-bill）→ French RF を足して総リターンにそろえる
- 月末 t に分かる値だけで選び、月 t+1 のリターンに当てる（先読みなし）
- 欠けた値は 0 と読まない（順位に入れない／戦略の月を空欄にする）
"""
import sys, os, io, json, math, zipfile, subprocess, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M

PREREG = 'out/mw_country_prereg.json'
OUT = 'mw_country.json'

DEV23 = 'usa jpn gbr deu fra che nld swe dnk nor fin bel aut ita esp irl prt can aus nzl hkg sgp isr'.split()
FR_FILES = {'gbr': 'UK', 'aut': 'Austria', 'aus': 'Austrlia', 'bel': 'Belgium', 'can': 'Canada', 'dnk': 'Denmark',
            'fin': 'Finland', 'fra': 'France', 'deu': 'Germany', 'hkg': 'HongKong', 'irl': 'Ireland', 'ita': 'Italy',
            'jpn': 'Japan', 'nld': 'Nethrlnd', 'nzl': 'NewZland', 'nor': 'Norway', 'sgp': 'Singapor', 'esp': 'Spain',
            'swe': 'Sweden', 'che': 'Swtzrlnd'}
F20 = sorted(FR_FILES)
V21 = F20 + ['usa']
DXUS22 = [c for c in DEV23 if c != 'usa']
EAFE19 = [c for c in F20 if c != 'can']
EM24 = 'bra chl chn col cze egy grc hun ind idn kor kwt mys mex per phl pol qat sau zaf twn tha tur are'.split()
FRONTIER = ('arg bgd bhr bgr hrv est isl jor ken kaz ltu lka mar mus nga omn pak rou srb svn tun vnm lva civ gha bwa '
            'jam tto zwe ukr').split()
ALL47 = DEV23 + EM24
ETF = {'EWJ': 'jpn', 'EWG': 'deu', 'EWU': 'gbr', 'EWC': 'can', 'EWA': 'aus', 'EWQ': 'fra', 'EWL': 'che', 'EWN': 'nld',
       'EWD': 'swe', 'EWP': 'esp', 'EWI': 'ita', 'EWH': 'hkg', 'EWS': 'sgp', 'EWK': 'bel', 'EWO': 'aut', 'SPY': 'usa'}
NMIN = 20
EM_ETF = 'EWZ EWT EWY EWW EWM EZA FXI ECH TUR THD EPOL EIDO EPHE EPU INDA'.split()
DEV_ETF_X = {'ENZL': 'nzl', 'EIRL': 'irl', 'ENOR': 'nor', 'EFNL': 'fin', 'EDEN': 'dnk'}
YAHOO_LAST = 202608  # 2026-09 は月の途中

# 費用（事前登録どおり）: 片道100%あたりの売買費用・信託報酬の差（年率）
COST = {'dev': (0.0015, 0.0040), 'em': (0.0030, 0.0050), 'fr': (0.0050, 0.0070), 'broad': (0.0005, 0.0),
        'etf': (0.0015, 0.0), 'etf_broad': (0.0005, 0.0), 'etf_em': (0.0030, 0.0),
        'ind49': (0.0010, 0.0030), 'ind12': (0.0010, 0.0005)}


def ym_add(ym, k):
    y, m = divmod(ym, 100)
    n = y * 12 + (m - 1) + k
    return (n // 12) * 100 + n % 12 + 1


def months_between(a, z):
    out, m = [], a
    while m <= z:
        out.append(m); m = ym_add(m, 1)
    return out


# ───────────────────────── データ ─────────────────────────
_RF = None


def rf():
    global _RF
    if _RF is None:
        _RF = M.ff_factors()['rf']
    return _RF


def to_total(ex):
    r = rf()
    return {k: v + r[k] for k, v in ex.items() if k in r}


def jkp_country(c):
    """JKP の国・地域の mkt vw → (総リターン {ym}, n {ym})。n は国なら n_stocks、地域なら n_countries"""
    rows = M.jkp_rows(c, 'mkt', 'factor', 'vw')
    ret, n = {}, {}
    for x in rows:
        if x['ret'] in ('', 'NA', 'na'):
            continue
        ym = M._ym(x['date'])
        ret[ym] = float(x['ret'])
        k = 'n_stocks' if 'n_stocks' in x else 'n_countries'
        n[ym] = int(x[k]) if x.get(k) not in (None, '', 'na', 'NA') else None
    return to_total(ret), n


def parse_fr_dat(txt):
    """French の国別 .Dat を節ごとに読む → {(種類, 組, 頻度): {'cols': [...], 'data': {日付: [値]}}}
    種類: 'USD' / 'LOC' / 'RATIO'、組: 'NR'（All 4 Not Reqd）/ 'RQ'（Required）、頻度: 'm' / 'a'"""
    secs, cur, kind, grp, cols, pend = {}, None, None, None, None, []
    for raw in txt.splitlines():
        line = raw.strip()
        if not line:
            cur = None
            continue
        tok = line.split()
        if tok[0].isdigit() and len(tok[0]) in (4, 6) and kind:
            freq = 'm' if len(tok[0]) == 6 else 'a'
            key = (kind, grp, freq)
            if cur is None:
                if key in secs:  # 同じ鍵が二度出たら二つ目は別物として残す
                    key = key + (len(secs),)
                cur = secs[key] = {'cols': cols, 'data': {}}
            vals = []
            for v in tok[1:]:
                try:
                    f = float(v)
                except ValueError:
                    f = None
                vals.append(None if f is None or f <= -99.99 or f == -999 else f)
            cur['data'][int(tok[0])] = vals
            continue
        cur = None
        low = line.lower()
        if 'dollar' in low and 'return' in low:
            kind = 'USD'
        elif 'local' in low and 'return' in low:
            kind = 'LOC'
        elif 'ratio' in low or 'annual value-weight averages' in low:
            kind = 'RATIO'
        if 'not req' in low:
            grp = 'NR'
        elif 'required' in low or ' reqd' in low:
            grp = 'RQ'
        if tok[0] in ('Mkt', 'Firms'):
            cols = tok
    return secs


_FR = {}


def french_intl():
    """{国: {'usd': 総リターン, 'loc': 現地総, 'loc_ex': 現地配当抜き, 'bm'/'ep'/'cep'/'yld'/'firms': {年Y: 値}}}"""
    if _FR:
        return _FR
    zt = zipfile.ZipFile(io.BytesIO(M.get('https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_International_Countries.zip',
                                          name='fr_F-F_International_Countries.zip')))
    zx = zipfile.ZipFile(io.BytesIO(M.get('https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_International_Countries_Wout_Div.zip',
                                          name='fr_F-F_International_Countries_Wout_Div.zip')))
    for c, f in FR_FILES.items():
        a = parse_fr_dat(zt.read(f + '.Dat').decode('latin-1'))
        b = parse_fr_dat(zx.read(f + '.Dat').decode('latin-1'))
        d = {}
        col = lambda sec, name: {k: v[sec['cols'].index(name)] / 100 for k, v in sec['data'].items() if v[sec['cols'].index(name)] is not None}
        d['usd'] = col(a[('USD', 'NR', 'm')], 'Mkt')
        d['loc'] = col(a[('LOC', 'NR', 'm')], 'Mkt')
        d['loc_ex'] = col(b[('LOC', 'NR', 'm')], 'Mkt')
        d['usd_ex'] = col(b[('USD', 'NR', 'm')], 'Mkt')
        rt = a[('RATIO', 'NR', 'a')]
        cs = rt['cols']  # ['Firms','B/M','E/P','CE/P','Yld']
        for name, key in (('B/M', 'bm'), ('E/P', 'ep'), ('CE/P', 'cep'), ('Yld', 'yld')):
            i = cs.index(name)
            d[key] = {y: v[i] / 100 for y, v in rt['data'].items() if v[i] is not None}
        i = cs.index('Firms')
        d['firms'] = {y: v[i] for y, v in rt['data'].items() if v[i] is not None}
        _FR[c] = d
    zi = zipfile.ZipFile(io.BytesIO(M.get('https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_International_Indices.zip',
                                          name='fr_F-F_International_Indices.zip')))
    a = parse_fr_dat(zi.read('Ind_all.Dat').decode('latin-1'))
    sec = a[('USD', 'NR', 'm')]
    _FR['_eafe'] = {k: v[sec['cols'].index('Mkt')] / 100 for k, v in sec['data'].items() if v[sec['cols'].index('Mkt')] is not None}
    return _FR


def _french_table(name, want, freq):
    for t, v in M.french_tables(name).items():
        if t.lower().startswith(want.lower()) and v['freq'] == freq:
            return v
    raise KeyError(f'{name}: {want}')


_US = {}


def us_data():
    """米国: 年次の B/M・E/P・CE/P（年 Y＝FY Y−1 ÷ Y−1年12月末の時価）と、規模別の時価加重で作る配当込み・配当抜きの月次"""
    if _US:
        return _US
    G = ['<= 0', 'Lo 30', 'Med 40', 'Hi 30']
    for fname, key, tname in (('Portfolios_Formed_on_BE-ME', 'bm', 'Sum of BE'), ('Portfolios_Formed_on_E-P', 'ep', 'Sum of E'),
                              ('Portfolios_Formed_on_CF-P', 'cep', 'Sum of CF')):
        ratio = _french_table(fname, tname, 'annual')
        nf = _french_table(fname, 'Number of Firms', 'monthly')
        sz = _french_table(fname, 'Average Firm Size', 'monthly')
        out = {}
        for y, row in ratio['data'].items():
            m = y * 100 + 7
            if m not in nf['data'] or m not in sz['data']:
                continue
            num = den = 0.0
            ok = False
            for g in G:
                i = ratio['cols'].index(g)
                s, n, a = row[i], nf['data'][m][nf['cols'].index(g)], sz['data'][m][sz['cols'].index(g)]
                if s is None or n is None or a is None or n <= 0:
                    continue
                w = n * a
                num += s * w; den += w
                if g != '<= 0':
                    ok = True
            if ok and den > 0:
                out[y] = num / den
        _US[key] = out
    # 規模別（Lo 30 / Med 40 / Hi 30）を社数×平均規模で時価加重 → 配当込み・配当抜き
    G3 = ['Lo 30', 'Med 40', 'Hi 30']
    tot = _french_table('Portfolios_Formed_on_ME', 'Average Value Weight Returns', 'monthly')
    ex = _french_table('Portfolios_Formed_on_ME_Wout_Div', 'Average Value Weight Returns', 'monthly')
    nf = _french_table('Portfolios_Formed_on_ME', 'Number of Firms', 'monthly')
    sz = _french_table('Portfolios_Formed_on_ME', 'Average Firm Size', 'monthly')
    rt, rx = {}, {}
    for m in sorted(tot['data']):
        if m not in ex['data'] or m not in nf['data'] or m not in sz['data']:
            continue
        ws, st, sx, ok = 0.0, 0.0, 0.0, True
        for g in G3:
            n, a = nf['data'][m][nf['cols'].index(g)], sz['data'][m][sz['cols'].index(g)]
            a1, b1 = tot['data'][m][tot['cols'].index(g)], ex['data'][m][ex['cols'].index(g)]
            if None in (n, a, a1, b1):
                ok = False; break
            w = n * a
            ws += w; st += w * a1 / 100; sx += w * b1 / 100
        if ok and ws > 0:
            rt[m] = st / ws; rx[m] = sx / ws
    _US['tot'] = rt
    _US['ex'] = rx
    return _US


def etf_raw(tk):
    """Yahoo のキャッシュ済み月次 JSON → (月末の終値〔分割調整・配当未調整〕{ym}, その月の分配金の合計 {ym})"""
    import datetime, glob
    M.yahoo(tk)  # キャッシュを作る
    f = os.path.join(M.CACHE, f'yh_{tk}_1mo.json')
    j = json.load(open(f))['chart']['result'][0]
    cl = {}
    for t, c in zip(j['timestamp'], j['indicators']['quote'][0]['close']):
        if c is None:
            continue
        d = datetime.datetime.utcfromtimestamp(t)
        cl[d.year * 100 + d.month] = c
    dv = {}
    for e in (j.get('events', {}).get('dividends', {}) or {}).values():
        d = datetime.datetime.utcfromtimestamp(e['date'])
        k = d.year * 100 + d.month
        dv[k] = dv.get(k, 0.0) + e['amount']
    cl = {k: v for k, v in cl.items() if k <= YAHOO_LAST}
    return cl, dv


def price_index(ex):
    """配当抜きの月次 → 価格指数 {ym: 月末の水準}（最初の月の前月末を1）"""
    p, lv = {}, 1.0
    ks = sorted(ex)
    if not ks:
        return p
    p[ym_add(ks[0], -1)] = 1.0
    prev = ym_add(ks[0], -1)
    for k in ks:
        if k != ym_add(prev, 1):  # 月が抜けたら以後は切る（0 と読まない）
            break
        lv *= 1 + ex[k]; p[k] = lv; prev = k
    return p


# ───────────────────────── 信号 ─────────────────────────
class World:
    """全データを持ち、月末 t に分かる信号を返す"""

    def __init__(self):
        self.ret, self.n = {}, {}
        for c in sorted(set(DEV23 + EM24 + FRONTIER)):
            try:
                self.ret[c], self.n[c] = jkp_country(c)
            except Exception as e:  # noqa
                print('JKP 取得失敗', c, e)
        self.reg = {}
        for r in ('developed', 'world', 'world_ex_us', 'emerging', 'frontier'):
            self.reg[r], _ = jkp_country(r)
        self.fr = french_intl()
        self.us = us_data()
        # 現地通貨の価格指数と配当（月次）
        self.px, self.div = {}, {}
        for c in F20:
            self.px[c] = price_index(self.fr[c]['loc_ex'])
            self.div[c] = {k: self.fr[c]['loc'][k] - self.fr[c]['loc_ex'][k] for k in self.fr[c]['loc'] if k in self.fr[c]['loc_ex']}
        self.px['usa'] = price_index(self.us['ex'])
        self.div['usa'] = {k: self.us['tot'][k] - self.us['ex'][k] for k in self.us['tot'] if k in self.us['ex']}
        # 年次の比率（年 Y ＝ Y−1 年12月末）
        self.lab = {'bm': {}, 'ep': {}, 'cep': {}, 'firms': {}}
        for c in F20:
            for k in ('bm', 'ep', 'cep', 'firms'):
                self.lab[k][c] = self.fr[c][k]
        for k in ('bm', 'ep', 'cep'):
            self.lab[k]['usa'] = self.us[k]
        self.lab['yld'] = {c: self.fr[c]['yld'] for c in F20}  # 事前登録3 の D2（年次表の Yld）
        # 実在ETF（R 族と D5）: 2026-09 は月の途中なので切る
        self.etf = {}
        for tk in list(ETF) + ['EFA', 'ACWI', 'EEM'] + EM_ETF + list(DEV_ETF_X):
            self.etf[tk] = {k: v for k, v in M.yahoo(tk).items() if k <= YAHOO_LAST}
        # 事前登録4 の J: ETF の分配金と未調整の終値
        self.etf_close, self.etf_div = {}, {}
        for tk in list(ETF) + EM_ETF + list(DEV_ETF_X):
            self.etf_close[tk], self.etf_div[tk] = etf_raw(tk)
        # 事前登録4 の I: French の業種（配当込み・配当抜き）
        self.ind = {}
        for n in (49, 12):
            tot = M.french_series(f'{n}_Industry_Portfolios', 'Value Weight', 'monthly')
            ex = M.french_series(f'{n}_Industry_Portfolios_Wout_Div', 'Value Weight', 'monthly')
            self.ind[n] = (tot, ex)
        # French の地域
        self.freg = {}
        for name, key in (('Developed_3_Factors', 'dev'), ('Developed_ex_US_3_Factors', 'dxus'), ('North_America_3_Factors', 'NA'),
                          ('Europe_3_Factors', 'EU'), ('Japan_3_Factors', 'JP'), ('Asia_Pacific_ex_Japan_3_Factors', 'APxJ')):
            for t, v in M.french_tables(name).items():
                if v['freq'] == 'monthly':
                    i, j = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
                    self.freg[key] = {d: (row[i] + row[j]) / 100 for d, row in v['data'].items() if row[i] is not None and row[j] is not None}
                    break

    # --- 基本 ---
    def elig(self, c, t, src='jkp'):
        if src == 'jkp':
            n = self.n.get(c, {}).get(t)
            return n is not None and n >= NMIN
        if src == 'fr':  # French 国別: 年次表の社数
            Y = t // 100 if t % 100 >= 6 else t // 100 - 1
            f = self.lab['firms'].get(c, {}).get(Y)
            return f is not None and f >= NMIN
        return True

    @staticmethod
    def cum(r, t, a, b):
        """t−a〜t−b の累積（全月そろわなければ None）"""
        g = 1.0
        for k in range(a, b - 1, -1):
            v = r.get(ym_add(t, -k))
            if v is None:
                return None
            g *= 1 + v
        return g - 1

    def dp_at(self, c, t):
        """配当利回り（月末 t までの12か月の配当リターンの和・現地通貨）"""
        d = self.div.get(c, {})
        v = [d.get(ym_add(t, -k)) for k in range(12)]
        return None if any(x is None for x in v) else sum(v)

    def label(self, key, c, Y):
        if key == 'dp':  # 年 Y の配当利回り＝ Y−1 年12月末の値（他の比率と時点をそろえる）
            return self.dp_at(c, (Y - 1) * 100 + 12)
        return self.lab[key].get(c, {}).get(Y)

    def bm_monthly(self, c, t):
        Y = t // 100 if t % 100 >= 6 else t // 100 - 1
        b = self.lab['bm'].get(c, {}).get(Y)
        p = self.px.get(c, {})
        p0, p1 = p.get((Y - 1) * 100 + 12), p.get(t)
        if b is None or p0 is None or p1 is None or p1 <= 0:
            return None
        return b * p0 / p1

    def etf_dp(self, tk, Y):
        """J: 過去12か月（Y−1年1〜12月）の分配金 ÷ Y−1年12月末の終値。12か月の履歴がそろう ETF だけ"""
        cl = self.etf_close.get(tk, {})
        if not cl or min(cl) > (Y - 1) * 100 + 1:
            return None
        p = cl.get((Y - 1) * 100 + 12)
        if not p:
            return None
        return sum(self.etf_div[tk].get((Y - 1) * 100 + m, 0.0) for m in range(1, 13)) / p

    def ind_dp(self, n, col, t):
        tot, ex = self.ind[n]
        v = []
        for k in range(12):
            m = ym_add(t, -k)
            a, b = tot[col].get(m), ex[col].get(m)
            if a is None or b is None:
                return None
            v.append(a - b)
        return sum(v)

    def cape(self, c, Y):
        """事前登録3 の K 族: CAPE_Y = P(Y−1年12月末) ÷ 10年平均の名目利益（E_y = E/P_y × P(y−1年12月末)）"""
        p = self.px.get(c, {})
        es = []
        for y in range(Y - 9, Y + 1):
            ep, py = self.lab['ep'].get(c, {}).get(y), p.get((y - 1) * 100 + 12)
            if ep is None or py is None:
                return None
            es.append(ep * py)
        m = S.mean(es)
        p0 = p.get((Y - 1) * 100 + 12)
        if m <= 0 or p0 is None:
            return None
        return p0 / m

    def relval(self, c, Y):
        rels = []
        for key in ('bm', 'cep', 'dp'):
            x = self.label(key, c, Y)
            h = [self.label(key, c, y) for y in range(Y - 10, Y)]
            h = [v for v in h if v is not None and v > 0]
            if x is None or x <= 0 or len(h) < 5:
                continue
            rels.append(math.log(x / S.median(h)))
        return S.mean(rels) if len(rels) >= 2 else None


def pct_ranks(score):
    """{国: 値} → {国: 0..1 の百分位（高いほど良い）}。同値は国コードで決める"""
    ks = sorted(score, key=lambda c: (score[c], c))
    n = len(ks)
    return {c: (i / (n - 1) if n > 1 else 0.5) for i, c in enumerate(ks)}


def top_k(score, K, reverse=True):
    """score の上位 K（reverse=False なら下位）。同値は国コード"""
    if K <= 0:
        return None
    ks = sorted(score, key=lambda c: ((-score[c]) if reverse else score[c], c))
    return ks[:K]


# ───────────────────────── 売買の再生 ─────────────────────────
def backtest(assets_ret, choose, months, rebal_month=None):
    """choose(t) → {資産: 重み}（合計1）または None（その期間は持たない＝空欄）。
    rebal_month=None なら毎月、6 なら毎年6月末に選び直して1年持ちっぱなし（重みは漂う）。
    戻り値: (総リターン {ym}, 回転 {ym}, 保有の記録 {ym: {資産: 重み}}, 割り直し件数)"""
    out, turn, hold = {}, {}, {}
    w = None  # 月初の重み（漂った後）
    renorm = 0
    for i in range(len(months) - 1):
        t, t1 = months[i], months[i + 1]
        if rebal_month is None or t % 100 == rebal_month or w is None:
            if rebal_month is not None and w is None and t % 100 != rebal_month:
                continue  # 年次: 最初の6月末まで待つ
            tgt = choose(t)
            if tgt is None:
                w = None
                continue
            if w is not None:
                turn[t1] = sum(abs(tgt.get(a, 0) - w.get(a, 0)) for a in set(tgt) | set(w)) / 2
            else:
                turn[t1] = 0.0  # 最初の買いは数えない（相手も買う）
            w = dict(tgt)
        else:
            turn[t1] = 0.0
        rs = {a: assets_ret(a, t1) for a in w}
        av = {a: x for a, x in rs.items() if x is not None}
        if not av:
            w = None
            continue
        tw = sum(w[a] for a in av)
        if len(av) < len(rs):
            renorm += 1
        rp = sum(w[a] * av[a] for a in av) / tw
        out[t1] = rp
        hold[t1] = {a: w[a] / tw for a in av}
        w = {a: w[a] / tw * (1 + av[a]) / (1 + rp) for a in av}
    return out, turn, hold, renorm


# ───────────────────────── 戦略の定義 ─────────────────────────
def make_strategies(W):
    """事前登録どおりの全戦略 → [{id, family, primary, universe, bench, cost, run()}]"""
    R = W.ret
    rfd = rf()

    def jret(a, t):
        if a == 'RF':
            return rfd.get(t)
        if a in R:
            return R[a].get(t)
        return W.reg.get(a, {}).get(t)

    def fret(a, t):  # French 国別ドル建て
        if a == 'RF':
            return rfd.get(t)
        return W.fr[a]['usd'].get(t)

    def gret(a, t):  # French 地域
        return W.freg[a].get(t)

    def mom_choose(univ, K, a, b, src='jkp', retd=None, reverse=True, kind='cum'):
        retd = retd or R

        def ch(t):
            sc = {}
            for c in univ:
                if not W.elig(c, t, src):
                    continue
                if kind == 'cum':
                    v = W.cum(retd.get(c, {}), t, a, b)
                elif kind == 'seas':
                    tg = ym_add(t, 1)
                    xs = [retd.get(c, {}).get(ym_add(tg, -12 * k)) for k in range(1, 21)]
                    xs = [x for x in xs if x is not None]
                    v = S.mean(xs) if len(xs) >= 5 else None
                elif kind == 'vol':
                    xs = [retd.get(c, {}).get(ym_add(t, -k)) for k in range(36)]
                    xs = [x for x in xs if x is not None]
                    v = S.stdev(xs) if len(xs) >= 24 else None
                if v is not None:
                    sc[c] = v
            k = K if K > 0 else math.ceil(len(sc) / (-K))  # K=-3 → 上位1/3、K=-4 → 上位1/4
            if k <= 0 or len(sc) < 2 * k:
                return None
            sel = top_k(sc, k, reverse)
            return {c: 1 / k for c in sel}
        return ch

    def val_choose(univ, K, key, src='jkp', cmap=None):
        """年次の割安（6月末に年 Y の値＝Y−1年12月末で選ぶ）。cmap は ETF→国（R 族）"""
        cmap = cmap or {}

        def ch(t):
            Y = t // 100
            el = [c for c in univ if W.elig(cmap.get(c, c), t, src)]
            sc = {}
            if key == 'comp4':
                prs = {}
                for kk in ('bm', 'ep', 'cep', 'dp'):
                    v = {c: W.label(kk, cmap.get(c, c), Y) for c in el}
                    v = {c: x for c, x in v.items() if x is not None}
                    if len(v) >= 2:
                        prs[kk] = pct_ranks(v)
                for c in el:
                    got = [prs[kk][c] for kk in prs if c in prs[kk]]
                    if len(got) >= 3:
                        sc[c] = S.mean(got)
            else:
                for c in el:
                    cc = cmap.get(c, c)
                    if key == 'relval':
                        v = W.relval(cc, Y)
                    elif key == 'cape':  # 低いほど割安 → 逆数（E10/P）で高い順
                        v = W.cape(cc, Y)
                        v = None if v is None else 1 / v
                    else:
                        v = W.label(key, cc, Y)
                    if v is not None:
                        sc[c] = v
            if len(sc) < 2 * K:
                return None
            return {c: 1 / K for c in top_k(sc, K)}
        return ch

    def bmM_choose(univ, K, src='jkp'):
        def ch(t):
            sc = {c: W.bm_monthly(c, t) for c in univ if W.elig(c, t, src)}
            sc = {c: v for c, v in sc.items() if v is not None}
            if len(sc) < 2 * K:
                return None
            return {c: 1 / K for c in top_k(sc, K)}
        return ch

    def vm_choose(univ, K, src='jkp', retd=None, cmap=None):
        retd = retd or R
        cmap = cmap or {}

        def ch(t):
            mo, va = {}, {}
            for c in univ:
                if not W.elig(cmap.get(c, c), t, src):
                    continue
                m = W.cum(retd.get(c, {}), t, 11, 1)
                v = W.bm_monthly(cmap.get(c, c), t)
                if m is not None and v is not None:
                    mo[c], va[c] = m, v
            if len(mo) < 2 * K:
                return None
            pm, pv = pct_ranks(mo), pct_ranks(va)
            ks = sorted(mo, key=lambda c: (-(pm[c] + pv[c]) / 2, -pm[c], c))
            return {c: 1 / K for c in ks[:K]}
        return ch

    def usrow_choose(a, b, legs=('usa', 'world_ex_us'), retf=None, gem=False):
        retf = retf or jret

        def ch(t):
            g = {}
            for x in legs:
                gg = 1.0
                for k in range(a, b - 1, -1):
                    v = retf(x, ym_add(t, -k))
                    if v is None:
                        return None
                    gg *= 1 + v
                g[x] = gg - 1
            win = max(legs, key=lambda x: (g[x], x == legs[0]))
            if gem:
                gr = 1.0
                for k in range(a, b - 1, -1):
                    v = rfd.get(ym_add(t, -k))
                    if v is None:
                        return None
                    gr *= 1 + v
                if g[legs[0]] <= gr - 1:
                    return {'RF': 1.0}
            return {win: 1.0}
        return ch

    def ctrend_choose(univ):
        def ch(t):
            el = [c for c in univ if W.elig(c, t) and W.cum(R.get(c, {}), t, 11, 0) is not None]
            if len(el) < 6:
                return None
            gr = W.cum(rfd, t, 11, 0)
            if gr is None:
                return None
            w = {}
            for c in el:
                a = c if W.cum(R[c], t, 11, 0) > gr else 'RF'
                w[a] = w.get(a, 0) + 1 / len(el)
            return w
        return ch

    def mom_abs_choose(univ, K):
        base = mom_choose(univ, K, 11, 1)

        def ch(t):
            w0 = base(t)
            if w0 is None:
                return None
            gr = W.cum(rfd, t, 11, 1)
            if gr is None:
                return None
            w = {}
            for c, x in w0.items():
                a = c if W.cum(R[c], t, 11, 1) > gr else 'RF'
                w[a] = w.get(a, 0) + x
            return w
        return ch

    def ew_choose(univ, src='jkp', retd=None, need=None):
        retd = retd or R

        def ch(t):
            el = [c for c in univ if W.elig(c, t, src) and retd.get(c, {}).get(t) is not None]
            if len(el) < 3:
                return None
            return {c: 1 / len(el) for c in el}
        return ch

    ST = []

    def add(id, fam, primary, univ_name, choose, retf, bench, cost, rebal=None, extra=None):
        d = {'id': id, 'family': fam, 'primary': primary, 'universe': univ_name, 'choose': choose, 'retf': retf,
             'bench': bench, 'cost': cost, 'rebal': rebal}
        d.update(extra or {})
        ST.append(d)

    # P（主）
    add('P1_mom12_K3', 'P', True, 'DEV23', mom_choose(DEV23, 3, 11, 1), jret, 'jkp_dev', 'dev', extra={'ew': 'C_ew_dev23', 'c5': ['E4_em_mom12_K3', 'E4_fr_mom12_K3'], 'pub': 1998})
    add('P2_mom12_K5', 'P', True, 'DEV23', mom_choose(DEV23, 5, 11, 1), jret, 'jkp_dev', 'dev', extra={'ew': 'C_ew_dev23', 'c5': ['E4_em_mom12_K5', 'E4_fr_mom12_K5'], 'pub': 1998})
    add('P3_bm_K3', 'P', True, 'V21', val_choose(V21, 3, 'bm'), jret, 'jkp_dev', 'dev', rebal=6, extra={'ew': 'C_ew_v21', 'pub': 1999})
    add('P4_bm_K5', 'P', True, 'V21', val_choose(V21, 5, 'bm'), jret, 'jkp_dev', 'dev', rebal=6, extra={'ew': 'C_ew_v21', 'pub': 1999})
    add('P5_vm_K3', 'P', True, 'V21', vm_choose(V21, 3), jret, 'jkp_dev', 'dev', extra={'ew': 'C_ew_v21', 'pub': 2014})
    add('P6_vm_K5', 'P', True, 'V21', vm_choose(V21, 5), jret, 'jkp_dev', 'dev', extra={'ew': 'C_ew_v21', 'pub': 2014})
    add('P7_usrow_12', 'P', True, 'usa/world_ex_us', usrow_choose(11, 0), jret, 'jkp_dev', 'broad', extra={'pub': 2013, 'also_world': True})
    # E1
    for K in (3, 5):
        add(f'E1_mom6_K{K}', 'E1', False, 'DEV23', mom_choose(DEV23, K, 5, 1), jret, 'jkp_dev', 'dev', extra={'ew': 'C_ew_dev23'})
        add(f'E1_mom12x_K{K}', 'E1', False, 'DEV23', mom_choose(DEV23, K, 11, 0), jret, 'jkp_dev', 'dev', extra={'ew': 'C_ew_dev23'})
    add('E1_mom12_T3', 'E1', False, 'DEV23', mom_choose(DEV23, -3, 11, 1), jret, 'jkp_dev', 'dev', extra={'ew': 'C_ew_dev23', 'pub': 1998})
    add('E1_mom12_K1', 'E1', False, 'DEV23', mom_choose(DEV23, 1, 11, 1), jret, 'jkp_dev', 'dev', extra={'ew': 'C_ew_dev23'})
    for K in (3, 5):
        add(f'E1_rev60_K{K}', 'E1', False, 'DEV23', mom_choose(DEV23, K, 59, 12, reverse=False), jret, 'jkp_dev', 'dev', extra={'ew': 'C_ew_dev23', 'pub': 1998})
        add(f'E1_seas_K{K}', 'E1', False, 'DEV23', mom_choose(DEV23, K, 0, 0, kind='seas'), jret, 'jkp_dev', 'dev', extra={'ew': 'C_ew_dev23', 'pub': 2017})
        add(f'E1_lowvol_K{K}', 'E1', False, 'DEV23', mom_choose(DEV23, K, 0, 0, reverse=False, kind='vol'), jret, 'jkp_dev', 'dev', extra={'ew': 'C_ew_dev23'})
    add('E1_usrow_12_1', 'E1', False, 'usa/world_ex_us', usrow_choose(11, 1), jret, 'jkp_dev', 'broad', extra={'also_world': True})
    add('E1_usrow_6', 'E1', False, 'usa/world_ex_us', usrow_choose(5, 0), jret, 'jkp_dev', 'broad', extra={'also_world': True})
    # E2
    for key in ('ep', 'cep', 'dp', 'comp4'):
        for K in (3, 5):
            add(f'E2_{key}_K{K}', 'E2', False, 'V21', val_choose(V21, K, key), jret, 'jkp_dev', 'dev', rebal=6, extra={'ew': 'C_ew_v21'})
    for K in (3, 5):
        add(f'E2_bmM_K{K}', 'E2', False, 'V21', bmM_choose(V21, K), jret, 'jkp_dev', 'dev', extra={'ew': 'C_ew_v21'})
    for K in (3, 5):
        add(f'E2_relval_K{K}', 'E2', False, 'V21', val_choose(V21, K, 'relval'), jret, 'jkp_dev', 'dev', rebal=6, extra={'ew': 'C_ew_v21'})
    # E3（相手 French Developed_ex_US）
    for K in (3, 5):
        add(f'E3_mom12_K{K}', 'E3', False, 'DXUS22', mom_choose(DXUS22, K, 11, 1), jret, 'fr_dxus', 'dev', extra={'ew': 'C_ew_dxus22'})
    for K in (3, 5):
        add(f'E3_bm_K{K}', 'E3', False, 'F20', val_choose(F20, K, 'bm'), jret, 'fr_dxus', 'dev', rebal=6, extra={'ew': 'C_ew_dxus22'})
    for K in (3, 5):
        add(f'E3_vm_K{K}', 'E3', False, 'F20', vm_choose(F20, K), jret, 'fr_dxus', 'dev', extra={'ew': 'C_ew_dxus22'})
    # E4
    for K in (3, 5):
        add(f'E4_em_mom12_K{K}', 'E4', False, 'EM24', mom_choose(EM24, K, 11, 1), jret, 'jkp_em', 'em', extra={'ew': 'C_ew_em24', 'pub': 1998})
    for K in (3, 5):
        add(f'E4_fr_mom12_K{K}', 'E4', False, 'FRONTIER', mom_choose(FRONTIER, K, 11, 1), jret, 'jkp_fr', 'fr', extra={'pub': 1998})
    add('E4_all_mom12_K5', 'E4', False, 'ALL47', mom_choose(ALL47, 5, 11, 1), jret, 'jkp_world', 'mixed', extra={'pub': 1998})
    add('E4_all_mom12_Q', 'E4', False, 'ALL47', mom_choose(ALL47, -4, 11, 1), jret, 'jkp_world', 'mixed', extra={'pub': 1998})
    # E5（タイミング）
    add('E5_gem', 'E5', False, 'usa/world_ex_us/T-bill', usrow_choose(11, 0, gem=True), jret, 'jkp_dev', 'broad', extra={'timing': True, 'pub': 2013, 'also_world': True})
    add('E5_ctrend_ew', 'E5', False, 'DEV23+T-bill', ctrend_choose(DEV23), jret, 'jkp_dev', 'dev', extra={'timing': True})
    add('E5_mom3_abs', 'E5', False, 'DEV23+T-bill', mom_abs_choose(DEV23, 3), jret, 'jkp_dev', 'dev', extra={'timing': True})
    # E6（French 1975〜・EAFE19）
    frr = {c: W.fr[c]['usd'] for c in EAFE19}
    for K in (3, 5):
        add(f'E6_mom12_K{K}', 'E6', False, 'EAFE19', mom_choose(EAFE19, K, 11, 1, src='fr', retd=frr), fret, 'fr_eafe', 'dev', extra={'ew': 'C_ew_eafe19', 'pub': 1998})
    for K in (3, 5):
        add(f'E6_bm_K{K}', 'E6', False, 'EAFE19', val_choose(EAFE19, K, 'bm', src='fr'), fret, 'fr_eafe', 'dev', rebal=6, extra={'ew': 'C_ew_eafe19', 'pub': 1999})
    for K in (3, 5):
        add(f'E6_vm_K{K}', 'E6', False, 'EAFE19', vm_choose(EAFE19, K, src='fr', retd=frr), fret, 'fr_eafe', 'dev', extra={'ew': 'C_ew_eafe19', 'pub': 2014})
    # E7（地域）
    regr = {g: W.freg[g] for g in ('NA', 'EU', 'JP', 'APxJ')}

    def reg_choose(K):
        def ch(t):
            sc = {g: W.cum(regr[g], t, 11, 1) for g in regr}
            sc = {g: v for g, v in sc.items() if v is not None}
            if len(sc) < 4:
                return None
            return {g: 1 / K for g in top_k(sc, K)}
        return ch
    add('E7_reg4_K1', 'E7', False, 'REG4', reg_choose(1), gret, 'fr_dev', 'broad', extra={'pub': 1998})
    add('E7_reg4_K2', 'E7', False, 'REG4', reg_choose(2), gret, 'fr_dev', 'broad', extra={'pub': 1998})
    # ── 事前登録3（0d292fa）: D 族（配当利回り・結果を見た後）と K 族（CAPE） ──
    def dpM_choose(univ, K):
        def ch(t):
            sc = {c: W.dp_at(c, t) for c in univ if W.elig(c, t)}
            sc = {c: v for c, v in sc.items() if v is not None}
            if len(sc) < 2 * K:
                return None
            return {c: 1 / K for c in top_k(sc, K)}
        return ch

    def eret(a, t):
        if a == 'RF':
            return rfd.get(t)
        return W.etf[a].get(t)
    ex_tks = [tk for tk in ETF if tk != 'SPY']
    for K in (3, 5):
        add(f'D1_f20_dp_K{K}', 'D', False, 'F20', val_choose(F20, K, 'dp'), jret, 'fr_dxus', 'dev', rebal=6, extra={'ew': 'C_ew_dxus22', 'pub': 1992})
    for K in (3, 5):
        add(f'D2_f20_yld_K{K}', 'D', False, 'F20', val_choose(F20, K, 'yld'), jret, 'fr_dxus', 'dev', rebal=6, extra={'ew': 'C_ew_dxus22', 'pub': 1992})
    for K in (3, 5):
        add(f'D3_f20_dpM_K{K}', 'D', False, 'F20', dpM_choose(F20, K), jret, 'fr_dxus', 'dev', extra={'ew': 'C_ew_dxus22', 'pub': 1992})
    for K in (3, 5):
        add(f'D4_eafe_dp_K{K}', 'D', False, 'EAFE19', val_choose(EAFE19, K, 'dp', src='fr'), fret, 'fr_eafe', 'dev', rebal=6, extra={'ew': 'C_ew_eafe19', 'pub': 1992})
    for K in (3, 5):
        add(f'D5_etf_dp_K{K}', 'D', False, 'ETF15（米国外の iShares 国別）', val_choose(ex_tks, K, 'dp', src='etf', cmap=ETF), eret, 'fr_dxus', 'etf',
            rebal=6, extra={'vend': 202512, 'also': ['etf_efa'], 'pub': 1992, 'note': '訓練は ETF の 1997-07〜2006-12（15年に満たない＝C1 は参考）。信託報酬は ETF の値動きに含まれる'})
    for K in (2, 4, 6):
        add(f'D6_f20_dp_K{K}', 'D', False, 'F20', val_choose(F20, K, 'dp'), jret, 'fr_dxus', 'dev', rebal=6, extra={'ew': 'C_ew_dxus22', 'pub': 1992})
    for K in (3, 5):
        add(f'K1_f20_cape_K{K}', 'K', False, 'F20', val_choose(F20, K, 'cape'), jret, 'fr_dxus', 'dev', rebal=6, extra={'ew': 'C_ew_dxus22'})
    for K in (3, 5):
        add(f'K2_v21_cape_K{K}', 'K', False, 'V21', val_choose(V21, K, 'cape'), jret, 'fr_dev', 'dev', rebal=6, extra={'ew': 'C_ew_v21'})
    # ── 事前登録4（18288ce）: I 族（米国の業種の配当利回り）と J 族（実在ETFの分配金） ──
    def ind_choose(n, K):
        tot = W.ind[n][0]

        def ch(t):
            Y = t // 100
            sc = {}
            for col in tot:
                if tot[col].get(t) is None:
                    continue
                v = W.ind_dp(n, col, (Y - 1) * 100 + 12)
                if v is not None:
                    sc[col] = v
            if len(sc) < 2 * K:
                return None
            return {c: 1 / K for c in top_k(sc, K)}
        return ch

    def iret(n):
        tot = W.ind[n][0]
        return lambda a, t: tot[a].get(t)
    add('I1_ind49_dp_K5', 'I', False, 'French 49業種', ind_choose(49, 5), iret(49), 'fr_mkt', 'ind49', rebal=6, extra={'pub': 1992})
    add('I1_ind49_dp_K10', 'I', False, 'French 49業種', ind_choose(49, 10), iret(49), 'fr_mkt', 'ind49', rebal=6, extra={'pub': 1992})
    add('I2_ind12_dp_K3', 'I', False, 'French 12業種', ind_choose(12, 3), iret(12), 'fr_mkt', 'ind12', rebal=6, extra={'pub': 1992})

    def etfdp_choose(tks, K, fr_signal=False, cmap=None):
        cmap = cmap or {}

        def ch(t):
            Y = t // 100
            sc = {}
            for tk in tks:
                if W.etf.get(tk, {}).get(t) is None:  # その月にリターンがある（上場している）ETF だけ
                    continue
                v = W.dp_at(cmap[tk], (Y - 1) * 100 + 12) if fr_signal else W.etf_dp(tk, Y)
                if v is not None:
                    sc[tk] = v
            if len(sc) < 2 * K:
                return None
            return {c: 1 / K for c in top_k(sc, K)}
        return ch
    dev_etf = ex_tks + list(DEV_ETF_X)
    dmap = dict(ETF); dmap.update(DEV_ETF_X)
    jn = '報告（訓練が短いので格付けは参考）'
    for K in (3, 5):
        add(f'J1_em_etf_dp_K{K}', 'J', False, '新興国 iShares 国別ETF', etfdp_choose(EM_ETF, K), eret, 'etf_eem', 'etf_em', rebal=6, extra={'note': jn})
    for K in (3, 5):
        add(f'J2_dev_etf_dp_K{K}', 'J', False, '先進国（米国外）iShares 国別ETF 20本', etfdp_choose(dev_etf, K), eret, 'etf_efa', 'etf', rebal=6, extra={'note': jn, 'also': ['fr_dxus']})
    add('J3_dev_etf_frdp_K3', 'J', False, '先進国（米国外）iShares 国別ETF 20本・信号は French', etfdp_choose(dev_etf, 3, fr_signal=True, cmap=dmap), eret, 'etf_efa', 'etf',
        rebal=6, extra={'note': jn, 'vend': 202512, 'also': ['fr_dxus']})
    # ── 事前登録5（4e35f52）: G 族（配当利回り＋勢い） ──
    def dpmom_choose(univ, K):
        def ch(t):
            mo, dp = {}, {}
            for c in univ:
                if not W.elig(c, t):
                    continue
                m = W.cum(R.get(c, {}), t, 11, 1)
                v = W.dp_at(c, t)
                if m is not None and v is not None:
                    mo[c], dp[c] = m, v
            if len(mo) < 2 * K:
                return None
            pm, pv = pct_ranks(mo), pct_ranks(dp)
            ks = sorted(mo, key=lambda c: (-(pm[c] + pv[c]) / 2, -pm[c], c))
            return {c: 1 / K for c in ks[:K]}
        return ch
    for K in (3, 5):
        add(f'G1_f20_dpmom_K{K}', 'G', False, 'F20', dpmom_choose(F20, K), jret, 'fr_dxus', 'dev', extra={'ew': 'C_ew_dxus22'})
    # 対照
    add('C_ew_dev23', 'CONTROL', False, 'DEV23', ew_choose(DEV23), jret, 'jkp_dev', 'dev')
    add('C_ew_v21', 'CONTROL', False, 'V21', ew_choose(V21), jret, 'jkp_dev', 'dev')
    add('C_ew_dxus22', 'CONTROL', False, 'DXUS22', ew_choose(DXUS22), jret, 'fr_dxus', 'dev')
    add('C_ew_em24', 'CONTROL', False, 'EM24', ew_choose(EM24), jret, 'jkp_em', 'em')
    add('C_ew_eafe19', 'CONTROL', False, 'EAFE19', ew_choose(EAFE19, src='fr', retd=frr), fret, 'fr_eafe', 'dev')
    add('C_usa', 'CONTROL', False, 'usa', lambda t: {'usa': 1.0}, jret, 'jkp_dev', 'broad')
    make_strategies.helpers = {'mom': mom_choose, 'val': val_choose, 'vm': vm_choose, 'usrow': usrow_choose, 'ew': ew_choose}
    # 事前登録2（c7d616e）: JKP の developed は米国抜きだった → 相手（ii）を French Developed へ。
    # 第1回の相手（JKP developed＝先進国・米国抜き）の結果は as_registered として残す
    for d in ST:
        if d['bench'] == 'jkp_dev':
            d['asreg'] = 'jkp_dev'
            d['bench'] = 'fr_dev'
    return ST


def benches(W):
    return {'jkp_dev': W.reg['developed'], 'jkp_world': W.reg['world'], 'jkp_em': W.reg['emerging'], 'jkp_fr': W.reg['frontier'],
            'jkp_usa': W.ret['usa'], 'fr_dxus': W.freg['dxus'], 'fr_dev': W.freg['dev'], 'fr_eafe': W.fr['_eafe'],
            'fr_mkt': M.ff_factors()['mkt'], 'etf_efa': W.etf['EFA'], 'etf_eem': W.etf['EEM']}


def month_grid(W):
    return months_between(197501, 202608)


# ───────────────────────── 点検（比較の数字は出さない） ─────────────────────────
def check():
    W = World()
    print('JKP 国:', len(W.ret), '地域:', {k: (min(v), max(v)) for k, v in W.reg.items()})
    for c in ('usa', 'jpn', 'gbr', 'irl', 'isr'):
        print(c, min(W.ret[c]), max(W.ret[c]), 'n≥20 の月', sum(1 for v in W.n[c].values() if v and v >= NMIN))
    print('French 国:', [c for c in F20], 'EAFE', min(W.fr['_eafe']), max(W.fr['_eafe']))
    for c in ('jpn', 'gbr', 'deu'):
        d = W.fr[c]
        print(c, 'usd', min(d['usd']), max(d['usd']), 'bm 1990,1991,2025', d['bm'].get(1990), d['bm'].get(1991), d['bm'].get(2025),
              'px 2025-12', round(W.px[c].get(202512, float('nan')), 3), 'dp 2024-12', W.dp_at(c, 202412), 'yld 2025', d['yld'].get(2025))
    print('US bm 1990/2000/2025', W.us['bm'].get(1990), W.us['bm'].get(2000), W.us['bm'].get(2025), 'ep 2025', W.us['ep'].get(2025),
          'cep 2025', W.us['cep'].get(2025), 'dp 2024-12', W.dp_at('usa', 202412), 'US tot', min(W.us['tot']), max(W.us['tot']))
    print('French 地域:', {k: (min(v), max(v)) for k, v in W.freg.items()})
    ST = make_strategies(W)
    print('戦略の数', len(ST), '族', sorted(set(s['family'] for s in ST)))
    # 信号が作れるか（リターンの比較はしない）
    t = 200012
    for s in ST[:8]:
        print(s['id'], s['choose'](t if s['rebal'] is None else 200006))


# ───────────────────────── 測定と判定 ─────────────────────────
def git_sha(path):
    try:
        return subprocess.check_output(['git', 'log', '-1', '--format=%H', '--', path], cwd=M.BASE, text=True).strip() or None
    except Exception:  # noqa
        return None


def cost_of(cls, hold):
    """(売買の単価, 信託報酬の差) — 国ごとに違う 'mixed' は保有の重みで平均"""
    if cls != 'mixed':
        return COST[cls]
    cp = er = n = 0.0
    for w in hold.values():
        for a, x in w.items():
            k = 'dev' if a in DEV23 else ('em' if a in EM24 else 'fr')
            cp += x * COST[k][0]; er += x * COST[k][1]
        n += 1
    return (cp / n, er / n) if n else COST['dev']


def cheap_er(cls, er):
    return 0.0010 if er > 0 else 0.0


def window_to(b, r):
    return {k: v for k, v in b.items() if k in r}


def cal_years(r, b, a=M.HOLD_START):
    out = {}
    ks = sorted(k for k in set(r) & set(b) if k >= a)
    for y in sorted(set(k // 100 for k in ks)):
        m = [k for k in ks if k // 100 == y]
        if len(m) < 12:
            continue
        gs = math.prod(1 + r[k] for k in m) - 1
        gb = math.prod(1 + b[k] for k in m) - 1
        out[y] = [round(gs * 100, 1), round(gb * 100, 1), round((gs - gb) * 100, 1)]
    return out


def hold_summary(hold, a=M.HOLD_START, z=None):
    ms = [k for k in hold if k >= a and (z is None or k <= z)]
    if not ms:
        return None
    cnt, wt = {}, {}
    for k in ms:
        for x, w in hold[k].items():
            cnt[x] = cnt.get(x, 0) + 1; wt[x] = wt.get(x, 0) + w
    top = sorted(cnt, key=lambda x: -wt[x])[:10]
    return {'months': len(ms), 'avg_weight': {x: round(wt[x] / len(ms), 3) for x in top},
            'share_months_held': {x: round(cnt[x] / len(ms), 3) for x in top}}


def evaluate_one(s, r, turn, hold, ren, b, B, series, rfd):
    out = {'id': s['id'], 'family': s['family'], 'primary': s['primary'], 'universe': s['universe'], 'benchmark': s['bench'],
           'rebalance': 'annual_june' if s['rebal'] == 6 else 'monthly', 'months': len(r),
           'first': min(r) if r else None, 'last': max(r) if r else None, 'renormalized_months': ren}
    if len(r) < 24:
        out['note'] = 'データ不足'
        return out
    ms = sorted(r)
    ann_turn = S.mean([turn.get(k, 0.0) for k in ms]) * 12
    cpu, er = cost_of(s['cost'], hold)
    net = M.apply_cost(M.apply_cost(r, ann_turn, cpu), er, 1.0)
    net_cheap = M.apply_cost(M.apply_cost(r, ann_turn, cpu), cheap_er(s['cost'], er), 1.0)
    out['cost'] = {'class': s['cost'], 'annual_oneway_turnover': round(ann_turn, 3), 'cost_per_unit': round(cpu, 5),
                   'er_diff': round(er, 5), 'annual_drag_pct': round((ann_turn * cpu + er) * 100, 3)}
    st = {'full': M.excess_stats(r, b), 'train': M.excess_stats(r, b, z=M.TRAIN_END), 'hold': M.excess_stats(r, b, a=M.HOLD_START),
          'recent': M.excess_stats(r, b, a=M.RECENT_START), 'full_net': M.excess_stats(net, b),
          'hold_net': M.excess_stats(net, b, a=M.HOLD_START), 'hold_net_cheapER': M.excess_stats(net_cheap, b, a=M.HOLD_START)}
    if s.get('pub'):
        st['post_pub'] = M.excess_stats(r, b, a=s['pub'] * 100 + 1)
        st['post_pub_from'] = s['pub']
    out['stats'] = st
    out['roll20'] = M.rolling(r, b, 20)
    out['roll20_net'] = M.rolling(net, b, 20)
    out['dca20'] = M.dca(r, b, 20)
    bw = window_to(b, r)
    out['maxdd'] = {'s': round(M.maxdd(r) * 100, 1), 'b': round(M.maxdd(bw) * 100, 1)}
    out['sharpe'] = {'train': [M.sharpe(r, rfd, z=M.TRAIN_END), M.sharpe(bw, rfd, z=M.TRAIN_END)],
                     'hold': [M.sharpe(r, rfd, a=M.HOLD_START), M.sharpe(bw, rfd, a=M.HOLD_START)]}
    if s.get('ew') and s['ew'] in series:
        e = series[s['ew']]
        out['vs_ew'] = {'full': M.excess_stats(r, e), 'hold': M.excess_stats(r, e, a=M.HOLD_START)}
    us = B['jkp_usa']
    out['vs_us'] = {'full': M.excess_stats(r, us), 'hold': M.excess_stats(r, us, a=M.HOLD_START)}
    for bk in s.get('also', []):
        out.setdefault('vs_other', {})[bk] = {'full': M.excess_stats(r, B[bk]), 'hold': M.excess_stats(r, B[bk], a=M.HOLD_START),
                                              'recent': M.excess_stats(r, B[bk], a=M.RECENT_START)}
    if s.get('note'):
        out['note'] = s['note']
    if s.get('also_world'):
        out['vs_world'] = {'full': M.excess_stats(r, B['jkp_world']), 'hold': M.excess_stats(r, B['jkp_world'], a=M.HOLD_START)}
    out['hold_summary'] = hold_summary(hold)
    out['train_summary'] = hold_summary(hold, a=0, z=M.TRAIN_END)
    out['_net'] = net
    return out


def run_etf(W, B, rfd):
    """R 族: iShares 国別ETF で同じ規則を再生（報告のみ）"""
    er = W.etf
    tks = list(ETF)
    h = make_strategies.helpers

    def eret(a, t):
        if a == 'RF':
            return rfd.get(t)
        return er[a].get(t)
    months = months_between(199604, YAHOO_LAST)
    VEND = 202512
    defs = [('R_etf_mom12_K3', h['mom'](tks, 3, 11, 1, src='etf', retd=er), None, 'etf', None),
            ('R_etf_mom12_K5', h['mom'](tks, 5, 11, 1, src='etf', retd=er), None, 'etf', None),
            ('R_etf_bm_K3', h['val'](tks, 3, 'bm', src='etf', cmap=ETF), 6, 'etf', VEND),
            ('R_etf_bm_K5', h['val'](tks, 5, 'bm', src='etf', cmap=ETF), 6, 'etf', VEND),
            ('R_etf_vm_K3', h['vm'](tks, 3, src='etf', retd=er, cmap=ETF), None, 'etf', VEND),
            ('R_etf_vm_K5', h['vm'](tks, 5, src='etf', retd=er, cmap=ETF), None, 'etf', VEND),
            ('R_etf_usrow', h['usrow'](11, 0, legs=('SPY', 'EFA'), retf=eret), None, 'etf_broad', None),
            ('R_etf_ew16', h['ew'](tks, src='etf', retd=er), None, 'etf', None)]
    out = []
    ser = {}
    for id_, ch, rb, cls, vend in defs:
        r, turn, hold, ren = backtest(eret, ch, months, rb)
        if vend:
            r = {k: v for k, v in r.items() if k <= vend}
        ser[id_] = r
        ms = sorted(r)
        ann_turn = S.mean([turn.get(k, 0.0) for k in ms]) * 12 if ms else 0
        cpu = COST[cls][0]
        net = M.apply_cost(r, ann_turn, cpu)
        d = {'id': id_, 'family': 'R', 'primary': False, 'first': ms[0] if ms else None, 'last': ms[-1] if ms else None,
             'cost': {'annual_oneway_turnover': round(ann_turn, 3), 'cost_per_unit': cpu, 'note': '信託報酬は ETF の値動きに含まれる'}}
        bs = {'fr_dev': B['fr_dev'], 'jkp_dev_exUS': B['jkp_dev'], 'acwi': er['ACWI'], 'spy': er['SPY']}
        d['vs'] = {}
        for bn, b in bs.items():
            d['vs'][bn] = {'pre_1997_2006': M.excess_stats(r, b, z=M.TRAIN_END), 'hold': M.excess_stats(r, b, a=M.HOLD_START),
                           'hold_net': M.excess_stats(net, b, a=M.HOLD_START), 'recent': M.excess_stats(r, b, a=M.RECENT_START)}
        d['vs']['ew16'] = {'hold': M.excess_stats(r, ser.get('R_etf_ew16', {}), a=M.HOLD_START)} if 'R_etf_ew16' in ser else None
        dv = d['vs']['fr_dev']
        g, c = M.grade(M.excess_stats(r, B['fr_dev']), dv['pre_1997_2006'], dv['hold'], M.rolling(r, B['fr_dev'], 20),
                       cost_hold=dv['hold_net'])
        d['grade_reference_only'] = g
        d['criteria'] = c
        d['note'] = '報告のみ: 訓練は ETF の最初の10年（1997〜2006）で15年に満たない。格付けは参考'
        d['hold_summary'] = hold_summary(hold)
        d['cal_years_vs_fr_dev'] = cal_years(r, B['fr_dev'])
        out.append(d)
    # 等分との差（ew16 が最後に計算されるので後から）
    for d in out:
        if d['id'] != 'R_etf_ew16':
            d['vs']['ew16'] = {'hold': M.excess_stats(ser[d['id']], ser['R_etf_ew16'], a=M.HOLD_START)}
    return out, er


def sanity(W, B, er):
    ff = M.ff_factors()
    mk = ff['mkt']
    out = {'french_mkt_cagr_full': round(M.cagr(mk) * 100, 2), 'french_mkt_cagr_2007': round(M.cagr(M.window(mk, M.HOLD_START)) * 100, 2),
           'french_mkt_span': [min(mk), max(mk)]}
    out['jkp_usa_vs_french_mkt'] = M.excess_stats(B['jkp_usa'], mk)
    out['us_synth_vs_french_mkt'] = M.excess_stats(W.us['tot'], mk)
    ks = sorted(set(W.us['tot']) & set(mk))
    out['us_synth_corr'] = round(M.corr([W.us['tot'][k] for k in ks], [mk[k] for k in ks]), 4)
    out['french_vs_jkp_country'] = {}
    for c in F20:
        a, b = W.fr[c]['usd'], W.ret[c]
        ks = sorted(k for k in set(a) & set(b) if 198601 <= k <= 202512)
        if len(ks) < 24:
            continue
        out['french_vs_jkp_country'][c] = {'corr': round(M.corr([a[k] for k in ks], [b[k] for k in ks]), 3),
                                           'cagr_fr': round(M.cagr([a[k] for k in ks]) * 100, 2), 'cagr_jkp': round(M.cagr([b[k] for k in ks]) * 100, 2)}
    xs, ys = [], []
    for c in F20:
        for Y, v in W.fr[c]['yld'].items():
            d = W.dp_at(c, (Y - 1) * 100 + 12)
            if d is not None and v is not None:
                xs.append(v); ys.append(d)
    out['yld_table_vs_dp_ret'] = {'n': len(xs), 'corr': round(M.corr(xs, ys), 3), 'mean_table': round(S.mean(xs) * 100, 2), 'mean_ret': round(S.mean(ys) * 100, 2)}
    ks = sorted(k for k in set(er['EWJ']) & set(W.ret['jpn']) if k <= 202512)
    out['EWJ_vs_jkp_jpn'] = {'from': ks[0], 'to': ks[-1], 'cagr_etf': round(M.cagr([er['EWJ'][k] for k in ks]) * 100, 2),
                             'cagr_jkp': round(M.cagr([W.ret['jpn'][k] for k in ks]) * 100, 2)}
    ks = sorted(k for k in set(er['SPY']) & set(mk) if k <= 202512)
    out['SPY_vs_french_mkt'] = {'from': ks[0], 'to': ks[-1], 'cagr_spy': round(M.cagr([er['SPY'][k] for k in ks]) * 100, 2),
                                'cagr_mkt': round(M.cagr([mk[k] for k in ks]) * 100, 2)}
    dv = B['jkp_dev']
    out['jkp_developed_is_ex_us'] = {'french_dev_cagr_2007_2025': round(M.cagr([B['fr_dev'][k] for k in B['fr_dev'] if 200701 <= k <= 202512]) * 100, 2),
                                     'french_dxus_cagr_2007_2025': round(M.cagr([B['fr_dxus'][k] for k in B['fr_dxus'] if 200701 <= k <= 202512]) * 100, 2),
                                     'jkp_dev_cagr_2007_2025': round(M.cagr([dv[k] for k in dv if 200701 <= k <= 202512]) * 100, 2),
                                     'jkp_usa_cagr_2007_2025': round(M.cagr([B['jkp_usa'][k] for k in B['jkp_usa'] if 200701 <= k <= 202512]) * 100, 2),
                                     'note': 'JKP の地域 developed は米国を含まない（n_countries 20〜22）。事前登録2 で相手（ii）を French Developed へ訂正'}
    out['jkp_developed_2008'] = round((math.prod(1 + dv[k] for k in dv if k // 100 == 2008) - 1) * 100, 1)
    out['jkp_developed_cagr_1986_2025'] = round(M.cagr(dv) * 100, 2)
    out['look_ahead'] = '信号は choose(t) の中で ym_add(t, -k)（k≥0）の値と、年 Y の表（Y−1年12月末）を Y年6月末以降にだけ使う。リターンは backtest が t+1 の月を当てる'
    return out


def post_hoc_reports(W, B, series, runs, rfd):
    """事前登録3 の X1〜X4（事後・格付けしない）"""
    out = {}
    dev, na, dx = B['fr_dev'], W.freg['NA'], W.freg['dxus']
    usa = B['jkp_usa']
    dp3 = series.get('D1_f20_dp_K3', {})
    # X1: 米国の重み w(t) を過去36か月の回帰で推定（月末 t まで）→ t+1 に w·米国 + (1−w)·dp3
    x1, ws = {}, {}
    ks = sorted(set(dev) & set(na) & set(dx))
    for i, t in enumerate(ks):
        win = ks[max(0, i - 35):i + 1]
        if len(win) < 36:
            continue
        num = sum((dev[k] - dx[k]) * (na[k] - dx[k]) for k in win)
        den = sum((na[k] - dx[k]) ** 2 for k in win)
        if den <= 0:
            continue
        w = min(1.0, max(0.0, num / den))
        t1 = ym_add(t, 1)
        if t1 in usa and t1 in dp3:
            x1[t1] = w * usa[t1] + (1 - w) * dp3[t1]
            ws[t1] = w
    def pack(r, b, label):
        return {'label': label, 'full': M.excess_stats(r, b), 'train': M.excess_stats(r, b, z=M.TRAIN_END),
                'hold': M.excess_stats(r, b, a=M.HOLD_START), 'recent': M.excess_stats(r, b, a=M.RECENT_START),
                'roll20': M.rolling(r, b, 20), 'dca20': M.dca(r, b, 20)}
    out['X1_us_anchor_dp3'] = pack(x1, dev, '米国は推定した市場の重みのまま・米国外だけ D1_f20_dp_K3 vs French Developed（事後・格付けなし）')
    if ws:
        wv = [ws[k] for k in sorted(ws)]
        out['X1_us_anchor_dp3']['us_weight'] = {'first': [min(ws), round(wv[0], 3)], 'median': round(S.median(wv), 3),
                                                'last': [max(ws), round(wv[-1], 3)], 'min': round(min(wv), 3), 'max': round(max(wv), 3)}
        # 同じ重みで米国外を French Developed_ex_US のまま持った姿（重みの推定の誤差を見る）
        base = {k: ws[k] * usa[k] + (1 - ws[k]) * dx[k] for k in ws if k in dx}
        out['X1_us_anchor_dp3']['same_weight_with_index_vs_dev'] = M.excess_stats(base, dev)
    # X2: 切替（P7）で米国外の月だけ dp3
    p7 = runs.get('P7_usrow_12')
    if p7:
        x2 = {}
        for k, h in p7[2].items():
            if 'usa' in h:
                x2[k] = usa.get(k)
            elif k in dp3:
                x2[k] = dp3[k]
        x2 = {k: v for k, v in x2.items() if v is not None}
        out['X2_usrow_dp3'] = pack(x2, dev, '米国と米国外の切替（12-0）で米国外の月だけ D1_f20_dp_K3 vs French Developed（事後・格付けなし）')
        out['X2_usrow_dp3']['months_in_dp3_hold'] = sum(1 for k in x2 if k >= M.HOLD_START and 'usa' not in p7[2].get(k, {}))
    # X3: フロンティアからジンバブエを除く
    R = W.ret
    fr_ex = [c for c in FRONTIER if c != 'zwe']
    months = months_between(197501, 202608)
    for K in (3, 5):
        def ch(t, K=K):
            sc = {c: W.cum(R.get(c, {}), t, 11, 1) for c in fr_ex if W.elig(c, t)}
            sc = {c: v for c, v in sc.items() if v is not None}
            if len(sc) < 2 * K:
                return None
            return {c: 1 / K for c in top_k(sc, K)}
        r, turn, hold, ren = backtest(lambda a, t: R[a].get(t), ch, months)
        out[f'X3_frontier_ex_zwe_K{K}'] = pack(r, B['jkp_fr'], f'フロンティアの勢い上位{K}（ジンバブエ除外）vs JKP frontier vw（相手にはジンバブエが入っている可能性）（事後・格付けなし）')
        out[f'X3_frontier_ex_zwe_K{K}']['annual_oneway_turnover'] = round(S.mean([turn.get(k, 0) for k in r]) * 12, 2) if r else None
    # X4: dp3 と米国
    out['X4_dp3_vs_us'] = pack(dp3, usa, 'D1_f20_dp_K3 vs 米国（JKP usa）（事後・格付けなし）')
    out['X4b_dp3_vs_dev'] = pack(dp3, dev, 'D1_f20_dp_K3 vs French Developed（米国込み）（事後・格付けなし）')
    return out


def diagnostics(W, B, series, runs, rfd, ST):
    """事前登録4 の Q1〜Q5（事後・格付けしない）"""
    out = {}
    b = B['fr_dxus']
    r, turn, hold, ren = runs['D1_f20_dp_K3']
    ms = [k for k in sorted(r) if k >= M.HOLD_START and k in b]
    con = {}
    for k in ms:
        for c, w in hold[k].items():
            con[c] = con.get(c, 0.0) + w * (W.ret[c][k] - b[k])
    out['Q1_contribution_hold'] = {'label': 'D1_f20_dp_K3 の保有期間の超過（算術・年率%）の国ごとの寄与（対 French Developed_ex_US）',
                                   'by_country': {c: round(v / len(ms) * 12 * 100, 2) for c, v in sorted(con.items(), key=lambda x: -x[1])},
                                   'total': round(sum(con.values()) / len(ms) * 12 * 100, 2)}
    h = make_strategies.helpers
    months = months_between(197501, 202608)
    jret = lambda a, t: W.ret[a].get(t) if a in W.ret else None
    loo = {}
    for x in ('nzl', 'aus', 'nor', 'fin', 'ita'):
        rr, *_ = backtest(jret, h['val']([c for c in F20 if c != x], 3, 'dp'), months, 6)
        st = M.excess_stats(rr, b, a=M.HOLD_START)
        sf = M.excess_stats(rr, b)
        loo[x] = {'hold_ex': st and st['ex_ann'], 'hold_t': st and st['t'], 'full_ex': sf and sf['ex_ann'], 'full_t': sf and sf['t']}
    out['Q2_leave_one_out'] = {'label': 'D1_f20_dp_K3 から一か国を除いた版（対 French Developed_ex_US）', 'by_excluded': loo}
    e15 = [ETF[tk] for tk in ETF if tk != 'SPY']
    rr, *_ = backtest(jret, h['val'](e15, 3, 'dp'), months, 6)
    out['Q3_etf15_universe_index'] = {'label': 'D5 と同じ15か国に限った D1 の規則（JKP の指数リターン）',
                                      'hold': M.excess_stats(rr, b, a=M.HOLD_START), 'full': M.excess_stats(rr, b), 'train': M.excess_stats(rr, b, z=M.TRAIN_END)}
    # Q4: 現地通貨建て
    zi = zipfile.ZipFile(io.BytesIO(M.get('https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_International_Indices.zip',
                                          name='fr_F-F_International_Indices.zip')))
    a = parse_fr_dat(zi.read('Ind_all.Dat').decode('latin-1'))
    sec = a[('LOC', 'NR', 'm')]
    eafe_loc = {k: v[sec['cols'].index('Mkt')] / 100 for k, v in sec['data'].items() if v[sec['cols'].index('Mkt')] is not None}
    floc = lambda a_, t: W.fr[a_]['loc'].get(t)
    rl, *_ = backtest(floc, h['val'](EAFE19, 3, 'dp', src='fr'), months, 6)
    ru = series['D4_eafe_dp_K3']
    out['Q4_currency'] = {'label': 'D4_eafe_dp_K3 を現地通貨建てで（相手 Ind_all 現地通貨）。ドル建てとの差＝通貨の寄与',
                          'local_hold': M.excess_stats(rl, eafe_loc, a=M.HOLD_START), 'local_full': M.excess_stats(rl, eafe_loc),
                          'usd_hold': M.excess_stats(ru, B['fr_eafe'], a=M.HOLD_START), 'usd_full': M.excess_stats(ru, B['fr_eafe'])}
    # Q5: CAPM α
    def capm(s_, b_, a_=None, z_=None):
        ks = sorted(k for k in set(s_) & set(b_) & set(rfd) if (a_ is None or k >= a_) and (z_ is None or k <= z_))
        y = [s_[k] - rfd[k] for k in ks]; x = [b_[k] - rfd[k] for k in ks]
        mx, my = S.mean(x), S.mean(y)
        beta = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / sum((xi - mx) ** 2 for xi in x)
        al = [yi - beta * xi for xi, yi in zip(x, y)]
        t = M.nw_t(al)
        return {'from': ks[0], 'to': ks[-1], 'alpha_ann': round(S.mean(al) * 12 * 100, 2), 't': round(t, 2) if t else None, 'beta': round(beta, 2)}
    d1 = series['D1_f20_dp_K3']
    out['Q5_capm_alpha'] = {'label': 'D1_f20_dp_K3 の β を除いた α（対 French Developed_ex_US）',
                            'full': capm(d1, b), 'train': capm(d1, b, z_=M.TRAIN_END), 'hold': capm(d1, b, a_=M.HOLD_START),
                            'vs_fr_dev_hold': capm(d1, B['fr_dev'], a_=M.HOLD_START), 'vs_us_hold': capm(d1, B['jkp_usa'], a_=M.HOLD_START)}
    # 事前登録5 の Q6〜Q8
    terc = {'top': {}, 'mid': {}, 'bot': {}}
    for Y in range(1986, 2026):
        t0 = Y * 100 + 6
        el = [c for c in F20 if W.elig(c, t0)]
        sc = {c: W.label('dp', c, Y) for c in el}
        sc = {c: v for c, v in sc.items() if v is not None}
        if len(sc) < 6:
            continue
        ks = sorted(sc, key=lambda c: (-sc[c], c))
        n = len(ks)
        grp = {'top': ks[:round(n / 3)], 'mid': ks[round(n / 3):round(2 * n / 3)], 'bot': ks[round(2 * n / 3):]}
        for g, cs in grp.items():
            for m in months_between(ym_add(t0, 1), ym_add(t0, 12)):
                xs = [W.ret[c].get(m) for c in cs if W.ret[c].get(m) is not None]
                if xs:
                    terc[g][m] = S.mean(xs)  # 各月等分（簡便・報告のみ）
    tq = {}
    for g, r_ in terc.items():
        tq[g] = {'full': M.excess_stats(r_, b), 'train': M.excess_stats(r_, b, z=M.TRAIN_END), 'hold': M.excess_stats(r_, b, a=M.HOLD_START)}
    ls = {k: terc['top'][k] - terc['bot'][k] for k in terc['top'] if k in terc['bot']}
    zero = {k: 0.0 for k in ls}
    tq['top_minus_bot'] = {'full': M.excess_stats(ls, zero), 'train': M.excess_stats(ls, zero, z=M.TRAIN_END), 'hold': M.excess_stats(ls, zero, a=M.HOLD_START)}
    out['Q6_terciles'] = {'label': 'F20 を配当利回りで三分位（毎月等分に戻す簡便版）・対 French Developed_ex_US。上−下は相手なしの差', 'groups': tq}
    sub = {}
    for sid, bk in (('D1_f20_dp_K3', 'fr_dxus'), ('D4_eafe_dp_K3', 'fr_eafe')):
        rr, bb = series[sid], B[bk]
        sub[sid] = {}
        for a_ in range(1976, 2026, 5):
            st = M.excess_stats(rr, bb, a=a_ * 100 + 1, z=(a_ + 4) * 100 + 12)
            if st:
                sub[sid][f'{a_}-{a_ + 4}'] = [st['ex_ann'], st['t'], st['cagr_diff']]
    out['Q7_subperiods'] = {'label': '5年ごとの超過 [算術%/年, t, 幾何差]', 'by': sub}
    rr = series['D1_f20_dp_K3']
    r_ex = {k: v for k, v in rr.items() if k // 100 != 2025}
    out['Q8_ex_2025'] = {'label': 'D1_f20_dp_K3 の保有期間（2025年を除く）', 'hold_ex_2025': M.excess_stats(r_ex, b, a=M.HOLD_START),
                         'hold_all': M.excess_stats(rr, b, a=M.HOLD_START)}
    return out


def main():
    W = World()
    rfd = rf()
    B = benches(W)
    ST = make_strategies(W)
    months = month_grid(W)
    # 1) 全戦略の系列
    runs, series = {}, {}
    order = [s for s in ST if s['family'] == 'CONTROL'] + [s for s in ST if s['family'] != 'CONTROL']
    for s in order:
        r, turn, hold, ren = backtest(s['retf'], s['choose'], months, s['rebal'])
        if s.get('vend'):
            r = {k: v for k, v in r.items() if k <= s['vend']}
            hold = {k: v for k, v in hold.items() if k <= s['vend']}
        runs[s['id']] = (r, turn, hold, ren)
        series[s['id']] = r
        print(s['id'], len(r), min(r) if r else None, max(r) if r else None, flush=True)
    # 2) 測る
    res = {}
    for s in order:
        r, turn, hold, ren = runs[s['id']]
        res[s['id']] = evaluate_one(s, r, turn, hold, ren, B[s['bench']], B, series, rfd)
    # 3) C5（P1/P2 は E4 の EM・フロンティア）
    for s in ST:
        if s.get('c5'):
            units = {}
            for u in s['c5']:
                st = res[u].get('stats', {})
                f, h = st.get('full'), st.get('hold')
                units[u] = {'full_ex_ann': f and f['ex_ann'], 'full_t': f and f['t'], 'hold_ex_ann': h and h['ex_ann']}
            pos = sum(1 for v in units.values() if v['full_ex_ann'] is not None and v['full_ex_ann'] > 0)
            res[s['id']]['repl'] = {'regions': len(units), 'positive': pos, 'units': units}
    # 4) 族ごとの Holm（保有期間・費用前・t≤0 は p=1）
    fams = {}
    for s in ST:
        if s['family'] == 'CONTROL':
            continue
        h = res[s['id']].get('stats', {}).get('hold')
        p = h['p'] if h and h['t'] is not None and h['t'] > 0 else 1.0
        fams.setdefault(s['family'], {})[s['id']] = p
    holm = {f: M.holm(v) for f, v in fams.items()}
    # 4b) 第1回の相手（JKP developed＝先進国・米国抜き）でも測って残す（事前登録2）
    ar, ar_p = {}, {}
    for s in ST:
        if not s.get('asreg'):
            continue
        r, turn, hold, ren = runs[s['id']]
        ar[s['id']] = evaluate_one(s, r, turn, hold, ren, B[s['asreg']], B, series, rfd)
        if s['family'] != 'CONTROL':
            h = ar[s['id']].get('stats', {}).get('hold')
            ar_p.setdefault(s['family'], {})[s['id']] = h['p'] if h and h['t'] is not None and h['t'] > 0 else 1.0
    ar_holm = {f: M.holm(v) for f, v in ar_p.items()}
    for sid, d in ar.items():
        st = d.get('stats')
        if not st:
            continue
        fam = res[sid]['family']
        hp = ar_holm.get(fam, {}).get(sid)
        sp = None
        sdef = next(x for x in ST if x['id'] == sid)
        if sdef.get('timing'):
            sp = {'train': tuple(d['sharpe']['train']), 'hold': tuple(d['sharpe']['hold'])}
        g, c = M.grade(st['full'], st['train'], st['hold'], d['roll20'], cost_hold=st['hold_net'], repl=res[sid].get('repl'),
                       family_holm_p=hp, sharpe_pair=sp, leveraged_or_timing=bool(sdef.get('timing')))
        res[sid]['as_registered_vs_dev_exUS'] = {
            'benchmark': 'JKP developed vw ＝ 先進国（米国抜き・22か国）＋RF。第1回の相手（事前登録 15ef00b）。主の格付けではない',
            'full': st['full'], 'train': st['train'], 'hold': st['hold'], 'hold_net': st['hold_net'], 'roll20': d['roll20'],
            'family_holm_p': hp, 'grade': g, 'criteria': c}
        wd = B['jkp_world']
        res[sid]['vs_jkp_world'] = {'full': M.excess_stats(series[sid], wd), 'hold': M.excess_stats(series[sid], wd, a=M.HOLD_START)}
    # 5) 判定
    for s in ST:
        d = res[s['id']]
        st = d.get('stats')
        if not st:
            d['grade'] = 'C'; d['criteria'] = None
            continue
        hp = holm.get(s['family'], {}).get(s['id'])
        d['family_holm_p'] = hp
        sp = None
        if s.get('timing'):
            sp = {'train': tuple(d['sharpe']['train']), 'hold': tuple(d['sharpe']['hold'])}
        g, c = M.grade(st['full'], st['train'], st['hold'], d['roll20'], cost_hold=st['hold_net'], repl=d.get('repl'),
                       family_holm_p=hp, sharpe_pair=sp, leveraged_or_timing=bool(s.get('timing')))
        d['grade'] = g
        d['criteria'] = c
        d['grade_label'] = {'P': '主', 'CONTROL': '対照（候補ではない）',
                            'D': '探索（結果を見た後・保有期間は新しい証拠ではない）', 'K': '探索（結果を見た後に足した物差し）',
                            'I': '探索（結果を見た後・独立の単位での再現）', 'J': '報告（実在ETF・訓練が短いので格付けは参考）',
                            'G': '探索（結果を見た後）'}.get(s['family'], '探索')
        if s['family'] == 'P' or g in ('S', 'A', 'B'):
            d['cal_years_hold'] = cal_years(series[s['id']], B[s['bench']])
    for d in res.values():
        d.pop('_net', None)
    # 5b) 事前登録3 の X（事後・格付けしない）
    xr = post_hoc_reports(W, B, series, runs, rfd)
    xr.update(diagnostics(W, B, series, runs, rfd, ST))
    # C5 の単位のうちフロンティアはジンバブエ（公定レートのハイパーインフレ）で汚れている → 除いた版でも符号を確かめて記録（判定は登録どおり）
    for sid, K in (('P1_mom12_K3', 3), ('P2_mom12_K5', 5)):
        x3 = xr.get(f'X3_frontier_ex_zwe_K{K}', {}).get('full')
        res[sid]['repl_note'] = ('フロンティアの単位（E4_fr）はジンバブエの非現実的なドル建てリターン（月+100%超）で汚れている。'
                                 f'ジンバブエを除いた版の全期間の超過 {x3 and x3["ex_ann"]}%/年（正負は同じ）')
    res['E4_fr_mom12_K3']['invalid_note'] = res['E4_fr_mom12_K5']['invalid_note'] = (
        '無効: 勝ちのほぼ全部がジンバブエ（2006〜2008・2020〜2024 のハイパーインフレを公定レートでドルに直した月+100〜180%）。'
        '実際には買えない。ジンバブエ抜きは post_hoc_reports_not_graded の X3')
    # 6) ETF の再生（報告）
    etf, er = run_etf(W, B, rfd)
    # 7) 点検
    san = sanity(W, B, er)
    tested = [res[s['id']] for s in ST] + etf
    summ = []
    for d in tested:
        st = d.get('stats') or {}
        g = d.get('grade', d.get('grade_reference_only'))
        h = st.get('hold') or (d.get('vs', {}).get('fr_dev', {}) or {}).get('hold')
        f = st.get('full')
        summ.append({'id': d['id'], 'family': d['family'], 'grade': g, 'full_ex': f and f['ex_ann'], 'full_t': f and f['t'],
                     'train_ex': st.get('train') and st['train']['ex_ann'], 'train_t': st.get('train') and st['train']['t'],
                     'hold_ex': h and h['ex_ann'], 'hold_t': h and h['t'], 'hold_cagr_diff': h and h['cagr_diff'],
                     'hold_net_ex': st.get('hold_net') and st['hold_net']['ex_ann'],
                     'roll20_win': d.get('roll20') and d['roll20']['win_rate'], 'holm_p': d.get('family_holm_p')})
    obj = {'angle': 'country', 'prereg': PREREG, 'prereg_commit': git_sha(PREREG),
           'prereg2': 'out/mw_country_prereg2.json', 'prereg2_commit': git_sha('out/mw_country_prereg2.json'),
           'deviation_note': '第1回の相手 JKP developed は先進国（米国抜き）だった。事前登録2 で相手（ii）を French Developed（米国込み・1990-07〜）へ訂正。第1回の数字は各戦略の as_registered_vs_dev_exUS に残した',
           'global_criteria': 'out/mw_prereg.json', 'benchmark_primary': 'French Developed Mkt（Mkt-RF＋RF・米国込み）＝P・E1・E2・E5・対照。E3=French Developed_ex_US・E4=JKP emerging/frontier/world・E6=French EAFE・E7=French Developed',
           'prereg3': 'out/mw_country_prereg3.json', 'prereg3_commit': git_sha('out/mw_country_prereg3.json'),
           'prereg4': 'out/mw_country_prereg4.json', 'prereg4_commit': git_sha('out/mw_country_prereg4.json'),
           'prereg5': 'out/mw_country_prereg5.json', 'prereg5_commit': git_sha('out/mw_country_prereg5.json'),
           'conclusion_ja': [
               '主の問い（米国込みの時価加重の先進国市場 French Developed に勝つか）: 主の7本で A・S は無し。国を選ぶ規則（勢い・割安・両方）は 2007〜2025 に年 −1〜−3% 負け、米国と米国外の切替（P7）だけが +0.42%/年（t0.40・B）',
               '負けの主因は規則の中身より『米国を少なく持つこと』: 同じ23か国の等分でも French Developed に −1.53%/年、米国だけなら +2.07%/年（t3.24）',
               '米国抜きの先進国（事前登録した系列 JKP developed の正体）に対しては勝っていた: 配当利回りの上位3か国（E2_dp_K3）が S（+3.76%/年・t2.81・費用後 +3.31%/年）、勢い上位5（P2）が A',
               '配当利回りの国選びは French の1976年からのデータでも S（D4・+3.49%/年・t2.75）、実在ETF 20本でも EFA に +3.36%/年（t2.26）。ただし上位3という一点に依存（K=5 で +1.2、NZ か豪州を除くと約 +1.7・t1）、三分位の上−下は保有期間で +0.1%/年（t0.07）、米国の業種・新興国ETFでは再現せず、米国込みの市場に対する α は 0.0、米国には −1.0%/年',
               '事後（格付けなし）: 米国は市場の重みのまま持ち、米国外の部分だけ配当利回り上位3か国に替える形は French Developed に +1.58%/年（t2.32・2007〜2025）',
               'データの訂正: JKP の地域 developed は米国を含まない（事前登録2 で相手を French Developed に訂正・第1回の数字は as_registered に残した）'],
           'n_tested': len(tested), 'families_holm': holm, 'summary_table': summ, 'tested': tested,
           'post_hoc_reports_not_graded': xr, 'sanity': san}
    p = M.save(OUT, obj)
    print('書いた', p)
    for x in summ:
        print(f"{x['id']:22s} {x['family']:8s} {x['grade']}  full {x['full_ex']} t{x['full_t']}  train {x['train_ex']} t{x['train_t']}  "
              f"hold {x['hold_ex']} t{x['hold_t']} g{x['hold_cagr_diff']} net {x['hold_net_ex']}  r20 {x['roll20_win']} holm {x['holm_p']}")


if __name__ == '__main__':
    if '--check' in sys.argv:
        check()
        sys.exit(0)
    main()
