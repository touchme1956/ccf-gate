#!/usr/bin/env python3
"""night/etf_add_check.py — 今の配分に足すならどの ETF か（2026-10-16・ユーザー「追加するならどんなETF?」）

読むだけ。門・採点・配分（portfolio.json）・注文書には触れない。事前登録 out/etf_add_prereg.json（5a527332）どおり。
  今（ETF 側・全体の%）: NASDAQ100 40 / SMH 25 / ITA 5 / SHLD 5 / XLV 7.5 / FBT 7.5（個別株10は物差しの外）
  案: 候補 X の5%を NASDAQ100 から（QQQM 35・X 5）。Δ＝案 − 今
機械1（主）: night/unx_assets.measure（5つの世界）＋ night/ndx_swap_check.variants・judge（感度5本）＋ unx_final.conds（保険の3条件）。
  候補31本（unx の行で楽天の海外ETF一覧か東証で買える本）。主の枠 USD・崩れあり／確かめの枠 USD・ドットコム級なし・円・崩れあり
機械2（確かめ）: night/etfcand.py の stage2 の道具（hook・4つの世界・別のプロセスで回す＝unx の差し替えと混ざらない）。
  今は SHLD→ITA・FBT は代理（FBIOX）が門を通らなければ XLV。候補は etfcand のショートリストの13家族の代表
回帰の検査: ① 今が out/sp500_compare.json の今と小数1桁で一致 ② 感度の主が measure と 1e-9 以内（USD・円）
  ③ 機械2 が etfcand の第2段の GDX・SIL の主の Δ を小数2桁で再現（今＝QQQM 40 / SMH 25 / ITA 10 / XLV 10）
勧め方は事前登録の Q1〜Q4・R7（配分は変えない）。参考（判定に使わない）: 足し方の感度（按分P5・N10）・上振れ・
  過去の転がる積立・100年の代用（写しのある本だけ）・NASDAQ100 / SMH との相関・楽天の経費率。

使い方: python3 night/etf_add_check.py  → out/etf_add_check.json
"""
import datetime, json, os, subprocess, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))

OUT = os.path.join(BASE, 'out', 'etf_add_check.json')
PREREG = os.path.join(BASE, 'out', 'etf_add_prereg.json')
CDIR = os.path.join(BASE, 'out', '_nx_cache', 'etf_add')
M2_OUT = os.path.join(CDIR, 'machine2.json')
SCRATCH = os.path.join(CDIR, 'etfcand_unused.json')        # hook を渡すと書かれない（念のため別の場所）
CUR = '今'
SLOT = 5
M2_ONLY = ['BBH', 'EWT', 'QTEC', 'FDN', 'FXL', 'COPX', 'SIL', 'GLIN', 'EPHE']
OVERLAP = {'GDX': 'GDX', 'XLU': 'XLU', 'XLP': 'XLP', 'GLD': 'GLDM'}     # 機械2 の代表 → 機械1 の行
VEH = {'EPI_LONG': 'EPI', 'TOPIX': None, 'UST_HEDGED_2621': None}
VEH_TSE = {'TOPIX': '東証の TOPIX 連動ETF（1306・1348・2557 など）', 'UST_HEDGED_2621': '東証 2621（iシェアーズ 米国債20年超 為替ヘッジあり）'}
FRAMES = ('USD・崩れあり（主）', 'USD・ドットコム級なし', '円・崩れあり')
M2_OLD = {'QQQM': 40, 'SMH': 25, 'ITA': 10, 'XLV': 10}            # etfcand の第2段の今（回帰の検査③）


