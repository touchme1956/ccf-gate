#!/usr/bin/env python3
"""night/edge/fam_lt_reversal.py — 系統 lt_reversal（第6回）: 長期の負け組（過去5年の負け側）の買いだけ vs 米国市場

事前登録 out/edge_prereg_r6.json の round6_families.lt_reversal（線・費用・相手・期間は out/edge_prereg.json と同じ）。
  ・特徴: JKP ret_60_12 ＝ 月 t−60〜t−12 の累積リターン（直近12か月を除いた過去5年）。De Bondt & Thaler 1985。
  ・良い側 = 予言の向き。JKP の因子は direction ×（'3.0' − '1.0'）。選定期間（1931-01〜2000-12）の米国で
    因子と '3.0'−'1.0' の相関は −1.000（vw_cap・vw とも）＝ direction(ret_60_12) = −1 ＝ 良い側は '1.0'（過去5年の負け組）。
    実物の並びも同じ向き（選定期間の月平均の超過・年率: vw_cap '1.0' 12.3% ＞ '2.0' 10.3% ＞ '3.0' 9.0%）。
  ・JKP の三分位の 'ret' は米ドルの**超過リターン**（米国の短期金利を引いたもの）→ 総リターン = ret + French RF
    （確かめ: 1926-07〜2000-12 で JKP mkt(vw)+RF − French 市場 = 平均 +0.018%/年）
  ・月 m の組は JKP が m−1 月末に組んだ三分位。銘柄数 n も組んだ時点の数。米国は三分位の n ≥ 50 の月だけ、再現の国は n ≥ 20
  ・費用: 片道の回転100%につき 0.25%。回転は 200%/年（事前登録 r6 の価格の信号の置き値）＋ 二つの三分位を等分に持つ変種の毎月の戻し
  ・他の市場: JKP の先進国22か国の同じ特徴・同じ側・同じ重み。国の相手は JKP の国の mkt（vw＝上限なしの時価加重・米ドル超過）＋ French RF

使い方: python3 night/edge/fam_lt_reversal.py          → 変種の表（選定の段・2000-12 まで）
        python3 night/edge/fam_lt_reversal.py --save   → 選んで凍結（out/edge/spec_lt_reversal.json）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h
import csv, io, math, statistics as S, zipfile
from concurrent.futures import ThreadPoolExecutor

FAMILY = {
    'key': 'lt_reversal',
    'name': '長期の負け組の買いだけ（JKP 過去5年〔直近1年を除く〕のリターンが低い三分位）',
    'implement': ('楽天証券の米国株（NISA 成長投資枠で買える・レバレッジではない）で、米国上場株を「13〜60か月前の累積リターン」で並べ、'
                  'いちばん低い3分の1（過去5年の負け組・境目は非超小型株で引く）を時価加重（1社の重みに上限＝JKP の vw_cap と同じく巨大株を抑える）で持ち、'
                  '毎月〜四半期に入れ替える（回転は 200%/年と置いた）。負け組の三分位は超小型株を多く含み数百〜2千社になるので、'
                  '個人は時価総額の大きい負け組から数十社に絞る近似になる。長期の負け組そのものを選ぶ ETF は無い——'
                  '近いのは割安株の ETF（楽天で買える VTV・IWD・RPV〔S&P500 の純粋な割安〕）だが、割安の物差し（簿価・利益÷株価）で選ぶので'
                  'この規則の成績の近似でしかない。個別株の組なので NISA の成長投資枠で持てる（ただし回転が大きく、枠の再利用は翌年）'),
}

CHAR = 'ret_60_12'
COST = 0.0025                     # 片道の回転100%につき（事前登録: 個別株の組）
TURN_ANN = 2.0                    # 片道の回転（年）。事前登録 r6 の価格の信号の置き値
MIN_N = 50                        # 米国: 三分位の銘柄数がこれ未満の月は使わない
MIN_N_REPL = 20                   # 他の国
REPL = ['jpn', 'gbr', 'deu', 'fra', 'can', 'aus', 'che', 'swe', 'nld', 'ita', 'esp', 'hkg', 'sgp', 'dnk', 'nor', 'bel',
        'fin', 'aut', 'irl', 'prt', 'nzl', 'isr']          # 事前登録 r6 の先進国22か国
JKP = 'https://jkpfactors-data.s3.amazonaws.com/public/'
LOSER, MID, WINNER = '1.0', '2.0', '3.0'

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
            _MEMO[k] = {s: (p.get(s, {}), n.get(s, {})) for s in (LOSER, MID, WINNER)}
        except Exception:
            _MEMO[k] = {}
    return _MEMO[k]


# ───────────────────────── 規則 ─────────────────────────
def build(spec, region, rf, min_n):
    """spec['sides'] の三分位を等分に持つ（1つなら素通し）→ (総リターン {m}, 片道の回転 {m})
    月 m に持つかどうかは、月 m の組（m−1 月末に組まれたもの）の銘柄数 n だけで決まる。等分の組は毎月戻す。
    データから何も推定しない（側・重み・閾値は spec の定数）"""
    L = legs(region, spec.get('char', CHAR), spec['w'])
    sides = spec['sides']
    if not L or any(s not in L or not L[s][0] for s in sides):
        return {}, {}
    ta = spec.get('turn_ann', TURN_ANN)
    months = sorted(set.intersection(*[set(L[s][0]) for s in sides]))
    ret, tv, prev = {}, {}, None
    tw = {s: 1 / len(sides) for s in sides}
    for m in months:
        if m not in rf or any(L[s][1].get(m, 0) < min_n for s in sides):
            prev = None
            continue
        reb = 0.0 if prev is None else 0.5 * sum(abs(prev.get(s, 0.0) - tw[s]) for s in tw)
        ret[m] = sum(tw[s] * L[s][0][m] for s in sides) + rf[m]
        tv[m] = ta / 12 + reb
        g = {s: tw[s] * (1 + L[s][0][m] + rf[m]) for s in sides}
        tot = sum(g.values())
        prev = {s: v / tot for s, v in g.items()} if tot > 0 else None
    return ret, tv


def run(spec):
    mk, rf = h.us_market()
    ret, tv = build(spec, 'usa', rf, spec.get('min_n', MIN_N))
    out = {'ret': ret, 'bench': mk, 'rf': rf, 'turnover': tv, 'cost': COST, 'markets': {}}
    regions = spec.get('replicate', [])

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
        for c, x in ex.map(one, regions):
            if x:
                out['markets'][c] = x
    return out


# ───────────────────────── 選定（2000-12 まで） ─────────────────────────
def _corr(a, b):
    ma, mb = S.mean(a), S.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def direction():
    """良い側を選定期間の米国データで確かめる: JKP 因子 = direction ×（'3.0'−'1.0'）→ 相関の符号。実物の並び（月平均）も併記"""
    out = {}
    for w in ('vw_cap', 'vw'):
        L = legs('usa', CHAR, w)
        f = h.jkp('usa', CHAR, 'factor', w)
        ms = sorted(set(f) & set(L[LOSER][0]) & set(L[WINNER][0]))
        r = _corr([f[m] for m in ms], [L[WINNER][0][m] - L[LOSER][0][m] for m in ms])
        out[w] = {'corr_factor_vs_3minus1': round(r, 4), 'good_side': WINNER if r > 0 else LOSER, 'months': len(ms),
                  'from': ms[0], 'to': ms[-1],
                  'mean_excess_pct_yr': {s: round(S.mean(L[s][0][m] for m in ms) * 1200, 2) for s in (LOSER, MID, WINNER)}}
    return out


def variants():
    """成績を見る前に決めた変種（6本）→ [(名前, spec, 選べるか)]
    選べるのは系統の定義（事前登録 r6『過去5年の負け側』＝良い側の三分位だけ）どおりの2本。
    『勝ち組を避ける（負け＋中の等分）』と『勝ち組』は向きと形の確認のための参考（数に入れるが選ばない）"""
    V = []
    for w in ('vw_cap', 'vw'):
        V.append((f'負け組の三分位・{w}', {'char': CHAR, 'w': w, 'sides': [LOSER]}, True))
    for w in ('vw_cap', 'vw'):
        V.append((f'勝ち組を避ける（負け＋中を等分）・{w}（参考）', {'char': CHAR, 'w': w, 'sides': [LOSER, MID]}, False))
    for w in ('vw_cap', 'vw'):
        V.append((f'勝ち組の三分位・{w}（参考・向きの確認）', {'char': CHAR, 'w': w, 'sides': [WINNER]}, False))
    return V


def beta(ret, mk, rf, a=None, b=None):
    ms = [m for m in sorted(set(ret) & set(mk)) if (a is None or m >= a) and (b is None or m <= b)]
    x = [mk[m] - rf[m] for m in ms]
    y = [ret[m] - rf[m] for m in ms]
    mx, my = S.mean(x), S.mean(y)
    bt = sum((p - mx) * (q - my) for p, q in zip(x, y)) / sum((p - mx) ** 2 for p in x)
    al = (my - bt * mx) * 1200
    return round(bt, 2), round(al, 2)


def ff3(ret, rf, a=None, b=None, turnover=None, cost=0.0):
    """Fama-French 3因子（French の月次・guard 済み）で費用後の超過を回帰 → α（%/年）・t・β（市場・SMB・HML）。参考（選定に使わない）"""
    d = h.french('F-F_Research_Data_Factors')
    t = next(iter(d))
    F = {c: {m: v / 100 for m, v in d[t][c].items() if m > 9999} for c in ('Mkt-RF', 'SMB', 'HML')}
    ms = [m for m in sorted(ret) if m in rf and all(m in F[c] for c in F) and (a is None or m >= a) and (b is None or m <= b)]
    y = [ret[m] - (turnover.get(m, 0.0) * cost if turnover else 0.0) - rf[m] for m in ms]
    X = [[1.0, F['Mkt-RF'][m], F['SMB'][m], F['HML'][m]] for m in ms]
    k = 4
    XtX = [[sum(r[i] * r[j] for r in X) for j in range(k)] for i in range(k)]
    Xty = [sum(r[i] * v for r, v in zip(X, y)) for i in range(k)]
    inv = _inv(XtX)
    bh = [sum(inv[i][j] * Xty[j] for j in range(k)) for i in range(k)]
    res = [v - sum(bh[i] * r[i] for i in range(k)) for r, v in zip(X, y)]
    s2 = sum(e * e for e in res) / (len(ms) - k)
    se = [math.sqrt(s2 * inv[i][i]) for i in range(k)]
    return {'alpha_pct_yr': round(bh[0] * 1200, 2), 't_alpha': round(bh[0] / se[0], 2),
            'b_mkt': round(bh[1], 2), 'b_smb': round(bh[2], 2), 'b_hml': round(bh[3], 2), 't_hml': round(bh[3] / se[3], 2),
            'from': ms[0], 'to': ms[-1]}


def _inv(A):
    n = len(A)
    M = [list(r) + [1.0 if i == j else 0.0 for j in range(n)] for i, r in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        pv = M[c][c]
        M[c] = [v / pv for v in M[c]]
        for r in range(n):
            if r != c:
                f = M[r][c]
                M[r] = [a - f * b for a, b in zip(M[r], M[c])]
    return [r[n:] for r in M]


def ex_january(ret, mk, rf, tv, a=None, b=None):
    """1月を除いた月だけの費用後の超過（算術・%/年）と t。De Bondt-Thaler の負け組の上乗せは1月に偏るという先行研究の確認（参考）"""
    out = {}
    for lab, keep in (('1月だけ', lambda m: m % 100 == 1), ('1月以外', lambda m: m % 100 != 1)):
        ms = [m for m in sorted(set(ret) & set(mk)) if keep(m) and (a is None or m >= a) and (b is None or m <= b)]
        ex = [ret[m] - tv.get(m, 0.0) * COST - mk[m] for m in ms]
        mu, sd = S.mean(ex), S.stdev(ex)
        out[lab] = {'mean_ex_pct_per_month': round(mu * 100, 3), 'contrib_pct_yr': round(mu * 100 * (1 if lab == '1月だけ' else 11), 2),
                    't': round(mu / (sd / math.sqrt(len(ms))), 2), 'months': len(ms)}
    return out


def select():
    assert h.PHASE == 'select'
    mk, rf = h.us_market()
    capm = {m: v + rf[m] for m, v in h.jkp('usa', 'mkt', 'factor', 'vw_cap').items() if m in rf}
    rows = []
    for name, sp, ok in variants():
        r, tv = build(sp, 'usa', rf, MIN_N)
        st = h.stats(r, mk, rf, b=h.SEL_END, turnover=tv, cost=COST)
        sub = {}
        for lab, a, b in (('1931-1962', None, 196212), ('1963-2000', 196301, h.SEL_END), ('1981-2000', 198101, h.SEL_END)):
            s2 = h.stats(r, mk, rf, a=a, b=b, turnover=tv, cost=COST)
            sub[lab] = {'excess': s2['excess'], 't': s2['t']} if s2 else None
        st_cap = h.stats(r, capm, rf, b=h.SEL_END, turnover=tv, cost=COST)
        bt, al = beta(r, mk, rf, b=h.SEL_END)
        rows.append({'name': name, 'eligible': ok, 'spec': sp, 'stats': st, 'sub': sub, 'beta': bt, 'alpha_capm': al,
                     'ex_vs_jkp_capped_mkt': st_cap['excess'] if st_cap else None,
                     'turnover_yr': round(sum(tv.values()) / len(tv) * 12, 3) if tv else None})
        print(f"{'○' if ok else '参'} {name:34} {st['from']}〜 ex{st['excess']:6} t{st['t']:6} (NW{st['t_nw']}) "
              f"vol{st['vol']}/{st['bench_vol']} dd{st['maxdd']}/{st['bench_maxdd']} β{bt} α{al} 回転{rows[-1]['turnover_yr']} "
              f"対capmkt {rows[-1]['ex_vs_jkp_capped_mkt']} 10年窓{st['roll10_win']}  部分 {sub}")
    return rows


LOOKAHEAD = ('scratchpad の lookahead_lt_reversal.py で確かめた（結果は下の lookahead_result）: '
             '(1) 切り口: EDGE_SEL_END=199012 と 200012 で別プロセスに走らせ、1990-12 までの規則・相手・短期金利・回転と、'
             '他の市場（22か国のうち 1990-12 以前にデータのある国）の規則・相手・回転が 1e-12 で一致するか（凍結した規則で）。'
             '(2) 未来の毒: 1985-12 より後の脚のリターン・銘柄数・米国市場・短期金利・国の市場をすべて乱数に置き換えても、'
             '1985-12 以前の規則のリターンと回転が1か月も変わらないか（後ろの月は変わる＝毒が効いていることも確かめる）。'
             '(3) 1か月ずらし: 1985-12 より後の脚の値を1か月後ろへずらして壊しても、それより前は不変か。'
             '(4) 同じ月の先読み（コードを読む検査）: 月 m に持つかどうかは月 m の行の銘柄数 n だけで決め、n と三分位は JKP が m−1 月末に'
             'm−60〜m−12 月のリターンで組んだもの。月 m の総リターン = JKP の月 m の超過 + 月 m の RF（差の最大も測る）。'
             'この module は全期間の平均・分位・標準化を一切使わず、側は spec の定数（データから再推定しない）')


def main(save=False, la_result=None):
    D = direction()
    print('向き:', D)
    rows = select()
    elig = [r for r in rows if r['eligible'] and r['stats'] and r['stats']['excess'] >= 1.0]
    if elig:
        best = max(elig, key=lambda r: r['stats']['t'])
        how = '事前登録どおり（系統の定義どおりの変種のうち、選定期間の費用後の超過 +1%/年以上の中で t が最大）'
    else:
        cand = [r for r in rows if r['eligible']]
        best = max(cand, key=lambda r: r['stats']['t'])
        how = ('どの変種も +1%/年 に届かなかった。系統の定義（事前登録 r6『過去5年の負け側』）どおりの変種の中で t が最大のものを選んだ')
    spec = dict(best['spec'])
    spec.update({'min_n': MIN_N, 'min_n_repl': MIN_N_REPL, 'replicate': REPL, 'turn_ann': TURN_ANN,
                 'side_note': "'1.0' = ret_60_12（月 t−60〜t−12 の累積リターン）が低い＝過去5年の負け組の三分位。JKP direction = −1"})
    r = run(spec)
    st = h.stats(r['ret'], r['bench'], r['rf'], b=h.SEL_END, turnover=r['turnover'], cost=r['cost'])
    mkt_sel = {}
    for c, x in r['markets'].items():
        s2 = h.stats(x['ret'], x['bench'], x['rf'], b=h.SEL_END, turnover=x['turnover'], cost=x['cost'])
        if s2:
            mkt_sel[c] = {'from': s2['from'], 'years': s2['years'], 'excess': s2['excess'], 't': s2['t']}
    f3 = ff3(r['ret'], r['rf'], b=h.SEL_END, turnover=r['turnover'], cost=r['cost'])
    f3_63 = ff3(r['ret'], r['rf'], a=196301, b=h.SEL_END, turnover=r['turnover'], cost=r['cost'])
    jan = ex_january(r['ret'], r['bench'], r['rf'], r['turnover'], b=h.SEL_END)
    tbl = [{'name': x['name'], 'eligible': x['eligible'], 'from': x['stats']['from'], 'excess': x['stats']['excess'],
            't': x['stats']['t'], 't_nw': x['stats']['t_nw'], 'vol': x['stats']['vol'], 'maxdd': x['stats']['maxdd'],
            'beta': x['beta'], 'alpha_capm': x['alpha_capm'], 'ex_vs_jkp_capped_mkt': x['ex_vs_jkp_capped_mkt'],
            'sub_periods': x['sub'], 'turnover_yr': x['turnover_yr']} for x in rows]
    print('選んだ:', best['name'], how)
    print('選定期間:', st)
    print('FF3（1931〜）:', f3)
    print('FF3（1963〜）:', f3_63)
    print('1月:', jan)
    print('他の市場（選定期間・参考）:', mkt_sel)
    if not save:
        return best, st
    sub = best['sub']
    other_w = next(x for x in rows if x['eligible'] and x is not best)
    avoid = next(x for x in rows if x['spec']['sides'] == [LOSER, MID] and x['spec']['w'] == best['spec']['w'])
    win = next(x for x in rows if x['spec']['sides'] == [WINNER] and x['spec']['w'] == best['spec']['w'])
    pos = sum(1 for v in mkt_sel.values() if v['excess'] > 0)
    rationale = (
        '【規則】米国上場株を JKP の ret_60_12（月 t−60〜t−12 の累積リターン＝直近1年を除く過去5年）で三分位に分け'
        f"（境目は非超小型株で引く）、いちばん低い三分位（過去5年の負け組・JKP '1.0'）を {best['spec']['w']}"
        f"{'（上限つきの時価加重＝NYSE の80%点で1社の重みに上限）' if best['spec']['w'] == 'vw_cap' else '（上限なしの時価加重）'}"
        'で買いだけで持つ。組は JKP が毎月 m−1 月末に組んだものをそのまま使い、月 m のリターンを取る。'
        '【なぜ】(1) 行き過ぎの反動（De Bondt & Thaler 1985・1987）: 投資家は数年続いた悪い知らせに過剰に反応し、負け組を安く売り込みすぎる——'
        '3〜5年の負け組はその後の3〜5年に勝ち組を上回った。(2) 長期の負け組は割安（簿価・利益に比べて株価が低い）になりやすく、'
        'Fama & French 1996 はこの効果の大半を割安（HML）と小型（SMB）で説明できると示した＝割安の上乗せと同じ源泉（リスクか、誤った外挿か：Lakonishok・Shleifer・Vishny 1994）。'
        '(3) 直近1年を除くのは短期の勢い（Jegadeesh & Titman 1993）と逆向きの力を混ぜないため（JKP の定義どおり）。'
        f"【選定期間 {st['from']}〜{st['to']}（{st['years']}年）】費用後（回転 200%/年×0.25%＝年0.5%を引いた後）の年率 {st['cagr']}% 対 French 米国市場 {st['bench_cagr']}%、"
        f"超過 {st['excess']:+}%/年、t {st['t']}（Newey-West {st['t_nw']}）、ぶれ {st['vol']}% 対 {st['bench_vol']}%、"
        f"最大下落 {st['maxdd']}% 対 {st['bench_maxdd']}%、転がる10年で勝った窓 {st['roll10_win']}。"
        f"市場に対するβ {best['beta']}・CAPM のα {best['alpha_capm']:+}%/年。"
        f"部分期間: 1931-1962 {sub['1931-1962']['excess']:+}%/年（t {sub['1931-1962']['t']}）・1963-2000 {sub['1963-2000']['excess']:+}%/年（t {sub['1963-2000']['t']}）・"
        f"1981-2000 {sub['1981-2000']['excess']:+}%/年（t {sub['1981-2000']['t']}）。"
        f"Fama-French 3因子の α は {f3['alpha_pct_yr']:+}%/年（t {f3['t_alpha']}・HML の係数 {f3['b_hml']}・SMB {f3['b_smb']}）＝上乗せの多くは割安と小型への傾きで説明される"
        f"（1963〜: α {f3_63['alpha_pct_yr']:+}%/年・t {f3_63['t_alpha']}・HML {f3_63['b_hml']}）。"
        f"1月の偏り: 月平均の超過は1月 {jan['1月だけ']['mean_ex_pct_per_month']}%（t {jan['1月だけ']['t']}）・1月以外 {jan['1月以外']['mean_ex_pct_per_month']}%（t {jan['1月以外']['t']}）。"
        f"JKP の上限つき市場（vw_cap）に対しては {best['ex_vs_jkp_capped_mkt']:+}%/年。"
        f"参考: もう一方の重み（{other_w['spec']['w']}）の負け組は {other_w['stats']['excess']:+}%/年（t {other_w['stats']['t']}）、"
        f"勝ち組を避ける（負け＋中の等分・{avoid['spec']['w']}）は {avoid['stats']['excess']:+}%/年（t {avoid['stats']['t']}）、"
        f"勝ち組の三分位（{win['spec']['w']}）は {win['stats']['excess']:+}%/年（t {win['stats']['t']}）＝負け組 ＞ 勝ち組 の向きは選定期間で成り立つ。"
        f"【選び方】{how}。"
        f"【他の市場（選定期間・参考・1986年ごろから）】先進国22か国のうち選定期間の超過が正は {pos}/{len(mkt_sel)}（国のデータは 1980年代後半に始まり15年前後しかない）。"
        '【予想】事前登録 r6 の予想どおり、割安と同じ源泉なので 2001年以降の米国（大型・グロース優位）では負ける見込みが高い。'
        '回転の置き値 200%/年は、5年の窓がゆっくり動く ret_60_12 には重めの可能性がある（実際の回転は公表されていない）。'
    )
    extra = {'implement': FAMILY['implement'], 'family_name': FAMILY['name'], 'lookahead_test': LOOKAHEAD,
             'lookahead_result': la_result, 'direction': D, 'variants_table': tbl, 'markets': list(r['markets']),
             'markets_selection_period': mkt_sel, 'selection_note': how, 'ff3_selection': {'1931-2000': f3, '1963-2000': f3_63},
             'january': jan,
             'benchmark': 'French 米国市場（Mkt-RF＋RF・CRSP 全上場の上限なし時価加重）。他の国は JKP の国の mkt（vw＝上限なし・米ドル超過）＋French RF',
             'cost_note': '片道の回転100%につき0.25%。回転は 200%/年（事前登録 r6 の価格の信号の置き値）＋等分の組の戻し（選んだ規則は1つの三分位なので戻し無し）',
             'eligible_variants': sum(1 for x in rows if x['eligible']), 'reference_variants': sum(1 for x in rows if not x['eligible'])}
    doc = h.save_spec('lt_reversal', spec, rationale, len(rows), st, extra)
    print('凍結:', best['name'])
    return doc


if __name__ == '__main__':
    main(save='--save' in sys.argv)
