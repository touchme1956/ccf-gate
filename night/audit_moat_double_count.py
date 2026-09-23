#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/audit_moat_double_count.py — **堀の柱どうしが同じ事実を二度数えていないか数える**（2026-08-13新設）

■ なぜ要るか（todo: moat_dom_irr_double_count）
  v9.9.141 で「最上段(100)を85として採点する」を入れたが、**なぜ最上段が劣るのか**の
  有力な説明である**二重計上**は手つかずのまま残った。
  規約の文そのものに重なりがある——
    dom=100 の刻みは「独占≥90%、**または実質唯一供給**」
    irr=100 の刻みは「**唯一供給**」
  ＝**同じ一つの事実（唯一供給）が、重み .25 と .25 の二つの欄を同時に満たす**。
  さらに dur=100 は「**規制**/プロセス知/物理」で、規制フランチャイズ由来の唯一供給は
  irr=100 と dur=100 を同時に満たしうる（.25 + .12）。
  v9.9.45 で TAM柱を廃した理由「**同じ信号を二度数えない**」に正面から反する。

■ ⚠ この道具は判定を一つも持たない
  Ω・採点式・刻み・重み・関門・売却規律・配分には一切触れない。**列挙するだけ**。
  「同じ事実か」の最終判定は**原本を読む審査官の側**にある（機械のキーワード一致は
  irr=70 で偽陽性だらけだったという実測が既にある——同じ轍を踏まない）。
  出すのは (a)規約の定義そのものが重なる社 (b)引用が literally 共有されている社
  (c)機構語が両方の欄に現れる社 の**作業リスト**である。

■ 数え方（結果を見る前に固定した規則）
  1. **引用の共有**——evidence の中の引用（『』"" “” で囲まれた span）を正規化し、
     二つの欄で **40字以上**共通する span があれば「引用共有」。
     ⚠ 部分文字列ではなく**共通部分文字列の最長**で測る（片方が長い引用でもう一方がその一部、を拾う）
  2. **機構語の共有**——唯一供給を主張する語群 SOLE と、規制を主張する語群 REG を定義し、
     どちらの欄にも同じ語群が現れるか。⚠ これは**弱い証拠**（同じ語でも別の事実を指しうる）
  3. **規約の定義の重なり**——irr=100 は規約上 dom=100 の条件を**定義上満たす**ので、
     evidence が無くても構造的に重なる。**dom が空欄でも「重なりうる」として数える**
     （空欄は他4本の平均を与えるので、唯一供給の事実が dom 側にも効いている可能性が残る）
  4. **同じ文**（2026-09-23新設・todo moat_same_sentence・下の「■ 同じ文」の節）——
     1 の40字一致は、共有部分が20〜39字のときと『…』で割った引用を拾えない。
     引用を省略記号で断片に割り、**20字以上の共通区間が両方の引用の端で揃う**
     （片方がもう片方を含む／ずれて重なる＝同じ原文の抜き書きどうし）組を拾う。
     規則は out/moat_same_sentence.json の preregistered に**結果を見る前に**固定した。
     既存の出力（rows 等）には触れず、JSON に新しいキー "same_sentence" を足すだけ

■ 使い方
  python3 night/audit_moat_double_count.py            要約 + 作業リスト
  python3 night/audit_moat_double_count.py --all      全社の内訳
  python3 night/audit_moat_double_count.py --json     out/moat_double_count.json を書く
  python3 night/audit_moat_double_count.py --t ASML   1社の中身
  python3 night/audit_moat_double_count.py --same-sentence
        同じ文の検出を out/moat_same_sentence.json の "detection" へ書く
        （preregistered / amendments / verdicts / result には触れない。--t 付きでは書かない）
  python3 night/audit_moat_double_count.py --also-score FILE
        判定圏(Ω≥72)を out/score_all.json と FILE（score_all.js --out の出力）の和集合で決める
