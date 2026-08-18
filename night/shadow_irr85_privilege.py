#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_irr85_privilege.py — **irr=85 の「特権」を外したら投下可はどうなるか**の影の計測
（2026-08-18新設・ユーザーの問い「irr85の銘柄たちは本当に信じれる？」の続き）

【なぜ測るか】
  この台帳は13年の検証で「機械の指標は5系統・204通り・7アンカーすべて全滅、生き延びたのは
  原本読解の irr だけ」と繰り返し出しており、その irr=85 に**二つの特権**を与えている:
    (1) **別枠85**（ccfIrr85Frame・v9.9.119/122）＝Ω75+ を免除して買付の土俵に上げる
    (2) **席の優先**（ccfAllocTop の mech()・v9.9.100）＝上位10席で irr=85 を先に置く
  ところが 2026-08-18 の再実測で、その根拠になった「2018年ビンテージ +24.6%/年・P=0.71」には
  **標本の重複（19件＝実14社）／半導体への偏り（外すと中央値 20.5%→11.9%・gap +0.20→+0.08）／
  読み手の水準ずれ（同じ111社で 85 の付与率 6.3%→17.1%・降格ゼロ）**があると判った。
  さらに**その読み替えで格上げされた12社のうち10社は、今日の厳しい基準では 70 に戻っている**。
  ＝**特権の根拠は、今日の基準が退けた読みの上に立っている**。

  だから「特権を外したら何が起きるか」を**値を一切動かさずに**測る。
  ⚠これは規約の改定案ではない（絶対のルール1）。**外すかどうかはユーザーの判断**で、
  この道具は「外したときの代金」を数字で見せるだけ。

【案】
  P0 現行           —— 別枠85 ＋ 席の優先（今日の門）
  A  別枠85だけ外す —— irr=85 でも Ω75+ が要る（席の優先は残す）
  B  席の優先だけ外す—— 席はΩ順のみ（別枠85は残す）
  C  両方外す       —— irr=85 は「堀の一要素」に戻る（採点への寄与は不変）

【作法】index.html を退避 → 1〜2行だけ差し替え → score_all → **必ず元へ戻す**（sha256で検算）。
  正本の採点・刻み・重み・関門・売却規律・配分はいっさい変えない。

【配分も測る】席が変われば城60%の配り方（Tier 5段 8:6:4:3:2）も変わる。
  ⚠**再実装しない**——index.html から ccfMcapUSD / CCF_MCAP_TIERS / ccfMcapTier / ccfMcapWeights の
  **本文をそのまま抜いて eval する**（v9.9.65の掟）。母集団は「席の社 ＋ in_castle_split の門外例外」。

使い方: python3 night/shadow_irr85_privilege.py [--only A]
出力  : out/shadow_irr85_privilege.json
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, 'index.html')
BAK = HTML + '.privshadow_bak'
SCORE = os.path.join(ROOT, 'out', 'score_all.json')
SCORE_BAK = SCORE + '.privshadow_bak'

# ── 錨（index.html の実文。ズレたら止める）─────────────────────────────
MECH_OLD = ("  const mech=c=>((c&&+c.irr===85)&&!ccfIrr85Below(c))?0:1;"
            "   // 0=機構が実証された型（先に席へ）")
MECH_NEW = "  const mech=c=>1;   // 【影の計測】席の優先を無効化（正本ではない）"
FRAME_OLD = "  if(irr!==85)return {pass:false,why:null};"
FRAME_NEW = ("  if(irr!==85)return {pass:false,why:null};\n"
             "  return {pass:false,why:'【影の計測】別枠85を無効化（正本ではない）'};")

CASES = [
    ('A', '別枠85だけ外す（irr=85でもΩ75+が要る・席の優先は残す）', True, False),
    ('B', '席の優先だけ外す（席はΩ順のみ・別枠85は残す）', False, True),
    ('C', '両方外す（irr=85は堀の一要素に戻る＝採点への寄与は不変）', True, True),
]


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()


