#!/usr/bin/env python3
"""night/gaps_sell.py — 歴史検証の穴③: 売却規律 S1/S2 の機械で測れる部分は、売った方が良かったか（読むだけ・判定に不使用）

事前登録: out/gaps7_prereg.json の Q3_sell（9c28f6c・測る前に固定）
  SEC frames（us-gaap・年次 CY2009〜CY2025）から各社・各年の ROIC（門式）・nde・利払カバー・Z''・FCF転換・粗利率を作り、
  前年に『保有の条件』（ROIC5年中央値≥17%・財務キル無し・自己資本>0・株価あり）を満たした社で、
  今年はじめて引き金（S1a/b/c・S2a/b/c）が立った社を、会計年度末の120日後の月末に売ったとする。
  比較群＝同じ会計年度に保有の条件を満たし、引き金がどれも立たなかった社（同じ窓の等加重平均）。
  株価は Yahoo の月次 adjclose（配当込み）で、今ティッカーがある社だけ（生存バイアス: 倒産した社が抜ける）。
出力: out/gaps_sell.json
"""
import json, os, statistics as S, sys, time, urllib.request, datetime, math

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'night'))
from gaps_common import add_months
from industry_trends import HDRS

OUT = os.path.join(BASE, 'out', 'gaps_sell.json')
FC = os.path.join(BASE, 'out', '_gaps_cache', 'frames')
PXC = os.path.join(BASE, 'out', '_gaps_cache', 'px')
WACC = 9.0
YEARS = range(2009, 2026)
# ★結果を見る前の修正（2026-09-28・走らせる前の点検で見つけた・結果はまだ一度も出ていない）:
#   初版は負債のタグを4つ（LongTermDebt / …Noncurrent / …Current / ShortTermBorrowings）しか見ず、
#   **どれも無い社を負債0として** ROIC を出していた（ルール7の事故の型）。実測 HD 2016: 負債は
#   LongTermDebtAndCapitalLeaseObligations にだけあり、投下資本が 自己資本−のれん に縮んで ROIC 389.6%。
#   Visa は StockholdersEquity を2011年でやめ、…IncludingPortionAttributableToNoncontrollingInterest へ移っていた＝全年が落ちていた。
#   ⇒ 候補を採取器 hachimon_fetch の TAGS に寄せて広げ、**負債のタグが一つも無い社年は『測れない』**（事前登録の
#     「取れない値はゼロと読まず『測れない』」どおり）。候補は『代替』（先に当たったものを使う）と『構成要素』（足す）を分ける:
#     負債 ＝ 非流動（代替: LongTermDebtNoncurrent → LongTermDebtAndCapitalLeaseObligations → LongTermNotesPayable → UnsecuredLongTermDebt）
#          ＋ 流動（DebtCurrent があればそれ一つ＝1年内返済と短期借入の合計。無ければ 1年内返済〔代替: LongTermDebtCurrent →
#             LongTermDebtAndCapitalLeaseObligationsCurrent〕＋ 短期借入〔代替: ShortTermBorrowings → CommercialPaper〕）。
#     非流動が無い社年だけ LongTermDebt（米国基準の定義では1年内返済を含む総額）＋短期借入、それも無ければ
#     DebtAndCapitalLeaseObligations / DebtLongtermAndShorttermCombinedAmount（総額）を使う。
#   ⚠ 構成要素の取りこぼし（転換社債・シニア債を別タグで出す社）は残る＝負債を小さく読む向き。
DUR = ['OperatingIncomeLoss', 'NetIncomeLoss', 'NetCashProvidedByUsedInOperatingActivities',
       'PaymentsToAcquirePropertyPlantAndEquipment', 'IncomeTaxExpenseBenefit',
       'IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest',
       'IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments',
       'InterestExpense', 'InterestExpenseDebt', 'InterestExpenseNonoperating', 'InterestAndDebtExpense',
       'DepreciationDepletionAndAmortization', 'DepreciationAndAmortization', 'DepreciationAmortizationAndAccretionNet',
       'GrossProfit',
       'Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'RevenueFromContractWithCustomerIncludingAssessedTax',
       'SalesRevenueNet']
