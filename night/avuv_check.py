#!/usr/bin/env python3
"""night/avuv_check.py — AVUV（Avantis 米国小型バリュー）を今の配分に足すのは？（2026-10-16・ユーザー「AVUV」・etf_add の続き）

読むだけ。門・採点・配分（portfolio.json）・注文書には触れない。事前登録 out/avuv_prereg.json（0709d1d5）どおり。
  AVUV の行: night/etf_forward_rank.py の外の道具の口（C・DATA・JPM_MAP・GMO_MAP・EXTRA_*）に足し、X.sec_env の中で R.main(write=False)
    を回して AVUV の行と毎月の値を受け取り、night/unx_assets.build の行と毎月の値に差し込む（unx の build は1バイトも変えない）。
    同じ R.main で作った VBR の行が unx の VBR と一致することで、同じ式で作れたことを確かめる。
  2019-09 以前の代わり: DFSVX・VISVX・DFFVX・French の SMALL HiBM（AVUV の経費率/12 を引く）のうち AVUV の本物 2019-10〜2026-09 との
    月次の相関が最も高いもの（同点は DFSVX）・0.90 未満なら止める。
  形: 今（NASDAQ100 40 / SMH 25 / ITA 5 / SHLD 5 / XLV 7.5 / FBT 7.5）・+AVUV・+VBR・+GDX（各 NASDAQ100 から5）。判定は etf_add と同じ。
  100年の代用の (3): AVUV と VBR を French の SMALL HiBM（1926〜）で写す（unx_assets.century_parts の部品にこの道具の中だけで足す）。
回帰の検査: ① 今・+VBR・+GDX が out/etf_add_check.json と小数1桁で一致 ② 感度の主が measure と 1e-9 以内（USD・円）
  ③ R.main で作った VBR の A1・A2・B・C が unx の VBR と 1e-12 以内で一致。どれかが外れれば止める。
使い方: python3 night/avuv_check.py → out/avuv_check.json
"""
import csv, datetime, json, math, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))

OUT = os.path.join(BASE, 'out', 'avuv_check.json')
PREREG = os.path.join(BASE, 'out', 'avuv_prereg.json')
CDIR = os.path.join(BASE, 'out', '_nx_cache', 'avuv')
AV_PROFILE = os.path.join(CDIR, 'AVUV_av_profile_20261016.json')
ETFD = os.path.join(CDIR, 'ETFD_20261016.csv')
PROXY_CANDS = ['DFSVX', 'VISVX', 'DFFVX', 'FRENCH_SMALL_HIBM']
OVL = (201910, 202609)
SPLICE_LAST = 201909
SLOT = 5
CUR = '今'
KEYS = {'AVUV': '+AVUV（NASDAQ100 から5）', 'VBR': '+VBR（etf_add と同じ）', 'GDX': '+GDX（etf_add と同じ）'}
ETF_ADD_KEYS = {'今': '今', '+VBR（etf_add と同じ）': '+VBR', '+GDX（etf_add と同じ）': '+GDX'}


def rakuten_tickers():
    s = open(ETFD, 'rb').read().decode('utf-8-sig')
    return {r[1] for r in csv.reader(s.splitlines()) if len(r) > 1 and r[1]}


def french_small_hibm(M, er=0.0):
    s = M.french_series('6_Portfolios_2x3', want='Average Value Weighted Returns')['SMALL HiBM']
    return {k: v - er / 12 for k, v in s.items()}


def stats(s, ms):
    xs = [s[m] for m in ms]
    g = math.exp(sum(math.log1p(x) for x in xs) * 12 / len(xs)) - 1
    mu = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs)) * math.sqrt(12)
    v, peak, mdd = 1.0, 1.0, 0.0
    for x in xs:
        v *= 1 + x
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return dict(年率=round(100 * g, 2), ぶれ=round(100 * sd, 1), 最大下落=round(100 * mdd, 1), 月数=len(xs))


