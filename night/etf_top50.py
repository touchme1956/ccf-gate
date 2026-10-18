#!/usr/bin/env python3
"""night/etf_top50.py — 今まで調べていない ETF の採用候補を上位50まで並べる（2026-10-18・ユーザー「いままで調べた候補以外で採用候補になるETFを、トップ50まで並べて」・参考・判定なし）

読むだけ。門・採点・配分・注文書には触れない。判定はしない（並べるだけ）。測り方は結果を見る前にこのファイルで固定し、回す前にコミットする。
新しいデータは取らない——etfcand（out/etfcand.json・2026-10-13・事前登録 8e86a4b）の第1段が既に測った数字だけを使う。

母集団: etfcand の家族 209（楽天で買える米国上場・東証の ETF・記録10年以上・レバレッジ等と今の本と同じ賭け〔相関≥0.95〕を外し、
        相関≥0.95 を1家族にまとめたもの）。家族の数字は代表の本の数字。
外す（今まで調べた）: 下の SOURCES のファイルのどれかに、家族の本のティッカーが1語として出てくる家族を丸ごと外す
        （etf_add・etfcand のショートリスト・小型株の比べ・防衛・ヘルスケア・質と勢い・メガ10/SCHD・4つの世界の順位付け・bestpf ほか）。
        語で拾うので、調べていない本を外しすぎることはあっても、調べた本を残すことは少ない側に倒している。外した家族は出力に全部書く。
物差し: 今の形（etfcand の形 QQQ40/SMH25/ITA5/SHLD5/XLV5/FBT5・今の配分の VBR 5 の無い形）の NASDAQ100 から5を候補へ回した形の
        円の実績の差 Δ（年率・最大下落・効率＝年率÷ぶれ）を W20（2006-10〜）と W10（2016-10〜）で。
        6つの並び（W20/W10 × 年率・最大下落・効率）それぞれで家族の順位を百分位にし、持っている並びの平均＝合成点。
        W20 が無い家族は W10 の3つだけで（印を付ける）。合成点の高い順に50。
注意: 過去の実績の並びで、これからの順位を約束しない。W10 は2016〜2026（テックと半導体の相場）なのでテック寄りが上に来やすい。
      4つの世界の判定（etfcand の第2段）はこの50本には掛けていない。
使い方: python3 night/etf_top50.py → out/etf_top50.json
"""
import datetime, json, os, re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'out', 'etf_top50.json')
SRC = os.path.join(BASE, 'out', 'etfcand.json')
SOURCES = ['etf_add_check.json', 'etf_add_prereg.json', 'smallcap_etf_compare.json', 'defense_alts.json', 'health_etf.json',
           'morefunds.json', 'factor_etf_rakuten.json', 'etf_forward_rank.json', 'etf_forward_combo.json', 'etfcand_short.json',
           'avuv_check.json', 'smt_mom_check.json', 'spmo_profile.json', 'gdx_history.json', 'unx_slices.json', 'unx_final.json',
           'bestpf_ext.json', 'bestpf_check.json', 'bestpf_final.json', 'etf_long_windows.json', 'etf_longest.json',
           'etf_ita_xlk.json', 'future30_options.json', 'alloc_check.json', 'castle10_check.json', 'portfolio_search.json']
METRICS = [('W20', 'cagr'), ('W20', 'mdd'), ('W20', 'eff'), ('W10', 'cagr'), ('W10', 'mdd'), ('W10', 'eff')]
TOP = 50


