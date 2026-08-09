#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_er.py — **irr=85 の14社を、門の合否をすべて無視して「期待値 E[r]」だけで並べる**（2026-08-09新設）

発端（ユーザー指示「私の投資基準を無視して期待値が高い銘柄を irr85 の中でランクつけろ」）。
無視するのは **合否の側**——Ω75+ ／ 堀70+ ／ キル（財務・複利停止）／ dep のベト ／
データ健全 ／ 第五の枠（席）／ 半導体上限。**E[r] の式そのものは門X本体のまま**使う
（式まで変えたら「期待値」の意味が変わってしまうので）。

E[r] = 純還元shy + 成長g + 倍率の重力mult(20年)
  g の分岐も門どおり: roicQ(=roicg または roicEx の大きい方) ≥ 15 **かつ** 堀無傷
  （erosion='none' ∧ disrupt≠'threat'）**かつ** cagr>0 → **実証CAGR**（min(cagr,20)、gcapがあれば更にmin）
  そうでなければ → **再投資式** g = bR × min(roicg,60)、bR = clamp(1 − shy%×per, 0, 1)
  fairPER = clamp(8+g,16,30) ／ mult = ((min(per,fair)/per)^(1/20) − 1)×100

**この道具の肝は「同じ物差しで14社を並べる」こと**。パックの per/shy は審査日ごとにバラバラ
（実測: VRSK は shy が欠測で門は0として計算・LRCX は px が2026-07-28 のまま）なので、
  ・per = **今日の株価 × 期末株数 ÷ TTM純利益**（四半期4本／取れなければ直近通期）
  ・shy = (配当 + 自社株買い − 株式発行) ÷ 今日の時価総額（直近通期のCF計算書）
を**14社すべてで作り直す**。⚠ASMLは純利益がEUR・株価がUSDなので**為替換算が要る**
（TSM/SAP で記録した ADR 通貨混線と同型。換算しないと PER が桁で狂う）。

使い方: python3 night/irr85_er.py --px LRCX=311.35,RBC=567.25,... [--eurusd 1.15621] [--json]
  価格は引数で渡す（この repo はブラウザから外部APIを叩かない作法なので、取得は呼び出し側の仕事）
