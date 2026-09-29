#!/usr/bin/env python3
"""night/edge/confirm_em.py — 「市場に勝てる規則の探索」第4回（確認）: 凍結した規則を新興国で確かめる（事前登録 out/edge_prereg_r4.json）

  担当: C1_value_em・C3_lowbeta_em・C4_jkpmulti_em（3つとも新興国）。KEY='em' → out/edge/confirm_em.json
  ★凍結した規則（out/edge/spec_*.json・night/edge/fam_*.py）は一文字も変えない。関数は import してそのまま呼ぶ。
  ★EDGE_PHASE=holdout はこのプロセスの中でだけ立てる（全期間を読む）。判定は 2001-01〜 だけ。2001年より前は報告だけ。

  ■ 写し方（事前登録 r4 のとおり）
    C1  各国で be_me・ni_me・ocf_me（JKP に無ければ fcf_me）・div12m_me の三分位 '3.0'（vw）を等分。相手はその国の JKP mkt（vw）＋米国 rf。
        三分位の銘柄数が20社未満の月は、その特徴の分をその国の市場で持つ（intl_value の fallback と同じ扱い＝その分の超過は0）。
        主の系列は国の等加重。
    C3  fam_lowbeta_lev.rule() をそのまま呼ぶ（spec＝out/edge/spec_lowbeta_lev.json の spec）。素材は各国の
        h.jkp(国,'betabab_1260d','portfolio','vw')['1.0'] ＋ rf、相手は JKP mkt（vw）＋ rf。組の回転は凍結した素材 jkp_t1 の
        SOURCES の値（年200%）＝round 1 の先進国での再現と同じ。費用は 0.005/回転。
    C4  fam_jkpmulti.build() をそのまま呼ぶ（spec＝out/edge/spec_jkpmulti.json の spec・min_n は spec の min_n_repl=20）。
        相手は JKP mkt（vw）＋ rf。費用は 0.005/回転（spec の他は変えない）。

  ■ 事前登録 r4 に書かれていない判断（結果を見る前に決めた。理由は DECISIONS に書き、出力にも写す）
"""
import os, sys
os.environ['EDGE_PHASE'] = 'holdout'                       # このプロセスの中でだけ
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as h                                          # noqa: E402
import fam_lowbeta_lev as LB                                 # noqa: E402
import fam_jkpmulti as JM                                    # noqa: E402
from evaluate import pooled                                  # noqa: E402  （round 1〜3 と同じ『ならし』の式）
import datetime, hashlib, json, math, statistics as S       # noqa: E402
from concurrent.futures import ThreadPoolExecutor            # noqa: E402

assert h.PHASE == 'holdout'
BASE = h.BASE

# 取れなかった JKP のファイル（その国に無い特徴）を覚えておく——h.jkp は失敗のたびに4回やり直す（計24秒）ので、同じ失敗を繰り返さない。
# 返り値・例外は h.jkp と同じ（このプロセスの中だけの包み。harness.py は変えていない）
_jkp_orig, _jkp_fail = h.jkp, {}


def _jkp_memo(region, key, kind='factor', w='vw_cap'):
    k = (region, key, kind, w)
    if k in _jkp_fail:
        raise _jkp_fail[k]
    try:
        return _jkp_orig(region, key, kind, w)
    except Exception as e:
        _jkp_fail[k] = e
        raise


h.jkp = _jkp_memo
OUT = os.path.join(BASE, 'out', 'edge', 'confirm_em.json')
AVAIL_URL = 'https://jkpfactors-data.s3.amazonaws.com/public/availability.json'

COST_EM = 0.005                    # 事前登録 r4: 新興国の個別株の組は片道の回転1あたり 0.5%
MIN_N = 20                         # 事前登録 r4: 各月、三分位に20社以上ある国だけを数える
T_MIN, SHARE_MIN, ALPHA, K_TESTS = 2.0, 0.6, 0.05, 4   # r4 の verdict（4つの確認の中で Holm）

