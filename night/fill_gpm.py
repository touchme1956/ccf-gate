#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/fill_gpm.py — 粗利率の水準 gpm（直近5会計年度の粗利率の中央値・3年以上）を原本から機械で埋める（v9.9.212・2026-10-12新設）

■ なぜ
  堀の歴史検証（docs/CLAUDE_ARCHIVE.md:18832・:18875・:18924・:18979・:19033）で、決算の数字だけで測れる部品のうち
  **粗利率の水準（M3）だけが、時代が重ならない2つの標本で長い先（10〜14年）の利益率の持続を当てた**
  （1990年代の入口→10〜14年先 +0.221・生き残りの偏りを入れた見積もりで 0.15〜0.20／XBRL の時代の6〜10年先 +0.11〜+0.16）。
  営業利益率の高さ（門の F7）をそろえても効く＝門に無い情報。ユーザー明示指示「では必要なものを採用して！」（2026-10-12）で
  堀の6本目の柱にした。門の gpa（粗利÷総資産）とは別物（こちらは粗利÷売上）。

■ 定義（検定の M3 と同じ。moat_track_test.firm_vintage・moat_track_panel.year_row）
      gpm = median( 粗利_y ÷ 売上_y : y = Y−4 … Y・測れた年が3年以上 ) × 100   [%]
  ・粗利＝GrossProfit。無い年は 売上 − 原価（CostOfRevenue → CostOfGoodsAndServicesSold／IFRS は CostOfSales）。
    粗利率が −100〜+100% の外の年は捨てる（検定と同じ）
  ・売上の候補（gate0 の一覧 retro_growth_persistence.REV_TAGS・IFRS は Revenue / RevenueFromContractsWithCustomers）は**代替**。
    窓の年を最も多く持つ候補を主にし、重なる年が2%以内で一致する候補だけで欠けた年を埋める（moat_era90 の merged_win と同じ。
    gate0 の『年数の多い候補が主』だと 2018年の収益認識の基準の変更でタグが替わった社の新しい年が落ちる）
  ・Y＝パックの会計年度（`_meta.reportDate`＋45日までに期末が来た最後の年次）。他の採点欄と同じ年を見る
  ・年は期末の暦年（backtest_core.annual_rows と同じ）

■ 原本
  ・米国株・外国の SEC 申告社: companyfacts（リポジトリ直下の companyfacts.zip。無い社は SEC の API）。
    us-gaap が無ければ ifrs-full。様式は 10-K／20-F／40-F の年次（FY・300日以上）。通貨は売上の行が最も多い単位にそろえる
  ・日本株: パックに刻んだ docID の**有価証券報告書PDF**（EDINET 直配信・鍵なし・rebuild_src_cache_jp の fetch_pdf）。
    表紙で 有報・会社・事業年度を確かめ、【連結損益計算書】（連結が無い社だけ【損益計算書】）の 売上高（売上収益・営業収益）と
    売上総利益の2期を読む。同じ年が複数の有報にあれば新しい有報の値（過年度の組み替えを含む）。EDINET_DB MCP は使わない

■ 空欄（理由は必ず `_meta.nulls.gpm`）
  ・金融・不動産（SIC 6xxx）＝検定の母集団の外（粗利率が事業の質を表さない）
  ・粗利の行も原価の行も無い社（売上原価を開示しない業態）・3年に届かない社
  ・空欄の社は堀指数で残りの柱に割り直される（今の5本の空欄と同じ扱い）——**測れないことで得をする向きがあり得る**ので、
    毎回の実行で空欄の社を一覧に出す
  ・**取れない（通信の失敗）と測れない（原本に無い）を分ける**（2026-10-12・ルール7の親戚）: SEC・EDINET が一時的に
    応答しない・ティッカーの一覧を取れない、のような失敗では**パックに何も書かない**（前の値も空欄の理由も残す）。
    旧版はこれを空欄の理由として書き、前回の測定値まで消していた。取れなかった社は一覧に出し、終了コード 2 で知らせる
    ——もう一度回せばよい。CIK はティッカーの一覧に無ければパックの `_meta.source`（SEC の提出書類の URL）から読む

