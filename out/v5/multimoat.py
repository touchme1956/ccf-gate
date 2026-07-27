# -*- coding: utf-8 -*-
"""複数の堀を持つ会社の採点案。現行エンジンは堀を1組(dom/irr/rep/dur)しか持てず、
   複数事業の会社は審査者が1つ選ぶか平均するしかない＝強い堀と弱い堀が混ざって薄まる。
   案: 事業ごとに堀を採点し、①利益(売上)で重みづけ ②最強の堀を軸に ③独立した堀に逓減ボーナス。
   MSFT FY2025 セグメント売上(10-K実額, 百万ドル): 総額281,724
     Productivity & Business Processes 120,810 / Intelligent Cloud 106,820 / More Personal Computing 54,094"""
import math
gm=lambda v,w: math.exp(sum(wi*math.log(vi) for vi,wi in zip(v,w)))
cap=lambda v: min(96,v)
W=[.30,.30,.25,.15]
moat=lambda d,i,r,u: gm([cap(d),cap(i),cap(r),cap(u)],W)

MSFT=[  # 事業, 売上, dom, irr, rep, dur, 根拠
 ("M365/Office (P&BP)",120810,70,70,80,85,"企業向け生産性ソフト58%(6sense)。irr70=テナント移行とファイル形式・ID連携の構造的事実。dur85=文書交換のネットワーク"),
 ("Azure (Intelligent Cloud)",106820,50,70,80,75,"Synergy Research クラウド約24%＝競争<40%。irr70=データ移送費とコミット契約"),
 ("Windows/Gaming/Search (MPC)",54094,70,50,80,75,"StatCounter デスクトップOS 56.55%。irr50=消費者は乗換自由"),
]
ASML=[("EUVリソグラフィ",32700,85,85,100,100,"20-F『world only manufacturer of EUV』")]
EWELL=[("訪問看護SaaS",4500,70,50,60,75,"第三者シェア統計なし→dom=null(=70扱い)")]

def score(segs,label):
    tot=sum(s[1] for s in segs)
    per=[(s[0],s[1]/tot,moat(*s[2:6]),s[6]) for s in segs]
    per.sort(key=lambda x:-x[2])
    wavg=sum(w*m for _,w,m,_ in per)                      # (b) 売上加重平均
    best=per[0][2]                                        # 最強の堀
    # (c) 最強を軸に、売上15%以上を覆う独立した堀へ逓減ボーナス(第2に+, 第3にその半分)
    bonus=0.0
    for k,(nm,w,m,_) in enumerate(per[1:3]):
        if w>=0.15: bonus += (m/best)*w*100*[0.18,0.09][k]
    comb=min(96,best+bonus)
    print(f"\n=== {label} ===")
    for nm,w,m,src in per: print(f"  {nm:<30} 売上{w*100:5.1f}%  堀 {m:5.1f}   {src[:52]}")
    print(f"  (a) 現行=審査者が1組に潰す        …… {moat(*_single[label]):5.1f}")
    print(f"  (b) 売上加重平均                  …… {wavg:5.1f}   ← 弱い堀が強い堀を薄める")
    print(f"  (c) 最強+独立ボーナス(推奨)       …… {comb:5.1f}   (最強{best:.1f} + 独立分{bonus:+.1f})")
    return comb
_single={"Microsoft":(70,50,80,75),"ASML":(85,85,100,100),"eWeLL":(70,50,60,75)}
score(MSFT,"Microsoft"); score(ASML,"ASML"); score(EWELL,"eWeLL")
print("""
読み方: (c)は「一点突破は薄めない・独立した第2の堀は少しだけ足す」。
  ASMLは単一事業なのでボーナス0＝集中を罰しない。eWeLLも単一なので変わらない。
  Microsoftだけが上がる＝『堀が複数ある』ことが初めて数字に出る。""")
