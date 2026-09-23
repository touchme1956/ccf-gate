# night/px_guard.py — Yahoo の株価履歴を取り直すとき「在庫の長い履歴を短い応答で上書きしない」検問
#
# 2026-09-23 新設（todo yahoo_history_vanished）。
# 実測: Yahoo は BBBY / EA / EQR / HLX / ISSC / LEG / QVCAQ / SALM について **2026-07 以降の足しか返さない**
#   （meta.firstTradeDate が 2026-07-17 に付け替わっている。range=max でも 2026-07 始まり、
#    period1 を 2004 年に置いても 2026-07 から。日によっては範囲指定が HTTP 400）。
#   ⇒ 取り直すと、2026-08 に採った全履歴が**黙って短い系列に置き換わる**（ルール7(c)「保管された値も毎回検問する」）。
#   実害: 2026-09-23 の作業用の写し（scratchpad）では EQR/QVCAQ/SALM/BBBY の月足が 2 本だけになり、
#   dd5（2008-07..2013-06 の窓）が作れず「測れない」側へ落ちた。
#
# 検問は二つ:
#   (1) keep_longer(old, new)   ── 同じ保管場所に**前の系列がある**とき。新しい系列が
#       空／前より始まりが遅い／前の期間の足が大きく欠ける → **前を残す**（上書きしない）。
#   (2) vet(sym, new, req_start) ── 前の系列が手元に無いとき（キャッシュを消した・別の端末）。
#       コミットしてある台帳 out/px_span_ledger.json が「この記号は ◯◯ には既に足があった」と
#       知っていて、応答の始まりが 要求の始まり と 台帳の始まり の遅いほうより 40日以上遅ければ
#       **その応答を使わない**（None を返す＝測れない。短い系列を全履歴として使わない）。
#   どちらも拒否したら out/_px_guard.log（.gitignore 済みの out/_*.log）へ1行 JSON と標準エラーに残す。
#
# ⚠ 記号の使い回し（BBBY＝旧 Bed Bath & Beyond → 現 Beyond Inc.）でも台帳は拒否する側に倒れる。
#   別の会社の短い系列を全履歴として使うより「測れない」のほうが正しい（誤値より空欄）。
# ⚠ 台帳は「始まり（最古の足）」だけを覚える。終わりは毎日伸びるので覚えない（差分の嵐を作らない）。
import datetime as _dt
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BASE, "out", "px_span_ledger.json")
LOG = os.path.join(BASE, "out", "_px_guard.log")
TOL_DAYS = 40            # 月足の端点のずれ（月初/月末・市場時差）を吸う幅
HOLE_SHARE = 0.80        # 前の期間の足が 8割を切ったら「欠けた」とみなす

_ledger = None


# ── 系列の形を一つにそろえる ─────────────────────────────────────────────
def _to_date(k):
    """'YYYY-MM' / 'YYYY-MM-DD' / unix秒 → date。読めなければ None。"""
    try:
        if isinstance(k, (int, float)):
            return _dt.datetime.utcfromtimestamp(int(k)).date()
        s = str(k)
        if len(s) == 7:
            return _dt.date(int(s[:4]), int(s[5:7]), 1)
        return _dt.date.fromisoformat(s[:10])
    except Exception:
        return None


def dates_of(series):
    """dict のキー / [[date, v], ...] / [(ts, v), ...] / [date, ...] を日付の昇順リストへ。"""
    if not series:
        return []
    if isinstance(series, dict):
        ks = list(series.keys())
    else:
        ks = [x[0] if isinstance(x, (list, tuple)) else x for x in series]
    ds = [d for d in (_to_date(k) for k in ks) if d is not None]
    return sorted(ds)


def span(series):
    ds = dates_of(series)
    if not ds:
        return None
    return {"first": ds[0].isoformat(), "last": ds[-1].isoformat(), "n": len(ds)}


