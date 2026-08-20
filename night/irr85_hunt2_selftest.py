#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_hunt2_selftest.py — **未知へ当てる前に、既知の85を取り戻せるか測る**（2026-08-19新設）

第一次の狩り(2026-08-08)は「確定済みの irr=85 を12社そのまま再発見することを先に確認してから
未知へ当てた」。第二次も同じ順序を踏む——**既知の正解を漏らす網で未知を探しても意味が無い**。

測るもの:
  ・台帳の irr=85 の15社のうち、新しい語彙のスクリーンが何社を掴んだか（再現率）
  ・掴んだ社が、除外しなければ読む順の何位に来たか（順位の妥当性）
  ・掴めなかった社は**名指しで出す**（黙って落とさない）——その社の機構語が語彙に無いということ

⚠ これは合否ではなく**網の較正**。判定は原本を読む審査官の仕事（絶対のルール2）。

実行: python3 night/irr85_hunt2_selftest.py
"""
import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'out')


def main():
    sa = json.load(open(os.path.join(OUT, 'score_all.json'), encoding='utf-8'))
    rows = sa if isinstance(sa, list) else sa['rows']
    known = sorted({str(r.get('t', '')).strip().split()[0].upper()
                    for r in rows if str(r.get('irr')) == '85'})
    u = json.load(open(os.path.join(OUT, 'irr85_hunt2_universe.json'), encoding='utf-8'))
    by_t = {}
    for r in u['rows']:
        t = (r.get('ticker') or '').upper()
        if t:
            by_t[t] = r
    # ★順位は cmd_rank が作った readlist をそのまま読む（式を書き写さない・v9.9.65）。
    #   既知の85は readlist からは除外されているので、**除外前の全社**で同じ式を当て直す必要がある。
    #   その式は night/irr85_hunt2.py の単一実装を import して使う。
    import importlib.util as _iu
    _sp = _iu.spec_from_file_location('_h2', os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                          'irr85_hunt2.py'))
    h2 = _iu.module_from_spec(_sp)
    _sp.loader.exec_module(h2)
    spread = h2.sic_spread(u['rows'])

    def sc(r):
        md = r.get('mode') or {}
        w = {'customer_bears': 5.0, 'lock_evidence': 2.0, 'neutral': 0.5}
        tot = 0.0
        for k, wt in w.items():
            for p in h2.collapse(r.get(k) or []):
                v = wt if md.get(p, 'phrase') == 'phrase' else 0.3
                if (spread.get(p) or {}).get('generic'):
                    v *= 0.15
                tot += v
        return tot
    ranked = sorted(u['rows'], key=lambda r: -sc(r))
    pos = {(r.get('ticker') or '').upper(): i + 1 for i, r in enumerate(ranked)}

    hit, missed = [], []
    for t in known:
        r = by_t.get(t)
        if r:
            hit.append((t, pos.get(t), sc(r), r['customer_bears'][:3], r['lock_evidence'][:2]))
        else:
            missed.append(t)
    print(f"台帳の irr=85 は {len(known)}社。新しい語彙が掴んだのは **{len(hit)}社** "
          f"（{len(hit) / max(1, len(known)) * 100:.0f}%）\n")
    print(f"{'T':7}{'順位':>6}{'点':>7}  当たった語（顧客負担 / 固着）")
    for t, p, s, cb, le in sorted(hit, key=lambda x: (x[1] or 99999)):
        print(f"{t:7}{str(p):>6}{s:7.1f}  {', '.join(cb) or '—'} / {', '.join(le) or '—'}")
    if missed:
        print(f"\n⚠ 掴めなかった {len(missed)}社（この社の機構語が語彙に無い）: {' '.join(missed)}")
        print('  ——日本株はSEC経路の外なので原理的に掴めない。それ以外は語彙の穴')

    # ─────────────────────────────────────────────────────────────────
    # ★実証済みの語を、未審査の母集団へ当て直す（この狩りで最も決定的な測定）
    #
    # 自己検証は「網が既知の85を掴むか」を測る。だが本当に知りたいのは逆で、
    # **その網が掴んだのと同じ語に、台帳の外の社が当たるか**。
    #   ・当たらなければ「この機構は台帳の外に存在しない」＝空振りが**証拠**になる
    #   ・当たれば読む先が名指しで出る
    # ⚠ 完全一致と語ANDを必ず分ける——語ANDは "boeing"+"material"+"specification" が
    #   同じ段落に散っているだけでも当たる。実測でこの3語の完全一致は母集団に**0件**。
    #   混ぜると「37社が当たった」というもっともらしい嘘になる。
    # ─────────────────────────────────────────────────────────────────
    proven = sorted({p for _, _, _, cb, le in hit for p in (list(cb) + list(le))})
    rlp = os.path.join(OUT, 'irr85_hunt2_readlist.json')
    recall = None
    if os.path.exists(rlp) and proven:
        rl = json.load(open(rlp, encoding='utf-8'))['rows']
        ex, an, who = {}, {}, {}
        for r in rl:
            md = r.get('mode') or {}
            for k in ('customer_bears', 'lock_evidence', 'neutral'):
                for q in (r.get(k) or []):
                    if q not in proven:
                        continue
                    an[q] = an.get(q, 0) + 1
                    if md.get(q, 'phrase') == 'phrase':
                        ex[q] = ex.get(q, 0) + 1
                        who.setdefault(q, []).append(r.get('ticker') or r.get('name', '')[:24])
        recall = {'n_proven': len(proven), 'n_readlist': len(rl),
                  'exact': ex, 'terms_only': {q: an[q] for q in an if not ex.get(q)},
                  'zero': [q for q in proven if not ex.get(q)], 'who': who}
        print(f"\n■ その語を、**台帳の外の {len(rl)}社**へ当て直す（完全一致だけを数える）")
        if ex:
            for q, n in sorted(ex.items(), key=lambda kv: -kv[1]):
                print(f"   {n:>4}社  {q}   [{' '.join(sorted(set(who[q]))[:6])}]")
        print(f"   **一社も当たらない語 {len(recall['zero'])}/{len(proven)}本**"
              f"（うち語ANDだけ当たる {len(recall['terms_only'])}本＝文字列は母集団に無い）")

    json.dump({'generated': dt.date.today().isoformat(), 'tool': 'night/irr85_hunt2_selftest.py',
               'n_known': len(known), 'n_hit': len(hit), 'missed': missed,
               'hit': [{'t': t, 'rank': p, 'score': round(s, 2),
                        'customer_bears': list(cb), 'lock_evidence': list(le)}
                       for t, p, s, cb, le in sorted(hit, key=lambda x: (x[1] or 99999))],
               'proven_phrases': proven, 'recall_on_unreviewed': recall},
              open(os.path.join(OUT, 'irr85_hunt2_selftest.json'), 'w'), ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
