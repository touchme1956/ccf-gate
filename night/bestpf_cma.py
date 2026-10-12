#!/usr/bin/env python3
"""night/bestpf_cma.py — R3: 2026年に公表された長期の予想（Capital Market Assumptions）を集めて「D の世界」を作る（2026-10-12）

読むだけ。門・採点・配分（portfolio.json）には触れない。事前登録 out/bestpf_prereg.json（7c4b672）の modules.R3_cma_2026 どおり。

  集めたもの … 運用会社・研究機関が公表した 5〜15年の株式の予想（数字・URL・公表日・期間・名目/実質・通貨）。
                 原本（PDF・Excel・JSON・ページ）は out/_bestpf_cache/cma/ に置き、--verify で表の数字が原本に在るかを確かめる。
  そろえ方   … 名目ドルの複利（幾何）にそろえる。
                 ・実質しか出さない会社（GMO）は (1+実質)×(1+2.5%)−1（事前登録）。GMO の2つの金利の場合は中点（etf_forward_rank の S4 と同じ）。
                 ・算術平均で出す会社（State Street）は 算術 − σ²/2（その会社の長期の標準偏差 σ）で複利へ。
                 ・幅で出す会社（Vanguard）は幅の中点。
                 ・他の通貨は換算しない（事前登録）。「ドル建てのものを優先」＝ドル建ての値が5社以上ある種類はドル建てだけの中央値。
                   米国外を現地通貨でしか出さない値（NT・Amundi・AQR・SSGA・GMO の米国外）は、ドル建てが5社未満の種類でだけ使う（感度 S_all_currency で全部混ぜた値も出す）。
  主に使う版 … 「2026年版と名乗る版、または2026年に公表された版」。Goldman Sachs（2025-11-12・2026年版と名乗らない）は感度だけ。
  D の世界   … 種類ごとに会社の値の中央値（5社以上の種類だけ）と、使った会社の期間の中央値 H。
                 D_gross＝(H×中央値＋(20−H)×B)/20（C と同じ作り）・D_net＝D_gross − 経費率 − 外国税（etf_forward_rank の行から）。
                 5社に届かない種類に割り当てた本は D＝C（事前登録）。
  当たり外れ … 公表された点検（BNY 2016→2025・Northern Trust 2020→2025・Tower 2008 の GMO 2000→2008）と、手で突き合わせ
                 （GMO 2013・2014 の7年予想、GMO 2021 と Vanguard 2018・JPM 2021 は途中経過）、CAPE の10年予想（Shiller のデータ）。
  今の値段   … CAPE（Research Affiliates 2026-09-30）・予想PER と利益の伸び（FactSet 2026-10-09）・上位10社の比重（SPY 2026-10-08）・
                 大手4社の設備投資（SEC の XBRL）。

使い方: python3 night/bestpf_cma.py            … 計算して out/bestpf_cma_2026.json を書く
        python3 night/bestpf_cma.py --verify   … 表の数字が原本（キャッシュ）に在るかだけを確かめる
出力: out/bestpf_cma_2026.json
"""
import csv, datetime, gzip, io, json, math, os, re, statistics as S, subprocess, sys, time, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
CACHE = os.path.join(BASE, 'out', '_bestpf_cache', 'cma')
OUT = os.path.join(BASE, 'out', 'bestpf_cma_2026.json')
PREREG = 'out/bestpf_prereg.json（7c4b672）modules.R3_cma_2026'
INFL = 0.025                    # 実質→名目（事前登録）
HZ = 20                         # 積立の期間（C と同じ）
MIN_HOUSES = 5                  # 5社以上の種類だけ D を作る（事前登録）
SEC_UA = {'User-Agent': 'ccf-gate research fortis5280@gmail.com', 'Accept-Encoding': 'gzip'}   # night/mw_best_ideas_13f.py と同じ
KEYS = ['USL', 'USS', 'USV', 'USG', 'EAFE', 'EUR', 'JP', 'EM', 'IND', 'CHN', 'ACWI', 'QUALITY', 'DIV', 'MOM',
        'SEC_TECH', 'SEC_SEMI', 'SEC_IND', 'SEC_FIN', 'SEC_UTIL', 'SEC_ENERGY', 'SEC_HEALTH']
KEY_JA = {'USL': '米国大型', 'USS': '米国小型', 'USV': '米国バリュー', 'USG': '米国グロース', 'EAFE': '先進国（米国除く）',
          'EUR': '欧州', 'JP': '日本', 'EM': '新興国', 'IND': 'インド', 'CHN': '中国', 'ACWI': '全世界', 'QUALITY': '質（クオリティ）',
          'DIV': '高配当', 'MOM': '勢い（モメンタム）', 'SEC_TECH': 'テクノロジー', 'SEC_SEMI': '半導体', 'SEC_IND': '資本財',
          'SEC_FIN': '金融', 'SEC_UTIL': '公益', 'SEC_ENERGY': 'エネルギー', 'SEC_HEALTH': 'ヘルスケア'}


