#!/usr/bin/env python3
"""night/edge/fam_pead.py — 系統 pead（第6回）: 決算の驚きの良い側（利益の驚き niq_su・売上の驚き saleq_su）の買いだけ vs 米国市場

事前登録 out/edge_prereg_r6.json の round6_families.pead（線・費用・相手・期間は out/edge_prereg.json と同じ）。
  ・素材: JKP（Jensen・Kelly・Pedersen）米国の三分位ポートフォリオ（買いだけ）
      niq_su    標準化した利益の驚き（四半期の純利益の前年同期差 ÷ その差の過去8四半期のばらつき）  Bernard & Thomas 1989 / Foster・Olsen・Shevlin 1984
      saleq_su  標準化した売上の驚き（同じ作りを四半期の売上で）                                    Jegadeesh & Livnat 2006
  ・良い側 = JKP の予言の向き。JKP の因子は direction ×（'3.0' − '1.0'）なので、選定期間（〜2000-12）の米国データで
    因子 と '3.0'−'1.0' の相関の符号から決め（directions()）、三分位の平均の並びでも確かめる。spec に定数として凍結する
  ・JKP の三分位の 'ret' は米ドルの超過リターン（米国の短期金利を引いたもの）→ 総リターン = ret + French RF
    （fam_payout.py で確かめ済み: JKP mkt(vw) + French RF − French 市場 = 月平均 0.0000）
  ・月 m の組は JKP が m−1 月末に組んだ三分位（会計値は公表の遅れを置いて使う＝JKP 2023 の作り方）。銘柄数 n も組んだ時点の数
  ・合成 = 良い側の脚を等分（毎月もとの比へ戻す）。その月に全部の脚がそろい、全部の脚の銘柄数が下限以上の月だけを返す
  ・費用: 片道の回転100%につき 0.25%。回転は 300%/年（四半期の決算の信号の置き値・r6）＋ 等分の組の毎月の戻し
  ・相手: French 米国市場（上限なしの時価加重・配当込み）
  ・再現: JKP の先進国22か国に同じ特徴・同じ側・同じ重み。国の相手は JKP の国の mkt（vw）＋ French RF（米ドル）

使い方: python3 night/edge/fam_pead.py          → 変種の表（選定の段・2000-12 まで）
        python3 night/edge/fam_pead.py --la     → 先読みの検査だけ
        python3 night/edge/fam_pead.py --save   → 選んで凍結（out/edge/spec_pead.json）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h
import csv, io, math, random, statistics as S, zipfile
from concurrent.futures import ThreadPoolExecutor

FAMILY = {
    'key': 'pead',
    'name': '決算の驚きの良い側の買いだけ（JKP 標準化した利益の驚き・売上の驚きの上の三分位）',
    'implement': ('楽天証券の米国株（成長投資枠で NISA 可・レバレッジではない）で個別株を持つ形しか無い: 決算が出るたび（四半期ごと・'
                  '米国は1〜2月・4〜5月・7〜8月・10〜11月に集中）、米国上場の大型・中型株を「四半期の利益（または売上）の前年同期差 ÷ その差の'
                  '過去2年のばらつき」で並べ、上の1/3を時価加重で持ち、下がった銘柄は次の決算で入れ替える。回転は年300%前後と重く、'
                  '数百社の三分位を個人が再現するのは無理なので、実際には大きい会社から数十社に絞る近似になる。'
                  '決算の驚きで選ぶ ETF は楽天の一覧（out/broker_lineup.json）には無く、米国にも純粋なものは見当たらない'
                  '（勢いの ETF〔MTUM〕は価格の勢いで選び、決算の驚きとは別物）。売買の手間・税（課税口座なら毎年の売却益に20.315%）が重い'),
}

COST = 0.0025                     # 片道の回転100%につき（事前登録: 個別株の組）
TURN_ANN = 3.0                    # 片道の回転（年）。事前登録 r6 の置き値（四半期の決算の信号 300%/年）
MIN_N = 50                        # 米国: 三分位の銘柄数がこれ未満の月は使わない
MIN_N_REPL = 20                   # 他の国
CHARS = ['niq_su', 'saleq_su']
REPL = ['jpn', 'gbr', 'deu', 'fra', 'can', 'aus', 'che', 'swe', 'nld', 'ita', 'esp', 'hkg', 'sgp', 'dnk', 'nor', 'bel',
        'fin', 'aut', 'irl', 'prt', 'nzl', 'isr']          # 事前登録 r6 の先進国22か国
JKP = 'https://jkpfactors-data.s3.amazonaws.com/public/'

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
            _MEMO[k] = {s: (p.get(s, {}), n.get(s, {})) for s in ('1.0', '2.0', '3.0')}
        except Exception:
            _MEMO[k] = {}
    return _MEMO[k]


# ───────────────────────── 規則 ─────────────────────────
def build(spec, region, rf, min_n):
    """spec: {'legs': [[特徴, 三分位], ...], 'w': 'vw_cap'|'vw'} → (総リターン {m}, 片道の回転 {m})
    脚を等分に持ち毎月戻す。月 m に持つかどうかは、月 m の組（m−1 月末に組まれたもの）の銘柄数 n だけで決まる"""
    L = []
    for ch, side in spec['legs']:
        d = legs(region, ch, spec['w'])
        if not d or side not in d or not d[side][0]:
            return {}, {}
        L.append(d[side])
    months = sorted(set.intersection(*[set(r) for r, _ in L]))
    k = len(L)
    tw = 1.0 / k
    ret, tv, prev = {}, {}, None
    for m in months:
        if m not in rf or any(n.get(m, 0) < min_n for _, n in L):
            prev = None
            continue
        reb = 0.0 if prev is None else 0.5 * sum(abs(p - tw) for p in prev)
        ret[m] = sum(tw * r[m] for r, _ in L) + rf[m]
        tv[m] = TURN_ANN / 12 + reb
        g = [tw * (1 + r[m] + rf[m]) for r, _ in L]
        tot = sum(g)
        prev = [x / tot for x in g] if tot > 0 else None
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
    """良い側: JKP 因子 = direction ×（'3.0'−'1.0'）→ 相関の符号（vw_cap と vw の両方）。三分位の平均の並びも出す"""
    out = {}
    for c in CHARS:
        d = {}
        for w in ('vw_cap', 'vw'):
            L = legs('usa', c, w)
            f = h.jkp('usa', c, 'factor', w)
            ms = sorted(set(f) & set(L['1.0'][0]) & set(L['3.0'][0]))
            r = _corr([f[m] for m in ms], [L['3.0'][0][m] - L['1.0'][0][m] for m in ms])
            means = {s: round(S.mean(L[s][0][m] for m in ms) * 1200, 2) for s in ('1.0', '2.0', '3.0')}
            d[w] = {'corr': round(r, 4), 'months': len(ms), 'from': ms[0], 'to': ms[-1], 'mean_excess_ann_pct': means}
        side = '3.0' if d['vw_cap']['corr'] > 0 else '1.0'
        assert (d['vw']['corr'] > 0) == (side == '3.0'), d
        out[c] = {'side': side, 'bad': '1.0' if side == '3.0' else '3.0', **d}
    return out


def variants(D):
    """成績を見る前に決めた変種（scratchpad の plan_pead.md どおり）→ [(名前, spec, 選べるか)]"""
    g = {c: D[c]['side'] for c in CHARS}
    b = {c: D[c]['bad'] for c in CHARS}
    V = []
    for w in ('vw_cap', 'vw'):
        V.append((f'利益の驚き(niq_su)の良い側・{w}', {'legs': [['niq_su', g['niq_su']]], 'w': w}, True))
        V.append((f'売上の驚き(saleq_su)の良い側・{w}', {'legs': [['saleq_su', g['saleq_su']]], 'w': w}, True))
        V.append((f'利益＋売上の良い側を等分・{w}', {'legs': [['niq_su', g['niq_su']], ['saleq_su', g['saleq_su']]], 'w': w}, True))
    V.append(('利益の驚きの悪い側・vw_cap（参考・向きの確認）', {'legs': [['niq_su', b['niq_su']]], 'w': 'vw_cap'}, False))
    V.append(('売上の驚きの悪い側・vw_cap（参考・向きの確認）', {'legs': [['saleq_su', b['saleq_su']]], 'w': 'vw_cap'}, False))
    V.append(('利益の驚きの中＋良を等分・vw_cap（参考・悪い驚きを避ける＝定義の外）',
              {'legs': [['niq_su', '2.0'], ['niq_su', g['niq_su']]], 'w': 'vw_cap'}, False))
    V.append(('利益＋売上の中＋良の4脚を等分・vw_cap（参考・定義の外）',
              {'legs': [['niq_su', '2.0'], ['niq_su', g['niq_su']], ['saleq_su', '2.0'], ['saleq_su', g['saleq_su']]], 'w': 'vw_cap'}, False))
    return V


def beta(ret, mk, rf, a=None, b=None):
    ms = [m for m in sorted(set(ret) & set(mk)) if (a is None or m >= a) and (b is None or m <= b)]
    x = [mk[m] - rf[m] for m in ms]
    y = [ret[m] - rf[m] for m in ms]
    mx, my = S.mean(x), S.mean(y)
    bt = sum((p - mx) * (q - my) for p, q in zip(x, y)) / sum((p - mx) ** 2 for p in x)
    al = (my - bt * mx) * 1200
    return round(bt, 2), round(al, 2)


SUBS = (('1964-1980', None, 198012), ('1981-1990', 198101, 199012), ('1991-2000', 199101, 200012))


def select(D=None, verbose=True):
    assert h.PHASE == 'select'
    mk, rf = h.us_market()
    D = D or directions()
    capm = {m: v + rf[m] for m, v in h.jkp('usa', 'mkt', 'factor', 'vw_cap').items() if m in rf}
    rows = []
    for name, sp, ok in variants(D):
        r, tv = build(sp, 'usa', rf, MIN_N)
        st = h.stats(r, mk, rf, b=h.SEL_END, turnover=tv, cost=COST)
        gross = h.stats(r, mk, rf, b=h.SEL_END)
        sub = {}
        for lab, a, b in SUBS:
            s2 = h.stats(r, mk, rf, a=a, b=b, turnover=tv, cost=COST)
            sub[lab] = {'excess': s2['excess'], 't': s2['t']} if s2 else None
        st_cap = h.stats(r, capm, rf, b=h.SEL_END, turnover=tv, cost=COST)
        bt, al = beta(r, mk, rf, b=h.SEL_END)
        rows.append({'name': name, 'eligible': ok, 'spec': sp, 'stats': st, 'gross_excess': gross['excess'], 'sub': sub,
                     'beta': bt, 'alpha_capm': al, 'ex_vs_jkp_capped_mkt': st_cap['excess'] if st_cap else None,
                     'turnover_yr': round(sum(tv.values()) / len(tv) * 12, 3) if tv else None, 'months': len(r)})
        if verbose:
            print(f"{'○' if ok else '参'} {name:44} {st['from']}〜 ex{st['excess']:6} (費用前{gross['excess']:6}) t{st['t']:6} (NW{st['t_nw']}) "
                  f"vol{st['vol']}/{st['bench_vol']} dd{st['maxdd']}/{st['bench_maxdd']} β{bt} α{al} 回転{rows[-1]['turnover_yr']} "
                  f"対capmkt {rows[-1]['ex_vs_jkp_capped_mkt']} 10年窓{st['roll10_win']}  部分 {sub}")
    return rows


# ───────────────────────── 先読みの検査 ─────────────────────────
def lookahead_test(spec):
    """(1) 切り詰め: 脚・銘柄数・RF を月 X で切って作り直しても、X までの規則のリターンと回転が完全一致
       (2) 未来の毒: X より後の脚のリターン・銘柄数・RF を乱数に置き換えても、X までは不変（後ろは変わる＝検査が空回りしていない）
       (3) 1か月ずらし: X より後の脚の値を1か月後ろへずらしても X までは不変
       (4) 月合わせ: 規則の月 m の総リターン − 月 m の RF = 月 m の JKP の脚の超過の等分（同じ月 m の値だけ）
       (5) 側は spec の定数（データから再推定しない）"""
    mk, rf = h.us_market()
    saved = {k: v for k, v in _MEMO.items()}
    full, ftv = build(spec, 'usa', rf, MIN_N)
    res = {'cuts': [], 'n_months_full': len(full)}
    ok = True
    rng = random.Random(20260928)
    cuts = [197512, 198512, 199012, 199512, 199912]
    try:
        for X in cuts:
            row = {'cut': X}
            # (1) 切り詰め
            _MEMO.clear()
            for k, v in saved.items():
                _MEMO[k] = {s: ({m: x for m, x in r.items() if m <= X}, {m: x for m, x in n.items() if m <= X}) for s, (r, n) in v.items()}
            rfX = {m: v for m, v in rf.items() if m <= X}
            part, ptv = build(spec, 'usa', rfX, MIN_N)
            exp = {m for m in full if m <= X}
            row['truncate'] = set(part) == exp and all(abs(part[m] - full[m]) < 1e-15 and abs(ptv[m] - ftv[m]) < 1e-15 for m in part)
            # (2) 未来の毒
            _MEMO.clear()
            for k, v in saved.items():
                _MEMO[k] = {s: ({m: (x if m <= X else rng.uniform(-0.3, 0.3)) for m, x in r.items()},
                                {m: (x if m <= X else rng.randint(0, 400)) for m, x in n.items()}) for s, (r, n) in v.items()}
            rfP = {m: (v if m <= X else rng.uniform(0, 0.02)) for m, v in rf.items()}
            pois, ptv2 = build(spec, 'usa', rfP, MIN_N)
            row['poison_prefix_same'] = all(m in pois and abs(pois[m] - full[m]) < 1e-15 and abs(ptv2[m] - ftv[m]) < 1e-15 for m in exp) \
                and not any(m in pois for m in set(h.month_range(min(full), X)) - exp)
            row['poison_effective'] = any(abs(pois.get(m, 9) - full[m]) > 1e-9 for m in full if m > X)
            # (3) 1か月ずらし
            _MEMO.clear()
            for k, v in saved.items():
                _MEMO[k] = {s: ({m: (x if m <= X else r.get(h.add_months(m, -1), x)) for m, x in r.items()}, n) for s, (r, n) in v.items()}
            sh, _ = build(spec, 'usa', rf, MIN_N)
            row['shift_prefix_same'] = all(abs(sh[m] - full[m]) < 1e-15 for m in exp)
            row['shift_effective'] = any(abs(sh.get(m, 9) - full[m]) > 1e-12 for m in full if m > X)
            ok &= row['truncate'] and row['poison_prefix_same'] and row['poison_effective'] and row['shift_prefix_same'] and row['shift_effective']
            res['cuts'].append(row)
    finally:
        _MEMO.clear()
        _MEMO.update(saved)
    # (4) 月合わせ
    Ls = [legs('usa', c, spec['w'])[s][0] for c, s in spec['legs']]
    d = max(abs(full[m] - rf[m] - sum(x[m] for x in Ls) / len(Ls)) for m in full)
    res['month_align_maxdiff'] = d
    res['sides_constant'] = all(s in ('1.0', '2.0', '3.0') for _, s in spec['legs'])
    res['ok'] = bool(ok and d < 1e-12 and res['sides_constant'])
    return res


def prefix_subprocess(spec):
    """(6) 別プロセスで EDGE_SEL_END=199012 と 200012 に切って run(spec) を走らせ、1990-12 までの規則・相手・回転と
    他の市場の規則が一致するか（night/edge/prefix_check.py と同じ考え方を、凍結の前の spec で当てる）"""
    import json, subprocess, tempfile
    here = os.path.dirname(os.path.abspath(__file__))
    code = ('import json,sys,os; sys.path.insert(0,%r); import fam_pead as f; spec=json.loads(sys.argv[1]); r=f.run(spec); '
            'print(json.dumps({"ret":r["ret"],"bench":r["bench"],"tv":r["turnover"],'
            '"mk":{c:x["ret"] for c,x in r["markets"].items()},"mtv":{c:x["turnover"] for c,x in r["markets"].items()}}))') % here
    outs = {}
    for cut in (199012, 200012):
        env = dict(os.environ, EDGE_PHASE='select', EDGE_SEL_END=str(cut))
        p = subprocess.run([sys.executable, '-c', code, json.dumps(spec)], capture_output=True, text=True, env=env, timeout=3600)
        if p.returncode:
            raise RuntimeError(p.stderr[-800:])
        outs[cut] = json.loads(p.stdout.strip().split('\n')[-1])
    a, b = outs[199012], outs[200012]
    bad, n = 0, 0
    for key in ('ret', 'bench', 'tv'):
        for m, v in a[key].items():
            if int(m) <= 199012:
                n += 1
                if m not in b[key] or abs(b[key][m] - v) > 1e-12:
                    bad += 1
    mbad, mn = 0, 0
    for c, ser in a['mk'].items():
        for m, v in ser.items():
            if int(m) <= 199012:
                mn += 1
                if c not in b['mk'] or m not in b['mk'][c] or abs(b['mk'][c][m] - v) > 1e-12:
                    mbad += 1
    # 1990-12 で切った側に、1990-12 より後の月が1つも無いこと（guard が効いている）
    leak = sum(1 for key in ('ret', 'bench') for m in a[key] if int(m) > 199012)
    return {'us_values_compared': n, 'us_mismatch': bad, 'markets_values_compared': mn, 'markets_mismatch': mbad,
            'markets_in_1990cut': sorted(a['mk']), 'leak_after_cut': leak, 'ok': bad == 0 and mbad == 0 and leak == 0 and n > 0}


# ───────────────────────── 凍結 ─────────────────────────
def main(save=False):
    D = directions()
    print('向き:', D)
    rows = select(D)
    elig = [r for r in rows if r['eligible'] and r['stats'] and r['stats']['excess'] >= 1.0]
    if elig:
        best = max(elig, key=lambda r: r['stats']['t'])
        how = '事前登録どおり（選べる6変種のうち、選定期間の費用後の超過が +1%/年以上の中で t が最大）'
    else:
        cand = [r for r in rows if r['eligible']]
        best = max(cand, key=lambda r: r['stats']['t'])
        how = ('どの変種も費用後で +1%/年 に届かなかった。系統の定義（良い側の三分位）どおりの選べる6変種の中で、'
               '費用後の超過の t が最大のものを正直に選んだ（線に届かない規則であることを承知で凍結する）')
    spec = {'legs': best['spec']['legs'], 'w': best['spec']['w'], 'min_n': MIN_N, 'min_n_repl': MIN_N_REPL,
            'replicate': REPL, 'turn_ann': TURN_ANN, 'cost_per_turnover': COST,
            'side_note': "'3.0' = 標準化した驚きが大きい三分位（JKP の direction が +1 の側）。選定期間の 因子 と 3.0−1.0 の相関で確かめた"}
    la = lookahead_test(spec)
    print('先読みの検査:', la)
    assert la['ok'], la
    pc = prefix_subprocess(spec)
    print('別プロセスの切り口の検査:', pc)
    assert pc['ok'], pc
    r = run(spec)
    st = h.stats(r['ret'], r['bench'], r['rf'], b=h.SEL_END, turnover=r['turnover'], cost=r['cost'])
    mkt_sel = {}
    for c, x in r['markets'].items():
        s2 = h.stats(x['ret'], x['bench'], x['rf'], b=h.SEL_END, turnover=x['turnover'], cost=x['cost'])
        if s2:
            mkt_sel[c] = {'from': s2['from'], 'years': s2['years'], 'excess': s2['excess'], 't': s2['t']}
    print('選んだ:', best['name'], how)
    print('選定期間:', st)
    print('他の市場（選定期間・参考）:', mkt_sel, 'markets:', sorted(r['markets']))
    if not save:
        return best, st
    tbl = [{'name': x['name'], 'eligible': x['eligible'], 'from': x['stats']['from'], 'excess': x['stats']['excess'],
            'gross_excess': x['gross_excess'], 't': x['stats']['t'], 't_nw': x['stats']['t_nw'], 'vol': x['stats']['vol'],
            'maxdd': x['stats']['maxdd'], 'beta': x['beta'], 'alpha_capm': x['alpha_capm'],
            'ex_vs_jkp_capped_mkt': x['ex_vs_jkp_capped_mkt'], 'sub_periods': x['sub'], 'turnover_yr': x['turnover_yr']} for x in rows]
    return best, st, spec, la, pc, r, mkt_sel, tbl, how, rows, D


if __name__ == '__main__':
    if '--la' in sys.argv:
        D = directions()
        sp = {'legs': [['niq_su', D['niq_su']['side']], ['saleq_su', D['saleq_su']['side']]], 'w': 'vw_cap', 'replicate': REPL[:4]}
        print(lookahead_test(sp))
        print(prefix_subprocess(sp))
    else:
        main(save=False)
