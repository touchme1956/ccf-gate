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
  ・★**割る・引く両辺の通貨（XBRL の units キー）がそろうときだけ計算する**（2026-09-23）。
    20-F 提出体は報告通貨と USD 便宜換算の両方を持つので、タグごとに単位を選ぶと別通貨を掴む
    （実害 WIT: 営業利益 USD ÷ 利息 INR＝0.13）。そろわなければ空欄＋理由 `unit_mismatch`
  ・★**CIK はパックの原本（`_meta.source` の /edgar/data/{CIK}/）を優先**し、無いときだけティッカー表
    （実害: 台帳『AMBIQ』＝Ambiq Micro なのに表の AMBIQ は Ambipar を引いた）

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

# ★2026-08-13 追加: **利息タグには基準がある**。上の候補列は「代替」として並べてあるが、
#   実測すると `taxonomy_agreement` の一致率は **0.345** しかない＝そもそも同じ概念ではない。
#   とくに危ないのが2つ——
#     `FinanceCosts`(IFRS)  = 支払利息 **＋ 為替差損・リース利息・引当の割引** の上位概念。
#         実害: 中南米の高金利・通貨安の社（AFYA/TIGO/TIMB/AXIA/ASAIY/CEPU）で
#         **nde が純現金なのに利払カバーが3未満**という内部矛盾が出る＝為替差損を利息と読んでいる
#     `InterestIncomeExpenseNet` = 受取利息と**相殺後の純額**。実測で符号が逆に出る例あり
#         （InterestExpenseDebt 777,000,000 に対し同年 −950,500,000）
#   → 候補列そのものは**変えない**（`intcov` は retro_features2.py と同一基準で、
#      歴史側の実測〔濃縮11.0倍〕がその基準で出ている。ここを黙って変えると
#      「基準の違う二つを割る」型を自分で作る）。
#      代わりに **基準を記録し、真正の利息だけで作った `intcov_strict` を別に出す**。
#      ＝roic の `_meta.basis.roic`（through-cycle / single-year / na）とまったく同じ作法。
INT_BASIS = {
    # 真正の利息（＝この基準の値だけが「利息を払えるか」を測っている）
    "InterestExpense": "interest", "InterestExpenseDebt": "interest",
    "InterestExpenseNonoperating": "interest", "InterestExpenseBorrowings": "interest",
    "InterestExpenseOperatingAndNonoperating": "interest", "InterestCostsIncurred": "interest",
    # 上位概念（利息＋その他の財務費用。過小に見える＝カバーが実際より低く出る側）
    "InterestAndDebtExpense": "interest_plus", "InterestAndDebtExpenseNet": "interest_plus",
    "FinanceCosts": "finance_costs",
    # 純額（受取利息と相殺。符号すら逆になりうる）
    "InterestIncomeExpenseNet": "net",
}
INT_PURE = [t for t in INT + INT_EXT if INT_BASIS.get(t) == "interest"]
# ★現金で払った利息（CF計算書の補足開示）。**発生ベースの利息費用とは基準が違う**
#   （資本化利息を除く・未払や PIK を含まない・支払時期のずれ）ので `intcov` には混ぜない。
#   だが**測れないよりはるかにまし**——実害: TDG（nde 5.88・債務超過）は
#   年次の利息費用タグを一つも持たず、四半期も **Q4 が離散タグで存在しない**
#   （米国の10-Kは通期しか出さない）ので3本しか揃わず、この経路が無いと**完全に不可視**になる。
#   ⚠ `InterestPaidNet` の "Net" は**資本化利息を除く**の意味で、受取利息との相殺ではない。
INT_CASH = ["InterestPaidNet", "InterestPaid"]
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
# --out FILE: 書き先を指定（正本も partial も書かない。score_all.js の --out と同じ作法）
_outp = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None


class _U(dict):
    """{年: 値} に **XBRL の units キー**（'USD' / 'INR' …）を持たせた dict。
       ★2026-09-23: **通貨をそろえずに割っていた**（実害: WIT の intcov_strict が
       営業利益 USD ÷ 支払利息 INR で 0.13＝誤キル）。20-F の外国提出体は同じタグを
       報告通貨と USD の便宜換算の両方で持つので、タグごとに単位を選ぶと
       分子と分母で**別の通貨**を掴みうる。割る・引く前に必ず `same_unit()` を通す。"""
    unit = None


