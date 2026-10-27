#!/usr/bin/env python3
"""night/smh25_where.py — SMH の5を他へ移すならどこか（2026-10-27・参考・判定なし）

ユーザーの問い「これよりSMHを5％移すならあなたはどうする？」への答えの材料。配分は変えない。
作りは night/etfonly_check.py を写した（形は全体の%・個別株0＝今の正本）。
形と物差しは結果を見る前にこのファイルで固定し、回す前にコミットする。

今: QQQM 40 / SMH 30 / ITA 15 / SHLD 5 / XLV 5 / FBT 5（2026-10-27 の正本）
候補（SMH 30→25・移す先に +5）: QQQM / ITA / XLV / FBT / SHLD / GDX / XLU
私の選び方（回す前に固定）:
  G1 π加重の平均の年率の差 ≥ −0.10pt（期待値をほとんど削らない）
  G2 最大下落と P5π（5%未満）の両方が今より良い（守りが実際に増える）
  G3 100年の代用（30年の中央）が下がらない
  G1〜G3 を満たす候補のうち、最大下落の改善が最も大きいもの。無ければ「移さない（今のまま）」。
回帰の検査: (a) 今が out/etfonly_check.json の『案（個別株なし）』と一致（USD・崩れあり・小数1桁）
  (b) 感度の主が measure と 1e-9 以内（USD と円）
使い方: python3 night/smh25_where.py → out/smh25_where.json
"""
import datetime, json, os, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
OUT = os.path.join(BASE, 'out', 'smh25_where.json')

NOW = '今'
BASEF = {'QQQM': 40, 'SMH': 30, 'ITA': 15, 'SHLD': 5, 'XLV': 5, 'FBT': 5}
DEST = ['QQQM', 'ITA', 'XLV', 'FBT', 'SHLD', 'GDX', 'XLU']
FORMS = {NOW: dict(BASEF)}
for d in DEST:
    f = dict(BASEF); f['SMH'] -= 5; f[d] = f.get(d, 0) + 5
    FORMS[f'SMH→{d}'] = f
REF = (os.path.join(BASE, 'out', 'etfonly_check.json'), '案（個別株なし）')
REG_KEYS = ('P15π', 'P5π（5%未満）', '最悪の世界', '最大下落', 'ぶれ', 'π加重の平均の年率')


