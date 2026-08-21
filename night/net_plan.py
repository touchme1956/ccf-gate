# night/net_plan.py — 決めた網(ETF)の中身と比率を測る（2026-08-19新設）
#
# 【何のための道具か】
#   ユーザーが決めた網の構成を、この台帳の物差しで測って材料を出す。
#   **判定はしない**——ETFの選定と網/城の比率は門の外（DCA側の決断）で、
#   門Ωの採点・四関門・堀の関門・売却規律にはいっさい触れない。
#
# 【測るもの】
#   (1) 網の門(ami.html)の規約をそのまま当てる（レバレッジ／純資産100億円／設定3年／経費率0.75%）
#   (2) 重ならない窓での実績（設定の新しい本は「測れない」と出す。年率にしない）
#   (3) 加重経費率——**唯一 確実に複利へ効く数字**
#   (4) ルックスルー（城＋網）——1銘柄8%上限は城の中でしか効かないので、束は必ず分解して見る
#   (5) 現行の網との差分
#
# 実行: python3 night/net_plan.py [--net 50] [--json]
# 出力: out/net_plan.json
import json, os, sys, importlib.util, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out", "net_plan.json")

# ★日付は実行時に採る（2026-08-20 是正）。初版は asof も年数も窓の終端も **2026-08-19 を焼き付けて**いた。
#   回転盤に載せた瞬間に、これは「回しても asof が動かない＝盤が永久に緑」になる
#   ——`backfill_machine_evidence.TODAY` が 2026-07-29 のまま固定されて
#   「いつ検算したかが判らない」状態になったのとまったく同じ型。
#   数字を書き写した箇所は必ず陳腐化する。
TODAY = datetime.date.today()
TODAY_S = TODAY.isoformat()
NOW_YM = f"{TODAY.year:04d}-{TODAY.month:02d}"

_s = importlib.util.spec_from_file_location("etf_returns", os.path.join(BASE, "night", "etf_returns.py"))
_m = importlib.util.module_from_spec(_s); sys.modules["etf_returns"] = _m; _s.loader.exec_module(_m)
fetch, cagr, maxdd = _m.fetch, _m.cagr, _m.maxdd

# ★網の顔ぶれと**中の重み**は portfolio.json（人の決定の置き場）から読む。
#   ここに書き写すと必ず割れる（v9.9.65）。読めなければ下の既定へ倒す。
NEW_FALLBACK = ["XLK", "SMH", "GRID", "ITA", "NASA"]


def net_target():
    """(顔ぶれ, {t: 総資産に対する%} or None, 重みの出所) を返す。
    ⚠**一本でも重みが無ければ全体を等分へ倒す**——指定のある本だけ重くすると
      「指定の穴が配分に化ける」（門の ccfNetRows / ccfMcapWeights と同じ作法）。"""
    try:
        t = (json.load(open(os.path.join(BASE, "portfolio.json"), encoding="utf-8")).get("target") or {})
        names = [str(x).strip().upper() for x in (t.get("ami_names") or []) if str(x).strip()]
        if not names:
            return NEW_FALLBACK, None, "既定（portfolio.json に ami_names が無い）"
        w = {str(k).strip().upper(): float(v) for k, v in (t.get("ami_weights") or {}).items()}
        miss = [n for n in names if not w.get(n)]
        if w and not miss:
            return names, {n: w[n] for n in names}, "portfolio.json の target.ami_weights"
        return names, None, ("等分（重みが無い本: " + "・".join(miss) + "）" if miss else "等分（ami_weights が未設定）")
    except Exception:
        return NEW_FALLBACK, None, "既定（portfolio.json が読めない）"


def net_now():
    """**今 実際に持っている網**を portfolio.json から読む。
    ★ここを書き写すと必ず陳腐化する——2026-08-21 まで `OLD=["XLK","QQQ","SMH"]` と
    網59.6%・XLK55/QQQ23/SMH22 が**ハードコード**されていて、保有が
    XLK/SMH/NASA・網30.8% に変わった後も「現行」として古い姿を比較対象に出し続けていた。
    戻り: (顔ぶれ, {t: 網の中での比}, 網の比率%, holdings が無くて積めない本)"""
    try:
        pf = json.load(open(os.path.join(BASE, "portfolio.json"), encoding="utf-8"))
        prof = json.load(open(os.path.join(BASE, "out", "etf_profiles.json"), encoding="utf-8")).get("etfs", {})
        ami = [p for p in pf["positions"] if p.get("sleeve") == "網" and (p.get("value_jpy") or 0) > 0]
        if not ami:
            return [], {}, 0.0, []
        tot = sum(p["value_jpy"] for p in ami)
        names = [p["ticker"] for p in ami]
        w = {p["ticker"]: p["value_jpy"] / tot for p in ami}
        pct = float((pf.get("summary") or {}).get("ami_net_pct") or 0.0)
        # holdings（構成銘柄）が無い本はルックスルーに積めない＝穴として名指しする
        # ⚠ prof が空＝etf_profiles.json が読めなかった、を「全本に穴がある」と言わない（ルール7）。
        #    実際 2026-08-21 に キーを "funds"（正しくは "etfs"）と書いて、カバー率100%のすぐ隣で
        #    「積めない本: XLK・SMH・NASA」というもっともらしい嘘を出した。
        hole = ([t for t in names if not (prof.get(t) or {}).get("h")] if prof
                else ["（etf_profiles.json が読めず判定できない）"])
        return names, w, pct, hole
    except Exception:
        return [], {}, 0.0, []


