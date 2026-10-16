#!/usr/bin/env python3
"""night/unx_final.py — 未調査の候補の検定 A: 今の配分（F_now）を標準の物差しに通す（2026-10-14）

読むだけ。門・採点・配分（portfolio.json）・注文書には触れない。事前登録 out/unexplored_prereg.json（6f534c92）の groups.A_final_allocation どおり。
  F_now  … ETF側 NDX40 / SMH25 / ITA5 / SHLD5 / XLV5 / FBT5（2026-10-13〜・個別株15は外）
  F_main … NDX50 / SMH25 / ITA10（2026-10-12 の最終）
  F_xlv  … NDX40 / SMH25 / ITA10 / XLV10（2026-10-13 の XLV 案）
  （NDX＝QQQM の行＝iFreeNEXT と同じ指数）
物差し: night/bestpf_check.py の1本ずつの塊（unx_assets.measure）・USD の枠が主・円の枠は感度。100年の代用は alloc_check.century と同じ
（書庫:19497 の (3) と同じ『全体の形』＝個別株15を今の席の業種の写しで足す。ETF 側だけの値も並べる）。
回帰の検査: USD の枠で F_main・F_xlv が書庫:19497 の表（P15π 28.4 / 27.4・5%未満 21.4 / 19.7・最悪 7.59 / 7.78・最大下落 −74.8 / −69.9）と
小数1桁で一致すること。一致しなければここで止めて理由を書く。
判定: 2026-10-13 の3条件（(1) P15π の低下 ≤ 1.5pt (2) 最悪の世界・P5π・最大下落の3つすべてが良い (3) 100年の代用の20年・30年の
中央が下がらず下位10%が上がる）で F_now を F_main と比べ、F_now − F_xlv を etf_ita_xlk.verdict（平均＝π加重の平均）で分類する。
どちらの結果でも配分は変えない。

使い方: python3 night/unx_final.py  → out/unx_final.json
"""
import datetime, json, math, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import unx_assets as U   # noqa: E402

OUT = os.path.join(BASE, 'out', 'unx_final.json')
W_CRASH, W_DC = '崩れあり 2000-09〜', 'ドットコム級なし 2002-11〜'
TARGET = {'F_main': {'P15π': 28.4, 'P5π（5%未満）': 21.4, '最悪の世界': 7.59, '最大下落': -74.8},
          'F_xlv': {'P15π': 27.4, 'P5π（5%未満）': 19.7, '最悪の世界': 7.78, '最大下落': -69.9}}
TARGET_CENT = {'F_main': {'30年の積立（起点1965〜1995）': {'中央値': 1.087, '下位10%点': 0.906, '市場に勝った割合': 0.71},
                           '20年の積立（起点1965〜2005）': {'中央値': 1.086, '下位10%点': 0.792, '最悪': 0.656, '市場に勝った割合': 0.66}},
               'F_xlv': {'30年の積立（起点1965〜1995）': {'中央値': 1.171, '下位10%点': 0.998, '市場に勝った割合': 0.87},
                         '20年の積立（起点1965〜2005）': {'中央値': 1.130, '下位10%点': 0.818, '最悪': 0.719, '市場に勝った割合': 0.71}}}
FORMS = {
    'F_main': {'QQQM': 50, 'SMH': 25, 'ITA': 10},
    'F_xlv': {'QQQM': 40, 'SMH': 25, 'ITA': 10, 'XLV': 10},
    'F_now': {'QQQM': 40, 'SMH': 25, 'ITA': 5, 'SHLD': 5, 'XLV': 5, 'FBT': 5},
}
REF_FORMS = {   # 事前登録の外（SHLD の代理が門を通らないための代わり・感度）
    'F_now_ITA10（SHLD5→ITA5）': {'QQQM': 40, 'SMH': 25, 'ITA': 10, 'XLV': 5, 'FBT': 5},
    'F_now_SHLD_EU（感度・後知恵・門を通らない）': {'QQQM': 40, 'SMH': 25, 'ITA': 5, 'SHLD_EU': 5, 'XLV': 5, 'FBT': 5},
}


def r1(x):
    return round(x + 1e-12, 1) if x >= 0 else -round(-x + 1e-12, 1)


def regression(tab):
    out, ok = {}, True
    for nm, tgt in TARGET.items():
        row = tab[W_CRASH][nm]
        d = {}
        for k, v in tgt.items():
            mine = row[k]
            same = r1(mine) == r1(v)
            d[k] = dict(書庫=v, この道具=mine, 小数1桁で一致=same)
            ok = ok and same
        out[nm] = d
    return out, ok


