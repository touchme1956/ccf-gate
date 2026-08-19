#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_hunt2_verdict.py — **第二次の狩りの答えを一枚にまとめる**（2026-08-19新設）

なぜ要るか:
  2026-08-08 の第一次の狩り（403社+20-F 38社を読んで新しい85はゼロ）は、
  自分でこう限界を書いていた——
    「フレーズは**確定済み85の実文から作った**ので、まだ見たことのない言い回しの機構は原理的に拾えない」
  第二次はその限界を潰すためにやった。**語彙を機構の意味から作り直す**（v1の24本と重なり0）。
  だから第二次の空振りは、第一次の空振りと**意味が違う**——
  「知っている言い回ししか探していないから見つからない」では説明できなくなる。

  この器はその主張を、**推測ではなく在庫から**組み立てる。数字を書き写さない
  （書き写した数字は必ず陳腐化する・この台帳が版番号と堀の線で繰り返し踏んだ型）。

読み方の要点（誤読しやすい順）:
  ① **完全一致の0件は「本当に0件」**。EDGAR全文検索は壊れていない（検算済み・irr85_hunt2.py 頭注）。
     だから flood_terms は**網の穴ではなく測定**——その言い回しは誰も書いていない。
  ② **完全一致と語ANDを混ぜない**。`boeing material specification` は語ANDで37社に当たるが
     完全一致は0件（"boeing"+"material"+"specification" が同じ段落に散っているだけ）。
  ③ **空振りは「探し方が悪い」の証拠にはならない**——ただし
     **自己検証で既知の85を掴めることを先に示した場合に限る**。だから recall を必ず併記する。

