# US 高得点14社の v4 精査（2026-07-26）

日本株をv4厳格版で裁いた際に残した留保「US側はv4以前の物差しで採点されている」を潰すための再審査。
対象は `kanshi_list.json` の `omega75plus` 14社（＝現行で75以上の全て）。

## やり方
**機械値（SEC由来のroic/fcf/accr等）と p1–p4・f1–f5 は一切触っていない。**
動かしたのは堀4因子（dom/irr/rep/dur）だけで、根拠は各社の10-K/20-F **原本の全文**（30万〜98万字）を
ダウンロードして機械抽出したもの。適用したのは index.html の審査プロトコル本文にある v4 規則:

- `dom` … **原本にシェア%がなければ null**
- `irr` … 70は「移行の年数か費用を原本で示せる時のみ」／ソフト・サービスは既定50
- `rep` … 80は「10年超かつ現存競合2社以下」。**現存競合を実名で挙げられる時点で80以上は不可**
- `dur` … 85（ネットワーク）は「両側の登録数など原本の数字で示せる時のみ」

## 原本を読んで分かった一番大きい事実
**14社中、10-Kで自社の市場シェア%を開示している会社はゼロだった。**
「market share」の語は全て『失うリスク』の文脈（例: NVDA "Competition could adversely impact our market share"）。
したがって dom=85 や 70 を付けていた11社は全て **dom=null** になる。

**乗換コストを年数や金額で書いている会社もゼロだった。** よって irr は原則50へ。
例外は認証・規制ロックか唯一供給を原本が明記している社のみ（下記）。

## 結果
| 銘柄 | 旧 | **v4** | 差 | 効いた原本 |
|---|---|---|---|---|
| ASML | 81.8 最上位 | **81.8 最上位** | 0 | **"ASML is currently the world's only manufacturer of EUV lithography systems."** ＝rep100が原本で裏付く。DUVはCanon/Nikonと競合と明記 |
| V | 83.0 最上位 | **79.5 堅実** | −3.5 | dur85維持: "nearly 5 billion payment credentials ... at more than 175 million merchant locations"＝両側の実数が原本にある |
| MSFT | 77.7 堅実 | **77.7 堅実** | 0 | プロトコルの参照アンカーと現行値が一致（後述） |
| KLAC | 81.3 最上位 | **77.1 堅実** | −4.2 | Applied Materials・Onto Innovation・Hitachi High-Techを実名で挙げられる |
| IRMD | 79.1 堅実 | **76.4 堅実** | −2.7 | 原本が自社に不利な事実を記載（後述）。ただしIVポンプは"only known provider"でirr85維持 |
| RMD | 76.5 堅実 | **76.0 堅実** | −0.5 | ResMedアンカーと一致。domのみnull |
| MA | 77.7 堅実 | **74.6 回避圏** | −3.1 | "Some competitors have more market share than we do in certain jurisdictions" |
| JKHY | 75.4 堅実 | **70.9 回避** | −4.5 | 基幹系の入替は多年だが年数・費用の数値記載が原本になくirr50 |
| ADBE | 76.7 堅実 | **69.4 回避** | −7.3 | v4「ソフトは既定irr50」 |
| **NVDA** | 78.4 堅実 | **69.3 回避** | **−9.1** | AMD/Intel/Huawei＋Amazon/Microsoft/Alibabaの自社設計が10-Kに実名。CUDAの"over 7.5 million developers"は片側のみ |
| CTAS | 78.0 堅実 | **69.2 回避** | −8.8 | 10-Kが自ら "highly fragmented" と記載 |
| WTS | 75.4 堅実 | **66.5 回避** | −8.9 | "the number and identities of our competitors vary by product line" |
| IDXX | 76.2 堅実 | **66.2 回避** | −10.0 | Zoetis・Heska・Antech(Mars)・Fujifilmを実名で挙げられる |
| WDFC | 75.5 堅実 | **65.0 回避** | −10.5 | 原本は "3-IN-ONE Oil is the market share leader among drip oils" ＝順位のみで%なし |

**投下閾値75を維持したのは6社**: ASML 81.8 / V 79.5 / MSFT 77.7 / KLAC 77.1 / IRMD 76.4 / RMD 76.0
**割ったのは8社**: MA・JKHY・ADBE・NVDA・CTAS・WTS・IDXX・WDFC

## 個別に重い2件
**① NVDA が 投下可 から外れる（78.4→69.3）**
`kanshi_list.json` の `toka`（投下可）は NVDA・MSFT・RMD。このうち NVDA が回避圏に落ちる。
落ちた理由は業績ではなく**堀の裏付け**: 10-Kにシェア%の開示がなくdom→null、Competition節が
AMD・Intel・Huawei に加え Amazon/Microsoft/Alibaba の自社設計まで挙げるためrep80→60。
保有(holdings.json)は MSFT/ASML/RMD なので**現在の保有には影響しない**。

**② IRMD は原本が自社に不利な事実を書いていた**
> "We believe the dominant competitor with a market-leading position in MRI compatible vital signs
> monitoring is **Invivo Research**, which was founded by Roger Susi, our founder, President and CEO"

自社が「支配的競合は他社」と書いている以上、dom=85（圧倒70-89%）は原本と矛盾する→null。
一方で同じ原本が **"We are the only known provider of non-magnetic IV infusion pump systems
specifically designed to be safe for use during MRI procedures"** と書き、ISO 13485・CE Mark・FDAの
認証ロックもあるので irr=85 と dur=100 は維持。差引 76.4 で閾値は保つ。

## 採点者として一番問題だと思うこと（ユーザー判断が要る）
プロトコル本文の〈参照アンカー〉が **ASML / ResMed / Microsoft** の堀値を確定させている。
この3社は、他11社を切った検査そのものを免除されている。実際に免除を外すとこうなる:

| 銘柄 | アンカー適用(現行) | アンカー免除 | 差 |
|---|---|---|---|
| ASML | 81.8 | **81.8** | 0 ＝原本の "world's only manufacturer of EUV lithography systems" で自力で通る |
| RMD | 76.0 | **73.1** | −2.9 ＝閾値割れ |
| MSFT | 77.7 | **71.7** | −6.0 ＝閾値割れ |

**ASMLのアンカーは原本で稼いだもの。MSFTとResMedのアンカーは原本で検証されていない。**
MSFTの10-Kは全製品ラインで競合の存在を書き、シェア%も乗換年数も書いていない——他11社を落とした
条件とまったく同じ。**MSFTとRMDは現在の保有銘柄**なので、ここは私の裁量で動かさず判断を仰ぐ。

採点ロジック・プロトコル本文は掟どおり一切変更していない（アンカーは正本の記述）。

## 生成物
- `extract.py` / `extract2.py` … 10-K/20-F原本の取得と証拠抽出
- `raw_evidence.json` / `evidence2.json` … 抽出された原本の英文（Competition節・シェア・認証・唯一供給・両側実数）
- `v4_us14_pack.json` … 門に取り込める14社のv4完成パック（`_meta.audit.hanshou` に原本根拠）
- 検証: `node tools_validate_gate_json.mjs out/us_v4/v4_us14_pack.json` → 14/14社が台帳入り・エラーなし

※ `out/{T}_gate_pack.json`（旧審査）は上書きしていない。v4結果は取り込むかどうかをユーザーが決める。
