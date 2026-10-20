#!/usr/bin/env python3
"""night/better_mix_check.py — 今の配分より良い案はあるか（2026-10-20・ユーザー「もっといい提案がないか教えて」・参考）

ユーザーが頼んだ比べ（ルール10: 頼まれたときだけ）。配分（portfolio.json）・門・採点・注文書には触れない。
候補・物差し・勧めの決まりは結果を見る前にこのファイルで固定し、回す前にコミットする（作りは night/xlk10_check.py・etf_add_check.py の部品のまま）。

今（2026-10-19〜・ETF 側・全体の%。個別株10は物差しの外）: QQQM 40 / SMH 25 / ITA 10 / SHLD 5 / XLV 5 / FBT 5
候補（9つ・これまでの測定で筋のあった手だけ）:
  A  防衛を ITA にまとめる（SHLD 5 → ITA）          : QQQM 40 / SMH 25 / ITA 15 / XLV 5 / FBT 5
  B  ヘルスケアを XLV にまとめる（FBT 5 → XLV）      : QQQM 40 / SMH 25 / ITA 10 / SHLD 5 / XLV 10
  C  金鉱株 GDX 5（NASDAQ100 から）                  : QQQM 35 / SMH 25 / ITA 10 / SHLD 5 / XLV 5 / FBT 5 / GDX 5
  D  公益 XLU 5（NASDAQ100 から）                    : QQQM 35 / SMH 25 / ITA 10 / SHLD 5 / XLV 5 / FBT 5 / XLU 5
  E  半導体 +5（NASDAQ100 から）                     : QQQM 35 / SMH 30 / ITA 10 / SHLD 5 / XLV 5 / FBT 5
  F1 A+B（4本にまとめる）                            : QQQM 40 / SMH 25 / ITA 15 / XLV 10
  F2 A+B+C                                           : QQQM 35 / SMH 25 / ITA 15 / XLV 10 / GDX 5
  F3 A+B+E                                           : QQQM 35 / SMH 30 / ITA 15 / XLV 10
  F4 A+B+C+E                                         : QQQM 30 / SMH 30 / ITA 15 / XLV 10 / GDX 5
物差し: unx_assets.measure（5つの世界・π）＋ ndx_swap_check.variants・judge（感度5本・etf_ita_xlk の verdict/summarize）を
  3つの枠（USD・崩れあり〔主〕／USD・ドットコム級なし／円・崩れあり）で、Δ＝候補 − 今。保険の3条件は unx_final.conds（候補を今と比べる）。
勧めの決まり（固定）:
  R1: 主の枠のまとめが『堅い価値あり』の候補＝測りの上で今より良い。複数なら主の Δ平均 の大きい順（確かめの2枠で割れたら名指し）
  R2: R1 が無ければ、主の枠で『前提しだい』かつ保険の3条件をすべて満たす候補＝保険として筋が通る（好みの差）
  R3: まとめる手（A・B・F1）は測りではなく記録の確かさ（SHLD は記録3年・代わりの門を通らない／FBT の費用 0.54% 対 XLV 0.08%）の手——
      主の判定が『価値なし』でなければ『まとめても測りは悪くならない』、『価値なし』なら『測りでは少し悪い＝まとめる理由は記録の確かさだけ』
  R4: どの結果でも配分は変えない（報告するだけ・入れるかはユーザーの明示指示）
参考（勧めに使わない）: 上振れ（P20）・過去の転がる20年の積立・100年の代用（GDX は French の Gold・XLU は Util・SHLD は ITA と同じ写し・
  FBT は Drugs）・中身の集中（lookthrough・GDX の中身は未取得＝NVDA は持たない）・楽天の経費率。
回帰の検査: (a) 今が out/ita10_check.json の『案（VBR → ITA）』と一致（USD・崩れあり・小数1桁）
  (b) 感度の主が measure と 1e-9 以内（USD と円）。どれかが外れれば止める
使い方: python3 night/better_mix_check.py → out/better_mix_check.json
"""
import datetime, json, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'better_mix_check.json')

