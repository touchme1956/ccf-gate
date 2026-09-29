#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/gate_add_facts.py — 門へ入れる候補の検定・段1（特徴だけ・リターンは見ない）（2026-09-29新設）

事前登録: out/gate_add_prereg.json（コミット 5b17fb3a・書き換えない）。
問い: 3セッションで効いた銘柄側の特徴（H1 cop_at・H2 nsi・負の対照 accr）を、門が審査する銘柄に
      近い母集団（門式 ROIC ≥ 15% の米国 us-gaap 10-K 提出社）で一度だけ検定する。その段1＝特徴の採取。

★この段ではリターンと特徴の関係を一切計算しない（事前登録を汚さない）。
  価格は『起点の月に価格があるか』と時価総額のためだけに読む。

■ 母集団（事前登録 data.universe）
  今日の SEC ティッカー表の社 ∩ companyfacts に事実がある ∩ 起点までに出た最新の年次報告が 10-K（us-gaap）
  ∩ 金融を除く（SIC 6000-6999）∩ 起点の月に価格がある（月次リターンが作れる＝前月末と起点の月の足がある）。
  20-F・40-F（IFRS 等）の社は検定の外。

■ 締切（事前登録 windows.features_cut）
  各窓の起点の日付で companyfacts を filed ≤ 起点 で切る（night/omega_retro_collect.cut をそのまま使う）。
  使う会計年度＝起点までに提出された年次報告のうち期末が最新のもの（hachimon_fetch._fy_model の提出ごとの期末）。

■ 特徴（事前登録 data.*_definition）
  roic_med5 : 門の採取器 hachimon_fetch.build_numbers を切った facts に当てた roic（through-cycle＝直近最大5年の
              roic 系列〔_tcSeries〕の中央値・3年以上のときだけ。IC 縮退ガード・税の欠測・年検問は門と同じ）。
              1〜2年しか無い社は門は単年値を出すが、事前登録は『3年以上』なので欠測にする。
  cop_at    : 現金ベースの営業利益 ÷ 総資産（Ball et al. 2016 の XBRL 版）。式とタグの族は eknzbh の
              night/mw_sec_replication.py の year_features（コミット d0e2d09a）と同じ:
                OP  = 営業利益（無ければ税引前利益＋利払い）+ 減価償却 + 研究開発費
                cop = OP − Δ売掛金 − Δ在庫 − Δ前払 + Δ前受収益 + Δ(買掛金＋未払費用)〔合算タグ優先・無ければ個別の和〕
                ÷ 当期末の総資産。(−1, 2) の外は欠測。営業利益か減価償却が無い社は欠測。
              ・cop_at（主）   : 増減の行が無いときは三値読み＝night/retro_features2.flow3 の規約
                                 （その年ラベルに触れる報告が〔四半期を含め〕ある＝欠測／無い＝活動なし0）。
              ・cop_at_mw（副）: mw の定義そのまま（増減の行・研究開発費が無ければ0）。外部の証拠を作った定義。
              ・cop_at_strict（報告のみ・事後の感度）: 事前登録の括弧内の言い換え『その年に行が無いが他の年には
                                 報告している＝欠測』（retro_features2.tag_seen 型）を増減の行と研究開発費に当てた版。
  nsi       : log(同じ10-K の基本加重平均株数の当期 ÷ 前期)（比較の列は分割を遡って調整済み）。範囲 (−2, 2) の外は欠測。
  accr      : 門の採取器の accr（(純利益 − 営業CF) ÷ 総資産）。build_numbers の値（%）を小数に直しただけ。

■ 価格（時価総額と『価格があるか』だけ）
  月次の系列は out/retro_monthly_2013_2018.json＋retro_monthly_2018_2026.json（adjclose）を優先し、
  無い社（またはその窓の起点の月のリターンが作れない社）は out/_nx_cache の Yahoo 月足（nx_common.yahoo と同じ
  キャッシュ名 yh_{T}_1mo.json）。時価総額＝起点の前月末の終値（Yahoo の close は後の株式分割で遡って調整
  されているので、起点より後の分割の比を掛けて当時の株価へ戻す）× 起点までに提出された表紙の発行済株数。

使い方:
  python3 night/gate_add_facts.py            # 全段（facts → SIC → 価格 → 組み立て）
  python3 night/gate_add_facts.py --only MSFT,ADBE,CW,LRCX   # 数社だけ（出力は .partial.json）
  python3 night/gate_add_facts.py --stage assemble           # キャッシュから組み立て直すだけ
