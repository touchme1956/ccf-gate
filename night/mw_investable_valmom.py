#!/usr/bin/env python3
"""night/mw_investable_valmom.py — 『市場に勝てる歴史検証』(mw) の角度 investable_valmom（読むだけ・門の判定には不使用）

問い: プログラムでいちばん頑丈だった勝ち＝米国外の国の中の『割安＋勢い』（JKP world_ex_us・上限なし時価加重・
      保有 2007〜 +2.18%/年 t4.62・40/40か国）を、この投資家（日本の個人・楽天証券・NISA・毎月積立・
      いま ETF 側は NASDAQ100 と SMH）が実際に買える器で取れるか。取れないならそれを示す。
事前登録: out/mw_investable_valmom_prereg.json（線は out/mw_prereg.json）。出力: out/mw_investable_valmom.json
使い方: python3 night/mw_investable_valmom.py

族
  P  買える器（楽天の海外ETF・日本の投信）× 自然な相手（格付け・族の Holm）
  R  買えない器（参考・格付け・族の Holm）: 紙の上乗せが実在の器でどれだけ取れたか
  K  紙（JKP の割安＋勢い・5地域）: world_ex_us は既知の値の再現
  E1 探索: 買える器14本の重みで紙を写す（毎年7月・直前60か月・0以上合計1）
  E2 探索: 日本の中の割安（高配当・質）を円・NISA の器で（相手 TOPIX ETF）
  I  投資家の単位（報告だけ）: ETF 側の 10/20/30% を置き換えた円の毎月積立
  F  前向き（報告だけ）: 1990〜2025 の揺れを借りた復元抽出＋仮定の平均
"""
import collections, csv, datetime, http.cookiejar, io, json, math, os, statistics as S, subprocess, sys, time, urllib.parse, urllib.request, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mw_common as M
import numpy as np

PRE_NAME = 'mw_investable_valmom_prereg.json'
OUT_NAME = 'mw_investable_valmom.json'
PRE = json.load(open(os.path.join(M.BASE, 'out', PRE_NAME)))
NOW_YM = datetime.date.today().year * 100 + datetime.date.today().month
JKP_END = 202512
START2, RMIN, NMIN = 199007, 0.4, 10
VALUE4 = ['be_me', 'ni_me', 'ocf_me', 'div12m_me']
DEVELOPED = {'aus', 'aut', 'bel', 'can', 'che', 'deu', 'dnk', 'esp', 'fin', 'fra', 'gbr', 'hkg', 'irl', 'isr', 'ita', 'jpn',
             'nld', 'nor', 'nzl', 'prt', 'sgp', 'swe', 'usa'}
REGIONS = ['world_ex_us', 'developed', 'emerging', 'jpn', 'world']
PAPER_COST = 0.00725          # PXF の経費率 0.44% ＋ 回転率 0.95 × 片道 0.30%
NISA_DRAG = 0.0032            # PXF の分配利回り 3.24% × 米国源泉税 10%
S3 = 'https://jkpfactors-data.s3.amazonaws.com/public/'
ITA_BASE = 'https://toushin-lib.fwg.ne.jp'


def sha_of(path):
    try:
        return subprocess.run(['git', '-C', M.BASE, 'log', '-1', '--format=%H', '--', path], capture_output=True, text=True).stdout.strip() or None
    except Exception:  # noqa
        return None


def prev_ym(m):
    y, mo = divmod(m, 100)
    return (y - 1) * 100 + 12 if mo == 1 else m - 1


