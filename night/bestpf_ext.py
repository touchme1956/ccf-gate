#!/usr/bin/env python3
"""night/bestpf_ext.py — R7: 株の ETF 7本（MTUM・QUAL・XLI・XLF・XLY・EPI・GRID）を etf_forward_rank と同じ物差しで測る（2026-10-12）

読むだけ。門・採点・配分には触れない。事前登録 out/bestpf_prereg.json（7c4b672）の modules.R7_ext_assets:
  「etf_forward_rank と同じ計算（A1・A2 の実績〔設定前は事前に名指しした代理〕・B・C）。代理は重なる期間の相関≥0.90 のときだけ使う。
    満たせない本は候補から外して名指しする」

やり方（night/etf_forward_rank.py＝R を**書き換えない**）
  1. R を import し、R.C・R.DATA・R.JPM_MAP・R.GMO_MAP・R.VG_MAP に新しい本を**足して**（既存の値は1つも変えない）R.main(write=False) を回す。
     R が読む ETF の中身のファイルは、既存の out/etf_forward_profiles.json を書き換えず、写しに新しい本を足したものを
     out/_bestpf_cache/R7/base/out/ に置き、R.BASE をその間だけそこへ向ける。代理の系列は M.yahoo の前に一枚かませて渡す。
     SEC の SIC の取得は industry_exposure.sic_lookup をそのまま使い、書き込み先（SICF）は写しへ・User-Agent は
     night/mw_best_ideas_13f.py の SEC_UA へ向ける（既存の out/sic_by_cik.json を書き換えない）。
  2. R.main の世界B は、業種（sector）・型（style）の集合が関数の中に固定されていて新しい本を入れられない
     （新しい本は『地域・市場全体＝上乗せなし』に落ちる）。そこで世界B（とBに依る世界C・感度）だけは、R の式を
     そのまま写した関数で新しい本について計算し直す。写しが正しいことは、既存の25本で R.main の値と
     **1e-12 以内で一致**することで確かめる（回帰の検査③）。
  3. 回帰の検査: ① R.main（拡張なし）が out/etf_forward_rank.json の表と一致するか
                 ② 拡張した R.main の既存25本が ① と1ビットも違わないか ③ 写しの世界B・Cが既存25本で一致するか

代理（測る前に固定: out/_bestpf_cache/R7/plan_before_measure.json・2026-10-12 09:40 UTC・sha256 a432e7f1…）
  MTUM（2013-04 まで）… French 6_Portfolios_ME_Prior_12_2 の BIG HiPRIOR（時価加重）− MTUM の経費率/12
  QUAL（2013-07 まで）… French の BIG HiOP（MOAT と同じ代理）− QUAL の経費率/12
  EPI （2008-02 まで）… JKP のインド市場 jkp_mkt('ind','vw')（超過）＋ French の RF − EPI の経費率/12
                         （^BSESN は配当を含まない価格指数で、ドルへ直す為替の月足が 2000 年まで遡れるか分からないので使わない）
                         既存の EPI の行は R のまま残し、代理つなぎの版を EPI_LONG として足す（回帰の検査で既存を守るため）
  GRID（2009-11 まで）… GRID の今の保有（AV 2026-10-09）を French 49業種へ割り当てた重みで、49業種（米国・時価加重）を混ぜる
                         − GRID の経費率/12。米国上場＝SEC の SIC→Siccodes49（R の ind_of と同じ）、米国外上場＝会社名から手で（HAND）
  XLI・XLF・XLY は 1998-12 からあるので代理なし。
  代理は重なる月（代理を使う最後の月より後・24か月以上）の相関 ≥ 0.90 のときだけ使う。満たさない本は A1 の毎月の値をそろえない
  （A2 が本物で埋まる本は、R の SAME_WINDOW と同じく『同じ窓の SPY との差』の A1 を参考に出し、組み合わせからは外れる）。

出力: out/bestpf_ext.json。night/bestpf_eval.py は rank_result() を呼ぶ（R.main(write=False) と同じ形 {rows, chains, spy, doc}）。

2026-10-12 検証役の指摘への手当て（出力の fixes_applied）
  - 世界C: JPM 2026 LTCMA には勢いの行（U.S. Equity Momentum Factor 7.60%）がある。主は指示どおり米国大型 6.7%、勢いの行は感度
    （MTUM_world_C_JPM_sensitivity）。環境変数 BESTPF_R7_MTUM_JPM=MOMENTUM で主を切り替えられる。
  - MTUM の回転率 116% の出典（iShares の 497K・2025-11-28）を足した。top_industries が上位6業種で切ってあることと、全業種の Chips の比重を出した。
"""
import copy, datetime, gzip, hashlib, json, math, os, shutil, sys, time, statistics as S
from contextlib import contextmanager

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etf_forward_rank as R            # noqa: E402
import mw_common as M                   # noqa: E402
import industry_exposure as IE          # noqa: E402
from industry_trends import ff49_map    # noqa: E402
from mw_best_ideas_13f import SEC_UA    # noqa: E402

OUT = os.path.join(BASE, 'out', 'bestpf_ext.json')
PREREG = 'out/bestpf_prereg.json（7c4b672）modules.R7_ext_assets'
CDIR = os.path.join(BASE, 'out', '_bestpf_cache', 'R7')
AV_RAW = os.path.join(CDIR, 'av_etf_profile_2026-10-12.json')
PLAN = os.path.join(CDIR, 'plan_before_measure.json')
FAKE_BASE = os.path.join(CDIR, 'base')
SICF_COPY = os.path.join(CDIR, 'sic_by_cik_copy.json')
GATE = 0.90
MIN_OVERLAP = 24

# ── 新しい本（R.C と同じ形）。GRID の k・JPM は米国上場の比 s で後から決める ──
NEW = {
    'MTUM':     dict(ja='米国モメンタム（勢い）', veh='MTUM', us=True, k=0.10, jpm='USL', gmo=[('USL', 1)], kind='style'),   # jpm は下の MTUM_JPM で決める
    'QUAL':     dict(ja='米国クオリティ（質）', veh='QUAL', us=True, k=0.10, jpm='QUALITY', gmo=[('USL', 1)], kind='style'),
    'XLI':      dict(ja='米国資本財', veh='XLI', us=True, k=0.10, jpm='USL', gmo=[('USL', 1)], kind='sector'),
    'XLF':      dict(ja='米国金融', veh='XLF', us=True, k=0.10, jpm='USL', gmo=[('USL', 1)], kind='sector'),
    'XLY':      dict(ja='米国一般消費財', veh='XLY', us=True, k=0.10, jpm='USL', gmo=[('USL', 1)], kind='sector'),
    'EPI_LONG': dict(ja='インド株（A1 は JKP インド市場の代理つなぎ）', veh='EPI', us=False, k=0.20, jpm='ASIAxJ', gmo=[('EM', 1)],
                     vg=[('EM', 1)], kind='region'),
    'GRID':     dict(ja='送電・電化（スマートグリッド）', veh='GRID', us=True, k=None, jpm='GRID_MIX', gmo=None, vg=None, kind='sector'),
}
# データの器: (主のティッカー, 代理の名前, 代理を使う最後の月)
NEW_DATA = {'MTUM': ('MTUM', 'BESTPF_PX_MTUM', 201304), 'QUAL': ('QUAL', 'BESTPF_PX_QUAL', 201307),
            'XLI': ('XLI', None, None), 'XLF': ('XLF', None, None), 'XLY': ('XLY', None, None),
            'EPI_LONG': ('EPI', 'BESTPF_PX_EPI', 200802), 'GRID': ('GRID', 'BESTPF_PX_GRID', 200911)}