出力: out/gate_add_facts.json
一時: {SCRATCH}/gate_add_*（companyfacts の1周の結果・SIC・ティッカー表）
"""
import argparse
import datetime
import gzip
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from multiprocessing import Pool
from statistics import median

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "night"))
os.chdir(BASE)

import hachimon_fetch as H  # noqa: E402  ——門の採取器そのもの（HDRS も）
from omega_retro_collect import cut  # noqa: E402  ——filed<=締切で切る
from retro_features2 import flow3, flow_maps, tag_seen  # noqa: E402  ——三値読みの作法

OUT = os.path.join(BASE, "out")
ZIP = os.path.join(BASE, "companyfacts.zip")
NXC = os.path.join(OUT, "_nx_cache")
SCRATCH = os.environ.get("GATE_ADD_SCRATCH") or os.path.join(
    "/tmp/claude-0/-home-user-ccf-gate/735bb0d1-4200-5bb3-8ad5-668cb4d411a0/scratchpad")
PREREG = os.path.join(OUT, "gate_add_prereg.json")

# 事前登録 windows: 主3窓＋2013（報告のみ）
WINDOWS = {"2013": "2013-07-01", "2016": "2016-07-01", "2019": "2019-07-01", "2022": "2022-07-01"}
MAIN_WINDOWS = ["2016", "2019", "2022"]

# ───────────── eknzbh night/mw_sec_replication.py（コミット d0e2d09a）の year_features と同じタグの族 ─────────────
# ⚠ 写し。元の定義を変えたらここも合わせること（check_mw_tags() が元のファイルと突き合わせる）
MW_COMMIT = "d0e2d09a"
KEEP_FORMS = ('10-K', '10-K/A', '10-KT', '10-KT/A', '10-K405')
INSTANT = {'Assets', 'StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'}
REV_SUB = ['Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax',
           'RevenueFromContractWithCustomerIncludingAssessedTax', 'SalesRevenueNet']
DA_SUB = ['DepreciationDepletionAndAmortization', 'DepreciationAndAmortization', 'DepreciationAmortizationAndAccretionNet']
PRETAX_SUB = ['IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest',
              'IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments']
RD_SUB = ['ResearchAndDevelopmentExpense', 'ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost']
INT_SUB = ['InterestExpense', 'InterestExpenseDebt', 'InterestAndDebtExpense', 'InterestExpenseNonoperating']
AR_SUB = ['IncreaseDecreaseInAccountsReceivable', 'IncreaseDecreaseInReceivables', 'IncreaseDecreaseInAccountsAndNotesReceivable']
INV_TAG = 'IncreaseDecreaseInInventories'
PP_SUB = ['IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets', 'IncreaseDecreaseInPrepaidExpense',
          'IncreaseDecreaseInOtherCurrentAssets']
DR_SUB = ['IncreaseDecreaseInContractWithCustomerLiability', 'IncreaseDecreaseInDeferredRevenue']
AP_SUB = ['IncreaseDecreaseInAccountsPayable', 'IncreaseDecreaseInAccountsPayableTrade']
ACC_SUB = ['IncreaseDecreaseInAccruedLiabilities', 'IncreaseDecreaseInOtherCurrentLiabilities']
APACC_TAG = 'IncreaseDecreaseInAccountsPayableAndAccruedLiabilities'
BOUNDS = {'cop_at': (-1.0, 2.0), 'nsi': (-2.0, 2.0)}
# 研究開発費の変種（ADBE がこれだけを使う・retro_features2.RND が 2026-08-05 に是正した偽0）。
#   mw の RD_SUB には無い＝mw の定義（副）では ADBE の研究開発費が0になる。主と strict には足す（記録つき）
RD_SOFTWARE = 'ResearchAndDevelopmentExpenseSoftwareExcludingAcquiredInProcessCost'
RD_MAIN = RD_SUB + [RD_SOFTWARE]

SEMI_SIC = {'3559', '3674', '3672', '3675', '3676', '3677', '3678', '3679', '3827', '3670'}  # combo_spy.semi_set の規則をSICへ


# ───────────────────────── 小道具 ─────────────────────────
def _d(s):
    return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def ym(d):
    return int(d[:4]) * 100 + int(d[5:7])


def ym_add(k, n):
    y, m = divmod(k // 100 * 12 + k % 100 - 1 + n, 12)
    return y * 100 + m + 1


def r6(x):
    return None if x is None else round(x, 6)


# ───────────────────────── mw の読み方（10-K の様式・約1年の期間・期末±3日） ─────────────────────────
class MW:
    """mw の _one()＋year_features の pick/first を、切った facts の上で再現する"""

    def __init__(self, fc):
        self.g = (fc.get("facts") or {}).get("us-gaap") or {}
        self._rows = {}

    def rows(self, tag):
        if tag in self._rows:
            return self._rows[tag]
        u = (self.g.get(tag) or {}).get("units") or {}
        rows = u.get("shares" if tag.startswith("WeightedAverage") else "USD") or []
        rr = []
        for r in rows:
            if r.get("form") not in KEEP_FORMS or _num(r.get("val")) is None or not r.get("end"):
                continue
            if tag not in INSTANT:
                if not r.get("start"):
                    continue
                try:
                    dd = (_d(r["end"]) - _d(r["start"])).days
                except Exception:
                    continue
                if not (330 <= dd <= 400):
                    continue
            rr.append((r["end"], float(r["val"]), r.get("filed") or "", 0 if r["form"] in ('10-K', '10-KT', '10-K405') else 1,
                       r.get("accn")))
        self._rows[tag] = rr
        return rr

    def pick(self, tag, E):
        dE = _d(E)
        rows = [r for r in self.rows(tag) if abs((_d(r[0]) - dE).days) <= 3]
        if not rows:
            return None
        return max(rows, key=lambda r: (r[2], r[3]))[1]

    def first(self, tags, E):
        for t in tags:
            v = self.pick(t, E)
            if v is not None:
                return v
        return None


def inst10k(g, tag, date):
    """時点の値（10-K の様式・期末±10日・最新の提出）"""
    dt = _d(date)
    best = None
    for r in ((g.get(tag) or {}).get("units") or {}).get("USD") or []:
        if r.get("start") or r.get("form") not in KEEP_FORMS or _num(r.get("val")) is None or not r.get("end"):
            continue
        if abs((_d(r["end"]) - dt).days) > 10:
            continue
        if best is None or (r.get("filed") or "") > best[1]:
            best = (float(r["val"]), r.get("filed") or "")
    return best[0] if best else None


def state3(mw, tags, E, deadline):
    """主の三値読み。値は mw の pick（10-K・期末±3日）。無ければ flow3 の規約で欠測と0を分ける:
    同じ年ラベルに触れる報告（四半期を含む）がある＝('miss')／無い＝('zero', 0)。
    flow3 が年次の値を持っているのに mw の pick に掛からない（10-K 以外の様式・期末が±3日の外）ときは、
    その値の期末が E±10日なら使い、そうでなければ欠測（別の期の値を当期と読まない）"""
    v = mw.first(tags, E)
    if v is not None:
        return ('val', v)
    y = int(E[:4])
    st = flow3(mw.g, tags, deadline)(y)
    if st[0] == 'val':
        _get, maps = flow_maps(mw.g, tags, deadline)
        for m in maps:
            if y in m:
                if abs((_d(m[y][2]) - _d(E)).days) <= 10:
                    return ('val', float(m[y][0]))
                return ('miss', None)
        return ('miss', None)
    if st[0] == 'miss':
        return ('miss', None)
    return ('zero', 0.0)


def state_seen(mw, tags, E, deadline):
    """事前登録の括弧内の言い換え（報告のみ）: 値が無く、期限内のどこかでその行を報告している＝欠測／一度も無い＝0"""
    v = mw.first(tags, E)
    if v is not None:
        return ('val', v)
    if tag_seen(mw.g, tags, deadline):
        return ('miss', None)
    return ('zero', 0.0)


def cop_features(fc, E, deadline):
    """cop_at の3つの版と、中身（監査用）"""
    mw = MW(fc)
    out = {}
    A = mw.pick('Assets', E)
    it = mw.first(INT_SUB, E)
    oi = mw.pick('OperatingIncomeLoss', E)
    oi_pretax = False
    if oi is None:
        pt = mw.first(PRETAX_SUB, E)
        if pt is not None:
            oi = pt + (it or 0.0)
            oi_pretax = True
    da = mw.first(DA_SUB, E)
    if da is None:
        dep = mw.pick('Depreciation', E)
        if dep is not None:
            da = dep + (mw.pick('AmortizationOfIntangibleAssets', E) or 0.0)
    rd_mw = mw.first(RD_SUB, E)
    rd_main = mw.first(RD_MAIN, E)
    parts = {"assets": A, "oi": oi, "oi_from_pretax": oi_pretax, "da": da, "rd_mw": rd_mw, "rd_main": rd_main}
    miss = []
    if A is None or A <= 0:
        miss.append("総資産なし")
    if oi is None:
        miss.append("営業利益なし（税引前利益も無い）")
    if da is None:
        miss.append("減価償却なし")
    if miss:
        out["cop_why"] = "・".join(miss)
        out["cop_parts"] = parts
        return out

    # ── 副: mw の定義（増減の行・研究開発費が無ければ0）
    dar = mw.first(AR_SUB, E)
    dinv = mw.pick(INV_TAG, E)
    dpp = mw.first(PP_SUB, E)
    ddr = mw.first(DR_SUB, E)
    apacc = mw.pick(APACC_TAG, E)
    if apacc is None:
        apacc = (mw.first(AP_SUB, E) or 0.0) + (mw.first(ACC_SUB, E) or 0.0)
    op_mw = oi + da + (rd_mw or 0.0)
    cop_mw = op_mw - (dar or 0.0) - (dinv or 0.0) - (dpp or 0.0) + (ddr or 0.0) + apacc
    v = cop_mw / A
    lo, hi = BOUNDS['cop_at']
    if lo <= v <= hi:
        out["cop_at_mw"] = v
    else:
        out["cop_why_mw"] = f"範囲外 {v:.3f}"

    # ── 前受収益の総額表示の是正（2026-09-29・段1の点検で見つけた読み違い）
    #   MSFT（FY2012・FY2015）と InterDigital（FY2015）は、キャッシュフロー計算書で前受収益の『繰り延べ（総額）』と
    #   『取り崩し（RecognitionOfDeferredRevenue）』を別の行に出しており、IncreaseDecreaseInDeferredRevenue に
    #   **総額の繰り延べ**（MSFT FY2015: 450.72億$）が入っている。mw の族は取り崩しの行を持たないので、
    #   増減の行として総額を足してしまう（MSFT の cop_at が 0.20 → 0.46 に膨らむ）。
    #   → 同じ10-K に RecognitionOfDeferredRevenue（キャッシュフロー計算書の行）があるときだけ、
    #     貸借対照表の前受収益の前期末→当期末の差（恒等式）で裁く: 差し引いた純額のほうが差に近ければ純額を使う。
    #     貸借対照表の残高が取れないときは直さず印（dr_gross_suspect）だけ付ける（推測で直さない）。
    #   ⚠ ContractWithCustomerLiabilityRevenueRecognized は注記の数字（期首残高のうち売上にした額）で、
    #     キャッシュフロー計算書の行ではない＝多くの社が純額の増減と並べて開示している（LRCX・AMAT・TJX…）ので使わない
    def dr_bal(d):
        for tags in (['DeferredRevenue'], ['ContractWithCustomerLiability'],
                     ['DeferredRevenueCurrent', 'DeferredRevenueNoncurrent'],
                     ['ContractWithCustomerLiabilityCurrent', 'ContractWithCustomerLiabilityNoncurrent']):
            vals = [inst10k(mw.g, t, d) for t in tags]
            if vals[0] is not None:
                return sum(v for v in vals if v is not None)
        return None

    dr_fix = None
    ddr_raw = mw.first(DR_SUB, E)
    rec_r = mw.pick('RecognitionOfDeferredRevenue', E)
    if ddr_raw is not None and rec_r is not None and rec_r != 0:
        net = ddr_raw - abs(rec_r)
        b1 = dr_bal(E)
        b0 = dr_bal((_d(E) - datetime.timedelta(days=365)).isoformat())
        info = {"gross": ddr_raw, "recognized": rec_r, "net": net, "bs_end": b1, "bs_prev": b0}
        if b1 is not None and b0 is not None:
            dbs = b1 - b0
            info["bs_change"] = dbs
            if abs(net - dbs) < abs(ddr_raw - dbs):
                dr_fix = net
                info["applied"] = True
            else:
                info["applied"] = False
        else:
            info["applied"] = False
            info["why"] = "貸借対照表の前受収益が取れず恒等式で裁けない＝直さない"
        out["dr_gross"] = info

    # ── 主 と strict: 増減の行を三値で読む
    def assemble(st_fn, rd_rule, fixes=True):
        s = {"ar": st_fn(mw, AR_SUB, E, deadline), "inv": st_fn(mw, [INV_TAG], E, deadline),
             "pp": st_fn(mw, PP_SUB, E, deadline), "dr": st_fn(mw, DR_SUB, E, deadline)}
        if fixes and dr_fix is not None and s["dr"][0] == 'val':
            s["dr"] = ('val', dr_fix)
        sc = st_fn(mw, [APACC_TAG], E, deadline)
        if sc[0] == 'val':
            s["apacc"] = sc
        else:
            sa, sb = st_fn(mw, AP_SUB, E, deadline), st_fn(mw, ACC_SUB, E, deadline)
            if 'miss' in (sa[0], sb[0]):
                s["apacc"] = ('miss', None)
            elif sa[0] == 'val' or sb[0] == 'val':
                s["apacc"] = ('val', sa[1] + sb[1])        # 合算タグが無い年だけ個別の和（二重に足さない）
            elif sc[0] == 'miss':
                s["apacc"] = ('miss', None)
            else:
                s["apacc"] = ('zero', 0.0)
        rdv = rd_main if fixes else rd_mw                   # 是正前＝mw の族だけ（ADBE 等の変種タグを読まない）
        if rd_rule == "main":
            s["rd"] = ('val', rdv) if rdv is not None else ('zero', 0.0)   # 研究開発費は mw どおり『無ければ0』
        else:
            if rdv is not None:
                s["rd"] = ('val', rdv)
            elif tag_seen(mw.g, RD_MAIN, deadline):
                s["rd"] = ('miss', None)
            else:
                s["rd"] = ('zero', 0.0)
        bad = [k for k, x in s.items() if x[0] == 'miss']
        if bad:
            return None, s, "欠測の行: " + ",".join(bad)
        cop = oi + da + s["rd"][1] - s["ar"][1] - s["inv"][1] - s["pp"][1] + s["dr"][1] + s["apacc"][1]
        v = cop / A
        if not (lo <= v <= hi):
            return None, s, f"範囲外 {v:.3f}"
        return v, s, None

    v, s, why = assemble(state3, "main")
    if v is not None:
        out["cop_at"] = v
    else:
        out["cop_why"] = why
    out["cop_states"] = {k: x[0] for k, x in s.items()}
    out["cop_vals"] = {k: x[1] for k, x in s.items()}          # 主の各行の値（欠測は None）＝点検用
    v0, _s0, _w0 = assemble(state3, "main", fixes=False)      # 是正（研究開発費の変種・前受収益の総額）の前の主
    if v0 is not None:
        out["cop_at_prefix"] = v0
    out["cop_fixed"] = [k for k, on in (("rd_software_tag", rd_mw is None and rd_main is not None),
                                        ("dr_gross_to_net", dr_fix is not None)) if on]
    # 点検用（採点・検定には使わない）: 族の外のタグで出ている増減の行（総資産の0.5%以上）。
    #   実例 LRCX FY2021 の『Accrued expenses and other liabilities +409.3百万$』は
    #   IncreaseDecreaseInAccruedLiabilitiesAndOtherOperatingLiabilities で、mw の族に無い＝主も副も0と読む
    fam = set(AR_SUB + [INV_TAG] + PP_SUB + DR_SUB + AP_SUB + ACC_SUB + [APACC_TAG])
    outside = {}
    for tg in mw.g:
        if tg.startswith("IncreaseDecrease") and tg not in fam:
            x = mw.pick(tg, E)
            if x is not None and abs(x) >= 0.005 * A:
                outside[tg] = round(x)
    if outside:
        out["cop_outside"] = outside
    v2, s2, why2 = assemble(state_seen, "strict")
    if v2 is not None:
        out["cop_at_strict"] = v2
    else:
        out["cop_why_strict"] = why2
    out["cop_parts"] = parts
    return out


def nsi_feature(fc, E):
    """同じ10-K（同じ accn）の基本加重平均株数の当期 ÷ 前期 の log（mw と同じ。mw は同じ提出日＋同じ訂正の印で
    同じ提出を見分けていたが、ここは accn で見分ける）"""
    mw = MW(fc)
    rows = mw.rows('WeightedAverageNumberOfSharesOutstandingBasic')
    dE = _d(E)
    cur = [r for r in rows if abs((_d(r[0]) - dE).days) <= 3]
    if not cur:
        return None, "当期の基本加重平均株数なし"
    rc = max(cur, key=lambda r: (r[2], r[3]))
    prev = [r for r in rows if r[4] == rc[4] and 350 <= (dE - _d(r[0])).days <= 380]
    if not prev:
        return None, "同じ10-Kに前期の列なし"
    if rc[1] <= 0 or prev[0][1] <= 0:
        return None, "株数が0以下"
    v = math.log(rc[1] / prev[0][1])
    lo, hi = BOUNDS['nsi']
    if not (lo <= v <= hi):
        return None, f"範囲外 {v:.3f}"
    return v, None


def latest_annual(fc, deadline):
    """門の年の付け方（_fy_model）で、起点までに出た年次報告のうち期末が最新の提出を返す"""
    fym = H._fy_model(fc)
    acc = fym.get("acc") or {}
    if not acc:
        return None
    E = max(v[1] for v in acc.values())
    accns = [a for a, v in acc.items() if v[1] == E]
    label = acc[accns[0]][0]
    forms, filed, nss = set(), [], set()
    for ns in ("us-gaap", "ifrs-full"):
        for node in ((fc.get("facts") or {}).get(ns) or {}).values():
            for u, rows in (node.get("units") or {}).items():
                for r in rows:
                    if r.get("accn") in accns:
                        forms.add(r.get("form"))
                        if r.get("filed"):
                            filed.append(r["filed"])
                        nss.add(ns)
    return {"E": E.isoformat(), "label": label, "accns": accns, "forms": sorted(f for f in forms if f),
            "filed": min(filed) if filed else None, "ns": sorted(nss)}


def shares_pit(fc, deadline):
    """時価総額の株数の候補（起点までに提出されたもの・値と日付）。決めるのは組み立て（分割の比が要るので）。
      dei   : 表紙の発行済株数（種類株は同じ提出・同じ日付の値を足す）
      bs    : 貸借対照表の CommonStockSharesOutstanding（同じく足す）
      wa    : 最新の基本加重平均株数（1つの値・足さない）
      float : 表紙の浮動株時価（EntityPublicFloat・ドル）＝候補が食い違ったときの裁定にだけ使う
    ⚠ 申告の桁の誤りが実在する: GRMN の2016年の10-Q の表紙 208,077,418,000 株（千倍）／WNC・PETS・IPAR ほかの
      加重平均株数は『千株』のまま（千分の一）。1つの出所を無条件に信じない"""
    facts = fc.get("facts") or {}

    def latest(rows, add=True):
        rows = [r for r in rows if _num(r.get("val")) is not None and r.get("end") and r.get("filed")]
        if not rows:
            return None
        r0 = max(rows, key=lambda r: (r["filed"], r["end"]))
        if not add:
            return [float(r0["val"]), r0["end"]]
        same = [r for r in rows if r.get("accn") == r0.get("accn") and r["end"] == r0["end"]]
        vals = sorted({float(r["val"]) for r in same})
        return [sum(vals), r0["end"], len(vals)]

    g = facts.get("us-gaap") or {}
    dei = facts.get("dei") or {}
    c = {}
    x = latest(((dei.get("EntityCommonStockSharesOutstanding") or {}).get("units") or {}).get("shares") or [])
    if x and x[0] > 0:
        c["dei"] = x
    x = latest(((g.get("CommonStockSharesOutstanding") or {}).get("units") or {}).get("shares") or [])
    if x and x[0] > 0:
        c["bs"] = x
    x = latest(((g.get("WeightedAverageNumberOfSharesOutstandingBasic") or {}).get("units") or {}).get("shares") or [], add=False)
    if x and x[0] > 0:
        c["wa"] = x
    x = latest(((dei.get("EntityPublicFloat") or {}).get("units") or {}).get("USD") or [], add=False)
    if x and x[0] > 0:
        c["float"] = x
    return {"sh_cands": c} if c else None


def choose_shares(cands, splits, start, px):
    """候補から株数を決める（分割を起点へ合わせてから）: 3つ以上そろえば中央値／2つなら2倍以内で表紙を優先・
    2倍超ずれたら浮動株時価に近い（株価×株数が浮動株時価の近く）ほう／1つならそれ。決められなければ None と理由"""
    def f_since(since):
        f_ = 1.0
        for dd, ratio in splits or []:
            if since < dd < start:
                f_ *= ratio
        return f_
    xs = [(k, v[0] * f_since(v[1])) for k, v in cands.items() if k in ("dei", "bs", "wa")]
    if not xs:
        return None, "株数の候補なし", None
    order = {"dei": 0, "bs": 1, "wa": 2}
    xs.sort(key=lambda kv: order[kv[0]])
    if len(xs) >= 3:
        vals = sorted(v for _, v in xs)
        med = vals[1]
        src = [k for k, v in xs if v == med][0]
        spread = max(vals) / min(vals)
        return med, f"{src}（3つの中央値" + (f"・最大/最小 {spread:.3g}倍" if spread > 2 else "") + "）", spread
    if len(xs) == 2:
        (k1, v1), (k2, v2) = xs
        r = v1 / v2
        if 0.5 <= r <= 2:
            return v1, k1, r
        fl = cands.get("float")
        if fl and px:
            best = min(xs, key=lambda kv: abs(math.log(px * kv[1] / fl[0])))
            return best[1], f"{best[0]}（{k1}と{k2}が {r:.3g}倍ずれ・浮動株時価に近いほう）", r
        return None, f"{k1}と{k2}が {r:.3g}倍ずれて裁けない", r
    return xs[0][1], xs[0][0], None


def features_window(facts, deadline):
    fc = cut(facts, deadline)
    la = latest_annual(fc, deadline)
    if la is None:
        return {"why": "起点までに年次報告なし"}
    rec = {"fy": la["label"], "fy_end": la["E"], "filed": la["filed"], "forms": la["forms"]}
    if not any(f.startswith("10-K") for f in la["forms"]):
        rec["why"] = "最新の年次報告が10-Kでない（" + ",".join(la["forms"]) + "）"
        return rec
    if "us-gaap" not in la["ns"]:
        rec["why"] = "最新の10-Kに us-gaap の事実なし"
        return rec
    rec["fy_age_days"] = (_d(deadline) - _d(la["E"])).days
    E = la["E"]
    # 門式 ROIC（門の採取器そのもの）
    try:
        ev = H.build_numbers(fc)
    except Exception as e:  # noqa
        ev = {}
        rec["roic_why"] = f"build_numbers 例外: {type(e).__name__}"
    tc = ev.get("_tcSeries") or {}
    rec["tc"] = tc
    rec["roic_n"] = ev.get("_tcYears") or len(tc)
    if ev.get("roic") is not None and (ev.get("_tcYears") or 0) >= 3:
        rec["roic_med5"] = ev["roic"]
        rec["roicg_med5"] = ev.get("roicg")
    elif "roic_why" not in rec:
        notes = [n for n in (ev.get("_note") or []) if "roic" in n]
        if tc and len(tc) < 3:
            rec["roic_why"] = f"有効な年が{len(tc)}年（3年未満）"
        elif tc:
            rec["roic_why"] = "系列が古い（門の年検問）"
        else:
            rec["roic_why"] = "系列なし（IC縮退・税/負債/無形の欠測など）"
        if notes:
            rec["roic_note"] = notes[0][:300]
    rec["tc_last"] = max(int(k) for k in tc) if tc else None
    # accr（門の値・%→小数）
    if ev.get("accr") is not None:
        rec["accr"] = round(ev["accr"] / 100.0, 6)
        evd = (ev.get("_evid") or {}).get("accr") or ""
        try:
            rec["accr_year"] = int(evd.split("機械算出 ")[1][:4])
        except Exception:
            rec["accr_year"] = None
    else:
        rec["accr_why"] = "門の採取器が accr を出さない（純利益/営業CF/総資産の欠測・年検問）"
    # cop_at
    cf = cop_features(fc, E, deadline)
    for k in ("cop_at", "cop_at_mw", "cop_at_strict", "cop_at_prefix"):
        if cf.get(k) is not None:
            rec[k] = r6(cf[k])
    for k in ("cop_why", "cop_why_mw", "cop_why_strict", "cop_states", "cop_fixed", "dr_gross", "cop_outside"):
        if k in cf:
            rec[k] = cf[k]
    if "cop_vals" in cf:
        rec["cop_vals"] = {k: (None if v is None else round(v)) for k, v in cf["cop_vals"].items()}
    p = cf.get("cop_parts") or {}
    rec["cop_parts"] = {k: (r6(v) if isinstance(v, float) else v) for k, v in p.items()}
    # nsi
    v, why = nsi_feature(fc, E)
    if v is not None:
        rec["nsi"] = r6(v)
    else:
        rec["nsi_why"] = why
    sh = shares_pit(fc, deadline)
    if sh:
        rec.update(sh)
    return rec


_Z = None


def _init():
    global _Z
    _Z = zipfile.ZipFile(ZIP)


def work(cik):
    name = f"CIK{int(cik):010d}.json"
    try:
        facts = json.loads(_Z.read(name))
    except KeyError:
        return cik, {"why": "companyfacts に無い"}
    except Exception as e:  # noqa
        return cik, {"why": f"読めない: {type(e).__name__}"}
    res = {"name": facts.get("entityName"), "w": {}}
    for w, dl in WINDOWS.items():
        try:
            res["w"][w] = features_window(facts, dl)
        except Exception as e:  # noqa
            res["w"][w] = {"why": f"例外: {type(e).__name__}: {str(e)[:120]}"}
    return cik, res


# ───────────────────────── ティッカー表・SIC ─────────────────────────
def sec_get(url):
    req = urllib.request.Request(url, headers=H.HDRS)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
    time.sleep(0.13)   # 10req/s 未満
    return b


def ticker_table():
    p = os.path.join(SCRATCH, "gate_add_company_tickers.json")
    if not os.path.exists(p) or time.time() - os.path.getmtime(p) > 3 * 86400:
        b = sec_get("https://www.sec.gov/files/company_tickers.json")
        open(p, "wb").write(b)
    T = json.load(open(p))
    ciks = {}
    for k in sorted(T, key=int):          # 表の順（SEC は時価総額の大きい順に並べている）
        v = T[k]
        ciks.setdefault(int(v["cik_str"]), []).append(v["ticker"])
    # 普通株でない記号を外す（優先株 -P/-PA…・ワラント -WT/…W・ユニット -UN/…U・権利 -RI/-RW・発行日取引 -V）。
    #   実害: EIDP（旧 DuPont・CIK 30554）は今の表に優先株 CTA-PB/CTA-PA しか無く、そのまま使うと優先株の値動きで
    #   2016年の DuPont を測ることになる。普通株の記号が1つも残らない社は『価格なし』として母集団から外れる
    out = {}
    for c, ts in ciks.items():
        keep = []
        for t in ts:
            if re.search(r"-(P[A-Z]?|WTA?|WS|UN|U|RI|RW|R|V)$", t):
                continue
            if len(t) == 5 and t[-1] in "WUR" and t[:4] in ts:
                continue   # NASDAQ の5文字目 W/U/R（ワラント・ユニット・権利）＝同じ社に4文字の普通株がある
            keep.append(t)
        out[c] = keep
    return out, datetime.datetime.utcfromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d")


def sic_map(ciks):
    """CIK→SIC。out/sic_by_cik.json・out/_sic_cache.json を先に読み、無い社だけ SEC submissions から取る"""
    p = os.path.join(SCRATCH, "gate_add_sic.json")
    S = json.load(open(p)) if os.path.exists(p) else {}
    try:
        for k, v in json.load(open(os.path.join(OUT, "sic_by_cik.json"))).items():
            S.setdefault(str(int(k)), {"sic": v, "src": "out/sic_by_cik.json"})
    except Exception:  # noqa
        pass
    try:
        for t, v in json.load(open(os.path.join(OUT, "_sic_cache.json"))).items():
            if v.get("cik") and v.get("sic"):
                S.setdefault(str(int(v["cik"])), {"sic": v["sic"], "desc": v.get("desc"), "src": "out/_sic_cache.json"})
    except Exception:  # noqa
        pass
    need = [c for c in ciks if str(c) not in S]
    print(f"■ SIC: 既知 {len(ciks) - len(need)}社・取りに行く {len(need)}社", flush=True)
    for i, c in enumerate(need, 1):
        try:
            # SIC は submissions JSON の先頭（ヘッダ部）にある＝先頭だけ読む（retro_sic と同じ作法・全文は数MBになる社がある）
            req = urllib.request.Request(f"https://data.sec.gov/submissions/CIK{int(c):010d}.json", headers=H.HDRS)
            with urllib.request.urlopen(req, timeout=60) as r:
                head = r.read(6000).decode("utf-8", "ignore")
            time.sleep(0.13)
            m1 = re.search(r'"sic"\s*:\s*"(\d*)"', head)
            m2 = re.search(r'"sicDescription"\s*:\s*"([^"]*)"', head)
            S[str(c)] = {"sic": (m1.group(1) if m1 else "") or None, "desc": m2.group(1) if m2 else None,
                         "src": "SEC submissions" + ("" if m1 else "（先頭に sic なし）")}
        except urllib.error.HTTPError as e:
            S[str(c)] = {"sic": None, "src": f"SEC submissions HTTP {e.code}"}
        except Exception as e:  # noqa
            S[str(c)] = {"sic": None, "src": f"SEC submissions 失敗 {type(e).__name__}"}
        if i % 200 == 0:
            print(f"   {i}/{len(need)}", flush=True)
            json.dump(S, open(p, "w"))
    json.dump(S, open(p, "w"))
    return S


# ───────────────────────── 価格 ─────────────────────────
def yahoo_file(t):
    return os.path.join(NXC, f'yh_{t.replace("^", "IDX_").replace("=", "_")}_1mo.json')


YAHOO_FETCHED = [0]


def yahoo_raw(t, fetch=True):
    """キャッシュ（nx_common.yahoo と同じ名前）を読む。無ければ取りに行く（404 は負のキャッシュ .404）"""
    p = yahoo_file(t)
    for neg in (p + ".404", p + ".none"):
        if os.path.exists(neg):
            return None
    if not (os.path.exists(p) and os.path.getsize(p) > 0):
        if not fetch:
            return None
        u = (f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t)}?period1=0&period2='
             f'{int(time.time())}&interval=1mo&events=div%2Csplit')
        ua = {'User-Agent': 'Mozilla/5.0 (ccf-gate research; contact via github touchme1956/ccf-gate)'}
        b, err = None, None
        for i in range(5):
            try:
                b = urllib.request.urlopen(urllib.request.Request(u, headers=ua), timeout=60).read()
                break
            except urllib.error.HTTPError as e:
                err = e
                if e.code == 404:
                    open(p + ".404", "w").write("404")
                    return None
                time.sleep(2 ** (i + 1))
            except Exception as e:  # noqa
                err = e
                time.sleep(2 ** (i + 1))
        if b is None:
            print(f"   ▲ Yahoo 取得失敗 {t}: {err}", flush=True)
            return None
        tmp = f"{p}.{os.getpid()}.tmp"
        open(tmp, "wb").write(b)
        os.replace(tmp, p)
        YAHOO_FETCHED[0] += 1
        time.sleep(0.3)
    try:
        return json.load(open(p))["chart"]["result"][0]
    except Exception:  # noqa
        return None


def yahoo_bars(r):
    """{yyyymm: (adjclose, close)} と 分割 [(日付, 比)]"""
    if not r:
        return None, []
    ts = r.get("timestamp") or []
    adj = ((r.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose")
    cl = ((r.get("indicators") or {}).get("quote") or [{}])[0].get("close")
    if not ts or adj is None or cl is None:
        return None, []
    out = {}
    for t, a, c in zip(ts, adj, cl):
        if a is None or c is None or a <= 0 or c <= 0:
            continue
        d = datetime.datetime.utcfromtimestamp(t)
        out[d.year * 100 + d.month] = (a, c)
    sp = []
    for k, v in ((r.get("events") or {}).get("splits") or {}).items():
        try:
            dd = datetime.datetime.utcfromtimestamp(int(v.get("date", k))).date()
            num, den = float(v.get("numerator") or 0), float(v.get("denominator") or 0)
            if num > 0 and den > 0:
                sp.append((dd, num / den))
        except Exception:  # noqa
            pass
    return out or None, sorted(sp)


RM = None
_YMEMO = {}   # 同じ記号の Yahoo 月足を窓ごとに読み直さない


def retro_monthly():
    global RM
    if RM is None:
        RM = {}
        for f in ("retro_monthly_2013_2018.json", "retro_monthly_2018_2026.json"):
            for t, arr in json.load(open(os.path.join(OUT, f))).items():
                d = RM.setdefault(t, {})
                for ts, v in arr:
                    if v is None or v <= 0:
                        continue
                    dt = datetime.datetime.utcfromtimestamp(ts)
                    d[dt.year * 100 + dt.month] = v
    return RM


def price_for(tickers, start, fetch=True):
    """その窓で使う価格の出所・前月末の終値（当時の株価へ戻したもの）。
    出所の優先: retro_monthly（起点の月のリターンが作れるなら）→ Yahoo 月足"""
    k1 = ym(start)
    k0 = ym_add(k1, -1)
    RMd = retro_monthly()
    rec = {}
    src = None
    for t in tickers:
        m = RMd.get(t)
        if m and k0 in m and k1 in m:
            src = ("retro_monthly", t)
            break
    ycands = []
    for t in tickers:
        for tt in dict.fromkeys([t, t.replace(".", "-")]):
            ycands.append(tt)
    ybars = None
    for t in ycands:
        if t not in _YMEMO:
            r = yahoo_raw(t, fetch=fetch)
            bars, sp = yahoo_bars(r)
            _YMEMO[t] = (bars, sp, (r or {}).get("meta") or {})
        bars, sp, _meta = _YMEMO[t]
        if bars and k0 in bars and k1 in bars:
            ybars = (t, bars, sp, _meta.get("currency"))
            break
    if src is None and ybars is not None:
        src = ("yahoo", ybars[0])
    if src is None:
        return None
    rec["price_src"], rec["price_ticker"] = src
    if ybars is not None:
        t, bars, sp, ccy = ybars
        rec["px_ticker"] = t
        rec["px_ccy"] = ccy
        a, c = bars[k0]
        after = [x for x in sp if x[0] >= _d(start)]
        f = 1.0
        for _dd, ratio in after:
            f *= ratio
        rec["px_close_adj"] = c
        rec["px_split_factor_after"] = f
        rec["px"] = c * f                       # 当時の株価（後の分割を戻した前月末の終値）
        rec["_splits"] = [(x[0].isoformat(), x[1]) for x in sp]
    return rec


# ───────────────────────── 段 ─────────────────────────
def stage_facts(ciks, only_ciks=None, procs=3):
    p = os.path.join(SCRATCH, "gate_add_facts_raw.json.gz" if not only_ciks else "gate_add_facts_raw.partial.json.gz")
    todo = sorted(only_ciks or ciks)
    t0 = time.time()
    res = {}
    with Pool(procs, initializer=_init) as pool:
        for i, (cik, r) in enumerate(pool.imap_unordered(work, todo, chunksize=8), 1):
            res[str(cik)] = r
            if i % 500 == 0:
                print(f"   facts {i}/{len(todo)} {time.time() - t0:.0f}s", flush=True)
    with gzip.open(p + ".tmp", "wt") as f:
        json.dump(res, f)
    os.replace(p + ".tmp", p)
    print(f"■ facts: {len(res)}社 {time.time() - t0:.0f}s → {p}", flush=True)
    return res


def load_raw(partial=False):
    p = os.path.join(SCRATCH, "gate_add_facts_raw.partial.json.gz" if partial else "gate_add_facts_raw.json.gz")
    with gzip.open(p, "rt") as f:
        return json.load(f)


def is_fin(sic):
    return sic is not None and sic.isdigit() and 6000 <= int(sic) <= 6999


def assemble(ciks, raw, S, partial=False, fetch=True):
    prereg_sha = None
    try:
        import hashlib
        prereg_sha = hashlib.sha256(open(PREREG, "rb").read()).hexdigest()[:16]
    except Exception:  # noqa
        pass
    rows = {w: {} for w in WINDOWS}
    counts = {w: {} for w in WINDOWS}
    reasons = {w: {} for w in WINDOWS}

    def bump(w, k, n=1):
        counts[w][k] = counts[w].get(k, 0) + n

    def why(w, k):
        reasons[w][k] = reasons[w].get(k, 0) + 1

    todo = sorted(raw, key=int)
    for i, c in enumerate(todo, 1):
        tick = ciks.get(int(c)) or []
        r = raw[c]
        common_ok = bool(tick)
        sic = (S.get(str(int(c))) or {}).get("sic")
        for w, start in WINDOWS.items():
            bump(w, "1_ticker_table_ciks")
            if "w" not in r:
                why(w, r.get("why") or "companyfacts に無い")
                continue
            bump(w, "2_in_companyfacts")
            f = r["w"].get(w) or {}
            if not any((x or "").startswith("10-K") for x in f.get("forms") or []) or "fy_age_days" not in f:
                why(w, "年次報告が10-K（us-gaap）でない／起点までに無い: " + (f.get("why") or "")[:40])
                continue
            bump(w, "3_us_gaap_10k")
            if not sic:
                why(w, "SIC 不明（金融か確かめられない）")
                continue
            if is_fin(sic):
                why(w, "金融（SIC 6000-6999）")
                continue
            bump(w, "4_non_financial")
            if not common_ok:
                why(w, "普通株の記号が無い（優先株・ワラント・ユニットだけ）")
                continue
            pr = price_for(tick, start, fetch=fetch)
            if pr is None:
                why(w, "起点の月の価格なし（前月末と起点の月の足）")
                continue
            bump(w, "5_universe_with_price")
            row = {"cik": int(c), "ticker": tick[0], "tickers": tick, "name": r.get("name"), "sic": sic,
                   "semi_3674": sic == "3674", "semi_set": sic in SEMI_SIC}
            row.update({k: v for k, v in f.items() if k not in ("forms",)})
            row["form"] = [x for x in f.get("forms") or [] if x.startswith("10-K")][0]
            row.update({k: v for k, v in pr.items() if not k.startswith("_")})
            if row.get("sh_cands") and row.get("px"):
                sh_now, src, spread = choose_shares(row["sh_cands"], pr.get("_splits"), start, row["px"])
                row["sh_src"] = src
                if spread is not None and not (0.5 <= spread <= 2):
                    row["sh_suspect"] = round(spread, 3)
                if sh_now:
                    row["sh"] = sh_now
                    row["mcap"] = row["px"] * sh_now
                else:
                    row["mcap_why"] = src
            else:
                row["mcap_why"] = "株数なし" if not row.get("sh_cands") else "終値なし"
            row["stale_10k"] = row.get("fy_age_days", 0) > 548
            rows[w][str(int(c))] = row
            if row.get("roic_med5") is not None:
                bump(w, "6_gate_roic_computable")
                if row["roic_med5"] >= 15:
                    bump(w, "7_pool_main_roic15")
                    for k in ("cop_at", "cop_at_mw", "cop_at_strict", "nsi", "accr"):
                        if row.get(k) is not None:
                            bump(w, f"8_pool15_has_{k}")
                    if row.get("mcap") is not None and row["mcap"] >= 2e9:
                        bump(w, "9_pool15_mcap2bn")
                    if row["stale_10k"]:
                        bump(w, "9_pool15_stale_10k")
                    if row["semi_3674"]:
                        bump(w, "9_pool15_sic3674")
                    if row["semi_set"]:
                        bump(w, "9_pool15_semi_set")
                if row["roic_med5"] >= 25:
                    bump(w, "7_pool_secondary_roic25")
            else:
                why(w, "（母集団内）門式ROIC 計算不能: " + (row.get("roic_why") or "")[:30])
        if i % 1000 == 0:
            print(f"   組み立て {i}/{len(todo)}（Yahoo 新規取得 {YAHOO_FETCHED[0]}）", flush=True)
    meta = {
        "generated": datetime.date.today().isoformat(),
        "prereg": "out/gate_add_prereg.json（コミット 5b17fb3a）", "prereg_sha256_16": prereg_sha,
        "stage": "段1＝特徴だけ（リターンと特徴の関係は一切計算していない）",
        "windows": WINDOWS, "main_windows": MAIN_WINDOWS, "report_only_windows": ["2013"],
        "companyfacts": {"file": "companyfacts.zip（コミットしない）",
                         "bytes": os.path.getsize(ZIP),
                         "mtime": datetime.datetime.utcfromtimestamp(os.path.getmtime(ZIP)).strftime("%Y-%m-%d")},
        "mw_source": f"eknzbh night/mw_sec_replication.py @ {MW_COMMIT}（year_features のタグの族と式）",
        "definitions": {
            "roic_med5": "hachimon_fetch.build_numbers(cut(facts, 起点)) の roic（_tcSeries＝直近最大5年の中央値）を、"
                         "_tcYears≥3 のときだけ採る。1〜2年の単年値は欠測。IC 縮退ガード・税/負債/無形の欠測・年検問は門と同じ",
            "cop_at": "主。OP=営業利益(無ければ税引前+利払い)+減価償却+研究開発費(mw の族＋ADBE の変種タグ・無ければ0)。"
                      "増減の行は mw の pick（10-K・期末±3日）で値を採り、無いときは retro_features2.flow3 の規約"
                      "（同じ年ラベルに触れる報告あり＝欠測／無し＝0）。÷総資産・(−1,2) の外は欠測",
            "cop_at_mw": "副。mw の year_features と同じ（増減の行・研究開発費が無ければ0・研究開発費は mw の族だけ）",
            "cop_at_strict": "報告のみ（事後の感度）。事前登録の括弧内の言い換え＝値が無く期限内のどこかで報告している行は欠測"
                             "（増減の行と研究開発費に retro_features2.tag_seen を当てた）",
            "nsi": "log(同じ10-K〔同じ accn〕の基本加重平均株数 当期÷前期)。前期＝期末の350〜380日前の列。(−2,2) の外は欠測。少ないほど良い",
            "accr": "門の採取器の accr（%）÷100＝(純利益−営業CF)÷総資産。小さいほど良い",
            "fy": "起点までに出た年次報告のうち期末が最新のもの（hachimon_fetch._fy_model の期末とラベル）",
            "universe": "今日の SEC ティッカー表の CIK ∩ companyfacts ∩ 最新の年次報告が10-K(us-gaap) ∩ SIC が 6000-6999 でない "
                        "∩ 起点の月の月次リターンが作れる（前月末と起点の月の足）。出所は retro_monthly を優先、無ければ Yahoo",
            "mcap": "起点の前月末の終値（Yahoo close×起点より後の分割の比＝当時の株価）×株数。株数は起点までに提出された3つの候補"
                    "（表紙の発行済株数 dei・貸借対照表の株数・最新の基本加重平均株数。種類株は同じ提出・同じ日付の値を足す。候補の日付と起点の間の分割を掛ける）"
                    "の中央値。2つしか無く2倍超ずれたら表紙の浮動株時価に近いほう。申告の千倍・千分の一の誤記が実在する（GRMN・WNC・IPAR…）ので1つを無条件に信じない。"
                    "時価総額は報告のみ（pool_secondary の 20億ドル）",
            "stale_10k": "期末が起点の548日（約18か月）より前＝最新の10-Kが古い社。事前登録に規則が無いので除かず印だけ付けた",
            "semi": "semi_3674＝SIC 3674 ／ semi_set＝combo_spy.semi_set の規則を SIC へ当てたもの（3559/3670/3672/3674-3679/3827）",
        },
        "counts": counts, "excluded_reasons": reasons,
        "yahoo_fetched_new": YAHOO_FETCHED[0],
        "no_returns_computed": True,
    }
    meta["diagnostics_no_returns"] = diagnostics(rows)
    spot_checks(rows)
    meta["deviations_and_interpretations"] = DEVIATIONS
    meta["spot_checks"] = SPOT_CHECKS
    rows = slim(rows)
    out = {"meta": meta, "windows": rows}
    p = out_path(partial)
    json.dump(out, open(p, "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"■ → {p}", flush=True)
    for w in WINDOWS:
        print(w, json.dumps(counts[w], ensure_ascii=False), flush=True)
    return out


def out_path(partial):
    # 数社だけの試運転は正本（out/）を上書きしない＝一時の場所へ（正本を数社で上書きすると、読む側が全母集団と誤認する）
    return os.path.join(SCRATCH, "gate_add_facts.partial.json") if partial else os.path.join(OUT, "gate_add_facts.json")


DETAIL = ("cop_vals", "cop_parts", "cop_states", "cop_outside", "dr_gross", "tc", "cop_why_strict", "cop_why_mw",
          "px_close_adj", "px_split_factor_after", "sh_cands", "roic_note")
MINIMAL = ("cik", "ticker", "name", "sic", "fy", "fy_end", "price_src", "mcap", "roic_n", "roic_why", "stale_10k")


def slim(rows):
    """出力を細くする: 門式 ROIC が出た社は特徴を全部・どこかの窓でプール（ROIC≥15）に入った社は点検用の中身まで。
    それ以外（母集団には居るが ROIC が出ない社）は最小限（数えるための欄だけ）"""
    pool_any = {c for w in rows for c, r in rows[w].items() if (r.get("roic_med5") or -1e9) >= 15}
    out = {}
    for w, R in rows.items():
        out[w] = {}
        for c, r in R.items():
            r = dict(r)
            if len(r.get("tickers") or []) <= 1:
                r.pop("tickers", None)
            if c in pool_any:
                out[w][c] = r
            elif r.get("roic_med5") is not None:
                out[w][c] = {k: v for k, v in r.items() if k not in DETAIL or k == "tc"}
            else:
                out[w][c] = {k: r[k] for k in MINIMAL if k in r}
    return out


def diagnostics(rows):
    """リターンを見ない記述統計だけ（プール＝門式 ROIC≥15 の中）。採否には使わない"""
    import statistics as st
    D = {}
    for w, R in rows.items():
        P = [r for r in R.values() if (r.get("roic_med5") or -1e9) >= 15]
        d = {"pool_n": len(P)}
        d["cop_fixed"] = {k: sum(1 for r in P if k in (r.get("cop_fixed") or [])) for k in ("rd_software_tag", "dr_gross_to_net")}
        d["cop_fixed_names"] = {k: sorted(r["ticker"] for r in P if k in (r.get("cop_fixed") or []))
                                for k in ("rd_software_tag", "dr_gross_to_net")}
        d["dr_gross_seen_not_applied"] = sorted(r["ticker"] for r in P if (r.get("dr_gross") or {}).get("applied") is False)
        d["cop_main_missing_why"] = {}
        for r in P:
            if r.get("cop_at") is None:
                k = (r.get("cop_why") or "?")[:40]
                d["cop_main_missing_why"][k] = d["cop_main_missing_why"].get(k, 0) + 1
        d["nsi_missing_why"] = {}
        for r in P:
            if r.get("nsi") is None:
                k = (r.get("nsi_why") or "?")[:40]
                d["nsi_missing_why"][k] = d["nsi_missing_why"].get(k, 0) + 1
        both = [(r["cop_at"], r["cop_at_mw"]) for r in P if r.get("cop_at") is not None and r.get("cop_at_mw") is not None]
        d["cop_main_vs_mw"] = {"n_both": len(both), "n_equal": sum(1 for a, b in both if abs(a - b) < 1e-9),
                               "median_abs_diff": round(st.median([abs(a - b) for a, b in both]), 5) if both else None}
        d["cop_outside_family_tags_share"] = round(sum(1 for r in P if r.get("cop_outside")) / len(P), 3) if P else None
        tagc = {}
        for r in P:
            for t in (r.get("cop_outside") or {}):
                tagc[t] = tagc.get(t, 0) + 1
        d["cop_outside_top_tags"] = dict(sorted(tagc.items(), key=lambda x: -x[1])[:8])
        ACCR_LIKE = ("IncreaseDecreaseInAccruedLiabilitiesAndOtherOperatingLiabilities",
                     "IncreaseDecreaseInEmployeeRelatedLiabilities", "IncreaseDecreaseInOtherAccruedLiabilities")
        d["accrued_like_outside_family_with_cop"] = sorted(
            r["ticker"] for r in P if r.get("cop_at") is not None and any(t in (r.get("cop_outside") or {}) for t in ACCR_LIKE))
        d["oi_from_pretax"] = sum(1 for r in P if (r.get("cop_parts") or {}).get("oi_from_pretax"))
        d["stale_10k"] = sorted(r["ticker"] for r in P if r.get("stale_10k"))
        d["accr_year_ne_fy"] = sorted(r["ticker"] for r in P if r.get("accr") is not None and r.get("accr_year") != r.get("fy"))
        d["tc_last_ne_fy"] = sorted(r["ticker"] for r in P if r.get("tc_last") is not None and r.get("tc_last") != r.get("fy"))
        d["price_src"] = {k: sum(1 for r in P if r.get("price_src") == k) for k in ("retro_monthly", "yahoo")}
        d["mcap_missing"] = sorted(r["ticker"] for r in P if r.get("mcap") is None)
        d["shares_cover_suspect"] = sorted(r["ticker"] for r in P if r.get("sh_suspect"))
        d["px_ccy_not_usd"] = sorted(r["ticker"] for r in P if r.get("px_ccy") not in (None, "USD"))
        for k in ("cop_at", "cop_at_mw", "nsi", "accr", "roic_med5"):
            v = sorted(r[k] for r in P if r.get(k) is not None)
            if v:
                d[f"dist_{k}"] = {"n": len(v), "p10": round(v[len(v) // 10], 4), "p50": round(v[len(v) // 2], 4),
                                  "p90": round(v[len(v) * 9 // 10], 4)}
        D[w] = d
    return D


DEVIATIONS = [
    "cop_at（主）の研究開発費に RD_SOFTWARE（ResearchAndDevelopmentExpenseSoftwareExcludingAcquiredInProcessCost）を足した。"
    "mw の族（副）には無く、ADBE・CDNS などこの変種だけを使う社の研究開発費が0と読まれる（retro_features2 が 2026-08-05 に是正した偽0と同じ）。"
    "是正前の主の値は cop_at_prefix に残した。研究開発費の『行が無ければ0』は mw どおり（事前登録が三値読みを指定したのは増減の行だけ）",
    "cop_at（主）の前受収益: 同じ10-K に RecognitionOfDeferredRevenue（キャッシュフロー計算書の取り崩しの行）があり、"
    "貸借対照表の前受収益の期首→期末の差が『繰り延べ−取り崩し』の純額のほうに近いときだけ純額を使った（MSFT FY2012・FY2015 の総額表示＝"
    "IncreaseDecreaseInDeferredRevenue に 361億$/451億$ の総額の繰り延べ。副の mw はそのまま＝MSFT 2016 は 0.455 と 0.200 に割れる）。是正前は cop_at_prefix",
    "三値読みの『触れる報告』は retro_features2.flow3 をそのまま使った＝年ラベルは期末の暦年（int(end[:4])）。1〜3月決算の社は当期の四半期が前の暦年に、"
    "翌期の第1四半期が同じ暦年に入るので、触れる報告の判定が会計年度とずれうる（例 NVDA FY2016: 翌期の第1四半期の IncreaseDecreaseInAccruedLiabilities で欠測）。"
    "flow3 の値が mw の pick に掛からない（10-K 以外の様式・期末が±3日の外）ときは期末±10日なら使い、外なら欠測",
    "事前登録の括弧内の言い換え（その年に行が無いが他の年には報告している＝欠測）は flow3 の規約（同じ年に触れる報告があれば欠測）と厳密には違う。"
    "主は flow3（事前登録が名指しした関数）とし、言い換えどおりの版を cop_at_strict として報告のみで残した（研究開発費にも同じ規則）",
    "nsi の『同じ10-K』は accn で見分けた（mw は同じ提出日＋訂正の印）",
    "fy は mw の『t−1 年の暦年内の期末』ではなく事前登録どおり『起点までに提出された最新の年次報告の期末』（3月決算の社は mw より1年新しい）",
    "roic_med5 は門の採取器の roic を _tcYears≥3 のときだけ採った（門は1〜2年なら単年値を出すが、事前登録は3年以上）",
    "期末が起点の548日より前の社（stale_10k）は事前登録に規則が無いので除かず印だけ付けた",
    "SIC は今日の登録分類（時点つきではない）。SIC が取れない社は金融か確かめられないので母集団から外した（excluded_reasons に数）",
    "時価総額の株数は表紙の発行済株数（dei）。種類株は同じ提出・同じ日付の値を足した。dei に無い社（GOOGL 等）は us-gaap の CommonStockSharesOutstanding へ倒した",
]

# ───────────── 手で確かめた値（10-K の表示＝EDGAR の Financial_Report.xlsx の行から電卓で計算） ─────────────
#   組み立てのたびに計算値と突き合わせ、差を meta.spot_checks に残す（差があれば理由も）
SPOT_EXPECT = [
    {"window": "2016", "ticker": "MSFT", "fy": "FY2015（期末 2015-06-30）", "accn": "0001193125-15-272806",
     "lines": "営業利益 18,161／研究開発費 12,046／減価償却等『Depreciation, amortization, and other』5,957（custom タグ＝族の外。族の代わりの"
              " Depreciation タグは 5,400）／売掛金 +1,456／棚卸 −272／その他流動資産 +62／前受収益 繰り延べ 45,072・取り崩し (44,920)／"
              "買掛金 (1,054)／その他流動負債 (624)／総資産 176,223／基本加重平均株数 8,177・8,299（百万）／純利益 12,193・営業CF 29,080／"
              "税引前 18,507・税 6,314／自己資本 80,083・短期借入 4,985・1年内長期 2,499・長期借入 27,808・のれん 16,939・無形 4,835（百万$）",
     "cop_at_hand": (18161 + 5400 + 12046 + 1456 - 272 + 62 + (45072 - 44920) - 1054 - 624) / 176223,
     "cop_at_hand_note": "式の減価償却（族の Depreciation 5,400）で 0.20047。表示の 5,957 なら 0.20363。mw（副）は総額の繰り延べ 45,072 を増減と読んで 0.455",
     "nsi_hand": math.log(8177 / 8299), "accr_hand": (12193 - 29080) / 176223,
     "roic_year": "2015", "roic_hand": 18161 * (1 - 6314 / 18507) / (80083 + 35292 - 16939 - 4835) * 100,
     "roic_hand_note": "表示の有利子負債 35,292（4,985+2,499+27,808）で 12.78%。門の採取器は 40,285（CommercialPaper 5,000 と ShortTermBorrowings 4,985 を"
                       "両方足す＝同じコマーシャルペーパーの額面と簿価の二重）で 12.14%。5年の中央値は FY2012 の 26.39% で、どちらでも FY2015 は最小＝中央値は不変"},
    {"window": "2022", "ticker": "ADBE", "fy": "FY2021（期末 2021-12-03）", "accn": "0000796343-22-000032",
     "lines": "営業利益 5,802／研究開発費 2,540（タグは ResearchAndDevelopmentExpenseSoftwareExcludingAcquiredInProcessCost）／減価償却等 788／"
              "売掛金 (430)／前払等 (475)／買掛金 (20)／未払費用等 162／前受収益 1,053／総資産 27,241／基本株数 477.3・480.9／純利益 4,822・営業CF 7,230／"
              "税引前 5,705・税 883／自己資本 14,797・借入 4,123・のれん 12,668・その他無形 1,820（百万$）",
     "cop_at_hand": (5802 + 788 + 2540 - 430 - 475 - 20 + 162 + 1053) / 27241,
     "cop_at_hand_note": "mw（副）は研究開発費の変種タグを読まず 0.25256",
     "nsi_hand": math.log(477.3 / 480.9), "accr_hand": (4822 - 7230) / 27241,
     "roic_year": "2021", "roic_hand": 5802 * (1 - 883 / 5705) / (14797 + 4123 - 12668 - 1820) * 100,
     "roic_hand_note": "表示の無形 1,820 で 110.6%（門は 1,839 で 111.1%）。門の系列は FY2018・FY2019 を IC/ICg<20%（のれん控除で分母縮退）で除き、"
                       "FY2017/2020/2021 の3年の中央値 80.25%"},
    {"window": "2022", "ticker": "CW", "fy": "FY2021（期末 2021-12-31）", "accn": "0000026324-22-000004",
     "lines": "営業利益 382,683／研究開発費 88,489／減価償却 114,384／売掛金 (59,372)／棚卸 15,321／買掛金・未払費用 17,713／前受収益 9,584／"
              "総資産 4,103,545／基本株数 40,417・41,738（千株）／純利益 267,159・営業CF 387,668／税引前 354,510・税 87,351／自己資本 1,826,490・"
              "長期借入 1,050,610・のれん 1,463,026・その他無形 538,077（千$）",
     "cop_at_hand": (382683 + 114384 + 88489 - 59372 + 15321 + 17713 + 9584) / 4103545,
     "nsi_hand": math.log(40417 / 41738), "accr_hand": (267159 - 387668) / 4103545,
     "roic_year": "2021", "roic_hand": 382683 * (1 - 87351 / 354510) / (1826490 + 1050610 - 1463026 - 538077) * 100},
    {"window": "2022", "ticker": "LRCX", "fy": "FY2021（期末 2021-06-27）", "accn": "0000707549-21-000136",
     "lines": "営業利益 4,482,023／研究開発費 1,493,408／減価償却 307,151／売掛金 (928,928)／棚卸 (792,591)／前払等 (59,189)／買掛金 184,615／"
              "前受利益 508,008／未払費用等 409,344（タグ IncreaseDecreaseInAccruedLiabilitiesAndOtherOperatingLiabilities＝mw の族の外）／"
              "総資産 15,892,152／基本株数 143,609・144,814（千株）／純利益 3,908,458・営業CF 3,588,163／税引前 4,370,804／自己資本 6,027,188・"
              "借入 11,349+4,990,333（リース込み）・のれん 1,490,134・無形 132,365（千$）",
     "cop_at_hand": (4482023 + 307151 + 1493408 - 928928 - 792591 - 59189 + 184615 + 508008) / 15892152,
     "cop_at_hand_note": "族の外の未払費用等 +409,344 を0と読んだ式どおりの値。表示の行を全部足すと 0.35262（+0.026）＝主も副も同じく取りこぼす",
     "nsi_hand": math.log(143609 / 144814), "accr_hand": (3908458 - 3588163) / 15892152,
     "roic_year": "2021", "roic_hand": 4482023 * (1 - (4370804 - 3908458) / 4370804) / (6027188 + 4960935 - 1490134 - 132365) * 100,
     "roic_hand_note": "有利子負債は門どおり LongTermDebt 4,960,935（表示はリース込み 5,001,682）"},
]
SPOT_CHECKS = {}


def spot_checks(rows):
    for e in SPOT_EXPECT:
        R = rows.get(e["window"]) or {}
        r = next((x for x in R.values() if x.get("ticker") == e["ticker"]), None)
        k = f'{e["ticker"]}@{e["window"]}'
        if r is None:
            SPOT_CHECKS[k] = {"error": "母集団に居ない"}
            continue
        got_roic_y = (r.get("tc") or {}).get(e["roic_year"])
        rec = {"fy": e["fy"], "accn": e["accn"], "lines_from_10k": e["lines"],
               "cop_at": {"computed": r.get("cop_at"), "hand": round(e["cop_at_hand"], 6),
                          "diff": None if r.get("cop_at") is None else round(r["cop_at"] - e["cop_at_hand"], 6),
                          "mw": r.get("cop_at_mw"), "note": e.get("cop_at_hand_note")},
               "nsi": {"computed": r.get("nsi"), "hand": round(e["nsi_hand"], 6),
                       "diff": None if r.get("nsi") is None else round(r["nsi"] - e["nsi_hand"], 6)},
               "accr": {"computed": r.get("accr"), "hand": round(e["accr_hand"], 5),
                        "diff": None if r.get("accr") is None else round(r["accr"] - e["accr_hand"], 4)},
               "roic_year": {"year": e["roic_year"], "computed": got_roic_y[0] if got_roic_y else None,
                             "hand": round(e["roic_hand"], 2), "note": e.get("roic_hand_note")},
               "roic_med5": {"computed": r.get("roic_med5"), "series": r.get("tc")}}
        SPOT_CHECKS[k] = rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    ap.add_argument("--stage", default="all", choices=["all", "facts", "sic", "assemble"])
    ap.add_argument("--procs", type=int, default=3)
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args()
    if not os.path.exists(ZIP):
        sys.exit("companyfacts.zip が無い（SEC から取り直す: https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip）")
    ciks, tdate = ticker_table()
    only = None
    if a.only:
        want = {x.strip().upper() for x in a.only.split(",")}
        only = [c for c, ts in ciks.items() if want & {t.upper() for t in ts}]
    partial = bool(only)
    if a.stage in ("all", "facts"):
        raw = stage_facts(ciks, only, a.procs)
    else:
        raw = load_raw(partial)
    if a.stage == "facts":
        return 0
    need = [int(c) for c, r in raw.items() if "w" in r and any(
        any((x or "").startswith("10-K") for x in (f.get("forms") or [])) for f in r["w"].values())]
    S = sic_map(need)
    if a.stage == "sic":
        return 0
    out = assemble(ciks, raw, S, partial=partial, fetch=not a.no_fetch)
    out["meta"]["ticker_table_date"] = tdate
    json.dump(out, open(out_path(partial), "w"), ensure_ascii=False, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
