#!/usr/bin/env python3
"""night/nx_pre1926x_data.py — nx_pre1926x（他セッションで残った規則を 1709〜1926 年に当てる）のデータ取得と整形だけ。

★成績は一つも計算しない（規則のリターン・市場との差・t・シャープは出さない）。ここが出すのは
データの形（列・期間・欠け・銘柄数・データの誤りの件数）だけ。事前登録 out/nx_pre1926x_prereg.json の
data 欄と known_limits の数字はこの道具の出力（python3 night/nx_pre1926x_data.py）から写した。

使うデータ（キャッシュ out/_nx_cache/・gitignore）
- Cowles Commission『Common-Stock Indexes』(1938/39) の月次指数（Yale ICF）:
    Series P（株価）Stock_Prices-Cowles.xls / Series C（現金配当を再投資した株価）Stock_PricesincDvds-Cowles.xls
    ★各月の『平均の株価』＝その月の高値と安値の算術平均（Cowles 1938 の Introduction『6. Construction』）。
      1918 年以降の一部の業種は Standard Statistics の週次の月平均へつないである＝どちらも月中の平均
- Yale ICF の Old NYSE（Goetzmann-Ibbotson-Peng 2001）: nyse-monthly-price-1815-1925-updated-2021-09-04-with-labels.csv
    （671 証券・月次の価格・買い気配と売り気配の平均・新聞が欠けた月は前後の月の平均で埋めてある＝ページの説明）
    Price-Weighted-Index-Returns-2020-08-20.xls（GIP の価格加重の指数のリターン・報告の相手）
- Yale ICF の London Stock Exchange（Investor's Monthly Manual・Goetzmann-Rouwenhorst）: Railways_new / Banks_new / Misc_new
    （生の月次・1869-01〜1929-12）と Totaldata.zip（整えた版・★Excel の行の上限 1,048,575 行で切れている）
- イングランド銀行『A millennium of macroeconomic data for the UK』v3.1: M13（月次の株価指数 1709〜）・M9（月次の短期金利）
- FRED の NBER 歴史系列: M13002US35620M156NNBR（ニューヨークの商業手形 4〜6か月・年率%・1857〜1971）
"""
import csv, io, json, math, os, re, sys, zipfile, collections, pickle, hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as C  # noqa: E402

CACHE = C.CACHE
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


# ───────────────────────── Cowles ─────────────────────────
# 索引番号（Cowles の本の Alphabetical List of Indexes）。Series P の xls では 列 = 番号 + 2
COWLES_COMBOS = {1: 'All Stocks', 2: 'Industrials', 4: 'Utilities', 5: 'Coal', 12: 'Steel and Iron', 34: 'Retail Trade',
                 39: 'Tobacco and Tobacco Products', 41: 'Automobiles and Trucks', 44: 'Retail Trade—Chain Stores', 58: 'Airplane'}
# 子（『親—子』の名前の業種）→ 親。10 の組合せ（59 の業種＋10 の組合せ＝69）はちょうど子を持つ番号
COWLES_CHILD = {53: 5, 54: 5, 28: 12, 29: 12, 35: 34, 36: 34, 44: 34, 45: 34, 48: 34, 59: 34, 61: 34, 69: 34,
                30: 39, 40: 39, 42: 41, 43: 41, 66: 58, 67: 58, 9: 4, 11: 4, 16: 4, 20: 4}
COWLES_SECTOR_AGG = (1, 2, 4)          # 市場・部門の集計（業種の横断から外す）
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