"""
import json, os, re, sys, glob, unicodedata

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "out")

# 正は index.html の ccfMoat（v9.9.36の5本重み）
# ★2026-09-23: 堀の重み・最上段の読み替え・堀指数は **audit_moat_gap.py から読む**（写しを持たない）。
#   ここに写しを持っていたため v9.9.36 の重み（.25/.25/.20/.12/.18）と v9.9.141 の読み替えのまま残り、
#   v9.9.185 の IRRTOP（記録85→採点100）も無く、moat_idx が門と 355/356社で最大±14ずれていた
#   （shadow_drop・weight の欄が誤っていた）。audit_moat_gap.W は index.html の ccfMoat から読む。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_moat_gap as _AMG  # noqa: E402
W = _AMG.W
# 正は index.html の ccfMoat（v9.9.141: 最上段は一つ下として採点）
TOPCAP = _AMG.TOPCAP
IRRTOP = _AMG.IRRTOP

# 「唯一供給・排他」を主張する語（規約 dom=100「または実質唯一供給」／irr=100「唯一供給」の引き金）
SOLE = [
    r"only manufacturer", r"sole (?:provider|supplier|source|manufacturer)",
    r"single source", r"exclusive franchise", r"exclusive right", r"exclusive territor",
    r"free from (?:direct )?competition", r"no competition", r"not (?:currently )?subject to competition",
    r"唯一供給", r"実質唯一", r"独占",
]
# 「規制」を主張する語（規約 dur=100「規制/プロセス知/物理」の引き金）
REG = [
    r"regulated", r"regulator", r"franchise", r"tariff", r"public utilit",
    r"commission", r"rate case", r"規制", r"フランチャイズ", r"料金",
]
GROUPS = {"SOLE": SOLE, "REG": REG}
# 「法で守られた排他的な事業権」——コンセッション・フランチャイズ・専属区域。
# ⚠ SOLE より狭い（技術的な唯一供給を含まない）。これが**どの柱に置かれているか**を数えるため
EXCL = re.compile(r"exclusive franchise|exclusive right|exclusive territor|exclusive concession|"
                  r"franchised territory|free from .{0,25}competition|no competition for|"
                  r"not .{0,20}subject to competition|独占コンセッション|排他的|独占的", re.I)

QUOTE = re.compile(r"『([^』]{20,})』|“([^”]{20,})”|\"([^\"]{20,})\"|「([^」]{20,})」")
MIN_SHARE = 40          # 共通部分文字列の最短（字）


def norm(s):
    """引用を突き合わせるための正規化——全角/半角・空白・強調記号を落とす。
    ⚠ irr85_mech_diff.py と同じ作法（** を空白でなく**空文字**へ落とす。
      空白へ落とすと『certification**.』が『certification .』になり本文と一致しなくなる）。"""
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("**", "").replace("*", "")
    s = re.sub(r"\s+", " ", s)
    # ⚠**日本語は語間に空白を置かない**＝CJKどうしの間の空白は必ずレイアウトの産物
    #   （2026-08-20の実害）。PDFの行折り返しが語の途中に入るので、片方の欄の引用だけが
    #   `…システム・サービスとし\nて、…` と割れていると、**最長共通部分文字列が
    #   そこで切れて 40字に届かず、二重計上が網に掛からない**。
    #   irr85_mech_diff.norm と同じ族の欠陥で、こちらは「見逃す」側へ片寄って壊れる。
    #   ⇒ 英語には当てない（空白が意味を持つ）。**両側がCJKのときだけ**畳む。
    s = re.sub(r"(?<=[\u3000-\u30ff\u3400-\u9fff\uf900-\ufaff\uff00-\uffef])"
               r" +"
               r"(?=[\u3000-\u30ff\u3400-\u9fff\uf900-\ufaff\uff00-\uffef])", "", s)
    return s.strip().lower()


def quotes(s):
    out = []
    for m in QUOTE.finditer(s or ""):
        q = next(g for g in m.groups() if g)
        q = norm(q)
        if len(q) >= MIN_SHARE:
            out.append(q)
    return out


def lcs_len(a, b):
    """最長共通部分文字列の長さ（DPは O(n*m) だが引用は短いので十分）"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def shared_quote(ea, eb):
    """二つの evidence の引用のあいだで MIN_SHARE 以上共通する最長 span を返す（無ければ None）"""
    qa, qb = quotes(ea), quotes(eb)
    best, bl = None, 0
    for x in qa:
        for y in qb:
            n = lcs_len(x, y)
            if n >= MIN_SHARE and n > bl:
                bl = n
                # 実際の共通部分を復元（最長一致の位置を探す）
                for i in range(len(x) - n + 1):
                    if x[i:i + n] in y:
                        best = x[i:i + n]
                        break
    return (best, bl) if best else (None, 0)


def hits(s, pats):
    t = norm(s)
    return sorted({p for p in pats if re.search(p, t)})


