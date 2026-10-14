#!/usr/bin/env python3
"""night/unx_account.py — 器の外の費用と取り分（群 E・読むだけ・門の採点・四関門・席・売却規律・配分・注文書には触れない）

2026-10-14 ユーザー「今までに見つけられなかったものを見つけ出して。調べきれていない組み合わせやETF投資信託など
調べられていないものを見つけ出して。」 事前登録 out/unexplored_prereg.json（6f534c92）の groups.E_account_costs をそのまま行う。

  E1 iDeCo（楽天証券）の口座の手数料（加入時・毎月・受け取り時・還付）と、20年の毎月の積立での年率の費用（内部収益率の差）。
     所得控除の効果は個人の収入に依るので書かない（『控除の効果がこの率を上回るか』の形で出す）。
     指定運用方法（配分を指定しないときの行き先）の名前と、その基準価額の1・3・5年の円の騰落率を、楽天・プラス・NASDAQ-100 と同じ窓で。
  E2 楽天カードの投信積立のポイント（カードの種類・販売会社の取り分〔代行手数料〕の帯・月の上限）と、iFreeNEXT NASDAQ100・こどもNISA・iDeCo に付くか。
     価値＝積立額×還元率。20年の毎月の積立の年率に直す式も出す。
  E3 円→ドルの両替の手数料（リアルタイム為替 0銭 と 円貨決済 25銭）と、米国 ETF の買付への効き（年率）。
  E4 NISA の米国 ETF の配当がドルで口座に残ったとき、門の注文書がそれを使うか（index.html のコードを読む）。
     使わないなら、保有と目標の配当利回り（out/etf_profiles.json）で、配当が平均 6/12/24 か月遊んだときの20年の最終額への効き。
  E5 緊急の資金の置き場所（普通預金・楽天銀行マネーブリッジ・個人向け国債 変動10年・楽天証券の円のマネーファンド）の今の利率と性質（額は書かない）。

事実（一次資料・2026-10-14 に取得）は下の FACTS に出典つきの定数として持つ＝事実の部分はネット無しで回る。
基準価額（E1）だけは投資信託協会 投信総合検索ライブラリーの CSV を使う（キャッシュがあれば取りに行かない。UA に個人の連絡先を載せない
nx_jpfunds_data.Lib を使う）。キャッシュの置き場所は環境変数 UNX_CACHE、無ければ out/_nx_cache/unx/account/（gitignore 済み）。

  UNX_CACHE=/path/to/cache python3 night/unx_account.py   → out/unx_account.json

⚠ 個人の収入・税率・節税額・名前は書かない（ルール9）。名義は A・B。額の例は一般の例（5,000円〜62,000円・1万〜10万円）で、
  この家の計画の額は portfolio.json に既にある比率（ETF側の目標）だけを使う。
⚠ 測れないものは null と理由（ルール7）。
"""
import csv, datetime, io, json, math, os, re, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'unx_account.json')
PREREG = 'out/unexplored_prereg.json（6f534c92）'
ACCESS = '2026-10-14'
CACHE = os.environ.get('UNX_CACHE') or os.path.join(BASE, 'out', '_nx_cache', 'unx', 'account')
DATA_END = '2026-09-30'          # 事前登録 common.data_cutoff（月次は 2026-09 まで）

# ─────────────────────────────────────────────────────────────────────────────
# 事実（一次資料）。value は数、quote は原文の要旨（抜粋）。url はその一次資料。
# ─────────────────────────────────────────────────────────────────────────────
U_RK_IDECO_FEE = 'https://dc.rakuten-sec.co.jp/service/commission/'
U_RK_IDECO_SELECT = 'https://dc.rakuten-sec.co.jp/service/select/'
U_RK_IDECO_SETTING = 'https://dc.rakuten-sec.co.jp/admission/setting/'
U_RK_IDECO_PRODUCT = 'https://dc.rakuten-sec.co.jp/service/product/'
U_KOUSHIKI_STRUCT = 'https://www.ideco-koushiki.jp/guide/structure.html'
U_HOKUGIN = 'https://www.hokugin.co.jp/save/kakuteikyosyutu/data/ideco_info20260828_01.pdf'
U_RK_CC = 'https://www.rakuten-sec.co.jp/web/rfund/guide/creditcard.html'
U_RK_CC_LIST = 'https://www.rakuten-sec.co.jp/web/rfund/guide/creditcard/list.html'
U_RK_CC_PDF = 'https://www.rakuten-sec.co.jp/web/rfund/guide/creditcard/pdf/fund_list_05point_202610.pdf'
U_RK_RCASH = 'https://www.rakuten-sec.co.jp/web/rfund/guide/rcash.html'
U_RK_KODOMO = 'https://www.rakuten-sec.co.jp/web/nisa/kodomo-nisa/'
U_DAIWA_KOFU = 'https://www.daiwa-am.co.jp/funds/doc_open/fund_doc_open.php?code=3373&type=1'
U_DAIWA_SEIKYU = 'https://www.daiwa-am.co.jp/funds/doc_open/fund_doc_open.php?code=3373&type=2'
U_RC_GOLD = 'https://www.rakuten-card.co.jp/card/rakuten-gold-card/'
U_RK_FXRULE = 'https://www.rakuten-sec.co.jp/web/currency/forex/rule.html'
U_RK_USCOMM = 'https://www.rakuten-sec.co.jp/web/foreign/us/commission.html'
U_RK_COMM = 'https://www.rakuten-sec.co.jp/web/commission/'
U_RK_PRESS_FX0 = 'https://www.rakuten-sec.co.jp/web/company/newsrelease/pdf/press20231201_02.pdf'
U_RK_DIVCCY = 'https://www.rakuten-sec.co.jp/web/info/info20230529-01.html'
U_RK_DIV = 'https://www.rakuten-sec.co.jp/web/service/dividend/'
U_RK_MMF_DIV = 'https://www.rakuten-sec.co.jp/web/us/stock/mmf/dividend/'
U_RK_RAKUMONEY = 'https://www.rakuten-sec.co.jp/web/service/rakumoney-mgmt/'
U_RB_RATE = 'https://www.rakuten-bank.co.jp/interest/details.html'
U_RB_NOTICE = 'https://www.rakuten-bank.co.jp/info/2026/260617.html'
U_MOF_199 = 'https://www.mof.go.jp/jgbs/individual/kojinmuke/houdouhappyou/p20261007.pdf'
U_MOF_HENDOU = 'https://www.mof.go.jp/jgbs/individual/kojinmuke/main/outline/hendou/'
U_RK_MRF = 'https://www.rakuten-sec.co.jp/web/rakutenmoneyfund/'
U_RK_MRF_JS = 'https://www.rakuten-sec.co.jp/api/ss/menu_js/rakuten_money_fund.js'
U_RK_MRF_YEN = 'https://www.rakuten-sec.co.jp/web/service/rakumoney-mgmt/currency-yen/'
U_JITA = 'https://toushin-lib.fwg.ne.jp/FdsWeb/FDST030000/csv-file-download'

