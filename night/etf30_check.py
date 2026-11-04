#!/usr/bin/env python3
"""night/etf30_check.py — 過去リターンの高い ETF 30本を、今の配分に5%入れた形で全部測る（2026-11-04・参考・配分は変えない）

ユーザー「有力な過去リターンを高くだしたETFで、候補になり得るものを30上げて」→「全て調べ上げて」。
30本＝out/etf_longest.json（楽天の海外ETF・記録10年以上）を同じ窓の S&P500 との差で並べた上位30（会話で示した表）。
門・採点・配分（portfolio.json）・注文書には触れない。★形・物差し・決まりはこの頭のとおりで、回す前にコミットする。

形: 今＝NASDAQ100 40 / SMH 20 / ITA 15 / XLV 10 / VBR 15（portfolio.json と照合）。候補 X＝今の NASDAQ100 から5を X へ（etf_add と同じ置き方）。
  X が今の本（SMH・ITA）なら その本が +5。X が QQQ なら今と同じ（測るまでもない）。
物差し:
 ①実績（全30本）: Yahoo の配当込み月次・ドル建て・毎月組み直し。今の5本は QQQ/SMH/ITA/XLV/VBR の本物。
   W20＝2006-10〜2026-09（X がそろう本だけ）・W10＝2016-10〜2026-09。年率・最大下落・ぶれの今との差。
   X 単体: W10 の年率・今の形との月次の相関・今の5本との相関の最大。
 ②未来の物差し（best15 の Fast・best15r の FastBR〔感度6本〕・Cent〔100年の代用〕）:
   X が物差しの本（best15r.POOL）なら X そのもの。無ければ W10 の月次の相関が0.95以上の物差しの本があればその本で代える（同じ賭け・名指し）。
   どちらも無ければ「未来は測れない」。
決まり（結果を見る前に固定）:
  実績が通る＝W10 で 年率の差>0 かつ 最大下落の深まり≤1pt、W20 がそろう本は W20 でも同じ。
  未来が通る＝元の平均の差≥0 かつ 業種の基礎率の平均の差が感度6本すべてで≥0。
  「候補に残る」＝両方が通る。実績だけ通る＝「過去だけ」・未来だけ通る＝「未来の物差しだけ」・未来が測れない＝その旨。
⚠ 限界: 実績は2006年以降の一つの時代（テックが勝った時代）・未来の物差しは予想と仮定・同じ賭けの代用は近似・5%の差は雑音に近い・円・税は見ない
使い方: python3 night/etf30_check.py → out/etf30_check.json
追記（2026-11-04・ユーザー「VBR ITA XLV から回すとどうなるかも確認して」）: --src VBR|ITA|XLV で 5% を回す元を替える
  （→ out/etf30_check_{src}.json）。決まり・物差し・30本は同じ。X が回す元と同じ本なら測らない（今と同じ）。
  QQQ は元が NASDAQ100 以外なら NASDAQ100 を +5 する形として普通に測る。この追記は結果を見る前にコミットする
"""
import contextlib, io, json, math, os, sys, time
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
SRC = sys.argv[sys.argv.index('--src') + 1] if '--src' in sys.argv else 'QQQM'
assert SRC in ('QQQM', 'VBR', 'ITA', 'XLV'), SRC
OUT = os.path.join(BASE, 'out', 'etf30_check.json' if SRC == 'QQQM' else f'etf30_check_{SRC}.json')

LIST30 = ('FTXL QTEC VGT BBH FXL IXN MGK FDN SMH FBT QQQ CIBR VOOG VONG EWY XLK VUG ITA IJR SKYY '
          'FPX TDIV IJH AIRR HACK RTH XLY MGC XLI XLE').split()
NOW = {'QQQM': 40, 'SMH': 20, 'ITA': 15, 'XLV': 10, 'VBR': 15}
REAL = {'QQQM': 'QQQ', 'SMH': 'SMH', 'ITA': 'ITA', 'XLV': 'XLV', 'VBR': 'VBR'}
W20, W10 = (200610, 202609), (201610, 202609)
CORR_SAME = 0.95


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def months(a, b):
    y, m, out = a // 100, a % 100, []
    while y * 100 + m <= b:
        out.append(y * 100 + m)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def form_of(x):
    f = dict(NOW)
    if x in ('QQQ', 'QQQM'):
        return f
    k = x if x in f else x
    f['QQQM'] -= 5
    f[k] = f.get(k, 0) + 5
    return f


def path(f, ret, ms):
    """毎月組み直しの月次リターン（f の鍵は実在のティッカー）"""
    tot = sum(f.values())
    return np.array([sum(w / tot * ret[t][m] for t, w in f.items()) for m in ms])