# ── ログ ───────────────────────────────────────────────────────────────
def log_refusal(sym, tool, reason, old_span=None, new_span=None, kept="old"):
    rec = {"at": _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "sym": sym, "tool": tool,
           "reason": reason, "old": old_span, "new": new_span, "kept": kept}
    print(f"⚠ px_guard: {sym} の応答を採らない（{tool}）— {reason}"
          f" / 前 {old_span and (old_span['first'], old_span['n'])}"
          f" / 今回 {new_span and (new_span['first'], new_span['n'])} → {kept} を残す", file=sys.stderr)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return rec


# ── (1) 前の系列があるとき ──────────────────────────────────────────────
def shorter_reason(old, new):
    """new が old より短い（＝上書きすると履歴が消える）なら理由の文字列、そうでなければ None。"""
    od = dates_of(old)
    if not od:
        return None                               # 守るべき前の履歴が無い
    nd = dates_of(new)
    if not nd:
        return "応答が空（取得失敗・no-result・HTTP 400 等）"
    if (nd[0] - od[0]).days > TOL_DAYS:
        return f"始まりが遅い（前 {od[0]} → 今回 {nd[0]}）"
    lo, hi = od[0], od[-1]
    n_old = len(od)
    n_new = sum(1 for d in nd if lo <= d <= hi)
    if n_old >= 6 and n_new < HOLE_SHARE * n_old:
        return f"前の期間の足が欠けた（{n_old} → {n_new} 本）"
    return None


def keep_longer(sym, old, new, tool):
    """前の系列 old を短い応答 new で上書きしない。採るほうを返す（拒否したらログを残す）。"""
    why = shorter_reason(old, new)
    if why is None:
        return new
    log_refusal(sym, tool, why, span(old), span(new), kept="old")
    return old


# ── (2) 台帳 ───────────────────────────────────────────────────────────
def _load():
    global _ledger
    if _ledger is None:
        try:
            _ledger = json.load(open(LEDGER, encoding="utf-8"))
        except Exception:
            _ledger = {"about": "px_guard の台帳（記号ごとに、Yahoo が以前は返していた最古の足）", "syms": {}}
        _ledger.setdefault("syms", {})
    return _ledger


def _save():
    led = _load()
    tmp = LEDGER + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(led, f, ensure_ascii=False, indent=0, sort_keys=True)
        os.replace(tmp, LEDGER)
    except Exception:
        pass


def known_first(sym):
    r = _load()["syms"].get(sym.upper())
    return _to_date(r["first"]) if r and r.get("first") else None


def note(sym, series, tool):
    """採った系列の始まりを台帳へ（より古い始まりを見たときだけ書く）。"""
    sp = span(series)
    if not sp:
        return
    led = _load()["syms"]
    k = sym.upper()
    cur = led.get(k)
    if cur and cur.get("first") and cur["first"] <= sp["first"]:
        return
    led[k] = {"first": sp["first"], "seen": _dt.date.today().isoformat(), "src": tool}
    _save()


def vet(sym, series, tool, req_start=None, record=True):
    """前の系列が手元に無いときの検問。台帳が知っている始まりより応答が遅く始まるなら None を返す。

    req_start: 要求した期間の始まり（date / 'YYYY-MM-DD' / unix秒）。台帳より後を頼んだときに
               誤って拒否しないため（例: 3年前から頼めば 3年前から始まるのが正しい）。
    """
    kf = known_first(sym)
    nd = dates_of(series)
    if kf is not None:
        rs = _to_date(req_start) if req_start is not None else None
        ref = max(kf, rs) if rs else kf
        if not nd:
            log_refusal(sym, tool, f"応答が空だが台帳では {kf} から足があった",
                        {"first": kf.isoformat(), "last": None, "n": None}, None, kept="none(測れない)")
            return None
        if (nd[0] - ref).days > TOL_DAYS:
            log_refusal(sym, tool, f"始まりが遅い（台帳 {kf}・要求 {rs} → 今回 {nd[0]}）",
                        {"first": kf.isoformat(), "last": None, "n": None}, span(series),
                        kept="none(測れない)")
            return None
    if record and nd:
        note(sym, series, tool)
    return series
