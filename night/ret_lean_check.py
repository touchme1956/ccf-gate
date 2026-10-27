#!/usr/bin/env python3
"""night/ret_lean_check.py — リターン重視気味に組むなら（2026-10-21・ユーザー「リターン重視気味で組むなら？」・参考）

ユーザーが頼んだ比べ（ルール10: 頼まれたときだけ）。配分（portfolio.json）・門・採点・注文書には触れない。
候補・物差し・勧めの決まりは結果を見る前にこのファイルで固定し、回す前にコミットする（作りは night/better_mix_check.py の部品のまま）。

今（2026-10-19〜・ETF 側・全体の%。個別株10は物差しの外）: QQQM 40 / SMH 25 / ITA 10 / SHLD 5 / XLV 5 / FBT 5
「気味」の定義（固定）: 今から動かす量（今との差の絶対値の合計÷2・資産全体の%）が 10 以内＝資産の1割までを動かす形だけを勧めの候補にする。
候補（これまでの測定で筋のあった手＝NASDAQ100 → SMH〔better_mix の E・upside_check〕と、守りの本〔SHLD・FBT〕をリターンの本へ）:
  動かす量 ≤10（勧めの候補・8つ）
    N5  NASDAQ100 → SMH 5                      : QQQM 35 / SMH 30 / ITA 10 / SHLD 5 / XLV 5 / FBT 5   （5）
    N10 NASDAQ100 → SMH 10                     : QQQM 30 / SMH 35 / ITA 10 / SHLD 5 / XLV 5 / FBT 5   （10）
    I1  SHLD → SMH                             : QQQM 40 / SMH 30 / ITA 10 / XLV 5 / FBT 5            （5）
    I2  SHLD・FBT → SMH                        : QQQM 40 / SMH 35 / ITA 10 / XLV 5                    （10）
    I3  SHLD・FBT → NASDAQ100                  : QQQM 50 / SMH 25 / ITA 10 / XLV 5                    （10）
    M1  SHLD → SMH・NASDAQ100 → SMH 5          : QQQM 35 / SMH 35 / ITA 10 / XLV 5 / FBT 5            （10）
    M2  SHLD → ITA・NASDAQ100 → SMH 5          : QQQM 35 / SMH 30 / ITA 15 / XLV 5 / FBT 5            （10）
    M3  FBT → SMH・NASDAQ100 → SMH 5           : QQQM 35 / SMH 35 / ITA 10 / SHLD 5 / XLV 5           （10）
  もっと寄せる形（参考・勧めの候補に入れない＝「気味」を越える）
    N15 NASDAQ100 → SMH 15                     : QQQM 25 / SMH 40 / ITA 10 / SHLD 5 / XLV 5 / FBT 5   （15）
    N20 NASDAQ100 → SMH 20                     : QQQM 20 / SMH 45 / ITA 10 / SHLD 5 / XLV 5 / FBT 5   （20）
    K3  守りを ITA 20 に・半導体 35            : QQQM 35 / SMH 35 / ITA 20                            （20）
    参考 SMH60:ITA40（etf_p15 の効率の形を90へ）: SMH 54 / ITA 36
    参考 テックだけ                            : QQQM 60 / SMH 30
    参考 NASDAQ100 だけ                        : QQQM 90
物差し: unx_assets.measure（5つの世界・π）＋ ndx_swap_check.variants・judge（感度5本）を3つの枠（USD・崩れあり〔主〕／USD・ドットコム級なし／円・崩れあり）で、
  Δ＝候補 − 今。100年の代用は全体の形（個別株10を席の業種の写しで）・中身の集中は lookthrough（城は席5社×2%）。
勧めの決まり（固定・主の枠＝USD・崩れあり）:
  G1 期待値: π加重の平均の年率の差が 主で +0.05pt 以上、かつ感度5本（主を含む）のうち4本以上で正
  G2 守り（ここ1週間＝個別株10%の時期にユーザーが選んだ形のうち最も守りの薄い 10-16 の『最終』〔今と比べ 最大下落 −2.8pt・
     5%未満 +0.8pt・最悪の世界 −0.11pt〕を少し丸めた線）: 最大下落の悪化 ≤ 3.0pt・5%未満の上昇 ≤ 1.0pt・最悪の世界の低下 ≤ 0.15pt
  G3 100年の代用: 30年の積立（起点1965〜1995）の市場との比の最悪 ≥ 0.95（10-16 の『最終』0.954 と同じくらい）
  選び方: 動かす量 ≤10 の候補のうち G1〜G3 をすべて満たすものから、主の Δ平均 が最大のもの
          （差が 0.03pt 未満なら動かす量の小さいほう→NVDA〔資産全体〕の低いほう）
  該当なし: 「決まりを満たす形は無い」と言い、G1 を満たす候補のうち Δ平均 が最大のものと外れた条件を名指しする
  どの結果でも配分は変えない（報告するだけ・入れるかはユーザーの明示指示）
参考（勧めに使わない）: 15%以上（P15π）・上振れ（P20・道の束）・世界ごとの年率の差（どの世界から来る上乗せか）・確かめの2枠・
  過去の転がる20年の積立・中身の集中（NVDA・半導体の連鎖）・もっと寄せる形の同じ検査。
回帰の検査: (a) 今が out/better_mix_check.json の『今』と一致（USD・崩れあり・小数1桁）
  (b) 感度の主が measure と 1e-9 以内（USD と円）。どれかが外れれば止める
使い方: python3 night/ret_lean_check.py → out/ret_lean_check.json
"""
import datetime, json, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'ret_lean_check.json')

