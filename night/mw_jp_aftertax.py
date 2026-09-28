#!/usr/bin/env python3
"""night/mw_jp_aftertax.py — 『市場に勝てる歴史検証』の角度 jp_aftertax（読むだけ・門の判定には不使用）

問い: これまでの角度で残った『上乗せ』(E1〜E4) は、日本の税（20.315%・損失の3年繰越・ウォッシュセール規則なし）と
      新NISA（つみたて120万・成長240万/年・生涯1800万〔成長は1200万まで〕・売った簿価は翌年に枠が戻る・
      買い直しは毎回その年の枠を使う・NISA の中の米国配当の源泉10%は戻らない）のもとで、
      同じ積立を『指数ファンドに NISA から入れて持ち続ける』場合より、税引後の最終資産で勝つか。
      損出し（同じ指数の双子への乗り換え）は小さくても確実な上乗せになるか。

事前登録: out/mw_jp_aftertax_prereg.json（測る前にコミット）。全体の線は out/mw_prereg.json（mw_common.grade）。
出力: out/mw_jp_aftertax.json

使い方:
  python3 night/mw_jp_aftertax.py --selftest   # 合成データで道具だけを確かめる（戦略と市場は比べない）
  python3 night/mw_jp_aftertax.py --dry        # データの範囲だけ（戦略と市場は比べない）
  python3 night/mw_jp_aftertax.py              # 全部測って out/mw_jp_aftertax.json へ
"""
import sys, os, io, json, math, csv, zipfile, subprocess, statistics as S, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402

ANGLE = 'jp_aftertax'
PREREG = 'mw_jp_aftertax_prereg.json'
OUT = 'mw_jp_aftertax.json'
FR_END, JKP_END = 202608, 202512
JKP_START = 196307                     # Compustat の後付けが強い 1963 年以前を使わない（gate_proxy と同じ）

# ── 税と NISA（事前登録の写し。変えるなら事前登録から）
TAX = 0.20315                          # 譲渡益・配当（申告分離・所得税15.315%＋住民税5%）
TAX_STRESS = 0.25                      # 税制の重しの試験
WH = 0.10                              # 米国の配当源泉（NISA では戻らない。課税口座は外国税額控除で戻す＝確定申告）
Q_TSUMI, Q_GROWTH = 1_200_000, 2_400_000
LIFE, LIFE_G = 18_000_000, 12_000_000
CONTRIB = 170_000                      # 月の積立（2026年の円・実質一定）。台帳の DCA「月17万」
SCALES = (100_000, 300_000)            # 感度（判定には使わない）
BENCH_FEE = 0.0010                     # 指数ファンド（eMAXIS Slim 級）の年の費用
SWITCH_COST = 0.0010                   # 損出しの乗り換え1回あたり
HARVEST_L = (0.10, 0.20)
NDX_DY = 0.005                         # NASDAQ100 の配当利回りの仮定（年）。^NDX は価格だけなので

LOG = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


