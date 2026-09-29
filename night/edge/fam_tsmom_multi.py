#!/usr/bin/env python3
"""night/edge/fam_tsmom_multi.py — 系統 tsmom_multi（第3回）: 手に入る資産の時系列の勢い（多資産・逆ぶれ加重・株のぶれまで借りる）

事前登録 out/edge_prereg.json の決まりで作る。読むだけ・門の採点に不使用。
  資産: 米国株（French 市場）・米国外株（French 国別・米ドル建ての等加重・1975〜）・米10年債（Shiller GS10 から作る）・短期金利（French RF）
  規則: 各資産の過去の勢い（短期金利との比較）が正なら持ち、負なら短期金利。持つ資産の重みは直近のぶれの逆数、
        全体を米国株の直近のぶれまで借りる（上限2倍・借りた分に 短期金利＋0.4%/年・レバレッジ型ETFの経費 0.9%/年）。月次。
  相手: 米国株100%（French 市場）。費用: 片道の回転1あたり 0.10%。他の市場での再現は無し。
  凍結した主の規則（out/edge/spec_tsmom_multi.json）は weight='eq'（持つ資産を等分）・12か月・ぶれ12か月・H。
  ⚠ 選定期間（1954-06〜2000-12）では24の変種すべてが米国株に負けた（+1%/年 に届いた変種は0）——詳しくは spec の rationale。
  ⚠ Shiller GS10 の 1953-03 以前は毎年1月の値の直線補間（月次のぶれ 0.5%/年 の作り物）なので債券は 1953-04 以降だけを使う。

★先読みの禁止: 月 m の重みは m−1 月末までの系列だけで作る（_weights は m より前のキーしか読まない）。
  ⚠ 債券は Shiller の GS10（1953年以降は FRED GS10＝日々の利回りの**月平均**）から作るので、平均どうしの差は
  ランダムウォークでも1か月ずれの自己相関 +0.25 を持つ（Working 1960）。これは本物の勢いではなく平均の作り物なので、
  債券の勢いと ぶれ は **1か月空けて**（m−2 月末まで）測る（bond_skip=1）。
"""
import sys, os, math, statistics as S
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h  # noqa: E402

FAMILY = {
    'key': 'tsmom_multi',
    'name': '多資産の時系列の勢い（米国株・米国外株・米10年債⇄短期金利・逆ぶれ加重・株のぶれまで借りる）',
    'implement': ('楽天証券の特定口座（課税）で月末に一度だけ売買する。米国株＝VTI、米国外株＝VEA（または VXUS・EFA）、'
                  '米10年債＝IEF、短期金利＝米ドルMMF か SHV。各資産の過去12か月のリターンが同じ期間の短期金利を上回れば持ち、'
                  '下回ればその枠を MMF へ。持つ資産は直近のぶれの逆数で割り振り、全体のぶれを米国株の直近のぶれまで借りる（最大2倍）。'
                  '借りる部分は楽天の米国株信用取引（委託保証金の約2倍まで）か、米国株の枠だけなら SSO（2倍・楽天で取扱あり）で代用する'
                  '——2倍の米国債・米国外株のETF（UST・UBT・EFO）は楽天の海外ETF一覧に無い。'
                  '⚠ NISA 不可（信用取引も レバレッジ型も NISA の対象外）。模型の借入費用（短期金利＋0.4%＋経費0.9%）は信用取引の実際の金利より低い時期がある。'),
}

