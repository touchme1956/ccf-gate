#!/usr/bin/env python3
"""night/tsumitate_cand.py — つみたて投資枠で買える投資信託から、今の形に足す候補を探す（2026-10-27・参考・判定なし）

ユーザーの問い「積立投資枠で変える中だと？」（つみたて投資枠で買える中だと？）。配分は変えない。形と選び方は結果を見る前にこのファイルで固定し、回す前にコミットする。

今: QQQM 40 / SMH 30 / ITA 15 / SHLD 5 / XLV 5 / FBT 5（2026-10-27 の正本）
候補 X: 金融庁のつみたて投資枠の届出一覧（out/tsumitate_lineup.json・2026-09-18版）にある本のうち、unx_assets の行で同じ指数を測れるもの
  VYM＝楽天・米国高配当株式インデックス（FTSE High Dividend Yield＝VYM）・100年の写しは French の配当利回りの上位30%（時価加重）
  VOO＝eMAXIS Slim 米国株式（S&P500）・100年の写しは市場
  VT＝eMAXIS Slim 全世界株式（オール・カントリー）／VEA＝先進国（除く米国）／TOPIX＝eMAXIS Slim 国内株式（TOPIX）は100年の月次の写しが無い（物差しだけ）
  ⚠ つみたて投資枠に米国の小型株・小型バリュー・業種（生活必需品・エネルギー・金融ほか）の投信は無い（届出一覧の確認）
形: 今の NASDAQ100 から5を X へ（QQQM 35 + X 5）。smallcap_add で出す元は NASDAQ100 が最もよかったのでそろえる。
物差し: smh25_where と同じ（unx_assets.measure・USD・崩れあり・100年の代用 century_monthly）。
選び方（回す前に固定）:
  H1 100年: 30年の積立の比の中央値・最悪が今より上 ∧ 20年の積立で市場に勝った割合が下がらない
  H2 物差し: π加重の平均の差 ≥ −0.10pt ∧ 最大下落と5%未満が今より悪くない
  H1（測れない本は H1 を問わない）∧ H2 の候補を 30年の中央値の大きい順（測れない本は後ろ）。無ければ「足す候補なし（今のまま）」。
⚠ 100年の写しは業種の後知恵を含む（今わかっている勝ち業種を選びやすい）・器は業種の混ぜ物・費用と税は写しに入れない。
回帰の検査: 今が out/smh25_where.json の『今』と一致（USD・崩れあり・小数1桁）・感度の主が measure と 1e-9 以内。
使い方: python3 night/tsumitate_cand.py → out/tsumitate_cand.json
"""
import datetime, json, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'tsumitate_cand.json')

NOW = '今'
BASEF = {'QQQM': 40, 'SMH': 30, 'ITA': 15, 'SHLD': 5, 'XLV': 5, 'FBT': 5}
PROXY = {}
CANDS = ['VYM', 'VOO', 'VT', 'VEA', 'TOPIX']
FORMS = {NOW: dict(BASEF)}
for x in CANDS:
    f = dict(BASEF); f['QQQM'] -= 5; f[x] = 5
    FORMS[f'NASDAQ100→{x}'] = f
REF = (os.path.join(BASE, 'out', 'smh25_where.json'), '今')
REG_KEYS = ('P15π', 'P5π（5%未満）', '最悪の世界', '最大下落', 'ぶれ', 'π加重の平均の年率')


