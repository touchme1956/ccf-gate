#!/usr/bin/env python3
"""night/ndx_swap_check.py — ITA か SHLD を NASDAQ100 に変えるのは？（2026-10-14・ユーザー「ITAかSHLDをNASDAQに変えるのは？」）

読むだけ。門・採点・配分（portfolio.json）・注文書には触れない。事前登録 out/ndx_swap_prereg.json（fae26ca3）どおり。
  F_cur … 今 NASDAQ100 40 / SMH 15 / 楽天・プラス・SOX 10 / ITA 5 / SHLD 5 / XLV 5 / FBT 5（個別株15は物差しの外）
  A … ITA 5 を NASDAQ100 へ ／ B … SHLD 5 を NASDAQ100 へ ／ C … 両方（10）を NASDAQ100 へ ／ 参考 D … SHLD 5 を ITA へ
判定: Δ＝今（X あり）− 案（X を NASDAQ100 へ）を etf_ita_xlk.verdict に通し、感度5本（main・A2を外す・半導体の基礎率・
  分散の上乗せなし・共分散を A2 の窓から）を etf_ita_xlk.summarize でまとめる。物差しは unx_assets.measure（5つの世界・π）。
  保険の3条件（unx_final.conds＝2026-10-13 に XLV を入れたときの決まり）を「今」を「案」と比べて当てる。
回帰の検査: ① F_cur が out/upside_check.json と小数1桁で一致 ② 感度の計算の main が unx_assets.measure の丸める前の値と 1e-9 以内で一致。
参考（判定に使わない）: 上振れ（P20・90%点）・過去の転がる20年の積立・100年の代用・SHLD／ITA が本物の窓・下げの局面・中身の集中・注文書。
注文書は night/shadow_seats.js --weights の結果（out/_nx_cache/ndx_swap/orders_*.json・run_orders.sh）を読む（無ければ『未取得』）。

使い方: python3 night/ndx_swap_check.py  → out/ndx_swap_check.json
"""
import datetime, json, math, os, re, subprocess, sys, time

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import unx_assets as U        # noqa: E402
import upside_check as UC     # noqa: E402

OUT = os.path.join(BASE, 'out', 'ndx_swap_check.json')
PREREG = os.path.join(BASE, 'out', 'ndx_swap_prereg.json')
ORD = os.path.join(BASE, 'out', '_nx_cache', 'ndx_swap')
W_CRASH, W_DC = UC.W_CRASH, UC.W_DC
VARS = ['main', 'S2', 'K4', 'K1', 'K2']
VARS_JA = {'main': '主', 'S2': 'A2を外す', 'K4': '半導体の基礎率', 'K1': '分散の上乗せなし', 'K2': '共分散をA2の窓から'}
CUR = 'F_cur（今・2026-10-14〜）'
KEYS = {'A': 'A_ITA→NDX（ITA 5 を NASDAQ100 へ）', 'B': 'B_SHLD→NDX（SHLD 5 を NASDAQ100 へ）',
        'C': 'C_両方→NDX（ITA・SHLD の10を NASDAQ100 へ）', 'D': '参考 D_SHLD→ITA（防衛を ITA 10 にまとめる・判定に使わない）'}
COMPS = {'ITA の価値（今 − A）': 'A', 'SHLD の価値（今 − B）': 'B', 'ITA・SHLD 両方の価値（今 − C）': 'C', '参考: SHLD を ITA にまとめるより（今 − D）': 'D'}
EPISODES = {'ITバブル崩壊 2000-09〜2002-10': (200009, 200210), '金融危機 2007-11〜2009-02': (200711, 200902),
            'コロナ 2020-01〜2020-03': (202001, 202003), '2022年の下げ 2022-01〜2022-09': (202201, 202209)}
REAL_WINDOWS = {'SHLD が本物の窓 2023-10〜2026-09（36か月）': (202310, 202609), 'ITA が本物の窓 2006-05〜2026-09': (200605, 202609)}
NET_ARG = {'QQQM': 'QQQM', 'SMH': 'SMH', 'SOX_F': 'RPLUS-SOX', 'ITA': 'ITA', 'SHLD': 'SHLD', 'XLV': 'XLV', 'FBT': 'FBT'}
CASTLE_ARG = 'CW=3,LRCX=3,MSFT=3,ASML=3,GOOGL=3'


