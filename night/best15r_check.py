#!/usr/bin/env python3
"""night/best15r_check.py — 「業種は勝ち続けない」という歴史の基礎率を前提にして、15%を狙う形を探し直す（best15r・2026-11-01・参考・配分は変えない）

ユーザー「業種が勝ち続けることはないことを歴史で証明したのに半導体によせるの？そういったことを含めて提案できない？」
best15 / best15c の半導体40%は、5つの世界のうち A1（直近26年）・A2（直近15年）の実績（π の37%）と、条件⑦「過去の転がる20年で
15%以上」から来ていた＝今の勝ち業種がこの先も勝ち続けるという前提。この道具はその前提を外し、リポジトリの歴史検証の結果を主の前提にする。
門・採点・配分（portfolio.json）・注文書には触れない。
★候補・基礎率・条件・選び方はこの頭に書いたとおりで、結果を見る前にこのファイルをコミットする（`--selfcheck` は一致の確かめだけ）。

前提にする歴史の結果（どれもリポジトリで測って記録済み）:
  P1 業種の勝ち負けは続かない（out/tech_persist.json・事前登録 out/tech_persist_prereg.json・1936〜・French 49業種）:
     過去10年の年率の上位5業種の対市場の超過の中央 次の10年 −1.84%/年（勝率20%）・次の20年 −0.83%/年／下位5業種 +0.56・+0.30%/年
     （事後: 1位の業種は次の10年 −4.0%/年・勝率26%）
  P2 比重が過去最大の業種は負けやすい（out/industry_peak.json・事前登録 5693cf8・判定「支持」）: 次の10年 −1.51%/年（5/19）・20年 −1.0%/年
  P3 業種を当てない（out/future30.json）: 勝者を追う形は市場の0.78倍・業種を当てない形が30年の下位10%点で最良
  P4 100年の代用（best15c と同じ）
今の位置（この道具の中で French 49 から作り直し、tech_persist の「今の位置」と一致を確かめる）:
  直近10年＝2016-07〜2026-06 の年率の上位5＝Chips・Mach・Hardw・Cnstr・Autos／下位5＝同じ式で下から5／比重が過去最大＝out/industry_peak.json の
  「今_記録を付けている業種」（Softw・Chips）。合わせた『勝ち業種』＝上位5 ∪ 記録の業種
世界（目的と条件）: 未来の3つ B（100年の平均）・C（JPM 2026）・D（アナリスト）だけ（π を足して1に直す: B .31・C .1597・D .1597 → .4925・.2537・.2537）。
  A1・A2（直近26年・15年の実績）は目的に使わない。ぶれ σ・最大下落・分散の上乗せの共分散は従来どおり 2000-09〜2026-09 の値動き（下げの深さの物差し）
基礎率の補正（主＝積立20年に期間をそろえて20年の値）: 業種 i の超過 e_i＝上位5 −0.83%・記録の業種 −1.00%（両方なら小さいほう＝足さない）・
  下位5 +0.30%・その他0 → 市場の比重（French 49 の最新月の時価総額）で重み付けた平均を全業種から引く（市場そのものは補正0）→
  各本の補正＝中身の業種の比重×e_i（中身は R・X・unx と同じ保有と SIC→49業種。米国外の本と中身の無い本は0＝K4 と同じ）→ B・C・D の年率に足す
条件 T1r（今を同じ世界で測った値と比べ、どれも下回らない）:
  ⓪ P15π（未来の3つ・補正後）≥ 今 ① π加重の平均 ≥ 今 ② 最悪の世界 ≥ 今 ③ 5%未満 ≤ 今 ④ 最大下落（2000-09〜）≥ 今
  ⑧ 100年の代用 30年の中央 ≥ 今 ∧ 最悪 ≥ 今
  ⑨ 勝ち業種を市場より多く持たない: 勝ち業種のそれぞれで、中身まで見た比重 ≤ 市場の比重（P1〜P3 を形の縛りにしたもの）
  外したもの: ⑤ A2を外した P15π・⑥ 未来の世界だけの P15π（主がそれ）・⑦ 過去の転がる20年で15%以上（直近の勝ち業種の実績で決まる）
候補・形: best15c と同じ18本（100年の写しがある本）・ETF 側100%・5%刻み・7本まで・1本40%まで
選び方（best15c と同じ釣り合い）: s＝min( (P15π−今)/(P15π の最大−今), (C−今)/(C の最大−今) ) を最大に（C＝100年の30年の中央）。
  s を小数3桁に丸めて同じなら P15π → 平均 → 最大下落が浅い → 名前の順
探索: 第0段 核4本（QQQM・SMH・ITA・XLV）だけ／第1段 核4本＋候補1本（5%以上）／第2段 核4本＋第1段の s の上位5本
  （第1段の P15π の最良の本と C の最良の本が入っていなければ s の下位から入れ替える）の総当たり（7本まで）
最終の確かめ（第2段の s の上位30を順に・最初に通った形を答えにする）:
  F1 基礎率と物差しの感度5本（10年の値 −1.84/−1.51/+0.56・1位の業種を強く Chips −4.0〔10年の値に〕・主の半分・
     分散の上乗せなし・共分散を A2 の窓から）すべてで P15π ≥ 今 ∧ π加重の平均 ≥ 今（それぞれ同じ感度で測った今と比べる）
  F2 円で見た最大下落（2000-09〜）≥ 今
  F3 100年の代用を (a) 費用を引いた写し (b) FBT の写しを XLV と同じにした写し で、30年の中央と最悪が今以上（best15c と同じ）
  通る形が無ければ「今のまま」
併せて出す（判定に使わない）: 今・答え・best15c の答え・best15 の勧め②・S&P500 だけ を、この物差しと元の物差し（A1・A2 を含む
  unx_assets.measure）の両方で／勝ち業種の中身の比重と市場の比重／⑨を外した P15π の最大（縛りの代金）／
  厳しい形（どの業種も市場の比重＋15pt まで）の答え／中身の集中（lookthrough）
⚠ 限界: 基礎率は業種の中央値で、ばらつきは大きい（上位5業種が次の10年に勝った窓も20%ある）・SIC の分類は今日のプラットフォーム企業を割る・
  米国の業種の記録だけ・100年の写しは後から勝ちが分かった業種（医薬品・防衛）を含む・未来の世界も予想・分散の上乗せは仮定・
  ⑨は小さい業種（Hardw 1.7%・Cnstr 0.6% など）でも市場の比重を上限にする・税は入らない・縛り（40%・7本・5%）は私が決めた
使い方: python3 night/best15r_check.py --selfcheck   （一致の確かめだけ）
        python3 night/best15r_check.py               → out/best15r_check.json
"""
import contextlib, io, json, math, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'best15r_check.json')