def cowles_returns(P=None, Cs=None, end=192606):
    """事前登録どおりの Cowles の月次リターン（総リターン＝Series C を主）。
    - 連続する2つの取引月の水準から r_t。1914-08〜11（取引所の閉鎖）は取引月から外し、1914-12 の値は 1914-07 からの5か月
    - C と P の食い違い: d_t = ln(C_t/C_{t−1}) − ln(P_t/P_{t−1}) が [−0.01, 0.05] の外なら点検。
        C 側だけが『跳ねて戻る』（|c_t|>0.15・|c_{t+1}|>0.15・符号が逆・|c_t+c_{t+1}|<0.05）なら C の写し誤りとみなし
        r_t = exp(p_t + d̃) − 1（d̃ = その業種の直前12の有効な月の d の中央値・無ければ 0.004）
        P 側だけが跳ねて戻るなら P の写し誤り＝C をそのまま使う。どちらとも決まらなければ欠測（0 と読まない）
    戻り値: ({番号: {ym: r}}, 点検の件数の辞書)"""
    if P is None:
        P, _ = cowles_P()
    if Cs is None:
        Cs, _ = cowles_C()
    closed = {191408, 191409, 191410, 191411}
    stats = collections.Counter()
    fixes = []
    R = {}
    for n in sorted(set(P) | set(Cs)):
        p, c = P.get(n, {}), Cs.get(n, {})
        ks = sorted(k for k in set(p) | set(c) if k <= end and k not in closed)
        prev = {}
        # 取引月の並び（閉鎖の4か月は飛ばす）で隣どうし
        allm = []
        k = 187101
        while k <= end:
            if k not in closed:
                allm.append(k)
            k = madd(k, 1)
        idx = {m: i for i, m in enumerate(allm)}
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
                spike = lambda a, b: a is not None and b is not None and abs(a) > 0.15 and abs(b) > 0.15 and a * b < 0 and abs(a + b) < 0.05
                # 直前の月が C の写し誤りだった場合（C_{t−1} が誤り）: c_{t−1} と c_t で跳ねて戻る
                t_1 = allm[i - 2] if i >= 2 else None
                cprev = _lr(c[t_1], c[t0]) if t_1 and t_1 in c and t0 in c else None
                c_bad = spike(cr, c2) or spike(cprev, cr)
                pprev = _lr(p[t_1], p[t0]) if t_1 and t_1 in p and t0 in p else None
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


# ───────────────────────── Old NYSE ─────────────────────────
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


def nyse_pw_index():
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


# ───────────────────────── イングランド銀行 ─────────────────────────
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
    """M13 → ({列: {ym: 水準}}, {列: 説明})。列 23 = つないだ月次の指数（主）"""
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
    """M9 → ({列: {ym: 年率%}}, {列: 説明})。列 2 = Bank Rate（月末）"""
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


# ───────────────────────── NBER（FRED） ─────────────────────────
def nber_cp():
    """ニューヨークの商業手形の金利（年率%）→ {ym: 月の小数リターン = 年率/1200}"""
    lines = fetch('nber_cp').decode().splitlines()[1:]
    out = {}
    for ln in lines:
        d, v = ln.split(',')
        try:
            out[int(d[:4]) * 100 + int(d[5:7])] = float(v) / 1200
        except ValueError:
            pass
    return out


# ───────────────────────── London Stock Exchange（IMM） ─────────────────────────
NONCOMMON = re.compile(r'pref|deb\b|deb\.|debenture|guar|bond|loan|mortgage|per cent|%|obligation|annuit|rent.?charge|lien|certif|warrant|right|scrip|founders|deferred', re.I)
FOREIGN_CCY = re.compile(r'\$|dollar|u\.s\. ?currency|francs?\b|marks?\b|lire|pesos?\b|roubles?|rupees?\b|yen\b|florins?|gulden', re.I)


def _num(s):
    s = (s or '').strip()
    if s in ('', 'NULL', '...', '-', '—'):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


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
    """生の Railways・Banks・Misc → {id: {'sector', 'name', 'sec', 'pct', 'm': {ym: (late, paid, par, amntshare, nshare, capsub, note)}}}。
    数字の欄だけを float にする（'...'・'xd' 等の注記は note に残す）。キャッシュ out/_nx_cache/nx_pre1926x_lse_raw.pkl"""
    pk = os.path.join(CACHE, 'nx_pre1926x_lse_raw.pkl')
    if os.path.exists(pk):
        return pickle.load(open(pk, 'rb'))
    out = {}
    for key, fn, sector in (('lse_rail', 'Railways_new.csv', 'rail'), ('lse_bank', 'Banks_new.csv', 'bank'), ('lse_misc', 'Misc_new.csv', 'misc')):
        z = zipfile.ZipFile(path(key))
        for row in csv.DictReader(io.TextIOWrapper(z.open(fn), encoding='latin-1')):
            try:
                ym = int(row['year']) * 100 + int(row['month'])
            except (ValueError, KeyError):
                continue
            i = row['id']
            rec = out.get(i)
            if rec is None:
                rec = out[i] = {'sector': sector, 'name': row.get('compsecdes', ''), 'sec': row.get('secdes', ''),
                                'pct': row.get('percentfrmsecdes', ''), 'm': {}}
            nshare = _num(row.get('capitalnumshare'))
            capsub = _num(row.get('capitalsubscribed')) or _num(row.get('capitalamntcapital'))
            rec['m'][ym] = (_num(row.get('pricemonthlate')), _num(row.get('capitalpaid')), _num(row.get('capitalpar')),
                            _num(row.get('capitalamntshare')), nshare, capsub,
                            (row.get('npricemonthlate') or '') + '|' + (row.get('nlastbusiness') or ''))
    pickle.dump(out, open(pk, 'wb'))
    return out


