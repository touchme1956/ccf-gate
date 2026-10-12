#!/usr/bin/env python3
"""night/bestpf_fund_persistence.py — bestpf の R6（読むだけ・門の判定・採点・配分には不使用）

問い（事前登録 out/bestpf_prereg.json の modules.R6_fund_persistence・コミット 7c4b672）:
  名の知れた長期の運用者・ファンドは、有名になった後の10年も勝ったか。
  予想（測る前に固定）: 「順位相関は0前後。上位の勝ちは続かない」

主の検定（事前登録どおり）
  A: 2006-01〜2015-12 の SPY に対する超過の年率で順位 → 2016-01〜2026-09 の超過の年率の順位
  B: 1996-01〜2005-12 → 2006-01〜2015-12（データのある本で）
  物差し: 超過の年率＝（ファンドの複利の年率）−（SPY の複利の年率）。同じ月だけで比べ、窓の月が1つでも
          欠けたファンドはその検定から外す（欠測を0と読まない・ルール7）
  統計: Spearman の順位相関（並べ替え検定 100,000回の両側 p）・前半の上位1/3 と下位1/3 の後半の超過の平均の差
        （同じ並べ替えで p）・前半の上位1/3 が後半も SPY に勝った割合
  Berkshire: 年次報告書（2025年の株主への手紙・1965〜2025 の1株あたり時価の変化と S&P 500 配当込み）と、
        Yahoo の月次（BRK-A / BRK-B）で10年ごとの差

データ
  - Yahoo の配当込み（分配金込み）の調整後終値（mw_common.yahoo・キャッシュは out/_bestpf_cache/fund_persistence/）。
    投資信託の調整後終値は分配金（キャピタルゲインの分配を含む）で調整されていることを 2026-10-12 に確かめた
    （例: FCNTX 2025-12-05 の分配 1.09 ドル＝基準価額の約4.5%・調整係数 0.95474→0.99826）
  - ただし Yahoo の調整後終値には『実際には無い分配の調整』（分配の事件はあるのに基準価額が下がっていない）が
    入っている月がある（2026-10-12 検証役の指摘: VWUSX 2019-04・FCNTX 2002-06）。日足で機械的に探し（phantom_scan）、
    分配率2%以上のものだけその月を割り戻す。直した本は運用会社の公表値（SEC）と突き合わせる（data_check_fixed）
  - SMT.L（Scottish Mortgage・ペンス建て）は Yahoo の月足が 2014年の5対1分割の前で調整が月ごとに揺れて壊れている
    （+300%/−80% が交互）。さらに日足の調整後終値も配当（ペンス）を約100分の1しか調整していない（実質は株価だけ）ので、
    日足の終値に配当の事件（ペンス）を足して配当込みの指数を自分で作る（2026-10-12 検証役の指摘で直した）。
    ドルへは GBPUSD=X の日足の月末値（2003-12〜）で直し、それより前は FRED DEXUSUK の月末値でつなぐ
  - BRK-A は Yahoo の月足が直近500か月（1985-02〜）しか返さないので、日足の月末値から作る（BRK-A は分割も配当も無い）
  - CGMFX（CGM Focus）は 2022-11-30 ごろ清算され Yahoo に系列が無い。SEC の目論見書（497K・485BPOS の XBRL）と
    半期報告書（N-CSRS）の年次リターンで感度の一本にだけ入れる（主の検定には入れない）
"""
import datetime, gzip, html, json, math, os, random, re, subprocess, sys, time, urllib.parse, urllib.request
import statistics as S

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402
import gaps_common as G  # noqa: E402
import mw_best_ideas_13f as B13  # noqa: E402  （SEC_UA だけを使う）

BASE = M.BASE
C = os.path.join(BASE, 'out', '_bestpf_cache', 'fund_persistence')
os.makedirs(C, exist_ok=True)
M.CACHE = C          # mw_common.get / yahoo のキャッシュ先をこの担当の場所へ
G.CACHE = C          # gaps_common.fred / french_mkt も
PRE = os.path.join(BASE, 'out', 'bestpf_prereg.json')
OUT = os.path.join(BASE, 'out', 'bestpf_fund_persistence.json')
SEED = 20261012
NPERM = 100000

A1, A2 = (200601, 201512), (201601, 202609)
B1, B2 = (199601, 200512), (200601, 201512)

# 米国株だけの部分集合（感度）から外す本（私の分類・名前と運用方針から。Yahoo の longName を表に残す）
NON_US_OR_MIXED = {
    'SGENX': '世界株（金・債券も持つ）', 'ANWPX': '世界株', 'HAINX': '米国外株', 'DODFX': '米国外株',
    'SMT.L': '英国上場の世界の成長株の投資信託', 'TWEBX': '世界の割安株', 'PRWCX': '株と債券の混合',
}

LIT = [
    {'id': 'SPIVA_US_Persistence_YE2025', 'what': 'S&P Dow Jones Indices『U.S. Persistence Scorecard Year-End 2025』（2026年公表・最新の米国版）',
     'url_primary': 'https://www.spglobal.com/spdji/en/documents/spiva/persistence-scorecard-year-end-2025.pdf',
     'access': '2026-10-12 に本体は HTTP 403（S&P の防御）で読めなかった。数字は二次資料の要約から＝本体で確かめられていない',
     'url_secondary': 'https://genuineimpact.substack.com/p/what-persists-is-failure（2026-08-04）',
     'numbers': [
         '大型株ファンドで 2021年に上半分だった334本のうち、上半分に残ったのは 1年後 58.7%・2年後 6.9%・3年後 5.1%・4年後 4.5%（偶然なら 6.25%）',
         '大型株ファンドで 2021年に上位1/4 だった164本のうち、2022年まで上位1/4 は 20.1%・2023〜2025年まで続けたのは 0%',
         '小型株ファンドで 2021年に上位1/4 だった124本のうち、2025年まで続けたのは 2.4%',
         '逆の例: 大型株で 2023年に上位1/4 だった173本の 28.9%・上半分だった338本の 49.4%（偶然なら 25%）が2年続けた（2024〜2025年の巨大株の流れ）',
         '2020年12月までの5年で下位1/4 だった国内株ファンド459本の 23.1% が2025年末までに合併・清算（上位1/4 の458本は 9.8%）＝負けたファンドほど消える',
         '2025年に大型株ファンドの 79% が S&P 500 に負けた（同じ二次資料・SPIVA の本表）']},
    {'id': 'SPIVA_US_Persistence_YE2024', 'what': 'S&P『U.S. Persistence Scorecard Year-End 2024』（二次資料）',
     'url_secondary': 'https://www.evidenceinvestor.com/post/the-persistence-of-fund-performance-what-the-evidence-shows（2025-05-26）',
     'numbers': ['2020年12月に上位1/4 だった国内株ファンドのうち、その後4年続けて上位1/4 に残ったのは 0本',
                 '大型株で 2020年に上半分 → 4年続けて上半分は 2.4%（偶然なら約6.25%）']},
    {'id': 'Carhart1997', 'what': 'Carhart (1997) On Persistence in Mutual Fund Performance, Journal of Finance 52(1):57-82',
     'url': 'https://doi.org/10.1111/j.1540-6261.1997.tb03808.x（抄録 https://www.afajof.org/page/Top50Cited）',
     'numbers': ['生き残りの偏りの無い標本（1962〜1993）で、成績の持続は株の共通の要因（1年の勢い）と費用でほぼ説明できる。説明できずに残る持続は『最悪のファンドが負け続ける』側に集中（抄録）',
                 '前年の上位10% の翌年の1因子アルファ +0.22%/月（t 2.10）・下位10% −0.45%/月（t −4.58）・素のリターンの差 0.67%/月（年およそ8%＝私の掛け算）。'
                 '4因子では差が 0.29%/月（t 2.13）に縮み、上位10% の4因子アルファは −0.12%/月（t −1.60）＝残る差は下位10% の負け（−0.40%/月・t −4.33）の側'
                 '（Choi & Zhao 2020 の Table 1 の『Carhart (1997) results』の列で確かめた・2026-10-12。旧版の『4因子では差が消える』は不正確だったので直した）']},
    {'id': 'ChoiZhao2020', 'what': 'Choi & Zhao (2020) Did Mutual Fund Return Persistence Persist? NBER WP 26707',
     'url': 'https://www.nber.org/papers/w26707（本文 https://www.nber.org/system/files/working_papers/w26707/w26707.pdf ）',
     'access': '2026-10-12 の直し役の作業で本文の PDF を読めた（検証役の点検の時点では HTTP 504）。下の数字は本文4〜5ページと Table 1 で確かめた',
     'numbers': ['Carhart の 1963〜1993 は再現できたが、1994〜2018 では有意な持続が無い（抄録）',
                 '1994〜2018: 上位10%−下位10% の1因子アルファの差 0.23%/月（p=0.306）・上位10% の4因子アルファ −0.19%/月（p=0.034＝有意に負）・下位10% の4因子アルファ −0.16%/月（p=0.101）・4因子の差 −0.03%/月（p=0.845）（本文4ページ・Table 1）']},
    {'id': 'KTWW2006', 'what': 'Kosowski, Timmermann, Wermers & White (2006) Can Mutual Fund “Stars” Really Pick Stocks? Journal of Finance 61(6):2551-2595',
     'url': 'https://doi.org/10.1111/j.1540-6261.2006.01015.x（読んだのは作業論文 2005-05 版 https://www.cfr-cologne.de/download/workingpaper/cfr-05-14.pdf ）',
     'numbers': ['1975〜2002 の米国株ファンド。5年以上ある1,788本のうち、運だけなら年+10%超のアルファ（費用後）は 9本のはずが実際は 29本',
                 '年−6%未満は運だけなら 63本のはずが実際は 128本＝負けの腕も本物',
                 '年+7%超のアルファの群のうち、ほぼ半分は本物の銘柄選びの腕・残り半分は運',
                 '前3年のアルファで並べた上位10% は翌年も有意（ブートストラップ）だが、通常の t 検定では有意でない（Carhart と同じ）']},
    {'id': 'FamaFrench2010', 'what': 'Fama & French (2010) Luck versus Skill in the Cross-Section of Mutual Fund Returns, Journal of Finance 65(5):1915-1947',
     'url': 'https://doi.org/10.1111/j.1540-6261.2010.01598.x（本文 https://mba.tuck.dartmouth.edu/bespeneckbo/default/AFA611-Eckbo%20web%20site/AFA611-S8C-FamaFrench-LuckvSkill-JF10.pdf ）',
     'numbers': ['1984-01〜2006-09（平均1,308本）。運用中の米国株ファンド全体の費用後アルファは −0.81〜−1.00%/年（t −2.05〜−3.02）＝等加重と時価加重・3因子と4因子の4通りの幅（1921ページ）・費用前はほぼ0（+0.13%・−0.05%）＝全体では市場とほぼ同じで、費用の分だけ負ける',
                 '真のアルファのばらつきの推定は 1.25%/年 → 費用前でも年+1.25%超のファンドは16%未満・年+2.5%超は約2.3%',
                 '費用を払った後に十分なアルファを出すファンドはごく少ない（ブートストラップ）']},
    {'id': 'FKP2018_BuffettsAlpha', 'what': 'Frazzini, Kabiller & Pedersen (2018) Buffett’s Alpha, Financial Analysts Journal 74(4)',
     'url': 'https://gwern.net/doc/economics/2018-frazzini.pdf（CFA 協会 https://rpc.cfainstitute.org/en/research/financial-analysts-journal/2018/faj-v74-n4-3 ・NBER 2013版 https://www.nber.org/papers/w19681 ）',
     'numbers': ['1976-10〜2017-03: Berkshire の無リスク金利を超えるリターン 年18.6%（市場 7.5%）・ぶれ 23.5%（15.3%）・シャープ比 0.79（市場 0.49）・市場ベータ 0.69',
                 '借入（保険の預かり金など）は平均 約1.7倍（NBER 2013版は約1.6倍・シャープ比 0.76）',
                 'アルファ: 市場だけ 13.4%/年（t 4.01）→ 規模・割安・勢いを足して 11.0%（t 3.30）→ 低ベータ（BAB）を足して 8.5%（t 2.55）→ 品質（QMJ）を足して 5.4%（t 1.55＝有意でない）',
                 '13F の上場株の部分は 5.8%（t 3.09）→ 0.3%（t 0.16）＝安全で質の高い割安株を借入で持つことでほぼ説明できる']},
    {'id': 'Morningstar_CGM_secondary', 'what': 'CGM Focus は2000年代の米国株ファンドで1位・年約18%、だが平均的な投資家は年約−11%（Morningstar の調べ・二次資料）',
     'url_secondary': 'https://www.aktienwelt360.de/2016/11/10/warum-dieser-fonds-18-pro-jahr-gemacht-hat-aber-die-anleger-11-verloren-haben/',
     'numbers': ['『年約18%』は SEC の年次報告書で確かめた（2000〜2009 の累計 +418.2%＝年17.9%）。『2000年代1位』と『投資家は年−11%』は二次資料（Morningstar の調べの紹介）だけが出典で、Morningstar の原本では確かめられていない']},
]


