#!/usr/bin/env python3
"""night/bestfund_data.py — bestfund（最高の投資信託・ETF を歴史検証と未来検証で探す）の材料（読むだけ・門には触れない）

事前登録 out/bestfund_prereg.json（d5eab7f・測る前に固定）の data_rules をそのまま実装する。

  chains()   … 39の賭けの月次の総リターン（配当込み）。実物 → 指数 → 長い代わり（Ken French・Shiller）の順に、月で切り替えてつなぐ。
               米国・世界の賭けはドル建て、日本の賭け（TOPIX・N225）は円建てで作り、両方の通貨の系列を返す。
               実物（ETF・投信）の期間は、その器の経費率を足し戻して『指数の値』に揃える（費用は世界ごとに買う器の分を引く）。
  fx()       … ドル円の月末（FRED DEXJPUS・1971-01〜。1949-04〜1970-12 は 360円）と月次の変化
  VEH        … 賭けごとの NISA で持てる器（楽天証券で買える・つみたて投資枠／成長投資枠）と費用・配当利回り・外国税の係数 k

取れない月を0と読まない（ルール7）。つなげない賭けは短い記録のまま返し、短いことを表に出す。
キャッシュは out/_mw_cache/（gitignore）。

  python3 night/bestfund_data.py          → 各賭けのつなぎ目・期間・つなぎ目の相関を表示し out/_mw_cache/bf_chains.json に保存
"""
import datetime, json, math, os, statistics as S, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import mw_common as M          # noqa: E402
import gaps_common as G        # noqa: E402

END = 202609                      # 最後の完全な月（2026-10-11 に作成）
A1, A2 = (200009, 202609), (201110, 202609)
CACHE_JSON = os.path.join(M.CACHE, 'bf_chains.json')

# ── 実物の器の経費率（足し戻す分・年率）。出所: Alpha Vantage ETF_PROFILE（2026-10-09 更新）・out/etf_profiles.json・
#    out/etf_forward_profiles.json・投信総合検索ライブラリー（東証ETF・2026-10-09）。古い投信（VIGRX 等）は今の公表値を置く
#    （昔はもっと高かった＝足し戻しは控えめ）。
ACTUAL_ER = {
    'VTI': 0.0003, 'QQQ': 0.0020, 'VT': 0.0006, 'VEA': 0.0003, 'EFA': 0.0032, 'VWO': 0.0006, 'VEIEX': 0.0029,
    '1306.T': 0.000968, '1321.T': 0.000824, 'EPI': 0.0084, 'SMH': 0.0035, 'SOXX': 0.0033, 'XLK': 0.0008, 'VGT': 0.0009,
    'IGV': 0.0038, 'FDN': 0.0049, 'MGK': 0.0005, 'VUG': 0.0003, 'VIGRX': 0.0017, 'VTV': 0.0003, 'VIVAX': 0.0017,
    'IJR': 0.0006, 'VBR': 0.0005, 'VISVX': 0.0019, 'QUAL': 0.0015, 'MTUM': 0.0015, 'USMV': 0.0015, 'VIG': 0.0004,
    'VYM': 0.0004, 'RSP': 0.0020, 'XLV': 0.0008, 'ITA': 0.0037, 'FSDAX': 0.0075, 'XLE': 0.0008, 'XLF': 0.0008,
    'XLP': 0.0008, 'XLU': 0.0008, 'VNQ': 0.0013, 'VGSIX': 0.0026, 'PXF': 0.0043, 'DFIVX': 0.0028, 'DEM': 0.0063,
    'DFEVX': 0.0044, 'GLD': 0.0040, 'BND': 0.0003, 'VBMFX': 0.0015,
}

# 20か国＝French の国別21ファイルから MSCI で新興国に分類されるマレーシアを除いたもの（その月に値のある国で等分）
DEV20 = ['UK', 'Austria', 'Austrlia', 'Belgium', 'Canada', 'Denmark', 'Finland', 'France', 'Germany', 'HongKong', 'Ireland',
         'Italy', 'Japan', 'Nethrlnd', 'NewZland', 'Norway', 'Singapor', 'Spain', 'Sweden', 'Swtzrlnd']