# ───────────────────────── 機械2（別のプロセス）─────────────────────────
def machine2_child(dst):
    import etfcand as EC
    os.makedirs(CDIR, exist_ok=True)

    def hook(ctx):
        meas, judge, show = ctx['measure'], ctx['judge'], ctx['show']
        has_fbt = 'FBT' in ctx['base_w']
        base = ({'QQQM': 40, 'SMH': 25, 'ITA': 10, 'XLV': 7.5, 'FBT': 7.5} if has_fbt else {'QQQM': 40, 'SMH': 25, 'ITA': 10, 'XLV': 15})
        fam, infos = ctx['fam_rows'], ctx['infos']
        ref = json.load(open(os.path.join(BASE, 'out', 'etfcand.json')))['stage2']['判定']
        mo = meas(M2_OLD)
        reg, ok = {}, True
        for fid in (45, 130):
            key = fam.get(fid)
            if key is None:
                reg[str(fid)] = '行が無い'
                ok = False
                continue
            wd = dict(M2_OLD); wd['QQQM'] -= SLOT; wd[key] = wd.get(key, 0) + SLOT
            d = judge(meas(wd), mo)['感度ごと']['main']['Δ']
            r = ref[str(fid)]['判定']['感度ごと']['main']['Δ']
            same = all(abs(d[k] - r[k]) < 1e-9 for k in r)
            reg[f"{fid} {infos[fid]['t']}"] = dict(この道具=d, etfcand=r, 一致=same)
            ok = ok and same
        mb = meas(base)
        res = {}
        for fid, key in fam.items():
            wd = dict(base); wd['QQQM'] -= SLOT; wd[key] = wd.get(key, 0) + SLOT
            m = meas(wd)
            j = judge(m, mb)
            info = {k: v for k, v in (infos.get(fid) or {}).items() if k not in ('代理の候補の相関', 'French49の重み')}
            res[infos[fid]['t']] = dict(家族=fid, 行=key, 物差し=show(m), 判定=j, 行の情報=info)
        out = {fid: dict(t=v.get('t'), 判定の外=v.get('判定の外')) for fid, v in ctx['outside'].items()}
        return dict(base=base, has_fbt=has_fbt, base_show=show(mb), regression=dict(ok=ok, rows=reg), results=res, outside=out,
                    self_check=ctx['self_check'], fbt_info={k: v for k, v in (ctx['fbt_info'] or {}).items() if k != '代理の候補の相関'})
    subst = {}
    if not os.path.exists(EC.ETFD):
        # etfcand の写し（etfd_20261013.csv・gitignore）がこのコンテナに無い → unx が取った 2026-10-14 の写しで代える。
        # 第2段がこの表から読むのは FBT の経費率・配当利回りだけ（FBT の行は代理 FBIOX の相関で門を通らないので判定には効かない）
        alt = os.path.join(BASE, 'out', '_nx_cache', 'unx', 'ab', 'dl', 'ETFD_20261014.csv')
        if not os.path.exists(alt):
            raise SystemExit(f'楽天の ETFD.csv の写しが無い: {EC.ETFD} / {alt}')
        subst['楽天 ETFD.csv'] = f'{os.path.relpath(EC.ETFD, BASE)} が無い → {os.path.relpath(alt, BASE)}（2026-10-14 の写し）で代えた（読むのは FBT の行だけ）'
        EC.ETFD = alt
    av = sorted(f[:-5] for f in os.listdir(EC.AVDIR)) if os.path.isdir(EC.AVDIR) else []
    subst['Alpha Vantage の保有（out/_nx_cache/etfcand/av/）'] = (
        f'この道具の実行の前に {"・".join(av)} を 2026-10-16 に取り直した（etfcand は 2026-10-13 の写し・このコンテナに無かった）' if av else '無い')
    doc = EC.stage2(src=EC.OUT, dst=SCRATCH, posthoc_on=False, hook=hook)
    doc['データの置き換え'] = subst
    json.dump(doc, open(dst, 'w'), ensure_ascii=False, indent=1, default=str)


def machine2():
    os.makedirs(CDIR, exist_ok=True)
    log_path = os.path.join(CDIR, 'machine2.log')
    with open(log_path, 'w') as fh:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), '--m2', M2_OUT], stdout=fh, stderr=subprocess.STDOUT, cwd=BASE, timeout=3600)
    if r.returncode:
        raise SystemExit(f'機械2 が失敗した: {os.path.relpath(log_path, BASE)}')
    return json.load(open(M2_OUT))


# ───────────────────────── 機械1 ─────────────────────────
def forms(P, drop=()):
    m1 = P['machine_1_main']
    cur = dict(m1['今'])
    cands = [x for x in m1[next(k for k in m1 if k.startswith('候補'))] if x not in drop]
    F = {CUR: cur}
    REF = {}
    tot = sum(cur.values())
    for x in cands:
        f = dict(cur); f['QQQM'] -= SLOT; f[x] = f.get(x, 0) + SLOT
        F[f'+{x}'] = f
        p = {c: w * (tot - SLOT) / tot for c, w in cur.items()}; p[x] = p.get(x, 0) + SLOT
        REF[f'+{x}（按分P5）'] = p
        n10 = dict(cur); n10['QQQM'] -= 2 * SLOT; n10[x] = n10.get(x, 0) + 2 * SLOT
        REF[f'+{x}（N10）'] = n10
    return cur, cands, F, REF


