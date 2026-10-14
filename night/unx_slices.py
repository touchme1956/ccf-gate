#!/usr/bin/env python3
"""night/unx_slices.py — 未調査の候補の検定 B: 今の配分に『テックと一緒に下げない本』を少しだけ足す形（2026-10-14）

読むだけ。門・採点・配分（portfolio.json）・注文書には触れない。事前登録 out/unexplored_prereg.json（6f534c92）の groups.B_diversifier_slices どおり。
  土台   … F_now（ETF側 NDX40 / SMH25 / ITA5 / SHLD5 / XLV5 / FBT5）
  形     … N5＝NASDAQ100 から5（40→35）／P5＝ETF側の全部から比例で5／N10＝NASDAQ100 から10（数字は全体の%＝ETF側85の中）
  候補   … GLDM・EDV・TLT・UST_HEDGED_2621・TIP・GDX・SLV・XLU・VNQ・TOPIX・EWY・YEN_CASH（EDV5_GLDM5 は N10 と P10 だけ）
  参考   … MF_REF（AQR TSMOM＋米国3か月国債）・GOLDPLUS_REF（NDX＋(金−現金)×1 で NDX の10を置き換え）＝ラベルなし・数字だけ
  枠     … 円が主（ドル建ての月次 × FRED DEXJPUS の月末の比・円の本はそのまま・B/C/D は為替の期待変化0）／感度 FX18（円の本以外の B・C・D −1.8%/年）／
           USD はドル建ての本だけの感度
判定（候補×形ごと・F_now との差）: (1) P15π の低下 ≤ 1.5pt (2) 最悪の世界・P5π・最大下落がすべて良い (3) 100年の代用（月次の写しがある本は月次・
  債券・金・現金は年次の写し）で20年・30年の積立の市場比の中央が下がらず下位10%が上がる。
  『堅い価値あり』＝(1)(2)(3) が崩れあり・ドットコム級なしの両方の窓で成り立ち (1) が A2 を外しても成り立つ／『条件を満たす』＝崩れありの窓で
  (1)(2) が成り立ち (3) が成り立つか測れない／『満たさない』＝それ以外。FX18 でラベルが変わる本は名指し。勧めるかは人の判断（配分は変えない）。

使い方: python3 night/unx_slices.py  → out/unx_slices.json
"""
import datetime, json, math, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import unx_assets as U   # noqa: E402

OUT = os.path.join(BASE, 'out', 'unx_slices.json')
W_CRASH, W_DC = '崩れあり 2000-09〜', 'ドットコム級なし 2002-11〜'
F_NOW = {'QQQM': 40, 'SMH': 25, 'ITA': 5, 'SHLD': 5, 'XLV': 5, 'FBT': 5}
CANDS = ['GLDM', 'EDV', 'TLT', 'UST_HEDGED_2621', 'TIP', 'GDX', 'SLV', 'XLU', 'VNQ', 'TOPIX', 'EWY', 'YEN_CASH']
PAIR = ('EDV5_GLDM5', {'EDV': 5, 'GLDM': 5})
REF_TRUNC_WIN = lambda last: {f'崩れあり 2000-09〜{last // 100}-{last % 100:02d}': (200009, last),
                              f'ドットコム級なし 2002-11〜{last // 100}-{last % 100:02d}': (200211, last)}


def sl(base, add, kind):
    """形を作る。add={本: 全体の%}・kind: N（NDX から）／P（ETF側の全部から比例で）"""
    tot_add = sum(add.values())
    f = dict(base)
    if kind == 'N':
        f['QQQM'] = f['QQQM'] - tot_add
    else:
        s = sum(base.values())
        f = {k: v * (s - tot_add) / s for k, v in base.items()}
    for k, v in add.items():
        f[k] = f.get(k, 0) + v
    return f


