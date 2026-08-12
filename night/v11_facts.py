#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/v11_facts.py — **v11 の機械層（層0・層2）が要る数字を原本から採る**

v11（`V11_SPEC.md`）は層0（土俵）と層2（壊れない）を機械で裁くが、**そのうち3つは
今日のパックに欄が無い**——5年FCF全年黒字 / 5年営業利益全年黒字 / 利払カバー。
無い欄を「たぶん大丈夫」で通すのは絶対のルール7の反対側なので、原本(SEC XBRL)から採る。

【定義は発明しない——歴史側と一字一句同じにする】
  ・`intcov = OperatingIncomeLoss(年次) ÷ InterestExpense(年次)`
    タグの並びも `night/retro_features2.py:55,67` と**同一**。ここを変えると
    影の判定（今日の台帳）とその較正（歴史パネル）が別の物差しで動く＝この repo が7回踏んだ
    「基準の違う二つを割る」型になる。
  ・`fcf = 営業CF − 設備投資`、5年すべて正か。`op5` は営業利益が5年すべて正か。
    どちらも歴史側の質実証プール（`retro_moat_durability.py`）と同じ問い。

【「採れない」と「無い」を区別する（ルール7の本旨）】
  利息の年次タグが無い社の大半は**無借金**である。採取器 `hachimon_fetch.debt_evidence()` が
  確立した作法——**候補タグの外まで走査し、痕跡が一つも無いときだけ 0 を事実とする**——を
  そのまま当て、`no_debt_evidence` を立てる。これを区別しないと、
  **無借金の会社を「利払カバーが測れない」という理由で落とす**ことになる
  （歴史パネルでの実測: 層2が落とした81社のうち **68社が未測定**で、恒久毀損は**0社**だった）。

【踏まないようにした落とし穴】
  ・companyconcept は使わない（実測で0件を返す）→ **companyfacts** に統一
  ・年次は期間11〜13ヶ月。同じ期末は**提出が新しいほう**
  ・候補タグは**代替**（構成要素ではない）ので合算しない
  ・パックの会計年度に揃える（無ければ最新年。どちらを使ったか必ず記録）
  ・日本株は SEC 経路に居ない＝**穴として明示**する（黙って対象外にしない）

