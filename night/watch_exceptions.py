#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/watch_exceptions.py — **門外例外で買った社を、門が止めている当の指標で四半期ごとに見張る**
（2026-08-09新設・ユーザー「TDGとLOARは特別枠でいれるから、もちろん監視は厳しくしたら？」）

【なぜ要るか】門外例外は「**門が止めているものを承知で越える**」判断。ところが——
  ・パックは**年次報告が基準**（RBC/LOARで確立した扱い）なので、**止めている指標は年1回しか更新されない**
  ・四半期点検(kessan_check.py)は売上・営業利益率・警報語を見るが、**財務の悪化は見ていない**
  ⇒ 例外で買った社を年次まで放置するのは、**警報を切ったまま乗る**のと同じ。
  **承知で越えたリスクは、承知した本人が測り続ける義務を負う。**

【何を測るか】止めている当の指標＝**財務キル nde>4** と、その裏にある金利負担・借入の動き:
  ・`nde` = (有利子負債 − 現金) / EBITDA … **TTM**（直近4四半期）で再計算
  ・`intcov` = 営業利益 / 支払利息 … TTM（歴史の実測では左尾を分けるのは残高倍率ではなく金利負担）
  ・**有利子負債の前四半期比** … 新規借入の検出（LOARはH1 2026に買収$250Mを新規借入$240Mで賄った）
  ・**自己資本の符号** … TDGは債務超過（別枠85はΩの線を免除するのでこのキルは通過を妨げない）

【⚠ 実装上の必須の検問（MKSIで実際に踏んだ）】`LongTermDebt` だけを読むと、
  **流動区分への振替を「返済」と誤読する**——実測 MKSI は LongTermDebt 4,150→2,544（−38.7%）に
  見えるが同時に ShortTermBorrowings が 51→1,399 で、総額は −6% でしかない（転換社債が
  実質転換可能になったための振替）。**必ず長期＋短期を足す。**

対象は `todo_list.json` の `gate_exception_*` 項目が持つ `tickers` から採る（固定リストにしない
——例外が増減したら自動で追随する）。**表示専用・判定には一切使わない**（売りは S1/S2/S3 のみ）。

