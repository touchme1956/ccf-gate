#!/usr/bin/env python3
"""night/newfunds.py — 最近一年以内（2025-10-11〜2026-10-10）に出た投資信託・ETF の中に、このユーザー
（円・毎月積立・NISA・20〜30年・楽天証券）にとって『良いもの』があるか（読むだけ・門・配分・器には触れない）

2026-10-11 ユーザー「最近一年以内に出た投資信託やETFでいいものがないか探してみて。」
事前登録 out/newfunds_prereg.json（48c0e1f・選ぶ前に固定）。母集団・除外・賭けへの割り当て・E1〜E4・判定 G1/G2/G3/参考 はそこにあるとおり。

材料（日付の写真・キャッシュは out/_nx_cache/newfunds/〔gitignore〕）
  U1 投資信託協会 投信総合検索ライブラリーの全件（基準日 2026-10-09・5,850本・東証の ETF を含む）＝ jita_full.json
     trustReward は税抜（×1.1 で税込）。nisaFlg=1 つみたて投資枠・nisaGrowthFlg=1 成長投資枠・unitOpenDiv=1 単位型・
     dcFundFlg=1 DC 専用・setlFqcy=012 毎月決算・supplementKindCd=1 インデックス型・institutionInfo に販売会社（楽天証券と手数料）
  U2 楽天証券の海外 ETF の一覧 ETFD.csv（2026-10-11）＝ etfd.csv（列: 0 コード／1 ティッカー／2 名前／3 市場／4 指数／5 経費率／
     22 日本語名／24 純資産／25 単位／32 設定日／56 年の分配回数）。米国上場の本の最初の取引日は Yahoo の firstTradeDate（事前登録どおり）
  既存の器: out/bestfund_vehicles.json（H5 実測＝指数との差の年率＋取り戻せない外国税）／投信ライブラリーの窓より前の器（表の費用＋外国税）／
           night/bestfund_data.VEH（米国 ETF の表の費用・両替・外国税の係数 k と配当利回り dy）

  python3 night/newfunds.py            → out/newfunds.json（キャッシュがあれば取りに行かない）
  python3 night/newfunds.py --refresh  → 一覧を取り直す（基準日が変わる＝事前登録の写真と別物になる。判定は写真の日付つきで残る）

⚠ 新しい器は自分の記録が1年未満＝本当の費用（指数との差）は測れない。表の費用（信託報酬＋外国税）で比べるが、既存の器の多くは実測で、
  実測には表に出ない費用（売買・保管・為替の換算・基準価額の時刻のずれ）が入っている＝この比べ方は新しい器に有利に傾く。
  公平のため、表の費用どうしの比べ（既存も表の費用＋外国税）も並べる。
"""
import csv, datetime, hashlib, io, json, os, re, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import bestfund_data as D  # noqa: E402  費用の表（VEH・外国税の係数・配当利回り）

CACHE = os.path.join(BASE, 'out', '_nx_cache', 'newfunds')
JITA = os.path.join(CACHE, 'jita_full.json')
ETFD = os.path.join(CACHE, 'etfd.csv')
YHDIR = os.path.join(CACHE, 'yahoo')
OUT = os.path.join(BASE, 'out', 'newfunds.json')
VEHJ = os.path.join(BASE, 'out', 'bestfund_vehicles.json')
BESTJ = os.path.join(BASE, 'out', 'bestfund.json')
PREREG = 'out/newfunds_prereg.json（48c0e1f）'
WIN = ('2025-10-11', '2026-10-10')
UA = {'User-Agent': 'Mozilla/5.0 (ccf-gate research; contact via github touchme1956/ccf-gate)'}
ETFD_URL = 'https://www.rakuten-sec.co.jp/web/market/search/etf_search/ETFD.csv'
LINE = 0.05          # 事前登録 G1: 既存の最安の器より年0.05%以上安い
FX_FEE_PCT = 0.02    # 米国 ETF の両替（1ドル25銭を20年の積立で年0.02%・bestfund_data.FX_FEE と同じ）

# ── ユーザーが今持っている賭けと bestfund の上位3（事前登録 G1）。賭けごとに G1 で見る枠
HELD = {'NDX': 'NASDAQ100', 'SEMI_MV': '半導体（SMH の指数）', 'SEMI_SOX': '半導体（SOX 指数）', 'DEFENSE': '米国航空・防衛（ITA）'}
TOP3 = {'FANG': 'FANG+', 'SP500': 'S&P500', 'TECH_SPDR': '米国テクノロジー（XLK）'}
ACCTS = {'NDX': ('つみたて', '成長'), 'SP500': ('つみたて', '成長'), 'FANG': ('つみたて', '成長'),
         'SEMI_MV': ('成長',), 'SEMI_SOX': ('成長',), 'DEFENSE': ('成長',), 'TECH_SPDR': ('成長',)}
GROUP = {'SEMI_MV': ('SEMI_MV', 'SEMI_SOX'), 'SEMI_SOX': ('SEMI_MV', 'SEMI_SOX')}  # 半導体は SMH と SOX の器をまとめて既存として比べる

# ── 除外（事前登録の語のまま。偽の当たりは notes に名指しする）
LEV_JP = ['レバレッジ', 'ブル', 'ベア', 'インバース', '2倍', '3倍', 'ダブル', 'トリプル', 'ショート']
LEV_US = re.compile(r'(\b[23][xX]\b|-1[xX]\b|\b1[xX] Short|Bull|Bear|Ultra|Short|Inverse)')
WRAP = re.compile(r'(SMA|ラップ|EW向け|ファンドラップ|適格機関|私募)')
CCY = re.compile(r'(通貨選択|レアル|リラ|豪ドル|南アフリカ|ランドコース|ペソ|ルピー|ルピア|ルーブル|アジア通貨|資源国通貨|バスケット通貨|通貨コース|米ドルコース|ユーロコース|人民元|中国元)')
HEDGED = re.compile(r'(為替ヘッジあり|ヘッジあり|為替ヘッジ付|円ヘッジ|為替リスク軽減|ヘッジ型|米ドル売り円買い)')
DCNAME = re.compile(r'((?<![A-Za-z])DC(?![A-Za-z])|確定拠出|年金)')

