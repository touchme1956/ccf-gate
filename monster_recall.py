#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""monster_recall.py — 教師データ(monster_set.json)への点in時 recall テスト。
門が歴代の高複利怪物を「点火前」に捕まえたかを、先読み無しで測る検証係。
門のコード(kaibutsu_scan/署名式/点火式)は一切変えず、kaibutsu_backtest の関数を流用する読み取り測定。
結果(2026-07): A型recall 82% / B型100% / C型64% / D型50%。A/B(門の本業)は高recall=門は較正済み。
C/D低recallは設計通り(拍子木は点火せず門Ωの持ち場)。A型の取り逃しCELH/SHOPはSECデータ窓の限界。
使い方: python monster_recall.py  (SEC重・数分)。SEC XBRLは2009年以降=それ以前の点火は検出不能(recallの下限)。
"""
import json, os, sys
from datetime import date
sys.path.insert(0, "/home/user/ccf-gate")
import kaibutsu_backtest as kb   # companyfacts/cik_map/quarterly_series/prior_q/TAGS_REV/OP

def all_ignitions(facts):
    """点in時に検出される全点火(type,end)を返す。3年窓の有無は問わない(最近の点火も拾う)。"""
    rev = kb.quarterly_series(facts, kb.TAGS_REV)
    op  = kb.quarterly_series(facts, kb.TAGS_OP)
    ends = sorted(rev)
    if len(ends) < 12: return [], (ends[0][:7] if ends else None), (ends[-1][:7] if ends else None)
    yoy={}; dopm={}
    for e in ends:
        p = kb.prior_q(ends, e)
        if p and rev.get(p): yoy[e]=(rev[e]/rev[p]-1)*100
        if p and op.get(e) is not None and op.get(p) is not None and rev.get(p) and rev.get(e):
            dopm[e]=op[e]/rev[e]*100 - op[p]/rev[p]*100
    ys=[e for e in ends if e in yoy]
    ev=[]
    for i,e in enumerate(ys):
        accel=0
        for j in range(i,0,-1):
            if yoy[ys[j]]>yoy[ys[j-1]]: accel+=1
            else: break
        bs=0
        for j in range(i,-1,-1):
            if dopm.get(ys[j]) is not None and dopm[ys[j]]>=2: bs+=1
            else: break
        y=yoy[e]; dp=dopm.get(e)
        if accel>=2 and y>=25 and (dp is not None and dp>=2): ev.append(("A",e))
        elif bs>=2 and y>=10: ev.append(("B",e))
    return ev, (ends[0][:7]), (ends[-1][:7])

M=json.load(open("/home/user/ccf-gate/monster_set.json"))
cmap=kb.cik_map()
print("=== 教師データ点in時 recall (門は点火前に怪物を捕まえたか) ===")
summ={}
for typ,ticks in M["types"].items():
    caught=0; testable=0; rows=[]
    for t in ticks:
        cik=cmap.get(t.upper())
        if not cik:
            rows.append(f"  {t:<6} CIK不明"); continue
        try:
            facts=kb.companyfacts(cik)
            ev, first_q, last_q = all_ignitions(facts)
        except Exception as e:
            rows.append(f"  {t:<6} 取得失敗"); continue
        testable+=1
        if ev:
            caught+=1
            first=ev[0]
            types="".join(sorted(set(x[0] for x in ev)))
            rows.append(f"  {t:<6} ✅点火[{types}] 最早 {first[0]}:{first[1][:7]} (データ {first_q}〜{last_q}・計{len(ev)}回)")
        else:
            rows.append(f"  {t:<6} ✗点火なし (データ {first_q}〜{last_q})")
    summ[typ]=(len(ticks),testable,caught)
    print(f"\n【{typ}】 recall {caught}/{testable}(検出可能中)")
    print("\n".join(rows))
print("\n=== 型別 recall サマリー ===")
for typ,(n,te,c) in summ.items():
    print(f"{typ:<12} 教師{n} / 検出可能{te} / 点火検出{c}  = recall {100*c/te:.0f}%" if te else f"{typ}: n/a")
print("\n※SEC XBRLは概ね2009年以降。それ以前に点火した怪物(MNST90s/AMZN1997/DPZ2004等)は原理的に検出不能=recallの下限。")
