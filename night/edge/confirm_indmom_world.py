#!/usr/bin/env python3
"""night/edge/confirm_indmom_world.py — 「市場に勝てる規則の探索」第4回（確認）C6_indmom_world（事前登録 out/edge_prereg_r4.json）

  凍結した indmom の規則（out/edge/spec_indmom.json・night/edge/fam_indmom.py）を、選定にも検定にも使っていない市場
  ＝JKP の国別の業種ポートフォリオ（米国以外の先進国と新興国）へ当てる。KEY='indmom_world' → out/edge/confirm_indmom_world.json
  ★凍結した規則は一文字も変えない。fam_indmom.signal() と fam_indmom.weights() を import してそのまま呼ぶ
    （窓 J=12・skip=0・等加重・毎月入れ替え・同順位の決め方・『業種が3つ未満なら持たない』の関門まで凍結のまま）。
  ★EDGE_PHASE=holdout はこのプロセスの中でだけ立てる（全期間を読む）。判定は 2001-01〜 だけ。2001年より前は報告だけ。
  ★書くのは out/edge/confirm_indmom_world.json だけ。ダウンロードは out/_edge_cache に既にあれば読むだけ、無ければ
    EDGE_SCRATCH（無ければ一時ディレクトリ）へ置く（リポジトリの中には書かない）。

  使い方: EDGE_SCRATCH=/path/to/scratch python3 night/edge/confirm_indmom_world.py [--lookahead]
"""
import os, sys
os.environ['EDGE_PHASE'] = 'holdout'                       # このプロセスの中でだけ
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as h                                          # noqa: E402
import fam_indmom as F                                       # noqa: E402  （凍結した規則の関数をそのまま呼ぶ）
from evaluate import pooled                                  # noqa: E402  （round 1〜3 と同じ『ならし』の式）
import csv, io, json, math, random, statistics as S, subprocess, tempfile, time, zipfile, datetime   # noqa: E402
from concurrent.futures import ThreadPoolExecutor            # noqa: E402

assert h.PHASE == 'holdout'
BASE = h.BASE
KEY = 'indmom_world'
OUT = os.path.join(BASE, 'out', 'edge', 'confirm_indmom_world.json')
SPEC_PATH = os.path.join(BASE, 'out', 'edge', 'spec_indmom.json')
SCRATCH = os.environ.get('EDGE_SCRATCH') or os.path.join(tempfile.gettempdir(), 'edge_scratch')
AVAIL_URL = 'https://jkpfactors-data.s3.amazonaws.com/public/availability.json'
IND_URL = 'https://jkpfactors-data.s3.amazonaws.com/public/industry/%5B{c}%5D_%5Bgics%5D_%5Bmonthly%5D_%5Bvw%5D.zip'
MKT_URL = 'https://jkpfactors-data.s3.amazonaws.com/public/%5B{c}%5D_%5Bmkt%5D_%5Bmonthly%5D_%5Bvw%5D.zip'

SPEC_DOC = json.load(open(SPEC_PATH, encoding='utf-8'))
FROZEN = SPEC_DOC['spec']                                    # {'n': 49, 'J': 12, 'skip': 0, 'k': 15, 'weight': 'ew'}
FRAC = FROZEN['k'] / FROZEN['n']                             # 上位3割＝15/49（事前登録 r4）
COST = 0.002                                                 # 事前登録 r4: 業種の入れ替えは回転1あたり 0.2%
MIN_FIRMS_HELD = 20                                          # 事前登録 r4「各月、三分位に20社以上ある国だけを数える」の写し（DECISIONS）
T_MIN, SHARE_MIN, ALPHA, K_TESTS = 2.0, 0.6, 0.05, 4         # r4 の verdict（4つの確認の中で Holm）

# 事前登録 r4 の列挙（MSCI の新興国＝2026 年の分類の24か国）と MSCI の先進国（米国を除く22か国）
EM = 'bra chl chn col cze egy grc hun ind idn kor kwt mys mex per phl pol qat sau zaf twn tha tur are'.split()
DM = 'can gbr deu fra ita esp nld bel che aut swe nor dnk fin irl prt jpn aus nzl hkg sgp isr'.split()

