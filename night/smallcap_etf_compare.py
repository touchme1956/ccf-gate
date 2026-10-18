#!/usr/bin/env python3
"""night/smallcap_etf_compare.py — 楽天で買える米国の小型株 ETF を同じ物差しで並べる（2026-10-18・ユーザー「小型株ETFがたくさん種類があるよねって話」・参考・判定なし）

読むだけ。門・採点・配分・注文書には触れない。判定はしない（並べるだけ）。測り方は結果を見る前にこのファイルで固定し、回す前にコミットする。

楽天で買えるか: out/broker_lineup.json（楽天の海外ETF一覧）に名前がある本＝R。無い本は参考（X）。
並べる本（米国の小型株・レバレッジ／インバース／カバードコール・インカム型は除く）:
  S&P600（黒字の条件つきの指数）: IJR・SPSM・VIOO（同じ指数の器3本）／VIOV（バリュー）・VIOG（グロース）
  Russell 2000（黒字の条件なし）: IWM・VTWO・RSSL（同じ指数の器）／VTWV（バリュー）・VTWG（グロース）
  CRSP（Vanguard）: VB（全体）・VBR（バリュー＝今の配分に入れた本）・VBK（グロース）
  配当・質・その他: DES（小型の配当）・DGRS（小型の質・配当成長）・SDVY（中小型の増配）・ESML（ESG）
  参考 X（楽天に無い）: AVUV（Avantis 小型バリュー）・IJS（S&P600 バリュー・iShares）・XSMO（S&P600 の勢い）・CALF（小型のフリーキャッシュフロー）
  相手: SPY・QQQ・IWM（小型の素の市場）
系列: Yahoo の調整後終値（配当込み・mw_common.yahoo）の月次・ドル建て。最後の月は 2026-09。
出すもの:
  ① 設定来（最初の完全な月〜2026-09）: 年率・ぶれ・最大下落・同じ窓の SPY との差
  ② 共通の窓: W04＝2004-02〜（VB・VBR・VBK・IJR・IWM がそろう）・W10＝2010-10〜（Vanguard の S&P600／Russell 2000 の器がそろう）・
     W20＝2019-10〜（AVUV を含む）・直近10年 2016-10〜・直近5年 2021-10〜・直近3年 2023-10〜
     各本の年率・ぶれ・最大下落・SPY との差・IWM との差・QQQ との相関・2008/2020/2022 の暦年
  ③ 同じ指数の器どうしの差（IJR・SPSM・VIOO／IWM・VTWO・RSSL）＝費用と連動の差
  ④ 転がる36か月で IWM を上回った割合（W10 の本・W10 の中）
使い方: python3 night/smallcap_etf_compare.py → out/smallcap_etf_compare.json
"""
import datetime, json, math, os, statistics as S, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import mw_common as M          # noqa: E402

OUT = os.path.join(BASE, 'out', 'smallcap_etf_compare.json')
LAST = 202609
GROUPS = {
    'S&P600': ['IJR', 'SPSM', 'VIOO', 'VIOV', 'VIOG'],
    'Russell2000': ['IWM', 'VTWO', 'RSSL', 'VTWV', 'VTWG'],
    'CRSP': ['VB', 'VBR', 'VBK'],
    '配当・質・その他': ['DES', 'DGRS', 'SDVY', 'ESML'],
    '参考（楽天に無い）': ['AVUV', 'IJS', 'XSMO', 'CALF'],
}
BENCH = ['SPY', 'QQQ']
WINDOWS = {'W04': 200402, 'W10': 201010, 'W20': 201910, '直近10年': 201610, '直近5年': 202110, '直近3年': 202310}
TWINS = {'S&P600': ['IJR', 'SPSM', 'VIOO'], 'Russell2000': ['IWM', 'VTWO', 'RSSL']}
YEARS = [2008, 2020, 2022]


def months(a, b):
    out, y, m = [], a // 100, a % 100
    while y * 100 + m <= b:
        out.append(y * 100 + m)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def stats(s, ms):
    xs = [s[m] for m in ms]
    g = math.exp(sum(math.log1p(x) for x in xs) * 12 / len(xs)) - 1
    mu = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs)) * math.sqrt(12)
    v, pk, mdd = 1.0, 1.0, 0.0
    for x in xs:
        v *= 1 + x
        pk = max(pk, v)
        mdd = min(mdd, v / pk - 1)
    return dict(年率=round(100 * g, 2), ぶれ=round(100 * sd, 1), 最大下落=round(100 * mdd, 1), 月数=len(xs))


def corr(a, b, ms):
    x = [a[m] for m in ms]
    y = [b[m] for m in ms]
    mx, my = S.mean(x), S.mean(y)
    num = sum((p - mx) * (q - my) for p, q in zip(x, y))
    den = math.sqrt(sum((p - mx) ** 2 for p in x) * sum((q - my) ** 2 for q in y))
    return round(num / den, 3)


