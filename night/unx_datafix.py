#!/usr/bin/env python3
"""night/unx_datafix.py — 事前登録 out/unexplored_prereg.json（6f534c92）の G2・G3（データの直しの候補を名指しする）

読むだけ。リポジトリのどのファイルも書き換えない（書くのは out/unx_datafix.json だけ）。直すかはユーザーに確かめる（事前登録どおり）。

G2（Yahoo の東証の系列）
  (a) 道具の一覧: night/*.py・night/edge/*.py・直下の *.py を走査し、Yahoo の系列を取りに行く道具のうち東証の記号（.T）を使うものと、
      その道具が書く out/*.json を名指しする（静的な走査＋手で確かめた注記）。
  (b) 各銘柄の点検: Yahoo の日次（終値・調整後終値・分配と分割の記録）を、投資信託協会 投信総合検索ライブラリーの基準価額の日次 CSV
      （分配金つき・協会側の口数の単位替えは比で戻す）と突き合わせ、
        ・記録されていない口数の分割（終値が 1/k や k 倍に跳び、協会の基準価額は動かない日）
        ・1〜数日だけの壊れた値（すぐ元の水準へ戻る跳び）
        ・分配金の抜け（協会の分配の日に Yahoo の調整後終値の割り戻しが無い・または小さすぎる）
      を日付つきで出す。協会に無い本（金の信託 1540・外国 ETF 1326・ETN 498A）と株は分割と壊れた値だけを見る（分配は基準が無い＝測れない）。
  (c) ずれの大きさ: 影響を受ける出力ごとに、その出力が使った統計を『Yahoo のまま（道具と同じ作り方）』と『直した系列』の両方で計算し直す。
      直した系列＝Yahoo の終値（壊れた日を外し、記録されていない分割を戻す）に協会の分配金を権利落ちの日（協会の決算日の前の営業日）で再投資。
      照合に協会の基準価額の総リターンも並べる（市場価格と基準価額の差は乖離の分だけ）。
      出力に残っている値（old_stored）・同じ作り方で今計算し直した値（old_recomputed）・直した値（corrected）を並べる。
  (d) 今の門（fetch_dashboard・fetch_returns・fetch_divs ほか）が東証の本を持つ・使うかを portfolio.json・state.json から確かめる。
G3（Yahoo 以外の相手に送る User-Agent のメール）
  直下と night/ の *.py を ast で読み、メールの入った見出し（User-Agent ほか）を作る場所と、それを使って送る相手の名前（ホスト）を名指しする。
  SEC（*.sec.gov）は CLAUDE.md ルール5 で連絡先が要るので別に数える。出力ではメールを <email> に伏せる。

キャッシュ（Yahoo・協会・JPX・French・FRED の取得物）は環境変数 UNX_CACHE（無ければ out/_nx_cache/unx/datafix〔gitignore 済み〕）。
mw_common.get の書き先もここへ向ける（既存の out/_mw_cache は書き換えない）。
月次は 2026-09 まで（事前登録の common.data_cutoff）。各出力の統計はその出力の窓（例: 〜2026-08）で計算し直す。

  python3 night/unx_datafix.py            → out/unx_datafix.json
"""
import ast, csv, datetime, io, json, math, os, re, statistics as S, sys, time, unicodedata, urllib.request, http.cookiejar

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import mw_common as M  # noqa: E402

CACHE = os.environ.get('UNX_CACHE') or os.path.join(BASE, 'out', '_nx_cache', 'unx', 'datafix')
os.makedirs(CACHE, exist_ok=True)
M.CACHE = CACHE          # mw_common.get / yahoo の書き先を自分のキャッシュへ（既存の out/_mw_cache は読みも書きもしない）
OUT = os.path.join(BASE, 'out', 'unx_datafix.json')
PREREG = 'out/unexplored_prereg.json（6f534c92）'
CUT = 202609             # 月次は 2026-09 まで
CUT_D = 20260930
LIB = 'https://toushin-lib.fwg.ne.jp'
YH = 'https://query1.finance.yahoo.com/v8/finance/chart/'
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
NICE = (2, 3, 4, 5, 8, 10, 16, 20, 25, 50, 100, 200, 500, 1000)
JUMP = math.log(1.6)     # 1日でこれより大きく動いたら跳びとして調べる（etf_jp.repair の 0.62/1.6 と同じ幅）

# ─────────────────────────── 東証の ETF → 協会の ISIN・協会コード ───────────────────────────
# JPX の ETF 一覧（https://www.jpx.co.jp/equities/products/etfs/issues/01.html・2026-10-14）の銘柄名と、
# 投信総合検索ライブラリーの全件（基準日 2026-10-09）の fundNm を NFKC で正規化して突き合わせた（2026-10-14）。
# 協会に無い本（信託・外国 ETF・ETN）は None。
TSE = {
    '1305': ('JP3027620008', '04315017', 'iFreeETF TOPIX（年1回決算型）'),
    '1306': ('JP3027630007', '01312017', 'NEXT FUNDS TOPIX連動型上場投信'),
    '1308': ('JP3039100007', '0231701C', '上場インデックスファンドTOPIX'),
    '1321': ('JP3027650005', '01311017', 'NEXT FUNDS 日経225連動型上場投信'),
    '1348': ('JP3047060003', '03311095', 'MAXIS トピックス上場投信'),
    '1399': ('JP3048170009', '0231415B', '上場インデックスファンドMSCI日本株高配当低ボラティリティ'),
    '1478': ('JP3048150001', '4831415A', 'iシェアーズ MSCI ジャパン高配当利回り ETF'),
    '1489': ('JP3048390003', '01314172', 'NEXT FUNDS 日経平均高配当株50指数連動型上場投信'),
    '1494': ('JP3048440006', '47313175', 'One ETF 高配当日本株'),
    '1545': ('JP3047240001', '01313108', 'NEXT FUNDS NASDAQ-100（為替ヘッジなし）連動型上場投信'),
    '1577': ('JP3047560002', '01313133', 'NEXT FUNDS 野村日本株高配当70連動型上場投信'),
    '1617': ('JP3046560003', '01315083', 'NEXT FUNDS 食品(TOPIX-17)'),
    '1618': ('JP3046570002', '01316083', 'NEXT FUNDS エネルギー資源(TOPIX-17)'),
    '1619': ('JP3046580001', '01317083', 'NEXT FUNDS 建設・資材(TOPIX-17)'),
    '1620': ('JP3046590000', '01318083', 'NEXT FUNDS 素材・化学(TOPIX-17)'),
    '1621': ('JP3046600007', '01319083', 'NEXT FUNDS 医薬品(TOPIX-17)'),
    '1622': ('JP3046610006', '0131A083', 'NEXT FUNDS 自動車・輸送機(TOPIX-17)'),
    '1623': ('JP3046620005', '0131B083', 'NEXT FUNDS 鉄鋼・非鉄(TOPIX-17)'),
    '1624': ('JP3046630004', '0131C083', 'NEXT FUNDS 機械(TOPIX-17)'),
    '1625': ('JP3046640003', '0131D083', 'NEXT FUNDS 電機・精密(TOPIX-17)'),
    '1626': ('JP3046650002', '0131E083', 'NEXT FUNDS 情報通信・サービスその他(TOPIX-17)'),
    '1627': ('JP3046660001', '0131F083', 'NEXT FUNDS 電力・ガス(TOPIX-17)'),
    '1628': ('JP3046670000', '0131G083', 'NEXT FUNDS 運輸・物流(TOPIX-17)'),
    '1629': ('JP3046680009', '0131H083', 'NEXT FUNDS 商社・卸売(TOPIX-17)'),
    '1630': ('JP3046690008', '0131I083', 'NEXT FUNDS 小売(TOPIX-17)'),
    '1631': ('JP3046700005', '0131J083', 'NEXT FUNDS 銀行(TOPIX-17)'),
    '1632': ('JP3046710004', '0131K083', 'NEXT FUNDS 金融(除く銀行)(TOPIX-17)'),
    '1633': ('JP3046720003', '0131L083', 'NEXT FUNDS 不動産(TOPIX-17)'),
    '1651': ('JP3048490001', '04316179', 'iFreeETF TOPIX高配当40指数'),
    '1698': ('JP3047170000', '02311105', '上場インデックスファンド日本高配当（東証配当フォーカス100）'),
    '200A': ('JP3050420003', '01311246', 'NEXT FUNDS 日経半導体株指数連動型上場投信'),
    '2243': ('JP3049860004', 'B5311234', 'グローバルX 半導体 ETF'),
    '2529': ('JP3048890002', '01312194', 'NEXT FUNDS 野村株主還元70連動型上場投信'),
    '2558': ('JP3048980001', '03312201', 'MAXIS米国株式（S&P500）上場投信'),
    '2559': ('JP3048990000', '03313201', 'MAXIS全世界株式（オール・カントリー）上場投信'),
    '2564': ('JP3049050002', 'B5311208', 'グローバルX MSCIスーパーディビィデンド-日本株式 ETF'),
    '2621': ('JP3049130002', '4831220A', 'iシェアーズ 米国債20年超 ETF（為替ヘッジあり）'),
    '2631': ('JP3049190006', '03314212', 'MAXISナスダック100上場投信'),
    '2632': ('JP3049200003', '03315212', 'MAXISナスダック100上場投信（為替ヘッジあり）'),
    '2639': ('JP3049310000', 'B5312216', 'グローバルX バイオ&メドテック-日本株式 ETF'),
    '2644': ('JP3049360005', 'B5311219', 'グローバルX 半導体関連-日本株式 ETF'),
    '2840': ('JP3049460003', '04314221', 'iFreeETF NASDAQ100（為替ヘッジなし）'),
    '2841': ('JP3049470002', '04313221', 'iFreeETF NASDAQ100（為替ヘッジあり）'),
    '466A': ('JP3051070005', 'B531225B', 'グローバルX 防衛テック ETF'),
    '513A': ('JP3051240004', 'B5312262', 'グローバルX 防衛テック-日本株式 ETF'),
    '610A': ('JP3051650004', 'B5312267', 'グローバルX 宇宙テック・トップ10 ETF（除く日本）'),
    '1540': (None, None, '純金上場信託（現物国内保管型）＝信託（協会に無い・分配なし）'),
    '1326': (None, None, 'SPDR ゴールド・シェア＝外国 ETF（協会に無い・分配なし）'),
    '498A': (None, None, '欧州防衛・航空 ETN（協会に無い・ETN＝分配なし）'),
}
# 道具が使う東証の株（分割と壊れた値だけを見る）
STOCKS = {
    'etf_jp の検算（REF）': ['8035', '6857', '6146', '6920', '4063'],
    'nx_brand_data の日本のブランド（nx_brand・nx_forward が値段を引く）': ['7751', '7267', '7203', '7974', '7201', '6752', '6758', '7270', '9983'],
}
SCOUT_CODES = ['1545', '2840', '2841', '1306', '1348', '2558', '2559', '2631', '2632', '2243', '2644', '1540', '1326', '2621', '466A', '513A']