NOW = '今'
FORMS = {
    NOW: {'QQQM': 40, 'SMH': 25, 'ITA': 10, 'SHLD': 5, 'XLV': 5, 'FBT': 5},
    'N5 NASDAQ100→SMH 5': {'QQQM': 35, 'SMH': 30, 'ITA': 10, 'SHLD': 5, 'XLV': 5, 'FBT': 5},
    'N10 NASDAQ100→SMH 10': {'QQQM': 30, 'SMH': 35, 'ITA': 10, 'SHLD': 5, 'XLV': 5, 'FBT': 5},
    'I1 SHLD→SMH': {'QQQM': 40, 'SMH': 30, 'ITA': 10, 'XLV': 5, 'FBT': 5},
    'I2 SHLD・FBT→SMH': {'QQQM': 40, 'SMH': 35, 'ITA': 10, 'XLV': 5},
    'I3 SHLD・FBT→NASDAQ100': {'QQQM': 50, 'SMH': 25, 'ITA': 10, 'XLV': 5},
    'M1 SHLD→SMH・NDX→SMH 5': {'QQQM': 35, 'SMH': 35, 'ITA': 10, 'XLV': 5, 'FBT': 5},
    'M2 SHLD→ITA・NDX→SMH 5': {'QQQM': 35, 'SMH': 30, 'ITA': 15, 'XLV': 5, 'FBT': 5},
    'M3 FBT→SMH・NDX→SMH 5': {'QQQM': 35, 'SMH': 35, 'ITA': 10, 'SHLD': 5, 'XLV': 5},
    'N15 NASDAQ100→SMH 15': {'QQQM': 25, 'SMH': 40, 'ITA': 10, 'SHLD': 5, 'XLV': 5, 'FBT': 5},
    'N20 NASDAQ100→SMH 20': {'QQQM': 20, 'SMH': 45, 'ITA': 10, 'SHLD': 5, 'XLV': 5, 'FBT': 5},
    'K3 守りを ITA 20・半導体 35': {'QQQM': 35, 'SMH': 35, 'ITA': 20},
    '参考 SMH60:ITA40': {'SMH': 54, 'ITA': 36},
    '参考 テックだけ': {'QQQM': 60, 'SMH': 30},
    '参考 NASDAQ100 だけ': {'QQQM': 90},
}
STEP_MAX = 10                                   # 「気味」＝資産の1割まで動かす
REFS = ('参考 SMH60:ITA40', '参考 テックだけ', '参考 NASDAQ100 だけ')
G1_MIN, G1_POS = 0.05, 4                        # 主の Δ平均 ≥ +0.05pt・感度5本のうち4本以上で正
G2_MDD, G2_P5, G2_WORST = -3.0, 1.0, -0.15      # pt（候補 − 今）
G3_FLOOR = 0.95                                 # 100年の代用 30年の積立の最悪
TIE = 0.03
CENT30 = '30年の積立（起点1965〜1995）'
PREV_REF = os.path.join(BASE, 'out', 'better_mix_check.json')
PREV_NAME = '今'
REG_KEYS = ('P15π', 'P5π（5%未満）', '最悪の世界', '最大下落', 'ぶれ', 'π加重の平均の年率')
FRAMES = ('USD・崩れあり（主）', 'USD・ドットコム級なし', '円・崩れあり')


