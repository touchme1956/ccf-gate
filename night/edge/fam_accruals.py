#!/usr/bin/env python3
"""night/edge/fam_accruals.py — 系統 accruals（第6回）: 発生主義の利益が小さい会社の買いだけの組 vs 米国市場

事前登録 out/edge_prereg_r6.json の round6_families.accruals（線・費用・相手・期間は out/edge_prereg.json と同じ）。
  素材: JKP（Jensen・Kelly・Pedersen）米国の三分位ポートフォリオ（買いだけ）。特徴は事前登録の3本——
    oaccruals_at  営業の発生主義利益 ÷ 総資産（利益のうち現金の裏付けの無い部分）   Sloan 1996
    taccruals_at  総発生主義利益 ÷ 総資産（営業＋投資＋財務の発生主義）             Richardson・Sloan・Soliman・Tuna 2005
    oaccruals_ni  営業の発生主義利益 ÷ |純利益|（利益の何割が発生主義か）         Hafzalla・Lundholm・Van Winkle 2011
  良い側 = 発生主義が**小さい**側。確かめ方（select() の directions()）: 選定期間（〜2000-12）の米国データで
    JKP の因子（= direction ×（'3.0'−'1.0'））と '3.0'−'1.0' の相関が3本とも −1.000 ＝ JKP の direction は −1
    ＝ 良い側は '1.0'（値の小さい三分位）。三分位の月平均も 3本×2重みすべてで '1.0' > '2.0' > '3.0' の単調（定義と一致）。
  合成 = 良い側の脚を等分（毎月もとの比へ戻す）。その月に使う脚がすべてそろい、どの脚も銘柄数が下限以上の月だけを返す。

  ⚠ JKP の ret は米国の短期金利（T-bill）を引いた**米ドルの超過**（fam_payout.py・fam_old_firms.py で確かめ済み:
    JKP mkt(vw) + French RF − French 市場 ≒ 0）→ 総リターン = ret + French RF。
  先読み: JKP は月末 m−1 の特徴（会計値は決算期末から4か月以上遅らせて使う＝JKP 2023 の作り方）で組み、月 m のリターンを出す。
    この module はデータから何も推定しない（側・重み・脚は凍結した spec の定数）。月 m のリターンは JKP の月 m の行と
    月 m の RF だけで決まり、持つかどうかは月 m の行の銘柄数 n（m−1 月末に組んだ時点の数）だけで決まる。
    scratchpad の lookahead_accruals.py が切り口・毒・ずらし で確かめた（spec の lookahead_test に結果）。

  相手: French 米国市場（上限なしの時価加重）。費用: 片道の回転1あたり 0.25%。
  回転: 会計の信号の置き値 50%/年（事前登録 r6）＋ 等分の組は毎月等分へ戻す売買。
  社数の下限: 米国は三分位が50社以上の月だけ。再現の国は20社以上。
  再現: JKP 先進国22か国（米国を除く）に同じ特徴・同じ側・同じ重み。国の相手は JKP の国の mkt（vw）＋米国 RF（米ドル）。

使い方: python3 night/edge/fam_accruals.py          → 変種の表（選定の段・2000-12 まで）
        python3 night/edge/fam_accruals.py --save LOOKAHEAD.json   → 選んで凍結（out/edge/spec_accruals.json）
          LOOKAHEAD.json は先読み検査（scratchpad の lookahead_accruals.py）の結果。ok でなければ凍結しない
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h
import csv, io, math, statistics as S, zipfile
from concurrent.futures import ThreadPoolExecutor

FAMILY = {
    'key': 'accruals',
    'name': '発生主義の利益が小さい会社の買いだけ（JKP 営業・総発生主義利益の小さい三分位）',
    'implement': ('楽天証券の米国株（NISA 成長投資枠で買える・レバレッジではない）で、米国上場の大型・中型株を'
                  '直近の年次決算（10-K・決算期末から4か月以上たったもの）の「発生主義の利益」＝純利益−営業キャッシュフロー'
                  '（または貸借対照表の運転資本の増分−減価償却）を総資産で割って並べ、いちばん小さい1/3（利益が現金で裏付けられている会社）を'
                  '時価加重（1社の重みに上限＝JKP の vw_cap と同じく巨大株を抑える。vw なら上限なし）で持ち、年に1〜2回入れ替える。'
                  '発生主義の利益で選ぶ ETF は楽天の海外ETFの一覧に無い（米国でも専用の ETF はほぼ無い）＝個別株を30〜50社持つ近似になり、'
                  '決算の数字（キャッシュフロー計算書）を自分で集める手間がかかる。NISA の成長投資枠で個別株として買える'),
}

COST = 0.0025                     # 片道の回転100%につき（事前登録: 個別株の組）
TURN_ANN = 0.5                    # 会計の信号（年1回の決算）の置き値 50%/年（事前登録 r6）
MIN_N = 50                        # 米国: 三分位の銘柄数がこれ未満の月は使わない（事前登録 r6）
MIN_N_REPL = 20                   # 再現の国（事前登録 r6）
CHARS = ['oaccruals_at', 'taccruals_at', 'oaccruals_ni']
REPL = ['jpn', 'gbr', 'deu', 'fra', 'can', 'aus', 'che', 'swe', 'nld', 'ita', 'esp', 'hkg', 'sgp', 'dnk', 'nor', 'bel',
        'fin', 'aut', 'irl', 'prt', 'nzl', 'isr']          # 事前登録 r6 の先進国22か国
JKP = 'https://jkpfactors-data.s3.amazonaws.com/public/'
LOW, MID, HIGH = '1.0', '2.0', '3.0'

_MEMO = {}


# ───────────────────────── 読み込み ─────────────────────────
def _counts(region, ch, w):
    """三分位の銘柄数 n（h.jkp は返さないので、同じキャッシュを h.cached で読み h.guard を通す）"""
    url = f'{JKP}portfolios/%5B{region}%5D_%5B{ch}%5D_%5Bmonthly%5D_%5B{w}%5D.zip'
    z = zipfile.ZipFile(io.BytesIO(h.cached(f'jkp_portfolio_{region}_{ch}_{w}.zip', url)))
    out = {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        try:
            out.setdefault(x['pf'], {})[int(x['date'][:4]) * 100 + int(x['date'][5:7])] = int(float(x['n']))
        except (TypeError, ValueError, KeyError):
            continue
    return {k: h.guard(v) for k, v in out.items()}


def legs(region, ch, w):
    """→ {三分位: (超過リターン {m}, 銘柄数 {m})}。取れなければ {}"""
    k = (region, ch, w)
    if k not in _MEMO:
        try:
            p = h.jkp(region, ch, 'portfolio', w)
            n = _counts(region, ch, w)
            _MEMO[k] = {s: (p.get(s, {}), n.get(s, {})) for s in (LOW, MID, HIGH)}
        except Exception:
            _MEMO[k] = {}
    return _MEMO[k]


# ───────────────────────── 規則 ─────────────────────────
def build(spec, region, rf, min_n):
    """spec: {'chars': [...], 'sides': {ch: '1.0'|'3.0'}, 'w': 'vw_cap'|'vw'} → (総リターン {m}, 片道の回転 {m})
    脚（特徴ごとの三分位）を等分に持つ（1本なら素通し）。月 m に持つかどうかは月 m の行の銘柄数 n
    （m−1 月末に組んだ時点）だけで決まる。等分の組は毎月もとの比へ戻し、その売買を回転に足す"""
    L = []
    for c in spec['chars']:
        lg = legs(region, c, spec['w'])
        s = spec['sides'][c]
        if not lg or s not in lg or not lg[s][0]:
            return {}, {}
        L.append(lg[s])
    months = sorted(set.intersection(*[set(x[0]) for x in L]))
    k = len(L)
    ret, tv, prev = {}, {}, None
    for m in months:
        if m not in rf or any(x[1].get(m, 0) < min_n for x in L):
            prev = None
            continue
        reb = 0.0 if prev is None else 0.5 * sum(abs(p - 1 / k) for p in prev)
        rs = [x[0][m] + rf[m] for x in L]
        ret[m] = sum(rs) / k
        tv[m] = TURN_ANN / 12 + reb
        g = [(1 / k) * (1 + r) for r in rs]
        tot = sum(g)
        prev = [v / tot for v in g] if tot > 0 else None
    return ret, tv


def run(spec):
    mk, rf = h.us_market()
    ret, tv = build(spec, 'usa', rf, spec.get('min_n', MIN_N))
    out = {'ret': ret, 'bench': mk, 'rf': rf, 'turnover': tv, 'cost': COST, 'markets': {}}

    def one(c):
        try:
            jm = h.jkp(c, 'mkt', 'factor', 'vw')          # その国の市場（上限なしの時価加重・米ドルの超過）
        except Exception:
            return c, None
        bench = {m: v + rf[m] for m, v in jm.items() if m in rf}
        r, t = build(spec, c, rf, spec.get('min_n_repl', MIN_N_REPL))
        r = {m: v for m, v in r.items() if m in bench}
        return c, ({'ret': r, 'bench': bench, 'rf': rf, 'turnover': {m: t[m] for m in r}, 'cost': COST}
                   if len(r) >= 24 and bench else None)
    with ThreadPoolExecutor(8) as ex:
        for c, x in ex.map(one, spec.get('replicate', [])):
            if x:
                out['markets'][c] = x
    return out


# ───────────────────────── 選定（2000-12 まで） ─────────────────────────
def _corr(a, b):
    ma, mb = S.mean(a), S.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def directions():
    """良い側を選定期間の米国データで決める: JKP 因子 = direction ×（'3.0'−'1.0'）→ 相関の符号。三分位の平均の並びも添える"""
    out = {}
    for c in CHARS:
        row = {}
        for w in ('vw_cap', 'vw'):
            p = h.jkp('usa', c, 'portfolio', w)
            f = h.jkp('usa', c, 'factor', w)
            ms = sorted(set(f) & set(p[LOW]) & set(p[HIGH]))
            r = _corr([f[m] for m in ms], [p[HIGH][m] - p[LOW][m] for m in ms])
            row[w] = {'corr_factor_vs_3minus1': round(r, 4), 'months': len(ms), 'from': ms[0], 'to': ms[-1],
                      'tercile_mean_pct_mo': {s: round(S.mean(p[s][m] for m in ms) * 100, 3) for s in (LOW, MID, HIGH)}}
        cs = [row[w]['corr_factor_vs_3minus1'] for w in row]
        side = HIGH if all(x > 0 for x in cs) else LOW if all(x < 0 for x in cs) else None
        out[c] = {'side': side, 'jkp_direction': (1 if side == HIGH else -1 if side == LOW else None), **row}
    return out


def variants(sides):
    """成績を見る前に決めた変種 → [(名前, spec, 選べるか)]。
    選べる14: 1本ずつ3 × 重み2 ／ 2本の等分3 × 重み2 ／ 3本の等分 × 重み2。
    参考3（選ばない・向きの確かめ）: 発生主義の大きい側（悪い側）の三分位 vw_cap"""
    V = []
    combos = [[c] for c in CHARS] + [[a, b] for i, a in enumerate(CHARS) for b in CHARS[i + 1:]] + [list(CHARS)]
    for cs in combos:
        for w in ('vw_cap', 'vw'):
            nm = ('+'.join(cs) if len(cs) < 3 else 'all3') + f'|{w}'
            V.append((nm, {'chars': cs, 'w': w, 'sides': {c: sides[c] for c in cs}}, True))
    bad = {LOW: HIGH, HIGH: LOW}
    for c in CHARS:
        V.append((f'{c}|vw_cap|悪い側（参考）', {'chars': [c], 'w': 'vw_cap', 'sides': {c: bad[sides[c]]}}, False))
    return V


def beta(ret, mk, rf, a=None, b=None):
    ms = [m for m in sorted(set(ret) & set(mk)) if (a is None or m >= a) and (b is None or m <= b)]
    x = [mk[m] - rf[m] for m in ms]
    y = [ret[m] - rf[m] for m in ms]
    mx, my = S.mean(x), S.mean(y)
    bt = sum((p - mx) * (q - my) for p, q in zip(x, y)) / sum((p - mx) ** 2 for p in x)
    al = (my - bt * mx) * 1200
    return round(bt, 2), round(al, 2)


SUBS = (('1952-1962', None, 196212), ('1963-1995', 196301, 199512), ('1996-2000（Sloan 公表後）', 199601, 200012))


def select():
    assert h.PHASE == 'select'
    mk, rf = h.us_market()
    capm = {m: v + rf[m] for m, v in h.jkp('usa', 'mkt', 'factor', 'vw_cap').items() if m in rf}
    D = directions()
    sides = {c: D[c]['side'] for c in CHARS}
    assert all(sides.values()), D
    rows = []
    for name, sp, ok in variants(sides):
        r, tv = build(sp, 'usa', rf, MIN_N)
        st = h.stats(r, mk, rf, b=h.SEL_END, turnover=tv, cost=COST)
        sub = {}
        for lab, a, b in SUBS:
            s2 = h.stats(r, mk, rf, a=a, b=b, turnover=tv, cost=COST)
            sub[lab] = {'excess': s2['excess'], 't': s2['t']} if s2 else None
        st_cap = h.stats(r, capm, rf, b=h.SEL_END, turnover=tv, cost=COST)
        bt, al = beta(r, mk, rf, b=h.SEL_END)
        rows.append({'name': name, 'eligible': ok, 'spec': sp, 'stats': st, 'sub': sub, 'beta': bt, 'alpha_capm': al,
                     'ex_vs_jkp_capped_mkt': st_cap['excess'] if st_cap else None,
                     'turnover_yr': round(sum(tv.values()) / len(tv) * 12, 3) if tv else None})
        print(f"{'○' if ok else '参'} {name:40} {st['from']}〜 ex{st['excess']:6} t{st['t']:6} (NW{st['t_nw']}) "
              f"vol{st['vol']}/{st['bench_vol']} dd{st['maxdd']}/{st['bench_maxdd']} β{bt} α{al} 回転{rows[-1]['turnover_yr']} "
              f"対capmkt {rows[-1]['ex_vs_jkp_capped_mkt']} 10年窓{st['roll10_win']}  部分 {sub}")
    return D, rows


def _lookahead_text(res):
    return ('scratchpad の lookahead_accruals.py で確かめた（すべて食い違い0）: '
            f"(1) 切り口: EDGE_SEL_END=199012 と 200012 で別プロセスに走らせ、1990-12 までの規則・相手・回転（{res['prefix_months']}か月）と"
            f"他の市場（{res['prefix_markets']}か国）の規則のリターン・回転が 1e-12 で一致（全14の選べる変種）。"
            f"(2) 未来の毒: 1985-12 より後の脚のリターン・銘柄数・米国市場・短期金利をすべて乱数に置き換えても、1985-12 以前の規則のリターンと回転が"
            f"1か月も変わらない（{res['poison_before']}か月・後の {res['poison_after_changed']}か月は変わる＝毒は効いている）。"
            f"(3) ずらし: 1985-12 より後の脚の値を1か月後ろへずらして壊しても、それ以前は不変（後ろは変わる）。"
            f"(4) 月合わせ: 月 m の総リターン − 月 m の RF = 脚の月 m の超過の等分（差の最大 {res['align_maxdiff']:.1e}）。"
            '(5) 同じ月の先読み: 月 m に持つかどうかは月 m の行の銘柄数 n だけで決め、n は JKP が m−1 月末に組んだ時点の数（fam_old_firms.py が年齢の三分位で確かめた JKP のファイルの作り）。'
            '側（信号の向き）は spec の定数で、データから再推定しない。この module は全期間の平均・分位・標準化を一切使わない。'
            '会計値は JKP が決算期末から4か月以上遅らせて使う（JKP 2023）ので、月 m の組は m−1 月末に公表済みの決算だけに基づく')


def main(save=False, la=None):
    D, rows = select()
    elig = [r for r in rows if r['eligible'] and r['stats'] and r['stats']['excess'] >= 1.0]
    if elig:
        best = max(elig, key=lambda r: r['stats']['t'])
        how = '事前登録どおり（選定期間の費用後の超過が +1%/年以上の変種の中で、費用後の超過の t が最大）'
    else:
        best = max((r for r in rows if r['eligible']), key=lambda r: r['stats']['t'])
        how = 'どの変種も +1%/年 に届かなかった。選べる変種の中で費用後の超過の t が最大のものを選んだ（線には届いていない）'
    spec = dict(best['spec'])
    spec.update({'min_n': MIN_N, 'min_n_repl': MIN_N_REPL, 'replicate': REPL, 'turn_ann': TURN_ANN,
                 'side_note': "'1.0' = 発生主義の利益が小さい三分位（JKP の direction −1）"})
    r = run(spec)
    st = h.stats(r['ret'], r['bench'], r['rf'], b=h.SEL_END, turnover=r['turnover'], cost=r['cost'])
    mkt_sel = {}
    for c, x in r['markets'].items():
        s2 = h.stats(x['ret'], x['bench'], x['rf'], b=h.SEL_END, turnover=x['turnover'], cost=x['cost'])
        if s2:
            mkt_sel[c] = {'from': s2['from'], 'years': s2['years'], 'excess': s2['excess'], 't': s2['t']}
    tbl = [{'name': x['name'], 'eligible': x['eligible'], 'from': x['stats']['from'], 'excess': x['stats']['excess'],
            't': x['stats']['t'], 't_nw': x['stats']['t_nw'], 'vol': x['stats']['vol'], 'maxdd': x['stats']['maxdd'],
            'beta': x['beta'], 'alpha_capm': x['alpha_capm'], 'ex_vs_jkp_capped_mkt': x['ex_vs_jkp_capped_mkt'],
            'sub_periods': x['sub'], 'turnover_yr': x['turnover_yr']} for x in rows]
    print('選んだ:', best['name'], how)
    print('選定期間:', st)
    print('他の市場（選定期間・参考）:', mkt_sel)
    if not save:
        return best, st
    assert la and la.get('ok'), la
    sub = best['sub']
    g = {x['name']: x for x in rows}
    sloan = g['oaccruals_at|vw_cap']
    vwv = g[best['name'].split('|')[0] + '|vw']
    badv = g[f"{best['spec']['chars'][0]}|vw_cap|悪い側（参考）"] if len(best['spec']['chars']) == 1 else None
    pos = sum(1 for v in mkt_sel.values() if v['excess'] > 0)
    rationale = (
        f"【規則】{best['name']}: 米国上場株を JKP の特徴 {'・'.join(best['spec']['chars'])} で三分位に分け、発生主義の利益が小さい三分位"
        "（'1.0'）を買いだけで持つ" + ('（脚は等分・毎月戻す）' if len(best['spec']['chars']) > 1 else '') +
        f"。重みは {best['spec']['w']}（vw_cap＝NYSE の80%点で1社の重みに上限／vw＝上限なしの時価加重）。組は JKP が m−1 月末に組んだものをそのまま使う。"
        '【なぜ】Sloan（1996, The Accounting Review）: 利益のうち現金の裏付けの無い部分（発生主義の利益＝運転資本の増分−減価償却）は'
        '現金の部分より持続しにくいのに、投資家は利益を一まとめに見て両者の持続性の差を株価に織り込まない＝発生主義の利益が大きい会社は'
        '翌年以降に利益が落ちて株価が失望し、小さい会社は相対的に報われる（1962-1991 の米国で両端の十分位の差 年約10%）。'
        '経営者の利益調整（引当金・在庫・売掛金の積み増し）の痕跡でもある。'
        'oaccruals_ni は同じ発生主義の利益を純利益の絶対値で割る（利益の何割が発生主義か＝Hafzalla・Lundholm・Van Winkle 2011 の percent accruals）。'
        '⚠ oaccruals_ni（2011）と taccruals_at（Richardson ら 2005）の定義は2001年以降に公表された——2000年までに知られていたのは Sloan の oaccruals_at だけ。'
        '事前登録 r6 はこの3本を系統に並べたので、選び方（t が最大）どおりに選んだが、その分だけ『後から見つかった測り方』を選ぶ後知恵がある。'
        f"【選定期間 {st['from']}〜{st['to']}（{st['years']}年）】費用後の年率 {st['cagr']}% 対 French 米国市場 {st['bench_cagr']}%、"
        f"超過 {st['excess']:+}%/年、t {st['t']}（Newey-West {st['t_nw']}）、ぶれ {st['vol']}% 対 {st['bench_vol']}%、"
        f"最大下落 {st['maxdd']}% 対 {st['bench_maxdd']}%、転がる10年で勝った窓 {st['roll10_win']}。"
        f"市場に対するβ {best['beta']}・CAPM のα {best['alpha_capm']:+}%/年。JKP の上限つき市場（vw_cap）に対しては {best['ex_vs_jkp_capped_mkt']:+}%/年"
        '＝超過のうち「上限つきの重み（中型寄り）」の分は小さい。'
        f"部分期間: 1952-1962 {sub['1952-1962']['excess']:+}%/年（t {sub['1952-1962']['t']}）・1963-1995 {sub['1963-1995']['excess']:+}%/年（t {sub['1963-1995']['t']}）・"
        f"1996-2000（Sloan の公表後）{sub['1996-2000（Sloan 公表後）']['excess']:+}%/年（t {sub['1996-2000（Sloan 公表後）']['t']}）＝効きはほぼ 1963-1995 に集まり、公表後の5年は小さい。"
        f"参考: Sloan 自身の測り方 oaccruals_at|vw_cap は {sloan['stats']['excess']:+}%/年（t {sloan['stats']['t']}）・公表後 {sloan['sub']['1996-2000（Sloan 公表後）']['excess']:+}%/年。"
        f"上限なしの vw では {vwv['stats']['excess']:+}%/年（t {vwv['stats']['t']}）＝巨大株の重みを抑えないと効きは6割ほどに縮む。"
        + (f"悪い側（発生主義の大きい三分位・vw_cap）は {badv['stats']['excess']:+}%/年（t {badv['stats']['t']}）で、良い側より悪い（系統の前提の向き）。" if badv else '') +
        f"【選び方】{how}。選べる14変種はすべて +1%/年 以上で t 2.6〜5.6（3本とも同じ向き・どの組でも効く＝一本の数字だけで効く規則ではない）。"
        f"【他の市場（選定期間・参考）】国のデータは 1983〜1998 年に始まり 2〜17 年しかない。超過が正は {pos}/{len(mkt_sel)} か国＝選定期間の国の比較はほぼ雑音。"
        '【予想】事前登録 r6 の予想どおり、米国では公表後に弱まった（1996-2000 の小ささ）。ホールドアウトで +1%/年・t≥2 を満たす見込みは高くない。'
    )
    extra = {'implement': FAMILY['implement'], 'family_name': FAMILY['name'], 'lookahead_test': _lookahead_text(la),
             'lookahead_result': la, 'directions': D, 'variants_table': tbl, 'markets': list(r['markets']),
             'markets_selection_period': mkt_sel, 'selection_note': how,
             'variants_note': '選べる14（1本ずつ3・2本の等分3・3本の等分1 × 重み vw_cap/vw）＋参考3（悪い側・向きの確かめ・選ばない）＝17。'
                              '変種の一覧は、向きの確かめ（3本の三分位の月平均の並び）を見た後・変種の成績を見る前に「すべての組み合わせ」として固定した',
             'benchmark': 'French 米国市場（Mkt-RF＋RF・CRSP 全上場の上限なし時価加重）。他の国は JKP の国の mkt（vw＝上限なし・米ドル超過）＋French RF',
             'cost_note': '片道の回転100%につき0.25%。回転は 50%/年（事前登録 r6 の会計の信号の置き値）＋等分の組の毎月の戻し',
             'eligible_variants': sum(1 for x in rows if x['eligible']), 'reference_variants': sum(1 for x in rows if not x['eligible'])}
    doc = h.save_spec('accruals', spec, rationale, len(rows), st, extra)
    print('凍結:', best['name'], doc['n_variants_tried'])
    return doc


if __name__ == '__main__':
    if '--save' in sys.argv:
        import json
        la = json.load(open(sys.argv[sys.argv.index('--save') + 1]))
        main(save=True, la=la)
    else:
        main(save=False)
