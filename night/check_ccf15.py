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
import math
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

print(f'check_ccf15: {ok} 件 OK・{bad} 件 NG')
sys.exit(1 if bad else 0)
