#!/usr/bin/env python3
"""私が選ぶ最終（final_pick_check・参考・判定なし・2026-10-27）——both_balance.evaluate と同じ物差しで4つの形を並べる。読むだけ。"""
import sys, json
sys.path.insert(0, '/home/user/ccf-gate/night')
import unx_assets as U, upside_check as UC, both_balance as BB, ndx_swap_check as N
res = U.build(); rows, chains = res['rows'], res['chains']
mega = U.mega_map(rows, ['QQQM','SMH','ITA','SHLD','XLV','FBT','VOO'])
cc, _, _ = U.castle_copy()
E = {'今 40/25/10/5/5/5': {'QQQM':40,'SMH':25,'ITA':10,'SHLD':5,'XLV':5,'FBT':5},
     'B 35/25/15/5/5/5': {'QQQM':35,'SMH':25,'ITA':15,'SHLD':5,'XLV':5,'FBT':5},
     'C 35/30/10/5/5/5': {'QQQM':35,'SMH':30,'ITA':10,'SHLD':5,'XLV':5,'FBT':5},
     'D 案1縮小 36/27/13.5/4.5x3': {'QQQM':36,'SMH':27,'ITA':13.5,'SHLD':4.5,'XLV':4.5,'FBT':4.5}}
F = {k: {a: round(w, 4) for a, w in U.whole(v, cc).items()} for k, v in E.items()}
ev = BB.evaluate(F, U, UC, rows, chains, mega)
ch_jpy, _ = U.jpy_chains(chains)
tj = U.measure(F, rows, ch_jpy, mega=mega, windows={UC.W_CRASH: __import__('bestpf_check').WINDOWS[UC.W_CRASH]})[UC.W_CRASH]
for k in E:
    e = ev[k]; net = {a: v for a, v in E[k].items()}
    look = N.lookthrough(net)
    print(k, f"平均{e['mean']:.2f} P15 {e['p15']:.1f} DD{e['dd']:.1f} 過去{e['past']} | 30m{e['c30m']:.3f} 30w{e['c30w']:.3f} 20p{e['c20p']:.3f} 勝30 {e['c30beat']} 勝20 {e['c20beat']} | 円 {tj[k]['π加重の平均の年率']} {tj[k]['最大下落']} | NVDA {look.get('NVDA（資産全体）')}")
