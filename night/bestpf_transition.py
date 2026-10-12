#!/usr/bin/env python3
"""night/bestpf_transition.py — 今の保有から、売らずに新しい配分へ近づくのに何か月かかるか（2026-10-12・ユーザー「NDX20/SMH50/ITA20/XLE10 これに個別枠10％を入れるなら？」）

読むだけ。門・配分には触れない（portfolio.json は書き換えない）。
門の割り方 cat（index.html の ccfCatBudget）を円のまま写した: 毎月の入金を区分の不足 max(0, 目標%×(総資産＋自動の積立＋入金) − 今の円) の比で割り、
不足の合計が入金より小さい月は不足を埋めた残りを目標比で。自動の積立（iDeCo・こどもNISA＝NASDAQ100 の区分）は先に買ったものとして数える
（その区分の取り分を超える月は、その区分は自動の積立だけ）。1株単位の丸めはしない（円のまま）。値段・為替は一定・売らない・配当は無視。
保有は state.json（2026-09-23 の株数）× out/dashboard.json の値段（npx）× ドル円。
入金: 2026-10〜12 は月17万円（自動の積立なし）・2027-01 から月20万円（うち自動の積立 3.5万円＝こどもNISA 3万＋iDeCo 5千〔A〕が NASDAQ100）。
XLK（目標0%）の数え方は2通り: 「その他」として ITA の区分に数える（今の門の ami_other と同じ）／どの区分にも数えない。
出力: out/bestpf_transition.json
"""
import datetime, json, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'out', 'bestpf_transition.json')

BUCKET_OF = {'QQQM': 'NDX', 'IFREE-NDX': 'NDX', 'SMH': 'SMH', 'ITA': 'ITA', 'XLE': 'XLE', 'MSFT': '個別', 'ASML': '個別'}
PLANS = {
    '新 NDX18/SMH45/ITA18/XLE9/個別10': {'NDX': 18, 'SMH': 45, 'ITA': 18, 'XLE': 9, '個別': 10},
    '新 NDX17/SMH42.5/ITA17/XLE8.5/個別15': {'NDX': 17, 'SMH': 42.5, 'ITA': 17, 'XLE': 8.5, '個別': 15},
    '今 NDX50/SMH20/その他15(ITA)/個別15': {'NDX': 50, 'SMH': 20, 'ITA': 15, 'XLE': 0, '個別': 15},
}


def holdings():
    st = json.load(open(os.path.join(BASE, 'state.json')))['data']
    pf = st['pf:portfolio']
    pf = json.loads(pf) if isinstance(pf, str) else pf
    db = json.load(open(os.path.join(BASE, 'out', 'dashboard.json')))
    fx = float(db['fx']['USDJPY'])
    out = {}
    for r in pf['positions']:
        px = float(r.get('npx') or 0)
        jpy = r['sh'] * px * (fx if r.get('ccy', 'USD') == 'USD' else 1)
        out[r['t']] = jpy
    return out, fx, pf['asof']


def split(o, keys, amt):
    r = {}
    sn = sum(o[k]['need'] for k in keys); st = sum(o[k]['t'] for k in keys)
    if amt <= 0:
        return {k: 0.0 for k in keys}
    if sn >= amt and sn > 0:
        for k in keys:
            r[k] = amt * o[k]['need'] / sn
    else:
        for k in keys:
            r[k] = o[k]['need'] + ((amt - sn) * o[k]['t'] / st if st > 0 else 0)
    return r


def cat_budget(cur, tot, targets, T, pre):
    """ccfCatBudget の写し（円は小数のまま）。cur＝区分ごとの今の円・tot＝総資産・pre＝{区分: 自動の積立の円}"""
    ks = [k for k, t in targets.items() if t > 0]
    P = sum(pre.get(k, 0) for k in ks)
    base = tot + P + T
    o = {k: dict(t=targets[k], need=max(0.0, targets[k] * base / 100 - cur.get(k, 0)), b=0.0) for k in ks}
    if P <= 0:
        r = split(o, ks, T)
        for k in ks:
            o[k]['b'] = r[k]
        return {k: o[k]['b'] for k in ks}
    act = ks[:]
    for _ in range(len(ks) + 1):
        Pa = sum(pre.get(k, 0) for k in act)
        allr = split(o, act, T + Pa)
        over = [k for k in act if pre.get(k, 0) > 0 and allr[k] < pre[k]]
        if not over:
            for k in act:
                o[k]['b'] = allr[k] - pre.get(k, 0)
            break
        act = [k for k in act if k not in over]
    return {k: o[k]['b'] for k in ks}


def simulate(h0, targets, xlk_into_ita, months=120):
    cur = {}
    other = 0.0
    for t, j in h0.items():
        b = BUCKET_OF.get(t)
        if t == 'XLK':
            if xlk_into_ita:
                cur['ITA'] = cur.get('ITA', 0) + j
            else:
                other += j
            continue
        cur[b] = cur.get(b, 0) + j
    first_buy, path = {}, []
    y, m = 2026, 10
    for i in range(months):
        ym = y * 100 + m
        if ym < 202701:
            T, pre = 170000, {}
        else:
            T, pre = 165000, {'NDX': 35000}
        tot = sum(cur.values()) + other
        b = cat_budget(cur, tot, targets, T, pre)
        for k, v in b.items():
            if v > 0.5 and k not in first_buy:
                first_buy[k] = dict(month_index=i + 1, ym=f'{y}-{m:02d}')
            cur[k] = cur.get(k, 0) + v
        for k, v in pre.items():
            cur[k] = cur.get(k, 0) + v
        tot = sum(cur.values()) + other
        share = {k: round(100 * cur.get(k, 0) / tot, 1) for k in targets}
        if other:
            share['XLK(区分の外)'] = round(100 * other / tot, 1)
        path.append(dict(ym=f'{y}-{m:02d}', total=round(tot), share=share))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    within = next((p['ym'] for p in path if all(abs(p['share'][k] - t) <= 2 for k, t in targets.items() if t > 0)), None)
    return dict(first_new_money=first_buy, within_2pt_of_target=within,
                at={p['ym']: p['share'] for p in path if p['ym'] in ('2026-12', '2027-09', '2028-09', '2029-09', '2031-09', '2036-09')})


def main():
    h0, fx, asof = holdings()
    tot0 = sum(h0.values())
    now = {}
    for t, j in h0.items():
        k = 'XLK' if t == 'XLK' else BUCKET_OF[t]
        now[k] = now.get(k, 0) + j
    print('今の保有（円）', {k: round(v) for k, v in now.items()}, '総資産', round(tot0), '比', {k: round(100 * v / tot0, 1) for k, v in now.items()})
    res = {}
    for pn, tg in PLANS.items():
        for xi in (True, False):
            key = f'{pn}｜XLK を{"その他（ITA の区分）に数える" if xi else "区分の外に置く"}'
            r = simulate(h0, tg, xi)
            res[key] = r
            print('==', key)
            print('   初めて新しいお金が入る月', {k: v['ym'] for k, v in r['first_new_money'].items()}, '／全区分が目標±2pt', r['within_2pt_of_target'])
            for ym, sh in r['at'].items():
                print('  ', ym, sh)
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/bestpf_transition.py', posthoc=True,
               holdings_asof=asof, usdjpy=fx, holdings_jpy={k: round(v) for k, v in h0.items()}, total_jpy=round(tot0),
               plans=PLANS, results=res,
               note='門の ccfCatBudget を円のまま写した（1株の丸めなし）・値段一定・売らない・配当なし。portfolio.json は書き換えていない')
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT)


if __name__ == '__main__':
    main()
