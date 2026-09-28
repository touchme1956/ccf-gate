#!/usr/bin/env python3
"""night/edge/fam_macro.py — 系統 macro「景気の信号で降りる」（事前登録 out/edge_prereg.json・第1回）

  規則の形: 月末に、景気の信号（失業率の趨勢・鉱工業生産・雇用者数・逆イールド・信用スプレッド・利上げ・物価の加速）と
  価格の趨勢（10か月平均）を見て、翌月の米国株の持ち高（0〜2倍）を決める。降りた分は短期金利（rf）。
  相手は Ken French の米国市場（CRSP 全上場の時価加重・配当込み）。費用は片道の回転1あたり 0.10%。

  ■ 先読みの禁止（コードで守る）
    ・月 m のリターンの持ち高は、市場のデータ（価格・金利の月平均）は m−1 月末まで、
      発表の遅れる統計（UNRATE・PAYEMS・INDPRO・CPIAUCSL）は m−2 月の値まで で作る（lag=2 が既定）。
      UNRATE・PAYEMS は翌月の第1金曜、INDPRO・CPI は翌月の中旬に出るので、m−1 月末には m−2 月の値が手に入る。
    ・lookahead_test() が「m−1 月より後の値（統計は m−2 月より後）をでたらめに変えても、過去の持ち高が1つも変わらない」ことを確かめる。
      わざと lag=0 にした規則が検査に落ちること（検査に効き目があること）も確かめる。
  ■ 限界
    ・FRED の値は改定後（当時の速報ではない）。雇用者数・鉱工業生産は改定が大きい。失業率は季節調整の改定が主で小さい。
    ・金利（GS10・TB3MS・BAA・AAA）は月平均。m−1 月の平均は m−1 月末の引けでほぼ確定するとして lag=1 を既定にした。

  使い方: python3 night/edge/fam_macro.py            → 全変種を選定期間（〜2000-12）で測って表を出す（保存しない）
          python3 night/edge/fam_macro.py --freeze   → 事前登録の選び方で一つ選び、out/edge/spec_macro.json に凍結
          python3 night/edge/fam_macro.py --test     → 先読みの検査だけ
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h                                                    # noqa: E402
import math, random, json, statistics as S                              # noqa: E402

FAMILY = {
    'key': 'macro',
    'name': '景気の信号で降りる（失業率の趨勢 × 価格の趨勢 ほか）',
    'implement': ('月末に1回だけ判断する。米国株の持ち高は 楽天証券の特定口座で VTI（または VOO／eMAXIS Slim 米国株式・楽天・全米株式）、'
                  '降りる先は 米ドルMMF・短期米国債ETF（BIL／SHV）・円の現金。'
                  '判断に使う数字は FRED で無料で見られる（UNRATE＝毎月第1金曜の雇用統計・その他）。'
                  'NISA 成長投資枠でも持てるが、降りるたびに売ると年の買付枠（240万円）を再び使うので、切替は特定口座が向く（売却益に約20.3%の税）。'
                  '持ち高1倍を超える変種は SSO（2倍・毎日リセット）を VOO と混ぜて作る＝NISA 不可・特定口座のみ。'),
}
COST = 0.001                     # 事前登録: 指数・ETF の入れ替えは片道の回転100%につき 0.10%
STATS_LAG = 2                    # 発表の遅れる統計の既定の遅れ（m−2 月の値まで）
MKT_LAG = 1                      # 市場の金利の既定の遅れ（m−1 月の月平均）
COMMON = (195601, 200012)        # 変種を同じ窓で比べるための共通の窓（全信号が定義される月から）
STAT_SERIES = ('UNRATE', 'INDPRO', 'PAYEMS', 'CPIAUCSL')
MKT_SERIES = ('GS10', 'TB3MS', 'BAA', 'AAA')


# ───────────────────────── データ ─────────────────────────
def load(need_daily=False):
    mk, rf = h.us_market()
    D = {'mk': mk, 'rf': rf}
    for s in STAT_SERIES + MKT_SERIES:
        D[s] = h.fred(s)
    if need_daily:
        dmk, drf = h.us_market_daily()
        D['dmk'], D['drf'] = dmk, drf
    return D


def _tr(mk):
    """月末の累積トータルリターン指数"""
    out, v = {}, 1.0
    for m in sorted(mk):
        v *= 1 + mk[m]
        out[m] = v
    return out


def _vals(ser, x, n):
    """x を含む直近 n か月の値（欠けがあれば None）"""
    out = []
    for k in range(n):
        v = ser.get(h.add_months(x, -k))
        if v is None:
            return None
        out.append(v)
    return out


# ───────────────────────── 信号（True＝悪い・False＝良い・None＝判定不能） ─────────────────────────
def sig_bad(sg, m, D, cache):
    s = sg['s']
    if s in ('sma', 'mom'):                                   # 価格の趨勢: m−1 月末まで
        tr = cache.setdefault('tr', _tr(D['mk']))
        p = h.add_months(m, -sg.get('lag', 1))
        if s == 'sma':
            v = _vals(tr, p, sg.get('n', 10))
            return None if v is None else tr[p] < S.mean(v)
        n = sg.get('n', 12)
        a = tr.get(h.add_months(p, -n))
        if a is None or p not in tr:
            return None
        rfs = _vals(D['rf'], p, n)
        if rfs is None:
            return None
        return tr[p] / a < math.prod(1 + r for r in rfs)
    lag = sg.get('lag', STATS_LAG if s in ('u_ma', 'sahm', 'ip_yoy', 'ip_ma', 'pay_yoy', 'pay_ma', 'cpi_acc') else MKT_LAG)
    x = h.add_months(m, -lag)
    if s == 'u_ma':                                           # 失業率がその n か月平均より上
        v = _vals(D['UNRATE'], x, sg.get('n', 12))
        return None if v is None else v[0] > S.mean(v)
    if s == 'sahm':                                           # サーム: 3か月平均が直前12か月の最低から th 以上上
        u = D['UNRATE']
        s3 = lambda z: (lambda w: None if w is None else S.mean(w))(_vals(u, z, 3))
        cur = s3(x)
        prev = [s3(h.add_months(x, -k)) for k in range(1, 13)]
        if cur is None or any(p is None for p in prev):
            return None
        return cur - min(prev) >= sg.get('th', 0.5)
    if s in ('ip_yoy', 'pay_yoy'):                            # 前年同月比がマイナス
        ser = D['INDPRO' if s == 'ip_yoy' else 'PAYEMS']
        a, b = ser.get(x), ser.get(h.add_months(x, -12))
        return None if a is None or b is None else a / b - 1 < 0
    if s in ('ip_ma', 'pay_ma'):                              # その n か月平均より下
        ser = D['INDPRO' if s == 'ip_ma' else 'PAYEMS']
        v = _vals(ser, x, sg.get('n', 12))
        return None if v is None else v[0] < S.mean(v)
    if s == 'yc_inv':                                         # 直近 k か月のどこかで 10年債 < 3か月物（逆イールド）
        k = sg.get('k', 1)
        out = False
        for j in range(k):
            y = h.add_months(x, -j)
            a, b = D['GS10'].get(y), D['TB3MS'].get(y)
            if a is None or b is None:
                return None
            out = out or (a - b < 0)
        return out
    if s == 'cs_ma':                                          # 信用スプレッド（BAA−AAA）がその n か月平均より上＝広がっている
        n = sg.get('n', 12)
        v = []
        for j in range(n):
            y = h.add_months(x, -j)
            a, b = D['BAA'].get(y), D['AAA'].get(y)
            if a is None or b is None:
                return None
            v.append(a - b)
        return v[0] > S.mean(v)
    if s == 'tb_up':                                          # 3か月物が n か月前より高い＝利上げの局面
        a, b = D['TB3MS'].get(x), D['TB3MS'].get(h.add_months(x, -sg.get('n', 12)))
        return None if a is None or b is None else a > b
    if s == 'cpi_acc':                                        # 物価の前年比が1年前より高い＝インフレの加速
        c = D['CPIAUCSL']
        g = lambda z: (lambda a, b: None if a is None or b is None else a / b - 1)(c.get(z), c.get(h.add_months(z, -12)))
        a, b = g(x), g(h.add_months(x, -12))
        return None if a is None or b is None else a > b
    raise ValueError(f'未知の信号 {s}')


def exposure(spec, m, D, cache):
    """月 m の米国株の持ち高（0〜2倍）。判定不能なら None"""
    mode = spec['mode']
    macro = spec.get('macro') or []
    price = spec.get('price')
    mb = [sig_bad(sg, m, D, cache) for sg in macro]
    if any(b is None for b in mb):
        return None
    pb = sig_bad(price, m, D, cache) if price else None
    if price and pb is None:
        return None
    ex = spec.get('exp', {})
    good, one, both = ex.get('good', 1.0), ex.get('one', 1.0), ex.get('both', 0.0)
    if mode == 'score':                                        # 悪い信号の割合だけ降りる
        flags = mb + ([pb] if price else [])
        return 1.0 - sum(flags) / len(flags)
    macro_bad = sum(mb) >= spec.get('need', 1) if macro else False
    if mode == 'macro_only':
        return both if macro_bad else good
    if mode == 'price_only':
        return both if pb else good
    if mode == 'and':                                          # 景気と価格の両方が悪いときだけ降りる
        if macro_bad and pb:
            return both
        return one if (macro_bad or pb) else good
    raise ValueError(mode)


def assemble(spec, D):
    """→ ret（費用の前）, turnover, exposure の月次"""
    cache = {}
    E = {}
    for m in sorted(D['mk']):
        e = exposure(spec, m, D, cache)
        if e is not None:
            E[m] = e
    need_lev = any(e > 1 for e in E.values())
    lev2 = {}
    if need_lev:
        d2 = h.lev_daily(D['dmk'], D['drf'], 2.0)                  # SSO 型: 毎日リセット・借入 rf+0.4%・経費 0.9%
        lev2 = h.to_monthly(d2)
    ret, tov = {}, {}
    prev_w = None
    for m in sorted(E):
        e = E[m]
        if e <= 1:
            w = (e, 0.0, 1.0 - e)                                  # (1倍の株, 2倍の株, 短期金利)
        else:
            w = (2.0 - e, e - 1.0, 0.0)
        if w[1] > 0 and m not in lev2:
            continue
        r = (D['mk'][m], lev2.get(m, 0.0), D['rf'].get(m, 0.0))
        ret[m] = sum(wi * ri for wi, ri in zip(w, r))
        tov[m] = 0.0 if prev_w is None else sum(abs(a - b) for a, b in zip(w, prev_w)) / 2
        v = [wi * (1 + ri) for wi, ri in zip(w, r)]              # 月中の値動きで比率がずれる（次の月初に直す）
        tot = sum(v)
        prev_w = tuple(x / tot for x in v) if tot > 0 else w
    return ret, tov, E


def run(spec):
    D = load(need_daily=spec.get('lev', False))
    ret, tov, _ = assemble(spec, D)
    mk, rf = D['mk'], D['rf']
    return {'ret': ret, 'bench': {m: mk[m] for m in ret}, 'rf': {m: rf.get(m, 0.0) for m in ret},
            'turnover': tov, 'cost': COST, 'markets': {}}


# ───────────────────────── 変種（結果を見る前に全部ここに書いた・上限40） ─────────────────────────
U = {'s': 'u_ma', 'n': 12}
PX = {'s': 'sma', 'n': 10}
IPY, IPM = {'s': 'ip_yoy'}, {'s': 'ip_ma', 'n': 12}
PAYY, PAYM = {'s': 'pay_yoy'}, {'s': 'pay_ma', 'n': 12}
SAHM = {'s': 'sahm', 'th': 0.5}
YC1, YC12, YC24 = {'s': 'yc_inv', 'k': 1}, {'s': 'yc_inv', 'k': 12}, {'s': 'yc_inv', 'k': 24}
CS = {'s': 'cs_ma', 'n': 12}
TBU = {'s': 'tb_up', 'n': 12}
CPIA = {'s': 'cpi_acc'}

VARIANTS = [
    # 失業率（GTT の核）
    ('V01 失業率>12か月平均で降りる', {'mode': 'macro_only', 'macro': [U]}, True),
    ('V02 GTT: 失業率>12か月平均 ∧ 価格<10か月平均', {'mode': 'and', 'macro': [U], 'price': PX}, True),
    ('V03 GTT(勢い): 失業率>12か月平均 ∧ 12か月の勢い<短期金利', {'mode': 'and', 'macro': [U], 'price': {'s': 'mom', 'n': 12}}, True),
    ('V04 サーム0.5で降りる', {'mode': 'macro_only', 'macro': [SAHM]}, True),
    ('V05 サーム0.5 ∧ 価格<10か月平均', {'mode': 'and', 'macro': [SAHM], 'price': PX}, True),
    # 鉱工業生産
    ('V06 鉱工業生産の前年比<0で降りる', {'mode': 'macro_only', 'macro': [IPY]}, True),
    ('V07 鉱工業生産の前年比<0 ∧ 価格<10か月平均', {'mode': 'and', 'macro': [IPY], 'price': PX}, True),
    ('V08 鉱工業生産<12か月平均 ∧ 価格<10か月平均', {'mode': 'and', 'macro': [IPM], 'price': PX}, True),
    # 雇用者数
    ('V09 雇用者数の前年比<0で降りる', {'mode': 'macro_only', 'macro': [PAYY]}, True),
    ('V10 雇用者数の前年比<0 ∧ 価格<10か月平均', {'mode': 'and', 'macro': [PAYY], 'price': PX}, True),
    # 実体の合成
    ('V11 {失業率↑・生産の前年比<0・雇用の前年比<0}の2つ以上で降りる', {'mode': 'macro_only', 'macro': [U, IPY, PAYY], 'need': 2}, True),
    ('V12 同2つ以上 ∧ 価格<10か月平均', {'mode': 'and', 'macro': [U, IPY, PAYY], 'need': 2, 'price': PX}, True),
    ('V13 {失業率・生産・雇用が12か月平均より悪い}のどれか ∧ 価格<10か月平均', {'mode': 'and', 'macro': [U, IPM, PAYM], 'need': 1, 'price': PX}, True),
    # 逆イールド
    ('V14 逆イールドの間は降りる', {'mode': 'macro_only', 'macro': [YC1]}, True),
    ('V15 直近12か月に逆イールドがあれば降りる', {'mode': 'macro_only', 'macro': [YC12]}, True),
    ('V16 直近24か月に逆イールド ∧ 価格<10か月平均', {'mode': 'and', 'macro': [YC24], 'price': PX}, True),
    ('V17 直近24か月に逆イールド ∧ 失業率>12か月平均', {'mode': 'macro_only', 'macro': [YC24, U], 'need': 2}, True),
    # 信用スプレッド
    ('V18 信用スプレッド(BAA−AAA)>12か月平均 ∧ 価格<10か月平均', {'mode': 'and', 'macro': [CS], 'price': PX}, True),
    ('V19 信用スプレッド>12か月平均で降りる', {'mode': 'macro_only', 'macro': [CS]}, True),
    # 金融引き締め・物価
    ('V20 3か月物が1年前より高い ∧ 価格<10か月平均', {'mode': 'and', 'macro': [TBU], 'price': PX}, True),
    ('V21 物価の前年比が加速 ∧ 価格<10か月平均', {'mode': 'and', 'macro': [CPIA], 'price': PX}, True),
    # 段階的に降りる（レバレッジなし）
    ('V22 失業率↑で半分・価格↓で半分降りる', {'mode': 'and', 'macro': [U], 'price': PX, 'exp': {'good': 1.0, 'one': 0.5, 'both': 0.0}}, True),
    ('V23 {失業率・生産・逆イールド12・価格}の悪い割合だけ降りる', {'mode': 'score', 'macro': [U, IPY, YC12], 'price': PX}, True),
    # 良い局面だけ借りて持つ（リスクを増やす）
    ('V24 GTT＋両方良いとき1.5倍', {'mode': 'and', 'macro': [U], 'price': PX, 'exp': {'good': 1.5, 'one': 1.0, 'both': 0.0}, 'lev': True}, True),
    ('V25 GTT＋両方良いとき2倍', {'mode': 'and', 'macro': [U], 'price': PX, 'exp': {'good': 2.0, 'one': 1.0, 'both': 0.0}, 'lev': True}, True),
    ('V26 GTT＋両方良いとき1.25倍', {'mode': 'and', 'macro': [U], 'price': PX, 'exp': {'good': 1.25, 'one': 1.0, 'both': 0.0}, 'lev': True}, True),
    # GTT の目盛りの感度（同じ考えの別の目盛り）
    ('V27 GTT(失業率は6か月平均)', {'mode': 'and', 'macro': [{'s': 'u_ma', 'n': 6}], 'price': PX}, True),
    ('V28 GTT(価格は12か月平均)', {'mode': 'and', 'macro': [U], 'price': {'s': 'sma', 'n': 12}}, True),
    ('V29 GTT(失業率の遅れ3か月＝より保守的)', {'mode': 'and', 'macro': [{'s': 'u_ma', 'n': 12, 'lag': 3}], 'price': PX}, True),
    # 合わせ技
    ('V30 価格<10か月平均 ∧ (失業率↑ か 直近12か月に逆イールド)', {'mode': 'and', 'macro': [U, YC12], 'need': 1, 'price': PX}, True),
    ('V31 価格<10か月平均 ∧ (失業率↑・生産↓・雇用↓・逆イールド12・信用↑ のどれか)', {'mode': 'and', 'macro': [U, IPY, PAYY, YC12, CS], 'need': 1, 'price': PX}, True),
    ('V32 GTT＋両方良く かつ 直近12か月に逆イールド無しのとき1.5倍', None, True),     # 下で組む
    # 参照（この系統の規則ではない＝選ばない）
    ('R1 参照: 価格<10か月平均だけで降りる（trend 系統の規則）', {'mode': 'price_only', 'price': PX}, False),
    ('R2 参照: いつも1.5倍（借りるだけ・時機なし）', {'mode': 'macro_only', 'macro': [], 'exp': {'good': 1.5}, 'lev': True}, False),
]


def exposure_v32(m, D, cache):
    """V32: GTT に逆イールドの警報を足して、景気・価格・曲線の3つとも良いときだけ 1.5 倍"""
    u = sig_bad(U, m, D, cache); p = sig_bad(PX, m, D, cache); y = sig_bad(YC12, m, D, cache)
    if None in (u, p, y):
        return None
    if u and p:
        return 0.0
    if not u and not p and not y:
        return 1.5
    return 1.0


_orig_exposure = exposure


def exposure(spec, m, D, cache):                                   # noqa: F811
    if spec.get('mode') == 'v32':
        return exposure_v32(m, D, cache)
    return _orig_exposure(spec, m, D, cache)


VARIANTS = [(n, ({'mode': 'v32', 'lev': True} if s is None else s), ok) for n, s, ok in VARIANTS]


# ───────────────────────── 先読みの検査 ─────────────────────────
def _perturb(D, c_mkt, c_stat, seed):
    """市場の系列は c_mkt より後、統計は c_stat より後の値をでたらめに変える（日次は月で判定）"""
    rnd = random.Random(seed)
    P = {}
    for k, ser in D.items():
        lim = c_stat if k in STAT_SERIES else c_mkt
        out = {}
        for d, v in ser.items():
            mm = d // 100 if d > 999999 else d
            if mm <= lim:
                out[d] = v
            elif k in ('mk', 'rf', 'dmk', 'drf'):                 # リターン: ±30% を足す
                out[d] = v + rnd.uniform(-0.3, 0.3)
            else:                                                  # 水準: 0.3〜1.7 倍
                out[d] = v * rnd.uniform(0.3, 1.7)
        P[k] = out
    return P


def lookahead_test(specs=None, cuts=(195712, 196305, 196911, 197403, 197708, 198006, 198407, 198710, 199012, 199403, 199808, 200009), verbose=True):
    """月 c+1 の持ち高は、市場は c 月末まで・統計は c−1 月まで しか使わないことを確かめる。
    c より後（統計は c−1 より後）の値を乱しても、m ≤ c+1 の持ち高が1つでも変われば先読み。
    わざと先読みさせた規則（失業率 lag=0・lag=1、価格を当月まで）が落ちることも確かめる"""
    D = load(need_daily=True)
    specs = specs or [s for _, s, _ in VARIANTS]
    bad = 0
    for spec in specs:
        for i, c in enumerate(cuts):
            E0 = {}
            cache = {}
            for m in sorted(D['mk']):
                e = exposure(spec, m, D, cache)
                if e is not None:
                    E0[m] = e
            P = _perturb(D, c, h.add_months(c, -1), seed=1000 + i)
            E1 = {}
            cache = {}
            for m in sorted(P['mk']):
                if m > h.add_months(c, 1):
                    break
                e = exposure(spec, m, P, cache)
                if e is not None:
                    E1[m] = e
            diff = [m for m in E1 if m in E0 and abs(E0[m] - E1[m]) > 1e-12]
            if diff:
                bad += 1
                if verbose:
                    print('✗ 先読み', spec, c, diff[:3])
    # 効き目の確認（陰性対照）: わざと先読みする規則は落ちなければならない
    cheats = [{'mode': 'and', 'macro': [{'s': 'u_ma', 'n': 12, 'lag': 0}], 'price': PX},
              {'mode': 'and', 'macro': [{'s': 'u_ma', 'n': 12, 'lag': 1}], 'price': PX},
              {'mode': 'macro_only', 'macro': [{'s': 'ip_yoy', 'lag': 1}]},
              {'mode': 'macro_only', 'macro': [{'s': 'yc_inv', 'k': 1, 'lag': 0}]}]
    caught = 0
    for spec in cheats:
        hit = False
        for i, c in enumerate(cuts):
            cache = {}
            E0 = {m: exposure(spec, m, D, cache) for m in sorted(D['mk']) if m <= h.add_months(c, 1)}
            P = _perturb(D, c, h.add_months(c, -1), seed=2000 + i)
            cache = {}
            E1 = {m: exposure(spec, m, P, cache) for m in sorted(P['mk']) if m <= h.add_months(c, 1)}
            if any(E0[m] is not None and E1.get(m) is not None and abs(E0[m] - E1[m]) > 1e-12 for m in E0):
                hit = True
        caught += hit
    # 切り捨ての検査: データを c 月（統計は c−1 月）で切っても m ≤ c+1 の持ち高が同じ
    trunc_bad = 0
    for spec in specs:
        cache = {}
        E0 = {m: exposure(spec, m, D, cache) for m in sorted(D['mk'])}
        for c in cuts:
            T = {k: {d: v for d, v in ser.items() if (d // 100 if d > 999999 else d) <= (h.add_months(c, -1) if k in STAT_SERIES else c)}
                 for k, ser in D.items()}
            T['mk'] = {m: v for m, v in D['mk'].items() if m <= h.add_months(c, 1)}   # リターンの月の並びだけは c+1 まで（値は使わない）
            T['mk'][h.add_months(c, 1)] = 0.0
            cache = {}
            for m in sorted(T['mk']):
                e = exposure(spec, m, T, cache)
                if (e is None) != (E0.get(m) is None) or (e is not None and abs(e - E0[m]) > 1e-12):
                    trunc_bad += 1
                    if verbose:
                        print('✗ 切り捨てで変わった', spec, c, m, e, E0.get(m))
                    break
    # 価格を当月の引けまで使う先読み（lag=0）の陰性対照
    hit = False
    spec = {'mode': 'price_only', 'price': {'s': 'sma', 'n': 10, 'lag': 0}}
    for i, c in enumerate(cuts):
        cache = {}
        E0 = {m: exposure(spec, m, D, cache) for m in sorted(D['mk']) if m <= h.add_months(c, 1)}
        P = _perturb(D, c, h.add_months(c, -1), seed=3000 + i)
        cache = {}
        E1 = {m: exposure(spec, m, P, cache) for m in sorted(P['mk']) if m <= h.add_months(c, 1)}
        hit = hit or any(E0[m] is not None and E1.get(m) is not None and abs(E0[m] - E1[m]) > 1e-12 for m in E0)
    res = {'specs_checked': len(specs), 'cuts': list(cuts), 'perturb_violations': bad, 'truncate_violations': trunc_bad,
           'negative_controls': f'{caught + hit}/{len(cheats) + 1} の先読み規則（統計 lag0・lag1・生産 lag1・金利 lag0・価格 lag0）を検出'}
    if verbose:
        print('先読みの検査:', res)
    return res


# ───────────────────────── 選定 ─────────────────────────
def measure_all(verbose=True):
    assert h.PHASE == 'select', '選定は EDGE_PHASE=select（既定）でだけ行う'
    D = load(need_daily=True)
    rows = []
    for name, spec, ok in VARIANTS:
        ret, tov, E = assemble(spec, D)
        bench = {m: D['mk'][m] for m in ret}
        full = h.stats(ret, bench, D['rf'], turnover=tov, cost=COST)
        com = h.stats(ret, bench, D['rf'], a=COMMON[0], b=COMMON[1], turnover=tov, cost=COST)
        ms = [m for m in ret if COMMON[0] <= m <= COMMON[1]]
        avg_e = S.mean(E[m] for m in ms) if ms else None
        out_share = sum(1 for m in ms if E[m] == 0) / len(ms) if ms else None
        yr_tov = sum(tov[m] for m in ms) / (len(ms) / 12) if ms else None
        rows.append({'name': name, 'spec': spec, 'eligible': ok, 'common': com, 'full': full,
                     'avg_exposure': round(avg_e, 3) if avg_e is not None else None,
                     'out_share': round(out_share, 3) if out_share is not None else None,
                     'turnover_per_year': round(yr_tov, 2) if yr_tov is not None else None})
        if verbose:
            c, f = com or {}, full or {}
            print(f"{name[:52]:52} 共通 {c.get('cagr')}/{c.get('bench_cagr')} 超過{c.get('excess')!s:>6} t{c.get('t')!s:>5} NW{c.get('t_nw')!s:>5} "
                  f"ぶれ{c.get('vol')}/{c.get('bench_vol')} DD{c.get('maxdd')}/{c.get('bench_maxdd')} 10年{c.get('roll10_win')} | "
                  f"全 {f.get('from')} 超過{f.get('excess')!s:>6} t{f.get('t')!s:>5} | 平均持ち高{rows[-1]['avg_exposure']} 降り{rows[-1]['out_share']} 回転{rows[-1]['turnover_per_year']}/年")
    return rows


# 選定の後に測った頑健性の確認（選ぶ対象ではない・試した数には数える）
DIAGNOSTICS = [
    ('D1 確認: V14 の金利を m−2 月の月平均にする（1か月遅らせる）', {'mode': 'macro_only', 'macro': [{'s': 'yc_inv', 'k': 1, 'lag': 2}]}),
]


def choose(rows):
    """事前登録の選び方: 共通の窓（COMMON）で 費用後の超過 ≥ +1%/年 の変種のうち t が最大。
    ⚠ 窓をそろえるのは、変種ごとにデータの始まりが違い（生産・信用は1927〜・失業率は1949〜・逆イールドは1953〜）、
      大恐慌を含むかどうかで t が変わるのを避けるため（結果を見る前にコードに書いた）"""
    ok = [r for r in rows if r['eligible'] and r['common'] and r['common']['excess'] >= 1.0]
    if ok:
        return max(ok, key=lambda r: r['common']['t']), True
    el = [r for r in rows if r['eligible'] and r['common']]
    return max(el, key=lambda r: r['common']['t']), False


def freeze():
    assert h.PHASE == 'select'
    la = lookahead_test(verbose=False)
    assert la['perturb_violations'] == 0 and la['truncate_violations'] == 0, la
    rows = measure_all(verbose=False)
    D = load(need_daily=False)
    diag = []
    for name, spec in DIAGNOSTICS:
        ret, tov, _ = assemble(spec, D)
        b = {m: D['mk'][m] for m in ret}
        diag.append({'name': name, 'common': h.stats(ret, b, D['rf'], a=COMMON[0], b=COMMON[1], turnover=tov, cost=COST),
                     'full': h.stats(ret, b, D['rf'], turnover=tov, cost=COST)})
    best, reached = choose(rows)
    spec = best['spec']
    r = run(spec)
    sel = h.stats(r['ret'], r['bench'], r['rf'], turnover=r['turnover'], cost=r['cost'])
    return rows, diag, best, reached, sel, la


if __name__ == '__main__':
    assert h.PHASE == 'select', 'このスクリプトは選定の段（EDGE_PHASE=select）専用'
    if '--test' in sys.argv:
        lookahead_test()
        sys.exit(0)
    rows = measure_all()
    json.dump(rows, open(os.path.join(os.environ.get('EDGE_SCRATCH', '/tmp'), 'macro_variants.json'), 'w'), ensure_ascii=False, indent=1)
