#!/usr/bin/env python3
"""night/edge/fam_old_firms.py — 系統 old_firms: 上場の古い会社（JKP の age の古い側の三分位）の買いだけ vs 米国市場

事前登録 out/edge_prereg_r5.json の round5_families.old_firms（線・費用・相手・期間は out/edge_prereg.json と同じ）。
  ・古い側 = JKP age の三分位 '3.0'（age が大きい側）。確かめ方: 1926-02 の行で、1926-01 に新しく載った8社が '1.0'、
    1925-12 から居る497社が '3.0' に入っている＝'3.0' が古い。JKP の direction(age) は −1（因子は『若い−古い』の向き）
  ・JKP の三分位の 'ret' は米ドルの**超過リターン**（米国の短期金利を引いたもの）→ 総リターン = ret + French RF
    （確かめ: 1963-07〜2000-12 の月平均 '3.0' vw 0.521% / French Mkt-RF 0.529% / RF 0.511%＝超過の水準）
  ・月 m の組は JKP が m−1 月末に組んだ三分位（age はその時点の上場からの月数）。銘柄数 n も組んだ時点の数
  ・費用: 片道の回転100%につき 0.25%。回転は 50%/年（事前登録の既定）＋ 二つの三分位を等分に持つ変種の戻し
  ・他の市場: JKP の先進国22か国の同じ側。国の相手は JKP の国の mkt（vw＝上限なしの時価加重・米ドル超過）＋ French RF

使い方: python3 night/edge/fam_old_firms.py          → 変種の表（選定の段・2000-12 まで）
        python3 night/edge/fam_old_firms.py --save   → 選んで凍結（out/edge/spec_old_firms.json）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h
import csv, io, math, statistics as S, zipfile
from concurrent.futures import ThreadPoolExecutor

FAMILY = {
    'key': 'old_firms',
    'name': '上場の古い会社の買いだけ（JKP 年齢の古い三分位）',
    'implement': ('楽天証券の米国株（NISA 成長投資枠で買える・レバレッジではない）で、米国上場株のうち「上場（CRSP/Compustat に載って）からの年数」'
                  'が長い上位3分の1の会社を時価加重（上限つき）で持ち、年に1〜2回入れ替える。境目の年数は時代で動く（米国の非超小型株の上位1/3）。'
                  '銘柄数は数百になり個人には重いので、実際には時価総額の大きい古い会社から数十社に絞る近似になる。'
                  '古さそのものを選ぶETFは無い。近い ETF（DIA・NOBL〔配当を25年増やした S&P500 の会社〕・VIG）は古い会社に偏るが、'
                  '配当や選定委員会など別の条件が混ざる＝この規則の成績の近似でしかない'),
}

COST = 0.0025                     # 片道の回転100%につき（事前登録: 個別株の組）
TURN_ANN = 0.5                    # 片道の回転（年）。事前登録 r5 の既定（年齢はゆっくり動く信号）
MIN_N = 50                        # 米国: 三分位の銘柄数がこれ未満の月は使わない
MIN_N_REPL = 20                   # 他の国
REPL = ['jpn', 'gbr', 'deu', 'fra', 'can', 'aus', 'che', 'swe', 'nld', 'ita', 'esp', 'hkg', 'sgp', 'dnk', 'nor', 'bel',
        'fin', 'aut', 'irl', 'prt', 'nzl', 'isr']          # jkpmulti と同じ先進国22か国
JKP = 'https://jkpfactors-data.s3.amazonaws.com/public/'
OLD, MID, YOUNG = '3.0', '2.0', '1.0'

_MEMO = {}


# ───────────────────────── 読み込み ─────────────────────────
def _counts(region, w):
    """三分位の銘柄数 n（h.jkp は返さないので、同じキャッシュを h.cached で読み h.guard を通す）"""
    url = f'{JKP}portfolios/%5B{region}%5D_%5Bage%5D_%5Bmonthly%5D_%5B{w}%5D.zip'
    z = zipfile.ZipFile(io.BytesIO(h.cached(f'jkp_portfolio_{region}_age_{w}.zip', url)))
    out = {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        try:
            out.setdefault(x['pf'], {})[int(x['date'][:4]) * 100 + int(x['date'][5:7])] = int(float(x['n']))
        except (TypeError, ValueError):
            continue
    return {k: h.guard(v) for k, v in out.items()}


def legs(region, w):
    """→ {三分位: (超過リターン {m}, 銘柄数 {m})}。取れなければ {}"""
    k = (region, w)
    if k not in _MEMO:
        try:
            p = h.jkp(region, 'age', 'portfolio', w)
            n = _counts(region, w)
            _MEMO[k] = {s: (p.get(s, {}), n.get(s, {})) for s in (YOUNG, MID, OLD)}
        except Exception:
            _MEMO[k] = {}
    return _MEMO[k]


# ───────────────────────── 規則 ─────────────────────────
def build(spec, region, rf, min_n):
    """spec['sides'] の三分位を等分に持つ（1つなら素通し）→ (総リターン {m}, 片道の回転 {m})
    月 m に持つかどうかは、月 m の組（m−1 月末に組まれたもの）の銘柄数 n だけで決まる。等分の組は毎月戻す"""
    L = legs(region, spec['w'])
    sides = spec['sides']
    if not L or any(s not in L for s in sides):
        return {}, {}
    months = sorted(set.intersection(*[set(L[s][0]) for s in sides]))
    ret, tv, prev = {}, {}, None
    tw = {s: 1 / len(sides) for s in sides}
    for m in months:
        if m not in rf or any(L[s][1].get(m, 0) < min_n for s in sides):
            prev = None
            continue
        reb = 0.0 if prev is None else 0.5 * sum(abs(prev.get(s, 0.0) - tw[s]) for s in tw)
        ret[m] = sum(tw[s] * L[s][0][m] for s in sides) + rf[m]
        tv[m] = TURN_ANN / 12 + reb
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
        return c, ({'ret': r, 'bench': bench, 'rf': rf, 'turnover': t, 'cost': COST} if len(r) >= 24 and bench else None)
    with ThreadPoolExecutor(8) as ex:
        for c, x in ex.map(one, regions):
            if x:
                out['markets'][c] = x
    return out


# ───────────────────────── 選定（2000-12 まで） ─────────────────────────
def variants():
    """成績を見る前に決めた変種（scratchpad の plan_old_firms.md どおり）→ [(名前, spec, 選べるか)]"""
    V = []
    for w in ('vw_cap', 'vw'):
        V.append((f'古い三分位・{w}', {'w': w, 'sides': [OLD]}, True))
    for w in ('vw_cap', 'vw'):
        V.append((f'若い三分位を避ける（中＋古を等分）・{w}', {'w': w, 'sides': [MID, OLD]}, True))
    for w in ('vw_cap', 'vw'):
        V.append((f'若い三分位・{w}（参考・向きの確認）', {'w': w, 'sides': [YOUNG]}, False))
    return V


def beta(ret, mk, rf, a=None, b=None):
    ms = [m for m in sorted(set(ret) & set(mk)) if (a is None or m >= a) and (b is None or m <= b)]
    x = [mk[m] - rf[m] for m in ms]
    y = [ret[m] - rf[m] for m in ms]
    mx, my = S.mean(x), S.mean(y)
    bt = sum((p - mx) * (q - my) for p, q in zip(x, y)) / sum((p - mx) ** 2 for p in x)
    al = (my - bt * mx) * 1200
    return round(bt, 2), round(al, 2)


def select():
    assert h.PHASE == 'select'
    mk, rf = h.us_market()
    capm = {m: v + rf[m] for m, v in h.jkp('usa', 'mkt', 'factor', 'vw_cap').items() if m in rf}
    rows = []
    for name, sp, ok in variants():
        r, tv = build(sp, 'usa', rf, MIN_N)
        st = h.stats(r, mk, rf, b=h.SEL_END, turnover=tv, cost=COST)
        sub = {}
        for lab, a, b in (('1926-1962', None, 196212), ('1963-2000', 196301, h.SEL_END), ('1973-2000', 197301, h.SEL_END)):
            s2 = h.stats(r, mk, rf, a=a, b=b, turnover=tv, cost=COST)
            sub[lab] = {'excess': s2['excess'], 't': s2['t']} if s2 else None
        st_cap = h.stats(r, capm, rf, b=h.SEL_END, turnover=tv, cost=COST)
        bt, al = beta(r, mk, rf, b=h.SEL_END)
        rows.append({'name': name, 'eligible': ok, 'spec': sp, 'stats': st, 'sub': sub, 'beta': bt, 'alpha_capm': al,
                     'ex_vs_jkp_capped_mkt': st_cap['excess'] if st_cap else None,
                     'turnover_yr': round(sum(tv.values()) / len(tv) * 12, 3) if tv else None})
        print(f"{'○' if ok else '参'} {name:32} {st['from']}〜 ex{st['excess']:6} t{st['t']:6} (NW{st['t_nw']}) "
              f"vol{st['vol']}/{st['bench_vol']} dd{st['maxdd']}/{st['bench_maxdd']} β{bt} α{al} 回転{rows[-1]['turnover_yr']} "
              f"対capmkt {rows[-1]['ex_vs_jkp_capped_mkt']} 10年窓{st['roll10_win']}  部分 {sub}")
    return rows


LOOKAHEAD = ('scratchpad の lookahead_old_firms.py で4通り確かめた（すべて食い違い0）: '
             '(1) 切り口: EDGE_SEL_END=199012 と 200012 で別プロセスに走らせ、1990-12 までの規則・相手・短期金利・回転（774か月）と'
             '他の市場（jpn/gbr/can/aus/deu/fra の規則・相手・回転 60〜106か月）が 1e-12 で一致（古い三分位 vw_cap・vw、中＋古の等分 vw_cap の3つ）。'
             '(2) 未来の毒: 1985-12 より後の脚のリターン・銘柄数・米国市場・短期金利・国の市場をすべて乱数に置き換えても、1985-12 以前の規則のリターンと回転が'
             '1か月も変わらない（714か月・後の180か月は変わる＝毒は効いている）。'
             '(3) 脚の最後の1か月（2000-12）を削っても、それ以前の893か月のリターンと回転が変わらない。'
             '(4) 同じ月の先読み: 月 m に持つかどうかは月 m の行の銘柄数 n だけで決め、n は JKP が m−1 月末に組んだ時点の数'
             '（1926-01 に新しく載った8社が 1926-02 の行の若い三分位に入り、1925-12 から居る497社が古い三分位に入る＝組んだのは 1926-01 末）。'
             '信号（年齢の三分位）は JKP が m−1 月末の上場からの月数で組んだもので、この module は全期間の平均・分位・標準化を一切使わない')


def main(save=False):
    rows = select()
    elig = [r for r in rows if r['eligible'] and r['stats'] and r['stats']['excess'] >= 1.0]
    if elig:
        best = max(elig, key=lambda r: r['stats']['t'])
        how = '事前登録どおり（超過 +1%/年以上の中で t が最大）'
    else:
        # どれも線に届かない → 事前登録 r5 の系統の定義（古い側の三分位）どおりの変種の中で t が最大のもの
        cand = [r for r in rows if r['eligible'] and r['spec']['sides'] == [OLD]]
        best = max(cand, key=lambda r: r['stats']['t'])
        how = ('どの変種も +1%/年 に届かなかった。系統の定義（事前登録 r5『age の古い側の三分位』）どおりの変種の中で t が最大のものを選んだ'
               '（全変種で t が最大の『中＋古を等分・vw_cap』は中の三分位を含み定義から外れるので選ばない）')
    spec = dict(best['spec'])
    spec.update({'min_n': MIN_N, 'min_n_repl': MIN_N_REPL, 'replicate': REPL, 'turn_ann': TURN_ANN,
                 'side_note': "'3.0' = age（上場からの月数）が大きい＝古い三分位"})
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
    sub = best['sub']
    alt = next(x for x in rows if x['name'].startswith('若い三分位を避ける') and x['spec']['w'] == 'vw_cap')
    vw = next(x for x in rows if x['name'] == '古い三分位・vw')
    yng = next(x for x in rows if x['name'].startswith('若い三分位・vw_cap'))
    pos = sum(1 for v in mkt_sel.values() if v['excess'] > 0)
    rationale = (
        '【規則】米国上場株のうち、上場からの年数（JKP の age＝CRSP か Compustat に最初に載ってからの月数）が長い三分位'
        '（JKP の三分位 \'3.0\'・境目は非超小型株で引く）を、上限つきの時価加重（JKP vw_cap＝NYSE の80%点で重みに上限）で買いだけで持つ。'
        '組は JKP が毎月 m−1 月末に組んだものをそのまま使い、月 m のリターンを取る。'
        '【なぜ】(1) 新規上場の長い不振（Ritter 1991・Loughran-Ritter 1995）: 上場から日の浅い会社は上場後の数年に市場に負けやすい——その裏返しとして、'
        '若い会社を持たない古い側は不振の組を避けられる。(2) 古い会社は景気の波と競争を何度もくぐった生き残りで、情報が多く不確かさが小さい'
        '（ただし Barry-Brown 1984 は逆に情報の少ない会社に上乗せがあると示唆しており、2000年以前の先行研究は向きが割れている）。'
        '(3) 年齢はゆっくり動く信号なので回転が小さく費用に強い（回転は事前登録どおり 50%/年と置いた＝実際より重めのはず）。'
        f'【選定期間 {st["from"]}〜{st["to"]}（{st["years"]}年）】費用後の年率 {st["cagr"]}% 対 French 米国市場 {st["bench_cagr"]}%、'
        f'超過 {st["excess"]:+}%/年、t {st["t"]}（Newey-West {st["t_nw"]}）、ぶれ {st["vol"]}% 対 {st["bench_vol"]}%、'
        f'最大下落 {st["maxdd"]}% 対 {st["bench_maxdd"]}%、転がる10年で勝った窓 {st["roll10_win"]}。'
        f'市場に対するβ {best["beta"]}・CAPM のα {best["alpha_capm"]:+}%/年＝超過の一部はβが1より大きいことによる。'
        f'部分期間: 1926-1962 {sub["1926-1962"]["excess"]:+}%/年（t {sub["1926-1962"]["t"]}）・1963-2000 {sub["1963-2000"]["excess"]:+}%/年（t {sub["1963-2000"]["t"]}）。'
        f'JKP の上限つき市場（vw_cap）に対しては {best["ex_vs_jkp_capped_mkt"]:+}%/年＝超過のおよそ半分は「上限つきの重み（中型寄り）」の分で、古さそのものの分は小さい。'
        f'参考: 上限なしの時価加重（vw）の古い三分位は {vw["stats"]["excess"]:+}%/年（t {vw["stats"]["t"]}）＝市場とほぼ同じ。'
        f'若い三分位（vw_cap）は {yng["stats"]["excess"]:+}%/年（t {yng["stats"]["t"]}）で、古い側が若い側より良い（系統が前提とする向き。事前登録 r5 に数値の予想は書かれていない）。'
        f'【選び方】{how}。選べる4変種のうち t が最大は『若い三分位を避ける（中＋古を等分）・vw_cap』（{alt["stats"]["excess"]:+}%/年・t {alt["stats"]["t"]}）。'
        f'【他の市場（選定期間・参考・1986年ごろから）】先進国22か国のうち超過が正は {pos}/{len(mkt_sel)}。国のデータは 1986年ごろに始まり、'
        '年齢はデータの始まりで切れている（古い側＝データの始まりから居る会社）。'
        '【予想】選定期間でも線（+1%/年）に届かない弱い効果で、その半分は重みの付け方の分。ホールドアウトで +1%/年・t≥2 を満たす見込みは低い。'
    )
    extra = {'implement': FAMILY['implement'], 'lookahead_test': LOOKAHEAD, 'variants_table': tbl, 'markets': list(r['markets']),
             'markets_selection_period': mkt_sel, 'selection_note': how,
             'benchmark': 'French 米国市場（Mkt-RF＋RF・CRSP 全上場の上限なし時価加重）。他の国は JKP の国の mkt（vw＝上限なし・米ドル超過）＋French RF',
             'cost_note': '片道の回転100%につき0.25%。回転は 50%/年（事前登録 r5 の既定）＋等分の組の戻し（選んだ規則は1つの三分位なので戻し無し）',
             'eligible_variants': sum(1 for x in rows if x['eligible']), 'reference_variants': sum(1 for x in rows if not x['eligible'])}
    doc = h.save_spec('old_firms', spec, rationale, len(rows), st, extra)
    print('凍結:', best['name'])
    return doc


if __name__ == '__main__':
    main(save='--save' in sys.argv)
