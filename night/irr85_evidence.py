#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_evidence.py — **irr=85 の根拠そのものを測り直す**（2026-08-18新設）

【なぜ要るか】
  この台帳は13年の検証で「機械の指標は5系統・204通り・7アンカーすべて全滅、生き延びたのは
  原本読解の irr だけ」と繰り返し出し、その irr=85 に**二つの特権**（別枠85・席の優先）を与えている。
  ところが根拠として引かれ続けてきた「2018年ビンテージ **+24.6%/年・P=0.71**」という数字は、
  **一度も分解されていなかった**——標本が重複していないか／半導体に偏っていないか／
  読み手の水準が揃っているか。ユーザーの問い「irr85の銘柄たちは本当に信じれる？」で初めて数えた。

  **数えたものを道具にしないと、次に同じ問いが来たときまた手で計算し直すことになる**（この台帳が
  `base_rate_check.py` の「n=10」焼き付けで踏んだ型の予防）。だからここに置く。

【測るもの（すべて既存の在庫から・追加取得ゼロ）】
  1. **のべ件数 vs 実社数** —— 同じ社が複数ビンテージで数えられていないか
  2. **半導体連鎖を外すと何が残るか** —— P(年率15%+)・中央値・70との差・二項CI
  3. **irr=70 の安定性** —— 4つの切り方で動くか（85と対照）
  4. **AI相場の前だけの窓（2013-07→2016-06）** —— 交絡の外で刻みが立つか
  5. **読み手の水準ずれ** —— 同じ社を早期(2013/2015)と2018で読み比べる
  6. **格上げされた社は今日どう読まれているか** —— 根拠の出所が今日の基準で生き残るか

【限界（先に書く）】
  ・窓はすべて2026年で終わる＝終点の相場が全ビンテージに等しく乗る
  ・母集団は同じ956ティッカー＝真の out-of-sample はゼロ
  ・読解はLLM（人手の再現検定は irr で90.5%まで）／生存バイアスは既記録のまま
  ・**半導体連鎖の線は判断が入る**——STX(HDD)・COHR(光通信)は「半導体そのもの」ではなく
    AI設備投資の連鎖。だから**1社ずつSICつきで印字**し、`--semi` で引き直せるようにしてある

