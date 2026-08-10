# night/hist_val_decompose.py — 自己相対バリュエーションが「効かない」ことの機構を分解する (2026-08-09新設)
#
# ─────────────────────────────────────────────────────────────────────────────
# 【なぜこの道具が要るか】
#   2026-08-09 の検定（out/hist_valuation_prereg.json → CLAUDE.md v9.9.118）は
#   「自己相対バリュエーション（現PERがその銘柄自身の過去の何%タイルか）は遮断器にならない」
#   ——事前登録6基準に合格ゼロ——と結論した。**だがそこで止めると読み手は
#   『指標がノイズだった』と誤読する。実測はその逆で、指標は当たっている。**
#
#   本器が測るのは *なぜ* 効かないか。分解すると:
#       総リターン ≒ 倍率の寄与（PERが何倍になったか） ＋ 事業の寄与（1株利益が何倍になったか）
#   自己相対分位は **倍率の寄与を強く正しく予言している**（分位が高いほど倍率は縮む）。
#   ところが**事業の寄与が同じだけ大きい**ので、総リターンでは相殺されて平らになる。
#
#   これは E[r] の mult 項（倍率の重力）の**正当性をむしろ強める実測**である。
#   v9.9.84 が「1999年型（法外な倍率）への保険は倍率の重力(mult)が担う」と書いた、
#   その mult が **実在して大きい**ことを、この台帳で初めて直接確認した形になる。
#   今回の結果を「価格は効かない」とだけ読むと mult を外す根拠に誤読されうるので、
#   出力の `implications` に明示する。
#
# ─────────────────────────────────────────────────────────────────────────────
# 【分解の定義（恒等式であることの証明つき）】
#   本器の PER は hist_valuation.py の定義そのまま:  pe = 時価総額 ÷ 純利益(TTM・as-known)
#   1株利益は  eps = 純利益(TTM) ÷ 発行済株数（**今日の株数基準**に揃えたもの）
#
#       pe = mcap / ni  かつ  mcap = px × sh  なので   px = pe × (ni / sh) = pe × eps
#   ゆえに **恒等的に**
#       ln(px1/px0) = ln(pe1/pe0) + ln(eps1/eps0)
#            株価の変化   =   倍率の寄与    +   事業の寄与
#   さらに配当を足すと
#       ln(総リターン)  = 倍率 + 事業 + 分配（配当・スピンオフ等）
#   本器はこの **4項の突合せを毎回検算して残差の分布を出す**（恒等式が成り立たないなら
#   分解の定義か採取が間違っている、というのが唯一の読み方）。
#
#   ※ 自社株買いは **eps の側**に入る（分母 sh が減るので eps が増える）。
#     「倍率の寄与」は純粋に市場が付ける値段の変化だけを指す。
#
# ─────────────────────────────────────────────────────────────────────────────
# 【踏まないようにした落とし穴】
#
# ■ 基準の違う二つを割らない（この台帳が6回踏んでいる型）
#   入口と出口の PER は **同じ採取器・同じ定義・同じ株数基準**で作る。
#   だから hist_valuation.analyse() をそのまま呼ぶ（**二重実装を作らない**）。
#   分割は hist_valuation が「今日の株数基準」へ翻訳済みなので、両端で約分される。
#
# ■ 窓のずれを黙って飲み込まない
#   在庫の前方リターン（retro_returns_*.json）は Yahoo の月足 adjclose で、
#   period1 = ビンテージ年の 07-01 → **最初の足は その年の 7月足＝7月末終値**、
#   最後の足は取得時点の当月足（2026-08）。一方 hist_valuation の入口は
#   asof=07-01 の le_asof ＝ **6月末終値**。つまり両者は1ヶ月ずれる。
#   → 本器は2通りを両方出す:
#       signal  : 入口 = ビンテージの asof 月（6月末）＝**分位を測ったのと同じ時点**（既定・主）
#       window  : 入口 = 7月末＝**前方リターンの起点と同じ足**（残差が純粋な分配になる）
#   主表は signal（分位＝信号が実際に見ていた値と同じ時点で分解するため）。
#   検算は window（残差＝分配だけになるので恒等式の検査が鋭くなる）。
#
# ■ 欠測をゼロと読むな（絶対のルール7）
#   出口で純利益が正でない社は **PER が定義できない**ので分解できない。
#   落とすが、**落とした社の前方リターンを必ず数えて出す**（`dropout`）——
#   落ちた社が敗者に偏っていれば主表の総リターンは上振れて見えるから。
#
# ■ 事前登録の外へ出ない
#   最後の `conditional` は「自己相対が高い ∧ 成長が付いてこない」で切ったときの分布を
#   **材料として並べるだけ**。閾値探索も合否判定もしない（次フェーズの事前登録の材料）。
#   分位の格子は既存の事前登録と同じ 0.80/0.85/0.90/0.95 に固定する。
#
# ─────────────────────────────────────────────────────────────────────────────
# 実行:
#   python3 night/hist_val_decompose.py --offline            # 3ビンテージ全部
#   python3 night/hist_val_decompose.py --v 2018 --offline
#   python3 night/hist_val_decompose.py --v 2018 --exit 2026-08-09 --sort ps_pct
#
#   スナップショットは out/_histval_cache/snap/ に貯める（.gitignore 済・再開可能）。
#   在庫は out/hist_val_decompose_{ビンテージ}.json
import argparse
import datetime as dt
import json
import math
import os
import statistics as st
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hist_val_rev import load_vintage_checked   # 在庫の版の検問（単一実装）
sys.path.insert(0, os.path.join(BASE, "night"))
import hist_valuation as HV                                   # noqa: E402  二重実装を作らない

SNAP = os.path.join(BASE, "out", "_histval_cache", "snap")
TOOL_REV = "r1 (2026-08-09)"