PROXY_FORM = {
    'MTUM': "French 6_Portfolios_ME_Prior_12_2 の BIG HiPRIOR（Average Value Weighted Returns）− MTUM の経費率/12",
    'QUAL': "French 6_Portfolios_ME_OP_2x3 の BIG HiOP（Average Value Weighted Returns）− QUAL の経費率/12（MOAT と同じ代理）",
    'EPI_LONG': "JKP インド市場 jkp_mkt('ind','vw')（RF を超える分）＋ French F-F_Research_Data_Factors の RF − EPI の経費率/12",
    'GRID': "GRID の今の保有を French 49業種へ割り当てた重みで、49業種（米国・Average Value Weighted Returns）を混ぜる − GRID の経費率/12",
}
# GRID の米国外上場の保有（AV では symbol が n/a）→ French 49業種（会社名から手で・測る前に固定）。None＝割り当てない
HAND = {
    'SCHNEIDER ELECTRIC SE': 'ElcEq', 'ABB LTD': 'ElcEq', 'PRYSMIAN SPA': 'ElcEq', 'HD HYUNDAI ELECTRIC': 'ElcEq',
    'LS ELECTRIC CO LTD': 'ElcEq', 'SIEMENS AG': 'ElcEq', 'NKT AS': 'ElcEq', 'FORTUNE ELECTRIC CO LTD': 'ElcEq', 'NEXANS': 'ElcEq',
    'HITACHI LTD': 'ElcEq', 'MEIDENSHA CORP': 'ElcEq', 'MITSUBISHI ELECTRIC CORP': 'ElcEq', 'VOLTRONIC POWER TECHNOLOGY CORP': 'ElcEq',
    'PANASONIC HOLDINGS CORP': 'ElcEq', 'TAIHAN CABLE AND SOLUTION CO LTD': 'ElcEq', 'FUJIKURA LTD': 'ElcEq',
    'SHIHLIN ELECTRIC & ENGINEERING CORP': 'ElcEq', 'SANIL ELECTRICAL CO LTD': 'ElcEq', 'DAIHEN CORP': 'ElcEq',
    'CENERGY HOLDINGS SA': 'ElcEq', 'SUMITOMO ELECTRIC INDUSTRIES LTD': 'ElcEq', 'LEGRAND SA': 'ElcEq', 'SMA SOLAR TECHNOLOGY AG': 'ElcEq',
    'LANDIS&GYR GROUP AG': 'ElcEq', 'ILJIN ELECTRIC CO LTD': 'ElcEq', 'WASION HOLDINGS LTD': 'ElcEq', 'TA YA ELECTRIC WIRE & CABLE': 'ElcEq',
    'ALLIS ELECTRIC CO LTD': 'ElcEq', 'SAMSUNG SDI CO LTD': 'ElcEq', 'WEG SA': 'ElcEq', 'FURUKAWA ELECTRIC CO LTD': 'ElcEq',
    'PFISTERER HOLDING SE ORDINARY SHARES': 'ElcEq', 'TAKAOKA TOKO CO LTD': 'ElcEq', 'FUJI ELECTRIC CO LTD': 'ElcEq',
    'OSAKI ELECTRIC CO LTD': 'ElcEq', 'ALFEN NV': 'ElcEq', 'NGK CORP': 'ElcEq', 'LS ECO ENERGY': 'ElcEq',
    'CHUNG-HSIN ELECTRIC & MACHINERY MFG CORP': 'ElcEq', 'TATUNG CO LTD': 'ElcEq', 'GS YUASA CORP': 'ElcEq', 'AZBIL CORP': 'ElcEq',
    'R&S GROUP HOLDING AG': 'ElcEq', 'ASTOR ENERJI AS': 'ElcEq',
    'NATIONAL GRID PLC': 'Util', 'E.ON SE': 'Util', 'TERNA SPA': 'Util', 'HYDRO ONE LTD': 'Util', 'EQUATORIAL SA': 'Util',
    'ELIA GROUP SA/NV': 'Util', 'REDEIA CORPORACION SA': 'Util', 'IBERDROLA SA': 'Util', 'CIA PARANAENSE DE ENERGIA COPEL': 'Util',
    'ENEL SPA': 'Util', 'ENGIE SA': 'Util', 'ISA ENERGIA BRASIL 0%': 'Util', 'REN-REDES ENERGETICAS NACIONAIS SGPS SA': 'Util',
    'SSE PLC': 'Util', 'EDP-ENERGIAS DE PORTUGAL SA': 'Util', 'VERBUND AG CLASS A': 'Util', 'BKW AG': 'Util',
    'INFINEON TECHNOLOGIES AG': 'Chips', 'RENESAS ELECTRONICS CORP': 'Chips', 'SAP SE': 'Softw', 'SPIE SA': 'Cnstr',
    'BELIMO HOLDING AG': 'Mach', 'BYD CO LTD CLASS H': 'Autos', 'ADVANTECH CO LTD': 'Hardw', 'STELLA-JONES INC': None,
}
CASH_WORDS = ('CASH', 'DOLLAR', 'POUND', 'STERLING', 'EURO', 'FRANC', 'WON', 'REAL', 'CURRENCY', 'DREYFUS', 'MONEY MARKET',
              'FUTURE', 'EMINI', 'XCME', 'HONG KONG')

# ── 世界C: MTUM に当てる JPM の行（2026-10-12 検証役の指摘を受けて足した）──
# JPM 2026 LTCMA（USD）には勢いの行がある。R の JPM には無いので、ここに出典つきで持つ（R は書き換えない）。
# 主は指示どおり米国大型（USL 6.7%・控えめな側）。環境変数 BESTPF_R7_MTUM_JPM=MOMENTUM で勢いの行（7.6%）へ1語で切り替わる
# （そのときは R.JPM に 'MOMENTUM' を**足すだけ**・既存のキーは変えない）。どちらを主にしても、もう一方を感度として出力に出す。
JPM_SRC = dict(url='https://am.jpmorgan.com/content/dam/jpm-am-aem/global/en/insights/ltcma-2026-us-matrix_usd.pdf',
               sha256='e97b01ac723f6fd162ebe741f876d3e1c8a194148ebf4eb2b09196e45aa43ba8', fetched='2026-10-12',
               column='Compound Return 2026 (%)（各行の最初の数字。U.S. Inflation 2.50 / 2.52 / 1.77 / 2.40 の並び＝複利2026・算術2026・ぶれ・複利2025 で列の順を確かめた）',
               rows={'U.S. Large Cap': 6.70, 'U.S. Equity Momentum Factor': 7.60, 'U.S. Equity Quality Factor': 6.60,
                     'U.S. Equity Value Factor': 7.70},
               cache='out/_bestpf_cache/R7/dl_jpm/ltcma-2026-us-matrix_usd.pdf（pdftotext -layout で読んだ）')
JPM_EXTRA = {'MOMENTUM': 7.6}
MTUM_JPM = os.environ.get('BESTPF_R7_MTUM_JPM', 'USL').strip().upper()
assert MTUM_JPM in ('USL', 'MOMENTUM'), f'BESTPF_R7_MTUM_JPM は USL か MOMENTUM（{MTUM_JPM}）'
MTUM_JPM_ALT = 'MOMENTUM' if MTUM_JPM == 'USL' else 'USL'

# ── MTUM の売買の多さ（回転率）の出典（2026-10-12 検証役の指摘を受けて確かめた）──
TURNOVER_SRC = {
    'MTUM': dict(
        prospectus_2025=dict(value=1.16, text="During the most recent fiscal year, the Fund's portfolio turnover rate was 116% of the average value of its portfolio.",
                             doc='iShares MSCI USA Momentum Factor ETF Summary Prospectus（497K・2025-11-28 提出・目論見書は 2025-11-28 付）',
                             url='https://www.sec.gov/Archives/edgar/data/1100663/000119312525302119/d28465d497k.htm',
                             fiscal_year='「直近の会計年度」（終わりの日はこの書類に書かれていない。同じ書類の指数の数字は 2025-07-31 時点）'),
        prospectus_2024=dict(value=0.95, text="… the Fund's portfolio turnover rate was 95% of the average value of its portfolio.",
                             url='https://www.sec.gov/Archives/edgar/data/1100663/000119312524268058/d834555d497k.htm',
                             doc='同 Summary Prospectus（497K・2024-11-29 提出）'),
        alpha_vantage=dict(value=1.16, src='Alpha Vantage ETF_PROFILE の portfolio_turnover（2026-10-09 時点・out/_bestpf_cache/R7/av_etf_profile_2026-10-12.json の turnover）'),
        method_2025=('MSCI USA Momentum SR Variant Index: 6か月と12か月の勢い（3か月国債を超えたリターン÷過去3年の週次のぶれ）を平均した点数の上位125社を、'
                     '点数×時価総額で重み付け（1社5%まで）。四半期ごとに入れ替え、1回の片道の入れ替えは30%まで（同じ 497K・2025-11-28 の Principal Investment Strategies）'),
        search='SEC 全文検索（efts.sec.gov・forms=497K・"iShares MSCI USA Momentum Factor ETF" "portfolio turnover rate"・2024-01-01〜2026-10-12）で4件。最新の2件を読んだ'),
}


def log(*a):
    print(*a, flush=True)


# ───────────────────────── 中身（ETF_PROFILE）─────────────────────────
def av_profiles():
    """AV の写し（gitignore の置き場）。無ければ out/bestpf_ext.json に同梱した写しから（別の機械でも rank_result が回るように）"""
    if os.path.exists(AV_RAW):
        return json.load(open(AV_RAW))['etfs']
    return json.load(open(OUT))['inputs_av_profiles']['etfs']


def holdings_for_R(t, p):
    """AV の holdings を R の prof_new の形 [[ticker, w], …] へ。symbol が n/a の行:
    現金・先物・通貨は n/a のまま（R の holdings_of が落とす）／会社名の行は '*会社名'（米国外上場＝SIC が無く未分類に数えられる）／
    名前の無い行（GRID の 'n/a'）は '*UNKNOWN#i'（AV の旧版で『*その他』だった行と同じ重みの並び＝米国外の株と読む）"""
    out, unk = [], 0
    for h in p['holdings']:
        s, w = h[0], h[1]
        if s != 'n/a':
            out.append([s, w])
            continue
        desc = h[2] if len(h) > 2 else ''
        if desc == 'n/a' or not desc:
            if t == 'GRID':
                unk += 1
                out.append([f'*UNKNOWN#{unk}', w])
            else:
                out.append(['n/a', w])
        elif any(x in desc.upper() for x in CASH_WORDS):
            out.append(['n/a', w])
        else:
            out.append(['*' + desc, w])
    return out


def build_fake_base(av):
    """R が読む2つの中身のファイルの写し（新しい本を足した）を FAKE_BASE/out/ に置く。既存のファイルは読むだけ"""
    od = os.path.join(FAKE_BASE, 'out')
    os.makedirs(od, exist_ok=True)
    shutil.copyfile(os.path.join(BASE, 'out', 'etf_profiles.json'), os.path.join(od, 'etf_profiles.json'))
    pn = json.load(open(os.path.join(BASE, 'out', 'etf_forward_profiles.json')))
    add = {}
    for t in ('MTUM', 'QUAL', 'XLI', 'XLF', 'XLY', 'GRID'):
        p = av[t]
        hs = holdings_for_R(t, p)
        add[t] = dict(er=p['er'], dy=p['dy'], inception=p['inception'], last_updated=p['last_updated'], net_assets=p['net_assets'],
                      n=len(p['holdings']), sectors=p['sectors'], holdings=hs,
                      src='R7: Alpha Vantage ETF_PROFILE（MCP）2026-10-12 採取 → out/_bestpf_cache/R7/av_etf_profile_2026-10-12.json')
    epi = copy.deepcopy(pn['etfs']['EPI'])
    epi['src'] = 'R7: out/etf_forward_profiles.json の EPI の写し（EPI_LONG の経費率・配当利回り）'
    add['EPI_LONG'] = epi
    clash = [t for t in add if t in pn['etfs']]
    assert not clash, f'既存の中身と名前がぶつかる: {clash}'
    pn['etfs'].update(add)
    pn['note_R7'] = 'R7（night/bestpf_ext.py）の写し。新しい本を足しただけ。正本は out/etf_forward_profiles.json'
    json.dump(pn, open(os.path.join(od, 'etf_forward_profiles.json'), 'w'), ensure_ascii=False, indent=1)
    return add


