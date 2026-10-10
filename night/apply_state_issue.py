#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/apply_state_issue.py — **GitHub の Issue に貼られた「保有の依頼」を検査して state.json に入れる**
（v9.9.210・2026-10-10 ユーザー明示指示「案1でやってマージして」）

■ 何のための道具か
  門は GitHub Pages の静的ページで、**ブラウザから repo へは鍵なしでは書けない**（state.js の頭注）。
  旧「鍵を端末に置く」道は v9.9.209 で撤去した（ユーザー「鍵がどうとかはいらない」）。代わりの道がこれ:
    ① 門が、端末の決定と repo の state.json の差から **「新規 Issue」のリンク**を作る（本文に依頼が入っている）
    ② 人が GitHub でそのリンクを開き、**「Submit new issue」を1回押す**（GitHub にログインしていれば鍵は要らない）
    ③ `.github/workflows/state_from_issue.yml` がこの道具を回し、検査を通れば state.json を更新して main へ push、
       📈成績（returns.yml）を作り直し、結果を Issue にコメントして閉じる
  人の手は「リンクを開いて1回押す」だけ。⚠ **これは main への自動 push の新設**（2026-09-23 に Routine の自動 push が
  アカウント停止の原因になった経緯により、ユーザーの明示指示が要った。2026-10-10「案1でやってマージして」）。