def _u(vals, unit):
    m = _U(vals)
    m.unit = unit
    return m


def same_unit(*us):
    """単位が全部そろっているときだけ True。**単位が判らない（None）もそろっていない側に数える**
       ——判らないものを同じと見なすのは、欠測をゼロと読むのと同じ型（ルール7）。"""
    return all(u is not None for u in us) and len(set(us)) == 1


def unit_mismatch_note(what, pairs):
    """null の理由文。pairs = [(名前, タグ, 単位), …]"""
    return ('unit_mismatch: ' + ' と '.join(f'{nm} {tg or "?"}[{u or "単位不明"}]' for nm, tg, u in pairs)
            + f'＝通貨（XBRL の units）がそろわないので {what} を算出しない（割らない）')


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
        prev, units = {}, set()
        for tg in tags:
            m, e, _ = annual(F, [tg], allow_neg=allow_neg)
            for y, v in m.items():
                if y in merged:
                    seen_pairs.append((tagof[y], tg, merged[y], v))   # 重なり＝改称の検算材料
                else:
                    merged[y], tagof[y] = v, tg
                    prev[y] = e.get(y)
                    units.add(m.unit)
        # 年ごとに別のタグを接ぐので、単位が一つにそろわなければ unit=None（割る側が拒む）
        return _u(merged, units.pop() if len(units) == 1 else None), prev, tagof, seen_pairs
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
            return _u({y: v[1] for y, v in seen.items()}, un), {y: v[2] for y, v in seen.items()}, tg
    return _u({}, None), {}, None


def quarters_sum(F, tags, fy_end):
    """★2026-08-13 追加: **年次タグが無い社のために四半期を足して12ヶ月を作る**。
       実害: TDG（nde 5.88・債務超過＝台帳で最もレバレッジの重い社）は年次の利息タグを
       一つも持たず、あるのは `InterestIncomeExpenseNet`（**負**＝純額）と `InterestPaidNet`（現金）だけ。
       四半期には `InterestExpenseNonoperating` が実在するので、足せば真正の利息で測れる。
       ⚠ **もっともらしい誤値より空欄**——次のどれかが崩れたら作らない:
         ・その会計年度に**ちょうど4本**そろう ・全部が正（費用）
         ・期間の合計が11〜13ヶ月 ・重なりが無い
       返り値: (tag, 合計, [期間], 単位) か (None, None, None, None)"""
    if not fy_end:
        return None, None, None, None
    import datetime as _dt
    try:
        end = _dt.date.fromisoformat(fy_end)
    except Exception:
        return None, None, None, None
    start_lim = end - _dt.timedelta(days=370)
    for tg in tags:
        js = _ns(F, tg)
        if not js:
            continue
        U = js.get('units') or {}
        if not U:
            continue
        un = 'USD' if 'USD' in U else max(U, key=lambda k: len(U[k]))
        best = {}
        for x in U[un]:
            s, e, fd = x.get('start'), x.get('end'), x.get('filed', '')
            if not s or not e:
                continue
            try:
                ds, de = _dt.date.fromisoformat(s), _dt.date.fromisoformat(e)
            except Exception:
                continue
            m = (de.year * 12 + de.month) - (ds.year * 12 + ds.month)
            if m < 2 or m > 4:            # 四半期だけ（年次・半期は別経路）
                continue
            if not (start_lim < de <= end):
                continue
            k = (s, e)
            if k not in best or fd > best[k][0]:
                best[k] = (fd, x['val'])
        qs = sorted(best.items())
        if len(qs) != 4:
            continue
        if any(v[1] <= 0 for _, v in qs):          # 費用なのに0以下＝符号規約が違う
            continue
        spans = [(_dt.date.fromisoformat(a), _dt.date.fromisoformat(b)) for (a, b), _ in qs]
        if any(spans[i][0] < spans[i - 1][1] for i in range(1, 4)):   # 重なり
            continue
        tot_m = (spans[-1][1].year * 12 + spans[-1][1].month) - (spans[0][0].year * 12 + spans[0][0].month)
        if tot_m < 11 or tot_m > 13:
            continue
        return tg, sum(v[1] for _, v in qs), [f'{a}→{b}' for (a, b), _ in qs], un
    return None, None, None, None