"""
import glob, json, os, sys, time, urllib.request
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
AS_JSON = '--json' in sys.argv[1:]
HDRS = {'User-Agent': 'hachimon-gate fortis5280@gmail.com'}
arg = lambda k, d=None: (sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d)
PX = {kv.split('=')[0].upper(): float(kv.split('=')[1]) for kv in (arg('--px') or '').split(',') if '=' in kv}
EURUSD = float(arg('--eurusd', '1.15621'))
FX = {'ASML': EURUSD}          # 純利益の報告通貨 → USD


def facts(cik):
    return json.load(urllib.request.urlopen(urllib.request.Request(
        f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json', headers=HDRS), timeout=150))


def periods(us, tags, qmax=100):
    Q, Y = {}, {}
    for tag in tags:
        for unit in us.get(tag, {}).get('units', {}).values():
            for f in unit:
                if not f.get('start'):
                    continue
                s = date.fromisoformat(f['start']); e = date.fromisoformat(f['end']); n = (e - s).days
                if n <= qmax: Q.setdefault(f['end'], f['val'])
                elif 350 <= n <= 380: Y.setdefault(f['end'], f['val'])
        if Q or Y:
            break
    return Q, Y


def ttm(Q, Y):
    """⚠ 四半期4本と通期のうち **終わりが新しいほう**を採る。
       四半期を無条件に優先すると、通期(Q4まで)が出ているのに Q3 までのTTMを掴む
       ——実測 LRCX: 四半期TTM(2026-03-29)6,319 vs FY2026通期(2026-06-28)7,265 で
       PER が 61.7 と 53.6 に割れた。「取れた値＝最新の値」(BKNG型)の同族。"""
    ks = sorted(Q)
    q = (sum(Q[k] for k in ks[-4:]), ks[-1]) if len(ks) >= 4 else None
    y = (Y[max(Y)], max(Y)) if Y else None
    if q and y: return q if q[1] >= y[1] else y
    return q or y or (None, None)


def main():
    if not PX:
        print('価格が要る: --px LRCX=311.35,CW=691.52,...'); return 2
    tk = json.load(urllib.request.urlopen(urllib.request.Request(
        'https://www.sec.gov/files/company_tickers.json', headers=HDRS), timeout=60))
    CIK = {v['ticker']: v['cik_str'] for v in tk.values()}
    P = {}
    for p in sorted(glob.glob('out/*_gate_pack.json')):
        t = os.path.basename(p).split('_gate_pack')[0]
        x = json.load(open(p, encoding='utf-8')); x = x.get('data') or x
        if x.get('irr') == 85:
            P[t] = x
    SA = {r['t']: r for r in json.load(open('out/score_all.json', encoding='utf-8'))}
    num = lambda v: (float(v) if str(v).replace('.', '', 1).replace('-', '', 1).isdigit() else None) if v not in (None, '') else None
    rows = []
    for t, x in P.items():
        if t not in PX or t not in CIK:
            print(f'  {t}: 価格またはCIKが無いので飛ばす'); continue
        F = facts(CIK[t]); us = F.get('facts', {}).get('us-gaap', {}) or F.get('facts', {}).get('ifrs-full', {})
        ni, asof = ttm(*periods(us, ['NetIncomeLoss', 'ProfitLoss']))
        sh = None
        for unit in F.get('facts', {}).get('dei', {}).get('EntityCommonStockSharesOutstanding', {}).get('units', {}).values():
            for f in unit:
                if not sh or f['end'] > sh[0]: sh = (f['end'], f['val'])
        if not ni or not sh:
            print(f'  {t}: 純利益または株数が取れない'); continue
        fx = FX.get(t, 1.0)
        dv = ttm(*periods(us, ['PaymentsOfDividendsCommonStock', 'PaymentsOfDividends']))[0] or 0
        bb = ttm(*periods(us, ['PaymentsForRepurchaseOfCommonStock', 'PaymentsForRepurchaseOfEquity']))[0] or 0
        iss = ttm(*periods(us, ['ProceedsFromIssuanceOfCommonStock', 'ProceedsFromStockOptionsExercised']))[0] or 0
        mcap = PX[t] * sh[1]
        per = mcap / (ni * fx)
        shy = (dv + bb - iss) * fx / mcap * 100
        roicg = num(x.get('roicg')) or num(x.get('roic')) or 0
        rx = num(x.get('roicEx')); roicQ = rx if (rx and rx > roicg) else roicg
        cagr = num(x.get('cagr')) or 0
        moat = (x.get('erosion') or 'none') == 'none' and (x.get('disrupt') or 'settled') != 'threat'
        bR = max(0.0, min(1.0, 1 - (shy / 100) * per))
        gcap = num(x.get('gcap'))
        if roicQ >= 15 and moat and cagr > 0:
            g = min(cagr, 20); br = '実証CAGR'
            if gcap is not None: g = min(g, gcap)
        else:
            g = bR * min(roicg, 60)
            g = (min(g, cagr) if cagr > 0 else 0) if x.get('cagr') not in (None, '') else min(g, 8)
            g = min(g, 20)
            br = f'再投資式(roicg {roicg}<15)' if roicQ < 15 else '再投資式(堀に印)'
        fair = max(16, min(30, 8 + g)); mult = ((min(per, fair) / per) ** (1 / 20) - 1) * 100
        r = SA.get(t, {})
        rows.append(dict(t=t, px=PX[t], asof=asof, mcap=mcap / 1e9, per=per, x=per / fair, shy=shy,
                         bR=bR, g=g, br=br, mult=mult, er=shy + g + mult, roicg=roicg,
                         s=r.get('s'), moat_idx=r.get('moat'), buy=bool(r.get('buy')), gate=r.get('xEr')))
        time.sleep(0.2)
    rows.sort(key=lambda z: -z['er'])
    print('\n■ irr=85 の14社 —— **期待値 E[r] の高い順**（合否・キル・関門・席はすべて無視／式は門X本体のまま）')
    print(f"  {'':<6}{'PER':>7}{'倍率':>7}{'shy':>7}{'g':>7}{'重力':>7}{'★E[r]':>8}   {'gの根拠':<24}門")
    for i, r in enumerate(rows, 1):
        print(f"  {i:>2}.{r['t']:<5}{r['per']:>7.1f}{r['x']:>6.2f}x{r['shy']:>6.2f}%{r['g']:>6.1f}%"
              f"{r['mult']:>6.1f}%{r['er']:>7.1f}%   {r['br']:<24}{'🟢' if r['buy'] else '⛔'}Ω{r['s']}")
    print('\n■ 読み方')
    print('  ・**上位はほぼ「gの分岐」で決まっている**——roicg≥15 で実証CAGRを使える社と、')
    print('    再投資式へ落ちる社の差が、PERの差より大きい。買収でroicgが薄い社は構造的に下位へ来る')
    print('  ・**倍率(PER÷fairPER)はほぼ全社2〜8倍**。歴史では質の中で価格は選別力を持たなかったが、')
    print('    E[r]の式は倍率の重力として必ず引く＝この順位は価格の影響を受けている')
    if AS_JSON:
        json.dump({'generated': '2026-08-09', 'eurusd': EURUSD, 'rows': rows},
                  open('out/irr85_er.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('\n→ out/irr85_er.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