DEFAULT_SPEC = {
    'lookback': '12',        # '12'＝過去12か月の超過 / '6_12'＝6か月と12か月の二つの信号の平均（0・0.5・1）
    'vol_win': 36,           # ぶれを測る月数（月次リターンの標準偏差×√12）
    'scheme': 'H',           # 'H'＝持つ資産だけで逆ぶれ加重→全体を株のぶれまで借りる / 'S1'＝全資産の枠（持たない枠は現金）で、借りる倍率は全資産を持った姿で決める / 'S2'＝枠のまま、今持つ姿で倍率を決める
    'cap': 2.0,              # 借りる上限（総エクスポージャーの倍率）
    'borrow_spread': 0.004,  # 借りた分に 短期金利＋この値（年率）
    'lev_fee': 0.009,        # 借りた分に掛かる レバレッジ型ETFの経費（年率・事前登録 costs どおり）
    'bond_skip': 1,          # 債券の勢い・ぶれを何か月空けて測るか（月平均の利回りの作り物の自己相関を避ける）
    'nonus': True,           # 米国外株を使う（1975〜・データが揃ってから）
    'weight': 'inv',         # 'inv'＝持つ資産を直近のぶれの逆数で / 'eq'＝持つ資産を等分（推定誤差に強い 1/N・DeMiguel ほか 2009）
    'bond_src': 'shiller',   # 'shiller'＝Shiller GS10（1953-04〜は FRED GS10＝日々の月平均）＋最後の月の後を FRED GS10 で継ぐ（主）/ 'dgs10_me'＝FRED DGS10 の月末の利回り（1962〜・診断用）
    'require': ['us', 'bond'],  # この資産が全部測れる月から始める（多資産の規則として評価する。米国外は揃ってから加わる）
    'cost': 0.001,           # 片道の回転1あたり（事前登録: 指数・ETF 0.10%）
}


# ───────────────────────── 資産の系列 ─────────────────────────
def _bond_price(c, y, T):
    """年2回利払い・クーポン c・残存 T 年の債券を利回り y で評価（額面1）"""
    n = 2 * T
    if abs(y) < 1e-9:
        return c / 2 * n + 1
    v = (1 + y / 2) ** (-n)
    return c / y * (1 - v) + v


def bond_yields():
    """{YYYYMM: 利回り(小数)}。Shiller GS10 を正とし、Shiller の最後の月より後だけ FRED GS10（同じ定義）で継ぐ"""
    y = {x['m']: x['GS10'] / 100 for x in h.shiller() if x.get('GS10') is not None}
    if y:
        last = max(y)
        try:
            fr = h.fred('GS10')
        except Exception:
            fr = {}
        for m, v in fr.items():
            if m > last:
                y[m] = v / 100
    return y


def _interp_run_end(y):
    """Shiller の GS10 は 1953-04 より前が『毎年1月の値の直線補間』（月次の動きが作り物）。
    二階差がほぼ0の月が続く最後の月を探し、その翌月からを本物の月次とみなす（FRED GS10 が取れないときの予備）"""
    ks = sorted(y)
    last_flat = None
    for a, b, c in zip(ks, ks[1:], ks[2:]):
        if abs(y[c] - 2 * y[b] + y[a]) < 1e-7:
            last_flat = b
    return h.add_months(last_flat, 1) if last_flat else (ks[0] if ks else None)


def real_monthly_from(y):
    """債券の利回りが本物の月次になる最初の月。FRED GS10（Shiller が 1953-04 以降に使う同じ系列）の最初の月を正とする"""
    try:
        fr = h.fred('GS10')
    except Exception:
        fr = {}
    return min(fr) if fr else _interp_run_end(y)


def bond_returns(yields=None, real_from=None):
    """10年の定満期債を毎月買い替える: 前月の利回りをクーポンにした額面の債券を、今月の利回り・残存 10−1/12 年で評価し、1か月分の利子を足す。
    ⚠ 利回りが補間（1953-03 以前）の月は使わない——月次のぶれが 0.5%/年 という作り物になり、逆ぶれ加重が債券に全部を載せる"""
    y = yields if yields is not None else bond_yields()
    rf0 = real_from if real_from is not None else (real_monthly_from(y) if yields is None else min(y))
    ks = sorted(k for k in y if k >= rf0)
    out = {}
    for a, b in zip(ks, ks[1:]):
        if h.add_months(a, 1) != b:
            continue
        c = y[a]
        out[b] = _bond_price(c, y[b], 10 - 1 / 12) - 1 + c / 12
    return out


def nonus_ew(countries=None):
    """French 国別（Value-Weight・米ドル建て）の米国外の国を、その月にデータのある国で等加重"""
    c = countries if countries is not None else h.french_countries('Dollar')
    per = {}
    for nm, s in c.items():
        if nm.upper() in ('US', 'USA', 'UNITED STATES'):
            continue
        for m, v in s.items():
            per.setdefault(m, []).append(v)
    return {m: sum(v) / len(v) for m, v in per.items() if v}


