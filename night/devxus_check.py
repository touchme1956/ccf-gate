#!/usr/bin/env python3
"""night/devxus_check.py — 先進国株式（除く米国）を今の配分に入れるのは？（2026-10-20・ユーザー「先進国株式除く米国は？？」・参考・判定なし）

ユーザーが頼んだ比べ（ルール10: 頼まれたときだけ）。配分（portfolio.json）・門・採点・注文書には触れない。
作りは night/gridnasa_check.py（＝ita10_check の物差し）を写した。形と物差しは結果を見る前にこのファイルで固定し、回す前にコミットする。
直前の問いが「個別株をはずすべきでは？」だったので、個別株10の代わりに入れる形（案A）と、NASDAQ100 から回す形（案B・案C）の両方を測る。

器（物差しの行）: VEA（Vanguard FTSE Developed Markets ETF・FTSE Developed All Cap ex US・経費率0.03%・楽天で買える）。
  unx_assets.build の VEA の行（2007-07 から本物・それより前は同じ指数の投資信託 VTMGX でつなぐ＝etf_forward_rank の行のまま）。
  同じ賭けの器（参考・L5）: SPDW 0.03%・IDEV 0.04%・EFA 0.32%（カナダを含まない）・
  投資信託 楽天・全世界株式（除く米国）インデックス・ファンド（FTSE Global All Cap ex US＝新興国を含む）・SBI・V・先進国株式（除く米国）。

形（全体の%）:
  ETF 側だけ（個別株10は物差しの外・合計90＝ita10_check・gridnasa_check と同じ）
    今                              : QQQM 40 / SMH 25 / ITA 10 / SHLD 5 / XLV 5 / FBT 5
    案B（NASDAQ100 の10を VEA へ）  : QQQM 30 / SMH 25 / ITA 10 / SHLD 5 / XLV 5 / FBT 5 / VEA 10
    案C（NASDAQ100 の5を VEA へ）   : QQQM 35 / SMH 25 / ITA 10 / SHLD 5 / XLV 5 / FBT 5 / VEA 5
  個別株を含む全体（合計100・個別株は ETF で代える＝castle10_check・alloc_check と同じ2通り）
    今V（個別株10を市場 VOO で代える）           : 今 ＋ VOO 10
    今S（個別株10を席の業種の写しで代える）       : 今 ＋ unx_assets.castle_copy()（今の席を業種の ETF へ: CW→ITA・LRCX/ASML→SMH・MSFT/GOOGL→QQQM）
    案A（個別株10を VEA へ）                     : 今 ＋ VEA 10
  ⚠ どちらの代え方も銘柄ごとの値動き（席の社の固有のぶれ）を持たない＝個別株をやめる守りの効き目はこの物差しでは小さく出る。
比べる組（差だけ・判定の名前は付けない）: 案B − 今・案C − 今・案A − 今V・案A − 今S
物差し: gridnasa_check と同じ（unx_assets.measure・ndx_swap_check の感度5本の差・3つの枠〔USD・崩れあり／USD・ドットコム級なし／円・崩れあり〕・
  上振れ〔upside_check.upside〕・過去の転がる積立〔upside_check.rolling・2000-09〜〕・楽天の経費率）。
  ⚠ 感度の『半導体の基礎率』は VEA の半導体を数えない（chips_adj は米国の本だけ＝VEA は割り引きも上乗せも0）。
100年の代用（年次・参考）: VEA の月次の写しが無い（unx_assets.MONTHLY_OK に無い）ので、unx_assets.century_parts の年次（月次の写しを暦年で複利）に
  VEA＝下の L1 の米国外（JST・GDP 加重・ドル建て）を足し、年1回の積立の市場（French の米国市場）との比を20年・30年で。
  JST が2020年で終わるので、すべての形を2020年までの窓でそろえる。起点は1928年からと1950年から（下の欠測の偏りのため）。
  形: 今S・今V・案A・案B と案C（個別株は席の業種の写しで足す＝gridnasa_check の『全体の形』と同じ）。
長い歴史（参考・物差しの外）:
  L1 JST Macrohistory R6（年次・1871〜2020・night/nx_jst の World・mask_prt・bench をそのまま使う＝超インフレと取引所の閉鎖の年は欠測〔0と読まない〕・
     PRT 2016〜2020 は欠測）: 米国 対 先進国（米国除く）＝米国以外の15か国（AUS BEL CHE DEU DNK ESP FIN FRA GBR ITA JPN NLD NOR PRT SWE）を
     ドル建ての GDP で加重した株の総リターン（nx_jst.bench の 'gdp'・ドル建て・名目・重みは nx_jst の決まり）。
     期間の年率（全期間・1871〜1913・1914〜1949・1950〜1989・1990〜2020・2000〜2020）・転がる20年／30年の一括で米国外が勝った割合と差・
     年1回の20年積立の比（米国外÷米国）・混ぜた形（米国90/米国外10・80/20・70/30・毎年組み直す）の20年／30年の積立の米国100に対する比。
     ⚠ 欠測の年を落とすと戦争・超インフレの大損（1940年代のドイツ・日本など）が抜け、米国外を良く見せる向き＝1950年からの版も出す。
  L2 Ken French（月次・Developed_ex_US_3_Factors の市場〔Mkt-RF+RF〕と米国の市場・1990-07〜）: 年率・ぶれ・最大下落・相関・10年ごとの年率・
     転がる10年／20年の毎月の積立の比（米国外÷米国）・混ぜた形（10/20%）の20年の積立の米国100に対する比。
  L3 本物の器（Yahoo の調整後終値・ドル建て・最初の月は途中からなので落とす）: VEA・VTMGX を SPY・QQQ と同じ月で（年率・ぶれ・最大下落・相関）・暦年（2008〜）。
  L4 機関の10年予想（out/bestfund_cma.json の chosen・2026-10-11 の写し）: 先進国（米国除く）と米国大型株（無ければ米国株全体）の両方がある機関ごとの差・
     米国の大型グロースがある機関はその値も。
  L5 器: out/broker_lineup.json の経費率・投資信託協会の一覧（out/_nx_cache/newfunds/jita_full.json・基準日 2026-10-09）の信託報酬（税抜）・
     販売会社に楽天証券があるか・NISA の印・金融庁のつみたて投資枠の一覧（out/tsumitate_lineup.json・2026-09-18 版）に名前があるか。
  L6 VEA の中身（Alpha Vantage ETF_PROFILE・last_updated 2026-10-16・2026-10-20 に取得・写しは AV_FILE〔gitignore〕）:
     本数・上位10社（会社でない行は除く）・半導体の会社（下の SEMI_NAMES の名前で数える・Samsung Electronics は電機の他の事業も含む）の重み。
  L7 中身の集中（lookthrough --what-if・参考）: 個別株は今の席×2%・VEA は中身が未取得として乗る（米国株を持たない＝NVDA の値は正しい側・
     半導体の連鎖の下限は VEA の分を数えない＝L6 の半導体の重み×VEA の比を別に出す）。
回帰の検査: (a) 今が out/better_mix_check.json の『今』と一致（USD・崩れあり・小数1桁） (b) 感度の主が measure と 1e-9 以内（USD と円）。外れれば止める。
使い方: python3 night/devxus_check.py → out/devxus_check.json（JST の写しが無ければ先に python3 night/nx_jst_data.py）
"""
import datetime, json, math, os, re, statistics as S, sys, time, unicodedata

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'devxus_check.json')
AV_FILE = os.path.join(BASE, 'out', '_nx_cache', 'devxus', 'VEA_av_profile_20261020.json')

