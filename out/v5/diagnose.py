# -*- coding: utf-8 -*-
"""門の内部を実測する診断。index.htmlのエンジン式をそのまま再現して三本柱を出す。
 moatIdx = 幾何平均([dom,irr,rep,dur], [.30,.30,.25,.15])  各因子96上限
 pm(堀の柱) = 0.70*moatIdx + 0.30*粗利確認   ※粗利確認は80と仮定
 sustain = 幾何平均([pm,pr,pt], 実装=[0.38,0.42,0.20] / 解説=[0.42,0.33,0.25])"""
import math
gm=lambda v,w: math.exp(sum(wi*math.log(vi) for vi,wi in zip(v,w)))
cap=lambda v: min(96,v)
moat=lambda d,i,r,u: gm([cap(d),cap(i),cap(r),cap(u)],[.30,.30,.25,.15])
ROWS=[("eWeLL(5038)",78.9,70,50,60,75),("V",79.5,70,50,60,85),("WDFC",65.0,70,50,60,55),
 ("MSFT",74.8,70,50,80,75),("KLAC",80.3,70,50,80,100),("NVDA",75.0,85,50,80,75),
 ("東京エレクトロン(8035)",76.9,85,50,80,100),("ASML",82.3,85,85,100,100)]
print(f"{'銘柄':<22}{'総合':>6}{'moatIdx':>9}{'pm(堀の柱)':>11}  解説の足切り70")
for nm,s,d,i,r,u in ROWS:
    m=moat(d,i,r,u); pm=0.70*m+0.30*80
    print(f"{nm:<22}{s:6.1f}{m:9.1f}{pm:11.1f}  {'○' if pm>=70 else '× 見送りのはず'}")
