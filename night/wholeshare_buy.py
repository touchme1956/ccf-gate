#!/usr/bin/env python3
"""night/wholeshare_buy.py — 1株単位でしか買えないとき、『不足から揃える』と『入金を決まった％で』のどちらが良いか（2026-10-13）

ユーザー（2026-10-13）「どうしても毎月きれいに分散して買うことはできない。株価が変わるごとに揃えるほうがいいのか
合計から決まった％投資したほうがいいのかどっちが良い？」への答えの材料。読むだけ・門・配分には触れない。
事前登録はしていない（判定ではなく参考）。同じ問いの事前登録つきの検証は out/buy_rules.json（R0＝今の買い方・R1＝固定の比・
1株単位は入れていない）と out/rebalance_policy.json。

比べる買い方（ETF側だけ・個別株15%は門の歴史が無いので外す）:
  gap      … 不足から揃える＝門の注文書（割り方 cat・ccfCatBudget＋ccfCatSharePlan）と同じ規則。
             区分の不足 max(0, 目標×(保有＋入金)−保有) の比で割り、1株の本は不足が1株の半分以上で買う。
             買えなかった円・端数は全部 NASDAQ100（iFreeNEXT＝円で端数まで買える）へ
  fixbox   … 決まった％・買えない分は貯める: 毎月 入金×目標 を本ごとの箱に入れ、1株の値段に届いたら買う（箱は現金・利息0）
  fixround … 決まった％・四捨五入: 毎月 入金×目標÷1株 を四捨五入した株数を買い、過不足は NASDAQ100 で吸う
  （参考）gapfrac / fixfrac … 1株単位の制約なし（全部 端数まで買える）の同じ2つ
目標: portfolio.json の target.ami_weights（NASDAQ100 50 / SMH 25 / ITA 10）を ETF側で正規化（58.8 / 29.4 / 11.8%）
データ: 円・月次・配当込み。NASDAQ100＝^NDX＋推定配当（1999-03 から QQQ）、SMH＝FSELX→SMH、ITA＝FSDAX→ITA でつなぐ。
        円は DEXJPUS の月末値。期間 1985-11〜2026-09
1株の値段: 各窓の初月を今日の値（SMH ¥95,499・ITA ¥32,710）に合わせ、その後は値動きどおり。¥150,000 を超えたら2分割
           （ETF の株式分割の代わり・門は1株が今月の入金より高い本を買わないので、分割しないと途中で買えなくなる）
入金: 毎月 ¥170,000（入金20万円×ETF側85%）・売らない
物差し: 最終の金額÷入金の合計（倍率）と門の規則との差／目標から一番ずれた区分のずれ（各月・最初の1年は買い集めの途中なので除く）の
        平均と最大／SMH の比率の最大／箱に寝ている現金の割合
出力: out/wholeshare_buy.json
"""
import datetime, json, math, os, statistics as S, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import etf_longest as L   # Yahoo の月足（1971年から要求する版）
import gaps_common as G   # FRED

PF = json.load(open(os.path.join(BASE, 'portfolio.json')))
AW = PF['target']['ami_weights']
_w = {'NDX': float(AW['IFREE-NDX']), 'SMH': float(AW['SMH']), 'ITA': float(AW['ITA'])}
W = {k: v / sum(_w.values()) for k, v in _w.items()}
PX0 = {'SMH': 95499.0, 'ITA': 32710.0}   # 2026-10-12 の注文書の1株の円（門の盤の値段×ドル円）
D = 170000.0
SPLIT = 150000.0
WHOLE = ('SMH', 'ITA')
RULES = ('gap', 'fixbox', 'fixround', 'gapfrac', 'fixfrac')
LABEL = {'gap': '不足から揃える（門の注文書の規則）', 'fixbox': '決まった％・買えない分は貯める',
         'fixround': '決まった％・四捨五入（過不足は NASDAQ100）',
         'gapfrac': '（参考）不足から揃える・端数まで買える', 'fixfrac': '（参考）決まった％・端数まで買える'}


def mdiff(a, b):
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:]) - int(a[5:])


def rets(s):
    ks = sorted(s)
    return {b: s[b] / s[a] - 1 for a, b in zip(ks, ks[1:]) if mdiff(a, b) == 1}