■ 守っていること（ここが本体——順番も意味がある）
  1. **オーナー本人の Issue だけ**（ワークフロー側の `if` と、ここでもう一度）。公開リポジトリなので誰でも Issue は立てられる。
  2. 依頼は **本文の ```ccf-state の中だけ**を読む（deflate+base64url）。本文はシェルへ渡さない（このファイルが event JSON から読む）。
  3. 形と**完全性**（sha256）・**キーの許可リスト**（state.js の EXACT＝night/state_keys.py）・値の大きさ。
  4. ★**自由記述の検問**（rule 9「個人の名前を repo に書かない」を自動の道で破らないための本体）:
     自由記述の欄（lots の src・position の note・売却の memo・who）は、**repo の state.json に既にある文（＝既に公開）**か、
     **門が機械で作る定型文**だけ通す。それ以外は止め、**Issue の本文を消す**。
     理由: 端末の localStorage には、名前を消す前の古い文が残っていることがある。手で反映する道（📤 書き出す→Claude）では
     Claude が目で見て直したが、自動の道には目が無い。**未知の文は公開しない**が唯一の安全側。
     ※ 名前の一覧は持たない（持てば対応表になる）。**「既に公開されているか」だけで決める**。
     ※ 同じ検問を門（state.js）が**リンクを作る前**にも掛ける。Issue は作られた時点で公開されるので、
        こちら（作られた後）は二重の備えで、本線は門のほう。
  5. **CAS（比較して置換）**: 依頼には、各キーについて「この repo の値（のハッシュ）の上に作った」が入っている。
     今の repo の値がそれと違えば（誰かが先に更新した）**何もしない**。端末が古いまま repo の新しい決定を潰さない。
  6. **変化が無ければ何もしない**（機械の書き戻し npx/npxAuto/fx だけの差も変化に数えない＝state.js の sameDecision と同じ）。
  7. 書く前に **validate_state.py**（CI が state.json に掛ける検査）を候補に掛ける。CI が落とす state.json は作らない。

■ 出力
  - `$GITHUB_OUTPUT` に status（applied|noop|rejected|skip）・code・redact・keys・saved_at
  - `$CCF_MSG_PATH`（既定 /tmp/ccf_state_msg.md）に Issue へ書くコメント（日本語）。
    ⚠ **コメントに依頼の中身（自由記述）は書かない**——止めた場所は欄の名前だけ。

使い方: ワークフローが `python3 night/apply_state_issue.py`（環境変数 GITHUB_EVENT_PATH / GITHUB_REPOSITORY_OWNER / GITHUB_OUTPUT）。
        手元の検査は night/check_state_issue.py と night/check_state_issue.js。
"""
import base64
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zlib
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import state_keys  # noqa: E402

TITLE_PREFIX = "[ccf-state]"
MAX_RAW = 1_500_000            # 伸ばした依頼の上限（バイト）
MAX_VALUE = 400_000            # 1キーの値の上限（文字）
FMT = "ccf-state-issue"

LABEL = {"pf:portfolio": "株数", "pf:net": "ETFの買付記録", "pf:sold": "売却記録", "pf:weights": "目標ウェイト",
         "pf:monthly_total": "今月の入金総額", "pf:monthly": "今月の個別枠", "pf:monthly_net": "今月のETF枠",
         "g7ignite:map": "点灯日"}

# ── 自由記述の検問（night/…の JS 版は state.js の ccfState.unseenText。**同じ表を共有ベクトルで突き合わせる**: night/state_issue_vectors.json）
STRICT_FIELDS = {"note", "memo", "src", "who"}          # 自由に書ける欄＝既に公開の文か定型文だけ
FREE_FIELDS = {"nm"}                                     # 会社名・ファンド名（公開情報）
ENUM_OK = {"個別", "ETF", "投資信託", "暗号資産", "成長", "つみたて", "特定", "iDeCo", "こどもNISA", "取引所", "子ども"}
_ACCT = r"(?:成長|つみたて|特定|iDeCo|こどもNISA|取引所)"
_WHO = r"(?:[A-Z]|子ども)"
# ※ re.ASCII（\d を 0-9 だけにする）と fullmatch（行末の改行を許さない）で、JS 版（state.js）より甘くならないようにする
SRC_TPL = re.compile(r"門の🏦保有で記録(?:（約定日 \d{4}-\d{2}-\d{2}）)?"
                     r"(?:（" + _WHO + r"(?:・" + _ACCT + r")?）|（" + _ACCT + r"）)?", re.ASCII)
SELL_NOTE_TPL = re.compile(r"\d{4}-\d{2}-\d{2} [0-9][0-9.,]*(?:株|口| [A-Z]{2,6})売却（門で記録）", re.ASCII)
MEMO_AUTO_TPL = re.compile(r"受取額は見積もり（(?:口数×基準価額|株数×単価×ドル円)）", re.ASCII)
WHO_TPL = re.compile(_WHO, re.ASCII)
SEG_SEP = "　"                                       # 全角空白（note / memo は定型文をこれでつなぐ）
MACHINE_FLD = {"fx", "npx", "npxAuto"}                   # 盤から書き戻される欄（state.js の MACHINE_FLD と同じ）


class ReqError(Exception):
    """依頼を受け付けない理由。code は 'format'|'sha'|'keys'|'size'|'owner'…"""

    def __init__(self, code, msg, redact=False):
        super().__init__(msg)
        self.code, self.msg, self.redact = code, msg, redact


def sha256_hex(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ── 依頼の取り出し ─────────────────────────────────────────────────────────
def extract_block(body):
    m = re.search(r"```ccf-state[ \t]*\r?\n(.*?)\r?\n?```", body or "", re.S)
    if not m:
        raise ReqError("format", "本文に ```ccf-state の囲みが見つからない", True)
    return re.sub(r"\s+", "", m.group(1))


def decode_block(txt):
    enc, dot, b64 = txt.partition(".")
    if not dot or enc not in ("z", "d", "p"):
        raise ReqError("format", "依頼の符号の形が読めない", True)
    try:
        raw = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
    except Exception:
        raise ReqError("format", "依頼の base64 が読めない（途中で切れた？）", True)
    try:
        if enc == "z":
            d = zlib.decompressobj(-15)
            raw = d.decompress(raw, MAX_RAW)
            if d.unconsumed_tail:
                raise ReqError("size", "依頼が大きすぎる", True)
        elif enc == "d":
            d = zlib.decompressobj()
            raw = d.decompress(raw, MAX_RAW)
            if d.unconsumed_tail:
                raise ReqError("size", "依頼が大きすぎる", True)
        elif len(raw) > MAX_RAW:
            raise ReqError("size", "依頼が大きすぎる", True)
    except ReqError:
        raise
    except Exception:
        raise ReqError("format", "依頼を伸ばせない（途中で切れた？）", True)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        raise ReqError("format", "依頼が JSON として読めない", True)