DECISIONS = {
    'decided_before_results': True,
    '素材': ('JKP の国別の業種ポートフォリオ（availability.json の industry）。米国以外で公開されている分類は GICS だけ（ff49 は usa だけ）なので '
           'GICS の2桁＝11部門を業種とする。URL は public/industry/[国]_[gics]_[monthly]_[vw].zip（実物で確かめた）。'
           '業種の中の重みは vw（上限なしの時価加重）——凍結した規則の素材 French の業種が業種の中は時価加重であり、相手の mkt も vw なので揃える。'),
    '総リターン': ('JKP の業種の ret は米ドルの超過リターン（米国の短期金利を引いたもの）。確かめ方: JKP の usa ff49（vw）と French 49業種の '
              '1979-01〜1985-12（44業種）で、月次の差の中央値が −0.88%/月（French RF の平均 0.83%/月）、RF を足すと −0.05%/月。'
              'よって業種の総リターン＝ret＋French RF、相手＝その国の JKP mkt（vw・超過）＋French RF（事前登録 r4・課題文どおり）。'
              '【追加の確かめ（結果を見た後・約束の確認だけで規則や写し方は変えていない）】相関0.97超の35組（1979-2000）に絞ると差の中央値 −0.577%/月 vs RF 0.566%/月、'
              'RF を足すと −0.011%/月。GICS のファイルも同じ約束か: JKP usa の GICS 部門と JKP usa ff49 の最も近い業種（2001〜）で、'
              'エネルギー（相関0.997）の差 +0.019±0.031%/月 vs RF 0.159%/月（GICS が総リターンなら +0.159 になる）＝GICS も超過リターン。'
              '凍結した規則の信号（12か月の複利）と回転の流し方は総リターンで計算する（French の素材が総リターンだったのと揃える）。'),
    '国の集合': ('事前登録 r4「米国以外の全ての国・先進国と新興国」を、availability.json の industry にある国のうち MSCI の先進国22か国（米国を除く）'
             '＋MSCI の新興国（r4 に列挙した24か国。cze は業種のデータが無い）と読んだ。フロンティア等（arg・pak・vnm・rus など）は '
             '先進国でも新興国でもないので入れない。分類は2026年の MSCI（時点ごとの分類ではない）。米国は検定済みなので含めない。'),
    '業種数と上位3割': ('業種数 N＝月 m に凍結した信号（fam_indmom.signal: m−1 月と窓の12か月がそろう業種）で並べられる業種の数。'
                  'k＝max(1, N×15/49 の四捨五入)。11部門なら k=3（N=9〜11→3・5〜8→2・3〜4→1）。k を入れた spec を fam_indmom.weights に'
                  'そのまま渡すので、凍結した『並べられる業種が max(k+1,3) 未満の月は持たない』もそのまま効く（＝3業種未満の国・月は数えない）。'),
    '社数の下限': ('r4「三分位に20社以上ある国だけを数える」を『持つ上位k業種の銘柄数の合計が20社以上の月だけその国を数える』と写した'
              '（三分位の規則で持つ組が20社以上あることの直訳）。銘柄数は JKP の n の m−1 月の行（m−1 月末に確実に分かる）。'
              'JKP は業種の銘柄数が10社未満の月の行を出さない（実物の最小値が10）ので、k≥2 なら下限は自動で満たし、k=1 のときだけ効く。'),
    '数えない月の扱い': ('国を数えない月（3業種未満・社数の下限割れ・その国の mkt が欠けた月）は、その国を戦略と相手の両方から外す（対称）。'
                   'その月は持たなかった＝次に数える月は新しく買い直すので回転1（凍結した規則の『最初の月は1』と同じ）。売る分の費用は数えない（凍結した規則と同じ）。'),
    '欠測': ('持っている業種の月 m の行が無い（銘柄数が10社を割った）ときは、凍結した規則どおり総リターン0と置く（fam_indmom.run と同じ）。回数を数えて出す。'),
    '回転と費用': ('凍結した規則どおり、前月の重みを当月のリターンで流した後の重みと新しい重みの差の絶対値の和の半分（片道）。費用は 0.002/回転（r4）。'),
    'ならし': ('主の系列は国の等加重（毎月、数える国の戦略の平均 vs 相手の平均）。判定の t は round 1〜3 と同じ evaluate.pooled（月ごとの国の平均の超過の t）。'
            '先進国と新興国を分けた集計も出すが、判定は全体で1つ。'),
    '国ごとの正': ('国ごとに h.stats（2001-01〜・費用後）の超過（年率の差）＞0 を正と数える。2001年以降に24か月以上ある国だけを分母に入れる'
               '（evaluate.judge_one と同じ）。'),
    'Holm': ('r4 は4つの確認の中で Holm を掛ける。この担当では片側 p（正規近似）と K=4 の各段の線（0.0125/0.0167/0.025/0.05）を出し、'
             '最終の Holm は4つの確認をそろえて掛ける（ここでは他の3つの p を見ない）。'),
    '参考（判定に使わない・事後に名札）': ('(a) 社数の下限なし（JKP の10社/業種だけ） (b) 持っている業種の欠測をその国の市場で代える (c) 診断: 並べられる全業種の等加重'
                             '（k=N）と、上位−全業種。どれも主の判定を変えない。'
                             '結果を見た後に足した頑健性（事後）: (d) 1か国ずつ抜いたときのならしの t の最小 (e) 2001-01〜2025-12 の300か月すべて数えた国だけ。'),
}


