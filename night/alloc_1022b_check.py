#!/usr/bin/env python3
"""night/alloc_1022b_check.py — 配分の変更（ITA の5を MISL へ）の前後を並べる（2026-10-22・参考・判定なし）

ユーザー明示指示「ITAをppaに5％移して」→ PPA（Invesco Aerospace & Defense）は楽天証券で買えない（2026-10-22 の楽天の米国 ETF の一覧
ETFD.csv の1,370行に無い・SBI の米国株式の取扱一覧〔2026-10-16〕にも無い）と伝え、本人が「MISL に移す（楽天で買える）」を選んだ。
これはその変更そのものの前後の検査（ルール10の「変更の検査」）で、判定の名前は付けない。作りは night/alloc_1022_check.py を写し、
MISL を物差しへ足した（unx_assets.add_extra＝既定は空の差し込み口）。形と物差しは結果を見る前にこのファイルで固定し、回す前にコミットする。

形（ETF 側・全体の%。個別株10は物差しの外）:
  前（ITA 5・2026-10-22〜）: QQQM 40 / SMH 30 / ITA 5 / SHLD 5 / XLV 5 / FBT 5
  新（MISL 5）            : QQQM 40 / SMH 30 / MISL 5 / SHLD 5 / XLV 5 / FBT 5
MISL の行: 2022-11 から本物（Yahoo の配当込みの月次）・2022-10 以前は ITA の系列（R の ITA＝2006-05 以前は FSDAX）から
  経費率の差（out/etf_profiles.json の MISL − ITA）/12 を月ごとに引いたもの。保有・費用は out/etf_profiles.json（MISL は Alpha Vantage 2026-10-16）。
  世界B は保有の業種（R の作法）・C は JPM の米国大型株（ITA と同じ）・D は材料が無いので C で代える（SHLD・FBT と同じ・bestpf_eval.load_D の決まり）・
  100年の代用は ITA と同じ写し（French の Aero＋Guns）。代理の門（相関 ≥0.90）を通らなくても残す（SHLD と同じ扱い・出力で名指し）。
物差し: alloc_1022_check と同じ（unx_assets.measure・3つの枠・上振れ〔道の束〕・過去の転がる積立・100年の代用〔個別株10は席の業種の写し〕・
  感度5本の差〔ndx_swap_check.judge の差だけ〕・中身の集中〔ndx_swap_check.lookthrough・城は席5社×2%〕）
  ＋ 本物の記録だけの窓（MISL と ITA は 2022-11〜・形は 2023-10〜〔SHLD の本物の最初の月から〕・ドルと円）＋ MISL の中身の重なり（ITA・QQQ・SHLD）。
回帰の検査（どれかが外れれば止める）:
  (a0) MISL を足した build の MISL 以外の本の行と系列が、足さない build（別のプロセス）と1ビットも違わない
       （順位の欄 rank・score・worst・top10_in_worlds は本の集まりで変わるので比べない＝unx_assets の回帰①と同じ）
  (a)  前が out/alloc_1022_check.json の『新（2026-10-22〜）』と一致（USD・崩れあり・小数1桁）
  (b)  感度の主が measure と 1e-9 以内（USD と円）
使い方: python3 night/alloc_1022b_check.py → out/alloc_1022b_check.json
"""
import datetime, json, os, pickle, subprocess, sys, time

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'alloc_1022b_check.json')

