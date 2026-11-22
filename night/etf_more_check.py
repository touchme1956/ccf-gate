#!/usr/bin/env python3
"""night/etf_more_check.py — 他に検討すべき ETF があるか（2026-11-22・ユーザー「他に検討すべきETFがないか調べて」・参考・配分は変えない）

読むだけ。門・採点・配分（portfolio.json）・注文書には触れない。結果がどう出ても配分は変えない（入れるかはユーザーの明示指示のときだけ）。
★母集団・物差し・決まりはこの頭に書いたとおりで、結果を見る前にこのファイルをコミットしてから回す。

今の形（portfolio.json と照合・違えば止まる）: ETF 側 NASDAQ100（iFreeNEXT）40.5 / SMH 18 / ITA 9 / FBT 13.5 / VBR 9（＝全体の90%）・個別株10%。
  物差しは ETF 側だけを100%にそろえて測る＝ NASDAQ100 45 / SMH 20 / ITA 10 / FBT 15 / VBR 10（個別株は物差しの外＝etf30 などと同じ）
案: 候補 X を ETF 側の5（全体の4.5%）だけ NASDAQ100 から回す（NASDAQ100 45→40・X 5＝etf_add・etf30 と同じ置き方）。
  参考（判定に使わない）: X 5 を ETF 側の5本から按分で取る形

母集団: 楽天証券の ETF 一覧 ETFD.csv（2026-11-22 に取得・sha256 をこの道具に固定）の米国上場（NYSE ARCA・ナスダック・Cboe）と東証・名証。
  外すもの:
  X1 レバレッジ・インバース（etfcand の語のまま） X2 通貨・ボラティリティ（etfcand のまま）
  X4 今の本と同じ指数（QQQ・QQQM・QNDX・SMH・ITA・FBT・VBR）
  X5 方針で外す（2026-11-04 ユーザー明示指示「金国債はいりない」）: 金（現物・先物・金鉱株・金を組み込んだ本）と国債
     （米国債・物価連動国債・短期国債・各国の国債・世界国債 WGBI・新興国国債 GBI-EM／EMBI）。銀・プラチナ・社債・総合債券は残す
  （金は英語名・日本語名・指数名の語で。国債は英語名・日本語名の語と、債券の本だけ指数名の国債の指数〔WGBI・GBI-EM・EMBI ほか〕で
   ＝株の本の指数名に短期国債の比べ相手が書いてある本〔JEPI など〕は外さない・政府系機関の MBS は残す。外した本は名前つきで出す）
値段: Yahoo の配当込み月次（mw_common.yahoo）。円で測る: 米国上場は FRED DEXJPUS の月末の比を掛け、NISA で戻らない外国の源泉税
  （米国の本は配当利回り×10%・それ以外の地域の本は×20%＝etfcand と同じ）を月割りで引く。東証・名証の本は円のまま。
  壊れた値: 月次で −60% 以下か +100% 以上の月がある窓は使わない（etfcand の X3b）。東証・名証の本で実績が通ったものは日次も見て、
  1日に −30% 以下か +40% 以上の動きの塊が10営業日後も水準をずらしたままなら、その月を含む窓は使わない（etfcand_short の追記2）
窓（円・月次・2026-10 まで）: W20＝2006-11〜2026-10・W10＝2016-11〜2026-10・W5＝2021-11〜2026-10・W3＝2023-11〜2026-10
  組: L＝W10 がそろう（W20 もそろえば W20 も見る）／S5＝W5 まで／S3＝W3 まで／N＝3年に満たない（判定しない・印だけ）
同じ賭け: 判定の窓（L は W10・S5 は W5・S3 は W3）で、今の5本（QQQ・SMH・ITA・FBT・VBR）のどれかとの相関が 0.95 以上なら『今の本と同じ賭け』
  （東証・名証と米国上場の組は重ならない四半期・同じ市場どうしは月次＝etfcand_short の追記）。判定はしない（数だけ出す）
家族: 残りを同じ窓の相関 0.95 以上でまとめる（記録が長い順→米国上場→経費率の安い順→名前の順に並べ、最初の本を代表に）。
  S5・S3 の本が L の家族の代表と 0.95 以上なら『L の家族の新しい器』と書く

物差し①実績（全部の組）: 今の形と案を毎月組み直した円の月次の道で、年率・最大下落・ぶれの差（案 − 今）。
  実績が通る＝ L は W10 で 年率の差 > 0 かつ 最大下落の差 ≥ −1.0pt（W20 がそろう本は W20 でも同じ）。
  S5 は W5 と W3 の両方・S3 は W3 で同じ（記録が短い組は参考の印だけ）
物差し②未来（L だけ・etf30 と同じ道具）: best15 の Fast（unx_assets.measure の式・5つの世界）と best15r の FastBR
  （業種の基礎率・感度6本）と Cent（100年の代用）。物差しの本は best15 の33本から方針の本（GDX・GLDM・EDV・TLT・TIP・UST_HEDGED_2621）を
  外したもの。X が物差しの本ならその本（EPI→EPI_LONG・1306.T→TOPIX）、無ければ W10 の相関（上と同じ測り方）が 0.95 以上の物差しの本で代える
  （同じ賭け・名指し）。どちらも無ければ『未来は測れない』。業種の基礎率は物差しの33本の中身で作る（米国外の本と中身の無い本は0＝K4 と同じ）
  未来が通る＝ 元の物差しの π加重の平均の差 ≥ 0 かつ 業種の基礎率の平均の差が感度6本すべてで ≥ 0（etf30 と同じ）
判定（L）: 候補に残る（両方が通る）／未来の物差しだけ通る／過去だけ通る／通らない／未来は測れない（実績は通る・通らない）
答えの決まり（結果を見る前に固定）:
  A1 『候補に残る』があれば、その家族を『検討すべき』として、基礎率の平均の差の感度6本の最小が大きい順に挙げる
  A2 無ければ『候補に残る ETF は無い』とし、『未来の物差しだけ通る』を守りの候補として基礎率の最小の大きい順に上位10、
     『過去だけ通る』（と『過去は通る〔未来は測れない〕』）を攻めの候補（未来の物差しは支持しない）として W10 の年率の差の大きい順に上位10を挙げる
  A3 記録が短い組（S5・S3）で実績が通った本は、W3 の年率の差の大きい順に上位10を『記録が短い（判定しない）』として挙げる
  A1〜A3 の並びは家族ごとに1本（その家族の中で並びの値が最も良い本・家族の本の数を添える）
  A4 2026-10-14 の写し（out/_nx_cache/unx/ab/dl/ETFD_20261014.csv）からの新しい本・消えた本を名前つきで出す
  A5 どの結果でも配分は変えない
回帰の検査: best15_check.selfcheck（速い評価が unx_assets.measure・century_monthly と一致）が通らなければ止まる
⚠ 限界: 実績の窓は2006年以降・2016年以降の一つの時代（テックが勝った時代）＝ NASDAQ100 から回すと多くの本は実績で負ける／
  未来の物差しは予想と仮定（分散の上乗せ・業種の基礎率）／同じ賭けの代用は近似／5%の差は雑音に近い／税は外国の源泉税だけ／
  東証と米国上場の時差／Yahoo の値の誤り／楽天で買える＝ NISA 成長投資枠の対象とは限らない
使い方: python3 night/etf_more_check.py → out/etf_more_check.json
"""
import contextlib, csv, datetime, hashlib, html, io, json, math, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etfcand as E            # noqa: E402
import etfcand_short as ES     # noqa: E402
import mw_common as M          # noqa: E402

