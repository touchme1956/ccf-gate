#!/usr/bin/env python3
"""night/alloc_1016_final_check.py — 最終の配分（2026-10-16）の前後を同じ物差しで並べる（参考・判定なし）

ユーザー明示指示「NASDAQ45％ SMH25％ XLV5％ FBT5％ ITA5％ SHLD5％ 個別株10％ これが最終で」で portfolio.json の配分を変えた
（同日昼に入れた SMT モメンタム10%を外し、NASDAQ100 40→45・SMH 20→25）。
これは変更そのものの前後の検査（CLAUDE.md ルール10 の『影の計測に当たらないもの』）で、判定はしない・配分を変える提案もしない。
物差しと形は結果を見る前にこのファイルで固定し、回す前にコミットする。作りは night/alloc_1016_check.py と同じ（関数もそのまま使う）。

形（ETF 側・全体の%。個別株10は物差しの外＝alloc_1016_check と同じ）:
  前（main・2026-10-15 夜）   : QQQM 40 / SMH 25 / ITA 5 / SHLD 5 / XLV 7.5 / FBT 7.5
  SMT入り（枝・2026-10-16 昼）: QQQM 40 / SMH 20 / SMT_MOM 10 / ITA 5 / SHLD 5 / XLV 5 / FBT 5
  最終（2026-10-16）          : QQQM 45 / SMH 25 / ITA 5 / SHLD 5 / XLV 5 / FBT 5
  NASDAQ100 は QQQM で代える（iFreeNEXT の費用の差は相手に有利なまま＝既存の道具と同じ）
SMT の行: alloc_1016_check・smt_mom_check（事前登録 eb119b72）と同じ——unx_assets.build の MTUM の行と毎月の値を写し、
  費用の差 年0.62pt（SMT 0.77 − MTUM 0.15）を A1・A2・B・C・D から引く。100年の代用の部品も同じ（French の BIG HiPRIOR − 費用の差）
物差し（どれも既存の関数をそのまま使う）:
  ① unx_assets.measure（USD・崩れあり 2000-09〜／USD・ドットコム級なし 2002-11〜／円・崩れあり）: 15%以上・5%未満・元本割れ・最悪の世界・
     π加重の平均・ぶれ・最大下落・崩れ2000型・過去の転がる20年で15%以上・世界ごとの年率
  ② upside_check.upside: 20%以上・25%以上・内部収益率の分位（USD・崩れあり）
  ③ upside_check.rolling: 過去の転がる積立（USD・2000-09〜2026-09）
  ④ 100年の代用（unx_assets.century_monthly・個別株は席の業種の写し＝castle_copy）: 20年・30年の積立の市場との比
  ⑤ 感度5本（ndx_swap_check.variants）の 最終 − 前・最終 − SMT入り の差——差だけを並べ、判定の名前は付けない
回帰の検査: (a) 前と SMT入りが out/alloc_1016_check.json の『前』『新』と一致（USD・崩れあり・小数1桁）
  (b) 感度の主が measure と 1e-9 以内（ndx_swap_check.regress_variants・USD と円）(c) SMT_MOM が MTUM と費用の差だけ違う。どれかが外れれば止める
使い方: python3 night/alloc_1016_final_check.py → out/alloc_1016_final_check.json
"""
import datetime, json, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'alloc_1016_final_check.json')

OLD, SMT, FIN = '前（main・2026-10-15 夜）', 'SMT入り（枝・2026-10-16 昼）', '最終（2026-10-16）'
FORMS = {
    OLD: {'QQQM': 40, 'SMH': 25, 'ITA': 5, 'SHLD': 5, 'XLV': 7.5, 'FBT': 7.5},
    SMT: {'QQQM': 40, 'SMH': 20, 'SMT_MOM': 10, 'ITA': 5, 'SHLD': 5, 'XLV': 5, 'FBT': 5},
    FIN: {'QQQM': 45, 'SMH': 25, 'ITA': 5, 'SHLD': 5, 'XLV': 5, 'FBT': 5},
}
PREV_REF = os.path.join(BASE, 'out', 'alloc_1016_check.json')
PREV_NAMES = {OLD: '前（2026-10-15 夜）', SMT: '新（2026-10-16）'}
REG_KEYS = ('P15π', 'P5π（5%未満）', '最悪の世界', '最大下落', 'ぶれ', 'π加重の平均の年率')


