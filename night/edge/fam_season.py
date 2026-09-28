#!/usr/bin/env python3
"""night/edge/fam_season.py — 系統 season（季節）: 暦だけで持ち高を変える規則（事前登録 out/edge_prereg.json・第1回）

  型（spec['type']）
    halloween  11〜4月（冬）は winter 倍・5〜10月（夏）は summer 倍（0＝短期金利）。Bouman & Jacobsen (2002)
    tom        月替わり（その月の最後の営業日＋翌月の最初の3営業日）は tom 倍・それ以外は base 倍。Lakonishok & Smidt (1988)・Ariel (1987)
    jan_small  1月だけ小型株（French Portfolios_Formed_on_ME の時価加重 size 列）・他の月は市場。Keim (1983)・Reinganum (1983)・Roll (1983)
    const      常に L 倍（対照。季節の規則ではないので選ばない）
  持ち高 L の作り方: L≤1 は 市場 L・短期金利 1−L／L>1 は h.lev_daily（毎日リセット・借入 rf＋0.4%/年・経費 0.9%/年）。
  回転（片道）: 持ち物を {現金, 1倍, 2倍, 3倍} の重みで表し、変わった日に ½Σ|Δ重み| を その日の月に付ける（市場↔現金の入れ替え＝1）。
  信号は暦だけ（その月・その日が何月か、月の何番目の営業日か）＝リターンを一切使わない。
  ⚠ 月替わりの「最後の営業日」は取引所の休日の暦（事前に公表）で決まる。データの日付から読むが、未来のリターンは読まない。

  他の市場での再現（凍結した規則を変えずに当てる）
    halloween / const → French 21か国（米ドル・月次・1975〜）。現金は米国の短期金利。レバレッジは同じ式を月次で
    tom               → French の日次の地域（Europe / Japan / Asia_Pacific_ex_Japan・1990-07〜）
    jan_small         → French の地域の 6 portfolios の小型3つの平均（Europe / Japan / Asia_Pacific_ex_Japan / Emerging_Markets）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h

FAMILY = {'key': 'season',
          'name': '季節（冬だけ厚く持つ・月替わり・1月の小型株）',
          'implement': ('暦だけで決まるので、楽天証券の米国株口座で年に数回（月替わりなら月2回）注文するだけ。'
                        '市場＝VTI（または eMAXIS Slim 全米株式）、2倍＝SSO（米国ETF）または iFreeレバレッジ S&P500（投信）、'
                        '3倍＝SPXL、小型株＝IWM / IJR、現金＝米ドルMMF（または円の普通預金）。'
                        '⚠ レバレッジ型はNISAの対象外（課税口座）。持ち高を1倍以下に保つ型（冬1倍・夏0）はNISAの成長投資枠の'
                        'ETF・投信で実行できるが、売るたびに非課税枠は戻らない（年2回の入れ替えはNISAと相性が悪い）')}

COST_ETF = 0.001        # 指数・ETF の入れ替え（片道の回転1につき）
COST_STOCK = 0.0025     # 個別株の組（French の分位）
WINTER = (11, 12, 1, 2, 3, 4)


# ───────────────────────── 部品 ─────────────────────────
def _w(L):
    """持ち高 L を {現金0, 1倍, 2倍, 3倍} の重みへ（1.5倍＝1倍0.5＋2倍0.5）"""
    if L < 0 or L > 3:
        raise ValueError(f'L={L} は 0〜3 の範囲だけ')
    if L <= 1:
        return {0: 1 - L, 1: L}
    if L <= 2:
        return {1: 2 - L, 2: L - 1}
    return {2: 3 - L, 3: L - 2}


def _tv(a, b):
    wa, wb = _w(a), _w(b)
    return 0.5 * sum(abs(wa.get(k, 0.0) - wb.get(k, 0.0)) for k in set(wa) | set(wb))


def _series(r, rf, L, days):
    """一定の L で持った系列（L≤1 は市場と現金の混合、L>1 は h.lev_daily の式）"""
    if L <= 1:
        return {k: L * r[k] + (1 - L) * rf.get(k, 0.0) for k in r}
    return h.lev_daily(r, {k: rf.get(k, 0.0) for k in r}, L, days=days)


def _apply(r, rf, expo, days):
    """expo(キー)→L で日（または月）ごとに持ち高を決め、(系列, {YYYYMM: 片道の回転}) を返す。
    expo は暦（キーそのもの）だけを見る＝リターンを見ない"""
    ks = sorted(r)
    Ls = {k: expo(k) for k in ks}
    cache = {L: _series(r, rf, L, days) for L in set(Ls.values())}
    out, tv, prev = {}, {}, None
    for k in ks:
        L = Ls[k]
        out[k] = cache[L][k]
        if prev is not None and L != prev:
            m = k // 100 if k > 999999 else k
            tv[m] = tv.get(m, 0.0) + _tv(prev, L)
        prev = L
    return out, tv


def _tom_days(keys):
    """月替わりの日の集合: 各月の最後の営業日 ＋ 各月の最初の3営業日（データに載る営業日で数える）"""
    by = {}
    for k in sorted(keys):
        by.setdefault(k // 100, []).append(k)
    s = set()
    for m, ds in by.items():
        s.update(ds[:3])
        s.add(ds[-1])
    return s


def _month_of(k):
    return (k // 100) % 100 if k > 999999 else k % 100


def _expo(spec, keys=None):
    t = spec['type']
    if t == 'halloween':
        w, s = float(spec['winter']), float(spec['summer'])
        return lambda k: w if _month_of(k) in WINTER else s
    if t == 'const':
        L = float(spec['L'])
        return lambda k: L
    if t == 'tom':
        days = _tom_days(keys)
        a, b = float(spec['tom']), float(spec['base'])
        return lambda k: a if k in days else b
    raise ValueError(t)


# ───────────────────────── 米国（主） ─────────────────────────
def _us_daily_rule(spec):
    d, drf = h.us_market_daily()
    ret_d, tv = _apply(d, drf, _expo(spec, d.keys()), 252)
    # 相手・短期金利も同じ日次のファイルから（French の日次と月次は作り方が違い、日次を複利した市場は月次より年0.14%低い＝
    # 規則だけ日次で作って月次の市場と比べると、規則が作り方の差だけで不利になる）
    return h.to_monthly(ret_d), h.to_monthly(d), h.to_monthly(drf), tv


def _jan_core(mk, small):
    """1月は small（小数）・他の月は mk。持ち替えは暦（1月か）だけで決まる。→ (ret, {YYYYMM: 片道の回転})"""
    ret, tv = {}, {}
    for m in sorted(mk):
        if m % 100 == 1 and m in small:
            ret[m] = small[m]
            tv[m] = tv.get(m, 0.0) + 1.0      # 12月末に市場→小型株
            nxt = h.add_months(m, 1)
            tv[nxt] = tv.get(nxt, 0.0) + 1.0  # 1月末に小型株→市場
        else:
            ret[m] = mk[m]
    return ret, {m: v for m, v in tv.items() if m in ret}


def _us_small(size):
    sz = h.french('Portfolios_Formed_on_ME')['Average Value Weight Returns -- Monthly'][size]
    return {m: v / 100 for m, v in sz.items()}


def _us_jan_small(spec):
    mk, rf = h.us_market()
    ret, tv = _jan_core(mk, _us_small(spec['size']))
    return ret, mk, rf, tv


# ───────────────────────── 他の市場 ─────────────────────────
def _rep_countries(spec, cost):
    _, usrf = h.us_market()
    out = {}
    for nm, r in h.french_countries('Dollar').items():
        if len(r) < 24:
            continue
        rr = {m: v for m, v in r.items() if m in usrf}
        ret, tv = _apply(rr, usrf, _expo(spec), 12)
        out[nm] = {'ret': ret, 'bench': rr, 'rf': {m: usrf[m] for m in rr}, 'turnover': tv, 'cost': cost}
    return out


def _rep_regions_daily(spec, cost):
    out = {}
    for reg in ('Europe', 'Japan', 'Asia_Pacific_ex_Japan'):
        d, drf = h.french_region(reg, daily=True)
        if len(d) < 500:
            continue
        ret_d, tv = _apply(d, drf, _expo(spec, d.keys()), 252)
        out[reg] = {'ret': h.to_monthly(ret_d), 'bench': h.to_monthly(d), 'rf': h.to_monthly(drf), 'turnover': tv, 'cost': cost}
    return out


def _rep_regions_small(spec, cost):
    out = {}
    for reg, fac in (('Europe', None), ('Japan', None), ('Asia_Pacific_ex_Japan', None), ('Emerging_Markets', 'Emerging_5_Factors')):
        pf = h.french(f'{reg}_6_Portfolios_ME_BE-ME')
        t = next(x for x in pf if 'Value Weight' in x and 'Monthly' in x)
        c = pf[t]
        small = {}
        for m in c['SMALL LoBM']:
            if 99999 < m < 1000000 and m in c.get('ME1 BM2', {}) and m in c.get('SMALL HiBM', {}):
                small[m] = (c['SMALL LoBM'][m] + c['ME1 BM2'][m] + c['SMALL HiBM'][m]) / 300
        if fac:
            f = h.french(fac)
            ft = next(iter(f))
            mk = {m: (f[ft]['Mkt-RF'][m] + f[ft]['RF'][m]) / 100 for m in f[ft]['Mkt-RF'] if m in f[ft]['RF'] and 99999 < m < 1000000}
            rf = {m: f[ft]['RF'][m] / 100 for m in f[ft]['RF'] if 99999 < m < 1000000}
        else:
            mk, rf = h.french_region(reg)
        ret, tv = _jan_core(mk, small)
        if len(ret) >= 24:
            out[reg] = {'ret': ret, 'bench': mk, 'rf': rf, 'turnover': tv, 'cost': cost}
    return out


# ───────────────────────── 入口 ─────────────────────────
def run(spec):
    t = spec['type']
    if t in ('halloween', 'const', 'tom'):
        ret, bench, rf, tv = _us_daily_rule(spec)
        cost = COST_ETF
        markets = _rep_regions_daily(spec, cost) if t == 'tom' else _rep_countries(spec, cost)
    elif t == 'jan_small':
        ret, bench, rf, tv = _us_jan_small(spec)
        cost = COST_STOCK
        markets = _rep_regions_small(spec, cost)
    else:
        raise ValueError(t)
    if spec.get('no_markets'):
        markets = {}
    return {'ret': ret, 'bench': bench, 'rf': rf, 'turnover': tv, 'cost': cost, 'markets': markets}


def lookahead_test(spec, cuts=None, seed=7):
    """先読みの自己検査（選定の段のデータだけで走る）。3つを確かめる:
      ① 1か月ずつ後のデータを足しても（cut → cut の翌月末）、cut までの持ち高と月次の成績が1ビットも変わらない
      ② cut より後のリターンを乱数に置き換えても、cut までの月次の成績と「すべての日」の持ち高が変わらない（持ち高はリターンを見ない）
      ③ 同じ月の中のリターンを並べ替えても、その月の持ち高（日付ごと）が変わらない（同じ月の先読みが無い）
    → {'ok': bool, 'checks': n, 'fails': [...]}"""
    import random
    rnd = random.Random(seed)
    fails, n = [], 0
    if spec['type'] == 'jan_small':
        mk, _ = h.us_market()
        sm = _us_small(spec['size'])
        full, ftv = _jan_core(mk, sm)
        ms = sorted(mk)
        for cut in (cuts or ms[12::7]):
            for c in (cut, h.add_months(cut, 1)):                   # ① 切ったデータで作り直す
                r1, t1 = _jan_core({m: v for m, v in mk.items() if m <= c}, {m: v for m, v in sm.items() if m <= c})
                for m in ms:
                    if m > cut:
                        break
                    n += 2
                    if abs(r1[m] - full[m]) > 1e-12:
                        fails.append(('trunc', c, m))
                    if abs(t1.get(m, 0.0) - ftv.get(m, 0.0)) > 1e-12:
                        fails.append(('tv_trunc', c, m))
            # ② cut より後を乱数へ
            r2, _ = _jan_core({m: (v if m <= cut else rnd.gauss(0, 0.05)) for m, v in mk.items()},
                              {m: (v if m <= cut else rnd.gauss(0, 0.08)) for m, v in sm.items()})
            for m in ms:
                if m > cut:
                    break
                n += 1
                if abs(r2[m] - full[m]) > 1e-12:
                    fails.append(('perturb', cut, m))
        return {'ok': not fails, 'checks': n, 'fails': fails[:10]}
    d, drf = h.us_market_daily()
    ks = sorted(d)
    months = sorted({k // 100 for k in ks})
    full_ret, _ = _apply(d, drf, _expo(spec, ks), 252)
    full_pos = {k: _expo(spec, ks)(k) for k in ks}
    full_m = h.to_monthly(full_ret)
    for cut in (cuts or months[12::7]):
        nxt = h.add_months(cut, 1)
        for c in (cut, nxt):                                        # ①
            kk = [k for k in ks if k // 100 <= c]
            dd = {k: d[k] for k in kk}
            e = _expo(spec, kk)
            rr, _ = _apply(dd, drf, e, 252)
            mm = h.to_monthly(rr)
            for m in months:
                if m > cut:
                    break
                n += 1
                if abs(mm[m] - full_m[m]) > 1e-12:
                    fails.append(('trunc', c, m))
            for k in kk:
                if k // 100 <= cut:
                    n += 1
                    if e(k) != full_pos[k]:
                        fails.append(('pos_trunc', c, k))
        # ② cut より後のリターンを乱数へ
        dp = {k: (d[k] if k // 100 <= cut else rnd.gauss(0, 0.02)) for k in ks}
        e2 = _expo(spec, ks)
        rr2, _ = _apply(dp, drf, e2, 252)
        mm2 = h.to_monthly(rr2)
        for m in months:
            if m > cut:
                break
            n += 1
            if abs(mm2[m] - full_m[m]) > 1e-12:
                fails.append(('perturb', cut, m))
        for k in ks:
            n += 1
            if e2(k) != full_pos[k]:
                fails.append(('pos_perturb', cut, k))
    # ③ 同じ月の中のリターンを並べ替える（全期間の各月）
    by = {}
    for k in ks:
        by.setdefault(k // 100, []).append(k)
    dsh = {}
    for m, dsl in by.items():
        vals = [d[k] for k in dsl]
        rnd.shuffle(vals)
        dsh.update(zip(dsl, vals))
    e3 = _expo(spec, list(dsh))
    for k in ks:
        n += 1
        if e3(k) != full_pos[k]:
            fails.append(('pos_shuffle', k))
    return {'ok': not fails, 'checks': n, 'fails': fails[:10]}


if __name__ == '__main__':
    import json
    if len(sys.argv) > 1 and sys.argv[1] == '--test':
        sp = json.loads(sys.argv[2])
        print(json.dumps(lookahead_test(sp), ensure_ascii=False))
        sys.exit(0)
    sp = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {'type': 'halloween', 'winter': 1, 'summer': 0}
    r = run(sp)
    print(json.dumps(h.stats(r['ret'], r['bench'], r['rf'], turnover=r['turnover'], cost=r['cost']), ensure_ascii=False))
