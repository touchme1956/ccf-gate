#!/usr/bin/env python3
"""night/style_combo_check.py — 型（大型・小型×割安・成長・勢い・質・低ぶれ・高配当・等加重・NASDAQ100・市場）の2〜3本の組で、
主役が入れ替わっても市場に勝ち続けた組はあるか（2026-11-01・参考・配分は変えない）

ユーザー「例えば大型バリューと小型バリューと組み合わせるとかなんかいい方法ないの？」（ndx_sv_check の続き）
★部品・組・期間・物差し・選び方はこの頭に書いたとおりで、結果を見る前にこのファイルをコミットする。

部品（月次・ドル・配当込み・費用の前＝器は経費率を足し戻す・bestfund_data.build_chain のつなぎ。← の右は器より前の代わり）:
  NDX NASDAQ100＝QQQ ← ^NDX＋配当の置き値 ← French のテック3業種65%＋市場35%
  LG 大型グロース＝VUG ← VIGRX ← French BIG LoBM ／ LV 大型バリュー＝VTV ← VIVAX ← French BIG HiBM
  SG 小型グロース＝VBK ← French SMALL LoBM（この道具の中でつなぐ）／ SV 小型バリュー＝VBR ← VISVX ← French SMALL HiBM
  SC 小型株＝IJR ← French の時価総額の下位30% ／ MOM 勢い＝MTUM ← French BIG HiPRIOR ／ QUAL 質＝QUAL ← French BIG HiOP
  LOWVOL 低ぶれ＝USMV ← French の分散の低い五分位 ／ HIDIV 高配当＝VYM ← French の配当利回り上位30% ／ EQW 等加重＝RSP ← French の時価総額の第6〜10十分位の平均
  MKT 市場＝French の米国市場（CRSP 全上場）＝比べる相手でもある
組: 12本から2本（等分）66通り・3本（等分）220通り＝286通り（毎月この比に戻す）。参考に 4つの角（LG・LV・SG・SV の等分）と1本ずつ
期間: 主＝1963-07〜（QUAL・LOWVOL の代わりが始まる月）〜3本がそろう最後の月。確かめ＝1927-07〜（QUAL・LOWVOL を含まない組だけ）
物差し（市場 MKT との差＝幾何の年率の差）:
  転がる10年（1か月ずつ）: 市場に勝った割合（窓の起点で前半 〜1989-12／後半 1990-01〜 に分けても）・中央・下位10%点・最悪
  暦の前半 1963-07〜1994-12・後半 1995-01〜の年率の差／転がる20年: 勝った割合・最悪／20年の積立の最終額÷市場の積立: 1以上の割合・最悪
  本物の器の期間 2004-03〜の年率の差（MOM は2013-05・QUAL は2013-08・LOWVOL は2011-11 までは代わり）／最大下落・ぶれ
  補い合い: 10年の窓で組の全部の本が市場に負けた割合・本どうしの転がる10年の市場との差の相関（平均）
選び方（堅い組）: ①転がる10年で市場に勝った割合が前半・後半とも90%以上 ∧ ②暦の前半・後半とも市場に勝つ ∧ ③20年の積立が市場以上だった窓が90%以上
  → 転がる10年の最悪が良い順（同じなら中央が高い順）
今の物差しでの確かめ（best15r と同じ: 業種の基礎率の物差し FastBR〔主＝20年の値〕と感度6本・元の物差し unx_assets.measure の USD・崩れあり・100年の代用・中身の集中）:
  測れるのは best15r の POOL にある本だけ＝NDX→QQQM・LG→VUG・LV→VTV・SV→VBR・SC→IJR・MKT→VOO（SG・MOM・QUAL・LOWVOL・HIDIV・EQW を含む組は歴史だけ:
  VBK・USMV は物差しの行が無い／VYM・RSP は2000年からの系列が無い／MTUM・QUAL は中身が無く楽天でも買えない）
  形（ETF 側100%）: 今 NASDAQ100 50/SMH 20/ITA 20/XLV 10 ／ NASDAQ100 50/VBR 50 ／ VTV 50/VBR 50（ユーザーの例）／
  堅い組のうち測れる組の上位5つ（等分）
  上乗せの感度（事後でなく先に決める）: P1＝B の世界の型の上乗せ（unx_assets の B_X×0.5）を VUG・VTV・VBR・IJR から引く／
  P2＝さらに C・D の VUG・VTV・VBR・IJR を VOO と同じに／P3＝どの本も期待値を VOO と同じにし基礎率の補正も0（差は分散の上乗せとぶれだけ）
楽天で買えるか（out/broker_lineup.json・2026-08-24 の写し）: 部品の器ごとに印を付ける（MOM は楽天では SMT 米国株式モメンタム〔投信・0.77%・作り方が違う〕だけ）
⚠ 限界: 器より前は代わり・紙の上（売買の費用なし）・286通りから選ぶので過去に合わせすぎうる（前半・後半の両方を課して弱める）・
  型の上乗せは同じデータで見つかったもの（後知恵）・米国だけ・税は入らない・等分以外の比は測らない
使い方: python3 night/style_combo_check.py → out/style_combo_check.json
"""
import contextlib, io, itertools, json, math, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'style_combo_check.json')

