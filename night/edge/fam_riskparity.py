#!/usr/bin/env python3
"""night/edge/fam_riskparity.py — 系統 riskparity: 株と債券のリスクの釣り合い＋借入（Asness・Frazzini・Pedersen 2012）

事前登録 out/edge_prereg.json（第1回）の一系統。読むだけ・門の採点に不使用。

■ 規則（月次）
  月 m の持ち高は **m−1 月末までのリターンだけ**で決める。
  1) 株（Ken French 米国市場・配当込み）と 10年債（Shiller GS10 から作る）の直近 N か月の月次リターンから
     ぶれ σ_s, σ_b と共分散を出す（N か月そろわない月は持たない）。
  2) 重み w_s ∝ 1/σ_s, w_b ∝ 1/σ_b（2資産ではリスク寄与の均等＝逆ぶれ比例と同じ）。'invvar' は 1/σ²。
  3) 釣り合わせた組の事前のぶれ σ_p = √(w'Σw) を、目標（株の直近のぶれ σ_s、または前もって決めた一定値）まで
     借りて合わせる: L = min(上限, 目標/σ_p)。L<1 のときは残りを短期金利で持つ。
  4) 借りた分 (L−1) に 短期金利＋0.4%/年、経費 0.9%/年（事前登録の「レバレッジ」の行・2倍型の ETF で上乗せ分を持つ形）。
  5) 売買の費用は 片道の回転1あたり 0.10%（評価側 h.stats が turnover×cost で引く）。

■ 10年債のリターン
  r_b(m) = y_{m−1}/12 + [ y_{m−1}/y_m ×(1−(1+y_m/2)^{−2n}) + (1+y_m/2)^{−2n} − 1 ],  n = 10 − 1/12 年
  ＝「利回り÷12＋修正デュレーション×利回りの低下」に凸性を足したもの（額面の債券を翌月の利回りで値付けし直す）。
  利回りの系列（規則の成績を見る前に、データの質だけで決めた）:
   ・1962-01 以降は FRED DGS10 の**月末**（その月の最後の営業日）。株（French・月末）と同じ時点で測るため。
     Shiller の GS10 は**月平均**なので、同じ 1962-2000 で月次のぶれを 13% 小さく（6.87% vs 7.92%）、
     1か月の自己相関を 0.33（月末は 0.12）に作ってしまう——逆ぶれの重みと借入の倍率を債券に甘く出す。
   ・1953-04〜1961-12 は Shiller GS10（＝FRED GS10 の月平均。1953-04〜2000-12 で1か月も違わないことを確認）。
   ・1953-03 以前は使わない。Shiller の GS10 はそこでは**年次の値を月へ直線補間したもの**（月次の変化のぶれ 0.018pt vs
     1953-04 以降 0.17pt）で、債券のぶれが作り物になり逆ぶれの重みを債券へ極端に寄せる。
   期間は決め打ちしない（harness の読み込みが返す範囲をそのまま使う）。
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h

FAMILY = {
    'key': 'riskparity',
    'name': '株と債券のリスクの釣り合い＋借入（リスクパリティ）',
    'implement': ('楽天証券の特定口座（課税）で、米国株 ETF（VTI）と米国中期国債 ETF（IEF／VGIT）を毎月、直近のぶれの逆数の比で持ち、'
                  '株の直近のぶれまで足りない分を 2倍・3倍の毎日リセット型（SSO／UPRO・TMF）で上乗せする。'
                  '借入の上乗せ分と経費（年0.9%前後）がかかる。レバレッジ型は NISA（成長投資枠）の対象外なので課税口座のみ'
                  '（借りない部分の VTI・IEF は NISA 可）。固定比の近い商品に 楽天・米国レバレッジバランス・ファンド（株90%＋債券270%）があるが、'
                  'ぶれで比率を変える規則そのものではない'),
}

BOND_START = 195304          # 実の月次の 10年利回りが始まる月（それより前は年次の補間）
MAT = 10.0                   # 10年の定満期
SPREAD = 0.004               # 借入の上乗せ（年）
FEE = 0.009                  # 上乗せ分の経費（年・2倍型の ETF）
COST = 0.001                 # 片道の回転1あたり（指数・ETF）

DEFAULT_SPEC = {'N': 60, 'weight': 'invvol', 'target': 'stock', 'cap': 2.0, 'est': 'equal',
                'start': 195805, 'spread': SPREAD, 'fee': FEE}


# ───────────────────────── データ ─────────────────────────
def ten_year_yields():
    """{YYYYMM: 10年利回り(小数)}。1962-01〜 FRED DGS10 の月末／それより前（1953-04〜）は Shiller GS10（月平均）"""
    eom = {m: v / 100 for m, v in h.guard(h.fred('DGS10')).items()}      # h.fred は日次の行を月へ上書き＝月の最後の営業日
    first = min(eom) if eom else 10 ** 9
    out = {r['m']: r['GS10'] / 100 for r in h.shiller()
           if r['GS10'] is not None and BOND_START <= r['m'] < first}
    out.update(eom)
    return out


def bond_returns(y):
    """定満期 10年の額面債を翌月の利回りで値付けし直す月次トータルリターン"""
    ks = sorted(y)
    out = {}
    n2 = 2 * (MAT - 1 / 12)
    for a, b in zip(ks, ks[1:]):
        if h.add_months(a, 1) != b:
            continue
        y0, y1 = y[a], y[b]
        disc = (1 + y1 / 2) ** (-n2)
        price = (y0 / y1) * (1 - disc) + disc
        out[b] = y0 / 12 + price - 1
    return out


def load():
    mkt, rf = h.us_market()
    bond = bond_returns(ten_year_yields())
    return mkt, rf, bond


# ───────────────────────── 規則 ─────────────────────────
def _moments(xs, ys, est):
    n = len(xs)
    if est == 'ewma':                            # 半減期12か月の指数加重（窓の中だけ）
        lam = 0.5 ** (1 / 12)
        ws = [lam ** (n - 1 - i) for i in range(n)]
    else:
        ws = [1.0] * n
    sw = sum(ws)
    mx = sum(w * x for w, x in zip(ws, xs)) / sw
    my = sum(w * y for w, y in zip(ws, ys)) / sw
    corr = sw / (sw - sum(w * w for w in ws) / sw)          # 不偏の補正
    vx = sum(w * (x - mx) ** 2 for w, x in zip(ws, xs)) / sw * corr
    vy = sum(w * (y - my) ** 2 for w, y in zip(ws, ys)) / sw * corr
    cxy = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys)) / sw * corr
    return vx * 12, vy * 12, cxy * 12                      # 年率


def weights(spec, mkt, bond):
    """{月 m: (e_s, e_b, L)} — 月 m の持ち高。**m より前の N か月だけ**を使う。
    データの最後の月の翌月の持ち高も出す（先読みの検査で使う）"""
    N, cap = int(spec['N']), float(spec['cap'])
    common = sorted(set(mkt) & set(bond))
    if not common:
        return {}
    out = {}
    last = common[-1]
    cand = h.month_range(h.add_months(common[0], N), h.add_months(last, 1))
    cset = set(common)
    for m in cand:
        win = [h.add_months(m, -k) for k in range(N, 0, -1)]
        if not all(x in cset for x in win):
            continue
        xs = [mkt[x] for x in win]
        ys = [bond[x] for x in win]
        vs, vb, cov = _moments(xs, ys, spec.get('est', 'equal'))
        ss, sb = math.sqrt(vs), math.sqrt(vb)
        if spec.get('weight', 'invvol') == 'invvar':
            a, b = 1 / vs, 1 / vb
        else:
            a, b = 1 / ss, 1 / sb
        ws, wb = a / (a + b), b / (a + b)
        sp = math.sqrt(max(ws * ws * vs + wb * wb * vb + 2 * ws * wb * cov, 1e-12))
        tgt = spec.get('target', 'stock')
        tv = ss if tgt == 'stock' else float(tgt)
        L = min(cap, tv / sp)
        out[m] = (L * ws, L * wb, L)
    return out


def simulate(spec, mkt, rf, bond):
    """→ ret（費用前・借入と経費は込み）、turnover（片道）、w（持ち高）"""
    W = weights(spec, mkt, bond)
    start = int(spec.get('start', 0) or 0)
    spread, fee = float(spec.get('spread', SPREAD)), float(spec.get('fee', FEE))
    ret, tov = {}, {}
    prev = None                                    # 前の月末の、値動き後の持ち高（資本1あたり）
    for m in sorted(W):
        if m < start or m not in mkt or m not in bond or m not in rf:
            prev = None if m >= start else prev
            continue
        es, eb, L = W[m]
        cash = 1 - L
        if prev is not None:
            ps, pb, pc = prev
            tov[m] = 0.5 * (abs(es - ps) + abs(eb - pb) + abs(cash - pc))
        else:
            tov[m] = 0.0                           # 最初の月の建て玉は相手（市場）と同じく費用なし
        r = es * mkt[m] + eb * bond[m] + cash * rf[m]
        if L > 1:
            r -= (L - 1) * (spread + fee) / 12
        ret[m] = r
        g = 1 + r
        prev = (es * (1 + mkt[m]) / g, eb * (1 + bond[m]) / g, 1 - es * (1 + mkt[m]) / g - eb * (1 + bond[m]) / g)
    return ret, tov, W


def sixty_forty(mkt, rf, bond, start=0, ws=0.6):
    """60/40（毎月リバランス・借りない）→ ret, turnover"""
    ret, tov, prev = {}, {}, None
    for m in sorted(set(mkt) & set(bond)):
        if m < start:
            continue
        wb = 1 - ws
        if prev is not None:
            tov[m] = 0.5 * (abs(ws - prev[0]) + abs(wb - prev[1]))
        else:
            tov[m] = 0.0
        r = ws * mkt[m] + wb * bond[m]
        ret[m] = r
        prev = (ws * (1 + mkt[m]) / (1 + r), wb * (1 + bond[m]) / (1 + r))
    return ret, tov


def run(spec):
    sp = dict(DEFAULT_SPEC)
    sp.update(spec or {})
    mkt, rf, bond = load()
    ret, tov, _ = simulate(sp, mkt, rf, bond)
    return {'ret': ret, 'bench': mkt, 'rf': rf, 'turnover': tov, 'cost': COST, 'markets': {}}


# ───────────────────────── 先読みの自己検査 ─────────────────────────
def lookahead_selftest(spec, cuts=(196512, 197512, 198112, 198712, 199412, 199912)):
    """(1) データを月 k で切って作った「月 k+1 の持ち高」が、全データで作った持ち高と一致するか
       (2) 切ったデータでの k までのリターン・回転が全データと一致するか
       (3) 月 m のリターンを1か月ずらして（未来へ）壊しても、月 m 以前の持ち高が変わらないか
    → 食い違いの件数（0 なら先読みなし）"""
    sp = dict(DEFAULT_SPEC); sp.update(spec or {})
    mkt, rf, bond = load()
    fullW = weights(sp, mkt, bond)
    fret, ftov, _ = simulate(sp, mkt, rf, bond)
    bad = []
    for k in cuts:
        cut = lambda d: {m: v for m, v in d.items() if m <= k}
        mk2, rf2, bd2 = cut(mkt), cut(rf), cut(bond)
        W2 = weights(sp, mk2, bd2)
        nxt = h.add_months(k, 1)
        if nxt in fullW:
            if nxt not in W2 or any(abs(a - b) > 1e-12 for a, b in zip(W2[nxt], fullW[nxt])):
                bad.append(('next_weight', k))
        r2, t2, _ = simulate(sp, mk2, rf2, bd2)
        for m in r2:
            if abs(r2[m] - fret[m]) > 1e-12 or abs(t2[m] - ftov[m]) > 1e-12:
                bad.append(('ret', k, m)); break
        # (3) k より後のリターンを乱す → k+1 以前の持ち高は不変のはず
        mk3 = {m: (v if m <= k else -v * 3 + 0.05) for m, v in mkt.items()}
        bd3 = {m: (v if m <= k else v * 5 - 0.02) for m, v in bond.items()}
        W3 = weights(sp, mk3, bd3)
        for m in W3:
            if m <= nxt and m in fullW and any(abs(a - b) > 1e-12 for a, b in zip(W3[m], fullW[m])):
                bad.append(('perturb', k, m)); break
    return bad


if __name__ == '__main__':
    import json
    sp = dict(DEFAULT_SPEC)
    print('先読みの自己検査:', lookahead_selftest(sp) or '食い違い 0 件')
    r = run(sp)
    print(json.dumps(h.stats(r['ret'], r['bench'], r['rf'], turnover=r['turnover'], cost=r['cost']), ensure_ascii=False))
