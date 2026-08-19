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
    # 読む順の点は cmd_rank と同じ式（書き写さず、universe の欄から組み直す）
    def sc(r):
        return len(r['customer_bears']) * 5 + len(r['lock_evidence']) * 2 + len(r['neutral']) * 0.4
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
    return 0


if __name__ == '__main__':
    sys.exit(main())