def forms():
    P = json.load(open(PREREG))
    return dict(P['forms_etf_side_percent_of_total']), P


def chips_adj(rows, assets):
    """etf_forward_combo の K4 の式（Chips の比重は rows の top_industries・米国の本だけ・VOO は市場・SOX_F は SMH）"""
    import etf_forward_combo as CB
    R = U.R
    rest = CB.CHIPS_GAP * CB.CHIPS_MKT / (1 - CB.CHIPS_MKT)
    out, share = {}, {}
    for c in assets:
        base = 'SMH' if c == 'SOX_F' else c
        if base == 'VOO':
            sh = CB.CHIPS_MKT
        else:
            us = (R.C.get(base) or U.NEW.get(base) or {}).get('us')
            sh = float((rows[base].get('top_industries') or {}).get('Chips') or 0.0) if us else None
        share[c] = sh
        out[c] = 0.0 if sh is None else (-CB.CHIPS_GAP * sh + rest * (1 - sh)) / 2
    return out, share


def variants(ports, rows, chains, k4):
    """unx_assets.measure の式を写し、感度5本の丸める前の値を出す（main は measure と同じ値＝回帰の検査②）"""
    import etf_p15 as P
    import etf_forward_combo as CB
    import bestpf_eval as E
    import bestpf_check as BC
    R = U.R
    tabs, _ = U.tables()
    assets = sorted({a for w in ports.values() for a in w} | {'VOO'})
    k2 = R.months(*R.A2)
    G2 = np.array([[chains[c][m] for m in k2] for c in assets])
    S2 = np.cov(np.log1p(G2), bias=True) * 12
    s2 = np.diag(S2).copy()
    adj = np.array([rows[c]['A1'] - rows[c]['A1_gross'] for c in assets])
    Dmap, _, _ = E.load_D(rows, assets)
    for c in assets:
        if 'D_override' in rows[c]:
            Dmap[c] = rows[c]['D_override']
    pi, _, _ = E.load_pi()
    noA2 = {k: (0.0 if k == 'A2' else v) for k, v in pi.items()}
    gB = np.array([rows[c]['B'] for c in assets]); gC = np.array([rows[c]['C'] for c in assets]); gD = np.array([Dmap[c] for c in assets])
    kk = np.array([k4[c] for c in assets])

    def pr(wv, sig, tau, p):
        tot = 0.0
        for k in E.WORLDS:
            if p.get(k, 0) <= 0:
                continue
            v = float(P.interp(tabs[tau], np.array([math.log1p(wv[k])]), np.array([sig]))[0])
            tot += p[k] * (v if tau >= 0.10 else 1 - v)
        return tot / sum(p[k] for k in E.WORLDS if p.get(k, 0) > 0)

    out = {}
    for wname, (a, b) in BC.WINDOWS.items():
        k1 = R.months(a, b)
        G1 = np.array([[chains[c][m] for m in k1] for c in assets])
        S1 = np.cov(np.log1p(G1), bias=True) * 12
        s1 = np.diag(S1).copy()
        tab = {}
        for nm, wd in ports.items():
            tot = sum(wd.values())
            w = np.array([wd.get(c, 0) / tot for c in assets])
            ps = CB.path_stats((w @ G1)[None, :], len(k1))
            a2 = float(np.expm1(np.log1p(w @ G2).sum() * 12 / len(k2)))
            res = {}
            for var in VARS:
                S, s = (S2, s2) if var == 'K2' else (S1, s1)
                q = float(w @ S @ w)
                bonus = 0.0 if var == 'K1' else 0.5 * (float(w @ s) - q)
                sig = math.sqrt(q)
                gb, gc, gd = (gB + kk, gC + kk, gD + kk) if var == 'K4' else (gB, gC, gD)
                wv = dict(A1=float(ps[0][0]) + float(w @ adj), A2=a2 + float(w @ adj), B=math.expm1(float(w @ np.log1p(gb)) + bonus),
                          C=math.expm1(float(w @ np.log1p(gc)) + bonus), D=math.expm1(float(w @ np.log1p(gd)) + bonus))
                p = noA2 if var == 'S2' else pi
                used = [k for k in E.WORLDS if p.get(k, 0) > 0]
                res[var] = dict(P15=pr(wv, sig, 0.15, p), P5=pr(wv, sig, 0.05, p), worst=min(wv[k] for k in used),
                                mean_pi=sum(p[k] * wv[k] for k in E.WORLDS) / sum(p.values()), vol=float(ps[1][0]), mdd=float(ps[2][0]),
                                sig=sig, bonus=bonus, worlds=wv)
            tab[nm] = res
        out[wname] = tab
    return out


