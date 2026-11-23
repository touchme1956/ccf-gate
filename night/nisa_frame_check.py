#!/usr/bin/env python3
"""night/nisa_frame_check.py — 配分の形ごとに、NISA の枠がいつ埋まり、課税口座にどれだけ入るかの目安（読むだけ・参考・判定なし）

ユーザー（2026-11-23）「戻してマージ（main 45/20/10/15/10）と、この形でマージ（最終結論 25/35/15/15/10）の比較だして」への答えの材料。
13の物差しは税の前の数字なので、形によって NISA の枠の使い方が違うこと（物差しの外）だけをこの道具で数える。
配分・採点・注文書は変えない。

置いたこと（道具の頭に固定・単純な算数）
  - 2027-01 から毎月の入金20万円（portfolio.json の nisa.monthly_total_jpy）。うち自動の積立 3.5万円
    （iDeCo A 0.5万円＋こどもNISA 3万円＝親の NISA の外・NASDAQ100 の区分に数える）。注文書が配るのは残りの16.5万円。
  - 新しいお金は目標の比（資産全体の%）で区分へ入る（定常の近似・区分ごとの値動きの差は数えない）。
    注文書の NASDAQ100（iFreeNEXT）はつみたて投資枠、それ以外の ETF と個別株は成長投資枠で買う（nisa.rule と同じ）。
  - 成長投資枠 2人で生涯2,400万円／つみたて投資枠 2人で年240万円／NISA 全体 2人で生涯3,600万円（1人1,800万円）。
  - 2026年末までに使った成長投資枠＝これまでの記録の約100万円（口座の分かる NISA の記録 約70万円〔MSFT 6株・SMH 3株・QQQM 1株〕＋
    口座の分からない XLK・ASML の一部と置いた。全部入れても約160万円＝埋まる時期は ±4か月）＋今月（2026-11・入金140万円）の注文書の成長投資枠の分
    （門の注文書 `night/shadow_seats.js --seats 10 --monthly 1400000 --then 200000 --weights …`・2026-11-20 の値段で読んだ値）。
    今月の iFreeNEXT のうち2人の月の上限（1人10万円）を超える分は成長投資枠の QNDX（overflow_to）と置いた。
  - 税の目安: 成長投資枠が埋まったあと課税口座で買った分の値上がり益に 20.315%（20年目に全部売ったとして）。
    年率は各形の期待の年率（元の物差し）と業種の基礎率の平均（基礎率の物差し）の2通りで一定に伸びるとした。配当の税は数えない。
  - 20年後の資産の目安＝今月の入金のあとの資産（約340万円）＋毎月20万円が同じ年率で伸びた額（税の前）。

使い方: python3 night/nisa_frame_check.py → out/nisa_frame_check.json（1秒）
"""
import datetime
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'out', 'nisa_frame_check.json')

MONTH, AUTO = 200_000, 35_000
GROW_CAP, TOTAL_CAP, TSUMI_YEAR = 24_000_000, 36_000_000, 2_400_000
YEARS, START_YEAR = 20, 2027
USED_BEFORE = 1_000_000                 # 2026-10 までの成長投資枠（目安）
ASSET_AFTER_THIS_MONTH = 3_395_000      # 今月の入金のあとの資産（注文書の総資産 ¥1,995,051＋入金 ¥1,400,000）
TAX = 0.20315
# 形: 資産全体の NASDAQ100 の%・今月の注文書の成長投資枠の分（ETF の株）と iFreeNEXT・2つの年率
FORMS = {
    '今の形（main）45/20/10/15/10': dict(ndx=40.5, etf_now=1_071_627, ifree_now=328_300, er=10.83, br=8.45),
    '最終結論 25/35/15/15/10': dict(ndx=22.5, etf_now=1_358_107, ifree_now=41_800, er=11.27, br=8.58),
    '枝の案 40/30/15/10/5': dict(ndx=36.0, etf_now=1_197_991, ifree_now=202_000, er=11.08, br=8.33),
}
BASE_KEY = '今の形（main）45/20/10/15/10'