PREV, NEW = '前（ITA 5・2026-10-22〜）', '新（MISL 5）'
FORMS = {
    PREV: {'QQQM': 40, 'SMH': 30, 'ITA': 5, 'SHLD': 5, 'XLV': 5, 'FBT': 5},
    NEW: {'QQQM': 40, 'SMH': 30, 'MISL': 5, 'SHLD': 5, 'XLV': 5, 'FBT': 5},
}
REF = (os.path.join(BASE, 'out', 'alloc_1022_check.json'), '新（2026-10-22〜）')
REG_KEYS = ('P15π', 'P5π（5%未満）', '最悪の世界', '最大下落', 'ぶれ', 'π加重の平均の年率')
MISL_JA = '米国の航空宇宙・防衛（First Trust Indxx Aerospace & Defense・39社）'
MISL_LAST = 202210                   # 代理を使う最後の月（設定 2022-10-25・本物の月次は 2022-11 から）
REAL_PAIR = (202211, 202609)         # MISL と ITA の本物どうし
REAL_FORM = (202310, 202609)         # 形の本物どうし（SHLD の本物は 2023-10 から）
RANK_KEYS = {'rank', 'score', 'worst', 'top10_in_worlds'}
NOEXTRA = """
import sys, pickle
sys.path.insert(0, 'night')
import unx_assets as U
r = U.build()
pickle.dump(dict(rows=r['rows'], chains=r['chains']), open(sys.argv[1], 'wb'))
"""


def canon(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False, default=str)