# ───────────────────────── 読み込み（書き込みはリポジトリの外だけ） ─────────────────────────
def _cached(name, url, days=30):
    p1 = os.path.join(h.CACHE, name)
    if os.path.exists(p1) and os.path.getsize(p1) > 100 and time.time() - os.path.getmtime(p1) < days * 86400:
        return open(p1, 'rb').read()
    os.makedirs(SCRATCH, exist_ok=True)
    p2 = os.path.join(SCRATCH, name)
    if os.path.exists(p2) and os.path.getsize(p2) > 100 and time.time() - os.path.getmtime(p2) < days * 86400:
        return open(p2, 'rb').read()
    b = h._get(url)
    open(p2 + '.part', 'wb').write(b)
    os.replace(p2 + '.part', p2)
    return b


def availability():
    return json.loads(_cached('jkp_availability.json', AVAIL_URL, 7))


def industry(c):
    """→ (ret_ex {業種: {YYYYMM: 米ドル超過}}, n {業種: {YYYYMM: 銘柄数}})。guard 済み（holdout では素通し）"""
    z = zipfile.ZipFile(io.BytesIO(_cached(f'jkp_industry_{c}_gics_vw.zip', IND_URL.format(c=c))))
    ret, n = {}, {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        assert x['location'] == c and x['weighting'] == 'vw' and x['freq'] == 'monthly', x
        i = str(int(float(x['gics'])))
        m = int(x['date'][:4]) * 100 + int(x['date'][5:7])
        try:
            v = float(x['ret'])
        except (TypeError, ValueError):
            continue
        ret.setdefault(i, {})[m] = v
        n.setdefault(i, {})[m] = int(float(x['n']))
    return {i: h.guard(s) for i, s in ret.items()}, {i: h.guard(s) for i, s in n.items()}


def mkt(c):
    """その国の JKP 'mkt'（vw・米ドル超過）{YYYYMM: 小数}。h.jkp(c,'mkt','factor','vw') と同じ URL・同じ読み方（キャッシュ名も同じ）"""
    z = zipfile.ZipFile(io.BytesIO(_cached(f'jkp_factor_{c}_mkt_vw.zip', MKT_URL.format(c=c))))
    out = {}
    for x in csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())):
        if (x.get('name') or 'mkt') != 'mkt':
            continue
        try:
            out[int(x['date'][:4]) * 100 + int(x['date'][5:7])] = float(x['ret'])
        except (TypeError, ValueError):
            continue
    return h.guard(out)


# ───────────────────────── 規則（凍結した関数を呼ぶだけ） ─────────────────────────
def k_of(N):
    return max(1, int(math.floor(N * FRAC + 0.5)))


def position(r, n_ind, m, floor):
    """月 m の持ち物（m−1 月末までのデータだけ）→ (重み or None, 状態, N, k, 持つ組の銘柄数)"""
    sc = F.signal(r, m, FROZEN['J'], FROZEN.get('skip', 0))
    N = len(sc)
    k = k_of(N)
    w = F.weights(r, None, m, dict(FROZEN, k=k))              # 凍結した関数（ew なので cap は使わない）
    if w is None:
        return None, 'few_industries', N, k, None
    prev = h.add_months(m, -1)
    held_n = sum(n_ind.get(i, {}).get(prev, 0) for i in w)
    if floor and held_n < floor:
        return None, 'below_floor', N, k, held_n
    return w, 'ok', N, k, held_n