def main():
    d = json.load(open(SRC))
    cand = {x['t']: x for x in d['候補']}
    fams = d['家族']
    text = ''
    used = []
    for f in SOURCES:
        p = os.path.join(BASE, 'out', f)
        if os.path.exists(p):
            text += open(p, encoding='utf-8').read()
            used.append(f)
    # etfcand 自身のショートリスト（第2段で裁いた家族）も調べた
    short = {s['家族'] for s in d['ショートリスト']}
    held = {'QQQ', 'QQQM', 'SMH', 'ITA', 'SHLD', 'XLV', 'FBT', 'VBR', 'XLK'}

    def seen(t):
        if t in held:
            return True
        return re.search(r'(?<![A-Za-z0-9.])' + re.escape(t) + r'(?![A-Za-z0-9])', text) is not None

    keep, dropped = [], []
    for f in fams:
        hit = [t for t in f['本'] if seen(t)]
        if f['id'] in short or hit:
            dropped.append(dict(家族=f['id'], 代表=f['代表'], 名前=f['代表の名前'], 理由=('etfcand のショートリスト' if f['id'] in short else '調べた本: ' + '・'.join(hit))))
        else:
            keep.append(f)
    # 百分位（1=最良）。最大下落の Δ は正＝浅くなる＝良い
    pct = {}
    for w, k in METRICS:
        xs = [(cand[f['代表']][w]['Δ'][k], f['id']) for f in keep if w in cand[f['代表']]]
        xs.sort(key=lambda z: -z[0])
        n = len(xs)
        for i, (_, fid) in enumerate(xs):
            pct.setdefault(fid, {})[f'{w} Δ{k}'] = 1 - i / (n - 1) if n > 1 else 1.0
    rows = []
    for f in keep:
        c = cand[f['代表']]
        p = pct.get(f['id'], {})
        if not p:
            continue
        r = dict(家族=f['id'], 代表=f['代表'], 名前=c.get('日本語名') or f['代表の名前'], 資産=c['資産'], 地域=c.get('地域'), 指数=c.get('指数'),
                 経費率=c.get('経費率'), 設定日=c.get('設定日'), 同じ家族の本=f['本'], W20あり='W20' in c,
                 合成点=round(100 * sum(p.values()) / len(p), 1), 百分位={k: round(100 * v) for k, v in p.items()})
        for w in ('W20', 'W10'):
            if w in c:
                r[w] = dict(Δ年率=c[w]['Δ']['cagr'], Δ最大下落=c[w]['Δ']['mdd'], Δ効率=c[w]['Δ']['eff'],
                            単体年率=c[w]['単体']['cagr'], 単体最大下落=c[w]['単体']['mdd'])
        r['今の本との相関の最大'] = c.get('今の本との相関の最大')
        rows.append(r)
    rows.sort(key=lambda r: -r['合成点'])
    doc = dict(generated=datetime.date.today().isoformat(), tool='night/etf_top50.py', kind='参考・判定なし',
               question='いままで調べた候補以外で採用候補になるETFを、トップ50まで並べて', source='out/etfcand.json（第1段・2026-10-13）',
               今の形=d['今の形']['重み（全体の%）'], 窓=d['窓'], 調べた本を拾ったファイル=used,
               家族の数=len(fams), 外した家族の数=len(dropped), 残った家族の数=len(rows), 上位=rows[:TOP], 外した家族=dropped,
               caveats=['過去の実績の並びで、これからの順位を約束しない', 'W10 は2016〜2026（テックと半導体の相場）でテック寄りが上に来やすい',
                        'W20 の無い家族は W10 の3つの並びだけで点を付けた', '4つの世界の判定はこの50本に掛けていない',
                        '今の形は etfcand の形（VBR 5 の無い形）'])
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('→', OUT, '外した', len(dropped), '残り', len(rows))
    for i, r in enumerate(rows[:TOP], 1):
        w20 = r.get('W20', {})
        w10 = r['W10']
        print(f"{i:2d} {r['代表']:8s} {r['合成点']:5.1f} {r['資産']} 費{r['経費率']} W20 Δ年{w20.get('Δ年率','  -')} Δ下{w20.get('Δ最大下落','  -')} | W10 Δ年{w10['Δ年率']} Δ下{w10['Δ最大下落']} | {r['名前'][:34]}")


if __name__ == '__main__':
    main()
