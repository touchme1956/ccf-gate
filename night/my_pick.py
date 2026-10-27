#!/usr/bin/env python3
"""私（Claude）ならどうするかを検証する（my_pick・参考・判定なし・2026-10-26）

ユーザーの問い「あなたならどうするか検証して」。both_balance（書庫:20811）の弱点＝①6つに入れなかった『過去の実際の並び』で大きく負ける
②防衛45%の集中 ③個別株10%（MSFT・ASML を持っている＝売らない限り残る）を外した形、を直して選び直す。
★回す前に固定したこと（このファイルを結果の前にコミット）
  候補: 全体の形＝ETF 90%（QQQM・SMH・ITA・XLV・FBT・10%刻み→上位3つの周り5%刻み・各本±10）＋個別株10%（席の業種の写し）。
    1本（個別株の写しを足した後）40%まで。SHLD・VOO は外す（SHLD の100年の写しは ITA と同じ・VOO は both_balance で選ばれない）。
  点: 3つの側の百分位の順位の平均の「いちばん小さい側」を最大に——
    模型（unx_assets.measure・USD 崩れあり）: π加重の平均・P15π・最大下落／100年: 30年の中央値・30年の最悪・20年の下位10%点／
    実績: 過去の転がる20年の積立で年15%以上の割合。
  勧めの決まり: 1位が今の形を7つすべてで上回り、かつ円の枠（measure の円）でも平均と最大下落で上回るなら『変える』、そうでなければ『今のまま』。
  併せて出す: 上位5・今・案1 の円の枠と中身の集中（lookthrough・NVDA）。
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import both_balance as BB
BASE = BB.BASE
OUT = os.path.join(BASE, 'out', 'my_pick.json')
NET = ['QQQM', 'SMH', 'ITA', 'XLV', 'FBT']
KEYS = ('mean', 'p15', 'dd', 'c30m', 'c30w', 'c20p', 'past')
SIDES = (('模型', ('mean', 'p15', 'dd')), ('100年', ('c30m', 'c30w', 'c20p')), ('実績', ('past',)))


def grid90(step):
    BB.ASSETS[:] = NET
    for f in BB.grid(step):
        g = {k: v * 0.9 for k, v in f.items()}
        yield g


def main():
    import unx_assets as U
    import upside_check as UC
    import ndx_swap_check as N
    t0 = time.time()
    res = U.build(); rows, chains = res['rows'], res['chains']
    mega = U.mega_map(rows, sorted(set(NET) | {'VOO', 'SHLD'}))
    cc, _, _ = U.castle_copy()
    W = lambda f: {k: round(v, 4) for k, v in U.whole(f, cc).items()}
    cur = W({'QQQM': 40, 'SMH': 25, 'ITA': 10, 'SHLD': 5, 'XLV': 5, 'FBT': 5})
    an1 = W({'QQQM': 36, 'SMH': 27, 'ITA': 13.5, 'SHLD': 4.5, 'XLV': 4.5, 'FBT': 4.5})
    refs = {'今': cur, '案1（個別株10を残した形）': an1}
    ok = lambda f: max(f.values()) <= 40 + 1e-9
    st1 = {}
    for g in grid90(10):
        f = W(g)
        if ok(f):
            st1[BB.name(f)] = f
    ev = BB.evaluate({**st1, **refs}, U, UC, rows, chains, mega)
    import numpy as np
    vals = {k: np.array([ev[n][k] for n in st1]) for k in KEYS}
    pct = lambda k, x: float((vals[k] < x).mean() + 0.5 * (vals[k] == x).mean())

    def score(e):
        side = {s: float(np.mean([pct(k, e[k]) for k in ks])) for s, ks in SIDES}
        return min(side.values()), side
    for e in ev.values():
        e['score'], e['side'] = score(e)
    top3 = sorted(st1, key=lambda n: -ev[n]['score'])[:3]
    st2 = {}
    for n in top3:
        g0 = {k: v / 0.9 for k, v in ev[n]['form'].items()}
        for g in grid90(5):
            f = W(g)
            if ok(f) and all(abs(f.get(a, 0) - ev[n]['form'].get(a, 0)) <= 10 + 1e-9 for a in NET):
                st2[BB.name(f)] = f
    st2 = {k: v for k, v in st2.items() if k not in ev}
    ev.update(BB.evaluate(st2, U, UC, rows, chains, mega))
    for e in ev.values():
        e['score'], e['side'] = score(e)
    cand = [n for n in ev if n not in refs]
    best = sorted(cand, key=lambda n: -ev[n]['score'])[:5]
    # 円の枠
    ch_jpy, _ = U.jpy_chains(chains)
    show = {**{n: ev[n]['form'] for n in best}, **refs}
    tj = U.measure(show, rows, ch_jpy, mega=mega, windows={UC.W_CRASH: __import__('bestpf_check').WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
    for n in show:
        ev[n]['jpy'] = {k: tj[n][k] for k in ('π加重の平均の年率', 'P15π', '最大下落')}
        net = {k: v for k, v in show[n].items()}
        for k, v in cc.items():
            net[k] = net.get(k, 0) - v
        net = {k: round(v, 2) for k, v in net.items() if v > 1e-9}
        try:
            ev[n]['look'] = N.lookthrough(net)
        except Exception as x:
            ev[n]['look'] = {'失敗': str(x)}
    b, c = ev[best[0]], ev['今']
    all7 = all(b[k] >= c[k] for k in KEYS)
    jp = b['jpy']['π加重の平均の年率'] >= c['jpy']['π加重の平均の年率'] and b['jpy']['最大下落'] >= c['jpy']['最大下落']
    rnd = lambda e: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in e.items()}
    doc = dict(generated=time.strftime('%Y-%m-%d'), tool='night/my_pick.py', kind='参考・判定なし', 通り=len(cand),
               上位=[{'名前': n, **rnd(ev[n])} for n in best], 参考={n: rnd(ev[n]) for n in refs},
               勧め={'1位が今を7つすべてで上回る': all7, '円でも平均と最大下落で上回る': jp, '決まりの答え': '変える' if (all7 and jp) else '今のまま'},
               秒=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    U.log('完了', doc['秒'], '秒', doc['勧め'])


if __name__ == '__main__':
    main()
