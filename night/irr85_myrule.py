#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_myrule.py — **irr=85 が現れたら、ユーザーが選んだ基準で採点する**
（2026-08-11新設・ユーザー指示「irr85の銘柄が出た場合は先ほどまでに使っていた基準で採点してほしい」）

■ この道具は判定を一切変えない（読むだけ）
  Ω・採点式・刻み・重み・四関門・堀の関門・売却規律S1/S2/S3・配分・別枠85 のいずれにも触らない。
  `score_all.js` も `index.html` も `gate_exceptions.json` も書き換えない。
  出すのは **out/irr85_myrule.json** と画面だけ。買うかどうかは人が決める。

■ なぜ要るか（穴の実物）
  ユーザーの選定ルールは 2026-08-11 の対話で決まったが、**機械のどこにも書かれていなかった**。
  書いてあるのは todo_list.json のメモだけで、**判定する道具が無い**。
  ところが日次の門2審査 Routine が毎日パックを足すので irr=85 の顔ぶれは動く——
  実測: このセッション中に **14社→15社**（KRMN が加わった）。
  「8社」は**今日の写真であってルールではない**ので、次に85が付いた社を毎回手で裁くことになる。
  それは20年もたない（例外の常態化はいちばん静かな劣化）。

■ ユーザーの基準（2026-08-11・「nde4は抜いて」で確定）
    irr = 85  ∧  営業利益率 ≥ 11.89  ∧  FCF転換(5年合計比) ≥ 0.639  ∧  売上5年CAGR ≥ 1.76
  下限3本は**2018年ビンテージ irr=85 の継続組15社の最小値そのもの**（v9.9.129で丸め上げを撤回した実測値）。
  **新しい定数を一つも発明していない。**
  ⚠ **nde ≤ 4 は入れない**（ユーザーが明示的に外した）。門の別枠85 は nde を要求するので、
     **ユーザーの基準は門より緩い**——差は nde と 二本柱 の2点。その差はこの道具が毎回名指しで出す。

■ FCF転換だけ基準が割れている（8例目・v9.9.129で記録）
  下限 0.639 は歴史側の `conv5 = sum(FCF 5年) ÷ sum(NI 5年)`（WSTの値）から作られたのに、
  門の `ccfIrr85Frame` は**パックの単年 fcf/ni** に当てている。同じWSTで **0.639 vs 0.95＝1.49倍差**。
  → **この道具は歴史と同じ5年合計比で測る**（`irr85_fill_asof` の計算をそのまま呼ぶ＝二重実装を作らない）。
  単年で床を作り直すのは誤り——COHR の単年 0.086 が最小値になり**床が事実上消える**。

■ 判定不能の扱い（irr85_fill_asof の --today にあった取り違えをここで直す）
  あちらは「欠測が一つでもあれば判定不能」を**確定的な不合格より優先**していたので、
  **nde で確定的に落ちている MKSI/LOAR を「判定不能」と表示していた**。
  ここでは **確定的な不合格が優先**する——欠測は結論を保留する理由だが、
  別の条件が既に確定で落としているなら保留にならない。

■ 決めていないこと（**この道具は決めない。名指しで出すだけ**）
  **堀70 がユーザーの基準に入るのか未決。** 選んだ8社は全部 堀73.6〜87.8 なので
  **一度も試されていない**。KRMN が最初の試験になるはずだったが FCF転換で先に落ちた。
  次に「3本の床は通る ∧ 堀が70を割る」irr=85 が現れたら、そこで判断が要る——
  この道具は該当社に **⚠堀70未決** の印を付けて止まる（勝手にどちらかへ倒さない＝絶対のルール1）。

使い方:
  python3 night/irr85_myrule.py            人が読む形
  python3 night/irr85_myrule.py --json     out/irr85_myrule.json を書く（新着の検出はこちら）
  python3 night/irr85_myrule.py --new      新着（前回の在庫に無かった社）だけを出す
出力  : out/irr85_myrule.json
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'night'))
import irr85_fill_asof as F          # facts/pick/タグ表をそのまま使う（二重実装を作らない）

AS_JSON = '--json' in sys.argv[1:]
NEW_ONLY = '--new' in sys.argv[1:]
OUT = 'out/irr85_myrule.json'

# ── ユーザーの基準（2026-08-11）。**すべて既存の実測値で、新しい定数はゼロ** ──
OPM, CONV, CG = 11.89, 0.639, 1.76      # 2018年ビンテージ irr=85 継続組15社の最小値
MOAT_LINE = 70.0                        # 門の堀の関門。**ユーザーの基準に入るかは未決**


