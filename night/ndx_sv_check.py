#!/usr/bin/env python3
"""night/ndx_sv_check.py — NASDAQ100 と米国の小型バリューは、市場の主役（業種）が入れ替わっても市場に勝ってきたか
（2026-11-01・参考・判定なし・配分は変えない）

ユーザー「では市場が入れ替わってもパフォーマンスをだすNASDAQと小型バリューは貴重なのでは？」
★系列・期間・物差し・比べる形はこの頭に書いたとおりで、結果を見る前にこのファイルをコミットする。勝ち負けの線（判定）は付けない＝並べるだけ。

系列（月次・ドル・配当込み・費用の前＝器は経費率を足し戻す・bestfund_data.build_chain のつなぎをそのまま使う）:
  市場 MKT＝French の米国市場（CRSP 全上場・時価加重・1926-07〜）
  NASDAQ100 NDX＝QQQ 1999-04〜 ← ^NDX の価格＋配当の置き値 1985-11〜 ← 代わり: French のテック3業種（時価加重）65%＋市場35% 1926-07〜
  小型バリュー SV＝VBR 2004-02〜 ← VISVX 1998-06〜 ← French の SMALL HiBM（6_Portfolios_2x3・時価加重・紙の上）1926-07〜
  混ぜた形（毎月この比に戻す）: NDX70/SV30・NDX50/SV50
期間: 全期間 1926-07〜（代わりと紙の上を含む）／本物の NASDAQ100 の期間 1985-11〜／本物の小型バリューの器の期間 1998-06〜。
  最後の月は3系列（MKT・NDX・SV）がそろう月
測るもの（市場 MKT との差＝幾何の年率の差・%pt/年）:
  ① 暦の10年ごと（1926-07〜1929-12・1930年代 … 2010年代・2020-01〜最後の月）の年率と市場との差。代わり・紙の上の期間を印で示す
  ② 転がる10年・20年（1か月ずつずらす）: 市場に勝った窓の割合・中央・下位10%点・最悪・最良（3つの期間それぞれ）
  ③ 補い合うか: 月次リターンの相関（NDX と SV）・転がる10年の市場との差の相関・10年の窓の4つの場合
     （両方勝ち／NDX だけ勝ち／SV だけ勝ち／両方負け）の割合（全期間と本物の NASDAQ100 の期間）
  ④ 主役が入れ替わった後: out/industry_peak.json の「山」（比重が過去最大を付けた業種）のうち10年先までデータのある山で、
     最初の記録の年の翌年1月からの10年の市場との差（NDX・SV・混ぜた形）。山の数・市場に勝った山の数・中央・山ごとの表。
     テックの山（Hardw・Softw・Chips）とそれ以外の山に分けても出す。（参考: 最後の記録の年の翌年から＝どれが最後かは後で分かる＝後知恵）
  ⑤ 20年の積立（毎月の初めに同額）の最終額÷同じ窓の市場の積立の最終額: 1以上の割合・中央・下位10%点・最悪（全期間と本物の NASDAQ100 の期間）
  ⑥ 器の確かめ（参考）: build_chain のつなぎ目の点検（VBR・VISVX・SMALL HiBM／QQQ・^NDX・代わりの重なる期間の年率と相関）・
     費用込みの VBR（2004-02〜）と QQQ（1999-04〜）の市場との差
  ⑦ 今の配分の物差しでの形の比べ（best15r と同じ: 元の物差し unx_assets.measure の USD・崩れあり／業種の基礎率の物差し best15r の FastBR
     〔主＝20年の値〕と感度6本の今との差／100年の代用 century_monthly〔VBR は SMALL HiBM〕／B の世界の記録の割り引きとの重なり／中身の集中）:
     今 NASDAQ100 50/SMH 20/ITA 20/XLV 10 ／ 中1 NASDAQ100 50/ITA 25/XLV 25 ／ 小1 NASDAQ100 50/VBR 20/ITA 20/XLV 10（SMH を VBR へ）／
     小2 NASDAQ100 50/VBR 30/ITA 10/XLV 10 ／ 小3 NASDAQ100 60/VBR 40 ／ 小4 NASDAQ100 50/VBR 50
（事後・結果を見た後に足した・判定に使わない）③b 本物どうしの期間（1998-06〜）の10年の窓の相関と両方負け／5年の窓の両方負けと混ぜた形が市場に勝った割合／
  ⑦b 小型バリューの上乗せが消えていたら: 基礎率の物差しで (S1) B の世界の VBR から100年の小型バリューの上乗せ（unx_assets の B_X×0.5）を引く・
  (S2) さらに C・D の VBR を VOO と同じにする（未来の3つの世界のどれも小型バリューに上乗せを置かない）
⚠ 限界: NASDAQ100 の1985年より前は代わり（つなぎ目の点検で本物の ^NDX より 1985-11〜 で年約1.5pt 低い）・SMALL HiBM は紙の上
  （売買の費用なし・VISVX は重なる期間で年約1pt 低い）・転がる窓は重なる（独立な数は少ない）・山は少なく時期が重なる・米国だけ・
  混ぜた形の比は私が決めた・税は入らない
使い方: python3 night/ndx_sv_check.py → out/ndx_sv_check.json
"""
import contextlib, io, json, math, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'ndx_sv_check.json')