# ════════════════════════════ 会社ごとの数字の表 ════════════════════════════
# v: {キー: dict(x=数字(%), label=原本の名前, cur='USD'|'local', ...)}。数字は原本の表記のまま（%）。
#   kind: 'nom'（名目の複利）/'real_pair'（GMO: 通常金利と低金利の実質）/'real'/'arith'（算術・sd=σ）/'range'（lo,hi）
#   ref: キャッシュの原本の中の場所（--verify で確かめる文字列）
HOUSES = [
    dict(id='JPM', name='J.P. Morgan Asset Management', edition='2026 Long-Term Capital Market Assumptions（30th）',
         urls=['https://am.jpmorgan.com/content/dam/jpm-am-aem/global/en/insights/ltcma-2026-us-matrix_usd.pdf',
               'https://am.jpmorgan.com/content/dam/jpm-am-aem/global/en/insights/portfolio-insights/ltcma/noindex/ltcma-full-report.pdf'],
         published='2025-10-20', published_src='PDF の作成日 2025-10-20・プレスリリース 2025-10（Morningstar 転載 PR Newswire 20251020）',
         asof='2025-09-30', H=12.5, horizon='10〜15年', basis='名目・複利（compound）', currency='USD',
         main=True, main_why='2026年版と名乗る版（課題文が名指し）。公表は2025年10月',
         file='jpm_2026_us_matrix_usd.pdf',
         v={'USL': dict(x=6.70, label='U.S. Large Cap', cur='USD'),
            'USS': dict(x=6.90, label='U.S. Small Cap', cur='USD'),
            'EUR': dict(x=7.80, label='Euro Area Large Cap', cur='USD'),
            'JP': dict(x=8.80, label='Japanese Equity', cur='USD'),
            'EAFE': dict(x=7.50, label='EAFE Equity', cur='USD'),
            'CHN': dict(x=7.70, label='Chinese Domestic Equity', cur='USD'),
            'EM': dict(x=7.80, label='Emerging Markets Equity', cur='USD'),
            'ACWI': dict(x=7.00, label='AC World Equity', cur='USD'),
            'USV': dict(x=7.70, label='U.S. Equity Value Factor', cur='USD'),
            'MOM': dict(x=7.60, label='U.S. Equity Momentum Factor', cur='USD'),
            'QUALITY': dict(x=6.60, label='U.S. Equity Quality Factor', cur='USD'),
            'DIV': dict(x=7.50, label='U.S. Equity Dividend Yield Factor', cur='USD')},
         extra={'U.S. Mid Cap': 7.00, 'UK Large Cap': 6.60, 'Hong Kong Equity': 7.40, 'AC Asia ex-Japan Equity': 7.90,
                'U.S. Equity Minimum Volatility Factor': 7.00, 'U.S. Inflation': 2.50}),
    dict(id='VG', name='Vanguard（VCMM）', edition='VCMM 2026年6月30日の計算（Vanguard Economic and Market Outlook の予想ページ）',
         urls=['https://corporate.vanguard.com/content/corporatesite/us/en/corp/vemo/vemo-return-forecasts.html',
               'https://corporate.vanguard.com/etc.clientlibs/corporatesite/clientlibs/clientlib-site/resources/dwcharts/i0PwL-3.htm'],
         published='2026-07-22', published_src='予想ページの更新日（WebFetch 2026-10-12）', asof='2026-06-30', H=10, horizon='10年',
         basis='名目・年率（中央値の±1pt の幅で表示 → 中点を使う）', currency='USD（米国外は unhedged＝ドル建て）', main=True,
         main_why='2026年に公表', file='vg_i0PwL-3.htm',
         v={'USL': dict(kind='range', lo=4.1, hi=6.1, label='U.S. large-cap', cur='USD'),
            'USS': dict(kind='range', lo=4.7, hi=6.7, label='U.S. small-cap', cur='USD'),
            'USV': dict(kind='range', lo=6.4, hi=8.4, label='U.S. value', cur='USD'),
            'USG': dict(kind='range', lo=3.6, hi=5.6, label='U.S. growth', cur='USD'),
            'EAFE': dict(kind='range', lo=4.5, hi=6.5, label='Developed markets ex-U.S. equities (unhedged)', cur='USD'),
            'EM': dict(kind='range', lo=2.0, hi=4.0, label='Emerging markets equities (unhedged)', cur='USD')},
         extra={'U.S. equities': '4.2〜6.2', 'Global ex-U.S. equities (unhedged)': '3.9〜5.9', 'U.S. REITs': '3.4〜5.4'}),
    dict(id='GMO', name='GMO', edition='GMO 7-Year Asset Class Forecast: August 2026',
         urls=['https://www.gmo.com/americas/research-library/gmo-7-year-asset-class-forecast-august-2026_gmo7yearassetclassforecast/',
               'https://www.gmo.com/globalassets/articles/gmo-7-year-asset-class-forecast/2026/gmo-7-year-asset-class-forecastaug26.pdf'],
         published='2026-09-21', published_src='GMO の研究ページの日付', asof='2026-08-31', H=7, horizon='7年',
         basis='実質（通常金利＝実質の均衡短期金利1.3%・低金利＝0.0% の2本）→ 中点＋2.5%（事前登録）', currency='米国は USD・米国外は現地（2021年版の注記 "local, real"）',
         main=True, main_why='2026年に公表', file='gmo_2026_08.pdf',
         v={'USL': dict(kind='real_pair', a=-7.4, b=-4.3, label='U.S. Large', cur='USD'),
            'USS': dict(kind='real_pair', a=-5.8, b=-2.8, label='U.S. Small', cur='USD'),
            'USV': dict(kind='real_pair', a=-0.7, b=1.2, label='U.S. Deep Value（割安の深い側＝米国バリューと読む・感度で外す）', cur='USD', approx=True),
            'EAFE': dict(kind='real_pair', a=-1.5, b=0.9, label='Intl Large', cur='local'),
            'EM': dict(kind='real_pair', a=-0.1, b=1.6, label='Emerging', cur='local')},
         extra={'Intl Small': '0.8 / 3.2', 'Intl Deep Value': '3.0 / 4.4', 'Japan Small Value': '4.7 / 6.4', 'Emerging Value': '3.3 / 4.4',
                'U.S. Cash': '1.0'}),
    dict(id='AQR', name='AQR Capital Management', edition='2026 Capital Market Assumptions for Major Asset Classes（Alternative Thinking）',
         urls=['https://www.aqr.com/Insights/Research/Alternative-Thinking/2026-Capital-Market-Assumptions-for-Major-Asset-Classes',
               'https://www.aqr.com/-/media/AQR/Documents/Alternative-Thinking/AQR-Alternative-Thinking---2026-Capital-Market-Assumptions.pdf'],
         published='2026-01-14', published_src='AQR のページ', asof='2025-12-31', H=7.5, horizon='5〜10年（中点 7.5年）',
         basis='Exhibit 3C の名目（現地通貨）を使う（実質は Exhibit 3A）。名目も出しているので +2.5% の換算はしない', currency='米国は USD・米国外は現地',
         main=True, main_why='2026年に公表', file='aqr_2026.pdf',
         v={'USL': dict(x=6.3, real=3.9, label='US Large', cur='USD'),
            'USS': dict(x=7.4, real=5.1, label='US Small', cur='USD'),
            'EUR': dict(x=6.9, real=5.0, label='Euro-zone', cur='local'),
            'JP': dict(x=6.7, real=4.9, label='Japan', cur='local'),
            'EAFE': dict(x=6.9, real=4.9, label='Global Dev. ex US', cur='local'),
            'CHN': dict(x=7.3, real=5.8, label='China', cur='local'),
            'EM': dict(x=7.4, real=5.1, label='All EM', cur='local'),
            'ACWI': dict(x=6.5, real=4.2, label='Global All Ctry', cur='local')},
         extra={'UK 名目/実質': '7.1 / 4.9', 'Global Dev. 名目/実質': '6.5 / 4.2', 'EM ex China 名目/実質': '7.5 / 4.8',
                'Global 60/40 実質': 3.4}),
    dict(id='SCHWAB', name='Charles Schwab（Schwab Asset Management）', edition="Schwab's 2026 Long-Term Capital Market Expectations",
         urls=['https://www.schwab.com/learn/story/schwabs-long-term-capital-market-expectations'],
         published='2026-01-02', published_src='ページの日付（January 2, 2026・更新 2026-03-16）', asof='2025-10-31', H=10, horizon='10年',
         basis='名目・年率（手数料・税なし）', currency='USD（指数は MSCI EAFE/EM の Net Return・ドル）', main=True, main_why='2026年に公表',
         file='schwab_2026_cme.html',
         v={'USL': dict(x=5.9, label='U.S. Large Cap（S&P 500）', cur='USD'),
            'USS': dict(x=5.9, label='U.S. Small Cap（Russell 2000）', cur='USD'),
            'EAFE': dict(x=7.0, label="Int'l Dev Large Cap（MSCI EAFE）", cur='USD'),
            'EM': dict(x=6.8, label='EM（MSCI EM）', cur='USD')},
         extra={"Int'l Dev Small Cap": 8.0, 'U.S. REITs': 6.4, 'U.S. inflation': 2.4}),
    dict(id='BLK', name='BlackRock Investment Institute', edition='BlackRock Capital Market Assumptions（August 2026・Starting point）',
         urls=['https://www.blackrock.com/institutions/en-global/institutional-insights/thought-leadership/capital-market-assumptions',
               'https://www.blackrock.com/blk-inst-c-assets/images/tools/blackrock-investment-institute/cma/blackrock-capital-market-assumptions.xlsx'],
         published='2026-08-11', published_src='ページの日付・表の見出し "August 2026, data as of 30 June 2026"', asof='2026-06-30', H=10,
         horizon='10年（表は5〜30年）', basis='名目・幾何（"All component numbers are geometric"）', currency='USD', main=True, main_why='2026年に公表',
         file='blackrock_cma.xlsx',
         v={'USL': dict(x=8.967651382941, label='US large cap equities（MSCI USA）', cur='USD'),
            'USS': dict(x=7.008477050054, label='US small cap equities（MSCI USA Small Cap）', cur='USD'),
            'EUR': dict(x=7.428417010513, label='Europe large cap equities（MSCI Europe）', cur='USD'),
            'EAFE': dict(x=7.768383596947, label='Global ex-US large cap equities（MSCI World ex-US）', cur='USD'),
            'EM': dict(x=8.798476149849, label='Emerging large cap equities（MSCI EM）', cur='USD'),
            'ACWI': dict(x=9.015125720695, label='All country large cap equities（MSCI ACWI）', cur='USD'),
            'CHN': dict(x=10.267323247186, label='China-Broad market', cur='USD')},
         extra={'Global large cap（MSCI World）10年': 8.64, 'China A-shares 10年': 8.67, 'US large cap 5年/30年': '9.44 / 8.44',
                'シナリオ AI productivity boom の US large cap 10年': 15.94, 'シナリオ Global risk premia rise の US large cap 10年': 2.02,
                '2025-09-30 時点の US equities 10年（Morningstar の記事 2026-01-12）': 5.2}),
    dict(id='SSGA', name='State Street Investment Management', edition='Long-Term Asset Class Forecasts Q3 2026',
         urls=['https://www.ssga.com/library-content/assets/pdf/global/multi-asset/2026/long-term-asset-class-forecasts-q3.pdf'],
         published='2026-07-15', published_src='PDF の作成日', asof='2026-06-30', H=10, horizon='10年以上（"Long term 10+ years"）',
         basis='算術平均（原本の注記 "annual arithmetic averages"）→ 算術 − σ²/2（σ＝原本の Long-term risk）で複利へ', currency='現地（"local (or regional) currency"・為替は含まない）',
         main=True, main_why='2026年に公表', file='ssga_2026_q3.pdf',
         v={'USL': dict(kind='arith', x=6.8, sd=16.1, label='US Large Cap（S&P 500）', cur='USD'),
            'USS': dict(kind='arith', x=7.3, sd=21.0, label='US Small Cap（S&P Small Cap 600）', cur='USD'),
            'EUR': dict(kind='arith', x=5.9, sd=14.7, label='Europe（MSCI Europe）', cur='local'),
            'EAFE': dict(kind='arith', x=6.5, sd=14.0, label='Global Developed ex US（MSCI World ex USA）', cur='local'),
            'EM': dict(kind='arith', x=7.2, sd=16.9, label='Emerging Markets（MSCI EM）', cur='local'),
            'ACWI': dict(kind='arith', x=6.8, sd=14.8, label='Global Equities（MSCI ACWI）', cur='local'),
            'QUALITY': dict(kind='arith', x=6.9, sd=14.1, label='Global Quality（MSCI World Quality）＝世界（米国ではない）', cur='local', approx=True),
            'MOM': dict(kind='arith', x=7.7, sd=15.6, label='Global Momentum（MSCI World Momentum）＝世界（米国ではない）', cur='local', approx=True)},
         extra={'US Mid Cap 算術/σ': '7.1 / 19.1', 'Global Value 算術/σ': '6.3 / 15.1', 'Global Growth 算術/σ': '7.2 / 16.2',
                'MSCI World 算術/σ': '6.7 / 15.0', 'ACWI ex US 算術/σ': '6.8 / 13.9', 'US inflation 10+年': 1.9}),
    dict(id='BNY', name='BNY Investments', edition='Capital Market Assumptions 2026: Endurance Under Pressure（10年）',
         urls=['https://www.bny.com/investments/global/en/capital-market-assumptions-2026.html',
               'https://www.bny.com/content/dam/imemea/documents/global-docs/en/BNY-Investments-2026-Capital-Market-Assumptions-USD.xlsx',
               'https://www.bny.com/content/dam/imemea/pdfs/endurance-under-pressure-capital-market-assumptions-2026-full.pdf'],
         published='2026-01-23', published_src='報告書 PDF の作成日（Excel の注記 BABR-854880-2025-12-17）', asof='2025-12-31', H=10, horizon='10年',
         basis='名目・幾何（Excel の Geometric Return 列）', currency='USD（unhedged）', main=True, main_why='2026年版・2026年に公表',
         file='bny_2026_usd.xlsx',
         v={'USL': dict(x=7.6, label='US Large Cap（Russell 1000）', cur='USD'),
            'USS': dict(x=7.5, label='US Small Cap（Russell 2000）', cur='USD'),
            'USV': dict(x=6.9, label='US Value（Russell 3000 Value）', cur='USD'),
            'USG': dict(x=8.0, label='US Growth（Russell 3000 Growth）', cur='USD'),
            'EUR': dict(x=8.1, label='EMU Equity（MSCI EMU IMI）', cur='USD'),
            'JP': dict(x=6.5, label='Japan Equity（MSCI Japan IMI）', cur='USD'),
            'EAFE': dict(x=7.8, label='Developed ex US Equity（MSCI World ex USA IMI）', cur='USD'),
            'EM': dict(x=8.1, label='Emerging Market Equity（MSCI EM IMI）', cur='USD'),
            'ACWI': dict(x=7.7, label='Global Equity（MSCI ACWI IMI）', cur='USD')},
         extra={'UK Equity': 9.3, 'US Mid Cap': 7.6, 'Developed ex US Small Cap': 8.0, 'United States Inflation': 2.3}),
    dict(id='TROWE', name='T. Rowe Price', edition='Capital Market Assumptions Five-Year Perspective 2026（U.S. Dollar・8th）',
         urls=['https://www.troweprice.com/content/dam/ide/articles/pdfs/2026/capital-market-assumptions-na.pdf'],
         published='2026-03-02', published_src='PDF の更新日（作成 2026-02-24）・2026年3月版', asof='確かめられない（原本に明記なし・2025年末と思われる）', H=5,
         horizon='5年', basis='名目・幾何（"Five-Year Geometric Average"）', currency='USD', main=True, main_why='2026年に公表', file='trowe_2026_na.pdf',
         v={'USL': dict(x=6.4, label='U.S. Large-Cap（Russell 1000）', cur='USD'),
            'USS': dict(x=6.3, label='U.S. Small-Cap（Russell 2000）', cur='USD'),
            'EUR': dict(x=8.1, label='Europe Equity', cur='USD'),
            'JP': dict(x=6.4, label='Japan Equity', cur='USD'),
            'EAFE': dict(x=7.1, label='Developed Market ex-U.S. Equity', cur='USD'),
            'EM': dict(x=8.7, label='EM Equity', cur='USD'),
            'CHN': dict(x=8.7, label='China Equity', cur='USD'),
            'ACWI': dict(x=6.8, label='Global Equity（MSCI ACWI）', cur='USD')},
         extra={'Global ex-U.S. Equity': 7.6, 'Developed Market Equity': 6.6, 'Asia ex-Japan Equity': 8.6, 'Canada Equity': 5.6}),
    dict(id='NT', name='Northern Trust Asset Management', edition='Capital Market Assumptions 10-Year Outlook: 2026 Edition',
         urls=['https://ntam.northerntrust.com/content/dam/northerntrust/investment-management/global/en/documents/thought-leadership/2026/cma/2026-capital-market-assumptions-report.pdf'],
         published='2026-01-14', published_src='プレスリリース（Business Wire 2026-01-14）・表紙は "RELEASED DECEMBER 2025"', asof='2025-09-30',
         H=10, horizon='10年（2025-09-30〜2035-09-30）', basis='名目・幾何（"annualized using geometric averages"）', currency='米国は USD・米国外は現地（実績の列が現地通貨）',
         main=True, main_why='2026年版・プレスリリースは2026年1月', file='nt_2026_cma.pdf',
         v={'USL': dict(x=6.8, label='U.S.（MSCI USA）', cur='USD'),
            'USS': dict(x=7.0, label='U.S. Small Cap（Russell 2000）', cur='USD'),
            'EUR': dict(x=5.7, label='Europe（MSCI Europe ex U.K.）', cur='local'),
            'JP': dict(x=7.3, label='Japan（MSCI Japan）', cur='local'),
            'EM': dict(x=6.9, label='Emerging Markets（MSCI EM）', cur='local'),
            'ACWI': dict(x=6.9, label='Global Equities（MSCI AC World）', cur='local')},
         extra={'U.K.': 6.2, 'Australia': 7.7, 'Canada': 5.8, 'Developed Markets（MSCI World）': 6.8}),
    dict(id='INVESCO', name='Invesco（Investment Solutions）', edition='Capital market assumptions 2Q 2026（USD・10年）',
         urls=['https://www.invesco.com/ch/en/insights/capital-markets-assumptions.html',
               'https://www.invesco.com/content/dam/invesco/emea/en/pdf/invesco-capital-market-assumption-usd.pdf'],
         published='2026-04-26', published_src='Invesco のページ（Q2 2026・26 April 2026）・PDF の作成 2026-07-23', asof='2026-03-31', H=10, horizon='10年',
         basis='名目・幾何（Figure 6 の "Expected geometric"）', currency='USD', main=True, main_why='2026年に公表', file='invesco_cma_usd.pdf',
         v={'USL': dict(x=4.9, label='US large cap（S&P 500）', cur='USD'),
            'USS': dict(x=4.5, label='US small cap（S&P 600）', cur='USD'),
            'EUR': dict(x=7.2, label='Europe equity（MSCI Europe）', cur='USD'),
            'JP': dict(x=8.6, label='Japan equity（MSCI JP）', cur='USD'),
            'EM': dict(x=7.1, label='EM equity（MSCI EM）', cur='USD'),
            'CHN': dict(x=5.8, label='China equity（MSCI China）', cur='USD'),
            'ACWI': dict(x=5.9, label='Global equity（MSCI ACWI）', cur='USD')},
         extra={'Global ex-US equity（MSCI ACWI ex-US・新興国を含むので EAFE には使わない）': 7.2, 'US broad market（S&P 1500）': 5.1,
                'US mid cap（S&P 400）': 8.3, 'Developed market（MSCI World）': 5.8, 'UK large cap': 9.4, 'APAC ex-JP': 5.7}),
    dict(id='AMUNDI', name='Amundi Investment Institute', edition='Capital Market Assumptions H2 update（August 2026）',
         urls=['https://research-center.amundi.com/files/nuxeo/dl/6df1bf9d-44de-412e-aa5c-4578e393e8b0'],
         published='2026-08-18', published_src='PDF の作成日・表紙 "August 2026"', asof='2026-06-30', H=10, horizon='10年',
         basis='名目・幾何（"Average Annualised GEOMETRIC 10-year Expected Returns"）', currency='現地（"Assets in local currency"）',
         main=True, main_why='2026年に公表', file='amundi_cma_h2_2026.pdf',
         v={'USL': dict(x=7.0, label='US Equity（NDDLUS）', cur='USD'),
            'EUR': dict(x=6.9, label='Europe Equity', cur='local'),
            'JP': dict(x=6.2, label='Japan Equity', cur='local'),
            'EM': dict(x=6.7, label='Emerging Markets Equity', cur='local'),
            'CHN': dict(x=9.3, label='China Equity', cur='local'),
            'IND': dict(x=7.8, label='India Equity', cur='local'),
            'ACWI': dict(x=7.0, label='AC World Equity', cur='local')},
         extra={'Euro zone Equity': 6.7, 'UK Equity': 7.2, 'Pacific ex Japan Equity': 7.0, 'World Equity': 7.0,
                'US Equity 5年平均': 7.3, '円は長期の適正値より約31%割安（JPYUSD）': '-31%'}),
    dict(id='RA', name='Research Affiliates（Asset Allocation Interactive）', edition='AAI（Valuation Dependent モデル・データ 2026-09-30・計算 2026-10-02）',
         urls=['https://interactive.researchaffiliates.com/asset-allocation',
               'https://interactive.researchaffiliates.com/asset-allocation-data/202610/02/usd/nominal/er/expected_return.json',
               'https://interactive.researchaffiliates.com/asset-allocation-data/202610/02/usd/asset.json'],
         published='2026-10-02', published_src='ページの設定 runDate 10/02/2026・dataDate 09/30/2026', asof='2026-09-30', H=10, horizon='10年',
         basis='名目・年率（usd/nominal/er）。実質も同じ所にある', currency='USD', main=True, main_why='2026年に公表', file='ra/usd_nominal_er_expected_return.json',
         v={'USL': dict(x=3.28, real=0.55, label='US Large（assetId 1）', cur='USD', aid=1),
            'USS': dict(x=7.58, real=4.84, label='US Small（assetId 4・Russell 2000）', cur='USD', aid=4),
            'USV': dict(x=3.85, real=1.12, label='US Large Value（assetId 2）', cur='USD', aid=2),
            'USG': dict(x=1.78, real=-0.95, label='US Large Growth（assetId 3）', cur='USD', aid=3),
            'EUR': dict(x=7.46, real=4.73, label='Europe（assetId 31）', cur='USD', aid=31),
            'JP': dict(x=8.83, real=6.09, label='Japan（assetId 11）', cur='USD', aid=11),
            'EAFE': dict(x=7.87, real=5.14, label='Dev ex US Large（assetId 32）', cur='USD', aid=32),
            'EM': dict(x=6.53, real=3.80, label='Emerging Markets（assetId 33）', cur='USD', aid=33),
            'CHN': dict(x=8.99, real=6.25, label='China（assetId 17）', cur='USD', aid=17),
            'IND': dict(x=5.72, real=2.99, label='India（assetId 18）', cur='USD', aid=18),
            'ACWI': dict(x=4.75, real=2.01, label='All Country（assetId 29）', cur='USD', aid=29)},
         extra={'US Small Value': 8.96, 'US Small Growth': 5.95, 'Dev ex US Large Value': 8.50, 'EM Value': 8.28, 'Taiwan': 3.55,
                'South Korea': 5.56}),
    dict(id='MSTAR', name='Morningstar（Multi-Asset Research・社外非公開）', edition='Morningstar の記事 "Experts Forecast Stock and Bond Returns: 2026 Edition"（Christine Benz）が載せた自社の数字',
         urls=['https://www.morningstar.com/markets/experts-forecast-stock-bond-returns-2026-edition'],
         published='2026-01-12', published_src='記事の日付', asof='2025-12-31', H=10, horizon='10年', basis='名目', currency='USD（記事に明記なし・米国の投資家向けの記事）',
         main=True, main_why='2026年に公表（ただし原本の表は社外非公開＝記事の数字）', file='morningstar_experts_2026.html',
         v={'USL': dict(x=5.3, label='US stocks', cur='USD'),
            'EAFE': dict(x=7.5, label='non-US developed-market stocks', cur='USD'),
            'EM': dict(x=9.9, label='emerging-market equities', cur='USD')},
         extra={}),
    dict(id='FIDI', name='Fidelity International', edition='Capital market assumptions update H1 2026（10年）',
         urls=['https://www.fidelity.com.au/sites/fidelity/assets/capital-market-assumptions-update-h1-2026-fidelity-international.pdf'],
         published='2026-04-30', published_src='原本 "Source: Fidelity International, April 2026"（PDF 作成 2026-05-07）', asof='2026-03-31', H=10,
         horizon='10年（20年も併記）',
         basis='名目・"Average expected returns" p.a.（幾何か算術かは明記なし → 主は原本の数字のまま・感度 S_fidi_arith で算術と見て 算術−σ²/2 へ。'
               'σ は同じ報告 p.11 の "Volatility assumptions (average)"（USD・2003-09〜2025-09 の月次の実績から）: DM equities 15.3%・EM equities 20.2%。'
               '米国株の σ は表に無いので DM equities（MSCI World）で代える）', currency='USD',
         main=True, main_why='2026年に公表', file='fidelity_intl_h1_2026.pdf',
         v={'USL': dict(x=6.4, sd=15.3, sd_src='p.11 Volatility assumptions の DM equities（米国株の σ は無い → 代用）', label='US Equities', cur='USD'),
            'EM': dict(x=8.0, sd=20.2, sd_src='p.11 Volatility assumptions の EM equities', label='Emerging Markets Equities', cur='USD')},
         extra={'Developed Markets Equities（MSCI World）10年': 6.7, 'Global Small Cap 10年': 7.1, 'US Equities 20年': 7.4, 'EM 20年': 8.9,
                'Fidelity（米国・Fidelity Institutional）の20年 US 5.8% は2025年版（Morningstar の記事）＝使わない': None}),
    dict(id='ROBECO', name='Robeco', edition='Expected Returns 2027-2031: The Great Rewiring（16th）',
         urls=['https://www.robeco.com/en-int/insights/2026/09/5-year-expected-returns-the-great-rewiring',
               'https://www.robeco.com/files/docm/docu-summary-expected-returns-2027-2031-en.pdf'],
         published='2026-09-16', published_src='要約 PDF の作成日', asof='確かめられない（要約に明記なし）', H=5, horizon='5年（2027〜2031）',
         basis='名目・年率', currency='USD 版の列（EUR・JPY・GBP 版もある）', main=True, main_why='2026年に公表', file='robeco_er_2027_2031_summary.pdf',
         v={'EM': dict(x=8.75, label='Emerging market equities（USD）', cur='USD')},
         extra={'Developed market equities（USD・世界＝米国を含む）': 7.75, 'Developed market equities（EUR）': 7.00,
                'Emerging market equities（EUR）': 8.00, 'USD inflation': 3.00}),
    # ── 感度だけ ──
    dict(id='GS', name='Goldman Sachs（Global Investment Research・Oppenheimer ほか）', edition='Global Strategy Paper "Building Long-Term Returns: Our 10-Year Forecasts"',
         urls=['https://www.gspublishing.com/content/research/en/reports/2025/11/12/0c292cc7-ce42-4fba-a026-744231e9f4f4.pdf'],
         published='2025-11-12', published_src='報告書の日付', asof='2025-11（報告書の日付）', H=10, horizon='10年', basis='名目・年率', currency='現地（"regional returns are expressed in local currency"）・全世界だけ USD 7.7%',
         main=False, main_why='2025年11月公表で2026年版と名乗らない → 主から外し感度 S_with_GS だけ', file='gs_10y_2025-11-12.pdf',
         v={'USL': dict(x=6.5, label='United States（S&P 500）', cur='USD'),
            'EUR': dict(x=7.1, label='Europe', cur='local'),
            'JP': dict(x=8.2, label='Japan', cur='local'),
            'EM': dict(x=10.9, label='Emerging Markets', cur='local'),
            'ACWI': dict(x=7.7, label='MSCI AC World（USD）', cur='USD')},
         extra={'Asia ex-Japan': 10.3, 'MSCI AC World（現地通貨）': 7.1, '米国の幅（下〜上の場合）': '3〜10',
                '同社 David Kostin らの 2024-10-18 の10年予想（S&P 500）': 3.0}),
]