def parse_payload(p, allowed):
    """(data, bases) を返す。形・完全性・キーの許可リスト・大きさを見る。"""
    if not isinstance(p, dict) or p.get("fmt") != FMT or p.get("ver") != 1:
        raise ReqError("format", "依頼の fmt/ver が合わない", True)
    dj = p.get("dataJson")
    if not isinstance(dj, str):
        raise ReqError("format", "依頼に dataJson が無い", True)
    if sha256_hex(dj) != p.get("sha"):
        raise ReqError("sha", "依頼の中身が検算と合わない（途中で変わった？）", True)
    try:
        data = json.loads(dj)
    except Exception:
        raise ReqError("format", "dataJson が JSON として読めない", True)
    if not isinstance(data, dict) or not data:
        raise ReqError("format", "送る決定が空", False)
    for k, v in data.items():
        if k not in allowed:
            raise ReqError("keys", "許可されていないキーが含まれていました（state.js の集合に無いもの。キー名は公開しないのでここには書きません）", True)
        if not isinstance(v, str) or len(v) > MAX_VALUE:
            raise ReqError("size", f"{k!r} の値が文字列でない／大きすぎる", True)
    bases = p.get("bases")
    if not isinstance(bases, dict):
        raise ReqError("format", "依頼に前提（bases）が無い", True)
    for k in data:
        b = bases.get(k)
        if not isinstance(b, list) or not b or len(b) > 8 or not all(isinstance(x, str) and len(x) <= 64 for x in b):
            raise ReqError("format", f"{k!r} の前提（bases）が読めない", True)
    return data, bases


# ── 決定の比較（state.js の sameDecision と同じ）─────────────────────────────
def strip_machine(v):
    o = json.loads(v)
    if isinstance(o, dict):
        for f in MACHINE_FLD:
            o.pop(f, None)
        if isinstance(o.get("positions"), list):
            o["positions"] = [({kk: vv for kk, vv in p.items() if kk not in MACHINE_FLD} if isinstance(p, dict) else p)
                              for p in o["positions"]]
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


def same_decision(k, mine, theirs):
    if mine == theirs:
        return True
    if mine is None or theirs is None:
        return False
    if k in state_keys.PLAIN_NUMBER_KEYS:
        return False
    try:
        return strip_machine(mine) == strip_machine(theirs)
    except Exception:
        return False


# ── 自由記述の検問 ─────────────────────────────────────────────────────────
def _walk(o, path, field, out):
    """(path, field, value) を深さ優先・挿入順で集める。文字列の葉だけ。"""
    if isinstance(o, str):
        out.append((path, field, o))
    elif isinstance(o, dict):
        for k, v in o.items():
            _walk(v, path + "." + k, k, out)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            _walk(v, path + f"[{i}]", field, out)


def _leaves(key, value):
    try:
        o = json.loads(value)
    except Exception:
        o = value
    out = []
    _walk(o, "", "", out)
    return [(key + ":" + p.lstrip("."), f, v) for p, f, v in out]


def public_sets(repo_data):
    """repo の state.json に既にある文（＝既に公開）。(全文の集合, note/memo の区切りごとの集合)"""
    full, segs = set(), set()
    for k, v in (repo_data or {}).items():
        if not isinstance(v, str):
            continue
        for _p, f, s in _leaves(k, v):
            full.add(s)
            if f in ("note", "memo"):
                for seg in s.split(SEG_SEP):
                    if seg.strip():
                        segs.add(seg.strip())
    return full, segs


def _is_ascii(s):
    try:
        s.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def safe_path(p):
    """コメントに書く『場所』。道筋には依頼の中の辞書のキー名が入るので、英数字と記号 `_:.[]-` 以外は `?` にする
    （名前を公開のコメントに載せない。欄の名前・添字・キーの英字だけが読める）。"""
    return re.sub(r"[^A-Za-z0-9_:.\[\]-]", "?", p)