def main():
    import unx_assets as U
    import upside_check as UC
    import ndx_swap_check as N
    import bestpf_eval as E
    import smt_mom_check as S
    import mw_common as M
    t0 = time.time()
    W_CRASH, W_DC = UC.W_CRASH, UC.W_DC
    for f in FORMS.values():
        assert abs(sum(f.values()) - 90) < 1e-9, f

    res = U.build()
    rows, chains = res['rows'], res['chains']
    R = U.R
    if 'MTUM' not in rows or 'MTUM' not in R.C:
        raise SystemExit('MTUM の行が無い（unx_assets.build の R7）')
    if abs(rows['MTUM']['er_vehicle'] - S.MTUM_ER) > 1e-12:
        raise SystemExit(f"MTUM の経費率が想定と違う: {rows['MTUM']['er_vehicle']}")
    # ── SMT_MOM（alloc_1016_check・smt_mom_check と同じ）──
    Dm, _, _ = E.load_D(rows, ['MTUM'])
    d_mtum = rows['MTUM'].get('D_override', Dm['MTUM'])
    smt = dict(rows['MTUM'])
    smt.update(A1=rows['MTUM']['A1'] - S.FEE_GAP, A2=rows['MTUM']['A2'] - S.FEE_GAP, B=rows['MTUM']['B'] - S.FEE_GAP, C=rows['MTUM']['C'] - S.FEE_GAP,
               D_override=d_mtum - S.FEE_GAP, er_vehicle=S.SMT_ER, ja='SMT 米国株式モメンタムファンド（MTUM の写し − 費用の差）', vehicle='SMT 米国株式モメンタム（投信）')
    rows['SMT_MOM'] = smt
    chains['SMT_MOM'] = dict(chains['MTUM'])
    R.C['SMT_MOM'] = dict(R.C['MTUM'])
    okd = (all(abs(rows['MTUM'][k] - smt[k] - S.FEE_GAP) < 1e-12 for k in ('A1', 'B', 'C')) and abs(d_mtum - smt['D_override'] - S.FEE_GAP) < 1e-12
           and abs(rows['MTUM']['A1_gross'] - smt['A1_gross']) < 1e-15 and chains['SMT_MOM'] == chains['MTUM'])

    F = {k: dict(v) for k, v in FORMS.items()}
    assets = sorted({a for f in F.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, assets)
    pi, _, _ = E.load_pi()
    _, sim = U.tables()
    U.log('USD の枠（', len(F), '形）')
    tab_usd = U.measure(F, rows, chains, mega=mega)
    ref = json.load(open(PREV_REF))['results']['USD・崩れあり（主）']
    reg_ab, ok_ab = {}, True
    for mine, theirs in PREV_NAMES.items():
        for k in REG_KEYS:
            a, b = tab_usd[W_CRASH][mine][k], ref[theirs][k]
            same = UC.r1(a) == UC.r1(b)
            reg_ab[f'{mine}・{k}'] = dict(alloc_1016_check=b, この道具=a, 一致=same)
            ok_ab = ok_ab and same
    k4, chips = N.chips_adj(rows, assets)
    vt_usd = N.variants(F, rows, chains, k4)
    reg_c = N.regress_variants(vt_usd, tab_usd)
    U.log('回帰の検査', ok_ab, reg_c['max_abs_diff'], okd)
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/alloc_1016_final_check.py', kind='参考・判定なし（ユーザー明示指示の変更の前後の検査）',
               instruction='NASDAQ45％ SMH25％ XLV5％ FBT5％ ITA5％ SHLD5％ 個別株10％ これが最終で',
               regression={'(a) 前と SMT入りが out/alloc_1016_check.json と一致（USD・崩れあり・小数1桁）': dict(ok=ok_ab, rows=reg_ab),
                           '(b) 感度の計算の主と unx_assets.measure（USD・丸める前・1e-9）': {k: v for k, v in reg_c.items() if k != 'rows'},
                           '(c) SMT_MOM が MTUM と費用の差（0.0062）だけ違う': okd})
    if not (ok_ab and reg_c['ok'] and okd):
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

    # ── 100年の代用（alloc_1016_check と同じ部品）──
    ev, big_hi6, big_hi25 = S.french_evidence(M)
    C = U.century_parts()
    C['parts']['MTUM'] = dict(big_hi6)
    C['parts']['SMT_MOM'] = {m: v - S.FEE_GAP / 12 for m, v in big_hi6.items()}
    U.MONTHLY_OK.update({'MTUM', 'SMT_MOM'})
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
    diffs = {}
    for cj, (a, b) in {'最終 − 前': (FIN, OLD), '最終 − SMT入り': (FIN, SMT)}.items():
        diffs[cj] = {}
        for fn, (vt, wn) in frames.items():
            j = N.judge(vt, wn, a, b)
            diffs[cj][fn] = {k: x['差'] for k, x in j['感度'].items()}     # 差だけ（判定の名前は付けない）
    cent_out = {nm: U.strip_century(d) for nm, d in cent.items() if d is not None}
    doc.update(
        forms=F,
        results={'USD・崩れあり（主）': table, 'USD・ドットコム級なし': {nm: show(tab_usd[W_DC][nm]) for nm in F},
                 '円・崩れあり': {nm: show(tab_jpy[W_CRASH][nm]) for nm in F},
                 '過去の転がる積立（USD・2000-09〜2026-09）': roll, '100年の代用（全体の形）': cent_out,
                 '感度5本の差（判定の名前は付けない）': diffs},
        frames={'USD': 'night/bestpf_check.py と同じ（ドル建て）', '円': f'月次のドル建ての値に FRED DEXJPUS の月末の比（{fx_url}）・B/C/D はドルのまま'},
        castle_copy=dict(seats=seats, castle_pct=cpct),
        caveats=['SMT入りの形の SMT は 2026 年より前が MTUM の写し（2013-04 より前は French の BIG HiPRIOR）＝SMT の作り方（21社・等金額・6/12/36か月）の違いは物差しの外',
                 'ETF 側だけを測る（個別株10は物差しの外）・判定はしない（変更はユーザーの明示指示）'],
        secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    U.log('→', OUT, f'{time.time() - t0:.0f}秒')
    for nm in F:
        r = table[nm]
        U.log(f"{nm:<22} P15 {r['P15π']:5.1f} P20 {r['上振れ']['P20（道の束）']:5.1f} P5 {r['P5π（5%未満）']:5.1f} 最悪 {r['最悪の世界']:5.2f} "
              f"平均 {r['π加重の平均の年率']:5.2f} ぶれ {r['ぶれ']:5.1f} 下落 {r['最大下落']:6.1f} 過去20年15%以上 {r['過去の転がる20年で15%以上']:5.1f}")
    for cj, d in diffs.items():
        for fn, x in d.items():
            dd = x['主']
            U.log(f"{cj:<14} {fn:<14} 主 Δ平均{dd['平均']:+.3f} Δ最悪{dd['最悪']:+.3f} Δ確率{dd['確率']:+.2f} Δぶれ{dd['ぶれ']:+.2f} "
                  f"Δ5%未満{dd['5%未満']:+.2f} Δ下落{dd['最大下落']:+.2f}")
    U.log('100年', json.dumps({nm: cent_out.get(nm) for nm in F}, ensure_ascii=False)[:1500])


if __name__ == '__main__':
    main()