# ── 配分: 門の実装をそのまま抜いて使う（再実装しない）────────────────────
def _slice_fn(src, head):
    """`head` から始まる関数/定数の本文を、括弧の収支で切り出す（門の実文をそのまま使う）"""
    i = src.index(head)
    cands = [(src.find(c, i), c) for c in ('{', '[') if src.find(c, i) >= 0]
    j, ch = min(cands)
    op, cl = (ch, '}' if ch == '{' else ']')
    d = 0
    for k in range(j, len(src)):
        if src[k] == op:
            d += 1
        elif src[k] == cl:
            d -= 1
            if d == 0:
                return src[i:k + 1] + (';' if op == '[' else '')
    raise RuntimeError('切り出せない: ' + head)


def alloc_weights(src0, seats, packs, fx, ex_split):
    """席＋in_castle_split の例外へ、門の ccfMcapWeights で城60%を配る"""
    body = "\n".join(_slice_fn(src0, h) for h in (
        'function ccfMcapUSD(', 'const CCF_MCAP_TIERS=',
        'function ccfMcapTier(', 'function ccfMcapWeights('))
    lst = []
    for t in list(seats) + [t for t in ex_split if t not in seats]:
        d = packs.get(t) or {}
        lst.append({'t': t, 'nm': d.get('nm'), 'px': d.get('px'),
                    'ni': d.get('ni'), 'eps': d.get('eps')})
    js = (body + "\n"
          + "const IN=" + json.dumps(lst) + ";\n"
          + "const list=IN.map(x=>({t:x.t,m:ccfMcapUSD(x," + repr(fx) + ")}));\n"
          + "const r=ccfMcapWeights(list,60,8);\n"
          + "console.log(JSON.stringify({mode:r.mode,w:r.w,tier:r.tier,missing:r.missing,"
            "m:Object.fromEntries(list.map(x=>[x.t,x.m]))}));")
    p = subprocess.run(['node', '-e', js], capture_output=True, text=True, cwd=ROOT)
    if p.returncode:
        raise RuntimeError('配分の計算に失敗: ' + (p.stderr or p.stdout)[:300])
    return json.loads(p.stdout)


def run_score():
    subprocess.run(['node', os.path.join(ROOT, 'night', 'score_all.js')],
                   cwd=ROOT, capture_output=True, text=True)
    rows = json.load(open(SCORE, encoding='utf-8'))
    buy = [r['t'] for r in rows if r.get('buy')]
    nxt = [r['t'] for r in rows if r.get('quali') and not r.get('buy')]
    by = {r['t']: r for r in rows}
    return buy, nxt, by