def main():
    import unx_assets as U
    import upside_check as UC
    import ndx_swap_check as N
    import bestpf_eval as E
    import etf_forward_combo as CB
    t0 = time.time()
    W_CRASH, W_DC = UC.W_CRASH, UC.W_DC
    for f in FORMS.values():
        assert abs(sum(f.values()) - 90) < 1e-9, f

    # (a0) 足さない build を別のプロセスで（同じ道具・同じキャッシュ）
    os.makedirs(U.CDIR, exist_ok=True)
    pk = os.path.join(U.CDIR, 'alloc_1022b_noextra.pkl')
    U.log('足さない build（別のプロセス）')
    subprocess.run([sys.executable, '-c', NOEXTRA, pk], cwd=BASE, check=True)
    ref0 = pickle.load(open(pk, 'rb'))

    U.add_extra('MISL', MISL_JA, 'ITA', MISL_LAST)
    res = U.build()
    rows, chains = res['rows'], res['chains']
    added = sorted(set(rows) - set(ref0['rows']))
    bad = []
    for c in ref0['rows']:
        a = {k: v for k, v in ref0['rows'][c].items() if k not in RANK_KEYS}
        b = {k: v for k, v in rows[c].items() if k not in RANK_KEYS}
        if canon(a) != canon(b):
            bad.append(('行', c, sorted(k for k in set(a) | set(b) if canon(a.get(k)) != canon(b.get(k)))[:8]))
        if ref0['chains'][c] != chains[c]:
            bad.append(('系列', c))
    rank_moved = sorted(c for c in ref0['rows'] if any(canon(ref0['rows'][c].get(k)) != canon(rows[c].get(k)) for k in RANK_KEYS))
    reg_a0 = dict(ok=(not bad and added == ['MISL']), 足した本=added, 食い違い=bad[:20], 比べた本=len(ref0['rows']),
                  順位の欄が動いた本=rank_moved, 順位の欄='rank・score・worst・top10_in_worlds（本の集まりで変わる＝比べない）')
    U.log('(a0)', reg_a0['ok'], added, bad[:3])

    F = {k: dict(v) for k, v in FORMS.items()}
    assets = sorted({a for f in F.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, assets)
    pi, _, _ = E.load_pi()
    _, sim = U.tables()
    U.log('USD の枠（', len(F), '形）')
    tab_usd = U.measure(F, rows, chains, mega=mega)
    path, theirs = REF
    refj = json.load(open(path))['results']['USD・崩れあり（主）'][theirs]
    reg_ab, ok_ab = {}, True
    for k in REG_KEYS:
        a, b = tab_usd[W_CRASH][PREV][k], refj[k]
        same = UC.r1(a) == UC.r1(b)
        reg_ab[f'{PREV}・{k}'] = {os.path.basename(path): b, 'この道具': a, '一致': same}
        ok_ab = ok_ab and same
    k4, chips = N.chips_adj(rows, assets)
    vt_usd = N.variants(F, rows, chains, k4)
    reg_c = N.regress_variants(vt_usd, tab_usd)
    U.log('回帰の検査', ok_ab, reg_c['max_abs_diff'])
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/alloc_1022b_check.py', kind='参考・判定なし（ユーザーが明示指示した変更の前後の検査）',
               question='ITAをppaに5％移して → PPA は楽天で買えない → 本人の選択「MISL に移す（楽天で買える）」',
               regression={'(a0) MISL を足した build の MISL 以外の本が、足さない build と1ビットも違わない（順位の欄を除く）': reg_a0,
                           '(a) 前が out/alloc_1022_check.json の『新（2026-10-22〜）』と一致（USD・崩れあり・小数1桁）': dict(ok=ok_ab, rows=reg_ab),
                           '(b) 感度の計算の主と unx_assets.measure（USD・丸める前・1e-9）': {k: v for k, v in reg_c.items() if k != 'rows'}})
    if not (reg_a0['ok'] and ok_ab and reg_c['ok']):
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
                                  '崩れ2000型_16〜18年目', '過去の転がる20年で15%以上', '世界ごとの年率', '超大型株の比率（ETF側）')}
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
    N.NET_ARG = dict(N.NET_ARG, MISL='MISL')
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

    # ── 本物の記録だけの窓（代理を含まない月）──
    R = U.R

    def stats(f, ch, a, b):
        ms = R.months(a, b)
        tot = sum(f.values())
        G = np.array([[ch[c][m] for m in ms] for c in f])
        w = np.array([f[c] / tot for c in f])
        g, v, d = CB.path_stats((w @ G)[None, :], len(ms))
        yr = {}
        for y in sorted({m // 100 for m in ms}):
            ys = [i for i, m in enumerate(ms) if m // 100 == y]
            yr[str(y) + ('（' + f'{ms[ys[0]] % 100}〜{ms[ys[-1]] % 100}月' + '）' if len(ys) < 12 else '')] = round(100 * (float(np.prod(1 + (w @ G)[ys])) - 1), 1)
        return dict(窓=f'{a}〜{b}', 月数=len(ms), 年率=round(100 * float(g[0]), 2), ぶれ=round(100 * float(v[0]), 1), 最大下落=round(100 * float(d[0]), 1), 暦年=yr)

    def corr(a, b, ch, lo, hi):
        ms = R.months(lo, hi)
        return round(float(np.corrcoef([ch[a][m] for m in ms], [ch[b][m] for m in ms])[0, 1]), 3)
    real = {}
    for fr, ch in (('USD', chains), ('円', ch_jpy)):
        real[fr] = {
            'MISL と ITA（本物どうし）': {c: stats({c: 1}, ch, *REAL_PAIR) for c in ('MISL', 'ITA', 'QQQM')},
            '形（本物どうし・毎月組み直し）': {nm: stats(f, ch, *REAL_FORM) for nm, f in F.items()}}
    real['月次の相関（USD・2022-11〜2026-09）'] = {'MISL×ITA': corr('MISL', 'ITA', chains, *REAL_PAIR), 'MISL×QQQM': corr('MISL', 'QQQM', chains, *REAL_PAIR),
                                              'ITA×QQQM': corr('ITA', 'QQQM', chains, *REAL_PAIR), 'MISL×SMH': corr('MISL', 'SMH', chains, *REAL_PAIR),
                                              'ITA×SMH': corr('ITA', 'SMH', chains, *REAL_PAIR)}

    # ── MISL の中身の重なり（out/etf_profiles.json）──
    prof = json.load(open(os.path.join(BASE, 'out', 'etf_profiles.json')))['etfs']

    def hold(c):
        return {t.upper(): w for t, w in prof[c]['h']}
    hm = hold('MISL')
    tm = sum(hm.values())
    over = {}
    for c in ('ITA', 'QQQ', 'SHLD'):
        hx = hold(c)
        over[c] = dict(asof=prof[c].get('asof'), MISL_の重さのうち_同じ会社=round(100 * sum(w for t, w in hm.items() if t in hx) / tm, 1),
                       小さいほうの重みの合計=round(100 * sum(min(w, hx[t]) for t, w in hm.items() if t in hx), 1))
    top = sorted(hm.items(), key=lambda kv: -kv[1])[:10]
    inside = {t: round(5 * w, 2) for t, w in top[:5]}                 # 全体の%（MISL 5%×中身）
    info = res['info']
    mrow = rows['MISL']
    Dm, Dsrc, _ = E.load_D(rows, ['MISL', 'ITA'])
    misl = dict(
        代理=dict(form=U.PROXY_FORM['MISL'], 最後の月=MISL_LAST, 経費率の差=info['extra']['MISL'].get('er_diff'),
                代理の門=info['gates'].get('MISL'), 門を通らず残した=info['gate_failed_kept'].get('MISL')),
        世界の値={c: {k: (round(100 * rows[c][k], 2) if isinstance(rows[c].get(k), float) else rows[c].get(k))
                   for k in ('A1', 'A2', 'B', 'C', 'er_vehicle', 'dy_vehicle', 'tax_drag', 'vol_A1', 'maxdd_A1')} for c in ('MISL', 'ITA')},
        D={c: dict(値=round(100 * Dm[c], 2), 出どころ=Dsrc[c]) for c in ('MISL', 'ITA')},
        業種=dict(MISL=info['expo_new'].get('MISL'), ITA={k: rows['ITA'].get(k) for k in ('record_share_e', 'holdings_coverage', 'top_industries')}),
        超大型株の比率=dict(MISL=round(100 * mega.get('MISL', 0.0), 1), ITA=round(100 * mega.get('ITA', 0.0), 1)),
        中身=dict(asof=prof['MISL'].get('asof'), 上位10社=[(t, round(100 * w, 2)) for t, w in top], 全体の中の比率_上位5社=inside,
                重なり=over, 経費率=prof['MISL'].get('er'), 純資産=prof['MISL'].get('aum')),
        行の出どころ=dict(A1A2='R.main（unx_assets の2回目）・2022-10 以前は代理', B=mrow.get('B_src')))
    doc.update(
        forms=F,
        results={'USD・崩れあり（主）': table, 'USD・ドットコム級なし': {nm: show(tab_usd[W_DC][nm]) for nm in F},
                 '円・崩れあり': {nm: show(tab_jpy[W_CRASH][nm]) for nm in F},
                 '過去の転がる積立（USD・2000-09〜2026-09）': roll, '100年の代用（全体の形）': cent_out,
                 '感度5本の差（判定の名前は付けない）': diffs, '中身の集中（lookthrough・参考）': look,
                 '本物の記録だけの窓': real, 'MISL の行': misl},
        frames={'USD': 'night/bestpf_check.py と同じ（ドル建て）', '円': f'月次のドル建ての値に FRED DEXJPUS の月末の比（{fx_url}）・B/C/D はドルのまま'},
        castle_copy=dict(seats=seats, castle_pct=cpct),
        caveats=['ETF 側だけを測る（個別株10は物差しの外・100年の代用だけ席の業種の写しで全体の形）・判定はしない',
                 'MISL の 2022-10 以前は ITA の系列から経費率の差を引いたもの＝26年の窓の大半は ITA の値動き（MISL の本物の記録は 2022-11 からの47か月）',
                 'MISL の D の世界は材料が無いので C で代える（ITA には D がある＝D の世界の差の一部は材料の違い）',
                 '100年の代用は MISL と ITA が同じ写し（Aero＋Guns）＝差は出ない',
                 'SHLD の 2023-09 以前は ITA のつなぎ（代理の門を通らない）',
                 '中身の集中は ETF の中身の写真（out/etf_profiles.json）の時点のまま（MISL は 2026-10-16）'],
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
    U.log('本物', json.dumps(real, ensure_ascii=False)[:2500])
    U.log('MISL', json.dumps(misl, ensure_ascii=False, default=str)[:2500])


if __name__ == '__main__':
    main()
