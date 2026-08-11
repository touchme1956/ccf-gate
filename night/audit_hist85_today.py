#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_hist85_today.py — **歴史で irr=85 と読まれた社は、今日の門を通るか**
（2026-08-08新設 / **2026-08-11 に全ビンテージへ拡張**）

なぜ要るか（ユーザーの問い「過去リターンだしたirr85の銘柄たちは門をつうかするの？」）:
  この台帳は「irr=85 が継続組を分ける唯一の変数」を歴史で実測し、それを堀の規約の中心に置いた。
  ならば**当の社たちが今日の門で何と言われるか**は、門そのものの較正になる。

★2026-08-11 の拡張（ユーザーの問い「もっと会社なかった？」→「やって」）:
  初版は **2018年ビンテージの21社だけ**を見ていた。だが irr=85 は
  **2013(249社読解で6社) / 2015(505社で13社) / 2018(177社で21社)** の3ビンテージで読まれており、
  重複を除くと **実社数28社（のべ40件）**ある。2013年が6社しか無いのは母集団が少ないからではなく
  **読解が249社止まりだったから**（コホートは956社）——irr=85 は母集団の1〜3%しか出ない稀なラベルなので、
  読む量がそのまま検出数を決める。

★この拡張で分かったこと——**全体で見ると逆転し、層別すると戻る（シンプソンのパラドックス）**:
  2013年の6社だけを見ると「今日の irr 再検算(53社→11社)が実績をきれいに二分している」ように見える
  （85維持4社=全員+19%超 ／ 70降格2社=+6.0%と−17.2%）。**28社に広げると全体では逆転する**——
      今日も irr=85 を維持 11社 … 2018→26 の中央値 +17.2%
      今日 70以下へ降格   16社 … 同 **+21.1%**   ←一見こちらが高い
  **だが半導体連鎖で層別すると、両方の層で 85維持のほうが高い**:
      半導体連鎖  85維持 n= 1 **+43.5%** ／ 降格 n=8 +31.9%   （差 +11.5pt・n=1なので判断不能）
      非半導体    85維持 n=10 **+16.5%** ／ 降格 n=8 **+5.4%** （差 **+11.1pt**・ここが本体）
  全体で逆転するのは、**「良い層」である半導体に降格組が偏っている**から
  （降格16社中8社が半導体で中央値+31.9%・一方85維持の半導体は LRCX 1社だけ）。
  ＝**厳格化はリターンと整合する。ただしそれが見えるのは層別した後**。

  ⚠ この層別は**事前登録していない事後の切り分け**である。ただし恣意的な探索ではない——
  CLAUDE.md は以前から「2018-26 の超過はほぼAI期に出た（前期lift+0.13 / 後期+0.38）」
  「半導体を除くと2015は P=0.400 へ落ちる」と**この交絡を名指しで記録している**。
  既知の交絡を当てたのであって、都合の良い切り口を探したのではない。

出すもの:
  1. 28社の実現リターン（**2018→26 と 2013→26 の2つの窓**）と最大DD
  2. 今日のΩ・堀・irr・キル・nde・roicg と四関門の判定／落ちている社の死因
  3. **今日 irr=85 を維持した群 vs 降格した群**の対比（上の不利な数字）
  4. **半導体連鎖かどうかで層別**——「降格組の上位は半導体に偏る」という説明が本当かを SIC で検証する
  5. 2018年時点で質実証(opm≥10% ∧ 5年FCF全年黒字)を満たしていたか

  **ただし読み違えやすい。** 今日のΩは**今日の財務**で測った値であって、当時の姿ではない。
  だからこの道具が出すのは「門が当時見逃したか」ではなく、
  「**十数年走った後の同じ会社を、門は今どう見るか**」である。この二つを混同すると
  「基準の違う二つを割る」型をそのまま踏む。

使い方: python3 night/audit_hist85_today.py [--json] [--v2018]
        --v2018 … 初版と同じ「2018年ビンテージ21社だけ」の視野に戻す