def conds(tab, a, b, cent_a, cent_b):
    """2026-10-13 の3条件（a を b と比べる）。窓ごと"""
    res = {}
    for wn in (W_CRASH, W_DC):
        ra, rb = tab[wn][a]['_raw'], tab[wn][b]['_raw']
        c1 = ra['P15'] >= rb['P15'] - 0.015
        c1n = ra['P15_noA2'] >= rb['P15_noA2'] - 0.015
        c2 = ra['worst'] > rb['worst'] and ra['P5'] < rb['P5'] and ra['mdd'] > rb['mdd']
        res[wn] = {'(1) P15π の低下 ≤ 1.5pt': bool(c1), '  差(pt)': round(100 * (ra['P15'] - rb['P15']), 2),
                   '(1) A2 を外しても': bool(c1n), '  差(pt)・A2を外す': round(100 * (ra['P15_noA2'] - rb['P15_noA2']), 2),
                   '(2) 最悪の世界・P5π・最大下落がすべて良い': bool(c2),
                   '  最悪の世界の差(pt)': round(100 * (ra['worst'] - rb['worst']), 2), '  P5π の差(pt)': round(100 * (ra['P5'] - rb['P5']), 2),
                   '  最大下落の差(pt)': round(100 * (ra['mdd'] - rb['mdd']), 2)}
    c3 = U.cond3(cent_a, cent_b)
    res['(3) 100年の代用（全体の形）の20年・30年の中央が下がらず下位10%が上がる'] = c3
    res['3条件すべて（崩れあり窓・書庫:19497 と同じ窓）'] = bool(res[W_CRASH]['(1) P15π の低下 ≤ 1.5pt'] and res[W_CRASH]['(2) 最悪の世界・P5π・最大下落がすべて良い'] and c3)
    return res


def verdict_vs(tab, a, b):
    from etf_ita_xlk import verdict
    out = {}
    for wn in (W_CRASH, W_DC):
        ra, rb = tab[wn][a]['_raw'], tab[wn][b]['_raw']
        d = {'平均': round(100 * (ra['mean_pi'] - rb['mean_pi']), 3), '最悪': round(100 * (ra['worst'] - rb['worst']), 3),
             '確率': round(100 * (ra['P15'] - rb['P15']), 3), 'ぶれ': round(100 * (ra['vol'] - rb['vol']), 3)}
        out[wn] = dict(差=d, 判定=verdict(d))
    return out