# 事前登録（out/hist_valuation_prereg.json）と同じ格子。ここを増やさない＝多重検定を抑える
PCT_GRID = (0.80, 0.85, 0.90, 0.95)
# 恒久毀損の線は台帳の既存定義（retro_moat_durability / hist_val_gate_test と同じ）
IMPAIR = -0.15
WIN = 0.15


# ── 小道具 ───────────────────────────────────────────────────────────────────
def q(v, p):
    """線形補間の分位（統計量の定義を道具ごとに変えない）。"""
    v = sorted(v)
    if not v:
        return None
    i = p * (len(v) - 1)
    lo = int(math.floor(i))
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)


def spearman(xs, ys):
    def rank(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(s):
            j = i
            while j + 1 < len(s) and v[s[j + 1]] == v[s[i]]:
                j += 1
            for k in range(i, j + 1):
                r[s[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    if len(xs) < 3:
        return None
    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return round(num / den, 4) if den else None


def ann(logr):
    """年率の対数寄与 → 見慣れた年率%（表示用。加法性は対数側にある）。"""
    return None if logr is None else round(100 * (math.exp(logr) - 1), 2)


def rnd(x, n=4):
    return None if x is None else round(x, n)


# ── スナップショット（hist_valuation をそのまま呼ぶ） ────────────────────────
def universe():
    """**全ビンテージのティッカーの和集合**。

    ⚠ スナップショットの鍵は (asof, px_mode) だが、**出口のスナップショットは
    ビンテージ間で共有される**。ここをビンテージごとの銘柄リストで作ると、
    最初に走ったビンテージの銘柄しか入っていないキャッシュを次のビンテージが
    「件数は足りている」と誤って再利用し、**そのビンテージだけ静かに欠測が増える**
    （実測: 2015 が 320社→281社 に痩せた）。CLAUDE.md が繰り返し記録している
    「取れた値＝正しい値」の親戚なので、**和集合で作って被覆を必ず検査する**。
    """
    uni = {}
    for v in (2013, 2015, 2018):
        inv = load_vintage_checked(v, allow_missing=True)   # 版の検問
        if inv is None:
            continue
        for r in inv["rows"]:
            if r["ticker"] not in uni or uni[r["ticker"]] is None:
                uni[r["ticker"]] = r.get("cik")
    return [{"ticker": t, "cik": c} for t, c in sorted(uni.items())]


def snapshot(asof_iso, px_mode, items, offline=True, force=False, min_months=0):
    """{ticker: row} を返す。out/_histval_cache/snap/ にキャッシュ。

    再利用の条件は **件数ではなく銘柄の被覆**（上の universe() の注記を見よ）。
    min_months は分位の下限（水準しか要らない所は 0、分位も要る所は事前登録どおり 36）。
    **鍵に入れる**——同じ asof でも下限が違えば別の在庫だから。
    """
    os.makedirs(SNAP, exist_ok=True)
    suf = "" if not min_months else f"_m{min_months}"
    path = os.path.join(SNAP, f"{asof_iso}_{px_mode}{suf}.json")
    want = {it["ticker"] for it in items}
    if os.path.exists(path) and not force:
        j = json.load(open(path))
        have = {r["ticker"] for r in j["rows"]}
        if want <= have:
            return {r["ticker"]: r for r in j["rows"]}
        print(f"    ※ キャッシュの被覆不足（{len(want - have)}社不足）→ 取り直す: {path}")
    asof = HV.D(asof_iso)
    spx, spx_last = HV.load_spx()
    tmap = HV.ticker_map(offline=offline)
    rows = []
    t0 = dt.datetime.now()
    for i, it in enumerate(items, 1):
        tk = it["ticker"]
        cik = it.get("cik") or tmap.get(tk)
        try:
            r = HV.analyse(tk, cik, asof, spx, spx_last, 0, min_months, px_mode, offline, False)
        except Exception as e:
            r = {"ticker": tk, "cik": cik, "nulls": {"all": f"例外 {type(e).__name__}: {e}"}}
        # 巨大な diag は落とす（在庫ではなくキャッシュなので理由だけ残す）
        rows.append({k: v for k, v in r.items() if k != "diag"})
        if i % 200 == 0:
            print(f"    {i}/{len(items)}  {(dt.datetime.now()-t0).seconds}s", flush=True)
    json.dump({"asof": asof_iso, "px_mode": px_mode, "n": len(rows),
               "tool": "night/hist_valuation.analyse (import)", "rows": rows},
              open(path + ".tmp", "w"), ensure_ascii=False)
    os.replace(path + ".tmp", path)
    return {r["ticker"]: r for r in rows}


def level(row):
    """スナップショット1行 → (pe, ni, eps, sh, px)。作れなければ None。"""
    if not row:
        return None
    pe, mc, sh = row.get("pe"), row.get("mcap"), row.get("shares_today_basis")
    if not pe or not mc or not sh or pe <= 0 or mc <= 0 or sh <= 0:
        return None
    ni = mc / pe
    return {"pe": pe, "ni": ni, "eps": ni / sh, "sh": sh, "px": row.get("px"),
            "ps": row.get("ps"), "rev": (mc / row["ps"]) if row.get("ps") else None}


# ── 本体 ─────────────────────────────────────────────────────────────────────
def decompose(vintage, exit_asof, offline=True, force=False):
    inv_path = os.path.join(BASE, "out", f"hist_val_{vintage}.json")
    inv = load_vintage_checked(vintage)                 # 版の検問
    items = universe()          # 全ビンテージの和集合で作る（出口の在庫を共有するため）

    entry_signal_asof = f"{vintage}-07-01"          # 在庫と同じ（px は 6月末）
    entry_window_asof = f"{vintage}-08-01"          # 前方リターンの起点と同じ足（7月末）
    look_asof = f"{vintage - 3}-08-01"              # 事前に見えていた3年成長の起点

    print(f"■ ビンテージ {vintage}: スナップショット")
    # ⚠ **入口の水準も在庫からではなく自分で採る**。
    #   在庫（hist_val_{V}.json）は採取器の版が上がると作り直されるが、出口は本器が
    #   その時の版で採る＝**在庫が r1・出口が r2 なら「基準の違う二つを割って」いる**
    #   （実際 2026-08-09 に在庫は r1→r2 へ作り直された。night/hist_val_rev.py の記録）。
    #   入口・出口・遡りを **全部 同じ実行・同じ版** で採れば、この経路は構造的に閉じる。
    #   在庫からは **分位(pe_pct 等)・質実証・前方リターン** だけを取り、水準は取らない。
    S_ent_s = snapshot(entry_signal_asof, "le_asof", items, offline, force, min_months=36)
    S_ent_w = snapshot(entry_window_asof, "le_asof", items, offline, force)
    S_look = snapshot(look_asof, "le_asof", items, offline, force)
    # 出口は2通り: le_asof（前月末・確定足）と asof_month（当月足＝前方リターンの終端と同じ）
    S_ex_m = snapshot(exit_asof, "asof_month", items, offline, force)
    S_ex_l = snapshot(exit_asof, "le_asof", items, offline, force)

    ex_month = next((r.get("px_month") for r in S_ex_m.values() if r.get("px_month")), None)
    ex_month_l = next((r.get("px_month") for r in S_ex_l.values() if r.get("px_month")), None)
    ent_w_month = next((r.get("px_month") for r in S_ent_w.values() if r.get("px_month")), None)
    ent_s_month = next((r.get("px_month") for r in S_ent_s.values() if r.get("px_month")), None)

    # 在庫と自前スナップショットが同じものを言っているかの照合（版ずれの検出）
    agree = {"n": 0, "pe_rel_diff_over_1pct": 0, "pe_pct_diff_over_0_02": 0,
             "max_pe_rel_diff": 0.0, "worst": None}
    for r in inv["rows"]:
        s = S_ent_s.get(r["ticker"]) or {}
        if not r.get("pe") or not s.get("pe"):
            continue
        agree["n"] += 1
        d = abs(s["pe"] / r["pe"] - 1)
        if d > 0.01:
            agree["pe_rel_diff_over_1pct"] += 1
        if d > agree["max_pe_rel_diff"]:
            agree["max_pe_rel_diff"], agree["worst"] = round(d, 5), r["ticker"]
        if r.get("pe_pct") is not None and s.get("pe_pct") is not None \
                and abs(r["pe_pct"] - s["pe_pct"]) > 0.02:
            agree["pe_pct_diff_over_0_02"] += 1
    agree["note"] = ("在庫の入口PER・分位 vs 本器が同じ asof で採り直した値。"
                     "大きく食い違うなら**在庫と本器で採取器の版が違う**（作り直しが要る）")

    # ── 行を組む
    rows, drop = [], []
    for r in inv["rows"]:
        t = r["ticker"]
        if not r.get("analysis_set") or not r.get("quality"):
            continue
        y, tr_tot = r.get("years"), r.get("tr_total")
        if not y or not tr_tot or tr_tot <= 0:
            continue
        pe_pct = r.get("pe_pct")
        if pe_pct is None:            # 事前登録の主指標が作れない＝そもそも遮断器を当てられない
            continue
        L0s, L0w = level(S_ent_s.get(t)), level(S_ent_w.get(t))
        L1m, L1l = level(S_ex_m.get(t)), level(S_ex_l.get(t))
        if not L0s or not L1m:
            why = "入口の水準が作れない" if not L0s else \
                  ((S_ex_m.get(t) or {}).get("nulls", {}).get("pe")
                   or (S_ex_m.get(t) or {}).get("nulls", {}).get("all")
                   or "出口の水準が作れない")
            drop.append({"ticker": t, "pe_pct": pe_pct, "tr_cagr": r.get("tr_cagr"), "why": why})
            continue
        tr = math.log(tr_tot) / y

        def split(L0, L1):
            return (math.log(L1["pe"] / L0["pe"]) / y, math.log(L1["eps"] / L0["eps"]) / y)

        m_s, e_s = split(L0s, L1m)
        m_w, e_w = (split(L0w, L1m) if L0w else (None, None))
        # 恒等式の検算: 株価の変化 = 倍率 + 事業（採取器の丸め以外で破れてはいけない）
        ident = None
        if L0s.get("px") and L1m.get("px"):
            ident = math.log(L1m["px"] / L0s["px"]) / y - (m_s + e_s)
        # 分配（配当・スピンオフ）: 同じ月足の adjclose と close の比の差＝**純粋な分配**
        divlog = None
        if L0w:
            P = HV.fetch_px(t, offline=True) or {}
            a_, c_ = P.get("adj") or {}, P.get("close") or {}
            if ent_w_month in a_ and ex_month in a_ and ent_w_month in c_ and ex_month in c_:
                divlog = (math.log(a_[ex_month] / a_[ent_w_month])
                          - math.log(c_[ex_month] / c_[ent_w_month])) / y
        resid_w = (tr - (m_w + e_w + divlog)) if (m_w is not None and divlog is not None) else None

        # 事前に見えていた成長（asof 以前の申告だけで作る＝look-ahead なし）
        Lk = level(S_look.get(t))
        g_eps3 = g_rev3 = None
        if Lk and Lk["eps"] > 0 and L0s["eps"] > 0:
            g_eps3 = math.log(L0s["eps"] / Lk["eps"]) / 3.0
        if Lk and Lk.get("rev") and L0s.get("rev"):
            g_rev3 = math.log(L0s["rev"] / Lk["rev"]) / 3.0

        rows.append({
            "ticker": t, "years": rnd(y, 2),
            "pe_pct": pe_pct, "ps_pct": r.get("ps_pct"), "pfcf_pct": r.get("pfcf_pct"),
            "adj_pe_pct": r.get("adj_pe_pct"), "pe_z": r.get("pe_z"),
            "pe_in": rnd(L0s["pe"], 2), "pe_out": rnd(L1m["pe"], 2),
            "pe_out_le": rnd(L1l["pe"], 2) if L1l else None,
            "mult": rnd(m_s, 6), "biz": rnd(e_s, 6), "tr": rnd(tr, 6),
            "mult_w": rnd(m_w, 6), "biz_w": rnd(e_w, 6), "div": rnd(divlog, 6),
            "ident_err": rnd(ident, 8), "resid_w": rnd(resid_w, 8),
            "sh_chg": rnd(math.log(L1m["sh"] / L0s["sh"]) / y, 6),
            "g_eps3_pre": rnd(g_eps3, 6), "g_rev3_pre": rnd(g_rev3, 6),
            "tr_cagr": r.get("tr_cagr"),
        })

    # ── 検算（恒等式・残差）
    ident = [abs(x["ident_err"]) for x in rows if x["ident_err"] is not None]
    resid = [x["resid_w"] for x in rows if x["resid_w"] is not None]
    divs = [x["div"] for x in rows if x["div"] is not None]
    recon = {
        # (1) 代数の恒等式。**独立な検査ではない**（px は約分で消えるので必ず 0 になる）が、
        #     採取・丸め・符号の実装事故はここで必ず露見する。0 でなければ道具が壊れている
        "identity_def": "ln(px1/px0)/年 − (倍率 + 事業)。代数的に恒等（実装と丸めの検査）",
        "identity_is_tautology": True,
        "identity_n": len(ident),
        "identity_max_abs": rnd(max(ident), 9) if ident else None,
        "identity_median_abs": rnd(st.median(ident), 9) if ident else None,
        # (2) 分配。定義上マイナスにならない＝adjclose の作法の検査
        "div_def": "同じ2つの月足で ln(adjclose比) − ln(close比)。配当・スピンオフの寄与",
        "div_pct": {f"p{int(p*100)}": ann(q(divs, p)) for p in (.05, .25, .5, .75, .95)} if divs else None,
        "div_min": ann(min(divs)) if divs else None,
        "div_max": ann(max(divs)) if divs else None,
        "div_negative_n": sum(1 for v in divs if v < -1e-6),
        "div_note": ("分配は定義上マイナスにならない（配当・スピンオフは総リターンを押し上げる側）。"
                     "マイナスが出たら adjclose の作法か窓の取り方が壊れている。"
                     "最大値の外れはスピンオフ（実例 AIV: 2020-12 の AIRC 分離を adjclose が分配として処理）"),
        # (3) **これが唯一の独立な突合せ**——在庫の前方リターン（retro_returns_*.json・
        #     別コード・別取得日 2026-08-05）と、本器が組んだ 倍率+事業+分配 を比べる。
        #     残差は「数日の取得日差 × その社の値動き」を年率へ均したもの。
        "external_check_def": ("ln(在庫の総リターン)/年 − (倍率 + 事業 + 分配)。"
                               "窓を揃えた版(window)で測る＝**独立に組んだ二つの系列の突合せ**"),
        "external_check_n": len(resid),
        "external_check_max_abs": rnd(max(abs(v) for v in resid), 9) if resid else None,
    }
    if resid:
        recon["external_check_pct"] = {f"p{int(p*100)}": ann(q(resid, p)) for p in (.05, .25, .5, .75, .95)}
        recon["external_check_over_1pct_n"] = sum(1 for v in resid if abs(v) > 0.01)
        recon["external_check_note"] = (
            "中央がゼロ近傍で、外れは取得日の数日差で説明がつく大きさ＝二系列は同じものを測っている")

    # ── 五分位（並べ替えの鍵は複数・分解は1つ）
    def quint(key):
        g = [x for x in rows if x.get(key) is not None]
        if len(g) < 25:
            return None
        g.sort(key=lambda x: x[key])
        n = len(g)
        out = []
        for i in range(5):
            b = g[round(i * n / 5):round((i + 1) * n / 5)]
            trs = [x["tr"] for x in b]
            out.append({
                "q": i + 1, "n": len(b),
                "key_lo": rnd(b[0][key], 3), "key_hi": rnd(b[-1][key], 3),
                "pe_in_med": rnd(st.median([x["pe_in"] for x in b]), 1),
                "pe_out_med": rnd(st.median([x["pe_out"] for x in b]), 1),
                "mult_med_pct": ann(st.median([x["mult"] for x in b])),
                "biz_med_pct": ann(st.median([x["biz"] for x in b])),
                "tr_med_pct": ann(st.median(trs)),
                "tr_mean_pct": ann(sum(trs) / len(trs)),
                "impair_n": sum(1 for x in b if (x["tr_cagr"] or 0) <= IMPAIR),
                "win15_n": sum(1 for x in b if (x["tr_cagr"] or 0) >= WIN),
            })
        ks = [x[key] for x in g]
        return {"quintiles": out,
                "rho_mult": spearman(ks, [x["mult"] for x in g]),
                "rho_biz": spearman(ks, [x["biz"] for x in g]),
                "rho_tr": spearman(ks, [x["tr"] for x in g]),
                "n": n}

    quints = {k: quint(k) for k in ("pe_pct", "ps_pct", "pfcf_pct", "adj_pe_pct")}

    # 窓を揃えた版でも同じ絵になるか（主表の感度）
    def quint_w():
        g = [x for x in rows if x.get("mult_w") is not None and x.get("pe_pct") is not None]
        if len(g) < 25:
            return None
        g.sort(key=lambda x: x["pe_pct"])
        n = len(g)
        return [{"q": i + 1, "n": len(b),
                 "mult_med_pct": ann(st.median([x["mult_w"] for x in b])),
                 "biz_med_pct": ann(st.median([x["biz_w"] for x in b])),
                 "tr_med_pct": ann(st.median([x["tr"] for x in b]))}
                for i, b in enumerate(g[round(i * n / 5):round((i + 1) * n / 5)]
                                      for i in range(5))]
    quints["pe_pct_window_aligned"] = quint_w()

    # 出口の月の選び方（当月足 vs 前月末）の感度。**窓の端の選択で絵が変わらない**ことの実測
    def quint_exit_le():
        g = [x for x in rows if x.get("pe_out_le") and x.get("pe_pct") is not None]
        if len(g) < 25:
            return None
        g.sort(key=lambda x: x["pe_pct"])
        n, out = len(g), []
        for i in range(5):
            b = g[round(i * n / 5):round((i + 1) * n / 5)]
            out.append({"q": i + 1, "n": len(b),
                        "mult_med_pct": ann(st.median(
                            [math.log(x["pe_out_le"] / x["pe_in"]) / x["years"] for x in b])),
                        "pe_out_med": rnd(st.median([x["pe_out_le"] for x in b]), 1)})
        return out
    quints["pe_pct_exit_le_asof"] = quint_exit_le()

    # ── 落とした社（生存バイアスの実数）
    kept_tr = [x["tr_cagr"] for x in rows if x["tr_cagr"] is not None]
    drop_tr = [d["tr_cagr"] for d in drop if d.get("tr_cagr") is not None]
    dq = sorted(rows + [{"pe_pct": d["pe_pct"], "tr_cagr": d.get("tr_cagr"), "_drop": True}
                        for d in drop], key=lambda x: x["pe_pct"])
    per_q = []
    n = len(dq)
    for i in range(5):
        b = dq[round(i * n / 5):round((i + 1) * n / 5)]
        d_ = [x for x in b if x.get("_drop")]
        k_ = [x for x in b if not x.get("_drop")]
        per_q.append({
            "q": i + 1, "n": len(b), "dropped": len(d_),
            "dropped_frac": rnd(len(d_) / len(b), 3),
            "dropped_tr_med": rnd(st.median([x["tr_cagr"] for x in d_ if x["tr_cagr"] is not None]), 4)
                              if any(x["tr_cagr"] is not None for x in d_) else None,
            "kept_tr_med": rnd(st.median([x["tr_cagr"] for x in k_ if x["tr_cagr"] is not None]), 4)
                           if k_ else None})
    dropout = {
        "def": "質実証プール ∧ 入口 pe_pct あり のうち、両端で PER が作れず分解できなかった社",
        "kept_n": len(rows), "dropped_n": len(drop),
        "kept_tr_med": rnd(st.median(kept_tr), 4) if kept_tr else None,
        "dropped_tr_med": rnd(st.median(drop_tr), 4) if drop_tr else None,
        "kept_impair_frac": rnd(sum(1 for v in kept_tr if v <= IMPAIR) / len(kept_tr), 4) if kept_tr else None,
        "dropped_impair_frac": rnd(sum(1 for v in drop_tr if v <= IMPAIR) / len(drop_tr), 4) if drop_tr else None,
        "by_entry_quintile": per_q,
        "reasons": _reasons(drop),
        "rows": sorted(drop, key=lambda d: (d.get("tr_cagr") is None, d.get("tr_cagr") or 0))[:40],
    }

    # ── 条件付きの材料（**閾値探索も合否判定もしない**）
    cond = conditional(inv, S_ent_s, S_look, exit_ok={x["ticker"] for x in rows})
    cond["why_conditioning_is_hard"] = why_hard(rows)
    cond["ex_post_illustration"] = ex_post(rows)

    return {
        "generated": dt.date.today().isoformat(),
        "tool": "night/hist_val_decompose.py",
        "tool_rev": TOOL_REV,
        # 読んだ在庫（採取器）の版。**この器の版とは別物**——
        # 2026-08-09に「2013だけr2・2015/2018がr1」の混在で検定7本が回った事故があるので、
        # 派生の在庫にも「どの版の在庫で出した数字か」を必ず刻む（night/hist_val_rev.py）
        "src_tool_rev": inv.get("tool_rev"),
        "vintage": vintage,
        "entry_signal_asof": entry_signal_asof, "entry_signal_px_month": ent_s_month,
        "entry_window_asof": entry_window_asof, "entry_window_px_month": ent_w_month,
        "exit_asof": exit_asof, "exit_px_month": ex_month, "exit_px_month_le": ex_month_l,
        "returns_src": inv.get("join", {}).get("returns_src"),
        "benchmark": inv.get("join", {}).get("benchmark"),
        "pool_def": ("質実証プール（opm>=10% ∧ 直近5年FCF全年黒字…在庫 hist_val_{V}.json の quality）"
                     " ∧ analysis_set ∧ 入口 pe_pct あり ∧ **両端で PER が作れる**"),
        "definition": {
            "identity": "ln(px1/px0) = ln(pe1/pe0) + ln(eps1/eps0)  （pe=時価総額÷純利益TTM, eps=純利益TTM÷株数）",
            "four_way": "ln(総リターン) = 倍率 + 事業 + 分配",
            "mult": "倍率の寄与＝PER が何倍になったかを年率の対数で",
            "biz": "事業の寄与＝1株利益（自社株買いの効果を含む）が何倍になったかを年率の対数で",
            "units": "*_med_pct / *_pct は年率%（対数寄与を exp して表示）。rows の mult/biz/tr は**対数**（加法的）",
        },
        "n": {"inventory_rows": len(inv["rows"]), "analysed": len(rows), "dropped": len(drop)},
        # 在庫（別の実行・別の版でありうる）と、本器が採り直した入口の照合
        "inventory_vs_snapshot": agree,
        "level_source": ("入口・出口・遡り の**水準はすべて本器のスナップショット**"
                         "（hist_valuation.analyse を同じ実行で呼ぶ）。在庫からは"
                         "分位・質実証・前方リターンだけを取る＝版ずれで割り算しない"),
        "reconcile": recon,
        "sorts": quints,
        "dropout": dropout,
        "conditional": cond,
        "limits": LIMITS,
        "implications": IMPLICATIONS,
        "rows": rows,
    }


def _reasons(drop):
    from collections import Counter
    c = Counter()
    for d in drop:
        w = d.get("why") or ""
        if "正でない" in w:
            k = "出口の純利益が正でない（PERが定義できない＝赤字転落）"
        elif "株数" in w:
            k = "出口の発行済株数が取れない（時価総額が作れない）"
        elif "Yahoo" in w or "月足" in w:
            k = "出口の月足が無い（上場廃止・被買収・改称）"
        elif "入口" in w:
            k = "入口の水準が作れない"
        else:
            k = w[:50] or "その他"
        c[k] += 1
    return dict(c.most_common())


def conditional(inv, S_ent_s, S_look, exit_ok):
    """「自己相対が高い ∧ 事前に見えていた成長が付いてこない」で切ったときの分布。

    **これは材料であって判定ではない。** 閾値は事前登録と同じ格子に固定し、
    どの組合せが「良い」とも言わない（次フェーズの事前登録を書くための分布）。

    プールは **両端で PER が作れる社に限定しない**——遮断器は asof 時点で回すので、
    出口の情報（＝生存・黒字継続）で母集団を絞ると生存バイアスを遮断器の中へ持ち込む。
    """
    pool = []
    for r in inv["rows"]:
        if not (r.get("analysis_set") and r.get("quality")):
            continue
        if r.get("pe_pct") is None or r.get("tr_cagr") is None:
            continue
        Lk, L0 = level(S_look.get(r["ticker"])), level(S_ent_s.get(r["ticker"]))
        g = None
        if Lk and L0 and Lk["eps"] > 0 and L0["eps"] > 0:
            g = math.log(L0["eps"] / Lk["eps"]) / 3.0
        gr = None
        if Lk and L0 and Lk.get("rev") and L0.get("rev"):
            gr = math.log(L0["rev"] / Lk["rev"]) / 3.0
        pool.append({"ticker": r["ticker"], "pe_pct": r["pe_pct"], "tr": r["tr_cagr"],
                     "g_eps3": g, "g_rev3": gr, "both_ends": r["ticker"] in exit_ok})
    if not pool:
        return None
    base_tr = [x["tr"] for x in pool]
    base = {"n": len(pool), "tr_med": rnd(st.median(base_tr), 4),
            "impair_frac": rnd(sum(1 for v in base_tr if v <= IMPAIR) / len(pool), 4),
            "impair_n": sum(1 for v in base_tr if v <= IMPAIR),
            "win15_frac": rnd(sum(1 for v in base_tr if v >= WIN) / len(pool), 4)}

    def cell(sel):
        s = [x for x in pool if sel(x)]
        p = [x for x in pool if not sel(x)]
        if not s:
            return None
        trs = [x["tr"] for x in s]
        trp = [x["tr"] for x in p]
        return {"stopped_n": len(s), "stopped_frac": rnd(len(s) / len(pool), 4),
                "stopped_tr_med": rnd(st.median(trs), 4),
                "passed_tr_med": rnd(st.median(trp), 4) if trp else None,
                "stopped_impair_n": sum(1 for v in trs if v <= IMPAIR),
                "stopped_impair_frac": rnd(sum(1 for v in trs if v <= IMPAIR) / len(s), 4),
                "impair_ratio_vs_base": rnd((sum(1 for v in trs if v <= IMPAIR) / len(s))
                                            / base["impair_frac"], 2) if base["impair_frac"] else None,
                "stopped_win15_frac": rnd(sum(1 for v in trs if v >= WIN) / len(s), 4)}

    have_g = [x for x in pool if x["g_eps3"] is not None]
    med_g = st.median([x["g_eps3"] for x in have_g]) if have_g else None
    have_gr = [x for x in pool if x["g_rev3"] is not None]
    med_gr = st.median([x["g_rev3"] for x in have_gr]) if have_gr else None

    cells = {}
    for thr in PCT_GRID:
        cells[f"pe_pct>={thr:.2f}"] = cell(lambda x, t=thr: x["pe_pct"] >= t)
        if med_g is not None:
            cells[f"pe_pct>={thr:.2f} ∧ 事前3年EPS成長<中央({100*(math.exp(med_g)-1):.1f}%)"] = cell(
                lambda x, t=thr, m=med_g: x["pe_pct"] >= t and x["g_eps3"] is not None and x["g_eps3"] < m)
            cells[f"pe_pct>={thr:.2f} ∧ 事前3年EPS成長<0"] = cell(
                lambda x, t=thr: x["pe_pct"] >= t and x["g_eps3"] is not None and x["g_eps3"] < 0)
        if med_gr is not None:
            cells[f"pe_pct>={thr:.2f} ∧ 事前3年売上成長<中央({100*(math.exp(med_gr)-1):.1f}%)"] = cell(
                lambda x, t=thr, m=med_gr: x["pe_pct"] >= t and x["g_rev3"] is not None and x["g_rev3"] < m)
    return {
        "note": ("**材料であって判定ではない**。閾値探索も合否判定もしていない。"
                 "事前登録の格子(0.80/0.85/0.90/0.95)に固定し、成長の側は"
                 "『プール中央値』と『0』という**事前に決まる2点だけ**を使った"),
        "growth_is_ex_ante": ("事前3年EPS成長は asof の3年前と asof のスナップショットの比。"
                              "どちらも filed<=その時点の申告だけで作るので look-ahead は無い"),
        "pool_def": "質実証プール ∧ 入口 pe_pct あり ∧ 前方リターンあり（**出口の情報で絞らない**）",
        "coverage_g_eps3": f"{len(have_g)}/{len(pool)}",
        "coverage_g_rev3": f"{len(have_gr)}/{len(pool)}",
        "base": base,
        "cells": {k: v for k, v in cells.items() if v},
    }


def why_hard(rows):
    """『高い倍率 ∧ 成長が付いてこない』を **事前に** 見分けようとすると何が起きるか。

    分解の含意はこう読める——遮断器が報われるのは「倍率が高いのに事業の寄与が小さい社」だけ。
    ではその条件を asof 時点の数字で作れるか、を相関で先に見る。
    """
    g = [x for x in rows if x.get("g_eps3_pre") is not None]
    gr = [x for x in rows if x.get("g_rev3_pre") is not None]
    if len(g) < 25:
        return None
    out = {
        "n_g_eps3": len(g), "n_g_rev3": len(gr),
        "rho_pre_growth_vs_entry_pe_pct": spearman([x["g_eps3_pre"] for x in g],
                                                   [x["pe_pct"] for x in g]),
        "rho_pre_growth_vs_entry_pe_level": spearman([x["g_eps3_pre"] for x in g],
                                                     [x["pe_in"] for x in g]),
        "rho_pre_growth_vs_realized_biz": spearman([x["g_eps3_pre"] for x in g],
                                                   [x["biz"] for x in g]),
        "rho_pre_growth_vs_realized_mult": spearman([x["g_eps3_pre"] for x in g],
                                                    [x["mult"] for x in g]),
        "rho_pre_growth_vs_tr": spearman([x["g_eps3_pre"] for x in g], [x["tr"] for x in g]),
    }
    if gr:
        out["rho_pre_rev_growth_vs_realized_biz"] = spearman([x["g_rev3_pre"] for x in gr],
                                                             [x["biz"] for x in gr])
    out["read"] = (
        "(a) 事前の成長と入口の自己相対分位が**強い負の相関**なら、自己相対PERの高さの正体は"
        "『株価が高い』ではなく『**分母の利益が一時的に低い**』＝二つの条件は同じ条件で、"
        "『高倍率 ∧ 低成長』は掛け合わせても新しい情報にならない。"
        "(b) 事前の成長と**事後**の事業の寄与が0か負なら、事前の成長は将来の成長の代理にならない"
        "（利益は平均回帰する）＝『成長が付いてこない社』を事前に名指しできない。"
        "この2つが同時に起きていると、条件付き遮断器は**構造的に**作れない")
    return out


def ex_post(rows):
    """**事後**の切り方（遮断器には使えない）で機構を図示する。

    「倍率が高い社を、その後の事業の寄与で三分する」と、分解の主張がそのまま見える。
    ここで差が出るのは当たり前（事後だから）。**これを遮断器と読んではいけない**——
    載せる理由は『では事前に同じ切り方ができるか』という次の問いの土俵を作るため。
    """
    hi = [x for x in rows if x["pe_pct"] is not None and x["pe_pct"] >= 0.80]
    if len(hi) < 30:
        return None
    hi = sorted(hi, key=lambda x: x["biz"])
    n = len(hi)
    ter = []
    for i in range(3):
        b = hi[round(i * n / 3):round((i + 1) * n / 3)]
        ter.append({"t": i + 1, "n": len(b),
                    "biz_med_pct": ann(st.median([x["biz"] for x in b])),
                    "mult_med_pct": ann(st.median([x["mult"] for x in b])),
                    "tr_med_pct": ann(st.median([x["tr"] for x in b])),
                    "impair_n": sum(1 for x in b if (x["tr_cagr"] or 0) <= IMPAIR)})
    return {"warning": "**事後の切り方**。遮断器には使えない（asof 時点でこの三分はできない）",
            "def": "自己相対PER分位 0.80以上の社を、実現した事業の寄与で三分",
            "tertiles": ter}


LIMITS = [
    "**両端で黒字かつ生存した社に限られる**（分解には出口のPERが要る＝出口で赤字・上場廃止の社は落ちる）。"
    "落とした社の前方リターンは `dropout` に実数で出してある——落ちた社は総じて敗者なので、"
    "主表の総リターンの水準は上振れて読める。ただし落ちた社が入口分位のどこにいたかも出してあり、"
    "**高分位に偏っていなければ分位間の比較（＝この分解の主張）は保たれる**",
    "質実証プールそのものが自己履歴36ヶ月を要求する＝**時価総額の大きい生存者に偏る**"
    "（v9.9.118 の検定で超幾何 P=1.6e-5 で左尾が切れていると測った）。この分解も同じ母集団の上にある",
    "3ビンテージは独立標本ではない（2018 の母集団は 2013 のティッカー名簿・判定プールの重複 69〜79%）",
    "**2013 は自己履歴が構造的に短い**——XBRL が2009年開始・TTM の助走に約18ヶ月要るので、"
    "2013-07 時点の自己履歴は中央値22ヶ月・最長46ヶ月。既定の下限36ヶ月で724社が落ち、"
    "分解できるのは 92社だけ（night/README.md の hist_valuation の項に実測）。"
    "**2013 の数字は方向の傍証であって検出力を持たない**",
    "窓が違う（2013=13.1年 / 2015=11.1年 / 2018=8.1年）。**年率で比べるがレジームは共通**"
    "——後半はどのビンテージも同じ 2018-2026 を含む",
    "2018 ビンテージの入口PERは TCJA(2017-12) の一時費用を TTM 純利益に含む社がある＝"
    "『高い株価』でなく『一時的に低い利益』で高分位に入る社が混じる（在庫の caveats に既出）。"
    "その社は事業の寄与が機械的に大きく出る側なので、**Q5 の事業の寄与は上振れて読む**",
    "**質実証プールの定義がビンテージ間で完全には揃わない**——2013/2015 は "
    "`opm>=10% ∧ FCF全年黒字 ∧ 営業利益全年黒字`、2018 は在庫に『営業利益全年黒字』が無いので前2条件だけ。"
    "同条件を課すと 2013 は −10.4%・2015 は −6.8% 縮むので、**2018のプールは7〜10%ぶん緩い**"
    "（hist_val_join.py の記録）。ビンテージ間で水準を比べるときはこの差を承知で読む",
    "分解は PER 基準。**赤字の期間がある社は入口・出口とも落ちる**ので、"
    "『倍率が高いのに利益が出ていない』型（この遮断器がいちばん効きそうな型）が構造的に薄い",
    "在庫の pe/mcap は JSON で丸めてあるため、恒等式の残差は 1e-6/年 程度の丸めを含む（`reconcile` に実測）",
]

IMPLICATIONS = [
    "自己相対分位は **倍率の寄与を強く正しく予言している**（分位が高いほど、その後 PER は縮む）。"
    "『効かない』の正体は指標がノイズだからではなく、**実在する信号が事業の寄与にぴったり相殺されている**から",
    "出口の PER は入口の分位によらず狭い帯へ収束する。入口で 3倍以上あった倍率の差が、"
    "出口ではほぼ消える＝**倍率は平均回帰し、その分だけ高倍率の社は倍率で損をする**",
    "だが高倍率の社は **1株利益がその分だけ速く伸びた**。市場は平均としては正しく値付けしていた",
    "**含意1（遮断器）**: 価格の遮断器が報われるのは『倍率が高いのに成長が付いてこない社』だけ。"
    "価格を成長（または堀の持続性＝irr=85）で条件付けない限り、価格単独の線は原理的に効かない。"
    "この台帳が横断面PER・fairPER倍率・E[r]・自己相対の4系統すべてで同じ答えに着いた理由がこれ",
    "**含意2（E[r]の mult 項の正当性）**: v9.9.84 は『1999年型（法外な倍率）への保険は倍率の重力(mult)が担う』"
    "と書いたが、その mult が実在して大きいことは直接には測っていなかった。"
    "本器の実測は **mult が年率で数%動く一次の項である**ことを示す＝**E[r] から mult を外す根拠にはならない**。"
    "今回の結果を『価格は効かない』とだけ読むと mult を外す誤読を生むので、ここを明示する",
    "**含意3（分解の非対称）**: 遮断器は総リターンの左尾を狙う道具なので、"
    "『倍率が縮む』ことと『元本が毀損する』ことは別物。分位ごとの恒久毀損の実数も出してある",
]


def main():
    ap = argparse.ArgumentParser(description="自己相対バリュエーションの分解（倍率の寄与 vs 事業の寄与）")
    ap.add_argument("--v", "--vintage", dest="v", help="2013 / 2015 / 2018（既定=全部）")
    ap.add_argument("--exit", default=dt.date.today().isoformat(), help="出口の asof")
    ap.add_argument("--offline", action="store_true", help="キャッシュだけで動かす")
    ap.add_argument("--force", action="store_true", help="スナップショットを取り直す")
    ap.add_argument("--json", action="store_true", help="要約をJSONで標準出力へ")
    a = ap.parse_args()
    vints = [int(a.v)] if a.v else [2013, 2015, 2018]
    for V in vints:
        d = decompose(V, a.exit, offline=a.offline, force=a.force)
        p = os.path.join(BASE, "out", f"hist_val_decompose_{V}.json")
        json.dump(d, open(p + ".tmp", "w"), ensure_ascii=False, indent=1)
        os.replace(p + ".tmp", p)
        if a.json:
            print(json.dumps({k: v for k, v in d.items() if k != "rows"}, ensure_ascii=False))
            continue
        print(f"\n══ {V}年ビンテージ  入口 {d['entry_signal_px_month']} → 出口 {d['exit_px_month']}"
              f"  n={d['n']['analysed']}（落とした {d['n']['dropped']}）")
        r = d["reconcile"]
        if r["identity_max_abs"] is not None:
            print(f"  恒等式 |px−(倍率+事業)| 最大 {r['identity_max_abs']:.1e}（代数的に恒等＝実装の検査）")
        if r.get("div_pct"):
            print(f"  分配の寄与 p25 {r['div_pct']['p25']:+.2f}% / 中央 {r['div_pct']['p50']:+.2f}% / "
                  f"p95 {r['div_pct']['p95']:+.2f}%  マイナス {r['div_negative_n']}社")
        if r.get("external_check_pct"):
            e = r["external_check_pct"]
            print(f"  独立突合せ 在庫の総リターン −(倍率+事業+分配): p5 {e['p5']:+.2f}% / "
                  f"中央 {e['p50']:+.2f}% / p95 {e['p95']:+.2f}%  "
                  f"|>1%/年| {r['external_check_over_1pct_n']}社")
        s = d["sorts"]["pe_pct"]
        print("  自己相対PER分位  入口PER  出口PER │ 倍率の寄与  事業の寄与   総リターン  恒久毀損")
        for x in s["quintiles"]:
            print(f"    Q{x['q']} n={x['n']:3d}      {x['pe_in_med']:6.1f}  {x['pe_out_med']:6.1f} │"
                  f" {x['mult_med_pct']:+8.2f}%  {x['biz_med_pct']:+8.2f}%  {x['tr_med_pct']:+8.2f}%"
                  f"   {x['impair_n']}社")
        print(f"    ρ(分位, 倍率) {s['rho_mult']:+.3f}   ρ(分位, 事業) {s['rho_biz']:+.3f}"
              f"   ρ(分位, 総) {s['rho_tr']:+.3f}")
        do = d["dropout"]
        print(f"  落とした {do['dropped_n']}社の前方リターン中央 {do['dropped_tr_med']}"
              f"（残った {do['kept_n']}社は {do['kept_tr_med']}）")
        w = (d.get("conditional") or {}).get("why_conditioning_is_hard")
        if w:
            print(f"  条件付けが難しい理由: ρ(事前3年EPS成長, 入口分位) "
                  f"{w['rho_pre_growth_vs_entry_pe_pct']:+.3f}／"
                  f"ρ(事前3年EPS成長, 事後の事業の寄与) {w['rho_pre_growth_vs_realized_biz']:+.3f}")
        print(f"  → {p}")


if __name__ == "__main__":
    main()
