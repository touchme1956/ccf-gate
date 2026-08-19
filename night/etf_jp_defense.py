# night/etf_jp_defense.py — 日本で買える「防衛・航空」の器を測る（2026-08-19新設）
#
# 【何のための道具か】
#   「防衛航空で日本で買えるで一番いいのは？」への材料。**判定はしない**
#   ——ETFの選定は門の外（DCA側）で、門Ωの採点・四関門・売却規律にはいっさい触れない。
#
# 【候補の見つけ方】東証の全ETF/ETNのコードを掃いて longName にキーワードが当たるものを採った
#   （2200-2299 / 1300-1699 / 2500-2899 / 100A-699A の 393本を実測）。**思い出しで書かない**
#
# 【★この道具の答えは「測れない」になる公算が高い】
#   4本とも 2025-11 以降の上場で、履歴が1〜9ヶ月しかない。
#   この台帳は「180日未満は年率換算しない」（audit_er_realized）と決めているので、
#   **年率にはせず累積で出す**。数字がある分だけ空欄より有害になる方が怖い。
#
# 【比較の作法】
#   (a) 円建てで揃える（日本上場は円・米国上場はドル→円）
#   (b) **為替中立も併記**——円安の追い風を混ぜたまま比べると自分で作った偏りを発見と誤認する
#   (c) 月ラベルは gmtoffset でローカル月に揃える（etf_jp.py で踏んだ13例目の再演を防ぐ）
#   (d) 未記録の分割は整数比に近いときだけ直す（etf_jp.repair）
#
# 実行: python3 night/etf_jp_defense.py [--json]
# 出力: out/etf_jp_defense.json
import json, os, sys, importlib.util

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out", "etf_jp_defense.json")

_s = importlib.util.spec_from_file_location("etf_jp", os.path.join(BASE, "night", "etf_jp.py"))
_m = importlib.util.module_from_spec(_s); sys.modules["etf_jp"] = _m; _s.loader.exec_module(_m)
fetch, repair = _m.fetch, _m.repair

# 東証の全掃きで当たった4本（キーワード: defen/aero/space/security/military/arms/shield/frontier）
JP = {
    "466A.T": "Global X 防衛テック ETF（世界・ex-Japan相当）",
    "513A.T": "Global X 日本防衛テック ETF（日本株）",
    "498A.T": "欧州防衛・航空 ETN（⚠ETN＝発行体の信用リスク）",
    "610A.T": "Global X 宇宙テック Top10 ETF（ex-Japan）",
}
US = {"XAR": "SPDR 航空防衛(等ウェイト)", "ITA": "iShares 米航空防衛",
      "PPA": "Invesco 航空防衛", "SHLD": "Global X Defense Tech (米国上場)",
      "SMH": "半導体", "SPY": "S&P500"}


def cum(ser, a, b, fx=None):
    ks = sorted(k for k in ser if a <= k <= b)
    if fx:
        ks = [k for k in ks if k in fx]
    if len(ks) < 2:
        return None
    v0 = ser[ks[0]] * (fx[ks[0]] if fx else 1.0)
    v1 = ser[ks[-1]] * (fx[ks[-1]] if fx else 1.0)
    n = (int(ks[-1][:4]) - int(ks[0][:4])) * 12 + (int(ks[-1][5:]) - int(ks[0][5:]))
    return {"累積": round(v1 / v0 - 1, 4), "月数": n, "窓": f"{ks[0]}→{ks[-1]}"}


def rets(ser, fx=None):
    ks = sorted(ser if not fx else [k for k in ser if k in fx])
    v = {k: ser[k] * (fx[k] if fx else 1.0) for k in ks}
    return {ks[i]: v[ks[i]] / v[ks[i - 1]] - 1 for i in range(1, len(ks))}


def corr(x, y, minn=5):
    ks = sorted(set(x) & set(y))
    if len(ks) < minn:
        return None
    n = len(ks)
    mx = sum(x[k] for k in ks) / n; my = sum(y[k] for k in ks) / n
    sxy = sum((x[k] - mx) * (y[k] - my) for k in ks)
    sxx = sum((x[k] - mx) ** 2 for k in ks); syy = sum((y[k] - my) ** 2 for k in ks)
    if sxx <= 0 or syy <= 0:
        return None
    return round(sxy / (sxx * syy) ** 0.5, 3), n


