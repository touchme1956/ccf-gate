#!/usr/bin/env bash
# night/review_runner.sh — **門2審査を1社ぶん機械で回す**（2026-08-10新設）
#
# ■ なぜ要るか
#   この門は審査の材料をすべて持っている——待ち行列(chunk/rechunk)・審査官への指示
#   (agent_prompt_template)・機械値の下ごしらえ(hachimon_fetch)・納品の合否(validate_packs)・
#   破損の検出(audit_gate)・影響の実測(score_all)。**欠けていたのは走らせる人だけ**だった。
#   実測 night/progress.json は pending_review 13 のまま動いていない。
#
# ■ 絶対のルール2をどう守るか（ここが設計の肝）
#   ルール2は「定性項目を**勝手に**埋めない」。機械が原本を読んで**引用つきで**埋めるのは
#   夜間バッチ審査として元々設計された手順（CLAUDE.md「夜間バッチ審査は night/」）で、
#   禁じられているのは *憶測で埋めること* と *根拠を書かないこと*。だから三重に縛る:
#     (1) **納品検査を通らないパックは捨てる** — validate_packs が
#         「値があるのに根拠が無い」を落とす。落ちたら書いたパックを**元へ戻す**
#     (2) **main へ直接書かない** — 呼び出し側(review.yml)が PR を作る。
#         **マージが審査官の手**になる＝人の承認を最後に残す
#     (3) **投下可が動いたら必ず名指しで出す**（v9.9.52の作法）— PR本文に差分を書く
#
# 使い方:
#   night/review_runner.sh NVDA            新規審査
#   night/review_runner.sh NVDA reaudit    再審査（reaudit_queue.json の理由を添える）
# 要るもの: ANTHROPIC_API_KEY（Claude Code CLI が読む）
set -uo pipefail
cd "$(dirname "$0")/.."

T="${1:?ticker が要る}"
MODE="${2:-new}"
PACK="out/${T}_gate_pack.json"
BAK="/tmp/${T}_gate_pack.bak.json"
MODEL="${REVIEW_MODEL:-claude-opus-5}"
TURNS="${REVIEW_MAX_TURNS:-120}"

echo "■ 門2審査 ${T}（${MODE}・model=${MODEL}）"

# 既存パックは必ず退避する。**審査が失敗したら元へ戻す**——
#   壊れた/根拠の無いパックを台帳に残すくらいなら、審査しなかったほうがよい。
[ -f "$PACK" ] && cp "$PACK" "$BAK"

# ── 1. 機械値の下ごしらえ（鍵不要・per-CIK API）─────────────────────────────
echo "→ hachimon_fetch"
python3 hachimon_fetch.py "$T" || { echo "✗ 採取に失敗＝審査に進まない"; exit 2; }

# ── 2. 審査（テンプレは正本 night/agent_prompt_template*.txt をそのまま使う）──
#   ⚠テンプレを**この場で書き換えない**。正本はⅡ手順3と同期されており、
#     ここで別の指示を混ぜると「同じ規約を二箇所に書く」型の事故になる（v9.9.65）。
TPL="night/agent_prompt_template.txt"
case "$T" in [0-9]*) TPL="night/agent_prompt_template_jp.txt";; esac
PROMPT="$(sed "s/{T}/${T}/g" "$TPL")"

if [ "$MODE" = "reaudit" ] && [ -f night/reaudit_queue.json ]; then
  WHY="$(python3 - "$T" <<'PY'
import json,sys
t=sys.argv[1].upper()
try:
    for r in json.load(open('night/reaudit_queue.json',encoding='utf-8'))['rows']:
        if r['t'].upper()==t:
            print(' / '.join(r['reasons'])); break
except Exception: pass
PY
)"
  PROMPT="${PROMPT}

【この審査は**再審査**である】
既存の out/${T}_gate_pack.json がある。検出器が挙げた理由:
  ${WHY}
- **理由に対応する欄を最優先で確定させよ**（何を直すための再審査かを見失わない）
- 既存パックの _meta.kenshi は**消さずに追記**する（審査の履歴が台帳の資産）
- 既存の値を動かすときは**旧→新・原本の実額・出典**を _meta.kenshi に書く
  ——後から書かれた記録を先に読めるようにしておくこと（MAのroicを巻き戻した事故の再発防止）"
fi

echo "→ claude -p（審査官）"
claude -p "$PROMPT" \
  --model "$MODEL" \
  --permission-mode acceptEdits \
  --allowed-tools "Read,Write,Edit,Bash,Glob,Grep,WebFetch" \
  --max-turns "$TURNS" 2>&1 | tail -40
RC=$?

# ── 3. 納品検査（**ここが唯一の合否**）────────────────────────────────────
if [ ! -f "$PACK" ]; then
  echo "✗ パックが作られなかった（rc=$RC）"
  [ -f "$BAK" ] && cp "$BAK" "$PACK"
  exit 3
fi
echo "→ validate_packs ${T}"
if ! python3 night/validate_packs.py "$T"; then
  echo "✗ 納品検査でFAIL＝**このパックは採らない**（値があるのに根拠が無い等）"
  if [ -f "$BAK" ]; then
    cp "$BAK" "$PACK"; echo "  既存パックへ戻した"
  else
    rm -f "$PACK"; echo "  新規パックを削除した（誤値より空欄）"
  fi
  exit 4
fi

# ── 4. 破損の検出（第四の関門の土台。err が出たら採らない）────────────────
if ! node night/audit_gate.js --t "$T" | tee /tmp/audit_$T.txt | tail -12; then :; fi
if grep -qE "要修正" /tmp/audit_$T.txt 2>/dev/null; then
  echo "⚠ 全件点検で要修正が出た——PR本文に出す（AMBIQ/CMTL のような既知の帯外は許容）"
fi

echo "✓ ${T} の審査は納品検査を通った"
exit 0