# 事前登録 r4 の列挙（MSCI の新興国＝2026 年の分類の24か国）
EM = 'bra chl chn col cze egy grc hun ind idn kor kwt mys mex per phl pol qat sau zaf twn tha tur are'.split()
DM = 'usa can gbr deu fra ita esp nld bel che aut swe nor dnk fin irl prt jpn aus nzl hkg sgp isr'.split()
AGG = {'all_countries', 'all_regions', 'developed', 'emerging', 'frontier', 'world', 'world_ex_us'}

C1_CHARS = ['be_me', 'ni_me', 'ocf_me', 'div12m_me']
C1_TURN = 0.5                      # 事前登録: 会計の信号 50%/年（JKP の三分位は毎月組み替えるので 0.5/12 を毎月計上）

DECISIONS = {
    'decided_before_results': True,
    '国の集合（主）': ('事前登録 r4 に列挙された MSCI の新興国24か国のうち、JKP にデータのある国（availability.json の portfolios に国があり、'
                  'その素材の系列が取れる国）。課題文「JKP にデータのある国すべて（先進国は含めない）」は r4 の列挙と availability の交わりと読んだ。'
                  '24か国は r4 の列挙で MSCI 新興国を過不足なく尽くしているので「など」は例示と読む。'),
    '国の集合（参考）': ('JKP にポートフォリオのある国のうち、先進国（MSCI の23か国＋usa）・地域の集計・主の24か国を除いた残り（フロンティア・ロシア・'
                   'アルゼンチン等）も同じ規則で回し、主の24か国に足した「広い集合」を参考として出す。判定には使わない。'),
    '国を数える月': ('r4「各月、三分位に20社以上ある国だけを数える」を次のように写した。C1: 4つの特徴のうち少なくとも1つの三分位 \'3.0\' が20社以上の月'
                '（20社未満の特徴はその国の市場で代える＝課題文の指定）。4つとも20社未満の月は、全部が市場になり超過が定義上0なので数えない。'
                'C3: 持つ三分位 \'1.0\'（低ベータ側）が20社以上の月。C4: fam_jkpmulti.build が min_n_repl=20 で少なくとも1本の脚を持つ月（build がそのように組む）。'
                '社数は JKP の n（月 m の組を m−1 月末に組んだ時点の銘柄数＝先読みではない。fam_jkpmulti と同じ読み方）。'),
    'C1 の回転': ('会計の信号の置き値 50%/年を、JKP の三分位が毎月組み替えることに合わせて 0.5/12 を毎月（特徴の脚の重みに比例して）計上し、'
                 'さらに4つの脚と市場の代わりの分を毎月等分へ戻す売買を数える（fam_jkpmulti.composite の数え方をそのまま使う。市場の代わりの分の中の回転は0）。'
                 'intl_value は French の年1回の組み替えなので1月に 0.5 を計上していた——月次の組では同じ年率を12等分するのが対応する写し方。'
                 '重みの戻しも数えるのは費用を軽く見せないため（保守側）。'),
    'C1 の ocf_me': 'ocf_me の三分位 \'3.0\' の系列がその国で取れない（JKP に無い・空）ときだけ fcf_me を使う。国ごとに決める（月ごとに入れ替えない）。',
    'C1 の脚の重み': ('4つの特徴を常に1/4ずつ。ある特徴の系列が国に無い・その月に20社未満・その月のリターンが欠ける、のいずれかならその1/4はその国の市場で持つ'
                   '（intl_value の fallback と同じ）。'),
    'C3 の組の回転': ('fam_lowbeta_lev.run が先進国の再現で使ったのと同じく、凍結した素材 jkp_t1 の SOURCES の値（年200%）を base_turn に渡す。'
                   '倍率は国の全期間の系列（20社未満の月も含む）で rule() がそのまま推定し、判定に数えるのは20社以上の月だけ。'
                   '参考として20社の下限を掛けない版も出す（round 1 の先進国の再現は下限なし）。'),
    'C4 の重み': 'spec の w（vw_cap＝脚の三分位は JKP の上限つき時価加重）は凍結した spec のまま変えない。相手は課題文どおり JKP mkt（vw）＋rf。',
    '国ごとの正': ('evaluate.py と同じく、2001-01〜の費用後の年率の差（幾何）が正の国を正と数える。h.stats の下限（24か月）に届かない国は分母に入れない。'
                '市場をならした超過と t は evaluate.pooled（月ごとに数えた国の超過の平均→その平均と t・超過は算術の年率）をそのまま使う。'),
    'Holm': ('r4 は4つの確認（C1・C3・C4・C6）の中で Holm。C6 はこの担当の外なので、判定は C6 の p を 1（最も不利）と置いた場合で出す'
             '（自分の3つの線が最も厳しくなる並び）。C6 の p を 0 と置いた場合（最も有利）も併記する。p は片側・正規近似（harness.pnorm_upper）。'),
}


