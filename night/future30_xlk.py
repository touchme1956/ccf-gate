#!/usr/bin/env python3
"""night/future30_xlk.py — 「XLKは？」（2026-10-11・future30 の続き・ユーザーの問い）

読むだけ。門・採点・配分には触れない。事後の判断の材料（仮説の検定ではない）。
  ① 今の保有の中の XLK（state.json の株数 × out/dashboard.json の最新値とドル円）と、
     新しいお金だけで薄まる道（値段は横ばい・売らない・XLK の目標は0%なので新しいお金は入らない）
  ② 100年の代用（future30 の Q3b と同じ置き方: NASDAQ100＝テック65%＋市場35%・SMH＝Chips・ITA＝Aero＋Guns・
     XLK＝テック〔Hardw・Softw・Chips を前月末の時価総額で加重＝gaps_common.french_tech〕・個別株＝市場）で、
     今の目標（その他15%＝ITA）・前の目標（その他15%＝XLK）・今の実際の保有（XLK 約3割）・XLK だけ を
     30年（起点1965〜1995）と20年（起点1965〜2005）の毎月の積立の市場との比で並べる
     ⚠ French のテックは Alphabet・Meta（SIC 7370）を含むが XLK は含まない（2018年から通信サービス）＝代用は XLK より少し広い
  ③ これからの物差し（out/etf_ita_xlk.json の席A〔今の形のその他15%〕と単体）を写す
出力: out/future30_xlk.json
"""
import datetime, json, os, statistics as S, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import gaps_common as G   # noqa: E402
import future30 as F      # noqa: E402

OUT = os.path.join(BASE, 'out', 'future30_xlk.json')


def holdings():
    st = json.load(open(os.path.join(BASE, 'state.json')))
    d = st.get('data') or st
    pf = d.get('pf:portfolio')
    pf = json.loads(pf) if isinstance(pf, str) else pf
    db = json.load(open(os.path.join(BASE, 'out', 'dashboard.json')))
    fx = (db.get('fx') or {}).get('USDJPY')
    q = db.get('quotes') or {}
    tg = json.load(open(os.path.join(BASE, 'portfolio.json')))['target']
    same = {s for v in (tg.get('ami_same_index') or {}).values() for s in v} | set(tg.get('ami_same_index') or {})
    rows, miss = [], []
    for r in pf['positions']:
        t, sh = r['t'], r.get('sh') or 0
        px = (q.get(t) or {}).get('px')
        if not px or not sh:
            miss.append(t)
            continue
        jpy = sh * px if (q.get(t) or {}).get('ccy') == 'JPY' else sh * px * fx
        if r.get('sleeve') == 'castle':
            b = '個別株'
        elif t in same:
            b = 'NASDAQ100'
        elif t == 'SMH':
            b = 'SMH'
        else:
            b = 'その他（XLK ほか）'
        rows.append({'t': t, '株数': sh, '値': px, '円': round(jpy), '区分': b})
    tot = sum(r['円'] for r in rows)
    for r in rows:
        r['比重(%)'] = round(100 * r['円'] / tot, 1)
    buckets = {}
    for r in rows:
        buckets[r['区分']] = buckets.get(r['区分'], 0) + r['円']
    xlk = sum(r['円'] for r in rows if r['t'] == 'XLK')
    # 新しいお金だけで薄まる道（今月から・値段は横ばい）: 2026年は pf:monthly、2027-01 から nisa.monthly_total_jpy（iDeCo・こどもNISA を含む入金額）
    num = lambda x: int(float(str(x).replace(',', ''))) if x not in (None, '') else 0   # state.json は文字列で持つ
    m0 = num(d.get('pf:monthly'))
    m1 = num((tg.get('nisa') or {}).get('monthly_total_jpy')) or m0
    start = int((tg.get('nisa') or {}).get('monthly_from', '2027-01').replace('-', ''))
    path, cum, hit = [], 0, {}
    m = 202610
    for i in range(1, 361):
        cum += m1 if m >= start else m0
        share = xlk / (tot + cum)
        for th in (0.15, 0.10, 0.05):
            if share < th and th not in hit:
                hit[th] = (i, m)
        if i in (1, 3, 6, 12, 24, 36, 60, 120, 240, 360):
            path.append({'何か月目': i, '月': f'{m // 100}-{m % 100:02d}', 'XLK の比重(%)': round(100 * share, 1)})
        m = G.add_months(m, 1)
    return {'価格の日': db.get('asof') or db.get('generated'), 'ドル円': fx, '保有の日（株数）': pf.get('asof'),
            '銘柄': rows, '区分(%)': {k: round(100 * v / tot, 1) for k, v in buckets.items()}, '総額(円)': tot,
            '価格が無く外した銘柄': miss,
            '入金の前提': f'今月から毎月 ¥{m0:,}、{start // 100}-{start % 100:02d} から ¥{m1:,}（iDeCo・こどもNISA を含む入金額）・XLK には新しいお金は入らない・値段は横ばい・売らない',
            '薄まる道': path,
            'XLK が目標15%を下回る月（その他の区分＝ITA に新しいお金が入り始める）': None if 0.15 not in hit else f'{hit[0.15][0]}か月目（{hit[0.15][1] // 100}-{hit[0.15][1] % 100:02d}）',
            '10%を下回る月': None if 0.10 not in hit else f'{hit[0.10][0]}か月目（{hit[0.10][1] // 100}-{hit[0.10][1] % 100:02d}）',
            '5%を下回る月': None if 0.05 not in hit else f'{hit[0.05][0]}か月目（{hit[0.05][1] // 100}-{hit[0.05][1] % 100:02d}）'}, buckets, tot