OUT = os.path.join(BASE, 'out', 'etf_more_check.json')
CDIR = os.path.join(BASE, 'out', '_nx_cache', 'etfmore')
ETFD = os.path.join(CDIR, 'ETFD_20261122.csv')
ETFD_SHA = 'ecab8c09b4a164cf83fde294187738f58f17db3e2cb1f35ec73b8d2944ca6a57'
OLD_ETFD = os.path.join(BASE, 'out', '_nx_cache', 'unx', 'ab', 'dl', 'ETFD_20261014.csv')
NOW = {'QQQM': 45, 'SMH': 20, 'ITA': 10, 'FBT': 15, 'VBR': 10}
NOW_TOTAL = {'IFREE-NDX': 40.5, 'SMH': 18, 'ITA': 9, 'FBT': 13.5, 'VBR': 9}
CASTLE = 10
REAL = {'QQQM': 'QQQ', 'SMH': 'SMH', 'ITA': 'ITA', 'FBT': 'FBT', 'VBR': 'VBR'}
HELD = {'QQQ', 'QQQM', 'QNDX', 'SMH', 'ITA', 'FBT', 'VBR'}
SLOT = 5
W20, W10, W5, W3 = (200611, 202610), (201611, 202610), (202111, 202610), (202311, 202610)
END = 202610
SAME_BET = FAMILY = STAND = 0.95
BROKEN_LO, BROKEN_HI = -0.60, 1.00
DAY_LO, DAY_HI = -0.30, 0.40
EPS = 1e-12
GOLD = re.compile(r'(?i)\bgold\b|ゴールド(?!マン)|金鉱|純金|金価格|(?<!白)金上場|金地金|金先物')
GOV = re.compile(r'(?i)treasur|\btreas\b|\bgovt\b|government|sovereign|t-bill|\btips\b|inflation[- ](protected|linked)'
                 r'|\bwgbi\b|国債|政府(?!系)|物価連動')                       # 英語名・日本語名に当てる
