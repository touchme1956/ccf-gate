# -*- coding: utf-8 -*-
"""v5(証拠規則)で全銘柄を通し直す。機械値・p1-p4・f1-f5は不変、堀4因子のみ再判定。"""
import json,os
# ticker/nm -> (dom, irr, rep, dur, 出典と反証テスト)
REP={'ASML': (100, '追随不能: EUVに出荷実績を持つ他社ゼロ(20-F原本)'), 'NVDA': (80, '②追随に10年超かつ累計R&D $10B級: FY2025 R&D 約129億ドル/年、CUDAは2006年から約20年。AMDは10年追ってなお86%対の劣位＝競合が出荷していても複製は極困難'), 'MSFT': (80, '②累計R&D $10B級: R&D 約300億ドル/年。アンカー(Microsoft rep80・AWS/Google現存)と一致'), 'KLAC': (80, '②追随10年超かつ累計R&D $10B級: R&D 約15億ドル/年×10年。次点AMATが9.8%に留まる'), 'V': (60, '複製の蓄積を金額で示せない。両側ネットワークの価値はdur85で既に評価済でrepに二重計上しない'), 'MA': (60, '同上。かつ10-Kが『Some competitors have more market share than we do』と自認'), 'RMD': (80, '③規制で実質封鎖: FDA 510(k)/承認＋償還コードが原本に明記。アンカー(ResMed rep80)と一致'), 'IRMD': (80, '①非磁性MRI対応輸液ポンプに出荷実績を持つ他社ゼロ＋③FDA 510(k)/CE/ISO 13485'), 'IDXX': (60, 'リファレンスラボ網は資本集約だが$10B級を数値で示せない'), 'ADBE': (60, 'ソフト/SaaSの上限60'), 'CTAS': (60, 'ルート網は数年・数億ドル規模で構築可'), 'JKHY': (60, '蓄積の数値を示せない'), 'WDFC': (60, 'ブランド由来。蓄積の数値なし'), 'WTS': (60, '製品ライン分散で単一の蓄積を示せない')}
REPJP={'レーザーテック(6920)': (80, '①アクティニックEUVマスク検査に出荷実績を持つ他社ゼロ(GM Insights/360iResearch)'), 'アドバンテスト(6857)': (80, '①出荷実績を持つのはTeradyne・Cohuの2社(インベスターズガイド2025/4: Advantest+Teradyneで約80%)'), '東京エレクトロン(8035)': (80, '②累計R&D $10B級: R&D 約2,000億円/年×10年。コータ/デベロッパ89%を40年維持'), 'ディスコ(6146)': (60, '堀はプロセス知でありR&D/設備の$10B級の蓄積は示せない(dom85で評価済)'), 'SCREENホールディングス(7735)': (60, '蓄積の数値を示せない'), '信越化学(4063)': (80, '②累計設備投資 $10B級: capex 4,346億円/年×10年＝300億ドル超。ウエハ工場は資本で封鎖される')}
US={
"ASML":(85,85,100,100,"dom85: Mordor Intelligence 全リソグラフィ83%(推定90%まで)・EUV100%・DUV液浸85%超。rep100: 20-F原本『ASML is currently the world's only manufacturer of EUV lithography systems』＝EUVに出荷実績を持つ他社ゼロ。Canon/Nikonは20-Fで実名で挙がるがDUV/ナノインプリントのみ出荷"),
"NVDA":(85,50,60,75,"dom85: Bloomberg(Visual Capitalist集計)データセンターAI 86%、Silicon Analysts 80-90%。rep60: AMD(MI350X)・Intel・Huaweiに加えAmazon/Google/Microsoftの自社設計が出荷中＝3社超。irr50: 移行の年数・費用・構造的事実のいずれも原本になし。dur75: CUDAの7.5百万開発者は片側のみで両側の数字がなくネットワーク85は不可"),
"MSFT":(70,50,60,75,"dom70: StatCounter Windowsデスクトップ56.55%(2026年6月)、企業向け生産性ソフト58%。rep60: Google Workspace・Apple・AWS・Google Cloudが出荷中＝3社超。**v5でアンカー免除を外した結果**。irr50: ソフト/サービス既定。dur75: M365の446百万有料シートは片側のみ"),
"V":(70,50,60,85,"dom70: Nilson Report 米購買額シェア70.38%・世界購買件数38.47%(UnionPay含む)。二つの数値が寡占帯を挟むため70。rep60: Mastercard・American Express・JCB・UnionPay・Discoverが出荷中。dur85維持: 10-K原本に両側の実数『nearly 5 billion payment credentials ... more than 175 million merchant locations』"),
"MA":(50,50,60,75,"dom50: Nilson Report 米購買額29.62%(Visa 70.38%)。10-K原本も『Some competitors have more market share than we do in certain jurisdictions』と自認。rep60: Visa他が出荷中。dur75: 原本の表現は『hundreds of millions of acceptance locations』でVisaのような両側の登録実数ではない"),
"KLAC":(70,50,60,100,"dom70: プロセス制御シェア56%(次点Applied Materials 9.8%、7倍差)。光学ウエハ検査は85%超だが下位区分。rep60: AMAT・Onto Innovation・日立ハイテクが出荷中＝3社。dur100: 検査装置は顧客の量産プロセスに組み込まれる型"),
"RMD":(70,85,60,85,"dom70: MarketsandMarkets/Mordor CPAP世界供給の40%超で首位。rep60: Philips Respironics(25-30%)・Fisher & Paykel・React Healthが出荷中＝3社超。**v5でアンカー免除を外した結果**。irr85維持: FDA 510(k)/承認が原本に明記された認証ロック"),
"IRMD":(70,85,80,100,"dom70: Future Market Insights/market.us MRI対応輸液ポンプ市場の40%超。rep80: 『only provider of a non-magnetic IV infusion pump system』＝非磁性MRI対応ポンプに出荷実績を持つ他社ゼロ(B.Braun/Baxter/BDは非MRI)。ただしバイタル監視はInvivo Researchが出荷し10-Kも『dominant competitor』と自認するため100は不可。irr85: FDA 510(k)+CE Mark+ISO 13485"),
"IDXX":(None,50,60,75,"dom=null: 上位3社(IDEXX/Zoetis/Antech)合計45-50%の統計しかなく、個社の%を①②③のどれでも示せない。rep60: Zoetis・Antech(Mars)・Fujifilmが出荷中"),
"ADBE":(70,50,60,75,"dom70: 6Wresearch/SNS Insider クリエイティブソフト58.2%(次点Corel 11.4%・Affinity 6.9%)。rep60: Canva(10.26%)・Corel・Affinity・Figmaが出荷中。irr50: ソフト既定"),
"CTAS":(50,50,60,75,"dom50: 米ユニフォームレンタル31-35%。10-K原本も『highly fragmented』と自認。rep60: Vestis(20-25%)・UniFirst(12%)・Alscoが出荷中"),
"JKHY":(50,50,60,75,"dom50: **カンザスシティ連銀(規制当局=証拠規則③)** 銀行の21%・信用組合の12%。Fiserv 42%/31%、FIS 9%/3%。rep60: Fiserv・FIS・Temenos等が出荷中"),
"WDFC":(None,50,60,55,"dom=null: 原本は『3-IN-ONE Oil is the market share leader among drip oils』で順位のみ、第三者統計でも%を特定できず。堀はブランド由来でdur55"),
"WTS":(None,50,60,75,"dom=null: 10-K原本が『the number and identities of our competitors vary by product line and market』と記載し、単一市場のシェア%が定義できない"),
}
JP={
"レーザーテック(6920)":(85,50,80,100,"dom85: GM Insights/360iResearch **アクティニックEUVパターンマスク検査は100%・13.5nmの実波長で検査できる唯一の市販装置**。ただし広義のEUVマスク検査ではKLAが34%超で出荷中のため100ではなく85。rep80: アクティニック区分に出荷実績を持つ他社ゼロ(蓄積は約10年で20年超ではないため100は不可)。**v4では個人ブログを根拠に一度dom100/rep80と付け、規則違反として自己是正しdom=null/rep60まで落としていた。v5の証拠規則で業界調査会社の統計が採用可となり復帰**"),
"アドバンテスト(6857)":(70,70,80,75,"dom70: アドバンテスト インベスターズガイド2025年4月(英語版)『Advantest+Teradyneで約80%』、第三者推定でアドバンテスト単独48-52%。rep80: 当該チョークポイントに出荷実績を持つのはTeradyneとCohuの2社。irr70: 原本『選定されたテスタを変更することは、顧客にとってデバイスの開発・評価・量産のすべての環境を再構築することと同義』＝構造的事実"),
"東京エレクトロン(8035)":(85,50,60,100,"dom85: 統合報告書『コータ/デベロッパの製品シェアは過去最高の89%』『EUV露光用塗布現像装置のシェア100%』。rep60: Applied Materials・Lam Research・ASML/KLAが出荷中＝3社超。社長自身が『半導体製造装置市場のシェアは10%に留まり』と全社ベースの非寡占を明記"),
"ディスコ(6146)":(85,50,60,100,"dom85: **日経テックフォーサイト(関家一馬社長)『AI関連の後工程装置シェア9割超』**、同社決算資料でダイサ/グラインダ/ポリッシャは7-8割。v4では10-Kにシェア%がなくnullだったが、v5の証拠規則で復帰。rep60: 東京精密・岡本工作機械・Accretechが出荷中"),
"SCREENホールディングス(7735)":(70,50,60,100,"dom70: 枚葉式洗浄装置で世界シェア1位45%(ORIX Rentec Insight)、洗浄装置全体では34.7%。rep60: 東京エレクトロン・SEMES・Lam Researchが出荷中"),
"信越化学(4063)":(None,50,60,100,"dom=null: 統合報告書は『半導体シリコンで世界1位』と順位のみ。第三者情報も『SUMCOと二強体制』止まりで%を特定できず、証拠規則①②③のどれでも数値を示せない"),
}
def load(p):
    d=json.load(open(p)); return d[0] if isinstance(d,list) else d
