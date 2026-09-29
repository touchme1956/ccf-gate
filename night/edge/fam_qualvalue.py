#!/usr/bin/env python3
"""night/edge/fam_qualvalue.py — 系統 qualvalue（第2回）: 大型株の『割安 × 高収益 × 投資が控えめ』の組を買って持つ

素材は Ken French の3重の組（2x4x4: 規模を NYSE の中央値で2つ × 2つの特徴を NYSE の四分位で独立に4つずつ・毎年6月末に組み替え）と
5x5 の2重の組（全規模・時価加重＝事実上は大型株の組）。規則は「大型（Big）の決めた升目を持つ」だけ（升目の中は時価加重 or 等加重）。
升目どうしは前の月の時価総額（社数 × 平均時価総額）か社数でまとめる。米国の大型＝NYSE の時価総額の中央値より上／
国際版の大型＝その地域の時価総額の上位90%を占める会社（French の定義）。

  ■ 先読みの扱い
    ・升目の組入れは French が毎年6月末に、前の会計年度の簿価・営業利益・総資産の伸び（t−1年）と6月末の時価で決めている。
      月 m のリターンは m の月初に決まっている組入れの結果なので、月 m の規則のリターンに使う情報は m−1 月末までに揃っている。
    ・升目をまとめる重みは **m−1 月の**（社数 × 平均時価総額）。French の平均時価総額が月初か月末かに関わらず m−1 月末までに分かる。
    ・全期間の平均・百分位・標準化は一切使わない（prefix_check で確かめる）。
  ■ 費用: 回転1あたり 0.25%。回転は spec['turnover_yr']（毎月 turnover_yr/12）。事前登録の『会計の信号 50%/年』が下限で、
    升目の中を等加重にする規則は毎月 等しい重みへ戻す分（片道 約36%/年）が加わるので 100%/年 と保守的に置く。
  ■ spec: legs=[{file, size(2=大型), a=[段], b=[段], axes=[a の名, b の名]}]（脚どうしは毎月等分）／within='vw'|'ew'（升目の中の重み）／
          combine='cap'|'firms'|'equal'（升目どうしの重み・m−1 月の値）／turnover_yr／cost／replicate（国際版の同じ升目で再現を見るか）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h   # noqa: E402

FAMILY = {
    'key': 'qualvalue',
    'name': '大型株の割安×高収益×控えめな投資（French 3重の組）',
    'implement': ('楽天証券の米国ETF（成長投資枠・NISA対象かは各ETFの画面で確かめる）で「大型の割安×高収益を、少数の巨大株に偏らずに」持つ形へ寄せる。'
                  '楽天の取扱一覧（out/broker_lineup.json 2026-08-24）に在る近いもの: Global X US Cash Flow Kings 100（FLOW・0.25%・大中型からフリーCF利回りの高い100社）／'
                  'VanEck Morningstar Wide Moat（MOAT・0.46%・堀のある会社を割安な順に・ほぼ等分）／Global X S&P 500 Quality Dividend（QDIV・0.20%）／'
                  'Invesco S&P 500 Equal Weight（RSP・0.20%）と Vanguard Value（VTV・0.04%）の組合せ。COWZ・QUAL・VLUE・QVAL は一覧に無い。'
                  '年1回（7月）に見直す。⚠ どのETFも French の升目そのものではない（選び方の定義・重み・経費 0.04〜0.46%/年が違う）＝検定するのは升目の規則で、ETFの成績ではない'),
}

VW, EW = 'Average Value Weighted Returns -- Monthly', 'Average Equal Weighted Returns -- Monthly'
NF, CAP = 'Number of Firms in Portfolios', 'Average Market Cap'

# 米国のファイル名 → 国際版の接尾辞（同じ升目の定義）
INTL_NAME = {'32_Portfolios_ME_BEME_OP_2x4x4': '32_Portfolios_ME_BE-ME_OP_2x4x4',
             '32_Portfolios_ME_BEME_INV_2x4x4': '32_Portfolios_ME_BE-ME_INV(TA)_2x4x4',
             '32_Portfolios_ME_OP_INV_2x4x4': '32_Portfolios_ME_INV(TA)_OP_2x4x4'}   # 国際版の列の並びも 規模×OP×INV（ファイル名の順と違う・列名で確かめた）
# 5x5（全規模）には国際版が無い → 5x5 を使う規則は markets を持たない
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


def _level(tok, top):
    """'LoBM'→1 / 'HiOP'→top / 'BM3'→3 / 'INV2'→2"""
    if tok.startswith('Lo'):
        return tok[2:], 1
    if tok.startswith('Hi'):
        return tok[2:], top
    i = len(tok.rstrip('0123456789'))
    return tok[:i], int(tok[i:])


def _cells(cols, leg):
    """升目の列名を位置で選ぶ。2x4x4: 位置=(規模−1)*16+(a−1)*4+(b−1)／5x5: (a−1)*5+(b−1)。
    選んだ列名を読み直して、規模・a・b の段が意図どおりかを必ず確かめる（並びの取り違えを黙って通さない）"""
    n = len(cols)
    ax = leg.get('axes')
    out = []
    for a in leg['a']:
        for b in leg['b']:
            if n == 32:
                c = cols[(leg.get('size', 2) - 1) * 16 + (a - 1) * 4 + (b - 1)]
                tk = c.split()
                sz = 1 if tk[0] in ('SMALL', 'ME1') else 2 if tk[0] in ('BIG', 'ME2') else None
                (na, la), (nb, lb) = _level(tk[1], 4), _level(tk[2], 4)
                assert sz == leg.get('size', 2) and la == a and lb == b, (c, leg)
            elif n == 25:
                c = cols[(a - 1) * 5 + (b - 1)]
                tk = c.split()
                (na, la), (nb, lb) = _level(tk[0], 5), _level(tk[1], 5)
                assert la == a and lb == b, (c, leg)
            else:
                raise ValueError(f'列の数が想定外: {n}')
            if ax:
                assert (na, nb) == tuple(ax), (c, ax)
            out.append(c)
    return out


def leg_firms(d, leg):
    """脚の社数（升目の合計）{月: 社数}——少数の会社への賭けになっていないかを見る"""
    nf = _find(d, NF)
    sel = _cells(list(_find(d, VW)), leg)
    ms = sorted(set.union(*[set(nf[c]) for c in sel]))
    return {m: sum(nf[c].get(m, 0) for c in sel) for m in ms if m > 99999}


def leg_ret(d, leg, within='vw', combine='cap'):
    """一つの脚（升目の集合）の月次リターン（小数）。combine='cap' は m−1 月の時価総額で重みづけ、'firms' は m−1 月の社数、'equal' は升目を等分"""
    R = _find(d, VW if within == 'vw' else EW)
    cols = list(R)
    sel = _cells(cols, leg)
    nf = _find(d, NF) if combine in ('cap', 'firms') else None
    cap = _find(d, CAP) if combine == 'cap' else None
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
            if combine == 'cap':            # 升目の時価総額（m−1 月）＝升目をまとめた時価加重
                n_, cp = nf[c].get(pm), cap[c].get(pm)
                if n_ is None or cp is None:
                    continue
                w = n_ * cp
            elif combine == 'firms':        # 升目の社数（m−1 月）＝within='ew' と組めば、全升目の会社を1社ずつ等しく持つ
                w = nf[c].get(pm)
                if w is None:
                    continue
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
            r = rule_ret(spec, rg)          # 取れなければ落ちる（黙って再現の市場を減らすと、再現の条件を素通りさせる）
            if r is None:                   # 国際版の無い升目（5x5）だけは再現を持たない
                continue
            bm, rrf = h.french_region(rg)
            markets[rg] = {'ret': r, 'bench': bm, 'rf': rrf, 'turnover': _turn(r, spec), 'cost': cost}
    return {'ret': ret, 'bench': mkt, 'rf': rf, 'turnover': _turn(ret, spec), 'cost': cost, 'markets': markets}