from ndx_sv_check import Roll, mrange, geo, pct, stats, ratio_stats   # noqa: E402

BLOCKS = {'NDX': ('NASDAQ100', 'NDX'), 'LG': ('大型グロース', 'GROWTH'), 'LV': ('大型バリュー', 'VALUE'), 'SG': ('小型グロース', None),
          'SV': ('小型バリュー', 'SMALLV'), 'SC': ('小型株', 'SMALL'), 'MOM': ('勢い', 'MOM'), 'QUAL': ('質', 'QUALITY'),
          'LOWVOL': ('低ぶれ', 'LOWVOL'), 'HIDIV': ('高配当', 'HIDIV'), 'EQW': ('等加重', 'EQW'), 'MKT': ('市場', None)}
VEHICLE = {'NDX': 'QQQM', 'LG': 'VUG', 'LV': 'VTV', 'SG': 'VBK', 'SV': 'VBR', 'SC': 'IJR', 'MOM': 'MTUM', 'QUAL': 'QUAL',
           'LOWVOL': 'USMV', 'HIDIV': 'VYM', 'EQW': 'RSP', 'MKT': 'VOO'}
FWD_ETF = {'NDX': 'QQQM', 'LG': 'VUG', 'LV': 'VTV', 'SV': 'VBR', 'SC': 'IJR', 'MKT': 'VOO'}
STYLE_ETF = ['VUG', 'VTV', 'VBR', 'IJR']
MAIN0, LONG0, HALF_START, CAL_HALF, REAL0 = 196307, 192707, 199001, 199501, 200403
NO_LONG = {'QUAL', 'LOWVOL'}
TOPK = 5
REF_FORMS = {'今 NASDAQ100 50/SMH 20/ITA 20/XLV 10': {'QQQM': 50, 'SMH': 20, 'ITA': 20, 'XLV': 10},
             'NASDAQ100 50/VBR 50': {'QQQM': 50, 'VBR': 50},
             'VTV 50/VBR 50（大型バリュー＋小型バリュー）': {'VTV': 50, 'VBR': 50}}


def name_of(c):
    return '＋'.join(BLOCKS[b][0] for b in c)


def load():
    import bestfund_data as D
    s = {}
    for b, (_, key) in BLOCKS.items():
        if b == 'MKT':
            s[b] = dict(D.french_mkt())
        elif b == 'SG':
            D.ACTUAL_ER.setdefault('VBK', 0.0007)
            r, segs, _ = D.build_chain('SG', [('actual', ('yahoo', 'VBK'), 'VBK'),
                                             ('proxy', ('french_pf', '6_Portfolios_2x3', 'SMALL LoBM', 'Average Value Weighted Returns'),
                                              'French の SMALL LoBM')])
            s[b] = r
        else:
            s[b] = D.build_chain(key)[0]
    last = min(max(v) for v in s.values())
    return s, last


def build_series(s, ks, combos):
    r = {b: {m: s[b][m] for m in ks} for b in s if all(m in s[b] for m in ks)}
    for c in combos:
        if all(b in r for b in c):
            r[c] = {m: sum(r[b][m] for b in c) / len(c) for m in ks}
    return r


def mdd(rr, ks):
    v, pk, w = 1.0, 1.0, 0.0
    for m in ks:
        v *= 1 + rr[m]
        pk = max(pk, v)
        w = min(w, v / pk - 1)
    return w