NOT_OBTAINED = [
    dict(house='Franklin Templeton（Investment Solutions）', edition='Capital Market Expectations 2026（2025-12-10）',
         url='https://www.ftinstitutional.com/articles/2025/multi-asset/capital-market-expectations-2026-can-ai-realize-rich-valuations',
         why='ページが JavaScript で描かれ、curl・WebFetch とも本文（数字）が空。検索でも数字の転載は見つからない＝確かめられない（0 と読まない）'),
    dict(house='Fidelity（米国・Fidelity Institutional）', edition='20年の CMA',
         url='https://institutional.fidelity.com/app/re/item/9904178.html',
         why='最新の数字は2025年版（Morningstar 2026-01-12 の記事: 米国株 20年 名目5.8%）で2026年に公表されたものではない。Fidelity International の H1 2026（10年）を Fidelity の行として使う'),
]

# 事前登録の外の会社（参考の照合だけ・D には入れない）
CROSS_CHECK = dict(
    source='PortfolioLab「Capital Market Assumptions」比較（2026-09-09 更新・二次資料）',
    url='https://www.portfoliolab.app/capital-market-assumptions/northern-trust',
    medians={'米国株': dict(median=6.3, n=14), '先進国（米国除く）': dict(median=7.3, n=12), '新興国': dict(median=7.7, n=14)},
    note='事前登録の名簿にない Callan・Meketa・PGIM・Verus を含む。版・期間・通貨がそろっていない二次資料なので D には使わない（照合だけ）')

# 候補（etf_forward_rank の C ＋ R7 の拡張）→ D の種類。JPM_MAP と同じ考え方（業種・テーマの ETF は米国大型）。
D_MAP = {'VT': 'ACWI', 'VOO': 'USL', 'VEA': 'EAFE', 'VWO': 'EM', 'TOPIX': 'JP', 'EPI': 'IND', 'EPI_LONG': 'IND', 'QQQM': 'USL', 'VUG': 'USL',
         'XLK': 'USL', 'SMH': 'USL', 'XLV': 'USL', 'XLP': 'USL', 'XLU': 'USL', 'XLE': 'USL', 'ITA': 'USL', 'RSP': 'USL',
         'VTV': 'USV', 'VBR': 'USS', 'IJR': 'USS', 'VIG': 'QUALITY', 'MOAT': 'QUALITY', 'VYM': 'DIV', 'PXF': 'EAFE', 'DEM': 'EM',
         'GLDM': None,
         'MTUM': 'MOM', 'QUAL': 'QUALITY', 'XLI': 'USL', 'XLF': 'USL', 'XLY': 'USL', 'GRID': 'ACWI'}
D_MAP_NOTE = {'EPI': 'JPM_MAP はアジア（日本除く）。D ではインドの種類（2社しかない → C と同じ）',
              'EPI_LONG': 'R7 の EPI の代理つなぎ版（night/bestpf_ext.py）。EPI と同じくインド（2社しかない → C と同じ）',
              'QQQM': '米国グロースの種類は3社（Vanguard 4.6・RA 1.78・BNY 8.0）で5社に届かない → JPM_MAP と同じく米国大型',
              'VUG': '同上（米国グロース 3社）', 'XLK': '業種の予想は見つからない → 米国大型（JPM_MAP と同じ）',
              'SMH': '業種の予想は見つからない → 米国大型（JPM_MAP と同じ）', 'VTV': 'JPM_MAP は JPM のバリュー因子。D では米国バリュー（5社）',
              'GRID': '送電・電化の世界株（米国が過半）。業種の予想は無い → 全世界（JPM_MAP に行は無い）',
              'XLI': '業種の予想は無い → 米国大型', 'XLF': '業種の予想は無い → 米国大型', 'XLY': '業種の予想は無い → 米国大型',
              'MTUM': '勢いは2社（JPM 7.6・SSGA 世界）→ C と同じ', 'QUAL': '質は2社（JPM・SSGA 世界）→ C と同じ',
              'VIG': '質は2社 → C と同じ', 'MOAT': '質は2社 → C と同じ', 'VYM': '高配当は1社（JPM）→ C と同じ',
              'GLDM': '株ではない（事前登録で外す）'}


# ════════════════════════════ そろえる ════════════════════════════
def to_nominal_geo(e):
    """原本の数字 → 名目の複利（小数）と、換算の説明"""
    k = e.get('kind', 'nom')
    if k == 'nom':
        return e['x'] / 100, '原本の名目の複利そのまま'
    if k == 'range':
        m = (e['lo'] + e['hi']) / 2
        return m / 100, f"幅 {e['lo']}〜{e['hi']} の中点 {m:.2f}"
    if k == 'real_pair':
        r = (e['a'] + e['b']) / 2 / 100
        return (1 + r) * (1 + INFL) - 1, f"実質 {e['a']}/{e['b']} の中点 {100 * r:.2f} → (1+実質)×1.025−1"
    if k == 'real':
        return (1 + e['x'] / 100) * (1 + INFL) - 1, '実質 → (1+実質)×1.025−1'
    if k == 'arith':
        a, sd = e['x'] / 100, e['sd'] / 100
        return a - sd * sd / 2, f"算術 {e['x']} − σ²/2（σ={e['sd']}）"
    raise ValueError(k)


def collect(houses, *, usd_only=False, drop=(), approx_ok=True, ssga_arith_raw=False, aqr_real25=False, fidi_arith=False):
    """種類ごとに [(会社, 名目の複利, H, 通貨)]
    fidi_arith: Fidelity International の "Average expected returns"（幾何か算術か明記なし）を算術と見て 算術−σ²/2 へ（σ は同じ報告の表）"""
    out = {k: [] for k in KEYS}
    for h in houses:
        if h['id'] in drop:
            continue
        for k, e in h['v'].items():
            if usd_only and e.get('cur') != 'USD':
                continue
            if not approx_ok and e.get('approx'):
                continue
            if ssga_arith_raw and e.get('kind') == 'arith':
                g = e['x'] / 100
            elif aqr_real25 and h['id'] == 'AQR':
                g = (1 + e['real'] / 100) * (1 + INFL) - 1
            elif fidi_arith and h['id'] == 'FIDI':
                if e.get('sd') is None:
                    raise ValueError(f'FIDI {k} の σ が無い（0 と読まない）')
                g = e['x'] / 100 - (e['sd'] / 100) ** 2 / 2
            else:
                g = to_nominal_geo(e)[0]
            out[k].append((h['id'], g, h['H'], e.get('cur'), bool(e.get('approx'))))
    return out


def d_table(coll, usd_priority=True):
    """種類ごとの中央値。
    usd_priority=True（主・事前登録「名目ドル」）: ドル建ての値だけで中央値を作る。ドル建てが5社未満の種類は D を作らない（D＝C）。
      現地通貨の値も混ぜた中央値は ref_with_local に参考として残すだけ（D には使わない）。
      ※ 2026-10-12 の直し: 以前はドル建てが5社未満の種類で現地通貨を混ぜて D を作れる形だった（主の計算では起きなかった）。
    usd_priority=False（参考の感度 S_all_currency だけ・事前登録の外）: 通貨を問わず全部混ぜる"""
    t = {}
    for k in KEYS:
        xs_all = coll[k]
        usd = [x for x in xs_all if x[3] == 'USD']
        if usd_priority:
            xs = usd
            basis = 'ドル建てだけ（5社以上）' if len(usd) >= MIN_HOUSES else 'ドル建てだけ（5社未満 → D＝C）'
        else:
            xs = xs_all
            basis = 'すべての通貨を混ぜる（参考・事前登録の外）'
        n = len(xs)
        e = dict(n=n, houses=[x[0] for x in xs], values=[round(100 * x[1], 3) for x in xs], basis=basis,
                 n_all=len(xs_all), n_usd=len(usd),
                 dropped_local=[(x[0], round(100 * x[1], 3)) for x in xs_all if x not in xs])
        if n:
            e['median'] = S.median(x[1] for x in xs)
            e['H_median'] = S.median(x[2] for x in xs)
            e['min'] = min(x[1] for x in xs); e['max'] = max(x[1] for x in xs)
            e['n_local_currency'] = sum(1 for x in xs if x[3] != 'USD')
        if usd_priority and len(xs_all) > len(usd):
            e['ref_with_local'] = dict(n=len(xs_all), median=S.median(x[1] for x in xs_all),
                                       note='現地通貨の値も混ぜた参考（名目ドルではない値を含む → D には使わない）')
        e['made'] = n >= MIN_HOUSES
        t[k] = e
    return t