def main():
    t0 = time.time()
    res = U.build()
    rows, chains, info = res['rows'], res['chains'], res['info']
    allf = dict(FORMS, **REF_FORMS)
    assets = sorted({a for f in allf.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, assets)

    # ── USD の枠（主）──
    U.log('USD の枠')
    tab_usd = U.measure(allf, rows, chains, mega=mega)
    reg, reg_ok = regression(tab_usd)
    U.log('回帰の検査', json.dumps(reg, ensure_ascii=False), '→', reg_ok)
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/unx_final.py', prereg=U.PREREG,
               question='今の配分（F_now）を標準の物差し（5つの世界・P15π・100年の代用）に通す', regression=dict(ok=reg_ok, rows=reg,
               note='USD の枠・崩れあり窓。書庫:19497 の表（night/bestpf_check.py の値）と小数1桁で比べた'))
    if not reg_ok:
        doc['decision'] = '回帰の検査に失敗＝測定を止めた（事前登録 regression_check）'
        doc['results'] = {'USD': U.strip_raw(tab_usd)}
        json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
        raise SystemExit('回帰の検査に失敗: ' + json.dumps(reg, ensure_ascii=False))

    # ── 円の枠（感度）──
    U.log('円の枠')
    ch_jpy, fx_url = U.jpy_chains(chains)
    tab_jpy = U.measure(allf, rows, ch_jpy, mega=mega)

    # ── 100年の代用 ──
    U.log('100年の代用')
    cc, seats, cpct = U.castle_copy()
    cent_whole = {nm: U.century_monthly(U.whole(f, cc)) for nm, f in allf.items()}
    cent_etf = {nm: U.century_monthly(f) for nm, f in allf.items()}
    reg_c = {}
    for nm, tgt in TARGET_CENT.items():
        d = cent_whole[nm]
        reg_c[nm] = {lab: {k: dict(書庫=v, この道具=d[lab][k], 一致=abs(d[lab][k] - v) < 0.0015) for k, v in kv.items()} for lab, kv in tgt.items()}
    doc['regression']['参考_100年の代用（書庫:19497 の表・全体の形）'] = reg_c

    # ── 判定 ──
    shld_failed = 'SHLD' in info['gate_failed_kept']
    dec = {}
    for nm in ['F_now'] + list(REF_FORMS):
        if nm == 'F_now_SHLD_EU（感度・後知恵・門を通らない）':
            continue
        dec[nm] = {'USD の枠（主）': {'F_main と比べた3条件': conds(tab_usd, nm, 'F_main', cent_whole[nm], cent_whole['F_main']),
                                     'F_xlv との差（etf_ita_xlk.verdict）': verdict_vs(tab_usd, nm, 'F_xlv')},
                   '円の枠（感度）': {'F_main と比べた3条件': conds(tab_jpy, nm, 'F_main', cent_whole[nm], cent_whole['F_main']),
                                    'F_xlv との差（etf_ita_xlk.verdict）': verdict_vs(tab_jpy, nm, 'F_xlv')}}
    main_rule = dec['F_now']['USD の枠（主）']
    if shld_failed:
        decision = {'事前登録どおりの判定': '測れない——SHLD の代理（ITA）が代理の門を通らない（2023-10〜2026-09 の36か月の相関 '
                                       f"{info['gates']['SHLD']['corr']} < 0.90）。common.proxy_gate は『満たせない本は名指しして外す』＝SHLD を含む F_now は事前登録どおりには作れない",
                    '参考の判定（事前登録の外・SHLD を門を通らない ITA つなぎのまま置いた F_now）': {
                        '3条件（F_main と・USD・崩れあり窓）': main_rule['F_main と比べた3条件']['3条件すべて（崩れあり窓・書庫:19497 と同じ窓）'],
                        'F_xlv との差（USD・崩れあり窓）': main_rule['F_xlv との差（etf_ita_xlk.verdict）'][W_CRASH]['判定'],
                        'F_xlv との差（USD・ドットコム級なし窓）': main_rule['F_xlv との差（etf_ita_xlk.verdict）'][W_DC]['判定']},
                    '参考の判定（F_now_ITA10＝SHLD5 を ITA5 に置いた形）': {
                        '3条件（F_main と・USD・崩れあり窓）': dec['F_now_ITA10（SHLD5→ITA5）']['USD の枠（主）']['F_main と比べた3条件']['3条件すべて（崩れあり窓・書庫:19497 と同じ窓）'],
                        'F_xlv との差（USD・崩れあり窓）': dec['F_now_ITA10（SHLD5→ITA5）']['USD の枠（主）']['F_xlv との差（etf_ita_xlk.verdict）'][W_CRASH]['判定']},
                    '配分': '変えない（報告するだけ・事前登録 decision）'}
    else:
        decision = {'3条件（F_main と・USD・崩れあり窓）': main_rule['F_main と比べた3条件']['3条件すべて（崩れあり窓・書庫:19497 と同じ窓）'],
                    'F_xlv との差': main_rule['F_xlv との差（etf_ita_xlk.verdict）'][W_CRASH]['判定'], '配分': '変えない（報告するだけ）'}

    deviations = list(info['deviations'])
    if shld_failed:
        deviations.append('事前登録の食い違いの読み: A_final_allocation.new_assets.SHLD は 2023-09 以前を ITA と書き、common.proxy_gate は相関 ≥ 0.90 の代理だけを使い'
                          '満たせない本を外すと書く。この道具は common.proxy_gate を優先した（＝事前登録どおりの判定は『測れない』）。ITA つなぎの F_now は参考として並べた')
        deviations.append('SHLD: 事前登録の代理（2023-09 以前は ITA）が代理の門を通らない（相関 '
                          f"{info['gates']['SHLD']['corr']}・36か月）。F_now は事前登録どおりには測れない。参考として、門を通らない ITA つなぎのまま SHLD を置いた F_now と、"
                          'SHLD5 を ITA5 に置いた F_now_ITA10 を同じ物差しで並べた（どちらも 2023-09 以前の SHLD の部分は ITA と同じ＝違いは最後の36か月だけ）')
        deviations.append('SHLD_EU（感度・後知恵）も代理の門を通らない（相関 ' f"{info['gates']['SHLD_EU']['corr']}）＝数字は参考")
    deviations.append('外国税の k: SHLD は保有の米国上場の比 s（' f"{info['shld']['us_share']}" '）で 0.10s＋0.20(1−s)＝X の GRID と同じ作法（common.costs の『米国上場は×10%』ではなく R の k の作法）')
    deviations.append('100年の代用の (3) は書庫:19497 と同じ『全体の形』（個別株15を今の席の業種の写し ' + json.dumps({k: round(v, 2) for k, v in cc.items()}) + '）で判定し、ETF 側だけの値も並べた')

    out_rows = {nm: {k: v for k, v in info['world_rows'].get(nm.split('（')[0], {}).items()} for nm in ('FBT', 'SHLD', 'SHLD_EU')}
    doc.update(
        frames={'USD': 'night/bestpf_check.py と同じ（ドル建て）', '円': f'月次のドル建ての値に FRED DEXJPUS の月末の比を掛けた（{fx_url}）・B/C/D はドルの値のまま（為替の期待変化0）'},
        forms={nm: f for nm, f in allf.items()},
        forms_note=('results の F_now は SHLD を門を通らない ITA つなぎ（2023-09 以前＝ITA）のまま置いた形＝事前登録どおりの F_now ではない（decision・deviations を見よ）'
                    if shld_failed else 'F_now は事前登録どおり'),
        inputs={'X.rank_result（R の25本＋R7）': 'night/bestpf_ext.py（写しはこの道具のキャッシュへ）',
                'π': 'out/bestpf_calibration.json の pi_main（bestpf_eval.load_pi）', 'D': 'out/bestpf_cma_2026.json（bestpf_eval.load_D・無い本は C）',
                '新しい本の代理の門': {c: info['gates'][c] for c in ('FBT', 'SHLD', 'SHLD_EU') if c in info['gates']},
                '新しい本の費用': {c: info['costs'][c] for c in ('FBT', 'SHLD') if c in info['costs']},
                '新しい本の世界': out_rows, 'SHLD の米国／米国外と手の業種': info['shld'], 'SHLD_EU の米国外上位10社': info['eu_basket'],
                'FBT・SHLD の業種の上乗せ': info['expo_new'], '席（個別株の写しに使った）': seats, '個別株(%)': cpct,
                '100年の代用の部品': 'alloc_check.century と同じ（NASDAQ100＝テック3業種65%＋市場35%・SMH＝Chips・ITA＝Aero＋Guns・XLV＝Drugs＋MedEq＋Hlth）＋ FBT＝Drugs・SHLD＝Aero＋Guns',
                'unx_assets の回帰の検査': info['regression']},
        results={'USD の枠（主）': U.strip_raw(tab_usd), '円の枠（感度）': U.strip_raw(tab_jpy),
                 '100年の代用（全体の形・個別株＝席の業種の写し）': {nm: U.strip_century(v) for nm, v in cent_whole.items()},
                 '100年の代用（ETF 側だけ）': {nm: U.strip_century(v) for nm, v in cent_etf.items()},
                 '判定の中身': dec},
        decision=decision, deviations=deviations,
        caveats=['SHLD の代理（ITA）は最後の36か月で相関 0.58・年率で −10pt 離れていた（SHLD 35.9% 対 ITA 25.9%）＝2023-09 以前の『SHLD』は実質 ITA',
                 'FBT の 2006-06 以前は ^BTK（価格指数・配当ほぼ無し）− 経費率/12＝配当の分だけ控えめ（FBT の配当はほぼ0）',
                 '100年の代用では FBT＝Drugs・SHLD＝Aero＋Guns（ITA と同じ）＝100年では SHLD と ITA を区別できない',
                 'B・C・D の新しい本: FBT・SHLD は業種の上乗せ（保有→French 49）と JPM 米国大型（SHLD は米国外分を EAFE）・D はアナリストの予想が無いので C',
                 '判定・配分には使わない（材料）'],
        secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    U.log('→', OUT, f'{time.time() - t0:.0f}秒')
    for frame, tab in (('USD', tab_usd), ('円', tab_jpy)):
        for wn in (W_CRASH, W_DC):
            for nm in allf:
                r = tab[wn][nm]
                U.log(f"[{frame}][{wn}] {nm[:28]:<28} P15 {r['P15π']:5.1f}（A2抜き {r['P15π（A2を外す）']:4.1f}） P5 {r['P5π（5%未満）']:4.1f} P0 {r['P0π（元本割れ）']:4.1f} "
                      f"最悪 {r['最悪の世界']:5.2f} 平均 {r['π加重の平均の年率']:5.2f} ぶれ {r['ぶれ']:4.1f} 下落 {r['最大下落']:6.1f} 後 {r['崩れ2000型_16〜18年目']:5.2f} 過去20年 {r['過去の転がる20年で15%以上']:5.1f}")
    for nm, d in cent_whole.items():
        a, b = d['30年の積立（起点1965〜1995）'], d['20年の積立（起点1965〜2005）']
        U.log(f"100年（全体） {nm[:28]:<28} 30年 中央{a['中央値']} 下位10%{a['下位10%点']} 勝ち{a['市場に勝った割合']} | 20年 中央{b['中央値']} 下位10%{b['下位10%点']} 最悪{b['最悪']}")
    U.log(json.dumps(decision, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
