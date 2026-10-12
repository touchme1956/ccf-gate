#!/usr/bin/env python3
"""night/bestpf_themes.py — bestpf の R4（主題）: 「これから伸びると言われる主題は、株主のリターンになるか」

事前登録 out/bestpf_prereg.json（7c4b672）の modules.R4_themes に従って測る（読むだけ・門・採点・配分は変えない）。
  予想（測る前）: 主題 ETF は上場後に SPY に負けやすい（中央値 −3〜−6%/年）。伸びる産業でも株主が報われるとは限らない

測るもの
  1. 主題 ETF（取れた76本＋取れなかった3本）を、上場の翌月から 2026-09 まで、同じ窓の SPY（配当込み）と比べる。
     上場後3年・5年の差・SPY に勝った割合・中央値。上場の時期（上場の前の24か月にその主題が市場に勝っていたか）。
  2. 上場からの月数をそろえた平均（Ben-David ほかの図2と同じ形・ただし素のリターンの差）と、
     「上場から5年以内の本だけ」を毎月等分に持つ暦の上のポートフォリオ。
  3. 同じ主題で後から出た本の時期（最初の本の値で、各上場の時点から3年先）。
  4. 今の値段と人気（Yahoo の表示 PER・資産額・経費率・直近3年の SPY との差）。
  5. 日本の改革（東証の要請 2023-03 以降）とインドは、上場の時期ではなく今の位置で見る。
  6. 文献と新しい産業の歴史（出典つきの定数）と、各主題の判定（需要の追い風・値段と人気・基礎率 → 区分）。
     AI・半導体は out/industry_peak.json と out/tech_persist.json の数字を必ず並べる。

データ
  - Yahoo の月足の調整後終値（配当込み）＝ mw_common.yahoo。キャッシュは out/_bestpf_cache/themes/（gitignore）。
  - Yahoo quoteSummary（表示 PER・資産額・経費率）は crumb つきで取り、同じキャッシュに置く（読むだけ）。
  - Ken French 49業種・市場（上場の前の主題の熱さの代理）。
  ⚠ 生き残りの偏り: Yahoo は償還された本を返さない（IRBO・POTX・BLCN は取れなかった＝表に「取れない」と書く）。
  ⚠ 取れない値は 0 と読まない（ルール7）。足りない窓は None。

使い方: python3 night/bestpf_themes.py           → out/bestpf_themes.json
        python3 night/bestpf_themes.py --no-qs   → quoteSummary を取らない（前回のキャッシュがあれば使う）
"""
import sys, os, json, math, time, statistics as S, datetime, urllib.request, http.cookiejar

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M  # noqa: E402

BASE = M.BASE
M.CACHE = os.path.join(BASE, 'out', '_bestpf_cache', 'themes')
OUT = os.path.join(BASE, 'out', 'bestpf_themes.json')
END = 202609          # 事前登録: 2026-09 まで
HEAT_MONTHS = 24      # 上場の前の熱さ: 上場月の前の24か月（Ben-David ほかは −24〜−6 か月）

# ───────────────────────── 主題 ETF の名簿 ─────────────────────────
# (ティッカー, 主題キー, 代理〔French 49業種のリスト or Yahoo の代理 'y:XXX'〕, 主題の始まりの上書き(yyyymm) or None, 注)
THEMES_JA = {
    'semis': 'AI・半導体（半導体）', 'ai': 'AI（ソフト・広く）', 'robot': 'ロボット・自動化', 'cloud': 'クラウド・ソフト',
    'cyber': 'サイバー', 'grid': '電力と送電・インフラ', 'clean': 'クリーンエネルギー', 'lithium': 'リチウム・電池',
    'nuclear': '原子力・ウラン', 'defense': '防衛', 'space': '宇宙', 'bio': 'ゲノム・バイオ', 'medtech': '医療機器',
    'fintech': 'フィンテック', 'ark': 'ARK（破壊的イノベーション）', 'india': 'インド', 'chinanet': '中国ネット',
    'gaming': 'ゲーム・eスポーツ', 'cannabis': '大麻', 'blockchain': 'ブロックチェーン', 'print3d': '3D印刷',
    'ev': 'EV・自動運転', 'internet': 'ネット・SNS', 'water': '水',
}
FR_PROXY = {
    'semis': ['Chips'], 'ai': ['Softw', 'Chips', 'Hardw'], 'robot': ['Mach', 'ElcEq', 'Chips'], 'cloud': ['Softw'],
    'cyber': ['Softw'], 'clean': ['ElcEq', 'Util'], 'lithium': ['Mines', 'Chems', 'ElcEq'], 'defense': ['Guns', 'Aero'],
    'space': ['Aero', 'Guns', 'Telcm'], 'bio': ['Drugs', 'LabEq'], 'medtech': ['MedEq'], 'fintech': ['BusSv', 'Fin'],
    'ark': ['Softw', 'BusSv', 'Hardw'], 'gaming': ['Fun', 'Softw'], 'print3d': ['Mach', 'Hardw'], 'ev': ['Autos'],
    'internet': ['BusSv', 'Softw'], 'water': ['Util', 'Mach'],
}
UNIV = [
    # AI・半導体
    ('SMH', 'semis', None, None, 'Yahoo の2000-06〜2011-12 は Semiconductor HOLDRS（2000-05 上場）・以後 VanEck'),
    ('SOXX', 'semis', None, None, ''), ('PSI', 'semis', None, None, ''), ('XSD', 'semis', None, None, ''),
    ('SOXQ', 'semis', None, None, ''), ('FTXL', 'semis', None, None, ''),
    ('AIQ', 'ai', None, None, ''), ('THNQ', 'ai', None, None, ''), ('ARTY', 'ai', None, None, ''), ('LOUP', 'ai', None, None, ''),
    ('CHAT', 'ai', None, None, ''), ('WTAI', 'ai', None, None, ''), ('KOMP', 'ai', None, None, ''), ('QTUM', 'ai', None, None, ''),
    ('BOTZ', 'robot', None, None, ''), ('ROBO', 'robot', None, None, ''), ('IRBO', 'robot', None, None, '2025年に償還（取れない）'),
    ('ARKQ', 'robot', None, None, ''), ('SNSR', 'robot', None, None, 'IoT'),
    ('SKYY', 'cloud', None, None, ''), ('CLOU', 'cloud', None, None, ''), ('WCLD', 'cloud', None, None, ''), ('IGV', 'cloud', None, None, 'ソフトウェア業種'),
    ('HACK', 'cyber', None, None, ''), ('CIBR', 'cyber', None, None, ''), ('BUG', 'cyber', None, None, ''),
    ('GRID', 'grid', ['Util', 'ElcEq'], None, '送電網'), ('PAVE', 'grid', ['Cnstr', 'BldMt', 'Mach'], None, '米国インフラ'),
    ('ICLN', 'clean', None, None, ''), ('TAN', 'clean', None, None, '太陽光'), ('PBW', 'clean', None, None, ''),
    ('QCLN', 'clean', None, None, ''), ('FAN', 'clean', None, None, '風力'),
    ('LIT', 'lithium', None, None, ''), ('BATT', 'lithium', None, None, ''),
    ('URA', 'nuclear', ['Mines'], None, 'ウラン'), ('URNM', 'nuclear', ['Mines'], None, 'ウラン鉱山'), ('NLR', 'nuclear', ['Util', 'Mines'], None, '原子力'),
    ('ITA', 'defense', None, None, ''), ('XAR', 'defense', None, None, ''), ('PPA', 'defense', None, None, ''), ('SHLD', 'defense', None, None, ''),
    ('UFO', 'space', None, None, ''), ('ARKX', 'space', None, None, ''), ('ROKT', 'space', None, None, ''),
    ('ARKG', 'bio', None, None, ''), ('GNOM', 'bio', None, None, ''), ('XBI', 'bio', None, None, ''), ('IBB', 'bio', None, None, ''),
    ('IHI', 'medtech', None, None, ''),
    ('FINX', 'fintech', None, None, ''), ('ARKF', 'fintech', None, None, ''), ('IPAY', 'fintech', None, None, ''),
    ('ARKK', 'ark', None, None, ''), ('ARKW', 'ark', None, None, ''),
    ('INDA', 'india', 'y:INDIA', None, ''), ('EPI', 'india', 'y:INDIA', None, ''), ('SMIN', 'india', 'y:INDIA', None, ''), ('INDY', 'india', 'y:INDIA', None, ''),
    ('KWEB', 'chinanet', 'y:FXI', None, ''), ('CQQQ', 'chinanet', 'y:FXI', None, ''),
    ('ESPO', 'gaming', None, None, ''), ('HERO', 'gaming', None, None, ''), ('GAMR', 'gaming', None, None, ''),
    ('MJ', 'cannabis', 'none', 201712, '2017-12 に大麻の主題へ転換（それ以前は別の中身）＝主題の上場を 2017-12 とみなす'),
    ('MSOS', 'cannabis', 'none', None, ''), ('YOLO', 'cannabis', 'none', None, ''), ('POTX', 'cannabis', 'none', None, '償還（取れない）'),
    ('BLOK', 'blockchain', 'y:BTC-USD', None, ''), ('BLCN', 'blockchain', 'y:BTC-USD', None, '取れない'), ('BKCH', 'blockchain', 'y:BTC-USD', None, ''),
    ('PRNT', 'print3d', None, None, ''),
    ('DRIV', 'ev', None, None, ''), ('KARS', 'ev', None, None, ''), ('IDRV', 'ev', None, None, ''),
    ('SOCL', 'internet', None, None, ''), ('FDN', 'internet', None, None, ''),
    ('PHO', 'water', None, None, ''), ('CGW', 'water', None, None, ''),
]


# ───────────────────────── 小道具 ─────────────────────────
def mnum(k):
    return k // 100 * 12 + k % 100 - 1