def step(f, g):
    ks = set(f) | set(g)
    return sum(abs(f.get(k, 0) - g.get(k, 0)) for k in ks) / 2


def main():
    import unx_assets as U
    import upside_check as UC
    import ndx_swap_check as N
    import bestpf_eval as E
    t0 = time.time()
    W_CRASH, W_DC = UC.W_CRASH, UC.W_DC
    for f in FORMS.values():
        assert abs(sum(f.values()) - 90) < 1e-9, f

    res = U.build()
    rows, chains = res['rows'], res['chains']
    F = {k: dict(v) for k, v in FORMS.items()}
    steps = {nm: step(f, F[NOW]) for nm, f in F.items()}
    elig = [nm for nm in F if nm != NOW and nm not in REFS and steps[nm] <= STEP_MAX + 1e-9]
    assets = sorted({a for f in F.values() for a in f} | {'VOO'})
    miss = [a for a in assets if a not in rows]
    if miss:
        raise SystemExit(f'行が無い: {miss}')
    late = {a: min(chains[a]) for a in assets if min(chains[a]) > UC.FIRST}
    if late:
        raise SystemExit(f'系列が主の窓（2000-09〜）にそろわない: {late}')
    mega = U.mega_map(rows, assets)
    pi, _, _ = E.load_pi()
    _, sim = U.tables()
    U.log('USD の枠（', len(F), '形）・勧めの候補', len(elig))
    tab_usd = U.measure(F, rows, chains, mega=mega)
    ref = json.load(open(PREV_REF))['results']['USD・崩れあり（主）'][PREV_NAME]
    reg_a, ok_a = {}, True
    for k in REG_KEYS:
        a, b = tab_usd[W_CRASH][NOW][k], ref[k]
        same = UC.r1(a) == UC.r1(b)
        reg_a[k] = dict(better_mix_check=b, この道具=a, 一致=same)
        ok_a = ok_a and same
    k4, chips = N.chips_adj(rows, assets)
    vt_usd = N.variants(F, rows, chains, k4)
    reg_b = N.regress_variants(vt_usd, tab_usd)
    U.log('回帰の検査', ok_a, reg_b['max_abs_diff'])
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/ret_lean_check.py', kind='参考（ユーザーが頼んだ比べ・勧めの決まりは道具の頭に固定）',
               question='リターン重視気味で組むなら？',
               regression={'(a) 今が out/better_mix_check.json の『今』と一致（USD・崩れあり・小数1桁）': dict(ok=ok_a, rows=reg_a),
                           '(b) 感度の計算の主と unx_assets.measure（USD・丸める前・1e-9）': {k: v for k, v in reg_b.items() if k != 'rows'}})
    if not (ok_a and reg_b['ok']):
        doc['decision'] = '回帰の検査に失敗＝止めた'
        json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
        raise SystemExit('回帰の検査に失敗')
    U.log('円の枠')
    ch_jpy, fx_url = U.jpy_chains(chains)
    tab_jpy = U.measure(F, rows, ch_jpy, mega=mega)
    vt_jpy = N.variants(F, rows, ch_jpy, k4)
    reg_j = N.regress_variants(vt_jpy, tab_jpy)
    doc['regression']['(b) 円の枠でも同じ'] = {k: v for k, v in reg_j.items() if k != 'rows'}
    if not reg_j['ok']:
        doc['decision'] = '回帰の検査に失敗（円）＝止めた'
        json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
        raise SystemExit('回帰の検査に失敗（円）')

    U.log('100年の代用')
    cc, seats, cpct = U.castle_copy()
    cent = {nm: U.century_monthly(U.whole(f, cc)) for nm, f in F.items()}

    U.log('中身の集中（lookthrough）')
    N.CASTLE_ARG = ','.join(f'{s}={cpct / len(seats):g}' for s in seats)
    look = {}
    for nm, f in F.items():
        try:
            look[nm] = N.lookthrough(f)
            if '城' in look[nm]:
                look[nm]['城'] = f'{N.CASTLE_ARG}（席{len(seats)}社×{cpct / len(seats):g}%）'
        except Exception as e:                       # 参考だけ・読めなければ名指し
            look[nm] = dict(読めず=str(e)[:200])

    U.log('判定')
    frames = {FRAMES[0]: (vt_usd, W_CRASH), FRAMES[1]: (vt_usd, W_DC), FRAMES[2]: (vt_jpy, W_CRASH)}
    others = [k for k in F if k != NOW]
    judg = {x: {fn: N.judge(vt, wn, x, NOW) for fn, (vt, wn) in frames.items()} for x in others}
    r0 = tab_usd[W_CRASH][NOW]['_raw']

    def c30min(nm):
        d = cent.get(nm)
        if not d or not d.get(CENT30):
            return None
        return min(d[CENT30]['_v'].values())

    checks = {}
    for x in others:
        rx = tab_usd[W_CRASH][x]['_raw']
        per = judg[x][FRAMES[0]]['感度']
        dm_main = per['主']['差']['平均']
        npos = sum(v['差']['平均'] > 0 for v in per.values())
        d_mdd, d_p5, d_worst = 100 * (rx['mdd'] - r0['mdd']), 100 * (rx['P5'] - r0['P5']), 100 * (rx['worst'] - r0['worst'])
        g1 = bool(dm_main >= G1_MIN and npos >= G1_POS)
        g2 = bool(d_mdd >= G2_MDD and d_p5 <= G2_P5 and d_worst >= G2_WORST)
        cm = c30min(x)
        g3 = None if cm is None else bool(cm >= G3_FLOOR)
        fails = [k for k, ok in (('G1 期待値', g1), ('G2 守り', g2), ('G3 100年の代用', g3)) if not ok]
        nv = look.get(x, {}).get('NVDA（資産全体）')
        checks[x] = {'動かす量': steps[x], '勧めの候補': x in elig,
                     'G1 期待値': dict(ok=g1, 主のΔ平均=dm_main, 正の感度の数=npos, 感度ごとのΔ平均={k: v['差']['平均'] for k, v in per.items()}),
                     'G2 守り': dict(ok=g2, 最大下落の差=round(d_mdd, 2), 五未満の差=round(d_p5, 2), 最悪の世界の差=round(d_worst, 3)),
                     'G3 100年の代用': dict(ok=g3, 三十年の最悪=(None if cm is None else round(cm, 3))),
                     'すべて満たす': not fails, '外れた条件': fails, 'NVDA（資産全体）': nv}

    passed = [x for x in elig if checks[x]['すべて満たす']]

    def key(x):
        nv = checks[x]['NVDA（資産全体）']
        return (-checks[x]['G1 期待値']['主のΔ平均'], steps[x], nv if isinstance(nv, (int, float)) else 99.0)
    read = {}
    if passed:
        order = sorted(passed, key=key)
        best = order[0]
        tied = [x for x in order[1:] if checks[best]['G1 期待値']['主のΔ平均'] - checks[x]['G1 期待値']['主のΔ平均'] < TIE]
        if tied:                                      # 差が 0.03pt 未満 → 動かす量の小さいほう → NVDA の低いほう
            pool = [best] + tied
            best = sorted(pool, key=lambda x: (steps[x], checks[x]['NVDA（資産全体）'] if isinstance(checks[x]['NVDA（資産全体）'], (int, float)) else 99.0))[0]
        read['勧め'] = dict(形=best, 中身=F[best], 動かす量=steps[best], 同点の扱い=(tied or None),
                          読み=f'決まりを満たす形のうち期待値（主の Δ平均）が最大: {best}')
        read['決まりを満たした候補（Δ平均の順）'] = [dict(形=x, 主のΔ平均=checks[x]['G1 期待値']['主のΔ平均'], 動かす量=steps[x]) for x in order]
    else:
        g1s = sorted([x for x in elig if checks[x]['G1 期待値']['ok']], key=key)
        read['勧め'] = dict(形=None, 読み='決まりを満たす形は無い',
                          G1を満たした中でΔ平均が最大=(dict(形=g1s[0], 外れた条件=checks[g1s[0]]['外れた条件']) if g1s else 'G1 を満たす候補も無い'))
    read['どの結果でも'] = '配分は変えない（報告するだけ・入れるかはユーザーの明示指示）'

    U.log('参考: 上振れ・世界ごと・転がる積立')

    def show(r):
        return {k: r[k] for k in ('P15π', 'P15π（A2を外す）', 'P5π（5%未満）', 'P0π（元本割れ）', '最悪の世界', 'π加重の平均の年率', 'ぶれ', '最大下落',
                                  '崩れ2000型_16〜18年目', '過去の転がる20年で15%以上', '世界ごとの年率')}
    table = {}
    w0 = tab_usd[W_CRASH][NOW]['世界ごとの年率']
    for nm in F:
        r = tab_usd[W_CRASH][nm]
        q, pr_ = UC.upside(sim, r['_raw'], pi)
        table[nm] = dict(show(r), 上振れ=dict(pr_, 内部収益率の分位=q),
                         世界ごとの年率の差={k: round(r['世界ごとの年率'][k] - w0[k], 2) for k in w0})
    roll = {nm: UC.rolling(f, rows, chains) for nm, f in F.items()}
    cent_out = {nm: U.strip_century(d) for nm, d in cent.items() if d is not None}
    doc.update(
        forms=F, steps=steps, eligible=elig, rule=dict(STEP_MAX=STEP_MAX, G1=dict(min=G1_MIN, positive_of_5=G1_POS),
                                                          G2=dict(mdd=G2_MDD, p5=G2_P5, worst=G2_WORST), G3=dict(floor=G3_FLOOR), tie=TIE),
        checks=checks,
        judgments={x: {fn: dict(まとめ=j['まとめ'], 主の判定=j['主の判定'], 感度=j['感度']) for fn, j in judg[x].items()} for x in others},
        reading=read, pi=pi,
        results={'USD・崩れあり（主）': table, 'USD・ドットコム級なし': {nm: show(tab_usd[W_DC][nm]) for nm in F},
                 '円・崩れあり': {nm: show(tab_jpy[W_CRASH][nm]) for nm in F},
                 '過去の転がる積立（USD・2000-09〜2026-09）': roll, '100年の代用（全体の形）': cent_out,
                 '中身の集中（lookthrough・参考）': look},
        K4_半導体の基礎率={c: dict(Chips=(None if chips[c] is None else round(chips[c], 3)), 足す年率=round(100 * k4[c], 3)) for c in assets},
        frames={'USD': 'night/bestpf_check.py と同じ（ドル建て）', '円': f'月次のドル建ての値に FRED DEXJPUS の月末の比（{fx_url}）・B/C/D はドルのまま'},
        castle_copy=dict(seats=seats, castle_pct=cpct),
        caveats=['ETF 側だけを測る（個別株10は物差しの外・100年の代用だけ席の業種の写しで全体の形）',
                 'SHLD の 2023-09 以前は ITA のつなぎ（代理の門を通らない）',
                 '半導体の上乗せの多くは世界 A1・A2（2000〜2026 の実績）から来る——世界ごとの年率の差で見る',
                 '中身の集中は ETF の中身の写真（out/etf_profiles.json）の時点のまま',
                 '100年の代用で SMH は French の Chips・QQQM はテック65%＋市場35%・FBT は Drugs・SHLD は ITA と同じ写し',
                 '勧めの決まりは道具の頭に固定。配分は変えない'],
        decision='配分は変えない（報告するだけ）', secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    U.log('→', OUT, f'{time.time() - t0:.0f}秒')
    for nm in F:
        r = table[nm]
        U.log(f"{nm:<26} 量 {steps[nm]:4.0f} P15 {r['P15π']:5.1f} P20 {r['上振れ']['P20（道の束）']:5.1f} P5 {r['P5π（5%未満）']:5.1f} 最悪 {r['最悪の世界']:5.2f} "
              f"平均 {r['π加重の平均の年率']:5.2f} ぶれ {r['ぶれ']:5.1f} 下落 {r['最大下落']:6.1f} 過去20年15%以上 {r['過去の転がる20年で15%以上']:5.1f} 世界差 {r['世界ごとの年率の差']}")
    for x in others:
        c = checks[x]
        U.log(f"{x:<26} 候補 {c['勧めの候補']!s:<5} G1 {c['G1 期待値']['ok']!s:<5} Δ平均 {c['G1 期待値']['主のΔ平均']:+.3f} 正 {c['G1 期待値']['正の感度の数']} "
              f"G2 {c['G2 守り']['ok']!s:<5} {c['G2 守り']} G3 {c['G3 100年の代用']} NVDA {c['NVDA（資産全体）']} | DC {judg[x][FRAMES[1]]['感度']['主']['差']['平均']:+.3f} "
              f"円 {judg[x][FRAMES[2]]['感度']['主']['差']['平均']:+.3f}")
    U.log('集中', json.dumps({nm: (v.get('NVDA（資産全体）'), v.get('半導体の連鎖（下限〜上限）')) for nm, v in look.items()}, ensure_ascii=False))
    U.log('読み', json.dumps(read, ensure_ascii=False)[:3000])


if __name__ == '__main__':
    main()