def sha(path):
    try:
        return hashlib.sha256(open(path, 'rb').read()).hexdigest()
    except OSError:
        return None


def availability():
    raw = h.cached('jkp_availability.json', AVAIL_URL, 7)
    return json.loads(raw)


def safe(fn, *a):
    try:
        return fn(*a)
    except Exception:
        return None


# ───────────────────────── 素材 ─────────────────────────
def mkt_total(c, rf):
    """その国の JKP mkt（vw・米ドルの超過）＋米国 rf → 総リターン"""
    f = safe(h.jkp, c, 'mkt', 'factor', 'vw') or {}
    return {m: v + rf[m] for m, v in f.items() if m in rf}, f


# ───────────────────────── C1 ─────────────────────────
def c1_country(c, rf, chars=None):
    """chars を渡すのは事後の参考（特徴ごと）のときだけ。判定は既定の C1_CHARS"""
    chars = chars or C1_CHARS
    bench, mk_ex = mkt_total(c, rf)
    if not bench:
        return None
    L, used = {}, []
    for ch in chars:
        r, n = JM.leg(c, ch, '3.0', 'vw')
        use = ch
        if ch == 'ocf_me' and not r:
            r, n = JM.leg(c, 'fcf_me', '3.0', 'vw')
            use = 'fcf_me'
        used.append(use)
        if r:
            L[use] = (r, n)
    real = list(L)
    L['MKT'] = (mk_ex, {m: 10 ** 9 for m in mk_ex})         # 市場の代わりの分（銘柄数の関門は掛けない）
    K = len(chars)

    def wfn(m, act):
        if 'MKT' not in act:
            return {}
        a = [ch for ch in real if ch in act]
        if not a:
            return {}                                         # 4つとも20社未満 → 数えない
        w = {ch: 1 / K for ch in a}
        if len(a) < K:
            w['MKT'] = (K - len(a)) / K
        return w
    months = sorted({m for ch in real for m in L[ch][0]} & set(bench))
    ret, tv = JM.composite(L, rf, months, MIN_N, wfn, lambda ch: 0.0 if ch == 'MKT' else C1_TURN)
    # 脚ごとに実際に持った月（20社以上）の割合
    legm = {ch: sum(1 for m in ret if m >= h.HOLD_START and m in L[ch][0] and L[ch][1].get(m, 0) >= MIN_N) for ch in real}
    nh = sum(1 for m in ret if m >= h.HOLD_START)
    return {'ret': ret, 'bench': {m: bench[m] for m in ret}, 'rf': rf, 'turnover': tv, 'cost': COST_EM,
            'info': {'chars_used': used, 'chars_with_data': real,
                     'leg_months_ge20_since2001': legm, 'months_counted_since2001': nh}}