ETF_NOW = {'QQQM': 40, 'SMH': 25, 'ITA': 10, 'SHLD': 5, 'XLV': 5, 'FBT': 5}
NOW, B, C = '今（ETF 側）', '案B（NASDAQ100 の10を VEA へ）', '案C（NASDAQ100 の5を VEA へ）'
NOWV, NOWS, A = '今V（個別株10を VOO で代える）', '今S（個別株10を席の業種の写しで代える）', '案A（個別株10を VEA へ）'
PAIRS = {'案B − 今': (B, NOW), '案C − 今': (C, NOW), '案A − 今V': (A, NOWV), '案A − 今S': (A, NOWS)}
PREV_REF = os.path.join(BASE, 'out', 'better_mix_check.json')
PREV_NAME = '今'
REG_KEYS = ('P15π', 'P5π（5%未満）', '最悪の世界', '最大下落', 'ぶれ', 'π加重の平均の年率')
JST_PERIODS = (('全期間', 1871, 2020), ('1871〜1913', 1871, 1913), ('1914〜1949', 1914, 1949), ('1950〜1989', 1950, 1989),
               ('1990〜2020', 1990, 2020), ('2000〜2020', 2000, 2020))
MIX_W = (0.10, 0.20, 0.30)
CENT_FIRST = (1928, 1950)
CENT_LAST = 2020
TRUSTS = ('楽天・全世界株式（除く米国）インデックス・ファンド', 'ＳＢＩ・Ｖ・先進国株式（除く米国）インデックス・ファンド',
          'ＳＢＩ・Ｖ・全世界株式（除く米国）ファンド')