def main():
    import unx_assets as U
    import upside_check as UC
    import ndx_swap_check as N
    import mw_common as M
    t0 = time.time()
    W_CRASH = UC.W_CRASH
    res = U.build()
    rows, chains = res['rows'], res['chains']
    F = {k: dict(v) for k, v in FORMS.items()}
    assets = sorted({a for f in F.values() for a in f} | {'VOO'})
    miss = [a for a in assets if a not in rows]
    if miss:
        raise SystemExit(f'行が無い: {miss}')
    mega = U.mega_map(rows, assets)
    tab = U.measure(F, rows, chains, mega=mega)
    ref = json.load(open(REF[0]))['results']['USD・崩れあり（主）'][REF[1]]
    ok_a = all(UC.r1(tab[W_CRASH][NOW][k]) == UC.r1(ref[k]) for k in REG_KEYS)
    k4, chips = N.chips_adj(rows, assets)
    vt = N.variants(F, rows, chains, k4)
    reg = N.regress_variants(vt, tab)
    U.log('回帰の検査', ok_a, reg['ok'])
    if not (ok_a and reg['ok']):
        raise SystemExit('回帰の検査に失敗')
    # 100年の写し（この道具の中だけで足す）
    C = U.century_parts()
    Fm = C['F']
    cols, ret, capm, me, be, share, mkt = Fm.load()
    allm = sorted(C['mkt'])
    C['parts']['VYM'] = M.french_series('Portfolios_Formed_on_D-P', want='Value Weight Returns')['Hi 30']
    U.MONTHLY_OK.add('VYM')
    cent = {nm: U.strip_century(U.century_monthly(f)) for nm, f in F.items()}

    def cw(nm, lab, key):
        d = cent.get(nm) or {}
        w = next((v for k, v in d.items() if k.startswith(lab)), {})
        return w.get(key)
    table, why, passed = {}, {}, []
    b = tab[W_CRASH][NOW]
    for nm in F:
        r = tab[W_CRASH][nm]
        table[nm] = {k: r[k] for k in ('π加重の平均の年率', 'P15π', 'P5π（5%未満）', '最悪の世界', 'ぶれ', '最大下落', '過去の転がる20年で15%以上', '世界ごとの年率')}
        table[nm]['100年_30年_中央'] = cw(nm, '30年', '中央値'); table[nm]['100年_30年_最悪'] = cw(nm, '30年', '最悪')
        table[nm]['100年_20年_勝ち'] = cw(nm, '20年', '市場に勝った割合'); table[nm]['100年_20年_中央'] = cw(nm, '20年', '中央値')
        if nm == NOW:
            continue
        t, tb = table[nm], table[NOW]
        h1 = None if t['100年_30年_中央'] is None else (t['100年_30年_中央'] > tb['100年_30年_中央'] and t['100年_30年_最悪'] > tb['100年_30年_最悪']
              and t['100年_20年_勝ち'] >= tb['100年_20年_勝ち'])
        h2 = (r['π加重の平均の年率'] - b['π加重の平均の年率'] >= -0.10 and r['最大下落'] >= b['最大下落'] and r['P5π（5%未満）'] <= b['P5π（5%未満）'])
        why[nm] = dict(H1=h1, H2=h2)
        if h1 is not False and h2:
            passed.append(nm)
    passed.sort(key=lambda n: -(table[n]['100年_30年_中央'] or 0))
    diffs = {x: {k: v['差'] for k, v in N.judge(vt, W_CRASH, x, NOW)['感度'].items()} for x in F if x != NOW}
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/tsumitate_cand.py', kind='参考（配分は変えない・選び方は道具の頭に固定）',
               question='積立投資枠で変える中だと？', forms=F, proxies=PROXY, results=table, century=cent,
               sensitivity=diffs, choice=dict(per_candidate=why, passed=passed, pick=(passed[0] if passed else '足す候補なし（今のまま）')),
               caveats=['物差しの行は米国 ETF の値動き（投信の信託報酬との差は写していない）', 'VYM の100年の写しは配当利回りの上位30%で指数の作り方と違う', 'VT・VEA・TOPIX は100年の月次の写しが無い'],
               secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    for nm in F:
        t = table[nm]
        U.log(f"{nm:<16} 平均 {t['π加重の平均の年率']:5.2f} P15 {t['P15π']:5.1f} P5 {t['P5π（5%未満）']:5.1f} 最悪 {t['最悪の世界']:5.2f} 下落 {t['最大下落']:6.1f} 過去20 {t['過去の転がる20年で15%以上']:5.1f} "
              f"100年30中央 {t['100年_30年_中央']} 最悪 {t['100年_30年_最悪']} 20年勝ち {t['100年_20年_勝ち']} 20年中央 {t['100年_20年_中央']} {why.get(nm,'')}")
    U.log('通過', passed)
    for x, d in diffs.items():
        U.log(x, json.dumps({k: v['平均'] for k, v in d.items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