def add_months(m, k):
    y, mo = divmod(m, 100)
    t = y * 12 + (mo - 1) + k
    return (t // 12) * 100 + t % 12 + 1


def r2(x, n=2):
    return None if x is None else round(x, n)


# ───────────────────────── 取得: 為替・French・JKP ─────────────────────────
def fx_monthend():
    txt = M.get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXJPUS', name='fred_DEXJPUS.csv', max_age_days=30).decode()
    out = {}
    for line in txt.splitlines()[1:]:
        p = line.split(',')
        if len(p) < 2:
            continue
        try:
            v = float(p[1])
        except ValueError:
            continue  # 欠測（'.'）は飛ばす＝0 にしない
        out[int(p[0][:4]) * 100 + int(p[0][5:7])] = v
    return out


def to_jpy(r, fx):
    out = {}
    for m, v in r.items():
        p = prev_ym(m)
        if m in fx and p in fx:
            out[m] = (1 + v) * fx[m] / fx[p] - 1
    return out


def country_nstocks():
    b = M.get(S3 + '%5Ball_countries%5D_%5Bmkt%5D_%5Bmonthly%5D_%5Bvw%5D.zip', name='jkp_factor_all_countries_mkt_vw_monthly.zip')
    z = zipfile.ZipFile(io.BytesIO(b))
    ns = collections.defaultdict(dict)
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        if x['n_stocks'] not in ('', 'NA', 'na'):
            ns[x['location']][M._ym(x['date'])] = int(float(x['n_stocks']))
    return dict(ns)


def pf_needed(loc, names):
    """all_factors の三分位のうち names だけ → {特性: {pf: {ym: (ret, n)}}}"""
    out = {k: collections.defaultdict(dict) for k in names}
    for x in M.jkp_rows(loc, 'all_factors', 'portfolios', 'vw'):
        k = x['name']
        if k not in out or x['ret'] in ('', 'NA', 'na'):
            continue
        out[k][x['pf']][M._ym(x['date'])] = (float(x['ret']), int(float(x['n'])) if x['n'] not in ('', 'NA', 'na') else 0)
    return {k: dict(v) for k, v in out.items()}


def select(pf, side, den, start=START2, rmin=RMIN, nmin=NMIN):
    """mw_intl F2b と同じ規則: 1990-07 以降・被覆率 R≥0.4・良い側 n≥10"""
    if not pf or side not in pf:
        return {}
    out = {}
    for m, (r, n) in pf[side].items():
        if n < nmin or m < start:
            continue
        tot = sum(pf[q][m][1] for q in pf if m in pf[q])
        d = den.get(m)
        if not d or tot / d < rmin:
            continue
        out[m] = r
    return out


def build_paper(rf):
    good = json.load(open(os.path.join(M.BASE, 'out', 'mw_intl.json')))['good_side']
    cn = country_nstocks()

    def den(pred):
        c = collections.Counter()
        for loc, d in cn.items():
            if pred(loc):
                for m, n in d.items():
                    c[m] += n
        return dict(c)
    DEN = {'world_ex_us': den(lambda l: l != 'usa'), 'developed': den(lambda l: l in DEVELOPED and l != 'usa'),
           'emerging': den(lambda l: l not in DEVELOPED), 'world': den(lambda l: True), 'jpn': dict(cn.get('jpn', {}))}
    P = {}
    for reg in REGIONS:
        pf = pf_needed(reg, VALUE4 + ['ret_12_1'])
        parts = [select(pf[k], good[k], DEN[reg]) for k in VALUE4]
        ms = set.intersection(*[set(p) for p in parts]) if all(parts) else set()
        vc = {m: S.mean(p[m] for p in parts) for m in ms}
        mo = select(pf['ret_12_1'], good['ret_12_1'], DEN[reg])
        vm = {m: 0.5 * vc[m] + 0.5 * mo[m] for m in vc if m in mo}
        mk = M.jkp_mkt(reg, 'vw')
        P[reg] = {'vm': vm, 'vc': vc, 'mom': mo, 'mkt': mk,
                  'vm_tot': {m: v + rf[m] for m, v in vm.items() if m in rf}, 'mkt_tot': {m: v + rf[m] for m, v in mk.items() if m in rf},
                  'act': {m: vm[m] - mk[m] for m in vm if m in mk}, 'act_vc': {m: vc[m] - mk[m] for m in vc if m in mk and m in vm},
                  'act_mom': {m: mo[m] - mk[m] for m in mo if m in mk and m in vm}}
    return P, good


def french_vw(name):
    for t, v in M.french_tables(name).items():
        if v['freq'] == 'monthly' and 'value weight' in t.lower():
            return {c: {d: row[i] / 100 for d, row in v['data'].items() if row[i] is not None} for i, c in enumerate(v['cols'])}
    raise KeyError(name)


def french_mkt(name):
    for t, v in M.french_tables(name).items():
        if v['freq'] == 'monthly' and 'Mkt-RF' in v['cols']:
            i, j = v['cols'].index('Mkt-RF'), v['cols'].index('RF')
            return {d: (row[i] + row[j]) / 100 for d, row in v['data'].items() if row[i] is not None and row[j] is not None}
    raise KeyError(name)


# ───────────────────────── 取得: Yahoo（ETF・米国の投信） ─────────────────────────
MUTUAL = {'DFIVX', 'DISVX', 'DFEVX', 'DFALX', 'DFISX', 'DFEMX', 'VTRIX', 'VGTSX', 'OAKIX', 'DODFX', 'FIVLX'}
_OP = {}


def ms_annual(t):
    """Yahoo quoteSummary fundPerformance の Morningstar 年次総リターン → {年: 小数}（mw_reality_gap と同じ取り方・キャッシュ共有）"""
    p = os.path.join(M.CACHE, f'rg_ms_{t}.json')
    if not (os.path.exists(p) and os.path.getsize(p) > 0 and time.time() - os.path.getmtime(p) < 30 * 86400):
        try:
            if 'op' not in _OP:
                cj = http.cookiejar.CookieJar()
                op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
                ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
                op.addheaders = [('User-Agent', ua), ('Accept', 'text/html'), ('Accept-Language', 'en-US,en;q=0.9')]
                op.open('https://finance.yahoo.com/quote/SPY/', timeout=60).read()
                op.addheaders = [('User-Agent', ua), ('Accept', '*/*')]
                crumb = None
                for i in range(6):
                    try:
                        crumb = op.open('https://query1.finance.yahoo.com/v1/test/getcrumb', timeout=60).read().decode(); break
                    except Exception:  # noqa
                        time.sleep(10 * (i + 1))
                _OP['op'], _OP['crumb'] = op, crumb
            b = _OP['op'].open(f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(t)}?modules=fundPerformance&crumb={_OP['crumb']}", timeout=60).read()
            tmp = f'{p}.{os.getpid()}.tmp'
            open(tmp, 'wb').write(b); os.replace(tmp, p)
        except Exception:  # noqa
            return {}
    try:
        rets = json.load(open(p))['quoteSummary']['result'][0]['fundPerformance']['annualTotalReturns']['returns']
    except Exception:  # noqa
        return {}
    return {int(x['year']): x['annualValue']['raw'] for x in rets if x.get('annualValue', {}).get('raw') is not None}


def ms_correct(m, ms, thr=1.0):
    out, fixed = dict(m), {}
    for y, v in ms.items():
        ks = [k for k in range(y * 100 + 1, y * 100 + 13) if k in m]
        if len(ks) < 12:
            continue
        a = (math.prod(1 + m[k] for k in ks) - 1) * 100
        if abs(a - v * 100) <= thr:
            continue
        k = ((1 + v) / (1 + a / 100)) ** (1 / 12)
        for mm in ks:
            out[mm] = (1 + out[mm]) * k - 1
        fixed[y] = [round(a, 2), round(v * 100, 2)]
    return out, fixed


YCACHE, MSFIX = {}, {}


def yh(t):
    if t in YCACHE:
        return YCACHE[t]
    r = {k: v for k, v in M.yahoo(t).items() if k < NOW_YM}
    if t in MUTUAL:
        ms = ms_annual(t)
        if ms:
            r, fixed = ms_correct(r, ms)
            MSFIX[t] = {'fixed_years': fixed, 'morningstar_years': len(ms)}
        else:
            MSFIX[t] = {'note': 'Morningstar 年次が取れず生のまま（分配の取りこぼしの疑いを直せていない）'}
    YCACHE[t] = r
    return r


# ───────────────────────── 取得: 投資信託協会（日本の投信・東証ETF の基準価額） ─────────────────────────
ITA = {  # 名前: (ISIN, 協会コード, 検索語〔メタ情報用〕)
    'JP:iFree新興国RAFI': ('JP90C000DVR8', '0431R169', 'ｉＦｒｅｅ新興国株式インデックス'),
    'JP:DCダイワ新興国ファンダメンタル': ('JP90C0007479', '04311107', 'ＤＣダイワ新興国株式ファンダメンタル'),
    'JP:SMT新興国': ('JP90C0005Z76', '6431208C', 'ＳＭＴ新興国株式インデックス'),
    'JP:海外株式コクサイ': ('JP90C0003ZV8', '0231C01A', 'インデックスファンド海外株式'),
    'JP:グローバル・バリュー・オープン': ('JP90C0003DB7', '0131496B', 'グローバル・バリュー・オープン'),
    'JP:ハリスグローバルバリュー株(年1)': ('JP90C0002AE9', '68311003', 'ハリスグローバルバリュー'),
    'JP:フィデリティ・オールカントリー割安好配当(年4)': ('JP90C0003619', '3231105B', 'フィデリティ・オールカントリー'),
    'JP:アムンディGサステナブル・バリュー(年2・ヘッジなし)': ('JP90C000ALA1', '58311147', 'アムンディ・グローバル・サステナブル・バリュー'),
    'JP:ワールド・バリュー・アロケーションB': ('JP90C0008ET6', '58312127', 'ワールド・バリュー・アロケーション'),
    'JP:ダイワFEグローバル・バリュー(ヘッジなし)': ('JP90C000DJ98', '04312167', 'ダイワＦＥグローバル・バリュー'),
    'JP:フィデリティ世界割安成長株B': ('JP90C000JW79', '32312203', 'フィデリティ・世界割安成長株投信'),
    'JP:世界高配当株式ファンド(資産成長型)': ('JP90C0005YG7', '0231408B', '世界高配当株式ファンド'),
    'JP:グローバル高配当株式ファンド(奇数月)': ('JP90C00021U0', '0231105B', 'グローバル高配当株式ファンド'),
    'JP:SMT欧州株配当貴族': ('JP90C000FL19', '6431317B', 'ＳＭＴ欧州株配当貴族'),
    'JP:TOPIX1306': ('JP3027630007', '01312017', 'ＴＯＰＩＸ連動型上場投信'),
    'JPE:1698日本高配当(東証配当フォーカス100)': ('JP3047170000', '02311105', '東証配当フォーカス'),
    'JPE:1577野村日本株高配当70': ('JP3047560002', '01313133', '野村日本株高配当７０'),
    'JPE:1478 iシェアーズMSCIジャパン高配当': ('JP3048150001', '4831415A', 'ジャパン高配当利回り'),
    'JPE:eMAXIS JAPANクオリティ150': ('JP90C000CGC3', '0331115B', 'ＪＡＰＡＮクオリティ'),
    'JPE:SMT日本株配当貴族': ('JP90C000DPV2', '64316168', 'ＳＭＴ日本株配当貴族'),
    'JPE:日経平均高配当利回り株ファンド': ('JP90C000H373', '0331118B', '日経平均高配当利回り株ファンド'),
    'JPE:アクティブバリューオープン': ('JP90C0003A28', '10311962', 'アクティブバリューオープン'),
    'JPE:ストラテジック・バリュー・オープン': ('JP90C0002PX7', '01311007', 'ストラテジック・バリュー・オープン'),
    'JPE:ダイワ・バリュー株・オープン': ('JP90C0003PK2', '04311002', 'ダイワ・バリュー株・オープン'),
    'JPE:フィデリティ・日本バリュー': ('JP90C00035L9', '32311022', 'フィデリティ・日本バリュー'),
    'JPE:三井住友DS日本バリュー株': ('JP90C0002LS6', '79314997', '日本バリュー株ファンド'),
    'JPE:三菱UFJバリューオープン': ('JP90C0000PH4', '03313009', '三菱ＵＦＪバリューオープン'),
    'JPE:日興アクティブバリュー': ('JP90C00020W8', '0231197A', '日興アクティブバリュー'),
    'JPE:DCつみたてアクティブバリューオープン': ('JP90C00039C0', '10311031', 'ＤＣつみたてアクティブバリュー'),
    'JPE:日本バリュースターオープン': ('JP90C0001YW3', '0931105B', '日本バリュースターオープン'),
    'JPE:日興ジャパン高配当株式': ('JP90C0005LU5', '02311085', '日興ジャパン高配当株式'),
    'JPE:One割安日本株(年1)': ('JP90C0009YG9', '4731213C', 'Ｏｎｅ割安日本株ファンド'),
}


class ItaLib:
    """投資信託協会 投信総合検索ライブラリー。User-Agent に個人の連絡先を載せない（mw_common の UA）"""
    def __init__(self):
        cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        self.op.addheaders = [('User-Agent', M.UA['User-Agent'])]
        self.op.open(ITA_BASE + '/FdsWeb/FDST000000', timeout=60).read()

    def search(self, kw):
        fields = ['s_investAssetKindCd', 's_investArea3kindCd', 's_instCd', 's_fdsInstCd', 's_dcFundCD', 't_investArea10kindCd', 't_investAssetKindCd',
                  't_instCd', 't_fdsInstCd', 's_investArea10kindCd', 's_setlFqcy', 's_dividend1y', 's_totalNetAssets', 's_nowToRedemptionDate',
                  's_establishedDateToNow', 's_isinCd']
        body = {f: [] for f in fields}
        body.update({'t_keyword': kw, 't_kensakuKbn': '1', 't_searchInfoFlag': '1', 'startNo': 0, 'draw': 1, 'searchBtnClickFlg': True})
        req = urllib.request.Request(ITA_BASE + '/FdsWeb/FDST999900/fundDataSearch', data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest',
                                              'Referer': ITA_BASE + '/FdsWeb/FDST999900', 'User-Agent': M.UA['User-Agent']})
        d = json.loads(self.op.open(req, timeout=60).read().decode())
        return (d.get('searchResultInfo') or {}).get('resultInfoMapList') or []

    def csv(self, isin, assoc):
        return self.op.open(f'{ITA_BASE}/FdsWeb/FDST030000/csv-file-download?isinCd={isin}&associFundCd={assoc}', timeout=120).read()


