#!/usr/bin/env python3
"""night/nx_osap_zoo_data.py — 角度 nx_osap_zoo（OSAP の残りの信号の全数調査）の【取得と整形だけ】（成績は計算しない・表示しない）

2026-09-28 ユーザー指示「市場に勝てる歴史検証が出るまでいろんな角度から調べて勝てる結果を出して…
別のSessionで検証していない新たな分析を同じ内容でしてほしい」。事前登録は out/nx_osap_zoo_prereg.json。

何をするか（リターンの平均・t・累積・勝率・市場との差は一度も計算しない）
  1. OSAP（Chen-Zimmermann・2025.10 版）の SignalDoc の予言変数 212 本すべてに、この角度での扱い（CLASS）を1本残らず付ける
     ——主の族 Z に入れる／報告だけ／除外（JKP 153 と同じ量・q07leu・兄弟 nx_osap_intang・nx_osap_info・他セッション）と理由
  2. 規則の台帳 RULES（主 Z・探索 ZC・報告 R）が使う組の月次リターン（小数）と銘柄数 Nlong を切り出す
       Z  : FF93style の BH（大型＝NYSE の時価の中央値超 × 変数の NYSE 70%点超・6月の値で組み7月〜翌6月持つ・時価加重）
       R  : 同じ信号の BL・BM・SH・SL・LS（報告）／QuintilesVW の 05（eknzbh と同じ形＝重複の報告）／離散の信号の VWforce の良い側
  3. 形だけを出す: 評価の開始（良い側の Nlong が初めて20以上）・終わり（最後の6月の組を1年持った所まで）・訓練/保有の月数・
     開始後に Nlong<20 で落ちる月・途中の欠け・Nlong の中央・信号の向きの確かめ（BH の signallag > BL の signallag の月の割合）
出力: out/_nx_cache/nx_osap_zoo_ports.json（gitignore）
  {'signals': {変数: {出典: {組: [[yyyymm, ret(小数), Nlong], …]}}}, 'shape': {規則: {…}}, 'class': {変数: {…}},
   'extract_sha256': 'signals' を sort_keys・区切り詰めで直列化した sha256, 'rules_sha256': RULES の sha256, 'class_sha256': CLASS の sha256}
  測る道具（night/nx_osap_zoo.py・これから書く）は最初に3つの sha と事前登録に書いた値の一致を確かめ、違えば止まる。

取得は兄弟の道具 night/nx_osap_intang_data.py の FILES・fetch・rows_of をそのまま使う（写さない）。
使い方: python3 night/nx_osap_zoo_data.py            … 取得・切り出し・形の表示
        python3 night/nx_osap_zoo_data.py --class    … 212本の扱いの表だけを表示（データは読まない）
"""
import csv, hashlib, io, json, os, statistics as S, sys, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nx_common as C  # noqa: E402
import nx_osap_intang_data as D  # noqa: E402  FILES・fetch・rows_of・ym を使う（写さない）

NMIN = 20              # 良い側の組の銘柄数の下限（兄弟と同じ）。評価はこの数に初めて届いた月から・その後に下回った月は落とす（0で埋めない）
LAST = 202412          # OSAP の最後の月
COST_PER_UNIT = 0.003  # 片道の売買 100% あたり 0.30%（兄弟 nx_osap_intang・eknzbh mw_factor_us と同じ単価）
BH_TURN = 1.0          # BH の片道の回転（年）の置き値＝上限。6月に年1回だけ組み直し、時価加重なので年の途中は売買が要らない
                       # （OSAP の重みは前月末の時価＝買って持つのと同じ）。6月に全部入れ替えても片道100%を超えない
COMP_TURN_ADD = 0.10   # 合成（ZC）を毎月等分へ戻す売買の足し分（兄弟の X3 と同じ）

# ───────────── 212本の扱い（CLASS）─────────────
# status:
#   Z        主の族（FF93 型の BH を French Mkt と比べて格付けする）
#   Z_near   主の族（同じ）。ただし JKP・他セッションの変数と「近い」（残差・変化・同じ論文の別の量）ので印を付ける
#   R_train  報告のみ: 保有期間（2007〜）の信号が無い（訓練期間だけの excess_stats）
#   R_thin   報告のみ: BH の良い側の銘柄数が20未満の月が多すぎる
#   R_dup    報告のみ: 離散の信号＝OSAP に FF93 型（大型・年1回）が無く、eknzbh mw_oap_signals が同じ組（VWforce の良い側）で既に格付けした
#   X_JKP    除外: JKP 153 の特性と同じ量（同じ分子と分母の考え・期間や割る数や遅れの違いだけ・対象を絞っただけ・JKP の特性の単純な組み合わせ）
#   X_Q07    除外: q07leu が試した（JKP 以外）
#   X_SIB    除外: 兄弟の角度 nx_osap_intang・nx_osap_info の主・探索・報告の規則に入っている
#   X_OTHER  除外: 他セッションが同じ経済の規則を別の作り方で試した
# jkp: 同じ量の JKP 特性（Factor Details の abr_jkp）。cite の一致（第1著者の姓＋年）は jkp_cite に別に書く
def _z(reason, flags=()):
    return {'status': 'Z', 'reason': reason, 'flags': list(flags)}


def _zn(reason, flags=()):
    return {'status': 'Z_near', 'reason': reason, 'flags': list(flags)}


def _xj(jkp, reason='', also=()):
    return {'status': 'X_JKP', 'jkp': jkp if isinstance(jkp, list) else [jkp], 'reason': reason, 'also': list(also)}


def _xs(rule):
    return {'status': 'X_SIB', 'reason': f'兄弟の規則 {rule}'}


