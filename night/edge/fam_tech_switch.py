#!/usr/bin/env python3
"""night/edge/fam_tech_switch.py — 系統 tech_switch（第5回）: テックと市場の入れ替え（相対の勢い）

  テック＝Ken French '49_Industry_Portfolios' の Hardw・Softw・Chips を、その月の組入れ時点（前月末）の時価総額
  （'Number of Firms in Portfolios' × 'Average Firm Size'）で加重した月次リターン（night/gaps_common.french_tech と同じ作り）。
  規則: 月 m の持ち高は、m−J〜m−1 月の J か月の累積リターンで テック と 米国市場 を比べて決める
        （相対 rel = Π(1+テック)/Π(1+市場) − 1）。
    mode='simple': rel > d ならテック、そうでなければ市場
    mode='band'  : rel > +d ならテックへ、rel < −d なら市場へ、その間は前月の持ち高のまま（行ったり来たりを減らす）
  相手: 米国市場（h.us_market）。費用: 入れ替え1回＝片道の回転 1.0 × 0.001（XLK/QQQ ⇄ VTI）。
  ⚠ 月 m の信号は m−1 月末までのリターンだけ（テックの加重に使う時価総額も French の定義で組入れ時点＝前月末）。
  読むだけ・門の採点に不使用。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as h

FAMILY = {
    'key': 'tech_switch',
    'name': 'テックと市場の入れ替え（相対の勢い）',
    'implement': ('毎月末に、過去Jか月の XLK（または QQQ）と VTI の配当込みリターンを比べ、翌月はどちらか一方を全額持つ。'
                  '楽天証券の米国ETF（XLK・QQQ・VTI）で実行できる。NISA の成長投資枠でも買えるが、NISA は買うたびに年間の枠を'
                  '使い売っても枠はその年に戻らないため、毎月の入れ替えは実質 課税口座（特定口座）向き。課税口座では入れ替えの'
                  'たびに売却益に約20%の税がかかる（主の判定では税を入れない）。投信なら iFreeNEXT NASDAQ100 ⇄ eMAXIS Slim 米国株式'
                  '（S&P500）でも同じことができるが、枠の使い方は同じ問題がある'),
}

TECH = ('Hardw', 'Softw', 'Chips')
COST = 0.001                      # 事前登録: 指数・ETF・業種の入れ替えは回転100%につき0.10%


def tech_series():
    """Hardw・Softw・Chips の時価総額加重（組入れ時点＝前月末の 社数×平均時価総額）→ {YYYYMM: 小数}。guard 済み"""
    d = h.french('49_Industry_Portfolios')
    ret = d['Average Value Weighted Returns -- Monthly']
    nf = d['Number of Firms in Portfolios']
    sz = d['Average Firm Size']
    months = sorted(set().union(*[set(ret[k]) for k in TECH]))
    out = {}
    for m in months:
        if m < 99999:
            continue
        num = den = 0.0
        for k in TECH:
            r = ret[k].get(m)
            w = (nf[k].get(m) or 0) * (sz[k].get(m) or 0)
            if r is None or w <= 0:
                continue
            num += w * r / 100
            den += w
        if den > 0:
            out[m] = num / den
    return out


def positions(tech, mkt, J, d=0.0, mode='simple'):
    """{YYYYMM: 'T'|'M'} 月 m の持ち高。m−J〜m−1 の月だけを使う（月 m 自身のリターンは使わない）。
    信号が作れない月（履歴が J か月そろわない）は市場。"""
    months = sorted(set(tech) & set(mkt))
    pos, prev = {}, 'M'
    for m in months:
        past = [h.add_months(m, -i) for i in range(J, 0, -1)]
        if all(p in tech and p in mkt for p in past):
            gt = gm = 1.0
            for p in past:
                gt *= 1 + tech[p]
                gm *= 1 + mkt[p]
            rel = gt / gm - 1
            if mode == 'band':
                cur = 'T' if rel > d else ('M' if rel < -d else prev)
            else:
                cur = 'T' if rel > d else 'M'
        else:
            cur = 'M'
        pos[m] = cur
        prev = cur
    return pos


def build(tech, mkt, pos):
    ret, tov, prev = {}, {}, None
    for m in sorted(pos):
        p = pos[m]
        ret[m] = tech[m] if p == 'T' else mkt[m]
        tov[m] = 1.0 if (prev is not None and p != prev) else 0.0
        prev = p
    return ret, tov


def run(spec):
    J = int(spec.get('J', 12))
    d = float(spec.get('d', 0.0))
    mode = spec.get('mode', 'simple')
    mkt, rf = h.us_market()
    tech = tech_series()
    pos = positions(tech, mkt, J, d, mode)
    ret, tov = build(tech, mkt, pos)
    bench = {m: mkt[m] for m in ret}
    return {'ret': ret, 'bench': bench, 'rf': {m: rf[m] for m in ret if m in rf},
            'turnover': tov, 'cost': COST, 'markets': {}, 'positions': pos}


def lookahead_test():
    """先読みの検査（選定の段のデータだけで行う）。
    (1) 切り詰め: 入力を 1960-12 / 1980-12 / 1990-12 で切って作った持ち高が、全データ（〜2000-12）で作った持ち高と、
        切った月までで1つも違わない。
    (2) 同じ月の撹乱: 月 m のテック・市場のリターンを極端な値（+300% / −90%）に書き換えても、月 m の持ち高は変わらない
        （変わってよいのは m+1 以降だけ）。全ての月で確かめる代わりに 1950〜2000 の各年の6月で確かめる。
    (3) 1か月ずらし: 入力を1か月後ろへずらすと、持ち高もちょうど1か月後ろへずれる。"""
    mkt, _ = h.us_market()
    tech = tech_series()
    res = {'truncate': {}, 'same_month': 0, 'same_month_bad': [], 'shift_bad': 0}
    for (J, d, mode) in [(3, 0.0, 'simple'), (6, 0.02, 'band'), (12, 0.05, 'simple'), (12, 0.05, 'band')]:
        full = positions(tech, mkt, J, d, mode)
        for cut in (196012, 198012, 199012):
            t2 = {m: v for m, v in tech.items() if m <= cut}
            m2 = {m: v for m, v in mkt.items() if m <= cut}
            part = positions(t2, m2, J, d, mode)
            bad = [m for m in part if part[m] != full[m]]
            res['truncate'][f'J{J}_d{d}_{mode}_{cut}'] = len(bad)
        for y in range(1950, 2001):
            m = y * 100 + 6
            for shock in (3.0, -0.9):
                t3 = dict(tech); m3 = dict(mkt)
                t3[m] = shock
                m3[m] = -0.5 if shock > 0 else 2.0
                p3 = positions(t3, m3, J, d, mode)
                res['same_month'] += 1
                if p3[m] != full[m]:
                    res['same_month_bad'].append((J, d, mode, m))
        ts = {h.add_months(m, 1): v for m, v in tech.items()}
        ms = {h.add_months(m, 1): v for m, v in mkt.items()}
        ps = positions(ts, ms, J, d, mode)
        res['shift_bad'] += sum(1 for m, v in full.items() if ps.get(h.add_months(m, 1)) != v)
    res['ok'] = (all(v == 0 for v in res['truncate'].values()) and not res['same_month_bad'] and res['shift_bad'] == 0)
    return res


if __name__ == '__main__':
    import json
    print(json.dumps(lookahead_test(), ensure_ascii=False)[:2000])
