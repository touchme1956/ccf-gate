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
    reads, refs, dup = {}, {}, {}
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
                # ★**排他で分類してはいけない**（2026-08-20の実害）。
                #   readmass は読解と反証を**1行にまとめて**返すので、その行は
                #   `rung`（読解）と `refuted`（反証）を**両方**持つ。
                #   elif で分けると読解が消え、`for t, r in reads.items()` から
                #   その社が丸ごと落ちる——**反証が成功した社ほど落ちる**という最悪の向き。
                #   実際 T1〜T7 は反証がセッション上限で死んで `refuted` が無かったので
                #   読解として通り、**反証が通った T8 の ECL/QLYS だけが静かに消えていた**。
                #   ⇒ 二つの if にして、まとめ行は**読解でもあり反証でもある**として扱う。
                #   （_o が同じになるので「反証は読解より後」の検問も等号で通る）
                if 'refuted' in x or 'final_rung' in x:
                    refs[t] = dict(x, _o=order, _wf=os.path.basename(os.path.dirname(j)))
                if 'rung' in x:
                    # ★同じ社を二つの班が独立に読むことがある（日本株は材料の経路が違うので
                    #   わざと二重に走らせた）。**後勝ちで捨てず、一致率の材料として残す**——
                    #   この改定の目的そのものが「一致率 0.706 を上げること」なので、
                    #   偶然できた二重読みは**この作業で唯一の再現性の実測**になる。
                    cand = dict(x, _o=order, _wf=os.path.basename(os.path.dirname(j)))
                    dup.setdefault(t, []).append(cand)
                    # ★**後勝ちではなく「出所を名指しした読解」を優先する**（2026-08-20）。
                    #   日本株は材料の経路が二つある——決算短信しか無いキャッシュで読んだ班と、
                    #   EDINET から有報を取り直した班。前者は保留に倒れ、後者は docId と
                    #   提出URLを `source_note` に書く。**実測で分離は綺麗**（4社とも
                    #   保留側は source_note が空・取り直し側は 726〜1275字）。
                    #   後勝ちのままだと**順序が変われば判定が変わる**——今日は取り直しが
                    #   後に走ったので正しい側が採られたが、それは規則ではなく偶然。
                    #   ⇒ 出所を書いた読解を優先し、同格なら後勝ち。
                    #   （v9.9.144 が「機構を名指しできないなら50」と要求するのと同じ原理を、
                    #     読解の採否にも当てる＝**証拠を示した側を採る**）
                    prev = reads.get(t)
                    if (prev is None
                            or (bool(cand.get('source_note')) and not prev.get('source_note'))
                            or (bool(cand.get('source_note')) == bool(prev.get('source_note')))):
                        reads[t] = cand
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
    return out, reads, refs, dup


def main():
    quiet = '--quiet' in sys.argv
    todo = targets()
    out, reads, refs, dup = collect(set(todo))
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
    # ★二重に読まれた社の一致率——この作業で唯一の再現性の実測
    twice = {t: v for t, v in dup.items() if len(v) >= 2}
    if twice:
        agree = sum(1 for v in twice.values() if len({x.get('rung') for x in v}) == 1)
        print(f'\n★二重に読まれた {len(twice)}社 — 刻みが一致 {agree}社'
              f'（一致率 {agree/len(twice):.3f}）')
        for t, v in sorted(twice.items()):
            rr = [f"{x.get('rung')}{'(保留)' if x.get('hold') else ''}@{x['_wf'][3:10]}" for x in v]
            mark = '✓' if len({x.get('rung') for x in v}) == 1 else '⚠割れた'
            print(f'   {mark} {t:6} ' + ' / '.join(rr))
        print('  ⚠ 2026-08-12 の実測は irr=70 で **0.706**（85は1.00）。改定の狙いはここを上げること')

    # 反証だけあって読解が無い（＝読解が落ちた）社
    orphan = [t for t in refs if t not in reads]
    if orphan:
        print(f'⚠ 反証だけあって読解が無い {len(orphan)}社: ' + ' '.join(orphan))
    return 0


if __name__ == '__main__':
    sys.exit(main())
