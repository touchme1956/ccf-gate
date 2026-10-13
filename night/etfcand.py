#!/usr/bin/env python3
"""night/etfcand.py — 他に入れるべき ETF の候補（2026-10-13・ユーザー「他に入れるべきETFの候補を徹底的に探して」）

読むだけ。門・採点・配分（portfolio.json）には触れない。事前登録 out/etfcand_prereg.json（8e86a4b・測る前に固定）どおり。

  第1段  python3 night/etfcand.py stage1
         楽天証券で買える ETF の全部（ETFD.csv 2026-10-13・米国上場と東証）を、今の形（QQQ 40 : SMH 25 : ITA 5 : SHLD 5 :
         XLV 5 : FBT 5）の NASDAQ100 から5を候補へ回した形の円の実績（W20 2006-10〜・W10 2016-10〜）で並べ、
         今の本と同じ賭け（相関 ≥0.95）を外し、家族（相関 ≥0.95）に整理して、第2段へ送る候補を決める
  第2段  python3 night/etfcand.py stage2
         ショートリストを etf_ita_xlk と同じ4つの世界（A1・A2・B・C）と判定の決まり・感度5本で裁く
出力: out/etfcand.json（第1段と第2段を同じファイルへ）
"""
import csv, datetime, hashlib, html, io, json, math, os, re, statistics as S, sys, time
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import mw_common as M      # noqa: E402
import gaps_common as G    # noqa: E402

OUT = os.path.join(BASE, 'out', 'etfcand.json')
PREREG = 'out/etfcand_prereg.json（8e86a4b）'
CDIR = os.path.join(BASE, 'out', '_nx_cache', 'etfcand')
ETFD = os.path.join(CDIR, 'etfd_20261013.csv')
ETFD_SHA = '57663d10c8456d389939905bc0c54ecebdeba1d3cfef837e48791302caf0331e'
MKT_US = {'NYSE ARCA', 'ﾅｽﾀﾞｯｸ', 'Cboe'}
MKT_JP = {'東証ETF', '名証ETF'}
# X1。事前登録（8e86a4b）の語のままだと偽の当たりが出た（測る前に名前だけで確かめた: 日本語名の『ブル』がブルームバーグ・
# サステナブル・リニューアブル・フレキシブル・オートコーラブルに、『ダブル』がダブルラインに、『ショート』がショート・マチュリティ・
# ウルトラショート・インカム・ロング／ショートに、英語の『1x』が PBR 1倍割れに、『Daily』がデイリー・カバード・コールに当たった）。
# → 測る前に直した（事前登録の追記 2026-10-13）: 米国上場は英語の名前だけで見る／日本上場は英語の名前と日本語名の両方で見る（日本語の語を絞る）
LEV = re.compile(r"(?i)(\bDaily\b(?! Covered)|Leveraged|\b[2-9](\.\d+)?[xX]\b|\b1\.\d+[xX]\b|-[1-9](\.\d+)?[xX]\b|\b1[xX] Short"
                 r"|\bBull\b|\bBear\b|\bUltra(Pro)?\b(?![- ]Short)|UltraShort"
                 r"|(?<!Ultra-)(?<!Ultra )(?<!Long/)(?<!Long-)(?<!Long )\bShort\b(?![- ](Term|Trm|Treasury|Treas|Duration|Maturity|Bond|Income|Muni|Government|Corporate|High Yield))"
                 r"|Inverse)")
LEV_JP = re.compile(r'(レバレッジ|インバース|ベア|ブル[２2３3・]|[２2３3]倍|ダブル(?!ライン)|トリプル|逆連動)')
VOLX = re.compile(r'(?i)(VIX|Volatility)')
HELD = ['QQQ', 'QQQM', 'SMH', 'ITA', 'SHLD', 'XLV', 'FBT']
HELD_REF = ['QQQ', 'SMH', 'ITA', 'SHLD', 'XLV', 'FBT']      # 同じ賭けを測る相手（NASDAQ100 は QQQ で代える）
BASE_W = {'QQQ': 40, 'SMH': 25, 'ITA': 5, 'SHLD': 5, 'XLV': 5, 'FBT': 5}
NET = 85
SLOT = 5
SHLD_FROM = 202310                                         # SHLD の最初の月（それより前は ITA で代える）
W20 = (200610, 202609)
W10 = (201610, 202609)
SAME_BET = 0.95
FAMILY = 0.95
TOPK = 5
# X3b（事前登録の追記 2026-10-13・候補の Δ を見る前）: Yahoo の東証の月足に桁や分割の誤り（−90%・+961%・−341% など）があった。
# 米国上場の本の実際の最悪・最良の月は OIH −55.5%（2020-03）・FXN +61.7%（2020-04）なので、−60% 以下か +100% 以上の月は壊れた値と読む
BROKEN_LO, BROKEN_HI = -0.60, 1.00


def log(*a):
    print(*a, flush=True)


def months(a, b):
    out, y, m = [], a // 100, a % 100
    while y * 100 + m <= b:
        out.append(y * 100 + m)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def num(x):
    try:
        return float(str(x).replace(',', ''))
    except ValueError:
        return None


# ───────────────────────── 母集団 ─────────────────────────
def load_universe():
    b = open(ETFD, 'rb').read()
    sha = hashlib.sha256(b).hexdigest()
    assert sha == ETFD_SHA, f'ETFD.csv の sha256 が事前登録と違う: {sha}'
    rows = list(csv.reader(io.StringIO(b.decode('utf-8-sig'))))
    uni, excluded = [], []
    for r in rows:
        if len(r) < 33:
            continue
        mk = r[3]
        if mk not in MKT_US | MKT_JP:
            continue
        us = mk in MKT_US
        yt = r[1] if us else r[0].replace('.NG', '.N')
        nm = html.unescape(r[2])
        ja = html.unescape(r[22])
        idx = html.unescape(r[4])
        d = dict(t=r[1] if us else r[0], y=yt, nm=nm, ja=ja, mkt=mk, us=us, idx=idx, er=num(r[5]), cls=r[6], region=r[7],
                 dy=num(r[19]), aum=num(r[24]), aum_unit=r[25], inception=r[32].replace('/', '-') if r[32] else None)
        why = None
        if LEV.search(nm) or (not us and LEV_JP.search(ja)):
            why = 'X1 レバレッジ・インバース'
        elif r[6] == '通貨' or VOLX.search(nm) or 'ボラティリティ' in ja:
            why = 'X2 通貨・ボラティリティ'
        elif (r[1] if us else r[0]) in HELD:
            why = 'X4 今持っている本'
        if why:
            excluded.append(dict(t=d['t'], nm=nm, ja=ja, why=why))
            continue
        uni.append(d)
    return uni, excluded, len(rows)


