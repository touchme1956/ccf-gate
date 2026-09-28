#!/usr/bin/env python3
"""night/nx_pre1926x_data.py — 角度 nx_pre1926x（他セッションで検証を生き残った規則を、誰も使っていない 1709〜1929 年に
作り直さずそのまま当てる＝独立の時代の答え合わせ）の【取得と整形・規則の台帳・格付けの定義】だけ。

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて勝てる結果を出して…
別のSessionで検証していない新たな分析を同じ内容でしてほしい」。事前登録は out/nx_pre1926x_prereg.json。

★成績は一つも計算しない・表示しない（規則のリターン・市場との差・t・シャープは出さない）。このファイルが出すのは
  データの形（列・期間・欠け・銘柄数・業種数・掃除で落ちた件数・規則が定義できる月数）だけ。
  ポートフォリオの組み立て（build_*）と格付け（grade_era）の関数は事前登録の定義そのもので、ここでは
  合成の乱数データ（--selftest）でしか動かしていない。測る道具 night/nx_pre1926x.py（これから書く）はここを import する（写さない）。

使うデータ（キャッシュ out/_nx_cache/・gitignore）
- Cowles Commission『Common-Stock Indexes』(1938/39) の月次指数（Yale ICF）:
    Series P（株価）Stock_Prices-Cowles.xls / Series C（現金配当を再投資した株価＝総リターン）Stock_PricesincDvds-Cowles.xls
    ★各月の値は『その月の高値と安値の平均』（Cowles 1938 の Introduction『6. Construction』）。1918 年以降の一部の業種は
      Standard Statistics の週次の月平均へつないである＝どちらも月中の平均（Working 1960 の見かけの自己相関）
- Yale ICF の Old NYSE（Goetzmann-Ibbotson-Peng 2001）: nyse-monthly-price-1815-1925-updated-2021-09-04-with-labels.csv
    （671 証券・月次の価格＝買い気配と売り気配の平均・新聞が欠けた月は前後の月の平均で埋めてある＝Yale のページの説明）
    Price-Weighted-Index-Returns-2020-08-20.xls（中身は CSV・GIP の価格加重の指数のリターン・報告の相手）
- Yale ICF の London Stock Exchange（Investor's Monthly Manual・Goetzmann-Rouwenhorst）: Railways_new / Banks_new / Misc_new
    （生の月次・1869-01〜1907-12 と 1915-01〜1929-12。1908〜1914 は欠け）と Totaldata.zip（整えた版・★Excel の行の上限
    1,048,575 行で切れている＝ ID 40407 の 1895-08 まで。証券の型の照合にだけ使う）
- イングランド銀行『A millennium of macroeconomic data for the UK』v3.1: M13（月次の株価指数 1709〜）・M9（月次の短期金利）
- FRED の NBER 歴史系列: M13002US35620M156NNBR（ニューヨークの商業手形 4〜6か月・年率%・1857〜1971・月平均）

使い方:
  python3 night/nx_pre1926x_data.py            # 取得＋形の報告（JSON を標準出力へ）
  python3 night/nx_pre1926x_data.py --extract  # 測る道具が読む抽出 out/_nx_cache/nx_pre1926x_extract.json を作り sha を出す
  python3 night/nx_pre1926x_data.py --selftest # 組み立ての関数を合成データだけで点検（実データは読まない）
"""
import csv, io, json, math, os, re, sys, zipfile, collections, pickle, hashlib, random, statistics as ST

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as C  # noqa: E402