import best15_check as B   # noqa: E402
import best15c_check as BCc  # noqa: E402

CORE = list(B.CORE)
CANDS = list(BCc.CANDS)
POOL = CORE + CANDS
NEXTRA, SDEC, NFIN, EPS = 5, 3, 30, 1e-12
WIN10 = (201607, 202606)                       # tech_persist の「今の位置」と同じ窓
RATES = {'主（20年の値）': dict(top=-0.0083, rec=-0.0100, bot=0.0030),
         '10年の値': dict(top=-0.0184, rec=-0.0151, bot=0.0056),
         '1位の業種を強く（10年の値・Chips −4.0）': dict(top=-0.0184, rec=-0.0151, bot=0.0056, first=-0.0400),
         '主の半分': dict(top=-0.00415, rec=-0.0050, bot=0.0015)}
VARS = ['主', '10年の値', '1位の業種を強く', '主の半分', '分散の上乗せなし', '共分散をA2の窓から']
FWD = ('B', 'C', 'D')
STRICT_PT = 0.15
REFS = {'best15c の答え SMH40/FBT35/ITA20/XLK5': {'SMH': 40, 'FBT': 35, 'ITA': 20, 'XLK': 5},
        'best15 の勧め② SMH40/FBT30/ITA15/NASDAQ100 15': {'SMH': 40, 'FBT': 30, 'ITA': 15, 'QQQM': 15},
        'S&P500 だけ': {'VOO': 100}}


def log(*a):
    print('[best15r]', *a, flush=True)


