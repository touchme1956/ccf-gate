#!/usr/bin/env python3
"""night/edge/fam_volmom.py — 系統 volmom（第2回）: 大型の勝ち組を「ぶれ」で調整して持つ（Barroso & Santa-Clara 2015 の買いだけ版）

  素材: Ken French '6_Portfolios_ME_Prior_12_2_Daily' の BIG HiPRIOR（大型×過去12−2か月の勝ち組・時価加重・日次）
  規則: 持ち高 w = 目標ぶれ ÷ その組の直近の実現ぶれ（直近 L 営業日・前日の終値まで）。上限 cap・下限 0。
        w ≤ 1 の残りは短期金利。w > 1 の超えた分は h.lev_daily と同じ（借入 rf＋0.4%/年・経費 0.9%/年）。
  相手: 米国市場（French Mkt-RF＋RF）。費用: 回転1あたり 0.25%（組の中の回転 200%/年×w ＋ 持ち高の変化 |Δw|）。
  再現: French の国際版 '{地域}_6_Portfolios_ME_Prior_250_20_Daily'（1990-11〜・日次で組み直す版）に同じ規則をそのまま当てる。
        相手はその地域の市場（French の地域3因子の Mkt-RF＋RF・米ドル）。

  ⚠ 覗き見の防止: データは harness の読み込み関数（french / us_market / us_market_daily / french_region）だけで読む。
    期間は決め打ちしない（EDGE_PHASE=select なら 2000-12 で切れ、holdout なら全期間が来る）。
    月 m の持ち高は「月 m の最初の営業日より前」の日次リターンだけで作る（日次の組み替えなら「その日より前」）。
    期待値や全期間のぶれで標準化しない（目標を『自分の長期のぶれ』にするときも、その時点までの累積だけを使う）。
"""
import sys, os, math, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h

FAMILY = {
    'key': 'volmom',
    'name': 'ぶれで調整した大型の勝ち組（買いだけ）',
    'implement': ('米国の大型モメンタムETF（iShares MSCI USA Momentum Factor＝MTUM・楽天証券の米国株口座で買える・'
                  'NISA 成長投資枠で可）を月末に1回、持ち高＝目標ぶれ÷直近のぶれ で持ち、残りは米ドルMMF／短期国債（外貨MMF）。'
                  '1倍を超える持ち高は信用取引（課税口座・NISA不可）か、1倍を上限にして使わない。'
                  'ぶれは MTUM の日次の終値から毎月末に計算する（表計算で足りる）')
}

DEF = {'port': 'BIG HiPRIOR', 'lookback': 126, 'target': 'own', 'cap': 1.5, 'floor': 0.0,
       'rebal': 'monthly', 'est': 'vol', 'own_min_days': 252, 'spread': 0.004, 'fee': 0.009,
       'cost': 0.0025, 'inner_turnover': 2.0, 'markets': ['Europe', 'Japan', 'Asia_Pacific_ex_Japan']}
US_FILE = '6_Portfolios_ME_Prior_12_2_Daily'
INTL_FILE = '{}_6_Portfolios_ME_Prior_250_20_Daily'
VW = 'Average Value Weighted Returns -- Daily'
DAYS = 252


# ───────────────────────── 素材 ─────────────────────────
def load(src, port):
    """→ (p_daily, mkt_daily, rf_daily, bench_monthly, rf_monthly)。すべて小数・guard 済み"""
    if src == 'US':
        d = h.french(US_FILE)[VW][port]
        mkd, rfd = h.us_market_daily()
        bm, rfm = h.us_market()
    else:
        d = h.french(INTL_FILE.format(src))[VW][port]
        mkd, rfd = h.french_region(src, daily=True)
        bm, rfm = h.french_region(src, daily=False)
    p = {k: v / 100 for k, v in d.items() if k > 9999999}
    return p, mkd, rfd, bm, rfm


