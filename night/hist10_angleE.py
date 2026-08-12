#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hist10_angleE.py — 角度E: **条件構造（決定木）を入れ子交差検証で**。

事前登録: out/hist10_prereg.json（**合否の線はそこにある。この道具は線を一つも作らない**）
入力    : out/hist_wd_panel.json   （特徴量。再実装しない）
          out/hist10_targets.json  （y10 / y_persist / y_biz の正本）
          night/hist10_diag.py     （原始関数を import: load / quantile / mh_diff /
                                     perm_engine / SUBSETS / CUT_QS / 線の定数）
          night/hist10_angleD.py   （**既存関門と各ゲートの実装を import**: g_blocked /
                                     mh_g / drop_one_sector_g / irr_control_g / incremental_g。
                                     同じ台帳を見る二つの検査器が違うことを言わないため）
出力    : out/hist10_angleE.json

判定・採点・台帳・index.html・パックには一切触らない。読むだけの調査。

────────────────────────────────────────────────────────────
なぜ木が新しいのか / なぜ木がいちばん危ないのか
────────────────────────────────────────────────────────────
これまで試された関数形は **単変量**(角度A) と **2本の積**(v2) と **和**(角度D) の3つ。
木は「Aが高いときだけBを見る」という**条件つきの構造**を表せる——これは和でも積でも
書けない形で、この在庫では一度も試されていない。

同時に木は**自由度が最大**＝偶然に構造を見つける力も最大である。事前診断
(night/hist10_diag.py) が結果の前にその値札を測っており、**深さ2の木を in-sample で
選ぶと雑音でも 0.577〜0.819 の確率で「合格」が出る**（和集合 0.91）。
だから木は **in-sample の最良を報告してはいけない**。事前登録 v3 の
`pass_line.for_D_and_E` が「外側foldでの性能のみを合否に使う」と書いているのはそのため。
本道具は **外側fold の性能だけ**を合否に使い、in-sample は参考値として別に出す。

────────────────────────────────────────────────────────────
結果を見る前に固定した設計（すべて診断・角度A/D と揃える）
────────────────────────────────────────────────────────────
1) **母集団は P_full / P_quality**。P_moat は 2016/2017 に irr の読解が無く
   n=61-63＝分子>=20 に構造的に届かない（診断の到達可能性）＝判定不能。
2) **特徴量の部分集合は診断と同一**（cov90_14 / all20）。理由は一つ——
   診断が角度Eの偽陽性率を**この部分集合で**測っているから。別の集合にすると
   自分の手続きの値札が分からなくなる。
3) **分割点は q25/q50/q75**（診断の CUT_QS と同一）。ただし **cut は外側/内側の
   train の分位で作る**。分位は y を見ないので厳密には漏れではないが、実運用に
   忠実な側（学習側の分位を held-out へ当てる）を主にする。
   コホート全体の分位で作った版も併走させ、差を出す（`cut_basis_sensitivity`）。
4) 木は**貪欲・情報利得（エントロピー）・最小葉サイズ20**（依頼文の指定）。深さ **2 と 3**。
5) 木から群を作る mode は2つ:
   - `best_leaf`  : |p_leaf − base_train| が最大の葉ひとつ（A/D の「群」と同じ粒度）
   - `leaf_union` : 有利な側の葉すべての和集合（群は大きく lift は薄くなりやすい）
6) **方向 up/down は先に固定する。内側で選ばない。**
   外側foldごとに方向が違うと OOF 群が意味を持たなくなるため（合成すると打ち消す）。
7) **内側CV が選ぶのは depth×mode の4通りだけ**。部分集合と方向と母集団は外側に固定。
   こうすると (pop, subset, direction) ごとに解析集合が動かず、OOF を合成できる。
8) **外側5分割・内側4分割。分割は会社(ticker)単位。**
   y10 は TRIO(2016/2017/2018) を**プール**するので、同じ ticker の3行が
   train と test に跨がらないことが要る（同じ956社が3回出てくる在庫だから）。
9) **合否は外側foldの性能のみ**。OOF 群に対して事前登録の全ゲートを当てる:
   |lift|>=0.15 ／ 分子>=20 ／ 2016・2017・2018 で維持 ／ 業種(MH・1つ抜き) ／
   irr>=70 層 ／ 増分（既存関門で7割超が説明されたら不合格）。

────────────────────────────────────────────────────────────
⚠ 目的変数のうち字義どおり判定できるのは y10 だけ（結果の前に確定している）
────────────────────────────────────────────────────────────
診断の target_judgeability がそう出しており、角度B・角度C も同じ壁で止まっている。
  y10      : 2013/2015/2016/2017/2018 で定義 → **判定可能**
  y_persist: **2013 でしか定義できない**（前半窓が2013起点でしか復元できない）
             → sign_stability(2016/2017/2018) を構造的に満たせない＝**判定不能**
  y_biz    : 2013/2015/2018 にしか分解の在庫が無い → 同じく**判定不能**
さらに特徴量の側にも壁がある（実測: 被覆>=50% の列）——
  2013/2015 は co_*（**約94%が look-ahead を含む**）のみ、2016/2017 は f2_* のみ、
  2018 は f2_* + pa_* + hv_*。
したがって y_persist は **look-ahead を含む特徴量でしか当てられない**。
y_persist / y_biz は「事前登録の外の診断」として外側fold性能だけ出し、**合否には数えない**。

────────────────────────────────────────────────────────────
⚠ この角度が構造的に抱えるもの（結果の前に書く）
────────────────────────────────────────────────────────────
・2016/2017/2018 は**同じ956ティッカー**（Jaccard=1.00）＝3ビンテージは独立な3つの
  証拠ではない。プールしても独立な会社数は増えない（実効 n は行数ではなく会社数）。
・complete-case で作るので all20 は母集団の約26%しか残らず、規模の大きい側へ偏る。
・2018窓はAI相場。前期/後期の分割は角度D が同じ配置で出している。
・木の偽陽性率は in-sample で 0.58〜0.82。**外側fold にした瞬間に 0.01〜0.03 まで落ちる**
  （診断の実測）＝この道具の値打ちはほぼ全部「外側でしか測らない」ことにある。