def cagr(x, a, b):
    """tech_persist.cagr と同じ式"""
    v = [x[m] for m in sorted(x) if a <= m <= b]
    n = (b // 100 - a // 100) * 12 + b % 100 - a % 100 + 1
    return math.prod(1 + q for q in v) ** (12 / len(v)) - 1 if len(v) >= n * .97 else None


def industry_state():
    """直近10年の上位5・下位5（French 49・時価加重）・最新月の市場の比重・比重が過去最大の業種"""
    import mw_common as M
    s = M.french_series('49_Industry_Portfolios', want='Average Value Weighted Returns')
    past = {k: cagr(x, *WIN10) for k, x in s.items()}
    ks = [k for k in past if past[k] is not None]
    order = sorted(ks, key=lambda k: -past[k])
    top5, bot5 = order[:5], order[-5:]
    tp = json.load(open(os.path.join(BASE, 'out', 'tech_persist.json')))['今の位置']
    want = [k for k, _ in tp['上位8業種']][:5]
    if top5 != want:
        raise SystemExit(f'上位5業種が tech_persist の今の位置と違う: {top5} 対 {want}')
    t = M.french_tables('49_Industry_Portfolios')
    nf = next(v for k, v in t.items() if k.startswith('Number of Firms') and v['freq'] == 'monthly')
    sz = next(v for k, v in t.items() if k.startswith('Average Firm Size') and v['freq'] == 'monthly')
    last = max(nf['data'])
    caps = {c: (n or 0) * (z or 0) for c, n, z in zip(nf['cols'], nf['data'][last], sz['data'][last])}
    tot = sum(caps.values())
    mkt = {c: v / tot for c, v in caps.items()}
    rec = [r['業種'] for r in json.load(open(os.path.join(BASE, 'out', 'industry_peak.json')))['今_記録を付けている業種']]
    return dict(top5=top5, bot5=bot5, rec=rec, past={k: past[k] for k in ks}, mkt=mkt, mkt_month=last)


def industry_vectors(U, rows):
    """各本の中身の業種の比重（全部）。R・X・unx と同じ保有と SIC→49業種（rows の top_industries と一致を確かめる）"""
    R, X = U.R, U.X
    prof_old = json.load(open(os.path.join(BASE, 'out', 'etf_profiles.json'))).get('etfs') or {}
    pn = os.path.join(BASE, 'out', 'etf_forward_profiles.json')
    prof_new = (json.load(open(pn)).get('etfs') or {}) if os.path.exists(pn) else {}
    prof_new = {**prof_new, **R.EXTRA_PROFILES}
    av = X.av_profiles()
    hold = {}
    for c in POOL:
        meta = R.C.get(c) or U.NEW.get(c) or X.NEW.get(c) or {}
        if c == 'VOO' or not meta.get('us'):
            continue
        if c == 'FBT':
            h = U.hold_t_new()[0]['FBT']
        elif c in X.SECTOR_NEW and c in av:
            h = [(x[0], x[1]) for x in X.holdings_for_R(c, av[c]) if x and x[0] and x[0] != 'n/a']
        else:
            h = R.holdings_of(c, prof_old, prof_new)
            if c == 'QQQM' and not h:
                h = R.holdings_of('QQQ', prof_old, prof_new)
        hold[c] = h
    tickers = {t.upper() for h in hold.values() for t, _ in h if not t.startswith('*')}
    with contextlib.redirect_stdout(io.StringIO()):
        ind_of, _ = U.mapper(tickers)
    vec, chk = {}, {}
    for c, h in hold.items():
        mapped = [(ind_of(t, c), w) for t, w in h]
        mw = sum(w for k, w in mapped if k)
        d = {}
        for k, w in mapped:
            if k:
                d[k] = d.get(k, 0) + w / mw
        vec[c] = d
        top6 = {k: round(v, 3) for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:6]}
        ref = rows[c].get('top_industries') or {}
        chk[c] = (top6 == ref)
    return vec, chk


def adj_vector(vec, st, rate, pool):
    """基礎率の補正（本ごと・年率）。市場の比重で重み付けた平均を0にそろえる"""
    e = {}
    for k in st['mkt']:
        v = 0.0
        if k in st['top5']:
            v = rate['top']
        if k in st['rec']:
            v = min(v, rate['rec']) if v else rate['rec']
        if k in st['bot5']:
            v = rate['bot']
        if 'first' in rate and k == st['top5'][0]:
            v = rate['first']
        e[k] = v
    ebar = sum(st['mkt'][k] * e[k] for k in st['mkt'])
    e = {k: v - ebar for k, v in e.items()}
    a = []
    for c in pool:
        if c == 'VOO':
            a.append(sum(st['mkt'][k] * e[k] for k in st['mkt']))
        elif c in vec:
            a.append(sum(w * e.get(k, -ebar) for k, w in vec[c].items()))
        else:
            a.append(0.0)
    return np.array(a), e


