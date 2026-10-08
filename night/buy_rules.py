#!/usr/bin/env python3
"""night/buy_rules.py — out/buyrule_prereg.json を書いてあるとおりに測る（読むだけ・門・配分には触れない）

問い: 今のポートフォリオ（ETF側 NASDAQ100 50 / XLK 15 / SMH 20 を目標の比に）へ毎月同じ額を積み立てるとき、
      今の買い方（区分の不足の比で配る＝割り方 cat）より最終の金額を大きくする買い方はあるか。
データ: 1985-10〜（NASDAQ100＝QQQ／それより前は ^NDX＋g・XLK／FSPTX・SMH／FSELX）と実物のETFだけ（2000-06〜）。
        円は DEXJPUS の月末値。現金はドルなら TB3MS・円なら日本のコールレート IRSTCI01JPM156N。
規則: R0（今の買い方）・R1 固定の比・R2 参考の売るリバランス・R3〜R5 不足を埋める順番・T1〜T4 現金で待つ。
先読み: 各月の始めの判断（合図・過去12か月のリターン・最高値・10か月の平均）は前の月の終わりまでの値だけで決める。
        合図に使う NASDAQ100 はドルの配当込みの指数（円で見るときも同じ合図）。
出力: out/buy_rules.json
使い方: python3 night/buy_rules.py
"""
import datetime, json, math, os, statistics as S, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import etf_longest as L   # Yahoo の月足（1971年から要求する版）
import gaps_common as G   # FRED

B = ['NDX', 'XLK', 'SMH']
W = {'NDX': 50 / 85, 'XLK': 15 / 85, 'SMH': 20 / 85}
RULES = ['R0', 'R1', 'R2', 'R3', 'R4', 'R5', 'T1', 'T2', 'T3', 'T4']


def rets(s):
    ks = sorted(s)
    return {b: s[b] / s[a] - 1 for a, b in zip(ks, ks[1:])}


def ikey(m):
    return int(m[:4]) * 100 + int(m[5:7])


def corr(a, b):
    ma, mb = S.mean(a), S.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return num / math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))


def load():
    raw = {t: L.fetch(t) for t in ['QQQ', 'XLK', 'SMH', '^NDX', 'FSPTX', 'FSELX']}
    miss = [t for t, v in raw.items() if not v]
    if miss:
        raise SystemExit('✗ 取れない: ' + ' '.join(miss))
    R = {t: rets(v) for t, v in raw.items()}
    ov = sorted(m for m in R['QQQ'] if m in R['^NDX'])
    g = S.mean(R['QQQ'][m] - R['^NDX'][m] for m in ov)

    def splice(gg):
        ndx = {m: (R['QQQ'][m] if m in R['QQQ'] else R['^NDX'][m] + gg) for m in R['^NDX']}
        xlk = {m: (R['XLK'][m] if m in R['XLK'] else R['FSPTX'][m]) for m in R['FSPTX']}
        smh = {m: (R['SMH'][m] if m in R['SMH'] else R['FSELX'][m]) for m in R['FSELX']}
        ms = sorted(set(ndx) & set(xlk) & set(smh))
        return ms, {'NDX': [ndx[m] for m in ms], 'XLK': [xlk[m] for m in ms], 'SMH': [smh[m] for m in ms]}

    main_ms, main = splice(g)
    _, main_g0 = splice(0.0)
    act_ms = sorted(set(R['QQQ']) & set(R['XLK']) & set(R['SMH']))
    act = {'NDX': [R['QQQ'][m] for m in act_ms], 'XLK': [R['XLK'][m] for m in act_ms], 'SMH': [R['SMH'][m] for m in act_ms]}
    chk = {}
    for p, a in (('^NDX+g', 'QQQ'), ('FSPTX', 'XLK'), ('FSELX', 'SMH')):
        src = '^NDX' if p == '^NDX+g' else p
        ms = sorted(m for m in R[a] if m in R[src])
        chk[f'{p} 対 {a}'] = dict(月=len(ms), 相関=round(corr([R[src][m] for m in ms], [R[a][m] for m in ms]), 3),
                                 年率の差=round((math.prod(1 + R[src][m] + (g if p == '^NDX+g' else 0) for m in ms) ** (12 / len(ms))
                                               - math.prod(1 + R[a][m] for m in ms) ** (12 / len(ms))) * 100, 2))
    return dict(g=g, main_ms=main_ms, main=main, main_g0=main_g0, act_ms=act_ms, act=act, check=chk)


def fred_monthly(sid, ms, pct=True):
    d = G.fred(sid)
    out, last = [], None
    for m in ms:
        v = d.get(ikey(m), last)
        if v is None:
            raise SystemExit(f'✗ {sid} が {m} に無い')
        last = v
        out.append(v)
    return out


def to_yen(ret, ms, fx):
    out = {}
    for b in B:
        r = []
        for i, m in enumerate(ms):
            k, kp = ikey(m), ikey(prev_month(m))
            r.append((1 + ret[b][i]) * fx[k] / fx[kp] - 1)
        out[b] = r
    return out


