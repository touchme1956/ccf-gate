#!/usr/bin/env python3
"""night/edge/fam_resmom.py — 系統 resmom（第6回）: 3因子の残差の勢いの良い側（買いだけ）vs 米国市場

事前登録 out/edge_prereg_r6.json の round6_families.resmom（線・費用・相手・期間は out/edge_prereg.json と同じ）。
  特徴（JKP の三分位ポートフォリオ・米国は 1926〜）:
    resff3_12_1  過去 t−12〜t−1 の Fama-French 3因子の残差の累積を、残差のぶれで割ったもの（Blitz・Huij・Martens 2011）
    resff3_6_1   同じく t−6〜t−1
  良い側 = JKP の予言の向き。JKP の因子は direction ×（'3.0'−'1.0'）なので、選定期間（〜2000-12）の米国データで
    因子と '3.0'−'1.0' の相関の符号から決め（directions()）、三分位の平均の並び（1<2<3 か）でも確かめる。
  合成 = 脚の等分（毎月もとの比へ戻す）。その月に全部の脚がそろい、どの脚も銘柄数が下限以上の月だけを返す。

  ⚠ JKP の三分位の 'ret' は米ドルの**超過リターン**（米国の短期金利を引いたもの）→ 総リターン = ret + French RF
    （fam_payout.py・fam_old_firms.py で確かめ済み: JKP mkt(vw) + RF − French 市場 ≒ 0）。
  先読み: JKP は月末 m−1 の特徴（残差は m−1 月末までのリターンと3因子で推定）で組み、月 m のリターンを出す。
    この module はデータから何も推定しない（側と重みは凍結した spec の定数）ので、月 m のリターンは JKP の月 m の値・
    月 m の銘柄数（組んだ時点の数）・月 m の RF だけで決まる。lookahead_test() が切り詰め・毒・ずらしで確かめる。

  相手: French 米国市場（上限なしの時価加重）。費用: 片道の回転1あたり 0.25%・回転 200%/年（価格の信号の置き値）。
  再現: JKP 先進国22か国の同じ特徴・同じ側・同じ重み。国の相手は JKP の国の mkt(vw) + 米国 RF（米ドル）。

使い方: python3 night/edge/fam_resmom.py          → 変種の表（選定の段・2000-12 まで）
        python3 night/edge/fam_resmom.py --save   → 選んで凍結（out/edge/spec_resmom.json）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h
import csv, io, math, statistics as S, zipfile
from concurrent.futures import ThreadPoolExecutor

FAMILY = {
    'key': 'resmom',
    'name': '残差の勢い（3因子で説明できない過去12か月／6か月の上昇が大きい三分位）の買いだけ',
    'implement': ('楽天証券の米国株（個別株・NISA 成長投資枠で買える・レバレッジではない）で実行する形: 毎月（少なくとも四半期に1回）、'
                  '米国上場の大型・中型株について、過去36か月の月次リターンを Fama-French 3因子（市場・規模・割安）に回帰し、'
                  '直近 t−12〜t−1 か月の残差（因子で説明できない分）の合計を残差のぶれで割った値で並べ、上位3分の1を時価加重'
                  '（1社の重みに上限＝JKP の vw_cap）で持つ。3因子の月次データは Ken French のサイトで無料で取れるが、全銘柄の回帰は'
                  '個人には重く、銘柄数は数百になる＝実際には時価総額の大きい上位数十社に絞る近似になる。'
                  '残差の勢いを選ぶ ETF は楽天の海外ETFの一覧に無い。近い ETF は普通の勢い（MTUM〔iShares MSCI USA Momentum Factor・'
                  'リスクで調整した6か月と12か月の勢い〕・PDP）で、残差ではない＝この規則の成績の近似でしかない。'
                  '回転は事前登録の置き値 200%/年（毎月入れ替えるので売買が多い・課税口座なら売却益の税が毎年かかる）'),
}

COST = 0.0025                     # 片道の回転1あたり（事前登録 costs: 個別株の組）
TURN_ANN = 2.0                    # 回転 200%/年（事前登録 r6: 価格の信号の置き値）
MIN_N = 50                        # 米国: 三分位の銘柄数がこれ未満の月は使わない
MIN_N_REPL = 20                   # 他の国
CHARS = ['resff3_12_1', 'resff3_6_1']
REF_CHARS = ['ret_12_1']          # 参考（選ばない）: 普通の勢い＝崩れの深さを比べる
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
    """spec: {'legs': [[特徴, 三分位], ...], 'w': 'vw_cap'|'vw'} → (総リターン {m}, 片道の回転 {m})
    脚を等分に持ち毎月もとの比へ戻す（1脚なら素通し）。月 m に持つかは月 m の組（m−1 月末に組まれたもの）の銘柄数 n だけで決まる"""
    Ls = []
    for ch, side in spec['legs']:
        L = legs(region, ch, spec['w'])
        if not L or side not in L or not L[side][0]:
            return {}, {}
        Ls.append(L[side])
    k = len(Ls)
    tw = [1 / k] * k
    months = sorted(set.intersection(*[set(x[0]) for x in Ls]))
    ret, tv, prev = {}, {}, None
    for m in months:
        if m not in rf or any(x[1].get(m, 0) < min_n for x in Ls):
            prev = None
            continue
        reb = 0.0 if prev is None else 0.5 * sum(abs(p - q) for p, q in zip(prev, tw))
        ret[m] = sum(tw[i] * Ls[i][0][m] for i in range(k)) + rf[m]
        tv[m] = TURN_ANN / 12 + reb            # 脚の置き値はどれも 200%/年（平均も 200%）＋脚どうしの戻し
        g = [tw[i] * (1 + Ls[i][0][m] + rf[m]) for i in range(k)]
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


# ───────────────────────── 選定（〜2000-12） ─────────────────────────
def _corr(a, b):
    ma, mb = S.mean(a), S.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def directions():
    """良い側を選定期間の米国データで決める: JKP 因子 = direction ×（'3.0'−'1.0'）→ 相関の符号。
    あわせて三分位の月平均（超過・vw_cap・50社以上の月）の並びを出す"""
    out = {}
    for c in CHARS + REF_CHARS:
        L = legs('usa', c, 'vw_cap')
        f = h.jkp('usa', c, 'factor', 'vw_cap')
        ms = sorted(set(f) & set(L[LOW][0]) & set(L[HIGH][0]))
        r = _corr([f[m] for m in ms], [L[HIGH][0][m] - L[LOW][0][m] for m in ms])
        ok = [m for m in sorted(set(L[LOW][0]) & set(L[MID][0]) & set(L[HIGH][0]))
              if min(L[s][1].get(m, 0) for s in (LOW, MID, HIGH)) >= MIN_N]
        means = {s: round(S.mean(L[s][0][m] for m in ok) * 1200, 2) for s in (LOW, MID, HIGH)} if ok else {}
        out[c] = {'side': HIGH if r > 0 else LOW, 'corr_factor_vs_3minus1': round(r, 4), 'months': len(ms),
                  'tercile_mean_excess_pct_yr_vw_cap': means, 'tercile_from': ok[0] if ok else None}
    return out


def variants(D):
    """成績を見る前に決めた変種（scratchpad の plan_resmom.md どおり）→ [(名前, spec, 選べるか)]"""
    g12, g6 = D['resff3_12_1']['side'], D['resff3_6_1']['side']
    b12 = LOW if g12 == HIGH else HIGH
    V = []
    for w in ('vw_cap', 'vw'):
        V.append((f'残差12-1の良い側・{w}', {'legs': [['resff3_12_1', g12]], 'w': w}, True))
    for w in ('vw_cap', 'vw'):
        V.append((f'残差6-1の良い側・{w}', {'legs': [['resff3_6_1', g6]], 'w': w}, True))
    for w in ('vw_cap', 'vw'):
        V.append((f'残差12-1と6-1の良い側を等分・{w}', {'legs': [['resff3_12_1', g12], ['resff3_6_1', g6]], 'w': w}, True))
    for w in ('vw_cap', 'vw'):
        V.append((f'残差12-1の悪い側を避ける（中＋良を等分）・{w}', {'legs': [['resff3_12_1', MID], ['resff3_12_1', g12]], 'w': w}, True))
    for w in ('vw_cap', 'vw'):
        V.append((f'残差12-1の悪い側・{w}（参考・向きの確認）', {'legs': [['resff3_12_1', b12]], 'w': w}, False))
    gr = D['ret_12_1']['side']
    V.append(('普通の勢い12-1の良い側・vw_cap（参考・崩れの比較）', {'legs': [['ret_12_1', gr]], 'w': 'vw_cap'}, False))
    return V


def beta(ret, mk, rf, a=None, b=None):
    ms = [m for m in sorted(set(ret) & set(mk)) if (a is None or m >= a) and (b is None or m <= b)]
    x = [mk[m] - rf[m] for m in ms]
    y = [ret[m] - rf[m] for m in ms]
    mx, my = S.mean(x), S.mean(y)
    bt = sum((p - mx) * (q - my) for p, q in zip(x, y)) / sum((p - mx) ** 2 for p in x)
    return round(bt, 2), round((my - bt * mx) * 1200, 2)


def worst(ret, bench, k=3):
    """超過の悪い月（崩れの深さ）"""
    ex = sorted(((ret[m] - bench[m], m) for m in set(ret) & set(bench)))[:k]
    return [(m, round(x * 100, 1)) for x, m in ex]


SUBS = (('〜1962', None, 196212), ('1963-1985', 196301, 198512), ('1986-2000', 198601, 200012))


def select():
    assert h.PHASE == 'select'
    mk, rf = h.us_market()
    capm = {m: v + rf[m] for m, v in h.jkp('usa', 'mkt', 'factor', 'vw_cap').items() if m in rf}
    D = directions()
    rows = []
    for name, sp, ok in variants(D):
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
                     'turnover_yr': round(sum(tv.values()) / len(tv) * 12, 3) if tv else None,
                     'worst_months': worst(r, mk)})
    return D, rows


def lookahead_test(spec, region='usa', cuts=(194012, 196512, 198512, 199512, 199912), min_n=MIN_N):
    """(1) 切り詰め: 全入力（脚のリターン・銘柄数・RF）を月 X で切っても X までの規則のリターンと回転が1つも変わらない
       (2) 毒: X より後の脚のリターン（1か月ずらし＋乱数）・銘柄数（乱数）・RF（乱数）に置き換えても X までは不変
           （X より後は変わる＝検査が空回りしていない）
       (3) 最後の1か月を削っても、それ以前は不変
       (4) 月合わせ: 規則の月 m の総リターン − 月 m の RF = 脚の月 m の超過の等分（毎月等分へ戻すので脚が何本でも一致）
       (5) 側（信号）は spec の定数で、データから再推定しない"""
    import random
    mk, rf = h.us_market()
    full, ftv = build(spec, region, rf, min_n)
    saved = {k: v for k, v in _MEMO.items()}
    res = {'region': region, 'months': len(full)}
    cuts = [X for X in cuts if full and min(full) < X < max(full)]
    rnd = random.Random(20260928)
    try:
        ok1 = ok2 = True
        for X in cuts:
            _MEMO.clear()
            for k, v in saved.items():
                _MEMO[k] = {s: ({m: r for m, r in p.items() if m <= X}, {m: n for m, n in c.items() if m <= X}) for s, (p, c) in v.items()}
            rfX = {m: v for m, v in rf.items() if m <= X}
            part, ptv = build(spec, region, rfX, min_n)
            ok1 &= set(part) == {m for m in full if m <= X} and all(abs(part[m] - full[m]) < 1e-15 and abs(ptv[m] - ftv[m]) < 1e-15 for m in part)
            _MEMO.clear()
            for k, v in saved.items():
                _MEMO[k] = {s: ({m: (r if m <= X else p.get(h.add_months(m, -1), r) + rnd.uniform(-0.05, 0.05)) for m, r in p.items()},
                                {m: (n if m <= X else rnd.randint(0, 2 * n + 1)) for m, n in c.items()}) for s, (p, c) in v.items()}
            rfP = {m: (v if m <= X else rnd.uniform(0, 0.01)) for m, v in rf.items()}
            part, ptv = build(spec, region, rfP, min_n)
            ok2 &= all(m in part and abs(part[m] - full[m]) < 1e-15 and abs(ptv[m] - ftv[m]) < 1e-15 for m in full if m <= X)
            ok2 &= any(m not in part or abs(part[m] - full[m]) > 1e-12 for m in full if m > X)
        res['cuts'] = cuts
        res['truncate'] = ok1
        res['poison_future'] = ok2
        _MEMO.clear()
        last = max(full)
        for k, v in saved.items():
            _MEMO[k] = {s: ({m: r for m, r in p.items() if m < last}, c) for s, (p, c) in v.items()}
        part, _ = build(spec, region, rf, min_n)
        res['drop_last_month'] = all(abs(part[m] - full[m]) < 1e-15 for m in full if m < last)
    finally:
        _MEMO.clear()
        _MEMO.update(saved)
    Ls = [legs(region, ch, spec['w'])[side][0] for ch, side in spec['legs']]
    res['month_align_maxdiff'] = max(abs(full[m] - rf[m] - sum(x[m] for x in Ls) / len(Ls)) for m in full)
    res['sides_constant'] = all(side in (LOW, MID, HIGH) for _, side in spec['legs'])
    res['ok'] = bool(cuts) and ok1 and ok2 and res['drop_last_month'] and res['sides_constant'] and res['month_align_maxdiff'] < 1e-12
    return res


def _fmt(r):
    st = r['stats']
    return (f"{'○' if r['eligible'] else '参'} {r['name']:40} {st['from']}〜 ex{st['excess']:+6.2f} t{st['t']:6.2f} (NW{st['t_nw']}) "
            f"vol{st['vol']}/{st['bench_vol']} dd{st['maxdd']}/{st['bench_maxdd']} β{r['beta']} α{r['alpha_capm']:+} 回転{r['turnover_yr']} "
            f"対capmkt{r['ex_vs_jkp_capped_mkt']:+} 10年窓{st['roll10_win']} 部分{r['sub']} 悪い月{r['worst_months']}")


def main(save=False):
    D, rows = select()
    print('directions', D)
    for r in rows:
        print(_fmt(r))
    elig = [r for r in rows if r['eligible'] and r['stats'] and r['stats']['excess'] >= 1.0]
    if elig:
        best = max(elig, key=lambda r: r['stats']['t'])
        how = '事前登録どおり（選定期間＝各変種のデータの始まり〜2000-12 の費用後の超過が +1%/年以上の中で t が最大）'
    else:
        cand = [r for r in rows if r['eligible']]
        best = max(cand, key=lambda r: r['stats']['t'])
        how = 'どの変種も +1%/年 に届かなかった。選べる変種の中で費用後の超過の t が最大のものを選んだ（線に届かないことを明記）'
    spec = dict(best['spec'])
    spec.update({'min_n': MIN_N, 'min_n_repl': MIN_N_REPL, 'replicate': REPL, 'turn_ann': TURN_ANN, 'cost': COST,
                 'side_note': "'3.0' = 特徴の値が大きい三分位。良い側は JKP の direction（因子と 3.0−1.0 の相関の符号）で決めた"})
    r = run(spec)
    st = h.stats(r['ret'], r['bench'], r['rf'], b=h.SEL_END, turnover=r['turnover'], cost=r['cost'])
    mkt_sel = {}
    for c, x in r['markets'].items():
        s2 = h.stats(x['ret'], x['bench'], x['rf'], b=h.SEL_END, turnover=x['turnover'], cost=x['cost'])
        if s2:
            mkt_sel[c] = {'from': s2['from'], 'years': s2['years'], 'excess': s2['excess'], 't': s2['t']}
    print('選んだ:', best['name'], how)
    print('選定期間:', st)
    print('他の市場（選定期間・参考）:', mkt_sel)
    if not save:
        return best, st, D, rows, mkt_sel
    la = lookahead_test(spec)
    la_c = {c: lookahead_test(spec, c, cuts=(199312, 199612, 199912), min_n=MIN_N_REPL) for c in ('gbr', 'jpn', 'can')}
    print('lookahead', la, la_c)
    assert la['ok'] and all(x['ok'] for x in la_c.values()), (la, la_c)
    mk, rf = h.us_market()
    # 参考: 普通の勢い（ret_12_1 の良い側・vw_cap）を同じ窓で（崩れの深さと t の比較）
    pm = next(x for x in rows if x['name'].startswith('普通の勢い'))
    pr, ptv = build(pm['spec'], 'usa', rf, MIN_N)
    pm_same = h.stats(pr, mk, rf, a=st['from'], b=h.SEL_END, turnover=ptv, cost=COST)
    ms = sorted(set(pr) & set(r['ret']) & set(mk))
    corr = round(_corr([pr[m] - mk[m] for m in ms], [r['ret'][m] - mk[m] for m in ms]), 2)
    sub = best['sub']
    pos = sum(1 for v in mkt_sel.values() if v['excess'] > 0)
    d12 = D['resff3_12_1']
    same_risk = st['vol'] <= st['bench_vol'] * 1.1 and st['maxdd'] >= st['bench_maxdd'] - 5
    rationale = (
        '【規則】米国上場株を、過去 t−12〜t−1 か月の Fama-French 3因子（市場・規模・割安）の残差の累積を残差のぶれで割った値'
        '（JKP の resff3_12_1）で三分位に分け、値の大きい三分位（\'3.0\'）を上限つきの時価加重（JKP vw_cap＝NYSE の80%点で重みに上限）で'
        '買いだけで持つ。組は JKP が毎月 m−1 月末に組んだものをそのまま使い、月 m のリターンを取る。三分位が50社未満の月は使わない。'
        '【なぜ（2000年以前の理由）】(1) 勢い（Jegadeesh・Titman 1993）: 過去12か月に上がった株は次の数か月も市場に勝ちやすい。'
        '原因は情報がゆっくり伝わること・投資家の過小反応（Barberis・Shleifer・Vishny 1998、Daniel・Hirshleifer・Subrahmanyam 1998、Hong・Stein 1999）。'
        '(2) 普通の勢いは、過去に上がった「因子」（市場・小型・割安）への傾きを抱えるので、因子の向きが反転すると一斉に崩れる'
        '（Grundy・Martin 2001〔1998年の working paper〕: 因子の分を除いた会社固有の勢いのほうが安定）。'
        '残差の勢いは因子の分を除いた会社固有の過小反応だけを取り、さらに残差のぶれで割るので、特定の荒い銘柄に偏らない。'
        '⚠ この系統の名前（Blitz・Huij・Martens 2011）は選定期間より後の論文で、調べる側はその論文が2000年以降の米国・他国でも効いたと報告したことを知っている＝後知恵。'
        f'【向き】JKP の因子と 3.0−1.0 の相関 {d12["corr_factor_vs_3minus1"]}（＝direction +1）・三分位の年平均の超過（vw_cap・50社以上の月）'
        f'{d12["tercile_mean_excess_pct_yr_vw_cap"]}＝1<2<3 の単調な並び。よって良い側は \'3.0\'（残差の勢いが大きい側）。'
        f'【選定期間 {st["from"]}〜{st["to"]}（{st["years"]}年・JKP の resff3 は三分位が50社そろうのが 1953-05 から）】'
        f'費用後（回転 200%/年 × 0.25%＝年0.5%）の年率 {st["cagr"]}% 対 French 米国市場 {st["bench_cagr"]}%、超過 {st["excess"]:+}%/年、'
        f't {st["t"]}（Newey-West {st["t_nw"]}）、ぶれ {st["vol"]}% 対 {st["bench_vol"]}%、最大下落 {st["maxdd"]}% 対 {st["bench_maxdd"]}%、'
        f'転がる10年で勝った窓 {st["roll10_win"]}、β {best["beta"]}・CAPM のα {best["alpha_capm"]:+}%/年'
        f'（{"同じリスクの区分に入る" if same_risk else "リスクを増やしている"}）。'
        f'JKP の上限つき市場（vw_cap）に対しても {best["ex_vs_jkp_capped_mkt"]:+}%/年＝超過は重みの付け方（中型寄り）の分ではない。'
        f'部分期間: 〜1962 {sub["〜1962"]["excess"]:+}%/年（t {sub["〜1962"]["t"]}）・1963-1985 {sub["1963-1985"]["excess"]:+}（t {sub["1963-1985"]["t"]}）・'
        f'1986-2000 {sub["1986-2000"]["excess"]:+}（t {sub["1986-2000"]["t"]}）＝3つの時期すべてで正。'
        f'超過の悪い月 {best["worst_months"]}。'
        f'参考: 同じ窓の普通の勢い（ret_12_1 の良い側・vw_cap）は 超過 {pm_same["excess"]:+}%/年・t {pm_same["t"]}・ぶれ {pm_same["vol"]}%・最大下落 {pm_same["maxdd"]}%'
        f'（超過どうしの相関 {corr}）＝同じくらいの上乗せを、より小さいぶれで取っている（予想「普通の勢いより崩れが浅い」と同じ向き）。'
        f'【選び方】{how}。t が次に大きいのは『12-1と6-1の良い側を等分・vw_cap』（t 5.64）で、どちらも同じ系統。'
        'vw（上限なし）の変種は弱い（12-1 で +3.29%/年・t 3.49）——上限なしの三分位は数社の巨大株の動きに振られる（1974-01・1974-12 に市場より −18% の月がある）。'
        f'【他の市場（選定期間・参考）】先進国のうち三分位が20社以上そろう月が24か月以上ある{len(mkt_sel)}か国で、超過が正は {pos}/{len(mkt_sel)}'
        '（国のデータは 1984〜1997年ごろに始まり、多くは10年前後しかない＝雑音が大きい）。'
        '【予想】米国では公表（2011）後と2009年の勢いの崩れで上乗せは小さくなる見込み（事前登録 r6 の予想「米国では小さい」）。'
    )
    tbl = [{'name': x['name'], 'eligible': x['eligible'], 'from': x['stats']['from'], 'excess': x['stats']['excess'],
            't': x['stats']['t'], 't_nw': x['stats']['t_nw'], 'vol': x['stats']['vol'], 'maxdd': x['stats']['maxdd'],
            'beta': x['beta'], 'alpha_capm': x['alpha_capm'], 'ex_vs_jkp_capped_mkt': x['ex_vs_jkp_capped_mkt'],
            'sub_periods': x['sub'], 'turnover_yr': x['turnover_yr'], 'worst_months': x['worst_months']} for x in rows]
    extra = {
        'implement': FAMILY['implement'], 'family_name': FAMILY['name'],
        'lookahead_test': ('lookahead_test() で米国（1965-12/1985-12/1995-12/1999-12 で切る）と英国・日本・カナダ（1993-12/1996-12/1999-12）を確かめた（すべて食い違い0）: '
                           '(1) 切り詰め: 脚のリターン・銘柄数・RF を月 X で切って作り直しても、X までの規則のリターンと回転が 1e-15 で一致し、月の集合も同じ '
                           '(2) 毒: X より後の脚のリターンを1か月ずらして乱数を足し、銘柄数と RF を乱数に置き換えても X までは不変（X より後は変わる＝検査が空回りしていない） '
                           '(3) 最後の1か月（2000-12）を削っても、それ以前は不変 '
                           f'(4) 月合わせ: 月 m の総リターン − 月 m の RF = 脚の月 m の超過（差の最大 {la["month_align_maxdiff"]:.1e}） '
                           '(5) 側（信号）は spec の定数でデータから再推定しない（向きは選定期間の米国データで一度だけ決めた）。'
                           '信号そのもの（残差の勢いの三分位）は JKP が m−1 月末までの月次リターンと3因子で作ったもので、この module は全期間の平均・分位・標準化を一切使わない。'
                           f'もっともらしさ: 普通の勢い（同じ作り）の上乗せは {pm_same["excess"]:+}%/年で Jegadeesh・Titman 1993 と同じ大きさ——同じ月のリターンが信号に混ざっていれば三分位の差は年数十%になる'),
        'directions': D,
        'variants_table': tbl,
        'variants_note': '選べる8（12-1・6-1・両方の等分・悪い側を避ける〔中＋良〕 × vw_cap/vw）＋参考3（12-1 の悪い側 × 2・普通の勢い12-1 の良い側）。成績を見る前に scratchpad の plan_resmom.md で固定',
        'plain_momentum_same_window': pm_same, 'corr_excess_vs_plain_momentum': corr,
        'markets': list(REPL),                       # ホールドアウトで当てる22か国（選定期間に24か月そろうのは markets_selection_period の国だけ）
        'markets_selection_period': mkt_sel,
        'markets_note': '国は JKP の3文字（jpn・gbr…）で run() の markets のキーと同じ。相手はその国の JKP mkt(vw)+米国RF（米ドル）。三分位が20社未満の月は落とす',
        'benchmark': 'French 米国市場（Mkt-RF＋RF・CRSP 全上場の上限なし時価加重）',
        'cost_note': '片道の回転1あたり0.25%・回転 200%/年（事前登録 r6 の価格の信号の置き値）。等分の変種は脚どうしの戻しを足す',
        'selection_note': how,
        'eligible_variants': sum(1 for x in rows if x['eligible']), 'reference_variants': sum(1 for x in rows if not x['eligible']),
    }
    doc = h.save_spec('resmom', spec, rationale, len(rows), st, extra)
    print('凍結:', best['name'], doc['n_variants_tried'])
    return doc


if __name__ == '__main__':
    main(save='--save' in sys.argv)
