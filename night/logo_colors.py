#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/logo_colors.py — 各銘柄ロゴの**代表色**を出して out/logos/index.json へ入れる
（2026-08-07新設・ユーザー要望「そのアイコンにあった色合いに少しぼかすとおしゃれなのでは？」）

なぜCIで出すか: 門はブラウザで369行を描く。1行ごとに canvas で画素を読むと重いうえ、
  同じ色を毎回計算し直すことになる。**価格(dashboard.json)と同じ作法**——CIで一度measureして
  JSONで配り、ブラウザは読むだけにする。

代表色の決め方（両形式とも「地の色」を捨てて「主張している色」を採る）:
  PNG … RGBAで読み、透明・ほぼ白・ほぼ黒・無彩色(彩度<0.14)の画素を捨てたうえで、
        HSVのHを24分割してヒストグラムの最頻ビンを採り、そのビンの中央値HSVを色にする。
        （平均だと補色が混ざって濁る＝ロゴの主張色にならない）
  SVG … fill/stop-color の16進を数え、同じく無彩色を捨てて最頻色。面積は見ないので近似だが、
        SVGロゴはブランド色をベタ塗りする作りが大半なので実用上これで足りる。
  **どちらでも決められなければ色を入れない**（ルール7: 無理に埋めない）。
  門の側は色が無ければティッカーのハッシュ色にフォールバックするので、表示は壊れない。

