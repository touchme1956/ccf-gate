#!/usr/bin/env python3
"""night/structure_rank.py — **門を無視して「半導体型の構造」だけで並べる**（2026-09-25・ユーザー「門を無視して構造が強い銘柄でランキングつけて」）

読むだけ・判定を一つも持たない。Ω・キル・四関門・席・配分・売却規律には触れない。

物差しは原本から読んだ2軸だけ:
  主 irr（顧客側の乗り換えコスト）— 歴史で3ビンテージ再現した唯一の堀の欄（docs/CLAUDE_ARCHIVE.md:6006 / :12717 / :12898）
  従 dom（支配シェア）         — ⚠ 歴史では検定できていない（2018で91%が50＝変動が無く測れなかった）
群（上ほど強い）:
  1 irr=85 ／ 2 irr=70 ∧ dom≥85 ／ 3 irr=70 ∧ dom=70 ／ 4 irr=70 ∧ dom 空欄 ／ 5 irr=70 ∧ dom=50
  対象外: irr=100（規制独占。歴史では負の信号＝5度再現）／ irr=50 ／ irr 空欄
群の中は dom 85+ → 70 → 空欄 → 50 の順、同じなら門の堀の指数（表示用の並べ替え）。

意図して外したもの:
  - 層（chain_layers.json）は採点に使わない。AIの供給網を測るための物差しで、分類は88/372社しか無く、
    半導体と航空から手で選んだ『二重のつるはし』を点にすると上位がその2業種になるのは当然になる（自己循環）。
    参考として表示だけする。
  - 空欄を0点にしない（絶対のルール7）。dom 空欄は『弱い』ではなく『測れていない』として別の段に置く。
  - 点数の合計を作らない。検証済みの重みが無いので、群と並び順だけを出す。

使い方: python3 night/structure_rank.py [--json]   出力: out/structure_rank.json
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def L(p): return json.load(open(os.path.join(ROOT, p)))

def group(irr, dom):
    if irr == 85: return 1
    if irr == 70:
        if dom is None: return 4
        if dom >= 85: return 2
        if dom == 70: return 3
        return 5
    return None

DOMRANK = lambda d: 0 if (d or 0) >= 85 else 1 if d == 70 else 2 if d is None else 3
GNAME = {1: 'irr=85（顧客の工程認定・認証で乗り換えにくい）', 2: 'irr=70 ∧ 寡占(dom≥85)',
         3: 'irr=70 ∧ dom=70', 4: 'irr=70 ∧ dom 空欄', 5: 'irr=70 ∧ 競争的(dom=50)'}

def main():
    cl = L('night/chain_layers.json'); lay = cl['map']; deep = set(cl['deep'])
    rows, out_of = [], {'irr100': [], 'irr_blank': [], 'irr50': 0}
    for r in L('out/score_all.json'):
        t = r['t']; pk = L(f'out/{t}_gate_pack.json')
        irr, dom = pk.get('irr'), pk.get('dom')
        if irr == 100: out_of['irr100'].append(t); continue
        if irr is None: out_of['irr_blank'].append(t); continue
        g = group(irr, dom)
        if g is None: out_of['irr50'] += 1; continue
        nul = ((pk.get('_meta') or {}).get('nulls') or {}).get('dom')
        rows.append(dict(t=t, group=g, irr=irr, dom=dom,
                         dom_blank_why=(nul[:120] if isinstance(nul, str) else None),
                         layer_ref=('◎' if t in deep else lay.get(t)),
                         moat=r.get('moat'), omega=float(r['s']) if r.get('s') not in (None, '') else None,
                         buy=bool(r.get('buy')), kills=r.get('kills'), per=pk.get('per')))
    rows.sort(key=lambda x: (x['group'], DOMRANK(x['dom']), -(x['moat'] or 0)))
    for i, x in enumerate(rows, 1): x['rank'] = i
    res = dict(generated=__import__('datetime').date.today().isoformat(), tool='night/structure_rank.py',
               note='門の判定を使わない構造だけの並び。群と並び順のみで合計点は作らない。Ω・投下可は参考表示。',
               groups=GNAME, rows=rows, out_of_scope=out_of)
    json.dump(res, open(os.path.join(ROOT, 'out/structure_rank.json'), 'w'), ensure_ascii=False, indent=1)
    if '--json' in sys.argv: print(json.dumps(res, ensure_ascii=False, indent=1)); return
    g0 = None
    for x in rows:
        if x['group'] != g0:
            g0 = x['group']; print(f"\n== 群{g0}: {GNAME[g0]}")
        print(f"{x['rank']:>3} {x['t']:<6} irr{x['irr']} dom{x['dom'] if x['dom'] is not None else '空'}"
              f" 層:{x['layer_ref'] or '-'} 堀{x['moat']} Ω{x['omega']} {'🟢' if x['buy'] else ''} キル{x['kills']} PER{x['per']}")
    print(f"\n対象外: irr=100 {len(out_of['irr100'])}社 {out_of['irr100']} ／ irr空欄 {len(out_of['irr_blank'])}社 ／ irr=50 {out_of['irr50']}社")

if __name__ == '__main__':
    main()