# ───────────────────────── C3 ─────────────────────────
def c3_country(c, rf, spec, min_n=MIN_N):
    bench, _ = mkt_total(c, rf)
    if not bench:
        return None
    p = (safe(h.jkp, c, 'betabab_1260d', 'portfolio', 'vw') or {}).get('1.0') or {}
    n = (safe(JM._counts, c, 'betabab_1260d', 'vw') or {}).get('1.0') or {}
    if not p:
        return None
    pt = {m: v + rf[m] for m, v in p.items() if m in rf}
    ret, tv, L = LB.rule(pt, bench, rf, spec, LB.SOURCES['jkp_t1'][2])     # 凍結した規則をそのまま
    keep = [m for m in ret if m in bench and (min_n is None or n.get(m, 0) >= min_n)]
    Lh = [L[m] for m in keep if m >= h.HOLD_START]
    return {'ret': {m: ret[m] for m in keep}, 'bench': {m: bench[m] for m in keep}, 'rf': rf,
            'turnover': {m: tv[m] for m in keep}, 'cost': COST_EM,
            'info': {'months_counted_since2001': sum(1 for m in keep if m >= h.HOLD_START),
                     'mean_leverage_since2001': round(S.mean(Lh), 3) if Lh else None,
                     'rule_months_total': len(ret)}}


# ───────────────────────── C4 ─────────────────────────
def c4_country(c, rf, spec):
    bench, _ = mkt_total(c, rf)
    if not bench:
        return None
    ret, tv, _ = JM.build(spec, c, bench, rf, min_n=spec.get('min_n_repl', JM.MIN_N_REPL))   # 凍結した spec のまま
    ret = {m: v for m, v in ret.items() if m in bench}
    if not ret:
        return None
    return {'ret': ret, 'bench': {m: bench[m] for m in ret}, 'rf': rf, 'turnover': {m: tv[m] for m in ret}, 'cost': COST_EM,
            'info': {'months_counted_since2001': sum(1 for m in ret if m >= h.HOLD_START)}}


# ───────────────────────── 集計 ─────────────────────────
def ew_series(markets, a=None, b=None):
    per_r, per_b = {}, {}
    for x in markets.values():
        c, tv = x['cost'], x['turnover']
        for m in x['ret']:
            if (a and m < a) or (b and m > b) or m not in x['bench']:
                continue
            per_r.setdefault(m, []).append(x['ret'][m] - tv.get(m, 0.0) * c)
            per_b.setdefault(m, []).append(x['bench'][m])
    return ({m: S.mean(v) for m, v in per_r.items()}, {m: S.mean(v) for m, v in per_b.items()},
            {m: len(v) for m, v in per_r.items()})


def pooled_range(markets, a, b):
    """evaluate.pooled と同じ式を a〜b に限って（部分期間・参考）"""
    ex = {}
    for x in markets.values():
        for m in x['ret']:
            if a <= m <= b and m in x['bench']:
                ex.setdefault(m, []).append(x['ret'][m] - x['turnover'].get(m, 0.0) * x['cost'] - x['bench'][m])
    e = [S.mean(v) for m, v in sorted(ex.items())]
    if len(e) < 24:
        return None
    mu, sd = S.mean(e), S.stdev(e)
    return {'from': min(ex), 'to': max(ex), 'months': len(e), 'excess': round(mu * 1200, 2),
            't': round(mu / (sd / math.sqrt(len(e))), 2) if sd > 0 else None}


