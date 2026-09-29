#!/usr/bin/env python3
"""night/edge/r9_japan_nisa.py — 第9回 B_japan_nisa（事前登録 out/edge_prereg_r9.json）

日本株を NISA で自分で持つ形（大型株だけ）で、日本の市場に勝てるかの確かめ。判定ではなく、確かな勝ち japan の『器』の検証。
読むだけ・門の採点に不使用。凍結した spec・fam_*.py は変えない。

■ 事前登録の規則（結果を見る前に固定）
  French Japan の 6 ポートフォリオ（2×3）の BIG のうち、割安（BIG HiBM）と、配当・益回り系が**ある場合は**それらを等分・毎月戻す。
  無い指標は使わない。→ 確かめた結果（2026-09-28）: French が公開している Japan の 6 ポートフォリオは
  ME_BE-ME / ME_OP / ME_INV / ME_Prior_12_2 の4つだけで、E-P・CF-P・D-P の大小別は 404（存在しない）。
  ⇒ 規則は **BIG HiBM（時価加重）1本**。OP・INV・Prior は割安・配当・益回り系ではないので入れない（参考として事後に並べるだけ）。
  相手 = French Japan の市場（h.french_region('Japan') の Mkt-RF＋RF・米ドル）。費用 0.25% × 回転 50%/年。配当は NISA で非課税
  （French の数字は配当込み・税前＝NISA ではそのまま手取り）。
■ 円建て: French の Japan 6 ポートフォリオと 3 因子には円のファイルが無い（ドルのみ）→ FRED DEXJPUS（各月の最後の営業日の値）で換算。
  相手の日本市場も同じ換算。米国市場（円）= h.us_market() を同じ換算。

使い方: EDGE_PHASE=holdout python3 night/edge/r9_japan_nisa.py
"""
import sys, os, json, math, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h

assert h.PHASE == 'holdout', 'EDGE_PHASE=holdout で走らせること（全期間を読む）'
OUT = os.path.join(h.BASE, 'out', 'edge', 'r9_japan_nisa.json')
COST, TURN = 0.0025, 0.5
PERIODS = {'2001〜': 200101, '2008〜': 200801, '2013〜': 201301, '2021〜': 202101}
SEL = ('選定期間 1990-07〜2000-12（参考）', 199007, 200012)


def vw(name, col):
    d = h.french(name)
    t = next(k for k in d if 'Value Weighted' in k and 'Monthly' in k)
    return {m: v / 100 for m, v in d[t][col].items() if 99999 < m < 1000000}


def nfirms(name, col):
    d = h.french(name)
    t = next((k for k in d if 'Number of Firms' in k), None)
    return {m: v for m, v in d[t][col].items() if 99999 < m < 1000000} if t else {}


def to_yen(r, fx):
    out = {}
    for m, x in r.items():
        p = h.add_months(m, -1)
        if m in fx and p in fx:
            out[m] = (1 + x) * (fx[m] / fx[p]) - 1
    return out


def block(ret, bench, rf, turn):
    o = {}
    last = max(set(ret) & set(bench))
    for k, a in PERIODS.items():
        o[k] = h.stats(ret, bench, rf, a=a, b=last, turnover=turn, cost=COST)
    o[SEL[0]] = h.stats(ret, bench, rf, a=SEL[1], b=SEL[2], turnover=turn, cost=COST)
    return o


