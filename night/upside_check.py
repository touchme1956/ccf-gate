#!/usr/bin/env python3
"""night/upside_check.py — 今の配分の上振れは小さいか（2026-10-14・ユーザー「今のままでは上振れが小さいのでは？」）

読むだけ。門・採点・配分（portfolio.json）・注文書には触れない。事前登録 out/upside_check_prereg.json（65a1f711）どおり。
  F_cur … 今（2026-10-14〜）NASDAQ100 40 / SMH 15 / 楽天・プラス・SOX 10 / ITA 5 / SHLD 5 / XLV 5 / FBT 5（個別株15は物差しの外）
  比べる形 … 前の形（10-13・10-12）・半導体を厚くする2つのはしご（守りの4本を残す LA／NASDAQ100＋半導体だけ LB）・
             etf_p15 の効率の最大（SMH60/ITA40）・天井（SMH100）・NASDAQ100 だけ・S&P500
物差し: night/unx_assets.measure（bestpf_check・unx_final と同じ式）に、
  - P20π・P25π と内部収益率の95%点（bestpf_eval.irr_quantiles と同じ道の束・同じ π）
  - A2（直近15年）を外した P20π
  - 過去の転がる20年の積立の内部収益率の最小・中央・最大（同じ系列・同じ手取りの調整・bestpf_realized と同じ式）
  - 100年の代用（unx_assets.century_monthly）の市場との比の上位10%点・最良
を足した。楽天・プラス・SOX は SMH の写しから年0.7pt を引いた本 SOX_F（感度: 引く分0）。
回帰の検査: F_main と F_now_1013 の USD・崩れあり窓の P15π・P5π・最悪の世界・最大下落が out/unx_final.json と小数1桁で一致しなければ止める。

使い方: python3 night/upside_check.py  → out/upside_check.json
"""
import copy, datetime, json, math, os, sys, time

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import unx_assets as U   # noqa: E402

OUT = os.path.join(BASE, 'out', 'upside_check.json')
PREREG = os.path.join(BASE, 'out', 'upside_check_prereg.json')
W_CRASH, W_DC = '崩れあり 2000-09〜', 'ドットコム級なし 2002-11〜'
SOX_DRAG = 0.007          # 楽天・プラス・SOX の実際に引かれた費用（2年 1.11%）− SMH（0.35%＋配当の外国税 約0.05%）
FIRST, END = 200009, 202609


def forms():
    P = json.load(open(PREREG))
    f = dict(P['forms_etf_side_percent_of_total'])   # 感度（SOX の引く分0）は F_now_1013 と同じ形＝別の行を作らない
    return f, P


def add_sox(rows, chains, drag):
    """SOX_F＝SMH の写しから年 drag を引いた本（月次は drag/12・世界 B/C/D は drag）"""
    import bestpf_eval as E
    r = copy.deepcopy(rows['SMH'])
    for k in ('B', 'C'):
        r[k] = rows['SMH'][k] - drag
    Dmap, _, _ = E.load_D(rows, ['SMH'])
    r['D_override'] = rows['SMH'].get('D_override', Dmap['SMH']) - drag
    r['ja'] = '楽天・プラス・SOX（SMH の写し − 年0.7pt）'
    rows['SOX_F'] = r
    chains['SOX_F'] = {m: v - drag / 12 for m, v in chains['SMH'].items()}


def irr_dist(sim, m_by_world, sig, pi):
    """bestpf_eval.irr_quantiles と同じ道の束 → (値, 累積の重み)"""
    vals, wts = [], []
    for w, m in m_by_world.items():
        p = pi.get(w, 0)
        if p <= 0:
            continue
        A = np.exp(sim['n_t'] / 12.0 * m)
        Wt = (np.exp(np.float32(sig) * sim['RC']) * A[None, :].astype(np.float32)).sum(axis=1)
        irr = np.interp(Wt, sim['K'], sim['r_grid'])
        vals.append(irr); wts.append(np.full(len(irr), p / len(irr)))
    v = np.concatenate(vals); wt = np.concatenate(wts)
    o = np.argsort(v)
    return v[o], wt[o] / wt.sum()


