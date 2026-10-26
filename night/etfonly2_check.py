#!/usr/bin/env python3
"""night/etfonly2_check.py — 個別株をなくして NASDAQ100 50 / SMH 25 の形にする案と今を全体の形で並べる（2026-10-26・参考・判定なし）

ユーザーの問い「NASDAQ100 50/ SMH 25/ ITA 10/ SHLD 5 / XLV 5 / FBT 5は？」（前の問いの続き＝個別株なし）への答えの材料。配分は変えない。
作りは night/etfonly2_check.py を写し（案の形だけ替えた）。元は night/smh30ita15_check.py、案が全体の100%（個別株0）なので、今も全体の形にそろえて比べる。
形と物差しは結果を見る前にこのファイルで固定し、回す前にコミットする。

形（全体の%）:
  今のETF側（回帰の検査用）: QQQM 40 / SMH 25 / ITA 10 / SHLD 5 / XLV 5 / FBT 5（個別株10は外す＝今までの道具と同じ）
  今（個別株＝席の業種の写し）: 上＋個別株10 を unx_assets.castle_copy（QQQM 4 / SMH 4 / ITA 2）＝QQQM 44 / SMH 29 / ITA 12 / SHLD 5 / XLV 5 / FBT 5
  今（個別株＝S&P500）       : 上の ETF 側＋VOO 10
  案（個別株なし）           : QQQM 50 / SMH 25 / ITA 10 / SHLD 5 / XLV 5 / FBT 5
物差し: smh30ita15_check と同じ（measure は重みを正規化する）。100年の代用は全体の形をそのまま（今のETF側だけ castle_copy を足す）。
⚠ 個別株を ETF で代えるので、会社ごとのぶれと選ぶ上乗せは測っていない（castle10_check と同じ限界）。
回帰の検査: (a) 今のETF側が out/ret_lean_check.json の『今』と一致（USD・崩れあり・小数1桁）
  (b) 感度の主が measure と 1e-9 以内（USD と円）。どれかが外れれば止める
使い方: python3 night/etfonly2_check.py → out/etfonly2_check.json
"""
import datetime, json, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'etfonly2_check.json')

PREV, CUR_C, CUR_V, NEW = '今のETF側', '今（個別株＝席の業種の写し）', '今（個別株＝S&P500）', '案（個別株なし）'
FORMS = {
    PREV: {'QQQM': 40, 'SMH': 25, 'ITA': 10, 'SHLD': 5, 'XLV': 5, 'FBT': 5},
    CUR_C: {'QQQM': 44, 'SMH': 29, 'ITA': 12, 'SHLD': 5, 'XLV': 5, 'FBT': 5},
    CUR_V: {'QQQM': 40, 'SMH': 25, 'ITA': 10, 'SHLD': 5, 'XLV': 5, 'FBT': 5, 'VOO': 10},
    NEW: {'QQQM': 50, 'SMH': 25, 'ITA': 10, 'SHLD': 5, 'XLV': 5, 'FBT': 5},
}
LOOK = {CUR_C: ('CW=2,LRCX=2,MSFT=2,ASML=2,GOOGL=2', FORMS[PREV]), NEW: ('CW=0', FORMS[NEW])}
REFS = {PREV: (os.path.join(BASE, 'out', 'ret_lean_check.json'), '今')}
REG_KEYS = ('P15π', 'P5π（5%未満）', '最悪の世界', '最大下落', 'ぶれ', 'π加重の平均の年率')


