#!/usr/bin/env python3
"""night/nx_indmom_real_data.py — 角度 nx_indmom_real（楽天証券で買える米国上場の業種・産業 ETF で『業種の勢い』を
実際に回したら SPY に勝ったか）の【取得と整形・母集団の規則・規則の台帳（宣言だけ）】。

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて勝てる結果を出して…
別のSessionで検証していない新たな分析を同じ内容でしてほしい」。事前登録は out/nx_indmom_real_prereg.json。

★成績は一つも計算しない・表示しない（規則のリターン・SPY との差・t・シャープ・勝率は出さない）。
  このファイルが出すのはデータの形（母集団の選別の件数と理由・ETF の上場月と月数・各月に使える ETF の数・
  N-PORT の中身の割合・月の切り方の点検・欠け）だけ。規則の組み立て（ポートフォリオのリターン）は書かない
  ＝測る道具 night/nx_indmom_real.py（これから書く）が RULES（宣言）と抽出を読んで組む。

母集団の規則（事前登録 universe と同じ・結果を見る前に凍結）
  段1（名前）: out/broker_lineup.json（楽天の米国上場 ETF 742本・2026-08-24 の写真）の名前から、発行会社の語
       （Global X・iShares・State Street SPDR…）を先に外し、次の順で除く: 名前が空（取扱終了の残骸）→
       レバレッジ・インバース・単一銘柄の上乗せ → 債券・現金 → 商品・ETN・暗号資産 → オプション・インカムの上乗せ →
       スマートベータ・能動運用 → 米国外・地域 → 市場全体・規模。残りを『細かい業種の語』（INDUSTRY）→
       『GICS セクターの語』（SECTOR）→『テーマの語』（THEME・除く）の順に当てる。どれにも当たらなければ除く。
  段2（中身）: SEC の N-PORT（最新の公開分）で、株の買い（assetCat EC/EP・payoffProfile Long）が純資産の 90% 以上、
       その株のうち『US』のものが 50% 超、デリバティブと売りが純資産の 5% 以下。US ＝ invCountry が US かつ ISIN の頭が US
       （ISIN が無い株は invCountry だけ）＝二つの印の両方（理由は nport_parse の注）。
       N-PORT が取れない ETF は落とす（空欄を合格にしない）。
  段3（重複）: 同じ業種・セクター（node）に複数あれば、Yahoo の月足の最初の完全な月が最も早い1本を代表にする
       （同じなら信託報酬の低いほう→記号の順）。版は二つ: etf_only（前身の HOLDRS の期間を切る・主）と
       spliced（Yahoo の系列そのまま・報告）。
  段3b（中身の重なり）: 代表どうしの今日の中身（N-PORT の株の重み）の重なり Σmin(w_A, w_B) が 50% 以上の組は、始まりの早い
       ほうだけ残す（同じ中身の node を二重に数えない。例: 不動産セクターと REIT）。

使うデータ（キャッシュ out/_nx_cache/・gitignore）
  - out/broker_lineup.json（リポジトリ内）
  - SEC: company_tickers_mf.json（記号→系列 ID）、browse-edgar の atom（系列の NPORT-P の一覧）、NPORT-P の primary_doc.xml
  - Yahoo の月足・日足（nx_common.yahoo と同じ URL とキャッシュ名＝調整後終値・配当込み）と、その生の JSON（終値・配当・時刻）
  - Ken French: F-F_Research_Data_Factors（Mkt・RF）・49_Industry_Portfolios・30_Industry_Portfolios（紙の双子）
  - FRED DEXJPUS（日次のドル円 → 月末値・税の報告用）

使い方:
  python3 night/nx_indmom_real_data.py             # 取得＋形の報告（JSON を標準出力へ）
  python3 night/nx_indmom_real_data.py --extract   # 測る道具が読む抽出 out/_nx_cache/nx_indmom_real_extract.json と sha を作る
  python3 night/nx_indmom_real_data.py --selftest  # 名前の規則・適格の判定（先読みなし）・K の式を合成データだけで点検
"""
import sys, os, re, io, json, time, math, hashlib, datetime, collections, urllib.request, urllib.parse, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as C  # noqa: E402

BASE = C.BASE
CACHE = C.CACHE
D = os.path.join(CACHE, 'nx_indmom_real')
EXTRACT = os.path.join(CACHE, 'nx_indmom_real_extract.json')
VERSION = 'nx_indmom_real_data v1 (2026-09-29)'
LINEUP = os.path.join(BASE, 'out', 'broker_lineup.json')
END = 202608            # 最後の完全な月（French も 2026-08 まで）。Yahoo の 2026-09（進行中）は使わない
MIN_N = 10              # 評価の始まり: 13か月の窓がそろう代表 ETF が MIN_N 本以上になった形成の月の翌月から（上位5の規則の 2K）
ELIG_MONTHS = 13        # 形成の月末 t に t−12〜t の13か月のリターンがそろう ETF だけが候補（全規則で同じ候補＝同じ土俵）
_EMAIL = re.search(r'^EMAIL\s*=\s*"([^"]+)"', open(os.path.join(BASE, 'hachimon_fetch.py'), encoding='utf-8').read(), re.M).group(1)
SEC_HDRS = {"User-Agent": f"hachimon-gate {_EMAIL}"}  # hachimon_fetch.py の HDRS と同じ形（ルール5）
SEC_INTERVAL = 0.25     # 4 req/s（10 req/s の制限を並走の道具と合わせても超えない）

# ───────────────────────── 段1: 名前の規則（凍結） ─────────────────────────
ISSUER = re.compile(r'^(State Street SPDR|State Street|SPDR|iShares|VanEck|First Trust|FT Vest|FT|Invesco|Vanguard|Global X|Direxion|'
                    r'ProShares|WisdomTree|Amplify|KraneShares|Roundhill|Tema|Themes|Tuttle Capital|GraniteShares|Leverage Shares|T-REX|'
                    r'REX|NEOS|JPMorgan|Goldman Sachs|Calamos|Militia|MUAM|ROBO Global|iPath ETN|iPath)\b\s*', re.I)