NOW = '今'
FORMS = {
    NOW: {'QQQM': 40, 'SMH': 25, 'ITA': 10, 'SHLD': 5, 'XLV': 5, 'FBT': 5},
    'A 防衛を ITA に': {'QQQM': 40, 'SMH': 25, 'ITA': 15, 'XLV': 5, 'FBT': 5},
    'B ヘルスケアを XLV に': {'QQQM': 40, 'SMH': 25, 'ITA': 10, 'SHLD': 5, 'XLV': 10},
    'C GDX 5': {'QQQM': 35, 'SMH': 25, 'ITA': 10, 'SHLD': 5, 'XLV': 5, 'FBT': 5, 'GDX': 5},
    'D XLU 5': {'QQQM': 35, 'SMH': 25, 'ITA': 10, 'SHLD': 5, 'XLV': 5, 'FBT': 5, 'XLU': 5},
    'E 半導体 +5': {'QQQM': 35, 'SMH': 30, 'ITA': 10, 'SHLD': 5, 'XLV': 5, 'FBT': 5},
    'F1 A+B（4本）': {'QQQM': 40, 'SMH': 25, 'ITA': 15, 'XLV': 10},
    'F2 A+B+C': {'QQQM': 35, 'SMH': 25, 'ITA': 15, 'XLV': 10, 'GDX': 5},
    'F3 A+B+E': {'QQQM': 35, 'SMH': 30, 'ITA': 15, 'XLV': 10},
    'F4 A+B+C+E': {'QQQM': 30, 'SMH': 30, 'ITA': 15, 'XLV': 10, 'GDX': 5},
}
CONSOLIDATE = ('A 防衛を ITA に', 'B ヘルスケアを XLV に', 'F1 A+B（4本）')
PREV_REF = os.path.join(BASE, 'out', 'ita10_check.json')
PREV_NAME = '案（VBR → ITA）'
REG_KEYS = ('P15π', 'P5π（5%未満）', '最悪の世界', '最大下落', 'ぶれ', 'π加重の平均の年率')
FRAMES = ('USD・崩れあり（主）', 'USD・ドットコム級なし', '円・崩れあり')
NET_EXTRA = {'GDX': 'GDX', 'XLU': 'XLU'}


