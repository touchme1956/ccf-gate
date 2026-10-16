#!/usr/bin/env python3
"""night/industry_century.py — 100年の歴史でリターンを出してきた業種（2026-10-16・ユーザー「他に100年の歴史でしてリターンを出してきた業種は？」）

参考・判定なし。読むだけ（門・採点・配分〔portfolio.json〕に触れない・どの結果でも配分は変えない）。
データ: Ken French の49業種（CRSP・時価加重・月次・倒産した会社も入る）＝future30.load() と同じ表／市場＝F-F の Mkt-RF＋RF。
決まり（結果を見る前にこのファイルで固定）:
  始まり   … その業種のデータの最初の月と、市場の時価総額の0.25%以上になった最初の年の7月の、遅いほう
              （1社・2社しか無い頃の値動きを100年の数字に混ぜない＝etf_forward_rank の後の直しと同じ線）
  年率     … 始まり〜2026-08 の幾何年率と、同じ月の市場の年率・その差（以下「市場との差」）
  積立     … 毎月1ずつ入れる30年・20年の積立の最後の額の市場との比（起点は始まりの翌年の1月から毎年・unx_assets.century_monthly と同じ置き方）
              → 市場に勝った割合・比の中央値・下位10%点
  前半/後半 … 始まり〜1975-12 と 1976-01〜2026-08 の市場との差（前半が20年に満たない業種は出さない）
  最近     … 2000-01〜・2010-01〜 の市場との差
  ぶれ・最大下落 … 始まり〜2026-08 の月次の年率のぶれと最大の下げ
  持続の確かめ … 1930年までに始まった業種（100年組）で、前半の市場との差の上位10と下位10が後半にどうだったか・順位の相関
  今の比重 … 2025年末の市場の時価総額に占める割合（future30 の share）
  器       … 楽天で買える米国 ETF（out/broker_lineup.json と out/etfcand.json にある本だけを名指し）と今の配分（ETF 側）の業種の量
              （unx_assets の各本の top_industries＝上位6業種・被覆81〜100%）
使い方: python3 night/industry_century.py → out/industry_century.json
"""
import datetime, json, math, os, re, statistics as S, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import future30 as F                 # noqa: E402
from tech_persist import spear      # noqa: E402
from industry_trends import JA      # noqa: E402

OUT = os.path.join(BASE, 'out', 'industry_century.json')
MIN_SHARE = 0.0025
HALF = 197512
RECENT = {'2000-01〜': 200001, '2010-01〜': 201001}
OLD = 1930                           # この年までに始まった業種＝100年組
# 器（参考）: 業種 → 楽天で買えるかもしれない米国 ETF（中身はどれも複数の業種の混ぜ物＝その業種そのものではない）
VEHICLE = {'Smoke': ['XLP', 'VDC'], 'Food': ['XLP', 'VDC'], 'Soda': ['XLP', 'VDC'], 'Beer': ['XLP', 'VDC'], 'Hshld': ['XLP', 'VDC'],
           'Drugs': ['XLV', 'VHT', 'PPH', 'FBT', 'IBB'], 'MedEq': ['XLV', 'VHT', 'IHI'], 'Hlth': ['XLV', 'VHT', 'IHF'],
           'Guns': ['ITA', 'SHLD', 'PPA'], 'Aero': ['ITA', 'SHLD', 'PPA'], 'Oil': ['XLE', 'VDE'], 'Util': ['XLU', 'VPU'],
           'Chips': ['SMH', 'SOXX'], 'Softw': ['IGV', 'XLK', 'VGT'], 'Hardw': ['XLK', 'VGT'], 'Gold': ['GDX'], 'Agric': ['MOO'],
           'Banks': ['XLF', 'VFH', 'KBE'], 'Insur': ['XLF', 'VFH', 'KIE'], 'Fin': ['XLF', 'VFH'], 'Telcm': ['VOX', 'XLC'],
           'Rtail': ['XLY', 'VCR', 'XRT'], 'Meals': ['XLY', 'VCR'], 'Mach': ['XLI', 'VIS'], 'ElcEq': ['XLI', 'VIS'],
           'Trans': ['XLI', 'VIS', 'IYT'], 'Chems': ['XLB', 'VAW'], 'Mines': ['XLB', 'VAW'], 'Steel': ['XLB', 'VAW'], 'BusSv': ['XLK', 'VGT']}


def available():
    """楽天で買える米国 ETF の名札（broker_lineup の etfs ＋ etfcand の候補の表に出てくる本）"""
    have = set()
    try:
        b = json.load(open(os.path.join(BASE, 'out', 'broker_lineup.json')))
        e = b.get('etfs')
        have |= set(e.keys()) if isinstance(e, dict) else {x.get('ticker') or x.get('code') or x.get('t') for x in (e or [])}
    except Exception:  # noqa
        pass
    try:
        s = open(os.path.join(BASE, 'out', 'etfcand.json')).read()
        have |= {t for v in VEHICLE.values() for t in v if re.search(r'"%s"' % t, s)}
    except Exception:  # noqa
        pass
    return have


