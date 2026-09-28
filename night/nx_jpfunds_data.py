#!/usr/bin/env python3
"""night/nx_jpfunds_data.py — nx 角度 jpfunds（日本の投資信託の全体）の **取得と整形だけ**
（成績は計算しない・表示しない・読むだけ・門の判定には不使用）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて勝てる結果を出して…
別のSessionで検証していない新たな分析を同じ内容でしてほしい」。
事前登録: out/nx_jpfunds_prereg.json（測る前に固定）／全体の線: out/nx_prereg.json（criteria_short_sample）。

データ（2026-09-28 に実際に確かめた形）
  1. 資産運用業協会（旧 投資信託協会）の投信総合検索ライブラリー
     - 検索API  POST /FdsWeb/FDST999900/fundDataSearch（JSON）。トップ /FdsWeb/FDST000000 を先に読んで
       セッションを作らないと『不正操作エラー』。★pageSize を 1000 にすると1回で1000本返る（画面は20本）。
       条件なしの検索で 5,845本（基準日 2026-09-28）＝**今運用中の公募投信だけ**（ETF 424本を含む）。
     - 基準価額の履歴 CSV  GET /FdsWeb/FDST030000/csv-file-download?isinCd=<ISIN>&associFundCd=<協会コード>
       Shift_JIS（cp932）・列は 年月日／基準価額(円)／純資産総額（百万円）／分配金／決算期。
       ★鍵は協会コード（isinCd は空でなければ何でも通る。違う協会コードを渡すと別のファンドの履歴が返る）。
       ★履歴は **2006-09-29 より前が無い**（1961年設定の公社債投信も 1985年設定の 225 も CSV は 2006-09-29 から）。
     - ★**償還済みのファンドは取れない**: 検索に出ない（redemptionDate が過去の行は 0本）。三菱UFJアセットマネジメントが
       自社サイトで公表している償還ファンドの協会コードで CSV を叩くと、2021-02〜2026-03 に償還した11本はすべて HTTP 500、
       2026-09-08 に償還した1本（20日前）だけまだ返った＝償還後しばらくで消える。
       ⇒ このライブラリーの母集団は **生き残りだけ**（2009年末に運用中だった株式投信〔追加型・ETF 除く〕のうち
       今も残るのは約 48%）。生き残りの偏りの大きさは JITA の本数の統計から数える（下の jita_survival）。
  2. 投資信託協会の統計（/tws/toukei_dw/I0112B_pub_y.xlsx: 公募投信の資産増減状況・年次・ファンド数）
     → 年末の『株式 追加型』−『株式 追加型 ＥＴＦ』の本数。ライブラリーの生き残りの本数と割って、
       その年に居たファンドが今まで残った割合 s(t) と、年あたりの償還率 q(t)=1−s^(1/年数) を作る（本数だけ・成績ではない）
  3. 三菱UFJアセットマネジメントの償還ファンド一覧（/mukamapi/fund_repayment/?site_type=1・2021-02〜2026-09 の244本・
     協会コード／ISIN／設定日／分類）と、その各ファンドの基準価額の全履歴（/fund_file/chart/chart_data_<ファンドコード>.js・
     BASE_PRICE と PROFIT_DISTRIBUTION）＝**生き残りの偏りを1社・5年だけ直に測る**ための部分標本（報告）
  4. MSCI の指数（円・配当込み〔NETR〕・月末）: app2.msci.com の getLevelDataForGraph（2000-12〜）。
     紙の相手（報告）と、同じ分類の指数型の投信がまだ無い年の代わり（主の相手の補欠・固定の費用を引く）
       Japan 939200 / USA 984000 / Kokusai（World ex Japan）991200 / ACWI 892400 / EM 891800
  5. AQR の時系列の勢い（nx_common.aqr_sheet・米ドルの超過）: 報告の族の『紙との差』だけ

使い方
  python3 night/nx_jpfunds_data.py --universe   → 全ファンドの一覧（成績の欄は捨てる）を凍結して out/_nx_cache/nx_jpfunds_universe.json
  python3 night/nx_jpfunds_data.py --nav        → 対象の全ファンドの CSV を out/_nx_cache/nx_jpfunds_nav/ へ（1.1秒あけ・取得済みは飛ばす）
  python3 night/nx_jpfunds_data.py --support    → MSCI・JITA・三菱UFJ の償還ファンドを取得
  python3 night/nx_jpfunds_data.py --show       → 形だけ（本数・期間・欠け・分類・相手の割り当て・生き残りの割合）
  python3 night/nx_jpfunds_data.py --sha        → extract_sha256 / rules_sha256 / universe_sha256 を表示

約束（成績を見ないための）
  - 検索の応答の成績の欄（騰落率・リスク・シャープ・順位・資金流出入・分配金の実績・純資産）は **保存しない**。
  - このファイルは月次の総リターンを作る関数（monthly_tr）を持つが、平均・t・累積などの成績の要約は作らない・表示しない。
"""
import sys, os, re, io, json, time, math, hashlib, datetime, unicodedata, urllib.request, urllib.error, http.cookiejar

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as N  # noqa: E402

LIB = 'https://toushin-lib.fwg.ne.jp'
UNIV = os.path.join(N.CACHE, 'nx_jpfunds_universe.json')
NAVDIR = os.path.join(N.CACHE, 'nx_jpfunds_nav')
SUPPORT = os.path.join(N.CACHE, 'nx_jpfunds_support.json')
MUFGDIR = os.path.join(N.CACHE, 'nx_jpfunds_mufg')
CUTOFF = 20260831          # 評価に使う最後の日（最後の完全な月末）。これより後の行は hash にも測定にも入れない
ARRAY_FIELDS = ['s_investAssetKindCd', 's_investArea3kindCd', 's_instCd', 's_fdsInstCd', 's_dcFundCD', 't_investArea10kindCd',
                't_investAssetKindCd', 't_instCd', 't_fdsInstCd', 's_investArea10kindCd', 's_setlFqcy', 's_dividend1y',
                's_totalNetAssets', 's_nowToRedemptionDate', 's_establishedDateToNow', 's_isinCd']
# 検索の応答のうち成績に当たる欄（保存しない）
PERF_KEYS = re.compile(r'(standardPrice|risk|sharp|rank|returnRa|stdCost|monthlyCancel|dividend|totalNetAssets|evalDiscrep|renzokuCancel)', re.I)


def nfkc(s):
    return unicodedata.normalize('NFKC', s or '')


