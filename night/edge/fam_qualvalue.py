#!/usr/bin/env python3
"""night/edge/fam_qualvalue.py — 系統 qualvalue（第2回）: 大型株の『割安 × 高収益 × 投資が控えめ』の組を買って持つ

素材は Ken French の3重の組（2x4x4: 規模を NYSE の中央値で2つ × 2つの特徴を NYSE の四分位で独立に4つずつ・毎年6月末に組み替え）と
5x5 の2重の組（全規模・時価加重＝事実上は大型株の組）。規則は「大型（Big）の決めた升目を時価加重でまとめて持つ」だけ。
升目どうしは前の月の時価総額（社数 × 平均時価総額）でまとめる（＝その升目を全部まとめた指数を持つのと同じ）。

  ■ 先読みの扱い
    ・升目の組入れは French が毎年6月末に、前の会計年度の簿価・営業利益・総資産の伸び（t−1年）と6月末の時価で決めている。
      月 m のリターンは m の月初に決まっている組入れの結果なので、月 m の規則のリターンに使う情報は m−1 月末までに揃っている。
    ・升目をまとめる重みは **m−1 月の**（社数 × 平均時価総額）。French の平均時価総額が月初か月末かに関わらず m−1 月末までに分かる。
    ・全期間の平均・百分位・標準化は一切使わない（prefix_check で確かめる）。
  ■ 費用: 回転は事前登録の『会計の信号 50%/年』＝毎月 0.5/12・回転1あたり 0.25%。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h   # noqa: E402

FAMILY = {
    'key': 'qualvalue',
    'name': '大型株の割安×高収益×控えめな投資（French 3重の組）',
    'implement': ('楽天証券の米国ETFで「大型・割安・高収益（質）」を同時に満たす指数を買って持つ。候補: Pacer US Cash Cows 100（COWZ・'
                  'ラッセル1000からフリーCF利回りの高い100社）・iShares MSCI USA Quality Factor（QUAL）と Value Factor（VLUE）の等分・'
                  'Distillate US Fundamental Stability & Value（DSTL）など。成長投資枠（NISA）で買える米国ETFが多い（各ETFの取扱と'
                  'NISA対象かは楽天の画面で確かめる）。年1回（7月）に見直し、指数側が組み替えるので持ち替えは基本的に不要。'
                  '⚠ ETFは French の升目そのものではない（選び方の定義・重み・費用 0.15〜0.40%/年 が違う）'),
}

VW, EW = 'Average Value Weighted Returns -- Monthly', 'Average Equal Weighted Returns -- Monthly'
NF, CAP = 'Number of Firms in Portfolios', 'Average Market Cap'

# 米国のファイル名 → 国際版の接尾辞（同じ升目の定義）
INTL_NAME = {'32_Portfolios_ME_BEME_OP_2x4x4': '32_Portfolios_ME_BE-ME_OP_2x4x4'}
REGIONS = ['Europe', 'Japan', 'Asia_Pacific_ex_Japan']          # 米国を含まない・互いに重ならない地域


def _find(d, key):
    """見出しの表記ゆれに耐える（国際版は 'Average Firm Size' 等の可能性）"""
    if key in d:
        return d[key]
    lk = key.lower()
    for t in d:
        tl = t.lower()
        if key == CAP and ('market cap' in tl or 'firm size' in tl):
            return d[t]
        if key == NF and 'number of firms' in tl:
            return d[t]
        if key in (VW, EW) and 'monthly' in tl and (('value weight' in tl) if key == VW else ('equal weight' in tl)):
            return d[t]
    raise KeyError(key)


def _cells(cols, leg):
    """升目の列名を位置で選ぶ。2x4x4: 位置=(規模−1)*16+(a−1)*4+(b−1)／5x5: (a−1)*5+(b−1)"""
    n = len(cols)
    out = []
    for a in leg['a']:
        for b in leg['b']:
            if n == 32:
                out.append(cols[(leg.get('size', 2) - 1) * 16 + (a - 1) * 4 + (b - 1)])
            elif n == 25:
                out.append(cols[(a - 1) * 5 + (b - 1)])
            else:
                raise ValueError(f'列の数が想定外: {n}')
    return out


def leg_ret(d, leg, within='vw', combine='cap'):
    """一つの脚（升目の集合）の月次リターン（小数）。combine='cap' は m−1 月の時価総額で重みづけ、'equal' は升目を等分"""
    R = _find(d, VW if within == 'vw' else EW)
    cols = list(R)
    sel = _cells(cols, leg)
    nf, cap = (_find(d, NF), _find(d, CAP)) if combine == 'cap' else (None, None)
    months = sorted(set.union(*[set(R[c]) for c in sel]))
    out = {}
    for m in months:
        if m < 99999:                     # 年次の行は除く
            continue
        pm = h.add_months(m, -1)
        num = den = 0.0
        for c in sel:
            r = R[c].get(m)
            if r is None:
                continue
            if combine == 'cap':
                n_, cp = nf[c].get(pm), cap[c].get(pm)
                if n_ is None or cp is None:
                    continue
                w = n_ * cp
            else:
                w = 1.0
            if w <= 0:
                continue
            num += w * r / 100
            den += w
        if den > 0:
            out[m] = num / den
    return out


def rule_ret(spec, region=None):
    """spec の脚をそれぞれ作り、脚どうしは等分（毎月）。region=None は米国"""
    legs = []
    for leg in spec['legs']:
        f = leg['file']
        if region:
            if f not in INTL_NAME:
                return None
            f = f'{region}_{INTL_NAME[f]}'
        d = h.french(f)
        legs.append(leg_ret(d, leg, spec.get('within', 'vw'), spec.get('combine', 'cap')))
    ms = sorted(set.intersection(*[set(x) for x in legs]))
    return {m: sum(x[m] for x in legs) / len(legs) for m in ms}


def _turn(ret, spec):
    t = spec.get('turnover_yr', 0.5) / 12
    return {m: t for m in ret}


def run(spec):
    cost = spec.get('cost', 0.0025)
    ret = rule_ret(spec)
    mkt, rf = h.us_market()
    markets = {}
    if spec.get('replicate', True):
        for rg in REGIONS:
            try:
                r = rule_ret(spec, rg)
            except Exception:
                r = None
            if not r:
                continue
            bm, rrf = h.french_region(rg)
            markets[rg] = {'ret': r, 'bench': bm, 'rf': rrf, 'turnover': _turn(r, spec), 'cost': cost}
    return {'ret': ret, 'bench': mkt, 'rf': rf, 'turnover': _turn(ret, spec), 'cost': cost, 'markets': markets}
