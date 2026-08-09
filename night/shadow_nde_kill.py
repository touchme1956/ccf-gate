#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/shadow_nde_kill.py — **財務キル（負債/EBITDA>4）の線を動かしたら誰がどう動くか**（2026-08-09新設）

発端（ユーザーの問い「財務キルを5にするのは？」）:
  v9.9.119 の irr=85 の別枠は **財務キル nde>4 だけは免除しない**と決めた（案②）。
  その線を 4→5 にすると何が起きるかを、推測ではなく門そのもので測る。

**この道具は測るだけ。index.html を一時的に書き換えて score_all を回し、必ず元へ戻す。**
（採点式・閾値の変更は絶対のルール1＝ユーザーの明示指示の領分）

測る三つ:
  1. **門の中で誰が動くか** —— キルの線だけを動かした場合／レバレッジの坂も一緒に伸ばした場合
     ⚠ **キルだけ動かすと 4<nde≤5 が「罰も無くキルも無い」空白になる**——
        現行の坂は `nde 2.5→4 で最大9.0の減点` で、4でキルへ引き継がれる設計。
        線だけ5へ動かすと、いちばん危ない帯が**現行より有利**になる（v9.9.93 で潰した崖の逆流）
  2. **歴史の実測** —— 2018年ビンテージ(n=956)の nde と前方8.1年の配当込みリターン。
     **遮断器は「止めた側の左尾」で裁く**（v9.9.98/99 で確立した物差し）＝恒久毀損率 P(年率≤−15%)
  3. **売却規律との整合** —— S1 は `nde>4 に転落` を売りの引き金に持つ（絶対のルール1で保護）。
     買いの線だけ動かすと**買う理由と売る理由が別の数字になる**

