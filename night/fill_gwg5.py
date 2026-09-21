#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/fill_gwg5.py — gwg5（のれんの5年増加率）を機械で埋める（2026-09-21新設）

■ なぜ要るか（ユーザー明示指示「買収控えめを最もスコアが評価するようにして」）
  門は買収の「多寡」を **acq5 の yes/no** でしか持っていなかった。acq5 は
  「今あるのれんの何割が直近5年に入ってきたか」を ≥30% / <10% で二値にしたものなので、
  **買収しない社と控えめに買う社が同じ 'no' に入る**——歴史が最も分けたがっている境界が、
  台帳の中に一本も無かった。gwg5 はその連続量そのもの。

■ 定義（2018年の歴史検証 night/retro_features_2018.py:135 と同一にそろえる）
      gwg5 = のれん(審査年) ÷ のれん(審査年−5) − 1
  **基準年ののれんが 0 または報告が一度も無い社は gwg5 = 0.0**（＝5年でのれんは増えていない）。
  2018年の検証はここを 0除算として **除外**していたが、除外すると
  「買収しない」という最も基本的な群が丸ごと測定から消える。実測でこの群は
  中央値 4.3%/年（のれんを持つ社は 7.0%）で、四分位の Q1 と同じ帯にいる。

■ 採取（絶対のルール7: 「タグが無い」と「値が0」を区別する）
  SEC **companyconcept** API（us-gaap/Goodwill）を社ごとに1本引く。
    - 404（そのタグを一度も報告していない） → **のれん無しが事実** → gwg5 = 0.0
    - 200 だが審査年または基準年の前後45日に instant が無い → **空欄**（測れていない）
  companyfacts.zip(1.4GB) を落とさずに済み、frames と違って
  「報告していない」と「その四半期に載っていない」を区別できる。

■ 空欄は罰でも褒美でもない
  門の `ccfAcqBand(null)` は **0点**を返す（=未測定は加点も減点もしない）。
  dom/moatW の「空欄は重みを再正規化」と同じ作法で、加算項における等価物。
  ただし判定圏(Ω72+)の空欄は 🔍全件点検 が warn で名指しする。