def conv5(t, fy):
    """歴史とまったく同じ式で FCF転換(5年合計比) を出す。測れなければ (None, 理由)"""
    if not (fy or '').isdigit():
        return None, 'reportDate が無い'
    g = F.facts(t)
    if not g:
        return None, 'companyfacts が取れない（ADR/日本株など）'
    Y = int(fy)
    yrs = list(range(Y - 4, Y + 1))
    fcfs, nis = [], []
    for y in yrs:
        ni, _ = F.pick(g, F.NI, y, instant=False)
        ocf, _ = F.pick(g, F.OCF, y, instant=False)
        # ⚠設備投資は **0 と欠測を区別する**（絶対のルール7）。候補タグに当たらないだけで
        #   0 と読むと FCF が過大に出る＝この床は**甘い側へ壊れる**。実害を1件踏んでいる——
        #   RBC は FY2023 で PaymentsToAcquirePropertyPlantAndEquipment を止め
        #   `PaymentsForCapitalImprovements` へ移ったので、直近3年の設備投資が丸ごと0と読まれ
        #   5年FCF転換が 1.361（真値 0.905）と出ていた。
        cap, capwhy = F.capex_of(g, y)
        if ni is None or ocf is None:
            return None, f'5年そろわず（{yrs[0]}-{yrs[-1]}・{y}年が欠測）＝単年で代用しない'
        if cap is None:
            return None, f'{capwhy}＝ゼロと読まない（ルール7）'
        fcfs.append(ocf - cap); nis.append(ni)
    if sum(nis) <= 0:
        return None, f'5年合計の純利益が0以下（{yrs[0]}-{yrs[-1]}）＝比が意味を持たない'
    return round(sum(fcfs) / sum(nis), 3), None


def judge(gm, c5, cagr):
    """ユーザーの基準で裁く。**確定的な不合格が欠測より優先**（irr85_fill_asof の取り違えをここで直す）"""
    ng, unk = [], []
    for v, thr, lbl in ((gm, OPM, '営利率'), (c5, CONV, 'FCF転換5年'), (cagr, CG, '成長')):
        if v is None:
            unk.append(lbl)
        elif v < thr:
            ng.append(f'{lbl} {v:.3f} < {thr}')
    if ng:
        return '不合格', '／'.join(ng)          # 測れた分で既に落ちている＝保留にしない
    if unk:
        return '判定不能', '測れない: ' + '／'.join(unk)
    return '合格', ''