def lse_is_common(rec):
    """事前登録の文の規則: 固定の率（percentfrmsecdes）が無く、証券の説明と名前に優先・社債・保証・借入・率の語が無いもの"""
    if (rec.get('pct') or '').strip() not in ('', 'NULL'):
        return False
    txt = (rec.get('sec') or '') + ' ' + (rec.get('name') or '')
    return not NONCOMMON.search(txt)


# ───────────────────────── 形の報告 ─────────────────────────
def shape_report():
    rep = {}
    # Cowles
    P, names = cowles_P()
    Cs, titles = cowles_C()
    R, st, fixes = cowles_returns(P, Cs)
    U = cowles_industry_universe(R)
    yrs = [187203, 188001, 189001, 190001, 191001, 192001, 192512, 192606]
    rep['cowles'] = {
        'P_groups': len(P), 'C_blocks': len(Cs),
        'C_blocks_with_data': sum(1 for n in Cs if Cs[n]),
        'P_first_last': {n: (min(v), max(v)) for n, v in P.items() if v},
        'C_first_last': {n: (min(v), max(v)) for n, v in Cs.items() if v},
        'P_names': names,
        'return_build_counts_to_192606': st,
        'text_number_cells_read': dict(TEXT_NUM_CELLS),
        'fixes': fixes,
        'industry_universe_keys': sorted(U),
        'industries_with_return_in_month': {m: sum(1 for s in U.values() if m in s) for m in yrs},
        'industries_ever_before_192606': sum(1 for s in U.values() if any(k <= 192606 for k in s)),
    }
    # NYSE
    meta, px = nyse()
    cnt = collections.Counter((m['class'], m['type']) for m in meta.values())
    ind = collections.Counter(m['industry'] for m in meta.values() if m['class'] == 'Equity' and m['type'] == 'common')
    com = [i for i, m in meta.items() if m['class'] == 'Equity' and m['type'] == 'common']
    per_year, ext, nret = {}, 0, 0
    closed = {191408, 191409, 191410, 191411}
    for y in range(1815, 1926, 5):
        per_year[y] = sum(1 for i in com if (y * 100 + 6) in px[i] and madd(y * 100 + 6, -1) in px[i])
    for i in com:
        ks = sorted(px[i])
        for a, b in zip(ks, ks[1:]):
            if madd(a, 1) == b:
                nret += 1
                x = px[i][b] / px[i][a]
                if x > 3 or x < 1 / 3:
                    ext += 1
    rep['nyse'] = {'securities': len(meta), 'class_type': {f'{a}/{b}': v for (a, b), v in cnt.items()},
                   'common_equity': len(com), 'common_by_industry': dict(ind),
                   'common_with_consecutive_price_june_of_year': per_year,
                   'consecutive_month_pairs': nret, 'price_ratio_outside_1/3_to_3': ext,
                   'months_in_file': (min(min(v) for v in px.values() if v), max(max(v) for v in px.values() if v)),
                   'prices_1914_aug_nov': sum(1 for i in com for k in closed if k in px[i])}
    pw = nyse_pw_index()
    rep['nyse_pw_index'] = {k: (min(v), max(v), len(v)) for k, v in pw.items()}
    # UK
    uk, desc = uk_share_prices()
    sp = uk[23]
    chg = uk[24]
    comp = collections.Counter()
    runs = []
    for k in sorted(chg):
        if k > 191406:
            break
        p0 = madd(k, -1)
        src = None
        for c in (2, 6, 9, 3, 5, 7, 8, 12, 13, 10, 14):
            s = uk[c]
            if k in s and p0 in s and abs((s[k] / s[p0] - 1) * 100 - chg[k]) < 1e-6:
                src = c
                break
        comp[src] += 1
        if not runs or runs[-1][0] != src:
            runs.append([src, k, k])
        else:
            runs[-1][2] = k
    rep['uk_index'] = {'spliced_col23_first_last': (min(sp), max(sp)), 'months_1709_05_to_1914_06': sum(1 for k in sp if 170905 <= k <= 191406),
                       'splice_source_runs_to_191406': [(desc.get(s, '?')[:90] if s else None, a, b) for s, a, b in runs],
                       'col_desc': {c: d[:160] for c, d in desc.items()}}
    rt, rdesc = uk_rates()
    rep['uk_rates'] = {c: {'desc': rdesc[c][:200], 'first_last': (min(v), max(v)) if v else None, 'n': len(v)} for c, v in rt.items() if v}
    cp = nber_cp()
    rep['nber_cp'] = {'first_last': (min(cp), max(cp)), 'n': len(cp)}
    # LSE
    raw = lse_raw()
    tt = lse_total_types()
    last = tt.pop('__last__', None)
    agree = collections.Counter()
    for i, rec in raw.items():
        if i in tt:
            agree[(tt[i][0] == 'Common Stock', lse_is_common(rec))] += 1
    cur_agree = collections.Counter()
    for i, rec in raw.items():
        if i in tt and tt[i][0] == 'Common Stock':
            cur_agree[(tt[i][1] == 'GBP', not FOREIGN_CCY.search((rec.get('name') or '') + ' ' + (rec.get('sec') or '')))] += 1
    commons = {i: rec for i, rec in raw.items() if lse_is_common(rec)}
    by_sector = collections.Counter(rec['sector'] for rec in commons.values())
    per = {}
    paidchg = shchg = ext = pairs = 0
    for y in (1870, 1875, 1880, 1885, 1890, 1895, 1900, 1905, 1910, 1913, 1920, 1925, 1929):
        k1 = y * 100 + 6
        k0 = madd(k1, -1)
        per[y] = sum(1 for rec in commons.values() if rec['m'].get(k1, (None,))[0] and rec['m'].get(k0, (None,))[0])
    capok = 0
    for rec in commons.values():
        ks = sorted(rec['m'])
        for a, b in zip(ks, ks[1:]):
            ra, rb = rec['m'][a], rec['m'][b]
            if madd(a, 1) != b or not ra[0] or not rb[0]:
                continue
            pairs += 1
            if ra[1] != rb[1]:
                paidchg += 1
            if ra[3] != rb[3]:
                shchg += 1
            x = rb[0] / ra[0]
            if x > 3 or x < 1 / 3:
                ext += 1
            if rb[4] or (rb[5] and rb[3]):
                capok += 1
    rep['lse'] = {'raw_securities': len(raw), 'raw_by_sector': dict(collections.Counter(r['sector'] for r in raw.values())),
                  'totaldata_last_row(NewID,year,month)': last, 'totaldata_ids': len(tt),
                  'classifier_vs_totaldata(Type==Common, rule==common)': {f'{a}/{b}': v for (a, b), v in agree.items()},
                  'currency_rule_vs_totaldata_on_common(GBP, rule GBP)': {f'{a}/{b}': v for (a, b), v in cur_agree.items()},
                  'common_by_rule': len(commons), 'common_by_sector': dict(by_sector),
                  'common_with_consecutive_late_price_june': per,
                  'consecutive_pairs': pairs, 'pairs_paidup_changed': paidchg, 'pairs_nominal_per_share_changed': shchg,
                  'pairs_ratio_outside_1/3_to_3': ext, 'pairs_with_cap_info(nshare or capsub&amntshare)': capok}
    rep['sha256_16'] = {k: sha(k) for k in ('cowles_P', 'cowles_C', 'nyse', 'nyse_pw', 'boe', 'lse_rail', 'lse_bank', 'lse_misc', 'lse_total', 'nber_cp')}
    return rep


if __name__ == '__main__':
    for k in URLS:
        fetch(k)
    r = shape_report()
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