def main():
    import unx_assets as U
    import upside_check as UC
    import ndx_swap_check as N
    import bestpf_eval as E
    t0 = time.time()
    W_CRASH, W_DC = UC.W_CRASH, UC.W_DC
    assert abs(sum(FORMS[PREV].values()) - 90) < 1e-9
    for k in (CUR_C, CUR_V, NEW):
        assert abs(sum(FORMS[k].values()) - 100) < 1e-9, k

    res = U.build()
    rows, chains = res['rows'], res['chains']
    F = {k: dict(v) for k, v in FORMS.items()}
    assets = sorted({a for f in F.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, assets)
    pi, _, _ = E.load_pi()
    _, sim = U.tables()
    U.log('USD の枠（', len(F), '形）')
    tab_usd = U.measure(F, rows, chains, mega=mega)
    reg_ab, ok_ab = {}, True
    for mine, (path, theirs) in REFS.items():
        ref = json.load(open(path))['results']['USD・崩れあり（主）'][theirs]
        for k in REG_KEYS:
            a, b = tab_usd[W_CRASH][mine][k], ref[k]
            same = UC.r1(a) == UC.r1(b)
            reg_ab[f'{mine}・{k}'] = {os.path.basename(path): b, 'この道具': a, '一致': same}
            ok_ab = ok_ab and same
    k4, chips = N.chips_adj(rows, assets)
    vt_usd = N.variants(F, rows, chains, k4)
    reg_c = N.regress_variants(vt_usd, tab_usd)
    U.log('回帰の検査', ok_ab, reg_c['max_abs_diff'])
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/etfonly2_check.py', kind='参考・判定なし（案の比べ・配分は変えない）',
               question='NASDAQ100 50/ SMH 25/ ITA 10/ SHLD 5 / XLV 5 / FBT 5は？',
               regression={'(a) 今が out/ret_lean_check.json の『今』と一致（USD・崩れあり・小数1桁）': dict(ok=ok_ab, rows=reg_ab),
                           '(b) 感度の計算の主と unx_assets.measure（USD・丸める前・1e-9）': {k: v for k, v in reg_c.items() if k != 'rows'}})
    if not (ok_ab and reg_c['ok']):
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

    cc, seats, cpct = U.castle_copy()
    assert U.whole(FORMS[PREV], cc) == FORMS[CUR_C], (cc, U.whole(FORMS[PREV], cc))
    cent = {nm: U.century_monthly(U.whole(f, cc) if nm == PREV else f) for nm, f in F.items() if nm != CUR_V}

    def show(r):
        return {k: r[k] for k in ('P15π', 'P15π（A2を外す）', 'P5π（5%未満）', 'P0π（元本割れ）', '最悪の世界', 'π加重の平均の年率', 'ぶれ', '最大下落',
                                  '崩れ2000型_16〜18年目', '過去の転がる20年で15%以上', '世界ごとの年率')}
    table = {}
    for nm in F:
        r = tab_usd[W_CRASH][nm]
        q, pr_ = UC.upside(sim, r['_raw'], pi)
        table[nm] = dict(show(r), 上振れ=dict(pr_, 内部収益率の分位=q))
    roll = {nm: UC.rolling(f, rows, chains) for nm, f in F.items()}
    frames = {'USD・崩れあり（主）': (vt_usd, W_CRASH), 'USD・ドットコム級なし': (vt_usd, W_DC), '円・崩れあり': (vt_jpy, W_CRASH)}
    diffs = {}
    for base in (CUR_C, CUR_V):
        diffs[f'案 − {base}'] = {}
        for fn, (vt, wn) in frames.items():
            j = N.judge(vt, wn, NEW, base)
            diffs[f'案 − {base}'][fn] = {k: x['差'] for k, x in j['感度'].items()}     # 差だけ（判定の名前は付けない）
    look = {}
    for nm, (castle, f) in LOOK.items():
        N.CASTLE_ARG = castle
        try:
            look[nm] = N.lookthrough(f)
            look[nm]['城'] = castle + ('（席5社×2%）' if castle != 'CW=0' else '（個別株なし）')
        except Exception as e:                       # 参考だけ・読めなければ名指し
            look[nm] = dict(読めず=str(e)[:200])
    cent_out = {nm: U.strip_century(d) for nm, d in cent.items() if d is not None}
    doc.update(
        forms=F,
        results={'USD・崩れあり（主）': table, 'USD・ドットコム級なし': {nm: show(tab_usd[W_DC][nm]) for nm in F},
                 '円・崩れあり': {nm: show(tab_jpy[W_CRASH][nm]) for nm in F},
                 '過去の転がる積立（USD・2000-09〜2026-09）': roll, '100年の代用（全体の形）': cent_out,
                 '感度5本の差（判定の名前は付けない）': diffs, '中身の集中（lookthrough・参考）': look},
        frames={'USD': 'night/bestpf_check.py と同じ（ドル建て）', '円': f'月次のドル建ての値に FRED DEXJPUS の月末の比（{fx_url}）・B/C/D はドルのまま'},
        castle_copy=dict(seats=seats, castle_pct=cpct),
        caveats=['全体の形で比べる（今の個別株10は席の業種の写しか S&P500 で代える＝会社ごとのぶれと選ぶ上乗せは測っていない）・判定はしない',
                 '今のETF側は回帰の検査のための行（個別株を外して正規化した形）',
                 'SHLD の 2023-09 以前は ITA のつなぎ（代理の門を通らない）',
                 '中身の集中は ETF の中身の写真（out/etf_profiles.json）の時点のまま'],
        secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    U.log('→', OUT, f'{time.time() - t0:.0f}秒')
    for nm in F:
        r = table[nm]
        U.log(f"{nm:<14} P15 {r['P15π']:5.1f} P20 {r['上振れ']['P20（道の束）']:5.1f} P5 {r['P5π（5%未満）']:5.1f} 最悪 {r['最悪の世界']:5.2f} "
              f"平均 {r['π加重の平均の年率']:5.2f} ぶれ {r['ぶれ']:5.1f} 下落 {r['最大下落']:6.1f} 過去20年15%以上 {r['過去の転がる20年で15%以上']:5.1f} 世界 {r['世界ごとの年率']}")
    for dn, d in diffs.items():
        for fn, x in d.items():
            U.log(dn, fn, json.dumps({k: (v['平均'], v['確率'], v['最大下落'], v['5%未満']) for k, v in x.items()}, ensure_ascii=False))
    U.log('100年', json.dumps(cent_out, ensure_ascii=False)[:1500])
    U.log('集中', json.dumps({nm: (v.get('NVDA（資産全体）'), v.get('半導体の連鎖（下限〜上限）')) for nm, v in look.items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
