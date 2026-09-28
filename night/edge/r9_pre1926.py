#!/usr/bin/env python3
"""night/edge/r9_pre1926.py — 第9回 A_pre1926（事前登録 out/edge_prereg_r9.json）

凍結した dip_lever（spec_dip_lever.json）と trend（spec_trend.json）を、選定にも検定にも使っていない
1871-1925年の米国（Shiller の S&P 総合・配当込み）へ当てる確認。規則は変えない（fam_*.py の関数をそのまま import）。
  ・総リターン = (P_m + D_m/12) / P_{m-1} − 1（P は月中の平均・D は年率の配当）
  ・短期金利 = FRED の NBER 歴史系列 M13002US35620M156NNBR（ニューヨークの商業手形・年率%）/1200。無い月は GS10/1200 で代え数を書く
  ・相手 = 同じ期間の株の持ち続け
  ・費用 = 凍結どおり（dip_lever: 借りた分に rf+0.4%/年・経費0.9%/年×e・回転1あたり0.10%／trend: 回転1あたり0.10%）
  ・日次が無い: dip_lever は fam 自身の月次の借り直し（apply_monthly＝他の市場と同じ近似）。
    trend の凍結は「日次63営業日のぶれ」→ 日次が無いので fam の月次の選択肢（src='monthly', win=12）で代える（置き換え・明記）
  ・判定（事前登録）: 費用後の超過が正 かつ t≥2 なら『再現した』。2本の中で Holm（α=0.05・片側 p は正規近似）
読むだけ。全期間を読むので EDGE_PHASE=holdout で走らせる。
"""
import os, sys, json, math, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if os.environ.get('EDGE_PHASE') != 'holdout':
    sys.exit('EDGE_PHASE=holdout で走らせる（1926以降の比較にも全期間を読む）')
import harness as h
import fam_dip_lever as fd
import fam_trend as ft

A, B = 187201, 192512          # 共通の評価窓（trend の準備12か月の後から）
ALPHA = 0.05
OUT = os.path.join(h.BASE, 'out', 'edge', 'r9_pre1926.json')


def shiller_ret():
    rows = [r for r in h.shiller() if r['P'] and r['D'] is not None]
    ret, gs10 = {}, {}
    for a, b in zip(rows, rows[1:]):
        if h.add_months(a['m'], 1) != b['m']:
            continue
        ret[b['m']] = (b['P'] + b['D'] / 12) / a['P'] - 1
    for r in h.shiller():
        if r['GS10'] is not None:
            gs10[r['m']] = r['GS10'] / 1200
    return ret, gs10


def rates(gs10):
    sid = 'M13002US35620M156NNBR'
    cp = {m: v / 1200 for m, v in h.fred(sid).items()}
    rf, sub = {}, []
    for m in h.month_range(187101, 192512):
        if m in cp:
            rf[m] = cp[m]
        elif m in gs10:
            rf[m] = gs10[m]; sub.append(m)
    return rf, sid, sub


def ac1(xs):
    mu = S.mean(xs)
    num = sum((xs[i] - mu) * (xs[i - 1] - mu) for i in range(1, len(xs)))
    den = sum((x - mu) ** 2 for x in xs)
    return num / den


def run_dip(ret, rf, sp, lag=0):
    lev = fd.dd_lever(ret, sp['X'], sp['e'], sp['exit'], sp.get('N'))
    if lag:                                   # 感度: 信号をさらに lag か月遅らせる
        ks = sorted(lev); lev = {ks[i]: (lev[ks[i - lag]] if i >= lag else 1.0) for i in range(len(ks))}
    r = fd.apply_monthly(ret, lev, rf)
    return r, fd.turnover_of(lev), lev


def run_trend(ret, rf, sp, start, lag=0):
    pos = ft.positions(sp, ret, rf)
    if lag:
        pos = {h.add_months(k, lag): v for k, v in pos.items()}
    return ft.apply(pos, ret, rf, start)


def episodes(lev, ret, rf):
    out, cur = [], None
    for m in sorted(lev):
        if lev[m] > 1 and cur is None:
            cur = [m, m]
        elif lev[m] > 1:
            cur[1] = m
        elif cur:
            out.append(cur); cur = None
    if cur:
        out.append(cur)
    res = []
    r, _, _ = None, None, None
    for a, b in out:
        ms = [m for m in h.month_range(a, b) if m in ret]
        g = math.prod(1 + ret[m] for m in ms)
        res.append({'from': a, 'to': b, 'months': len(ms), 'market_x': round(g, 2)})
    return res