def cal(s, y):
    ms = [y * 100 + i for i in range(1, 13) if y * 100 + i <= LAST]
    if not all(m in s for m in ms):
        return None
    return round(100 * (math.prod(1 + s[m] for m in ms) - 1), 1)


def main():
    lineup = json.load(open(os.path.join(BASE, 'out', 'broker_lineup.json')))['etfs']
    rak = set(lineup.keys()) if isinstance(lineup, dict) else {e.get('t') for e in lineup}
    allt = [t for g in GROUPS.values() for t in g] + BENCH
    ser, er = {}, {}
    for t in sorted(set(allt)):
        try:
            s = {k: v for k, v in M.yahoo(t).items() if k <= LAST}
        except Exception as e:  # noqa: BLE001
            print('取れない', t, e)
            continue
        if s:
            ser[t] = s
        if isinstance(lineup, dict) and t in lineup:
            er[t] = lineup[t].get('er')
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/smallcap_etf_compare.py', kind='参考・判定なし',
               question='小型株ETFがたくさん種類があるよねって話（どれがいいか）', last_month=LAST, groups=GROUPS,
               rakuten={t: (t in rak) for t in allt}, expense_ratio_rakuten_list=er, results={})
    # ① 設定来
    inc = {}
    for t, s in ser.items():
        ks = sorted(s)
        ms = [m for m in months(ks[0], LAST) if m in s]
        if len(ms) < 12:
            continue
        r = stats(s, ms)
        if 'SPY' in ser and all(m in ser['SPY'] for m in ms):
            r['SPY同じ窓'] = stats(ser['SPY'], ms)['年率']
            r['SPYとの差'] = round(r['年率'] - r['SPY同じ窓'], 2)
        r['最初の月'] = ms[0]
        inc[t] = r
    doc['results']['①設定来'] = inc
    # ② 共通の窓
    win = {}
    for wn, a in WINDOWS.items():
        ms = months(a, LAST)
        rows = {}
        for t, s in ser.items():
            if not all(m in s for m in ms):
                continue
            r = stats(s, ms)
            for bt in ('SPY', 'IWM'):
                if bt in ser and all(m in ser[bt] for m in ms):
                    r[bt + 'との差'] = round(r['年率'] - stats(ser[bt], ms)['年率'], 2)
            if 'QQQ' in ser and all(m in ser['QQQ'] for m in ms):
                r['QQQとの相関'] = corr(s, ser['QQQ'], ms)
            for y in YEARS:
                if y * 100 + 1 >= a:
                    r[str(y)] = cal(s, y)
            rows[t] = r
        win[wn] = dict(窓=f'{a}〜{LAST}', 本=dict(sorted(rows.items(), key=lambda kv: -kv[1]['年率'])))
    doc['results']['②共通の窓'] = win
    # ③ 同じ指数の器どうし
    tw = {}
    for g, ts in TWINS.items():
        ok = [t for t in ts if t in ser]
        a = max(min(ser[t]) for t in ok)
        ms = [m for m in months(a, LAST) if all(m in ser[t] for t in ok)]
        ms = ms[1:]
        tw[g] = dict(窓=f'{ms[0]}〜{LAST}', 本={t: stats(ser[t], ms) for t in ok})
    doc['results']['③同じ指数の器'] = tw
    # ④ 転がる36か月で IWM を上回った割合（W10）
    ms = months(WINDOWS['W10'], LAST)
    roll = {}
    if 'IWM' in ser:
        for t, s in ser.items():
            if t == 'IWM' or not all(m in s for m in ms):
                continue
            wins, diffs = 0, []
            for i in range(0, len(ms) - 35):
                w = ms[i:i + 36]
                d = math.prod(1 + s[m] for m in w) ** (1 / 3) - math.prod(1 + ser['IWM'][m] for m in w) ** (1 / 3)
                diffs.append(d)
                wins += d > 0
            roll[t] = dict(窓の数=len(diffs), IWMを上回った割合=round(wins / len(diffs), 3), 差の中央値_年率pt=round(100 * S.median(diffs), 2))
    doc['results']['④転がる36か月_IWMとの比較_W10'] = roll
    doc['caveats'] = ['ドル建て・配当込み・税と為替は入れない', '共通の窓はその窓の最初の月から値がある本だけ',
                      '過去の成績で、これからの順位を約束しない（小型・バリューの上乗せは米国で2007年以降ほぼ消えた〔書庫の検証〕）']
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT)
    for wn, w in win.items():
        print(f'\n■ {wn} {w["窓"]}')
        for t, r in w['本'].items():
            print(f"  {t:5s} {'楽' if t in rak else '×'} 年率{r['年率']:6.2f} ぶれ{r['ぶれ']:5.1f} 下落{r['最大下落']:6.1f} SPY差{r.get('SPYとの差', 0):+6.2f} IWM差{r.get('IWMとの差', 0):+6.2f} QQQ相関{r.get('QQQとの相関', 0):.2f}")


if __name__ == '__main__':
    main()
