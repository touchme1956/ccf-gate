#!/usr/bin/env python3
"""night/edge/confirm_r10.py — 「市場に勝てる規則の探索」第10回（確認）: 国の中の割安と収益性をフロンティアの国で確かめる（事前登録 out/edge_prereg_r10.json の confirmations_r10）

  C15_value_frontier  confirm_em.c1_country をそのまま呼ぶ（be_me・ni_me・ocf_me/fcf_me・div12m_me の三分位3・vw を等分・20社未満の脚は市場で代える）
  C16_profit_frontier fam_profit.build(spec_profit, 国, rf, 20) をそのまま呼ぶ（confirm_r7.py と同じ写し方）
  国 = fam_frontier.frontier_countries()（先進国22・新興国24のどちらにも入らない JKP の国）。国の相手はその国の JKP mkt（vw）＋米国 rf、
  費用 回転1あたり 0.5%。判定は 2001-01〜。2本の中で Holm。
  出力: out/edge/confirm_r10.json
"""
import os, sys, json, math, importlib, datetime
os.environ['EDGE_PHASE'] = 'holdout'
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as h                     # noqa: E402
import confirm_em as CE                 # noqa: E402
import fam_frontier as FF               # noqa: E402
from evaluate import committed          # noqa: E402

assert h.PHASE == 'holdout'
OUT = os.path.join(h.BASE, 'out', 'edge', 'confirm_r10.json')
T_MIN, SHARE_MIN, ALPHA = 2.0, 0.6, 0.05


def profit_country(c, rf, spec, mod):
    bench, _ = CE.mkt_total(c, rf)
    if not bench:
        return None
    try:
        r, t = mod.build(spec, c, rf, 20)
    except Exception:
        return None
    r = {m: v for m, v in r.items() if m in bench}
    if not r:
        return None
    return {'ret': r, 'bench': {m: bench[m] for m in r}, 'rf': rf, 'turnover': {m: t.get(m, 0.0) for m in r}, 'cost': CE.COST_EM,
            'info': {'months_counted_since2001': sum(1 for m in r if m >= h.HOLD_START)}}


def main():
    for p in ('out/edge/spec_profit.json', 'night/edge/fam_profit.py', 'out/edge/spec_intl_value.json'):
        sha, clean = committed(p)
        assert sha and clean, p
    _, rf = h.us_market()
    cs = FF.frontier_countries()
    spec_p = json.load(open(os.path.join(h.BASE, 'out', 'edge', 'spec_profit.json')))['spec']
    modp = importlib.import_module('fam_profit')
    C15, C16 = {}, {}
    for c in cs:
        x = CE.safe(CE.c1_country, c, rf)
        if x and x['ret']:
            C15[c] = x
        y = profit_country(c, rf, spec_p, modp)
        if y:
            C16[c] = y
    res = {'C15_value_frontier': CE.summarize(C15, 'C15: 国の中の割安・高配当をフロンティアの国へ'),
           'C16_profit_frontier': CE.summarize(C16, 'C16: 収益性（cop_at の三分位3・vw_cap）をフロンティアの国へ')}
    ps = {k: h.pnorm_upper(v['pooled_t']) for k, v in res.items()}
    hm = CE.holm(ps)
    for k, v in res.items():
        c1 = v['pooled_t'] is not None and v['pooled_t'] >= T_MIN and (v['pooled_excess'] or 0) > 0
        c2 = (v['positive_share'] or 0) >= SHARE_MIN
        v['holm'] = hm[k]
        v['criteria'] = {'ならした超過が正で t≥2': c1, '6割以上の国で正': c2, 'Holm（2本の中）': hm[k]['pass']}
        v['verdict'] = '再現した' if (c1 and c2 and hm[k]['pass']) else '再現しなかった'
    out = {'title': '第10回の確認（凍結した規則をフロンティアの国へ）', 'prereg': 'out/edge_prereg_r10.json', 'generated': datetime.date.today().isoformat(),
           'countries': cs, 'tests': res}
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    for k, v in res.items():
        print(k, v['verdict'], '国', v['countries_run'], '判定', v['countries_rated'], '正', v['positive'], 'ならし', v['pooled_excess'], 't', v['pooled_t'],
              '半分', v['subperiods_info'], 'Holm', v['holm'])


if __name__ == '__main__':
    main()