def build():
    out = {"asof": "2026-08-19",
           "問い": "防衛・航空で日本で買える器のうち一番いいのはどれか",
           "注意": ["ETFの選定は門の外（DCA側）。この道具は判定を持たない",
                    "★4本とも上場が新しく、年率換算しない（180日未満は年率にしない規約の精神）",
                    "投資信託(非上場)はYahooに系列が無く**この道具では測れない**＝穴として明示"]}
    fx = fetch("JPY=X")
    ser, rep = {}, {}
    for t in list(JP) + list(US):
        s = fetch(t)
        if not s:
            out.setdefault("取得できず", []).append(t)
            continue
        s, f = repair(s)
        if f:
            rep[t] = f
        ser[t] = s
    out["分割の修理"] = rep or "なし"

    # 各候補の設定来（円建て）と、同じ窓の対照
    rows = {}
    for t, nm in JP.items():
        if t not in ser:
            continue
        ks = sorted(ser[t])
        a, b = ks[0], ks[-1]
        row = {"名前": nm, "上場": a, "円建て": cum(ser[t], a, b)}
        peers = {}
        for u, un in US.items():
            if u not in ser:
                continue
            j = cum(ser[u], a, b, fx)      # 円建て
            n = cum(ser[u], a, b)          # 為替中立（現地通貨）
            if j and n:
                peers[u] = {"名前": un, "円建て": j["累積"], "為替中立": n["累積"]}
        row["同じ窓の米国上場（対照）"] = dict(sorted(peers.items(), key=lambda z: -z[1]["円建て"]))
        # 円建てどうしの差
        if row["円建て"]:
            row["円建てで勝った相手"] = [u for u, v in peers.items() if row["円建て"]["累積"] > v["円建て"]]
        rows[t] = row
    out["候補"] = rows

    # ★466A は SHLD（米国上場 Global X Defense Tech）と同じ中身か——相関で確かめる
    if "466A.T" in ser and "SHLD" in ser:
        r1 = rets(ser["466A.T"])
        r2 = rets(ser["SHLD"], fx)   # 円建てに揃えて比べる（466Aは円建てなので）
        c = corr(r1, r2)
        out["★466A は SHLD の円建て版か"] = {
            "月次相関(円建てどうし)": (c[0] if c else None), "n": (c[1] if c else 0),
            "読み方": "1.0に近ければ同じ中身＝**円で買えるSHLD**。低ければ別物",
        }
        c2 = corr(r1, rets(ser["SHLD"]))
        out["★466A は SHLD の円建て版か"]["参考: SHLDを現地通貨のままにした相関"] = c2[0] if c2 else None

    # 日本株の防衛(513A) と 世界の防衛(466A) は別物か
    if "513A.T" in ser and "466A.T" in ser:
        c = corr(rets(ser["513A.T"]), rets(ser["466A.T"]))
        out["日本の防衛 vs 世界の防衛"] = {"月次相関": (c[0] if c else None), "n": (c[1] if c else 0)}


    # ---- ★網の門(ami.html)の規約をそのまま当てる（判定を新しく作らない）
    #   キル: レバレッジ／純資産100億円未満／**設定3年未満**／経費率0.75%超
    import datetime
    NOW = datetime.date(2026, 8, 19)
    gate = {}
    for t in list(JP) + list(US):
        if t not in ser:
            continue
        ks = sorted(ser[t])
        y0, m0 = int(ks[0][:4]), int(ks[0][5:])
        age = round(((NOW.year - y0) * 12 + (NOW.month - m0)) / 12.0, 1)
        kills = []
        if age < 3:
            kills.append(f"設定から {age}年 < 3年——実績が無い")
        gate[t] = {"設定からの年数": age, "網の門のキル": kills or "なし（年数の条件は通る）",
                   "★未測定": "純資産と経費率はYahooから採れない＝キルの残り2つは未判定"}
    out["★網の門(ami.html)の規約を当てる"] = gate

    out["限界"] = [
        "★履歴が1〜9ヶ月＝**どれも実績で選べない**。今日の答えは『測れない』",
        "円建ての比較には円安の追い風が入る（為替中立を必ず併記した）",
        "経費率はYahooから採れない——目論見書で必ず確認する（コストは唯一 確実に複利へ効く数字）",
        "498A は ETN＝発行体の信用リスクを負う（ETFとは別の器）",
        "投資信託(非上場)は測れていない＝この一覧は『上場しているもの』だけ",
        "取扱の有無は証券会社ごとに違う——米国ETFが買えるかは各社の一覧で確認",
    ]
    return out


if __name__ == "__main__":
    o = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(o, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(o, ensure_ascii=False, indent=1))
