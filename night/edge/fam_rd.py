#!/usr/bin/env python3
"""night/edge/fam_rd.py — 系統 rd（第6回）: 研究開発の厚い会社の買いだけの組 vs 米国市場

事前登録 out/edge_prereg_r6.json の round6_families.rd（線・費用・相手・期間は out/edge_prereg.json と同じ・K は累積）。
  素材: JKP（Jensen・Kelly・Pedersen）米国の三分位ポートフォリオ（買いだけ）。特徴は3本——
    rd_me    研究開発費 ÷ 時価総額（R&D-to-market）             Chan・Lakonishok・Sougiannis 2001（以下 CLS）
    rd_sale  研究開発費 ÷ 売上（R&D-to-sales）                  CLS 2001
    rd5_at   研究開発の資本（5年の研究開発費を毎年20%ずつ減価して積んだもの）÷ 総資産   CLS 2001 の R&D capital・Lev & Sougiannis 1996
  良い側 = JKP の予言の向き。JKP の因子は direction ×（'3.0' − '1.0'）なので、選定期間（〜2000-12）の米国データで
  因子 と '3.0'−'1.0' の相関の符号から決める（directions() が確かめ、spec に凍結する）。確かめた結果は3本とも +1.000
  ＝'3.0'（研究開発の厚い側）が良い側。JKP の定義表の direction も3本とも +1。

  ⚠ 研究開発を開示しない会社は三分位に入らない（JKP は研究開発費の欠測を0と読まない）——三分位の銘柄数の合計は
    2000-12 で rd_me 3,485社（米国の上場のおよそ半分）。米国の研究開発の開示は FAS 2（1974年）で義務になり、
    それ以前（1951〜1971）は任意に開示した少数の会社だけ（三分位あたり 9〜77社）。事前登録 r6 の社数の下限
    （米国は三分位が50社以上の月だけ）で、rd_me・rd_sale は 1965〜66年から、rd5_at は 1972〜73年から使える。
    ＝この規則の相手（French 米国市場）は研究開発をしない会社も含む市場全体で、『研究開発をする会社かどうか』の差も超過に入る。

  ⚠ JKP の ret は米国の短期金利（T-bill）を引いた米ドルの超過 → 総リターン = ret + French RF（fam_payout・fam_old_firms と同じ）。
  先読み: JKP は月末 t の特徴（会計値は4か月以上遅らせて使う）で組み、t+1 の月のリターンを出す。銘柄数 n も組んだ時点の数。
    この規則はデータから何も推定しない（側と重みは凍結した spec の定数）ので、月 m のリターンは JKP の月 m の値・月 m の n・
    月 m の RF だけで決まる。lookahead_test() が切り詰め・ずらし（未来を壊す）・月合わせで確かめる。

  相手: French 米国市場（上限なしの時価加重）。費用: 回転1あたり 0.25%・回転 50%/年（会計の信号の置き値・事前登録 r6）。
    複数の特徴を等分する変種は 脚の置き値の平均（どれも50%/年）＋ 毎月等分へ戻す売買（前月末の漂いから計算）。
  再現: JKP 先進国22か国に同じ特徴・同じ側・同じ重み付けを当てる（三分位20社以上の月だけ）。国の相手は JKP mkt(vw) + 米国 RF（米ドル）。

使い方: python3 night/edge/fam_rd.py            → 変種の表（選定の段・2000-12 まで）
        python3 night/edge/fam_rd.py --freeze   → 選んで凍結（out/edge/spec_rd.json）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h
import csv, io, json, math, random, statistics as S, zipfile
from concurrent.futures import ThreadPoolExecutor

FAMILY = {
    'key': 'rd',
    'name': '研究開発の厚い会社の買いだけ（JKP 研究開発費÷時価総額・÷売上・研究開発の資本÷総資産 の厚い三分位）',
    'implement': ('楽天証券の米国株（成長投資枠＝NISA 可・レバレッジではない）で、研究開発費を開示している米国上場株を'
                  '研究開発の厚さ（研究開発費÷時価総額 など・決算書の数字）で並べ、厚い上位1/3を時価加重で持ち、年に1回（決算の後）入れ替える。'
                  '三分位は数百社になり個人には重いので、実際には時価総額の大きい順に数十社に絞る近似になる（成績は近似でしかない）。'
                  '研究開発の厚さそのもので選ぶ ETF は楽天の海外ETFに無い。近いもの（XLK・VGT・IBB・SMH など技術・医薬の業種 ETF）は'
                  '研究開発の厚い業種に傾くが、業種で選ぶ別の規則で、研究開発費÷時価総額の高い（割安な研究開発）会社を選ぶこの規則とは中身が違う。'
                  '日本の個人が同じ規則を回すには、SEC の決算（10-K の Research and development 行）から自分で並べる必要がある'),
}

COST = 0.0025            # 片道の回転1あたり（個別株の組・事前登録 costs）
TURN_ANN = 0.5           # 回転 50%/年（会計の信号の置き値・事前登録 r6）
CHARS = ['rd_me', 'rd_sale', 'rd5_at']
MIN_N = 50               # 米国: 三分位の銘柄数がこれ未満の月は使わない（事前登録 r6）
MIN_N_REPL = 20          # 他の国（事前登録 r6）
DEV = ['jpn', 'gbr', 'deu', 'fra', 'can', 'aus', 'che', 'swe', 'nld', 'ita', 'esp', 'hkg', 'sgp', 'dnk', 'nor', 'bel',
       'fin', 'aut', 'irl', 'prt', 'nzl', 'isr']             # 先進国22か国（事前登録 r6 の順）
JKP = 'https://jkpfactors-data.s3.amazonaws.com/public/'
HIGH, MID, LOW = '3.0', '2.0', '1.0'

_MEMO = {}


# ───────────────────────── 読み込み ─────────────────────────
def _leg_raw(region, ch, w):
    key = ('p', region, ch, w)
    if key not in _MEMO:
        try:
            _MEMO[key] = h.jkp(region, ch, 'portfolio', w)
        except Exception:
            _MEMO[key] = {}
    return _MEMO[key]


def _counts(region, ch, w):
    """三分位の銘柄数 n（h.jkp は返さないので、同じキャッシュを h.cached で読み h.guard を通す）"""
    key = ('n', region, ch, w)
    if key in _MEMO:
        return _MEMO[key]
    url = f'{JKP}portfolios/%5B{region}%5D_%5B{ch}%5D_%5Bmonthly%5D_%5B{w}%5D.zip'
    out = {}
    try:
        z = zipfile.ZipFile(io.BytesIO(h.cached(f'jkp_portfolio_{region}_{ch}_{w}.zip', url)))
        for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
            try:
                out.setdefault(x['pf'], {})[int(x['date'][:4]) * 100 + int(x['date'][5:7])] = int(float(x['n']))
            except (TypeError, ValueError, KeyError):
                continue
    except Exception:
        out = {}
    _MEMO[key] = {k: h.guard(v) for k, v in out.items()}
    return _MEMO[key]


# ───────────────────────── 規則 ─────────────────────────
def build(spec, region, rf, min_n):
    """→ (総リターン {m}, 片道の回転 {m})。spec: {'chars': [...], 'sides': {ch: '1.0'|'2.0'|'3.0'}, 'w': 'vw_cap'|'vw'}
    合成は脚の等分（毎月もとの比へ戻す）。月 m に持つのは、使う脚がすべて月 m の行を持ち、どの脚も月 m の銘柄数
    （m−1 月末に組んだ時点の数）が min_n 以上の月だけ。途中で脚が欠けた月は持たない（中身を黙って変えない）"""
    chars, w = spec['chars'], spec['w']
    L = [(_leg_raw(region, c, w).get(spec['sides'][c], {}), _counts(region, c, w).get(spec['sides'][c], {})) for c in chars]
    if not L or any(not p for p, _ in L):
        return {}, {}
    months = sorted(set.intersection(*[set(p) for p, _ in L]))
    tw = 1.0 / len(L)
    ret, tv, prev = {}, {}, None
    for m in months:
        if m not in rf or any(n.get(m, 0) < min_n for _, n in L):
            prev = None
            continue
        r = [p[m] + rf[m] for p, _ in L]
        reb = 0.0 if prev is None else 0.5 * sum(abs(x - tw) for x in prev)
        ret[m] = sum(r) / len(r)
        tv[m] = TURN_ANN / 12 + reb
        g = [tw * (1 + x) for x in r]
        tot = sum(g)
        prev = [x / tot for x in g] if tot > 0 else None
    return ret, tv


def run(spec):
    mk, rf = h.us_market()
    ret, tv = build(spec, 'usa', rf, spec.get('min_n', MIN_N))
    out = {'ret': ret, 'bench': mk, 'rf': rf, 'turnover': tv, 'cost': COST, 'markets': {}}

    def one(c):
        try:
            jm = h.jkp(c, 'mkt', 'factor', 'vw')        # その国の市場（上限なしの時価加重・米ドルの超過）
        except Exception:
            return c, None
        bench = {m: v + rf[m] for m, v in jm.items() if m in rf}
        r, t = build(spec, c, rf, spec.get('min_n_repl', MIN_N_REPL))
        r = {m: v for m, v in r.items() if m in bench}
        if len(r) < 24:
            return c, None
        return c, {'ret': r, 'bench': bench, 'rf': rf, 'turnover': {m: t[m] for m in r}, 'cost': COST}

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
    """良い側を選定期間の米国データで決める: JKP 因子 = direction ×（'3.0'−'1.0'）→ 相関の符号"""
    out = {}
    for c in CHARS:
        p = _leg_raw('usa', c, 'vw_cap')
        f = h.jkp('usa', c, 'factor', 'vw_cap')
        ms = sorted(set(f) & set(p[LOW]) & set(p[HIGH]))
        r = _corr([f[m] for m in ms], [p[HIGH][m] - p[LOW][m] for m in ms])
        # 実物の並び: 3つの三分位がそろって50社以上の月だけで、三分位ごとの平均の超過（年率%・JKP の ret＝T-bill を引いた超過）
        n = _counts('usa', c, 'vw_cap')
        mm = [m for m in sorted(set(p[LOW]) & set(p[MID]) & set(p[HIGH])) if all(n[s].get(m, 0) >= MIN_N for s in (LOW, MID, HIGH))]
        means = {s: round(S.mean(p[s][m] for m in mm) * 1200, 2) for s in (LOW, MID, HIGH)}
        out[c] = {'side': HIGH if r > 0 else LOW, 'corr': round(r, 4), 'months': len(ms), 'from': ms[0], 'to': ms[-1],
                  'tercile_mean_excess_over_tbill_pct_yr': means, 'tercile_means_window': f'{mm[0]}-{mm[-1]}（{len(mm)}か月）',
                  'monotonic_increasing': means[LOW] < means[MID] < means[HIGH]}
    return out


def variants(sides):
    """成績を見る前に決めた変種 → [(名前, spec, 選べるか)]。数字や月を振らない。
    選べる14本 = 3本の単独 ×2重み ＋ 2本の等分3組 ×2重み ＋ 3本の等分 ×2重み。参考3本 = 薄い側（向きの確認・選ばない）"""
    V = []
    combos = [[c] for c in CHARS] + [['rd_me', 'rd_sale'], ['rd_me', 'rd5_at'], ['rd_sale', 'rd5_at'], list(CHARS)]
    for w in ('vw_cap', 'vw'):
        for cs in combos:
            V.append(('+'.join(cs) + f'|{w}', {'chars': cs, 'w': w, 'sides': {c: sides[c] for c in cs}}, True))
    for c in CHARS:
        V.append((f'{c}|vw_cap|薄い側（参考）', {'chars': [c], 'w': 'vw_cap', 'sides': {c: LOW}}, False))
    return V


def beta(ret, mk, rf, a=None, b=None):
    ms = [m for m in sorted(set(ret) & set(mk)) if (a is None or m >= a) and (b is None or m <= b)]
    x = [mk[m] - rf[m] for m in ms]
    y = [ret[m] - rf[m] for m in ms]
    mx, my = S.mean(x), S.mean(y)
    bt = sum((p - mx) * (q - my) for p, q in zip(x, y)) / sum((p - mx) ** 2 for p in x)
    return round(bt, 2), round((my - bt * mx) * 1200, 2)


SUBS = (('〜1974', None, 197412), ('1975-1987', 197501, 198712), ('1988-2000', 198801, 200012))
COMMON_START = 197501    # 参考の共通窓: FAS 2（研究開発の開示の義務化）の後・3本すべてが50社以上そろう（CLS 2001 の標本も 1975〜）


def select():
    assert h.PHASE == 'select'
    mk, rf = h.us_market()
    D = directions()
    sides = {c: D[c]['side'] for c in CHARS}
    rows = []
    for name, sp, ok in variants(sides):
        r, tv = build(sp, 'usa', rf, MIN_N)
        st = h.stats(r, mk, rf, b=h.SEL_END, turnover=tv, cost=COST)
        cm = h.stats(r, mk, rf, a=COMMON_START, b=h.SEL_END, turnover=tv, cost=COST)
        sub = {}
        for lab, a, b in SUBS:
            s2 = h.stats(r, mk, rf, a=a, b=b, turnover=tv, cost=COST)
            sub[lab] = {'excess': s2['excess'], 't': s2['t']} if s2 else None
        bt, al = beta(r, mk, rf, b=h.SEL_END)
        rows.append({'name': name, 'eligible': ok, 'spec': sp, 'stats': st, 'common': cm, 'sub': sub, 'beta': bt, 'alpha_capm': al,
                     'turnover_yr': round(sum(tv.values()) / len(tv) * 12, 3) if tv else None})
    return D, rows


def lookahead_test(spec):
    """(1) 切り詰め: JKP の脚・銘柄数・RF を月 X で切って作り直しても、X までの規則のリターンと回転が完全一致
       (2) 未来の毒: X より後の JKP の値を1か月ずらし、銘柄数と RF を乱数に置き換えて壊しても、X までは不変（後は変わる＝空回りしていない）
       (3) 側（信号）は spec の定数で、データから再推定しない（毒を入れても directions を呼ばない）
       (4) 月合わせ: 規則の月 m の総リターン − 月 m の RF = JKP の月 m の脚の超過の平均"""
    mk, rf = h.us_market()
    full, ftv = build(spec, 'usa', rf, MIN_N)
    saved = dict(_MEMO)
    cuts = [197512, 198512, 199012, 199512, 199912]
    res = {'cuts': cuts}
    ok1 = ok2 = True
    rnd = random.Random(20260928)
    try:
        for X in cuts:
            _MEMO.clear()
            for k, v in saved.items():
                _MEMO[k] = {s: {m: x for m, x in ser.items() if m <= X} for s, ser in v.items()}
            rfX = {m: v for m, v in rf.items() if m <= X}
            part, ptv = build(spec, 'usa', rfX, MIN_N)
            ok1 &= set(part) == {m for m in full if m <= X}
            ok1 &= all(abs(part[m] - full[m]) < 1e-15 and abs(ptv[m] - ftv[m]) < 1e-15 for m in part)
        res['truncate'] = ok1
        for X in cuts:
            _MEMO.clear()
            for k, v in saved.items():
                if k[0] == 'p':
                    _MEMO[k] = {s: {m: (x if m <= X else ser.get(h.add_months(m, -1), x) + rnd.gauss(0, 0.05)) for m, x in ser.items()}
                                for s, ser in v.items()}
                else:
                    _MEMO[k] = {s: {m: (x if m <= X else rnd.randint(0, 3000)) for m, x in ser.items()} for s, ser in v.items()}
            rfP = {m: (v if m <= X else rnd.uniform(0, 0.01)) for m, v in rf.items()}
            part, ptv = build(spec, 'usa', rfP, MIN_N)
            ok2 &= all(m in part and abs(part[m] - full[m]) < 1e-15 and abs(ptv[m] - ftv[m]) < 1e-15 for m in full if m <= X)
            ok2 &= any(abs(part.get(m, 9) - full[m]) > 1e-9 for m in full if m > X)
        res['poison_future'] = ok2
    finally:
        _MEMO.clear()
        _MEMO.update(saved)
    res['sides_constant'] = bool(spec.get('sides')) and all(s in (LOW, MID, HIGH) for s in spec['sides'].values())
    L = [_leg_raw('usa', c, spec['w'])[spec['sides'][c]] for c in spec['chars']]
    res['month_align_maxdiff'] = max(abs(full[m] - rf[m] - sum(x[m] for x in L) / len(L)) for m in full)
    # (5) 銘柄数の条件は月 m の行の n（m−1 月末に組んだ時点）だけで決まる: 持った月はすべて n ≥ MIN_N、持たない月は n < MIN_N か行が無い
    Ns = [_counts('usa', c, spec['w'])[spec['sides'][c]] for c in spec['chars']]
    res['min_n_ok'] = all(all(n.get(m, 0) >= MIN_N for n in Ns) for m in full)
    res['ok'] = ok1 and ok2 and res['month_align_maxdiff'] < 1e-12 and res['sides_constant'] and res['min_n_ok']
    return res


def _fmt(st):
    return f"{st['from']}〜 ex{st['excess']:+6.2f} t{st['t']:5.2f} (NW{st['t_nw']:5.2f}) vol{st['vol']:5.1f}/{st['bench_vol']:5.1f} dd{st['maxdd']:6.1f}/{st['bench_maxdd']:6.1f} 10年窓{st['roll10_win']}"


def main(freeze=False):
    D, rows = select()
    print('directions', D)
    for x in rows:
        print(f"{'○' if x['eligible'] else '参'} {x['name']:34s} {_fmt(x['stats'])} | 1975〜 ex{x['common']['excess']:+6.2f} t{x['common']['t']:5.2f}"
              f" | β{x['beta']} α{x['alpha_capm']:+} 回転{x['turnover_yr']} | {x['sub']}")
    elig = [x for x in rows if x['eligible'] and x['stats']['excess'] >= 1.0]
    if elig:
        best = max(elig, key=lambda x: x['stats']['t'])
        how = '事前登録どおり（選定期間＝各変種のデータの始まり〜2000-12 の費用後の超過が +1%/年以上の中で t が最大）'
    else:
        best = max((x for x in rows if x['eligible']), key=lambda x: x['stats']['t'])
        how = 'どの変種も +1%/年 に届かなかった。選べる変種の中で t が最大のものを正直に選んだ（線は下げていない）'
    print('選ぶ:', best['name'], how)
    if not freeze:
        return best
    spec = dict(best['spec'])
    spec.update({'min_n': MIN_N, 'min_n_repl': MIN_N_REPL, 'replicate': list(DEV), 'turn_ann': TURN_ANN,
                 'side_note': "'3.0' = 研究開発の厚い三分位（JKP の direction +1・選定期間の因子と 3.0−1.0 の相関 +1.000）"})
    la = lookahead_test(spec)
    print('lookahead', la)
    assert la['ok'], la
    r = run(spec)
    st = h.stats(r['ret'], r['bench'], r['rf'], b=h.SEL_END, turnover=r['turnover'], cost=r['cost'])
    assert abs(st['excess'] - best['stats']['excess']) < 1e-9 and st['t'] == best['stats']['t']
    mkt_sel = {}
    for c, x in r['markets'].items():
        s2 = h.stats(x['ret'], x['bench'], x['rf'], b=h.SEL_END, turnover=x['turnover'], cost=x['cost'])
        if s2:
            mkt_sel[c] = {'from': s2['from'], 'years': s2['years'], 'excess': s2['excess'], 't': s2['t']}
    print('他の市場（選定期間・参考）:', mkt_sel)
    tbl = [{'name': x['name'], 'eligible': x['eligible'], 'from': x['stats']['from'], 'excess': x['stats']['excess'], 't': x['stats']['t'],
            't_nw': x['stats']['t_nw'], 'vol': x['stats']['vol'], 'maxdd': x['stats']['maxdd'],
            'from_1975': {'excess': x['common']['excess'], 't': x['common']['t']}, 'beta': x['beta'], 'alpha_capm': x['alpha_capm'],
            'sub_periods': x['sub'], 'turnover_yr': x['turnover_yr']} for x in rows]
    sub, cm = best['sub'], best['common']
    others = sorted((x for x in rows if x['eligible'] and x is not best), key=lambda x: -x['stats']['t'])[:3]
    pos = sum(1 for v in mkt_sel.values() if v['excess'] > 0)
    rationale = (
        f"【規則】{best['name']}——JKP 米国の三分位のうち研究開発の厚い側（'3.0'）を"
        f"{'上限つきの時価加重（vw_cap）' if best['spec']['w'] == 'vw_cap' else '上限なしの時価加重（vw）'}で買いだけで持つ"
        f"{'（' + '・'.join(best['spec']['chars']) + ' の厚い側を等分・毎月戻す）' if len(best['spec']['chars']) > 1 else ''}。"
        '研究開発を開示しない会社は三分位に入らない（米国の上場のおよそ半分だけが素材）。三分位が50社未満の月は持たない。'
        '良い側の確かめ: JKP の direction は3本とも +1、選定期間の因子と 3.0−1.0 の相関は3本とも +1.000、三分位の平均の超過（T-bill 超・3つとも50社以上の月）は '
        + '／'.join(f"{c} 薄い{D[c]['tercile_mean_excess_over_tbill_pct_yr'][LOW]}<中{D[c]['tercile_mean_excess_over_tbill_pct_yr'][MID]}<厚い{D[c]['tercile_mean_excess_over_tbill_pct_yr'][HIGH]}%/年"
                   for c in CHARS) + '（3本とも単調）。'
        '【なぜ】研究開発は会計上その年の費用として全額落とされるので、研究開発の厚い会社は利益と簿価が小さく見え、'
        '市場は将来の利益を過小に見積もる（Lev & Sougiannis 1996・Chan, Lakonishok & Sougiannis 2001〔1975〜1995 の米国〕：'
        '研究開発費÷時価総額の高い組は年に約6%市場に勝ち、特に過去に株価が下がった研究開発の厚い会社で大きい。研究開発費÷売上は平均では勝たない）。'
        'CLS は、市場が研究開発への投資の報いを過小評価する（誤評価）か、研究開発の不確かさへの対価（リスク）かを分けられないとしている。'
        f"【選定期間 {st['from']}〜{st['to']}（{st['years']}年・費用 回転50%/年×0.25% を引いた後・相手 French 米国市場）】"
        f"年率 {st['cagr']}% 対 {st['bench_cagr']}%、超過 {st['excess']:+}%/年、t {st['t']}（Newey-West {st['t_nw']}）、"
        f"ぶれ {st['vol']}% 対 {st['bench_vol']}%、最大下落 {st['maxdd']}% 対 {st['bench_maxdd']}%、転がる10年の勝ち {st['roll10_win']}。"
        f"β {best['beta']}・CAPM のα {best['alpha_capm']:+}%/年。"
        f"部分期間: 〜1974（FAS 2 の前・任意の開示の会社だけ） {sub['〜1974']['excess'] if sub['〜1974'] else '—'}%/年"
        f"（t {sub['〜1974']['t'] if sub['〜1974'] else '—'}）・1975-1987 {sub['1975-1987']['excess']:+}（t {sub['1975-1987']['t']}）・"
        f"1988-2000 {sub['1988-2000']['excess']:+}（t {sub['1988-2000']['t']}）。1975〜2000（CLS の標本に近い窓）では {cm['excess']:+}%/年・t {cm['t']}。"
        f"次点: " + '／'.join(f"{x['name']} {x['stats']['excess']:+}・t {x['stats']['t']}" for x in others) + '。'
        f"【選び方】{how}。試した変種は{len(rows)}本（選べる14本＝3本の単独と等分4組 × vw_cap/vw、参考3本＝薄い側の向きの確認・選ばない）。"
        f"【他の市場（選定期間・参考）】22か国のうち三分位が20社以上そろう月が24か月以上ある国は {len(mkt_sel)}、そのうち超過が正は {pos}。"
        '米国外は研究開発の開示が薄く（国際会計基準では開発費の資産計上もある）、選定期間の国の比較は短く雑音が大きい。'
        '【予想（後知恵を含む）】研究開発の厚い会社は技術・医薬に傾くので、2001年以降の米国（大型テックの優位）では勝つかもしれないが、'
        '研究開発費÷時価総額の高い側は『研究開発に対して割安』な会社で、2000年のITバブルの崩壊の直後はむしろ効く向き。大型テックの勝ちを拾うとは限らない。'
    )
    extra = {
        'implement': FAMILY['implement'],
        'family_name': FAMILY['name'],
        'lookahead_test': ('(1) 切り詰め: JKP の脚・三分位の銘柄数・RF を 1975-12/1985-12/1990-12/1995-12/1999-12 で切って作り直しても、'
                           '切った月までの規則のリターンと回転が完全一致（持つ月の集合も一致） '
                           '(2) 未来の毒: 切った月より後の JKP のリターンを1か月ずらして乱数を足し、銘柄数と RF を乱数に置き換えても、それより前のリターンと回転は不変'
                           '（後ろは変わる＝検査が空回りしていない） (3) 側（信号）は spec の定数で、データから再推定しない '
                           f"(4) 月 m の総リターン − 月 m の RF = JKP の月 m の脚の超過の平均（差の最大 {la['month_align_maxdiff']:.1e}） "
                           '(5) 持つかどうか（三分位 50社以上）は月 m の行の n（JKP が m−1 月末に組んだ時点の銘柄数）だけで決まり、持った月はすべて条件を満たす。'
                           'JKP は月末 t の特徴で組み t+1 のリターンを出す（会計値は4か月以上遅らせる＝JKP 2023 の作り方）。'
                           '良い側は選定期間（〜2000-12）の米国データで 因子 と 3.0−1.0 の相関の符号から決めた（3本とも +1.000）'),
        'directions': D,
        'variants_table': tbl,
        'selection_note': how,
        'selection_window_note': '選び方は各変種のデータの始まり（三分位が50社以上そろう最初の月）〜2000-12 の t。from_1975 は FAS 2 の後の共通の窓（参考）',
        'subperiods': sub,
        'from_1975': {'excess': cm['excess'], 't': cm['t'], 'from': cm['from']},
        'markets': list(r['markets']),
        'markets_selection_period': mkt_sel,
        'markets_note': ('国は JKP の3文字で run() の markets のキーと同じ。相手はその国の JKP mkt(vw)+米国RF（米ドル）。三分位の銘柄数が20未満の月は落とす。'
                         '24か月そろわない国は markets に入らない（研究開発の開示が薄い国）'),
        'benchmark': 'French 米国市場（Mkt-RF＋RF・CRSP 全上場の上限なし時価加重）',
        'cost_note': '片道の回転100%につき0.25%。回転は 50%/年（事前登録 r6 の会計の信号の置き値）＋等分の組の毎月の戻し',
        'eligible_variants': sum(1 for x in rows if x['eligible']), 'reference_variants': sum(1 for x in rows if not x['eligible']),
    }
    doc = h.save_spec('rd', spec, rationale, len(rows), st, extra)
    print('凍結:', best['name'], doc['n_variants_tried'])
    return doc


if __name__ == '__main__':
    main(freeze='--freeze' in sys.argv)