def metrics(R, r, ks, c, comps):
    n = len(ks)
    i10, i20 = range(0, n - 120 + 1), range(0, n - 240 + 1)
    ex10 = np.array([R.ann(c, i, 120) - R.ann('MKT', i, 120) for i in i10])
    first = np.array([ks[i] < HALF_START for i in i10])
    ex20 = np.array([R.ann(c, i, 240) - R.ann('MKT', i, 240) for i in i20])
    dca = np.array([R.dca(c, i, 240) / R.dca('MKT', i, 240) for i in i20])
    h1 = [m for m in ks if m < CAL_HALF]; h2 = [m for m in ks if m >= CAL_HALF]; re = [m for m in ks if m >= REAL0]
    o = dict(名前=name_of(comps), 本=list(comps),
             十年_勝ち=round(float((ex10 > 0).mean()), 3), 十年_勝ち_前半=round(float((ex10[first] > 0).mean()), 3),
             十年_勝ち_後半=round(float((ex10[~first] > 0).mean()), 3), 十年_中央=pct(float(np.median(ex10))),
             十年_下位10=pct(float(np.percentile(ex10, 10))), 十年_最悪=pct(float(ex10.min())),
             暦の前半の差=pct(geo(r[c], h1) - geo(r['MKT'], h1)), 暦の後半の差=pct(geo(r[c], h2) - geo(r['MKT'], h2)),
             二十年_勝ち=round(float((ex20 > 0).mean()), 3), 二十年_最悪=pct(float(ex20.min())),
             積立二十年_一以上=round(float((dca >= 1).mean()), 3), 積立二十年_最悪=round(float(dca.min()), 3), 積立二十年_中央=round(float(np.median(dca)), 3),
             本物の器の期間の差=pct(geo(r[c], re) - geo(r['MKT'], re)),
             年率=pct(geo(r[c], ks)), 最大下落=pct(mdd(r[c], ks), 1), ぶれ=pct(float(np.std([r[c][m] for m in ks]) * math.sqrt(12)), 1))
    if len(comps) > 1:
        exs = {b: np.array([R.ann(b, i, 120) - R.ann('MKT', i, 120) for i in i10]) for b in comps}
        allbad = np.logical_and.reduce([exs[b] <= 0 for b in comps])
        cs = [float(np.corrcoef(exs[a], exs[b])[0, 1]) for a, b in itertools.combinations(comps, 2)]
        o.update(全部負け=round(float(allbad.mean()), 3), 市場との差の相関の平均=round(float(np.mean(cs)), 3))
    o['堅い'] = bool(o['十年_勝ち_前半'] >= .90 and o['十年_勝ち_後半'] >= .90 and o['暦の前半の差'] > 0 and o['暦の後半の差'] > 0
                    and o['積立二十年_一以上'] >= .90)
    return o


def long_check(s, last, combos):
    ks = mrange(LONG0, last)
    use = [c for c in combos if not (set(c) & NO_LONG)]
    r = build_series({b: v for b, v in s.items() if b not in NO_LONG}, ks, use)
    R = Roll({k: v for k, v in r.items()}, ks)
    out = {}
    n = len(ks)
    for c in use:
        if c not in r:
            continue
        ex10 = np.array([R.ann(c, i, 120) - R.ann('MKT', i, 120) for i in range(0, n - 120 + 1)])
        dca = np.array([R.dca(c, i, 240) / R.dca('MKT', i, 240) for i in range(0, n - 240 + 1)])
        out[c] = dict(十年_勝ち=round(float((ex10 > 0).mean()), 3), 十年_最悪=pct(float(ex10.min())),
                      積立二十年_一以上=round(float((dca >= 1).mean()), 3), 積立二十年_最悪=round(float(dca.min()), 3))
    return out


