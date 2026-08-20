#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr70_apply.py — 二重読みの判定を台帳へ入れる（2026-08-20新設）

なぜ道具にするか:
  200社ぶんを手で書くと、**引用の書き方が壊れた瞬間に逐語照合が「機構文が消えた」に化ける**。
  2026-08-19 だけで3通りの壊れ方を踏んだ——却下した引用を『』に入れる(MSFT)／
  XBRLのタグ割れ(MSFT)／省略記号なしの短縮(HWM)。だから**書く側で機械的に検問する**。

検問（ここを通らない行は書かない）:
  1. rung は 50/70/85 のいずれか（規約に無い中間値は作らない）
  2. **85 は自動では入れない**——85には3層の手続き（根拠の型・逐語照合・二重読み）があるので
     `audit_irr85` の経路へ回す。ここでは印だけ付けて据置
  3. 70 を置くなら**引用が1件以上**あり、かつ**原本キャッシュと逐語一致**すること
     （irr85_mech_diff.norm と同じ正規化を使う＝二重実装を作らない）
  4. 却下した引用・見出しは『』に入れない（引用は肯定の証拠だけ）

使い方:
  python3 night/irr70_apply.py verdicts.json            # 検問だけ（書かない）
  python3 night/irr70_apply.py verdicts.json --write
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import irr85_mech_diff as M          # norm を共有（照合の基準を二つ持たない）

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'out', '_src_cache')
D = '2026-08-20'


def body(t):
    p = os.path.join(CACHE, f'{t}.txt')
    if not os.path.exists(p):
        return None
    return ' ' + M.norm(open(p, encoding='utf-8', errors='ignore').read()) + ' '


def check(r):
    """この行を書いてよいか。返り値 (ok, 落とした理由, 逐語NGの引用)"""
    t = r.get('ticker')
    # ★材料が薄い社は**書かない**。読み手が hold を立てたらそれを尊重する——
    #   決算短信しか無い日本株で 50 と書くと『読めていない』を『機構が無い』に化かす（ルール7）。
    if r.get('hold'):
        return False, '読み手が保留にした（材料が薄い）: ' + (r.get('reason') or '')[:80], []
    rung = r.get('final_rung', r.get('rung'))
    if rung not in (50, 70, 85):
        return False, f'刻みが規約に無い: {rung}', []
    if rung == 85:
        return False, '85は自動で入れない（audit_irr85 の3層の手続きへ回す）', []
    qs = [q.get('q', '') for q in (r.get('quotes') or []) if q.get('q')]
    if rung == 70 and not qs:
        return False, '70なのに引用が無い（v9.9.144: 付けられないなら50）', []
    # ★70 は**機構の名指し**も要る（v9.9.144 の要求は「機構を名指し、原本の引用を付ける」の**両方**）。
    #   引用だけ通すと「機構の名前が無い70」が残り、次の読み手がまた同じ検証をやり直す。
    #   実害: 反証で 50→70 へ覆った3社（SPGI/TGS/ENB）が、引用は優れているのに機構欄が空だった
    #   ——反証の schema に機構の欄が無かったのが原因（設計の穴・同日是正）。
    if rung == 70 and not (r.get('mechanism') or '').strip():
        return False, '70なのに機構が名指しされていない（v9.9.144: 機構と引用の両方が要る）', []
    b = body(t)
    if b is None:
        return False, '原本キャッシュが無い＝逐語照合できない', []
    ng = []
    for q in qs:
        for part in re.split(r'…+|\.\.\.+', q):
            part = part.strip(' 　*・,')
            letters = sum(c.isascii() and c.isalpha() for c in part)
            if letters < 40 and not re.search(r'[ぁ-んァ-ヶ一-龥]{12,}', part):
                continue          # 短い断片は偶然一致するので照合しない
            if M.norm(part) not in b:
                ng.append(part[:110])
    if ng and rung == 70:
        return False, f'引用が原本と逐語一致しない（{len(ng)}件）', ng
    return True, ('引用の逐語NGあり（50なので値は入れる）' if ng else ''), ng


