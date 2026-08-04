#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kessan_calendar.py v1 — 監視銘柄の決算日カレンダー生成器
対象: kanshi_list.json の監視28社(US上場。ASML/TSM/NVMI等ADR含む)。無ければ holdings.json(保有+質80+)にフォールバック。
      日本株コードはAlpha Vantage/SEC推定の対象外ゆえ除外→EDINET/IR経路で別途。
使い方: python kessan_calendar.py            … 3か月先までの決算日を取得
        python kessan_calendar.py NVDA MSFT  … 指定銘柄のみ
出力:  ① 画面に日付順の一覧表
       ② kessan_calendar.ics …… Googleカレンダーに取込→スケジュール連動(全日イベント)
       ③ out/next_earnings.json …… 決算日データ（門内の常時表示は撤去済み→Googleカレンダーで確認）
データ源: Alpha Vantage EARNINGS_CALENDAR(1リクエストで全社分・無料枠で十分)。
          鍵(av_key.txt / ccf/av_key.txt / 環境変数AV_KEY)が無ければ
          SEC提出履歴から「昨年同期＋365日」で推定(src=est、?付き表示)。
"""
import json, re, sys, os, csv, io, time, urllib.request
from datetime import date, datetime

EMAIL = "fortis5280@gmail.com"
HOLD_PATHS = ["./holdings.json", "./ccf/holdings.json",
              "/content/drive/MyDrive/ccf/holdings.json"]
KANSHI_PATHS = ["./kanshi_list.json", "./ccf/kanshi_list.json",
                "/content/drive/MyDrive/ccf/kanshi_list.json"]
KEY_PATHS  = ["./av_key.txt", "./ccf/av_key.txt",
              "/content/drive/MyDrive/ccf/av_key.txt"]
OUT_JSON = "out/next_earnings.json"
OUT_ICS  = "kessan_calendar.ics"
HDRS = {"User-Agent": f"hachimon-kessan {EMAIL}"}

def get(url):
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
    time.sleep(0.15)
    return b.decode("utf-8", "ignore")

def is_jp(t):
    """日本株コード(4-5桁数字・末尾.Tも許容)。Alpha Vantage/SEC推定は米国のみ"""
    return bool(re.fullmatch(r"\d{4,5}(?:\.T)?", t))

def _load_hold_elite():
    """◆保有 と ★質80+ の実体を読む（2026-08-04是正・R10）。
    旧実装は kanshi_list.json 経路で hold=cfg['holdings']（存在しないキー＝常に空）・
    elite=監視全員 としており、**◆が一度も付かず★が全員に付く**＝マークが無意味化していた。
    ◆は holdings.json（kessan_check.py と同じ正本）、★は out/score_all.json の実測Ω(s>=80) から採る。
    score_all が無ければ★は付けない——判定不能を「全員★」と偽らない。"""
    hold, elite = set(), set()
    for p in HOLD_PATHS:
        if os.path.exists(p):
            try:
                cfg = json.load(open(p, encoding="utf-8"))
                hold = {t.strip().upper() for t in (cfg.get("holdings") or []) if t.strip()}
            except Exception:
                pass
            break
    try:
        sa = json.load(open("out/score_all.json", encoding="utf-8"))
        elite = {str(r.get("t", "")).upper() for r in sa if (r.get("s") or 0) >= 80}
    except Exception:
        pass
    return hold, elite

def load_targets():
    """決算日カレンダーの対象＝監視の正本リスト。優先: kanshi_list.json(監視セット・キーは list)。
       無ければ holdings.json(保有+質80+)。日本株コードはAlpha Vantage/SEC推定の
       対象外ゆえ除外し注記（日本株の決算日は EDINET/IR 経路で別途）"""
    for p in KANSHI_PATHS:
        if os.path.exists(p):
            cfg = json.load(open(p, encoding="utf-8"))
            # 2026-07-30 是正: make_kanshi.py が書くキーは **"list"**。ここは "tickers" しか
            #   読んでおらず、ファイルが在ってパースも通るのに中身がゼロ件になり、**黙って
            #   holdings.json へフォールバック**していた（画面には正常な行に見える
            #   「監視リスト: ./holdings.json → 保有3…」だけが出る）。実害: 監視33社のうち
            #   3社しか点検されず、ADBE/NVDA/MA/APH/IRMD/TSM 等が一度も見られていなかった。
            #   pin(手で足した銘柄)も対象に含める。旧キー "tickers" は後方互換で残す。
            tk = [t.strip().upper() for t in
                  ((cfg.get("list") or cfg.get("tickers") or []) + (cfg.get("pin") or []))
                  if t.strip()]
            tk = sorted(set(tk))
            us = [t for t in tk if not is_jp(t)]
            jp = [t for t in tk if is_jp(t)]
            # 2026-08-04是正(R10): ◆★は監視リストからは決まらない（監視は合併集合で保有/質の
            #   区別を持たない）。holdings.json と score_all.json から実体を引く
            hold, elite = _load_hold_elite()
            if us:
                print(f"監視リスト: {p} → 監視{len(tk)}社（うち米国{len(us)}社の決算日を取得）")
                if jp:
                    print(f"  ※日本株{len(jp)}社は対象外→EDINET/IR経路へ: {jp}")
                return sorted(set(us)), hold, elite
            # フォールバックは**黙って**行わない——上の事故は「静かな縮退」が原因だった
            print(f"⚠ {p} は在るが点検可能な銘柄が0件（キー list/tickers/pin を確認）→ holdings.json へ退避")
    for p in HOLD_PATHS:
        if os.path.exists(p):
            cfg = json.load(open(p, encoding="utf-8"))
            hold  = [t.strip().upper() for t in (cfg.get("holdings") or []) if t.strip()]
            elite = [t.strip().upper() for t in (cfg.get("elite") or []) if t.strip()]
            if not elite:
                elite = [t.strip().upper() for t in (cfg.get("watch") or []) if t.strip()]
            tg = [t for t in sorted(set(hold) | set(elite)) if not is_jp(t)]
            if tg:
                print(f"監視リスト: {p} → 保有{len(hold)} + 質80+{len(elite)} = {len(tg)}銘柄")
                return tg, set(hold), set(elite)
    print("kanshi_list.json / holdings.json なし → 引数で銘柄を指定")
    return [], set(), set()

def av_key():
    for p in KEY_PATHS:
        if os.path.exists(p):
            k = open(p).read().strip()
            if k: return k
    return os.environ.get("AV_KEY", "").strip() or None

def from_alpha_vantage(targets, key):
    """EARNINGS_CALENDAR: 全社CSVを1回で取得し監視銘柄だけ抽出"""
    url = f"https://www.alphavantage.co/query?function=EARNINGS_CALENDAR&horizon=3month&apikey={key}"
    txt = get(url)
    out = {}
    rd = csv.DictReader(io.StringIO(txt))
    for row in rd:
        s = (row.get("symbol") or "").upper()
        d = (row.get("reportDate") or "").strip()
        if s in targets and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            if s not in out or d < out[s]:   # 最も近い日
                out[s] = d
    return out

def cik_map():
    j = json.loads(get("https://www.sec.gov/files/company_tickers.json"))
    return {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in j.values()}

def est_from_sec(t, cmap):
    """推定: 直近提出(10-Q/10-K)のperiodOfReportに約1四半期+提出ラグを足すのではなく、
       昨年の『次に来るはずの提出』の提出日+365日で近似する。"""
    cik = cmap.get(t.upper())
    if not cik: return None
    j = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
    r = j["filings"]["recent"]
    dates = []
    for i, f in enumerate(r["form"]):
        if f in ("10-Q", "10-K", "20-F"):
            try: dates.append(date.fromisoformat(r["filingDate"][i]))
            except Exception: pass
    if not dates: return None
    today = date.today()
    # 昨年の提出日のうち「+365すると今日以降になる」最も近いもの
    cands = sorted(d.toordinal()+365 for d in dates)
    for o in cands:
        if o >= today.toordinal():
            return date.fromordinal(o).isoformat()
    return None

def build(targets, hold, elite):
    items = []
    key = av_key()
    av = {}
    if key:
        try:
            av = from_alpha_vantage(set(targets), key)
            print(f"Alpha Vantage: {len(av)}/{len(targets)} 銘柄の決算日を取得")
        except Exception as e:
            print(f"Alpha Vantage失敗({e}) → SEC推定に切替")
    missing = [t for t in targets if t not in av]
    if missing:
        try:
            cmap = cik_map()
            for t in missing:
                try:
                    d = est_from_sec(t, cmap)
                    if d: av[t] = d; items_src_est.add(t)
                except Exception: pass
        except Exception as e:
            print(f"SEC推定も失敗: {e}")
    for t in sorted(av):
        items.append({"t": t, "date": av[t],
                      "src": "est" if t in items_src_est else "av",
                      "hold": t in hold, "elite": t in elite})
    items.sort(key=lambda x: x["date"])
    return items

items_src_est = set()

def write_ics(items):
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CCF//kessan-calendar//JP"]
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    for it in items:
        d = it["date"].replace("-", "")
        mark = ("◆" if it["hold"] else "") + ("★" if it["elite"] else "")
        est = "（推定)" if it["src"] == "est" else ""
        L += ["BEGIN:VEVENT",
              f"UID:{it['t']}-{d}@ccf-gate",
              f"DTSTAMP:{stamp}",
              f"DTSTART;VALUE=DATE:{d}",
              f"SUMMARY:決算: {it['t']} {mark}{est}",
              "DESCRIPTION:壊れない複利の門・四半期点検の対象。決算後は「四半期点検の依頼文」で点検。株価では動かない。",
              "END:VEVENT"]
    L.append("END:VCALENDAR")
    open(OUT_ICS, "w", newline="", encoding="utf-8").write("\r\n".join(L) + "\r\n")

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if re.fullmatch(r"[A-Za-z][A-Za-z.\-]{0,7}", a)]
    if args:
        targets, hold, elite = [a.upper() for a in args], set(), set()
    else:
        targets, hold, elite = load_targets()
    if not targets: sys.exit(0)
    items = build(targets, hold, elite)
    print(f"\n=== 決算カレンダー {date.today()} ===")
    today = date.today()
    for it in items:
        dd = (date.fromisoformat(it["date"]) - today).days
        mark = ("◆" if it["hold"] else " ") + ("★" if it["elite"] else " ")
        est = "?" if it["src"] == "est" else " "
        print(f"  {it['t']:<6}{mark} {it['date']} (D-{dd}){est}")
    os.makedirs("out", exist_ok=True)
    json.dump({"generated": str(today), "items": items},
              open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_ics(items)
    print(f"\n→ {OUT_ICS}（Googleカレンダーに取込=スケジュール連動） / {OUT_JSON}（決算日データ）")
