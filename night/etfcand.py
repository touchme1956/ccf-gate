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
        d = dict(d, tax_k=k, tax_drag=drag, first=min(ry), ry=ry)
        d['w20'] = all(m in ry for m in k20)
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


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'stage1'
    if cmd == 'stage1':
        stage1()
    else:
        raise SystemExit(f'不明な指示: {cmd}')