def stats(r):
    v = np.cumprod(1 + r)
    cagr = v[-1] ** (12 / len(r)) - 1
    dd = float(np.min(v / np.maximum.accumulate(v) - 1))
    return dict(年率=round(cagr * 100, 2), 最大下落=round(dd * 100, 1), ぶれ=round(float(np.std(r) * math.sqrt(12) * 100), 1))


def main():
    t0 = time.time()
    t = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    w = {('QQQM' if k == 'IFREE-NDX' else k): v for k, v in t['ami_weights'].items() if v}
    if w != NOW or float(t.get('shiro_castle_pct') or 0) != 0:
        raise SystemExit(f'今の形が正本と違う: {w}')
    import mw_common as M
    tick = sorted(set(LIST30) | set(REAL.values()))
    ret = {}
    for x in tick:
        try:
            ret[x] = M.yahoo(x)
        except Exception as e:
            log('取れない', x, e)
    real_now = {REAL[k]: v for k, v in NOW.items()}

    def real_form(x):
        f = dict(real_now)
        rs = REAL[SRC]
        if x == rs:
            return f
        f[rs] -= 5
        f[x] = f.get(x, 0) + 5
        return f
    res = {}
    for wn, (a, b) in (('W20', W20), ('W10', W10)):
        ms = months(a, b)
        if not all(all(m in ret[t] for m in ms) for t in real_now):
            raise SystemExit(f'今の5本が {wn} にそろわない')
        base = path(real_now, ret, ms)
        s0 = stats(base)
        res[wn] = dict(今=s0)
        for x in LIST30:
            if x not in ret or not all(m in ret[x] for m in ms):
                continue
            s = stats(path(real_form(x), ret, ms))
            res[wn][x] = dict(s, 年率の差=round(s['年率'] - s0['年率'], 2), 最大下落の差=round(s['最大下落'] - s0['最大下落'], 1),
                              ぶれの差=round(s['ぶれ'] - s0['ぶれ'], 1))
    ms10 = months(*W10)
    base10 = path(real_now, ret, ms10)
    single = {}
    for x in LIST30:
        if x not in ret or not all(m in ret[x] for m in ms10):
            single[x] = dict(取れない=True)
            continue
        xr = np.array([ret[x][m] for m in ms10])
        cs = {t_: float(np.corrcoef(xr, np.array([ret[t_][m] for m in ms10]))[0, 1]) for t_ in real_now}
        tm = max(cs, key=cs.get)
        single[x] = dict(W10の年率=stats(xr)['年率'], W10の最大下落=stats(xr)['最大下落'], 今の形との相関=round(float(np.corrcoef(xr, base10)[0, 1]), 2),
                         今の本との相関の最大=f'{tm} {cs[tm]:.2f}')

    # ② 未来の物差し
    import best15_check as B
    import best15r_check as BR
    import unx_assets as U
    with contextlib.redirect_stdout(io.StringIO()):
        bres = U.build()
    rows, chains = bres['rows'], bres['chains']
    P = BR.POOL
    B.century_extend(U)
    fast, cent = B.Fast(U, rows, chains, P), B.Cent(U, P)
    fbr = BR.FastBR(fast)
    vec, _ = BR.industry_vectors(U, rows)
    st = BR.industry_state()
    adj = {nm: BR.adj_vector(vec, st, rt, P)[0] for nm, rt in BR.RATES.items()}
    a0 = adj['主（20年の値）']
    poolreal = {('QQQ' if p == 'QQQM' else p): p for p in P}
    for p in list(poolreal):
        if p not in ret:
            try:
                ret[p] = M.yahoo(p)
            except Exception:
                pass
    stand = {}
    for x in LIST30:
        if x in poolreal:
            stand[x] = dict(本=poolreal[x], 方法='物差しの本そのもの')
            continue
        if single[x].get('取れない'):
            stand[x] = None
            continue
        xr = np.array([ret[x][m] for m in ms10])
        best = None
        for pr, pp in poolreal.items():
            if pr in ret and all(m in ret[pr] for m in ms10):
                c_ = float(np.corrcoef(xr, np.array([ret[pr][m] for m in ms10]))[0, 1])
                if best is None or c_ > best[1]:
                    best = (pp, c_)
        stand[x] = dict(本=best[0], 方法=f'同じ賭けで代える（W10 の相関 {best[1]:.3f}）') if best and best[1] >= CORR_SAME else \
            dict(本=None, 方法=f'未来は測れない（最も近い物差しの本 {best[0]} の相関 {best[1]:.3f} < {CORR_SAME}）' if best else '未来は測れない')
    keys = ['今'] + [x for x in LIST30 if stand.get(x) and stand[x]['本']]

    def fform(x):
        if x == '今':
            return dict(NOW)
        f = dict(NOW)
        p = stand[x]['本']
        if p == SRC:
            return f
        f[SRC] -= 5
        f[p] = f.get(p, 0) + 5
        return f
    W = np.array([[fform(k).get(c, 0) for c in P] for k in keys], dtype=np.float64)
    e, b, c = fast.eval(W), fbr.eval(W, a0), cent.eval(W)
    vres = {}
    for v in BR.VARS:
        vres[v] = {'主': lambda: fbr.eval(W, a0), '10年の値': lambda: fbr.eval(W, adj['10年の値']),
                   '1位の業種を強く': lambda: fbr.eval(W, adj['1位の業種を強く（10年の値・Chips −4.0）']),
                   '主の半分': lambda: fbr.eval(W, adj['主の半分']), '分散の上乗せなし': lambda: fbr.eval(W, a0, nobonus=True),
                   '共分散をA2の窓から': lambda: fbr.eval(W, a0, cov2=True)}[v]()
    fut, raw = {}, {}
    P100 = lambda v: round(float(v) * 100, 3)   # 小数→%（2026-11-04 是正: 初回は小数のまま丸めて差が0に潰れた・決まりは不変）
    for j, k in enumerate(keys):
        raw[k] = dict(m=float(e['mean_pi'][j] - e['mean_pi'][0]), b={v: float(vres[v]['mean_pi'][j] - vres[v]['mean_pi'][0]) for v in BR.VARS})
        fut[k] = dict(元の平均=P100(e['mean_pi'][j]), 元の15パーセント以上=P100(e['P15'][j]), 元の最大下落=P100(e['mdd'][j]),
                      基礎率の平均=P100(b['mean_pi'][j]), 百年の三十年の中央=round(float(c['c30med'][j]), 3),
                      差=dict(元の平均=P100(e['mean_pi'][j] - e['mean_pi'][0]), 元の15パーセント以上=P100(e['P15'][j] - e['P15'][0]),
                             元の最大下落=P100(e['mdd'][j] - e['mdd'][0]),
                             基礎率の平均_感度6本={v: P100(raw[k]['b'][v]) for v in BR.VARS},
                             百年の中央=round(float(c['c30med'][j] - c['c30med'][0]), 3)))

    # 決まり
    verdict = {}
    for x in LIST30:
        if x == REAL[SRC]:
            verdict[x] = '今と同じ（回す元そのもの）'
            continue
        r10, r20 = res['W10'].get(x), res['W20'].get(x)
        okr = None
        if r10:
            okr = r10['年率の差'] > 0 and r10['最大下落の差'] >= -1.0 and (r20 is None or (r20['年率の差'] > 0 and r20['最大下落の差'] >= -1.0))
        f_ = fut.get(x)
        okf = None if f_ is None else (raw[x]['m'] >= -1e-12 and all(v >= -1e-12 for v in raw[x]['b'].values()))
        if okr is None:
            verdict[x] = '実績が取れない'
        elif okf is None:
            verdict[x] = ('過去だけ通る' if okr else '過去も通らない') + '（未来は測れない）'
        else:
            verdict[x] = {(True, True): '候補に残る', (True, False): '過去だけ通る', (False, True): '未来の物差しだけ通る',
                          (False, False): '通らない'}[(okr, okf)]
    out = dict(generated=time.strftime('%Y-%m-%d'), tool='night/etf30_check.py', kind='参考（配分は変えない・決まりは道具の頭に固定）',
               question='有力な過去リターンを高くだしたETF 30本を全て調べ上げて', 回す元=SRC, 今=NOW,
               判定=verdict, 実績=res, 単体=single, 未来の物差しの本=stand, 未来の物差し=fut, secs=round(time.time() - t0))
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1, default=str)
    for x in LIST30:
        r10, r20, f_ = res['W10'].get(x, {}), res['W20'].get(x), fut.get(x)
        log(f"{x:5} {verdict[x]:<22} W10 {r10.get('年率の差')} {r10.get('最大下落の差')} | W20 {r20 and (r20['年率の差'], r20['最大下落の差'])} | "
            f"未来 {stand[x] and stand[x]['本']} {f_ and (f_['差']['元の平均'], min(f_['差']['基礎率の平均_感度6本'].values()), f_['差']['元の最大下落'], f_['差']['百年の中央'])} | 単体 {single[x]}")
    log('今', res['W10']['今'], res['W20']['今'], fut['今'], f'{time.time() - t0:.0f}秒')


if __name__ == '__main__':
    main()