def find_unseen_text(data, repo_data):
    """送ろうとしている値のうち、**repo に無い自由記述**の場所（欄の道筋）を返す。中身は返さない。"""
    full, segs = public_sets(repo_data)
    bad = []
    for k, v in data.items():
        for path, field, s in _leaves(k, v):
            if field in STRICT_FIELDS:
                if s in full:
                    continue
                if field == "who" and WHO_TPL.fullmatch(s):
                    continue
                if field == "src" and SRC_TPL.fullmatch(s):
                    continue
                if field in ("note", "memo"):
                    parts = [x.strip() for x in s.split(SEG_SEP) if x.strip()]
                    pat = SELL_NOTE_TPL if field == "note" else MEMO_AUTO_TPL
                    if all((x in segs) or pat.fullmatch(x) for x in parts):
                        continue
                bad.append(path)
            elif field in FREE_FIELDS:
                continue
            elif k in state_keys.PLAIN_NUMBER_KEYS:
                if not re.fullmatch(r"[0-9.,]*", s):      # 今月の入金額は数字だけ
                    bad.append(path)
            elif _is_ascii(s) or s in ENUM_OK or s in full:
                continue
            else:
                bad.append(path)
    return bad


# ── 本体 ───────────────────────────────────────────────────────────────────
def now_iso():
    t = datetime.now(timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def _next_saved_at(old):
    n = now_iso()
    if old and n <= str(old):                               # 時計が戻っていても savedAt は進める（門は「repo のほうが新しい」で取り込む）
        try:
            t = datetime.fromisoformat(str(old).replace("Z", "+00:00")).astimezone(timezone.utc)
            from datetime import timedelta
            t = t + timedelta(seconds=1)
            return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"
        except Exception:
            pass
    return n


def _labels(keys):
    return "・".join(LABEL.get(k, k) for k in keys)


def run_validate(path):
    r = subprocess.run([sys.executable, os.path.join(HERE, "validate_state.py"), "--path", path],
                       capture_output=True, text=True, cwd=ROOT)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def apply_event(event, state_path, owner, validate=True):
    """event（Issue の event JSON）を処理して結果の辞書を返す。state_path は検査を通れば書き換える。"""
    issue = (event or {}).get("issue") or {}
    login = ((issue.get("user") or {}).get("login") or "")
    title = issue.get("title") or ""
    if not owner or login.lower() != owner.lower():
        return {"status": "skip", "code": "owner", "message": "", "redact": False, "keys": [], "saved_at": ""}
    if not title.startswith(TITLE_PREFIX):
        return {"status": "skip", "code": "title", "message": "", "redact": False, "keys": [], "saved_at": ""}

    def rej(code, msg, redact=False, extra=""):
        m = ("⚠ **止めました（何も書き換えていません）**\n\n" + msg + "\n"
             + (extra + "\n" if extra else "")
             + ("\n依頼の本文は、公開されたままにしないため**削除しました**。\n" if redact else "")
             + "\n反映は、これまでどおり門の「📤 書き出す」を Claude に貼って「反映して」でもできます。")
        return {"status": "rejected", "code": code, "message": m, "redact": redact, "keys": [], "saved_at": ""}

    try:
        allowed = set(state_keys.exact_keys())
        payload = decode_block(extract_block(issue.get("body")))
        data, bases = parse_payload(payload, allowed)
    except ReqError as e:
        return rej(e.code, f"依頼を読めませんでした: {e.msg}。", e.redact)

    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        return rej("state", f"repo の state.json が読めません（{type(e).__name__}）。")
    if not isinstance(state, dict) or state.get("fmt") != "ccf-state" or not isinstance(state.get("data"), dict):
        return rej("state", "repo の state.json の形が想定と違います。")
    repo_data = state["data"]

    # 4. 自由記述の検問（先に・変化の有無にかかわらず）
    bad = find_unseen_text(data, repo_data)
    if bad:
        shown = "、".join(f"`{safe_path(b)}`" for b in bad[:6]) + (f" ほか{len(bad) - 6}か所" if len(bad) > 6 else "")
        return rej("text", "依頼の中に、**repo にまだ無い自由記述**（口座のメモ・売却のメモなど）がありました。"
                   "名前などを公開リポジトリに載せないための検査です。", True,
                   f"場所: {shown}（中身はここに書きません）")

    # 6. 変化の有無（機械の書き戻しだけの差は数えない）
    changes = {}
    for k, v in data.items():
        cur = repo_data.get(k)
        if cur is not None and same_decision(k, cur, v):
            continue
        changes[k] = v
    if not changes:
        return {"status": "noop", "code": "noop", "redact": False, "keys": [], "saved_at": state.get("savedAt") or "",
                "message": "✓ **変更はありませんでした**（依頼の中身は、repo の state.json と同じです）。何も書き換えていません。"}

    # 5. CAS
    stale = []
    for k in changes:
        cur = repo_data.get(k)
        h = "-" if cur is None else sha256_hex(cur)
        if h not in bases[k]:
            stale.append(k)
    if stale:
        return rej("conflict", f"repo の「{_labels(stale)}」が、この依頼を作ったあとに**変わっています**（別の更新が先に入った）。"
                   "上書きすると新しいほうを消すので、何もしていません。",
                   False, "門の赤い帯の「⭳ repo の保有で上書きする」で合わせてから、もう一度記録してください。")

    # 書く
    new = copy.deepcopy(state)
    for k, v in changes.items():
        new["data"][k] = v
    new["savedAt"] = _next_saved_at(state.get("savedAt"))
    text = json.dumps(new, ensure_ascii=False, indent=1) + "\n"
    if validate:
        d = tempfile.mkdtemp(prefix="ccf_state_")
        cand = os.path.join(d, "state.json")
        with open(cand, "w", encoding="utf-8") as f:
            f.write(text)
        rc, out = run_validate(cand)
        if rc != 0:
            fails = [ln.strip()[2:] for ln in out.splitlines() if ln.strip().startswith("- ")][:3]
            return rej("invalid", "入れたあとの state.json が、CI の検査（validate_state）を通りません。",
                       False, "理由: " + "／".join(fails) if fails else "")
    tmp = state_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, state_path)
    keys = list(changes)
    return {"status": "applied", "code": "applied", "redact": False, "keys": keys, "saved_at": new["savedAt"],
            "message": f"✓ **state.json に入れました**（{_labels(keys)}・保存 {new['savedAt']}）。\n\n"
                       "📈成績は数分で作り直されます。門は、次に開いたとき（または「↻ 反映できたか確認」）repo に追いつきます。"}


