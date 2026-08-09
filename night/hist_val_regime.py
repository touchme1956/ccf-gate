#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/hist_val_regime.py — 事前登録 out/hist_valuation_prereg.json の検定を
**レジーム（期間）と業種（SIC）で壊しにかかる**独立実装。

役割は3つ:
  (A) 再現: hist_val_gate_test.py の判定（c1/c2/c4）を、rows から独立に組み直して再現できるか
  (B) レジーム: 前期(asof..asof+4y) と 後期(asof+4y..end) に分けて同じ検定を回す
  (C) 業種: 高分位の社が特定SICへ偏っていないか／同一SIC2内での比較

前方リターンは in-sample の tr_cagr（配当込み・retro_returns_*.json 由来）を使い、
期間分割だけは out/_histval_cache/px の月次 adj（配当・分割調整済み）から自前で作る。
**adj どうしの比しか取らない**（水準は使わない）＝「調整済み系列×当時の申告値」を割らない。
"""
import json, gzip, os, sys, math, statistics as st
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT  = os.path.join(ROOT, 'out')
PXD  = os.path.join(OUT, '_histval_cache', 'px')

PERM = -0.15          # 恒久毀損の線（事前登録）
GRID = {'pct':[0.80,0.85,0.90,0.95], 'z':[1.0,1.5,2.0], 'spx':[0.80,0.90,0.95]}
IND = {  # 指標名 -> (kind, 分位/z)
 'pe_pct':'pct','ps_pct':'pct','pfcf_pct':'pct','adj_pe_pct':'pct',
 'pe_z':'z','ps_z':'z',
}
VINT = [2013,2015,2018]

def load(v):
    return json.load(open(os.path.join(OUT, f'hist_val_{v}.json')))

def med(xs):
    return round(st.median(xs),4) if xs else None

def stats(rows, key='tr_cagr'):
    xs=[r[key] for r in rows if r.get(key) is not None]
    if not xs: return {'n':len(rows),'n_ret':0,'median':None,'p_perm':None,'n_perm':0}
    nperm=sum(1 for x in xs if x<=PERM)
    return {'n':len(rows),'n_ret':len(xs),'median':med(xs),'mean':round(sum(xs)/len(xs),4),
            'p_perm':round(nperm/len(xs),4),'n_perm':nperm,
            'p_win':round(sum(1 for x in xs if x>=0.15)/len(xs),4)}

def measurable(r, ind, kind):
    v=r.get(ind)
    if v is None: return False
    if kind=='z':
        hm=r.get(ind.replace('_z','')+'_hist_months')
        if hm is None or hm<36: return False
    return True

def cell(pool, ind, kind, thr, key='tr_cagr'):
    m=[r for r in pool if measurable(r,ind,kind)]
    stop=[r for r in m if r[ind]>=thr]
    pas =[r for r in m if r[ind]< thr]
    base=stats(pool,key); s=stats(stop,key); p=stats(pas,key)
    out={'n_pool':len(pool),'n_measurable':len(m),
         'coverage':round(len(m)/len(pool),4) if pool else None,
         'n_stop':len(stop),'stop_rate_pool':round(len(stop)/len(pool),4) if pool else None,
         'stopped':s,'passed':p,'base':base}
    # 判定
    c1r = round(s['p_perm']/base['p_perm'],2) if (s['p_perm'] is not None and base['p_perm']) else None
    out['c1_ratio']=c1r; out['c1_numer']=s['n_perm']
    out['c1']= bool(c1r is not None and c1r>=2.0 and s['n_perm']>=5)
    out['c2']= bool(s['median'] is not None and p['median'] is not None and s['median']<=p['median'])
    out['c2_gap']= round((s['median']-p['median']),4) if (s['median'] is not None and p['median'] is not None) else None
    out['c4']= bool(out['stop_rate_pool'] is not None and out['stop_rate_pool']<=0.15)
    return out

# ---------------- (A) 再現 ----------------
def reproduce():
    gt=json.load(open(os.path.join(OUT,'hist_val_gate_test.json')))
    mine={}; mism=[]; n=0
    data={v:load(v) for v in VINT}
    pools={}
    for v in VINT:
        rows=[r for r in data[v]['rows'] if r.get('analysis_set')]
        pools[(v,'full')]=rows
        pools[(v,'quality')]=[r for r in rows if r.get('quality')]
    for res in gt['results']:
        v=res['vintage']; pl=res['pool']; ind=res['indicator']; thr=res['threshold']
        kind=IND.get(ind)
        if kind is None: continue
        c=cell(pools[(v,pl)], ind, kind, thr)
        n+=1
        ev=res['ev']; jg=res['judge']
        d={}
        for k,(a,b) in {'n_pool':(c['n_pool'],ev['n_pool']),'n_measurable':(c['n_measurable'],ev['n_measurable']),
                        'n_stop':(c['n_stop'],ev['n_stop']),
                        'stop_median':(c['stopped']['median'],ev['stopped']['median']),
                        'pass_median':(c['passed']['median'],ev['passed']['median']),
                        'stop_nperm':(c['stopped']['n_perm'],ev['stopped']['n_perm']),
                        'base_nperm':(c['base']['n_perm'],ev['base']['n_perm']),
                        'c1':(c['c1'],jg['c1']),'c2':(c['c2'],jg['c2']),'c4':(c['c4'],jg['c4'])}.items():
            if a!=b: d[k]=[a,b]
        if d: mism.append({'vintage':v,'pool':pl,'indicator':ind,'threshold':thr,'diff':d})
        mine[f'{v}|{pl}|{ind}|{thr}']=c
    return {'cells':n,'mismatches':len(mism),'diffs':mism[:20],
            'my_c1_pass':sum(1 for c in mine.values() if c['c1']),
            'my_c2_pass':sum(1 for c in mine.values() if c['c2']),
            'my_c4_pass':sum(1 for c in mine.values() if c['c4'])}, mine

if __name__=='__main__':
    rep,_=reproduce()
    print(json.dumps(rep,ensure_ascii=False,indent=1))

# ---------------- 期間分割（px キャッシュの月次 adj から自前で作る） ----------------
def _adj(t):
    p=os.path.join(PXD,t+'.json.gz')
    if not os.path.exists(p): return None
    return json.loads(gzip.open(p).read()).get('adj')

def _m2i(m):
    y,mm=m.split('-'); return int(y)*12+int(mm)

def cagr(a, m0, m1):
    """月次 adj の比だけで年率を出す（水準は使わない＝『調整済み×当時の申告値』を割らない）"""
    if not a: return None
    s=a.get(m0); e=a.get(m1)
    if not s or not e or s<=0 or e<=0: return None
    yrs=(_m2i(m1)-_m2i(m0))/12.0
    if yrs<=0: return None
    return round((e/s)**(1.0/yrs)-1.0, 4)

# 各ビンテージ: (倍率を測った月, +4y の月, AI分割の月, 終端の月)
SPLIT = {
 2018: {'m0':'2018-06','mid_rel':'2022-06','mid_ai':'2022-06','end':'2026-07'},
 2015: {'m0':'2015-06','mid_rel':'2019-06','mid_ai':'2022-06','end':'2026-07'},
 2013: {'m0':'2013-06','mid_rel':'2017-06','mid_ai':'2022-06','end':'2026-07'},
}

def attach_subperiods(v, rows):
    sp=SPLIT[v]; n_ok=0; recon=[]
    for r in rows:
        a=_adj(r['ticker'])
        r['_full_px']=cagr(a,sp['m0'],sp['end'])
        r['_early']  =cagr(a,sp['m0'],sp['mid_rel'])
        r['_late']   =cagr(a,sp['mid_rel'],sp['end'])
        r['_pre_ai'] =cagr(a,sp['m0'],sp['mid_ai'])
        r['_ai']     =cagr(a,sp['mid_ai'],sp['end'])
        if r['_full_px'] is not None:
            n_ok+=1
            if r.get('tr_cagr') is not None: recon.append(abs(r['_full_px']-r['tr_cagr']))
    return {'n_with_px':n_ok,'recon_median_abs_diff':round(st.median(recon),4) if recon else None,
            'recon_frac_within_1_5pt':round(sum(1 for x in recon if x<=0.015)/len(recon),3) if recon else None,
            'split':sp}

# ---------------- (B) レジーム検定 ----------------
def regime_cells(verbose=False):
    data={v:load(v) for v in VINT}
    diag={}; res=[]
    for v in VINT:
        rows=[r for r in data[v]['rows'] if r.get('analysis_set')]
        diag[v]=attach_subperiods(v,rows)
        pools={'quality':[r for r in rows if r.get('quality')],'full':rows}
        for pl,pool in pools.items():
            for ind,kind in IND.items():
                for thr in GRID[kind]:
                    row={'vintage':v,'pool':pl,'indicator':ind,'threshold':thr}
                    for lab,key in (('full_insample','tr_cagr'),('full_px','_full_px'),
                                    ('early','_early'),('late','_late'),
                                    ('pre_ai','_pre_ai'),('ai','_ai')):
                        c=cell(pool,ind,kind,thr,key=key)
                        row[lab]={'n_stop':c['n_stop'],'stop_rate':c['stop_rate_pool'],
                                  'stop_med':c['stopped']['median'],'pass_med':c['passed']['median'],
                                  'gap':c['c2_gap'],
                                  'base_pperm':c['base']['p_perm'],'stop_pperm':c['stopped']['p_perm'],
                                  'stop_nperm':c['stopped']['n_perm'],'c1_ratio':c['c1_ratio'],
                                  'c1':c['c1'],'c2':c['c2'],'c4':c['c4']}
                    res.append(row)
    return diag,res

# ---------------- (C) 業種（SIC） ----------------
def sic_map():
    d=json.load(open(os.path.join(OUT,'retro_sic.json')))
    m={}
    for r in d['rows']:
        if r.get('sic2'): m[r['ticker']]={'sic2':r['sic2'],'desc':r.get('sicDesc')}
    return m

def sector_view(v=2018, pool='quality', ind='pe_pct', thr=0.80, key='tr_cagr', min_n=12):
    S=sic_map(); d=load(v)
    rows=[r for r in d['rows'] if r.get('analysis_set')]
    attach_subperiods(v,rows)
    pl=[r for r in rows if r.get('quality')] if pool=='quality' else rows
    kind=IND[ind]
    m=[r for r in pl if measurable(r,ind,kind) and S.get(r['ticker'])]
    stop=[r for r in m if r[ind]>=thr]
    # 偏り
    from collections import Counter
    cs=Counter(S[r['ticker']]['sic2'] for r in stop); ca=Counter(S[r['ticker']]['sic2'] for r in m)
    bias=[]
    for s,n in ca.most_common():
        if n<min_n: continue
        k=cs.get(s,0)
        bias.append({'sic2':s,'desc':next((S[r['ticker']]['desc'] for r in m if S[r['ticker']]['sic2']==s),''),
                     'n_all':n,'n_stop':k,'stop_rate':round(k/n,3)})
    overall=len(stop)/len(m) if m else None
    # 同一SIC2内での比較（プール内比較＝業種効果を外す）
    within=[]; pooled_s=[]; pooled_p=[]
    for s,n in ca.items():
        if n<min_n: continue
        g=[r for r in m if S[r['ticker']]['sic2']==s]
        gs=[r for r in g if r[ind]>=thr]; gp=[r for r in g if r[ind]<thr]
        xs=[r[key] for r in gs if r.get(key) is not None]; xp=[r[key] for r in gp if r.get(key) is not None]
        if len(xs)<3 or len(xp)<3: continue
        within.append({'sic2':s,'n_stop':len(xs),'n_pass':len(xp),
                       'stop_med':round(st.median(xs),4),'pass_med':round(st.median(xp),4),
                       'gap':round(st.median(xs)-st.median(xp),4)})
        # 業種中央値を引いた残差でプール
        allx=[r[key] for r in g if r.get(key) is not None]; mm=st.median(allx)
        pooled_s+=[x-mm for x in xs]; pooled_p+=[x-mm for x in xp]
    res={'vintage':v,'pool':pool,'indicator':ind,'threshold':thr,'return_key':key,
         'n_measurable_with_sic':len(m),'overall_stop_rate':round(overall,4) if overall else None,
         'sector_bias':bias,'within_sic':sorted(within,key=lambda x:x['gap']),
         'within_sic_gap_positive':sum(1 for w in within if w['gap']>0),'within_sic_n':len(within),
         'pooled_demeaned':{'n_stop':len(pooled_s),'n_pass':len(pooled_p),
              'stop_med':round(st.median(pooled_s),4) if pooled_s else None,
              'pass_med':round(st.median(pooled_p),4) if pooled_p else None,
              'gap':round(st.median(pooled_s)-st.median(pooled_p),4) if pooled_s and pooled_p else None}}
    return res

# ---------------- 出力 ----------------
def build():
    rep, mine = reproduce()
    diag, cells = regime_cells()
    power={}
    for v in VINT:
        rows=[r for r in load(v)['rows'] if r.get('analysis_set')]
        for pool,pl in (('quality',[r for r in rows if r.get('quality')]),('full',rows)):
            perm=[r['ticker'] for r in pl if (r.get('tr_cagr') or 0)<=PERM]
            power[f'{v}|{pool}']={'n':len(pl),'n_perm':len(perm),
                'p_perm':round(len(perm)/len(pl),4),'cap_c4_15pct':int(len(pl)*0.15),
                'max_c1_numer':min(len(perm),int(len(pl)*0.15)),
                'c1_satisfiable':min(len(perm),int(len(pl)*0.15))>=5,'perm_tickers':perm[:12]}
    cov={}
    for v in VINT:
        rows=[r for r in load(v)['rows'] if r.get('analysis_set')]
        for pool,pl in (('quality',[r for r in rows if r.get('quality')]),('full',rows)):
            perm=[r for r in pl if (r.get('tr_cagr') or 0)<=PERM]
            for ind,kind in IND.items():
                cov[f'{v}|{pool}|{ind}']={
                 'pool':round(sum(1 for r in pl if measurable(r,ind,kind))/len(pl),4),
                 'among_perm':round(sum(1 for r in perm if measurable(r,ind,kind))/len(perm),4) if perm else None,
                 'n_perm':len(perm)}
    sec={}
    for v,pool,ind,thr in ((2018,'quality','pe_pct',0.80),(2018,'full','ps_pct',0.80),
                           (2015,'quality','pe_pct',0.80),(2018,'quality','adj_pe_pct',0.80)):
        sec[f'{v}|{pool}|{ind}|{thr}']=sector_view(v,pool,ind,thr,min_n=12)
    out={'generated':'2026-08-09','tool':'night/hist_val_regime.py',
         'lens':'レジーム（期間）と業種（SIC）で事前登録の検定を壊しにかかる独立実装',
         'reproduce_gate_test':rep,'subperiod_diag':diag,
         'power_ceiling':power,'coverage_pool_vs_event':cov,
         'regime_cells':cells,'sector':sec,
         'splits':SPLIT,
         'notes':[
          'COVID暴落窓(2020-02→2020-06)は4ヶ月＝180日未満なので年率換算しない（CLAUDE.mdの規約）。regime_cells の値は年率なので参考扱い',
          '部分期間の「年率<=-15%」は恒久毀損ではない（窓が短い）＝診断用',
          '2013/2015 の後半窓は信号が4〜9年古い＝倍率の持続性を経由した間接検定で、asof の遮断器の検定ではない']}
    json.dump(out,open(os.path.join(OUT,'hist_val_regime.json'),'w'),ensure_ascii=False,indent=1)
    return out