EXCLUDE_ORDER = [
    ('leveraged_inverse_single', re.compile(r'(?i)\b(2x|3x|1x|-1x|ultrapro|ultrashort|ultra|inverse|leveraged|yieldboost|weeklypay|autocallable|bull|bear|daily)\b')),
    ('bond_cash', re.compile(r'(?i)\b(bond|bd|treasury|treasuries|t-?bill|aggregate|corporate|corp|municipal|tips|floating|fltg|credit|high yield|hg yld|'
                             r'fallen|loan|mbs|mortgage.backed|duration|fixed income|investment grade|income allocation|preferred|prefrrd|convertible|'
                             r'inflation|short maturity|government|real return|tot rtn)\b')),
    ('commodity_etn_crypto', re.compile(r'(?i)\b(gold trust|gold shares|gold minishares|silver trust|commodity|cmmdty|commodities|agriculture fund|'
                                        r'gsci|etn|bitcoin|crypto|gold strategy)\b|\bdb\b')),
    ('option_income_overlay', re.compile(r'(?i)\b(premium income|covered call|buywrite|buffer|target income|high income|enhanced income|income blast|'
                                         r'risk managed|alternative income|arbitrage|income partners)\b')),
    ('smart_beta_active', re.compile(r'(?i)\b(alphadex|dividends?|div|dvd|quality|momentum|value|val|growth|equal weight(ed)?|low vol|moat|capital strength|'
                                     r'cash flow|aristocrats|achievers|esg|sustainable|gender|buyback|opportunities|dorsey|active|strategy|long/short|'
                                     r'tactical|opportunistic|select equity|superdividend|superincome|leaders|innovators|innovation|innovate|flexible|'
                                     r'smart beta|public-private|conscious)\b')),
    ('non_us', re.compile(r'(?i)\b(global|international|intl|internatnl|world|ex-us|ex us|emerging|em|eafe|acwi|europe|european|euro|eurozone|'
                          r'japan|china|chinext|csi|india|nifty|asia|pacific|latin|brazil|mexico|korea|south korea|taiwan|germany|dax|africa|'
                          r'vietnam|indonesia|malaysia|singapore|thailand|philippines|poland|turkey|kokusai|tokai|frontier|developed|devt|'
                          r'hedged|north american)\b')),
    ('broad_market_size', re.compile(r'(?i)(s&p 500|s&p500|\b500 index\b|nasdaq[- ]?100|nasdaq next gen|future gen|russell|total stock|total world|'
                                     r'mid[- ]?cap|small[- ]?cap|smallcap|midcap|largecap|large[- ]?cap|mega cap|dow 30|dow jones indust|'
                                     r's&p 100|extended market|1500|microcap|\bqqq\b|magnificent|fang|us equity|global 100|new econ)')),
]
# 細かい業種（GICS の産業・産業グループ・下位産業に当たる語）。node の名前は GICS に寄せた（French 49 への対応は FR49 に）
INDUSTRY = [
    ('SEMI', r'semiconductor'), ('BIOTECH', r'biotech'), ('PHARMA', r'pharmaceutical'), ('OILSVC', r'oil services?'),
    ('RETAIL', r'\bretail\b'), ('AERODEF', r'aerospace|\bdefen[cs]e\b'), ('STEEL', r'\bsteel\b'), ('GOLDMIN', r'gold miners'),
    ('SILVERMIN', r'silver miners'), ('COPPERMIN', r'copper miners'), ('URANIUM', r'uranium'), ('INTERNET', r'\binternet\b'),
    ('MREIT', r'mortgage real estate'), ('EQREIT', r'\breit\b'), ('MLP', r'\bmlp\b'),
]
# GICS の11セクター（粗い）
SECTOR = [
    ('S_TECH', r'\btechnology\b|information technology'), ('S_HEALTH', r'\bhealth ?care\b'), ('S_FIN', r'\bfinancials?\b|\bfinancial sel'),
    ('S_ENERGY', r'\benergy\b'), ('S_INDU', r'\bindustrials?\b|\bindustrial select'), ('S_MATER', r'\bmaterials\b'), ('S_UTIL', r'\butilities\b'),
    ('S_STAPLES', r'\bconsumer staples\b'), ('S_DISCR', r'\bconsumer disc'), ('S_COMM', r'\bcom(munication)? s(er)?v|\bcom svc'),
    ('S_REALEST', r'\breal estate\b'),
]
# テーマ（一つの GICS の産業ではなく、複数の産業をまたぐ筋書き）＝除く。業種・セクターの語より先に当てる
THEME = re.compile(r'(?i)\b(cybersecurity|cloud|artificial intelligence|ai|robotics|robotic|automation|blockchain|fintech|healthtech|genomics|'
                   r'social media|video games|esports|e-commerce|millennial|space|drone|photonics|photonic|optical|memory|nextg|'
                   r'smart mobility|autonomous|electric vehicles|industrial renaissance|defense tech|humanoid|physcl|clean|solar|wind|'
                   r'renewable|hydrogen|lithium|battery|rare earth|critical|strategic metals|smart grid|electrification|infrastructure|'
                   r'climatetech|water|agribusiness|agtech|timber|forestry|nuclear|metaverse|data center|kensho)\b')

# 段2（中身）の線
EQ_MIN = 90.0        # 株の買いが純資産の 90% 以上
US_MIN = 50.0        # その株のうち発行体の国が US のものが 50% 超（過半）
DERIV_MAX = 5.0      # デリバティブ（assetCat が D で始まる）と売り（payoffProfile Short）の |割合| の和が純資産の 5% 以下

# 前身の器（Yahoo が前身の系列をつないでいる記号）。★公開の事実（成績ではない）: 2011-12-20 に VanEck（当時 Market Vectors）が
# Merrill Lynch の HOLDRS（固定の銘柄の籠・預託証券）のうち5本を同じ記号の ETF に切り替えた。HOLDRS は指数の ETF ではない
# （組み入れの入れ替えが無く、買収された銘柄は現金で払い出され、100口単位）。etf_only 版はこの日より前の月を使わない
PREDECESSOR = {
    'SMH': {'kind': 'Semiconductor HOLDRS', 'etf_from': '2011-12-20', 'first_etf_full_month': 201201},
    'BBH': {'kind': 'Biotech HOLDRS', 'etf_from': '2011-12-20', 'first_etf_full_month': 201201},
    'OIH': {'kind': 'Oil Service HOLDRS', 'etf_from': '2011-12-20', 'first_etf_full_month': 201201},
    'PPH': {'kind': 'Pharmaceutical HOLDRS', 'etf_from': '2011-12-20', 'first_etf_full_month': 201201},
    'RTH': {'kind': 'Retail HOLDRS', 'etf_from': '2011-12-20', 'first_etf_full_month': 201201},
}
# 設定日（発行会社の資料の値を私の記憶で置いた＝点検用。Yahoo の最初の足と 62 日以上ずれたら前身のつなぎを疑って印を付ける）
INCEPTION = {
    'XLB': '1998-12-16', 'XLE': '1998-12-16', 'XLF': '1998-12-16', 'XLI': '1998-12-16', 'XLK': '1998-12-16', 'XLP': '1998-12-16',
    'XLU': '1998-12-16', 'XLV': '1998-12-16', 'XLY': '1998-12-16', 'XLRE': '2015-10-07', 'XLC': '2018-06-18',
    'IYR': '2000-06-12', 'IBB': '2001-02-05', 'RWR': '2001-04-23', 'VOX': '2004-09-23', 'VGT': '2004-01-26', 'VHT': '2004-01-26',
    'VFH': '2004-01-26', 'VAW': '2004-01-26', 'VCR': '2004-01-26', 'VDC': '2004-01-26', 'VPU': '2004-01-26', 'VDE': '2004-09-23',
    'VIS': '2004-09-23', 'FDN': '2006-06-19', 'FBT': '2006-06-19', 'ITA': '2006-05-01', 'SLX': '2006-10-10', 'REM': '2007-05-01',
    'FRI': '2007-05-08', 'MLPA': '2012-04-18', 'BBRE': '2018-06-15', 'FTXL': '2016-09-20',
    'SMH': '2011-12-20', 'BBH': '2011-12-20', 'OIH': '2011-12-20', 'PPH': '2011-12-20', 'RTH': '2011-12-20',
}
BENCH = ['SPY', 'QQQ']
# 紙の双子（French 49）への対応（報告 R 用・結果を見る前に固定。多対多で、REIT は French では Fin の中にあるので対応なし）
FR49 = {'SEMI': ['Chips'], 'BIOTECH': ['Drugs'], 'PHARMA': ['Drugs'], 'OILSVC': ['Oil'], 'RETAIL': ['Rtail'], 'AERODEF': ['Aero', 'Guns'],
        'STEEL': ['Steel'], 'GOLDMIN': ['Gold'], 'INTERNET': [], 'EQREIT': [], 'MREIT': [], 'MLP': [], 'URANIUM': [], 'SILVERMIN': [],
        'COPPERMIN': []}

