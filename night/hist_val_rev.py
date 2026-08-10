# night/hist_val_rev.py — 自己相対バリュエーション在庫の**版の検問**（2026-08-09新設）
#
# ■ なぜ要るか（実際に踏んだ事故）
#   2026-08-09、採取器 night/hist_valuation.py は途中で **r2（share_scale_guard＝
#   filer の株数の桁誤りを落とす）** へ上がったのに、在庫は
#     out/hist_val_2013.json = r2 ／ out/hist_val_2015.json = r1 ／ out/hist_val_2018.json = r1
#   と**混ざったまま**残り、検定4本・反証3本がすべて r1 を読んでいた。
#   これは CLAUDE.md が6回記録している **「基準の違う二つを割る」型**そのもの
#   （KLACの株式分割／ADRのper／JP門0の新旧pt／through-cycle と single-year の片側だけ変更／
#     門0の売上タグの決算日の錨／台帳の per と自己相対の pe）。
#   実害の実測: NUS（恒久毀損 −25.1%/年）の pe_pct が 0.693→0.955、
#   INOD（+66.0%/年の勝者）の ps_pct が 0.987→**0.0**、
#   CTA-PB は時価総額が 10,297 → 89.4十億$ ＝分位が 0.034 → 0.784 と正反対に動いた。
#
# ■ 何を検問するか（人の注意力ではなく機構で防ぐ）
#   (1) **版が書いていない在庫を拒否する**。`tool_rev` は r2 から入れた欄なので、
#       欄が無い＝r1 と**一意に決まる**（推測ではない）。
#   (2) **突き合わせる在庫の版が揃っているか**を見る。病気は「r1であること」ではなく
#       **「r1とr2を並べて比べたこと」**なので、揃っていなければ止める。
#       r3 が来ても『全部 r3 なら通る』ので、この検問は将来の版上げを妨げない。
#
# ■ この器は判定を一つも持たない
#   採点・分位・合否の計算は一行も入れない。だから
#   night/hist_val_lookahead.py が掲げる「検定の計算を一行も import しない」独立性は保たれる
#   （import しているのは*版の照合*だけで、測る側のコードではない）。
#
# 使い方:
#   from hist_val_rev import load_vintage_checked, require_same_rev
#   d = load_vintage_checked(2018)                  # 版が無ければ SystemExit で止まる
#   require_same_rev({y: d[y] for y in (2013, 2015, 2018)})
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")

# 版が書かれていない在庫は、この版で作られたもの（＝share_scale_guard 以前）
IMPLIED_REV_WHEN_MISSING = "r1 (share_scale_guard 以前)"

_HOWTO = ("採り直し方: python3 night/hist_valuation.py --asof {y}-07-01 "
          "--tickers out/hist_val_{y}.json --out out/hist_val_{y}.json --offline "
          "&& python3 night/hist_val_join.py --asof {y}\n"
          "  ※ --out を明示すると部分実行ガードが効かないので、**先に在庫を退避**すること")


def rev_of(inv):
    """在庫の版。欄が無ければ None（＝r1）。"""
    return (inv or {}).get("tool_rev")


def path_of(y):
    return os.path.join(OUT, f"hist_val_{y}.json")


# この実行の中で読んだ在庫の版（パス→版）。**混在は読んだ瞬間に止める**ので、
# 検問を1行入れるだけで「版の違う二つを突き合わせた」が構造的に起きなくなる。
_SEEN = {}


def load_vintage_checked(y, path=None, allow_missing=False):
    """ビンテージ在庫を読み、**版が無ければ止める**。同じ実行で**版が混ざっても止める**。

    allow_missing=True はファイルそのものが無い場合に None を返す（在庫が任意の器用）。
    版が無い場合は allow_missing に関係なく止める——「読めたが古い」を黙って通すのが
    今回の事故そのものだったから。
    """
    p = path or path_of(y)
    if not os.path.exists(p):
        if allow_missing:
            return None
        raise SystemExit(f"■ 在庫が無い: {p}\n  " + _HOWTO.format(y=y))
    inv = json.load(open(p, encoding="utf-8"))
    if not rev_of(inv):
        raise SystemExit(
            f"■ 版の無い在庫を拒否した: {p}\n"
            f"  `tool_rev` が無い＝**{IMPLIED_REV_WHEN_MISSING}** の在庫。\n"
            f"  r1 は filer の株数の桁誤り（実測 2018年で 68社・212申告）をそのまま分位に入れるので、\n"
            f"  『自己史上いちばん高い』が機械的に捏造される（実測 INOD ps_pct 0.987→0.0 / NUS 0.693→0.955）。\n"
            f"  " + _HOWTO.format(y=y))
    _SEEN[p] = rev_of(inv)
    if len(set(_SEEN.values())) > 1:
        detail = " ／ ".join(f"{os.path.basename(k)}: {v}" for k, v in sorted(_SEEN.items()))
        raise SystemExit(
            f"■ 版の違う在庫を同じ実行で読んだ: {detail}\n"
            "  **基準の違う二つを割らない**（CLAUDE.mdが6回記録している事故の型）。\n"
            "  古いほうを採り直してから回すこと。\n"
            "  " + _HOWTO.format(y="{年}"))
    return inv


def seen_revs():
    """この実行で読んだ在庫の版（出力に刻んで、後から『どの版で出した数字か』を辿れるように）。

    ⚠ **在庫を読み終えた後で呼ぶこと**。報告dictの初期化と同時に呼ぶと空になる
    （実際に一度そうなった）。書き出しの直前に代入するのが正しい。
    """
    return {os.path.basename(k): v for k, v in _SEEN.items()}


def require_same_rev(invs, where=""):
    """複数ビンテージの版が揃っているかを見る。揃っていなければ止める。

    invs: {年: 在庫dict}（None は無視する）
    """
    seen = {}
    for y, inv in (invs or {}).items():
        if inv is None:
            continue
        seen.setdefault(rev_of(inv) or IMPLIED_REV_WHEN_MISSING, []).append(str(y))
    if len(seen) > 1:
        detail = " ／ ".join(f"{r}: {', '.join(ys)}" for r, ys in sorted(seen.items()))
        raise SystemExit(
            f"■ 版の違う在庫を突き合わせようとした{('（' + where + '）') if where else ''}: {detail}\n"
            "  **基準の違う二つを割らない**（CLAUDE.mdが6回記録している事故の型）。\n"
            "  古いほうを採り直してから回すこと。\n"
            "  " + _HOWTO.format(y="{年}"))
    return next(iter(seen), None)
