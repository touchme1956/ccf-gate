#!/usr/bin/env python3
"""night/sp500_compare.py — 今の配分を S&P500 と同じ物差しで並べる（2026-10-16・ユーザー「S&P500との比較だして」）

参考・判定なし。読むだけ（門・採点・配分〔portfolio.json〕・注文書に触れない・どの結果でも配分は変えない）。
形（ETF 側の%・個別株は物差しの外。100年の代用だけ『全体の形』＝個別株を今の席の業種の写しで足す〔unx_final と同じ〕）:
  今        … portfolio.json の target.ami_weights（IFREE-NDX は同じ指数の QQQM の行で数える・目標0%の本は入れない）
  S&P500    … VOO 100
  NASDAQ100 … QQQM 100（参考）
物差し（どれも既存の道具の式をそのまま使う・新しい式は無い）:
  ① 模型: night/unx_assets.measure（bestpf_check・upside_check と同じ5つの世界と π）＋ upside_check.upside（道の束の P20・内部収益率の分位）
     ＋ 世界ごとの S&P500 との差
  ② 過去の積立: 2000-09〜2026-09・USD と円・毎月同額・転がる20年/15年/10年の内部収益率（bestpf_realized.irr_monthly）と S&P500 との差
  ③ 暦年（2001〜2025・USD）の年率・S&P500 に勝った年の数・月次の相関とベータ・差のぶれ
  ④ 期間の年率（全期間・2006-05〜・直近10年・直近5年・直近3年）と下げの局面の累計（ndx_swap_check の EPISODES）
  ⑤ 100年の代用: upside_check.century_up（ETF 側と全体の形）＝米国株全体（French の市場）との比
  ⑥ 中身の集中: 今＝night/lookthrough.py --what-if（城は今の席×castle_rank_weights）／S&P500＝VOO の中身（Alpha Vantage ETF_PROFILE・定数）
  ⑦ 実際の成績: out/returns.json（📈成績と同じ数字）を写す
回帰の検査: S&P500 と NASDAQ100 の USD・崩れあり窓の P15π・P5π・最悪の世界・最大下落が out/upside_check.json と小数1桁で一致しなければ止める。

使い方: python3 night/sp500_compare.py  → out/sp500_compare.json
"""
import ast, datetime, json, math, os, re, subprocess, sys, time

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import unx_assets as U          # noqa: E402
import upside_check as UC       # noqa: E402
import ndx_swap_check as N      # noqa: E402

OUT = os.path.join(BASE, 'out', 'sp500_compare.json')
W_CRASH, W_DC = UC.W_CRASH, UC.W_DC
FIRST, END = UC.FIRST, UC.END
CUR, SPX, NDX = '今（2026-10-15〜・ETF 側）', 'S&P500（VOO）', 'NASDAQ100（QQQM・参考）'
MAP = {'IFREE-NDX': 'QQQM'}     # 同じ指数（器の費用の差は notes に）
PERIODS = {'全期間 2000-09〜2026-09': (200009, 202609), 'ITA が本物の窓 2006-05〜2026-09': (200605, 202609),
           '直近10年 2016-10〜2026-09': (201610, 202609), '直近5年 2021-10〜2026-09': (202110, 202609),
           '直近3年 2023-10〜2026-09（SHLD が本物の窓）': (202310, 202609)}
# VOO の中身（Alpha Vantage ETF_PROFILE・last_updated 2026-10-16 00:01 UTC・保有の重み）。上位10と、lookthrough.py の SEMI に入る社だけ写す
VOO_ASOF = '2026-10-16（Alpha Vantage ETF_PROFILE VOO）'
VOO_TOP10 = {'NVDA': 8.08, 'AAPL': 7.03, 'MSFT': 5.70, 'AMZN': 3.84, 'GOOGL': 3.01, 'AVGO': 2.65, 'GOOG': 2.40, 'META': 1.90, 'MU': 1.63, 'TSLA': 1.57}
VOO_SEMI = {'NVDA': 8.08, 'AVGO': 2.65, 'AMD': 1.16, 'AMAT': 0.55, 'LRCX': 0.57, 'KLAC': 0.35, 'MU': 1.63, 'INTC': 0.67, 'TXN': 0.36,
            'QCOM': 0.27, 'ADI': 0.27, 'NXPI': 0.09, 'MRVL': 0.28, 'MCHP': 0.06, 'ON': 0.04, 'SWKS': 0.02, 'TER': 0.08}