"""

import json
import math
import os
import random
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import hist10_diag as D          # noqa: E402  原始関数（再実装しない）
import hist10_angleD as AD       # noqa: E402  既存関門とゲートの実装（再実装しない）

OUT = os.path.join(os.path.dirname(HERE), "out")
DEST = os.path.join(OUT, "hist10_angleE.json")

# ── 事前登録の線。**この道具は一つも作らない** ──
LIFT = D.LIFT                     # 0.15
MIN_NUM = D.MIN_NUM               # 20
INCREMENTAL_MAX_CAUGHT = 0.70     # prereg pass_line.incremental
TRIO = D.TRIO                     # [2016, 2017, 2018]
POPS = D.POPS                     # ["P_full", "P_quality"]
SUBSETS = D.SUBSETS               # cov90_14 / all20（診断と同一）
CUT_QS = D.CUT_QS                 # [0.25, 0.50, 0.75]（診断と同一）
SEED = D.SEED

# ── 木の設計（依頼文の指定。結果の前に固定） ──
MIN_LEAF = 20
DEPTHS = (2, 3)
MODES = ("best_leaf", "leaf_union")
DIRS = ("up", "down")
N_OUTER = 5
N_INNER = 4

N_PERM = int(os.environ.get("HIST10E_NPERM", 2000))
N_POWER = int(os.environ.get("HIST10E_NPOWER", 200))
FAST = os.environ.get("HIST10E_FAST") == "1"

# co_* は 2013/2015 でしか無く、**約94%が look-ahead を含む**（panel の既知の非対称）
CO_COLS = ["co_opm", "co_roic_med5", "co_roic_latest", "co_roic_worst5", "co_sales_cagr5",
           "co_fcf_conv_5y", "co_fcf_all_pos", "co_op_all_pos", "co_equity_neg",
           "co_rev_asof", "co_score"]


def r4(x):
    return None if x is None else round(x, 4)


def rate(k, n):
    return (k / n) if n else None


def spearman(xs, ys):
    return AD.spearman(xs, ys)


# ─────────────────────── 解析集合 ───────────────────────
def build_set(rows, target, vints, cols, pop):
    """complete-case（その部分集合の全列が数値）・目的が定義済み・母集団条件。"""
    rs = []
    for r in rows:
        if r["vintage"] not in vints:
            continue
        if pop == "P_quality" and not r.get("P_quality"):
            continue
        if pop == "P_moat" and not r.get("P_moat"):
            continue
        if r.get(target) is None:
            continue
        ok = True
        for c in cols:
            v = r.get(c)
            if v is None or isinstance(v, str):
                ok = False
                break
        if ok:
            rs.append(r)
    return rs


def ticker_folds(rs, k, seed):
    """**会社単位**の分割。同じ ticker の全ビンテージが同じ fold に入る。"""
    ts = sorted({r["ticker"] for r in rs})
    order = list(ts)
    random.Random(seed).shuffle(order)
    assign = {t: i % k for i, t in enumerate(order)}
    masks = []
    for f in range(k):
        m = 0
        for i, r in enumerate(rs):
            if assign[r["ticker"]] == f:
                m |= (1 << i)
        masks.append(m)
    return masks


def cond_grid(rs, cols, train_mask, full):
    """条件＝『列 >= 分位点』。**分位点は train_mask の行だけから作る**。
    木は分割で両側を見るので `<` 版は要らない（診断の連言列挙と違う点）。"""
    idx = [i for i in range(len(rs)) if (train_mask >> i) & 1]
    out = []
    seen = set()
    for c in cols:
        vals = [float(rs[i][c]) for i in idx]
        for q in CUT_QS:
            cut = D.quantile(vals, q)
            if cut is None:
                continue
            m = 0
            for i, r in enumerate(rs):
                if float(r[c]) >= cut:
                    m |= (1 << i)
            mc = m.bit_count()
            if mc == 0 or mc == len(rs):
                continue
            key = (c, m)
            if key in seen:
                continue
            seen.add(key)
            out.append(("%s>=q%d" % (c, int(q * 100)), c, m))
    return out


# ─────────────────────── 木 ───────────────────────
def _went(k, n):
    """重み付きエントロピー n·H(k/n)（nat）。0log0=0。"""
    if n <= 0 or k <= 0 or k >= n:
        return 0.0
    p = k / n
    return -n * (p * math.log(p) + (1 - p) * math.log(1 - p))


def grow(rule_mask, node_mask, depth, lm, conds, full, leaves, splits, level, min_leaf, path):
    """貪欲・情報利得・最小葉サイズ。
    rule_mask = 全行に対する経路の充足マスク（held-out へそのまま当てられる）
    node_mask = rule_mask & train_mask（学習側の節）
    path      = 人が読める経路（'x>=q50' / '!x>=q50'）"""
    n = node_mask.bit_count()
    k = (node_mask & lm).bit_count()
    if depth <= 0 or n < 2 * min_leaf:
        leaves.append((rule_mask, n, k, path))
        return
    base_w = _went(k, n)
    best = None
    for ci in range(len(conds)):
        cm = conds[ci][2]
        L = node_mask & cm
        nl = L.bit_count()
        if nl < min_leaf:
            continue
        nr = n - nl
        if nr < min_leaf:
            continue
        kl = (L & lm).bit_count()
        gain = base_w - _went(kl, nl) - _went(k - kl, nr)
        if best is None or gain > best[0]:
            best = (gain, ci, L, nl)
    if best is None or best[0] <= 1e-12:
        leaves.append((rule_mask, n, k, path))
        return
    _, ci, L, _nl = best
    name, col, cm = conds[ci]
    splits.append({"level": level, "cond": name, "col": col, "n_node": n})
    inv = full ^ cm
    grow(rule_mask & cm, L, depth - 1, lm, conds, full, leaves, splits, level + 1, min_leaf,
         path + [name])
    grow(rule_mask & inv, node_mask & inv, depth - 1, lm, conds, full, leaves, splits,
         level + 1, min_leaf, path + ["!" + name])


def grow_once(train_mask, conds, lm, full, depth, min_leaf=MIN_LEAF):
    """木を1本だけ育てる。**mode も direction もここでは使わない**ので、
    育てた1本から4通り（mode×direction）の群を取り出せる＝置換の費用が1/4になる。"""
    leaves, splits = [], []
    grow(full, train_mask, depth, lm, conds, full, leaves, splits, 0, min_leaf, [])
    ntr = train_mask.bit_count()
    base_tr = (train_mask & lm).bit_count() / ntr if ntr else 0.0
    return leaves, splits, base_tr


def extract(leaves, base_tr, direction, mode, min_leaf=MIN_LEAF):
    """木の葉から『群』を作る。方向は外から固定される。"""
    cand = [x for x in leaves if x[1] >= min_leaf]
    if not cand:
        return 0, []
    if mode == "best_leaf":
        best = None
        for rm, n, k, path in cand:
            d = k / n - base_tr
            if (d > 0) if direction == "up" else (d < 0):
                if best is None or abs(d) > abs(best[0]):
                    best = (d, rm, path, n, k)
        if not best:
            return 0, []
        return best[1], [{"path": best[2], "n_train": best[3], "k_train": best[4],
                          "p_train": r4(rate(best[4], best[3]))}]
    m = 0
    used = []
    for rm, n, k, path in cand:
        d = k / n - base_tr
        if (d > 0) if direction == "up" else (d < 0):
            m |= rm
            used.append({"path": path, "n_train": n, "k_train": k,
                         "p_train": r4(rate(k, n))})
    return m, used


# ─────────────────────── 入れ子交差検証 ───────────────────────
class Cell:
    """(target, pop, subset, vints) ごとに一度だけ作る。fold と条件格子は
    ラベルに依存しないので**置換のたびに作り直さない**（速度の全部がここ）。"""

    def __init__(self, rows, target, name_target, vints, sname, cols, pop, seed):
        self.target = target
        self.name_target = name_target
        self.vints = list(vints)
        self.sname = sname
        self.cols = list(cols)
        self.pop = pop
        self.rs = build_set(rows, target, vints, cols, pop)
        self.n = len(self.rs)
        self.full = (1 << self.n) - 1 if self.n else 0
        self.ok = self.n >= 100
        if not self.ok:
            return
        self.outer_te = ticker_folds(self.rs, N_OUTER, seed)
        self.outer = [(self.full ^ te, te) for te in self.outer_te]
        # 内側は外側trainの中で、やはり会社単位
        self.inner = []
        for fi, (tr, _te) in enumerate(self.outer):
            sub = [i for i in range(self.n) if (tr >> i) & 1]
            ts = sorted({self.rs[i]["ticker"] for i in sub})
            order = list(ts)
            random.Random(seed + 1000 + fi).shuffle(order)
            assign = {t: i % N_INNER for i, t in enumerate(order)}
            ff = []
            for g in range(N_INNER):
                ite = 0
                for i in sub:
                    if assign[self.rs[i]["ticker"]] == g:
                        ite |= (1 << i)
                ff.append((tr & ~ite & self.full, ite))
            self.inner.append(ff)
        # 条件格子（train の分位）—— ラベル非依存なので一度だけ
        self.grid_outer = [cond_grid(self.rs, cols, tr, self.full) for tr, _ in self.outer]
        self.grid_inner = [[cond_grid(self.rs, cols, itr, self.full) for itr, _ in ff]
                           for ff in self.inner]
        self.grid_all = cond_grid(self.rs, cols, self.full, self.full)
        # 業種の層（MH 用）
        self.strata = defaultdict(list)
        for i, r in enumerate(self.rs):
            if r.get("sic2"):
                self.strata[r["sic2"]].append(i)

    def label_mask(self, labs=None):
        """labs=None なら実データ。labs は {vintage: {ticker: 0/1}}（置換）。"""
        m = 0
        for i, r in enumerate(self.rs):
            if labs is None:
                x = r.get(self.target)
            else:
                x = labs.get(r["vintage"], {}).get(r["ticker"])
            if x:
                m |= (1 << i)
        return m

    def nested_both(self, lm, min_leaf=MIN_LEAF, keep_detail=True):
        """外側foldの性能のみ。選択は内側、評価は held-out。
        **up と down を同時に返す**（木は方向に依らないので育て直さない）。"""
        oof = {"up": 0, "down": 0}
        chosen = {"up": [], "down": []}
        for fi, (tr, te) in enumerate(self.outer):
            ntr = tr.bit_count()
            base_tr = (tr & lm).bit_count() / ntr if ntr else 0.0
            # 内側: 木は (depth × inner fold) だけ育て、mode×direction は葉から取り出す
            ig = {(dp, md, dr): 0 for dp in DEPTHS for md in MODES for dr in DIRS}
            for gi, (itr, ite) in enumerate(self.inner[fi]):
                g = self.grid_inner[fi][gi]
                for dp in DEPTHS:
                    leaves, _sp, b = grow_once(itr, g, lm, self.full, dp, min_leaf)
                    for md in MODES:
                        for dr in DIRS:
                            rm, _u = extract(leaves, b, dr, md, min_leaf)
                            ig[(dp, md, dr)] |= (rm & ite)
            best = {"up": None, "down": None}
            for dr in DIRS:
                for dp in DEPTHS:
                    for md in MODES:
                        gg = ig[(dp, md, dr)]
                        m = gg.bit_count()
                        if m == 0:
                            continue
                        k = (gg & lm).bit_count()
                        lf = k / m - base_tr
                        s = lf if dr == "up" else -lf
                        if m < MIN_NUM:
                            s -= 1e6          # 退化した群は選ばない
                        if best[dr] is None or s > best[dr][0]:
                            best[dr] = (s, dp, md)
            # 外側train で選ばれた深さの木を育て直す（深さは高々2通り）
            trees = {}
            for dr in DIRS:
                if best[dr] is None:
                    chosen[dr].append(None)
                    continue
                _s, dp, md = best[dr]
                if dp not in trees:
                    trees[dp] = grow_once(tr, self.grid_outer[fi], lm, self.full, dp, min_leaf)
                leaves, splits, b = trees[dp]
                rm, used = extract(leaves, b, dr, md, min_leaf)
                oof[dr] |= (rm & te)
                ent = {"fold": fi, "depth": dp, "mode": md, "inner_score": r4(_s),
                       "n_rule_train": (rm & tr).bit_count(),
                       "n_rule_test": (rm & te).bit_count()}
                if keep_detail:
                    ent["splits"] = splits
                    ent["leaves_used"] = used
                chosen[dr].append(ent)
        return oof, chosen

    def in_sample(self, lm, direction, depth=3, mode="best_leaf"):
        """**参考値**。合否には使わない（診断の実測: 木の in-sample 偽陽性率 0.58〜0.82）。"""
        leaves, splits, base = grow_once(self.full, self.grid_all, lm, self.full, depth)
        rm, used = extract(leaves, base, direction, mode)
        m = rm.bit_count()
        k = (rm & lm).bit_count()
        return {"depth": depth, "mode": mode, "n_group": m, "k": k,
                "p_group": r4(rate(k, m)), "base": r4(base),
                "lift": r4((k / m - base) if m else None),
                "splits": splits, "leaves_used": used,
                "⚠": "in-sample。診断の実測では木を in-sample で選ぶと雑音でも "
                     "0.577〜0.819 の確率で『合格』が出る＝**合否には使わない**"}


# ─────────────────────── ゲート（角度D の実装を呼ぶ） ───────────────────────
def gate_stats(cell, lm, oof, direction):
    """OOF 群に対する gate1（lift・分子・符号不変）。

    ⚠**分子の単位**: 事前登録は「事象の分子 >= 20**社**」と書いている。角度A/D は
    1ビンテージのコホート（1社=1行）で測るので行数=社数だった。ここは TRIO を
    プールするので **1行 = (会社, ビンテージ)** であり、行で数えると同じ会社を
    最大3回数えてしまう。よって**登録ゲートは「事象を持つ相異なる会社の数」**で当てる
    （行で数えるより必ず厳しい側＝線を緩めていない）。行の数も併記する。"""
    n = cell.n
    m = oof.bit_count()
    k = (oof & lm).bit_count()
    base = (lm.bit_count() / n) if n else 0.0
    lf = (k / m - base) if m else None
    sgn = 1 if direction == "up" else -1
    co_g, co_k = set(), set()
    for i in range(n):
        if (oof >> i) & 1:
            t = cell.rs[i]["ticker"]
            co_g.add(t)
            if (lm >> i) & 1:
                co_k.add(t)
    per_v = {}
    for v in cell.vints:
        vm = 0
        for i, r in enumerate(cell.rs):
            if r["vintage"] == v:
                vm |= (1 << i)
        nv = vm.bit_count()
        if not nv:
            continue
        bv = (vm & lm).bit_count() / nv
        gv = oof & vm
        mv = gv.bit_count()
        kv = (gv & lm).bit_count()
        per_v[str(v)] = {"n": nv, "base": r4(bv), "n_group": mv, "k": kv,
                         "p_group": r4(rate(kv, mv)),
                         "lift": r4((kv / mv - bv) if mv else None)}
    sign_applicable = all(v in cell.vints for v in TRIO)
    sign_ok = None
    if sign_applicable:
        vals = [per_v.get(str(v), {}).get("lift") for v in TRIO]
        sign_ok = all(x is not None and abs(x) >= LIFT and (1 if x > 0 else -1) == sgn
                      for x in vals)
    return {"n_rows": n, "base": r4(base), "n_group": m, "numerator": k,
            "n_group_companies": len(co_g), "numerator_companies": len(co_k),
            "p_group": r4(rate(k, m)), "lift": r4(lf),
            "lift_ok": (lf is not None and abs(lf) >= LIFT and (1 if lf > 0 else -1) == sgn),
            "min_num_ok": len(co_k) >= MIN_NUM,
            "min_num_ok_row_reading": k >= MIN_NUM,
            "min_num_unit": "相異なる会社（登録の『20社』の字義。行で数える版も併記）",
            "per_vintage": per_v,
            "sign_stability_applicable": sign_applicable,
            "sign_ok": sign_ok,
            "effective_required_lift": r4(max(LIFT, (MIN_NUM / m - base)) if m else None)}


def mh_pooled(cell, lm, oof):
    """業種調整をプールした行の上でも測る（**診断であって合否ではない**）。

    なぜ要るか——角度D の mh_g は**ビンテージごと**に当てる。木の OOF 群は
    TRIO をプールして作るので1ビンテージあたりの群は約1/3に痩せ、45前後ある sic2 の
    多くで群が3行未満になり `n1<3` で落ちる。**層が落ちて測れないのか、
    それとも本当に業種の影なのか**を切り分けるために、同じ重み（D.mh_diff）と
    同じ足切り（AD.mh_g の n1>=3・n0>=3）のまま、層の作り方だけ変えて併記する。
      by_sic        : 層 = sic2（ビンテージを跨いでプール。⚠年で基準率が違うので混ぜている）
      by_sic_vintage: 層 = sic2 × ビンテージ（最も厳しい・年の違いを混ぜない）"""
    out = {}
    for name, keyf in (("by_sic", lambda r: r.get("sic2")),
                       ("by_sic_vintage", lambda r: (r.get("sic2"), r["vintage"]))):
        st = defaultdict(list)
        for i, r in enumerate(cell.rs):
            if r.get("sic2"):
                st[keyf(r)].append(i)
        keep, used, dropped = {}, 0, 0
        for kk, idxs in st.items():
            n1 = sum(1 for i in idxs if (oof >> i) & 1)
            n0 = len(idxs) - n1
            if n1 < 3 or n0 < 3:
                dropped += 1
                continue
            keep[kk] = idxs
            used += 1
        val = D.mh_diff(lm, oof, keep, cell.full) if keep else None
        rows_kept = sum(len(v) for v in keep.values())
        grp_kept = sum(1 for kk in keep for i in keep[kk] if (oof >> i) & 1)
        out[name] = {"mh_risk_diff": r4(val), "strata_used": used, "strata_dropped": dropped,
                     "rows_in_kept_strata": rows_kept,
                     "group_rows_in_kept_strata": grp_kept,
                     "group_rows_total": oof.bit_count(),
                     "share_of_group_measurable": r4(rate(grp_kept, oof.bit_count()))}
    return out


def sector_composition(cell, lm, oof, top=8):
    """群がどの業種で出来ているか。**生の lift と MH の差の正体を名前で見る**ため。

    生の lift − MH（業種内） ＝ 業種間の差（＝業種の影）。その差が大きいとき、
    どの sic2 がそれを作っているのかは数字だけでは分からないので並べる。"""
    n = cell.n
    tot = defaultdict(int)
    tot_k = defaultdict(int)
    grp = defaultdict(int)
    grp_k = defaultdict(int)
    for i, r in enumerate(cell.rs):
        s = r.get("sic2") or "?"
        tot[s] += 1
        if (lm >> i) & 1:
            tot_k[s] += 1
        if (oof >> i) & 1:
            grp[s] += 1
            if (lm >> i) & 1:
                grp_k[s] += 1
    m = oof.bit_count()
    rows = []
    for s in sorted(grp, key=lambda x: -grp[x])[:top]:
        rows.append({
            "sic2": s,
            "group_rows": grp[s], "share_of_group": r4(rate(grp[s], m)),
            "share_of_population": r4(rate(tot[s], n)),
            "sector_base_rate": r4(rate(tot_k[s], tot[s])),
            "group_rate_in_sector": r4(rate(grp_k[s], grp[s])),
            "within_sector_lift": r4((grp_k[s] / grp[s] - tot_k[s] / tot[s])
                                     if grp[s] and tot[s] else None),
        })
    return {"population_base": r4(lm.bit_count() / n),
            "top_sectors_in_group": rows,
            "read": "share_of_group が share_of_population より大きく、その業種の "
                    "sector_base_rate が母集団の base と大きく違うなら、生の lift の一部は"
                    "**業種の構成**が作っている（MH はそれを取り除いた値）"}


def _ustub(cell, v):
    return {(cell.sname, cell.pop, v): [r for r in cell.rs if r["vintage"] == v]}


def _gset(cell, oof, v):
    return {cell.rs[i]["ticker"] for i in range(cell.n)
            if ((oof >> i) & 1) and cell.rs[i]["vintage"] == v}


def full_gates(cell, lm, oof, direction, target):
    """**角度D の実装をそのまま呼ぶ**（同じ閾値・同じ足切り）。OOF 群に当てる。"""
    sgn = 1 if direction == "up" else -1
    res = {}
    vints = [v for v in cell.vints]
    mh, dos = {}, {}
    for v in vints:
        U = _ustub(cell, v)
        g = _gset(cell, oof, v)
        mh[str(v)] = AD.mh_g(U, cell.sname, cell.pop, v, g, ykey=target)
        dos[str(v)] = AD.drop_one_sector_g(U, cell.sname, cell.pop, v, g, ykey=target)
    res["mh"] = mh
    res["mh_pooled_diagnostic"] = mh_pooled(cell, lm, oof)
    res["sector_composition"] = sector_composition(cell, lm, oof)
    res["drop_one_sector"] = dos
    if any(x is None for x in mh.values()) or any(x is None for x in dos.values()):
        res["verdict"] = "判定不能"
        res["gate_failed_at"] = "sector_control(測定不能)"
        return res
    mh_ok = all(x["mh_risk_diff"] is not None and abs(x["mh_risk_diff"]) >= LIFT
                and (1 if x["mh_risk_diff"] > 0 else -1) == sgn for x in mh.values())
    dos_ok = all(x["lift"] is not None and abs(x["lift"]) >= LIFT
                 and (1 if x["lift"] > 0 else -1) == sgn for x in dos.values())
    res["mh_ok"] = mh_ok
    res["drop_one_sector_ok"] = dos_ok
    if not (mh_ok and dos_ok):
        res["verdict"] = "不合格"
        res["gate_failed_at"] = "sector_control"
        return res
    vlast = vints[-1]
    U = _ustub(cell, vlast)
    g = _gset(cell, oof, vlast)
    sbt = {r["ticker"]: (1.0 if r["ticker"] in g else 0.0) for r in U[(cell.sname, cell.pop, vlast)]}
    irr = AD.irr_control_g(U, cell.sname, cell.pop, vlast, g, sbt, ykey=target)
    res["irr"] = {str(vlast): irr}
    lay = irr.get("irr_ge70", {}).get("lift")
    if lay is None and not irr.get("orthogonal_hint"):
        res["verdict"] = "判定不能"
        res["gate_failed_at"] = "not_irr_shadow"
        return res
    if not (irr.get("orthogonal_hint") is True or (lay is not None and abs(lay) >= LIFT)):
        res["verdict"] = "不合格"
        res["gate_failed_at"] = "not_irr_shadow"
        return res
    inc = {}
    for v in vints:
        inc[str(v)] = AD.incremental_g(_ustub(cell, v), cell.sname, cell.pop, v,
                                       _gset(cell, oof, v), direction, ykey=target)
    res["incremental"] = inc
    if any("status" in inc[str(v)] for v in vints):
        res["verdict"] = "判定不能"
        res["gate_failed_at"] = "incremental(測定不能)"
        return res
    if direction == "up":
        ls = [inc[str(v)].get("lift") for v in vints]
        shares = [inc[str(v)].get("share_of_group_already_blocked") for v in vints]
        inc_ok = all(x is not None and abs(x) >= LIFT and (1 if x > 0 else -1) == sgn
                     for x in ls)
        blocked_ok = all(s is None or s <= INCREMENTAL_MAX_CAUGHT for s in shares)
        res["incremental_summary"] = {"lift_within_gate_passers": ls,
                                      "share_already_blocked": shares, "line": LIFT,
                                      "max_caught_line": INCREMENTAL_MAX_CAUGHT}
        ok = inc_ok and blocked_ok
    else:
        tot = sum(inc[str(v)].get("n_failures_in_group", 0) for v in vints)
        cau = sum(inc[str(v)].get("already_caught", 0) for v in vints)
        sh = rate(cau, tot)
        res["incremental_summary"] = {"caught_share": r4(sh),
                                      "max_caught_line": INCREMENTAL_MAX_CAUGHT}
        ok = sh is not None and sh <= INCREMENTAL_MAX_CAUGHT
    res["incremental_ok"] = ok
    if not ok:
        res["verdict"] = "不合格"
        res["gate_failed_at"] = "incremental"
        return res
    res["verdict"] = "合格"
    return res


def gate1_pass(gs):
    return bool(gs["lift_ok"] and gs["min_num_ok"] and gs["sign_ok"] is True)


# ─────────────────────── 偽陽性率 ───────────────────────
def fpr_y10(cells, rows, n_perm, seed):
    """会社単位で全ビンテージ同時に y10 を並べ替える（診断の perm_engine をそのまま使う）。"""
    draw, _to_masks, info = D.perm_engine(rows, {}, seed=seed)
    keys = sorted(cells.keys())
    hit_cell = Counter()
    hit_any = 0
    hit_any_full = 0
    for _pi in range(n_perm):
        if _pi % 200 == 0:
            print("  [fpr] %d/%d" % (_pi, n_perm), file=sys.stderr, flush=True)
        labs = draw(True)
        any_pass = False
        any_full = False
        for kk in keys:
            c = cells[kk]
            lm = c.label_mask(labs)
            oof, _ch = c.nested_both(lm, keep_detail=False)
            for d in DIRS:
                gs = gate_stats(c, lm, oof[d], d)
                if gate1_pass(gs):
                    hit_cell[(kk, d)] += 1
                    any_pass = True
                    fg = full_gates(c, lm, oof[d], d, "y10")
                    if fg.get("verdict") == "合格":
                        any_full = True
        if any_pass:
            hit_any += 1
        if any_full:
            hit_any_full += 1
    se = math.sqrt(max(hit_any, 1) / n_perm * (1 - hit_any / n_perm) / n_perm)
    return {
        "n_perm": n_perm,
        "null": "会社単位・sic2層内・全ビンテージ同時（診断 perm_engine をそのまま使用）",
        "perm_engine_info": info,
        # ⚠ kk は "P_full|cov90_14" という**文字列**。kk[0]/kk[1] と書くと
        #    'P' と '_' になり4セルすべてが同じキーに潰れる（初版のバグ・実測で発見）
        "by_cell_gate1": {("%s|%s" % (kk, d)):
                          {"rate": r4(hit_cell[(kk, d)] / n_perm),
                           "hits": hit_cell[(kk, d)]}
                          for kk in keys for d in DIRS},
        "union_gate1": r4(hit_any / n_perm),
        "union_all_gates": r4(hit_any_full / n_perm),
        "mc_se_union_gate1": r4(se),
        "reading": "『探索者が (母集団×部分集合×方向) を全部試す場合』の値札。"
                   "in-sample の木は診断が 0.577〜0.819 と測っている——外側foldにすると何処まで落ちるか",
    }


# ─────────────────────── 検出力（陽性対照の注入） ───────────────────────
def power_inject(cell, deltas, reps, seed, direction="up", full_gate_at=None):
    """真の規則を仕込んで、この手続きが掴めるかを数える。

    ⚠ ラベルは行ごとに独立に引く＝**同じ会社の3行の相関を無視している**ので、
       実データより有利な条件での検出力（上限側の推定）。
    `full_gate_at` に δ を渡すと、その δ で **gate1 の先（業種・irr・増分）まで**
    通るかも数える＝『後段のゲートが木の形の群に対して到達可能か』の実測。
    到達不能なら実データの落ち方は「不合格」ではなく「判定不能」と読むべき（v1の敗因）。"""
    rnd = random.Random(seed)
    n = cell.n
    base = sum(1 for r in cell.rs if r.get(cell.target)) / n
    grid = cell.grid_all
    # 群の大きさが 15〜35% になる条件対を集める（真の規則の候補）
    cands = []
    for i in range(len(grid)):
        for j in range(i + 1, len(grid)):
            g = grid[i][2] & grid[j][2]
            s = g.bit_count() / n
            if 0.15 <= s <= 0.35:
                cands.append(g)
    if not cands:
        return {"status": "真の規則にできる条件対が無い"}
    sgn = 1 if direction == "up" else -1
    out = {}
    for delta in deltas:
        hits = 0
        full_hits = 0
        gate_fail = Counter()
        su, mhv, pooled = [], [], []
        do_full = (full_gate_at is not None and abs(delta - full_gate_at) < 1e-9)
        for _ in range(reps):
            g = cands[rnd.randrange(len(cands))]
            m = g.bit_count()
            p_in = min(0.98, max(0.02, base + sgn * delta))
            p_out = min(0.98, max(0.02, base - sgn * delta * m / (n - m)))
            lm = 0
            for i in range(n):
                p = p_in if ((g >> i) & 1) else p_out
                if rnd.random() < p:
                    lm |= (1 << i)
            oof, _ch = cell.nested_both(lm, keep_detail=False)
            gs = gate_stats(cell, lm, oof[direction], direction)
            if gate1_pass(gs):
                hits += 1
                if do_full:
                    fg = full_gates(cell, lm, oof[direction], direction, cell.target)
                    if fg.get("verdict") == "合格":
                        full_hits += 1
                    else:
                        gate_fail[fg.get("gate_failed_at") or "?"] += 1
                    for _v, x in (fg.get("mh") or {}).items():
                        if x and x.get("strata_used") is not None:
                            su.append(x["strata_used"])
                            mhv.append(abs(x["mh_risk_diff"]))
                    pd = (fg.get("mh_pooled_diagnostic") or {}).get("by_sic_vintage")
                    if pd and pd.get("mh_risk_diff") is not None:
                        pooled.append(abs(pd["mh_risk_diff"]))
        ent = {"reps": reps, "detected_gate1": hits, "power_gate1": r4(hits / reps),
               "mc_se": r4(math.sqrt(max(hits, 1) / reps * (1 - hits / reps) / reps))}
        if do_full:
            ent["passed_all_gates"] = full_hits
            ent["power_all_gates"] = r4(full_hits / reps)
            ent["conditional_on_gate1"] = r4(rate(full_hits, hits))
            ent["where_the_injected_truth_died"] = dict(gate_fail)
            ent["mh_diagnostics_on_injected_truth"] = {
                "mean_strata_used": r4(sum(su) / len(su)) if su else None,
                "mean_abs_mh": r4(sum(mhv) / len(mhv)) if mhv else None,
                "mean_abs_mh_pooled_sic_x_vintage":
                    r4(sum(pooled) / len(pooled)) if pooled else None,
                "read": "真の効果 δ=0.25 を仕込んでも MH がこの値までしか出ないなら、"
                        "落ちているのは効果ではなく**層の薄さ**",
            }
        out["delta_%.2f" % delta] = ent
    out["_note"] = ("真の規則は『条件2つの積・群は母集団の15〜35%』。ラベルは行独立に引くので"
                    "**実データより有利な**推定。方向=" + direction)
    return out


# ─────────────────────── (c) 変数の一致 ───────────────────────
def variable_agreement(real_cells):
    """木が選んだ分割変数を数え、A/C/D の結果と突き合わせる。"""
    tally = defaultdict(Counter)
    root = defaultdict(Counter)
    for key, ent in real_cells.items():
        for d in DIRS:
            ch = ent["directions"][d]["chosen"]
            for c in ch:
                if not c:
                    continue
                for s in c["splits"]:
                    tally[key][s["col"]] += 1
                    if s["level"] == 0:
                        root[key][s["col"]] += 1
    def top(cnt, k=8):
        return [{"col": c, "n": n} for c, n in cnt.most_common(k)]
    per_cell = {}
    for key in tally:
        rr = root[key]
        tot_root = sum(rr.values())
        per_cell[key] = {
            "split_vars_all_levels": top(tally[key]),
            "root_vars": top(rr),
            "root_stability": r4(max(rr.values()) / tot_root) if tot_root else None,
            "root_stability_read": "外側5fold×2方向の根が同じ変数になった割合",
        }
    allv = Counter()
    allr = Counter()
    for key in tally:
        allv.update(tally[key])
        allr.update(root[key])
    return {"per_cell": per_cell,
            "pooled_split_vars": top(allv, 12),
            "pooled_root_vars": top(allr, 12)}


def read_other_angles():
    """A / C / D の結論を**ファイルから読む**（記憶で書かない）。"""
    out = {}
    p = os.path.join(OUT, "hist10_angleA.json")
    if os.path.exists(p):
        a = json.load(open(p, encoding="utf-8"))
        out["A"] = {
            "n_pass": a["verdict_counts"]["n_pass"],
            "top_up": [{"variable": x["variable"], "pop": x["population"], "cut": x["cut"],
                        "min_abs_lift_161718": x["min_abs_lift_161718"],
                        "verdict": x["verdict"]} for x in a.get("top_up_15", [])[:5]],
            "top_down": [{"variable": x["variable"], "pop": x["population"], "cut": x["cut"],
                          "min_abs_lift_161718": x["min_abs_lift_161718"],
                          "verdict": x["verdict"]} for x in a.get("top_down_15", [])[:5]],
        }
    p = os.path.join(OUT, "hist10_angleB.json")
    if os.path.exists(p):
        b = json.load(open(p, encoding="utf-8"))
        out["B"] = {"n_pass": b.get("n_pass_total"),
                    "why": b["verdict"].get("B1_is_structurally_unfair", {}).get("why")}
    p = os.path.join(OUT, "hist10_angleC.json")
    if os.path.exists(p):
        c = json.load(open(p, encoding="utf-8"))
        out["C"] = {"n_pass": c["★verdict"]["prereg_pass_count"],
                    "headline": c["★verdict"]["headline"]}
    p = os.path.join(OUT, "hist10_angleD.json")
    if os.path.exists(p):
        dd = json.load(open(p, encoding="utf-8"))
        out["D"] = {"n_pass": dd.get("n_pass_all_gates"),
                    "passes": [{"pop": x["pop"], "subset": x["subset"], "sel": x["sel"],
                                "sides": x["sides"], "s": x["s"], "J": x["J"],
                                "direction": x["direction"]} for x in dd.get("passes", [])]}
    return out


# ─────────────────────── 自己検査 ───────────────────────
def self_checks(cells):
    out = {}
    # (1) OOF は各行をちょうど1回ずつ test にする
    part = []
    for key, c in cells.items():
        u = 0
        ok = True
        for _tr, te in c.outer:
            if u & te:
                ok = False
            u |= te
        part.append({"cell": key, "covers_all_rows": u == c.full, "no_overlap": ok})
    out["outer_folds_partition"] = {"cells": part,
                                    "all_ok": all(x["covers_all_rows"] and x["no_overlap"]
                                                  for x in part)}
    # (2) 会社が train と test に跨がらない
    leak = []
    for key, c in cells.items():
        bad = 0
        for tr, te in c.outer:
            a = {c.rs[i]["ticker"] for i in range(c.n) if (tr >> i) & 1}
            b = {c.rs[i]["ticker"] for i in range(c.n) if (te >> i) & 1}
            bad += len(a & b)
        for fi, ff in enumerate(c.inner):
            for itr, ite in ff:
                a = {c.rs[i]["ticker"] for i in range(c.n) if (itr >> i) & 1}
                b = {c.rs[i]["ticker"] for i in range(c.n) if (ite >> i) & 1}
                bad += len(a & b)
        leak.append({"cell": key, "tickers_on_both_sides": bad})
    out["no_company_leak"] = {"cells": leak,
                              "all_ok": all(x["tickers_on_both_sides"] == 0 for x in leak)}
    # (3) bitset と素朴な数え方が一致するか
    mism = 0
    checked = 0
    for key, c in list(cells.items())[:2]:
        lm = c.label_mask()
        oof, _ = c.nested_both(lm, keep_detail=False)
        for d in DIRS:
            m1 = oof[d].bit_count()
            k1 = (oof[d] & lm).bit_count()
            idx = [i for i in range(c.n) if (oof[d] >> i) & 1]
            m2 = len(idx)
            k2 = sum(1 for i in idx if c.rs[i].get(c.target))
            checked += 1
            if m1 != m2 or k1 != k2:
                mism += 1
    out["bitset_vs_naive"] = {"checked": checked, "mismatch": mism}
    # (4) 群は葉の規則そのものか（held-out へ当てた規則が test 内に収まっているか）
    strayed = 0
    for key, c in cells.items():
        lm = c.label_mask()
        oof, ch = c.nested_both(lm)
        for d in DIRS:
            acc = 0
            for fi, (_tr, te) in enumerate(c.outer):
                acc |= (oof[d] & te)
            if acc != oof[d]:
                strayed += 1
    out["oof_group_inside_test_folds"] = {"cells_checked": len(cells) * 2, "strayed": strayed}
    return out


def reproduce_diag_tree(rows):
    """診断が同じ在庫で回した角度Eの入れ子CV（**手続きは違う**——単一ビンテージ・深さ2・
    連言全列挙）をそのまま呼んで並べる。数字を比べるためではなく、
    『同じ在庫・同じ母集団を読んでいる』ことを示すため。"""
    try:
        U = D.build_universes(rows)
        rnd = random.Random(D.SEED)
        folds = {}
        for s in SUBSETS:
            folds.update(D.make_folds(U, s, rnd))
        cj = {s: D.masks_conjunction(U, s) for s in SUBSETS}
        _draw, to_masks, _i = D.perm_engine(rows, U, seed=D.SEED)
        mm = to_masks({v: {r["ticker"]: (1 if r.get("y10") else 0)
                           for r in D.pop_rows(rows, v, "P_full")} for v in TRIO})
        out = {}
        for s in SUBSETS:
            _n, det = D.eval_conjunction_cv(cj[s], mm, s, folds)
            out[s] = det
        return {"procedure": "診断 hist10_diag.eval_conjunction_cv（2018単独・深さ2・連言全列挙・"
                             "コホート全体の分位・fold は行単位）",
                "result": out,
                "why_here": "手続きが違うので数字は一致しない。**同じ在庫を読んでいる**ことの確認"}
    except Exception as e:      # noqa: BLE001
        return {"status": "呼べなかった: %s" % e}


# ─────────────────────── cut の基準の感度 ───────────────────────
def cut_basis_sensitivity(cells, rows):
    """分位点を『train で作る』（主）と『コホート全体で作る』（診断と同じ）で
    結論が変わるかを実測する。分位は y を見ないので漏れではないが、確かめる。"""
    out = {}
    for key, c in cells.items():
        lm = c.label_mask()
        oof_a, _ = c.nested_both(lm, keep_detail=False)
        go, gi = c.grid_outer, c.grid_inner
        c.grid_outer = [c.grid_all] * len(c.outer)
        c.grid_inner = [[c.grid_all] * N_INNER for _ in c.inner]
        oof_b, _ = c.nested_both(lm, keep_detail=False)
        c.grid_outer, c.grid_inner = go, gi
        row = {}
        for d in DIRS:
            ga = gate_stats(c, lm, oof_a[d], d)
            gb = gate_stats(c, lm, oof_b[d], d)
            row[d] = {"train_quantile": {"lift": ga["lift"], "n_group": ga["n_group"],
                                         "k": ga["numerator"], "gate1": gate1_pass(ga)},
                      "cohort_quantile": {"lift": gb["lift"], "n_group": gb["n_group"],
                                          "k": gb["numerator"], "gate1": gate1_pass(gb)},
                      "same_verdict": gate1_pass(ga) == gate1_pass(gb)}
        out[key] = row
    return out


# ─────────────────────── main ───────────────────────
def main():
    panel, tg, prereg, rows = D.load()
    seed = SEED

    # ── 登録された目的（判定できる） ──
    cells = {}
    skipped = {}
    for pop in POPS:
        for sname, cols in SUBSETS.items():
            c = Cell(rows, "y10", "y10", TRIO, sname, cols, pop, seed)
            if c.ok:
                cells["%s|%s" % (pop, sname)] = c
            else:
                skipped["%s|%s" % (pop, sname)] = {
                    "n_rows": c.n, "reason": "complete-case の行が100未満で入れ子CVを組めない",
                    "verdict": "判定不能"}

    # ── 事前登録の外（判定できない目的）。診断としてだけ回す ──
    aux_defs = [
        ("y_persist", [2013], "co11", CO_COLS,
         "**事前登録の外**: y_persist は2013でしか定義できず sign_stability を構造的に満たせない。"
         "さらに2013の特徴量は co_* だけで**約94%が look-ahead を含む**"),
        ("y_biz", [2018], "cov90_14", SUBSETS["cov90_14"],
         "**事前登録の外**: y_biz の分解在庫は2013/2015/2018のみ。2016/2017を作れないので"
         "符号不変ゲートを当てられない。2018は f2_*（look-ahead 無し）"),
        ("y_biz", [2018], "all20", SUBSETS["all20"],
         "**事前登録の外**（同上・特徴量20本）"),
        ("y_biz", [2015], "co11", CO_COLS,
         "**事前登録の外**（同上）。さらに2015の特徴量は co_* だけで look-ahead を含む＝"
         "2018の f2_* 版とは**基準の違う二つ**なので並べて読まないこと"),
    ]
    aux_cells = {}
    for tgt, vints, sname, cols, note in aux_defs:
        for pop in POPS:
            c = Cell(rows, tgt, tgt, vints, sname, cols, pop, seed)
            key = "%s@%s|%s|%s" % (tgt, "+".join(str(v) for v in vints), pop, sname)
            if c.ok:
                aux_cells[key] = (c, note)
            else:
                skipped[key] = {"n_rows": c.n, "verdict": "判定不能",
                                "reason": "complete-case の行が100未満で入れ子CVを組めない"}

    print("解析集合（y10・登録）:", {k: v.n for k, v in cells.items()}, file=sys.stderr)
    print("解析集合（事前登録の外）:", {k: v[0].n for k, v in aux_cells.items()}, file=sys.stderr)

    # ── 到達可能性・実効要求（結果の前に出す） ──
    reach = {}
    for key, c in cells.items():
        lm = c.label_mask()
        base = lm.bit_count() / c.n
        reach[key] = {
            "n_rows": c.n,
            "n_companies": len({r["ticker"] for r in c.rs}),
            "base": r4(base),
            "min_group_for_20_events_at_base_plus_line":
                math.ceil(MIN_NUM / (base + LIFT)) if base + LIFT > 0 else None,
            "min_group_for_20_events_at_base_minus_line":
                (math.ceil(MIN_NUM / (base - LIFT)) if base - LIFT > 0 else None),
            "down_direction_note":
                "下向きは群の中の事象が少ないほど強いので、分子>=20 は『弱い効果しか通さない』"
                "側に働く。base-0.15 で 20 事象を出すには群が %s 行要る" %
                (math.ceil(MIN_NUM / (base - LIFT)) if base - LIFT > 0 else "∞"),
        }

    # ── 本番: 実データの入れ子CV ──
    real = {}
    for key, c in cells.items():
        lm = c.label_mask()
        ent = {"pop": c.pop, "subset": c.sname, "n_rows": c.n,
               "n_companies": len({r["ticker"] for r in c.rs}),
               "vintages": c.vints, "directions": {}}
        oof, chosen = c.nested_both(lm)
        for d in DIRS:
            gs = gate_stats(c, lm, oof[d], d)
            g1 = gate1_pass(gs)
            item = {"oof": gs, "gate1_pass": g1, "chosen": chosen[d],
                    "in_sample_reference": c.in_sample(lm, d)}
            if g1:
                item["full_gates"] = full_gates(c, lm, oof[d], d, "y10")
                item["verdict"] = item["full_gates"].get("verdict")
                item["gate_failed_at"] = item["full_gates"].get("gate_failed_at")
            else:
                item["verdict"] = "不合格"
                item["gate_failed_at"] = ("lift" if not gs["lift_ok"]
                                          else "min_numerator" if not gs["min_num_ok"]
                                          else "sign_stability")
            ent["directions"][d] = item
        real[key] = ent

    # ── 事前登録の外の目的 ──
    aux = {}
    for key, (c, note) in aux_cells.items():
        lm = c.label_mask()
        ent = {"note": note, "target": c.target, "pop": c.pop, "subset": c.sname,
               "vintages": c.vints, "n_rows": c.n,
               "n_companies": len({r["ticker"] for r in c.rs}),
               "base": r4(lm.bit_count() / c.n),
               "sign_stability_applicable": False,
               "verdict": "判定不能（事前登録の sign_stability を構造的に満たせない）",
               "directions": {}}
        oof, chosen = c.nested_both(lm)
        for d in DIRS:
            gs = gate_stats(c, lm, oof[d], d)
            ent["directions"][d] = {
                "oof": gs,
                "would_pass_lift_and_min_num": bool(gs["lift_ok"] and gs["min_num_ok"]),
                "chosen_depth_mode": [(x["depth"], x["mode"]) if x else None
                                      for x in chosen[d]],
                "split_vars": [s["col"] for x in chosen[d] if x for s in x["splits"]],
                "in_sample_reference": c.in_sample(lm, d),
            }
        aux[key] = ent

    # ── 実測した構造の事実（結果を読む前に要る） ──
    facts = {}
    ybiz = {}
    for v in (2013, 2015, 2018):
        rs = [r for r in rows if r["vintage"] == v and r.get("y_biz") is not None]
        ybiz[str(v)] = {"n": len(rs),
                        "of_which_P_quality": sum(1 for r in rs if r.get("P_quality")),
                        "of_which_P_moat": sum(1 for r in rs if r.get("P_moat"))}
    facts["y_biz_rows_are_all_P_quality"] = {
        "by_vintage": ybiz,
        "meaning": "y_biz（事業由来の寄与）は**分解プールが質実証プールから作られている**ので、"
                   "y_biz が定義される行は全部 P_quality。よって y_biz の "
                   "P_full セルと P_quality セルは**同一の解析集合**であり、"
                   "同じ数字が出るのはバグではない（重複して数えないこと）",
    }
    facts["mh_strata_coverage"] = {
        "why": "木の OOF 群は小さく（1ビンテージあたり十数〜数十行）、45前後ある sic2 の"
               "多くで群が3行に満たない。角度D の mh_g は n1<3 の層を落とすので、"
               "MH は**残った少数の層だけ**で計算される。合否はD と同じ規則のまま変えないが、"
               "『何層で測ったか』を必ず並べて読むこと",
        "observed": {},
    }
    for key, e in real.items():
        for d in DIRS:
            fg = e["directions"][d].get("full_gates")
            if not fg or "mh" not in fg:
                continue
            facts["mh_strata_coverage"]["observed"]["%s|%s" % (key, d)] = {
                v: {"used": x.get("strata_used"), "dropped": x.get("strata_dropped")}
                for v, x in fg["mh"].items() if x}

    # ── (c) 変数の一致 ──
    varagree = variable_agreement(real)
    others = read_other_angles()

    # ── 自己検査 ──
    checks = self_checks(cells)

    # ── cut 基準の感度 ──
    cutsens = cut_basis_sensitivity(cells, rows)

    # ── 検出力（陽性対照の注入）。両方向＋『後段のゲートは到達可能か』 ──
    pw = {"_why": "登録した線ちょうどの効果が本当にあってもこの手続きが掴めるか。"
                  "掴めないなら『合格ゼロ』は効果の不在の証拠ではない。"
                  "δ=0.25 では gate1 の先（業種・irr・増分）まで通るかも数える＝"
                  "**後段のゲートが木の形の群に到達可能か**の実測",
          "up": {}, "down": {}}
    reps = 30 if FAST else N_POWER
    for key in sorted(cells):
        for d in DIRS:
            print("  [power] %s %s" % (key, d), file=sys.stderr, flush=True)
            pw[d][key] = power_inject(cells[key], [0.10, 0.15, 0.20, 0.25], reps,
                                      seed + 77, direction=d, full_gate_at=0.25)
        if FAST:
            break

    # ── 偽陽性率 ──
    nperm = 20 if FAST else N_PERM
    fpr = fpr_y10(cells, rows, nperm, seed)

    # ── 診断の木（別手続き）を並べる ──
    diag_tree = reproduce_diag_tree(rows)
    diag_json = {}
    p = os.path.join(OUT, "hist10_diag.json")
    if os.path.exists(p):
        dj = json.load(open(p, encoding="utf-8"))
        diag_json = dj.get("false_positive", {}).get("angle_E_tree", {})

    # ── 到達可能性を実測したうえで、落ち方の**読み**を付ける ──
    # 「当てられない関門を『不合格』と書いてはいけない」（prereg が v1 の敗因として明記）
    reach_gate = {}
    for d in DIRS:
        for key, v in pw[d].items():
            e = v.get("delta_0.25") if isinstance(v, dict) else None
            if not e:
                continue
            reach_gate[(key, d)] = {
                "power_gate1_at_0.25": e.get("power_gate1"),
                "power_all_gates_at_0.25": e.get("power_all_gates"),
                "died_at": e.get("where_the_injected_truth_died"),
                "mh_diag": e.get("mh_diagnostics_on_injected_truth"),
                "⚠": "**二値にしない**。0/300 と 2/300 の差で『不合格』と『判定不能』を"
                     "分けるのは標本誤差で分けること。数字をそのまま読む",
            }
    for key, e in real.items():
        for d in DIRS:
            it = e["directions"][d]
            rg = reach_gate.get((key, d))
            it["later_gates_reachability"] = rg
            if not it["gate1_pass"]:
                it["verdict_reading_with_reachability"] = it["verdict"]
                continue
            p = (rg or {}).get("power_all_gates_at_0.25")
            if p is None:
                it["verdict_reading_with_reachability"] = it["verdict"] + "（到達可能性は未測定）"
            else:
                it["verdict_reading_with_reachability"] = (
                    "gate1 は通り、後段（業種）で落ちた。ただし**δ=0.25 の真の効果を"
                    "仕込んでも後段まで通るのは陽性対照で %.1f%% しかない**＝この群の形では"
                    "後段のゲートをほぼ当てられない。よってこの落ち方は"
                    "『不合格（効果が無い）』ではなく**判定不能（当てられない関門で落ちた）**"
                    "と読むのが正確" % (p * 100))

    n_pass = sum(1 for e in real.values() for d in DIRS
                 if e["directions"][d].get("verdict") == "合格")
    n_gate1 = sum(1 for e in real.values() for d in DIRS
                  if e["directions"][d]["gate1_pass"])
    n_unreach = sum(1 for e in real.values() for d in DIRS
                    if e["directions"][d]["gate1_pass"]
                    and ((e["directions"][d].get("later_gates_reachability") or {})
                         .get("power_all_gates_at_0.25") or 0) <= 0.01)

    # ── (a)(b)(c) に直接答える要約（数字はすべて上で計算したものを引く） ──
    ans_b = {}
    for key, e in real.items():
        for d in DIRS:
            it = e["directions"][d]
            o = it["oof"]
            ans_b["%s|%s" % (key, d)] = {
                "oof_lift": o["lift"], "oof_n_group_rows": o["n_group"],
                "oof_numerator_rows": o["numerator"],
                "oof_numerator_companies": o["numerator_companies"],
                "per_vintage_lift": {v: x["lift"] for v, x in o["per_vintage"].items()},
                "gate1": it["gate1_pass"],
                "verdict": it["verdict"],
                "gate_failed_at": it.get("gate_failed_at"),
                "in_sample_lift_for_contrast": it["in_sample_reference"]["lift"],
            }
    answers = {
        "(a)_three_targets": {
            "y10": "**判定可能**。結果は cells_y10",
            "y_persist": "**判定不能**（2013でしか定義できず sign_stability を満たせない。"
                         "さらに2013の特徴量は co_* で約94%が look-ahead）。"
                         "参考の外側fold性能は outside_prereg_aux_targets",
            "y_biz": "**判定不能**（分解在庫が 2013/2015/2018 のみ。2016/2017 を作れない）。"
                     "参考の外側fold性能は outside_prereg_aux_targets",
            "note": "この3つの判定可能性は診断 hist10_diag の target_judgeability が"
                    "**結果の前に**同じことを出しており、角度B・角度C も同じ壁で止まっている",
        },
        "(b)_outer_fold_performance": ans_b,
        "(c)_variable_agreement": {
            "tree_root_vars_pooled": [x["col"] for x in varagree["pooled_root_vars"]],
            "tree_all_split_vars_pooled": [x["col"] for x in varagree["pooled_split_vars"]],
            "angleA_top_up": [x["variable"] for x in others.get("A", {}).get("top_up", [])],
            "angleA_top_down": [x["variable"] for x in others.get("A", {}).get("top_down", [])],
            "angleD_pass_vars": [p["sel"] for p in others.get("D", {}).get("passes", [])],
            "angleC_pass": others.get("C", {}).get("n_pass"),
            "angleB_pass": others.get("B", {}).get("n_pass"),
        },
        "★the_in_sample_trap_measured_here": {
            "why": "木は自由度が最大。in-sample の最良を報告すると必ず立派な数字が出る",
            "in_sample_vs_oof": {("%s|%s" % (k, d)):
                                 {"in_sample": real[k]["directions"][d]
                                  ["in_sample_reference"]["lift"],
                                  "out_of_fold": real[k]["directions"][d]["oof"]["lift"]}
                                 for k in real for d in DIRS},
        },
    }

    doc = {
        "generated": "2026-08-12",
        "tool": "night/hist10_angleE.py",
        "★answers": answers,
        "prereg": "out/hist10_prereg.json",
        "angle": "E: 条件構造（決定木）を入れ子交差検証で",
        "inputs": {"panel": "out/hist_wd_panel.json",
                   "panel_generated": panel.get("generated"),
                   "targets": "out/hist10_targets.json",
                   "targets_generated": tg.get("generated"),
                   "prereg_version": prereg.get("version")},
        "★verdict": {
            "n_pass_all_gates": n_pass,
            "n_pass_gate1_only": n_gate1,
            "n_gate1_pass_whose_later_gates_are_effectively_unreachable": n_unreach,
            "unreachable_definition": "δ=0.25 の真の効果を仕込んだ陽性対照でも"
                                      "後段まで通る割合が 1% 以下",
            "line": "prereg の全条件（|lift|>=0.15 ∧ 分子>=20社 ∧ 3ビンテージ符号不変 ∧ "
                    "業種調整 ∧ irr層 ∧ 増分）を**外側foldの性能に対してのみ**当てる",
            "stopping_rule": "合格ゼロならゼロと書く。線を緩めて通さない",
            "judgeable_targets": ["y10"],
            "not_judgeable_targets": ["y_persist", "y_biz"],
            "⚠how_to_read_the_zero": (
                "合格ゼロを『効果の不在』と読んではいけない。理由を2つ実測してある——"
                "(1) **検出力**: 登録した線ちょうど δ=0.15 の効果を仕込んでも gate1 の"
                "検出力はごく低い。(2) **後段のゲートの到達可能性**: δ=0.25 の真の効果を"
                "仕込んでも業種ゲートが通らない配置がある＝そこで落ちた実データは"
                "『不合格』ではなく『判定不能』。詳細は must_report_before_verdict と"
                "各セルの later_gates_reachability"),
        },
        "pass_line_used": {"lift": LIFT, "min_numerator": MIN_NUM,
                           "incremental_max_caught": INCREMENTAL_MAX_CAUGHT,
                           "note": "事前登録の値。動かしていない"},
        "design_fixed_before_results": {
            "populations": POPS,
            "subsets": {k: v for k, v in SUBSETS.items()},
            "cut_quantiles": CUT_QS,
            "cut_basis": "外側/内側の train の分位（主）。コホート全体版も併走して差を出す",
            "tree": {"criterion": "情報利得（エントロピー）", "min_leaf": MIN_LEAF,
                     "depths": list(DEPTHS), "greedy": True},
            "group_modes": list(MODES),
            "direction": "up/down は**先に固定**（内側で選ばない）",
            "nested_cv": {"outer": N_OUTER, "inner": N_INNER,
                          "split_unit": "会社(ticker)。y10 は TRIO をプールするので"
                                        "同じ会社の3行が train/test に跨がらない",
                          "inner_selects": "depth × mode の4通りだけ"},
            "verdict_uses": "外側foldの性能のみ（in-sample は参考値として別掲）",
        },
        "must_report_before_verdict": {
            "reachability": reach,
            "power_positive_control": pw,
            "false_positive": fpr,
            "false_positive_from_diag_other_procedure": diag_json,
        },
        "★self_checks": checks,
        "★structural_facts_measured": facts,
        "cells_skipped_too_small": skipped,
        "cells_y10": real,
        "★(c)_variable_agreement_with_other_angles": {
            "tree_splits": varagree,
            "other_angles": others,
            "how_to_read": "木が『どの変数で切ったか』と、A(単変量)・D(加法)が挙げた変数が"
                           "重なるか。重なるなら関数形を変えても同じ信号を見ている＝"
                           "木が新しい構造を見つけたのではない",
        },
        "cut_basis_sensitivity": cutsens,
        "outside_prereg_aux_targets": aux,
        "diag_tree_same_inventory": diag_tree,
        "structural_limits": [
            "2016/2017/2018 は同じ956ティッカー（Jaccard=1.00）。プールしても独立な会社数は"
            "増えない＝実効 n は行数ではなく会社数",
            "complete-case なので all20 は母集団の約26%しか残らず規模の大きい側へ偏る",
            "y_persist は2013でしか定義できず、その2013の特徴量は co_*（約94%が look-ahead）",
            "y_biz は 2013/2015/2018 にしか無い。2018だけが f2_*（look-ahead 無し）の単一窓",
            "検出力の注入はラベルを行独立に引くので、同じ会社の3行の相関を無視した"
            "**実データより有利な**推定",
            "2018窓はAI相場。この道具はレジーム分割を出さない（角度D が同じ配置で出している）",
        ],
    }
    with open(DEST, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    # ── 画面 ──
    print("\n=== 角度E: 木 × 入れ子交差検証 ===")
    print("解析集合(y10):")
    for k, c in sorted(cells.items()):
        print("  %-22s 行=%4d 会社=%4d base=%.4f"
              % (k, c.n, len({r['ticker'] for r in c.rs}), c.label_mask().bit_count() / c.n))
    print("\n外側fold の性能（**これだけが合否**）:")
    for k in sorted(real):
        for d in DIRS:
            it = real[k]["directions"][d]
            o = it["oof"]
            pv = {v: o["per_vintage"].get(v, {}).get("lift") for v in ("2016", "2017", "2018")}
            print("  %-22s %-4s lift=%-8s 群=%-4s(社%-4s) 分子=%-4s(社%-3s) 年別=%s → %s"
                  % (k, d, o["lift"], o["n_group"], o["n_group_companies"],
                     o["numerator"], o["numerator_companies"], pv, it["verdict"]))
            if it["gate1_pass"]:
                print("      ↳ %s" % it.get("verdict_reading_with_reachability"))
            print("      参考(in-sample 深さ3) lift=%s 群=%s 分子=%s"
                  % (it["in_sample_reference"]["lift"], it["in_sample_reference"]["n_group"],
                     it["in_sample_reference"]["k"]))
    print("\n偽陽性率（置換 %d 回・会社単位）: gate1 の和集合=%s ／ 全ゲート=%s (MC SE %s)"
          % (fpr["n_perm"], fpr["union_gate1"], fpr["union_all_gates"], fpr["mc_se_union_gate1"]))
    if diag_json:
        print("  診断が測った別手続きの木: in-sample=%s / %s ／ 外側fold=%s / %s"
              % (diag_json["by_subset"]["cov90_14"]["false_positive_rate_in_sample_then_3vintage"],
                 diag_json["by_subset"]["all20"]["false_positive_rate_in_sample_then_3vintage"],
                 diag_json["by_subset"]["cov90_14"]["false_positive_rate_nested_cv"],
                 diag_json["by_subset"]["all20"]["false_positive_rate_nested_cv"]))
    print("\n検出力（陽性対照の注入）:")
    for d in DIRS:
        for k in sorted(pw[d]):
            v = pw[d][k]
            if "status" in v:
                print("  %-22s %-4s %s" % (k, d, v["status"]))
                continue
            e25 = v["delta_0.25"]
            print("  %-22s %-4s δ0.10=%-6s δ0.15=%-6s δ0.20=%-6s ｜ δ0.25 gate1=%-6s 全ゲート=%-6s %s"
                  % (k, d, v["delta_0.10"]["power_gate1"], v["delta_0.15"]["power_gate1"],
                     v["delta_0.20"]["power_gate1"], e25["power_gate1"],
                     e25.get("power_all_gates"), e25.get("where_the_injected_truth_died")))
    print("\n(c) 木が切った変数（プール）: %s"
          % [x["col"] for x in varagree["pooled_root_vars"][:6]])
    print("    A の上位: up=%s down=%s"
          % ([x["variable"] for x in others.get("A", {}).get("top_up", [])[:3]],
             [x["variable"] for x in others.get("A", {}).get("top_down", [])[:3]]))
    print("    D の合格: %s" % [p["sel"] for p in others.get("D", {}).get("passes", [])])
    print("\n事前登録の外（判定不能な目的）:")
    for k in sorted(aux):
        e = aux[k]
        for d in DIRS:
            o = e["directions"][d]["oof"]
            print("  %-40s %-4s lift=%-8s 群=%-4s 分子=%-4s" % (k, d, o["lift"], o["n_group"],
                                                                o["numerator"]))
    print("\n★ 合格（全ゲート）= %d ／ gate1 のみ通過 = %d" % (n_pass, n_gate1))
    print("→ %s" % DEST)
    return 0


if __name__ == "__main__":
    sys.exit(main())