def madd(m, k):
    y, mo = divmod(m // 100 * 12 + m % 100 - 1 + k, 12)
    return y * 100 + mo + 1


def mrange(a, z):
    out, m = [], a
    while m <= z:
        out.append(m)
        m = madd(m, 1)
    return out


def git_sha(path):
    try:
        return subprocess.run(['git', 'log', '-1', '--format=%H', '--', path], cwd=M.BASE, capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa
        return None


# ───────────────────────── データ ─────────────────────────
def fred_monthly(sid, how='last'):
    """キャッシュ済みの FRED CSV → {yyyymm: 値}（'last'＝月末の最後の観測・'first'＝月の値）。欠測（.）は読まない"""
    b = M.get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}', name=f'fred_{sid}.csv', max_age_days=100000)
    out = {}
    for r in csv.DictReader(io.StringIO(b.decode())):
        v = r.get(sid)
        if v in (None, '', '.'):
            continue
        d = r['observation_date']
        ym = int(d[:4]) * 100 + int(d[5:7])
        if how == 'first' and ym in out:
            continue
        out[ym] = float(v)
    return out


def market_div_return():
    """French 12業種の（配当込み − 配当抜き）を時価（社数×平均規模）で加重 → 市場の月次の配当リターン（小数）"""
    wi = M.french_tables('12_Industry_Portfolios')
    wo = M.french_tables('12_Industry_Portfolios_Wout_Div')

    def tab(T, want):
        for k, v in T.items():
            if want.lower() in k.lower() and v['freq'] == 'monthly':
                return v
        raise KeyError(want)
    rw, ro = tab(wi, 'Average Value Weighted Returns'), tab(wo, 'Average Value Weighted Returns')
    nf, sz = tab(wi, 'Number of Firms'), tab(wi, 'Average Firm Size')
    out = {}
    for m, row in rw['data'].items():
        if m not in ro['data'] or m not in nf['data'] or m not in sz['data'] or m > FR_END:
            continue
        num = den = 0.0
        ok = True
        for i in range(len(rw['cols'])):
            a, b, n, s = row[i], ro['data'][m][i], nf['data'][m][i], sz['data'][m][i]
            if None in (a, b, n, s):
                ok = False
                break
            w = n * s
            num += w * (a - b) / 100
            den += w
        if ok and den > 0:
            out[m] = num / den
    return out


def load_all():
    """全ての系列を読む（成績はまだ計算しない）"""
    D = {}
    ff = M.ff_factors()
    D['mkt'] = {k: v for k, v in ff['mkt'].items() if k <= FR_END}
    D['rf'] = {k: v for k, v in ff['rf'].items() if k <= FR_END}
    D['dy'] = market_div_return()
    D['cpi'] = fred_monthly('CPIAUCNS', 'first')
    D['fx'] = fred_monthly('DEXJPUS', 'last')          # 円/ドル（月末）
    # E1: cop_at（JKP 米国・vw 三分位の良い−悪い・符号つき）
    ls, dirn = {}, None
    for x in M.jkp_rows('usa', 'all_factors', 'factor', 'vw'):
        if x['name'] != 'cop_at' or x['ret'] in ('', 'NA', 'na'):
            continue
        ls[M._ym(x['date'])] = float(x['ret'])
        dirn = x.get('direction')
    D['cop_ls_vw'], D['cop_dir'] = ls, dirn
    # E1m: mega の順位加重（向き無し → 向きを掛ける）
    u = 'https://jkpfactors-data.s3.amazonaws.com/public/factor/%5Busa%5D_%5Bcop_at%5D_%5Bmega%5D.zip'
    b = M.get(u, name='jkp_size_usa_cop_at_mega.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    mg = {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        if x['ret'] in ('', 'NA', 'na') or int(x['n']) < 50:
            continue
        mg[M._ym(x['date'])] = float(x['ret']) * float(dirn)
    D['cop_ls_mega'] = mg
    # E2: 門の16本の良い側（gate_proxy P1）
    import mw_gate_proxy as G
    keep = {c for v in G.MEASURES.values() for c, _ in v}
    Dg = G.load('usa', 'vw', keep=keep)
    ex, info = G.composite(Dg, G.MEASURES, 'good')
    D['p1_total'] = G.total(ex)
    D['p1_info'] = info
    D['p1_turn'] = G.turnover(G.MEASURES, 'good')
    D['p1_unit_cost'] = G.UNIT_COST
    # E3・E4: 業種の勢い（etf_tactical の規則関数をそのまま使う）
    import mw_etf_tactical as E
    src = {}
    ind = M.french_series('10_Industry_Portfolios', 'Value Weight')
    for c in ['NoDur', 'Durbl', 'Manuf', 'Enrgy', 'HiTec', 'Telcm', 'Shops', 'Hlth', 'Utils']:
        src['FR10_' + c] = E.cut(ind[c])
    for t in E.SECT_EF + E.FSEL + E.RAKU + ['QQQ', '^NDX']:
        if t not in src:
            try:
                src[t] = E.yh(t)
            except Exception as e:  # noqa  取れないものは対象外（0で埋めない）
                log('  ⚠ 取得失敗', t, str(e)[:80])
    for t in E.DEAD:
        rows = sorted(csv.DictReader(open(os.path.join(M.CACHE, f'av_dead_select_{t}.csv'))), key=lambda r: r['date'])
        px = {int(r['date'][:4]) * 100 + int(r['date'][5:7]): float(r['adj']) for r in rows}
        ks = sorted(px)
        src['AV_' + t] = E.cut({k: px[k] / px[p] - 1 for p, k in zip(ks, ks[1:]) if madd(p, 1) == k})
    for k in list(src):
        src[k], _ = E.contiguous_tail(src[k], k)
    D['src'] = src
    D['E'] = E
    return D


def build_edges(D):
    """事前登録の E1〜E4（主）と副の型。どれも総リターン（小数）と、税の模型が要る情報を返す"""
    E = D['E']
    rf, mkt = D['rf'], D['mkt']
    ed = {}
    # E1 cop_at の傾け（mega_tilt X3b: 市場 + 0.11 ×（vw 三分位の良い−悪い））
    lam, to_leg = 0.11, 0.4
    ks = [k for k in sorted(D['cop_ls_vw']) if JKP_START <= k <= JKP_END and k in mkt]
    ed['E1_cop_tilt'] = dict(kind='single', primary=True, vehicle='direct', fee=0.0,
                             R={k: mkt[k] + lam * D['cop_ls_vw'][k] for k in ks},
                             T=lam * 2 * to_leg + 0.04, cu=0.001, start=ks[0], end=ks[-1],
                             desc='E1 cop_at の傾け: French 市場 + 0.11×（JKP 米国 vw 三分位の良い−悪い）（mega_tilt X3b・買いだけに収まる λ）。個別株を直接持つ（年の売却 0.088＋合併等 0.04）',
                             src_ref=('mw_mega_tilt', 'X3b_vw_cop_at_lamvw'))
    lamm = 0.04
    ks = [k for k in sorted(D['cop_ls_mega']) if JKP_START <= k <= JKP_END and k in mkt]
    ed['E1m_cop_mega'] = dict(kind='single', primary=False, vehicle='direct', fee=0.0,
                              R={k: mkt[k] + lamm * D['cop_ls_mega'][k] for k in ks},
                              T=lamm * 2 * to_leg + 0.04, cu=0.001, start=ks[0], end=ks[-1],
                              desc='副 E1m: French 市場 + 0.04×（JKP 米国 mega の順位加重 LS）（mega_tilt X1_lamfeas）',
                              src_ref=('mw_mega_tilt', 'X1_mega_cop_at_lamfeas'))
    # E2 門の16本（gate_proxy P1）
    p1 = {k: v for k, v in D['p1_total'].items() if JKP_START <= k <= JKP_END and k in mkt}
    ks = sorted(p1)
    ed['E2_gate_P1'] = dict(kind='single', primary=True, vehicle='direct', fee=0.0, R=p1,
                            T=D['p1_turn'] + 0.04, cu=D['p1_unit_cost'], start=ks[0], end=ks[-1],
                            desc=f'E2 門の16本の良い側を等分（gate_proxy P1・JKP 米国 vw 三分位）。個別株を直接持つ（年の売却 {D["p1_turn"]}＋合併等 0.04・費用 0.2%/片道100%）',
                            src_ref=('mw_gate_proxy', 'P1_GATE_ALL'))
    # E3 セクターの勢い（etf_tactical P5_SECT3）: L＝French 10業種（Other 除く9）・E＝SPDR 9本
    src = D['src']
    RL = {'TBILL': rf}
    RL.update({s: src[s] for s in E.SECT_L})
    g, n, ns, wp, tr = E.run(RL, E.mk_sector(E.SECT_L, 3))
    ed['E3_sector_mom'] = dict(kind='multi', primary=True, vehicle='direct', fee=0.0010, R=RL, wpath=wp, gross=g, trades=tr,
                               cs=E.C_SIDE, start=min(g), end=max(g),
                               desc='E3 業種の勢い（etf_tactical P5_SECT3_L）: French 10業種（Other 除く9）の12か月上位3を等分・毎月。セクター ETF の長い代理（年の費用 0.10% を足す）',
                               src_ref=('mw_etf_tactical', 'P5_SECT3_L'))
    RE, _seg = E.build_version(src, rf, 'E', E.SECT_EF)
    g, n, ns, wp, tr = E.run(RE, E.mk_sector(E.SECT_EF, 3))
    ed['E3e_spdr_mom'] = dict(kind='multi', primary=False, fresh_for='E3_sector_mom', vehicle='direct', fee=0.0, R=RE, wpath=wp, gross=g,
                              trades=tr, cs=E.C_SIDE, start=min(g), end=max(g),
                              desc='E3 の実物（etf_tactical P5_SECT3_E）: Select Sector SPDR 9本の12か月上位3を等分・毎月（2007〜の新しい答え合わせに使う）',
                              src_ref=('mw_etf_tactical', 'P5_SECT3_E'))
    # E4 Fidelity Select 風の上位3（etf_tactical H3_FSELD_K3_BL）
    fseld = list(E.FSEL) + ['AV_' + t for t in E.DEAD]
    R4 = {'TBILL': rf}
    R4.update({s: src[s] for s in fseld if src.get(s)})
    g, n, ns, wp, tr = E.run(R4, E.mk_sector_dyn(fseld, 3, 'blend', 20, alive=True), dynamic=True)
    ed['E4_fsel_top3'] = dict(kind='multi', primary=True, vehicle='direct', fee=0.0, R=R4, wpath=wp, gross=g, trades=tr,
                              cs=E.C_SIDE, start=min(g), end=max(g),
                              desc='E4 Fidelity Select 風（etf_tactical H3_FSELD_K3_BL）: Select 33本＋合併・廃止6本の (r1+r3+r6+r12)/4 上位3を等分・毎月（日本の居住者は買えない）',
                              src_ref=('mw_etf_tactical', 'H3_FSELD_K3_BL'))
    g, n, ns, wp, tr = E.run(R4, E.mk_sector_dyn(fseld, 3, 'r12', 20, alive=True), dynamic=True)
    ed['E4r_fsel_r12'] = dict(kind='multi', primary=False, vehicle='direct', fee=0.0, R=R4, wpath=wp, gross=g, trades=tr,
                              cs=E.C_SIDE, start=min(g), end=max(g),
                              desc='副 E4r: 同じ Select＋死んだ6本の12か月上位3（etf_tactical H1_FSELD_K3_R12）',
                              src_ref=('mw_etf_tactical', 'H1_FSELD_K3_R12'))
    # 楽天で買える業種・テーマ ETF（日本の居住者が実際に買える唯一の形・2003〜）
    RK = {'TBILL': rf}
    RK.update({s: src[s] for s in E.RAKU if src.get(s)})
    for nm, sc, rid in (('E3k_raku_r12', 'r12', 'K1_RAKU_K3_R12'), ('E4k_raku_bl', 'blend', 'K3_RAKU_K3_BL')):
        g, n, ns, wp, tr = E.run(RK, E.mk_sector_dyn(E.RAKU, 3, sc, 20, alive=True), dynamic=True)
        ed[nm] = dict(kind='multi', primary=False, vehicle='direct', fee=0.0, R=RK, wpath=wp, gross=g, trades=tr, cs=E.C_SIDE,
                      start=min(g), end=max(g),
                      desc=f'副 {nm}: 楽天で買える業種・テーマ ETF（101本）の{"12か月" if sc == "r12" else "(r1+r3+r6+r12)/4"}上位3（etf_tactical {rid}）',
                      src_ref=('mw_etf_tactical', rid))
    return ed


def ndx_series(D):
    """NASDAQ100: QQQ（配当込み）がある月は QQQ、無い月は ^NDX 価格 + 0.5%/年（etf_tactical の NDX_PX_DIV と同じ）"""
    q, n = D['src']['QQQ'], D['src']['^NDX']
    out = {}
    for m in sorted(set(q) | set(n)):
        if m in q:
            out[m] = q[m]
        elif m in n:
            out[m] = n[m] + NDX_DY / 12
    out, _ = D['E'].contiguous_tail(out, 'NDX_splice')
    return out


# ───────────────────────── 税と NISA の模型 ─────────────────────────
class Regime:
    """mode: 'free'（非課税・枠なし）/'taxable'（課税口座だけ）/'real'（NISA から入れて溢れは課税口座）"""
    def __init__(self, name, mode, tax=TAX, wh=WH, scale=CONTRIB, tsumi_index=False, location=None):
        self.name, self.mode, self.tax, self.wh, self.scale, self.tsumi_index = name, mode, tax, wh, scale, tsumi_index
        self.location = location           # 事前登録2 X1: 'L1'＝NISA は指数だけ・上乗せは課税口座だけ


REG = {
    'R0_pretax': Regime('R0_pretax', 'free', tax=0.0, wh=0.0),
    'R1_nisa_unlimited': Regime('R1_nisa_unlimited', 'free', tax=0.0, wh=WH),
    'R2_real': Regime('R2_real', 'real'),
    'R3_taxable': Regime('R3_taxable', 'taxable'),
    'R2_real_tax25': Regime('R2_real_tax25', 'real', tax=TAX_STRESS),
    'R3_taxable_tax25': Regime('R3_taxable_tax25', 'taxable', tax=TAX_STRESS),
    'R2_real_100k': Regime('R2_real_100k', 'real', scale=SCALES[0]),
    'R2_real_300k': Regime('R2_real_300k', 'real', scale=SCALES[1]),
    'R2t_real_tsumi_index': Regime('R2t_real_tsumi_index', 'real', tsumi_index=True),
    # 事前登録2（探索）X1: 置き場所を分ける
    'L1_real': Regime('L1_real', 'real', location='L1'),
    'L1_real_tax25': Regime('L1_real_tax25', 'real', tax=TAX_STRESS, location='L1'),
    'L1_real_100k': Regime('L1_real_100k', 'real', scale=SCALES[0], location='L1'),
    'L1_real_300k': Regime('L1_real_300k', 'real', scale=SCALES[1], location='L1'),
}


class Arm:
    """一つの口座群（NISA つみたて NT・成長 NG・課税 T・非課税枠なし F）。月初に売買・積立、月中にリターン、月末に配当。
    strat: {'kind': 'single'|'multi', 'asset' or 'wpath', 'T'（年の実現率）, 'cu'（片道100%あたり費用）, 'cs'（片側費用）}
    assets: {名前: {'vehicle': 'fund'|'direct', 'fee': 年, 'frames': ('NT','NG') or ('NG',)}}"""

    def __init__(self, reg, strat, assets, R, DY, idx, harvest=None):
        self.reg, self.st, self.A, self.R, self.DY, self.idx = reg, strat, assets, R, DY, idx
        self.tax = reg.tax
        self.pos = {}                      # (口座, 資産) -> [時価, 取得額（移動平均）]
        self.cash = 0.0
        self.ytd = 0.0; self.ydiv = 0.0; self.withheld = 0.0
        self.carry = []                    # [年, 損失]
        self.qu = {'NT': 0.0, 'NG': 0.0}
        self.life = self.life_g = self.pend = self.pend_g = 0.0
        self.year = None
        self.hv = harvest                  # {'L':, 'gain': bool, 'asset': 'IDX'}
        self.twin_age = None
        self.stats = {'tax_paid': 0.0, 'harvests': 0, 'carry_expired': 0.0, 'gain_harvest': 0.0, 'costs': 0.0, 'fx': 0.0}

    # ── 口座
    def accts(self):
        return {'free': ('F',), 'taxable': ('T',), 'real': ('NT', 'NG', 'T')}[self.reg.mode]

    def _add(self, acct, a, x):
        p = self.pos.setdefault((acct, a), [0.0, 0.0])
        p[0] += x; p[1] += x

    def buy(self, a, x, m, force_taxable=False):
        """x を資産 a に入れる。real では NISA の枠（年・生涯）→ 残りを課税口座"""
        if x <= 1e-12:
            return
        mode = self.reg.mode
        if mode == 'free':
            self._add('F', a, x); return
        if self.reg.location == 'L1' and a != 'IDX':
            force_taxable = True
        if mode == 'taxable' or force_taxable:
            self._add('T', a, x); return
        k = self.idx(m)
        for fr in self.A[a]['frames']:
            cap_y = (Q_TSUMI if fr == 'NT' else Q_GROWTH) * k - self.qu[fr]
            cap_l = LIFE * k - self.life
            if fr == 'NG':
                cap_l = min(cap_l, LIFE_G * k - self.life_g)
            y = min(x, max(0.0, cap_y), max(0.0, cap_l))
            if y > 1e-12:
                self._add(fr, a, y)
                self.qu[fr] += y; self.life += y
                if fr == 'NG':
                    self.life_g += y
                x -= y
            if x <= 1e-12:
                return
        self._add('T', a, x)

    def sell(self, acct, a, x):
        p = self.pos.get((acct, a))
        if not p or p[0] <= 1e-12 or x <= 0:
            return 0.0
        x = min(x, p[0])
        f = x / p[0]
        b = p[1] * f
        if acct == 'T':
            self.realize(x - b)
        elif acct in ('NT', 'NG'):
            self.pend += b
            if acct == 'NG':
                self.pend_g += b
        p[0] -= x; p[1] -= b
        if p[0] <= 1e-9:
            del self.pos[(acct, a)]
        self.cash += x
        return x

    def realize(self, g):
        if self.tax <= 0:
            return
        self.ytd += g
        self.withhold()

    def withhold(self):
        tgt = self.tax * max(0.0, self.ytd)
        self.cash -= tgt - self.withheld
        self.withheld = tgt

    def settle(self, year, final=False):
        """年の精算（確定申告）: 3年以内の繰越損失を古い順に当て、外国税額控除（配当の米国源泉 10% まで）を戻す"""
        if self.tax <= 0:
            return
        self.carry = [c for c in self.carry if year - c[0] <= 3]
        inc = self.ytd
        fin = 0.0
        if inc > 0:
            rem = inc
            for c in self.carry:
                u = min(c[1], rem)
                c[1] -= u; rem -= u
            fin = self.tax * rem
            cred = min(self.reg.wh * self.ydiv, fin) if self.ydiv > 0 else 0.0
            fin -= cred
        elif inc < 0:
            self.carry.append([year, -inc])
        self.cash += self.withheld - fin
        self.stats['tax_paid'] += fin
        exp = sum(c[1] for c in self.carry if year - c[0] >= 3)
        self.stats['carry_expired'] += exp
        self.carry = [c for c in self.carry if c[1] > 1e-9 and year - c[0] < 3]
        self.ytd = self.ydiv = self.withheld = 0.0

    def new_year(self, m):
        y = m // 100
        if self.year is not None and y != self.year:
            self.settle(self.year)
            self.qu = {'NT': 0.0, 'NG': 0.0}
            self.life -= self.pend; self.life_g -= self.pend_g
            self.pend = self.pend_g = 0.0
        self.year = y

    # ── 月の流れ
    def value(self, assets=None):
        return sum(v[0] for (ac, a), v in self.pos.items() if assets is None or a in assets)

    def cover_cash(self):
        """現金が負（税の支払い）なら課税口座→NISA の順に按分で売る"""
        for _ in range(4):
            if self.cash >= -1e-9:
                return
            need = -self.cash
            for grp in (('T',), ('NT', 'NG', 'F')):
                tv = sum(v[0] for (ac, a), v in self.pos.items() if ac in grp)
                if tv <= 0:
                    continue
                f = min(1.0, need / tv)
                for key in [k for k in self.pos if k[0] in grp]:
                    self.sell(key[0], key[1], self.pos[key][0] * f)
                break

    def harvest_step(self, m):
        hv = self.hv
        a, tw = hv['asset'], hv['asset'] + '_TWIN'
        # 1か月たった双子を元へ戻す（課税口座の中で）
        if self.twin_age is not None:
            self.twin_age += 1
            if self.twin_age >= 1:
                p = self.pos.get(('T', tw))
                if p:
                    x = self.sell('T', tw, p[0])
                    c = x * SWITCH_COST
                    self.cash -= c; self.stats['costs'] += c
                    self.cash -= x - c
                    self._add('T', a, x - c)
                self.twin_age = None
        # 取得額より L 以上下がったら双子へ（損を実現）
        p = self.pos.get(('T', a))
        if p and p[0] > 0 and p[0] <= (1 - hv['L']) * p[1] and self.twin_age is None:
            x = self.sell('T', a, p[0])
            c = x * SWITCH_COST
            self.cash -= c; self.stats['costs'] += c
            self.cash -= x - c
            self._add('T', tw, x - c)
            self.twin_age = 0
            self.stats['harvests'] += 1
        # 益出し（12月・その年で切れる繰越損失の分だけ、利益を実現してすぐ買い直す＝ウォッシュセール規則なし）
        if hv.get('gain') and m % 100 == 12 and self.tax > 0:
            exp = sum(c[1] for c in self.carry if self.year - c[0] >= 3)
            room = exp - max(0.0, self.ytd)
            for key in [('T', a), ('T', tw)]:
                if room <= 1e-9:
                    break
                p = self.pos.get(key)
                if not p or p[0] <= p[1]:
                    continue
                u = p[0] - p[1]
                g = min(room, u)
                x = p[0] * g / u
                self.sell(key[0], key[1], x)
                c = x * SWITCH_COST
                self.cash -= c; self.stats['costs'] += c
                self.cash -= x - c
                self._add('T', key[1], x - c)
                self.stats['gain_harvest'] += g
                room -= g

    def start_month(self, m, contrib):
        """月初（前月末の情報で）: 年替わり・積立・損出し・戦略の売買・現金の投入"""
        self.new_year(m)
        self.cash += contrib
        st = self.st
        if self.hv:
            self.harvest_step(m)
        # 事前登録2 X1（L1）: 積立はまず指数ファンドを NISA へ（入りきらない分だけ上乗せを課税口座で）
        if self.reg.location == 'L1' and self.reg.mode == 'real' and contrib > 0 and st.get('asset') != 'IDX':
            x = min(contrib, self.cash)
            k = self.idx(m)
            for fr in self.A['IDX']['frames']:
                cap_y = (Q_TSUMI if fr == 'NT' else Q_GROWTH) * k - self.qu[fr]
                cap_l = LIFE * k - self.life
                if fr == 'NG':
                    cap_l = min(cap_l, LIFE_G * k - self.life_g)
                y = min(x, max(0.0, cap_y), max(0.0, cap_l))
                if y > 1e-12:
                    self._add(fr, 'IDX', y)
                    self.qu[fr] += y; self.life += y
                    if fr == 'NG':
                        self.life_g += y
                    x -= y; self.cash -= y
        # R2t: 戦略の側でも、つみたて枠はまず指数ファンドへ
        if self.reg.tsumi_index and self.reg.mode == 'real' and contrib > 0 and st.get('asset') != 'IDX':
            k = self.idx(m)
            cap = min(Q_TSUMI * k - self.qu['NT'], LIFE * k - self.life, contrib, self.cash)
            if cap > 1e-9:
                self._add('NT', 'IDX', cap)
                self.qu['NT'] += cap; self.life += cap
                self.cash -= cap
        if st['kind'] == 'single':
            a = st['asset']
            q = st['T'] / 12
            if q > 0:
                for key in [k for k in self.pos if k[1] == a]:
                    x = self.sell(key[0], a, self.pos[key][0] * q)
                    c = x * st['cu']
                    self.cash -= c; self.stats['costs'] += c
            self.cover_cash()
            if self.cash > 1e-9:
                x = self.cash
                self.cash = 0.0
                if self.hv and self.twin_age is not None and a == self.hv['asset'] and self.reg.mode != 'free':
                    # 双子を持っている月は、課税口座へ入る分を双子へ
                    before = {k: v[0] for k, v in self.pos.items()}
                    self.buy(a, x, m)
                    p = self.pos.get(('T', a))
                    added = p[0] - before.get(('T', a), 0.0) if p else 0.0
                    if added > 1e-12:
                        p[0] -= added; p[1] -= added
                        if p[0] <= 1e-9:
                            del self.pos[('T', a)]
                        self._add('T', a + '_TWIN', added)
                else:
                    self.buy(a, x, m)
        else:
            w = st['wpath'][madd(m, -1)]
            names = set(st['assets'])
            tv = self.value(names) + self.cash
            cur = {}
            for (ac, a), v in self.pos.items():
                if a in names:
                    cur[a] = cur.get(a, 0.0) + v[0]
            cs = st['cs']
            for a in list(cur):
                tg = w.get(a, 0.0) * tv
                if cur[a] > tg + 1e-9:
                    ex = cur[a] - tg
                    f = ex / cur[a]
                    for key in [k for k in self.pos if k[1] == a]:
                        x = self.sell(key[0], a, self.pos[key][0] * f)
                        c = x * cs
                        self.cash -= c; self.stats['costs'] += c
            self.cover_cash()
            need = {a: w[a] * tv - cur.get(a, 0.0) for a in w if w[a] * tv - cur.get(a, 0.0) > 1e-9}
            tn = sum(need.values())
            if tn > 0 and self.cash > 1e-9:
                sc = min(1.0, self.cash / (tn * (1 + cs)))
                for a, x in need.items():
                    y = x * sc
                    c = y * cs
                    self.cash -= y + c; self.stats['costs'] += c
                    self.buy(a, y, m)
            if self.cash > 1e-6:                      # 端数（費用の差）は重みで按分
                x = self.cash
                self.cash = 0.0
                for a in w:
                    self.buy(a, x * w[a], m)

    def apply_month(self, m):
        """当月のリターン・費用・配当（配当は現金へ・課税口座は源泉）"""
        dy = self.DY[m]
        wh = self.reg.wh
        divs = []
        for key, p in list(self.pos.items()):
            ac, a = key
            spec = self.A[a]
            r = self.R[a][m]
            if spec['vehicle'] == 'fund':
                p[0] *= 1 + r - wh * dy - spec['fee'] / 12
            else:
                v0 = p[0]
                p[0] *= 1 + (r - dy) - spec['fee'] / 12
                divs.append((ac, v0 * dy))
        for ac, d in divs:
            self.cash += d * (1 - wh)
            if ac == 'T' and self.tax > 0:
                self.ydiv += d
                self.ytd += d
                self.withhold()

    def liquidation_value(self):
        """いま全部売ったら手元に残る額（税引後）"""
        tv = self.value()
        if self.tax <= 0:
            return tv + self.cash
        u = sum(v[0] - v[1] for (ac, a), v in self.pos.items() if ac == 'T')
        inc = self.ytd + u
        fin = 0.0
        if inc > 0:
            avail = sum(c[1] for c in self.carry if self.year - c[0] <= 3)
            fin = self.tax * max(0.0, inc - avail)
            cred = min(self.reg.wh * self.ydiv, fin) if self.ydiv > 0 else 0.0
            fin -= cred
        return tv + self.cash - (fin - self.withheld)

    def liquidate(self):
        self.stats['nisa_end'] = sum(v[0] for (ac, a), v in self.pos.items() if ac in ('NT', 'NG'))
        self.stats['pre_liq'] = self.value() + self.cash
        for key in [k for k in self.pos if k[0] == 'T']:
            self.sell('T', key[1], self.pos[key][0])
        self.settle(self.year, final=True)
        return self.value() + self.cash


CPI_FILLED = []


def fill_cpi(cpi):
    """欠けた月（米国 CPI の 2025-10 は政府閉鎖で未公表）を前後の月の幾何補間で埋める。
    積立額と NISA 枠の実質化だけに使い、リターンには使わない（事後の技術的な修正・deviations に記録）"""
    ks = sorted(cpi)
    out = dict(cpi)
    for a, b in zip(ks, ks[1:]):
        gap = mrange(madd(a, 1), madd(b, -1))
        n = len(gap) + 1
        for i, m in enumerate(gap, 1):
            out[m] = cpi[a] * (cpi[b] / cpi[a]) ** (i / n)
            CPI_FILLED.append(m)
    return out


def make_idx_cpi(cpi, ref=FR_END):
    cpi = fill_cpi(cpi)
    base = cpi[ref]

    def f(m):
        return cpi[m] / base
    return f


def run_arm(reg, strat, assets, R, DY, idx, months, contrib_real=None, lump=None, harvest=None, record=False):
    """months を順に動かす。contrib_real: 月の積立（実質・idx を掛ける）。lump: 最初に入れる額。戻り値: 税引後の最終額（と記録）"""
    arm = Arm(reg, strat, assets, R, DY, idx, harvest)
    rec = {}
    for i, m in enumerate(months):
        c = 0.0
        if contrib_real is not None:
            c = contrib_real * idx(m)
        if lump is not None and i == 0:
            c += lump
        arm.start_month(m, c)
        arm.apply_month(m)
        if record:
            rec[m] = arm.liquidation_value()
    fin = arm.liquidate()
    return fin, arm, rec


# ───────────────────────── 窓 ─────────────────────────
def dca_windows(first, last, years=20):
    """1月起点・years 年（240か月）の毎月積立の窓。first 月から入れられ、last 月までに終わるもの"""
    out = []
    for y in range(first // 100, 2100):
        a = y * 100 + 1
        if a < first:
            continue
        z = (y + years - 1) * 100 + 12
        if z > last:
            break
        out.append((a, z))
    return out


def lump_windows(first, last, years=20):
    """7月起点・years 年の一括（mw_common.rolling と同じ起点）"""
    out = []
    for y in range(first // 100, 2100):
        a = y * 100 + 7
        if a < first:
            continue
        z = (y + years) * 100 + 6
        if z > last:
            break
        out.append((a, z))
    return out


def summarize_ratios(rs):
    """[(起点, 比)] → 勝率・中央・最悪・最良・10%点"""
    if not rs:
        return None
    v = sorted(r for _, r in rs)
    n = len(v)
    return {'n': n, 'win_share': round(sum(1 for r in v if r > 1) / n, 3), 'median': round(v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2, 4),
            'p10': round(v[max(0, int(n * 0.1) - 0)] if n >= 10 else v[0], 4),
            'worst': [min(rs, key=lambda x: x[1])[0], round(min(r for _, r in rs), 4)],
            'best': [max(rs, key=lambda x: x[1])[0], round(max(r for _, r in rs), 4)]}


# ───────────────────────── 合成データでの道具の確かめ（成績は見ない） ─────────────────────────
def selftest():
    ok = {}
    ms = mrange(200001, 202012)
    one = lambda m: 1.0
    # (1) 非課税・費用0・配当0: 積立の終値は閉じた式と一致
    R = {'IDX': {m: 0.01 for m in ms}}
    DY = {m: 0.0 for m in ms}
    A = {'IDX': {'vehicle': 'fund', 'fee': 0.0, 'frames': ('NT', 'NG')}}
    st = {'kind': 'single', 'asset': 'IDX', 'T': 0.0, 'cu': 0.0}
    fin, arm, _ = run_arm(REG['R0_pretax'], st, A, R, DY, one, ms[:240], contrib_real=1.0)
    closed = sum(1.01 ** (240 - i) for i in range(240))
    ok['dca_closed_form'] = abs(fin - closed) < 1e-6 * closed
    # (2) 課税口座の一括: 終値 = V − τ(V−1)
    fin, arm, _ = run_arm(REG['R3_taxable'], st, A, R, DY, one, ms[:240], lump=1.0)
    V = 1.01 ** 240
    ok['lump_taxable'] = abs(fin - (V - TAX * (V - 1))) < 1e-9
    # (3) NISA の生涯枠: 値動き0・月17万 → 1800万で満ち、以後は課税口座
    R0 = {'IDX': {m: 0.0 for m in ms}}
    fin, arm, _ = run_arm(REG['R2_real'], st, A, R0, DY, one, ms[:240], contrib_real=CONTRIB)
    nisa = sum(v[0] for (ac, a), v in arm.pos.items() if ac in ('NT', 'NG')) if arm.pos else None
    ok['life_cap'] = abs(arm.life - LIFE) < 1 and abs(fin - CONTRIB * 240) < 1e-3
    # (4) 実現率モデル: 値動き0なら税0、終値は元本−費用
    st2 = {'kind': 'single', 'asset': 'IDX', 'T': 1.2, 'cu': 0.001}
    fin, arm, _ = run_arm(REG['R3_taxable'], st2, A, R0, DY, one, ms[:24], lump=1.0)
    ok['realize_no_gain_no_tax'] = arm.stats['tax_paid'] == 0 and abs(fin - (1 - 0.001 * 0.1) ** 23) < 1e-9
    # (5) 実現率 100%/月・毎月+1%・課税: 毎月の利益が実現して税（年の精算）→ 一括の繰延より小さい
    st3 = {'kind': 'single', 'asset': 'IDX', 'T': 12.0, 'cu': 0.0}
    fin_hi, arm_hi, _ = run_arm(REG['R3_taxable'], st3, A, R, DY, one, ms[:240], lump=1.0)
    fin_bh, _, _ = run_arm(REG['R3_taxable'], st, A, R, DY, one, ms[:240], lump=1.0)
    ok['turnover_tax_drag'] = fin_hi < fin_bh and abs(fin_hi - (1 + 0.01 * (1 - TAX)) ** 240) / fin_hi < 0.02
    # (6) 繰越損失は3年で切れる: −30% の後に横ばい、損出しすると損は使えず失効 → 取得額が下がった分だけ最後に多く払う
    path = {m: 0.0 for m in ms}
    path[ms[1]] = -0.30
    path[ms[20]] = 0.60
    Rp = {'IDX': path, 'IDX_TWIN': path}
    A2 = {'IDX': A['IDX'], 'IDX_TWIN': A['IDX']}
    fb, _, _ = run_arm(REG['R3_taxable'], st, A2, Rp, DY, one, ms[:200], lump=1.0)
    fh, ah, _ = run_arm(REG['R3_taxable'], st, A2, Rp, DY, one, ms[:200], lump=1.0, harvest={'L': 0.10, 'asset': 'IDX'})
    fg, ag, _ = run_arm(REG['R3_taxable'], st, A2, Rp, DY, one, ms[:200], lump=1.0, harvest={'L': 0.10, 'asset': 'IDX', 'gain': True})
    ok['harvest_expiry_hurts'] = ah.stats['harvests'] == 1 and ah.stats['carry_expired'] > 0.29 and fh < fb
    ok['gain_harvest_rescues'] = ag.stats['gain_harvest'] > 0.29 and fg > fh and abs(fg - fb) < 0.01
    # (7) 回転の gross は etf_tactical.run の gross と一致（非課税・費用0・配当0・積立なし）
    ms2 = mrange(200001, 200512)
    Rr = {'A': {m: (0.02 if m % 2 else -0.01) for m in ms2}, 'B': {m: 0.005 for m in ms2}}
    wp = {madd(m, -1): ({'A': 0.5, 'B': 0.5} if m % 3 else {'A': 1.0}) for m in ms2}
    A3 = {'A': {'vehicle': 'direct', 'fee': 0.0, 'frames': ('NG',)}, 'B': {'vehicle': 'direct', 'fee': 0.0, 'frames': ('NG',)}}
    st4 = {'kind': 'multi', 'wpath': wp, 'assets': ['A', 'B'], 'cs': 0.0}
    fin, arm, _ = run_arm(REG['R0_pretax'], st4, A3, Rr, {m: 0.0 for m in ms2}, one, ms2, lump=1.0)
    g = 1.0
    for m in ms2:
        w = wp[madd(m, -1)]
        g *= 1 + sum(w[a] * Rr[a][m] for a in w)
    ok['multi_gross_matches'] = abs(fin - g) < 1e-9
    # (8) NISA で回すと枠を使う: 毎月全部入れ替え・月17万・値動き0 → NISA に入るのは年240万まで
    fin, arm, _ = run_arm(REG['R2_real'], {'kind': 'multi', 'wpath': {madd(m, -1): ({'A': 1.0} if m % 2 else {'B': 1.0}) for m in ms2},
                                           'assets': ['A', 'B'], 'cs': 0.0},
                          A3, {'A': {m: 0.0 for m in ms2}, 'B': {m: 0.0 for m in ms2}}, {m: 0.0 for m in ms2}, one, ms2[:12], contrib_real=CONTRIB)
    ok['rotation_consumes_quota'] = arm.qu['NG'] <= Q_GROWTH + 1 and abs(arm.qu['NG'] - Q_GROWTH) < 1
    # (9) 配当: 課税口座の直接保有は 20.315%（外国税額控除つき）、NISA は 10%
    Rd = {'IDX': {m: 0.002 for m in ms}}
    DYd = {m: 0.002 for m in ms}
    Ad = {'IDX': {'vehicle': 'direct', 'fee': 0.0, 'frames': ('NG',)}}
    fin_t, arm_t, _ = run_arm(REG['R3_taxable'], st, Ad, Rd, DYd, one, ms[:24], lump=1.0)
    fin_f, _, _ = run_arm(REG['R1_nisa_unlimited'], st, Ad, Rd, DYd, one, ms[:24], lump=1.0)
    ok['div_tax_rates'] = abs((1 + 0.002 * (1 - TAX)) ** 24 - fin_t) < 5e-4 and abs((1 + 0.002 * 0.9) ** 24 - fin_f) < 1e-9
    return ok



# ───────────────────────── 測る ─────────────────────────
ONE = lambda m: 1.0
IDX_SPEC = {'vehicle': 'fund', 'fee': BENCH_FEE, 'frames': ('NT', 'NG')}
BENCH_ST = {'kind': 'single', 'asset': 'IDX', 'T': 0.0, 'cu': 0.0}
PRIMARY = ['E1_cop_tilt', 'E2_gate_P1', 'E3_sector_mom', 'E4_fsel_top3']
SECONDARY = ['E1m_cop_mega', 'E3e_spdr_mom', 'E4r_fsel_r12', 'E3k_raku_r12', 'E4k_raku_bl']
FRESH_OF = {'E3_sector_mom': 'E3e_spdr_mom'}      # E3 の 2007〜 の新しい答え合わせは実物の SPDR で
DCA_REGIMES = ['R0_pretax', 'R1_nisa_unlimited', 'R2_real', 'R3_taxable', 'R2_real_tax25', 'R3_taxable_tax25',
               'R2_real_100k', 'R2_real_300k', 'R2t_real_tsumi_index']
JPY_REGIMES = ['R1_nisa_unlimited', 'R2_real', 'R3_taxable']
LUMP_REGIMES = ['R0_pretax', 'R1_nisa_unlimited', 'R3_taxable']


def to_jpy(R, fx):
    out = {}
    for m, r in R.items():
        p = madd(m, -1)
        if m in fx and p in fx:
            out[m] = (1 + r) * fx[m] / fx[p] - 1
    return out


def arm_spec(ed, mkt):
    if ed['kind'] == 'single':
        R = {'E': ed['R'], 'IDX': mkt}
        A = {'E': {'vehicle': ed['vehicle'], 'fee': ed['fee'], 'frames': ('NG',)}, 'IDX': IDX_SPEC}
        st = {'kind': 'single', 'asset': 'E', 'T': ed['T'], 'cu': ed['cu']}
    else:
        names = sorted({a for w in ed['wpath'].values() for a in w})
        R = {a: ed['R'][a] for a in names}
        R['IDX'] = mkt
        A = {a: {'vehicle': ed['vehicle'], 'fee': ed['fee'], 'frames': ('NG',)} for a in names}
        A['IDX'] = IDX_SPEC
        st = {'kind': 'multi', 'wpath': ed['wpath'], 'assets': names, 'cs': ed['cs']}
    return st, A, R


def spec_jpy(spec, fx):
    st, A, R = spec
    return st, A, {a: to_jpy(r, fx) for a, r in R.items()}


def bench_spec(mkt):
    return BENCH_ST, {'IDX': IDX_SPEC}, {'IDX': mkt}


class Runner:
    def __init__(self, D):
        self.D = D
        self.cache = {}
        self.idx_usd = make_idx_cpi(D['cpi'])

    def pair(self, reg, spec, bspec, a, z, cur='USD', contrib=True, bkey='MKT', harvest=None, bharvest=None):
        """同じ積立（または一括1）で 戦略/相手 の税引後の最終額と、その比"""
        months = mrange(a, z)
        idx = self.idx_usd if cur == 'USD' else ONE
        DY = self.D['dy'] if not bkey.startswith('NDX') else {m: NDX_DY / 12 for m in months}
        c = reg.scale if contrib else None
        lump = None if contrib else 1.0
        st, A, R = spec
        fs, arm_s, _ = run_arm(reg, st, A, R, DY, idx, months, contrib_real=c, lump=lump, harvest=harvest)
        k = (bkey, reg.name, a, z, cur, contrib, json.dumps(bharvest, sort_keys=True))
        if k not in self.cache:
            stb, Ab, Rb = bspec
            fb, arm_b, _ = run_arm(reg, stb, Ab, Rb, DY, idx, months, contrib_real=c, lump=lump, harvest=bharvest)
            self.cache[k] = (fb, arm_b.stats)
        fb, sb = self.cache[k]
        return fs / fb, arm_s.stats, sb, fs, fb

    def lump_series(self, reg, spec, a, z, bkey='MKT', harvest=None):
        months = mrange(a, z)
        DY = self.D['dy'] if not bkey.startswith('NDX') else {m: NDX_DY / 12 for m in months}
        st, A, R = spec
        fin, arm, rec = run_arm(reg, st, A, R, DY, ONE, months, lump=1.0, harvest=harvest, record=True)
        out, prev = {}, 1.0
        for m in months:
            out[m] = rec[m] / prev - 1
            prev = rec[m]
        return out, fin


def dca_block(RN, reg, spec, bspec, first, last, cur='USD', bkey='MKT', harvest=None, bharvest=None, keep_windows=False):
    """20年の転がる窓（1月起点・毎月積立）・2007〜の一本・2007〜の10年窓"""
    out = {}
    rs, diag = [], []
    for a, z in dca_windows(first, last, 20):
        r, ss, sb, fs, fb = RN.pair(reg, spec, bspec, a, z, cur, True, bkey, harvest, bharvest)
        rs.append((a, round(r, 4)))
        diag.append((ss, sb, fs, fb))
    out['roll20'] = summarize_ratios(rs)
    if keep_windows:
        out['roll20_windows'] = rs
    if diag:
        def med(xs):
            xs = sorted(xs)
            return round(xs[len(xs) // 2], 4) if xs else None
        out['roll20_diag_median'] = {
            'nisa_share_end_s': med([d[0].get('nisa_end', 0) / d[0]['pre_liq'] for d in diag if d[0].get('pre_liq')]),
            'nisa_share_end_b': med([d[1].get('nisa_end', 0) / d[1]['pre_liq'] for d in diag if d[1].get('pre_liq')]),
            'tax_paid_over_final_s': med([d[0]['tax_paid'] / d[2] for d in diag]),
            'tax_paid_over_final_b': med([d[1]['tax_paid'] / d[3] for d in diag]),
            'costs_over_final_s': med([d[0]['costs'] / d[2] for d in diag]),
            'harvests_s': med([d[0]['harvests'] for d in diag]),
            'carry_expired_over_final_s': med([d[0]['carry_expired'] / d[2] for d in diag]),
        }
    if first <= 200701 and last >= 202412:
        r, ss, sb, fs, fb = RN.pair(reg, spec, bspec, 200701, last, cur, True, bkey, harvest, bharvest)
        out['hold_2007'] = {'from': 200701, 'to': last, 'ratio': round(r, 4),
                            'nisa_share_end_s': round(ss.get('nisa_end', 0) / ss['pre_liq'], 3) if ss.get('pre_liq') else None,
                            'tax_paid_over_final_s': round(ss['tax_paid'] / fs, 4), 'tax_paid_over_final_b': round(sb['tax_paid'] / fb, 4)}
        h10 = []
        for a, z in dca_windows(200701, last, 10):
            r, *_ = RN.pair(reg, spec, bspec, a, z, cur, True, bkey, harvest, bharvest)
            h10.append((a, round(r, 4)))
        out['hold_10y'] = summarize_ratios(h10)
    return out


def lump_grade(RN, reg, spec, bspec, first, last, bkey='MKT', harvest=None, bharvest=None):
    """一括の税引後（いま全部売ったら残る額）の月次リターンで mw_common.grade の材料を作る。期間ごとに口座を作り直す"""
    per = {'full': (first, last), 'train': (first, M.TRAIN_END), 'hold': (max(first, M.HOLD_START), last),
           'recent': (max(first, M.RECENT_START), last)}
    st = {}
    for k, (a, z) in per.items():
        if z - a < 200:          # 2年未満
            st[k] = None
            continue
        s, _ = RN.lump_series(reg, spec, a, z, bkey, harvest)
        b, _ = RN.lump_series(reg, bspec, a, z, bkey, bharvest)
        st[k] = M.excess_stats(s, b)
    out = []
    for a, z in lump_windows(first, last, 20):
        r, ss, sb, fs, fb = RN.pair(reg, spec, bspec, a, z, 'USD', False, bkey, harvest, bharvest)
        out.append((a // 100, round((fs ** (1 / 20) - fb ** (1 / 20)) * 100, 2)))
    if out:
        v = sorted(c for _, c in out)
        roll = {'windows': len(out), 'wins': sum(1 for _, c in out if c > 0), 'win_rate': round(sum(1 for _, c in out if c > 0) / len(out), 3),
                'median': v[len(v) // 2], 'worst': min(out, key=lambda x: x[1]), 'best': max(out, key=lambda x: x[1])}
    else:
        roll = None
    st['roll20'] = roll
    return st


def passes(block, fresh_ratio):
    r = block.get('roll20')
    if not r or r['n'] < 10:
        return None
    return bool(r['win_share'] >= 0.8 and r['median'] > 1 and fresh_ratio is not None and fresh_ratio > 1)


def run_all(D, ed, t0):
    RN = Runner(D)
    mkt = D['mkt']
    fx = D['fx']
    out = {'angle': ANGLE, 'prereg': PREREG, 'prereg_commit': git_sha(f'out/{PREREG}'), 'global_prereg': 'mw_prereg.json',
           'global_prereg_commit': git_sha('out/mw_prereg.json'), 'benchmark': 'French Mkt（Mkt-RF+RF・上限なしの時価加重）を指数ファンド（積み上げ型・年0.10%・配当の米国源泉10%は戻らない）で NISA から持ち続け、窓の終わりに税を払って全部売る',
           'sanity': {}, 'deviations': [], 'tested': []}
    san = out['sanity']
    san['selftest'] = selftest()
    san['cpi_filled_months'] = sorted(set(CPI_FILLED))
    out['deviations'].append('米国 CPI（CPIAUCNS）の 2025-10 が欠けていた（政府閉鎖で未公表）ため、最初の実行が KeyError で止まった。'
                             '前後の月の幾何補間で埋めて再実行した（積立額と NISA 枠の実質化だけに使う・リターンには使わない・結果を見る前の技術的な修正）')
    san['french_mkt_cagr_full'] = round(M.cagr(mkt) * 100, 2)
    san['french_mkt_cagr_2007'] = round(M.cagr(M.window(mkt, M.HOLD_START)) * 100, 2)
    dy = D['dy']
    dec = {}
    for m, v in dy.items():
        dec.setdefault(m // 1000 * 10, []).append(v)
    san['market_div_yield_by_decade_pct_per_year'] = {d: round(S.mean(v) * 1200, 2) for d, v in sorted(dec.items())}
    mj = to_jpy(mkt, fx)
    san['french_mkt_cagr_2007_jpy'] = round(M.cagr(M.window(mj, M.HOLD_START)) * 100, 2)
    san['usdjpy_200612_202608'] = [fx[200612], fx[202608]]
    san['cop_direction'] = D['cop_dir']
    san['p1_info'] = D['p1_info']
    # 元の角度の数字の再現（税前・同じ作り方）
    rep = {}
    srcj = {}
    for k, v in ed.items():
        g = v['gross'] if v['kind'] == 'multi' else v['R']
        h = M.excess_stats(g, mkt, a=M.HOLD_START)
        f = M.excess_stats(g, mkt)
        mod, rid = v['src_ref']
        if mod not in srcj:
            srcj[mod] = json.load(open(os.path.join(M.BASE, 'out', mod + '.json')))
        ref = None
        for t in srcj[mod].get('tested', []):
            nm = t.get('name') or t.get('id')
            if nm == rid:
                if 'hold' in t and isinstance(t['hold'], dict):
                    ref = {'hold_ex': t['hold'].get('ex_ann'), 'hold_t': t['hold'].get('t'), 'grade': t.get('grade')}
                else:
                    ref = {'hold_ex': t.get('hold_ex'), 'hold_t': t.get('hold_t'), 'grade': t.get('grade')}
                break
        rep[k] = {'mine_hold_ex': h and h['ex_ann'], 'mine_hold_t': h and h['t'], 'mine_full_ex': f and f['ex_ann'], 'mine_full_t': f and f['t'],
                  'mine_from': v['start'], 'source': f'{mod}:{rid}', 'source_values': ref}
    san['reproduction_pretax_vs_source'] = rep
    log('再現', json.dumps(rep, ensure_ascii=False))
    bspec = bench_spec(mkt)
    bspec_j = spec_jpy(bspec, fx)
    edges_out = {}
    for name in PRIMARY + SECONDARY:
        e = ed[name]
        spec = arm_spec(e, mkt)
        spec_j = spec_jpy(spec, fx)
        first, last = e['start'], min(e['end'], FR_END)
        rec = {'description': e['desc'], 'primary': e['primary'], 'source': e['src_ref'], 'from': first, 'to': last,
               'turnover_or_realization': e.get('T') if e['kind'] == 'single' else round(S.mean(e['trades'][k] for k in e['trades']) / 2 * 12, 2),
               'dca': {}, 'dca_jpy': {}, 'lump': {}}
        for rg in DCA_REGIMES:
            blk = dca_block(RN, REG[rg], spec, bspec, first, last, keep_windows=(rg in ('R2_real', 'R3_taxable', 'R1_nisa_unlimited')))
            rec['dca'][rg] = blk
            out['tested'].append({'name': f'{name}__dca__{rg}', 'family': 'dca_primary' if e['primary'] else 'dca_secondary', 'edge': name,
                                  'regime': rg, 'kind': 'dca20_ratio',
                                  'roll20': blk.get('roll20'), 'hold_2007': (blk.get('hold_2007') or {}).get('ratio'),
                                  'hold_10y_median': (blk.get('hold_10y') or {}).get('median')})
            r = blk.get('roll20') or {}
            log(f'{name:15s} {rg:22s} 20年窓 n={r.get("n")} 勝率={r.get("win_share")} 中央={r.get("median")} 最悪={r.get("worst")} 2007〜={(blk.get("hold_2007") or {}).get("ratio")}  ({time.time() - t0:.0f}s)')
        for rg in JPY_REGIMES:
            if first <= 200701:
                blk = dca_block(RN, REG[rg], spec_j, bspec_j, max(first, 200701), last, cur='JPY')
                rec['dca_jpy'][rg] = {k: blk.get(k) for k in ('hold_2007', 'hold_10y')}
                out['tested'].append({'name': f'{name}__dca_jpy__{rg}', 'family': 'jpy_fresh', 'edge': name, 'regime': rg, 'kind': 'dca_ratio_jpy',
                                      'hold_2007': (blk.get('hold_2007') or {}).get('ratio'), 'hold_10y_median': (blk.get('hold_10y') or {}).get('median')})
        for rg in LUMP_REGIMES:
            rec['lump'][rg] = lump_grade(RN, REG[rg], spec, bspec, first, last)
        edges_out[name] = rec
    # 一括の格付け（族ごとに Holm）
    for rg in LUMP_REGIMES:
        for fam, members in (('primary', PRIMARY), ('secondary', SECONDARY)):
            ps = {n: (edges_out[n]['lump'][rg].get('hold') or {}).get('p') for n in members}
            hp = M.holm({k: v for k, v in ps.items() if v is not None})
            for n in members:
                L = edges_out[n]['lump'][rg]
                g, c = M.grade(L.get('full'), L.get('train'), L.get('hold'), L.get('roll20'), cost_hold=L.get('hold'), repl=None,
                               family_holm_p=hp.get(n), leveraged_or_timing=False)
                L['holm_p_hold'] = hp.get(n)
                L['grade'], L['criteria'] = g, c
                out['tested'].append({'name': f'{n}__lump__{rg}', 'family': f'lump_{fam}_{rg}', 'edge': n, 'regime': rg, 'kind': 'lump_grade',
                                      'primary': fam == 'primary' and rg == 'R3_taxable', 'grade': g, 'criteria': c,
                                      'full': L.get('full'), 'train': L.get('train'), 'hold': L.get('hold'), 'recent': L.get('recent'),
                                      'roll20': L.get('roll20'), 'holm_p_hold': hp.get(n)})
                log(f'格付け {n:15s} {rg:18s} {g}  保有 {(L.get("hold") or {}).get("ex_ann")} t={(L.get("hold") or {}).get("t")}  20年窓 {(L.get("roll20") or {}).get("win_rate")}')
    # 判定（事前登録の規則）
    verdicts = {}
    for name in PRIMARY + SECONDARY:
        rec = edges_out[name]
        fr = FRESH_OF.get(name, name)
        fresh = edges_out.get(fr, rec)

        def fresh_ratio(rg):
            return (fresh['dca'][rg].get('hold_2007') or {}).get('ratio')
        p = {rg: passes(rec['dca'][rg], fresh_ratio(rg)) for rg in DCA_REGIMES}
        jr = (fresh['dca_jpy'].get('R2_real', {}).get('hold_2007') or {}).get('ratio')
        if p['R2_real'] is None:
            v = '判定不能（20年窓が10本未満）'
        elif p['R2_real'] and jr is not None and jr > 1:
            v = '残る'
        elif p['R1_nisa_unlimited']:
            v = 'NISA の中だけなら残る'
        else:
            v = '残らない'
        verdicts[name] = {'verdict': v, 'pass_by_regime': p, 'jpy_R2_2007_ratio': jr, 'fresh_series': fr,
                          'R2_roll20': rec['dca']['R2_real'].get('roll20'), 'R2_2007': fresh_ratio('R2_real'),
                          'R1_roll20': rec['dca']['R1_nisa_unlimited'].get('roll20'), 'R0_roll20': rec['dca']['R0_pretax'].get('roll20'),
                          'R3_roll20': rec['dca']['R3_taxable'].get('roll20')}
        log('判定', name, v, json.dumps(p, ensure_ascii=False))
    out['edges'] = edges_out
    out['verdicts'] = verdicts
    # ── 損出し
    ndx = ndx_series(D)
    H_UNDER = {'MKT_fund': (mkt, 'fund', 'MKT'), 'MKT_etf': (mkt, 'direct', 'MKT'), 'NDX_fund': (ndx, 'fund', 'NDX')}
    H_VAR = {'L10': {'L': 0.10}, 'L20': {'L': 0.20}, 'L10G': {'L': 0.10, 'gain': True}, 'L20G': {'L': 0.20, 'gain': True}}
    H_REG = ['R3_taxable', 'R2_real', 'R3_taxable_tax25']
    hv_out = {}
    hps = {}
    for un, (ser, veh, bkey) in H_UNDER.items():
        spec_ = {'vehicle': veh, 'fee': BENCH_FEE, 'frames': ('NT', 'NG')}
        A = {'IDX': spec_, 'IDX_TWIN': spec_}
        R = {'IDX': ser, 'IDX_TWIN': ser}
        sp = (BENCH_ST, A, R)
        spj = spec_jpy(sp, fx)
        first, last = min(ser), max(ser)
        for vn, hv in H_VAR.items():
            h = dict(hv, asset='IDX')
            rec = {'underlying': un, 'variant': vn, 'dca': {}, 'dca_jpy': {}}
            for rg in H_REG:
                blk = dca_block(RN, REG[rg], sp, sp, first, last, bkey=bkey + '_' + un, harvest=h, bharvest=None)
                rec['dca'][rg] = blk
                out['tested'].append({'name': f'H_{un}_{vn}__dca__{rg}', 'family': 'harvest', 'kind': 'dca20_ratio_vs_no_harvest', 'regime': rg,
                                      'roll20': blk.get('roll20'), 'hold_2007': (blk.get('hold_2007') or {}).get('ratio'),
                                      'hold_10y_median': (blk.get('hold_10y') or {}).get('median'), 'diag': blk.get('roll20_diag_median')})
                r = blk.get('roll20') or {}
                log(f'損出し {un} {vn} {rg}: n={r.get("n")} 勝率={r.get("win_share")} 中央={r.get("median")} 最悪={r.get("worst")} 2007〜={(blk.get("hold_2007") or {}).get("ratio")} 回数中央={(blk.get("roll20_diag_median") or {}).get("harvests_s")}')
            for rg in ('R3_taxable', 'R2_real'):
                blk = dca_block(RN, REG[rg], spj, spj, max(first, 200701), last, cur='JPY', bkey=bkey + '_' + un, harvest=h, bharvest=None)
                rec['dca_jpy'][rg] = {k: blk.get(k) for k in ('hold_2007', 'hold_10y')}
                out['tested'].append({'name': f'H_{un}_{vn}__dca_jpy__{rg}', 'family': 'harvest_jpy', 'kind': 'dca_ratio_jpy', 'regime': rg,
                                      'hold_2007': (blk.get('hold_2007') or {}).get('ratio')})
            L = lump_grade(RN, REG['R3_taxable'], sp, sp, first, last, bkey=bkey + '_' + un, harvest=h, bharvest=None)
            rec['lump_R3'] = L
            hps[f'H_{un}_{vn}'] = (L.get('hold') or {}).get('p')
            hv_out[f'H_{un}_{vn}'] = rec
    hp = M.holm({k: v for k, v in hps.items() if v is not None})
    hverd = {}
    for k, rec in hv_out.items():
        L = rec['lump_R3']
        g, c = M.grade(L.get('full'), L.get('train'), L.get('hold'), L.get('roll20'), cost_hold=L.get('hold'), repl=None,
                       family_holm_p=hp.get(k), leveraged_or_timing=False)
        L['grade'], L['criteria'], L['holm_p_hold'] = g, c, hp.get(k)
        out['tested'].append({'name': f'{k}__lump__R3_taxable', 'family': 'harvest_lump', 'kind': 'lump_grade_vs_no_harvest', 'grade': g,
                              'criteria': c, 'full': L.get('full'), 'train': L.get('train'), 'hold': L.get('hold'), 'recent': L.get('recent'),
                              'roll20': L.get('roll20'), 'holm_p_hold': hp.get(k)})
        b3 = rec['dca']['R3_taxable']
        jr = (rec['dca_jpy']['R3_taxable'].get('hold_2007') or {}).get('ratio')
        ok = passes(b3, (b3.get('hold_2007') or {}).get('ratio'))
        r = b3.get('roll20') or {}
        if ok is None:
            v = '判定不能'
        elif ok and jr is not None and jr > 1:
            v = '小さくても確実な上乗せ'
        elif r.get('median', 1) > 1:
            v = '平均では僅かに得だが確実ではない'
        else:
            v = '上乗せにならない（損か0）'
        hverd[k] = {'verdict': v, 'R3_roll20': r, 'R3_2007': (b3.get('hold_2007') or {}).get('ratio'), 'R3_jpy_2007': jr,
                    'R2_roll20': rec['dca']['R2_real'].get('roll20'), 'lump_grade': g}
        log('損出し判定', k, v)
    out['harvest'] = hv_out
    out['harvest_verdicts'] = hverd
    out['n_tested'] = len(out['tested'])
    out['log_tail'] = LOG[-60:]
    out['runtime_s'] = round(time.time() - t0, 1)
    p = M.save(OUT, out)
    log('書いた', p, os.path.getsize(p), 'bytes', f'{time.time() - t0:.0f}s')



# ───────────────────────── 事前登録2（探索）: X1 置き場所・X2 帯 ─────────────────────────
X1_REGIMES = ['L1_real', 'L1_real_tax25', 'L1_real_100k', 'L1_real_300k']


def mk_buffer(E, names, K, exit_rank, score):
    """帯つきの上位 K: 持っているものは順位が exit_rank より下がるまで持つ。続けて持つものは値動きのまま、
    出たものの重みを入ったものへ等分。t 月末までのデータだけ（H.get は t を超えると止まる）"""
    state = {'w': None, 't': None}

    def f(H):
        sc = (lambda s: H.cum(s, 12)) if score == 'r12' else H.blend
        avail = [s for s in names if H.R.get(s) and E.alive_next(H, s) and sc(s) is not None]
        if len(avail) < 20:
            return None
        ranked = [n for _, _, n in sorted((-sc(s), i, s) for i, s in enumerate(avail))]
        rank = {s: i + 1 for i, s in enumerate(ranked)}
        prev = state['w']
        if prev is None or state['t'] != madd(H.t, -1):
            w = {s: 1 / K for s in ranked[:K]}
        else:
            g = {s: prev[s] * (1 + H.get(s, H.t)) for s in prev}
            tot = sum(g.values())
            g = {s: v / tot for s, v in g.items()}
            keep = {s: v for s, v in g.items() if rank.get(s, 10 ** 9) <= exit_rank}
            freed = 1 - sum(keep.values())
            need = K - len(keep)
            ent = [s for s in ranked if s not in keep][:need] if need > 0 else []
            w = dict(keep)
            for s in ent:
                w[s] = freed / len(ent)
            if not ent and freed > 1e-12:
                t2 = sum(w.values())
                w = {s: v / t2 for s, v in w.items()}
        state['w'], state['t'] = w, H.t
        return w
    return f


def build_x2(D):
    E = D['E']
    src, rf = D['src'], D['rf']
    fseld = list(E.FSEL) + ['AV_' + t for t in E.DEAD]
    R4 = {'TBILL': rf}
    R4.update({s: src[s] for s in fseld if src.get(s)})
    RK = {'TBILL': rf}
    RK.update({s: src[s] for s in E.RAKU if src.get(s)})
    ed = {}
    for nm, R, names, sc, base in (('X2_fsel_bl_buf', R4, fseld, 'blend', 'E4_fsel_top3'), ('X2_fsel_r12_buf', R4, fseld, 'r12', 'E4r_fsel_r12'),
                                   ('X2_raku_r12_buf', RK, list(E.RAKU), 'r12', 'E3k_raku_r12'), ('X2_raku_bl_buf', RK, list(E.RAKU), 'blend', 'E4k_raku_bl')):
        g, n, ns, wp, tr = E.run(R, mk_buffer(E, names, 3, 6, sc), dynamic=True)
        ed[nm] = dict(kind='multi', primary=False, vehicle='direct', fee=0.0, R=R, wpath=wp, gross=g, trades=tr, cs=E.C_SIDE,
                      start=min(g), end=max(g), base=base,
                      desc=f'探索 X2 {nm}: {base} の帯版（上位3を持ち、6位より下がるまで売らない・続けて持つものはドリフト）',
                      src_ref=('mw_etf_tactical', None))
    return ed


def eval_block(RN, name, e, mkt, fx, regimes, jpy_regimes, lump_regimes, tested, fam):
    spec = arm_spec(e, mkt)
    spec_j = spec_jpy(spec, fx)
    bspec = bench_spec(mkt)
    bspec_j = spec_jpy(bspec, fx)
    first, last = e['start'], min(e['end'], FR_END)
    rec = {'description': e['desc'], 'from': first, 'to': last,
           'turnover_or_realization': e.get('T') if e['kind'] == 'single' else round(S.mean(e['trades'][k] for k in e['trades']) / 2 * 12, 2),
           'dca': {}, 'dca_jpy': {}, 'lump': {}}
    for rg in regimes:
        blk = dca_block(RN, REG[rg], spec, bspec, first, last, keep_windows=rg in ('R2_real', 'L1_real', 'R3_taxable'))
        rec['dca'][rg] = blk
        tested.append({'name': f'{name}__dca__{rg}', 'family': fam, 'edge': name, 'regime': rg, 'kind': 'dca20_ratio',
                       'roll20': blk.get('roll20'), 'hold_2007': (blk.get('hold_2007') or {}).get('ratio'),
                       'hold_10y_median': (blk.get('hold_10y') or {}).get('median')})
        r = blk.get('roll20') or {}
        log(f'{name:16s} {rg:22s} 20年窓 n={r.get("n")} 勝率={r.get("win_share")} 中央={r.get("median")} 最悪={r.get("worst")} 2007〜={(blk.get("hold_2007") or {}).get("ratio")}')
    for rg in jpy_regimes:
        if first <= 200701:
            blk = dca_block(RN, REG[rg], spec_j, bspec_j, max(first, 200701), last, cur='JPY')
            rec['dca_jpy'][rg] = {k: blk.get(k) for k in ('hold_2007', 'hold_10y')}
            tested.append({'name': f'{name}__dca_jpy__{rg}', 'family': fam + '_jpy', 'edge': name, 'regime': rg, 'kind': 'dca_ratio_jpy',
                           'hold_2007': (blk.get('hold_2007') or {}).get('ratio'), 'hold_10y_median': (blk.get('hold_10y') or {}).get('median')})
            log(f'{name:16s} 円 {rg:18s} 2007〜={(blk.get("hold_2007") or {}).get("ratio")}')
    for rg in lump_regimes:
        rec['lump'][rg] = lump_grade(RN, REG[rg], spec, bspec, first, last)
    return rec


def run_part2(D, ed, t0):
    RN = Runner(D)
    mkt, fx = D['mkt'], D['fx']
    p = os.path.join(M.BASE, 'out', OUT)
    out = json.load(open(p))
    tested = out['tested']
    n0 = len(tested)
    p2 = {'prereg2': 'mw_jp_aftertax_prereg2.json', 'prereg2_commit': git_sha('out/mw_jp_aftertax_prereg2.json')}
    x2 = build_x2(D)
    p2['x2_turnover_oneway_per_year'] = {k: round(S.mean(v['trades'][m] for m in v['trades']) / 2 * 12, 2) for k, v in x2.items()}
    p2['x2_pretax_hold_vs_mkt_gross'] = {k: M.excess_stats(v['gross'], mkt, a=M.HOLD_START) for k, v in x2.items()}
    allE = dict(ed)
    allE.update(x2)
    # X1: 置き場所（主と副の8本＋X2 の4本）
    x1 = {}
    for name in PRIMARY + SECONDARY + list(x2):
        if name == 'E3e_spdr_mom' and False:
            continue
        x1[name] = eval_block(RN, name, allE[name], mkt, fx, X1_REGIMES, ['L1_real'], [], tested, 'X1_location')
    # X2: 帯（主の族と同じ全部）
    x2r = {}
    for name in x2:
        x2r[name] = eval_block(RN, name, x2[name], mkt, fx, DCA_REGIMES, JPY_REGIMES, LUMP_REGIMES, tested, 'X2_buffer')
    for rg in LUMP_REGIMES:
        ps = {n: (x2r[n]['lump'][rg].get('hold') or {}).get('p') for n in x2r}
        hp = M.holm({k: v for k, v in ps.items() if v is not None})
        for n in x2r:
            L = x2r[n]['lump'][rg]
            g, c = M.grade(L.get('full'), L.get('train'), L.get('hold'), L.get('roll20'), cost_hold=L.get('hold'), repl=None,
                           family_holm_p=hp.get(n), leveraged_or_timing=False)
            L['holm_p_hold'], L['grade'], L['criteria'] = hp.get(n), g, c
            tested.append({'name': f'{n}__lump__{rg}', 'family': f'X2_lump_{rg}', 'edge': n, 'regime': rg, 'kind': 'lump_grade',
                           'exploratory': True, 'grade': g, 'criteria': c, 'full': L.get('full'), 'train': L.get('train'),
                           'hold': L.get('hold'), 'recent': L.get('recent'), 'roll20': L.get('roll20'), 'holm_p_hold': hp.get(n)})
            log(f'格付け(探索) {n:16s} {rg:18s} {g}  保有 {(L.get("hold") or {}).get("ex_ann")} t={(L.get("hold") or {}).get("t")}')
    # 判定
    fresh_map = dict(FRESH_OF)
    v1 = {}
    for name, rec in x1.items():
        fr = fresh_map.get(name, name)
        frec = x1.get(fr, rec)
        fratio = (frec['dca']['L1_real'].get('hold_2007') or {}).get('ratio')
        ok = passes(rec['dca']['L1_real'], fratio)
        jr = (frec['dca_jpy'].get('L1_real', {}).get('hold_2007') or {}).get('ratio')
        if ok is None:
            v = '判定不能（20年窓が10本未満）'
        elif ok and jr is not None and jr > 1:
            v = '置き場所を分ければ残る'
        else:
            v = '置き場所を分けても残らない'
        v1[name] = {'verdict': v, 'L1_roll20': rec['dca']['L1_real'].get('roll20'), 'L1_2007': fratio, 'L1_jpy_2007': jr,
                    'pass_by_regime': {rg: passes(rec['dca'][rg], (frec['dca'][rg].get('hold_2007') or {}).get('ratio')) for rg in X1_REGIMES},
                    'hold_10y': rec['dca']['L1_real'].get('hold_10y')}
        log('X1 判定', name, v)
    v2 = {}
    for name, rec in x2r.items():
        fr_ = lambda rg: (rec['dca'][rg].get('hold_2007') or {}).get('ratio')
        pp = {rg: passes(rec['dca'][rg], fr_(rg)) for rg in DCA_REGIMES}
        jr = (rec['dca_jpy'].get('R2_real', {}).get('hold_2007') or {}).get('ratio')
        if pp['R2_real'] is None:
            v = '判定不能（20年窓が10本未満）'
        elif pp['R2_real'] and jr is not None and jr > 1:
            v = '残る'
        elif pp['R1_nisa_unlimited']:
            v = 'NISA の中だけなら残る'
        else:
            v = '残らない'
        v2[name] = {'verdict': v, 'pass_by_regime': pp, 'jpy_R2_2007_ratio': jr, 'R2_roll20': rec['dca']['R2_real'].get('roll20'),
                    'R0_roll20': rec['dca']['R0_pretax'].get('roll20'), 'R1_roll20': rec['dca']['R1_nisa_unlimited'].get('roll20'),
                    'R3_roll20': rec['dca']['R3_taxable'].get('roll20'), 'R2_2007': fr_('R2_real'), 'R0_2007': fr_('R0_pretax')}
        log('X2 判定', name, v)
    p2['x1'] = x1
    p2['x2'] = x2r
    p2['x1_verdicts'] = v1
    p2['x2_verdicts'] = v2
    p2['n_tested_added'] = len(tested) - n0
    out['part2'] = p2
    out['n_tested'] = len(tested)
    out['log_tail_part2'] = LOG[-80:]
    M.save(OUT, out)
    log('書いた part2', p, os.path.getsize(p), f'{time.time() - t0:.0f}s')


# ───────────────────────── 本番 ─────────────────────────
def main():
    if '--selftest' in sys.argv:
        r = selftest()
        print(json.dumps(r, ensure_ascii=False, indent=1))
        if not all(r.values()):
            raise SystemExit('selftest 失敗')
        return
    t0 = time.time()
    D = load_all()
    ed = build_edges(D)
    if '--dry' in sys.argv:
        info = {k: {'start': v['start'], 'end': v['end'], 'months': len(v['gross'] if v['kind'] == 'multi' else v['R'])} for k, v in ed.items()}
        info['dy'] = [min(D['dy']), max(D['dy'])]
        info['fx'] = [min(D['fx']), max(D['fx'])]
        info['cpi'] = [min(D['cpi']), max(D['cpi'])]
        print(json.dumps(info, ensure_ascii=False, indent=1))
        return
    if '--part2' in sys.argv:
        run_part2(D, ed, t0)
        return
    run_all(D, ed, t0)


if __name__ == '__main__':
    main()