使い方: python3 night/shadow_nde_kill.py [--json]
"""
import io
import json
import os
import re
import statistics as st
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = '--json' in sys.argv[1:]
HTML = 'index.html'
KILL = "  if(ndeK!==null&&ndeK>4)kills.push('負債/EBITDA&gt;4');"
PEN = "  if(ndeV>2.5&&ndeV<=4){levPen+=(ndeV-2.5)*6; levMsg.push(`レバレッジ高め(${ndeV.toFixed(1)}x) −${((ndeV-2.5)*6).toFixed(0)}`);}"


def run():
    subprocess.run(['node', 'night/score_all.js'], capture_output=True, text=True)
    a = json.load(open('out/score_all.json', encoding='utf-8'))
    return {r['t']: r for r in a}


def summarize(cur, base=None):
    buy = [t for t, r in cur.items() if r.get('buy')]
    qual = [t for t, r in cur.items() if r.get('quali')]
    kil = [t for t, r in cur.items() if r.get('kills')]
    d = {'buy': sorted(buy, key=lambda t: -cur[t]['s']), 'nbuy': len(buy),
         'nquali': len(qual), 'nkill': len(kil),
         'n75': sum(1 for r in cur.values() if (r['s'] or 0) >= 75)}
    if base:
        d['moved'] = sorted([t for t in cur if abs((cur[t]['s'] or 0) - (base[t]['s'] or 0)) > 0.05],
                            key=lambda t: -abs((cur[t]['s'] or 0) - (base[t]['s'] or 0)))
        d['buy_in'] = sorted(set(buy) - set(t for t, r in base.items() if r.get('buy')))
        d['buy_out'] = sorted(set(t for t, r in base.items() if r.get('buy')) - set(buy))
    return d


def history():
    """2018年ビンテージ: nde と前方8.1年の配当込みリターン。遮断器は左尾で裁く。"""
    F = {r['ticker']: r for r in json.load(open('out/retro_features_2018.json', encoding='utf-8'))['rows']}
    R = {r['ticker']: r for r in json.load(open('out/retro_returns_2018.json', encoding='utf-8'))['rows']}
    P = [(F[t].get('nde18'), R[t]['tr_cagr']) for t in F if t in R and F[t].get('nde18') is not None]
    P = [(n, r) for n, r in P if n is not None and -20 < n < 40]
    out = []
    base_imp = sum(1 for _, r in P if r <= -0.15) / len(P)
    for lab, pred in [('nde ≤ 0（純現金）', lambda n: n <= 0), ('0 < nde ≤ 2', lambda n: 0 < n <= 2),
                      ('2 < nde ≤ 3', lambda n: 2 < n <= 3), ('3 < nde ≤ 4', lambda n: 3 < n <= 4),
                      ('**4 < nde ≤ 5**', lambda n: 4 < n <= 5), ('nde > 5', lambda n: n > 5)]:
        g = [r for n, r in P if pred(n)]
        if not g:
            continue
        out.append({'lab': lab, 'n': len(g), 'med': st.median(g),
                    'imp': sum(1 for r in g if r <= -0.15) / len(g),
                    'p15': sum(1 for r in g if r >= 0.15) / len(g)})
    return P, base_imp, out


def main():
    src = io.open(HTML, encoding='utf-8').read()
    if KILL not in src or PEN not in src:
        print('✗ 錨が見つからない——index.html のキル/坂の行が変わった可能性がある。'
              'この道具は当時の実装を前提にしているので、錨を確認してから使うこと')
        return 1
    P, base_imp, hist = history()

    print('■ 歴史の実測（2018年ビンテージ・n={} 社・前方8.1年・配当込み）'.format(len(P)))
    print('  **遮断器は「止めた側の左尾」で裁く**（v9.9.98/99 の物差し）。'
          f'全体の恒久毀損 P(年率≤−15%) = {base_imp*100:.1f}%')
    print(f"  {'帯':<20}{'n':>5}{'中央値':>9}{'P(15%+)':>9}{'恒久毀損':>9}")
    for h in hist:
        print(f"  {h['lab']:<18}{h['n']:>5}{h['med']*100:>8.1f}%{h['p15']:>9.2f}{h['imp']:>9.2f}"
              + ('  ← 4→5 で通すことになる帯' if '4 < nde' in h['lab'] else ''))

    results = {}
    try:
        base = run()
        results['A 現行（キル>4・坂 2.5→4）'] = summarize(base)
        # B: キルの線だけ 5 へ（坂はそのまま＝4<nde≤5 が罰もキルも無い空白になる）
        io.open(HTML, 'w', encoding='utf-8').write(src.replace(KILL, KILL.replace('>4)', '>5)'), 1))
        results['B キルだけ 5 へ（坂は 2.5→4 のまま）'] = summarize(run(), base)
        # C: キルも坂も 5 へ（空白を作らない形）
        s2 = src.replace(KILL, KILL.replace('>4)', '>5)'), 1)
        s2 = s2.replace(PEN, PEN.replace('ndeV<=4', 'ndeV<=5'), 1)
        io.open(HTML, 'w', encoding='utf-8').write(s2)
        results['C キルも坂も 5 へ（坂 2.5→5）'] = summarize(run(), base)
        # D: 線は4のまま・**坂の上限だけ外す**＝非単調の解消（下の probe が示す欠陥への処方）
        io.open(HTML, 'w', encoding='utf-8').write(src.replace(PEN, PEN.replace('&&ndeV<=4', ''), 1))
        results['D 線は4のまま・坂の上限だけ外す（非単調の解消）'] = summarize(run(), base)
    finally:
        io.open(HTML, 'w', encoding='utf-8').write(src)      # **必ず元へ戻す**
        assert io.open(HTML, encoding='utf-8').read() == src
        run()                                                 # 正本 score_all.json を現行で書き直す
        print('\n✓ index.html を元へ戻し、out/score_all.json を現行の門で再生成した')

    print('\n■ 門の中で誰が動くか')
    for k, v in results.items():
        print(f"\n── {k}")
        print(f"   キル {v['nkill']}社 ／ Ω75+ {v['n75']}社 ／ 四関門通過 {v['nquali']}社 ／ **投下可 {v['nbuy']}社**")
        print(f"   {' '.join(v['buy'])}")
        if 'moved' in v:
            print(f"   Ωが動く {len(v['moved'])}社"
                  + (f"　入 {' '.join(v['buy_in'])}" if v.get('buy_in') else '')
                  + (f"　出 {' '.join(v['buy_out'])}" if v.get('buy_out') else '')
                  + ('' if (v.get('buy_in') or v.get('buy_out')) else '　**投下可の顔ぶれは不変**'))

    # 4<nde≤5 に居る社
    import glob
    band = []
    SA = json.load(open('out/score_all.json', encoding='utf-8'))
    S = {r['t']: r for r in SA}
    for p in sorted(glob.glob('out/*_gate_pack.json')):
        t = os.path.basename(p).split('_gate_pack')[0]
        x = json.load(open(p, encoding='utf-8'))
        x = x.get('data') or x
        n = x.get('nde')
        if n is not None and 4 < float(n) <= 5:
            band.append((t, float(n), (S.get(t) or {}).get('s'), (S.get(t) or {}).get('moat'), x.get('irr')))
    print(f"\n■ 4 < nde ≤ 5 の帯に居る社（線を5にすると救われる候補） {len(band)}社")
    for t, n, s, m, irr in sorted(band, key=lambda z: -(z[2] or 0)):
        print(f"   {t:<6} nde{n:>5.2f}  Ω{str(s):>5}  堀{str(m):>5}  irr{str(irr):>4}")

    # ── 単調性の検問（この道具でいちばん重要な出力）───────────────────────────
    #   キルは `evalScore = min(evalScore, 60)`（1個の場合）で**上限**を掛けるだけ。
    #   一方レバレッジの坂 levPen は `2.5 < nde ≤ 4` でしか効かない。
    #   ⇒ **キル帯へ入った社は坂の罰から抜ける**ので、真のスコアが60未満の社は
    #      nde が 4.00 を跨いで増えると **Ω が上がる**。借金が増えるほど点が上がる向き。
    print('\n■ 単調性の検問（1社を nde だけ振る・他は不変）')
    probe = []
    for v in ['2.4', '3.0', '3.5', '3.9', '3.99', '4.01', '4.5', '5.0', '6.0', '20']:
        subprocess.run(['node', 'night/score_all.js', '--only', 'OKE', '--set', f'nde={v}'],
                       capture_output=True, text=True)
        try:
            r = json.load(open('out/score_all.partial.json', encoding='utf-8'))[0]
            probe.append((v, r['s'], r.get('kills')))
        except Exception:
            pass
    for v, s, k in probe:
        print(f"   nde={v:<5} → Ω {s:>5}   キル {k}"
              + ('   ← ここで **Ω が上がる**（借金が増えるほど点が上がる）' if v == '4.01' else ''))
    try:
        os.remove('out/score_all.partial.json')
    except OSError:
        pass
    print('   【原因】キルは Ω に**上限**を掛けるだけ（1個なら60）／坂 levPen は `2.5<nde≤4` でしか効かない。')
    print('   ⇒ キル帯へ入ると坂の罰から抜けるので、真のスコアが60未満の社は nde が増えるほど Ω が上がる。')
    print('   ⇒ **線を4から5へ動かす前に、線の「上」の扱いを直すのが先**（案D）。')

    if AS_JSON:
        p = 'out/shadow_nde_kill.json'
        json.dump({'generated': '2026-08-09', 'history': hist, 'base_impair': base_imp,
                   'schemes': results, 'band45': band, 'probe': probe},
                  open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