FACTS = {
    'E1_ideco_fees': {
        'url': U_RK_IDECO_FEE, 'accessed': ACCESS,
        '加入時・移換時（国民年金基金連合会）': 2829,
        '毎月（加入者＝掛金を拠出している人）': {
            '国民年金基金連合会': {'2026年11月分まで': 105, '2026年12月分（2027年1月26日引落分）から': 120},
            '楽天証券（運営管理手数料）': 0,
            '信託銀行': 66,
            '合計': {'今（2026年11月分まで）': 171, '2026年12月分から': 186},
        },
        '国基連の手数料の数え方': '2026年11月分（2026-12-28引落分）までは納付（収納）回数1回につき105円。2026年12月分（2027-01-26引落分）から'
                          'は拠出月数（収納回数にかかわらず、掛金を拠出する対象月数）に応じて月額120円＝年単位拠出（月別掛金）でも120円×月数。'
                          '毎月の掛金から控除され、控除後の額で運用商品が買われる。',
        '運用指図者（掛金を拠出していない人）': {'信託銀行': 66, '楽天証券': 0, '合計': 66,
                                   '払い方': '年金資産から（毎年1回、保有商品の一部を売って充てる）・給付金から差し引く'},
        '給付（受け取り）1回あたり（信託銀行）': 440,
        '還付1回あたり': {'国民年金基金連合会': 1048, '信託銀行': 440, '合計': 1488,
                     '還付とは': '限度額を超えた掛金・加入資格の無い月の掛金などを返すこと'},
        '移換（楽天証券から他社等へ）': 4400,
        'cross_check': {'url': U_HOKUGIN, 'accessed': ACCESS,
                        '要旨': '北陸銀行の案内（2026年9月）: 国基連の掛金納付時手数料 105円→120円・2027年1月26日の口座引き落とし分の掛金から。'
                              '年単位拠出の加入者は「現行: 掛金を拠出する月のみ負担／新: 掛金拠出有無に関わらず毎月分負担」。'
                              '運用指図者は掛金納付時手数料を負担しない（影響なし）。'},
        'scout_conflict': '探索役は「186円/月」と書いた＝一次資料と一致（今は171円・2026年12月分から186円）。'
                          '拠出しない月: 掛金を止めて運用指図者になれば国基連の120円は掛からず信託銀行の66円/月だけ（資産から年1回）。'
                          '年単位拠出の拠出しない月も、2026年12月分からは国基連120円×その期間の月数が掛かる（楽天・北陸銀行とも）。',
    },
    'E1_default_fund': {
        'url': U_RK_IDECO_SELECT, 'accessed': ACCESS,
        '名前': '楽天・インデックス・バランス（DC年金）', '委託会社': '楽天投信投資顧問',
        'isin': 'JP90C000GCQ3', 'associFundCd': '9I312185',
        '適用': '初回掛金拠出日から約4か月経過しても配分指定をされていない場合、この商品で運用される（楽天証券）。'
              'それまでは未指図資産として現金のまま管理される（楽天証券 口座開設後のお手続き）。'
              '2018年4月30日以前の加入者は特定期間・猶予期間なく『みずほDC定期預金』が購入される。',
        'koushiki': {'url': U_KOUSHIKI_STRUCT, 'accessed': ACCESS,
                     '要旨': '最初の掛金の納付日から特定期間3か月以上および猶予期間2週間以上で運営管理機関が定める期間を経過しても'
                           '運用商品を選ばないと、指定運用方法を選んだものとみなされ購入される（iDeCo公式）。'},
        '選定理由（楽天証券の商品一覧）': {'url': U_RK_IDECO_PRODUCT,
                              '要旨': '世界各国の株と債券に広く分散投資し、コストも十分低い（長期の運用商品のベース）'},
        '比べる本': {'名前': '楽天・プラス・NASDAQ-100インデックス・ファンド', 'isin': 'JP90C000QF22', 'associFundCd': '9I314241',
                  '設定日': '2024-01-30', '注': 'iDeCo のラインナップの中の NASDAQ100 の本（楽天証券の商品一覧）'},
        '参考の本（同じ指数・記録が長い）': {'名前': 'iFreeNEXT NASDAQ100インデックス', 'isin': 'JP90C000GUN2', 'associFundCd': '04317188',
                              '設定日': '2018-08-31', '注': 'iDeCo のラインナップには無い（NISA の器）。3年・5年の窓の NASDAQ100 の代わりに並べるだけ'},
        '配分指定の確かめ方': {
            'url': U_RK_IDECO_SETTING, 'accessed': ACCESS,
            '手順': [
                '書類（国基連の「個人型年金加入確認通知書」・JIS&T社の「口座開設のお知らせ」「インターネットパスワード設定のお知らせ」）が届いたら、'
                '楽天証券にログイン→「確定拠出年金 iDeCo」で初期設定（加入者口座番号と JIS&T のインターネットパスワード）',
                '「掛金の配分方針を設定（商品別配分設定）」（2回目以降は 注文→「掛金の配分変更」）で商品ごとの割合を1%単位で入れ、'
                '「商品別配分」で内容を確かめて確定。配分状況は「確定拠出年金トップ」に反映（時間がかかることがある）',
                '楽天証券の総合口座が無い場合は JIS&T社の専用サイト→「個人ポートフォリオ」→「商品別配分変更」',
                '締め切り: 引落日（26日・休日は翌営業日）から9営業日目の17時30分まで。配分指定した商品は掛金引落日から13営業日目に発注',
                '確かめる点: 確定拠出年金トップの配分状況が「楽天・プラス・NASDAQ-100 100%」になっていること・最初の約定後の資産に'
                '「楽天・インデックス・バランス（DC年金）」や現金（未指図資産）が残っていないこと',
            ]},
    },
    'E2_card_points': {
        'url': U_RK_CC_LIST, 'accessed': ACCESS, '更新日（ページ）': '2026-09-24',
        '還元率（代行手数料が年率0.4%（税込）未満のファンド）': {'楽天ブラックカード': 0.02, '楽天プレミアムカード': 0.01,
                                                 '楽天ゴールドカード': 0.0075, '上記以外の楽天カード': 0.005},
        '還元率（代行手数料が年率0.4%（税込）以上のファンド）': {'楽天ブラックカード': 0.02, '上記以外の楽天カード': 0.01},
        'ブラックカードの変更': '2027年1月買付分から 2.0%〜3.2%（前年の年間ショッピング利用額400万円以上で3.2%）（creditcard.html）',
        '判定の時点': '積立購入の前月12日（非営業日は前営業日）の代行手数料データ。変動するタイプは3か月前の13日',
        '月の上限': 100000, '上限の注': '毎月100円〜100,000円（複数ファンドの合計）。登録できる楽天カードは1枚・別のカードに変えても上限は同じ（creditcard.html）',
        '対象口座': '特定口座・一般口座・NISA成長投資枠・NISAつみたて投資枠。未成年口座・法人口座は対象外。楽ラップの積立・iDeCo口座での積立は対象外（creditcard.html）',
        '名義': '楽天証券と楽天カードの名義が一致するカードだけ。家族カードは使えない（贈与とみなされ得る）（creditcard.html）',
        '締め切りと買付日': '毎月12日までの積立設定で翌月の積立注文。買付日は 2024-08-25 以降に初めて使う人は毎月12日。1回払いだけ（creditcard.html）',
        'ポイント付与日': '積立注文月の15日前後（creditcard.html）',
        'url_main': U_RK_CC,
        'iFreeNEXT_NASDAQ100': {
            '販売会社の取り分（代行手数料）': {'税抜': 0.215, '税込': round(0.215 * 1.1, 4), '単位': '%/年',
                                  'url': U_DAIWA_SEIKYU, 'accessed': ACCESS,
                                  '要旨': '信託報酬 年率0.495%（税抜0.45%）の配分: 委託会社 0.215%・販売会社 0.215%・受託会社 0.02%（税抜・別途消費税）。'
                                        '販売会社への配分は代行手数料（請求目論見書 第二部(3)【信託報酬等】・交付目論見書 使用開始日 2026-05-26 にも同じ表）',
                                  'url_kofu': U_DAIWA_KOFU},
            '帯': '0.4%（税込）未満', '一覧に載っているか': True,
            '一覧': {'url': U_RK_CC_PDF, '要旨': '「楽天カードクレジット決済0.5%～2％ポイント還元対象ファンド一覧（2026年9月12日時点）」＝2026年10月注文分に '
                                                'JP90C000GUN2 iFreeNEXTNASDAQ100ｲﾝﾃﾞｯｸｽ（大和アセットマネジメント）が載っている'},
        },
        'こどもNISA': {'付くか': False, 'url': U_RK_KODOMO,
                     '理由': 'カード積立と楽天ペイ残高積立はどちらも「未成年口座」を対象外とする（creditcard.html・rcash.html）。楽天証券のこどもNISAは'
                           'こども口座（未成年口座）で開く（kodomo-nisa ページ「こども口座（未成年口座）開設済の場合は…」）。同じページが挙げるポイントは'
                           '対象ファンドの残高に応じたポイントと、楽天ポイントで買付できることだけ。また名義が一致するカードに限られ家族カードも不可。'},
        'iDeCo': {'付くか': False, '理由': '「iDeCo口座での積立は対象外」（creditcard.html・rcash.html）'},
        '楽天ペイ残高（電子マネー）積立': {'url': U_RK_RCASH, '還元率': 0.005, '月の上限': 50000,
                                '要旨': '積立利用額の0.5%。毎月100円〜50,000円。対象口座はカードと同じ（未成年口座・iDeCo は対象外）。カードと合わせて月15万円まで'},
        '年会費（楽天カード）': {'ゴールド': 2200, 'プレミアム': 11000, 'url': U_RC_GOLD, 'accessed': ACCESS,
                          '注': '楽天カードのサイトは自動取得を拒否（アクセス集中の画面）。値は rakuten-card.co.jp の検索結果に出た公式ページの比較表の抜粋で確かめた'},
    },
    'E3_fx': {
        'リアルタイム為替（米ドル/円）': {'手数料_銭': 0, 'url': U_RK_FXRULE, 'accessed': ACCESS,
                                '要旨': '取引時間 8:00〜翌6:00（夏時間翌5:00）・1米ドル以上0.01米ドル単位・発注後即時に約定。'
                                      '手数料は0銭だが、買レート・売レートは業者間レートを採用しており乖離がある（＝業者間の売り買いの差は残る）',
                                'since': {'url': U_RK_PRESS_FX0, '要旨': '2023年12月4日（月）8時注文分から米ドル/円のリアルタイム為替の手数料を無料'}},
        '円貨決済（日本円で米国株を売買）': {'手数料_銭': 25, 'url': U_RK_USCOMM, 'accessed': ACCESS,
                                 '要旨': '為替手数料（スプレッド）日本円での株式購入時 25銭/米ドル・売却時 25銭/米ドル（注文約定時の為替レートに含まれる）'},
        '配当の円での受け取り': {'手数料_銭': 25, 'url': U_RK_DIVCCY, 'accessed': ACCESS,
                          '要旨': '米国株の配当を日本円で受け取る場合、1米ドルあたり25銭の為替手数料（受け取り方を変えなければ米ドルで受け取る）'},
        'NISA の米国株の取引手数料': {'値': 0, 'url': U_RK_COMM, '注': '楽天のプレス（2023-12-01）「新NISA 米国株式の個別銘柄（ADR含む）・ETF の取引（売買）手数料が無料」'},
    },
    'E4_dividends': {
        '受け取りの通貨': {'url': U_RK_DIVCCY, 'accessed': ACCESS,
                     '要旨': '2023年5月28日から米国株の配当を米ドルか円かで選べる。変更がない場合は米ドルで受け取る設定（初期設定＝米ドル）。'},
        '入金先': {'url': U_RK_DIV, '要旨': '外国株式の配当金・分配金は源泉徴収後の金額が総合取引口座に入金。米国株式は配当金受取方法に応じて日本円か米ドル'},
        '米ドルMMF の自動買付': {'url': U_RK_MMF_DIV, 'accessed': ACCESS,
                           '要旨': '配当金受取方法を「外貨建てMMFで受取り」にすると、配当の入金日に楽天・米ドルMMF（ノーザン・トラスト・米ドル・リクイディティ・ファンド）を'
                                 '購入手数料0で自動買付。らくらくマネー運用（米ドル）では保有している米ドルMMFを米国株式などの買付代金としてそのまま使える（rakumoney-mgmt）',
                           'url2': U_RK_RAKUMONEY, '利回り': None, '利回りの理由': '楽天のページは利回りを画面の中で読み込む形で、静的な取得では値が取れなかった（未取得）'},
        'NISA の配当の税': '日本の税は掛からず、米国の源泉税10%は戻らない（etf_forward_rank の k と同じ扱い・事前登録 common.costs）',
    },
    'E5_emergency': {
        '楽天銀行 普通預金': {'金利_税引前': 0.40, '金利_税引後': 0.318, 'url': U_RB_RATE, 'accessed': ACCESS,
                        '性質': '変動金利・予告なく変わる。預金保険制度の「決済用預金」ではない（一般の預金として扱う）。利息に20.315%'},
        '楽天銀行 マネーブリッジ（優遇金利1）': {'金利_税引前': {'1円〜1,000万円': 0.48, '1,000万円を超えた分': 0.42},
                                     '金利_税引後': {'1円〜1,000万円': 0.382, '1,000万円を超えた分': 0.334},
                                     '改定日': '2026-08-03（2026-06-17 のお知らせ）', 'url': U_RB_RATE, 'url_notice': U_RB_NOTICE, 'accessed': ACCESS,
                                     '性質': '楽天証券と口座を連携する（前月末までに設定→当月1か月適用）。普通預金なのでいつでも引き出せる。'
                                           'マネーブリッジの自動入金（スイープ）で証券口座の買付に使える。楽天カードの引き落としがある人は優遇金利2 年0.42%。'
                                           '「ボーナス金利」プログラムで最大年0.74%（条件あり・ここでは条件を測っていない）'},
        '個人向け国債 変動10年（第199回）': {'初回の利率_税引前': 2.05, '初回の利率_税引後': 1.6335425, '基準金利': 3.10, '式': '基準金利×0.66（下限0.05%）・半年毎に見直し',
                                  '募集期間': '2026-10-08〜2026-10-30', '発行日': '2026-11-16', '利払日': '毎年5月15日・11月15日',
                                  '中途換金': '第2期利子支払日（発行から1年経過）以後いつでも。直前2回分の各利子（税引前）×0.79685 が差し引かれる',
                                  '単位': '1万円から1万円単位・額面100円につき100円（中途換金も同じ＝値段は動かない）',
                                  'url': U_MOF_199, 'url2': U_MOF_HENDOU, 'accessed': ACCESS,
                                  'scout_check': '探索役の「第199回 2.05%」は財務省の報道発表（令和8年10月7日）と一致'},
        '楽天・マネーファンド（MRF・楽天証券）': {'年利回り_税引前_信託報酬控除後': 1.079, '計算期間': '2026-10-07〜2026-10-13（7日間の分配金実績から）',
                                      'url': U_RK_MRF, 'url_value': U_RK_MRF_JS, 'url_auto': U_RK_MRF_YEN, 'accessed': ACCESS,
                                      '性質': '公社債投信（MRF）・元本保証ではない（預金保険の対象でもない）・信託報酬は年率1%以内・1円以上1円単位・購入手数料無料・'
                                            '引き出しは申込みの翌営業日に預り金へ（16時締め）・特定口座（NISA口座は対象外）・分配金は毎日→月末に再投資・'
                                            '利子所得20.315%。マネーブリッジから買える。らくらくマネー運用（円）で国内株式・投資信託の買付代金に自動で充てられる（積立は対象外）'},
        '円MMF': {'値': None, '理由': '楽天証券のメニューにある円のマネーファンドは「楽天・マネーファンド（MRF）」で、円MMF（MRF でない MMF）を扱っているかは確かめていない。'
                                     '事前登録の「円の MMF」は楽天で買える円のマネーファンド＝MRF で読み替えた（deviations）'},
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# 算術
# ─────────────────────────────────────────────────────────────────────────────
def irr_annual(outflows, terminal, months):
    """毎月はじめに outflows[t]（t=0..months-1）を払い、months か月目の終わりに terminal を受け取る流れの内部収益率（年率・実効）。"""
    def fv(i):
        return sum(c * (1 + i) ** (months - t) for t, c in enumerate(outflows))
    lo, hi = -0.5 / 12, 1.0 / 12
    for _ in range(200):
        mid = (lo + hi) / 2
        if fv(mid) > terminal:
            hi = mid
        else:
            lo = mid
    return (1 + (lo + hi) / 2) ** 12 - 1


def ideco_fee_drag(C, r, months=240, entry=2829, monthly=186, payout=440):
    """月 C 円を months か月。毎月 monthly、最初の月に entry を掛金から引き、受け取りで payout を1回引く。
    運用は年率 r（手数料以外の費用は0）。戻り値: 手数料を引いた後の内部収益率と差（pt/年）・手数料の合計。"""
    g = (1 + r) ** (1 / 12) - 1
    V = 0.0
    for t in range(months):
        inv = C - monthly - (entry if t == 0 else 0)
        V = (V + inv) * (1 + g)
    term = V - payout
    irr = irr_annual([C] * months, term, months)
    fees = monthly * months + entry + payout
    return {'irr_pct': round(100 * irr, 3), 'drag_pt': round(100 * (r - irr), 3),
            'fees_total_yen': fees, 'fee_share_of_contrib_pct': round(100 * fees / (C * months), 2)}


def dca_value_weighted_years(r, months=240):
    """毎月同額の積立で、最終額への寄与で重みを付けた平均の保有年数 D（年）。ln(1+p)/D が一度だけの取り分 p の年率の目安。"""
    g = (1 + r) ** (1 / 12) - 1
    w = [(1 + g) ** (months - t) for t in range(months)]
    return sum(wi * (months - t) / 12 for t, wi in enumerate(w)) / sum(w)


def one_off_to_annual(p, r, months=240):
    """積立額に一度だけ p（ポイントなら +p、両替の手数料なら −p）が付いたときの内部収益率の変化（pt/年・厳密）と目安式の値。"""
    g = (1 + r) ** (1 / 12) - 1
    V = 0.0
    for t in range(months):
        V = (V + (1 + p)) * (1 + g)
    irr = irr_annual([1.0] * months, V, months)
    D = dca_value_weighted_years(r, months)
    return {'exact_pt': round(100 * (irr - r), 4), 'approx_pt_ln1p_over_D': round(100 * math.log(1 + p) / D, 4), 'D_years': round(D, 2)}


def fee_at_exit(f, r, months=240):
    """最後に全額へ f の手数料が掛かったときの内部収益率の変化（pt/年）。"""
    g = (1 + r) ** (1 / 12) - 1
    V = 0.0
    for t in range(months):
        V = (V + 1.0) * (1 + g)
    irr = irr_annual([1.0] * months, V * (1 - f), months)
    return round(100 * (irr - r), 4)


def idle_dividend_effect(y, r, lag, months=240, wht=0.10):
    """配当利回り y（年・税引前・ポートフォリオ全体に対して）の配当が、源泉10%を引かれて現金で入り、lag か月 0% で遊んでから再投資される。
    lag=0 を『毎月すぐ再投資』の基準にして、最終額の差（%）と内部収益率の差（pt/年）を返す。lag=None は最後まで再投資しない。
    総リターン r（年）は税引前の配当を含む＝値上がり分は r−y。源泉10%の漏れは両方に同じく入る。"""
    g = (1 + r) ** (1 / 12) - 1
    dm = y / 12

    def run(L):
        V, q = 0.0, []
        for t in range(months):
            V += 1.0
            if L is not None:
                while q and q[0][0] <= t:
                    V += q.pop(0)[1]
            div = V * dm
            V *= (1 + g - dm)
            net = div * (1 - wht)
            if L == 0:
                V += net
            else:
                q.append((t + 1 + (L if L is not None else 10 ** 9), net))
        cash = sum(a for _, a in q)
        return V + cash, cash
    b, _ = run(0)
    x, cash = run(lag)
    ib = irr_annual([1.0] * months, b, months)
    ix = irr_annual([1.0] * months, x, months)
    return {'terminal_diff_pct': round(100 * (x / b - 1), 3), 'irr_diff_pt': round(100 * (ix - ib), 4),
            'idle_cash_share_at_end_pct': round(100 * cash / x, 3)}


# ─────────────────────────────────────────────────────────────────────────────
# 基準価額（E1）
# ─────────────────────────────────────────────────────────────────────────────
def jita_nav(isin, assoc):
    """[(YYYY-MM-DD, 基準価額, 分配金)]。キャッシュ優先。取れなければ None（ルール7）。"""
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f'jita_{assoc}.csv')
    if not (os.path.exists(p) and os.path.getsize(p) > 0):
        try:
            import nx_jpfunds_data as J
            b = J.Lib().csv(isin, assoc)
        except Exception as e:  # noqa
            print(f'  基準価額を取れない {assoc}: {e}', file=sys.stderr)
            return None
        if not b:
            return None
        open(p + '.tmp', 'wb').write(b)
        os.replace(p + '.tmp', p)
        time.sleep(0.5)
    t = open(p, 'rb').read().decode('cp932', errors='replace')
    rows = list(csv.reader(io.StringIO(t)))
    if not rows or '年月日' not in rows[0][0] or '基準価額' not in rows[0][1]:
        return None
    out = []
    for r in rows[1:]:
        m = re.match(r'\s*(\d{4})年(\d{1,2})月(\d{1,2})日', r[0] if r else '')
        if not m:
            continue
        try:
            nav = float(r[1].replace(',', ''))
        except ValueError:
            continue
        dv = 0.0
        if len(r) > 3 and r[3].strip():
            try:
                dv = float(r[3].replace(',', ''))
            except ValueError:
                return None
        out.append((f'{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}', nav, dv))
    out.sort()
    return out


def tr_levels(rows):
    lv, x, prev = {}, None, None
    for d, nav, dv in rows:
        x = nav if x is None else x * (nav + dv) / prev
        prev = nav
        lv[d] = x
    return lv


def on_or_before(lv, day):
    ks = [k for k in lv if k <= day]
    return max(ks) if ks else None


def window_return(lv, end_day, years=None, start_day=None):
    e = on_or_before(lv, end_day)
    if e is None:
        return None
    if start_day is None:
        ed = datetime.date.fromisoformat(e)
        try:
            sd = ed.replace(year=ed.year - years)
        except ValueError:
            sd = ed.replace(year=ed.year - years, day=28)
        start_day = sd.isoformat()
    s = on_or_before(lv, start_day)
    first = min(lv)
    if s is None or first > start_day:
        return {'start': None, 'end': e, 'cum_pct': None, 'ann_pct': None,
                'reason': f'記録が窓に足りない（最初の基準価額 {first}）'}
    days = (datetime.date.fromisoformat(e) - datetime.date.fromisoformat(s)).days
    cum = lv[e] / lv[s] - 1
    ann = (1 + cum) ** (365.25 / days) - 1 if days > 0 else None
    return {'start': s, 'end': e, 'cum_pct': round(100 * cum, 2), 'ann_pct': round(100 * ann, 2) if ann is not None else None}


def month_end_maxdd(lv, start, end):
    ks = sorted(k for k in lv if start <= k <= end)
    me = {}
    for k in ks:
        me[k[:7]] = k
    xs = [lv[me[m]] for m in sorted(me)]
    if len(xs) < 3:
        return None
    peak, dd = xs[0], 0.0
    for x in xs:
        peak = max(peak, x)
        dd = min(dd, x / peak - 1)
    return round(100 * dd, 1)


# ─────────────────────────────────────────────────────────────────────────────
# E4: index.html を読む（行番号は回すたびに数え直す）
# ─────────────────────────────────────────────────────────────────────────────
def read_order_book():
    p = os.path.join(BASE, 'index.html')
    L = open(p, encoding='utf-8').read().split('\n')
    names = ['ccfLedgerMap', 'ccfPfLive', 'ccfNetRows', 'ccfTotalAmt', 'ccfAutoAmt', 'ccfOrderAmt', 'ccfCatBudget',
             'ccfSleeveSplit', 'ccfWholeSharePlan', 'ccfCatSharePlan', 'ccfWholeShareBody', 'renderPlan']
    where = {}
    for n in names:
        rx = re.compile(r'^(async\s+)?function\s+' + n + r'\s*\(')
        hit = [i + 1 for i, s in enumerate(L) if rx.match(s)]
        where[n] = hit[0] if hit else None
    calls = {'ccfWholeShareBody に渡す入金（TO=ccfOrderAmt()）': [i + 1 for i, s in enumerate(L) if 'const TO=ccfOrderAmt()' in s],
             '注文書の呼び出し（ccfWholeShareBody(pass,tw,pxInfo,NO,TO,…)）': [i + 1 for i, s in enumerate(L) if 'ccfWholeShareBody(pass,tw,pxInfo,NO,TO' in s],
             '区分の材料の総資産（K={tot:+LV.total}）': [i + 1 for i, s in enumerate(L) if 'const K={tot:+LV.total}' in s],
             'pf:monthly_total を読む所': [i + 1 for i, s in enumerate(L) if "localStorage.getItem('pf:monthly_total')" in s]}
    # 注文書の関数の本文（定義の行から次の行頭の function まで）の中に、口座の現金・配当を読む語があるか
    starts = sorted(i for i, x in enumerate(L) if re.match(r'^(async\s+)?function\s', x))
    span_hits = {}
    for n, ln in where.items():
        if not ln:
            continue
        nxt = [i for i in starts if i > ln - 1]
        body = '\n'.join(L[ln - 1:(nxt[0] if nxt else len(L))])
        span_hits[n] = {k: body.count(k) for k in ('預り', '配当', 'dividend', 'cash', '外貨')}
    txt = '\n'.join(L)
    tokens = {'預り金': txt.count('預り金'), '外貨預り': txt.count('外貨預り'), "sleeve==='cash'": txt.count("sleeve==='cash'"),
              'cash（英字・どこでも）': len(re.findall(r'\bcash\b', txt)), 'MMF': txt.count('MMF')}
    pt = open(os.path.join(BASE, 'portfolio.html'), encoding='utf-8').read()
    cash_row = [i + 1 for i, s in enumerate(pt.split('\n')) if "opt('cash',p.sleeve,'現金')" in s]
    return {'index_html_lines': where, 'call_sites': calls, 'token_counts_in_index_html': tokens,
            'token_note': '英字の cash（index.html 全体）は全部、企業の財務（XBRL の現金の欄・net-cash の注意書き）で口座の現金ではない。renderPlan の中の「配当」2件は表示の文（実現複利は配当込み、の注記）',
            'token_counts_in_order_book_function_bodies': span_hits,
            'portfolio_html_cash_row_option_line': cash_row}


def load_json(rel):
    try:
        return json.load(open(os.path.join(BASE, rel), encoding='utf-8'))
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    deviations, caveats = [], []
    res = {}
    rs = [0.05, 0.08, 0.12]

    # ── E1 ──
    F1 = FACTS['E1_ideco_fees']
    m_new = F1['毎月（加入者＝掛金を拠出している人）']['合計']['2026年12月分から']
    tab = []
    for C in (5000, 10000, 20000, 23000, 62000):
        row = {'月の掛金_円': C, '毎月の手数料が掛金に占める割合_%': round(100 * m_new / C, 2)}
        for r in rs:
            row[f'r={int(r*100)}%'] = ideco_fee_drag(C, r, monthly=m_new)
        tab.append(row)
    main5 = {f'r={int(r*100)}%': ideco_fee_drag(5000, r, monthly=m_new)['drag_pt'] for r in rs}
    res['E1_ideco'] = {
        'fees': {k: v for k, v in F1.items() if k not in ('url', 'accessed')},
        'model': '月の掛金 C を240か月（20年）。毎月 186円（2026年12月分からの国基連120＋信託銀行66）を掛金から引き、最初の月に加入時 2,829円も引く。'
                 '運用は年率 r（ファンドの費用は入れない＝手数料だけの効き）。受け取りは一時金1回で 440円。掛金の側から見た内部収益率と r の差＝年率の費用。'
                 '還付（1,488円/回）と移換（4,400円）は起きたときだけなので入れていない。年金形式で受け取れば 440円×回数。'
                 '加入時の 2,829円は最初の掛金から引くと置いた（引かれ方の一次資料は確かめていない・別に払っても効きはほぼ同じ）。',
        'drag_5000yen_pt_per_year': main5,
        'drag_table': tab,
        'note_r_independence': 'r を 5〜12% に振っても差はほぼ同じ（手数料は掛金に対する一定額なので、成長率にほとんど依らない）。',
        'phrasing': '所得控除の効果（個人の収入で決まるので計算しない）が、この年率の費用（月5,000円なら上の値）を上回るかどうかで判断する形になる。'
                    'iDeCo の中のファンドの費用（楽天・プラス・NASDAQ-100 の実際の費用）はこの外に別にかかる。',
        'after_stop': '掛金を止めて運用指図者になると、毎月 66円（信託銀行）だけが年1回 資産から引かれる＝年792円（残高に対する割合は残高次第）。',
    }
    F2 = FACTS['E1_default_fund']
    nav = {}
    for key, isin, assoc in (('default', F2['isin'], F2['associFundCd']),
                             ('rplus_ndx', F2['比べる本']['isin'], F2['比べる本']['associFundCd']),
                             ('ifree_ndx', F2['参考の本（同じ指数・記録が長い）']['isin'], F2['参考の本（同じ指数・記録が長い）']['associFundCd'])):
        rows = jita_nav(isin, assoc)
        nav[key] = tr_levels(rows) if rows else None
    win = {}
    for key in ('default', 'rplus_ndx', 'ifree_ndx'):
        lv = nav[key]
        if not lv:
            win[key] = {'理由': '基準価額を取れなかった'}
            continue
        w = {f'{y}年': window_return(lv, DATA_END, years=y) for y in (1, 3, 5)}
        w['楽天・プラス・NASDAQ-100 の設定来と同じ窓'] = window_return(lv, DATA_END, start_day='2024-01-30')
        e5 = (w['5年'] or {}).get('start')
        w['5年の窓の月末の最大下落_%'] = month_end_maxdd(lv, e5, DATA_END) if e5 else None
        win[key] = w
    res['E1_default_fund'] = {
        'name': F2['名前'], 'rule': F2['適用'], 'koushiki': F2['koushiki']['要旨'],
        'verify_allocation': F2['配分指定の確かめ方']['手順'],
        'returns_yen_TR': {'楽天・インデックス・バランス（DC年金）': win.get('default'),
                           '楽天・プラス・NASDAQ-100インデックス・ファンド': win.get('rplus_ndx'),
                           '参考: iFreeNEXT NASDAQ100インデックス（同じ指数・iDeCo には無い）': win.get('ifree_ndx')},
        'returns_note': f'投資信託協会 投信総合検索ライブラリーの基準価額 CSV（{U_JITA}）。分配金は分配落ちの日に再投資。終わりは {DATA_END} 以前の最後の基準価額。'
                        '窓の始まりはその日の N 年前以前の最後の基準価額。費用は基準価額の中に入っている（税は入らない）。',
    }
    deviations.append('E1: 楽天・プラス・NASDAQ-100 は 2024-01-30 設定で 3年・5年の窓が無い。3年・5年は null（理由つき）とし、'
                      '①同じ指数の iFreeNEXT NASDAQ100（iDeCo には無い・費用が高い）を参考に並べ、②楽天・プラスの設定来と同じ窓で両方を比べた。')
    deviations.append('E1: 事前登録の指示は night/fetch_tsumitate_funds.py の Lib だが、同じ投信総合検索ライブラリーを UA に個人の連絡先を載せない '
                      'night/nx_jpfunds_data.Lib（同じ CSV の経路）で取った（共通の指示「新しい UA に個人のメールを載せない」に従う）。')

    # ── E2 ──
    FC = FACTS['E2_card_points']
    pts = {}
    for nm, p in (('一般カード 0.5%', 0.005), ('ゴールド 0.75%', 0.0075), ('プレミアム 1%', 0.01)):
        pts[nm] = {f'r={int(r*100)}%': one_off_to_annual(p, r) for r in rs}
    amounts = {}
    for M in (10000, 30000, 50000, 100000):
        amounts[f'月{M:,}円'] = {'一般0.5%_年のポイント': round(M * 12 * 0.005), 'ゴールド0.75%': round(M * 12 * 0.0075), 'プレミアム1%': round(M * 12 * 0.01)}
    fee = FC['年会費（楽天カード）']
    be = {'ゴールド（年会費2,200円・一般より+0.25%）': {'損益分岐の月の積立_円': round(fee['ゴールド'] / 12 / 0.0025)},
          'プレミアム（年会費11,000円・一般より+0.5%）': {'損益分岐の月の積立_円': round(fee['プレミアム'] / 12 / 0.005),
                                              '注': '上限の月10万円を超える＝積立のポイントだけでは元が取れない'}}
    res['E2_card_points'] = {
        'rates': {k: FC[k] for k in ('還元率（代行手数料が年率0.4%（税込）未満のファンド）', '還元率（代行手数料が年率0.4%（税込）以上のファンド）',
                                    'ブラックカードの変更', '判定の時点', '月の上限', '上限の注', '対象口座', '名義', '締め切りと買付日', 'ポイント付与日')},
        'iFreeNEXT_NASDAQ100': FC['iFreeNEXT_NASDAQ100'],
        'kodomo_NISA': FC['こどもNISA'], 'iDeCo': FC['iDeCo'], 'rakuten_pay_balance': FC['楽天ペイ残高（電子マネー）積立'],
        'value_formula': '価値（円）＝カードで払った積立額×還元率（その月に一度だけ）。20年の毎月の積立の年率への換算: '
                         f'内部収益率の上乗せ ≈ ln(1+p)÷D（D＝最終額への寄与で重みを付けた平均の保有年数。毎月同額の20年なら r=8% で約{dca_value_weighted_years(0.08):.1f}年）。'
                         'exact_pt は全ての積立に p が付いたとして内部収益率を解き直した値。カードで払える分（月10万円まで）にだけ効く。',
        'annualized': pts, 'points_per_year_examples': amounts, 'higher_tier_breakeven': be,
        'friction': '積立設定（毎月12日まで・翌月12日に買付・金額は前もって決める）だけが対象。門の注文書が出す iFreeNEXT の月ごとに変わる額（端数を寄せる分）を'
                    'その月にスポットで買う分にはポイントが付かない。',
    }
    caveats.append('E2: 年会費は楽天カードのサイトの直接取得が拒否されたので、rakuten-card.co.jp の検索結果に出た公式ページの比較表の抜粋で確かめた。')

    # ── E3 ──
    dash = load_json('out/dashboard.json') or {}
    fxv = ((dash.get('fx') or {}).get('USDJPY'))
    fx_src = 'out/dashboard.json fx.USDJPY（' + str((dash.get('fx') or {}).get('day')) + '）'
    if not fxv:
        fxv, fx_src = 158.365, '置き値（2026-10-14 の dashboard.json の値）'
    f = 0.25 / float(fxv)
    pf = load_json('portfolio.json') or {}
    tg = pf.get('target') or {}
    W = tg.get('ami_weights') or {}
    funds = set((tg.get('ami_funds') or {}).keys())
    usd_etf_w = sum(float(v) for k, v in W.items() if k not in funds and float(v) > 0)
    castle = float(tg.get('shiro_castle_pct') or 0)
    usd_share = (usd_etf_w + castle) / 100.0
    e3 = {}
    for r in rs:
        b = one_off_to_annual(-f, r)['exact_pt']
        x = fee_at_exit(f, r)
        e3[f'r={int(r*100)}%'] = {'ドルで買う分_買いだけ_pt': b, 'ドルで買う分_買い＋最後に円へ_pt': round(b + x, 4),
                                  'ポートフォリオ全体_買いだけ_pt': round(b * usd_share, 4), 'ポートフォリオ全体_買い＋最後_pt': round((b + x) * usd_share, 4)}
    res['E3_fx'] = {
        'facts': FACTS['E3_fx'],
        'usdjpy': float(fxv), 'usdjpy_src': fx_src,
        'fee_per_usd_purchase_pct': round(100 * f, 4),
        'usd_bought_share_of_target_pct': round(100 * usd_share, 1),
        'usd_share_note': f'目標（portfolio.json）のうち円の投資信託（{", ".join(sorted(funds))}）以外の ETF {usd_etf_w:g}%＋個別株 {castle:g}%（米国株・ADR が中心）をドルで買う分とした。',
        'irr_effect': e3,
        'note': '25銭は円貨決済で毎回、0銭はリアルタイム為替で先に両替してから外貨決済で買う場合。0銭でも業者間レートの売り買いの差は残る（大きさは未取得＝null）。'
                'repo の既存の置き値 FX_FEE=年0.02%（bestfund_data・newfunds）は 25銭を前提にした値で、上の買いだけの値とほぼ同じ。',
        'spread_on_0sen': None, 'spread_on_0sen_reason': '楽天は「業者間レートを採用・買レートと売レートに乖離」とだけ書き、幅を公表していない',
    }

    # ── E4 ──
    ob = read_order_book()
    prof = ((load_json('out/etf_profiles.json') or {}).get('etfs')) or {}
    etfs = ['SMH', 'ITA', 'SHLD', 'XLV', 'FBT', 'QQQM', 'XLK']
    dy = {t: (prof.get(t) or {}).get('dy') for t in etfs}
    y_target = sum(float(W.get(t, 0)) / 100 * float(dy[t]) for t in etfs if dy.get(t) is not None)
    st = load_json('state.json') or {}
    pfp = ((st.get('data') or {}).get('pf:portfolio'))
    if isinstance(pfp, str):
        pfp = json.loads(pfp)
    cur = None
    if isinstance(pfp, dict) and pfp.get('positions'):
        fx_s = float(pfp.get('fx') or 0)
        vals = {}
        for p in pfp['positions']:
            sh, px = float(p.get('sh') or 0), float(p.get('npx') or p.get('bpx') or 0)
            v = sh * px * (fx_s if p.get('ccy') != 'JPY' else 1)
            if v > 0:
                vals[str(p.get('t')).upper()] = v
        tot = sum(vals.values())
        hd = ((load_json('out/holdings_div.json') or {}).get('div')) or {}
        qd = ((dash.get('quotes')) or {})
        ycur_etf, ycur_stock, wts, ys = 0.0, 0.0, {}, {}
        for t, v in vals.items():
            w = v / tot
            wts[t] = round(100 * w, 1)
            if t in dy and dy[t] is not None:
                ys[t] = dy[t]
                ycur_etf += w * float(dy[t])
            else:
                ttm = (hd.get(t) or {}).get('ttm')
                q = qd.get(t) or {}
                px = q.get('px') if isinstance(q, dict) else None
                if ttm is not None and px:
                    ys[t] = round(float(ttm) / float(px), 5)
                    ycur_stock += w * ys[t]
                else:
                    ys[t] = None
        cur = {'asof': pfp.get('asof'), 'weights_pct': wts, 'yields': ys,
               'y_etf_part': round(ycur_etf, 5), 'y_stock_part': round(ycur_stock, 5), 'y_total': round(ycur_etf + ycur_stock, 5),
               'note': '比率は state.json の株数×npx（2026-09-23 の写真）。ETF の利回りは out/etf_profiles.json の dy、個別株は out/holdings_div.json の直近365日の配当÷'
                       'out/dashboard.json の株価（事前登録の ETF の一覧の外＝参考）。今の保有は全部ドル建て。'}
    sims = {}
    for nm, yv in (('目標の米国ETF（事前登録の主）', y_target), ('今の保有（ETF＋個別株・参考）', cur['y_total'] if cur else None)):
        if yv is None:
            sims[nm] = None
            continue
        sims[nm] = {'y_gross_pct': round(100 * yv, 3)}
        for r in (0.08, 0.12):
            sims[nm][f'r={int(r*100)}%'] = {f'{L}か月': idle_dividend_effect(yv, r, L) for L in (6, 12, 24)}
            sims[nm][f'r={int(r*100)}%']['最後まで使わない（参考）'] = idle_dividend_effect(yv, r, None)
    res['E4_usd_dividends'] = {
        'facts': FACTS['E4_dividends'],
        'order_book_reads': ob,
        'finding': (
            '注文書が配るお金は「今月の入金額」（localStorage pf:monthly_total を読む ccfTotalAmt）から iDeCo とこどもNISA の自動の積立を引いた '
            'ccfOrderAmt() だけ（renderPlan の中で TO=ccfOrderAmt() を ccfWholeShareBody に渡し、ccfCatSharePlan／ccfWholeSharePlan がその T だけを'
            '区分・銘柄に割る）。口座のドルや円の預り金・受け取った配当を読む欄は 🏦保有 の台帳（pf:portfolio の positions: t/sh/npx/bpx/ccy/v/sleeve…）にも'
            '注文書にも無い（index.html に「預り金」「外貨預り」は0件）。⇒ ドルで受け取った配当は、人が手で両替・買付するか入金額に足さない限り使われない。'
            '副作用: 🏦保有の編集で「現金」の行（portfolio.html の sleeve=cash）を手で入れると、ccfLedgerMap はその行を袖なし（城でも網でもない）として'
            '総資産（ccfPfLive の total＝区分の材料の tot）に足すので、各区分の目標額（目標%×総資産）が上がるが、その現金自体は配られない。'
        ),
        'yields_from_etf_profiles': dy, 'target_weights_pct': {t: float(W.get(t, 0)) for t in etfs},
        'y_target_portfolio_gross_pct': round(100 * y_target, 3),
        'current_holdings': cur,
        'model': '毎月同額を240か月。総リターン r（税引前の配当込み）。配当は源泉10%を引いて現金で入り（NISA なので日本の税は無し）、'
                 'L か月 0% で遊んでから再投資。基準は「受け取った月にすぐ再投資」。最後に残っている現金は額面で数える。L は平均の代わりに一定の遅れで置いた。',
        'idle_effect': sims,
    }
    deviations.append('E4: 「平均 6/12/24 か月遊ぶ」を、毎回ちょうど L か月遅れて再投資する一定の遅れで置いた（遅れの散らばりは入れていない）。')

    # ── E5 ──
    res['E5_emergency'] = FACTS['E5_emergency']
    deviations.append('E5: 楽天証券で買える円のマネーファンドは「楽天・マネーファンド（MRF）」。事前登録の「円の MMF」はこれで読み替えた。')

    # ── 判定（数字は上の結果から取る）──
    d1 = {C: tab[i]['r=8%']['drag_pt'] for i, C in enumerate((5000, 10000, 20000, 23000, 62000))}
    p05 = res['E2_card_points']['annualized']['一般カード 0.5%']['r=8%']['exact_pt']
    e3r = res['E3_fx']['irr_effect']['r=8%']
    sm = sims.get('目標の米国ETF（事前登録の主）') or {}
    e4vals = [sm[k][L]['terminal_diff_pct'] for k in ('r=8%', 'r=12%') for L in ('6か月', '12か月', '24か月') if k in sm]
    mm = FACTS['E5_emergency']
    decision = {
        'rule': '事前登録 groups.E_account_costs.decision: 事実と算術だけ。人の作業として todo に足す価値があるかを書く（足すのはユーザーに確かめてから）。',
        'E1': {'label': '事実と算術', 'todo_worth': True,
               'why': f'月5,000円では固定の手数料が年率 約{d1[5000]:.2f}pt（r=8%・毎月の手数料は掛金の{100*m_new/5000:.1f}%）。'
                      f'月1万円 {d1[10000]:.2f}pt・2万円 {d1[20000]:.2f}pt・2.3万円 {d1[23000]:.2f}pt・6.2万円 {d1[62000]:.2f}pt。'
                      '所得控除の効果がこの率を上回るかは個人の収入で決まる（ここでは計算しない）。'
                      '既存の todo ideco_raise_review_2028（掛金を上げるかの見直し）の材料としてこの表を添える価値がある。'
                      'もう一つは操作の確認: 最初の引き落としの後に配分指定が「楽天・プラス・NASDAQ-100 100%」になっているか（指定が無いと約4か月現金のあと'
                      '楽天・インデックス・バランス（DC年金）を買う）。既存の todo ideco_start_confirm に1行足す形が最小。'},
        'E2': {'label': '事実と算術', 'todo_worth': True,
               'why': f'iFreeNEXT NASDAQ100 は販売会社の取り分 {FC["iFreeNEXT_NASDAQ100"]["販売会社の取り分（代行手数料）"]["税込"]}%（税込）＝0.4%未満の帯で、'
                      '一般カード0.5%・ゴールド0.75%・プレミアム1%（ブラック2%）。月10万円まで・名義一致・こどもNISA と iDeCo は対象外。'
                      f'カード払いの積立設定にした分は内部収益率が 約{p05:+.3f}pt/年（0.5%・r=8%）。'
                      '小さいが設定1回で費用ゼロ。注文書の月ごとに変わる額とは噛み合わない（積立設定は固定額・スポット買いは対象外）ので、'
                      '固定の積立額をカードにして端数だけスポットで買う形にできるかの確認が要る。'
                      f'ゴールドは月約{be["ゴールド（年会費2,200円・一般より+0.25%）"]["損益分岐の月の積立_円"]:,}円以上でないと年会費の元が取れず、プレミアムは上限内では元が取れない。'},
        'E3': {'label': '事実と算術', 'todo_worth': True,
               'why': f'25銭は 1ドル{float(fxv):.1f}円で各買付の約{100*f:.3f}%＝ドルで買う分の内部収益率 {e3r["ドルで買う分_買いだけ_pt"]:+.4f}pt/年'
                      f'（出口も円貨なら {e3r["ドルで買う分_買い＋最後に円へ_pt"]:+.4f}pt）・ポートフォリオ全体で {e3r["ポートフォリオ全体_買いだけ_pt"]:+.4f}〜'
                      f'{e3r["ポートフォリオ全体_買い＋最後_pt"]:+.4f}pt/年（r=8%）。リアルタイム為替（0銭）で先に両替すれば消せる（業者間の売り買いの差は残る）。'
                      '1株単位の手動の買付の手順に「先に0銭で両替→外貨決済」を足すだけなので確認の todo の価値はあるが、優先は低い。'},
        'E4': {'label': '事実と算術', 'todo_worth': True,
               'why': '注文書は口座のドル（配当）を使わない（コードで確認・入金額だけを配る）。'
                      f'目標の米国 ETF の配当利回りは全体で年 約{100*y_target:.2f}%（税引前・iFreeNEXT 40% は分配なし）。'
                      + (f'遊ぶ期間が平均 6〜24 か月なら20年の最終額への効きは {max(e4vals):+.2f}〜{min(e4vals):+.2f}%（r=8〜12%）。' if e4vals else '')
                      + '小さいが、配当を「外貨建てMMFで受取り」にする設定（NISA の外の米ドルMMF に入る）や、配当のドルを次の米国 ETF の外貨決済の買付に充てる手順で消せる。'
                      'コードの変更は提案しない（人の手順の確認として todo の価値はある・優先は低い）。'},
        'E5': {'label': '事実のみ', 'todo_worth': False,
               'why': f'置き場所の利率（税引前）: 普通預金 {mm["楽天銀行 普通預金"]["金利_税引前"]}%・マネーブリッジ {mm["楽天銀行 マネーブリッジ（優遇金利1）"]["金利_税引前"]["1円〜1,000万円"]}%'
                      f'・楽天・マネーファンド（MRF）{mm["楽天・マネーファンド（MRF・楽天証券）"]["年利回り_税引前_信託報酬控除後"]}%（7日間の実績・元本保証なし）'
                      f'・個人向け国債 変動10年 第199回 {mm["個人向け国債 変動10年（第199回）"]["初回の利率_税引前"]}%（発行から1年は換金不可・その後は直前2回分の利子×0.79685 で換金）。'
                      '額は書かない。既存の todo ideco_prestart_checks（生活防衛資金）があるので新しい todo は要らず、そこにこの表を参照として添えれば足りる。'},
    }

    caveats += [
        '一次資料の値は 2026-10-14 の取得。手数料・金利・還元率は予告なく変わる（国基連は 2026年12月分から 105→120円に上げたところ）。',
        'E1 の年率の費用は手数料だけ（ファンドの信託報酬・実際の費用は別）。所得控除の効果・受け取りの税は個人の収入と退職金に依るので計算しない（ルール9）。',
        'E1 の基準価額の窓は短い（楽天・プラスは2年8か月）。過去の騰落率は将来の予想ではない。楽天・インデックス・バランス（DC年金）は株と為替ヘッジ付きの債券の分散型で、'
        'NASDAQ100 とは別の賭け（比べているのは「指定を忘れたときに何が起きたか」）。',
        'E4 の配当利回りは out/etf_profiles.json の dy（日付は本ごと・2026-08〜10）。利回りは動く。個別株（目標15%）の配当は事前登録の一覧の外なので主には入れず、'
        '今の保有の参考の行にだけ入れた（ASML は源泉が10%でなくオランダ15%だが、ここでは一律10%で置いた）。',
        'E4 の効きは配当の現金が 0% で遊ぶ前提。米ドルMMF に自動で入れれば利回りが付く（楽天の米ドルMMF の利回りは未取得）。',
        'E3 の 0銭でも業者間レートの売り買いの差は残る（幅は非公表）。円貨決済でSPU（楽天市場のポイント倍率）の条件を満たす場合の取り分は測っていない。',
    ]

    doc = {
        'generated': datetime.date.today().isoformat(),
        'tool': 'night/unx_account.py',
        'prereg': PREREG,
        'question': 'groups.E_account_costs（器の外の費用と取り分: iDeCo の固定の手数料・カード積立のポイント・為替の手数料・使われないドルの配当・緊急の資金の置き場所）',
        'inputs': {
            'facts_accessed': ACCESS,
            'sources': sorted({v for v in globals().values() if isinstance(v, str) and v.startswith('https://')}),
            'repo_files_read': ['index.html（注文書のコード）', 'portfolio.html（🏦保有の編集の現金の行）', 'portfolio.json（target）', 'state.json（保有の写真）',
                                'out/etf_profiles.json（dy）', 'out/holdings_div.json', 'out/dashboard.json（ドル円・株価）'],
            'nav_cache': os.path.relpath(CACHE, BASE) if CACHE.startswith(BASE) else '（スクラッチ・UNX_CACHE）',
            'data_end': DATA_END,
        },
        'results': res,
        'decision': decision,
        'deviations': deviations,
        'caveats': caveats,
        'runtime_sec': round(time.time() - t0, 1),
    }
    json.dump(doc, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'→ {OUT}  ({doc["runtime_sec"]}s)', file=sys.stderr)


if __name__ == '__main__':
    main()
