#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/fill_growth_trend.py — **成長の軌道（加速／減速）を原本から機械算出する**（2026-08-09新設）

発端（ユーザー指示「成長が落ちている銘柄にマイナスをつける仕組みを作ってほしい」）。

【なぜ新しい欄が要るか——同じ信号を二度数えていないことを先に確かめた】
  門が既に持つ成長系の欄は、いずれも**別のもの**を測っている:
    cagr(5年の水準) ／ gmt(利益率のトレンド) ／ sht(同業比のシェア趨勢) ／
    f2(TAM浸透率・TAM成長) ／ f3(R&D比の3年トレンド＋シェア趨勢) ／ moatdecay(市場CAGR) ／
    ccfShrinkGate(cagr<0 ∧ gmt=down ＝ **収縮**であって減速ではない)
  ＝**自社の売上成長そのものの軌道（加速しているか減速しているか）は一度も測っていない**。

【定義は発明しない——歴史検証が使った量をそのまま使う】
  `accel = CAGR(a-2 → a, 2年) − CAGR(a-5 → a-2, 3年)`  （night/retro_features2.py:278 と同一）
  この量は 2018/2017/2016 の**3アンカーで安定して効いた4つの信号の一つ**
  （R&D比・純発行低・還元性向高・**成長加速**。CLAUDE.md 追補(3.8)）。lift は +0.1〜0.2 と弱いが、
  **符号がビンテージで反転しなかった数少ない量**。定義を変えるとその較正が効かなくなるので、そのまま使う。

【踏まないようにした落とし穴（この repo が実際に踏んだ型）】
  ・**候補タグは代替か構成要素か**（無形・有利子負債・販管費・売上で4回踏んだ）——売上タグは**代替**なので
    合算しない。重なる年で一致するタグだけを接ぐ（採取器 series() と同じ作法）
  ・**年ラベルの差で年数を数える**（要素数で数えると年が飛んだとき cagr が過大になる。実測 NVDA 85.9%→47.4%）
  ・**「取れた値＝最新の値」にしない**（BKNG型）——系列の最新年がパックの会計年度から2年以上遅れていたら算出不能
  ・**負・ゼロの売上では CAGR を作らない**（符号が反転する）

使い方: python3 night/fill_growth_trend.py [--write] [--only T,T,...] [--json]
  --write を付けるとパックへ `cagrT` を書き、根拠を _meta.evidence.cagrT に刻む。
  付けなければ読むだけ（出力 out/growth_trend.json）。
