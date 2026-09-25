#!/usr/bin/env python3
"""night/shadow_structure_first.py — **影の計測: 構造を最優先にし、財務は利払カバー<3 だけで止める門**（2026-09-25・ユーザー「やって」）

読むだけ。index.html・台帳・四関門・席・配分には触れない（score_all は --out で scratch へ書くので正本も上書きしない）。
規則:
  並び   = night/structure_rank.py の順（irr 主・dom 従）
  止める = 利払カバー<3（実測のみ） ／ 財務以外のキル（ROIC≤WACC・複利停止・堀の減衰・期限型独占）／ 点検の要修正
  止めない = nde>4・債務超過・Altman Z・Ω・二本柱・門X・堀の関門70
  VRSK のような未完了の重大事象は「止める／止めない」の2案を並べる
キルの内訳は score_all を nde=0,eq=pos,z=5 で回し直して、財務の3本を外した残りを数える。
⚠ TDG の intcov はパックが空欄（純額の利息しか開示しない）。SEC XBRL の InterestIncomeExpenseNet から
  FY2025 営業利益 4,165 ÷ 純支払利息 1,572 百万$ = 2.65（総額の利息なら更に低い）を `EXTRA_IC` に置いた。
使い方: python3 night/shadow_structure_first.py   出力: out/shadow_structure_first.json
"""
import json, os, subprocess, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def L(p): return json.load(open(os.path.join(ROOT, p)))
SEATS = 5
EXTRA_IC = {'TDG': (2.65, 'SEC XBRL FY2025: OperatingIncomeLoss 4,165 ÷ InterestIncomeExpenseNet 1,572 百万$（純額・総額ならさらに低い）')}

def main():
    subprocess.run(['python3', 'night/structure_rank.py'], cwd=ROOT, check=True, capture_output=True)
    tmp = os.path.join(tempfile.mkdtemp(), 'nofin.json')
    subprocess.run(['node', 'night/score_all.js', '--set', 'nde=0,eq=pos,z=5', '--out', tmp],
                   cwd=ROOT, check=True, capture_output=True)
    nofin = {r['t']: r for r in json.load(open(tmp))}
    now = {r['t']: r for r in L('out/score_all.json')}
    cur = [r['t'] for r in L('out/score_all.json') if r.get('buy')]
    rows = []
    for x in L('out/structure_rank.json')['rows']:
        t = x['t']; pk = L(f'out/{t}_gate_pack.json')
        ic, ic_src = pk.get('intcov'), 'pack'
        if ic is None and t in EXTRA_IC: ic, ic_src = EXTRA_IC[t][0], EXTRA_IC[t][1]
        ic_kill = ic is not None and ic < 3
        other = nofin[t]['kills'] - (1 if ic_kill and pk.get('intcov') is not None else 0)
        why = []
        if ic_kill: why.append(f'利払カバー{ic:.2f}<3')
        if other > 0: why.append(f'財務以外のキル{other}')
        if not now[t].get('audOK', True): why.append('点検の要修正')
        rows.append(dict(t=t, rank=x['rank'], group=x['group'], irr=x['irr'], dom=x['dom'], intcov=ic, intcov_src=ic_src,
                         stop=why, pending=bool(now[t].get('pending')), omega=x['omega'], buy_now=t in cur))
    def seats(block_pending):
        ok = [r for r in rows if not r['stop'] and not (block_pending and r['pending'])]
        return [r['t'] for r in ok[:SEATS]]
    a, b = seats(False), seats(True)
    res = dict(generated=__import__('datetime').date.today().isoformat(), tool='night/shadow_structure_first.py',
               current=cur, structure_first=a, structure_first_block_pending=b,
               in_=[t for t in a if t not in cur], out=[t for t in cur if t not in a], rows=rows)
    json.dump(res, open(os.path.join(ROOT, 'out/shadow_structure_first.json'), 'w'), ensure_ascii=False, indent=1)
    print('現行の投下可     :', cur)
    print('構造優先（案A）  :', a, ' 入', res['in_'], '出', res['out'])
    print('構造優先＋未完了で止める（案B）:', b)
    for r in rows[:20]:
        print(f"{r['rank']:>3} {r['t']:<5} irr{r['irr']} dom{r['dom']} ic{r['intcov']} Ω{r['omega']}"
              f" {'止: '+'・'.join(r['stop']) if r['stop'] else '通'}{' (未完了の重大事象)' if r['pending'] else ''}")

if __name__ == '__main__':
    main()
