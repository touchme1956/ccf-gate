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

★2026-08-17 の是正（ユーザー報告「新しく入った銘柄に色がない」）——**色が236銘柄ぶん消えていた**。
  実測: 2026-08-17 の ops.yml 実行で 色あり **318 → 104**（PNGの214件が全滅・SVGは無傷）。
  経路は二段で、**どちらも「作った答えを捨てる」型**だった:
  (1) `fetch_logos.py` が index.json を**ディスクから作り直す**ので c/cs/d/x が毎回消える
  (2) このスクリプトが recompute するが **Pillow が CI に無い**（pip install がどのworkflowにも無い）
      → `from PIL import Image` が ImportError → `except Exception: cols=[]` で
      **「測れなかった」を「色なし」として上書き**していた。SVGは正規表現なので生き残った
  是正は三つ:
  (a) **PILが無くても読む**——PNGを標準ライブラリ(zlib)だけで解く `_png_pixels`。
      out/logos の実測236枚は全部 8bit・非インタレース（colortype 0/2/3/4/6）でこれで足りる。
      読めない形式は None を返す＝**読めたふりをしない**
  (b) **測れなかったときは前回の測定を残す**（黙って色なしで上書きしない）。
      失敗は件数と銘柄名で大声で出し、終了コードも 1 にする（`audit_stale_bs` の作法）
  (c) **色が減る書き込みを拒否する**——`--allow-loss` が無い限り中止（空書き込みの検問）。
      ロゴ画像が本当に差し替わって色が消える場合だけ、人が旗を付けて通す
  ⚠ 併せて `fetch_logos.py` 側で **画像が変わっていない銘柄の色を持ち回す**ようにした。
    指紋は per-ticker の `b`(バイト数)——`b` が一致する限り「前回測ったその画像」だと言える。

使い方: python3 night/logo_colors.py [--force] [--allow-loss]
  環境変数 CCF_NO_PIL=1 … Pillow があっても純標準ライブラリの読み手を使う（両経路の突合せ用）
