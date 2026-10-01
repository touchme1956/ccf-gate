#!/usr/bin/env python3
"""night/edge/fam_lowbeta_lev.py — 系統 lowbeta_lev（事前登録 out/edge_prereg.json・第1回）

低ベータ・低ぶれの株の組を、その時点までに推定したベータ（またはぶれ）で 1/β 倍（上限2倍・下限1倍）に借りて持つ。
Frazzini & Pedersen (2014)「Betting Against Beta」の買いだけ＋借入版（Black 1972 の借入制約・Baker/Bradley/Wurgler 2011 の宝くじ選好）。

  ■ 素材（すべて時価加重）
    fr_beta_q / fr_beta_d     French 'Portfolios_Formed_on_BETA' の Lo 20 / Lo 10（毎年6月末に過去60か月のベータで組む・1963-07〜）
    fr_var_q / fr_var_d       French 'Portfolios_Formed_on_VAR' の Lo 20 / Lo 10（毎月末に過去60営業日の分散で組む）
    fr_resvar_q / fr_resvar_d French 'Portfolios_Formed_on_RESVAR' の Lo 20 / Lo 10（3因子の残差の分散・毎月）
    jkp_t1                    JKP 'betabab_1260d' の三分位の 1（低ベータ側・vw・1928〜。JKP の ret は米国の短期金利を引いた超過なので rf を足して総リターンにする）
    jkp_beta60 / jkp_ivol252 / jkp_rvol21 / jkp_betadown   JKP の他の低リスクの特徴（60か月β・1年の固有ぶれ・21日のぶれ・下方β）の三分位の 1
  ■ 規則（月次）
    月 m の倍率 L_m = clip(1/β̂, 1, cap)（method='beta'）／ clip(σ_mkt/σ_p, 1, cap)（method='vol'）／
    clip(1/(ρ̂·σ_p/σ_mkt), 1, cap)（method='fp'＝相関は window か月・ぶれは直近24か月。Frazzini-Pedersen の分解）。
    β̂・σ は **m−1 月末までの** 直近 window か月（超過リターン）だけで推定する。
    月 m のリターン = L·r_p − (L−1)·(rf + spread/12) − fee/12（L>1 のとき）。
  ■ 費用（事前登録どおり）
    借りた分に 短期金利＋0.4%/年、経費 0.9%/年（レバレッジの実額の代わり＝個人の信用取引の金利の上乗せに近い）。
    売買: 片道の回転1あたり 0.25%。回転 = 組の入れ替え（年1回の組は年100%、毎月の組は価格の信号として年200%）× L
          ＋ 倍率を戻す売買（前月の値動きでずれた倍率を L_m へ戻す分）。
  ■ 相手: Ken French の米国市場（CRSP 全上場の時価加重・配当込み）。
  ■ 再現: JKP の先進国の同じ特徴（素材が French なら 'betabab_1260d'）の三分位の 1（vw）に同じ規則（window・method・cap）を当て、相手はその国の JKP 'mkt'（vw）＋米国の短期金利＝米ドル建ての総リターン。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h  # noqa: E402
import statistics as S  # noqa: E402

FAMILY = {
    'key': 'lowbeta_lev',
    'name': '低ベータ株を借りて市場並みに持つ（BAB の買いだけ＋借入）',
    'implement': ('証券会社の米国株信用取引（SBI・マネックス・楽天など。NISA では不可＝課税口座）で、米国の低ボラ／低ベータ株 ETF '
                  '（例: iShares MSCI USA Min Vol〔USMV〕・Invesco S&P 500 Low Volatility〔SPLV〕）を 1/β 倍（上限2倍）まで買う。'
                  '月末に過去の月次リターンから β を測り直し、倍率を合わせる。信用取引の金利は短期金利＋0.4%/年より高いのが普通なので、'
                  '経費0.9%/年をその上乗せの代わりに引いてある。レバレッジ型の低ボラETFは日本の証券会社では買えない。'),
}

SOURCES = {
    # key: (French の名前 or None, 列 or JKP の特徴, 片道の回転/年〔組の入れ替え〕)
    'fr_beta_q':    ('Portfolios_Formed_on_BETA', 'Lo 20', 1.0),     # 年1回の組 → 回転は年100%を超えない（上限を置く）
    'fr_beta_d':    ('Portfolios_Formed_on_BETA', 'Lo 10', 1.0),
    'fr_var_q':     ('Portfolios_Formed_on_VAR', 'Lo 20', 2.0),      # 毎月の組・価格の信号 → 事前登録の 200%/年
    'fr_var_d':     ('Portfolios_Formed_on_VAR', 'Lo 10', 2.0),
    'fr_resvar_q':  ('Portfolios_Formed_on_RESVAR', 'Lo 20', 2.0),
    'fr_resvar_d':  ('Portfolios_Formed_on_RESVAR', 'Lo 10', 2.0),
    'jkp_t1':       (None, 'betabab_1260d', 2.0),                     # JKP 三分位の 1（低い側）・vw
    'jkp_beta60':   (None, 'beta_60m', 2.0),
    'jkp_ivol252':  (None, 'ivol_capm_252d', 2.0),
    'jkp_rvol21':   (None, 'rvol_21d', 4.0),                          # 21日のぶれは入れ替わりが速い → 400%/年と置く
    'jkp_betadown': (None, 'betadown_252d', 2.0),
}
TABLE = 'Value Weighted Returns -- Monthly'
DEV = 'aus aut bel can che deu dnk esp fin fra gbr hkg irl isr ita jpn nld nor nzl prt sgp swe'.split()
COST = 0.0025          # 片道の回転1あたり（個別株の組）


def load_source(src, rf):
    """→ ({YYYYMM: 総リターン(小数)}, 年あたりの回転)"""
    name, col, turn = SOURCES[src]
    if name:
        d = h.french(name)[TABLE][col]
        return {m: v / 100 for m, v in d.items() if m > 9999}, turn
    p = h.jkp('usa', col, 'portfolio', 'vw')['1.0']      # JKP の ret は米国の短期金利を引いた超過 → rf を足す
    return {m: v + rf[m] for m, v in p.items() if m in rf}, turn


def _beta(y, x):
    mx, my = S.mean(x), S.mean(y)
    vx = sum((a - mx) ** 2 for a in x)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / vx if vx > 0 else None


def leverage(p, mkt, rf, window, method, cap):
    """{m: L_m}。L_m は m より前の window か月（連続・m−1 まで）だけで決める"""
    ms = sorted(m for m in p if m in mkt and m in rf)
    L = {}
    for i, m in enumerate(ms):
        if i < window:
            continue
        w = ms[i - window:i]                              # m は含まない（m−window 〜 m−1）
        if h.add_months(w[0], window - 1) != w[-1] or h.add_months(w[-1], 1) != m:
            continue                                      # 途中が欠けている窓は使わない
        yp = [p[k] - rf[k] for k in w]
        xm = [mkt[k] - rf[k] for k in w]
        if method == 'beta':
            b = _beta(yp, xm)
            x = 1 / b if b and b > 0 else cap
        elif method == 'fp':                              # Frazzini-Pedersen: 相関は長い窓・ぶれは直近24か月
            ys, xs = yp[-24:], xm[-24:]
            mx, my = S.mean(xm), S.mean(yp)
            cov = sum((a - mx) * (b - my) for a, b in zip(xm, yp))
            vx, vy = sum((a - mx) ** 2 for a in xm), sum((b - my) ** 2 for b in yp)
            rho = cov / (vx * vy) ** 0.5 if vx > 0 and vy > 0 else None
            b = rho * S.stdev(ys) / S.stdev(xs) if rho is not None and S.stdev(xs) > 0 else None
            x = 1 / b if b and b > 0 else cap
        else:
            sp, sm = S.stdev(yp), S.stdev(xm)
            x = sm / sp if sp > 0 else cap
        L[m] = min(cap, max(1.0, x))
    return L


def levered(p, L, rf, base_turn, spread=0.004, fee=0.009):
    """月次で倍率 L を持ったときのリターン（借入・経費込み・売買の費用の前）と片道の回転"""
    ret, tv = {}, {}
    prev = None                                           # (L, r_p, 借入の費用率) 前月
    for m in sorted(L):
        l = L[m]
        c = rf[m] + spread / 12
        ret[m] = l * p[m] - (l - 1) * c - (fee / 12 if l > 1 else 0.0)
        t = l * base_turn / 12                            # 組そのものの入れ替え（持ち高に比例）
        if prev is not None and h.add_months(prev[0], 1) == m:
            pl, pr, pc = prev[1], prev[2], prev[3]
            eq = 1 + pl * pr - (pl - 1) * pc - (fee / 12 if pl > 1 else 0.0)
            drift = pl * (1 + pr) / eq if eq > 0 else pl
            t += abs(l - drift)                          # 前月の値動きでずれた倍率を L へ戻す売買
        else:
            t += l                                        # 最初の月は全額を買う
        tv[m] = t
        prev = (m, l, p[m], c)
    return ret, tv


def rule(p, mkt, rf, spec, base_turn):
    L = leverage(p, mkt, rf, spec['window'], spec['method'], spec.get('cap', 2.0))
    ret, tv = levered(p, L, rf, base_turn, spec.get('spread', 0.004), spec.get('fee', 0.009))
    return ret, tv, L


def run(spec):
    mkt, rf = h.us_market()
    p, bt = load_source(spec['source'], rf)
    ret, tv, L = rule(p, mkt, rf, spec, bt)
    bench = {m: mkt[m] for m in ret}
    markets = {}
    jkey = SOURCES[spec['source']][1] if SOURCES[spec['source']][0] is None else 'betabab_1260d'
    jturn = SOURCES[spec['source']][2] if SOURCES[spec['source']][0] is None else SOURCES['jkp_t1'][2]
    for c in DEV:
        try:
            pc = h.jkp(c, jkey, 'portfolio', 'vw').get('1.0') or {}
            fc = h.jkp(c, 'mkt', 'factor', 'vw') or {}
        except Exception:
            continue
        pt = {m: v + rf[m] for m, v in pc.items() if m in rf}
        mt = {m: v + rf[m] for m, v in fc.items() if m in rf}
        r2, t2, _ = rule(pt, mt, rf, spec, jturn)
        if len(r2) < 24:
            continue
        markets[f'jkp_{c}'] = {'ret': r2, 'bench': {m: mt[m] for m in r2 if m in mt}, 'rf': rf, 'turnover': t2, 'cost': COST}
    return {'ret': ret, 'bench': bench, 'rf': rf, 'turnover': tv, 'cost': COST, 'markets': markets, 'L': L}
