#!/usr/bin/env python3
"""night/alloc_1022_check.py — 配分の変更（ITA の5を SMH へ）の前後を並べる（2026-10-22・参考・判定なし）

ユーザー明示指示「NASDAQ40SMH30ITA5％SHLD5％ XLK5％FBT5％個別株10％」（「XLK」は XLV の打ち間違いと本人に確かめた）で配分を変える。
これはその変更そのものの前後の検査（ルール10の「変更の検査」）で、判定の名前は付けない。作りは night/ita10_check.py をそのまま写し、
形だけ替えた（VBR を持たないので100年の代用の写しは unx_assets の部品だけ）・中身の集中（lookthrough）を足した。
形と物差しは結果を見る前にこのファイルで固定し、回す前にコミットする。

形（ETF 側・全体の%。個別株10は物差しの外）:
  前（2026-10-19〜）  : QQQM 40 / SMH 25 / ITA 10 / SHLD 5 / XLV 5 / FBT 5
  新（2026-10-22〜）  : QQQM 40 / SMH 30 / ITA 5 / SHLD 5 / XLV 5 / FBT 5
物差し: ita10_check と同じ（unx_assets.measure・3つの枠・上振れ〔道の束〕・過去の転がる積立・100年の代用〔個別株10は席の業種の写し〕・
  感度5本の差〔ndx_swap_check.judge の差だけ〕）＋ 中身の集中（ndx_swap_check.lookthrough・城は席5社×2%）。
回帰の検査: (a) 前が out/ret_lean_check.json の『今』と一致（USD・崩れあり・小数1桁）
  (a2) 新が out/smh30_check.json の『案（VBR → SMH）』（2026-10-19 に同じ形を測った）と一致（同）
  (b) 感度の主が measure と 1e-9 以内（USD と円）。どれかが外れれば止める
使い方: python3 night/alloc_1022_check.py → out/alloc_1022_check.json
"""
import datetime, json, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'alloc_1022_check.json')

PREV, NEW = '前（2026-10-19〜）', '新（2026-10-22〜）'
FORMS = {
    PREV: {'QQQM': 40, 'SMH': 25, 'ITA': 10, 'SHLD': 5, 'XLV': 5, 'FBT': 5},
    NEW: {'QQQM': 40, 'SMH': 30, 'ITA': 5, 'SHLD': 5, 'XLV': 5, 'FBT': 5},
}
REFS = {PREV: (os.path.join(BASE, 'out', 'ret_lean_check.json'), '今'),
        NEW: (os.path.join(BASE, 'out', 'smh30_check.json'), '案（VBR → SMH）')}
REG_KEYS = ('P15π', 'P5π（5%未満）', '最悪の世界', '最大下落', 'ぶれ', 'π加重の平均の年率')


def main():
    import unx_assets as U
    import upside_check as UC
    import ndx_swap_check as N
    import bestpf_eval as E
    t0 = time.time()
    W_CRASH, W_DC = UC.W_CRASH, UC.W_DC
    for f in FORMS.values():
        assert abs(sum(f.values()) - 90) < 1e-9, f

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
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/alloc_1022_check.py', kind='参考・判定なし（ユーザーが明示指示した変更の前後の検査）',
               question='NASDAQ40SMH30ITA5％SHLD5％ XLK5％FBT5％個別株10％（XLK は XLV の打ち間違いと確認）',
               regression={'(a) 前が out/ret_lean_check.json の『今』と・(a2) 新が out/smh30_check.json の『案（VBR → SMH）』と一致（USD・崩れあり・小数1桁）': dict(ok=ok_ab, rows=reg_ab),
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
    cent = {nm: U.century_monthly(U.whole(f, cc)) for nm, f in F.items()}

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
    diffs = {'新 − 前': {}}
    for fn, (vt, wn) in frames.items():
        j = N.judge(vt, wn, NEW, PREV)
        diffs['新 − 前'][fn] = {k: x['差'] for k, x in j['感度'].items()}     # 差だけ（判定の名前は付けない）
    N.CASTLE_ARG = ','.join(f'{s}={cpct / len(seats):g}' for s in seats)
    look = {}
    for nm, f in F.items():
        try:
            look[nm] = N.lookthrough(f)
            if '城' in look[nm]:
                look[nm]['城'] = f'{N.CASTLE_ARG}（席{len(seats)}社×{cpct / len(seats):g}%）'
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
        caveats=['ETF 側だけを測る（個別株10は物差しの外・100年の代用だけ席の業種の写しで全体の形）・判定はしない',
                 'SHLD の 2023-09 以前は ITA のつなぎ（代理の門を通らない）',
                 '中身の集中は ETF の中身の写真（out/etf_profiles.json）の時点のまま'],
        secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    U.log('→', OUT, f'{time.time() - t0:.0f}秒')
    for nm in F:
        r = table[nm]
        U.log(f"{nm:<14} P15 {r['P15π']:5.1f} P20 {r['上振れ']['P20（道の束）']:5.1f} P5 {r['P5π（5%未満）']:5.1f} 最悪 {r['最悪の世界']:5.2f} "
              f"平均 {r['π加重の平均の年率']:5.2f} ぶれ {r['ぶれ']:5.1f} 下落 {r['最大下落']:6.1f} 過去20年15%以上 {r['過去の転がる20年で15%以上']:5.1f} 世界 {r['世界ごとの年率']}")
    for fn, x in diffs['新 − 前'].items():
        U.log(fn, json.dumps({k: (v['平均'], v['確率'], v['最大下落'], v['5%未満']) for k, v in x.items()}, ensure_ascii=False))
    U.log('100年', json.dumps({nm: cent_out.get(nm) for nm in F}, ensure_ascii=False)[:1500])
    U.log('集中', json.dumps({nm: (v.get('NVDA（資産全体）'), v.get('半導体の連鎖（下限〜上限）')) for nm, v in look.items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
