# night/filing_behavior.py — 「提出書類の振る舞い」の採取（2026-08-12新設）
#
# 目的: 歴史検証の5系統目。既存の4系統（財務比率 retro_features2 / 株価・値動き retro_path・
#       hist_val / 本文のキーワード retro_fulltext / 業種 retro_sic）はいずれも
#       「会社が報告した数字」「市場が付けた値段」「本文の語」だが、
#       **会社がどう振る舞ったか（いつ・何を・どれだけ提出したか）** は一度も測っていない。
#       SEC submissions のメタデータだけから14系統を作る。
#
# 事前登録: out/filing_behavior_prereg.json（結果を見る前にコミット済み・4b8b237）
#
# look-ahead 防止: すべて filingDate <= asof_date で切る。
#       年ラベルではなく **提出日** で切るので、12月決算社のFY2018=2019年2月提出は構造的に入らない
#       （retro_build_readlist が確立した作法）。
#
# 欠測の扱い（ルール7）:
#   - 窓内に10-Kが1件も無い → 10-K系（lag10k/lag_d/sz/szchg/amend）は null。0と書かない
#   - カウント系（nt/nonrel/audchg/exec5/shelf/d13d/f4/k8）は **窓内の提出が1件でもあれば0が事実**。
#     提出が一件も取れなかった社は全欄 null にして fetched=False を立てる
#   - 8-K の items が空文字の提出は「項目不明」として items_blank に数える（0件と断定しない）
#
# レート: グローバルなペーサーで全リクエスト開始の間隔を 0.12 秒以上に強制（<= 毎秒8.3）。
#         SECの上限10req/sを並列でも構造的に超えられない。
# 途中経過: 50社ごとに print、100社ごとに .partial.json へチェックポイント（再実行で続きから）
#
# 実行: python3 night/filing_behavior.py 2018     （out/filing_behavior_2018.json）
#       python3 night/filing_behavior.py 2013     （out/filing_behavior_2013.json）

import datetime
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(BASE, "out")
EMAIL = "fortis5280@gmail.com"
HDRS = {"User-Agent": f"ccf-gate {EMAIL}", "Accept-Encoding": "gzip, deflate"}

VINTAGES = {
    2018: {"asof": "2018-07-01", "returns": "retro_returns_2018.json", "cikmap": "retro_sic.json"},
    2013: {"asof": "2013-07-01", "returns": "retro_returns_2013_all.json", "cikmap": "retro_cohort_2013.json"},
}

_pace_lock = threading.Lock()
_last = [0.0]
MIN_GAP = 0.12


def paced_get(url, tries=3):
    for a in range(tries):
        with _pace_lock:
            gap = time.time() - _last[0]
            if gap < MIN_GAP:
                time.sleep(MIN_GAP - gap)
            _last[0] = time.time()
        try:
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    import gzip

                    raw = gzip.decompress(raw)
                return json.loads(raw.decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1.5 * (a + 1))
        except Exception:
            time.sleep(1.5 * (a + 1))
    return None


def d(s):
    return datetime.date.fromisoformat(s)


def load_cikmap(vint):
    """ticker -> cik。2018は retro_sic.json、2013は retro_cohort_2013.json。"""
    path = os.path.join(OUTDIR, VINTAGES[vint]["cikmap"])
    rows = json.load(open(path))["rows"]
    m = {}
    for r in rows:
        t, c = r.get("ticker"), r.get("cik")
        if t and c:
            m.setdefault(t, int(c))
    return m


