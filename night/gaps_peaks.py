#!/usr/bin/env python3
"""night/gaps_peaks.py — 歴史検証の穴②: 他の国の天井から積み立てても20年で報われたか（読むだけ・判定に不使用）

事前登録: out/gaps7_prereg.json の Q2_peaks（9c28f6c・測る前に固定）
天井＝(i)過去最高値 (ii)その高値を取り戻すまでに −50%以上下げた (iii)直前60か月で +100%以上。
★後から見て天井だった月＝最悪の出発点を選ぶストレステスト（先読みを含むことを承知で選ぶ）。
その月末に最初の1を入れ、以後毎月同額。現地通貨・配当込み。
出力: out/gaps_peaks.json
"""
import json, os, statistics as S, sys, time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
from gaps_common import french_mkt, french_country, french_countries, french_tech, add_months, dca

OUT = os.path.join(BASE, 'out', 'gaps_peaks.json')
JA = {'Austria': 'オーストリア', 'Austrlia': 'オーストラリア', 'Belgium': 'ベルギー', 'Canada': 'カナダ', 'Denmark': 'デンマーク',
      'Finland': 'フィンランド', 'France': 'フランス', 'Germany': 'ドイツ', 'HongKong': '香港', 'Ireland': 'アイルランド',
      'Italy': 'イタリア', 'Japan': '日本', 'Malaysia': 'マレーシア', 'Nethrlnd': 'オランダ', 'NewZland': 'ニュージーランド',
      'Norway': 'ノルウェー', 'Singapor': 'シンガポール', 'Spain': 'スペイン', 'Sweden': 'スウェーデン', 'Swtzrlnd': 'スイス',
      'UK': '英国', 'US': '米国（市場）', 'USTech': '米国テック3業種'}


def level(rets):
    ms = sorted(rets)
    lv, v = {}, 1.0
    lv[add_months(ms[0], -1)] = 1.0
    for m in ms:
        v *= 1 + rets[m]
        lv[m] = v
    return lv