MIXES = {'NDX70/SV30': {'NDX': .7, 'SV': .3}, 'NDX50/SV50': {'NDX': .5, 'SV': .5}}
SERIES = ['NDX', 'SV', 'NDX70/SV30', 'NDX50/SV50']
NDX_REAL, SV_REAL = 198511, 199806
PERIODS = {'全期間（1926-07〜・代わりと紙の上を含む）': 192607, '本物の NASDAQ100 の期間（1985-11〜）': NDX_REAL,
           '本物の小型バリューの器の期間（1998-06〜）': SV_REAL}
TECH_IND = ('Hardw', 'Softw', 'Chips')
FORMS = {'今 NASDAQ100 50/SMH 20/ITA 20/XLV 10': {'QQQM': 50, 'SMH': 20, 'ITA': 20, 'XLV': 10},
         '中1 NASDAQ100 50/ITA 25/XLV 25': {'QQQM': 50, 'ITA': 25, 'XLV': 25},
         '小1 NASDAQ100 50/VBR 20/ITA 20/XLV 10': {'QQQM': 50, 'VBR': 20, 'ITA': 20, 'XLV': 10},
         '小2 NASDAQ100 50/VBR 30/ITA 10/XLV 10': {'QQQM': 50, 'VBR': 30, 'ITA': 10, 'XLV': 10},
         '小3 NASDAQ100 60/VBR 40': {'QQQM': 60, 'VBR': 40},
         '小4 NASDAQ100 50/VBR 50': {'QQQM': 50, 'VBR': 50}}


