#!/usr/bin/env python3
"""night/gridnasa_check.py — ITA の5を GRID・NASA に2.5%ずつ回す案（2026-10-20・ユーザー「GRID NASAをITA5にして2.5％ずついれるのは？」・参考・判定なし）

ユーザーが頼んだ比べ（ルール10: 頼まれたときだけ）。配分（portfolio.json）・門・採点・注文書には触れない。
作りは night/ita10_check.py をそのまま写し、形と GRID のつなぎ・NASA の参考だけ足した。物差しと形は結果を見る前にこのファイルで固定し、回す前にコミットする。

形（ETF 側・全体の%。個別株10は物差しの外）:
  今                       : QQQM 40 / SMH 25 / ITA 10 / SHLD 5 / XLV 5 / FBT 5
  案（ユーザーの形）       : QQQM 40 / SMH 25 / ITA 5 / SHLD 5 / XLV 5 / FBT 5 / GRID 2.5 / NASA 2.5
    → NASA（Tema Space Innovators・設定 2026-03-30）は値段が約6か月半しかなく、物差し（2000-09〜の月次）にも
      代理の門（重なり24か月以上・相関0.90以上）にも載らない＝測れない。だから案を2つに分ける:
  案の測れる部分           : QQQM 40 / SMH 25 / ITA 7.5 / SHLD 5 / XLV 5 / FBT 5 / GRID 2.5（NASA の2.5は ITA に置いたまま）
  参考（NASA の分も GRID に）: QQQM 40 / SMH 25 / ITA 5 / SHLD 5 / XLV 5 / FBT 5 / GRID 5
GRID のつなぎ（主）: 本物は 2009-12〜。2009-11 以前は bestpf_ext の代理（GRID の今の保有を French 49業種へ割り当てた重みで混ぜる − 経費率/12）。
  この代理は事前登録の門を通らない（相関 0.892 < 0.90・重なりの年率は代理が +2.27pt 高い）——今の形の SHLD を ITA でつなぐ
  （相関0.58・門を通らない）のと同じ扱いで、出力に名指しする。代理が GRID を良く見せる向き（年率が高い・テックとの相関が低い）かも測って出す。
確かめ（GRID は本物だけ）: 2009-12〜2026-09 の月次で、3つの形を毎月組み直した年率・ぶれ・最大下落・10年の毎月の積立の最終額の比（形÷今）。
  ほかの本は物差しと同じ系列・費用と外国税の差（A1−A1_gross）は upside_check.rolling と同じく毎月足す。
物差し: ita10_check と同じ（unx_assets.measure・ndx_swap_check の感度5本の差・3つの枠・過去の転がる積立・100年の代用
  〔GRID は代理と同じ業種の重みで French 49業種を混ぜる＝その月に値のある業種で割り直す〕・中身の集中〔個別株は席5社×2%〕・楽天の経費率）。判定の名前は付けない。
NASA の参考（物差しの外）: ①設定からの日次の記録（NASA・ITA・GRID・QQQ・SMH・SPY・同じ日）②中身（Alpha Vantage ETF_PROFILE・下の定数）
  ③記録の長い宇宙の ETF（ROKT・UFO・ARKX＝楽天の一覧に無い・同じ窓の QQQ・ITA・SPY）
回帰の検査: (a) 今が out/better_mix_check.json の『今』と一致（USD・崩れあり・小数1桁） (b) 感度の主が measure と 1e-9 以内（USD と円）
  (c) 作り直した GRID の代理と本物の相関（bestpf_ext の記録と同じ重なりの月）が記録の値と 0.0005 以内。どれかが外れれば止める
使い方: python3 night/gridnasa_check.py → out/gridnasa_check.json
"""
import datetime, json, math, os, statistics as S, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'gridnasa_check.json')