CLASS = {
    # ── 主の族 Z（新しい形＝大型株だけ・年1回の組替え・時価加重。誰も BH で測っていない）──
    'AnnouncementReturn': _z('決算発表の前日〜2日後の市場調整リターン（CJL 1996）。JKP に無い（Factor Details の Abr は abr_jkp 無し）。q07leu pead・eknzbh の業績の勢いは会計の驚き niq_su 等で、株価の反応ではない'),
    'BetaLiquidityPS': _z('Pastor-Stambaugh の流動性のβ（60か月）。JKP に無い'),
    'BetaTailRisk': _z('Kelly-Jiang の裾のリスクのβ（120か月）。JKP に無い'),
    'CashProd': _z('現金の生産性（(時価−総資産)÷現金）。JKP に無い（JKP cash_at は現金÷総資産の水準）'),
    'CustomerMomentum': _z('主要顧客（Compustat の区分データ）の前月の株価リターン（Cohen-Frazzini 2008）。JKP に無い',
                           ['nx_leadlag の独立の答え合わせ（業種ではなく会社どうしの取引先のつながり）', '兄弟 intang は nx_leadlag に任せて外した→この角度で入れる（依頼の指示）']),
    'EarningsStreak': _z('アナリスト予想に対する驚きが同じ向きに続いた会社の驚き（Loh-Warachka 2012・I/B/E/S）。JKP に無い・兄弟 info の規則に無い'),
    'EarnSupBig': _z('同じ業種の大型30%の会社の利益の驚きを、大型30%以外の会社に当てる（Hou 2007・業種の中の先行遅行）。JKP に無い',
                     ['nx_leadlag と近い考え（情報の遅れの伝わり）', '定義上、時価の上位30%の会社は信号を持たない＝BH は NYSE の中央値〜全銘柄の上位30%の会社だけ']),
    'Frontier': _z('簿価時価比を会社の特徴で説明した回帰の残差（Nguyen-Swanson 2009・効率的フロンティア）。JKP に無い'),
    'IndRetBig': _z('同じ業種の大型30%の会社の前月のリターンを、大型30%以外の会社に当てる（Hou 2007）。JKP に無い。業種の勢い（IndMom・q07leu indmom）は業種自身の6か月で別の量',
                    ['nx_leadlag と近い考え（情報の遅れの伝わり）', '定義上、時価の上位30%の会社は信号を持たない']),
    'iomom_cust': _z('BEA の産業連関表で重みづけした顧客の業種の前月のリターン（Menzly-Ozbas 2010）。JKP に無い',
                     ['nx_leadlag の独立の答え合わせ（nx_leadlag は業種の組、こちらは会社の組・OSAP の作り方）', '兄弟 intang は nx_leadlag に任せて外した→この角度で入れる（依頼の指示）']),
    'iomom_supp': _z('BEA の産業連関表で重みづけした仕入れ先の業種の前月のリターン（Menzly-Ozbas 2010）。JKP に無い',
                     ['nx_leadlag の独立の答え合わせ', '兄弟 intang は nx_leadlag に任せて外した→この角度で入れる（依頼の指示）']),
    'OrderBacklog': _z('受注残÷平均総資産（Rajgopal ほか 2003・符号−＝少ない側が良い）。JKP に無い',
                       ['main の moat4 C1（受注残の倍率・2019-21 の3起点・SEC XBRL・約200社・不合格）の独立の答え合わせ（長い歴史・大型株）。兄弟 intang は main に任せて外した']),
    'OrderBacklogChg': _z('受注残÷平均総資産の前年差（Baik-Ahn 2007・符号＋）。JKP に無い', ['main の moat4 C1 の独立の答え合わせ']),
    'DelDRC': _z('前受収益の前年差÷平均総資産（Prakash-Sinha 2013）。JKP に無い。BH は 2002-07 から＝訓練が15年に満たない→短い標本の線（criteria_short_sample）',
                 ['main の moat_dr（前受収益の倍率・2013/16/17/18・不合格）の独立の答え合わせ。兄弟 intang は main に任せて外した']),
    'PriceDelayRsq': _z('市場の過去のリターンへの遅れた反応（Hou-Moskowitz 2005・決定係数の版）。JKP に無い', ['同じ論文の3つの版（Rsq・Slope・Tstat）＝独立の試行は1つに近い']),
    'PriceDelaySlope': _z('同じ（係数の版）', ['同じ論文の3つの版']),
    'PriceDelayTstat': _z('同じ（t値の版）', ['同じ論文の3つの版']),
    'realestate': _z('不動産の保有の割合（業種の平均を引く・Tuzel 2010）。JKP に無い（JKP tangibility は有形固定資産全体）'),
    'retConglomerate': _z('多角化企業の各事業の業種の単一事業の会社の前月リターンを売上で加重（Cohen-Lou 2012）。JKP に無い', ['nx_leadlag と近い考え（情報の遅れの伝わり）']),
    # ── 主の族 Z_near（近い・印つき）──
    'AbnormalAccruals': _zn('発生主義の利益の「異常な部分」（業種×年の回帰の残差・Xie 2001）。JKP の oaccruals_at（Sloan 1996）・q07leu accruals（oaccruals_ni）は発生主義の利益そのもの＝この角度の線（同じ量か）では別の量',
                            ['Xie (2001) は JKP の capx_gr1 の cite と同じ（別の変数）', '兄弟 intang は「JKP の発生主義・q07leu accruals と同じ経済の信号」として外した＝判定が兄弟と違う']),
    'ChAssetTurnover': _zn('資産回転率の前年差（Soliman 2008）。JKP sale_bev（Soliman 2008）は水準で、変化は無い', ['Soliman (2008) は JKP ebit_bev・ebit_sale・sale_bev の cite と同じ']),
    'IntanBM': _zn('5年リターンのうち簿価時価比の変化で説明できない部分（無形のリターン・Daniel-Titman 2006）。JKP ret_60_12・q07leu lt_reversal は生の過去リターン＝別の量',
                   ['Daniel-Titman (2006) は JKP eqnpo_12m の cite と同じ（別の変数）', '兄弟 intang は「長期の逆張り・JKP と同じ論文」として外した＝判定が兄弟と違う', '同じ論文の4つの版（BM・CFP・EP・SP）']),
    'IntanCFP': _zn('同じ（キャッシュフロー÷時価の版）', ['同じ論文の4つの版', '兄弟 intang は外した']),
    'IntanEP': _zn('同じ（益回りの版）', ['同じ論文の4つの版', '兄弟 intang は外した']),
    'IntanSP': _zn('同じ（売上÷時価の版）', ['同じ論文の4つの版', '兄弟 intang は外した']),
    'betaVIX': _zn('VIX の日次の変化へのβ（1か月・Ang ほか 2006）。JKP の ivol_ff3_21d・rvol_21d は同じ論文の別の量（自分のぶれ）', ['Ang et al. (2006) は JKP ivol_ff3_21d・rvol_21d の cite と同じ']),
    'VarCF': _zn('(利益＋減価償却)÷時価の60か月の分散（Haugen-Baker 1996）。JKP ocfq_saleq_std（営業CF÷売上のぶれ）・earnings_variability とは作り方が違う（時価で割る）',
                 ['Haugen-Baker (1996) は JKP at_turnover・ni_be の cite と同じ']),
    'VolumeTrend': _zn('出来高の60か月の傾き（Haugen-Baker 1996）。JKP に傾きは無い（turnover_126d・dolvol_var_126d は水準とぶれ）', ['Haugen-Baker (1996) は JKP の cite と同じ']),
    'TrendFactor': _zn('3〜1000日の移動平均の比を回帰で合成した価格の趨勢（Han-Zhou-Zhu 2016）。JKP に無い。株の勢い（eknzbh・q07leu）とは別の量だが価格の趨勢の仲間', ['株価の勢いの仲間']),
    # ── 報告のみ ──
    'Activism1': {'status': 'R_train', 'reason': 'G 指数（Governance・1990〜2006）から作る＝BH の最後の6月の組は 2006-06・保有期間は 2007-01〜06 の6か月だけ。eknzbh は主の族で格付け済み'},
    'Activism2': {'status': 'R_train', 'reason': '同じ（G 指数から作る・保有期間の信号が無い）'},
    'ProbInformedTrading': {'status': 'R_thin', 'reason': 'PIN（Easley ほか 2002）は 2013 年の推定で終わり、BH の良い側は銘柄数の中央値22・Nlong<20 で落ちる月が114（訓練12か月・保有30か月しか残らない）。'
                            '★eknzbh の検証の一覧で Q5 の格付け（B）を見てしまった（contamination）'},
    # 離散（FF93 型が無い）＝eknzbh が VWforce の良い側で格付け済み
    'DivInit': {'status': 'R_dup', 'reason': '離散（配当の開始・Michaely-Thaler-Womack 1995）。eknzbh の主の族（Event）で VWforce の良い側と大型版（ME>NYSE20%）を格付け済み'},
    'DivOmit': {'status': 'R_dup', 'reason': '離散（配当の停止・符号−＝良い側は停止しなかった会社＝市場のほぼ全部）。eknzbh の主の族で格付け済み'},
    'DivSeason': {'status': 'R_dup', 'reason': '離散（配当の季節性・Hartzmark-Salomon 2013）。eknzbh の主の族で格付け済み'},
    'DivYieldST': {'status': 'R_dup', 'reason': '離散（翌月の配当の予想・Litzenberger-Ramaswamy 1979＝JKP div12m_me と同じ論文の別の量）。eknzbh の副の族で格付け済み'},
    'ExchSwitch': {'status': 'R_dup', 'reason': '離散（取引所の移動・符号−）。eknzbh の主の族で格付け済み'},
    'IndIPO': {'status': 'R_dup', 'reason': '離散（新規上場・符号−）。eknzbh の主の族で格付け済み'},
    'RDIPO': {'status': 'R_dup', 'reason': '離散（研究開発の無い新規上場・符号−）。eknzbh の主の族で格付け済み'},
    'DebtIssuance': {'status': 'R_dup', 'reason': '離散（社債の発行・Spiess-Affleck-Graves 1999・符号−）。JKP dbnetis_at（純負債の発行）と近い。eknzbh の副の族で格付け済み'},
    'ConvDebt': {'status': 'R_dup', 'reason': '離散（転換社債の有無・Valta 2016・符号−）。eknzbh の副の族で格付け済み'},
    'RIO_Disp': {'status': 'R_dup', 'reason': '離散（機関の保有の残差×予想のばらつき・Nagel 2005）。eknzbh の主の族（13F）で格付け済み'},
    'RIO_MB': {'status': 'R_dup', 'reason': '離散（機関の保有の残差×時価簿価比）。eknzbh の主の族で格付け済み'},
    'RIO_Turnover': {'status': 'R_dup', 'reason': '離散（機関の保有の残差×売買回転）。eknzbh の主の族で格付け済み'},
    'RIO_Volatility': {'status': 'R_dup', 'reason': '離散（機関の保有の残差×固有のぶれ）。eknzbh の主の族で格付け済み'},
    'AccrualsBM': {'status': 'R_dup', 'reason': '離散（簿価時価比の高い×発生主義の低い・Bartov-Kim 2004＝JKP be_me と oaccruals_at の組み合わせ）。eknzbh の副の族で格付け済み'},
    'MomRev': {'status': 'R_dup', 'reason': '離散（勢い×長期の逆張り・Chan-Ko 2006＝JKP ret_12_1 と ret_60_12 の組み合わせ）。eknzbh の副の族で格付け済み'},
    'MomVol': {'status': 'R_dup', 'reason': '離散（勢い×出来高・Lee-Swaminathan 2000＝JKP ret_6_1 と turnover の組み合わせ）。eknzbh の副の族で格付け済み'},
    'Governance': {'status': 'R_train', 'reason': '離散（G 指数・1990〜2006）。保有期間の信号が無い。eknzbh の副の族で格付け済み'},
    # ── 除外: 兄弟の角度 ──
    **{s: _xs('nx_osap_intang ' + r) for s, r in [
        ('OrgCap', 'P1・X1・X2'), ('AdExp', 'P2・X1・X2'), ('BrandInvest', 'P3・X1・X2'), ('RDAbility', 'P4'), ('SurpriseRD', 'P5'), ('Herf', 'P6・X1・X2'),
        ('MS', 'P7'), ('FR', 'P8・X1・X2'), ('GrAdExp', 'X4'), ('EarningsConsistency', 'X4'), ('RDS', 'X4'), ('HerfBE', 'X4'), ('HerfAsset', 'X4'),
        ('PatentsRD', 'R1（訓練だけ）'), ('CitationsRD', 'R1（訓練だけ）')]},
    **{s: _xs('nx_osap_info ' + r) for s, r in [
        ('ShortInterest', 'P1・XL1・XL17'), ('CredRatDG', 'P2'), ('REV6', 'P3・XL2・XL18'), ('AnalystRevision', 'P4・XL3・XL19'),
        ('ForecastDispersion', 'P5・XL4・XL20'), ('fgr5yrLag', 'P6・XL5・XL21'), ('ConsRecomm', 'Q1'), ('ChangeInRecommendation', 'Q2・XS12・XS15'),
        ('skew1', 'Q3・XS13・XS16'), ('EarningsForecastDisparity', 'XL6'), ('sfe', 'XL7'), ('FEPS', 'XL8'), ('AnalystValue', 'XL9'), ('AOP', 'XL10'),
        ('PredictedFE', 'XL11'), ('ExclExp', 'XL12'), ('ChNAnalyst', 'XL13'), ('ChForecastAccrual', 'XL14'), ('DelBreadth', 'XL15'),
        ('UpRecomm', 'XS1'), ('DownRecomm', 'XS2'), ('Recomm_ShortInterest', 'XS3'), ('SmileSlope', 'XS4'), ('CPVolSpread', 'XS5'),
        ('RIVolSpread', 'XS6'), ('dVolCall', 'XS7'), ('dVolPut', 'XS8'), ('dCPVolSpread', 'XS9'), ('OptionVolume1', 'XS10'), ('OptionVolume2', 'XS11'),
        ('IO_ShortInterest', 'R（報告）')]},
    # ── 除外: 他セッション（JKP 以外）──
    'IndMom': {'status': 'X_OTHER', 'reason': '業種の勢い（Grinblatt-Moskowitz 1999）＝q07leu indmom（French 49業種）・eknzbh の業種の勢い・q07leu tech_switch で試した'},
    'sinAlgo': {'status': 'X_Q07', 'reason': '罪の株（Hong-Kacperczyk 2009）＝q07leu sin（French の Smoke・Beer・Fun）で試した'},
    'Spinoff': {'status': 'X_OTHER', 'reason': 'スピンオフ（Cusatis ほか 1993）＝hbm38n ev5 のスピンオフで試した。eknzbh の主の族でも格付け済み（離散）'},
    # ── 除外: JKP 153 と同じ量 ──
    'Accruals': _xj('oaccruals_at', 'Sloan (1996)・同じ論文', ['q07leu accruals']),
    'AM': _xj('at_me', 'Fama-French (1992)・同じ論文'),
    'AssetGrowth': _xj('at_gr1', 'Cooper-Gulen-Schill (2008)・同じ論文'),
    'Beta': _xj('beta_60m', 'Fama-MacBeth (1973)・同じ論文'),
    'BetaFP': _xj('betabab_1260d', 'Frazzini-Pedersen (2014)・同じ論文', ['q07leu lowbeta_lev']),
    'BidAskSpread': _xj('bidaskhl_21d', 'OSAP の定義は Corwin-Schultz の高値安値の推定＝JKP と同じ推定'),
    'BM': _xj('be_me', '簿価÷時価（Stattman 1980）＝JKP be_me（Rosenberg ほか 1985）と同じ量'),
    'BMdec': _xj('be_me', '12月の時価で割る簿価時価比（Fama-French 1992）'),
    'BookLeverage': _xj('at_be', 'Fama-French (1992)・同じ論文'),
    'BPEBM': _xj(['be_me', 'bev_mev'], '簿価時価比の負債の部分＝BP − EBM（Penman-Richardson-Tuna 2007・JKP bev_mev・netdebt_me と同じ論文）＝JKP の2特性の差'),
    'Cash': _xj('cash_at', 'Palazzo (2012)・同じ論文'),
    'CBOperProf': _xj('cop_atl1', 'Ball ほか (2016)・同じ論文'),
    'CF': _xj(['fcf_me', 'ocf_me'], '(利益＋減価償却)÷時価（LSV 1994＝JKP fcf_me と同じ論文）＝キャッシュフロー利回り'),
    'cfp': _xj('ocf_me', 'Desai ほか (2004)・同じ論文'),
    'ChEQ': _xj('be_gr1a', '自己資本の伸び（分子は同じ自己資本の変化・割る数だけ違う）'),
    'ChInv': _xj('inv_gr1a', 'Thomas-Zhang (2002)・同じ論文'),
    'ChInvIA': _xj('capx_gr1', '設備投資の伸び（業種の平均を引く）・Abarbanell-Bushee (1998) は JKP dsale_dinv ほかの cite と同じ'),
    'ChNNCOA': _xj('nncoa_gr1a', '非流動の純営業資産の変化'),
    'ChNWC': _xj('cowc_gr1a', '運転資本の変化'),
    'ChTax': _xj('tax_gr1a', 'Thomas-Zhang (2011)・同じ論文'),
    'CompEquIss': _xj('eqnpo_12m', 'Daniel-Titman (2006) の複合的な株式の発行・同じ論文'),
    'CompositeDebtIssuance': _xj('debt_gr3', 'Lyandres-Sun-Zhang (2008)・同じ論文'),
    'CoskewACX': _xj('coskew_21d', '共歪度（Ang-Chen-Xing 2006 は JKP betadown_252d の cite と同じ）'),
    'Coskewness': _xj('coskew_21d', 'Harvey-Siddique (2000)・同じ論文'),
    'DelCOA': _xj('coa_gr1a', 'Richardson ほか (2005)'), 'DelCOL': _xj('col_gr1a', 'Richardson ほか (2005)'),
    'DelEqu': _xj('be_gr1a', 'Richardson ほか (2005)'), 'DelFINL': _xj('fnl_gr1a', 'Richardson ほか (2005)'),
    'DelLTI': _xj('lti_gr1a', 'Richardson ほか (2005)'), 'DelNetFin': _xj('nfna_gr1a', 'Richardson ほか (2005)'),
    'dNoa': _xj('noa_gr1a', 'Hirshleifer ほか (2004)'),
    'DolVol': _xj('dolvol_126d', 'Brennan ほか (1998)', ['q07leu turnover']),
    'EarningsSurprise': _xj('niq_su', 'Foster-Olsen-Shevlin (1984)', ['q07leu pead']),
    'EBM': _xj('bev_mev', 'Penman-Richardson-Tuna (2007)'),
    'EntMult': _xj('ebitda_mev', 'Loughran-Wellman (2011)'),
    'EP': _xj('ni_me', '益回り（Basu 1977・JKP は Basu 1983）'),
    'EquityDuration': _xj('eq_dur', 'Dechow-Sloan-Soliman (2004)'),
    'FirmAge': _xj('age', '上場からの年数', ['q07leu old_firms']),
    'FirmAgeMom': _xj('ret_6_1', '6か月の勢いを若い会社（年数の最下位五分位）に絞っただけ（Zhang 2006）＝対象を絞った同じ量'),
    'AgeIPO': _xj('age', '新規上場の会社の創業からの年数（Ritter 1991）＝会社の年数を新規上場に絞った同じ量。eknzbh の主の族（Event）で VWforce 以外に大型版（ME>NYSE20%）も格付け済み', ['q07leu old_firms']),
    'GP': _xj('gp_at', 'Novy-Marx (2013)'),
    'grcapx': _xj('capx_gr2', 'Anderson-Garcia-Feijoo (2006)'), 'grcapx3y': _xj('capx_gr3', 'Anderson-Garcia-Feijoo (2006)'),
    'GrLTNOA': _xj('lnoa_gr1a', 'Fairfield-Whisenant-Yohn (2003)'),
    'GrSaleToGrInv': _xj('dsale_dinv', 'Abarbanell-Bushee (1998)'), 'GrSaleToGrOverhead': _xj('dsale_dsga', 'Abarbanell-Bushee (1998)'),
    'High52': _xj('prc_highprc_252d', 'George-Hwang (2004)', ['q07leu hi52']),
    'hire': _xj('emp_gr1', 'Belo-Lin-Bazdresch (2014)'),
    'IdioVol3F': _xj('ivol_ff3_21d', 'Ang ほか (2006)'), 'IdioVolAHT': _xj('ivol_capm_252d', 'Ali-Hwang-Trombley (2003)'),
    'Illiquidity': _xj('ami_126d', 'Amihud (2002)'),
    'IntMom': _xj('ret_12_7', 'Novy-Marx (2012)'),
    'Investment': _xj('capex_abn', 'Titman-Wei-Xie (2004)'),
    'InvestPPEInv': _xj('ppeinv_gr1a', 'Lyandres-Sun-Zhang (2008)'),
    'InvGrowth': _xj('inv_gr1', 'Belo-Lin (2012)', ['q07leu investment は inv_gr1']),
    'Leverage': _xj('debt_me', 'Bhandari (1988)'),
    'LRreversal': _xj('ret_60_12', 'De Bondt-Thaler (1985)', ['q07leu lt_reversal']),
    'MaxRet': _xj('rmax1_21d', 'Bali-Cakici-Whitelaw (2011)', ['q07leu lottery']),
    'MeanRankRevGrowth': _xj(['sale_gr3', 'sale_gr1'], '過去5年の売上の伸びの順位（LSV 1994・同じ論文）'),
    'Mom12m': _xj('ret_12_1', 'Jegadeesh-Titman (1993)'), 'Mom6m': _xj('ret_6_1', 'Jegadeesh-Titman (1993)'),
    'Mom12mOffSeason': _xj('seas_1_1na', 'Heston-Sadka (2008)'),
    'Mom6mJunk': _xj('ret_6_1', '6か月の勢いを格付けの低い会社に絞っただけ（Avramov ほか 2007）。★eknzbh の検証の一覧で格付け（D10 が B）を見てしまった'),
    'MomOffSeason': _xj('seas_2_5na', 'Heston-Sadka (2008)', ['q07leu seas']), 'MomOffSeason06YrPlus': _xj('seas_6_10na', 'Heston-Sadka (2008)'),
    'MomOffSeason11YrPlus': _xj('seas_11_15na', 'Heston-Sadka (2008)'), 'MomOffSeason16YrPlus': _xj('seas_16_20na', 'Heston-Sadka (2008)'),
    'MomSeason': _xj('seas_2_5an', 'Heston-Sadka (2008)', ['q07leu seas']), 'MomSeason06YrPlus': _xj('seas_6_10an', 'Heston-Sadka (2008)'),
    'MomSeason11YrPlus': _xj('seas_11_15an', 'Heston-Sadka (2008)'), 'MomSeason16YrPlus': _xj('seas_16_20an', 'Heston-Sadka (2008)'),
    'MomSeasonShort': _xj('seas_1_1an', 'Heston-Sadka (2008)', ['q07leu seas']),
    'MRreversal': _xj('ret_60_12', '月 t−18〜t−13 の過去リターン（De Bondt-Thaler 1985・同じ論文）＝過去リターンの窓違い'),
    'NetDebtFinance': _xj('dbnetis_at', 'Bradshaw-Richardson-Sloan (2006)'), 'NetEquityFinance': _xj('eqnetis_at', 'Bradshaw-Richardson-Sloan (2006)'),
    'XFIN': _xj('netis_at', 'Bradshaw-Richardson-Sloan (2006)'),
    'NetDebtPrice': _xj('netdebt_me', 'Penman-Richardson-Tuna (2007)'),
    'NetPayoutYield': _xj('eqnpo_me', 'Boudoukh ほか (2007)'), 'PayoutYield': _xj('eqpo_me', 'Boudoukh ほか (2007)'),
    'NOA': _xj('noa_at', 'Hirshleifer ほか (2004)'),
    'NumEarnIncrease': _xj('ni_inc8q', '利益が前年同期より増えた四半期の連続数（最大8）＝Barth-Elliott-Finn (1999) の量（兄弟 intang の判定を引き継ぐ）'),
    'OperProf': _xj('ope_be', 'Fama-French (2006/2015)'),
    'OperProfRD': _xj(['op_at', 'op_atl1'], '研究開発を足し戻した営業利益÷総資産（Ball ほか 2016・同じ論文）'),
    'OPLeverage': _xj('opex_at', 'Novy-Marx (2011)'),
    'PctAcc': _xj('oaccruals_ni', 'Hafzalla ほか (2011)', ['q07leu accruals']), 'PctTotAcc': _xj('taccruals_ni', 'Hafzalla ほか (2011)'),
    'Price': _xj('prc', '株価'),
    'PS': _xj('f_score', 'Piotroski (2000)'),
    'RD': _xj('rd_me', 'Chan-Lakonishok-Sougiannis (2001)', ['q07leu rd']), 'RDcap': _xj('rd5_at', 'Li (2011)'),
    'RealizedVol': _xj('rvol_21d', 'Ang ほか (2006)'),
    'ResidualMomentum': _xj('resff3_12_1', 'Blitz-Huij-Martens (2011)', ['q07leu resmom']),
    'ReturnSkew': _xj('rskew_21d', 'Bali-Engle-Murray (2016)', ['q07leu lottery']), 'ReturnSkew3F': _xj('iskew_ff3_21d', 'Bali-Engle-Murray (2016)'),
    'RevenueSurprise': _xj('saleq_su', 'Jegadeesh-Livnat (2006)'),
    'roaq': _xj('niq_at', 'Balakrishnan-Bartov-Faurel (2010)'),
    'RoE': _xj('ni_be', 'Haugen-Baker (1996)'),
    'ShareIss1Y': _xj('chcsho_12m', 'Pontiff-Woodgate (2008)。★eknzbh の結果の要約で格付けを見てしまった', ['q07leu payout']),
    'ShareIss5Y': _xj(['chcsho_12m', 'eqnpo_12m'], '5年の株数の変化（Daniel-Titman 2006・JKP eqnpo_12m と同じ論文）＝株数の変化の窓違い。★eknzbh の結果の要約で格付けを見てしまった'),
    'Size': _xj('market_equity', 'Banz (1981)。FF93 型にも無い'),
    'SP': _xj('sale_me', 'Barbee-Mukherji-Raines (1996)'),
    'std_turn': _xj('turnover_var_126d', 'Chordia-Subrahmanyam-Anshuman (2001)'),
    'STreversal': _xj('ret_1_0', 'Jegadeesh (1990)'),
    'tang': _xj('tangibility', 'Hahn-Lee (2009)'),
    'Tax': _xj('pi_nix', 'Lev-Nissim (2004)（兄弟 intang の判定を引き継ぐ）'),
    'TotalAccruals': _xj('taccruals_at', 'Richardson ほか (2005)'),
    'VolMkt': _xj('turnover_126d', '売買代金÷時価＝売買回転（Haugen-Baker 1996）'),
    'VolSD': _xj('dolvol_var_126d', 'Chordia-Subrahmanyam-Anshuman (2001)'),
    'zerotrade1M': _xj('zero_trades_21d', 'Liu (2006)'), 'zerotrade6M': _xj('zero_trades_126d', 'Liu (2006)'),
    'zerotrade12M': _xj('zero_trades_252d', 'Liu (2006)'),
    'OScore': _xj('o_score', 'Dichev (1998)・離散'),
    'ShareVol': _xj('turnover_126d', 'Datar-Naik-Radcliffe (1998)・離散'),
    'ShareRepurchase': _xj(['eqpo_me', 'chcsho_12m'], '自社株買いの有無（Ikenberry ほか 1995）＝JKP の純還元・株数の変化と同じ経済の信号（兄弟 intang の判定を引き継ぐ）・離散', ['q07leu payout']),
}