使い方: python3 night/v11_facts.py [--only T,T,...]
出力: out/v11_facts.json
"""
import glob
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
UA = {'User-Agent': 'ccf-gate fortis5280@gmail.com', 'Accept-Encoding': 'gzip'}

OP = ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"]
# ⚠**同じ概念のタグ名が年代で変わる**。`InterestExpense` は US-GAAP タクソノミの改訂で
#   2019年前後に `InterestExpenseNonoperating` 等へ置き換わったため、歴史(FY2016-18)では
#   3タグで 73% 採れるのに、今日(FY2025-26)では **21%** しか採れない。
#   タグ名に固執すると「同じ定義」のつもりで**別の母集団**を測ることになる——
#   まさにこの repo が7回踏んだ「基準の違う二つ」の型。よって:
#     ・候補は**代替**として優先順に並べ、**アンカー年に届く最上位の候補**を採る
#       （採取器 series() が ASC606 の売上改称で確立した作法と同じ）
#     ・両方ある年で値が一致するかを毎回集計し、`taxonomy_agreement` として出力に残す
#       ＝「同じ概念の改称である」ことを主張ではなく実測で示す
INT = ["InterestExpense", "InterestExpenseDebt", "InterestAndDebtExpense"]
INT_EXT = ["InterestExpenseNonoperating", "InterestExpenseOperatingAndNonoperating",
           "InterestExpenseBorrowings", "InterestIncomeExpenseNet", "FinanceCosts",
           "InterestAndDebtExpenseNet", "InterestCostsIncurred"]
REV = ["Revenues", "RegulatedAndUnregulatedOperatingRevenue",
       "RevenueFromContractWithCustomerExcludingAssessedTax",
       "RevenueFromContractWithCustomerIncludingAssessedTax",
       "SalesRevenueNet", "SalesRevenueGoodsNet", "SalesRevenueServicesNet", "Revenue"]
OCF = ["NetCashProvidedByUsedInOperatingActivities",
       "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
       "CashFlowsFromUsedInOperatingActivities"]
CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
         "PaymentsForCapitalImprovements", "PaymentsToAcquireOtherPropertyPlantAndEquipment",
         "PaymentsToAcquireMachineryAndEquipment", "PaymentsForProceedsFromProductiveAssets",
         "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
         "PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets"]
DEBT_TRACE = set(INT + INT_EXT + [
    "LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtCurrent",
    "LongTermDebtAndCapitalLeaseObligations", "DebtAndCapitalLeaseObligations",
    "ShortTermBorrowings", "OtherShortTermBorrowings", "NotesPayable", "NotesPayableCurrent",
    "LinesOfCreditCurrent", "LongTermLineOfCredit", "SeniorNotes", "ConvertibleDebtNoncurrent",
    "ConvertibleNotesPayable", "UnsecuredLongTermDebt", "SecuredDebt", "LoansPayable",
    "DebtInstrumentCarryingAmount", "InterestPaidNet", "InterestPaid"])

ONLY = None
if '--only' in sys.argv:
    ONLY = set(sys.argv[sys.argv.index('--only') + 1].split(','))


def http(url, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180)
            b = r.read()
            if r.headers.get('Content-Encoding') == 'gzip':
                b = gzip.decompress(b)
            return b
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1 + i)
        except Exception:
            time.sleep(1 + i)
    return None


def _ns(F, tg):
    """タグを**名前空間に依らず**探す。20-F 提出体（ASML/SAP/RELX/RACE 等）は `ifrs-full` に居り、
       us-gaap だけ見ると**丸ごと未測定**になる（=IFRS勢を国籍で落とすのと同じ）。"""
    for ns in ('us-gaap', 'ifrs-full', 'srt'):
        js = (F.get(ns) or {}).get(tg)
        if js:
            return js
    for ns, d in F.items():
        if isinstance(d, dict) and tg in d:
            return d[tg]
    return None


def annual(F, tags, allow_neg=True, per_year=False):
    """{期末年: 値} を候補タグの優先順で返す。候補は**代替**なので合算しない。
       per_year=True のときは「年ごとに、その年に届く最上位の候補」を採る
       （タクソノミ改称で系列が年代で分かれるため。採取器 series() と同じ作法）。"""
    if per_year:
        merged, tagof, seen_pairs = {}, {}, []
        prev = {}
        for tg in tags:
            m, e, _ = annual(F, [tg], allow_neg=allow_neg)
            for y, v in m.items():
                if y in merged:
                    seen_pairs.append((tagof[y], tg, merged[y], v))   # 重なり＝改称の検算材料
                else:
                    merged[y], tagof[y] = v, tg
                    prev[y] = e.get(y)
        return merged, prev, tagof, seen_pairs
    for tg in tags:
        js = _ns(F, tg)
        if not js:
            continue
        U = js.get('units') or {}
        if not U:
            continue
        un = 'USD' if 'USD' in U else max(U, key=lambda k: len(U[k]))
        seen = {}
        for x in U[un]:
            s, e, fd = x.get('start'), x.get('end'), x.get('filed', '')
            if not s or not e:
                continue
            m = (int(e[:4]) * 12 + int(e[5:7])) - (int(s[:4]) * 12 + int(s[5:7]))
            if m < 11 or m > 13:
                continue
            y = int(e[:4])
            if y not in seen or fd > seen[y][0]:
                seen[y] = (fd, x['val'], e)
        if not allow_neg and any(v[1] < 0 for v in seen.values()):
            continue
        if seen:
            return {y: v[1] for y, v in seen.items()}, {y: v[2] for y, v in seen.items()}, tg
    return {}, {}, None


def trace_recent(F, anchor, back=3):
    """有利子負債・利息の痕跡タグのうち、**アンカーから back 年以内に値がある**ものだけ。"""
    got = set()
    for ns, dd in F.items():
        if not isinstance(dd, dict):
            continue
        for k in dd:
            if k not in DEBT_TRACE or k in got:
                continue
            for un, arr in ((dd[k].get('units') or {}).items()):
                for x in arr:
                    e = x.get('end')
                    if e and (anchor is None or int(e[:4]) >= anchor - back):
                        got.add(k)
                        break
                if k in got:
                    break
    return got


def overlap_pairs(F, tags):
    """候補タグどうしが**同じ年に何を言っているか**を集める（診断のみ・判定には使わない）。"""
    got, out = {}, []
    for tg in tags:
        m, _, _ = annual(F, [tg])
        for y, v in m.items():
            if y in got:
                out.append((got[y][0], tg, got[y][1], v))
            else:
                got[y] = (tg, v)
    return out


def tax_agree(pairs):
    """利息タグの改称が「同じ概念の名前替え」であることを、**主張ではなく実測**で示す。
       両方のタグがある年で値が2%以内に一致した割合。低ければ接いではいけない。"""
    if not pairs:
        return {'n': 0, 'note': '重なる年が一つも無い（改称の検算材料が無い）'}
    ok = sum(1 for a, b, va, vb in pairs
             if abs(va - vb) <= 0.02 * max(abs(va), abs(vb), 1))
    ex = [{'primary': a, 'secondary': b, 'v1': va, 'v2': vb} for a, b, va, vb in pairs[:5]]
    return {'n': len(pairs), 'agree_2pct': ok, 'rate': round(ok / len(pairs), 3),
            'examples': ex,
            'note': '両タグがある年での一致率。低ければ「同じ概念の改称」という前提が崩れる'}


def main():
    tick2cik = {}
    j = http('https://www.sec.gov/files/company_tickers.json')
    if j:
        for v in json.loads(j).values():
            tick2cik.setdefault(v['ticker'].upper(), str(v['cik_str']).zfill(10))

    packs = sorted(glob.glob('out/*_gate_pack.json'))
    items, jp, nocik, fail, agree = {}, [], [], [], []
    for i, p in enumerate(packs):
        t = os.path.basename(p).split('_gate_pack')[0]
        if ONLY and t not in ONLY:
            continue
        try:
            d = json.load(open(p, encoding='utf-8'))
        except Exception:
            continue
        nm = str(d.get('nm') or t)
        if re.match(r'^\d{4,5}(\s|$|\.)', nm):
            jp.append(t)
            continue
        cik = tick2cik.get(t.upper())
        if not cik:
            nocik.append(t)
            continue
        raw = http(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json')
        if not raw:
            fail.append(t)
            continue
        F = json.loads(raw).get('facts') or {}
        op, opend, _ = annual(F, OP)
        # 利息はタクソノミ改称をまたぐが、**年ごとに継ぎ接ぎしない**——実測で
        #   InterestExpense と InterestAndDebtExpense の一致率は 0.478（後者は債務消滅損等を含む）＝
        #   別概念。**会社ごとに一つのタグ**（アンカー年に届く最上位の候補）だけを使う。
        agree.extend(overlap_pairs(F, INT + INT_EXT))
        rev, _, _ = annual(F, REV)
        ocf, _, _ = annual(F, OCF)
        cap, _, _ = annual(F, CAPEX)

        rec = {'nm': nm, 'cik': cik, 'nulls': {}}
        rd = ((d.get('_meta') or {}).get('reportDate') or '')[:4]
        anchor_hint = int(rd) if rd else (max(op) if op else None)
        # 痕跡は**直近3年以内のものだけ**数える（`hachimon_fetch.debt_evidence()` と同じ作法）。
        #   全期間で見ると、10年以上前に完済した関係者向け手形1本で無借金の社が
        #   「未測定」に化ける（実測 IRMD: 痕跡は 2013-14 の手形だけ）。
        rec['debt_trace'] = sorted(trace_recent(F, anchor_hint))[:8]
        rec['no_debt_evidence'] = not rec['debt_trace']

        # ── 層0: 5年すべて営業利益黒字 / 5年すべてFCF黒字 ─────────────
        anchor = None
        if op and rd and int(rd) - max(op) > 1 and int(rd) not in op:
            # 営業利益の年次がパックの会計年度から2年以上古い＝**古い数字で今日を裁かない**
            #   （実測 KLAC: `OperatingIncomeLoss` が2015年で終了し 2014年を掴んでいた。
            #    CLAUDE.md が既に記録している型で、正しくは売上−原価−R&D−販管費の導出が要る）
            rec['nulls']['all'] = (f'営業利益の年次が {max(op)}年止まりでパックの {rd}年から古い'
                                   '＝この社は導出（売上−原価−R&D−販管費）が要る。今日は未測定とする')
            op = {}
        if op:
            anchor = int(rd) if (rd and int(rd) in op) else max(op)
            rec['fy'] = anchor
            rec['fy_basis'] = 'pack' if (rd and int(rd) in op) else 'latest'
            rec['fy_end'] = opend.get(anchor)
            W = [anchor - k for k in range(5)]
            if all(y in op for y in W):
                rec['op5_all_pos'] = all(op[y] > 0 for y in W)
            else:
                rec['nulls']['op5_all_pos'] = '営業利益の年次が5年そろわない'
            if all(y in ocf for y in W) and all(y in cap for y in W):
                rec['fcf5_all_pos'] = all(ocf[y] - cap[y] > 0 for y in W)
            elif all(y in ocf for y in W) and not cap:
                # 設備投資のタグが一度も無い＝設備投資がほぼ無い事業（CF計算書は無い行を載せない）
                rec['fcf5_all_pos'] = all(ocf[y] > 0 for y in W)
                rec['nulls']['fcf5_note'] = '設備投資タグが一度も無い＝営業CFのみで判定'
            else:
                rec['nulls']['fcf5_all_pos'] = '営業CFまたは設備投資の年次が5年そろわない'
            ys = [y for y in sorted(set(rev) & set(op)) if rev[y]]
            if ys and (anchor in ys or anchor - ys[-1] <= 1):
                y = anchor if anchor in ys else ys[-1]
                rec['opm'] = round(op[y] / rev[y] * 100, 2)
                rec['opm_fy'] = y
            elif ys:
                rec['nulls']['opm'] = f'売上の年次が {ys[-1]}年止まりでアンカー {anchor}年から古い'
        else:
            rec['nulls']['all'] = 'OperatingIncomeLoss の年次が無い（小計を置かない提出体裁）'

        # ── 層2: 利払カバー ────────────────────────────────────
        #   **比の分子と分母は必ず同じ年**（年をまたいで割るのが「基準の違う二つ」の型）。
        #   アンカー年に両方あればそれを、無ければ**両方そろう最新の年**を使い、その旨を記録する。
        #   ⚠**優先順だけで候補を選ぶと古い年を掴む**（実測: V が 2011年・KLAC が 2014年の
        #     `InterestExpense` を採ってしまった＝BKNG型「取れた値＝最新の値」の裏返し）。
        #     採取器 series() が確立した規則をそのまま当てる——
        #     **アンカーに届く候補のうち優先順が最上位**／届く候補が無ければ最新年が最も新しい候補／
        #     それでもアンカーから2年以上古いなら**算出不能**（古い利息で今日を裁かない）。
        cands = []
        for tg in INT + INT_EXT:
            m, _, _ = annual(F, [tg])
            ys = [y for y in sorted(set(m) & set(op)) if m[y] > 0]
            if ys:
                cands.append((tg, ys, m))
        hit_ie = None
        for tg, ys, m in cands:
            if anchor in ys:
                hit_ie = (tg, anchor, m[anchor])
                break
        if not hit_ie and cands:
            newest = max(ys[-1] for _, ys, _ in cands)
            if anchor is not None and anchor - newest <= 1:
                tg, ys, m = next(c for c in cands if c[1][-1] == newest)
                hit_ie = (tg, newest, m[newest])
            else:
                rec['intcov_na_reason'] = 'stale'
                rec['nulls']['intcov'] = (f'支払利息の年次は {newest}年が最新でアンカー {anchor}年から'
                                          '2年以上古い＝古い利息で今日を裁かない（BKNG型の回避）')
        if hit_ie:
            tg, y, val = hit_ie
            rec['int'], rec['int_tag'], rec['int_fy'] = val, tg, y
            rec['intcov'] = round(op[y] / val, 3)
            if y != anchor:
                rec['nulls']['intcov_fy'] = (f'アンカー {anchor}年に利息が無いので'
                                             f'**分子・分母とも {y}年**で算出（年をまたいで割らない）')
        elif rec['no_debt_evidence']:
            rec['intcov_na_reason'] = 'no_debt'          # 無借金＝測れないのではなく「無い」
        elif not rec.get('intcov_na_reason'):
            rec['intcov_na_reason'] = 'unmeasured'        # 負債の痕跡はあるのに利息が採れない
        items[t] = rec
        if (i + 1) % 40 == 0:
            print(f'  … {i+1}/{len(packs)}', file=sys.stderr)
        time.sleep(0.11)

    out = {'generated': time.strftime('%Y-%m-%d'), 'tool': 'night/v11_facts.py',
           'definitions': {
               'intcov': 'OperatingIncomeLoss(年次)/InterestExpense(年次)＝retro_features2.py と同一定義・同一タグ順',
               'op5_all_pos': 'アンカーFYから5年すべて営業利益が正',
               'fcf5_all_pos': 'アンカーFYから5年すべて (営業CF−設備投資) が正',
               'no_debt_evidence': '有利子負債・利息の痕跡タグが一つも無い＝無借金（上限の不等式で結論）'},
           'holes': {'jp': jp, 'no_cik': nocik, 'fetch_fail': fail},
           'taxonomy_agreement': tax_agree(agree),
           'items': items}
    json.dump(out, open('out/v11_facts.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    g = lambda k: sum(1 for v in items.values() if v.get(k) is not None)
    nod = sum(1 for v in items.values() if v.get('intcov_na_reason') == 'no_debt')
    unm = sum(1 for v in items.values() if v.get('intcov_na_reason') == 'unmeasured')
    print(f'■ v11 機械項目: {len(items)}社 ／ intcov {g("intcov")} '
          f'（無借金 {nod} ／ 拡張タグのみ {g("intcov_ext")} ／ 未測定 {unm}）'
          f' ／ op5 {g("op5_all_pos")} ／ fcf5 {g("fcf5_all_pos")}')
    print(f'  ⚠日本株 {len(jp)}社は SEC 経路に無く**構造的な穴**（CIK不明 {len(nocik)}／取得失敗 {len(fail)}）')
    print('→ out/v11_facts.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