NOW, A, B = '今', '案の測れる部分（NASA の2.5は ITA のまま）', '参考（NASA の分も GRID に）'
FORMS = {
    NOW: {'QQQM': 40, 'SMH': 25, 'ITA': 10, 'SHLD': 5, 'XLV': 5, 'FBT': 5},
    A: {'QQQM': 40, 'SMH': 25, 'ITA': 7.5, 'SHLD': 5, 'XLV': 5, 'FBT': 5, 'GRID': 2.5},
    B: {'QQQM': 40, 'SMH': 25, 'ITA': 5, 'SHLD': 5, 'XLV': 5, 'FBT': 5, 'GRID': 5},
}
USER_FORM = {'QQQM': 40, 'SMH': 25, 'ITA': 5, 'SHLD': 5, 'XLV': 5, 'FBT': 5, 'GRID': 2.5, 'NASA': 2.5}
PREV_REF = os.path.join(BASE, 'out', 'better_mix_check.json')
PREV_NAME = '今'
REG_KEYS = ('P15π', 'P5π（5%未満）', '最悪の世界', '最大下落', 'ぶれ', 'π加重の平均の年率')
GATE_TOL = 0.0005
DAILY = ('NASA', 'ITA', 'GRID', 'QQQ', 'SMH', 'SPY')
SPACE = ('ROKT', 'UFO', 'ARKX')
# NASA の中身（Alpha Vantage ETF_PROFILE・last_updated 2026-10-16 00:01 UTC・2026-10-20 に取得）。説明・symbol・重み（n/a＝ティッカー無し）
NASA_AV = dict(
    src='Alpha Vantage ETF_PROFILE（symbol=NASA・last_updated 2026-10-16 00:01 UTC・2026-10-20 に取得）',
    net_assets=1100000000, er=0.0075, inception='2026-03-30', dividend_yield_av=-0.0068,
    sectors={'INDUSTRIALS': 0.293, 'COMMUNICATION SERVICES': 0.145, 'INFORMATION TECHNOLOGY': 0.117},
    holdings=[
        ('SPACEX SPV EXPOSURE (COMMON)', 'n/a', 0.1649), ('ROCKET LAB CORP', 'RKLB', 0.105),
        ('SPACE EXPLORATION TECHNOLOGIES CORP CLASS A', 'SPCX', 0.0735), ('AST SPACEMOBILE INC', 'ASTS', 0.0675),
        ('VIASAT INC', 'VSAT', 0.052), ('UNIVERSAL MICROWAVE TECHNOLOGY INC', 'n/a', 0.0485), ('FILTRONIC PLC', 'n/a', 0.042),
        ('MDA SPACE LTD', 'n/a', 0.0392), ('FIREFLY AEROSPACE INC', 'FLY', 0.0377), ('5N PLUS INC', 'n/a', 0.0359),
        ('INTUITIVE MACHINES INC', 'LUNR', 0.034), ('VOYAGER TECHNOLOGIES INC', 'VOYG', 0.0308), ('LUMENTUM HOLDINGS INC', 'LITE', 0.0235),
        ('BLACKSKY TECHNOLOGY INC', 'BKSY', 0.0223), ('ASTROSCALE HOLDINGS INC', 'n/a', 0.0221), ('SATELLOGIC INC', 'SATL', 0.02),
        ('WIN SEMICONDUCTORS CORP', 'n/a', 0.018), ('LIGHTPATH TECHNOLOGIES INC', 'LPTH', 0.0164), ('VISHAY PRECISION GROUP INC', 'VPG', 0.016),
        ('QPS HOLDINGS INC', 'n/a', 0.0156), ('AIXTRON SE', 'n/a', 0.0155), ('PLANET LABS PBC', 'PL', 0.0153), ('SYNSPECTIVE INC', 'n/a', 0.0145),
        ('REDWIRE CORP', 'RDW', 0.01), ('OHB SE', 'n/a', 0.0086), ('YORK SPACE SYSTEMS INC', 'YSS', 0.0082), ('STMICROELECTRONICS NV ADR', 'STM', 0.0073),
        ('VELO3D INC', 'VELO', 0.0064), ('CREOTECH INSTRUMENTS SA', 'n/a', 0.0063), ('SPHERE CORP', 'n/a', 0.0057), ('CPS TECHNOLOGIES CORP', 'CPSH', 0.0051),
        ('ECHOSTAR CORP CLASS A', 'ECHO', 0.004), ('SYNTEC OPTICS HOLDINGS INC', 'OPTX', 0.004), ('HAWKEYE 360 INC', 'HAWK', 0.0031),
        ('NEW TAIWAN DOLLAR', 'n/a', 0.0006), ('FIRST AMERICAN TREASURY OBLIGS X', 'FXFXX', 0.0005)])