Z_IDS = sorted(s for s, v in CLASS.items() if v['status'] in ('Z', 'Z_near'))
SHORT_SAMPLE = {'DelDRC'}   # 訓練が15年に満たない（BH が 2002-07 から）＝criteria_short_sample

# ───────────── 規則の台帳（事前登録と同じ）─────────────
RULES = []
for s in Z_IDS:
    RULES.append(dict(id=f'Z_{s}_BH', fam='Z', signal=s, file='FF93style', port='BH', turn=BH_TURN,
                      criteria='short' if s in SHORT_SAMPLE else 'long', near=CLASS[s]['status'] == 'Z_near'))
ZC = [
    dict(id='ZC1_ALL', fam='ZC', parts=[f'Z_{s}_BH' for s in Z_IDS], min_legs=10, turn_add=COMP_TURN_ADD,
         what='主の族 Z の全部の BH を等分（その月に使える脚だけ・毎月等分へ戻す）'),
    dict(id='ZC2_LINKS', fam='ZC', parts=[f'Z_{s}_BH' for s in ['CustomerMomentum', 'iomom_cust', 'iomom_supp', 'IndRetBig', 'EarnSupBig', 'retConglomerate']],
         min_legs=3, turn_add=COMP_TURN_ADD, what='つながった会社・業種の情報の遅れ（顧客・仕入れ先・同じ業種の大型・多角化企業の事業）'),
    dict(id='ZC3_ACCT', fam='ZC', parts=[f'Z_{s}_BH' for s in ['AbnormalAccruals', 'ChAssetTurnover', 'CashProd', 'Frontier', 'realestate',
                                                                  'OrderBacklog', 'OrderBacklogChg', 'DelDRC', 'VarCF']],
         min_legs=4, turn_add=COMP_TURN_ADD, what='会計から作る信号（発生主義の異常・資産回転の変化・現金の生産性・割安の残差・不動産・受注残・前受収益・CF のぶれ）'),
]
RULES += ZC
# 報告のみ（格付けに数えない）
R_DUP_TURN = {'1': 2.0, '3': 1.0, '6': 0.7, '12': 0.5, '36': 0.3, 'NA': 0.5}   # eknzbh mw_oap_signals_prereg の置き値（SignalDoc の Portfolio Period 別・不明は0.5。重複の報告を同じ物差しで並べるため）
R_DUP_FAST = {'AnnouncementReturn', 'betaVIX', 'IndRetBig'}          # eknzbh が「速い」（年6.0）に入れた信号のうち Z にあるもの
REPORT = []
for s in Z_IDS:
    REPORT.append(dict(id=f'R_dupQ5_{s}', fam='R_dup', signal=s, file='QuintilesVW', port='05', turn_rule='eknzbh'))