def forms():
    out = {'BASE（F_now）': dict(F_NOW)}
    meta = {}
    for c in CANDS:
        for nm, add, kind in (('N5', {c: 5}, 'N'), ('P5', {c: 5}, 'P'), ('N10', {c: 10}, 'N')):
            k = f'{c}|{nm}'
            out[k] = sl(F_NOW, add, kind)
            meta[k] = (c, nm)
    pc, padd = PAIR
    for nm, kind in (('N10', 'N'), ('P10', 'P')):
        k = f'{pc}|{nm}'
        out[k] = sl(F_NOW, padd, kind)
        meta[k] = (pc, nm)
    return out, meta


def conds(tab, k, base, c3):
    r = {}
    for wn in (W_CRASH, W_DC):
        a, b = tab[wn][k]['_raw'], tab[wn][base]['_raw']
        r[wn] = dict(c1=bool(a['P15'] >= b['P15'] - 0.015), c1_noA2=bool(a['P15_noA2'] >= b['P15_noA2'] - 0.015),
                     c2=bool(a['worst'] > b['worst'] and a['P5'] < b['P5'] and a['mdd'] > b['mdd']),
                     dP15=round(100 * (a['P15'] - b['P15']), 2), dP15_noA2=round(100 * (a['P15_noA2'] - b['P15_noA2']), 2),
                     dworst=round(100 * (a['worst'] - b['worst']), 2), dP5=round(100 * (a['P5'] - b['P5']), 2),
                     dmdd=round(100 * (a['mdd'] - b['mdd']), 2), dmean=round(100 * (a['mean_pi'] - b['mean_pi']), 2),
                     dvol=round(100 * (a['vol'] - b['vol']), 2))
    firm = all(r[w]['c1'] and r[w]['c2'] and r[w]['c1_noA2'] for w in (W_CRASH, W_DC)) and c3 is True
    meets = r[W_CRASH]['c1'] and r[W_CRASH]['c2'] and (c3 is True or c3 is None)
    lab = '堅い価値あり' if firm else ('条件を満たす' if meets else '満たさない')
    return lab, r


