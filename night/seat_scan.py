#!/usr/bin/env python3
"""night/seat_scan.py — FBT の席に置ける ETF・投資信託を全部から探す
（2026-11-23・ユーザー「他に検討すべきETFや投資信託はないの？」＝直前に FBT の席を XLK・XLV と比べた続き・参考・配分は変えない）

読むだけ。門・採点・配分（portfolio.json）・注文書には触れない。結果がどう出ても配分は変えない（入れるかはユーザーの明示指示のときだけ）。
★母集団・物差し・決まりはこの頭に書いたとおりで、結果を見る前にこのファイルをコミットしてから回す。
  （書く前に見たのは材料の形＝本数・設定日・基準価額の写しの有無と、下の「回す前に知っていたこと」だけ）

問いの読み方: 昨日の etf_more_check は「NASDAQ100 から5を回して足す」形で楽天の ETF を全部測った（候補に残る本は0）。
  まだ測っていないのは ①FBT の席（ETF 側の15）にほかの本を置いた場合 ②投資信託を形に入れた場合。この道具はその2つを測る。
今の形（origin/main の portfolio.json と照合・違えば止まる）: ETF 側 NASDAQ100 45 / SMH 20 / ITA 10 / FBT 15 / VBR 10（個別株10%は物差しの外）。
案: FBT の15をそのまま候補 X の15に替える（form_eval の XLK・XLV と同じ置き方）。判定は今の形で。
  参考（判定に使わない）: 私の選ぶ形 NASDAQ100 25 / SMH 35 / ITA 15 / FBT 15 / VBR 10 でも同じ入れ替えの数字を出す。

母集団①ETF: 楽天証券の ETF 一覧 ETFD.csv（2026-11-22 の写し・sha256 は etf_more_check と同じ）の米国上場と東証・名証。
  外すもの＝etf_more_check.why_out のまま（X1 レバレッジ・インバース／X2 通貨・ボラティリティ／X4 今の本と同じ指数／X5 方針＝金・国債）と、
  past_winners の是正2（東証の NASDAQ100 連動 ETF も X4）。
母集団②投資信託: 投信総合検索ライブラリーの全件（2026-11-22 の写し・5,874本）のうち、past_winners.fund_out で外れない本
  （単位型・ETF・確定拠出年金とラップ専用・レバレッジ型・NASDAQ100 連動・金・国債を外す）で、楽天証券で買える本。
  記録が10年以上（設定 2016-10-31 以前）: 基準価額の写しがある本だけ測る＝past_winners のふるい（設定 2006-11-30 以前の全部＋
    協会の10年の騰落率の上位300＋楽天で買える本の上位200）。写しの無い本は取り足さない（その中の10年の騰落率の最大は +275%＝年14.1%で、
    FBT の同じ10年の円の年率 17.2% に届かない＝FBT の席に置いて年率が上がる見込みが無い。本数と最大を出力に書く）。
  記録が10年未満（設定 2016-11-01 以後）: 協会の5年の騰落率の上位30本と、5年の無い本の3年の騰落率の上位30本だけ基準価額を取って測る
    （判定しない・参考）。
値段: ETF は Yahoo の配当込み月次（mw_common.yahoo）。円で測る——米国上場は FRED DEXJPUS の月末の比を掛け、NISA で戻らない外国の源泉税
  （米国の本は配当利回り×10%・それ以外の地域は×20%）を月割りで引く。東証・名証は円のまま（どれも etf_more_check.to_yen のまま）。
  投資信託は基準価額＋分配金の再投資（past_winners.fund_monthly・口数の併合と分割は比で戻す・31日を超える空きの月は使わない）。
  壊れた値: 月次で −60% 以下か +100% 以上の月がある窓は使わない。東証・名証の ETF で実績が通ったものは日次も見る（etf_more_check.daily_shift）。
窓（円・月次・2026-10 まで）: W20＝2006-12〜2026-10（239か月＝投資信託の基準価額の記録が 2006-11-24 からのため。ETF も同じ窓）・
  W10＝2016-11〜2026-10・W5＝2021-11〜2026-10・W3＝2023-11〜2026-10
  組: L＝W10 がそろう（W20 もそろえば W20 も見る）／S5＝W5 まで／S3＝W3 まで／N＝3年に満たない（測らない）
同じ賭け（判定しない・数と名前を出す）: 組の窓（L は W10・S5 は W5・S3 は W3）の相関が 0.95 以上
  （米国上場どうし・日本の器どうしは月次／東証・投資信託と米国上場の組は重ならない四半期＝etf_more_check.xcorr）。
  残りの4本（NASDAQ100・SMH・ITA・VBR）のどれかと 0.95 以上＝『残りの本と同じ賭け』（FBT の席に置くとその本を増やすのと同じ。
    NASDAQ100・XLK は form_eval で測りずみ）
  FBT と 0.95 以上＝『FBT と同じ賭けの別の器』（年率・最大下落・費用を並べるだけ）

物差し①実績（円）: 今の形と、FBT の15を X に替えた形を毎月組み直した月次の道で、年率・最大下落・ぶれの差（案 − 今・丸める前の値で判定＝
  etf_more_check は表示の桁で判定していた。ここは丸める前にそろえる）。
  実績が通る＝ L は W10 で 年率の差 > 0 かつ 最大下落の差 ≥ −1.0pt（W20 がそろう本は W20 でも同じ）。
  S5 は W5 と W3 の両方・S3 は W3 で同じ（記録が短い組は参考の印だけ・判定しない）
物差し②未来（L だけ・etf_more_check と同じ道具）: best15 の Fast（unx_assets.measure の式・5つの世界）・best15r の FastBR（業種の基礎率・感度6本）・
  Cent（100年の代用・NASDAQ100 の入れ替えを数えない写し＝参考）。物差しの本は best15 の33本から方針の本（GDX・GLDM・EDV・TLT・TIP・UST_HEDGED_2621）と
  今の5本を外したもの。X が物差しの本ならその本（EPI→EPI_LONG・1306.T→TOPIX）、無ければ W10 の相関（上と同じ測り方）が 0.95 以上の物差しの本で代える
  （名指し）。どちらも無ければ『未来は測れない』。
  未来が通る＝ 元の物差しの π加重の平均の差 ≥ 0 かつ 業種の基礎率の平均の差が感度6本すべてで ≥ 0（etf_more_check と同じ）
  席の役目（添える印・未来が測れる本だけ）: 年15%以上の確率の差 ≥ 0 かつ 年5%未満の確率の差 ≤ 0 かつ 最大下落の差 ≥ 0 なら『席の役目も保つ』
判定（L・同じ賭けでない本）: 候補に残る（実績も未来も通る）／未来の物差しだけ通る／過去だけ通る／通らない／
  過去は通る（未来は測れない）／過去も通らない（未来は測れない）
答えの決まり（結果を見る前に固定）:
  A1 『候補に残る』があれば『FBT の席で検討すべき本』として、基礎率の平均の差の感度6本の最小が大きい順に挙げる（『席の役目も保つ』の印を添える）
  A2 無ければ『FBT の席に置いて過去も未来も上回る本は無い』とし、『未来の物差しだけ通る』を守り寄りの候補として基礎率の最小の大きい順に上位10、
     『過去だけ通る』『過去は通る（未来は測れない）』を攻め寄りの候補（未来の物差しは支持しない・測れない）として W10 の年率の差の大きい順に
     ETF の上位10と投資信託の上位10を挙げる
  A3 記録が短い組（S5・S3）で実績が通った本は、W3 の年率の差の大きい順に ETF の上位10・投資信託の上位10を『記録が短い（判定しない）』として挙げる
  A4 『FBT と同じ賭けの別の器』は全部を表にする（判定しない）。『残りの本と同じ賭け』は本ごとの数と W10 の年率の差の上位10の名前だけ
  A1〜A3 の並びは家族ごとに1本（並びの上から見て、その窓の相関が 0.95 以上の上の本があればその家族に入れる・家族の本の数を添える）
  A5 どの結果でも配分は変えない
回帰の検査（どれかが外れれば止める）: (a) best15_check.selfcheck（速い評価が unx_assets.measure・century_monthly と一致）
  (b) 今の形の実績（W10・W5・W3）が out/etf_more_check.json の「今の形の実績」と一致
  (c) FBT→XLV・FBT→XLK の未来の数字（今の形と私の形）が out/form_eval_fbt_vs_xlv.json・out/form_eval_fbt_vs_xlk.json と表示の桁で一致
回す前に知っていたこと:
  ・form_eval（今日）: FBT→XLK は期待の年率 −0.07〜−0.09pt・最大下落 2〜4pt 深い／FBT→XLV は年15%以上 −1.0〜−1.6pt・最大下落 2〜4pt 浅い＝どちらも未来は通らない
  ・ndx45_smh25_check: 今の形の FBT の5を NASDAQ100・ITA・VBR・SMH へ回すと、期待の年率か基礎率の平均のどちらかが下がる（6本の中に両方を上げる行き先は無い）
  ・etf_more_check（昨日・NASDAQ100 から5）: 候補に残る0・未来の物差しだけ通るのはヘルスケア（XLV・VHT・IXJ）とエネルギー（XLE・VDE・IXC）・過去は COPX だけ
  ・past_winners（今日）: 10年・20年の年率の上位は半導体・テクノロジーの本（今と同じ賭け）。S&P500 を20年で上回った投資信託は723本中3本
  ・1本ずつの円の年率: FBT W10 17.2%・W20 15.1%／XLV 17.1%・12.6%／ITA 18.2%・13.9%／VBR 15.4%・10.4%／S&P500 20.1%・12.6%／NASDAQ100 25.2%・17.5%／SMH 38.1%・21.5%
  ・見込み（測っていない）: W10 だけなら S&P500 型やテックの本の多くが通るが、W20 がそろう本は FBT の 15.1% が壁になり通る本は少ない。
    未来の物差しは通る本がほとんど無い＝A1 は0か、ごく少ない
⚠ 限界: 実績の窓は2006年以降・2016年以降の一つの時代（テックが勝った時代）／FBT の2011〜2015年のバイオの上げが W20 の壁を高くしている／
  未来の物差しは予想と仮定（分散の上乗せ・業種の基礎率）／同じ賭けの代用は近似／投資信託は未来の物差しでほとんど測れない／
  投資信託の10年のふるいは10年の騰落率の上位だけ／税は外国の源泉税だけ／東証と米国上場の時差／Yahoo の値の誤り／
  楽天で買える＝ NISA 成長投資枠の対象とは限らない（投資信託は印あり・ETF は印なし）／15%の入れ替えでも差は小さい
使い方: python3 night/seat_scan.py → out/seat_scan.json（基準価額の取り足しを除いて約2分）
"""
import contextlib, datetime, io, json, math, os, subprocess, sys, time
from collections import Counter
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etfcand as E            # noqa: E402
import etf_more_check as EM    # noqa: E402
import past_winners as PW      # noqa: E402
import beat_ret_check as BT    # noqa: E402