def frames(f):
    ndx_new = MONTH * f['ndx'] / 100
    tsumi_m = max(0.0, ndx_new - AUTO)                       # 注文書が NASDAQ100 へ配る分（つみたて投資枠）
    grow_m = (MONTH - AUTO) - tsumi_m                        # 成長投資枠へ行く分
    used = USED_BEFORE + f['etf_now'] + max(0, f['ifree_now'] - 200_000)
    tsumi = min(f['ifree_now'], 200_000)
    fill_m, taxable, basis = None, 0.0, []
    for m in range(YEARS * 12):
        g = min(grow_m, max(0.0, GROW_CAP - used))
        used += g
        if g < grow_m:
            if fill_m is None:
                fill_m = m
            taxable += grow_m - g
            basis.append((m, grow_m - g))
        tsumi += min(tsumi_m, TSUMI_YEAR / 12)
    return dict(tsumi_m=tsumi_m, grow_m=grow_m, used=used, tsumi=tsumi, fill_m=fill_m, taxable=taxable, basis=basis)


def fv(er):
    r = (1 + er / 100) ** (1 / 12) - 1
    return ASSET_AFTER_THIS_MONTH * (1 + er / 100) ** YEARS + MONTH * (((1 + r) ** (YEARS * 12) - 1) / r)


def tax(basis, er):
    r = (1 + er / 100) ** (1 / 12) - 1
    return TAX * sum(a * ((1 + r) ** (YEARS * 12 - m) - 1) for m, a in basis)


def main():
    res = {}
    for nm, f in FORMS.items():
        x = frames(f)
        res[nm] = {
            '注文書の毎月（2027-01から）': {'NASDAQ100（つみたて投資枠）': round(x['tsumi_m']), '成長投資枠': round(x['grow_m'])},
            '成長投資枠が埋まる': (None if x['fill_m'] is None else
                              {'年後': round(x['fill_m'] / 12, 1), 'ごろ': f"{START_YEAR + x['fill_m'] // 12}-{x['fill_m'] % 12 + 1:02d}"}),
            '20年で課税口座に入る(万円)': round(x['taxable'] / 1e4),
            '20年でつみたて投資枠(万円)': round(x['tsumi'] / 1e4),
            '20年で NISA 全体(万円)': round((x['used'] + x['tsumi']) / 1e4),
            '年率': {'元の物差し': f['er'], '基礎率の物差し': f['br']},
            '20年後の資産(万円)': {'元の物差し': round(fv(f['er']) / 1e4), '基礎率の物差し': round(fv(f['br']) / 1e4)},
            '値上がり益の税(万円)': {'元の物差し': round(tax(x['basis'], f['er']) / 1e4), '基礎率の物差し': round(tax(x['basis'], f['br']) / 1e4)},
        }
    b = res[BASE_KEY]
    for nm, v in res.items():
        v['main との差(万円)'] = {k: {'資産': v['20年後の資産(万円)'][k] - b['20年後の資産(万円)'][k],
                                   '税': v['値上がり益の税(万円)'][k] - b['値上がり益の税(万円)'][k]} for k in ('元の物差し', '基礎率の物差し')}
    doc = {'generated': datetime.date.today().isoformat(), 'tool': 'night/nisa_frame_check.py',
           'kind': '参考・判定なし・目安の算数（配分・採点・注文書は変えない）',
           'question': '配分の形ごとに、NISA の枠がいつ埋まり、課税口座にどれだけ入るか（13の物差しの外・税）',
           '置いたこと': __doc__.split('置いたこと（道具の頭に固定・単純な算数）')[1].split('使い方:')[0].strip().splitlines(),
           '形ごと': res,
           '⚠': ['定常の近似（区分ごとの値動きの差・個別株が目標を超えている間の配り方・入金額の変更は数えない）',
                 '税は20年目に全部売ったときの値上がり益だけ（配当の税・外国税・売らずに持ち続ける場合は数えない）',
                 '制度は今のまま続くと置いた（NISA の上限・税率）']}
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT)
    for nm, v in res.items():
        fl = v['成長投資枠が埋まる']
        print(f"{nm}: 成長投資枠が埋まる {fl['ごろ'] if fl else '20年のうちに埋まらない'}（{fl['年後'] if fl else '-'}年後）"
              f"・課税口座へ {v['20年で課税口座に入る(万円)']:,}万円・つみたて {v['20年でつみたて投資枠(万円)']:,}万円"
              f"・NISA 全体 {v['20年で NISA 全体(万円)']:,}万円")
        for k in ('元の物差し', '基礎率の物差し'):
            d = v['main との差(万円)'][k]
            print(f"   {k}: 年率 {v['年率'][k]}%・20年後 {v['20年後の資産(万円)'][k]:,}万円（main との差 {d['資産']:+,}）"
                  f"・税 {v['値上がり益の税(万円)'][k]:,}万円（差 {d['税']:+,}）")


if __name__ == '__main__':
    main()
