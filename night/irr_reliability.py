#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr_reliability.py — **刻みの信頼性は刻みごとにどう違うか**（事前登録 Q3）

既記録は「両ビンテージで読まれた147社の一致率 90.5%・**85は一度も揺れていない**」だが、
**刻み別（50の一致率／70の一致率）は一度も測られていない**。今日の台帳は
70 が213社・50 が123社なので、**誤分類の期待数はこの刻み別の一致率でしか出せない**。

【この測定の限界（先に書く）】
  ・読み手はいずれもLLM。人の審査官の再現性ではない
  ・2013系と2015系は**別の年の原本**を読んでいる（同じ紙の再読ではない）＝
    不一致には「読み手のぶれ」と「会社が実際に変わった」が混ざる。**分離できない**
  ・したがって出るのは**一致率の下限**であって、読み手のぶれだけの一致率ではない

使い方: python3 night/irr_reliability.py [--json]
出力: out/irr_reliability.json
"""
import json, os, sys, statistics, collections
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(ROOT)
sys.path.insert(0,'night')
from irr_substructure import load, READ            # **二重実装を作らない**（同じ読み込みを使う）

def main():
    rec,_=load()
    by={}
    for (v,t),d in rec.items(): by.setdefault(t,{})[v]=d
    both={t:g for t,g in by.items() if '2013' in g and '2015' in g}
    out={'generated':'2026-08-12','tool':'night/irr_reliability.py',
         'prereg':'out/irr_precision_prereg.json Q3',
         'sources':list(READ.keys()),
         '母集団':{'両ビンテージで読まれた社':len(both),'全社':len(by)}}

    # ── 混同行列（2013 → 2015）───────────────────────────────
    cm=collections.Counter((g['2013']['irr'],g['2015']['irr']) for g in both.values())
    steps=sorted({k for kk in cm for k in kk})
    out['混同行列(行=2013 / 列=2015)']={str(a):{str(b):cm.get((a,b),0) for b in steps} for a in steps}
    agree=sum(v for (a,b),v in cm.items() if a==b)
    out['全体一致率']={'一致':agree,'n':len(both),'率':round(agree/len(both),3) if both else None}

    # ── 刻み別（**n を必ず添える**。全体一致率は 50 の大量サンプルに支配される）──
    per={}
    for a in steps:
        n=sum(v for (x,_),v in cm.items() if x==a)
        ag=cm.get((a,a),0)
        moved=collections.Counter({f'{a}→{b}':v for (x,b),v in cm.items() if x==a and b!=a})
        per[str(a)]={'n(2013でこの刻み)':n,'2015でも同じ':ag,
                     '一致率':round(ag/n,3) if n else None,'不一致の行き先':dict(moved)}
    out['刻み別']=per

    # ── 今日の台帳への翻訳（**点推定を断定せず上限と下限で挟む**）──────────
    import glob
    today=collections.Counter()
    for f in glob.glob('out/*_gate_pack.json'):
        d=json.load(open(f,encoding='utf-8')); v=d.get('irr')
        today[str(v) if v not in (None,'') else '未測定']+=1
    tr={}
    for k,n in today.items():
        p=per.get(k,{}).get('一致率')
        if p is None: continue
        # 二人の独立な読み手の一致率 p から、単一の読み手の正解率 a を挟む:
        #   下限: 二人が同じ間違いをしない（独立に誤る）と置くと p ≈ a^2 + (誤りが一致する分) >= a^2 → a <= sqrt(p) は上限
        #   上限: 片方が常に正しいと置けば a >= p
        # ＝ **a は [p, sqrt(p)] の間**。どちらかに断定しない
        lo,hi=p,round(p**0.5,3)
        tr[k]={'今日の社数':n,'一致率':p,'単一の読み手の正解率の帯':[round(lo,3),hi],
               '誤分類の期待数の帯':[round(n*(1-hi),1),round(n*(1-lo),1)]}
    out['今日の台帳への翻訳']=tr
    out['翻訳の仮定']=('一致率 p から単一の正解率 a を [p, √p] で挟む。下限は「片方が常に正しい」、'
                      '上限は「二人が独立に誤る」置き方。**どちらが正しいかは決めない**')

    # ── 引用の厚さと一致率の関係（「根拠が厚い社ほど揺れないか」）────────────
    q=[(min(g['2013']['qlen'],g['2015']['qlen']), g['2013']['irr']==g['2015']['irr']) for g in both.values()]
    if q:
        med=statistics.median([x[0] for x in q])
        thick=[a for l,a in q if l> med]; thin=[a for l,a in q if l<=med]
        out['引用の厚さと一致率']={'厚い側':{'n':len(thick),'一致率':round(sum(thick)/len(thick),3) if thick else None},
                                  '薄い側':{'n':len(thin),'一致率':round(sum(thin)/len(thin),3) if thin else None},
                                  '中央値の字数':int(med),
                                  '注':'⚠ Q1 の実測では**引用長は継続の予言子として lift −0.086（逆向き）**。'
                                       '厚さが効くとしても「揺れにくさ」であって「当たりやすさ」ではない'}
    # ── ★是正策の直接の検定: 「機構の型を名指しできた社は揺れないか」───────────
    #   今日の台帳は mech（機構の型）を **85 にしか記録していない**。70 にも要求すべきかは、
    #   「名指しできた社の一致率が高いか」で決まる。**提案する前に測る。**
    seg={}
    for lab,f in (('機構の型を名指しできた', lambda d: d.get('mech') not in (None,'なし')),
                  ('時制=完了形',            lambda d: d.get('tense')=='完了形'),
                  ('moat5>=4',              lambda d: (d.get('moat5') or 0)>=4)):
        for scope,pick in (('irr=70 に限る', lambda g: g['2013']['irr']==70), ('全刻み', lambda g: True)):
            sub=[g for g in both.values() if pick(g)]
            hit=[g for g in sub if f(g['2013'])]; no=[g for g in sub if not f(g['2013'])]
            ah=sum(1 for g in hit if g['2013']['irr']==g['2015']['irr'])
            an=sum(1 for g in no  if g['2013']['irr']==g['2015']['irr'])
            seg[f'{lab} / {scope}']={
                '名指しあり':{'n':len(hit),'一致率':round(ah/len(hit),3) if hit else None},
                '名指しなし':{'n':len(no), '一致率':round(an/len(no),3) if no else None},
                '差pt':(round((ah/len(hit)-an/len(no))*100,1) if hit and no else None)}
    out['是正策の検定: 機構の型を名指しできた社は揺れないか']=seg

    # 不一致10件の内訳（何が揺れたのか実物を見る）
    dis=[{'ticker':t,'2013':g['2013']['irr'],'2015':g['2015']['irr'],
          'mech2013':g['2013'].get('mech'),'tense2013':g['2013'].get('tense'),
          'qlen2013':g['2013']['qlen'],'qlen2015':g['2015']['qlen']}
         for t,g in both.items() if g['2013']['irr']!=g['2015']['irr']]
    out['不一致の実物']=sorted(dis,key=lambda x:(x['2013'],x['2015']))

    out['この測定で言えないこと']=[
        '不一致に「読み手のぶれ」と「会社が実際に変わった」が混ざる（別の年の原本を読んでいる）＝分離できない',
        '読み手はLLM。人の審査官の再現性ではない',
        '母集団は同じ956ティッカーで out-of-sample はゼロ']
    json.dump(out,open('out/irr_reliability.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
    if '--json' in sys.argv: print(json.dumps(out,ensure_ascii=False,indent=1)); return 0
    print(f"■ 両ビンテージで読まれた社: {len(both)}社　全体一致率 {out['全体一致率']['率']}")
    print('\n■ 刻み別の一致率（**これが今まで測られていなかった**）')
    for k,v in sorted(per.items(),key=lambda z:-int(z[0])):
        print(f"  irr={k:<4} n={v['n(2013でこの刻み)']:>3}  一致率 {v['一致率']}"
              f"　不一致の行き先: {v['不一致の行き先'] or '—'}")
    print('\n■ 今日の台帳への翻訳（誤分類の期待数）')
    for k,v in sorted(tr.items(),key=lambda z:-int(z[0]) if z[0].isdigit() else 0):
        print(f"  irr={k:<4} {v['今日の社数']:>3}社 × (1−正解率 {v['単一の読み手の正解率の帯']}) "
              f"→ **誤分類 {v['誤分類の期待数の帯'][0]}〜{v['誤分類の期待数の帯'][1]}社**")
    if out.get('引用の厚さと一致率'):
        e=out['引用の厚さと一致率']
        print(f"\n■ 引用の厚さと一致率: 厚い側 {e['厚い側']['一致率']}(n={e['厚い側']['n']}) "
              f"／ 薄い側 {e['薄い側']['一致率']}(n={e['薄い側']['n']})")
    print('→ out/irr_reliability.json')
    return 0

if __name__=='__main__': sys.exit(main())