# ───────────────────────── 値段（円） ─────────────────────────
def fx_monthly():
    fx = G.fred('DEXJPUS')
    ks = sorted(fx)
    return {k: fx[k] / fx[p] - 1 for p, k in zip(ks, ks[1:])
            if (k // 100 * 12 + k % 100) - (p // 100 * 12 + p % 100) == 1}


def fetch(tickers, workers=4):
    out, err = {}, {}

    def one(t):
        try:
            return t, M.yahoo(t), None
        except Exception as e:  # noqa
            return t, None, str(e)[:200]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (t, r, e) in enumerate(ex.map(one, tickers)):
            if r:
                out[t] = r
            else:
                err[t] = e or '空'
            if (i + 1) % 100 == 0:
                log(f'  値段 {i + 1}/{len(tickers)}')
    return out, err


def to_yen(d, r, fxr):
    """月次リターン（その本の通貨）→ 円・NISA で戻らない外国税（米国上場だけ）を引く"""
    k = 0.10 if d['region'] == 'アメリカ' else 0.20
    drag = (k * (d['dy'] or 0.0) / 100 / 12) if d['us'] else 0.0
    if d['us']:
        return {m: (1 + v) * (1 + fxr[m]) - 1 - drag for m, v in r.items() if m in fxr and m <= W10[1]}, k, drag * 12
    return {m: v for m, v in r.items() if m <= W10[1]}, 0.0, 0.0


# ───────────────────────── 物差し ─────────────────────────
def stats(r, ks):
    xs = [r[k] for k in ks]
    lg = sum(math.log1p(x) for x in xs)
    cagr = math.exp(lg * 12 / len(xs)) - 1
    vol = S.pstdev(xs) * math.sqrt(12)
    v = pk = 1.0
    dd = 0.0
    path = []
    for x in xs:
        v *= 1 + x
        pk = max(pk, v)
        dd = min(dd, v / pk - 1)
        path.append(v)
    w12 = min(path[i + 11] / (path[i - 1] if i else 1.0) - 1 for i in range(len(xs) - 11))
    return dict(cagr=cagr, vol=vol, mdd=dd, eff=cagr / vol if vol else None, w12=w12)


def corr(a, b, ks):
    return M.corr([a[k] for k in ks], [b[k] for k in ks])


def r2(x, d=2):
    return None if x is None else round(100 * x, d)


# ───────────────────────── 第1段 ─────────────────────────
def stage1():
    t0 = time.time()
    uni, excluded, nrows = load_universe()
    log(f'ETFD.csv {nrows} 行 → 米国上場・東証 {len(uni) + len(excluded)} 本・除外 {len(excluded)}（X1/X2/X4）・残り {len(uni)}')
    fxr = fx_monthly()
    base_tk = HELD_REF
    meta_h = {}
    rows_all = list(csv.reader(io.StringIO(open(ETFD, 'rb').read().decode('utf-8-sig'))))
    for r in rows_all:
        if len(r) > 32 and r[3] in MKT_US and r[1] in base_tk:
            meta_h[r[1]] = dict(t=r[1], y=r[1], us=True, region=r[7], dy=num(r[19]), er=num(r[5]), nm=html.unescape(r[2]))
    assert set(meta_h) == set(base_tk), f'今の本が ETFD.csv に無い: {set(base_tk) - set(meta_h)}'
    log('値段を取る（今の本）')
    px_h, err_h = fetch([meta_h[t]['y'] for t in base_tk])
    assert not err_h, err_h
    H = {t: to_yen(meta_h[t], px_h[t], fxr)[0] for t in base_tk}
    log('値段を取る（候補）', len(uni))
    px, perr = fetch([d['y'] for d in uni])
    k10, k20 = months(*W10), months(*W20)

    # 今の形（SHLD は 2023-09 まで ITA で代える）
    def shld(m):
        return H['SHLD'][m] if m >= SHLD_FROM else H['ITA'][m]
    all_m = months(200607, W10[1])
    base = {}
    for m in all_m:
        if all(m in H[t] for t in ('QQQ', 'SMH', 'ITA', 'XLV', 'FBT')) and (m < SHLD_FROM or m in H['SHLD']):
            base[m] = sum(BASE_W[t] * (shld(m) if t == 'SHLD' else H[t][m]) for t in BASE_W) / NET
    for ks in (k10, k20):
        miss = [m for m in ks if m not in base]
        assert not miss, f'今の形の月が欠ける: {miss[:5]}'
    bst = {'W10': stats(base, k10), 'W20': stats(base, k20)}
    log('今の形 W20', {k: r2(v) for k, v in bst['W20'].items()}, ' W10', {k: r2(v) for k, v in bst['W10'].items()})

    cands, x3 = [], []
    for d in uni:
        r = px.get(d['y'])
        if r is None:
            x3.append(dict(t=d['t'], nm=d['nm'], why='X3 値段が取れない', err=perr.get(d['y'])))
            continue
        ry, k, drag = to_yen(d, r, fxr)
        miss10 = [m for m in k10 if m not in ry]
        if miss10:
            first = min(ry) if ry else None
            x3.append(dict(t=d['t'], nm=d['nm'], why='X3 W10 の120か月がそろわない', first=first, missing=len(miss10)))
            continue
        bad10 = [m for m in k10 if ry[m] <= BROKEN_LO or ry[m] >= BROKEN_HI]
        if bad10:
            x3.append(dict(t=d['t'], nm=d['nm'], why='X3b 値段が壊れている（W10 に月次 −60% 以下か +100% 以上の月）',
                           months={m: round(100 * ry[m], 1) for m in bad10[:6]}))
            continue
        d = dict(d, tax_k=k, tax_drag=drag, first=min(ry), ry=ry)
        d['w20'] = all(m in ry for m in k20)
        if d['w20']:
            bad20 = [m for m in k20 if ry[m] <= BROKEN_LO or ry[m] >= BROKEN_HI]
            if bad20:
                d['w20'] = False
                d['w20_broken'] = {m: round(100 * ry[m], 1) for m in bad20[:6]}
        cands.append(d)
    log(f'記録の点検 → 候補 {len(cands)}（W20 もそろう {sum(c["w20"] for c in cands)}）・X3 で外す {len(x3)}')

    # 同じ賭け
    for c in cands:
        best = None
        for h in HELD_REF:
            ks = [m for m in k10 if m in H[h]] if h != 'SHLD' else [m for m in k10 if m >= SHLD_FROM]
            v = corr(c['ry'], H[h], ks)
            if best is None or v > best[1]:
                best = (h, v)
        c['held_corr'] = best
        c['same_bet'] = best[1] >= SAME_BET

    # 形の物差し
    for c in cands:
        for wn, ks in (('W10', k10), ('W20', k20)):
            if wn == 'W20' and not c['w20']:
                continue
            fr = {m: base[m] + SLOT / NET * (c['ry'][m] - H['QQQ'][m]) for m in ks}
            st, so = stats(fr, ks), stats(c['ry'], ks)
            c[wn] = dict(form=st, own=so, d={k: (st[k] - bst[wn][k]) if st[k] is not None else None for k in st})

    # 家族
    live = [c for c in cands if not c['same_bet']]
    usdjpy = G.fred('DEXJPUS')
    fx_now = usdjpy[max(k for k in usdjpy if k <= W10[1])]

    def aum_usd(c):
        a = c['aum'] or 0.0
        return a / fx_now if c['aum_unit'] == '百万円' else a
    live.sort(key=lambda c: (c['first'], c['er'] if c['er'] is not None else 9e9, -aum_usd(c)))
    fams = []
    for c in live:
        hit = None
        for f in fams:
            if corr(c['ry'], f['rep']['ry'], k10) >= FAMILY:
                hit = f
                break
        if hit:
            hit['members'].append(c)
            c['family'] = hit['id']
        else:
            f = dict(id=len(fams) + 1, rep=c, members=[c])
            fams.append(f)
            c['family'] = f['id']
    log(f'同じ賭けでない候補 {len(live)} → 家族 {len(fams)}')

    # ショートリスト（株式の家族と金の現物の家族）
    gld = next((c for c in cands if c['t'] == 'GLD'), None)
    assert gld is not None, 'GLD が候補に無い'

    def is_gold(f):
        return f['rep']['cls'] != '株式' and corr(f['rep']['ry'], gld['ry'], k10) >= 0.95
    elig = [f for f in fams if f['rep']['cls'] == '株式' or is_gold(f)]
    lists = {}
    for wn in ('W20', 'W10'):
        pool = [f for f in elig if wn in f['rep']]
        for mt, key in (('Δ年率', 'cagr'), ('Δ最大下落', 'mdd'), ('Δ効率', 'eff')):
            top = sorted(pool, key=lambda f: -f['rep'][wn]['d'][key])[:TOPK]
            lists[f'{wn} {mt}'] = [f['id'] for f in top]
    short = {}
    for ln, ids in lists.items():
        for i in ids:
            short.setdefault(i, []).append(ln)
    log(f'ショートリスト {len(short)} 家族')
    for i, why in sorted(short.items(), key=lambda kv: kv[0]):
        f = fams[i - 1]
        rp = f['rep']
        w = rp.get('W20') or rp['W10']
        log(f"  #{i:3d} {rp['t']:8} {rp['nm'][:44]:44} 家族{len(f['members']):3d}本  "
            f"{'W20' if 'W20' in rp else 'W10'} Δ年率 {r2(w['d']['cagr']):+6.2f} Δ下落 {r2(w['d']['mdd']):+6.2f} Δ効率 {w['d']['eff']:+.4f}  ← {', '.join(why)}")

    def row(c):
        o = dict(t=c['t'], 名前=c['nm'], 日本語名=c['ja'], 市場=c['mkt'], 資産=c['cls'], 地域=c['region'], 指数=c['idx'],
                 経費率=c['er'], 配当利回り=c['dy'], 純資産=c['aum'], 純資産の単位=c['aum_unit'], 設定日=c['inception'],
                 最初の月=c['first'], 外国税の目減り=r2(c['tax_drag'], 3),
                 今の本との相関の最大={'本': c['held_corr'][0], '相関': round(c['held_corr'][1], 3)}, 同じ賭け=c['same_bet'],
                 家族=c.get('family'))
        for wn in ('W20', 'W10'):
            if wn in c:
                x = c[wn]
                o[wn] = {'形': {k: r2(v) if k != 'eff' else round(v, 4) for k, v in x['form'].items()},
                         '単体': {k: r2(v) if k != 'eff' else (round(v, 4) if v is not None else None) for k, v in x['own'].items()},
                         'Δ': {k: (r2(v) if k != 'eff' else round(v, 4)) for k, v in x['d'].items()}}
        return o

    doc = dict(generated=datetime.date.today().isoformat(), tool='night/etfcand.py', prereg=PREREG, stage=1,
               universe=dict(src='楽天 ETFD.csv 2026-10-13', sha256=ETFD_SHA, rows=nrows, us_jp=len(uni) + len(excluded),
                             excluded_X1_X2_X4=len(excluded), excluded_X3=len(x3), candidates=len(cands),
                             w20_capable=sum(c['w20'] for c in cands), same_bet=sum(c['same_bet'] for c in cands),
                             families=len(fams)),
               今の形={'重み（全体の%）': BASE_W, 'SHLD': 'SHLD の 2023-09 までは ITA で代える',
                       'W20': {k: r2(v) if k != 'eff' else round(v, 4) for k, v in bst['W20'].items()},
                       'W10': {k: r2(v) if k != 'eff' else round(v, 4) for k, v in bst['W10'].items()}},
               窓=dict(W20=f'{W20[0]}〜{W20[1]}', W10=f'{W10[0]}〜{W10[1]}'),
               候補=[row(c) for c in sorted(cands, key=lambda c: -(c.get('W20') or c['W10'])['d']['cagr'])],
               家族=[dict(id=f['id'], 代表=f['rep']['t'], 代表の名前=f['rep']['nm'], 資産=f['rep']['cls'],
                          本=[m['t'] for m in f['members']], 金の現物=is_gold(f) if f['rep']['cls'] != '株式' else False) for f in fams],
               並び=lists,
               ショートリスト=[dict(家族=i, 代表=fams[i - 1]['rep']['t'], 名前=fams[i - 1]['rep']['nm'], 入った並び=why,
                                   本=[m['t'] for m in fams[i - 1]['members']]) for i, why in sorted(short.items())],
               除外_X1_X2_X4=excluded, 除外_X3=x3, secs=round(time.time() - t0))
    prev = json.load(open(OUT)) if os.path.exists(OUT) else {}
    if prev.get('stage2'):
        doc['stage2'] = prev['stage2']
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    log('→', OUT, f'（{doc["secs"]}秒）')
    return doc



# ───────────────────────── 第2段 ─────────────────────────
PROXY_FUNDS = ['FBIOX', 'FSCSX', 'FDCPX', 'FSENX', 'VGENX', 'VGHCX', 'FSPHX', 'FSMEX', 'FSUTX', 'FSAGX', 'VGPMX', 'FSRBX', 'FIDSX',
               'FSPCX', 'FCYIX', 'FSDAX', 'FSRFX', 'FDFAX', 'FSCPX', 'FSRPX', 'FSDPX', 'FSCHX', 'FRESX', 'VGSIX', 'FSTCX', 'FSLBX',
               'FNARX', 'FSHOX', 'FDLSX', 'FSAVX', 'FSDCX', 'FSESX', 'FSAIX', 'FBSOX', 'NAESX', 'VISVX', 'VIGRX', 'VIVAX', 'VTMGX',
               'VEIEX', 'VGTSX', 'DFIVX', 'DFEVX']
JKP_ISO = {'日本': 'jpn', '中国': 'chn', 'インド': 'ind', 'ブラジル': 'bra', '韓国': 'kor', '台湾': 'twn', 'メキシコ': 'mex', 'ドイツ': 'deu',
           'インドネシア': 'idn', 'ベトナム': 'vnm', 'フィリピン': 'phl', 'ポーランド': 'pol', 'マレーシア': 'mys', 'シンガポール': 'sgp',
           '南アフリカ共和国': 'zaf', 'タイ': 'tha', 'トルコ': 'tur'}
REG_DEV = {'グローバル（除くアメリカ）', 'ヨーロッパ', 'アジア パシフィック', 'ユーロ', 'ドイツ', 'シンガポール'}
REG_EM = {'新興諸国', 'ラテンアメリカ', 'アフリカ', 'アジア パシフィック（除く日本）', '中国', 'インド', 'ブラジル', '韓国', '台湾', 'メキシコ',
          'インドネシア', 'ベトナム', 'フィリピン', 'ポーランド', 'マレーシア', '南アフリカ共和国', 'タイ', 'トルコ'}
ASIA_EM = {'アジア パシフィック（除く日本）', '中国', 'インド', '韓国', '台湾', 'インドネシア', 'ベトナム', 'フィリピン', 'マレーシア', 'タイ'}
SMALL = re.compile(r'(?i)(Small|Mid|Russell 2000|S&P 600|S&P 400|SmallCap|MidCap)')
BASE2 = {'QQQM': 40, 'SMH': 25, 'ITA': 10, 'XLV': 5, 'FBT': 5}
AVDIR = os.path.join(CDIR, 'av')


def prev_month(m):
    y, mm = m // 100, m % 100
    return (y - 1) * 100 + 12 if mm == 1 else y * 100 + mm - 1


def jpm_key(rep):
    rg = rep['region']
    if rg == 'アメリカ':
        return 'USS' if SMALL.search(rep['nm']) else 'USL'
    if rg == '日本':
        return 'JP'
    if rg == 'グローバル':
        return 'ACWI'
    if rg in ASIA_EM:
        return 'ASIAxJ'
    if rg in REG_EM:
        return 'EM'
    if rg in REG_DEV:
        return 'EAFE'
    return None


def load_av(t):
    p = os.path.join(AVDIR, f'{t}.json')
    if not os.path.exists(p):
        return None
    j = json.load(open(p))
    hs = [[h['symbol'], float(h['weight']), h.get('description', '')] for h in j.get('holdings', [])]
    return dict(er=float(j['net_expense_ratio']), dy=float(j['dividend_yield']) if j.get('dividend_yield') not in (None, 'n/a') else None,
                inception=j.get('inception_date'), last_updated=j.get('last_updated'), net_assets=j.get('net_assets'), holdings=hs,
                sectors=j.get('sectors'))


def french_region_mkt(fname):
    out = {}
    for t, v in M.french_tables(fname).items():
        if v['freq'] == 'monthly':
            ci = [c.lower() for c in v['cols']]
            for d, row in v['data'].items():
                if row[ci.index('mkt-rf')] is not None and row[ci.index('rf')] is not None:
                    out[d] = (row[ci.index('mkt-rf')] + row[ci.index('rf')]) / 100
            break
    return out


def run_posthoc(E):
    """結果を見た後に足した点検（事前登録の外・判定と結論に使わない）。
    P1 金・銀・銅の鉱山株に French 49 の業種の長い歴史（全期間・raw）の上乗せを半分当てる（B・C）
    P2 今の形に FBT を FBIOX でつないで入れる（代理の相関 0.874＜0.90 で事前登録では外した）
    P3 100年の代用（French 49 の Gold 業種・1963-07〜）で NASDAQ100 から5を回す
    P4 年ごとの差（A1 の窓・ドル）"""
    np, R, X, CB, IX, P = E['np'], E['R'], E['X'], E['CB'], E['IX'], E['P']
    rows, chains, assets, idx = E['rows'], E['chains'], E['assets'], E['idx']
    measure, judge, show = E['measure'], E['judge'], E['show']
    out = {}
    miners = {fid: key for fid, key in E['fam_rows'].items() if E['infos'][fid].get('t') in ('GDX', 'SIL', 'COPX')}
    # ── P1 ──
    bi = E['bi']
    p1 = {}
    gb_save, gc_save = E['gb0'].copy(), E['gc0'].copy()
    for fid, key in miners.items():
        w49 = E['infos'][fid].get('French49の重み') or {}
        tot = sum(w49.values())
        xr = sum(w / tot * bi['X_ind_raw'][k]['x'] for k, w in w49.items() if k in bi['X_ind_raw']) if tot else 0.0
        row = rows[key]
        bg = R.R_EQ + R.SHRINK * xr + R.REC_A                      # e＝0（記録の二業種を持たない）として米国の業種の本と同じ式
        cg = (R.H_JPM * R.JPM[row['jpm']] / 100 + (R.H - R.H_JPM) * bg) / R.H
        nb, nc = bg - row['er_vehicle'] - row['tax_drag'], cg - row['er_vehicle'] - row['tax_drag']
        i = idx[key]
        E['gb0'][i], E['gc0'][i] = nb, nc
        wd = dict(E['base_w']); wd['QQQM'] -= SLOT; wd[key] = wd.get(key, 0) + SLOT
        m = measure(wd)
        j = judge(m, E['base_m'])
        p1[E['infos'][fid]['t']] = dict(業種の上乗せraw=round(100 * xr, 2), B=round(100 * nb, 2), C=round(100 * nc, 2),
                                         主のB=round(100 * row['B'], 2), 主のC=round(100 * row['C'], 2), 物差し=show(m), 判定=j)
        E['gb0'][i], E['gc0'][i] = gb_save[i], gc_save[i]
    out['P1 鉱山株に業種の長い歴史の上乗せを当てる'] = p1
    log('事後 P1', {k: (v['業種の上乗せraw'], v['B'], v['判定']['主'], v['判定']['まとめ']) for k, v in p1.items()})
    # ── P2 FBT を FBIOX でつなぐ ──
    p2 = {}
    try:
        usd = M.yahoo('FBT')
        fbx = M.yahoo('FBIOX')
        er = (E['fbt_rep']['er'] or 0) / 100
        first = min(usd)
        last = prev_month(first)
        ch = {m: (fbx[m] - er / 12 if m <= last else usd[m]) for m in E['k1']}
        dy = (E['fbt_rep']['dy'] or 0) / 100
        tax = 0.10 * dy
        a1g, a2g = R.geo(ch, E['k1']), R.geo(ch, E['k2'])
        prof_old = json.load(open(os.path.join(BASE, 'out', 'etf_profiles.json'))).get('etfs') or {}
        hold = R.holdings_of('FBT', prof_old, {})
        ind_of, _ = X.mapper({t.upper() for t, _ in hold if not t.startswith('*')})
        ex = X.expo_of(['FBT_P2'], {'FBT_P2': hold}, lambda t, c=None: ind_of(t), bi)['FBT_P2']
        e = ex['e'] if ex['e'] is not None else R.E_MKT
        bg = R.R_EQ + R.SHRINK * (ex['X_ind'] or 0.0) + (R.REC_A - R.REC_B * e)
        cg = (R.H_JPM * R.JPM['USL'] / 100 + (R.H - R.H_JPM) * bg) / R.H
        p2['FBT の行'] = dict(A1=round(100 * (a1g - tax), 2), A2=round(100 * (a2g - tax), 2), B=round(100 * (bg - er - tax), 2), C=round(100 * (cg - er - tax), 2))
        rows2 = dict(rows); chains2 = dict(chains)
        rows2['FBT_P2'] = dict(A1=a1g - tax, A2=a2g - tax, A1_gross=a1g, A2_gross=a2g, B=bg - er - tax, C=cg - er - tax, us=True,
                               top_industries=ex['top_industries'])
        chains2['FBT_P2'] = ch
        sub = run_engine(rows2, chains2, {'QQQM': 40, 'SMH': 25, 'ITA': 10, 'XLV': 5, 'FBT_P2': 5},
                         [E['fam_rows'][f] for f in E['fam_rows']], np, R, CB, P, IX)
        p2['判定'] = {E['infos'][f]['t']: sub[E['fam_rows'][f]] for f in E['fam_rows']}
        log('事後 P2（FBT を FBIOX でつなぐ）', {k: (v['主'], v['まとめ']) for k, v in p2['判定'].items()})
    except Exception as e:  # noqa
        import traceback
        p2['失敗'] = traceback.format_exc()[-800:]
    out['P2 今の形に FBT を FBIOX でつないで入れる'] = p2
    # ── P3 100年の代用 ──
    p3 = {}
    try:
        import future30 as F
        cols, ret, capm, me, be, share, mkt = F.load()
        endm = max(mkt)
        tech = G.french_tech()
        allm = sorted(mkt)
        ndx = F.mix([(0.65, tech), (0.35, mkt)], allm)
        dfn = F.capw(ret, capm, ['Aero', 'Guns'], allm)
        hc = F.capw(ret, capm, ['Drugs', 'MedEq', 'Hlth'], allm)
        chips, gold, mines = ret['Chips'], ret['Gold'], ret['Mines']
        forms = {'今の形の写し（NASDAQ100 40・SMH 25・防衛 10・ヘルスケア 10・個別株 15＝市場）': [(0.40, ndx), (0.25, chips), (0.10, dfn), (0.10, hc), (0.15, mkt)],
                 '＋金鉱株 5（NASDAQ100 から）': [(0.35, ndx), (0.25, chips), (0.10, dfn), (0.10, hc), (0.05, gold), (0.15, mkt)],
                 '＋鉱業 5（NASDAQ100 から・参考）': [(0.35, ndx), (0.25, chips), (0.10, dfn), (0.10, hc), (0.05, mines), (0.15, mkt)]}
        ser = {nm: F.mix(parts, allm) for nm, parts in forms.items()}
        names = list(forms)
        base_s = ser[names[0]]
        gm = sorted(m for m in base_s if all(m in s for s in ser.values()))
        p3['窓'] = f'{gm[0]}〜{gm[-1]}'
        for nm in names:
            s = ser[nm]
            p3.setdefault('全期間', {})[nm] = dict(年率=round(100 * F.cagr_m(s, gm), 2), 最大下落=round(100 * R.maxdd(s, gm), 1),
                                                 ぶれ=round(100 * R.vol(s, gm), 1))
        for n, lab, y0, y1 in ((360, '30年の積立', gm[0] // 100 + 1, 1996), (240, '20年の積立', gm[0] // 100 + 1, 2006)):
            for nm in names[1:]:
                v = []
                for y in range(y0, y1 + 1):
                    ms = F.months(y * 100 + 1, n)
                    if ms[-1] > endm or any(m not in base_s for m in ms):
                        continue
                    a, b = F.dca_mult(ser[nm], ms), F.dca_mult(base_s, ms)
                    if a and b:
                        v.append((y, a / b))
                vv = sorted(x for _, x in v)
                p3.setdefault(lab, {})[nm] = dict(起点=f'{v[0][0]}〜{v[-1][0]}', 窓=len(v), 今の形との比の中央値=round(S.median(vv), 4),
                                                  今の形を上回った割合=round(sum(x > 1 for x in vv) / len(vv), 3), 最悪=round(vv[0], 4), 最良=round(vv[-1], 4),
                                                  最悪の起点=min(v, key=lambda z: z[1])[0])
        gms = sorted(m for m in gold if m in mkt and m in ndx)
        p3['金鉱株（French Gold）単体'] = dict(窓=f'{gms[0]}〜{gms[-1]}', 年率=round(100 * F.cagr_m(gold, gms), 2), 市場=round(100 * F.cagr_m(mkt, gms), 2),
                                                 ぶれ=round(100 * R.vol(gold, gms), 1), 最大下落=round(100 * R.maxdd(gold, gms), 1),
                                                 市場との相関=round(M.corr([gold[m] for m in gms], [mkt[m] for m in gms]), 3),
                                                 NASDAQ100の代用との相関=round(M.corr([gold[m] for m in gms], [ndx[m] for m in gms]), 3))
        dec = {}
        for a in range(1960, 2030, 10):
            ms = [m for m in gms if a * 100 + 1 <= m <= (a + 9) * 100 + 12]
            if len(ms) >= 24:
                dec[f'{a}年代'] = round(100 * (F.cagr_m(gold, ms) - F.cagr_m(mkt, ms)), 1)
        p3['金鉱株の10年ごとの市場との年率の差'] = dec
        log('事後 P3', {k: v for k, v in p3.items() if k in ('全期間', '30年の積立', '20年の積立')})
    except Exception as e:  # noqa
        import traceback
        p3['失敗'] = traceback.format_exc()[-800:]
    out['P3 100年の代用（French 49）'] = p3
    # ── P4 年ごとの差（A1・ドル）──
    p4 = {}
    for fid, key in miners.items():
        wd0 = E['vec'](E['base_w']); wd = dict(E['base_w']); wd['QQQM'] -= SLOT; wd[key] = wd.get(key, 0) + SLOT
        w1 = E['vec'](wd)
        yrs = {}
        for y in range(2001, 2027):
            ms = [m for m in E['k1'] if m // 100 == y]
            if len(ms) < 6:
                continue
            a = math.prod(1 + sum(w1[idx[c]] * chains[c][m] for c in assets) for m in ms) - 1
            b = math.prod(1 + sum(wd0[idx[c]] * chains[c][m] for c in assets) for m in ms) - 1
            yrs[y] = round(100 * (a - b), 2)
        p4[E['infos'][fid]['t']] = dict(年ごとの差=yrs, 上位=sorted(yrs.items(), key=lambda kv: -kv[1])[:4], 下位=sorted(yrs.items(), key=lambda kv: kv[1])[:4])
    out['P4 年ごとの差（A1の窓・ドル・毎年組み直しではなく毎月）'] = p4
    # ── P5 第1段で落ちた既存の行も同じ決まりで（ふるいが良い本を落としていないかの点検）──
    p5 = {}
    try:
        shortlisted = set(E['fam_rows'].values())
        others = [c for c in E['rows'] if c in E['R'].C and c not in shortlisted and c not in ('QQQM', 'SMH', 'ITA', 'XLV')
                  and all(m in chains[c] for m in E['k1'])]
        sub = run_engine(rows, chains, E['base_w'], others, np, R, CB, P, IX)
        for c in others:
            p5[c] = dict(sub[c], 名前=R.C[c]['ja'])
        log('事後 P5（既存の行すべて）', {c: (v['主'], v['まとめ'], v['主のΔ']['平均'], v['主のΔ']['最悪']) for c, v in p5.items()})
    except Exception:  # noqa
        import traceback
        p5['失敗'] = traceback.format_exc()[-800:]
    out['P5 第1段で落ちた既存の行も同じ決まりで'] = p5
    return out


def run_engine(rows, chains, base_w, keys, np, R, CB, P, IX):
    """事後の P2 用: 今の形を替えて、keys の各本を NASDAQ100 から5回した判定だけを返す（stage2 と同じ式）"""
    k1, k2 = R.months(*R.A1), R.months(*R.A2)
    T1, T2 = len(k1), len(k2)
    assets = list(dict.fromkeys(list(base_w) + list(keys)))
    G1 = np.array([[chains[c][m] for m in k1] for c in assets]); G2 = np.array([[chains[c][m] for m in k2] for c in assets])
    adj = np.array([rows[c]['A1'] - rows[c]['A1_gross'] for c in assets])
    gb0 = np.array([rows[c]['B'] for c in assets]); gc0 = np.array([rows[c]['C'] for c in assets])
    S1 = np.cov(np.log1p(G1), bias=True) * 12; S2 = np.cov(np.log1p(G2), bias=True) * 12
    s1, s2 = np.diag(S1).copy(), np.diag(S2).copy()

    def is_us(c):
        return R.C[c]['us'] if c in R.C else bool(rows[c].get('us'))
    chips = {c: (CB.CHIPS_MKT if c == 'VOO' else float((rows[c].get('top_industries') or {}).get('Chips') or 0.0)) for c in assets if c == 'VOO' or is_us(c)}
    rest = CB.CHIPS_GAP * CB.CHIPS_MKT / (1 - CB.CHIPS_MKT)
    chips_adj = np.array([((-CB.CHIPS_GAP * chips[c] + rest * (1 - chips[c])) / 2) if c in chips else 0.0 for c in assets])
    tabs = P.dca_tables(20, [0.05, 0.15], log=False)
    idx = {c: i for i, c in enumerate(assets)}

    def measure(wd):
        tot = sum(wd.values()); W = np.zeros(len(assets))
        for c, w in wd.items():
            W[idx[c]] += w / tot
        g, v, d = CB.path_stats((W @ G1)[None, :], T1)
        a2g = math.expm1(float(np.log1p(W @ G2).sum()) * 12 / T2)
        q1, q2 = float(W @ S1 @ W), float(W @ S2 @ W)
        out = {}
        for var in IX.VARS:
            wv = dict(A1=float(g[0] + W @ adj), A2=a2g + float(W @ adj))
            gb, gc = (gb0 + chips_adj, gc0 + chips_adj) if var == 'K4' else (gb0, gc0)
            if var == 'K1':
                wv['B'], wv['C'] = float(W @ gb), float(W @ gc)
            else:
                sv, qv = (s2, q2) if var == 'K2' else (s1, q1)
                bonus = 0.5 * (float(W @ sv) - qv)
                wv['B'] = math.expm1(float(W @ np.log1p(gb)) + bonus); wv['C'] = math.expm1(float(W @ np.log1p(gc)) + bonus)
            names = ['A1', 'B', 'C'] if var == 'S2' else ['A1', 'A2', 'B', 'C']
            sig = math.sqrt(q2 if var == 'K2' else q1)
            p15 = float(np.mean([P.interp(tabs[0.15], np.array([math.log1p(wv[n])]), np.array([sig]))[0] for n in names]))
            out[var] = dict(mean=float(np.mean([wv[n] for n in names])), worst=min(wv[n] for n in names), p15=p15)
        return dict(var=out, vol=float(v[0]), mdd=float(d[0]))
    base = measure(base_w)
    res = {}
    for k in keys:
        wd = dict(base_w); wd['QQQM'] -= SLOT; wd[k] = wd.get(k, 0) + SLOT
        m = measure(wd)
        vs, per = {}, {}
        for var in IX.VARS:
            x, y = m['var'][var], base['var'][var]
            dd = {'平均': 100 * (x['mean'] - y['mean']), '最悪': 100 * (x['worst'] - y['worst']), '確率': 100 * (x['p15'] - y['p15']),
                  'ぶれ': 100 * (m['vol'] - base['vol']), '最大下落': 100 * (m['mdd'] - base['mdd'])}
            vs[var] = IX.verdict(dd)
            per[var] = {kk: round(vv, 2) for kk, vv in dd.items()}
        res[k] = dict(主=vs['main'], まとめ=IX.summarize(vs), 主のΔ=per['main'], 感度=vs)
    return res


def stage2():
    import numpy as np
    import etf_forward_rank as R
    import etf_forward_combo as CB
    import etf_p15 as P
    import etf_ita_xlk as IX
    import bestpf_ext as X
    import bestpf_eval as E
    t0 = time.time()
    doc = json.load(open(OUT))
    assert doc.get('stage') in (1, 2), '第1段を先に回す'
    log('① 既存の行（bestpf_ext.rank_result）')
    res = X.rank_result()
    rows, chains = res['rows'], res['chains']
    k1, k2 = R.months(*R.A1), R.months(*R.A2)
    T1, T2 = len(k1), len(k2)
    combinable = {c for c in rows if all(m in chains[c] for m in k1)}
    log('  組み合わせに使える既存の行', sorted(combinable))
    ident = {}
    for c in combinable:
        s = {c, R.DATA[c][0]}
        veh = str(R.C[c].get('veh', '')).split('（')[0].split(' ')[0].strip()
        if veh:
            s.add(veh)
        ident[c] = s
    if 'EPI_LONG' in combinable:
        ident['EPI_LONG'] |= {'EPI'}
    fxr = fx_monthly()
    ctx = X._STATE['ctx']
    bi = ctx['bi']

    # ── 新しい本の道 ──
    ind49 = M.french_series('49_Industry_Portfolios', want='Average Value Weighted Returns')
    rf = M.ff_factors()['rf']
    dxm, emm = french_region_mkt('Developed_ex_US_3_Factors'), french_region_mkt('Emerging_5_Factors')
    fund_cache = {}

    def fund(t):
        if t not in fund_cache:
            try:
                fund_cache[t] = M.yahoo(t)
            except Exception:
                fund_cache[t] = {}
        return fund_cache[t]

    def usd_series(rep):
        raw = M.yahoo(rep['y'])
        if rep['us']:
            return {m: v for m, v in raw.items() if m <= R.A1[1]}
        return {m: (1 + v) / (1 + fxr[m]) - 1 for m, v in raw.items() if m in fxr and m <= R.A1[1]}

    def new_asset(key, rep, fixed_proxy=None):
        """新しい本の行と毎月の値。返り値 (row, chain, info) か (None, None, info)"""
        info = dict(t=rep['t'], 名前=rep['nm'], 地域=rep['region'])
        usd = usd_series(rep)
        first = min(usd)
        real_ks = R.months(first, R.A1[1])
        gaps = [m for m in real_ks if m not in usd]
        if gaps:
            info['判定の外'] = f'本物の月に抜けがある（{len(gaps)}か月・最初 {gaps[0]}）'
            return None, None, info
        broken = [m for m in real_ks if usd[m] <= BROKEN_LO or usd[m] >= BROKEN_HI]
        if broken:
            info['判定の外'] = f'本物の月に壊れた値（{broken[:3]}）'
            return None, None, info
        er = (rep['er'] / 100) if rep.get('er') is not None else None
        av = load_av(rep['t'])
        if er is None and av is not None:
            er = av['er']
        er_known = er is not None
        er = er if er_known else 0.0          # 代理の相関は経費率で変わらない。経費率が分からない本は代理を確かめた後で判定の外にする
        hold = []
        if av is not None:
            hold = [(h[0], h[1]) for h in X.holdings_for_R(rep['t'], dict(holdings=av['holdings'])) if h and h[0] and h[0] != 'n/a']
        elif rep['t'] in ('FBT',):
            prof_old = json.load(open(os.path.join(BASE, 'out', 'etf_profiles.json'))).get('etfs') or {}
            hold = R.holdings_of(rep['t'], prof_old, {})
        info['保有の本数'] = len(hold)
        ind_of = None
        if hold:
            ind_of, _sic = X.mapper({t.upper() for t, _ in hold if not t.startswith('*')})
        chain = None
        if first <= k1[0]:
            chain = {m: usd[m] for m in k1}
            info['代理'] = 'なし（本物が 2000-09 からそろう）'
        else:
            last = prev_month(first)
            need = [m for m in k1 if m <= last]
            cands = {}
            if fixed_proxy:
                cands[fixed_proxy] = {m: v - er / 12 for m, v in fund(fixed_proxy).items()}
            else:
                if hold and ind_of:
                    wmap = {}
                    for t, w in hold:
                        k = ind_of(t)
                        if k:
                            wmap[k] = wmap.get(k, 0) + w
                    if wmap:
                        tot = sum(wmap.values())
                        ms = sorted(set.intersection(*[set(ind49[k]) for k in wmap]))
                        cands['French49の保有の混ぜ物'] = {m: sum(w / tot * ind49[k][m] for k, w in wmap.items()) - er / 12 for m in ms}
                        info['French49の重み'] = {k: round(w / tot, 4) for k, w in sorted(wmap.items(), key=lambda kv: -kv[1])}
                if rep['region'] in JKP_ISO:
                    try:
                        j = M.jkp_mkt(JKP_ISO[rep['region']], 'vw')
                        cands[f"JKP {JKP_ISO[rep['region']]} 市場"] = {m: v + rf[m] - er / 12 for m, v in j.items() if m in rf}
                    except Exception as e:  # noqa
                        info['JKP の失敗'] = str(e)[:120]
                if rep['region'] in REG_DEV:
                    cands['French Developed ex US 市場'] = {m: v - er / 12 for m, v in dxm.items()}
                if rep['region'] in REG_EM:
                    cands['French Emerging 市場'] = {m: v - er / 12 for m, v in emm.items()}
                for f in PROXY_FUNDS:
                    s = fund(f)
                    if s:
                        cands[f] = {m: v - er / 12 for m, v in s.items()}
            tried = {}
            for nm, p in cands.items():
                if any(m not in p for m in need):
                    tried[nm] = '2000-09 からつなぎ目までの月がそろわない'
                    continue
                ov = [m for m in real_ks if m in p]
                if len(ov) < 24:
                    tried[nm] = f'重なる月 {len(ov)}'
                    continue
                tried[nm] = round(M.corr([usd[m] for m in ov], [p[m] for m in ov]), 4)
            ok = {nm: v for nm, v in tried.items() if isinstance(v, float)}
            info['代理の候補の相関'] = dict(sorted(tried.items(), key=lambda kv: -(kv[1] if isinstance(kv[1], float) else -9)))
            if not ok:
                info['判定の外'] = 'つなげる代理が無い'
                return None, None, info
            best = max(ok, key=lambda k: ok[k])
            info['代理'] = best
            info['代理の相関'] = ok[best]
            info['つなぎ目'] = f'{last} まで代理・{first} から本物'
            if ok[best] < 0.90:
                info['判定の外'] = f'代理の相関 {ok[best]:.3f} < 0.90（事前登録の線）'
                return None, None, info
            p = cands[best]
            chain = {m: (p[m] if m <= last else usd[m]) for m in k1}
        if not er_known:
            info['判定の外'] = '経費率が分からない（ETFD.csv の列5が空・東証の本）'
            return None, None, info
        us = rep['region'] == 'アメリカ' and rep['us']
        k = (0.10 if rep['region'] == 'アメリカ' else 0.20) if rep['us'] else 0.0
        dy = (rep['dy'] / 100) if rep.get('dy') is not None else ((av or {}).get('dy') or 0.0)
        tax = k * dy
        a1g = R.geo(chain, k1)
        a2g = R.geo(chain, k2)
        expo = None
        if us and hold:
            expo = X.expo_of([key], {key: hold}, lambda t, c=None: ind_of(t), bi)[key]
        if us:
            x = (expo or {}).get('X_ind') or 0.0
            e = (expo or {}).get('e')
            e = R.E_MKT if e is None else e
            bg = R.R_EQ + R.SHRINK * x + (R.REC_A - R.REC_B * e)
        else:
            x, e, bg = 0.0, None, R.R_EQ
        jk = jpm_key(rep)
        if jk is None:
            info['判定の外'] = f"地域 {rep['region']} に JPM の行を当てられない"
            return None, None, info
        cg = (R.H_JPM * R.JPM[jk] / 100 + (R.H - R.H_JPM) * bg) / R.H
        row = dict(ja=rep['nm'], A1_gross=a1g, A2_gross=a2g, A1=a1g - tax, A2=a2g - tax, B=bg - er - tax, C=cg - er - tax,
                   B_gross=bg, C_gross=cg, B_X=x, record_share_e=e, er_vehicle=er, tax_drag=tax, tax_k=k, dy=dy, jpm=jk, us=us,
                   top_industries=(expo or {}).get('top_industries') if us else None,
                   vol_A1=R.vol(chain, k1), maxdd_A1=R.maxdd(chain, k1))
        info.update({'A1': r2(row['A1']), 'A2': r2(row['A2']), 'B': r2(row['B']), 'C': r2(row['C']), '経費率': round(100 * er, 3),
                     '外国税の目減り': r2(tax, 3), 'JPM': jk, 'B_上乗せX(縮める前)': r2(x), '記録の二業種e': None if e is None else round(e, 3),
                     '業種の上位': row['top_industries']})
        return row, chain, info

    # ── 世界B の写しの自己検問（既存の米国の業種の本）──
    rep_chk = {}
    for c in combinable:
        if c in ctx['expo'] and R.C[c]['us'] and c not in ('VOO',) and c in (X.SECTOR_R | X.SECTOR_NEW):
            ex = ctx['expo'][c]
            e = ex['e'] if ex['e'] is not None else R.E_MKT
            bg = R.R_EQ + R.SHRINK * (ex['X_ind'] or 0.0) + (R.REC_A - R.REC_B * e)
            rep_chk[c] = abs(bg - rows[c]['B_gross'])
    assert rep_chk and max(rep_chk.values()) < 1e-12, f'世界B の写しが R と合わない {rep_chk}'
    log('  世界B の写し OK（既存の業種の本', len(rep_chk), '本・最大の差', max(rep_chk.values()), '）')

    # ── FBT（今の形）──
    meta = {c['t']: c for c in doc['候補']}
    fbt_rep = None
    for r in csv.reader(io.StringIO(open(ETFD, 'rb').read().decode('utf-8-sig'))):
        if len(r) > 32 and r[3] in MKT_US and r[1] == 'FBT':
            fbt_rep = dict(t='FBT', y='FBT', us=True, region=r[7], nm=html.unescape(r[2]), er=num(r[5]), dy=num(r[19]))
    fbt_row, fbt_chain, fbt_info = new_asset('FBT', fbt_rep, fixed_proxy='FBIOX')
    log('  FBT', {k: v for k, v in fbt_info.items() if k not in ('代理の候補の相関',)})
    base_w = dict(BASE2)
    if fbt_row is None:
        base_w = {'QQQM': 40, 'SMH': 25, 'ITA': 10, 'XLV': 10}
        log('  FBT の代理が通らない → 今の形は XLV 10 で代える')
    else:
        rows['FBT'], chains['FBT'] = fbt_row, fbt_chain

    # ── ショートリストの家族 → 行 ──
    fam = {f['id']: f for f in doc['家族']}
    fam_rows, infos, outside = {}, {}, {}
    for s in doc['ショートリスト']:
        f = fam[s['家族']]
        members = set(f['本'])
        hit = [c for c in sorted(combinable) if ident.get(c, set()) & members and c not in ('QQQM', 'SMH', 'ITA', 'XLV')]
        if 'EPI' in members and 'EPI_LONG' in combinable:
            hit = ['EPI_LONG']
        if hit:
            fam_rows[s['家族']] = hit[0]
            infos[s['家族']] = dict(t=s['代表'], 既存の行=hit[0], 名前=s['名前'])
            continue
        rep = meta[s['代表']]
        rep_d = dict(t=rep['t'], y=rep['t'], us=rep['市場'] in MKT_US, region=rep['地域'], nm=rep['名前'], er=rep['経費率'], dy=rep['配当利回り'])
        key = 'X_' + rep['t'].replace('.', '_')
        row, chain, info = new_asset(key, rep_d)
        info['家族'] = s['家族']
        infos[s['家族']] = info
        if row is None:
            outside[s['家族']] = info
            log('  判定の外', rep['t'], info.get('判定の外'), '代理', info.get('代理'), info.get('代理の相関'))
            continue
        rows[key], chains[key] = row, chain
        fam_rows[s['家族']] = key
        log('  新しい行', rep['t'], '代理', info.get('代理'), info.get('代理の相関'), 'A1', info['A1'], 'A2', info['A2'], 'B', info['B'], 'C', info['C'])

    # ── 組み合わせの道具（etf_forward_combo の式の写し）──
    assets = list(dict.fromkeys(list(base_w) + list(fam_rows.values()) + ['QQQM', 'SMH', 'ITA']))
    G1 = np.array([[chains[c][m] for m in k1] for c in assets])
    G2 = np.array([[chains[c][m] for m in k2] for c in assets])
    adj = np.array([rows[c]['A1'] - rows[c]['A1_gross'] for c in assets])
    gb0 = np.array([rows[c]['B'] for c in assets]); gc0 = np.array([rows[c]['C'] for c in assets])
    L1, L2 = np.log1p(G1), np.log1p(G2)
    S1 = np.cov(L1, bias=True) * 12; S2 = np.cov(L2, bias=True) * 12
    s1, s2 = np.diag(S1).copy(), np.diag(S2).copy()

    def is_us(c):
        return R.C[c]['us'] if c in R.C else bool(rows[c].get('us'))
    chips = {}
    for c in assets:
        if c == 'VOO':
            chips[c] = CB.CHIPS_MKT
        elif is_us(c):
            chips[c] = float((rows[c].get('top_industries') or {}).get('Chips') or 0.0)
    rest = CB.CHIPS_GAP * CB.CHIPS_MKT / (1 - CB.CHIPS_MKT)
    chips_adj = np.array([((-CB.CHIPS_GAP * chips[c] + rest * (1 - chips[c])) / 2) if c in chips else 0.0 for c in assets])
    tabs = P.dca_tables(20, [0.05, 0.15], log=False)
    tabs_pi = P.dca_tables(20, [0.0, 0.05, 0.10, 0.15], log=False)
    idx = {c: i for i, c in enumerate(assets)}

    def vec(wd):
        tot = sum(wd.values())
        v = np.zeros(len(assets))
        for c, w in wd.items():
            v[idx[c]] += w / tot
        return v

    def measure(wd):
        W = vec(wd)[None, :]
        g, v, d = CB.path_stats(W @ G1, T1)
        a2g = np.expm1(np.log1p(W @ G2).sum(axis=-1) * 12 / T2)
        q1 = float(W[0] @ S1 @ W[0]); q2 = float(W[0] @ S2 @ W[0])
        out = {}
        for var in IX.VARS:
            A1w = float(g[0] + W[0] @ adj); A2w = float(a2g[0] + W[0] @ adj)
            gb, gc = (gb0 + chips_adj, gc0 + chips_adj) if var == 'K4' else (gb0, gc0)
            if var == 'K1':
                Bw, Cw = float(W[0] @ gb), float(W[0] @ gc)
            else:
                sv, qv = (s2, q2) if var == 'K2' else (s1, q1)
                bonus = 0.5 * (float(W[0] @ sv) - qv)
                Bw = math.expm1(float(W[0] @ np.log1p(gb)) + bonus); Cw = math.expm1(float(W[0] @ np.log1p(gc)) + bonus)
            wv = dict(A1=A1w, A2=A2w, B=Bw, C=Cw)
            names = ['A1', 'B', 'C'] if var == 'S2' else ['A1', 'A2', 'B', 'C']
            sig = math.sqrt(q2 if var == 'K2' else q1)
            p15 = float(np.mean([P.interp(tabs[0.15], np.array([math.log1p(wv[n])]), np.array([sig]))[0] for n in names]))
            p5 = 1 - float(np.mean([P.interp(tabs[0.05], np.array([math.log1p(wv[n])]), np.array([sig]))[0] for n in names]))
            out[var] = dict(mean=float(np.mean([wv[n] for n in names])), worst=min(wv[n] for n in names), p15=p15, p5=p5, wv=wv)
        hs = P.hist_success(W, G1, adj, T1)
        return dict(var=out, vol=float(v[0]), mdd=float(d[0]), hs240=float(hs[240][0]), hs180=float(hs[180][0]), q1=q1)

    def delta(a, b, var):
        x, y = a['var'][var], b['var'][var]
        return {'平均': 100 * (x['mean'] - y['mean']), '最悪': 100 * (x['worst'] - y['worst']), '確率': 100 * (x['p15'] - y['p15']),
                '五未満': 100 * (x['p5'] - y['p5']), 'ぶれ': 100 * (a['vol'] - b['vol']), '最大下落': 100 * (a['mdd'] - b['mdd'])}

    def judge(a, b):
        per, vs = {}, {}
        for var in IX.VARS:
            d = delta(a, b, var)
            vs[var] = IX.verdict(d)
            per[var] = dict(Δ={k: round(v, 2) for k, v in d.items()}, 判定=vs[var])
        return dict(感度ごと=per, 主=vs['main'], まとめ=IX.summarize(vs))

    def show(m):
        x = m['var']['main']
        return {'平均': round(100 * x['mean'], 2), '最悪': round(100 * x['worst'], 2), '確率': round(100 * x['p15'], 1),
                '五未満': round(100 * x['p5'], 1), 'ぶれ': round(100 * m['vol'], 1), '最大下落': round(100 * m['mdd'], 1),
                '世界ごと': {k: round(100 * v, 2) for k, v in x['wv'].items()},
                '過去20年で15%以上': round(100 * m['hs240'], 1), '過去15年で15%以上': round(100 * m['hs180'], 1)}

    # ── 自己検問: etf_ita_xlk の席A ──
    ix = json.load(open(os.path.join(BASE, 'out', 'etf_ita_xlk.json')))['slots']['A']['table']
    chk = {}
    for nm, wd, ref in (('ITA', {'QQQM': 50, 'SMH': 20, 'ITA': 15}, ix['ITA']), ('QQQM', {'QQQM': 65, 'SMH': 20}, ix['QQQM'])):
        sm = show(measure(wd))
        diff = {k: (sm[k], ref[k]) for k in ('平均', '最悪', '確率', '五未満', 'ぶれ', '最大下落') if abs(sm[k] - ref[k]) > (0.011 if k in ('平均', '最悪') else 0.11)}
        chk[nm] = dict(ours={k: sm[k] for k in ('平均', '最悪', '確率', '五未満', 'ぶれ', '最大下落')}, ref={k: ref[k] for k in ('平均', '最悪', '確率', '五未満', 'ぶれ', '最大下落')}, diff=diff)
    log('  自己検問（etf_ita_xlk の席A）', chk)
    if any(v['diff'] for v in chk.values()):
        raise SystemExit(f'自己検問が通らない: {chk}')

    # ── 判定 ──
    base_m = measure(base_w)
    log('今の形（第2段）', base_w, show(base_m))
    results = {}
    for fid, key in fam_rows.items():
        wd = dict(base_w); wd['QQQM'] -= SLOT; wd[key] = wd.get(key, 0) + SLOT
        m = measure(wd)
        j = judge(m, base_m)
        pr = {c: w * (NET - SLOT) / NET for c, w in base_w.items()}; pr[key] = pr.get(key, 0) + SLOT
        w10 = dict(base_w); w10['QQQM'] -= 2 * SLOT; w10[key] = w10.get(key, 0) + 2 * SLOT
        mp, m10 = measure(pr), measure(w10)
        results[fid] = dict(家族=fid, 代表=infos[fid]['t'], 行=key, 名前=infos[fid].get('名前'), 物差し=show(m), 判定=j,
                            参考_按分で足す=dict(物差し=show(mp), 判定=judge(mp, base_m)),
                            参考_10足す=dict(物差し=show(m10), 判定=judge(m10, base_m)))
        jj = j['感度ごと']['main']['Δ']
        log(f"  #{fid:3d} {infos[fid]['t']:8} 主 {j['主']:6} まとめ {j['まとめ']:10} Δ平均 {jj['平均']:+.2f} Δ最悪 {jj['最悪']:+.2f} Δ確率 {jj['確率']:+.2f} Δぶれ {jj['ぶれ']:+.2f} Δ下落 {jj['最大下落']:+.2f} "
            f"| 感度 {[j['感度ごと'][v]['判定'] for v in IX.VARS]}")

    # ── bestpf の物差し（参考）──
    try:
        pi, _, _ = E.load_pi()
        Dmap, _, _ = E.load_D(rows, assets)
        gD = np.array([Dmap[c] for c in assets])

        def p15pi(wd):
            W = vec(wd)
            m = measure(wd)['var']['main']['wv']
            q = float(W @ S1 @ W); bonus = 0.5 * (float(W @ s1) - q); sig = math.sqrt(q)
            wv = dict(m, D=math.expm1(float(W @ np.log1p(gD)) + bonus))
            out = {}
            for tau in (0.15, 0.05):
                tot = sum(pi[k] * (float(P.interp(tabs_pi[tau], np.array([math.log1p(wv[k])]), np.array([sig]))[0]) if tau >= 0.10 else
                                   1 - float(P.interp(tabs_pi[tau], np.array([math.log1p(wv[k])]), np.array([sig]))[0])) for k in E.WORLDS if pi.get(k, 0) > 0)
                out['P15π' if tau == 0.15 else 'P5π（5%未満）'] = round(100 * tot / sum(pi[k] for k in E.WORLDS if pi.get(k, 0) > 0), 1)
            out['最悪の世界（5つ）'] = round(100 * min(wv.values()), 2)
            return out
        ref_pi = {'今の形': p15pi(base_w)}
        for fid, key in fam_rows.items():
            wd = dict(base_w); wd['QQQM'] -= SLOT; wd[key] = wd.get(key, 0) + SLOT
            ref_pi[results[fid]['代表']] = p15pi(wd)
    except Exception as e:  # noqa
        ref_pi = {'失敗': str(e)[:200]}

    firm = sorted([r for r in results.values() if r['判定']['まとめ'] == '堅い価値あり'],
                  key=lambda r: (-r['判定']['感度ごと']['main']['Δ']['平均'], -r['判定']['感度ごと']['main']['Δ']['最悪']))
    combo = None
    if len(firm) >= 2:
        a, b = firm[0]['行'], firm[1]['行']
        wd = dict(base_w); wd['QQQM'] -= 2 * SLOT; wd[a] = wd.get(a, 0) + SLOT; wd[b] = wd.get(b, 0) + SLOT
        mc = measure(wd)
        combo = dict(形=wd, 物差し=show(mc), 判定=judge(mc, base_m))
    # ───────────── 事後（判定に使わない・結果を見た後に足した点検）─────────────
    posthoc = {}
    try:
        posthoc = run_posthoc(dict(rows=rows, chains=chains, assets=assets, idx=idx, measure=measure, judge=judge, show=show, vec=vec,
                                   base_w=base_w, base_m=base_m, fam_rows=fam_rows, infos=infos, results=results, firm=firm,
                                   gb0=gb0, gc0=gc0, R=R, X=X, CB=CB, P=P, IX=IX, bi=bi, k1=k1, k2=k2, new_asset=new_asset,
                                   fbt_rep=fbt_rep, np=np, set_bc=None))
    except Exception as e:  # noqa
        import traceback
        posthoc = {'失敗': traceback.format_exc()[-1500:]}
        log('事後の点検が失敗', str(e)[:300])
    if firm:
        concl = f"『堅い価値あり』{len(firm)}家族。勧めるのは {firm[0]['代表']}（家族 #{firm[0]['家族']}）"
    else:
        concl = '『堅い価値あり』の家族は無い＝決まりでは今のまま'
    doc['stage'] = 2
    doc['stage2'] = dict(generated=datetime.date.today().isoformat(), 今の形=dict(重み=base_w, SHLD='ITA で代える（A1 をつなげない）',
                         FBT=fbt_info, 物差し=show(base_m)), 自己検問=chk,
                         世界Bの写し={c: v for c, v in rep_chk.items()}, 家族の行=infos, 判定の外=outside, 判定=results,
                         参考_bestpfの物差し=ref_pi, 参考_上位2本を5ずつ=combo, 結論=concl,
                         事後_判定に使わない=posthoc,
                         注='Δ＝候補の形 − 今の形（%pt）。判定の決まりは etf_ita_xlk と同じ。採否はユーザー', secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    log('結論:', concl)
    log('→', OUT, f'（{round(time.time() - t0)}秒）')

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'stage1'
    if cmd == 'stage1':
        stage1()
    elif cmd == 'stage2':
        stage2()
    else:
        raise SystemExit(f'不明な指示: {cmd}')