def nxt(m):
    return m + 1 if m % 100 < 12 else (m // 100 + 1) * 100 + 1


def mrange(a, b):
    out = []
    while a <= b:
        out.append(a)
        a = nxt(a)
    return out


def add_months(m, k):
    t = (m // 100) * 12 + (m % 100 - 1) + k
    return (t // 12) * 100 + t % 12 + 1


def geo(r, ks):
    return math.exp(math.fsum(math.log1p(r[k]) for k in ks) * 12 / len(ks)) - 1


def pct(x, d=2):
    return None if x is None else round(100 * x, d)


def stats(xs, d=2):
    if not xs:
        return None
    a = np.array(xs)
    return dict(窓=len(xs), 市場に勝った割合=round(float((a > 0).mean()), 3), 中央=round(100 * float(np.median(a)), d),
                下位10パーセント点=round(100 * float(np.percentile(a, 10)), d), 最悪=round(100 * float(a.min()), d),
                最良=round(100 * float(a.max()), d))


def ratio_stats(xs):
    if not xs:
        return None
    a = np.array(xs)
    return dict(窓=len(xs), 一以上の割合=round(float((a >= 1).mean()), 3), 中央=round(float(np.median(a)), 3),
                下位10パーセント点=round(float(np.percentile(a, 10)), 3), 最悪=round(float(a.min()), 3), 最良=round(float(a.max()), 3))


def load():
    import bestfund_data as D
    mkt = D.french_mkt()
    ndx, ndx_segs, ndx_chk = D.build_chain('NDX')
    sv, sv_segs, sv_chk = D.build_chain('SMALLV')
    last = min(max(mkt), max(ndx), max(sv))
    ks = [m for m in mrange(192607, last) if m in mkt and m in ndx and m in sv]
    if len(ks) != len(mrange(192607, last)):
        raise SystemExit(f'月が欠けている: {len(ks)} 対 {len(mrange(192607, last))}')
    r = {'MKT': {m: mkt[m] for m in ks}, 'NDX': {m: ndx[m] for m in ks}, 'SV': {m: sv[m] for m in ks}}
    for nm, w in MIXES.items():
        r[nm] = {m: sum(w[k] * r[k][m] for k in w) for m in ks}
    # 費用込みの器（参考）
    net = {}
    for t in ('VBR', 'QQQ'):
        s = D.yahoo_tr(t)
        net[t] = {m: s[m] for m in ks if m in s}
    return r, ks, dict(ndx=dict(segs=ndx_segs, checks=ndx_chk), sv=dict(segs=sv_segs, checks=sv_chk)), net


class Roll:
    """1つの月の並び ks の上で、各系列の対数の累積和（転がる年率と積立を速く出す）"""

    def __init__(self, r, ks):
        self.ks, self.ix = ks, {m: i for i, m in enumerate(ks)}
        self.S = {k: np.concatenate([[0.0], np.cumsum(np.log1p([v[m] for m in ks]))]) for k, v in r.items()}
        self.T = {k: np.concatenate([[0.0], np.cumsum(np.exp(-s[:-1]))]) for k, s in self.S.items()}

    def ann(self, k, i, n):
        return math.exp((self.S[k][i + n] - self.S[k][i]) * 12 / n) - 1

    def dca(self, k, i, n):
        """毎月の初めに1を入れて n か月の最終額"""
        return math.exp(self.S[k][i + n]) * (self.T[k][i + n] - self.T[k][i])


def decades(r, ks, last):
    rows = []
    spans = [(192607, 192912, '1926-07〜1929')] + [(y * 100 + 1, (y + 9) * 100 + 12, f'{y}年代') for y in range(1930, 2020, 10)]
    spans.append((202001, last, f'2020-01〜{str(last)[:4]}-{str(last)[4:]}'))
    for a, b, lab in spans:
        mm = [m for m in ks if a <= m <= b]
        mk = geo(r['MKT'], mm)
        row = dict(時代=lab, 月数=len(mm), 市場の年率=pct(mk))
        for k in SERIES:
            g = geo(r[k], mm)
            row[k] = dict(年率=pct(g), 市場との差=pct(g - mk))
        row['NDX の出所'] = '代わり' if b < NDX_REAL else ('代わり＋本物' if a < NDX_REAL else '本物')
        row['SV の出所'] = '紙の上' if b < SV_REAL else ('紙の上＋器' if a < SV_REAL else '器')
        rows.append(row)
    return rows


def rolling(R, ks, last):
    out = {}
    for pn, p0 in PERIODS.items():
        out[pn] = {}
        i0 = R.ix[p0]
        for n, lab in ((120, '10年'), (240, '20年')):
            idx = range(i0, len(ks) - n + 1)
            if len(idx) <= 0:
                continue
            res = {}
            for k in SERIES:
                ex = [R.ann(k, i, n) - R.ann('MKT', i, n) for i in idx]
                res[k] = stats(ex)
            res['起点'] = f'{ks[i0]}〜{ks[idx[-1]]}'
            out[pn][lab] = res
    return out


def complement(r, R, ks):
    out = {}
    for pn, p0 in list(PERIODS.items())[:2]:
        i0 = R.ix[p0]
        mm = ks[i0:]
        a = np.array([r['NDX'][m] for m in mm]); b = np.array([r['SV'][m] for m in mm])
        n = 120
        idx = range(i0, len(ks) - n + 1)
        en = np.array([R.ann('NDX', i, n) - R.ann('MKT', i, n) for i in idx])
        es = np.array([R.ann('SV', i, n) - R.ann('MKT', i, n) for i in idx])
        em = {k: np.array([R.ann(k, i, n) - R.ann('MKT', i, n) for i in idx]) for k in MIXES}
        out[pn] = dict(月次リターンの相関=round(float(np.corrcoef(a, b)[0, 1]), 3),
                       転がる10年の市場との差の相関=round(float(np.corrcoef(en, es)[0, 1]), 3),
                       十年の窓=len(en),
                       両方勝ち=round(float(((en > 0) & (es > 0)).mean()), 3),
                       NDXだけ勝ち=round(float(((en > 0) & (es <= 0)).mean()), 3),
                       SVだけ勝ち=round(float(((en <= 0) & (es > 0)).mean()), 3),
                       両方負け=round(float(((en <= 0) & (es <= 0)).mean()), 3),
                       混ぜた形が市場に勝った割合={k: round(float((v > 0).mean()), 3) for k, v in em.items()},
                       NDXが負けた窓での混ぜた形の市場との差の中央={k: pct(float(np.median(v[en <= 0])) if (en <= 0).any() else None) for k, v in em.items()},
                       NDXが負けた窓でのSVの市場との差の中央=pct(float(np.median(es[en <= 0])) if (en <= 0).any() else None),
                       SVが負けた窓でのNDXの市場との差の中央=pct(float(np.median(en[es <= 0])) if (es <= 0).any() else None))
    return out


def posthoc(R, ks):
    """事後（結果を見た後に足した・判定に使わない）: 本物どうしの期間の10年の窓／5年の窓"""
    out = {}
    i0 = R.ix[SV_REAL]
    idx = range(i0, len(ks) - 120 + 1)
    en = np.array([R.ann('NDX', i, 120) - R.ann('MKT', i, 120) for i in idx])
    es = np.array([R.ann('SV', i, 120) - R.ann('MKT', i, 120) for i in idx])
    out['本物どうしの期間（1998-06〜）の10年の窓'] = dict(窓=len(en), 市場との差の相関=round(float(np.corrcoef(en, es)[0, 1]), 3),
                                                両方負け=round(float(((en <= 0) & (es <= 0)).mean()), 3),
                                                両方勝ち=round(float(((en > 0) & (es > 0)).mean()), 3))
    for pn, p0 in PERIODS.items():
        i0 = R.ix[p0]
        idx = range(i0, len(ks) - 60 + 1)
        en = np.array([R.ann('NDX', i, 60) - R.ann('MKT', i, 60) for i in idx])
        es = np.array([R.ann('SV', i, 60) - R.ann('MKT', i, 60) for i in idx])
        o = dict(窓=len(en), 両方負け=round(float(((en <= 0) & (es <= 0)).mean()), 3))
        for k in MIXES:
            e = np.array([R.ann(k, i, 60) - R.ann('MKT', i, 60) for i in idx])
            o[k] = dict(市場に勝った割合=round(float((e > 0).mean()), 3), 最悪=pct(float(e.min())))
        out[f'5年の窓・{pn}'] = o
    return out


def peaks(r, R, ks, last):
    pk = json.load(open(os.path.join(BASE, 'out', 'industry_peak.json')))['山']
    rows = []
    for key, lab in (('最初の記録', '最初の記録の翌年から'), ('最後の記録', '最後の記録の翌年から（後知恵）')):
        for p in pk:
            y = p.get(key)
            if not y:
                continue
            s = (int(y) + 1) * 100 + 1
            if s not in R.ix or R.ix[s] + 120 > len(ks):
                continue
            i = R.ix[s]
            mk = R.ann('MKT', i, 120)
            row = dict(起点=lab, 業種=p['業種'], ja=p.get('ja'), 年=int(y), 始まり=s, テック=p['業種'] in TECH_IND,
                       業種そのものの次の10年=p.get('最初の記録から10年(%/年)') if key == '最初の記録' else p.get('最後の記録から10年(%/年)・後知恵'))
            for k in SERIES:
                row[k] = pct(R.ann(k, i, 120) - mk)
            rows.append(row)

    def summ(sel):
        if not sel:
            return None
        o = dict(山の数=len(sel), 始まりの年の数=len({x['始まり'] for x in sel}))
        for k in SERIES:
            v = [x[k] for x in sel]
            o[k] = dict(勝った山=f"{sum(1 for z in v if z > 0)}/{len(v)}", 中央=round(float(np.median(v)), 2), 平均=round(float(np.mean(v)), 2))
        return o
    out = {}
    for lab in ('最初の記録の翌年から', '最後の記録の翌年から（後知恵）'):
        sel = [x for x in rows if x['起点'] == lab]
        out[lab] = dict(全部=summ(sel), テックの山=summ([x for x in sel if x['テック']]), テック以外の山=summ([x for x in sel if not x['テック']]))
    return out, rows


def dca(R, ks):
    out = {}
    for pn, p0 in list(PERIODS.items())[:2]:
        i0 = R.ix[p0]
        n = 240
        idx = range(i0, len(ks) - n + 1)
        res = {k: ratio_stats([R.dca(k, i, n) / R.dca('MKT', i, n) for i in idx]) for k in SERIES}
        res['起点'] = f'{ks[i0]}〜{ks[idx[-1]]}'
        out[pn] = res
    return out


def vehicles(r, ks, net, chains_meta):
    out = dict(つなぎ目の点検=dict(NASDAQ100=chains_meta['ndx']['checks'], 小型バリュー=chains_meta['sv']['checks']),
               区間=dict(NASDAQ100=chains_meta['ndx']['segs'], 小型バリュー=chains_meta['sv']['segs']))
    for t, s in net.items():
        mm = sorted(s)
        if t == 'VBR':
            mm = [m for m in mm if m >= 200403]
        else:
            mm = [m for m in mm if m >= 199904]
        g, mk = geo(s, mm), geo(r['MKT'], mm)
        o = dict(期間=f'{mm[0]}〜{mm[-1]}', 年率_費用込み=pct(g), 市場の年率=pct(mk), 市場との差=pct(g - mk))
        if t == 'VBR':
            o['紙の上の SMALL HiBM との差'] = None
            try:
                import bestfund_data as D
                paper = D.french_pf('6_Portfolios_2x3', 'SMALL HiBM', 'Average Value Weighted Returns')
                pm = [m for m in mm if m in paper]
                o['紙の上の SMALL HiBM の年率（同じ期間）'] = pct(geo(paper, pm))
                o['紙の上の SMALL HiBM との差'] = pct(geo(s, pm) - geo(paper, pm))
            except Exception as e:  # 参考なので落とさない
                o['紙の上の SMALL HiBM との差'] = f'取れない: {e}'
        out[f'{t}（費用込み）'] = o
    return out


def forms_part():
    import best15_check as B
    import best15r_check as BR
    import unx_assets as U
    import upside_check as UC
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    B.century_extend(U)
    P = BR.POOL
    for f in FORMS.values():
        miss = [c for c in f if c not in P]
        if miss:
            raise SystemExit(f'物差しに無い本: {miss}')
    fast, cent = B.Fast(U, rows, chains, P), B.Cent(U, P)
    fbr = BR.FastBR(fast)
    st = BR.industry_state()
    vec, _ = BR.industry_vectors(U, rows)
    win = list(dict.fromkeys(st['top5'] + st['rec']))
    IND = np.array([[(st['mkt'].get(k, 0.0) if c == 'VOO' else vec.get(c, {}).get(k, 0.0)) for k in win] for c in P])
    adj = {nm: BR.adj_vector(vec, st, rt, P)[0] for nm, rt in BR.RATES.items()}
    a0 = adj['主（20年の値）']
    names = list(FORMS)
    W = np.array([[FORMS[n].get(c, 0) for c in P] for n in names], dtype=np.float64)
    Wn = W / W.sum(axis=1, keepdims=True)

    def ve(Wf, v):
        return {'主': lambda: fbr.eval(Wf, a0), '10年の値': lambda: fbr.eval(Wf, adj['10年の値']),
                '1位の業種を強く': lambda: fbr.eval(Wf, adj['1位の業種を強く（10年の値・Chips −4.0）']),
                '主の半分': lambda: fbr.eval(Wf, adj['主の半分']), '分散の上乗せなし': lambda: fbr.eval(Wf, a0, nobonus=True),
                '共分散をA2の窓から': lambda: fbr.eval(Wf, a0, cov2=True)}[v]()
    V = {v: ve(W, v) for v in BR.VARS}
    E, cs = V['主'], cent.eval(W)
    with contextlib.redirect_stdout(io.StringIO()):
        tab = U.measure(FORMS, rows, chains, mega=U.mega_map(rows, sorted({a for f in FORMS.values() for a in f} | {'VOO'})))
    piB = float(json.load(open(os.path.join(BASE, 'out', 'best15r_check.json')))['pi_forward']['B'])
    # ⑦b（事後）小型バリューの上乗せが消えていたら
    iv, ivoo = P.index('VBR'), P.index('VOO')
    gB0, gC0, gD0 = fbr.gB.copy(), fbr.gC.copy(), fbr.gD.copy()
    noprem = {}
    try:
        fbr.gB[iv] -= 0.5 * float(rows['VBR']['B_X'])
        noprem['S1 B の世界の小型バリューの上乗せを0'] = fbr.eval(W, a0)
        fbr.gC[iv], fbr.gD[iv] = fbr.gC[ivoo], fbr.gD[ivoo]
        noprem['S2 未来の3つの世界のどれも小型バリューに上乗せなし'] = fbr.eval(W, a0)
    finally:
        fbr.gB, fbr.gC, fbr.gD = gB0, gC0, gD0
    out = {}
    for j, nm in enumerate(names):
        f = FORMS[nm]
        o = tab[UC.W_CRASH][nm]
        cm = U.century_monthly(f)
        out[nm] = dict(
            形=f,
            元の物差し=dict(P15π=o['P15π'], 平均=o['π加重の平均の年率'], 五パーセント未満=o['P5π（5%未満）'], 最悪の世界=o['最悪の世界'],
                         最大下落=o['最大下落'], ぶれ=o['ぶれ'], 世界=o['世界ごとの年率'], 過去の転がる20年で15パーセント以上=o['過去の転がる20年で15%以上']),
            基礎率の物差し=dict(P15π=round(100 * float(E['P15'][j]), 2), 平均=round(100 * float(E['mean_pi'][j]), 2),
                            最悪の世界=round(100 * float(E['worst'][j]), 2), 五パーセント未満=round(100 * float(E['P5'][j]), 2),
                            最大下落=round(100 * float(E['mdd'][j]), 1), ぶれ=round(100 * float(E['vol'][j]), 1)),
            基礎率の感度ごとの今との差={v: dict(P15=round(100 * float(V[v]['P15'][j] - V[v]['P15'][0]), 2),
                                        平均=round(100 * float(V[v]['mean_pi'][j] - V[v]['mean_pi'][0]), 3),
                                        五パーセント未満=round(100 * float(V[v]['P5'][j] - V[v]['P5'][0]), 2)) for v in BR.VARS},
            百年=dict(三十年の中央=round(float(cs['c30med'][j]), 3), 三十年の最悪=round(float(cs['c30min'][j]), 3),
                    詳細=(None if cm is None else U.strip_century(cm))),
            勝ち業種の中身の比重={k: round(100 * float(Wn[j] @ IND[:, i]), 1) for i, k in enumerate(win)},
            二重に数えた分_B_rec=round(100 * piB * sum(w / sum(f.values()) * float(rows[c].get('B_rec') or 0.0) for c, w in f.items()), 3),
            事後_小型バリューの上乗せが消えていたら={k: dict(P15π=round(100 * float(e['P15'][j]), 2), 平均=round(100 * float(e['mean_pi'][j]), 2),
                                                五パーセント未満=round(100 * float(e['P5'][j]), 2),
                                                今との差=dict(P15=round(100 * float(e['P15'][j] - e['P15'][0]), 2),
                                                           平均=round(100 * float(e['mean_pi'][j] - e['mean_pi'][0]), 3),
                                                           五パーセント未満=round(100 * float(e['P5'][j] - e['P5'][0]), 2)))
                                       for k, e in noprem.items()},
            中身の集中=B.lookthrough(f))
    return out


def main():
    t0 = time.time()
    r, ks, meta, net = load()
    last = ks[-1]
    R = Roll(r, ks)
    res = dict(generated=time.strftime('%Y-%m-%d'), tool='night/ndx_sv_check.py', kind='参考（判定なし・配分は変えない・測り方は道具の頭に固定）',
               question='NASDAQ100 と米国の小型バリューは、市場の主役（業種）が入れ替わっても市場に勝ってきたか', 最後の月=last)
    res['①時代ごと'] = decades(r, ks, last)
    res['②転がる窓'] = rolling(R, ks, last)
    res['③補い合うか'] = complement(r, R, ks)
    res['④主役が入れ替わった後'], res['④山ごと'] = peaks(r, R, ks, last)
    res['⑤二十年の積立'] = dca(R, ks)
    res['⑥器の確かめ'] = vehicles(r, ks, net, meta)
    res['⑦今の物差しでの形の比べ'] = forms_part()
    res['事後（判定に使わない）'] = posthoc(R, ks)
    res['secs'] = round(time.time() - t0)
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    for row in res['①時代ごと']:
        print(row['時代'], '市場', row['市場の年率'], {k: row[k]['市場との差'] for k in SERIES}, row['NDX の出所'], row['SV の出所'])
    print('→', OUT, res['secs'], 's')


if __name__ == '__main__':
    main()