# ── 賭けへの割り当て（bestfund の39の賭けの言葉。上から順に最初に当たったもの）。(賭け, 当てる, 外す)
JP_RULES = [
    ('NDX', r'(NASDAQ\s?-?100|ナスダック\s?100|QQQ)', r'(カバード|ゴールド|&|トップ|次世代|これ1本|QYLD)'),
    ('FANG', r'FANG', r'(ゴールド)'),
    ('SEMI_SOX', r'(SOX|フィラデルフィア半導体)', None),
    ('SEMI_MV', r'(MVIS|SMH)', None),
    ('EQW', r'S&P\s?500.*(イコール|均等)', None),
    ('SP500', r'S&P\s?500', r'(高配当|配当貴族|トップ|クオリティ|キャッシュフロー|ゴールド|プロテクション|除く金融|これ1本|半導体|プレミアム|トレンド|NYダウ)'),
    ('ACWI', r'(オール・?カントリー|ACWI)', r'(高配当|ゴールド|除く日本|モメンタム)'),
    ('KOKUSAI', r'(KOKUSAI|コクサイ|先進国株式\(除く日本\)|先進国株式インデックス)', r'(高配当|モメンタム|リーダー)'),
    ('EM', r'(新興国株式インデックス|エマージング株式インデックス)', r'(高配当)'),
    ('TOPIX', r'TOPIX', r'(高配当|ゴールド|アルファ|グロース|コア30|バリュー|REIT|銀行|トップ)'),
    ('N225', r'(日経225|日経平均)', r'(高配当|株主還元|トレンド|ねらって|半導体|銀行|エンタメ)'),
    ('SMALL', r'(ラッセル2000|Russell\s?2000)', None),
    ('INDIA', r'(Nifty|ニフティ)', None),
    ('GOLD', r'(ゴールド|金ETF|SPDRゴールド)', r'(株|鉱|ビジネス|プラス|インカム|&)'),
    ('DEFENSE_X', r'(防衛|航空宇宙|ディフェンス)', None),     # ITA（Dow Jones U.S. Select Aerospace & Defense）と同じ指数の器は窓に無い
    ('SEMI_X', r'(半導体|セミコン|メモリ)', None),              # SOX・SMH の指数ではない半導体（日本・韓国・中国・メモリ・全世界）
]
US_RULES = [
    ('NDX', r'(Nasdaq[- ]?100|NASDAQ[- ]?100)', r'(Covered|Income|Buffer|Top 30|Next Gen|Equal)'),
    ('SP500', r'S&P 500', r'(Equal|High Div|Dividend|Low Vol|Growth|Value|Quality|Momentum|Top|Buffer|Income|Covered|ex)'),
    ('SEMI_SOX', r'(PHLX Semiconductor|SOX)', None),
    ('SEMI_MV', r'(MVIS US Listed Semiconductor)', None),
    ('TECH_SPDR', r'Technology Select Sector', None),
    ('FANG', r'FANG', None),
    ('DEFENSE', r'(Select Aerospace & Defense)', None),
    ('SEMI_X', r'(Semiconductor|Memory|DRAM)', None),
]


def nfkc(s):
    return unicodedata.normalize('NFKC', s or '')


def key(s):
    """名前の照合用（全角→半角・空白と中黒の揺れを消す・<購入・換金手数料なし> のような添え書きを消す）"""
    return re.sub(r'[\s・]', '', re.sub(r'<[^>]*>', '', nfkc(s))).replace('（', '(').replace('）', ')')


def same_vehicle(a, b):
    """器の名前が同じか（bestfund_data.VEH の名前は（…）の注記を外して比べる。短い名前は完全一致だけ＝VT と VTI を混ぜない）"""
    ka, kb = key(re.sub(r'（[^）]*）', '', a)), key(re.sub(r'（[^）]*）', '', b))
    if ka == kb:
        return True
    return min(len(ka), len(kb)) >= 8 and (ka.startswith(kb) or kb.startswith(ka))


def fnum(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def sha256(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


# ═════════════════════════ 取得（キャッシュ） ═════════════════════════
def load_jita(refresh=False):
    if refresh or not os.path.exists(JITA):
        import nx_jpfunds_data as J
        rows, total, std = J.Lib().search_all()
        os.makedirs(CACHE, exist_ok=True)
        json.dump({'std': std, 'rows': rows}, open(JITA, 'w'), ensure_ascii=False)
    d = json.load(open(JITA))
    return d['std'], d['rows']


def load_etfd(refresh=False):
    if refresh or not os.path.exists(ETFD):
        b = urllib.request.urlopen(urllib.request.Request(ETFD_URL, headers=UA), timeout=120).read()
        os.makedirs(CACHE, exist_ok=True)
        open(ETFD, 'wb').write(b)
    return list(csv.reader(io.StringIO(open(ETFD, encoding='utf-8-sig').read())))


def yahoo_first(ticker):
    """Yahoo の firstTradeDate（取引所の現地日付）。取れなければ None（理由つき）。キャッシュ: yahoo/{T}.json"""
    os.makedirs(YHDIR, exist_ok=True)
    p = os.path.join(YHDIR, re.sub(r'[^A-Za-z0-9._-]', '_', ticker) + '.json')
    if os.path.exists(p):
        return json.load(open(p))
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}?range=5d&interval=1d'
    out = {'ticker': ticker, 'first': None, 'err': None}
    for i in range(3):
        try:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read())
            m = (j['chart']['result'] or [{}])[0].get('meta', {})
            ft = m.get('firstTradeDate')
            if ft is not None:
                off = m.get('gmtoffset') or 0
                out['first'] = datetime.datetime.utcfromtimestamp(ft + off).date().isoformat()
            else:
                out['err'] = 'firstTradeDate なし'
            break
        except urllib.error.HTTPError as e:
            out['err'] = f'HTTP {e.code}'
            if e.code in (404, 400):
                break
            time.sleep(2 ** (i + 1))
        except Exception as e:  # noqa
            out['err'] = str(e)[:120]
            time.sleep(2 ** (i + 1))
    time.sleep(0.25)
    json.dump(out, open(p, 'w'), ensure_ascii=False)
    return out


# ═════════════════════════ 規則 ═════════════════════════
def rakuten(r):
    """投信ライブラリーの販売会社から楽天証券の手数料（％）。None＝楽天で売っていない"""
    for i in r.get('institutionInfo') or []:
        if '楽天' in nfkc(i.get('instName')):
            return fnum(i.get('salesFee')) if fnum(i.get('salesFee')) is not None else 0.0
    return None


def is_etf_jp(r):
    return r.get('fundCategory') == '10' or (r.get('isinCd') or '').startswith('JP3')


def exclusions_jp(r):
    n = nfkc(r['fundNm'])
    why = []
    hit = [w for w in LEV_JP if w in n]
    if hit:
        why.append('レバレッジ・インバース（名前に「' + '・'.join(hit) + '」）')
    if r.get('setlFqcy') == '012' or '毎月' in n:
        why.append('毎月分配')
    if CCY.search(n):
        why.append('通貨選択型')
    if r.get('unitOpenDiv') == '1':
        why.append('単位型')
    if r.get('dcFundFlg') == '1':
        why.append('DC 専用')
    if WRAP.search(n):
        why.append('ファンドラップ／SMA／ラップ専用')
    return why


def bet_of(name, rules):
    for b, inc, exc in rules:
        if re.search(inc, name) and not (exc and re.search(exc, name)):
            return b
    return None