def holm(ps):
    order = sorted(ps, key=lambda k: ps[k])
    out, stop = {}, False
    for i, k in enumerate(order):
        thr = ALPHA / (len(order) - i)
        ok = (not stop) and ps[k] <= thr
        stop = stop or not ok
        out[k] = {'p': round(ps[k], 4), 'thr': round(thr, 4), 'pass': ok}
    return out


def main():
    spd = json.load(open(os.path.join(h.BASE, 'out', 'edge', 'spec_dip_lever.json')))['spec']
    spt = json.load(open(os.path.join(h.BASE, 'out', 'edge', 'spec_trend.json')))['spec']
    spt_m = dict(spt, src='monthly', win=12)            # 日次が無いための置き換え（凍結の中の月次の選択肢）
    ret_all, gs10 = shiller_ret()
    rf, sid, sub = rates(gs10)
    ret = {m: v for m, v in ret_all.items() if m <= 192512 and m in rf}

    res = {'about': '第9回 A_pre1926: 凍結した dip_lever・trend を 1871-1925 の米国（Shiller・配当込み）へ当てる確認（読むだけ）',
           'prereg': 'out/edge_prereg_r9.json', 'window': [A, B],
           'data': {'stock': 'Shiller ie_data.xls: (P_m + D_m/12)/P_{m-1} − 1・P は月中の平均',
                    'rf': f'FRED {sid}（NBER: ニューヨークの商業手形・年率%/1200）', 'rf_substituted_by_GS10_months': sub},
           'substitutions': ['dip_lever: 日次が無いので fam_dip_lever.apply_monthly（月次の借り直し・他の市場に当てたのと同じ近似）',
                             'trend: 凍結は日次63営業日のぶれ。日次が無いので fam_trend の月次の選択肢 src=monthly・win=12 で代える'
                             '（中央値との比は自己相対なので、月平均でぶれが縮む分は打ち消し合う）'],
           'costs': 'dip_lever: 借りた分 e に rf+0.4%/年・経費0.9%/年×e・回転1あたり0.10%／trend: 回転1あたり0.10%（凍結どおり）'}

    # ── 主 ──
    rd, tvd, lev = run_dip(ret, rf, spd)
    sd = h.stats(rd, ret, rf, a=A, b=B, turnover=tvd, cost=fd.COST)
    sd['lever_months'] = sum(1 for m in lev if lev[m] > 1 and A <= m <= B)
    sd['episodes'] = [e for e in episodes(lev, ret, rf) if e['to'] >= A]
    rt, tvt = run_trend(ret, rf, spt_m, A)
    st = h.stats(rt, ret, rf, a=A, b=B, turnover=tvt, cost=ft.COST)
    pos = ft.positions(spt_m, ret, rf)
    st['out_months'] = sum(1 for m in pos if A <= m <= B and pos[m] < 1)
    st['turnover_per_year'] = round(sum(v for m, v in tvt.items() if A <= m <= B) / st['years'], 2)
    ps = {'C13_dip_lever_1871': h.pnorm_upper(sd['t']), 'C14_trend_1871': h.pnorm_upper(st['t'])}
    hm = holm(ps)
    main_ = {}
    for key, s in (('C13_dip_lever_1871', sd), ('C14_trend_1871', st)):
        rep = s['excess'] > 0 and s['t'] is not None and s['t'] >= 2
        if s['t'] is None and s.get('lever_months') == 0:
            v = '検定不能（1872-1925 に一度も借りなかった＝相手と同一）'
        else:
            v = '再現した' if rep and hm[key]['pass'] else '再現した（Holm は通らない）' if rep else '再現しなかった'
        main_[key] = {'stats': s, 'holm': hm[key], 'verdict': v}
    res['main'] = main_

    # ── 配当込み指数の最大の下落（月平均）と、その時期 ──
    v = peak = 1.0; pk_m = None; worst = (0.0, None, None)
    for m in sorted(ret):
        v *= 1 + ret[m]
        if v >= peak:
            peak, pk_m = v, m
        if v / peak - 1 < worst[0]:
            worst = (v / peak - 1, pk_m, m)
    res['max_drawdown_1871_1925'] = {'dd': round(worst[0] * 100, 1), 'peak': worst[1], 'trough': worst[2],
                                     'note': 'dip_lever の線は −40%。月平均の値なので月末の値より浅く出る'}

    # ── 自己相関（月平均の株価） ──
    xs = [ret[m] for m in sorted(ret) if A <= m <= B]
    mkt, frf = h.us_market()
    fr = [mkt[m] for m in sorted(mkt) if 192707 <= m <= 200012]
    sh2 = [ret_all[m] for m in sorted(ret_all) if 192707 <= m <= 200012]
    res['autocorr'] = {
        'shiller_1872_1925': {'rho1': round(ac1(xs), 3), 'n': len(xs), 'se': round(1 / math.sqrt(len(xs)), 3)},
        'shiller_1927_2000_monthavg': {'rho1': round(ac1(sh2), 3), 'n': len(sh2)},
        'french_1927_2000_monthend': {'rho1': round(ac1(fr), 3), 'n': len(fr)},
        'theory': 'Working (1960): 酔歩を月中で平均すると、平均の差の1次の自己相関は約0.25（月末の値なら0）',
        'var_ratio_note': '平均化で月次のぶれは約 √(2/3)≈0.82 倍に縮む（同じく Working）'}
    res['autocorr']['var_shiller_vs_french_1927_2000'] = round(S.stdev(sh2) / S.stdev(fr), 3)

    # ── 感度・事後（名札つき）──
    sens = {}
    r1, tv1, _ = run_dip(ret, rf, spd, lag=1)
    sens['dip_lever_信号をもう1か月遅らせる'] = h.stats(r1, ret, rf, a=A, b=B, turnover=tv1, cost=fd.COST)
    r1, tv1 = run_trend(ret, rf, spt_m, A, lag=1)
    sens['trend_信号をもう1か月遅らせる'] = h.stats(r1, ret, rf, a=A, b=B, turnover=tv1, cost=ft.COST)
    r1, tv1 = run_trend(ret, rf, dict(spt, src='monthly', win=3), A)
    sens['trend_ぶれ窓3か月（63営業日に近い長さ）'] = h.stats(r1, ret, rf, a=A, b=B, turnover=tv1, cost=ft.COST)
    gsr = {m: gs10[m] for m in rf if m in gs10}
    r1, tv1, _ = run_dip(ret, gsr, spd)
    sens['dip_lever_金利を GS10 に'] = h.stats(r1, ret, gsr, a=A, b=B, turnover=tv1, cost=fd.COST)
    r1, tv1 = run_trend(ret, gsr, spt_m, A)
    sens['trend_金利を GS10 に'] = h.stats(r1, ret, gsr, a=A, b=B, turnover=tv1, cost=ft.COST)
    res['sensitivity_事後'] = sens

    # ── 較正（事後）: 同じ規則を 1927-2000 に、月末の French と 月平均の Shiller で当て比べる＝平均化の上げ底の大きさ ──
    cal = {}
    sh_ret = {m: v for m, v in ret_all.items() if m in frf}
    for nm, R in (('French_月末', mkt), ('Shiller_月平均', sh_ret)):
        R = {m: v for m, v in R.items() if m <= 200012}
        a_, b_ = 192707, 200012
        r1, tv1, lv = run_dip(R, frf, spd)
        cal[f'dip_lever_{nm}_月次借り直し'] = h.stats(r1, R, frf, a=a_, b=b_, turnover=tv1, cost=fd.COST)
        r1, tv1 = run_trend(R, frf, spt_m, a_)
        cal[f'trend_{nm}_月次ぶれ12'] = h.stats(r1, R, frf, a=a_, b=b_, turnover=tv1, cost=ft.COST)
        r1, tv1 = run_trend(R, frf, spt_m, a_, lag=1)
        cal[f'trend_{nm}_月次ぶれ12_1か月遅らせ'] = h.stats(r1, R, frf, a=a_, b=b_, turnover=tv1, cost=ft.COST)
    res['calibration_1927_2000_事後'] = cal

    # ── 1926 以降の正式の結果 ──
    er = json.load(open(os.path.join(h.BASE, 'out', 'edge_results.json')))['families']
    res['post1926_official'] = {k: {'selection_1926_2000': er[k]['selection'], 'holdout_2001_2026': er[k]['holdout'],
                                    'verdict': er[k]['verdict']} for k in ('dip_lever', 'trend')}
    json.dump(res, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps({k: {'v': v['verdict'], **{x: v['stats'][x] for x in ('excess', 'ex_arith', 't', 't_nw', 'vol', 'bench_vol', 'maxdd', 'bench_maxdd', 'cagr', 'bench_cagr', 'roll10_win')}} for k, v in main_.items()}, ensure_ascii=False, indent=1))
    print(json.dumps({k: main_[k]['stats'].get(x) for k in main_ for x in ('lever_months', 'out_months', 'turnover_per_year', 'episodes') if main_[k]['stats'].get(x) is not None}, ensure_ascii=False))
    print(json.dumps(res['autocorr'], ensure_ascii=False))
    for k, v in {**sens, **cal}.items():
        print(k, {x: v[x] for x in ('excess', 'ex_arith', 't', 'vol', 'bench_vol', 'maxdd', 'bench_maxdd')})
    print('rf substituted:', len(sub))


if __name__ == '__main__':
    main()