def main():
    import unx_assets as U
    import upside_check as UC
    import ndx_swap_check as N
    import bestpf_eval as E
    t0 = time.time()
    W_CRASH, W_DC = UC.W_CRASH, UC.W_DC
    for k, f in FORMS.items():
        assert abs(sum(f.values()) - 100) < 1e-9, k
    res = U.build()
    rows, chains = res['rows'], res['chains']
    F = {k: dict(v) for k, v in FORMS.items()}
    assets = sorted({a for f in F.values() for a in f} | {'VOO'})
    miss = [a for a in assets if a not in rows]
    if miss:
        raise SystemExit(f'行が無い: {miss}')
    mega = U.mega_map(rows, assets)
    pi, _, _ = E.load_pi()
    _, sim = U.tables()
    tab_usd = U.measure(F, rows, chains, mega=mega)
    ref = json.load(open(REF[0]))['results']['USD・崩れあり（主）'][REF[1]]
    ok_a = all(UC.r1(tab_usd[W_CRASH][NOW][k]) == UC.r1(ref[k]) for k in REG_KEYS)
    k4, chips = N.chips_adj(rows, assets)
    vt_usd = N.variants(F, rows, chains, k4)
    reg_b = N.regress_variants(vt_usd, tab_usd)
    ch_jpy, fx_url = U.jpy_chains(chains)
    tab_jpy = U.measure(F, rows, ch_jpy, mega=mega)
    vt_jpy = N.variants(F, rows, ch_jpy, k4)
    reg_j = N.regress_variants(vt_jpy, tab_jpy)
    U.log('回帰の検査', ok_a, reg_b['ok'], reg_j['ok'])
    if not (ok_a and reg_b['ok'] and reg_j['ok']):
        raise SystemExit('回帰の検査に失敗')
    cent = {nm: U.strip_century(U.century_monthly(f)) for nm, f in F.items()}

    def show(r):
        return {k: r[k] for k in ('P15π', 'P5π（5%未満）', 'P0π（元本割れ）', '最悪の世界', 'π加重の平均の年率', 'ぶれ', '最大下落',
                                  '過去の転がる20年で15%以上', '世界ごとの年率')}
    table = {}
    for nm in F:
        r = tab_usd[W_CRASH][nm]
        q, pr_ = UC.upside(sim, r['_raw'], pi)
        table[nm] = dict(show(r), P20=pr_.get('P20（道の束）'))
    frames = {'USD・崩れあり（主）': (vt_usd, W_CRASH), 'USD・ドットコム級なし': (vt_usd, W_DC), '円・崩れあり': (vt_jpy, W_CRASH)}
    diffs = {x: {fn: {k: v['差'] for k, v in N.judge(vt, wn, x, NOW)['感度'].items()} for fn, (vt, wn) in frames.items()}
             for x in F if x != NOW}

    def c30(nm, key='中央値'):
        d = cent.get(nm) or {}
        w = next((v for k, v in d.items() if k.startswith('30年')), {})
        return w.get(key) if isinstance(w, dict) else None
    pick, why = None, {}
    b = table[NOW]
    for x in F:
        if x == NOW:
            continue
        r = table[x]
        g1 = r['π加重の平均の年率'] - b['π加重の平均の年率'] >= -0.10
        g2 = r['最大下落'] > b['最大下落'] and r['P5π（5%未満）'] < b['P5π（5%未満）']
        cx, cb = c30(x), c30(NOW)
        g3 = None if (cx is None or cb is None) else cx >= cb
        why[x] = dict(G1=g1, G2=g2, G3=g3, 最大下落の改善=round(r['最大下落'] - b['最大下落'], 2))
        if g1 and g2 and g3 and (pick is None or why[x]['最大下落の改善'] > why[pick]['最大下落の改善']):
            pick = x
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/smh25_where.py', kind='参考（配分は変えない・選び方は道具の頭に固定）',
               question='これよりSMHを5％移すならあなたはどうする？', forms=F,
               results={'USD・崩れあり（主）': table, 'USD・ドットコム級なし': {nm: show(tab_usd[W_DC][nm]) for nm in F},
                        '円・崩れあり': {nm: show(tab_jpy[W_CRASH][nm]) for nm in F}, '100年の代用': cent,
                        '感度5本の差': diffs},
               choice=dict(rule='G1 平均 ≥ −0.10pt ∧ G2 最大下落と5%未満が良い ∧ G3 100年30年の中央が下がらない → 最大下落の改善が最大',
                           per_candidate=why, pick=pick or '移さない（今のまま）'),
               caveats=['SHLD の 2023-09 以前は ITA のつなぎ', '分散の効く本（GDX・XLU）の価値は分散の上乗せの仮定に頼る'],
               secs=round(time.time() - t0))
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    for nm in F:
        r = table[nm]
        U.log(f"{nm:<10} 平均 {r['π加重の平均の年率']:5.2f} P15 {r['P15π']:5.1f} P20 {r['P20']} P5 {r['P5π（5%未満）']:5.1f} 最悪 {r['最悪の世界']:5.2f} "
              f"ぶれ {r['ぶれ']:5.1f} 下落 {r['最大下落']:6.1f} 過去20 {r['過去の転がる20年で15%以上']:5.1f} 100年30中央 {c30(nm)} 最悪 {c30(nm,'最悪')} 勝ち {c30(nm,'市場に勝った割合')}")
    U.log('選び', json.dumps(why, ensure_ascii=False), '→', pick)
    for x, d in diffs.items():
        U.log(x, json.dumps({fn: {k: v['平均'] for k, v in dd.items()} for fn, dd in d.items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