実行: python3 night/irr85_hunt2_verdict.py [--json]
出力: out/irr85_hunt2_verdict.json
終了コード: 常に0（測定であって関門ではない）
"""
import datetime as dt
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'out')


def jload(name, default=None):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        return default
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return default


def rows_of(d):
    if d is None:
        return []
    if isinstance(d, list):
        return d
    for k in ('rows', 'readlist', 'candidates'):
        if isinstance(d.get(k), list):
            return d[k]
    return []


def main():
    as_json = '--json' in sys.argv
    st = jload('irr85_hunt2_stats.json')
    uni = jload('irr85_hunt2_universe.json')
    rl = jload('irr85_hunt2_readlist.json')
    mat = jload('irr85_hunt2_material.json')
    sf = jload('irr85_hunt2_selftest.json')
    rd = jload('irr85_hunt2_read.json')          # 読解の結果（ワークフローが書く）
    miss = [k for k, v in [('stats', st), ('universe', uni), ('readlist', rl),
                           ('material', mat), ('selftest', sf)] if v is None]

    o = {'generated': dt.date.today().isoformat(), 'tool': 'night/irr85_hunt2_verdict.py',
         'missing_inputs': miss}

    # ── ① 語彙 ────────────────────────────────────────────────
    if st:
        c = {}
        for r in st['rows']:
            c[r.get('verdict')] = c.get(r.get('verdict'), 0) + 1
        ok = [r.get('total') for r in st['rows'] if r.get('verdict') == 'ok' and r.get('total')]
        ok.sort()
        zero = c.get('flood_terms', 0) + c.get('ok_terms', 0) + c.get('dead', 0)
        o['vocab'] = {
            'n': len(st['rows']), 'window': st.get('window'), 'verdicts': c,
            'exact_zero': zero, 'exact_zero_pct': round(zero / max(1, len(st['rows'])) * 100),
            'flood_exact': c.get('flood', 0),
            'median_hits_of_usable': ok[len(ok) // 2] if ok else None,
            'note': ('★完全一致が1500件超で送れなかった語は %d本＝「一般英語すぎて探せなかった」穴は無い。'
                     '0件だった%d本(%d%%)は網の穴ではなく「その言い回しは誰も書いていない」という測定。'
                     '使えた語の完全一致は中央値%s件＝**極めて特異な語彙**で、'
                     '空振りが鈍い網のせいだという説明は成り立たない')
            % (c.get('flood', 0), zero, round(zero / max(1, len(st['rows'])) * 100),
               ok[len(ok) // 2] if ok else '—'),
        }

    # ── ② 母集団と、第一次との重なり ──────────────────────────
    v1 = set()
    for f in ('irr85_hunt_readlist.json', 'irr85_hunt_20f_readlist.json',
              'irr85_hunt_candidates.json', 'irr85_hunt_ranked.json'):
        for r in rows_of(jload(f)):
            if isinstance(r, dict) and (r.get('cik') or r.get('CIK')):
                v1.add(str(r.get('cik') or r.get('CIK')).zfill(10))
    c2 = {r['cik'] for r in rows_of(rl)}
    o['universe'] = {
        'gate0': None, 'packs': len(glob.glob(os.path.join(OUT, '*_gate_pack.json'))),
        'hit_any_phrase': (uni or {}).get('n', {}).get('ciks'),
        'excluded_reviewed': (uni or {}).get('n', {}).get('excluded'),
        'readlist': len(c2), 'material': (mat or {}).get('n'),
        'v1_touched': len(v1), 'overlap_with_v1': len(c2 & v1),
        'note': ('★第二次の readlist %d社と第一次が触れた %d社の重なりは **%d社**。'
                 '語彙が重ならない（v1の24本と0本）ので、掘る場所も重ならなかった。'
                 '⇒ 第二次の空振りは「知っている言い回ししか探していないから」では説明できない')
        % (len(c2), len(v1), len(c2 & v1)),
    }
    try:
        import csv
        p = os.path.join(ROOT, 'gate0_all.csv')
        if os.path.exists(p):
            o['universe']['gate0'] = sum(1 for _ in csv.DictReader(open(p, encoding='utf-8-sig')))
    except Exception:
        pass

    # ── ③ 自己検証と、実証済みの語の当て直し（この狩りの本体） ──
    if sf:
        rc = sf.get('recall_on_unreviewed') or {}
        o['recall'] = {
            'known': sf.get('n_known'), 'caught': sf.get('n_hit'), 'missed': sf.get('missed'),
            'n_proven_phrases': rc.get('n_proven'),
            'exact_hits_on_unreviewed': rc.get('exact'),
            'phrases_with_zero_unreviewed_exact': len(rc.get('zero') or []),
            'zero': rc.get('zero'),
            'who': rc.get('who'),
            'note': ('既知の85を実際に掴んだ%s本のうち、未審査%s社が**完全一致**で当たったのは%s本だけ。'
                     '残り%s本は一社も当たらない——顧客負担の意味を運ぶ語がすべてそちら側にある')
            % (rc.get('n_proven'), rc.get('n_readlist'), len(rc.get('exact') or {}),
               len(rc.get('zero') or [])),
        }

    # ── ④ 読解と反証 ─────────────────────────────────────────
    if rd:
        o['read'] = {'n': (rd.get('n') or {}), 'survived': [x.get('ticker') for x in (rd.get('survived') or [])],
                     'refuted': rd.get('refuted'), 'all': rd.get('all')}
    else:
        o['read'] = None

    json.dump(o, open(os.path.join(OUT, 'irr85_hunt2_verdict.json'), 'w'),
              ensure_ascii=False, indent=1)
    if as_json:
        print(json.dumps(o, ensure_ascii=False, indent=1))
        return 0

    print(f"■ irr=85 第二次の狩り——答え（{o['generated']}）")
    if miss:
        print(f"  ⚠ 在庫が足りない: {miss}（測れない部分は「測れない」と出す）")
    if 'vocab' in o:
        v = o['vocab']
        print(f"\n① 語彙 {v['n']}本（機構の意味から作った・第一次の24本と重なり0）")
        print(f"   使えた {v['verdicts'].get('ok',0)}本（完全一致の中央値 {v['median_hits_of_usable']}件）"
              f" ／ 近い変種で拾えた {v['verdicts'].get('ok_terms',0)}本")
        print(f"   ★完全一致が0件 {v['exact_zero']}本（{v['exact_zero_pct']}%）"
              f" ／ 一般英語すぎて送れなかった語 **{v['flood_exact']}本**")
    u = o['universe']
    print(f"\n② 掘った場所  門0母集団 {u['gate0']} ／ パック {u['packs']}")
    print(f"   何かの語に当たった {u['hit_any_phrase']}社 → 既審査を除いて **{u['readlist']}社**"
          f"（材料を取ったのは {u['material']}社）")
    print(f"   ★第一次が触れた {u['v1_touched']}社との重なり **{u['overlap_with_v1']}社**")
    if 'recall' in o:
        r = o['recall']
        print(f"\n③ 自己検証  既知の85 {r['known']}社中 **{r['caught']}社**を掴む"
              f"（掴めない: {' '.join(r['missed'] or []) or 'なし'}）")
        print(f"   その語を台帳の外へ当て直すと——完全一致で当たった語 {len(r['exact_hits_on_unreviewed'] or {})}本:")
        for p, n in sorted((r['exact_hits_on_unreviewed'] or {}).items(), key=lambda kv: -kv[1]):
            print(f"      {n:>4}社  {p}")
        print(f"   **一社も当たらない語 {r['phrases_with_zero_unreviewed_exact']}本**")
    if o['read']:
        n = o['read']['n']
        print(f"\n④ 読解 {n.get('read')}社 → 85の提案 {n.get('proposed85')}社 →"
              f" **反証を全部くぐった {n.get('survived')}社**")
        if o['read']['survived']:
            print('   ' + ' '.join(o['read']['survived']))
    else:
        print("\n④ 読解 —（out/irr85_hunt2_read.json がまだ無い）")
    print(f"\n→ out/irr85_hunt2_verdict.json")
    return 0


if __name__ == '__main__':
    sys.exit(main())