CACHE = C.CACHE
EXTRACT = os.path.join(CACHE, 'nx_pre1926x_extract.json')
YALE = 'https://som.yale.edu/sites/default/files/'
URLS = {
    'cowles_P': (YALE + '2021-12/Stock_Prices-Cowles.xls', 'yale_cowles_stock_prices_monthly.xls'),
    'cowles_C': (YALE + '2021-12/Stock_PricesincDvds-Cowles.xls', 'yale_cowles_prices_incdvds.xls'),
    'cowles_intro': (YALE + '2021-12/Introduction.xls', 'yale_cowles_Introduction.xls'),
    'nyse': (YALE + '2022-02/nyse-monthly-price-1815-1925-updated-2021-09-04-with-labels.csv', 'yale_nyse_monthly_1815_1925.csv'),
    'nyse_pw': (YALE + '2021-12/Price-Weighted-Index-Returns-2020-08-20.xls', 'yale_nyse_pw_index_returns.xls'),
    'nyse_notes1': (YALE + '2022-01/UpdateNotes-2021-09-04.pdf', 'yale_nyse_UpdateNotes-2021-09-04.pdf'),
    'nyse_notes2': (YALE + '2021-12/RevisionNotes-2020-08-20.pdf', 'yale_nyse_RevisionNotes-2020-08-20.pdf'),
    'lse_rail': (YALE + '2021-12/Railways_new.csv.zip', 'yale_lse_Railways_new.csv.zip'),
    'lse_bank': (YALE + '2021-12/Banks_new.csv.zip', 'yale_lse_Banks_new.csv.zip'),
    'lse_misc': (YALE + '2021-12/Misc_new.csv.zip', 'yale_lse_Misc_new.csv.zip'),
    'lse_total': (YALE + '2021-12/Totaldata.zip', 'yale_lse_Totaldata.zip'),
    'boe': ('https://www.bankofengland.co.uk/-/media/boe/files/statistics/research-datasets/a-millennium-of-macroeconomic-data-for-the-uk.xlsx', 'boe_millennium.xlsx'),
    'nber_cp': ('https://fred.stlouisfed.org/graph/fredgraph.csv?id=M13002US35620M156NNBR', 'fred_M13002US35620M156NNBR.csv'),
}
MON = {m: i + 1 for i, m in enumerate(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'])}

# 期間（事前登録の data.periods と同じ）
COWLES_END = 192606          # 1926-07 から French（CRSP）＝他セッションの規則が作られたデータと重なるので使わない
COWLES_CLOSED = (191408, 191409, 191410, 191411)   # NYSE の閉鎖。1914-12 の値は 1914-07 からの1期間
LSE_SEGMENTS = ((186902, 190712), (191502, 192912))  # 生の IMM に 1908-01〜1914-12 の価格が無い（形で確認）
NYSE_SEGMENTS = ((181502, 192512),)
UK_HAL_MAIN = (170905, 191406)   # 英国のハロウィーンの主の期間（第一次大戦の閉鎖の前まで）
UK_HAL_REPORT = (191502, 192512)


def fetch(key, max_age_days=365):
    u, n = URLS[key]
    return C.get(u, name=n, max_age_days=max_age_days)


def path(key):
    fetch(key)
    return os.path.join(CACHE, URLS[key][1])


def sha(key):
    return hashlib.sha256(open(path(key), 'rb').read()).hexdigest()[:16]


def madd(ym, k):
    y, m = divmod(ym, 100)
    t = y * 12 + (m - 1) + k
    return (t // 12) * 100 + t % 12 + 1


def month_range(a, z, skip=()):
    out, k = [], a
    while k <= z:
        if k not in skip:
            out.append(k)
        k = madd(k, 1)
    return out


def round_half_up(x):
    return int(math.floor(x + 0.5))


# ═════════════════════════ Cowles ═════════════════════════
# 索引番号（Cowles の本の Alphabetical List of Indexes）。Series P の xls では 列 = 番号 + 2
COWLES_COMBOS = {1: 'All Stocks', 2: 'Industrials', 4: 'Utilities', 5: 'Coal', 12: 'Steel and Iron', 34: 'Retail Trade',
                 39: 'Tobacco and Tobacco Products', 41: 'Automobiles and Trucks', 44: 'Retail Trade—Chain Stores', 58: 'Airplane'}
# 子（『親—子』の名前の業種）→ 親。10 の組合せ（59 の業種＋10 の組合せ＝69）はちょうど子を持つ番号
COWLES_CHILD = {53: 5, 54: 5, 28: 12, 29: 12, 35: 34, 36: 34, 44: 34, 45: 34, 48: 34, 59: 34, 61: 34, 69: 34,
                30: 39, 40: 39, 42: 41, 43: 41, 66: 58, 67: 58, 9: 4, 11: 4, 16: 4, 20: 4}
COWLES_SECTOR_AGG = (1, 2, 4)          # 市場・部門の集計（業種の横断から外す）。Utilities(4) の子 9・11・16・20 は業種として残る
TOBACCO_SPLICE = (39, 30)              # 親 39 が値を持たない月だけ子 30（葉巻）で埋める唯一のつなぎ（30 は 1901〜・39 は 1912〜）


def _cell_num(v):
    """xls の値 → 正の数か None。文字の数字（'1465.'・'70:2'・'198 6'・'988.8.'＝写しの癖）も読む。
    '- - -'・'N.Y.S.E. CLOSED'・'(DISCONTINUED)' は None（0 と読まない）"""
    if isinstance(v, float):
        return v if v > 0 else None
    s = str(v).strip()
    if not s:
        return None
    s = re.sub(r'(?<=\d)[: ](?=\d)', '.', s)
    s = s.rstrip('.')
    if not re.match(r'^\d+(\.\d+)?$', s):
        return None
    x = float(s)
    return x if x > 0 else None


TEXT_NUM_CELLS = collections.Counter()


def cowles_P():
    """Series P → ({番号: {yyyymm: 水準}}, {番号: 名前})。年は列0・月は列1から読む
    （列2の『MM/YYYY』は 1905 年の12行がすべて '01/1905' になっている＝写しの誤り）"""
    import xlrd
    sh = xlrd.open_workbook(path('cowles_P')).sheet_by_index(0)
    names = {c - 2: str(sh.cell_value(0, c)).strip() for c in range(3, sh.ncols)}
    out = {n: {} for n in names}
    for r in range(1, sh.nrows):
        try:
            y = int(float(sh.cell_value(r, 0)))
        except ValueError:
            continue
        mo = MON.get(str(sh.cell_value(r, 1)).strip()[:3])
        if not mo or not 1860 <= y <= 1945:
            continue
        ym = y * 100 + mo
        for c in range(3, sh.ncols):
            v = _cell_num(sh.cell_value(r, c))
            if v is not None:
                if sh.cell_type(r, c) == 1:
                    TEXT_NUM_CELLS['P'] += 1
                out[c - 2][ym] = v
    return out, names


def cowles_C():
    """Series C（ページ組みの表）→ ({番号: {yyyymm: 水準}}, {番号: 見出し})。'C-n' の見出しの下の年の行を読む"""
    import xlrd
    sh = xlrd.open_workbook(path('cowles_C')).sheet_by_index(0)
    out, title, cur = {}, {}, None
    for r in range(sh.nrows):
        c0 = str(sh.cell_value(r, 0)).strip()
        m = re.match(r'^C-(\d+)', c0)
        if m:
            cur = int(m.group(1))
            out.setdefault(cur, {})
            t = ' '.join(str(sh.cell_value(r, c)).strip() for c in range(1, sh.ncols) if str(sh.cell_value(r, c)).strip())
            if t and '(concluded' not in c0:
                title.setdefault(cur, t)
            continue
        if cur is None:
            continue
        try:
            y = int(float(c0))
        except ValueError:
            continue
        if not 1860 <= y <= 1945:
            continue
        for mo in range(1, 13):
            v = _cell_num(sh.cell_value(r, mo))
            if v is not None:
                if sh.cell_type(r, mo) == 1:
                    TEXT_NUM_CELLS['C'] += 1
                out[cur][y * 100 + mo] = v
    return out, title


def _lr(a, b):
    return math.log(b / a)


def cowles_months(end=COWLES_END):
    """Cowles の取引月の並び（閉鎖の4か月を飛ばす＝1914-07 の次は 1914-12）"""
    return month_range(187101, end, skip=COWLES_CLOSED)


def cowles_returns(P=None, Cs=None, end=COWLES_END):
    """事前登録どおりの Cowles の月次リターン（総リターン＝Series C を主）。
    - 連続する2つの取引月の水準から r_t。1914-08〜11（取引所の閉鎖）は取引月から外し、1914-12 の値は 1914-07 からの5か月
    - C と P の食い違い: d_t = ln(C_t/C_{t−1}) − ln(P_t/P_{t−1}) が [−0.01, 0.05] の外なら点検。
        C 側だけが『跳ねて戻る』（|c_t|>0.15・|c_{t+1}|>0.15・符号が逆・|c_t+c_{t+1}|<0.05）なら C の写し誤りとみなし
        r_t = exp(p_t + d̃) − 1（d̃ = その業種の直前12の有効な月の d の中央値・無ければ 0.004）
        P 側だけが跳ねて戻るなら P の写し誤り＝C をそのまま使う。どちらとも決まらなければ欠測（0 と読まない）
    戻り値: ({番号: {ym: r}}, 点検の件数の辞書, 直した月の一覧)"""
    if P is None:
        P, _ = cowles_P()
    if Cs is None:
        Cs, _ = cowles_C()
    stats = collections.Counter()
    fixes = []
    R = {}
    allm = cowles_months(end)
    spike = lambda a, b: a is not None and b is not None and abs(a) > 0.15 and abs(b) > 0.15 and a * b < 0 and abs(a + b) < 0.05
    for n in sorted(set(P) | set(Cs)):
        p, c = P.get(n, {}), Cs.get(n, {})
        out, dhist = {}, []
        for i in range(1, len(allm)):
            t0, t1 = allm[i - 1], allm[i]
            cp = c.get(t0), c.get(t1)
            pp = p.get(t0), p.get(t1)
            cr = _lr(*cp) if None not in cp else None
            pr = _lr(*pp) if None not in pp else None
            if cr is None and pr is None:
                continue
            if cr is not None and pr is not None:
                d = cr - pr
                if -0.01 <= d <= 0.05:
                    out[t1] = math.exp(cr) - 1
                    dhist.append(d)
                    stats['agree'] += 1
                    continue
                stats['disagree'] += 1
                t2 = allm[i + 1] if i + 1 < len(allm) else None
                c2 = _lr(c[t1], c[t2]) if t2 and t1 in c and t2 in c else None
                p2 = _lr(p[t1], p[t2]) if t2 and t1 in p and t2 in p else None
                t_1 = allm[i - 2] if i >= 2 else None
                cprev = _lr(c[t_1], c[t0]) if t_1 and t_1 in c and t0 in c else None
                pprev = _lr(p[t_1], p[t0]) if t_1 and t_1 in p and t0 in p else None
                c_bad = spike(cr, c2) or spike(cprev, cr)
                p_bad = spike(pr, p2) or spike(pprev, pr)
                if c_bad and not p_bad:
                    dt = sorted(dhist[-12:])
                    dd = dt[len(dt) // 2] if dt else 0.004
                    out[t1] = math.exp(pr + dd) - 1
                    stats['fix_C_typo'] += 1
                    fixes.append((n, t1, 'C'))
                elif p_bad and not c_bad:
                    out[t1] = math.exp(cr) - 1
                    stats['fix_P_typo'] += 1
                    fixes.append((n, t1, 'P'))
                else:
                    stats['unresolved_missing'] += 1
                    fixes.append((n, t1, '?'))
            elif cr is not None:
                out[t1] = math.exp(cr) - 1          # P が無い月（C だけ）
                stats['C_only'] += 1
            else:
                stats['P_only_missing'] += 1          # C が無い月は総リターンが無い＝欠測（P で埋めない・主）
        R[n] = out
    return R, dict(stats), fixes


def cowles_price_returns(P, n=1, end=COWLES_END):
    """Series P（配当なし）の連続する取引月のリターン（報告の相手: NYSE の単位と同じ『価格だけ』の基準で比べるため）"""
    allm = cowles_months(end)
    p = P.get(n, {})
    return {t1: p[t1] / p[t0] - 1 for t0, t1 in zip(allm, allm[1:]) if t0 in p and t1 in p}


def cowles_industry_universe(R):
    """事前登録の業種の母集団（親を先に）: 集計 1・2・4 を外し、子（『親—子』）を外す。
    Tobacco だけ 39 が無い月を 30（葉巻）で埋める。戻り値 {業種キー: {ym: r}}"""
    out = {}
    for n, s in R.items():
        if n in COWLES_SECTOR_AGG:
            continue
        if n in COWLES_CHILD and COWLES_CHILD[n] not in COWLES_SECTOR_AGG:
            continue
        if n == 39:
            s = dict(R.get(30, {}))
            s.update(R.get(39, {}))
        out[n] = s
    return out


# ═════════════════════════ 掃除（株ごとの月次リターン） ═════════════════════════
def clean_returns(r, cnt):
    """株ごとの {ym: r}（連続する月の対だけ）を掃除する。事前登録の data.cleaning と同じ:
    (1) 跳ねて戻る写し誤り（Hou-Karolyi-Kho 2011 の月次の規則）: 連続する2か月 a,b で r_a か r_b が +300% を超え、
        (1+r_a)(1+r_b)−1 < +50% なら両方を欠測にする
    (2) +990% を超える月は欠測
    欠測は 0 で埋めない（その月はその株を持たないのと同じ＝重みを残りで割り直す）"""
    r = dict(r)
    ks = sorted(r)
    drop = set()
    for a, b in zip(ks, ks[1:]):
        if madd(a, 1) != b:
            continue
        if (r[a] > 3.0 or r[b] > 3.0) and (1 + r[a]) * (1 + r[b]) - 1 < 0.5:
            drop.add(a); drop.add(b)
    for k in drop:
        r.pop(k, None)
    cnt['drop_reversal_300pct'] += len(drop)
    big = [k for k, v in r.items() if v > 9.9]
    for k in big:
        r.pop(k)
    cnt['drop_gt_990pct'] += len(big)
    return r


# ═════════════════════════ Old NYSE（GIP） ═════════════════════════
def _nyse_date(s):
    s = s.strip()
    m = re.match(r'^([A-Za-z]{3})-(\d{2,4})$', s)
    if not m:
        return None
    y = int(m.group(2))
    if y < 100:
        y += 1900           # 1900 年以降は2桁（'Aug-25' = 1925-08）
    return y * 100 + MON[m.group(1)]


def nyse():
    """→ (meta {列: {name, uid, industry, class, type}}, prices {列: {ym: 価格}})。'NA' は入れない"""
    rows = list(csv.reader(open(path('nyse'), encoding='utf-8-sig')))
    ids = rows[0][1:]
    lab = {r[0]: r[1:] for r in rows[1:6]}
    meta = {ids[j]: {'name': lab['Company'][j], 'uid': lab['Unique.number'][j], 'industry': lab['Industry'][j],
                     'class': lab['Class'][j], 'type': lab['Type'][j]} for j in range(len(ids))}
    px = {i: {} for i in ids}
    for r in rows[6:]:
        ym = _nyse_date(r[0])
        if ym is None:
            continue
        for j, v in enumerate(r[1:]):
            if v in ('NA', ''):
                continue
            try:
                x = float(v)
            except ValueError:
                continue
            if x > 0:
                px[ids[j]][ym] = x
    return meta, px


# 普通株の判定: 標識つき（Class/Type）は Equity/common だけ。標識の無い 420 証券は名前に優先株・書付・権利・保証・債券・新旧の別の語が
# 無いものを普通株とみなす（標識つきの側で 'new'・'old'・'scrip'・'prefer' を普通株から外しているのと同じ線）
NYSE_NONCOMMON = re.compile(r"pref|preff|\bpfd?\b|\bpf\.|scrip|script|s'p\b|certif|\brights?\b|guar|bond|\bdeb|,\s*(new|old)\b|\b(new|old) stock|\bstate of\b", re.I)


def nyse_is_common(m):
    if m['class'] == 'Equity' and m['type'] == 'common':
        return True
    if m['class'] == '' and m['type'] == '':
        return not NYSE_NONCOMMON.search(m['name'])
    return False


def nyse_panel():
    """→ {'ret': {列: {ym: r}}, 'filled': {列: [ym…]}, 'last': {列: ym}, 'first': {列: ym}, 'counts': Counter}
    ret は連続する2か月の価格の比だけ（間の月が欠けていれば作らない）→ clean_returns。
    filled = p_t がちょうど (p_{t−1}+p_{t+1})/2（前後の月の平均で埋めた月の見込み・相対 1e−9 以内・p_{t−1}≠p_{t+1}）"""
    meta, px = nyse()
    cnt = collections.Counter()
    ret, filled, last, first = {}, {}, {}, {}
    for i, m in meta.items():
        if not nyse_is_common(m):
            cnt['not_common'] += 1
            continue
        p = px[i]
        if not p:
            continue
        ks = sorted(p)
        first[i], last[i] = ks[0], ks[-1]
        r = {}
        for a, b in zip(ks, ks[1:]):
            if madd(a, 1) == b:
                r[b] = p[b] / p[a] - 1
                cnt['pairs'] += 1
        fl = []
        for a, b, c in zip(ks, ks[1:], ks[2:]):
            if madd(a, 1) == b and madd(b, 1) == c and p[a] != p[c] and abs(p[b] - (p[a] + p[c]) / 2) <= 1e-9 * p[b]:
                fl.append(b)
        filled[i] = fl
        cnt['filled_months'] += len(fl)
        ret[i] = clean_returns(r, cnt)
        cnt['common'] += 1
    return {'ret': ret, 'filled': filled, 'last': last, 'first': first, 'counts': cnt}


def nyse_pw_index():
    """GIP の価格加重の指数のリターン（ファイルの拡張子は .xls だが中身は CSV）→ {'2015': {ym: r}, '2020': {ym: r}}"""
    rows = list(csv.reader(open(path('nyse_pw'), encoding='latin-1')))
    out = {'2015': {}, '2020': {}}
    for r in rows[1:]:
        ym = _nyse_date(r[0])
        if ym is None:
            continue
        for k, v in zip(('2015', '2020'), r[1:3]):
            try:
                out[k][ym] = float(v)
            except ValueError:
                pass
    return out


# ═════════════════════════ イングランド銀行・NBER ═════════════════════════
def _boe_sheet(name):
    import openpyxl
    pk = os.path.join(CACHE, 'nx_pre1926x_boe_' + re.sub(r'\W+', '_', name) + '.pkl')
    if os.path.exists(pk) and os.path.getmtime(pk) > os.path.getmtime(path('boe')):
        return pickle.load(open(pk, 'rb'))
    wb = openpyxl.load_workbook(path('boe'), read_only=True, data_only=True)
    rows = [tuple(r) for r in wb[name].iter_rows(values_only=True)]
    pickle.dump(rows, open(pk, 'wb'))
    return rows


def uk_share_prices():
    """M13 → ({列: {ym: 水準}}, {列: 説明})。列 23 = つないだ月次の指数（主）、列 24 = その前月比 %"""
    rows = _boe_sheet('M13. Mthly share prices 1709+ ')
    W = max(len(r) for r in rows)
    desc = {c: ' / '.join(str(rows[i][c]) for i in (2, 3) if c < len(rows[i]) and rows[i][c] is not None) for c in range(2, W)}
    out = {c: {} for c in range(2, W)}
    for r in rows[4:]:
        if not r or r[0] is None or r[1] not in MON:
            continue
        ym = int(r[0]) * 100 + MON[r[1]]
        for c in range(2, W):
            if c < len(r) and isinstance(r[c], (int, float)) and r[c] > 0:
                out[c][ym] = float(r[c])
    return out, desc


def uk_rates():
    """M9 → ({列: {ym: 年率%}}, {列: 説明})。列 2 = Bank Rate（月末）・列 6 = 3か月の一流手形の割引率（月平均 1824〜1939）・
    列 9 = 3か月の銀行手形（月末 1870〜1982）・列 14 = 一流の短期の手形のつないだ系列（1718〜・月末と月平均の混ざり）"""
    rows = _boe_sheet('M9. Mthly short-term rates')
    W = max(len(r) for r in rows)
    desc = {c: ' / '.join(str(rows[i][c]) for i in (2, 3, 4, 5, 6) if c < len(rows[i]) and rows[i][c] is not None) for c in range(2, W)}
    out = {c: {} for c in range(2, W)}
    for r in rows[7:]:
        if not r or r[0] is None or r[1] not in MON:
            continue
        try:
            ym = int(r[0]) * 100 + MON[r[1]]
        except (TypeError, ValueError):
            continue
        for c in range(2, W):
            if c < len(r) and isinstance(r[c], (int, float)):
                out[c][ym] = float(r[c])
    return out, desc


def nber_cp():
    """ニューヨークの商業手形の金利（年率%・月平均）→ {ym: 月の小数リターン = 年率/1200}"""
    lines = fetch('nber_cp').decode().splitlines()[1:]
    out = {}
    for ln in lines:
        d, v = ln.split(',')
        try:
            out[int(d[:4]) * 100 + int(d[5:7])] = float(v) / 1200
        except ValueError:
            pass
    return out


def uk_cash(rt=None):
    """英国の現金（月 t の小数リターン）= 列 9（3か月の銀行手形・月末）の t−1 の値 ÷1200。列 9 が無い月は列 6（月平均）の t の値。
    どちらも無い月は無い（0 と読まない）"""
    if rt is None:
        rt, _ = uk_rates()
    out = {}
    for k in sorted(set(rt[6]) | set(rt[9])):
        p = madd(k, -1)
        if p in rt[9]:
            out[k] = rt[9][p] / 1200
        elif k in rt[6]:
            out[k] = rt[6][k] / 1200
    return out


def uk_hal_rate(rt=None):
    """英国のハロウィーンの借入の基準（月 t の小数）= 列 14（1718-03〜）、無ければ列 2（Bank Rate・1694〜）の t の値 ÷1200"""
    if rt is None:
        rt, _ = uk_rates()
    out = {}
    for k in sorted(set(rt[14]) | set(rt[2])):
        v = rt[14].get(k, rt[2].get(k))
        if v is not None:
            out[k] = v / 1200
    return out


def uk_index_returns(uk=None):
    """列 23（つないだ月次の指数）の連続する2か月の比。1914-07〜1914-12 の閉鎖を挟む月は作らない"""
    if uk is None:
        uk, _ = uk_share_prices()
    s = uk[23]
    return {b: s[b] / s[a] - 1 for a, b in zip(sorted(s), sorted(s)[1:]) if madd(a, 1) == b}


# ═════════════════════════ London Stock Exchange（IMM） ═════════════════════════
def _num(s):
    s = (s or '').strip()
    if s in ('', 'NULL', '...', '-', '—'):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


def _num0(s):
    """0 を値として残す版（配当の率 0% は『無配』という値）"""
    s = (s or '').strip()
    if s in ('', 'NULL', '...', '-', '—'):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v >= 0 else None


def _norm_heading(h):
    return re.sub(r'\s+', ' ', (h or '').upper()).rstrip('.').strip()


def lse_total_types():
    """Totaldata（整えた版）→ {OldID: (Type, Currency, ISO)}。★行の上限で切れている（ID 40407 の 1895-08 まで）"""
    pk = os.path.join(CACHE, 'nx_pre1926x_lse_types.pkl')
    if os.path.exists(pk):
        return pickle.load(open(pk, 'rb'))
    z = zipfile.ZipFile(path('lse_total'))
    out, last = {}, None
    for row in csv.DictReader(io.TextIOWrapper(z.open('Totaldata.csv'), encoding='latin-1')):
        out.setdefault(row['OldID'], (row['Type'], row['Currency'], row['ISO']))
        last = (row['NewID'], row['Year'], row['Month'])
    out['__last__'] = last
    pickle.dump(out, open(pk, 'wb'))
    return out


def lse_raw():
    """生の Railways・Banks・Misc → {'sec': {id: {'file', 'name', 'sec', 'pct', 'm': {ym: 月の組}}}, 'headings': [見出し…], 'dups': 件数}
    月の組 = (late, paid, par, amntshare, nshare, capsub, sharestock, 配当率%の平均, 配当ペンスの平均, 見出しの番号, 注記)
    数字の欄だけを float にする（'...'・'xd' 等の注記は注記に残す）。キャッシュ out/_nx_cache/nx_pre1926x_lse_raw2.pkl"""
    pk = os.path.join(CACHE, 'nx_pre1926x_lse_raw2.pkl')
    if os.path.exists(pk):
        return pickle.load(open(pk, 'rb'))
    out, heads, hidx, dups = {}, [], {}, 0
    for key, fn, file in (('lse_rail', 'Railways_new.csv', 'rail'), ('lse_bank', 'Banks_new.csv', 'bank'), ('lse_misc', 'Misc_new.csv', 'misc')):
        z = zipfile.ZipFile(path(key))
        for row in csv.DictReader(io.TextIOWrapper(z.open(fn), encoding='latin-1')):
            try:
                ym = int(row['year']) * 100 + int(row['month'])
            except (ValueError, KeyError):
                continue
            i = row['id']
            rec = out.get(i)
            if rec is None:
                rec = out[i] = {'file': file, 'name': row.get('compsecdes', ''), 'sec': row.get('secdes', ''),
                                'pct': row.get('percentfrmsecdes', ''), 'm': {}}
            h = _norm_heading(row.get('region') or row.get('industrydes') or '')
            hid = hidx.get(h)
            if hid is None:
                hid = hidx[h] = len(heads)
                heads.append(h)
            rates = [_num0(row.get(f'dvdlastfourratepercentannum{k}')) for k in (1, 2, 3, 4)]
            rates = [x for x in rates if x is not None]
            pence = [_num0(row.get(f'dvdlastfourpence{k}')) for k in (1, 2, 3, 4)]
            pence = [x for x in pence if x is not None]
            if ym in rec['m']:
                dups += 1
            rec['m'][ym] = (_num(row.get('pricemonthlate')), _num(row.get('capitalpaid')), _num(row.get('capitalpar')),
                            _num(row.get('capitalamntshare')), _num(row.get('capitalnumshare')),
                            _num(row.get('capitalsubscribed')) or _num(row.get('capitalamntcapital')),
                            _num(row.get('capitalsharestock')),
                            (sum(rates) / len(rates)) if rates else None, (sum(pence) / len(pence)) if pence else None,
                            hid, (row.get('npricemonthlate') or '') + '|' + (row.get('nlastbusiness') or ''))
    obj = {'sec': out, 'headings': heads, 'dups': dups}
    pickle.dump(obj, open(pk, 'wb'))
    return obj


# 普通株の判定（事前登録の data.lse.common_rule）: 固定の率（percentfrmsecdes）が無く、
# 証券の説明（secdes）に優先・社債・保証・借入・率・権利などの語が無く、かつ
# （secdes に ordinary・ord・common・shares がある か 会社名の行にもそれらの語が無い）もの。
# Totaldata の Type と照合（1895-08 までの 4,474 証券）: 一致 93.0%（両方普通株 1,361・両方ちがう 2,797・こちらだけ普通株 69・Totaldata だけ普通株 247）。
# 前の担当者の規則（名前と説明の両方に広い語）は一致 90.2%（'Land Mortgage' の会社や 'Do shares' の行を落としていた）
LSE_NONCOMMON = re.compile(r'\bpref|\bpf\b|\bdeb\b|deb\.|debenture|guar|\bbonds?\b|\bbds\b|per cent|%|\bloan\b|annuit|rent.?charge|\bcertif|'
                           r'\bwarrants?\b|\brights?\b|\bscrip\b|founders|deferred|oblig|\bmort|\blien\b|\bB\b', re.I)


def lse_is_common(rec):
    if (rec.get('pct') or '').strip() not in ('', 'NULL'):
        return False
    sec, nm = rec.get('sec') or '', rec.get('name') or ''
    if LSE_NONCOMMON.search(sec):
        return False
    if re.search(r'ordinary|\bord\b|common|\bshares?\b', sec, re.I):
        return True
    return not LSE_NONCOMMON.search(nm)


# 見出し → 時代をまたいで変わらない業種（一番粗い共通の分け方）。上から順に最初に当たったものを採る（順番に意味がある:
# 'STEAMSHIPS' は 'TEA' を含む・'NORTHERN IRELAND' は 'LAND' を含む）。見出しは形（2026-09-28 に全 244 種を列挙）だけを見て決めた
LSE_SECTOR_RULES = (
    ('EXCLUDE', r'CORP|CITY LOANS|PUBLIC BOARDS|COUNTY|DOM\., INDIAN|BDS\.'),   # 地方自治体・公共団体の証券（株ではない）。
                                                                              # 'RUB. BDS. (G.B. & N.I.), &C' は 'PUB. BDS.'（公共団体）の読み取り誤り
    ('SHIPPING', r'STEAMSHIP|STEMSHIP|SHIPPING'),
    ('TEA_RUBBER', r'\bTEA\b|COFFEE|RUBBER'),             # 1907〜1921 に『茶・コーヒー・ゴム』が一つの見出し
    ('BREWERIES', r'BREWER'),
    ('MINES', r'MINES'),
    ('CANALS_DOCKS', r'CANAL|DOCK|HARBOUR'),              # 1909〜 に『運河・ドック・港』が一つの見出し
    ('UTIL_GAS_WATER_ELEC', r'GAS|WATER|ELEC'),            # 1875〜1891 に『ガスと水道』が一つの見出し
    ('IRON_COAL_STEEL', r'IRON'),
    ('LAND_MORTGAGE_FIN', r'\bLAND'),
    ('TRUSTS', r'TRUST'),
    ('TELEGRAPH', r'TELEGRAPH'),
    ('TRAMWAYS', r'TRAM'),
    ('TEXTILES', r'SPINNING'),
    ('WAGONS', r'WAGON'),
    ('NITRATE', r'NITRATE'),
    ('OIL', r'\bOIL'),
    ('OTHER', r'OTHER|MISCELLANEOUS'),
)
LSE_NOT_SELECTABLE = ('OTHER', 'UNMAPPED', 'EXCLUDE')   # 『その他』は業種として選ばない（French の Other と同じ扱い）が、相手の母集団には入る


def lse_sector(file, heading):
    """(ファイル, 見出し) → 業種。鉄道のファイルは全部 RAIL（1869〜1894 は英国・植民地・外国の鉄道が一つの見出し）、
    ただし 'BOND' を含む見出し（American Railroad Sterling Bonds）は EXCLUDE。銀行のファイルは INSURANCE と BANK（銀行・割引商会・金融）"""
    if file == 'rail':
        return 'EXCLUDE' if 'BOND' in heading else 'RAIL'
    if file == 'bank':
        return 'INSURANCE' if 'INSURANCE' in heading else 'BANK'
    for name, pat in LSE_SECTOR_RULES:
        if re.search(pat, heading):
            return name
    return 'UNMAPPED'


def _lse_nshares(v):
    """月の組 → 株数（無ければ None）。capitalnumshare、無ければ 払込の対象の資本 ÷ 1株の額面（amntshare か sharestock）"""
    if v[4]:
        return v[4]
    if v[5] and v[3]:
        return v[5] / v[3]
    if v[5] and v[6]:
        return v[5] / v[6]
    return None


def lse_panel():
    """→ {'ret': {id: {ym: r}}, 'sect': {id: [[from_ym, to_ym, 業種], …]}（月 t のリターンには t−1 の見出しの業種）,
          'plag': {id: {ym: p_{t−1}}}, 'cap': {id: {ym: 時価_{t−1}}}（株数は直近12か月以内に分かった値・報告の時価加重だけ）,
          'dy': {id: {ym: 月の配当利回りの近似}}（報告だけ）, 'first'/'last': {id: ym}, 'counts'}
    リターン = 連続する2か月の月末ごろの価格（pricemonthlate）の比。次の対は作らない（欠測）:
      払込額・1株の額面（amntshare・sharestock）が両方分かっていて変わった対（払込の呼び出し・株の併合と分割＝リターンではない）、
      t−1 の業種が EXCLUDE。そのあと clean_returns"""
    obj = lse_raw()
    raw, heads = obj['sec'], obj['headings']
    cnt = collections.Counter()
    ret, sect, plag, cap, dy, first, last = {}, {}, {}, {}, {}, {}, {}
    for i, rec in raw.items():
        if not lse_is_common(rec):
            cnt['not_common'] += 1
            continue
        M = rec['m']
        ks = sorted(k for k in M if M[k][0])
        if not ks:
            continue
        first[i], last[i] = ks[0], ks[-1]
        r, sruns, pl, cp, dv = {}, [], {}, {}, {}
        ns_last = None
        for a, b in zip(ks, ks[1:]):
            va, vb = M[a], M[b]
            nsa = _lse_nshares(va)
            if nsa:
                ns_last = (a, nsa)
            if madd(a, 1) != b:
                continue
            sa = lse_sector(rec['file'], heads[va[9]])
            if sa == 'EXCLUDE':
                cnt['pairs_excluded_sector'] += 1
                continue
            cnt['pairs'] += 1
            if (va[1] and vb[1] and va[1] != vb[1]) or (va[3] and vb[3] and va[3] != vb[3]) or (va[6] and vb[6] and va[6] != vb[6]):
                cnt['drop_capital_change'] += 1
                continue
            r[b] = vb[0] / va[0] - 1
            pl[b] = va[0]
            if ns_last and madd(ns_last[0], 12) >= a:
                cp[b] = va[0] * ns_last[1]
            basis = va[1] or va[2] or va[3] or va[6]
            if va[7] is not None and basis:
                dv[b] = va[7] / 100 * basis / 12 / va[0]
            if sruns and sruns[-1][2] == sa and sruns[-1][1] == madd(b, -1):
                sruns[-1][1] = b
            else:
                sruns.append([b, b, sa])
        r = clean_returns(r, cnt)
        if not r:
            continue
        ret[i] = r
        sect[i] = sruns
        plag[i] = {k: v for k, v in pl.items() if k in r}
        cap[i] = {k: v for k, v in cp.items() if k in r}
        dy[i] = {k: v for k, v in dv.items() if k in r}
        cnt['common_with_returns'] += 1
    return {'ret': ret, 'sect': sect, 'plag': plag, 'cap': cap, 'dy': dy, 'first': first, 'last': last, 'counts': cnt}


def sector_at(sruns, ym):
    for a, z, s in sruns:
        if a <= ym <= z:
            return s
    return None


def lse_industries(panel, min_members=3):
    """LSE の業種の月次リターン = その月に t−1 の見出しでその業種に居て、月 t のリターンがある株の等分の平均。
    月 t に3社未満なら、その業種のその月は欠測（0 と読まない）。選べない業種（OTHER・UNMAPPED・EXCLUDE）は作らない。
    → ({業種: {ym: r}}, {業種: {ym: 社数}})"""
    acc = collections.defaultdict(lambda: collections.defaultdict(list))
    for i, r in panel['ret'].items():
        sr = panel['sect'][i]
        for k, v in r.items():
            s = sector_at(sr, k)
            if s and s not in LSE_NOT_SELECTABLE:
                acc[s][k].append(v)
    R, N = {}, {}
    for s, d in acc.items():
        R[s] = {k: math.fsum(v) / len(v) for k, v in d.items() if len(v) >= min_members}
        N[s] = {k: len(v) for k, v in d.items()}
    return R, N


# ═════════════════════════ 規則の台帳（事前登録と同じもの） ═════════════════════════
# kind: ind_topk（業種の勢い・上位 K を等分・H か月の重ね持ち）/ ind_multi（1・3・6・12 か月の百分位の平均）/
#       ind_trend（業種ごとの10か月線・L 倍）/ stk_mom（株の勢い・上位の分位を等分）/ stk_seas（株の季節性）/ halloween
# skip = 形成の窓の終わりと保有の月のあいだに空ける月数。gap_from_asis = 元の規則からこの角度で1か月あけたか（Working 1960 への備え）
# cost: ('two', u)＝両側の売買 Σ|Δw| × u（mw_industry）、('one', u)＝片道 ½Σ|Δw| × u（mw_momentum）、
#       ('moved', u)＝出入りした業種の重み × L × u（mw_trend）、('dL', u)＝|ΔL| × u（mw_calendar）
_A = [
    dict(key='G3_mom12_5', src=['industry:G3_mom12_5'], kind='ind_topk', L=12, skip=1, asis_skip=0, H=1, K=5, minN=10, cost=('two', 0.0005),
         what='12か月（形成の月末 f の f−12〜f−1＝1か月あけた版）の累積が最も高い5業種を等分・毎月。候補が 2K=10 未満の月は定義しない'),
    dict(key='G4_mom12_10', src=['industry:G4_mom12_10'], kind='ind_topk', L=12, skip=1, asis_skip=0, H=1, K=10, minN=20, cost=('two', 0.0005),
         what='同じく上位10業種。候補が20未満の月は定義しない'),
    dict(key='P9_multi_5', src=['industry:P9_multi_5'], kind='ind_multi', windows=[1, 3, 6, 12], skip=1, asis_skip=0, K=5, minN=10, cost=('two', 0.0005),
         what='1・3・6・12か月の累積の百分位の平均が最も高い5業種を等分・毎月（4本そろう業種だけ・1か月あけた版）'),
    dict(key='F1b_MG_6_6', src=['momentum:F1b_ind10', 'momentum:F1b_ind12', 'momentum:F1b_ind17', 'momentum:F1b_ind30', 'momentum:F1b_ind49'],
         kind='ind_topk', L=6, skip=1, asis_skip=0, H=6, frac=0.15, minN=5, cost=('one', 0.0005),
         what='Moskowitz-Grinblatt 6-6: 6か月の累積の上位 K=max(2, 四捨五入(0.15N)) 業種を等分、6か月の重ね持ち（1か月あけた版）'),
    dict(key='F3g_12-1_H1_K15', src=['momentum:F3g_ind17_12-1_H1_K15'], kind='ind_topk', L=11, skip=1, asis_skip=1, H=1, frac=0.15, minN=5,
         cost=('one', 0.0005), what='12-1（f−11〜f−1・元から直近1か月を飛ばす）の上位15%・毎月'),
    dict(key='F3g_12-1_H1_K30', src=['momentum:F3g_ind30_12-1_H1_K30'], kind='ind_topk', L=11, skip=1, asis_skip=1, H=1, frac=0.30, minN=5,
         cost=('one', 0.0005), what='12-1 の上位30%・毎月'),
    dict(key='F3g_9-0_H1_K30', src=['momentum:F3g_ind17_9-0_H1_K30', 'momentum:F3g_ind30_9-0_H1_K30'], kind='ind_topk', L=9, skip=1, asis_skip=0,
         H=1, frac=0.30, minN=5, cost=('one', 0.0005), what='9か月（1か月あけた版＝f−9〜f−1）の上位30%・毎月'),
    dict(key='S3_FABER_L2', src=['trend:S3_US_IND49_FABER_L2'], kind='ind_trend', sma=10, Lev=2.0, skip=1, asis_skip=0, cost=('moved', 0.001),
         spread=0.005, fee=0.009, timing=True,
         what='業種ごとに総リターン指数の月末値＞直近10個の平均なら持ち、下なら現金。業種は等分（時価が無い）・2倍（1か月あけた版＝月 t−1 末の信号で月 t+1）'),
    dict(key='S3_FABER_L3', src=['trend:S3_US_IND49_FABER_L3'], kind='ind_trend', sma=10, Lev=3.0, skip=1, asis_skip=0, cost=('moved', 0.001),
         spread=0.005, fee=0.009, timing=True, what='同じく3倍'),
]
_STK = [
    dict(key='F1a1_top_decile', src=['momentum:F1a1_us_top_decile'], kind='stk_mom', L=11, skip=1, asis_skip=1, frac=0.10, min_port=10,
         what='12-2（保有の月の t−12〜t−2＝形成の月末 f の f−11〜f−1）の上位10%を等分・毎月（元は時価加重。時価が無いので等分）'),
    dict(key='ret_12_1_tercile', src=['intl:F2a:ret_12_1'], kind='stk_mom', L=11, skip=1, asis_skip=1, frac=1 / 3, min_port=10,
         what='JKP の ret_12_1（f−11〜f−1）の上位3分の1を等分・毎月（元は時価加重の三分位）'),
    dict(key='seas_6_10an_tercile', src=['momentum:F14_usa_seas_6_10an'], kind='stk_seas', years=[6, 7, 8, 9, 10], frac=1 / 3, min_port=10,
         what='保有の月と同じ暦月の 6〜10 年前のリターンの平均（5年すべてそろう株だけ）の上位3分の1を等分・毎月（元は時価加重の三分位）'),
]
RULES = []
for r in _A:                    # A: Cowles の業種（米国 1871〜1926-06・総リターン）
    RULES.append(dict(r, id='A_' + r['key'], fam='A', data='cowles_ind',
                      bench=('cowles_ew_ind' if r['kind'] == 'ind_trend' else 'cowles_mkt'), rf='us_cash'))
# 株の規則の片道の単価: 元の規則の単価（F1a1 0.20%・ret_12_1 は mw_intl の先進国 0.30%／米国の参考 0.10%・seas 0.10%）を、
# 英国では mw_intl の米国外の先進国 0.30% を下限にする（eknzbh の F15 も米国外は 0.30%）。米国（NYSE）は元の米国の単価 0.10%
for r in _STK:                  # B: LSE の株（英国 1869〜1907・1915〜1929・価格だけ）
    RULES.append(dict(r, id='B_' + r['key'], fam='B', data='lse_stk', bench='lse_ew', weight='ew', cost=('one', 0.003)))
for r in _STK[1:]:              # C: Old NYSE の株（米国 1815〜1925・価格だけ）。十分位は銘柄が足りず作れない（shape）
    RULES.append(dict(r, id='C_' + r['key'], fam='C', data='nyse_stk', bench='nyse_ew', weight='ew', cost=('one', 0.001)))
for r in _A:                    # D: LSE の業種（英国・等分の業種指数）
    RULES.append(dict(r, id='D_' + r['key'], fam='D', data='lse_ind',
                      bench=('lse_ew_ind' if r['kind'] == 'ind_trend' else 'lse_ew'), rf='uk_cash'))
RULES.append(dict(id='H_HAL_OV15_UK', key='HAL_OV15', fam='H', data='uk_index', kind='halloween', src=['calendar:X06_HAL_OV15_WORLD', 'calendar:Y03_HAL_OV15_WXUS'],
                  winter=[11, 12, 1, 2, 3, 4], Lev=1.5, spread=0.005, cost=('dL', 0.001), timing=True, bench='uk_index', rf='uk_hal',
                  period=list(UK_HAL_MAIN), what='英国の株価指数（イングランド銀行 M13 の列 23・価格だけ）に 11〜4月は1.5倍・5〜10月は1倍。借入 0.5×(短期金利+0.5%)'))
# 形で作れないと決まったもの（測る前に族から外す。out/nx_pre1926x_prereg.json の not_testable_by_shape と同じ）
NOT_TESTABLE_BY_SHAPE = {
    'D_G4_mom12_10': 'LSE の選べる業種（3社以上）は どの月も最大16（2K=20 に届く月が無い＝定義できる月 0）',
    'C_seas_6_10an_tercile': 'Old NYSE で 6〜10 年前の同じ暦月がそろう株が少なく、上位3分の1が10社以上になる月は 76（1898-07〜1922-04・MIN_MONTHS=180 未満）',
}
FAMILIES = {f: [r['id'] for r in RULES if r['fam'] == f and r['id'] not in NOT_TESTABLE_BY_SHAPE] for f in 'ABCDH'}
MIN_MONTHS = 180            # 定義できる月がこれ未満の単位は『検定不能（短い）』＝格付けしない


def rules_sha():
    return hashlib.sha256(json.dumps(RULES, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


# ═════════════════════════ 格付け（criteria_independent_era） ═════════════════════════
def grade_era(full_net, h1_net, h2_net, holm_p_one, drop_top_net=None, sharpe_halves=None, timing=False, drop_top_applies=True, months=None):
    """事前登録の criteria_independent_era をそのまま当てる。引数は nx_common.excess_stats の戻り値（費用後の s − b）。
    欠けた入力は不合格側に倒す（空欄を合格にしない）。
      E1 費用後の算術の超過 > 0 かつ 幾何の年率差 > 0（全期間）
      E2 費用後の NW t（ラグ12）≥ 2.0
      E3 前半・後半（定義できる月を数で二分）の両方で費用後の幾何の年率差 > 0
      E4 族の中の Holm 補正後の片側 p < 0.05
      E5 （タイミング・借入の型だけ）前半・後半の両方で費用後のシャープ（現金を引いた）が相手を上回る
      E7 最大寄与の構成要素（業種・株）を母集団から抜いて作り直しても費用後の幾何の年率差 > 0（ハロウィーンは N/A）
    S = E1∧E2∧E3∧E4∧E7∧(E5)／A = E1∧E2∧E3∧(E5)／B = E1∧(E5)／C = それ以外。月数が MIN_MONTHS 未満は 'NA_short'"""
    if months is not None and months < MIN_MONTHS:
        return 'NA_short', {}
    c = {}
    c['E1_sign'] = bool(full_net and full_net['ex_ann'] > 0 and full_net['cagr_diff'] > 0)
    c['E2_t'] = bool(full_net and (full_net['t'] or 0) >= 2.0)
    c['E3_halves'] = bool(h1_net and h2_net and h1_net['cagr_diff'] > 0 and h2_net['cagr_diff'] > 0)
    c['E4_holm'] = bool(holm_p_one is not None and holm_p_one < 0.05)
    if timing:
        sp = sharpe_halves or {}
        c['E5_sharpe'] = bool(sp.get('h1') and sp.get('h2') and None not in sp['h1'] + sp['h2']
                              and sp['h1'][0] > sp['h1'][1] and sp['h2'][0] > sp['h2'][1])
    else:
        c['E5_sharpe'] = None
    c['E7_drop_top'] = bool(drop_top_net and drop_top_net['cagr_diff'] > 0) if drop_top_applies else None
    ok = lambda k: c[k] is True
    na_or = lambda k: c[k] is None or c[k] is True
    if ok('E1_sign') and ok('E2_t') and ok('E3_halves') and ok('E4_holm') and na_or('E7_drop_top') and na_or('E5_sharpe'):
        g = 'S'
    elif ok('E1_sign') and ok('E2_t') and ok('E3_halves') and na_or('E5_sharpe'):
        g = 'A'
    elif ok('E1_sign') and na_or('E5_sharpe'):
        g = 'B'
    else:
        g = 'C'
    return g, c


def rule_verdict(unit_grades):
    """同じ元の規則を当てた単位たち（例: Cowles の業種と LSE の業種）の格付けをまとめる（事前登録の rule_level_verdict）"""
    g = [x for x in unit_grades if x in ('S', 'A', 'B', 'C')]
    if not g:
        return '検定不能'
    if all(x in 'SAB' for x in g) and 'S' in g:
        return '再現（強）'
    if all(x in 'SAB' for x in g) and any(x in 'SA' for x in g):
        return '再現'
    if all(x in 'SAB' for x in g):
        return '向きだけ'
    if any(x in 'SAB' for x in g):
        return '割れた'
    return '再現せず'


# ═════════════════════════ ポートフォリオの組み立て（事前登録の定義・合成データでだけ点検済み） ═════════════════════════
def _cost_of(turn_two_sided, spec):
    kind, u = spec
    if kind == 'two':
        return turn_two_sided * u
    if kind == 'one':
        return 0.5 * turn_two_sided * u
    raise ValueError(spec)


def _hold(months, coh, H, R, cost):
    """組 coh[f]（形成の月の番号 → 業種/株の一覧）を f+1…f+H に持つ。各月の重み = (1/H)Σ組(1/その組でその月にリターンがある数)。
    H 個の組が全部そろった月だけ。費用 = 目標の重みと前月の重みが値動きで流れた後の差から（最初の月・途切れた後の月は 0）。
    → (s 総リターン, s 費用後, 回転（両側）, 重み)"""
    s, net, turn, W = {}, {}, {}, {}
    prev_after = None
    for j in range(1, len(months)):
        fs = list(range(j - H, j))
        if any(f not in coh for f in fs):
            prev_after = None
            continue
        m = months[j]
        w = collections.defaultdict(float)
        ok = True
        for f in fs:
            mem = [n for n in coh[f] if m in R.get(n, {})]
            if not mem:
                ok = False
                break
            for n in mem:
                w[n] += 1.0 / H / len(mem)
        if not ok:
            prev_after = None
            continue
        rp = math.fsum(w[n] * R[n][m] for n in w)
        to = math.fsum(abs(w.get(n, 0.0) - prev_after.get(n, 0.0)) for n in set(w) | set(prev_after)) if prev_after is not None else 0.0
        s[m] = rp
        turn[m] = to
        net[m] = rp - _cost_of(to, cost)
        W[m] = dict(w)
        prev_after = {n: w[n] * (1 + R[n][m]) / (1 + rp) for n in w}
    return s, net, turn, W


def build_ind_topk(R, months, L, skip, H, cost, K=None, frac=None, minN=5, exclude=()):
    """業種の勢い（mw_momentum_verify.ind_momentum と同じ作り方＋候補の下限）。
    months = 連続した期間の並び（途中に切れ目の無い1つの区間。切れ目のあるデータは区間ごとに呼ぶ）。
    月の番号 f の末に、[f−skip−L+1, f−skip] の対数リターンの和で並べ（窓に欠けがある業種は入れない）、上位 K を組にする。
    K = 固定 か max(2, 四捨五入(frac×N))。候補 N < minN の月は組を作らない。同点は名前の順"""
    names = [n for n in R if n not in exclude]
    lr = {n: [math.log1p(R[n][m]) if m in R[n] else None for m in months] for n in names}
    coh, info = {}, {}
    for f in range(len(months)):
        lo, hi = f - skip - L + 1, f - skip
        if lo < 0:
            continue
        sc = []
        for n in names:
            seg = lr[n][lo:hi + 1]
            if any(v is None for v in seg):
                continue
            sc.append((-math.fsum(seg), str(n), n))
        N = len(sc)
        k = K if K is not None else max(2, round_half_up(frac * N))
        if N < minN or N < k:
            continue
        sc.sort()
        coh[f] = [n for _, _, n in sc[:k]]
        info[months[f]] = (N, k)
    s, net, turn, W = _hold(months, coh, H, R, cost)
    return {'s': s, 'net': net, 'turn': turn, 'w': W, 'NK': info}


def _pct_ranks(vals):
    """{名前: 値} → {名前: 百分位 0〜1}（小さい順・同点は平均の順位）"""
    items = sorted(vals.items(), key=lambda x: x[1])
    n = len(items)
    out, i = {}, 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        r = (i + j) / 2
        for k in range(i, j + 1):
            out[items[k][0]] = r / (n - 1) if n > 1 else 0.5
        i = j + 1
    return out


def build_ind_multi(R, months, windows, skip, K, minN, cost, exclude=()):
    """1・3・6・12 か月（windows）の累積の百分位の平均が最も高い K 業種を等分・毎月（全部の窓がそろう業種だけ・同点は名前の順）"""
    names = [n for n in R if n not in exclude]
    lr = {n: [math.log1p(R[n][m]) if m in R[n] else None for m in months] for n in names}
    Lmax = max(windows)
    coh, info = {}, {}
    for f in range(len(months)):
        hi = f - skip
        if hi - Lmax + 1 < 0:
            continue
        ok = [n for n in names if all(v is not None for v in lr[n][hi - Lmax + 1:hi + 1])]
        if len(ok) < minN or len(ok) < K:
            continue
        avg = collections.defaultdict(float)
        for L in windows:
            pr = _pct_ranks({n: math.fsum(lr[n][hi - L + 1:hi + 1]) for n in ok})
            for n in ok:
                avg[n] += pr[n] / len(windows)
        coh[f] = [n for _, _, n in sorted((-avg[n], str(n), n) for n in ok)[:K]]
        info[months[f]] = (len(ok), K)
    s, net, turn, W = _hold(months, coh, 1, R, cost)
    return {'s': s, 'net': net, 'turn': turn, 'w': W, 'NK': info}


def build_ind_trend(R, months, rf, sma, Lev, skip, cost, spread, fee, exclude=()):
    """業種ごとの10か月線（mw_trend 第5族 S3 の業種を等分にした版＝ mw_trend の C5 の作り方）。
    業種 i の総リターン指数 I_i（途切れずに続くリターンだけでつなぐ・途切れたら新しい業種として数え直す）。
    月の番号 g の末の信号 up_i(g) = I_i(g) > 直近 sma 個の月末値の平均（sma 個そろわない最初の月々は『上』）。
    保有の月 j の母集団 U_j = 月 j−1 の末に指数があり月 j のリターンがある業種、重み w_i = 1/|U_j|。
    信号は g = j−1−skip の末のもの（skip=1 が1か月あけた版）。E = Lev×Σ_{上} w_i、
    s_j = Lev×Σ_{上} w_i r_i + (1−E)×rf_j − [E>1: ((E−1)×spread + fee)/12] − Σ_{状態が変わった業種} w_i×Lev×u。
    相手 b_j = U_j の等分の平均。→ {'s','net','b','E','w'}"""
    names = [n for n in R if n not in exclude]
    idx, up = {}, {}
    for n in names:
        I, u, hist, lev = {}, {}, [], None
        for g, m in enumerate(months):
            if m not in R[n]:
                hist, lev = [], None            # 途切れた＝次に現れたら新しい業種として数え直す
                continue
            if lev is None:
                lev, hist = 1.0, [1.0]          # 始まりの月の前の月末の水準を 1 とする（これも月末値の1つ）
            lev *= 1 + R[n][m]
            hist.append(lev)
            I[g] = lev
            h = hist[-sma:]
            u[g] = True if len(h) < sma else lev > math.fsum(h) / sma
        idx[n], up[n] = I, u
    s, net, b, E, W = {}, {}, {}, {}, {}
    prev_state = None
    for j in range(1, len(months)):
        m = months[j]
        g = j - 1 - skip
        if g < 0:
            continue
        U = [n for n in names if (j - 1) in idx[n] and m in R[n] and g in up[n]]
        if not U or m not in rf:          # 現金の金利が無い月は作らない（0 と読まない）
            prev_state = None
            continue
        w = 1.0 / len(U)
        ups = [n for n in U if up[n][g]]
        e = Lev * w * len(ups)
        rp = Lev * math.fsum(w * R[n][m] for n in ups) + (1 - e) * rf[m]
        if e > 1:
            rp -= ((e - 1) * spread + fee) / 12
        st = {n: up[n][g] for n in U}
        moved = 0.0 if prev_state is None else math.fsum(w for n in U if n in prev_state and prev_state[n] != st[n])
        s[m] = rp
        net[m] = rp - moved * Lev * cost[1]
        b[m] = math.fsum(R[n][m] for n in U) / len(U)
        E[m] = e
        W[m] = {n: (Lev * w if st[n] else 0.0) for n in U}
        prev_state = st
    return {'s': s, 'net': net, 'b': b, 'E': E, 'w': W}


def build_stk_mom(R, months, L, skip, frac, min_port, cost, weight='ew', cap=None, exclude=()):
    """株の勢い。月の番号 f の末に、[f−L, f] の月すべてにリターンがある株（＝月 f にも取引がある）を候補にし、
    [f−skip−L+1, f−skip] の対数リターンの和の上位 n = 四捨五入(frac×N) を組にする（同点は名前の順）。n < min_port の月は作らない。
    f+1 に持つ（重みは等分、weight='vw' なら cap[株][f+1]＝月 f の時価で）。月 f+1 にリターンが無い株は残りで割り直す"""
    names = [n for n in R if n not in exclude]
    coh = {}
    for f in range(len(months)):
        lo, hi = f - skip - L + 1, f - skip
        if lo < 0 or hi < lo:
            continue
        need = months[min(lo, f):f + 1]
        sc = []
        for n in names:
            d = R[n]
            if any(m not in d for m in need):
                continue
            sc.append((-math.fsum(math.log1p(d[m]) for m in months[lo:hi + 1]), str(n), n))
        k = round_half_up(frac * len(sc))
        if k < min_port:
            continue
        sc.sort()
        coh[f] = [n for _, _, n in sc[:k]]
    return _hold_stk(months, coh, R, cost, weight, cap)


def build_stk_seas(R, months, years, frac, min_port, cost, weight='ew', cap=None, exclude=()):
    """株の季節性（Heston-Sadka・JKP seas_6_10an）。月の番号 f の末に、保有の月 f+1 と同じ暦月の years 年前のリターン
    r(months[f+1] − 12y) がすべてあり、月 f にもリターンがある株を候補にし、その平均の上位 n = 四捨五入(frac×N) を組にする"""
    names = [n for n in R if n not in exclude]
    coh = {}
    for f in range(len(months) - 1):
        nxt = months[f + 1]
        lags = [madd(nxt, -12 * y) for y in years]
        if lags[-1] < months[0]:
            continue
        sc = []
        for n in names:
            d = R[n]
            if months[f] not in d or any(m not in d for m in lags):
                continue
            sc.append((-math.fsum(d[m] for m in lags) / len(lags), str(n), n))
        k = round_half_up(frac * len(sc))
        if k < min_port:
            continue
        sc.sort()
        coh[f] = [n for _, _, n in sc[:k]]
    return _hold_stk(months, coh, R, cost, weight, cap)


def _hold_stk(months, coh, R, cost, weight, cap):
    s, net, turn, W, NP = {}, {}, {}, {}, {}
    prev_after = None
    for j in range(1, len(months)):
        f = j - 1
        if f not in coh:
            prev_after = None
            continue
        m = months[j]
        mem = [n for n in coh[f] if m in R[n]]
        if weight == 'vw':
            mem = [n for n in mem if cap and m in cap.get(n, {})]
            tot = math.fsum(cap[n][m] for n in mem)
            w = {n: cap[n][m] / tot for n in mem} if tot > 0 else {}
        else:
            w = {n: 1.0 / len(mem) for n in mem} if mem else {}
        if not w:
            prev_after = None
            continue
        rp = math.fsum(w[n] * R[n][m] for n in w)
        to = math.fsum(abs(w.get(n, 0.0) - prev_after.get(n, 0.0)) for n in set(w) | set(prev_after)) if prev_after is not None else 0.0
        s[m] = rp
        turn[m] = to
        net[m] = rp - _cost_of(to, cost)
        W[m] = w
        NP[m] = len(w)
        prev_after = {n: w[n] * (1 + R[n][m]) / (1 + rp) for n in w}
    return {'s': s, 'net': net, 'turn': turn, 'w': W, 'n': NP}


def build_ew_universe(R, months, exclude=()):
    """相手: その月にリターンがある全部の等分（価格だけの単位は価格だけ）"""
    out = {}
    for m in months:
        v = [R[n][m] for n in R if n not in exclude and m in R[n]]
        if v:
            out[m] = math.fsum(v) / len(v)
    return out


def build_halloween(m, rate, winter, Lev, spread, cost, a=None, z=None):
    """ハロウィーン（mw_calendar P2_HAL_OV15 の月次版）: 暦の月が winter なら Lev 倍、それ以外は1倍（株を常に持つ）。
    s_t = L_t×m_t − (L_t−1)×(rate_t + spread/12) − |L_t − L_{t−1}|×u。相手 = m（買って持つだけ）"""
    s, net = {}, {}
    prevL = None
    for k in sorted(m):
        if (a and k < a) or (z and k > z) or k not in rate:
            prevL = None
            continue
        L = Lev if k % 100 in winter else 1.0
        r = L * m[k] - (L - 1) * (rate[k] + spread / 12)
        s[k] = r
        net[k] = r - (abs(L - prevL) * cost[1] if prevL is not None else 0.0)
        prevL = L
    return {'s': s, 'net': net}


def contributions(w, R, b):
    """構成要素ごとの寄与 Σ_t w_{i,t}(r_{i,t} − b_t)（E7 の『最大寄与の1つ』を決めるため）"""
    out = collections.defaultdict(float)
    for m, wd in w.items():
        if m not in b:
            continue
        for n, x in wd.items():
            out[n] += x * (R[n][m] - b[m])
    return dict(out)


def contributions_trend(w, R, rf, b_universe_n):
    """ind_trend の E7 用の寄与 Σ_t (W_{i,t} − 1/N_t)(r_{i,t} − rf_t)（W = Lev×w×上）＝相手（等分）からのずれの寄与"""
    out = collections.defaultdict(float)
    for m, wd in w.items():
        n = len(wd)
        for i, x in wd.items():
            out[i] += (x - 1.0 / n) * (R[i][m] - rf[m])
    return dict(out)


def halves(keys):
    ks = sorted(keys)
    h = len(ks) // 2
    return (ks[0], ks[h - 1]), (ks[h], ks[-1])


# ═════════════════════════ 抽出（測る道具が読む・sha で凍結） ═════════════════════════
def _sd(d):
    return {str(k): v for k, v in sorted(d.items())}


def build_extract():
    P, names = cowles_P()
    Cs, _ = cowles_C()
    R, st, fixes = cowles_returns(P, Cs)
    U = cowles_industry_universe(R)
    lse = lse_panel()
    LI, LN = lse_industries(lse)
    ny = nyse_panel()
    uk, udesc = uk_share_prices()
    rt, _ = uk_rates()
    data = {
        'cowles': {'months': cowles_months(), 'ind': {str(n): _sd(s) for n, s in U.items()},
                   'names': {str(n): names[n] for n in U}, 'mkt': _sd(R[1]), 'mkt_price': _sd(cowles_price_returns(P, 1)),
                   'build_counts': st, 'fixes': fixes},
        'lse': {'segments': [list(x) for x in LSE_SEGMENTS], 'ret': {i: _sd(r) for i, r in lse['ret'].items()},
                'sect': lse['sect'], 'plag': {i: _sd(r) for i, r in lse['plag'].items()},
                'cap': {i: _sd(r) for i, r in lse['cap'].items() if r}, 'dy': {i: _sd(r) for i, r in lse['dy'].items() if r},
                'first': lse['first'], 'last': lse['last'], 'ind': {s: _sd(d) for s, d in LI.items()},
                'ind_n': {s: _sd(d) for s, d in LN.items()}, 'counts': dict(lse['counts'])},
        'nyse': {'segments': [list(x) for x in NYSE_SEGMENTS], 'ret': {i: _sd(r) for i, r in ny['ret'].items()},
                 'filled': ny['filled'], 'first': ny['first'], 'last': ny['last'], 'counts': dict(ny['counts']),
                 'pw_index_2020': _sd(nyse_pw_index()['2020'])},
        'uk_index': {'ret': _sd(uk_index_returns(uk)), 'level': _sd(uk[23])},
        'rates': {'us_cash': _sd(nber_cp()), 'uk_cash': _sd(uk_cash(rt)), 'uk_hal': _sd(uk_hal_rate(rt))},
    }
    blob = json.dumps(data, sort_keys=True, separators=(',', ':')).encode()
    out = {'data': data, 'extract_sha256': hashlib.sha256(blob).hexdigest(), 'rules_sha256': rules_sha(),
           'sources_sha256_16': {k: sha(k) for k in ('cowles_P', 'cowles_C', 'nyse', 'nyse_pw', 'boe', 'lse_rail', 'lse_bank', 'lse_misc', 'lse_total', 'nber_cp')}}
    tmp = EXTRACT + '.tmp'
    json.dump(out, open(tmp, 'w'), separators=(',', ':'))
    os.replace(tmp, EXTRACT)
    return out


def load_extract():
    """測る道具の入口: 抽出を読み、sha を計算し直して返す（事前登録の値と比べるのは呼ぶ側）"""
    o = json.load(open(EXTRACT))
    blob = json.dumps(o['data'], sort_keys=True, separators=(',', ':')).encode()
    o['extract_sha256_recomputed'] = hashlib.sha256(blob).hexdigest()
    o['rules_sha256_now'] = rules_sha()
    return o


# ═════════════════════════ 形の報告（成績は出さない） ═════════════════════════
def _definable_ind(avail, months, L, skip, minN, K=None, frac=None, H=1):
    """業種の規則が『組を作れる月』の数と最初と最後（リターンの有無だけで数える＝値は使わない）"""
    cnt, first, last, run = 0, None, None, 0
    ok_f = set()
    for f in range(len(months)):
        lo, hi = f - skip - L + 1, f - skip
        if lo < 0:
            continue
        N = sum(1 for a in avail.values() if all(months[x] in a for x in range(lo, hi + 1)))
        k = K if K is not None else max(2, round_half_up(frac * N))
        if N >= minN and N >= k:
            ok_f.add(f)
    for j in range(1, len(months)):
        if all(f in ok_f for f in range(j - H, j)):
            cnt += 1
            first = first or months[j]
            last = months[j]
    return {'months': cnt, 'first': first, 'last': last}


def _definable_stk(avail, months, L, skip, frac, min_port):
    cnt, first, last = 0, None, None
    for f in range(len(months) - 1):
        lo = f - skip - L + 1
        if lo < 0:
            continue
        need = months[lo:f + 1]
        N = sum(1 for a in avail.values() if all(m in a for m in need))
        if round_half_up(frac * N) >= min_port:
            cnt += 1
            first = first or months[f + 1]
            last = months[f + 1]
    return {'months': cnt, 'first': first, 'last': last}


def _definable_seas(avail, months, years, frac, min_port):
    cnt, first, last = 0, None, None
    for f in range(len(months) - 1):
        nxt = months[f + 1]
        lags = [madd(nxt, -12 * y) for y in years]
        N = sum(1 for a in avail.values() if months[f] in a and all(m in a for m in lags))
        if round_half_up(frac * N) >= min_port:
            cnt += 1
            first = first or nxt
            last = nxt
    return {'months': cnt, 'first': first, 'last': last}


def shape_report():
    rep = {}
    P, names = cowles_P()
    Cs, titles = cowles_C()
    R, st, fixes = cowles_returns(P, Cs)
    U = cowles_industry_universe(R)
    cm = cowles_months()
    rep['cowles'] = {
        'P_groups': len(P), 'C_blocks': len(Cs), 'C_blocks_with_data': sum(1 for n in Cs if Cs[n]),
        'names': {n: names[n] for n in sorted(U)},
        'return_build_counts_to_192606': st, 'text_number_cells_read': dict(TEXT_NUM_CELLS), 'fixes_n': len(fixes),
        'industries_with_return_june': {y: sum(1 for s in U.values() if y * 100 + 6 in s) for y in range(1872, 1927, 2)},
        'mkt_C1_months': sum(1 for k in R[1] if k <= COWLES_END),
    }
    avail = {n: set(s) for n, s in U.items()}
    dfn = {}
    for r in RULES:
        if r['fam'] == 'A':
            if r['kind'] == 'ind_topk':
                dfn[r['id']] = _definable_ind(avail, cm, r['L'], r['skip'], r['minN'], r.get('K'), r.get('frac'), r['H'])
            elif r['kind'] == 'ind_multi':
                dfn[r['id']] = _definable_ind(avail, cm, max(r['windows']), r['skip'], r['minN'], r['K'], None, 1)
            else:
                dfn[r['id']] = {'months': sum(1 for k in cm if any(k in a for a in avail.values())) - 2, 'first': None, 'last': None}
    # LSE
    obj = lse_raw()
    lse = lse_panel()
    LI, LN = lse_industries(lse)
    heads = obj['headings']
    hs = collections.Counter()
    for rec in obj['sec'].values():
        for v in rec['m'].values():
            hs[(rec['file'], v[9])] += 1
    unm = sorted({heads[h] for (f, h) in hs if lse_sector(f, heads[h]) == 'UNMAPPED'})
    per = {}
    for y in (1870, 1875, 1880, 1885, 1890, 1895, 1900, 1905, 1907, 1916, 1920, 1925, 1929):
        k = y * 100 + 6
        per[y] = {'stocks_with_return': sum(1 for r in lse['ret'].values() if k in r),
                  'industries_ge3': sorted(s for s, d in LI.items() if k in d),
                  'members': {s: LN[s].get(k, 0) for s in sorted(LN)}}
    rep['lse'] = {'raw_securities': len(obj['sec']), 'duplicate_rows': obj['dups'], 'counts': dict(lse['counts']),
                  'unmapped_headings': unm, 'june': per,
                  'industries_ever': sorted(LI), 'max_industries_in_a_month': max(sum(1 for d in LI.values() if k in d)
                                                                                   for k in month_range(186902, 192912)),
                  'stocks_with_cap_june': {y: sum(1 for c in lse['cap'].values() if y * 100 + 6 in c) for y in (1870, 1880, 1887, 1890, 1900, 1907, 1920)},
                  'stocks_with_dy_june': {y: sum(1 for c in lse['dy'].values() if y * 100 + 6 in c) for y in (1870, 1880, 1890, 1900, 1907, 1920)}}
    lavail = {n: set(s) for n, s in lse['ret'].items()}
    liavail = {n: set(s) for n, s in LI.items()}
    for seg in LSE_SEGMENTS:
        ms = month_range(*seg)
        for r in RULES:
            if r['fam'] == 'D':
                if r['kind'] == 'ind_topk':
                    d = _definable_ind(liavail, ms, r['L'], r['skip'], r['minN'], r.get('K'), r.get('frac'), r['H'])
                elif r['kind'] == 'ind_multi':
                    d = _definable_ind(liavail, ms, max(r['windows']), r['skip'], r['minN'], r['K'], None, 1)
                else:
                    d = {'months': sum(1 for k in ms if any(k in a for a in liavail.values())), 'first': None, 'last': None}
            elif r['fam'] == 'B':
                if r['kind'] == 'stk_mom':
                    d = _definable_stk(lavail, ms, r['L'], r['skip'], r['frac'], r['min_port'])
                else:
                    d = _definable_seas(lavail, ms, r['years'], r['frac'], r['min_port'])
            else:
                continue
            dfn.setdefault(r['id'], {})[f'{seg[0]}-{seg[1]}'] = d
    # NYSE
    ny = nyse_panel()
    nms = month_range(*NYSE_SEGMENTS[0])
    navail = {n: set(s) for n, s in ny['ret'].items()}
    rep['nyse'] = {'counts': dict(ny['counts']),
                   'stocks_with_return_june': {y: sum(1 for r in ny['ret'].values() if y * 100 + 6 in r) for y in range(1815, 1926, 5)}}
    for r in RULES:
        if r['fam'] == 'C':
            if r['kind'] == 'stk_mom':
                dfn[r['id']] = _definable_stk(navail, nms, r['L'], r['skip'], r['frac'], r['min_port'])
            else:
                dfn[r['id']] = _definable_seas(navail, nms, r['years'], r['frac'], r['min_port'])
    dfn['C_F1a1_top_decile(参考・台帳に無い)'] = _definable_stk(navail, nms, 11, 1, 0.10, 10)
    rep['definable_months'] = dfn
    # UK index / rates
    uk, desc = uk_share_prices()
    rt, rdesc = uk_rates()
    ur = uk_index_returns(uk)
    hr = uk_hal_rate(rt)
    rep['uk'] = {'index_returns_first_last': (min(ur), max(ur)), 'index_returns_in_main': sum(1 for k in ur if UK_HAL_MAIN[0] <= k <= UK_HAL_MAIN[1]),
                 'index_missing_in_main': [k for k in month_range(*UK_HAL_MAIN) if k not in ur][:40],
                 'hal_rate_first_last': (min(hr), max(hr)), 'hal_rate_missing_in_main': sum(1 for k in month_range(*UK_HAL_MAIN) if k not in hr),
                 'uk_cash_first_last': (min(uk_cash(rt)), max(uk_cash(rt)))}
    cp = nber_cp()
    rep['us_cash'] = {'first_last': (min(cp), max(cp)), 'n': len(cp)}
    rep['rules_sha256'] = rules_sha()
    rep['families'] = FAMILIES
    rep['sources_sha256_16'] = {k: sha(k) for k in ('cowles_P', 'cowles_C', 'nyse', 'nyse_pw', 'boe', 'lse_rail', 'lse_bank', 'lse_misc', 'lse_total', 'nber_cp')}
    return rep


# ═════════════════════════ 合成データの点検（実データは読まない） ═════════════════════════
def selftest():
    rnd = random.Random(7)
    months = month_range(190001, 192012)
    R = {f'i{k}': {m: rnd.gauss(0.005, 0.05) for m in months} for k in range(12)}
    del R['i3'][months[40]]
    res = []
    # (1) 先読みなし: 月 j 以降のリターンを書き換えても、月 j までの戦略のリターンは変わらない
    for fn in (lambda Rx: build_ind_topk(Rx, months, 12, 1, 1, ('two', 0.0005), K=3, minN=6),
               lambda Rx: build_ind_topk(Rx, months, 6, 1, 6, ('one', 0.0005), frac=0.15, minN=5),
               lambda Rx: build_ind_multi(Rx, months, [1, 3, 6, 12], 1, 3, 6, ('two', 0.0005)),
               lambda Rx: build_stk_mom(Rx, months, 11, 1, 1 / 3, 3, ('one', 0.003)),
               lambda Rx: build_stk_seas(Rx, months, [6, 7, 8, 9, 10], 1 / 3, 3, ('one', 0.003))):
        a = fn(R)
        cut = months[150]
        R2 = {n: {m: (v if m <= cut else rnd.gauss(0, 0.2)) for m, v in d.items()} for n, d in R.items()}
        b = fn(R2)
        same = all(abs(a['net'][m] - b['net'][m]) < 1e-15 for m in a['net'] if m <= cut)
        res.append(('no_lookahead', same))
    rf = {m: 0.003 for m in months}
    a = build_ind_trend(R, months, rf, 10, 2.0, 1, ('moved', 0.001), 0.005, 0.009)
    R2 = {n: {m: (v if m <= months[150] else rnd.gauss(0, 0.2)) for m, v in d.items()} for n, d in R.items()}
    b = build_ind_trend(R2, months, rf, 10, 2.0, 1, ('moved', 0.001), 0.005, 0.009)
    res.append(('no_lookahead_trend', all(abs(a['net'][m] - b['net'][m]) < 1e-15 for m in a['net'] if m <= months[150])))
    # (2) 1か月あけた版は、直前の月のリターンを書き換えても組が変わらない（skip=1 の窓が f−1 で終わる）
    x = build_ind_topk(R, months, 12, 1, 1, ('two', 0.0005), K=3, minN=6)
    j = 100
    R3 = {n: dict(d) for n, d in R.items()}
    for n in R3:
        if months[j - 1] in R3[n]:
            R3[n][months[j - 1]] += rnd.gauss(0, 0.5)
    y = build_ind_topk(R3, months, 12, 1, 1, ('two', 0.0005), K=3, minN=6)
    res.append(('gap_ignores_last_month', set(x['w'][months[j]]) == set(y['w'][months[j]])))
    # (3) 植えた勢い（前の12か月に上げた業種が翌月も上がる）を拾う＝向きの点検
    Rp = {f'i{k}': {} for k in range(12)}
    drift = {f'i{k}': rnd.gauss(0, 0.01) for k in range(12)}
    for m in months:
        if m % 100 == 1:
            drift = {n: 0.8 * drift[n] + rnd.gauss(0, 0.01) for n in drift}
        for n in Rp:
            Rp[n][m] = drift[n] + rnd.gauss(0.005, 0.03)
    p = build_ind_topk(Rp, months, 12, 1, 1, ('two', 0.0005), K=3, minN=6)
    bm = build_ew_universe(Rp, months)
    ex = [p['s'][m] - bm[m] for m in p['s']]
    res.append(('planted_momentum_positive', ST.mean(ex) > 0))
    # (4) 回転と費用: 同じ組を持ち続ければ（業種1つ・H=1）費用は 0
    R1 = {'x': {m: 0.01 for m in months}, 'y': {m: 0.0 for m in months}}
    q = build_ind_topk(R1, months, 3, 1, 1, ('one', 0.01), K=1, minN=2)
    res.append(('constant_holding_zero_cost', all(abs(q['s'][m] - q['net'][m]) < 1e-15 for m in q['s'])))
    # (5) ハロウィーン: 夏は相手と同じ、冬は 1.5 倍から借入を引いた値
    mm = {k: 0.01 for k in month_range(190001, 190312)}
    hh = build_halloween(mm, {k: 0.002 for k in mm}, [11, 12, 1, 2, 3, 4], 1.5, 0.005, ('dL', 0.001))
    res.append(('halloween_summer_equal', abs(hh['s'][190007] - 0.01) < 1e-15))
    res.append(('halloween_winter', abs(hh['s'][190012] - (0.015 - 0.5 * (0.002 + 0.005 / 12))) < 1e-15))
    # (6) grade_era の線
    ok = {'ex_ann': 1.0, 'cagr_diff': 0.5, 't': 2.1}
    res.append(('grade_S', grade_era(ok, ok, ok, 0.01, ok, months=300)[0] == 'S'))
    res.append(('grade_A_no_holm', grade_era(ok, ok, ok, 0.2, ok, months=300)[0] == 'A'))
    res.append(('grade_B_weak_t', grade_era(dict(ok, t=1.0), ok, ok, 0.2, ok, months=300)[0] == 'B'))
    res.append(('grade_short', grade_era(ok, ok, ok, 0.01, ok, months=100)[0] == 'NA_short'))
    res.append(('grade_timing_needs_sharpe', grade_era(ok, ok, ok, 0.01, ok, sharpe_halves={'h1': (0.5, 0.6), 'h2': (0.5, 0.4)}, timing=True, months=300)[0] == 'C'))
    res.append(('verdict', rule_verdict(['S', 'B']) == '再現（強）' and rule_verdict(['A', 'C']) == '割れた' and rule_verdict(['NA_short']) == '検定不能'))
    return res


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        out = selftest()
        for k, v in out:
            print(('OK  ' if v else 'FAIL') + ' ' + k)
        sys.exit(0 if all(v for _, v in out) else 1)
    for k in URLS:
        fetch(k)
    if '--extract' in sys.argv:
        o = build_extract()
        print('extract', EXTRACT, os.path.getsize(EXTRACT))
        print('extract_sha256', o['extract_sha256'])
        print('rules_sha256  ', o['rules_sha256'])
        sys.exit(0)
    print(json.dumps(shape_report(), ensure_ascii=False, indent=1, default=str))