出力: out/logos/index.json の have[T] を {"ext":..., "b":バイト数, "c":"#rrggbb", "m":読み手} へ更新
"""
import colorsys, json, os, re, statistics, struct, sys, zlib, collections

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(BASE, "out", "logos")
IDX = os.path.join(DIR, "index.json")
NEUTRAL = re.compile(r"^#?(fff(fff)?|000(000)?|ffffffff|f{3,8}|0{3,8})$", re.I)


def _png_pixels(p, box):
    """**Pillow が無くても PNG を読む**（zlib だけ・標準ライブラリ）。RGBAのリストを返す。
    対応は 8bit・非インタレースの colortype 0/2/3/4/6（out/logos の236枚は全部これ）。
    それ以外・壊れている場合は **None**＝読めたふりをしない（ルール7）。
    縮小は最近傍の間引き（Pillowの thumbnail は補間するので画素の集まりは完全一致しない。
    だから **PILがある環境ではPILを使い続け**、この読み手は穴を埋める側だけに使う。
    どちらで測ったかは have[T].m に刻むので、後から取り違えない）。"""
    b = open(p, "rb").read()
    if b[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w = h = bd = ct = inter = None
    idat, plte, trns = [], None, None
    i = 8
    while i + 8 <= len(b):
        ln = int.from_bytes(b[i:i + 4], "big")
        typ, dat = b[i + 4:i + 8], b[i + 8:i + 8 + ln]
        if typ == b"IHDR" and len(dat) >= 13:
            w, h, bd, ct, _cm, _fl, inter = struct.unpack(">IIBBBBB", dat[:13])
        elif typ == b"PLTE":
            plte = dat
        elif typ == b"tRNS":
            trns = dat
        elif typ == b"IDAT":
            idat.append(dat)
        elif typ == b"IEND":
            break
        i += 12 + ln
    if not idat or bd != 8 or inter != 0 or ct not in (0, 2, 3, 4, 6) or not w or not h:
        return None
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    try:
        raw = zlib.decompress(b"".join(idat))
    except Exception:
        return None
    stride = w * ch
    if len(raw) < h * (stride + 1):
        return None
    step = max(1, -(-w // box[0]), -(-h // box[1]))     # 縮小率（切り上げ）
    rows, prev, pos = [], bytearray(stride), 0
    for y in range(h):
        f = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if f == 1:                                       # Sub
            for x in range(ch, stride):
                line[x] = (line[x] + line[x - ch]) & 255
        elif f == 2:                                     # Up
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif f == 3:                                     # Average
            for x in range(stride):
                a = line[x - ch] if x >= ch else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 255
        elif f == 4:                                     # Paeth
            for x in range(stride):
                a = line[x - ch] if x >= ch else 0
                c = prev[x - ch] if x >= ch else 0
                u = prev[x]
                pa, pb, pc = abs(u - c), abs(a - c), abs(a + u - 2 * c)
                line[x] = (line[x] + (a if (pa <= pb and pa <= pc) else (u if pb <= pc else c))) & 255
        elif f != 0:
            return None
        if y % step == 0:
            rows.append(line)
        prev = line
    out = []
    tr = trns or b""
    for line in rows:
        for x in range(0, w, step):
            o = x * ch
            if ct == 6:
                out.append((line[o], line[o + 1], line[o + 2], line[o + 3]))
            elif ct == 2:
                out.append((line[o], line[o + 1], line[o + 2], 255))
            elif ct == 4:
                g = line[o]
                out.append((g, g, g, line[o + 1]))
            elif ct == 0:
                g = line[o]
                out.append((g, g, g, 255))
            else:                                        # 3=パレット
                idx = line[o]
                if not plte or idx * 3 + 2 >= len(plte):
                    return None
                a = tr[idx] if idx < len(tr) else 255
                out.append((plte[idx * 3], plte[idx * 3 + 1], plte[idx * 3 + 2], a))
    return out


_PXCACHE = {}
PIXSRC = set()
LAST_SRC = None


def pixels(p, box):
    """画素の**単一の入口**（従来は3関数がそれぞれ `from PIL import Image` を書いていた）。
    PILがあればPIL・無ければ純標準ライブラリ。**どちらでも読めなければ例外**を上げる
    ——上位が「測れなかった」と「色が無い」を区別できるようにするため。"""
    global LAST_SRC
    k = (p, box)
    if k not in _PXCACHE:
        d, src = None, None
        if not os.environ.get("CCF_NO_PIL"):
            try:
                from PIL import Image
                im = Image.open(p).convert("RGBA")
                im.thumbnail(box)
                # Pillow 12 で getdata が非推奨（14で削除）。新旧どちらでも同じ (r,g,b,a) の列を返す
                d, src = list(getattr(im, "get_flattened_data", im.getdata)()), "pil"
            except ImportError:
                d = None
        if d is None:
            d = _png_pixels(p, box)
            if d is None:
                raise RuntimeError("PNGを読めない（PIL不在＋標準ライブラリでも解けない形式）")
            src = "py"
        _PXCACHE[k] = (d, src)
    d, src = _PXCACHE[k]
    LAST_SRC = src
    PIXSRC.add(src)
    return d


def hexc(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def lum_png(p):
    """不透明画素の平均輝度。**白い線画を白タイルに置くと消える**ので、
    明るいロゴには暗い地を敷く必要がある（実測: CTAS/RACE は不透明画素の100%が純白だった）。
    **ただし自前の不透明な地を持つ画像は対象外**——地色を変えても画像が全面を覆うので効かないし、
    「暗い地が要る」と誤って印を付けると次の人が原因を探すことになる。透過がある画像だけを見る。"""
    d = pixels(p, (64, 64))
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
    d = pixels(p, (64, 64))
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


# ── モノクロのロゴの「墨の濃さ」（v9.9.153・2026-08-17 ユーザー指示「入れて」）──────────
#   from_png / from_svg が色を返さない＝ロゴが**実質モノクロ**（黒地に白文字・黒のワードマーク等）。
#   従来はここで行を染めなかったので、実測49銘柄（KRMN・CTAS・RACE 等）の行が無色のままだった。
#   **黒・白・灰はそのロゴが現に持っている色**なので、明度から灰を作るのは「存在しない色を足す」
#   ことではない（v9.9.105 が禁じたのは**ハッシュ色**＝そのロゴと何の関係も無い色）。
#   ⚠ 帯で挟むのは**両テーマで見えるようにするため**——素の値だと黒ロゴは #000 に張り付いて
#     暗いテーマで消え、白ロゴは #fff に張り付いて明るいテーマで消える。
#     挟んでも**暗いロゴは暗い側・明るいロゴは明るい側**に残るので、ロゴの明暗の情報は失われない。
#   ★帯は実機で測って決めた（この台帳の作法: 見た目は文章で判断せず撮って比べる）。
#     行の中央の合成ピクセルと地の差（0-255・大きいほど見える）:
#       帯 [0.34,0.70] … 明るい灰 明テーマ **Δ16** / 暗テーマ Δ34 ／ 暗い灰 Δ35 / **Δ14**
#       帯 [0.40,0.60] … 明るい灰 **Δ21** / Δ28 ／ 暗い灰 Δ32 / **Δ18**   ← 採用（最悪ケースが最良）
#     参考: 有彩色の行（MSFT）は 明 Δ67 / 暗 Δ40。**灰は有彩色より控えめ**に出る（それでよい）。
#     ⚠ 灰は `.tgrad{filter:saturate(1.35)}` の恩恵を受けられない（彩度0を1.35倍しても0）ので、
#       同じ不透明度でも有彩色より弱く見える。**不透明度(.21/.18/.16)は変えない**——
#       あれは「もう少し薄く」を二度受けて較正した数字で、灰のために動かすと約束を破ることになる。
#       代わりに**灰の明度そのものを地から離す**のが、既存の較正を壊さない直し方。
GREY_LO, GREY_HI = 0.40, 0.60


def grey_hex(lum255):
    q = int(round(min(GREY_HI, max(GREY_LO, lum255 / 255.0)) * 255))
    return "#%02x%02x%02x" % (q, q, q)


def mono_png(p):
    """不透明画素の**明度の中央値**から灰を作る（平均だと少数の白地に引っぱられる）。"""
    px = [(r, g, b) for r, g, b, a in pixels(p, (96, 96)) if a >= 120]
    if not px:
        return None
    return grey_hex(statistics.median(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in px))


def mono_svg(p):
    """塗りに現れる**無彩色（白・黒・灰）の中央値**から灰を作る。
    塗りが一つも無い（currentColor や CSS クラスで塗る）SVGは **None**＝測っていないので染めない。"""
    lum = []
    for h in svg_fills(open(p, encoding="utf-8", errors="ignore").read()):
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        hh, ss, vv = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if ss >= 0.18:           # 有彩色は from_svg の領分（ここは無彩色だけを見る）
            continue
        lum.append(0.2126 * r + 0.7152 * g + 0.0722 * b)
    return grey_hex(statistics.median(lum)) if lum else None


def from_png(p, n=3):
    """代表色を**最大n色**返す（面積の多い色相ビン順）。
    v9.9.106: 1色だと単調なので、ロゴが実際に持っている色を複数拾って多段グラデーションにする。
    **色は必ずロゴ自身から採る**——見栄えのために存在しない色を足さない（ルール7の精神）。"""
    bins = collections.defaultdict(list)
    for r, g, b, a in pixels(p, (96, 96)):
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


def svg_fills(s):
    """SVGの塗りを **#hex / 色名 / rgb() のすべて**から拾って16進6桁で返す。
    ⚠ 2026-08-17: 旧実装は `#hex` しか見ておらず、**Finnhub 由来のSVGが使う `rgb(212,42,28)` を
    取りこぼしていた**——AZO は実際には赤いのに「色なし」として扱われていた（実測1銘柄）。"""
    out = []
    for m in re.finditer(r'(?:fill|stop-color|stroke)\s*[:=]\s*"?(#[0-9a-fA-F]{3,6}\b|white\b|black\b'
                         r'|rgb\(\s*\d+\s*[,\s]\s*\d+\s*[,\s]\s*\d+\s*\))', s, re.I):
        v = m.group(1).lower()
        if v.startswith("rgb("):
            r, g, b = (int(x) for x in re.findall(r"\d+", v)[:3])
            if max(r, g, b) > 255:
                continue
            out.append("%02x%02x%02x" % (r, g, b))
            continue
        h = {"white": "ffffff", "black": "000000"}.get(v, v.lstrip("#"))
        if len(h) == 3:
            h = "".join(x * 2 for x in h)
        if len(h) == 6:
            out.append(h)
    return out


def from_svg(p, n=3):
    s = open(p, encoding="utf-8", errors="ignore").read()
    c = collections.Counter()
    for h in svg_fills(s):
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
    allow_loss = "--allow-loss" in sys.argv
    d = json.load(open(IDX, encoding="utf-8"))
    have = d.get("have") or {}
    prev_ok = {t for t, v in have.items() if isinstance(v, dict) and (v.get("c") or v.get("k"))}
    out, n_new, n_keep, n_none, fails, kept_worse = {}, 0, 0, 0, [], []
    for t, cur in sorted(have.items()):
        cur = cur if isinstance(cur, dict) else {"ext": cur}
        ext = cur.get("ext")
        p = os.path.join(DIR, f"{t}.{ext}")
        size = os.path.getsize(p) if os.path.exists(p) else None
        # 指紋（b=バイト数）が一致＝**前回測ったその画像そのもの**なので測り直さない。
        #   ⚠ 据置のときは cur を丸ごと持ち回す——旧実装は {"ext","c"} だけを書き戻しており
        #     **cs（複数色）・d（暗い地が要る）・x（実質白紙）を毎回落としていた**（静かな劣化）。
        #   ★条件に c を要求しない——色が無い銘柄の d/x も測り直さないでよい（同じ絵からは同じ答え）。
        #     `b` を書くのは**このスクリプトだけ**で、fetch_logos は測定済みの値と一緒に持ち回すか
        #     画像が変わったら捨てる。だから「b があって一致＝この絵で測った記録がある」と言える。
        if size is not None and cur.get("b") == size and not force:
            out[t] = {**cur, "b": size}
            n_keep += 1
            continue
        err = False
        try:
            cols = from_png(p) if ext == "png" else from_svg(p)
        except Exception as e:                       # 読めなかった＝「色が無い」ではない
            cols, err = [], str(e) or e.__class__.__name__
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
        # ★ここが 2026-08-17 に236銘柄の色を消した当の経路。**下向きには書き換えない**——
        #   (a) 読めなかった(err) (b) 読めたが色が出ず、しかも**画像は前回と同一**(b が一致)
        #   のどちらも「前回の測定のほうが確か」なので残す。画像が本当に差し替わった場合だけ
        #   色の消滅を受け入れる（＝色が減るのは常に「絵が変わったから」に限られる）。
        #   PILと標準ライブラリの読み手は縮小の仕方が違い、実測3銘柄(EXEL/MPWR/TRN)で
        #   py側だけ色が出ない。この規則があるとCIがPIL無しで回っても色を落とさない。
        # v9.9.153: 有彩色が採れなかった＝モノクロのロゴ。**そのロゴ自身の明度**から灰を作る。
        #   ⚠ x=1（画像が実質白紙）のときは作らない——白紙の明度を測っても意味が無いし、
        #     門はその画像を描かずモノグラムを見せるので、行だけ染めても正体不明の帯になる。
        grey = None
        if not col and not err and not bad:
            try:
                grey = mono_png(p) if ext == "png" else mono_svg(p)
            except Exception:
                grey = None
        if (err or not (col or grey)) and (cur.get("c") or cur.get("k")) \
                and not allow_loss and (err or cur.get("b") == size):
            keep = {k: cur[k] for k in ("c", "cs", "k", "d", "x", "m") if k in cur}
            out[t] = {"ext": ext, **({"b": size} if size is not None else {}), **keep}
            (fails if err else kept_worse).append(f"{t}{'('+err+')' if err else ''}")
            continue
        if err:
            out[t] = {"ext": ext, **({"b": size} if size is not None else {})}
            fails.append(f"{t}({err}・色は無いまま)")
            continue
        src = LAST_SRC if ext == "png" and LAST_SRC == "py" else None
        # x=1: 画像が実質白紙＝門は img を描かずモノグラムを見せる（ファイルは残すので再取得はしない）
        out[t] = {"ext": ext, **({"b": size} if size is not None else {}),
                  **({"c": col} if col else {}),
                  **({"cs": cols} if len(cols) > 1 else {}),
                  **({"k": grey} if (grey and not col) else {}),
                  **({"d": 1} if dark else {}), **({"x": 1} if bad else {}),
                  **({"m": src} if (src and (col or grey)) else {})}
        n_new += 1
        if not col:
            n_none += 1
    ok = [t for t, v in out.items() if v.get("c")]
    grey_ok = [t for t, v in out.items() if v.get("k")]
    lost = sorted(prev_ok - set(ok) - set(grey_ok))
    if lost and not allow_loss:
        # ★空書き込みの検問（audit_stale_bs:243 と同じ言葉）——**色が減る書き込みは拒否**する。
        #   採取が壊れたときに表示が黙って劣化するのを、人の注意力ではなく機構で防ぐ。
        print(f"⚠ 中止: 色を失う銘柄が {len(lost)}件 ある"
              f"（前 {len(prev_ok)} → 後 {len(ok)+len(grey_ok)}〔有彩 {len(ok)}＋灰 {len(grey_ok)}〕）")
        print(f"   {' '.join(lost[:40])}")
        print("   ロゴ画像が本当に差し替わったのなら --allow-loss を付けて通す。"
              "そうでなければ読み手（Pillow / _png_pixels）が壊れている")
        if fails:
            print(f"   測れなかった {len(fails)}件: {' '.join(fails[:20])}")
        sys.exit(1)
    d["have"] = out
    d["note"] = ("門は同一オリジンで out/logos/{T}.{ext} を読む。無い銘柄はモノグラムで描く（欠測を別物で埋めない）。"
                 "c=ロゴの代表色（night/logo_colors.py がCIで算出）——門はこれで淡い発光を描く。"
                 "色が出せなかった銘柄はティッカーのハッシュ色へフォールバック。"
                 "b=画像のバイト数＝色の指紋（一致する限り測り直さない・fetch_logos が持ち回す）。"
                 "m=py は Pillow 不在で標準ライブラリの読み手が測った印。k=モノクロのロゴを**そのロゴ自身の明度**から灰にした色（v9.9.153・有彩色が採れないときだけ）")
    json.dump(d, open(IDX, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"画素の読み手: {'+'.join(sorted(PIXSRC)) or '（PNGを読まなかった）'}"
          f"{'  ⚠ Pillow が無い（標準ライブラリで代替）' if PIXSRC == {'py'} else ''}")
    print(f"代表色: 新規算出 {n_new}（うち決められず {n_none}）／据置 {n_keep}")
    if fails:
        print(f"⚠ **測れなかった {len(fails)}銘柄**（前回の測定は残してある）: {' '.join(fails[:20])}")
    if kept_worse:
        print(f"今回の読み手では色が出ず**前回の測定を残した {len(kept_worse)}銘柄**"
              f"（画像は前回と同一）: {' '.join(kept_worse[:20])}")
    print(f"色あり **{len(ok)}/{len(out)}銘柄** ＋ モノクロのロゴを明度から灰に **{len(grey_ok)}銘柄**"
          f"（＝行が染まるのは {len(ok)+len(grey_ok)}銘柄）")
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
    if fails:
        sys.exit(1)     # 測れなかったことを終了コードにも出す（静かに成功したふりをしない）


if __name__ == "__main__":
    main()