def classify_jp(r):
    """（賭け, 種類, 注記）。種類: 既存の賭け／為替ヘッジあり／組み合わせ／アクティブ／新しい指数／債券・マネー／REIT／その他の資産"""
    n = nfkc(r['fundNm'])
    sup, asset = r.get('supplementKindCd'), r.get('investAssetKindCd')
    b = bet_of(n, JP_RULES)
    if re.search(r'(ゴールドプラス|&ゴールド|ゴールド・プラス|FANG\+ゴールド|トレンドフォロー|\d資産|バランス|アロケーション|マルチアセット|これ1本|ゴール・サポート|ねらってそなえる|ポリシードライブ|プロテクト)', n) or asset == '5':
        return None, '組み合わせ', '2つ以上の賭け（株と金・債券など）を1本にした器'
    if HEDGED.search(n):
        return b, '為替ヘッジあり', 'ユーザーは為替をヘッジしない方針（2026-09-23 決定）'
    if asset == '2':
        return None, '債券・マネー', ''
    if asset == '3':
        return None, 'REIT', ''
    if asset == '4' and b == 'GOLD':
        return b, '既存の賭け', D.JA['GOLD'] + '（金の価格に連動。投信ライブラリーのインデックス型の印は無い）'
    if sup != '1':
        return b, 'アクティブ', '指数に連動しない（運用会社の判断で選ぶ）'
    if asset == '4' and b != 'GOLD':
        return None, 'その他の資産', '金以外のコモディティ・プライベート資産など'
    if b in D.VEH:
        return b, '既存の賭け', D.JA.get(b, b)
    if b in ('DEFENSE_X', 'SEMI_X'):
        return b, '新しい指数', {'DEFENSE_X': '防衛の別の指数（ITA の指数ではない）', 'SEMI_X': '半導体の別の指数（SOX・SMH の指数ではない）'}[b]
    return 'NEW', '新しい指数', ''


def classify_us(row):
    n, idx, ja = row[2], row[4], nfkc(row[22])
    b = bet_of(n + ' | ' + idx, US_RULES)
    if b in D.VEH:
        return b, '既存の賭け', D.JA.get(b, b)
    note = '' if idx.strip() else '楽天の一覧に指数の記載なし（アクティブ運用か、指数が載っていない）'
    if b == 'SEMI_X':
        return b, '新しい指数', ('半導体の別の指数（SOX・SMH の指数ではない）' + ('・' + note if note else ''))
    return 'NEW', '新しい指数', note


# ═════════════════════════ 費用 ═════════════════════════
def tax_pct(b):
    """NISA で取り戻せない配当の外国税（年%）＝ k×dy（bestfund_data.VEH）。賭けが表に無ければ None"""
    v = D.VEH.get(b)
    return round(100 * v['k'] * v['dy'], 4) if v else None


# 中で外国の ETF を買う器（投信ライブラリーの信託報酬に中の ETF の費用が入っていない）。名前の一部 → (中の ETF, 年%, 出所)
INNER = {
    'グローバルX防衛テックETF': ('SHLD', 0.50, 'out/defense_alts.json（466A＝SHLD を円で持つ・合計 0.5275%）'),
    'SBI・V・S&P500': ('VOO', 0.03, 'night/bestfund_data.VEH'),
    'SBI・インベスコQQQ': ('QQQM', 0.15, '名前（中で QQQ・QQQM）'),
    'インベスコQQQファンド': ('QQQ（587A）', 0.18, 'インベスコ・アセット・マネジメント（中で QQQ・合計 0.3175% 程度）'),
}
SUSPECT = re.compile(r'(グローバルX|SBI・V・|SBI・SPDR|SBI・iシェアーズ|SBIネクスト|SBI欧州|SBIエネルギー|楽天・全米|楽天・米国高配当|一歩先いく)')


def inner_of(name):
    k = key(name)
    for sub, v in INNER.items():
        if key(sub) in k:
            return v
    return None


def new_cost_jp(r, b):
    """新しい投信・東証 ETF の表の費用（年%・税込）＋中の ETF＋外国税"""
    n = nfkc(r['fundNm'])
    fee = fnum(r.get('trustReward'))
    fee_in = round(fee * 1.1, 4) if fee is not None else None
    inn = inner_of(n)
    tx = tax_pct(b) if b in D.VEH else None
    note = []
    if inn:
        note.append(f'中で {inn[0]}（{inn[1]}%）を買う＝投信ライブラリーの信託報酬に入っていない分を足した（{inn[2]}）')
    elif fee is not None and fee < 0.12 and SUSPECT.search(n) and r.get('investArea3kindCd') != '1':
        note.append('中で外国の ETF を買う形の可能性（その ETF の費用は投信ライブラリーの信託報酬に入っていない）＝表の費用は下限')
    tot = None
    if fee_in is not None and tx is not None:
        tot = round(fee_in + (inn[1] if inn else 0) + tx, 4)
    return {'listed_incl_tax': fee_in, 'inner': (inn[0], inn[1]) if inn else None, 'foreign_tax': tx, 'fx': 0.0,
            'total': tot, 'note': note}


# ═════════════════════════ 既存の器 ═════════════════════════
def incumbents(rows):
    """賭け → 枠 → 器の一覧（費用の小さい順）。費用は実測（bestfund_vehicles）があれば実測、無ければ表の費用＋外国税。
    like_for_like＝どの器も表の費用＋外国税で比べた値（公平のための並べ）"""
    veh = json.load(open(VEHJ))
    meas = {}   # key(器の名前) → (cost_used, basis, listed_fee, tsumitate, growth, kind)
    for bb in veh['bets']:
        for v in bb['vehicles']:
            meas[key(v['vehicle'])] = (bb['bet'], v)
    out = {}

    def add(b, acct, item):
        out.setdefault(b, {}).setdefault(acct, []).append(item)

    # (1) bestfund_vehicles（実測）
    for k, (b, v) in meas.items():
        tx = tax_pct(b) or 0.0
        fx = FX_FEE_PCT if v['kind'] == 'us' else 0.0
        lfl = round(v['listed_fee'] + fx + tx, 4)   # listed_fee は中の ETF の経費を含めた表の費用（SBI・V は 0.0638＋VOO 0.03）
        it = {'vehicle': v['vehicle'], 'kind': {'fund': '投信', 'us': '米国ETF'}.get(v['kind'], v['kind']), 'cost': v['cost_used'],
              'basis': ('実測（' + v['cost_basis'] + '）') if v.get('td_5y') is not None or v.get('td_3y') is not None else '表の費用＋外国税',
              'like_for_like': lfl, 'src': 'out/bestfund_vehicles.json'}
        if v['tsumitate']:
            add(b, 'つみたて', it)
        if v['growth']:
            add(b, '成長', it)
    # (2) bestfund_data.VEH の米国 ETF・東証 ETF・投信のうち (1) に無いもの（表の費用＋外国税）
    for b, v in D.VEH.items():
        cands = []
        if v.get('tsumitate'):
            cands.append(('つみたて', v['tsumitate'][0], v['tsumitate'][1]))
        if v.get('growth'):
            cands.append(('成長', v['growth'][0], v['growth'][1]))
        for nm, fee, acct in v.get('alt') or []:
            cands += [('つみたて', nm, fee), ('成長', nm, fee)] if acct == '両方' else [(acct, nm, fee)]
        for acct, nm, fee in cands:
            if any(same_vehicle(nm, v2['vehicle']) for (_, v2) in meas.values()):
                continue
            c = round(100 * (fee + v['k'] * v['dy']), 4)
            add(b, acct, {'vehicle': nm, 'kind': '米国ETF' if re.fullmatch(r'[A-Z]{2,5}', nm.split('（')[0]) else '投信・東証ETF', 'cost': c,
                          'basis': '表の費用＋外国税', 'like_for_like': c, 'src': 'night/bestfund_data.VEH'})
    # (3) 投信ライブラリーの窓より前の器（楽天で手数料0の投信・東証 ETF）
    for r in rows:
        est = (r.get('establishedDate') or '')[:10]
        if not est or est >= WIN[0] or exclusions_jp(r):
            continue
        b, kind, _ = classify_jp(r)
        if kind != '既存の賭け' or b not in GROUP and b not in ACCTS and b not in D.VEH:
            continue
        etf = is_etf_jp(r)
        rk = rakuten(r)
        if not etf and (rk is None or rk > 0):
            continue
        n = nfkc(r['fundNm'])
        if any(same_vehicle(n, v2['vehicle']) for (_, v2) in meas.values()):
            continue   # 実測がある器は (1) の実測を使う（事前登録: 実測があれば実測）
        nc = new_cost_jp(r, b)
        if nc['total'] is None or nc['note'] and not nc['inner']:
            continue   # 中の ETF の費用が分からない器は既存の比べに使わない（下限の数字で既存を安く見せない）
        it = {'vehicle': n, 'kind': '東証ETF' if etf else '投信', 'cost': nc['total'], 'basis': '表の費用＋外国税',
              'like_for_like': nc['total'], 'est': est, 'src': f'投信ライブラリー（{r.get("associFundCd")}）'}
        if r.get('nisaFlg') == '1':
            add(b, 'つみたて', it)
        if r.get('nisaGrowthFlg') == '1':
            add(b, '成長', it)
    for b in out:
        for acct in out[b]:
            seen, lst = set(), []
            for it in sorted(out[b][acct], key=lambda x: (x['cost'], x['vehicle'])):
                if key(it['vehicle']) in seen:
                    continue
                seen.add(key(it['vehicle']))
                lst.append(it)
            out[b][acct] = lst
    return out