"""
import glob
import json
import os
import statistics
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = '--json' in sys.argv[1:]
ONLY2018 = '--v2018' in sys.argv[1:]   # 初版と同じ視野に戻す
WACC = 8.93  # 台帳の既定（roicg<WACC の−8 の線）


def pack(t):
    for p in glob.glob('out/*_gate_pack.json'):
        if os.path.basename(p).split('_gate_pack')[0] == t:
            d = json.load(open(p, encoding='utf-8'))
            return d.get('data') or d
    return None


def cause(s, x):
    """落ちている社の死因を一つに決める（門の判定順に合わせる）"""
    if s is None:
        return '台帳に無し'
    if s.get('buy'):
        return '—'
    if s.get('quali'):
        return '席外（資格あり）'
    if s.get('moat') is None:
        return 'データ健全（堀が算出不能）'
    if (s.get('kills') or 0) > 0:
        nde = (x or {}).get('nde')
        if isinstance(nde, (int, float)) and nde > 4:
            return '財務キル（nde>4）'
        return 'キル（複利停止ほか）'
    if (s.get('s') or 0) >= 75 and (s.get('moat') or 0) >= 70:
        return 'データ健全（点検/期末後/納品検査）'
    if (s.get('moat') or 0) < 70:
        return '堀不足'
    rg = (x or {}).get('roicg')
    if isinstance(rg, (int, float)) and rg < WACC:
        return "買収代金（roicg<WACC）"
    return 'Ω不足'


def rows_of(f):
    """在庫のゆれ（list / {rows:} / {items:} / dict-of-dict）を吸収して行の list を返す"""
    d = json.load(open(f, encoding='utf-8'))
    r = d if isinstance(d, list) else (d.get('rows') or d.get('items') or [])
    if isinstance(r, dict):
        r = list(r.values())
    return [x for x in r if isinstance(x, dict)]


# irr=85 の読解の在庫。**ビンテージごとに欄名が違う**（replication は irr / 2018年版は irr18）ので
# ここで吸収する。片方だけ直すと「基準の違う二つ」を作る。
VINTAGES = [
    ('2013', 'out/retro_irr85_replication_2013_2013q.json', 'ticker', 'irr'),
    ('2015', 'out/retro_irr85_replication_2015_2015q_2015qb.json', 'ticker', 'irr'),
    ('2018', 'out/retro_moat_2018.json', 't', 'irr18'),
    ('2018', 'out/retro_moat_2018_rest.json', 't', 'irr18'),
]

# 半導体・データセンター連鎖の **4桁SIC**。**層別のためだけに使う**——採点にも判定にも一切効かない。
#   3674=半導体デバイス / 3559=半導体製造装置(Special Industry Machinery NEC) /
#   3827=光学計測 / 3672=PCB / 3825=電気計測 / 3572=コンピュータ記憶装置
# ⚠**境界は判断が入る**（STX=HDD・COHR=光通信は「半導体そのもの」ではなくAI設備投資の連鎖）。
#   だから下で**分類を1社ずつ画面に出す**——読み手が同意できない線なら自分で引き直せるように。
# ⚠ 2026-08-11 に踏んだバグの記録: 初版は**2桁の `sic2` に4桁コードを当てて**全社が非該当になり、
#   「降格17社のうち半導体は0社（0%）」という**もっともらしい0**を出した。
#   0件は測定ではなく照合失敗のことがある——**0を発見と読む前に、照合が成立しているか確かめる**。
SEMI_SIC = {'3674', '3559', '3827', '3672', '3825', '3572'}


def collect85():
    """3ビンテージの irr=85 を集めて {ticker: set(vintage)} を返す"""
    out = {}
    for v, f, key, fld in VINTAGES:
        if not os.path.exists(f):
            continue
        for r in rows_of(f):
            if r.get(fld) == 85 and r.get(key):
                out.setdefault(r[key], set()).add(v)
    return out


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def main():
    if not os.path.exists('out/score_all.json'):
        subprocess.run(['node', 'night/score_all.js'], capture_output=True, text=True)

    firms = collect85()
    if ONLY2018:
        firms = {t: v for t, v in firms.items() if '2018' in v}

    R18 = {r['ticker']: r for r in rows_of('out/retro_returns_2018.json') if r.get('ticker')}
    R13 = ({r['ticker']: r for r in rows_of('out/retro_returns_2013_all.json') if r.get('ticker')}
           if os.path.exists('out/retro_returns_2013_all.json') else {})
    sa = {r['t']: r for r in rows_of('out/score_all.json')}
    F = {r['ticker']: r for r in rows_of('out/retro_features2_2018.json') if r.get('ticker')}
    SIC = ({r['ticker']: r for r in rows_of('out/retro_sic.json') if r.get('ticker')}
           if os.path.exists('out/retro_sic.json') else {})

    rows = []
    for t in sorted(firms, key=lambda z: -(R18.get(z, {}).get('tr_cagr') or -9)):
        s, x, f = sa.get(t), pack(t), F.get(t)
        si = SIC.get(t) or {}
        sic4, sicd = si.get('sic'), si.get('sicDesc')
        rows.append(dict(
            t=t, vintages=sorted(firms[t]),
            cagr18=R18.get(t, {}).get('tr_cagr'), mdd=R18.get(t, {}).get('mdd'),
            cagr13=R13.get(t, {}).get('tr_cagr'),
            s=(s or {}).get('s'), moat=(s or {}).get('moat'), kills=(s or {}).get('kills'),
            irr=(x or {}).get('irr'), nde=(x or {}).get('nde'), roicg=(x or {}).get('roicg'),
            buy=bool((s or {}).get('buy')), quali=bool((s or {}).get('quali')),
            cause=cause(s, x), sic=sic4, sicDesc=sicd,
            semi=(sic4 in SEMI_SIC) if sic4 else None,
            q2018=(bool(f and f['opm'] >= 0.10 and f.get('fcfpos5') == 5) if f else None)))

    n = len(rows)
    scope = '2018年ビンテージ' if ONLY2018 else '3ビンテージ(2013/2015/2018)の和集合'
    print(f'■ {scope}で irr=85 と読まれた{n}社は、今日の門を通るか')
    print('  ※ **今日のΩは今日の財務**。門が当時見逃したかの検証ではない（十数年走った後の姿）\n')
    print(f"  {'':<6}{'読年':<12}{'18→26':>8}{'13→26':>8}{'DD':>6} | {'Ω':>5}{'堀':>6}{'irr':>4}"
          f"{'kill':>5}{'半':>3} {'18質':>4}  判定／死因")
    fm = lambda z: '    — ' if z is None else f'{z*100:+6.1f}%'
    for r in rows:
        j = '🟢投下可' if r['buy'] else ('🔵席外' if r['quali'] else '⛔' + r['cause'])
        print(f"  {r['t']:<6}{'/'.join(r['vintages']):<12}{fm(r['cagr18'])}{fm(r['cagr13'])}"
              f"{(r['mdd'] or 0)*100:>5.0f}% | {str(r['s']):>5}{str(r['moat']):>6}{str(r['irr']):>4}"
              f"{str(r['kills']):>5}{('半' if r['semi'] else '  '):>3} {('◎' if r['q2018'] else '—'):>4}"
              f"  {j}")

    w = [r['cagr18'] for r in rows if r['cagr18'] is not None]
    print(f"\n  実現(2018→26・8.1年・配当込み) 中央値 {med(w)*100:.1f}%/年 ／ "
          f"年15%+ {sum(1 for v in w if v >= .15)}/{len(w)}社 ／ 元本割れ {sum(1 for v in w if v < 0)}社")
    allw = [r['tr_cagr'] for r in rows_of('out/retro_returns_2018.json') if r.get('tr_cagr') is not None]
    print(f"  （比較）2018コホート全{len(allw)}社の中央値 {med(allw)*100:.1f}%/年"
          f"　→ この群は明らかに上側に寄っている＝**ラベル自体は当たっている**")
    print(f"  **今日の門: 投下可 {sum(1 for r in rows if r['buy'])}社 ／ 席外 "
          f"{sum(1 for r in rows if r['quali'] and not r['buy'])}社 ／ 不通過 "
          f"{sum(1 for r in rows if not r['quali'])}社**")

    # ── ★門にとって不利な数字。**必ず出す**（都合の悪い測定こそ在庫に残す）────────
    keep = [r for r in rows if r['irr'] == 85]
    drop = [r for r in rows if r['irr'] is not None and r['irr'] < 85]
    print(f"\n■ ★今日の irr 再検算(53社→11社)は、歴史のリターンで裏付けられるか")
    print(f"   → **全体では逆転する。層別すると戻る（シンプソンのパラドックス）**")
    print(f"   今日も irr=85 を維持 {len(keep):2d}社: 2018→26 中央値 "
          f"{(med([r['cagr18'] for r in keep]) or 0)*100:+.1f}%  ({' '.join(r['t'] for r in keep)})")
    print(f"   今日 70以下へ降格   {len(drop):2d}社: 同           "
          f"{(med([r['cagr18'] for r in drop]) or 0)*100:+.1f}%  ← **こちらのほうが高い**")
    print(f"   2013年の6社だけを見ると綺麗に分かれて見える（85維持4社=全員+19%超／降格2社=+6.0%と−17.2%）")
    print(f"   ＝**n=6 の絵を一般化してはいけない**。この節はその実例として残す")
    print(f"   ただし**この逆転はセクター交絡**——次の層別を見よ（両方の層では85維持が高い）")

    # ── 半導体で層別（「降格組は半導体に偏る」という説明の検証）──────────────
    print('\n■ 「降格組の上位は半導体連鎖に偏る」は本当か（SICで層別・採点には不使用）')
    for lbl, want in (('半導体連鎖', True), ('非半導体', False)):
        k = [r for r in keep if r['semi'] is want]
        d = [r for r in drop if r['semi'] is want]
        mk, md = med([r['cagr18'] for r in k]), med([r['cagr18'] for r in d])
        print(f"   {lbl:<8} 85維持 {len(k):2d}社 中央値 {('  — ' if mk is None else f'{mk*100:+.1f}%')}"
              f" ／ 降格 {len(d):2d}社 中央値 {('  — ' if md is None else f'{md*100:+.1f}%')}")
    nsemi = sum(1 for r in drop if r['semi'])
    print(f"   降格{len(drop)}社のうち半導体連鎖は {nsemi}社（{nsemi/max(len(drop),1)*100:.0f}%）")
    print('   分類の内訳（**境界は判断が入るので1社ずつ出す**・SICは4桁）:')
    for r in sorted(rows, key=lambda z: -(z['cagr18'] or -9)):
        if r['sic'] is None:
            print(f"     {r['t']:<6}{'SIC不明':<8}—"); continue
        print(f"     {r['t']:<6}{r['sic']:<6}{'半導体連鎖' if r['semi'] else '        '}  {r['sicDesc']}")

    from collections import Counter
    c = Counter(r['cause'] for r in rows if not r['quali'])
    print('\n  死因の内訳: ' + ' ／ '.join(f'{k} {v}社' for k, v in c.most_common()))

    print('\n■ 読み方')
    print('  ・**irr=85 は「買ってよい」を意味しない。** 堀の関門を通っても、財務キル・買収代金・')
    print('    データ健全が独立に止める。この群の中にも DD−96%(CMTL)・−74%(IPGP)・−77%(ROG) が実在する')
    print('  ・**★全体の逆転を結論にしてはいけない。** 層別すると両方の層で 85維持が高い')
    print('    （非半導体 +16.5% vs +5.4%）。逆転の正体は**降格組が「良い層」である半導体に偏る**こと')
    print('    ——2018→26 は半導体・AI相場に極端に有利な単一の窓で、CLAUDE.md が以前から')
    print('    「超過はほぼAI期に出た」「半導体を除くと2015は P=0.400 へ落ちる」と記録している交絡')
    print('  ・**それでも「厳格化が正しい」と強く言ってはいけない**——')
    print('    (a) 層別は**事前登録していない事後の切り分け**（既知の交絡を当てただけだが順序は事後）')
    print('    (b) 半導体層は n=1 vs 8 で判断不能。非半導体層も n=10 vs 8 と薄い')
    print('    (c) 降格の理由は「機構が弱い」ではなく**「自社取得の認証／向きが逆／記述が無い」＝')
    print('        機構が存在しない**という質的判定で、そもそもリターンで検証する筋の話ではない')
    print('  ・**門が当時何を言ったかはこの道具では判らない**（定性採点を当時の原本でやり直す')
    print('    必要がある）。機械の背骨だけなら retro_cohort.py／backtest_core.py の領分')

    if AS_JSON:
        p = 'out/audit_hist85_today.json'
        json.dump(dict(generated='2026-08-11', scope=scope, n=n,
                       note=('3ビンテージの和集合。**今日のΩは今日の財務**で当時の姿ではない。'
                             'keep_vs_drop は門にとって不利な数字だが意図的に在庫へ残している'),
                       keep_vs_drop=dict(
                           keep_n=len(keep), keep_med=med([r['cagr18'] for r in keep]),
                           drop_n=len(drop), drop_med=med([r['cagr18'] for r in drop])),
                       rows=rows), open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