GOV_IDX = re.compile(r'(?i)\bwgbi\b|gbi-em|\bembi\b|govt bond|government bond|国債')   # 債券の本だけ・指数名に当てる
POLICY_POOL = {'GDX', 'GLDM', 'EDV', 'TLT', 'TIP', 'UST_HEDGED_2621'}
POOL_REAL = {'QQQM': 'QQQ', 'EPI_LONG': 'EPI', 'TOPIX': '1306.T'}
REAL_POOL = {'EPI': 'EPI_LONG', '1306.T': 'TOPIX'}
VARS = None   # best15r.VARS（読み込んでから）


def log(*a):
    print('[etf_more]', *a, file=sys.stderr, flush=True)


def months(a, b):
    return E.months(a, b)


# ───────────────────────── 母集団 ─────────────────────────
def load(path, check_sha=None):
    b = open(path, 'rb').read()
    sha = hashlib.sha256(b).hexdigest()
    if check_sha and sha != check_sha:
        raise SystemExit(f'ETFD.csv の sha256 が違う: {sha}')
    rows = list(csv.reader(io.StringIO(b.decode('utf-8-sig'))))
    out = []
    for r in rows:
        if len(r) < 33 or r[3] not in E.MKT_US | E.MKT_JP:
            continue
        us = r[3] in E.MKT_US
        out.append(dict(t=r[1] if us else r[0], y=r[1] if us else r[0].replace('.NG', '.N'), nm=html.unescape(r[2]),
                        ja=html.unescape(r[22]), idx=html.unescape(r[4]), mkt=r[3], us=us, er=E.num(r[5]), cls=r[6], region=r[7],
                        dy=E.num(r[19]), aum=E.num(r[24]), aum_unit=r[25], inception=r[32].replace('/', '-') if r[32] else None))
    return out, len(rows), sha


def why_out(d):
    nm, ja, idx = d['nm'], d['ja'], d['idx']
    if E.LEV.search(nm) or (not d['us'] and E.LEV_JP.search(ja)):
        return 'X1 レバレッジ・インバース'
    if d['cls'] == '通貨' or E.VOLX.search(nm) or 'ボラティリティ' in ja:
        return 'X2 通貨・ボラティリティ'
    if d['t'] in HELD:
        return 'X4 今の本と同じ指数'
    if GOLD.search(f'{nm} {ja} {idx}'):
        return 'X5 方針で外す（金）'
    if GOV.search(f'{nm} {ja}') or (d['cls'] == '債券' and GOV_IDX.search(idx)):
        return 'X5 方針で外す（国債）'
    return None


# ───────────────────────── 値段 ─────────────────────────
def fetch(ys, workers=4):
    out, err = {}, {}

    def one(y):
        try:
            return y, M.yahoo(y), None
        except Exception as e:  # noqa
            return y, None, str(e)[:160]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (y, r, e) in enumerate(ex.map(one, ys)):
            if r:
                out[y] = r
            else:
                err[y] = e or '空'
            if (i + 1) % 100 == 0:
                log(f'値段 {i + 1}/{len(ys)}')
    return out, err


def to_yen(d, r, fxr):
    if d['us']:
        k = 0.10 if d['region'] == 'アメリカ' else 0.20
        drag = k * (d['dy'] or 0.0) / 100 / 12
        return {m: (1 + v) * (1 + fxr[m]) - 1 - drag for m, v in r.items() if m in fxr and m <= END}
    return {m: v for m, v in r.items() if m <= END}