def best_incumbent(inc, b, acct):
    lst = []
    for bb in GROUP.get(b, (b,)):
        lst += inc.get(bb, {}).get(acct, [])
    if not lst:
        return None, None
    reg = min(lst, key=lambda x: x['cost'])
    lfl = min(lst, key=lambda x: x['like_for_like'])
    return reg, lfl


# ═════════════════════════ 判定 ═════════════════════════
def judge(e, inc, ce):
    """事前登録の G1/G2/G3/参考。e は1本の器の行（費用・枠・賭けが入っている）"""
    b, kind = e['bet'], e['kind']
    if kind == '既存の賭け' and (b in HELD or b in TOP3):
        rows = []
        for acct in ACCTS[b]:
            if acct not in e['accounts']:
                rows.append({'account': acct, 'eligible': False})
                continue
            reg, lfl = best_incumbent(inc, b, acct)
            if reg is None or e['cost']['total'] is None:
                rows.append({'account': acct, 'eligible': True, 'incumbent': None})
                continue
            d_reg = round(reg['cost'] - e['cost']['total'], 4)
            d_lfl = round(lfl['like_for_like'] - e['cost']['total'], 4)
            rows.append({'account': acct, 'eligible': True,
                         'incumbent_registered': {'vehicle': reg['vehicle'], 'cost': reg['cost'], 'basis': reg['basis']},
                         'cheaper_by_registered': d_reg,
                         'incumbent_like_for_like': {'vehicle': lfl['vehicle'], 'cost': lfl['like_for_like']},
                         'cheaper_by_like_for_like': d_lfl,
                         'meets_line_registered': d_reg >= LINE, 'meets_line_like_for_like': d_lfl >= LINE})
        e['vs_incumbent'] = rows
        hit = [x for x in rows if x.get('meets_line_registered')]
        if hit:
            why = []
            if e.get('record_years', 0) < 1:
                why.append('自分の記録が1年未満で実際の連動が測れない')
            if (e.get('aum_oku') or 0) < 50:
                why.append(f'純資産が小さい（{e.get("aum_oku")}億円）')
            if e['vehicle_kind'] == '東証ETF':
                why.append('東証 ETF＝楽天の積立に対応しているかは確かめていない')
            return ('G2' if why else 'G1'), ('費用の線を越える（' + '・'.join(f'{x["account"]}枠で {x["cheaper_by_registered"]:+.3f}%' for x in hit) + '）' +
                                            ('。ただし ' + '・'.join(why) if why else ''))
        ok = [x for x in rows if x.get('eligible') and x.get('incumbent_registered')]
        if not ok:
            el = [x['account'] for x in rows if not x.get('eligible')]
            return '参考', ('その賭けで使う枠（' + '・'.join(ACCTS[b]) + '）の対象ではない') if el and len(el) == len(rows) else '既存の器と比べられない'
        x = max(ok, key=lambda y: y['cheaper_by_registered'])
        return '参考', (f'{x["account"]}枠の既存の最安（{x["incumbent_registered"]["vehicle"]}・{x["incumbent_registered"]["cost"]:.3f}%・'
                       f'{x["incumbent_registered"]["basis"]}）より {x["cheaper_by_registered"]:+.3f}%（線 +{LINE:.2f}%）。'
                       f'表の費用どうしでは {x["incumbent_like_for_like"]["vehicle"]}（{x["incumbent_like_for_like"]["cost"]:.3f}%）より {x["cheaper_by_like_for_like"]:+.3f}%')
    if kind == '既存の賭け':
        c = ce.get(b)
        return '参考', f'今持っている賭けでも bestfund の上位3でもない（{D.JA.get(b, b)}・CE {c}%）' if c is not None else '今持っている賭けでも bestfund の上位3でもない'
    if kind == '為替ヘッジあり':
        return '参考', '為替ヘッジあり（ユーザーは為替をヘッジしない方針）'
    if kind == '組み合わせ':
        return '参考', '2つ以上の賭けを1本にした器＝別々に持てば足りる（費用も高い）'
    if kind == 'アクティブ':
        return '参考', f'アクティブ運用（指数の歴史で測れない・運用会社の腕は1年未満の記録では分からない・信託報酬 {e["cost"]["listed_incl_tax"]}%）'
    if kind in ('債券・マネー', 'REIT', 'その他の資産'):
        return '参考', f'{kind}（このユーザーの20〜30年の株の積立の外）'
    # 新しい指数（E3）
    ih = e.get('index_history') or {}
    yrs = ih.get('public_years')
    if yrs is None:
        return '参考', '判定できない（新しい指数・指数の公表日を確かめていない＝実績10年以上の証拠なし）'
    if yrs < 10:
        return '参考', f'判定できない（新しい指数・公表後の実績 {yrs} 年＜10年＝証拠が足りない）'
    if yrs >= 20:
        nb = ih.get('near_bet')
        tail = (f'。近い賭け {D.JA.get(nb, nb)} の CE は {ce.get(nb)}%（上位3は {min(ce[b2] for b2 in TOP3)}〜{max(ce[b2] for b2 in TOP3)}%）') if nb and nb in ce else ''
        return '参考', f'G3 の検定はしていない（公表後 {yrs} 年の指数だが bestfund の物差し〔CE〕で測る材料を用意していない）{tail}'
    return '参考', f'公表後 {yrs} 年（10〜20年）＝G3 の条件（20年以上）に届かない'


