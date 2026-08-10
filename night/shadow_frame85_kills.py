#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_frame85_kills.py — **別枠85 が nde 以外のキルを免除している穴**の影の計測（2026-08-09新設）

発端: 2026-08-09 に TDG の nde を 3.9 にして全369社を回したら、
  **Ω42.4・tier=失格・出口=s1・キル1件（債務超過）のまま 🟢投下可に入り、KLAC を押し出した**。
  ccfIrr85Frame は `nde>4` だけを明示的に適用し、**他のキル**——
  債務超過 / Altman Z''<1.1（倒産圏）/ ROIC≤WACC（価値破壊）/ ROIIC<WACC（複利停止）/
  堀の明確な減衰 / 期限型独占——を**一つも見ていない**。
  v9.9.122 が「二本柱の陥落は免除しない」を足したのと**同じ形の穴**。

案:
  A 現行
  B **キルが1件でもあれば別枠を通さない**（`r.kills===0` を条件に足す）

作法: index.html を退避 → 差し替え → score_all → **必ず元へ戻す**。正本の採点は変えない。
  さらに「TDG の nde が線を割ったら」の**注入検査**も両案で回す（今日は誰も動かなくても、
  線が動いた瞬間に効くかどうかが、この穴の本当の意味だから）。

使い方: python3 night/shadow_frame85_kills.py
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
HTML = 'index.html'
BAK = HTML + '.shadow_bak'
SCORE = 'out/score_all.json'
SCORE_BAK = SCORE + '.shadow_bak'
TDG = 'out/TDG_gate_pack.json'
TDG_BAK = TDG + '.shadow_bak'

ANCHOR = ("  const pf=(r&&typeof r.pfail==='number')?r.pfail:null;")
PATCH = ("  const _kl=(r&&typeof r.kills==='number')?r.kills:null;\n"
         "  if(_kl===null)ng.push('キルが未評価（別枠は特権ゆえ与えない）');\n"
         "  else if(_kl>0)ng.push(`キル${_kl}件（別枠でも免除しない）`);\n"
         + ANCHOR)


def run():
    subprocess.run(['node', 'night/score_all.js'], capture_output=True, text=True)
    rows = json.load(open(SCORE, encoding='utf-8'))
    return ([r['t'] for r in rows if r.get('buy')],
            [r['t'] for r in rows if r.get('quali') and not r.get('buy')])


def main():
    src = open(HTML, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1, '錨が見つからない'
    tdg_src = open(TDG, encoding='utf-8').read()
    shutil.copy2(HTML, BAK)
    shutil.copy2(TDG, TDG_BAK)
    if os.path.exists(SCORE):
        shutil.copy2(SCORE, SCORE_BAK)
    out = {}
    try:
        for pat, plab in ((None, 'A 現行'), (PATCH, 'B キルが1件でもあれば別枠を通さない')):
            open(HTML, 'w', encoding='utf-8').write(src if pat is None else src.replace(ANCHOR, pat, 1))
            for inj, ilab in ((None, '今日のまま'), (3.9, 'TDGのndeを3.9に注入')):
                x = json.loads(tdg_src)
                d = x.get('data') or x
                if inj is not None:
                    d['nde'] = inj
                json.dump(x, open(TDG, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                buy, nxt = run()
                out[f'{plab} / {ilab}'] = dict(buy=buy, next=nxt, tdg=('TDG' in buy))
                print(f'■ {plab}　{ilab}')
                print(f'   投下可 {len(buy)}社: {" ".join(buy)}')
                print(f'   TDGは買付に{"**入る**" if "TDG" in buy else "入らない"}')
    finally:
        shutil.move(BAK, HTML)
        shutil.move(TDG_BAK, TDG)
        if os.path.exists(SCORE_BAK):
            shutil.move(SCORE_BAK, SCORE)
        assert open(HTML, encoding='utf-8').read() == src
        assert open(TDG, encoding='utf-8').read() == tdg_src
        run()
        print('\n（index.html・TDGのパック・score_all.json を復元した）')
    json.dump({'generated': '2026-08-09', 'cases': out},
              open('out/shadow_frame85_kills.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('→ out/shadow_frame85_kills.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
