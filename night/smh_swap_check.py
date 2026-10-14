#!/usr/bin/env python3
"""night/smh_swap_check.py — SHLD を SMH に変えるのは？（2026-10-14・ユーザー「SHLD→SMHは？」・ndx_swap の続き）

読むだけ。門・採点・配分（portfolio.json）・注文書には触れない。事前登録 out/smh_swap_prereg.json（dc1a98db）どおり。
  F_cur … 今 NASDAQ100 40 / SMH 15 / 楽天・プラス・SOX 10 / ITA 5 / SHLD 5 / XLV 5 / FBT 5（個別株15は物差しの外）
  E … SHLD 5 を SMH へ（SMH 20）／参考 B … SHLD 5 を NASDAQ100 へ（ndx_swap の B）／参考 F … ITA 5 を SMH へ
判定は ndx_swap と同じ（night/ndx_swap_check.py の variants・judge・reading をそのまま使う）＋上振れの読み（upside_check の R2・R3）。
回帰の検査: ① F_cur が out/upside_check.json と小数1桁で一致 ② 感度の計算の主が measure と 1e-9 以内 ③ B が out/ndx_swap_check.json の B と一致。
注文書は night/shadow_seats.js --weights（out/_nx_cache/smh_swap/orders_*.json）。--orders を付けると先に4通りを回す（1回約2分）。

使い方: python3 night/smh_swap_check.py [--orders]  → out/smh_swap_check.json
"""
import datetime, json, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import unx_assets as U        # noqa: E402
import upside_check as UC     # noqa: E402
import ndx_swap_check as N    # noqa: E402

OUT = os.path.join(BASE, 'out', 'smh_swap_check.json')
PREREG = os.path.join(BASE, 'out', 'smh_swap_prereg.json')
ORD = os.path.join(BASE, 'out', '_nx_cache', 'smh_swap')
W_CRASH, W_DC = UC.W_CRASH, UC.W_DC
CUR = N.CUR
KEYS = {'E': 'E_SHLD→SMH（SHLD 5 を SMH へ）', 'B': '参考 B_SHLD→NDX（直前の ndx_swap の B）',
        'F': '参考 F_ITA→SMH（ITA 5 を SMH へ・模型では SHLD≒ITA なので同じ問いの裏）'}
COMPS = [('SHLD の価値（SMH と比べる・今 − E）', CUR, KEYS['E'], True),
         ('参考: SMH へ回した形 − NASDAQ100 へ回した形（E − B）', KEYS['E'], KEYS['B'], False),
         ('参考: ITA の価値（SMH と比べる・今 − F）', CUR, KEYS['F'], False)]
ORDER_RUNS = {'F_cur': None, 'E': 'SMH=20,SHLD=0', 'B': 'IFREE-NDX=45,SHLD=0', 'F': 'SMH=20,ITA=0'}


def upside_read(up, a, b):
    """upside_check の R2・R3（a＝案・b＝今。upside_check と同じく表示の値〔丸めた値〕で比べ、丸める前の差も残す）"""
    ra, rb = up[a], up[b]
    ua, ub = ra['上振れ'], rb['上振れ']
    d = dict(ΔP20=round(ua['P20（道の束）'] - ub['P20（道の束）'], 1), ΔP20_A2を外す=round(ua['P20（A2を外す）'] - ub['P20（A2を外す）'], 1),
             ΔP25=round(ua['P25（道の束）'] - ub['P25（道の束）'], 1),
             Δ90点=round(ua['内部収益率の分位']['90%点'] - ub['内部収益率の分位']['90%点'], 1),
             Δ中央=round(ua['内部収益率の分位']['50%点'] - ub['内部収益率の分位']['50%点'], 1),
             Δ10点=round(ua['内部収益率の分位']['10%点'] - ub['内部収益率の分位']['10%点'], 1),
             ΔP15π=round(ra['P15π'] - rb['P15π'], 1), ΔP5=round(ra['P5π（5%未満）'] - rb['P5π（5%未満）'], 1),
             ΔP0=round(ra['P0π（元本割れ）'] - rb['P0π（元本割れ）'], 1),
             Δ最悪の世界=round(ra['最悪の世界'] - rb['最悪の世界'], 2), Δ最大下落=round(ra['最大下落'] - rb['最大下落'], 1),
             Δぶれ=round(ra['ぶれ'] - rb['ぶれ'], 1), **{'Δ崩れ16〜18年目': round(ra['崩れ2000型_16〜18年目'] - rb['崩れ2000型_16〜18年目'], 2)})
    raw_a, raw_b = ra.get('_raw'), rb.get('_raw')
    if raw_a and raw_b:
        d['丸める前'] = {'Δ最悪の世界': round(100 * (raw_a['worst'] - raw_b['worst']), 4), 'ΔP5': round(100 * (raw_a['P5'] - raw_b['P5']), 4),
                       'Δ最大下落': round(100 * (raw_a['mdd'] - raw_b['mdd']), 4)}
    free = d['ΔP20'] >= 1.0 and d['Δ最悪の世界'] >= 0 and d['ΔP5'] <= 0 and d['Δ最大下落'] >= 0
    d['読み（R2）'] = ('ただの上振れ（代金なし）' if free else ('代金つきの上振れ' if d['ΔP20'] >= 1.0 else '上振れは増えない（+1.0pt 未満）'))
    if d['ΔP20'] >= 1.0 and d['ΔP20_A2を外す'] < 1.0:
        d['読み（R3）'] = '直近15年の流れが続く世界に頼る'
    return d


