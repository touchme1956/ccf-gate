#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/check_state_issue.py — Issue から state.json を更新する道（night/apply_state_issue.py）の**オフライン検査**（v9.9.210）

何を見るか（ネット不要・実 repo の state.json は書き換えない＝一時ディレクトリで走らせる）:
  A 受け付ける: 正しい依頼が state.json に入る（savedAt が進む・他のキーは1バイトも動かない・キーの並びが保たれる・
      validate_state を通る）／3種の符号（z=raw deflate・d=zlib・p=無圧縮）／repo に無いキーを足す（前提 '-'）／2つ目の前提／機械の書き戻しだけの差は「変更なし」
  B 止める: オーナー以外・題名違いは skip／sha 不一致／切れた符号／許可されていないキー／前提が無い／大きすぎる（zip 爆弾）／
      CAS（repo が先に変わった）／入れたあとの state.json が validate_state を通らない
  C 自由記述の検問（rule 9）: 共有ベクトル night/state_issue_vectors.json の全件が期待どおり（JS 版と同じ答え）／
      止めたとき**依頼の中身をコメントに書かない**・本文を消す印（redact）が立つ
  D CLI（GITHUB_EVENT_PATH・GITHUB_OUTPUT・CCF_MSG_PATH）として走る／想定外の例外でも定型のコメントを残す
  E 状態の保存: 同じ依頼の再実行は「変更なし」（再配信しても二重に書かない）