def usable(raw, ks):
    """窓の月がそろい、壊れた月（−60% 以下・+100% 以上）が無い"""
    return all(m in raw for m in ks) and not any(raw[m] <= BROKEN_LO or raw[m] >= BROKEN_HI for m in ks)


def daily_shift(y, a, b):
    """日次で水準がずれたままの塊の月（etfcand_short.daily_bad と同じ規則・窓 a〜b）"""
    r = M.yahoo(y, interval='1d')
    ds = sorted(r)
    lv, v = [], 1.0
    for dd in ds:
        v *= 1 + r[dd]
        lv.append(v)
    lo, hi = a * 100 + 1, b * 100 + 31
    flags = [i for i, dd in enumerate(ds) if lo <= dd <= hi and (r[dd] <= DAY_LO or r[dd] >= DAY_HI)]
    cl = []
    for i in flags:
        if cl and i - cl[-1][-1] <= 10:
            cl[-1].append(i)
        else:
            cl.append([i])
    bad = {}
    for c in cl:
        p0 = lv[c[0] - 1] if c[0] > 0 else 1.0
        p1 = lv[min(c[-1] + 10, len(lv) - 1)]
        x = p1 / p0 - 1
        if x <= DAY_LO or x >= DAY_HI:
            bad[ds[c[0]] // 100] = round(100 * x, 1)
    return bad


# ───────────────────────── 実績の物差し ─────────────────────────
def path(f, ret, ks):
    tot = sum(f.values())
    return {m: sum(w / tot * ret[t][m] for t, w in f.items()) for m in ks}


def st(r, ks):
    s = E.stats(r, ks)
    return dict(年率=round(100 * s['cagr'], 2), 最大下落=round(100 * s['mdd'], 1), ぶれ=round(100 * s['vol'], 1))


def xcorr(da, ra, db, rb, ks):
    if da['us'] != db['us']:
        return M.corr(ES.qret(ra, ks), ES.qret(rb, ks))
    return E.corr(ra, rb, ks)


# ───────────────────────── 本体 ─────────────────────────
def main():
    global VARS
    t0 = time.time()
    tg = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    w = {k: v for k, v in tg['ami_weights'].items() if v}
    if w != NOW_TOTAL or float(tg.get('shiro_castle_pct') or 0) != CASTLE:
        raise SystemExit(f'今の形が正本と違う: {w}・個別株 {tg.get("shiro_castle_pct")}（この道具の NOW を直してから回す）')
    uni, nrows, sha = load(ETFD, ETFD_SHA)
    meta = {d['t']: d for d in uni}
    out_list, cands = {}, []
    for d in uni:
        why = why_out(d)
        if why:
            out_list.setdefault(why, []).append(f"{d['t']} {d['ja'] or d['nm']}")
        else:
            cands.append(d)
    log(f'ETFD {nrows} 行 → 米国上場・東証 {len(uni)} 本・外す {sum(len(v) for v in out_list.values())}・残り {len(cands)}')

    # 新しい本・消えた本（A4）
    newl = None
    if os.path.exists(OLD_ETFD):
        old, _, osha = load(OLD_ETFD)
        oset = {d['t'] for d in old}
        nset = {d['t'] for d in uni}
        newl = dict(比べた写し=f'{os.path.relpath(OLD_ETFD, BASE)}（sha256 {osha[:12]}）',
                    新しい本=[dict(t=t, 名前=meta[t]['ja'] or meta[t]['nm'], 指数=meta[t]['idx'], 種類=meta[t]['cls'], 設定=meta[t]['inception'],
                                 外す理由=why_out(meta[t])) for t in sorted(nset - oset)],
                    消えた本=[next(f"{d['t']} {d['ja'] or d['nm']}" for d in old if d['t'] == t) for t in sorted(oset - nset)])

    # 物差しの本（未来）
    import best15_check as B
    import best15r_check as BR
    import unx_assets as U
    VARS = BR.VARS
    with contextlib.redirect_stdout(io.StringIO()):
        bres = U.build()
    rows, chains = bres['rows'], bres['chains']
    P33 = B.pool_list()
    B.century_extend(U)
    fast, cent = B.Fast(U, rows, chains, P33), B.Cent(U, P33)
    with contextlib.redirect_stdout(io.StringIO()):
        sc = B.selfcheck(U, rows, chains, P33, fast, cent)
    if not sc['一致']:
        raise SystemExit(f'回帰の検査（best15 の selfcheck）が通らない: {sc}')
    log('回帰の検査 ok', sc['形'], sc['100年を測れた形'])
    fbr = BR.FastBR(fast)
    keep = BR.POOL
    BR.POOL = P33
    vec, chk = BR.industry_vectors(U, rows)
    BR.POOL = keep
    if not all(chk.values()):
        raise SystemExit(f'業種の中身が rows の top_industries と違う: {[k for k, v in chk.items() if not v]}')
    stt = BR.industry_state()
    adj = {nm: BR.adj_vector(vec, stt, rt, P33)[0] for nm, rt in BR.RATES.items()}
    a0 = adj['主（20年の値）']
    stand_pool = [p for p in P33 if p not in POLICY_POOL and p not in NOW]

    # 値段
    need = sorted({d['y'] for d in cands} | set(REAL.values()) | {POOL_REAL.get(p, p) for p in stand_pool})
    rawp, perr = fetch(need)
    fxr = E.fx_monthly()
    if END not in fxr:
        raise SystemExit(f'ドル円の月次に {END} が無い（最後 {max(fxr)}）')
    ymeta = {d['y']: d for d in uni}
    for y in need:
        if y not in ymeta:
            raise SystemExit(f'{y} が ETFD に無い（物差しの本の器）')
    ry = {y: to_yen(ymeta[y], r, fxr) for y, r in rawp.items()}
    for t in REAL.values():
        for wn, w_ in (('W20', W20), ('W10', W10), ('W5', W5), ('W3', W3)):
            if not usable(rawp.get(t, {}), months(*w_)):
                raise SystemExit(f'今の本 {t} が {wn} にそろわない')
    base_real = {REAL[k]: v for k, v in NOW.items()}
    K = {wn: months(*w_) for wn, w_ in (('W20', W20), ('W10', W10), ('W5', W5), ('W3', W3))}
    base_path = {wn: path(base_real, ry, ks) for wn, ks in K.items()}
    base_st = {wn: st(base_path[wn], K[wn]) for wn in K}
    log('今の形（円）', base_st)

    def form_x(y, how='NDX'):
        f = dict(base_real)
        if how == 'NDX':
            f['QQQ'] -= SLOT
        else:
            f = {k: v * (100 - SLOT) / 100 for k, v in f.items()}
        f[y] = f.get(y, 0) + SLOT
        return f

    recs = {}
    for d in cands:
        y = d['y']
        rec = dict(t=d['t'], 名前=d['ja'] or d['nm'], 英語名=d['nm'], 指数=d['idx'], 種類=d['cls'], 地域=d['region'],
                   市場='米国上場' if d['us'] else '東証・名証', 経費率=d['er'], 設定=d['inception'])
        if y not in rawp:
            rec.update(組='値段なし', 理由=perr.get(y))
            recs[d['t']] = rec
            continue
        raw = rawp[y]
        ok = {wn: usable(raw, K[wn]) for wn in K}
        first = min(raw)
        rec['最初の月'] = first
        grp = 'L' if ok['W10'] else 'S5' if ok['W5'] else 'S3' if ok['W3'] else 'N'
        broke = [wn for wn in K if all(m in raw for m in K[wn]) and not ok[wn]]
        if broke:
            rec['壊れた窓'] = broke
        rec['組'] = grp
        rec['_ok'] = ok
        recs[d['t']] = rec
    log('組', {g: sum(1 for r in recs.values() if r['組'] == g) for g in ('L', 'S5', 'S3', 'N', '値段なし')})

    def jwin(g):
        return {'L': 'W10', 'S5': 'W5', 'S3': 'W3'}[g]

    def realized(rec, y):
        res = {}
        for wn in K:
            if not rec['_ok'][wn]:
                continue
            ks = K[wn]
            s = st(path(form_x(y), ry, ks), ks)
            b = base_st[wn]
            res[wn] = dict(s, 年率の差=round(s['年率'] - b['年率'], 2), 最大下落の差=round(s['最大下落'] - b['最大下落'], 1),
                           ぶれの差=round(s['ぶれ'] - b['ぶれ'], 1))
            sp = st(path(form_x(y, 'PRO'), ry, ks), ks)
            res[wn]['按分の年率の差'] = round(sp['年率'] - b['年率'], 2)
            res[wn]['按分の最大下落の差'] = round(sp['最大下落'] - b['最大下落'], 1)
        return res

    def okr_of(rec):
        r = rec['実績']
        p = lambda x: x is not None and x['年率の差'] > 0 and x['最大下落の差'] >= -1.0
        if rec['組'] == 'L':
            return p(r.get('W10')) and ('W20' not in r or p(r['W20']))
        if rec['組'] == 'S5':
            return p(r.get('W5')) and p(r.get('W3'))
        if rec['組'] == 'S3':
            return p(r.get('W3'))
        return None

    # 実績・同じ賭け
    for t, rec in recs.items():
        if rec['組'] not in ('L', 'S5', 'S3'):
            continue
        d = meta[t]
        y = d['y']
        rec['実績'] = realized(rec, y)
        ks = K[jwin(rec['組'])]
        cs = {b: round(xcorr(d, ry[y], ymeta[b], ry[b], ks), 3) for b in REAL.values()}
        bm = max(cs, key=cs.get)
        rec['今の本との相関の最大'] = f'{bm} {cs[bm]:.3f}'
        rec['今の形との相関'] = round(xcorr(d, ry[y], dict(us=True), base_path[jwin(rec['組'])], ks), 3)
        sx = st(ry[y], ks)
        rec['単体'] = {jwin(rec['組']): sx}
        if cs[bm] >= SAME_BET:
            rec['同じ賭け'] = bm
        rec['実績が通る'] = okr_of(rec)

    # 東証・名証で実績が通った本は日次の分割の誤りを見る
    jp_chk = [t for t, r in recs.items() if r.get('実績が通る') and not meta[t]['us']]
    log('日次の確かめ', len(jp_chk))
    dbad = {}
    for t in jp_chk:
        rec = recs[t]
        a = {'L': W20 if rec['_ok']['W20'] else W10, 'S5': W5, 'S3': W3}[rec['組']]
        try:
            bad = daily_shift(meta[t]['y'], a[0], a[1])
        except Exception as e:  # noqa
            bad = None
            rec['日次'] = f'取れない {str(e)[:80]}'
        if bad:
            dbad[t] = bad
            rec['日次の分割の誤り'] = bad
            for wn in list(rec['実績']):
                if any(m in bad for m in K[wn]):
                    rec['_ok'][wn] = False
                    del rec['実績'][wn]
            if rec['組'] == 'L' and not rec['_ok']['W10']:
                rec['組'] = 'S5' if rec['_ok']['W5'] else 'S3' if rec['_ok']['W3'] else 'N'
            rec['実績が通る'] = okr_of(rec) if rec['組'] in ('L', 'S5', 'S3') else None

    # 家族
    def order_key(t):
        d, r = meta[t], recs[t]
        return (r['最初の月'], 0 if d['us'] else 1, d['er'] if d['er'] is not None else 9.0, t)
    fams = {}
    for g in ('L', 'S5', 'S3'):
        ks = K[jwin(g)]
        mem = sorted([t for t, r in recs.items() if r['組'] == g and not r.get('同じ賭け')], key=order_key)
        reps = []
        for t in mem:
            d = meta[t]
            hit = None
            for rp in reps:
                if xcorr(d, ry[d['y']], meta[rp], ry[meta[rp]['y']], ks) >= FAMILY:
                    hit = rp
                    break
            if hit:
                recs[t]['家族'] = hit
                fams[hit].append(t)
            else:
                reps.append(t)
                recs[t]['家族'] = t
                fams[t] = [t]
        if g != 'L':
            lreps = [rp for rp in fams if recs[rp]['組'] == 'L']
            for t in mem:
                d = meta[t]
                for rp in lreps:
                    if xcorr(d, ry[d['y']], meta[rp], ry[meta[rp]['y']], ks) >= FAMILY:
                        recs[t]['L の家族の新しい器'] = rp
                        break

    # 未来の物差し（L・同じ賭けでない本）
    preal = {p: POOL_REAL.get(p, p) for p in stand_pool}
    pk10 = K['W10']
    for t, rec in recs.items():
        if rec['組'] != 'L' or rec.get('同じ賭け'):
            continue
        d = meta[t]
        y = d['y']
        s = None
        if t in stand_pool:
            s, how = t, '物差しの本そのもの'
        elif y in REAL_POOL and REAL_POOL[y] in stand_pool:
            s, how = REAL_POOL[y], f'物差しの本 {REAL_POOL[y]} の器'
        else:
            best = None
            for p, pr in preal.items():
                if pr not in ry or not all(m in ry[pr] for m in pk10):
                    continue
                c_ = xcorr(d, ry[y], ymeta[pr], ry[pr], pk10)
                if best is None or c_ > best[1]:
                    best = (p, c_)
            if best and best[1] >= STAND:
                s, how = best[0], f'同じ賭けで代える（W10 の相関 {best[1]:.3f}）'
            else:
                how = f'未来は測れない（最も近い物差しの本 {best[0]} の相関 {best[1]:.3f} < {STAND}）' if best else '未来は測れない'
        rec['未来の物差しの本'] = dict(本=s, 方法=how)
    used = sorted({r['未来の物差しの本']['本'] for r in recs.values() if r.get('未来の物差しの本', {}).get('本')})
    names = ['今'] + [f'+{s}' for s in used] + [f'+{s}（按分）' for s in used]

    def fform(nm):
        f = dict(NOW)
        if nm == '今':
            return f
        s = nm[1:].replace('（按分）', '')
        if nm.endswith('（按分）'):
            f = {k: v * (100 - SLOT) / 100 for k, v in f.items()}
        else:
            f['QQQM'] -= SLOT
        f[s] = f.get(s, 0) + SLOT
        return f
    Wm = np.array([[fform(nm).get(c, 0) for c in P33] for nm in names], dtype=np.float64)
    e, c = fast.eval(Wm), cent.eval(Wm)
    vres = {'主': fbr.eval(Wm, a0), '10年の値': fbr.eval(Wm, adj['10年の値']),
            '1位の業種を強く': fbr.eval(Wm, adj['1位の業種を強く（10年の値・Chips −4.0）']), '主の半分': fbr.eval(Wm, adj['主の半分']),
            '分散の上乗せなし': fbr.eval(Wm, a0, nobonus=True), '共分散をA2の窓から': fbr.eval(Wm, a0, cov2=True)}
    assert list(vres) == VARS, (list(vres), VARS)
    P100 = lambda v: None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v) * 100, 3)
    fut = {}
    for j, nm in enumerate(names):
        db = {v: float(vres[v]['mean_pi'][j] - vres[v]['mean_pi'][0]) for v in VARS}
        cm = float(c['c30med'][j]) if c['ok'][j] else None
        fut[nm] = dict(元の平均=P100(e['mean_pi'][j]), 元の15パーセント以上=P100(e['P15'][j]), 元の最大下落=P100(e['mdd'][j]),
                       基礎率の平均=P100(vres['主']['mean_pi'][j]), 百年の三十年の中央=None if cm is None else round(cm, 3),
                       _dm=float(e['mean_pi'][j] - e['mean_pi'][0]), _db=db,
                       差=dict(元の平均=P100(e['mean_pi'][j] - e['mean_pi'][0]), 元の15パーセント以上=P100(e['P15'][j] - e['P15'][0]),
                              元の最大下落=P100(e['mdd'][j] - e['mdd'][0]), 基礎率の平均_感度6本={v: P100(x) for v, x in db.items()},
                              基礎率の最小=P100(min(db.values())),
                              百年の中央=None if cm is None or not c['ok'][0] else round(cm - float(c['c30med'][0]), 3)))
    for t, rec in recs.items():
        s = (rec.get('未来の物差しの本') or {}).get('本')
        if not s:
            continue
        f_ = fut[f'+{s}']
        rec['未来'] = {k: v for k, v in f_.items() if not k.startswith('_')}
        rec['未来_按分'] = fut[f'+{s}（按分）']['差']
        rec['未来が通る'] = f_['_dm'] >= -EPS and all(x >= -EPS for x in f_['_db'].values())
    for t, rec in recs.items():
        if rec['組'] != 'L' or rec.get('同じ賭け'):
            continue
        okr, okf = rec.get('実績が通る'), rec.get('未来が通る')
        if okf is None:
            rec['判定'] = ('過去は通る' if okr else '過去も通らない') + '（未来は測れない）'
        else:
            rec['判定'] = {(True, True): '候補に残る', (False, True): '未来の物差しだけ通る', (True, False): '過去だけ通る',
                          (False, False): '通らない'}[(bool(okr), bool(okf))]

    # 答え
    L = [r for r in recs.values() if r['組'] == 'L' and not r.get('同じ賭け')]
    def fam_rows(cat):
        xs = [r for r in L if r.get('判定') == cat]
        return xs
    bmin = lambda r: r['未来']['差']['基礎率の最小']
    def per_fam(xs):
        seen, out = set(), []
        for r in xs:
            f = r.get('家族') or r['t']
            if f in seen:
                continue
            seen.add(f)
            out.append(r)
        return out
    a1 = sorted(fam_rows('候補に残る'), key=lambda r: -bmin(r))
    a2d = sorted(fam_rows('未来の物差しだけ通る'), key=lambda r: -bmin(r))
    a2o = sorted(fam_rows('過去だけ通る') + [r for r in L if r.get('判定') == '過去は通る（未来は測れない）'],
                 key=lambda r: -r['実績']['W10']['年率の差'])
    sh = [r for r in recs.values() if r['組'] in ('S5', 'S3') and not r.get('同じ賭け') and r.get('実績が通る')]
    a3 = sorted(sh, key=lambda r: -r['実績']['W3']['年率の差'])
    a1, a2d, a2o, a3 = per_fam(a1), per_fam(a2d), per_fam(a2o), per_fam(a3)
    brief = lambda r: dict(t=r['t'], 名前=r['名前'], 家族=r.get('家族'), 家族の本の数=len(fams.get(r.get('家族'), [])), 判定=r.get('判定'), 実績=r.get('実績'), 未来=(r.get('未来') or {}).get('差'),
                           未来の物差しの本=r.get('未来の物差しの本'), 単体=r.get('単体'), 経費率=r['経費率'], 今の本との相関の最大=r.get('今の本との相関の最大'))
    from collections import Counter
    cnt = Counter(r.get('判定') for r in L)
    answer = dict(
        A1_検討すべき=[brief(r) for r in a1],
        A2_守りの候補=[brief(r) for r in a2d[:10]] if not a1 else None,
        A2_攻めの候補=[brief(r) for r in a2o[:10]] if not a1 else None,
        A3_記録が短い=[dict(t=r['t'], 名前=r['名前'], 組=r['組'], 家族=r.get('家族'), 家族の本の数=len(fams.get(r.get('家族'), [])), 実績=r['実績'], 単体=r['単体'], 経費率=r['経費率'],
                       L_の家族の新しい器=r.get('L の家族の新しい器'), 今の本との相関の最大=r.get('今の本との相関の最大')) for r in a3[:10]],
        A5='配分は変えない')
    for r in recs.values():
        r.pop('_ok', None)
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/etf_more_check.py', kind='参考（配分は変えない・決まりは道具の頭に固定）',
               question='他に検討すべきETFがないか調べて', 今=NOW, 今_全体=dict(NOW_TOTAL, 個別株=CASTLE),
               母集団=dict(src='楽天証券 ETFD.csv 2026-11-22', sha256=sha, rows=nrows, 米国上場と東証=len(uni), 残り=len(cands),
                        外した本={k: dict(数=len(v), 本=v) for k, v in out_list.items()}),
               新しい本と消えた本=newl, 回帰の検査=sc, 今の形の実績=base_st, 今の形の未来=fut['今'],
               組の数={g: sum(1 for r in recs.values() if r['組'] == g) for g in ('L', 'S5', 'S3', 'N', '値段なし')},
               同じ賭けの数=sum(1 for r in recs.values() if r.get('同じ賭け')), 家族の数=len(fams), 判定の数=dict(cnt),
               答え=answer, 家族=fams, 本=recs, 日次の分割の誤り=dbad, 値段が取れない=perr, secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    log('判定', dict(cnt), '短い組で実績が通る', len(sh), f'{time.time() - t0:.0f}秒')
    for nm, xs in (('A1', a1), ('A2 守り', a2d[:10]), ('A2 攻め', a2o[:10]), ('A3', a3[:10])):
        log(nm, [(r['t'], r.get('判定'), (r.get('実績') or {}).get('W10' if r['組'] == 'L' else 'W3', {}).get('年率の差'),
                  (r.get('未来') or {}).get('差', {}).get('基礎率の最小')) for r in xs])


if __name__ == '__main__':
    main()