def main():
    import unx_assets as U
    import upside_check as UC
    import ndx_swap_check as N
    import bestpf_eval as E
    from unx_final import conds
    t0 = time.time()
    W_CRASH, W_DC = UC.W_CRASH, UC.W_DC
    for f in FORMS.values():
        assert abs(sum(f.values()) - 90) < 1e-9, f

    res = U.build()
    rows, chains = res['rows'], res['chains']
    F = {k: dict(v) for k, v in FORMS.items()}
    assets = sorted({a for f in F.values() for a in f} | {'VOO'})
    miss = [a for a in assets if a not in rows]
    if miss:
        raise SystemExit(f'行が無い: {miss}')
    late = {a: min(chains[a]) for a in assets if min(chains[a]) > UC.FIRST}
    if late:
        raise SystemExit(f'系列が主の窓（2000-09〜）にそろわない: {late}')
    mega = U.mega_map(rows, assets)
    pi, _, _ = E.load_pi()
    _, sim = U.tables()
    U.log('USD の枠（', len(F), '形）')
    tab_usd = U.measure(F, rows, chains, mega=mega)
    ref = json.load(open(PREV_REF))['results']['USD・崩れあり（主）'][PREV_NAME]
    reg_a, ok_a = {}, True
    for k in REG_KEYS:
        a, b = tab_usd[W_CRASH][NOW][k], ref[k]
        same = UC.r1(a) == UC.r1(b)
        reg_a[k] = dict(ita10_check=b, この道具=a, 一致=same)
        ok_a = ok_a and same
    k4, chips = N.chips_adj(rows, assets)
    vt_usd = N.variants(F, rows, chains, k4)
    reg_b = N.regress_variants(vt_usd, tab_usd)
    U.log('回帰の検査', ok_a, reg_b['max_abs_diff'])
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/better_mix_check.py', kind='参考（ユーザーが頼んだ比べ・勧めの決まりは道具の頭に固定）',
               question='もっといい提案がないか教えて',
               regression={'(a) 今が out/ita10_check.json の『案（VBR → ITA）』と一致（USD・崩れあり・小数1桁）': dict(ok=ok_a, rows=reg_a),
                           '(b) 感度の計算の主と unx_assets.measure（USD・丸める前・1e-9）': {k: v for k, v in reg_b.items() if k != 'rows'}})
    if not (ok_a and reg_b['ok']):
        doc['decision'] = '回帰の検査に失敗＝止めた'
        json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
        raise SystemExit('回帰の検査に失敗')
    U.log('円の枠')
    ch_jpy, fx_url = U.jpy_chains(chains)
    tab_jpy = U.measure(F, rows, ch_jpy, mega=mega)
    vt_jpy = N.variants(F, rows, ch_jpy, k4)
    reg_j = N.regress_variants(vt_jpy, tab_jpy)
    doc['regression']['(b) 円の枠でも同じ'] = {k: v for k, v in reg_j.items() if k != 'rows'}
    if not reg_j['ok']:
        doc['decision'] = '回帰の検査に失敗（円）＝止めた'
        json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
        raise SystemExit('回帰の検査に失敗（円）')

    U.log('100年の代用')
    cc, seats, cpct = U.castle_copy()
    cent = {nm: U.century_monthly(U.whole(f, cc)) for nm, f in F.items()}

    U.log('判定')
    frames = {FRAMES[0]: (vt_usd, W_CRASH), FRAMES[1]: (vt_usd, W_DC), FRAMES[2]: (vt_jpy, W_CRASH)}
    cands = [k for k in F if k != NOW]
    judg, ins = {}, {}
    for x in cands:
        judg[x] = {fn: N.judge(vt, wn, x, NOW) for fn, (vt, wn) in frames.items()}
        cu = conds(tab_usd, x, NOW, cent[x], cent[NOW])
        c12 = bool(cu[W_CRASH]['(1) P15π の低下 ≤ 1.5pt'] and cu[W_CRASH]['(2) 最悪の世界・P5π・最大下落がすべて良い'])
        c3 = cu['(3) 100年の代用（全体の形）の20年・30年の中央が下がらず下位10%が上がる']
        ins[x] = dict(USD=cu, 状態=('すべて満たす' if (c12 and c3) else ('(1)(2) を満たす・(3) は測れない' if (c12 and c3 is None) else '満たさない')))

    def md(x):
        return judg[x][FRAMES[0]]['感度']['主']['差']
    r1 = sorted([x for x in cands if judg[x][FRAMES[0]]['まとめ'] == '堅い価値あり'], key=lambda x: -md(x)['平均'])
    read = {}
    if r1:
        split = {x: {fn: judg[x][fn]['まとめ'] for fn in FRAMES[1:] if judg[x][fn]['まとめ'] != '堅い価値あり'} for x in r1}
        read['R1'] = dict(候補=[dict(案=x, 主の差=md(x), 確かめの枠=(split[x] or 'どちらも堅い価値あり')) for x in r1],
                          読み=f'R1: 測りの上で今より良い——{"・".join(r1)}（主の Δ平均の順）')
    else:
        read['R1'] = '主の枠で『堅い価値あり』の候補は無い'
    if not r1:
        r2 = [x for x in cands if judg[x][FRAMES[0]]['まとめ'] == '前提しだい' and ins[x]['状態'] == 'すべて満たす']
        read['R2'] = (dict(候補=r2, 読み='R2: 保険として筋が通る（好みの差）——' + '・'.join(r2)) if r2 else 'R2: 保険の3条件をすべて満たす候補も無い')
    r3 = {}
    for x in CONSOLIDATE:
        mv = judg[x][FRAMES[0]]['主の判定']
        r3[x] = dict(主の判定=mv, まとめ=judg[x][FRAMES[0]]['まとめ'],
                     読み=('まとめても測りは悪くならない（理由は記録の確かさと費用）' if mv != '価値なし' else '測りでは少し悪い＝まとめる理由は記録の確かさだけ'))
    read['R3'] = r3
    read['R4'] = 'どの結果でも配分は変えない（報告するだけ・入れるかはユーザーの明示指示）'

    U.log('参考: 上振れ・転がる積立・集中・経費率')

    def show(r):
        return {k: r[k] for k in ('P15π', 'P15π（A2を外す）', 'P5π（5%未満）', 'P0π（元本割れ）', '最悪の世界', 'π加重の平均の年率', 'ぶれ', '最大下落',
                                  '崩れ2000型_16〜18年目', '過去の転がる20年で15%以上', '世界ごとの年率')}
    table = {}
    for nm in F:
        r = tab_usd[W_CRASH][nm]
        q, pr_ = UC.upside(sim, r['_raw'], pi)
        table[nm] = dict(show(r), 上振れ=dict(pr_, 内部収益率の分位=q))
    roll = {nm: UC.rolling(f, rows, chains) for nm, f in F.items()}
    N.NET_ARG.update(NET_EXTRA)
    look = {}
    for nm, f in F.items():
        try:
            look[nm] = N.lookthrough(f)
        except Exception as e:                       # 参考だけ・読めなければ名指し
            look[nm] = dict(読めず=str(e)[:200])
    bl = json.load(open(os.path.join(BASE, 'out', 'broker_lineup.json')))['etfs']
    er = {a: (bl.get(a) or {}).get('er') for a in assets if a != 'VOO'}
    cent_out = {nm: U.strip_century(d) for nm, d in cent.items() if d is not None}
    doc.update(
        forms=F,
        judgments={x: {fn: dict(まとめ=j['まとめ'], 主の判定=j['主の判定'], 感度=j['感度']) for fn, j in judg[x].items()} for x in cands},
        insurance=ins, reading=read,
        results={'USD・崩れあり（主）': table, 'USD・ドットコム級なし': {nm: show(tab_usd[W_DC][nm]) for nm in F},
                 '円・崩れあり': {nm: show(tab_jpy[W_CRASH][nm]) for nm in F},
                 '過去の転がる積立（USD・2000-09〜2026-09）': roll, '100年の代用（全体の形）': cent_out,
                 '中身の集中（lookthrough・参考）': look, '楽天の経費率（out/broker_lineup.json）': er},
        K4_半導体の基礎率={c: dict(Chips=(None if chips[c] is None else round(chips[c], 3)), 足す年率=round(100 * k4[c], 3)) for c in assets},
        frames={'USD': 'night/bestpf_check.py と同じ（ドル建て）', '円': f'月次のドル建ての値に FRED DEXJPUS の月末の比（{fx_url}）・B/C/D はドルのまま'},
        castle_copy=dict(seats=seats, castle_pct=cpct),
        caveats=['ETF 側だけを測る（個別株10は物差しの外）',
                 'SHLD の 2023-09 以前は ITA のつなぎ（代理の門を通らない）＝A は測りの上では ITA と SHLD の差がほぼ出ない',
                 '分散の効く本（GDX・XLU）の価値は分散の上乗せの仮定に頼る（感度『分散の上乗せなし』が外す）',
                 '100年の代用で FBT は Drugs・SHLD は ITA と同じ写し',
                 '勧めの決まりは道具の頭に固定。配分は変えない（R4）'],
        decision='配分は変えない（報告するだけ・R4）', secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    U.log('→', OUT, f'{time.time() - t0:.0f}秒')
    for nm in F:
        r = table[nm]
        U.log(f"{nm:<20} P15 {r['P15π']:5.1f} P20 {r['上振れ']['P20（道の束）']:5.1f} P5 {r['P5π（5%未満）']:5.1f} 最悪 {r['最悪の世界']:5.2f} "
              f"平均 {r['π加重の平均の年率']:5.2f} ぶれ {r['ぶれ']:5.1f} 下落 {r['最大下落']:6.1f} 過去20年15%以上 {r['過去の転がる20年で15%以上']:5.1f}")
    for x in cands:
        d = md(x)
        U.log(f"{x:<20} {judg[x][FRAMES[0]]['まとめ']:<12} 主 {judg[x][FRAMES[0]]['主の判定']:<5} Δ平均{d['平均']:+.3f} Δ最悪{d['最悪']:+.3f} "
              f"Δ確率{d['確率']:+.2f} Δぶれ{d['ぶれ']:+.2f} Δ5%未満{d['5%未満']:+.2f} Δ下落{d['最大下落']:+.2f} | 感度 "
              f"{[v['判定'] for v in judg[x][FRAMES[0]]['感度'].values()]} | DC {judg[x][FRAMES[1]]['まとめ']} 円 {judg[x][FRAMES[2]]['まとめ']} | 保険 {ins[x]['状態']}")
    U.log('100年', json.dumps({nm: (cent_out.get(nm) or {}).get('30年の積立（起点1965〜1995）') for nm in F}, ensure_ascii=False)[:2500])
    U.log('集中', json.dumps({nm: (v.get('NVDA（資産全体）'), v.get('半導体の連鎖（下限〜上限）')) for nm, v in look.items()}, ensure_ascii=False))
    U.log('読み', json.dumps(read, ensure_ascii=False)[:3000])


if __name__ == '__main__':
    main()