def forward(forms):
    import best15_check as B
    import best15r_check as BR
    import unx_assets as U
    import upside_check as UC
    with contextlib.redirect_stdout(io.StringIO()):
        res = U.build()
    rows, chains = res['rows'], res['chains']
    B.century_extend(U)
    P = BR.POOL
    for f in forms.values():
        miss = [c for c in f if c not in P]
        if miss:
            raise SystemExit(f'物差しに無い本: {miss}')
    fast, cent = B.Fast(U, rows, chains, P), B.Cent(U, P)
    fbr = BR.FastBR(fast)
    st = BR.industry_state()
    vec, _ = BR.industry_vectors(U, rows)
    win = list(dict.fromkeys(st['top5'] + st['rec']))
    IND = np.array([[(st['mkt'].get(k, 0.0) if c == 'VOO' else vec.get(c, {}).get(k, 0.0)) for k in win] for c in P])
    adj = {nm: BR.adj_vector(vec, st, rt, P)[0] for nm, rt in BR.RATES.items()}
    a0 = adj['主（20年の値）']
    names = list(forms)
    W = np.array([[forms[n].get(c, 0) for c in P] for n in names], dtype=np.float64)
    Wn = W / W.sum(axis=1, keepdims=True)

    def ve(v):
        return {'主': lambda: fbr.eval(W, a0), '10年の値': lambda: fbr.eval(W, adj['10年の値']),
                '1位の業種を強く': lambda: fbr.eval(W, adj['1位の業種を強く（10年の値・Chips −4.0）']),
                '主の半分': lambda: fbr.eval(W, adj['主の半分']), '分散の上乗せなし': lambda: fbr.eval(W, a0, nobonus=True),
                '共分散をA2の窓から': lambda: fbr.eval(W, a0, cov2=True)}[v]()
    V = {v: ve(v) for v in BR.VARS}
    # 上乗せの感度 P1〜P3
    g0 = (fbr.gB.copy(), fbr.gC.copy(), fbr.gD.copy())
    io_ = P.index('VOO')
    sens = {}
    try:
        for c in STYLE_ETF:
            fbr.gB[P.index(c)] -= 0.5 * float(rows[c]['B_X'])
        sens['P1 B の世界の型の上乗せなし'] = fbr.eval(W, a0)
        for c in STYLE_ETF:
            fbr.gC[P.index(c)], fbr.gD[P.index(c)] = fbr.gC[io_], fbr.gD[io_]
        sens['P2 B・C・D の型の上乗せなし'] = fbr.eval(W, a0)
        fbr.gB[:], fbr.gC[:], fbr.gD[:] = fbr.gB[io_], fbr.gC[io_], fbr.gD[io_]
        sens['P3 どの本も市場と同じ期待値・補正なし'] = fbr.eval(W, np.zeros(len(P)))
    finally:
        fbr.gB, fbr.gC, fbr.gD = g0
    E, cs = V['主'], cent.eval(W)
    with contextlib.redirect_stdout(io.StringIO()):
        tab = U.measure(forms, rows, chains, mega=U.mega_map(rows, sorted({a for f in forms.values() for a in f} | {'VOO'})))
    out = {}
    for j, nm in enumerate(names):
        f = forms[nm]
        o = tab[UC.W_CRASH][nm]
        cm = U.century_monthly(f)
        out[nm] = dict(
            形=f,
            基礎率の物差し=dict(P15π=round(100 * float(E['P15'][j]), 2), 平均=round(100 * float(E['mean_pi'][j]), 2),
                            最悪の世界=round(100 * float(E['worst'][j]), 2), 五パーセント未満=round(100 * float(E['P5'][j]), 2),
                            最大下落=round(100 * float(E['mdd'][j]), 1), ぶれ=round(100 * float(E['vol'][j]), 1)),
            基礎率の感度ごとの今との差={v: dict(P15=round(100 * float(V[v]['P15'][j] - V[v]['P15'][0]), 2),
                                        平均=round(100 * float(V[v]['mean_pi'][j] - V[v]['mean_pi'][0]), 3),
                                        五パーセント未満=round(100 * float(V[v]['P5'][j] - V[v]['P5'][0]), 2)) for v in BR.VARS},
            上乗せの感度={k: dict(P15π=round(100 * float(e['P15'][j]), 2), 平均=round(100 * float(e['mean_pi'][j]), 2),
                               五パーセント未満=round(100 * float(e['P5'][j]), 2),
                               今との差=dict(P15=round(100 * float(e['P15'][j] - e['P15'][0]), 2),
                                          平均=round(100 * float(e['mean_pi'][j] - e['mean_pi'][0]), 3),
                                          五パーセント未満=round(100 * float(e['P5'][j] - e['P5'][0]), 2))) for k, e in sens.items()},
            元の物差し=dict(P15π=o['P15π'], 平均=o['π加重の平均の年率'], 五パーセント未満=o['P5π（5%未満）'], 最悪の世界=o['最悪の世界'],
                         最大下落=o['最大下落'], ぶれ=o['ぶれ'], 世界=o['世界ごとの年率'], 過去の転がる20年で15パーセント以上=o['過去の転がる20年で15%以上']),
            百年=dict(三十年の中央=round(float(cs['c30med'][j]), 3), 三十年の最悪=round(float(cs['c30min'][j]), 3),
                    詳細=(None if cm is None else U.strip_century(cm))),
            勝ち業種の中身の比重={k: round(100 * float(Wn[j] @ IND[:, i]), 1) for i, k in enumerate(win)},
            中身の集中=B.lookthrough(f))
    return out