def regress_variants(vt, tab):
    worst, rows = 0.0, {}
    for wn, t in tab.items():
        for nm, r in t.items():
            a, b = vt[wn][nm]['main'], r['_raw']
            d = max([abs(a[k] - b[k]) for k in ('P15', 'P5', 'worst', 'mean_pi', 'vol', 'mdd', 'sig')]
                    + [abs(a['worlds'][k] - b['worlds'][k]) for k in b['worlds']])
            rows[f'{wn} / {nm}'] = d
            worst = max(worst, d)
    return dict(max_abs_diff=worst, tol=1e-9, ok=worst <= 1e-9, rows=rows)


def judge(vt, wn, a, b):
    from etf_ita_xlk import verdict, summarize
    per, vs = {}, {}
    for var in VARS:
        ra, rb = vt[wn][a][var], vt[wn][b][var]
        d = {'平均': round(100 * (ra['mean_pi'] - rb['mean_pi']), 3), '最悪': round(100 * (ra['worst'] - rb['worst']), 3),
             '確率': round(100 * (ra['P15'] - rb['P15']), 3), 'ぶれ': round(100 * (ra['vol'] - rb['vol']), 3),
             '5%未満': round(100 * (ra['P5'] - rb['P5']), 3), '最大下落': round(100 * (ra['mdd'] - rb['mdd']), 3)}
        vs[var] = verdict(d)
        per[VARS_JA[var]] = dict(差=d, 判定=vs[var])
    return dict(感度=per, まとめ=summarize(vs), 主の判定=vs['main'])


def reading(summary, main_v, ins_ok, others):
    if summary == '堅い価値あり':
        r = 'R1: 今のまま（残す）を勧める'
    elif summary == '堅い価値なし〜小さい':
        r = ('R2: NASDAQ100 へ替えるほうが測りでは良い' if main_v == '価値なし' else 'R2: どちらでもよい（好みの差）')
    elif ins_ok:
        r = 'R3: 今のまま（保険として 2026-10-13 の3条件を満たす）'
    else:
        r = 'R4: 決まりでは今のまま（替える根拠が堅くない）。ただし残す根拠も薄い＝好みの差'
    split = {k: v for k, v in others.items() if v != summary}
    if split:
        r += '（R5: 窓・通貨で割れる——' + '・'.join(f'{k} は {v}' for k, v in split.items()) + '）'
    return r


def monthly_series(f, rows, chains, a, b):
    import bestpf_realized as BR
    tot = sum(f.values())
    w = {c: v / tot for c, v in f.items()}
    ms = BR.months(a, b)
    return ms, [sum(w[c] * (chains[c][m] + (rows[c]['A1'] - rows[c]['A1_gross']) / 12) for c in w) for m in ms]


def stats(xs):
    n = len(xs)
    g = math.exp(sum(math.log1p(x) for x in xs) * 12 / n) - 1
    mu = sum(xs) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / n) * math.sqrt(12)
    v, peak, mdd = 1.0, 1.0, 0.0
    for x in xs:
        v *= 1 + x
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return dict(年率=round(100 * g, 2), ぶれ=round(100 * sd, 1), 最大下落=round(100 * mdd, 1), 月数=n)


def corr(a, b):
    a, b = np.array(a), np.array(b)
    return round(float(np.corrcoef(a, b)[0, 1]), 3)


def lookthrough(f):
    net = ','.join(f'{NET_ARG[k]}={v:g}' for k, v in f.items())
    p = subprocess.run([sys.executable, os.path.join(BASE, 'night', 'lookthrough.py'), '--what-if', '--castle', CASTLE_ARG, '--net', net],
                       capture_output=True, text=True, timeout=600, cwd=BASE)
    m = re.search(r'★指定 \S+（網 [\d.]+%）\s+(\S+) ([\d.]+)%\s+([\d.]+)〜\s*([\d.]+)%\s+(\d+)件\s+([\d.]+)%\s+NVDA\s+([\d.]+)%', p.stdout)
    if not m:
        return dict(読めず=True, 末尾=p.stdout[-400:])
    return {'最大の1銘柄': f'{m.group(1)} {m.group(2)}%', '半導体の連鎖（下限〜上限）': f'{m.group(3)}〜{m.group(4)}%',
            'NVDA（資産全体）': float(m.group(7)), '未取得': f'{m.group(6)}%', '城': CASTLE_ARG + '（席5社×3%）', '網': net}