def months(a, b):
    out, y, m = [], a // 100, a % 100
    while y * 100 + m <= b:
        out.append(y * 100 + m)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def gcagr(r, ms):
    return math.prod(1 + r[m] for m in ms) ** (12 / len(ms)) - 1


def dca_mult(r, ms):
    W = 0.0
    for m in ms:
        W = (W + 1) * (1 + r[m])
    return W / len(ms)


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))]


def stats(r, ms):
    xs = [r[m] for m in ms]
    mu = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs)) * math.sqrt(12)
    v = peak = 1.0
    mdd = 0.0
    for x in xs:
        v *= 1 + x
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return sd, mdd


def dca_windows(r, mkt, start, end, n):
    """起点＝始まりの翌年の1月から毎年・n か月そろう窓だけ → [(起点の年, 比)]"""
    out = []
    y = start // 100 + 1
    while True:
        ms = F.months(y * 100 + 1, n)
        if ms[-1] > end:
            break
        if all(m in r and m in mkt for m in ms):
            out.append((y, dca_mult(r, ms) / dca_mult(mkt, ms)))
        y += 1
    return out


def main():
    cols, ret, capm, me, be, share, mkt = F.load()
    end = min(max(mkt), min(max(ret[c]) for c in cols))
    have = available()
    rows = {}
    for c in cols:
        r = ret[c]
        first = min(r)
        big = next((y for y in sorted(share[c]) if share[c][y] >= MIN_SHARE), None)
        if big is None:
            rows[c] = {'業種': JA.get(c, c), '始まり': None, '理由': f'市場の{MIN_SHARE * 100:g}%に一度も届かない'}
            continue
        start = max(first, big * 100 + 7)
        ms = [m for m in months(start, end) if m in r and m in mkt]
        ci, cm = gcagr(r, ms), gcagr(mkt, ms)
        sd, mdd = stats(r, ms)
        o = {'業種': JA.get(c, c), '始まり': start, '年数': round(len(ms) / 12, 1), '年率': round(100 * ci, 2), '市場の年率': round(100 * cm, 2),
             '市場との差': round(100 * (ci - cm), 2), 'ぶれ': round(100 * sd, 1), '最大下落': round(100 * mdd, 1),
             '1ドルが': round(math.prod(1 + r[m] for m in ms), 1), '市場の1ドルが': round(math.prod(1 + mkt[m] for m in ms), 1)}
        for lab, n in (('30年の積立', 360), ('20年の積立', 240)):
            w = dca_windows(r, mkt, start, end, n)
            if w:
                xs = [x for _, x in w]
                o[lab] = {'窓': len(w), '起点': f'{w[0][0]}〜{w[-1][0]}', '市場に勝った割合': round(sum(x > 1 for x in xs) / len(xs), 2),
                          '比の中央値': round(S.median(xs), 3), '下位10%点': round(q(xs, 0.10), 3), '最悪': round(min(xs), 3), '最良': round(max(xs), 3)}
        h1 = [m for m in ms if m <= HALF]
        h2 = [m for m in ms if m > HALF]
        if len(h1) >= 240:
            o['前半の市場との差'] = round(100 * (gcagr(r, h1) - gcagr(mkt, h1)), 2)
            o['前半'] = f'{h1[0]}〜{h1[-1]}'
        o['後半の市場との差（1976-01〜）'] = round(100 * (gcagr(r, h2) - gcagr(mkt, h2)), 2)
        for lab, a in RECENT.items():
            mm = [m for m in ms if m >= a]
            o[f'{lab}の市場との差'] = round(100 * (gcagr(r, mm) - gcagr(mkt, mm)), 2)
        ly = max(share[c])
        o['今の比重'] = round(100 * share[c][ly], 2)
        o['比重の年'] = ly
        o['器（楽天で買える本・参考）'] = [t for t in VEHICLE.get(c, []) if t in have]
        o['器の候補で楽天に無い本'] = [t for t in VEHICLE.get(c, []) if t not in have]
        rows[c] = o
    ok = {c: o for c, o in rows.items() if o.get('始まり')}
    order = sorted(ok, key=lambda c: -ok[c]['市場との差'])
    old = [c for c in ok if ok[c]['始まり'] // 100 <= OLD and '前半の市場との差' in ok[c]]
    pers = None
    if len(old) >= 20:
        top = sorted(old, key=lambda c: -ok[c]['前半の市場との差'])[:10]
        bot = sorted(old, key=lambda c: ok[c]['前半の市場との差'])[:10]
        h2 = '後半の市場との差（1976-01〜）'
        pers = {'業種の数': len(old), '前半の上位10': [JA.get(c, c) for c in top], '前半の上位10の後半の平均': round(S.mean(ok[c][h2] for c in top), 2),
                '前半の上位10のうち後半も市場に勝った数': sum(ok[c][h2] > 0 for c in top),
                '前半の下位10': [JA.get(c, c) for c in bot], '前半の下位10の後半の平均': round(S.mean(ok[c][h2] for c in bot), 2),
                '前半の下位10のうち後半に市場に勝った数': sum(ok[c][h2] > 0 for c in bot),
                '前半と後半の順位の相関': round(spear([ok[c]['前半の市場との差'] for c in old], [ok[c][h2] for c in old]), 3)}
        pers['2000年以降も'] = {'前半の上位10の平均': round(S.mean(ok[c]['2000-01〜の市場との差'] for c in top), 2),
                            '前半の上位10のうち勝った数': sum(ok[c]['2000-01〜の市場との差'] > 0 for c in top)}
    both = [c for c in order if ok[c]['始まり'] // 100 <= OLD and ok[c].get('前半の市場との差', -1) > 0 and ok[c]['後半の市場との差（1976-01〜）'] > 0]
    med = S.median(ok[c]['市場との差'] for c in ok)
    # 今の配分（ETF 側）の業種の量（unx_assets の top_industries・上位6業種）
    expo = None
    try:
        import unx_assets as U
        res = U.build()
        tg = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
        w = {}
        for k, v in tg['ami_weights'].items():
            if v:
                a = 'QQQM' if k == 'IFREE-NDX' else k
                w[a] = w.get(a, 0) + float(v)
        tot = sum(w.values())
        agg, cov = {}, 0.0
        for a, v in w.items():
            ti = res['rows'][a].get('top_industries') or {}
            for ind, x in ti.items():
                agg[ind] = agg.get(ind, 0) + v / tot * x
            cov += v / tot * sum(ti.values())
        expo = {'ETF 側の比（全体の%）': w, '被覆（上位6業種で測れた割合）': round(cov, 3),
                '業種の量（ETF 側の中の%）': {JA.get(k, k): round(100 * x, 1) for k, x in sorted(agg.items(), key=lambda kv: -kv[1])}}
    except Exception as e:  # noqa
        expo = {'読めず': str(e)[:200]}
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/industry_century.py', kind='参考・判定なし（配分は変えない）',
               question='ユーザー「他に100年の歴史でしてリターンを出してきた業種は？」', end=end, min_share=MIN_SHARE,
               notes=['Ken French の49業種（CRSP・時価加重・倒産・上場廃止も入る＝生き残りの偏りは業種の単位では小さい）',
                      '業種は SIC（事業の分類）で決まる＝中身は時代で変わる（今の Chips は Apple を含む・Softw は1965年から）',
                      '市場との差は幾何の年率の差・積立の比は毎月1ずつ入れた最後の額の比（起点の年の1月から）',
                      '始まりは市場の0.25%以上になった年の7月から（1〜2社の頃の値動きを混ぜない）・1963年からの業種（防衛・貴金属・清涼飲料ほか）は約63年',
                      '業種の成績は費用・税の前・器（ETF）はどれも複数の業種の混ぜ物'],
               results={'業種ごと（市場との差の大きい順）': {c: ok[c] for c in order},
                        '外した業種': {c: o for c, o in rows.items() if not o.get('始まり')},
                        '前半も後半も市場に勝った100年組': [JA.get(c, c) for c in both],
                        '市場との差の中央値（業種の真ん中）': round(med, 2),
                        '持続の確かめ（前半の勝者は後半も勝ったか）': pers,
                        '今の配分（ETF 側）の業種の量': expo})
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT)
    for c in order:
        o = ok[c]
        d30 = o.get('30年の積立', {})
        print(f"{JA.get(c, c)[:8]:<8} {o['始まり']} {o['年数']:5.1f}年 年率{o['年率']:6.2f} 差{o['市場との差']:+6.2f} 前半{o.get('前半の市場との差', float('nan')):+6.2f} "
              f"後半{o['後半の市場との差（1976-01〜）']:+6.2f} 2000〜{o['2000-01〜の市場との差']:+6.2f} 2010〜{o['2010-01〜の市場との差']:+6.2f} "
              f"30年勝ち{d30.get('市場に勝った割合', '-')} 中央{d30.get('比の中央値', '-')} ぶれ{o['ぶれ']} 下落{o['最大下落']} 比重{o['今の比重']} 器{o['器（楽天で買える本・参考）']}")
    print('持続', json.dumps(pers, ensure_ascii=False))
    print('前半も後半も', [JA.get(c, c) for c in both])
    print('今の配分', json.dumps(expo, ensure_ascii=False)[:800])


if __name__ == '__main__':
    main()