# ── 賭けのつなぎ（事前登録 data_rules.chains の順）。各段: (種類, 出所, 表示)。種類 = actual（器）/ index / proxy（代わり）
CHAINS = {
    'ACWI': [('actual', ('yahoo', 'VT'), 'VT'), ('index', ('msci', 892400, 'USD'), 'MSCI ACWI（ドル・配当込み NETR）'),
             ('proxy', ('blend', [(('french_mkt',), .6), (('french_dxus',), .4)]), '米国60%＋先進国（米国除く）40%（French）'),
             ('proxy', ('blend', [(('french_mkt',), .6), (('dev20',), .4)]), '米国60%＋French の国別20か国の等分40%')],
    'SP500': [('index', ('yahoo', '^SP500TR'), 'S&P500 トータルリターン指数'), ('proxy', ('shiller',), 'Shiller の S&P 総合（名目・配当込み・月平均の値段）')],
    'USTOT': [('actual', ('yahoo', 'VTI'), 'VTI'), ('proxy', ('french_mkt',), 'French の米国市場（CRSP 全上場）')],
    'NDX': [('actual', ('yahoo', 'QQQ'), 'QQQ'), ('index', ('px_div', '^NDX', 'QQQ'), '^NDX の価格＋配当の置き値（QQQ の最初の3年）'),
            ('proxy', ('blend', [(('french_tech',), .65), (('french_mkt',), .35)]), '代わり: French のテック3業種65%＋市場35%')],
    'KOKUSAI': [('index', ('msci', 991200, 'USD'), 'MSCI Kokusai（ドル・NETR）'),
                ('proxy', ('blend', [(('french_region', 'North_America_3_Factors'), .65), (('french_region', 'Europe_3_Factors'), .35)]),
                 'French の北米65%＋欧州35%')],
    'DEVXUS': [('actual', ('yahoo', 'VEA'), 'VEA'), ('actual', ('yahoo', 'EFA'), 'EFA'), ('proxy', ('french_dxus',), 'French の先進国（米国除く）'),
               ('proxy', ('dev20',), 'French の国別20か国の等分')],
    'EM': [('actual', ('yahoo', 'VWO'), 'VWO'), ('actual', ('yahoo', 'VEIEX'), 'VEIEX'), ('proxy', ('french_em',), 'French の新興国')],
    'TOPIX': [('actual', ('jita_nav', 'JP3027630007', '01312017', '1306.T'), '1306（円・投信協会の基準価額＋分配金）'), ('index', ('msci', 939200, 'JPY'), 'MSCI Japan（円・NETR）'),
              ('proxy', ('french_country', 'Japan', 'Local'), 'French の日本（円）')],
    'N225': [('actual', ('jita_nav', 'JP3027650005', '01311017', '1321.T'), '1321（円・投信協会の基準価額＋分配金）'),
             ('index', ('px_div_nav', '^N225', 'JP3027650005', '01311017'), '^N225 の価格＋配当の置き値（1321 の最初の3年）')],
    'INDIA': [('actual', ('yahoo', 'EPI'), 'EPI'), ('index', ('px_div_inr', '^BSESN', 'EPI'), '^BSESN の価格（ドル換算）＋配当の置き値（EPI の最初の3年）')],
    'SEMI_MV': [('actual', ('yahoo', 'SMH'), 'SMH'), ('index', ('px_div', '^SOX', 'SMH'), '^SOX の価格＋配当の置き値（SMH の最初の3年）'),
                ('proxy', ('french_ind', ['Chips']), '代わり: French の Chips（電子部品を含む）')],
    'SEMI_SOX': [('actual', ('yahoo', 'SOXX'), 'SOXX'), ('index', ('px_div', '^SOX', 'SOXX'), '^SOX の価格＋配当の置き値（SOXX の最初の3年）'),
                 ('proxy', ('french_ind', ['Chips']), '代わり: French の Chips')],
    'TECH_SPDR': [('actual', ('yahoo', 'XLK'), 'XLK'), ('proxy', ('french_tech',), '代わり: French のテック3業種（時価総額で加重）')],
    'TECH_VGT': [('actual', ('yahoo', 'VGT'), 'VGT'), ('actual', ('yahoo', 'XLK'), 'XLK'), ('proxy', ('french_tech',), '代わり: French のテック3業種')],
    'FANG': [('index', ('yahoo_from', '^NYFANG', 201710), 'NYSE FANG+（価格・発表後 2017-10〜）')],
    'SOFT': [('actual', ('yahoo', 'IGV'), 'IGV'), ('proxy', ('french_ind_minshare', 'Softw', 0.0025), '代わり: French の Softw（時価総額の0.25%以上の月）')],
    'INET': [('actual', ('yahoo', 'FDN'), 'FDN')],
    'MEGAG': [('actual', ('yahoo', 'MGK'), 'MGK'), ('actual', ('yahoo', 'VUG'), 'VUG'),
              ('proxy', ('french_pf', '6_Portfolios_2x3', 'BIG LoBM', 'Average Value Weighted Returns'), 'French の大型グロース（BIG LoBM）')],
    'GROWTH': [('actual', ('yahoo', 'VUG'), 'VUG'), ('actual', ('yahoo', 'VIGRX'), 'VIGRX'),
               ('proxy', ('french_pf', '6_Portfolios_2x3', 'BIG LoBM', 'Average Value Weighted Returns'), 'French の BIG LoBM')],
    'VALUE': [('actual', ('yahoo', 'VTV'), 'VTV'), ('actual', ('yahoo', 'VIVAX'), 'VIVAX'),
              ('proxy', ('french_pf', '6_Portfolios_2x3', 'BIG HiBM', 'Average Value Weighted Returns'), 'French の BIG HiBM')],
    'SMALL': [('actual', ('yahoo', 'IJR'), 'IJR'), ('proxy', ('french_pf', 'Portfolios_Formed_on_ME', 'Lo 30', 'Average Value Weight Returns'), 'French の時価総額下位30%')],
    'SMALLV': [('actual', ('yahoo', 'VBR'), 'VBR'), ('actual', ('yahoo', 'VISVX'), 'VISVX'),
               ('proxy', ('french_pf', '6_Portfolios_2x3', 'SMALL HiBM', 'Average Value Weighted Returns'), 'French の SMALL HiBM')],
    'QUALITY': [('actual', ('yahoo', 'QUAL'), 'QUAL'),
                ('proxy', ('french_pf', '6_Portfolios_ME_OP_2x3', 'BIG HiOP', 'Average Value Weighted Returns'), 'French の BIG HiOP')],
    'MOM': [('actual', ('yahoo', 'MTUM'), 'MTUM'),
            ('proxy', ('french_pf', '6_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR', 'Average Value Weighted Returns'), 'French の BIG HiPRIOR')],
    'LOWVOL': [('actual', ('yahoo', 'USMV'), 'USMV'), ('proxy', ('french_pf', 'Portfolios_Formed_on_VAR', 'Lo 20', 'Value Weighted Returns'), 'French の分散の低い五分位')],
    'DIVG': [('actual', ('yahoo', 'VIG'), 'VIG')],
    'HIDIV': [('actual', ('yahoo', 'VYM'), 'VYM'), ('proxy', ('french_pf', 'Portfolios_Formed_on_D-P', 'Hi 30', 'Value Weight Returns'), 'French の配当利回り上位30%')],
    'EQW': [('actual', ('yahoo', 'RSP'), 'RSP'), ('proxy', ('french_me_6to10',), 'French の時価総額の第6〜10十分位の平均')],
    'HEALTH': [('actual', ('yahoo', 'XLV'), 'XLV'), ('proxy', ('french_ind', ['Hlth', 'MedEq', 'Drugs']), 'French の Hlth＋MedEq＋Drugs')],
    'DEFENSE': [('actual', ('yahoo', 'ITA'), 'ITA'), ('actual', ('yahoo', 'FSDAX'), 'FSDAX'), ('proxy', ('french_ind', ['Guns', 'Aero']), 'French の Guns＋Aero')],
    'ENERGY': [('actual', ('yahoo', 'XLE'), 'XLE'), ('proxy', ('french_ind', ['Oil']), 'French の Oil')],
    'FIN': [('actual', ('yahoo', 'XLF'), 'XLF'), ('proxy', ('french_ind', ['Banks', 'Insur', 'Fin']), 'French の Banks＋Insur＋Fin')],
    'STAPLES': [('actual', ('yahoo', 'XLP'), 'XLP'), ('proxy', ('french_ind', ['Food', 'Soda', 'Beer', 'Smoke', 'Hshld']), 'French の Food＋Soda＋Beer＋Smoke＋Hshld')],
    'UTIL': [('actual', ('yahoo', 'XLU'), 'XLU'), ('proxy', ('french_ind', ['Util']), 'French の Util')],
    'REIT': [('actual', ('yahoo', 'VNQ'), 'VNQ'), ('actual', ('yahoo', 'VGSIX'), 'VGSIX')],
    'DXUS_VAL': [('actual', ('yahoo', 'PXF'), 'PXF'), ('actual', ('yahoo', 'DFIVX'), 'DFIVX'),
                 ('proxy', ('french_pf', 'Developed_ex_US_6_Portfolios_ME_BE-ME', 'BIG HiBM', 'Average Value Weighted Returns'), 'French の先進国（米国除く）BIG HiBM')],
    'EM_VAL': [('actual', ('yahoo', 'DEM'), 'DEM'), ('actual', ('yahoo', 'DFEVX'), 'DFEVX'),
               ('proxy', ('french_pf', 'Emerging_Markets_6_Portfolios_ME_BE-ME', 'BIG HiBM', 'Average Value Weighted Returns'), 'French の新興国 BIG HiBM')],
    'GOLD': [('actual', ('yahoo', 'GLD'), 'GLD'), ('index', ('gold_fut',), '金の先物（GC=F の月末）'), ('index', ('fred_gold',), 'FRED の金価格（取れれば）')],
    'BOND': [('actual', ('yahoo', 'BND'), 'BND'), ('actual', ('yahoo', 'VBMFX'), 'VBMFX')],
}
# ★結果を見た後の是正（データの質・事前登録の外・2026-10-11）: NYSE FANG+ は 2017-09-26 に発表された指数で、2014-09-19〜2017-09-25 は
#   発表時に選んだ銘柄で後から計算した試算（ICE の説明どおり）。実際の値ではないので主の計算から外した。事前登録どおりの系列（2014-10〜）は
#   CHAINS_PREREG に残し、bestfund.py の感度『事前登録どおり（FANG の試算期間を含む）』で並べる
CHAINS_PREREG = {'FANG': [('index', ('yahoo', '^NYFANG'), 'NYSE FANG+（価格・試算期間 2014-10〜 を含む＝事前登録どおり）')]}
JPY_NATIVE = {'TOPIX', 'N225'}
JA = {
    'ACWI': '全世界株（オール・カントリー）', 'SP500': 'S&P500', 'USTOT': '米国株全体', 'NDX': 'NASDAQ100', 'KOKUSAI': '先進国株（日本除く）',
    'DEVXUS': '先進国株（米国除く）', 'EM': '新興国株', 'TOPIX': '日本株（TOPIX）', 'N225': '日本株（日経平均）', 'INDIA': 'インド株',
    'SEMI_MV': '半導体（SMH の指数）', 'SEMI_SOX': '半導体（SOX 指数）', 'TECH_SPDR': '米国テクノロジー（XLK）', 'TECH_VGT': '米国 IT（VGT）',
    'FANG': 'FANG+', 'SOFT': '米国ソフトウェア', 'INET': '米国インターネット', 'MEGAG': '米国メガキャップ・グロース', 'GROWTH': '米国大型グロース',
    'VALUE': '米国大型バリュー', 'SMALL': '米国小型', 'SMALLV': '米国小型バリュー', 'QUALITY': '米国クオリティ', 'MOM': '米国モメンタム',
    'LOWVOL': '米国低ボラティリティ', 'DIVG': '米国連続増配', 'HIDIV': '米国高配当', 'EQW': 'S&P500 均等加重', 'HEALTH': '米国ヘルスケア',
    'DEFENSE': '米国航空・防衛', 'ENERGY': '米国エネルギー', 'FIN': '米国金融', 'STAPLES': '米国生活必需品', 'UTIL': '米国公益',
    'REIT': '米国 REIT', 'DXUS_VAL': '先進国（米国除く）バリュー寄り', 'EM_VAL': '新興国高配当（バリュー寄り）', 'GOLD': '金', 'BOND': '米国債券（総合）',
}