def orders():
    out = {}
    for k in ('F_cur', 'A', 'B', 'C', 'D'):
        p = os.path.join(ORD, f'orders_{k}.json')
        if not os.path.exists(p):
            out[k] = '未取得（out/_nx_cache/ndx_swap/run_orders.sh を回す）'
            continue
        d = json.load(open(p))
        run = (d.get('runs') or {}).get('10')
        if not run:
            out[k] = '注文書の結果が無い（shadow_seats の失敗）'
            continue
        nm = run.get('cat_names') or {}
        m1, m12 = run['months'][0], run['months'][-1]
        first = {}
        for key in run.get('cat_keys') or []:
            f = next((x for x in run['months'] if (x['cat_yen'].get(key) or 0) > 0), None)
            first[nm.get(key, key)] = (f['m'] if f else None)
        y12 = {nm.get(key, key): sum(x['cat_yen'].get(key, 0) for x in run['months']) for key in run.get('cat_keys') or []}
        out[k] = {'目標の差し替え': d.get('weights_override'), '今月の個別株': f"¥{m1['castle_yen']:,}（{m1['castle_bought'] or 'なし'}）",
                  '今月の ETF・投資信託': f"¥{m1['etf_yen']:,}（本ごとは下の区分ごとの円）",
                  '今月の区分ごとの円': {nm.get(key, key): v for key, v in m1['cat_yen'].items()},
                  '初めて新しいお金が入る月（12か月のうち）': first, '12か月の区分ごとの円の合計': y12,
                  '区分の比率（今）': {nm.get(key, key): round(run['cat_in'][key]['now'], 1) for key in run.get('cat_keys') or []},
                  '区分の比率（12か月後）': {nm.get(key, key): v for key, v in m12['cat_pct'].items()},
                  '注文書の文（門の画面）': run.get('order_text')}
    return out