def num(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return None if x <= 0 else x


def moat_idx(d, drop=None):
    """index.html の ccfMoat と同値（audit_moat_gap.moat_idx に委譲）。drop で1本を空欄にできる。"""
    if drop:
        d = {k: (None if k in drop else v) for k, v in d.items()}
    return _AMG.moat_idx(d)


def pillar_corr(packs):
    """★引用の共有とは**独立**の証拠——柱どうしの順位相関。
    規約が別のものを測っているはずの柱が強く相関するのは、重なりの疑いになる。
    ⚠ 相関は「同じ事実を数えている」の証明ではない（良い会社は全部の柱が高い）。
      ただし **moatW が他と +0.13〜0.18 しか相関しない**のが内部対照で、
      高い相関が単なる『良い会社の後光』では説明できないことを示す。"""
    import itertools, math
    def rank(v):
        s2 = sorted(range(len(v)), key=lambda i: v[i]); r = [0] * len(v); i = 0
        while i < len(s2):
            j = i
            while j + 1 < len(s2) and v[s2[j + 1]] == v[s2[i]]:
                j += 1
            for k in range(i, j + 1):
                r[s2[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    def rho(a, b):
        ra, rb = rank(a), rank(b); n = len(a)
        ma, mb = sum(ra) / n, sum(rb) / n
        num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
        da = math.sqrt(sum((x - ma) ** 2 for x in ra))
        db = math.sqrt(sum((y - mb) ** 2 for y in rb))
        return num / (da * db) if da and db else 0.0
    vals = [{k: num(p.get(k)) for k in W} for p in packs]
    out = []
    for a, b in itertools.combinations(W, 2):
        xy = [(x[a], x[b]) for x in vals if x[a] is not None and x[b] is not None]
        if len(xy) < 30:
            continue
        out.append({"a": a, "b": b, "n": len(xy),
                    "rho": round(rho([x for x, _ in xy], [y for _, y in xy]), 3)})
    return sorted(out, key=lambda r: -r["rho"])


def load():
    rows = []
    for f in sorted(glob.glob(os.path.join(OUT, "*_gate_pack.json"))):
        try:
            p = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        rows.append(p)
    return rows


PAIRS = [("dom", "irr"), ("irr", "dur"), ("dom", "dur"),
         ("dom", "rep"), ("irr", "rep"), ("rep", "dur")]


def pillar_text(p, k):
    """柱 k の根拠文。空欄の理由にも根拠文が書かれることがある（domの再監査記録が典型）。
    analyse() と「同じ文」の節が同じものを読む（二重実装を作らない）"""
    m = p.get("_meta") or {}
    ev = m.get("evidence") or {}
    nu = m.get("nulls") or {}
    return str(ev.get(k) or "") + "\n" + str(nu.get(k) or "")


def analyse(p):
    t = (p.get("nm") or "?").split(" ")[0]

    def text(k):
        return pillar_text(p, k)

    val = {k: num(p.get(k)) for k in W}
    out = {"t": t, "nm": p.get("nm"), "val": val, "pairs": [], "flags": []}

    # (3) 規約の定義そのものの重なり——irr=100 は定義上 dom=100 の条件を満たす
    if val["irr"] == 100:
        out["flags"].append({
            "kind": "規約の定義の重なり",
            "why": "irr=100(唯一供給) は dom=100 の刻み『独占≥90%、**または実質唯一供給**』を"
                   "定義上そのまま満たす。dom が何であれ、同じ一つの事実が二つの欄の資格を作る",
            "weight": W["dom"] + W["irr"],
        })
    if val["dom"] == 100:
        out["flags"].append({
            "kind": "規約の定義の重なり(dom側)",
            "why": "dom=100 は『または実質唯一供給』でも取れるので、irr=100 と同じ事実で立ちうる",
            "weight": W["dom"] + W["irr"],
        })

    for a, b in PAIRS:
        ta, tb = text(a), text(b)
        if not ta.strip() or not tb.strip():
            continue
        q, ql = shared_quote(ta, tb)
        grp = {}
        for g, pats in GROUPS.items():
            ha, hb = hits(ta, pats), hits(tb, pats)
            both = sorted(set(ha) & set(hb))
            if both:
                grp[g] = both
        if q or grp:
            out["pairs"].append({
                "a": a, "b": b, "va": val[a], "vb": val[b],
                "weight": round(W[a] + W[b], 4),
                "shared_quote": q, "shared_quote_len": ql,
                "shared_groups": grp,
            })
    # 影の計測: 重なっている対の**軽いほう**を空欄へ落としたら堀はどうなるか（判定はしない）
    idx0 = moat_idx(p)
    out["moat"] = idx0
    worst = None
    for pr in out["pairs"]:
        if not pr["shared_quote"]:
            continue                     # 引用共有だけを影の計測の対象にする（機構語は弱い証拠）
        drop = pr["a"] if W[pr["a"]] <= W[pr["b"]] else pr["b"]
        i2 = moat_idx(p, drop={drop})
        if i2 is None:
            continue
        if worst is None or i2 < worst[1]:
            worst = (drop, i2)
    if worst:
        out["shadow_drop"] = {"drop": worst[0], "moat_after": round(worst[1], 2),
                              "delta": round(worst[1] - (idx0 or 0), 2)}
    return out


# ════════════════════════════════════════════════════════════════════════════════
# ■ 同じ文（same_sentence・2026-09-23新設・todo moat_same_sentence）
#   ⚠ この節は上の analyse() / rows / 引用共有(40字) と**独立**。既存の出力は1バイトも変えない
#     （JSON に新しいキー "same_sentence" を足すだけ）。判定は一つも持たない＝作業リスト。
#   【なぜ】2026-09-23 の段落の測定（todo double_count_same_paragraph）で、原本の同じ文を
#     2本の柱が引いている組は読んだ23組中18組が本物の二重計上だった。既存の40字一致は
#     (a) 共有部分が20〜39字 (b) 『…』で割った引用 を構造的に拾えない
#     （ASML: dur の『25 years of engineering』(23字) は rep の引用の一部——quotes() が
#       40字未満の引用を最初から捨てるので、どれだけ一致しても網に掛からない）。
#   【規則】out/moat_same_sentence.json の preregistered（結果を見る前に固定）と同一:
#     1) 引用 = QUOTE・text = pillar_text（analyse と同じ）
#     2) norm() の後に省略記号で断片へ割る。照合キー = irr85_mech_diff.norm(断片) の両端の記号を落としたもの
#        （逐語照合の器と同じキー＝二重実装を作らない）。20字未満の断片は使わない
#     3) 柱aの断片と柱bの断片の**極大な共通区間**で20字以上のものが、**両方の引用の端で揃う**
#        ——左の余り min(ix,iy)≤3 かつ 右の余り min(残りx,残りy)≤3。片方がもう片方を含む／
#        ずれて重なる＝同じ原文の抜き書きどうし。両方が同じ側で別の文字へ続くなら、
#        別の文が同じ言い回しを共有しているだけなので採らない（原本なしで文を同定する方法）
#     4) その区間が全パックの堀5柱の断片のうち3社以上に現れるなら定型句（見出し等）として採らない
#     5) 対象は PAIRS の6組・両方の柱に値がある組。既存の40字一致(literal40)が当たる組は
#        「新規」から外す（既に rows に載っている）
#   ⚠ 変数名は ss_ で始める——main() の `hit` を使い回して rows を [] にした事故（2026-08-19〜09-23）を
#     繰り返さないため、この節の集計は関数の中に閉じ、main() の名前空間に何も置かない。
# ════════════════════════════════════════════════════════════════════════════════
SS_REV = "ss1"
SS_PILLARS = ["dom", "irr", "rep", "dur", "moatW"]
SS_MIN_FRAG = 20        # 断片の最短（字・キー上）
SS_MIN_SHARED = 20      # 共通区間の最短（字・キー上）
SS_EDGE_SLACK = 3       # 端で揃うとみなす余り（字）
SS_BOILER_DF = 3        # この社数以上の断片に現れる区間は定型句
SS_BAND = 72.0          # 判定圏
SS_SEED = 20260923      # 判定圏の外の標本の種
SS_SAMPLE_N = 30        # 判定圏の外の標本の組数
SS_ELL = re.compile(r"\.{2,}|‥|⋯|・{2,}|\(略\)|（略）|\[\s*\]")
SS_EDGE = re.compile(r"^[\W_]+|[\W_]+$")
SS_FILE = os.path.join(OUT, "moat_same_sentence.json")
_ss_md = []


def ss_key(s):
    """断片の照合キー（irr85_mech_diff.norm ＝ 逐語照合の器と同じ正規化＋両端の記号を落とす）"""
    if not _ss_md:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        import irr85_mech_diff          # import 時に行うのは定数の定義と chdir(リポジトリ根) だけ
        _ss_md.append(irr85_mech_diff.norm)
    return SS_EDGE.sub("", _ss_md[0](s))


def ss_fragments(text):
    """[(元の引用, 断片キー)] ——引用を norm() の後に省略記号で割り、20字以上の断片だけ残す"""
    out = []
    for m in QUOTE.finditer(text or ""):
        q = next(g for g in m.groups() if g)
        for part in SS_ELL.split(norm(q)):
            k = ss_key(part)
            if len(k) >= SS_MIN_FRAG:
                out.append((q, k))
    return out


def ss_common(x, y, minlen=SS_MIN_SHARED):
    """x と y の**極大な**共通区間（左右どちらにも伸ばせない）で長さ minlen 以上のものを
    (xでの開始, yでの開始, 長さ) で全部返す。minlen 字の種を突き合わせてから左右へ伸ばす
    （全対のDPより桁違いに速く、極大区間は必ず先頭 minlen 字の種を持つので取りこぼさない）"""
    if len(x) < minlen or len(y) < minlen:
        return []
    seeds = {}
    for i in range(len(x) - minlen + 1):
        seeds.setdefault(x[i:i + minlen], []).append(i)
    seen, out = set(), []
    for j in range(len(y) - minlen + 1):
        for i in seeds.get(y[j:j + minlen], ()):
            a, b = i, j
            while a > 0 and b > 0 and x[a - 1] == y[b - 1]:
                a, b = a - 1, b - 1
            if (a, b) in seen:
                continue
            seen.add((a, b))
            n = 0
            while a + n < len(x) and b + n < len(y) and x[a + n] == y[b + n]:
                n += 1
            out.append((a, b, n))
    return out


def ss_anchored(x, y, ix, iy, n):
    """共通区間が両方の引用の端で揃うか（＝同じ原文の抜き書きどうしの重なり）"""
    return (min(ix, iy) <= SS_EDGE_SLACK
            and min(len(x) - ix - n, len(y) - iy - n) <= SS_EDGE_SLACK)


def ss_corpus(packs):
    """定型句の判定用: 銘柄 → その社の堀5柱の断片キーを \\x00 でつないだ文字列（全パック）"""
    c = {}
    for p in packs:
        t = (p.get("nm") or "?").split(" ")[0]
        c[t] = "\x00".join(k for pk in SS_PILLARS for _, k in ss_fragments(pillar_text(p, pk)))
    return c


def ss_pack(p, corpus):
    """1社の「同じ文」の組（PAIRS・両方に値）。組ごとに当たった区間を全部持つ"""
    t = (p.get("nm") or "?").split(" ")[0]
    val = {k: num(p.get(k)) for k in W}
    fr = {k: ss_fragments(pillar_text(p, k)) for k in W}
    out = []
    for a, b in PAIRS:
        if val[a] is None or val[b] is None:
            continue
        spans = {}
        for qa, x in fr[a]:
            for qb, y in fr[b]:
                for ix, iy, n in ss_common(x, y):
                    if not ss_anchored(x, y, ix, iy, n):
                        continue
                    s = x[ix:ix + n]
                    df = sum(1 for v in corpus.values() if s in v)
                    if df >= SS_BOILER_DF or s in spans:
                        continue
                    # 表示用: 二つの断片を重ねた「evidence から判る範囲の原文」
                    left = x[:ix] if ix >= iy else y[:iy]
                    right = x[ix + n:] if len(x) - ix >= len(y) - iy else y[iy + n:]
                    spans[s] = {"shared": s, "len": n, "df": df,
                                "frag_a": x, "frag_b": y, "host": left + s + right,
                                "quote_a": qa[:600], "quote_b": qb[:600]}
        if spans:
            lit, llen = shared_quote(pillar_text(p, a), pillar_text(p, b))
            out.append({"t": t, "a": a, "b": b, "va": val[a], "vb": val[b],
                        "weight": round(W[a] + W[b], 4),
                        "literal40": bool(lit), "literal_len": llen, "new": not lit,
                        "spans": sorted(spans.values(), key=lambda z: -z["len"])})
    return out


def ss_omega(sc, t):
    try:
        return float((sc.get(t) or {}).get("s"))
    except (TypeError, ValueError):
        return None


def same_sentence_section(packs, sc, sc2, only, show_all):
    """「同じ文」の節を画面へ出し、JSON 用の dict を返す（main() の名前空間を汚さない）"""
    corpus = ss_corpus(packs)                       # 定型句の判定は --t に関係なく全パックで
    ss_rows = []
    for p in packs:
        t = (p.get("nm") or "?").split(" ")[0]
        if only and t.upper() not in only:
            continue
        for r in ss_pack(p, corpus):
            o1 = ss_omega(sc, t)
            o2 = ss_omega(sc2, t) if sc2 else None
            r["omega"] = o1
            r["omega_also"] = o2
            r["band"] = bool((o1 is not None and o1 >= SS_BAND) or (o2 is not None and o2 >= SS_BAND))
            r["buy"] = bool((sc.get(t) or {}).get("buy"))
            ss_rows.append(r)
    ss_new = [r for r in ss_rows if r["new"]]
    ss_band = [r for r in ss_new if r["band"]]
    print(f"── ★同じ文を2本の柱が引いている組（same_sentence・{SS_REV}）──")
    print(f"  共通区間 {SS_MIN_SHARED}字以上・両方の引用の端で揃う（余り≤{SS_EDGE_SLACK}字）・"
          f"{SS_BOILER_DF}社以上に出る区間は定型句として除外・PAIRS の6組・両方に値")
    print(f"  同じ文の組 {len(ss_rows)}（{len({r['t'] for r in ss_rows})}社）"
          f" ＝ 既存の40字一致にも載る {sum(1 for r in ss_rows if r['literal40'])}"
          f" ＋ **新規 {len(ss_new)}**（{len({r['t'] for r in ss_new})}社）")
    print(f"  新規のうち 判定圏(Ω≥{SS_BAND:.0f}) {len(ss_band)}組（{len({r['t'] for r in ss_band})}社）"
          f" ／ 圏外 {len(ss_new) - len(ss_band)}組")
    shown = ss_new if show_all else ss_band
    for r in sorted(shown, key=lambda z: (-(z["omega"] or 0), z["t"], z["a"], z["b"])):
        mark = "🟢" if r["buy"] else ("◆" if r["band"] else "  ")
        s0 = r["spans"][0]
        print(f"  {mark}{r['t']:<7} Ω{(r['omega'] or 0):>5.1f}  {r['a']}={r['va'] and int(r['va'])}"
              f" × {r['b']}={r['vb'] and int(r['vb'])}  共通 {s0['len']}字"
              f"{'（ほか' + str(len(r['spans']) - 1) + '区間）' if len(r['spans']) > 1 else ''}")
        print(f"        『{s0['shared'][:150]}』")
    if not show_all and len(ss_new) > len(ss_band):
        print(f"  （圏外 {len(ss_new) - len(ss_band)}組は --all で出る）")
    print()
    return {"rev": SS_REV,
            "rule": {"min_fragment": SS_MIN_FRAG, "min_shared": SS_MIN_SHARED,
                     "edge_slack": SS_EDGE_SLACK, "boilerplate_df": SS_BOILER_DF,
                     "ellipsis": SS_ELL.pattern, "pairs": [f"{a}×{b}" for a, b in PAIRS],
                     "valued_only": True, "band": SS_BAND,
                     "spec": "out/moat_same_sentence.json の preregistered"},
            "n_pairs": len(ss_rows), "n_literal40": sum(1 for r in ss_rows if r["literal40"]),
            "n_new": len(ss_new), "n_new_band": len(ss_band),
            "pairs": ss_rows}


def ss_compact(ss):
    """moat_double_count.json に載せる軽い形（区間の本文・断片・引用の全文は moat_same_sentence.json の detection 側）"""
    keep = ("shared", "len", "df")
    out = dict(ss)
    out["pairs"] = [dict(r, spans=[{k: z[k] for k in keep} for z in r["spans"]]) for r in ss["pairs"]]
    out["detail"] = "区間の前後（host）・断片・引用の全文は out/moat_same_sentence.json の detection（--same-sentence で書く）"
    return out


def ss_write_detection(ss, argv_only, score_files=()):
    """out/moat_same_sentence.json の "detection" を書く。事前登録・読解の結果には触れない"""
    import hashlib, random, datetime, platform
    if argv_only:
        print("⚠ --t 付きでは moat_same_sentence.json を書かない（部分の検出で標本が変わるため）")
        return
    cur = {}
    if os.path.exists(SS_FILE):
        cur = json.load(open(SS_FILE, encoding="utf-8"))
        pre = cur.get("preregistered")
        if pre is not None:
            blob = json.dumps(pre, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if hashlib.sha256(blob.encode("utf-8")).hexdigest() != cur.get("preregistered_sha256"):
                print("✗✗ preregistered の sha256 が記録と合わない——事前登録が書き換えられている。書かずに止まる")
                sys.exit(1)
    ss_new = [r for r in ss["pairs"] if r["new"]]
    pool = sorted((r for r in ss_new if not r["band"]), key=lambda r: (r["t"], r["a"], r["b"]))
    samp = random.Random(SS_SEED).sample(pool, min(SS_SAMPLE_N, len(pool)))
    h = hashlib.sha256()
    for f in sorted(glob.glob(os.path.join(OUT, "*_gate_pack.json"))):
        h.update(open(f, "rb").read())
    cur["detection"] = {
        "rev": SS_REV, "run_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python": platform.python_version(), "packs_sha256": h.hexdigest(),
        "score_sources": [{"file": os.path.relpath(f, BASE) if f.startswith(BASE) else f,
                           "sha256": hashlib.sha256(open(f, "rb").read()).hexdigest()}
                          for f in score_files if f and os.path.exists(f)],
        "rule": ss["rule"], "n_pairs": ss["n_pairs"], "n_literal40": ss["n_literal40"],
        "n_new": ss["n_new"], "n_new_band": ss["n_new_band"],
        "band": [f"{r['t']} {r['a']}×{r['b']}" for r in ss_new if r["band"]],
        "sample_pool_n": len(pool), "sample_seed": SS_SEED,
        "sample": [f"{r['t']} {r['a']}×{r['b']}" for r in samp],
        "pairs": ss["pairs"]}
    with open(SS_FILE, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=1)
    print(f"→ out/moat_same_sentence.json（detection: 新規 {ss['n_new']}組・判定圏 {ss['n_new_band']}組・"
          f"標本 {len(samp)}/{len(pool)}組）")


def main():
    show_all = "--all" in sys.argv
    as_json = "--json" in sys.argv
    only = None
    if "--t" in sys.argv:
        only = {x.strip().upper() for x in sys.argv[sys.argv.index("--t") + 1].split(",")}

    sc = {}
    p = os.path.join(OUT, "score_all.json")
    if os.path.exists(p):
        d = json.load(open(p, encoding="utf-8"))
        sc = {r["t"]: r for r in (d if isinstance(d, list) else d.get("rows", []))}

    res = []
    for pack in load():
        r = analyse(pack)
        if only and r["t"].upper() not in only:
            continue
        r["omega"] = (sc.get(r["t"]) or {}).get("s")
        r["buy"] = (sc.get(r["t"]) or {}).get("buy")
        res.append(r)

    hit = [r for r in res if r["pairs"] or r["flags"]]
    qshare = [r for r in res if any(x["shared_quote"] for x in r["pairs"])]
    defn = [r for r in res if r["flags"]]

    print("■ 堀の柱どうしの二重計上の目録（night/audit_moat_double_count.py）")
    print(f"  パック {len(res)}社 ／ 何らかの重なり {len(hit)}社")
    print(f"  ★引用が literally 共有されている社 {len(qshare)}社（最も強い証拠）")
    print(f"  ★規約の定義そのものが重なる社 {len(defn)}社（irr=100 または dom=100）")
    print()

    if qshare:
        print("── ★引用の共有（同じ一文が二つの欄の根拠になっている）──")
        for r in sorted(qshare, key=lambda x: -(x.get("omega") or 0)):
            for pr in r["pairs"]:
                if not pr["shared_quote"]:
                    continue
                mark = "🟢" if r.get("buy") else "  "
                print(f"  {mark}{r['t']:<7} Ω{(r.get('omega') or 0):>5.1f}  "
                      f"{pr['a']}={pr['va'] and int(pr['va'])} × {pr['b']}={pr['vb'] and int(pr['vb'])}"
                      f"  重み計 {pr['weight']:.2f}  共通 {pr['shared_quote_len']}字")
                print(f"        『{pr['shared_quote'][:150]}』")
            if r.get("shadow_drop"):
                s = r["shadow_drop"]
                print(f"        影の計測: {s['drop']} を空欄にすると 堀 {r['moat']:.1f}→{s['moat_after']}"
                      f"（{s['delta']:+.1f}）")
        print()

    if defn:
        print("── ★規約の定義の重なり（irr=100 / dom=100 は同じ『唯一供給』で立ちうる）──")
        for r in sorted(defn, key=lambda x: -(x.get("omega") or 0)):
            mark = "🟢" if r.get("buy") else "  "
            v = r["val"]
            print(f"  {mark}{r['t']:<7} Ω{(r.get('omega') or 0):>5.1f}  "
                  f"irr={v['irr'] and int(v['irr'])} dom={v['dom'] and int(v['dom'])} "
                  f"dur={v['dur'] and int(v['dur'])} rep={v['rep'] and int(v['rep'])} "
                  f"moatW={v['moatW'] and int(v['moatW'])}  堀 {r['moat'] and round(r['moat'],1)}")
        print()

    # ★2026-08-13 追加: 二重計上より大きい問題が出たので数える——
    #   **同じ型の事実（法で守られた排他的な事業権）が、社によって別の柱に置かれている**。
    #   規約はこの事実がどの柱に属すかを言っていないので、読み手ごとに置き場所が変わる。
    place = {}
    for pack in load():
        t = (pack.get("nm") or "?").split(" ")[0]
        if only and t.upper() not in only:
            continue
        ev = ((pack.get("_meta") or {}).get("evidence") or {})
        # ⚠ 2026-09-23: ここは以前 `hit` という名前を使い回し、上の `hit`（重なりのある社の行）を上書きしていた
        #   ＝ out/moat_double_count.json の "rows" が 2026-08-19 以降ずっと [] だった（読む道具
        #   moat_dc_batches / shadow_moat_dedup / shadow_moat_merge は黙って0件を受け取っていた）。
        where = [k for k in W if EXCL.search(str(ev.get(k) or ""))]
        if where:
            place[t] = {"where": where, "vals": {k: num(pack.get(k)) for k in W},
                        "omega": (sc.get(t) or {}).get("s"), "buy": bool((sc.get(t) or {}).get("buy"))}
    if place:
        cnt = {}
        for v in place.values():
            cnt["+".join(sorted(v["where"]))] = cnt.get("+".join(sorted(v["where"])), 0) + 1
        print(f"── ★『法で守られた排他的な事業権』を根拠に持つ社 {len(place)}社 — その事実が置かれた柱 ──")
        print("  ⚠ 規約はこの事実がどの柱に属すかを言っていない。**置き場所が読み手ごとに変わる**")
        for k, v in sorted(cnt.items(), key=lambda x: -x[1]):
            print(f"     {k:<18} {v}社")
        both = [t for t, v in place.items() if len(v["where"]) >= 2]
        print(f"  ★**同じ社の中で二つ以上の柱に置かれている**（＝literal な二重計上）: "
              f"{len(both)}社  {' '.join(sorted(both)) or '—'}")
        print()

    corr = pillar_corr(load())
    print("── ★柱どうしの順位相関（引用の共有とは独立の証拠）──")
    print("  ⚠相関は二重計上の証明ではない。だが**moatW だけが他と弱くしか相関しない**のが内部対照で、")
    print("    高い相関が単なる『良い会社の後光』では説明できないことを示す")
    for c_ in corr:
        print(f"     {c_['a']:>6} × {c_['b']:<6} n={c_['n']:>3}  rho={c_['rho']:+.3f}  "
              + "#" * max(0, int(c_["rho"] * 40)))
    print()

    grponly = [r for r in res if r["pairs"] and not any(x["shared_quote"] for x in r["pairs"])]
    print(f"── 機構語だけが両方の欄に出る社 {len(grponly)}社 ──")
    print("  ⚠**弱い証拠**。同じ語でも別の事実を指しうるので、これだけで二重計上と断じない")
    if show_all:
        for r in sorted(grponly, key=lambda x: -(x.get("omega") or 0))[:60]:
            gs = sorted({g for pr in r["pairs"] for g in pr["shared_groups"]})
            ps = " ".join(f"{pr['a']}×{pr['b']}" for pr in r["pairs"])
            print(f"     {r['t']:<7} Ω{(r.get('omega') or 0):>5.1f}  {ps}  [{','.join(gs)}]")
    print()

    # ■ 同じ文（2026-09-23新設）——集計は same_sentence_section の中に閉じる（上の変数を一つも使い回さない）
    sc_also, ss_also_path = {}, None
    if "--also-score" in sys.argv:
        ss_also_path = sys.argv[sys.argv.index("--also-score") + 1]
        da = json.load(open(ss_also_path, encoding="utf-8"))
        sc_also = {r["t"]: r for r in (da if isinstance(da, list) else da.get("rows", []))}
    ss = same_sentence_section(load(), sc, sc_also, only, show_all)
    if "--same-sentence" in sys.argv:
        ss_write_detection(ss, only, (os.path.join(OUT, "score_all.json"), ss_also_path))

    if as_json:
        out = {"tool": "audit_moat_double_count", "rev": "r3",
               "n_packs": len(res), "n_quote_shared": len(qshare), "n_definition": len(defn),
               "n_group_only": len(grponly), "exclusive_placement": place, "pillar_corr": corr, "rows": hit,
               "same_sentence": ss_compact(ss)}
        with open(os.path.join(OUT, "moat_double_count.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print("\n→ out/moat_double_count.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