# 新しい指数の公表の時期（調べて確かめたものだけ。無いものは『確かめていない』）。名前の一部 → (指数, 公表後の年数〔2026-10-09 まで〕, 出所, 近い賭け)
INDEX_HISTORY = {
    'ニッセイ・S米国グロース株式メガ10': ('Solactive US Growth Mega 10 Select（米国の時価総額上位10社を等金額・年4回見直し）', 1.0,
                                     'ニッセイアセット 2025-10-17 発表（nam.co.jp/news/fpdf/251017_press01.pdf）・指数の算出開始 2025-10-15', None),
    'Smart-i Pro米国リブート75': ('ブルームバーグ米国業績改善企業75指数（Bloomberg Reformers Index）', 0.7,
                                 '算出開始 2026-02（2016-07 まで遡って試算）・docs/CLAUDE_ARCHIVE.md の rf 節で検定済み（A・境界）', None),
    'ドイツ株式・DAX': ('DAX（ドイツの大型40社）', 38.3, 'Deutsche Börse・1988-07-01 公表開始（live.deutsche-boerse.com の「Facts from 30 years of DAX」）', 'DEVXUS'),
    'NZAM上場投信DAX': ('DAX（ドイツの大型40社）', 38.3, 'Deutsche Börse・1988-07-01 公表開始（live.deutsche-boerse.com の「Facts from 30 years of DAX」）', 'DEVXUS'),
    'ユーロ・ストックス50': ('EURO STOXX 50（ユーロ圏の大型50社）', 28.6, 'STOXX・1998-02-26 公表開始（stoxx.com の「The EURO STOXX 50 and STOXX Ltd. turn 20」）', 'DEVXUS'),
}
# defense_alts（2026-10-10・eb3f176）で既に判定した防衛の器（結論: ITA のまま）
DEFENSE_ALTS = ['グローバルX防衛テックETF', 'グローバルX防衛テック-日本株式ETF', 'たわらノーロードフォーカス防衛・航空宇宙', '欧州防衛・航空宇宙株式インデックスファンド']


# 事前登録の母集団の外（事後・ウェブで確かめた事実。判定には使わない）——母集団は「設定日が窓の中」なので、
# 古い器が新しく買えるようになった・新しく発表されたが設定は窓の外、のようなものは入らない。ユーザーの役に立つものだけ並べる
OUTSIDE_UNIVERSE = [
    {'what': 'インデックスファンドNASDAQ100（アメリカ株式）（アモーヴァ・2020-08-31 設定）が 2026-10-09 につみたて投資枠に加わった',
     'facts': '信託報酬 税込0.484%（iFreeNEXT NASDAQ100 は 0.495%）・純資産 約3,824億円。投信ライブラリーの楽天の手数料の欄は 2.0%、楽天のページの NISA の表示は食い違う＝楽天でつみたて投資枠で買えるかは未確認',
     'measured': 'tracking_reference.b_existing_real_cost（実際の費用 3年 0.652%・5年 0.706%＝iFreeNEXT の 0.621%・0.643% より高い。同じ日本の器どうしの傾きでも iFreeNEXT に年 −0.03〜−0.06%）',
     'src': '金融庁 つみたて投資枠対象商品届出一覧 2026-10-08版の脚注「2026年10月9日、インデックスファンドNASDAQ100（アメリカ株式）を追加」・資産運用業協会の成長投資枠リスト（2026-10-08 変更）'},
    {'what': 'インベスコQQQトラスト シリーズ1（587A）＝QQQ そのものが東証に上場（2026-06-09・外国籍 ETF・円で1口から）',
     'facts': '総経費率 0.18%（QQQ は 2025-12-19 にオープンエンド化が承認され 0.20%→0.18%）・インベスコは NISA 成長投資枠で買えると表示・JPX の概要は外国証券取引口座が必要と記載。QQQM（0.15%＋両替0.02%）より表の費用が高い',
     'src': 'JPX の銘柄概要（587A）・インベスコ 2026-05-22 プレスリリース・invesco.com/jp/ja/etf/qqq.html'},
    {'what': 'ITA（iシェアーズ 米国航空宇宙＆防衛 ETF）が楽天証券で買えるようになったのは 2025-12-12（NISA 成長投資枠 ○・経費率 0.38%）',
     'facts': 'その他 ETF・投資信託 15% で買う本（2026-10-10 決定）。todo ita_nisa_check の答え',
     'src': '楽天証券のお知らせ info20251211-01（2025-12-12 現地約定分から取扱開始・NISA 成長投資枠 ○）'},
    {'what': '楽天証券が「こどもNISA」専用の信託報酬ゼロの投資信託を出すと発表（2026-10-09）',
     'facts': 'ファンド名・指数・運用会社・開始日は未定（準備が整い次第公表）。こどもNISA は 2027年1月から。門の計画は iFreeNEXT NASDAQ100（0.495%）',
     'src': '楽天証券 2026-10-09 プレスリリース（PR TIMES）'},
    {'what': 'SBI・オールカントリー・インデックス・ファンド（税込0.055%・2026-11-17 設定）と SBI・ゼロ・オールカントリー（0.00%・こどもNISA 専用）',
     'facts': '発表は 2026-10-01（窓の中）・設定は窓の外。SBI アセットの器で、楽天で売るかは不明（同じ会社の SBI NASDAQ100 は楽天に無い）',
     'src': 'SBI アセットマネジメント 2026-10-01 発表'},
]


def index_history(name):
    k = key(name)
    for sub, v in INDEX_HISTORY.items():
        if key(sub) in k:
            return {'index': v[0], 'public_years': v[1], 'src': v[2], 'near_bet': v[3]}
    return None


# ═════════════════════════ 参考: 実際の連動（判定に使わない） ═════════════════════════
# (a) 事前登録 E1「新しい器の設定来の指数との差は参考に出すだけ・判定に使わない」＝新しい器と既存の器を同じ窓で比べる
# (b) 事後（事前登録の外・結果を見た後）: 同じ賭けの既存の東証 ETF の実際の費用（3年・5年）＝東証 ETF に表に出ない費用がどれだけあるか、
#     と 2026-10-09 につみたて投資枠に加わったアモーヴァ インデックスファンドNASDAQ100（アメリカ株式）の実際の費用
REF_OLD = {  # 賭け → 同じ窓で比べる既存の器（名前, isin〔'us'＝米国 ETF〕, 協会コード or ティッカー, 表の費用〔税込・％〕）
    'NDX': [('iFreeETF NASDAQ100(為替ヘッジなし)〔2840〕', 'JP3049460003', '04314221', 0.11),
            ('NEXT FUNDS NASDAQ-100(為替ヘッジなし)〔1545〕', 'JP3047240001', '01313108', 0.22),
            ('MAXISナスダック100上場投信〔2631〕', 'JP3049190006', '03314212', 0.22),
            ('楽天・プラス・NASDAQ-100インデックス・ファンド', 'JP90C000QF22', '9I314241', 0.198),
            ('iFreeNEXT NASDAQ100インデックス', 'JP90C000GUN2', '04317188', 0.495),
            ('インデックスファンドNASDAQ100(アメリカ株式)〔アモーヴァ・2026-10-09 つみたて投資枠に追加〕', 'JP90C000KNQ2', '02314208', 0.484),
            ('QQQM', 'us', 'QQQM', 0.15)],
    'SP500': [('MAXIS米国株式(S&P500)上場投信〔2558〕', 'JP3048980001', '03312201', 0.066),
              ('iシェアーズS&P500米国株ETF〔1655〕', 'JP3048530004', '48312179', 0.077),
              ('NEXT FUNDS S&P500指数(為替ヘッジなし)〔2633〕', 'JP3049250008', '01316213', 0.066),
              ('上場インデックスファンド米国株式(S&P500)〔1547〕', 'JP3047260009', '0231110A', 0.066),
              ('eMAXIS Slim米国株式(S&P500)', 'JP90C000GKC6', '03311187', 0.0814),
              ('楽天・プラス・S&P500インデックス・ファンド', 'JP90C000Q2U6', '9I31223A', 0.077),
              ('VOO', 'us', 'VOO', 0.03)],
}


