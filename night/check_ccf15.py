#!/usr/bin/env python3
"""night/check_ccf15.py — CCF15 の道具（night/ccf15.py）の部品を、作った数字で確かめる（ネット無し・キャッシュ無しで回る）

確かめること:
  - 順位（同点・向き）
  - 株数の変化（分割の補正・併合・説明できない大きさは測れない）
  - 有利子負債の読み方（代替と構成要素・タグが無ければ None）
  - ROIC（投下資本が自己資本の2割未満なら算出不能 → のれん込みへ落ちる）
  - 壊れないの検問（線の向き・測れないときは外す）
  - 浮動株の窓（10-K が出ていた値だけ）
  - かごの月次リターン（年1回の持ち替え・持ったまま／毎月同じ重み・欠けた月）
  - 毎月の積立の倍率
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ccf15 as C

ok = bad = 0


def check(name, cond, detail=''):
    global ok, bad
    if cond:
        ok += 1
    else:
        bad += 1
        print(f'✗ {name} {detail}')


def close(a, b, eps=1e-9):
    return a is not None and b is not None and abs(a - b) < eps


# 順位
r = C.pct({'a': 1, 'b': 2, 'c': 2, 'd': 3})
check('順位: 最小は0', close(r['a'], 0.0))
check('順位: 同点は平均', close(r['b'], r['c']) and close(r['b'], 0.5))
check('順位: 最大は1', close(r['d'], 1.0))
r2 = C.pct({'a': 1, 'b': 3}, higher=False)
check('順位: 小さいほど上', close(r2['a'], 1.0) and close(r2['b'], 0.0))

# 株数の変化
F = {1: {2020: {'sh': 100.0, 'sh_end': '2020-12-31', 'end': '2020-12-31'},
         2023: {'sh': 105.0, 'sh_end': '2023-12-31', 'end': '2023-12-31'}}}
check('株数: 分割なし', close(C.dilution(F, 1, 2023, [], 3), 0.05))
F[1][2023]['sh'] = 1030.0
check('株数: 10対1の分割を補正', close(C.dilution(F, 1, 2023, [[20220610, 10.0]], 3), 0.03, 1e-9))
F[1][2023]['sh'] = 10.2
check('株数: 1対10の併合を補正', close(C.dilution(F, 1, 2023, [[20220610, 0.1]], 3), 0.02, 1e-9))
F[1][2023]['sh'] = 30.0
check('株数: 分割の記録が無いのに0.3倍は測れない', C.dilution(F, 1, 2023, [], 3) is None)
F[1][2023]['sh'] = 102.0
check('株数: 分割があっても既に補正済みならそのまま', close(C.dilution(F, 1, 2023, [[20220610, 4.0]], 3), 0.02, 1e-9))
F[1][2023]['sh'] = 1000.0 * 1.9
check('株数: 分割で割っても±60%を超えたら測れない', C.dilution(F, 1, 2023, [[20220610, 10.0]], 3) is None)
check('株数: 古い年が無ければ測れない', C.dilution(F, 1, 2024, [], 3) is None)
F[1][2023]['sh'] = 98.0
check('株数: 窓より前の分割は使わない', close(C.dilution(F, 1, 2023, [[20190101, 2.0]], 3), -0.02, 1e-9))

# 有利子負債
check('負債: タグが無ければ None', C.debt_of({}) is None)
check('負債: 非流動＋流動', C.debt_of({'LongTermDebtNoncurrent': 100, 'DebtCurrent': 20}) == 120)
check('負債: 1年内返済＋短期借入', C.debt_of({'LongTermDebtNoncurrent': 100, 'LongTermDebtCurrent': 10, 'ShortTermBorrowings': 5}) == 115)
check('負債: LongTermDebt（総額）＋短期借入', C.debt_of({'LongTermDebt': 80, 'ShortTermBorrowings': 5}) == 85)
check('負債: 0 は値として扱う', C.debt_of({'LongTermDebtNoncurrent': 0}) == 0)

# ROIC
P = {9: {2024: {'OperatingIncomeLoss': 100.0, 'StockholdersEquity': 1000.0, 'LongTermDebtNoncurrent': 0.0,
                'Goodwill': 900.0, 'IntangibleAssetsNetExcludingGoodwill': 50.0, 'IncomeTaxExpenseBenefit': 20.0,
                'IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest': 100.0,
                'Assets': 2000.0, 'Liabilities': 1000.0}}}
f = C.features(P)[9][2024]
check('ROIC: 投下資本が自己資本の2割未満なら算出不能', f['roic'] is None)
check('ROIC: のれん込みへ落ちる', close(f['roic_used'], 100 * 0.8 / 1000 * 100))
P[9][2024]['Goodwill'] = 400.0
f = C.features(P)[9][2024]
check('ROIC: 門の式（NOPAT÷(自己資本＋負債−のれん−無形)）', close(f['roic'], 80 / 550 * 100))
P[9][2024]['StockholdersEquity'] = -50.0
f = C.features(P)[9][2024]
check('自己資本: 資産−負債が正なら符号の誤りとして直す', close(f['eq'], 1000.0) and f['eq_fix'])

# 壊れないの検問
R = {'kills': {'nde_max': 4, 'intcov_min': 3, 'z2_min': 1.1, 'wacc': 9.0, 'roic_years': 5, 'roic_min_years': 3}}
base = dict(oi=10, eq=100, nde=1.0, icov=10.0, z=3.0, roic_used=20.0)
FF = {5: {y: dict(base) for y in range(2020, 2025)}}
check('検問: 問題なし', C.kills(FF, 5, 2024, R) == [])
FF[5][2024]['nde'] = 4.5
check('検問: 純負債/EBITDA>4', any('EBITDA' in w for w in C.kills(FF, 5, 2024, R)))
FF[5][2024]['nde'] = 1.0
FF[5][2024]['icov'] = 2.0
check('検問: 利払いの余裕<3倍', any('利払い' in w for w in C.kills(FF, 5, 2024, R)))
FF[5][2024]['icov'] = None
check('検問: 利払いが無ければ発火しない', C.kills(FF, 5, 2024, R) == [])
for y in range(2020, 2025):
    FF[5][y]['roic_used'] = 8.0
check('検問: ROIC中央値≤WACC', any('ROIC中央値' in w for w in C.kills(FF, 5, 2024, R)))
for y in (2020, 2021, 2022):
    FF[5][y]['roic_used'] = None
for y in (2023, 2024):
    FF[5][y]['roic_used'] = 30.0
check('検問: ROICが3年分ないなら測れないで外す', any('測れない' in w for w in C.kills(FF, 5, 2024, R)))
FF[5][2024]['eq'] = -1
check('検問: 債務超過', any('債務超過' in w for w in C.kills(FF, 5, 2024, R)))
check('検問: 決算が無ければ外す', C.kills(FF, 5, 2019, R) == ['決算が無い（測れない）'])

# 浮動株の窓
FL = {1: {'2025-06-30': 5e9, '2024-06-30': 4e9}, 2: {'2025-12-31': 9e9, '2024-12-31': 3e9}, 3: {'2023-01-01': 1e10}}
ranked, cand = C.universe(FL, C.dt.date(2026, 6, 30), 10)
check('浮動株: 12か月前より新しい値は使わない（10-Kがまだ出ていない）', cand.get(2) == 3e9)
check('浮動株: 窓の中の最新', cand.get(1) == 5e9)
check('浮動株: 30か月より古い値は使わない', 3 not in cand)
check('浮動株: 大きい順', ranked == [1, 2])

# かごの月次リターン
class X:
    pass
ctx = X()
ctx.PX = {'A': {'m': {202306: 100.0, 202307: 110.0, 202308: 121.0}}, 'B': {'m': {202306: 100.0, 202307: 90.0, 202308: 90.0}}}
r, g = C.basket_returns(ctx, {2023: ['A', 'B']}, 202308, 'bh')
check('かご: 1か月目は平均', close(r[202307], 0.0))
check('かご: 持ったままなら重みが動く', close(r[202308], (0.55 * 0.10 + 0.45 * 0.0) / 1.0))
r, g = C.basket_returns(ctx, {2023: ['A', 'B']}, 202308, 'ew')
check('かご: 毎月同じ重み', close(r[202308], 0.05))
ctx.PX['B']['m'].pop(202307)
r, g = C.basket_returns(ctx, {2023: ['A', 'B']}, 202308, 'bh')
check('かご: 欠けた月は0%・次の月に最後の値から', close(r[202307], 0.05) and close(r[202308], (0.55 * 0.10 + 0.5 * (-0.10)) / 1.05) and g == 1)

# 毎月の積立
m = C.dca({202301: 0.0, 202302: 0.0, 202303: 0.0}, 3)
check('積立: 値動きなしなら1倍', len(m) == 1 and close(m[0], 1.0))
m = C.dca({202301: 1.0, 202302: 0.0}, 2)
check('積立: 最初の月の2倍は最初の1回だけに効く', close(m[0], 1.5))
check('月の足し算', C.ym_add(202312, 1) == 202401 and C.ym_add(202401, -1) == 202312)

# ── v2 の部品 ──
# 浮動株の単位の誤り
v, n = C.fix_float(4.0958e12, 3.0e9)
check('浮動株: 1000倍の誤りを直す', close(v, 4.0958e9, 1) and n == 1)
v, n = C.fix_float(4.429e15, 3.0e9)
check('浮動株: 100万倍の誤りを直す', close(v, 4.429e9, 1) and n == 2)
v, n = C.fix_float(2.7e12, 6.5e10)
check('浮動株: 正しい値（総資産の40倍）は触らない', close(v, 2.7e12, 1) and n == 0)
v, n = C.fix_float(4.0e6, 3.0e10)
check('浮動株: 1000分の1の誤りを直す', close(v, 4.0e9, 1) and n == -1)
check('浮動株: 総資産が無ければ測れない', C.fix_float(1e9, None)[0] is None)
v, n = C.fix_float(2.6e11, 2.2e9, classified=False)
check('浮動株: 銀行（流動資産を出さない）の1000倍の誤りを直す', close(v, 2.6e8, 1) and n == 1)
v, n = C.fix_float(1.5e11, 1.4e11, classified=False)
check('浮動株: 銀行でも時価が総資産並みなら触らない', close(v, 1.5e11, 1) and n == 0)
# 営業利益の代わりの道
oi, src = C.op_income_derived({'GrossProfit': 100.0, 'ResearchAndDevelopmentExpense': 20.0, 'SellingGeneralAndAdministrativeExpense': 30.0})
check('営業利益: 粗利−研究開発−販管費', close(oi, 50.0) and src == 'derived_gp')
oi, src = C.op_income_derived({'Revenues': 300.0, 'CostOfRevenue': 200.0, 'GeneralAndAdministrativeExpense': 10.0, 'SellingAndMarketingExpense': 15.0})
check('営業利益: 売上−原価で粗利・一般管理費＋販売費で販管費', close(oi, 75.0) and src == 'derived_gp')
oi, src = C.op_income_derived({'IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest': 80.0, 'InterestExpense': 5.0})
check('営業利益: 税引前＋支払利息', close(oi, 85.0) and src == 'derived_ebit')
check('営業利益: 何も無ければ測れない', C.op_income_derived({})[0] is None)
P2 = {7: {2024: {'OperatingIncomeLoss': 50.0, 'StockholdersEquity': 500.0, 'Assets': 800.0, 'Liabilities': 300.0,
                 'CashAndCashEquivalentsAtCarryingValue': 100.0, 'DepreciationDepletionAndAmortization': 10.0}}}
f2 = C.features(P2)[7][2024]
check('借金のタグも支払利息も無い会社は借金0と読む', f2['debt_src'] == 'none' and f2['roic'] is not None)
P2[7][2024]['InterestExpense'] = 20.0
f2 = C.features(P2)[7][2024]
check('利息を払っているのに借金のタグが無ければ測れない', f2['roic'] is None and f2['roicg'] is None)
# 1社の上限
w = C.cap_weights({'a': 50, 'b': 30, 'c': 10, 'd': 5, 'e': 5}, 0.3)
check('上限: 合計は1', close(sum(w.values()), 1.0, 1e-9))
check('上限: 30%を超えない', max(w.values()) <= 0.3 + 1e-9)
check('上限: 残りは比を保つ', close(w['c'] / w['d'], 2.0, 1e-9))
w = C.cap_weights({'a': 1, 'b': 1}, 0.3)
check('上限: 守れない社数なら掛けない', close(w['a'], 0.5))
# 金融の検問
RF = {'kills_fin': {'years': 5, 'min_years': 3, 'roe_min': 9.0}}
FF2 = {8: {y: {'ni': 12.0, 'eq': 100.0} for y in range(2020, 2025)}}
check('金融: ROE 12% は通る', C.fin_kills(FF2, 8, 2024, RF) == [])
FF2[8][2022]['ni'] = -1.0
check('金融: 前の年の赤字（Berkshire の2022年の評価損など）だけでは外さない', C.fin_kills(FF2, 8, 2024, RF) == [])
FF2[8][2024]['ni'] = -1.0
check('金融: 直近の年が赤字なら外す', any('赤字' in w for w in C.fin_kills(FF2, 8, 2024, RF)))
FF2[8][2024]['ni'] = 12.0
FF2[8][2022]['ni'] = 5.0
for y in (2020, 2021, 2023):
    FF2[8][y]['ni'] = 8.0
check('金融: ROE の中央値≤9%なら外す', any('ROE' in w for w in C.fin_kills(FF2, 8, 2024, RF)))
check('業種: 金融とテックの見分け', C.is_fin(6022) and not C.is_fin(7372) and C.is_tech(3674) and C.is_tech(7372) and not C.is_tech(2834))
# 重みつきのかご・入れ替えの売買の量
ctx2 = X()
ctx2.PX = {'A': {'m': {202306: 100.0, 202307: 110.0, 202406: 110.0, 202407: 110.0}}, 'B': {'m': {202306: 100.0, 202307: 100.0, 202406: 100.0, 202407: 100.0}}}
r, ends, g = C.basket_returns_w(ctx2, {2023: {'A': 0.75, 'B': 0.25}}, 202307)
check('重みつきのかご: 1か月目', close(r[202307], 0.075))
check('重みつきのかご: 年の終わりの重み', close(ends[2023]['A'], 0.825 / 1.075))
to = C.turnover({2023: {'A': 0.5, 'B': 0.5}, 2024: {'A': 0.5, 'B': 0.5}}, {2023: {'A': 0.6, 'B': 0.4}})
check('売買の量: 0.5×Σ|差|', close(to[2024], 0.1))

# 営業利益の三つ目の道（支払利息のタグも無い）
oi, src = C.op_income_derived({'IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest': 80.0})
check('営業利益: 支払利息のタグも無ければ税引前利益だけ（低く出る側）', close(oi, 80.0) and src == 'derived_pretax')
# 借金の無い会社: 負債合計のタグが無くても
P3 = {9: {2024: {'OperatingIncomeLoss': 50.0, 'StockholdersEquity': 500.0, 'Assets': 800.0}}}
check('借金のタグも利息も負債合計も無い会社も借金0と読む', C.features(P3)[9][2024]['debt_src'] == 'none')
# 純利益の代わりの道
check('純利益: NetIncomeLoss が無ければ普通株に帰属する純利益', close(C.features({1: {2024: {'NetIncomeLossAvailableToCommonStockholdersBasic': 7.0}}})[1][2024]['ni'], 7.0))
# 番号が変わった会社: タグごとに今の番号が先・無いタグは古い番号で埋める・古い番号は消す
old_s = dict(C.SUCCESSORS)
C.SUCCESSORS.clear()
C.SUCCESSORS.update({101: 202})
P4 = {101: {2020: {'Assets': 1.0, 'NetIncomeLoss': 5.0}, 2021: {'Assets': 2.0, 'NetIncomeLoss': 6.0}},
      202: {2021: {'Assets': 2.5}, 2022: {'Assets': 3.0}}}
C.merge_successors(P4)
check('番号の付け替え: 古い番号は消える', 101 not in P4)
check('番号の付け替え: 古い年は古い番号から', close(P4[202][2020]['NetIncomeLoss'], 5.0))
check('番号の付け替え: 同じ年は今の番号の値が先・無いタグは古い番号で', close(P4[202][2021]['Assets'], 2.5) and close(P4[202][2021]['NetIncomeLoss'], 6.0))
C.SUCCESSORS.clear()
C.SUCCESSORS.update(old_s)
# 6月末に出ていた決算の年（会計年度の終わりが4月1日より後の年は使わない）
FD = {1: {2025: {'end': '2025-12-31', 'oi': 1.0}},
      2: {2025: {'end': '2026-06-30', 'oi': 1.0}, 2024: {'end': '2025-06-30', 'oi': 1.0}},
      3: {2023: {'end': '2023-12-31', 'oi': 1.0}},
      4: {2025: {'end': '2026-03-31', 'ni': 1.0}}}
asof = C.dt.date(2026, 6, 30)
check('決算の年: 12月決算は前の暦年', C.decision_year(FD, 1, asof, 2026) == 2025)
check('決算の年: 6月決算は7月に出る年を使わない', C.decision_year(FD, 2, asof, 2026) == 2024)
check('決算の年: 2年より古ければ測れない', C.decision_year(FD, 3, asof, 2026) is None)
check('決算の年: 3月決算はその年', C.decision_year(FD, 4, asof, 2026) == 2025)
# 株数の基準の日（提出の年と会計年度の終わりの月から）
check('株数の基準: 9月決算・2024年の提出→2024年11月', C.sh_basis_date({'sh_accn': '0000320193-24-000123', 'sh_end': '2024-09-28'}) == C.dt.date(2024, 11, 27))
check('株数の基準: 12月決算・2025年の提出→2025年2月', C.sh_basis_date({'sh_accn': '0000000001-25-000001', 'sh_end': '2024-12-31'}) == C.dt.date(2025, 2, 26))
check('株数の基準: accn が無ければ分からない', C.sh_basis_date({'sh_end': '2024-12-31'}) is None)


# 時価の推定（浮動株×株価の変化 と 株数×株価 を突き合わせる）
class Y2:
    pass


def mvctx(fl, sh, splits=()):
    k = Y2()
    k.c2t = {5: 'Q'}
    k.PX = {'Q': {'m': {202306: 10.0, 202406: 10.0, 202506: 20.0, 202606: 40.0},
                  'c': {202306: 10.0, 202406: 10.0, 202506: 20.0, 202606: 40.0}, 'splits': list(splits)}}
    k.FL = {5: fl}
    k.F = {5: {2025: {'sh': sh, 'sh_accn': '0000000005-26-000001', 'sh_end': '2025-12-31', 'end': '2025-12-31', 'assets': 1e9, 'classified': True}}}
    return k


asof = C.dt.date(2026, 6, 30)
v, how = C.mv_value(mvctx({'2025-06-30': 1.8e9}, 1e8), 5, asof, 202606, 2025)
check('時価: ふつうは浮動株×株価の変化（配当で膨らまない終値の比）', close(v, 3.6e9, 1) and how == 'fl')
v, how = C.mv_value(mvctx({'2025-06-30': 7e9}, 1e8), 5, asof, 202606, 2025)
check('時価: 浮動株が全株の3.5倍なら届け出の誤り→株数×株価', close(v, 4e9, 1) and how == 'sh')
v, how = C.mv_value(mvctx({'2025-06-30': 1.8e9}, 1e5), 5, asof, 202606, 2025)
check('時価: 株数が1000分の1なら株数の側の誤り→浮動株', close(v, 3.6e9, 1) and how == 'fl')
v, how = C.mv_value(mvctx({'2025-06-30': 2e8}, 1e8), 5, asof, 202606, 2025)
check('時価: 浮動株が全株の1割（親会社が大半）→買える浮動株', close(v, 4e8, 1) and how == 'fl')
v, how = C.mv_value(mvctx({'2025-06-30': 1.8e9, '2024-06-30': 9e8, '2023-06-30': 9e9}, 1e8), 5, asof, 202606, 2025)
check('時価: 浮動株は最大3つの中央値（1つの誤りに引きずられない）', close(v, 3.6e9, 1))
v, how = C.mv_value(mvctx({}, 1e8, splits=[[20260301, 2.0]]), 5, asof, 202606, 2025)
check('時価: 株数の数字が出た後の分割は掛ける', close(v, 8e9, 1) and how == 'sh_only')
# 浮動株の株数が2,000億株を超える＝1000倍の届け出（Fannie Mae・Freddie Mac）
k = mvctx({}, 5.9e9)
k.PX['Q']['c'][201206] = k.PX['Q']['m'][201206] = 0.26
v, n = C.verify_float(k, 5, 301e9, '2012-06-30')
check('浮動株: 株数が2,000億株を超えれば1000で割る', close(v, 301e6, 1) and n == 1)

# ───────── v3: 質と勢いの線・30社・緩衝帯・運用の近似 ─────────
k = mvctx({}, 1e8)
k.PX['Q']['m'] = {202506: 20.0, 202605: 30.0, 202606: 40.0}
check('勢い: 12-1か月は最後の1か月を除く', close(C.momentum(k, 5, 202606, 12, 1), 0.5))
check('勢い: 6-1か月', C.momentum(k, 5, 202606, 6, 1) is None)
k.PX['Q']['m'][202512] = 25.0
check('勢い: 6-1か月（12月末→5月末）', close(C.momentum(k, 5, 202606, 6, 1), 0.2))
del k.PX['Q']['m'][202506]
check('勢い: 12か月前の値が無ければ測れない', C.momentum(k, 5, 202606, 12, 1) is None)
ts = C.top_set({'a': 1, 'b': 2, 'c': 3, 'd': 4}, 0.5)
check('線: 上位半分', ts == {'c', 'd'})
check('線: 上位2/3', C.top_set({'a': 1, 'b': 2, 'c': 3, 'd': 4}, 0.667) == {'b', 'c', 'd'})
check('線: 1以上は線なし', C.top_set({'a': 1}, 1.0) is None)
check('壊れた理由: 測れないだけは壊れたと読まない', C.substantive(['決算が無い（測れない）', 'ROICが3年分ない（測れない）']) == [] and
      C.substantive(['営業赤字', '自己資本が測れない']) == ['営業赤字'])
w = C.weights_v3(['a', 'b', 'c'], {'a': 4.0, 'b': 1.0, 'c': 1.0}, {'cap': 0.5})
check('重み: 時価の比で上限まで', close(w['a'], 0.5) and close(w['b'], 0.25))
w = C.weights_v3(['a', 'b'], {'a': 9.0, 'b': 1.0}, {'cap': 0.9, 'weighting': 'sqrt'})
check('重み: 時価の平方根', close(w['a'], 0.75))
w = C.weights_v3(['a', 'b'], {'a': 9.0, 'b': 1.0}, {'cap': 0.9, 'weighting': 'equal'})
check('重み: 同じ重み', close(w['a'], 0.5))


class FakeCtx:
    def need_sic(self, ciks, fetch):
        pass

    def px(self, t, fetch=False):
        return self.PX.get(t)


def v3ctx():
    k = FakeCtx()
    spec = {1: (600, 0.9, 0.5), 2: (500, 0.1, 0.4), 3: (400, 0.8, -0.1), 4: (300, 0.7, 0.3), 5: (200, 0.6, 0.2), 6: (100, 0.2, -0.2)}
    k.FL, k.c2t, k.SIC, k.PX, k.F, k.names = {}, {}, {}, {}, {}, {}
    for c, (mv, q, m) in spec.items():
        t = f'T{c}'
        k.FL[c] = {'2025-06-30': float(mv)}
        k.c2t[c] = t
        k.SIC[c] = 3674
        k.PX[t] = {'m': {202506: 100.0, 202605: 100.0 * (1 + m), 202606: 100.0 * (1 + m)},
                   'c': {202506: 10.0, 202605: 10.0, 202606: 10.0}, 'splits': []}
        k.F[c] = {y: {'oi': 10.0, 'eq': 100.0, 'nde': None, 'icov': None, 'z': None, 'roic_used': 20.0, 'gpa': q, 'cfoa': q,
                      'sh': None, 'end': f'{y}-12-31', 'assets': 1000.0, 'classified': True} for y in range(2021, 2026)}
    return k


RV3 = {'universe': {'float_top': 10, 'exclude_sic': [[6000, 6799, '金融']]},
       'kills': {'nde_max': 4, 'intcov_min': 3, 'z2_min': 1.1, 'wacc': 9.0, 'roic_years': 5, 'roic_min_years': 3},
       'quality': {'metrics': ['gpa', 'cfoa', 'dsh'], 'min_metrics': 2, 'dsh_years': 3, 'enter_top': 0.5, 'stay_top': 0.667},
       'momentum': {'months': 12, 'skip': 1, 'enter_top': 0.5, 'stay_top': 0.667},
       'select': {'n': 1, 'buffer_rank': 2, 'cap': 0.1}}
co = C.cohort_v3(v3ctx(), 2026, RV3)
check('v3: 入る線は質と勢いの両方', co['E1'] == [1, 4], str(co['E1']))
check('v3: 残る線は上位2/3', co['E2'] == {1, 4, 5}, str(co['E2']))
check('v3: 時価の大きい順に n 社', co['members'] == [1] and close(co['w'][1], 1.0))
co = C.cohort_v3(v3ctx(), 2026, RV3, prev=[5])
check('v3: 緩衝帯の外（入る線の内の社と並べて3位）なら残さない', co['members'] == [1])
R2 = C.variant(RV3, select__buffer_rank=3)
co = C.cohort_v3(v3ctx(), 2026, R2, prev=[5, 3])
check('v3: 緩衝帯の内なら残す・残る線の外（勢いが下）は残さない', co['members'] == [1, 5] and co['kept'] == [5])
co = C.cohort_v3(v3ctx(), 2026, RV3, prev_pool=[2])
check('v3: 比べる相手は検問・質・勢いなしの時価の上位（緩衝帯つき）', co['pmem'] == [1, 2])
co = C.cohort_v3(v3ctx(), 2026, C.variant(RV3, quality__enter_top=1.0, quality__stay_top=1.0))
check('v3: 質の線なし（感度）なら勢いだけ', co['E1'] == [1, 2, 4])
k = v3ctx()
k.SIC[1] = 6022
co = C.cohort_v3(k, 2026, RV3)
check('v3: 金融は持たない（土俵の外）', 1 not in co['pool'] and co['members'] == [4])
k = v3ctx()
del k.PX['T1']['m'][202506]
co = C.cohort_v3(k, 2026, RV3)
check('v3: 勢いが測れない社（上場1年未満）は入らない', 1 not in co['E1'] and co['members'] == [4])
k = v3ctx()
for y in range(2021, 2026):
    k.F[4][y]['oi'] = -1.0
co = C.cohort_v3(k, 2026, RV3)
check('v3: 検問に落ちた社は入らない・壊れた理由として残る', 4 not in co['elig'] and C.substantive(co['why'][4]) != [])

# 運用の近似（積立・壊れた社だけ売る・売却益の税・同じ年の通算）
at = {202307: {'A': 1.0}, 202308: {'A': 1.0}, 202407: {'B': 1.0}}
rets = {'A': {202307: 1.0}, 'B': {}}
o = C.dca_operational(None, at, {2024: {'A'}}, rets=rets)
check('運用: 壊れた社を売り、利益に税を引いて次の目標へ', close(o['taxes_paid_during'], C.TAX_JP, 1e-4) and o['sells_broken'] == 1
      and close(o['final'], 4.0 - C.TAX_JP, 1e-3))
check('運用: 最後に売る税はもう引いた分を数えない', close(o['final_tax'], 0.0, 1e-9))
at = {202307: {'A': 0.25, 'C': 0.75}, 202407: {'B': 1.0}}
rets = {'A': {202307: 1.0}, 'C': {202307: -1 / 3}, 'B': {}}
o = C.dca_operational(None, at, {2024: {'A', 'C'}}, rets=rets)
check('運用: 同じ年の損と通算（利益と損が同じなら税0・先に引いた分は戻る）', close(o['taxes_paid_during'], 0.0, 1e-9) and close(o['final'], 2.0, 1e-9))
at = {202307: {'A': 1.0}, 202308: {'B': 1.0}}
rets = {'A': {202307: 1.0}, 'B': {}}
o = C.dca_operational(None, at, {}, rets=rets)
check('運用: 目標から外れただけの社は売らない', o['names_held_end'] == 2 and close(o['final'], 3.0) and o['sells_broken'] == 0)
check('運用: 最後に売れば利益に税', close(o['after_tax'], 3.0 - C.TAX_JP * 1.0, 1e-3))
o = C.dca_plain({202301: 0.0, 202302: 0.0}, [202301, 202302])
check('積立: 値動きなしなら1倍・年率0', close(o['multiple'], 1.0) and o['irr'] == 0.0)
check('年率（お金の重みつき）: 月1%なら年12.68%', C.irr_m(12, sum(1.01 ** i for i in range(1, 13))) == 12.68)
yy = C.by_cohort_year({'A': {C.ym_add(202306, i): 0.01 for i in range(1, 13)}}, 202406)
row = [r for r in yy if r['組'] == 2023][0]
check('各年: 7月〜翌6月の複利・そろわない系列は書かない', close(row['A'], round((1.01 ** 12 - 1) * 100, 1)) and 'A' not in yy[0])

print(f'check_ccf15: {ok} 件 OK・{bad} 件 NG')
sys.exit(1 if bad else 0)