SAME_BET = ('VEA', 'SPDW', 'IDEV', 'EFA', 'VEU', 'VXUS', 'VT')
SEMI_NAMES = ('SAMSUNG ELECTRONICS', 'SK HYNIX', 'ASML', 'TOKYO ELECTRON LTD', 'ADVANTEST', 'INFINEON', 'STMICROELECTRONICS', 'ASM INTERNATIONAL',
              'BE SEMICONDUCTOR', 'DISCO CORP', 'RENESAS', 'LASERTEC', 'SCREEN HOLDINGS', 'KOKUSAI ELECTRIC', 'SOCIONEXT', 'ARM HOLDINGS',
              'NXP SEMICONDUCTORS', 'SUMCO', 'ROHM CO', 'ASMPT', 'NOVA LTD', 'TOWER SEMICONDUCTOR', 'HANMI SEMICONDUCTOR')
# 会社でない行（現金の担保・通貨・為替予約）。名前の一部で外すと AIR LIQUIDE・DOLLARAMA・METCASH などの会社を誤って外すので、行全体の形で決める
NONCO_RE = (r'^SLBBH\d+$', r'^[A-Z]{3}/[A-Z]{3} FWD \d{8}$', r'^(US|CANADIAN|NEW ZEALAND|SINGAPORE|AUSTRALIAN|HONG KONG) DOLLAR$',
            r'^JAPANESE YEN$', r'^BRITISH POUND STERLING$', r'^EURO$', r'^SWISS FRANC$', r'^(DANISH|NORWEGIAN|SWEDISH) KRON[EA]$',
            r'^ISRAELI (NEW )?SHEKEL$', r'^POLISH ZLOTY$')
YAHOO = ('VEA', 'VTMGX', 'SPY', 'QQQ')


def path(xs):
    w = pk = 1.0
    mdd = 0.0
    for x in xs:
        w *= 1 + x
        pk = max(pk, w)
        mdd = min(mdd, w / pk - 1)
    return w, mdd


def stats(xs, per_year):
    w, mdd = path(xs)
    yrs = len(xs) / per_year
    return dict(年率=round(100 * (w ** (1 / yrs) - 1), 2), ぶれ=round(100 * S.pstdev(xs) * math.sqrt(per_year), 1), 最大下落=round(100 * mdd, 1),
                年率割るぶれ=round((w ** (1 / yrs) - 1) / (S.pstdev(xs) * math.sqrt(per_year)), 3), 期間の数=len(xs))


def geo(series, keys):
    return math.prod(1 + series[k] for k in keys) ** (1 / len(keys)) - 1


def dca(xs):
    v = 0.0
    for x in xs:
        v = (v + 1) * (1 + x)
    return v


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))]


def dist(v):
    """[(起点, 比)] → 中央値・下位10%点・最悪・最良・上回った割合"""
    xs = [x for _, x in v]
    if not xs:
        return None
    return dict(窓=len(xs), 起点=f'{v[0][0]}〜{v[-1][0]}', 中央値=round(S.median(xs), 3), 下位10パーセント点=round(q(xs, 0.10), 3),
                最悪=round(min(xs), 3), 最良=round(max(xs), 3), 上回った割合=round(sum(x > 1 for x in xs) / len(xs), 2))