■ 日本株・ADR は対象外（SECのus-gaapタグを持たない）＝空欄。EDINETからの充填は未実装。
実行: python3 night/fill_gwg5.py [--write] [--only MSFT,APH] [--list]
"""
import json, os, sys, time, datetime, urllib.request, urllib.error, glob

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HDRS = {"User-Agent": "hachimon-gate fortis5280@gmail.com"}
WIN = 45


def d2(s):
    return datetime.date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def _one(cik, tax, concept_name):
    """returns ('none',None) / ('ok',{end:val}) / ('miss',None)"""
    u = "https://data.sec.gov/api/xbrl/companyconcept/CIK%010d/%s/%s.json" % (cik, tax, concept_name)
    for i in range(4):
        try:
            r = urllib.request.urlopen(urllib.request.Request(u, headers=HDRS), timeout=60)
            j = json.loads(r.read())
            units = {k: v for k, v in j.get("units", {}).items() if v}
            if not units:
                # ⚠ **200 が返って中身が空**、は 404 とは別物。実測で V / KO / CDNS など16社が
                #   companyconcept で Goodwill も Assets も空配列を返す（コカコーラに総資産が
                #   無いはずがない＝API側の欠落）。これを「のれん無し」と読むと絶対のルール7そのもの。
                return ("empty", None)
            # 通貨は社ごとに違う（ASML は EUR）。比を取るので単位は揃っていればよい——
            # **最も申告数の多い単位ひとつ**に絞る（混ぜると通貨をまたいで割ることになる）
            uk = max(units, key=lambda k: len(units[k]))
            m = {}
            for e in units[uk]:
                if e.get("start"):
                    continue
                en = e.get("end")
                if not en:
                    continue
                if en not in m or e.get("filed", "") > m[en][1]:
                    m[en] = (e["val"], e.get("filed", ""))
            return ("ok", {k: v[0] for k, v in m.items()}) if m else ("none", None)
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


def _facts(cik):
    """companyconcept が空を返す社の逃げ道。companyfacts を1本引いて Goodwill を拾う。
    （3〜4MB あるので**第一手には使わない**——空が返った社だけ）"""
    u = "https://data.sec.gov/api/xbrl/companyfacts/CIK%010d.json" % cik
    for i in range(3):
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                u, headers=dict(HDRS, **{"Accept-Encoding": "gzip"})), timeout=180)
            b = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                import gzip
                b = gzip.decompress(b)
            j = json.loads(b)
            f = j.get("facts", {})
            node = (f.get("us-gaap", {}) or {}).get("Goodwill") or (f.get("ifrs-full", {}) or {}).get("Goodwill")
            if not node:
                # 総資産は在るのに のれんが無い＝のれんを報告していない（上限の不等式）
                has_assets = any((f.get(tx, {}) or {}).get("Assets") for tx in ("us-gaap", "ifrs-full"))
                return ("none", None) if has_assets else ("miss", None)
            units = {k: v for k, v in node.get("units", {}).items() if v}
            if not units:
                return ("miss", None)
            uk = max(units, key=lambda k: len(units[k]))
            m = {}
            for e in units[uk]:
                if e.get("start"):
                    continue
                en = e.get("end")
                if not en:
                    continue
                if en not in m or e.get("filed", "") > m[en][1]:
                    m[en] = (e["val"], e.get("filed", ""))
            return ("ok", {k: v[0] for k, v in m.items()}) if m else ("miss", None)
        except Exception:
            if i == 2:
                return ("miss", None)
            time.sleep(2 ** i)
    return ("miss", None)


def concept(cik):
    """us-gaap と ifrs-full の **両方** を引く。
    ⚠ 絶対のルール7: 片方だけ引いて404を「のれん無し」と読むと、IFRS申告社
    （実測 INFY / IHG / DLO）を **のれんゼロと断定**してしまう。
    「のれん無し」と言ってよいのは **両方の税務分類で404** のときだけ。"""
    sts = []
    for tax in ("us-gaap", "ifrs-full"):
        st, m = _one(cik, tax, "Goodwill")
        if st == "ok":
            return ("ok", m)
        sts.append(st)
        time.sleep(0.12)
    if "empty" in sts:
        # companyconcept が空を返した社は **companyfacts で引き直す**（実測でこちらには在る）
        st, m = _facts(cik)
        if st != "miss":
            return (st, m)
    if not all(x == "none" for x in sts):
        return ("miss", None)
    # ⚠ 両方404でも、まだ「のれんが無い」とは言えない——**そもそも XBRL でタグ付けしていない**
    #   申告社かもしれない（20-F は細目タグ付けの歴史が浅い）。総資産という
    #   どの申告にも必ず在る項目で「この社はタグ付けしている」ことを先に確かめる。
    #   タグ付けしているのに Goodwill が一度も無い＝のれんは報告される行に存在しない、
    #   という**上限の不等式**でだけ 0 と断定してよい（CLAUDE.md の IRMD/TSM と同じ作法）。
    for tax in ("us-gaap", "ifrs-full"):
        st, _ = _one(cik, tax, "Assets")
        time.sleep(0.12)
        if st == "ok":
            return ("none", None)
    return ("miss", None)


def at(m, target):
    best = None
    for s, v in m.items():
        try:
            dd = abs((d2(s) - target).days)
        except Exception:
            continue
        if dd <= WIN and (best is None or dd < best[0]):
            best = (dd, v, s)
    return best


def main():
    write = "--write" in sys.argv
    only = None
    if "--only" in sys.argv:
        only = {x.strip().upper() for x in sys.argv[sys.argv.index("--only") + 1].split(",")}
    sic = json.load(open(os.path.join(BASE, "out/_sic_cache.json")))
    # _sic_cache は米国申告社だけ。20-F の外国申告社（ASML/RELX/TSM…）は SEC の
    # company_tickers.json にしか居ないので、**足りない分だけ**そこから補う
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
                # ⚠ ここを黙って空のまま進めると、外国申告社の空欄理由が
                #   「SECに提出していない社」という**嘘**になる（実測で429を踏んだ）
                print("! company_tickers.json を引けなかった:", e)
                try:
                    cikx = json.load(open(cpath))
                    print("  → out/_cik_tickers.json（前回の控え）を使う")
                except Exception:
                    print("  ⚠ 控えも無い。外国申告社の判定ができないので中止する")
                    sys.exit(2)
            else:
                time.sleep(3 * (i + 1))
    files = sorted(glob.glob(os.path.join(BASE, "out/*_gate_pack.json")))
    rows, skip_jp, changed = [], 0, 0
    for f in files:
        t = os.path.basename(f).replace("_gate_pack.json", "")
        if only and t.upper() not in only:
            continue
        d = json.load(open(f))
        rd = (d.get("_meta") or {}).get("reportDate")
        cik = (sic.get(t) or {}).get("cik") or cikx.get(t.upper())
        if not cik or not rd:
            # 絶対のルール8: 空欄の理由は必ず _meta.nulls に書く（書かないと
            # 「測っていない」と「測って0」が台帳の上で同じ見た目になる）
            skip_jp += 1
            why = ("ティッカーからCIKを解決できない（日本株など、SECのXBRLに現れない社）"
                   if not cik else "パックに reportDate が無く基準年を決められない")
            if write and d.get("gwg5") is None and (d.get("_meta", {}).get("nulls", {}) or {}).get("gwg5") != why:
                d.setdefault("_meta", {}).setdefault("nulls", {})["gwg5"] = why
                json.dump(d, open(f, "w"), ensure_ascii=False, indent=1)
                changed += 1
            continue
        fe = d2(rd)
        try:
            base = fe.replace(year=fe.year - 5)
        except ValueError:
            base = fe.replace(year=fe.year - 5, day=28)
        st, m = concept(int(cik))
        time.sleep(0.12)
        def _clear(reason):
            """測れなかったときの後始末。**二つのことを必ずやる**——
            (a) 以前このツールが入れた機械値が「測れない」に変わったら**消す**
                （残すと『測っていない』が『測って0』のまま採点に効き続ける・絶対のルール7）
            (b) **空欄の理由を必ず _meta.nulls に書く**（絶対のルール8）。
                ⚠ 初版は (a) のときだけ書いていたので、一度も値が入らなかった社21件と、
                  古い理由が残ったままの社13件が『理由の記録なし』で残った。"""
            if not write:
                return False
            hit = False
            if d.get("gwg5") is not None and (d.get("_meta", {}).get("provenance", {}) or {}).get("gwg5") == "machine":
                d.pop("gwg5", None)
                d["_meta"].get("evidence", {}).pop("gwg5", None)
                d["_meta"].get("provenance", {}).pop("gwg5", None)
                hit = True
            if d.get("gwg5") is None and (d.setdefault("_meta", {}).setdefault("nulls", {})).get("gwg5") != reason:
                d["_meta"]["nulls"]["gwg5"] = reason
                hit = True
            if hit:
                json.dump(d, open(f, "w"), ensure_ascii=False, indent=1)
            return hit

        if st == "none":
            g, ev = 0.0, "SEC XBRL の us-gaap/Goodwill と ifrs-full/Goodwill が**どちらも404**（かつ総資産は XBRL で申告済＝タグ付けしている社）＝のれんを一度も報告していない→5年でのれんは増えていない (gwg5=0)"
        elif st == "miss":
            changed += 1 if _clear("SECからのれんの系列を採取できなかった") else 0
            rows.append((t, None, "採取失敗")); continue
        else:
            a, b = at(m, fe), at(m, base)
            if a is None or b is None:
                r_ = "審査年(%s)または基準年(%s)の前後45日に のれんの instant が無い" % (fe, base)
                changed += 1 if _clear(r_) else 0
                rows.append((t, None, r_)); continue
            if b[1] <= 0:
                g = 0.0 if a[1] <= 0 else None
                if g is None:
                    r_ = "基準年ののれんが0で審査年は正＝増加率が定義できない（0からの増加）"
                    changed += 1 if _clear(r_) else 0
                    rows.append((t, None, r_)); continue
                ev = "のれん %s %.0f → %s %.0f（いずれも0）→ gwg5=0" % (b[2], b[1], a[2], a[1])
            else:
                g = a[1] / b[1] - 1.0
                ev = "のれん %s %.0f百万$ → %s %.0f百万$ ＝ %+.1f%%（SEC XBRL の Goodwill 系列: companyconcept／空なら companyfacts）" % (
                    b[2], b[1] / 1e6, a[2], a[1] / 1e6, 100 * g)
        old = d.get("gwg5")
        rows.append((t, g, ev))
        if write and (old is None or abs((old or 0) - g) > 1e-9):
            d["gwg5"] = round(g, 4)
            d.setdefault("_meta", {}).setdefault("evidence", {})["gwg5"] = ev
            d["_meta"].setdefault("provenance", {})["gwg5"] = "machine"
            json.dump(d, open(f, "w"), ensure_ascii=False, indent=1)
            changed += 1
    ok = [r for r in rows if r[1] is not None]
    print("対象 %d社（SEC外＝日本株/ADR等 %d社は対象外）／埋まった %d社／空欄 %d社" %
          (len(rows), skip_jp, len(ok), len(rows) - len(ok)))
    from collections import Counter
    def band(g):
        return "none" if g <= 0 else ("mild" if g < 0.43 else ("mid" if g < 1.31 else "heavy"))
    c = Counter(band(r[1]) for r in ok)
    print("  帯: 買収しない %d / 控えめ %d / 中 %d / 大きく買う %d" %
          (c["none"], c["mild"], c["mid"], c["heavy"]))
    if "--list" in sys.argv:
        for t, g, ev in rows:
            print("  %-6s %s  %s" % (t, ("%+.3f" % g) if g is not None else "  空欄", ev))
    print("書き込み %d社%s" % (changed, "" if write else "（--write で反映）"))


if __name__ == "__main__":
    main()