def evidence(r):
    t = r['ticker']
    rung = r.get('final_rung', r.get('rung'))
    L = [f'**irr {rung}（{D}・irr=70 の二重読み。v9.9.144 の5点検問）**']
    if rung == 70 and r.get('mechanism'):
        L.append('《機構》' + r['mechanism'])
    for q in (r.get('quotes') or [])[:6]:
        L.append('『' + q['q'].strip() + '』' + (f"（{q.get('where','')}）" if q.get('where') else '')
                 + (f"——{q.get('why','')}" if q.get('why') else ''))
    if r.get('counter_quotes'):
        L.append('《反証（同じ原本に同居する）》'
                 + ' ／ '.join('『' + (c.get('q') or '').strip() + '』' for c in r['counter_quotes'][:4] if c.get('q')))
    if r.get('scope'):
        L.append('《射程》' + r['scope'])
    L.append('《検問と反証の経緯》' + (r.get('reason') or '')[:2600])
    if r.get('ref_why'):
        L.append('《別の読み手による反証》' + str(r['ref_why'])[:1600])
    return '　'.join(L)


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__); return
    rows = json.load(open(a[0]))
    rows = rows.get('rows') if isinstance(rows, dict) else rows
    write = '--write' in a
    ok, skip, changed, held = [], [], [], []
    for r in rows:
        good, why, ng = check(r)
        t = r['ticker']; rung = r.get('final_rung', r.get('rung'))
        p = os.path.join(ROOT, 'out', f'{t}_gate_pack.json')
        if not os.path.exists(p):
            skip.append((t, 'パックが無い')); continue
        d = json.load(open(p)); old = d.get('irr')
        if not good:
            skip.append((t, why + (('｜' + ' / '.join(ng[:2])) if ng else '')))
            # ★保留・不受理の理由は**パックに残す**（値は触らない）。
            #   残さないと次の読み手が同じ穴を掘る——台帳が dom の探索で
            #   「否定的結果も _meta.nulls へ記録する」と決めたのと同じ作法。
            if write:
                m = d.setdefault('_meta', {})
                k = m.get('kenshi'); k = [k] if isinstance(k, str) else (k or [])
                k.append(f'{D} irr の二重読み: 値は据置（{old}）。'
                         + ('材料が薄く判定できず保留' if r.get('hold')
                            else '85と読まれたので3層の手続きへ回す' if rung == 85
                            else '不受理: ' + why)
                         + '——' + (r.get('reason') or '')[:1400])
                m['kenshi'] = k
                json.dump(d, open(p, 'w'), ensure_ascii=False, indent=1)
                held.append(t)
            continue
        if write:
            m = d.setdefault('_meta', {})
            d['irr'] = rung
            m.setdefault('evidence', {})['irr'] = evidence(r)
            m.setdefault('irr85_verify', []).append({
                'date': D, 'kind': '二重読み', 'rung': rung,
                'verdict': ('据置' if old == rung else f'是正({old}→{rung})'),
                'by': 'irr=70 の二重読み（未検証200社の一斉検証・5点検問）',
                'note': (('confidence=' + str(r.get('confidence') or '?')) +
                         ('｜旧根拠は規約を満たしていなかった' if r.get('evidence_gap') else '') +
                         ('｜別の読み手の反証: ' + ('覆った' if r.get('refuted') else '落とせなかった')
                          if r.get('ref_why') else '') +
                         (f'｜⚠引用の逐語NG {len(ng)}件' if ng else '')),
            })
            k = m.get('kenshi'); k = [k] if isinstance(k, str) else (k or [])
            k.append(f'{D} irr {old} → {rung}（二重読み）' if old != rung else
                     f'{D} irr={rung} 据置（二重読み・根拠を書き直し）')
            m['kenshi'] = k
            json.dump(d, open(p, 'w'), ensure_ascii=False, indent=1)
        ok.append((t, old, rung))
        if old != rung:
            changed.append((t, old, rung))
    print(f'■ 判定 {len(rows)}件 → 受理 {len(ok)}／見送り {len(skip)}　（{"書いた" if write else "検問のみ"}）')
    if held:
        print(f'  不受理の理由をパックへ記録（値は据置）: {len(held)}社  ' + ' '.join(held))
    print(f'  値が動く: {len(changed)}社  ' + ' '.join(f'{t}:{o}→{n}' for t, o, n in changed[:40]))
    for t, why in skip:
        print(f'  ✗ {t:6} {why[:120]}')


if __name__ == '__main__':
    main()
