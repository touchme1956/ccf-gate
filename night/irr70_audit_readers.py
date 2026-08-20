#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr70_audit_readers.py — 200社の判定が「読んだ結果」か「既定に流れた結果」かを測る（2026-08-20新設）

なぜ要るか:
  v9.9.144 は「機構を名指しできないなら 50」と定めた——つまり **50 が既定**。
  だから 200社を35班に割って読ませると、**怠けた班と丁寧な班の区別が付かないまま
  台帳の堀が一斉に下がる**危険がある。しかも 50 は引用を要求しないので
  `irr70_apply` の逐語検問も素通りする（70 にしか掛からない）。

  歴史側の読解では「採点者の偏りなし（35班中17班に分散・1班最大2社）」を実測して
  この危険を潰した。同じ検査をこちらにも当てる。

何を見るか（**判定はしない。作業リストを出す**）:
  1. **班ごとの刻みの偏り**——全員 50 の班／全員 70 の班を名指しする
  2. **理由に測定の痕跡があるか**——grep の実数・語の出現回数・「探したが無かった」の記述
  3. **反証が実際に走ったか**——反証が無い社／反証が中身の無い社
  4. **50 なのに反証の引用がある社**（＝70 を支える文が見つかったのに 50 のままかもしれない）
  5. **材料の厚みと判定の関係**——候補文が厚いのに一言で 50 にした社

使い方:
  python3 night/irr70_audit_readers.py            # 作業リスト
  python3 night/irr70_audit_readers.py --json
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V = os.path.join(ROOT, 'out', 'irr70_verdicts.json')
DOS = os.path.join(ROOT, 'out', 'irr70_dossiers')

# 「測った」の痕跡。数を書いている／原本を走査したと述べている
MEASURED = re.compile(
    r'\b\d+\s*(?:回|件|本|箇所|hits?|matches?|occurrences?)'
    r'|grep|wc -l|出現(?:は|が|回数)|全文|走査|該当(?:は|なし|ゼロ|0)'
    r'|\b0\s*(?:回|件|hits?)|一度も|一件も|一つも', re.I)


def load():
    rows = json.load(open(V, encoding='utf-8'))
    dos = {}
    if os.path.isdir(DOS):
        for f in os.listdir(DOS):
            if f.endswith('.json'):
                try:
                    dos[f[:-5]] = json.load(open(os.path.join(DOS, f), encoding='utf-8'))
                except Exception:
                    pass
    return rows, dos


def main():
    as_json = '--json' in sys.argv
    rows, dos = load()
    if not rows:
        print('判定がまだ無い'); return 0
    out = {'n': len(rows), 'flags': {}}

    # 1) 班ごとの偏り
    byw = defaultdict(list)
    for r in rows:
        byw[r.get('wf') or '?'].append(r)
    uni = []
    for w, rs in sorted(byw.items()):
        c = Counter(x['final_rung'] for x in rs if not x.get('hold'))
        if len(rs) >= 3 and len(c) == 1:
            uni.append(dict(wf=w, n=len(rs), rung=list(c)[0],
                            tickers=[x['ticker'] for x in rs]))
    out['flags']['班の刻みが一様'] = uni

    # 2) 理由に測定の痕跡が無い
    nomeas = [dict(ticker=r['ticker'], rung=r['final_rung'], len=len(r.get('reason') or ''))
              for r in rows if not MEASURED.search(r.get('reason') or '')]
    out['flags']['理由に測定の痕跡が無い'] = nomeas

    # 3) 反証が走っていない／中身が無い
    noref = [r['ticker'] for r in rows
             if (r.get('refute_why') or '').strip() in ('', '(反証なし)')
             or len(r.get('refute_why') or '') < 60]
    out['flags']['反証が無いか中身が薄い'] = noref

    # 4) 50 なのに反証が引用を出している（＝70側の証拠が見つかっていた可能性）
    odd = [dict(ticker=r['ticker'], why=(r.get('refute_why') or '')[:160])
           for r in rows if r['final_rung'] == 50 and not r.get('hold')
           and re.search(r'『|"|多年|multi-?year|switching cost|qualif', r.get('refute_why') or '', re.I)
           and re.search(r'70', r.get('refute_why') or '')]
    out['flags']['50だが反証が70側の材料に触れている'] = odd

    # 5) 材料が厚いのに理由が短い
    thin = []
    for r in rows:
        d = dos.get(r['ticker']) or {}
        n = sum((d.get('counts') or {}).values())
        if n >= 30 and len(r.get('reason') or '') < 700:
            thin.append(dict(ticker=r['ticker'], 候補文=n, 理由字数=len(r.get('reason') or '')))
    out['flags']['材料が厚いのに理由が短い'] = thin

    # ★0) 85 と読まれた社。**これは作業リストの最上位**——
    #   apply は 85 を自動で入れない（3層の手続きへ回す）が、85 は堀を**上げる**ので
    #   買付の席を動かしうる唯一の向き。埋もれさせない。
    up = [dict(ticker=r['ticker'], mech=(r.get('mechanism') or '')[:90],
               conf=r.get('confidence'), refuted=r.get('refuted'))
          for r in rows if r.get('rung') == 85 or r.get('final_rung') == 85]
    out['flags']['★85と読まれた（3層の手続きへ回す）'] = up

    # 6) 引用ゼロの 70（apply が落とすはずだが先に見せる）
    q0 = [r['ticker'] for r in rows if r['final_rung'] == 70 and not (r.get('quotes') or [])]
    out['flags']['70なのに引用が無い'] = q0

    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1)); return 0

    c = Counter(r['final_rung'] for r in rows if not r.get('hold'))
    print(f'■ 判定 {len(rows)}件  ' + ' '.join(f'{k}:{v}社' for k, v in sorted(c.items(), key=lambda kv: -(kv[0] or 0)))
          + f"  保留 {sum(1 for r in rows if r.get('hold'))}社")
    print(f"  班 {len(byw)}／覆った {sum(1 for r in rows if r.get('refuted'))}件"
          f"／旧根拠が規約を満たさず {sum(1 for r in rows if r.get('evidence_gap'))}件")
    print()
    for k, v in out['flags'].items():
        if not v:
            print(f'  ✓ {k}: 0件')
            continue
        print(f'  ⚠ {k}: {len(v)}件')
        for x in v[:12]:
            print('     ', json.dumps(x, ensure_ascii=False)[:170] if isinstance(x, dict) else x)
        if len(v) > 12:
            print(f'      … 他 {len(v)-12}件')
    print('\n⚠ これは**作業リストであって有罪判決ではない**——'
          '鳴った社を原本で見直す先を絞るための道具')
    return 0


if __name__ == '__main__':
    sys.exit(main())