OUT = os.path.join(BASE, 'out', 'seat_scan.json')
SEAT = 'FBT'
MAIN = dict(BT.NOWF)
MINE = {'QQQM': 25, 'SMH': 35, 'ITA': 15, 'FBT': 15, 'VBR': 10}
FORMS = {'今の形': MAIN, '私の形': MINE}
CASTLE = 10
REAL = {'QQQM': 'QQQ', 'SMH': 'SMH', 'ITA': 'ITA', 'FBT': 'FBT', 'VBR': 'VBR'}
WIN = {'W20': (200612, 202610), 'W10': (201611, 202610), 'W5': (202111, 202610), 'W3': (202311, 202610)}
END = 202610
SAME = 0.95
EPS = 1e-12
MDD_TOL = 0.010
NTOP, NSHORT = 10, 30
EST10 = 20161031


def log(*a):
    print('[seat_scan]', *a, file=sys.stderr, flush=True)


def P100(v, d=2):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v) * 100, d)


def usable(it, ks):
    src = it.get('raw') or it['yen']
    return EM.usable(src, ks) and all(m in it['yen'] for m in ks)


def xc(a, b, ks):
    return EM.xcorr(a, a['yen'], b, b['yen'], ks)


def form_path(parts, ks):
    tot = float(sum(w for _, w in parts))
    return {m: sum(w / tot * s[m] for s, w in parts) for m in ks}