def upside(sim, raw, pi):
    noA2 = {k: (0.0 if k == 'A2' else v) for k, v in pi.items()}
    m = {k: math.log1p(v) for k, v in raw['worlds'].items()}
    v, w = irr_dist(sim, m, raw['sig'], pi)
    cw = np.cumsum(w)
    q = {f'{p}%点': round(100 * float(v[min(len(v) - 1, np.searchsorted(cw, p / 100))]), 1) for p in (10, 50, 75, 90, 95)}
    pr = {f'P{t}（道の束）': round(100 * float(w[v >= t / 100].sum()), 1) for t in (15, 20, 25)}
    v2, w2 = irr_dist(sim, m, raw['sig'], noA2)
    pr['P20（A2を外す）'] = round(100 * float(w2[v2 >= 0.20].sum()), 1)
    pr['P15（A2を外す・道の束）'] = round(100 * float(w2[v2 >= 0.15].sum()), 1)
    return q, pr


def rolling(wd, rows, chains):
    import bestpf_realized as BR
    tot = sum(wd.values())
    w = {c: v / tot for c, v in wd.items()}
    allm = BR.months(FIRST, END)
    s = [sum(w[c] * (chains[c][m] + (rows[c]['A1'] - rows[c]['A1_gross']) / 12) for c in w) for m in allm]
    out = {}
    for yrs in (20, 15):
        n = 12 * yrs
        v = [BR.irr_monthly(s[i:i + n])[0] for i in range(len(s) - n + 1)]
        vs = sorted(v)
        out[f'{yrs}年'] = dict(窓の数=len(v), 最小=round(100 * vs[0], 2), 中央=round(100 * vs[len(vs) // 2], 2), 最大=round(100 * vs[-1], 2),
                              以上15=round(100 * sum(x >= 0.15 for x in v) / len(v), 1), 以上20=round(100 * sum(x >= 0.20 for x in v) / len(v), 1))
    out['今日で終わる20年'] = round(100 * BR.irr_monthly(s[-240:])[0], 2)
    return out


def century_up(f):
    g = {('SMH' if k == 'SOX_F' else k): 0 for k in f}
    for k, v in f.items():
        g['SMH' if k == 'SOX_F' else k] += v
    d = U.century_monthly(g)
    if d is None:
        return None
    o = {}
    for lab, x in d.items():
        xs = sorted(x['_v'].values())
        o[lab] = {'窓': x['窓'], '中央値': x['中央値'], '下位10%点': x['下位10%点'], '上位10%点': round(U._q(xs, 0.90), 3),
                  '最良': round(xs[-1], 3), '最悪': x['最悪'], '市場に勝った割合': x['市場に勝った割合']}
    return o


def r1(x):
    return round(x + 1e-12, 1) if x >= 0 else -round(-x + 1e-12, 1)


def main():
    t0 = time.time()
    F, P = forms()
    res = U.build()
    rows, chains = res['rows'], res['chains']
    add_sox(rows, chains, SOX_DRAG)
    assets = sorted({a for f in F.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, [a for a in assets if a != 'SOX_F'])
    mega['SOX_F'] = mega.get('SMH', 0.0)
    import bestpf_eval as E
    pi, _, _ = E.load_pi()
    _, sim = U.tables()

    # ── 回帰の検査 ──
    U.log('USD の枠')
    tab_usd = U.measure(F, rows, chains, mega=mega)
    ref = json.load(open(os.path.join(BASE, 'out', 'unx_final.json')))['results']['USD の枠（主）'][W_CRASH]
    reg, ok = {}, True
    for mine, theirs in (('F_main（10-12 の最終）', 'F_main'), ('F_now_1013（SMH25・10-13〜10-14）', 'F_now')):
        d = {}
        for k in ('P15π', 'P5π（5%未満）', '最悪の世界', '最大下落'):
            a, b = tab_usd[W_CRASH][mine][k], ref[theirs][k]
            d[k] = dict(unx_final=b, この道具=a, 一致=r1(a) == r1(b))
            ok = ok and r1(a) == r1(b)
        reg[mine] = d
    U.log('回帰の検査', json.dumps(reg, ensure_ascii=False), ok)
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/upside_check.py', prereg='out/upside_check_prereg.json（65a1f711）',
               question=P['question'], regression=dict(ok=ok, rows=reg))
    if not ok:
        doc['decision'] = '回帰の検査に失敗＝止めた'
        json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
        raise SystemExit('回帰の検査に失敗')

    U.log('円の枠')
    ch_jpy, _ = U.jpy_chains(chains)
    tab_jpy = U.measure(F, rows, ch_jpy, mega=mega)

    def enrich(tab):
        out = {}
        for wn, t in tab.items():
            o = {}
            for nm, r in t.items():
                q, pr = upside(sim, r['_raw'], pi)
                rr = {k: v for k, v in r.items() if k != '_raw'}
                rr['上振れ'] = dict(pr, 内部収益率の分位=q, 最良の世界=round(100 * max(r['_raw']['worlds'].values()), 2))
                o[nm] = rr
            out[wn] = o
        return out

    U.log('上振れの分位')
    up_usd, up_jpy = enrich(tab_usd), enrich(tab_jpy)
    U.log('過去の転がる積立')
    roll = {nm: rolling(f, rows, chains) for nm, f in F.items()}
    U.log('100年の代用')
    cent = {nm: century_up(f) for nm, f in F.items()}
    cc, seats, cpct = U.castle_copy()
    cent_whole = {nm: century_up(U.whole(f, cc)) for nm, f in F.items()}

    # ── 読み方（事前登録 R1〜R3）──
    cur = 'F_cur（今・2026-10-14〜）'
    reading = {}
    for frame, up in (('USD・崩れあり（主）', up_usd[W_CRASH]), ('USD・ドットコム級なし', up_usd[W_DC]),
                      ('円・崩れあり', up_jpy[W_CRASH])):
        c = up[cur]
        P20 = {nm: r['上振れ']['P20（道の束）'] for nm, r in up.items()}
        Q90 = {nm: r['上振れ']['内部収益率の分位']['90%点'] for nm, r in up.items()}
        top = max(P20, key=P20.get)
        r1_ = {'F_cur の P20': P20[cur], 'F_cur の90%点': Q90[cur],
               'VOO': dict(P20=P20['R_VOO100（S&P500）'], 九十=Q90['R_VOO100（S&P500）']),
               'QQQM100': dict(P20=P20['R_QQQM100（NASDAQ100だけ）'], 九十=Q90['R_QQQM100（NASDAQ100だけ）']),
               'F_main': dict(P20=P20['F_main（10-12 の最終）'], 九十=Q90['F_main（10-12 の最終）']),
               '天井（測った形の中の最大の P20）': dict(形=top, P20=P20[top], 九十=Q90[top]),
               'F_cur は天井の何割（P20）': round(P20[cur] / P20[top], 2) if P20[top] else None}
        big = (P20[cur] > P20['R_VOO100（S&P500）'] and Q90[cur] > Q90['R_VOO100（S&P500）']
               and P20[cur] > P20['R_QQQM100（NASDAQ100だけ）'] and Q90[cur] > Q90['R_QQQM100（NASDAQ100だけ）'])
        small = (P20[cur] < P20['R_VOO100（S&P500）'] and Q90[cur] < Q90['R_VOO100（S&P500）'])
        r1_['判定（R1）'] = ('市場・NASDAQ100 より上振れは大きい' if big else
                           ('市場より上振れは小さい' if small else '市場より大きいが NASDAQ100 と比べると混ざる／小さい'))
        steps = {}
        for nm, r in up.items():
            if nm == cur:
                continue
            d = dict(ΔP20=round(r['上振れ']['P20（道の束）'] - c['上振れ']['P20（道の束）'], 1),
                     ΔP20_A2を外す=round(r['上振れ']['P20（A2を外す）'] - c['上振れ']['P20（A2を外す）'], 1),
                     Δ90点=round(r['上振れ']['内部収益率の分位']['90%点'] - c['上振れ']['内部収益率の分位']['90%点'], 1),
                     Δ中央=round(r['上振れ']['内部収益率の分位']['50%点'] - c['上振れ']['内部収益率の分位']['50%点'], 1),
                     ΔP5=round(r['P5π（5%未満）'] - c['P5π（5%未満）'], 1), Δ最悪の世界=round(r['最悪の世界'] - c['最悪の世界'], 2),
                     Δ最大下落=round(r['最大下落'] - c['最大下落'], 1), **{'Δ崩れ16〜18年目': round(r['崩れ2000型_16〜18年目'] - c['崩れ2000型_16〜18年目'], 2)},
                     Δ10点=round(r['上振れ']['内部収益率の分位']['10%点'] - c['上振れ']['内部収益率の分位']['10%点'], 1))
            free = d['ΔP20'] >= 1.0 and d['Δ最悪の世界'] >= 0 and d['ΔP5'] <= 0 and d['Δ最大下落'] >= 0
            d['読み（R2）'] = ('ただの上振れ（代金なし）' if free else ('代金つきの上振れ' if d['ΔP20'] >= 1.0 else '上振れは増えない（+1.0pt 未満）'))
            if d['ΔP20'] >= 1.0 and d['ΔP20_A2を外す'] < 1.0:
                d['読み（R3）'] = '直近15年の流れが続く世界に頼る'
            steps[nm] = d
        reading[frame] = dict(R1=r1_, R2_R3=steps)

    doc.update(
        forms=F, sox=dict(model='SMH の写し − 年0.7pt（SOX_F）', drag=SOX_DRAG, sensitivity='引く分0なら F_now_1013（SMH25）と同じ形'),
        pi=pi, notes=['ETF 側だけ（個別株15は物差しの外）', 'SHLD は unx_final と同じく門を通らない ITA つなぎ（2023-09 以前＝ITA）',
                      'P20・P25・95%点は irr_quantiles と同じ道の束から（P15π は etf_p15 の表＝少しずれる・両方出す）',
                      '100年の代用の SOX_F は SMH（Chips）として数える'],
        results={'USD・崩れあり（主）': up_usd[W_CRASH], 'USD・ドットコム級なし': up_usd[W_DC], '円・崩れあり': up_jpy[W_CRASH],
                 '円・ドットコム級なし': up_jpy[W_DC], '過去の転がる積立（USD・2000-09〜2026-09）': roll,
                 '100年の代用（ETF側だけ・市場との比）': cent, '100年の代用（全体の形・個別株＝席の業種の写し）': cent_whole},
        reading=reading, decision='配分は変えない（報告するだけ・事前登録 R4）', secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    U.log('→', OUT, f'{time.time() - t0:.0f}秒')
    for nm, r in up_usd[W_CRASH].items():
        u = r['上振れ']; q = u['内部収益率の分位']; ro = roll[nm]['20年']; ce = (cent[nm] or {}).get('20年の積立（起点1965〜2005）') or {}
        U.log(f"{nm[:26]:<26} P15π {r['P15π']:5.1f} P20 {u['P20（道の束）']:5.1f}(A2抜 {u['P20（A2を外す）']:4.1f}) P25 {u['P25（道の束）']:4.1f} "
              f"中央 {q['50%点']:5.1f} 90点 {q['90%点']:5.1f} 95点 {q['95%点']:5.1f} | P5 {r['P5π（5%未満）']:4.1f} 最悪 {r['最悪の世界']:5.2f} "
              f"下落 {r['最大下落']:6.1f} 崩16 {r['崩れ2000型_16〜18年目']:5.2f} | 過去20年 中央{ro['中央']:5.1f} 最小{ro['最小']:5.1f} 最大{ro['最大']:5.1f} "
              f"| 100年20年 中央{ce.get('中央値')} 下10{ce.get('下位10%点')} 上10{ce.get('上位10%点')}")


if __name__ == '__main__':
    main()
