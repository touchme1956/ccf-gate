#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/castle_correlation.py — **城の銘柄が同時に壊れるかを測る**（2026-08-11新設）

■ なぜ要るか
  門は1銘柄の上限を8%（¼ケリー）で厳密に守るのに、**束では一度も見ていなかった**。
  実測（2026-08-11の目標配分）: 城15社のうち **半導体連鎖5社=城の31.1% / 航空・防衛4社=城の31.5%**、
  **2つで城の62.6%**。半導体には上限（城の30%・v9.9.117）を作ったのに、
  **同じ大きさの航空・防衛には上限も監視も無い**。
  そして「同じ束か」を判断する材料が**業種のラベルしか無かった**——
  ラベルは人が貼るもので、相関は市場が決める。**測っていないものを上限で縛っていた。**

■ 何を測るか（新しい定数も新しい判定も作らない）
  月次リターン（Yahoo adjclose＝配当込み・`retro_fetch_returns.py` と同じ一本の source）から
    (1) 各ペアの相関係数
    (2) **下げ相場だけの相関**（市場が下げた月に限った相関）＝『同時に壊れるか』の本体。
        平常時の相関より下げ相場の相関のほうが高いのが普通で、**その差が集中の代金**
    (3) 束ごと（半導体／航空防衛／その他）の平均相関と、束をまたぐ平均相関
    (4) **実効銘柄数** N_eff = 1 / Σ(w_i w_j ρ_ij)（等ウェイトなら分散から逆算した「実質何銘柄か」）
  **判定はしない**——上限も線も置かない。相関は測ってから議論するもので、
  この道具が出すのは数字だけ。配分は門の外（DCA側の決断）。

■ ⚠ 限界（先に書く）
  ・**過去の相関は将来の相関ではない**。とくに相関は危機で1へ寄る（測っている窓に危機が無ければ
    その性質は見えない）。この道具が使える窓は Yahoo の履歴の範囲＝多くて十数年。
  ・**上場が新しい社は測れない**（LOAR 2024年IPO・KRMN 2025年IPO）＝穴として明示する。
  ・相関は**同時に落ちる度合い**であって**同時に壊れる度合い**ではない。恒久毀損の相関は
    n が小さすぎて測れない（歴史側の irr=85 の恒久毀損は n=10 で 1件）。

使い方:
  python3 night/castle_correlation.py              城（席10＋門外例外）を測る
  python3 night/castle_correlation.py --years 5    窓を変える（既定10年）
  python3 night/castle_correlation.py --json       out/castle_correlation.json を書く