def run_country(ind_ex, n_ind, mkt_ex, rf, floor=MIN_FIRMS_HELD, miss='zero', all_ind=False):
    """→ ret, bench, turnover（月次・米ドルの総リターン）, 月ごとの状態の数え上げ"""
    r = {i: {m: v + rf[m] for m, v in s.items() if m in rf} for i, s in ind_ex.items()}
    bench = {m: v + rf[m] for m, v in mkt_ex.items() if m in rf}
    months = sorted(set().union(*[set(s) for s in r.values()])) if r else []
    ret, tv, info = {}, {}, {'months': {}, 'missing_held': [], 'N_k': {}}
    w_prev = None
    for m in months:
        if all_ind:
            # 診断（規則ではない）: 並べられる業種を全部等分で持つ。同じ国・月の土俵（3業種以上）で比べる
            sc = F.signal(r, m, FROZEN['J'], FROZEN.get('skip', 0))
            w = {i: 1 / len(sc) for i in sc} if len(sc) >= 3 else None
            st, N, k, hn = ('ok' if w else 'few_industries'), len(sc), len(sc), None
        else:
            w, st, N, k, hn = position(r, n_ind, m, floor)
        if w is not None and m not in bench:
            w, st = None, 'no_mkt'
        info['months'][m] = st
        if w is None:
            w_prev = None                                     # 持たなかった月 → 次に数える月は買い直し
            continue
        info['N_k'][m] = (N, k, hn)
        fill = {}
        for i in w:
            if m in r[i]:
                fill[i] = r[i][m]
            else:
                fill[i] = 0.0 if miss == 'zero' else bench[m]
                info['missing_held'].append((m, i))
        rp = sum(wi * fill[i] for i, wi in w.items())
        if w_prev is None:
            tv[m] = 1.0
        else:
            ks = set(w) | set(w_prev)
            tv[m] = 0.5 * sum(abs(w.get(i, 0.0) - w_prev.get(i, 0.0)) for i in ks)
        ret[m] = rp
        w_prev = {i: wi * (1 + fill[i]) / (1 + rp) for i, wi in w.items()} if rp > -1 else None
    return ret, {m: bench[m] for m in ret}, tv, info


# ───────────────────────── 集計 ─────────────────────────
def ew_series(markets, cs):
    ret, bench, tv = {}, {}, {}
    per = {}
    for c in cs:
        x = markets[c]
        for m in x['ret']:
            per.setdefault(m, []).append((x['ret'][m], x['bench'][m], x['turnover'].get(m, 0.0)))
    for m, v in per.items():
        ret[m] = S.mean(a for a, _, _ in v)
        bench[m] = S.mean(b for _, b, _ in v)
        tv[m] = S.mean(t for _, _, t in v)
    ncty = {m: len(v) for m, v in per.items()}
    return ret, bench, tv, ncty


def summarize(markets, cs, rf, label):
    cs = [c for c in cs if c in markets]
    if not cs:
        return None
    ret, bench, tv, ncty = ew_series(markets, cs)
    st = h.stats(ret, bench, rf, a=h.HOLD_START, turnover=tv, cost=COST)
    p_ex, p_t = pooled({c: markets[c] for c in cs})
    rep = {}
    for c in cs:
        x = markets[c]
        s = h.stats(x['ret'], x['bench'], rf, a=h.HOLD_START, turnover=x['turnover'], cost=COST)
        if s:
            rep[c] = s
    pos = sum(1 for v in rep.values() if v['excess'] > 0)
    hm = [m for m in ncty if m >= h.HOLD_START]
    # 前半・後半（2001-2012 / 2013-）
    halves = {'2001-2012': h.stats(ret, bench, rf, a=200101, b=201212, turnover=tv, cost=COST),
              '2013-': h.stats(ret, bench, rf, a=201301, turnover=tv, cost=COST)}
    return {'label': label, 'countries': len(cs), 'countries_counted_24m': len(rep),
            'positive': f'{pos}/{len(rep)}', 'positive_share': round(pos / len(rep), 3) if rep else None,
            'pooled_excess_arith_pct_yr': p_ex, 'pooled_t': p_t, 'p_one_sided': h.pnorm_upper(p_t) if p_t is not None else None,
            'ew_stats_2001': st, 'halves': halves,
            'countries_per_month': {'min': min(ncty[m] for m in hm) if hm else None, 'median': S.median(ncty[m] for m in hm) if hm else None,
                                    'max': max(ncty[m] for m in hm) if hm else None, 'first_month': min(hm) if hm else None,
                                    'last_month': max(hm) if hm else None}}