def mkey(n):
    return (n // 12) * 100 + n % 12 + 1


def add_m(k, d):
    return mkey(mnum(k) + d)


def ann(logsum, n):
    return math.exp(logsum * 12 / n) - 1 if n else None


def geo_diff(s, b, ks):
    """同じ月 ks での幾何の年率差（%/年）と各年率"""
    if not ks:
        return None, None, None
    ls = math.fsum(math.log1p(s[k]) for k in ks); lb = math.fsum(math.log1p(b[k]) for k in ks)
    gs, gb = ann(ls, len(ks)), ann(lb, len(ks))
    return round((gs - gb) * 100, 2), round(gs * 100, 2), round(gb * 100, 2)


def cum_rel(s, b, ks):
    """同じ月 ks での相対の富（s の富 ÷ b の富）− 1（%）"""
    w = math.fsum(math.log1p(s[k]) - math.log1p(b[k]) for k in ks)
    return round((math.exp(w) - 1) * 100, 1)


def spearman(x, y):
    n = len(x)
    if n < 5:
        return None
    def rk(v):
        o = sorted(range(n), key=lambda i: v[i]); r = [0.0] * n; i = 0
        while i < n:
            j = i
            while j + 1 < n and v[o[j + 1]] == v[o[i]]:
                j += 1
            for t in range(i, j + 1):
                r[o[t]] = (i + j) / 2
            i = j + 1
        return r
    return round(M.corr(rk(x), rk(y)), 3)


def med(v):
    v = [x for x in v if x is not None]
    return round(S.median(v), 2) if v else None


def share_pos(v):
    v = [x for x in v if x is not None]
    return (sum(1 for x in v if x > 0), len(v))


def summ(v, win_label='SPYに勝った'):
    """win_label: 勝った数の見出し（QQQ と比べるときは 'QQQに勝った'。2026-10-12 検証役の指摘で引数にした）"""
    v = [x for x in v if x is not None]
    if not v:
        return {'n': 0}
    w, n = share_pos(v)
    return {'n': n, '中央値(%/年)': round(S.median(v), 2), '平均(%/年)': round(S.mean(v), 2), win_label: f'{w}/{n}',
            '勝率': round(w / n, 3), '最小': round(min(v), 2), '最大': round(max(v), 2)}


def roll_win(s, b, years, step=12):
    """その本の最初の月から step か月ずつずらした years 年の一括の窓で、幾何の年率差（%/年）の分布。
    中央値は statistics.median（本当の中央値）。窓は重なる（独立でない）"""
    ks = [k for k in sorted(s) if k in b]
    n = years * 12
    out = []
    for i in range(0, len(ks) - n + 1, step):
        w = ks[i:i + n]
        if mnum(w[-1]) - mnum(w[0]) + 1 != n:   # 抜けた月をまたぐ窓は数えない（ルール7）
            continue
        out.append((w[0], geo_diff(s, b, w)[0]))
    if not out:
        return None
    v = [d for _, d in out]
    return {'窓': len(out), '勝った': sum(1 for d in v if d > 0), '中央(%/年)': round(S.median(v), 2),
            '最悪(起点・%/年)': list(min(out, key=lambda x: x[1])), '最良(起点・%/年)': list(max(out, key=lambda x: x[1]))}


def dca_both(s, b, years=10, step=12):
    """mw_common.dca と同じ積立（毎月同額・step か月ずつ起点をずらす）。中央を二通りで返す:
    上側の中央（mw_common.dca と同じ v[len//2]）と本当の中央値（statistics.median）"""
    ks = sorted(set(s) & set(b))
    n = years * 12
    out = []
    for i in range(0, len(ks) - n + 1, step):
        w = ks[i:i + n]
        ws = wb = 0.0
        for k in w:
            ws = (ws + 1) * (1 + s[k]); wb = (wb + 1) * (1 + b[k])
        out.append(round(ws / wb, 3))   # mw_common.dca と同じく窓ごとに3桁へ丸めてから並べる
    if not out:
        return None
    v = sorted(out)
    return {'窓': len(v), '上側の中央': v[len(v) // 2], '本当の中央値': round(S.median(v), 4),
            '勝った窓の割合': round(sum(1 for r in v if r > 1) / len(v), 3)}


def yahoo_safe(t):
    try:
        return M.yahoo(t)
    except Exception as e:  # noqa
        return {'__err__': str(e)[:160]}


# ───────────────────────── Yahoo quoteSummary（表示 PER など） ─────────────────────────
class QS:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.op.addheaders = [('User-Agent', 'Mozilla/5.0 (ccf-gate research)')]
        self.crumb = None

    def _crumb(self):
        if self.crumb:
            return self.crumb
        try:
            self.op.open('https://fc.yahoo.com', timeout=30).read()
        except Exception:  # 404 でもクッキーは付く
            pass
        self.crumb = self.op.open('https://query2.finance.yahoo.com/v1/test/getcrumb', timeout=30).read().decode().strip()
        return self.crumb

    def get(self, t, fetch=True, max_age_days=5):
        p = os.path.join(M.CACHE, f'qs_{t.replace("^", "IDX_")}.json')
        if os.path.exists(p) and (not fetch or time.time() - os.path.getmtime(p) < max_age_days * 86400):
            return json.load(open(p))
        if not fetch:
            return None
        u = (f'https://query2.finance.yahoo.com/v10/finance/quoteSummary/{t}?modules=summaryDetail,defaultKeyStatistics,'
             f'fundProfile&crumb={self._crumb()}')
        for i in range(3):
            try:
                j = json.loads(self.op.open(u, timeout=30).read())
                r = (j.get('quoteSummary') or {}).get('result') or []
                if not r:
                    return None
                r = r[0]
                sd, ks, fp = r.get('summaryDetail', {}), r.get('defaultKeyStatistics', {}), r.get('fundProfile', {})
                g = lambda d, k: (d.get(k) or {}).get('raw') if isinstance(d.get(k), dict) else None  # noqa
                out = {'asof': datetime.date.today().isoformat(), 'source': 'Yahoo quoteSummary（summaryDetail・defaultKeyStatistics・fundProfile）',
                       'trailingPE': g(sd, 'trailingPE'), 'totalAssets': g(sd, 'totalAssets') or g(ks, 'totalAssets'),
                       'yield': g(sd, 'yield'), 'expense_ratio': g(fp.get('feesExpensesInvestment', {}) or {}, 'annualReportExpenseRatio'),
                       'inception': ((ks.get('fundInceptionDate') or {}).get('fmt')), 'beta3y': g(ks, 'beta3Year'),
                       'y3avg': g(ks, 'threeYearAverageReturn'), 'y5avg': g(ks, 'fiveYearAverageReturn'),
                       'category': fp.get('categoryName')}
                os.makedirs(M.CACHE, exist_ok=True)
                json.dump(out, open(p, 'w'), ensure_ascii=False)
                time.sleep(0.4)
                return out
            except Exception:  # noqa
                time.sleep(2 ** (i + 1))
        return None


# ───────────────────────── 出典つきの定数（文献・歴史・需要の証拠） ─────────────────────────
LIT_BENDAVID = {
    'citation': 'Ben-David, I., Franzoni, F., Kim, B., Moussawi, R. (2023) "Competition for Attention in the ETF Space", '
                'The Review of Financial Studies 36(3): 987–1042（作業論文 NBER w28369 rev2, 2021）',
    'note_on_journal': '事前登録と依頼文は Journal of Finance と書いていたが、掲載誌は The Review of Financial Studies（2023）。数字は NBER 版から読んだ',
    'url': 'https://www.nber.org/system/files/working_papers/w28369/revisions/w28369.rev2.pdf',
    'abstract_url': 'https://sfi.ch/en/publications/competition-for-attention-in-the-etf-space',
    'sample': '米国の株の ETF・CRSP 1993〜2019（特化型＝業種と主題 526本・広い型 554本）',
    'numbers': [
        '特化型 ETF は最初の5年でリスク調整後に約30%を失う（要旨）',
        '特化型 ETF 全部を持つポートフォリオのリスク調整後リターンは −3.1%/年（費用後）。上場直後の本は最初の5年で約 −6%/年（本文 p.4）',
        '上場後60か月の市場（CRSP 時価加重）との差: 特化型 平均 −0.44%/月・中央 −0.21%/月（約 −2.5%/年）／広い型 平均 −0.16%/月・中央 −0.11%/月（表1）',
        '主題型だけ（115本）: 平均 −0.87%/月・中央 −0.30%/月（約 −3.6%/年）・2019年までに償還 37%（付表 D.1 Panel D）',
        '経費率の中央: 特化型 58bp・主題型 65bp・広い型 35bp（表1・付表 D.1）',
        '2019年12月に特化型は業界の資産の18%だが手数料収入の36%（p.4）',
        '負けの原因は費用ではなく、上場の時点で中身の株が割高だったこと。上場前の24か月に中身の株は市場に勝っており、メディアの注目も高い。上場の前後が評価の天井（6.1節・表6・図6）',
        '上場前に過去のリターンや注目が高かった本ほど上場後の負けが大きい（図7）',
    ],
}
HISTORY = [
    {'産業': '運河と鉄道（英国 1816〜1851）', '技術は本物か': '本物（鉄道の貨物は運河の約60倍の効率）',
     '株主': '運河株は鉄道の開通（1825）後の25年で70%超下落。鉄道株は1846年に天井（272路線の認可）・1849年までに3分の2下落。25年の通算は値上がり年3%＋配当で「まずまず」だが乱高下',
     '出典': 'Dimson, Marsh, Staunton「Credit Suisse Global Investment Returns Yearbook 2015」pp.9-10',
     'url': 'https://assets.london.edu/hxo16fanegqh/17qoDLtNQRLq7vMWg7fvqb/aeb1575bd2edd4b963c65277c5bfbd7a/global-investment-returns-yearbook-2015.pdf'},
    {'産業': '米国の鉄道（1900〜2014）', '技術は本物か': '1900年に米国市場の63%を占めた（今は1%未満）',
     '株主': '1900年の1ドル → 鉄道 62,716ドル ＞ 市場 39,134ドル ＞ 道路輸送 10,570ドル ＞ 航空 7,090ドル。衰退産業が市場に勝ち、最も新しい航空が最下位。ただし鉄道も1970年代初めまでは大きく負けていた（Penn Central 破産1970）',
     '出典': 'DMS Yearbook 2015 図6・p.10', 'url': 'https://assets.london.edu/hxo16fanegqh/17qoDLtNQRLq7vMWg7fvqb/aeb1575bd2edd4b963c65277c5bfbd7a/global-investment-returns-yearbook-2015.pdf'},
    {'産業': '自動車（米国）', '技術は本物か': '本物（社会を変えた）',
     '株主': '少なくとも2,000の自動車ブランドがあり、生き残った米国の自動車会社は3社',
     '出典': 'Warren Buffett & Carol Loomis「Mr. Buffett on the Stock Market」Fortune 1999-11-22', 'url': 'https://fortune.com/1999/11/22/warren-buffett-on-stock-market/'},
    {'産業': '航空（米国）', '技術は本物か': '本物',
     '株主': '飛行機メーカーは1919〜39年に約300社あり、今も残るのはひと握り（原文 aircraft manufacturers）。航空会社（airline companies）が航空の始まり以来に稼いだお金の合計は1992年時点で「ゼロ」。「投資の鍵は産業が社会をどれだけ変えるかではなく、各社の競争上の強みとその持続性」',
     '出典': '同上 Fortune 1999-11-22', 'url': 'https://fortune.com/1999/11/22/warren-buffett-on-stock-market/'},
    {'産業': 'ラジオ（RCA・1920年代）', '技術は本物か': '本物（RCA は以後も米国のラジオ・無線の首位）',
     '株主': 'RCA は1929年9月 114.75ドル（分割調整後）→ 1932年5月 2.625ドル（約 −98%。同じ記事の別の箇所と Time 誌は 2.50ドル）。1929年の高値を取り戻した年は資料で食い違う（1966年とする記事あり＝確かめられない）',
     '出典': 'Global Financial Data「RCA and the Roaring Twenties」（⚠ 2026-10-12 に URL は globalfindata.com へ転送されて 404＝本文は開けず、検索結果の要約と The Bubble Blog の引用〔114.75→2.625〕で確かめた）',
     'url': 'https://www.globalfinancialdata.com/rca-and-the-roaring-twenties',
     'url_alt': 'https://thebubbleblog.substack.com/p/rcas-radiant-rise-and-radio-ruin'},
    {'産業': 'インターネット・テック（1995〜2014）', '技術は本物か': '本物',
     '株主': '米国テックは2000年3月までの5年で9倍 → 2年半で −82%。それでも1995〜2014の20年では年10.5%（米国株全体 9.9%）＝2000年1〜9月に買った人だけが損',
     '出典': 'DMS Yearbook 2015 図5・pp.9-10', 'url': 'https://assets.london.edu/hxo16fanegqh/17qoDLtNQRLq7vMWg7fvqb/aeb1575bd2edd4b963c65277c5bfbd7a/global-investment-returns-yearbook-2015.pdf'},
    {'産業': '通信（2000〜2002）', '技術は本物か': '本物（光ファイバー網はその後のネットの土台）',
     '株主': '通信会社の時価総額 約2兆ドルが消えた（株式市場全体の下落 約7兆ドルのうち）',
     '出典': 'Paul Starr「The Great Telecom Implosion」The American Prospect 2002-08', 'url': 'https://prospect.org/2002/08/19/great-telecom-implosion/'},
    {'産業': '米国シェール（2010〜2020）', '技術は本物か': '本物（米国の産油量を世界一へ）',
     '株主': 'Deloitte（2020）: 2010年以降のシェール業界はフリーキャッシュフローが約3,000億ドルの赤字・資産の減損4,500億ドル超・190件超の破産',
     '出典': 'Argus Media「Shale industry write-downs may top $300bn: Deloitte」2020-06', 'url': 'https://www.argusmedia.com/en/news-and-insights/latest-market-news/2116691-shale-industry-write-downs-may-top-300bn-deloitte'},
    {'産業': '国の経済成長（16か国・1900〜2002）', '技術は本物か': '—',
     '株主': '1人あたり実質 GDP の伸びと株の実質リターンの国どうしの相関は −0.37（p=0.16）。1970〜2002の19か国で −0.08、新興13か国（1988〜2002）で 0.02',
     '出典': 'Jay Ritter (2005)「Economic growth and equity returns」Pacific-Basin Finance Journal 13: 489–503', 'url': 'https://site.warrington.ufl.edu/ritter/files/2015/04/Economic-growth-and-equity-returns-2005.pdf'},
    {'産業': '新規上場（新しい産業はここから生まれる）', '技術は本物か': '—',
     '株主': '米国の IPO 7,793件（1980〜2012）は上場3年で市場に対し平均 −18.6%。英国 2,499件（1975〜2004）は5年で −31.6%。上場から20年超の古い株は3年以下の新しい株の約3倍の富（英国 1980〜2014）',
     '出典': 'DMS Yearbook 2015 pp.11-12（Ritter 2014・Gregory ほか 2010 を引用）', 'url': 'https://assets.london.edu/hxo16fanegqh/17qoDLtNQRLq7vMWg7fvqb/aeb1575bd2edd4b963c65277c5bfbd7a/global-investment-returns-yearbook-2015.pdf'},
    {'産業': 'S&P500 の業種（1957〜2003・Siegel『株式投資の未来』）', '技術は本物か': '—',
     '株主': '1957年の最初の500社だけを持ち続けたほうが、新しい会社を足し続けた S&P500 より成績が良かった（成長の罠）。業種の比重の伸び縮みで説明できるのはリターンの3分の1未満・IT と金融は凡庸・縮んだエネルギーが良かった',
     '出典': 'Wharton Magazine「The Next Long Run」2006（Siegel の要約）', 'url': 'https://magazine.wharton.upenn.edu/issues/summer-2006/the-next-long-run'},
]
DEMAND = {
    'semis': {'強さ': '強い', '証拠': 'WSTS の2026年5月の予想（まだ決まった数字ではない）: 世界の半導体の売上 2025年 7,956億ドル → 2026年 1兆5,112億ドル（+89.9%）→ 2027年 1兆9,137億ドル（+26.6%）。メモリーの売上は 2,300億ドル → 8,039億ドル（メモリーそのものの伸びが +249.5%・全体の増加 7,156億ドルのうち 5,739億ドル＝約80%がメモリー・HBM 等）',
              '注': 'メモリーは昔から好不況の振れが最も大きい部品（2026年の+250%は値段の急騰を含む）＝需要の天井が利益の天井になりやすい',
              '出典': 'https://www.wsts.org/esraCMS/extension/media/f/WST/7618/WSTS_FC-Release-2026-May.pdf'},
    'ai': {'強さ': '強い', '証拠': 'IEA『Energy and AI』（2025）: データセンターの電力 2024年 415TWh → 2030年 約945TWh（2倍超・AI が主因）',
           '出典': 'https://www.iea.org/reports/energy-and-ai/executive-summary'},
    'grid': {'強さ': '強い', '証拠': 'IEA の基本ケース: データセンターの電力は2030年までに2倍超・米国では電力需要の伸びの約半分がデータセンター。IEA『World Energy Investment 2025』: 送電網への投資は年約4,000億ドルで発電（約1兆ドル）に遅れ、発電と同じ水準まで増やす必要',
             '出典': 'https://www.iea.org/reports/energy-and-ai/executive-summary ; https://www.climateaction.org/news/global-energy-investment-to-hit-record-3.3-trillion-in-2025（IEA WEI 2025 の要約）'},
    'clean': {'強さ': '強い（量）', '証拠': 'IEA WEI 2025: クリーンエネルギーへの投資 2.2兆ドル/年（化石燃料 1.1兆ドルの2倍）',
              '注': '量は伸びたが値段が崩れた: 中国製の太陽光パネルは2024年に約0.10ドル/W の最安値（供給過剰）＝伸びが利益にならない形',
              '出典': 'https://www.climateaction.org/news/global-energy-investment-to-hit-record-3.3-trillion-in-2025 ; https://ioplus.nl/archive/en/chinese-solar-module-prices-plunge-to-record-lows/'},
    'lithium': {'強さ': '中（量は伸びたが値段が崩れた）', '証拠': '炭酸リチウムの値段は2022年11月の天井から底で約85〜88%下落（2025年半ばに底・その後反発）',
                '出典': 'https://www.theglobeandmail.com/investing/investment-ideas/article-have-lithium-prices-bottomed-yet ; https://news.metal.com/newscontent/103506193/'},
    'nuclear': {'強さ': '強い（政策・ただし実現は不確か）', '証拠': '米国の大統領令（2025-05-23）: 原子力を約100GW → 2050年に400GW へ。データセンターの電力需要と結びつけた（二次資料）',
                '出典': 'https://introl.com/blog/trump-400-gw-nuclear-executive-orders-2050-target（二次資料・ホワイトハウスの原文は未確認）'},
    'defense': {'強さ': '強い', '証拠': 'SIPRI（2026-04）: 2025年の世界の軍事費 2兆8,870億ドル（原文 $2887 billion）・実質 +2.9%・11年連続の増加・世界 GDP の2.5%（2009年以来の高さ）。欧州 +14%',
                '出典': 'https://www.sipri.org/sites/default/files/Military%20Expenditure%202025.pdf'},
    'space': {'強さ': '中', '証拠': '世界経済フォーラム・McKinsey（2024-04）: 宇宙経済 2023年 6,300億ドル → 2035年 1.8兆ドル（年約9%）',
              '出典': 'https://www.weforum.org/reports/space-the-1-8-trillion-opportunity-for-global-economic-growth'},
    'cyber': {'強さ': '強い', '証拠': 'Gartner（2026-02）: 情報セキュリティへの世界の支出 2026年 2,440億ドル（為替一定で +11.6%）',
              '出典': 'https://www.gartner.com/en/documents/7408930（要約）・softwarestrategiesblog.com の Gartner 2Q26 の要約（二次）'},
    'robot': {'強さ': '中', '証拠': 'IFR World Robotics 2025: 2024年の産業用ロボットの設置 54.2万台・稼働台数 466万台（+9%・2019年から年平均 +11%）。10年で需要は2倍',
              '出典': 'https://ifr.org/ifr-press-releases/news/global-robot-demand-in-factories-doubles-over-10-years'},
    'india': {'強さ': '中〜強い（成長）', '証拠': 'IMF（2026-01 世界経済見通しの更新）: インドの成長率 2025年度 7.3%・2026年度 6.4%（主要国で最も高い部類）',
              '注': '経済の伸びと株のリターンは国どうしでつながらない（Ritter 2005: 相関 −0.37）',
              '出典': 'https://www.hl.co.uk/news/imf-raises-india-fy26-growth-forecast-to-73-sees-slower-pace-in-next-two-years（Reuters 配信）'},
    'japan_reform': {'強さ': '中（株主還元の制度の変化）', '証拠': '東証の要請（2023-03・資本コストと株価を意識した経営）以後、自社株買いの枠は2024年度 18.7兆円・2025年度は4〜12月だけで14.2兆円で過去最高のペース',
                     '出典': 'https://www.nippon.com/en/japan-data/h02676/'},
    'bio': {'強さ': '中', '証拠': '高齢化（需要は確か）だが、ゲノムなどの新しい治療が利益になる時期は読めない', '出典': '（数字の出典なし＝確かめられない）'},
    'medtech': {'強さ': '中', '証拠': '高齢化（需要は確か）', '出典': '（数字の出典なし＝確かめられない）'},
    'cloud': {'強さ': '強い', '証拠': 'Gartner（2024-11）: 世界の公開クラウドへの支出 2024年 5,957億ドル → 2025年 7,234億ドル（+21%）',
              '出典': 'https://www.gartner.com/en/newsroom/press-releases/2024-11-19-gartner-forecasts-worldwide-public-cloud-end-user-spending-to-total-723-billion-dollars-in-2025'},
    'ev': {'強さ': '強い（量）', '証拠': 'IEA『Global EV Outlook 2025』: 2024年の電気自動車の販売 1,700万台超・新車の20%超（中国はほぼ半分）',
           '注': '量の伸びは中国勢の値下げ競争と一緒に来た＝伸びが利益にならない形（クリーンエネ・リチウムと同じ）',
           '出典': 'https://www.iea.org/reports/global-ev-outlook-2025/executive-summary'},
    'chinanet': {'強さ': '中（政策の振れ）', '証拠': '利用者は大きいが、2021年の規制強化で中国ネット株は大きく下げた（下の実測）', '出典': '（実測は本ファイルの表）'},
}


# 20年で株主が報われる見込み（言葉）。数字は judge の中で実績・値段から足す。
# 共通の物差し: 主題 ETF は上場後に SPY に負けるのが基礎率（本ファイルの集計）。「市場並み」は SPY と同じくらい、の意味
OUTLOOK = {
    'semis': ('市場並み〜やや下の見込み（基礎率 −1.5〜−4.0%/年）。半導体の ETF は上場以来6本とも SPY に勝ったが、その多くは直近の AI 相場の窓で、'
              '2000年の天井の直後に上場した SMH は最初の10年に SPY に年 −10.5%（10年で −72%）だった。需要は本物で加速しているが、比重は100年で最大・直近10年の1位・PER は SPY の約1.4倍で、'
              'ここから20年で市場に勝ち続けるには、過去の基礎率では少数派の形（1位の業種が次の10年も勝つ＝勝率26%）が要る。上下どちらにも大きくぶれる'),
    'ai': ('市場並みかやや下の見込み。AI の名前の ETF は上場以来 SPY には8本中7本が勝った（AI 相場の窓の中）が、AI のお金が通った半導体（SMH）には10本中10本が負けた'
           '（docs/CLAUDE_ARCHIVE.md:9492）。直近3年は SPY に年 +14% で人気が高く、記録の比重の業種の基礎率（次の10年 −1.5%/年）が当てはまる側に居る'),
    'robot': ('やや下の見込み。工場のロボットは10年で2倍に増えたが、ロボットの ETF（ROBO・BOTZ）は上場以来 SPY に負け、値段（PER）は SPY の約1.4倍'),
    'cloud': ('市場並みかやや下の見込み。支出は年20%前後で伸びているが、クラウドの ETF は2019年の上場組が SPY に負け、PER は SPY の約1.4倍'),
    'cyber': ('市場並みの見込み。支出の伸び（年+12%）は確かで、HACK・CIBR・BUG は上場以来ほぼ SPY 並み。PER は SPY の約1.4倍で上乗せの余地は小さい'),
    'grid': ('市場並みの見込み。データセンターの電力で需要は強いが、GRID は2009年からの17年で SPY に年 −1.9%。値段は SPY の約1.2倍'),
    'clean': ('低い見込み。量（投資額・設置量）は伸びたが、値段の崩れと競争で利益にならず、TAN・ICLN は18年で年 −7.7%・−3.9%（SPY 年+12%）。安くなったが歴史は最悪の部類'),
    'lithium': ('低い見込み。電池の量は伸びたがリチウムの値段は天井から約85〜88%下落。LIT は16年で SPY に年 −8.9%'),
    'nuclear': ('不確か。政策の追い風は強くなったが、ウランの ETF は上場の時期で結果が正反対（URA −18.4%/年・URNM +9.2%/年）＝主題ではなく値段の時期が決めた'),
    'defense': ('市場並み〜やや上の見込み。軍事費は11年連続で増加し、防衛の ETF は20年で SPY に年 +1〜+2%（主題の中で数少ない勝ち）。ただし PER は SPY の約1.2倍で、2026年の欧州の再軍備は値段に入り始めている'),
    'space': ('やや下の見込み。宇宙経済は年9%の予想だが、UFO・ARKX は上場以来 SPY に負けた。直近3年の急騰（SPY に年 +15%）で値段が先に走っている'),
    'bio': ('市場並みかやや下の見込み。新しい治療は本物だが、利益になる時期が読めず、ゲノムの ETF（ARKG・GNOM）は SPY に負けた'),
    'medtech': ('市場並みの見込み。高齢化で需要は確か。IHI は20年で SPY に年 −1.2%・直近3年は大きく負けた（値段は下がった）'),
    'fintech': ('やや下の見込み。決済の電子化は進んだが、フィンテックの ETF は3本とも SPY に年 −5〜−10%'),
    'ark': ('不確か。ARKK は12年で SPY 並み（年 +0.5%）だが、途中で −80% 近く下げており、資金の多くは高値で入った'),
    'india': ('不確か〜やや下。成長は主要国で最も速いが、インドの ETF は4本とも SPY に年 −6〜−10%（ルピー安を含む）。経済の伸びと株のリターンは国どうしでつながらない（Ritter 2005）'),
    'chinanet': ('不確か。値段は SPY の約0.6倍と安いが、2021年の規制で −76%。政策の振れを値段に入れる必要がある'),
    'gaming': ('市場並みかやや下の見込み。'),
    'cannabis': ('低い見込み。大麻の ETF は3本とも SPY に年 −39% 前後（年率そのものは −23〜−24%）'),
    'blockchain': ('不確か。中身はビットコインの値段に連動する会社で、BLOK は SPY を年 +2.7% 上回り、BKCH は SPY に年 −16%'),
    'print3d': ('低い見込み。2013〜14年の流行の後に上場した PRNT は SPY に年 −12.5%'),
    'ev': ('低い見込み。販売は新車の20%を超えたが、値下げ競争で利益にならず、EV の ETF は3本とも SPY に負けた'),
    'internet': ('市場並みの見込み。FDN（2006年〜）は SPY に年 +2.5% と勝ったが、SOCL（2011年〜）は年 −6.4%'),
    'water': ('やや下の見込み。PHO・CGW は約20年で SPY に年 −3〜−4%'),
}


# ───────────────────────── 本体 ─────────────────────────
def main(fetch_qs=True):
    spy = M.yahoo('SPY'); qqq = M.yahoo('QQQ')
    ff = M.ff_factors(); mkt = ff['mkt']
    ind = M.french_series('49_Industry_Portfolios')
    ysr = {t: yahoo_safe(t) for t in ['FXI', 'BTC-USD', '^BSESN', 'INR=X']}
    # インドの代理: Sensex（価格・配当なし）をドル建てへ（INR=X は 1ドルあたりのルピー）
    bse, inr = ysr['^BSESN'], ysr['INR=X']
    india_usd = {k: (1 + bse[k]) / (1 + inr[k]) - 1 for k in bse if k in inr}
    proxies_y = {'y:FXI': (ysr['FXI'], spy), 'y:BTC-USD': (ysr['BTC-USD'], spy), 'y:INDIA': (india_usd, spy)}

    rows, missing = [], []
    series = {}
    for (t, th, prox, start_override, note) in UNIV:
        r = yahoo_safe(t)
        if '__err__' in r or not r:
            missing.append({'t': t, '主題': THEMES_JA[th], '理由': 'Yahoo が返さない（償還・名称変更の疑い）＝生き残りの偏りの実例', 'err': r.get('__err__') if isinstance(r, dict) else None, '注': note})
            continue
        ks_all = sorted(k for k in r if k <= END)
        launch = add_m(ks_all[0], -1) if start_override is None else start_override
        ks = [k for k in ks_all if k > launch and k in spy]
        # 抜けた月（Yahoo の欠け）を数える
        gaps = (mnum(ks[-1]) - mnum(ks[0]) + 1) - len(ks) if ks else None
        s = {k: r[k] for k in ks}
        series[t] = s
        d_full, g_s, g_b = geo_diff(s, spy, ks)
        dq, _, gq = geo_diff(s, qqq, [k for k in ks if k in qqq])
        row = {'t': t, '主題': THEMES_JA[th], 'theme': th, '上場月(推定)': launch, '最初の月': ks[0], '最後の月': ks[-1],
               '月数': len(ks), '年数': round(len(ks) / 12, 1), '欠けた月': gaps,
               '年率%': g_s, 'SPY年率%(同じ窓)': g_b, '差(%/年)': d_full, 'QQQとの差(%/年)': dq,
               '最大下落%': round(M.maxdd(s) * 100, 1), 'SPY最大下落%(同じ窓)': round(M.maxdd({k: spy[k] for k in ks}) * 100, 1)}
        for h in (12, 36, 60, 120):
            if len(ks) >= h:
                w = ks[:h]
                dd, _, _ = geo_diff(s, spy, w)
                row[f'上場後{h // 12}年の差(%/年)'] = dd
                row[f'上場後{h // 12}年の相対の富(%)'] = cum_rel(s, spy, w)
            else:
                row[f'上場後{h // 12}年の差(%/年)'] = None
        # 途中の窓（2026-10-12 検証役の指摘で追加: 全期間で勝っても途中で大きく負けた時期を見落とさない）
        for yy in (5, 10):
            row[f'転がる{yy}年窓（12か月ずらし）'] = roll_win(s, spy, yy)
        # 上場の前の熱さ（代理の24か月の市場との差・幾何%/年と累計%）
        heat, heat_src = None, None
        pre = [add_m(launch, -i) for i in range(HEAT_MONTHS, 0, -1)]
        if prox is None or isinstance(prox, list):
            cols = prox if isinstance(prox, list) else FR_PROXY.get(th)
            if cols and all(k in mkt and all(k in ind[c] for c in cols) for k in pre):
                p = {k: S.mean(ind[c][k] for c in cols) for k in pre}
                heat = cum_rel(p, mkt, pre); heat_src = 'French 49業種 ' + '+'.join(cols) + '（等分）− French 市場'
        elif isinstance(prox, str) and prox.startswith('y:'):
            ps, pb = proxies_y[prox]
            if all(k in ps and k in pb for k in pre):
                heat = cum_rel(ps, pb, pre); heat_src = {'y:FXI': 'FXI − SPY', 'y:BTC-USD': 'ビットコイン − SPY', 'y:INDIA': 'Sensex（ドル換算・配当なし）− SPY'}[prox]
        row['上場前24か月の主題の市場との差(%・累計)'] = heat
        row['熱さの代理'] = heat_src or ('代理なし（確かめられない）' if prox == 'none' else '代理のデータが足りない')
        # 今の位置（直近3年・5年の SPY との差）
        for h in (36, 60):
            w = [k for k in ks if k > add_m(END, -h)]
            row[f'直近{h // 12}年の差(%/年)'] = geo_diff(s, spy, w)[0] if len(w) == h else None
        row['注'] = note
        rows.append(row)

    # 同じ主題で何本目か（名簿の中で・上場月の順）
    by_th = {}
    for r_ in rows:
        by_th.setdefault(r_['theme'], []).append(r_)
    for th, rs in by_th.items():
        rs.sort(key=lambda x: x['上場月(推定)'])
        for i, r_ in enumerate(rs):
            r_['主題の中で何本目'] = i + 1
            r_['前の24か月に同じ主題で出た本数'] = sum(1 for q in rs if mnum(r_['上場月(推定)']) - 24 <= mnum(q['上場月(推定)']) < mnum(r_['上場月(推定)']))

    # ── 集計 ──
    agg = {
        '全期間（上場の翌月〜2026-09）': summ([r_['差(%/年)'] for r_ in rows]),
        '上場後1年': summ([r_['上場後1年の差(%/年)'] for r_ in rows]),
        '上場後3年': summ([r_['上場後3年の差(%/年)'] for r_ in rows]),
        '上場後5年': summ([r_['上場後5年の差(%/年)'] for r_ in rows]),
        '上場後10年': summ([r_['上場後10年の差(%/年)'] for r_ in rows]),
        'QQQとの差・全期間': summ([r_['QQQとの差(%/年)'] for r_ in rows], win_label='QQQに勝った'),
        '最大下落の中央(%)': {'主題ETF': med([r_['最大下落%'] for r_ in rows]), 'SPY(同じ窓)': med([r_['SPY最大下落%(同じ窓)'] for r_ in rows])},
    }
    eras = [('〜2009', 0, 200912), ('2010〜2016', 201001, 201612), ('2017〜2020', 201701, 202012), ('2021〜', 202101, 299912)]
    agg['上場の時期別・全期間'] = {e: summ([r_['差(%/年)'] for r_ in rows if a <= r_['上場月(推定)'] <= z]) for e, a, z in eras}
    agg['上場の時期別・上場後3年'] = {e: summ([r_['上場後3年の差(%/年)'] for r_ in rows if a <= r_['上場月(推定)'] <= z]) for e, a, z in eras}
    agg['主題別・全期間'] = {THEMES_JA[th]: summ([r_['差(%/年)'] for r_ in rs]) | {'本': [r_['t'] for r_ in rs]} for th, rs in by_th.items()}
    agg['主題別・上場後3年'] = {THEMES_JA[th]: summ([r_['上場後3年の差(%/年)'] for r_ in rs]) for th, rs in by_th.items()}
    # 主題ごとに1本（最も古い本）だけ＝同じ主題の重複を除く
    first = [rs[0] for rs in by_th.values()]
    agg['主題ごとに最も古い1本だけ・全期間'] = summ([r_['差(%/年)'] for r_ in first]) | {'本': [r_['t'] for r_ in first]}
    agg['主題ごとに最も古い1本だけ・上場後3年'] = summ([r_['上場後3年の差(%/年)'] for r_ in first])
    # 半導体を除く（今の窓は半導体の追い風が極端）
    agg['半導体を除く・全期間'] = summ([r_['差(%/年)'] for r_ in rows if r_['theme'] != 'semis'])
    agg['半導体を除く・上場後3年'] = summ([r_['上場後3年の差(%/年)'] for r_ in rows if r_['theme'] != 'semis'])
    # 長く生きた本で SPY に勝った本（2026-10-12 検証役の指摘「防衛だけが20年勝った、は誤り」で追加）
    for yrs in (15, 20):
        lg = [r_ for r_ in rows if r_['年数'] >= yrs]
        win = sorted([r_ for r_ in lg if (r_['差(%/年)'] or 0) > 0], key=lambda x: -x['差(%/年)'])
        agg[f'上場から{yrs}年以上の本'] = summ([r_['差(%/年)'] for r_ in lg]) | {
            'SPYに勝った本': [{'t': r_['t'], '主題': r_['主題'], '年数': r_['年数'], '差(%/年)': r_['差(%/年)']} for r_ in win]}

    # ── 上場からの月数をそろえた平均（等分）──
    ev = {}
    for h in (12, 24, 36, 60):
        rel = [cum_rel(series[r_['t']], spy, sorted(series[r_['t']])[:h]) for r_ in rows if r_['月数'] >= h]
        ev[f'{h}か月'] = {'本数': len(rel), '相対の富の中央(%)': med(rel), '相対の富の平均(%)': round(S.mean(rel), 1) if rel else None,
                         'SPYに勝った': f'{sum(1 for x in rel if x > 0)}/{len(rel)}'}
    # 月ごとの平均の超過（算術）を積んだ道筋
    path = []
    cum = 0.0
    for m in range(1, 61):
        xs = []
        for r_ in rows:
            ks = sorted(series[r_['t']])
            if len(ks) >= m:
                k = ks[m - 1]; xs.append(series[r_['t']][k] - spy[k])
        if len(xs) < 10:
            break
        cum += S.mean(xs)
        if m in (6, 12, 24, 36, 48, 60):
            path.append({'月': m, '本数': len(xs), '平均の超過の累計(%)': round(cum * 100, 1)})

    # ── 暦の上のポートフォリオ（毎月、生きている本を等分）──
    def cal_port(maxage=None):
        port = {}
        for k in sorted(spy):
            if k > END:
                continue
            xs = []
            for r_ in rows:
                s_ = series[r_['t']]
                if k in s_:
                    age = mnum(k) - mnum(r_['上場月(推定)'])
                    if maxage is None or age <= maxage:
                        xs.append(s_[k])
            if len(xs) >= 3:
                port[k] = S.mean(xs)
        return port
    cal = {}
    for name, ma in (('全部の本', None), ('上場から5年以内の本だけ', 60), ('上場から3年以内の本だけ', 36)):
        p = cal_port(ma)
        st = M.excess_stats(p, spy)
        cal[name] = st
    # 2006年以降だけ（本数が3本以上そろう時期）
    p5 = cal_port(60)
    cal['上場から5年以内の本だけ・2010-01〜'] = M.excess_stats(p5, spy, a=201001)
    # 2026-10-12 検証役の指摘で追加: 期間を分けても向きが同じか・初めの時期の本数・ぶれの比（ベータとは別）
    pall = cal_port(None)
    cal['全部の本・期間を分ける'] = {lab: M.excess_stats(pall, spy, a=a, z=z) for lab, a, z in
                                (('2001-08〜2009-12', 200108, 200912), ('2010-01〜2019-12', 201001, 201912), ('2020-01〜2026-09', 202001, END))}
    def n_alive(k):
        return sum(1 for r_ in rows if k in series[r_['t']])
    cal['全部の本・その月の本数'] = {str(k): n_alive(k) for k in (200108, 200201, 200301, 200401, 200501, 200601, 200801, 201001, 201501, 202001, 202609)}
    a0 = cal['全部の本']
    cal['全部の本・読み'] = {
        '値動きの大きさの比（年のぶれ÷SPYの年のぶれ）': round(a0['vol_s'] / a0['vol_b'], 2),
        'ベータ（SPY が1動くとき平均でどれだけ動くか）': a0['beta'],
        '年率の差(%/年)': a0['cagr_diff'], '算術の超過(%/年)': a0['ex_ann'], 't': a0['t'],
        'ぶれによる目減りの差の近似(%/年)': round(0.5 * ((a0['vol_s'] / 100) ** 2 - (a0['vol_b'] / 100) ** 2) * 100, 2),
        '注': (f"年率の差（幾何）は {a0['cagr_diff']}%/年だが、毎月の平均の差（算術）は {a0['ex_ann']}%/年で t {a0['t']}＝偶然と区別できない。"
              f"差の残りの約 {round(0.5 * ((a0['vol_s'] / 100) ** 2 - (a0['vol_b'] / 100) ** 2) * 100, 1)}%/年は、値動きが大きいことによる目減り（年のぶれの2乗の半分の差・近似）。"
              '期間を分けると 2000年代・2010年代・2020年代のどれでも SPY を下回った（下の『期間を分ける』）。2001-08〜2005 はそろっている本が4〜5本だけ'),
    }

    # ── 毎月の積立で見る（10年がそろう本・起点を1年ずつずらす）──
    dca_rows = []
    for r_ in rows:
        if r_['月数'] < 120:
            continue
        d = dca_both(series[r_['t']], spy, years=10, step=12)
        if d:
            dca_rows.append({'t': r_['t'], '主題': r_['主題'], '窓': d['窓'], '勝った窓の割合': d['勝った窓の割合'],
                             '最終額の比(SPY=1)の中央': d['上側の中央'], '最終額の比(SPY=1)の本当の中央値': d['本当の中央値']})
    up = [x['最終額の比(SPY=1)の中央'] for x in dca_rows]; tr = [x['最終額の比(SPY=1)の本当の中央値'] for x in dca_rows]
    dca_sum = {'本数': len(dca_rows),
               '最終額の比の中央（本ごとの上側の中央の中央・mw_common.dca と同じ）': round(S.median(up), 3) if up else None,
               '最終額の比の中央（本ごとの本当の中央値の中央）': round(S.median(tr), 3) if tr else None,
               '本ごとの中央の比が1を超えた本（上側の中央）': f"{sum(1 for x in up if x > 1)}/{len(up)}",
               '本ごとの中央の比が1を超えた本（本当の中央値）': f"{sum(1 for x in tr if x > 1)}/{len(tr)}",
               '勝った窓の割合の中央': med([x['勝った窓の割合'] for x in dca_rows]), '明細': dca_rows,
               '注': ('10年の毎月同額の積立の最終額を SPY の積立と比べた（mw_common.dca と同じ積み方・起点は12か月ずつ）。窓は重なる。'
                     'mw_common.dca は窓の数が偶数のとき上側の中央（v[len//2]）を返すので、本当の中央値（statistics.median）も並べた（2026-10-12 検証役の指摘）')}

    # ── 上場の前の熱さと上場後 ──
    def heat_test(key):
        pairs = [(r_['上場前24か月の主題の市場との差(%・累計)'], r_[key]) for r_ in rows
                 if r_['上場前24か月の主題の市場との差(%・累計)'] is not None and r_[key] is not None]
        if len(pairs) < 8:
            return {'n': len(pairs)}
        hs = sorted(p[0] for p in pairs); mh = S.median(hs)
        hot = [p[1] for p in pairs if p[0] > mh]; cold = [p[1] for p in pairs if p[0] <= mh]
        # 2026-10-12 検証役の指摘: 中央値で分けた半分は「市場に勝っていた側」ではない（中央値は +3.8〜+5.1%）。
        # 見出しを中身に合わせ、符号（上場前に主題が市場に勝った／負けた）で分けた形も並べる（事後・参考）
        pos = [p[1] for p in pairs if p[0] > 0]; neg = [p[1] for p in pairs if p[0] <= 0]
        return {'n': len(pairs), '熱さの中央(%)': round(mh, 1), '熱さが中央値より上の半分': summ(hot),
                '熱さが中央値以下の半分': summ(cold),
                '符号で分ける（事後・参考）': {'上場前に主題が市場に勝っていた本（熱さ>0）': summ(pos), '負けていた本（熱さ≤0）': summ(neg)},
                '順位相関（熱さ vs 上場後）': (rho := spearman([p[0] for p in pairs], [p[1] for p in pairs])),
                '順位相関の近似p(両側・本どうしは独立でない＝参考)': (round(M.p_two(rho * math.sqrt(len(pairs) - 2) / math.sqrt(1 - rho * rho)), 3) if rho is not None and abs(rho) < 1 else None),
                '上場前に主題が市場に勝っていた本の割合': f'{sum(1 for p in pairs if p[0] > 0)}/{len(pairs)}'}
    heat = {'上場後3年': heat_test('上場後3年の差(%/年)'), '上場後5年': heat_test('上場後5年の差(%/年)'), '全期間': heat_test('差(%/年)')}
    # 同じ主題で前の24か月に別の本が出ていた（＝流行の後）か
    def crowd_test(key):
        a = [r_[key] for r_ in rows if r_['前の24か月に同じ主題で出た本数'] >= 1 and r_[key] is not None]
        b = [r_[key] for r_ in rows if r_['前の24か月に同じ主題で出た本数'] == 0 and r_[key] is not None]
        return {'前の24か月に同じ主題の本が出ていた': summ(a), '出ていなかった': summ(b)}
    crowd = {'上場後3年': crowd_test('上場後3年の差(%/年)'), '全期間': crowd_test('差(%/年)')}

    # ── 同じ主題の最も古い本の値で、各上場の時点から3年先 ──
    sib = []
    for th, rs in by_th.items():
        if len(rs) < 2:
            continue
        base = rs[0]; s0 = series[base['t']]
        for r_ in rs:
            st = r_['上場月(推定)']
            w = [k for k in sorted(s0) if k > st][:36]
            if len(w) < 36:
                continue
            sib.append({'主題': THEMES_JA[th], '最古の本': base['t'], '上場した本': r_['t'], '上場月': st,
                        '最古の本の値で3年先の差(%/年)': geo_diff(s0, spy, w)[0], '何本目': r_['主題の中で何本目']})
    sib_sum = {'1本目の上場から': summ([x['最古の本の値で3年先の差(%/年)'] for x in sib if x['何本目'] == 1]),
               '2本目以降の上場から（主題が流行った後）': summ([x['最古の本の値で3年先の差(%/年)'] for x in sib if x['何本目'] >= 2])}

    # ── 今の値段と人気（Yahoo quoteSummary）──
    qs = QS()
    quotes = {}
    for t in [r_['t'] for r_ in rows] + ['SPY', 'QQQ', 'EWJ', 'DXJ', 'JPXN', 'XLV', 'XLU', 'XLK']:
        try:
            quotes[t] = qs.get(t, fetch=fetch_qs)
        except Exception as e:  # noqa
            quotes[t] = None
    spy_pe = (quotes.get('SPY') or {}).get('trailingPE')

    # ── 日本の改革・インドなど「今の位置」で見る ──
    def since(t, a):
        r = yahoo_safe(t)
        if '__err__' in r:
            return None
        ks = [k for k in sorted(r) if a <= k <= END and k in spy]
        d, g, b = geo_diff(r, spy, ks)
        return {'t': t, '窓': f'{ks[0]}〜{ks[-1]}', '年数': round(len(ks) / 12, 1), '年率%': g, 'SPY年率%': b, '差(%/年)': d}
    japan = {'東証の要請（2023-03-31）の翌月から': [since(t, 202304) for t in ('EWJ', 'DXJ', 'JPXN')],
             'アベノミクスの始まり（2013-01）から': [since(t, 201301) for t in ('EWJ', 'DXJ', 'JPXN')],
             '注': 'EWJ（MSCI 日本）・DXJ（為替ヘッジ付き日本・配当重視）・JPXN（JPX日経400＝資本効率で選ぶ指数）。ドル建て・配当込み'}
    # 歴史の実測（Yahoo で測れる分）
    hist_measured = []
    for t, a, z, lab in [('QQQ', 200004, 201504, 'ナスダック100: 2000年3月の天井の翌月から15年'),
                         ('SMH', 200007, 201006, '半導体（HOLDRS→SMH）: 上場の翌月（2000年の天井の直後）から10年'),
                         ('TAN', 200805, END, '太陽光 TAN: 上場の翌月から今まで'),
                         ('ICLN', 200807, END, 'クリーンエネ ICLN: 上場の翌月から今まで'),
                         ('XOP', 201001, 202012, '石油ガス開発（シェール）XOP: 2010〜2020'),
                         ('KWEB', 202102, 202210, '中国ネット KWEB: 2021年2月の天井から規制強化の底まで')]:
        r = yahoo_safe(t)
        if '__err__' in r:
            hist_measured.append({'対象': lab, '取れない': r['__err__']}); continue
        ks = [k for k in sorted(r) if a <= k <= z and k in spy]
        d, g, b = geo_diff(r, spy, ks)
        hist_measured.append({'対象': lab, 't': t, '窓': f'{ks[0]}〜{ks[-1]}', '年率%': g, 'SPY年率%': b, '差(%/年)': d,
                              '累計%': round((math.exp(math.fsum(math.log1p(r[k]) for k in ks)) - 1) * 100, 1),
                              '最大下落%': round(M.maxdd({k: r[k] for k in ks}) * 100, 1)})

    # ── 主題ごとの今の値段と人気 ──
    theme_now = {}
    for th, rs in by_th.items():
        pes = [(quotes.get(r_['t']) or {}).get('trailingPE') for r_ in rs]
        pes = [p for p in pes if p is not None and 5 <= p < 500]  # 5未満は表示の誤りとみなす（DXJ 4.4 のような値）
        aum = [(quotes.get(r_['t']) or {}).get('totalAssets') for r_ in rs]
        er = [(quotes.get(r_['t']) or {}).get('expense_ratio') for r_ in rs]
        d3 = [r_['直近3年の差(%/年)'] for r_ in rs if r_['直近3年の差(%/年)'] is not None]
        theme_now[th] = {'主題': THEMES_JA[th], '本': [r_['t'] for r_ in rs],
                         '表示PERの中央': round(S.median(pes), 1) if pes else None,
                         'SPYの表示PERに対する倍率': round(S.median(pes) / spy_pe, 2) if pes and spy_pe else None,
                         '資産額の合計(億ドル)': round(sum(a for a in aum if a) / 1e8, 0) if any(aum) else None,
                         '経費率の中央(%)': round(S.median([e for e in er if e]) * 100, 2) if any(er) else None,
                         '直近3年のSPYとの差の中央(%/年)': round(S.median(d3), 1) if d3 else None}

    # ── 防衛の途中の窓（2026-10-12 検証役の指摘「20年続けて SPY を上回った、は言い過ぎ」で追加）──
    rowd = {r_['t']: r_ for r_ in rows}
    dfx = {}
    for t in ('ITA', 'XAR', 'PPA', 'SHLD'):
        r_ = rowd.get(t)
        if not r_:
            continue
        w = [k for k in sorted(series[t]) if 201907 <= k <= 202406 and k in spy]
        dfx[t] = {'上場月(推定)': r_['上場月(推定)'], '年数': r_['年数'], '全期間の差(%/年)': r_['差(%/年)'],
                  '2019-07〜2024-06 の差(%/年)': geo_diff(series[t], spy, w)[0] if len(w) == 60 else None,
                  '転がる5年窓': r_['転がる5年窓（12か月ずらし）'], '転がる10年窓': r_['転がる10年窓（12か月ずらし）']}
    defense_mid = {'明細': dfx, '注': '全期間では SPY を少し上回ったが、途中の5年では大きく負けた時期がある。窓は重なる（独立でない）'}

    def _rw(t, yy):
        x = (dfx.get(t) or {}).get(f'転がる{yy}年窓') or {}
        return f"{x.get('勝った')}/{x.get('窓')}" if x else '—'
    ita, xar, ppa = dfx.get('ITA', {}), dfx.get('XAR', {}), dfx.get('PPA', {})
    w15 = agg['上場から15年以上の本']['SPYに勝った本']
    non_def = [x for x in w15 if x['t'] not in ('ITA', 'XAR', 'PPA')]
    def _sg(x):
        return format(x, '+.2f') if isinstance(x, (int, float)) else '—'
    defense_line = (f"防衛の ETF は上場から約20年で SPY を少し上回った（ITA {_sg(ita.get('全期間の差(%/年)'))}%/年・{ita.get('年数')}年、PPA {_sg(ppa.get('全期間の差(%/年)'))}%/年・{ppa.get('年数')}年、"
                    f"XAR は {xar.get('年数')}年で {_sg(xar.get('全期間の差(%/年)'))}%/年）。ただし途中の5年では大きく負けた時期がある"
                    f"（2019-07〜2024-06 の SPY との差 ITA {_sg(ita.get('2019-07〜2024-06 の差(%/年)'))}%/年・XAR {_sg(xar.get('2019-07〜2024-06 の差(%/年)'))}・PPA {_sg(ppa.get('2019-07〜2024-06 の差(%/年)'))}。"
                    f"ITA が勝ったのは転がる10年窓で {_rw('ITA', 10)}・5年窓で {_rw('ITA', 5)}）。"
                    f"上場から15年以上で SPY に勝った主題の本は防衛のほかにもある（{'・'.join(x['t'] + ' ' + format(x['差(%/年)'], '+.2f') for x in non_def)}）")
    defense_mid['読み'] = defense_line
    OUTLOOK['defense'] = ('市場並み〜やや上の見込み。軍事費は11年連続で増加。' + defense_line +
                          '。PER は SPY の約1.2倍で、2026年の欧州の再軍備は値段に入り始めている')

    # ── 判定（事前に決めた単純な決まり＋人の手の上書きを理由つきで）──
    # 値段と人気: 高い ＝ PER が SPY の1.3倍以上 か 直近3年の差が +10%/年以上 ／ 低い ＝ PER が SPY の0.85倍以下 かつ 直近3年の差が −5%/年以下
    # ⚠ 区分の線（PER が SPY の1.3倍・0.85倍、直近3年の差 +10%/年・−5%/年）と、クリーンエネ・リチウム・EV を手で区分する上書きは
    #   このモジュールが決めたもの（事前登録 modules.R4_themes には無い）。2026-10-12 検証役の指摘で明記し、どの線で決まったかを出す
    def price_level(tn):
        r_ = tn.get('SPYの表示PERに対する倍率'); d3 = tn.get('直近3年のSPYとの差の中央(%/年)')
        why = []
        if r_ is not None and r_ >= 1.3:
            why.append(f'PER が SPY の{r_}倍（1.3倍以上）')
        if d3 is not None and d3 >= 10:
            why.append(f'直近3年の SPY との差 +{d3}%/年（+10%/年以上）')
        if why:
            return '高い（値段に期待が入っている）', '・'.join(why)
        if (r_ is not None and r_ <= 0.85) and (d3 is not None and d3 <= -5):
            return '低い（人気が去った）', f'PER が SPY の{r_}倍（0.85倍以下）かつ直近3年の差 {d3}%/年（−5%/年以下）'
        if r_ is None and d3 is None:
            return '確かめられない', 'PER も直近3年の差も無い'
        if d3 is not None and d3 <= -5:
            return '低め（直近3年 SPY に負け）', f'直近3年の差 {d3}%/年（−5%/年以下）・PER は SPY の{r_}倍'
        return '普通', f'PER は SPY の{r_}倍・直近3年の差 {d3}%/年（どの線にも当たらない）'
    judge = []
    for th, tn in theme_now.items():
        dm = DEMAND.get(th, {})
        hist = agg['主題別・全期間'][THEMES_JA[th]]
        h3 = agg['主題別・上場後3年'][THEMES_JA[th]]
        pl, pl_why = price_level(tn)
        strong = dm.get('強さ', '').startswith('強い')
        if th in ('clean', 'lithium', 'ev'):
            cat = '追い風（量）はあるが株主に届きにくい（値段の崩れ・競争）'
            pl_why += '（区分はモジュールの手の上書き: 量の伸びに値段の崩れ・競争が伴った主題＝DEMAND の注）'
        elif pl.startswith('高い') and strong:
            cat = '追い風だが値段に入っている'
        elif pl.startswith('高い'):
            cat = '値段が先に走っている（追い風の確かさに比べて高い）'
        elif pl.startswith('低') and strong:
            cat = '追い風はあり値段は下がった（候補になりうるが歴史は弱い）'
        elif pl.startswith('低'):
            cat = '人気が去った（値段は下がったが追い風も不確か）'
        elif strong:
            cat = '追い風はあるが値段は普通（基礎率どおり）'
        else:
            cat = '特別な理由なし（基礎率どおり）'
        if not dm:
            cat += '／需要の証拠は集めていない'
        ol = OUTLOOK.get(th)
        if ol:
            ol = (ol + f"（数字: 主題 ETF の実績の中央 {hist.get('中央値(%/年)')}%/年・SPY に勝った {hist.get('SPYに勝った')}・"
                  f"PER は SPY の {tn.get('SPYの表示PERに対する倍率')}倍・直近3年の SPY との差 {tn.get('直近3年のSPYとの差の中央(%/年)')}%/年）")
        judge.append({'主題': THEMES_JA[th], 'theme': th, '本': tn['本'], '需要の追い風': dm or None, '20年で株主が報われる見込み': ol,
                      '今の値段と人気': tn | {'区分の決まりでの値段': pl, 'どの線で決まったか': pl_why},
                      '主題ETFの実績（上場の翌月〜2026-09・SPYとの差）': {k: hist.get(k) for k in ('n', '中央値(%/年)', 'SPYに勝った')},
                      '主題ETFの実績（上場後3年）': {k: h3.get(k) for k in ('n', '中央値(%/年)', 'SPYに勝った')},
                      '区分': cat})

    # 日本の改革（上場の時期ではなく今の位置で）
    jq = quotes.get('EWJ') or {}
    j1 = japan['東証の要請（2023-03-31）の翌月から']
    judge.append({'主題': '日本の改革（資本効率・株主還元）', 'theme': 'japan_reform', '本': ['EWJ', 'DXJ', 'JPXN'],
                  '需要の追い風': DEMAND['japan_reform'],
                  '今の値段と人気': {'EWJの表示PER': jq.get('trailingPE'), 'SPYの表示PERに対する倍率': round(jq['trailingPE'] / spy_pe, 2) if jq.get('trailingPE') and spy_pe else None,
                               '東証の要請の後のSPYとの差(%/年)': {x['t']: x['差(%/年)'] for x in j1 if x},
                               '注': 'DXJ の表示 PER 4.4 は誤りとみなして使わない。DXJ は為替ヘッジ付き（円安の分だけ上に出る）'},
                  '20年で株主が報われる見込み': ('不確か〜市場並み。改革は自社株買いという形で株主に直接届き（2024年度 18.7兆円）、値段は SPY の約0.6倍と安い。'
                                      'だがドル建て・為替ヘッジなしでは要請の後も SPY に負け（EWJ 年 −2.2%・JPXN −2.7%）、2013年からでは年 −6%。'
                                      'リポジトリの測定では日本で報われたのは「質」ではなく配当・割安（CLAUDE.md の JKP の節: 日本の配当利回り +8.4%/年 t4.7）'),
                  '区分': '追い風（制度）はあり値段は低い（候補になりうるが、ドル建てで米国に勝った証拠は無い）'})

    # AI・半導体の特別欄（industry_peak・tech_persist を並べる）
    ip = json.load(open(os.path.join(BASE, 'out', 'industry_peak.json')))
    tp = json.load(open(os.path.join(BASE, 'out', 'tech_persist.json')))
    semi_rows = [r_ for r_ in rows if r_['theme'] == 'semis']
    ai_semis = {
        '今の比重（French 49業種・2025年末）': ip['今_記録を付けている業種'],
        'industry_peak（記録の比重の業種の次の10年・山ごと）': ip['主_閾値5%・次の10年・山ごと'],
        'industry_peak の比較群（記録でない比重5%以上の業種・10年）': ip['比較群_記録でない年(比重5%以上)・10年'],
        'industry_peak・閾値10%（今の二つはここ）・10年': ip['副']['閾値10%・10年'],
        'industry_peak・記録の後5年以内にもう一度記録が来た割合': ip['記録の後_5年以内にもう一度記録が来た割合(その時点の基礎率)'],
        'tech_persist（過去10年の上位5業種の次の10年）': tp['Q1_業種の持続']['次の10年']['全起点（重なる）'],
        'tech_persist（過去10年の1位の業種の次の10年）': {k: tp['事後_過去10年1位の業種の次の10年'][k] for k in ('窓', '中央', '勝率')},
        'tech_persist（今の位置）': tp['今の位置'],
        'tech_persist（テック3業種の時代ごと）': tp['テック3業種(Hardw/Softw/Chips 等分)'],
        'tech_persist（最大の1割が過去10年に市場に勝った後の次の10年）': tp['Q2_最大の1割−市場(%/年)']['過去10年に市場に勝った後の次の10年'],
        '半導体ETFの実測（本ファイル）': [{k: r_[k] for k in ('t', '上場月(推定)', '年数', '差(%/年)', '上場後3年の差(%/年)', '上場後5年の差(%/年)', '直近3年の差(%/年)', '直近5年の差(%/年)')} for r_ in semi_rows],
        'SMH の今（Yahoo）': quotes.get('SMH'),
        'WSTS': DEMAND['semis'],
        '読み': ('需要は本物で今も加速している（WSTS の2026年5月の予想で 2026年の売上 +90%・まだ決まった数字ではない）。だが基礎率はそろって逆を指す: 比重が記録の業種は次の10年に市場に負けやすい'
                 f'（中央 {ip["主_閾値5%・次の10年・山ごと"]["中央値(%/年)"]}%/年・勝ち {ip["主_閾値5%・次の10年・山ごと"]["勝った山"]}・比重10%超の山では '
                 f'{ip["副"]["閾値10%・10年"]["中央値(%/年)"]}%/年・{ip["副"]["閾値10%・10年"]["勝った山"]}）、過去10年の1位の業種は次の10年に '
                 f'中央 {tp["事後_過去10年1位の業種の次の10年"]["中央"]}%/年（勝率 {tp["事後_過去10年1位の業種の次の10年"]["勝率"]}）。'
                 '半導体は直近10年の1位（年33.3%）で、今の比重は100年で最大。ただし記録は続きやすい（5年以内にもう一度記録が来た割合 72.5%）ので時期は当てられない。'
                 '予想の 2026年のメモリーの売上 +250%（メモリーそのものの伸び）は景気の山の形で、山の後の半導体は過去に大きく下げた（2000-07〜2010-06 の SMH は下の歴史の実測）'),
    }

    # ── 事前登録の予想の答え合わせ ──
    m_full = agg['全期間（上場の翌月〜2026-09）'].get('中央値(%/年)')
    m3 = agg['上場後3年'].get('中央値(%/年)'); m5 = agg['上場後5年'].get('中央値(%/年)')
    pred = {'予想': '主題 ETF は上場後に SPY に負けやすい（中央値 −3〜−6%/年）。伸びる産業でも株主が報われるとは限らない',
            '結果': f'全期間の中央 {m_full}%/年（SPY に勝った {agg["全期間（上場の翌月〜2026-09）"]["SPYに勝った"]}）・上場後3年 {m3}%/年（{agg["上場後3年"]["SPYに勝った"]}）・上場後5年 {m5}%/年（{agg["上場後5年"]["SPYに勝った"]}）',
            '判定': None}
    inside = [x for x in (m_full, m3, m5) if x is not None and -6.0 <= x <= -3.0]
    if all(x is not None and x < 0 for x in (m_full, m3, m5)):
        pred['判定'] = ('当たり（向きと幅）' if len(inside) >= 2 else '向きは当たり・幅は外れ（' + ('予想より大きく負けた' if min(m_full, m3, m5) < -6 else '予想より小さい負け') + '）')
    else:
        pred['判定'] = '外れ（SPY に負けていない窓がある）'
    pred['上場前の熱さ（Ben-David ほかの仕組み）の補足'] = (
        '熱さの中央値で分けると、熱い側が負けやすいのは上場後5年だけ。符号（上場前に主題が市場に勝ったか）で分けると3年・全期間でも熱い側が負けやすいが、'
        '順位相関はほぼ0。分け方で見え方が変わるので、この仕組みへの支持は弱いまま（2026-10-12 検証役の指摘で追加）')

    out = {
        'generated': datetime.date.today().isoformat(), 'tool': 'night/bestpf_themes.py', 'module': 'R4_themes',
        'prereg': 'out/bestpf_prereg.json（7c4b672）modules.R4_themes',
        'role': '判断の材料（門・採点・配分は変えない）',
        'source': {'price': 'Yahoo Finance chart API の月足 adjclose（配当込み）＝ night/mw_common.yahoo・キャッシュ out/_bestpf_cache/themes/',
                   'quote': 'Yahoo quoteSummary（表示 PER＝trailingPE・資産額 totalAssets・経費率 annualReportExpenseRatio）',
                   'proxy': 'Ken French 49 Industry Portfolios（時価加重）・F-F_Research_Data_Factors（市場）／FXI・ビットコイン（BTC-USD）・Sensex（^BSESN を INR=X でドル換算）'},
        'method': {'窓': '上場の月（Yahoo の最初の足の月・MJ は主題の転換月 2017-12）の翌月から 2026-09 まで。SPY は同じ月だけ',
                   '差': '幾何の年率の差（ETF の年率 − SPY の年率・%/年）。上場後N年は最初の N×12 か月',
                   '上場前の熱さ': f'上場月の前の{HEAT_MONTHS}か月の、主題の代理の市場に対する相対の富（累計%）',
                   '暦の上のポートフォリオ': '毎月、その月にデータのある本を等分（3本以上の月だけ）。mw_common.excess_stats（NW t・lag12）',
                   '区分の線（事前登録に無い・モジュールが決めた）': ('値段が「高い」＝表示 PER が SPY の1.3倍以上 か 直近3年の SPY との差が +10%/年以上。'
                                                  '「低い」＝PER が SPY の0.85倍以下 かつ 直近3年の差が −5%/年以下。「低め」＝直近3年の差が −5%/年以下。'
                                                  'クリーンエネ・リチウム・EV は値段の線によらず「量はあるが株主に届きにくい」へ手で区分した。'
                                                  'これらの線と上書きは事前登録 modules.R4_themes に無く、このモジュールが決めた（2026-10-12 検証役の指摘で明記）。'
                                                  '各主題の「どの線で決まったか」に理由を出した')},
        'n': len(rows), '取れなかった本': missing,
        '集計': agg,
        '上場からの月数をそろえた平均': {'相対の富': ev, '平均の超過の累計（算術）': path},
        '暦の上のポートフォリオ（等分）': cal,
        '10年の積立で見る': dca_sum,
        '上場の前の熱さと上場後': heat,
        '流行の後に出た本（前の24か月に同じ主題の本が出ていた）': crowd,
        '同じ主題の最古の本の値で各上場から3年先': {'まとめ': sib_sum, '明細': sib},
        '文献_BenDavid': LIT_BENDAVID,
        '新しい産業の歴史': HISTORY,
        '歴史の実測（Yahoo）': hist_measured,
        '日本の改革（今の位置）': japan,
        '主題ごとの判定': judge,
        '防衛の途中の窓': defense_mid,
        'AI・半導体（基礎率を並べる）': ai_semis,
        'SPYの表示PER': spy_pe,
        '事前登録の予想の答え合わせ': pred,
        'rows': rows,
        'quotes': quotes,
    }
    a_ = agg
    hp5 = heat['上場後5年']; hp3 = heat['上場後3年']; hpa = heat['全期間']
    sg = lambda h, k: h['符号で分ける（事後・参考）'][k]  # noqa
    c0 = cal['全部の本']; cr = cal['全部の本・読み']; cp = cal['全部の本・期間を分ける']
    # 区分の一覧は判定から作る（手で写さない）
    SHORT = {'semis': '半導体', 'ai': 'AI', 'robot': 'ロボット', 'cloud': 'クラウド', 'cyber': 'サイバー', 'grid': '送電・インフラ',
             'clean': 'クリーンエネ', 'lithium': 'リチウム', 'nuclear': '原子力', 'defense': '防衛', 'space': '宇宙', 'bio': 'バイオ',
             'medtech': '医療機器', 'fintech': 'フィンテック', 'ark': 'ARK', 'india': 'インド', 'chinanet': '中国ネット', 'gaming': 'ゲーム',
             'cannabis': '大麻', 'blockchain': 'ブロックチェーン', 'print3d': '3D印刷', 'ev': 'EV', 'internet': 'ネット', 'water': '水'}
    CATS = [('追い風だが値段に入っている', '追い風はあるが値段に入っている'), ('値段が先に走っている', '値段が先に走っている'),
            ('追い風はあるが値段は普通', '追い風はあり値段は普通'), ('追い風（量）はあるが株主に届きにくい', '量は伸びたが株主に届きにくい'),
            ('追い風はあり値段は下がった', '追い風はあり値段は下がった'), ('人気が去った', '人気が去った'), ('特別な理由なし', '特別な理由なし')]
    short = {}
    for j in judge:
        if j['theme'] == 'japan_reform':
            continue
        lab = next((b for a, b in CATS if j['区分'].startswith(a)), j['区分'].split('／')[0])
        short.setdefault(lab, []).append(SHORT.get(j['theme'], j['theme']))
    cat_line = '／'.join(f"{k}＝{'・'.join(v)}" for k, v in short.items())
    tn_ai = theme_now['ai']
    out['要約'] = [
        f"主題 ETF {len(rows)}本（取れなかった3本は償還など）を上場の翌月から 2026-09 まで SPY と比べると、差の中央は {a_['全期間（上場の翌月〜2026-09）']['中央値(%/年)']}%/年・SPY に勝ったのは {a_['全期間（上場の翌月〜2026-09）']['SPYに勝った']}。"
        f"上場後3年 {a_['上場後3年']['中央値(%/年)']}%/年（{a_['上場後3年']['SPYに勝った']}）・5年 {a_['上場後5年']['中央値(%/年)']}%/年（{a_['上場後5年']['SPYに勝った']}）・10年 {a_['上場後10年']['中央値(%/年)']}%/年（{a_['上場後10年']['SPYに勝った']}）。QQQ に勝ったのは {a_['QQQとの差・全期間']['QQQに勝った']}",
        f"毎月そろって持つと（等分）年率 {c0['cagr_s']}% 対 SPY {c0['cagr_b']}%（差 {c0['cagr_diff']}%/年）。年のぶれは {c0['vol_s']}% 対 {c0['vol_b']}%＝SPY の約{cr['値動きの大きさの比（年のぶれ÷SPYの年のぶれ）']}倍（ベータ {c0['beta']}）。"
        f"毎月の平均の差（算術）は {c0['ex_ann']}%/年・t {c0['t']} で偶然と区別できないが、"
        f"2001-08〜2009-12（{cp['2001-08〜2009-12']['cagr_s']}% 対 {cp['2001-08〜2009-12']['cagr_b']}%）・2010年代（{cp['2010-01〜2019-12']['cagr_s']} 対 {cp['2010-01〜2019-12']['cagr_b']}）・2020年以降（{cp['2020-01〜2026-09']['cagr_s']} 対 {cp['2020-01〜2026-09']['cagr_b']}）のどれでも SPY を下回った。最初の約4年半はそろう本が4〜5本だけ",
        f"10年の毎月の積立でも、最終額は SPY の積立の中央 {dca_sum['最終額の比の中央（本ごとの本当の中央値の中央）']}〜{dca_sum['最終額の比の中央（本ごとの上側の中央の中央・mw_common.dca と同じ）']}倍（SPY を上回った本 {dca_sum['本ごとの中央の比が1を超えた本（本当の中央値）']}〜{dca_sum['本ごとの中央の比が1を超えた本（上側の中央）']}＝中央値の取り方に依る）",
        f"上場の前の24か月に主題が市場に勝っていた本は {hpa['上場前に主題が市場に勝っていた本の割合']}（大麻3本は代理が無く測れない）。熱さの中央値（約 {hp5['熱さの中央(%)']}〜{hpa['熱さの中央(%)']}%）で分けると、上場後5年は上の半分が中央 {hp5['熱さが中央値より上の半分']['中央値(%/年)']}%/年・下の半分が {hp5['熱さが中央値以下の半分']['中央値(%/年)']}%/年（順位相関 {hp5['順位相関（熱さ vs 上場後）']}）だが、3年・全期間では差が無い。"
        f"符号（上場前に市場に勝ったか）で分けると、5年 {sg(hp5, '上場前に主題が市場に勝っていた本（熱さ>0）')['中央値(%/年)']} 対 {sg(hp5, '負けていた本（熱さ≤0）')['中央値(%/年)']}・3年 {sg(hp3, '上場前に主題が市場に勝っていた本（熱さ>0）')['中央値(%/年)']} 対 {sg(hp3, '負けていた本（熱さ≤0）')['中央値(%/年)']}・全期間 {sg(hpa, '上場前に主題が市場に勝っていた本（熱さ>0）')['中央値(%/年)']} 対 {sg(hpa, '負けていた本（熱さ≤0）')['中央値(%/年)']} と、熱い側が負けやすい形が3つとも出る。ただし順位相関は3年 {hp3['順位相関（熱さ vs 上場後）']}・全期間 {hpa['順位相関（熱さ vs 上場後）']} でほぼ0＝分け方で見え方が変わり、支持は弱い",
        'Ben-David ほか（2023・RFS）: 特化型 ETF は最初の5年でリスク調整後に約30%（約 −6%/年）負け、原因は上場の時点の割高さ。主題型の上場後60か月の市場との差の中央は −0.30%/月（約 −3.6%/年）＝本ファイルの中央とほぼ同じ',
        '新しい産業の歴史は「技術は本物でも株主は報われないことが多い」: 航空会社が稼いだお金の合計は1992年時点でゼロ・自動車は2,000超のブランドから米国3社・RCA は −98%・2000年のテックは −82%・通信は約2兆ドルが消えた・シェールはフリーキャッシュフロー約3,000億ドルの赤字。鉄道は衰退産業なのに1900年から市場に勝った。'
        '国の経済成長と株のリターンの相関は −0.37（Ritter 2005・16か国・p=0.16＝有意ではない）',
        defense_line,
        f'主題ごとの区分（区分の線はこのモジュールが決めた・事前登録に無い）: {cat_line}',
        f"AI（ソフト・広く）は PER が SPY の{tn_ai['SPYの表示PERに対する倍率']}倍でほぼ並み。「高い」とされたのは直近3年の SPY との差 +{tn_ai['直近3年のSPYとの差の中央(%/年)']}%/年（伸び）のため",
        f"AI・半導体: 比重はソフトウェア 19.9%・半導体 19.3% でどちらも100年で最大。記録の比重の業種は次の10年に中央 {ip['主_閾値5%・次の10年・山ごと']['中央値(%/年)']}%/年（{ip['主_閾値5%・次の10年・山ごと']['勝った山']}）、過去10年の1位の業種は次の10年に中央 {tp['事後_過去10年1位の業種の次の10年']['中央']}%/年（勝率 {tp['事後_過去10年1位の業種の次の10年']['勝率']}）。"
        f"需要は WSTS の2026年5月の予想で 2026年の売上 +90%（メモリーの売上そのものは +250%）と本物だが、値段（PER は SPY の {theme_now['semis']['SPYの表示PERに対する倍率']}倍・直近3年 SPY に年 +{theme_now['semis']['直近3年のSPYとの差の中央(%/年)']}%）に入っている",
    ]
    out['事前登録から外れた点'] = [
        '文献の掲載誌: 依頼文は Journal of Finance と書いたが、Ben-David ほか（2023）は The Review of Financial Studies 36(3) に載った。数字は NBER 版（w28369 rev2）から読んだ',
        '上場の前の熱さは、ETF の中身（Ben-David ほかの方法）ではなく、主題に近い業種（French 49）や代理（FXI・ビットコイン・Sensex）の市場との差で測った。大麻は代理が無く「確かめられない」',
        'MJ は2017-12 の大麻への転換を上場とみなした（それ以前は別の中身）',
        '日本の改革は ETF の上場の時期では測れないので、東証の要請（2023-03）とアベノミクス（2013-01）からの SPY との差で見た',
        '今の値段は Yahoo quoteSummary の表示 PER（ETF ごとの計算方法は Yahoo 任せ・赤字の会社の扱いは確かめられない）。DXJ の 4.4 は誤りとみなして使わない',
        '名簿は事前に決めた本（依頼文の例＋同じ主題の本）で、ETF 全体からの無作為ではない。依頼文の IRBO・POTX・BLCN は Yahoo が返さず入っていない',
        '主題の区分の線（PER が SPY の1.3倍・0.85倍、直近3年の差 +10%/年・−5%/年）と、クリーンエネ・リチウム・EV を手で区分する上書きは、事前登録に無くこのモジュールが決めた',
        '上場前の熱さを符号で分けた比べ方・防衛の途中の窓・暦の上のポートフォリオの期間分け・積立の本当の中央値は、検証役の指摘（2026-10-12）を受けた事後の追加（参考）',
    ]
    out['注意'] = [
        '生き残りの偏り: 償還された本（Ben-David ほかでは主題型の37%）は入らない＝本当の基礎率はもっと悪い',
        '窓の終わり（2026-09）は半導体と AI の急騰の中（SMH の直近3年は SPY に年 +39%）。半導体を除くと全期間の差の中央は '
        f"{a_['半導体を除く・全期間']['中央値(%/年)']}%/年",
        '同じ主題の本どうしは独立でない（同じ株を持つ）。主題ごとに最も古い1本だけなら中央 '
        f"{a_['主題ごとに最も古い1本だけ・全期間']['中央値(%/年)']}%/年（{a_['主題ごとに最も古い1本だけ・全期間']['SPYに勝った']}）",
        'ドル建て・配当込み・税前。経費率（主題型の中央 0.6% 前後）は値に入っている',
        '需要の数字の一部は二次資料（IEA の投資額・原子力の大統領令・Deloitte のシェール・RCA の回復年）。本文に「二次」と書いた',
        '「20年の見込み」は基礎率と今の値段からの言葉の評価で、予言ではない。記録の比重は続きやすく（5年以内にもう一度記録 72.5%）、時期は当てられない',
    ]
    out['最終の選択へ渡すもの'] = {
        '主題ETFの基礎率': {'上場後の SPY との差の中央(%/年)': a_['全期間（上場の翌月〜2026-09）']['中央値(%/年)'], '上場後10年で SPY に勝った': a_['上場後10年']['SPYに勝った'],
                       '10年積立の最終額の比の中央': f"{dca_sum['最終額の比の中央（本ごとの本当の中央値の中央）']}〜{dca_sum['最終額の比の中央（本ごとの上側の中央の中央・mw_common.dca と同じ）']}",
                       '10年積立で SPY を上回った本': f"{dca_sum['本ごとの中央の比が1を超えた本（本当の中央値）']}〜{dca_sum['本ごとの中央の比が1を超えた本（上側の中央）']}（中央値の取り方に依る）"},
        '使い方': '「これから伸びる主題」という理由だけで候補の本を足さない。足すなら B・C の世界で主題型の基礎率（−3%/年前後）を引いて比べる',
        '半導体（SMH）の割引の幅': {'記録の比重の業種・10年': ip['主_閾値5%・次の10年・山ごと']['中央値(%/年)'], '比重10%超の山・10年': ip['副']['閾値10%・10年']['中央値(%/年)'],
                             '過去10年の1位の業種・10年': tp['事後_過去10年1位の業種の次の10年']['中央'], '意味': 'etf_forward_rank の K4（半導体の基礎率）の感度と同じ向き。−1.5〜−4.0%/年の幅で感度を取る'},
        '防衛（ITA・XAR・PPA）': (defense_line + f"。値段は SPY の{theme_now['defense']['SPYの表示PERに対する倍率']}倍。上乗せは見込まず市場並みで扱うのが無難"),
        '送電・サイバー・クラウド': '市場並み（上乗せなし）。PER は SPY の1.2〜1.4倍',
        'P15πとの関係': ('主の物差しは P15π（20年の積立で年15%以上の確率）。15%を超えるには高い伸びとぶれが要り、半導体は A1・A2 の世界でそれを満たすが、'
                        f"B・C の世界では基礎率の割引（上の幅）を受ける。主題 ETF をまとめて持つ形は、年のぶれが {c0['vol_s']}%（SPY の約{cr['値動きの大きさの比（年のぶれ÷SPYの年のぶれ）']}倍・ベータ {c0['beta']}）で、"
                        f"年率は SPY より {abs(c0['cagr_diff'])}% 低かった（算術の差 {c0['ex_ann']}%/年・t {c0['t']} は偶然と区別できないが、3つの時期のどれでも下回った）＝15%に届く確率を上げない"),
        '避ける側': 'クリーンエネ・リチウム・EV・大麻・インド・中国ネット（上場後の差 −8〜−39%/年）。「量は伸びたが株主は報われない」の実例',
        '日本の改革': '値段は SPY の約0.6倍で制度の追い風はあるが、ドル建て（ヘッジなし）では要請の後も SPY に年 −2.2%。15%以上を狙う物差し（事前登録の改め 2026-10-12 の P15π）の候補ではなく、分散の材料',
    }
    out['最終の選択へ渡すもの']['半導体の需要の数字'] = 'WSTS の2026年5月の予想（まだ決まった数字ではない）: 世界の売上 +89.9%・メモリーの売上そのものは +249.5%（全体の増加の約80%がメモリー）＝景気の山の形'
    out['fixes_applied'] = [
        {'重さ': 'medium', '指摘': '「防衛だけは20年続けて SPY を少し上回った」は言い過ぎ（『だけ』『続けて』）',
         '直したこと': ('要約・最終の選択へ渡すもの・OUTLOOK[defense] の文を、全期間の差と途中の負けを並べる文（defense_line・数字はコードで計算）へ置き換えた。'
                     '各本に転がる5年・10年窓（12か月ずらし）を足し、『上場から15年以上の本』『上場から20年以上の本』で SPY に勝った本の一覧と、『防衛の途中の窓』を足した'),
         '直した後': defense_line},
        {'重さ': 'medium', '指摘': '『ぶれは SPY の1.4倍』は計算の誤り（23.7÷14.9＝1.59。1.38 はベータ）',
         '直したこと': 'ぶれの比をコードで計算して書き、ベータは別に書いた（要約・P15πとの関係）。算術の差と t、期間を分けた年率、ぶれによる目減りの近似、最初の時期の本数も足した',
         '直した後': f"年のぶれ {c0['vol_s']}% 対 {c0['vol_b']}%＝{cr['値動きの大きさの比（年のぶれ÷SPYの年のぶれ）']}倍・ベータ {c0['beta']}・算術の差 {c0['ex_ann']}%/年 t {c0['t']}"},
        {'重さ': 'low', '指摘': '熱さの分け方の名前が中身と合わない・分母（76→73）・分け方に依る結論',
         '直したこと': '見出しを『熱さが中央値より上の半分／以下の半分』に改め、符号で分けた比べ方（事後・参考）を足した。要約の分母は計算値（73本）を使う。予想の答え合わせに補足を足した',
         '直した後': f"上場前に主題が市場に勝っていた本 {hpa['上場前に主題が市場に勝っていた本の割合']}"},
        {'重さ': 'low', '指摘': 'WSTS の数字は予想・メモリーの +250% は内訳ではない',
         '直したこと': 'DEMAND・AI と半導体の読み・要約・最終の選択へ渡すものを『WSTS の2026年5月の予想』『メモリーの売上そのものの伸び』に改めた（全体の増加の約80%がメモリー）'},
        {'重さ': 'low', '指摘': '10年積立の『SPY を上回った本 17/45』は上側の中央値に依る',
         '直したこと': '同じ積み方で本当の中央値（statistics.median）も出し、両方を並べた',
         '直した後': f"{dca_sum['本ごとの中央の比が1を超えた本（本当の中央値）']}〜{dca_sum['本ごとの中央の比が1を超えた本（上側の中央）']}・中央 {dca_sum['最終額の比の中央（本ごとの本当の中央値の中央）']}〜{dca_sum['最終額の比の中央（本ごとの上側の中央の中央・mw_common.dca と同じ）']}倍"},
        {'重さ': 'low', '指摘': '航空の『1919〜39年に約300社』は飛行機メーカー・RCA の安値は GFD では 2.625ドル・GFD の URL は開けない',
         '直したこと': 'Fortune の原文（2026-10-12 に WebFetch で確認: aircraft manufacturers・airline companies の合計は1992年時点でゼロ）に合わせた。RCA は 114.75→2.625ドル（同じ記事の別の箇所と Time 誌は 2.50）とし、URL が 404 であることと、確かめた経路（検索結果の要約・The Bubble Blog）を注記した'},
        {'重さ': 'low', '指摘': '主題の区分の線と手の上書きが事前登録に無い・AI が高いとされた理由',
         '直したこと': 'method と事前登録から外れた点に明記し、各主題に『どの線で決まったか』を出した。要約に AI は PER が SPY 並みで、高いとされたのは直近3年の伸びと書いた',
         '直した後': f"AI: {[j for j in judge if j['theme'] == 'ai'][0]['今の値段と人気']['どの線で決まったか']}"},
        {'重さ': 'low', '指摘': '暦の上のポートフォリオの t と時期の偏り・Ritter の p 値が要約に無い',
         '直したこと': '要約に算術の差 t・3つの時期の年率・最初の時期の本数、Ritter の「16か国・p=0.16」を足した'},
        {'重さ': 'low', '指摘': '『QQQとの差・全期間』のキーが SPYに勝った のまま・SIPRI の数字の丸め',
         '直したこと': 'キーを『QQQに勝った』に改めた（summ に見出しの引数）。SIPRI は 2兆8,870億ドル（原文 $2887 billion）に改めた'},
        {'重さ': 'low', '指摘': 'DMS 2015 の図6は p.11',
         '直したこと': '直していない。2026-10-12 に PDF を取り直して pdftotext で確かめると、図6（62,716・39,134）は印刷のページ番号「YEARBOOK 2015 _ 10」のページにあり、p.11 にあるのは IPO の数字（18.6%・31.6%）。元の「図6・p.10」が正しい'},
    ]
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    return out


if __name__ == '__main__':
    o = main(fetch_qs='--no-qs' not in sys.argv)
    a = o['集計']
    print('n', o['n'], '取れない', [m['t'] for m in o['取れなかった本']])
    for k in ('全期間（上場の翌月〜2026-09）', '上場後1年', '上場後3年', '上場後5年', '上場後10年', 'QQQとの差・全期間', '半導体を除く・全期間', '主題ごとに最も古い1本だけ・全期間'):
        print(k, a[k])
    print(json.dumps(o['事前登録の予想の答え合わせ'], ensure_ascii=False))
