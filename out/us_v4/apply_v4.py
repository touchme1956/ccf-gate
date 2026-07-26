# -*- coding: utf-8 -*-
"""US高得点14社に門2審査プロトコルv4(index.html正本)を適用。
機械値(SEC由来)は一切触らず、堀4因子(dom/irr/rep/dur)のみ原本根拠で是正する。
参照アンカー(ASML/ResMed/Microsoft)はプロトコルが確定済みなので堀を動かさない。"""
import json,os
FIX={
"NVDA":dict(dom=None,irr=50,rep=60,dur=75,
 h="AMD・Intel・Huawei、加えてAmazon/Microsoft/Alibabaの自社設計を10-KのCompetition節が実名で挙げる＝現存競合2社以下でないためrep80は不可→60。10-K全文にシェア%の開示はなく(市場シェアの語は全て『失うリスク』の文脈)dom→null。移行年数・費用の記載なしでirr→50。CUDAの『over 7.5 million developers』は原本の実数だが片側のみで、v4のdur85(両側の登録数)には足りず75(スイッチングコスト)"),
"MSFT":dict(keep=True,h="プロトコルの参照アンカー『Microsoft irr70 rep80 dur85(AWS/Google現存)』と現行値が完全一致。アンカーは正本が確定済みなので動かさない"),
"RMD":dict(dom=None,h="参照アンカー『ResMed irr85 rep80 dur85』と現行のirr/rep/durが完全一致→堀は据置。domのみ是正: 10-K全文にシェア%の開示がなくnull。Competition節はPhilips BV・Fisher & Paykel・DeVilbiss・Apex Medical・BMC Medical・React Healthを実名で列挙"),
"V":dict(dom=None,irr=50,rep=60,dur=85,
 h="rep: Mastercard・American Express・JCB・China UnionPay・Discoverが10-Kで実名→60。irr: 移行年数・費用の記載なし、かつ10-K自身がCredit Card Competition Act(第2ネットワーク強制)のリスクを記載→50。**dur85は原本の両側実数で維持**: 『nearly 5 billion payment credentials ... available to be used at more than 175 million merchant locations worldwide』"),
"CTAS":dict(dom=None,irr=50,rep=60,dur=75,
 h="10-Kが自ら『The primary markets served by each of the Cintas operating segments are local in nature and **highly fragmented**』と記載＝寡占ではない。rep80不可→60、dom→null。dur85(ネットワーク)を支える両側の登録数が原本になくルート密度＝規模の経済なので75(スイッチングコスト)"),
"MA":dict(dom=None,irr=50,rep=60,dur=75,
 h="10-Kが『We compete worldwide with payments networks such as Visa, American Express, JCB, China UnionPay and Discover』と実名列挙し、さらに『**Some competitors have more market share than we do in certain jurisdictions**』と自認→rep60/dom null。dur: 原本の表現は『hundreds of millions of acceptance locations』で、Visaのような両側の登録実数ではないためv4のdur85要件を満たさず75。**事業の優劣ではなく開示の差**"),
"IDXX":dict(dom=None,irr=50,rep=60,dur=75,
 h="Competition節がZoetis・Heska・Antech(Mars)・Fujifilm等を実名で挙げる→rep60。10-Kにシェア%の開示なし→dom null。機器の複数年契約はあるが移行年数・費用の数値記載がなくirr→50"),
"ADBE":dict(dom=None,irr=50,rep=60,dur=75,
 h="v4『ソフトウェア/サービスは既定irr50』を適用→70から50。10-KのCOMPETITION節は『companies of various sizes and both public and private companies, including large, global companies and smaller companies with more specialized focuses, new entrants, and AI or cloud-native companies』＝競合多数。シェア%開示なし→dom null"),
"WDFC":dict(dom=None,irr=50,rep=60,dur=55,
 h="原本にあるのは『3-IN-ONE Oil is the market share leader among drip oils in many countries』＝順位のみで%がなくdom null。10-Kが『We are aware of many competing products』と記載→rep60。堀はブランド由来でdur55は据置(v4の上限規則どおり)"),
"JKHY":dict(dom=None,irr=50,rep=60,dur=75,
 h="Fiserv等を実名で挙げ、10-Kが『Some of our current competitors have longer operating histories, larger client bases, and greater financial resources』と記載。基幹系の入替は多年を要するが**年数・費用の数値記載が原本になく**irr→50(アドバンテストと同じ判定)。シェア%なし→dom null"),
"WTS":dict(dom=None,irr=50,rep=60,dur=75,
 h="10-Kが『the number and identities of our competitors vary by product line and market』と記載＝製品ラインごとに競合が存在→rep60。シェア%なし→dom null。競争要因に『plumbing code requirements』が挙がるが認証が当社を排他的にロックする記載はなくirr→50、durは規格適合＝スイッチングコスト75"),
"KLAC":dict(dom=None,irr=50,rep=60,dur=100,
 h="Applied Materials・Onto Innovation・Hitachi High-Technologiesを実名で挙げられる→rep60。10-Kにシェア%開示なし(『市場シェアを失うリスク』の記述のみ)→dom null。移行年数の記載なしirr→50。**dur100(プロセス知/物理)は据置**＝検査装置は顧客の量産プロセスに組み込まれる型"),
"ASML":dict(keep=True,h="プロトコルの参照アンカー『ASML irr85 rep100 dur100(代替供給者ゼロ)』と現行値が完全一致。アンカーは正本が確定済みなので動かさない"),
"IRMD":dict(dom=None,rep=60,
 h="**原本が自社に不利な事実を書いている**: 『We believe the dominant competitor with a market-leading position in MRI compatible vital signs monitoring is **Invivo Research**』→dom85(圧倒70-89%)は原本と矛盾しnull、rep80も不可→60。一方irr85は原本で維持: 『**We are the only known provider of non-magnetic IV infusion pump systems specifically designed to be safe for use during MRI procedures**』＋ISO 13485/CE Mark/FDAの認証ロック。dur100(規制/物理)も据置"),
}
T=list(FIX.keys()); base=[];new=[]
for t in T:
    d=json.load(open(f"out/{t}_gate_pack.json")); o=d[0] if isinstance(d,list) else d
    base.append(json.loads(json.dumps(o)))
    f=FIX[t]
    if not f.get("keep"):
        for k in ("dom","irr","rep","dur"):
            if k in f: o[k]=f[k]
    m=o.setdefault("_meta",{}); a=m.setdefault("audit",{})
    a.update({"auditDate":"2026-07-26","model":"claude-opus-5",
      "protocol":"門2審査プロトコル v4(index.html正本の厳格版)",
      "hanshou":f["h"],
      "scope":"堀4因子(dom/irr/rep/dur)のみ原本根拠で是正。機械値(SEC由来)・p1-p4・f1-f5は不変",
      "anchor_note":"参照アンカー ASML(irr85/rep100/dur100)・ResMed(irr85/rep80/dur85)・Microsoft(irr70/rep80/dur85)はプロトコル本文が確定済みのため堀を動かさない"})
    new.append(o)
json.dump(base,open("/tmp/us14_base.json","w"),ensure_ascii=False)
json.dump(new,open("out/us_v4/v4_us14_pack.json","w"),ensure_ascii=False,indent=1)
print("ok",len(new))