def d_net_rows(table, rows):
    """候補ごとの D（正味）。rows は etf_forward_rank の行（B_gross・er_vehicle・tax_drag・C）"""
    out, detail = {}, {}
    for c, key in D_MAP.items():
        r = rows.get(c)
        e = table.get(key) if key else None
        if key is None:
            detail[c] = dict(key=None, note=D_MAP_NOTE.get(c))
            continue
        if e and e['made']:
            H = e['H_median']
            if r is None:
                detail[c] = dict(key=key, D_made=True, cma=e['median'], H=H, pending=True,
                                 note='この本の B・経費率・外国税（R7 の行）がまだ無い → D_net は未計算。D_net=(H×cma+(20−H)×B_gross)/20−er−tax')
                continue
            g = (H * e['median'] + (HZ - H) * r['B_gross']) / HZ
            net = g - r['er_vehicle'] - r['tax_drag']
            out[c] = net
            detail[c] = dict(key=key, D_made=True, cma=round(e['median'], 5), H=H, B_gross=round(r['B_gross'], 5),
                             D_gross=round(g, 5), er=r['er_vehicle'], tax=round(r['tax_drag'], 5), D_net=round(net, 5),
                             C_net=round(r['C'], 5), D_minus_C=round(net - r['C'], 5), note=D_MAP_NOTE.get(c))
        else:
            if r is None:
                detail[c] = dict(key=key, D_made=False, pending=True, note=(D_MAP_NOTE.get(c) or '') + '・5社未満 → D＝C（R7 の C を使う）')
                continue
            out[c] = r['C']
            detail[c] = dict(key=key, D_made=False, D_net=round(r['C'], 5), C_net=round(r['C'], 5),
                             note=(D_MAP_NOTE.get(c) or '') + f"・{KEY_JA.get(key, key)}は {e['n'] if e else 0} 社で5社未満 → D＝C（事前登録）")
    return out, detail


# ════════════════════════════ 原本との照合（--verify） ════════════════════════════
def _pdftext(name, layout=True):
    p = os.path.join(CACHE, name)
    args = ['pdftotext'] + (['-layout'] if layout else ['-raw']) + [p, '-']
    return subprocess.run(args, capture_output=True, text=True).stdout


def _num_in_line(text, label_re, num):
    """label_re を含む行に num（表記のまま）があるか"""
    for line in text.splitlines():
        if re.search(label_re, line) and re.search(r'(?<![\d.])' + re.escape(num) + r'(?![\d])', line):
            return True
    return False


def verify():
    res = []

    def ok(h, k, good, how):
        res.append(dict(house=h, key=k, ok=bool(good), how=how))

    # JPM（行の先頭が名前・最初の数字が 2026 の複利）
    t = _pdftext('jpm_2026_us_matrix_usd.pdf', layout=False)
    jp = next(h for h in HOUSES if h['id'] == 'JPM')
    for k, e in jp['v'].items():
        m = re.search(r'^' + re.escape(e['label']) + r' (\d+\.\d\d) ', t, flags=re.M)
        ok('JPM', k, m and abs(float(m.group(1)) - e['x']) < 1e-9, f"matrix の行 '{e['label']} {m.group(1) if m else '?'}'")
    # 照合: リポジトリの etf_forward_rank.JPM と同じか
    try:
        import etf_forward_rank as R
        rep = {'ACWI': 'ACWI', 'USL': 'USL', 'USS': 'USS', 'EAFE': 'EAFE', 'JP': 'JP', 'EM': 'EM', 'USV': 'VALUE', 'QUALITY': 'QUALITY', 'DIV': 'DIV'}
        for k, rk in rep.items():
            ok('JPM×repo', k, abs(R.JPM[rk] - jp['v'][k]['x']) < 1e-9, f'night/etf_forward_rank.py の JPM[{rk}]={R.JPM[rk]}')
    except Exception as ex:   # noqa
        ok('JPM×repo', '-', False, f'読めない: {ex}')
    # Vanguard（datawrapper の CSV）
    s = open(os.path.join(CACHE, 'vg_i0PwL-3.htm'), encoding='utf-8', errors='replace').read()
    for k, e in next(h for h in HOUSES if h['id'] == 'VG')['v'].items():
        lab = e['label']
        good = (f'{lab}\\\\tLow\\\\t{e["lo"]:g}' in s) and (f'{lab}\\\\tHigh\\\\t{e["hi"]:g}' in s)
        ok('VG', k, good, f'CSV の {lab} Low {e["lo"]:g} / High {e["hi"]:g}')
    # GMO（チャートの数字が在るか）
    t = _pdftext('gmo_2026_08.pdf')
    for k, e in next(h for h in HOUSES if h['id'] == 'GMO')['v'].items():
        ok('GMO', k, (f"{e['a']:.1f}%" in t) and (f"{e['b']:.1f}%" in t), f"チャートに {e['a']}% と {e['b']}%（位置は pdftotext -bbox で確認）")
    # AQR（Exhibit 3 の数字が在るか）
    t = _pdftext('aqr_2026.pdf')
    for k, e in next(h for h in HOUSES if h['id'] == 'AQR')['v'].items():
        ok('AQR', k, (f"{e['x']:.1f}%" in t) and (f"{e['real']:.1f}%" in t), f"Exhibit 3 に名目 {e['x']}%・実質 {e['real']}%（位置は bbox で確認）")
    # Schwab（ページの図の説明文）
    s = open(os.path.join(CACHE, 'schwab_2026_cme.html'), encoding='utf-8', errors='replace').read()
    good = ('2026 CMEs: U.S. Large Cap 5.9%, U.S. Small Cap 5.9%' in s) and ('Dev Large Cap 7.0%' in s) and ('EM 6.8%' in s)
    ok('SCHWAB', 'USL/USS/EAFE/EM', good, '図の説明 "2026 CMEs: U.S. Large Cap 5.9%, U.S. Small Cap 5.9%, Int\'l Dev Large Cap 7.0%, … EM 6.8%"')
    # BlackRock（Excel の Starting point・USD・10年）
    try:
        import openpyxl
        wb = openpyxl.load_workbook(os.path.join(CACHE, 'blackrock_cma.xlsx'), read_only=True, data_only=True)
        rows = list(wb.worksheets[0].iter_rows(values_only=True))
        usd = {r[2]: r[6] for r in rows[3:] if r[0] == 'USD' and r[1] == 'Equities'}
        names = {'USL': 'US large cap equities', 'USS': 'US small cap equities', 'EUR': 'Europe large cap equities',
                 'EAFE': 'Global ex-US large cap equities', 'EM': 'Emerging large cap equities', 'ACWI': 'All country large cap equities',
                 'CHN': 'China-Broad market'}
        bl = next(h for h in HOUSES if h['id'] == 'BLK')['v']
        for k, nm in names.items():
            ok('BLK', k, nm in usd and abs(100 * usd[nm] - bl[k]['x']) < 1e-6, f"Starting point シート USD '{nm}' 10 year = {100 * usd.get(nm, float('nan')):.4f}")
        wb2 = openpyxl.load_workbook(os.path.join(CACHE, 'bny_2026_usd.xlsx'), read_only=True, data_only=True)
        r2 = list(wb2.worksheets[0].iter_rows(values_only=True))
        geo = {}
        for r in r2:   # 列: (分類) 名前・指数・ティッカー・算術・幾何・ぶれ
            vals = [c for c in r if c is not None]
            if len(vals) >= 6 and all(isinstance(x, (int, float)) for x in vals[-3:]):
                geo[vals[-6]] = vals[-2]
        bmap = {'USL': 'US Large Cap', 'USS': 'US Small Cap', 'USV': 'US Value', 'USG': 'US Growth', 'EUR': 'EMU Equity',
                'JP': 'Japan Equity', 'EAFE': 'Developed ex US Equity', 'EM': 'Emerging Market Equity', 'ACWI': 'Global Equity'}
        bn = next(h for h in HOUSES if h['id'] == 'BNY')['v']
        for k, nm in bmap.items():
            ok('BNY', k, nm in geo and abs(100 * geo[nm] - bn[k]['x']) < 1e-6, f"Expected Risk and Return シート '{nm}' Geometric = {100 * geo.get(nm, float('nan')):.2f}")
    except Exception as ex:   # noqa
        ok('BLK/BNY', '-', False, f'Excel が読めない: {ex}')
    # State Street（行の3つ目の数字＝Long term 10+・5つ目＝Long-term risk）
    t = _pdftext('ssga_2026_q3.pdf')
    for k, e in next(h for h in HOUSES if h['id'] == 'SSGA')['v'].items():
        nm = e['label'].split('（')[0]
        good = False
        for line in t.splitlines():
            if line.strip().startswith(nm):
                nums = re.findall(r'-?\d+\.\d', line)
                if len(nums) >= 5 and float(nums[2]) == e['x'] and float(nums[4]) == e['sd']:
                    good = True
        ok('SSGA', k, good, f"表の行 '{nm}' の Long term 10+ = {e['x']}・Long-term risk = {e['sd']}")
    # T. Rowe（Annualized expected returns の表）
    t = _pdftext('trowe_2026_na.pdf')
    for k, e in next(h for h in HOUSES if h['id'] == 'TROWE')['v'].items():
        nm = e['label'].split('（')[0].replace('-', '[-‑]')
        ok('TROWE', k, _num_in_line(t, r'^\s*' + nm + r'\s', f"{e['x']:.1f}"), f"表の行 '{e['label']}' {e['x']}")
    # Northern Trust（Long-Term Return Forecasts の 2026 列）
    t = _pdftext('nt_2026_cma.pdf')
    ntl = {'USL': r'U\.S\.\s+MSCI USA\s', 'USS': r'U\.S\. Small Cap\s+Russell 2000', 'EUR': r'Europe\s+MSCI Europe ex U\.K\.\s',
           'JP': r'Japan\s+MSCI Japan\s', 'EM': r'Emerging Markets\s+MSCI Emerging Markets\s', 'ACWI': r'Global Equities\s+MSCI AC World\s'}
    for k, e in next(h for h in HOUSES if h['id'] == 'NT')['v'].items():
        good = False
        for line in t.splitlines():
            m = re.search(ntl[k] + r'\s*(\d+\.\d)', line)
            if m and float(m.group(1)) == e['x']:
                good = True
        ok('NT', k, good, f"Long-Term Return Forecasts の 2026 列 '{e['label']}' {e['x']}")
    # Invesco（Figure 6）
    t = _pdftext('invesco_cma_usd.pdf')
    for k, e in next(h for h in HOUSES if h['id'] == 'INVESCO')['v'].items():
        nm = e['label'].split('（')[0]
        ok('INVESCO', k, _num_in_line(t, r'^\s*' + re.escape(nm) + r'\d?\s', f"{e['x']:.1f}"), f"Figure 6 の行 '{nm}' {e['x']}")
    # Amundi（10年の幾何＝行の2つ目の % ）
    t = _pdftext('amundi_cma_h2_2026.pdf')
    for k, e in next(h for h in HOUSES if h['id'] == 'AMUNDI')['v'].items():
        nm = e['label'].split('（')[0]
        good = False
        for line in t.splitlines():
            if line.strip().startswith(nm):
                p = re.findall(r'-?\d+\.\d%', line)
                if len(p) >= 2 and p[1] == f"{e['x']:.1f}%":
                    good = True
        ok('AMUNDI', k, good, f"表の行 '{nm}' の 10年の幾何 = {e['x']}%")
    # Research Affiliates（JSON）
    try:
        N = {r['assetId']: r for r in json.load(open(os.path.join(CACHE, 'ra', 'usd_nominal_er_expected_return.json')))}
        Rr = {r['assetId']: r for r in json.load(open(os.path.join(CACHE, 'ra', 'usd_real_er_expected_return.json')))}
        for k, e in next(h for h in HOUSES if h['id'] == 'RA')['v'].items():
            n_, r_ = 100 * N[e['aid']]['return'], 100 * Rr[e['aid']]['return']
            ok('RA', k, abs(n_ - e['x']) < 0.006 and abs(r_ - e['real']) < 0.006, f"assetId {e['aid']} 名目 {n_:.3f}・実質 {r_:.3f}")
    except Exception as ex:   # noqa
        ok('RA', '-', False, f'JSON が読めない: {ex}')
    # Morningstar（記事の本文）
    s = open(os.path.join(CACHE, 'morningstar_experts_2026.html'), encoding='utf-8', errors='replace').read()
    ok('MSTAR', 'USL/EAFE/EM', ('5.3%' in s) and ('7.5% for non-US developed-market stocks' in s) and ('9.9% for emerging-market equities' in s),
       '記事 "the 10-year return expectation for US stocks is just 5.3%, it’s 7.5% for non-US developed-market stocks and 9.9% for emerging-market equities"')
    # Fidelity International（USD の表）
    t = _pdftext('fidelity_intl_h1_2026.pdf')
    seg = t[t.find('USD capital market assumptions'):][:3000]
    ok('FIDI', 'USL', _num_in_line(seg, r'US Equities', '6.4%'), "USD 表 'US Equities 6.4%'")
    ok('FIDI', 'EM', _num_in_line(seg, r'Emerging Markets Equities', '8.0%'), "USD 表 'Emerging Markets Equities 8.0%'")
    # Fidelity International の σ（p.11 の棒グラフ。数字の x 座標が軸の名前 DM / EM の x 座標に最も近いか）
    try:
        bb = subprocess.run(['pdftotext', '-f', '11', '-l', '11', '-bbox', os.path.join(CACHE, 'fidelity_intl_h1_2026.pdf'), '-'],
                            capture_output=True, text=True).stdout
        ws = [(float(a), float(b), w) for a, b, w in re.findall(r'xMin="([\d.]+)" yMin="([\d.]+)"[^>]*>([^<]+)</word>', bb)]
        good_hdr = 'Volatility assumptions' in subprocess.run(['pdftotext', '-f', '11', '-l', '11', os.path.join(CACHE, 'fidelity_intl_h1_2026.pdf'), '-'],
                                                              capture_output=True, text=True).stdout
        axis = {w: x for x, y, w in ws if x > 700 and 360 < y < 380 and w in ('DM', 'EM', 'Global')}
        bars = [(x, w) for x, y, w in ws if x > 700 and y < 300 and w.endswith('%')]
        near = {lab: min(bars, key=lambda b: abs(b[0] - axis[lab]))[1] for lab in ('DM', 'EM') if lab in axis and bars}
        fv = next(h for h in HOUSES if h['id'] == 'FIDI')['v']
        ok('FIDI', 'σ(USL←DM)', good_hdr and near.get('DM') == f"{fv['USL']['sd']:.1f}%", f"p.11 Volatility assumptions の DM equities の棒 = {near.get('DM')}")
        ok('FIDI', 'σ(EM)', good_hdr and near.get('EM') == f"{fv['EM']['sd']:.1f}%", f"p.11 Volatility assumptions の EM equities の棒 = {near.get('EM')}")
    except Exception as ex:   # noqa
        ok('FIDI', 'σ', False, f'p.11 が読めない: {ex}')
    # Robeco
    t = _pdftext('robeco_er_2027_2031_summary.pdf')
    ok('ROBECO', 'EM', _num_in_line(t, r'Emerging market equities', '8.75%'), "表 'Emerging market equities … 8.75%（USD 列）'")
    # Goldman
    t = _pdftext('gs_10y_2025-11-12.pdf')
    ok('GS', 'USL/EUR/JP/EM/ACWI', all(x in t for x in ['+6.5%', '+7.1%', '+8.2%', '+10.9%', '7.7% in USD']), '本文 United States +6.5% / Europe +7.1% / Japan +8.2% / EM +10.9% / 7.7% in USD')
    # ── 当たり外れ・今の値段に使う数字 ──
    t = _pdftext('nt_2026_cma.pdf')
    ok('NT点検', '2020→2025', ('returned 15.9%' in t) and ('4.7% forecast' in t) and ('9.8% versus our 5.4% forecast' in t) and ('13.4%' in t) and ('5.1%' in t),
       '"U.S. equities returned 15.9% versus a 4.7% forecast, while emerging markets returned 9.8% versus our 5.4% forecast"')
    t = _pdftext('bny_2026_full.pdf')
    ok('BNY点検', '2016→2025', all(x in t for x in ['13.4', '9.9', '8.9', '5.2', 'valuations expanded from 18.8 to 26.5']),
       '図 "2016 Capital Market Assumptions vs. Actual 10-Year Returns" の数字（列は pdftotext -bbox で割り当て: 左が実際・右が2016年の予想）')
    t = _pdftext('duke_gmo_predictions.pdf')
    ok('Tower2008', 'GMO', all(x in t for x in ['0.939', '0.781', '5.51', '5.99', '-1.29', '-4.92']), 'Exhibit 1 "Correlation for equities 0.939"')
    t = _pdftext('gmo_2021_03.pdf')
    ok('GMO2021', 'USL/USS/EFA/EM', all(x in t for x in ['-7.3%', '-8.1%', '-2.3%', '-1.5%', 'As of March 31, 2021']), 'GMO 2021-03-31 の図（位置は bbox で確認: U.S. Large −7.3・U.S. Small −8.1・Intl Large −2.3・Emerging −1.5）')
    t = _pdftext('factset_ei_100926.pdf')
    ok('FactSet', '2026-10-09', all(x in t for x in ['forward 12-month P/E ratio for the S&P 500 is 19.1', 'For CY 2026, analysts are projecting earnings growth of 32.7%',
                                                       'For CY 2027, analysts are projecting earnings growth of 15.8%', 'The trailing 12-month P/E ratio is 26.0', '7,765.36']),
       'Earnings Insight 2026-10-09 の本文')
    return res