def peaks(rets, dd_min=-0.5, run_min=1.0):
    lv = level(rets)
    ms = sorted(lv)
    out = []
    ath = -1
    for i, m in enumerate(ms):
        if lv[m] <= ath:
            continue
        ath = lv[m]
        # 次に高値を更新する月まで（無ければ最後まで）の最安値
        low = lv[m]
        nxt = None
        for m2 in ms[i + 1:]:
            if lv[m2] > lv[m]:
                nxt = m2
                break
            low = min(low, lv[m2])
        dd = low / lv[m] - 1
        back = add_months(m, -60)
        run = (lv[m] / lv[back] - 1) if back in lv else None
        if dd <= dd_min and run is not None and run >= run_min:
            out.append({'peak': m, 'dd': round(dd, 3), 'run5y': round(run, 2), 'recovered': nxt,
                        'years_to_recover': round((nxt // 100 - m // 100) + (nxt % 100 - m % 100) / 12, 1) if nxt else None})
    return out


def evaluate(series, dd_min, run_min):
    rows = []
    for name, rets in series.items():
        for p in peaks(rets, dd_min, run_min):
            r = {'market': name, 'ja': JA.get(name, name), **p}
            for yrs in (10, 15, 20, 25):
                mult, irr = dca(rets, add_months(p['peak'], 1), yrs * 12, irr=True)
                r[f'{yrs}年_倍率'] = None if mult is None else round(mult, 2)
                r[f'{yrs}年_年率'] = None if irr is None else round(irr * 100, 1)
                # 一括（天井で全額）の年率
                lv = level(rets)
                end = add_months(p['peak'], yrs * 12)
                r[f'{yrs}年_一括年率'] = round(((lv[end] / lv[p['peak']]) ** (1 / yrs) - 1) * 100, 1) if end in lv else None
            rows.append(r)
    return rows


def verdict(rows):
    v = [r['20年_年率'] for r in rows if r.get('20年_年率') is not None]
    if len(v) < 5:
        return '判定不能', {'山': len(v)}
    med = S.median(v)
    neg = sum(x < 0 for x in v) / len(v)
    if med >= 4 and neg <= 0.2:
        vd = '支持'
    elif med < 2 or neg >= 1 / 3:
        vd = '否定'
    else:
        vd = '弱い'
    return vd, {'山': len(v), '20年の積立の年率_中央値': round(med, 1), '元本割れの山': f'{sum(x < 0 for x in v)}/{len(v)}',
                '最悪': min(v), '最良': max(v)}


def shiller_us():
    """事後の追加（事前登録の外）: Shiller ie_data.xls の S&P総合（配当込み）を名目へ直した月次リターン（1871〜）。
    French の米国は1926-07からで、1929年の天井は直前60か月が取れず定義(iii)に掛からなかったため"""
    import xlrd, urllib.request
    from gaps_common import _cached
    b = _cached('shiller_ie_data.xls', 'http://www.econ.yale.edu/~shiller/data/ie_data.xls', days=60)
    sh = xlrd.open_workbook(file_contents=b).sheet_by_name('Data')
    lv = {}
    for i in range(8, sh.nrows):
        r = sh.row_values(i)
        if not isinstance(r[0], float) or not isinstance(r[9], float) or not isinstance(r[4], float):
            continue
        y, mo = int(r[0]), int(round((r[0] - int(r[0])) * 100))
        lv[y * 100 + mo] = r[9] * r[4]          # 実質トータルリターン × 物価 ＝ 名目トータルリターン
    ms = sorted(lv)
    return {b_: lv[b_] / lv[a_] - 1 for a_, b_ in zip(ms, ms[1:])}


def main():
    series = {c: french_country(c, 'Local') for c in french_countries()}
    mkt, _ = french_mkt()
    series['US'] = mkt
    series['USTech'] = french_tech()
    main_rows = evaluate(series, -0.5, 1.0)
    vd, st = verdict(main_rows)
    sub = {}
    for nm, (dd, run, excl) in {'下落−40%で定義': (-0.4, 1.0, False), '5年で1.5倍以上': (-0.5, 0.5, False),
                               '米国の山を除く': (-0.5, 1.0, True)}.items():
        ser = {k: v for k, v in series.items() if not (excl and k in ('US', 'USTech'))}
        rr = evaluate(ser, dd, run)
        sub[nm] = {'判定（同じ決まり）': verdict(rr)[0], **verdict(rr)[1],
                   '山': [f"{r['ja']} {r['peak']}" for r in rr]}
    try:
        post = {'米国（Shiller・1871〜）': evaluate({'US_Shiller': shiller_us()}, -0.5, 1.0)}
        post['米国（Shiller・1871〜）_下落−40%'] = evaluate({'US_Shiller': shiller_us()}, -0.4, 1.0)
    except Exception as e:
        post = {'エラー': repr(e)}
    sub['★事後の追加（事前登録の外）: 米国1929年を含める'] = post
    lumps = [r['20年_一括年率'] for r in main_rows if r.get('20年_一括年率') is not None]
    doc = {'generated': time.strftime('%Y-%m-%d'), 'tool': 'night/gaps_peaks.py', 'prereg': 'out/gaps7_prereg.json Q2_peaks（9c28f6c）',
           '判定': vd, '要約': st, '一括投資の20年年率_中央値': round(S.median(lumps), 1) if lumps else None,
           '山': main_rows, '副': sub,
           '注': '現地通貨・配当込み（Ken French の国別 Value-Weight Local Returns・1975〜2025／米国は1926〜）。天井は後から見た最悪の出発点（ストレステスト）'}
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('判定', vd, st, '一括中央', doc['一括投資の20年年率_中央値'])
    for r in main_rows:
        print(r['ja'], r['peak'], 'dd', r['dd'], '5y', r['run5y'], '回復', r['years_to_recover'],
              '| 積立年率 10/15/20/25:', r['10年_年率'], r['15年_年率'], r['20年_年率'], r['25年_年率'],
              '| 20年倍率', r['20年_倍率'], '一括20年', r['20年_一括年率'])
    for k, v in sub.items():
        if k.startswith('★'):
            for kk, rows in v.items():
                for r in (rows if isinstance(rows, list) else []):
                    print('事後', kk, r['peak'], 'dd', r['dd'], '5y', r['run5y'], '回復', r['years_to_recover'],
                          '| 積立年率 10/15/20/25:', r['10年_年率'], r['15年_年率'], r['20年_年率'], r['25年_年率'], '一括20年', r['20年_一括年率'])
            continue
        print('副', k, {kk: vv for kk, vv in v.items() if kk != '山'}, v['山'])


if __name__ == '__main__':
    main()
