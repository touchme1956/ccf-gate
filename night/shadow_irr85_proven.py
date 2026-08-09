#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_irr85_proven.py — **irr=85 の特別扱いを「歴史的に複利中央値が高い社」に限ると誰がどう動くか**
（2026-08-09新設・ユーザー指示「irr85は歴史的にみて今後も複利中央値が高いと見込めるものだけ
特別にポートフォリオにいれたい」の影の計測）

門が irr=85 に与えている特別扱いは**二つ**——
  (1) **別枠85**（ccfIrr85Frame・v9.9.119/122）＝Ω75+ を免除して買付の土俵に上げる
  (2) **席の優先**（ccfAllocTop の mech()・v9.9.100）＝上位10席で irr=85 を先に置く

絞る軸は `night/irr85_mech_test.py` の実測で**一つに決まった**——
  ・軸A **機構の型** は使えない: n=2〜8 で、しかも **CW がまったく同じ引用で
    2013読解=D認定業者名簿 / 2015読解=C第三者が用途を認定 に割れた**＝ラベルが再現しない
    （irr の刻み 85 自体は一度も揺れていないのと対照的）。参考として P3 で測るだけにする
  ・軸B **その社自身の実現複利**（今日の14社のうち11社は歴史のコホート本人）＝
    読み手に依存しない算術。**実績中央値が年15%+ は9社、下回るのは HXL 7.3% と ST −0.2%**

案:
  P1 厳格 —— 実績中央値≥15% の社にだけ特権（**実績が追えない社にも与えない**＝
             「特権は測れないときに与えない」v9.9.122 の向き）
  P2 緩和 —— 実績が15%未満と**判っている**社からだけ特権を外す（実績なしは据置）
  P3 参考 —— 機構B設計組込を外す（ラベル不安定ゆえ規則にはできない。数字だけ見る）

作法（この repo の型）: index.html を退避 → 差し替え → score_all → **必ず元へ戻す**。正本の採点は変えない。

使い方: python3 night/shadow_irr85_proven.py [--only P1]
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'index.html')
BAK = HTML + '.shadow_bak'
SCORE = os.path.join(ROOT, 'out', 'score_all.json')
SCORE_BAK = SCORE + '.shadow_bak'

# 実績（night/irr85_mech_test.py の表3・3つの窓の中央値）
PROVEN = ['LRCX', 'CW', 'ENTG', 'MKSI', 'TDG', 'RBC', 'NOVT', 'WST', 'BWXT']   # 中央値 ≥15%
FAILED = ['HXL', 'ST']                                                          # 中央値 <15%
MECH_B = ['ST']                                                                 # 今日の私のラベル（不安定）

MECH_OLD = "  const mech=c=>(c&&+c.irr===85)?0:1;      // 0=機構が実証された型（先に席へ）"
FRAME_OLD = "  if(irr!==85)return {pass:false,why:null};"
# ⚠パックのティッカー欄は `nm`（`t` ではない）。初版は d.t を読んで **全社の別枠が落ちた**
#   ——「実績のある RBC が落ちる」というもっともらしい誤りが出た。錨は必ず実データで検算する
DK = ("  const _dk=x=>String((x&&(x.nm||x.t))||'').trim().split(/[\\s_]/)[0].toUpperCase();\n")


def _set(name, arr):
    return "const %s=new Set(%s);" % (name, json.dumps(arr))


def case_src(kind):
    """(mech行の置換, frame行の置換) を返す"""
    if kind == 'P1':
        s = _set('_PV', PROVEN)
        m = ("  " + s + "\n  const _k=c=>String((c&&c.t)||'').trim().split(/[\\s_]/)[0].toUpperCase();\n"
             "  const mech=c=>((c&&+c.irr===85)&&_PV.has(_k(c)))?0:1;")
        f = ("  if(irr!==85)return {pass:false,why:null};\n" + DK +
             "  " + s + "\n"
             "  if(!_PV.has(_dk(d)))"
             "return {pass:false,why:'実績が年15%+と確認できない（P1厳格）'};")
        return m, f
    drop = FAILED if kind == 'P2' else MECH_B
    s = _set('_NG', drop)
    m = ("  " + s + "\n  const _k=c=>String((c&&c.t)||'').trim().split(/[\\s_]/)[0].toUpperCase();\n"
         "  const mech=c=>((c&&+c.irr===85)&&!_NG.has(_k(c)))?0:1;")
    f = ("  if(irr!==85)return {pass:false,why:null};\n" + DK +
         "  " + s + "\n"
         "  if(_NG.has(_dk(d)))"
         "return {pass:false,why:'歴史の実績が年15%未満'};")
    return m, f


def run():
    subprocess.run(['node', os.path.join(ROOT, 'night', 'score_all.js')],
                   cwd=ROOT, capture_output=True, text=True)
    rows = json.load(open(SCORE, encoding='utf-8'))
    buy = [r['t'] for r in rows if r.get('buy')]
    nxt = [r['t'] for r in rows if r.get('quali') and not r.get('buy')]
    return buy, nxt


def main():
    only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None
    src0 = open(HTML, encoding='utf-8').read()
    assert MECH_OLD in src0, '席の優先の錨が見つからない'
    assert FRAME_OLD in src0, '別枠の錨が見つからない'
    shutil.copy2(HTML, BAK)
    if os.path.exists(SCORE):
        shutil.copy2(SCORE, SCORE_BAK)
    out = {}
    try:
        b0, n0 = run()
        print(f'■ P0 現行  投下可{len(b0)}社: {" ".join(b0)}')
        print(f'          🔵次点: {" ".join(n0[:8])}')
        out['P0'] = dict(buy=b0, next=n0)
        for kind, lab in (('P1', '厳格＝実績中央値≥15%の社にだけ特権（実績なしも特権なし）'),
                          ('P2', '緩和＝実績が15%未満と判っている社からだけ特権を外す'),
                          ('P3', '参考＝機構B設計組込を外す（ラベル不安定・規則にはできない）')):
            if only and kind != only:
                continue
            m, f = case_src(kind)
            open(HTML, 'w', encoding='utf-8').write(
                src0.replace(MECH_OLD, m).replace(FRAME_OLD, f))
            b, n = run()
            io = [t for t in b if t not in b0], [t for t in b0 if t not in b]
            print(f'\n■ {kind} {lab}')
            print(f'  投下可{len(b)}社: {" ".join(b)}')
            print(f'  出 {" ".join(io[1]) or "—"} ／ 入 {" ".join(io[0]) or "—"}')
            out[kind] = dict(label=lab, buy=b, next=n, dropped=io[1], added=io[0])
    finally:
        shutil.move(BAK, HTML)
        if os.path.exists(SCORE_BAK):
            shutil.move(SCORE_BAK, SCORE)
        assert open(HTML, encoding='utf-8').read() == src0, '復元に失敗'
        print('\n（index.html と out/score_all.json を復元した）')
    json.dump({'generated': '2026-08-09', 'proven': PROVEN, 'failed': FAILED, 'cases': out},
              open(os.path.join(ROOT, 'out', 'shadow_irr85_proven.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('→ out/shadow_irr85_proven.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