"""
import datetime
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import px_guard as PXG   # noqa: E402  株価履歴の検問（短い応答を採らない・2026-09-23）

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

AS_JSON = '--json' in sys.argv[1:]
YEARS = 10
for i, a in enumerate(sys.argv):
    if a == '--years' and i + 1 < len(sys.argv):
        YEARS = int(sys.argv[i + 1])

UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}
T1 = int(time.time())
T0 = int((datetime.datetime.now() - datetime.timedelta(days=365 * YEARS + 40)).timestamp())

# 束のラベル（v9.9.117 の SEMI と同じ集合＋航空防衛）。**ラベルは仮説であって答えではない**
#   ——この道具はラベルどおりに相関しているかを検算するために置く。
SEMI = {'ASML', 'LRCX', 'KLAC', 'MKSI', 'ENTG'}
AERO = {'CW', 'RBC', 'TDG', 'HWM'}


def fetch(sym):
    url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}'
           f'?period1={T0}&period2={T1}&interval=1mo')
    for k in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                j = json.loads(r.read())
            res = (j.get('chart', {}).get('result') or [None])[0]
            if not res:
                return None
            ts = res.get('timestamp') or []
            adj = ((res.get('indicators', {}).get('adjclose') or [{}])[0].get('adjclose')) or []
            pts = [(t, v) for t, v in zip(ts, adj) if v is not None]
            return PXG.vet(sym, pts, 'castle_correlation.fetch', req_start=T0) or None  # ★px_guard: 台帳より遅く始まる応答は採らない（2026-09-23）
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 * (k + 1))
        except Exception:
            time.sleep(2 * (k + 1))
    return None


def monthly(pts):
    """{年月: 月次リターン}。**同じ月の重複は捨てる**（分割・再上場で稀に起きる）"""
    px = {}
    for t, v in pts:
        px[datetime.datetime.utcfromtimestamp(t).strftime('%Y-%m')] = v
    ks = sorted(px)
    return {ks[i]: px[ks[i]] / px[ks[i - 1]] - 1
            for i in range(1, len(ks)) if px[ks[i - 1]]}


def corr(a, b):
    ks = sorted(set(a) & set(b))
    if len(ks) < 24:                      # 2年未満は相関を出さない（雑音しか出ない）
        return None, len(ks)
    x = [a[k] for k in ks]; y = [b[k] for k in ks]
    mx = sum(x) / len(x); my = sum(y) / len(y)
    sx = math.sqrt(sum((v - mx) ** 2 for v in x)); sy = math.sqrt(sum((v - my) ** 2 for v in y))
    if sx == 0 or sy == 0:
        return None, len(ks)
    return round(sum((x[i] - mx) * (y[i] - my) for i in range(len(x))) / (sx * sy), 3), len(ks)


def main():
    rows = json.load(open('out/score_all.json', encoding='utf-8'))
    ex = json.load(open('gate_exceptions.json', encoding='utf-8'))['items']
    seats = [r['t'] for r in rows if r.get('buy')]
    names = seats + [x['t'] for x in ex]
    print(f'■ 城の相関 — **同時に落ちるか**を測る（判定はしない・配分は門の外）')
    print(f'  対象 {len(names)}社（席{len(seats)} ＋ 門外例外{len(ex)}）／窓 {YEARS}年・月次・配当込み\n')

    ser, miss = {}, []
    for t in names:
        sym = (t + '.T') if t.isdigit() else t
        p = fetch(sym)
        m = monthly(p) if p else {}
        if len(m) < 24:
            miss.append((t, f'月次が{len(m)}ヶ月＝2年未満（上場が新しい/取得不能）'))
            continue
        ser[t] = m
    # 市場（SPY）——下げ相場の切り出しに使う。取れなければ等ウェイト平均で代用
    spy = monthly(fetch('SPY') or [])
    mk = spy if len(spy) >= 24 else None

    ok = sorted(ser)
    pairs = {}
    for i, a in enumerate(ok):
        for b in ok[i + 1:]:
            c, n = corr(ser[a], ser[b])
            if c is not None:
                pairs[f'{a}|{b}'] = dict(rho=c, n=n)

    def grp(t):
        return 'semi' if t in SEMI else ('aero' if t in AERO else 'other')

    def avg(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 3) if v else None

    within, across = {}, []
    for k, v in pairs.items():
        a, b = k.split('|')
        ga, gb = grp(a), grp(b)
        if ga == gb:
            within.setdefault(ga, []).append(v['rho'])
        else:
            across.append(v['rho'])

    print('  ── 束の中と、束をまたぐ平均相関 ──')
    for g, lbl in (('semi', '半導体連鎖'), ('aero', '航空・防衛'), ('other', 'その他')):
        n = sum(1 for t in ok if grp(t) == g)
        print(f'   {lbl:<6s} {n}社  束の中の平均 ρ = {avg(within.get(g, [])) if within.get(g) else "—"}')
    print(f'   束をまたぐ平均 ρ = {avg(across)}')

    # ── 下げ相場での挙動（『同時に壊れるか』の本体）───────────────────────────
    #   ⚠**条件付き相関はそのまま読んではいけない**（Forbes-Rigobon の指摘）——
    #   市場の向きで月を選ぶと共通因子の分散が切り詰められ、**相関は機械的に下がる**。
    #   実測でもそうなった（全期間 0.374 → 下げ月 0.309）が、これは
    #   「下げでは分散が効く」という発見ではなく**測り方の産物**。数字は出すが読み方を添える。
    #   代わりに**符号の統計**を主に見る——最悪の月に**何割のペアが揃って下げたか**。
    #   これは条件付けの切り詰めを受けにくく、『同時に壊れるか』に直接答える。
    down = down_note = None
    codrop = worst = None
    if mk:
        dm = {k for k, v in mk.items() if v < 0}
        dser = {t: {k: v for k, v in s.items() if k in dm} for t, s in ser.items()}
        dp = []
        for i, a in enumerate(ok):
            for b in ok[i + 1:]:
                c, n = corr(dser[a], dser[b])
                if c is not None:
                    dp.append(c)
        down = avg(dp)
        allr = avg([v['rho'] for v in pairs.values()])
        down_note = ('条件付き相関は共通因子の分散が切り詰められるため機械的に下がる'
                     '（Forbes-Rigobon）。全期間との差を「分散が効いた/効かない」と読まないこと')
        print(f'\n  ── 下げ相場（市場が下げた {len(dm)}ヶ月）──')
        print(f'   参考: 全ペア平均 ρ  全期間 {allr} → 下げ月 {down}')
        print('   ⚠**この差を読まないこと**——市場の向きで月を選ぶと共通因子の分散が切り詰められ、')
        print('     相関は**機械的に下がる**（Forbes-Rigobon）。下げで分散が効いた証拠ではない。')
        # 最悪の月（市場の下位10%）で、揃って下げたペアの割合＝符号の統計
        wm = sorted(mk, key=lambda k: mk[k])[:max(3, len(mk) // 10)]
        worst = [(k, round(mk[k] * 100, 1)) for k in wm]
        tot = hit = 0
        for k in wm:
            for i, a in enumerate(ok):
                for b in ok[i + 1:]:
                    va, vb = ser[a].get(k), ser[b].get(k)
                    if va is None or vb is None:
                        continue
                    tot += 1
                    if va < 0 and vb < 0:
                        hit += 1
        codrop = round(hit / tot, 3) if tot else None
        print(f'\n   **最悪の {len(wm)}ヶ月で、揃って下げたペアの割合 = {codrop:.0%}**'
              if codrop is not None else '')
        print('     （符号の統計＝条件付けの切り詰めを受けにくい。'
              '完全に独立なら約25%・完全に一蓮托生なら100%）')
        print('     対象の月: ' + ' / '.join(f'{k}({v:+.1f}%)' for k, v in worst))

    # 実効銘柄数（等ウェイト前提）: N_eff = n^2 / ΣΣρ_ij
    n = len(ok)
    if n >= 2:
        s = float(n)                      # 対角は 1
        for v in pairs.values():
            s += 2 * v['rho']
        neff = round(n * n / s, 1) if s > 0 else None
        print(f'\n  ── 実効銘柄数（等ウェイト・N_eff = n²/ΣΣρ）──')
        print(f'   名目 {n}社 → **実効 {neff}社**（相関を差し引くと実質これだけの分散しかない）')
    else:
        neff = None

    # 最も強い/弱いペア
    top = sorted(pairs.items(), key=lambda kv: -kv[1]['rho'])[:6]
    bot = sorted(pairs.items(), key=lambda kv: kv[1]['rho'])[:4]
    print('\n  ── 最も一緒に動くペア ──')
    for k, v in top:
        a, b = k.split('|')
        print(f'   {a:<6s}{b:<6s} ρ={v["rho"]:+.3f}  ({grp(a)}/{grp(b)}・{v["n"]}ヶ月)')
    print('  ── 最も別々に動くペア ──')
    for k, v in bot:
        a, b = k.split('|')
        print(f'   {a:<6s}{b:<6s} ρ={v["rho"]:+.3f}  ({grp(a)}/{grp(b)}・{v["n"]}ヶ月)')

    if miss:
        print(f'\n  ⚠測れない {len(miss)}社（穴として明示する・黙って対象外にしない）:')
        for t, w in miss:
            print(f'   {t:<6s} {w}')

    if AS_JSON:
        p = 'out/castle_correlation.json'
        json.dump(dict(generated=str(datetime.date.today()), years=YEARS,
                       note=('城の銘柄の月次相関（Yahoo adjclose・配当込み）。**判定には一切使わない**'
                             '——上限も線も置かない。相関は測ってから議論するもので、'
                             '配分は門の外（DCA側の決断）。⚠過去の相関は将来の相関ではなく、'
                             '危機では1へ寄る。窓に危機が無ければその性質は見えない。'),
                       names=names, measured=ok, unmeasured=[dict(t=t, why=w) for t, w in miss],
                       within=({g: avg(v) for g, v in within.items()}), across=avg(across),
                       all_rho=avg([v['rho'] for v in pairs.values()]), down_rho=down,
                       down_rho_caveat=down_note, worst_months=worst, codrop_worst=codrop,
                       n_eff=neff, n_eff_note=('等ウェイト・等ボラティリティを仮定した近似'
                                               ' N_eff = n²/ΣΣρ。実際のボラの差は織り込まない'),
                       pairs=pairs),
                  open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