■ 帯（門の ccfGpmBand が持つ。**切れ目は測定値であって発明ではない**）
      gpm < 26.8%      → 50
      26.8 〜 44.0%    → 70
      44.0% 以上       → 85
  26.8 / 44.0 は XBRL の時代の表（out/_moat5_panel.json・ビンテージ 2011〜2020・検定の母集団＝入口の売上2億ドル以上・
  金融と不動産を除く・各1,073〜1,526社）での M3 の三分位の切れ目の**10ビンテージの中央値**（下 25.9〜27.4・上 42.5〜48.9）。
  acqS5 の帯（7ビンテージの三分位の切れ目の中央値）と同じ作り方。参考: 1990年代の入口（1995〜1999年度）では 21.7 / 36.5

実行: python3 night/fill_gpm.py [--write] [--only MSFT,6146] [--list] [--us-only|--jp-only]
      審査の納品の前に `python3 night/fill_gpm.py --only {T} --write`（gpm は機械の柱＝審査官は書かない。
      値も _meta.nulls.gpm も無いパックは納品検査 night/validate_packs.py が FAIL にする）
出力: パックの gpm・_meta.evidence.gpm・_meta.provenance.gpm="machine"（または _meta.nulls.gpm）
終了コード: 取れなかった社（一時的な失敗）が1社でもあれば 2
キャッシュ: 日本株の有報のテキスト out/_nx_cache/gpm_jp/{docID}.txt（gitignore）
"""
import glob, gzip, json, os, re, statistics, sys, time, unicodedata, urllib.error, urllib.request, zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import retro_growth_persistence as RGP      # noqa: E402  REV_TAGS（gate0 の売上タグ）・SEAM_TOL（2%）

ZIP = os.path.join(BASE, 'companyfacts.zip')
JP_CACHE = os.path.join(BASE, 'out', '_nx_cache', 'gpm_jp')
HDRS = {'User-Agent': 'hachimon-gate fortis5280@gmail.com'}   # SEC 向け（ルール5）。EDINET には別の UA を使う（rebuild_src_cache_jp）
CUT_LO, CUT_HI = 26.8, 44.0          # 帯の切れ目（上の頭注。門の CCF_GPM_CUT と同じ値＝check で照合）
NEED = 3                             # 窓5年のうち測れた年の下限（検定と同じ）
LAG = 45                             # reportDate のあと何日までに期末が来た年次を Y とみなすか
FORMS = {'10-K', '10-K/A', '10-KT', '10-KT/A', '20-F', '20-F/A', '40-F', '40-F/A'}
REV = {'us-gaap': [t for t in RGP.REV_TAGS if t not in ('Revenue', 'RevenueFromContractsWithCustomers')],
       'ifrs-full': ['Revenue', 'RevenueFromContractsWithCustomers']}
COST = {'us-gaap': ['CostOfRevenue', 'CostOfGoodsAndServicesSold'], 'ifrs-full': ['CostOfSales']}
GP = 'GrossProfit'


class Transient(Exception):
    """取れない（通信の一時的な失敗）。測れない（原本に無い）とは別——パックに何も書かない"""


def band(g):
    """門の ccfGpmBand と同じ（表示と集計用）"""
    if g is None:
        return None
    return 50 if g < CUT_LO else (70 if g < CUT_HI else 85)


# ─────────────────────────── SEC（米国株・外国の申告社） ───────────────────────────
_ZF = None


def facts_of(cik):
    """companyfacts（zip を先に・無ければ SEC の API）。XBRL が無い社（404）は None。
    通信の失敗が続けば Transient（測れない、ではない＝呼び手はパックに何も書かない）"""
    global _ZF
    name = 'CIK%010d.json' % int(cik)
    try:
        if _ZF is None and os.path.exists(ZIP):
            _ZF = zipfile.ZipFile(ZIP)
        if _ZF is not None:
            return json.loads(_ZF.read(name))
    except KeyError:
        pass
    u = 'https://data.sec.gov/api/xbrl/companyfacts/%s' % name
    why = ''
    for i in range(3):
        try:
            r = urllib.request.urlopen(urllib.request.Request(u, headers=dict(HDRS, **{'Accept-Encoding': 'gzip'})), timeout=180)
            b = r.read()
            if r.headers.get('Content-Encoding') == 'gzip':
                b = gzip.decompress(b)
            time.sleep(0.15)
            return json.loads(b)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            why = 'HTTP %d' % e.code
            time.sleep(2 ** i)
        except Exception as e:
            why = '%s: %s' % (type(e).__name__, e)
            time.sleep(2 ** i)
    raise Transient('SEC の companyfacts を取れない（%s）' % why)


def _days(a, b):
    import datetime as dt
    try:
        return (dt.date(*map(int, b.split('-'))) - dt.date(*map(int, a.split('-')))).days
    except Exception:
        return None


def rows_of(facts, tax, tag, unit=None):
    """年次の行 {期末の暦年: (値, 期末, 提出日, 様式, 単位)}。同じ年に複数あれば最後に提出された行
       （backtest_core.annual_rows と同じ規則に 20-F・40-F と ifrs-full・外貨を足した）"""
    node = (facts.get('facts', {}).get(tax, {}) or {}).get(tag)
    if not node:
        return {}
    best = {}
    for u, rows in (node.get('units') or {}).items():
        if unit and u != unit:
            continue
        if '/' in u or u in ('shares', 'pure'):
            continue
        for r in rows:
            if r.get('fp') != 'FY' or r.get('form') not in FORMS or r.get('val') is None:
                continue
            st, en, fd = r.get('start'), r.get('end') or '', r.get('filed') or ''
            if not en:
                continue
            if st:
                dd = _days(st, en)
                if dd is not None and dd < 300:
                    continue
            k = int(en[:4])
            if k not in best or fd > best[k][2]:
                best[k] = (float(r['val']), en, fd, r.get('form'), u)
    return best


def reporting_unit(facts, tax):
    """売上の行が最も多い通貨（比を取るので粗利・原価も同じ単位にそろえる）"""
    cnt = {}
    for tag in REV[tax] + [GP]:
        node = (facts.get('facts', {}).get(tax, {}) or {}).get(tag) or {}
        for u, rows in (node.get('units') or {}).items():
            if '/' in u or u in ('shares', 'pure'):
                continue
            cnt[u] = cnt.get(u, 0) + sum(1 for r in rows if r.get('fp') == 'FY' and r.get('form') in FORMS)
    return max(cnt, key=cnt.get) if cnt else None


def merged_win(facts, tax, tags, unit, W):
    """候補＝代替: 窓の年を最も多く持つ候補を主にし、重なる年が2%以内で一致する候補だけで欠けた年を埋める（moat_era90 と同じ）"""
    cands = []
    for t in tags:
        d = rows_of(facts, tax, t, unit)
        if d:
            cands.append((t, d))
    if not cands:
        return {}, None
    cands.sort(key=lambda c: (-sum(1 for y in W if y in c[1]), -len(c[1])))
    main_tag, merged = cands[0][0], dict(cands[0][1])
    src = {y: main_tag for y in merged}
    for t, d in cands[1:]:
        ov = [y for y in merged if y in d]
        if not all(merged[y][0] == 0 or abs(d[y][0] - merged[y][0]) / abs(merged[y][0]) <= RGP.SEAM_TOL for y in ov):
            continue
        for y, v in d.items():
            if y not in merged:
                merged[y], src[y] = v, t
    return merged, src


def sec_gpm(facts, report_date):
    """(gpm[%] or None, 年ごとの明細, 理由)"""
    tax = 'us-gaap' if any(rows_of(facts, 'us-gaap', t) for t in REV['us-gaap'] + [GP]) else (
        'ifrs-full' if any(rows_of(facts, 'ifrs-full', t) for t in REV['ifrs-full'] + [GP]) else None)
    if tax is None:
        return None, [], 'SEC の XBRL に売上の年次の行が無い'
    unit = reporting_unit(facts, tax)
    allrev = {}
    for t in REV[tax]:
        for y, v in rows_of(facts, tax, t, unit).items():
            allrev.setdefault(y, v)
    lim = None
    if report_date:
        import datetime as dt
        try:
            lim = (dt.date(*map(int, report_date[:10].split('-'))) + dt.timedelta(days=LAG)).isoformat()
        except Exception:
            lim = None
    ys = [y for y, v in allrev.items() if lim is None or v[1] <= lim]
    if not ys:
        return None, [], 'パックの会計年度（reportDate %s）までの売上の年次の行が無い' % report_date
    Y = max(ys)
    W = list(range(Y - 4, Y + 1))
    rev, rsrc = merged_win(facts, tax, REV[tax], unit, W)
    cost, csrc = merged_win(facts, tax, COST[tax], unit, W)
    gp = rows_of(facts, tax, GP, unit)
    det = []
    for y in W:
        r = rev.get(y)
        if not r or r[0] <= 0:
            continue
        g, how = None, None
        if y in gp:
            g, how = gp[y][0], 'GrossProfit'
        elif y in cost:
            g, how = r[0] - cost[y][0], '売上−%s' % csrc[y]
        if g is None:
            continue
        v = g / r[0]
        if -1 <= v <= 1:
            det.append({'y': y, 'gm': round(v * 100, 2), 'rev': r[0], 'gp': g, 'how': how, 'revTag': rsrc[y], 'form': r[3], 'end': r[1]})
    if len(det) < NEED:
        why = ('粗利の行（GrossProfit）も原価の行（%s）も無い＝売上原価を開示しない業態' % '・'.join(COST[tax])
               if not gp and not cost else '窓 %d〜%d 年で粗利率が測れた年が %d 年（3年に届かない）' % (W[0], W[-1], len(det)))
        return None, det, why
    g = round(statistics.median(d['gm'] for d in det), 1)
    return g, det, '%s・単位 %s' % (tax, unit)


# ─────────────────────────── 日本株（有報PDF） ───────────────────────────
PL_HEAD = re.compile(r'【(?:要約)?連結損益(?:計算書|及び(?:その他の)?包括利益計算書)】')
PL_HEAD_SOLO = re.compile(r'【損益計算書】')
_PFX = r'(?:[IVXⅠ-Ⅹ]+\s+|\d+\.\s*)?'     # 旧様式の『I 売上高』『1.売上原価』の番号
REV_LINE = re.compile(r'^\s*' + _PFX + r'(売上高合計|売上収益合計|営業収益合計|売上高|売上収益|営業収益)(?:\s|※|\()')
GP_LINE = re.compile(r'^\s*' + _PFX + r'売上総利益(?!率)')
COST_LINE = re.compile(r'^\s*' + _PFX + r'(売上原価合計|売上原価)(?:\s|※|\()')   # 粗利の行が無い表だけ『売上−原価』（米国株と同じ）
NUM = re.compile(r'(△|▲|-)?\s*(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?')   # 小数のある数（百分比の列）は金額ではないので捨てる（_nums）


def _nf(s):
    return unicodedata.normalize('NFKC', s or '')


def _nums(line):
    s = re.sub(r'※\s*\d+(?:\s*,\s*※?\s*\d+)*', ' ', line)      # 注記番号（※1・※2,※3）を落とす
    s = re.sub(r'\(注\s*\d*\)', ' ', s)
    out = []
    for m in NUM.finditer(s):
        if m.group(3):            # 『100.0』『23.4』＝百分比の列（実測 村田製作所の旧様式）。有報の金額は整数
            continue
        v = float(m.group(2).replace(',', ''))
        out.append(-v if m.group(1) else v)
    return out


def jp_text(doc_id):
    """有報PDF → テキスト（キャッシュ）。取れなければ (None, 理由)"""
    import rebuild_src_cache_jp as RB
    os.makedirs(JP_CACHE, exist_ok=True)
    p = os.path.join(JP_CACHE, doc_id + '.txt')
    if os.path.exists(p):
        return open(p, encoding='utf-8').read(), ''
    b, why = RB.fetch_pdf(doc_id)
    if b is None:
        return None, why
    try:
        pages, _n = RB.pdf_pages(b)
    except Exception as e:
        return None, 'PDF を読めない: %s' % e
    first = pages[0] if pages else ''
    txt = '<<<COVER>>>\n' + first + '\n<<<BODY>>>\n' + '\n'.join(RB.strip_footer(t)[0] for t in pages)
    open(p, 'w', encoding='utf-8').write(txt)
    return txt, ''


def jp_pl(txt):
    """連結（無ければ単体）の損益計算書の 売上・粗利 の2期 → ((売上_前, 粗利_前), (売上_当, 粗利_当), 見出し) or (None, 理由)"""
    s = _nf(txt.split('<<<BODY>>>', 1)[-1])
    heads = [m for m in PL_HEAD.finditer(s)]
    kind = '連結'
    if not heads:
        heads, kind = [m for m in PL_HEAD_SOLO.finditer(s)], '単体'
    for m in heads:
        blk = s[m.start(): m.start() + 2500]
        two = bool(re.search(r'前(?:連結会計|事業)年度', blk[:800]))
        # 連結の初年度は当期の1列だけ（実測 PR TIMES FY2022/2・FFRI FY2022/3）——当期だけを採る（前期の単体と混ぜない）
        one = (not two) and bool(re.search(r'当(?:連結会計|事業)年度', blk[:800]))
        if not (two or one):
            continue
        need = 2 if two else 1
        rv = gp = cs = None
        um = re.search(r'\(単位\s*[:：]\s*(百万円|千円|円)\)', blk[:400])
        unit = um.group(1) if um else '単位不明'
        for ln in blk.split('\n')[1:]:
            if rv is None and REV_LINE.match(ln):
                n = _nums(ln)
                if len(n) >= need:
                    rv = (n[-2] if two else None, n[-1])
            if gp is None and GP_LINE.match(ln):
                n = _nums(ln)
                if len(n) >= need:
                    gp = (n[-2] if two else None, n[-1])
            if cs is None and COST_LINE.match(ln):
                n = _nums(ln)
                if len(n) >= need:
                    cs = (n[-2] if two else None, n[-1])
            if rv and gp:
                break
        how = ''
        if rv and not gp and cs:
            gp = (None if rv[0] is None or cs[0] is None else rv[0] - cs[0], rv[1] - cs[1])
            how = '・粗利の行が無く売上−売上原価'
        if rv and gp:
            return ((rv[0], gp[0]), (rv[1], gp[1]), '%s・%s（%s%s%s）' % (kind, m.group(0), unit, '' if two else '・当期の1列だけ', how)), ''
        if rv and not gp:
            return None, '%s の損益計算書に売上総利益の行も売上原価の行も無い（売上原価を開示しない業態）' % kind
    return None, '損益計算書の表（前期・当期の2列）を読めない'


def jp_gpm(t, pack, log):
    import rebuild_src_cache_jp as RB
    m = pack.get('_meta') or {}
    rd = str(m.get('reportDate') or '')
    if not re.match(r'^\d{4}-\d{2}', rd):
        return None, [], 'パックに reportDate が無く基準年を決められない'
    Y = int(rd[:4])
    W = list(range(Y - 4, Y + 1))
    prio, rest = RB.doc_ids(pack)
    ids = sorted(set(prio) | set(rest), reverse=True)
    if not ids:
        return None, [], 'パックに有報の docID が刻まれていない'
    # 審査の記録に『docID列: FY2026 S100YCOO / FY2025 …』があれば、2期とも既に読めた年の有報は落とさない（礼儀と時間）
    known = {}
    for s_ in RB._strings(m):
        for fy_, d_ in re.findall(r'FY\s*(\d{4})\s*[:：]?\s*(S100[0-9A-Z]{4})', s_):
            known.setdefault(d_, int(fy_))
    # FY が分かる有報は Y・Y−2・Y−4 を先に読む（1冊で2期読めるので3冊で窓の5年がそろう）
    tgt = {Y, Y - 2, Y - 4}
    ids = sorted(ids, key=lambda d: (0 if known.get(d) in tgt else 1, -(known.get(d) or 0), [-ord(ch) for ch in d]))
    got, seen_fy, notes, flaky = {}, set(), [], []
    for d in ids:
        if all(y in got for y in W):
            break
        if d in known and known[d] in got and (known[d] - 1) in got:
            continue
        txt, why = jp_text(d)
        if txt is None:
            notes.append('%s 取れない（%s）' % (d, why))
            if not (why.startswith('HTTP 404') or why.startswith('PDF を読めない')):
                flaky.append('%s（%s）' % (d, why))     # 通信の失敗＝測れない、ではない
            continue
        cov = RB.cover_info(txt.split('<<<BODY>>>', 1)[0].replace('<<<COVER>>>', ''))
        if not RB.is_yuho(cov.get('kind')) or not cov.get('fy_end'):
            continue
        if not RB.same_company(pack, cov):
            notes.append('%s は別の会社（%s）' % (d, cov.get('company')))
            continue
        fy = int(cov['fy_end'][:4])
        if fy in seen_fy:
            continue
        seen_fy.add(fy)
        pl, why = jp_pl(txt)
        if pl is None:
            notes.append('%s（FY%d）%s' % (d, fy, why))
            if '売上原価の行も無い' in why:
                return None, [], why + '（%s・FY%d）' % (d, fy)
            continue
        (rp, gpp), (rc, gpc), head = pl
        for yy, (r_, g_) in ((fy, (rc, gpc)), (fy - 1, (rp, gpp))):
            if yy not in got and r_ and r_ > 0 and g_ is not None:   # 新しい有報の値を先に採る（docID は新しい順）
                v = g_ / r_
                if -1 <= v <= 1:
                    got[yy] = {'y': yy, 'gm': round(v * 100, 2), 'rev': r_, 'gp': g_, 'doc': d, 'fy': fy, 'head': head}
    det = [got[y] for y in W if y in got]
    if len(det) < NEED:
        if flaky:
            raise Transient('有報PDFを取れない: %s' % '／'.join(flaky[:3]))
        return None, det, '窓 %d〜%d 年で粗利率が測れた年が %d 年（3年に届かない）%s' % (W[0], W[-1], len(det), ('／' + '／'.join(notes[:3])) if notes else '')
    g = round(statistics.median(x['gm'] for x in det), 1)
    return g, det, 'EDINET 有報PDF'


# ─────────────────────────── 本体 ───────────────────────────
def cik_maps():
    sic = json.load(open(os.path.join(BASE, 'out', '_sic_cache.json')))
    cikx = {}
    p = os.path.join(BASE, 'out', '_cik_tickers.json')
    for i in range(4):
        try:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(
                'https://www.sec.gov/files/company_tickers.json', headers=HDRS), timeout=60).read())
            cikx = {str(v.get('ticker', '')).upper(): v.get('cik_str') for v in j.values()}
            json.dump(cikx, open(p, 'w'))
            break
        except Exception:
            time.sleep(3 * (i + 1))
    if not cikx and os.path.exists(p):
        cikx = json.load(open(p))
    bycik = json.load(open(os.path.join(BASE, 'out', 'sic_by_cik.json')))
    return sic, cikx, bycik


def cik_from_pack(pack):
    """パックの _meta.source（審査に使った SEC の提出書類の URL）から CIK を読む。
    ティッカーの一覧に無い社（社名・ティッカーの変更直後・一覧の取りこぼし）の控え。
    evidence は他社の提出書類も引くので読まない"""
    m = re.search(r'edgar/data/(\d+)/', str((pack.get('_meta') or {}).get('source') or ''))
    return int(m.group(1)) if m else None


def is_jp_ticker(t):
    return bool(re.fullmatch(r'\d{4}[A-Z]?', t))


def main():
    write = '--write' in sys.argv
    only = None
    if '--only' in sys.argv:
        only = {x.strip().upper() for x in sys.argv[sys.argv.index('--only') + 1].split(',')}
    us_only, jp_only = '--us-only' in sys.argv, '--jp-only' in sys.argv
    sic, cikx, bycik = cik_maps()
    rows, changed, flaky = [], 0, []
    for f in sorted(glob.glob(os.path.join(BASE, 'out', '*_gate_pack.json'))):
        t = os.path.basename(f).replace('_gate_pack.json', '')
        if only and t.upper() not in only:
            continue
        jp = is_jp_ticker(t)
        if (us_only and jp) or (jp_only and not jp):
            continue
        d = json.load(open(f, encoding='utf-8'))
        m = d.setdefault('_meta', {})
        rd = str(m.get('reportDate') or '')
        g, det, why, src = None, [], '', ''
        try:
            if jp:
                g, det, why = jp_gpm(t, d, None)
                src = 'jp'
            else:
                ent = sic.get(t) or {}
                cik = ent.get('cik') or cikx.get(t.upper()) or cik_from_pack(d)
                s4 = ent.get('sic') or (bycik.get(str(int(cik))) if cik else None)
                if not cik:
                    if not cikx:
                        raise Transient('SEC のティッカーの一覧を取れず、控えも無い')
                    why = 'ティッカーから CIK を解決できない（SEC の XBRL に現れない社・_meta.source にも SEC の URL が無い）'
                elif s4 and str(s4).startswith('6'):
                    why = '金融・不動産（SIC %s）＝検定の母集団の外（粗利率が事業の質を表さない）' % s4
                else:
                    facts = facts_of(cik)
                    if facts is None:
                        why = 'SEC に XBRL の companyfacts が無い（CIK %s）' % cik
                    else:
                        g, det, why = sec_gpm(facts, rd)
                src = 'sec'
        except Transient as e:
            flaky.append((t, str(e)))        # 取れない＝測れない、ではない。パックには何も書かない（前の値も理由も残す）
            continue
        if g is not None:
            if src == 'sec':
                yrs = ' / '.join('%d %.1f%%%s' % (x['y'], x['gm'], '' if x['how'] == 'GrossProfit' else '（' + x['how'] + '）') for x in det)
                ev = ('粗利率（粗利÷売上）の直近5会計年度の中央値 = %.1f%%（%d年: %s）。帯 %d（<26.8→50／26.8〜44.0→70／≥44.0→85）。'
                      '原本: SEC XBRL companyfacts（%s・売上 %s・粗利 GrossProfit〔無い年は 売上−原価〕・様式 %s）。night/fill_gpm.py'
                      % (g, len(det), yrs, band(g), why, det[-1]['revTag'], det[-1]['form']))
            else:
                yrs = ' / '.join('%d %.1f%%' % (x['y'], x['gm']) for x in det)
                docs = sorted({'%s(FY%d)' % (x['doc'], x['fy']) for x in det}, reverse=True)
                last = det[-1]
                ev = ('粗利率（売上総利益÷売上高）の直近5会計年度の中央値 = %.1f%%（%d年: %s）。帯 %d（<26.8→50／26.8〜44.0→70／≥44.0→85）。'
                      '原本: EDINET 有報PDF %s の%s（直近 FY%d: 売上 %s ／ 売上総利益 %s）。同じ年が複数の有報にあれば新しい有報の値。night/fill_gpm.py'
                      % (g, len(det), yrs, band(g), ' / '.join(docs), last['head'], last['y'], format(last['rev'], ',.0f'), format(last['gp'], ',.0f')))
            rows.append((t, g, ev))
            if write and (d.get('gpm') != g or (m.get('evidence') or {}).get('gpm') != ev):
                d['gpm'] = g
                m.setdefault('evidence', {})['gpm'] = ev
                m.setdefault('provenance', {})['gpm'] = 'machine'
                (m.get('nulls') or {}).pop('gpm', None)
                json.dump(d, open(f, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                changed += 1
        else:
            reason = '粗利率を測れない: ' + why
            rows.append((t, None, reason))
            if write:
                hit = False
                if d.get('gpm') is not None and (m.get('provenance') or {}).get('gpm') == 'machine':
                    d.pop('gpm', None)
                    (m.get('evidence') or {}).pop('gpm', None)
                    (m.get('provenance') or {}).pop('gpm', None)
                    hit = True
                if d.get('gpm') is None and (m.setdefault('nulls', {})).get('gpm') != reason:
                    m['nulls']['gpm'] = reason
                    hit = True
                if hit:
                    json.dump(d, open(f, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                    changed += 1
    ok = [r for r in rows if r[1] is not None]
    from collections import Counter
    c = Counter(band(r[1]) for r in ok)
    print('対象 %d社／埋まった %d社（帯 50:%d / 70:%d / 85:%d）／空欄 %d社' % (len(rows), len(ok), c[50], c[70], c[85], len(rows) - len(ok)))
    print('空欄の社（測れないことで得をする向きがあり得る＝名指しする）:')
    for t, g, ev in rows:
        if g is None:
            print('  %-6s %s' % (t, ev[:160]))
    if '--list' in sys.argv:
        for t, g, ev in rows:
            if g is not None:
                print('  %-6s %5.1f%% 帯%d  %s' % (t, g, band(g), ev[:200]))
    if flaky:
        print('取れなかった社 %d社（通信の一時的な失敗＝測れない、ではない。パックには何も書いていない・前の値と理由はそのまま。もう一度回す）:' % len(flaky))
        for t, why in flaky:
            print('  %-6s %s' % (t, why[:160]))
    print('書き込み %d社%s' % (changed, '' if write else '（--write で反映）'))
    return 2 if flaky else 0


if __name__ == '__main__':
    sys.exit(main())