def main():
    # 何が取れるか
    avail = {}
    for nm in ['Japan_6_Portfolios_ME_BE-ME', 'Japan_6_Portfolios_ME_E-P', 'Japan_6_Portfolios_ME_CF-P', 'Japan_6_Portfolios_ME_D-P',
               'Japan_6_Portfolios_ME_EP', 'Japan_6_Portfolios_ME_OP', 'Japan_6_Portfolios_ME_INV', 'Japan_6_Portfolios_ME_Prior_12_2']:
        try:
            h.french(nm); avail[nm] = '取れた'
        except Exception as e:
            avail[nm] = f'取れない（{type(e).__name__}: {str(e)[:40]}）'

    bm = vw('Japan_6_Portfolios_ME_BE-ME', 'BIG HiBM')
    rule = bm                                            # 等分する脚は1本だけ（事前登録どおり）
    turn = {m: TURN / 12 for m in rule}
    mkt, rf = h.french_region('Japan')
    usm, usrf = h.us_market()
    fx = h.fred('DEXJPUS')
    rule_y, mkt_y, us_y = to_yen(rule, fx), to_yen(mkt, fx), to_yen(usm, fx)
    last = max(set(rule) & set(mkt))

    res = {
        'key': 'r9_japan_nisa', 'asof': '2026-09-28', 'prereg': 'out/edge_prereg_r9.json の B_japan_nisa',
        'data_available': avail,
        'rule_as_run': 'French Japan 6 ポートフォリオ（Bloomberg 由来・6月末組成）の BIG HiBM（時価加重）1本。E-P・CF-P・D-P の大小別は French に無い＝使わない。'
                       '費用 0.25%×回転50%/年＝年0.125%を毎月引く。相手は French Japan 市場（費用ゼロ）。',
        'data_end': last,
        'usd_vs_japan_market': block(rule, mkt, rf, turn),
        'yen_vs_japan_market': block(rule_y, mkt_y, None, turn),
        'yen_rule_vs_us_market_yen': block(rule_y, us_y, None, turn),
        'yen_japan_market_vs_us_market_yen': block(mkt_y, us_y, None, None),
    }
    # BIG HiBM の社数（6月の組成時）
    nf = nfirms('Japan_6_Portfolios_ME_BE-ME', 'BIG HiBM')
    res['big_hibm_firms'] = {str(y): nf.get(y * 100 + 7) for y in (1991, 2000, 2007, 2008, 2013, 2021, 2025, 2026) if nf.get(y * 100 + 7) is not None}
    # 年ごとの超過（円・時期の偏り）
    yr = {}
    for y in range(2001, last // 100 + 1):
        ms = [m for m in rule_y if m // 100 == y and m in mkt_y]
        if len(ms) >= 6:
            a = math.prod(1 + rule_y[m] - TURN / 12 * COST for m in ms) - 1
            b = math.prod(1 + mkt_y[m] for m in ms) - 1
            yr[str(y)] = round((a - b) * 100, 2)
    res['yearly_excess_yen_pct'] = yr
    ex = [(float(v), k) for k, v in yr.items()]
    ex.sort()
    res['yearly_excess_note'] = f'正の年 {sum(v > 0 for v, _ in ex)}/{len(ex)}・最良 {ex[-1][1]} {ex[-1][0]}・最悪 {ex[0][1]} {ex[0][0]}'
    # 事後（事前登録の外・規則ではない）: 参考の BIG の脚
    post = {}
    for nm, col in [('Japan_6_Portfolios_ME_OP', 'BIG HiOP'), ('Japan_6_Portfolios_ME_INV', 'BIG LoINV'),
                    ('Japan_6_Portfolios_ME_Prior_12_2', 'BIG HiPRIOR')]:
        s = vw(nm, col)
        post[col] = {k: h.stats(s, mkt, rf, a=a, b=last, turnover={m: TURN / 12 for m in s}, cost=COST) for k, a in PERIODS.items()}
    res['事後_参考_規則ではない'] = {'説明': '事前登録の規則に入らない BIG の脚（割安・配当・益回り系ではない）。結果を見て規則に足さない', 'usd_vs_japan_market': post}
    # 為替換算の検算: French 国別 Japan の Local と Dollar の比から出る為替と DEXJPUS
    try:
        loc = h.french_countries('Local').get('Japan', {}); dol = h.french_countries('Dollar').get('Japan', {})
        diffs = []
        for m in dol:
            p = h.add_months(m, -1)
            if m in loc and m in fx and p in fx and m >= 200101:
                implied = (1 + loc[m]) / (1 + dol[m]) - 1
                diffs.append(implied - (fx[m] / fx[p] - 1))
        res['fx_check'] = {'説明': 'French 国別 Japan の 円/ドル の比から出る月次の為替 − DEXJPUS の月次変化（2001〜）',
                           'n': len(diffs), 'mean_pct': round(S.mean(diffs) * 100, 3), 'mad_pct': round(S.mean(abs(x) for x in diffs) * 100, 3)}
    except Exception as e:
        res['fx_check'] = f'取れない: {e}'

    # 実在の器（前の検証の数字をそのまま引用）
    try:
        v = json.load(open(os.path.join(h.BASE, 'out', 'edge', 'verify_japan_yen_etf.json')))
        c = v['tse_etfs']['composite_primary_equal_weight']
        res['real_vehicles_quoted'] = {
            '出典': 'out/edge/verify_japan_yen_etf.json（tse_etfs.composite_primary_equal_weight・再計算していない）',
            '東証の高配当ETF8本の等分_vs_1348(TOPIX)_2013-01〜2026-08': c.get('2013-2608'),
            '同_2013〜2020': c.get('2013-2020'), '同_2021〜2026-08': c.get('2021-2608'),
            '同_verdict': v.get('verdict'),
        }
    except Exception as e:
        res['real_vehicles_quoted'] = f'読めない: {e}'

    # 判定（事前登録は判定語を持たない＝統括の語彙で。線は他の系統と同じ: 費用後 +1%/年以上かつ t≥2 を『取れる形がある』）
    u = res['yen_vs_japan_market']['2001〜']
    later = [res['yen_vs_japan_market'][k] for k in ('2008〜', '2013〜', '2021〜')]
    if u and u['excess'] >= 1 and u['t'] >= 2 and all(x and x['excess'] > 0 for x in later):
        vd = '取れる形がある'
    elif u and u['excess'] > 0:
        vd = '弱い'
    else:
        vd = '取れない'
    res['verdict'] = vd
    res['verdict_rule'] = '円・日本市場相手の 2001〜 が 費用後 +1%/年以上 かつ t≥2、しかも 2008〜・2013〜・2021〜 の超過がすべて正 →『取れる形がある』／2001〜 の超過が正だが届かない →『弱い』／負 →『取れない』（線はこの担当が結果を見る前に置いた）'
    # 事後の注意（判定語は上の線どおり・動かさない。読み方の材料だけ足す）
    ex_y = {m: rule_y[m] - TURN / 12 * COST - mkt_y[m] for m in rule_y if m in mkt_y and 200101 <= m <= last}
    exu = {m: rule[m] - TURN / 12 * COST - mkt[m] for m in rule if m in mkt and 200101 <= m <= last}
    def tt(e, a, b):
        xs = [e[m] for m in sorted(e) if a <= m <= b]
        return {'ex_arith': round(S.mean(xs) * 1200, 2), 't': round(S.mean(xs) / (S.stdev(xs) / math.sqrt(len(xs))), 3), 'n': len(xs)}
    res['事後_読み方の注意'] = {
        't_unrounded_2001〜': {'円': tt(ex_y, 200101, last), 'ドル': tt(exu, 200101, last)},
        '2001-2020だけ（円）': tt(ex_y, 200101, 202012), '2021〜だけ（円）': tt(ex_y, 202101, last),
        '読み': '判定の線（円で t≥2）は t=2.003 で辛うじて越え、ドルでは t=1.93 で届かない＝境目。2001〜2020 の20年は +0.8%/年・t0.5 で、'
               '勝ちの大半は 2021年以降（日本の割安株の相場・2019〜2020 の −31pt の負けの後）から来る。実在の東証高配当ETFの等分は同じ区間で紙の半分以下',
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1)[:9000])


if __name__ == '__main__':
    main()