def main():
    t0 = time.time()
    s, last = load()
    keys = list(BLOCKS)
    combos = [tuple(c) for k in (2, 3) for c in itertools.combinations(keys, k)]
    corners = ('LG', 'LV', 'SG', 'SV')
    ks = mrange(MAIN0, last)
    r = build_series(s, ks, combos + [corners])
    missing = [b for b in keys if b not in r]
    if missing:
        raise SystemExit(f'主の期間に月が欠けた部品: {missing}')
    R = Roll(r, ks)
    rows = {c: metrics(R, r, ks, c, c) for c in combos}
    singles = {b: metrics(R, r, ks, b, (b,)) for b in keys if b != 'MKT'}
    corner = metrics(R, r, ks, corners, corners)
    lc = long_check(s, last, combos + [corners] + [(b,) for b in keys if b not in NO_LONG and b != 'MKT'])
    bl = json.load(open(os.path.join(BASE, 'out', 'broker_lineup.json')))['etfs']
    raku = {b: (VEHICLE[b] in bl) for b in keys}
    for c, o in list(rows.items()) + [(corners, corner)]:
        o['確かめ_1927年から'] = lc.get(c)
        o['楽天で器を買える'] = all(raku[b] for b in c)
        o['今の物差しで測れる'] = all(b in FWD_ETF for b in c)
    for b, o in singles.items():
        o['確かめ_1927年から'] = lc.get((b,))
        o['楽天で器を買える'] = raku[b]
    firm = sorted([c for c, o in rows.items() if o['堅い']], key=lambda c: (-rows[c]['十年_最悪'], -rows[c]['十年_中央']))
    measurable = [c for c in firm if rows[c]['今の物差しで測れる']][:TOPK]
    forms = dict(REF_FORMS)
    for c in measurable:
        f = {}
        for b in c:
            f[FWD_ETF[b]] = f.get(FWD_ETF[b], 0) + round(100 / len(c), 4)
        nm = f'堅い組 {name_of(c)}'
        if all(set(f) != set(g) or any(abs(f[k] - g.get(k, 0)) > 1e-6 for k in f) for g in forms.values()):
            forms[nm] = f
    fwd = forward(forms)
    res = dict(generated=time.strftime('%Y-%m-%d'), tool='night/style_combo_check.py', kind='参考（配分は変えない・選び方は道具の頭に固定）',
               question='型の2〜3本の組で、主役が入れ替わっても市場に勝ち続けた組はあるか', 主の期間=f'{ks[0]}〜{ks[-1]}', 最後の月=last,
               部品={b: dict(名前=BLOCKS[b][0], 器=VEHICLE[b], 楽天=raku[b]) for b in keys},
               一本ずつ=singles, 四つの角=corner,
               堅い組の数=len(firm), 堅い組=[dict(**rows[c]) for c in firm],
               ユーザーの例_大型バリューと小型バリュー=rows[('LV', 'SV')], 参考_NASDAQ100と小型バリュー=rows[('NDX', 'SV')],
               全部の組=[dict(**o) for o in sorted(rows.values(), key=lambda o: (-o['十年_最悪'], -o['十年_中央']))],
               今の物差しでの確かめ=fwd, secs=None)
    res['secs'] = round(time.time() - t0)
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    print('堅い組', len(firm), '/', len(rows))
    for c in firm[:15]:
        o = rows[c]
        print(f"  {o['名前']:28s} 十年勝ち {o['十年_勝ち_前半']}/{o['十年_勝ち_後半']} 最悪 {o['十年_最悪']} 中央 {o['十年_中央']} 前半 {o['暦の前半の差']} 後半 {o['暦の後半の差']} 本物 {o['本物の器の期間の差']} 積立最悪 {o['積立二十年_最悪']} 楽天 {o['楽天で器を買える']}")
    o = rows[('LV', 'SV')]
    print('大型バリュー＋小型バリュー', {k: o[k] for k in ('十年_勝ち_前半', '十年_勝ち_後半', '十年_最悪', '暦の前半の差', '暦の後半の差', '本物の器の期間の差', '全部負け', '堅い')})
    print('→', OUT, res['secs'], 's')


if __name__ == '__main__':
    main()