def ra(r, k):
    try:
        return float(r.get(k))
    except (TypeError, ValueError):
        return None


def label(it):
    return f"{it['key']} {it['nm']}"


def main():
    t0 = time.time()
    live = json.loads(subprocess.run(['git', 'show', 'origin/main:portfolio.json'], capture_output=True, text=True,
                                     cwd=BASE, check=True).stdout)['target']
    w, cp = BT.etf_side(live)
    if not BT.same(w, MAIN) or cp != CASTLE:
        raise SystemExit(f'今の形が origin/main の portfolio.json と違う: {w}・個別株 {cp}（beat_ret_check の NOWF を直してから回す）')
    K = {wn: E.months(*ab) for wn, ab in WIN.items()}

    # ── 母集団① ETF
    uni, nrows, sha = EM.load(EM.ETFD, EM.ETFD_SHA)
    why = {d['t']: EM.why_out(d) for d in uni}
    for d in uni:
        if not why[d['t']] and not d['us'] and (d['idx'] or '').startswith('NASDAQ 100 TR'):
            why[d['t']] = 'X4 今の本と同じ指数（東証の NASDAQ100 連動）'
    cands = [d for d in uni if not why[d['t']]]
    ecnt = Counter((why[d['t']] or '測る候補')[:2] if why[d['t']] else '測る候補' for d in uni)
    log(f'ETFD {nrows} 行 → 米国上場・東証 {len(uni)} 本・測る候補 {len(cands)}')

    # ── 未来の物差し
    import best15_check as B
    import best15r_check as BR
    import unx_assets as U
    with contextlib.redirect_stdout(io.StringIO()):
        bres = U.build()
    rows, chains = bres['rows'], bres['chains']
    P33 = B.pool_list()
    B.century_extend(U)
    fast, cent = B.Fast(U, rows, chains, P33), B.Cent(U, P33)
    with contextlib.redirect_stdout(io.StringIO()):
        sc = B.selfcheck(U, rows, chains, P33, fast, cent)
    if not sc['一致']:
        raise SystemExit(f'回帰の検査 (a) が通らない: {sc}')
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
    VARS = list(BR.VARS)
    stand_pool = [p for p in P33 if p not in EM.POLICY_POOL and p not in MAIN]
    preal = {p: EM.POOL_REAL.get(p, p) for p in stand_pool}
    log('回帰の検査 (a) ok・物差しの本', len(stand_pool))

    # ── 値段（ETF）
    need = sorted({d['y'] for d in cands} | set(REAL.values()) | set(preal.values()))
    rawp, perr = EM.fetch(need)
    fxr = E.fx_monthly()
    if END not in fxr:
        raise SystemExit(f'ドル円の月次に {END} が無い（最後 {max(fxr)}）')
    ymeta = {d['y']: d for d in uni}

    def mk(d):
        r = rawp.get(d['y'])
        if not r:
            return None
        return dict(key=d['t'], nm=d['ja'] or d['nm'], kind='米国ETF' if d['us'] else '東証ETF', us=d['us'],
                    raw={m: v for m, v in r.items() if m <= END}, yen=EM.to_yen(d, r, fxr), y=d['y'], 設定=d['inception'],
                    費用=d['er'], 指数=d['idx'], 種類=d['cls'], 地域=d['region'])
    held = {}
    for k, t in REAL.items():
        it = mk(ymeta[t])
        if not it or not all(usable(it, ks) for ks in K.values()):
            raise SystemExit(f'今の本 {t} の値段がそろわない')
        held[k] = it
    pool_it = {}
    for p, y in preal.items():
        if y in ymeta and rawp.get(y):
            pool_it[p] = mk(ymeta[y])
    C = {}
    for d in cands:
        it = mk(d)
        if it is None:
            C[d['t']] = dict(key=d['t'], nm=d['ja'] or d['nm'], kind='米国ETF' if d['us'] else '東証ETF', 組='値段なし', 理由=perr.get(d['y']))
        else:
            C[d['t']] = it

    # ── 母集団② 投資信託
    L = PW.load_list()
    frows = L['rows']
    fo = {r['associFundCd']: PW.fund_out(r) for r in frows}
    fcnt = Counter((fo[r['associFundCd']] or '外さない')[:2] if fo[r['associFundCd']] else '外さない' for r in frows)
    elig = [r for r in frows if fo[r['associFundCd']] is None and PW.rak(r)]
    long_ = [r for r in elig if PW.est(r) <= EST10]
    short = [r for r in elig if PW.est(r) > EST10]
    s5 = sorted([r for r in short if ra(r, 'standardPriceRa5y') is not None], key=lambda r: -ra(r, 'standardPriceRa5y'))[:NSHORT]
    s3 = sorted([r for r in short if ra(r, 'standardPriceRa5y') is None and ra(r, 'standardPriceRa3y') is not None],
                key=lambda r: -ra(r, 'standardPriceRa3y'))[:NSHORT]
    miss = PW.fetch_navs({r['associFundCd']: r for r in s5 + s3})
    nonav = []
    D = PW.D
    for r in long_ + s5 + s3:
        a = r['associFundCd']
        p = os.path.join(PW.NAVDIR, f'{a}.csv')
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            if PW.est(r) <= EST10:
                nonav.append(r)
            continue
        mon, sp = PW.fund_monthly(PW.nav_rows(open(p, 'rb').read()))
        if not mon:
            continue
        nm = D.nfkc(r.get('fundNm')) + (f"（{D.nfkc(r.get('fundNkNm'))}）" if r.get('fundNkNm') else '')
        C[a] = dict(key=a, nm=nm, kind='投資信託', us=False, yen=mon, 設定=(r.get('establishedDate') or '')[:10],
                    費用=round(float(r['trustReward']) * 1.1, 4) if r.get('trustReward') not in (None, '') else None,
                    運用会社=D.nfkc(r.get('entrustCmpNm')), NISA=PW.nisa_of(r), 協会の10年の騰落率=PW.ra10(r),
                    協会の5年の騰落率=ra(r, 'standardPriceRa5y'), 協会の3年の騰落率=ra(r, 'standardPriceRa3y'),
                    口数の併合分割を戻した=[f'{d_} {s_}' for d_, s_ in sp][:4] or None)
    nn = [PW.ra10(r) for r in nonav if PW.ra10(r) is not None]
    fund_note = dict(全件=len(frows), 基準日=L.get('std'), 内訳=dict(fcnt), 外さない本のうち楽天で買える本=len(elig),
                     記録が10年以上=len(long_), うち基準価額の写しがあり測った本=sum(1 for r in long_ if r['associFundCd'] in C),
                     写しが無く測らない本=len(nonav), 測らない本のうち10年の騰落率が無い本=len(nonav) - len(nn), 測らない本の10年の騰落率の最大=max(nn) if nn else None,
                     測らない本の10年の騰落率の最大の年率=round(100 * ((1 + max(nn) / 100) ** 0.1 - 1), 2) if nn else None,
                     記録が10年未満=len(short), うち測った本_5年の上位と3年の上位=sum(1 for r in s5 + s3 if r['associFundCd'] in C),
                     基準価額が取れなかった本=len(miss))
    log('投資信託', fund_note)

    # ── 今の形の実績
    def parts_of(form, it=None):
        ps = [(held[k]['yen'], w_) for k, w_ in form.items() if k != SEAT or it is None]
        if it is not None:
            ps.append((it['yen'], form[SEAT]))
        return ps
    base_raw = {fn: {wn: E.stats(form_path(parts_of(f), ks), ks) for wn, ks in K.items()} for fn, f in FORMS.items()}
    show = lambda s: dict(年率=round(100 * s['cagr'], 2), 最大下落=round(100 * s['mdd'], 1), ぶれ=round(100 * s['vol'], 1))
    base_st = {fn: {wn: show(s) for wn, s in x.items()} for fn, x in base_raw.items()}
    ref_more = json.load(open(os.path.join(BASE, 'out', 'etf_more_check.json')))['今の形の実績']
    reg_b = {wn: base_st['今の形'][wn] == ref_more[wn] for wn in ('W10', 'W5', 'W3')}
    if not all(reg_b.values()):
        raise SystemExit(f"回帰の検査 (b) が通らない: {base_st['今の形']} / {ref_more}")
    log('回帰の検査 (b) ok・今の形（円）', base_st['今の形'])

    # ── 組・実績・同じ賭け
    def p_ok(x):
        return x is not None and x['_dc'] > 0 and x['_dm'] >= -MDD_TOL

    def okr_of(it):
        r = it['実績']['今の形']
        if it['組'] == 'L':
            return p_ok(r.get('W10')) and ('W20' not in r or p_ok(r['W20']))
        if it['組'] == 'S5':
            return p_ok(r.get('W5')) and p_ok(r.get('W3'))
        if it['組'] == 'S3':
            return p_ok(r.get('W3'))
        return None

    def realized(it):
        res = {}
        for fn, f in FORMS.items():
            for wn, ks in K.items():
                if not it['_ok'][wn]:
                    continue
                s = E.stats(form_path(parts_of(f, it), ks), ks)
                b = base_raw[fn][wn]
                res.setdefault(fn, {})[wn] = dict(show(s), 年率の差=round(100 * (s['cagr'] - b['cagr']), 2), 最大下落の差=round(100 * (s['mdd'] - b['mdd']), 1),
                                                  ぶれの差=round(100 * (s['vol'] - b['vol']), 1), _dc=s['cagr'] - b['cagr'], _dm=s['mdd'] - b['mdd'])
        return res
    jwin = {'L': 'W10', 'S5': 'W5', 'S3': 'W3'}

    def assess(it):
        ok = it['_ok']
        it['組'] = 'L' if ok['W10'] else 'S5' if ok['W5'] else 'S3' if ok['W3'] else 'N'
        for k in ('実績', '今の本との相関', '同じ賭け', '単体', '実績が通る'):
            it.pop(k, None)
        if it['組'] == 'N':
            return
        ks = K[jwin[it['組']]]
        it['実績'] = realized(it)
        cs = {k: xc(it, held[k], ks) for k in REAL}
        it['今の本との相関'] = {k: round(v, 3) for k, v in cs.items()}
        rest = max((k for k in REAL if k != SEAT), key=lambda k: cs[k])
        if cs[SEAT] >= SAME and cs[SEAT] >= cs[rest]:
            it['同じ賭け'] = SEAT
        elif cs[rest] >= SAME:
            it['同じ賭け'] = rest
        it['単体'] = {wn: show(E.stats(it['yen'], K[wn])) for wn in K if ok[wn]}
        it['実績が通る'] = okr_of(it)
    for it in C.values():
        if it.get('組') == '値段なし':
            continue
        it['_ok'] = {wn: usable(it, ks) for wn, ks in K.items()}
        it['最初の月'] = min(it['yen']) if it['yen'] else None
        assess(it)
    log('組', dict(Counter((it['kind'], it.get('組')) for it in C.values())))

    # 東証・名証の ETF で実績が通ったものは日次も見る（水準がずれたままの月を含む窓は使わない → 組と実績をやり直す）
    dbad = {}
    for it in C.values():
        if it['kind'] != '東証ETF' or not it.get('実績が通る'):
            continue
        a = {'L': WIN['W20'] if it['_ok']['W20'] else WIN['W10'], 'S5': WIN['W5'], 'S3': WIN['W3']}[it['組']]
        try:
            bad = EM.daily_shift(it['y'], a[0], a[1])
        except Exception as e:  # noqa
            bad = None
            it['日次'] = f'取れない {str(e)[:80]}'
        if bad:
            dbad[it['key']] = bad
            it['日次の分割の誤り'] = bad
            for wn in K:
                if it['_ok'][wn] and any(m in bad for m in K[wn]):
                    it['_ok'][wn] = False
            assess(it)
    log('日次の分割の誤り', dbad)

    # ── 未来の物差し（L・同じ賭けでない本）
    k10 = K['W10']
    pool_ok = {p: pit for p, pit in pool_it.items() if pit and usable(pit, k10)}
    for it in C.values():
        if it.get('組') != 'L' or it.get('同じ賭け'):
            continue
        s, how = None, None
        if it['kind'] != '投資信託' and it['key'] in stand_pool:
            s, how = it['key'], '物差しの本そのもの'
        elif it['kind'] != '投資信託' and it['y'] in EM.REAL_POOL and EM.REAL_POOL[it['y']] in stand_pool:
            s, how = EM.REAL_POOL[it['y']], f"物差しの本 {EM.REAL_POOL[it['y']]} の器"
        else:
            best = None
            for p, pit in pool_ok.items():
                c_ = xc(it, pit, k10)
                if best is None or c_ > best[1]:
                    best = (p, c_)
            if best and best[1] >= SAME:
                s, how = best[0], f'同じ賭けで代える（W10 の相関 {best[1]:.3f}）'
            else:
                how = f'未来は測れない（最も近い物差しの本 {best[0]} の相関 {best[1]:.3f} < {SAME}）' if best else '未来は測れない'
        it['未来の物差しの本'] = dict(本=s, 方法=how)
    used = sorted({it['未来の物差しの本']['本'] for it in C.values() if (it.get('未来の物差しの本') or {}).get('本')} | {'XLV', 'XLK'})

    def fform(base, s):
        f = {k: v for k, v in base.items() if k != SEAT}
        f[s] = f.get(s, 0) + base[SEAT]
        return f
    flist = [MAIN, MINE] + [fform(MAIN, s) for s in used] + [fform(MINE, s) for s in used]
    Wm = np.array([[f.get(c, 0) for c in P33] for f in flist], dtype=np.float64)
    e, c = fast.eval(Wm), cent.eval(Wm)
    vres = {'主': fbr.eval(Wm, a0), '10年の値': fbr.eval(Wm, adj['10年の値']),
            '1位の業種を強く': fbr.eval(Wm, adj['1位の業種を強く（10年の値・Chips −4.0）']), '主の半分': fbr.eval(Wm, adj['主の半分']),
            '分散の上乗せなし': fbr.eval(Wm, a0, nobonus=True), '共分散をA2の窓から': fbr.eval(Wm, a0, cov2=True)}
    assert list(vres) == VARS, (list(vres), VARS)
    n = len(used)
    fut = {}
    for i, s in enumerate(used):
        o = {}
        for fn, j, j0 in (('今の形', 2 + i, 0), ('私の形', 2 + n + i, 1)):
            db = {v: float(vres[v]['mean_pi'][j] - vres[v]['mean_pi'][j0]) for v in VARS}
            cm = float(c['c30med'][j] - c['c30med'][j0]) if c['ok'][j] and c['ok'][j0] else None
            dm, dp15, dp5, dmd = (float(e[k][j] - e[k][j0]) for k in ('mean_pi', 'P15', 'P5', 'mdd'))
            o[fn] = dict(値=dict(期待の年率=P100(e['mean_pi'][j]), 年15パーセント以上=P100(e['P15'][j]), 年5パーセント未満=P100(e['P5'][j]),
                                最大下落=P100(e['mdd'][j], 1), 最悪の世界=P100(e['worst'][j]), 基礎率の平均=P100(vres['主']['mean_pi'][j]),
                                基礎率の5パーセント未満=P100(vres['主']['P5'][j])),
                         差=dict(期待の年率=P100(dm, 3), 年15パーセント以上=P100(dp15), 直近15年を外した年15パーセント以上=P100(e['P15_noA2'][j] - e['P15_noA2'][j0]),
                                年5パーセント未満=P100(dp5), 最大下落=P100(dmd, 1), 最悪の世界=P100(e['worst'][j] - e['worst'][j0], 3),
                                基礎率の平均_感度6本={v: P100(x, 3) for v, x in db.items()}, 基礎率の最小=P100(min(db.values()), 3),
                                基礎率の5パーセント未満=P100(vres['主']['P5'][j] - vres['主']['P5'][j0]), 百年の三十年の中央_数えない写し=None if cm is None else round(cm, 3)),
                         _dm=dm, _db=db, _bmin=min(db.values()),
                         未来が通る=bool(dm >= -EPS and all(x >= -EPS for x in db.values())),
                         席の役目も保つ=bool(dp15 >= -EPS and dp5 <= EPS and dmd >= -EPS))
        fut[s] = o
    base_f = {fn: dict(期待の年率=P100(e['mean_pi'][j]), 年15パーセント以上=P100(e['P15'][j]), 年5パーセント未満=P100(e['P5'][j]), 最大下落=P100(e['mdd'][j], 1),
                       最悪の世界=P100(e['worst'][j]), 基礎率の平均=P100(vres['主']['mean_pi'][j]), 基礎率の5パーセント未満=P100(vres['主']['P5'][j]))
              for fn, j in (('今の形', 0), ('私の形', 1))}

    # 回帰の検査 (c): form_eval と表示の桁で一致
    reg_c = {}
    for s, fnm in (('XLV', 'form_eval_fbt_vs_xlv.json'), ('XLK', 'form_eval_fbt_vs_xlk.json')):
        fe = json.load(open(os.path.join(BASE, 'out', fnm)))
        for fn, nmf, base_nm in (('今の形', f'今の形の FBT を {s} に', '今の形（main）'), ('私の形', f'私の形の FBT を {s} に', '私の選ぶ形（FBT 15）')):
            y = fe['形ごと'][nmf]['物差し13']['V1']
            v = fut[s][fn]['値']
            pair = next(p for p in fe['対ごとの判定'] if p['案'] == nmf and p['相手'] == base_nm)
            reg_c[f'{s}・{fn}'] = dict(
                期待の年率=v['期待の年率'] == y['①期待の年率'], 年15パーセント以上=v['年15パーセント以上'] == y['②年15%以上の確率'],
                年5パーセント未満=v['年5パーセント未満'] == y['③年5%未満の確率'], 最大下落=v['最大下落'] == y['④最大下落'],
                基礎率の平均=v['基礎率の平均'] == y['⑥基礎率の平均'],
                基礎率の感度6本の差=all(abs(fut[s][fn]['差']['基礎率の平均_感度6本'][k] - pair['基礎率の感度6本の相手との差'][k]['平均']) < 1e-9 for k in VARS))
    if not all(all(x.values()) for x in reg_c.values()):
        raise SystemExit(f'回帰の検査 (c) が通らない: {reg_c}')
    log('回帰の検査 (c) ok')

    for it in C.values():
        s = (it.get('未来の物差しの本') or {}).get('本')
        if s:
            it['未来'] = {fn: {k: v for k, v in x.items() if not k.startswith('_')} for fn, x in fut[s].items()}
            it['未来が通る'] = fut[s]['今の形']['未来が通る']
            it['_bmin'] = fut[s]['今の形']['_bmin']
    for it in C.values():
        if it.get('組') != 'L' or it.get('同じ賭け'):
            continue
        okr, okf = it.get('実績が通る'), it.get('未来が通る')
        if okf is None:
            it['判定'] = ('過去は通る' if okr else '過去も通らない') + '（未来は測れない）'
        else:
            it['判定'] = {(True, True): '候補に残る', (False, True): '未来の物差しだけ通る', (True, False): '過去だけ通る',
                          (False, False): '通らない'}[(bool(okr), bool(okf))]

    # ── 答え
    def fams(items, ks, top):
        reps = []
        for it in items:
            hit = next((rp for rp in reps if xc(it, rp, ks) >= SAME), None)
            if hit is not None:
                hit['_mem'].append(label(it))
            else:
                it['_mem'] = []
                reps.append(it)
        return reps[:top]

    def brief(it):
        o = dict(名札=it['key'], 名前=it['nm'], 種類=it['kind'], 組=it['組'], 判定=it.get('判定'), 設定=it.get('設定'), 費用=it.get('費用'),
                 指数=it.get('指数'), NISA=it.get('NISA'), 運用会社=it.get('運用会社'), 単体=it.get('単体'),
                 実績={fn: {wn: {k: v for k, v in x.items() if not k.startswith('_')} for wn, x in r.items()} for fn, r in it['実績'].items()},
                 今の本との相関=it.get('今の本との相関'), 未来の物差しの本=it.get('未来の物差しの本'),
                 未来の差=(it.get('未来') or {}).get('今の形', {}).get('差'), 席の役目も保つ=(it.get('未来') or {}).get('今の形', {}).get('席の役目も保つ'),
                 未来の差_私の形=(it.get('未来') or {}).get('私の形', {}).get('差'),
                 家族のほかの本=it.get('_mem') or None, 家族の本の数=1 + len(it.get('_mem') or []))
        return {k: v for k, v in o.items() if v is not None}
    Lc = [it for it in C.values() if it.get('組') == 'L' and not it.get('同じ賭け')]
    cat = lambda *names: [it for it in Lc if it.get('判定') in names]
    dc10 = lambda it: it['実績']['今の形']['W10']['_dc']
    dc3 = lambda it: it['実績']['今の形']['W3']['_dc']
    a1 = fams(sorted(cat('候補に残る'), key=lambda it: -it['_bmin']), k10, 999)
    a2d = fams(sorted(cat('未来の物差しだけ通る'), key=lambda it: -it['_bmin']), k10, NTOP)
    past = sorted(cat('過去だけ通る', '過去は通る（未来は測れない）'), key=lambda it: -dc10(it))
    a2o_e = fams([it for it in past if it['kind'] != '投資信託'], k10, NTOP)
    a2o_f = fams([it for it in past if it['kind'] == '投資信託'], k10, NTOP)
    sh = sorted([it for it in C.values() if it.get('組') in ('S5', 'S3') and not it.get('同じ賭け') and it.get('実績が通る')], key=lambda it: -dc3(it))
    a3_e = fams([it for it in sh if it['kind'] != '投資信託'], K['W3'], NTOP)
    a3_f = fams([it for it in sh if it['kind'] == '投資信託'], K['W3'], NTOP)
    vessels = sorted([it for it in C.values() if it.get('同じ賭け') == SEAT], key=lambda it: (it['組'], -it['実績']['今の形'][jwin[it['組']]]['_dc']))
    rest_same = [it for it in C.values() if it.get('同じ賭け') and it['同じ賭け'] != SEAT]
    rs_cnt = Counter((it['同じ賭け'], it['組']) for it in rest_same)
    rs_top = sorted([it for it in rest_same if it['組'] == 'L'], key=lambda it: -dc10(it))[:NTOP]
    cntj = Counter((('投資信託' if it['kind'] == '投資信託' else 'ETF'), it.get('判定')) for it in Lc)
    answer = dict(
        A1_FBTの席で検討すべき本=[brief(it) for it in a1],
        A2_結論=None if a1 else 'FBT の席に置いて過去も未来も上回る本は無い',
        A2_守り寄りの候補_未来の物差しだけ通る=[brief(it) for it in a2d] if not a1 else None,
        A2_攻め寄りの候補_ETF=[brief(it) for it in a2o_e] if not a1 else None,
        A2_攻め寄りの候補_投資信託=[brief(it) for it in a2o_f] if not a1 else None,
        A3_記録が短い_ETF=[brief(it) for it in a3_e], A3_記録が短い_投資信託=[brief(it) for it in a3_f],
        A4_FBTと同じ賭けの別の器=[brief(it) for it in vessels],
        A4_残りの本と同じ賭けの数={f'{k[0]}・{k[1]}': v for k, v in sorted(rs_cnt.items())},
        A4_残りの本と同じ賭け_W10の年率の差の上位=[dict(名札=it['key'], 名前=it['nm'], 種類=it['kind'], 同じ賭け=it['同じ賭け'],
                                        年率の差_W10=it['実績']['今の形']['W10']['年率の差'], 最大下落の差_W10=it['実績']['今の形']['W10']['最大下落の差']) for it in rs_top],
        A5='配分は変えない')
    def compact(it):
        o = dict(名前=it['nm'], 種類=it['kind'], 組=it.get('組'))
        for k in ('設定', '費用', '最初の月', '同じ賭け', '判定', '実績が通る', '未来が通る', '日次の分割の誤り', '日次', '理由'):
            if it.get(k) is not None:
                o[k] = it[k]
        sp = it.get('未来の物差しの本')
        if sp:
            o['未来の物差しの本'] = sp.get('本') or sp.get('方法')
        r = (it.get('実績') or {}).get('今の形')
        if r:
            o['実績_今の形_年率の差と最大下落の差'] = {wn: [x['年率の差'], x['最大下落の差']] for wn, x in r.items()}
        if it.get('今の本との相関'):
            o['今の本との相関'] = it['今の本との相関']
        return o
    recs = {k: compact(it) for k, it in C.items()}
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/seat_scan.py', kind='参考（配分は変えない・決まりは道具の頭に固定）',
               question='他に検討すべきETFや投資信託はないの？', 席=f'{SEAT}（ETF 側の {MAIN[SEAT]}）', 形=FORMS, 窓={k: f'{a}〜{b}（{len(K[k])}か月）' for k, (a, b) in WIN.items()},
               母集団=dict(ETF=dict(src='楽天証券 ETFD.csv 2026-11-22', sha256=sha, rows=nrows, 米国上場と東証=len(uni), 内訳=dict(ecnt), 値段が取れない=len(perr)),
                        投資信託=fund_note),
               回帰の検査={'(a) selfcheck': sc, '(b) 今の形の実績が etf_more_check と一致': reg_b, '(c) form_eval と一致': reg_c},
               今の形の実績=base_st, 今の形の未来=base_f, FBT_単体={wn: show(E.stats(held[SEAT]['yen'], ks)) for wn, ks in K.items()},
               組の数={f'{a}・{b}': v for (a, b), v in sorted(Counter((('投資信託' if it['kind'] == '投資信託' else 'ETF'), it.get('組')) for it in C.values()).items())},
               判定の数={f'{a}・{b}': v for (a, b), v in sorted(cntj.items(), key=lambda x: str(x[0]))},
               実績が通った数=dict(L=sum(1 for it in Lc if it.get('実績が通る')), L_W20もそろう本=sum(1 for it in Lc if it['_ok']['W20'] and it.get('実績が通る')),
                             L_W20がそろう本の数=sum(1 for it in Lc if it['_ok']['W20']), 未来が通った数=sum(1 for it in Lc if it.get('未来が通る')),
                             未来を測れた数=sum(1 for it in Lc if it.get('未来が通る') is not None)),
               未来_物差しの本ごと={s: {fn: {k: v for k, v in x.items() if not k.startswith('_')} for fn, x in o.items()} for s, o in fut.items()},
               答え=answer, 本=recs, 日次の分割の誤り=dbad, ETFの値段が取れない=perr, secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    log('判定', dict(cntj), f'{time.time() - t0:.0f}秒')
    for nm, xs in (('A1', a1), ('A2 守り', a2d), ('A2 攻め ETF', a2o_e), ('A2 攻め 投信', a2o_f), ('A3 ETF', a3_e), ('A3 投信', a3_f), ('器', vessels)):
        log(nm, [(it['key'], it['nm'][:18], it.get('判定'), it['実績']['今の形'].get(jwin[it['組']], {}).get('年率の差')) for it in xs])


if __name__ == '__main__':
    main()