def prev_month(m):
    y, mo = int(m[:4]), int(m[5:7]) - 1
    if mo == 0:
        y, mo = y - 1, 12
    return f'{y:04d}-{mo:02d}'


def irr(fv, n):
    """毎月の始めに1ずつ n回入れて、n か月後に fv になった年率"""
    lo, hi = -0.99, 2.0
    for _ in range(80):
        r = (lo + hi) / 2
        m = (1 + r) ** (1 / 12)
        gsum = n if abs(m - 1) < 1e-12 else m * (m ** n - 1) / (m - 1)
        if gsum < fv:
            lo = r
        else:
            hi = r
    return (lo + hi) / 2


def alloc(rule, H, A, ctx):
    """今月 A を配る。H は株の区分ごとの金額（現金を除く）。戻り値＝区分ごとの配分"""
    if A <= 0:
        return {b: 0.0 for b in B}
    T = sum(H.values())
    need = {b: max(0.0, W[b] * (T + A) - H[b]) for b in B}
    sn = sum(need.values())
    if rule == 'R1':
        return {b: A * W[b] for b in B}
    if rule in ('R0', 'R2', 'T1', 'T2', 'T3', 'T4') or rule not in ('R3', 'R4', 'R5'):
        if sn >= A and sn > 0:
            return {b: A * need[b] / sn for b in B}
        return {b: need[b] + (A - sn) * W[b] for b in B}
    # R3〜R5: 不足のある区分を順に埋める
    if rule == 'R3':
        order = sorted((b for b in B if need[b] > 0), key=lambda b: -need[b] / (W[b] * (T + A)))
    else:
        tr = ctx.get('trail')
        if tr is None:   # 過去のリターンがまだ無い最初の月は R0
            return alloc('R0', H, A, ctx)
        order = sorted((b for b in B if need[b] > 0), key=lambda b: tr[b] if rule == 'R4' else -tr[b])
    out = {b: 0.0 for b in B}
    rem = A
    for b in order:
        x = min(rem, need[b])
        out[b] += x
        rem -= x
        if rem <= 1e-15:
            break
    if rem > 1e-15:
        for b in B:
            out[b] += rem * W[b]
    return out


def simulate(rule, ret, cash_r, sig, s, n):
    """起点 s から n か月、毎月の始めに1を入れる。戻り値＝(最終の金額, 現金の割合の平均, 最終の比率のずれの最大)"""
    H = {b: 0.0 for b in B}
    cash = 0.0
    reserve = 0.0
    cash_share = []
    for i in range(n):
        t = s + i
        ctx = {'trail': sig['trail'][t]}
        if rule in ('T1', 'T2', 'T3'):
            cash += 1.0
            go = sig['above_ma'][t] if rule == 'T1' else (sig['dd'][t] <= (-0.10 if rule == 'T2' else -0.20))
            if go:
                a = alloc('R0', H, cash, ctx)
                for b in B:
                    H[b] += a[b]
                cash = 0.0
        elif rule == 'T4':
            a = alloc('R0', H, 0.8, ctx)
            for b in B:
                H[b] += a[b]
            reserve += 0.2
            if sig['dd'][t] <= -0.20 and reserve > 0:
                a = alloc('R0', H, reserve, ctx)
                for b in B:
                    H[b] += a[b]
                reserve = 0.0
        else:
            a = alloc(rule, H, 1.0, ctx)
            for b in B:
                H[b] += a[b]
            if rule == 'R2':
                T = sum(H.values())
                H = {b: T * W[b] for b in B}
        # その月のリターン
        for b in B:
            H[b] *= 1 + ret[b][t]
        cash *= 1 + cash_r[t]
        reserve *= 1 + cash_r[t]
        tot = sum(H.values()) + cash + reserve
        cash_share.append((cash + reserve) / tot if tot > 0 else 0.0)
    T = sum(H.values())
    drift = max(abs(H[b] / T - W[b]) for b in B) if T > 0 else 0.0
    return T + cash + reserve, S.mean(cash_share), drift


def signals(ret_usd_ndx, ret_all):
    """各月 t の始めに使える合図（前の月の終わりまで）。ret_usd_ndx＝ドルの NASDAQ100 の月次リターン"""
    n = len(ret_usd_ndx)
    lvl = [1.0]
    for r in ret_usd_ndx:
        lvl.append(lvl[-1] * (1 + r))      # lvl[t] ＝ 月 t の始め（＝前の月の終わり）の水準
    above_ma, dd, trail = [], [], []
    ath = 0.0
    for t in range(n):
        ath = max(ath, lvl[t])
        dd.append(lvl[t] / ath - 1)
        win = lvl[max(0, t - 9): t + 1]
        above_ma.append(lvl[t] >= S.mean(win))
        if t == 0:
            trail.append(None)
        else:
            k = max(0, t - 12)
            trail.append({b: math.prod(1 + x for x in ret_all[b][k:t]) - 1 for b in B})
    return dict(above_ma=above_ma, dd=dd, trail=trail)