# ── 器（NISA・楽天証券）。費用は税込の年率。fund＝日本の投資信託（楽天証券の取扱と NISA の枠は投信総合検索ライブラリー 2026-10-09 の
#    institutionInfo・nisaFlg・nisaGrowthFlg で確かめた）／us＝米国ETF（楽天の ETFD.csv 2026-10-11 に在るものだけ）／jp＝東証ETF。
#    費用には投信が中で買う米国ETFの経費（投信の信託報酬に含まれない分）と、米国ETFの両替の手数料（1ドル25銭を20年の積立で年0.02%）を足してある。
#    alt＝（器, 費用, 枠）。枠は つみたて／成長／両方（その器がどちらの枠で買えるか）。
#    k＝NISA の中で取り戻せない配当の外国税の係数（米国株 0.10・米国外の株を持つ米国ETF 0.20〔etf_forward_rank〕・米国外の株を直接持つ
#    日本の投信 0.15〔置き値〕・日本株 0）。dy＝配当利回り（米国ETF は Alpha Vantage 2026-10-09 など。日本の投信は同じ指数の米国ETFの値）。
FX_FEE = 0.0002
VEH = {
    'ACWI': dict(tsumitate=('楽天・プラス・オールカントリー株式インデックス・ファンド', 0.000561), growth=('楽天・プラス・オールカントリー株式インデックス・ファンド', 0.000561),
                 alt=[('eMAXIS Slim 全世界株式（オール・カントリー）', 0.0005775, '両方'), ('VT', 0.0006 + FX_FEE, '成長')], k=0.62 * 0.10 + 0.38 * 0.15, dy=0.0158),
    'SP500': dict(tsumitate=('楽天・プラス・S&P500インデックス・ファンド', 0.000770), growth=('楽天・プラス・S&P500インデックス・ファンド', 0.000770),
                  alt=[('eMAXIS Slim 米国株式（S&P500）', 0.000814, '両方'), ('SBI・V・S&P500（中で VOO 0.03%）', 0.000638 + 0.0003, '両方'), ('VOO', 0.0003 + FX_FEE, '成長')], k=0.10, dy=0.0098),
    'USTOT': dict(tsumitate=('楽天・全米株式インデックス・ファンド（中で VTI 0.03%）', 0.001320 + 0.0003), growth=('VTI', 0.0003 + FX_FEE),
                  alt=[('eMAXIS Slim 全米株式（成長投資枠のみ）', 0.000814, '成長')], k=0.10, dy=0.0101),
    'NDX': dict(tsumitate=('iFreeNEXT NASDAQ100インデックス', 0.00495), growth=('QQQM', 0.0015 + FX_FEE),
                alt=[('楽天・プラス・NASDAQ-100インデックス・ファンド（成長投資枠のみ）', 0.00198, '成長')], k=0.10, dy=0.0046),
    'KOKUSAI': dict(tsumitate=('楽天・プラス・先進国株式（除く日本）インデックス・ファンド', 0.000880), growth=('楽天・プラス・先進国株式（除く日本）インデックス・ファンド', 0.000880),
                    alt=[('eMAXIS Slim 先進国株式インデックス（除く日本）', 0.000989, '両方')], k=0.72 * 0.10 + 0.28 * 0.15, dy=0.0150),
    'DEVXUS': dict(tsumitate=None, growth=('VEA', 0.0003 + FX_FEE), alt=[('EFA', 0.0032 + FX_FEE, '成長')], k=0.20, dy=0.0249),
    'EM': dict(tsumitate=('eMAXIS Slim 新興国株式インデックス', 0.001518), growth=('eMAXIS Slim 新興国株式インデックス', 0.001518),
               alt=[('VWO', 0.0006 + FX_FEE, '成長')], k=0.15, dy=0.0229),
    'TOPIX': dict(tsumitate=('eMAXIS Slim 国内株式（TOPIX）', 0.001430), growth=('One ETF トピックス（東証）', 0.000495),
                  alt=[('MAXIS トピックス上場投信（1348）', 0.00066, '成長'), ('NEXT FUNDS TOPIX（1306）', 0.000968, '成長')], k=0.0, dy=0.022),
    'N225': dict(tsumitate=('楽天・プラス・日経225インデックス・ファンド', 0.001320), growth=('NEXT FUNDS 日経225（1321）', 0.000824),
                 alt=[('eMAXIS Slim 国内株式（日経平均）', 0.00143, '両方')], k=0.0, dy=0.017),
    'INDIA': dict(tsumitate=None, growth=('たわらノーロード インド株式 Nifty50', 0.002805), alt=[('楽天・インド株 Nifty50', 0.00308, '成長'), ('EPI', 0.0084 + FX_FEE, '成長')],
                  k=0.15, dy=0.012),
    'SEMI_MV': dict(tsumitate=None, growth=('SMH', 0.0035 + FX_FEE), alt=[], k=0.10, dy=0.0015),
    'SEMI_SOX': dict(tsumitate=None, growth=('楽天・プラス・SOX インデックス・ファンド', 0.00176), alt=[('ニッセイ SOX 指数インデックスファンド', 0.001815, '成長')], k=0.10, dy=0.0021),
    'TECH_SPDR': dict(tsumitate=None, growth=('XLK', 0.0008 + FX_FEE), alt=[], k=0.10, dy=0.0042),
    'TECH_VGT': dict(tsumitate=None, growth=('VGT', 0.0009 + FX_FEE), alt=[], k=0.10, dy=0.0032),
    'FANG': dict(tsumitate=('iFreeNEXT FANG+インデックス', 0.007755), growth=('iFreeNEXT FANG+インデックス', 0.007755), alt=[], k=0.10, dy=0.003),
    'SOFT': dict(tsumitate=None, growth=None, alt=[], k=0.10, dy=0.0, note='IGV は楽天に無く、同じ賭けの日本の投信も無い（ETFD.csv 2026-10-11・投信ライブラリー）'),
    'INET': dict(tsumitate=None, growth=('FDN', 0.0049 + FX_FEE), alt=[], k=0.10, dy=0.0),
    'MEGAG': dict(tsumitate=None, growth=('MGK', 0.0005 + FX_FEE), alt=[], k=0.10, dy=0.0029),
    'GROWTH': dict(tsumitate=None, growth=('VUG', 0.0003 + FX_FEE), alt=[], k=0.10, dy=0.0035),
    'VALUE': dict(tsumitate=None, growth=('VTV', 0.0003 + FX_FEE), alt=[], k=0.10, dy=0.0179),
    'SMALL': dict(tsumitate=None, growth=('IJR', 0.0006 + FX_FEE), alt=[], k=0.10, dy=0.0151),
    'SMALLV': dict(tsumitate=None, growth=('VBR', 0.0005 + FX_FEE), alt=[], k=0.10, dy=0.019),
    'QUALITY': dict(tsumitate=None, growth=('MOAT（QUAL は楽天に無い・指数が違う）', 0.0046 + FX_FEE), alt=[], k=0.10, dy=0.0102,
                    note='データのつなぎは QUAL ← French BIG HiOP。買える器は MOAT だけで指数が違う'),
    'MOM': dict(tsumitate=None, growth=None, alt=[], k=0.10, dy=0.0078, note='MTUM は楽天に無い（ETFD.csv 2026-10-11）'),
    'LOWVOL': dict(tsumitate=None, growth=None, alt=[], k=0.10, dy=0.0123, note='USMV は楽天に無い（ETFD.csv 2026-10-11）'),
    'DIVG': dict(tsumitate=None, growth=('VIG', 0.0004 + FX_FEE), alt=[], k=0.10, dy=0.0143),
    'HIDIV': dict(tsumitate=('楽天・米国高配当株式インデックス・ファンド（中で VYM）', 0.00132 + 0.0004), growth=('VYM', 0.0004 + FX_FEE),
                  alt=[('SBI・V・米国高配当株式インデックス・ファンド（中で VYM）', 0.000638 + 0.0004, '成長')], k=0.10, dy=0.022),
    'EQW': dict(tsumitate=None, growth=('RSP', 0.0020 + FX_FEE), alt=[], k=0.10, dy=0.0147),
    'HEALTH': dict(tsumitate=None, growth=('XLV', 0.0008 + FX_FEE), alt=[], k=0.10, dy=0.0152),
    'DEFENSE': dict(tsumitate=None, growth=('ITA', 0.0037 + FX_FEE), alt=[], k=0.10, dy=0.0044),
    'ENERGY': dict(tsumitate=None, growth=('XLE', 0.0008 + FX_FEE), alt=[], k=0.10, dy=0.0239),
    'FIN': dict(tsumitate=None, growth=('XLF', 0.0008 + FX_FEE), alt=[], k=0.10, dy=0.014),
    'STAPLES': dict(tsumitate=None, growth=('XLP', 0.0008 + FX_FEE), alt=[], k=0.10, dy=0.0247),
    'UTIL': dict(tsumitate=None, growth=('XLU', 0.0008 + FX_FEE), alt=[], k=0.10, dy=0.0269),
    'REIT': dict(tsumitate=None, growth=None, alt=[], k=0.10, dy=0.038, note='VNQ は楽天に無く、同じ賭けの NISA 対象の投信も楽天に無い'),
    'DXUS_VAL': dict(tsumitate=None, growth=('PXF', 0.0043 + FX_FEE), alt=[], k=0.20, dy=0.0241),
    'EM_VAL': dict(tsumitate=None, growth=('DEM', 0.0063 + FX_FEE), alt=[], k=0.20, dy=0.0334),
    'GOLD': dict(tsumitate=None, growth=('GLDM', 0.0010 + FX_FEE), alt=[('ステート・ストリート・ゴールド・オープン（為替ヘッジなし）', 0.001925, '成長')], k=0.0, dy=0.0),
    'BOND': dict(tsumitate=None, growth=('BND', 0.0003 + FX_FEE), alt=[], k=0.10, dy=0.0506),
}
REGION = {  # 世界 E の地域の市場（事前登録 future_worlds.E）
    'ACWI': 'ACWI', 'KOKUSAI': 'KOKUSAI', 'DEVXUS': 'DEVXUS', 'DXUS_VAL': 'DEVXUS', 'EM': 'EM', 'EM_VAL': 'EM', 'INDIA': 'EM',
    'TOPIX': 'TOPIX', 'N225': 'TOPIX', 'GOLD': 'GOLD', 'BOND': 'BOND',
}