def century(buckets, tot, rows):
    cols, ret, capm, me, be, share, mkt = F.load()
    endm = max(mkt)
    tech = G.french_tech()
    allm = sorted(mkt)
    ndx = F.mix([(0.65, tech), (0.35, mkt)], allm)
    dfn = F.capw(ret, capm, ['Aero', 'Guns'], allm)
    chips = ret['Chips']
    w = {k: v / tot for k, v in buckets.items()}
    xlk_w = sum(r['円'] for r in rows if r['t'] == 'XLK') / tot
    oth_w = w.get('その他（XLK ほか）', 0) - xlk_w
    forms = {
        'F1 今の目標（NASDAQ100 50・SMH 20・ITA 15・個別株 15）': [(0.50, ndx), (0.20, chips), (0.15, dfn), (0.15, mkt)],
        'F2 前の目標（NASDAQ100 50・SMH 20・XLK 15・個別株 15）': [(0.50, ndx), (0.20, chips), (0.15, tech), (0.15, mkt)],
        f'F3 今の実際の保有（NASDAQ100 {100 * w.get("NASDAQ100", 0):.0f}・XLK {100 * xlk_w:.0f}・SMH {100 * w.get("SMH", 0):.0f}・個別株 {100 * w.get("個別株", 0):.0f}・個別株＝市場）':
            [(w.get('NASDAQ100', 0), ndx), (xlk_w, tech), (w.get('SMH', 0), chips), (w.get('個別株', 0) + oth_w, mkt)],
        'F3s 同・個別株（MSFT・ASML）をテックで代える（感度）':
            [(w.get('NASDAQ100', 0), ndx), (xlk_w + w.get('個別株', 0), tech), (w.get('SMH', 0), chips), (oth_w, mkt)],
        'F4 XLK だけ（＝テック）': [(1.0, tech)],
        'F5 NASDAQ100 だけ（テック65%＋市場35%）': [(1.0, ndx)],
    }
    out = {}
    for nm, parts in forms.items():
        parts = [(a, s) for a, s in parts if a > 0]
        tw = sum(a for a, _ in parts)
        s = F.mix([(a / tw, x) for a, x in parts], allm)
        d = {}
        for n, lab, starts, halves in ((360, '30年の積立（起点1965〜1995）', range(1965, 1996), 1979),
                                       (240, '20年の積立（起点1965〜2005）', range(1965, 2006), 1985)):
            v = []
            for y in starts:
                ms = F.months((y + 1) * 100 + 1, n)
                if ms[-1] > endm:
                    continue
                a, b = F.dca_mult(s, ms), F.dca_mult(mkt, ms)
                if a and b:
                    v.append((y, a / b))
            xs = sorted(x for _, x in v)
            q = lambda p: xs[min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))]
            early = [x for y, x in v if y <= halves]
            late = [x for y, x in v if y > halves]
            d[lab] = {'窓': len(xs), '中央値': round(S.median(xs), 3), '市場に勝った割合': round(sum(x > 1 for x in xs) / len(xs), 2),
                      '下位10%点': round(q(0.10), 3), '最悪': round(xs[0], 3), '最良': round(xs[-1], 3),
                      f'中央値_起点〜{halves}': round(S.median(early), 3), f'中央値_起点{halves + 1}〜': round(S.median(late), 3)}
        out[nm] = d
    return out


def forward():
    d = json.load(open(os.path.join(BASE, 'out', 'etf_ita_xlk.json')))
    a = d['slots']['A']
    main = a['判定']['XLK']['感度ごと']['main']
    return {'出典': 'out/etf_ita_xlk.json（4つの世界・20年の積立の確率・2026-10-10）',
            '席A 今の形のその他15%（QQQM 50 / SMH 20 / X 15）': {
                'XLK': a['table']['XLK'], 'ITA（今）': a['table'].get('ITA'), 'NASDAQ100 に回す': main['NASDAQ100'],
                'XLK の判定（対 NASDAQ100）': d['verdicts']['A:XLK']['まとめ'], 'ITA の判定（対 NASDAQ100）': d['verdicts'].get('A:ITA', {}).get('まとめ')},
            'XLK 単体': d['single']['XLK'], '相関': d['corr']['XLK'], '中身': d['holdings']['XLK'],
            '最大下落': d['drawdowns']['XLK'], '直近の年率': d['trailing']['XLK'], '暦年': d['years']['XLK']}


def main():
    h, buckets, tot = holdings()
    c = century(buckets, tot, h['銘柄'])
    out = {'generated': datetime.date.today().isoformat(), 'tool': 'night/future30_xlk.py',
           '位置づけ': '事後の判断の材料（ユーザーの問い「XLKは？」）・仮説の検定ではない・門・配分は変えない',
           '① 今の保有の中の XLK': h, '② 100年の代用（市場との比）': c, '③ これからの物差し': forward()}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(h['区分(%)'], ensure_ascii=False), '総額', h['総額(円)'])
    for r in h['銘柄']:
        print(' ', r)
    for p in h['薄まる道']:
        print(' ', p)
    for k in ('XLK が目標15%を下回る月（その他の区分＝ITA に新しいお金が入り始める）', '10%を下回る月', '5%を下回る月'):
        print(k, h[k])
    for nm, d in c.items():
        a, b = d['30年の積立（起点1965〜1995）'], d['20年の積立（起点1965〜2005）']
        print(f"{nm}\n   30年 中央{a['中央値']} 勝ち{a['市場に勝った割合']} 下位10%{a['下位10%点']} 最悪{a['最悪']} | 20年 中央{b['中央値']} 勝ち{b['市場に勝った割合']} 下位10%{b['下位10%点']} 最悪{b['最悪']}")
    print('書いた', OUT)


if __name__ == '__main__':
    main()
