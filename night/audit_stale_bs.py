#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_stale_bs.py — **パックの貸借対照表が「期末後の重大事象」を跨いで古くなっていないか**（2026-08-06新設）

なぜ要るか（実際に踏んだ穴）:
  2026-08-06、roicGap の崖を段階減点にした帰結として **APH（アンフェノール）が投下可へ入り、
  資産の6.3%を占める第3位の配分**を受けた。ところが調べると——

    パックの reportDate      : 2025-12-31
    CommScope買収(約105億$・同社史上最大)の完了 : **2026-01-09＝期末の9日後**
    その後の実額(10-Q・2026-07-31提出):
        のれん   10,575 → 17,555 百万$ (+66%)
        無形      2,241 →  5,289 百万$ (+136%)
        総資産   36,237 → 44,807 百万$ (+24%)
        のれん＋無形 ÷ 自己資本   96% → **147%**（自己資本を超えた）

  **パックが採点しているのは、期末の9日後に消えた会社**だった。しかも roicGap を動かす当の変数
  （のれん＋無形 ÷ 投下資本）がまさにここで膨らんでいる＝罰が効くべき方向に事実が動いているのに、
  台帳はそれを見ていない。

  既存の鮮度検査（validate_packs・2026-07-29新設）は **reportDate と auditDate の「年」の差**しか
  見ていない（3年前でFAIL・2年前でwarn。DSGXが2005年の20-Fで審査されていた事故への対策）。
  APH は同じ年なので**警告すら出ない**。acq5 も「過去5年に買収したか」を見るだけで、
  **期末の後に閉じた買収は次の10-Kが出るまで誰の目にも入らない**。

何を測るか:
  パックの reportDate 時点の のれん と、その後に提出された最新の のれん を比べ、
  **「今あるのれんのうち何割が reportDate 以降に入ってきたか」** を出す。
  ——これは acq5 が使っているのとまったく同じ問いで、同じ刻み（≥30%）をそのまま使う。
  **新しい定数を発明していない**（門の作法）。

思想:
  この道具は**読むだけ**で、採点にもパックにも書き込まない。
  検出は「この銘柄は買付の土俵に載せない」＝第四の関門の領分であり、
  Ω・売却規律・堀の関門はいずれも動かさない（絶対のルール1）。
  **買わない理由であって売る理由ではない。**

使い方:
  python3 night/audit_stale_bs.py            判定圏(Ω72+)だけ（SECへの請求を絞る）
  python3 night/audit_stale_bs.py --all      全パック
  python3 night/audit_stale_bs.py --t APH    1銘柄
  python3 night/audit_stale_bs.py --write    out/stale_bs.json を更新（score_all が読む）
出力:
  out/stale_bs.json  … {ticker: {reportDate, gwAt, gwNow, newPct, asOf, verdict, note}}