使い方: python3 night/logo_colors.py [--force]
出力: out/logos/index.json の have[T] を {"ext":..., "c":"#rrggbb"} 形式へ更新
"""
import colorsys, json, os, re, statistics, sys, collections

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(BASE, "out", "logos")
IDX = os.path.join(DIR, "index.json")
NEUTRAL = re.compile(r"^#?(fff(fff)?|000(000)?|ffffffff|f{3,8}|0{3,8})$", re.I)


def hexc(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def lum_png(p):
    """不透明画素の平均輝度。**白い線画を白タイルに置くと消える**ので、
    明るいロゴには暗い地を敷く必要がある（実測: CTAS/RACE は不透明画素の100%が純白だった）。
    **ただし自前の不透明な地を持つ画像は対象外**——地色を変えても画像が全面を覆うので効かないし、
    「暗い地が要る」と誤って印を付けると次の人が原因を探すことになる。透過がある画像だけを見る。"""
    from PIL import Image
    im = Image.open(p).convert("RGBA")
    im.thumbnail((64, 64))
    d = list(im.getdata())
    if not d:
        return None
    if sum(1 for *_, a in d if a < 120) / len(d) < 0.06:   # 透過がほぼ無い＝自前の地を持つ
        return None
    px = [(r, g, b) for r, g, b, a in d if a >= 120]
    if not px:
        return None
    return sum(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in px) / len(px)


def blank_png(p):
    """**不透明なのに実質ほぼ白紙**の画像を見つける。地色を変えても画像が全面を覆うので救えない
    ——こういうものは「ロゴが出ている」ふりをするより、モノグラムに戻すほうが正しい（ルール7）。
    線が細いワードマークを誤って捨てないよう、ばらつき(標準偏差)の線は 25 と厳しめに置く
    （実測: 目で見て白紙に見える IPAR 11.6 ・4393 14.0・IPGP 21.4・6920 23.4 だけが該当し、
    線は細いが読める LRCX 36.6・ETN 36.5・CRAI 35.6 は残る）。"""
    from PIL import Image
    im = Image.open(p).convert("RGBA")
    im.thumbnail((64, 64))
    d = list(im.getdata())
    if not d or sum(1 for *_, a in d if a < 120) / len(d) >= 0.06:
        return False
    lum = [0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b, a in d]
    return statistics.mean(lum) > 235 and statistics.pstdev(lum) < 25


def lum_svg(p):
    """SVGは全面塗りの背景rectを持つものが多い（例: parqetのASMLは <rect .. fill="white"/>）。
    自前の地を持つなら地色の切替は不要なので None を返す。持たない場合だけ白系の塗りの多さで判定する。"""
    s = open(p, encoding="utf-8", errors="ignore").read()
    if re.search(r'<rect[^>]*\bwidth="(100%|\d{2,})"[^>]*fill="(?!none)', s):
        return None
    w = len(re.findall(r'fill\s*[:=]\s*"?(#f{3}\b|#f{6}\b|white)', s, re.I))
    d = len(re.findall(r'fill\s*[:=]\s*"?(#0{3}\b|#0{6}\b|black|#[0-9a-f]{0,2}[0-4][0-9a-f])', s, re.I))
    return 235.0 if (w and w >= d) else None


def from_png(p, n=3):
    """代表色を**最大n色**返す（面積の多い色相ビン順）。
    v9.9.106: 1色だと単調なので、ロゴが実際に持っている色を複数拾って多段グラデーションにする。
    **色は必ずロゴ自身から採る**——見栄えのために存在しない色を足さない（ルール7の精神）。"""
    from PIL import Image
    im = Image.open(p).convert("RGBA")
    im.thumbnail((96, 96))
    bins = collections.defaultdict(list)
    for r, g, b, a in list(im.getdata()):
        if a < 120:
            continue
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if s < 0.14 or v < 0.10 or v > 0.98:   # 無彩色・ほぼ黒・ほぼ白は「地」なので捨てる
            continue
        bins[int(h * 24) % 24].append((h, s, v))
    if not bins:
        return []
    out, top = [], sorted(bins.values(), key=len, reverse=True)
    if len(top[0]) < 4:        # 色画素がこれ未満＝ロゴが実質モノクロ。無理に色を作らない（ルール7）
        return []
    for px in top[:n]:
        if len(px) < max(3, len(top[0]) * 0.08):   # 面積が主色の8%未満は「点」なので採らない
            break
        out.append(hexc(statistics.median(x[0] for x in px),
                        min(0.95, max(0.50, statistics.median(x[1] for x in px))),
                        min(0.95, max(0.55, statistics.median(x[2] for x in px)))))
    return out


def from_svg(p, n=3):
    s = open(p, encoding="utf-8", errors="ignore").read()
    c = collections.Counter()
    for m in re.finditer(r'(?:fill|stop-color|stroke)\s*[:=]\s*"?#([0-9a-fA-F]{3,6})', s):
        h = m.group(1)
        if len(h) == 3:
            h = "".join(x * 2 for x in h)
        if len(h) != 6 or NEUTRAL.match(h):
            continue
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        hh, ss, vv = colorsys.rgb_to_hsv(r, g, b)
        if ss < 0.18 or vv < 0.12 or vv > 0.97:
            continue
        c["#" + h.lower()] += 1
    return [x for x, _ in c.most_common(n)]


def main():
    force = "--force" in sys.argv
    d = json.load(open(IDX, encoding="utf-8"))
    have = d.get("have") or {}
    out, n_new, n_keep, n_none = {}, 0, 0, 0
    for t, cur in sorted(have.items()):
        ext = cur["ext"] if isinstance(cur, dict) else cur
        col = cur.get("c") if isinstance(cur, dict) else None
        if col and not force:
            out[t] = {"ext": ext, "c": col}; n_keep += 1; continue
        p = os.path.join(DIR, f"{t}.{ext}")
        try:
            cols = from_png(p) if ext == "png" else from_svg(p)
        except Exception:
            cols = []
        cols = cols or []
        col = cols[0] if cols else None
        try:
            lu = lum_png(p) if ext == "png" else lum_svg(p)
        except Exception:
            lu = None
        # d=1: ロゴ自体が明るい＝白タイルでは消える → 門は暗い地を敷く
        dark = 1 if (lu is not None and lu > 200) else 0
        try:
            bad = blank_png(p) if ext == "png" else False
        except Exception:
            bad = False
        # x=1: 画像が実質白紙＝門は img を描かずモノグラムを見せる（ファイルは残すので再取得はしない）
        out[t] = {"ext": ext, **({"c": col} if col else {}),
                  **({"cs": cols} if len(cols) > 1 else {}),
                  **({"d": 1} if dark else {}), **({"x": 1} if bad else {})}
        n_new += 1
        if not col:
            n_none += 1
    d["have"] = out
    d["note"] = ("門は同一オリジンで out/logos/{T}.{ext} を読む。無い銘柄はモノグラムで描く（欠測を別物で埋めない）。"
                 "c=ロゴの代表色（night/logo_colors.py がCIで算出）——門はこれで淡い発光を描く。"
                 "色が出せなかった銘柄はティッカーのハッシュ色へフォールバック")
    json.dump(d, open(IDX, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"代表色: 新規算出 {n_new}（うち決められず {n_none}）／据置 {n_keep}")
    ok = [(t, v["c"]) for t, v in out.items() if v.get("c")]
    print(f"色あり **{len(ok)}/{len(out)}銘柄**")
    nd = sum(1 for v in out.values() if v.get("d"))
    nx = [t for t, v in out.items() if v.get("x")]
    n2 = sum(1 for v in out.values() if len(v.get("cs") or []) >= 2)
    n3 = sum(1 for v in out.values() if len(v.get("cs") or []) >= 3)
    print(f"複数色が取れた: 2色以上 **{n2}銘柄** / 3色 **{n3}銘柄**")
    print(f"明るいロゴ（暗い地を敷く） **{nd}銘柄** ／ 実質白紙で不採用（モノグラムへ） **{len(nx)}銘柄** {' '.join(nx)}")
    for t in ("ASML", "MSFT", "NVDA", "CTAS", "RACE", "6920", "MA", "ADBE", "KLAC", "CDNS"):
        if t in out:
            print(f"   {t:6} {' '.join(out[t].get('cs') or ([out[t]['c']] if out[t].get('c') else ['（色なし）'])):32}"
                  f" {'暗い地' if out[t].get('d') else '淡い地'}")


if __name__ == "__main__":
    main()