VOO_IT_SECTOR = 37.7
COST_NOTE = ('今の NASDAQ100 は iFreeNEXT（信託報酬 税込0.495%）で、模型の QQQM（0.15%）より年0.345pt 重い＝ETF 側では年約0.15pt（40/90）。'
             'S&P500 を NISA の eMAXIS Slim 米国株式（0.0814%）で持つなら VOO（0.03%）より年約0.05pt 重い＝模型の差は年約0.1pt 縮む（信託報酬の差だけ・ここでは引いていない）')


def dca_mult(irr_pct, n=240):
    """年率の内部収益率 → 毎月の初めに同額を n か月入れた最後の額÷投じた額（bestpf_realized.irr_monthly と同じ置き方）"""
    g = (1 + irr_pct / 100) ** (1 / 12) - 1
    return n if g == 0 else ((1 + g) ** n - 1) / g * (1 + g) / n


def forms():
    tg = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    cur = {}
    for k, v in tg['ami_weights'].items():
        if not v:
            continue
        a = MAP.get(k, k)
        cur[a] = cur.get(a, 0) + float(v)
    return {CUR: cur, SPX: {'VOO': 100.0}, NDX: {'QQQM': 100.0}}, tg


def semi_set():
    """lookthrough.py の SEMI を ast で読む（実行しない＝あちらは import で走る）"""
    src = open(os.path.join(BASE, 'night', 'lookthrough.py'), encoding='utf-8').read()
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'SEMI' for t in node.targets):
            return set(ast.literal_eval(node.value))
    raise SystemExit('lookthrough.py の SEMI が読めない')


def irr_windows(s, n):
    """→ [(年率の内部収益率, 最後の額÷投じた額)]"""
    import bestpf_realized as BR
    return [BR.irr_monthly(s[i:i + n]) for i in range(len(s) - n + 1)]


