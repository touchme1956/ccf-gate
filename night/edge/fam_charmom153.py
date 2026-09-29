#!/usr/bin/env python3
"""night/edge/fam_charmom153.py — 系統 charmom153（第10回 ④）: 特徴の勢い——153特徴の良い側の三分位のうち、直近で勝っている k 本を持つ

事前登録 out/edge_prereg_r10.json の families.charmom153（線・費用・相手・期間は out/edge_prereg.json と同じ）。
  ・素材: JKP（Jensen・Kelly・Pedersen）米国の三分位ポートフォリオ（買いだけ）。特徴の一覧は hindsight_bound.py の chars()
    （JKP availability.json の factors.usa。テーマ名は三分位のファイルが無く落ちる）。
  ・良い側: hindsight_bound.py と同じ決め方——選定期間（〜2000-12）の米国で、JKP の因子（vw_cap）と
    三分位の差 '3.0'−'1.0'（その重み w のもの）の共分散の符号。正なら '3.0'、負なら '1.0'。
    ★側は凍結の時に選定期間のデータで一度だけ決めて spec['sides'] に書く（run() はデータから推定しない）。
      そうしないと、先読みの検査（1990-12 で切る）で側が変わり、1990年以前の成績が食い違う。
  ・総リターン = JKP の三分位 'ret'（米ドルの超過）+ French RF（h.us_market()）。
  ・規則: 月 m に、良い側の三分位を「m−1 月末までの直近 L か月の米国市場に対する超過」で並べ、上位 k 本を等分で持つ。
    超過 = Π(1+r) − Π(1+市場)（L か月の複利どうしの差）。L か月すべてがそろう（その月の三分位が最低社数以上）特徴だけを並べる。
    月 m に持てる（月 m の三分位が最低社数以上＝m−1 月末に組んだ時点の数）ことも条件。候補が k 本に満たない月は持たない。
  ・回転: 組の中の回転の置き値 100%/年（月 1/12）＋入れ替えの回転（前月末に値動きで漂った重みと今月の等分との差の絶対値の和の半分）。
  ・費用: 片道の回転1あたり 0.25%。
  ・他の市場: JKP 先進国22か国（spec_profit.json の replicate と同じ）。その国に在る特徴だけ・三分位20社以上の月。
    側は米国で凍結したもの。国の相手は JKP の国の mkt（vw）＋米国 RF。k・L・w は凍結したもの。
    国の中の順位は国の相手に対する超過で並べる（相手は全特徴で共通なので、並びは総リターンで並べるのと同じ）。

使い方: python3 night/edge/fam_charmom153.py          → 変種の表（選定の段・2000-12 まで）
        python3 night/edge/fam_charmom153.py --save   → 選んで凍結（out/edge/spec_charmom153.json）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h
import csv, io, json, math, statistics as S, zipfile, threading
from concurrent.futures import ThreadPoolExecutor

FAMILY = {
    'key': 'charmom153',
    'name': '特徴の勢い（JKP 米国153特徴の良い側の三分位のうち、直近 L か月に米国市場へ最も勝った k 本を等分で持つ）',
    'implement': ('毎月、JKP が公開する米国の153の特徴（割安・収益性・勢い・投資など）ごとの「良い側の3分の1」の成績を見て、'
                  '直近で最も市場に勝っている k 本を等分で持つ。個人がそのまま再現するのは難しい——一本ごとに数百社の組なので、'
                  '実際には特徴の上位銘柄を時価の大きい順に絞る近似か、因子ETF（楽天で買える MTUM・QUAL・VLUE・USMV など）を'
                  '直近の成績で入れ替える粗い近似になる（ETF は十数本しか無く、153本の勢いとは別物）。'
                  '楽天証券の米国株・海外ETF（成長投資枠＝NISA 可・レバレッジではない）。入れ替えは毎月'),
}

COST = 0.0025
TURN_ANN = 1.0                    # 組の中の回転の置き値（会計と価格の信号の間）
MIN_N = 50                        # 米国: 三分位の銘柄数（r6/r8 の米国の決まりにそろえた）
MIN_N_REPL = 20                   # 他の国（事前登録 r10）
KS, LS, WS = (5, 10, 20), (1, 6, 12), ('vw_cap', 'vw')
REPL = ['jpn', 'gbr', 'deu', 'fra', 'can', 'aus', 'che', 'swe', 'nld', 'ita', 'esp', 'hkg', 'sgp', 'dnk', 'nor', 'bel',
        'fin', 'aut', 'irl', 'prt', 'nzl', 'isr']          # spec_profit.json の replicate と同じ22か国
JKP = 'https://jkpfactors-data.s3.amazonaws.com/public/'

_MEMO = {}
_LOCK = threading.Lock()


# ───────────────────────── 読み込み ─────────────────────────
def chars():
    """hindsight_bound.py の chars() と同じ（JKP availability.json の factors.usa・'mkt' を除く）"""
    d = json.loads(h.cached('jkp_availability.json', JKP + 'availability.json'))
    f = d.get('factors', {})
    names = f.get('usa') or f.get('all_countries') or []
    return sorted(n for n in names if n != 'mkt')


def legs(region, ch, w):
    """→ {三分位: (超過リターン {m}, 銘柄数 {m})}。h.jkp と同じキャッシュを一度だけ読み、両方を h.guard に通す。取れなければ {}"""
    k = (region, ch, w)
    with _LOCK:
        if k in _MEMO:
            return _MEMO[k]
    try:
        url = f'{JKP}portfolios/%5B{region}%5D_%5B{ch}%5D_%5Bmonthly%5D_%5B{w}%5D.zip'
        z = zipfile.ZipFile(io.BytesIO(h.cached(f'jkp_portfolio_{region}_{ch}_{w}.zip', url)))
        r, n = {}, {}
        for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
            try:
                m = int(x['date'][:4]) * 100 + int(x['date'][5:7])
                rv, nv = float(x['ret']), int(float(x['n']))
            except (TypeError, ValueError, KeyError):
                continue
            r.setdefault(x['pf'], {})[m] = rv
            n.setdefault(x['pf'], {})[m] = nv
        out = {s: (h.guard(r.get(s, {})), h.guard(n.get(s, {}))) for s in ('1.0', '2.0', '3.0') if s in r}
    except Exception:
        out = {}
    with _LOCK:
        _MEMO[k] = out
    return out


def factor(ch):
    try:
        return h.jkp('usa', ch, 'factor', 'vw_cap')
    except Exception:
        return {}


# ───────────────────────── 良い側（選定期間で一度だけ） ─────────────────────────
def sides(cs):
    """hindsight_bound.py の one() と同じ: 〜2000-12 の米国で 因子(vw_cap) と '3.0'−'1.0'（重み w）の共分散の符号。
    共通の月が60か月未満の特徴は落とす。→ {w: {特徴: '1.0'|'3.0'}}"""
    assert h.PHASE == 'select'

    def one(c):
        f = factor(c)
        if not f:
            return c, {}
        o = {}
        for w in WS:
            p = legs('usa', c, w)
            if '1.0' not in p or '3.0' not in p:
                continue
            a3, a1 = p['3.0'][0], p['1.0'][0]
            common = [m for m in f if m in a1 and m in a3 and m <= 200012]
            if len(common) < 60:
                continue
            a = [f[m] for m in common]; b = [a3[m] - a1[m] for m in common]
            ma, mb = S.mean(a), S.mean(b)
            cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
            o[w] = '3.0' if cov >= 0 else '1.0'
        return c, o
    out = {w: {} for w in WS}
    with ThreadPoolExecutor(8) as ex:
        for c, o in ex.map(one, chars()):
            for w, s in o.items():
                out[w][c] = s
    return out


# ───────────────────────── 規則 ─────────────────────────
def build(spec, region, rf, bench, min_n):
    """spec: {'k','L','w','sides': {特徴: 側}} → (総リターン {m}, 片道の回転 {m}, 持った特徴 {m: [...]})
    月 m の選び方は m−1 月末までの L か月の総リターンと相手、月 m の銘柄数（m−1 月末に組んだ時点）だけを使う"""
    k, L, w, sd = spec['k'], spec['L'], spec['w'], spec['sides']
    ser = {}
    for c, s in sd.items():
        p = legs(region, c, w)
        if s not in p:
            continue
        r, n = p[s]
        ok = {m: r[m] + rf[m] for m in r if m in rf and n.get(m, 0) >= min_n}
        if ok:
            ser[c] = ok
    if not ser:
        return {}, {}, {}
    months = sorted(set().union(*[set(v) for v in ser.values()]))
    ret, tv, held, prev = {}, {}, {}, None      # prev: 前月末に漂った重み {特徴: w}
    for m in months:
        if m not in rf:
            prev = None
            continue
        past = [h.add_months(m, -i) for i in range(1, L + 1)]
        if any(q not in bench for q in past):
            prev = None
            continue
        gb = math.prod(1 + bench[q] for q in past)
        sc = []
        for c, v in ser.items():
            if m in v and all(q in v for q in past):
                sc.append((math.prod(1 + v[q] for q in past) - gb, c))
        if len(sc) < k:
            prev = None
            continue
        sc.sort(key=lambda x: (-x[0], x[1]))
        pick = [c for _, c in sc[:k]]
        tw = {c: 1.0 / k for c in pick}
        if prev is None:
            sw = 0.0
        else:
            sw = 0.5 * sum(abs(tw.get(c, 0.0) - prev.get(c, 0.0)) for c in set(tw) | set(prev))
        rs = {c: ser[c][m] for c in pick}
        ret[m] = sum(rs.values()) / k
        tv[m] = TURN_ANN / 12 + sw
        held[m] = pick
        g = {c: tw[c] * (1 + rs[c]) for c in pick}
        tot = sum(g.values())
        prev = {c: x / tot for c, x in g.items()} if tot > 0 else None
    return ret, tv, held


def run(spec):
    mk, rf = h.us_market()
    ret, tv, _ = build(spec, 'usa', rf, mk, spec.get('min_n', MIN_N))
    out = {'ret': ret, 'bench': mk, 'rf': rf, 'turnover': tv, 'cost': COST, 'markets': {}}
    # 国の読み込みを先に並列で温める（22か国 × 特徴）
    jobs = [(c, ch) for c in spec.get('replicate', []) for ch in spec['sides']]
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda x: legs(x[0], x[1], spec['w']), jobs))

    def one(c):
        try:
            jm = h.jkp(c, 'mkt', 'factor', 'vw')
        except Exception:
            return c, None
        bench = {m: v + rf[m] for m, v in jm.items() if m in rf}
        r, t, _ = build(spec, c, rf, bench, spec.get('min_n_repl', MIN_N_REPL))
        r = {m: v for m, v in r.items() if m in bench}
        return c, ({'ret': r, 'bench': bench, 'rf': rf, 'turnover': {m: t[m] for m in r}, 'cost': COST}
                   if len(r) >= 24 and bench else None)
    for c in spec.get('replicate', []):
        c, x = one(c)
        if x:
            out['markets'][c] = x
    return out


# ───────────────────────── 選定（2000-12 まで） ─────────────────────────
def variants(SD):
    """成績を見る前に決めた変種（18本）: k × L × 重み"""
    V = []
    for w in WS:
        for k in KS:
            for L in LS:
                V.append((f'k{k}_L{L}|{w}', {'k': k, 'L': L, 'w': w, 'sides': SD[w]}))
    return V


def beta(ret, mk, rf, a=None, b=None):
    ms = [m for m in sorted(set(ret) & set(mk)) if (a is None or m >= a) and (b is None or m <= b)]
    x = [mk[m] - rf[m] for m in ms]
    y = [ret[m] - rf[m] for m in ms]
    mx, my = S.mean(x), S.mean(y)
    bt = sum((p - mx) * (q - my) for p, q in zip(x, y)) / sum((p - mx) ** 2 for p in x)
    return round(bt, 2), round((my - bt * mx) * 1200, 2)


def select(SD):
    assert h.PHASE == 'select'
    mk, rf = h.us_market()
    rows = []
    for name, sp in variants(SD):
        r, tv, held = build(sp, 'usa', rf, mk, MIN_N)
        st = h.stats(r, mk, rf, b=h.SEL_END, turnover=tv, cost=COST)
        if not st:
            rows.append({'name': name, 'spec': sp, 'stats': None})
            print(name, '測れない'); continue
        sub = {}
        for lab, a, b in (('〜1975', None, 197512), ('1976-2000', 197601, h.SEL_END), ('1986-2000', 198601, h.SEL_END)):
            s2 = h.stats(r, mk, rf, a=a, b=b, turnover=tv, cost=COST)
            sub[lab] = {'excess': s2['excess'], 't': s2['t']} if s2 else None
        bt, al = beta(r, mk, rf, b=h.SEL_END)
        ncand = S.median(len(v) for v in held.values()) if held else None
        rows.append({'name': name, 'spec': sp, 'stats': st, 'sub': sub, 'beta': bt, 'alpha_capm': al,
                      'turnover_yr': round(sum(tv.values()) / len(tv) * 12, 3) if tv else None})
        print(f"{name:14} {st['from']}〜 ex{st['excess']:+6.2f} t{st['t']:5.2f} (NW{st['t_nw']:5.2f}) "
              f"vol{st['vol']}/{st['bench_vol']} dd{st['maxdd']}/{st['bench_maxdd']} β{bt} α{al:+} 回転{rows[-1]['turnover_yr']} "
              f"10年窓{st['roll10_win']} 部分{sub}")
    return rows


def main(save=False):
    SD = sides(chars())
    for w in WS:
        print(w, '特徴', len(SD[w]), '側3.0', sum(1 for s in SD[w].values() if s == '3.0'))
    rows = select(SD)
    ok = [r for r in rows if r['stats']]
    elig = [r for r in ok if r['stats']['excess'] >= 1.0]
    if elig:
        best = max(elig, key=lambda r: r['stats']['t'])
        how = '事前登録どおり（選定期間の費用後の超過が +1%/年以上の変種の中で、費用後の超過の t が最大）'
    else:
        best = max(ok, key=lambda r: r['stats']['t'])
        how = 'どの変種も +1%/年 に届かなかった。t が最大の変種を選んだ（線に届かないことを承知で）'
    spec = dict(best['spec'])
    spec.update({'min_n': MIN_N, 'min_n_repl': MIN_N_REPL, 'replicate': REPL, 'turn_ann': TURN_ANN,
                 'side_note': "sides = 〜2000-12 の米国で JKP 因子(vw_cap) と '3.0'−'1.0' の共分散の符号（hindsight_bound と同じ）。凍結時に固定"})
    r = run(spec)
    st = h.stats(r['ret'], r['bench'], r['rf'], b=h.SEL_END, turnover=r['turnover'], cost=r['cost'])
    mkt_sel = {}
    for c, x in r['markets'].items():
        s2 = h.stats(x['ret'], x['bench'], x['rf'], b=h.SEL_END, turnover=x['turnover'], cost=x['cost'])
        if s2:
            mkt_sel[c] = {'from': s2['from'], 'years': s2['years'], 'excess': s2['excess'], 't': s2['t']}
    tbl = [{'name': x['name'], 'from': x['stats']['from'], 'excess': x['stats']['excess'], 't': x['stats']['t'],
            't_nw': x['stats']['t_nw'], 'vol': x['stats']['vol'], 'maxdd': x['stats']['maxdd'], 'beta': x['beta'],
            'alpha_capm': x['alpha_capm'], 'sub_periods': x['sub'], 'turnover_yr': x['turnover_yr']} for x in ok]
    print('選んだ:', best['name'], how)
    print('選定期間:', st)
    print('他の市場（選定期間・参考）:', mkt_sel)
    if not save:
        return best, st
    sub = best['sub']
    pos = sum(1 for v in mkt_sel.values() if v['excess'] > 0)
    others = sorted(ok, key=lambda x: -x['stats']['t'])[:4]
    rationale = (
        f'【規則】{best["name"]}: JKP 米国の特徴 {len(spec["sides"])} 本の良い側の三分位'
        f'（{"上限つきの時価加重 vw_cap" if spec["w"] == "vw_cap" else "上限なしの時価加重 vw"}）を、毎月 m−1 月末までの直近 {spec["L"]} か月の'
        f'米国市場に対する超過（複利どうしの差）で並べ、上位 {spec["k"]} 本を等分で持つ（毎月入れ替え）。'
        '【なぜ】2001年より前に筋があった: 因子のリターンには自己相関がある（Lewellen 2002 の業種・規模・簿価時価比の組の勢い／'
        'Moskowitz & Grinblatt 1999 の業種の勢い）。特徴の勢いとしての整理（Ehsani & Linnainmaa 2019・Gupta & Kelly 2019）は後の公表で、'
        'それを知った上での回（事前登録 r10 の honesty）。'
        f'【選定期間 {st["from"]}〜{st["to"]}（{st["years"]}年）】費用後の年率 {st["cagr"]}% 対 French 米国市場 {st["bench_cagr"]}%、'
        f'超過 {st["excess"]:+}%/年、t {st["t"]}（Newey-West {st["t_nw"]}）、ぶれ {st["vol"]}% 対 {st["bench_vol"]}%、'
        f'最大下落 {st["maxdd"]}% 対 {st["bench_maxdd"]}%、転がる10年で勝った窓 {st["roll10_win"]}。'
        f'市場に対するβ {best["beta"]}・CAPM のα {best["alpha_capm"]:+}%/年。回転 {best["turnover_yr"]}/年。'
        f'部分期間: ' + ' / '.join(f'{lab} {v["excess"]:+}%/年（t {v["t"]}）' for lab, v in sub.items() if v) + '。'
        f'【選び方】{how}。t の上位4: ' + ' / '.join(f'{x["name"]} {x["stats"]["excess"]:+}%（t {x["stats"]["t"]}）' for x in others) + '。'
        f'【他の市場（選定期間・参考・多くは1990年前後から）】先進国22か国のうち選定期間で測れた {len(mkt_sel)} か国で超過が正は {pos}。'
        '⚠ 良い側は選定期間の因子の向きで決めた（後知恵を1つ減らすため）が、153本という特徴の一覧そのものは2023年の JKP の選択＝'
        '2001年以降に知られた特徴も含む（事後の知識が一覧に入っている）。'
    )
    extra = {'implement': FAMILY['implement'], 'family_name': FAMILY['name'],
             'lookahead_test': ('night/edge/prefix_check.py（EDGE_SEL_END=199012 と 200012 で別プロセスに run() を回し、1990-12 までの規則・相手・'
                                '他の市場の成績が完全一致）。側は spec の定数で、run() はデータから平均・分位・標準化を推定しない。'
                                '月 m の選びは m−1 月末までの L か月の総リターン・相手と、月 m の行の n（JKP が m−1 月末に組んだ時点の数）だけ'),
             'variants_table': tbl, 'markets': list(REPL), 'markets_selection_period': mkt_sel, 'selection_note': how,
             'benchmark': 'French 米国市場（Mkt-RF＋RF）。他の国は JKP の国の mkt（vw＝上限なし・米ドル超過）＋French RF',
             'cost_note': '片道の回転1あたり 0.25%。回転は組の中の置き値 100%/年＋入れ替え（漂った重みと等分との差の絶対値の和の半分）',
             'decisions_not_in_prereg': [
                 '米国の三分位は50社以上の月だけ（r6/r8 の米国の決まりにそろえた。r10 は国の20社だけを書いていた）',
                 '直近 L か月の超過は複利どうしの差 Π(1+r)−Π(1+市場)（相手は全特徴で共通なので並びは総リターンの並びと同じ）',
                 '候補が k 本に満たない月は持たない（その月は成績に入らない）。同点は特徴名の順',
                 '良い側は米国で凍結した側を他の国にもそのまま使う（国ごとに推定しない）',
                 '国の順位は国の相手に対する超過で並べる（並びは総リターンと同じ）',
                 '良い側は凍結時に spec に固定（run() で推定すると先読みの検査で切り口ごとに側が変わるため）']}
    doc = h.save_spec('charmom153', spec, rationale, len(rows), st, extra)
    print('凍結:', best['name'], doc['n_variants_tried'])
    return doc


if __name__ == '__main__':
    main(save='--save' in sys.argv)
