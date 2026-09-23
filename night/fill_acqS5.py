#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/fill_acqS5.py — acqS5（買収支出の5年合計 ÷ 期初総資産）を機械で埋める（v9.9.181・2026-09-21新設）

■ なぜ gwg5（のれん残高の5年増加率）から替えるのか
  のれん**残高**の増減は **減損・事業売却・為替**で汚れる。実測（docs/CLAUDE_ARCHIVE.md:14804）:
   ・同じ661社・同じ窓・同じリターンでも、のれんの読み方（companyfacts / SEC frames）を替えるだけで
     「最下位」が Q1(買収しない) と Q4(大きく買う) で**入れ替わる**（411社で値が0.05超ずれる）。
   ・Q1 の内訳は のれんが3割以上消えた群 4.0% / やや減 5.6% / ほぼ横ばい 6.0% ＝
     **Q1の下半分は「買わなかった社」ではなく「買って償却した社」**だった。
  **支出なら 0 が「本当に一円も買っていない」を意味する。**

■ 定義（歴史検証 night/retro_acqspend.py と同一にそろえる）
      acqS5 = Σ(直近5会計年度の買収支出) ÷ 総資産(審査年−5)
  分子は `PaymentsToAcquireBusinessesNetOfCashAcquired`（IFRS申告社は
  `CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinessesClassifiedAsInvestingActivities`）。
  **負値は0に丸める**（売却による回収を買収支出と相殺しない＝測っているのは「どれだけ買ったか」）。

■ 帯（`ccfAcqBand` が持つ。**切れ目は測定値であって発明ではない**）
      0            → 買収しない  −1
      0 〜 0.085   → 控えめ      +2   ← 最高
      0.085〜0.311 → 中          +1
      0.311 超     → 大きく買う   0
  0.085 / 0.311 は **7ビンテージ(2015-2021)の三分位の切れ目の中央値**で、
  たまたま2018年ビンテージの切れ目とちょうど一致する（下限 0.079〜0.092 / 上限 0.296〜0.347 と7年ぶん不動）。

■ 絶対のルール7（「タグが無い」と「値が0」を区別する）
  ・買収支出は**フロー**なので、ある年に事実が無い＝その年は買っていない、と読んでよい。
    **ただしその社が XBRL でタグ付けしていることを先に確かめる**——総資産(Assets)が申告されている社に限る。
  ・companyconcept が **200 で中身が空**を返す社がある（実測 V / KO / CDNS など）ので
    404 と区別し、空なら **companyfacts で引き直す**。
  ・期初総資産が取れない社は**空欄**（分母を推測しない）。空欄の理由は必ず `_meta.nulls` に書く。