# ════════════════════════════ 当たり外れ ════════════════════════════
def _cpi():
    p = os.path.join(CACHE, 'data', 'fred_CPIAUCSL.csv')
    if not os.path.exists(p) or time.time() - os.path.getmtime(p) > 20 * 86400:
        b = urllib.request.urlopen(urllib.request.Request('https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL',
                                                          headers={'User-Agent': 'curl/8.5.0'}), timeout=120).read()   # gaps_common と同じ名乗り
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'wb').write(b)
    out = {}
    for row in list(csv.reader(io.StringIO(open(p).read())))[1:]:
        if len(row) >= 2 and row[1] not in ('.', ''):
            out[int(row[0][:4]) * 100 + int(row[0][5:7])] = float(row[1])
    return out


def _yahoo(t):
    import mw_common as M
    M.CACHE = os.path.join(CACHE, 'mw')     # キャッシュはこの担当の場所へ
    return M.yahoo(t)


def _add(ym, k):
    y, m = divmod(ym // 100 * 12 + ym % 100 - 1 + k, 12)
    return y * 100 + m + 1


def realized(ticker, start, months, cpi):
    """start＝予想の時点の月（その月末から）。months か月の名目・実質の年率。足りない月は欠測（0 と読まない）"""
    r = _yahoo(ticker)
    ks = [_add(start, i) for i in range(1, months + 1)]
    miss = [k for k in ks if k not in r]
    if miss:
        return dict(ticker=ticker, months=months, missing=miss[:5], n_missing=len(miss))
    g = 1.0
    for k in ks:
        g *= 1 + r[k]
    yrs = months / 12
    nom = g ** (1 / yrs) - 1
    end = ks[-1]
    cpi_end = cpi.get(end)
    cpi_note = None
    if cpi_end is None:   # CPI は 2026-08 まで → 最後の月が無ければ直前の月で代える（書く）
        e2 = max(k for k in cpi if k <= end)
        cpi_end, cpi_note = cpi[e2], f'CPI は {e2} までしか無い → {e2} の値で代用'
    infl = (cpi_end / cpi[start]) ** (1 / yrs) - 1
    real = (1 + nom) / (1 + infl) - 1
    return dict(ticker=ticker, window=f'{_add(start, 1)}〜{end}', months=months, nominal=round(100 * nom, 2), inflation=round(100 * infl, 2),
                real=round(100 * real, 2), cpi_note=cpi_note)


def cape_accuracy():
    """Shiller のデータで CAPE の10年予想を測る（先読みなし: その時点までに終わった10年窓だけで当てはめる）"""
    import xlrd
    p = os.path.join(CACHE, 'data', 'shiller_ie_data.xls')
    if not os.path.exists(p):
        b = urllib.request.urlopen('http://www.econ.yale.edu/~shiller/data/ie_data.xls', timeout=120).read()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'wb').write(b)
    sh = xlrd.open_workbook(p).sheet_by_name('Data')
    ym, tr, cape = [], [], []
    for i in range(8, sh.nrows):
        r = sh.row_values(i)
        if not isinstance(r[0], float) or not isinstance(r[9], float):
            continue
        y = int(r[0]); m = int(round((r[0] - y) * 100))
        ym.append(y * 100 + m); tr.append(r[9]); cape.append(r[12] if isinstance(r[12], float) else None)
    n = len(ym)
    fwd = [((tr[i + 120] / tr[i]) ** 0.1 - 1) if i + 120 < n else None for i in range(n)]
    idx = {v: i for i, v in enumerate(ym)}
    rows = []
    for i in range(n):
        if ym[i] < 195001 or fwd[i] is None or cape[i] is None:
            continue
        done = [j for j in range(0, i - 120 + 1) if fwd[j] is not None and cape[j] is not None]   # その時点で終わっている窓
        if len(done) < 360:
            continue
        xs = [math.log(cape[j]) for j in done]; ys = [fwd[j] for j in done]
        mx, my = S.mean(xs), S.mean(ys)
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
        a = my - b * mx
        rows.append(dict(ym=ym[i], cape=cape[i], real=fwd[i], f_yield=1 / cape[i], f_reg=a + b * math.log(cape[i]), f_hist=my))

    def stat(key):
        e = [r[key] - r['real'] for r in rows]
        f = [r[key] for r in rows]; y = [r['real'] for r in rows]
        mf, my = S.mean(f), S.mean(y)
        c = sum((a - mf) * (b - my) for a, b in zip(f, y)) / math.sqrt(sum((a - mf) ** 2 for a in f) * sum((b - my) ** 2 for b in y))
        return dict(mean_error_pt=round(100 * S.mean(e), 2), rmse_pt=round(100 * math.sqrt(S.mean(x * x for x in e)), 2), corr=round(c, 2))
    pick = {}
    for want in (196512, 197406, 198207, 199912, 200003, 200303, 200709, 200903, 201309):
        r = next((x for x in rows if x['ym'] == want), None)
        if r:
            pick[str(want)] = dict(CAPE=round(r['cape'], 1), 予想_1割CAPE=round(100 * r['f_yield'], 2), 予想_回帰=round(100 * r['f_reg'], 2),
                                   予想_過去平均=round(100 * r['f_hist'], 2), 実際の10年実質=round(100 * r['real'], 2))
    # 今の CAPE（RA の 2026-09-30）で、全期間の当てはめから
    allx = [(math.log(cape[j]), fwd[j]) for j in range(n) if fwd[j] is not None and cape[j] is not None]
    mx, my = S.mean(x for x, _ in allx), S.mean(y for _, y in allx)
    b = sum((x - mx) * (y - my) for x, y in allx) / sum((x - mx) ** 2 for x, _ in allx)
    a = my - b * mx
    resid = [y - (a + b * x) for x, y in allx]
    se = math.sqrt(S.mean(e * e for e in resid))
    now = 40.513731477556
    return dict(
        data='Robert Shiller ie_data.xls（S&P 総合・配当再投資の実質トータルリターン・CAPE）。最後の月 ' + str(ym[-1]),
        url='http://www.econ.yale.edu/~shiller/data/ie_data.xls',
        method='1950-01〜' + str(rows[-1]['ym']) + ' の各月に、その月までに終わった10年窓（30年分以上）だけで「次の10年の実質年率 ~ log(CAPE)」を当てはめて予想（先読みなし）。'
               '比べる予想: 1÷CAPE（益回り）・回帰・過去の平均',
        n_months=len(rows),
        stats={'1割CAPE（益回り）': stat('f_yield'), '回帰（その時点まで）': stat('f_reg'), '過去の平均': stat('f_hist')},
        picks=pick,
        now=dict(CAPE=round(now, 1), CAPE_src='Research Affiliates AAI の US Large（2026-09-30）', 益回り=round(100 / now, 2),
                 回帰の予想_実質=round(100 * (a + b * math.log(now)), 2), 回帰の残差の標準偏差=round(100 * se, 2),
                 注意='CAPE 40 超は1999-2000年の数か月しか過去に無い（外挿）。Shiller の CAPE と RA の CAPE は作り方が少し違う'))


