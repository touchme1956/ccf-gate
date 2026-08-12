#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/v11_backtest.py — **V11_SPEC.md の「切替の条件」1〜3 を歴史パネルで実測する**

判定の線は一つも発明していない。すべて `V11_SPEC.md` の表と、この repo が既に持つ定数
（win=+15% / destroy=−15% / 質実証 / irr の刻み / intcov<3 / nde>4）から読む。
**この道具は合否を宣言する。だが正本は一切触らない**（v11 は影・切替はユーザーの明示指示）。

母集団: `out/hist_wd_panel.json` の **2016 / 2017 / 2018** ビンテージ
  （f2_ 系＝提出日で厳密に切った特徴量が在るのはこの3つだけ。intcov もここにしか無い）。

**look-ahead を構造で防ぐ**: irr の読解は 2013/2015/2018 にしか無いので、欠けるビンテージには
`irr_near` を使う。ただし **`irr_near_src <= vintage` のものだけ**——2016年の行に2018年の読解を
当てるのは後知恵（パネルには実際に 34行 混じっている）。

【この検定で言えることの射程（先に書く）】
  ・歴史パネルに **Ω は再構成できない**（定性11欄が当時の原本で採点されていない）。
    よって比較できるのは**両門の機械部分だけ**。
  ・`dep` / `erosion` / `disrupt` は歴史側に無い＝層2の5本のうち**3本は検定不能**。
    これらは v9 から持ち込んだ既存の関門で v11 の新規主張ではないが、増分は測れない。
  ・**3ビンテージは同じ 956 ティッカー**（Jaccard 1.00）・窓は 2018-2026 を共有＝**out-of-sample はゼロ**。
    よって「ビンテージ3つで一致」は独立な3つの証拠ではない。**per-vintage を必ず併記する**。
  ・層0（質実証）は 2016-2018 では **op_all_pos を欠く2条件**（パネルの known_asymmetries）。
    比較する両門に**同じ**層0を当てるので head-to-head は公平だが、水準は規約より緩い。