INS = ['StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest',
       'LongTermDebt', 'LongTermDebtNoncurrent', 'LongTermDebtCurrent', 'ShortTermBorrowings',
       'LongTermDebtAndCapitalLeaseObligations', 'LongTermDebtAndCapitalLeaseObligationsCurrent', 'DebtCurrent',
       'CommercialPaper', 'LongTermNotesPayable', 'UnsecuredLongTermDebt',
       'DebtAndCapitalLeaseObligations', 'DebtLongtermAndShorttermCombinedAmount',
       'Goodwill', 'IntangibleAssetsNetExcludingGoodwill', 'CashAndCashEquivalentsAtCarryingValue',
       'CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents', 'Assets', 'Liabilities',
       'AssetsCurrent', 'LiabilitiesCurrent', 'RetainedEarningsAccumulatedDeficit']


def first(d, keys):
    """代替の候補: 先に当たった値（無ければ None）。0 は値として扱う"""
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return None


def debt_of(d):
    """有利子負債。タグが一つも無ければ None（負債0と読まない）"""
    lnc = first(d, ['LongTermDebtNoncurrent', 'LongTermDebtAndCapitalLeaseObligations', 'LongTermNotesPayable', 'UnsecuredLongTermDebt'])
    st = first(d, ['ShortTermBorrowings', 'CommercialPaper'])
    if d.get('DebtCurrent') is not None:
        cur = d['DebtCurrent']
    else:
        c = first(d, ['LongTermDebtCurrent', 'LongTermDebtAndCapitalLeaseObligationsCurrent'])
        cur = None if (c is None and st is None) else (c or 0) + (st or 0)
    if lnc is not None:
        return lnc + (cur or 0)
    if d.get('LongTermDebt') is not None:
        return d['LongTermDebt'] + (st or 0)
    if d.get('DebtLongtermAndShorttermCombinedAmount') is not None:
        return d['DebtLongtermAndShorttermCombinedAmount']          # 短期借入も含む総額
    if d.get('DebtAndCapitalLeaseObligations') is not None:
        return d['DebtAndCapitalLeaseObligations'] + (st or 0)     # 長期（1年内返済を含む）の総額
    return cur          # 流動の負債だけ出している社（無ければ None＝測れない）


def frame(tag, period):
    os.makedirs(FC, exist_ok=True)
    fn = os.path.join(FC, f'{tag}_{period}.json')
    if os.path.exists(fn):
        return json.load(open(fn))
    url = f'https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/{period}.json'
    data = None
    for a in range(4):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers=HDRS), timeout=120).read()
            data = [[e['cik'], e['val'], e.get('end')] for e in json.loads(raw)['data']]
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                data = []
                break
            time.sleep(3 * (a + 1))
        except Exception:
            time.sleep(3 * (a + 1))
    if data is None:
        raise RuntimeError(f'frames 取得失敗 {tag} {period}')
    json.dump(data, open(fn, 'w'))
    time.sleep(0.12)
    return data


def load_panel():
    P = {}   # cik -> year -> {tag: val, '_end': fiscal end}
    for y in YEARS:
        for t in DUR:
            for cik, v, end in frame(t, f'CY{y}'):
                d = P.setdefault(cik, {}).setdefault(y, {})
                d[t] = v
                if t == 'OperatingIncomeLoss' and end:
                    d['_end'] = end
        for t in INS:
            for cik, v, end in frame(t, f'CY{y}Q4I'):
                P.setdefault(cik, {}).setdefault(y, {})[t] = v
    return P


def roic_pt(r):
    P = [[0, 40], [8, 50], [12, 62], [16, 72], [22, 82], [30, 90], [40, 96], [200, 96]]
    if r <= 0:
        return 40 + (r / 8) * 10 if r > -1e9 else 40   # 門の式は0未満を想定していないので0の点から外挿
    for (x0, y0), (x1, y1) in zip(P, P[1:]):
        if r <= x1:
            return y0 + (y1 - y0) * (r - x0) / (x1 - x0)
    return 96


def pillar(roic_tc, wacc):
    return 0.6 * roic_pt(roic_tc) + 0.4 * min(100, 50 + (roic_tc - wacc) * 2)