"""
import json
import os
import sys
import time
import gzip
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
UA = {'User-Agent': 'ccf-gate fortis5280@gmail.com'}
WRITE = '--write' in sys.argv[1:]
ONLY = None
if '--only' in sys.argv:
    ONLY = set(sys.argv[sys.argv.index('--only') + 1].split(','))

# 採取器 hachimon_fetch の TAGS["rev"] と同じ並び（＝意味の優先順。総額を先・ASC606のsubsetを後）
REV = ["Revenues", "RegulatedAndUnregulatedOperatingRevenue",
       "RevenueFromContractWithCustomerExcludingAssessedTax",
       "RevenueFromContractWithCustomerIncludingAssessedTax",
       "SalesRevenueNet", "SalesRevenueGoodsNet", "SalesRevenueServicesNet", "Revenue"]


def get(url, gz=False):
    """⚠**companyconcept は使わない**——実測で信用できなかった（VRSK/V は companyfacts に107件あるのに
       companyconcept が 0件を返す）。この repo の道具が全部使っている **companyfacts** に揃える。
       gzip を要求すると 369社で 0.11GB・約3分に収まる（非圧縮なら約1.8GB）。"""
    h = dict(UA)
    if gz:
        h['Accept-Encoding'] = 'gzip'
    for i in range(3):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=120)
            b = r.read()
            if r.headers.get('Content-Encoding') == 'gzip':
                b = gzip.decompress(b)
            return json.loads(b)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1 + i)
        except Exception:
            time.sleep(1 + i)
    return None


def annual(js):
    """10-K/20-Fの年次（期間11ヶ月以上）だけを {期末年: 値} に。同じ年は**提出が新しいほう**を採る。
       通貨は**一番点数の多い単位ひとつ**に固定する（accelは比の差なので通貨は問わないが、
       混ぜると『基準の違う二つを割る』型になる。ADR/20-F勢はEUR等で報告する）"""
    U = (js.get('units') or {})
    if not U:
        return {}
    un = 'USD' if 'USD' in U else max(U, key=lambda k: len(U[k]))
    out, best = {}, {}
    for _ in (0,):
        arr = U[un]
        for x in arr:
            f, s, e = x.get('form', ''), x.get('start'), x.get('end')
            if not (f.startswith('10-K') or f.startswith('20-F')) or not s:
                continue
            m = (int(e[:4]) * 12 + int(e[5:7])) - (int(s[:4]) * 12 + int(s[5:7]))
            if m < 11 or m > 13:
                continue
            y, fd = int(e[:4]), x.get('filed', '')
            if y not in best or fd > best[y]:
                best[y], out[y] = fd, x['val']
    return out


def splice(series, anchor=None):
    """候補タグ（＝**代替**であって構成要素ではない）から主系列を決める。採取器 series() と同じ作法:
       **錨の年に届く候補のうち、REVの並び（＝意味の優先順）が最上位のものを主系列**にする。
       ⚠「最新年が新しいほうを採る」にすると意味の違うタグへ黙って乗り換える（BKNG実測 roicg 53.1→17.8）。
       ⚠逆に「重なりが一致したものだけ接ぐ」にすると、**ASC606の改称で重なる年が無い社**（実測 MSFT:
         旧 Revenues 2008-2017 ／ 新 ASC606タグ 2020-2026）で両方とも使えず、古いほうだけが残る。
       他の候補は**重なる年が0.5%以内で一致するときだけ**継ぎ足す（穴埋め）。一致しなければ触らない。"""
    series = [s for s in series if s]
    if not series:
        return {}
    base = None
    if anchor is not None:
        for s in series:                      # REVの並び順＝優先順のまま前から見る
            if anchor in s:
                base = dict(s)
                break
    if base is None:
        base = dict(max(series, key=lambda s: (max(s) if s else 0, len(s))))
    for s in series:
        ov = [y for y in s if y in base]
        if ov and all(abs(s[y] - base[y]) <= max(abs(base[y]), 1) * 0.005 for y in ov):
            for y, v in s.items():
                base.setdefault(y, v)
    return base


def cagr(v0, v1, n):
    if v0 is None or v1 is None or v0 <= 0 or v1 <= 0 or n <= 0:
        return None
    return (v1 / v0) ** (1.0 / n) - 1


def main():
    tk = get("https://www.sec.gov/files/company_tickers.json") or {}
    T2C = {}
    for r in tk.values():
        T2C.setdefault(r['ticker'].upper(), int(r['cik_str']))

    import glob
    rows, skip = [], []
    packs = sorted(glob.glob('out/*_gate_pack.json'))
    for i, p in enumerate(packs, 1):
        t = os.path.basename(p).split('_gate_pack')[0]
        if ONLY and t not in ONLY:
            continue
        x = json.load(open(p, encoding='utf-8'))
        d = x.get('data') or x
        cik = T2C.get(t.upper())
        if cik is None:
            skip.append((t, '日本株ほかSEC対象外（CIKが引けない）＝穴として明示する'))
            continue
        # 錨は**パックの会計年度**（審査した年で測る。採取器が先へ進んでいても引きずられない）
        rd = (d.get('reportDate') or (x.get('_meta') or {}).get('reportDate') or '')
        anchor = int(rd[:4]) if (len(rd) >= 4 and rd[:4].isdigit()) else None
        # ⚠**候補タグは全部引く**。「1本目で年数が足りたら打ち切る」にすると、ASC606で改称した社で
        #   **旧タグの古い系列だけを掴む**（実測: MSFT が Revenues の2017年止まりで錨2017・V が2020）
        #   ＝この repo が BKNG で踏んだ「取れた値＝最新の値」型を自分で再現してしまう。
        cf = get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", gz=True)
        time.sleep(0.12)                           # SECのレート制限(10req/s)を守る
        if not cf:
            skip.append((t, 'companyfacts が取得できない'))
            continue
        F = cf.get('facts') or {}
        cand = []
        # IFRS提出体(20-F)は us-gaap 名前空間に売上が無い。ifrs-full も当たる（ASML/SAP/RELX/RACE型）
        for ns, tag in ([('us-gaap', t2) for t2 in REV] +
                        [('ifrs-full', t2) for t2 in ('Revenue', 'RevenueFromContractsWithCustomers')]):
            js = (F.get(ns) or {}).get(tag)
            if js:
                aa = annual(js)
                if aa:
                    cand.append(aa)
        ser = splice(cand, anchor)
        if len(ser) < 6:
            skip.append((t, f'年次の売上が{len(ser)}年ぶんしか採れない（accelには6年が要る）'))
            continue
        ys = sorted(ser)
        a = anchor if (anchor is not None and anchor in ser) else None
        if a is None:
            # 錨の年が系列に無い＝会計年度のずれ。**その手前の年まで下がる**（2年まで）。
            #   それでも無ければ「取れた値＝最新の値」にせず算出不能にする（BKNG型を作らない）
            for k in (1, 2):
                if anchor is not None and (anchor - k) in ser:
                    a = anchor - k
                    break
        if a is None:
            skip.append((t, f'パックの会計年度{anchor}が売上系列({ys[0]}-{ys[-1]})に無い'))
            continue
        need = [a, a - 2, a - 5]
        if any(y not in ser for y in need) or any(ser[y] <= 0 for y in need):
            skip.append((t, f'窓の年が欠けている（要 {a-5}/{a-2}/{a}・在庫 {ys[0]}-{ys[-1]}）'))
            continue
        c2 = cagr(ser[a - 2], ser[a], 2)
        c1 = cagr(ser[a - 5], ser[a - 2], 3)
        if c1 is None or c2 is None:
            skip.append((t, '売上が負またはゼロの年があり CAGR を作れない'))
            continue
        acc = (c2 - c1) * 100
        rows.append(dict(t=t, a=a, rev5=ser[a - 5], rev2=ser[a - 2], rev0=ser[a],
                         c1=round(c1 * 100, 2), c2=round(c2 * 100, 2), accel=round(acc, 2),
                         old=d.get('cagrT')))
        if i % 40 == 0:
            print(f'  … {i}/{len(packs)}  算出{len(rows)} / 見送り{len(skip)}', file=sys.stderr)

    rows.sort(key=lambda r: r['accel'])
    print(f'■ 成長の軌道 cagrT = 直近2年CAGR − その前3年CAGR（歴史検証 retro_features2 の accel と同一定義）')
    print(f'  算出 {len(rows)}社 / 見送り {len(skip)}社')
    if rows:
        import statistics as st
        v = [r['accel'] for r in rows]
        q = lambda p: sorted(v)[int(len(v) * p)]
        print(f"  分布: 最小{v[0]:+.1f}pt / 25%{q(.25):+.1f} / 中央{st.median(v):+.1f} / "
              f"75%{q(.75):+.1f} / 最大{sorted(v)[-1]:+.1f}pt")
        print(f"  減速(<0) {sum(1 for x in v if x<0)}社 / 加速(≥0) {sum(1 for x in v if x>=0)}社")

    if WRITE:
        n = 0
        for r in rows:
            p = f"out/{r['t']}_gate_pack.json"
            x = json.load(open(p, encoding='utf-8'))
            d = x.get('data') or x
            d['cagrT'] = r['accel']
            m = x.setdefault('_meta', {})
            m.setdefault('evidence', {})['cagrT'] = (
                f"機械算出（night/fill_growth_trend.py・SEC XBRL companyconcept）: "
                f"売上 {r['a']-5}年 {r['rev5']:,.0f} → {r['a']-2}年 {r['rev2']:,.0f} → {r['a']}年 {r['rev0']:,.0f}。"
                f"直近2年CAGR {r['c2']:.2f}% − その前3年CAGR {r['c1']:.2f}% = **{r['accel']:+.2f}pt**。"
                f"定義は歴史検証 night/retro_features2.py の accel と同一（3アンカーで符号が安定した4信号の一つ）。"
                f"候補タグは代替として扱い、重なる年が0.5%以内で一致するものだけを接いだ。")
            m.setdefault('provenance', {})['cagrT'] = 'machine'
            json.dump(x, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            n += 1
        for t, why in skip:
            p = f"out/{t}_gate_pack.json"
            if not os.path.exists(p):
                continue
            x = json.load(open(p, encoding='utf-8'))
            # **キーは置いて値を null にする**——受理キーは門の applyFields が正で、
            #   キーごと無いと納品検査の様式一致で落ちる（他の未測定欄と同じ形にそろえる）
            (x.get('data') or x)['cagrT'] = None
            m = x.setdefault('_meta', {})
            m.setdefault('nulls', {})['cagrT'] = f'成長の軌道を算出できない: {why}'
            json.dump(x, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\n→ {n}社へ cagrT を書き込み・{len(skip)}社へ理由つき空欄を刻んだ')

    json.dump({'generated': '2026-08-09',
               'note': 'cagrT = CAGR(a-2→a,2) − CAGR(a-5→a-2,3)。retro_features2 の accel と同一定義',
               'rows': rows, 'skipped': [{'t': t, 'why': w} for t, w in skip]},
              open('out/growth_trend.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('→ out/growth_trend.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
