#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/hist10_targets.py — **事前登録 out/hist10_prereg.json の3つの目的変数を作る**（2026-08-12新設）

この道具は**判定・合否の線を一つも持たない**。作るのは目的変数（y）だけで、
以降の角度A〜Eはすべてこの1本が出す out/hist10_targets.json を読む（二重実装を作らない）。

  y10       tr_cagr >= 0.10                       ← 事前登録の主目的（両方向で検定される）
  y_persist 前半(2013-07→2018-07) **と** 後半(2018-07→2026-08) の**両方**で 10%+
            ＝「壊れない複利」そのもの。前半は重なりを外して復元する:
              (1+r13)^13.09 = (1+r_前半)^5.0 × (1+r18)^8.09
            （irr85_windows.pre() と同じ操作。ここでは各行の実測 years を使う）
  y_biz     **倍率の寄与を除いた**年率が 10%+ ＝事業由来の複利
            hist_val_decompose の恒等式 ln(総リターン)/年 = 倍率 + 事業 + 分配 (+残差) を使う

⚠ **この道具が最初に出す答えは「どこまで測れるか」である**（事前登録 must_report_before_verdict の
   「到達可能性」に当たる）。3つの目的は**存在するビンテージが違う**:
     y10        2013 / 2015 / 2016 / 2017 / 2018   （5ビンテージすべて）
     y_persist  2013 のみ                          （前半の復元に2013と2018の両方の窓が要る）
     y_biz      2013 / 2015 / 2018                 （hist_val_decompose が在る年だけ）
   事前登録の sign_stability は「2016/2017/2018 すべてで維持」なので、
   **y_persist と y_biz はこの条件を字義どおりには満たしようがない**。
   ここを黙って読み替えると「測れない」を「測って合格」に化かすことになるので、
   本器は満たせないことを明示し、代替（y_biz なら 2013/2015/2018）は
   **『事前登録の外』の札を付けて**出す。合否に数えるかは読み手の判断で、本器は判定しない。

⚠ **y_persist は y10(2013) の部分集合**（両半が10%+なら全体も必ず10%+＝幾何平均）。
   重なりの数字はこの構造を確認するために出す（独立な二つの目的ではない）。