def region_of(b):
    return REGION.get(b, 'SP500')


def cost_of(b, which='best'):
    """年率の費用＝器の経費率（中の米国ETF・両替を含む）＋外国税 k×dy。which: best（NISA で持てる器の中で最安）/ tsumitate / growth"""
    v = VEH[b]
    tax = v['k'] * v['dy']
    cands = []
    if v.get('tsumitate'):
        cands.append(('つみたて', v['tsumitate'][0], v['tsumitate'][1]))
    if v.get('growth'):
        cands.append(('成長', v['growth'][0], v['growth'][1]))
    for nm, fee, acct in v.get('alt') or []:
        cands.append((acct, nm, fee))
    if which == 'tsumitate':
        cands = [c for c in cands if c[0] in ('つみたて', '両方')]
    elif which == 'growth':
        cands = [c for c in cands if c[0] in ('成長', '両方')]
    if not cands:
        return None
    acct, nm, fee = min(cands, key=lambda x: x[2])
    return dict(account=acct, vehicle=nm, fee=fee, tax=tax, total=fee + tax)


def eligible(b):
    v = VEH[b]
    return bool(v.get('tsumitate') or v.get('growth'))


# ───────────────────────── 出所 ─────────────────────────
_memo = {}


def _m(key, fn):
    if key not in _memo:
        _memo[key] = fn()
    return _memo[key]