def accuracy(cpi):
    acc = dict(published=[], hand=[], cape=None)
    acc['published'] = [
        dict(who='BNY Investments（自社の点検）', what='2016年の10年予想 vs 実際の10年（2025-06-30まで）',
             src='https://www.bny.com/content/dam/imemea/pdfs/endurance-under-pressure-capital-market-assumptions-2026-full.pdf（p.3 の図・数字は pdftotext -bbox で列に割り当て）',
             rows={'米国大型': dict(予想=7.1, 実際=13.4), '米国中型': dict(予想=7.7, 実際=9.9), '米国小型': dict(予想=8.2, 実際=7.1),
                   '先進国（米国除く）': dict(予想=6.9, 実際=6.6), '新興国': dict(予想=8.9, 実際=5.2)},
             note='原本: 米国大型だけが範囲の外（PER が18.8→26.5に上がった）。新興国は株数の増加で下に外れた'),
        dict(who='Northern Trust（自社の点検 "How Have We Done?"）', what='2020年の5年予想 vs 実際（2020→2025）',
             src='https://ntam.northerntrust.com/content/dam/northerntrust/investment-management/global/en/documents/thought-leadership/2026/cma/2026-capital-market-assumptions-report.pdf（Exhibit 15）',
             rows={'米国株': dict(予想=4.7, 実際=15.9), '新興国株': dict(予想=5.4, 実際=9.8), 'リスク資産の組み合わせ': dict(予想=5.1, 実際=13.4),
                   '全体の組み合わせ': dict(予想=4.1, 実際=7.9)},
             note='原本 "our 2020 five-year forecast was too pessimistic … Little did we suspect the huge optimism fueling the AI boom"'),
        dict(who='Edward Tower（Duke 大学・2008-11）', what='GMO の予想（2000-07〜）と Vanguard の投信の実績（〜2008-10）',
             src='https://public.econ.duke.edu/Papers/PDF/GMO_Predictions1.pdf（Exhibit 1）',
             rows={'株の5種類の順位の相関': 0.939, '全資産の相関': 0.781, '1位の組 予想/実際': '5.51 / 5.99', '5位の組 予想/実際': '-1.29 / -4.92'},
             note='順位はよく当たった（5種類のうち4つの順位が一致）。水準は5つ中4つで予想が高すぎた（2000〜2008は下落相場）。'
                  'ただし 2000〜2008年の1回の窓・株5種類（n=5）だけの例で、順位が当たりやすいことの一般の証拠にはならない'),
        dict(who='Research Affiliates（自社の点検 "Asset Allocation Interactive at 10 Years: The Good, the Not Too Bad, and the Ugly"・2025-01）',
             what='AAI の10年予想（2014年〜）と実績', src='https://www.researchaffiliates.com/publications/articles/1069-asset-allocation-interactive-good-bad-ugly',
             rows={}, note='数字は取れなかった（ページが JavaScript で描かれる）。要旨（検索の要約・二次）: 平均の水準はおおむね実績の分布の中ほど・資産の並び順はおおむね当たった・為替とインフレの予想が弱い。確かめられない'),
        dict(who='Vanguard（自社の振り返り・二次資料経由）', what='VCMM の10年予想（2010年ごろ）vs 2010年代',
             src='https://mymoneyblog.com/vanguards-10-year-stock-market-return-forecasts-accurate-wrong.html',
             rows={}, note='Vanguard の記述（二次資料の引用）: 60/40 の10年はおおむね予想の範囲内・米国株は予想を上回り・米国外は下回った。数字は確かめられない'),
    ]
    # ── 手で突き合わせ ──
    def hand(who, fdate, src, items, H, note=None, partial=False):
        out = []
        for lab, f, tic in items:
            months = int(round(H * 12))
            last_full = 202609
            have = (last_full // 100 * 12 + last_full % 100) - (fdate // 100 * 12 + fdate % 100)
            mm = min(months, have)
            rz = realized(tic, fdate, mm, cpi)
            out.append(dict(asset=lab, forecast=f, proxy=tic, realized=rz, full_window=mm == months))
        acc['hand'].append(dict(who=who, forecast_asof=fdate, horizon_years=H, source=src, items=out, partial=partial, note=note))
    hand('GMO 7年予想（実質）', 201405, 'Motley Fool 2014-06-12 "This Is Another Sign Twitter Went Public Too Early"（GMO の5月末の予想を引用・二次）: https://www.fool.com/investing/general/2014/06/12/this-is-another-sign-twitter-went-public-too-early.aspx',
         [('米国大型（実質）', -1.5, 'SPY'), ('米国小型（実質）', -4.5, 'IWM')], 7, note='実際は配当込み（Yahoo の調整後終値）・CPIAUCSL で実質に')
    hand('GMO 7年予想（実質）', 201307, 'My Money Blog 2020-12-22（GMO 2013年7月の予想を引用・二次）: https://www.mymoneyblog.com/gmo-asset-class-return-forecasts-2020-vs-2013.html',
         [('米国大型（実質）', -2.1, 'SPY')], 7, note='予想の時点は2013年7月末と置いた')
    hand('GMO 7年予想（実質・2021-03-31）', 202103, 'GMO の原本 https://www.gmo.com/globalassets/articles/gmo-7-year-asset-class-forecast/2021/gmo_7yrforecasts_3-21.pdf',
         [('米国大型（実質）', -7.3, 'SPY'), ('米国小型（実質）', -8.1, 'IWM'), ('先進国大型（実質・現地）', -2.3, 'EFA'), ('新興国（実質・現地）', -1.5, 'EEM')],
         7, partial=True, note='途中経過（2026-09 までの5.5年）。先進国・新興国の実際はドル建て（EFA・EEM）で予想は現地通貨＝基準が少し違う')
    hand('Vanguard 2018年の見通し（名目・10年・2017-12公表）', 201712, 'ThinkAdvisor 2017-12-04 "Vanguard Issues Its Most Subdued Outlook in a Decade"（二次）: https://thinkadvisor.com/2017/12/04/vanguard-issues-its-most-subdued-outlook-in-a-decade',
         [('米国株（名目 3〜5% の中点）', 4.0, 'VTI'), ('米国外株（名目 5.5〜7.5% の中点）', 6.5, 'VXUS')], 10, partial=True,
         note='途中経過（2026-09 までの8.75年）。予想は名目なので実際も名目で比べる')
    hand('J.P. Morgan 2021 LTCMA（名目・10〜15年・2020-09-30時点）', 202009, 'CFA Institute Enterprising Investor 2021-04-12（Anson J. Glacy Jr.・JPM の "fall from 5.6% last year to 4.1%" を引用・二次）: https://rpc.cfainstitute.org/blogs/enterprising-investor/2021/building-optimized-portfolios-with-jpmorgans-2021-forecasts',
         [('米国株（記事の表現 "equity market returns"・名目。大型か・幾何か算術かは記事に書かれていない）', 4.1, 'SPY')], 12.5, partial=True,
         note='途中経過（2026-09 までの6年）。名目で比べる。比べる相手を SPY（米国大型）に置いたのはこちらの読み替え')
    acc['cape'] = cape_accuracy()
    # 要点
    acc['summary'] = ('どの会社も2010年代〜2020年代前半の米国大型株を大きく低く見積もった（BNY 2016: 7.1→実際13.4・NT 2020: 4.7→15.9・GMO 2014: 実質−1.5→実際+11.9%〔2014-06〜2021-05・SPY・CPI で実質〕）。'
                      '理由は PER の上昇（BNY: 18.8→26.5）と AI の熱狂（NT）。逆に新興国は高く見積もりがち（BNY 2016: 8.9→5.2）。'
                      '順位（どれが相対的に良いか）は水準より当たったという例がある（Tower 2008 の GMO: 相関0.94・ただし 2000〜2008年の1回の窓・株5種類だけ）が、2010年代の米国 vs 米国外は外れた。'
                      'CAPE の10年予想は長い目では負の関係が効くが誤差が大きい（下の cape.stats）')
    return acc


# ════════════════════════════ 今の値段 ════════════════════════════
def sec_capex():
    """大手4社の設備投資（現金の有形固定資産の購入・XBRL）。直近12か月（2026-06-30まで）と2025暦年"""
    tags = ['PaymentsToAcquirePropertyPlantAndEquipment', 'PaymentsToAcquireProductiveAssets']
    cos = {'MSFT': '0000789019', 'GOOGL': '0001652044', 'AMZN': '0001018724', 'META': '0001326801'}
    out = {}
    for t, cik in cos.items():
        rec = None
        for tag in tags:
            p = os.path.join(CACHE, 'sec', f'{t}_{tag}.json')
            if not os.path.exists(p) or time.time() - os.path.getmtime(p) > 30 * 86400:
                u = f'https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json'
                try:
                    b = urllib.request.urlopen(urllib.request.Request(u, headers=SEC_UA), timeout=60).read()
                    try:
                        b = gzip.decompress(b)
                    except OSError:
                        pass
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    open(p, 'wb').write(b)
                except Exception:   # noqa
                    time.sleep(0.15)
                    continue
                time.sleep(0.15)      # 毎秒10件以下
            j = json.load(open(p))
            facts = j.get('units', {}).get('USD', [])
            if not facts:
                continue

            def dur(f):
                a = datetime.date.fromisoformat(f['start']); b = datetime.date.fromisoformat(f['end'])
                return (b - a).days

            def pick(end, lo, hi):
                c = [f for f in facts if f.get('end') == end and 'start' in f and lo <= dur(f) <= hi]
                c.sort(key=lambda f: f.get('filed', ''))
                return c[-1] if c else None
            if t == 'MSFT':     # 会計年度は6月末＝会計年度そのものが「6月末までの12か月」
                fy = pick('2026-06-30', 350, 380); prev = pick('2025-06-30', 350, 380)
                if fy:
                    rec = dict(tag=tag, ttm_to_2026_06=fy['val'] / 1e9, ttm_src=f"FY2026（{fy['start']}〜{fy['end']}・{fy.get('form')} {fy.get('filed')}）",
                               ttm_to_2025_06=prev['val'] / 1e9 if prev else None,
                               ttm_prev_src=f"FY2025（{prev['start']}〜{prev['end']}・{prev.get('form')} {prev.get('filed')}）" if prev else None,
                               ref_fy_or_cal2025=prev['val'] / 1e9 if prev else None, ref_src='FY2025（2024-07〜2025-06）' if prev else None)
            else:
                fy25 = pick('2025-12-31', 350, 380); h125 = pick('2025-06-30', 170, 190); h126 = pick('2026-06-30', 170, 190)
                fy24 = pick('2024-12-31', 350, 380); h124 = pick('2024-06-30', 170, 190)
                if fy25 and h125 and h126:
                    ttm = (fy25['val'] - h125['val'] + h126['val']) / 1e9
                    rec = dict(tag=tag, ttm_to_2026_06=ttm, ttm_src=f"2025暦年 {fy25['val'] / 1e9:.1f} − 2025年上期 {h125['val'] / 1e9:.1f} + 2026年上期 {h126['val'] / 1e9:.1f}（{h126.get('form')} {h126.get('filed')}）",
                               ttm_to_2025_06=((fy24['val'] - h124['val'] + h125['val']) / 1e9) if (fy24 and h124) else None,
                               ttm_prev_src=(f"2024暦年 {fy24['val'] / 1e9:.1f} − 2024年上期 {h124['val'] / 1e9:.1f} + 2025年上期 {h125['val'] / 1e9:.1f}（{h125.get('form')} {h125.get('filed')}）"
                                             if (fy24 and h124) else '2024暦年か2024年上期が XBRL に無い（欠測＝0 と読まない）'),
                               ref_fy_or_cal2025=fy25['val'] / 1e9, ref_src='2025暦年')
            if rec:
                break
        out[t] = rec or dict(note='XBRL のタグが見つからない（欠測＝0 と読まない）')
    got = [v['ttm_to_2026_06'] for v in out.values() if isinstance(v, dict) and v.get('ttm_to_2026_06')]
    prev = [v['ttm_to_2025_06'] for v in out.values() if isinstance(v, dict) and v.get('ttm_to_2025_06')]
    ref = [v['ref_fy_or_cal2025'] for v in out.values() if isinstance(v, dict) and v.get('ref_fy_or_cal2025')]
    tot, totp = (sum(got) if len(got) == 4 else None), (sum(prev) if len(prev) == 4 else None)
    return dict(companies={k: ({kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items()}) for k, v in out.items()},
                total_ttm_bn=round(tot, 1) if tot is not None else None,
                total_prev_bn=round(totp, 1) if totp is not None else None,
                prev_def='前年＝1年前の同じ12か月（2024-07〜2025-06。MSFT は FY2025・他3社は 2024暦年−2024年上期＋2025年上期）',
                growth_pct=round(100 * (tot / totp - 1), 1) if (tot and totp) else None,
                ref_msft_fy25_plus_cal2025_bn=round(sum(ref), 1) if len(ref) == 4 else None,
                ref_note='参考: MSFT FY2025＋他3社の2025暦年。直近12か月（2025-07〜2026-06）と他3社の分が6か月重なるので、「前年」として伸びの計算には使わない'
                         '（2026-10-12 の直し: 以前はこの値を「前年」と書いていた）',
                src='SEC data.sec.gov companyconcept（us-gaap PaymentsToAcquirePropertyPlantAndEquipment／PaymentsToAcquireProductiveAssets）・単位 十億ドル・現金の購入（ファイナンスリースは含まない）')


def _ensure(name, url, ua=None):
    """キャッシュに無ければ取りに行く（取れなければ例外＝黙って空にしない）"""
    p = os.path.join(CACHE, name)
    if not os.path.exists(p) or os.path.getsize(p) == 0:
        b = urllib.request.urlopen(urllib.request.Request(url, headers=ua or {'User-Agent': 'Mozilla/5.0'}), timeout=120).read()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'wb').write(b)
    return p


def spy_top10():
    import openpyxl
    p = _ensure('spy_holdings.xlsx', 'https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx')
    wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    asof = rows[2][1]
    hdr = next(i for i, r in enumerate(rows) if r and 'Weight' in [str(c) for c in r])
    h = [str(c) for c in rows[hdr]]
    wi, ni, ti = h.index('Weight'), h.index('Name'), h.index('Ticker')
    data = [(r[ni], r[ti], float(r[wi])) for r in rows[hdr + 1:] if r and isinstance(r[wi], (int, float))]
    data.sort(key=lambda x: -x[2])
    lines10 = round(sum(x[2] for x in data[:10]), 2)
    co = {}
    for nm, t, w in data:
        k = 'Alphabet' if t in ('GOOGL', 'GOOG') else t
        co[k] = co.get(k, 0) + w
    top = sorted(co.items(), key=lambda kv: -kv[1])[:10]
    return dict(asof=asof, top10_lines_pct=lines10, top10_companies_pct=round(sum(w for _, w in top), 2),
                top10_companies=[(k, round(w, 2)) for k, w in top], total_weight_pct=round(sum(x[2] for x in data), 2),
                src='https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx（SPY の毎日の保有）',
                history='1880〜2010 の平均は約24%・ITバブルの天井で約26〜27%（RBC Wealth Management・Visual Capitalist の集計・二次）')