def main_delta(j):
    return j['感度']['主']['差']


def main():
    import unx_assets as U
    import upside_check as UC
    import ndx_swap_check as N
    t0 = time.time()
    W_CRASH, W_DC = UC.W_CRASH, UC.W_DC
    P = json.load(open(PREREG))
    cur, cands, F, REF = forms(P)

    U.log('機械2（別のプロセス・etfcand の第2段の道具）')
    m2 = machine2()
    U.log('  機械2 の回帰の検査', m2['regression']['ok'], '今', m2['base'], 'FBT', m2['has_fbt'], m2.get('データの置き換え'))

    res = U.build()
    rows, chains = res['rows'], res['chains']
    miss = [x for x in cands if x not in rows]
    if miss:
        raise SystemExit(f'候補の行が無い: {miss}')
    # 系列が主の窓（2000-09〜）にそろわない候補は測れない＝事前登録で GRID・EPI を外したのと同じ理由で外し、名指しする
    late = {x: min(chains[x]) for x in cands if min(chains[x]) > UC.FIRST}
    if late:
        cur, cands, F, REF = forms(P, drop=set(late))
        U.log('  系列が主の窓にそろわず外した候補', late)
    allp = dict(F, **REF)
    assets = sorted({a for f in allp.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, assets)
    import bestpf_eval as E
    pi, _, _ = E.load_pi()
    _, sim = U.tables()

    U.log('機械1 USD の枠（', len(F), '形）')
    tab_usd = U.measure(F, rows, chains, mega=mega)
    ref = json.load(open(os.path.join(BASE, 'out', 'sp500_compare.json')))['results']['模型 USD・崩れあり（主）']['今（2026-10-15〜・ETF 側）']
    reg1, ok1 = {}, True
    for k in ('P15π', 'P5π（5%未満）', '最悪の世界', '最大下落'):
        a, b = tab_usd[W_CRASH][CUR][k], ref[k]
        same = UC.r1(a) == UC.r1(b)
        reg1[k] = dict(sp500_compare=b, この道具=a, 一致=same)
        ok1 = ok1 and same
    k4, chips = N.chips_adj(rows, assets)
    vt_usd = N.variants(allp, rows, chains, k4)
    reg2 = N.regress_variants(vt_usd, tab_usd)
    U.log('回帰の検査', ok1, reg2['max_abs_diff'], '機械2', m2['regression']['ok'])
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/etf_add_check.py', prereg='out/etf_add_prereg.json（5a527332）',
               question=P['question'],
               deviations_from_prereg={
                   '測れない候補（事前登録の31本から外した）': {x: f'系列が {m // 100}-{m % 100:02d} から＝主の窓（2000-09〜）にそろわない（事前登録で GRID を外したのと同じ理由・事前登録の時点で見落とした）'
                                                    for x, m in late.items()},
                   '機械2 の材料': m2.get('データの置き換え')},
               regression={'① 今と out/sp500_compare.json の今（USD・崩れあり・小数1桁）': dict(ok=ok1, rows=reg1),
                           '② 感度の計算の主と unx_assets.measure（USD・丸める前・1e-9）': {k: v for k, v in reg2.items() if k != 'rows'},
                           '③ 機械2 が etfcand の第2段の主の Δ を再現（GDX・SIL・小数2桁）': m2['regression'],
                           '機械2 の自己検問（etfcand のまま・etf_ita_xlk の席A）': m2['self_check']})
    if not (ok1 and reg2['ok'] and m2['regression']['ok']):
        doc['decision'] = '回帰の検査に失敗＝止めた'
        json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
        raise SystemExit('回帰の検査に失敗')

    U.log('機械1 円の枠')
    ch_jpy, fx_url = U.jpy_chains(chains)
    tab_jpy = U.measure(F, rows, ch_jpy, mega=mega)
    vt_jpy = N.variants(allp, rows, ch_jpy, k4)
    reg3 = N.regress_variants(vt_jpy, tab_jpy)
    doc['regression']['④ 円の枠でも②と同じ'] = {k: v for k, v in reg3.items() if k != 'rows'}
    if not reg3['ok']:
        doc['decision'] = '回帰の検査に失敗（円の枠）＝止めた'
        json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
        raise SystemExit('回帰の検査に失敗（円）')

    U.log('100年の代用（写しのある本だけ）')
    cc, seats, cpct = U.castle_copy()

    def g(f):
        o = {}
        for k, v in f.items():
            kk = 'SMH' if k == 'SOX_F' else k
            o[kk] = o.get(kk, 0) + v
        return o
    cent = {nm: U.century_monthly(U.whole(g(f), cc)) for nm, f in F.items()}

    # ── 判定（機械1）──
    U.log('判定')
    from unx_final import conds
    frames = {FRAMES[0]: (vt_usd, W_CRASH), FRAMES[1]: (vt_usd, W_DC), FRAMES[2]: (vt_jpy, W_CRASH)}
    judg, ins, refj = {}, {}, {}
    for x in cands:
        nm = f'+{x}'
        judg[x] = {fn: N.judge(vt, wn, nm, CUR) for fn, (vt, wn) in frames.items()}
        cu = conds(tab_usd, nm, CUR, cent[nm], cent[CUR])
        cj = conds(tab_jpy, nm, CUR, cent[nm], cent[CUR])
        c12 = bool(cu[W_CRASH]['(1) P15π の低下 ≤ 1.5pt'] and cu[W_CRASH]['(2) 最悪の世界・P5π・最大下落がすべて良い'])
        c3 = cu['(3) 100年の代用（全体の形）の20年・30年の中央が下がらず下位10%が上がる']
        state = 'すべて満たす' if (c12 and c3) else ('(1)(2) を満たす・(3) は測れない' if (c12 and c3 is None) else '満たさない')
        ins[x] = {'USD の枠': cu, '円の枠（感度）': cj, '状態（USD・崩れあり）': state}
        refj[x] = {lab: {'まとめ': j['まとめ'], '主の差': main_delta(j)} for lab, j in
                   (('按分P5（ETF 側全部から5）', N.judge(vt_usd, W_CRASH, f'+{x}（按分P5）', CUR)),
                    ('N10（NASDAQ100 から10）', N.judge(vt_usd, W_CRASH, f'+{x}（N10）', CUR)))}

    main_sum = {x: judg[x][FRAMES[0]] for x in cands}

    def dkey(x):
        d = main_delta(main_sum[x])
        return (-d['平均'], -d['最悪'])
    firm1 = sorted([x for x in cands if main_sum[x]['まとめ'] == '堅い価値あり'], key=dkey)
    m2r = m2['results']
    firm2 = [t for t in M2_ONLY if t in m2r and m2r[t]['判定']['まとめ'] == '堅い価値あり']
    insurance = sorted([x for x in cands if main_sum[x]['まとめ'] == '前提しだい' and ins[x]['状態（USD・崩れあり）'] != '満たさない'],
                       key=lambda x: -main_delta(main_sum[x])['最悪'])

    read = {}
    if firm1:
        split = {x: {fn: judg[x][fn]['まとめ'] for fn in FRAMES[1:] if judg[x][fn]['まとめ'] != '堅い価値あり'} for x in firm1}
        read['Q1'] = dict(堅い価値あり=[dict(本=x, 主の差=main_delta(main_sum[x]), 確かめの枠=split[x] or 'どちらも堅い価値あり') for x in firm1],
                         足すならこれ=firm1[0],
                         読み=f"Q1: 足すなら {firm1[0]}（機械1 の主の枠で『堅い価値あり』{len(firm1)}本の Δ平均 1位）"
                              + (f"——窓・通貨で割れる（{'・'.join(f'{k} は {v}' for k, v in split[firm1[0]].items())}）" if split[firm1[0]] else ''))
    else:
        read['Q1'] = '機械1 の主の枠に『堅い価値あり』の候補は無い'
    if not firm1:
        if firm2:
            sil_note = ('SIL は 2010-04 まで金鉱株の投信 FSAGX でつないでいる（機械2 の GDX と同じ代理）——機械1 の GDX は『'
                        + main_sum['GDX']['まとめ'] + '』＝SIL の代理の部分は機械1 では支持されない') if ('SIL' in firm2 and main_sum['GDX']['まとめ'] != '堅い価値あり') else None
            read['Q2'] = {'堅い価値あり': firm2, '読み': 'Q2: 4つの世界の物差しでは（D の世界なし・SHLD と FBT の代わりあり）' + '・'.join(firm2) + ' が『堅い価値あり』',
                          'SIL の注': sil_note}
        else:
            read['Q2'] = '機械2 だけの候補にも『堅い価値あり』は無い'
    if not firm1 and not firm2:
        read['Q3'] = (dict(候補=[dict(本=x, 保険=ins[x]['状態（USD・崩れあり）'], 主の差=main_delta(main_sum[x])) for x in insurance],
                           読み='Q3: 保険として足すのは筋が通る（好みの差）——' + '・'.join(insurance)) if insurance else 'Q3: 足す根拠はデータに無い')
    q4 = {}
    for t2, x1 in OVERLAP.items():
        a = main_sum[x1]['まとめ'] if x1 in main_sum else None
        b = m2r[t2]['判定']['まとめ'] if t2 in m2r else None
        q4[f'{t2}（機械1 の行 {x1}）'] = dict(機械1=a, 機械2=b, 割れる=(a is not None and b is not None and a != b))
    read['Q4'] = q4
    read['参考: 保険の候補（Q3 の決まりで並べた・今回の読みに使うかは Q1〜Q2 しだい）'] = [
        dict(本=x, 保険=ins[x]['状態（USD・崩れあり）'], 主の差=main_delta(main_sum[x])) for x in insurance]
    read['R7'] = 'どの結果でも配分は変えない（報告するだけ・入れるかはユーザーの明示指示）'

    # ── 参考（判定に使わない）──
    U.log('参考: 上振れ・転がる積立・相関・組み合わせ')
    combo = None
    if len(firm1) >= 2:
        a, b = firm1[0], firm1[1]
        cf = dict(cur); cf['QQQM'] -= 2 * SLOT; cf[a] = cf.get(a, 0) + SLOT; cf[b] = cf.get(b, 0) + SLOT
        nmc = f'+{a}+{b}（各5・NASDAQ100 から10）'
        pc = {CUR: cur, nmc: cf}
        tc = U.measure(pc, rows, chains, mega=mega)
        vc = N.variants(pc, rows, chains, k4)
        jc = N.judge(vc, W_CRASH, nmc, CUR)
        combo = dict(形=cf, まとめ=jc['まとめ'], 主の判定=jc['主の判定'], 感度=jc['感度'],
                     物差し={k: v for k, v in tc[W_CRASH][nmc].items() if k not in ('_raw', '積立20年の内部収益率')})

    def show(r):
        return {k: r[k] for k in ('P15π', 'P15π（A2を外す）', 'P5π（5%未満）', 'P0π（元本割れ）', '最悪の世界', 'π加重の平均の年率', 'ぶれ', '最大下落',
                                  '崩れ2000型_16〜18年目', '過去の転がる20年で15%以上', '世界ごとの年率')}
    table = {}
    for nm in F:
        r = tab_usd[W_CRASH][nm]
        q, pr_ = UC.upside(sim, r['_raw'], pi)
        table[nm] = dict(show(r), 上振れ=dict(pr_, 内部収益率の分位=q))
    table_dc = {nm: show(tab_usd[W_DC][nm]) for nm in F}
    table_jpy = {nm: show(tab_jpy[W_CRASH][nm]) for nm in F}
    roll = {nm: UC.rolling(f, rows, chains) for nm, f in F.items()}
    q = N.monthly_series({'QQQM': 1}, rows, chains, UC.FIRST, UC.END)[1]
    s = N.monthly_series({'SMH': 1}, rows, chains, UC.FIRST, UC.END)[1]
    corr = {}
    for x in cands:
        xs = N.monthly_series({x: 1}, rows, chains, UC.FIRST, UC.END)[1]
        corr[x] = {'NASDAQ100（QQQM）': N.corr(xs, q), 'SMH': N.corr(xs, s), '単体': N.stats(xs)}
    bl = json.load(open(os.path.join(BASE, 'out', 'broker_lineup.json')))['etfs']
    veh = {}
    for x in cands:
        if x in VEH_TSE:
            veh[x] = dict(器=VEH_TSE[x], 楽天=None, 注='東証で買う本（楽天の海外ETF一覧の外）')
            continue
        t = VEH.get(x) or x
        e = bl.get(t)
        veh[x] = dict(器=t, 楽天=bool(e), 名前=(e or {}).get('nm'), 経費率=(e or {}).get('er'))
    cent_out = {nm: U.strip_century(d) for nm, d in cent.items() if d is not None}

    doc.update(
        forms=dict(今=cur, 足し方='候補 X の5%を NASDAQ100 から（QQQM 35・X 5）', 候補=cands),
        K4_半導体の基礎率={c: dict(Chips=(None if chips[c] is None else round(chips[c], 3)), 足す年率=round(100 * k4[c], 3)) for c in assets},
        pi=pi,
        judgments={x: {fn: dict(まとめ=j['まとめ'], 主の判定=j['主の判定'], 感度=j['感度']) for fn, j in judg[x].items()} for x in cands},
        insurance=ins, reference_ways_to_add=refj, reading=read, combo_top2=combo,
        machine2={'今': m2['base'], 'FBT': ('FBT の行が通った' if m2['has_fbt'] else 'FBT の代理が門を通らない → XLV で代えた（etfcand と同じ）'),
                  'FBT の行': m2['fbt_info'], '今の物差し': m2['base_show'], '判定の外': m2['outside'],
                  'データの置き換え（事前登録からのずれ・道具の式は不変）': m2.get('データの置き換え'),
                  'results': {t: dict(家族=r['家族'], 行=r['行'], まとめ=r['判定']['まとめ'], 主=r['判定']['主'], 感度=r['判定']['感度ごと'],
                                      物差し=r['物差し'], 行の情報=r['行の情報']) for t, r in m2r.items()}},
        results={'機械1 USD・崩れあり（主）': table, '機械1 USD・ドットコム級なし': table_dc, '機械1 円・崩れあり': table_jpy,
                 '過去の転がる積立（USD・2000-09〜2026-09）': roll, '100年の代用（全体の形・写しのある形だけ）': cent_out,
                 '相関と単体の値動き（月次・USD・2000-09〜2026-09）': corr, '器（楽天の海外ETF一覧 out/broker_lineup.json）': veh},
        frames={'USD': 'night/bestpf_check.py と同じ（ドル建て）', '円': f'月次のドル建ての値に FRED DEXJPUS の月末の比を掛けた（{fx_url}）・B/C/D はドルの値のまま'},
        castle_copy=dict(seats=seats, castle_pct=cpct, copy={k: round(v, 2) for k, v in cc.items()}),
        caveats=['ETF 側だけを測る（個別株10は物差しの外）＝足す本は個別株の銘柄ごとのぶれを打ち消す効き目を持たない形で測られる',
                 'SHLD の 2023-09 以前は ITA のつなぎ（代理の門を通らない）・機械2 では SHLD を ITA で代え、FBT は代理が通らなければ XLV で代える',
                 '分散の効く本の価値は分散の上乗せ ½(Σw s²−w\'Sw) の仮定に頼る（感度『分散の上乗せなし』が外す）',
                 '100年の代用は写しのある本（候補では GDX・XLU）だけ＝保険の (3) は他の本では測れない',
                 '機械2 は D の世界を持たず、確率は4つの世界の平均（機械1 は π 加重）',
                 '判定は事前登録どおり。配分は変えない（R7）'],
        decision='配分は変えない（報告するだけ・事前登録 R7）', secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    U.log('→', OUT, f'{time.time() - t0:.0f}秒')

    U.log('── 機械1（主の枠・Δ＝案 − 今・NASDAQ100 から5）──')
    for x in sorted(cands, key=dkey):
        j = main_sum[x]; d = main_delta(j)
        U.log(f"{x:<16} {j['まとめ']:<10} 主 {j['主の判定']:<5} Δ平均{d['平均']:+6.3f} Δ最悪{d['最悪']:+6.3f} Δ確率{d['確率']:+6.2f} Δぶれ{d['ぶれ']:+6.2f} "
              f"Δ5%未満{d['5%未満']:+6.2f} Δ下落{d['最大下落']:+6.2f} | 感度 {[v['判定'] for v in j['感度'].values()]} | "
              f"DC {judg[x][FRAMES[1]]['まとめ']} 円 {judg[x][FRAMES[2]]['まとめ']} | 保険 {ins[x]['状態（USD・崩れあり）']} | "
              f"P5 {refj[x]['按分P5（ETF 側全部から5）']['まとめ']} N10 {refj[x]['N10（NASDAQ100 から10）']['まとめ']}")
    U.log('── 機械2（4つの世界）──')
    for t, r in m2r.items():
        d = r['判定']['感度ごと']['main']['Δ']
        U.log(f"{t:<6} {r['判定']['まとめ']:<10} 主 {r['判定']['主']:<5} Δ{d} 感度 {[r['判定']['感度ごと'][v]['判定'] for v in r['判定']['感度ごと']]}")
    U.log('読み', json.dumps(read, ensure_ascii=False)[:3000])
    if combo:
        U.log('上位2本', combo['形'], combo['まとめ'])


if __name__ == '__main__':
    if len(sys.argv) >= 3 and sys.argv[1] == '--m2':
        machine2_child(sys.argv[2])
    else:
        main()