使い方: python3 night/check_state_issue.py     終了コード 1 = 1件でも ✗
"""
import base64
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import apply_state_issue as A  # noqa: E402

OWNER = "touchme1956"
passed = failed = 0


def ok(c, m):
    global passed, failed
    if c:
        passed += 1
        print("  ✓ " + m)
    else:
        failed += 1
        print("  ✗ " + m)


def ser(o):
    return o if isinstance(o, str) else json.dumps(o, ensure_ascii=False, separators=(",", ":"))


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def b64u(b):
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def enc_payload(payload, enc="z"):
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if enc == "z":
        c = zlib.compressobj(9, zlib.DEFLATED, -15)
        raw = c.compress(raw) + c.flush()
    elif enc == "d":
        raw = zlib.compress(raw, 9)
    return enc + "." + b64u(raw)


def make_payload(data, bases, **over):
    dj = json.dumps({k: ser(v) for k, v in data.items()}, ensure_ascii=False, separators=(",", ":"))
    p = {"fmt": A.FMT, "ver": 1, "at": "2026-10-10T09:30:00.000Z", "bases": bases, "dataJson": dj, "sha": sha(dj)}
    p.update(over)
    return p


def body_of(block):
    return "門の「人の決定」を repo の state.json に入れる依頼です。\n\n```ccf-state\n" + block + "\n```\n"


def event(body, login=OWNER, title="[ccf-state] 保有を反映 2026-10-10 18:30", number=7):
    return {"issue": {"number": number, "title": title, "body": body, "user": {"login": login}}}


def bases_for(state, keys, extra=None):
    out = {}
    for k in keys:
        v = state["data"].get(k)
        out[k] = ["-" if v is None else sha(v)] + list((extra or {}).get(k, []))
    return out


# ── 固定の state（実 repo の形に合わせた小さい版）────────────────────────────
V = json.load(open(os.path.join(HERE, "state_issue_vectors.json"), encoding="utf-8"))


def base_state():
    data = {k: ser(v) for k, v in V["repo"].items()}
    data["pf:weights"] = ser({"net": {"QQQM": 40}, "city": {"MSFT": 5.000000001}, "total": 100})
    return {"fmt": "ccf-state", "ver": 1, "savedAt": "2026-10-08T11:38:16.000Z",
            "note": "門の「人の決定」の正本。", "data": data, "asof": "2026-09-23"}


def run(ev, state, validate=True):
    d = tempfile.mkdtemp(prefix="ccf_chk_")
    p = os.path.join(d, "state.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps(state, ensure_ascii=False, indent=1) + "\n")
    before = open(p, "rb").read()
    res = A.apply_event(ev, p, OWNER, validate=validate)
    after = open(p, "rb").read()
    return res, json.loads(after.decode("utf-8")), before, after


def add_lot(state_data, **kw):
    o = json.loads(state_data["pf:portfolio"])
    lot = {"sh": 1, "jpy": 80000, "bd": "2026-10-10", "who": "A", "acct": "成長",
           "src": "門の🏦保有で記録（約定日 2026-10-10）（A・成長）"}
    lot.update(kw)
    o["positions"][0]["bdLots"].append(lot)
    o["positions"][0]["sh"] += 1
    o["positions"][0]["bjpy"] += 80000
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


print("■ A. 受け付ける")
st = base_state()
newp = add_lot(st["data"])
payload = make_payload({"pf:portfolio": newp}, bases_for(st, ["pf:portfolio"]))
res, after, before, raw_after = run(event(body_of(enc_payload(payload))), st)
ok(res["status"] == "applied" and res["keys"] == ["pf:portfolio"], f"正しい依頼が入る（{res['status']}・{res['keys']}）")
ok(after["data"]["pf:portfolio"] == newp, "株数の値が依頼どおりになる")
ok(all(after["data"][k] == st["data"][k] for k in st["data"] if k != "pf:portfolio"), "ほかのキーは1バイトも動かない")
ok(list(after["data"].keys()) == list(st["data"].keys()) and list(after.keys()) == list(st.keys()), "キーの並びと上位の欄（note・asof）が保たれる")
ok(after["savedAt"] > st["savedAt"] and after["savedAt"].endswith("Z") and len(after["savedAt"]) == 24, f"savedAt が進む（{after['savedAt']}）")
ok(res["saved_at"] == after["savedAt"], "結果の saved_at は書いた値と同じ")
ok(raw_after.decode("utf-8") == json.dumps(after, ensure_ascii=False, indent=1) + "\n", "書式は state.js の書き出しと同じ（インデント1・末尾に改行）")
ok("state.json に入れました" in res["message"] and "株数" in res["message"], "コメントは日本語で何を入れたかを言う")

for enc in ("d", "p"):
    st = base_state()
    res, after, *_ = run(event(body_of(enc_payload(make_payload({"pf:portfolio": add_lot(st["data"])}, bases_for(st, ["pf:portfolio"])), enc))), st)
    ok(res["status"] == "applied", f"符号 {enc}（{'zlib' if enc == 'd' else '無圧縮'}）も読める")

st = base_state()
res, after, *_ = run(event(body_of(enc_payload(make_payload({"pf:net": ser({"add": {"QQQM": 1}}), "pf:monthly_total": "200000"},
                                                          bases_for(st, ["pf:net", "pf:monthly_total"]))))), st)
ok(res["status"] == "applied" and after["data"]["pf:net"] == '{"add":{"QQQM":1}}' and after["data"]["pf:monthly_total"] == "200000",
   f"repo に無いキー（前提 '-'）を足せる／今月の入金額は数字の文字列でも通る（{res['status']}）")
ok(list(after["data"])[-1] == "pf:net" and list(after["data"]).index("pf:monthly_total") == list(st["data"]).index("pf:monthly_total"),
   "新しいキーは末尾に足され、もとからあるキー（今月の入金額）は元の位置のまま値だけ替わる")

st = base_state()
other = json.loads(st["data"]["pf:portfolio"]); other["positions"][0]["sh"] = 9
mid = json.dumps(other, ensure_ascii=False, separators=(",", ":"))
newp = add_lot(st["data"])
st_moved = copy.deepcopy(st); st_moved["data"]["pf:portfolio"] = mid           # repo は、依頼を作ったあとに自分の前回の依頼で進んでいる
p2 = make_payload({"pf:portfolio": newp}, {"pf:portfolio": [sha(st["data"]["pf:portfolio"]), sha(mid)]})
res, *_ = run(event(body_of(enc_payload(p2))), st_moved)
ok(res["status"] == "applied", "前提が2つ（最後に同期した repo の値・前に送った値）のどちらかに今の repo が一致すれば入る")

st = base_state()
mach = json.loads(st["data"]["pf:portfolio"]); mach["fx"] = 151.5
for p_ in mach["positions"]:
    p_["npx"] = 123.45; p_["npxAuto"] = True
res, after, before, raw_after = run(event(body_of(enc_payload(make_payload({"pf:portfolio": json.dumps(mach, ensure_ascii=False)}, bases_for(st, ["pf:portfolio"]))))), st)
ok(res["status"] == "noop" and before == raw_after, "機械の書き戻し（npx・npxAuto・fx）だけの差は「変更なし」で、ファイルは1バイトも動かない")

print("■ B. 止める（何も書き換えない）")
def expect_reject(name, ev, st_, code, redact=None):
    res, after, before, raw_after = run(ev, st_)
    good = res["status"] == "rejected" and res["code"] == code and before == raw_after and (redact is None or res["redact"] is redact)
    ok(good, f"{name}（{res['status']}/{res['code']}・redact={res['redact']}）")
    return res

st = base_state()
good_body = body_of(enc_payload(make_payload({"pf:portfolio": add_lot(st["data"])}, bases_for(st, ["pf:portfolio"]))))
res, _, before, raw_after = run(event(good_body, login="someone-else"), st)
ok(res["status"] == "skip" and before == raw_after and res["message"] == "", "オーナー以外の Issue は skip（何も書かず、コメントもしない）")
res, _, before, raw_after = run(event(good_body, title="ふつうの Issue"), st)
ok(res["status"] == "skip", "題名が [ccf-state] で始まらなければ skip")
res, _, before, raw_after = run({"issue": {"number": 1, "title": "[ccf-state] x", "body": good_body, "user": {"login": OWNER.upper()}}}, st)
ok(res["status"] == "applied", "オーナー名の大文字小文字は区別しない")

pl = make_payload({"pf:portfolio": add_lot(st["data"])}, bases_for(st, ["pf:portfolio"]))
pl["sha"] = "0" * 64
expect_reject("sha が合わない", event(body_of(enc_payload(pl))), st, "sha", True)
blk = enc_payload(make_payload({"pf:portfolio": add_lot(st["data"])}, bases_for(st, ["pf:portfolio"])))
expect_reject("途中で切れた符号", event(body_of(blk[: len(blk) // 2])), st, "format", True)
expect_reject("囲みが無い本文", event("ただの文章です"), st, "format", True)
expect_reject("符号の形が違う", event(body_of("x.abc")), st, "format", True)
expect_reject("許可されていないキー", event(body_of(enc_payload(make_payload({"pf:bogus": "1"}, {"pf:bogus": ["-"]})))), st, "keys", True)
r = expect_reject("許可されていないキー名に名前があっても、コメントに書かない", event(body_of(enc_payload(make_payload({"pf:テスト氏": "1"}, {"pf:テスト氏": ["-"]})))), st, "keys", True)
ok("テスト氏" not in r["message"], "  └ コメントにキー名（依頼の中身）を書かない")
expect_reject("台帳 g7: は入れない", event(body_of(enc_payload(make_payload({"g7:MSFT": "{}"}, {"g7:MSFT": ["-"]})))), st, "keys", True)
expect_reject("前提（bases）が無い", event(body_of(enc_payload(make_payload({"pf:portfolio": add_lot(st["data"])}, {})))), st, "format", True)
expect_reject("値が文字列でない", event(body_of(enc_payload({"fmt": A.FMT, "ver": 1, "bases": {"pf:sold": ["-"]},
                                                           "dataJson": json.dumps({"pf:sold": []}), "sha": sha(json.dumps({"pf:sold": []}))}))), st, "size", True)
bomb = b64u(zlib.compress(b"0" * 5_000_000, 9)[2:-4])      # raw deflate の形（先頭2バイトと末尾4バイトを除く）で 5MB に伸びる
expect_reject("伸ばすと大きすぎる依頼（zip 爆弾）", event(body_of("z." + bomb)), st, "size", True)

# CAS
st = base_state()
req = make_payload({"pf:portfolio": add_lot(st["data"])}, bases_for(st, ["pf:portfolio"]))
st_changed = copy.deepcopy(st)
o = json.loads(st_changed["data"]["pf:portfolio"]); o["positions"][0]["sh"] = 10
st_changed["data"]["pf:portfolio"] = json.dumps(o, ensure_ascii=False, separators=(",", ":"))
r = expect_reject("CAS: 依頼を作ったあとに repo の値が変わっていれば止める", event(body_of(enc_payload(req))), st_changed, "conflict", False)
ok("株数" in r["message"] and "上書き" in r["message"], "  └ コメントは何が変わったか（株数）と、どうすればよいか（repo の保有で上書き）を言う")
st_abs = base_state()
req = make_payload({"pf:net": ser({"add": {"QQQM": 1}})}, {"pf:net": ["-"]})
st_has = copy.deepcopy(st_abs); st_has["data"]["pf:net"] = ser({"add": {"SMH": 1}})
expect_reject("CAS: repo に無いはずのキーが、あとから入っていても止める", event(body_of(enc_payload(req))), st_has, "conflict", False)

# validate_state を通らない
st = base_state()
bad = json.dumps({"asof": "x"})                                   # positions 配列が無い pf:portfolio
r = expect_reject("入れたあとの state.json が validate_state を通らなければ止める（positions が無い）",
                  event(body_of(enc_payload(make_payload({"pf:portfolio": bad}, bases_for(st, ["pf:portfolio"]))))), st, "invalid", False)
ok("positions" in r["message"], "  └ 理由（CI の検査の言葉）をコメントに出す")

print("■ C. 自由記述の検問（名前を公開リポジトリに載せない）")
def ser_map(m):
    return {k: ser(v) for k, v in m.items()}

repo_ser = ser_map(V["repo"])
badn = 0
for c in V["cases"]:
    got = A.find_unseen_text(ser_map(c["send"]), repo_ser)
    if got != c["expect"]:
        badn += 1
        print(f"    ✗ {c['name']}: {got} ≠ {c['expect']}")
ok(badn == 0, f"共有ベクトル {len(V['cases'])}件が期待どおり（JS 版 ccfState.unseenText と同じ表）")

st = base_state()
sneaky = "楽天証券 テスト氏 証券口座(新NISA) 2株（古い記録）"
newp = add_lot(st["data"], src=sneaky)
r = expect_reject("repo に無い自由記述（古い文に名前）は止める", event(body_of(enc_payload(make_payload({"pf:portfolio": newp}, bases_for(st, ["pf:portfolio"]))))), st, "text", True)
ok("テスト氏" not in r["message"] and sneaky not in r["message"] and "positions[0].bdLots[1].src" in r["message"],
   "  └ コメントには場所（欄の名前）だけを書き、**中身は書かない**")
ok("削除しました" in r["message"], "  └ 本文を消したと言う（redact の印も立つ）")
# 道筋に入る辞書のキー名が名前でも、コメントには `?` で出る（場所の道筋は依頼の中のキー名を含む）
o2 = json.loads(add_lot(st["data"])); o2["positions"][0]["テスト氏メモ"] = "未知の文"
r = expect_reject("辞書のキー名に日本語があって値が自由な文でも止める", event(body_of(enc_payload(make_payload({"pf:portfolio": json.dumps(o2, ensure_ascii=False)}, bases_for(st, ["pf:portfolio"]))))), st, "text", True)
ok("テスト氏" not in r["message"] and "?" in r["message"] and "positions[0]." in r["message"], "  └ 場所の道筋のキー名は安全な文字だけにする（日本語は ? に）")
newp = add_lot(st["data"], who="テスト氏")
expect_reject("who が名前なら止める", event(body_of(enc_payload(make_payload({"pf:portfolio": newp}, bases_for(st, ["pf:portfolio"]))))), st, "text", True)
# 検問は「変化が無いキー」にも掛かる（既に公開されている文の再送は通る）
st = base_state()
res, *_ = run(event(body_of(enc_payload(make_payload({"pf:portfolio": st["data"]["pf:portfolio"]}, bases_for(st, ["pf:portfolio"]))))), st)
ok(res["status"] == "noop", "既に repo にある内容の再送は「変更なし」（検問も通る）")

print("■ D. CLI として走る（GITHUB_EVENT_PATH・GITHUB_OUTPUT・CCF_MSG_PATH）")
st = base_state()
d = tempfile.mkdtemp(prefix="ccf_cli_")
sp, ep, op, mp = (os.path.join(d, n) for n in ("state.json", "event.json", "out.txt", "msg.md"))
open(sp, "w", encoding="utf-8").write(json.dumps(st, ensure_ascii=False, indent=1) + "\n")
ev = event(body_of(enc_payload(make_payload({"pf:portfolio": add_lot(st["data"])}, bases_for(st, ["pf:portfolio"])))))
json.dump(ev, open(ep, "w", encoding="utf-8"), ensure_ascii=False)
env = dict(os.environ, GITHUB_EVENT_PATH=ep, GITHUB_OUTPUT=op, CCF_MSG_PATH=mp, CCF_STATE_PATH=sp, GITHUB_REPOSITORY_OWNER=OWNER)
r = subprocess.run([sys.executable, os.path.join(HERE, "apply_state_issue.py")], env=env, capture_output=True, text=True)
outs = dict(ln.split("=", 1) for ln in open(op, encoding="utf-8").read().splitlines() if "=" in ln)
ok(r.returncode == 0 and outs.get("status") == "applied" and outs.get("keys") == "pf:portfolio" and outs.get("redact") == "false" and outs.get("saved_at", "").endswith("Z"),
   f"CLI が出力（status・keys・redact・saved_at）を書く（{outs}）")
ok("state.json に入れました" in open(mp, encoding="utf-8").read(), "コメント用のファイルを書く")
ok(json.load(open(sp, encoding="utf-8"))["data"]["pf:portfolio"] == add_lot(st["data"]), "state.json が書き換わる")
# 同じ依頼をもう一度（再配信・再実行）→ 変更なし
open(op, "w").close()
r = subprocess.run([sys.executable, os.path.join(HERE, "apply_state_issue.py")], env=env, capture_output=True, text=True)
outs = dict(ln.split("=", 1) for ln in open(op, encoding="utf-8").read().splitlines() if "=" in ln)
ok(outs.get("status") == "noop", f"同じ依頼の再実行は「変更なし」（二重に書かない）（{outs.get('status')}）")
# 想定外の例外
json.dump({"issue": {"title": "[ccf-state] x", "body": "x", "user": {"login": OWNER}}}, open(ep, "w", encoding="utf-8"))
open(sp, "w", encoding="utf-8").write("{ this is not json")
open(op, "w").close()
r = subprocess.run([sys.executable, os.path.join(HERE, "apply_state_issue.py")], env=env, capture_output=True, text=True)
outs = dict(ln.split("=", 1) for ln in open(op, encoding="utf-8").read().splitlines() if "=" in ln)
ok(outs.get("status") == "rejected" and outs.get("code") in ("format", "state"), f"壊れた入力でも止まらず、定型のコメントを出す（{outs.get('status')}/{outs.get('code')}）")
# 鍵（GITHUB_REPOSITORY_OWNER）が無ければ何もしない
env2 = dict(env); env2.pop("GITHUB_REPOSITORY_OWNER", None)
open(op, "w").close()
subprocess.run([sys.executable, os.path.join(HERE, "apply_state_issue.py")], env=env2, capture_output=True, text=True)
ok(dict(ln.split("=", 1) for ln in open(op, encoding="utf-8").read().splitlines() if "=" in ln).get("status") == "skip", "オーナー名が無ければ何もしない（skip）")

print("■ E. 実際の repo の state.json に対して（読むだけ）")
real = json.load(open(os.path.join(ROOT, "state.json"), encoding="utf-8"))
res, after, before, raw_after = run(event(body_of(enc_payload(make_payload({k: v for k, v in real["data"].items()}, bases_for(real, list(real["data"])))))), real)
ok(res["status"] == "noop" and before == raw_after, "今の state.json の中身を丸ごと送っても、検問を通り「変更なし」になる（実データの自由記述は全部 repo に既にある）")

print(f"\n結果: ✓ {passed} / ✗ {failed}")
sys.exit(1 if failed else 0)