def summarize(markets, name):
    by = {}
    for c, x in sorted(markets.items()):
        st = h.stats(x['ret'], x['bench'], x['rf'], a=h.HOLD_START, turnover=x['turnover'], cost=x['cost'])
        pre = h.stats(x['ret'], x['bench'], x['rf'], b=h.SEL_END, turnover=x['turnover'], cost=x['cost'])
        row = {'months_counted_since2001': x['info'].get('months_counted_since2001'), **(x.get('info') or {})}
        if st:
            row.update({'from': st['from'], 'to': st['to'], 'years': st['years'], 'cagr': st['cagr'], 'bench_cagr': st['bench_cagr'],
                        'excess': st['excess'], 'ex_arith': st['ex_arith'], 't': st['t'], 't_nw': st['t_nw'],
                        'vol': st['vol'], 'bench_vol': st['bench_vol'], 'maxdd': st['maxdd'], 'bench_maxdd': st['bench_maxdd']})
        else:
            row['note'] = '2001年以降に数えた月が24か月未満 → 国ごとの正の分母に入れない（ならしには入る）'
        if pre:
            row['pre2001_info'] = {'from': pre['from'], 'excess': pre['excess'], 't': pre['t']}
        by[c] = row
    rated = {c: r for c, r in by.items() if 'excess' in r}
    pos = sum(1 for r in rated.values() if r['excess'] > 0)
    p_ex, p_t = pooled(markets)
    ew_r, ew_b, ncty = ew_series(markets, a=h.HOLD_START)
    ew = h.stats(ew_r, ew_b, markets[next(iter(markets))]['rf'] if markets else None)
    ew_pre_r, ew_pre_b, _ = ew_series(markets, b=h.SEL_END)
    ew_pre = h.stats(ew_pre_r, ew_pre_b, None)
    nc = list(ncty.values())
    # 1か国抜き（参考・頑健性）
    loo = {}
    for c in markets:
        _, t2 = pooled({k: v for k, v in markets.items() if k != c})
        loo[c] = t2
    worst = min(loo.items(), key=lambda kv: kv[1] if kv[1] is not None else 99) if loo else None
    last = max(ew_r) if ew_r else None
    return {
        'name': name,
        'by_country': by,
        'countries_run': len(markets), 'countries_rated': len(rated),
        'positive': f'{pos}/{len(rated)}', 'positive_share': round(pos / len(rated), 3) if rated else None,
        'pooled_excess': p_ex, 'pooled_t': p_t,
        'pooled_months': len(ew_r), 'pooled_from': min(ew_r) if ew_r else None, 'pooled_to': last,
        'countries_per_month': {'min': min(nc), 'median': S.median(nc), 'max': max(nc)} if nc else None,
        'ew_portfolio_since2001': ew,
        'subperiods_info': {'2001-2012': pooled_range(markets, 200101, 201212), '2013-': pooled_range(markets, 201301, 209912)},
        'pre2001_info': {'pooled': pooled_range(markets, 190001, h.SEL_END), 'ew': ew_pre},
        'leave_one_out_info': {'min_pooled_t': worst[1] if worst else None, 'dropped': worst[0] if worst else None},
    }


def holm(pvals):
    """pvals: {名前: p}（K_TESTS 本ぶんそろえて渡す）→ {名前: (線, 通過)}"""
    order = sorted(pvals.items(), key=lambda kv: kv[1])
    out, stop = {}, False
    for i, (k, p) in enumerate(order):
        thr = ALPHA / (len(order) - i)
        ok = (not stop) and p <= thr
        if not ok:
            stop = True
        out[k] = {'p': p, 'thr': round(thr, 5), 'pass': ok}
    return out


def run_set(countries, rf, spec_lb, spec_jm):
    C1, C3, C3n, C4 = {}, {}, {}, {}
    # 素材を先に並列で取る（キャッシュに入れるだけ）
    def warm(c):
        safe(h.jkp, c, 'mkt', 'factor', 'vw')
        for ch in C1_CHARS + ['fcf_me', 'betabab_1260d']:
            safe(h.jkp, c, ch, 'portfolio', 'vw')
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(warm, countries))
    for c in countries:
        x = c1_country(c, rf)
        if x and x['ret']:
            C1[c] = x
        x = c3_country(c, rf, spec_lb)
        if x and x['ret']:
            C3[c] = x
        x = c3_country(c, rf, spec_lb, min_n=None)
        if x and x['ret']:
            C3n[c] = x
        x = c4_country(c, rf, spec_jm)
        if x and x['ret']:
            C4[c] = x
        print(f'{c}: C1 {len(C1.get(c, {}).get("ret", {}))} C3 {len(C3.get(c, {}).get("ret", {}))} C4 {len(C4.get(c, {}).get("ret", {}))}',
              flush=True)
    return C1, C3, C3n, C4