# ═════════════════════════ 規則の台帳（測る前に固定・測る道具は import する） ═════════════════════════
RULES = {
    'version': '2026-09-28',
    'universe_filter': {
        'open_end': "unitOpenDiv == '2'（追加型。単位型は除く）",
        'not_etf': "isinCd が 'JP3' で始まらない かつ fundCategory != '10'（上場投信を除く）",
        'dc_only_excluded': "dcFundFlg == '1'（確定拠出年金の専用）は主の母集団から除く（この投資家は買えない）。'2'（DC と一般の両方）と '9'（一般）は入れる",
        'wrap_only_regex': r'(SMA|ラップ|EW向け|ファンドラップ|適格機関|私募)',
        'dc_name_regex': r'(DC|確定拠出|年金)',
        'dc_name_note': 'dc_name_regex は fundNm（愛称は含めない）だけに当て、当たれば DC 専用とみなして除く（dcFundFlg の印が無いか 2/9 でも、年金積立・野村DC・(確定拠出年金向け)・(個人型年金向け) のような器は NISA・課税口座で買えない）',
        'special_regex': r'(ブル(?!ー)|ベア(?!リング)|レバレッジ|インバース|[2-9]倍|ダブル|トリプル|ブースト|価格変動抑制|リスク抑制|マーケット・ニュートラル|マーケットニュートラル|プライムニュートラル|ロング・ショート|ロングショート|絶対収益)',
        'hedged_regex': r'(ヘッジあり|ヘッジ有|為替ヘッジ付|円ヘッジ|ヘッジ型|\(H\)|ヘッジコース|米ドル売り円買い|為替ヘッジ\))',
        'currency_course_regex': r'(レアル|リラ|豪ドル|南アフリカ|ランドコース|ペソ|ルピー|ルピア|ルーブル|アジア通貨|資源国通貨|バスケット通貨|通貨コース|米ドルコース|ユーロコース|人民元|中国元|ドル投資型)',
        'yen_course_foreign': "名前に『円コース』があり分類が JP 以外なら為替ヘッジありとみなして除く（通貨選択型の円コースは外国の資産を円へヘッジした形。JP の円コースは通貨の上乗せが無い素の日本株なので残す）",
        'special_kind': "supplementKindCd == '2'（特殊型）は除く",
        'fx_exposure_check': "外国の4分類（US/GLX/GLW/EM）では、名前に出ない為替ヘッジ（野村の Aコース/Bコース など）を振り返りの月次で見分ける: 選択の日 t ごとに、そのファンドの振り返りの月次リターンを MSCI の同じ分類の指数の米ドル建て（NETR）と、円／米ドルの変化（MSCI World の円建てと米ドル建ての比から作る）の二つに最小二乗で回帰し、円／米ドルの係数が 0.5 未満なら『ヘッジあり』とみなしてその年は並べない。振り返りの月だけを使う（後知恵なし）。相手の指数型と報告の族の外国の器にも同じ検査を当てる",
        'name_is_nfkc': 'すべての名前の照合は NFKC（全角→半角）にした fundNm＋fundNkNm（愛称）に対して行う',
    },
    'categories': {
        'JP': "fundCategory == '1'（国内株式）",
        'US': "fundCategory == '4'（海外株式）かつ 地域の印が北米だけ（investArea10kindCd3 == '1'・他は '0'）",
        'GLX': "fundCategory == '4' かつ 地域の印がグローバルだけ（investArea10kindCd1 == '1'・他は '0'）＝日本を除く世界",
        'GLW': "fundCategory == '7'（内外株式）かつ 地域の印がグローバルだけ＝日本を含む世界",
        'EM': "fundCategory == '4' かつ 地域の印がエマージングだけ（investArea10kindCd10 == '1'・他は '0'）",
        'others': '上の5つに入らない分類（欧州・アジア・単一国・債券・REIT・資産複合など）は主の母集団に入れない',
    },
    'kind': {
        'active': "supplementKindCd == '0'",
        'index': "supplementKindCd == '1'",
    },
    'comparator': {
        'what': '同じ分類の指数型の投信（円・費用後の本物の器）。選択の日 t ごとに、下の名前の規則を満たし t の時点で基準価額がある指数型のうち、今の信託報酬（trustReward・税抜）が最も安いもの（同じなら設定が古いもの）を1本選び、次の選択の日まで持つ',
        'eligible': "kind == index かつ universe_filter をすべて通る（為替ヘッジあり・DC 専用・SMA/ラップ専用・特殊型は相手にしない）",
        'name_include': {
            'JP': ['TOPIX', 'トピックス'],
            'US': ['S&P500', 'S&P 500', 'S&P・500'],
            'GLX': ['先進国', 'コクサイ', '外国株式'],
            'GLW': ['全世界', 'オール・カントリー', 'オールカントリー', 'ACWI'],
            'EM': ['新興国', 'エマージング'],
        },
        'name_exclude': ['配当', '貴族', 'バリュー', 'グロース', '小型', '中型', '中小型', 'ESG', 'SRI', 'クオリティ', 'Core30', 'コア30',
                         'TOPIX100', 'TOPIX500', '除く', '均等', 'リート', 'REIT', '債券', 'バランス', '3地域', '4資産', '8資産',
                         'トップ', 'テック', 'テクノロジー', 'ゴールド', 'プラス', 'モメンタム', 'ファクター', 'アジア', 'インド', '中国'],
        'fallback': '指数型が1本も無い分類の選択年は、MSCI の円・配当込み（NETR）の月次リターン − 年0.50%/12（固定の費用・2009〜2013年ごろの外国株の指数型の信託報酬の目安）。JP=939200 / US=984000 / GLX=991200 / GLW=892400 / EM=891800',
        'why_current_fee': '過去の信託報酬の履歴はライブラリーに無い（今の値だけ）。今いちばん安い器を選ぶのは後知恵で相手を強くする向き（能動の側に不利＝保守的）。基準価額は当時の実際の費用を引いた後の値なので、成績そのものに後知恵は入らない',
    },
    'returns': {
        'monthly_total_return': '月末＝その月の最後の基準価額の日。日次の総リターン (基準価額_d + 分配金_d) ÷ 基準価額_(d−1) − 1 を月内で掛け合わせる（分配金は税引前・その日の基準価額で再投資）',
        'missing': '前の基準価額の日から31日を超えて空いたら、その間の月は値なし（0 と読まない）。値なしの月はその月の平均から外して残りで割り直す',
        'cutoff': '2026-08-31 まで（途中の 2026-09 は使わない）',
        'fund_first_month': 'CSV の最初の日を含む月は使わない（月の途中から始まるため）。履歴の最初は 2006-09-29 なので、最初に使える月は 2006-10',
    },
    'selection': {
        'dates': '毎年9月の最後の基準価額の日（2006-09-29 の履歴の始まりに合わせる）。3年の振り返りは 2009-09 から 2025-09 まで17回、5年は 2011-09 から 2025-09 まで15回',
        'eligible_at_t': 'kind == active かつ universe_filter を通る かつ 分類が5つのどれか かつ t−L年の9月末から t まで L×12 か月すべての月次リターンがある',
        'lookback_score': '振り返りの累積の総リターン Π(1+r)−1（費用後＝信託報酬を引いた後の基準価額・分配金再投資）。同じ分類の中だけで並べる',
        'share_class_dedupe': '同じ委託会社（協会コードの先頭2文字）で、振り返りの月次リターンの相関が 0.995 以上の組は同じ親ファンドの別コース（毎月分配型・年1回決算型など）とみなし、t の純資産（CSV の純資産総額）が最大の1本だけ残す（単連結でつなぐ）。並べる前に行う',
        'min_group': '重複を除いた後の対象が 8本未満の分類・年は、その年その分類を使わない（空欄を 0 と読まない）',
        'top_quartile': 'k = ceil(n/4) 本（n は重複を除いた後の本数）。同点は純資産の大きい順',
        'holding': '選んだ翌月から次の選択の月まで12か月（最後は 2025-10〜2026-08 の11か月）。月ごとに等分で持ち直す（ファンドの単位で等分・分類で割らない）',
        'fund_excess': '各ファンドの月次の超過 = そのファンドの総リターン − その分類の相手の総リターン。s_t = 選んだファンドの総リターンの平均、b_t = 同じ重みでのそれぞれの相手の平均（excess_stats(s, b)）',
    },
    'costs': {
        'buy': '保有に新しく入ったファンドの月（組み入れの最初の月）に、今の販売会社のうち最も安い購入時手数料（institutionInfo の salesFee の最小・税抜）×1.1（消費税）を引く。最初の年はすべてが新しく入ったものとして引く',
        'sell': '保有から外れたファンドには、信託財産留保額の印（retentionMoneyCd が 1 以外）があれば 0.3% を外れる月に引く（料率はライブラリーに無いので固定の置き値）',
        'comparator': '相手も同じ規則（相手の器が替わった年に新しい器の購入時手数料・古い器の留保額）',
        'per_month_weight': '費用はその月のポートフォリオの重み（1/n）を掛けて月の超過から引く',
        'report_max': '報告: 購入時手数料を上限（buyFee）で引く版・手数料なしの版',
        'tax_report': '報告（課税口座）: 分配金に 20.315% を払った日に課税（全額を普通分配金とみなす・悲観側）、組み替えで外れたファンドの含み益に 20.315%、最後の月に全部を売ったとして課税。相手も同じ。NISA の中は課税なし＝主の結果',
    },
    'lower_bound': {
        'why': 'ライブラリーは生き残りだけ。選んだ上位のファンドのうち、その後に崩れて償還された分が母集団から消えている＝能動の側に有利な偏り',
        'rule': '保有年 y（y 年10月〜翌9月）の各月の超過から h_y/12 を引く。h_y = q_y × 0.30。q_y = 1 − s^(1/T)、s = ライブラリーの生き残りのうち (y−1) 年末までに設定された本数 ÷ JITA の (y−1) 年末の『株式 追加型』−『株式 追加型 ＥＴＦ』の本数、T = (y−1) 年末から 2026-09-28 までの年数。＝その年に償還された割合の選んだファンドが、償還の月に −30%（hbm38n の ev5 と同じ −30%）',
        'mild_report': '報告: h_y = q_y × 0.10',
        'counts_universe': "ライブラリー側は unitOpenDiv == '2' ∧ ISIN が JP3 でない ∧ 名前に 公社債投信/MMF/MRF/中期国債 を含まない（JITA の『株式投信』に合わせる）",
    },
    'families': {
        'P': {
            'role': '主の族（criteria_short_sample で格付け・Holm は P の2本で）',
            'P1_top_q_3y': '振り返り3年・上位1/4・12か月保有・5分類をまとめて・相手は分類ごとの指数型の投信。評価 2009-10〜2026-08（203か月）',
            'P2_top_q_5y': '振り返り5年・上位1/4・同じ。評価 2011-10〜2026-08（179か月）',
        },
        'C': {
            'role': '対照の族（格付けはするが『対照』と明記・Holm は C の3本で）',
            'C1_cheap_q_fee': '同じ選択の日・同じ適格（振り返り3年がそろう能動の投信・重複を除いた後）のうち、今の信託報酬（trustReward）が安い1/4（k = ceil(n/4)・同じなら純資産の大きい順）。評価 2009-10〜2026-08。★今の信託報酬で過去を選ぶ後知恵（能動の投信の信託報酬はあまり変わらないが、下げた器が上に来る）',
            'C2_all_active': '同じ適格の能動の投信を全部等分（上位を選ぶことに意味があるかの基準）。評価 2009-10〜2026-08',
            'C3_bottom_q_3y': '振り返り3年の下位1/4（Carhart の持続の反対側）。評価 2009-10〜2026-08。★生き残りの偏りは下位にいちばん強く効く（下位で崩れたファンドほど償還される）',
        },
        'X': {
            'role': '探索の族（格付けはするが『探索』と明記・Holm は X の4本で・主の結論には使わない）',
            'X1_top_q_1y': '振り返り1年（Carhart 1997 の元の形）。選択 2007-09〜2025-09・評価 2007-10〜2026-08',
            'X2_top_q_3y_ir': '振り返り3年の、相手に対する月次の超過の平均 ÷ 超過の標準偏差（情報比）の上位1/4',
            'X3_top_q_3y_big': 'P1 と同じだが、t の純資産が 100億円以上のファンドだけで並べる（償還されにくい器）。min_group と ceil(n/4) は同じ',
            'X4_top_d_3y': '振り返り3年の上位1/10（k = ceil(n/10)・最低2本）',
        },
        'R': {
            'role': '報告（格付けしない）',
            'R1_by_category': 'P1・P2・C1・C2 を分類ごと（JP/US/GLX/GLW/EM）に',
            'R2_spread': 'P1 − C3（上位1/4 − 下位1/4＝Carhart の持続の差）',
            'R3_paper': '相手を MSCI の円・配当込み（費用なし）にした版と、相手を分類の指数型の全部の等分にした版と、相手の器を今の販売会社が5社以上のもの（nInstitutions ≥ 5）に限った版（野村スリーゼロ先進国株式投信〔信託報酬 0%・販売会社1社〕のような、多くの投資家が買えない器を相手にしない感度）',
            'R4_costs': '購入時手数料の上限版・手数料なし版・課税口座の版（costs.tax_report）',
            'R5_lower_mild': 'lower_bound の mild_report',
            'R6_dca': '20年がそろわないので、毎月同額の積立の最終額の比（規則 ÷ 相手）を 10年窓（nx_common.dca(years=10)）で',
            'R7_comparator_drag': '相手の指数型の投信 − MSCI の紙（指数型の器の費用と追従のずれ）',
            'R8_fund_count': '選択の日ごとの分類別の本数（重複を除く前・後）・選ばれた本数・相手の器の名前と信託報酬・為替の係数の検査で外した本数・今の NISA の印（成長投資枠 nisaGrowthFlg・つみたて投資枠 nisaFlg）の割合',
            'R9_single_alternative': '選んだファンドの平均 − （MSCI ACWI の円・NETR − 0.10%/年）＝日本の NISA の投資家の典型の代わり（オール・カントリーの指数型）ひとつと比べる',
        },
        'B': {
            'role': '生き残りの偏りの部分的な答え合わせ（報告・格付けしない）。三菱UFJアセットマネジメントの2021-02〜2026-09 の償還ファンド（全履歴が同社のサイトにある）を足し戻す',
            'B1_add_back_mufg': 'P1・P2・C2・C3 を選択 2021-09〜2025-09 に限り、(a) ライブラリーの生き残りだけ と (b) (a) に三菱UFJの償還ファンドを分類の規則（mufg_category）で足し戻した版を並べる（差＝1社ぶんの生き残りの偏り）',
            'B2_mufg_only': '母集団を三菱UFJの能動の投信だけにして、(a) 生き残りだけ と (b) 償還も含む（2021-09 以降の選択では完全な母集団）を並べる',
            'mufg_filter': "universe_filter の正規表現（wrap/special/hedged/currency）＋ 外国の資産の円コース ＋ 名前に DC/確定拠出（MUFG の一覧に DC の印が無いため）＋ 名前に 上場投信 か cff_type が PublicFund 以外（ETF・DC 型）を除く。為替の係数の検査（fx_exposure_check）も同じく当てる",
            'mufg_category': "MUFG の cff_fund_type_name が 国内株式 → JP。海外株式 → 名前に 米国/北米/アメリカ/S&P/ダウ/NASDAQ/ナスダック → US、新興国/エマージング/BRICs/ブリックス → EM、先進国/グローバル/世界/外国/海外/コクサイ → GLX、それ以外（単一国・地域）は入れない。内外株式 → 名前に グローバル/世界/全世界/オール → GLW。名前に インデックス → 指数型（能動から外す）。universe_filter の正規表現も同じく当てる",
        },
        'Q': {
            'role': '報告の族（格付けしない）。★nx の他の角度（nx_stack の時系列の勢い・nx_jst の高配当の国・nx_brand のブランド）が紙の上で勝ったと聞いた**後に**決めた後知恵の答え合わせ',
            'membership': 'ライブラリーの今の一覧から名前（NFKC の fundNm＋愛称）で機械的に拾う。universe_filter の DC 専用・SMA/ラップ専用・為替ヘッジあり・通貨選択は除く（特殊型は MF のために残す）。12か月以上の月次がある器だけ',
            'Q1_managed_futures': "名前に マネージド・フューチャーズ / マネージドフューチャーズ / フューチャーズ / トレンドフォロー / トレンド・フォロー / AHL / CTA / ウィントン / アルファシンプレックス / トレンド戦略 / リキッド・トレンド のどれか ∧ fundCategory が '11'（資産複合）か空欄（その他資産）。相手 = GLW の相手（全世界の指数型）と、円の現金（0%）。紙との差 = 同じ月の AQR TSMOM（米ドルの超過・為替ヘッジした円の超過の近似）",
            'Q2_brand': "名前に ブランド ∧ 分類が JP/US/GLX/GLW/EM のどれか。相手 = その分類の相手",
            'Q3_high_dividend_foreign': "名前に 高配当 ∧ 分類が US/GLX/GLW/EM（国内株式は q07leu の verify_japan_yen_etf〔18本〕と eknzbh の mw_investable_valmom が既に測ったので外す）。相手 = その分類の相手。★nx_jst の『高配当の国（国を選ぶ）』とは別物（これは国の中の銘柄を選ぶ）",
            'Q3b_high_dividend_domestic_crosscheck': '名前に 高配当 ∧ JP。他セッションと重なるので答え合わせの検算としてだけ（結論に使わない）',
            'portfolio': '各グループの器を、器の2か月目から等分（月ごとに持ち直す）。器ごとの超過も一覧にする',
        },
    },
    'evaluation': {
        'grade': 'nx_common.grade_short(full, first_half, second_half, drop_top, cost_full, lower_bound, family_holm_p_one)',
        'halves': '評価の月を数で半分（奇数なら後半に1か月多く）',
        'drop_top': '評価の全期間で寄与 Σ_t w_{i,t}·(r_{i,t} − b_{i,t}) が最大の1本（重複を除いた後のファンド）を全期間から除き、残りで割り直す',
        'holm': '族ごとに片側 p で Holm（P 2本・C 3本・X 4本）',
    },
}