_ITA = {}
UNIT_FIX = {}


def ita_lib():
    if 'lib' not in _ITA:
        _ITA['lib'] = ItaLib()
    return _ITA['lib']


def ita_monthly(key):
    """基準価額と分配金（1万口あたり・決算日に分配落ち）から日次の総リターン指数 → 月末 → 月次（途中の今月は落とす）"""
    isin, assoc, _ = ITA[key]
    p = os.path.join(M.CACHE, f'ita_{isin}.csv')
    if not (os.path.exists(p) and os.path.getsize(p) > 1000 and time.time() - os.path.getmtime(p) < 7 * 86400):
        b = ita_lib().csv(isin, assoc)
        tmp = f'{p}.{os.getpid()}.tmp'
        open(tmp, 'wb').write(b); os.replace(tmp, p)
        time.sleep(0.6)
    rows = []
    for ln in open(p, 'rb').read().decode('shift_jis', 'replace').splitlines()[1:]:
        c = ln.split(',')
        if len(c) < 4 or '年' not in c[0]:
            continue
        try:
            nav = float(c[1])
        except ValueError:
            continue
        d = int(c[0][0:4]) * 10000 + int(c[0][5:7]) * 100 + int(c[0][8:10])
        dist = float(c[3]) if c[3].strip() not in ('', '-') else 0.0  # 空欄＝その日に分配が無い（欠測ではない）
        rows.append((d, nav, dist))
    rows.sort()
    tr, prev, last = None, None, {}
    for d, nav, dist in rows:
        if prev is None:
            tr = 1.0
        else:
            f = (nav + dist) / prev
            if f > 5 or f < 0.2:
                # 事後に見つけたデータの穴（結果ではなくデータの検算で直す）: 東証ETF の基準価額の単位が途中で変わる
                # （1478 は 2016-07-19 に 1口→100口あたり・1,692→170,799）。10 のべきで割り戻し、それでも外れる日は鎖を切る（0 と読まない）
                p10 = 10 ** round(math.log10(f))
                if 0.8 <= f / p10 <= 1.25:
                    UNIT_FIX.setdefault(key, []).append({'date': d, 'raw_ratio': round(f, 4), 'divided_by': p10})
                    f = f / p10
                else:
                    UNIT_FIX.setdefault(key, []).append({'date': d, 'raw_ratio': round(f, 4), 'action': '鎖を切る（この日から先を別の系列として扱わず、この月までで打ち切る）'})
                    break
            tr = tr * f
        prev = nav
        last[d // 100] = tr
    ks = sorted(k for k in last if k < NOW_YM)
    return {k: last[k] / last[p_] - 1 for p_, k in zip(ks, ks[1:]) if add_months(p_, 1) == k}


def ita_meta():
    p = os.path.join(M.CACHE, 'ita_meta_investable_valmom.json')
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 7 * 86400:
        return json.load(open(p))
    out = {}
    for key, (isin, assoc, kw) in ITA.items():
        try:
            hit = next((h for h in ita_lib().search(kw) if h.get('isinCd') == isin), None)
        except Exception as e:  # noqa
            hit, err = None, str(e)[:120]
        if hit:
            try:
                tr = float(hit.get('trustReward'))
            except (TypeError, ValueError):
                tr = None
            out[key] = {'isin': isin, 'name': hit.get('fundNm'), 'company': hit.get('entrustCmpNm'), 'established': str(hit.get('establishedDate'))[:10],
                        'trust_fee_ex_tax_pct': tr, 'trust_fee_incl_tax_pct': round(tr * 1.1, 4) if isinstance(tr, (int, float)) else None,
                        'net_assets_mil_jpy': hit.get('totalNetAssets'), 'nisa_tsumitate': hit.get('nisaFlg') in (1, '1'),
                        'nisa_growth': hit.get('nisaGrowthFlg') in (1, '1'), 'nisaFlg_raw': hit.get('nisaFlg'), 'nisaGrowthFlg_raw': hit.get('nisaGrowthFlg')}
        else:
            out[key] = {'isin': isin, 'note': '検索で ISIN が見つからず（メタ情報なし・推測で埋めない）'}
        time.sleep(0.5)
    json.dump(out, open(p, 'w'), ensure_ascii=False)
    return out


def rakuten_etfs():
    """楽天の ETF 一覧（ETFD.csv）→ {ティッカー: {er, yield, index}}。broker_lineup.json（2026-08-24）と両方で取扱を見る"""
    out = {}
    try:
        b = M.get('https://www.rakuten-sec.co.jp/web/market/search/etf_search/ETFD.csv', name='rakuten_ETFD.csv', max_age_days=7)
        for r in csv.reader(io.StringIO(b.decode('utf-8-sig', 'replace'))):
            if len(r) > 20:
                def fl(x):
                    try:
                        return float(x)
                    except ValueError:
                        return None
                out[r[1]] = {'er_pct': fl(r[5]), 'dist_yield_pct': fl(r[19]), 'index': r[4], 'currency': r[18]}
    except Exception as e:  # noqa
        out['_error'] = str(e)[:200]
    lineup = json.load(open(os.path.join(M.BASE, 'out', 'broker_lineup.json')))['etfs']
    return out, lineup


def sbi_list(tickers):
    """事後に足した情報（格付けには不使用）: SBI証券の米国株・ETF 取扱一覧の HTML に名前が載っているか"""
    try:
        t = M.get('https://search.sbisec.co.jp/v2/popwin/info/stock/pop6040_usequity_list.html', name='sbi_usequity_list.html', max_age_days=7).decode('shift_jis', 'replace')
    except Exception as e:  # noqa
        return {'_error': str(e)[:200]}
    import re
    return {k: bool(re.search(r'>\s*' + re.escape(k) + r'\s*<', t)) for k in tickers}


# ───────────────────────── 統計の小道具 ─────────────────────────
def ols_nw(y, X, lag=12):
    y, X = np.asarray(y, float), np.asarray(X, float)
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X)
    u = X * e[:, None]
    Sm = u.T @ u
    for L in range(1, lag + 1):
        G = u[L:].T @ u[:-L]
        Sm += (1 - L / (lag + 1)) * (G + G.T)
    se = np.sqrt(np.diag(XtXi @ Sm @ XtXi))
    r2_ = 1 - e.var() / y.var() if y.var() > 0 else None
    return b, b / se, r2_