def load():
    now = datetime.date.today()
    cur = f'{now.year:04d}-{now.month:02d}'
    raw = {t: L.fetch(t) for t in ['QQQ', '^NDX', 'SMH', 'FSELX', 'ITA', 'FSDAX']}
    miss = [t for t, v in raw.items() if not v]
    if miss:
        raise SystemExit('✗ 取れない: ' + ' '.join(miss))
    raw = {t: {k: x for k, x in v.items() if k < cur} for t, v in raw.items()}   # 途中の今月を落とす
    R = {t: rets(v) for t, v in raw.items()}
    ov = sorted(m for m in R['QQQ'] if m in R['^NDX'])
    g = S.mean(R['QQQ'][m] - R['^NDX'][m] for m in ov)
    ser = {'NDX': {m: (R['QQQ'][m] if m in R['QQQ'] else R['^NDX'][m] + g) for m in R['^NDX']},
           'SMH': {m: (R['SMH'][m] if m in R['SMH'] else R['FSELX'][m]) for m in R['FSELX']},
           'ITA': {m: (R['ITA'][m] if m in R['ITA'] else R['FSDAX'][m]) for m in R['FSDAX']}}
    fx = G.fred('DEXJPUS')
    ms, out = [], {b: [] for b in ser}
    for m in sorted(set(ser['NDX']) & set(ser['SMH']) & set(ser['ITA'])):
        y, mo = int(m[:4]), int(m[5:])
        k, pk = y * 100 + mo, (y * 100 + mo - 1) if mo > 1 else ((y - 1) * 100 + 12)
        if k not in fx or pk not in fx:
            continue
        f = fx[k] / fx[pk]
        ms.append(m)
        for b in ser:
            out[b].append((1 + ser[b][m]) * f - 1)
    if any(mdiff(a, b) != 1 for a, b in zip(ms, ms[1:])):
        raise SystemExit('✗ 月が抜けている（つないだ系列に穴）')
    return ms, out, g


def gap_budget(H, TOT):
    base = TOT + D
    need = {b: max(0.0, W[b] * base - H[b]) for b in W}
    sn = sum(need.values())
    bud = ({b: D * need[b] / sn for b in W} if sn >= D and sn > 0
           else {b: need[b] + (D - sn) * W[b] for b in W})
    return base, need, bud


