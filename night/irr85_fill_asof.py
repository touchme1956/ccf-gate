#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_fill_asof.py — **irr=85 の当時(2018)の欠測を埋めて標本外の n=4 という縛りを外す**
（2026-08-11新設・ユーザー指示「n=4も外して」）

なぜ要るか:
  `night/irr85_criteria.py` が現行の下限を当時の値へ当てたとき、**28社中11社が判定不能**だった。
  とくに**標本外（2013/2015のみで読まれた社＝循環していない唯一の検証）は7社中4社しか判定できず**、
  「n=4 では何も言えない」が結論の縛りになっていた。

欠測の正体（走査して特定した）:
  `retro_features_2018.py` の nde18 は `if lt is not None and cash is not None` で、
  **長期有利子負債の候補タグが1つも当たらないと None** になる。ところがその原因は2種類ある——
    (A) **本当に無借金**（NVMI / DLB / OLED＝2017-2019の全期間で有利子負債の痕跡がゼロ）
    (B) **候補タグに無い名前で報告している**（**ADI = `UnsecuredLongTermDebt` 5,192百万$**）
  **この2つを区別せずに None にしていたのが穴**。(A) は debt=0 が事実なので nde を計算できる。
  ——これは `hachimon_fetch.debt_evidence()` が既に確立した作法（候補タグの外まで独立に走査し、
  痕跡が一つも無いときだけ debt=0 を事実とする）を、歴史側の在庫へ当てただけ。
  **「タグが無い」と「値が0」を区別する**＝絶対のルール7そのもの。

何をするか:
  companyfacts（**companyconcept ではない**——v9.9.128 で空を返すことを確認済み）から
  FY2018 の 有利子負債・現金・営業利益・D&A・FCF・純利益 を採り、
  **`retro_features_2018.py` とまったく同じ式**で nde18 と conv5 を再計算する。
  新しい定義も新しい定数も作らない。埋まらないものは**理由つきで埋まらないままにする**（ルール7）。

  ⚠ **この道具は在庫を書き換えない。** `out/irr85_asof_fill.json` へ別に出し、
  irr85_criteria.py がそれを**補助として読む**。元の retro_features_2018.json は歴史検証の
  他の道具も読むので、ここで書き換えると「基準の違う二つ」を作る。

★--today モード（2026-08-11 ユーザー指示「違う今の銘柄も昔の基準と同じように測って」）:
  **今日の irr=85 を、歴史とまったく同じ式で測り直す。** これが要る理由は実害があるから——
  別枠85の下限 **FCF転換 0.639 は WST の 5年合計比 `sum(FCF 5年)÷sum(NI 5年)`** から作られたのに、
  門の `ccfIrr85Frame` は **パックの単年 `fcf/ni`** に当てている。
  **同じ WST で 0.639（5年）vs 0.95（単年）＝1.49倍の差**。
  ＝**「基準の違う二つを割る」型**（KLACの株式分割／ADRのper／JP門0のpt／through-cycleの片側変更／
  門0の売上タグの錨／台帳のperと自己相対のpe／在庫の版の混在 に続く型）。
  opm・cagr5・nde の3つは歴史側と門で定義が一致しているので、**割れているのは conv だけ**。

使い方: python3 night/irr85_fill_asof.py [--json] [--today]
出力  : out/irr85_asof_fill.json      … 歴史側の欠測を埋めた補助在庫
        out/irr85_today_histbasis.json … --today で今日の irr=85 を歴史と同じ式で測った値