YAHOO_HELPERS = {  # 東証の記号を Yahoo へ渡す入口（関数・道具の中の取得）
    'mw_common.yahoo': '月次・日次の調整後終値（月は取引所の現地時刻・2026-09-28 から）',
    'etf_jp.fetch': '月次の調整後終値（YYYY-MM・gmtoffset）＋ etf_jp.repair（月次の比 0.62/1.6 で整数比の分割を戻す）',
    'mw_jp_nisa_bridge.yahoo_local': 'mw_common.yahoo と同じ URL を現地の月で切る',
    'fetch_returns.yahoo': '日次の調整後終値（保有の成績）',
    'fetch_dashboard.yahoo_quotes': '今日の値段と前日の値段（系列ではない）',
    'fetch_divs.fetch': '直近2年の月次の分配（表示だけ）',
    'mw_forward.yh_daily': '日次の調整後終値（前向きの検定の城の日本株）',
    'castle_correlation.fetch': '城の相関（日次→月次）',
}


# ═══════════════════════════════ 取得 ═══════════════════════════════
def yh_raw(sym, interval):
    """mw_common.yahoo と同じ URL・同じキャッシュ名（書き先は自分のキャッシュ）→ chart の result"""
    import urllib.parse
    u = f'{YH}{urllib.parse.quote(sym)}?period1=0&period2={int(time.time())}&interval={interval}&events=div%2Csplit'
    name = f'yh_{sym.replace("^", "IDX_").replace("=", "_")}_{interval}.json'
    p = os.path.join(CACHE, name)
    fresh = os.path.exists(p) and time.time() - os.path.getmtime(p) < 3 * 86400
    b = M.get(u, name=name, max_age_days=3)
    if not fresh:
        time.sleep(0.4)
    j = json.loads(b)
    res = (j.get('chart') or {}).get('result')
    return res[0] if res else None


def yh_monthly_as_used(sym):
    """mw_common.yahoo（今の作り方＝現地の月）をそのまま。2026-09 まで"""
    yh_raw(sym, '1mo')   # キャッシュを作る（同じ名前を M.yahoo が読む）
    return {k: v for k, v in M.yahoo(sym).items() if k <= CUT}


def yh_monthly_levels_etfjp(sym):
    """etf_jp.fetch と同じ読み方（月足の調整後終値・gmtoffset・YYYY-MM）。px_guard は通さない（台帳を書かないため）"""
    r = yh_raw(sym, '1mo')
    if not r:
        return {}
    ind = r['indicators']
    ser = (ind.get('adjclose') or [{}])[0].get('adjclose') or ind['quote'][0]['close']
    gmt = (r.get('meta') or {}).get('gmtoffset') or 0
    o = {}
    for t, v in zip(r['timestamp'], ser):
        if v is None:
            continue
        d = datetime.datetime.utcfromtimestamp(t + gmt)
        o[f'{d.year:04d}-{d.month:02d}'] = float(v)
    now = datetime.datetime.utcfromtimestamp(time.time() + gmt)
    return {k: v for k, v in o.items() if int(k[:4]) * 100 + int(k[5:]) < now.year * 100 + now.month}


def yh_daily(sym):
    """日次 → rows [(yyyymmdd, close, adjclose)]・divs {yyyymmdd: amount}・splits [(yyyymmdd, '分子:分母')]"""
    r = yh_raw(sym, '1d')
    if not r or not r.get('timestamp'):
        return None
    off = (r.get('meta') or {}).get('gmtoffset') or 0
    q = r['indicators']['quote'][0]
    adj = (r['indicators'].get('adjclose') or [{}])[0].get('adjclose') or q['close']
    rows = []
    for t, c, a in zip(r['timestamp'], q['close'], adj):
        if c is None or a is None or c <= 0 or a <= 0:
            continue
        d = int(datetime.datetime.utcfromtimestamp(t + off).strftime('%Y%m%d'))
        if rows and rows[-1][0] == d:
            rows[-1] = (d, c, a)
        else:
            rows.append((d, c, a))
    ev = r.get('events') or {}
    divs, splits = {}, []
    for k, v in (ev.get('dividends') or {}).items():
        divs[int(datetime.datetime.utcfromtimestamp(int(v.get('date', k)) + off).strftime('%Y%m%d'))] = v.get('amount')
    for k, v in (ev.get('splits') or {}).items():
        splits.append((int(datetime.datetime.utcfromtimestamp(int(v.get('date', k)) + off).strftime('%Y%m%d')), v.get('splitRatio')))
    return {'rows': rows, 'divs': divs, 'splits': sorted(splits), 'meta': {'currency': (r.get('meta') or {}).get('currency'),
                                                                        'firstTradeDate': (r.get('meta') or {}).get('firstTradeDate')}}


class JitaLib:
    """投信総合検索ライブラリー（nx_jpfunds_data.Lib と同じ作法。User-Agent は mw_common.UA＝連絡先のメールを載せない）"""
    def __init__(self):
        self.op = None

    def csv(self, isin, assoc):
        p = os.path.join(CACHE, f'jita_{assoc}.csv')
        if os.path.exists(p) and time.time() - os.path.getmtime(p) < 7 * 86400 and os.path.getsize(p) > 0:
            return open(p, 'rb').read()
        if self.op is None:
            self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            self.op.addheaders = [('User-Agent', M.UA['User-Agent'])]
            self.op.open(LIB + '/FdsWeb/FDST000000', timeout=60).read()
        err = None
        for i in range(4):
            try:
                b = self.op.open(f'{LIB}/FdsWeb/FDST030000/csv-file-download?isinCd={isin}&associFundCd={assoc}', timeout=120).read()
                open(p + '.tmp', 'wb').write(b)
                os.replace(p + '.tmp', p)
                time.sleep(0.5)
                return b
            except Exception as e:  # noqa
                err = e
                time.sleep(2 ** (i + 1))
        raise RuntimeError(f'協会の CSV が取れない {assoc}: {err}')


JL = JitaLib()


def jita_daily(isin, assoc):
    """協会の CSV → [(yyyymmdd, 基準価額, 分配金)]・協会側の口数の単位替え（1日で整数比に跳ぶ）は比で戻す。単位替えの日も返す"""
    t = JL.csv(isin, assoc).decode('cp932', errors='replace').splitlines()
    if not t or '年月日' not in t[0] or '基準価額' not in t[0]:
        raise RuntimeError(f'協会の CSV の見出しが想定と違う: {t[:1]}')
    raw = []
    for line in t[1:]:
        x = line.split(',')
        m = re.match(r'(\d{4})年(\d{2})月(\d{2})日', x[0].strip())
        if not m:
            continue
        try:
            nav = float(x[1])
        except ValueError:
            continue
        dv = 0.0
        if len(x) > 3 and x[3].strip():
            try:
                dv = float(x[3])
            except ValueError:
                dv = 0.0
        raw.append((int(m.group(1) + m.group(2) + m.group(3)), nav, dv))
    raw.sort()
    adj, out, units, odd = 1.0, [], [], []
    for i, (d, nav, dv) in enumerate(raw):
        if i:
            q = nav / raw[i - 1][1]
            if abs(math.log(q)) > JUMP:
                k = min(NICE, key=lambda z: min(abs(math.log(q * z)), abs(math.log(q / z))))
                if abs(math.log(q / k)) < 0.05:
                    adj /= k; units.append({'date': d, 'ratio': round(q, 4), 'as': f'協会の基準価額が {k} 倍（単位替え）'})
                elif abs(math.log(q * k)) < 0.05:
                    adj *= k; units.append({'date': d, 'ratio': round(q, 4), 'as': f'協会の基準価額が 1/{k}（単位替え）'})
                else:
                    odd.append({'date': d, 'ratio': round(q, 4)})
        out.append((d, nav * adj, dv * adj))
    return out, units, odd


