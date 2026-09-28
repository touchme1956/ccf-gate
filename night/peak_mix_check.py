#!/usr/bin/env python3
"""night/peak_mix_check.py — 『比重が過去最大の業種』の結果を受けて、ETF側の配合を変える必要があるかを測る（読むだけ・配分は変えない）
2026-09-28 ユーザー「この結果を受けてポートフォリオに変更する必要があるか検証して」。
二つの物差しを並べる: (1) 歴史の毎月積立（QQQ/SMH/SPY・2000-06→・天井直後に始めた窓も） (2) 業種の基礎率（out/industry_peak.json）
から見た偏りの代金＝（記録の二業種の割合−市場の割合）×（記録の業種と残りの差）。出力 out/peak_mix_check.json
"""
import sys, os, json, time, numpy as np, statistics as S
BASE=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0,os.path.join(BASE,'night')); os.chdir(BASE)
import etf_theme as T
A=('QQQ','SMH','SPY')
px={t:T.fetch(t) for t in A}
c=sorted(set.intersection(*[set(px[t]) for t in A])); end=max(m for m in c if m<time.strftime('%Y-%m')); c=[m for m in c if m<=end]
P={t:np.array([px[t][m] for m in c]) for t in A}; cu={t:np.concatenate([[0],np.cumsum(1/P[t])]) for t in A}
def add(k,n):
    y,m=int(k[:4]),int(k[5:]);m+=n;y+=(m-1)//12;m=(m-1)%12+1;return f'{y:04d}-{m:02d}'
def mult(w,i,j): return sum(w[t]*(cu[t][j]-cu[t][i])*P[t][j] for t in A)/(j-i)
def win(Y,lo=None,hi=None):
    o=[]
    for i,a in enumerate(c):
        b=add(a,Y*12)
        if b>end: break
        if (lo is None or a>=lo) and (hi is None or a<=hi): o.append((i,c.index(b)))
    return o
# ETF側80%の中身（比）。個別20%は共通なので比較から外す
cand={'A 今 iFree60/SMH20':{'QQQ':.75,'SMH':.25,'SPY':0},
 'B iFree70/SMH10':{'QQQ':.875,'SMH':.125,'SPY':0},
 'C iFree80のみ':{'QQQ':1,'SMH':0,'SPY':0},
 'D iFree50/SMH10/S&P20':{'QQQ':.625,'SMH':.125,'SPY':.25},
 'E iFree40/SMH10/S&P30':{'QQQ':.5,'SMH':.125,'SPY':.375},
 'F S&P500のみ':{'QQQ':0,'SMH':0,'SPY':1}}
res={}
for k,w in cand.items():
    r={}
    for Y in (10,15,20):
        v=sorted(mult(w,i,j) for i,j in win(Y)); r[f'{Y}年中央']=round(v[len(v)//2],2); r[f'{Y}年最悪']=round(v[0],2)
    # 記録の山の直後（2000-06〜2001-12開始）＝今と似た出発点
    for Y in (10,20):
        v=[mult(w,i,j) for i,j in win(Y,'2000-06','2001-12')]
        r[f'天井直後開始{Y}年(中央)']=round(S.median(v),2) if v else None
    res[k]=r
X=json.load(open('out/industry_exposure.json')); K=json.load(open('out/industry_peak.json'))
ea=X['ETF単体の記録の二業種(%)']; mk=X['米国市場全体(French・2025年末)']['二つの合計(%)']
castle=4.0   # 個別20%のうち記録の二業種は MSFT（4%）だけ（目標の姿・等分）
med=K['主_閾値5%・次の10年・山ごと']['中央値(%/年)']; spread=-med*(1+mk/(100-mk))   # 記録の業種 − 残りの業種（市場との差が med なら）
for k,w in cand.items():
    e=castle+80*(w['QQQ']*ea['QQQ']['French寄せ']+w['SMH']*ea['SMH']['French寄せ']+w['SPY']*mk)/100
    res[k]['記録の二業種(%)']=round(e,1); res[k]['基礎率どおりなら市場との差(%/年)']=round(-(e-mk)/100*spread,2)
for k,r in res.items():
    for kk,v in r.items(): r[kk]=float(v) if v is not None else None
print(c[0],end)
for k,r in res.items(): print(k,r)
json.dump({'generated':time.strftime('%Y-%m-%d'),'窓':f'{c[0]}→{end}','注':'倍率＝毎月同額積立の最後の評価額÷投下額。個別20%は全案共通なので倍率の比較から外した。S&P500 の業種の割合は米国株全体で代用','案':res},open('out/peak_mix_check.json','w'),ensure_ascii=False,indent=1)