def main():
    import mw_common as M
    import etf_forward_rank as R
    import bestpf_ext as X
    import unx_assets as U
    import upside_check as UC
    import ndx_swap_check as N
    t0 = time.time()
    W_CRASH, W_DC = UC.W_CRASH, UC.W_DC
    P = json.load(open(PREREG))
    F = {k: dict(v) for k, v in P['forms_etf_side_percent_of_total'].items()}
    prof = json.load(open(AV_PROFILE))
    avuv_er = float(prof['net_expense_ratio'])
    rk = rakuten_tickers()
    avail = {t: (t in rk) for t in ('AVUV', 'VBR', 'GDX', 'VIOV', 'DES')}

    # ── 代わりを選ぶ ──
    avuv = {m: v for m, v in M.yahoo('AVUV').items() if m <= OVL[1]}
    ks = [m for m in R.months(*OVL) if m in avuv]
    if len(ks) != len(R.months(*OVL)):
        raise SystemExit(f'AVUV の本物の月が欠けている（{len(ks)} / {len(R.months(*OVL))}）')
    pick, raw_corr = {}, {}
    for c in PROXY_CANDS:
        p = french_small_hibm(M, avuv_er) if c == 'FRENCH_SMALL_HIBM' else M.yahoo(c)
        kk = [m for m in ks if m in p]
        r = M.corr([avuv[m] for m in kk], [p[m] for m in kk])
        raw_corr[c] = r
        full = all(m in p for m in R.months(200009, SPLICE_LAST))
        pick[c] = dict(重なる月=len(kk), 相関=round(r, 4), 年率_AVUV=round(100 * R.geo(avuv, kk), 2), 年率_代わり=round(100 * R.geo(p, kk), 2),
                       最初の月=min(p), 主の窓を埋められる=full)
    ok = [c for c in PROXY_CANDS if pick[c]['主の窓を埋められる']]
    best = max(ok, key=lambda c: (raw_corr[c], c == 'DFSVX'))
    U.log('代わり', best, pick[best])
    if raw_corr[best] < 0.90:
        json.dump(dict(generated=datetime.date.today().isoformat(), decision='測れない（代わりの相関 < 0.90）', proxies=pick), open(OUT, 'w'),
                  ensure_ascii=False, indent=1)
        raise SystemExit('代わりの相関が 0.90 に届かない＝測れない')

    # ── unx の行（そのまま）──
    res = U.build()
    rows, chains = res['rows'], res['chains']

    # ── AVUV を R の口に足して R.main を回す（X.sec_env の中＝SIC の写しへ書く）──
    # X.rank_result の後の R.C・R.DATA には R7 の本（合成の代わり BESTPF_PX_* を持つ）が残る＝unx の swap_R と同じく
    # R の25本＋AVUV だけにして回し、終われば元へ戻す
    rows0 = res['rows0']
    r25 = [c for c in rows0 if not rows0[c].get('r7_new')]
    oc, od = R.C, R.DATA
    try:
        R.C = {c: oc[c] for c in r25}
        R.DATA = {c: od[c] for c in r25}
        R.C['AVUV'] = dict(ja='米国小型バリュー（Avantis・割安∧収益性）', veh='AVUV（楽天では買えない・松井証券ほか）', us=True, k=0.10)
        R.DATA['AVUV'] = ('AVUV', best, SPLICE_LAST)
        if best == 'FRENCH_SMALL_HIBM':
            R.EXTRA_PROXY['FRENCH_SMALL_HIBM'] = lambda: french_small_hibm(M, avuv_er)
        R.JPM_MAP['AVUV'] = R.JPM_MAP['VBR']
        R.GMO_MAP['AVUV'] = list(R.GMO_MAP['VBR'])
        R.EXTRA_STYLE['AVUV'] = 'VBR'
        hold = [[h['symbol'], float(h['weight'])] for h in prof['holdings'] if h.get('symbol') and h['symbol'] != 'n/a']
        R.EXTRA_PROFILES['AVUV'] = dict(er=avuv_er, dy=float(prof['dividend_yield']), holdings=hold)
        U.log('R.main（R の25本＋AVUV）', len(R.C))
        with X.sec_env():
            ext = R.main(write=False)
        avuv_meta = dict(R.C['AVUV'])
    finally:
        R.C, R.DATA = oc, od
    R.C['AVUV'] = avuv_meta       # 判定の段の chips_adj が『米国の本』と読めるように（R.DATA には足さない）
    rowsR, chainsR = ext['rows'], ext['chains']
    reg3 = {}
    for k in ('A1', 'A2', 'B', 'C', 'A1_gross'):
        reg3[k] = dict(unx=rows['VBR'][k], R_main=rowsR['VBR'][k], 差=abs(rows['VBR'][k] - rowsR['VBR'][k]))
    ok3 = all(v['差'] <= 1e-12 for v in reg3.values()) and chainsR['VBR'] == chains['VBR']
    rows['AVUV'] = dict(rowsR['AVUV'])
    chains['AVUV'] = dict(chainsR['AVUV'])
    if any(m not in chains['AVUV'] for m in R.months(UC.FIRST, UC.END)):
        raise SystemExit('AVUV の毎月の値が主の窓にそろわない')
    U.log('AVUV の行', {k: round(100 * rows['AVUV'][k], 2) for k in ('A1', 'A2', 'B', 'C')}, 'VBR', {k: round(100 * rows['VBR'][k], 2) for k in ('A1', 'A2', 'B', 'C')})

    assets = sorted({a for f in F.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, assets)
    import bestpf_eval as E
    pi, _, _ = E.load_pi()
    _, sim = U.tables()

    U.log('USD の枠')
    tab_usd = U.measure(F, rows, chains, mega=mega)
    ea = json.load(open(os.path.join(BASE, 'out', 'etf_add_check.json')))['results']['機械1 USD・崩れあり（主）']
    reg1, ok1 = {}, True
    for mine, theirs in ETF_ADD_KEYS.items():
        for k in ('P15π', 'P5π（5%未満）', '最悪の世界', '最大下落'):
            a, b = tab_usd[W_CRASH][mine][k], ea[theirs][k]
            same = UC.r1(a) == UC.r1(b)
            reg1[f'{mine}・{k}'] = dict(etf_add=b, この道具=a, 一致=same)
            ok1 = ok1 and same
    k4, chips = N.chips_adj(rows, assets)
    vt_usd = N.variants(F, rows, chains, k4)
    reg2 = N.regress_variants(vt_usd, tab_usd)
    U.log('回帰の検査', ok1, reg2['max_abs_diff'], ok3)
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/avuv_check.py', prereg='out/avuv_prereg.json（0709d1d5）',
               question=P['question'],
               regression={'① 今・+VBR・+GDX と out/etf_add_check.json（USD・崩れあり・小数1桁）': dict(ok=ok1, rows=reg1),
                           '② 感度の計算の主と unx_assets.measure（USD・丸める前・1e-9）': {k: v for k, v in reg2.items() if k != 'rows'},
                           '③ R.main で作った VBR と unx の VBR（1e-12）': dict(ok=ok3, rows=reg3)})
    if not (ok1 and reg2['ok'] and ok3):
        doc['decision'] = '回帰の検査に失敗＝止めた'
        json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
        raise SystemExit('回帰の検査に失敗')

    U.log('円の枠')
    ch_jpy, fx_url = U.jpy_chains(chains)
    tab_jpy = U.measure(F, rows, ch_jpy, mega=mega)
    vt_jpy = N.variants(F, rows, ch_jpy, k4)
    reg4 = N.regress_variants(vt_jpy, tab_jpy)
    doc['regression']['④ 円の枠でも②と同じ'] = {k: v for k, v in reg4.items() if k != 'rows'}
    if not reg4['ok']:
        doc['decision'] = '回帰の検査に失敗（円）＝止めた'
        json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
        raise SystemExit('回帰の検査に失敗（円）')

    # ── 100年の代用（AVUV と VBR を French の SMALL HiBM で写す・この道具の中だけ）──
    C = U.century_parts()
    sv = french_small_hibm(M, 0.0)
    C['parts']['AVUV'] = sv
    C['parts']['VBR'] = sv
    U.MONTHLY_OK.update({'AVUV', 'VBR'})
    cc, seats, cpct = U.castle_copy()
    cent = {nm: U.century_monthly(U.whole(f, cc)) for nm, f in F.items()}

    # ── 判定 ──
    from unx_final import conds
    frames = {'USD・崩れあり（主）': (vt_usd, W_CRASH), 'USD・ドットコム級なし': (vt_usd, W_DC), '円・崩れあり': (vt_jpy, W_CRASH)}
    comps = {'AVUV の価値（+AVUV − 今）': (KEYS['AVUV'], CUR), '参考: 器の差（+AVUV − +VBR）': (KEYS['AVUV'], KEYS['VBR']),
             '参考: GDX と比べる（+AVUV − +GDX）': (KEYS['AVUV'], KEYS['GDX']), '参考: VBR の価値（+VBR − 今・etf_add と同じ）': (KEYS['VBR'], CUR),
             '参考: GDX の価値（+GDX − 今・etf_add と同じ）': (KEYS['GDX'], CUR)}
    judg, ins = {}, {}
    for cj, (a, b) in comps.items():
        judg[cj] = {fn: N.judge(vt, wn, a, b) for fn, (vt, wn) in frames.items()}
        cu = conds(tab_usd, a, b, cent[a], cent[b])
        c12 = bool(cu[W_CRASH]['(1) P15π の低下 ≤ 1.5pt'] and cu[W_CRASH]['(2) 最悪の世界・P5π・最大下落がすべて良い'])
        c3 = cu['(3) 100年の代用（全体の形）の20年・30年の中央が下がらず下位10%が上がる']
        ins[cj] = dict(USD=cu, 状態=('すべて満たす' if (c12 and c3) else ('(1)(2) を満たす・(3) は測れない' if (c12 and c3 is None) else '満たさない')))

    def main_of(cj):
        return judg[cj]['USD・崩れあり（主）']
    m = main_of('AVUV の価値（+AVUV − 今）')
    others = {fn: judg['AVUV の価値（+AVUV − 今）'][fn]['まとめ'] for fn in ('USD・ドットコム級なし', '円・崩れあり')}
    if m['まとめ'] == '堅い価値あり':
        g = main_of('参考: GDX の価値（+GDX − 今・etf_add と同じ）')
        da, dg = m['感度']['主']['差'], g['感度']['主']['差']
        order = sorted([('AVUV', da), ('GDX', dg)], key=lambda t: (-t[1]['平均'], -t[1]['最悪']))
        rd = 'R1: AVUV も足す候補（主の Δ平均 の順: ' + ' ＞ '.join(t[0] for t in order) + '）'
        split = {k: v for k, v in others.items() if v != '堅い価値あり'}
        if split:
            rd += '——窓・通貨で割れる（' + '・'.join(f'{k} は {v}' for k, v in split.items()) + '）'
    elif m['まとめ'] == '前提しだい' and ins['AVUV の価値（+AVUV − 今）']['状態'] == 'すべて満たす':
        rd = 'R2: 保険として足すのは筋が通る（好みの差）'
    else:
        rd = f"R3: 足す根拠はデータに無い（まとめ {m['まとめ']}・主 {m['主の判定']}・保険 {ins['AVUV の価値（+AVUV − 今）']['状態']}）"
    v = main_of('参考: 器の差（+AVUV − +VBR）')
    if v['まとめ'] == '堅い価値あり':
        r4 = 'R4: 同じ小型バリューの賭けなら AVUV の器のほうが良い'
    elif v['まとめ'] == '堅い価値なし〜小さい' and v['主の判定'] == '価値なし':
        r4 = 'R4: VBR の器で足りる'
    else:
        r4 = f"R4: 器の差は決まりでははっきりしない（まとめ {v['まとめ']}・主 {v['主の判定']}）"
    read = dict(R1_R3=rd, R4=r4, R5=f"楽天の海外ETF一覧（2026-10-16）に AVUV は{'ある' if avail['AVUV'] else '無い'}——楽天で買える同じ賭けは VBR（etf_add では『前提しだい』）",
                R7='配分は変えない（報告するだけ）', 確かめの枠=others)

    # ── 参考 ──
    def show(r):
        return {k: r[k] for k in ('P15π', 'P15π（A2を外す）', 'P5π（5%未満）', 'P0π（元本割れ）', '最悪の世界', 'π加重の平均の年率', 'ぶれ', '最大下落',
                                  '崩れ2000型_16〜18年目', '過去の転がる20年で15%以上', '世界ごとの年率')}
    table = {}
    for nm in F:
        r = tab_usd[W_CRASH][nm]
        q, pr_ = UC.upside(sim, r['_raw'], pi)
        table[nm] = dict(show(r), 上振れ=dict(pr_, 内部収益率の分位=q))
    roll = {nm: UC.rolling(f, rows, chains) for nm, f in F.items()}
    ways = {}
    cur = F[CUR]
    tot = sum(cur.values())
    pp = {c: w * (tot - SLOT) / tot for c, w in cur.items()}; pp['AVUV'] = SLOT
    n10 = dict(cur); n10['QQQM'] -= 2 * SLOT; n10['AVUV'] = 2 * SLOT
    fw = {CUR: cur, '+AVUV（按分P5）': pp, '+AVUV（N10）': n10}
    vw = N.variants(fw, rows, chains, k4)
    for nm in ('+AVUV（按分P5）', '+AVUV（N10）'):
        j = N.judge(vw, W_CRASH, nm, CUR)
        ways[nm] = dict(まとめ=j['まとめ'], 主の差=j['感度']['主']['差'])
    real = {}
    ms = R.months(*OVL)
    others_s = {t: M.yahoo(t) for t in ('VBR', 'DFSVX', 'IJR', 'SPY', 'QQQ', 'GDX')}
    real['同じ窓 2019-10〜2026-09（ドル・配当込み）'] = dict(AVUV=stats(avuv, ms), **{t: stats(s, ms) for t, s in others_s.items()})
    yrs = {}
    for y in range(2020, 2027):
        mm = R.months(y * 100 + 1, min(y * 100 + 12, OVL[1]))
        yrs[str(y) + ('（1〜9月）' if y == 2026 else '')] = {t: round(100 * (math.prod(1 + s[k] for k in mm) - 1), 1)
                                                         for t, s in [('AVUV', avuv)] + list(others_s.items())}
    real['暦年(%)'] = yrs
    real['相関（月次・同じ窓）'] = {t: round(M.corr([avuv[k] for k in ms], [s[k] for k in ms]), 3) for t, s in others_s.items()}
    long_ms = R.months(UC.FIRST, UC.END)
    real['つないだ AVUV の 2000-09〜2026-09'] = dict(AVUV=stats(chains['AVUV'], long_ms), VBR=stats(chains['VBR'], long_ms), SPY=stats(chains['VOO'], long_ms))
    cent_out = {nm: U.strip_century(d) for nm, d in cent.items() if d is not None}

    doc.update(
        facts=P['facts_known_before_measuring'], rakuten_available=avail, proxies=pick, proxy_used=best,
        avuv_row={k: (round(100 * v, 3) if isinstance(v, float) else v) for k, v in rows['AVUV'].items()
                  if k in ('A1', 'A2', 'B', 'C', 'A1_gross', 'A2_gross', 'B_gross', 'C_gross', 'B_X', 'B_rec', 'B_src', 'er_vehicle', 'dy_vehicle',
                           'tax_drag', 'vol_A1', 'maxdd_A1', 'record_share_e', 'holdings_coverage', 'top_industries', 'proxy', 'proxy_until')},
        vbr_row={k: (round(100 * v, 3) if isinstance(v, float) else v) for k, v in rows['VBR'].items()
                 if k in ('A1', 'A2', 'B', 'C', 'B_X', 'B_rec', 'er_vehicle', 'dy_vehicle', 'tax_drag', 'top_industries')},
        K4_半導体の基礎率={c: dict(Chips=(None if chips[c] is None else round(chips[c], 3)), 足す年率=round(100 * k4[c], 3)) for c in assets},
        pi=pi, forms=F,
        judgments={cj: {fn: dict(まとめ=j['まとめ'], 主の判定=j['主の判定'], 感度=j['感度']) for fn, j in d.items()} for cj, d in judg.items()},
        insurance=ins, reading=read, ways_to_add=ways,
        results={'USD・崩れあり（主）': table, 'USD・ドットコム級なし': {nm: show(tab_usd[W_DC][nm]) for nm in F},
                 '円・崩れあり': {nm: show(tab_jpy[W_CRASH][nm]) for nm in F}, '過去の転がる積立（USD・2000-09〜2026-09）': roll,
                 '100年の代用（全体の形）': cent_out, '本物の記録': real},
        frames={'USD': 'night/bestpf_check.py と同じ（ドル建て）', '円': f'月次のドル建ての値に FRED DEXJPUS の月末の比（{fx_url}）・B/C/D はドルのまま'},
        castle_copy=dict(seats=seats, castle_pct=cpct),
        caveats=['AVUV の 2019-09 以前は代わり（' + best + '）＝ AVUV の運用の腕ではなく、似た型の投信・指数の値動き',
                 '世界B は VBR と同じ型の上乗せ（小型バリューの長い歴史 ×0.5）・世界C は JPM の USS・世界D は C で代える＝AVUV の収益性の選別の上乗せは持たない',
                 '100年の代用は AVUV と VBR を同じ French の SMALL HiBM で写す（区別しない）',
                 'ETF 側だけを測る（個別株10は物差しの外）・判定は事前登録どおり・配分は変えない'],
        decision='配分は変えない（報告するだけ・事前登録 R7）', secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    U.log('→', OUT, f'{time.time() - t0:.0f}秒')
    for cj, d in judg.items():
        for fn, j in d.items():
            dd = j['感度']['主']['差']
            U.log(f"{cj[:22]:<22} {fn:<14} {j['まとめ']:<10} 主 {j['主の判定']:<5} Δ平均{dd['平均']:+.3f} Δ最悪{dd['最悪']:+.3f} Δ確率{dd['確率']:+.2f} "
                  f"Δぶれ{dd['ぶれ']:+.2f} Δ5%未満{dd['5%未満']:+.2f} Δ下落{dd['最大下落']:+.2f} | {[x['判定'] for x in j['感度'].values()]}")
        U.log('   保険', ins[cj]['状態'])
    U.log('読み', json.dumps(read, ensure_ascii=False))
    U.log('本物の記録', json.dumps(real['同じ窓 2019-10〜2026-09（ドル・配当込み）'], ensure_ascii=False))


if __name__ == '__main__':
    main()