out=[]
for t,(dom,irr,rep,dur,h) in US.items():
    o=load(f"out/{t}_gate_pack.json")
    rep,rh=REP[t]
    o["dom"],o["irr"],o["rep"],o["dur"]=dom,irr,rep,dur
    h=h+" / rep"+str(rep)+": "+rh
    a=o.setdefault("_meta",{}).setdefault("audit",{})
    a.update({"auditDate":"2026-07-26","model":"claude-opus-5",
      "protocol":"門2審査プロトコル v5(証拠規則: 自己開示ではなく第三者が検証できる事実)",
      "hanshou":h,"scope":"堀4因子のみ再判定。機械値(SEC由来)・p1-p4・f1-f5は不変"})
    out.append(o)
sem={o["nm"]:o for o in json.load(open("out/jp/semi/v4_semi14_pack.json"))}
for nm,(dom,irr,rep,dur,h) in JP.items():
    o=sem[nm]
    if nm in REPJP: rep,rh=REPJP[nm]; h=h+" / rep"+str(rep)+": "+rh
    o["dom"],o["irr"],o["rep"],o["dur"]=dom,irr,rep,dur
    a=o["_meta"]["audit"]; a["protocol"]="門2審査プロトコル v5(証拠規則)"; a["auditDate"]="2026-07-26"; a["hanshou_v5"]=h
for o in sem.values(): out.append(o)
json.dump(out,open("out/v5/v5_all_pack.json","w"),ensure_ascii=False,indent=1)
print(len(out),"社")
