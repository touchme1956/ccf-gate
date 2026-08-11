#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_scope_life.py — **irr=85 の「機構の射程」と「認定の寿命」を並べる**（2026-08-11新設）

■ なぜ要るか
  irr=85 は今日**二値**でしか持っていない——機構が在るか無いか。だが20〜30年の複利では
  次の2つが決定的で、**どちらも原本に書いてあるのに台帳に無かった**（8社とも根拠文中に%の言及ゼロを実測）:

    ① **機構の射程** … 売上の何%がその機構の裏にあるか。
       「機構が全社を覆う」と「売上の3割を覆う」は別物。TDG は『約90%が専有部品』、
       CW は3セグメントで機構文はOEM認定品について述べる、ENTG は『単一プラットフォームが3%未満』。
    ② **認定の寿命** … 一度得た認定が何年効くか＝**堀の複利期間そのもの**。
       TDG は『aftermarket ... approximately 25 to 30 years』と明示する一方、
       LRCX の認定はノード世代で更新され installed base が入れ替わりながら続く
       ——**まったく別の時間構造なのに、台帳では同じ irr=85 だった**。

■ ⚠ これは**選別の線ではない。記録である。**
  事前登録の検定（`night/irr85_criteria.py`・候補15本・偽陽性率0.678）が
  **「85の中の優劣を分ける入口の変数は無い」**と出しており、n=27 では新しい線を作れない。
  よって射程も寿命も**合否に一切使わない**——Ω・採点式・四関門・堀の関門・別枠85・配分は不変。
  出すのは表と穴の名指しだけ。**測定は直す・買付規則は変えない**（この台帳の作法）。

■ 置き場（`_meta.mech`）と、そこに置く理由
  **`_meta.evidence.irr` の中に書かない。** `night/irr85_mech_diff.py` が evidence の
  **英文引用を断片へ割って原本と照合する**ので、日本語の注記を引用に混ぜると照合の断片が汚れる。
  だから独立のキー `_meta.mech` に置く。`_meta` の型検査は kenshi/evidence/nulls/provenance
  だけを見るので、追加キーは納品検査に触らない（確認済み）。

使い方:
  python3 night/irr85_scope_life.py            表を出す
  python3 night/irr85_scope_life.py --json     out/irr85_scope_life.json を書く
  python3 night/irr85_scope_life.py --gaps     まだ測っていない社だけ
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

AS_JSON = '--json' in sys.argv[1:]
GAPS = '--gaps' in sys.argv[1:]


def rng(lo, hi, one=None, unit=''):
    """点推定・幅・片側を**取り違えないように**書き分ける。

    ⚠初版は片側しか無いとき裸の数字を出しており、**VRSK の上限70.9%が点推定に見えていた**
      （実際は「Underwriting全体が上限・下限は原本から導けない」）。
      幅と点を同じ見た目にすると、測れていないものを測れたことにしてしまう。"""
    if one is not None:
        return f'{one:g}{unit}'
    if lo is None and hi is None:
        return '—'
    if lo is not None and hi is not None:
        return (f'{lo:g}{unit}' if lo == hi else f'{lo:g}–{hi:g}{unit}')
    if hi is not None:
        return f'≤{hi:g}{unit}'
    return f'≥{lo:g}{unit}'


def main():
    sa = {r['t']: r for r in json.load(open('out/score_all.json', encoding='utf-8'))}
    rows = []
    for f in sorted(os.listdir('out')):
        if not f.endswith('_gate_pack.json'):
            continue
        d = json.load(open('out/' + f, encoding='utf-8'))
        if str(d.get('irr')) != '85':
            continue
        t = f.split('_gate_pack')[0]
        m = ((d.get('_meta') or {}).get('mech') or {})
        rows.append((t, d, m))

    have = [(t, d, m) for t, d, m in rows if m]
    gaps = [(t, d, m) for t, d, m in rows if not m]
    show = gaps if GAPS else rows

    print('■ irr=85 の「機構の射程」と「認定の寿命」')
    print('  ⚠**選別の線ではなく記録**——合否には一切使わない'
          '（事前登録の検定が「85の中の優劣を分ける入口の変数は無い」と出している）\n')
    print(f"  {'':7s}{'Ω':>6}  {'射程':>10}  {'寿命':>10}  {'検証':<9s} 機構／寿命の根拠")
    for t, d, m in show:
        s = sa.get(t, {})
        if not m:
            print(f"  {t:6s}{(s.get('s') or 0):6.1f}  {'未測定':>10}  {'未測定':>10}  {'—':<9s} ")
            continue
        sc = rng(m.get('scope_low'), m.get('scope_high'), m.get('scope_pct'), '%')
        li = rng(m.get('life_low'), m.get('life_high'), None, '年')
        v = m.get('verified') or '—'
        base = ' '.join((m.get('life_basis') or m.get('scope_basis') or '').split())[:52]
        print(f"  {t:6s}{(s.get('s') or 0):6.1f}  {sc:>10}  {li:>10}  {v:<9s} {base}")
        if m.get('scope_null_why'):
            print('         射程の点推定なし: ' + ' '.join(m['scope_null_why'].split())[:96])
        if m.get('life_null_why'):
            print('         寿命の開示なし  : ' + ' '.join(m['life_null_why'].split())[:96])

    # 穴を名指しする（v9.9.52の作法）
    nos = [t for t, d, m in rows if m and m.get('scope_pct') is None]
    nol = [t for t, d, m in rows if m and m.get('life_low') is None and m.get('life_high') is None]
    print(f"\n  測定済み {len(have)} / irr=85 {len(rows)}社"
          f"　（未着手 {len(gaps)}）")
    if gaps:
        print(f"  ・未着手: {' '.join(t for t, _, _ in gaps)}")
    if nos:
        print(f"  ・射程の**点推定**が原本から導けない（幅か片側のみ・理由つき）: {' '.join(nos)}")
    if nol:
        print(f"  ・**認定の寿命を会社が開示していない**（理由つき）: {' '.join(nol)}")

    # 読み方の助け——射程が狭い/寿命が短いほど、同じ irr=85 でも意味が違う
    meas = [(t, m) for t, d, m in rows if m and (m.get('scope_pct') is not None)]
    if meas:
        meas.sort(key=lambda kv: kv[1]['scope_pct'])
        print('\n  ── 射程の狭い順（同じ85でも、覆っている売上の割合は違う）──')
        for t, m in meas:
            print(f"   {t:6s} {m['scope_pct']:5.1f}%  " + ' '.join((m.get('scope_basis') or '').split())[:74])

    if AS_JSON:
        p = 'out/irr85_scope_life.json'
        json.dump(dict(generated=str(__import__('datetime').date.today()),
                       note=('irr=85 の機構が覆う売上の割合と、認定が効く年数。'
                             '**合否には一切使わない**——記録であって選別の線ではない。'
                             '置き場が _meta.evidence.irr でなく _meta.mech なのは、'
                             'irr85_mech_diff が evidence の英文引用を原本と照合するため'
                             '（日本語の注記を混ぜると照合の断片が汚れる）。'),
                       n_total=len(rows), n_measured=len(have),
                       no_scope=nos, no_life=nol, todo=[t for t, _, _ in gaps],
                       items={t: m for t, d, m in rows if m}),
                  open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