# ───────────────────────── 取得 ─────────────────────────
def months(a, z):
    out, y, m = [], a // 100, a % 100
    while y * 100 + m <= z:
        out.append(y * 100 + m)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def yahoo_daily_raw(ticker):
    """Yahoo の日足（終値・調整後終値・分配と分割の事件）をそのまま返す（キャッシュ 3日）"""
    u = (f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?period1=0'
         f'&period2={int(time.time())}&interval=1d&events=div%2Csplit')
    j = json.loads(M.get(u, name=f'yh_{ticker.replace("=", "_")}_1d_full.json', max_age_days=3))
    return j['chart']['result'][0]


def ym_of(d):
    return d.year * 100 + d.month


def consecutive_returns(last):
    """{月: 月末値} → 月次リターン（今月は落とす・抜けた月をまたがない）"""
    now = datetime.datetime.now(datetime.timezone.utc)
    cur = now.year * 100 + now.month
    ks = sorted(k for k in last if k < cur)
    return {k: last[k] / last[p] - 1 for p, k in zip(ks, ks[1:])
            if (k // 100 * 12 + k % 100) - (p // 100 * 12 + p % 100) == 1}


def daily_rows(res):
    """日足 → [(現地の日付, 終値, 調整後終値)]（どちらかが欠ける日は捨てる・0 と読まない）"""
    off = res.get('meta', {}).get('gmtoffset') or 0
    q = res['indicators']['quote'][0]['close']
    a = (res['indicators'].get('adjclose') or [{}])[0].get('adjclose') or [None] * len(q)
    rows = []
    for t, c, x in zip(res['timestamp'], q, a):
        if not isinstance(c, (int, float)) or not isinstance(x, (int, float)) or c <= 0 or x <= 0:
            continue
        rows.append((datetime.datetime.fromtimestamp(t + off, datetime.timezone.utc).date(), c, x))
    return rows, off


# ───── Yahoo の『実際には無い分配の調整』の検査（2026-10-12 検証役の指摘で新設） ─────
# Yahoo の調整後終値は、分配の事件（金額）の日に、それより前の値を (1 − 金額÷前日の基準価額) 倍する。
# 分配が本当にあったなら、その日に基準価額（終値）が分配額のぶん下がる。下がっていないのに調整だけが入ると、
# 調整後終値がその日だけ『分配額のぶん跳ね上がる』（実際には無い利益）。
# 規則: 1995-12〜2026-09 の分配の事件のうち、調整後終値が跳ねた（跳ね ≥ 分配率の4割）もので、
#       事件の日の前後2営業日（計5日）のどの日も、終値の下げ（素のまま・SPY の動きを差し引いたもの）の両方が
#       分配額の4割に届かない → 『下げの見えない分配』。分配率（金額÷前日の基準価額）が 2% 以上なら直す
#       （その月の月次リターンを跳ねの倍率で割り戻す）。0.5〜2% は日々の値動きに紛れて見分けられないので
#       直さず名指しし、全部を直した場合の上限を感度に出す。
PH_RANGE = (19951201, 20260930)
PH_MATERIAL = 0.02
PH_SMALL = 0.005
PH_DROP = 0.4
PH_WIN = 2


def phantom_scan(ticker, spyret):
    res = yahoo_daily_raw(ticker)
    rows, off = daily_rows(res)
    idx = {d: i for i, (d, _, _) in enumerate(rows)}
    material, small, nodate, checked = [], [], [], 0
    for e in (res.get('events') or {}).get('dividends', {}).values():
        d = datetime.datetime.fromtimestamp(e['date'] + off, datetime.timezone.utc).date()
        key = d.year * 10000 + d.month * 100 + d.day
        if not (PH_RANGE[0] <= key <= PH_RANGE[1]):
            continue
        i = idx.get(d)
        if i is None or i == 0:
            nodate.append({'ex_date': str(d), 'amount': e['amount']})
            continue
        a = e['amount']
        cp = rows[i - 1][1]
        rel = a / cp
        jump = (rows[i][2] / rows[i - 1][2]) / (rows[i][1] / rows[i - 1][1])
        checked += 1
        if rel < PH_SMALL or jump - 1 < PH_DROP * rel:
            continue
        drops = []
        for j in range(max(1, i - PH_WIN), min(len(rows), i + PH_WIN + 1)):
            raw = (rows[j - 1][1] - rows[j][1]) / a
            m = spyret.get(rows[j][0])
            mk = (rows[j - 1][1] * (1 + m) - rows[j][1]) / a if m is not None else None
            drops.append({'date': str(rows[j][0]), 'drop_raw': round(raw, 2), 'drop_spy_adj': round(mk, 2) if mk is not None else None})
        if not all(x['drop_raw'] < PH_DROP and (x['drop_spy_adj'] is None or x['drop_spy_adj'] < PH_DROP) for x in drops):
            continue
        ev = {'fund': ticker, 'ex_date': str(d), 'month': ym_of(d), 'amount': a, 'nav_before': round(cp, 4),
              'dist_pct_of_nav': round(rel * 100, 2), 'adjclose_jump_pct': round((jump - 1) * 100, 2), 'jump_factor': jump,
              'nav_drop_as_share_of_dist': drops}
        (material if rel >= PH_MATERIAL else small).append(ev)
    return {'material': material, 'small_unconfirmed': small, 'events_checked': checked, 'event_date_not_trading_day': nodate}


def yahoo_daily_month_end(ticker):
    """日足の調整後終値の月末値 → 月次リターン（今月は落とす・抜けた月をまたがない）。日付は UTC+3 で丸める"""
    r = yahoo_daily_raw(ticker)
    ts = r['timestamp']
    adj = (r['indicators'].get('adjclose') or [{}])[0].get('adjclose') or r['indicators']['quote'][0]['close']
    last = {}
    for t, a in zip(ts, adj):
        if not isinstance(a, (int, float)) or a <= 0:
            continue
        d = datetime.datetime.fromtimestamp(t + 3 * 3600, datetime.timezone.utc)
        last[d.year * 100 + d.month] = a
    now = datetime.datetime.now(datetime.timezone.utc)
    cur = now.year * 100 + now.month
    ks = sorted(k for k in last if k < cur)
    return {k: last[k] / last[p] - 1 for p, k in zip(ks, ks[1:])
            if (k // 100 * 12 + k % 100) - (p // 100 * 12 + p % 100) == 1}, {k: last[k] for k in ks}


def sec_get(url, name):
    p = os.path.join(C, name)
    if os.path.exists(p) and os.path.getsize(p) > 0:
        return open(p, 'rb').read()
    time.sleep(0.15)  # 毎秒10件以下
    b = urllib.request.urlopen(urllib.request.Request(url, headers=B13.SEC_UA), timeout=120).read()
    if b[:2] == b'\x1f\x8b':
        b = gzip.decompress(b)
    open(p + '.part', 'wb').write(b)
    os.replace(p + '.part', p)
    return b


def smt_gbp_total_return():
    """SMT.L の配当込みの月次リターン（ポンド・ペンス建て）を、日足の終値と配当の事件（ペンス）から自分で作る。
    2026-10-12 検証役の指摘: Yahoo の SMT.L の調整後終値は、配当（ペンス）を本来の約100分の1でしか調整していない
    （例: 2016-06-09 の 1.58p＝前日終値の 0.61% に対し、調整後終値の調整は 0.0061%）＝実質は株価だけの系列だった。
    終値は 2014-06-30 の5対1分割の前後でそろっている（分割をまたいで連続）・配当も分割後の単位にそろっていることを確かめた。
    戻り値: (配当込み, 旧の調整後終値〔実質株価だけ〕, 点検の記録)"""
    res = yahoo_daily_raw('SMT.L')
    rows, off = daily_rows(res)
    days = [d for d, _, _ in rows]
    divs, unmatched = {}, []
    for e in (res.get('events') or {}).get('dividends', {}).values():
        d = datetime.datetime.fromtimestamp(e['date'] + off, datetime.timezone.utc).date()
        # 取引の無い日に付いた配当は、その次の取引日に付ける（落とさない）
        nxt = next((x for x in days if x >= d), None)
        if nxt is None:
            unmatched.append(str(d)); continue
        divs[nxt] = divs.get(nxt, 0.0) + e['amount']
    tr, prev = 1.0, None
    me_tr, me_adj, me_px = {}, {}, {}
    for d, c, a in rows:
        if prev is not None:
            tr *= (c + divs.get(d, 0.0)) / prev
        prev = c
        me_tr[ym_of(d)] = tr; me_adj[ym_of(d)] = a; me_px[ym_of(d)] = c
    r_tr, r_adj, r_px = consecutive_returns(me_tr), consecutive_returns(me_adj), consecutive_returns(me_px)
    # 点検: 窓ごとの配当の上乗せ（配当込みの年率 − 終値だけの年率）と、旧の調整後終値の上乗せ
    chk = {}
    for lab, (a_, z_) in [('1996-2005', B1), ('2006-2015', A1), ('2016-2026-09', A2)]:
        g_tr, g_adj, g_px = cagr_window(r_tr, a_, z_), cagr_window(r_adj, a_, z_), cagr_window(r_px, a_, z_)
        if None in (g_tr, g_adj, g_px):
            chk[lab] = None; continue
        chk[lab] = {'div_contrib_ann_pct（配当込み−終値だけ）': round((g_tr - g_px) * 100, 2),
                    'yahoo_adjclose_contrib_ann_pct（旧の調整後終値−終値だけ）': round((g_adj - g_px) * 100, 3)}
    sample = []
    for d in sorted(divs):
        if datetime.date(2016, 1, 1) <= d <= datetime.date(2016, 12, 31):
            i = days.index(d)
            sample.append({'ex_date': str(d), 'div_pence': round(divs[d], 4), 'prev_close_pence': rows[i - 1][1],
                           'div_pct_of_price': round(divs[d] / rows[i - 1][1] * 100, 3),
                           'yahoo_adjclose_adjust_pct': round(((rows[i][2] / rows[i - 1][2]) / (rows[i][1] / rows[i - 1][1]) - 1) * 100, 4)})
    return r_tr, r_adj, {'dividend_events': len(divs), 'unmatched_dividend_dates': unmatched,
                         'window_check': chk, 'sample_2016': sample}


def smt_usd():
    """SMT.L（ペンス）→ ドル建ての月次リターン。為替は GBPUSD=X の日足の月末（2003-12〜）・それより前は FRED DEXUSUK の月末。
    主は配当込み（終値＋配当で自分で作る）。旧の調整後終値（実質株価だけ）の版も『直す前』の比較のために返す"""
    r_gbp, r_gbp_old, divchk = smt_gbp_total_return()
    _, fx_y = yahoo_daily_month_end('GBPUSD=X')
    fx_f = {k: v for k, v in G.fred('DEXUSUK').items()}
    first_y = min(fx_y)
    fx = {}
    for k, v in fx_f.items():
        if k < first_y:
            fx[k] = v
    fx.update(fx_y)
    ks = sorted(fx)
    r_fx = {k: fx[k] / fx[p] - 1 for p, k in zip(ks, ks[1:])
            if (k // 100 * 12 + k % 100) - (p // 100 * 12 + p % 100) == 1}
    usd = {k: (1 + r_gbp[k]) * (1 + r_fx[k]) - 1 for k in r_gbp if k in r_fx}
    usd_old = {k: (1 + r_gbp_old[k]) * (1 + r_fx[k]) - 1 for k in r_gbp_old if k in r_fx}
    # つなぎ目の検算: 重なる月で Yahoo と FRED の為替の月次の変化を比べる
    fks = sorted(fx_f)
    r_ff = {k: fx_f[k] / fx_f[p] - 1 for p, k in zip(fks, fks[1:])}
    yks = sorted(fx_y)
    r_yy = {k: fx_y[k] / fx_y[p] - 1 for p, k in zip(yks, yks[1:])}
    ov = sorted(set(r_ff) & set(r_yy))
    ov = [k for k in ov if k <= 202609]
    chk = {'overlap_months': len(ov), 'corr': round(M.corr([r_ff[k] for k in ov], [r_yy[k] for k in ov]), 4),
           'mean_abs_diff_pct': round(S.mean(abs(r_ff[k] - r_yy[k]) for k in ov) * 100, 3),
           'yahoo_fx_first_month': first_y}
    outl = [(k, round(v, 3)) for k, v in r_gbp.items() if abs(v) > 0.35]
    return usd, r_gbp, chk, outl, usd_old, divchk


def cgm_focus():
    """CGM Focus（CGMFX）の年次リターンを SEC の提出書類から。主の検定には入れない（感度だけ）"""
    t = sec_get('https://www.sec.gov/Archives/edgar/data/60335/000006033522000031/ck0000060335-20211231.htm',
                'sec_cgm_485bpos_2022.htm').decode('utf-8', 'replace')
    ctxdef = {}
    for m in re.finditer(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', t, re.S):
        ctxdef[m.group(1)] = m.group(2)
    ann, avg = {}, {}
    for m in re.finditer(r'<ix:nonFraction([^>]*)>([^<]*)</ix:nonFraction>', t):
        a = m.group(1)
        nm = re.search(r'name="([^"]+)"', a).group(1)
        ctx = re.search(r'contextRef="([^"]+)"', a).group(1)
        body = ctxdef.get(ctx, '')
        if 'S000000876Member' not in body:          # CGM Focus Fund の系列だけ
            continue
        if not (nm.startswith('rr:AnnualReturn') or nm.startswith('rr:AverageAnnualReturnYear')):
            continue
        try:
            v = float(m.group(2).replace(',', '')) * (-1 if 'sign="-"' in a else 1)
        except ValueError:
            continue
        mm = re.match(r'rr:AnnualReturn(\d{4})$', nm)
        if mm:
            ann[int(mm.group(1))] = v
        elif nm.startswith('rr:AverageAnnualReturnYear'):
            who = 'sp500' if 'SandP500IndexMember' in body else ('fund' if 'PerformanceMeasureAxis' not in body else None)
            if who:
                avg[f'{who}_{nm[-2:]}y_to_2021'] = v
    t16 = sec_get('https://www.sec.gov/Archives/edgar/data/60335/000006033516000076/a2016_focussummarypros.htm',
                  'sec_cgm_497k_2016.htm').decode('latin-1')
    t16 = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', t16)).replace('&nbsp;', ' ')
    mm = re.search(r'Return before taxes\s*\(?([\d.]+)\)?%\s*\(?([\d.]+)\)?%\s*\(?([\d.]+)\)?%.*?S&(?:amp;)?P 500 INDEX.*?\)\s*([\d.]+)%\s*([\d.]+)%\s*([\d.]+)%', t16)
    ten15 = {'fund_10y_2006_2015': float(mm.group(3)), 'sp500_10y_2006_2015': float(mm.group(6)),
             'fund_1y_2015': -float(mm.group(1)) if '(' + mm.group(1) in t16 else float(mm.group(1))} if mm else None
    tn = sec_get('https://www.sec.gov/Archives/edgar/data/60335/000006033522000043/cgmncsr06302022.htm',
                 'sec_cgm_ncsrs_2022.htm').decode('latin-1')
    tn = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', tn))
    mh = re.search(r'For the first six months of the year, CGM Focus Fund decreased -([\d.]+)%', tn)
    h1 = -float(mh.group(1)) if mh else None
    t497 = sec_get('https://www.sec.gov/Archives/edgar/data/60335/000092963822001509/form497.htm',
                   'sec_cgm_497_2022.htm').decode('latin-1')
    liq = 'November 30, 2022' if 'November 30, 2022' in t497 else None
    t09 = sec_get('https://www.sec.gov/Archives/edgar/data/60335/000095015610000031/d73427_ncsr.htm',
                  'sec_cgm_ncsr_2009.htm').decode('latin-1')
    t09 = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', t09)).replace('\xa0', ' '))
    m09 = re.search(r'CGM Focus Fund 10 Years\s*\+\s*([\d.]+)\s*%', t09)
    ten09 = None
    if m09:
        cum = float(m09.group(1))
        ten09 = {'cum_pct_2000_2009': cum, 'ann_pct_2000_2009': round(((1 + cum / 100) ** 0.1 - 1) * 100, 2)}
    return {'annual_pct': ann, 'avg_pct': avg, 'ten_2006_2015': ten15, 'h1_2022_pct': h1, 'liquidation_date': liq,
            'ten_2000_2009': ten09,
            'sources': {
                '485BPOS_2022_xbrl': 'https://www.sec.gov/Archives/edgar/data/60335/000006033522000031/ck0000060335-20211231.htm（rr:AnnualReturn2012〜2021・系列 S000000876）',
                '497K_2016': 'https://www.sec.gov/Archives/edgar/data/60335/000006033516000076/a2016_focussummarypros.htm（10年平均 2006〜2015）',
                'N-CSRS_2022-06-30': 'https://www.sec.gov/Archives/edgar/data/60335/000006033522000043/cgmncsr06302022.htm（2022年上半期 −10.9%・S&P 500 −20.0%）',
                '497_2022-09-30': 'https://www.sec.gov/Archives/edgar/data/60335/000092963822001509/form497.htm（清算の決定・2022-11-30 ごろ運用停止）',
                'N-CSR_2009-12-31': 'https://www.sec.gov/Archives/edgar/data/60335/000095015610000031/d73427_ncsr.htm（10年の累計 +418.2%＝2000〜2009）'}}


def brk_letter():
    """Berkshire の2025年の株主への手紙（2026-02-28）の表『Berkshire’s Performance vs. the S&P 500』を読む"""
    url = 'https://www.berkshirehathaway.com/letters/2025ltr.pdf'
    b = M.get(url, name='brk_2025ltr.pdf', max_age_days=365)
    pdf = os.path.join(C, 'brk_2025ltr.pdf')
    txt = os.path.join(C, 'brk_2025ltr.txt')
    if not (os.path.exists(txt) and os.path.getsize(txt) > 0):
        subprocess.run(['pdftotext', '-layout', pdf, txt], check=True)
    rows = {}
    for line in open(txt, encoding='utf-8', errors='replace'):
        m = re.match(r'^\s*(\d{4})\s*[ .]+\s+(\(?-?[\d.]+\)?)%?\s+(\(?-?[\d.]+\)?)%?\s*$', line)
        if not m:
            continue
        y = int(m.group(1))

        def val(s):
            neg = s.startswith('(')
            v = float(s.strip('()'))
            return -v if neg else v
        rows[y] = (val(m.group(2)), val(m.group(3)))
    comp = re.search(r'Compounded Annual Gain.*?([\d.]+)%\s+([\d.]+)%', open(txt, encoding='utf-8', errors='replace').read())
    return rows, ({'brk': float(comp.group(1)), 'sp500': float(comp.group(2))} if comp else None), url


# ───────────────────────── 計算 ─────────────────────────
def cagr_window(r, a, z):
    ks = months(a, z)
    if any(k not in r for k in ks):
        return None
    return math.exp(math.fsum(math.log1p(r[k]) for k in ks) * 12 / len(ks)) - 1


def excess(r, b, a, z, kind='geo'):
    ks = months(a, z)
    if any(k not in r or k not in b for k in ks):
        return None
    if kind == 'geo':
        return (cagr_window(r, a, z) - cagr_window(b, a, z)) * 100
    return S.mean(r[k] - b[k] for k in ks) * 12 * 100


def alpha_capm(r, b, rf, a, z):
    ks = months(a, z)
    if any(k not in r or k not in b or k not in rf for k in ks):
        return None
    y = [r[k] - rf[k] for k in ks]
    x = [b[k] - rf[k] for k in ks]
    mx, my = S.mean(x), S.mean(y)
    beta = sum((u - mx) * (v - my) for u, v in zip(x, y)) / sum((u - mx) ** 2 for u in x)
    return (my - beta * mx) * 12 * 100, beta


def ols(y, X):
    """最小二乗（定数項つき）。X は説明変数の列のリスト → (切片, 係数のリスト)。正規方程式をガウスの消去で解く"""
    n, k = len(y), len(X) + 1
    cols = [[1.0] * n] + [list(c) for c in X]
    A = [[sum(cols[i][t] * cols[j][t] for t in range(n)) for j in range(k)] for i in range(k)]
    b = [sum(cols[i][t] * y[t] for t in range(n)) for i in range(k)]
    for i in range(k):
        p = max(range(i, k), key=lambda r: abs(A[r][i]))
        A[i], A[p] = A[p], A[i]; b[i], b[p] = b[p], b[i]
        for r in range(i + 1, k):
            f = A[r][i] / A[i][i]
            for c in range(i, k):
                A[r][c] -= f * A[i][c]
            b[r] -= f * b[i]
    x = [0.0] * k
    for i in range(k - 1, -1, -1):
        x[i] = (b[i] - sum(A[i][c] * x[c] for c in range(i + 1, k))) / A[i][i]
    return x[0], x[1:]


def alpha_style(r, F, a, z):
    """型（スタイル）で調整したアルファ（年率%）。F = {名前: {月: 値}}（右辺）。左辺は r − rf（F['_rf']）"""
    ks = months(a, z)
    rf = F['_rf']
    if any(k not in r or k not in rf or any(k not in F[f] for f in F if f != '_rf') for k in ks):
        return None
    y = [r[k] - rf[k] for k in ks]
    names = [f for f in F if f != '_rf']
    X = [[F[f][k] for k in ks] for f in names]
    c, bs = ols(y, X)
    return c * 12 * 100, dict(zip(names, [round(v, 2) for v in bs]))


def ranks(v):
    """大きいほど1位。同順位は平均の順位"""
    idx = sorted(range(len(v)), key=lambda i: -v[i])
    rk = [0.0] * len(v)
    i = 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and v[idx[j + 1]] == v[idx[i]]:
            j += 1
        for t in range(i, j + 1):
            rk[idx[t]] = (i + j) / 2 + 1
        i = j + 1
    return rk


def pearson(a, b):
    return M.corr(a, b)


def persistence(names, x1, x2, label, nperm=NPERM):
    """x1・x2 は前半・後半の超過（%/年）。順位相関・三分位・並べ替え p"""
    n = len(names)
    r1, r2 = ranks(x1), ranks(x2)
    rho = pearson(r1, r2)
    k = n // 3
    order = sorted(range(n), key=lambda i: r1[i])
    top, bot = order[:k], order[-k:]
    mid = order[k:n - k]

    def tb(vals):
        return S.mean(vals[i] for i in top) - S.mean(vals[i] for i in bot)
    d_obs = tb(x2)
    rng = random.Random(SEED)
    perm = list(range(n))
    c_rho = c_d = 0
    for _ in range(nperm):
        rng.shuffle(perm)
        r2p = [r2[i] for i in perm]
        x2p = [x2[i] for i in perm]
        if abs(pearson(r1, r2p)) >= abs(rho) - 1e-12:
            c_rho += 1
        if abs(tb(x2p)) >= abs(d_obs) - 1e-12:
            c_d += 1
    win1 = [i for i in range(n) if x1[i] > 0]
    lose1 = [i for i in range(n) if x1[i] <= 0]
    rows = sorted(({'fund': names[i], 'ex1': round(x1[i], 2), 'rank1': r1[i], 'ex2': round(x2[i], 2), 'rank2': r2[i],
                    'third1': ('上位' if i in top else '下位' if i in bot else '中位'), 'beat_spy2': x2[i] > 0}
                   for i in range(n)), key=lambda d: d['rank1'])
    return {
        'label': label, 'n': n, 'tercile_size': k,
        'top_third_ex1_mean': round(S.mean(x1[i] for i in top), 2), 'bottom_third_ex1_mean': round(S.mean(x1[i] for i in bot), 2),
        'spearman': round(rho, 3), 'perm_p_two_sided': round(c_rho / nperm, 4),
        'null_sd_approx': round(1 / math.sqrt(n - 1), 3),
        'top_third_ex2_mean': round(S.mean(x2[i] for i in top), 2), 'top_third_ex2_median': round(S.median(x2[i] for i in top), 2),
        'mid_third_ex2_mean': round(S.mean(x2[i] for i in mid), 2) if mid else None,
        'bottom_third_ex2_mean': round(S.mean(x2[i] for i in bot), 2), 'bottom_third_ex2_median': round(S.median(x2[i] for i in bot), 2),
        'top_minus_bottom_ex2': round(d_obs, 2), 'top_minus_bottom_perm_p': round(c_d / nperm, 4),
        'top_third_beat_spy2_share': round(sum(1 for i in top if x2[i] > 0) / k, 3),
        'top_third_beat_spy2_count': f'{sum(1 for i in top if x2[i] > 0)}/{k}',
        'bottom_third_beat_spy2_count': f'{sum(1 for i in bot if x2[i] > 0)}/{k}',
        'all_beat_spy2_count': f'{sum(1 for v in x2 if v > 0)}/{n}',
        'all_beat_spy1_count': f'{sum(1 for v in x1 if v > 0)}/{n}',
        'winners1_winners2': f'{sum(1 for i in win1 if x2[i] > 0)}/{len(win1)}',
        'losers1_winners2': f'{sum(1 for i in lose1 if x2[i] > 0)}/{len(lose1)}',
        'ex1_median': round(S.median(x1), 2), 'ex2_median': round(S.median(x2), 2), 'ex2_mean': round(S.mean(x2), 2),
        'rows': rows,
    }


def run_test(R, spy, w1, w2, label, kind='geo', subset=None, extra=None, nperm=NPERM):
    names, x1, x2, excluded = [], [], [], []
    for t, r in R.items():
        if subset is not None and t not in subset:
            continue
        e1, e2 = excess(r, spy, *w1, kind=kind), excess(r, spy, *w2, kind=kind)
        if e1 is None or e2 is None:
            miss = [k for k in months(w1[0], w2[1]) if k not in r]
            excluded.append({'fund': t, 'first_month': min(r) if r else None, 'missing_months_in_windows': len(miss)})
            continue
        names.append(t); x1.append(e1); x2.append(e2)
    if extra:
        for t, (e1, e2) in extra.items():
            names.append(t); x1.append(e1); x2.append(e2)
    res = persistence(names, x1, x2, label, nperm=nperm)
    res['windows'] = {'first': list(w1), 'second': list(w2)}
    res['measure'] = '幾何（複利の年率の差）' if kind == 'geo' else '算術（月次の差の平均×12）'
    res['excluded'] = excluded
    return res


def letter_decades(rows):
    def cg(a, z, i):
        ys = [y for y in range(a, z + 1)]
        if any(y not in rows for y in ys):
            return None
        g = math.fsum(math.log1p(rows[y][i] / 100) for y in ys)
        return (math.exp(g / len(ys)) - 1) * 100
    out = []
    for a, z, lab in [(1965, 1969, '1965〜1969（1965・1966 は9月決算・1967 は15か月）'), (1970, 1979, '1970年代'),
                      (1980, 1989, '1980年代'), (1990, 1999, '1990年代'), (2000, 2009, '2000年代'), (2010, 2019, '2010年代'),
                      (2016, 2025, '2016〜2025'), (2020, 2025, '2020〜2025'), (1965, 2025, '1965〜2025 全期間')]:
        b, s = cg(a, z, 0), cg(a, z, 1)
        out.append({'period': lab, 'years': f'{a}-{z}', 'brk_cagr': round(b, 2), 'sp500tr_cagr': round(s, 2),
                    'diff': round(b - s, 2), 'brk_beat_years': f'{sum(1 for y in range(a, z + 1) if rows[y][0] > rows[y][1])}/{z - a + 1}'})
    roll = []
    for a in range(1965, 2017):
        z = a + 9
        b, s = cg(a, z, 0), cg(a, z, 1)
        if b is not None:
            roll.append({'from': a, 'to': z, 'diff': round(b - s, 2)})
    return out, roll

DEVIATIONS = [
    'CGMFX（CGM Focus）は 2022-11-30 ごろ清算され Yahoo に系列が無い→主の検定から外し、SEC の提出書類の年次リターンで感度の一本（清算の後は SPY に乗り換えたと置く）にだけ入れた',
    'SMT.L は Yahoo の月足が分割の前で壊れている（+300%/−80% が交互）ので、M.yahoo の月足ではなく日足から作った。さらに Yahoo の調整後終値は配当（ペンス）を約100分の1しか調整していない（実質は株価だけ）と検証役が見つけたので、日足の終値に配当の事件（ペンス）を足して配当込みの系列を自分で作り直した（2026-10-12）。ドルへの換算は GBPUSD=X の日足の月末（2003-12〜）で、それより前（1996〜2003）は FRED DEXUSUK の月末でつないだ（重なる273か月の為替の月次の相関 0.976）',
    'Yahoo の調整後終値に『実際には無い分配の調整』（分配の事件はあるのに基準価額が下がっていない）が入っている月を、日足で機械的に探して直した（2026-10-12・検証役の指摘）。直したのは分配率2%以上の2件（VWUSX 2019-04・FCNTX 2002-06）だけで、どちらも運用会社の公表値（SEC）と突き合わせて確かめた。0.5〜2% の候補は日々の値動きに紛れて見分けられないので直さず、全部を直した場合を感度に出した',
    '検定 B では BRK-B の上場前の 1996-01〜05 を BRK-A の月次で埋めた（重なる364か月の相関 0.989）',
    'BRK-A の1980年代は M.yahoo の月足が直近500か月（1985-02〜）しか返さないので日足の月末値から作った。1980年代の比べる相手は SPY も S&P 500 配当込み指数（^SP500TR は 1988-01〜）も Yahoo に無いので、French の米国市場（CRSP の時価加重・配当込み）を使い、Berkshire の手紙の表（S&P 500 配当込みの暦年）も並べた',
    '事前登録に無い追加（事後・参考）: 算術の超過・米国株の本だけ・ベータ調整のアルファ・型で調整したアルファ（A の結果を見た後に、上位と下位が型で並んでいると見えたので足した）・後半の超過を型の部分とアルファの部分に分ける分解（検証役の指摘で足した）・5年ずつの組・清算された CGMFX を入れる感度・直す前のデータでの結果',
    'SPIVA の本体（S&P の PDF・ページ）は 2026-10-12 に HTTP 403 で読めず、数字は二次資料（Genuine Impact 2026-08-04・Evidence Investor 2025-05-26）の要約から取った＝本体で確かめられていない',
    'Carhart (1997) と Kosowski ほか (2006) と Fama-French (2010) の雑誌の版は出版社のページが 403 で、Carhart の数字は Choi & Zhao (2020) の再現論文の Table 1（本文の PDF で確かめた）、Kosowski ほかは 2005年の作業論文、Fama-French は公開の本文の写しから取った',
]
CAVEATS = [
    '32本は今の時点で有名な本＝生き残りの偏りがある（消えたファンドは入らない）。全体の成績は良く見え、順位の持続もゆがむ',
    '比べる相手は SPY だけ。世界株・米国外・株と債券の混合の本も SPY と比べたので、順位は腕よりも型（米国株か・成長株か）で決まりやすい。米国株の本だけ・型で調整したアルファの感度も見た',
    'ファンドは Yahoo の調整後終値（分配金込み・費用は引かれた後・税は引いていない）。米国の投資信託の A 株（AGTHX・AIVSX・AMCPX・ANWPX）の販売手数料は引いていない。SMT.L は英国の投資信託会社の株価（純資産との差の割安・割高を含む）に配当を足したもの',
    'Yahoo のデータの点検は『分配の事件があるのに基準価額が下がっていない』向きだけを機械で探した。逆向き（分配があったのに Yahoo に事件が無い＝実際には無い損）は機械では探せておらず、運用会社の公表値との突き合わせ（DODGX・DODFX・VWUSX・FCNTX）で合うことを見ただけ。分配率0.5〜2% の候補は直していない（全部直しても結論は変わらないことは感度で確かめた）',
    'BPTRX の 2003-04 より前は前身のパートナーシップの成績の可能性が高い（成功報酬つき）＝検定 B の前半は器が違う',
    '本の数が少ない（28〜31本）。順位相関の偶然のぶれは ±0.18〜0.19 程度（1/√(n−1)）。10年の窓は2組しかなく、独立な試行は実質2回',
    'Berkshire の1980年代の Yahoo の比較は French の米国市場（S&P 500 ではない）で、手紙の S&P 500 の数字と少し違う',
    'CGMFX の感度は 2022-07 以降（清算まで含む）を SPY と同じと置いた。清算の前の2022年7〜11月の成績は確かめられない',
    '型で調整したアルファの物差し（成長−割安・小型−大型・米国外−米国・債券）には品質・低ベータ・勢いが入っていない。米国外は 0.6 VEURX＋0.4 VPACX の私の置き値。型で説明できない残りが腕なのか、物差しに無い型なのかは見分けられない',
]


def for_final(o):
    tA, s = o['test_A'], o['sensitivity']
    dec = s['A_style_decomposition']
    return [
        f"超投資家・有名ファンドの成績は『次の10年』にほとんど引き継がれない: 有名な32本のうち 2016〜2026-09 に SPY に勝ったのは {tA['all_beat_spy2_count']} 本（中央値 {tA['ex2_median']:+}%/年）。"
        "過去の成績で運用者を選ぶ根拠は弱い（1996〜2005→2006〜2015 では順位が逆向き・5年ずつの組では符号が入れ替わる）＝R1・R2 の『写し』を採るなら R2 の事前登録の合格線（費用後 +1%/年・t≥2・前半後半とも正）を厳しく当てる",
        f"2006〜2015→2016〜2026 で順位が続いた分のうち、型（成長株・米国株）の流れで説明できるのは約半分（後半の超過の前半の成績への傾き {dec['slope_total']} のうち 型 {dec['slope_style_part']}・型で説明できない残り {dec['slope_alpha_part']}）。"
        f"残りの半分（型で調整したアルファの順位相関 {s['A_style_alpha']['spearman']}・p={s['A_style_alpha']['perm_p_two_sided']}）は、腕なのか、私の物差しに無い型（品質・低ベータ・勢い）なのかは見分けられない。"
        "1996〜2005→2006〜2015 では型で調整しても持続は弱く（順位相関 " + str(s['B_style_alpha']['spearman']) + "）、素の順位は逆向きだった＝最終の選択で過去の勝ち組の型（成長株・テック）に重く賭けるなら、それは主に型の賭けで、型の流れがいつ反転するかは当てられないと分かったうえで",
        'Berkshire の超過は 1970〜1980年代の年+16〜22点から 2010年代以降の 0〜−2点へ縮んだ。品質・低ベータ・借入で説明される（Buffett’s Alpha）＝個別株15%の部分で『超投資家と重なる銘柄』を示すのは参考どまりにする',
        '持続が残るのは負けの側（SPIVA・Carhart: 下位は下位に残りやすく消えやすい）＝費用が高く型の偏った能動の器を避けること自体には根拠がある',
    ]


def sec_text(url, name):
    t = sec_get(url, name).decode('utf-8', 'replace')
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', t)).replace('\xa0', ' '))


def yr_ret(r, y):
    ks = months(y * 100 + 1, y * 100 + 12)
    return None if any(k not in r for k in ks) else (math.prod(1 + r[k] for k in ks) - 1) * 100


def data_check_fixed(R, R_raw):
    """直した2本（VWUSX・FCNTX）を、運用会社の公表（SEC の提出書類）と、直す前・直した後で突き合わせる"""
    out = []
    for u, nm, y in [('https://www.sec.gov/Archives/edgar/data/52848/000168386320015429/f7676d1.htm', 'sec_vwusx_497k_2020.htm', 2019),
                     ('https://www.sec.gov/Archives/edgar/data/52848/000005284826000643/f45461d1.htm', 'sec_vwusx_2026.htm', 2024)]:
        t = sec_text(u, nm)
        m = re.search(rf'Periods Ended December 31, {y} 1 Year 5 Years 10 Years Vanguard U\.S\. Growth Fund Investor Shares '
                      r'Return Before Taxes ([\d.]+) ?% ([\d.]+) ?% ([\d.]+) ?%', t)
        row = {'fund': 'VWUSX', 'source': u, 'periods': f'1年・5年・10年（{y}-12 まで・年率%）'}
        if not m:
            row['error'] = '公表値が読めない'; out.append(row); continue

        def three(r):
            v = [yr_ret(r, y), cagr_window(r, (y - 4) * 100 + 1, y * 100 + 12), cagr_window(r, (y - 9) * 100 + 1, y * 100 + 12)]
            return [round(v[0], 2) if v[0] is not None else None] + [round(x * 100, 2) if x is not None else None for x in v[1:]]
        row.update({'official': [float(m.group(i)) for i in (1, 2, 3)], 'yahoo_before_fix': three(R_raw['VWUSX']),
                    'yahoo_after_fix': three(R['VWUSX'])})
        out.append(row)
    u = 'https://www.sec.gov/Archives/edgar/data/24238/000002423808000006/main.htm'
    t = sec_text(u, 'sec_fcntx_485bpos_2008.htm')
    m = re.search(r'Year-by-Year Returns <R> Contrafund </R> <R> Calendar Years </R>((?: <R> \d{4} </R>){10})((?: <R> -?[\d.]+% </R>){10})', t)
    if m:
        ys = [int(x) for x in re.findall(r'\d{4}', m.group(1))]
        vs = [float(x) for x in re.findall(r'-?[\d.]+(?=%)', m.group(2))]
        rows = []
        for y, v in zip(ys, vs):
            b, a = yr_ret(R_raw['FCNTX'], y), yr_ret(R['FCNTX'], y)
            rows.append({'year': y, 'official': v, 'yahoo_before_fix': round(b, 2) if b is not None else None,
                         'yahoo_after_fix': round(a, 2) if a is not None else None})
        out.append({'fund': 'FCNTX', 'source': u, 'periods': '暦年のリターン（%）1998〜2007', 'rows': rows,
                    'max_abs_diff_before_fix': round(max(abs(r['yahoo_before_fix'] - r['official']) for r in rows), 2),
                    'max_abs_diff_after_fix': round(max(abs(r['yahoo_after_fix'] - r['official']) for r in rows), 2)})
    else:
        out.append({'fund': 'FCNTX', 'source': u, 'error': '公表値が読めない'})
    return out


def data_check(R, spy):
    """Yahoo の配当込みの月次が、運用会社の公表（SEC の目論見書 485BPOS・2026-04-22）と合うかの検算"""
    u = 'https://www.sec.gov/Archives/edgar/data/29440/000119312526169303/d21586d485bpos.htm'
    t = sec_get(u, 'sec_dodge_485bpos_2026.htm').decode('utf-8', 'replace')
    t = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', t)).replace('\xa0', ' '))
    out = []
    for tick, label in [('DODGX', 'Dodge & Cox Stock – Class I'), ('DODFX', 'Dodge & Cox International Stock – Class I')]:
        m = re.search(re.escape('Periods Ended 12/31/2025 ' + label) + r' 1 Year 5 Years 10 Years Return before taxes ([\d.]+) % ([\d.]+) % ([\d.]+) %', t)
        if not m or tick not in R:
            out.append({'fund': tick, 'error': '公表値か系列が読めない'}); continue
        r = R[tick]
        one = (math.prod(1 + r[k] for k in months(202501, 202512)) - 1) * 100
        five = cagr_window(r, 202101, 202512) * 100
        ten = cagr_window(r, 201601, 202512) * 100
        out.append({'fund': tick, 'official_1y_5y_10y_to_2025': [float(m.group(1)), float(m.group(2)), float(m.group(3))],
                    'yahoo_1y_5y_10y_to_2025': [round(one, 2), round(five, 2), round(ten, 2)]})
    m = re.search(r'S&P 500 Index \(reflects no deduction for expenses or taxes\) ([\d.]+) ([\d.]+) ([\d.]+)', t)
    if m:
        out.append({'fund': 'SPY（相手）', 'sp500_index_official_1y_5y_10y_to_2025': [float(m.group(i)) for i in (1, 2, 3)],
                    'spy_yahoo_1y_5y_10y_to_2025': [round((math.prod(1 + spy[k] for k in months(202501, 202512)) - 1) * 100, 2),
                                                    round(cagr_window(spy, 202101, 202512) * 100, 2), round(cagr_window(spy, 201601, 202512) * 100, 2)],
                    'note': 'SPY は指数より経費（年0.09%前後）と配当の再投資の時差の分だけ低い'})
    return {'source': u, 'rows': out}


def survivorship_note(tA, tB, cgm, sens):
    dead = sens.get('A_with_dead_CGMFX')
    dead_txt = f"CGMFX を入れた感度で A の順位相関が {tA['spearman']}→{dead['spearman']} に上がったのと同じ向き" if dead else 'CGMFX の感度は作れなかった'
    return {
        'what': '生き残りの偏り（消えたファンドが入っていない）',
        'points': [
            '32本は 2026年の今『名の知れた長期のファンド』として選ばれた＝今まで生き残り、名が残った本だけ。2006年や1996年の時点で有名だったが、その後に消えた・名を失ったファンドは入っていない',
            f'32本のうち清算で系列が無いのは CGMFX の1本だけ（3%・{cgm.get("liquidation_date")} ごろ運用停止・SEC 497）。SPIVA では下位1/4 の国内株ファンドの 23.1%・上位1/4 でも 9.8% が5年で合併・清算される（二次資料）＝この一覧は普通の母集団よりはるかに生き残りに偏っている',
            f'偏りの向き: 全体の成績は良く見える（選ばれた理由が過去の成績だから）。SPY に勝った本の割合は 1996〜2005 が {tB["all_beat_spy1_count"]}・2006〜2015 が {tA["all_beat_spy1_count"]}・2016〜2026-09 が {tA["all_beat_spy2_count"]} と、今に近い窓ほど下がる。'
            'これは選ばれ方の偏り（昔の勝ちで名が残った）と合う。ただし 2016年以降は巨大株の相場で能動のファンド全体が SPY に負けやすかった期間（SPIVA の二次資料で 2025年に大型株ファンドの 79% が S&P 500 に負けた）とも重なり、どちらが効いたかは区別できない',
            f'順位相関への影響（推測）: ①負けたファンドほど消える（SPIVA）ので、消えた負け組を入れれば『下位は下位に残る』持続は強まる向き（{dead_txt}） ②一方『今まで通算で良かった本』を選ぶと、片方の窓で負けた本はもう片方で勝っていないと選ばれないので、順位相関は下へゆがむ向き。どちらが大きいかはこの32本では確かめられない',
            '上場廃止のある CRSP の全ファンドで測った文献（Carhart 1997・Fama-French 2010・SPIVA）はこの偏りが無い',
        ]}


def make_summary(o):
    tA, tB, s = o['test_A'], o['test_B'], o['sensitivity']
    bl = {d['period']: d for d in o['berkshire']['letter_decades']}
    by = {d['period']: d for d in o['berkshire']['yahoo_decades']}
    cg = o['cgm_focus_dead_fund']
    reg = s['style_regime']
    dec = s['A_style_decomposition']
    sa, sb = s['A_style_alpha'], s['B_style_alpha']
    av = cg.get('avg_pct', {})
    cg_txt = (f"2000年代の米国株ファンドで1位とされた CGM Focus（『1位』は Morningstar の調べの紹介＝二次資料。2000〜2009 の10年で +{cg['ten_2000_2009']['cum_pct_2000_2009']}%＝年 {cg['ten_2000_2009']['ann_pct_2000_2009']}% は SEC の年次報告書）は、"
              f"重ならない後の10年（2012〜2021）に年 {av.get('fund_10y_to_2021')}%（S&P 500 は {av.get('sp500_10y_to_2021')}%）しか上げず、2022年に清算された"
              f"（2006〜2015 の10年でも年 {cg['ten_2006_2015']['fund_10y_2006_2015']}% 対 {cg['ten_2006_2015']['sp500_10y_2006_2015']}% で負けたが、この窓は 2000年代と4年重なり2008年の大きな負けを両方に含む）。") \
        if cg.get('ten_2000_2009') and cg.get('ten_2006_2015') else ''
    summ = (
        f"名の知れた長期のファンド32本（Berkshire・Fidelity Contrafund・Sequoia・Dodge & Cox など）を、前の10年の成績（SPY との差）で並べ、次の10年も同じ順に並ぶかを見た。"
        f"①2006〜2015 → 2016〜2026-09（{tA['n']}本）: 順位相関は {tA['spearman']}（並べ替えの p={tA['perm_p_two_sided']}）で、予想した0前後ではなく、はっきり続いた。"
        f"前半の上位1/3 は後半に SPY を年 {tA['top_third_ex2_mean']:+}% 上回り（平均・前半は {tA['top_third_ex1_mean']:+}%）、下位1/3 は {tA['bottom_third_ex2_mean']:+}%、差 {tA['top_minus_bottom_ex2']} 点。"
        f"ただし前半の上位1/3 でも後半に SPY に勝ったのは {tA['top_third_beat_spy2_count']} 本だけで、全体では {tA['all_beat_spy2_count']} 本（中央値 {tA['ex2_median']:+}%/年）。"
        f"続いた理由の一部は『型』: 成長株が割安株に勝ち（Vanguard の指数で年 {reg['growth_minus_value_ann_pct']['2006-2015']:+}%→{reg['growth_minus_value_ann_pct']['2016-2026-09']:+}%）、米国外が米国に負け続けた（{reg['intl_minus_us_ann_pct']['2006-2015']:+}%→{reg['intl_minus_us_ann_pct']['2016-2026-09']:+}%）ので、成長株の本が上・割安株と米国外の本が下に並びやすかった。"
        f"ただし後半の超過を、私の型の物差し（成長−割安・小型−大型・米国外−米国・債券）で説明できる部分と説明できない残りに分けると、前半の成績に対する傾き {dec['slope_total']} のうち 型 {dec['slope_style_part']}・残り {dec['slope_alpha_part']} でほぼ半々。"
        f"型で調整したアルファでも順位相関 {sa['spearman']}（p={sa['perm_p_two_sided']}）が残る。残りの半分が運用者の腕なのか、物差しに無い型（品質・低ベータ・勢い）なのかは見分けられない。"
        f"②1996〜2005 → 2006〜2015（{tB['n']}本）: 順位相関は {tB['spearman']}（p={tB['perm_p_two_sided']}）で、むしろ逆向き。前半の上位1/3 の後半の超過は {tB['top_third_ex2_mean']:+}%（前半 {tB['top_third_ex1_mean']:+}%）・下位1/3 は {tB['bottom_third_ex2_mean']:+}%。型で調整したアルファの順位相関は {sb['spearman']}（p={sb['perm_p_two_sided']}）。"
        f"5年ずつの組（事後の参考）でも順位相関は {', '.join(str(c['spearman']) for c in s['five_year_chain']['pairs'])} と符号が入れ替わり、平均 {s['five_year_chain']['mean_spearman']}。"
        f"Berkshire は手紙の表で、S&P 500（配当込み）との差が 1970年代 {bl['1970年代']['diff']:+}・1980年代 {bl['1980年代']['diff']:+}・1990年代 {bl['1990年代']['diff']:+}・2000年代 {bl['2000年代']['diff']:+}・2010年代 {bl['2010年代']['diff']:+}・2016〜2025 {bl['2016〜2025']['diff']:+} 点/年と、大きくなるほど縮んだ。"
        f"Yahoo の月次では 2016-01〜2026-09 が {by['2016-01〜2026-09']['diff']:+} 点/年、2026年1〜9月は累計 {by['2026-01〜2026-09']['diff_cum']:+} 点。"
        f"{cg_txt}"
        f"文献も同じ向き: SPIVA では大型株の上半分が4年続けて上半分に残るのは 4.5%（偶然なら 6.25%）、Carhart の持続は1994年以降に消え（Choi & Zhao）、Buffett の超過も品質・低ベータ・約1.7倍の借入でほぼ説明される。"
        f"結論: 『有名な運用者の後を追えば勝てる』は支持されない（後半の10年に SPY に勝ったのは {tA['all_beat_spy2_count']} 本・1996〜2005→2006〜2015 では順位が逆向き・5年ずつの組では符号が入れ替わる）。"
        f"2006〜2026 で続いて見えた分の約半分は型（成長株・米国株）の流れで、その流れがいつ変わるかは当てられない。残りの半分の正体は見分けられない。")
    pred = (f"予想『順位相関は0前後。上位の勝ちは続かない』。検定 B（1996〜2005→2006〜2015）は順位相関 {tB['spearman']}（p={tB['perm_p_two_sided']}）で当たった。"
            f"主の検定 A（2006〜2015→2016〜2026-09）は順位相関 {tA['spearman']}（p={tA['perm_p_two_sided']}）で外れた（0前後ではない）。"
            f"『上位の勝ちは続かない』は半分当たり: A の上位1/3 の超過は前半 {tA['top_third_ex1_mean']:+}%/年 → 後半 {tA['top_third_ex2_mean']:+}%/年に縮み、SPY に勝ったのは {tA['top_third_beat_spy2_count']}。"
            f"B の上位1/3 は {tB['top_third_ex1_mean']:+}% → {tB['top_third_ex2_mean']:+}%。"
            f"A の持続のうち型（成長株・米国株）の流れで説明できるのは約半分で、型を調整しても順位相関 {sa['spearman']}（p={sa['perm_p_two_sided']}）が残る（B は {sb['spearman']}・p={sb['perm_p_two_sided']}）。"
            "この残りが腕か、私の物差しに無い型（品質・低ベータ・勢い）かは見分けられない（型の調整は事後の追加）。")
    return summ, pred


def build_fixes(o, fix_events, small_cands, scan_rec, dcf):
    """検証役の指摘（2026-10-12）に対して何をどう直したかの記録"""
    s = o['sensitivity']

    def brief(T):
        return {k: T.get(k) for k in ('n', 'spearman', 'perm_p_two_sided', 'top_third_ex1_mean', 'top_third_ex2_mean', 'bottom_third_ex2_mean',
                                      'top_minus_bottom_ex2', 'top_third_beat_spy2_count', 'all_beat_spy2_count', 'all_beat_spy1_count', 'ex2_median')}

    def row(T, f):
        for r in T['rows']:
            if r['fund'] == f:
                return {'ex1': r['ex1'], 'ex2': r['ex2'], 'third1': r['third1'], 'rank1': r['rank1']}
        return None
    eff = {'A': {'before': brief(s['A_before_fix']), 'phantom_fix_only': brief(s['A_phantom_fix_only']), 'after': brief(o['test_A'])},
           'B': {'before': brief(s['B_before_fix']), 'phantom_fix_only': brief(s['B_phantom_fix_only']), 'after': brief(o['test_B'])}}
    smt = {'A_before': row(s['A_before_fix'], 'SMT.L'), 'A_after': row(o['test_A'], 'SMT.L'),
           'B_before': row(s['B_before_fix'], 'SMT.L'), 'B_after': row(o['test_B'], 'SMT.L')}
    ph = {'VWUSX_A_before': row(s['A_before_fix'], 'VWUSX'), 'VWUSX_A_after': row(s['A_phantom_fix_only'], 'VWUSX'),
          'FCNTX_B_before': row(s['B_before_fix'], 'FCNTX'), 'FCNTX_B_after': row(s['B_phantom_fix_only'], 'FCNTX')}
    dec = s['A_style_decomposition']
    return [
        {'issue': '順位が続いた理由を「主に型」と書いていた（medium）', 'verdict': '指摘は正しい・直した',
         'what_changed': 'summary_ja・prediction_check・for_final_selection(2) を「型で説明できるのは約半分・残り半分は型の物差しでは説明できず、腕か物差しに無い型（品質・低ベータ・勢い）かは見分けられない」に直した。'
                         '後半の超過を型の部分とアルファの部分に分ける分解（sensitivity.A_style_decomposition / B_style_decomposition）を足し、数字は本文から自動で引く',
         'effect': {'A_decomposition': {k: dec.get(k) for k in ('n', 'slope_total', 'slope_style_part', 'slope_alpha_part', 'spearman_ex1_vs_style_part',
                                                               'perm_p_style_part', 'spearman_ex1_vs_alpha_part', 'perm_p_alpha_part', 'identity_max_abs_err')},
                    'A_style_alpha_spearman': s['A_style_alpha']['spearman'], 'A_style_alpha_p': s['A_style_alpha']['perm_p_two_sided'],
                    'A_capm_alpha_spearman': s['A_capm_alpha']['spearman'], 'A_us_only_spearman': s['A_us_only']['spearman'],
                    'A_us_only_p': s['A_us_only']['perm_p_two_sided'],
                    'note': '検証役の再計算（日足の月末値・numpy の最小二乗）では 傾き 1.236＝型 0.622＋アルファ 0.615・型で調整したアルファの順位相関 0.496。'
                            'この道具（Yahoo の月足）では上の数字。データの経路が違うので小数は少しずれるが、どちらも「ほぼ半々」で同じ結論'}},
        {'issue': 'Yahoo の調整後終値に実際には無い分配の調整が入っている月（VWUSX 2019-04・FCNTX 2002-06）（medium）', 'verdict': '指摘は正しい・直した',
         'what_changed': '日足で全31本（と型の物差しの指数ファンド6本）の 1995-12〜2026-09 の分配の事件を機械で点検する phantom_scan を足した（規則は本体の PH_* の頭注）。'
                         '分配率2%以上で基準価額の下げが見えない事件（material）だけ、その月の月次リターンを調整後終値の跳ねの倍率で割り戻した。'
                         '0.5〜2% の候補（small_unconfirmed）は日々の値動きに紛れて見分けられないので直さず名指しし、全部直した場合を sensitivity.*_all_small_candidates_fixed に出した。'
                         '直した2本は運用会社の公表値（SEC）と直す前・直した後で突き合わせた（data_check_vs_prospectus.fixed_funds）',
         'events_fixed': fix_events, 'scan_summary': scan_rec, 'small_unconfirmed_candidates': small_cands,
         'effect': {'VWUSX_and_FCNTX_rows': ph, 'tests_before_vs_phantom_fix_only': {k: {'before': v['before'], 'phantom_fix_only': v['phantom_fix_only']} for k, v in eff.items()},
                    'all_small_candidates_fixed': {'A': brief(s['A_all_small_candidates_fixed']), 'B': brief(s['B_all_small_candidates_fixed']),
                                                   'note': '31本の候補（role=fund）だけを直した上限。型の物差しの指数ファンドの候補（role=style_factor）は検定 A・B には効かず、型で調整したアルファの感度にだけ効く（そちらは直していない）'},
                    'published_check': dcf}},
        {'issue': 'SMT.L の調整後終値に配当がほぼ入っていない（実質は株価だけ）のに「配当込み」と書いていた（medium）', 'verdict': '指摘は正しい・直した',
         'what_changed': '日足の終値（ペンス）に Yahoo の配当の事件（ペンス）を足して配当込みの指数を自分で作り直した（smt_gbp_total_return）。data_sources の書き方も直した。'
                         '取引の無い日の配当は次の取引日に付け、落とさない。窓ごとの配当の上乗せは notes.SMT.L.dividend_check',
         'effect': {'SMT.L_rows': smt}},
        {'issue': 'CGM Focus の「2000年代1位 → 次の10年（2006〜2015）」は窓が4年重なる・「1位」は二次資料だけ（low）', 'verdict': '指摘は正しい・直した',
         'what_changed': '本文の「次の10年」を重ならない 2012〜2021（年 5.68% 対 S&P 500 16.55%・SEC 485BPOS 2022 の XBRL）にし、2006〜2015 は「2000年代と4年重なる」と明記。「1位」は Morningstar の調べの紹介（二次資料）と本文と文献欄に添えた'},
        {'issue': '「今に近い期間ほど SPY に勝てなくなった（選ばれ方の偏りを示す）」は言い過ぎ（low）', 'verdict': '指摘は正しい・直した',
         'what_changed': 'survivorship.points を「選ばれ方の偏りと合う。ただし 2016年以降の巨大株の相場で能動のファンド全体が SPY に負けやすかった期間とも重なり、区別できない」に直した'},
        {'issue': '文献の小さな不正確さ（Fama-French の「時価加重」・Choi & Zhao の本文の数字が未確認）（low）', 'verdict': '直した',
         'what_changed': 'Fama-French の −0.81〜−1.00%/年 を「等加重と時価加重・3因子と4因子の4通りの幅」に直した。Choi & Zhao は本文の PDF（NBER）が今回は読めたので、0.23%/月（p=0.306）・−0.19%/月（p=0.034）を本文4ページと Table 1 で確かめたと記録した。'
                         'あわせて同じ Table 1 で、Carhart の欄の旧記述「4因子では差が消える」が不正確（実際は 0.29%/月・t 2.13 に縮み、残る差は下位10% の負けの側）と分かったので直した（私が見つけたもの）'},
    ]


def main():
    pre = json.load(open(PRE))
    mod = pre['modules']['R6_fund_persistence']
    funds = mod['funds']
    names = {}
    R, notes, unavailable = {}, {}, []
    spy = M.yahoo('SPY')
    for t in funds:
        if t == 'SMT.L':
            usd, gbp, fxchk, outl, smt_old_usd, divchk = smt_usd()
            R[t] = usd
            notes[t] = {'how': 'Yahoo SMT.L の日足の終値（ペンス）に配当の事件（ペンス）を足して作った配当込みの月末値 → GBP の月次リターン × 為替（GBPUSD=X 日足の月末・2003-12 より前は FRED DEXUSUK 月末）でドルへ（2026-10-12 に直した）',
                        'why_not_monthly_bars': 'Yahoo の月足は 2012-10 以前で 5対1 分割の調整が月ごとに揺れ +300%/−80% が交互に出る（実測 1985-03 +376%・1985-04 −80% など）',
                        'why_not_adjclose': 'Yahoo の SMT.L の調整後終値は配当（ペンス）を約100分の1しか調整していない＝実質は株価だけ（検証役の指摘・sample_2016 の adjust と div_pct を比べよ）',
                        'dividend_check': divchk,
                        'fx_splice_check': fxchk, 'gbp_outliers_over_35pct': outl,
                        'gbp_cagr_2016_2026_09': round(cagr_window(gbp, *A2) * 100, 2) if cagr_window(gbp, *A2) is not None else None}
            continue
        try:
            r = M.yahoo(t)
        except Exception as e:  # noqa
            r = {}
            notes[t] = {'error': f'Yahoo に時系列が無い（{type(e).__name__}: {e}）'}
        if not r:
            unavailable.append(t)
            continue
        R[t] = r
    for t in list(R) + ['SPY']:
        p = os.path.join(C, f'yh_{t}_1mo.json')
        if os.path.exists(p):
            try:
                names[t] = json.load(open(p))['chart']['result'][0]['meta'].get('longName')
            except Exception:  # noqa
                pass
    names['SMT.L'] = 'Scottish Mortgage Investment Trust（Yahoo: Scottish Mortgage Ord）'

    # ── Yahoo の『実際には無い分配の調整』を日足で探して直す（2026-10-12 検証役の指摘）
    spy_rows, _ = daily_rows(yahoo_daily_raw('SPY'))
    spyret = {d: c / pc - 1 for (_, pc, _), (d, c, _) in zip(spy_rows, spy_rows[1:])}
    R_raw = {t: dict(r) for t, r in R.items()}
    R_raw['SMT.L'] = smt_old_usd                       # 直す前＝旧の調整後終値（実質株価だけ）
    R_phantom_only = {t: dict(r) for t, r in R.items()}
    R_phantom_only['SMT.L'] = smt_old_usd              # 分配の誤りだけ直し、SMT.L は旧のまま（効果を分けるため）
    R_allcand = {t: dict(r) for t, r in R.items()}     # 0.5〜2% の候補まで全部直した上限（感度）
    scan_rec, fix_events, small_cands = {}, [], []

    def apply_scan(t, series_list, role):
        sc = phantom_scan(t, spyret)
        scan_rec[t] = {'events_checked': sc['events_checked'], 'material': len(sc['material']),
                       'small_unconfirmed': len(sc['small_unconfirmed']), 'role': role}
        for ev in sc['material']:
            k = ev['month']
            if k not in series_list[0]:
                ev['error'] = 'その月の月次リターンが無い'; fix_events.append(ev); continue
            before = series_list[0][k]
            for ser in series_list:
                if k in ser:
                    ser[k] = (1 + ser[k]) / ev['jump_factor'] - 1
            ev.update({'role': role, 'monthly_return_before_pct': round(before * 100, 2),
                       'monthly_return_after_pct': round(series_list[0][k] * 100, 2)})
            fix_events.append(ev)
        for ev in sc['small_unconfirmed']:
            ev['role'] = role
            small_cands.append(ev)
        return sc

    for t in list(R):
        if t == 'SMT.L':
            continue  # 配当込みを自分で作り直した（Yahoo の分配の事件を使っていない）
        sc = apply_scan(t, [R[t], R_phantom_only[t], R_allcand[t]], 'fund')
        for ev in sc['small_unconfirmed']:
            if ev['month'] in R_allcand[t]:
                R_allcand[t][ev['month']] = (1 + R_allcand[t][ev['month']]) / ev['jump_factor'] - 1
        if sc['material']:
            notes.setdefault(t, {})['fix'] = ('Yahoo の調整後終値に実際には無い分配の調整が入っていた月を直した: ' +
                                             '・'.join(f"{e['ex_date']}（分配 {e['amount']}＝基準価額の {e['dist_pct_of_nav']}%・その月 {e['monthly_return_before_pct']}%→{e['monthly_return_after_pct']}%）" for e in sc['material']))
    # BRK-B の 1996-01〜05（上場前）は BRK-A で埋める（同じ会社・後で相関を検算）
    brka, brka_px = yahoo_daily_month_end('BRK-A')
    brkb = R['BRK-B']
    ov = sorted(k for k in set(brka) & set(brkb) if k <= 202609)
    brk_chk = {'overlap_months': len(ov), 'corr': round(M.corr([brka[k] for k in ov], [brkb[k] for k in ov]), 4),
               'mean_abs_diff_pct': round(S.mean(abs(brka[k] - brkb[k]) for k in ov) * 100, 3),
               'brkb_first_month': min(brkb)}
    brkb_filled = dict(brkb)
    filled = []
    for k in months(199001, min(brkb) - 1):
        if k in brka:
            brkb_filled[k] = brka[k]; filled.append(k)
    R_B = dict(R)
    R_B['BRK-B'] = brkb_filled
    R_raw_B = dict(R_raw); R_raw_B['BRK-B'] = brkb_filled
    R_po_B = dict(R_phantom_only); R_po_B['BRK-B'] = brkb_filled
    R_ac_B = dict(R_allcand); R_ac_B['BRK-B'] = brkb_filled
    notes['BRK-B'] = {'test_B_fill': f'検定 B では BRK-B の上場前（{filled[0] if filled else "-"}〜{filled[-1] if filled else "-"}）を BRK-A の月次で埋めた',
                      'brka_brkb_check': brk_chk}
    notes['BPTRX'] = {'caveat': 'Baron Partners は 2003-04-30 に投資信託へ転換。それより前の系列は前身のパートナーシップ（成功報酬20%つき・未登録）の成績の可能性が高い（Baron の開示: https://www.baroncapitalgroup.com/sites/default/files/2025-10/fact-sheet-baron-partners-fund-9.30.2025.pdf ）＝検定 B の前半は器が違う'}
    for t, why in [('FAIRX', '設定 1999-12'), ('FMIHX', '設定 2001-12'), ('DODFX', '設定 2001-05')]:
        notes.setdefault(t, {})['test_B'] = f'{why}＝検定 B の前半（1996〜2005）がそろわない'

    # データの点検: 大きな月次の動き
    outliers = {t: [(k, round(v, 3)) for k, v in r.items() if abs(v) > 0.3 and k >= 199001] for t, r in R.items()}
    outliers = {t: v for t, v in outliers.items() if v}

    # 主の検定
    testA = run_test(R, spy, A1, A2, 'A: 2006-01〜2015-12 → 2016-01〜2026-09（主）')
    testB = run_test(R_B, spy, B1, B2, 'B: 1996-01〜2005-12 → 2006-01〜2015-12（主）')

    # 感度
    sens = {}
    # 直す前のデータ（旧の結果の再現）・分配の誤りだけ直した版・0.5〜2% の候補まで全部直した版
    sens['A_before_fix'] = run_test(R_raw, spy, A1, A2, 'A・直す前のデータ（旧の報告の再現）')
    sens['B_before_fix'] = run_test(R_raw_B, spy, B1, B2, 'B・直す前のデータ（旧の報告の再現）')
    sens['A_phantom_fix_only'] = run_test(R_phantom_only, spy, A1, A2, 'A・分配の誤りだけ直す（SMT.L は旧のまま）', nperm=20000)
    sens['B_phantom_fix_only'] = run_test(R_po_B, spy, B1, B2, 'B・分配の誤りだけ直す（SMT.L は旧のまま）', nperm=20000)
    sens['A_all_small_candidates_fixed'] = run_test(R_allcand, spy, A1, A2, 'A・0.5〜2% の候補まで全部直した上限', nperm=20000)
    sens['B_all_small_candidates_fixed'] = run_test(R_ac_B, spy, B1, B2, 'B・0.5〜2% の候補まで全部直した上限', nperm=20000)
    sens['A_arith'] = run_test(R, spy, A1, A2, 'A・算術の超過', kind='arith', nperm=20000)
    sens['B_arith'] = run_test(R_B, spy, B1, B2, 'B・算術の超過', kind='arith', nperm=20000)
    us = {t for t in R if t not in NON_US_OR_MIXED}
    sens['A_us_only'] = run_test(R, spy, A1, A2, 'A・米国株の本だけ（世界株・米国外・混合を外す）', subset=us, nperm=20000)
    sens['B_us_only'] = run_test(R_B, spy, B1, B2, 'B・米国株の本だけ', subset=us, nperm=20000)
    tb3 = {k: v / 1200 for k, v in G.fred('TB3MS').items()}

    def alpha_test(RR, w1, w2, label):
        nm, x1, x2, betas = [], [], [], {}
        for t, r in RR.items():
            a1, a2 = alpha_capm(r, spy, tb3, *w1), alpha_capm(r, spy, tb3, *w2)
            if a1 is None or a2 is None:
                continue
            nm.append(t); x1.append(a1[0]); x2.append(a2[0]); betas[t] = [round(a1[1], 2), round(a2[1], 2)]
        res = persistence(nm, x1, x2, label, nperm=20000)
        res['measure'] = 'SPY に対する CAPM のアルファ（年率・無リスク金利は FRED TB3MS）'
        res['note_beat'] = 'この感度では *_beat_spy* の欄は『アルファが正』の数（SPY に勝ったかではない）'
        res['betas'] = betas
        return res
    sens['A_capm_alpha'] = alpha_test(R, A1, A2, 'A・ベータを調整したアルファ')
    sens['B_capm_alpha'] = alpha_test(R_B, B1, B2, 'B・ベータを調整したアルファ')
    # 型（成長／割安・小型・米国外・債券）で調整したアルファ（事後の追加: A の結果を見た後に、
    # 『上位も下位も型〔成長株か割安・米国外か〕で並んでいる』と見えたので足した）
    styl = {t: M.yahoo(t) for t in ('VIGRX', 'VIVAX', 'NAESX', 'VEURX', 'VPACX', 'VBMFX')}
    for t, ser in styl.items():   # 型の物差しの指数ファンドにも同じ点検をかける
        apply_scan(t, [ser], 'style_factor')
    vig, viv, nae, veu, vpa, vbm = (styl[t] for t in ('VIGRX', 'VIVAX', 'NAESX', 'VEURX', 'VPACX', 'VBMFX'))
    F = {'_rf': tb3}
    F['mkt'] = {k: spy[k] - tb3[k] for k in spy if k in tb3}
    F['growth_minus_value'] = {k: vig[k] - viv[k] for k in vig if k in viv}
    F['small_minus_large'] = {k: nae[k] - spy[k] for k in nae if k in spy}
    F['intl_minus_us'] = {k: 0.6 * veu[k] + 0.4 * vpa[k] - spy[k] for k in veu if k in vpa and k in spy}
    F['bonds'] = {k: vbm[k] - tb3[k] for k in vbm if k in tb3}

    def style_test(RR, w1, w2, label):
        nm, x1, x2, load = [], [], [], {}
        for t, r in RR.items():
            a1, a2 = alpha_style(r, F, *w1), alpha_style(r, F, *w2)
            if a1 is None or a2 is None:
                continue
            nm.append(t); x1.append(a1[0]); x2.append(a2[0]); load[t] = {'first': a1[1], 'second': a2[1]}
        res = persistence(nm, x1, x2, label, nperm=20000)
        res['measure'] = ('型で調整したアルファ（年率%）: r−rf を SPY−rf・成長−割安（VIGRX−VIVAX）・小型−大型（NAESX−SPY）・'
                          '米国外−米国（0.6 VEURX＋0.4 VPACX−SPY）・債券（VBMFX−rf）に回帰した切片×12')
        res['loadings'] = load
        res['note'] = '事後の追加（事前登録に無い）。米国外の合成の 0.6/0.4 は私の置き値'
        res['note_beat'] = 'この感度では *_beat_spy* の欄は『アルファが正』の数（SPY に勝ったかではない）'
        return res
    sens['A_style_alpha'] = style_test(R, A1, A2, 'A・型で調整したアルファ（事後）')
    sens['B_style_alpha'] = style_test(R_B, B1, B2, 'B・型で調整したアルファ（事後）')

    def style_decomp(RR, w1, w2, label):
        """後半の算術の超過（月次の r−SPY の平均×12）＝ アルファ ＋ 型の部分 に分け、前半の成績（複利の超過）に対する
        傾きと順位相関をそれぞれで出す（検証役の指摘で足した・事後）。
        恒等式: r−SPY ＝ a ＋ (b_mkt−1)(SPY−rf) ＋ Σ b_i F_i ＋ e（切片があるので e の平均は0）"""
        fn = [f for f in F if f != '_rf']
        ks = months(*w2)
        if any(k not in F[f] for f in fn for k in ks):
            return {'label': label, 'error': '型の物差しの月が欠ける'}
        fm = {f: S.mean(F[f][k] for k in ks) for f in fn}
        nm, e1s, ar, st, al = [], [], [], [], []
        for t, r in RR.items():
            e1 = excess(r, spy, *w1)
            if e1 is None or any(k not in r or k not in spy or k not in tb3 for k in ks):
                continue
            c, bs = ols([r[k] - tb3[k] for k in ks], [[F[f][k] for k in ks] for f in fn])
            b = dict(zip(fn, bs))
            stp = ((b['mkt'] - 1) * fm['mkt'] + sum(b[f] * fm[f] for f in fn if f != 'mkt')) * 1200
            nm.append(t); e1s.append(e1); al.append(c * 1200); st.append(stp)
            ar.append(S.mean(r[k] - spy[k] for k in ks) * 1200)

        def slope(x, y):
            mx, my = S.mean(x), S.mean(y)
            return sum((u - mx) * (v - my) for u, v in zip(x, y)) / sum((u - mx) ** 2 for u in x)
        p_st = persistence(nm, e1s, st, 'style part', nperm=20000)
        p_al = persistence(nm, e1s, al, 'alpha part', nperm=20000)
        p_ar = persistence(nm, e1s, ar, 'arith', nperm=20000)
        return {'label': label, 'n': len(nm), 'note': '事後の追加（検証役の指摘・2026-10-12）。前半は複利の超過、後半は算術の超過（月次の差の平均×12）を、私の型の物差しの回帰で分けた',
                'identity_max_abs_err': round(max(abs(a_ - (b_ + c_)) for a_, b_, c_ in zip(ar, st, al)), 10),
                'slope_total': round(slope(e1s, ar), 3), 'slope_style_part': round(slope(e1s, st), 3), 'slope_alpha_part': round(slope(e1s, al), 3),
                'spearman_ex1_vs_arith2': p_ar['spearman'], 'spearman_ex1_vs_style_part': p_st['spearman'], 'perm_p_style_part': p_st['perm_p_two_sided'],
                'spearman_ex1_vs_alpha_part': p_al['spearman'], 'perm_p_alpha_part': p_al['perm_p_two_sided'],
                'var_arith2': round(S.pvariance(ar), 2), 'var_style_part': round(S.pvariance(st), 2), 'var_alpha_part': round(S.pvariance(al), 2),
                'rows': sorted(({'fund': t, 'ex1': round(x, 2), 'arith2': round(a_, 2), 'style_part2': round(b_, 2), 'alpha_part2': round(c_, 2)}
                                for t, x, a_, b_, c_ in zip(nm, e1s, ar, st, al)), key=lambda d: -d['ex1'])}
    sens['A_style_decomposition'] = style_decomp(R, A1, A2, 'A: 後半（2016-01〜2026-09）の超過を型とアルファに分ける')
    sens['B_style_decomposition'] = style_decomp(R_B, B1, B2, 'B: 後半（2006-01〜2015-12）の超過を型とアルファに分ける')
    # 成長−割安の型そのものが前半・後半で続いたか（参考）
    gv = F['growth_minus_value']
    sens['style_regime'] = {
        'growth_minus_value_ann_pct': {lab: round(S.mean(gv[k] for k in months(a, z)) * 12 * 100, 2)
                                       for lab, (a, z) in [('1996-2005', B1), ('2006-2015', A1), ('2016-2026-09', A2)]},
        'intl_minus_us_ann_pct': {lab: round(S.mean(F['intl_minus_us'][k] for k in months(a, z)) * 12 * 100, 2)
                                  for lab, (a, z) in [('1996-2005', B1), ('2006-2015', A1), ('2016-2026-09', A2)]},
        'note': '算術の年率（月次の差の平均×12）。Vanguard の指数ファンド（費用込み）で作った近似'}
    # 5年→5年（事後の追加・参考）
    chain = []
    for w1, w2 in [((199601, 200012), (200101, 200512)), ((200101, 200512), (200601, 201012)),
                   ((200601, 201012), (201101, 201512)), ((201101, 201512), (201601, 202012)),
                   ((201601, 202012), (202101, 202609))]:
        RR = R_B if w1[0] < 199606 else R
        t_ = run_test(RR, spy, w1, w2, f'{w1[0]}〜{w1[1]} → {w2[0]}〜{w2[1]}', nperm=20000)
        chain.append({k: t_[k] for k in ('label', 'n', 'spearman', 'perm_p_two_sided', 'top_minus_bottom_ex2',
                                          'top_minus_bottom_perm_p', 'top_third_beat_spy2_count', 'all_beat_spy2_count')})
    sens['five_year_chain'] = {'note': '事後の追加（事前登録に無い・参考）。重ならない5年の組を順に', 'pairs': chain,
                               'mean_spearman': round(S.mean(c['spearman'] for c in chain), 3)}
    # 消えたファンド（CGMFX）を入れる
    cgm = cgm_focus()
    cgm_extra = None
    if cgm['ten_2006_2015'] and all(y in cgm['annual_pct'] for y in range(2016, 2022)) and cgm['h1_2022_pct'] is not None:
        spy1 = cagr_window(spy, *A1) * 100
        e1 = cgm['ten_2006_2015']['fund_10y_2006_2015'] - spy1
        w = 1.0
        for y in range(2016, 2022):
            w *= 1 + cgm['annual_pct'][y] / 100
        w *= 1 + cgm['h1_2022_pct'] / 100
        for k in months(202207, 202609):     # 清算の後は SPY へ乗り換えたと置く（2022-07〜11 の実績は不明＝SPY と同じと置く）
            w *= 1 + spy[k]
        f2 = w ** (12 / len(months(*A2))) - 1
        e2 = (f2 - cagr_window(spy, *A2)) * 100
        cgm_extra = {'CGMFX': (e1, e2)}
        cgm['test_A_inputs'] = {'ex1_pct': round(e1, 2), 'ex2_pct': round(e2, 2),
                                'assumption': '2006〜2015 は目論見書の10年平均 4.54%（S&P 500 7.30%）と SPY の年率の差。2016-01〜2026-09 は 2016〜2021 の年次・2022 上半期 −10.9%・2022-07 以降は SPY（清算の手取りを SPY へ）'}
        sens['A_with_dead_CGMFX'] = run_test(R, spy, A1, A2, 'A・清算された CGMFX を入れる', extra=cgm_extra, nperm=20000)

    # 全期間の成績（参考）
    full = []
    for t, r in R.items():
        row = {'fund': t, 'name': names.get(t), 'first_month': min(r)}
        for lab, (a, z) in [('2006_2026', (200601, 202609)), ('1996_2026', (199601, 202609)), ('2016_2026', A2), ('2006_2015', A1)]:
            e = excess(r, spy, a, z)
            row[f'ex_{lab}'] = round(e, 2) if e is not None else None
        full.append(row)
    full.sort(key=lambda d: -(d['ex_2016_2026'] if d['ex_2016_2026'] is not None else -99))

    # Berkshire
    rows, comp, burl = brk_letter()
    dec, roll = letter_decades(rows)
    # Yahoo 月次での10年ごと
    ff_mkt, _ = G.french_mkt()
    sptr = M.yahoo('^SP500TR')
    brkb_y = R['BRK-B']
    ydec = []
    for lab, a, z, ser, bench, bname in [
            ('1980年代（1980-04〜1989-12）', 198004, 198912, brka, ff_mkt, 'French の米国市場（CRSP 時価加重・配当込み）※SPY も S&P500 配当込み指数も Yahoo に無い'),
            ('1988-02〜1989-12', 198802, 198912, brka, sptr, '^SP500TR'),
            ('1990年代', 199001, 199912, brka, sptr, '^SP500TR'),
            ('2000年代', 200001, 200912, brkb_y, spy, 'SPY'),
            ('2010年代', 201001, 201912, brkb_y, spy, 'SPY'),
            ('2016-01〜2026-09', 201601, 202609, brkb_y, spy, 'SPY'),
            ('2020-01〜2026-09', 202001, 202609, brkb_y, spy, 'SPY'),
            ('2026-01〜2026-09', 202601, 202609, brkb_y, spy, 'SPY')]:
        ks = months(a, z)
        if any(k not in ser or k not in bench for k in ks):
            ydec.append({'period': lab, 'error': '月が欠ける'}); continue
        if len(ks) < 12:   # 1年未満は年率に直さず、その期間の累計で
            c1 = math.prod(1 + ser[k] for k in ks) - 1
            c2 = math.prod(1 + bench[k] for k in ks) - 1
            ydec.append({'period': lab, 'series': 'BRK-A' if ser is brka else 'BRK-B', 'bench': bname, 'months': len(ks),
                         'brk_cum': round(c1 * 100, 2), 'bench_cum': round(c2 * 100, 2), 'diff_cum': round((c1 - c2) * 100, 2),
                         'note': '1年未満なので年率にしない（累計）'})
            continue
        g1 = math.exp(math.fsum(math.log1p(ser[k]) for k in ks) * 12 / len(ks)) - 1
        g2 = math.exp(math.fsum(math.log1p(bench[k]) for k in ks) * 12 / len(ks)) - 1
        st = M.excess_stats(ser, bench, a, z) if len(ks) >= 24 else None
        ydec.append({'period': lab, 'series': 'BRK-A' if ser is brka else 'BRK-B', 'bench': bname, 'months': len(ks),
                     'brk_cagr': round(g1 * 100, 2), 'bench_cagr': round(g2 * 100, 2), 'diff': round((g1 - g2) * 100, 2),
                     'nw_t_of_monthly_diff': st['t'] if st else None, 'beta': st['beta'] if st else None,
                     'vol_brk': st['vol_s'] if st else None, 'vol_bench': st['vol_b'] if st else None})
    # 年次の検算（Yahoo の BRK-A の暦年リターンと手紙）
    yr_chk = []
    for y in range(1981, 2026):
        ks = months(y * 100 + 1, y * 100 + 12)
        if all(k in brka for k in ks):
            v = (math.prod(1 + brka[k] for k in ks) - 1) * 100
            yr_chk.append((y, round(v, 1), rows.get(y, (None,))[0]))
    diffs = [abs(a - b) for _, a, b in yr_chk if b is not None]
    berk = {'letter_url': burl, 'letter_note': '2025年の株主への手紙（2026-02-28）末尾の表『Berkshire’s Performance vs. the S&P 500』（1株あたりの時価の変化と S&P 500 配当込み）',
            'letter_compounded_1965_2025': comp, 'letter_decades': dec, 'letter_rolling_10y': roll,
            'yahoo_decades': ydec,
            'yahoo_vs_letter_annual_check': {'years': len(yr_chk), 'max_abs_diff_pt': round(max(diffs), 2) if diffs else None,
                                             'median_abs_diff_pt': round(S.median(diffs), 2) if diffs else None}}

    out = {
        'module': 'R6', 'prereg': 'out/bestpf_prereg.json', 'prereg_commit': '7c4b672', 'tool': 'night/bestpf_fund_persistence.py',
        'generated': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'question': mod['q'], 'prediction': mod['prediction'], 'funds_prereg': funds,
        'data_sources': {
            'funds': 'Yahoo Finance chart API の調整後終値（配当・分配金込み）の月次（mw_common.yahoo）。ただし実際には無い分配の調整が入っていた2か月（VWUSX 2019-04・FCNTX 2002-06）は日足の点検で見つけて直した（fixes_applied）。'
                     'SMT.L は日足の終値＋配当の事件（ペンス）から自分で作った配当込み（Yahoo の調整後終値は配当がほぼ入っていないため）。BRK-A は日足の調整後終値の月末値（配当なし）',
            'spy': 'Yahoo SPY の調整後終値（配当込み）',
            'fx': 'Yahoo GBPUSD=X 日足の月末（2003-12〜）＋ FRED DEXUSUK 日次の月末（それより前）',
            'rf': 'FRED TB3MS（CAPM の感度だけ）', 'french': 'Ken French F-F_Research_Data_Factors（Mkt-RF+RF・Berkshire の1980年代の比較だけ）',
            'berkshire_letter': burl, 'cgm_sec': cgm['sources']},
        'names': names, 'notes': notes, 'unavailable': {t: 'Yahoo に時系列が無い（清算・SEC 497 2022-09-30）' for t in unavailable},
        'monthly_moves_over_30pct_since_1990': outliers,
        'test_A': testA, 'test_B': testB, 'sensitivity': sens, 'cgm_focus_dead_fund': cgm,
        'full_period_excess_vs_spy': full, 'berkshire': berk, 'literature': LIT,
        'survivorship': survivorship_note(testA, testB, cgm, sens),
        'data_check_vs_prospectus': data_check(R, spy),
        'phantom_distribution_scan': {'rule': {'range': list(PH_RANGE), 'material_dist_pct_of_nav': PH_MATERIAL * 100,
                                               'small_dist_pct_of_nav': PH_SMALL * 100, 'drop_share_threshold': PH_DROP, 'window_trading_days': PH_WIN},
                                      'per_fund': scan_rec, 'fixed_events': len(fix_events), 'small_unconfirmed': len(small_cands)},
    }
    dcf = data_check_fixed(R, R_raw)
    out['data_check_vs_prospectus']['fixed_funds'] = dcf
    out['summary_ja'], out['prediction_check'] = make_summary(out)
    out['deviations'] = DEVIATIONS
    out['caveats'] = CAVEATS
    out['for_final_selection'] = for_final(out)
    out['fixes_applied'] = build_fixes(out, fix_events, small_cands, scan_rec, dcf)
    json.dump(out, open(OUT + '.part', 'w'), ensure_ascii=False, indent=1)
    os.replace(OUT + '.part', OUT)
    # 画面へ要点
    for T in (testA, testB):
        print(T['label'], 'n', T['n'], 'rho', T['spearman'], 'p', T['perm_p_two_sided'], 'top-bot', T['top_minus_bottom_ex2'],
              'p', T['top_minus_bottom_perm_p'], 'top beat', T['top_third_beat_spy2_count'], 'all beat', T['all_beat_spy2_count'],
              'excluded', [e['fund'] for e in T['excluded']])
    for k, v in sens.items():
        if 'spearman' in v:
            print(k, 'n', v['n'], 'rho', v['spearman'], 'p', v['perm_p_two_sided'], 'top-bot', v['top_minus_bottom_ex2'], v['top_third_beat_spy2_count'])
    print('chain', [(c['label'], c['n'], c['spearman']) for c in chain])
    print('berk letter', [(d['period'], d['diff']) for d in dec])
    print('berk yahoo', [(d['period'], d.get('diff', d.get('diff_cum'))) for d in ydec])
    print('yr check', berk['yahoo_vs_letter_annual_check'])
    print('fixed events', [(e['fund'], e['ex_date'], e.get('monthly_return_before_pct'), e.get('monthly_return_after_pct')) for e in fix_events])
    print('small candidates', [(e['fund'], e['ex_date'], e['dist_pct_of_nav']) for e in small_cands])
    print('decomp A', {k: sens['A_style_decomposition'].get(k) for k in ('n', 'slope_total', 'slope_style_part', 'slope_alpha_part', 'spearman_ex1_vs_style_part', 'spearman_ex1_vs_alpha_part', 'identity_max_abs_err')})
    print('decomp B', {k: sens['B_style_decomposition'].get(k) for k in ('n', 'slope_total', 'slope_style_part', 'slope_alpha_part', 'spearman_ex1_vs_style_part', 'spearman_ex1_vs_alpha_part')})
    print('published check', json.dumps(dcf, ensure_ascii=False)[:1500])


if __name__ == '__main__':
    main()