# ───────────────────────── L1 JST（年次・1871〜2020） ─────────────────────────
def jst_long():
    import nx_jst as J
    if not os.path.exists(J.SER):
        raise SystemExit(f'JST の写しが無い: {J.SER}（先に python3 night/nx_jst_data.py）')
    _, data = J.load_raw()
    data = J.mask_prt(data, 'missing')
    W = J.World(data)
    ex = [c for c in J.UNIVERSE if c != 'USA']
    exus = J.bench(W, ex, 'usd', 'gdp')
    us = {y: W.ret('eq', 'usd', 'USA', y) for y in range(J.Y_FIRST + 1, J.Y_LAST + 1)}
    us = {y: r for y, r in us.items() if r is not None}
    years = sorted(set(exus) & set(us))
    ncty = {y: sum(1 for c in ex if W.ret('eq', 'usd', c, y) is not None and W.gdp_w(c, y - 2 if J.FIX['gdp_lag'] else y - 1) is not None) for y in years}
    periods = {}
    for lab, a, b in JST_PERIODS:
        ys = [y for y in years if a <= y <= b]
        periods[lab] = dict(年=f'{ys[0]}〜{ys[-1]}（{len(ys)}年）', 米国=round(100 * geo(us, ys), 2), 米国外=round(100 * geo(exus, ys), 2),
                            差_米国外引く米国=round(100 * (geo(exus, ys) - geo(us, ys)), 2))
    yset = set(years)

    def roll(n, first):
        lump, dcr = [], []
        for y in years:
            ys = list(range(y, y + n))
            if y < first or any(t not in yset for t in ys):
                continue
            d = geo(exus, ys) - geo(us, ys)
            lump.append((y, d))
            dcr.append((y, dca([exus[t] for t in ys]) / dca([us[t] for t in ys])))
        ds = [d for _, d in lump]
        won = [y for y, d in lump if d > 0]
        return dict(一括=dict(窓=len(ds), 起点=f'{lump[0][0]}〜{lump[-1][0]}', 米国外が勝った割合=round(sum(d > 0 for d in ds) / len(ds), 2),
                              差の中央値=round(100 * S.median(ds), 2), 差の最小=round(100 * min(ds), 2), 差の最大=round(100 * max(ds), 2),
                              米国外が勝った起点=_runs(won)),
                    年1回の積立の比_米国外割る米国=dist(dcr))

    rolling = {f'{n}年・起点{first}〜': roll(n, first) for n in (20, 30) for first in (1871, 1950)}

    def mix(w, n, first):
        v = []
        for y in years:
            ys = list(range(y, y + n))
            if y < first or any(t not in yset for t in ys):
                continue
            mx = [(1 - w) * us[t] + w * exus[t] for t in ys]
            v.append((y, dca(mx) / dca([us[t] for t in ys])))
        return dist(v)

    mixes = {f'米国{round(100 * (1 - w))}/米国外{round(100 * w)}': {f'{n}年・起点{first}〜': mix(w, n, first) for n in (20, 30) for first in (1871, 1950)}
             for w in MIX_W}
    corr = round(_corr([us[y] for y in years], [exus[y] for y in years]), 3)
    corr50 = round(_corr([us[y] for y in years if y >= 1950], [exus[y] for y in years if y >= 1950]), 3)
    return dict(出典='JST Macrohistory R6（night/nx_jst_data.py の写し）・nx_jst.World / mask_prt / bench（gdp）',
                国=ex, 年ごとの国の数_最小=min(ncty.values()), 国の数が15未満の年=[y for y in years if ncty[y] < 15],
                期間の年率=periods, 年次の相関={'全期間': corr, '起点1950〜': corr50}, 転がる窓=rolling, 混ぜた形の積立の比_混ぜた形割る米国100=mixes,
                ann=dict(exus=exus, us=us))


def _runs(ys):
    """連続した年の塊（[1871,1872,1873,1880] → '1871〜1873・1880'）"""
    if not ys:
        return ''
    out, s, p = [], ys[0], ys[0]
    for y in ys[1:]:
        if y == p + 1:
            p = y
            continue
        out.append(f'{s}〜{p}' if s != p else f'{s}')
        s = p = y
    out.append(f'{s}〜{p}' if s != p else f'{s}')
    return '・'.join(out)


def _corr(a, b):
    ma, mb = S.mean(a), S.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return num / math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))


# ───────────────────────── L2 French（月次・1990-07〜） ─────────────────────────
def french_long():
    import etfcand as EC
    import gaps_common as G
    dx = EC.french_region_mkt('Developed_ex_US_3_Factors')
    us, _ = G.french_mkt()
    ms = sorted(set(dx) & set(us))
    out = dict(窓=f'{ms[0]}〜{ms[-1]}（{len(ms)}か月）', 米国=stats([us[m] for m in ms], 12), 米国外=stats([dx[m] for m in ms], 12),
               月次の相関=round(_corr([us[m] for m in ms], [dx[m] for m in ms]), 3))
    dec = {}
    for lab, a, b in (('1990-07〜1999-12', 199007, 199912), ('2000〜2009', 200001, 200912), ('2010〜2019', 201001, 201912), ('2020〜', 202001, 999912)):
        mm = [m for m in ms if a <= m <= b]
        dec[lab] = dict(米国=stats([us[m] for m in mm], 12)['年率'], 米国外=stats([dx[m] for m in mm], 12)['年率'], 月数=len(mm))
    out['10年ごとの年率'] = dec
    for n in (120, 240):
        v = [(ms[i], dca([dx[m] for m in ms[i:i + n]]) / dca([us[m] for m in ms[i:i + n]])) for i in range(len(ms) - n + 1)]
        out[f'転がる{n // 12}年の毎月の積立の比_米国外割る米国'] = dist(v)
    for w in (0.10, 0.20):
        v = [(ms[i], dca([(1 - w) * us[m] + w * dx[m] for m in ms[i:i + 240]]) / dca([us[m] for m in ms[i:i + 240]])) for i in range(len(ms) - 240 + 1)]
        out[f'混ぜた形 米国{round(100 * (1 - w))}/米国外{round(100 * w)} の20年の積立の比_割る米国100'] = dist(v)
    return out