class FastBR:
    """best15_check.Fast の配列で、未来の3つの世界（補正つき）だけを測る"""

    def __init__(self, fast):
        f = self.f = fast
        p = f.pi
        tot = sum(p[k] for k in FWD)
        self.pi = {k: p[k] / tot for k in FWD}
        self.S2 = np.cov(np.log1p(f.G2), bias=True) * 12
        self.s2 = np.diag(self.S2).copy()
        self.gB, self.gC, self.gD = np.expm1(f.lB), np.expm1(f.lC), np.expm1(f.lD)

    def eval(self, W, a, nobonus=False, cov2=False):
        import etf_forward_combo as CB
        f, P = self.f, self.f.P
        W = np.asarray(W, dtype=np.float64)
        W = W / W.sum(axis=1, keepdims=True)
        _, vol, mdd = CB.path_stats(W @ f.G1, f.T1)
        S, s = (self.S2, self.s2) if cov2 else (f.S1, f.s1)
        q = np.einsum('ij,jk,ik->i', W, S, W)
        bonus = np.zeros(len(W)) if nobonus else 0.5 * (W @ s - q)
        sig = np.sqrt(q)
        wv = {'B': np.expm1(W @ np.log1p(self.gB + a) + bonus), 'C': np.expm1(W @ np.log1p(self.gC + a) + bonus),
              'D': np.expm1(W @ np.log1p(self.gD + a) + bonus)}
        ok = (sig >= P.S0) & (sig <= P.S1_)
        for k in FWD:
            m = np.log1p(wv[k])
            ok &= (m >= P.M0) & (m <= P.M1)

        def pr(tau):
            tot = np.zeros(len(W))
            for k in FWD:
                v = np.full(len(W), np.nan)
                if ok.any():
                    v[ok] = P.interp(f.tabs[tau], np.log1p(wv[k][ok]), sig[ok])
                tot += self.pi[k] * (v if tau >= 0.10 else 1 - v)
            return tot
        return dict(ok=ok, P15=np.where(ok, pr(0.15), np.nan), P5=np.where(ok, pr(0.05), np.nan),
                    mean_pi=sum(self.pi[k] * wv[k] for k in FWD), worst=np.minimum.reduce([wv[k] for k in FWD]),
                    vol=vol, mdd=mdd, sig=sig, B=wv['B'], C=wv['C'], D=wv['D'])


def run(fbr, cent, A, now, a, IND, cap, chunk=20000):
    keys = ('ok', 'P15', 'P5', 'mean_pi', 'worst', 'vol', 'mdd', 'sig')
    E = {k: np.empty(len(A), dtype=bool if k == 'ok' else np.float64) for k in keys}
    E['c30med'] = np.full(len(A), np.nan); E['c30min'] = np.full(len(A), np.nan); E['cok'] = np.zeros(len(A), bool)
    E['cap'] = np.zeros(len(A), bool); E['capx'] = np.zeros(len(A))
    for s in range(0, len(A), chunk):
        W = A[s:s + chunk].astype(np.float64)
        e = fbr.eval(W, a)
        for k in keys:
            E[k][s:s + chunk] = e[k]
        Wn = W / W.sum(axis=1, keepdims=True)
        ex = Wn @ IND - cap[None, :]
        E['cap'][s:s + chunk] = (ex <= 1e-9).all(axis=1)
        E['capx'][s:s + chunk] = ex.max(axis=1)
        with np.errstate(invalid='ignore'):
            pre = e['ok'] & (e['P15'] >= now['P15'] - EPS) & (e['mean_pi'] >= now['mean_pi'] - EPS) & (e['worst'] >= now['worst'] - EPS) \
                & (e['P5'] <= now['P5'] + EPS) & (e['mdd'] >= now['mdd'] - EPS)
        if pre.any():
            ce = cent.eval(W[pre])
            ii = np.arange(s, min(s + chunk, len(A)))[pre]
            E['c30med'][ii] = ce['c30med']; E['c30min'][ii] = ce['c30min']; E['cok'][ii] = ce['ok']
    return E


def feas(E, now, use_cap=True):
    with np.errstate(invalid='ignore'):
        g = {'⓪15%以上': E['P15'] >= now['P15'] - EPS, '①平均': E['mean_pi'] >= now['mean_pi'] - EPS,
             '②最悪の世界': E['worst'] >= now['worst'] - EPS, '③5%未満': E['P5'] <= now['P5'] + EPS,
             '④最大下落': E['mdd'] >= now['mdd'] - EPS,
             '⑧100年': E['cok'] & (E['c30med'] >= now['c30med'] - EPS) & (E['c30min'] >= now['c30min'] - EPS)}
        if use_cap:
            g['⑨勝ち業種を市場より多く持たない'] = E['cap']
        f = E['ok'].copy()
        for v in g.values():
            f &= v
    return f, g


def name_of(row):
    return B.name_of(row, POOL)


def form_of(row):
    return {POOL[j]: int(row[j]) * B.STEP for j in range(len(POOL)) if row[j] > 0}


def brief(E, i, s=None, a=None, b=None):
    d = dict(P15π=round(100 * E['P15'][i], 2), 平均=round(100 * E['mean_pi'][i], 2), 最悪の世界=round(100 * E['worst'][i], 2),
             五パーセント未満=round(100 * E['P5'][i], 2), 最大下落=round(100 * E['mdd'][i], 1), ぶれ=round(100 * E['vol'][i], 1),
             百年の中央=round(float(E['c30med'][i]), 3), 百年の最悪=round(float(E['c30min'][i]), 3),
             勝ち業種の超過の最大=round(100 * float(E['capx'][i]), 1))
    if s is not None:
        d.update(s=round(float(s[i]), 4), P15の取り分=round(float(a[i]), 3), 百年の取り分=round(float(b[i]), 3))
    return d