def run(ret, cash_r, sig, horizons=(240, 180, 120)):
    n = len(ret['NDX'])
    out = {}
    for H in horizons:
        if n < H:
            continue
        starts = list(range(0, n - H + 1))
        res = {r: [] for r in RULES}
        for s in starts:
            for r in RULES:
                fv, cs, dr = simulate(r, ret, cash_r, sig, s, H)
                res[r].append((irr(fv, H), fv / H, cs, dr))
        base = [x[0] for x in res['R0']]
        half = len(starts) // 2
        o = {}
        for r in RULES:
            ir = [x[0] for x in res[r]]
            d = [a - b for a, b in zip(ir, base)]
            o[r] = dict(窓=len(ir), 年率_中央=round(S.median(ir) * 100, 2), 年率_最悪=round(min(ir) * 100, 2),
                        倍率_中央=round(S.median(x[1] for x in res[r]), 3),
                        R0との差_中央=round(S.median(d) * 100, 3), R0との差_最小=round(min(d) * 100, 3), R0との差_最大=round(max(d) * 100, 3),
                        R0に勝った割合=round(sum(1 for x in d if x > 1e-12) / len(d), 3),
                        前半の差_中央=round(S.median(d[:half]) * 100, 3), 後半の差_中央=round(S.median(d[half:]) * 100, 3),
                        現金の割合_中央=round(S.median(x[2] for x in res[r]) * 100, 1),
                        最終のずれ_中央=round(S.median(x[3] for x in res[r]) * 100, 1))
        out[f'{H // 12}年'] = o
    return out


def main():
    D = load()
    ms = D['main_ms']
    tb = fred_monthly('TB3MS', ms)
    jp = fred_monthly('IRSTCI01JPM156N', ms)
    fxd = G.fred('DEXJPUS')
    cash_usd = [x / 1200 for x in tb]
    cash_jpy = [x / 1200 for x in jp]
    main_yen = to_yen(D['main'], ms, fxd)
    sig_main = signals(D['main']['NDX'], D['main'])
    sig_main_g0 = signals(D['main_g0']['NDX'], D['main_g0'])
    am = D['act_ms']
    ai = [ms.index(m) for m in am]
    act_cash_usd = [cash_usd[i] for i in ai]
    act_cash_jpy = [cash_jpy[i] for i in ai]
    act_yen = to_yen(D['act'], am, fxd)
    sig_act = signals(D['act']['NDX'], D['act'])
    variants = {
        '主_ドル（1985-10〜・代理つなぎ）': (D['main'], cash_usd, sig_main, ms),
        '主_円': (main_yen, cash_jpy, sig_main, ms),
        '実物ETF_ドル（2000-06〜）': (D['act'], act_cash_usd, sig_act, am),
        '実物ETF_円': (act_yen, act_cash_jpy, sig_act, am),
        '感度_ドル_配当の推定g=0': (D['main_g0'], cash_usd, sig_main_g0, ms),
    }
    res = {}
    for k, (ret, cr, sg, mm) in variants.items():
        res[k] = dict(期間=f'{prev_month(mm[0])} → {mm[-1]}（{len(mm)}か月）', 結果=run(ret, cr, sg))
        print('  済', k, flush=True)
    # 判定（事前登録の線）
    M = res['主_ドル（1985-10〜・代理つなぎ）']['結果']['20年']
    Y = res['主_円']['結果']['20年']
    A = res['実物ETF_ドル（2000-06〜）']['結果'].get('20年')
    verdict = {}
    for r in RULES:
        if r == 'R0':
            continue
        m, y = M[r], Y[r]
        a_ok = m['R0との差_中央'] >= 0.25
        b_ok = m['R0に勝った割合'] >= 0.70
        c_ok = m['前半の差_中央'] > 0 and m['後半の差_中央'] > 0
        d_ok = y['R0との差_中央'] >= 0.25 and y['R0に勝った割合'] >= 0.70
        e_ok = (A is not None) and A[r]['R0との差_中央'] > 0
        ok = a_ok and b_ok and c_ok and d_ok and e_ok
        verdict[r] = dict(a=a_ok, b=b_ok, c=c_ok, d=d_ok, e=e_ok,
                          判定=('参考（売る・採らない）' + ('：線は満たした' if ok else '：線は満たさない')) if r == 'R2' else ('今の買い方より良い' if ok else '良いとは言えない'))
    better = [r for r, v in verdict.items() if r != 'R2' and v['判定'] == '今の買い方より良い']
    out = dict(generated=datetime.date.today().isoformat(), prereg='out/buyrule_prereg.json', tool='night/buy_rules.py',
               目標の比=W, NASDAQ100の配当の推定g_月=round(D['g'], 6), NASDAQ100の配当の推定g_年=round(((1 + D['g']) ** 12 - 1) * 100, 2),
               代理と実物の重なり=D['check'], 合図='ドルの NASDAQ100（配当込み）。円で見るときも同じ合図',
               結果=res, 判定=verdict, 結論=('今の買い方より良い買い方: ' + '・'.join(better)) if better else '今の買い方より良い買い方は見つからなかった')
    with open(os.path.join(BASE, 'out', 'buy_rules.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write('\n')
    print(json.dumps({k: out[k] for k in ('NASDAQ100の配当の推定g_年', '代理と実物の重なり', '結論')}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