def _out(res, outpath):
    if not outpath:
        return
    with open(outpath, "a", encoding="utf-8") as f:
        f.write(f"status={res['status']}\ncode={res['code']}\nredact={'true' if res['redact'] else 'false'}\n"
                f"keys={','.join(res['keys'])}\nsaved_at={res['saved_at']}\n")


def main():
    ev = os.environ.get("GITHUB_EVENT_PATH")
    out = os.environ.get("GITHUB_OUTPUT")
    msgp = os.environ.get("CCF_MSG_PATH") or "/tmp/ccf_state_msg.md"
    state_path = os.environ.get("CCF_STATE_PATH") or os.path.join(ROOT, "state.json")
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER") or ""
    if not ev or not os.path.exists(ev):
        print("GITHUB_EVENT_PATH が無い——何もしない")
        _out({"status": "skip", "code": "noevent", "redact": False, "keys": [], "saved_at": ""}, out)
        return 0
    try:
        with open(ev, encoding="utf-8") as f:
            event = json.load(f)
        res = apply_event(event, state_path, owner)
    except Exception as e:                                   # 想定外: コメントは定型だけ（中身は書かない）
        print(f"::error::想定外の例外 {type(e).__name__}")
        _out({"status": "error", "code": "exception", "redact": False, "keys": [], "saved_at": ""}, out)
        with open(msgp, "w", encoding="utf-8") as f:
            f.write("⚠ **処理が止まりました**（想定外の失敗）。何も書き換えていないはずですが、Actions のログを確認してください。\n\n"
                    "反映は、門の「📤 書き出す」を Claude に貼って「反映して」でもできます。\n")
        raise
    with open(msgp, "w", encoding="utf-8") as f:
        f.write(res["message"] + "\n")
    _out(res, out)
    print(f"status={res['status']} code={res['code']} keys={res['keys']} redact={res['redact']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