使い方: python3 night/watch_exceptions.py [--json]
出力: out/exception_watch.json
"""
import glob
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
UA = {'User-Agent': 'ccf-gate fortis5280@gmail.com', 'Accept-Encoding': 'gzip'}
OUT = 'out/exception_watch.json'
LINE = 4.0                      # 財務キルの線（門の規約と同じ。ここで新しい定数を作らない）

OP = ["OperatingIncomeLoss"]
DEBT_LT = ["LongTermDebtNoncurrent", "LongTermDebt", "DebtAndCapitalLeaseObligations",
           "LongTermDebtAndCapitalLeaseObligations"]
DEBT_C = ["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings",
          "LongTermDebtAndCapitalLeaseObligationsCurrent"]
CASH = ["CashAndCashEquivalentsAtCarryingValue"]
DEP = ["DepreciationDepletionAndAmortization", "Depreciation"]
AMO = ["AmortizationOfIntangibleAssets"]
# ⚠TDGで実測: 上の3本はどれも無く、同社は `InterestExpenseNonoperating` と
#   `InterestIncomeExpenseNet` で報告していた（初版はここを取りこぼして「未取得」を出した）。
#   ⚠さらに **同じ四半期で符号が割れる**——2025-12-27 は Nonoperating が +475 なのに
#   IncomeExpenseNet は **−475**。素朴に合計すると TTM が 1,870 → 920 と**2倍ずれ**、
#   intcov が 2.40 → 4.88 という**もっともらしい誤値**になる。
#   → 費用として扱う系列に**負の四半期が混じったら、その候補は使わず次へ**倒す（下の ttm の sign="expense"）。
INT = ["InterestExpense", "InterestExpenseDebt", "InterestAndDebtExpense",
       "InterestExpenseNonoperating", "InterestIncomeExpenseNet"]
EQ = ["StockholdersEquity"]


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


def inst(F, tags):
    """残高（期末時点）の系列 {end日付: 値}。10-K/10-Q の両方から採る。
    ⚠**初版は「最初に値が取れた候補タグで break」していて、実測 TDG が 2021-01-02・
    MKSI が 2023-12-31 という古い残高を掴んだ**（先頭候補 LongTermDebtNoncurrent が
    数年前に報告を止めていたため）。そのまま今日のTTM EBITDAで割ると
    「基準の違う二つを割る」型そのもので、TDG の nde が 5.88 → **2.87** と出て
    『✓線の下』という**危険な誤結論**になった。
    → **候補は代替**なので、日付ごとに優先順が最上位の候補を採る（採取器 series() と同じ作法）。"""
    per = []
    for tg in tags:
        js = (F.get('us-gaap') or {}).get(tg)
        if not js:
            continue
        cur, best = {}, {}
        for un, arr in (js.get('units') or {}).items():
            if un != 'USD':
                continue
            for x in arr:
                if x.get('start') or not x.get('end'):
                    continue
                if not str(x.get('form', '')).startswith(('10-K', '10-Q', '20-F')):
                    continue
                e, fd = x['end'], x.get('filed', '')
                if e not in best or fd > best[e]:
                    best[e], cur[e] = fd, x['val']
        if cur:
            per.append(cur)
    out = {}
    for cur in per:                       # 優先順の低いものから入れ、上位で上書き
        pass
    for cur in reversed(per):
        out.update(cur)
    return out


def debt_total(F):
    """**長期＋短期を必ず足す**（MKSIで踏んだ「流動区分への振替を返済と誤読する」罠）"""
    lt, cu = inst(F, DEBT_LT), inst(F, DEBT_C)
    if not lt:
        return {}, {}, {}
    tot = {e: lt[e] + (cu.get(e) or 0) for e in lt}
    return tot, lt, cu


def _d(s):
    return (int(s[:4]) * 372 + int(s[5:7]) * 31 + int(s[8:10])) if s else None


def ttm(F, tags, sign=None):
    """直近4四半期の合計（フロー）。四半期が揃わなければ None。
    sign='expense' のとき、直近4本に**負の値が混じる候補は採らず次の候補へ倒す**
    （TDGで実測した符号割れ対策——素朴に合計すると intcov が2倍ずれる）。"""
    q = []
    for tg in tags:
        js = (F.get('us-gaap') or {}).get(tg)
        if not js:
            continue
        seen = {}
        for un, arr in (js.get('units') or {}).items():
            if un != 'USD':
                continue
            for x in arr:
                s, e, fd = x.get('start'), x.get('end'), x.get('filed', '')
                if not s or not e:
                    continue
                m = (int(e[:4]) * 12 + int(e[5:7])) - (int(s[:4]) * 12 + int(s[5:7]))
                if m < 2 or m > 4:          # 四半期だけ（年次・半期は使わない）
                    continue
                if e not in seen or fd > seen[e][0]:
                    seen[e] = (fd, x['val'])
        if seen:
            cand = sorted(seen.items())
            if len(cand) >= 4:
                l4 = cand[-4:]
                if sign == 'expense' and any(v < 0 for _, (_, v) in l4):
                    continue          # 符号が割れている候補は使わない
                q = cand
                break
    if len(q) < 4:
        return None, None
    last4 = q[-4:]
    return sum(v for _, (_, v) in last4), last4[-1][0]


def main():
    td = json.load(open('todo_list.json', encoding='utf-8'))
    targets = []
    for it in td.get('items', []):
        if str(it.get('id', '')).startswith('gate_exception') and not it.get('done'):
            for t in (it.get('tickers') or []):
                if t not in [x[0] for x in targets]:
                    targets.append((t, it.get('id'), it.get('title', '')))
    if not targets:
        print('■ 門外例外は登録されていない（todo_list.json の gate_exception_* に tickers を持たせる）')
        return 0

    tk = http("https://www.sec.gov/files/company_tickers.json")
    T2C = {}
    for r in json.loads(tk).values():
        T2C.setdefault(str(r['ticker']).upper(), int(r['cik_str']))

    packs = {}
    for p in sorted(glob.glob('out/*_gate_pack.json')):
        t = os.path.basename(p).split('_gate_pack')[0]
        x = json.load(open(p, encoding='utf-8'))
        packs[t] = (x.get('data') or x)

    rows = []
    for t, eid, title in targets:
        d = packs.get(t) or {}
        rec = dict(t=t, exception=eid, pack_nde=d.get('nde'), pack_eq=d.get('eq'),
                   pack_rdate=((d.get('_meta') or {}).get('reportDate')), nulls={})
        cik = T2C.get(t.upper())
        if not cik:
            rec['nulls']['all'] = 'SECのティッカー表にCIKが無い（日本株など）＝この経路では見張れない'
            rows.append(rec)
            continue
        j = http(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json')
        time.sleep(0.15)
        if not j:
            rec['nulls']['all'] = 'companyfacts の取得に失敗'
            rows.append(rec)
            continue
        F = json.loads(j).get('facts') or {}
        tot, lt, cu = debt_total(F)
        cash = inst(F, CASH)
        eq = inst(F, EQ)
        op, opq = ttm(F, OP)
        dep, _ = ttm(F, DEP)
        amo, _ = ttm(F, AMO)
        ie, _ = ttm(F, INT, sign='expense')
        if tot:
            ends = sorted(tot)
            e0 = ends[-1]
            rec['asof'] = e0
            rec['debt'] = tot[e0]
            rec['debt_lt'] = lt.get(e0)
            rec['debt_cur'] = cu.get(e0)
            if len(ends) >= 2:
                p0 = ends[-2]
                rec['debt_prev'] = tot[p0]
                rec['debt_prev_end'] = p0
                rec['debt_chg'] = tot[e0] / tot[p0] - 1 if tot[p0] else None
            rec['cash'] = cash.get(e0)
            rec['equity'] = eq.get(e0)
        # ⚠**残高の日付とTTMの終わりが揃っているか**を必ず検問する（揃わないなら算出しない）。
        #   これを置かないと「古い負債 ÷ 今日のEBITDA」という基準の違う二つの割り算になる。
        if op is not None and rec.get('asof') and opq and abs(_d(rec['asof']) - _d(opq)) > 100:
            rec['nulls']['nde_ttm'] = (f"残高の日付({rec['asof']})とTTMの終わり({opq})が揃わない"
                                       "＝基準の違う二つを割ることになるので算出しない（ルール7）")
            op = None
        if op is not None:
            ebitda = op + (dep or 0) + (amo or 0)
            rec['op_ttm'] = op
            rec['ebitda_ttm'] = ebitda
            rec['ttm_end'] = opq
            if rec.get('debt') is not None and rec.get('cash') is not None and ebitda > 0:
                rec['nde_ttm'] = (rec['debt'] - rec['cash']) / ebitda
            if ie and ie > 0:
                rec['intcov_ttm'] = op / ie
            elif ie == 0:
                rec['nulls']['intcov_ttm'] = '支払利息が0で報告（∞のもっともらしい代値を作らない）'
            else:
                rec['nulls']['intcov_ttm'] = ('支払利息の四半期タグが4本そろわない。'
                    '⚠**自己資本マイナス＋高レバの社ではこれが最も見たい数字**なので、'
                    '原本(10-Q損益計算書)から手で確認すること')
        else:
            rec['nulls']['nde_ttm'] = '四半期が4本そろわない（提出体裁により TTM を組めない）'

        # 判定——**線に近づいたか離れたか**。売買の判定には使わない（表示と気づきのため）
        n, pn = rec.get('nde_ttm'), rec.get('pack_nde')
        if n is None:
            rec['verdict'] = '測定不能'
        elif n <= LINE:
            rec['verdict'] = '✓線の下（次の年次報告で門が自力で取り込む見込み）'
        elif pn is not None and n > pn + 0.15:
            rec['verdict'] = '⚠悪化（線からさらに離れた）'
        elif pn is not None and n < pn - 0.15:
            rec['verdict'] = '△改善（まだ線の上）'
        else:
            rec['verdict'] = '—横ばい（線の上）'
        # ★2026-08-18 の是正（ユーザーの問い「かなり危ない状況なのでは？」で発覚）——
        #   旧実装は債務超過を **verdict の後ろへ足すだけ** だったので、VRSK が
        #   『✓線の下（次の年次報告で門が自力で取り込む見込み）／債務超過』と表示されていた。
        #   **この二つは正反対を指している**——nde は線の下だが、**債務超過は門のキルそのもの**
        #   （index.html:1919 `eq==='neg' → kills.push('債務超過')`／同 3081 `S1.push('債務超過に転落')`）。
        #   ＝次の年次報告が持ってくるのは「取り込み」ではなく **キルと売却シグナル** である。
        #   実測(2026-08-18・影の計測): VRSK の eq を neg にすると **Ω81.3→59.6・キル1・出口 hold→s1**。
        #   台帳の eq=neg は13社あり、**13社すべて Ω≤52・出口=s1**（ORLY/BKNG/AZO/FICO/MSCI…）。
        #   **甘い側へ静かに壊れる**種類なので、✓を上書きして先頭に出す。表示専用・判定には不使用。
        if rec.get('equity') is not None and rec['equity'] < 0:
            if str(rec.get('pack_eq') or '') == 'pos':
                rec['verdict'] = ('⚠**債務超過（パックはまだ pos）＝次の年次報告でキルと出口s1が来る**'
                                  + '／nde: ' + rec['verdict'])
            else:
                rec['verdict'] += '／債務超過（パックに反映ずみ）'
        if rec.get('debt_chg') is not None and rec['debt_chg'] > 0.10:
            rec['verdict'] += f"／⚠新規借入 前四半期比 +{rec['debt_chg']*100:.0f}%"
        rows.append(rec)

    print(f'■ 門外例外の四半期監視　対象 {len(rows)}社　線 nde>{LINE}')
    print(f"  {'':<6}{'四半期':<12}{'nde(年次)':>10}{'nde(TTM)':>10}{'intcov':>9}"
          f"{'負債(百万$)':>12}{'前Q比':>8}  判定")
    DASH = chr(8212)
    for r in rows:
        f = lambda v, w, p=2: (f'{v:>{w}.{p}f}' if isinstance(v, (int, float)) else f'{DASH:>{w}}')
        chg = (f"{r['debt_chg']*100:+.1f}%" if r.get('debt_chg') is not None else DASH)
        print(f"  {r['t']:<6}{str(r.get('asof') or DASH):<12}{f(r.get('pack_nde'),10)}"
              f"{f(r.get('nde_ttm'),10)}{f(r.get('intcov_ttm'),9)}"
              f"{(r['debt']/1e6 if r.get('debt') else 0):>12,.0f}{chg:>8}"
              f"  {r.get('verdict','')}")
        for k, v in (r.get('nulls') or {}).items():
            print(f"      ⚠ {k} 未取得: {v}")
    json.dump({'generated': time.strftime('%Y-%m-%d'), 'asof': time.strftime('%Y-%m-%d'),
               'line': LINE, 'n': len(rows),
               'note': '門外例外で買った社を、門が止めている当の指標(nde)で四半期ごとに見張る。'
                       '表示専用・判定には一切使わない（売りは S1/S2/S3 のみ）。'
                       'nde は長期＋短期を必ず足す（流動区分への振替を返済と誤読しないため）',
               'rows': rows}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\n→ {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