def main():
    t0 = time.time()
    F, P = forms()
    res = U.build()
    rows, chains = res['rows'], res['chains']
    UC.add_sox(rows, chains, UC.SOX_DRAG)
    assets = sorted({a for f in F.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, [a for a in assets if a != 'SOX_F'])
    mega['SOX_F'] = mega.get('SMH', 0.0)
    import bestpf_eval as E
    pi, _, _ = E.load_pi()
    _, sim = U.tables()

    U.log('USD の枠')
    tab_usd = U.measure(F, rows, chains, mega=mega)
    ref = json.load(open(os.path.join(BASE, 'out', 'upside_check.json')))['results']['USD・崩れあり（主）'][CUR]
    reg1, ok1 = {}, True
    for k in ('P15π', 'P5π（5%未満）', '最悪の世界', '最大下落'):
        a, b = tab_usd[W_CRASH][CUR][k], ref[k]
        reg1[k] = dict(upside_check=b, この道具=a, 一致=UC.r1(a) == UC.r1(b))
        ok1 = ok1 and UC.r1(a) == UC.r1(b)
    k4, chips = chips_adj(rows, assets)
    vt_usd = variants(F, rows, chains, k4)
    reg2 = regress_variants(vt_usd, tab_usd)
    U.log('回帰の検査', ok1, reg2['max_abs_diff'])
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/ndx_swap_check.py', prereg='out/ndx_swap_prereg.json（fae26ca3）',
               question=P['question'], regression={'① F_cur と out/upside_check.json（USD・崩れあり・小数1桁）': dict(ok=ok1, rows=reg1),
                                                   '② 感度の計算の main と unx_assets.measure（丸める前・1e-9）': {k: v for k, v in reg2.items() if k != 'rows'}})
    if not (ok1 and reg2['ok']):
        doc['decision'] = '回帰の検査に失敗＝止めた'
        json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
        raise SystemExit('回帰の検査に失敗')

    U.log('円の枠')
    ch_jpy, fx_url = U.jpy_chains(chains)
    tab_jpy = U.measure(F, rows, ch_jpy, mega=mega)
    vt_jpy = variants(F, rows, ch_jpy, k4)
    reg3 = regress_variants(vt_jpy, tab_jpy)
    doc['regression']['③ 円の枠でも②と同じ'] = {k: v for k, v in reg3.items() if k != 'rows'}

    U.log('100年の代用')
    cc, seats, cpct = U.castle_copy()

    def g(f):
        o = {}
        for k, v in f.items():
            kk = 'SMH' if k == 'SOX_F' else k
            o[kk] = o.get(kk, 0) + v
        return o
    cent_whole = {nm: U.century_monthly(U.whole(g(f), cc)) for nm, f in F.items()}
    cent_up_etf = {nm: UC.century_up(f) for nm, f in F.items()}
    cent_up_whole = {nm: UC.century_up(U.whole(f, cc)) for nm, f in F.items()}

    # ── 判定 ──
    U.log('判定')
    from unx_final import conds
    frames = {'USD・崩れあり（主）': (vt_usd, W_CRASH), 'USD・ドットコム級なし': (vt_usd, W_DC), '円・崩れあり': (vt_jpy, W_CRASH)}
    judg, ins, read = {}, {}, {}
    for cj, k in COMPS.items():
        alt = KEYS[k]
        judg[cj] = {fn: judge(vt, wn, CUR, alt) for fn, (vt, wn) in frames.items()}
        ins[cj] = {'USD の枠': conds(tab_usd, CUR, alt, cent_whole[CUR], cent_whole[alt]),
                   '円の枠（感度）': conds(tab_jpy, CUR, alt, cent_whole[CUR], cent_whole[alt])}
        main_j = judg[cj]['USD・崩れあり（主）']
        ins_ok = ins[cj]['USD の枠']['3条件すべて（崩れあり窓・書庫:19497 と同じ窓）']
        others = {fn: judg[cj][fn]['まとめ'] for fn in ('USD・ドットコム級なし', '円・崩れあり')}
        read[cj] = dict(まとめ=main_j['まとめ'], 主の判定=main_j['主の判定'], 保険の3条件=ins_ok, 確かめの枠=others,
                        読み=reading(main_j['まとめ'], main_j['主の判定'], ins_ok, others) + ('（参考・判定に使わない）' if k == 'D' else ''))

    # ── 参考（判定に使わない）──
    U.log('参考: 上振れ・転がる積立・本物の窓・下げ・集中')

    def enrich(tab):
        out = {}
        for wn, t in tab.items():
            o = {}
            for nm, r in t.items():
                q, pr_ = UC.upside(sim, r['_raw'], pi)
                rr = {k: v for k, v in r.items() if k != '_raw'}
                rr['上振れ'] = dict(pr_, 内部収益率の分位=q)
                o[nm] = rr
            out[wn] = o
        return out
    up_usd, up_jpy = enrich(tab_usd), enrich(tab_jpy)
    roll = {nm: UC.rolling(f, rows, chains) for nm, f in F.items()}
    realw = {}
    for lab, (a, b) in REAL_WINDOWS.items():
        o = {}
        for nm, f in F.items():
            _, xs = monthly_series(f, rows, chains, a, b)
            o[nm] = stats(xs)
        ms, q = monthly_series({'QQQM': 1}, rows, chains, a, b)
        o['相関（月次）'] = {c: corr(monthly_series({c: 1}, rows, chains, a, b)[1], q) for c in ('ITA', 'SHLD', 'XLV', 'FBT', 'SMH')}
        o['相関（月次）']['ITA×SHLD'] = corr(monthly_series({'ITA': 1}, rows, chains, a, b)[1], monthly_series({'SHLD': 1}, rows, chains, a, b)[1])
        for c in ('QQQM', 'ITA', 'SHLD'):
            o[f'{c} 単体'] = stats(monthly_series({c: 1}, rows, chains, a, b)[1])
        realw[lab] = o
    epi = {}
    for lab, (a, b) in EPISODES.items():
        o = {}
        for nm, f in list(F.items()) + [('QQQM 単体', {'QQQM': 1}), ('ITA 単体', {'ITA': 1}), ('SHLD 単体（2023-09 以前は ITA）', {'SHLD': 1})]:
            _, xs = monthly_series(f, rows, chains, a, b)
            v = 1.0
            for x in xs:
                v *= 1 + x
            o[nm] = round(100 * (v - 1), 1)
        epi[lab] = o
    look = {nm: lookthrough(f) for nm, f in F.items()}
    ords = orders()

    doc.update(
        forms=F, sox=dict(model='SMH の写し − 年0.7pt（SOX_F・upside_check と同じ）', drag=UC.SOX_DRAG),
        K4_半導体の基礎率={c: dict(Chips=(None if chips[c] is None else round(chips[c], 3)), 足す年率=round(100 * k4[c], 3)) for c in assets},
        pi=pi,
        judgments=judg, insurance=ins, reading=read,
        results={'USD・崩れあり（主）': up_usd[W_CRASH], 'USD・ドットコム級なし': up_usd[W_DC], '円・崩れあり': up_jpy[W_CRASH],
                 '円・ドットコム級なし': up_jpy[W_DC],
                 '感度ごとの丸める前の値（USD・崩れあり）': {nm: {VARS_JA[v]: {k: (round(100 * x, 3) if isinstance(x, float) else x)
                                                                      for k, x in r.items() if k != 'worlds'} for v, r in t.items()}
                                                       for nm, t in vt_usd[W_CRASH].items()},
                 '過去の転がる積立（USD・2000-09〜2026-09）': roll,
                 '100年の代用（ETF側だけ・市場との比）': cent_up_etf, '100年の代用（全体の形・個別株＝席の業種の写し）': cent_up_whole,
                 '本物の窓': realw, '下げの局面（累計%・USD）': epi, '中身の集中（lookthrough --what-if）': look,
                 '注文書（shadow_seats --weights・入金20万円・席10）': ords},
        frames={'USD': 'night/bestpf_check.py と同じ（ドル建て）', '円': f'月次のドル建ての値に FRED DEXJPUS の月末の比を掛けた（{fx_url}）・B/C/D はドルの値のまま'},
        castle_copy=dict(seats=seats, castle_pct=cpct, copy={k: round(v, 2) for k, v in cc.items()}),
        caveats=['SHLD の 2023-09 以前は ITA のつなぎ（代理の門を通らない・最後の36か月の相関 0.58）＝ A と B の違いは最後の36か月と B/C/D だけ',
                 '100年の代用では ITA と SHLD はどちらも Aero＋Guns＝A と B は同じ値',
                 'K4 は etf_forward_combo では B・C だけ（D の世界が無かった）＝ここでは事前登録どおり D にも同じものを足した',
                 '楽天・プラス・SOX は SMH の写し − 年0.7pt（100年の代用は SMH として数える）',
                 '注文書の12か月は今日の状態のまま（2027-01 の iDeCo・こどもNISA の開始は模していない・値段は一定）',
                 '判定・配分には使わない（材料）'],
        decision='配分は変えない（報告するだけ・事前登録 R6）', secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    U.log('→', OUT, f'{time.time() - t0:.0f}秒')
    for cj, r in read.items():
        U.log(cj, json.dumps(r, ensure_ascii=False))
        for fn, j in judg[cj].items():
            U.log('   ', fn, j['まとめ'], {v: (x['判定'], x['差']['平均'], x['差']['最悪'], x['差']['確率'], x['差']['ぶれ']) for v, x in j['感度'].items()})
    for nm, r in up_usd[W_CRASH].items():
        u = r['上振れ']; q = u['内部収益率の分位']; ro = roll[nm]['20年']
        U.log(f"{nm[:24]:<24} P15π {r['P15π']:5.1f} P5 {r['P5π（5%未満）']:4.1f} 最悪 {r['最悪の世界']:5.2f} 平均 {r['π加重の平均の年率']:5.2f} "
              f"ぶれ {r['ぶれ']:4.1f} 下落 {r['最大下落']:6.1f} P20 {u['P20（道の束）']:4.1f} 90点 {q['90%点']:4.1f} | 過去20年 中央{ro['中央']:5.2f} 最小{ro['最小']:5.2f} | "
              f"NVDA {look[nm].get('NVDA（資産全体）')} 半導体 {look[nm].get('半導体の連鎖（下限〜上限）')}")


if __name__ == '__main__':
    main()