def build_all(data, rf, **kw):
    markets, infos = {}, {}
    for c, (ind_ex, n_ind, mk) in data.items():
        ret, bench, tv, info = run_country(ind_ex, n_ind, mk, rf, **kw)
        infos[c] = info
        if ret:
            markets[c] = {'ret': ret, 'bench': bench, 'rf': rf, 'turnover': tv, 'cost': COST}
    return markets, infos


def verdict_of(s):
    ok = (s['pooled_excess_arith_pct_yr'] is not None and s['pooled_excess_arith_pct_yr'] > 0 and
          (s['pooled_t'] or -9) >= T_MIN and (s['positive_share'] or 0) >= SHARE_MIN)
    return '再現した' if ok else '再現しなかった'


# ───────────────────────── 先読みの検査 ─────────────────────────
def _trunc(ind_ex, n_ind, mk, K):
    cut = lambda s: {m: v for m, v in s.items() if m <= K}
    return {i: cut(s) for i, s in ind_ex.items()}, {i: cut(s) for i, s in n_ind.items()}, cut(mk)


def _scramble(ind_ex, n_ind, mk, K, R):
    f = lambda s: {m: (R.gauss(0, .1) if m > K else v) for m, v in s.items() if not (m > K and R.random() < .15)}
    g = lambda s: {m: (R.randint(10, 400) if m > K else v) for m, v in s.items()}
    return {i: f(s) for i, s in ind_ex.items()}, {i: g(s) for i, s in n_ind.items()}, f(mk)