# ───────────────────────── SEC（SIC）─────────────────────────
_last_sec = [0.0]


def sec_get(url, tries=4):
    """industry_exposure.sic_lookup の get の代わり: SEC_UA（mw_best_ideas_13f）・毎秒10件以下・gzip を解く"""
    import urllib.request, urllib.error
    for i in range(tries):
        dt = time.time() - _last_sec[0]
        if dt < 0.15:
            time.sleep(0.15 - dt)
        _last_sec[0] = time.time()
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=SEC_UA), timeout=90).read()
            if b[:2] == b'\x1f\x8b':
                b = gzip.decompress(b)
            return b
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** i)
        except Exception:
            time.sleep(2 ** i)
    return None


@contextmanager
def sec_env():
    """sic_lookup の書き込み先を写しへ、取得を SEC_UA へ（終われば戻す）"""
    if not os.path.exists(SICF_COPY):
        shutil.copyfile(IE.SICF, SICF_COPY)
    old = (IE.SICF, IE.get)
    IE.SICF, IE.get = SICF_COPY, sec_get
    try:
        yield
    finally:
        IE.SICF, IE.get = old


# ───────────────────────── 業種の割り当て（R の ind_of の写し＋GRID の手の割り当て）─────────────────────────
def mapper(tickers):
    with sec_env():
        sic = IE.sic_lookup(tickers)
    f49 = ff49_map()

    def ind_of(t, c=None):
        if t.startswith('*'):
            return HAND.get(t[1:]) if c == 'GRID' else None    # R では '*' は SIC が無く未分類。手の割り当ては GRID だけ
        s = sic.get(t.upper(), (None,))[0]
        if s is None:
            return None
        k = f49(s)
        return IE.FRENCH_LIKE.get(t.upper(), (k,))[0]
    return ind_of, sic


def grid_split(hs):
    """GRID の米国上場の比 s（会社の行だけで割る・現金は除く）"""
    us = sum(w for t, w in hs if t != 'n/a' and not t.startswith('*'))
    fo = sum(w for t, w in hs if t.startswith('*'))
    return us / (us + fo), us, fo


# ───────────────────────── 代理の系列 ─────────────────────────
def build_proxies(av, grid_w):
    px = {}
    hop = M.french_series('6_Portfolios_ME_OP_2x3', want='Average Value Weighted Returns')['BIG HiOP']
    mom = M.french_series('6_Portfolios_ME_Prior_12_2', want='Average Value Weighted Returns')['BIG HiPRIOR']
    px['BESTPF_PX_MTUM'] = {k: v - av['MTUM']['er'] / 12 for k, v in mom.items()}
    px['BESTPF_PX_QUAL'] = {k: v - av['QUAL']['er'] / 12 for k, v in hop.items()}
    rf = M.ff_factors()['rf']
    j = M.jkp_mkt('ind', 'vw')
    epi_er = json.load(open(os.path.join(BASE, 'out', 'etf_forward_profiles.json')))['etfs']['EPI']['er']
    px['BESTPF_PX_EPI'] = {k: v + rf[k] - epi_er / 12 for k, v in j.items() if k in rf}
    ind = M.french_series('49_Industry_Portfolios', want='Average Value Weighted Returns')
    tot = sum(grid_w.values())
    ws = {k: w / tot for k, w in grid_w.items()}
    months = sorted(set.intersection(*[set(ind[k]) for k in ws]))
    px['BESTPF_PX_GRID'] = {m: sum(w * ind[k][m] for k, w in ws.items()) - av['GRID']['er'] / 12 for m in months}
    return px, ws, epi_er