def main():
    t0 = time.time()
    res = U.build()
    rows, chains, info = res['rows'], res['chains'], res['info']
    F, meta = forms()
    usable = {k: f for k, f in F.items() if all(a in rows for a in f)}
    dropped = {k: [a for a in f if a not in rows] for k, f in F.items() if k not in usable}
    # 参考
    refs = {}
    gp = 'GOLDPLUS_REF'
    if gp in rows:
        refs[f'{gp}|NDX10を置換'] = sl(F_NOW, {gp: 10}, 'N')
    mf = 'MF_REF'
    mf_forms = {}
    if mf in rows:
        mf_forms = {'BASE（F_now）': dict(F_NOW), f'{mf}|N5': sl(F_NOW, {mf: 5}, 'N'), f'{mf}|P5': sl(F_NOW, {mf: 5}, 'P'), f'{mf}|N10': sl(F_NOW, {mf: 10}, 'N')}
    assets = sorted({a for f in list(usable.values()) + list(refs.values()) + list(mf_forms.values()) for a in f} | {'VOO'})
    mega = U.mega_map(rows, assets)
    import bestpf_eval as E
    Dmap, Dsrc, _ = E.load_D(rows, assets)
    for c in assets:
        if 'D_override' in rows[c]:
            Dmap[c] = rows[c]['D_override']; Dsrc[c] = 'D_override（参考の本）'
    rows_fx, Dmap_fx = U.fx18_rows(rows, Dmap)
    ch_jpy, fx_url = U.jpy_chains(chains)

    allp = dict(usable, **refs)
    U.log('円の枠（主）', len(allp), '形')
    tab_j = U.measure(allp, rows, ch_jpy, Dmap=Dmap, mega=mega)
    U.log('円の枠・FX18')
    tab_jfx = U.measure(allp, rows_fx, ch_jpy, Dmap=Dmap_fx, mega=mega)
    usd_forms = {k: f for k, f in allp.items() if not any(a in U.YEN_ASSETS for a in f)}
    U.log('USD の枠（ドル建ての本だけ）', len(usd_forms))
    tab_u = U.measure(usd_forms, rows, chains, Dmap=Dmap, mega=mega)
    tab_mf = tab_mf_usd = None
    if mf_forms:
        last = rows[mf]['trunc_to']
        wins = REF_TRUNC_WIN(last)
        U.log('参考 MF_REF（窓を', last, 'までに縮める）')
        tab_mf = U.measure(mf_forms, rows, ch_jpy, Dmap=Dmap, mega=mega, windows=wins, a2=(201110, last))
        tab_mf_usd = U.measure(mf_forms, rows, chains, Dmap=Dmap, mega=mega, windows=wins, a2=(201110, last))

    # ── 100年の代用 ──
    U.log('100年の代用')
    cc, seats, cpct = U.castle_copy()
    base_k = 'BASE（F_now）'
    cent = {}
    base_m = U.century_monthly(U.whole(F_NOW, cc))
    base_a = U.century_annual(U.whole(F_NOW, cc))
    base_m_etf = U.century_monthly(F_NOW)
    base_a_etf = U.century_annual(F_NOW)
    for k, f in usable.items():
        if k == base_k:
            continue
        c = meta[k][0]
        comps = [a for a in f if a not in F_NOW]
        if all(a in U.MONTHLY_OK for a in comps):
            how = '月次の写し'
            cf, cb = U.century_monthly(U.whole(f, cc)), base_m
            cfe, cbe = U.century_monthly(f), base_m_etf
        elif all(a in U.ANNUAL_MAP for a in comps):
            how = '年次の写し（Damodaran＋French の月次を暦年で複利）'
            cf, cb = U.century_annual(U.whole(f, cc)), base_a
            cfe, cbe = U.century_annual(f), base_a_etf
        else:
            how, cf, cb, cfe, cbe = '測れない（100年の写しが無い）', None, None, None, None
        cent[k] = dict(how=how, c3=U.cond3(cf, cb), form=U.strip_century(cf), base=U.strip_century(cb),
                       c3_etf_only=U.cond3(cfe, cbe), form_etf_only=U.strip_century(cfe))

    # ── ラベル ──
    labels, detail, flips, usd_labels = {}, {}, [], {}
    for k in usable:
        if k == base_k:
            continue
        c3 = cent[k]['c3']
        lab, r = conds(tab_j, k, base_k, c3)
        lab_fx, r_fx = conds(tab_jfx, k, base_k, c3)
        labels[k] = lab
        detail[k] = {'円（主）': r, '円・FX18': r_fx, '(3)': c3, '(3) の写し': cent[k]['how'], 'ラベル（円・主）': lab, 'ラベル（円・FX18）': lab_fx}
        if lab != lab_fx:
            flips.append(f'{k}: {lab} → FX18 で {lab_fx}')
        if k in usd_forms:
            lu, ru = conds(tab_u, k, base_k, c3)
            usd_labels[k] = lu
            detail[k]['USD（感度）'] = ru
            detail[k]['ラベル（USD・感度）'] = lu
    cand_table = {}
    for k, lab in labels.items():
        c, nm = meta[k]
        cand_table.setdefault(c, {})[nm] = lab

    deviations = list(info['deviations'])
    if 'SHLD' in info['gate_failed_kept']:
        deviations.append('土台 F_now の SHLD: 事前登録の代理（2023-09 以前は ITA）が代理の門を通らない（相関 '
                          f"{info['gates']['SHLD']['corr']}）。B の差は土台との差なので、SHLD を門を通らない ITA つなぎのまま置いた F_now を土台にした（A の参考と同じ）")
    deviations += [
        'UST_HEDGED_2621 の円の月次は事前登録の式（TLT〔代理 VUSTX〕−（TB3MS − 日本の3か月）/12）のまま全期間に使い、実物 2621 の基準価額は代理の門にだけ使った。'
        '日本の3か月（IR3TIB01JPM156N）が無い月はコール（IRSTCI01JPM156N）・両方無い 2026-09 は 2026-08 の値を持ち越した（月ごとの一覧は inputs.日本の3か月）。'
        'YEN_CASH も同じ系列。ヘッジの金利差はその月の値（月平均）を使った',
        'MF_REF: 事前登録に B・C・D の式が無い＝上乗せ0（B＝Damodaran の T-bill の実質＋インフレ2.5%・C＝D＝JPM U.S. Cash 3.1）と置いた。'
        'AQR TSMOM が 2026-05 で終わる＝A1・A2 の窓を 2026-05 までに縮め、土台も同じ窓で測り直して並べた（0 で埋めない）。紙の上の値・費用0',
        'GOLDPLUS_REF: 月次＝QQQM の行（QQQ）＋(GLDM の行 − TB3MS/12)・B＝QQQM の B＋(R_GOLD − T-bill の B)・C＝QQQM の C＋(金の C − 3.1)・D＝QQQM の D＋(金の C − 3.1)。'
        '費用は QQQ の器のまま（実物の信託報酬は確かめていない）',
        '100年の代用の (3) は書庫:19497 と同じ『全体の形』（個別株15を今の席の業種の写し ' + json.dumps({k: round(v, 2) for k, v in cc.items()}) + '）で判定し、ETF 側だけの値も並べた。'
        '年次の写し: 株の部品は月次の写しを暦年で複利・債券（EDV・TLT・TIP・UST_HEDGED）は Damodaran の T-bond（10年）・金は Gold・円の現金は T-bill（米国）で代えた（円の金利・ヘッジ・銀・REIT・日本株・韓国株の100年の系列は持たない）',
        '外国税の k: R の作法（米国の株・債券・REIT の器 0.10／米国外の株が大半の GDX・EWY 0.20／SLV・GLDM・円の本 0）。common.costs の『米国上場は×10%』とは GDX・EWY で違う',
        '配当利回り（外国税に使う）: 新しい米国上場の本は Yahoo の分配金の直近12か月 ÷ 2026-09 末の終値（楽天 ETFD.csv の値も並べた）。経費率は楽天 ETFD.csv（VNQ は SEC の目論見書・楽天の一覧に無い）',
        'GDX の世界B: French 49 の Gold は時価総額の0.25%以上の月が240に届かず、R の作法どおり上乗せ0（事前登録どおりの全期間の上乗せは −3.79%/年＝感度 _b_raw）',
    ]
    def wr(c):
        return info['world_rows'].get(c) or {k: (round(100 * rows[c][k], 3) if isinstance(rows[c].get(k), float) else rows[c].get(k))
                                             for k in ('A1', 'A2', 'B', 'C', 'er_vehicle', 'dy_vehicle', 'tax_drag', 'vol_A1', 'maxdd_A1')}
    doc = dict(
        generated=datetime.date.today().isoformat(), tool='night/unx_slices.py', prereg=U.PREREG,
        question='今の配分（F_now）に『テックと一緒に下げない本』を少しだけ足す形（5〜10%）を標準の物差しで測る',
        frames={'円（主）': f'月次のドル建ての値 × FRED DEXJPUS の月末の比（{fx_url}）・円の本（YEN_CASH・UST_HEDGED_2621）はそのまま・B/C/D は為替の期待変化0',
                '円・FX18（感度）': '円の本以外の B・C・D から 1.8%/年（JPM 2026 の円高の前提）を引く', 'USD（感度）': 'ドル建ての本だけ・night/bestpf_check.py と同じ'},
        forms={k: {a: round(v, 4) for a, v in f.items()} for k, f in allp.items()}, forms_dropped=dropped,
        inputs={'代理の門（使った代理・重なる月・相関）': info['gates'], '外した本': info['excluded'],
                '門を通らないが土台の形のために残した本': info['gate_failed_kept'],
                '費用（新しい本）': info['costs'], '新しい本の世界（USD・%）': {c: wr(c) for c in CANDS + [mf, gp] if c in rows},
                '世界の定数': info['consts'], '日本の3か月': info['jp3m'], 'AQR TSMOM': info['tsmom'], '合成の系列の窓': info['syn_cover'],
                '2621 の実物（投資信託協会）': info['jita_2621'], 'D の出どころ': {c: Dsrc.get(c) for c in assets},
                'π': 'out/bestpf_calibration.json の pi_main', '席（個別株の写し）': seats, '個別株(%)': cpct,
                'unx_assets の回帰の検査': info['regression']},
        results={'円（主）': U.strip_raw(tab_j), '円・FX18（感度）': U.strip_raw(tab_jfx), 'USD（感度・ドル建ての本だけ）': U.strip_raw(tab_u),
                 '参考_MF_REF（窓を縮めた・円）': U.strip_raw(tab_mf) if tab_mf else None,
                 '参考_MF_REF（窓を縮めた・USD）': U.strip_raw(tab_mf_usd) if tab_mf else None,
                 '100年の代用': {'土台（全体の形）': {'月次': U.strip_century(base_m), '年次': U.strip_century(base_a)},
                              '土台（ETF側だけ）': {'月次': U.strip_century(base_m_etf), '年次': U.strip_century(base_a_etf)}, '形ごと': cent},
                 '判定の中身': detail},
        decision={'ラベル（円・主・候補×形）': cand_table, 'FX18 でラベルが変わる形': flips or 'なし',
                  'ラベル（USD・感度）': usd_labels, '参考の本（ラベルなし）': ['MF_REF', 'GOLDPLUS_REF'],
                  'note': '勧めるかは結果を見た人の判断（配分は変えない）'},
        deviations=deviations,
        caveats=['土台の SHLD は 2023-09 以前が ITA（代理の門を通らない）＝A の参考と同じ扱い',
                 '代理: EDV・TLT は VUSTX（デュレーションが短い＝下げも上げも控えめ）・TIP は VIPSX・GDX は FSAGX・SLV は SI=F・VNQ は VGSIX・FBT は ^BTK',
                 'B・C・D の債券は Damodaran の10年国債の100年と今の利回りを15年＝超長期の EDV の価格の動き（デュレーション約24年）は B・C・D に入っていない',
                 '円の枠の A1・A2 は 2000年以降の円安（DEXJPUS 107→157）を含む＝円の本（現金・ヘッジ債）はドル建ての本より不利に見える',
                 '100年の代用（年次）は米国の数字だけ＝為替・円の金利を持たない',
                 'VNQ は楽天の取扱一覧（ETFD.csv 2026-10-14）に無い（買える器は BBRE・RWR など）。GLDM・EDV などが NISA 成長投資枠の対象かは確かめていない',
                 '判定・配分には使わない（材料）'],
        secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    U.log('→', OUT, f'{time.time() - t0:.0f}秒')
    for wn in (W_CRASH, W_DC):
        for k in allp:
            r = tab_j[wn][k]
            U.log(f"[円][{wn[:6]}] {k:<22} P15 {r['P15π']:5.1f}（A2抜き {r['P15π（A2を外す）']:4.1f}） P5 {r['P5π（5%未満）']:4.1f} 最悪 {r['最悪の世界']:5.2f} "
                  f"平均 {r['π加重の平均の年率']:5.2f} ぶれ {r['ぶれ']:4.1f} 下落 {r['最大下落']:6.1f} 後 {r['崩れ2000型_16〜18年目']:5.2f} 過去20年 {r['過去の転がる20年で15%以上']:5.1f}")
    U.log(json.dumps(cand_table, ensure_ascii=False))
    U.log('FX18', flips)
    U.log('USD', json.dumps(usd_labels, ensure_ascii=False))


if __name__ == '__main__':
    main()