class Vol:
    """日次の系列の「ある日より前」の実現ぶれ（平均を引かない二乗平均・年率）。cutoff より前の日だけを使う"""

    def __init__(self, daily):
        self.days = sorted(daily)
        self.cs = [0.0]
        for k in self.days:
            self.cs.append(self.cs[-1] + daily[k] ** 2)

    def n_before(self, cutoff):
        return bisect.bisect_left(self.days, cutoff)          # cutoff より前の日の数（cutoff 当日は入らない）

    def trailing(self, cutoff, L):
        i = self.n_before(cutoff)
        if i < L:
            return None
        return math.sqrt(DAYS * (self.cs[i] - self.cs[i - L]) / L)

    def expanding(self, cutoff, min_days):
        i = self.n_before(cutoff)
        if i < min_days:
            return None
        return math.sqrt(DAYS * self.cs[i] / i)


def weight(spec, vp, vm, cutoff):
    """cutoff（YYYYMMDD）の前日の終値までで決める持ち高。決まらなければ None"""
    L = spec['lookback']
    s = vp.trailing(cutoff, L)
    if not s or s <= 0:
        return None
    tg = spec['target']
    if tg == 'own':
        tgt = vp.expanding(cutoff, spec['own_min_days'])
    elif tg == 'mkt':
        tgt = vm.trailing(cutoff, L)
    elif tg == 'none':
        return 1.0
    else:
        tgt = float(tg)
    if tgt is None:
        return None
    w = (tgt / s) ** 2 if spec['est'] == 'var' else tgt / s
    return min(spec['cap'], max(spec['floor'], w))


def day_ret(x, f, w, spec):
    if w <= 1:
        return w * x + (1 - w) * f
    return w * x - (w - 1) * (f + spec['spread'] / DAYS) - spec['fee'] / DAYS   # h.lev_daily と同じ式


def build(spec, src):
    """→ {'ret','bench','rf','turnover','cost','w'}（月次）"""
    p, mkd, rfd, bm, rfm = load(src, spec['port'])
    vp, vm = Vol(p), Vol(mkd)
    days = sorted(p)
    bymonth = {}
    for d in days:
        bymonth.setdefault(d // 100, []).append(d)
    ret, tov, wmon = {}, {}, {}
    prev_w = None
    started = False
    for m in sorted(bymonth):
        ds = bymonth[m]
        if spec['rebal'] == 'daily':
            ws = [weight(spec, vp, vm, d) for d in ds]
            if any(w is None for w in ws):
                if started:
                    raise RuntimeError(f'持ち高が途中で決まらない {src} {m}')
                continue
        else:
            w0 = weight(spec, vp, vm, m * 100 + 1)             # 月 m の最初の日より前（＝m−1 月末の終値まで）
            if w0 is None:
                if started:
                    raise RuntimeError(f'持ち高が途中で決まらない {src} {m}')
                continue
            ws = [w0] * len(ds)
        started = True
        g = 1.0
        dw = 0.0
        for d, w in zip(ds, ws):
            g *= 1 + day_ret(p[d], rfd.get(d, 0.0), w, spec)
            dw += abs(w - prev_w) if prev_w is not None else w
            prev_w = w
        ret[m] = g - 1
        wbar = sum(ws) / len(ws)
        tov[m] = wbar * spec['inner_turnover'] / 12 + dw
        wmon[m] = wbar
    return {'ret': ret, 'bench': {m: bm[m] for m in ret if m in bm}, 'rf': {m: rfm[m] for m in ret if m in rfm},
            'turnover': tov, 'cost': spec['cost'], 'w': wmon}


def run(spec):
    sp = dict(DEF)
    sp.update(spec or {})
    us = build(sp, 'US')
    mk = {}
    for reg in sp.get('markets') or []:
        x = build(sp, reg)
        mk[reg] = {k: x[k] for k in ('ret', 'bench', 'rf', 'turnover', 'cost')}
    return {'ret': us['ret'], 'bench': us['bench'], 'rf': us['rf'], 'turnover': us['turnover'], 'cost': us['cost'],
            'markets': mk, 'weights': us['w']}