"""
import json
import os
import re
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'night'))
import audit_stale_bs as SB          # companyfacts 経由の取得を再利用（二重実装を作らない）

AS_JSON = '--json' in sys.argv[1:]
TODAY = '--today' in sys.argv[1:]

# retro_features_2018.py と**同じ候補**＋走査で見つかった不足分だけを足す
DEBT_LT = ["LongTermDebtNoncurrent", "LongTermDebt", "DebtAndCapitalLeaseObligations",
           "LongTermDebtAndCapitalLeaseObligations",
           "UnsecuredLongTermDebt", "UnsecuredLongTermDebtNoncurrent"]   # ← ADI がここに居た
DEBT_C = ["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings",
          "LongTermDebtAndCapitalLeaseObligationsCurrent", "UnsecuredDebtCurrent",
          "CommercialPaperAtCarryingValue"]
CASH = ["CashAndCashEquivalentsAtCarryingValue"]
OP = ["OperatingIncomeLoss"]
DEP = ["DepreciationDepletionAndAmortization", "Depreciation"]
AMO = ["AmortizationOfIntangibleAssets"]
NI = ["NetIncomeLoss", "ProfitLoss"]
OCF = ["NetCashProvidedByUsedInOperatingActivities",
       "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]
CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
         "PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets",
         # 2026-08-11 追加: **RBC は FY2023 で PaymentsToAcquirePropertyPlantAndEquipment を止め、
         #   FY2022 以降 `PaymentsForCapitalImprovements` で報告している**。候補に無いので
         #   FY2024-2026 の設備投資が丸ごと 0 と読まれ、5年FCF転換が 1.361 と**過大**に出ていた。
         "PaymentsForCapitalImprovements",
         "PaymentsToAcquireMachineryAndEquipment", "PaymentsToAcquireBuildings"]

# 設備投資の「痕跡」を候補タグの外まで探すための網（capex=0 を事実と言えるかの検問）。
#   **絶対のルール7そのもの**——「候補タグに当たらない」と「設備投資が0」は別物で、
#   前者をゼロと読むと FCF が過大に出る（＝この床は甘い側へ壊れる）。
#   DEBTLIKE と同じ作法で、**痕跡が一つも無いときだけ 0 を事実とする**。
#   ⚠買収（PaymentsToAcquireBusinesses…）は痕跡に数えない——FCF の定義は設備投資のみ控除で、
#   買収を混ぜると「買収した年だけ FCF が消える」別の壊れ方になる。
CAPEXLIKE = re.compile(r'(PaymentsToAcquireProperty|PaymentsToAcquireProductive|'
                       r'PaymentsForCapitalImprovement|PaymentsToAcquireMachinery|'
                       r'PaymentsToAcquireBuildings|PaymentsForProceedsFromProductiveAssets|'
                       r'PaymentsToAcquireEquipment|PaymentsForCapitalExpenditure)')


def capex_of(d, year):
    """その年の設備投資。(値, 理由) を返す。**取れないときに 0 を返さない**（ルール7）
       - 候補タグに当たる → その値
       - 候補に当たらないが痕跡がある → (None, '別名で報告') ＝その年は測れない
       - 痕跡が一つも無い → (0, None) ＝設備投資を持たない事実として 0"""
    v, _ = pick(d, CAPEX, year, instant=False)
    if v is not None:
        return v, None
    ns = (d.get('facts', {}) or {}).get('us-gaap', {}) or {}
    for k in ns:
        if not CAPEXLIKE.search(k):
            continue
        for u in (ns[k].get('units', {}) or {}).values():
            if not isinstance(u, list):
                continue
            for x in u:
                if x.get('form') in FORMS and x.get('start') and str(x.get('end', ''))[:4] == str(year):
                    return None, f'設備投資が候補外のタグで報告されている（{k}・{year}年）'
    return 0, None

# 有利子負債の「痕跡」を候補タグの外まで探すための網（debt=0 を事実と言えるかの検問）
DEBTLIKE = re.compile(r'(LongTermDebt|ShortTermBorrow|DebtCurrent|Borrowings|NotesPayable|SeniorNotes|'
                      r'ConvertibleDebt|CapitalLeaseObligations|'
                      r'FinanceLeaseLiability|CommercialPaper|DebtAndCapitalLease)')
# ⚠**残高ではないもの**は痕跡に数えない（2026-08-11に踏んだ誤検出）——
#   `LineOfCreditFacilityMaximumBorrowingCapacity` は**借入枠**（AEIS 500M＝未使用の枠）、
#   `LongTermDebtMaturities...` は**返済スケジュール**（将来の支払予定）、
#   `DebtInstrumentFaceAmount` は**証券の額面**（発行していない枠のことがある）。
#   これらを痕跡に数えると、**真に無借金の社を「痕跡あり」と誤判定して埋められなくなる**
#   ＝ルール7が守ろうとしたのと逆向きの誤り（測れるものを測れないことにする）。
NOT_BALANCE = re.compile(r'(LineOfCreditFacility|Maturities|FaceAmount|InterestRate|'
                         r'DebtInstrumentTerm|Covenant|UnusedCapacity)')


def facts(t):
    cik = SB.cik_of(t)
    return (SB.facts(cik) if cik else None)


# 20-F を受ける（**NVMI はイスラエルの外国私募発行体で 20-F 提出**・報告通貨はUSD）。
#   10-K だけに絞ると「データが無い」ではなく「様式が違うだけ」の社を落とす
FORMS = ('10-K', '10-Q', '20-F')


def pick(d, tags, year, instant=True):
    """FY{year} の値。instant=残高（start無し）／False=期間（start有り）。同じ期末は後から提出された値を採る"""
    us = (d.get('facts', {}) or {}).get('us-gaap', {}) or {}
    for tag in tags:
        best = None
        for u in ((us.get(tag) or {}).get('units') or {}).values():
            if not isinstance(u, list):
                continue
            for x in u:
                if x.get('form') not in FORMS:
                    continue
                if instant and x.get('start'):
                    continue
                if (not instant) and not x.get('start'):
                    continue
                e = x.get('end', '')
                if not e or e[:4] != str(year):
                    continue
                if not instant:
                    # 通期のみ（期間が330日以上）
                    try:
                        from datetime import date
                        s = date(*map(int, x['start'].split('-')))
                        en = date(*map(int, e.split('-')))
                        if (en - s).days < 330:
                            continue
                    except Exception:
                        continue
                if best is None or x.get('filed', '') > best[1]:
                    best = (x['val'], x.get('filed', ''))
        if best:
            return best[0], tag
    return None, None


def debt_trace(d, year=2018):
    """対象年に有利子負債の**残高**の痕跡があるか（候補タグの外まで）。無ければ debt=0 が事実

    ⚠対象年に限る（±0年）。**AEIS は FY2018 は無借金で、2019年9月の Artesyn 買収で負債が乗った**
    ——±2年の窓で見ると「痕跡あり」になり、FY2018 の真の姿（無借金）を埋められなくなる。
    hachimon_fetch.debt_evidence() が±2年を使うのは「今日の値」を出すためで、
    **as-of の値を出すここでは対象年に限るのが正しい**（基準の違う二つを作らない）。
    """
    us = (d.get('facts', {}) or {}).get('us-gaap', {}) or {}
    for tag, v in us.items():
        if not DEBTLIKE.search(tag) or NOT_BALANCE.search(tag):
            continue
        for u in ((v.get('units') or {})).values():
            if not isinstance(u, list):
                continue
            for x in u:
                if (x.get('end', '')[:4] == str(year)
                        and x.get('form') in FORMS and not x.get('start')
                        and abs(x.get('val', 0)) > 1e6):
                    return f'{tag}={x["val"]/1e6:,.1f}M'
    return None


REV = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
       "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet"]


def today_mode():
    """今日の irr=85 を**歴史とまったく同じ式**で測る（--today）"""
    OPM, CONV, CG, ND = 11.89, 0.639, 1.76, 4.0
    packs = []
    for f in sorted(os.listdir('out')):
        if not f.endswith('_gate_pack.json'):
            continue
        d = json.load(open('out/' + f, encoding='utf-8'))
        if str(d.get('irr')) != '85':
            continue
        packs.append((f.split('_gate_pack')[0], d))
    sa = {r['t']: r for r in json.load(open('out/score_all.json', encoding='utf-8'))}
    print(f'■ 今日の irr=85 {len(packs)}社を**歴史と同じ式**で測る')
    print(f'  ⚠ conv だけ基準が割れている——下限 {CONV} は歴史の **5年合計比** から作られたのに、')
    print(f'     門は**パックの単年 fcf/ni** に当てている（同じWSTで 0.639 vs 0.95＝1.49倍差）\n')
    print(f"  {'':6s}{'FY':>6}{'営利率':>8}{'conv単年':>9}{'conv5年':>9}{'成長':>7}{'nde':>7}  歴史基準の合否 / 門の合否")
    out = {}
    for t, d in packs:
        fy = str((d.get('_meta') or {}).get('reportDate') or '')[:4]
        g = facts(t)
        rec = {'fy': fy}
        if g and fy.isdigit():
            Y = int(fy)
            yrs = list(range(Y - 4, Y + 1))
            fcfs, nis, ok, why_c = [], [], True, None
            for y in yrs:
                ni_y, _ = pick(g, NI, y, instant=False)
                ocf_y, _ = pick(g, OCF, y, instant=False)
                cap_y, capwhy = capex_of(g, y)      # 0と欠測を区別（ルール7・2026-08-11）
                if ni_y is None or ocf_y is None or cap_y is None:
                    ok = False; why_c = capwhy; break
                fcfs.append(ocf_y - cap_y); nis.append(ni_y)
            if ok and sum(nis) > 0:
                rec['conv5_hist'] = round(sum(fcfs) / sum(nis), 3)
            else:
                rec['conv5_note'] = (why_c + '＝ゼロと読まない（ルール7）') if why_c else \
                    f'5年そろわず（{yrs[0]}-{yrs[-1]}）＝単年で代用しない'
            op_y, _ = pick(g, OP, Y, instant=False)
            rev_y, _ = pick(g, REV, Y, instant=False)
            if op_y is not None and rev_y:
                rec['opm_hist'] = round(op_y / rev_y * 100, 2)
        fcf, ni = d.get('fcf'), d.get('ni')
        rec['conv_pack'] = round(fcf / ni, 3) if (isinstance(fcf, (int, float))
                                                 and isinstance(ni, (int, float)) and ni) else None
        rec['gm_pack'] = d.get('gm'); rec['cagr_pack'] = d.get('cagr'); rec['nde_pack'] = d.get('nde')
        # 歴史基準の合否（conv だけ5年へ差し替え・他はパック＝定義が一致している）
        c5 = rec.get('conv5_hist')
        ng = []
        for v, thr, lbl in ((rec['gm_pack'], OPM, '営利率'), (c5, CONV, '転換5年'),
                            (rec['cagr_pack'], CG, '成長')):
            if v is None: ng.append(lbl + '—')
            elif v < thr: ng.append(f'{lbl}{v:.2f}')
        nde = rec['nde_pack']
        if nde is None: ng.append('nde—')
        elif nde > ND: ng.append(f'nde{nde:.2f}')
        unk = any('—' in z for z in ng)
        rec['hist_basis'] = '判定不能' if unk else ('合格' if not ng else '不合格')
        rec['hist_why'] = '/'.join(ng)
        s_ = sa.get(t, {})
        rec['gate'] = '🟢投下可' if s_.get('buy') else ('🔵次点' if s_.get('quali') else '⛔')
        f = lambda z, w=8, p=2: '—'.rjust(w) if z is None else f'{z:>{w}.{p}f}'
        print(f"  {t:6s}{fy:>6}{f(rec.get('gm_pack'))}{f(rec.get('conv_pack'),9,3)}"
              f"{f(c5,9,3)}{f(rec.get('cagr_pack'),7,1)}{f(rec.get('nde_pack'),7)}  "
              f"{rec['hist_basis']}{('['+rec['hist_why']+']') if rec['hist_why'] else '':<22s} / {rec['gate']}")
        out[t] = rec
    # 基準の差でどれだけ動くか
    diff = [(t, r['conv_pack'], r['conv5_hist']) for t, r in out.items()
            if r.get('conv_pack') is not None and r.get('conv5_hist') is not None]
    if diff:
        rr = [b / a for _, a, b in diff if a]
        print(f"\n  conv 単年 vs 5年合計比: {len(diff)}社で比較可 ／ 比の中央値 {st.median(rr):.2f}倍"
              f" ／ 範囲 {min(rr):.2f}〜{max(rr):.2f}倍")
        flip = [t for t, a, b in diff if (a >= 0.639) != (b >= 0.639)]
        print(f"  **基準を歴史へ揃えると合否が変わる社: {len(flip)}社**"
              + (f" → {' '.join(flip)}" if flip else "（今日は無し）"))
    if AS_JSON:
        p = 'out/irr85_today_histbasis.json'
        json.dump(dict(generated='2026-08-11',
                       note=('今日の irr=85 を歴史と同じ式で測った値。conv5_hist は '
                             'sum(FCF 5年)÷sum(NI 5年)＝下限0.639 と同じ基準。'
                             'conv_pack はパックの単年 fcf/ni＝**門が実際に使っている値**で基準が違う'),
                       items=out), open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\n→ {p}')
    return 0


def main():
    if TODAY:
        return today_mode()
    H = json.load(open('out/audit_hist85_today.json', encoding='utf-8'))['rows']

    def rows_of(f):
        d = json.load(open(f, encoding='utf-8'))
        r = d if isinstance(d, list) else (d.get('rows') or d.get('items') or [])
        return [x for x in (list(r.values()) if isinstance(r, dict) else r) if isinstance(x, dict)]
    F1 = {r['ticker']: r for r in rows_of('out/retro_features_2018.json') if r.get('ticker')}
    F2 = {r['ticker']: r for r in rows_of('out/retro_features2_2018.json') if r.get('ticker')}

    need = []
    for h in H:
        t = h['t']
        a, b = F1.get(t, {}), F2.get(t, {})
        miss = [k for k, v in (('nde18', a.get('nde18')), ('conv5', b.get('conv5')),
                               ('opm', b.get('opm')), ('cagr5', b.get('cagr5'))) if v is None]
        if miss:
            need.append((t, miss, '2018' in h['vintages']))

    print(f'■ irr=85 の当時(2018)の欠測を埋める　対象 {len(need)}社')
    print('  ※ 元の在庫は書き換えない（out/irr85_asof_fill.json へ別に出す）——'
          '歴史検証の他の道具も同じ在庫を読むため\n')
    out = {}
    for t, miss, v2018 in need:
        d = facts(t)
        if not d:
            print(f'  {t:6s} companyfacts 取得失敗＝埋めない'); continue
        rec, notes = {}, []
        if 'nde18' in miss:
            lt, lt_tag = pick(d, DEBT_LT, 2018)
            cur, _ = pick(d, DEBT_C, 2018)
            cash, _ = pick(d, CASH, 2018)
            op, _ = pick(d, OP, 2018, instant=False)
            dep, _ = pick(d, DEP, 2018, instant=False)
            amo, _ = pick(d, AMO, 2018, instant=False)
            basis = None
            if lt is None:
                tr = debt_trace(d, 2018)
                if tr is None:
                    lt, basis = 0.0, '真に無借金（FY2018に有利子負債の**残高**の痕跡が一つも無い。借入枠・返済予定・額面は残高でないので数えない）'
                else:
                    notes.append(f'長期負債が候補タグに無く、痕跡は {tr} にある＝**要タグ追加**。埋めない')
            else:
                basis = f'{lt_tag}'
            if lt is not None and cash is not None and op:
                ebitda = op + (dep or 0) + (amo or 0)
                if ebitda > 0:
                    rec['nde18'] = round((lt + (cur or 0) - cash) / ebitda, 3)
                    rec['nde_basis'] = basis
                else:
                    notes.append('EBITDA≤0＝算出不能')
            elif not notes:
                notes.append(f'欠測: lt={lt} cash={cash} op={op}')
        if 'conv5' in miss:
            # **在庫(retro_features2.py:295)と同じ式** = sum(FCF 2014-2018) / sum(NI 2014-2018)。
            #   単年で代用すると「基準の違う二つ」になる（下限0.639は5年の合計比から作られている）
            fcfs, nis, gaps = [], [], []
            for y in range(2014, 2019):
                ni_y, _ = pick(d, NI, y, instant=False)
                ocf_y, _ = pick(d, OCF, y, instant=False)
                cap_y, _ = capex_of(d, y)           # 0と欠測を区別（ルール7・2026-08-11）
                if ni_y is None or ocf_y is None:
                    gaps.append(y); continue
                fcfs.append(ocf_y - (cap_y or 0)); nis.append(ni_y)
            if len(fcfs) == 5 and sum(nis) > 0:
                rec['conv5'] = round(sum(fcfs) / sum(nis), 3)
                rec['conv_basis'] = 'sum(FCF 2014-2018)÷sum(NI 2014-2018)＝在庫と同一式'
            else:
                notes.append(f'conv5 は5年そろわず埋めない（欠測年 {gaps or "—"}／NI合計'
                             f'{"≤0" if sum(nis) <= 0 else "OK"}）＝単年で代用しない（基準の違う二つを作らない）')
        if notes:
            rec['note'] = ' / '.join(notes)
        rec['scope'] = '標本内' if v2018 else '標本外'
        out[t] = rec
        got = ' '.join(f'{k}={v}' for k, v in rec.items() if k in ('nde18', 'conv5'))
        print(f"  {t:6s}{rec['scope']}  {got or '—'}"
              + (f"   {rec.get('nde_basis','')}" if rec.get('nde_basis') else '')
              + (f"   ⚠{rec['note']}" if rec.get('note') else ''))

    filled = sum(1 for r in out.values() if 'nde18' in r or 'conv5' in r)
    print(f'\n  埋まった {filled}社 / 対象 {len(need)}社')
    if AS_JSON:
        p = 'out/irr85_asof_fill.json'
        json.dump(dict(generated='2026-08-11',
                       note=('retro_features_2018.py と同じ式で FY2018 を再計算した補助在庫。'
                             '元の在庫は書き換えない。nde18 の欠測の正体は (A)真に無借金 と '
                             '(B)候補タグに無い名前 の2種類で、区別せず None にしていたのが穴だった'),
                       items=out), open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'→ {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