def loading(s, b, reg, P):
    """器の上乗せ（器 − 相手）を紙の上乗せ（紙の割安＋勢い − 市場・同じ地域）に回帰（〜2025-12・NW t）"""
    pa = P[reg]
    ms = sorted(m for m in set(s) & set(b) & set(pa['act']) & set(pa['act_vc']) & set(pa['act_mom']) if m <= JKP_END)
    if len(ms) < 36:
        return {'months': len(ms), 'note': '36か月未満'}
    y = [s[m] - b[m] for m in ms]
    x = [pa['act'][m] for m in ms]
    b1, t1, rr1 = ols_nw(y, np.column_stack([np.ones(len(ms)), x]))
    b2, t2, rr2 = ols_nw(y, np.column_stack([np.ones(len(ms)), [pa['act_vc'][m] for m in ms], [pa['act_mom'][m] for m in ms]]))
    pm, vmn = S.mean(x) * 1200, S.mean(y) * 1200
    return {'months': len(ms), 'from': ms[0], 'to': ms[-1], 'region': reg,
            'one_factor': {'beta': r2(float(b1[1]), 3), 't_beta': r2(float(t1[1])), 'alpha_ann': r2(float(b1[0]) * 1200), 't_alpha': r2(float(t1[0])), 'r2': r2(rr1, 3)},
            'two_factor': {'beta_value': r2(float(b2[1]), 3), 't_value': r2(float(t2[1])), 'beta_mom': r2(float(b2[2]), 3), 't_mom': r2(float(t2[2])),
                           'alpha_ann': r2(float(b2[0]) * 1200), 't_alpha': r2(float(t2[0])), 'r2': r2(rr2, 3)},
            'paper_active_ann': r2(pm), 'vehicle_active_ann': r2(vmn), 'shortfall_ann': r2(pm - vmn), 'capture': r2(vmn / pm, 2) if pm else None,
            'corr': r2(M.corr(x, y), 3)}


def pair_eval(s, b, reg, P, turnover=0.0, unit=0.001):
    ms = sorted(set(s) & set(b))
    if len(ms) < 60:
        return {'months': len(ms), 'note': '重なりが60か月未満（評価しない）', 'from': ms[0] if ms else None, 'to': ms[-1] if ms else None}
    s, b = {m: s[m] for m in ms}, {m: b[m] for m in ms}
    out = {'months': len(ms), 'from': ms[0], 'to': ms[-1],
           'full': M.excess_stats(s, b), 'train': M.excess_stats(s, b, z=M.TRAIN_END), 'hold': M.excess_stats(s, b, a=M.HOLD_START),
           'recent': M.excess_stats(s, b, a=M.RECENT_START),
           'hold_net': M.excess_stats(M.apply_cost(s, turnover, unit), b, a=M.HOLD_START),
           'roll20': M.rolling(s, b, 20), 'dca20': M.dca(s, b, 20), 'dca10': M.dca(s, b, 10),
           'maxdd_s': r2(M.maxdd(s) * 100, 1), 'maxdd_b': r2(M.maxdd(b) * 100, 1), 'turnover_for_cost': turnover, 'unit_cost': unit}
    out['loading'] = loading(s, b, reg, P) if reg else None
    return out


def grade_family(res):
    hp = {k: (v.get('hold') or {}).get('p') for k, v in res.items() if v.get('hold')}
    hol = M.holm(hp)
    for k, v in res.items():
        if not v.get('full'):
            v['grade'], v['criteria'], v['holm_p'] = 'C', None, None
            v['grade_note'] = '評価できる重なりが無い（不合格側）'
            continue
        g, c = M.grade(v['full'], v['train'], v['hold'], v['roll20'], cost_hold=v['hold_net'], repl=None, family_holm_p=hol.get(k))
        v['grade'], v['criteria'], v['holm_p'] = g, c, hol.get(k)
        v['short_history_view（参考・格付けではない）'] = {'C2_hold_sign': c['C2_hold_sign'], 'C3_hold_t': c['C3_hold_t'], 'C6_net_cost': c['C6_net_cost'],
                                                     'family_holm_lt_0.05': (hol.get(k) is not None and hol.get(k) < 0.05),
                                                     'train_available': v['train'] is not None, 'roll20_available': v['roll20'] is not None}
    return hol


def simplex_ls(R, y, iters=20000):
    """min ||R w − y||²  s.t. w ≥ 0・Σw = 1（射影勾配）"""
    R, y = np.asarray(R, float), np.asarray(y, float)
    n = R.shape[1]
    w = np.full(n, 1.0 / n)
    L = 2 * np.linalg.eigvalsh(R.T @ R).max()

    def proj(v):
        u = np.sort(v)[::-1]; css = np.cumsum(u)
        rho = np.nonzero(u * np.arange(1, n + 1) > (css - 1))[0][-1]
        th = (css[rho] - 1) / (rho + 1)
        return np.maximum(v - th, 0)
    for _ in range(iters):
        g = 2 * R.T @ (R @ w - y)
        w2 = proj(w - g / L)
        if np.abs(w2 - w).max() < 1e-12:
            w = w2; break
        w = w2
    return w