for s in sorted(k for k, v in CLASS.items() if v['status'] == 'R_dup'):
    REPORT.append(dict(id=f'R_dupVWF_{s}', fam='R_dup', signal=s, file='VWforce', port='TOP', turn_rule='eknzbh'))
for s in ['Activism1', 'Activism2', 'ProbInformedTrading']:
    REPORT.append(dict(id=f'R_BH_{s}', fam='R_train' if CLASS[s]['status'] == 'R_train' else 'R_thin', signal=s, file='FF93style', port='BH', turn=BH_TURN))
REPORT.append(dict(id='R_dupVWF_Governance', fam='R_train', signal='Governance', file='VWforce', port='TOP', turn_rule='eknzbh'))

# 切り出す組
NEED = {'FF93style': {}, 'QuintilesVW': {}, 'VWforce': {}}
for s in Z_IDS + ['Activism1', 'Activism2', 'ProbInformedTrading']:
    NEED['FF93style'][s] = {'BH', 'BL', 'BM', 'SH', 'SL', 'LS'}
for s in Z_IDS + ['Activism1', 'Activism2', 'ProbInformedTrading']:
    NEED['QuintilesVW'][s] = {'05', '01', 'LS'}
for s, v in CLASS.items():
    if v['status'] == 'R_dup' or s == 'Governance':
        NEED['VWforce'][s] = None   # None = すべての組（良い側＝最大の番号は形で決める）