NEW, NET_W, NET_W_SRC = net_target()
OLD, OLD_W, OLD_PCT, OLD_HOLE = net_now()          # 現行＝portfolio.json の実測
BENCH = ["SPY", "VT"]
# 網の門(ami.html)のキル。**新しい定数を作らない**——ami.html:290-293 と同じ数字
KILL_AUM_OKU = 100          # 億円
KILL_AGE_Y = 3
KILL_ER_PCT = 0.75
USDJPY_FOR_AUM = 158.0      # 純資産のキルは円建ての線なので換算が要る（概算・判定の境目から遠い）

# 重ならない窓（GRID の設定 2009-11 以降で3つ取れる）。**最後の窓の終端は今月**
#   ——固定にすると再実行しても測る範囲が広がらず、盤だけ緑で中身が凍る。
SAME_START = "2010-08"
def windows():
    return [("2010-08", "2015-08"), ("2015-08", "2020-08"), ("2020-08", NOW_YM)]


def build(net_pct):
    prof = json.load(open(os.path.join(BASE, "out", "etf_profiles.json")))["etfs"]
    out = {"asof": TODAY_S,
           "決定": {"網": NEW, "網の比率": net_pct, "城の比率": 100 - net_pct,
                    "網の中の重み": (NET_W if NET_W else "未指定——等ウェイトで計算した"),
                    "重みの出所": NET_W_SRC,
                    "重みの合計": (round(sum(NET_W.values()), 4) if NET_W else None)},
           "注意": ["ETFの選定と網/城の比率は門の外（DCA側）。この道具は判定を持たない",
                    "経費率は唯一 確実に複利へ効く数字。リターンは推定だが費用は確定"]}

    # ---- (1) 網の門の規約
    gate = {}
    for t in NEW:
        p = prof.get(t)
        if not p:
            gate[t] = {"error": "holdings 未取得"}
            continue
        y0, m0 = int(p["inc"][:4]), int(p["inc"][5:7])
        age = round(((TODAY.year - y0) * 12 + (TODAY.month - m0)) / 12.0, 1)
        aum_oku = p["aum"] * USDJPY_FOR_AUM / 1e8
        kills = []
        if age < KILL_AGE_Y:
            kills.append(f"設定から {age}年 < 3年——実績が無い")
        if aum_oku < KILL_AUM_OKU:
            kills.append(f"純資産 {aum_oku:.0f}億円 < 100億円——償還リスク")
        if p["er"] * 100 > KILL_ER_PCT:
            kills.append(f"経費率 {p['er']*100:.3f}% > 0.75%")
        gate[t] = {"設定": p["inc"], "年数": age, "純資産(億円)": round(aum_oku),
                   "経費率%": round(p["er"] * 100, 3), "実効銘柄数": p.get("eff_n"),
                   "キル": kills or "なし"}
    out["網の門(ami.html)の規約"] = gate

    # ---- (3) 加重経費率
    # ★重みは決定どおり（無ければ等分）。**加重経費率は唯一 確実に複利へ効く数字**なので、
    #   等分で出した数字を「決定の経費率」として出さない。
    rel = (NET_W if NET_W else {t: 1.0 for t in NEW})
    _rw = sum(rel.get(t, 0) for t in NEW if t in prof) or 1.0
    er_new = sum(prof[t]["er"] * rel.get(t, 0) for t in NEW if t in prof) / _rw
    er_old = None
    try:
        pf = json.load(open(os.path.join(BASE, "portfolio.json")))
        amis = [p for p in pf["positions"] if p["sleeve"] == "網"]
        s = sum(p["value_jpy"] for p in amis if p["ticker"] in prof)
        er_old = sum(prof[p["ticker"]]["er"] * p["value_jpy"] for p in amis if p["ticker"] in prof) / s
    except Exception:
        pass
    out["加重経費率"] = {("新（%s）" % NET_W_SRC): round(er_new * 100, 4),
                        ("現行（%s）" % ("/".join(OLD) if OLD else "保有なし")):
                            (round(er_old * 100, 4) if er_old else None),
                        "20年で終価に効く分": f"新 約{(1-(1-er_new)**20)*100:.1f}% / 現行 約{(1-(1-er_old)**20)*100:.1f}%" if er_old else None}

    # ---- (2) 窓
    ser = {t: fetch(t) for t in NEW + OLD + BENCH}
    ser = {k: v for k, v in ser.items() if v}
    wins = {}
    for a, b in windows():
        row = {}
        for t, s in ser.items():
            c = cagr(s, a, b)
            if c is not None:
                row[t] = round(c, 4)
        na = [t for t in NEW if t not in row]
        wins[f"{a}→{b}"] = {"年率": dict(sorted(row.items(), key=lambda z: -z[1])),
                            "測れない": na}
    out["重ならない窓"] = wins
    same = {}
    for t, s in ser.items():
        c = cagr(s, SAME_START, NOW_YM)
        if c is not None:
            same[t] = {"年率": round(c, 4), "最大下落": maxdd(s, SAME_START, NOW_YM)}
    out[f"同じ窓 {SAME_START}→{NOW_YM}（GRIDの設定以降）"] = dict(sorted(same.items(), key=lambda z: -z[1]["年率"]))

    # ---- (4) ルックスルー
    pf = json.load(open(os.path.join(BASE, "portfolio.json")))
    tot = pf["total_jpy"]
    castle = {p["ticker"]: p["value_jpy"] / tot for p in pf["positions"] if p["sleeve"] == "城"}
    cs = sum(castle.values())
    def look(nets, net_w):
        agg, cov = {}, 0.0
        for t, v in castle.items():                      # 城は現在の顔ぶれを比例で (100-net) へ
            agg[t] = agg.get(t, 0) + v / cs * (1 - net_w)
            cov += v / cs * (1 - net_w)
        for t, ww in nets.items():
            p = prof.get(t)
            if not p:
                continue
            for sym, x in p["h"]:
                agg[sym] = agg.get(sym, 0) + net_w * ww * x
                cov += net_w * ww * x
        return agg, cov
    _rs = sum(rel.get(t, 0) for t in NEW) or 1.0
    for nm, nets in (("新（%s／%s）" % ("/".join(NEW), NET_W_SRC), {t: rel.get(t, 0) / _rs for t in NEW}),
                     ("現行（%s ＝ portfolio.json の実測）" % "/".join(
                         "%s%.0f" % (t, OLD_W[t] * 100) for t in OLD) if OLD else "現行（保有なし）", OLD_W)):
        nw = net_pct / 100.0 if nm.startswith("新") else OLD_PCT / 100.0
        agg, cov = look(nets, nw)
        SEMI = {"NVDA","TSM","AVGO","AMD","ASML","MU","AMAT","LRCX","TXN","ADI","KLAC","INTC","MRVL",
                "QCOM","CDNS","SNPS","MPWR","TER","NXPI","STM","ARM","ALAB","MCHP","ON","SWKS",
                "COHR","LITE","SNDK","STX","WDC","KEYS","SMCI","ENTG","MKSI","ONTO","AEIS"}
        out.setdefault("ルックスルー", {})[nm] = {
            "網の比率": round(nw * 100, 1), "カバー率": round(cov * 100, 1),
            "上位12": [[s, round(x * 100, 2)] for s, x in sorted(agg.items(), key=lambda z: -z[1])[:12]],
            "半導体連鎖": round(sum(x for s, x in agg.items() if s in SEMI) * 100, 1),
        }

    out["限界"] = [
        "★網の門のキルに当たる本は上の「網の門(ami.html)の規約」に実額で出る（設定の新しい本は年率にしない）",
        "★GRID は保有の約半分が米国外（海外上場）。ルックスルーの個別名は積めるが米国株ではない",
        "網の中の重みの出所は「%s」。重みを変えれば加重経費率もルックスルーも全部動く" % NET_W_SRC,
        "純資産のキルは円建ての線なので USDJPY=158 で概算した（境目から遠いので判定は動かない）",
        ("現行のルックスルーに積めない本（holdings 未取得）: %s" % "・".join(OLD_HOLE))
        if OLD_HOLE else "現行の網は全本の holdings がそろっている＝ルックスルーに穴なし",
    ]
    return out


if __name__ == "__main__":
    n = 50
    if "--net" in sys.argv:
        n = int(sys.argv[sys.argv.index("--net") + 1])
    o = build(n)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(o, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(o, ensure_ascii=False, indent=1))