def gate(px):
    """代理と本物の重なる月の相関（R.build_chains の点検と同じ式）"""
    res = {}
    for c, (main, proxy, last) in NEW_DATA.items():
        if not proxy:
            continue
        r = M.yahoo(main)
        p = px[proxy]
        ov = sorted(k for k in r if k in p and k > last)
        first_main = min(r)
        ok_cont = (first_main // 100 * 12 + first_main % 100) - (last // 100 * 12 + last % 100) == 1
        if len(ov) < MIN_OVERLAP:
            res[c] = dict(proxy=proxy, form=PROXY_FORM[c], overlap_months=len(ov), corr=None, used=False, reason='重なる月が24か月未満')
            continue
        cr = M.corr([r[k] for k in ov], [p[k] for k in ov])
        g_m, g_p = R.geo(r, ov), R.geo(p, ov)
        te = S.pstdev([r[k] - p[k] for k in ov]) * math.sqrt(12)
        res[c] = dict(proxy=proxy, form=PROXY_FORM[c], until=last, first_real_month=first_main, continuous=ok_cont,
                      overlap=f'{ov[0]}〜{ov[-1]}', overlap_months=len(ov), corr=round(cr, 4),
                      geo_main=round(100 * g_m, 2), geo_proxy=round(100 * g_p, 2), gap=round(100 * (g_m - g_p), 2),
                      tracking_error=round(100 * te, 2), used=bool(cr >= GATE and ok_cont),
                      reason=('相関 ≥ 0.90＝代理を使う' if cr >= GATE else f'相関 {cr:.3f} < 0.90＝代理を使わない（事前登録の rule）')
                      + ('' if ok_cont else '・本物の最初の月が代理の最後の月の翌月でない'))
    return res


# ───────────────────────── R へ足す・回す ─────────────────────────
_STATE = {}


@contextmanager
def patched_env(px):
    """R.BASE を写しへ・M.yahoo の前に代理を一枚・SIC を写しへ（終われば戻す）"""
    old_base, old_y = R.BASE, M.yahoo

    def yahoo(t, *a, **k):
        if t in px:
            return dict(px[t])
        return old_y(t, *a, **k)
    R.BASE, M.yahoo = FAKE_BASE, yahoo
    try:
        with sec_env():
            yield
    finally:
        R.BASE, M.yahoo = old_base, old_y


def add_to_R(meta, data, s_us):
    """R の辞書に**足すだけ**（既存のキーは1つも書き換えない）。R.OUT は写しへ向ける（同じプロセスで誤って R.main(write=True) を
    呼んでも out/etf_forward_rank.json を上書きしないため）"""
    for c in meta:
        assert c not in R.C and c not in R.DATA, f'{c} は既に R にある'
    R.JPM['GRID_MIX'] = s_us * R.JPM['USL'] + (1 - s_us) * R.JPM['EAFE']
    for k, v in JPM_EXTRA.items():          # 使うときだけ足す（R に同じ名前があれば値が同じことを確かめる）
        if any(m['jpm'] == k for m in meta.values()):
            assert R.JPM.get(k, v) == v, f'R.JPM[{k}] が既にあり値が違う'
            R.JPM[k] = v
    for c, m in meta.items():
        R.C[c] = dict(ja=m['ja'], veh=m['veh'], us=m['us'], k=m['k'])
        R.DATA[c] = data[c]
        R.JPM_MAP[c] = m['jpm']
        R.GMO_MAP[c] = m['gmo']
        if m.get('vg') is not None:
            R.VG_MAP[c] = m['vg']
        if m.get('same_window'):
            R.SAME_WINDOW.add(c)
    R.OUT = os.path.join(CDIR, 'etf_forward_rank_SHOULD_NOT_BE_WRITTEN.json')


# ───────────────────────── 世界B（R の式の写し）─────────────────────────
def b_inputs():
    """R.main の中の世界Bの材料を、同じ式で作る（ff・49業種・時価総額の下限・型の上乗せ）"""
    geo = R.geo
    ff = M.ff_factors()
    mkt = ff['mkt']
    ind = M.french_series('49_Industry_Portfolios', want='Average Value Weighted Returns')
    tabs49 = M.french_tables('49_Industry_Portfolios')
    nf = next(v for k, v in tabs49.items() if k.startswith('Number of Firms') and v['freq'] == 'monthly')
    sz = next(v for k, v in tabs49.items() if k.startswith('Average Firm Size') and v['freq'] == 'monthly')
    share = {}
    for d, row in nf['data'].items():
        srow = sz['data'].get(d)
        if not srow:
            continue
        caps = [(n or 0) * (z or 0) if (n and z and n > 0 and z > 0) else 0 for n, z in zip(row, srow)]
        tot = sum(caps)
        if tot:
            share[d] = {c: caps[i] / tot for i, c in enumerate(nf['cols'])}
    X_ind, X_ind_raw = {}, {}
    for nm, s in ind.items():
        ks = sorted(k for k in s if k in mkt)
        if len(ks) >= 240:
            X_ind_raw[nm] = dict(x=geo(s, ks) - geo(mkt, ks), start=ks[0], end=ks[-1])
        kf = [k for k in ks if share.get(k, {}).get(nm, 0) >= R.MIN_SHARE]
        if len(kf) >= 240:
            X_ind[nm] = dict(x=geo(s, kf) - geo(mkt, kf), start=kf[0], end=kf[-1], months=len(kf))
    p2 = M.french_series('6_Portfolios_2x3', want='Average Value Weighted Returns')
    pop = M.french_series('6_Portfolios_ME_OP_2x3', want='Average Value Weighted Returns')
    pdp = M.french_series('Portfolios_Formed_on_D-P', want='Value Weight Returns')
    pme = M.french_series('Portfolios_Formed_on_ME', want='Average Value Weight Returns')
    pmom = M.french_series('6_Portfolios_ME_Prior_12_2', want='Average Value Weighted Returns')
    rsp_p = {}
    dec = ['6-Dec', '7-Dec', '8-Dec', '9-Dec', 'Hi 10']
    for k in pme['6-Dec']:
        if all(k in pme[d] for d in dec):
            rsp_p[k] = sum(pme[d][k] for d in dec) / len(dec)

    def x_vs(s, m):
        ks = sorted(k for k in s if k in m)
        return geo(s, ks) - geo(m, ks), ks[0], ks[-1]

    def mkt_of(name, fname):
        out = {}
        for t, v in M.french_tables(fname).items():
            if v['freq'] == 'monthly':
                ci = [c.lower() for c in v['cols']]
                for d, row in v['data'].items():
                    if row[ci.index('mkt-rf')] is not None and row[ci.index('rf')] is not None:
                        out[d] = (row[ci.index('mkt-rf')] + row[ci.index('rf')]) / 100
                break
        return out
    dx = M.french_series('Developed_ex_US_6_Portfolios_ME_BE-ME', want='Average Value Weighted Returns')
    dxm = mkt_of('dx', 'Developed_ex_US_3_Factors')
    em = M.french_series('Emerging_Markets_6_Portfolios_ME_BE-ME', want='Average Value Weighted Returns')
    emm = mkt_of('em', 'Emerging_5_Factors')
    style = {
        'VUG': ('BIG LoBM（大型グロース）', *x_vs(p2['BIG LoBM'], mkt)),
        'VTV': ('BIG HiBM（大型バリュー）', *x_vs(p2['BIG HiBM'], mkt)),
        'VBR': ('SMALL HiBM（小型バリュー）', *x_vs(p2['SMALL HiBM'], mkt)),
        'IJR': ('ME 第2五分位', *x_vs(pme['Qnt 2'], mkt)),
        'RSP': ('ME 第6〜10十分位の平均', *x_vs(rsp_p, mkt)),
        'VYM': ('D/P 上位30%', *x_vs(pdp['Hi 30'], mkt)),
        'VIG': ('BIG HiOP（大型×高収益）', *x_vs(pop['BIG HiOP'], mkt)),
        'MOAT': ('BIG HiOP（大型×高収益）', *x_vs(pop['BIG HiOP'], mkt)),
        'PXF': ('先進国（米国除く）BIG HiBM − その市場', *x_vs(dx['BIG HiBM'], dxm)),
        'DEM': ('新興国 BIG HiBM − その市場', *x_vs(em['BIG HiBM'], emm)),
        # ↓ R7 で足す（R の style と同じ作り）
        'MTUM': ('BIG HiPRIOR（大型×直近12か月の勝ち）', *x_vs(pmom['BIG HiPRIOR'], mkt)),
        'QUAL': ('BIG HiOP（大型×高収益）', *x_vs(pop['BIG HiOP'], mkt)),
    }
    return dict(X_ind=X_ind, X_ind_raw=X_ind_raw, style=style)


SECTOR_R = {'QQQM', 'XLK', 'SMH', 'XLV', 'XLP', 'XLU', 'XLE', 'ITA'}
SECTOR_NEW = {'XLI', 'XLF', 'XLY', 'GRID'}


def expo_of(cands, hold_t, ind_of, bi):
    """R.main の expo と同じ式（e・業種の上乗せ・読めた割合・業種の上位）"""
    X_ind, X_ind_raw = bi['X_ind'], bi['X_ind_raw']
    expo = {}
    for c in cands:
        h = hold_t[c]
        mapped = [(ind_of(t, c), w) for t, w in h]
        tot = sum(w for _, w in h)
        mw = sum(w for k, w in mapped if k)
        e = sum(w for k, w in mapped if k in ('Softw', 'Chips')) / mw if mw else None
        xi = sum(w * X_ind[k]['x'] for k, w in mapped if k in X_ind) / mw if mw else None
        xi_raw = sum(w * X_ind_raw[k]['x'] for k, w in mapped if k in X_ind_raw) / mw if mw else None
        top = {}
        for k, w in mapped:
            if k:
                top[k] = top.get(k, 0) + w / mw
        expo[c] = dict(e=e, X_ind=xi, X_ind_raw=xi_raw, coverage=round(mw / tot, 3) if tot else None, n=len(h),
                       top_industries={k: round(v, 3) for k, v in sorted(top.items(), key=lambda kv: -kv[1])[:6]},
                       all_industries={k: v for k, v in sorted(top.items(), key=lambda kv: -kv[1])})
    if 'VOO' in cands or 'VOO' in R.C:
        expo['VOO'] = dict(e=R.E_MKT, X_ind=0.0, coverage=None, n=None, top_industries={}, note='米国市場の比重（industry_peak）を使う')
    return expo


def world_fns(bi, expo):
    style, sector = bi['style'], SECTOR_R | SECTOR_NEW

    def world_b(c, shrink=R.SHRINK, raw=False):
        if c == 'GLDM':
            return R.R_GOLD, 0.0, 0.0, '金: 実質1.3%＋インフレ2.5%'
        x, src = 0.0, '地域・市場全体＝上乗せなし'
        if c in style:
            x, src = style[c][1], f'{style[c][0]}（{style[c][2]}〜{style[c][3]}）'
        elif c in sector:
            x = (expo.get(c) or {}).get('X_ind_raw' if raw else 'X_ind') or 0.0
            src = '49業種の長い歴史の上乗せを保有で重み付け' + ('（事前登録どおり・社数の少ない時期を含む）' if raw else f'（業種が時価総額の{100 * R.MIN_SHARE:g}%以上の月だけ）')
        rec = 0.0
        if R.C[c]['us']:
            e = (expo.get(c) or {}).get('e')
            if e is None:
                e = R.E_MKT
            rec = R.REC_A - R.REC_B * e
        return R.R_EQ + shrink * x + rec, x, rec, src

    def jpm_c(c, b, h=R.H):
        return (R.H_JPM * R.JPM[R.JPM_MAP[c]] / 100 + (h - R.H_JPM) * b) / h

    def gmo_c(c, b):
        mp = R.GMO_MAP.get(c)
        if mp is None:
            return jpm_c(c, b)
        real = sum(R.GMO[k] * w for k, w in mp) / 100
        nom = (1 + real) * (1 + R.INFL) - 1
        return (R.H_GMO * nom + (R.H - R.H_GMO) * b) / R.H

    def vg_c(c, b):
        if c in R.VG_MAP:
            mp = R.VG_MAP[c]
            if mp is None:
                return jpm_c(c, b)
            v = sum(R.VG[k] * w for k, w in mp) / 100
        else:
            v = R.VG['US'] / 100
        return (R.H_VG * v + (R.H - R.H_VG) * b) / R.H
    return world_b, jpm_c, gmo_c, vg_c


BKEYS = ['B_gross', 'B_X', 'B_rec', 'C_gross', 'B', 'C', '_b03', '_b07', '_c03', '_c07', '_c_gmo', '_c_vg', '_c_h30', '_b_raw', '_c_raw', 'B_X_raw']


def b_values(c, row, world_b, jpm_c, gmo_c, vg_c):
    """R.main の『費用・税を引いて4つの世界をそろえる』のうち B に依る部分と同じ式"""
    er_v, tax = row['er_vehicle'], row['tax_drag']
    b, x, rec, src = world_b(c)
    out = dict(B_gross=b, B_X=x, B_rec=rec, B_src=src, C_gross=jpm_c(c, b), B=b - er_v - tax, C=jpm_c(c, b) - er_v - tax,
               _b03=world_b(c, 0.3)[0] - er_v - tax, _b07=world_b(c, 0.7)[0] - er_v - tax,
               _c03=jpm_c(c, world_b(c, 0.3)[0]) - er_v - tax, _c07=jpm_c(c, world_b(c, 0.7)[0]) - er_v - tax,
               _c_gmo=gmo_c(c, b) - er_v - tax, _c_vg=vg_c(c, b) - er_v - tax, _c_h30=jpm_c(c, b, 30) - er_v - tax)
    braw = world_b(c, raw=True)[0]
    out['_b_raw'] = braw - er_v - tax
    out['_c_raw'] = jpm_c(c, braw) - er_v - tax
    out['B_X_raw'] = world_b(c, raw=True)[1]
    return out


# ───────────────────────── 並べる（R と同じ）─────────────────────────
W = ['A1', 'A2', 'B', 'C']


def rank_all(rows):
    def score(c, worlds):
        v = [rows[c][w] for w in worlds]
        return S.mean(v), min(v)
    order = sorted(rows, key=lambda c: (-score(c, W)[0], -score(c, W)[1]))
    wr = {w: {c: i + 1 for i, c in enumerate(sorted(rows, key=lambda c: -rows[c][w]))} for w in W}
    for i, c in enumerate(order):
        rows[c]['rank'] = i + 1
        rows[c]['score'] = score(c, W)[0]
        rows[c]['worst'] = score(c, W)[1]
        rows[c]['worst_world'] = min(W, key=lambda w: rows[c][w])
        rows[c]['best_world'] = max(W, key=lambda w: rows[c][w])
        rows[c]['world_rank'] = {w: wr[w][c] for w in W}
        rows[c]['top10_in_worlds'] = sum(1 for w in W if wr[w][c] <= 10)

    def top10(vals):
        return sorted(vals, key=lambda c: (-S.mean(vals[c]), -min(vals[c])))[:10]
    sens = {}
    sens['S0_事前登録どおり（業種の時価総額の下限なし）'] = top10({c: [rows[c]['A1'], rows[c]['A2'], rows[c]['_b_raw'], rows[c]['_c_raw']] for c in rows})
    sens['S1_順位の平均'] = sorted(rows, key=lambda c: (S.mean(wr[w][c] for w in W), -rows[c]['worst']))[:10]
    sens['S2_A2を外す'] = top10({c: [rows[c][w] for w in ('A1', 'B', 'C')] for c in rows})
    sens['S3_縮み0.3'] = top10({c: [rows[c]['A1'], rows[c]['A2'], rows[c]['_b03'], rows[c]['_c03']] for c in rows})
    sens['S3_縮み0.7'] = top10({c: [rows[c]['A1'], rows[c]['A2'], rows[c]['_b07'], rows[c]['_c07']] for c in rows})
    sens['S4_CをGMOに'] = top10({c: [rows[c]['A1'], rows[c]['A2'], rows[c]['B'], rows[c]['_c_gmo']] for c in rows})
    sens['S4_CをVanguardに'] = top10({c: [rows[c]['A1'], rows[c]['A2'], rows[c]['B'], rows[c]['_c_vg']] for c in rows})
    sens['S5_期間30年'] = top10({c: [rows[c]['A1'], rows[c]['A2'], rows[c]['B'], rows[c]['_c_h30']] for c in rows})
    sens['S6_外国税なし'] = top10({c: [rows[c][w] + rows[c]['_notax'] for w in W] for c in rows})
    stability = {c: sum(1 for v in sens.values() if c in v) for c in rows}
    return order, sens, stability


def pct(x, d=2):
    return None if x is None else round(100 * x, d)


def table_rows(rows, order, stability):
    out = []
    for c in order:
        r = rows[c]
        out.append({
            'rank': r['rank'], 't': c, 'ja': r['ja'], 'vehicle': r['vehicle'], 'R7で追加': c in NEW,
            '平均(%/年)': pct(r['score']), '最悪の世界(%/年)': pct(r['worst']), '最悪の世界': r['worst_world'], '最良の世界': r['best_world'],
            'A1(%/年)': pct(r['A1']), 'A2(%/年)': pct(r['A2']), 'B(%/年)': pct(r['B']), 'C(%/年)': pct(r['C']),
            '各世界の順位': r['world_rank'], '上位10に入った世界の数': r['top10_in_worlds'], '感度9本のうち上位10に残った数': stability[c],
            '経費率(%)': pct(r['er_vehicle'], 3), '配当利回り(%)': pct(r['dy_vehicle']), '外国税の目減り(%/年)': pct(r['tax_drag'], 3),
            'A1_ぶれ(%/年)': pct(r['vol_A1'], 1), 'A1_最大下落(%)': pct(r['maxdd_A1'], 1),
            'A2_ぶれ(%/年)': pct(r['vol_A2'], 1), 'A2_最大下落(%)': pct(r['maxdd_A2'], 1),
            'B_上乗せX(%/年・縮める前)': pct(r['B_X']), 'B_上乗せX_事前登録どおり(%/年)': pct(r.get('B_X_raw')), 'B_記録の業種REC(%/年)': pct(r['B_rec'], 3),
            'B_上乗せの出どころ': r['B_src'],
            '記録の二業種の比率e': None if r.get('record_share_e') is None else round(r['record_share_e'], 3),
            '中身の読めた割合': r.get('holdings_coverage'), '業種の上位': r.get('top_industries'),
            'データ': f"{r['data']}" + (f"＋〜{r['proxy_until']}は{r['proxy']}" if r['proxy'] else ''),
            'A1の注': r['A1_note'],
            '組み合わせの候補': combinable(c, r, chains_of(r)),
        })
    return out


_CHAINS = {}


def chains_of(r):
    return _CHAINS.get(id(r))


def combinable(c, r, ch):
    """night/bestpf_eval.py と同じ条件: 株であること（GLDM でない）・A1 の毎月の値がそろうこと"""
    if c == 'GLDM':
        return '外す（株でない＝金）'
    if ch is None:
        return None
    miss = [m for m in R.months(*R.A1) if m not in ch]
    return '候補' if not miss else f'外す（A1 の毎月の値が {len(miss)} か月欠ける・最初 {miss[0]}）'


def numeric_fields(row):
    return {k: v for k, v in row.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


# ───────────────────────── MTUM の世界C: JPM の行を替えた感度 ─────────────────────────
def mtum_jpm_sensitivity(rows, world_b, order, sens, stability):
    """MTUM の世界C に当てる JPM の行を、主（MTUM_JPM）ともう一方（MTUM_JPM_ALT）で並べる。
    C に依る欄（C・_c03・_c07・_c_raw・_c_h30）だけを替え、行の写しで並べ直す（rows 自体は変えない）。
    _c_gmo・_c_vg は JPM を使わない（MTUM の GMO は米国大型・Vanguard は既定の米国）ので同じ"""
    c = 'MTUM'
    if c not in rows:
        return None
    val = {'USL': R.JPM['USL'], 'MOMENTUM': JPM_EXTRA['MOMENTUM']}
    r = rows[c]
    er_v, tax = r['er_vehicle'], r['tax_drag']

    def jc(v, b, h=R.H):
        return (R.H_JPM * v / 100 + (h - R.H_JPM) * b) / h

    def c_keys(v):
        return dict(C=jc(v, world_b(c)[0]) - er_v - tax, _c03=jc(v, world_b(c, 0.3)[0]) - er_v - tax,
                    _c07=jc(v, world_b(c, 0.7)[0]) - er_v - tax, _c_raw=jc(v, world_b(c, raw=True)[0]) - er_v - tax,
                    _c_h30=jc(v, world_b(c)[0], 30) - er_v - tax)
    main_k = c_keys(val[MTUM_JPM])
    chk = max(abs(main_k[k] - r[k]) for k in main_k)
    assert chk <= 1e-12, f'MTUM の C の写しが行と合わない（{chk}）'
    rows2 = {k: dict(v) for k, v in rows.items()}
    rows2[c].update(c_keys(val[MTUM_JPM_ALT]))
    order2, sens2, stab2 = rank_all(rows2)

    def view(rw, od, st, sn, lab):
        x = rw[c]
        return {'JPM の行': lab, 'JPM の値(%)': val[lab], 'C(%/年)': pct(x['C']), '平均(%/年)': pct(x['score']), '最悪の世界(%/年)': pct(x['worst']),
                '順位': x['rank'], '上位10': od[:10], '感度9本のうち上位10に残った数(MTUM)': st[c],
                '感度の上位10': {k: v for k, v in sn.items()}}
    a, b = view(rows, order, stability, sens, MTUM_JPM), view(rows2, order2, stab2, sens2, MTUM_JPM_ALT)
    moved = {t: (rows[t]['rank'], rows2[t]['rank']) for t in rows if rows[t]['rank'] != rows2[t]['rank']}
    return {'主（rows に入っている値）': a, '感度（もう一方の行）': b, 'C(%/年)': a['C(%/年)'], '平均(%/年)': a['平均(%/年)'], '順位': a['順位'],
            '順位が動いた本(主→感度)': moved, '上位10が変わるか': a['上位10'] != b['上位10'],
            '感度の上位10の数が変わった本': {t: (stability[t], stab2[t]) for t in rows if stability[t] != stab2[t]},
            '写しの検算(主の C と行の C の最大の差)': chk,
            'note': ('C は (12.5×JPM＋7.5×B)/20 − 費用 − 外国税。JPM の行だけを替えた差は (12.5/20)×(7.6−6.7)%＝0.5625%/年。'
                     '主は指示どおり米国大型（控えめな側）。R は VTV→Value・VIG/MOAT→Quality と型の行を当てているので、R と同じ作りにそろえるなら勢いの行'
                     '（環境変数 BESTPF_R7_MTUM_JPM=MOMENTUM で切り替わる）')}


def chips_full_table(rows, expo):
    """K4（半導体の基礎率の感度）が読む Chips の比重: top_industries（上位6業種で切ってある）と全業種の両方。
    etf_forward_combo / bestpf_eval は top_industries の Chips を読み、上位6業種に無ければ0とする（R と同じ決まり）。
    ここでは差と、全業種で読んだときの K4 の調整の差（%/年）を名指しするだけで、rows は変えない"""
    import etf_forward_combo as CB
    rest = CB.CHIPS_GAP * CB.CHIPS_MKT / (1 - CB.CHIPS_MKT)
    out = {}
    for c in rows:
        if c == 'VOO':
            out[c] = dict(note=f'eval は市場の Chips 比重 CHIPS_MKT={CB.CHIPS_MKT} を使う（中身を読まない）')
            continue
        if not R.C[c]['us'] or c not in expo:
            out[c] = dict(note='米国の本でない＝K4 の調整なし（中身を業種へ割り当てていない）')
            continue
        top6 = float((rows[c].get('top_industries') or {}).get('Chips') or 0.0)
        full = float(expo[c]['all_industries'].get('Chips') or 0.0)
        d = -(full - top6) * (CB.CHIPS_GAP + rest) / 2
        out[c] = dict(chips_top6=round(top6, 4), chips_all_industries=round(full, 4), cut_by_top6=bool(full > 0 and top6 == 0),
                      K4_adj_diff_if_all_industries=pct(d, 3))
    return dict(rule='K4 の調整 = (−CHIPS_GAP×s ＋ rest×(1−s))/2・rest = CHIPS_GAP×CHIPS_MKT/(1−CHIPS_MKT)（night/etf_forward_combo.py 33・94〜99行）',
                CHIPS_GAP=CB.CHIPS_GAP, CHIPS_MKT=CB.CHIPS_MKT,
                cut_names=[c for c, v in out.items() if v.get('cut_by_top6')], table=out)


def fixes_applied(ctx, mtum_c_line):
    """2026-10-12 検証役の指摘（medium 1・low 2）と、直す途中で自分で見つけた誤り1件への手当て"""
    ch = chips_full_table(ctx['rows_ref'], ctx['expo'])
    cut = {c: ch['table'][c] for c in ch['cut_names']}
    return [
        dict(severity='medium', issue='世界Cで MTUM に JPM の米国大型（6.7%）を当て、報告で『業種ごとの予想が無い』と書いたが、JPM 2026 LTCMA には勢いの行（U.S. Equity Momentum Factor 7.60%）がある',
             check=f"JPM の PDF を取り直して確かめた（sha256 {JPM_SRC['sha256'][:12]}…・列は Compound Return 2026・U.S. Large Cap 6.70／Momentum 7.60／Quality 6.60／Value 7.70）",
             fix=('主は指示（『MTUM は米国大型』）どおり米国大型 6.7% のまま。文を『勢いの行 7.60% はあるが、指示どおり米国大型（控えめな側）を使った』に直し、'
                  '勢いの行を使った場合を感度として出した（MTUM_world_C_JPM_sensitivity: C・平均・順位・上位10・感度9本）。'
                  'まとめ役が R と同じ作り（VTV→Value・VIG/MOAT→Quality）にそろえると決めたら、環境変数 BESTPF_R7_MTUM_JPM=MOMENTUM で1語で切り替わる'
                  '（R.JPM に MOMENTUM を足すだけ・既存のキーは変えない）'),
             result=mtum_c_line),
        dict(severity='low', issue='報告の『MTUM の売買の多さ（年116%）』に出典が書かれていない',
             check='値は AV ETF_PROFILE の portfolio_turnover 1.16（out/_bestpf_cache/R7/av_etf_profile_2026-10-12.json・この JSON の inputs_av_profiles にも turnover: 1.16 で入っていた）。'
                   'SEC の全文検索で iShares の Summary Prospectus（497K）を引き、本文で確かめた',
             fix='new_assets.MTUM.turnover_prospectus に出典（URL・本文の一文・提出日）を入れ、⚠ に書いた。直近の会計年度 116%・その前の年 95%',
             result=TURNOVER_SRC['MTUM']['prospectus_2025']['url']),
        dict(severity='low', issue='feeds_final の『top_industries＝K4 の Chips の比重』は不正確。top_industries は上位6業種で切ってあり、Chips が7位以下の本は K4 で0と読まれる',
             fix=('rows は変えない（R と etf_forward_combo の決まり〔上位6業種に無ければ0〕と既存の本にそろえたまま）。全業種の Chips の比重と、全業種で読んだときの K4 の調整の差を '
                  '"chips_share_all_industries(K4)" に全本ぶん出し、feeds_final に1行足した'),
             result={c: (v['chips_all_industries'], v['K4_adj_diff_if_all_industries']) for c, v in cut.items()}),
        dict(severity='（自分で見つけた）', issue='⚠ の『MTUM は…毎半年入れ替える指数』は今の目論見書と違う',
             check='497K（2025-11-28）の Principal Investment Strategies: MSCI USA Momentum SR Variant Index・6か月と12か月の勢いをぶれで割った点数の上位125社・四半期ごとに入れ替え・1回の片道の入れ替えは30%まで',
             fix='⚠ の文を直した（数字は何も変わらない）'),
    ]


# ───────────────────────── 本体 ─────────────────────────
def build(checks=True):
    if 'res' in _STATE and not checks:
        return _STATE['res']
    t0 = time.time()
    file_doc = json.load(open(os.path.join(BASE, 'out', 'etf_forward_rank.json')))
    base_res = None
    if checks:
        log('① R.main（拡張なし）を回す')
        assert not any(c in R.C for c in NEW), 'R が既に拡張されている（同じプロセスで2回呼ばない）'
        with sec_env():                      # SIC の書き込み先を写しへ（既存の out/sic_by_cik.json を書き換えないため）
            base_res = R.main(write=False)
    av = av_profiles()
    add = build_fake_base(av)
    hold_new = {t: [(h[0], h[1]) for h in add[t]['holdings'] if h and h[0] and h[0] != 'n/a'] for t in ('MTUM', 'QUAL', 'XLI', 'XLF', 'XLY', 'GRID')}
    s_us, us_w, fo_w = grid_split(hold_new['GRID'])
    meta = copy.deepcopy(NEW)
    meta['GRID']['k'] = s_us * 0.10 + (1 - s_us) * 0.20
    meta['GRID']['gmo'] = [('USL', s_us), ('INTL', 1 - s_us)]
    meta['GRID']['vg'] = [('US', s_us), ('DEV', 1 - s_us)]
    meta['MTUM']['jpm'] = MTUM_JPM

    # 既存の中身（R が読むのと同じ: prof_new→prof_old）＋新しい本
    prof_old = json.load(open(os.path.join(FAKE_BASE, 'out', 'etf_profiles.json'))).get('etfs') or {}
    prof_new = json.load(open(os.path.join(FAKE_BASE, 'out', 'etf_forward_profiles.json'))).get('etfs') or {}
    hold_t = {}
    for c in list(R.C) + [c for c in NEW if c not in R.C]:
        us = (R.C.get(c) or meta.get(c))['us']
        if not us or c == 'VOO':
            continue
        h = R.holdings_of(c, prof_old, prof_new)
        if c == 'QQQM':
            h = R.holdings_of('QQQM', prof_old, prof_new) or R.holdings_of('QQQ', prof_old, prof_new)
        hold_t[c] = h
    tickers = {t.upper() for h in hold_t.values() for t, _ in h if not t.startswith('*')}
    log('SIC を引く', len(tickers), '本')
    ind_of, sic = mapper(tickers)
    unknown_sic = sorted(t for t in {t for c in NEW if c in hold_t for t, _ in hold_t[c] if not t.startswith('*')}
                         if sic.get(t.upper(), (None,))[0] is None)

    # GRID の代理の重み（保有→49業種）
    gw = {}
    for t, w in hold_t['GRID']:
        k = ind_of(t, 'GRID')
        if k:
            gw[k] = gw.get(k, 0) + w
    log('GRID の業種の重み', {k: round(v, 4) for k, v in sorted(gw.items(), key=lambda kv: -kv[1])}, '米国上場の比', round(s_us, 4))

    px, grid_ws, epi_er = build_proxies(av, gw)
    gates = gate(px)
    log('代理の点検', {c: (g['corr'], g['used']) for c, g in gates.items()})

    # 代理が通らない本: A2 が本物で埋まるなら SAME_WINDOW（参考の A1）／埋まらないなら R へ足さない
    k2 = R.months(*R.A2)
    excluded, data = {}, {}
    for c, (main, proxy, last) in NEW_DATA.items():
        if proxy and not gates[c]['used']:
            real = M.yahoo(main)
            if all(m in real for m in k2):
                if c == 'EPI_LONG':
                    excluded[c] = dict(reason=gates[c]['reason'] + '。代理なしの EPI は既存の行（R の SAME_WINDOW）と同じなので足さない')
                    continue
                data[c] = (main, None, None)
                meta[c]['same_window'] = True
                excluded[c] = dict(reason=gates[c]['reason'] + '。A1 の毎月の値がそろわないので組み合わせからは外れる。A2 は本物で測れる（A1 は同じ窓の SPY との差の参考値）',
                                   kept_in_table=True)
            else:
                own = sorted(real)
                spy = M.yahoo('SPY')
                g_c, g_s = R.geo(real, own), R.geo(spy, own)
                excluded[c] = dict(reason=gates[c]['reason'] + '。本物は A2（2011-10〜）もそろわないので R へ足さない', kept_in_table=False,
                                   own_window=f'{own[0]}〜{own[-1]}', own_geo=pct(g_c), spy_same_window=pct(g_s), diff_vs_spy=pct(g_c - g_s))
                continue
        else:
            data[c] = (main, proxy, last)
    meta = {c: m for c, m in meta.items() if c in data}

    log('② 拡張した R.main を回す')
    add_to_R(meta, data, s_us)
    with patched_env(px):
        ext = R.main(write=False)
    rows, chains = ext['rows'], ext['chains']
    r_main_uncorrected = {c: {k: rows[c][k] for k in ('B', 'C', 'B_X', 'B_rec', 'B_src')} for c in meta}

    # 世界B（R の式の写し）
    log('③ 世界Bの写し')
    bi = b_inputs()
    expo = expo_of([c for c in hold_t], hold_t, ind_of, bi)
    world_b, jpm_c, gmo_c, vg_c = world_fns(bi, expo)
    replica = {}
    for c in rows:
        if c in meta:
            continue
        v = b_values(c, rows[c], world_b, jpm_c, gmo_c, vg_c)
        d = {k: abs(v[k] - rows[c][k]) for k in BKEYS}
        replica[c] = max(d.values())
    rep_max = max(replica.values())
    rep_ok = rep_max <= 1e-12
    expo_ok = {}
    for c in SECTOR_R:
        e_rows = rows[c].get('record_share_e')
        expo_ok[c] = (abs((expo[c]['e'] or 0) - (e_rows or 0)) <= 1e-12, rows[c].get('top_industries') == expo[c]['top_industries'],
                      rows[c].get('holdings_coverage') == expo[c]['coverage'])
    log('  写しの最大の差（既存）', rep_max, '業種の割り当て一致', all(all(v) for v in expo_ok.values()))
    if not rep_ok:
        raise SystemExit(f'世界Bの写しが R と合わない（最大の差 {rep_max}）。新しい本の B を信じられないので止める')
    for c in meta:
        v = b_values(c, rows[c], world_b, jpm_c, gmo_c, vg_c)
        rows[c].update(v)
        if R.C[c]['us']:
            rows[c]['record_share_e'] = expo[c]['e']
            rows[c]['holdings_coverage'] = expo[c]['coverage']
            rows[c]['top_industries'] = expo[c]['top_industries']
        rows[c]['us'] = R.C[c]['us']
        rows[c]['r7_new'] = True
    order, sens, stability = rank_all(rows)
    for c in rows:
        _CHAINS[id(rows[c])] = chains[c]
    mtum_sens = mtum_jpm_sensitivity(rows, world_b, order, sens, stability)
    log('  MTUM の世界C（主', MTUM_JPM, '／感度', MTUM_JPM_ALT, '）', {k: mtum_sens[k] for k in ('C(%/年)', '平均(%/年)', '順位')} if mtum_sens else None)

    # ── 回帰の検査 ──
    reg = {}
    if checks:
        # ① 拡張なしの R.main と out/etf_forward_rank.json
        bt = {r['t']: r for r in base_res['doc']['table']}
        ft = {r['t']: r for r in file_doc['table']}
        diffs = []
        for t, fr in ft.items():
            br = bt.get(t)
            if br is None:
                diffs.append((t, '行が無い'))
                continue
            for k, v in fr.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    if br.get(k) != v:
                        diffs.append((t, k, v, br.get(k)))
                elif isinstance(v, dict) and k != '各世界の順位':
                    if br.get(k) != v:
                        diffs.append((t, k, v, br.get(k)))
                elif k == '各世界の順位' and br.get(k) != v:
                    diffs.append((t, k, v, br.get(k)))
        sc_diff = {k: (file_doc['splice_checks'].get(k), base_res['doc']['splice_checks'].get(k))
                   for k in set(file_doc['splice_checks']) | set(base_res['doc']['splice_checks'])
                   if file_doc['splice_checks'].get(k) != base_res['doc']['splice_checks'].get(k)}
        reg['①_拡張なしのR.main_と_out/etf_forward_rank.json'] = dict(
            file_generated=file_doc['generated'], rows=len(ft), mismatches=len(diffs), first_mismatches=diffs[:20],
            splice_check_mismatches=sc_diff, spy_a1=(file_doc['SPY_A1(%/年)'], base_res['doc']['SPY_A1(%/年)']),
            top10_same=[r['t'] for r in file_doc['top10']] == [r['t'] for r in base_res['doc']['top10']],
            ok=(not diffs and not sc_diff and file_doc['SPY_A1(%/年)'] == base_res['doc']['SPY_A1(%/年)']))
        # ② 拡張した R.main の既存25本 と ①（数の欄は全部・順位の欄は除く＝本が増えれば順位は動く）
        rank_keys = {'rank', 'score', 'worst', 'top10_in_worlds'}
        bad = []
        for c, br in base_res['rows'].items():
            er_ = rows[c]
            for k, v in numeric_fields(br).items():
                if k in rank_keys:
                    continue
                if er_.get(k) != v:
                    bad.append((c, k, v, er_.get(k)))
            if base_res['chains'][c] != chains[c]:
                bad.append((c, 'chain'))
        sc_e = {k: v for k, v in ext['doc']['splice_checks'].items() if k in base_res['doc']['splice_checks']}
        reg['②_拡張したR.mainの既存25本_と_拡張なし'] = dict(rows=len(base_res['rows']), mismatches=len(bad), first=bad[:20],
                                                   splice_checks_same=sc_e == base_res['doc']['splice_checks'], ok=not bad)
        # 表（丸めた値）でも out/etf_forward_rank.json と比べる
        tab_ext = {r['t']: r for r in table_rows(rows, order, stability)}
        cmp_keys = ['A1(%/年)', 'A2(%/年)', 'B(%/年)', 'C(%/年)', '平均(%/年)', '最悪の世界(%/年)', '経費率(%)', '配当利回り(%)', '外国税の目減り(%/年)',
                    'A1_ぶれ(%/年)', 'A1_最大下落(%)', 'A2_ぶれ(%/年)', 'A2_最大下落(%)', 'B_上乗せX(%/年・縮める前)', 'B_記録の業種REC(%/年)']
        bad2 = [(t, k, fr[k], tab_ext[t][k]) for t, fr in ft.items() for k in cmp_keys if fr.get(k) != tab_ext[t].get(k)]
        reg['②b_拡張した表の既存25本_と_out/etf_forward_rank.json（丸めた値）'] = dict(keys=cmp_keys, mismatches=len(bad2), first=bad2[:20], ok=not bad2)
        reg['③_世界Bの写し_と_R.main（既存25本）'] = dict(keys=BKEYS, max_abs_diff=rep_max, tol=1e-12, ok=rep_ok,
                                                   per_asset={c: v for c, v in replica.items()},
                                                   industry_mapping_same_for_sector_ETFs={c: all(v) for c, v in expo_ok.items()})
    res = dict(rows=rows, chains=chains, spy=ext['spy'], doc=None)
    ctx = dict(meta=meta, data=data, gates=gates, excluded=excluded, s_us=s_us, us_w=us_w, fo_w=fo_w, grid_ws=grid_ws, gw=gw,
               bi=bi, expo=expo, order=order, sens=sens, stability=stability, reg=reg, av=av, add=add, unknown_sic=unknown_sic,
               r_main_uncorrected=r_main_uncorrected, file_doc=file_doc, mtum_sens=mtum_sens, rows_ref=rows, ext_splice=ext['doc']['splice_checks'], epi_er=epi_er, px=px, secs=round(time.time() - t0))
    res['doc'] = make_doc(rows, chains, ctx)
    _STATE['res'] = res
    _STATE['ctx'] = ctx
    return res


def a1_monthly(chains):
    k1 = R.months(*R.A1)
    out = {}
    for c, r in chains.items():
        miss = [m for m in k1 if m not in r]
        out[c] = dict(window=f'{k1[0]}〜{k1[-1]}', months=len(k1), missing_n=len(miss),
                      missing=(miss if len(miss) <= 40 else miss[:20] + ['…'] + miss[-5:]),
                      returns={str(m): round(r[m], 8) for m in k1 if m in r})
    return out


def own_window_stats(c):
    """新しい本の本物だけの窓の年率と、同じ窓の SPY・QQQ との差（参考）"""
    main = NEW_DATA[c][0]
    r = M.yahoo(main)
    ks = sorted(k for k in r if k <= R.A1[1])
    spy, qqq = M.yahoo('SPY'), M.yahoo('QQQ')
    ks = [k for k in ks if k in spy and k in qqq]
    g, gs, gq = R.geo(r, ks), R.geo(spy, ks), R.geo(qqq, ks)
    return dict(window=f'{ks[0]}〜{ks[-1]}', years=round(len(ks) / 12, 1), geo=pct(g), spy=pct(gs), qqq=pct(gq),
                diff_spy=pct(g - gs), diff_qqq=pct(g - gq), vol=pct(R.vol(r, ks), 1), maxdd=pct(R.maxdd(r, ks), 1),
                corr_spy=round(M.corr([r[k] for k in ks], [spy[k] for k in ks]), 3))


def make_doc(rows, chains, ctx):
    order, sens, stability = ctx['order'], ctx['sens'], ctx['stability']
    meta, gates = ctx['meta'], ctx['gates']
    tab = table_rows(rows, order, stability)
    plan_sha = hashlib.sha256(open(PLAN, 'rb').read()).hexdigest() if os.path.exists(PLAN) else None
    new_info = {}
    for c in NEW:
        m = ctx['meta'].get(c) or NEW[c]
        info = dict(ja=m['ja'], vehicle=m['veh'], us=m['us'], foreign_tax_k=m['k'], data=NEW_DATA[c], proxy_form=PROXY_FORM.get(c),
                    splice_check=gates.get(c), in_R_run=c in rows, excluded=ctx['excluded'].get(c),
                    JPM=(m['jpm'], R.JPM.get(m['jpm'])), GMO=m['gmo'], Vanguard=m.get('vg') or '既定（R と同じ: 米国 VG US）',
                    B_kind=m['kind'])
        if c in rows:
            r = rows[c]
            info['R.main_before_B_fix'] = {k: (pct(v) if isinstance(v, float) else v) for k, v in ctx['r_main_uncorrected'][c].items()}
            info['B_after_fix(%/年)'] = pct(r['B'])
            info['C_after_fix(%/年)'] = pct(r['C'])
        try:
            info['own_window_real_only'] = own_window_stats(c)
        except Exception as e:  # noqa
            info['own_window_real_only'] = f'取れない: {e}'
        if c in ctx['av']:
            p = ctx['av'][c]
            info['profile'] = dict(er=p['er'], dy=p['dy'], inception=p['inception'], last_updated=p['last_updated'], n=len(p['holdings']),
                                   turnover_AV=p.get('turnover'),
                                   turnover_AV_src='Alpha Vantage ETF_PROFILE の portfolio_turnover（何年度の値かは AV に書かれていない・MTUM 以外は目論見書で確かめていない）',
                                   sectors_AV=p['sectors'], top_holdings=[h[:2] if h[0] != 'n/a' else [h[2], h[1]] for h in p['holdings'][:10]])
        if c in TURNOVER_SRC:
            info['turnover_prospectus'] = TURNOVER_SRC[c]
        if c == 'MTUM':
            info['JPM_note'] = (f"世界C の JPM の行: 主 {MTUM_JPM}（{R.JPM['USL'] if MTUM_JPM == 'USL' else JPM_EXTRA['MOMENTUM']}%）。"
                                f"JPM 2026 LTCMA には U.S. Equity Momentum Factor 7.60% の行がある（出典 {JPM_SRC['url']}）。"
                                '指示（MTUM は米国大型）どおり米国大型 6.7% を主にし、勢いの行を使った場合を MTUM_world_C_JPM_sensitivity に出した')
        if c in ctx['expo']:
            info['industries_French49(保有の重み)'] = {k: round(v, 3) for k, v in ctx['expo'][c]['all_industries'].items()}
        new_info[c] = info
    gi = dict(us_listed_share=round(ctx['s_us'], 4), us_listed_weight=round(ctx['us_w'], 4), foreign_listed_weight=round(ctx['fo_w'], 4),
              JPM_GRID_MIX=round(R.JPM['GRID_MIX'], 3), foreign_tax_k=round(meta['GRID']['k'], 4) if 'GRID' in meta else None,
              proxy_industry_weights={k: round(v, 4) for k, v in sorted(ctx['grid_ws'].items(), key=lambda kv: -kv[1])},
              hand_map_note='米国外上場（AV で symbol が n/a）の会社は会社名から手で49業種へ（測る前に固定・night/bestpf_ext.py の HAND）。名前の無い行と Stella-Jones は割り当てない')
    excl_names = [c for c, v in ctx['excluded'].items()]
    k1 = R.months(*R.A1)
    k2 = R.months(*R.A2)
    proxy_share = {}
    for c, (main, proxy, last) in ctx['data'].items():
        if proxy:
            n1 = sum(1 for m in k1 if m <= last)
            n2 = sum(1 for m in k2 if m <= last)
            proxy_share[c] = dict(A1_proxy_months=n1, A1_share=round(n1 / len(k1), 3), A2_proxy_months=n2, A2_share=round(n2 / len(k2), 3),
                                  overlap_gap_real_minus_proxy=(gates.get(c) or {}).get('gap'))
    comb = [c for c in rows if combinable(c, rows[c], chains[c]) == '候補']
    not_comb = {c: combinable(c, rows[c], chains[c]) for c in rows if combinable(c, rows[c], chains[c]) != '候補'}
    ms = ctx.get('mtum_sens')
    if ms:
        a, b = ms['主（rows に入っている値）'], ms['感度（もう一方の行）']
        mtum_c_line = (f"MTUM の C: 主（{a['JPM の行']} {a['JPM の値(%)']}%）{a['C(%/年)']}・平均 {a['平均(%/年)']}・{a['順位']}位 ／ "
                       f"感度（{b['JPM の行']} {b['JPM の値(%)']}%）{b['C(%/年)']}・平均 {b['平均(%/年)']}・{b['順位']}位"
                       f"（上位10は{'変わる' if ms['上位10が変わるか'] else '変わらない'}）")
    else:
        mtum_c_line = 'MTUM が R へ足されていないので感度は無い'
    plan_content = json.load(open(PLAN)) if os.path.exists(PLAN) else (json.load(open(OUT)).get('plan_before_measure') or {}).get('content')
    doc = {
        'generated': datetime.date.today().isoformat(), 'tool': 'night/bestpf_ext.py', 'prereg': PREREG,
        'plan_before_measure': dict(path='out/_bestpf_cache/R7/plan_before_measure.json（gitignore 済みの置き場・コミットされていない）', sha256=plan_sha,
                                    written='2026-10-12 09:40 UTC（相関を一度も測る前・自己申告）', content=plan_content),
        'question': '今までの21本に無い株の ETF（MTUM・QUAL・XLI・XLF・XLY・EPI・GRID）を etf_forward_rank と同じ物差しで測る',
        'unit': 'ドル建ての幾何年率（費用と NISA で取り戻せない配当の外国税を引いた後）。R と同じ',
        'worlds': {'A1': f'{R.A1[0]}→{R.A1[1]} の実績（直近26年）', 'A2': f'{R.A2[0]}→{R.A2[1]} の実績（直近15年）',
                   'B': f'100年の平均: R株 {100 * R.R_EQ:.2f}%＋{R.SHRINK}×X＋REC', 'C': f'JPM 2026 LTCMA を {R.H_JPM}年・その後 B（{R.H}年）'},
        'how': ('R（night/etf_forward_rank.py）を書き換えず、R の辞書に新しい本を足して R.main(write=False) を回した。'
                'R.main の世界Bは業種・型の集合が関数の中に固定されていて新しい本を入れられないので、世界B（とBに依る C・感度）だけ R の式の写しで計算し直した。'
                '写しが既存25本で R と 1e-12 以内で一致することを確かめた（regression ③）'),
        'new_assets': new_info,
        'GRID_detail': gi,
        'excluded_from_combination': {c: ctx['excluded'][c] for c in excl_names},
        'combination_candidates(株・A1の毎月の値がそろう)': comb,
        'not_combinable': not_comb,
        'proxy_share(代理の月の割合と、重なる期間の本物−代理の年率の差)': proxy_share,
        'regression': ctx['reg'],
        'MTUM_world_C_JPM_sensitivity': ms,
        'JPM_2026_LTCMA_rows_checked': JPM_SRC,
        'chips_share_all_industries(K4)': chips_full_table(rows, ctx['expo']),
        'fixes_applied': fixes_applied(ctx, mtum_c_line),
        'notes_for_eval': [
            'rows[c]["top_industries"] は上位6業種で切ってある（R と同じ）。K4（半導体の基礎率の感度）はここから Chips を読み、上位6業種に無ければ0とする。'
            'そのため Chips が7位以下の本（"chips_share_all_industries(K4)" の cut_names）は K4 で0と読まれる。差は小さい（同じ表の K4_adj_diff_if_all_industries）',
            'MTUM の世界C は主が米国大型 6.7%（指示どおり）。勢いの行 7.6% にそろえるなら BESTPF_R7_MTUM_JPM=MOMENTUM を付けて rank_result() を呼ぶ（MTUM_world_C_JPM_sensitivity に結果）',
        ],
        'top10': [{'rank': i + 1, 't': c, 'ja': rows[c]['ja'], '平均(%/年)': pct(rows[c]['score']), '最悪の世界(%/年)': pct(rows[c]['worst'])}
                  for i, c in enumerate(order[:10])],
        'top10_before_R7(out/etf_forward_rank.json)': [r['t'] for r in ctx['file_doc']['top10']],
        'table': tab,
        'sensitivity_top10': sens,
        'splice_checks_all(R.main の点検)': ctx['ext_splice'],
        'B_style_long_run_excess(%/年・縮める前)': {c: dict(portfolio=v[0], x=pct(v[1]), start=v[2], end=v[3]) for c, v in ctx['bi']['style'].items()},
        'A1_monthly(データの器の月次リターン・費用と外国税を引く前)': a1_monthly(chains),
        'A1_net_adjust(%/年・A1−A1_gross＝費用の差−外国税)': {c: pct(rows[c]['A1'] - rows[c]['A1_gross'], 4) for c in rows},
        'unknown_SIC_in_new_holdings': ctx['unknown_sic'],
        'inputs_av_profiles': dict(source='Alpha Vantage ETF_PROFILE（MCP）2026-10-12 採取の写し（out/_bestpf_cache/R7/av_etf_profile_2026-10-12.json と同じ）',
                                   etfs=ctx['av']),
        'secs': ctx['secs'],
        '⚠': [
            '代理の期間（MTUM・QUAL は A1 の約半分〔2000-09〜2013年〕・A2 の最初の1年半、EPI_LONG は A1 の約3割）の値は、重なる期間の本物−代理の年率の差（MTUM +1.27・QUAL −2.22・EPI −0.24 %/年）ほどずれうる。QUAL の A1 は代理が本物より強かった分だけ高めに出ている恐れがある（MOAT と同じ向き）',
            'EPI の配当利回りは R の入力（AV）で 0.01% と小さく、外国税の目減りはほぼ0になっている（R の EPI と同じ値をそのまま使った）',
            ('代理は ETF そのものではない。MTUM の代理（French BIG HiPRIOR）は12か月の勝ちの上位30%の大型株。MTUM は 6か月と12か月の勢いを過去3年の週次のぶれで割った点数の'
             '上位125社を点数×時価総額で重み付けし、四半期ごとに入れ替える指数（1回の片道の入れ替えは30%まで・497K 2025-11-28）で、作りが違う。'
             '重なる期間では本物が代理より年1.27%高かった'),
            ('MTUM の売買の多さ（回転率）は直近の会計年度 116%（その前の年 95%）＝ iShares の Summary Prospectus（497K 2025-11-28・2024-11-29）。'
             'AV の ETF_PROFILE の portfolio_turnover も 1.16。代理の期間（French の月次の組）には売買の費用は入っていない'),
            ('世界C: JPM 2026 LTCMA に業種（資本財・金融・一般消費財・送電）の行は無いので、XLI・XLF・XLY は米国大型 6.7%、GRID は米国大型と EAFE の混ぜ。'
             'QUAL は質の行 6.6%（R の VIG・MOAT と同じ）。MTUM には勢いの行（U.S. Equity Momentum Factor 7.60%）があるが、指示どおり米国大型 6.7% を主にした（控えめな側）。'
             + mtum_c_line),
            'GRID の代理は米国外の会社にも米国の業種のリターンを当てている（国・為替の差は入らない）。保有は今の写真で、2000〜2009年の中身ではない',
            'EPI_LONG の代理は JKP のインド市場全体（時価加重）。EPI は利益で重み付けした指数',
            '世界Bの業種の上乗せは米国の歴史（French・CRSP）。GRID の米国外の分にも米国の業種の歴史を当てた（R が地域の差を付けないのと同じ仮定）',
            'GRID の世界Cは JPM の米国大型と EAFE を米国上場の比で混ぜた（複利の予想を算術で混ぜる近似）',
            '新しい本の世界Bは R.main の中では『上乗せなし』に落ちるので、R の式の写しで計算し直した（写しは既存25本で一致を確認）',
            '判定・配分には使わない（材料）',
        ],
    }
    return doc


def rank_result():
    """night/bestpf_eval.py が呼ぶ。R.main(write=False) と同じ形 {rows, chains, spy, doc}（rows は既存25＋R7 で足せた本）"""
    return build(checks=False)


def main():
    res = build(checks=True)
    doc = res['doc']
    ctx = _STATE['ctx']
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    log(f'→ {OUT}（{ctx["secs"]}秒）')
    log('回帰:', {k: v.get('ok') for k, v in ctx['reg'].items()})
    log(f"{'順':>2} {'候補':8} {'平均':>6} {'最悪':>6} {'A1':>6} {'A2':>6} {'B':>6} {'C':>6} 感度")
    for t in doc['table']:
        log(f"{t['rank']:2d} {t['t']:8} {t['平均(%/年)']:6.2f} {t['最悪の世界(%/年)']:6.2f} {t['A1(%/年)']:6.2f} {t['A2(%/年)']:6.2f} "
            f"{t['B(%/年)']:6.2f} {t['C(%/年)']:6.2f} {t['感度9本のうち上位10に残った数']}{'  ＊R7' if t['R7で追加'] else ''}")


if __name__ == '__main__':
    main()