def _sha(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def rules_sha():
    return _sha({'RULES': RULES, 'REPORT': REPORT, 'consts': {'NMIN': NMIN, 'LAST': LAST, 'COST_PER_UNIT': COST_PER_UNIT, 'BH_TURN': BH_TURN,
                                                              'COMP_TURN_ADD': COMP_TURN_ADD, 'R_DUP_TURN': R_DUP_TURN, 'R_DUP_FAST': sorted(R_DUP_FAST)}})


def class_sha():
    return _sha(CLASS)


def signaldoc():
    b = D.fetch('SignalDoc')
    return {r['Acronym']: r for r in D.rows_of('SignalDoc', b)}


def jkp_cite_match(doc):
    """兄弟と同じ方法の1段目: JKP の Factor Details.xlsx の cite（第1著者の姓＋年）と SignalDoc の Authors の第1語＋Year の一致。
    一致は『同じ論文』の候補にすぎない（同じ論文の別の変数もある）ので、2段目の定義の読みは CLASS に手で書いた。
    綴りの違い（OSAP Hirschleifer / JKP Hirshleifer・JKP Jegedeesh・Assness）は拾えない＝定義の読みで補った"""
    import re
    import openpyxl
    b = C.get('https://raw.githubusercontent.com/bkelly-lab/ReplicationCrisis/master/GlobalFactors/Factor%20Details.xlsx',
              name='jkp_factor_details.xlsx', max_age_days=3650)
    wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True)
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    h = rows[0]
    jk = []
    for rr in rows[1:]:
        d = dict(zip(h, rr))
        if not d.get('abr_jkp'):
            continue
        cite = str(d.get('cite') or '')
        m = re.search(r'\((\d{4})\)', cite) or re.search(r'(\d{4})', cite)
        jk.append((re.split(r'[ ,]', cite.strip())[0].lower(), int(m.group(1)) if m else None, d['abr_jkp']))
    out = {}
    for a, r in doc.items():
        if r['Cat.Signal'] != 'Predictor':
            continue
        first = re.split(r'[ ,]', r['Authors'].strip())[0].lower()
        yr = int(r['Year']) if r['Year'].isdigit() else None
        out[a] = sorted(abr for f, y, abr in jk if f == first and y == yr)
    return out, {'n_jkp': len(jk), 'sha256': hashlib.sha256(b).hexdigest()}


