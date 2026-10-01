#!/usr/bin/env python3
"""night/gaps_withdraw.py — 歴史検証の穴⑥: 取り崩しの時期に暴落が来たら（読むだけ・判定に不使用）

事前登録: out/gaps7_prereg.json の Q6_withdraw（9c28f6c・測る前に固定）
  資産: 市場100 ／ テック寄り＝テック3業種60＋市場40 ／ テック寄り＋取り崩し開始時に半分を短期国債へ（毎月その比率に戻す）
  取り崩し: 開始時の資産の4%（毎年物価で調整）を毎月1/12ずつ30年。失敗＝30年以内に0
  窓: 取り崩し開始 1926-07〜1995-12 の毎月（米ドル・名目リターン、引き出し額は物価で調整）
出力: out/gaps_withdraw.json
"""
import json, os, statistics as S, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
from gaps_common import fred, french_mkt, french_tech, french_country, add_months

OUT = os.path.join(BASE, 'out', 'gaps_withdraw.json')


def port(M, T, RF, kind):
    if kind == '市場100':
        return M
    tech = {m: 0.6 * T[m] + 0.4 * M[m] for m in M if m in T}
    if kind == 'テック寄り':
        return tech
    return {m: 0.5 * tech[m] + 0.5 * RF[m] for m in tech if m in RF}


def withdraw(r, cpi, start, rate, years=30, v0=1.0):
    v = v0
    for i in range(years * 12):
        m = add_months(start, i)
        if m not in r or m not in cpi:
            return None
        w = v0 * rate / 12 * cpi[m] / cpi[start]
        v -= w
        if v <= 0:
            return {'fail': True, 'years': round(i / 12, 1), 'end_real': 0.0}
        v *= 1 + r[m]
    end = add_months(start, years * 12)
    return {'fail': False, 'years': years, 'end_real': round(v / v0 * cpi[start] / cpi.get(add_months(end, -1), cpi[start]), 3)}


def summarize(res):
    ok = [x for x in res if x]
    f = [x for x in ok if x['fail']]
    return {'窓': len(ok), '失敗率': round(len(f) / len(ok), 3) if ok else None,
            '失敗までの年数_中央': S.median(x['years'] for x in f) if f else None,
            '30年後の実質の残り_中央': S.median(x['end_real'] for x in ok) if ok else None,
            '30年後の実質の残り_下位10%': sorted(x['end_real'] for x in ok)[len(ok) // 10] if ok else None}


def main():
    M, RF = french_mkt()
    T = french_tech()
    cpi = fred('CPIAUCNS')
    starts = [m for m in sorted(M) if 192607 <= m <= 199512]
    kinds = ['市場100', 'テック寄り', 'テック寄り＋半分を短期国債']
    P = {k: port(M, T, RF, k) for k in kinds}
    main_res = {}
    for rate in (0.035, 0.04, 0.05):
        main_res[f'{rate * 100:g}%'] = {k: summarize([withdraw(P[k], cpi, s, rate) for s in starts]) for k in kinds}
    m4 = main_res['4%']
    d1 = m4['テック寄り']['失敗率'] - m4['市場100']['失敗率']
    d2 = m4['テック寄り']['失敗率'] - m4['テック寄り＋半分を短期国債']['失敗率']
    v1 = '支持（テック寄りのまま取り崩すと失敗が増える）' if d1 >= 0.05 else '支持しない'
    v2 = '支持（半分を移すと失敗が減る）' if d2 >= 0.05 else '支持しない'
    # 失敗した窓の起点（10年刻みで数える）
    fails = {}
    for k in kinds:
        c = {}
        for s in starts:
            x = withdraw(P[k], cpi, s, 0.04)
            if x and x['fail']:
                c[str(s // 1000 * 10) + '年代'] = c.get(str(s // 1000 * 10) + '年代', 0) + 1
        fails[k] = c
    # 副: 20年積立（毎月、物価で調整した同額）→ 残高の4%を30年取り崩す（1926-07〜1975-12開始）
    def accum_then_withdraw(kind_acc, kind_wd, s):
        v = 0.0
        for i in range(240):
            m = add_months(s, i)
            if m not in P[kind_acc] or m not in cpi:
                return None
            v = (v + cpi[m] / cpi[s]) * (1 + P[kind_acc][m])
        s2 = add_months(s, 240)
        return withdraw(P[kind_wd], cpi, s2, 0.04, 30, v)
    seq = {}
    for nm, (a, b) in {'市場100→市場100': ('市場100', '市場100'), 'テック寄り→テック寄り': ('テック寄り', 'テック寄り'),
                       'テック寄り→半分を短期国債': ('テック寄り', 'テック寄り＋半分を短期国債')}.items():
        seq[nm] = summarize([accum_then_withdraw(a, b, s) for s in [m for m in starts if m <= 197512]])
    # 副: 日本（French Japan・円・名目・配当込み）で4%を30年（1975-01〜1995-12開始・物価は調整しない）
    jp = french_country('Japan', 'Local')
    flat = {m: 1.0 for m in jp}
    jp_res = summarize([withdraw(jp, flat, s, 0.04) for s in sorted(jp) if 197501 <= s <= 199512])
    doc = {'generated': time.strftime('%Y-%m-%d'), 'tool': 'night/gaps_withdraw.py', 'prereg': 'out/gaps7_prereg.json Q6_withdraw（9c28f6c）',
           '判定_テック寄りは失敗が増えるか': v1, '判定_半分を移すと減るか': v2,
           '取り崩しの率ごと': main_res, '4%で失敗した窓の起点（年代ごと）': fails,
           '副_20年積立→30年取り崩し（1926〜1975開始）': seq, '副_日本株だけで4%（名目・1975〜1995開始）': jp_res,
           '注': '米ドル建て。テック3業種＝French 49業種の Hardw・Softw・Chips の時価加重。短期国債＝French の RF。手数料・税は入れていない'}
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print(v1, '|', v2)
    for k, v in main_res.items():
        print(k, v)
    print('失敗の起点', fails)
    print('積立→取り崩し', seq)
    print('日本', jp_res)


if __name__ == '__main__':
    main()
