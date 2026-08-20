#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr70_collect.py — 二重読みのワークフローの答えを一本に集める（2026-08-20新設）

なぜ道具にするか:
  200社を8つのワークフローに割って読ませたので、答えが**8箇所の journal.jsonl に散る**。
  手で拾うと必ず取り落とす——そして取り落とした社は「読んでいない」ではなく
  **「読んだが台帳に入っていない」**という一番静かな壊れ方になる（ルール7の同族）。

何をするか:
  1. すべての journal.jsonl から読解(ONE/MANY)と反証(REF/REFMANY)の結果を拾う
  2. 同じ社が複数回出たら**最後に走った反証を優先**（再実行の後勝ち）
  3. 反証が覆したら final_rung を採る。覆せなければ読解の rung
  4. **読んでいない社を名指しで出す**——これがこの道具の本体

使い方:
  python3 night/irr70_collect.py                 # 集計して out/irr70_verdicts.json へ
  python3 night/irr70_collect.py --quiet
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF = os.path.expanduser(
    '~/.claude/projects/-home-user-ccf-gate/ac22100b-fce1-56ac-96d4-8c0747738dca/subagents/workflows')
OUT = os.path.join(ROOT, 'out', 'irr70_verdicts.json')


def rows_of(v):
    """結果は 1社(ONE) のことも 班(MANY) のこともある。両方受ける"""
    if not isinstance(v, dict):
        return []
    if 'rows' in v and isinstance(v['rows'], list):
        return [x for x in v['rows'] if isinstance(x, dict) and x.get('ticker')]
    if v.get('ticker'):
        return [v]
    return []


def targets():
    """★読むはずの母集団＝**未検証の irr=70**。ここに無い社の判定は拾わない——
    別の目的で走った過去のワークフローの結果を混ぜると、
    『同じ台帳を見る二つの検査器が違うことを言う』(v9.9.65) をこの器の中で作ることになる。"""
    sa = json.load(open(os.path.join(ROOT, 'out', 'score_all.json')))
    rws = sa['rows'] if isinstance(sa, dict) else sa
    out = []
    for r in rws:
        if r.get('irr') != 70:
            continue
        p = os.path.join(ROOT, 'out', f"{r['t']}_gate_pack.json")
        if not os.path.exists(p):
            continue
        d = json.load(open(p))
        if any(x.get('rung') == 70 for x in ((d.get('_meta') or {}).get('irr85_verify') or [])):
            continue
        out.append(r['t'])
    return out


def collect(keep=None):
    reads, refs = {}, {}
    order = 0
    for j in sorted(glob.glob(os.path.join(WF, '*', 'journal.jsonl')),
                    key=lambda p: os.path.getmtime(p)):
        for line in open(j, encoding='utf-8', errors='ignore'):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get('type') != 'result':
                continue
            order += 1
            for x in rows_of(r.get('result')):
                t = str(x['ticker']).strip()
                if keep is not None and t not in keep:
                    continue
                # 反証は refuted/final_rung を持つ。読解は rung を持つ
                if 'refuted' in x or 'final_rung' in x:
                    refs[t] = dict(x, _o=order, _wf=os.path.basename(os.path.dirname(j)))
                elif 'rung' in x:
                    reads[t] = dict(x, _o=order, _wf=os.path.basename(os.path.dirname(j)))
    out = []
    for t, r in reads.items():
        v = refs.get(t)
        # ⚠ 反証は読解より**後**に走ったものだけ採る（前の実行の残骸を掴まない）
        if v and v.get('_o', 0) < r.get('_o', 0):
            v = None
        moved = bool(v and v.get('refuted'))
        q = (v.get('better_quotes') if moved and v.get('better_quotes') else r.get('quotes')) or []
        out.append(dict(
            ticker=t,
            rung=r.get('rung'),
            final_rung=(v.get('final_rung') if moved else r.get('rung')),
            hold=bool(r.get('hold') or (v and v.get('hold'))),
            refuted=moved,
            mechanism=r.get('mechanism') or '',
            scope=r.get('scope') or '',
            confidence=r.get('confidence') or '',
            evidence_gap=bool(r.get('evidence_gap')),
            source_note=r.get('source_note') or '',
            reason=r.get('reason') or '',
            quotes=q,
            counter_quotes=r.get('counter_quotes') or [],
            refute_why=(v.get('why') if v else '(反証なし)'),
            wf=r.get('_wf'),
        ))
    out.sort(key=lambda x: x['ticker'])
    return out, reads, refs


def main():
    quiet = '--quiet' in sys.argv
    todo = targets()
    out, reads, refs = collect(set(todo))
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    # 読むはずだった社
    got = {x['ticker'] for x in out}
    miss = [t for t in todo if t not in got]
    if quiet:
        print(f'{len(out)}件 / 未読 {len(miss)}社')
        return 0
    print(f'集めた判定 {len(out)}件  → {OUT}')
    print(f'  反証で覆った {sum(1 for x in out if x["refuted"])}件'
          f' ／ 保留 {sum(1 for x in out if x["hold"])}件'
          f' ／ 旧根拠が規約を満たしていなかった {sum(1 for x in out if x["evidence_gap"])}件')
    from collections import Counter
    c = Counter(x['final_rung'] for x in out if not x['hold'])
    print('  刻み:', ', '.join(f'{k}:{v}社' for k, v in sorted(c.items(), key=lambda kv: -(kv[0] or 0))))
    print(f'\n★まだ読んでいない {len(miss)}社')
    if miss:
        print('  ' + ' '.join(miss))
    # 反証だけあって読解が無い（＝読解が落ちた）社
    orphan = [t for t in refs if t not in reads]
    if orphan:
        print(f'⚠ 反証だけあって読解が無い {len(orphan)}社: ' + ' '.join(orphan))
    return 0


if __name__ == '__main__':
    sys.exit(main())