def check_class(doc):
    """212本すべてに扱いが付いていること・余分が無いことを確かめる（付いていなければ止まる）"""
    pred = {a for a, r in doc.items() if r['Cat.Signal'] == 'Predictor'}
    miss, extra = sorted(pred - set(CLASS)), sorted(set(CLASS) - pred)
    if miss or extra:
        raise SystemExit(f'CLASS が SignalDoc の予言変数と合わない: 無い {miss} / 余分 {extra}')
    return len(pred)


def nxt(m):
    return m + 1 if m % 100 != 12 else (m // 100 + 1) * 100 + 1


def eval_window(rows, end):
    """評価の開始＝Nlong が初めて NMIN 以上で ret がある月。終わり＝end。→ (開始, 使える月, 開始後に落ちる月, 途中の欠け)"""
    st = next((m for m, r, n in rows if r is not None and n is not None and n >= NMIN), None)
    if st is None:
        return None, [], 0, 0
    ev = [(m, r, n) for m, r, n in rows if st <= m <= end]
    good = [x for x in ev if x[1] is not None and x[2] is not None and x[2] >= NMIN]
    have = {m for m, _, _ in ev}
    gaps, m = 0, st
    while m <= min(end, ev[-1][0]):
        if m not in have:
            gaps += 1
        m = nxt(m)
    return st, good, len(ev) - len(good), gaps


def main():
    doc = signaldoc()
    npred = check_class(doc)
    out = {'generated': '2026-09-28', 'note': '取得と整形だけ。ret は小数の総リターン（OSAP の % を 1/100）。成績の集計は入れていない',
           'sources': {}, 'signals': {}, 'signallag_check': {}}
    for key in ('SignalDoc', 'FF93style', 'QuintilesVW', 'VWforce'):
        b = D.fetch(key)
        out['sources'][key] = {'drive_id': D.FILES[key][0], 'cache': D.FILES[key][1], 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()}
        if key == 'SignalDoc':
            continue
        want = NEED[key]
        lagsum = {}
        for r in D.rows_of(key, b):
            s = r['signalname']
            if s not in want or not r['date'][:4].isdigit():
                continue
            ps = want[s]
            if ps is not None and r['port'] not in ps:
                continue
            ret = float(r['ret']) / 100.0 if r['ret'] not in ('', 'NA', 'NaN') else None
            n = int(float(r['Nlong'])) if r['Nlong'] not in ('', 'NA') else None
            m = D.ym(r['date'])
            out['signals'].setdefault(s, {}).setdefault(key, {}).setdefault(r['port'], []).append([m, ret, n])
            # 向きの確かめ（形）: FF93 の BH と BL の signallag（組の時価加重の平均の信号×符号）を月ごとに比べる
            if key == 'FF93style' and r['port'] in ('BH', 'BL') and r['signallag'] not in ('', 'NA', 'NaN'):
                lagsum.setdefault(s, {}).setdefault(m, {})[r['port']] = float(r['signallag'])
        for s, d in lagsum.items():
            both = [v for v in d.values() if 'BH' in v and 'BL' in v]
            out['signallag_check'][s] = {'months': len(both), 'share_BH_gt_BL': round(sum(1 for v in both if v['BH'] > v['BL']) / len(both), 4) if both else None}
        out['sources'][key]['missing_signals'] = sorted(set(want) - set(s for s in out['signals'] if key in out['signals'][s]))
    for v in out['signals'].values():
        for ports in v.values():
            for p in ports:
                ports[p].sort()
    # VWforce の良い側＝最大の番号（形で決める）
    top = {}
    for s, v in out['signals'].items():
        if 'VWforce' in v:
            top[s] = max(p for p in v['VWforce'] if p != 'LS')
    out['vwforce_top_port'] = top
    # 終わりの規則（BH）: 最後の6月の組＝Q5 の 05 に Y年7月のリターンがある最大の Y（信号の Y年6月の値がある）→ (Y+1)年6月まで
    shape = {}
    for rr in RULES + REPORT:
        if 'parts' in rr:
            continue
        s = rr['signal']
        port = top.get(s) if rr['port'] == 'TOP' else rr['port']
        rows = out['signals'].get(s, {}).get(rr['file'], {}).get(port)
        if not rows:
            shape[rr['id']] = {'error': 'データ無し'}
            continue
        last_ret = max(m for m, r, n in rows if r is not None)
        end = min(last_ret, LAST)
        rule_end = None
        if rr['file'] == 'FF93style':
            q = out['signals'].get(s, {}).get('QuintilesVW', {}).get('05', [])
            ys = [m // 100 for m, r, n in q if r is not None and m % 100 == 7]
            if ys:
                rule_end = (max(ys) + 1) * 100 + 6
                end = min(end, rule_end)
        st, good, drop, gaps = eval_window(rows, end)
        tr = [m for m, r, n in good if m <= C.TRAIN_END]
        ho = [m for m, r, n in good if m >= C.HOLD_START]
        nl = [n for m, r, n in good]
        shape[rr['id']] = {'file': rr['file'], 'port': port, 'raw_from': rows[0][0], 'raw_to': rows[-1][0], 'last_june_rule_end': rule_end,
                           'eval_from': st, 'eval_to': good[-1][0] if good else None, 'months': len(good), 'train_months': len(tr),
                           'train_years': round(len(tr) / 12, 1), 'hold_months': len(ho), 'dropped_after_start_nlong_lt20': drop, 'gaps': gaps,
                           'nlong_median': S.median(nl) if nl else None, 'nlong_min': min(nl) if nl else None,
                           'nlong_median_hold': S.median([n for m, r, n in good if m >= C.HOLD_START]) if ho else None}
    out['shape'] = shape
    out['class'] = CLASS
    out['jkp_cite_match'], out['sources']['JKP_Factor_Details'] = jkp_cite_match(doc)
    out['signaldoc'] = {s: {k: doc[s][k] for k in ('Authors', 'Year', 'Journal', 'Cat.Form', 'Cat.Data', 'Cat.Economic', 'Sign', 'Stock Weight',
                                                  'LS Quantile', 'Portfolio Period', 'Start Month', 'Filter', 'SampleStartYear', 'SampleEndYear',
                                                  'Return', 'T-Stat', 'Predictability in OP', 'Signal Rep Quality')}
                        for s in sorted(set(Z_IDS) | {k for k, v in CLASS.items() if v['status'].startswith('R_')})}
    for nm in ('F-F_Research_Data_Factors', 'Portfolios_Formed_on_ME', 'F-F_Research_Data_5_Factors_2x3', 'F-F_Momentum_Factor'):
        b = C.get(C.FR.format(nm), name=f'fr_{nm}.zip', max_age_days=60)
        out['sources'][f'French_{nm}'] = {'url': C.FR.format(nm), 'cache': f'fr_{nm}.zip', 'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()}
    out['extract_sha256'] = _sha(out['signals'])
    out['rules_sha256'] = rules_sha()
    out['class_sha256'] = class_sha()
    p = os.path.join(C.CACHE, 'nx_osap_zoo_ports.json')
    tmp = p + '.tmp'
    json.dump(out, open(tmp, 'w'), ensure_ascii=False)
    os.replace(tmp, p)

    # ── 形だけを表示（リターンの統計は出さない）──
    print('出力', p)
    print('予言変数', npred, '本・主の族 Z', len(Z_IDS), '本')
    print('extract_sha256', out['extract_sha256'])
    print('rules_sha256  ', out['rules_sha256'])
    print('class_sha256  ', out['class_sha256'])
    for key, v in out['sources'].items():
        print(f"{key:44s} bytes={v.get('bytes', '-')!s:>10s} sha256={v['sha256']} 欠け={v.get('missing_signals')}")
    print('\n規則 | 組 | 評価の開始〜終わり | 月数（訓練/保有） | 開始後に落ちる月 | 欠け | Nlong 中央（全/保有）・最小 | 向き（BH>BL の月の割合）')
    for rr in RULES + REPORT:
        if 'parts' in rr:
            print(f"{rr['id']:34s} 合成 {len(rr['parts'])} 脚・最低 {rr['min_legs']} 本")
            continue
        x = shape[rr['id']]
        if 'error' in x:
            print(rr['id'], x['error'])
            continue
        lc = out['signallag_check'].get(rr['signal'], {}).get('share_BH_gt_BL') if rr['file'] == 'FF93style' else ''
        print(f"{rr['id']:34s} {x['file']:11s} {x['port']:3s} {x['eval_from']}〜{x['eval_to']} | {x['months']}（{x['train_months']}={x['train_years']}年/{x['hold_months']}）"
              f" | {x['dropped_after_start_nlong_lt20']} | {x['gaps']} | {x['nlong_median']}/{x['nlong_median_hold']}・{x['nlong_min']} | {lc}")


def show_class():
    doc = signaldoc()
    n = check_class(doc)
    from collections import Counter
    print('予言変数', n, Counter(v['status'] for v in CLASS.values()))
    cm, _ = jkp_cite_match(doc)
    print('\n著者・年が JKP の cite と一致したもの（1段目）:', sum(1 for v in cm.values() if v), '本')
    for k in sorted(cm):
        if cm[k]:
            st = CLASS[k]['status']
            same = set(CLASS[k].get('jkp') or []) & set(cm[k])
            print(f"  {k:24s} {st:8s} cite一致 {','.join(cm[k])}" + ('' if st == 'X_JKP' and same else '   ← 定義の読みで' + ('別の量と判定' if st != 'X_JKP' else '別の JKP 特性と同じ量と判定')))
    print('\n著者・年は一致しないが定義の読みで JKP と同じ量と判定したもの（2段目）:')
    for k in sorted(CLASS):
        if CLASS[k]['status'] == 'X_JKP' and not cm.get(k):
            print(f"  {k:24s} → {','.join(CLASS[k]['jkp'])}")
    for st in ('Z', 'Z_near', 'R_train', 'R_thin', 'R_dup', 'X_SIB', 'X_Q07', 'X_OTHER', 'X_JKP'):
        ks = sorted(k for k, v in CLASS.items() if v['status'] == st)
        print(f'\n[{st}] {len(ks)}本')
        for k in ks:
            v = CLASS[k]
            print(f"  {k:26s} {doc[k]['Cat.Form'][:4]} {doc[k]['Authors'][:30]:30s} {doc[k]['Year']} | {('JKP ' + '・'.join(v['jkp']) + ' | ') if v.get('jkp') else ''}{v.get('reason', '')[:110]}")


if __name__ == '__main__':
    if '--class' in sys.argv:
        show_class()
    else:
        main()