使い方: python3 night/v11_backtest.py [--json]
出力: out/v11_backtest.json
"""
import json
import math
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

WIN, DESTROY = 0.15, -0.15
VINT = (2016, 2017, 2018)
INTCOV_LINE = 3.0        # V11_SPEC 層2
NDE_KILL = 4.0           # v9 の財務キル


def med(a):
    a = sorted(a)
    n = len(a)
    return None if not n else (a[n // 2] if n % 2 else (a[n // 2 - 1] + a[n // 2]) / 2)


def stats(rows):
    r = [x for x in rows if x.get('tr_cagr') is not None]
    n = len(r)
    if not n:
        return {'n': 0}
    tr = [x['tr_cagr'] for x in r]
    return {'n': n,
            'median': round(med(tr) * 100, 2),
            'mean': round(sum(tr) / n * 100, 2),
            'p_win': round(sum(1 for v in tr if v >= WIN) / n, 3),
            'n_win': sum(1 for v in tr if v >= WIN),
            'p_destroy': round(sum(1 for v in tr if v <= DESTROY) / n, 3),
            'n_destroy': sum(1 for v in tr if v <= DESTROY),
            'worst': round(min(tr) * 100, 2)}


def boot_diff(a, b, f, iters=2000, seed=20260812):
    """f(群) の差 (a−b) のブートストラップ95%区間。行は独立でない（同じティッカーが
       3ビンテージに出る）ので**これは楽観的な区間**——per-vintage を必ず併読すること。"""
    rnd = random.Random(seed)
    if not a or not b:
        return None
    d = []
    for _ in range(iters):
        sa = [a[rnd.randrange(len(a))] for _ in range(len(a))]
        sb = [b[rnd.randrange(len(b))] for _ in range(len(b))]
        va, vb = f(sa), f(sb)
        if va is not None and vb is not None:
            d.append(va - vb)
    d.sort()
    if not d:
        return None
    return [round(d[int(.025 * len(d))], 4), round(d[int(.975 * len(d))], 4)]


def irr_eff(x):
    """look-ahead を含まない有効 irr。直接の読解を優先し、無ければ**過去のビンテージの**読解だけを使う。"""
    if x.get('irr') is not None:
        return x['irr'], 'direct'
    src = x.get('irr_near_src')
    if x.get('irr_near') is not None and src is not None and int(src) <= int(x['vintage']):
        return x['irr_near'], f'near{src}'
    return None, None


def mech(v):
    """V11_SPEC 層1 の A/B/C。v9 の irr=85/70(75)/50 と一対一。"""
    if v is None:
        return None
    v = int(v)
    if v >= 85:
        return 'A'
    if v >= 70:
        return 'B'
    return 'C'


def load():
    d = json.load(open('out/hist_wd_panel.json', encoding='utf-8'))
    rows = []
    for x in d['rows']:
        if x.get('vintage') not in VINT or not x.get('has_outcome'):
            continue
        v, src = irr_eff(x)
        x = dict(x)
        x['_irr'] = v
        x['_irr_src'] = src
        x['_mech'] = mech(v)
        rows.append(x)
    return rows


def L0(x):
    """層0 土俵。パネルの P_quality（2016-2018 は op_all_pos を欠く2条件）"""
    return x.get('P_quality') is True


def L2_shrink(x):
    """事業の収縮（v9.9.99 と同一）。**測れない社は落とさない**（v9 の実装と同じく空欄は非発火）"""
    return (x.get('f2_cagr5') is not None and x['f2_cagr5'] < 0
            and x.get('f2_opmD5') is not None and x['f2_opmD5'] < 0)


def L2_fin_v11(x):
    """v11 の金利負担。**測れないものは通さない**（未測定は安全ではない・ルール7）。
       返り値: True=通す / False=止める / None=未測定（＝止める側だが理由が違う）"""
    ic = x.get('f2_intcov')
    if ic is None:
        return None
    return ic >= INTCOV_LINE


def main():
    rows = load()
    out = {'generated': time.strftime('%Y-%m-%d'), 'tool': 'night/v11_backtest.py',
           'spec': 'V11_SPEC.md（切替の条件1〜3・測る前に固定・commit 7e3c6a6）',
           'hurdles': {'win': WIN, 'destroy': DESTROY, 'intcov_line': INTCOV_LINE, 'nde_kill': NDE_KILL},
           'scope_limits': [
               '歴史パネルに Ω は再構成できない＝比較できるのは両門の機械部分だけ',
               'dep/erosion/disrupt は歴史に無い＝層2の5本のうち3本は検定不能',
               '3ビンテージは同じ956ティッカー・窓は2018-2026を共有＝out-of-sample はゼロ',
               '層0は2016-2018では op_all_pos を欠く2条件（両門に同じものを当てるので head-to-head は公平）'],
           'coverage': {}, 'C1_layers': {}, 'C2_financial': {}, 'C3_deletion': {}}

    for v in VINT:
        g = [x for x in rows if x['vintage'] == v]
        out['coverage'][str(v)] = {
            'n': len(g), 'L0': sum(1 for x in g if L0(x)),
            'irr_direct': sum(1 for x in g if x['_irr_src'] == 'direct'),
            'irr_near_past': sum(1 for x in g if x['_irr_src'] and x['_irr_src'] != 'direct'),
            'irr_none': sum(1 for x in g if x['_irr'] is None),
            'intcov': sum(1 for x in g if x.get('f2_intcov') is not None)}

    # ── 条件1: 層ごとに増分があるか ─────────────────────────────────
    def c1(g, label):
        s0 = [x for x in g if L0(x)]
        s1 = [x for x in s0 if x['_mech'] in ('A', 'B')]
        s1a = [x for x in s0 if x['_mech'] == 'A']
        s2 = [x for x in s1 if not L2_shrink(x) and L2_fin_v11(x) is True]
        rec = {'母集団': stats(g), '層0 土俵': stats(s0),
               '層0∧層1(A/B)': stats(s1), '（参考）層0∧機構A のみ': stats(s1a),
               '層0∧1∧2 = v11': stats(s2)}
        # 層1・層2 の増分（前段との差）
        rec['増分'] = {}
        for a, b, nm in (('層0 土俵', '母集団', '層0'), ('層0∧層1(A/B)', '層0 土俵', '層1'),
                         ('層0∧1∧2 = v11', '層0∧層1(A/B)', '層2')):
            A, B = rec[a], rec[b]
            if A['n'] and B['n']:
                rec['増分'][nm] = {'Δ恒久毀損pt': round((A['p_destroy'] - B['p_destroy']) * 100, 2),
                                   'Δ中央値pt': round(A['median'] - B['median'], 2),
                                   'ΔP(勝)pt': round((A['p_win'] - B['p_win']) * 100, 2),
                                   'n': A['n']}
        return rec

    out['C1_layers']['pooled(3ビンテージ・重複あり)'] = c1(rows, 'pooled')
    for v in VINT:
        out['C1_layers'][str(v)] = c1([x for x in rows if x['vintage'] == v], str(v))

    # ── 条件2: 財務の物差しの交換（nde>4 vs intcov<3）─────────────────
    #   nde が採れるのは 2018年ビンテージだけ（retro_features_2018.json の nde18）
    nde = {}
    try:
        for x in json.load(open('out/retro_features_2018.json', encoding='utf-8'))['rows']:
            if x.get('nde18') is not None:
                nde[x['ticker']] = x['nde18']
    except Exception as e:
        out['C2_financial']['error'] = f'nde18 を読めない: {e}'

    base = [x for x in rows if x['vintage'] == 2018 and L0(x) and x['_mech'] in ('A', 'B')]
    both = [x for x in base if x['ticker'] in nde and x.get('f2_intcov') is not None]
    def split(g, pred):
        st = [x for x in g if pred(x)]
        pa = [x for x in g if not pred(x)]
        return {'止めた': stats(st), '通した': stats(pa),
                '濃縮(止/通)': (round(stats(st)['p_destroy'] / stats(pa)['p_destroy'], 2)
                               if stats(st).get('n') and stats(pa).get('p_destroy') else None),
                '止めた側の中央値は低いか': (None if not (stats(st)['n'] and stats(pa)['n'])
                                            else stats(st)['median'] < stats(pa)['median'])}
    out['C2_financial']['母集団'] = {'説明': '2018年ビンテージ・層0∧層1(A/B)・nde と intcov が両方採れる行',
                                     'n_層0∧層1': len(base), 'n_両方採れる': len(both),
                                     '欠測で落ちた': len(base) - len(both)}
    if both:
        out['C2_financial']['v9  nde>4 のキル'] = split(both, lambda x: nde[x['ticker']] > NDE_KILL)
        out['C2_financial']['v11 intcov<3 の関門'] = split(both, lambda x: x['f2_intcov'] < INTCOV_LINE)
        # 線の感度（発明ではなく、実測の帯をなぞる）
        out['C2_financial']['線の感度(intcov)'] = {
            str(L): split(both, lambda x, L=L: x['f2_intcov'] < L) for L in (1, 2, 3, 5)}
        # 広い母集団（層0のみ）でも見る——判定圏に絞ると事象が枯れるため
        wide = [x for x in rows if x['vintage'] == 2018 and L0(x)
                and x['ticker'] in nde and x.get('f2_intcov') is not None]
        out['C2_financial']['（参考）層0のみの広い母集団'] = {
            'n': len(wide),
            'v9  nde>4': split(wide, lambda x: nde[x['ticker']] > NDE_KILL),
            'v11 intcov<3': split(wide, lambda x: x['f2_intcov'] < INTCOV_LINE)}

    # ── 条件3: 削除は支持されるか（降ろした堀の欄を戻すと改善するか）──────
    def c3(g, label):
        v11 = [x for x in g if L0(x) and x['_mech'] in ('A', 'B')
               and not L2_shrink(x) and L2_fin_v11(x) is True]
        withm = [x for x in v11 if x.get('moat5') is not None and x['moat5'] >= 4]
        nom = [x for x in v11 if x.get('moat5') is not None and x['moat5'] < 4]
        rec = {'v11 のまま': stats(v11),
               '＋主観の堀 moat5≥4 を要求': stats(withm),
               '（対照）moat5<4': stats(nom),
               'moat5 が測れている行': sum(1 for x in v11 if x.get('moat5') is not None)}
        a, b = rec['＋主観の堀 moat5≥4 を要求'], rec['v11 のまま']
        if a['n'] and b['n']:
            rec['戻すと改善するか'] = {
                'Δ恒久毀損pt': round((a['p_destroy'] - b['p_destroy']) * 100, 2),
                'Δ中央値pt': round(a['median'] - b['median'], 2),
                '結論': ('改善する＝削除は誤り'
                         if (a['p_destroy'] < b['p_destroy'] and a['median'] > b['median'])
                         else '改善しない＝削除は支持される')}
        return rec

    out['C3_deletion']['pooled'] = c3(rows, 'pooled')
    for v in VINT:
        out['C3_deletion'][str(v)] = c3([x for x in rows if x['vintage'] == v], str(v))

    # ── 層2 は何を落としているのか（自分の設計にいちばん不利な診断を、自分で出す）──
    #   関門は「止めた社数」ではなく「止めた理由の内訳」で裁く。**未測定で落ちているなら
    #   それは risk のふるいではなく被覆のふるい**で、名前を偽っていることになる。
    s1 = [x for x in rows if L0(x) and x['_mech'] in ('A', 'B')]
    drop = {'未測定(intcov が採れない)': [], 'intcov<3': [], '事業の収縮': []}
    for x in s1:
        f = L2_fin_v11(x)
        if f is None:
            drop['未測定(intcov が採れない)'].append(x)
        elif f is False:
            drop['intcov<3'].append(x)
        elif L2_shrink(x):
            drop['事業の収縮'].append(x)
    out['C1_layers']['層2 が落とした理由の内訳'] = {
        '層0∧層1 の母数': len(s1),
        '通した': len(s1) - sum(len(v) for v in drop.values()),
        **{k: {**stats(v), '毀損の実数': stats(v).get('n_destroy')} for k, v in drop.items()},
        '所見': ('未測定で落ちる社数 > 線で落ちる社数 なら、層2は risk のふるいではなく'
                 '被覆のふるいとして働いている＝名前を偽っている')}

    # 上の診断を受けた反実仮想（**結果を見た後に足した検定**なので、その旨を出力に残す）:
    #   「未測定は通さない」をやめ「未測定は通す（穴として記録）」にしたら何が変わるか。
    #   利息の年次タグが無い社の大半は**無借金**（利息を報告しない）であり、
    #   採取器 hachimon_fetch の debt_evidence() が確立した作法＝
    #   「痕跡がゼロのときだけ debt=0 を事実とする」に照らせば、拒否ではなく通すのが筋。
    def c1b(g):
        s0 = [x for x in g if L0(x)]
        s1 = [x for x in s0 if x['_mech'] in ('A', 'B')]
        s2 = [x for x in s1 if not L2_shrink(x) and L2_fin_v11(x) is not False]
        return {'層0∧1∧2(未測定は通す)': stats(s2),
                '層0∧1∧2(未測定は通さない・仕様どおり)': stats(
                    [x for x in s1 if not L2_shrink(x) and L2_fin_v11(x) is True])}
    out['C1_layers']['反実仮想: 未測定の扱い（事後に足した検定）'] = {
        'pooled': c1b(rows), **{str(v): c1b([x for x in rows if x['vintage'] == v]) for v in VINT}}

    # ── 判定 ──────────────────────────────────────────────────
    ver = {}
    p = out['C1_layers']['pooled(3ビンテージ・重複あり)']['増分']
    ver['条件1 層ごとの増分'] = {}
    for k, d in p.items():
        ok = d['Δ恒久毀損pt'] <= 0.0 and d['Δ中央値pt'] >= 0.0
        ver['条件1 層ごとの増分'][k] = {'合否': '✓' if ok else '✗', **d}
    ver['条件1 判定'] = ('✓' if all(v['合否'] == '✓' for k, v in ver['条件1 層ごとの増分'].items())
                         else '✗（増分ゼロの層は v11 自身から落とす）')
    if both:
        a = out['C2_financial']['v11 intcov<3 の関門']
        b = out['C2_financial']['v9  nde>4 のキル']
        nd = a['止めた']['n_destroy'] + a['通した']['n_destroy']
        if nd == 0:
            # **到達不能**——事前登録した母集団に恒久毀損が1社も居ないので、
            #   どちらの物差しが左尾を分けるかを原理的に決められない。
            #   ⚠これは v11 の負けではなく**私の事前登録の欠陥**（v1 hist_val で踏んだのと同じ型:
            #   「合否基準が母集団の稀少事象の実数で到達可能か」を結果を見る前に数えていなかった）。
            #   ついでに、この 0件 自体が独立な発見でもある——**層0∧層1 を通った群には左尾が残っていない**
            #   （`hist_wd_verify_destroy.py` の「増分0.0」と同じことを別の道で再現した）。
            w = out['C2_financial'].get('（参考）層0のみの広い母集団') or {}
            ver['条件2 財務の物差しの交換'] = {
                '合否': '判定不能',
                '理由': f'事前登録した母集団（2018・層0∧層1・n={len(both)}）に恒久毀損が0社＝'
                        'どちらの物差しでも濃縮が定義できない。事前登録の欠陥（到達可能性を先に数えていない）',
                '独立な含意': '層0∧層1 を通った群には、層2 が捕まえるべき左尾がそもそも残っていない',
                '（事後・仕様文が母集団を特定していなかったための別読み）層0のみ': {
                    'n': w.get('n'),
                    'v9 nde>4 の濃縮': (w.get('v9  nde>4') or {}).get('濃縮(止/通)'),
                    'v11 intcov<3 の濃縮': (w.get('v11 intcov<3') or {}).get('濃縮(止/通)'),
                    '⚠': '結果を見た後に選んだ読みなので、v11 の合格の根拠にはしない'}}
        else:
            ok = (a['濃縮(止/通)'] is not None and b['濃縮(止/通)'] is not None
                  and a['濃縮(止/通)'] > b['濃縮(止/通)'] and a['止めた側の中央値は低いか'] is True)
            ver['条件2 財務の物差しの交換'] = {'合否': '✓' if ok else '✗',
                                              'v11濃縮': a['濃縮(止/通)'], 'v9濃縮': b['濃縮(止/通)'],
                                              'v11の止めた側の中央値は低いか': a['止めた側の中央値は低いか']}
    ver['条件3 削除の妥当性'] = out['C3_deletion']['pooled'].get('戻すと改善するか', {})
    out['verdict'] = ver
    json.dump(out, open('out/v11_backtest.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    if '--json' in sys.argv:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0

    P = out['C1_layers']['pooled(3ビンテージ・重複あり)']
    print('■ 条件1 — 層ごとに増分があるか（pooled 2016/2017/2018・⚠同じ956社が重複）')
    print(f"  {'':<22}{'n':>5}{'中央値':>8}{'P(勝)':>7}{'恒久毀損':>9}{'最悪':>8}")
    for k in ('母集団', '層0 土俵', '層0∧層1(A/B)', '（参考）層0∧機構A のみ', '層0∧1∧2 = v11'):
        s = P[k]
        if not s['n']:
            continue
        print(f"  {k:<22}{s['n']:>5}{s['median']:>7.1f}%{s['p_win']:>7.2f}{s['p_destroy']:>9.3f}{s['worst']:>7.0f}%")
    for k, d in P['増分'].items():
        print(f"    増分 {k}: Δ恒久毀損 {d['Δ恒久毀損pt']:+.2f}pt / Δ中央値 {d['Δ中央値pt']:+.2f}pt / ΔP(勝) {d['ΔP(勝)pt']:+.1f}pt")
    print('  ビンテージ別（独立ではない）:')
    for v in VINT:
        s = out['C1_layers'][str(v)]['層0∧1∧2 = v11']
        b = out['C1_layers'][str(v)]['母集団']
        if s['n']:
            print(f"    {v}: v11 n={s['n']:>3} 中央値{s['median']:>6.1f}% 毀損{s['p_destroy']:.3f}"
                  f"  ／ 母集団 n={b['n']} 中央値{b['median']:.1f}% 毀損{b['p_destroy']:.3f}")

    if both:
        print('\n■ 条件2 — 財務の物差しの交換（2018年ビンテージ・層0∧層1・n=%d）' % len(both))
        for nm in ('v9  nde>4 のキル', 'v11 intcov<3 の関門'):
            d = out['C2_financial'][nm]
            st, pa = d['止めた'], d['通した']
            print(f"  {nm:<20} 止めた n={st['n']:>3} 中央値{st['median']:>6.1f}% 毀損{st['p_destroy']:.3f}"
                  f"  ／ 通した n={pa['n']:>3} 中央値{pa['median']:>6.1f}% 毀損{pa['p_destroy']:.3f}"
                  f"  濃縮 {d['濃縮(止/通)']}")
        print('  線の感度:', {k: v['濃縮(止/通)'] for k, v in out['C2_financial']['線の感度(intcov)'].items()})

    print('\n■ 条件3 — 削除は支持されるか（降ろした主観の堀 moat5 を戻す）')
    d = out['C3_deletion']['pooled']
    print(f"  v11 のまま n={d['v11 のまま']['n']} 中央値{d['v11 のまま']['median']:.1f}% 毀損{d['v11 のまま']['p_destroy']:.3f}")
    if d['＋主観の堀 moat5≥4 を要求']['n']:
        e = d['＋主観の堀 moat5≥4 を要求']
        print(f"  ＋moat5≥4    n={e['n']} 中央値{e['median']:.1f}% 毀損{e['p_destroy']:.3f}"
              f"  → {d.get('戻すと改善するか', {}).get('結論')}")
    print('\n■ 判定:', json.dumps(out['verdict'], ensure_ascii=False)[:400])
    print('→ out/v11_backtest.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