def sim(rule, R, s, n):
    frac = rule.endswith('frac')
    sh = {b: 0.0 for b in WHOLE}
    ndx, px, box, contrib = 0.0, dict(PX0), {b: 0.0 for b in WHOLE}, 0.0
    devs, smh_max, cash_sum = [], 0.0, 0.0
    for i in range(s, s + n):
        if i > s:                                     # その月の値動き（初月は値動きの前に買う）
            ndx *= 1 + R['NDX'][i]
            for b in WHOLE:
                px[b] *= 1 + R[b][i]
        if not frac:
            for b in WHOLE:                           # 分割（値段が高くなりすぎたら）
                while px[b] > SPLIT:
                    px[b] /= 2
                    sh[b] *= 2
        contrib += D
        H = {'NDX': ndx, **{b: sh[b] * px[b] for b in WHOLE}}
        TOT = sum(H.values())
        if rule in ('gap', 'gapfrac'):
            base, need, bud = gap_budget(H, TOT)
            if frac:
                ndx += bud['NDX']
                for b in WHOLE:
                    sh[b] += bud[b] / px[b]
            else:
                flex = bud['NDX']                     # 投資信託の取り分＝丸株の過不足を吸う（ccfCatSharePlan と同じ）
                for b in sorted(WHOLE, key=lambda b: -(need[b] / max(1e-9, W[b] * base))):
                    rem, p, left, k = bud[b], px[b], need[b], 0
                    if left >= p / 2 and p <= D:
                        while left >= p / 2 and rem >= p / 2 and p <= rem + flex and k < 50:
                            if p <= rem:
                                rem -= p
                            else:
                                flex -= p - rem
                                rem = 0.0
                            k += 1
                            left -= p
                    sh[b] += k
                    flex += rem                       # 使い残しは投資信託へ
                ndx += flex
        elif rule == 'fixfrac':
            ndx += D * W['NDX']
            for b in WHOLE:
                sh[b] += D * W[b] / px[b]
        elif rule == 'fixbox':
            ndx += D * W['NDX']
            for b in WHOLE:
                box[b] += D * W[b]
                k = int(box[b] // px[b])
                sh[b] += k
                box[b] -= k * px[b]
        elif rule == 'fixround':
            spend = D
            for b in WHOLE:
                k = min(int(math.floor(D * W[b] / px[b] + 0.5)), int(spend // px[b]))
                sh[b] += k
                spend -= k * px[b]
            ndx += spend
        H = {'NDX': ndx, **{b: sh[b] * px[b] for b in WHOLE}}
        inv = sum(H.values())
        cash = sum(box.values()) if rule == 'fixbox' else 0.0
        if i - s >= 12 and inv > 0:                   # 最初の1年は買い集めの途中なので数えない
            devs.append(max(abs(H[b] / inv - W[b]) for b in W) * 100)
            smh_max = max(smh_max, H['SMH'] / inv * 100)
            cash_sum += cash / (inv + cash) * 100
    return dict(mult=(inv + cash) / contrib, dev_avg=S.mean(devs), dev_max=max(devs), dev_end=devs[-1],
                smh_max=smh_max, cash_avg=cash_sum / len(devs))


def r2(x, k=2):
    return round(x, k)


def main():
    ms, R, g = load()
    out = dict(generated=datetime.date.today().isoformat(), tool='night/wholeshare_buy.py',
               question='1株単位でしか買えないとき、不足から揃える（門）と入金を決まった％で、のどちらが良いか',
               prereg=None, note='参考（事前登録なし）。事前登録つきの同じ問いは out/buy_rules.json の R0 と R1（1株単位なし）',
               period=f'{ms[0]} → {ms[-1]}（{len(ms)}か月）', target_etf_side={k: r2(v * 100, 1) for k, v in W.items()},
               deposit_jpy=D, start_price_jpy=PX0, split_above_jpy=SPLIT, ndx_div_g_month=round(g, 6),
               rules=LABEL, windows={})
    for yrs in (20, 15, 10):
        n = yrs * 12
        st = list(range(0, len(ms) - n + 1))
        res = {r: [sim(r, R, s, n) for s in st] for r in RULES}
        win = {'n': len(st)}
        for r in RULES:
            v = res[r]
            ref = res['gapfrac'] if r.endswith('frac') else res['gap']
            d = [a['mult'] / b['mult'] - 1 for a, b in zip(v, ref)]
            win[r] = dict(倍率_中央=r2(S.median(x['mult'] for x in v), 3), 倍率_最悪=r2(min(x['mult'] for x in v), 3),
                          揃えるとの差_中央pct=r2(S.median(d) * 100), 揃えるとの差_最小pct=r2(min(d) * 100),
                          揃えるとの差_最大pct=r2(max(d) * 100), 揃えるに勝った割合=r2(sum(x > 0 for x in d) / len(d)),
                          ずれ_平均の中央pt=r2(S.median(x['dev_avg'] for x in v), 1),
                          ずれ_最大の中央pt=r2(S.median(x['dev_max'] for x in v), 1),
                          ずれ_最大の最大pt=r2(max(x['dev_max'] for x in v), 1),
                          ずれ_終わりの中央pt=r2(S.median(x['dev_end'] for x in v), 1),
                          SMH最大の中央pct=r2(S.median(x['smh_max'] for x in v), 1),
                          箱の現金_平均pct=r2(S.median(x['cash_avg'] for x in v), 1))
        if yrs == 20:
            by = {}
            for s, a, b in zip(st, res['fixbox'], res['gap']):
                by.setdefault(ms[s][:4], []).append(a['mult'] / b['mult'] - 1)
            win['起点の年ごと_決まった％貯める−揃える_中央pct'] = {y: r2(S.median(v) * 100, 1) for y, v in sorted(by.items())}
        out['windows'][f'{yrs}年'] = win
        print(f'== 転がる{yrs}年（{len(st)}窓）')
        for r in RULES:
            w = win[r]
            print(f"  {LABEL[r]}: 倍率 中央{w['倍率_中央']} 最悪{w['倍率_最悪']} | 差 中央{w['揃えるとの差_中央pct']:+}% "
                  f"[{w['揃えるとの差_最小pct']:+}, {w['揃えるとの差_最大pct']:+}] 勝ち{w['揃えるに勝った割合']} | ずれ 平均{w['ずれ_平均の中央pt']}pt "
                  f"最大{w['ずれ_最大の中央pt']}pt 終わり{w['ずれ_終わりの中央pt']}pt | SMH最大{w['SMH最大の中央pct']}% | 現金{w['箱の現金_平均pct']}%")
    out['limits'] = [
        '個別株15%は外した（門の選び方の歴史が無い）。1株の値段の問題は個別株のほうが大きいが、規則の性質は同じ',
        'SMH・ITA の2000年・2006年より前は投信（FSELX・FSDAX・アクティブ運用）でつないだ。NASDAQ100 の1999年より前は価格指数＋推定配当',
        '米国の1985年以降の一つの時代。窓は重なり、独立な試行は2つほど。税・手数料は入れていない（NISA で売らない前提）',
        '1株の値段は窓の初月を今日の値に合わせた（その後は値動きどおり）。¥150,000 で2分割する置き方は仮定',
        '目標は今の配分（NASDAQ100 50 / SMH 25 / ITA 10）を ETF側で正規化したもの。配分が変われば数字も変わる',
    ]
    with open(os.path.join(BASE, 'out', 'wholeshare_buy.json'), 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('→ out/wholeshare_buy.json')


if __name__ == '__main__':
    main()