使い方: python3 night/irr85_evidence.py [--semi LRCX,ENTG,...] [--json]
出力  : out/irr85_evidence.json
"""
import json
import math
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'out')
HURDLE = 0.15          # 既存のハードル（新しい定数を作らない）
RUIN = -0.15           # 恒久毀損の線（既存）

# 読解の在庫（ビンテージ, ファイル, irrの欄, 前方リターンの在庫）
READS = [
    ('2013', ['retro_moat_2013.json', 'retro_moat_2013q.json'], 'irr', 'retro_returns_2013_all.json'),
    ('2015', ['retro_moat_2015.json', 'retro_moat_2015q.json', 'retro_moat_2015qb.json'], 'irr',
     ['retro_returns_2015_q.json', 'retro_returns_2015.json']),
    ('2018', ['retro_moat_2018.json'], 'irr18', 'retro_returns_2018.json'),
]
# ★半導体連鎖（判断が入る線なので**明示のリスト**にして1社ずつSICを印字する）。
#   装置・材料・検査・電子部品・光・HDD まで＝同じ設備投資サイクルに乗るか、で採る。
SEMI = ['LRCX', 'ENTG', 'MKSI', 'NVMI', 'AMAT', 'ADI', 'MPWR', 'NXPI',
        'IPGP', 'AEIS', 'OLED', 'COHR', 'APH', 'STX', 'ROG']


def jload(name):
    p = os.path.join(OUT, name)
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else None


def returns(spec):
    """{ticker: tr_cagr} を返す（複数在庫は先勝ち＝先に書いたほうが正）"""
    out = {}
    for nm in ([spec] if isinstance(spec, str) else spec):
        d = jload(nm) or {}
        for r in (d.get('rows') or []):
            t = r.get('ticker')
            if t and t not in out and r.get('tr_cagr') is not None:
                out[t] = float(r['tr_cagr'])
    return out


def wilson(k, n, z=1.96):
    """二項の Wilson 区間（0/nでも壊れない）"""
    if not n:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - r) / d), min(1.0, (c + r) / d))


def med(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def stat(rows):
    """rows=[(ticker, cagr)] → 件数・P(15%+)・中央値・恒久毀損"""
    n = len(rows)
    if not n:
        return dict(n=0, p15=None, med=None, ruin=None, ci=(None, None))
    k = sum(1 for _, c in rows if c >= HURDLE)
    return dict(n=n, p15=round(k / n, 3), med=round(med([c for _, c in rows]), 4),
                ruin=round(sum(1 for _, c in rows if c <= RUIN) / n, 3),
                ci=tuple(None if x is None else round(x, 3) for x in wilson(k, n)))


def load_reads():
    """[(vintage, ticker, rung, cagr)] を作る（のべ）"""
    recs, ret = [], {}
    for v, files, key, rspec in READS:
        ret[v] = returns(rspec)
        for f in files:
            d = jload(f)
            if not d:
                continue
            for x in (d.get('rows') or []):
                t = x.get('ticker') or x.get('t')
                rung = x.get(key)
                if not t or rung is None:
                    continue
                # 2018 の中間刻みは 75（2013/2015 は 70）——同じ「高摩擦移行困難」なので束ねて読む
                r = int(rung)
                c = ret[v].get(t)
                recs.append(dict(v=v, t=t, rung=r, mid=(r in (70, 75)), cagr=c))
    return recs, ret


def main():
    a = sys.argv[1:]
    semi = set(SEMI)
    if '--semi' in a:
        semi = {x.strip().upper() for x in a[a.index('--semi') + 1].split(',') if x.strip()}
    sic = {r['ticker']: r for r in ((jload('retro_sic.json') or {}).get('rows') or [])}
    recs, _ = load_reads()
    out = {'generated': '2026-08-18', 'hurdle': HURDLE, 'semi': sorted(semi),
           'note': 'irr=85 の根拠を分解して測り直す。値も規約も一切変えない（読むだけ）。'}

    # ── 1. のべ件数 vs 実社数 ──────────────────────────────
    print('■ 1. のべ件数 vs 実社数（同じ社が複数ビンテージで数えられていないか）')
    tot = Counter()
    byco = defaultdict(set)
    for r in recs:
        tot[r['rung']] += 1
        byco[r['rung']].add(r['t'])
    lines = []
    for rung in sorted(tot, reverse=True):
        dup = tot[rung] - len(byco[rung])
        lines.append(dict(rung=rung, readings=tot[rung], companies=len(byco[rung]), dup=dup))
        print(f'   irr={rung:3}  のべ {tot[rung]:4}件 → 実 **{len(byco[rung]):3}社**（重複 {dup}）')
    d85 = sorted(t for t in byco.get(85, set())
                 if sum(1 for r in recs if r['t'] == t and r['rung'] == 85) > 1)
    print(f'   ★irr=85 で複数回数えられている社: {" ".join(d85) or "—"}')
    out['dedup'] = dict(rows=lines, irr85_duplicated=d85)

    # ── 2. 半導体連鎖を外すと何が残るか ────────────────────
    print('\n■ 2. 半導体連鎖を外すと何が残るか（★この線は判断が入るので1社ずつSICを出す）')
    r85 = [r for r in recs if r['rung'] == 85 and r['cagr'] is not None]
    print('   irr=85 の全社:')
    for t in sorted({r['t'] for r in r85}):
        s = sic.get(t) or {}
        cg = [r['cagr'] for r in r85 if r['t'] == t]
        print(f'     {"◆半導体" if t in semi else "　　　　"} {t:6} '
              f'SIC{str(s.get("sic") or "—"):>5} {str(s.get("sicDesc") or "")[:30]:32}'
              f' 実現 {"/".join(f"{c*100:+.1f}%" for c in cg)}')
    cuts = {}
    for lab, sel in (('全部', lambda r: True),
                     ('半導体を外す', lambda r: r['t'] not in semi)):
        for rung, rlab in ((85, '85'), (None, '70/75')):
            rs = [(r['t'], r['cagr']) for r in recs if r['cagr'] is not None and sel(r)
                  and (r['rung'] == 85 if rung else r['mid'])]
            uq = [(t, med([c for tt, c in rs if tt == t])) for t in sorted({t for t, _ in rs})]
            cuts[f'{lab}/{rlab}'] = dict(のべ=stat(rs), 社単位=stat(uq))
    for lab in ('全部', '半導体を外す'):
        a85, a70 = cuts[f'{lab}/85'], cuts[f'{lab}/70/75']
        g = (a85['のべ']['p15'] or 0) - (a70['のべ']['p15'] or 0)
        gq = (a85['社単位']['p15'] or 0) - (a70['社単位']['p15'] or 0)
        print(f'\n   【{lab}】')
        print(f'     irr=85    のべ n={a85["のべ"]["n"]:3} P15={a85["のべ"]["p15"]} '
              f'中央値 {a85["のべ"]["med"]*100:+.1f}%  CI{a85["のべ"]["ci"]}  毀損{a85["のべ"]["ruin"]}')
        print(f'               社単位 n={a85["社単位"]["n"]:3} P15={a85["社単位"]["p15"]} '
              f'中央値 {a85["社単位"]["med"]*100:+.1f}%')
        print(f'     irr=70/75 のべ n={a70["のべ"]["n"]:3} P15={a70["のべ"]["p15"]} '
              f'中央値 {a70["のべ"]["med"]*100:+.1f}%  毀損{a70["のべ"]["ruin"]}')
        print(f'     ★85−70 の差: のべ **{g:+.2f}** ／ 社単位 **{gq:+.2f}**')
    out['semi_strip'] = cuts

    # ── 3. irr=70 の安定性（85との対照）──────────────────
    print('\n■ 3. irr の刻みは切り方で動くか（★70の安定性が対照になる）')
    tbl = []
    for lab, sel in (('全部', lambda r: True), ('半導体を外す', lambda r: r['t'] not in semi),
                     ('2013のみ', lambda r: r['v'] == '2013'), ('2015のみ', lambda r: r['v'] == '2015'),
                     ('2018のみ', lambda r: r['v'] == '2018')):
        row = {'cut': lab}
        for rung in (50, 'mid', 85, 100):
            rs = [(r['t'], r['cagr']) for r in recs if r['cagr'] is not None and sel(r)
                  and (r['mid'] if rung == 'mid' else r['rung'] == rung)]
            row[str(rung)] = stat(rs)
        tbl.append(row)
        f = lambda k: (f"{row[k]['p15']:.2f}({row[k]['n']})" if row[k]['n'] else '—')
        print(f'   {lab:12} 50 {f("50"):11} 70/75 {f("mid"):11} 85 {f("85"):11} 100 {f("100")}')
    print('   （括弧内はのべ件数。**70/75 はどの切り方でもほぼ動かない**のが85との違い）')
    for row in tbl:
        for rung in ('50', 'mid', '85', '100'):
            if row[rung]['n']:
                print(f'     {row["cut"]:12} irr={rung:4} 恒久毀損 {row[rung]["ruin"]}') if rung in ('mid', '85') else None
    out['stability'] = tbl

    # ── 4. AI相場の前だけの窓 ────────────────────────────
    print('\n■ 4. AI相場の前だけの窓（2013-07 → 2016-06・2.92年）')
    pre = returns('retro_returns_2013w.json')
    if pre:
        for rung, lab in ((50, '50'), ('mid', '70'), (85, '85'), (100, '100')):
            rs = [(r['t'], pre[r['t']]) for r in recs if r['v'] == '2013' and r['t'] in pre
                  and (r['mid'] if rung == 'mid' else r['rung'] == rung)]
            s = stat(rs)
            if s['n']:
                print(f'   irr={lab:4} n={s["n"]:3} P15={s["p15"]} 中央値 {s["med"]*100:+.1f}%  CI{s["ci"]}')
                out.setdefault('pre_ai', {})[lab] = s
        r85p = sorted([(r['t'], pre[r['t']]) for r in recs
                       if r['v'] == '2013' and r['rung'] == 85 and r['t'] in pre], key=lambda x: -x[1])
        print('   irr=85 の内訳: ' + ' ／ '.join(
            f'{t}{"◆" if t in semi else ""} {c*100:+.1f}%' for t, c in r85p))
        print('   ⚠ 2.92年の窓なので年率の分散が大きい。**方向の傍証**であって独立の証拠ではない')
    else:
        print('   （retro_returns_2013w.json が無い）')

    # ── 5. 読み手の水準ずれ ──────────────────────────────
    print('\n■ 5. 読み手の水準ずれ（同じ社を早期 2013/2015 と 2018 で読み比べる）')
    # ⚠**2018の中間刻みは 75、2013/2015 は 70**——同じ「高摩擦移行困難」なので
    #   揃えてから比べる。揃えないと 70↔75 が全部「不一致」に化け、一致率が嘘になる（実測 50.6%→）
    norm = lambda x: 70 if x in (70, 75) else x
    early, late = {}, {}
    for r in recs:
        d = early if r['v'] in ('2013', '2015') else late
        # 同じ社が2013と2015の両方で読まれていたら**高いほう**を採る＝格上げの数え方を保守側へ倒す
        d[r['t']] = max(norm(r['rung']), d.get(r['t'], 0))
    both = sorted(set(early) & set(late))
    up = [t for t in both if late[t] > early[t]]
    dn = [t for t in both if late[t] < early[t]]
    e85 = sum(1 for t in both if early[t] == 85)
    l85 = sum(1 for t in both if late[t] == 85)
    print(f'   両方で読まれた {len(both)}社  一致 {len(both)-len(up)-len(dn)}社'
          f'（{(len(both)-len(up)-len(dn))/max(1,len(both))*100:.1f}%）')
    print(f'   ★irr=85 の付与率: 早期 {e85}/{len(both)} = {e85/max(1,len(both))*100:.1f}%'
          f'  →  2018 {l85}/{len(both)} = {l85/max(1,len(both))*100:.1f}%'
          f'（**{l85/max(1,e85):.1f}倍**）')
    promo = sorted(t for t in both if late[t] == 85 and early[t] != 85)
    demo = sorted(t for t in both if early[t] == 85 and late[t] != 85)
    print(f'   85へ格上げ {len(promo)}社: {" ".join(promo) or "—"}')
    print(f'   85から降格 {len(demo)}社: {" ".join(demo) or "—"}  ← **降格がゼロなら「読み手が緩んだ」の署名**')
    # ★対照: **2013 vs 2015**（どちらも同じ刻み表・同じ作法）——ここが揃っていれば
    #   ずれているのは irr という欄ではなく **2018の班** だと言える
    v13, v15 = {}, {}
    for r in recs:
        if r['v'] == '2013':
            v13[r['t']] = max(norm(r['rung']), v13.get(r['t'], 0))
        elif r['v'] == '2015':
            v15[r['t']] = max(norm(r['rung']), v15.get(r['t'], 0))
    bb = sorted(set(v13) & set(v15))
    ag = sum(1 for t in bb if v13[t] == v15[t])
    a85, b85 = sum(1 for t in bb if v13[t] == 85), sum(1 for t in bb if v15[t] == 85)
    print(f'   ── 対照 2013 vs 2015（同じ刻み表・同じ作法）: 両方で読まれた {len(bb)}社  '
          f'一致 {ag}社（**{ag/max(1,len(bb))*100:.1f}%**）  '
          f'85の付与率 {a85/max(1,len(bb))*100:.1f}% → {b85/max(1,len(bb))*100:.1f}%')
    print('   ⇒ 対照が高いのに 2018 との一致が低いなら、揺れているのは**欄ではなく2018の班**')
    out['reader_shift'] = dict(n_both=len(both), agree=len(both) - len(up) - len(dn),
                               early85=e85, late85=l85, promoted=promo, demoted=demo,
                               control_1315=dict(n=len(bb), agree=ag, e85=a85, l85=b85))

    # ── 6. 格上げされた社は今日どう読まれているか ────────────
    print('\n■ 6. 格上げされた社を**今日の台帳**で引き直す（根拠が今日の基準で生き残るか）')
    today = {}
    for f in os.listdir(OUT):
        if f.endswith('_gate_pack.json'):
            try:
                d = json.load(open(os.path.join(OUT, f), encoding='utf-8'))
            except Exception:
                continue
            today[f[:-len('_gate_pack.json')]] = d.get('irr')
    keep, back, none = [], [], []
    for t in promo:
        v = today.get(t)
        (none if v is None else (keep if int(v) == 85 else back)).append(
            t if v is None else f'{t}({int(v)})')
    print(f'   今日も 85 のまま: **{len(keep)}社** {" ".join(keep) or "—"}')
    print(f'   今日は下がっている: **{len(back)}社** {" ".join(back) or "—"}')
    print(f'   今日の台帳に無い: {len(none)}社 {" ".join(none) or "—"}')
    print('   ⇒ 格上げが今日の基準で生き残らないなら、その読みから出た数字を根拠に使えない')
    out['promoted_today'] = dict(kept85=keep, downgraded=back, absent=none)

    json.dump(out, open(os.path.join(OUT, 'irr85_evidence.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('\n→ out/irr85_evidence.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