# ═══════════════════════════════ 点検（1銘柄） ═══════════════════════════════
def ymd(d):
    return datetime.date(d // 10000, d // 100 % 100, d % 100)


def month_end_levels(daily):
    """[(d, level)] → {yyyymm: 月末の level}（CUT まで）"""
    me = {}
    for d, v in daily:
        if d // 100 <= CUT:
            me[d // 100] = v
    return me


def rets_from_levels(me):
    ks = sorted(me)
    return {k: me[k] / me[p] - 1 for p, k in zip(ks, ks[1:]) if M_add(p, 1) == k}


def M_add(m, k):
    y, mo = divmod(m, 100)
    t = y * 12 + mo - 1 + k
    return (t // 12) * 100 + t % 12 + 1


def check_instrument(code, kind='etf'):
    """Yahoo の日次を協会の基準価額と突き合わせる。戻り値の 'corr_daily' は直した総リターン（日次の水準）"""
    sym = f'{code}.T'
    out = {'code': code, 'symbol': sym}
    yd = yh_daily(sym)
    if not yd or len(yd['rows']) < 30:
        out['error'] = 'Yahoo の日次が取れない（測れない）'
        return out, None
    rows = yd['rows']
    out['yahoo'] = {'from': rows[0][0], 'to': rows[-1][0], 'days': len(rows), 'split_events': yd['splits'],
                    'div_events': len(yd['divs'])}
    isin, assoc, nm = TSE.get(code, (None, None, None))
    out['name'] = nm
    jit, jl, units, odd = None, None, [], []
    if isin:
        try:
            jit, units, odd = jita_daily(isin, assoc)
        except Exception as e:  # noqa
            out['jita_error'] = str(e)[:200]
        if jit:
            jl, x = {jit[0][0]: 1.0}, 1.0
            for (a, n0, _), (b, n1, v1) in zip(jit, jit[1:]):
                x *= (n1 + v1) / n0
                jl[b] = x
            out['jita'] = {'isin': isin, 'assoc': assoc, 'from': jit[0][0], 'to': jit[-1][0], 'days': len(jit),
                           'distributions': sum(1 for r in jit if r[2] > 0), 'unit_changes_undone': units, 'unexplained_jumps': odd}
    jdates = sorted(jl) if jl else []

    def jlevel_at(d):
        """協会の総リターンの水準（d 以前の最後の日）"""
        import bisect
        i = bisect.bisect_right(jdates, d)
        return jl[jdates[i - 1]] if i else None

    # (1) 壊れた値（跳んで5営業日以内に元の水準の ±15% へ戻る）
    closes = [c for _, c, _ in rows]
    bad = set()
    i = 1
    while i < len(rows):
        if i - 1 in bad:
            i += 1; continue
        prev_i = max(j for j in range(i) if j not in bad)
        q = closes[i] / closes[prev_i]
        if abs(math.log(q)) > JUMP:
            back = None
            for j in range(i + 1, min(i + 6, len(rows))):
                if abs(math.log(closes[j] / closes[prev_i])) < math.log(1.15):
                    back = j; break
            if back is not None:
                for j in range(i, back):
                    bad.add(j)
                i = back; continue
        i += 1
    glitches = [{'date': rows[j][0], 'close': rows[j][1], 'prev_close': rows[max(k for k in range(j) if k not in bad)][1]} for j in sorted(bad)]
    good = [r for j, r in enumerate(rows) if j not in bad]
    # (2) 記録されていない分割（整数比に近い跳び・協会の基準価額は動かない）
    unrec, unexplained = [], []
    fac = [1.0] * len(good)
    f = 1.0
    for n in range(len(good) - 1, 0, -1):
        (d0, c0, a0), (d1, c1, a1) = good[n - 1], good[n]
        q = c1 / c0
        if abs(math.log(q)) > JUMP:
            k = min(NICE, key=lambda z: min(abs(math.log(q * z)), abs(math.log(q / z))))
            rec = [s for s in yd['splits'] if abs((ymd(s[0]) - ymd(d1)).days) <= 3]
            jr = None
            if jl:
                a, b = jlevel_at(d0), jlevel_at(d1)
                jr = round(b / a, 4) if a and b else None
            item = {'date': d1, 'prev_date': d0, 'close_ratio': round(q, 4), 'adjclose_ratio': round(a1 / a0, 4),
                    'yahoo_split_event_near': rec, 'jita_tr_ratio_same_days': jr}
            if abs(math.log(q * k)) < 0.12:
                item['as'] = f'1:{k}（口数の分割）'
                f /= k
            elif abs(math.log(q / k)) < 0.12:
                item['as'] = f'{k}:1（口数の併合）'
                f *= k
            else:
                item['as'] = '整数比でない（本物の値動きか壊れた値）＝直さない'
                unexplained.append(item)
                fac[n - 1] = f
                continue
            item['adjclose_also_jumps'] = abs(math.log((a1 / a0) / q)) < 0.05
            item['jita_confirms_no_move'] = (jr is not None and 0.8 < jr < 1.25)
            unrec.append(item)
        fac[n - 1] = f
    price = [(d, c * fac[n]) for n, (d, c, a) in enumerate(good)]
    # (3) 分配: 協会の分配を権利落ちの日（決算日の前の Yahoo の営業日）で再投資。Yahoo の割り戻しと突き合わせる
    ratio = {d: a / c for d, c, a in good}      # 調整後終値 ÷ 終値（分配の割り戻しのときだけ変わる）
    gd = [d for d, _, _ in good]
    import bisect
    dist_audit, reinv = [], {}
    if jit:
        for d, nav, dv in jit:
            if dv <= 0 or d < gd[0] or d > gd[-1] + 5:
                continue
            y_j = dv / nav
            i = bisect.bisect_left(gd, d) - 1       # 決算日より前の最後の Yahoo の日＝権利落ちの日（近似）
            if i < 1:
                continue
            ex = gd[i]
            reinv[ex] = reinv.get(ex, 1.0) * (1 + y_j)
            # Yahoo の割り戻し: 決算日の10日前〜3日後の窓の前後で 調整後÷終値 の比がどれだけ変わったか
            lo = bisect.bisect_left(gd, int((ymd(d) - datetime.timedelta(days=12)).strftime('%Y%m%d'))) - 1
            hi = bisect.bisect_right(gd, int((ymd(d) + datetime.timedelta(days=3)).strftime('%Y%m%d'))) - 1
            # 割り戻しの前は 調整後÷終値 が m＝(1−分配÷前日の終値) 倍に縮む → 後÷前 − 1 ＝ 1/m − 1 ≈ 分配の利回り
            y_y = ratio[gd[hi]] / ratio[gd[max(lo, 0)]] - 1 if hi > max(lo, 0) else None
            ev = [(k, v) for k, v in yd['divs'].items() if -12 <= (ymd(k) - ymd(d)).days <= 3]
            amt = ev[0][1] if ev else None
            # Yahoo の金額を Yahoo のその日の終値で割った利回り（金額だけ縮んでいる＝分割の倍率で割られている を見る）
            y_amt = (amt / dict((dd, cc) for dd, cc, _ in good).get(gd[i], float('nan'))) if amt is not None else None
            st = 'ok' if (y_y is not None and abs(y_y - y_j) <= max(0.3 * y_j, 0.0005)) else \
                 ('missing' if (y_y is None or y_y < 0.1 * y_j) else ('too_small' if y_y < y_j else 'too_large'))
            # 0.1 倍未満＝抜け・0.1〜0.7 倍＝小さすぎ（例: 分割の倍率で割られた金額）・1.3 倍超＝大きすぎ（例: 桁違いの金額）
            dist_audit.append({'date': d, 'ex_date_used': ex, 'jita_yield_pct': round(100 * y_j, 3),
                               'yahoo_adj_yield_pct': None if y_y is None else round(100 * y_y, 3),
                               'yahoo_event': None if amt is None else {'date': ev[0][0], 'amount': amt,
                                                                         'amount_over_close_pct': None if (y_amt is None or y_amt != y_amt) else round(100 * y_amt, 4)},
                               'status': st})
    tr, lvl = [], 1.0
    for n, (d, p) in enumerate(price):
        if n:
            lvl *= p / price[n - 1][1] * reinv.get(d, 1.0)
        tr.append((d, lvl))
    # 年ごとの分配の取りこぼし
    by_y = {}
    for a in dist_audit:
        y = a['date'] // 10000
        b = by_y.setdefault(y, [0.0, 0.0, 0])
        b[0] += a['jita_yield_pct']; b[1] += (a['yahoo_adj_yield_pct'] or 0.0); b[2] += 1
    out['glitch_days'] = glitches
    out['unrecorded_splits'] = unrec
    out['unexplained_jumps_kept'] = unexplained
    out['distributions'] = {
        'n_jita': len(dist_audit), 'status_counts': {s: sum(1 for a in dist_audit if a['status'] == s) for s in ('ok', 'too_small', 'missing', 'too_large')},
        'yearly_pct': {str(y): {'jita': round(v[0], 3), 'yahoo_adj': round(v[1], 3), 'missed': round(v[0] - v[1], 3)} for y, v in sorted(by_y.items())},
        'events': dist_audit} if jit else '協会に無い本・分配の基準が無い（測れない）'
    # 月次の比べ
    used = {}
    try:
        used = yh_monthly_as_used(sym)
    except Exception as e:  # noqa
        out['yahoo_monthly_error'] = str(e)[:150]
    corr_m = rets_from_levels(month_end_levels(tr))
    jit_m = rets_from_levels(month_end_levels(sorted(jl.items()))) if jl else {}
    ks = sorted(set(used) & set(corr_m))
    if ks:
        dif = {k: used[k] - corr_m[k] for k in ks}
        big = sorted(((k, v) for k, v in dif.items() if abs(v) > 0.02), key=lambda x: -abs(x[1]))

        def cg(r, kk):
            g = 1.0
            for k in kk:
                g *= 1 + r[k]
            return g ** (12 / len(kk)) - 1 if kk else None
        ks_j = [k for k in ks if k in jit_m]
        out['monthly'] = {
            'window': f'{ks[0]}〜{ks[-1]}（{len(ks)}か月）',
            'cagr_yahoo_as_used_pct': round(100 * cg(used, ks), 2), 'cagr_corrected_pct': round(100 * cg(corr_m, ks), 2),
            'cagr_gap_pt': round(100 * (cg(used, ks) - cg(corr_m, ks)), 2),
            'mean_gap_pt_per_yr': round(1200 * S.mean(dif.values()), 2),
            'jita_nav_check': None if len(ks_j) < 12 else {
                'window': f'{ks_j[0]}〜{ks_j[-1]}（{len(ks_j)}か月）', 'cagr_corrected_pct': round(100 * cg(corr_m, ks_j), 2),
                'cagr_jita_nav_tr_pct': round(100 * cg(jit_m, ks_j), 2),
                'gap_corrected_minus_nav_pt': round(100 * (cg(corr_m, ks_j) - cg(jit_m, ks_j)), 2),
                'monthly_corr': round(M.corr([corr_m[k] for k in ks_j], [jit_m[k] for k in ks_j]), 4)},
            'months_gap_gt_2pct': [{'month': k, 'yahoo_as_used_pct': round(100 * used[k], 2), 'corrected_pct': round(100 * corr_m[k], 2),
                                    'gap_pt': round(100 * v, 2)} for k, v in big[:15]],
            'n_months_gap_gt_2pct': len(big)}
    sc = out['distributions']['status_counts'] if isinstance(out['distributions'], dict) else {}
    affected = bool(unrec or glitches or sc.get('missing') or sc.get('too_small') or sc.get('too_large'))
    out['affected'] = affected
    return out, {'corr_m': corr_m, 'used_m': used, 'jit_m': jit_m, 'tr': tr}


def check_stock(code):
    """株: Yahoo が記録していない分割（終値の整数比の跳び）と壊れた値だけ"""
    yd = yh_daily(f'{code}.T')
    if not yd:
        return {'code': code, 'error': 'Yahoo の日次が取れない'}
    rows = yd['rows']
    jumps = []
    for (d0, c0, a0), (d1, c1, a1) in zip(rows, rows[1:]):
        q = c1 / c0
        if abs(math.log(q)) > JUMP:
            rec = [s for s in yd['splits'] if abs((ymd(s[0]) - ymd(d1)).days) <= 3]
            jumps.append({'date': d1, 'close_ratio': round(q, 4), 'adjclose_ratio': round(a1 / a0, 4), 'yahoo_split_event_near': rec})
    return {'code': code, 'from': rows[0][0], 'to': rows[-1][0], 'split_events': yd['splits'],
            'close_jumps_gt_60pct': jumps, 'affected': bool(jumps),
            'note': '株の分割は Yahoo が記録して終値・調整後終値ともさかのぼって直す（記録があれば跳びは出ない）。分配の基準は無い＝分配は見ていない'}


# ═══════════════════════════════ (a) 道具の一覧（静的） ═══════════════════════════════
def py_files():
    fs = [os.path.join(BASE, f) for f in sorted(os.listdir(BASE)) if f.endswith('.py')]
    for root, _, files in os.walk(os.path.join(BASE, 'night')):
        if '_cache' in root or '__pycache__' in root:
            continue
        fs += [os.path.join(root, f) for f in sorted(files) if f.endswith('.py')]
    return fs


def inventory():
    rx_t = re.compile(r"""['"]([0-9]{3}[0-9A-Z])\.T['"]|['"]\.T['"]|\{[^}]*\}\.T['"]""")
    rx_yh = re.compile(r'finance\.yahoo\.com|\bM\.yahoo\(|\bMC\.yahoo\(|mw_common\.yahoo|yahoo_local\(|\byh\(|\bfr\.yahoo\(|\byahoo\(|yahoo_quotes\(|yh_daily\(|\bfetch\(')
    rx_out = re.compile(r"out/[A-Za-z0-9_./{}-]+\.json|['\"]([a-z0-9_]+\.json)['\"]")
    rows = []
    for p in py_files():
        if os.path.basename(p) == 'unx_datafix.py':
            continue
        s = open(p, encoding='utf-8', errors='replace').read()
        if not rx_t.search(s):
            continue
        codes = sorted(set(m.group(1) for m in rx_t.finditer(s) if m.group(1)))
        dyn = bool(re.search(r"""\+\s*['"]\.T['"]|\}\.T['"]""", s))
        guards = [g for g, pat in (('分割の修理（etf_jp.repair）', r'repair\('), ('±40%/50% 超の月を外す', r'abs\(v\)\s*[<>]=?\s*0\.[45]|> ?0\.4\b|v < -0\.4'),
                                   ('器−市場 >8% の月を外す', r'> ?0\.08'), ('跳びを記録だけ（外さない）', r'YJUMPS'),
                                   ('px_guard（短い応答を採らない）', r'PXG\.vet'), ('協会の基準価額で照合', r'csv-file-download|jita_|ita_monthly|fund_series'))
                  if re.search(pat, s)]
        outs = sorted(set((m.group(0) if m.group(0).startswith('out/') else m.group(1)) for m in rx_out.finditer(s)))
        rows.append({'file': os.path.relpath(p, BASE), 'tse_codes_literal': codes, 'builds_dot_T_dynamically': dyn,
                     'yahoo_fetch_seen': bool(rx_yh.search(s)), 'guards_found': guards, 'json_paths_named': outs[:30]})
    return rows


# 手で確かめた注記（静的な走査が拾った各道具を読んで、何を Yahoo の東証の系列から作るか）
TOOL_NOTES = {
    'night/etf_jp.py': {'series': '2644・200A・2243・1625・1321・1305（ETF）＋検算の株5社', 'helper': 'etf_jp.fetch＋repair', 'outputs': ['out/etf_jp.json'],
                        'uses': '円建ての年率・最大下落（rows[].jpy）と米国 ETF との差'},
    'night/etf_jp_defense.py': {'series': '466A・513A・498A・610A', 'helper': 'etf_jp.fetch＋repair', 'outputs': ['out/etf_jp_defense.json'],
                                'uses': '上場来の円建ての累積（候補[].円建て.累積）'},
    'night/alt_etf_compare.py': {'series': '466A・513A・1621・2639', 'helper': 'mw_common.yahoo', 'outputs': ['out/alt_etf_compare.json'],
                                 'uses': '共通の窓の年率・ぶれ・最大下落・替えた形の年率'},
    'night/defense_alts.py': {'series': '466A・513A', 'helper': 'mw_common.yahoo', 'outputs': ['out/defense_alts.json'],
                              'uses': "A' 円建ての短い記録（累積・最大下落）"},
    'night/mw_japan.py': {'series': '高配当 ETF 9本（1489・1577・1698・2529・1478・1399・1651・1494・2564）・相手 1305（照合 1348・1306）', 'helper': 'mw_common.yahoo',
                          'outputs': ['out/mw_japan.json'], 'uses': 'E5（報告のみ）: 1305 との超過の年率'},
    'night/mw_jp_nisa_bridge.py': {'series': '同じ高配当 ETF 9本', 'helper': 'mw_jp_nisa_bridge.yahoo_local（跳びは記録だけ）', 'outputs': ['out/mw_jp_nisa_bridge.json'],
                                   'uses': 'P2 の器: MSCI Japan（円・gross）との超過・紙の上乗せの載り（capture）。mw_holdable_breakeven が 1489 の載りと追従のぶれを入力に使う'},
    'night/mw_industry.py': {'series': 'TOPIX-17 業種別 ETF 1617〜1633・相手 1308', 'helper': 'mw_common.yahoo（|月次|>50% を外す）', 'outputs': ['out/mw_industry.json'],
                             'uses': 'prereg5 の J1・J2・J3（業種の勢い）の超過'},
    'night/mw_holdable_breakeven.py': {'series': '1306（JMKT の器）・1489（入力は mw_jp_nisa_bridge.json から）', 'helper': 'mw_common.yahoo（器−市場 >8% の月を外す）',
                                       'outputs': ['out/mw_holdable_breakeven.json'], 'uses': 'fits.JMKT（1306 − French の日本〔円〕のずれの平均・ぶれ）→ 袖 JMKT の雑音'},
    'night/bestfund_data.py': {'series': '1306・1321 は記号だけで、値は協会の基準価額（jita_nav）', 'helper': 'Yahoo ではない', 'outputs': ['out/bestfund.json ほか'],
                               'uses': '影響なし（Yahoo の東証の系列を使っていない）'},
    'night/fetch_dashboard.py': {'series': '監視リストの日本株（今日の値段と前日の値段）', 'helper': 'fetch_dashboard.yahoo_quotes', 'outputs': ['out/dashboard.json'],
                                 'uses': '盤の株価（系列ではない・分割の日の前日比だけがずれうる）'},
    'night/fetch_divs.py': {'series': '盤の値段のある日本株の直近2年の分配', 'helper': 'fetch_divs.fetch', 'outputs': ['out/holdings_div.json'], 'uses': '銘柄の詳細の配当利回り（表示だけ）'},
    'night/fetch_returns.py': {'series': '保有の日本株（数字のコード）があれば', 'helper': 'fetch_returns.yahoo', 'outputs': ['out/returns.json'], 'uses': '成績'},
    'night/estimate_bd.py': {'series': '保有の日本株があれば', 'helper': 'fetch_returns.yahoo', 'outputs': ['state.json（--write のとき）'], 'uses': '買付日の推定'},
    'night/castle_correlation.py': {'series': '席・門外例外の日本株があれば', 'helper': '道具の中の取得', 'outputs': ['out/castle_correlation.json'], 'uses': '城の相関'},
    'night/mw_forward.py': {'series': '城の日本株があれば', 'helper': 'mw_forward.yh_daily', 'outputs': ['out/mw_forward.json'], 'uses': '前向きの検定'},
    'night/fetch_logos.py': {'series': '日本株のロゴ', 'helper': '値段ではない', 'outputs': ['out/logos/index.json'], 'uses': '影響なし'},
    'night/nx_brand_data.py': {'series': '日本のブランド9社（株）', 'helper': '記号の表（値段は nx_brand.py・nx_forward.py が引く）', 'outputs': ['out/nx_brand.json・out/nx_forward.json'],
                               'uses': 'ブランドの組（日本の社は株＝分割の点検だけ）'},
}


# ═══════════════════════════════ (c) ずれの大きさ ═══════════════════════════════
def cagr_of(r, ks):
    g = 1.0
    for k in ks:
        g *= 1 + r[k]
    return g ** (12 / len(ks)) - 1


def mdd_of(r, ks):
    g = pk = 1.0
    dd = 0.0
    for k in ks:
        g *= 1 + r[k]; pk = max(pk, g); dd = min(dd, g / pk - 1)
    return dd


def ym_key(k):  # 'YYYY-MM' → yyyymm
    return int(k[:4]) * 100 + int(k[5:7])


def r2(x, n=2):
    return None if x is None else round(x, n)


def impact_etf_jp(DATA):
    import etf_jp as EJ
    d = json.load(open(os.path.join(BASE, 'out', 'etf_jp.json')))
    res = []
    for row in d['rows']:
        t = row['t']; code = t[:-2]
        if code not in DATA or not row.get('jpy'):
            continue
        lv = yh_monthly_levels_etfjp(t)
        fixed, found = EJ.repair(lv)
        a, b = row['first'], '2026-08'
        old = EJ.st(fixed, a, b)
        cm = DATA[code]['corr_m']
        me = {}
        lvl = 1.0
        ks = sorted(k for k in cm if ym_key(a) < k <= ym_key(b))
        for k in ks:
            lvl *= 1 + cm[k]; me[k] = lvl
        me[ym_key(a)] = 1.0
        kk = sorted(me)
        ks_r = [k for k in kk[1:]]
        corr = {'cagr': cagr_of({k: me[k] / me[p] - 1 for p, k in zip(kk, kk[1:])}, ks_r) if ks_r else None,
                'maxdd': mdd_of({k: me[k] / me[p] - 1 for p, k in zip(kk, kk[1:])}, ks_r) if ks_r else None}
        res.append({'file': 'out/etf_jp.json', 'key': f'rows[{t}].jpy', 'window': f'{a}〜{b}',
                    'old_stored': {'cagr_pct': r2(100 * row['jpy']['cagr']), 'maxdd_pct': r2(100 * row['jpy']['maxdd'])},
                    'old_recomputed': None if not old else {'cagr_pct': r2(100 * old['cagr']), 'maxdd_pct': r2(100 * old['maxdd']),
                                                            'repair_found': found},
                    'corrected': {'cagr_pct': r2(100 * corr['cagr']) if corr['cagr'] is not None else None,
                                  'maxdd_pct': r2(100 * corr['maxdd']) if corr['maxdd'] is not None else None},
                    'delta_cagr_pt_vs_recomputed': None if not old or corr['cagr'] is None else r2(100 * (corr['cagr'] - old['cagr'])),
                    'note': 'rows[].vs[].diff_jpy_pt・diff_fxneutral_pt（米国 ETF との差）は同じ幅だけ動く'})
    return res


def impact_etf_jp_defense(DATA):
    import etf_jp as EJ
    p = os.path.join(BASE, 'out', 'etf_jp_defense.json')
    d = json.load(open(p))
    res = []
    for t, row in (d.get('候補') or {}).items():
        code = t[:-2]
        jp = row.get('円建て')
        if not jp or code not in DATA:
            continue
        a, b = jp['窓'].split('→')
        lv = yh_monthly_levels_etfjp(t)
        fixed, found = EJ.repair(lv)
        ks = sorted(k for k in fixed if a <= k <= b)
        old = fixed[ks[-1]] / fixed[ks[0]] - 1 if len(ks) >= 2 else None
        cm = DATA[code]['corr_m']
        kk = [k for k in sorted(cm) if ym_key(a) < k <= ym_key(b)]
        corr = math.prod(1 + cm[k] for k in kk) - 1 if kk else None
        res.append({'file': 'out/etf_jp_defense.json', 'key': f'候補[{t}].円建て.累積', 'window': f'{a}→{b}',
                    'old_stored_pct': r2(100 * jp['累積']), 'old_recomputed_pct': r2(100 * old) if old is not None else None,
                    'corrected_pct': r2(100 * corr) if corr is not None else None,
                    'delta_pt_vs_recomputed': None if old is None or corr is None else r2(100 * (corr - old))})
    return res


def impact_alt_etf(DATA):
    d = json.load(open(os.path.join(BASE, 'out', 'alt_etf_compare.json')))
    fx = M.yahoo('JPY=X')
    SHAPE = {'QQQ': 40, 'SMH': 25, 'ITA': 10, 'XLV': 10}

    def yen_us(t):
        s = M.yahoo(t)
        return {k: (1 + v) * (1 + fx[k]) - 1 for k, v in s.items() if k in fx}
    base = {t: yen_us(t) for t in SHAPE}

    def stats(r, ks):
        g = pk = 1.0; dd = 0.0
        for k in ks:
            g *= 1 + r[k]; pk = max(pk, g); dd = min(dd, g / pk - 1)
        n = len(ks)
        return {'年率': round(100 * (g ** (12 / n) - 1), 1), 'ぶれ': round(100 * S.pstdev([r[k] for k in ks]) * math.sqrt(12), 1), '最大下落': round(100 * dd, 1)}

    def shape(ks, ref, alt):
        tot = sum(SHAPE.values())
        return {k: sum(w * (alt[k] if t == ref else base[t][k]) for t, w in SHAPE.items()) / tot for k in ks}
    res = []
    for grp, rows in d['群'].items():
        ref = 'ITA' if grp == '防衛' else 'XLV'
        for row in rows:
            t = row.get('本', '')
            if not t.endswith('.T') or '窓' not in row or t[:-2] not in DATA:
                continue
            a, b = [int(x) for x in row['窓'].split('〜')]
            used = DATA[t[:-2]]['used_m']; cm = DATA[t[:-2]]['corr_m']
            ks = [k for k in sorted(used) if a <= k <= b and k in cm and all(k in base[x] for x in SHAPE)]
            if len(ks) < 6:
                continue
            res.append({'file': 'out/alt_etf_compare.json', 'key': f'群.{grp}[{t}]', 'window': f'{ks[0]}〜{ks[-1]}（{len(ks)}か月）',
                        'old_stored': {'単体': row['単体'], '替えた形': row['替えた形']},
                        'old_recomputed': {'単体': stats(used, ks), '替えた形': stats(shape(ks, ref, used), ks)},
                        'corrected': {'単体': stats(cm, ks), '替えた形': stats(shape(ks, ref, cm), ks)}})
    return res


def impact_defense_alts(DATA):
    d = json.load(open(os.path.join(BASE, 'out', 'defense_alts.json')))
    blk = d.get("A' 円建ての短い記録") or {}
    res = []
    for lab in ('466A', '513A'):
        row = blk.get(lab)
        if not isinstance(row, dict) or lab not in DATA:
            continue
        a, b = [int(x) for x in re.findall(r'(\d{6})', row['窓'])[:2]]
        used = DATA[lab]['used_m']; cm = DATA[lab]['corr_m']
        ks = [k for k in sorted(used) if a <= k <= b and k in cm]
        if not ks:
            continue
        res.append({'file': 'out/defense_alts.json', 'key': f"A' 円建ての短い記録.{lab}", 'window': f'{ks[0]}〜{ks[-1]}（{len(ks)}か月）',
                    'old_stored': {'累積': row['累積'][lab], '最大下落': row['最大下落'][lab]},
                    'old_recomputed': {'累積': r2(100 * (math.prod(1 + used[k] for k in ks) - 1), 1), '最大下落': r2(100 * mdd_of(used, ks), 1)},
                    'corrected': {'累積': r2(100 * (math.prod(1 + cm[k] for k in ks) - 1), 1), '最大下落': r2(100 * mdd_of(cm, ks), 1)}})
    return res


def impact_mw_japan(DATA):
    d = json.load(open(os.path.join(BASE, 'out', 'mw_japan.json')))
    rows = {r.get('id'): r for r in d['tested'] if str(r.get('id', '')).startswith('E5_')}
    b_used = {k: v for k, v in DATA['1305']['used_m'].items() if k <= 202608}
    b_corr = DATA['1305']['corr_m']
    res = []
    for code in ('1489', '1577', '1698', '2529', '1478', '1399', '1651', '1494', '2564'):
        st = rows.get(f'E5_{code}.T')
        if not st or code not in DATA:
            continue
        old = (st.get('full') or {})
        z = old.get('to') or 202608
        s_used = {k: v for k, v in DATA[code]['used_m'].items() if k <= z}
        s_corr = {k: v for k, v in DATA[code]['corr_m'].items() if k <= z}
        a = old.get('from')
        rc = M.excess_stats(s_used, b_used, a=a, z=z)
        cc = M.excess_stats(s_corr, {k: v for k, v in b_corr.items() if k <= z}, a=a, z=z)
        pick = lambda x: None if not x else {k: x[k] for k in ('from', 'to', 'ex_ann', 't', 'cagr_s', 'cagr_b', 'cagr_diff')}
        res.append({'file': 'out/mw_japan.json', 'key': f'tested[E5_{code}.T].full（相手 1305.T）',
                    'old_stored': pick(old) if old else None, 'old_recomputed': pick(rc), 'corrected': pick(cc),
                    'delta_ex_ann_pt_vs_recomputed': None if not (rc and cc) else r2(cc['ex_ann'] - rc['ex_ann'])})
    return res


def impact_jp_nisa_bridge(DATA):
    """相手（MSCI Japan gross・1306 の基準価額）は Yahoo の東証の系列ではないので動かない。
    超過の算術平均は 器の月次の差の平均だけ動く（Δex_ann＝12×平均(直した−Yahoo)×100）、cagr_s は器の年率の差だけ動く"""
    d = json.load(open(os.path.join(BASE, 'out', 'mw_jp_nisa_bridge.json')))
    res = []
    for r in d['tested']:
        vid = str(r.get('id', ''))
        if not vid.endswith('.T') or vid[:-2] not in DATA:
            continue
        used = DATA[vid[:-2]]['used_m']; cm = DATA[vid[:-2]]['corr_m']
        row = {'file': 'out/mw_jp_nisa_bridge.json', 'key': f'tested[{vid}]'}
        for blk in ('full', 'hold'):
            st = r.get(blk)
            if not isinstance(st, dict) or 'from' not in st:
                continue
            ks = [k for k in sorted(used) if st['from'] <= k <= st['to'] and k in cm]
            de = 1200 * S.mean(cm[k] - used[k] for k in ks) / 100 * 100 if ks else None
            dg = 100 * (cagr_of(cm, ks) - cagr_of(used, ks)) if ks else None
            row[blk] = {'window': f"{st['from']}〜{st['to']}", 'months_matched': len(ks),
                        'ex_ann_stored': st.get('ex_ann'), 'ex_ann_corrected': r2(st.get('ex_ann') + de) if de is not None and st.get('ex_ann') is not None else None,
                        'cagr_s_stored': st.get('cagr_s'), 'cagr_s_corrected': r2(st.get('cagr_s') + dg) if dg is not None and st.get('cagr_s') is not None else None,
                        'delta_ex_ann_pt': r2(de), 'delta_cagr_s_pt': r2(dg)}
        cap = r.get('capture')
        if isinstance(cap, dict) and cap.get('from'):
            ks = [k for k in sorted(used) if cap['from'] <= k <= cap['to'] and k in cm]
            if ks:
                dv = 1200 * S.mean(cm[k] - used[k] for k in ks)
                va = cap.get('vehicle_active_ann'); pa = cap.get('paper_active_ann')
                row['capture'] = {'window': f"{cap['from']}〜{cap['to']}", 'vehicle_active_ann_stored': va,
                                  'vehicle_active_ann_corrected': r2(va + dv) if va is not None else None,
                                  'capture_ratio_stored': cap.get('capture_ratio'),
                                  'capture_ratio_corrected': r2((va + dv) / pa, 2) if (va is not None and pa) else None,
                                  'note': 'one_factor.beta（載り）は月次の回帰＝分配の月の小さな差では大きく動かない（計算し直していない）'}
        res.append(row)
    return res


def impact_mw_industry(DATA):
    import mw_industry as MI
    d = json.load(open(os.path.join(BASE, 'out', 'mw_industry.json')))
    stored = {r.get('id'): r for r in d['tested'] if 'topix17' in str(r.get('id', ''))}
    codes = [str(x) for x in range(1617, 1634)]
    orig = MI.topix17_data

    def as_used():
        def clean(t):
            r = {k: v for k, v in DATA[t[:-2]]['used_m'].items() if k <= 202608}
            bad = sorted(k for k, v in r.items() if abs(v) > 0.5)
            return {k: v for k, v in r.items() if abs(v) <= 0.5}, bad
        R, bad = {}, {}
        for c in codes:
            R[f'{c}.T'], bad[f'{c}.T'] = clean(f'{c}.T')
        bench, bad['1308.T'] = clean('1308.T')
        return R, bench, {k: v for k, v in bad.items() if v}

    def corrected():
        R = {f'{c}.T': {k: v for k, v in DATA[c]['corr_m'].items() if k <= 202608} for c in codes}
        bench = {k: v for k, v in DATA['1308']['corr_m'].items() if k <= 202608}
        bad = {t: sorted(k for k, v in r.items() if abs(v) > 0.5) for t, r in list(R.items()) + [('1308.T', bench)]}
        return R, bench, {k: v for k, v in bad.items() if v}
    out = {}
    try:
        MI.topix17_data = as_used
        A = {r['id']: r for r in MI.part5(None)}
        MI.topix17_data = corrected
        B = {r['id']: r for r in MI.part5(None)}
    finally:
        MI.topix17_data = orig
    res = []
    pick = lambda x: None if not x else {k: x.get(k) for k in ('from', 'to', 'ex_ann', 't', 'cagr_s', 'cagr_b', 'cagr_diff')}
    for sid in sorted(set(A) | set(B)):
        res.append({'file': 'out/mw_industry.json', 'key': f'tested[{sid}].hold',
                    'old_stored': pick((stored.get(sid) or {}).get('hold')), 'old_recomputed': pick(A[sid]['hold']), 'corrected': pick(B[sid]['hold']),
                    'data_errors_dropped_recomputed': A[sid].get('data_errors_dropped'), 'data_errors_dropped_corrected': B[sid].get('data_errors_dropped'),
                    'holding_last_recomputed': A[sid].get('holding_last'), 'holding_last_corrected': B[sid].get('holding_last'),
                    'delta_ex_ann_pt_vs_recomputed': None if not (A[sid]['hold'] and B[sid]['hold']) else r2(B[sid]['hold']['ex_ann'] - A[sid]['hold']['ex_ann']),
                    'delta_cagr_diff_pt_vs_recomputed': None if not (A[sid]['hold'] and B[sid]['hold']) else r2(B[sid]['hold']['cagr_diff'] - A[sid]['hold']['cagr_diff'])})
    return res


def impact_holdable(DATA):
    import mw_holdable_breakeven as HB
    import numpy as np
    d = json.load(open(os.path.join(BASE, 'out', 'mw_holdable_breakeven.json')))
    st = (d.get('fits') or {}).get('JMKT')
    fx, _ = HB.load_fx()
    import mw_country
    fr = mw_country.french_intl()
    jpn = {k: v for k, v in fr['jpn']['usd'].items() if k <= HB.END}
    jpy_jpn = {m: (1 + jpn[m]) * (1 + fx[m]) - 1 for m in jpn if m in fx}

    def sd_diff(a, b, m0, m1):
        ms = [m for m in HB.mrange(m0, m1) if m in a and m in b]
        x = np.array([a[m] - b[m] for m in ms])
        return {'sd_ann': round(float(x.std(ddof=1) * math.sqrt(12) * 100), 3), 'mean_ann': round(float(x.mean() * 1200), 3), 'n': len(ms), 'from': ms[0], 'to': ms[-1]}
    out = {}
    for lab, ser in (('old_recomputed', DATA['1306']['used_m']), ('corrected', DATA['1306']['corr_m'])):
        bad = sorted(m for m in ser if m in jpy_jpn and 200903 <= m <= HB.END and abs(ser[m] - jpy_jpn[m]) > 0.08)
        y = {m: v for m, v in ser.items() if m not in bad}
        r = sd_diff(y, jpy_jpn, 200903, HB.END)
        r['excluded_months'] = bad
        r['before_exclusion'] = sd_diff(ser, jpy_jpn, 200903, HB.END)
        out[lab] = r
    return [{'file': 'out/mw_holdable_breakeven.json', 'key': 'fits.JMKT（1306 − French の日本〔円〕）',
             'old_stored': None if not st else {k: (round(v, 3) if isinstance(v, float) else v) for k, v in st.items() if k != 'before_fix'},
             **out, 'note': 'sleeves.JMKT.sd（袖 JMKT の雑音）は fits.JMKT.sd_ann/100。mean_ann は袖には入っていない（E=0）'}]


# ═══════════════════════════════ (d) 今の門 ═══════════════════════════════
def live_gate():
    pf = json.load(open(os.path.join(BASE, 'portfolio.json')))
    st = json.load(open(os.path.join(BASE, 'state.json')))
    dd = st.get('data', st)
    pp = dd.get('pf:portfolio'); pp = json.loads(pp) if isinstance(pp, str) else pp
    hold = [(p.get('t'), p.get('kind')) for p in (pp or {}).get('positions') or []]
    t = pf.get('target') or {}
    names = list(t.get('ami_names') or [])
    funds = list((t.get('ami_funds') or {}).keys())
    ex = json.load(open(os.path.join(BASE, 'gate_exceptions.json')))
    sa = json.load(open(os.path.join(BASE, 'out', 'score_all.json')))
    seats = [r['t'] for r in sa if r.get('buy')]
    kl = json.load(open(os.path.join(BASE, 'kanshi_list.json')))
    kt = [x.get('t') if isinstance(x, dict) else x for x in (kl.get('list') if isinstance(kl, dict) else kl)]
    jp = lambda x: bool(re.fullmatch(r'\d{3}[0-9A-Z]', str(x)))
    return {'holdings_state_json': hold, 'holdings_tse': [h for h, _ in hold if jp(h)],
            'ami_names_target': names, 'ami_names_tse': [x for x in names if jp(x)], 'ami_funds（協会の基準価額・Yahoo ではない）': funds,
            'seats_score_all': seats, 'seats_tse': [x for x in seats if jp(x)],
            'gate_exceptions_tse': [x['t'] for x in ex.get('items', []) if jp(x['t'])],
            'kanshi_list_tse（盤の値段・fetch_divs）': [x for x in kt if jp(x)]}


# ═══════════════════════════════ G3 ═══════════════════════════════
SEC_HOST = re.compile(r'(^|\.)sec\.gov$')


class _Src:
    """ast.get_source_segment は呼ぶたびに全文を割るので遅い。行の頭の位置を先に持って切り出す"""
    def __init__(self, s):
        self.s = s
        self.off = [0]
        for line in s.splitlines(keepends=True):
            self.off.append(self.off[-1] + len(line))
        self.lines = s.splitlines()

    def seg(self, n):
        try:
            a = self.off[n.lineno - 1] + len(self.s[self.off[n.lineno - 1]:].encode('utf-8')[:n.col_offset].decode('utf-8', 'ignore'))
            b = self.off[n.end_lineno - 1] + len(self.s[self.off[n.end_lineno - 1]:].encode('utf-8')[:n.end_col_offset].decode('utf-8', 'ignore'))
            return self.s[a:b]
        except Exception:
            return ''


def g3_scan():
    """メールの入った見出しを作る名前と、それを使って送る呼び出し・送る相手のホストを ast で拾う"""
    files = py_files()
    modname = lambda p: os.path.splitext(os.path.basename(p))[0]
    srcs = {p: open(p, encoding='utf-8', errors='replace').read() for p in files}
    # 1) メールの名前を定義しうるファイル（メールの文字列か hachimon_fetch の EMAIL を読む）
    mod_email_names, trees, S_ = {}, {}, {}

    def parse(p):
        if p not in trees:
            try:
                trees[p] = ast.parse(srcs[p]); S_[p] = _Src(srcs[p])
            except SyntaxError:
                trees[p] = None
        return trees[p]
    for p, s in srcs.items():
        if not (EMAIL_RE.search(s) or re.search(r'\bEMAIL\b', s)):
            continue
        tr = parse(p)
        if tr is None:
            continue
        names, changed = set(), True
        assigns = [(n, S_[p].seg(n.value)) for n in ast.walk(tr) if isinstance(n, ast.Assign)]
        assigns = [(n, v) for n, v in assigns if v]
        while changed:
            changed = False
            for n, seg in assigns:
                hit = bool(EMAIL_RE.search(seg)) or any(re.search(rf'\b{re.escape(x)}\b', seg) for x in names)
                if hit:
                    for t in n.targets:
                        for nm in ([t] if not isinstance(t, ast.Tuple) else t.elts):
                            if isinstance(nm, ast.Name) and nm.id not in names:
                                names.add(nm.id); changed = True
        if names:
            mod_email_names[modname(p)] = names
    all_names = set().union(*mod_email_names.values()) if mod_email_names else set()
    name_rx = re.compile(r'\b(' + '|'.join(sorted(map(re.escape, all_names))) + r')\b') if all_names else None
    host_rx = re.compile(r'https?://([A-Za-z0-9.-]+)')
    findings = []
    for p, s in srcs.items():
        if not (EMAIL_RE.search(s) or (name_rx and name_rx.search(s))):
            continue
        tr = parse(p)
        if tr is None:
            continue
        SS = S_[p]
        local = set(mod_email_names.get(modname(p), set()))
        aliases = {}
        for n in ast.walk(tr):
            if isinstance(n, ast.ImportFrom) and n.module:
                for a in n.names:
                    if a.name in mod_email_names.get(n.module, set()):
                        local.add(a.asname or a.name)
            if isinstance(n, ast.Import):
                for a in n.names:
                    aliases[a.asname or a.name] = a.name
        parents = {}
        for n in ast.walk(tr):
            for c in ast.iter_child_nodes(n):
                parents[c] = n

        def encl(n):
            while n in parents:
                n = parents[n]
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    return n
            return tr

        def hdr_has_email(expr):
            seg = SS.seg(expr)
            if EMAIL_RE.search(seg):
                return True
            if any(re.search(rf'\b{re.escape(x)}\b', seg) for x in local):
                return True
            for al, mod in aliases.items():
                for x in mod_email_names.get(mod, set()):
                    if re.search(rf'\b{re.escape(al)}\.{re.escape(x)}\b', seg):
                        return True
            return False
        sites = []
        for n in ast.walk(tr):
            if isinstance(n, ast.Call):
                fn = SS.seg(n.func)
                if fn.endswith('Request'):
                    hk = [k.value for k in n.keywords if k.arg == 'headers']
                    if hk and hdr_has_email(hk[0]):
                        sites.append((n, hk[0]))
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Attribute) and t.attr == 'addheaders' and hdr_has_email(n.value):
                        sites.append((n, n.value))
        if not sites:
            continue
        # モジュールの URL 定数（BASE + '/x' のように別の定数を足したものも、固定点までたどる）
        mod_assign = {}
        for m in tr.body:
            if isinstance(m, ast.Assign) and len(m.targets) == 1 and isinstance(m.targets[0], ast.Name):
                mod_assign[m.targets[0].id] = SS.seg(m.value)
        mod_hosts = {k: set(host_rx.findall(v)) for k, v in mod_assign.items()}
        changed = True
        while changed:
            changed = False
            for k, v in mod_assign.items():
                for nm, hs in list(mod_hosts.items()):
                    if hs and nm != k and re.search(rf'\b{re.escape(nm)}\b', v) and not hs <= mod_hosts[k]:
                        mod_hosts[k] |= hs; changed = True

        def hosts_of(seg):
            hs = set(host_rx.findall(seg))
            for nm, h2 in mod_hosts.items():
                if h2 and re.search(rf'\b{re.escape(nm)}\b', seg):
                    hs |= h2
            return hs
        calls = [m for m in ast.walk(tr) if isinstance(m, ast.Call)]

        def params(fn):
            return [x.arg for x in fn.args.posonlyargs + fn.args.args]

        def resolve(url_expr, scope, depth, how):
            """URL の式 → ホストの集合（引数で受けた URL は呼ぶ所へ最大4段さかのぼる）"""
            if url_expr is None:
                how.append('scope'); return hosts_of(SS.seg(scope) if scope is not tr else '')
            seg = SS.seg(url_expr)
            hs = hosts_of(seg)
            if isinstance(url_expr, ast.Name) and isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                pr = params(scope)
                if url_expr.id in pr:
                    if depth >= 4:
                        how.append('depth'); return hs
                    idx = pr.index(url_expr.id) - (1 if pr and pr[0] in ('self', 'cls') else 0)
                    for m in calls:
                        if SS.seg(m.func).split('.')[-1] != scope.name:
                            continue
                        arg = None
                        for k in m.keywords:
                            if k.arg == url_expr.id:
                                arg = k.value
                        if arg is None and 0 <= idx < len(m.args):
                            arg = m.args[idx]
                        if arg is not None:
                            how.append(f'caller L{m.lineno}')
                            hs |= resolve(arg, encl(m), depth + 1, how)
                    return hs
                local = [n for n in ast.walk(scope) if isinstance(n, ast.Assign)
                         and any(isinstance(t, ast.Name) and t.id == url_expr.id for t in n.targets)]
                for n in local:
                    hs |= hosts_of(SS.seg(n.value))
                for n in ast.walk(scope):   # for u in [...] の形
                    if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == url_expr.id:
                        hs |= hosts_of(SS.seg(n.iter))
            if not hs:
                how.append('scope_fallback')
                hs = hosts_of(SS.seg(scope) if scope is not tr else s)
            return hs

        def outer(n):
            """モジュールの直下の def・class の名前（別のファイルが import するときの名前）"""
            top = None
            while n in parents:
                n = parents[n]
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and parents.get(n) is tr:
                    top = n.name
            return top or '<module>'
        for n, h in sites:
            scope = encl(n)
            how = []
            if isinstance(n, ast.Call):
                url_expr = n.args[0] if n.args else next((k.value for k in n.keywords if k.arg in ('url', 'fullurl')), None)
                hosts = resolve(url_expr, scope, 0, how)
            else:   # opener.addheaders: その class（無ければ関数）の中の URL・参照する定数
                cl = scope
                while cl in parents and not isinstance(cl, ast.ClassDef):
                    cl = parents[cl]
                cl = cl if isinstance(cl, ast.ClassDef) else scope
                hosts = hosts_of(SS.seg(cl) if cl is not tr else s)
                how.append('opener: class の中')
            non_sec = sorted(h_ for h_ in hosts if not SEC_HOST.search(h_))
            findings.append({'file': os.path.relpath(p, BASE), 'line': n.lineno, 'scope': getattr(scope, 'name', '<module>'), 'outer': outer(n),
                             'header_expr_line': h.lineno, 'header_text': EMAIL_RE.sub('<email>', SS.lines[h.lineno - 1].strip())[:200],
                             'hosts': sorted(hosts), 'non_sec_hosts': non_sec, 'resolved_by': sorted(set(how))[:6]})
    # 別のファイルの「メールを送るクラス・関数」を使う所（例: fetch_tsumitate_funds.Lib）
    senders = {}
    for f in findings:
        if f['non_sec_hosts'] and f['outer'] != '<module>':
            senders.setdefault(modname(f['file']), set()).add(f['outer'])
    users = []
    rx_s = re.compile(r'\b(' + '|'.join(map(re.escape, senders)) + r')\b') if senders else None
    for p, s in srcs.items():
        if not (rx_s and rx_s.search(s)):
            continue
        tr = parse(p)
        if tr is None:
            continue
        for n in ast.walk(tr):
            if isinstance(n, ast.ImportFrom) and n.module in senders:
                got = [a.name for a in n.names if a.name in senders[n.module]]
                if got:
                    users.append({'file': os.path.relpath(p, BASE), 'line': n.lineno, 'imports': f'from {n.module} import {", ".join(got)}'})
            if isinstance(n, ast.Import):
                for a in n.names:
                    if a.name in senders:
                        al = a.asname or a.name
                        for m in ast.walk(tr):
                            if isinstance(m, ast.Attribute) and isinstance(m.value, ast.Name) and m.value.id == al and m.attr in senders[a.name]:
                                users.append({'file': os.path.relpath(p, BASE), 'line': m.lineno, 'imports': f'{a.name}.{m.attr}'})
    return findings, users


# 手で確かめた G3 の注記（ast の結果を読んで、実際にどこへ送るかを確かめた・2026-10-14）
G3_REVIEW = {
    'night/fetch_tsumitate_funds.py': '投信協会（toushin-lib.fwg.ne.jp）へ。Lib の opener の既定の見出し（L56）と検索の Request（L65）の両方。'
                                      'fetch_dashboard.fund_quotes（market.yml・平日毎日）と fetch_returns.fund_series（market.yml・returns.yml）がこの Lib を使う＝CI が毎営業日送っている。'
                                      '同じ協会へ送る nx_jpfunds_data.Lib・mw_jp_nisa_bridge・mw_investable_valmom・mw_own_exposure は mw_common/nx_common の UA（メールなし）',
    'market_fetch.py': '_get が Alpha Vantage・FMP（鍵つき）と SEC に同じ見出し。ops.yml が AV_KEY のある月に回す。market_fetch_free.py・market_fetch_sec.py は _get を SEC にだけ使う',
    'kessan_calendar.py': 'get が Alpha Vantage（鍵があれば）にも同じ見出し。ops.yml が毎月回す',
    'kessan_check_jp.py': 'EDINET（api.edinet-fsa.go.jp・disclosure2dl.edinet-fsa.go.jp）。ops.yml（鍵があれば）',
    'night/watch_events.py': '_fetch が EDINET API（鍵つき）にも同じ見出し（SEC と共用）。events.yml（平日毎日）',
    'night/audit_wacc_stale.py': 'FRED（fred.stlouisfed.org）。ops.yml（毎月）',
    'night/fetch_logos.py': 'parqet（assets.parqet.com）・FMP の画像。ops.yml（毎月）',
    'night/beat_spy_rule.py': 'Yahoo（query1.finance.yahoo.com）。CI では回っていない（手で回す道具）',
    'night/backtest_core.py': 'get が SEC と Yahoo の両方に同じ見出し。gate0.yml（年1回）',
    'night/industry_trends.py': 'get が SEC と Ken French（mba.tuck.dartmouth.edu）の両方に同じ見出し。ops.yml（毎月）。industry_exposure.py は get を SEC にだけ使う',
    'night/irr70_dossier.py': 'irr85_extract.UA（メールつき）で EDINET の有報 PDF（disclosure2dl.edinet-fsa.go.jp）も取る。CI では回っていない',
    'night/unx_assets.py': '★この事前登録の別の実装（未コミット）が fetch_tsumitate_funds.Lib を import している＝その道具を回すと協会へメールつきの UA が送られる（リードへ）',
    '解けなかった3か所（ホスト不明）': 'bestpf_ext.py L211（SEC_UA・SEC の URL を引数で受ける）・gaps_delisted_irr.py L113（retro_read_helper.HD・SEC の提出書類）・'
                                    'retro_read_helper.py L32（plain(url)・SEC の提出書類）＝手で読んで SEC だけと確かめた',
}


DEVIATIONS = [
    '事前登録の G2 は「Yahoo の東証の系列を使う道具を一覧にし、分割・分配金の抜けでずれた出力を名指しする（ずれの大きさつき）」だけを決めていて、'
    '点検の線は決めていない。線は道具を書くときに決めた（1日の終値の跳び ×1.6 超＝etf_jp.repair の幅／整数比の近さ |log(比×k)|<0.12／5営業日以内に ±15% へ戻れば壊れた値／'
    '分配の一致は Yahoo の割り戻しが協会の分配の利回りの ±30%〔0.05pt 未満の差は一致〕）。最初の試しで Yahoo の割り戻しの利回りの符号を逆に取っていた純粋な誤りを直した（線は変えていない）',
    '分配の基準は協会の CSV の分配金（決算日の行・基準価額は分配落ち後）。市場価格の権利落ちの日は「決算日の前の Yahoo の営業日」で近似した（月をまたぐのは決算日が月初のときだけ）',
    'mw_jp_nisa_bridge は相手（MSCI Japan gross・1306 の基準価額）を取り直さない Δ法: 相手は Yahoo の東証の系列ではないので、超過の算術平均は器の月次の差の平均だけ、'
    'cagr_s は器の年率の差だけ動く（t値・β・4因子は計算し直していない）',
    'old_recomputed は 2026-10-14 に取り直した Yahoo の値で作った（道具と同じ作り方）。Yahoo は調整後終値をさかのぼって直すので、出力を作った日の値（old_stored）と食い違うことがある＝両方を並べた',
    '探索役が挙げた東証の本のうち、どの道具も Yahoo で使っていない本（1545・2840 ほか）も点検した（データの危うさの記録）。影響の計算には入らない',
]
CAVEATS = [
    '直した系列の確かさは、協会の基準価額の総リターンとの年率の差（G2_instruments.etfs[].monthly.jita_nav_check）で確かめた。残る差は市場価格と基準価額の乖離の分',
    '株（etf_jp の検算5社・nx_brand の日本の9社）は分割の跳びと壊れた値だけを見た。株の配当には独立の基準が無い（測れない）',
    'G3 は静的な走査: 送る相手は同じ関数（URL を引数で受ける関数は呼ぶ所へ最大4段）の文字列と URL 定数から推した。実行時に組む URL・別ファイルから渡す URL は取りこぼしうる＝reviewed_notes で確かめた。'
    '*.py だけ（index.html・シェル・workflow は対象外）',
    'ずれの大きさは各出力の窓・各出力の作り方で計算し直した数字で、判定（格付け）は計算し直していない（直すときは各道具を回し直す）',
]


# ═══════════════════════════════ まとめ ═══════════════════════════════
def summarize(out):
    """結果からまとめを作る（判定の線は足さない＝数字を並べるだけ。直すかはユーザーに確かめる）"""
    wf = {}
    for f in sorted(os.listdir(os.path.join(BASE, '.github', 'workflows'))):
        wf[f] = open(os.path.join(BASE, '.github', 'workflows', f), encoding='utf-8').read()

    def in_ci(path):
        nm = os.path.basename(path)
        return [w for w, t in wf.items() if re.search(rf'\b{re.escape(nm)}\b', t)]
    # G3
    g3 = out['G3_ua']
    files = {}
    for fpath, sites in g3['non_sec_with_email_by_file'].items():
        hosts = sorted({h for x in sites for h in x['non_sec_hosts']})
        files[fpath] = {'lines': [x['line'] for x in sites], 'non_sec_hosts': hosts, 'ci': in_ci(fpath),
                        'header_text': sites[0]['header_text']}
    for u in g3['toushin_lib_users（そのクラスを使う道具）']:
        files.setdefault(u['file'], {'via': u['imports'], 'line': u['line'], 'non_sec_hosts': ['toushin-lib.fwg.ne.jp'], 'ci': in_ci(u['file'])})
    # G2 銘柄
    inst = []
    for c, r in out['G2_instruments']['etfs'].items():
        if not r.get('affected'):
            continue
        d = r.get('distributions')
        sc = d['status_counts'] if isinstance(d, dict) else None
        inst.append({'code': c, 'used_by_tools': c in out['G2_instruments']['used_by_tools'],
                     'unrecorded_splits': [f"{x['date']} {x['as']}（終値×{x['close_ratio']}・調整後も跳ぶ={x['adjclose_also_jumps']}・協会の水準の比 {x['jita_tr_ratio_same_days']}）" for x in r.get('unrecorded_splits') or []],
                     'glitch_days': [f"{g['date']}（{g['close']} ← 前 {g['prev_close']}）" for g in r.get('glitch_days') or []],
                     'distribution_status': sc,
                     'distribution_years_off': {y: v for y, v in (d.get('yearly_pct') or {}).items() if abs(v['missed']) >= 0.05} if isinstance(d, dict) else None,
                     'monthly': {k: (r.get('monthly') or {}).get(k) for k in ('window', 'cagr_yahoo_as_used_pct', 'cagr_corrected_pct', 'cagr_gap_pt', 'n_months_gap_gt_2pct')}})
    ok = [c for c, r in out['G2_instruments']['etfs'].items() if 'error' not in r and not r.get('affected')]
    err = {c: r.get('error') for c, r in out['G2_instruments']['etfs'].items() if 'error' in r}
    st_aff = {g: [x['code'] for x in v if x.get('affected')] for g, v in out['G2_instruments']['stocks'].items()}
    # G2 出力ごとのずれ（並べるだけ）
    rows = []

    def add(fp, key, metric, old_s, old_r, cor):
        if cor is None:
            return
        base = old_r if old_r is not None else old_s
        rows.append({'file': fp, 'key': key, 'metric': metric, 'old_stored': old_s, 'old_recomputed': old_r, 'corrected': cor,
                     'delta_vs_recomputed': None if base is None else round(cor - base, 2)})
    imp = out['G2_impact']
    for x in imp.get('etf_jp') or []:
        if isinstance(x, dict) and x.get('corrected'):
            for m in ('cagr_pct', 'maxdd_pct'):
                add(x['file'], x['key'], m, x['old_stored'].get(m), (x.get('old_recomputed') or {}).get(m), x['corrected'].get(m))
    for x in imp.get('etf_jp_defense') or []:
        if isinstance(x, dict):
            add(x['file'], x['key'], '累積%', x.get('old_stored_pct'), x.get('old_recomputed_pct'), x.get('corrected_pct'))
    for x in imp.get('alt_etf_compare') or []:
        if isinstance(x, dict):
            for blk, m in (('単体', '年率'), ('単体', '最大下落'), ('替えた形', '年率')):
                add(x['file'], x['key'], f'{blk}.{m}', x['old_stored'][blk][m], x['old_recomputed'][blk][m], x['corrected'][blk][m])
    for x in imp.get('defense_alts') or []:
        if isinstance(x, dict):
            for m in ('累積', '最大下落'):
                add(x['file'], x['key'], m, x['old_stored'][m], x['old_recomputed'][m], x['corrected'][m])
    for x in imp.get('mw_japan') or []:
        if isinstance(x, dict) and x.get('corrected'):
            for m in ('ex_ann', 'cagr_s'):
                add(x['file'], x['key'], m, (x.get('old_stored') or {}).get(m), (x.get('old_recomputed') or {}).get(m), x['corrected'].get(m))
    for x in imp.get('mw_jp_nisa_bridge') or []:
        if isinstance(x, dict):
            f_ = x.get('full') or {}
            add(x['file'], x['key'] + '.full', 'ex_ann（Δ法）', f_.get('ex_ann_stored'), None, f_.get('ex_ann_corrected'))
            add(x['file'], x['key'] + '.full', 'cagr_s（Δ法）', f_.get('cagr_s_stored'), None, f_.get('cagr_s_corrected'))
            c_ = x.get('capture') or {}
            add(x['file'], x['key'] + '.capture', 'capture_ratio（Δ法）', c_.get('capture_ratio_stored'), None, c_.get('capture_ratio_corrected'))
    for x in imp.get('mw_industry') or []:
        if isinstance(x, dict) and x.get('corrected'):
            for m in ('ex_ann', 'cagr_diff'):
                add(x['file'], x['key'], m, (x.get('old_stored') or {}).get(m), (x.get('old_recomputed') or {}).get(m), x['corrected'].get(m))
    for x in imp.get('mw_holdable_breakeven') or []:
        if isinstance(x, dict) and x.get('corrected'):
            for m in ('mean_ann', 'sd_ann'):
                add(x['file'], x['key'], m, (x.get('old_stored') or {}).get(m), (x.get('old_recomputed') or {}).get(m), x['corrected'].get(m))
    rows.sort(key=lambda r: -abs(r['delta_vs_recomputed'] or 0))
    lg = out['G2_live_gate']
    return {
        'G3_files_sending_email_to_non_sec': files,
        'G2_affected_instruments': inst, 'G2_clean_instruments': ok, 'G2_errors': err, 'G2_stocks_with_unrecorded_jumps': st_aff,
        'G2_output_deltas_sorted': rows,
        'G2_impact_errors': {k: v.get('error') for k, v in imp.items() if isinstance(v, dict) and v.get('error')},
        'live_gate_affected': bool(lg['holdings_tse'] or lg['ami_names_tse'] or lg['seats_tse'] or lg['gate_exceptions_tse']),
        'live_gate_note': '保有・ETF 側の目標の本・席・門外例外に東証の本は無い（投資信託は協会の基準価額で Yahoo ではない）。'
                          '盤（fetch_dashboard）と fetch_divs は監視リストの日本株の今日の値段・直近の分配を Yahoo から取る＝系列ではなく、分割の日の前日比だけがずれうる'}


# ═══════════════════════════════ 本体 ═══════════════════════════════
def main():
    t0 = time.time()
    out = {'generated': datetime.date.today().isoformat(), 'tool': 'night/unx_datafix.py', 'prereg': PREREG,
           'groups': ['G_data_fixes.G2_yahoo_tse', 'G_data_fixes.G3_ua'],
           'role': '読むだけ。直すかはユーザーに確かめる（事前登録どおり）。リポジトリのファイルは1つも書き換えていない',
           'inputs': {
               'yahoo': f'{YH}{{記号}}?period1=0&period2=…&interval=1d|1mo&events=div%2Csplit（mw_common.yahoo と同じ URL・キャッシュ名）',
               'jita': f'{LIB}/FdsWeb/FDST030000/csv-file-download?isinCd=…&associFundCd=…（基準価額・分配金の日次 CSV・User-Agent は mw_common.UA）',
               'tse_isin_map': 'JPX の ETF 一覧（https://www.jpx.co.jp/equities/products/etfs/issues/01.html）の名前 × 協会の全件の fundNm（2026-10-14 に突き合わせて道具に固定）',
               'french_fred': 'mw_holdable_breakeven の再計算だけ（mw_country.french_intl・FRED DEXJPUS）',
               'cache': CACHE}}
    # ── G3
    findings, users = g3_scan()
    non_sec = [f for f in findings if f['non_sec_hosts']]
    sec_only = [f for f in findings if not f['non_sec_hosts']]
    by_file = {}
    for f in non_sec:
        by_file.setdefault(f['file'], []).append(f)
    out['G3_ua'] = {
        'question': '投信協会（toushin-lib.fwg.ne.jp）ほか SEC 以外へ、User-Agent などの見出しにメールを入れて送っている道具（メールは <email> に伏せた）',
        'method': 'ast: 値の式にメールの文字列・メールの名前（EMAIL 等）を含む名前を固定点まで集め、Request(headers=…)・opener.addheaders にそれが入る所を送る場所とした。'
                  '送る相手＝その関数（とその関数を呼ぶ所）の文字列のホスト＋参照するモジュールの URL 定数。SEC（*.sec.gov）は CLAUDE.md ルール5 で連絡先が要るので別に数えた',
        'toushin_lib_with_email': [f for f in non_sec if 'toushin-lib.fwg.ne.jp' in f['non_sec_hosts']],
        'toushin_lib_users（そのクラスを使う道具）': [u for u in users if 'fetch_tsumitate_funds' in u['imports']],
        'non_sec_with_email_by_file': {k: [{x: f[x] for x in ('line', 'scope', 'header_expr_line', 'header_text', 'non_sec_hosts')} for f in v] for k, v in sorted(by_file.items())},
        'reviewed_notes': G3_REVIEW,
        'n_send_sites_with_email': len(findings), 'n_sec_only': len(sec_only), 'n_with_non_sec_host': len(non_sec),
        'other_users_of_email_senders': [u for u in users if 'fetch_tsumitate_funds' not in u['imports']],
        'caveat': '静的な走査: 相手のホストは同じ関数の文字列から推した（実際に送る相手の上限）。一つの関数が SEC と他の相手の両方の URL を持つ時は両方が出る＝reviewed_notes で確かめた。'
                  'ブラウザ（index.html ほか）・シェル・workflow のメールは対象外（*.py だけ）'}
    # ── G2 (a)
    inv = inventory()
    for r in inv:
        r['reviewed'] = TOOL_NOTES.get(r['file'])
    out['G2_inventory'] = {'helpers': YAHOO_HELPERS, 'tools': inv,
                           'not_yahoo_but_checked': {
                               'night/bestfund_data.py jita_daily': '協会の基準価額の単位替えの倍率の表が (2,3,4,5,10,20,50,100) だけ（16・200 が無い）。東証の市場での分割（2840 1:16・1545 1:200）は協会の基準価額には出ず、協会側の単位替えは 2840 2024-12-20・1545 2026-08-12 の ×10 だけ＝表で戻せる（今は影響なし。将来 ×16 等の単位替えが協会に出たら戻せない）',
                               'night/newfunds.py REF_OLD（2840・1545 の実際の費用）': '協会の基準価額（bestfund_vehicles.td_fund）＝Yahoo ではない'}}
    # ── G2 (b)
    codes = sorted(TSE)
    checks, DATA = {}, {}
    for c in codes:
        try:
            r, dat = check_instrument(c)
        except Exception as e:  # noqa
            r, dat = {'code': c, 'error': f'{type(e).__name__}: {str(e)[:200]}'}, None
        checks[c] = r
        if dat:
            DATA[c] = dat
        print(f"  {c}: {'影響あり' if r.get('affected') else ('—' if 'error' in r else 'ずれなし')}"
              f" 分割{len(r.get('unrecorded_splits') or [])} 壊れ{len(r.get('glitch_days') or [])}"
              f" {(r.get('monthly') or {}).get('cagr_gap_pt')}", flush=True)
    stocks = {}
    for grp, cs in STOCKS.items():
        stocks[grp] = [check_stock(c) for c in cs]
    out['G2_instruments'] = {'etfs': checks, 'stocks': stocks,
                             'used_by_tools': sorted({c for r in inv for c in r['tse_codes_literal'] if c in TSE}),
                             'scout_codes_not_used_via_yahoo': [c for c in SCOUT_CODES if not any(c in r['tse_codes_literal'] for r in inv)]}
    # ── G2 (c)
    imp = {}
    for nm, fn in (('etf_jp', impact_etf_jp), ('etf_jp_defense', impact_etf_jp_defense), ('alt_etf_compare', impact_alt_etf),
                   ('defense_alts', impact_defense_alts), ('mw_japan', impact_mw_japan), ('mw_jp_nisa_bridge', impact_jp_nisa_bridge),
                   ('mw_industry', impact_mw_industry), ('mw_holdable_breakeven', impact_holdable)):
        try:
            imp[nm] = fn(DATA)
        except Exception as e:  # noqa
            import traceback
            imp[nm] = {'error': f'{type(e).__name__}: {str(e)[:300]}', 'trace': traceback.format_exc()[-800:]}
        print(f'  impact {nm}: {"エラー" if isinstance(imp[nm], dict) else len(imp[nm])}', flush=True)
    out['G2_impact'] = imp
    out['G2_live_gate'] = live_gate()
    out['results'] = summarize(out)
    out['decision'] = '報告のみ（事前登録 G2・G3 どおり）。どの道具も直していない——直すか・どれから直すかはユーザーに確かめる'
    out['deviations'] = DEVIATIONS
    out['caveats'] = CAVEATS
    out['runtime_sec'] = round(time.time() - t0)
    tmp = OUT + '.tmp'
    json.dump(out, open(tmp, 'w'), ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print('→', OUT, out['runtime_sec'], '秒')


if __name__ == '__main__':
    main()
