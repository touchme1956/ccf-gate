#!/usr/bin/env python3
"""night/alt_etf_compare.py — 防衛（ITA）・ヘルスケア（XLV）の代わりの ETF を、同じ窓・円建てで比べる（2026-10-13・ユーザー
「防衛ITAほかバイオ薬品XLV以外にもっといいETFや投資信託が出ているはず。探して」）

読むだけ。門・採点・配分（portfolio.json）には触れない。事前登録なし＝参考（判断の材料）。
- 候補: 楽天で買える本（楽天の ETFD.csv・2026-10-09 の一覧で確かめた）と、楽天に無いが候補に挙がる本
- 値段: Yahoo の調整後の月末（配当込み・mw_common.yahoo）。米国上場の本は JPY=X の月次の変化を掛けて円にする（東証の本は円のまま）
- 単体: 共通の窓（候補・ITA・XLV・QQQ・SMH の全部がある月）の年率・ぶれ・最大下落・QQQ との相関
- 形: 今の ETF 側の形（QQQ 40 : SMH 25 : ITA 10 : XLV 10・毎月リバランス）で ITA か XLV を候補に替えた形の年率・ぶれ・最大下落
⚠ 記録の短い本（3年以下）は、その数年の相場（欧州の再軍備・防衛テックの人気・肥満症の薬）をそのまま写す——「良い本」の証拠にはならない
出力: out/alt_etf_compare.json
"""
import datetime, json, math, os, statistics as S, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
import mw_common as M  # noqa: E402

OUT = os.path.join(BASE, 'out', 'alt_etf_compare.json')
# 楽天の欄は ETFD.csv（https://www.rakuten-sec.co.jp/web/market/search/etf_search/ETFD.csv・2026-10-09 のデータ）で確かめた
CANDS = {
    '防衛': ('ITA', [('ITA', True), ('SHLD', True), ('MISL', True), ('466A.T', True), ('513A.T', True),
                     ('XAR', False), ('PPA', False), ('EUAD', False), ('NATO', False), ('WAR', False)]),
    'ヘルスケア': ('XLV', [('XLV', True), ('VHT', True), ('IXJ', True), ('IBB', True), ('BBH', True), ('FBT', True),
                         ('PPH', True), ('FXH', True), ('GNOM', True), ('HEAL', True), ('1621.T', True), ('2639.T', True),
                         ('FHLC', False), ('IYH', False), ('RSPH', False), ('XBI', False), ('IHI', False), ('XHE', False),
                         ('XPH', False), ('OZEM', False), ('THNR', False), ('HRTS', False)]),
}
SHAPE = {'QQQ': 40, 'SMH': 25, 'ITA': 10, 'XLV': 10}


def main():
    fx = M.yahoo('JPY=X')

    def yen(t):
        try:
            s = M.yahoo(t)
        except Exception:
            return {}
        if t.endswith('.T'):
            return s
        return {k: (1 + v) * (1 + fx[k]) - 1 for k, v in s.items() if k in fx}

    base = {t: yen(t) for t in SHAPE}

    def stats(r):
        ks = sorted(r); g = 1.0; pk = 1.0; dd = 0.0
        for k in ks:
            g *= 1 + r[k]; pk = max(pk, g); dd = min(dd, g / pk - 1)
        n = len(ks)
        return {'月数': n, '年率': round(100 * (g ** (12 / n) - 1), 1),
                'ぶれ': round(100 * S.pstdev([r[k] for k in ks]) * math.sqrt(12), 1), '最大下落': round(100 * dd, 1)}

    def corr(a, b, ks):
        x = [a[k] for k in ks]; y = [b[k] for k in ks]; mx, my = S.mean(x), S.mean(y)
        return round(sum((p - mx) * (q - my) for p, q in zip(x, y))
                     / math.sqrt(sum((p - mx) ** 2 for p in x) * sum((q - my) ** 2 for q in y)), 2)

    def shape(ks, ref, alt):
        tot = sum(SHAPE.values())
        return {k: sum(w * (alt[k] if t == ref else base[t][k]) for t, w in SHAPE.items()) / tot for k in ks}

    out = {'generated': datetime.date.today().isoformat(), 'tool': 'night/alt_etf_compare.py', '円建て': True,
           '形': 'QQQ 40 : SMH 25 : ITA 10 : XLV 10（毎月リバランス）で ITA か XLV を候補に替える', '群': {}}
    for grp, (ref, cands) in CANDS.items():
        rows = []
        for t, rk in cands:
            s = yen(t)
            if not s:
                rows.append({'本': t, '楽天': rk, '注': '値段が取れない'}); continue
            ks = sorted(set(s) & set.intersection(*[set(v) for v in base.values()]))
            if len(ks) < 6:
                rows.append({'本': t, '楽天': rk, '注': f'共通の月が {len(ks)} か月しかない'}); continue
            rows.append({'本': t, '楽天': rk, '窓': f'{ks[0]}〜{ks[-1]}', '単体': stats({k: s[k] for k in ks}),
                         '同じ窓の' + ref: stats({k: base[ref][k] for k in ks}),
                         '相関QQQ': corr(s, base['QQQ'], ks), '相関SMH': corr(s, base['SMH'], ks),
                         '今の形': stats(shape(ks, ref, base[ref])), '替えた形': stats(shape(ks, ref, s))})
        out['群'][grp] = rows
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, indent=1)
    for grp, rows in out['群'].items():
        ref = CANDS[grp][0]
        print('■', grp)
        for r in rows:
            if '注' in r:
                print(f"  {r['本']:7} {r['注']}"); continue
            c, b, n, w = r['単体'], r['同じ窓の' + ref], r['今の形'], r['替えた形']
            print(f"  {r['本']:7}{'' if r['楽天'] else '（楽天に無い）':10} {r['窓']}（{c['月数']}か月） 年率 {c['年率']:6.1f}（{ref} {b['年率']:6.1f}）"
                  f" ぶれ {c['ぶれ']:5.1f}（{b['ぶれ']:5.1f}） 最大下落 {c['最大下落']:6.1f}（{b['最大下落']:6.1f}） 相関QQQ {r['相関QQQ']:.2f}"
                  f" | 形 年率 {n['年率']:5.1f}→{w['年率']:5.1f} ぶれ {n['ぶれ']:4.1f}→{w['ぶれ']:4.1f} 最大下落 {n['最大下落']:6.1f}→{w['最大下落']:6.1f}")
    print('→', OUT)


if __name__ == '__main__':
    main()