"""
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")
EMAIL = "fortis5280@gmail.com"
HDRS = {"User-Agent": f"ccf-gate {EMAIL}"}

# acq5 と同じ刻みを使う（新しい定数を作らない）
#   yes ≥30% / no <10% / 中間は判定不能  ——「今あるのれんの何割が新しいか」
NEW_YES, NEW_NO = 30.0, 10.0

ARGV = sys.argv[1:]
ALL = "--all" in ARGV
WRITE = "--write" in ARGV
ONE = ARGV[ARGV.index("--t") + 1] if "--t" in ARGV else None


def get(url):
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
    time.sleep(0.15)          # 礼儀（SECは10req/s制限）
    return b.decode("utf-8", "ignore")


_TICK = {}


def cik_of(t):
    global _TICK
    if not _TICK:
        try:
            j = json.loads(get("https://www.sec.gov/files/company_tickers.json"))
            _TICK = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in j.values()}
        except Exception as e:
            print(f"  ティッカー表の取得に失敗: {e}")
            return None
    return _TICK.get(t.upper())


# 2026-08-10: **20-F/6-K を足した。** それまでは 10-K/10-Q だけを見ていたので、
#   **外国私募発行体（ASML＝🟢投下可 / SAP / RELX / RACE …）は系列が空**になり、
#   「のれんを一度も報告していない社」とまったく同じ袋に入っていた——
#   ＝**期末後の重大事象を原理的に検出できないのに、検出できた顔をする**（ルール7の親戚）。
#   6-K は中間財務諸表を添付するので BS項目が入ることがある。
#   ⚠IFRS提出体は us-gaap タグを持たないので、下の concept() が ifrs-full も見る。
FORMS_OK = ("10-K", "10-Q", "20-F", "40-F", "6-K")

_FACTS = (None, None)          # (cik, 解析済みfacts) ——直前の1社だけ持つ（1社4.6MB。全社抱えると数百MB）


def facts(cik):
    """companyfacts を1社ぶん取って持ち回す。取れなければ None"""
    global _FACTS
    if _FACTS[0] == cik:
        return _FACTS[1]
    try:
        d = json.loads(get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"))
    except Exception:
        d = None
    _FACTS = (cik, d)
    return d


def concept(cik, tag):
    """{期末日: 値} を返す（インスタント値のみ＝BS項目）。取れなければ None

    us-gaap で取れなければ **ifrs-full** も見る（20-F提出体のため・2026-08-10）。

    **companyconcept ではなく companyfacts から採る（2026-08-10 是正）**——
    companyconcept は 2026-08 時点で `"units":{"USD":{}}` と**空を返す**（実測 VRSK/CTAS の
    Goodwill・Assets とも0件。同じCIKの companyfacts には Goodwill が134件ある）。
    CLAUDE.md は 2026-08-09 に fill_growth_trend で**まったく同じ故障を記録している**
    （「companyconcept API が信用できない…この repo の道具が全部使っている companyfacts へ統一」）が、
    **直したのはその1本だけで、第四の関門であるこの道具は取り残されていた**＝
    「1社直したら同型も洗う」の取りこぼし。しかも実害の形が悪い——
    **例外ではなく空の辞書が返る**ので、全社が「のれんの系列なし」として静かに skip され、
    `--write` すると out/stale_bs.json が**空で上書きされて関門ごと消える**。
    「検査が回ったつもりで回っていない」＝この台帳が最も嫌う壊れ方（hist_val_regime の
    `if __name__` 置き忘れと同族）。下の main() に空書き込みの検問を入れてある。
    """
    d = facts(cik)
    if not d:
        return None
    ns_all = d.get("facts", {}) or {}
    units = {}
    for ns in ("us-gaap", "ifrs-full"):      # IFRS提出体は us-gaap を持たない
        u = ((ns_all.get(ns, {}) or {}).get(tag, {}) or {}).get("units", {})
        if u:
            units = u
            break
    out = {}
    for u in units.values():
        if not isinstance(u, list):          # 空や型崩れは黙って飛ばす（0件と読まない）
            continue
        for x in u:
            if x.get("start") or x.get("form") not in FORMS_OK:
                continue
            e = x.get("end")
            if e:
                # 同じ期末で複数提出があれば**後から提出されたもの**を採る（遡及修正を反映）
                prev = out.get(e)
                if prev is None or x.get("filed", "") >= prev[1]:
                    out[e] = (x["val"], x.get("filed", ""))
    return {k: v[0] for k, v in out.items()}


def main():
    rows = json.load(open(os.path.join(OUT, "score_all.json"), encoding="utf-8"))
    if ONE:
        pick = [r for r in rows if r["t"] == ONE]
    elif ALL:
        pick = rows
    else:
        pick = [r for r in rows if (r.get("s") or 0) >= 72]

    print(f"■ 期末後の重大事象で貸借対照表が古くなっていないか　対象 {len(pick)}社"
          f"{'（判定圏 Ω72+）' if not (ALL or ONE) else ''}")
    print(f"  判定: 「今あるのれんのうち reportDate 以降に入った割合」が {NEW_YES:.0f}% 以上なら要審査")
    print(f"        （acq5 と同じ問い・同じ刻み＝新しい定数を作らない）\n")

    res, skipped, fetched = {}, [], 0     # fetched=のれんの系列が実際に取れた社数（空書き込みの検問に使う）
    for r in pick:
        t = r["t"]
        if re.fullmatch(r"\d{4}", t):        # 日本株はSEC対象外
            skipped.append((t, "日本株(SEC対象外)"))
            continue
        p = os.path.join(OUT, f"{t}_gate_pack.json")
        if not os.path.exists(p):
            continue
        d = json.load(open(p, encoding="utf-8"))
        rd = str((d.get("_meta") or {}).get("reportDate") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", rd):
            skipped.append((t, "reportDate が無い/不正"))
            continue
        cik = cik_of(t)
        if not cik:
            skipped.append((t, "CIK不明(ADR等)"))
            continue
        gw = concept(cik, "Goodwill")
        if not gw:
            skipped.append((t, "のれんの系列なし(のれんを持たない社を含む)"))
            continue
        fetched += 1
        after = {k: v for k, v in gw.items() if k > rd}
        if not after:
            continue                          # reportDate 以降の提出がまだ無い＝正常
        at = max([k for k in gw if k <= rd], default=None)
        if at is None:
            continue
        g0, asOf = gw[at], max(after)
        g1 = after[asOf]
        if g1 <= 0:
            continue
        new_pct = (g1 - g0) / g1 * 100.0      # 今あるのれんのうち新しく入った割合
        verdict = ("要審査" if new_pct >= NEW_YES
                   else "判定不能" if new_pct > NEW_NO else "ok")
        if verdict != "ok":
            res[t] = dict(reportDate=rd, gwAt=g0, gwNow=g1, asOf=asOf,
                          newPct=round(new_pct, 1), verdict=verdict, omega=r.get("s"),
                          buy=bool(r.get("buy")))
        print(f"  {t:<7}{rd}  のれん {g0/1e6:>10,.0f} → {g1/1e6:>10,.0f} 百万$"
              f"（{asOf}）  新しさ {new_pct:>6.1f}%  {'⚠ '+verdict if verdict!='ok' else '✓'}")

    print()
    bad = {k: v for k, v in res.items() if v["verdict"] == "要審査"}
    mid = {k: v for k, v in res.items() if v["verdict"] == "判定不能"}
    if bad:
        print("■ 要審査（パックの貸借対照表が会社の現在を描いていない）")
        for t, v in sorted(bad.items(), key=lambda x: -x[1]["newPct"]):
            mark = " ← **投下可**" if v["buy"] else ""
            print(f"   {t:<7}Ω{v['omega']:.1f}  のれんの{v['newPct']:.1f}%が {v['reportDate']} 以降に入った{mark}")
    if mid:
        print("■ 判定不能（中間帯・acq5と同じく空欄に倒す）")
        for t, v in mid.items():
            print(f"   {t:<7}新しさ {v['newPct']:.1f}%")
    if not res:
        print("✓ 期末後に貸借対照表が大きく変わった社は無し")
    if skipped:
        print(f"\n  対象外 {len(skipped)}社（穴として明示する・黙って対象外にしない）:")
        from collections import Counter
        for why, n in Counter(w for _, w in skipped).most_common():
            print(f"    {n:>3}社  {why}")

    if WRITE:
        path = os.path.join(OUT, "stale_bs.json")
        # ── 空書き込みの検問（2026-08-10新設）───────────────────────────────
        #   採取経路が壊れると **例外ではなく空の系列**が返り、全社が「のれんの系列なし」で
        #   静かに skip され、ここで out/stale_bs.json が空で上書きされて**関門ごと消える**。
        #   実際に踏んだ: companyconcept が `"units":{"USD":{}}` を返すようになり、
        #   この道具は「検査が回ったつもりで回っていない」状態だった。
        #   **一社もデータが取れていないのに書き換えるのは、検査の不在を「異常なし」と偽ること**（ルール7）。
        if fetched == 0 and not ONE:
            print(f"\n⛔ **書き込みを中止**——のれんの系列が取れた社が0（対象 {len(pick)}社）。"
                  f"\n   採取経路が壊れている疑いが濃い。既存の {path} を空で上書きすると"
                  f"\n   第四の関門（期末後の重大事象）が黙って消えるので、書かない。")
            return 1
        json.dump({"asof": time.strftime("%Y-%m-%d"), "rule": f"のれんの新しさ≥{NEW_YES:.0f}%で要審査",
                   "fetched": fetched,
                   "items": res}, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n→ {path} を更新（score_all.js が第四の関門で読む・のれんが取れた社 {fetched}）")
    else:
        print("\n（--write で out/stale_bs.json を更新する）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