def present():
    ra_attr = {r['assetId']: r for r in json.load(open(_ensure(os.path.join('ra', 'usd_asset_attribute.json'),
                                                                'https://interactive.researchaffiliates.com/asset-allocation-data/202610/02/usd/asset_attribute.json')))}
    capes = {nm: round(ra_attr[i]['shillerPE'], 1) for nm, i in [('米国大型', 1), ('米国小型', 4), ('先進国（米国除く）', 32), ('欧州', 31),
                                                                    ('日本', 11), ('新興国', 33), ('中国', 17), ('インド', 18), ('台湾', 26), ('全世界', 29)]}
    p = dict(
        cape=dict(us_large=round(ra_attr[1]['shillerPE'], 2), percentile_since_1880=round(ra_attr[1]['shillerPEPercentile'], 4),
                  median_since_1880=round(ra_attr[1]['shillerMedian'], 1), max=round(ra_attr[1]['shillerMax'], 1), asof='2026-09-30',
                  by_market=capes, src='Research Affiliates AAI の asset_attribute.json（https://interactive.researchaffiliates.com/asset-allocation-data/202610/02/usd/asset_attribute.json）',
                  shiller_last=dict(month='2023-09', cape=30.8, note='Shiller の公開データは2023年9月で止まっている（ie_data.xls）')),
        factset=dict(asof='2026-10-09', forward_pe=19.1, forward_pe_5y_avg=19.8, forward_pe_10y_avg=19.1, forward_pe_2026_06_30=20.4,
                     trailing_pe=26.0, eps_growth_cy2026=32.7, revenue_growth_cy2026=12.5, eps_growth_cy2027=15.8, revenue_growth_cy2027=9.4,
                     sp500_close=7765.36, bottom_up_target=9290.58,
                     note='6月末から株価+3.5%・12か月先の利益の予想+10.4% → 予想PER は下がった（20.4→19.1）。利益が速く伸びている分、CAPE（過去10年の平均利益）と予想PER の見え方が大きく違う',
                     src='FactSet Earnings Insight 2026-10-09: https://advantage.factset.com/hubfs/Website/Resources%20Section/Research%20Desk/Earnings%20Insight/EarningsInsight_100926.pdf（p.1・p.17）'),
        spy_top10=spy_top10(),
        ai_capex=sec_capex(),
        ai_capex_guidance=dict(range_bn='約720〜745（4社合計・2026暦年の会社の見通し）', status='二次資料のみ＝確かめられない。原本の数字は上の ai_capex（XBRL の実績・直近12か月）',
                               secondary_urls=['https://mlq.ai/news/big-techs-2026-capex-range-reaches-720-billion-to-745-billion/',
                                               'https://tech-insider.org/microsoft-meta-google-ai-capex-725-billion-2026/',
                                               'https://valueaddvc.com/ai-spending'],
                               grid_note='FactSet 2026-10-09（p.16）: 2026年9月の米国本土48州の平均の電力需要は541GW（前年の最高から+8.7%）・データセンターの建設が新しい需要を足している。テキサス州は新しいデータセンターの承認を一時止めた'),
    )
    return p