# ───────────────────────── 規則の台帳（宣言だけ・測る道具が組む） ─────────────────────────
# 記法: 形成の月末 t に、t−(skip+L−1)〜t−skip の L か月の累積リターンで並べ、t+1 月を持つ。
RULES = {
    'P1_G3_12_1_top5': {'kind': 'topk', 'L': 12, 'skip': 1, 'K': 5, 'H': 1,
                        'what': '12か月（t−12〜t−1＝直近1か月をあける）の累積の上位5本を等分・毎月（課題文の形・nx_pre1926x の A_G3 の1か月あけた版と同じ）'},
    'P2_G3_12_0_top5': {'kind': 'topk', 'L': 12, 'skip': 0, 'K': 5, 'H': 1,
                        'what': '12か月（t−11〜t）の累積の上位5本を等分・毎月（eknzbh の G3_mom12_5 そのまま＝『m−12〜m−1』）'},
    'P3_MG_6_6': {'kind': 'topk', 'L': 6, 'skip': 0, 'frac': 0.15, 'H': 6,
                  'what': 'Moskowitz-Grinblatt 6-6（eknzbh の F1b そのまま）: 6か月（t−5〜t）の上位 K=max(2, floor(0.15N+0.5)) 本を等分し6か月持つ重ね持ち（6つの組を1/6ずつ・組の中は毎月等分に戻す・組がそろうまでは既にある組で等分）'},
    'P4_P9_multi_top5': {'kind': 'multi', 'windows': [1, 3, 6, 12], 'skip': 0, 'K': 5, 'H': 1,
                         'what': '1・3・6・12か月（どれも t で終わる）の累積の百分位（(順位−1)/(N−1)・同順位は平均）の平均の上位5本を等分・毎月（eknzbh の P9_multi_5）'},
    'P5_F3g_12_1_K30': {'kind': 'topk', 'L': 11, 'skip': 1, 'frac': 0.30, 'H': 1,
                        'what': '12-1（t−11〜t−1）の上位 K=max(2, floor(0.30N+0.5)) 本を等分・毎月（eknzbh の F3g_ind30_12-1_H1_K30 の形）'},
}
REFERENCE = {
    'REF_EW_menu': '同じ月の候補（代表 ETF）を全部等分・毎月（勢いを除いた『業種 ETF を並べて持つだけ』）',
    'REF_bridge_eknzbh_K3_R12': 'eknzbh 第7族の K1 の形（12か月＝t−11〜t の上位3・等分・毎月）を同じ母集団で（橋渡し・報告）',
    'REF_bridge_eknzbh_K3_BL': 'eknzbh 第7族の K3 の形（(r1+r3+r6+r12)/4 の上位3）を同じ母集団で（橋渡し・報告）',
}