def main():
    av = availability()
    have = set(av.get('portfolios', {}))
    prim = [c for c in EM if c in have]
    ref = sorted(c for c in have if c not in DM and c not in AGG and c not in EM)
    spec_lb = json.load(open(os.path.join(BASE, 'out', 'edge', 'spec_lowbeta_lev.json'), encoding='utf-8'))['spec']
    spec_jm = json.load(open(os.path.join(BASE, 'out', 'edge', 'spec_jkpmulti.json'), encoding='utf-8'))['spec']
    _, rf = h.us_market()

    C1, C3, C3n, C4 = run_set(prim, rf, spec_lb, spec_jm)
    s1 = summarize(C1, 'C1_value_em: 国の中の割安・高配当（be_me・ni_me・ocf_me/fcf_me・div12m_me の三分位3・vw を等分）')
    s3 = summarize(C3, 'C3_lowbeta_em: 低ベータ株を 1/β 倍（上限2倍・60か月）で持つ（betabab_1260d の三分位1・vw）')
    s4 = summarize(C4, 'C4_jkpmulti_em: 凍結した10本の合成（vw_cap の良い側を等分）')
    s3n = summarize(C3n, 'C3（参考・社数の下限なし）')

    tests = {'C1': s1, 'C3': s3, 'C4': s4}
    p = {k: h.pnorm_upper(v['pooled_t']) if v['pooled_t'] is not None else 1.0 for k, v in tests.items()}
    hw = holm({**p, 'C6': 1.0})                                  # 判定: C6 を最も不利に置く
    hb = holm({**p, 'C6': 0.0})                                  # 参考: C6 を最も有利に置く
    for k, v in tests.items():
        c_t = v['pooled_excess'] is not None and v['pooled_excess'] > 0 and (v['pooled_t'] or 0) >= T_MIN
        c_s = (v['positive_share'] or 0) >= SHARE_MIN
        v['p_one_sided'] = round(p[k], 5)
        v['holm_worst_case_C6_p1'] = hw[k]
        v['holm_best_case_C6_p0'] = hb[k]
        v['criteria'] = {'ならした超過が正で t≥2': c_t, '6割以上の国で正': c_s, 'Holm（C6 を最も不利に置く）': hw[k]['pass']}
        if c_t and c_s and hw[k]['pass']:
            v['verdict'] = '再現した'
        else:
            v['verdict'] = '再現しなかった'
        if v['verdict'] == '再現しなかった' and c_t and c_s and hb[k]['pass']:
            v['verdict_note'] = 'Holm だけが C6 の結果次第（C6 が先に通れば線が緩む）'

    # 参考: 広い集合（主の24か国＋フロンティア等）
    R1, R3, R3n, R4 = run_set(ref, rf, spec_lb, spec_jm)
    broad = {}
    for k, (a, b) in {'C1': (C1, R1), 'C3': (C3, R3), 'C4': (C4, R4)}.items():
        mk = {**a, **b}
        sm = summarize(mk, k + '（参考・広い集合）') if mk else None
        if sm:
            broad[k] = {'countries_added': sorted(b), 'positive': sm['positive'], 'pooled_excess': sm['pooled_excess'],
                        'pooled_t': sm['pooled_t'], 'by_country_added': {c: sm['by_country'][c] for c in b}}

    doc = {
        'key': 'em', 'round': 4, 'generated': datetime.date.today().isoformat(), 'phase': h.PHASE,
        'prereg': 'out/edge_prereg_r4.json', 'base_prereg': 'out/edge_prereg.json',
        'verdict_rule': ('r4: 2001-01〜・費用後・国をならした月次超過（evaluate.pooled）が正で t≥2.0、かつ 6割以上の国で超過が正。'
                         '4つの確認（C1・C3・C4・C6）の中で Holm（α=0.05・片側）。'),
        'verdict': {'C1': s1['verdict'], 'C3': s3['verdict'], 'C4': s4['verdict']},
        'C1': s1, 'C3': s3, 'C4': s4,
        'C3_reference_no_min_n': {k: s3n[k] for k in ('positive', 'pooled_excess', 'pooled_t', 'pooled_months', 'countries_rated')},
        'holm': {'K': K_TESTS, 'worst_case_C6_p1': hw, 'best_case_C6_p0': hb,
                 'note': 'C6 の p が出たら4本で掛け直すこと（このファイルの判定は C6 を最も不利に置いた場合）'},
        'countries_primary': prim, 'countries_reference_extra': ref,
        'mapping_decisions': DECISIONS,
        'costs': {'per_turnover': COST_EM, 'C1_turnover': '会計 50%/年（毎月 0.5/12）＋脚の等分への戻し',
                  'C3_turnover': '組 200%/年×倍率＋倍率の戻し（fam_lowbeta_lev.levered のまま）',
                  'C4_turnover': 'spec の turn_ann のまま＋合成の戻し（fam_jkpmulti.composite のまま）',
                  'C3_borrow': '借りた分に 米国 rf＋0.4%/年、経費 0.9%/年（spec のまま）'},
        'frozen_inputs_sha256': {p_: sha(os.path.join(BASE, p_)) for p_ in
                                 ('out/edge/spec_lowbeta_lev.json', 'out/edge/spec_jkpmulti.json', 'out/edge/spec_intl_value.json',
                                  'out/edge/spec_japan.json', 'night/edge/fam_lowbeta_lev.py', 'night/edge/fam_jkpmulti.py',
                                  'night/edge/harness.py', 'night/edge/evaluate.py', 'out/edge_prereg_r4.json')},
        'reference_broader_set': broad,
        'data_notes': [
            '国の分類は MSCI の今日（2026年）の新興国を全期間に当てた＝その時点の分類ではない（例: ギリシャは2001〜2013年に先進国、'
            'カタール・UAE は2014年まで、サウジは2019年まで、クウェートは2020年までフロンティア。ロシア〔2022年に除外〕・アルゼンチン・パキスタンは主の集合に無い＝参考の広い集合に入る）。',
            'JKP のリターンは米ドル建てで、米国の短期金利を引いた超過。総リターンは French の米国 RF を足して作った（先進国の確認と同じ）。国の相手は JKP 自身の国の市場（vw・上限なし）で、MSCI の指数ではない。',
            '外国人が買えたか（中国 A 株・サウジは2015年まで外国人に閉鎖・インドの外国人枠など）の投資可能性の絞りは無い。新興国の小型・流動性の低い株の実際の売買費用は 0.5%/回転より重いことがある。',
            'JKP の新興国の被覆は国によって1990年代〜2000年代から。三分位の銘柄数が薄い国・月は20社の下限で落ちる（国ごとの months_counted_since2001 を見よ）。',
            'C1 の div12m_me は無配の会社が多い国で三分位3の境が歪むことがある（JKP の三分位は特徴の値で3等分）。',
            'C4 の脚は凍結した spec の vw_cap（上限つきの時価加重）、相手は vw（上限なし）。上限つきの脚は小型寄りなので、その分の差を含む（先進国の確認と同じ）。',
            'C3 の借入の金利は米国の短期金利＋0.4%/年（米ドルで借りる想定）。新興国の株を信用で買う現実の手段はほぼ無い＝実行できる規則ではなく、効果の再現の確認。',
            '2001年より前は報告だけ（pre2001_info）。判定に使っていない。',
        ],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(doc, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for k, v in tests.items():
        print(f"{k}: {v['verdict']}  ならし {v['pooled_excess']}%/年 t{v['pooled_t']}  正 {v['positive']}  Holm線 {v['holm_worst_case_C6_p1']}")
    print('参考 C3 下限なし:', doc['C3_reference_no_min_n'])
    print('参考 広い集合:', {k: (v['positive'], v['pooled_excess'], v['pooled_t']) for k, v in broad.items()})
    print('→', OUT)


# ───────────────────────── 事後の参考（判定を見た後に足した。判定には使わない） ─────────────────────────
def turnover_yr(markets):
    """2001年以降の国ごとの年あたりの回転（片道）の中央値と、費用 0.5% での年あたりの費用"""
    t = []
    for x in markets.values():
        v = [x['turnover'].get(m, 0.0) for m in x['ret'] if m >= h.HOLD_START]
        if len(v) >= 24:
            t.append(S.mean(v) * 12)
    if not t:
        return None
    md = S.median(t)
    return {'median_turnover_per_year': round(md, 2), 'median_cost_per_year_pct': round(md * COST_EM * 100, 2), 'countries': len(t)}


def posthoc():
    doc = json.load(open(OUT, encoding='utf-8'))
    prim = doc['countries_primary']
    spec_lb = json.load(open(os.path.join(BASE, 'out', 'edge', 'spec_lowbeta_lev.json'), encoding='utf-8'))['spec']
    spec_jm = json.load(open(os.path.join(BASE, 'out', 'edge', 'spec_jkpmulti.json'), encoding='utf-8'))['spec']
    _, rf = h.us_market()
    C1, C3, _, C4 = run_set(prim, rf, spec_lb, spec_jm)
    out = {'note': '判定を見た後に足した参考（事後）。判定・線は変えていない'}
    out['turnover'] = {'C1': turnover_yr(C1), 'C3': turnover_yr(C3), 'C4': turnover_yr(C4)}
    # 費用の前（参考）
    g = lambda mk: pooled({c: {**x, 'cost': 0.0} for c, x in mk.items()})
    out['gross_of_cost_pooled'] = {k: dict(zip(('excess', 't'), g(v))) for k, v in (('C1', C1), ('C3', C3), ('C4', C4))}
    # 先進国と同じ費用 0.25%/回転（参考）
    q = lambda mk: pooled({c: {**x, 'cost': 0.0025} for c, x in mk.items()})
    out['cost_0.25pct_pooled'] = {k: dict(zip(('excess', 't'), q(v))) for k, v in (('C1', C1), ('C3', C3), ('C4', C4))}
    # C4 の脚は vw_cap（上限つき）→ 相手を JKP mkt の vw_cap にしたら（上限つきの重みの分を相手にも持たせる）
    mk4 = {}
    for c, x in C4.items():
        f = safe(h.jkp, c, 'mkt', 'factor', 'vw_cap') or {}
        b = {m: f[m] + rf[m] for m in x['ret'] if m in f and m in rf}
        if b:
            mk4[c] = {**x, 'ret': {m: x['ret'][m] for m in b}, 'bench': b}
    s4 = summarize(mk4, 'C4 vs JKP mkt vw_cap（参考）') if mk4 else None
    out['C4_vs_mkt_vw_cap'] = {k: s4[k] for k in ('positive', 'pooled_excess', 'pooled_t')} if s4 else None
    # C1 の特徴を一つずつ（同じ 20社の下限・市場で代える扱い）
    per = {}
    for ch in C1_CHARS:
        mk = {}
        for c in prim:
            x = c1_country(c, rf, [ch])
            if x and x['ret']:
                mk[c] = x
        sm = summarize(mk, ch) if mk else None
        if sm:
            per[ch] = {k: sm[k] for k in ('positive', 'pooled_excess', 'pooled_t')}
    out['C1_single_characteristic'] = per
    # 大きい4国（中国・韓国・台湾・インド）を抜く／湾岸4国（UAE・クウェート・カタール・サウジ）を抜く
    for nm, drop in (('C1_without_chn_kor_twn_ind', {'chn', 'kor', 'twn', 'ind'}), ('C1_without_gulf', {'are', 'kwt', 'qat', 'sau'})):
        p_ex, p_t = pooled({c: x for c, x in C1.items() if c not in drop})
        out[nm] = {'excess': p_ex, 't': p_t}
    for nm, drop in (('C4_without_chn_kor_twn_ind', {'chn', 'kor', 'twn', 'ind'}), ('C4_without_gulf', {'are', 'kwt', 'qat', 'sau'})):
        p_ex, p_t = pooled({c: x for c, x in C4.items() if c not in drop})
        out[nm] = {'excess': p_ex, 't': p_t}
    doc['post_hoc_reference'] = out
    json.dump(doc, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    posthoc() if '--posthoc' in sys.argv else main()