def _lv_fund(isin, assoc, s=None, e=None):
    rows = [r for r in D.jita_daily(isin, assoc) if (s is None or r[0] >= s) and (e is None or r[0] <= e)]
    if len(rows) < 2:
        return {}, []
    lv, x = {rows[0][0]: 1.0}, 1.0
    for (a, n0, _), (b, n1, v1) in zip(rows, rows[1:]):
        x *= (n1 + v1) / n0
        lv[b] = x
    return lv, [d for d, _, _ in rows]


def _slope(X, Y, start, end):
    """log(X/Y) を時間（年）に当てた最小二乗の傾き（年率・％）。窓の両端の雑音（基準価額の時刻のずれ）に強い。(傾き, 始, 終, 日数)"""
    import math
    ds = [d for d in sorted(set(X) & set(Y)) if start <= d <= end]
    if len(ds) < 60:
        return None
    t0 = datetime.date(ds[0] // 10000, ds[0] // 100 % 100, ds[0] % 100)
    xs = [(datetime.date(d // 10000, d // 100 % 100, d % 100) - t0).days / 365.25 for d in ds]
    ys = [math.log(X[d] / X[ds[0]]) - math.log(Y[d] / Y[ds[0]]) for d in ds]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return round(100 * b, 3), ds[0], ds[-1], n


def _index_lv_jpy(bet, dates):
    """器の日付の列に合わせた指数の円建ての水準（bestfund_vehicles.td_fund と同じ合わせ方: 1日前の米国の終値 × 前日のドル円）"""
    import bestfund_vehicles as V
    lv, ccy = V.idx_daily(bet, 'JPY')
    keys = sorted(lv)
    fx = V.fx_daily()
    fk = sorted(fx)
    out = {}
    for d in dates:
        k, f = V._before(keys, d), V._before(fk, d)
        if k and (ccy == 'JPY' or f):
            out[d] = lv[k] * (1.0 if ccy == 'JPY' else fx[f])
    return out


def tracking_reference(main_rows):
    """(a) 事前登録 E1 の参考の欄: 新しい器の設定来の連動を、同じ窓の既存の日本の器と直接比べる（判定に使わない）
    (b) 事後（事前登録の外）: 同じ賭けの既存の器の実際の費用（3年・5年）＝表に出ない費用の大きさ"""
    import bestfund_vehicles as V
    end = D.END * 100 + 31
    veh = json.load(open(VEHJ))
    measured = {key(v['vehicle']): v for bb in veh['bets'] for v in bb['vehicles']}
    real = {}   # (b) の結果: 名前 → 3年・5年の実際の費用
    out = {'role': '参考（判定に使わない）。(a) は事前登録 E1 の参考の欄、(b) は事後（事前登録の外・結果を見た後）',
           'a_new_vs_existing_same_window': [], 'b_existing_real_cost': []}
    for b, lst in REF_OLD.items():
        tx = tax_pct(b)
        for nm, isin, code, lf in lst:
            if isin == 'us':
                m = measured.get(key(nm))
                if m:
                    out['b_existing_real_cost'].append({'vehicle': nm, 'bet': D.JA[b], 'listed_plus_tax_fx': round(lf + tx + FX_FEE_PCT, 3),
                                                        'cost_3y': m.get('cost_3y'), 'cost_5y': m.get('cost_5y'), 'src': 'out/bestfund_vehicles.json'})
                    real[nm] = m.get('cost_3y')
                continue
            x = {'vehicle': nm, 'bet': D.JA[b], 'listed_plus_tax': round(lf + tx, 3)}
            for yrs in (2, 3, 5):
                r = V.td_fund(b, isin, code, yrs)
                if r:
                    x[f'cost_{yrs}y'] = round(-100 * r[0], 3)
                    x[f'hidden_{yrs}y'] = round(-100 * r[0] - (lf + tx), 3)
            out['b_existing_real_cost'].append(x)
            real[nm] = x.get('cost_3y') if x.get('cost_3y') is not None else x.get('cost_2y')
    for e in main_rows:
        b = e['bet']
        if e['kind'] != '既存の賭け' or b not in REF_OLD or not e.get('isin') or e.get('record_years', 0) < 0.25:
            continue
        lv_new, dates = _lv_fund(e['isin'], e['assoc'], None, end)
        if len(dates) < 60:
            continue
        idx = _index_lv_jpy(b, dates)
        vs_idx = _slope(lv_new, idx, dates[0], end)
        row = {'vehicle': e['name'], 'bet': D.JA[b], 'listed_plus_tax': e['cost']['total'],
               'vs_index_slope': vs_idx[0] if vs_idx else None, 'window': f'{dates[0]}〜{min(end, dates[-1])}（{len(dates)}日）',
               'vs_existing': []}
        implied = []
        for nm, isin, code, lf in REF_OLD[b]:
            if isin == 'us':
                continue
            lv_old, _ = _lv_fund(isin, code, dates[0], end)
            sl = _slope(lv_new, lv_old, dates[0], end)
            if not sl:
                continue
            z = {'vehicle': nm, 'slope_new_minus_existing': sl[0], 'existing_real_cost': real.get(nm)}
            if real.get(nm) is not None:
                z['implied_new_real_cost'] = round(real[nm] - sl[0], 3)
                implied.append(z['implied_new_real_cost'])
            row['vs_existing'].append(z)
        if implied:
            implied.sort()
            row['implied_new_real_cost_median'] = implied[len(implied) // 2] if len(implied) % 2 else round((implied[len(implied) // 2 - 1] + implied[len(implied) // 2]) / 2, 3)
        out['a_new_vs_existing_same_window'].append(row)
    out['note'] = ['slope＝log(新しい器 ÷ 既存の器) を時間に当てた傾き（年率％・正なら新しい器が上回った）。同じ日本の器どうしなので、為替・時刻の合わせ方の雑音はほぼ消える',
                   'implied_new_real_cost＝既存の器の実際の費用（3年。3年の記録が無ければ2年）−傾き。窓が1年未満なので目安（事前登録 E1: 判定に使わない）',
                   'cost＝−（器の総リターン−指数の総リターン）の年率（bestfund_vehicles.td_fund と同じ: 直近3年・5年の1年ごとの差を毎日ずらして平均）。'
                   '日本の器は基準価額に外国税・費用が全部入る。米国 ETF は NISA で取り戻せない外国税と両替（年0.02%）を足した（out/bestfund_vehicles.json）',
                   'hidden＝実際の費用 −（表の費用＋外国税）＝表に出ない費用（指数の使用料・売買・保管・為替の換算・分配金を待つ間の現金・基準価額の時刻のずれ）']
    return out


# ═════════════════════════ 本体 ═════════════════════════
def main(refresh=False, skip_td=False):
    std, rows = load_jita(refresh)
    etfd = load_etfd(refresh)
    best = json.load(open(BESTJ))
    ce = {t['bet']: t['CE_γ2(%/年)'] for t in best['table']}
    inc = incumbents(rows)
    stdd = std[:10]
    res = {'generated': datetime.date.today().isoformat(), 'tool': 'night/newfunds.py', 'prereg': PREREG,
           'question': '最近一年以内（2025-10-11〜2026-10-10）に出た投資信託・ETF の中に、このユーザーにとって良いものがあるか',
           'snapshot': {'jita_standard_date': stdd, 'jita_rows': len(rows), 'jita_sha256': sha256(JITA),
                        'etfd_fetched': '2026-10-11', 'etfd_rows': len(etfd), 'etfd_sha256': sha256(ETFD)},
           'window': list(WIN), 'line_pct': LINE}
    # ── U1
    u1 = [r for r in rows if WIN[0] <= (r.get('establishedDate') or '')[:10] <= WIN[1]]
    main_rows, ref_not_rakuten, ref_fee, excluded = [], [], [], []
    for r in u1:
        n = nfkc(r['fundNm'])
        ex = exclusions_jp(r)
        est = r['establishedDate'][:10]
        base = {'name': n, 'kind_vehicle': '東証ETF' if is_etf_jp(r) else '投信', 'established': est,
                'isin': r.get('isinCd'), 'assoc': r.get('associFundCd')}
        if ex:
            excluded.append(dict(base, why=ex))
            continue
        b, kind, knote = classify_jp(r)
        etf = is_etf_jp(r)
        rk = rakuten(r)
        acc = (['つみたて'] if r.get('nisaFlg') == '1' else []) + (['成長'] if r.get('nisaGrowthFlg') == '1' else [])
        aum = fnum(r.get('totalNetAssets'))
        e = {'name': n, 'vehicle_kind': '東証ETF' if etf else '投信', 'established': est,
             'record_years': round((datetime.date.fromisoformat(stdd) - datetime.date.fromisoformat(est)).days / 365.25, 2),
             'bet': b, 'bet_ja': D.JA.get(b, b) if b else None, 'kind': kind, 'kind_note': knote, 'accounts': acc,
             'cost': new_cost_jp(r, b), 'aum_oku': round(aum / 100, 1) if aum is not None else None,
             'flow_oku': {k: round(fnum(r.get(f))/100, 1) for k, f in (('1m', 'monthlyCancelCreateVal'), ('3m', 'monthlyCancelCreateVal3'),
                                                                        ('6m', 'monthlyCancelCreateVal6'), ('12m', 'monthlyCancelCreateVal12'))
                          if fnum(r.get(f)) is not None},
             'rakuten_sales_fee': rk, 'isin': r.get('isinCd'), 'assoc': r.get('associFundCd'),
             'distributions_per_year': {'001': 1, '002': 2, '004': 4, '006': 6, '012': 12}.get(r.get('setlFqcy'))}
        if DCNAME.search(n):
            e['flag_dc_name'] = '名前に DC・確定拠出・年金（DC 向けの器の可能性。事前登録の除外は dcFundFlg=1 だけなので残した）'
        if kind == '新しい指数':
            e['index_history'] = index_history(n)
        if not etf and rk is None:
            ref_not_rakuten.append(e)
            continue
        if not etf and rk and rk > 0:
            ref_fee.append(e)
            continue
        main_rows.append(e)
    # ── U2（楽天の米国 ETF・Yahoo の最初の取引日）
    us_all = [x for x in etfd if x and x[0].split('.')[-1] in ('P', 'O')]
    u2, u2_err, col32_cross = [], [], []
    for x in us_all:
        t = (x[1] or x[0].split('.')[0]).strip()
        y = yahoo_first(t)
        incep = x[32].strip().replace('/', '-') if len(x) > 32 else ''
        in_y = y['first'] is not None and WIN[0] <= y['first'] <= WIN[1]
        in_c = bool(incep) and WIN[0] <= incep <= WIN[1]
        if y['first'] is None:
            u2_err.append({'ticker': t, 'err': y['err'], 'market_blank': x[3] == '', 'inception_col32': incep or None})
        if in_y != in_c and y['first'] is not None:
            col32_cross.append({'ticker': t, 'yahoo_first': y['first'], 'inception_col32': incep or None})
        if in_y:
            u2.append((x, y['first'], incep))
    u2_main, u2_ex = [], []
    for x, first, incep in u2:
        t = (x[1] or x[0].split('.')[0]).strip()
        why = []
        if LEV_US.search(x[2]) or any(w in nfkc(x[22]) for w in LEV_JP):
            why.append('レバレッジ・インバース')
        if (x[56].strip() if len(x) > 56 else '') == '12':
            why.append('毎月分配')
        base = {'ticker': t, 'name': x[2], 'name_ja': nfkc(x[22]), 'first_trade': first, 'inception_col32': incep or None}
        if why:
            u2_ex.append(dict(base, why=why))
            continue
        b, kind, knote = classify_us(x)
        er = fnum(x[5]) if fnum(x[5]) is not None else fnum(x[33] if len(x) > 33 else None)
        tx = tax_pct(b) if b in D.VEH else None
        aum = fnum(x[24])
        e = dict(base, vehicle_kind='米国ETF', bet=b, bet_ja=D.JA.get(b, b), kind=kind, kind_note=knote, index=x[4] or None,
                 accounts=['成長（要確認）'], record_years=round((datetime.date(2026, 10, 11) - datetime.date.fromisoformat(first)).days / 365.25, 2),
                 cost={'listed': er, 'fx': FX_FEE_PCT, 'foreign_tax': tx, 'total': round(er + FX_FEE_PCT + tx, 4) if er is not None and tx is not None else None},
                 aum_musd=aum, market=x[3])
        if kind == '新しい指数':
            e['index_history'] = index_history(x[2])
        u2_main.append(e)
    # ── 判定
    for e in main_rows:
        g, why = judge(e, inc, ce)
        if any(key(x) in key(e['name']) for x in DEFENSE_ALTS):
            why += '。defense_alts（2026-10-10・eb3f176）で判定済み＝ITA のまま'
        e['judgment'], e['reason'] = g, why
    for e in u2_main:
        if e['kind'] == '既存の賭け' and (e['bet'] in HELD or e['bet'] in TOP3):
            e['accounts'] = ['成長']
        g, why = judge(e, inc, ce)
        e['judgment'], e['reason'] = g, why
    for lst in (ref_not_rakuten, ref_fee):
        for e in lst:
            g, why = judge(dict(e), inc, ce)
            if any(key(x) in key(e['name']) for x in DEFENSE_ALTS):
                why += '。defense_alts（2026-10-10・eb3f176）で判定済み＝ITA のまま'
            e['judgment_if_available'], e['reason_if_available'] = g, why
    allj = main_rows + u2_main
    res['counts'] = {'U1_window': len(u1), 'U1_excluded': len(excluded), 'U1_main': len(main_rows),
                     'U1_ref_not_at_rakuten': len(ref_not_rakuten), 'U1_ref_sales_fee': len(ref_fee),
                     'U2_us_rows': len(us_all), 'U2_yahoo_missing': len(u2_err), 'U2_window': len(u2), 'U2_excluded': len(u2_ex),
                     'U2_main': len(u2_main),
                     'judgments': {g: sum(1 for e in allj if e['judgment'] == g) for g in ('G1', 'G2', 'G3', '参考')}}
    res['verdict'] = {
        'G1': [e['name'] if 'name' in e else e['ticker'] for e in allj if e['judgment'] == 'G1'],
        'G2': [e['name'] if 'name' in e else e['ticker'] for e in allj if e['judgment'] == 'G2'],
        'G3': [e['name'] if 'name' in e else e['ticker'] for e in allj if e['judgment'] == 'G3']}
    # 今持っている賭け・上位3の新しい器（近いところ）を費用の差の大きい順に
    near = []
    for e in allj:
        for x in e.get('vs_incumbent') or []:
            if x.get('incumbent_registered'):
                near.append({'vehicle': e.get('name') or e.get('ticker'), 'kind': e['vehicle_kind'], 'bet': e['bet_ja'], 'account': x['account'],
                             'new_cost': e['cost']['total'], 'incumbent': x['incumbent_registered']['vehicle'],
                             'incumbent_cost': x['incumbent_registered']['cost'], 'incumbent_basis': x['incumbent_registered']['basis'],
                             'cheaper_by_registered': x['cheaper_by_registered'],
                             'incumbent_like_for_like': x['incumbent_like_for_like']['vehicle'],
                             'cheaper_by_like_for_like': x['cheaper_by_like_for_like'], 'aum_oku': e.get('aum_oku'),
                             'record_years': e.get('record_years')})
    res['held_and_top3_new_vehicles'] = sorted(near, key=lambda z: -z['cheaper_by_registered'])
    res['incumbents_used'] = {b: {acct: lst[:6] for acct, lst in inc.get(b, {}).items()} for b in list(HELD) + list(TOP3)}
    res['main_table_U1'] = sorted(main_rows, key=lambda e: ({'G1': 0, 'G2': 1, 'G3': 2}.get(e['judgment'], 3), e['kind'], e['established']))
    res['main_table_U2'] = sorted(u2_main, key=lambda e: e['first_trade'])
    res['reference_not_at_rakuten'] = sorted(ref_not_rakuten, key=lambda e: e['established'])
    res['reference_sales_fee_at_rakuten'] = sorted(ref_fee, key=lambda e: e['established'])
    res['excluded_U1'] = sorted(excluded, key=lambda e: e['established'])
    res['excluded_U2'] = u2_ex
    res['U2_yahoo_missing'] = u2_err
    res['U2_yahoo_vs_listed_inception_disagree'] = col32_cross
    def _false_lev(n):
        # 事前登録の語が別の単語の一部だっただけ（ブルームバーグ・ステーブル・フレキシブルの『ブル』）
        m = n
        for w in ('ブルームバーグ', 'ステーブル', 'フレキシブル'):
            m = m.replace(w, '')
        return n != m and not any(w in m for w in LEV_JP)
    fp = [e['name'] for e in excluded if all('レバレッジ' in y for y in e['why']) and _false_lev(e['name'])]
    ls = [e['name'] for e in excluded if 'ロングショート' in e['name'] or 'ロング・ショート' in e['name']]
    res['notes'] = [
        '新しい器は自分の記録が1年未満＝本当の費用（指数との差）は測れない。既存の器の多くは実測（表に出ない費用を含む）で、新しい器は表の費用＝新しい器に有利に傾いた比べ。'
        '公平のため、どの器も表の費用＋外国税で比べた値（like_for_like）も並べた',
        '費用は税込の年率（%）。外国税は NISA で取り戻せない配当の源泉税＝k×配当利回り（bestfund_data.VEH）。米国 ETF は両替 年0.02% を足した',
        '投信ライブラリーの信託報酬は、中で外国の ETF を買う器ではその ETF の費用を含まない（例: グローバルX 防衛テック ETF は 0.0275% と載るが、中の SHLD 0.50% を足して 0.5275%）。'
        '分かったものは足し、分からないものは「表の費用は下限」と書いた（既存の比べには使わない）',
        '東証 ETF は分配金を払い出す（中で再投資しない）＝NISA で受け取った分配金を買い直すと成長投資枠を使う。投信（分配0円）とはここが違う',
        '除外の「レバレッジ・インバース」は事前登録の語（ブル・ショート ほか）をそのまま当てた。語が別の単語の一部だっただけの本（偽の当たり）: ' + ('、'.join(fp) if fp else 'なし') +
        '（どれも今持っている賭け・上位3には当たらない＝戻しても判定は「参考」）。ロング・ショート戦略の本は売りを使う運用なので語どおり外した: ' + str(len(ls)) + '本',
        '楽天での取扱は投信ライブラリーの販売会社の欄で見た（東証 ETF・米国 ETF は楽天で売買できるとした）。楽天の積立の可否・NISA の表示・ポイントは見ていない',
        '投信ライブラリーの NISA の印は遅れることがある（例: SBI NASDAQ100 は資産運用業協会の成長投資枠リストに 2026-04-21 から載るが、ライブラリーの印は対象外の 9）。'
        '判定に効く器（今持っている賭け・上位3）は資産運用業協会のリストと突き合わせた（NZAM 534A・533A・SPDR 449A・Smart-i NASDAQ100 は成長投資枠の対象）',
    ]
    res['outside_universe_post_hoc'] = OUTSIDE_UNIVERSE
    if not skip_td:
        res['tracking_reference'] = tracking_reference(main_rows)
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
    return res


if __name__ == '__main__':
    r = main(refresh='--refresh' in sys.argv, skip_td='--no-td' in sys.argv)
    print('→', OUT)
    print(json.dumps(r['counts'], ensure_ascii=False))
    print('判定', json.dumps(r['verdict'], ensure_ascii=False))
    for z in r['held_and_top3_new_vehicles']:
        print(f"  {z['vehicle'][:40]:40s} {z['bet']}/{z['account']} 新 {z['new_cost']} vs {z['incumbent'][:28]} {z['incumbent_cost']}（{z['incumbent_basis']}）"
              f" 差 {z['cheaper_by_registered']:+.3f} ／表どうし {z['incumbent_like_for_like'][:24]} 差 {z['cheaper_by_like_for_like']:+.3f}")