def pick_int(F, op, anchor, tags):
    """利息を1本選ぶ。**比の分子と分母は必ず同じ年**（年をまたいで割るのが「基準の違う二つ」の型）。
       アンカーに届く候補のうち優先順が最上位／届かなければ最新年が最も新しい候補／
       アンカーから2年以上古いなら算出不能（古い利息で今日を裁かない・BKNG型の回避）。
       返り値: (tag, year, value, unit) か (None, 'stale'|'none', 注記, None)
       ⚠ 単位（通貨）は**選ぶ基準にしない**——ここで同じ通貨の候補へ黙って乗り換えると
         利息の基準（interest / finance_costs …）が静かに入れ替わる。単位の検問は割る側で行う。"""
    cands = []
    for tg in tags:
        m, _, _ = annual(F, [tg])
        ys = [y for y in sorted(set(m) & set(op)) if m[y] > 0]
        if ys:
            cands.append((tg, ys, m))
    if not cands:
        return None, 'none', None, None
    for tg, ys, m in cands:
        if anchor in ys:
            return tg, anchor, m[anchor], m.unit
    newest = max(ys[-1] for _, ys, _ in cands)
    if anchor is not None and anchor - newest <= 1:
        tg, ys, m = next(c for c in cands if c[1][-1] == newest)
        return tg, newest, m[newest], m.unit
    return None, 'stale', (f'支払利息の年次は {newest}年が最新でアンカー {anchor}年から'
                           '2年以上古い＝古い利息で今日を裁かない（BKNG型の回避）'), None


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
                if same_unit(got[y][2], m.unit):   # 通貨の違う二つを「不一致」と数えない
                    out.append((got[y][0], tg, got[y][1], v))
            else:
                got[y] = (tg, v, m.unit)
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
    tick2cik, cik2title = {}, {}
    j = http('https://www.sec.gov/files/company_tickers.json')
    if j:
        for v in json.loads(j).values():
            tick2cik.setdefault(v['ticker'].upper(), str(v['cik_str']).zfill(10))
            cik2title.setdefault(str(v['cik_str']).zfill(10), v['title'])

    packs = sorted(glob.glob('out/*_gate_pack.json'))
    items, jp, nocik, fail, agree = {}, [], [], [], []
    cik_conflicts = []
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
        # ★2026-09-23: **CIK はパック自身の原本から引く**。ティッカー表だけで引くと、
        #   台帳の呼び名と SEC の現行ティッカーがずれた社で**別の会社**を掴む
        #   （実害: 台帳の『AMBIQ』＝Ambiq Micro〔CIK 1500412・SEC上は AMBQ〕なのに、
        #    SEC の表の AMBIQ は破産で Q が付いた Ambipar〔CIK 1937441〕＝v11 の全欄が別会社の数字）。
        #   パックの `_meta.source` は審査官が読んだ原本の URL で、EDGAR の
        #   `/edgar/data/{CIK}/` を含む＝**その社の身元**。これを最優先し、無いときだけ表を使う。
        #   食い違いは黙って直さず `holes.cik_conflict` に名前と社名つきで出す。
        src = str((d.get('_meta') or {}).get('source') or '')
        msrc = re.search(r'sec\.gov/Archives/edgar/data/(\d+)/', src)
        cik_src = msrc.group(1).zfill(10) if msrc else None
        cik_tick = tick2cik.get(t.upper())
        cik = cik_src or cik_tick
        if cik_src and cik_tick and cik_src != cik_tick:
            cik_conflicts.append({'t': t, 'cik_pack_source': cik_src,
                                  'title_pack_source': cik2title.get(cik_src),
                                  'cik_ticker_table': cik_tick,
                                  'title_ticker_table': cik2title.get(cik_tick),
                                  'used': 'pack_source'})
        if not cik:
            nocik.append(t)
            continue
        raw = http(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json')
        if not raw:
            fail.append(t)
            continue
        J = json.loads(raw)
        F = J.get('facts') or {}
        op, opend, op_tag0 = annual(F, OP)
        # 利息はタクソノミ改称をまたぐが、**年ごとに継ぎ接ぎしない**——実測で
        #   InterestExpense と InterestAndDebtExpense の一致率は 0.478（後者は債務消滅損等を含む）＝
        #   別概念。**会社ごとに一つのタグ**（アンカー年に届く最上位の候補）だけを使う。
        agree.extend(overlap_pairs(F, INT + INT_EXT))
        rev, _, _ = annual(F, REV)
        ocf, _, _ = annual(F, OCF)
        cap, _, _ = annual(F, CAPEX)

        rec = {'nm': nm, 'cik': cik, 'cik_from': 'pack_source' if cik_src else 'ticker_table',
               'entityName': J.get('entityName'), 'nulls': {}}
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
                                   '＝この社は導出（売上−原価−R&D−販管費）が要る')
            op = _u({}, None)
            # ★2026-08-13: **採取器が既に出した答えを読む**（導出を再実装しない・v9.9.65）。
            #   hachimon_fetch は直接タグが届かない社で 売上−原価−R&D−販管費 を導出し、
            #   **その会社自身が報告している年で一致するときだけ採用する**自己検証を掛けている。
            #   その結果が `gm`（営業利益率）としてパックに入っているので、売上を掛けて戻す。
            #   ⚠ ここで導出式をもう一度書くと、採取器と違う答えを出す二つの検査器ができる。
            #   実害: KLAC は🟢投下可なのに、この経路が無いと**分子が無くて利払カバーが永久に測れない**
            gmv = d.get('gm')
            if gmv is not None and rd and int(rd) in rev:
                try:
                    op = _u({int(rd): float(gmv) / 100.0 * rev[int(rd)]}, rev.unit)
                    rec['op_source'] = 'pack_gm'
                    rec['nulls']['all'] += (f'。**パックの gm {gmv}% × 売上 {rev[int(rd)]:,.0f} で復元**'
                                            '（採取器が自己検証つきで導出した値・再実装ではない）')
                except (TypeError, ValueError):
                    op = _u({}, None)
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
                if same_unit(ocf.unit, cap.unit):
                    rec['fcf5_all_pos'] = all(ocf[y] - cap[y] > 0 for y in W)
                else:   # 引き算も割り算と同じ——通貨の違う二つを引かない
                    rec['nulls']['fcf5_all_pos'] = unit_mismatch_note(
                        'FCF(営業CF−設備投資)', [('営業CF', None, ocf.unit), ('設備投資', None, cap.unit)])
            elif all(y in ocf for y in W) and not cap:
                # 設備投資のタグが一度も無い＝設備投資がほぼ無い事業（CF計算書は無い行を載せない）
                rec['fcf5_all_pos'] = all(ocf[y] > 0 for y in W)
                rec['nulls']['fcf5_note'] = '設備投資タグが一度も無い＝営業CFのみで判定'
            else:
                rec['nulls']['fcf5_all_pos'] = '営業CFまたは設備投資の年次が5年そろわない'
            ys = [y for y in sorted(set(rev) & set(op)) if rev[y]]
            if ys and (anchor in ys or anchor - ys[-1] <= 1) and not same_unit(op.unit, rev.unit):
                rec['nulls']['opm'] = unit_mismatch_note(
                    '営業利益率', [('営業利益', None, op.unit), ('売上', None, rev.unit)])
            elif ys and (anchor in ys or anchor - ys[-1] <= 1):
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
        tg, y, val, iu = pick_int(F, op, anchor, INT + INT_EXT)
        if tg is None and y == 'stale':
            rec['intcov_na_reason'] = 'stale'
            rec['nulls']['intcov'] = val
        op_tag = rec.get("op_source") or op_tag0
        if tg:
            rec['int'], rec['int_tag'], rec['int_fy'] = val, tg, y
            rec['int_unit'], rec['op_unit'] = iu, op.unit
            rec['int_basis'] = INT_BASIS.get(tg, 'unknown')
            if same_unit(op.unit, iu):
                rec['intcov'] = round(op[y] / val, 3)
            else:
                # ★通貨の違う二つを割らない（WIT: 営業利益 USD ÷ 利息 INR）。空欄＋理由
                rec['intcov_na_reason'] = 'unit_mismatch'
                rec['nulls']['intcov'] = unit_mismatch_note(
                    '利払カバー', [('営業利益', op_tag, op.unit), ('利息', tg, iu)])
            if y != anchor:
                rec['nulls']['intcov_fy'] = (f'アンカー {anchor}年に利息が無いので'
                                             f'**分子・分母とも {y}年**で算出（年をまたいで割らない）')
            # ★真正の利息だけで作り直す。基準が `interest` でない社は **null にして理由を書く**
            #   ——「測っていない」を「測って問題なし」にしない（絶対のルール7の同族）
            if rec['int_basis'] == 'interest':
                if rec.get('intcov') is not None:
                    rec['intcov_strict'] = rec['intcov']
                else:
                    rec['nulls']['intcov_strict'] = rec['nulls']['intcov']
            else:
                stg, sy, sval, su = pick_int(F, op, anchor, INT_PURE)
                if stg and not same_unit(op.unit, su):
                    rec['int_strict_tag'], rec['int_strict_fy'], rec['int_strict_unit'] = stg, sy, su
                    rec['nulls']['intcov_strict'] = unit_mismatch_note(
                        '真正の利息による利払カバー', [('営業利益', op_tag, op.unit), ('利息', stg, su)])
                elif stg:
                    rec['intcov_strict'] = round(op[sy] / sval, 3)
                    rec['int_strict_tag'], rec['int_strict_fy'] = stg, sy
                else:
                    rec['nulls']['intcov_strict'] = (
                        f'採れた利息タグ {tg} の基準は **{rec["int_basis"]}**＝'
                        + {'finance_costs': 'IFRSの財務費用（為替差損・リース利息・引当の割引を含む上位概念）',
                           'interest_plus': '利息＋債務消滅損等を含む上位概念',
                           'net': '受取利息と相殺した純額（符号すら逆になりうる）'}.get(
                               rec['int_basis'], '不明')
                        + '。真正の利息タグはこの社の facts に無い＝利払カバーは算出不能')
        elif rec['no_debt_evidence']:
            rec['intcov_na_reason'] = 'no_debt'          # 無借金＝測れないのではなく「無い」
        elif not rec.get('intcov_na_reason'):
            rec['intcov_na_reason'] = 'unmeasured'        # 負債の痕跡はあるのに利息が採れない

        # ★年次の真正タグが無い社は、四半期を足して12ヶ月を作る（TDG がこの形）。
        #   **分子はアンカー年の営業利益**なので、分母も同じ会計年度でなければ足さない
        if rec.get('intcov_strict') is None and not rec['no_debt_evidence'] and anchor in op:
            qtg, qsum, qspans, qu = quarters_sum(F, INT_PURE, rec.get('fy_end'))
            if qtg and qsum > 0 and not same_unit(op.unit, qu):
                rec['nulls']['intcov_strict_quarters'] = unit_mismatch_note(
                    '四半期合算の利払カバー', [('営業利益', op_tag, op.unit), ('利息(四半期)', qtg, qu)])
            elif qtg and qsum > 0:
                rec['intcov_strict'] = round(op[anchor] / qsum, 3)
                rec['int_strict_tag'], rec['int_strict_fy'] = qtg, anchor
                rec['int_strict_period'] = 'quarters_sum'
                rec['int_strict_spans'] = qspans
                rec['nulls'].pop('intcov_strict', None)
                if rec.get('intcov') is None:            # intcov 側も埋まっていなければ併記
                    rec['int'], rec['int_tag'], rec['int_fy'] = qsum, qtg, anchor
                    rec['int_basis'], rec['int_period'] = 'interest', 'quarters_sum'
                    rec['intcov'] = rec['intcov_strict']
                    rec['intcov_na_reason'] = None
                    rec['nulls'].pop('intcov', None)

        # ★最後の砦: 現金で払った利息（基準が違うので **別の欄**に置き、intcov には混ぜない）
        if rec.get('intcov_strict') is None and not rec['no_debt_evidence'] and anchor in op:
            ctg, cy, cval, cu = pick_int(F, op, anchor, INT_CASH)
            if ctg and not same_unit(op.unit, cu):
                rec['nulls']['intcov_cash'] = unit_mismatch_note(
                    '現金基準の利払カバー', [('営業利益', op_tag, op.unit), ('支払利息(現金)', ctg, cu)])
            elif ctg:
                rec['intcov_cash'] = round(op[cy] / cval, 3)
                rec['int_cash_tag'], rec['int_cash_fy'] = ctg, cy
                rec['nulls']['intcov_cash'] = ('現金で払った利息（資本化利息を除く）÷営業利益。'
                                               '**発生ベースの利息費用ではない**＝キルの物差しにするなら'
                                               'この基準の違いを承知のうえで')

        # ★被覆の穴を**推測で埋めず、名前で出す**（2026-08-13）。
        #   候補列に無いタグで利息を報告している社は、タグ名を足せば測れるようになる
        #   ——ADI の `UnsecuredLongTermDebt`（候補に無い名前で5,192百万$）と同じ型。
        #   ⚠ここでは値を採らない。**実在するタグ名を作業リストへ出すだけ**——
        #     見つけたタグが本当に利息かは人が確かめる（勝手に足すと基準が混ざる）
        if rec.get('intcov') is None and rec.get('intcov_na_reason') in ('unmeasured', 'stale'):
            known, found = set(INT + INT_EXT), []
            for ns, dd in (F or {}).items():
                if not isinstance(dd, dict):
                    continue
                for tg in dd:
                    if tg in known or 'Interest' not in tg:
                        continue
                    if not any(k in tg for k in ('Expense', 'Cost', 'Paid', 'Charge')):
                        continue
                    m, _, _ = annual(F, [tg])
                    ys = [yy for yy in sorted(set(m) & set(op)) if m[yy] > 0]
                    if ys and anchor is not None and anchor - ys[-1] <= 1:
                        found.append(f'{ns}:{tg}({ys[-1]})')
            if found:
                rec['int_tag_candidates'] = sorted(set(found))
        items[t] = rec
        if (i + 1) % 40 == 0:
            print(f'  … {i+1}/{len(packs)}', file=sys.stderr)
        time.sleep(0.11)

    out = {'generated': time.strftime('%Y-%m-%d'), 'tool': 'night/v11_facts.py',
           'definitions': {
               'intcov': 'OperatingIncomeLoss(年次)/InterestExpense(年次)＝retro_features2.py と同一定義・同一タグ順',
               'int_basis': 'interest（真正の利息）/ interest_plus（債務消滅損等を含む）/ '
                            'finance_costs（IFRSの財務費用＝為替差損等を含む）/ net（受取利息と相殺）',
               'intcov_strict': '**基準が interest の利息だけ**で作った利払カバー。'
                                'intcov と違い上位概念・純額を混ぜない＝キルの物差しに使えるのはこちら',
               'int_tag_candidates': '候補列に無いが利息らしいタグを実在するものだけ列挙した作業リスト。'
                                     '**値は採っていない**（本当に利息かは人が確かめる）',
               'intcov_cash': '**現金で払った利息**（資本化利息を除く）で作った利払カバー。'
                              '発生ベースではないので intcov / intcov_strict とは別基準——混ぜて割らないこと',
               'int_strict_period': 'annual か quarters_sum（年次タグが無い社は同一会計年度の四半期4本を合算）',
               'op5_all_pos': 'アンカーFYから5年すべて営業利益が正',
               'fcf5_all_pos': 'アンカーFYから5年すべて (営業CF−設備投資) が正',
               'no_debt_evidence': '有利子負債・利息の痕跡タグが一つも無い＝無借金（上限の不等式で結論）',
               'unit_mismatch': '分子と分母（引き算の両辺）の XBRL units がそろわない＝算出しない。nulls に両辺のタグと単位',
               'cik_from': 'pack_source（パックの _meta.source の EDGAR URL の CIK）/ ticker_table（SEC company_tickers.json）'},
           'holes': {'jp': jp, 'no_cik': nocik, 'fetch_fail': fail,
                     # パックの原本の CIK と SEC ティッカー表の CIK が食い違った社（原本側を採用）
                     'cik_conflict': cik_conflicts,
                     # 通貨（XBRL units）がそろわず算出しなかった欄
                     'unit_mismatch': {t: sorted(k for k, v in r['nulls'].items()
                                                 if str(v).startswith('unit_mismatch'))
                                       for t, r in items.items()
                                       if any(str(v).startswith('unit_mismatch') for v in r['nulls'].values())}},
           'taxonomy_agreement': tax_agree(agree),
           'items': items}
    # ★2026-08-13: **部分実行で正本を潰さない**。`--only` の6社で全299社の在庫を上書きする事故を
    #   実際に踏んだ（score_all.js の `--jp/--us` が正本を約40行で潰したのと同じ型・在庫は git から復元）。
    #   旗つきの実行は `.partial` へ書く＝**構造で塞ぐ**（注意力に頼らない）
    dest = _outp or ('out/v11_facts.partial.json' if ONLY else 'out/v11_facts.json')
    out['partial'] = sorted(ONLY) if ONLY else None
    json.dump(out, open(dest, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    g = lambda k: sum(1 for v in items.values() if v.get(k) is not None)
    nod = sum(1 for v in items.values() if v.get('intcov_na_reason') == 'no_debt')
    unm = sum(1 for v in items.values() if v.get('intcov_na_reason') == 'unmeasured')
    import collections as _c
    bas = _c.Counter(v.get('int_basis') for v in items.values() if v.get('int_basis'))
    cand = [t for t, v in items.items() if v.get('int_tag_candidates')]
    print(f'■ v11 機械項目: {len(items)}社 ／ intcov {g("intcov")} '
          f'（無借金 {nod} ／ 拡張タグのみ {g("intcov_ext")} ／ 未測定 {unm}）'
          f' ／ op5 {g("op5_all_pos")} ／ fcf5 {g("fcf5_all_pos")}')
    qsum = sum(1 for v in items.values() if v.get('int_strict_period') == 'quarters_sum')
    print(f'  利息の基準: ' + ' ／ '.join(f'{k} {v}' for k, v in bas.most_common())
          + f'  → **intcov_strict {g("intcov_strict")}社**（基準が interest のものだけ'
          + (f'・うち四半期合算 {qsum}社' if qsum else '') + '）')
    print(f'  現金で払った利息でしか測れない社: {g("intcov_cash")}社（別基準・混ぜて割らない）')
    if cand:
        print(f'  ⏳候補列に無い利息らしいタグが実在する社 {len(cand)}社（作業リスト・値は採っていない）: '
              + ' '.join(cand[:12]) + (' …' if len(cand) > 12 else ''))
    print(f'  ⚠日本株 {len(jp)}社は SEC 経路に無く**構造的な穴**（CIK不明 {len(nocik)}／取得失敗 {len(fail)}）')
    um = out['holes']['unit_mismatch']
    if um:
        print(f'  ⚠通貨（XBRL units）がそろわず算出しなかった社 {len(um)}: '
              + ' '.join(f'{t}({",".join(v)})' for t, v in sorted(um.items())))
    if cik_conflicts:
        print(f'  ⚠パックの原本の CIK と SEC ティッカー表が食い違う社 {len(cik_conflicts)}（原本側を採用）: '
              + ' '.join(f'{c["t"]}[{c["title_pack_source"]} ≠ 表:{c["title_ticker_table"]}]'
                         for c in cik_conflicts))
    print(f'→ {dest}' + ('  ⚠部分実行なので正本は書き換えていない' if (ONLY or _outp) else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