def main():
    prev = {}
    if os.path.exists(OUT):
        try:
            prev = (json.load(open(OUT, encoding='utf-8')) or {}).get('items', {}) or {}
        except Exception:
            prev = {}
    sa = {r['t']: r for r in json.load(open('out/score_all.json', encoding='utf-8'))}

    packs = []
    for f in sorted(os.listdir('out')):
        if not f.endswith('_gate_pack.json'):
            continue
        d = json.load(open('out/' + f, encoding='utf-8'))
        if str(d.get('irr')) != '85':
            continue
        packs.append((f.split('_gate_pack')[0], d))

    items, undecided = {}, []
    for t, d in packs:
        fy = str((d.get('_meta') or {}).get('reportDate') or '')[:4]
        c5, why5 = conv5(t, fy)
        gm, cagr, nde = d.get('gm'), d.get('cagr'), d.get('nde')
        v, why = judge(gm, c5, cagr)
        s = sa.get(t, {})
        moat = s.get('moat')
        rec = dict(fy=fy, opm=gm, conv5=c5, conv5_note=why5, cagr=cagr,
                   nde=nde,                                   # 参考（ユーザーの基準からは外してある）
                   verdict=v, why=why,
                   moat=moat, moat_ok=(None if moat is None else moat >= MOAT_LINE),
                   omega=s.get('s'), pfail=s.get('pfail'), kills=s.get('kills'),
                   gate=('🟢投下可' if s.get('buy') else ('🔵次点' if s.get('quali') else '⛔')),
                   is_new=(t not in prev))
        # ★決めていない分岐: 3本の床は通るのに堀が関門を割る社
        if v == '合格' and moat is not None and moat < MOAT_LINE:
            rec['undecided'] = ('あなたの基準は通るが**堀 %.1f < %.0f**。'
                                '堀70を基準に入れるかは未決＝ここは人が決める' % (moat, MOAT_LINE))
            undecided.append(t)
        items[t] = rec

    order = {'合格': 0, '判定不能': 1, '不合格': 2}
    keys = sorted(items, key=lambda t: (order[items[t]['verdict']], -(items[t]['omega'] or 0)))
    show = [t for t in keys if items[t]['is_new']] if NEW_ONLY else keys

    print('■ irr=85 を**あなたの基準**で採点する（判定は変えない・読むだけ）')
    print('  基準: irr=85 ∧ 営利率≥%.2f ∧ FCF転換(5年合計比)≥%.3f ∧ 成長≥%.2f'
          '　※nde は外してある（2026-08-11の明示指示）' % (OPM, CONV, CG))
    print('  ⚠FCF転換は**歴史と同じ5年合計比**で測る（門は単年に当てている＝基準差・v9.9.129に記録）\n')
    print(f"  {'':7s}{'Ω':>6}{'堀':>6}{'営利率':>8}{'転換5年':>9}{'成長':>7}{'(nde)':>7}  あなたの判定 / 門")
    for t in show:
        r = items[t]
        f = lambda z, w=8, p=2: '—'.rjust(w) if z is None else f'{z:>{w}.{p}f}'
        mark = '★新' if r['is_new'] else '   '
        print(f"  {mark}{t:5s}{f(r['omega'],5,1)}{f(r['moat'],6,1)}{f(r['opm'])}"
              f"{f(r['conv5'],9,3)}{f(r['cagr'],7,1)}{f(r['nde'],7)}  "
              f"{r['verdict']:<5s}{('['+r['why']+']') if r['why'] else '':<34s} / {r['gate']}")
    n = {v: sum(1 for t in items if items[t]['verdict'] == v) for v in order}
    print(f"\n  合格 {n['合格']} ／ 判定不能 {n['判定不能']} ／ 不合格 {n['不合格']}　（irr=85 は {len(items)}社）")

    new = [t for t in keys if items[t]['is_new']]
    if new:
        print(f"  ★新着 {len(new)}社: {' '.join(new)}"
              + ('　（初回実行のため全社が新着扱い）' if not prev else ''))

    # あなたの基準と門の判定が食い違う社を名指しで出す（v9.9.52の作法）
    gap_in = [t for t in keys if items[t]['verdict'] == '合格' and items[t]['gate'] == '⛔']
    gap_out = [t for t in keys if items[t]['verdict'] != '合格' and items[t]['gate'] != '⛔']
    if gap_in:
        print(f"\n  ◇ あなたの基準は通るが門は⛔（{len(gap_in)}社）: {' '.join(gap_in)}")
        print("     ＝門外の明示判断が要る組。差の正体は **nde と 二本柱** "
              "（門の別枠85 は両方を要求し、あなたの基準は要求しない）")
        for t in gap_in:
            r = items[t]
            print(f"       {t:6s} 門の⛔理由: 柱fail{r['pfail']} キル{r['kills']} "
                  f"Ω{r['omega']} nde{r['nde']}")
    if gap_out:
        print(f"\n  ⚠ 門は通すのにあなたの基準では通らない（{len(gap_out)}社）: {' '.join(gap_out)}")
    if undecided:
        print(f"\n  ⚠⚠ **未決の分岐に当たった {len(undecided)}社**: {' '.join(undecided)}")
        for t in undecided:
            print('       ' + t + ' ' + items[t]['undecided'])
        print("     堀70をあなたの基準に入れるかは決まっていない（選んだ8社は全部 堀73.6+ で"
              "**一度も試されていない**）。**この道具は勝手に倒さない**＝絶対のルール1。")
    else:
        print("\n  ・未決の分岐（3本の床は通るが堀<70）に当たった社: なし")

    if AS_JSON:
        json.dump(dict(generated=str(__import__('datetime').date.today()),
                       rule=('irr=85 ∧ 営利率≥%.2f ∧ FCF転換(5年合計比)≥%.3f ∧ 成長≥%.2f'
                             '（nde は明示的に外してある）' % (OPM, CONV, CG)),
                       note=('ユーザーが2026-08-11に選んだ基準。下限3本は2018年ビンテージ irr=85 '
                             '継続組15社の最小値そのもの＝新しい定数は無い。'
                             '**判定には一切使わない**——買うかどうかは人が決め、決めたら '
                             'gate_exceptions.json へ書く。門の別枠85 との差は nde と 二本柱。'),
                       undecided_branch=('堀70 をこの基準に入れるかは未決。'
                                         'items[].undecided がある社が最初の試験になる'),
                       counts=n, new=new, gap_in=gap_in, gap_out=gap_out,
                       undecided=undecided, items=items),
                  open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\n→ {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