実行: python3 night/fill_acqS5.py [--write] [--only MSFT,APH] [--list]
"""
import json, os, sys, time, datetime, urllib.request, urllib.error, glob

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HDRS = {"User-Agent": "hachimon-gate fortis5280@gmail.com"}
WIN = 45          # 会計期末との許容日数
PAY = [("us-gaap", "PaymentsToAcquireBusinessesNetOfCashAcquired"),
       ("us-gaap", "PaymentsToAcquireBusinessesGross"),
       ("ifrs-full", "CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinessesClassifiedAsInvestingActivities")]
ASSETS = [("us-gaap", "Assets"), ("ifrs-full", "Assets")]
# 「支出0」を信じてよいかを裏から確かめる系列（買収そのものの系列。fix_acq5.py と同じ作法）。
# ⚠ **支出の行を切り出さない社がある**——実測 MSFT は PaymentsToAcquireBusinesses… が **FY2011で終わり**、
#   Activision 690億$ は `GoodwillAcquiredDuringPeriod` 51,235百万$ にしか現れない。
#   ここで裏を取らないと「買っていない」という**嘘の0**を台帳へ書き込む（絶対のルール7）。
GWA = [("us-gaap", "GoodwillAcquiredDuringPeriod"),
       ("us-gaap", "BusinessCombinationConsiderationTransferred1"),
       ("us-gaap", "BusinessCombinationConsiderationTransferred")]


def d2(s):
    return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def _pick_unit(units):
    """通貨は社ごとに違う。比を取るので単位は揃っていればよいが、混ぜると通貨をまたいで割る"""
    units = {k: v for k, v in units.items() if v}
    return max(units, key=lambda k: len(units[k])) if units else None


def _parse(entries, kind):
    """kind='inst' → {end:val} ／ kind='dur' → [(start,end,val)] の年次だけ"""
    if kind == "inst":
        m = {}
        for e in entries:
            if e.get("start") or not e.get("end"):
                continue
            k = e["end"]
            if k not in m or e.get("filed", "") > m[k][1]:
                m[k] = (e["val"], e.get("filed", ""))
        return {k: v[0] for k, v in m.items()}
    m = {}
    for e in entries:
        st, en = e.get("start"), e.get("end")
        if not st or not en:
            continue
        try:
            if not (330 <= (d2(en) - d2(st)).days <= 400):   # 年次の期間だけ（四半期を足し込まない）
                continue
        except Exception:
            continue
        if en not in m or e.get("filed", "") > m[en][1]:
            m[en] = (e["val"], e.get("filed", ""))
    return {k: v[0] for k, v in m.items()}


def _concept(cik, tax, name, kind):
    u = "https://data.sec.gov/api/xbrl/companyconcept/CIK%010d/%s/%s.json" % (cik, tax, name)
    for i in range(4):
        try:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=HDRS), timeout=60).read())
            uk = _pick_unit(j.get("units", {}))
            if not uk:
                return ("empty", None)      # ⚠ 200で中身が空。404とは別物
            return ("ok", _parse(j["units"][uk], kind))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ("none", None)
            if i == 3:
                return ("miss", None)
            time.sleep(2 ** i)
        except Exception:
            if i == 3:
                return ("miss", None)
            time.sleep(2 ** i)
    return ("miss", None)


_FACTS = {}


def _facts(cik):
    """companyconcept が空を返す社の逃げ道（3〜4MBあるので第一手には使わない）"""
    if cik in _FACTS:
        return _FACTS[cik]
    u = "https://data.sec.gov/api/xbrl/companyfacts/CIK%010d.json" % cik
    for i in range(3):
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                u, headers=dict(HDRS, **{"Accept-Encoding": "gzip"})), timeout=180)
            b = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                import gzip
                b = gzip.decompress(b)
            _FACTS[cik] = json.loads(b).get("facts", {})
            return _FACTS[cik]
        except Exception:
            if i == 2:
                _FACTS[cik] = None
                return None
            time.sleep(2 ** i)
    return None


def grab(cik, cands, kind):
    """候補（税務分類×タグ）を順に引き、最初に取れたものを返す。
    ⚠ この候補群は **代替**（同じものの別名）であって構成要素ではない——足し合わせない"""
    saw_empty = False
    for tax, name in cands:
        st, m = _concept(cik, tax, name, kind)
        time.sleep(0.12)
        if st == "ok" and m:
            return ("ok", m)
        if st == "empty":
            saw_empty = True
    if saw_empty:
        f = _facts(cik)
        if f:
            for tax, name in cands:
                node = (f.get(tax, {}) or {}).get(name)
                if not node:
                    continue
                uk = _pick_unit(node.get("units", {}))
                if uk:
                    m = _parse(node["units"][uk], kind)
                    if m:
                        return ("ok", m)
            return ("none", None)
        return ("miss", None)
    return ("none", None)


def near(m, target, win=WIN):
    best = None
    for s, v in m.items():
        try:
            dd = abs((d2(s) - target).days)
        except Exception:
            continue
        if dd <= win and (best is None or dd < best[0]):
            best = (dd, v, s)
    return best


def back(dt, n):
    try:
        return dt.replace(year=dt.year - n)
    except ValueError:
        return dt.replace(year=dt.year - n, day=28)


def _misaligned(m, fe):
    """窓 (fe−5年, fe] に年次期末があるのに、どの錨 fe−k年(k=0..4) の±WIN にも乗らないならその期末を返す。
    reportDate が10-Q期末のパックでは錨がずれ、支出を0と読んでしまう（2026-09-23 実測）ので、それを見分ける。"""
    lo = back(fe, 5) + datetime.timedelta(days=WIN)    # 5年前の錨に乗る期末（窓の外の年）は数えない（52/53週の社で数日ずれる）
    for s in (m or {}):
        try:
            e = d2(s)
        except Exception:
            continue
        if lo < e <= fe and not any(abs((e - back(fe, k)).days) <= WIN for k in range(5)):
            return s
    return None


def main():
    write = "--write" in sys.argv
    only = None
    if "--only" in sys.argv:
        only = {x.strip().upper() for x in sys.argv[sys.argv.index("--only") + 1].split(",")}
    sic = json.load(open(os.path.join(BASE, "out/_sic_cache.json")))
    cikx, cpath = {}, os.path.join(BASE, "out/_cik_tickers.json")
    for i in range(5):
        try:
            j = json.loads(urllib.request.urlopen(urllib.request.Request(
                "https://www.sec.gov/files/company_tickers.json", headers=HDRS), timeout=60).read())
            for v in j.values():
                cikx[str(v.get("ticker", "")).upper()] = v.get("cik_str")
            json.dump(cikx, open(cpath, "w"))
            break
        except Exception as e:
            if i == 4:
                print("! company_tickers.json を引けなかった:", e)
                try:
                    cikx = json.load(open(cpath)); print("  → out/_cik_tickers.json（控え）を使う")
                except Exception:
                    print("  ⚠ 控えも無い。外国申告社の判定ができないので中止する"); sys.exit(2)
            else:
                time.sleep(3 * (i + 1))

    rows, skip, changed = [], 0, 0
    for f in sorted(glob.glob(os.path.join(BASE, "out/*_gate_pack.json"))):
        t = os.path.basename(f).replace("_gate_pack.json", "")
        if only and t.upper() not in only:
            continue
        d = json.load(open(f))
        rd = (d.get("_meta") or {}).get("reportDate")
        cik = (sic.get(t) or {}).get("cik") or cikx.get(t.upper())

        def clear(reason):
            """測れなかったら **値を消し、理由を必ず残す**（絶対のルール7・8）"""
            if not write:
                return False
            hit = False
            if d.get("acqS5") is not None and (d.get("_meta", {}).get("provenance", {}) or {}).get("acqS5") == "machine":
                d.pop("acqS5", None)
                d["_meta"].get("evidence", {}).pop("acqS5", None)
                d["_meta"].get("provenance", {}).pop("acqS5", None)
                hit = True
            if d.get("acqS5") is None and (d.setdefault("_meta", {}).setdefault("nulls", {})).get("acqS5") != reason:
                d["_meta"]["nulls"]["acqS5"] = reason
                hit = True
            if hit:
                json.dump(d, open(f, "w"), ensure_ascii=False, indent=1)
            return hit

        if not cik or not rd:
            skip += 1
            why = ("ティッカーからCIKを解決できない（日本株など、SECのXBRLに現れない社）"
                   if not cik else "パックに reportDate が無く基準年を決められない")
            changed += 1 if clear(why) else 0
            rows.append((t, None, why)); continue

        fe = d2(rd); c = int(cik)
        sa, am = grab(c, ASSETS, "inst")
        if sa != "ok":
            r_ = "SECのXBRLに総資産(Assets)が無い＝細目タグ付けをしていない社で、買収支出の0が『買っていない』と読めない"
            changed += 1 if clear(r_) else 0
            rows.append((t, None, r_)); continue
        b = near(am, back(fe, 5))
        if b is None or not b[1] or b[1] <= 0:
            r_ = "期初総資産（%s の前後45日）が取れない＝分母を推測しない" % back(fe, 5)
            changed += 1 if clear(r_) else 0
            rows.append((t, None, r_)); continue
        base_assets, base_end = b[1], b[2]

        sp, pm = grab(c, PAY, "dur")
        if sp == "miss":
            r_ = "買収支出の系列をSECから採取できなかった"
            changed += 1 if clear(r_) else 0
            rows.append((t, None, r_)); continue
        pm = pm or {}
        # 2026-09-23: **reportDate が会計年度末でない（10-Q期末で再審査したパック）と、錨 fe−k年 の±45日に
        #   年次期間が一つも乗らず、支出0＝「一円も買っていない」と書いていた**（実測: GOOGL/HWM/AWI/CDNS を
        #   2026-06-30 へ更新したら4社とも 0.000。Wiz 29.5十億$ や Hexagon 2.9十億$ を買った社で）。
        #   窓の中に年次期末があるのに錨に乗らない＝錨がずれている＝測れていない（絶対のルール7）。書かずに飛ばす。
        mis = _misaligned(pm, fe)
        if mis:
            rows.append((t, None, "reportDate %s が会計年度末でない（窓の中の年次期末 %s が錨に乗らない）＝年次の窓を組めないので書かない" % (rd, mis)))
            continue
        tot, hits, yrs = 0.0, [], 0
        for k in range(5):
            tgt = back(fe, k)
            e = near(pm, tgt)
            if e:
                v = max(0.0, e[1]); tot += v; yrs += 1
                if v > 0:
                    hits.append("%s %.0f百万$" % (e[2], v / 1e6))
        if tot <= 0:
            # 支出0のときだけ裏を取る（在るときは引かない＝SECへの無駄打ちをしない）
            sg, gm = grab(c, GWA, "dur")
            mis = _misaligned(gm, fe)
            if mis:
                rows.append((t, None, "reportDate %s が会計年度末でない（のれん増加の年次期末 %s が錨に乗らない）＝0を確かめられないので書かない" % (rd, mis)))
                continue
            got = 0.0
            for k in range(5):
                e = near(gm or {}, back(fe, k))
                if e and e[1] and e[1] > 0:
                    got += e[1]
            if sg == "miss":
                r_ = "買収支出が0だが、買収そのものの系列(のれん増加/対価)を採取できず0を確かめられない"
                changed += 1 if clear(r_) else 0
                rows.append((t, None, r_)); continue
            if got > 0:
                r_ = ("買収支出の行を切り出していない社＝測れない（5年で のれん増加/取得対価 %.0f百万$ を申告しているのに "
                      "買収支出の申告が0。MSFTがこの型——支出タグはFY2011で終わり Activision はのれん側にしか出ない）" % (got / 1e6))
                changed += 1 if clear(r_) else 0
                rows.append((t, None, r_)); continue
        g = tot / base_assets
        ev = ("買収支出 %d年ぶん合計 %.0f百万$ ÷ 期初総資産(%s) %.0f百万$ ＝ %.3f"
              % (5, tot / 1e6, base_end, base_assets / 1e6, g))
        ev += ("／内訳: " + " / ".join(hits)) if hits else "／**5年で買収支出の申告なし＝一円も買っていない**（総資産は申告済＝タグ付けしている社で、のれん増加・取得対価の申告も0であることを裏から確認済）"
        ev += "（SEC XBRL: PaymentsToAcquireBusinessesNetOfCashAcquired 系。負値は0に丸め・年次期間のみ）"
        rows.append((t, g, ev))
        old = d.get("acqS5")
        if write and (old is None or abs((old or 0) - g) > 1e-9):
            d["acqS5"] = round(g, 4)
            d.setdefault("_meta", {}).setdefault("evidence", {})["acqS5"] = ev
            d["_meta"].setdefault("provenance", {})["acqS5"] = "machine"
            d["_meta"].get("nulls", {}).pop("acqS5", None)
            json.dump(d, open(f, "w"), ensure_ascii=False, indent=1)
            changed += 1

    ok = [r for r in rows if r[1] is not None]
    def band(g):
        return "none" if g <= 0 else ("mild" if g <= 0.085 else ("mid" if g <= 0.311 else "heavy"))
    from collections import Counter
    c = Counter(band(r[1]) for r in ok)
    print("対象 %d社（CIK/reportDate 不明 %d社）／埋まった %d社／空欄 %d社"
          % (len(rows), skip, len(ok), len(rows) - len(ok)))
    print("  帯: 買収しない %d / 控えめ %d / 中 %d / 大きく買う %d"
          % (c["none"], c["mild"], c["mid"], c["heavy"]))
    if "--list" in sys.argv:
        for t, g, ev in rows:
            print("  %-6s %s  %s" % (t, ("%.4f" % g) if g is not None else " 空欄", ev[:150]))
    print("書き込み %d社%s" % (changed, "" if write else "（--write で反映）"))


if __name__ == "__main__":
    main()