def features(P, zero_debt=False):
    F = {}
    for cik, ys in P.items():
        out = {}
        for y, d in ys.items():
            oi = d.get('OperatingIncomeLoss')
            eq = first(d, ['StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'])
            if oi is None or eq is None:
                continue
            pre = first(d, ['IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest',
                            'IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments'])
            tax = d.get('IncomeTaxExpenseBenefit')
            t = min(0.5, max(0.0, tax / pre)) if (pre and pre > 0 and tax is not None) else (0.35 if y <= 2017 else 0.21)
            debt = debt_of(d)
            if debt is None and zero_debt:
                debt = 0.0                                    # 感度（事前登録の外）だけ: 初版の読み方
            if debt is not None:
                ic = eq + debt - (d.get('Goodwill') or 0) - (d.get('IntangibleAssetsNetExcludingGoodwill') or 0)
                roic = (oi * (1 - t) / ic * 100) if (eq > 0 and ic > 0 and ic >= 0.2 * eq) else None
            else:
                roic = None                                   # 負債が測れない＝ROIC も測れない（0と読まない）
            da = first(d, ['DepreciationDepletionAndAmortization', 'DepreciationAndAmortization', 'DepreciationAmortizationAndAccretionNet'])
            ebitda = oi + da if da is not None else None
            cash = first(d, ['CashAndCashEquivalentsAtCarryingValue', 'CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents'])
            nde = ((debt - cash) / ebitda) if (debt is not None and ebitda and ebitda > 0 and cash is not None) else None
            ie = first(d, ['InterestExpense', 'InterestExpenseDebt', 'InterestExpenseNonoperating', 'InterestAndDebtExpense'])
            ic_cov = (oi / ie) if (ie and ie > 0) else None
            ta, tl, ca, cl, re_ = d.get('Assets'), d.get('Liabilities'), d.get('AssetsCurrent'), d.get('LiabilitiesCurrent'), d.get('RetainedEarningsAccumulatedDeficit')
            z = (6.56 * (ca - cl) / ta + 3.26 * re_ / ta + 6.72 * oi / ta + 1.05 * eq / tl) if (ta and tl and ca is not None and cl is not None and re_ is not None and ta > 0 and tl > 0) else None
            ni, ocf, cap = d.get('NetIncomeLoss'), d.get('NetCashProvidedByUsedInOperatingActivities'), d.get('PaymentsToAcquirePropertyPlantAndEquipment')
            conv = ((ocf - (cap or 0)) / ni * 100) if (ni and ni > 0 and ocf is not None) else None
            rev = next((d[k] for k in ('Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'RevenueFromContractWithCustomerIncludingAssessedTax', 'SalesRevenueNet') if d.get(k)), None)
            gm = (d['GrossProfit'] / rev * 100) if (d.get('GrossProfit') is not None and rev and rev > 0) else None
            out[y] = dict(roic=roic, eq=eq, nde=nde, icov=ic_cov, z=z, conv=conv, gm=gm, end=d.get('_end'))
        for y in out:
            vals = [out[k]['roic'] for k in range(y - 4, y + 1) if k in out and out[k]['roic'] is not None]
            out[y]['roic_tc'] = S.median(vals) if len(vals) >= 3 else None
        F[cik] = out
    return F


def fin_kill(f):
    return (f['nde'] is not None and f['nde'] > 4) or (f['icov'] is not None and f['icov'] < 3) or \
           (f['z'] is not None and f['z'] < 1.1) or f['eq'] <= 0


def triggers(F, cik, y, wacc):
    f, p = F[cik].get(y), F[cik].get(y - 3)
    if not f or f['roic_tc'] is None:
        return None
    rtc = f['roic_tc']
    t = {'S1a': fin_kill(f), 'S1b': rtc <= wacc, 'S1c': pillar(rtc, wacc) < 70}
    spread = rtc - wacc
    t['S2a'] = (f['nde'] is not None and 3 < f['nde'] <= 4) or (f['z'] is not None and 1.1 <= f['z'] < 1.8) or (0 < spread < 3)
    t['S2b'] = f['conv'] is not None and f['conv'] < 65
    t['S2c'] = bool(p and f['roic'] is not None and p.get('roic') is not None and f['gm'] is not None and p.get('gm') is not None
                    and f['roic'] - p['roic'] <= -2 and f['gm'] - p['gm'] <= -1)
    t['S1'] = t['S1a'] or t['S1b'] or t['S1c']
    t['S2'] = (t['S2a'] or t['S2b'] or t['S2c']) and not t['S1']
    return t


def held(F, cik, y):
    f = F[cik].get(y)
    return bool(f and f['roic_tc'] is not None and f['roic_tc'] >= 17 and not fin_kill(f))


def asof(end):
    d = datetime.date.fromisoformat(end) + datetime.timedelta(days=120)
    return d.year * 100 + d.month


def prices(tickers):
    import etf_theme as T
    os.makedirs(PXC, exist_ok=True)
    out = {}
    for i, t in enumerate(sorted(tickers)):
        fn = os.path.join(PXC, f'{t}.json')
        if os.path.exists(fn):
            px = json.load(open(fn))
        else:
            px = T.fetch(t) or {}
            json.dump(px, open(fn, 'w'))
            time.sleep(0.2)
        out[t] = {int(k[:4]) * 100 + int(k[5:7]): v for k, v in px.items()}
    return out


def fwd(px, a, h):
    b = add_months(a, h)
    if a in px and b in px and px[a] > 0:
        return (px[b] / px[a]) ** (12 / h) - 1
    return None


def run(F, tick, PX, spy, last, wacc):
    """一つの WACC で引き金の社と比較群を作り、先の年率の差をまとめる → (引き金ごとの結果, 判定, 比較群の社年)"""
    events = {k: [] for k in ('S1', 'S2', 'S1a', 'S1b', 'S1c', 'S2a', 'S2b', 'S2c')}
    controls = {}
    done = {k: set() for k in events}
    for y in range(2014, 2023):
        for c in tick:
            if not held(F, c, y - 1) or y not in F[c] or not F[c][y].get('end'):
                continue
            t = triggers(F, c, y, wacc)
            if t is None:
                continue
            a = asof(F[c][y]['end'])
            if a not in PX[tick[c]]:
                continue
            if not any(t[k] for k in ('S1a', 'S1b', 'S1c', 'S2a', 'S2b', 'S2c')):
                controls.setdefault(y, []).append(c)
                continue
            for k in events:
                if t[k] and c not in done[k]:
                    done[k].add(c)
                    events[k].append((c, y, a))
    out = {}
    for k, evs in events.items():
        rows = []
        for c, y, a in evs:
            px = PX[tick[c]]
            row = {'t': tick[c], 'fy': y, 'asof': a}
            for h in (12, 36, 60):
                if add_months(a, h) > last:
                    continue
                r = fwd(px, a, h)
                cs = [fwd(PX[tick[cc]], a, h) for cc in controls.get(y, []) if cc != c]
                cs = [x for x in cs if x is not None]
                s = fwd(spy, a, h)
                if r is None or not cs:
                    continue
                row[f'差{h}'] = (r - S.mean(cs)) * 100
                row[f'対SPY{h}'] = (r - s) * 100 if s is not None else None
            rows.append(row)
        summ = {}
        for h in (12, 36, 60):
            v = [r[f'差{h}'] for r in rows if f'差{h}' in r]
            vs = [r[f'対SPY{h}'] for r in rows if r.get(f'対SPY{h}') is not None]
            if v:
                summ[f'{h}か月'] = {'社数': len(v), '比較群との差の中央値(%/年)': round(S.median(v), 2), '平均': round(S.mean(v), 2),
                                  '比較群に勝った割合': round(sum(x > 0 for x in v) / len(v), 3),
                                  'SPYとの差の中央値': round(S.median(vs), 2) if vs else None,
                                  'SPYに勝った割合': round(sum(x > 0 for x in vs) / len(vs), 3) if vs else None}
        out[k] = {'引き金の社': len(evs), '結果': summ, '例': [f"{r['t']} FY{r['fy']}" for r in rows[:12]]}
    vd = {}
    for k in ('S1', 'S2'):
        s36 = out[k]['結果'].get('36か月')
        if not s36 or s36['社数'] < 30:
            vd[k] = '判定不能'
        elif s36['比較群との差の中央値(%/年)'] <= -2 and s36['比較群に勝った割合'] <= 0.40:
            vd[k] = '売るのが良い（支持）'
        elif s36['比較群との差の中央値(%/年)'] >= 2:
            vd[k] = '売るのは害'
        else:
            vd[k] = '弱い'
    return out, vd, sum(len(v) for v in controls.values())


def main():
    P = load_panel()
    F = features(P)
    F0 = features(P, zero_debt=True)          # 感度（事前登録の外・結果を見る前に足した）: 負債のタグが無い社年を負債0と読む＝初版の読み方
    c2t = {}
    for t, c in json.load(open(os.path.join(BASE, 'out', '_cik_tickers.json'))).items():
        c2t.setdefault(int(c), []).append(t)
    ever = {c for c in F if any(held(F, c, y) for y in F[c])}
    ever0 = {c for c in F0 if any(held(F0, c, y) for y in F0[c])}
    no_ticker = [c for c in ever if c not in c2t]
    tick = {c: sorted(c2t[c], key=len)[0] for c in ever if c in c2t}
    tick0 = {c: sorted(c2t[c], key=len)[0] for c in ever0 if c in c2t}
    PX = prices(set(tick.values()) | set(tick0.values()) | {'SPY'})
    spy = PX['SPY']
    last = max(spy)
    res = {}
    for wacc in (WACC, 8.0, 10.0):
        out, vd, nc = run(F, tick, PX, spy, last, wacc)
        res[f'WACC{wacc:g}%'] = {'判定': vd, '引き金': out, '比較群の社年': nc}
    out0, vd0, nc0 = run(F0, tick0, PX, spy, last, WACC)
    doc = {'generated': time.strftime('%Y-%m-%d'), 'tool': 'night/gaps_sell.py', 'prereg': 'out/gaps7_prereg.json Q3_sell（9c28f6c）',
           '判定（主＝WACC9%・36か月）': res['WACC9%']['判定'], '結果': res,
           '結果を見る前の修正': '負債・自己資本・D&A・利息・現金の候補タグを採取器 hachimon_fetch に寄せて広げ、負債のタグが一つも無い社年は負債0ではなく『測れない』にした（初版は HD 2016 の ROIC を 389.6% と出していた）。検定を一度も走らせ終える前に見つけた',
           '★事前登録の外の感度_負債のタグが無い社年を負債0と読む（初版の読み方・WACC9%・結果を見る前に足した）': {'判定': vd0, '引き金': {k: v for k, v in out0.items() if k in ('S1', 'S2')},
                                                                  '比較群の社年': nc0, '一度でも保有の条件を満たした社': len(ever0)},
           '母集団': {'一度でも保有の条件を満たした社': len(ever), 'うち今ティッカーが無く外れた社（生存バイアス）': len(no_ticker),
                    '株価が取れた社': sum(1 for c in tick if PX.get(tick[c]))},
           '注': 'frames は暦年にそろえる（6月決算の社は損益と貸借の時点がずれる）。負債のタグが一つも無い社年は測れない（無借金でタグを出さない社も抜ける）。定性の部分（堀の減衰・disrupt・erosion・質スコアの連続低下）は測れない。今ティッカーが無い社は入らない＝倒産した社が抜ける（引き金の社を良く見せる向き）'}
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1)
    print('判定', doc['判定（主＝WACC9%・36か月）'], doc['母集団'])
    for w, r in res.items():
        print('==', w, r['判定'], '比較群', r['比較群の社年'])
        for k, v in r['引き金'].items():
            print('  ', k, v['引き金の社'], v['結果'].get('36か月'), '| 12:', v['結果'].get('12か月', {}).get('比較群との差の中央値(%/年)'),
                  '60:', v['結果'].get('60か月', {}).get('比較群との差の中央値(%/年)'))
    print('== 感度（負債タグ無し=0）', vd0, '比較群', nc0)
    for k in ('S1', 'S2'):
        print('  ', k, out0[k]['引き金の社'], out0[k]['結果'].get('36か月'))


if __name__ == '__main__':
    main()