def dca_dist(mix, cur, years, a=None, z=None):
    """毎月同額を years 年（起点を毎月ずらす）。最終資産の比（mix ÷ cur）と倍率（最終 ÷ 払い込み）"""
    ks = sorted(m for m in set(mix) & set(cur) if (a is None or m >= a) and (z is None or m <= z))
    n = years * 12
    rows = []
    for i in range(0, len(ks) - n + 1):
        w = ks[i:i + n]
        if add_months(w[0], n - 1) != w[-1]:
            continue  # 途中に抜けがある窓は使わない
        wm = wc = 0.0
        for k in w:
            wm = (wm + 1) * (1 + mix[k]); wc = (wc + 1) * (1 + cur[k])
        rows.append((w[0], wm / wc, wm / n, wc / n))
    if not rows:
        return None
    rat = sorted(r[1] for r in rows)
    q = lambda p: rat[min(len(rat) - 1, int(p * (len(rat) - 1) + 0.5))]
    worst = sorted(rows, key=lambda r: r[1])[:3]
    mm = sorted(r[2] for r in rows); mc = sorted(r[3] for r in rows)
    return {'windows': len(rows), 'first_start': rows[0][0], 'last_start': rows[-1][0], 'win_rate': r2(sum(1 for r in rat if r > 1) / len(rat), 3),
            'ratio_median': r2(q(0.5), 3), 'ratio_p10': r2(q(0.1), 3), 'ratio_worst': [worst[0][0], r2(worst[0][1], 3)],
            'ratio_best': [max(rows, key=lambda r: r[1])[0], r2(max(r[1] for r in rows), 3)],
            'worst3': [[r[0], r2(r[1], 3)] for r in worst],
            'multiple_mix_median': r2(mm[len(mm) // 2], 2), 'multiple_cur_median': r2(mc[len(mc) // 2], 2),
            'multiple_mix_worst': r2(mm[0], 2), 'multiple_cur_worst': r2(mc[0], 2)}


def ser_stats(r, a=None, z=None):
    ks = sorted(m for m in r if (a is None or m >= a) and (z is None or m <= z))
    if len(ks) < 24:
        return None
    x = [r[k] for k in ks]
    return {'from': ks[0], 'to': ks[-1], 'cagr': r2(M.cagr(x) * 100), 'vol': r2(S.stdev(x) * math.sqrt(12) * 100, 1), 'maxdd': r2(M.maxdd({k: r[k] for k in ks}) * 100, 1)}


# ───────────────────────── 族の組み立て ─────────────────────────
def get_series(name, fx):
    """器の名前 → 月次リターン（器の通貨）。COMBO は毎月戻す"""
    if name.startswith('COMBO:'):
        body = name[6:]
        if '(' in body:
            pair, wts = body.split('(')
            a_, b_ = pair.split('+'); wa, wb = [float(x) / 100 for x in wts.rstrip(')').split(':')]
        else:
            a_, b_ = body.split('+'); wa = wb = 0.5
        ra, rb = yh(a_), yh(b_)
        return {m: wa * ra[m] + wb * rb[m] for m in set(ra) & set(rb)}
    if name.startswith('JP:') or name.startswith('JPE:'):
        return ita_monthly(name)
    if name == 'VGK→円':
        return to_jpy(yh('VGK'), fx)
    return yh(name)


def run_family(members, fx, P, fam):
    res = {}
    for name, spec in members.items():
        cp, reg = spec[0], spec[1]
        try:
            s = get_series(name, fx)
            b = get_series(cp, fx)
            r = pair_eval(s, b, reg, P)
        except Exception as e:  # noqa
            r = {'error': str(e)[:300]}
        r['counterpart'] = cp
        r['paper_region'] = reg
        res[name] = r
        f, h = r.get('full') or {}, r.get('hold') or {}
        print(f'  [{fam}] {name} vs {cp}: {r.get("months")}か月 全 {f.get("ex_ann")} t{f.get("t")} 保 {h.get("ex_ann")} t{h.get("t")} '
              f'載り {((r.get("loading") or {}).get("one_factor") or {}).get("beta")}', flush=True)
    return res


def main():
    t0 = time.time()
    ff = M.ff_factors()
    rf, mkt_us = ff['rf'], ff['mkt']
    fx = fx_monthend()
    P, good = build_paper(rf)
    print('紙の地域', {k: (min(v['vm']), max(v['vm']), len(v['vm'])) for k, v in P.items()}, flush=True)
    out = {'tool': 'night/mw_investable_valmom.py', 'prereg': f'out/{PRE_NAME}', 'prereg_commit': sha_of(f'out/{PRE_NAME}'),
           'global_prereg': 'out/mw_prereg.json', 'generated': datetime.date.today().isoformat()}

    # ── 楽天・投信協会のメタ情報
    rk, lineup = rakuten_etfs()
    try:
        meta = ita_meta()
    except Exception as e:  # noqa
        meta = {'_error': str(e)[:200]}
    out['universe'] = {'rakuten_etfd_csv': {t: rk.get(t) for t in sorted(set(PRE['families']['P_buyable']['members']) | set(PRE['families']['R_reference']['members']) | {'VEA', 'EFA', 'VEU', 'SPDW', 'EEM', 'EWJ', 'ACWI', 'VGK', 'QQQ', 'SMH', 'IEMG', 'SCZ', 'DXJ'}) if not t.startswith(('JP', 'COMBO'))},
                       'in_broker_lineup_2026_08_24': {t: (t in lineup) for t in sorted(set(PRE['families']['P_buyable']['members']) | set(PRE['families']['R_reference']['members'])) if not t.startswith(('JP', 'COMBO'))},
                       'in_sbi_list_2026_09_28（事後に足した情報・格付けには不使用）': sbi_list(sorted(t for t in set(PRE['families']['P_buyable']['members']) | set(PRE['families']['R_reference']['members']) if not t.startswith(('JP', 'COMBO')))),
                       'ita_meta': meta, 'prereg_universe_notes': PRE['context_known_before_registering']['universe_found_before_registering']}

    # ── 族 K（紙）
    K = {}
    for reg in REGIONS:
        s, b = P[reg]['vm_tot'], P[reg]['mkt_tot']
        unit = 0.005 if reg == 'emerging' else 0.003
        r = pair_eval(s, b, None, P, turnover=0.95, unit=unit)
        r['hold_2x_cost'] = M.excess_stats(M.apply_cost(s, 0.95, unit * 2), b, a=M.HOLD_START)
        r['post_pub_2014'] = M.excess_stats(s, b, a=201401)
        K[f'paper:{reg}'] = r
        f, h = r.get('full') or {}, r.get('hold') or {}
        print(f'  [K] paper:{reg}: 全 {f.get("ex_ann")} t{f.get("t")} 保 {h.get("ex_ann")} t{h.get("t")}', flush=True)
    grade_family(K)

    # ── 族 P（買える）・R（参考）
    Pfam = run_family(PRE['families']['P_buyable']['members'], fx, P, 'P')
    grade_family(Pfam)
    Rmem = PRE['families']['R_reference']['members']
    Rfam = run_family(Rmem, fx, P, 'R')
    grade_family(Rfam)

    # ── 族 E1（買える器で紙を写す）
    U = ['PXF', 'IDHQ', 'DEM', 'DGS', 'DFJ', 'DFE', 'DEW', 'FGD', 'VEA', 'EEM', 'EWJ', 'VGK', 'VPL', 'EPP']
    UR = {t: yh(t) for t in U}
    E1 = {}
    for nm, reg, cp in (('E1a_dev', 'developed', 'VEA'), ('E1b_exus', 'world_ex_us', 'VEU')):
        tgt = P[reg]['vm_tot']
        port, wlog = {}, {}
        for Y in range(2013, 2026):
            fit = [add_months((Y - 5) * 100 + 7, i) for i in range(60)]
            if not all(m in tgt for m in fit) or not all(all(m in UR[t] for m in fit) for t in U):
                wlog[Y] = 'データ不足で飛ばす'
                continue
            Rm = np.array([[UR[t][m] for t in U] for m in fit]); yv = np.array([tgt[m] for m in fit])
            w = simplex_ls(Rm, yv)
            wlog[Y] = {t: round(float(x), 3) for t, x in zip(U, w) if x > 0.005}
            for i in range(12):
                m = add_months(Y * 100 + 7, i)
                if m >= NOW_YM or not all(m in UR[t] for t in U):
                    continue
                port[m] = float(sum(w[j] * UR[t][m] for j, t in enumerate(U)))
        r = pair_eval(port, yh(cp), reg, P)
        r['weights_by_july'] = wlog
        r['counterpart'], r['paper_region'] = cp, reg
        E1[nm] = r
        f, h = r.get('full') or {}, r.get('hold') or {}
        print(f'  [E1] {nm}: 全 {f.get("ex_ann")} t{f.get("t")} 載り {((r.get("loading") or {}).get("one_factor") or {}).get("beta")}', flush=True)
    grade_family(E1)

    # ── 族 E2（日本）
    E2mem = {k: ['JP:TOPIX1306', 'jpn'] for k in PRE['families']['E2_japan_home']['members']}
    E2 = run_family(E2mem, fx, P, 'E2')
    grade_family(E2)

    # ── 投資家の単位 I
    qqq, ndx, smh = yh('QQQ'), yh('^NDX'), yh('SMH')
    both = sorted(set(qqq) & set(ndx))
    d_hat = (M.cagr([qqq[m] for m in both]) - M.cagr([ndx[m] for m in both])) * 100 + 0.20
    chips = french_vw('49_Industry_Portfolios')['Chips']
    ndx_side = {m: (qqq[m] - 0.00295 / 12) if m in qqq else (ndx[m] + d_hat / 1200 - 0.00495 / 12) for m in set(ndx) | set(qqq)}
    semi_side = {m: smh[m] if m in smh else chips[m] - 0.0035 / 12 for m in set(chips) | set(smh) if m >= 198501}
    C_usd = {m: 0.75 * ndx_side[m] + 0.25 * semi_side[m] for m in set(ndx_side) & set(semi_side)}
    C_jpy = to_jpy(C_usd, fx)
    wx, dv = P['world_ex_us'], P['developed']
    pxf_load = (((Pfam.get('PXF') or {}).get('loading') or {}).get('one_factor') or {})
    beta_pxf, alpha_pxf = pxf_load.get('beta'), pxf_load.get('alpha_ann')
    fb = french_vw('Developed_ex_US_6_Portfolios_ME_BE-ME')['BIG HiBM']; fp = french_vw('Developed_ex_US_6_Portfolios_ME_Prior_12_2')['BIG HiPRIOR']
    dfivx, pxf = yh('DFIVX'), yh('PXF')
    rafi_em_jpy = ita_monthly('JP:DCダイワ新興国ファンダメンタル')
    nd = NISA_DRAG / 12
    V_usd = {
        'V0_exus_mkt': {m: wx['mkt_tot'][m] - 0.001 / 12 for m in wx['mkt_tot'] if m >= START2},
        'V1_paper': {m: wx['vm_tot'][m] - PAPER_COST / 12 - nd for m in wx['vm_tot']},
        'V2_paper_half': {m: wx['mkt_tot'][m] + 0.5 * wx['act'][m] - PAPER_COST / 12 - nd for m in wx['act'] if m in wx['mkt_tot']},
        'V3_pxf_like': ({m: dv['mkt_tot'][m] + alpha_pxf / 1200 + beta_pxf * dv['act'][m] - nd for m in dv['act'] if m in dv['mkt_tot']}
                        if beta_pxf is not None else {}),
        'V4_french_big': {m: 0.5 * fb[m] + 0.5 * fp[m] - PAPER_COST / 12 - nd for m in fb if m in fp},
        'V5_dfivx': dict(dfivx),
        'V6_pxf': {m: v - nd for m, v in pxf.items()},
    }
    V_jpy = {k: to_jpy(v, fx) for k, v in V_usd.items()}
    pj = V_jpy['V6_pxf']
    V_jpy['V7_pxf_rafiem'] = {m: 0.8 * pj[m] + 0.2 * rafi_em_jpy[m] for m in set(pj) & set(rafi_em_jpy)}
    ERAS = {'A_real': 200007, 'B_proxy': START2}
    I = {}
    for era, a in ERAS.items():
        Cj = {m: v for m, v in C_jpy.items() if m >= a and (era == 'B_proxy' or (m in qqq and m in smh))}
        I[era] = {'current': ser_stats(Cj), 'sleeves': {}}
        for vk, V in V_jpy.items():
            Vv = {m: v for m, v in V.items() if m >= a}
            ms = sorted(set(Vv) & set(Cj))
            if len(ms) < 120:
                I[era]['sleeves'][vk] = {'months': len(ms), 'note': '重なり120か月未満'}
                continue
            rec = {'from': ms[0], 'to': ms[-1], 'months': len(ms), 'sleeve': ser_stats({m: Vv[m] for m in ms}), 'current_same_months': ser_stats({m: Cj[m] for m in ms}),
                   'corr_with_current': r2(M.corr([Vv[m] for m in ms], [Cj[m] for m in ms]), 3), 'by_weight': {}}
            for w in (0.1, 0.2, 0.3):
                mix = {m: (1 - w) * Cj[m] + w * Vv[m] for m in ms}
                cur = {m: Cj[m] for m in ms}
                rec['by_weight'][f'w{int(w * 100)}'] = {'mix': ser_stats(mix), 'dca20': dca_dist(mix, cur, 20), 'dca15': dca_dist(mix, cur, 15), 'dca10': dca_dist(mix, cur, 10)}
            I[era]['sleeves'][vk] = rec
            d20 = (rec['by_weight']['w20'].get('dca20') or {})
            print(f'  [I] {era} {vk} w20: 20年 勝率 {d20.get("win_rate")} 中央 {d20.get("ratio_median")} 最悪 {d20.get("ratio_worst")}', flush=True)
    out['investor'] = {'eras': ERAS, 'ndx_div_estimate_pct': r2(d_hat, 3), 'pxf_alpha_beta_for_V3': {'alpha_ann': alpha_pxf, 'beta': beta_pxf}, 'results': I}

    # ── 前向き F
    ms = sorted(m for m in set(C_jpy) & set(to_jpy(wx['mkt_tot'], fx)) & set(wx['act']) if START2 <= m <= JKP_END)
    Xj = to_jpy(wx['mkt_tot'], fx)
    c = np.array([C_jpy[m] for m in ms]); x = np.array([Xj[m] for m in ms]); aa = np.array([wx['act'][m] for m in ms])
    E_A = float(aa.mean() * 1200)
    c0, x0, a0 = c - c.mean(), x - x.mean(), aa - aa.mean()
    rng = np.random.default_rng(20260928)
    NP, NB, BL = 5000, 20, 12
    starts = rng.integers(0, len(ms), size=(NP, NB))
    idx = ((starts[:, :, None] + np.arange(BL)[None, None, :]) % len(ms)).reshape(NP, NB * BL)
    cc, xx, ax = c0[idx], x0[idx], a0[idx]

    def dca_term(r):
        W = np.zeros(r.shape[0])
        for t in range(r.shape[1]):
            W = (W + 1) * (1 + r[:, t])
        return W
    k_base = 0.5 * beta_pxf if beta_pxf is not None else None
    ks = {'k0': 0.0, 'k_base': k_base, 'k_half': 0.5, 'k_full': 1.0}
    Fres = []
    Wc_cache = {}
    for gC in (-1, 0, 1):
        rC = cc + (7.0 + gC - 0.46) / 1200
        Wc = dca_term(rC)
        Wc_cache[gC] = Wc
        for gap in (-2, -1, 0, 1, 2):
            for kn, kv in ks.items():
                if kv is None:
                    continue
                rV = xx + kv * ax + (7.0 + gap + kv * E_A - 0.44 - 0.32) / 1200
                for w in (0.1, 0.2, 0.3):
                    Wm = dca_term((1 - w) * rC + w * rV)
                    rat = Wm / Wc
                    Fres.append({'g_C': gC, 'gap': gap, 'k': kn, 'k_value': r2(kv, 3), 'w': w, 'p_mix_wins': r2(float((rat > 1).mean()), 3),
                                 'ratio_median': r2(float(np.median(rat)), 3), 'ratio_p5': r2(float(np.percentile(rat, 5)), 3), 'ratio_p95': r2(float(np.percentile(rat, 95)), 3),
                                 'cur_multiple_median': r2(float(np.median(Wc / 240)), 2), 'mix_multiple_median': r2(float(np.median(Wm / 240)), 2)})
    base = [f for f in Fres if f['g_C'] == 0 and f['gap'] == 0 and f['k'] == 'k_base']
    # 歴史の米国外 − 米国の市場（文脈）
    us_j = M.jkp_mkt('usa', 'vw')
    gaps = {}
    for lab, a_, z_ in (('1990-07〜2025-12', START2, JKP_END), ('1990-07〜2006-12', START2, 200612), ('2007-01〜2025-12', 200701, JKP_END), ('2013-07〜2025-12', 201307, JKP_END)):
        k2 = sorted(m for m in set(wx['mkt']) & set(us_j) if a_ <= m <= z_)
        gaps[f'JKP world_ex_us − usa {lab}'] = r2((M.cagr([wx['mkt'][m] + rf[m] for m in k2]) - M.cagr([us_j[m] + rf[m] for m in k2])) * 100)
    try:
        import mw_intl_verify as V
        ind = V.french_intl('F-F_International_Indices', 'Not Reqd')['Ind_all']['Mkt']
        for lab, a_, z_ in (('1975-01〜2026-08', 197501, 202608), ('1975-01〜1989-12', 197501, 198912), ('1990-01〜2006-12', 199001, 200612), ('2007-01〜2026-08', 200701, 202608)):
            k2 = sorted(m for m in set(ind) & set(mkt_us) if a_ <= m <= z_)
            gaps[f'French EAFE − 米国 {lab}'] = r2((M.cagr([ind[m] for m in k2]) - M.cagr([mkt_us[m] for m in k2])) * 100)
    except Exception as e:  # noqa
        gaps['french_eafe_error'] = str(e)[:200]
    # 解析の目安: 基準の仮定での ETF 側の期待の年率差（算術・分散の効果を別に）
    sdC, sdV, rho = float(c.std() * math.sqrt(12)), float(np.std(x0 + (k_base or 0) * a0) * math.sqrt(12)), float(np.corrcoef(c0, x0 + (k_base or 0) * a0)[0, 1])
    analytic = {}
    if k_base is not None:
        dmu = (k_base * E_A - 0.44 - 0.32) - (-0.46)
        for w in (0.1, 0.2, 0.3):
            var_mix = (1 - w) ** 2 * sdC ** 2 + w ** 2 * sdV ** 2 + 2 * w * (1 - w) * rho * sdC * sdV
            analytic[f'w{int(w * 100)}'] = {
                'mean_diff_pct（算術の差 w×(μV−μC)）': r2(w * dmu, 3),
                'rebalance_bonus_pct（混ぜた幾何 − 両方の幾何の加重平均）': r2(w * (1 - w) * (sdC ** 2 + sdV ** 2 - 2 * rho * sdC * sdV) / 2 * 100, 3),
                'geo_diff_vs_current_pct（混ぜた幾何 − 今の幾何 ≈ w×Δμ ＋ (σC² − σmix²)/2）': r2(w * dmu + (sdC ** 2 - var_mix) / 2 * 100, 3),
                'note': '2026-09-28 事後に直した: 初版は rebalance_bonus だけを出していたが、今の配分との比較に要るのは geo_diff（揺れの小さくなる分の効果）。どちらも報告だけ'}
    # 事後（結果を見た後に足した感度・判定には使わない）: 今の ETF 側の揺れに見合う期待（CAPM の β）を置いたら
    post = {'label': '事後（初回の結果を見た後に足した感度・格付けにも前向きの基準にも使わない）'}
    ffm = {m: mkt_us[m] for m in C_usd if START2 <= m <= JKP_END and m in mkt_us}
    kk = sorted(ffm)
    cu = [C_usd[m] - rf[m] for m in kk]; mu_ = [mkt_us[m] - rf[m] for m in kk]
    beta_C = float(np.cov(cu, mu_)[0, 1] / np.var(mu_, ddof=1))
    post['beta_current_vs_us_mkt_usd_1990_2025'] = r2(beta_C, 3)
    post['g_C_if_capm（(β−1)×(7.0−3.0)）'] = r2((beta_C - 1) * 4.0, 2)
    be = []
    if k_base is not None:
        for gC in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
            rC = cc + (7.0 + gC - 0.46) / 1200
            rV = xx + k_base * ax + (7.0 + 0 + k_base * E_A - 0.44 - 0.32) / 1200
            Wc = dca_term(rC); Wm = dca_term(0.8 * rC + 0.2 * rV)
            rat = Wm / Wc
            be.append({'g_C': gC, 'gap': 0, 'k': 'k_base', 'w': 0.2, 'p_mix_wins': r2(float((rat > 1).mean()), 3), 'ratio_median': r2(float(np.median(rat)), 3)})
    post['break_even_scan_w20_gap0_kbase'] = be
    pxs = {}
    for cp in ('VEA', 'EFA', 'SPDW', 'SCHF', 'CWI', 'VEU'):
        try:
            b_ = yh(cp); s_ = yh('PXF')
            kx = sorted(set(s_) & set(b_))
            pxs[f'PXF vs {cp}'] = {'full': M.excess_stats({m: s_[m] for m in kx}, {m: b_[m] for m in kx}),
                                   'from_2013_07': M.excess_stats({m: s_[m] for m in kx}, {m: b_[m] for m in kx}, a=M.RECENT_START)}
        except Exception as e:  # noqa
            pxs[f'PXF vs {cp}'] = {'error': str(e)[:150]}
    post['pxf_counterpart_sensitivity'] = pxs
    out['post_hoc'] = post
    out['forward'] = {'months_used': [ms[0], ms[-1], len(ms)], 'E_A_paper_active_ann_pct': r2(E_A, 3), 'beta_pxf': beta_pxf, 'k_values': {k: r2(v, 3) for k, v in ks.items()},
                      'vol_current_jpy': r2(sdC * 100, 1), 'vol_sleeve_base_jpy': r2(sdV * 100, 1), 'corr_base': r2(rho, 3),
                      'analytic_base_gap0_gC0': analytic, 'history_exus_minus_us_cagr_pct': gaps, 'base_rows': base, 'grid': Fres}

    # ── 検算
    san = {}
    san['french_us_mkt_cagr_1926'] = r2(M.cagr(mkt_us) * 100)
    san['french_us_mkt_cagr_2007'] = r2(M.cagr(M.window(mkt_us, M.HOLD_START)) * 100)
    kw = K['paper:world_ex_us']
    san['paper_world_ex_us_reproduce'] = {'full': [(kw.get('full') or {}).get('ex_ann'), (kw.get('full') or {}).get('t')], 'hold': [(kw.get('hold') or {}).get('ex_ann'), (kw.get('hold') or {}).get('t')],
                                          'expected': {'full': [2.99, 6.10], 'hold': [2.18, 4.62]}}
    san['usdjpy_monthend'] = {str(k): fx.get(k) for k in (200706, 201110, 201506, 202512, 202608)}
    try:
        kok, acwi = ita_monthly('JP:海外株式コクサイ'), to_jpy(yh('ACWI'), fx)
        k2 = sorted(set(kok) & set(acwi))
        san['kokusai_fund_vs_acwi_jpy'] = {'months': len(k2), 'corr': r2(M.corr([kok[m] for m in k2], [acwi[m] for m in k2]), 3),
                                           'cagr_fund': r2(M.cagr([kok[m] for m in k2]) * 100), 'cagr_acwi_jpy': r2(M.cagr([acwi[m] for m in k2]) * 100)}
    except Exception as e:  # noqa
        san['kokusai_fund_vs_acwi_jpy'] = {'error': str(e)[:200]}
    san['ndx_dividend_estimate_pct'] = r2(d_hat, 3)
    san['morningstar_fix'] = MSFIX
    san['ita_unit_change_fix（事後に見つけたデータの穴）'] = UNIT_FIX
    san['no_lookahead'] = '紙は JKP の組み立て（t 月末の特性で t+1 月）。E1 の重みは7月の直前60か月だけ。器は実在の値'
    out['sanity'] = san

    # ── まとめ
    out['families'] = {'P_buyable': Pfam, 'R_reference': Rfam, 'K_paper': K, 'E1_replicate': E1, 'E2_japan_home': E2}
    tested = []
    for fam, res in out['families'].items():
        for k, v in res.items():
            tested.append({'name': k, 'family': fam, 'grade': v.get('grade'), 'criteria': v.get('criteria'), 'holm_p': v.get('holm_p'),
                           'counterpart': v.get('counterpart'), 'months': v.get('months'),
                           'full': [(v.get('full') or {}).get('ex_ann'), (v.get('full') or {}).get('t')],
                           'hold': [(v.get('hold') or {}).get('ex_ann'), (v.get('hold') or {}).get('t'), (v.get('hold') or {}).get('cagr_diff')],
                           'beta_paper': ((v.get('loading') or {}).get('one_factor') or {}).get('beta')})
    for era, e in I.items():
        for vk, rec in e['sleeves'].items():
            for w in (10, 20, 30):
                tested.append({'name': f'I:{era}:{vk}:w{w}', 'family': 'I_investor', 'grade': None, 'report_only': True})
    out['tested'] = tested
    out['n_tested'] = len(tested)
    out['n_graded'] = sum(1 for t in tested if t['grade'] is not None)
    out['grade_counts'] = dict(collections.Counter(t['grade'] for t in tested if t['grade'] is not None))
    out['deviations'] = [
        '事後に見つけたデータの穴: 投信協会の東証ETF の基準価額の単位が途中で変わる（1478 は 2016-07-19 に 1口→100口あたり）。初回の結果（1478 の超過 +971%/年）で気づき、日次の比が 5倍超・1/5未満のときは 10 のべきで割り戻す処理を足した（割っても外れる日は鎖を切る）。直したのは 1478 の1日だけ（sanity に記録）',
        '報告だけの解析値: 前向きの analytic は初版で rebalance_bonus（混ぜた幾何 − 両方の幾何の加重平均）だけを出していたが、今の配分との比較に要る geo_diff（揺れが小さくなる分を含む）を足した',
        '事後（格付けにも前向きの基準にも使わない）: PXF の相手を変えた感度（EFA・SPDW・SCHF・CWI・VEU）、今の ETF 側の β に見合う期待（CAPM）での前向きの感度と損益分岐の走査、SBI証券の取扱一覧の確認を足した',
        'メタ情報の直し: 投信協会の trustReward が文字列で来たので数値に直した（格付け・成績には無関係）',
        '取得: 登録前のデータの有無の確認で night/fetch_tsumitate_funds.py の Lib（User-Agent に利用者の連絡先が入っている）を使って投信協会に問い合わせた。本番の道具は mw_common の User-Agent（連絡先なし）に替えた',
        'mw_common.py は変更していない']
    fam_P = out['families']['P_buyable']
    pxf_r, ifr = fam_P.get('PXF') or {}, fam_P.get('JP:iFree新興国RAFI') or {}
    L = lambda r: ((r.get('loading') or {}).get('one_factor') or {})
    LL = lambda r: (r.get('loading') or {})
    ia = I['A_real']['sleeves']; ib = I['B_proxy']['sleeves']
    d20 = lambda d, v, w='w20': ((d.get(v) or {}).get('by_weight') or {}).get(w, {}).get('dca20') or {}
    bs = [f for f in Fres if f['g_C'] == 0 and f['gap'] == 0 and f['k'] == 'k_base' and f['w'] == 0.2]
    b0 = [f for f in Fres if f['g_C'] == 0 and f['gap'] == 0 and f['k'] == 'k0' and f['w'] == 0.2]
    out['summary_ja'] = [
        f"紙の『米国外の国の中の割安＋勢い』は再現した（全期間 +{K['paper:world_ex_us']['full']['ex_ann']}%/年 t{K['paper:world_ex_us']['full']['t']}・2007〜 +{K['paper:world_ex_us']['hold']['ex_ann']} t{K['paper:world_ex_us']['hold']['t']}）。",
        f"楽天で買える器の中で米国外の割安を実装しているのは PXF（基本指標加重）と iFree新興国株式（RAFI 新興国・つみたて枠）だけで、米国外の勢い（モメンタム）の器は楽天に1本も無い。",
        f"PXF は VEA に対して 2007〜 +{(pxf_r.get('hold') or {}).get('ex_ann')}%/年（t{(pxf_r.get('hold') or {}).get('t')}）。紙の上乗せへの載り β{L(pxf_r).get('beta')}・同じ月の紙 +{LL(pxf_r).get('paper_active_ann')} に対し器 +{LL(pxf_r).get('vehicle_active_ann')}＝取れたのは約{int(round((LL(pxf_r).get('capture') or 0) * 100))}%。割安の半分だけで、勢いの半分は逆向き。",
        f"iFree新興国（RAFI）は相手に +{(ifr.get('hold') or {}).get('ex_ann')}%/年（t{(ifr.get('hold') or {}).get('t')}）。日本の全世界アクティブ割安・高配当投信9本は全部コクサイ（円）に負けた（2007〜 −1.2〜−4.9%/年・信託報酬 税込0.76〜1.98%）。",
        '全体の線では買える器はすべて C（2007年以降に生まれ、訓練期間も20年窓も無い＝構造的）。紙以外で B は買えない DODFX だけ。',
        f"円の毎月積立: 今の ETF 側の20%を米国外（紙の割安＋勢いそのものでも）に替えると、2000〜2005年起点の20年窓はすべて負け（紙で中央 {d20(ia, 'V1_paper').get('ratio_median')}・最悪 {d20(ia, 'V1_paper').get('ratio_worst')}）。1990年起点の代理でも勝率 {d20(ib, 'V1_paper').get('win_rate')}（紙）・{d20(ib, 'V3_pxf_like').get('win_rate')}（PXF 型）。米国外の市場が米国に年約5%負けた差が上乗せを飲み込んだ。",
        f"前向き（紙の上乗せを半分×PXF の載り・米国外と米国の差0・今の側に上乗せの期待なし）: 20%置き換えで勝つ確率 {bs[0]['p_mix_wins'] if bs else None}・最終資産の中央 ×{bs[0]['ratio_median'] if bs else None}。ただし上乗せ抜き（k=0）でも ×{b0[0]['ratio_median'] if b0 else None}＝差のほとんどは揺れが小さくなる分で、割安＋勢いの上乗せの寄与は20年で約1%。今の側の揺れに見合う期待（事後・CAPM）を置くと勝つ確率は約6割まで下がる。"]
    out['runtime_sec'] = round(time.time() - t0, 1)
    p = M.save(OUT_NAME, out)
    print('→', p, out['grade_counts'], out['runtime_sec'], 's')


if __name__ == '__main__':
    main()