# ───────────────────────── L3 本物の器 ─────────────────────────
def vehicles_record():
    import mw_common as M
    mm, miss = {}, {}
    for t in YAHOO:
        try:
            mm[t] = M.yahoo(t)
        except Exception as e:  # noqa — 取れない本は名指しして外す（黙って0にしない）
            miss[t] = str(e)[:160]
    if any(t in miss for t in ('VEA', 'SPY', 'QQQ')):
        return dict(取れない=miss)
    out = dict(取れない=miss) if miss else {}
    for base in [b for b in ('VEA', 'VTMGX') if b in mm]:
        ms = [m for m in sorted(mm[base]) if all(m in mm[t] for t in (base, 'SPY', 'QQQ'))][1:]
        out[f'{base} の窓'] = dict(窓=f'{ms[0]}〜{ms[-1]}（{len(ms)}か月）',
                                  本ごと={t: dict(stats([mm[t][m] for m in ms], 12),
                                                  SPYとの相関=round(_corr([mm[t][m] for m in ms], [mm['SPY'][m] for m in ms]), 2),
                                                  QQQとの相関=round(_corr([mm[t][m] for m in ms], [mm['QQQ'][m] for m in ms]), 2)) for t in (base, 'SPY', 'QQQ')})
    cal = {}
    ms = sorted(m for m in mm['VEA'] if all(m in mm[t] for t in ('VEA', 'SPY', 'QQQ')))
    for y in range(2008, 2027):
        ys = [m for m in ms if m // 100 == y]
        if not ys:
            continue
        cal[str(y) + ('' if len(ys) == 12 else f'（{len(ys)}か月）')] = {t: round(100 * (math.prod(1 + mm[t][m] for m in ys) - 1), 1) for t in ('VEA', 'SPY', 'QQQ')}
    out['暦年（VEA・SPY・QQQ・%）'] = cal
    out['VEA が SPY を上回った暦年'] = [k for k, v in cal.items() if v['VEA'] > v['SPY']]
    return out


# ───────────────────────── L4 機関の10年予想 ─────────────────────────
def institutions():
    c = json.load(open(os.path.join(BASE, 'out', 'bestfund_cma.json')))
    rows, diffs = [], []
    for inst, d in c['chosen'].items():
        cl = d.get('classes', {})
        g = lambda k: (cl.get(k) or {}).get('value_pct')     # noqa: E731
        dev = g('DEV_EX_US')
        usk = 'US_LARGE' if g('US_LARGE') is not None else ('US_TOTAL' if g('US_TOTAL') is not None else None)
        if dev is None or usk is None:
            continue
        d_ = round(dev - g(usk), 2)
        diffs.append(d_)
        rows.append(dict(機関=inst, 先進国除く米国=dev, 米国=g(usk), 米国の種類=usk, 差=d_, 米国の大型グロース=g('US_LARGE_GROWTH')))
    return dict(出典='out/bestfund_cma.json の chosen（各機関の公表値・名目・ドル建て・10年前後）', 機関の数=len(rows),
                米国外が上=sum(x > 0 for x in diffs), 同じ=sum(x == 0 for x in diffs), 米国が上=sum(x < 0 for x in diffs),
                差の中央値=round(S.median(diffs), 2), 機関ごと=sorted(rows, key=lambda r: -r['差']))


# ───────────────────────── L5 器・L6 VEA の中身 ─────────────────────────
def _norm(s):
    """名前の突き合わせ用（全角・半角の違い・中黒・空白を無視）"""
    return unicodedata.normalize('NFKC', s).replace('・', '').replace(' ', '')


def vehicles():
    bl = json.load(open(os.path.join(BASE, 'out', 'broker_lineup.json')))['etfs']
    etf = {t: dict(名前=(bl.get(t) or {}).get('nm'), 楽天=t in bl, 経費率=(bl.get(t) or {}).get('er')) for t in SAME_BET}
    tl = json.load(open(os.path.join(BASE, 'out', 'tsumitate_lineup.json')))
    tnames = {r['nm'] for sec in ('指定インデックス投資信託', '指定インデックス投資信託以外の投資信託（アクティブ運用投信等）', '上場株式投資信託（ETF）')
              for r in tl[sec]['rows']}
    tidx = {r['nm']: r['idx'] for sec in ('指定インデックス投資信託', '上場株式投資信託（ETF）') for r in tl[sec]['rows']}
    j = json.load(open(os.path.join(BASE, 'out', '_nx_cache', 'newfunds', 'jita_full.json')))
    tr = {}
    for nm in TRUSTS:
        r = next((x for x in j['rows'] if x['fundNm'] == nm), None)
        if r is None:
            tr[nm] = dict(一覧に無い=True)
            continue
        sellers = [i.get('instName') for i in (r.get('institutionInfo') or []) if isinstance(i, dict)]
        tn = next((t for t in tnames if _norm(t) == _norm(nm)), None)
        tr[nm] = dict(設定日=(r.get('establishedDate') or '')[:10], 信託報酬_税抜=r.get('trustReward'), 純資産_百万円=r.get('totalNetAssets'),
                      騰落率_1年=r.get('standardPriceRa1y'), 騰落率_3年=r.get('standardPriceRa3y'), 販売会社の数=len(sellers),
                      楽天証券で買える='楽天証券' in sellers, 販売会社_抜粋=[s for s in sellers if s in ('楽天証券', 'ＳＢＩ証券', '松井証券', 'マネックス証券')],
                      NISAの印=dict(nisaFlg=r.get('nisaFlg'), nisaGrowthFlg=r.get('nisaGrowthFlg')),
                      つみたて投資枠の一覧に名前=tn is not None, 指数=tidx.get(tn) if tn else None)
    idev = next((n for n in tnames if '先進国(除く米国)' in _norm(n)), None)
    return dict(ETF=etf, 投資信託=tr, 基準日=j.get('std'),
                つみたて投資枠の一覧のETF=dict(名前=idev, 指数=tidx.get(idev),
                                        注='金融庁の一覧（2026-09-18 版）に載る ETF。楽天のつみたて投資枠で買えるかは確かめていない'))


def vea_holdings():
    d = json.load(open(AV_FILE))
    h = [(x['description'], x['symbol'], float(x['weight'])) for x in d['holdings']]
    co = [x for x in h if not any(re.match(p_, x[0].upper()) for p_ in NONCO_RE)]
    non = [x for x in h if x not in co]
    semi = [x for x in co if any(k in x[0].upper() for k in SEMI_NAMES)]
    return dict(出典='Alpha Vantage ETF_PROFILE（symbol=VEA・last_updated ' + d.get('last_updated', '') + '・2026-10-20 に取得）',
                純資産=float(d['net_assets']), 経費率=float(d['net_expense_ratio']), 配当利回り=float(d['dividend_yield']), 設定=d['inception_date'],
                本数=len(h), 掲載の重みの合計=round(sum(w for *_, w in h), 4), 会社でない行=[dict(名前=n, 重み=w) for n, _, w in non],
                上位10社=[dict(名前=n, 重み=w) for n, _, w in sorted(co, key=lambda x: -x[2])[:10]],
                上位10社の合計=round(sum(w for *_, w in sorted(co, key=lambda x: -x[2])[:10]), 4),
                半導体の会社=dict(合計=round(sum(w for *_, w in semi), 4), 内訳=[dict(名前=n, 重み=w) for n, _, w in sorted(semi, key=lambda x: -x[2])],
                              注='名前で数えた（SEMI_NAMES）。Samsung Electronics は携帯・家電も含む'),
                業種=d.get('sectors'), 業種の注='Alpha Vantage の業種の欄は重みが 0.01 以下で壊れている＝使わない')


# ───────────────────────── 本体 ─────────────────────────
def main():
    import unx_assets as U
    import upside_check as UC
    import ndx_swap_check as N
    import bestpf_eval as E
    t0 = time.time()
    W_CRASH, W_DC = UC.W_CRASH, UC.W_DC
    res = U.build()
    rows, chains = res['rows'], res['chains']
    cc, seats, cpct = U.castle_copy()
    if abs(cpct - 10) > 1e-9:
        raise SystemExit(f'個別株の目標が10%でない（{cpct}）＝形を作り直してから回す')
    F = {NOW: dict(ETF_NOW), B: dict(ETF_NOW, QQQM=30, VEA=10), C: dict(ETF_NOW, QQQM=35, VEA=5),
         NOWV: dict(ETF_NOW, VOO=10), NOWS: U.whole(ETF_NOW, cc), A: dict(ETF_NOW, VEA=10)}
    for nm in (NOW, B, C):
        assert abs(sum(F[nm].values()) - 90) < 1e-9, nm
    for nm in (NOWV, NOWS, A):
        assert abs(sum(F[nm].values()) - 100) < 1e-9, nm
    assets = sorted({a for f in F.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, assets)
    pi, _, _ = E.load_pi()
    _, sim = U.tables()
    U.log('USD の枠（', len(F), '形）')
    tab_usd = U.measure(F, rows, chains, mega=mega)
    ref = json.load(open(PREV_REF))['results']['USD・崩れあり（主）'][PREV_NAME]
    reg_a, ok_a = {}, True
    for k in REG_KEYS:
        a, b = tab_usd[W_CRASH][NOW][k], ref[k]
        same = UC.r1(a) == UC.r1(b)
        reg_a[k] = dict(better_mix_check=b, この道具=a, 一致=same)
        ok_a = ok_a and same
    k4, chips = N.chips_adj(rows, assets)
    vt_usd = N.variants(F, rows, chains, k4)
    reg_b = N.regress_variants(vt_usd, tab_usd)
    U.log('回帰の検査', ok_a, reg_b['max_abs_diff'])
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/devxus_check.py', kind='参考・判定なし（ユーザーが頼んだ比べ）',
               question='先進国株式除く米国は？？',
               regression={'(a) 今が out/better_mix_check.json の『今』と一致（USD・崩れあり・小数1桁）': dict(ok=ok_a, rows=reg_a),
                           '(b) 感度の計算の主と unx_assets.measure（USD・丸める前・1e-9）': {k: v for k, v in reg_b.items() if k != 'rows'}})
    if not (ok_a and reg_b['ok']):
        doc['decision'] = '回帰の検査に失敗＝止めた'
        json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
        raise SystemExit('回帰の検査に失敗')
    U.log('円の枠')
    ch_jpy, fx_url = U.jpy_chains(chains)
    tab_jpy = U.measure(F, rows, ch_jpy, mega=mega)
    vt_jpy = N.variants(F, rows, ch_jpy, k4)
    reg_j = N.regress_variants(vt_jpy, tab_jpy)
    doc['regression']['(b) 円の枠でも同じ'] = {k: v for k, v in reg_j.items() if k != 'rows'}
    if not reg_j['ok']:
        doc['decision'] = '回帰の検査に失敗（円）＝止めた'
        json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
        raise SystemExit('回帰の検査に失敗（円）')

    def show(r):
        return {k: r[k] for k in ('P15π', 'P15π（A2を外す）', 'P5π（5%未満）', 'P0π（元本割れ）', '最悪の世界', 'π加重の平均の年率', 'ぶれ', '最大下落',
                                  '崩れ2000型_16〜18年目', '下落2022型_16年目', '過去の転がる20年で15%以上', '世界ごとの年率')}
    table = {}
    for nm in F:
        r = tab_usd[W_CRASH][nm]
        q_, pr_ = UC.upside(sim, r['_raw'], pi)
        table[nm] = dict(show(r), 上振れ=dict(pr_, 内部収益率の分位=q_))
    roll = {nm: UC.rolling(f, rows, chains) for nm, f in F.items()}
    frames = {'USD・崩れあり（主）': (vt_usd, W_CRASH), 'USD・ドットコム級なし': (vt_usd, W_DC), '円・崩れあり': (vt_jpy, W_CRASH)}
    diffs = {}
    for cj, (a, b) in PAIRS.items():
        diffs[cj] = {}
        for fn, (vt, wn) in frames.items():
            j = N.judge(vt, wn, a, b)
            diffs[cj][fn] = {k: x['差'] for k, x in j['感度'].items()}     # 差だけ（判定の名前は付けない）

    U.log('長い歴史: JST')
    L1 = jst_long()
    ann_ex = L1.pop('ann')
    U.log('長い歴史: French')
    L2 = french_long()
    U.log('本物の器')
    L3 = vehicles_record()
    L4 = institutions()
    L5 = vehicles()
    L6 = vea_holdings()

    # ── 100年の代用（年次）: VEA＝JST の米国外（GDP 加重・ドル建て）──
    CP = U.century_parts()
    ann = dict(CP['ann'])
    ann['VEA'] = {y: r for y, r in ann_ex['exus'].items()}
    am = {y: r for y, r in CP['ann_mkt'].items() if y <= CENT_LAST}
    cent_forms = {NOWS: F[NOWS], NOWV: F[NOWV], A: F[A], B + '＋個別株の写し': U.whole(F[B], cc), C + '＋個別株の写し': U.whole(F[C], cc)}

    def cent_annual(f, first):
        keys = [k for k, w in f.items() if w > 0]
        miss = [k for k in keys if k not in ann]
        if miss:
            return dict(写しが無い本=miss)
        years = sorted(y for y in am if y >= first and all(y in ann[k] for k in keys))
        tw = sum(f[k] for k in keys)
        r = {y: sum(f[k] / tw * ann[k][y] for k in keys) for y in years}
        out = {}
        for n in (30, 20):
            v = []
            for y in years:
                ys = range(y, y + n)
                if any(t not in r or t not in am for t in ys):
                    continue
                v.append((y, dca([r[t] for t in ys]) / dca([am[t] for t in ys])))
            out[f'{n}年の積立（年次・年1回）'] = dist(v)
        return out
    cent = {f'起点{first}〜（窓は{CENT_LAST}年まで）': {nm: cent_annual(f, first) for nm, f in cent_forms.items()} for first in CENT_FIRST}

    # ── 中身の集中（lookthrough・個別株は今の席×2%・VEA は未取得として乗る）──
    N.NET_ARG.update({'VEA': 'VEA'})
    castle_seats = ','.join(f'{s}={cpct / len(seats):g}' for s in seats)
    look_cases = {NOW: (dict(ETF_NOW), castle_seats), A: (dict(ETF_NOW, VEA=10), 'CW=0'),
                  B: (dict(F[B]), castle_seats), C: (dict(F[C]), castle_seats)}
    look = {}
    semi_vea = L6['半導体の会社']['合計']
    for nm, (f, ca) in look_cases.items():
        N.CASTLE_ARG = ca
        try:
            look[nm] = N.lookthrough(f)
            look[nm]['城'] = ('なし（個別株10を VEA へ）' if ca == 'CW=0' else f'{ca}（席{len(seats)}社×{cpct / len(seats):g}%）')
            look[nm]['VEA の中の半導体の会社（L6・資産全体の%）'] = round(f.get('VEA', 0) * semi_vea, 2)
        except Exception as e:                       # 参考だけ・読めなければ名指し
            look[nm] = dict(読めず=str(e)[:200])
    bl = json.load(open(os.path.join(BASE, 'out', 'broker_lineup.json')))['etfs']
    er = {a: (bl.get(a) or {}).get('er') for a in assets}

    doc.update(
        forms=F, pairs={k: list(v) for k, v in PAIRS.items()}, castle_copy=dict(seats=seats, castle_pct=cpct, copy=cc),
        vea_row={k: (round(100 * rows['VEA'][k], 2) if isinstance(rows['VEA'].get(k), (int, float)) else None) for k in ('A1', 'A1_gross', 'A2', 'B', 'C')},
        vea_chain=dict(最初=min(chains['VEA']), 最後=max(chains['VEA']), 注='2007-07 から本物の VEA・それより前は VTMGX（etf_forward_rank の行）'),
        results={'USD・崩れあり（主）': table, 'USD・ドットコム級なし': {nm: show(tab_usd[W_DC][nm]) for nm in F},
                 '円・崩れあり': {nm: show(tab_jpy[W_CRASH][nm]) for nm in F},
                 '過去の転がる積立（USD・2000-09〜2026-09）': roll, '感度5本の差（判定の名前は付けない）': diffs,
                 '100年の代用（年次・VEA は JST の米国外）': cent,
                 'L1 JST 1871〜2020（米国 対 米国外15か国・GDP 加重・ドル建て）': L1, 'L2 French 月次 1990-07〜': L2, 'L3 本物の器': L3,
                 'L4 機関の10年予想': L4, 'L5 器': L5, 'L6 VEA の中身': L6, 'L7 中身の集中（lookthrough・参考）': look,
                 '楽天の経費率（out/broker_lineup.json）': er},
        K4_半導体の基礎率={c: dict(Chips=(None if chips[c] is None else round(chips[c], 3)), 足す年率=round(100 * k4[c], 3)) for c in assets},
        frames={'USD': 'night/bestpf_check.py と同じ（ドル建て）', '円': f'月次のドル建ての値に FRED DEXJPUS の月末の比（{fx_url}）・B/C/D はドルのまま'},
        caveats=['判定はしない・配分は変えない（参考）',
                 '個別株の代え方（VOO・席の業種の写し）は銘柄ごとの値動きを持たない＝個別株をやめる守りの効き目は小さく出る',
                 '感度の『半導体の基礎率』は VEA の半導体（Samsung・SK hynix・ASML など）を数えない',
                 'JST の米国外は欠測の年（超インフレ・取引所の閉鎖）を落とした GDP 加重＝戦争の大損が抜けて米国外を良く見せる向き（1950年からの版も出した）・'
                 'GDP 加重は時価総額加重（VEA）と同じではない・カナダは JST に株の列が無く入っていない',
                 '機関の予想は当たった記録が乏しい（同じ割高さの理屈で米国の負けを10年以上言い続けてきた機関もある）'],
        secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    U.log('→', OUT, f'{time.time() - t0:.0f}秒')
    for nm in F:
        r = table[nm]
        U.log(f"{nm:<28} P15 {r['P15π']:5.1f} P20 {r['上振れ']['P20（道の束）']:5.1f} P5 {r['P5π（5%未満）']:5.1f} 最悪 {r['最悪の世界']:5.2f} "
              f"平均 {r['π加重の平均の年率']:5.2f} ぶれ {r['ぶれ']:5.1f} 下落 {r['最大下落']:6.1f} 過去20年15%以上 {r['過去の転がる20年で15%以上']:5.1f}")
    for cj, d in diffs.items():
        for fn, x in d.items():
            dd_ = x['主']
            U.log(f"{cj:<12} {fn:<14} 主 Δ平均{dd_['平均']:+.3f} Δ最悪{dd_['最悪']:+.3f} Δ確率{dd_['確率']:+.2f} Δぶれ{dd_['ぶれ']:+.2f} "
                  f"Δ5%未満{dd_['5%未満']:+.2f} Δ下落{dd_['最大下落']:+.2f}")


if __name__ == '__main__':
    main()