def yahoo_tr(t):
    return _m(('yh', t), lambda: M.yahoo(t))


def yahoo_px(t):
    """配当を足さない価格（close）の月次リターン（mw_common.yahoo と同じキャッシュ・同じ月の切り方）"""
    def f():
        import urllib.parse
        u = (f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}?period1=0&period2={int(time.time())}'
             f'&interval=1mo&events=div%2Csplit')
        j = json.loads(M.get(u, name=f'yh_{t.replace("^", "IDX_").replace("=", "_")}_1mo.json', max_age_days=3))
        r = j['chart']['result'][0]
        off = r.get('meta', {}).get('gmtoffset') or 0
        px = {}
        for ts, c in zip(r['timestamp'], r['indicators']['quote'][0]['close']):
            if c is None:
                continue
            d = datetime.datetime.utcfromtimestamp(ts + off)
            px[d.year * 100 + d.month] = c
        now = datetime.datetime.utcfromtimestamp(time.time() + off)
        px = {k: v for k, v in px.items() if k < now.year * 100 + now.month}
        ks = sorted(px)
        return {k: px[k] / px[p] - 1 for p, k in zip(ks, ks[1:]) if (k // 100 * 12 + k % 100) - (p // 100 * 12 + p % 100) == 1}
    return _m(('yhpx', t), f)


def geo(r, ks=None):
    ks = sorted(r) if ks is None else ks
    if not ks or any(k not in r for k in ks):
        return None
    return math.exp(math.fsum(math.log1p(r[k]) for k in ks) * 12 / len(ks)) - 1


def div_first3(t):
    """器 t の最初の3年（36か月）の配当利回り＝配当込みの年率 − 価格の年率"""
    tr, px = yahoo_tr(t), yahoo_px(t)
    ks = sorted(set(tr) & set(px))[:36]
    return max(0.0, geo(tr, ks) - geo(px, ks)), ks[0], ks[-1]


def fx():
    """→ (level {yyyymm: 円/ドル の月末}, chg {yyyymm: その月の変化（円安が正）})"""
    def f():
        d = G.fred('DEXJPUS')
        lv = {}
        y, m = 1949, 4
        while y * 100 + m <= 197012:
            lv[y * 100 + m] = 360.0
            m += 1
            if m > 12:
                y, m = y + 1, 1
        for k, v in d.items():
            if k >= 197101 and k <= END:
                lv[k] = v
        ks = sorted(lv)
        chg = {k: lv[k] / lv[p] - 1 for p, k in zip(ks, ks[1:])}
        return lv, chg
    return _m(('fx',), f)


def shiller_nominal():
    def f():
        import xlrd
        b = M.get('http://www.econ.yale.edu/~shiller/data/ie_data.xls', name='shiller_ie_data.xls', max_age_days=3650)
        sh = xlrd.open_workbook(file_contents=b).sheet_by_name('Data')
        lv = {}
        for i in range(8, sh.nrows):
            r = sh.row_values(i)
            if not isinstance(r[0], float) or not isinstance(r[9], float) or not isinstance(r[4], float):
                continue
            s = f'{r[0]:.2f}'
            lv[int(s[:4]) * 100 + int(s[5:7])] = r[9] * r[4]     # 実質トータルリターン × 物価 ＝ 名目トータルリターン
        ms = sorted(lv)
        return {b_: lv[b_] / lv[a_] - 1 for a_, b_ in zip(ms, ms[1:])}
    return _m(('shiller',), f)


def french_mkt():
    return _m(('fmkt',), lambda: M.ff_factors()['mkt'])


def _intl_mkt(name):
    def f():
        for t, v in M.french_tables(name).items():
            if v['freq'] == 'monthly':
                ci = [c.lower() for c in v['cols']]
                out = {}
                for d, row in v['data'].items():
                    a, b = row[ci.index('mkt-rf')], row[ci.index('rf')]
                    if a is not None and b is not None:
                        out[d] = (a + b) / 100
                return out
        raise KeyError(name)
    return _m(('intl', name), f)


def ind49():
    def f():
        tabs = M.french_tables('49_Industry_Portfolios')
        ret = next(v for k, v in tabs.items() if k.startswith('Average Value Weighted Returns') and v['freq'] == 'monthly')
        nf = next(v for k, v in tabs.items() if k.startswith('Number of Firms') and v['freq'] == 'monthly')
        sz = next(v for k, v in tabs.items() if k.startswith('Average Firm Size') and v['freq'] == 'monthly')

        def col(t):
            return {c: {d: row[i] for d, row in t['data'].items() if row[i] is not None} for i, c in enumerate(t['cols'])}
        return col(ret), col(nf), col(sz)
    return _m(('ind49',), f)


def french_ind(names):
    """業種を前月末の時価総額（社数×平均時価総額）で加重した月次リターン（小数）"""
    ret, nf, sz = ind49()
    out = {}
    months = sorted(set().union(*[set(ret[n]) for n in names]))
    for m in months:
        num = den = 0.0
        for n in names:
            r, k, z = ret[n].get(m), nf[n].get(m), sz[n].get(m)
            if r is None or r <= -99 or not k or not z or k <= 0 or z <= 0:
                continue
            w = k * z
            num += w * r / 100
            den += w
        if den > 0:
            out[m] = num / den
    return out


def ind_share(name):
    ret, nf, sz = ind49()
    sh = {}
    for m in nf[name]:
        tot = 0.0
        for n in nf:
            k, z = nf[n].get(m), sz[n].get(m)
            if k and z and k > 0 and z > 0:
                tot += k * z
        k, z = nf[name].get(m), sz[name].get(m)
        if tot and k and z and k > 0 and z > 0:
            sh[m] = k * z / tot
    return sh


def french_pf(ds, col, want):
    return _m(('fpf', ds, col, want), lambda: M.french_series(ds, want=want)[col])


def french_me_6to10():
    def f():
        pme = M.french_series('Portfolios_Formed_on_ME', want='Average Value Weight Returns')
        dec = ['6-Dec', '7-Dec', '8-Dec', '9-Dec', 'Hi 10']
        return {k: sum(pme[d][k] for d in dec) / len(dec) for k in pme['6-Dec'] if all(k in pme[d] for d in dec)}
    return _m(('me610',), f)


def dev20():
    def f():
        ss = {c: G.french_country(c, 'Dollar') for c in DEV20}
        months = sorted(set().union(*[set(s) for s in ss.values()]))
        out = {}
        for m in months:
            v = [s[m] for s in ss.values() if m in s]
            if len(v) >= 10:
                out[m] = sum(v) / len(v)
        return out
    return _m(('dev20',), f)


def msci(code, ccy):
    def f():
        url = (f'https://app2.msci.com/products/service/index/indexmaster/getLevelDataForGraph?currency_symbol={ccy}&index_variant=NETR'
               f'&start_date=19970101&end_date={END}30&data_frequency=END_OF_MONTH&baseValue=false&index_codes={code}')
        j = json.loads(M.get(url, name=f'bf_msci_{code}_NETR_{ccy}_{END}30.json', max_age_days=30))
        lv = {x['calc_date'] // 100: x['level_eod'] for x in j['indexes']['INDEX_LEVELS']}
        ks = sorted(lv)
        return {k: lv[k] / lv[p] - 1 for p, k in zip(ks, ks[1:]) if k <= END}
    return _m(('msci', code, ccy), f)


def gold_fut():
    def f():
        from etf_forward_rank import gold_futures_monthly
        return gold_futures_monthly()
    return _m(('goldfut',), f)


def fred_gold():
    def f():
        for sid in ('GOLDAMGBD228NLBM', 'GOLDPMGBD228NLBM'):
            try:
                lv = G.fred(sid)
                if len(lv) > 24:
                    ks = sorted(lv)
                    return {k: lv[k] / lv[p] - 1 for p, k in zip(ks, ks[1:])}
            except Exception:
                continue
        return {}
    return _m(('fredgold',), f)


def px_div(idx, veh, inr=False):
    """指数 idx の価格リターン＋器 veh の最初の3年の配当利回りを月割りで足す（inr=True ならルピーをドルへ）"""
    px = yahoo_px(idx)
    y, a, b = div_first3(veh)
    add = (1 + y) ** (1 / 12) - 1
    out = {k: (1 + v) * (1 + add) - 1 for k, v in px.items()}
    if inr:
        inr_lv = G.fred('DEXINUS')
        out2 = {}
        for k, v in out.items():
            p = (k // 100 - 1) * 100 + 12 if k % 100 == 1 else k - 1
            if k in inr_lv and p in inr_lv:
                out2[k] = (1 + v) * inr_lv[p] / inr_lv[k] - 1
        out = out2
    return out, dict(div_yield=round(y, 5), from_vehicle=veh, months=f'{a}〜{b}')



def jita_daily(isin, assoc):
    """投信総合検索ライブラリーの基準価額の日次 CSV → [(yyyymmdd, 基準価額, 分配金)]（END の月末まで）。
    口数の併合・分割（1日で基準価額が2倍以上・半分以下になり、整数比に近い日）は比で戻す（例: 1321 は 2026-07-09 に10口→1口）"""
    def f():
        import re
        p = os.path.join(M.CACHE, f'bf_jita_{assoc}.csv')
        if not (os.path.exists(p) and time.time() - os.path.getmtime(p) < 7 * 86400 and os.path.getsize(p) > 0):
            import nx_jpfunds_data as J
            b = J.Lib().csv(isin, assoc)
            if b is None:
                return []
            open(p + '.tmp', 'wb').write(b)
            os.replace(p + '.tmp', p)
        t = open(p, 'rb').read().decode('cp932', errors='replace').splitlines()
        rows = []
        for line in t[1:]:
            x = line.split(',')
            m = re.match(r'(\d{4})年(\d{2})月(\d{2})日', x[0].strip())
            if not m:
                continue
            d = int(m.group(1) + m.group(2) + m.group(3))
            if d > END * 100 + 31:
                continue
            try:
                nav = float(x[1])
            except ValueError:
                continue
            dv = 0.0
            if len(x) > 3 and x[3].strip():
                try:
                    dv = float(x[3])
                except ValueError:
                    dv = 0.0
            rows.append((d, nav, dv))
        rows.sort()
        adj, out = 1.0, []
        for i, (d, nav, dv) in enumerate(rows):
            if i:
                q = rows[i - 1][1] / nav            # 前日 ÷ 今日
                for k in (2, 3, 4, 5, 10, 20, 50, 100):
                    if abs(q * k - 1) < 0.05:        # 今日が前日の約 k 倍＝k口→1口の併合
                        adj /= k
                    if abs(q / k - 1) < 0.05:        # 今日が前日の約 1/k＝1口→k口の分割
                        adj *= k
            out.append((d, nav * adj, dv * adj))
        return out
    return _m(('jita', assoc), f)


def jita_monthly(isin, assoc):
    """日次の基準価額＋分配金 → 月次の総リターン（最初の日の月は使わない）"""
    rows = jita_daily(isin, assoc)
    out, acc, cur = {}, 1.0, None
    for (d0, n0, _), (d1, n1, v1) in zip(rows, rows[1:]):
        ym = d1 // 100
        if cur is not None and ym != cur:
            out[cur] = acc - 1
            acc = 1.0
        cur = ym
        acc *= (n1 + v1) / n0
    if cur is not None:
        out[cur] = acc - 1
    if rows:
        out.pop(rows[0][0] // 100, None)
    # 月の途中で終わった最後の月は使わない
    if rows and rows[-1][0] % 100 < 25:
        out.pop(rows[-1][0] // 100, None)
    return {k: v for k, v in out.items() if k <= END}


def div_first3_nav(isin, assoc):
    """器の最初の3年の分配金利回り（基準価額の総リターン − 価格だけのリターン）"""
    rows = jita_daily(isin, assoc)
    tr = jita_monthly(isin, assoc)
    pxm, last = {}, {}
    for d, nav, _ in rows:
        last[d // 100] = nav
    ks = sorted(last)
    pxr = {k: last[k] / last[p] - 1 for p, k in zip(ks, ks[1:])}
    common = sorted(set(tr) & set(pxr))[:36]
    return max(0.0, geo(tr, common) - geo(pxr, common)), common[0], common[-1]


def source(spec):
    """→ (月次リターン dict, 補足 dict)"""
    kind = spec[0]
    if kind == 'yahoo':
        return yahoo_tr(spec[1]), {}
    if kind == 'yahoo_from':
        return {k: v for k, v in yahoo_tr(spec[1]).items() if k >= spec[2]}, {
            'note': f'{spec[2]} より前は指数の発表前の試算（後から選んだ銘柄での計算）なので使わない'}
    if kind == 'jita_nav':
        return jita_monthly(spec[1], spec[2]), {'note': 'Yahoo の配当込みの値が壊れていた（毎年7月に−400%など）ので投信協会の基準価額と分配金で作った'}
    if kind == 'px_div_nav':
        px = yahoo_px(spec[1])
        y, a, b = div_first3_nav(spec[2], spec[3])
        add = (1 + y) ** (1 / 12) - 1
        return {k: (1 + v) * (1 + add) - 1 for k, v in px.items()}, dict(div_yield=round(y, 5), from_vehicle=spec[3], months=f'{a}〜{b}')
    if kind == 'px_div':
        return px_div(spec[1], spec[2])
    if kind == 'px_div_inr':
        return px_div(spec[1], spec[2], inr=True)
    if kind == 'shiller':
        return shiller_nominal(), {}
    if kind == 'french_mkt':
        return french_mkt(), {}
    if kind == 'french_dxus':
        return _intl_mkt('Developed_ex_US_3_Factors'), {}
    if kind == 'french_em':
        return _intl_mkt('Emerging_5_Factors'), {}
    if kind == 'french_region':
        return _intl_mkt(spec[1]), {}
    if kind == 'french_tech':
        return _m(('ftech',), G.french_tech), {}
    if kind == 'french_ind':
        return _m(('find', tuple(spec[1])), lambda: french_ind(spec[1])), {}
    if kind == 'french_ind_minshare':
        s = french_ind([spec[1]])
        sh = ind_share(spec[1])
        return {k: v for k, v in s.items() if sh.get(k, 0) >= spec[2]}, {'min_share': spec[2]}
    if kind == 'french_pf':
        return french_pf(spec[1], spec[2], spec[3]), {}
    if kind == 'french_me_6to10':
        return french_me_6to10(), {}
    if kind == 'french_country':
        return G.french_country(spec[1], spec[2]), {}
    if kind == 'dev20':
        return dev20(), {'countries': DEV20}
    if kind == 'msci':
        return msci(spec[1], spec[2]), {}
    if kind == 'gold_fut':
        return gold_fut(), {}
    if kind == 'fred_gold':
        return fred_gold(), {}
    if kind == 'blend':
        parts = [(source(s)[0], w) for s, w in spec[1]]
        ks = set(parts[0][0])
        for p, _ in parts[1:]:
            ks &= set(p)
        return {k: sum(p[k] * w for p, w in parts) for k in ks}, {'weights': [w for _, w in spec[1]]}
    raise KeyError(kind)


def _prev(m):
    return (m // 100 - 1) * 100 + 12 if m % 100 == 1 else m - 1


def build_chain(bet, spec_list=None):
    """→ (月次リターン {yyyymm: 小数}（ドル建て、日本の賭けは円建て）, 区間の表 list, つなぎ目の点検 list)"""
    out, segs, checks = {}, [], []
    boundary = None
    prev_series = None
    for kind, spec, label in (spec_list or CHAINS[bet]):
        s, extra = source(spec)
        if kind == 'actual':
            er = ACTUAL_ER[spec[3] if spec[0] == 'jita_nav' else spec[1]]
            s = {k: v + er / 12 for k, v in s.items()}
        s = {k: v for k, v in s.items() if k <= END}
        if not s:
            segs.append(dict(label=label, kind=kind, months=0, note='取れなかった'))
            continue
        if boundary is None:
            # 最後の月から遡って続いている塊だけ使う
            m = max(s)
            take = []
            while m in s:
                take.append(m)
                m = _prev(m)
        else:
            m = _prev(boundary)
            take = []
            while m in s:
                take.append(m)
                m = _prev(m)
            # つなぎ目の点検: 重なる24か月以上の相関と年率
            if prev_series is not None:
                ov = sorted(k for k in s if k in prev_series and k >= boundary)
                if len(ov) >= 24:
                    checks.append(dict(newer=segs[-1]['label'] if segs else None, older=label, overlap=len(ov),
                                       corr=round(M.corr([s[k] for k in ov], [prev_series[k] for k in ov]), 3),
                                       geo_newer=round(100 * geo(prev_series, ov), 2), geo_older=round(100 * geo(s, ov), 2)))
        if not take:
            segs.append(dict(label=label, kind=kind, months=0, note='つなぎ目の前の月が無い（つなげない）'))
            continue
        for k in take:
            out[k] = s[k]
        boundary = min(take)
        segs.append(dict(label=label, kind=kind, frm=min(take), to=max(take), months=len(take), **({'extra': extra} if extra else {})))
        prev_series = s
    return out, segs, checks


def chain_prereg(bet):
    """事前登録どおりのつなぎ（是正の前）→ {'usd':…, 'jpy':…}"""
    r, segs, _ = build_chain(bet, CHAINS_PREREG[bet])
    usd, jpy = (to_usd(r), r) if bet in JPY_NATIVE else (r, to_jpy(r))
    return {'usd': usd, 'jpy': jpy, 'segs': segs, 'first': min(r), 'last': max(r)}


def to_jpy(r_usd):
    _, chg = fx()
    return {k: (1 + v) * (1 + chg[k]) - 1 for k, v in r_usd.items() if k in chg}


def to_usd(r_jpy):
    _, chg = fx()
    return {k: (1 + v) / (1 + chg[k]) - 1 for k, v in r_jpy.items() if k in chg}


def chains(refresh=False):
    """→ {賭け: {'usd': {...}, 'jpy': {...}, 'segs': [...], 'checks': [...], 'proxy_until': yyyymm or None, 'first': .., 'first_actual_or_index': ..}}"""
    if not refresh and os.path.exists(CACHE_JSON) and time.time() - os.path.getmtime(CACHE_JSON) < 3 * 86400:
        d = json.load(open(CACHE_JSON))
        for b in d['bets'].values():
            for c in ('usd', 'jpy'):
                b[c] = {int(k): v for k, v in b[c].items()}
        return d['bets']
    res = {}
    for b in CHAINS:
        r, segs, checks = build_chain(b)
        if b in JPY_NATIVE:
            jpy, usd = r, to_usd(r)
        else:
            usd, jpy = r, to_jpy(r)
        proxy_months = [s for s in segs if s.get('kind') == 'proxy' and s.get('months')]
        real = [s for s in segs if s.get('kind') in ('actual', 'index') and s.get('months')]
        res[b] = dict(usd=usd, jpy=jpy, segs=segs, checks=checks,
                      first=min(r) if r else None, last=max(r) if r else None,
                      first_real=min(s['frm'] for s in real) if real else None,
                      first_actual=min((s['frm'] for s in segs if s.get('kind') == 'actual' and s.get('months')), default=None),
                      proxy_until=max(s['to'] for s in proxy_months) if proxy_months else None)
    os.makedirs(M.CACHE, exist_ok=True)
    json.dump({'generated': datetime.datetime.utcnow().isoformat(), 'bets': res}, open(CACHE_JSON, 'w'))
    return res


def main():
    res = chains(refresh=True)
    print(f"{'賭け':10} {'最初':>6} {'実物/指数':>8} {'代わり〜':>8} {'最後':>6}  区間")
    for b, d in res.items():
        segs = ' ← '.join(f"{s['label']}[{s.get('frm','-')}〜{s.get('to','-')}]" for s in d['segs'] if s.get('months'))
        print(f"{b:10} {d['first']} {d['first_real']} {str(d['proxy_until']):>8} {d['last']}  {segs}")
        for c in d['checks']:
            print(f"     つなぎ目 {c['older']}: 重なり{c['overlap']}か月 相関{c['corr']} 年率 新{c['geo_newer']}% 旧{c['geo_older']}%")
    print('→', CACHE_JSON)


if __name__ == '__main__':
    main()