MSCI = {'JP': 939200, 'US': 984000, 'GLX': 991200, 'GLW': 892400, 'EM': 891800}
FALLBACK_FEE = 0.005


def rules_sha():
    return hashlib.sha256(json.dumps(RULES, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


# ═════════════════════════ 取得 ═════════════════════════
class Lib:
    """投信総合検索ライブラリー（セッションを作ってから叩く）。UA に個人の連絡先を載せない（nx_common.UA）"""
    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.op.addheaders = [('User-Agent', N.UA['User-Agent'])]
        self.op.open(LIB + '/FdsWeb/FDST000000', timeout=60).read()

    def search_all(self, page=1000):
        rows, start, total = [], 0, None
        while True:
            body = {f: [] for f in ARRAY_FIELDS}
            body.update({'startNo': start, 'draw': 1, 'searchBtnClickFlg': True, 'pageSize': page})
            req = urllib.request.Request(LIB + '/FdsWeb/FDST999900/fundDataSearch', data=json.dumps(body).encode(),
                                         headers={'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest',
                                                  'Referer': LIB + '/FdsWeb/FDST999900', 'User-Agent': N.UA['User-Agent']})
            d = json.loads(self.op.open(req, timeout=120).read().decode())
            info = d.get('searchResultInfo') or {}
            got = info.get('resultInfoMapList') or []
            total = int(info.get('recordsTotal') or 0)
            std = info.get('standardDate')
            rows += got
            start += len(got)
            if not got or start >= total:
                return rows, total, std
            time.sleep(1.0)

    def csv(self, isin, assoc, tries=4):
        u = f'{LIB}/FdsWeb/FDST030000/csv-file-download?isinCd={isin}&associFundCd={assoc}'
        err = None
        for i in range(tries):
            try:
                return self.op.open(u, timeout=120).read()
            except urllib.error.HTTPError as e:
                if e.code == 500:
                    return None   # 償還済み・存在しない（再試行しても同じ）
                err = e
            except Exception as e:  # noqa
                err = e
            time.sleep(2 ** (i + 1))
        raise RuntimeError(f'CSV 取得失敗 {assoc}: {err}')


def strip_row(r):
    """検索の1行から成績の欄を捨てる。販売会社の手数料は最小だけ残す（費用の置き値）"""
    out = {k: v for k, v in r.items() if not PERF_KEYS.search(k) and k not in ('institutionInfo', 'settlementInfo')}
    fees = []
    for x in r.get('institutionInfo') or []:
        try:
            fees.append(float(x.get('salesFee')))
        except (TypeError, ValueError):
            pass
    out['salesFeeMin'] = min(fees) if fees else None
    out['nInstitutions'] = len(r.get('institutionInfo') or [])
    return out


def build_universe():
    lib = Lib()
    rows, total, std = lib.search_all()
    kept = [strip_row(r) for r in rows]
    doc = {'fetched_at': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'), 'standardDate': std, 'recordsTotal': total,
           'n': len(kept), 'note': '成績の欄（騰落率・リスク・シャープ・順位・資金流出入・分配金の実績・純資産）は保存していない',
           'rows': sorted(kept, key=lambda r: r['associFundCd'])}
    os.makedirs(N.CACHE, exist_ok=True)
    json.dump(doc, open(UNIV, 'w'), ensure_ascii=False)
    return doc


def load_universe():
    return json.load(open(UNIV))


# ═════════════════════════ 分類 ═════════════════════════
_RX = {k: re.compile(RULES['universe_filter'][k]) for k in ('wrap_only_regex', 'special_regex', 'hedged_regex', 'currency_course_regex')}
_DCNAME = re.compile(RULES['universe_filter']['dc_name_regex'])


def name_of(r):
    return nfkc(r.get('fundNm')) + ' ' + nfkc(r.get('fundNkNm'))


def area_flags(r):
    return tuple(i for i in range(1, 11) if r.get(f'investArea10kindCd{i}') == '1')


def category(r):
    c, f = r.get('fundCategory'), area_flags(r)
    if c == '1':
        return 'JP'
    if c == '4' and f == (3,):
        return 'US'
    if c == '4' and f == (1,):
        return 'GLX'
    if c == '4' and f == (10,):
        return 'EM'
    if c == '7' and f == (1,):
        return 'GLW'
    return None


def flags(r):
    nm = name_of(r)
    return {
        'open_end': r.get('unitOpenDiv') == '2',
        'etf': (r.get('isinCd') or '').startswith('JP3') or r.get('fundCategory') == '10',
        'dc_only': r.get('dcFundFlg') == '1' or bool(_DCNAME.search(nfkc(r.get('fundNm')))),
        'wrap_only': bool(_RX['wrap_only_regex'].search(nm)),
        'special_name': bool(_RX['special_regex'].search(nm)),
        'hedged': bool(_RX['hedged_regex'].search(nm)) or ('円コース' in nm and category(r) != 'JP'),
        'currency_course': bool(_RX['currency_course_regex'].search(nm)),
        'special_kind': r.get('supplementKindCd') == '2',
    }


def passes_filter(r, allow_special=False):
    f = flags(r)
    if not f['open_end'] or f['etf'] or f['dc_only'] or f['wrap_only'] or f['hedged'] or f['currency_course']:
        return False
    if not allow_special and (f['special_name'] or f['special_kind']):
        return False
    return True


def kind(r):
    return {'0': 'active', '1': 'index'}.get(r.get('supplementKindCd'), 'other')


def comparator_candidates(rows, cat):
    inc = RULES['comparator']['name_include'][cat]
    exc = RULES['comparator']['name_exclude']
    out = []
    for r in rows:
        if category(r) != cat or kind(r) != 'index' or not passes_filter(r):
            continue
        nm = name_of(r)
        if any(nfkc(k) in nm for k in inc) and not any(nfkc(k) in nm for k in exc):
            out.append(r)
    return out


REPORT_Q = {
    'Q1_managed_futures': (['マネージド・フューチャーズ', 'マネージドフューチャーズ', 'フューチャーズ', 'トレンドフォロー', 'トレンド・フォロー', 'AHL', 'CTA',
                            'ウィントン', 'アルファシンプレックス', 'トレンド戦略', 'リキッド・トレンド'], ('11', None)),
    'Q2_brand': (['ブランド'], 'cat5'),
    'Q3_high_dividend_foreign': (['高配当'], ('US', 'GLX', 'GLW', 'EM')),
    'Q3b_high_dividend_domestic_crosscheck': (['高配当'], ('JP',)),
}


def report_members(rows):
    out = {}
    for q, (kws, where) in REPORT_Q.items():
        mem = []
        for r in rows:
            if not passes_filter(r, allow_special=(q == 'Q1_managed_futures')):
                continue
            nm = name_of(r)
            if not any(nfkc(k) in nm for k in kws):
                continue
            if q == 'Q1_managed_futures':
                if r.get('fundCategory') not in where:
                    continue
            elif where == 'cat5':
                if category(r) is None:
                    continue
            elif category(r) not in where:
                continue
            mem.append(r['associFundCd'])
        out[q] = sorted(mem)
    return out


def needed_codes(rows):
    """CSV を取る器: 5分類の能動・指数型（主・対照・探索・相手）＋ 報告の族の器。DC 専用・ヘッジありなどは母集団から外すが、形の確認のため5分類のものは全部取る"""
    need = {r['associFundCd']: r['isinCd'] for r in rows if category(r) and kind(r) in ('active', 'index') and r.get('unitOpenDiv') == '2'
            and not flags(r)['etf']}
    rm = report_members(rows)
    by = {r['associFundCd']: r for r in rows}
    for q, codes in rm.items():
        for c in codes:
            need[c] = by[c]['isinCd']
    return need


# ═════════════════════════ 基準価額 ═════════════════════════
def nav_path(assoc):
    return os.path.join(NAVDIR, f'{assoc}.csv')


def fetch_navs(codes, sleep=1.1, log_every=100):
    os.makedirs(NAVDIR, exist_ok=True)
    lib = Lib()
    miss, done = [], 0
    for i, (assoc, isin) in enumerate(sorted(codes.items())):
        p = nav_path(assoc)
        if os.path.exists(p) and os.path.getsize(p) > 0:
            continue
        b = lib.csv(isin, assoc)
        if b is None:
            miss.append(assoc)
            open(p + '.missing', 'w').write('HTTP 500')
        else:
            tmp = p + '.tmp'
            open(tmp, 'wb').write(b)
            os.replace(tmp, p)
        done += 1
        if done % log_every == 0:
            print(f'  {done} 本取得（{i + 1}/{len(codes)}）', file=sys.stderr)
        time.sleep(sleep)
    return miss


def parse_csv(b):
    """→ [(yyyymmdd, 基準価額, 純資産(百万円) or None, 分配金 or 0.0)]（CUTOFF まで・日付順）。基準価額が読めない行は捨てて数える"""
    t = b.decode('cp932', errors='replace')
    out, bad = [], 0
    for line in t.splitlines()[1:]:
        x = line.split(',')
        if len(x) < 2 or not x[0].strip():
            continue
        m = re.match(r'(\d{4})年(\d{2})月(\d{2})日', x[0].strip())
        if not m:
            bad += 1
            continue
        d = int(m.group(1) + m.group(2) + m.group(3))
        if d > CUTOFF:
            continue
        try:
            nav = float(x[1])
        except ValueError:
            bad += 1
            continue
        na = None
        if len(x) > 2 and x[2].strip():
            try:
                na = float(x[2])
            except ValueError:
                na = None
        dv = 0.0
        if len(x) > 3 and x[3].strip():
            try:
                dv = float(x[3])
            except ValueError:
                dv = 0.0
        out.append((d, nav, na, dv))
    out.sort()
    return out, bad


def load_nav(assoc):
    p = nav_path(assoc)
    if not os.path.exists(p):
        return None
    return parse_csv(open(p, 'rb').read())[0]


def _ymd(d):
    return datetime.date(d // 10000, d // 100 % 100, d % 100)


def monthly_tr(daily):
    """日次の行 → {yyyymm: 月次の総リターン}（最初の日を含む月は使わない・31日を超える空きの後の月は値なし）。成績の要約はしない"""
    if not daily or len(daily) < 2:
        return {}
    first_ym = daily[0][0] // 100
    acc, cur, bad_months, out = 1.0, None, set(), {}
    for (d0, n0, _, _), (d1, n1, _, v1) in zip(daily, daily[1:]):
        ym = d1 // 100
        if (_ymd(d1) - _ymd(d0)).days > 31:
            y0, m0 = divmod(d0 // 100, 100)
            y1, m1 = divmod(ym, 100)
            k = y0 * 12 + m0 - 1
            while k <= y1 * 12 + m1 - 1:
                bad_months.add((k // 12) * 100 + k % 12 + 1)
                k += 1
        if cur is not None and ym != cur:
            out[cur] = acc - 1
            acc = 1.0
        cur = ym
        acc *= (n1 + v1) / n0 if n0 > 0 else float('nan')
    if cur is not None:
        out[cur] = acc - 1
    out.pop(first_ym, None)
    for k in bad_months:
        out.pop(k, None)
    return {k: v for k, v in out.items() if not math.isnan(v) and k <= CUTOFF // 100}


def month_end_net_assets(daily):
    """{yyyymm: その月の最後の日の純資産(百万円)}（X3・重複の除去で使う）"""
    out = {}
    for d, _, na, _ in daily:
        if na is not None:
            out[d // 100] = na
    return out


# ═════════════════════════ 補助のデータ ═════════════════════════
def msci_jpy(code, variant='NETR', ccy='JPY'):
    """MSCI の月末の水準 → 月次リターン {yyyymm: 小数}（ccy='USD' なら米ドル建て）"""
    url = (f'https://app2.msci.com/products/service/index/indexmaster/getLevelDataForGraph?currency_symbol={ccy}&index_variant={variant}'
           f'&start_date=19970101&end_date={CUTOFF}&data_frequency=END_OF_MONTH&baseValue=false&index_codes={code}')
    j = json.loads(N.get(url, name=f'jpf_msci_{code}_{variant}_{ccy}_{CUTOFF}.json', max_age_days=3650))
    lv = {x['calc_date'] // 100: x['level_eod'] for x in j['indexes']['INDEX_LEVELS']}
    ks = sorted(lv)
    return {k: lv[k] / lv[p] - 1 for p, k in zip(ks, ks[1:]) if k <= CUTOFF // 100}


def usdjpy_change():
    """円／米ドルの月次の変化（円安が正）= (1+World の円建て) ÷ (1+World の米ドル建て) − 1"""
    j, u = msci_jpy(990100, ccy='JPY'), msci_jpy(990100, ccy='USD')
    return {k: (1 + j[k]) / (1 + u[k]) - 1 for k in j if k in u}


JITA_URL = 'https://www.toushin.or.jp/tws/toukei_dw/I0112B_pub_y.xlsx'
BOND_NAME = re.compile(r'(公社債投信|MMF|MRF|中期国債|マネー・リザーブ|マネー・マネージメント)')


def jita_counts():
    import openpyxl
    b = N.get(JITA_URL, name='jpf_jita_I0112B_pub_y.xlsx', max_age_days=3650)
    wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)

    def counts(sh):
        out = {}
        for row in wb[sh].iter_rows(values_only=True):
            if row[1] and isinstance(row[1], str) and re.match(r'\d{4}年', row[1].strip()):
                y = int(row[1].strip()[:4])
                vals = [v for v in row[2:] if v is not None]
                if vals and isinstance(vals[-1], (int, float)):
                    out[y] = int(vals[-1])
        return out
    return counts('株式 追加型'), counts('株式 追加型 ＥＴＦ')


def jita_survival(rows):
    """年末ごと: JITA の株式投信（追加型・ETF 除く）の本数、ライブラリーの生き残りのうちその年末までに設定された本数、
    s = 割合、q = 年あたりの償還率（1−s^(1/T)）。本数だけ（成績ではない）"""
    A, E = jita_counts()
    lib = [r for r in rows if r.get('unitOpenDiv') == '2' and not (r.get('isinCd') or '').startswith('JP3') and not BOND_NAME.search(nfkc(r.get('fundNm')))]
    snap = datetime.date(2026, 9, 28)
    out = {}
    for y in sorted(A):
        if y < 2005:
            continue
        nj = A[y] - E.get(y, 0)
        nl = sum(1 for r in lib if (r.get('establishedDate') or '9999')[:10] <= f'{y}-12-31')
        T = (snap - datetime.date(y, 12, 31)).days / 365.25
        s = nl / nj if nj else None
        q = 1 - s ** (1 / T) if s and 0 < s <= 1 and T > 0 else None
        out[y] = {'jita_open_ex_etf': nj, 'library_survivors_established_by_year_end': nl, 's': round(s, 4) if s else None,
                  'years_to_now': round(T, 2), 'q_per_year': round(q, 4) if q is not None else None}
    return out


MUFG_LIST = 'https://www.am.mufg.jp/mukamapi/fund_repayment/?site_type=1'
MUFG_CHART = 'https://www.am.mufg.jp/fund_file/chart/chart_data_{}.js'


def mufg_category(x):
    nm = nfkc(x.get('cff_fund_name')) + ' ' + nfkc(x.get('cff_fund_nick_name'))
    t = x.get('cff_fund_type_name')
    has = lambda ks: any(nfkc(k) in nm for k in ks)
    if t == '国内株式':
        c = 'JP'
    elif t == '海外株式':
        if has(['米国', '北米', 'アメリカ', 'S&P', 'ダウ', 'NASDAQ', 'ナスダック']):
            c = 'US'
        elif has(['新興国', 'エマージング', 'BRICs', 'ブリックス']):
            c = 'EM'
        elif has(['先進国', 'グローバル', '世界', '外国', '海外', 'コクサイ']):
            c = 'GLX'
        else:
            c = None
    elif t == '内外株式':
        c = 'GLW' if has(['グローバル', '世界', '全世界', 'オール']) else None
    else:
        c = None
    k = 'index' if 'インデックス' in nm else 'active'
    bad = (any(_RX[r].search(nm) for r in ('wrap_only_regex', 'special_regex', 'hedged_regex', 'currency_course_regex'))
           or ('円コース' in nm and c not in (None, 'JP'))            # 外国の資産の円コース＝ヘッジあり（主の母集団と同じ扱い）
           or bool(re.search(r'(DC|確定拠出)', nm))                  # DC 専用（ライブラリーでは dcFundFlg で落とすもの。MUFG の一覧に印が無いので名前で）
           or '上場投信' in nm or x.get('cff_type') != 'PublicFund')  # ETF・DC 型は除く
    return c, k, bad


def mufg_redeemed(fetch_charts=True):
    j = json.loads(N.get(MUFG_LIST, name='jpf_mufg_fund_repayment.json', max_age_days=3650))
    L = j['datasets']['api00025TmCmFndFundsOutDto']
    keep = []
    for x in L:
        c, k, bad = mufg_category(x)
        keep.append({'fund_cd': x['cff_fund_cd'], 'assoc': x['cff_association_fund_cd'], 'isin': x['cff_isin_cd'], 'type': x['cff_type'],
                     'name': x['cff_fund_name'], 'fund_type': x['cff_fund_type_name'], 'setting_date': x['cff_setting_date'],
                     'redeemed': x['cfm_base_date'], 'cat': c, 'kind': k, 'excluded_by_filter': bad})
    if fetch_charts:
        os.makedirs(MUFGDIR, exist_ok=True)
        for r in keep:
            if r['cat'] and r['type'] == 'PublicFund':
                p = os.path.join(MUFGDIR, f"{r['fund_cd']}.json")
                if not os.path.exists(p):
                    try:
                        b = urllib.request.urlopen(urllib.request.Request(MUFG_CHART.format(r['fund_cd']), headers=N.UA), timeout=120).read()
                        open(p, 'wb').write(b)
                    except Exception as e:  # noqa
                        open(p + '.missing', 'w').write(str(e)[:200])
                    time.sleep(1.0)
    return keep


def load_mufg_daily(fund_cd):
    """三菱UFJの chart_data → parse_csv と同じ形 [(yyyymmdd, 基準価額, 純資産(百万円), 分配金)]"""
    p = os.path.join(MUFGDIR, f'{fund_cd}.json')
    if not os.path.exists(p):
        return None
    d = json.load(open(p))
    out = []
    for x in d.get('ROWS') or []:
        dd = int(x['BASE_DATE'])
        if dd > CUTOFF or x.get('BASE_PRICE') is None:
            continue
        na = x.get('NET_ASSET_VALUE')
        out.append((dd, float(x['BASE_PRICE']), (float(na) / 1e6) if na is not None else None, float(x.get('PROFIT_DISTRIBUTION') or 0.0)))
    return sorted(out)


def build_support(rows):
    sup = {'msci_months': {}, 'jita_survival': jita_survival(rows), 'mufg_redeemed': mufg_redeemed()}
    for cat, code in list(MSCI.items()) + [('WORLD_for_fx', 990100)]:
        for ccy in ('JPY', 'USD'):
            s = msci_jpy(code, ccy=ccy)
            sup['msci_months'][f'{cat}_{ccy}'] = {'code': code, 'first': min(s), 'last': max(s), 'n': len(s)}
    fx = usdjpy_change()
    sup['msci_months']['USDJPY_change_from_MSCI_World'] = {'first': min(fx), 'last': max(fx), 'n': len(fx)}
    json.dump(sup, open(SUPPORT, 'w'), ensure_ascii=False, indent=1)
    return sup


# ═════════════════════════ 凍結の印 ═════════════════════════
def universe_sha():
    d = load_universe()
    return hashlib.sha256(json.dumps(d['rows'], sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def extract_sha(codes=None):
    """CUTOFF までの全 CSV（日付・基準価額・純資産・分配金）を協会コード順に直列化した sha256。測る道具は最初に確かめる"""
    h = hashlib.sha256()
    names = sorted(f[:-4] for f in os.listdir(NAVDIR) if f.endswith('.csv'))
    if codes is not None:
        names = [c for c in names if c in codes]
    for a in names:
        rows = load_nav(a)
        h.update(a.encode())
        h.update(json.dumps(rows, separators=(',', ':')).encode())
    return h.hexdigest(), len(names)


# ═════════════════════════ 形だけ ═════════════════════════
def sel_dates():
    return [y * 100 + 9 for y in range(2007, 2026)]


def show():
    import collections
    d = load_universe()
    rows = d['rows']
    print(f"一覧: {d['n']}本（基準日 {d['standardDate']}・取得 {d['fetched_at']}）")
    cats = collections.Counter((category(r), kind(r)) for r in rows if category(r))
    print('5分類×種類（フィルター前）:', dict(sorted(cats.items(), key=str)))
    ok = [r for r in rows if category(r) and passes_filter(r)]
    print('フィルター後:', dict(sorted(collections.Counter((category(r), kind(r)) for r in ok).items(), key=str)))
    fl = collections.Counter()
    for r in rows:
        if category(r):
            for k, v in flags(r).items():
                if v:
                    fl[k] += 1
    print('除く理由（5分類・重なりあり）:', dict(fl))
    # CSV の形
    have = [f[:-4] for f in os.listdir(NAVDIR) if f.endswith('.csv')] if os.path.isdir(NAVDIR) else []
    miss = [f[:-12] for f in os.listdir(NAVDIR) if f.endswith('.csv.missing')] if os.path.isdir(NAVDIR) else []
    print(f'CSV: 取得 {len(have)}本・HTTP 500 {len(miss)}本')
    firsts, lasts, gaps, badrows, nrows, divrows = collections.Counter(), collections.Counter(), 0, 0, [], 0
    mon = {}
    for a in have:
        b = open(nav_path(a), 'rb').read()
        daily, bad = parse_csv(b)
        badrows += bad
        if not daily:
            continue
        nrows.append(len(daily))
        firsts[str(daily[0][0])[:4]] += 1
        lasts[str(daily[-1][0])[:6]] += 1
        divrows += sum(1 for x in daily if x[3])
        for (d0, *_), (d1, *_) in zip(daily, daily[1:]):
            if (_ymd(d1) - _ymd(d0)).days > 31:
                gaps += 1
        mon[a] = monthly_tr(daily)
    print('CSV の最初の年:', dict(sorted(firsts.items())))
    print('CSV の最後の月:', dict(sorted(lasts.items())))
    print(f'31日を超える空き: {gaps}か所・読めない行 {badrows}・分配金のある行 {divrows}・行数の中央 {sorted(nrows)[len(nrows)//2] if nrows else None}')
    by = {r['associFundCd']: r for r in rows}
    # 選択の日ごとの適格の本数（重複を除く前）
    print('選択の日ごとの適格（能動・フィルター後・振り返りの月がそろう本数・重複を除く前）:')
    for L in (1, 3, 5):
        line = []
        for t in sel_dates():
            y = t // 100
            months = []
            k = (y - L) * 12 + 9
            while k < y * 12 + 9:
                months.append((k // 12) * 100 + k % 12 + 1)
                k += 1
            if months[0] < 200610:
                continue
            c = collections.Counter()
            for a, m in mon.items():
                r = by.get(a)
                if not r or kind(r) != 'active' or not passes_filter(r) or not category(r):
                    continue
                if all(mm in m for mm in months):
                    c[category(r)] += 1
            line.append(f"{y}:{'/'.join(f'{k}{c[k]}' for k in ('JP', 'US', 'GLX', 'GLW', 'EM'))}")
        print(f'  L={L}年 ', '  '.join(line))
    # 相手の割り当て（名前と信託報酬だけ）
    print('相手（選択の日ごと・t に基準価額がある指数型のうち今の信託報酬が最安）:')
    for cat in ('JP', 'US', 'GLX', 'GLW', 'EM'):
        cands = comparator_candidates(rows, cat)
        seq = []
        for t in sel_dates():
            alive = [r for r in cands if r['associFundCd'] in mon and t in mon[r['associFundCd']]]
            if not alive:
                seq.append(f'{t // 100}:MSCI-0.5%')
                continue
            best = min(alive, key=lambda r: (float(r.get('trustReward') or 9), r.get('establishedDate') or ''))
            seq.append(f"{t // 100}:{best['associFundCd']}({best.get('trustReward')})")
        print(f'  {cat} 候補 {len(cands)}本 ', ' '.join(seq))
    rm = report_members(rows)
    print('報告の族の器:', {k: len(v) for k, v in rm.items()})
    for q, codes in rm.items():
        if q.startswith('Q1') or q.startswith('Q2'):
            print('  ', q, [(c, nfkc(by[c]['fundNm'])[:28], (min(mon[c]) if c in mon and mon[c] else None)) for c in codes])
    if os.path.exists(SUPPORT):
        sup = json.load(open(SUPPORT))
        print('MSCI（円・NETR）:', sup['msci_months'])
        print('JITA の生き残り（年末・本数だけ）:')
        for y, v in sup['jita_survival'].items():
            print('  ', y, v)
        mr = sup['mufg_redeemed']
        c = collections.Counter((r['cat'], r['kind'], r['excluded_by_filter']) for r in mr if r['type'] == 'PublicFund')
        print('三菱UFJの償還（公募・2021-02〜）:', len(mr), '本・分類×種類×除外:', dict(c))
        got = sum(1 for r in mr if r['cat'] and r['type'] == 'PublicFund' and os.path.exists(os.path.join(MUFGDIR, f"{r['fund_cd']}.json")))
        print('  うち5分類で全履歴を取得:', got)
        spans = []
        for r in mr:
            if r['cat'] and r['type'] == 'PublicFund':
                dd = load_mufg_daily(r['fund_cd'])
                if dd:
                    spans.append((dd[0][0] // 100, dd[-1][0] // 100))
        if spans:
            print('  履歴の最初の年の分布:', dict(sorted(collections.Counter(str(a)[:4] for a, _ in spans).items())),
                  '最後の月の範囲:', min(b for _, b in spans), '〜', max(b for _, b in spans))


if __name__ == '__main__':
    a = sys.argv[1:]
    if '--universe' in a:
        d = build_universe()
        print(f"一覧を凍結: {d['n']}本 / 基準日 {d['standardDate']}", file=sys.stderr)
    if '--nav' in a:
        rows = load_universe()['rows']
        need = needed_codes(rows)
        print(f'CSV を取る器: {len(need)}本', file=sys.stderr)
        miss = fetch_navs(need)
        print(f'HTTP 500: {len(miss)}本', file=sys.stderr)
    if '--support' in a:
        build_support(load_universe()['rows'])
    if '--show' in a:
        show()
    if '--sha' in a:
        print('universe_sha256', universe_sha())
        print('rules_sha256', rules_sha())
        print('extract_sha256', *extract_sha())