def realized(F, rows, chains):
    """② 転がる積立の窓ごとの内部収益率と S&P500 との差"""
    ser = {nm: N.monthly_series(f, rows, chains, FIRST, END) for nm, f in F.items()}
    ms = ser[SPX][0]
    out = {}
    for yrs in (20, 15, 10):
        n = 12 * yrs
        both = {nm: irr_windows(s, n) for nm, (_, s) in ser.items()}
        irr = {nm: [a for a, _ in v] for nm, v in both.items()}
        o = {'窓の数': len(irr[SPX]), '起点': f'{ms[0]}〜{ms[len(irr[SPX]) - 1]}'}
        for nm, v in irr.items():
            vs = sorted(v)
            mult = sorted(b for _, b in both[nm])
            o[nm] = dict(最小=round(100 * vs[0], 2), 中央=round(100 * vs[len(vs) // 2], 2), 最大=round(100 * vs[-1], 2),
                         以上15=round(100 * sum(x >= 0.15 for x in v) / len(v), 1), 今日で終わる窓=round(100 * v[-1], 2),
                         倍率の中央=round(mult[len(mult) // 2], 2), 倍率の最小=round(mult[0], 2), 今日で終わる窓の倍率=round(both[nm][-1][1], 2))
        for nm in (CUR, NDX):
            d = [a - b for a, b in zip(irr[nm], irr[SPX])]
            ds = sorted(d)
            worst_i = min(range(len(d)), key=lambda i: d[i])
            o[f'{nm} − S&P500'] = dict(勝った窓の割合=round(100 * sum(x > 0 for x in d) / len(d), 1), 差の最小=round(100 * ds[0], 2),
                                       差の中央=round(100 * ds[len(ds) // 2], 2), 差の最大=round(100 * ds[-1], 2),
                                       差が最小の窓の起点=ms[worst_i])
        out[f'{yrs}年'] = o
    return out, ser


def calendar(ser):
    """③ 暦年（2001〜2025）"""
    yrs = list(range(2001, 2026))
    ann = {}
    for nm, (ms, s) in ser.items():
        by = {}
        for m, r in zip(ms, s):
            by.setdefault(m // 100, []).append(r)
        ann[nm] = {y: math.prod(1 + r for r in by[y]) - 1 for y in yrs if len(by.get(y, [])) == 12}
    out = {'年ごと': {y: {nm: round(100 * ann[nm][y], 1) for nm in ann} for y in yrs}}
    for nm in (CUR, NDX):
        w = [y for y in yrs if ann[nm][y] > ann[SPX][y]]
        out[f'{nm} が S&P500 に勝った年'] = f'{len(w)}/{len(yrs)}'
        out[f'{nm} の最悪の年'] = f'{min(yrs, key=lambda y: ann[nm][y])}（{100 * min(ann[nm].values()):.1f}%）'
    out['S&P500 の最悪の年'] = f'{min(yrs, key=lambda y: ann[SPX][y])}（{100 * min(ann[SPX].values()):.1f}%）'
    s_spx = np.array(ser[SPX][1])
    for nm in (CUR, NDX):
        x = np.array(ser[nm][1])
        c = float(np.corrcoef(x, s_spx)[0, 1])
        beta = float(np.cov(x, s_spx, bias=True)[0, 1] / np.var(s_spx))
        te = float(np.std(x - s_spx) * math.sqrt(12))
        out[f'{nm} の月次（2000-09〜2026-09）'] = dict(S_P500との相関=round(c, 3), ベータ=round(beta, 2), 差のぶれ_年率=round(100 * te, 1))
    return out


def periods(F, rows, chains):
    """④ 期間の年率・下げの局面の累計"""
    out = {}
    for lab, (a, b) in PERIODS.items():
        out[lab] = {nm: N.stats(N.monthly_series(f, rows, chains, a, b)[1]) for nm, f in F.items()}
    ep = {}
    for lab, (a, b) in N.EPISODES.items():
        ep[lab] = {nm: round(100 * (math.prod(1 + r for r in N.monthly_series(f, rows, chains, a, b)[1]) - 1), 1) for nm, f in F.items()}
    return out, ep


def concentration(cur, tg):
    """⑥ 今＝lookthrough --what-if（城は今の席×castle_rank_weights）／S&P500＝VOO の中身"""
    import alloc_check as AC
    order, prox_w, _ = AC.seats()
    cpct = float(tg.get('shiro_castle_pct') or 0)
    castle = ','.join(f'{t}={cpct * w:g}' for t, w in prox_w.items())
    net = ','.join(f'{k}={v:g}' for k, v in cur.items())
    p = subprocess.run([sys.executable, os.path.join(BASE, 'night', 'lookthrough.py'), '--what-if', '--castle', castle, '--net', net],
                       capture_output=True, text=True, timeout=600, cwd=BASE)
    m = re.search(r'★指定 \S+（網 [\d.]+%）\s+(\S+) ([\d.]+)%\s+([\d.]+)〜\s*([\d.]+)%\s+(\d+)件\s+([\d.]+)%\s+NVDA\s+([\d.]+)%', p.stdout)
    now = ({'読めず': True, '末尾': p.stdout[-400:]} if not m else
           {'最大の1銘柄': f'{m.group(1)} {m.group(2)}%', '半導体の連鎖（下限〜上限）': f'{m.group(3)}〜{m.group(4)}%',
            'NVDA（資産全体）': float(m.group(7)), '未取得': f'{m.group(6)}%', '城': castle + f'（席{len(order)}社・個別株{cpct:g}%）', '網': net})
    S = semi_set()
    extra = sorted(set(VOO_SEMI) - S)
    if extra:
        raise SystemExit(f'VOO_SEMI に SEMI の外の社: {extra}')
    spx = {'NVDA': VOO_TOP10['NVDA'], '上位10社': round(sum(VOO_TOP10.values()), 1), 'Alphabet（2種類の合計）': round(VOO_TOP10['GOOGL'] + VOO_TOP10['GOOG'], 2),
           '半導体の連鎖（lookthrough と同じ SEMI）': round(sum(VOO_SEMI.values()), 1), '情報技術の業種': VOO_IT_SECTOR, '出所': VOO_ASOF,
           'SEMI のうち S&P500 に無い社': sorted(S - set(VOO_SEMI))}
    return {CUR + '＋個別株（資産全体）': now, SPX: spx}


def returns_copy():
    """⑦ 📈成績（out/returns.json）"""
    r = json.load(open(os.path.join(BASE, 'out', 'returns.json')))
    pct = lambda x: None if x is None else round(100 * x, 1)  # noqa: E731
    c = r.get('castle') or {}
    return {'作った日': r.get('generated'), '値段の日': r.get('bench_asof'), '保有の日数': r.get('span_days'),
            '対象': [p.get('t') or p.get('ticker') for p in r.get('positions', [])],
            '投じた円': r['compared']['cost_jpy'],
            '保有（終値・配当なし）%': pct(r['compared']['ret']), '保有（配当込み）%': pct(r['compared_tr']['ret']),
            'S&P500（配当込み・同じ円を同じ日に）%': pct(r['benchmark']['ret']),
            'S&P500 の幅（買付日の推定の幅）%': [pct(x) for x in (r.get('benchmark_range') or [])],
            'NASDAQ100（QQQM・同じ円を同じ日に）%': pct((r.get('benchmark_qqqm') or {}).get('ret')),
            '個別株だけ': {'銘柄': c.get('tickers'), '個別株（配当込み）%': pct((c.get('compared_tr') or {}).get('ret')),
                       'S&P500%': pct((c.get('spy') or {}).get('ret')), 'QQQM%': pct((c.get('qqqm') or {}).get('ret'))},
            '注意': r.get('annualize_why')}


def main():
    t0 = time.time()
    F, tg = forms()
    res = U.build()
    rows, chains = res['rows'], res['chains']
    miss = sorted({a for f in F.values() for a in f} - set(rows))
    if miss:
        raise SystemExit(f'模型に無い本: {miss}')
    assets = sorted({a for f in F.values() for a in f})
    mega = U.mega_map(rows, assets)
    import bestpf_eval as E
    pi, _, _ = E.load_pi()
    _, sim = U.tables()

    U.log('USD の枠')
    tab_usd = U.measure(F, rows, chains, mega=mega)
    ref = json.load(open(os.path.join(BASE, 'out', 'upside_check.json')))['results']['USD・崩れあり（主）']
    reg, ok = {}, True
    for mine, theirs in ((SPX, 'R_VOO100（S&P500）'), (NDX, 'R_QQQM100（NASDAQ100だけ）')):
        d = {}
        for k in ('P15π', 'P5π（5%未満）', '最悪の世界', '最大下落'):
            a, b = tab_usd[W_CRASH][mine][k], ref[theirs][k]
            d[k] = dict(upside_check=b, この道具=a, 一致=UC.r1(a) == UC.r1(b))
            ok = ok and UC.r1(a) == UC.r1(b)
        reg[mine] = d
    U.log('回帰の検査', json.dumps(reg, ensure_ascii=False), ok)
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/sp500_compare.py', kind='参考・判定なし（配分は変えない）',
               question='ユーザー「S&P500との比較だして」', forms=F, regression=dict(ok=ok, rows=reg))
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
                q, pr = UC.upside(sim, r['_raw'], pi)
                rr = {k: v for k, v in r.items() if k != '_raw'}
                rr['上振れ'] = dict(pr, 内部収益率の分位=q,
                                  **{'20年の積立の倍率（分位から・最後の額÷投じた額）': {k: round(dca_mult(v), 2) for k, v in q.items()}})
                o[nm] = rr
            for nm in (CUR, NDX):
                a, b = t[nm]['_raw'], t[SPX]['_raw']
                o[nm]['S&P500 との差'] = dict(世界ごとの年率={k: round(100 * (a['worlds'][k] - b['worlds'][k]), 2) for k in a['worlds']},
                                            π加重の平均=round(100 * (a['mean_pi'] - b['mean_pi']), 2), 最悪の世界=round(100 * (a['worst'] - b['worst']), 2),
                                            P15π=round(100 * (a['P15'] - b['P15']), 1), P5π=round(100 * (a['P5'] - b['P5']), 1),
                                            P0π=round(100 * (a['P0'] - b['P0']), 1), ぶれ=round(100 * (a['vol'] - b['vol']), 1),
                                            最大下落=round(100 * (a['mdd'] - b['mdd']), 1))
            out[wn] = o
        return out

    U.log('上振れの分位')
    up_usd, up_jpy = enrich(tab_usd), enrich(tab_jpy)
    U.log('過去の積立（USD・円）')
    roll_usd, ser_usd = realized(F, rows, chains)
    roll_jpy, _ = realized(F, rows, ch_jpy)
    U.log('暦年・期間・下げの局面')
    cal = calendar(ser_usd)
    per, ep = periods(F, rows, chains)
    per_jpy, ep_jpy = periods(F, rows, ch_jpy)
    U.log('100年の代用')
    cent = {nm: UC.century_up(f) for nm, f in F.items()}
    cc, seats, cpct = U.castle_copy()
    cent_whole = {CUR + '＋個別株（席の業種の写し）': UC.century_up(U.whole(F[CUR], cc))}
    U.log('中身の集中')
    conc = concentration(F[CUR], tg)
    rc = returns_copy()

    doc.update(
        pi=pi,
        notes=['ETF 側だけ（個別株は物差しの外）。100年の代用だけ全体の形（個別株＝今の席の業種の写し・銘柄ごとのぶれは入らない）',
               'SHLD の 2023-09 以前は ITA のつなぎ（unx_final・upside_check と同じ）・世界 B/C/D は円の枠でもドルのまま（unx_final と同じ）',
               '過去の積立・期間・下げの局面は 2000-09〜2026-09 の実績（つないだ系列・手取りの調整は bestpf_realized と同じ）＝予想ではない',
               '100年の代用の比べる相手は French の市場（米国株全体）＝S&P500 そのものではないが、ほぼ同じ動き（大型株が大半）',
               COST_NOTE],
        results={'模型 USD・崩れあり（主）': up_usd[W_CRASH], '模型 USD・ドットコム級なし': up_usd[W_DC],
                 '模型 円・崩れあり': up_jpy[W_CRASH], '模型 円・ドットコム級なし': up_jpy[W_DC],
                 '過去の転がる積立（USD）': roll_usd, '過去の転がる積立（円）': roll_jpy, '暦年（USD）': cal,
                 '期間の年率（USD）': per, '下げの局面の累計（USD）': ep, '期間の年率（円）': per_jpy, '下げの局面の累計（円）': ep_jpy,
                 '100年の代用（ETF 側だけ・市場との比）': cent, '100年の代用（全体の形）': cent_whole,
                 '中身の集中': conc, '実際の成績（📈成績・out/returns.json）': rc},
        decision='参考・判定なし（配分は変えない）', secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    U.log('→', OUT, f'{time.time() - t0:.0f}秒')
    m = up_usd[W_CRASH]
    for nm in F:
        r = m[nm]; u = r['上振れ']; q = u['内部収益率の分位']; ro = roll_usd['20年'][nm]
        U.log(f"{nm[:22]:<22} 平均 {r['π加重の平均の年率']:5.2f} 最悪 {r['最悪の世界']:5.2f} 世界 {r['世界ごとの年率']} | P15π {r['P15π']:5.1f} P20 {u['P20（道の束）']:5.1f} "
              f"P5 {r['P5π（5%未満）']:4.1f} P0 {r['P0π（元本割れ）']:4.1f} 中央 {q['50%点']:5.1f} 10点 {q['10%点']:5.1f} 90点 {q['90%点']:5.1f} | "
              f"ぶれ {r['ぶれ']:4.1f} 下落 {r['最大下落']:6.1f} | 過去20年 中央{ro['中央']:5.1f} 最小{ro['最小']:5.1f} 最大{ro['最大']:5.1f} 今日{ro['今日で終わる窓']:5.1f}")


if __name__ == '__main__':
    main()