def main():
    t0 = time.time()
    B.check_now()
    import unx_assets as U
    import upside_check as UC
    import bestpf_check as BC
    import etf_forward_combo as CB
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    miss = [c for c in POOL if c not in rows]
    if miss:
        raise SystemExit(f'行が無い: {miss}')
    C = B.century_extend(U)
    fast, cent = B.Fast(U, rows, chains, POOL), B.Cent(U, POOL)
    fbr = FastBR(fast)
    st = industry_state()
    win_ind = list(dict.fromkeys(st['top5'] + st['rec']))
    vec, vchk = industry_vectors(U, rows)
    inds = sorted(st['mkt'])
    IND = np.array([[(st['mkt'].get(k, 0.0) if c == 'VOO' else vec.get(c, {}).get(k, 0.0)) for k in win_ind] for c in POOL])
    cap = np.array([st['mkt'][k] for k in win_ind])
    INDall = np.array([[(st['mkt'].get(k, 0.0) if c == 'VOO' else vec.get(c, {}).get(k, 0.0)) for k in inds] for c in POOL])
    capall = np.array([st['mkt'][k] + STRICT_PT for k in inds])
    adj, e_ind = {}, {}
    for nm, r in RATES.items():
        adj[nm], e_ind[nm] = adj_vector(vec, st, r, POOL)
    a0 = adj['主（20年の値）']

    # ── 自己検問 ──
    sc = {}
    sc['中身の業種が rows の top_industries と一致'] = {c: bool(v) for c, v in vchk.items()}
    sc['市場そのもの（VOO）の補正'] = {k: round(float(v[POOL.index('VOO')]), 12) for k, v in adj.items()}
    rng = np.random.default_rng(7)
    Wr = rng.integers(0, 9, size=(60, len(POOL))).astype(np.float64)
    Wr[Wr.sum(axis=1) == 0, 0] = 1
    e1 = fbr.eval(Wr, np.zeros(len(POOL)))
    e2 = fast.eval(Wr)
    d15 = float(np.nanmax(np.abs(e1['P15'] - e2['P15_fwd'])))
    sc['補正0で best15_check.Fast の未来の世界だけの P15π と一致（最大の差）'] = d15
    forms = {f'r{i}': {POOL[j]: int(Wr[i][j]) for j in range(len(POOL)) if Wr[i][j] > 0} for i in range(12)}
    with contextlib.redirect_stdout(io.StringIO()):
        tab = U.measure(forms, rows, chains, windows={UC.W_CRASH: BC.WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
    dw = 0.0
    for i, nm in enumerate(forms):
        for k in FWD:
            dw = max(dw, abs(float(e1[k][i]) - tab[nm]['_raw']['worlds'][k]))
    sc['補正0で unx_assets.measure の B・C・D と一致（最大の差）'] = dw
    sc['一致'] = bool(d15 < 1e-12 and dw < 1e-12 and all(vchk.values())
                    and all(abs(v) < 1e-12 for v in sc['市場そのもの（VOO）の補正'].values()))
    log('自己検問', json.dumps(sc, ensure_ascii=False))
    log('上位5', st['top5'], '下位5', st['bot5'], '記録', st['rec'], '市場の比重', {k: round(st['mkt'][k], 4) for k in win_ind})
    log('補正（主・本ごと %/年）', {c: round(100 * float(a0[i]), 2) for i, c in enumerate(POOL)})
    if not sc['一致']:
        raise SystemExit('自己検問が通らない')
    if '--selfcheck' in sys.argv:
        return

    n = len(POOL)
    W0 = np.array([[B.NOW.get(c, 0) for c in POOL]], dtype=np.float64)
    e0, c0 = fbr.eval(W0, a0), cent.eval(W0)
    now = {k: float(np.asarray(v)[0]) for k, v in e0.items() if k != 'ok'}
    now.update(c30med=float(c0['c30med'][0]), c30min=float(c0['c30min'][0]))
    now_capx = float(((W0 / W0.sum()) @ IND - cap).max())
    log('今（この物差し）', {k: round(v, 4) for k, v in now.items()}, '勝ち業種の超過の最大', round(now_capx, 4))

    # ── 第0段・第1段 ──
    idx_core = [POOL.index(c) for c in CORE]
    A4 = B.all_forms(4, 4, B.CAP)
    A0 = np.zeros((len(A4), n), dtype=np.int8)
    A0[:, idx_core] = A4
    blocks = [('核4本だけ', A0)]
    A5 = B.all_forms(5, 5, B.CAP, must=4)
    for x in CANDS:
        A = np.zeros((len(A5), n), dtype=np.int8)
        A[:, idx_core + [POOL.index(x)]] = A5
        blocks.append((x, A))
    A01 = np.vstack([b for _, b in blocks])
    lab = np.concatenate([np.full(len(b), nm, dtype=object) for nm, b in blocks])
    E01 = run(fbr, cent, A01, now, a0, IND, cap)
    f01, _ = feas(E01, now)
    if not f01.any():
        raise SystemExit('第0・1段で条件を通った形が無い')
    mx1 = BCc.maxima(E01, f01, E01['c30med'])
    s01, sa01, sb01 = BCc.score(E01, now, mx1, E01['c30med'], now['c30med'])
    st1 = {}
    for nm, _ in blocks:
        ii = np.where(f01 & (lab == nm))[0]
        if not len(ii):
            st1[nm] = None
            continue
        b = BCc.order_s(ii, E01, s01, A01)[0]
        st1[nm] = dict(最良の形=name_of(A01[b]), **brief(E01, b, s01, sa01, sb01), 通った形=int(len(ii)),
                       _s=float(s01[b]), _p=float(E01['P15'][ii].max()), _c=float(E01['c30med'][ii].max()))
        log('第1段', nm, json.dumps({k: v for k, v in st1[nm].items() if not k.startswith('_')}, ensure_ascii=False))
    elig = [x for x in CANDS if st1[x] and st1[x]['_s'] > 0]
    extras = sorted(elig, key=lambda x: (-st1[x]['_s'], x))[:NEXTRA]
    have = [x for x in CANDS if st1[x]]
    bestP = max(have, key=lambda x: (st1[x]['_p'], x)) if have else None
    bestC = max(have, key=lambda x: (st1[x]['_c'], x)) if have else None
    forced = []
    for need in (bestP, bestC):
        if need is None or need in extras:
            continue
        if len(extras) < NEXTRA:
            extras.append(need)
        else:
            j = max(k for k, x in enumerate(extras) if x not in forced)
            extras[j] = need
        forced.append(need)
    assets2 = CORE + extras
    log('第1段の最大', mx1, '第2段の本', assets2, '（P15π の最良', bestP, '・C の最良', bestC, '）')

    # ── 第2段 ──
    A2s = B.all_forms(len(assets2), B.KMAX, B.CAP)
    A2 = np.zeros((len(A2s), n), dtype=np.int8)
    A2[:, [POOL.index(c) for c in assets2]] = A2s
    log('第2段の形', len(A2))
    E2 = run(fbr, cent, A2, now, a0, IND, cap)
    f2, g2 = feas(E2, now)
    cnt = {k: int(np.nansum(v & E2['ok'])) for k, v in g2.items()}
    log('第2段で条件を通った形', int(f2.sum()), '条件ごと', cnt)
    if not f2.any():
        raise SystemExit('第2段で条件を通った形が無い')
    mx2 = BCc.maxima(E2, f2, E2['c30med'])
    s2, sa2, sb2 = BCc.score(E2, now, mx2, E2['c30med'], now['c30med'])
    ii = np.where(f2)[0]
    top = BCc.order_s(ii, E2, s2, A2)[:NFIN]
    forms = {name_of(A2[i]): form_of(A2[i]) for i in top}

    # ── 最終の確かめ ──
    def variant_eval(Wf, var):
        if var == '主':
            return fbr.eval(Wf, a0)
        if var == '10年の値':
            return fbr.eval(Wf, adj['10年の値'])
        if var == '1位の業種を強く':
            return fbr.eval(Wf, adj['1位の業種を強く（10年の値・Chips −4.0）'])
        if var == '主の半分':
            return fbr.eval(Wf, adj['主の半分'])
        if var == '分散の上乗せなし':
            return fbr.eval(Wf, a0, nobonus=True)
        if var == '共分散をA2の窓から':
            return fbr.eval(Wf, a0, cov2=True)
        raise KeyError(var)
    Wt = np.array([[f.get(c, 0) for c in POOL] for f in forms.values()], dtype=np.float64)
    vres = {v: (variant_eval(Wt, v), variant_eval(W0, v)) for v in VARS}
    ch_jpy, _ = U.jpy_chains(chains)
    Gj = np.array([[ch_jpy[c][m] for m in U.R.months(*BC.WINDOWS[UC.W_CRASH])] for c in POOL])
    _, _, mdd_j = CB.path_stats((Wt / Wt.sum(axis=1, keepdims=True)) @ Gj, Gj.shape[1])
    _, _, mdd_j0 = CB.path_stats((W0 / W0.sum()) @ Gj, Gj.shape[1])
    parts = C['parts']
    fee = {c: rows[c]['er_vehicle'] + rows[c]['tax_drag'] for c in POOL}
    parts_c1 = dict(parts)
    parts_c1['FBT'] = parts['XLV']
    parts_c2 = {c: {m: r - fee[c] / 12 for m, r in parts[c].items()} for c in POOL}
    mkt_c2 = {m: r - fee['VOO'] / 12 for m, r in C['mkt'].items()}
    cent1, cent2 = BCc.CentP(U, POOL, parts_c1), BCc.CentP(U, POOL, parts_c2, mkt_c2)
    k1, k2 = cent1.eval(Wt), cent2.eval(Wt)
    n1, n2 = cent1.eval(W0), cent2.eval(W0)
    finals, answer = [], None
    for j, (nm, i) in enumerate(zip(forms, top)):
        f1 = {v: dict(P15=bool(vres[v][0]['P15'][j] >= vres[v][1]['P15'][0] - EPS), 平均=bool(vres[v][0]['mean_pi'][j] >= vres[v][1]['mean_pi'][0] - EPS))
              for v in VARS}
        ok1 = all(x['P15'] and x['平均'] for x in f1.values())
        ok2 = bool(mdd_j[j] >= mdd_j0[0] - EPS)
        f3a = bool(k2['c30med'][j] >= n2['c30med'][0] - EPS and k2['c30min'][j] >= n2['c30min'][0] - EPS)
        f3b = bool(k1['c30med'][j] >= n1['c30med'][0] - EPS and k1['c30min'][j] >= n1['c30min'][0] - EPS)
        ok = ok1 and ok2 and f3a and f3b
        finals.append(dict(名前=nm, **brief(E2, i, s2, sa2, sb2), F1=ok1, F2円の最大下落=ok2, F3a費用=f3a, F3bFBTの写し=f3b,
                           感度ごとの差={v: dict(P15=round(100 * float(vres[v][0]['P15'][j] - vres[v][1]['P15'][0]), 2),
                                            平均=round(100 * float(vres[v][0]['mean_pi'][j] - vres[v][1]['mean_pi'][0]), 3)) for v in VARS},
                           円の最大下落=round(100 * float(mdd_j[j]), 1)))
        if ok and answer is None:
            answer = nm
    log('答え', answer)

    # ── 両端・縛りの代金・厳しい形 ──
    iP = BCc.order_s(ii, E2, E2['P15'], A2)[0]
    iC = BCc.order_s(ii, E2, E2['c30med'], A2)[0]
    ends = {'15%以上の確率の最大': dict(名前=name_of(A2[iP]), **brief(E2, iP, s2, sa2, sb2)),
            '100年の中央の最大': dict(名前=name_of(A2[iC]), **brief(E2, iC, s2, sa2, sb2))}
    fnc, _ = feas(E2, now, use_cap=False)
    jnc = np.where(fnc)[0]
    nocap = None
    if len(jnc):
        mxn = BCc.maxima(E2, fnc, E2['c30med'])
        sn, san, sbn = BCc.score(E2, now, mxn, E2['c30med'], now['c30med'])
        bn = BCc.order_s(jnc, E2, sn, A2)[0]
        bp = BCc.order_s(jnc, E2, E2['P15'], A2)[0]
        nocap = dict(説明='⑨（勝ち業種を市場より多く持たない）を外した場合（同じ第2段の形の中で）',
                     釣り合いの答え=dict(名前=name_of(A2[bn]), **brief(E2, bn, sn, san, sbn)),
                     P15πの最大=dict(名前=name_of(A2[bp]), **brief(E2, bp)), 条件を通った形=int(fnc.sum()))
    strict = None
    Wn2 = A2.astype(np.float64)
    okst = np.zeros(len(A2), bool)
    for s0 in range(0, len(A2), 50000):
        Wc = Wn2[s0:s0 + 50000]
        Wc = Wc / Wc.sum(axis=1, keepdims=True)
        okst[s0:s0 + 50000] = ((Wc @ INDall - capall[None, :]) <= 1e-9).all(axis=1)
    fst = f2 & okst
    if fst.any():
        jst = np.where(fst)[0]
        mxs = BCc.maxima(E2, fst, E2['c30med'])
        ss, sas, sbs = BCc.score(E2, now, mxs, E2['c30med'], now['c30med'])
        bs = BCc.order_s(jst, E2, ss, A2)[0]
        strict = dict(説明=f'どの業種も中身の比重を市場の比重＋{int(100 * STRICT_PT)}pt までにした場合（条件 T1r と⑨も）',
                      答え=dict(名前=name_of(A2[bs]), **brief(E2, bs, ss, sas, sbs)), 条件を通った形=int(fst.sum()))
    else:
        strict = dict(説明=f'どの業種も市場の比重＋{int(100 * STRICT_PT)}pt まで', 答え=None)

    # ── 詳しい物差し（この物差し・元の物差し）──
    show_forms = {'今': dict(B.NOW)}
    if answer:
        show_forms['答え'] = forms[answer]
    show_forms['15%以上の確率の最大'] = form_of(A2[iP])
    show_forms['100年の中央の最大'] = form_of(A2[iC])
    if nocap:
        show_forms['⑨を外した釣り合いの答え'] = form_of(A2[bn])
        show_forms['⑨を外した P15π の最大'] = form_of(A2[bp])
    if strict and strict.get('答え'):
        show_forms['厳しい形の答え'] = form_of(A2[bs])
    show_forms.update(REFS)
    Ws = np.array([[f.get(c, 0) for c in POOL] for f in show_forms.values()], dtype=np.float64)
    es, cs = fbr.eval(Ws, a0), cent.eval(Ws)
    Wsn = Ws / Ws.sum(axis=1, keepdims=True)
    assets = sorted({a for f in show_forms.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, assets)
    with contextlib.redirect_stdout(io.StringIO()):
        tab0 = U.measure(show_forms, rows, chains, mega=mega)
    detail = {}
    for j, (nm, f) in enumerate(show_forms.items()):
        cm = U.century_monthly(f)
        o = tab0[UC.W_CRASH][nm]
        detail[nm] = dict(形=f,
                          この物差し=dict(P15π=round(100 * float(es['P15'][j]), 2), 五パーセント未満=round(100 * float(es['P5'][j]), 2),
                                       平均=round(100 * float(es['mean_pi'][j]), 2), 最悪の世界=round(100 * float(es['worst'][j]), 2),
                                       世界=dict(B=round(100 * float(es['B'][j]), 2), C=round(100 * float(es['C'][j]), 2), D=round(100 * float(es['D'][j]), 2)),
                                       ぶれ=round(100 * float(es['vol'][j]), 1), 最大下落=round(100 * float(es['mdd'][j]), 1),
                                       百年の中央=round(float(cs['c30med'][j]), 3), 百年の最悪=round(float(cs['c30min'][j]), 3)),
                          元の物差し_A1A2を含む=dict(P15π=o['P15π'], 平均=o['π加重の平均の年率'], 五パーセント未満=o['P5π（5%未満）'],
                                              世界=o['世界ごとの年率'], 過去の転がる20年で15パーセント以上=o['過去の転がる20年で15%以上'],
                                              積立20年の内部収益率=o['積立20年の内部収益率']),
                          百年=(None if cm is None else U.strip_century(cm)),
                          勝ち業種の中身の比重={k: round(100 * float(Wsn[j] @ IND[:, i]), 1) for i, k in enumerate(win_ind)},
                          最大の業種=max(((k, round(100 * float(Wsn[j] @ INDall[:, i]), 1)) for i, k in enumerate(inds)), key=lambda t: t[1]),
                          中身の集中=B.lookthrough(f))

    doc = dict(generated=time.strftime('%Y-%m-%d'), tool='night/best15r_check.py', kind='参考（配分は変えない・選び方は道具の頭に固定）',
               question='業種は勝ち続けないという歴史の基礎率を前提にして、15%を狙う形を探し直す（best15c の続き）',
               pi_forward=fbr.pi, pool=POOL, now=B.NOW, now_raw=now, now_capx=now_capx, selfcheck=sc,
               industries=dict(上位5=st['top5'], 下位5=st['bot5'], 記録=st['rec'], 勝ち業種=win_ind, 市場の比重の月=st['mkt_month'],
                               市場の比重={k: round(st['mkt'][k], 4) for k in win_ind},
                               直近10年の年率={k: round(100 * st['past'][k], 1) for k in st['top5'] + st['bot5']}),
               base_rate={nm: dict(業種の超過={k: round(100 * v, 3) for k, v in e_ind[nm].items() if abs(v) > 1e-12},
                                   本ごとの補正={c: round(100 * float(adj[nm][i]), 3) for i, c in enumerate(POOL)}) for nm in RATES},
               industry_vectors={c: {k: round(v, 4) for k, v in sorted(d.items(), key=lambda kv: -kv[1])} for c, d in vec.items()},
               stage1={k: ({kk: vv for kk, vv in v.items() if not kk.startswith('_')} if v else None) for k, v in st1.items()},
               stage1_max=dict(P15π=round(100 * mx1['P15'], 2), 百年の中央=round(mx1['C'], 3)),
               stage2=dict(本=assets2, 形の数=int(len(A2)), 条件を通った形=int(f2.sum()), 条件ごと=cnt,
                           最大=dict(P15π=round(100 * mx2['P15'], 2), 百年の中央=round(mx2['C'], 3))),
               answer=answer or '今のまま', finals=finals, ends=ends, nocap=nocap, strict=strict, detail=detail,
               secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    log('完了', doc['secs'], '秒', answer)


if __name__ == '__main__':
    main()