使い方: python3 night/hist10_targets.py [--json]
出力  : out/hist10_targets.json（--json なしでも書く。標準出力は人が読む報告）
"""
import collections
import json
import math
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

PREREG = 'out/hist10_prereg.json'
PANEL = 'out/hist_wd_panel.json'
OUT = 'out/hist10_targets.json'
GENERATED = '2026-08-12'


def rnd(x, n=6):
    return None if x is None else round(x, n)


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 6) if xs else None


def rate(k, n):
    return {'k': k, 'n': n, 'p': (round(k / n, 4) if n else None)}


def tab2(pairs):
    """2値×2値の 2x2 表と一致の指標。pairs=[(a,b),...] は両方 True/False の行だけ"""
    n11 = sum(1 for a, b in pairs if a and b)
    n10 = sum(1 for a, b in pairs if a and not b)
    n01 = sum(1 for a, b in pairs if (not a) and b)
    n00 = sum(1 for a, b in pairs if (not a) and (not b))
    n = n11 + n10 + n01 + n00
    den = math.sqrt((n11 + n10) * (n01 + n00) * (n11 + n01) * (n10 + n00))
    phi = ((n11 * n00 - n10 * n01) / den) if den else None
    return {
        'n': n, 'n11': n11, 'n10': n10, 'n01': n01, 'n00': n00,
        'P_a': (round((n11 + n10) / n, 4) if n else None),
        'P_b': (round((n11 + n01) / n, 4) if n else None),
        'agree': (round((n11 + n00) / n, 4) if n else None),
        'jaccard': (round(n11 / (n11 + n10 + n01), 4) if (n11 + n10 + n01) else None),
        'phi': (round(phi, 4) if phi is not None else None),
        'P_b_given_a': (round(n11 / (n11 + n10), 4) if (n11 + n10) else None),
        'P_a_given_b': (round(n11 / (n11 + n01), 4) if (n11 + n01) else None),
    }


def pre_rate(r_long, y_long, r_short, y_short):
    """重なりを外した前半の年率（irr85_windows.pre() と同じ式）"""
    if r_long is None or r_short is None:
        return None
    if 1 + r_short <= 0 or 1 + r_long < 0 or y_long <= y_short:
        return None
    return ((1 + r_long) ** y_long / (1 + r_short) ** y_short) ** (1 / (y_long - y_short)) - 1


# ────────────────────────────────────────────────────────────── 入力
def load():
    src = {}
    prereg = json.load(open(PREREG, encoding='utf-8'))
    panel = json.load(open(PANEL, encoding='utf-8'))
    src[PREREG] = prereg.get('generated')
    src[PANEL] = panel.get('generated')
    ret = {}
    for v, f in ((2013, 'out/retro_returns_2013_all.json'), (2018, 'out/retro_returns_2018.json')):
        d = json.load(open(f, encoding='utf-8'))
        src[f] = d.get('generated')
        ret[v] = {'rows': {r['ticker']: r for r in d['rows']},
                  'benchmark': d.get('benchmark'), 'file': f}
    dec = {}
    for v in (2013, 2015, 2018):
        f = f'out/hist_val_decompose_{v}.json'
        d = json.load(open(f, encoding='utf-8'))
        src[f] = d.get('generated')
        dec[v] = {'rows': {r['ticker']: r for r in d['rows']}, 'meta': d, 'file': f}
    f = 'out/retro_path_2018.json'
    d = json.load(open(f, encoding='utf-8'))
    src[f] = d.get('generated')
    path = {r['ticker']: r for r in d['rows']}
    f = 'out/retro_monthly_2013_2018.json'
    monthly = json.load(open(f, encoding='utf-8'))
    src[f] = '2026-08-05 (retro_path_features.py の在庫)'
    return prereg, panel, ret, dec, path, monthly, src


def join_checks(panel, ret, dec):
    """**目的変数を作る前に、繋いでいる二つが同じものかを確かめる**（基準の違う二つを割らないため）"""
    out = {}
    pm = {(r['vintage'], r['ticker']): r for r in panel['rows']}
    n = bad = 0
    for v in (2013, 2018):
        for t, a in ret[v]['rows'].items():
            p = pm.get((v, t))
            if p is None or not p['has_outcome']:
                continue
            n += 1
            if abs(a['tr_cagr'] - p['tr_cagr']) > 1e-9 or abs(a['years'] - p['years']) > 5e-3:
                bad += 1
    out['panel_vs_returns'] = {'n': n, 'mismatch': bad,
                               'def': 'パネルの tr_cagr/years と在庫の returns ファイルが一致するか'}
    n = bad = 0
    for v in (2013, 2015, 2018):
        for t, d in dec[v]['rows'].items():
            p = pm.get((v, t))
            if p is None:
                continue
            n += 1
            if (d.get('tr_cagr') is None or p['tr_cagr'] is None
                    or abs(d['tr_cagr'] - p['tr_cagr']) > 1e-9 or abs(d['years'] - p['years']) > 5e-3):
                bad += 1
    out['panel_vs_decompose'] = {'n': n, 'mismatch': bad,
                                 'def': ('分解の tr_cagr/years とパネルが一致するか。'
                                         '食い違えば分解と目的が別の窓を見ている＝割ってはいけない')}
    # 分解の tr（=ln(tr_total)/年）を戻すと tr_cagr になるか＝y10 と y_biz が同じリターンに載っているか
    e = []
    for v in (2013, 2015, 2018):
        for t, d in dec[v]['rows'].items():
            if d.get('tr') is not None and d.get('tr_cagr') is not None:
                e.append(abs(math.exp(d['tr']) - 1 - d['tr_cagr']))
    out['decompose_tr_vs_tr_cagr'] = {
        'n': len(e), 'max_abs': (round(max(e), 8) if e else None),
        'med_abs': (round(st.median(e), 8) if e else None),
        'def': ('exp(tr)−1 と tr_cagr の差。**y10 と y_biz が同じリターンに載っている**ことの確認。'
                '丸め（tr_total 小数3桁）以上に開いたら別物を割っている')}
    return out


# ────────────────────────────────────────────────────────────── 目的変数
def build(panel, ret, dec):
    """パネルの各行へ y10 / y_persist / y_biz を足す。作れないものは None（False ではない）"""
    rows = []
    # 前半の復元に使う窓の「満期」＝各ファイルの benchmark years（modal と一致することは診断で確認済）
    Y13 = ret[2013]['benchmark']['years']
    Y18 = ret[2018]['benchmark']['years']
    for r in panel['rows']:
        v, t = r['vintage'], r['ticker']
        o = {'ticker': t, 'vintage': v,
             'has_outcome': r['has_outcome'], 'window_full': r['window_full'],
             'tr_cagr': r['tr_cagr'], 'years': r['years'],
             'sic2': r['sic2'], 'size_rev': r['size_rev'],
             'P_full': r['P_full'], 'P_quality': r['P_quality'], 'P_moat': r['P_moat'],
             'irr': r['irr'],
             # 参考: 既存の15%の目的（同じ行で比べられるように持つ・本器の目的ではない）
             'win15': r['win'], 'destroy15': r['destroy']}

        # ── y10
        o['y10'] = (r['tr_cagr'] >= 0.10) if (r['has_outcome'] and r['tr_cagr'] is not None) else None

        # ── y_persist（2013 の入口でのみ定義できる）
        o['r_pre'] = o['r_post'] = None
        o['y_persist'] = None
        o['persist_basis'] = None
        if v == 2013:
            a, b = ret[2013]['rows'].get(t), ret[2018]['rows'].get(t)
            if a is None or b is None:
                o['persist_basis'] = 'どちらかの窓に社が無い'
            elif abs(a['years'] - Y13) > 1e-9 or abs(b['years'] - Y18) > 1e-9:
                # ⚠ 窓が満期でない社を混ぜない（DBD 型: 2013 の窓が 3.01 年＝2013→2018 を含まない）
                o['persist_basis'] = f"窓が満期でない(2013={a['years']} / 2018={b['years']})"
            else:
                rp = pre_rate(a['tr_cagr'], a['years'], b['tr_cagr'], b['years'])
                if rp is None:
                    o['persist_basis'] = '復元不能(全損等)'
                else:
                    o['r_pre'], o['r_post'] = rnd(rp), b['tr_cagr']
                    o['y_persist'] = bool(rp >= 0.10 and b['tr_cagr'] >= 0.10)
                    o['persist_basis'] = f"前半{Y13 - Y18:.2f}年 ∧ 後半{Y18}年"

        # ── y_biz（分解が在る年だけ）
        o['biz_rate'] = o['biz_rate_strict'] = o['mult_rate'] = o['div_rate'] = None
        o['y_biz'] = o['y_biz_strict'] = None
        o['biz_basis'] = None
        d = dec.get(v, {}).get('rows', {}).get(t)
        if d is None:
            o['biz_basis'] = ('分解の年ではない' if v not in dec else '分解プールに無い')
        elif d.get('mult_w') is None or d.get('div') is None or d.get('tr') is None:
            o['biz_basis'] = '分解の成分が欠ける'
        else:
            # 主: **実測の総リターンから倍率の寄与だけを引く**（残差は事業側に残る＝tr との整合が厳密）
            o['biz_rate'] = rnd(math.exp(d['tr'] - d['mult_w']) - 1)
            # 副: 名前の付いた成分の和だけ（事業＋分配。残差を含まない）
            o['biz_rate_strict'] = rnd(math.exp(d['biz_w'] + d['div']) - 1)
            o['mult_rate'] = rnd(math.exp(d['mult_w']) - 1)
            o['div_rate'] = rnd(math.exp(d['div']) - 1)
            o['y_biz'] = bool(o['biz_rate'] >= 0.10)
            o['y_biz_strict'] = bool(o['biz_rate_strict'] >= 0.10)
            o['biz_basis'] = 'tr−倍率(mult_w)／窓を揃えた版'
        rows.append(o)
    return rows


# ────────────────────────────────────────────────────────────── 基準率
def base_rates(rows):
    out = {}
    pops = [('P_full', lambda r: r['P_full'] is True),
            ('P_full∩window_full', lambda r: r['P_full'] is True and r['window_full']),
            ('P_quality', lambda r: r['P_quality'] is True),
            ('P_moat(irr>=70)', lambda r: r['P_moat'] is True)]
    for y in ('y10', 'y_persist', 'y_biz', 'y_biz_strict'):
        out[y] = {}
        for v in sorted({r['vintage'] for r in rows}):
            cell = {}
            for pname, f in pops:
                sub = [r for r in rows if r['vintage'] == v and f(r) and r[y] is not None]
                cell[pname] = rate(sum(1 for r in sub if r[y]), len(sub))
            # 判定不能の数（False と混同しないため）
            dn = [r for r in rows if r['vintage'] == v and r['P_full'] is True]
            cell['_undefined_in_P_full'] = sum(1 for r in dn if r[y] is None)
            out[y][str(v)] = cell
    return out


# ────────────────────────────────────────────────────────────── 重なり
def overlaps(rows):
    ov = {}
    # y10 × y_persist（2013 のみ・構造上 y_persist ⊂ y10 のはず）
    p = [(r['y10'], r['y_persist']) for r in rows
         if r['vintage'] == 2013 and r['y10'] is not None and r['y_persist'] is not None]
    t = tab2(p)
    t['note'] = ('y_persist=True ⟹ y10=True は数学的必然（両半が10%+なら幾何平均も10%+）。'
                 'n01（persistだけTrue）が0でなければ実装が壊れている')
    t['structural_violation_n01'] = t['n01']
    ov['y10 × y_persist (2013)'] = t
    # y10 × y_biz（分解が在る年ごと）
    for v in (2013, 2015, 2018):
        p = [(r['y10'], r['y_biz']) for r in rows
             if r['vintage'] == v and r['y10'] is not None and r['y_biz'] is not None]
        if p:
            ov[f'y10 × y_biz ({v})'] = tab2(p)
    # y_persist × y_biz（2013 のみ）
    p = [(r['y_persist'], r['y_biz']) for r in rows
         if r['vintage'] == 2013 and r['y_persist'] is not None and r['y_biz'] is not None]
    if p:
        ov['y_persist × y_biz (2013)'] = tab2(p)
    # y_biz × y_biz_strict（構成の違いが効くか）
    for v in (2013, 2015, 2018):
        p = [(r['y_biz'], r['y_biz_strict']) for r in rows
             if r['vintage'] == v and r['y_biz'] is not None]
        if p:
            ov[f'y_biz × y_biz_strict ({v})'] = tab2(p)
    # 参考: y10 × win15（既存の目的との関係）
    for v in (2013, 2018):
        p = [(r['y10'], r['win15']) for r in rows
             if r['vintage'] == v and r['y10'] is not None and r['win15'] is not None]
        if p:
            ov[f'y10 × win(15%) ({v})'] = tab2(p)
    return ov


# ────────────────────────────────────────────────────────────── 線のきわどさ
def fragility(rows):
    """**10%の線から±1pt に何社いるか**。ラベルがどれだけ揺れやすいかは、以降の角度が
       lift を語る前に知っておくべき量（測定の揺れが lift の分子を作れてしまう）"""
    out = {}
    for y, col in (('y10', 'tr_cagr'), ('y_persist', None), ('y_biz', 'biz_rate')):
        cell = {}
        for v in sorted({r['vintage'] for r in rows}):
            sub = [r for r in rows if r['vintage'] == v and r[y] is not None]
            if not sub:
                continue
            if y == 'y_persist':
                # 前半・後半のどちらかが線の±1pt 以内なら「きわどい」
                near = sum(1 for r in sub
                           if min(abs(r['r_pre'] - 0.10), abs(r['r_post'] - 0.10)) <= 0.01)
            else:
                near = sum(1 for r in sub if abs(r[col] - 0.10) <= 0.01)
            cell[str(v)] = {'n': len(sub), 'within_1pt': near,
                            'share': round(near / len(sub), 4)}
        out[y] = cell
    out['_note'] = ('±1pt に入る社は、測り方（窓の端・丸め・分解の残差）だけで札が裏返りうる。'
                    '独立検証②が示すとおり前半の復元には1ヶ月ぶんの不定性があり、'
                    '実測で 10% の線をまたぐ食い違いは 4.25%（40/941）ある')
    return out


# ────────────────────────────────────────────────────────────── 分解の中身
def decomp_shape(rows):
    """y_biz と y10 の差は**倍率の寄与そのもの**。何を引いているのかを数字で示す"""
    out = {}
    for v in (2013, 2015, 2018):
        sub = [r for r in rows if r['vintage'] == v and r['y_biz'] is not None]
        if not sub:
            continue
        mu = sorted(r['mult_rate'] for r in sub)
        n = len(mu)
        out[str(v)] = {
            'n': n,
            'mult_rate_med': med([r['mult_rate'] for r in sub]),
            'mult_rate_p05': round(mu[int(0.05 * (n - 1))], 4),
            'mult_rate_p95': round(mu[int(0.95 * (n - 1))], 4),
            'mult_negative_share': round(sum(1 for x in mu if x < 0) / n, 4),
            'biz_rate_med': med([r['biz_rate'] for r in sub]),
            'div_rate_med': med([r['div_rate'] for r in sub]),
            'tr_cagr_med': med([r['tr_cagr'] for r in sub]),
        }
    out['_note'] = ('倍率の寄与は年率で±数%動く一次の項。y_biz はこれを取り除いた「事業だけで'
                    '何%複利したか」。y10 との食い違い（φ 0.40〜0.42）はこの項が作っている')
    return out


# ────────────────────────────────────────────────────────────── y_biz の被覆と偏り
def coverage_bias(rows):
    out = {}
    for v in (2013, 2015, 2018):
        base = [r for r in rows if r['vintage'] == v and r['P_full'] is True]
        cov = [r for r in base if r['y_biz'] is not None]
        non = [r for r in base if r['y_biz'] is None]

        def desc(g):
            sz = [r['size_rev'] for r in g if r['size_rev']]
            tc = [r['tr_cagr'] for r in g if r['tr_cagr'] is not None]
            y1 = [r for r in g if r['y10'] is not None]
            q = [r for r in g if r['P_quality'] is not None]
            return {
                'n': len(g),
                'size_rev_med': med(sz), 'size_rev_p25': (round(st.quantiles(sz, n=4)[0], 1) if len(sz) > 3 else None),
                'size_rev_p75': (round(st.quantiles(sz, n=4)[2], 1) if len(sz) > 3 else None),
                'tr_cagr_med': med(tc),
                'P_y10': rate(sum(1 for r in y1 if r['y10']), len(y1)),
                'P_quality_share': rate(sum(1 for r in q if r['P_quality'] is True), len(q)),
                'top_sic2': collections.Counter(r['sic2'] for r in g if r['sic2']).most_common(6),
            }
        c, n = desc(cov), desc(non)
        # 業種の偏り: 被覆側と非被覆側のシェア差が大きい業種
        def share(g):
            cnt = collections.Counter(r['sic2'] for r in g if r['sic2'])
            tot = sum(cnt.values()) or 1
            return {k: v / tot for k, v in cnt.items()}
        sc, sn = share(cov), share(non)
        diffs = sorted(({'sic2': k, 'covered': round(sc.get(k, 0), 4),
                         'uncovered': round(sn.get(k, 0), 4),
                         'diff_pt': round((sc.get(k, 0) - sn.get(k, 0)) * 100, 2)}
                        for k in set(sc) | set(sn)),
                       key=lambda x: -abs(x['diff_pt']))[:8]
        out[str(v)] = {'coverage': rate(len(cov), len(base)),
                       'covered': c, 'uncovered': n, 'sector_share_diff_top': diffs,
                       'pool_def': None}
    return out


# ────────────────────────────────────────────────────────────── 復元の検算
def verify(rows, ret, path, monthly):
    Y13 = ret[2013]['benchmark']['years']
    Y18 = ret[2018]['benchmark']['years']
    got = [r for r in rows if r['vintage'] == 2013 and r['r_pre'] is not None]

    # (0) 恒等式の**前提**——二つの窓が同じ終点を見ているか。違えば式そのものが成り立たない
    end_bad = []
    for r in got:
        a, b = ret[2013]['rows'][r['ticker']], ret[2018]['rows'][r['ticker']]
        if a.get('end') != b.get('end'):
            end_bad.append({'t': r['ticker'], 'end13': a.get('end'), 'end18': b.get('end')})
    prem = {'def': '(1+r13)^13.09 と (1+r18)^8.09 は同じ終点を共有していなければ約分できない',
            'n_checked': len(got), 'end_mismatch_n': len(end_bad), 'end_mismatch': end_bad[:10],
            'note': ('食い違いはいずれも1日で、月足の最終バーの打刻差。5年に均すと無視できる大きさだが、'
                     '**前提の破れなので隠さず名指しする**')}

    # (1) 恒等式の再構成（**代数的に恒等＝道具の検査であって独立な検証ではない**）
    errs = []
    for r in got:
        a = ret[2013]['rows'][r['ticker']]
        recon = (1 + r['r_pre']) ** (Y13 - Y18) * (1 + r['r_post']) ** Y18
        errs.append(abs(recon - (1 + a['tr_cagr']) ** Y13))
    tauto = {'def': '(1+r_pre)^5.0 × (1+r_post)^8.09 − (1+r13)^13.09',
             'is_tautology': True,
             'why': 'r_pre はこの式を解いて作ったので必ず0になる。丸め・符号・窓の取り違えの検査にしかならない',
             'n': len(errs), 'max_abs': (round(max(errs), 12) if errs else None)}

    # (1b) 在庫の内部整合（tr_total と tr_cagr は別々に丸めて記録されている）
    tt = []
    for v in (2013, 2018):
        e, e_big = [], []
        for t, a in ret[v]['rows'].items():
            if a.get('tr_total') and a.get('years'):
                x = abs((1 + a['tr_cagr']) ** a['years'] - a['tr_total']) / a['tr_total']
                e.append(x)
                if a['tr_total'] >= 0.1:
                    e_big.append(x)
        tt.append({'vintage': v, 'n': len(e), 'max_rel': round(max(e), 6),
                   'med_rel': round(st.median(e), 8),
                   'n_tr_total_ge_0.1': len(e_big), 'max_rel_tr_total_ge_0.1': round(max(e_big), 6)})
    inner = {'def': '在庫の tr_total と (1+tr_cagr)^years の相対差',
             'per_vintage': tt,
             'note': ('外れはすべて tr_total<=0.01 の全損級の社＝tr_total が小数3桁に丸められているため'
                      'の見かけ。tr_total>=0.1 に限れば丸め幅どおりで、10%の線の近くには一切効かない')}

    # (2) **独立な検証**: retro_path_2018 の rf5（2013-07→2018-07 の月次adjcloseから直接測った前半CAGR）
    pair = []
    for r in got:
        p = path.get(r['ticker'])
        if p and p.get('rf5') is not None:
            pair.append((r['ticker'], r['r_pre'], p['rf5'], p.get('years')))
    d = [b - c for _, b, c, _ in pair]
    n = len(pair)
    mx = st.mean([b for _, b, _, _ in pair]) if n else None
    my = st.mean([c for _, _, c, _ in pair]) if n else None
    cor = None
    if n > 2:
        sx = math.sqrt(sum((b - mx) ** 2 for _, b, _, _ in pair))
        sy = math.sqrt(sum((c - my) ** 2 for _, _, c, _ in pair))
        if sx and sy:
            cor = sum((b - mx) * (c - my) for _, b, c, _ in pair) / (sx * sy)
    flip = [(t, b, c) for t, b, c, _ in pair if (b >= 0.10) != (c >= 0.10)]
    indep = {
        'def': ('復元した前半 r_pre と、retro_path_2018.rf5（2013-07→2018-07 の月次adjclose系列から'
                '**独立に**測った前半CAGR）の突合せ。二つは別の在庫・別の計算経路'),
        'n': n, 'pearson_r': (round(cor, 6) if cor else None),
        'diff_med_pt': (round(st.median(d) * 100, 3) if d else None),
        'diff_mean_pt': (round(st.mean(d) * 100, 3) if d else None),
        'diff_p05_pt': (round(sorted(d)[int(0.05 * (n - 1))] * 100, 3) if n else None),
        'diff_p95_pt': (round(sorted(d)[int(0.95 * (n - 1))] * 100, 3) if n else None),
        'diff_max_abs_pt': (round(max(abs(x) for x in d) * 100, 3) if d else None),
        'threshold_flip_n': len(flip),
        'threshold_flip_rate': (round(len(flip) / n, 4) if n else None),
        'threshold_flip_examples': [{'t': t, 'r_pre': b, 'rf5': c} for t, b, c in flip[:12]],
        'expected_bias': ('rf5 の年数は月足の実測（多くが4.92年）で、復元側は 13.09−8.09=5.00 年ちょうど。'
                          '窓の端が数十日ずれるので**系統差が残るのが正常**。ゼロになるほうがおかしい'),
        'path_years_med': med([y for _, _, _, y in pair]),
    }

    # (3) 指数（SPY）を同じ式で復元する——CLAUDE.md の実測 12.9% と合うか
    a, b = ret[2013]['benchmark'], ret[2018]['benchmark']
    sp = pre_rate(a['tr_cagr'], a['years'], b['tr_cagr'], b['years'])
    anchor = {'def': 'SPY を同じ式で復元', 'r13': a['tr_cagr'], 'r18': b['tr_cagr'],
              'r_pre': rnd(sp, 5),
              'claude_md_recorded': 0.129,
              'match': (abs(sp - 0.129) < 0.001) if sp is not None else None}

    # (4) **いちばん鋭い独立検証**——月次在庫と突き合わせると残差が「ちょうど1ヶ月ぶんの値動き」になるはず。
    #     復元は 2013-07-01→2018-07-01（5.00年）を指すが、月次在庫の最終バーは **2018-06-01**（4.92年）。
    #     よって F_復元 ÷ F_月次 = 2018年6月→7月の1ヶ月リターン。これが
    #     (a)実在する1ヶ月の断面分布の形をしていて (b)その社の5年利回りと（機械的な寄与を超えて）
    #     相関しない なら、復元の指数・約分は正しい。指数を取り違えていればここが必ず崩れる。
    imp, y_pre = [], []
    for r in got:
        s = monthly.get(r['ticker'])
        if not s or len(s) < 50:
            continue
        a, b = ret[2013]['rows'][r['ticker']], ret[2018]['rows'][r['ticker']]
        f_rec = (1 + a['tr_cagr']) ** a['years'] / (1 + b['tr_cagr']) ** b['years']
        f_mon = s[-1][1] / s[0][1]
        if f_mon <= 0:
            continue
        imp.append(f_rec / f_mon - 1)
        y_pre.append(r['r_pre'])
    n = len(imp)
    cor = None
    if n > 2:
        mx, my = st.mean(imp), st.mean(y_pre)
        sx = math.sqrt(sum((a - mx) ** 2 for a in imp))
        sy = math.sqrt(sum((a - my) ** 2 for a in y_pre))
        if sx and sy:
            cor = sum((a - mx) * (b - my) for a, b in zip(imp, y_pre)) / (sx * sy)
    ss = sorted(imp)
    sharp = {
        'def': ('F_復元 ÷ F_月次 − 1。月次在庫(retro_monthly_2013_2018)の最終バーは 2018-06-01 なので、'
                'これは 2018年6月→7月の**1ヶ月リターン**であるはず'),
        'n': n,
        'median': (round(st.median(imp), 5) if n else None),
        'mean': (round(st.mean(imp), 5) if n else None),
        'sd': (round(st.pstdev(imp), 5) if n > 1 else None),
        'p05': (round(ss[int(0.05 * (n - 1))], 5) if n else None),
        'p95': (round(ss[int(0.95 * (n - 1))], 5) if n else None),
        'corr_with_r_pre': (round(cor, 4) if cor is not None else None),
        'read': ('中央が数%・sdが約8%・両裾が±10〜15%＝**実在する1ヶ月の断面分布そのもの**。'
                 'r_pre との相関が小さく正なのは、その1ヶ月が r_pre の5年に含まれるという機械的な寄与'
                 '（対数で1/5だけ効く）で説明がつく。指数や約分を取り違えていれば、'
                 'ここは断面分布ではなく利回り水準に比例した系統差になる'),
    }

    # (5) **独立な検証③**——CLAUDE.md が別セッションの irr85_windows.py の実測として記録している
    #     18社の前半/後半。同じ式を別の道具で回した結果と一致するかの回帰検査。
    #     式を書き換えたらここが必ず落ちる（数字は CLAUDE.md「実績の窓」節の実測をそのまま写したもの）
    CM = {'LRCX': (32.3, 43.5), 'KLAC': (23.4, 43.5), 'CW': (27.8, 24.5), 'RBC': (22.7, 19.2),
          'MSFT': (30.6, 22.1), 'IDXX': (38.4, 11.4), 'V': (26.2, 13.9), 'RMD': (19.3, 10.7),
          'NOVT': (49.1, 12.3), 'MKSI': (30.7, 17.2), 'TDG': (28.3, 20.7), 'ENTG': (29.6, 19.6),
          'WST': (25.2, 15.7), 'BWXT': (26.1, 14.0), 'HXL': (15.1, 5.9), 'ST': (7.4, -0.7),
          'DLB': (15.2, 0.8), 'CMTL': (8.8, -30.1)}
    idx = {r['ticker']: r for r in got}
    hit, miss = 0, []
    for t, (a, b) in CM.items():
        r = idx.get(t)
        if r is None:
            miss.append({'t': t, 'why': '復元できていない'})
        elif abs(r['r_pre'] * 100 - a) < 0.06 and abs(r['r_post'] * 100 - b) < 0.06:
            hit += 1
        else:
            miss.append({'t': t, 'got': [round(r['r_pre'] * 100, 1), round(r['r_post'] * 100, 1)],
                         'claude_md': [a, b]})
    regress = {'def': ('CLAUDE.md「実績の窓」節が別セッションの irr85_windows.py の実測として'
                       '記録している18社の前半/後半と一致するか（式を書き換えたら落ちる回帰検査）'),
               'n': len(CM), 'match': hit, 'mismatch': miss}

    excl = collections.Counter(r['persist_basis'] for r in rows
                               if r['vintage'] == 2013 and r['r_pre'] is None and r['persist_basis'])
    return {'identity_premise_same_endpoint': prem, 'regression_vs_claude_md': regress,
            'tautological_reconstruction': tauto, 'inventory_internal': inner,
            'independent_vs_path_rf5': indep, 'independent_one_month_residual': sharp,
            'spy_anchor': anchor,
            'excluded_reasons': dict(excl), 'n_recovered': len(got)}


# ────────────────────────────────────────────────────────────── 到達可能性
def reachability(rows, prereg):
    out = {}
    for y in ('y10', 'y_persist', 'y_biz'):
        vs = sorted({r['vintage'] for r in rows if r[y] is not None})
        need = [2016, 2017, 2018]
        out[y] = {
            'vintages_available': vs,
            'prereg_sign_stability_needs': need,
            'sign_stability_reachable': all(v in vs for v in need),
            'n_defined_total': sum(1 for r in rows if r[y] is not None),
            'min_numerator_20_reachable_per_vintage': {
                str(v): sum(1 for r in rows if r['vintage'] == v and r[y]) for v in vs},
        }
    out['_note'] = ('事前登録 pass_line.sign_stability は「2016/2017/2018 すべて」。'
                    'y_persist は2013の入口でしか定義できず、y_biz は hist_val_decompose が'
                    '2013/2015/2018 にしか無い（2016/2017 の hist_val 在庫が存在しない）。'
                    '**この2つは字義どおりの合格が構造的に不可能**。代替の年で見る場合は'
                    '「事前登録の外」と明示すること（stopping_rule）。')
    return out


# ────────────────────────────────────────────────────────────── 報告
def report(res):
    P = print
    P('■ hist10_targets — 事前登録 out/hist10_prereg.json の3つの目的変数')
    P(f"  生成 {res['generated']} / 入力 {len(res['sources'])}本 / 行 {len(res['rows'])}")
    P('  ⚠ この道具は判定・合否の線を一つも持たない。作るのは y だけ')

    P('\n■ ①到達可能性——**目的ごとに存在するビンテージが違う**（合否を語る前に必ず読む）')
    for y in ('y10', 'y_persist', 'y_biz'):
        r = res['reachability'][y]
        ok = '✓' if r['sign_stability_reachable'] else '✗**不可能**'
        P(f"  {y:<10} 定義できる年 {r['vintages_available']}  "
          f"事前登録の sign_stability(2016/2017/2018) → {ok}   定義済み行 {r['n_defined_total']}")
    P(f"  → {res['reachability']['_note']}")

    P('\n■ ②基準率（分子/分母つき・判定不能は分母から外してある）')
    for y in ('y10', 'y_persist', 'y_biz', 'y_biz_strict'):
        P(f'  ── {y}')
        P(f"     {'年':<6}{'P_full':>22}{'∩window_full':>22}{'P_quality':>22}{'P_moat(irr>=70)':>22}")
        for v, cell in res['base_rates'][y].items():
            def f(k):
                c = cell[k]
                return f"{c['k']}/{c['n']}" + (f"={c['p']:.3f}" if c['p'] is not None else '=—')
            P(f"     {v:<6}{f('P_full'):>22}{f('P_full∩window_full'):>22}"
              f"{f('P_quality'):>22}{f('P_moat(irr>=70)'):>22}"
              f"   判定不能 {cell['_undefined_in_P_full']}")

    P('\n■ ③重なり——3つは同じことを測っていないか')
    for k, t in res['overlaps'].items():
        P(f"  {k:<28} n={t['n']:<5} P(a)={t['P_a']} P(b)={t['P_b']} "
          f"一致={t['agree']} φ={t['phi']} Jaccard={t['jaccard']} "
          f"P(b|a)={t['P_b_given_a']} P(a|b)={t['P_a_given_b']}")
        if t.get('note'):
            P(f"      └ {t['note']}  → n01={t['n01']}")

    P('\n■ ④y_biz の被覆と偏り——被覆した社は母集団から偏っていないか')
    for v, c in res['biz_coverage'].items():
        cv, un = c['covered'], c['uncovered']
        P(f"  ── {v}  被覆 {c['coverage']['k']}/{c['coverage']['n']} = {c['coverage']['p']}")
        P(f"     {'':<10}{'n':>6}{'売上中央値':>16}{'tr_cagr中央値':>15}{'P(y10)':>16}{'質実証の割合':>16}")
        for nm, g in (('被覆した社', cv), ('しない社', un)):
            sz = (f"{g['size_rev_med']/1e9:.2f}十億$" if g['size_rev_med'] else '—')
            y1 = "{}/{}={}".format(g['P_y10']['k'], g['P_y10']['n'], g['P_y10']['p'])
            qs = str(g['P_quality_share']['p'])
            P(f"     {nm:<10}{g['n']:>6}{sz:>16}{str(g['tr_cagr_med']):>15}{y1:>16}{qs:>16}")
        P('     業種のシェア差(pt) 上位: ' + ', '.join(
            f"{d['sic2']}:{d['diff_pt']:+.1f}" for d in c['sector_share_diff_top'][:6]))

    P('\n■ ⑤y_biz が引いているもの（倍率の寄与）と、線のきわどさ')
    P(f"     {'年':<6}{'n':>6}{'倍率の年率 中央':>17}{'p5':>9}{'p95':>9}{'負の割合':>10}"
      f"{'事業側 中央':>14}{'総 中央':>10}")
    for v, c in res['decomposition_shape'].items():
        if v.startswith('_'):
            continue
        P(f"     {v:<6}{c['n']:>6}{c['mult_rate_med']:>17}{c['mult_rate_p05']:>9}{c['mult_rate_p95']:>9}"
          f"{c['mult_negative_share']:>10}{c['biz_rate_med']:>14}{c['tr_cagr_med']:>10}")
    P('  10%の線から±1pt に入る社（札が測り方で裏返りうる社）:')
    for y, cell in res['fragility'].items():
        if y.startswith('_'):
            continue
        P(f"     {y:<10}" + '  '.join(f"{v}:{c['within_1pt']}/{c['n']}={c['share']}"
                                      for v, c in cell.items()))
    P(f"     └ {res['fragility']['_note']}")

    P('\n■ ⑥前半復元の検算')
    v = res['verify']
    j = res['join_checks']
    for k, c in j.items():
        P(f"  (0a) 繋ぎの検査 {k}: n={c['n']} "
          + (f"食い違い {c['mismatch']}" if 'mismatch' in c
             else f"最大差 {c['max_abs']} / 中央 {c['med_abs']}"))
    p = v['identity_premise_same_endpoint']
    P(f"  (0b) 恒等式の前提（二つの窓が同じ終点か）: n={p['n_checked']} 終点の食い違い {p['end_mismatch_n']}社 "
      + (', '.join(f"{x['t']}({x['end13']}/{x['end18']})" for x in p['end_mismatch']) or '—'))
    t = v['tautological_reconstruction']
    P(f"  (1) 再構成の誤差 n={t['n']} 最大 {t['max_abs']}  "
      f"← **代数的に恒等＝独立な検証ではない**（{t['why']}）")
    for x in v['inventory_internal']['per_vintage']:
        P(f"  (1b) 在庫の内部整合 {x['vintage']}: n={x['n']} 中央{x['med_rel']} 最大{x['max_rel']}"
          f"／tr_total>=0.1 に限れば n={x['n_tr_total_ge_0.1']} 最大{x['max_rel_tr_total_ge_0.1']}")
    P(f"      └ {v['inventory_internal']['note']}")
    i = v['independent_vs_path_rf5']
    P(f"  (2) **独立な検証①** vs retro_path_2018.rf5（別在庫・別経路）: n={i['n']} 相関 r={i['pearson_r']}")
    P(f"      差(復元−rf5) 中央 {i['diff_med_pt']}pt / p5 {i['diff_p05_pt']}pt / p95 {i['diff_p95_pt']}pt "
      f"/ 最大 {i['diff_max_abs_pt']}pt")
    P(f"      10%の線をまたぐ食い違い {i['threshold_flip_n']}/{i['n']} = {i['threshold_flip_rate']}")
    P(f"      └ {i['expected_bias']}（rf5 の年数中央値 {i['path_years_med']}）")
    s = v['independent_one_month_residual']
    P(f"  (3) **独立な検証②（いちばん鋭い）** 残差＝1ヶ月ぶんの値動きか: n={s['n']} "
      f"中央 {s['median']} 平均 {s['mean']} sd {s['sd']} p5 {s['p05']} p95 {s['p95']} "
      f"／ r_pre との相関 {s['corr_with_r_pre']}")
    P(f"      └ {s['read']}")
    a = v['spy_anchor']
    P(f"  (4) SPY を同じ式で復元 → 前半 {a['r_pre']:.4f}（CLAUDE.md の実測 {a['claude_md_recorded']}）"
      f" 一致={a['match']}")
    g = v['regression_vs_claude_md']
    P(f"  (5) **独立な検証③** CLAUDE.md 記録の18社（別セッション・別の道具の実測）と一致: "
      f"{g['match']}/{g['n']}" + (f"  食い違い {g['mismatch']}" if g['mismatch'] else '  ← 全一致'))
    P(f"  復元できた社 {v['n_recovered']} / 除外の理由 {v['excluded_reasons']}")


def main():
    prereg, panel, ret, dec, path, monthly, src = load()
    rows = build(panel, ret, dec)
    res = {
        'generated': GENERATED,
        'tool': 'night/hist10_targets.py',
        'prereg': PREREG,
        'purpose': ('事前登録の3つの目的変数（y10 / y_persist / y_biz）を作る。'
                    '判定・合否の線は一つも持たない。角度A〜Eはこの1本を読む'),
        'sources': src,
        'hurdle': 0.10,
        'hurdle_src': 'out/hist10_prereg.json（新しい定数を作っていない）',
        'definitions': {
            'y10': 'tr_cagr >= 0.10（配当込み年率・在庫の前方リターン）',
            'y_persist': ('前半(2013-07→2018-07) ∧ 後半(2018-07→2026-08) の両方が >=0.10。'
                          '前半は (1+r13)^13.09 =(1+r_pre)^5.0 ×(1+r18)^8.09 で復元。'
                          '**両窓とも満期の社だけ**（DBD型の短い窓を混ぜない）'),
            'y_biz': ('exp(tr − mult_w) − 1 >= 0.10。tr=ln(総リターン)/年、mult_w=倍率の寄与（窓を揃えた版）。'
                      '**実測の総リターンから倍率の寄与だけを引く**ので残差は事業側に残り、tr との整合が厳密'),
            'y_biz_strict': ('exp(biz_w + div) − 1 >= 0.10。名前の付いた成分の和だけ（残差を含まない）。'
                             '事前登録の文言「事業由来の寄与だけ」に寄せた版。主指標との食い違いは重なりの表に出る'),
            'why_two_biz': ('事前登録の角度Cは「事業由来の寄与だけ」、依頼文は「倍率の寄与を除いた年率」。'
                            '両者は残差(resid_w)のぶんだけ違う。どちらか一方を黙って選ばず両方作る'),
        },
        'structural_facts': [
            'y_persist=True ⟹ y10(2013)=True は数学的必然（両半が10%+なら幾何平均も10%+）＝独立な二つの目的ではない',
            'y_persist は2013の入口でしか作れない／y_biz は分解在庫のある2013/2015/2018だけ',
            '2015 の outcome は retro_returns_2015_q（質実証プール寄り506社）で全社ではない',
            'hist_val_decompose のプールは 質実証 ∧ 入口pe_pct あり ∧ 両端でPERが作れる＝**質に強く偏る**',
        ],
        'reachability': reachability(rows, prereg),
        'base_rates': base_rates(rows),
        'overlaps': overlaps(rows),
        'biz_coverage': coverage_bias(rows),
        'fragility': fragility(rows),
        'decomposition_shape': decomp_shape(rows),
        'join_checks': join_checks(panel, ret, dec),
        'verify': verify(rows, ret, path, monthly),
        'n_rows': len(rows),
        'rows': rows,
    }
    for v in (2013, 2015, 2018):
        res['biz_coverage'][str(v)]['pool_def'] = dec[v]['meta'].get('pool_def')
    json.dump(res, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    report(res)
    print(f'\n→ {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