def load(spec=None):
    spec = dict(DEFAULT_SPEC, **(spec or {}))
    us, rf = h.us_market()
    if spec.get('bond_src', 'shiller') == 'dgs10_me':
        y = {m: v / 100 for m, v in h.fred('DGS10').items()}      # fred() は日次を月のキーへ畳む＝その月の最後の日の値
        bond = bond_returns(y, real_from=min(y)) if y else {}
    else:
        bond = bond_returns()
    A = {'us': us, 'bond': bond}
    if spec.get('nonus', True):
        A['nonus'] = nonus_ew()
    return A, rf


# ───────────────────────── 重み（先読みなし） ─────────────────────────
def _window(series, end, n):
    """end を含めて遡る n か月の値（全部揃わなければ None）"""
    out, m = [], end
    for _ in range(n):
        if m not in series:
            return None
        out.append(series[m])
        m = h.add_months(m, -1)
    return out[::-1]


def _signal(r, rf, end, L):
    """end までの L か月の複利 − 同じ月の短期金利の複利 > 0 → 1"""
    w = _window(r, end, L)
    f = _window(rf, end, L)
    if w is None or f is None:
        return None
    return 1.0 if math.prod(1 + x for x in w) > math.prod(1 + x for x in f) else 0.0


def weights_for(m, A, rf, spec):
    """月 m に持つ エクスポージャー {資産: 倍率}（現金は 1−合計）。m−1 月末までのデータだけを使う。
    使えない（履歴が足りない）なら None"""
    last = h.add_months(m, -1)
    VW = int(spec['vol_win'])
    sig, vol, ends = {}, {}, {}
    for a, r in A.items():
        skip = int(spec['bond_skip']) if a == 'bond' else 0
        e = h.add_months(last, -skip)
        if spec['lookback'] == '12':
            s = _signal(r, rf, e, 12)
        elif spec['lookback'] == '6_12':
            s6, s12 = _signal(r, rf, e, 6), _signal(r, rf, e, 12)
            s = None if s6 is None or s12 is None else (s6 + s12) / 2
        else:
            raise ValueError(spec['lookback'])
        w = _window(r, e, VW)
        if s is None or w is None:
            continue
        sd = S.stdev(w) * math.sqrt(12)
        if sd <= 0:
            continue
        sig[a], vol[a], ends[a] = s, sd, e
    if any(a not in sig for a in spec.get('require', ['us'])):   # 米国株（目標のぶれ）と債券が測れない月は使わない
        return None
    target = vol['us']
    inv = {a: (1 / vol[a] if spec.get('weight', 'inv') == 'inv' else 1.0) for a in sig}

    def pvol(w):
        """今の重み w を、各資産の直近 VW か月（その資産の測った窓）に当てた組のぶれ"""
        if not any(w.values()):
            return 0.0
        seqs = {a: _window(A[a], ends[a], VW) for a in w if w[a]}
        pr = [sum(w[a] * seqs[a][i] for a in seqs) for i in range(VW)]
        return S.stdev(pr) * math.sqrt(12)

    sch = spec['scheme']
    held = {a for a in sig if sig[a] > 0}
    if not held:
        return {a: 0.0 for a in sig}
    if sch == 'H':
        tot = sum(inv[a] for a in held)
        w = {a: sig[a] * inv[a] / tot if a in held else 0.0 for a in sig}
        pv = pvol(w)
    else:
        tot = sum(inv.values())
        w = {a: sig[a] * inv[a] / tot for a in sig}
        if sch == 'S1':
            pv = pvol({a: inv[a] / tot for a in sig})
        elif sch == 'S2':
            pv = pvol(w)
        else:
            raise ValueError(sch)
    L = min(float(spec['cap']), target / pv) if pv > 0 else float(spec['cap'])
    return {a: L * w[a] for a in sig}