def main():
    t0 = time.time()
    if '--orders' in sys.argv:
        N.run_orders(ORDER_RUNS, ORD)
    P = json.load(open(PREREG))
    F = dict(P['forms_etf_side_percent_of_total'])
    res = U.build()
    rows, chains = res['rows'], res['chains']
    UC.add_sox(rows, chains, UC.SOX_DRAG)
    assets = sorted({a for f in F.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, [a for a in assets if a != 'SOX_F'])
    mega['SOX_F'] = mega.get('SMH', 0.0)
    import bestpf_eval as E
    pi, _, _ = E.load_pi()
    _, sim = U.tables()

    U.log('USD の枠')
    tab_usd = U.measure(F, rows, chains, mega=mega)
    ref = json.load(open(os.path.join(BASE, 'out', 'upside_check.json')))['results']['USD・崩れあり（主）'][CUR]
    refB = json.load(open(os.path.join(BASE, 'out', 'ndx_swap_check.json')))['results']['USD・崩れあり（主）'][N.KEYS['B']]
    reg1, ok1 = {}, True
    for k in ('P15π', 'P5π（5%未満）', '最悪の世界', '最大下落'):
        for lab, mine, theirs in (('F_cur と upside_check', tab_usd[W_CRASH][CUR][k], ref[k]), ('B と ndx_swap', tab_usd[W_CRASH][KEYS['B']][k], refB[k])):
            same = UC.r1(mine) == UC.r1(theirs)
            reg1[f'{lab}・{k}'] = dict(元=theirs, この道具=mine, 一致=same)
            ok1 = ok1 and same
    k4, chips = N.chips_adj(rows, assets)
    vt_usd = N.variants(F, rows, chains, k4)
    reg2 = N.regress_variants(vt_usd, tab_usd)
    U.log('回帰の検査', ok1, reg2['max_abs_diff'])
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/smh_swap_check.py', prereg='out/smh_swap_prereg.json（dc1a98db）',
               question=P['question'], regression={'① F_cur と upside_check・B と ndx_swap（USD・崩れあり・小数1桁）': dict(ok=ok1, rows=reg1),
                                                   '② 感度の計算の主と unx_assets.measure（丸める前・1e-9）': {k: v for k, v in reg2.items() if k != 'rows'}})
    if not (ok1 and reg2['ok']):
        doc['decision'] = '回帰の検査に失敗＝止めた'
        json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
        raise SystemExit('回帰の検査に失敗')

    U.log('円の枠')
    ch_jpy, fx_url = U.jpy_chains(chains)
    tab_jpy = U.measure(F, rows, ch_jpy, mega=mega)
    vt_jpy = N.variants(F, rows, ch_jpy, k4)
    reg3 = N.regress_variants(vt_jpy, tab_jpy)
    doc['regression']['③ 円の枠でも②と同じ'] = {k: v for k, v in reg3.items() if k != 'rows'}

    U.log('100年の代用')
    cc, seats, cpct = U.castle_copy()

    def g(f):
        o = {}
        for k, v in f.items():
            kk = 'SMH' if k == 'SOX_F' else k
            o[kk] = o.get(kk, 0) + v
        return o
    cent_whole = {nm: U.century_monthly(U.whole(g(f), cc)) for nm, f in F.items()}
    cent_up_etf = {nm: UC.century_up(f) for nm, f in F.items()}
    cent_up_whole = {nm: UC.century_up(U.whole(f, cc)) for nm, f in F.items()}

    U.log('判定')
    from unx_final import conds
    frames = {'USD・崩れあり（主）': (vt_usd, W_CRASH), 'USD・ドットコム級なし': (vt_usd, W_DC), '円・崩れあり': (vt_jpy, W_CRASH)}
    judg, ins, read = {}, {}, {}
    for cj, a, b, judged in COMPS:
        judg[cj] = {fn: N.judge(vt, wn, a, b) for fn, (vt, wn) in frames.items()}
        ins[cj] = {'USD の枠': conds(tab_usd, a, b, cent_whole[a], cent_whole[b]),
                   '円の枠（感度）': conds(tab_jpy, a, b, cent_whole[a], cent_whole[b])}
        main_j = judg[cj]['USD・崩れあり（主）']
        ins_ok = ins[cj]['USD の枠']['3条件すべて（崩れあり窓・書庫:19497 と同じ窓）']
        others = {fn: judg[cj][fn]['まとめ'] for fn in ('USD・ドットコム級なし', '円・崩れあり')}
        read[cj] = dict(まとめ=main_j['まとめ'], 主の判定=main_j['主の判定'], 保険の3条件=ins_ok, 確かめの枠=others,
                        読み=N.reading(main_j['まとめ'], main_j['主の判定'], ins_ok, others) + ('' if judged else '（参考・判定に使わない）'))

    U.log('参考: 上振れ・転がる積立・本物の窓・下げ・集中')

    def enrich(tab, keep_raw=False):
        out = {}
        for wn, t in tab.items():
            o = {}
            for nm, r in t.items():
                q, pr_ = UC.upside(sim, r['_raw'], pi)
                rr = {k: v for k, v in r.items() if keep_raw or k != '_raw'}
                rr['上振れ'] = dict(pr_, 内部収益率の分位=q)
                o[nm] = rr
            out[wn] = o
        return out
    up_usd_raw, up_jpy_raw = enrich(tab_usd, True), enrich(tab_jpy, True)
    upr = {}
    for fn, up in (('USD・崩れあり（主）', up_usd_raw[W_CRASH]), ('USD・ドットコム級なし', up_usd_raw[W_DC]), ('円・崩れあり', up_jpy_raw[W_CRASH])):
        upr[fn] = {'E − 今（SHLD→SMH）': upside_read(up, KEYS['E'], CUR), '参考 B − 今（SHLD→NASDAQ100）': upside_read(up, KEYS['B'], CUR),
                   '参考 F − 今（ITA→SMH）': upside_read(up, KEYS['F'], CUR)}
    main_up = upr['USD・崩れあり（主）']['E − 今（SHLD→SMH）']['読み（R2）']
    rr = read[COMPS[0][0]]['読み']
    if main_up == 'ただの上振れ（代金なし）' and (rr.startswith('R1') or rr.startswith('R3') or rr.startswith('R4')):
        read[COMPS[0][0]]['R6'] = '替えると上振れが増え、主の窓で測った代金は無い（上振れの読み R2）。ただし決まりの読みは今のまま——どちらを取るかはユーザーの判断'
    strip = lambda d: {wn: {nm: {k: v for k, v in r.items() if k != '_raw'} for nm, r in t.items()} for wn, t in d.items()}  # noqa: E731
    up_usd, up_jpy = strip(up_usd_raw), strip(up_jpy_raw)

    roll = {nm: UC.rolling(f, rows, chains) for nm, f in F.items()}
    realw = {}
    for lab, (a, b) in N.REAL_WINDOWS.items():
        o = {nm: N.stats(N.monthly_series(f, rows, chains, a, b)[1]) for nm, f in F.items()}
        q = N.monthly_series({'QQQM': 1}, rows, chains, a, b)[1]
        o['相関（月次・QQQM と）'] = {c: N.corr(N.monthly_series({c: 1}, rows, chains, a, b)[1], q) for c in ('SMH', 'ITA', 'SHLD')}
        for c in ('QQQM', 'SMH', 'ITA', 'SHLD'):
            o[f'{c} 単体'] = N.stats(N.monthly_series({c: 1}, rows, chains, a, b)[1])
        realw[lab] = o
    epi = {}
    for lab, (a, b) in N.EPISODES.items():
        o = {}
        for nm, f in list(F.items()) + [('QQQM 単体', {'QQQM': 1}), ('SMH 単体', {'SMH': 1}), ('ITA 単体', {'ITA': 1})]:
            v = 1.0
            for x in N.monthly_series(f, rows, chains, a, b)[1]:
                v *= 1 + x
            o[nm] = round(100 * (v - 1), 1)
        epi[lab] = o
    look = {nm: N.lookthrough(f) for nm, f in F.items()}
    ords = N.orders(tuple(ORDER_RUNS), ORD)

    doc.update(
        forms=F, sox=dict(model='SMH の写し − 年0.7pt（SOX_F・upside_check と同じ）', drag=UC.SOX_DRAG),
        K4_半導体の基礎率={c: dict(Chips=(None if chips[c] is None else round(chips[c], 3)), 足す年率=round(100 * k4[c], 3)) for c in assets},
        pi=pi, judgments=judg, insurance=ins, reading=read, upside_reading=upr,
        results={'USD・崩れあり（主）': up_usd[W_CRASH], 'USD・ドットコム級なし': up_usd[W_DC], '円・崩れあり': up_jpy[W_CRASH],
                 '円・ドットコム級なし': up_jpy[W_DC],
                 '感度ごとの丸める前の値（USD・崩れあり）': {nm: {N.VARS_JA[v]: {k: (round(100 * x, 3) if isinstance(x, float) else x)
                                                                        for k, x in r.items() if k != 'worlds'} for v, r in t.items()}
                                                       for nm, t in vt_usd[W_CRASH].items()},
                 '過去の転がる積立（USD・2000-09〜2026-09）': roll,
                 '100年の代用（ETF側だけ・市場との比）': cent_up_etf, '100年の代用（全体の形・個別株＝席の業種の写し）': cent_up_whole,
                 '本物の窓': realw, '下げの局面（累計%・USD）': epi, '中身の集中（lookthrough --what-if）': look,
                 '注文書（shadow_seats --weights・入金20万円・席10）': ords},
        frames={'USD': 'night/bestpf_check.py と同じ（ドル建て）', '円': f'月次のドル建ての値に FRED DEXJPUS の月末の比を掛けた（{fx_url}）・B/C/D はドルの値のまま'},
        castle_copy=dict(seats=seats, castle_pct=cpct, copy={k: round(v, 2) for k, v in cc.items()}),
        caveats=['SHLD の 2023-09 以前は ITA のつなぎ（代理の門を通らない）＝模型では SHLD と ITA をほぼ区別できない（E と F がほぼ同じになる）',
                 '100年の代用では SMH＝Chips・SHLD＝ITA＝Aero＋Guns・楽天・プラス・SOX は SMH として数える（SOX の引く分は入れない）',
                 'K4 は事前登録どおり B・C・D に同じものを足した（etf_forward_combo では B・C だけ）',
                 '上振れの読み（R2）は upside_check と同じく表示の値で比べた（丸める前の差も残した）',
                 '注文書の12か月は今日の状態のまま（2027-01 の iDeCo・こどもNISA の開始は模していない・値段は一定）',
                 '判定・配分には使わない（材料）'],
        decision='配分は変えない（報告するだけ・事前登録 R7）', secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    U.log('→', OUT, f'{time.time() - t0:.0f}秒')
    for cj, r in read.items():
        U.log(cj, json.dumps(r, ensure_ascii=False))
        for fn, j in judg[cj].items():
            U.log('   ', fn, j['まとめ'], {v: (x['判定'], x['差']['平均'], x['差']['最悪'], x['差']['確率'], x['差']['ぶれ']) for v, x in j['感度'].items()})
    for fn, d in upr.items():
        U.log('上振れの読み', fn, json.dumps(d['E − 今（SHLD→SMH）'], ensure_ascii=False))
    for nm, r in up_usd[W_CRASH].items():
        u = r['上振れ']; q = u['内部収益率の分位']; ro = roll[nm]['20年']
        U.log(f"{nm[:24]:<24} P15π {r['P15π']:5.1f} P5 {r['P5π（5%未満）']:4.1f} 最悪 {r['最悪の世界']:5.2f} 平均 {r['π加重の平均の年率']:5.2f} "
              f"ぶれ {r['ぶれ']:4.1f} 下落 {r['最大下落']:6.1f} P20 {u['P20（道の束）']:4.1f} 90点 {q['90%点']:4.1f} | 過去20年 中央{ro['中央']:5.2f} 最小{ro['最小']:5.2f} | "
              f"NVDA {look[nm].get('NVDA（資産全体）')} 半導体 {look[nm].get('半導体の連鎖（下限〜上限）')}")


if __name__ == '__main__':
    main()