def lookahead_test(data, rf, ncty=8):
    """(1) 月 m の持ち物（業種・k・状態）を m−1 で切ったデータから作っても全データから作っても同一
       (2) 切り点 K より後を捨てた／乱数・欠測・でたらめな銘柄数に差し替えたデータで回しても、K 以前の ret・bench・回転・状態が1ビットも変わらない
       (3) 検出力: 信号の窓をわざと1か月未来へずらした版では (1) が不一致を出す"""
    R = random.Random(11)
    cs = sorted(data)[:: max(1, len(data) // ncty)]
    n1 = n2 = bad3 = n3 = 0
    for c in cs:
        ind_ex, n_ind, mk = data[c]
        r = {i: {m: v + rf[m] for m, v in s.items() if m in rf} for i, s in ind_ex.items()}
        months = sorted(set().union(*[set(s) for s in r.values()]))
        for m in months[13::9]:
            a = position(r, n_ind, m, MIN_FIRMS_HELD)
            t_ind, t_n, _ = _trunc(ind_ex, n_ind, mk, h.add_months(m, -1))
            rt = {i: {mm: v + rf[mm] for mm, v in s.items() if mm in rf} for i, s in t_ind.items()}
            b = position(rt, t_n, m, MIN_FIRMS_HELD)
            assert a[:4] == b[:4] and a[4] == b[4], (c, m, a, b)
            n1 += 1
            # (3) 窓を1か月未来へ: m+1 で signal を作ったものを m の持ち物と比べる
            fut = F.signal(r, h.add_months(m, 1), FROZEN['J'], 0)
            fut_t = F.signal(rt, h.add_months(m, 1), FROZEN['J'], 0)
            n3 += 1
            bad3 += fut != fut_t
        ret0, b0, tv0, i0 = run_country(ind_ex, n_ind, mk, rf)
        for K in months[20::31]:
            for d2 in (_trunc(ind_ex, n_ind, mk, K), _scramble(ind_ex, n_ind, mk, K, R)):
                r2, b2, tv2, i2 = run_country(*d2, rf)
                for m in ret0:
                    if m > K:
                        break
                    assert r2.get(m) == ret0[m] and b2.get(m) == b0[m] and tv2.get(m) == tv0[m], (c, K, m)
                for m, st in i0['months'].items():
                    if m <= K:
                        assert i2['months'].get(m) == st, (c, K, m)
            n2 += 1
    return {'countries_checked': cs, 'positions_prefix_checked': n1, 'truncate_scramble_cuts': n2,
            'power_future_window_mismatch': f'{bad3}/{n3}'}


# ───────────────────────── 本体 ─────────────────────────
def main():
    la_only = '--lookahead' in sys.argv
    av = availability()
    ind_ctys = set(av['industry'])
    cset = [c for c in DM + EM if c in ind_ctys]
    missing = [c for c in DM + EM if c not in ind_ctys]
    _, rf = h.us_market()

    def load(c):
        ind_ex, n_ind = industry(c)
        return c, (ind_ex, n_ind, mkt(c))
    with ThreadPoolExecutor(6) as ex:
        data = dict(ex.map(load, cset))
    la = lookahead_test(data, rf)
    print('先読みの検査', la)
    if la_only:
        return

    markets, infos = build_all(data, rf)
    groups = {'全体': [c for c in cset if c in markets], '先進国': [c for c in DM if c in markets], '新興国': [c for c in EM if c in markets]}
    main_s = {g: summarize(markets, cs, rf, g) for g, cs in groups.items()}
    v = verdict_of(main_s['全体'])

    # 国ごと
    per = {}
    for c in cset:
        inf = infos[c]
        mh = {m: s for m, s in inf['months'].items() if m >= h.HOLD_START}
        cnt = {k: sum(1 for s in mh.values() if s == k) for k in ('ok', 'below_floor', 'few_industries', 'no_mkt')}
        Ns = [inf['N_k'][m][0] for m in inf['N_k'] if m >= h.HOLD_START]
        ks = [inf['N_k'][m][1] for m in inf['N_k'] if m >= h.HOLD_START]
        hns = [inf['N_k'][m][2] for m in inf['N_k'] if m >= h.HOLD_START]
        x = markets.get(c)
        st = h.stats(x['ret'], x['bench'], rf, a=h.HOLD_START, turnover=x['turnover'], cost=COST) if x else None
        pre = h.stats(x['ret'], x['bench'], rf, b=200012, turnover=x['turnover'], cost=COST) if x else None
        pre_n = sum(1 for m in (x['ret'] if x else {}) if m <= 200012)
        tvy = (S.mean(x['turnover'][m] for m in x['ret'] if m >= h.HOLD_START) * 12) if x and any(m >= h.HOLD_START for m in x['ret']) else None
        ind_ex = data[c][0]
        per[c] = {'group': '先進国' if c in DM else '新興国',
                  'industry_data_from': min(min(s) for s in ind_ex.values()) if ind_ex else None,
                  'industry_data_to': max(max(s) for s in ind_ex.values()) if ind_ex else None,
                  'holdout': ({'from': st['from'], 'to': st['to'], 'years': st['years'], 'excess_geo_pct_yr': st['excess'],
                               'excess_arith_pct_yr': st['ex_arith'], 't': st['t'], 't_nw': st['t_nw'], 'cagr': st['cagr'],
                               'bench_cagr': st['bench_cagr'], 'vol': st['vol'], 'bench_vol': st['bench_vol'],
                               'maxdd': st['maxdd'], 'bench_maxdd': st['bench_maxdd']} if st else None),
                  'counted_in_positive_share': st is not None,
                  'months_2001_counted': cnt['ok'], 'months_2001_below_floor': cnt['below_floor'],
                  'months_2001_few_industries_or_no_signal': cnt['few_industries'], 'months_2001_no_mkt': cnt['no_mkt'],
                  'industries_ranked_median': S.median(Ns) if Ns else None, 'k_median': S.median(ks) if ks else None,
                  'held_firms_median': S.median(hns) if hns else None,
                  'turnover_per_year_2001': round(tvy, 2) if tvy is not None else None,
                  'missing_held_industry_months_2001': sum(1 for m, _ in inf['missing_held'] if m >= h.HOLD_START),
                  'pre2001_months': pre_n, 'pre2001_report_only': pre}

    # 参考（判定に使わない）
    ref = {}
    mk_a, _ = build_all(data, rf, floor=0)
    ref['a_社数の下限なし'] = {g: summarize(mk_a, [c for c in cs if c in mk_a], rf, g) for g, cs in
                          {'全体': cset, '先進国': DM, '新興国': EM}.items()}
    mk_b, inf_b = build_all(data, rf, miss='mkt')
    ref['b_欠測を市場で代える'] = {g: summarize(mk_b, [c for c in cs if c in mk_b], rf, g) for g, cs in
                            {'全体': cset, '先進国': DM, '新興国': EM}.items()}
    mk_c, _ = build_all(data, rf, all_ind=True)
    ref['c_診断_全業種の等加重'] = {g: summarize(mk_c, [c for c in cs if c in mk_c], rf, g) for g, cs in
                             {'全体': cset, '先進国': DM, '新興国': EM}.items()}
    # 上位−全業種等加重（同じ国・同じ月だけ）
    common = {c: sorted(set(markets[c]['ret']) & set(mk_c.get(c, {}).get('ret', {}))) for c in markets}
    diff = {}
    for c, ms in common.items():
        for m in ms:
            if m >= h.HOLD_START:
                a = markets[c]['ret'][m] - markets[c]['turnover'].get(m, 0) * COST
                b = mk_c[c]['ret'][m] - mk_c[c]['turnover'].get(m, 0) * COST
                diff.setdefault(m, []).append(a - b)
    dd = [S.mean(v) for m, v in sorted(diff.items())]
    ref['c_診断_上位−全業種等加重'] = {'excess_arith_pct_yr': round(S.mean(dd) * 1200, 2),
                                 't': round(S.mean(dd) / (S.stdev(dd) / math.sqrt(len(dd))), 2), 'months': len(dd)}
    # (d) 1か国ずつ抜いたときのならしの t の最小（事後の頑健性）
    loo = {}
    for c in groups['全体']:
        pe, pt = pooled({x: markets[x] for x in groups['全体'] if x != c})
        loo[c] = (pe, pt)
    worst = min(loo.items(), key=lambda kv: kv[1][1])
    ref['d_1か国抜きの最小'] = {'dropped': worst[0], 'pooled_excess_arith_pct_yr': worst[1][0], 'pooled_t': worst[1][1],
                          'max_t': max(v[1] for v in loo.values())}
    # (e) 2001-01〜2025-12 の300か月すべて数えた国だけ（国の出入りが無い集合）
    full = [c for c in groups['全体'] if per[c]['months_2001_counted'] == 300]
    ref['e_全300か月そろう国だけ'] = {g: summarize(markets, [c for c in cs if c in full], rf, g) for g, cs in
                               {'全体': cset, '先進国': DM, '新興国': EM}.items()}

    ms_all = [m for c in markets for m in markets[c]['ret'] if m >= h.HOLD_START]
    notes = [
        '業種は GICS の11部門（凍結した規則を選んだ French の49業種より粗い）。上位3割は11部門なら3部門で、1部門の比重が大きい（49業種の15本とは分散が違う）。',
        f'JKP の GICS の業種の系列は多くの国で 1999〜2001 年から（米国も 1999-07〜）。12か月の窓がそろうのはさらに1年後なので、2001年より前の月はほとんど無い（報告だけ）。データの最後の月は {max(ms_all) if ms_all else None}。',
        'JKP は業種の銘柄数が10社未満の月の行を出さない。小さな国では部門が出たり消えたりし、並べられる部門の数 N が月で変わる（k も変わる）。',
        'リターンは米ドル建て（為替を含む）。相手も同じ国の米ドル建ての mkt（vw）なので、国の中の選別だけを比べている。',
        '国の分類は2026年の MSCI（時点ごとの分類ではない）。新興国の時価加重の市場は少数の巨大株に偏る国がある（台湾・韓国など）。業種の中も時価加重なので同じ偏りを持つ。',
        '費用は回転1あたり0.2%（r4）。新興国の業種ETFは少なく、実際に国ごと・部門ごとに持つ手段は乏しい（実行の費用はこれより高い可能性）。税は入れていない。',
        '国は等加重（主の系列）。国の数は月で変わる（新しく数えられる国が入る）。',
        'JKP の GICS の割り当てが各時点の分類か（後から付けた今の分類を過去へ当てていないか）は確かめていない。後の分類を過去へ当てていれば、業種の中身に少しの後知恵が入る。',
        '業種の勢いは各国で互いに相関する（世界の同じ部門が同時に勝つ）ので、40か国は40の独立な試行ではない。t は国をならした一本の月次系列で出しており、国の間の相関はその中に入っている。',
        f'持っている業種の月 m の行が無い（銘柄数が10社を割った）月は凍結した規則どおり総リターン0と置いた。2001年以降の件数: {sum(p["missing_held_industry_months_2001"] for p in per.values())}。',
    ]
    doc = {
        'key': KEY, 'test': 'C6_indmom_world', 'generated': datetime.date.today().isoformat(),
        'prereg': 'out/edge_prereg_r4.json', 'prereg_base': 'out/edge_prereg.json',
        'frozen_rule': {'spec_file': 'out/edge/spec_indmom.json', 'spec': FROZEN, 'frozen': SPEC_DOC.get('frozen'),
                        'code': 'night/edge/fam_indmom.py の signal()・weights() をそのまま呼ぶ（k だけ r4 の写し方で国・月ごとに入れる）',
                        'spec_commit': _git_last('out/edge/spec_indmom.json'), 'code_commit': _git_last('night/edge/fam_indmom.py')},
        'mapping_decisions': DECISIONS,
        'cost_per_turnover': COST, 'countries_not_available': missing,
        'verdict': v,
        'verdict_rule': 'r4: 2001-01〜・費用後・国をならした月次超過（算術・年率）が正で t ≥ 2.0、かつ 6割以上の国で超過が正。4つの確認の中で Holm（α=0.05）',
        'risk': _risk(main_s['全体']['ew_stats_2001']),
        'pooled_excess': main_s['全体']['pooled_excess_arith_pct_yr'], 'pooled_t': main_s['全体']['pooled_t'],
        'positive': main_s['全体']['positive'],
        'holm_note': {'p_one_sided': main_s['全体']['p_one_sided'],
                      'K4_thresholds': [round(ALPHA / (K_TESTS - i), 4) for i in range(K_TESTS)],
                      'note': '最終の Holm は4つの確認をそろえて掛ける（ここでは他の3つの p を見ていない）'},
        'summary_main': main_s,
        'per_country': per,
        'reference_not_verdict': ref,
        'lookahead_test': la,
        'data_notes': notes,
    }
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    s = main_s['全体']
    print(f"■ {KEY}: {v}  ならし {s['pooled_excess_arith_pct_yr']}%/年 (t {s['pooled_t']})  正 {s['positive']}  "
          f"EW 年率 {s['ew_stats_2001']['cagr']} vs {s['ew_stats_2001']['bench_cagr']}")
    for g in ('先進国', '新興国'):
        x = main_s[g]
        print(f"   {g}: ならし {x['pooled_excess_arith_pct_yr']}%/年 (t {x['pooled_t']})  正 {x['positive']}")
    for c, p in per.items():
        hd = p['holdout'] or {}
        print(f"   {c} {p['group']} {hd.get('from')}-{hd.get('to')} 超過 {hd.get('excess_geo_pct_yr')} (t {hd.get('t')}) 数えた月 {p['months_2001_counted']} "
              f"下限割れ {p['months_2001_below_floor']} 業種不足 {p['months_2001_few_industries_or_no_signal']} N {p['industries_ranked_median']} k {p['k_median']}")
    for kx, vv in ref.items():
        if isinstance(vv, dict) and '全体' in vv and vv['全体']:
            print('  参考', kx, vv['全体']['pooled_excess_arith_pct_yr'], vv['全体']['pooled_t'], vv['全体']['positive'])
        else:
            print('  参考', kx, vv)


def _risk(hd):
    """事前登録（第1回）のリスクの区分: ぶれ ≤ 相手×1.1 かつ 最大下落 ≤ 相手＋5pt なら『同じリスクで』"""
    if not hd:
        return None
    same = hd['vol'] <= hd['bench_vol'] * 1.1 and hd['maxdd'] >= hd['bench_maxdd'] - 5
    return ('同じリスクで' if same else 'リスクを増やして') + f"（ぶれ {hd['vol']}% vs {hd['bench_vol']}%・最大下落 {hd['maxdd']}% vs {hd['bench_maxdd']}%）"


def _git_last(path):
    try:
        return subprocess.run(['git', '-C', BASE, 'log', '-1', '--format=%h %cI', '--', path], capture_output=True, text=True, timeout=30).stdout.strip() or None
    except Exception:
        return None


if __name__ == '__main__':
    main()