# ───────────────────────── 本体 ─────────────────────────
def simulate(A, rf, spec):
    spec = dict(DEFAULT_SPEC, **(spec or {}))
    months = sorted(set(A['us']) & set(rf))
    ret, turn, expo = {}, {}, {}
    prev = None                                         # 前月末（漂流後）のエクスポージャー
    for m in months:
        e = weights_for(m, A, rf, spec)
        if e is None:
            continue
        # この月のリターンがまだ無い資産（系列の終わり）は持てない → その月は止める
        if any(e[a] and m not in A[a] for a in e):
            break
        gross = sum(e.values())
        cash = 1 - gross
        borrowed = max(0.0, gross - 1)
        r = sum(e[a] * A[a][m] for a in e if e[a]) + cash * rf[m]
        r -= borrowed * (spec['borrow_spread'] + spec['lev_fee']) / 12
        # 片道の回転 = ½ × (Σ|Δ危険資産| + |Δ現金|)。前月末の重みは その月のリターンで漂流させる
        p = prev or {}
        pc = 1 - sum(p.values()) if prev is not None else 1.0
        keys = set(e) | set(p)
        tv = 0.5 * (sum(abs(e.get(a, 0.0) - p.get(a, 0.0)) for a in keys) + abs(cash - pc))
        ret[m], turn[m], expo[m] = r, tv, dict(e)
        # 漂流
        g = 1 + r
        prev = {a: e[a] * (1 + A[a][m]) / g for a in e} if g > 0 else {a: 0.0 for a in e}
    return ret, turn, expo


def run(spec):
    spec = dict(DEFAULT_SPEC, **(spec or {}))
    A, rf = load(spec)
    ret, turn, _ = simulate(A, rf, spec)
    us = A['us']
    return {'ret': ret, 'bench': {m: us[m] for m in us}, 'rf': rf, 'turnover': turn,
            'cost': spec.get('cost', 0.001), 'markets': {}}


if __name__ == '__main__':
    r = run(DEFAULT_SPEC)
    print(h.stats(r['ret'], r['bench'], r['rf'], turnover=r['turnover'], cost=r['cost']))


# ───────────────────────── 先読みの検査 ─────────────────────────
def lookahead_test(spec=None, cuts=(196012, 197506, 198512, 199512)):
    """(1) 全系列を月 c で切って回した結果が、全期間で回した結果の c までと一致するか
       (2) 月 c+1 の重みを『c までのデータ』だけで作ったものが、全期間のデータで作ったものと一致するか
       (3) c より後の月のリターンを壊しても（×−3 して +0.5）、c+1 までの重みが変わらないか
    どれかがずれたら先読み。→ [(c, 最大の差, 重みが一致したか)]"""
    spec = dict(DEFAULT_SPEC, **(spec or {}))
    A, rf = load(spec)
    full_ret, _, full_exp = simulate(A, rf, spec)
    out = []
    for c in cuts:
        At = {a: {m: v for m, v in r.items() if m <= c} for a, r in A.items()}
        rft = {m: v for m, v in rf.items() if m <= c}
        rt, _, _ = simulate(At, rft, spec)
        common = [m for m in rt if m <= c]
        d1 = max((abs(rt[m] - full_ret[m]) for m in common), default=0.0)
        nxt = h.add_months(c, 1)
        w_trunc = weights_for(nxt, At, rft, spec)
        w_full = weights_for(nxt, A, rf, spec)
        same_w = (w_trunc is None and w_full is None) or (w_trunc is not None and w_full is not None and
                                                          all(abs(w_trunc.get(a, 0) - w_full.get(a, 0)) < 1e-12 for a in set(w_trunc) | set(w_full)))
        Ab = {a: {m: (v if m <= c else -3 * v + 0.5) for m, v in r.items()} for a, r in A.items()}
        rfb = {m: (v if m <= c else 0.05) for m, v in rf.items()}
        _, _, exp_b = simulate(Ab, rfb, spec)
        same_b = all(abs(exp_b[m].get(a, 0) - full_exp[m].get(a, 0)) < 1e-12 for m in full_exp if m <= nxt and m in exp_b for a in full_exp[m])
        out.append({'cut': c, 'n_months': len(common), 'max_ret_diff': d1, 'weights_c+1_same': same_w, 'weights_after_corrupt_same': same_b})
    return out