def rules_sha():
    return hashlib.sha256(json.dumps({'RULES': RULES, 'MIN_N': MIN_N, 'ELIG_MONTHS': ELIG_MONTHS, 'END': END},
                                     sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def k_of(spec, n):
    """選ぶ本数。固定 K か、割合なら max(2, floor(frac·N + 0.5))（Python の round の偶数丸めを使わない）"""
    if 'K' in spec:
        return spec['K']
    return max(2, int(math.floor(spec['frac'] * n + 0.5)))


# ───────────────────────── 月の算術 ─────────────────────────
def madd(ym, k):
    y, m = divmod(ym, 100)
    t = y * 12 + (m - 1) + k
    return (t // 12) * 100 + t % 12 + 1


def months(a, z):
    out, m = [], a
    while m <= z:
        out.append(m)
        m = madd(m, 1)
    return out


# ───────────────────────── 段1 ─────────────────────────
def strip_issuer(nm):
    core = nm or ''
    for _ in range(2):
        core = ISSUER.sub('', core).strip()
    return core


def classify_name(nm):
    """→ (stage1, node, reason)。stage1 ∈ {'industry','sector','excluded'}"""
    if not (nm or '').strip():
        return 'excluded', None, 'name_empty（取扱終了の残骸か不明・名前で判定できない）'
    core = strip_issuer(nm)
    for key, rx in EXCLUDE_ORDER:
        m = rx.search(core)
        if m:
            return 'excluded', None, f'{key}（語: {m.group(0)}）'
    th = THEME.search(core)
    if th:
        return 'excluded', None, f'theme（語: {th.group(0)}）'
    for node, rx in INDUSTRY:
        if re.search(rx, core, re.I):
            return 'industry', node, 'industry_word'
    for node, rx in SECTOR:
        if re.search(rx, core, re.I):
            return 'sector', node, 'sector_word'
    return 'excluded', None, 'no_industry_or_sector_word'


def stage1(lineup=None):
    lineup = lineup or json.load(open(LINEUP))['etfs']
    out = {}
    for t in sorted(lineup):
        v = lineup[t]
        s1, node, why = classify_name(v.get('nm', ''))
        out[t] = {'nm': v.get('nm', ''), 'er': v.get('er', ''), 'mkt': v.get('mkt', ''), 'stage1': s1, 'node': node, 'why': why}
    return out


# ───────────────────────── 段2: SEC N-PORT ─────────────────────────
_last_sec = [0.0]


def sec_get(url, name, max_age_days=60, tries=4):
    os.makedirs(D, exist_ok=True)
    p = os.path.join(D, name)
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < max_age_days * 86400 and os.path.getsize(p) > 0:
        return open(p, 'rb').read()
    err = None
    for i in range(tries):
        wait = SEC_INTERVAL - (time.time() - _last_sec[0])
        if wait > 0:
            time.sleep(wait)
        _last_sec[0] = time.time()
        try:
            b = urllib.request.urlopen(urllib.request.Request(url, headers=SEC_HDRS), timeout=120).read()
            tmp = f'{p}.{os.getpid()}.tmp'
            open(tmp, 'wb').write(b)
            os.replace(tmp, p)
            return b
        except Exception as e:  # noqa
            err = e
            time.sleep(2 ** (i + 1))
    raise RuntimeError(f'SEC 取得失敗 {url}: {err}')


def mf_map():
    j = json.loads(sec_get('https://www.sec.gov/files/company_tickers_mf.json', 'company_tickers_mf.json', max_age_days=30))
    f = j['fields']
    return {r[f.index('symbol')]: {'cik': r[f.index('cik')], 'seriesId': r[f.index('seriesId')], 'classId': r[f.index('classId')]} for r in j['data']}


def nport_list(series_id):
    u = f'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={series_id}&type=NPORT-P&dateb=&owner=include&count=40&output=atom'
    b = sec_get(u, f'atom_{series_id}.xml').decode('latin-1')
    out = []
    for e in re.findall(r'<entry>(.*?)</entry>', b, re.S):
        acc = re.search(r'<accession-number>([^<]+)<', e)
        fd = re.search(r'<filing-date>([^<]+)<', e)
        href = re.search(r'<filing-href>([^<]+)<', e)
        ftype = re.search(r'<filing-type>([^<]+)<', e)
        if acc and href:
            cik = re.search(r'/data/(\d+)/', href.group(1))
            out.append({'acc': acc.group(1), 'filed': fd.group(1) if fd else None, 'cik': cik.group(1) if cik else None,
                        'type': ftype.group(1) if ftype else None})
    return out


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def nport_parse(xml):
    """NPORT-P の primary_doc.xml → 中身の割合（純資産に対する %）。
    ★US の判定は二つの印の両方: invCountry == 'US'（N-PORT の『投資・発行体の国』）かつ ISIN の頭2文字が 'US'（ISIN が無ければ invCountry だけ）。
      理由（形の点検で分かった・成績ではない）: invCountry は届け出る会社ごとに意味がずれる（Global X の金鉱株・銀鉱株の ETF は
      カナダ・メキシコの鉱山会社にも US を付けていて US が 58〜76% に見えた。VanEck の同種は 9〜16%）。ISIN だけだと ADR
      （TSM・ASML の米国の預託証券）が US に数えられる。両方が US と言う株だけを US とする（厳しい側）"""
    g = lambda tag: (re.search(rf'<{tag}>([^<]*)</{tag}>', xml) or [None, None])[1]
    res = {'seriesId': g('seriesId'), 'seriesName': g('seriesName'), 'repPdDate': g('repPdDate'), 'netAssets': _f(g('netAssets')),
           'n_hold': 0, 'eq_long_pct': 0.0, 'eq_us_pct': 0.0, 'eq_us_invcountry_pct': 0.0, 'eq_us_isin_pct': 0.0,
           'deriv_short_abs_pct': 0.0, 'other_pct': 0.0, 'by_country_top': {}, 'assetCat': collections.Counter()}
    ctry = collections.Counter()
    hold = collections.Counter()
    for blk in re.findall(r'<invstOrSec>(.*?)</invstOrSec>', xml, re.S):
        pv = _f((re.search(r'<pctVal>([^<]*)</pctVal>', blk) or [None, None])[1]) or 0.0
        cat = (re.search(r'<assetCat>([^<]*)</assetCat>', blk) or [None, ''])[1]
        if not cat:
            m = re.search(r'<assetConditional[^>]*assetCat="([^"]+)"', blk)
            cat = m.group(1) if m else 'NA'
        prof = (re.search(r'<payoffProfile>([^<]*)</payoffProfile>', blk) or [None, ''])[1]
        cty = (re.search(r'<invCountry>([^<]*)</invCountry>', blk) or [None, 'NA'])[1]
        isin = (re.search(r'<isin value="([A-Z0-9]+)"', blk) or [None, None])[1]
        is_deriv = cat.startswith('D') or '<derivativeInfo>' in blk
        res['n_hold'] += 1
        res['assetCat'][cat] += 1
        if is_deriv or prof == 'Short':
            res['deriv_short_abs_pct'] += abs(pv)
        elif cat in ('EC', 'EP') and prof in ('Long', ''):
            res['eq_long_pct'] += pv
            ctry[cty] += pv
            cus = (re.search(r'<cusip>([^<]*)</cusip>', blk) or [None, None])[1]
            nmh = (re.search(r'<name>([^<]*)</name>', blk) or [None, ''])[1]
            key = isin or (f'CUSIP:{cus}' if cus and cus.strip('0N/A ') else f'NAME:{nmh.strip().upper()}')
            hold[key] += pv
            us_c = cty == 'US'
            us_i = (isin[:2] == 'US') if isin else us_c
            if us_c:
                res['eq_us_invcountry_pct'] += pv
            if us_i:
                res['eq_us_isin_pct'] += pv
            if us_c and us_i:
                res['eq_us_pct'] += pv
        else:
            res['other_pct'] += pv
    e = res['eq_long_pct']
    res['us_share_of_eq'] = round(100 * res['eq_us_pct'] / e, 2) if e > 0 else None
    res['us_share_invcountry_only'] = round(100 * res['eq_us_invcountry_pct'] / e, 2) if e > 0 else None
    res['us_share_isin_only'] = round(100 * res['eq_us_isin_pct'] / e, 2) if e > 0 else None
    res['by_country_top'] = {k: round(v, 2) for k, v in ctry.most_common(6)}
    tot = sum(hold.values())
    res['holdings_w'] = {k: v / tot for k, v in hold.items()} if tot > 0 else {}   # 株の買いだけを 1 に直した重み（重なりの計算用）
    res['assetCat'] = dict(res['assetCat'])
    for k in ('eq_long_pct', 'eq_us_pct', 'eq_us_invcountry_pct', 'eq_us_isin_pct', 'deriv_short_abs_pct', 'other_pct'):
        res[k] = round(res[k], 2)
    return res


def nport_for(ticker, mf):
    """最新の NPORT-P と、一覧の最も古いもの（安定の点検）を読む → {'latest':…, 'oldest':…} か {'error':…}"""
    m = mf.get(ticker)
    if not m:
        return {'error': 'company_tickers_mf に記号が無い（40年法のファンドでない・名前が変わった等）'}
    try:
        lst = [x for x in nport_list(m['seriesId']) if (x['type'] or 'NPORT-P').upper().startswith('NPORT-P')]
    except Exception as e:  # noqa
        return {'error': f'atom 取得失敗: {e}', 'seriesId': m['seriesId']}
    if not lst:
        return {'error': 'NPORT-P が一覧に無い', 'seriesId': m['seriesId']}
    out = {'seriesId': m['seriesId'], 'n_listed': len(lst)}
    for tag, x in (('latest', lst[0]), ('oldest', lst[-1])):
        try:
            xml = sec_get(f"https://www.sec.gov/Archives/edgar/data/{x['cik']}/{x['acc'].replace('-', '')}/primary_doc.xml",
                          f"nport_{x['acc']}.xml", max_age_days=3650).decode('utf-8', 'replace')
            r = nport_parse(xml)
            r['acc'], r['filed'] = x['acc'], x['filed']
            if r['seriesId'] != m['seriesId']:
                r['warn'] = f"系列 ID が違う（{r['seriesId']} ≠ {m['seriesId']}）"
            out[tag] = r
        except Exception as e:  # noqa
            out[tag] = {'error': str(e)}
    return out


def stage2_pass(np_):
    lt = np_.get('latest') or {}
    if 'error' in np_ or 'error' in lt or not lt:
        return False, 'N-PORT が取れない（空欄を合格にしない）'
    if lt.get('seriesId') and np_.get('seriesId') and lt['seriesId'] != np_['seriesId']:
        return False, '系列 ID の不一致'
    if lt['eq_long_pct'] < EQ_MIN:
        return False, f"株の買いが純資産の {lt['eq_long_pct']}% < {EQ_MIN}%"
    if lt['us_share_of_eq'] is None or lt['us_share_of_eq'] <= US_MIN:
        return False, f"株のうち US の発行体が {lt['us_share_of_eq']}% ≤ {US_MIN}%"
    if lt['deriv_short_abs_pct'] > DERIV_MAX:
        return False, f"デリバティブ・売りが {lt['deriv_short_abs_pct']}% > {DERIV_MAX}%"
    return True, 'pass'


# ───────────────────────── Yahoo ─────────────────────────
def _yh_url(ticker, interval):
    # nx_common.yahoo と同じ URL の形とキャッシュ名（period2 は時刻で変わるがキャッシュ名は同じ＝同じファイルを共有する）
    return (f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?period1=0&period2={int(time.time())}'
            f'&interval={interval}&events=div%2Csplit'), f'yh_{ticker.replace("^", "IDX_").replace("=", "_")}_{interval}.json'


def yahoo_raw(ticker, interval='1mo'):
    u, name = _yh_url(ticker, interval)
    return json.loads(C.get(u, name=name, max_age_days=3))


def yahoo_shape(ticker):
    """月足の形の点検（成績は出さない）: 月の切り方（UTC と市場の時差 gmtoffset で同じ月になるか）・月の重複・進行中の月・
    最初の足・firstTradeDate・通貨・種類・配当の件数・px_guard の台帳との比較"""
    j = yahoo_raw(ticker, '1mo')
    r = j['chart']['result'][0]
    meta = r.get('meta') or {}
    ts = r.get('timestamp') or []
    gmt = meta.get('gmtoffset') or 0
    adj = (r['indicators'].get('adjclose') or [{}])[0].get('adjclose') or []
    utc_keys, loc_keys, odd = [], [], []
    for i, t in enumerate(ts):
        du = datetime.datetime.utcfromtimestamp(t)
        dl = datetime.datetime.utcfromtimestamp(t + gmt)
        utc_keys.append(du.year * 100 + du.month)
        loc_keys.append(dl.year * 100 + dl.month)
        if i < len(ts) - 1 and not (dl.day == 1 and dl.hour == 0 and dl.minute == 0):
            odd.append(dl.strftime('%Y-%m-%d %H:%M'))
    mism = sum(1 for a, b in zip(utc_keys, loc_keys) if a != b)
    dup = [k for k, c in collections.Counter(utc_keys).items() if c > 1]
    none_adj = sum(1 for a in adj if a is None)
    divs = (r.get('events') or {}).get('dividends') or {}
    splits = (r.get('events') or {}).get('splits') or {}
    ftd = meta.get('firstTradeDate')
    first_bar = datetime.datetime.utcfromtimestamp(ts[0] + gmt).strftime('%Y-%m-%d') if ts else None
    try:
        import px_guard as PXG
        kf = PXG.known_first(ticker)
    except Exception:  # noqa
        kf = None
    return {'first_bar': first_bar, 'firstTradeDate': datetime.datetime.utcfromtimestamp(ftd + gmt).strftime('%Y-%m-%d') if ftd else None,
            'last_bar': datetime.datetime.utcfromtimestamp(ts[-1] + gmt).strftime('%Y-%m-%d %H:%M') if ts else None,
            'n_bars': len(ts), 'utc_vs_market_month_mismatch': mism, 'dup_months': dup, 'bars_not_at_market_midnight_excl_last': odd[:5],
            'n_bars_not_at_market_midnight_excl_last': len(odd), 'adjclose_none': none_adj, 'n_dividends': len(divs), 'n_splits': len(splits),
            'currency': meta.get('currency'), 'instrumentType': meta.get('instrumentType'), 'exchangeTimezoneName': meta.get('exchangeTimezoneName'),
            'gmtoffset': gmt, 'px_guard_known_first': kf}


def yahoo_monthly(ticker):
    """調整後の月次リターン（nx_common.yahoo そのもの・UTC で月を切る）を END までに切る＋終値のリターンと配当（税の報告用）"""
    adj = {k: v for k, v in C.yahoo(ticker, '1mo').items() if k <= END}
    j = yahoo_raw(ticker, '1mo')
    r = j['chart']['result'][0]
    q = r['indicators']['quote'][0]
    close = {}
    for t, c in zip(r['timestamp'], q.get('close') or []):
        if c is None:
            continue
        d = datetime.datetime.utcfromtimestamp(t)
        close[d.year * 100 + d.month] = c
    ks = sorted(close)
    cret = {k: close[k] / close[p] - 1 for p, k in zip(ks, ks[1:]) if k <= END}
    div = collections.defaultdict(float)
    for ev in ((r.get('events') or {}).get('dividends') or {}).values():
        d = datetime.datetime.utcfromtimestamp(ev['date'])
        ym = d.year * 100 + d.month
        if ym <= END:
            div[ym] += ev['amount']
    # 配当利回り（月）= その月の配当 ÷ 前月末の終値（Yahoo の close は分割調整済み・配当は未調整）
    dy = {}
    for p, k in zip(ks, ks[1:]):
        if k <= END and div.get(k):
            dy[k] = div[k] / close[p]
    return adj, cret, dy


def yahoo_daily(ticker):
    return {k: v for k, v in C.yahoo(ticker, '1d').items() if k // 100 <= END}


# ───────────────────────── 適格・代表 ─────────────────────────
def first_full_month(ret):
    return min(ret) if ret else None


def start_month(ticker, ret, variant):
    s = first_full_month(ret)
    if s is None:
        return None
    if variant == 'etf_only' and ticker in PREDECESSOR:
        s = max(s, PREDECESSOR[ticker]['first_etf_full_month'])
    return s


def eligible(ret_by_t, t, start_by_t):
    """形成の月末 t に候補になれる記号: t−12〜t の13か月すべてにリターンがあり、どれも start 以降（t より後の月は見ない）"""
    out = []
    need = months(madd(t, -(ELIG_MONTHS - 1)), t)
    for k, r in ret_by_t.items():
        s = start_by_t.get(k)
        if s is None or need[0] < s:
            continue
        if all(m in r for m in need):
            out.append(k)
    return sorted(out)


def choose_reps(cands, starts, er):
    """node ごとに代表1本: 最初の完全な月が最も早い → 信託報酬が低い → 記号の順"""
    by = collections.defaultdict(list)
    for t, node in cands.items():
        if starts.get(t) is not None:
            by[node].append(t)
    reps = {}
    for node, ts in sorted(by.items()):
        ts.sort(key=lambda x: (starts[x], _f(er.get(x)) if _f(er.get(x)) is not None else 9.9, x))
        reps[node] = {'rep': ts[0], 'others': ts[1:]}
    return reps


OVERLAP_MAX = 0.50   # 二つの代表の中身の重なり Σ min(w_A, w_B)（今日の N-PORT）が 50% 以上なら同じ node とみなす（過半）


def overlap(ha, hb):
    return sum(min(v, hb.get(k, 0.0)) for k, v in ha.items()) if ha and hb else None


def dedup_overlap(reps, starts, er, hold):
    """段3b: 代表どうしの中身の重なりが OVERLAP_MAX 以上の組は、始まりの早いほう（同じなら信託報酬の低いほう→記号）だけ残す。
    重なりの大きい組から順に裁く。落ちた node と相手・重なりを記録する"""
    rep_t = {n: x['rep'] for n, x in reps.items()}
    pairs = []
    ns = sorted(rep_t)
    for i, a in enumerate(ns):
        for b in ns[i + 1:]:
            o = overlap(hold.get(rep_t[a]), hold.get(rep_t[b]))
            if o is not None and o >= OVERLAP_MAX:
                pairs.append((o, a, b))
    dropped = {}
    key = lambda n: (starts[rep_t[n]], _f(er.get(rep_t[n])) if _f(er.get(rep_t[n])) is not None else 9.9, rep_t[n])
    for o, a, b in sorted(pairs, reverse=True):
        if a in dropped or b in dropped:
            continue
        keep, drop = (a, b) if key(a) <= key(b) else (b, a)
        dropped[drop] = {'rep': rep_t[drop], 'overlap_with': keep, 'kept_rep': rep_t[keep], 'overlap': round(o, 3)}
    kept = {n: x for n, x in reps.items() if n not in dropped}
    return kept, dropped


# ───────────────────────── 形の報告 ─────────────────────────
def build(verbose=True):
    S1 = stage1()
    lineup = json.load(open(LINEUP))['etfs']
    cnt = collections.Counter(v['why'].split('（')[0] for v in S1.values())
    cand = {t: v for t, v in S1.items() if v['stage1'] in ('industry', 'sector')}
    mf = mf_map()
    NP, S2 = {}, {}
    for t in sorted(cand):
        NP[t] = nport_for(t, mf)
        ok, why = stage2_pass(NP[t])
        S2[t] = {'pass': ok, 'why': why}
        if verbose:
            lt = NP[t].get('latest') or {}
            print(f"  N-PORT {t:5s} {cand[t]['node']:10s} eq={lt.get('eq_long_pct')} us/eq={lt.get('us_share_of_eq')} (inv {lt.get('us_share_invcountry_only')} / isin {lt.get('us_share_isin_only')}) "
                  f"der={lt.get('deriv_short_abs_pct')} rep={lt.get('repPdDate')} → {ok} {why}", file=sys.stderr)
    passed = {t: cand[t]['node'] for t in cand if S2[t]['pass']}
    # Yahoo
    RET, CRET, DY, SHAPE = {}, {}, {}, {}
    for t in sorted(set(passed) | set(BENCH)):
        try:
            SHAPE[t] = yahoo_shape(t)
            RET[t], CRET[t], DY[t] = yahoo_monthly(t)
        except Exception as e:  # noqa
            SHAPE[t] = {'error': str(e)}
    er = {t: lineup.get(t, {}).get('er') for t in passed}
    starts = {v: {t: start_month(t, RET.get(t, {}), v) for t in passed} for v in ('etf_only', 'spliced')}
    reps0 = {v: choose_reps(passed, starts[v], er) for v in ('etf_only', 'spliced')}
    hold = {t: (NP[t].get('latest') or {}).get('holdings_w') or {} for t in passed}
    reps, dropped_overlap = {}, {}
    for v in ('etf_only', 'spliced'):
        reps[v], dropped_overlap[v] = dedup_overlap(reps0[v], starts[v], er, hold)
    ov_matrix = {}
    rset = sorted({x['rep'] for v in reps0.values() for x in v.values()})
    for i, a in enumerate(rset):
        for b in rset[i + 1:]:
            o = overlap(hold.get(a), hold.get(b))
            if o is not None and o >= 0.10:
                ov_matrix[f'{a}-{b}'] = round(o, 3)
    # 各月の候補の数（代表だけ）と評価の始まり
    menu = {}
    for v in ('etf_only', 'spliced'):
        rep_t = {n: x['rep'] for n, x in reps[v].items()}
        for uname, pick in (('U_all', lambda n: True), ('U_narrow', lambda n: not n.startswith('S_')), ('U_sector', lambda n: n.startswith('S_'))):
            ts = {rep_t[n]: RET[rep_t[n]] for n in rep_t if pick(n) and rep_t[n] in RET}
            st = {k: starts[v][k] for k in ts}
            ncount, t0 = {}, None
            for t in months(199901, madd(END, -1)):
                e = eligible(ts, t, st)
                ncount[t] = len(e)
                if t0 is None and len(e) >= MIN_N:
                    t0 = t
            menu[f'{v}:{uname}'] = {'n_nodes': len(ts), 'first_formation_month_N_ge_MIN_N': t0,
                                    'eval_from': madd(t0, 1) if t0 else None, 'eval_to': END,
                                    'eval_months': len(months(madd(t0, 1), END)) if t0 else 0,
                                    'N_by_year_end': {str(y): ncount.get(y * 100 + 12) for y in range(1999, 2026)},
                                    'N_at_last_formation': ncount.get(madd(END, -1))}
    # 前身・設定日の点検
    incep_flags = {}
    for t in passed:
        sh = SHAPE.get(t, {})
        if t in INCEPTION and sh.get('first_bar'):
            gap = (datetime.date.fromisoformat(INCEPTION[t]) - datetime.date.fromisoformat(sh['first_bar'])).days
            if abs(gap) > 62:
                incep_flags[t] = {'inception': INCEPTION[t], 'yahoo_first_bar': sh['first_bar'], 'days_yahoo_earlier': gap,
                                  'handled_by_PREDECESSOR': t in PREDECESSOR}
    report = {
        'version': VERSION, 'end': END, 'rules_sha256': rules_sha(),
        'stage1_counts': dict(cnt), 'stage1_candidates': {t: {'nm': v['nm'], 'node': v['node'], 'stage1': v['stage1'], 'er': v['er']} for t, v in sorted(cand.items())},
        'stage2': {t: {'pass': S2[t]['pass'], 'why': S2[t]['why'],
                       'latest': {k: (NP[t].get('latest') or {}).get(k) for k in ('repPdDate', 'seriesName', 'eq_long_pct', 'us_share_of_eq', 'us_share_invcountry_only', 'us_share_isin_only', 'deriv_short_abs_pct', 'other_pct', 'n_hold', 'by_country_top')},
                       'oldest': {k: (NP[t].get('oldest') or {}).get(k) for k in ('repPdDate', 'eq_long_pct', 'us_share_of_eq', 'us_share_invcountry_only', 'us_share_isin_only', 'deriv_short_abs_pct', 'n_hold')},
                       'error': NP[t].get('error')} for t in sorted(cand)},
        'passed_nodes': passed,
        'reps_before_overlap': reps0, 'reps': reps, 'dropped_by_overlap': dropped_overlap, 'overlap_ge_10pct_between_candidate_reps': ov_matrix,
        'starts': starts, 'menu': menu, 'inception_flags': incep_flags,
        'yahoo_shape': SHAPE,
    }
    return report, {'RET': RET, 'CRET': CRET, 'DY': DY, 'passed': passed, 'reps': reps, 'reps0': reps0, 'dropped_overlap': dropped_overlap,
                    'overlap': ov_matrix, 'starts': starts, 'S1': S1, 'S2': S2, 'NP': NP}


def build_extract():
    rep, X = build(verbose=True)
    reps_all = sorted({x['rep'] for v in X['reps'].values() for x in v.values()})
    daily = {}
    for t in reps_all + BENCH:
        try:
            daily[t] = yahoo_daily(t)
        except Exception as e:  # noqa
            daily[t] = {'error': str(e)}
    ff = C.ff_factors()
    fr49 = C.french_series('49_Industry_Portfolios', 'Value Weight')
    fr30 = C.french_series('30_Industry_Portfolios', 'Value Weight')
    cut = lambda d: {k: v for k, v in d.items() if 199801 <= k <= END}
    fx_raw = C.get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXJPUS', name='fred_DEXJPUS.csv', max_age_days=7).decode()
    fx = {}
    for line in fx_raw.splitlines()[1:]:
        a, _, b = line.partition(',')
        try:
            v = float(b)
        except ValueError:
            continue
        ym = int(a[:4]) * 100 + int(a[5:7])
        if 199801 <= ym <= END:
            fx[ym] = v  # 行は日付の昇順＝最後に残るのがその月の最後の値（月末値）
    data = {
        'end': END, 'rules': RULES, 'min_n': MIN_N, 'elig_months': ELIG_MONTHS,
        'universe': {'stage1': X['S1'], 'stage2': X['S2'], 'passed_nodes': X['passed'], 'reps_before_overlap': X['reps0'], 'reps': X['reps'],
                     'dropped_by_overlap': X['dropped_overlap'], 'overlap_matrix': X['overlap'], 'starts': X['starts'],
                     'predecessor': PREDECESSOR, 'overlap_max': OVERLAP_MAX,
                     'nport_latest': {t: {k: v for k, v in (X['NP'][t].get('latest') or {}).items() if k != 'holdings_w'} for t in X['NP']}},
        'ret_m': {t: {str(k): v for k, v in X['RET'][t].items()} for t in X['RET']},
        'close_ret_m': {t: {str(k): v for k, v in X['CRET'][t].items()} for t in X['CRET']},
        'div_yield_m': {t: {str(k): v for k, v in X['DY'][t].items()} for t in X['DY']},
        'ret_d': {t: ({str(k): v for k, v in d.items()} if 'error' not in d else d) for t, d in daily.items()},
        'french': {'mkt': {str(k): v for k, v in cut(ff['mkt']).items()}, 'rf': {str(k): v for k, v in cut(ff['rf']).items()},
                   'ind49': {c: {str(k): v for k, v in cut(s).items()} for c, s in fr49.items()},
                   'ind30': {c: {str(k): v for k, v in cut(s).items()} for c, s in fr30.items()}},
        'fx_usdjpy_month_end': {str(k): v for k, v in fx.items()},
    }
    sha = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    os.makedirs(CACHE, exist_ok=True)
    json.dump({'version': VERSION, 'sha256_data': sha, 'rules_sha256': rules_sha(), 'data': data}, open(EXTRACT, 'w'))
    rep['extract'] = {'path': EXTRACT, 'bytes': os.path.getsize(EXTRACT), 'sha256_data': sha,
                      'daily_first': {t: (min(d) if d and 'error' not in d else d) for t, d in daily.items()},
                      'french_last': {'mkt': max(ff['mkt']), 'ind49': max(max(s) for s in fr49.values() if s), 'ind30': max(max(s) for s in fr30.values() if s)},
                      'fx_months': [min(fx), max(fx), len(fx)]}
    # 相手どうしの形（規則の成績ではない）: SPY と French Mkt の月次の相関・差の最大
    spy, mkt = X['RET'].get('SPY', {}), ff['mkt']
    ks = [k for k in spy if k in mkt and k >= 199401]
    if ks:
        rep['sanity_spy_vs_french_mkt'] = {'months': len(ks), 'corr': round(C.corr([spy[k] for k in ks], [mkt[k] for k in ks]), 4),
                                           'max_abs_monthly_diff_pct': round(100 * max(abs(spy[k] - mkt[k]) for k in ks), 2)}
    return rep


def load_extract(check_sha=None):
    x = json.load(open(EXTRACT))
    sha = hashlib.sha256(json.dumps(x['data'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if sha != x['sha256_data'] or (check_sha and sha != check_sha):
        raise SystemExit(f'抽出の sha が違う: {sha}（登録 {check_sha}）＝止まる')
    if rules_sha() != x['rules_sha256']:
        raise SystemExit('RULES が抽出の時点と違う＝止まる')
    return x['data']


# ───────────────────────── 自己点検（合成データだけ） ─────────────────────────
def selftest():
    ok = []
    # 1) 名前の規則（固定の例）
    exp = {
        'VanEck Semiconductor ETF': ('industry', 'SEMI'), 'iShares Biotechnology ETF': ('industry', 'BIOTECH'),
        'State Street Technology Select Sector SPDR ETF': ('sector', 'S_TECH'), 'Global X MLP ETF': ('industry', 'MLP'),
        'Global X Cybersecurity ETF': ('excluded', None), 'Direxion Daily Semiconductor Bull 3X ETF': ('excluded', None),
        'iShares Global Energy ETF': ('excluded', None), 'First Trust Health Care AlphaDEX Fund': ('excluded', None),
        'iShares Mortgage Real Estate ETF': ('industry', 'MREIT'), 'iShares US Real Estate ETF': ('sector', 'S_REALEST'),
        'Global X US Infrastructure Development ETF': ('excluded', None), '': ('excluded', None),
        'GraniteShares YieldBOOST Semiconductor ETF': ('excluded', None), 'iShares US Aerospace & Defense ETF': ('industry', 'AERODEF'),
        'Global X Defense Tech ETF': ('excluded', None), 'State Street SPDR Dow Jones REIT ETF': ('industry', 'EQREIT'),
        'Global X SuperDividend REIT ETF': ('excluded', None), 'Vanguard Communication Services Index Fund ETF': ('sector', 'S_COMM'),
        'State Street Com Svc Sel Sec SPDR ETF': ('sector', 'S_COMM'), 'First Trust Dow Jones International Internet ETF': ('excluded', None),
    }
    bad = [(n, classify_name(n)[:2], e) for n, e in exp.items() if classify_name(n)[:2] != e]
    ok.append(('name_rules', not bad, bad))
    # 2) 適格は t より後の月を見ない（t より後を消しても結果が同じ）・13か月そろわないと入らない
    import random
    rnd = random.Random(1)
    R = {f'E{i}': {m: rnd.gauss(0, .05) for m in months(200001 + i, 202012)} for i in range(15)}
    st = {k: min(v) for k, v in R.items()}
    same = True
    for t in (200112, 200506, 201012):
        a = eligible(R, t, st)
        Rcut = {k: {m: x for m, x in v.items() if m <= t} for k, v in R.items()}
        same &= a == eligible(Rcut, t, st)
    ok.append(('eligibility_no_lookahead', same, None))
    e = eligible({'A': {m: 0.0 for m in months(200001, 200112)}}, 200101, {'A': 200001})   # 200001〜200101 の13か月
    e2 = eligible({'A': {m: 0.0 for m in months(200001, 200112)}}, 200012, {'A': 200001})  # 12か月しか無い
    ok.append(('eligibility_needs_13_months', e == ['A'] and e2 == [], (e, e2)))
    # 3) 前身の切り: etf_only では 2012-01 より前は始まらない
    ok.append(('predecessor_cut', start_month('SMH', {200006: 0.0, 201201: 0.0}, 'etf_only') == 201201 and
               start_month('SMH', {200006: 0.0}, 'spliced') == 200006, None))
    # 4) K の式（偶数丸めを使わない）
    ok.append(('k_formula', [k_of({'frac': .15}, n) for n in (10, 17, 22, 49)] == [2, 3, 3, 7] and
               [k_of({'frac': .30}, n) for n in (10, 15, 22, 49)] == [3, 5, 7, 15] and k_of({'K': 5}, 12) == 5, None))
    # 5) 代表の選び方
    r = choose_reps({'A': 'X', 'B': 'X', 'C': 'Y'}, {'A': 200101, 'B': 200001, 'C': 200501}, {'A': '0.1', 'B': '0.5', 'C': ''})
    ok.append(('choose_reps', r['X']['rep'] == 'B' and r['Y']['rep'] == 'C', r))
    # 6) N-PORT の解析（合成の XML）
    xml = ('<seriesId>S1</seriesId><seriesName>T</seriesName><repPdDate>2026-06-30</repPdDate><netAssets>100</netAssets>'
           '<invstOrSec><pctVal>50</pctVal><identifiers><isin value="US0079031078"/></identifiers><payoffProfile>Long</payoffProfile><assetCat>EC</assetCat><invCountry>US</invCountry></invstOrSec>'
           '<invstOrSec><pctVal>10</pctVal><identifiers><isin value="CA0679011084"/></identifiers><payoffProfile>Long</payoffProfile><assetCat>EC</assetCat><invCountry>US</invCountry></invstOrSec>'
           '<invstOrSec><pctVal>35</pctVal><identifiers><isin value="US8740391003"/></identifiers><payoffProfile>Long</payoffProfile><assetCat>EC</assetCat><invCountry>TW</invCountry></invstOrSec>'
           '<invstOrSec><pctVal>5</pctVal><payoffProfile>Long</payoffProfile><assetCat>STIV</assetCat><invCountry>US</invCountry></invstOrSec>')
    p = nport_parse(xml)
    ok.append(('nport_parse', p['eq_long_pct'] == 95.0 and abs(p['us_share_of_eq'] - 52.63) < .01 and abs(p['us_share_invcountry_only'] - 63.16) < .01
               and abs(p['us_share_isin_only'] - 89.47) < .01 and p['other_pct'] == 5.0, p))
    ok.append(('stage2_rule', stage2_pass({'seriesId': 'S1', 'latest': p})[0] is True and
               stage2_pass({'seriesId': 'S1', 'latest': dict(p, us_share_of_eq=50.0)})[0] is False and
               stage2_pass({'error': 'x'})[0] is False, None))
    # 7) 中身の重なりで重複を落とす
    reps = {'S_REALEST': {'rep': 'A', 'others': []}, 'EQREIT': {'rep': 'B', 'others': []}, 'SEMI': {'rep': 'C', 'others': []}}
    hold = {'A': {'x': .5, 'y': .5}, 'B': {'x': .45, 'y': .35, 'z': .2}, 'C': {'q': 1.0}}
    kept, dropped = dedup_overlap(reps, {'A': 200007, 'B': 200105, 'C': 201201}, {'A': '0.4', 'B': '0.25', 'C': '0.35'}, hold)
    ok.append(('dedup_overlap', set(kept) == {'S_REALEST', 'SEMI'} and dropped.get('EQREIT', {}).get('overlap') == 0.8, (kept, dropped)))
    for name, good, info in ok:
        print(('OK  ' if good else 'NG  ') + name + ('' if good else f'  {info}'))
    return all(g for _, g, _ in ok)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--extract', action='store_true')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        sys.exit(0 if selftest() else 1)
    if a.extract:
        rep = build_extract()
    else:
        rep, _ = build()
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