def main():
    only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None
    src0 = open(HTML, encoding='utf-8').read()
    if MECH_OLD not in src0:
        print('✗ 席の優先の錨が見つからない（index.html の実文が変わった）', file=sys.stderr)
        return 1
    if FRAME_OLD not in src0:
        print('✗ 別枠85の錨が見つからない（index.html の実文が変わった）', file=sys.stderr)
        return 1
    h0 = sha(HTML)

    # パック（配分の入力）とドル円
    packs = {}
    for p in os.listdir(os.path.join(ROOT, 'out')):
        if p.endswith('_gate_pack.json'):
            t = p[:-len('_gate_pack.json')]
            try:
                d = json.load(open(os.path.join(ROOT, 'out', p), encoding='utf-8'))
            except Exception:
                continue
            packs[t] = {k: d.get(k) for k in ('nm', 'px', 'ni', 'eps', 'irr')}
    fx = None
    try:
        fx = (json.load(open(os.path.join(ROOT, 'out', 'dashboard.json'),
                             encoding='utf-8')).get('fx') or {}).get('USDJPY')
    except Exception:
        pass
    ex_split = []
    try:
        for it in (json.load(open(os.path.join(ROOT, 'gate_exceptions.json'),
                                  encoding='utf-8')).get('items') or []):
            if it.get('in_castle_split'):
                ex_split.append(str(it.get('t') or '').upper())
    except Exception:
        pass

    shutil.copy2(HTML, BAK)
    if os.path.exists(SCORE):
        shutil.copy2(SCORE, SCORE_BAK)
    out = {}
    try:
        b0, n0, by0 = run_score()
        irr85_0 = [t for t in b0 if str((packs.get(t) or {}).get('irr')) in ('85', '85.0')]
        w0 = alloc_weights(src0, b0, packs, fx, ex_split)
        s85 = round(sum(w0['w'].get(t, 0) for t in irr85_0), 2)
        print(f'■ P0 現行  投下可{len(b0)}社: {" ".join(b0)}')
        print(f'   うち irr=85 は **{len(irr85_0)}社**: {" ".join(irr85_0) or "—"}'
              f'（目標ウェイト合計 **{s85}%** ／ 城60%の{round(s85/60*100)}%）')
        print(f'   🔵次点: {" ".join(n0[:10])}')
        out['P0'] = dict(label='現行（別枠85＋席の優先）', buy=b0, next=n0,
                         irr85_in_buy=irr85_0, w=w0['w'], tier=w0['tier'],
                         mode=w0['mode'], irr85_weight=s85)

        for kind, lab, drop_frame, drop_mech in CASES:
            if only and kind != only:
                continue
            s = src0
            if drop_frame:
                s = s.replace(FRAME_OLD, FRAME_NEW)
            if drop_mech:
                s = s.replace(MECH_OLD, MECH_NEW)
            open(HTML, 'w', encoding='utf-8').write(s)
            b, n, by = run_score()
            w = alloc_weights(src0, b, packs, fx, ex_split)
            i85 = [t for t in b if str((packs.get(t) or {}).get('irr')) in ('85', '85.0')]
            sw = round(sum(w['w'].get(t, 0) for t in i85), 2)
            gone = [t for t in b0 if t not in b]
            came = [t for t in b if t not in b0]
            print(f'\n■ {kind} {lab}')
            print(f'   投下可{len(b)}社: {" ".join(b)}')
            print(f'   出 {" ".join(gone) or "—"} ／ 入 {" ".join(came) or "—"}')
            print(f'   うち irr=85 は {len(i85)}社（目標ウェイト合計 {sw}%）')
            # 席順が変わっただけの社（顔ぶれは同じでも配分が動く）
            mv = {t: (round(w0['w'].get(t, 0), 2), round(w['w'].get(t, 0), 2))
                  for t in set(list(w0['w']) + list(w['w']))
                  if abs(w0['w'].get(t, 0) - w['w'].get(t, 0)) > 0.005}
            if mv:
                print('   目標ウェイトが動く社: '
                      + ' ／ '.join(f'{t} {a}→{b_}%' for t, (a, b_) in sorted(mv.items())))
            out[kind] = dict(label=lab, buy=b, next=n, dropped=gone, added=came,
                             irr85_in_buy=i85, irr85_weight=sw, w=w['w'],
                             tier=w['tier'], mode=w['mode'], weight_moved=mv)
    finally:
        shutil.move(BAK, HTML)
        if os.path.exists(SCORE_BAK):
            shutil.move(SCORE_BAK, SCORE)
        assert sha(HTML) == h0, '★index.html の復元に失敗した'
        print('\n（index.html と out/score_all.json を復元した — sha256 一致）')

    json.dump({'generated': '2026-08-18', 'fx': fx, 'ex_split': ex_split,
               'note': 'これは影の計測であって規約の改定案ではない（絶対のルール1）。'
                       '正本の採点・刻み・重み・関門・売却規律・配分はいっさい変えていない。',
               'cases': out},
              open(os.path.join(ROOT, 'out', 'shadow_irr85_privilege.json'),
                   'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('→ out/shadow_irr85_privilege.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