def collect(cik, asof):
    """1社ぶんの提出履歴を asof まで集めて特徴量にする。"""
    z = str(cik).zfill(10)
    sub = paced_get(f"https://data.sec.gov/submissions/CIK{z}.json")
    if not sub:
        return None
    f = sub.get("filings", {})
    recent = f.get("recent", {})
    cols = ["form", "filingDate", "reportDate", "items", "size"]
    rows = []

    def push(block):
        n = len(block.get("form", []))
        for i in range(n):
            fd = block["filingDate"][i]
            if fd > asof:
                continue
            rows.append(
                {
                    "form": block["form"][i],
                    "fd": fd,
                    "rd": block.get("reportDate", [""] * n)[i] or "",
                    "items": block.get("items", [""] * n)[i] or "",
                    "size": block.get("size", [0] * n)[i] or 0,
                }
            )

    if recent.get("form"):
        push(recent)

    # 古い綴り。窓（asof-6.5年 .. asof）に掛かるものだけ取る
    lo = (d(asof) - datetime.timedelta(days=int(365.25 * 6.5))).isoformat()
    first_seen = None
    for meta in f.get("files", []) or []:
        ff, ft = meta.get("filingFrom", ""), meta.get("filingTo", "")
        if ff and (first_seen is None or ff < first_seen):
            first_seen = ff
        if ft and ft < lo:
            continue
        if ff and ff > asof:
            continue
        blk = paced_get(f"https://data.sec.gov/submissions/{meta['name']}")
        if blk:
            push(blk)

    if not rows:
        return {"fetched": False, "sic": sub.get("sic"), "name": sub.get("name")}

    rows.sort(key=lambda r: r["fd"], reverse=True)
    a = d(asof)
    w5 = (a - datetime.timedelta(days=1826)).isoformat()   # 5年
    w1 = (a - datetime.timedelta(days=365)).isoformat()    # 1年

    # 会社の年齢: 古い綴りの filingFrom か、取れた提出の最古
    oldest = min(r["fd"] for r in rows)
    if first_seen and first_seen < oldest:
        oldest = first_seen
    age = round((a - d(oldest)).days / 365.25, 2)

    in5 = [r for r in rows if r["fd"] >= w5]
    in1 = [r for r in rows if r["fd"] >= w1]

    def cnt(seq, pred):
        return sum(1 for r in seq if pred(r))

    def has_item(r, code):
        return code in [x.strip() for x in r["items"].split(",") if x.strip()]

    k8_all = [r for r in in5 if r["form"] in ("8-K", "8-K/A")]
    items_blank = cnt(k8_all, lambda r: not r["items"].strip())

    tens = [r for r in rows if r["form"] in ("10-K", "10-KSB", "10-K405") and r["rd"]]
    lag10k = lag_d = sz = szchg = None
    if tens:
        lag10k = (d(tens[0]["fd"]) - d(tens[0]["rd"])).days
        sz = tens[0]["size"] or None
        if len(tens) >= 2 and tens[1]["size"]:
            szchg = round((tens[0]["size"] / tens[1]["size"] - 1) * 100, 1)
        if len(tens) >= 3:
            lag_d = lag10k - (d(tens[2]["fd"]) - d(tens[2]["rd"])).days

    return {
        "fetched": True,
        "sic": sub.get("sic"),
        "name": sub.get("name"),
        "n_filings_5y": len(in5),
        "age_yrs": age,
        "lag10k": lag10k,
        "lag_d": lag_d,
        "sz": sz,
        "szchg": szchg,
        "n10k_5y": cnt(in5, lambda r: r["form"] in ("10-K", "10-KSB", "10-K405")),
        "amend": cnt(in5, lambda r: r["form"] == "10-K/A"),
        "nt": cnt(in5, lambda r: r["form"].startswith("NT ")),
        "nonrel": cnt(k8_all, lambda r: has_item(r, "4.02")),
        "audchg": cnt(k8_all, lambda r: has_item(r, "4.01")),
        "exec5": cnt(k8_all, lambda r: has_item(r, "5.02")),
        "k8": round(len(k8_all) / 5.0, 2),
        "items_blank": items_blank,
        "f4": cnt(in1, lambda r: r["form"] == "4"),
        "shelf": cnt(in5, lambda r: r["form"].startswith("424B") or r["form"] in ("S-1", "S-3", "S-3ASR", "S-1/A", "S-3/A")),
        "d13d": cnt(in5, lambda r: r["form"].startswith("SC 13D")),
    }


def main():
    vint = int(sys.argv[1]) if len(sys.argv) > 1 else 2018
    cfg = VINTAGES[vint]
    asof = cfg["asof"]
    rets = json.load(open(os.path.join(OUTDIR, cfg["returns"])))["rows"]
    cikmap = load_cikmap(vint)
    targets = []
    missing_cik = []
    for r in rets:
        t = r["ticker"]
        if t in cikmap:
            targets.append((t, cikmap[t]))
        else:
            missing_cik.append(t)

    out_path = os.path.join(OUTDIR, f"filing_behavior_{vint}.json")
    part_path = out_path + ".partial"
    done = {}
    if os.path.exists(part_path):
        done = json.load(open(part_path)).get("rows", {})
        print(f"partial から再開: {len(done)}社")

    todo = [(t, c) for t, c in targets if t not in done]
    print(f"asof={asof} 対象{len(targets)}社（未処理{len(todo)}・CIK不明{len(missing_cik)}）")

    n = 0
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(collect, c, asof): t for t, c in todo}
        for fu in as_completed(futs):
            t = futs[fu]
            try:
                res = fu.result()
            except Exception as e:
                res = {"fetched": False, "error": str(e)}
            done[t] = res or {"fetched": False, "error": "no submissions"}
            n += 1
            if n % 50 == 0:
                print(f"  {n}/{len(todo)}")
            if n % 100 == 0:
                json.dump({"rows": done}, open(part_path, "w"))

    ok = sum(1 for v in done.values() if v and v.get("fetched"))
    json.dump(
        {
            "generated": datetime.date.today().isoformat(),
            "asof": vint,
            "asof_date": asof,
            "prereg": "out/filing_behavior_prereg.json",
            "source": "SEC submissions API（filingDate <= asof で切る）",
            "n": len(done),
            "n_fetched": ok,
            "missing_cik": missing_cik,
            "rows": done,
        },
        open(out_path, "w"),
        ensure_ascii=False,
    )
    if os.path.exists(part_path):
        os.remove(part_path)
    print(f"→ {out_path}  採取成功 {ok}/{len(done)}")


if __name__ == "__main__":
    main()