NASA_CASH = ('NEW TAIWAN DOLLAR', 'FIRST AMERICAN TREASURY OBLIGS X')


def path(xs):
    """月次（または日次）のリターンの列 → 終値の倍率・最大下落"""
    w = pk = 1.0
    mdd = 0.0
    for x in xs:
        w *= 1 + x
        pk = max(pk, w)
        mdd = min(mdd, w / pk - 1)
    return w, mdd


def stats(xs, per_year):
    w, mdd = path(xs)
    yrs = len(xs) / per_year
    return dict(年率=round(100 * (w ** (1 / yrs) - 1), 2), ぶれ=round(100 * S.pstdev(xs) * math.sqrt(per_year), 1), 最大下落=round(100 * mdd, 1),
                年率割るぶれ=round((w ** (1 / yrs) - 1) / (S.pstdev(xs) * math.sqrt(per_year)), 3))


def main():
    import unx_assets as U
    import upside_check as UC
    import ndx_swap_check as N
    import bestpf_eval as E
    import mw_common as M
    t0 = time.time()
    W_CRASH, W_DC = UC.W_CRASH, UC.W_DC
    for f in list(FORMS.values()) + [USER_FORM]:
        assert abs(sum(f.values()) - 90) < 1e-9, f

    res = U.build()
    rows, chains = res['rows'], res['chains']
    R = U.R

    # ── GRID のつなぎ（bestpf_ext の代理を同じ式で作り直す）──
    import bestpf_ext as X
    doc_x = X.rank_result()['doc']
    sc = doc_x['new_assets']['GRID']['splice_check']
    gw = doc_x['GRID_detail']['proxy_industry_weights']
    px, ws, _ = X.build_proxies(X.av_profiles(), gw)
    prox = px['BESTPF_PX_GRID']
    real_y = M.yahoo('GRID')
    a0, b0 = (int(x) for x in sc['overlap'].split('〜'))
    ov = [m for m in sorted(real_y) if a0 <= m <= b0 and m in prox]
    corr_re = M.corr([real_y[m] for m in ov], [prox[m] for m in ov])
    ok_c = abs(corr_re - sc['corr']) <= GATE_TOL
    first_real = min(chains['GRID'])
    grid_m = {m: v for m, v in prox.items() if m < first_real}
    grid_m.update(chains['GRID'])
    need = R.months(UC.FIRST, UC.END)
    miss = [m for m in need if m not in grid_m]
    if miss:
        raise SystemExit(f'GRID のつなぎに穴: {miss[:5]}…')
    chains_m = dict(chains)
    chains_m['GRID'] = grid_m
    # 代理が GRID を良く見せる向きか（重なりの月で 本物 対 代理: 年率・QQQ との相関）
    qq = chains['QQQM']
    ov2 = [m for m in ov if m in qq]
    proxy_bias = dict(
        重なり=f'{ov2[0]}〜{ov2[-1]}（{len(ov2)}か月）',
        年率_本物=stats([real_y[m] for m in ov2], 12)['年率'], 年率_代理=stats([prox[m] for m in ov2], 12)['年率'],
        QQQとの相関_本物=round(M.corr([real_y[m] for m in ov2], [qq[m] for m in ov2]), 3),
        QQQとの相関_代理=round(M.corr([prox[m] for m in ov2], [qq[m] for m in ov2]), 3),
        つないだ月の代理のQQQとの相関=round(M.corr([prox[m] for m in need if m < first_real], [qq[m] for m in need if m < first_real]), 3),
        つないだ月=f'{UC.FIRST}〜{max(m for m in need if m < first_real)}（{sum(1 for m in need if m < first_real)}か月）')

    F = {k: dict(v) for k, v in FORMS.items()}
    assets = sorted({a for f in F.values() for a in f} | {'VOO'})
    mega = U.mega_map(rows, assets)
    pi, _, _ = E.load_pi()
    _, sim = U.tables()
    U.log('USD の枠（', len(F), '形）')
    tab_usd = U.measure(F, rows, chains_m, mega=mega)
    ref = json.load(open(PREV_REF))['results']['USD・崩れあり（主）'][PREV_NAME]
    reg_a, ok_a = {}, True
    for k in REG_KEYS:
        a, b = tab_usd[W_CRASH][NOW][k], ref[k]
        same = UC.r1(a) == UC.r1(b)
        reg_a[k] = dict(better_mix_check=b, この道具=a, 一致=same)
        ok_a = ok_a and same
    k4, chips = N.chips_adj(rows, assets)
    vt_usd = N.variants(F, rows, chains_m, k4)
    reg_b = N.regress_variants(vt_usd, tab_usd)
    U.log('回帰の検査', ok_a, reg_b['max_abs_diff'], '代理の相関', round(corr_re, 4), sc['corr'])
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/gridnasa_check.py', kind='参考・判定なし（ユーザーが頼んだ比べ）',
               question='GRID NASAをITA5にして2.5％ずついれるのは？',
               regression={'(a) 今が out/better_mix_check.json の『今』と一致（USD・崩れあり・小数1桁）': dict(ok=ok_a, rows=reg_a),
                           '(b) 感度の計算の主と unx_assets.measure（USD・丸める前・1e-9）': {k: v for k, v in reg_b.items() if k != 'rows'},
                           '(c) 作り直した GRID の代理と本物の相関が bestpf_ext の記録と一致': dict(ok=ok_c, 記録=sc['corr'], 作り直し=round(corr_re, 4),
                                                                                        重なり=sc['overlap'], 許容=GATE_TOL)})
    if not (ok_a and reg_b['ok'] and ok_c):
        doc['decision'] = '回帰の検査に失敗＝止めた'
        json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
        raise SystemExit('回帰の検査に失敗')
    U.log('円の枠')
    ch_jpy, fx_url = U.jpy_chains(chains_m)
    tab_jpy = U.measure(F, rows, ch_jpy, mega=mega)
    vt_jpy = N.variants(F, rows, ch_jpy, k4)
    reg_j = N.regress_variants(vt_jpy, tab_jpy)
    doc['regression']['(b) 円の枠でも同じ'] = {k: v for k, v in reg_j.items() if k != 'rows'}
    if not reg_j['ok']:
        doc['decision'] = '回帰の検査に失敗（円）＝止めた'
        json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
        raise SystemExit('回帰の検査に失敗（円）')

    # ── 100年の代用（GRID は代理と同じ業種の重みで French 49業種を混ぜる・その月に値のある業種で割り直す・この道具の中だけ）──
    import future30 as F30
    _, ret, *_ = F30.load()
    C = U.century_parts()
    allm = sorted(C['mkt'])
    gpart, no_ind = {}, sorted(k for k in gw if k not in ret)
    for m in allm:
        num = den = 0.0
        for k, w in gw.items():
            r = (ret.get(k) or {}).get(m)
            if r is None:
                continue
            num += w * r
            den += w
        if den > 0:
            gpart[m] = num / den
    C['parts']['GRID'] = gpart
    U.MONTHLY_OK.add('GRID')
    cc, seats, cpct = U.castle_copy()
    cent = {nm: U.century_monthly(U.whole(f, cc)) for nm, f in F.items()}

    def show(r):
        return {k: r[k] for k in ('P15π', 'P15π（A2を外す）', 'P5π（5%未満）', 'P0π（元本割れ）', '最悪の世界', 'π加重の平均の年率', 'ぶれ', '最大下落',
                                  '崩れ2000型_16〜18年目', '下落2022型_16年目', '過去の転がる20年で15%以上', '世界ごとの年率')}
    table = {}
    for nm in F:
        r = tab_usd[W_CRASH][nm]
        q, pr_ = UC.upside(sim, r['_raw'], pi)
        table[nm] = dict(show(r), 上振れ=dict(pr_, 内部収益率の分位=q))
    roll = {nm: UC.rolling(f, rows, chains_m) for nm, f in F.items()}
    frames = {'USD・崩れあり（主）': (vt_usd, W_CRASH), 'USD・ドットコム級なし': (vt_usd, W_DC), '円・崩れあり': (vt_jpy, W_CRASH)}
    diffs = {}
    for cj, (a, b) in {'案の測れる部分 − 今': (A, NOW), '参考 − 今': (B, NOW)}.items():
        diffs[cj] = {}
        for fn, (vt, wn) in frames.items():
            j = N.judge(vt, wn, a, b)
            diffs[cj][fn] = {k: x['差'] for k, x in j['感度'].items()}     # 差だけ（判定の名前は付けない）
    cent_out = {nm: U.strip_century(d) for nm, d in cent.items() if d is not None}

    # ── 確かめ: GRID は本物だけ（2009-12〜）──
    ms_r = R.months(first_real, UC.END)

    def series(f, ch):
        tot = sum(f.values())
        return [sum(f[c] / tot * (ch[c][m] + (rows[c]['A1'] - rows[c]['A1_gross']) / 12) for c in f) for m in ms_r]
    ser = {nm: series(f, chains) for nm, f in F.items()}

    def dca_fv(xs):
        v = 0.0
        for x in xs:
            v = (v + 1) * (1 + x)
        return v
    n10 = 120
    dca = {}
    for nm in F:
        if nm == NOW:
            continue
        rat = [dca_fv(ser[nm][i:i + n10]) / dca_fv(ser[NOW][i:i + n10]) for i in range(len(ms_r) - n10 + 1)]
        rs = sorted(rat)
        dca[nm] = dict(窓の数=len(rat), 中央=round(rs[len(rs) // 2], 4), 最小=round(rs[0], 4), 最大=round(rs[-1], 4),
                       今を上回った割合=round(100 * sum(x > 1 for x in rat) / len(rat), 1))
    check_real = dict(窓=f'{ms_r[0]}〜{ms_r[-1]}（{len(ms_r)}か月・GRID は本物だけ）',
                      形ごと={nm: stats(ser[nm], 12) for nm in F}, 十年の毎月の積立の最終額の比_形割る今=dca)

    # ── 参考: GRID の長い記録（本物・2010-01〜）──
    mm = {t: M.yahoo(t) for t in ('GRID', 'QQQ', 'ITA', 'SPY')}
    ms_g = [m for m in sorted(mm['GRID']) if m >= 201001 and all(m in mm[t] for t in mm)]
    grid_long = dict(窓=f'{ms_g[0]}〜{ms_g[-1]}（{len(ms_g)}か月・Yahoo の調整後終値・ドル建て）',
                     本ごと={t: dict(stats([mm[t][m] for m in ms_g], 12),
                                     QQQとの相関=round(M.corr([mm[t][m] for m in ms_g], [mm['QQQ'][m] for m in ms_g]), 2),
                                     ITAとの相関=round(M.corr([mm[t][m] for m in ms_g], [mm['ITA'][m] for m in ms_g]), 2)) for t in mm})

    # ── NASA の参考（物差しの外）──
    dd = {t: M.yahoo(t, interval='1d') for t in DAILY}
    days = sorted(d for d in dd['NASA'] if all(d in dd[t] for t in DAILY))
    nasa_rec = dict(窓=f'{days[0]}〜{days[-1]}（{len(days)}営業日・日次のリターン・ドル建て）',
                    本ごと={t: dict(累計=round(100 * (path([dd[t][d] for d in days])[0] - 1), 1),
                                    ぶれ_年率換算=round(100 * S.pstdev([dd[t][d] for d in days]) * math.sqrt(252), 1),
                                    最大下落=round(100 * path([dd[t][d] for d in days])[1], 1),
                                    QQQとの相関=round(M.corr([dd[t][d] for d in days], [dd['QQQ'][d] for d in days]), 2),
                                    ITAとの相関=round(M.corr([dd[t][d] for d in days], [dd['ITA'][d] for d in days]), 2)) for t in DAILY})
    h = NASA_AV['holdings']
    comp = [x for x in h if x[0] not in NASA_CASH]
    nasa_hold = dict(出典=NASA_AV['src'], 純資産=NASA_AV['net_assets'], 経費率=NASA_AV['er'], 設定=NASA_AV['inception'],
                     配当利回り_AV=NASA_AV['dividend_yield_av'], 業種=NASA_AV['sectors'], 本数=len(comp),
                     SpaceX合計=round(sum(w for d, t, w in comp if 'SPACEX' in d or t == 'SPCX'), 4),
                     うち非上場のSPV=round(sum(w for d, t, w in comp if 'SPV' in d), 4),
                     上位10社=round(sum(w for _, _, w in sorted(comp, key=lambda x: -x[2])[:10]), 4),
                     ティッカー無し=round(sum(w for d, t, w in comp if t == 'n/a'), 4),
                     上位10=[dict(名前=d, ティッカー=t, 重み=w) for d, t, w in sorted(comp, key=lambda x: -x[2])[:10]])
    space = {}
    for th in SPACE:
        try:
            ms_all = M.yahoo(th)
        except Exception as e:  # noqa
            space[th] = dict(取れない=str(e)[:120])
            continue
        mmx = dict(mm, **{th: ms_all})
        ms_s = [m for m in sorted(ms_all) if all(m in mmx[t] for t in (th, 'QQQ', 'ITA', 'SPY'))][1:]   # 最初の月は途中から＝落とす
        space[th] = dict(窓=f'{ms_s[0]}〜{ms_s[-1]}（{len(ms_s)}か月）',
                         本ごと={t: dict(stats([mmx[t][m] for m in ms_s], 12),
                                         QQQとの相関=round(M.corr([mmx[t][m] for m in ms_s], [mmx['QQQ'][m] for m in ms_s]), 2)) for t in (th, 'QQQ', 'ITA', 'SPY')})

    # ── 中身の集中（個別株は席5社×今の比率の等分）・楽天の経費率 ──
    N.NET_ARG.update({'GRID': 'GRID'})
    N.CASTLE_ARG = ','.join(f'{s}={cpct / len(seats):g}' for s in seats)
    look = {}
    for nm, f in F.items():
        try:
            look[nm] = N.lookthrough(f)
            if '城' in look[nm]:
                look[nm]['城'] = f'{N.CASTLE_ARG}（席{len(seats)}社×{cpct / len(seats):g}%）'
        except Exception as e:                       # 参考だけ・読めなければ名指し
            look[nm] = dict(読めず=str(e)[:200])
    bl = json.load(open(os.path.join(BASE, 'out', 'broker_lineup.json')))['etfs']
    er = {a: (bl.get(a) or {}).get('er') for a in sorted(set(assets) | {'NASA'}) if a != 'VOO'}

    doc.update(
        forms=F, user_form=USER_FORM,
        nasa_not_measurable='NASA は設定 2026-03-30・月次で約6か月半＝物差し（2000-09〜の月次・A2 は 2011-10〜）にも代理の門（重なり24か月以上・相関0.90以上）にも載らない。'
                            '案はそのまま測れないので、GRID の部分（案の測れる部分）と NASA の参考（記録・中身・宇宙の ETF）に分けた',
        grid_splice=dict(つなぎ=f'{first_real} より前は bestpf_ext の代理（{sc["form"]}）・{first_real} から本物',
                         門の記録=dict(相関=sc['corr'], 重なり=sc['overlap'], 本物の年率=sc['geo_main'], 代理の年率=sc['geo_proxy'], 差=sc['gap'],
                                    追従のずれ=sc['tracking_error'], 使う=sc['used'], 理由=sc['reason']),
                         業種の重み=gw, 代理が良く見せる向きか=proxy_bias,
                         扱い='今の形の SHLD を ITA でつなぐ（門を通らない）のと同じく、門を通らない代理を形を作るために使い名指しする'),
        results={'USD・崩れあり（主）': table, 'USD・ドットコム級なし': {nm: show(tab_usd[W_DC][nm]) for nm in F},
                 '円・崩れあり': {nm: show(tab_jpy[W_CRASH][nm]) for nm in F},
                 '過去の転がる積立（USD・2000-09〜2026-09・GRID の前半は代理）': roll, '100年の代用（全体の形）': cent_out,
                 '感度5本の差（判定の名前は付けない）': diffs, '確かめ: GRID は本物だけ': check_real,
                 '参考: GRID の長い記録（本物）': grid_long, '参考: NASA の記録（設定から・日次）': nasa_rec, '参考: NASA の中身': nasa_hold,
                 '参考: 記録の長い宇宙の ETF（楽天の一覧に無い）': space,
                 '中身の集中（lookthrough・参考）': look, '楽天の経費率（out/broker_lineup.json・NASA は空欄＝AV では0.75%）': er},
        K4_半導体の基礎率={c: dict(Chips=(None if chips[c] is None else round(chips[c], 3)), 足す年率=round(100 * k4[c], 3)) for c in assets},
        century_grid=dict(業種で混ぜる=gw, 無い業種=no_ind, 月数=len(gpart)),
        frames={'USD': 'night/bestpf_check.py と同じ（ドル建て）', '円': f'月次のドル建ての値に FRED DEXJPUS の月末の比（{fx_url}）・B/C/D はドルのまま'},
        castle_copy=dict(seats=seats, castle_pct=cpct),
        caveats=['ETF 側だけを測る（個別株10は物差しの外）・判定はしない・配分は変えない',
                 'NASA は測れない——案の測れる部分は NASA の2.5を ITA に置いたままの形（NASA の値動きは入っていない）',
                 'GRID の 2009-11 以前は門を通らない代理（相関0.892）。代理は重なりの月で年率が本物より高く、つないだ2000〜2009年は今の GRID ほどテックと一緒に動かない＝崩れ2000型の場面で GRID を良く見せる向きがありうる（確かめは本物だけの窓）',
                 '100年の代用の GRID は今の保有の業種の重みを100年に当てた写し'],
        secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    U.log('→', OUT, f'{time.time() - t0:.0f}秒')
    for nm in F:
        r = table[nm]
        U.log(f"{nm:<26} P15 {r['P15π']:5.1f} P20 {r['上振れ']['P20（道の束）']:5.1f} P5 {r['P5π（5%未満）']:5.1f} 最悪 {r['最悪の世界']:5.2f} "
              f"平均 {r['π加重の平均の年率']:5.2f} ぶれ {r['ぶれ']:5.1f} 下落 {r['最大下落']:6.1f} 過去20年15%以上 {r['過去の転がる20年で15%以上']:5.1f}")
    for cj, d in diffs.items():
        for fn, x in d.items():
            dd_ = x['主']
            U.log(f"{cj:<16} {fn:<14} 主 Δ平均{dd_['平均']:+.3f} Δ最悪{dd_['最悪']:+.3f} Δ確率{dd_['確率']:+.2f} Δぶれ{dd_['ぶれ']:+.2f} "
                  f"Δ5%未満{dd_['5%未満']:+.2f} Δ下落{dd_['最大下落']:+.2f}")
    U.log('代理の向き', json.dumps(proxy_bias, ensure_ascii=False))
    U.log('確かめ（本物だけ）', json.dumps(check_real, ensure_ascii=False)[:900])
    U.log('NASA の記録', json.dumps(nasa_rec, ensure_ascii=False)[:900])
    U.log('100年', json.dumps({nm: cent_out.get(nm) for nm in F}, ensure_ascii=False)[:1500])


if __name__ == '__main__':
    main()