# ════════════════════════════ 本体 ════════════════════════════
def main():
    if '--verify' in sys.argv:
        v = verify()
        bad = [x for x in v if not x['ok']]
        for x in v:
            print(('OK ' if x['ok'] else 'NG ') + f"{x['house']:9s} {x['key']:14s} {x['how']}")
        print(f'{len(v) - len(bad)}/{len(v)} が原本と一致')
        return
    main_h = [h for h in HOUSES if h['main']]
    coll = collect(main_h)
    table = d_table(coll)
    # 感度
    # cls: 'reading'＝事前登録の中で読み方が分かれる所を振る ／ 'reference'＝事前登録の外の値を混ぜる参考（幅の主な数字には入れない）
    sens_defs = {
        'S_all_currency': dict(houses=main_h, kw={}, prio=False, cls='reference',
                               why='参考（事前登録の外）: ドル建てに限らず、現地通貨の値（米国外を現地通貨で出す NT・Amundi・AQR・SSGA・GMO）も混ぜる'),
        'S_ssga_arith_raw': dict(houses=main_h, kw=dict(ssga_arith_raw=True), cls='reference',
                                 why='参考（事前登録の外＝複利でない）: State Street の算術平均を複利へ直さずそのまま'),
        'S_with_GS': dict(houses=HOUSES, kw={}, cls='reading', why='Goldman Sachs（2025-11-12）を足す'),
        'S_no_GMO': dict(houses=main_h, kw=dict(drop=('GMO',)), cls='reading', why='いちばん低い GMO を外す'),
        'S_strict_2026_pub': dict(houses=main_h, kw=dict(drop=('JPM', 'NT')), cls='reading',
                                  why='2026年に公表された版だけ（JPM 2026 LTCMA は2025-10-20 公表・Northern Trust 2026 Edition は表紙に "RELEASED DECEMBER 2025" → 2社とも外す）'),
        'S_no_JPM': dict(houses=main_h, kw=dict(drop=('JPM',)), cls='reading', why='JPM だけ外す（2026-10-12 より前の S_strict_2026_pub と同じ）'),
        'S_no_approx': dict(houses=main_h, kw=dict(approx_ok=False), cls='reading', why='近い読み替え（GMO の Deep Value＝バリュー・SSGA の世界の質/勢い）を外す'),
        'S_aqr_real_plus25': dict(houses=main_h, kw=dict(aqr_real25=True), cls='reading', why='AQR を実質＋2.5%（事前登録の換算）で'),
        'S_no_5y': dict(houses=main_h, kw=dict(drop=('TROWE', 'ROBECO')), cls='reading',
                        why='5年の予想（T. Rowe Price "Five-Year Geometric Average"・Robeco "5-year annualized"）を外す（事前登録は「10年前後」）'),
        'S_fidi_arith': dict(houses=main_h, kw=dict(fidi_arith=True), cls='reading',
                             why='Fidelity International の "Average expected returns"（幾何か算術か明記なし）を算術と見て 算術−σ²/2（σ は同じ報告 p.11: DM 15.3%〔米国株の代用〕・EM 20.2%）'),
        'S_no5y_fidi_arith': dict(houses=main_h, kw=dict(drop=('TROWE', 'ROBECO'), fidi_arith=True), cls='reading',
                                  why='S_no_5y と S_fidi_arith を両方'),
    }
    sens = {}
    for nm, d in sens_defs.items():
        t = d_table(collect(d['houses'], **d['kw']), usd_priority=d.get('prio', True))
        sens[nm] = dict(why=d['why'], cls=d['cls'],
                        by_key={k: dict(n=t[k]['n'], made=t[k]['made'],
                                        median=round(100 * t[k]['median'], 3) if t[k]['n'] else None,
                                        H=t[k].get('H_median'),
                                        ref_with_local=(dict(n=t[k]['ref_with_local']['n'], median=round(100 * t[k]['ref_with_local']['median'], 3))
                                                        if t[k].get('ref_with_local') else None)) for k in KEYS if t[k]['n']})
        sens[nm]['_table'] = t
    # 行（B・経費率・外国税）
    rows, rows_src, r7_problem = {}, None, None
    try:
        import etf_forward_rank as R
        rows = R.main(write=False)['rows']
        rows_src = 'night/etf_forward_rank.py の main(write=False)["rows"]'
    except Exception as ex:   # noqa
        rows_src = f'etf_forward_rank が読めない: {ex}'
    r7_added = []
    try:
        import bestpf_ext as X   # R7（あれば）
        if not hasattr(X, 'rank_result'):
            r7_problem = 'night/bestpf_ext.py に rank_result() が無い'
        else:
            rx = X.rank_result()
            rx = rx.get('rows', rx) if isinstance(rx, dict) else rx
            if not isinstance(rx, dict):
                r7_problem = f'bestpf_ext.rank_result() の形が想定と違う（{type(rx).__name__}）'
            else:
                for k, v in rx.items():
                    if k not in rows and isinstance(v, dict) and 'B_gross' in v:
                        rows[k] = v; r7_added.append(k)
                rows_src += f" ＋ night/bestpf_ext.py の rank_result()（足した本: {'・'.join(r7_added) or 'なし'}）"
    except Exception as ex:   # noqa  黙って抜けない（2026-10-12 の直し）
        r7_problem = f'night/bestpf_ext.py が読めない: {type(ex).__name__}: {ex}'
    if r7_problem:
        rows_src += f'（R7 の行は読めなかった: {r7_problem}）'
    dnet, detail = d_net_rows(table, rows)
    unmapped_rows = sorted(c for c in rows if c not in D_MAP)
    sens_dnet = {nm: {c: round(v, 5) for c, v in d_net_rows(s['_table'], rows)[0].items()} for nm, s in sens.items()}
    for s in sens.values():
        s.pop('_table')
    # 出典の表（換算の説明つき）
    houses_out = []
    for h in HOUSES:
        hv = {}
        for k, e in h['v'].items():
            g, how = to_nominal_geo(e) if not (h['id'] == 'AQR') else (e['x'] / 100, f"Exhibit 3C の名目 {e['x']}（実質 {e['real']}）")
            hv[k] = dict(label=e['label'], raw={kk: vv for kk, vv in e.items() if kk not in ('label', 'cur', 'approx', 'aid')},
                         currency=e.get('cur'), nominal_geo_pct=round(100 * g, 3), how=how, approx=bool(e.get('approx')))
        houses_out.append(dict(id=h['id'], name=h['name'], edition=h['edition'], urls=h['urls'], published=h['published'],
                               published_src=h['published_src'], data_asof=h['asof'], horizon=h['horizon'], H_years=h['H'],
                               basis=h['basis'], currency=h['currency'], in_main=h['main'], main_why=h['main_why'],
                               cache_file='out/_bestpf_cache/cma/' + h['file'], values=hv,
                               extra={k: v for k, v in h['extra'].items() if v is not None} if h.get('extra') else {}))
    # 種類ごとの D
    d_by_key = {}
    for k in KEYS:
        e = table[k]
        d_by_key[k] = dict(ja=KEY_JA[k], n=e['n'], made=e['made'], basis=e['basis'], n_all_currencies=e['n_all'], n_usd=e['n_usd'],
                           local_currency_values_not_used=e['dropped_local'], houses=e['houses'], values_pct=e['values'],
                           median_pct=round(100 * e['median'], 3) if e['n'] else None,
                           H_median=e.get('H_median'), min_pct=round(100 * e['min'], 2) if e['n'] else None,
                           max_pct=round(100 * e['max'], 2) if e['n'] else None, n_local_currency=e.get('n_local_currency', 0),
                           ref_with_local_pct=(dict(n=e['ref_with_local']['n'], median=round(100 * e['ref_with_local']['median'], 3), note=e['ref_with_local']['note'])
                                               if e.get('ref_with_local') else None),
                           note=None if e['made'] else ('ドル建ての値が5社に届かない → この種類に割り当てた本は D＝C（事前登録）' if e['n'] or e['n_all']
                                                        else '数字を出す会社が見つからない'))
    # JPM との照合（C の世界）
    jpm_check = []
    try:
        import etf_forward_rank as R
        for k, rk in {'ACWI': 'ACWI', 'USL': 'USL', 'USS': 'USS', 'EAFE': 'EAFE', 'JP': 'JP', 'EM': 'EM', 'USV': 'VALUE',
                      'QUALITY': 'QUALITY', 'DIV': 'DIV'}.items():
            jv = next(h for h in HOUSES if h['id'] == 'JPM')['v'][k]['x']
            jpm_check.append(dict(key=k, repo_JPM=R.JPM[rk], matrix_pdf=jv, same=abs(R.JPM[rk] - jv) < 1e-9))
    except Exception as ex:   # noqa
        jpm_check.append(dict(error=str(ex)))
    cpi = _cpi()
    acc = accuracy(cpi)
    pres = present()
    # 候補ごとの表（D と C）
    asset_table = {c: dict(ticker=c, **detail.get(c, {})) for c in D_MAP}
    # 要約の数字
    usl = d_by_key['USL']; eafe = d_by_key['EAFE']; em = d_by_key['EM']; jp = d_by_key['JP']; acwi = d_by_key['ACWI']; uss = d_by_key['USS']
    out = dict(
        module='R3', name='2026年の長期予想（CMA）の中央値＝D の世界', generated=datetime.date.today().isoformat(), tool='night/bestpf_cma.py',
        prereg=PREREG,
        rule=dict(D='D_gross=(H×中央値＋(20−H)×B_gross)/20・D_net=D_gross−経費率−外国税（etf_forward_rank の C と同じ作り）',
                  min_houses=MIN_HOUSES, infl_for_real=INFL, main_editions='2026年版と名乗る版、または2026年に公表された版（Goldman Sachs は感度だけ）',
                  conversions='実質だけ→(1+r)(1.025)−1（GMO・2つの金利の中点）／算術→算術−σ²/2（State Street）／幅→中点（Vanguard）／他通貨は換算しない',
                  currency_priority='中央値はドル建ての値だけで作る（事前登録「名目ドル」）。ドル建てが5社に届かない種類は D＝C。'
                                    '現地通貨の値も混ぜた中央値は D_by_key[].ref_with_local_pct に参考として残す（D には使わない）。'
                                    '2026-10-12 の直し: 以前の版は「ドル建てが5社未満なら現地通貨も混ぜて D を作る」形だった（主の計算ではどの種類にも起きず、感度でだけ起きていた）'),
        houses=houses_out, houses_not_obtained=NOT_OBTAINED, cross_check_secondary=CROSS_CHECK,
        D_by_key=d_by_key, D_map=D_MAP, D_map_note=D_MAP_NOTE, asset_table=asset_table,
        D_net_by_asset={c: round(v, 6) for c, v in dnet.items()},
        D_inputs_by_key={k: dict(cma=round(table[k]['median'], 6), H=table[k]['H_median']) for k in KEYS if table[k]['made']},
        rows_source=rows_src,
        sensitivity=sens, sensitivity_D_net_by_asset=sens_dnet,
        jpm_check_vs_repo=jpm_check,
        accuracy=acc, present=pres,
    )
    # 気づいたこと（数字は上の表から）
    gv = {h['id']: (to_nominal_geo(h['v']['USG'])[0], to_nominal_geo(h['v']['USL'])[0]) for h in main_h if 'USG' in h['v'] and 'USL' in h['v']}
    vv = {h['id']: (to_nominal_geo(h['v']['USV'])[0], to_nominal_geo(h['v']['USL'])[0]) for h in main_h if 'USV' in h['v'] and 'USL' in h['v']}
    usl_vals = sorted(coll['USL'], key=lambda x: x[1])
    out['observations'] = [
        dict(what='米国大型の予想のばらつき', detail=f"最も低い {usl_vals[0][0]} {100 * usl_vals[0][1]:.1f}% 〜 最も高い {usl_vals[-1][0]} {100 * usl_vals[-1][1]:.1f}%（中央値 {usl['median_pct']:.1f}%）。"
             '低い側は「今の値段（CAPE 40）が平均へ戻る」を強く入れる会社（GMO・Research Affiliates・Invesco）。高い側は BlackRock の Starting point（同社の2025-09-30 時点の10年予想は 5.2%＝Morningstar 2026-01-12 の記事。上がった理由は原本の表に書かれておらず確かめられない。同じ表に別の場合として AI productivity boom 15.9%・Global risk premia rise 2.0% もある）'),
        dict(what='グロース（成長株）は米国大型より低く見られがち', detail=f"米国グロースを出す{len(gv)}社のうち{sum(1 for a, b in gv.values() if a < b)}社が米国大型より低い: " +
             '・'.join(f"{k} グロース {100 * a:.1f}% vs 大型 {100 * b:.1f}%" for k, (a, b) in gv.items()) +
             '。D では5社に届かないので、NASDAQ100・XLK・SMH などは JPM_MAP と同じく米国大型の数字を使った＝会社の見方より甘い側に置いている'),
        dict(what='バリュー（割安株）は米国大型より高く見られがち', detail=f"米国バリューを出す{len(vv)}社のうち{sum(1 for a, b in vv.values() if a > b)}社が米国大型より高い: " +
             '・'.join(f"{k} バリュー {100 * a:.1f}% vs 大型 {100 * b:.1f}%" for k, (a, b) in vv.items()) + '（GMO は Deep Value）'),
        dict(what='米国外のほうが高い（ドル建て）', detail=f"先進国（米国除く）{eafe['median_pct']:.1f}%・新興国 {em['median_pct']:.1f}%・日本 {jp['median_pct']:.1f}% vs 米国大型 {usl['median_pct']:.1f}%。"
             'ドル建ての予想にはドル安（他の通貨が上がる）を入れる会社が多い（Amundi: 円は適正値より約31%安い）。現地通貨の予想だけで作ると差は小さい（感度 S_all_currency）'),
        dict(what='過去の同じ種類の予想の当たり外れ', detail=acc['summary']),
        dict(what='今の値段', detail=f"CAPE（米国大型）{pres['cape']['us_large']}（1880年からの上位 {100 * (1 - pres['cape']['percentile_since_1880']):.1f}%）・"
             f"12か月先の PER {pres['factset']['forward_pe']}（10年平均と同じ）・上位10社 {pres['spy_top10']['top10_companies_pct']}%・"
             f"2026年の利益の伸びの予想 +{pres['factset']['eps_growth_cy2026']}%・2027年 +{pres['factset']['eps_growth_cy2027']}%・"
             f"大手4社の設備投資 直近12か月（2025-07〜2026-06）{pres['ai_capex']['total_ttm_bn']} 十億ドル（1年前の同じ12か月 {pres['ai_capex']['total_prev_bn']}・"
             f"{pres['ai_capex']['growth_pct']:+.0f}%）。"
             '利益が急に伸びているので、過去10年の利益で測る CAPE は「とても高い」、来年の利益で測る PER は「ふつう」と、物差しで答えが割れている'),
    ]
    # ── 感度の幅（候補ごと）: reading＝事前登録の中の読み方の揺れ ／ reference＝事前登録の外の参考 ──
    rd_names = [nm for nm, sv in sens.items() if sv['cls'] == 'reading']
    rf_names = [nm for nm, sv in sens.items() if sv['cls'] == 'reference']

    def _rng(c, names):
        vs = [(sens_dnet[nm][c], nm) for nm in names if c in sens_dnet[nm]]
        if not vs:
            return None
        lo, hi = min(vs), max(vs)
        return dict(min=round(lo[0], 5), min_by=lo[1], max=round(hi[0], 5), max_by=hi[1])
    sens_range = {}
    for c in dnet:
        sens_range[c] = dict(main=round(dnet[c], 5), C=round(rows[c]['C'], 5) if c in rows else None,
                             D_made=bool(detail.get(c, {}).get('D_made')),
                             reading=_rng(c, rd_names), with_reference=_rng(c, rd_names + rf_names))
    made_c = [c for c in dnet if detail.get(c, {}).get('D_made')]
    max_dc = max(made_c, key=lambda c: abs(detail[c]['D_minus_C'])) if made_c else None
    sens_dc = [(abs(sens_dnet[nm][c] - rows[c]['C']), c, nm) for nm in rd_names for c in sens_dnet[nm] if c in rows]
    sens_dc_max = max(sens_dc) if sens_dc else None
    out['sensitivity_range_by_asset'] = sens_range
    show = [c for c in ('VOO', 'QQQM', 'SMH', 'VT', 'VEA', 'VWO', 'TOPIX', 'VTV', 'VBR', 'XLI', 'XLF', 'XLY', 'GRID') if c in sens_range]
    pend_txt = []
    if r7_problem:
        pend_txt.append(f'R7 の行が読めなかった（{r7_problem}）→ R7 だけの本（MTUM・QUAL・XLI・XLF・XLY・GRID・EPI_LONG）は D_net が無く、load_D() が C で代える。直してから python3 night/bestpf_cma.py を回し直す')
    pend_txt += [f"{c}: {detail[c].get('note')}" for c in detail if detail[c].get('pending')]
    if unmapped_rows:
        pend_txt.append('D_MAP に無い行（D を作らず load_D() が C で代える）: ' + '・'.join(unmapped_rows))
    out['for_final'] = dict(
        how='night/bestpf_eval.py の load_D() は D_net_by_asset を読む（無い本は C で代える）。最終の採点の直前に python3 night/bestpf_cma.py を回し直す（R7 の行を読み直すため）。',
        pending=('・'.join(pend_txt) if pend_txt else 'なし（R7 の行も読めた: ' + '・'.join(r7_added) + '。MTUM・QUAL・EPI・EPI_LONG は5社未満の種類なので D＝C）'),
        sensitivity=('感度の幅は sensitivity_range_by_asset。reading（事前登録の中で読み方が分かれる所: ' + '・'.join(rd_names) + '）と、'
                     'with_reference（さらに事前登録の外の参考 ' + '・'.join(rf_names) + ' を入れた幅）を分けた。主と reading の最小〜最大: ' +
                     '・'.join(f"{c} {100 * sens_range[c]['main']:.2f}%（{100 * sens_range[c]['reading']['min']:.2f}〜{100 * sens_range[c]['reading']['max']:.2f}）"
                               for c in show if sens_range[c]['reading']) +
                     (f"。主の D と C の差の最大は {max_dc} の {100 * detail[max_dc]['D_minus_C']:+.2f}pt" if max_dc else '') +
                     (f"・reading の感度の中での最大は {sens_dc_max[1]}（{sens_dc_max[2]}）の C との差 {100 * sens_dc_max[0]:.2f}pt" if sens_dc_max else '') +
                     '。日本は5年の予想を外すとドル建てが4社になり D＝C、VTV は GMO の Deep Value を外すと米国バリューが4社になり D＝C'),
    )
    # ── 検証役の指摘への直し（2026-10-12） ──
    voo = sens_range.get('VOO', {}); usl_s = {nm: sens[nm]['by_key'].get('USL', {}).get('median') for nm in sens}
    jp_s = {nm: sens[nm]['by_key'].get('JP', {}) for nm in ('S_no_5y', 'S_no5y_fidi_arith')}
    em_s = {nm: sens[nm]['by_key'].get('EM', {}).get('median') for nm in ('S_no_5y', 'S_fidi_arith', 'S_no5y_fidi_arith')}
    cap = pres['ai_capex']
    out['fixes_applied'] = [
        dict(severity='medium', issue='感度に「5年の予想を外す」と「Fidelity International を算術と見る」が無く、米国大型の中央値と VOO の D_net の幅が狭く見えていた',
             fix='感度 S_no_5y（T. Rowe Price・Robeco を外す）・S_fidi_arith（FIDI を 算術−σ²/2。σ は同じ報告 p.11 の Volatility assumptions: DM equities 15.3%〔米国株の σ は無いので代用〕・EM 20.2%・--verify で棒の位置を確認）・S_no5y_fidi_arith（両方）を足した。for_final.sensitivity と summary_ja の幅をこの結果に合わせた',
             after=dict(USL_median_pct={k: usl_s.get(k) for k in ('S_no_5y', 'S_fidi_arith', 'S_no5y_fidi_arith')}, EM_median_pct=em_s,
                        JP=jp_s, VOO_D_net_reading_range_pct=([round(100 * voo['reading']['min'], 2), round(100 * voo['reading']['max'], 2)] if voo.get('reading') else None)),
             before='VOO の D_net の幅は 6.96〜7.11%（以前の7本の感度・現地通貨を混ぜる参考も含む）'),
        dict(severity='low', issue='設備投資の「前年 3,575億ドル」は1年前の12か月ではなかった（MSFT FY2025＋他3社の2025暦年＝直近12か月と6か月重なる）',
             fix='前年＝1年前の同じ12か月（2024-07〜2025-06）に替えた（SEC companyconcept の 2024暦年−2024年上期＋2025年上期・MSFT は FY2025）。357.5 は ref_msft_fy25_plus_cal2025_bn として「前年」と呼ばずに残した',
             before=dict(prev_bn=357.5, growth_pct=round(100 * (510.7 / 357.5 - 1), 1)),
             after=dict(prev_bn=cap['total_prev_bn'], growth_pct=cap['growth_pct'], ref_bn=cap['ref_msft_fy25_plus_cal2025_bn'])),
        dict(severity='low', issue='出力が R7（night/bestpf_ext.py）より前に作られ、XLI・XLF・XLY・GRID の D_net が無かった。R7 を読む所が例外を黙って捨てていた',
             fix='回し直して R7 の行を読んだ（足した本: ' + ('・'.join(r7_added) or 'なし') + '）。R7 が読めないときは rows_source と for_final.pending に理由を書く形にした。EPI_LONG（R7 の行）を D_MAP に足した（インド＝5社未満 → D＝C）',
             after={c: dict(D_net=round(100 * dnet[c], 3), C=round(100 * rows[c]['C'], 3)) for c in ('XLI', 'XLF', 'XLY', 'GRID', 'MTUM', 'QUAL', 'EPI_LONG') if c in dnet},
             r7_problem=r7_problem),
        dict(severity='low', issue='(a) ドル建てが5社未満の種類で、感度が現地通貨の値を「名目ドル」の中央値に混ぜていた（事前登録は D＝C）。(b) S_strict_2026_pub が Northern Trust（表紙 "RELEASED DECEMBER 2025"）を残していた',
             fix='(a) d_table を「ドル建てだけで中央値・5社未満なら D＝C」に直し、現地通貨を混ぜた値は ref_with_local に参考として別名で残した。S_all_currency と S_ssga_arith_raw は「参考（事前登録の外）」の印を付け、幅の主な数字（reading）から外した。'
                 '(b) S_strict_2026_pub は JPM と NT の両方を外す形にし、以前の JPM だけの版は S_no_JPM として残した',
             before=dict(S_strict_USL_pct=6.1, S_strict_VOO_D_net_pct=6.96, S_strict_JP_pct='6.7（7社・現地通貨込み）'),
             after=dict(S_strict_USL_pct=usl_s.get('S_strict_2026_pub'), S_strict_VOO_D_net_pct=round(100 * sens_dnet['S_strict_2026_pub'].get('VOO', float('nan')), 3),
                        S_strict_JP=sens['S_strict_2026_pub']['by_key'].get('JP'))),
        dict(severity='low', issue='説明の一部が出典より強く言い切っていた',
             fix='(1) BlackRock の米国大型 5.2%→9.0% の理由（「AI による利益の上方修正」）は原本に書かれていない → 「理由は確かめられない」に。'
                 '(2) Tower 2008 の順位の相関0.94 に「2000〜2008年の1回の窓・株5種類だけの例」を書き添えた。'
                 '(3) JPM 2021 の 4.1% を「米国株（記事の表現 "equity market returns"・大型か・幾何か算術かは不明）」に書き直した'),
    ]
    # 要約（やさしい日本語）
    out['summary_ja'] = (
        f"2026年に出た長期（5〜15年）の株の予想を {sum(1 for h in HOUSES if h['main'])} 社から集めた（Goldman Sachs は2025年11月なので感度だけ・Franklin は数字が取れなかった）。"
        f"中央値は 米国大型 {usl['median_pct']:.1f}%（{usl['n']}社・幅 {usl['min_pct']:.1f}〜{usl['max_pct']:.1f}）・米国小型 {uss['median_pct']:.1f}%・"
        f"先進国（米国除く）{eafe['median_pct']:.1f}%・日本 {jp['median_pct']:.1f}%・新興国 {em['median_pct']:.1f}%・全世界 {acwi['median_pct']:.1f}%（いずれも名目のドル建て・年率・ドル建ての値だけの中央値）。"
        f"米国大型は過去100年の平均（約10%）よりかなり低く、米国外のほうを高く見る会社が多い。"
        + (f"D（20年へ伸ばして費用と税を引いた後）と C の差は主の計算で最大 {abs(100 * detail[max_dc]['D_minus_C']):.2f}pt（{max_dc}）。"
           if max_dc else '')
        + (f"ただし読み方を変えると（5年の予想を外す・Fidelity を算術と見る・2026年公表だけ など）、米国大型の中央値は "
           f"{min([usl['median_pct']] + [usl_s[nm] for nm in rd_names if usl_s.get(nm) is not None]):.1f}〜"
           f"{max([usl['median_pct']] + [usl_s[nm] for nm in rd_names if usl_s.get(nm) is not None]):.1f}% まで動き、"
           f"VOO の D は {100 * voo['reading']['min']:.2f}〜{100 * voo['reading']['max']:.2f}% になる。" if voo.get('reading') else '')
        + "同じ方法の予想は2010年代の米国株を大きく低く見積もってきた（BNY 2016: 7.1%→実際13.4%）。")
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps({k: out[k] for k in ('summary_ja',)}, ensure_ascii=False, indent=1))
    for k in KEYS:
        e = d_by_key[k]
        if e['n']:
            print(f"{k:8s} n={e['n']:2d} made={e['made']!s:5s} median={e['median_pct']:.2f} H={e['H_median']} {e['houses']}")
    for c, d in asset_table.items():
        print(c, {kk: d.get(kk) for kk in ('key', 'D_made', 'cma', 'H', 'D_net', 'C_net', 'D_minus_C', 'pending')})


if __name__ == '__main__':
    main()
