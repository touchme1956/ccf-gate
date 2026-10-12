#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ops_status.py — 運用サイクルの回転状態を機械で出す（2026-08-04新設・「すべて回るように」）

なぜ要るか:
  この台帳の周期作業は 毎営業日2本・月次5本・四半期2本・年次5本 に増えた。回っているかどうかを
  人の記憶で管理すると20年は続かない（予実台帳をCIに入れたのと同じ理由）。各作業の
  「最終実行がいつか・期限内か」を出力ファイルの実測から作り、門の⚙自動化タブが表示する。
  **回っていない作業が黙って止まるのが最悪**——止まっていること自体を毎日見えるようにする。

日付の取り方:
  出力JSONに日付フィールドがあればそれ（採取時刻の実測）、無ければ git の最終コミット日。
  git履歴が浅いcheckout(fetch-depth:1)では正しい日付が出ないため、CI側は fetch-depth:0 で走らせる。
  取れないものは「不明」と書く——不明を健全と読まない（ルール7の親戚）。

使い方: python3 night/ops_status.py  → out/ops_status.json ＋ 標準出力に一覧
"""
import glob
import json, os, re, subprocess, sys
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git_date(path):
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%cs", "--", path],
                           capture_output=True, text=True, cwd=BASE, timeout=30)
        d = r.stdout.strip()
        return d if len(d) == 10 else None
    except Exception:
        return None


def json_field(path, *keys):
    try:
        d = json.load(open(os.path.join(BASE, path), encoding="utf-8"))
        for k in keys:
            v = d.get(k)
            if isinstance(v, str) and len(v) >= 10:
                return v[:10]
        return None
    except Exception:
        return None


def er_last_obs():
    try:
        d = json.load(open(os.path.join(BASE, "out", "er_ledger.json"), encoding="utf-8"))
        return max((o.get("date", "") for o in d.get("observations", [])), default=None)
    except Exception:
        return None


def mw_formation_years():
    """前向きの検定（mw）の SEC 版（H7）の組入れがある年の集合。2026年は事前登録に凍結
    （out/mw_forward_prereg.json の frozen.sec_formation_2026）、以後は form_sec が書く out/mw_forward_sec_formation_Y.json。
    読めない・weights_fcap が空のファイルは数えない（道具もそれを組入れとして使えない）"""
    ys = set()
    try:
        pr = json.load(open(os.path.join(BASE, "out", "mw_forward_prereg.json"), encoding="utf-8"))
        if ((pr.get("frozen") or {}).get("sec_formation_2026") or {}).get("weights_fcap"):
            ys.add(2026)
    except Exception:
        pass
    for f in glob.glob(os.path.join(BASE, "out", "mw_forward_sec_formation_*.json")):
        m = re.search(r"_(\d{4})\.json$", f)
        if not m:
            continue
        try:
            if json.load(open(f, encoding="utf-8")).get("weights_fcap"):
                ys.add(int(m.group(1)))
        except Exception:
            pass
    return ys


def mw_formation_anchor():
    """SEC 版の最新の組入れの年 Y → "Y-07-01"（Y年7月〜翌6月に持つ組入れ）。無ければ None（不明を健全と読まない）"""
    ys = mw_formation_years()
    return f"{max(ys)}-07-01" if ys else None


# ── 前向きの検定の見張り（2026-09-29新設・同日 検査役の指摘で (a')(d)・外し方・外来の文の無害化を足した）────
#   盤は日付しか見ないので、『毎月走るのに月を取れない』（Yahoo・French・投信の CSV に弾かれ続ける）は
#   緑のまま進む。道具は値の出ない月を3か月待つと『欠測』として固定し、**固定した月は後から戻せない**
#   （20年の検定に永久の穴が空く）。錨の日付が期限内でも、次のどれかで ⚠ にする:
#     (a)  値の出ない月が、最後の実行の時点で2か月以上待ちになっている（道具は3を超えると固定する）
#     (a') 最後の実行が月を『欠測』として固定した——固定した次の実行から (a) は黙るので、取り返しのつかない出来事
#          そのものが盤にも Issue にも一度も出ないまま消えていた。固定した月（locked_on）の実行のあいだ出す
#     (b)  最後の実行の記録（nx の log）に『失敗』がある（mw の出力は log を持たない＝(a) だけで見る）
#     (c)  道具が凍結の記録と違う（night/check_forward_frozen.py の check をそのまま呼ぶ＝二重実装しない）。
#          ops.yml はそのとき更新を回さない＝月が進まないので、日付の期限（40日）より先にここで知らせる
#     (d)  最後の実行が失敗・時間切れ・途中で止まった（out/forward_run.json＝ops.yml の forward ジョブが段ごとに
#          書く印）。落ちた実行は出力を書かないので、印が無いと 40日の期限（最大で約40日後）まで誰も気づけない
#   ⚠ 月は**今日ではなく最後の実行の日（generated）で数える**——道具と同じ数え方。今日で数えると、毎月2日の
#     実行の前日に、正常な1か月待ち（French は約1か月遅れで出る）を2か月待ちと数えて鳴らしてしまう。
#     実行そのものが止まったことは、錨の日付の期限（40日）と (d) が見る。
#   ⚠ 外し方（鳴りっぱなしは鳴らないのと同じ）: FORWARD_WATCH_ACK に理由を書く。理由の無い行は効かない。
#     (出力のパス, 仮説) は (a)(a') をその仮説だけ、(出力のパス, "log:<種類>") は (b) の『失敗』をその種類だけ外す
#     （種類＝ログの行の先頭の語: 'brand:'・'jp:'・'indmom:'・'F2_brand10_vs_SPY 202610:' なら F2_brand10_vs_SPY）。
#     lock_brand は次の年の一覧を観測するまで毎月 API を呼ぶので、API が恒久的に変われば毎月『brand: 取得失敗』が残る。
#   ⚠ 所見に入れる外来の文（例外の文・ログ・待ちの理由）は _plain() を通す——山括弧を似た字へ替え、長さを切る。
#     how は ⚙カード（innerHTML）・📋今日・Issue（Markdown）へそのまま届く。例外の文の山括弧（urlopen error 等）が
#     タグとして読まれて理由が消えたり、HTTP の理由句に仕込まれた HTML が実行されたりしないように（門の側でも esc する＝二重に守る）
#   ⚠ 所見を作る部分は丸ごと try で包む——出力の形が想定と違って例外を投げると ops_status.py ごと落ち、
#     ops.yml と events.yml のコミット段（ops_status の後ろ）まで止まる。例外は「見張りを回せない（型名）」という所見にする
FORWARD_WATCH = {"mwforward": ("out/mw_forward.json", "mw"), "nxforward": ("out/nx_forward.json", "nx")}
FORWARD_RUN = "out/forward_run.json"
FORWARD_WAIT_WARN = 2
FORWARD_TEXT_MAX = 120
FORWARD_WATCH_ACK = {
    # (出力のパス, 仮説): "理由（いつ・何が終わったか・事前登録のどの規則で止まるか）",
    # 例 ("out/nx_forward.json", "F4_RSST_vs_SPY"): "20XX-XX に RSST が償還（stopping_rules どおり F4 はここで止まる）",
    # (出力のパス, "log:<種類>"): "理由（いつ・何が変わったか・その規則はどう扱われるか）",
    # 例 ("out/nx_forward.json", "log:brand"): "20XX-XX に Interbrand の API が廃止（F2 は最後の形成のまま流れる）",
}
FORWARD_RUN_JA = {"started": "途中で止まった（時間切れ・中断の疑い）", "failed": "失敗した",
                  "timeout": "時間切れで止めた", "frozen": "凍結の検査に落ちて回さなかった",
                  "broken_output": "出力が JSON として読めず、戻してコミットしなかった"}
# 手で回し直すときの案内（2026-09-29 検査役の指摘: 「26日以降か次の2日」だけでは、定期実行が落ちたときの回復で逆向きになる）。
#   nx の F2 は、次の年のブランドの一覧を**初めて観測した日**の月末で組む（26日以降なら翌月末）＝月1回の実行なら
#   『公開の翌月末』。一覧が出た月の 26日〜翌月25日に観測すれば形成は正しい月になる。
FORWARD_RERUN_HINT = {
    "mwforward": "手で回し直すなら Actions → monthly ops → Run workflow（forward=auto）。mw は回す日で答えが変わらない"
                 "（取り込むのは終わった月だけ）ので、いつ回してもよい。",
    "nxforward": "手で回し直すなら Actions → monthly ops → Run workflow（forward=auto）: 今月の定期実行（2日・予備の3日）が"
                 "落ちた／時間切れで、新しいブランドの一覧が**前の月までに**出ていたなら**その月の25日までに**回す"
                 "（26日以降に回すと F2 の形成が『公開の翌月末』より1か月遅れる。F3 の選択も早いほうがよい）。"
                 "**今月の2日より後に**新しい一覧が出たなら26日以降に回すか次の2日を待つ（25日までに回すと形成が1か月早まる）。"
                 "一覧が出たかは nx の log（brand: の行）か Interbrand の発表で分かる。",
}


def _plain(s, n=FORWARD_TEXT_MAX):
    """外から来た文を所見に入れる形へ: 空白を詰め、山括弧を似た字へ替え（HTML・Markdown でタグとして読まれない）、長さを切る"""
    s = " ".join(str(s).split()).replace("<", "‹").replace(">", "›")
    return s if len(s) <= n else s[:n - 1] + "…"


def _acked(path, key):
    return bool(str(FORWARD_WATCH_ACK.get((path, key)) or "").strip())


def _log_kind(line):
    """ログの行の種類＝先頭の語（'brand: 取得失敗 …' → 'brand'／'F2_brand10_vs_SPY 202610: 取得の失敗 …' → 'F2_brand10_vs_SPY'）"""
    m = re.match(r"\s*([^\s:：]+)", line)
    return m.group(1) if m else ""


def _ym_label(m):
    try:
        m = int(m)
    except (TypeError, ValueError):
        return None, None
    return m, f"{m // 100}-{m % 100:02d}"


def forward_watch(path, group):
    """前向きの検定の出力を読み、見張りの所見の文のリストを返す（空なら何も無い）。
    出力が読めなければ (c) だけを見る——そのときは錨の日付が取れず、盤は unknown（健全と読まない）になる"""
    found = []
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:                   # どこから import されても同じ night/ の本体を読む
            sys.path.insert(0, here)
        import check_forward_frozen as CF          # 凍結の検査の本体をそのまま使う（二重実装しない）
        bad, _ = CF.check([group])
        if bad:
            found.append(f"道具が凍結の記録と違う {len(bad)}件（例: {_plain(bad[0].get('path'), 60)}・{_plain(bad[0].get('why'), 60)}）"
                         "＝ops.yml は更新を回していない → python3 night/check_forward_frozen.py で名指しと戻し方を見る")
    except Exception as e:
        found.append(f"凍結の検査を回せない（{type(e).__name__}）＝道具が記録どおりか分からない")
    try:
        d = json.load(open(os.path.join(BASE, path), encoding="utf-8"))
        g = str(d.get("generated") or "")
        gym = int(g[:4]) * 12 + int(g[5:7])
    except Exception:
        return found
    try:
        found += _forward_findings(path, group, d, g, gym)
    except Exception as e:
        found.append(f"見張りを回せない（{type(e).__name__}）＝{path} の形が想定と違う"
                     "（道具の出力の形が変わった／壊れた？）→ 中身を確かめる")
    return found


def _forward_findings(path, group, d, g, gym):
    """(a)(a')(b)(d) の所見。形が想定と違えば例外を投げる（呼び手が『見張りを回せない』にする）"""
    found = []
    hyps = d.get("hypotheses") or {}
    if not isinstance(hyps, dict):
        raise TypeError(f"hypotheses が {type(hyps).__name__}")
    for h, v in sorted(hyps.items()):
        if _acked(path, h):
            continue
        fw = (v or {}).get("forward") or {}
        for w in fw.get("waiting_for") or []:
            m, lab = _ym_label(w.get("m") if isinstance(w, dict) else w)
            if m is None:
                continue
            age = gym - (m // 100 * 12 + m % 100)
            if age >= FORWARD_WAIT_WARN:
                why = (w.get("why") if isinstance(w, dict) else None) or ""
                # mw の出力は待ちの理由を残さない。SEC 版（H7）だけは理由が機械で分かる＝その年の組入れが無い
                if not why and h.startswith("H7_"):
                    y = m // 100 if m % 100 >= 7 else m // 100 - 1
                    if y not in mw_formation_years():
                        why = f"{y}年7月の組入れが無い＝form_sec {y} を回してコミットする（手順は『前向きの検定 SEC版の組み直し』）"
                found.append(f"{h} の {lab} が{age}か月待ち" + (f"（{_plain(why)}）" if why else ""))
        # (a') 最後の実行が欠測として固定した月（固定した月の実行のあいだ出す＝一度は必ず見える）
        for r in fw.get("months") or []:
            if not (isinstance(r, dict) and r.get("missing")):
                continue
            if str(r.get("locked_on") or "")[:7] != g[:7]:
                continue
            m, lab = _ym_label(r.get("m"))
            if m is None:
                continue
            note = r.get("note") or ""
            found.append(f"{h} の {lab} を欠測として固定した（{str(r.get('locked_on'))[:10]}・戻せない）"
                         + (f"（{_plain(note)}）" if note else ""))
    fails = [x for x in (d.get("log") or []) if isinstance(x, str) and "失敗" in x
             and not _acked(path, "log:" + _log_kind(x))]
    if fails:
        found.append(f"最後の実行の記録に『失敗』が{len(fails)}行（例: {_plain(fails[0], 100)}）")
    # (d) 最後の実行の印。読めなければ何も言わない（錨の日付と (a)(b) が見る）
    try:
        runs = json.load(open(os.path.join(BASE, FORWARD_RUN), encoding="utf-8")).get("runs") or {}
    except Exception:
        runs = {}
    r = runs.get(group) if isinstance(runs, dict) else None
    if isinstance(r, dict):
        oc, rd = str(r.get("outcome") or ""), str(r.get("date") or "")[:10]
        if oc and oc != "ok" and rd >= g[:10]:
            found.append(f"最後の実行（{_plain(rd, 12)}・{_plain(r.get('trigger') or '?', 24)}）が"
                         f"{FORWARD_RUN_JA.get(oc) or _plain(oc, 30)}"
                         + (f"（終了コード {_plain(r.get('rc'), 12)}）" if str(r.get("rc") or "0") != "0" else "")
                         + "＝その回は月を取り込んでいない")
    return found


def kessan_last(suffix):
    files = glob.glob(os.path.join(BASE, "out", "kessan", f"*{suffix}"))
    if not files:
        return None
    dates = [git_date(os.path.relpath(f, BASE)) for f in files]
    dates = [d for d in dates if d]
    return max(dates) if dates else None


# 各周期作業の定義: (id, 表示名, 周期ラベル, 期限日数, 日付の取り方, 回し方)
# 期限日数は「これを超えたら止まっているとみなす」線——毎営業日=4日(連休吸収)/月次=40日/四半期=100日/年次=430日
# ── 各作業が「何をしているか」（2026-08-17新設・ユーザー指示）────────────────
#   カードには回し方(how)しか出ておらず、名前だけでは何の作業か判らなかった。
#   書き方の約束: **① 何をするか ② 止まると何が起きるか** の2文。専門語には言い換えを添える。
#   ⚠ここは説明であって判定ではない——門の合否・採点・売却規律には一切効かない。
WHAT = {
    "market": "監視している銘柄の株価とドル円を毎日取ってくる。止まると🏦保有の評価額が古い株価のままになる（買付の合否は動かないが、いくら持っているかが合わなくなる）",
    "events": "保有・監視銘柄の臨時の届出（減損・役員の退任・監査人が過去の決算を「信頼できない」と言う・破産・上場廃止の通知）を毎日拾う。四半期の点検と点検のあいだ3ヶ月の隙間を埋める見張りで、止まるとその隙間が無防備になる",
    "parity": "ブラウザで見る門と、端末の計算が同じ答えを出すかを実ブラウザで369社ぶん突き合わせる。止まると「同じ台帳を見る二つが違うことを言う」を誰も見張らなくなる",
    "today": "各検出器の結果を集めて「📋今日やること」を作る。止まるとあの画面が古い中身を出し続ける——しかも見た目は「やることはありません」と同じになる",
    "freshness": "この回転盤自身の死角を見る。盤は各作業の『日付』しか見ないので、①日付は動くのに中身が凍っている ②中身は動くのに元データが死んでいる、を別に測る",
    "er": "「この株は年何%」という門の推定を、月に一度そのときの株価とともに封じ込める。20年後に推定が当たっていたかを答え合わせするための台帳で、止まると検証が永久にできない",
    "divy": "各社の配当利回りを別に記録する。株価だけ見ると配当のぶんリターンが低く出るので、上の予実を突き合わせるときにこれが要る",
    "gatehist": "毎日の採点結果のうち『変わったところだけ』を残す。止まると履歴に穴が空き、後から埋められない（gitの履歴はCIと作業ブランチが混ざって一本の系列にならない）",
    "irrcov": "歴史の検証で唯一効いた指標(irr＝顧客が乗り換えるとき費用を負うか)が、全上場企業の何%に付いているかを数える。判定には使わない",
    "histval": "今のPERが『その銘柄自身の過去』の何%タイルかを出す。表示だけで合否には使わない。止まると古い分位を今日の分位として出し続ける（画面は何も言わない）",
    "returns": "保有・ポートフォリオ・S&P500 のトータルリターンを**円建てに揃えて**出す。表示だけで判定には不使用。止まると古いリターンを今日のリターンとして出し続ける（画面は何も言わない）",
    "returnseries": "📈成績タブの**日次の推移**（保有・S&P500・投じた円）を作る。同じ道具(fetch_returns)が returns.json と同時に書くが、**買付日が判る行が消えると推移だけ作れない**——そのとき表は更新され続けるので、別の錨で数えないとグラフだけ静かに古くなる。表示だけで判定には不使用",
    "profiles": "各社の原本(10-K・有報)から「何をしている会社か」を抜いて配る。表示だけ。**英文のままでは読めない**ので日本語の要約を out/profiles_ja.json に別で持つ（night/profiles_ja.py。素材が変われば指紋で自動的に「古い」へ落ち、未訳は📌今日タブに出る）",
    "netplan": "網(ETF)の材料を作る——網の門(ami.html)の規約（レバレッジ／純資産／設定3年／経費率0.75%）をそのまま当てた合否と、経費率・実効銘柄数・加重経費率・ルックスルー。🛒買付順位の◈網の節がこれを読む。**判定は持たない**（ETFの選定と網/城の比率は門の外＝DCA側の決断）。止まると **NASA が3年を越えても⛔のまま**／経費率や純資産が古いまま画面に出続ける（画面は何も言わない）",
    "logos": "銘柄のロゴを取り込み、その**ロゴ自身の色**で行を淡く染める。表示だけで判定には不使用。"
             "止まると新しく審査した社が色もロゴも無いまま気づかれない（2026-08-17の実害）",
    "excwatch": "門が止めているのを承知で買った銘柄を、止めている当の指標で四半期ごとに測り直す。止まると警報を切ったまま乗ることになる",
    "irr85hist": "irr=85 の特権（Ω75未満でも土俵に上がれる／席で先に置く）を与えてよい社かを、その社自身の過去の実現リターンで裁く材料。止まると新しく85になった社が無検証で特権を受ける＝甘い側へ壊れる",
    "irr85mech": "堀の根拠にした原本の一文が、最新の年次報告にまだ在るかを一字一句で照合する。消えたら赤信号（ただし在っても安全の証明にはならない片側の検査）",
    "irr70mech": "同じ照合を irr=70 の45社へ当てる。**コストは 70→50 の一方向**（判定圏の70→50は投下可を10社→5社にする一方、50→70も85→70も0社しか動かさない）ので、85 と同じ重さで見張る",
    "castlecorr": "保有銘柄が『同時に落ちる』関係にないかを10年の値動きで測る。1銘柄8%の上限は守っていても束では一度も見ていなかったので、その材料",
    "irr85audit": "irr=85 の根拠が「顧客の側が再認定の費用と時間を負う」を本当に述べているかを型で仕分ける作業リスト。自社が取る認証や願望形は当たらない",
    "irr85scope": "その堀が会社の売上の何%に及ぶか、認定は何年もつかを原本から拾う。表示だけで線は引かない",
    "irr85myrule": "irr=85 の社を、あなた自身の選定ルール（営業利益率・FCF転換・売上成長の下限）で採点し、門との食い違いを名指しする",
    "irr85dual": "新しく irr=85 を付けたとき、別の読み手が独立に検証したかを数える。関門ではなく作業リスト（未検証は欠陥ではなく工程の途中）",
    "irr70dual": "**買付圏の irr=70** を、別の読み手が独立に検証したかを数える。70は刻み別で唯一ラベルが揺れ（一致率0.706）、しかも70→50は投下可を10社→5社にする＝最も揺れる刻みが最も費用を持つ",
    "newlist": "上場して最初の年次報告が出た会社を掃いて、堀の機構を示す言い回しがあるか探す作業リスト。刻みを決めるのは原本を読む人",
    "cagrt": "売上の伸びが加速しているか減速しているかを測る。**これは採点に効く欄**で、空欄だと減速の罰が発火しないので、止まると新しく審査した社ほど甘くなる",
    "fetch": "審査の前に、原本から機械で読める数字（売上・利益・負債など）を下ごしらえする。止まると新規銘柄の審査が在庫切れで止まる（在庫の残り日数はこのカードに出る）",
    "reaudit": "各検出器が見つけたものを『次に審査すべき順』に並べる。止まると検出と作業がつながらず、見つけても誰にも渡らない",
    "notify": "行動が要ることだけをGitHubのIssueにする。画面は開いた人にしか届かないので、その代わり",
    "sht": "同業と比べて売上シェアが伸びているか縮んでいるかを測る。粗利率の低下と組で『堀が崩れ始めた』先行警報になる",
    "stalebs": "決算の期末より後に貸借対照表が大きく動いていないか（買収でのれんが跳ねた等）を四半期報告で見る。買付を止める関門の入力",
    "pending": "合意済みだがまだ閉じていない買収などを見る。完了するとのれんの3割超が入れ替わる規模なら買付を止める（採点しているのが『これからの会社』ではなくなるため）",
    "cihealth": "workflow が『走って失敗した』かを見る。回転盤の他の項は成果物の日付しか見ないので、走って失敗した日を「止まっている」としか言えない——直し方が違う",
    "packstale": "新しい年次報告が出ているのに、審査が古い年のままの社を出す。放っておくと1年前の会社の姿で配分を決めることになる",
    "waccdrift": "割引率の前提（国債利回り）が市場と離れていないかを見る。離れたら人が採点機の欄を更新する（規約の変更ではなく入力の更新）",
    "vfail": "「値は入っているが根拠が書かれていない」欄を持つ社の一覧。買付を止める関門の入力で、席に着く社は0件でなければならない",
    "kanshi": "株価・決算・臨時報告を追う銘柄の名簿を作り直す。止まると、新しく買付に入った社の株価が取れないまま気づかれない",
    "cal": "監視銘柄の次の決算発表日を取って、Googleカレンダーに取り込めるファイルを作る",
    "xwatch": "『あといくら下がれば期待リターンが0になるか』の線を計算し直す。成行で買わずに指値で入るときの目安",
    "kessanUS": "保有・監視銘柄の直近四半期を機械で点検し、売上と利益率の変調・警報語（減損／退任など）を拾う。要審査は再審査の待ち行列へ回る",
    "kessanJP": "同じ点検を日本株の有報PDFで行う。数値は桁が割れて読めないことが多いので警報語だけで裁く。EDINETの無料鍵が要る",
    "v10": "次の世代の採点式を影で並走させ、2027年に新旧どちらが当たっていたか答え合わせするための記録",
    "bfdiff": "機械の採取器を直しても、既に審査済みのデータは自動では直らない。そのズレ（取り残し）を数えて作業リストにする",
    "v11": "v10 と同じく、別の設計の採点式を影で走らせて記録する",
    "calib": "毎年7月に『そのときの判定』を凍結して残す。後から答え合わせできるようにするためで、**時点を逃すと永久に失われる**唯一の作業",
    "gate0": "全上場企業から審査候補を絞る年1回の一次ふるい。1.4GBの財務データが要るのでCIでは回せない",
    "gate0jp": "同じ一次ふるいを日本株で行う。母集団そのものの更新にはEDINETの鍵が要る（鍵なしでできるのは順位の付け直しまで）",
    "state": "株数・売却記録・目標ウェイトなど、ブラウザにしかない『人が決めたこと』をrepoへ書き出す。門はブラウザからrepoへ書けないので人の手が要り、**忘れると消えたとき戻らない**",
    "mwforward": "登録した後の月（2026-10〜）でしか答え合わせできない8本の仮説（ETF側の配合・城×2・米国外の割安＋勢い・新興国の多因子・米国の質・SEC版の質・新興国の紙）を、終わった月ごとに e過程（いつ見ても有効な検定）で更新する。判定には使わない。止まると、値を取れない月が3か月で『欠測』として固定され、20年の検定に戻せない穴が空く（待ちが2か月に達した月・欠測を固定した月・最後の実行の失敗があれば⚠にする）",
    "nxforward": "楽天で持てる規則（業種ETFの勢い・ブランド上位10社・国内株式の能動の投信の上位1/4）とその副・参考の8本を、終わった月ごとに e過程で更新する。10月は投信の選び直しで約30分かかる。判定には使わない。止まると、値を取れない月が3か月で『欠測』として固定される（待ちが2か月に達した月・欠測を固定した月・最後の実行の記録の『失敗』・実行そのものの失敗や時間切れがあれば⚠にする）",
    "mwformsec": "前向きの検定の SEC 版（H7）の組入れを毎年7月に作り直す。1.4GB の一括ファイルが要るので CI では回せない人の作業。遅れると、その年の11月2日の ops の実行で7月が『欠測』として固定され、以後1か月ずつ失われる（固定した欠測は戻せない）",
    "backtest": "『当時読めた数字だけ』で過去に遡って採点し、その後の実際のリターンと突き合わせる。成長の減衰など、予実台帳の答えを先取りするための材料",
}


def build():
    today = date.today()
    # auto: True=CIが全自動 / "key"=鍵をSecretsに置けば自動(無ければ手動) / False=人の作業
    items = [
        ("market",  "株価データ",          "毎営業日", 4,
         json_field("out/dashboard.json", "asof") or git_date("out/dashboard.json"),
         "market.yml 21:30UTC（FINNHUB_KEY）", True),
        ("events",  "8-K・臨報監視",           "毎営業日", 4,
         json_field("out/events_watch.json", "asof"),
         "events.yml 22:10UTC（米国は鍵不要・日本株はEDINET_API_KEY）", True),
        # v9.9.140: 📋今日 の集計。**止まると画面が「今日やることはありません」と言い続ける**
        #   ——この画面はいちばん人が信じるところなので、止まったことが判る必要がある。
        # v9.9.140: 門(ブラウザ)と端末(score_all.js)の一致。**v9.9.65の掟を機械で測る唯一の道具**
        #   ——止まると「同じ台帳を見る二つが違うことを言う」を誰も見張っていない状態に戻る。
        ("parity",  "門と端末の一致",          "毎営業日", 4,
         json_field("out/gate_parity.json", "generated"),
         "ci.yml 平日22:00UTC（実ブラウザ）／手動 node night/check_gate_parity.js", True),
        ("today",   "📋今日の集計",            "毎営業日", 4,
         json_field("out/today.json", "generated"),
         "ci.yml 平日22:00UTC／手動 python3 night/today.py --json", True),
        # 2026-08-18新設: **この盤自身のいちばん大きな死角**。
        #   ここ(ops_status)は成果物の日付しか見ないので、workflow が**走って失敗した**ことを知らない。
        #   実測: market.yml は 8/14・8/17 に走り、採取もパック反映も全部成功してコミットまで作ったのに
        #   `git push` が `! [rejected] main -> main` で弾かれ、70ファイル分が runner ごと捨てられた。
        #   盤の表示は「止まっている疑い」——**『動いていない』と『動いて失敗している』は直し方が違う**。
        #   ⚠ 鍵が要る（Actions API は公開リポジトリでも未認証は403）。CIでは GITHUB_TOKEN が自動で入る
        ("cihealth", "自動化の健康診断",        "毎営業日", 4,
         json_field("out/ci_health.json", "generated"),
         "ci.yml 平日22:00UTC（actions:read）／手動 GH_TOKEN=... python3 night/ci_health.py --write", "key"),
        # 2026-08-17新設: **この盤自身の死角を見張る器**。
        #   ここ（ops_status）は錨の**日付しか見ていない**が、日付と中身は独立に壊れる——
        #     A 日付が凍る（中身は動く）＝**偽陽性**。実際に audit_irr85_dual で5日間鳴りっぱなしだった
        #     B 日付は動くが中身が凍る    ＝**偽陰性**
        #     C 中身も動くが入力が死ぬ    ＝**偽陰性**。実測 sp500_pe_monthly(2026-03停止)→hist_val_now(08-09)
        #   A は check_frozen_dates（CIで落とす）、**B と C は check_freshness** が測る。
        #   偽陰性は盤が緑なので誰も探しに行かない＝**この器が止まると死角が死角のまま戻る**。
        #   ⚠ 作業リストなのでCIでは落とさない（鳴りすぎる警報は鳴らないのと同じ）。
        #     落とさない以上、止まったことを見るのはここしかない。
        ("freshness", "中身と入力の鮮度",       "毎営業日", 4,
         json_field("out/freshness.json", "generated"),
         "ci.yml 平日22:00UTC／手動 python3 night/check_freshness.py --json", True),
        ("er",      "E[r]予実の観測封印",      "月1",     40,
         er_last_obs(),
         "market.yml（月初・snapは月次idempotent）", True),
        ("divy",    "配当分離(divY)",          "月1",     40,
         json_field("out/divy.json", "asof"),
         "ops.yml 毎月2日／手動 python3 night/fill_divy.py", True),
        # v9.9.118(2026-08-09): 自己相対バリュエーション（🛒買付順位の表示専用・合否には不使用）。
        #   **表示だけの作業でも盤に載せる**——止まると門は「未取得」ではなく
        #   **古い分位を今日の分位として出し続ける**（JSONが残るので画面は何も言わない）。
        #   黙って劣化する種類なので、回転の側で見張る。
        # ★v9.9.143(2026-08-14・ユーザー指示「1.2.3すべてやりたい」)
        #   ②門が自分の過去の判定を持つ。**止まると履歴に穴が空き、後から埋められない**
        #   （git の score_all.json は CI と作業ブランチが交互に入って一本の系列にならない）。
        ("gatehist", "門の判定の履歴",            "毎営業日", 4,
         json_field("out/gate_state.json", "day"),
         "market.yml が毎日／手動 python3 night/gate_history.py --append", True),
        #   ①irr の被覆。**判定には使わない**が、13年の検証を生き延びた唯一の指標が
        #   母集団の12.3%にしか付いていない、という数字を見えるところに置き続ける。
        ("irrcov", "irr の被覆と未審査の穴",       "月1",     40,
         json_field("out/irr_coverage.json", "generated"),
         "ci.yml 月次／手動 python3 night/audit_irr_coverage.py", True),
        ("histval", "自己相対バリュエーション",  "月1",     40,
         json_field("out/hist_val_now.json", "asof"),
         "ops.yml 毎月2日／手動 python3 night/hist_valuation.py --asof 〈今日の日付〉 "
         "--tickers kanshi_list.json --out out/hist_val_now.json", True),
        # v9.9.160(2026-08-20): 網(ETF)の材料。**🛒買付順位の◈網の節がこれを読む**——
        #   網の門(ami.html)のキル（設定3年／純資産／経費率）と実効銘柄数を出す。
        #   止まると **NASA が3年を越えても⛔のまま**／経費率や純資産が古いまま画面に出続ける。
        #   価格(dashboard)と同じ「CIで計算してJSONで配り、門は描くだけ」の配管なので、
        #   配る側が止まったことを盤が言えないと、門は古い材料を今日の材料として出す。
        ("netplan", "網(ETF)の材料",            "月1",     40,
         json_field("out/net_plan.json", "asof"),
         "ops.yml 毎月2日／手動 python3 night/net_plan.py", True),
        # v9.9.154(2026-08-17): トータルリターン（盤の📈節・表示専用）。
        #   価格が毎営業日動くので market.yml に置いてある＝毎営業日の錨。
        ("returns", "トータルリターン",        "毎営業日", 4,
         json_field("out/returns.json", "generated"),
         "market.yml 平日21:30UTC／手動 python3 night/fetch_returns.py", True),
        # v9.9.156(2026-08-18): 📈成績タブの推移。**同じ道具が同時に書く**が別に数える——
        #   買付日が判る行が消えると推移だけ作れなくなり、returns.json は更新され続けるので
        #   「グラフだけ静かに古くなる」形になる。別の錨にすればそれが赤くなる。
        ("returnseries", "成績の推移(グラフ)", "毎営業日", 4,
         json_field("out/returns_series.json", "generated"),
         "market.yml 平日21:30UTC／手動 python3 night/fetch_returns.py", True),
        # v9.9.125(2026-08-09): 銘柄ごとの企業説明（📚台帳・🛒買付順位の🏢チップ／表示専用）。
        #   止まっても判定は動かないが、**新しく審査した社の説明が出ないまま気づかれない**ので盤に載せる。
        ("profiles", "企業説明(原本Item1)",   "月1",     40,
         json_field("out/profiles.json", "generated"),
         "ops.yml 毎月2日／手動 python3 night/fetch_profiles.py", True),
        # v9.9.152(2026-08-17): 銘柄アイコンと**行の代表色**（表示専用）。
        #   止まると**新しく審査した社が色もロゴも無いまま気づかれない**（ユーザー報告の症状）。
        #   しかも2026-08-17には、回っているのに**色を236銘柄ぶん消す**という壊れ方をした
        #   ——だから「回ったか」だけでなく色の数も出す（下の logos_colored）。
        ("logos", "銘柄アイコンと代表色",    "月1",     40,
         json_field("out/logos/index.json", "generated"),
         "ops.yml 毎月2日／手動 python3 night/fetch_logos.py && python3 night/logo_colors.py", True),
        # 2026-08-09: 門外例外（特別枠）の四半期監視。**止まると甘い側へ壊れる**——
        #   例外は「門が止めているものを承知で越える」判断で、パックは年次基準なので
        #   止めている当の指標(nde)が年1回しか更新されない。この道具が回らないと
        #   **警報を切ったまま乗る**ことになる。
        ("excwatch", "門外例外の四半期監視",  "四半期",  100,
         json_field("out/exception_watch.json", "asof"),
         "ops.yml 毎月2日／手動 python3 night/watch_exceptions.py", True),
        # v9.9.124(2026-08-09): irr=85 の実績台帳（別枠85・席の優先の特権をどの社に与えるかを決める）。
        #   **止まると穴が開く向きが危ない**——新しく irr=85 になった社は台帳に載らず「中立」扱いで
        #   特権を受ける。実績が悪い社でもそうなるので、載せ直しが止まると**甘い側へ静かに壊れる**。
        ("irr85hist", "irr=85の実績台帳",      "月1",     40,
         json_field("out/irr85_history.json", "generated"),
         "ops.yml 毎月2日／手動 python3 night/irr85_mech_test.py --json", True),
        # 2026-08-11(ユーザー明示指示「irr85の銘柄が出た場合は先ほどまでに使っていた基準で採点してほしい」):
        #   **新しく irr=85 になった社を、ユーザーの基準（営利率11.89 / FCF転換5年0.639 / 成長1.76）で採点する。**
        #   日次の門2審査 Routine がパックを足すので irr=85 の顔ぶれは動く（実測: このセッション中に14→15社）。
        #   止まっても今日の判定は動かない（この道具は読むだけ）が、**新着が誰にも採点されないまま溜まる**
        #   ——「8社」が写真からルールへ変わった意味が消える種類。毎営業日にした理由は、
        #   Routine が毎日走るのに月次で拾うと最大1ヶ月ぶん新着が見えないから。
        # 2026-08-11(ユーザー指示「進めて」): irr=85 を**捌く**ための3本。いずれも読むだけ。
        #   ①機構文の年次diff——**歴史が唯一「効く」と出した変数の劣化を機械が見張る**。
        #     台帳に刻んだ引用が最新の年次報告にまだ在るか。⚠片側の検査（消えたら赤信号／
        #     在っても安全ではない＝CMTL は文を残したまま壊れた）。
        #   ②城の相関——1銘柄の上限8%は守るのに**束では一度も見ていなかった**。
        #     半導体5社・航空防衛4社で城の62.6%なのに、同じ束かの判断材料が業種ラベルだけだった。
        #   ③irr=85 の根拠監査——**回転盤にもCIにも登録が無く2026-08-05の54社のまま6日間止まっていた**
        #     （実データは15社）。KRMN が監視から漏れていたのと同じ形。
        ("irr85mech", "機構文の年次diff",      "毎営業日", 4,
         json_field("out/irr85_mech_diff.json", "generated"),
         "ci.yml（push/PR毎）／手動 python3 night/irr85_mech_diff.py --json", True),
        # ⚠**70 も別の錨として登録する**（2026-09-19）。85 と同じ器だが**別ファイル・別の母集団**で、
        #   片方が止まってももう片方の日付は動く＝一つの錨では止まったことが見えない。
        #   実害: この枠は買付圏だけを見ていたので、**JKHY（堀66.6で⛔＝買付圏の外）の
        #   FY2026 10-K が 22日間 誰にも見られなかった**。
        ("irr70mech", "機構文の年次diff(irr=70)", "毎営業日", 4,
         json_field("out/irr70_mech_diff.json", "generated"),
         "ci.yml（push/PR毎）／手動 python3 night/irr85_mech_diff.py --rung 70 --json", True),
        ("castlecorr", "城の相関（同時に落ちるか）", "月1",  40,
         json_field("out/castle_correlation.json", "generated"),
         "ops.yml 毎月2日／手動 python3 night/castle_correlation.py --json", True),
        # ⚠期限は「月1・40日」ではなく**毎営業日・4日**（2026-08-11 同日中の是正）。
        #   この2本は ops.yml（月次）ではなく **ci.yml（push/PR毎＋平日22:00UTCのschedule）**で回るので、
        #   実際の周期は毎営業日。40日にすると**CIが壊れて止まっても40日間 ✓ が出続ける**——
        #   まさにこの道具が2026-08-05から6日間止まっていたのを誰も検出できなかったのと同じ形を、
        #   期限の側から作り直すことになる。同じ ci.yml で回る irr85myrule（毎営業日・4日）と揃える。
        ("irr85audit", "irr=85の根拠監査",      "毎営業日", 4,
         json_field("out/audit_irr85.json", "generated"),
         "ci.yml（push/PR毎）／手動 python3 night/audit_irr85.py", True),
        # 2026-08-11: 機構の射程と認定の寿命（_meta.mech）。**測定は原本読解＝人の作業**だが、
        #   この表は「まだ測っていない社」を名指しするので回し続ける意味がある
        #   ——新しく irr=85 になった社は未着手のまま静かに溜まる（KRMNが監視から漏れたのと同じ形）。
        ("irr85scope", "機構の射程と認定の寿命",  "月1",     40,
         json_field("out/irr85_scope_life.json", "generated"),
         "ops.yml 毎月2日／手動 python3 night/irr85_scope_life.py --json", True),
        ("irr85myrule", "irr=85をあなたの基準で採点", "毎営業日", 4,
         json_field("out/irr85_myrule.json", "generated"),
         "ci.yml（push/PR毎）／手動 python3 night/irr85_myrule.py --json", True),
        # 2026-08-12(A-1): **irr=85 の二重読み**の有無を数える。
        #   実測で「同じ111社でも班により irr=85 の付与率が 5.4%→17.1%（3.2倍・p=0.017）」と判った。
        #   門は irr=85 に別枠(v9.9.119)と席の優先(v9.9.100)を与えているので、
        #   **「いつ・誰に読まれたか」で買付の資格が動きうる**。
        #   ⚠ 関門ではなく作業リスト（未検証は欠陥ではなく工程の途中）。だが**盤に載せる**——
        #   載せないと「新しく85が付いたのに誰も検証していない」が静かに溜まる（KRMNがまさにその形）。
        ("irr85dual", "irr=85の二重読み",      "毎営業日", 4,
         json_field("out/irr85_dual.json", "generated"),
         "ci.yml（push/PR毎）／手動 python3 night/audit_irr85_dual.py", True),
        # 2026-08-19新設: **買付圏の irr=70**。85と分けて数えるのは、同じ器でも
        #   止まり方が独立だから（--rung 70 の呼び出しだけ落ちても 85 は緑のまま）。
        ("irr70dual", "irr=70の二重読み(買付圏)", "毎営業日", 4,
         json_field("out/irr70_dual.json", "generated"),
         "ci.yml（push/PR毎）／手動 python3 night/audit_irr85_dual.py --rung 70", True),
        # 2026-08-10(ユーザー明示指示「上場後1年後にirr85の銘柄は測定できるようにしたい」):
        #   **新規上場社を母集団へ入れ続ける**。上場初年度は10-Kが無いので網に掛からず、
        #   翌年に初めての10-Kが出ても**掃除が一回きりだと誰も見ていない**。
        #   2026-08-08のスイープはまさにこの形で、しかも読解リストを「パックが無い社」に
        #   絞っていたため **KRMN（irr=70・根拠が空）が読解対象から外れていた**。
        #   止まっても今日の判定は動かないが、**測る対象が入ってこなくなる**＝
        #   歴史が「唯一効く」と出した変数の被覆が静かに痩せる種類。
        ("newlist", "新規上場のirr機構語",   "月1",     40,
         json_field("out/new_listings_irr.json", "generated"),
         "ops.yml 毎月2日／手動 python3 night/watch_new_listings.py", True),
        # 2026-08-10: **採点入力の再測定2本**。どちらも --write を付けず測るだけ（ルール2）だが、
        #   止まると**新しく審査した社ほど甘くなる**種類なので盤で見張る。
        #   cagrT: compute() が使う欄で、空欄は CCF_BLANK の 'best'＝罰が発火しない
        #   sht  : 空欄は SELECT既定の 'flat' に化け、**Intel警報（gmt=down ∧ sht=down）**を含む
        #          5規則がまるごと不発になる。実測で369社中322社が空欄だった
        ("cagrt",   "成長の軌道cagrTの測定", "月1",     40,
         json_field("out/growth_trend.json", "generated"),
         "ops.yml 毎月2日／手動 python3 night/fill_growth_trend.py（反映は --write＝審査官の手）", True),
        # 2026-08-17新設: **機械値の下ごしらえ（採取）**。ops.yml が月1で回しているのに
        #   **盤に無かった**——出力が out/{T}_gate_input.json という**銘柄ごとのファイル**で、
        #   盤が見る単一の錨が存在しなかったため。止まっても誰も気づけない典型の穴。
        #   ⚠ここが止まると門2審査は**在庫が尽きるまで気づかない**（実測の在庫58社＝約12日）。
        #   在庫の数は out/fetch_run.json の stock_unreviewed に入る（📋今日が読む）。
        ("fetch",   "機械値の採取(門1)",     "月1",     40,
         json_field("out/fetch_run.json", "generated"),
         "ops.yml 毎月2日（未審査の先頭5社）／手動 python hachimon_fetch.py [T ...]", True),
        # 2026-08-10: **検出器の出力を作業へ流す接続**。止まると「検出は自動・作業は手動」の
        #   断絶が戻る——新しい10-Kが出ても納品検査がFAILしても、待ち行列に何も入らなくなる。
        ("reaudit", "再審査の待ち行列",      "月1",     40,
         json_field("night/reaudit_queue.json", "generated"),
         "ci.yml（push毎）＋ops.yml 毎月2日／手動 python3 night/enqueue_reaudit.py --json "
         "&& python3 night/make_chunks.py --reaudit --top 20", True),
        # 2026-08-10: **自動化そのものを見張る3本**。
        #   通知・機械是正・門2審査が止まっても、今日の判定は動かないので**気づけない**——
        #   だからこそ盤に載せる（「回っているつもりで止まっている」を作らない）。
        ("notify",  "通知(Issue化)",         "毎営業日", 4,
         json_field("out/events_watch.json", "asof"),
         "events.yml（行動が要ることだけIssueにする・冪等）", True),
        # 2026-09-23: fix.yml（機械是正の自動提案）を削除した（ユーザー「消して」）。実行2回・PRは repo 設定で作れず、
        #   機械項目の埋め直しは四半期の見直しでセッションから回す。戻すなら git 履歴から。
        # 2026-08-17: **`review.yml` を畳んだので、この行も降ろす**（ユーザー指示「3つともやって」）。
        #   経緯は消さない——review.yml は **走行回数 0** のまま9日前が最終で、盤の「鍵待ち」は
        #   この1件だけだった。同じ仕事を Routine『【門】日次 門2審査（自動・5社）』が毎日していて
        #   （盤の `reviewrun` は🟢）、CLAUDE.md 自身が
        #   「$を払って未実証の経路を開くより、$を払わず実証済みの経路を毎日に伸ばす」と記録している。
        #   ＝**直すのではなく降ろすのが筋**。降ろせば「鍵待ち」という常設の黄色が消え、
        #   盤が本当に全緑になる（鳴りっぱなしを一つ減らす）。
        #   ⚠ その Routine も 2026-09-23 に止めた（ユーザー指示「両方止めて」）——審査は必要なときにセッションで頼む。
        #   ⚠ 復活させたいときは git 履歴に review.yml が残っている（ANTHROPIC_API_KEY が要る）。
        ("sht",     "シェア趨勢shtの測定",   "月1",     40,
         json_field("out/sht_report.json", "asof"),
         "ops.yml 毎月2日／手動 python3 night/build_sic_cache.py && python3 night/fill_sht.py --json"
         "（反映は --write＝審査官の手）", True),
        # v9.9.94(2026-08-06): 期末後の重大事象の検査。**回っているかを盤で見張る**——
        #   この検査が黙って止まると「パックが会社の現在を描いていない」銘柄が
        #   何食わぬ顔で投下可に戻る（APHがまさにその状態で資産の6.3%を受けていた）。
        ("stalebs", "期末後の重大事象の検査",  "毎営業日", 4,
         json_field("out/stale_bs.json", "asof"),
         "ci.yml（push/PR毎）／手動 python3 night/audit_stale_bs.py --write", True),
        # v9.9.128(2026-08-10): 合意済み・**未完了**の重大事象。stale_bs の**時間的な穴**を塞ぐ検査で、
        #   これが止まると「合意/判決からクローズまでの数ヶ月〜1年超」がまた無防備になる。
        #   ⚠ この欄は審査官が _meta.pending に書くので、**盤が緑でも書き漏らしは検出できない**
        #   ——見落としの網は watch_events の pending_todo（8-K Item 1.01/1.02/8.01）が受け持つ。
        ("pending", "未完了の重大事象の検査",  "毎営業日", 4,
         json_field("out/pending.json", "asof"),
         "ci.yml（push/PR毎）／手動 python3 night/audit_pending.py --all --write", True),
        # 2026-08-07新設: パックより新しい年次報告が出ていないか。**既存の検査が全部すり抜ける穴**——
        #   validate_packs の鮮度は「年」の差(3年でFAIL)、audit_stale_bs は のれんの入替のみ
        #   ＝買収しない優良企業が静かに1会計年度ぶん古くなるのは誰も見ていなかった。
        #   実測(初回): MSFT・KLAC（ともに投下可）を含む5社が1年遅れ。
        ("packstale", "パックの会計年度の遅れ",  "毎営業日", 4,
         json_field("out/pack_stale.json", "asof"),
         "ci.yml（push/PR毎）／手動 python3 night/audit_pack_stale.py --write", True),
        # 2026-08-07新設: WACCの既定値(無リスク金利)のズレ。**これは検出器であって適用器ではない**
        #   ——rfrの更新はユーザーの月次ルーチン（買うリズムと選ぶリズムを分ける設計）に属する。
        #   自動化するのは適用ではなく検出。todo_listが自ら「忘れても盤が検出できない種類」と
        #   書いていた項目に、初めて検出器が付いた。
        ("waccdrift", "WACC既定のズレ検出",     "月1",     40,
         json_field("out/wacc_drift.json", "asof"),
         "ops.yml 毎月2日／手動 python3 night/audit_wacc_stale.py --write", True),
        # v9.9.95(2026-08-07): 納品検査のFAIL。**関門がこのJSONを読む以上、
        #   JSONの鮮度が関門の鮮度そのもの**——止まると古いFAIL表で買付を裁くことになる。
        ("vfail",   "納品検査FAIL表",          "毎営業日", 4,
         json_field("out/validate_fail.json", "asof"),
         "ci.yml（push/PR毎）／手動 python3 night/validate_packs.py --json", True),
        ("kanshi",  "監視リスト生成",          "月1",     40,
         git_date("kanshi_list.json"),
         "ops.yml／手動 python3 make_kanshi.py", True),
        ("cal",     "決算カレンダー",          "月1",     40,
         json_field("out/next_earnings.json", "generated"),
         "ops.yml／手動 python kessan_calendar.py", True),
        ("xwatch",  "X監視表(開通ライン)",     "月1",     40,
         git_date("gate1_x_watch.json"),
         "ops.yml／手動 python x_watch_recalc.py", True),
        ("kessanUS","決算点検（米国）",        "四半期",  100,
         kessan_last("_qcheck.txt"),
         "ops.yml（月次で先回り）／手動 python kessan_check.py", True),
        ("kessanJP","決算点検（日本株）",      "四半期",  100,
         kessan_last("_qcheck_jp.txt"),
         "ops.yml（EDINET_API_KEYをSecretsに置けば自動）／手動 python3 kessan_check_jp.py", "key"),
        ("v10",     "v10影スコア更新",         "年1(7月)", 430,
         json_field("out/v10_shadow.json", "generated") or git_date("out/v10_shadow.json"),
         "ops.yml（7月）／手動 python3 v10_series.py"
         "　⚠**実行は out/v10_shadow.json を上書きする**——2027-07の答え合わせの材料は"
         "calibration.json の凍結キー（v10_scores_2026／snapshots.2026）から採ること", True),
        # v11「引き算の門」の影（2026-08-12新設）。**v10 の轍を踏まないために回転盤へ載せる**
        #   ——v10 は年1(7月)なので、止まっても**最大430日は誰も気づかない**。実際 2026-08-12 に
        #   「道具が repo に無い」と誤診されたときも、それを覆す測定は4日間 誰も撃たなかった
        #   （★2026-08-16 訂正: 道具は 2026-08-09 から在り、動く）。
        #   v11 は判定に一切使わないが、**月1にして止まったことが見えるようにしておく**。
        # 採取器の是正がパックに届いているかの実測（2026-08-13新設）。
        #   **止まると「取り残し」が静かに溜まる**——nde の12社はこの経路で8ヶ月見えなかった。
        ("bfdiff",  "採取器とパックの食い違い",  "月1",     40,
         json_field("out/backfill_diff.json", "generated") or git_date("out/backfill_diff.json"),
         "ops.yml 毎月2日／手動 python3 night/backfill_machine_evidence.py --json"
         "（**読むだけ**。--sync は単位ずれ・年ずれを注入するので自動では走らせない）", True),
        ("v11",     "v11影スコア更新",         "月1",     40,
         json_field("out/v11_shadow.json", "generated") or git_date("out/v11_shadow.json"),
         "ops.yml 毎月2日／手動 python3 night/v11_facts.py && node night/v11_gate.js"
         "（V11_SPEC.md・正本の判定には一切使わない）", True),
        # 2026-08-10: **auto=False → True**。人の判断が要るのは *v9 vs v10 の勝敗判定* であって
        #   スナップショットの生成ではない（鍵もネットも companyfacts も不要）。もう半分の
        #   v10_series.py は既に7月だけ自動で、**片方だけ手動という非対称**が残っていた。
        #   しかもこれは**時点を逃すと永久に失われる**唯一の項目——一度失敗している
        #   （calibration.json に v9 の Ω合成値が無く 2027-07 の答え合わせが成立しなくなった）。
        ("calib",   "年次較正の封印(7月)",      "年1(7月)", 430,
         git_date("out/calibration.json"),
         "ops.yml（7月）／手動 python calibration_check.py"
         "——**封印は自動・v9/v10の勝敗判定はユーザーの判断**（V10_SPEC）", True),
        # 2026-08-10: 錨を **git のコミット日 → 実行印(out/gate0_run.json)** へ。
        #   実測では gate1_queue.json の直近コミットが門0と無関係の作業（予実台帳の基準印）で、
        #   それでも盤は「期限内」と出していた。**年次作業ほど測り方が弱い**という倒錯を直す。
        ("gate0",   "米国門0発掘",             "年1(1-2月)", 430,
         json_field("out/gate0_run.json", "generated") or git_date("gate1_queue.json"),
         "python run_gate0_local.py（companyfacts.zip 1.4GB＝CI外）", False),
        # 2026-08-10: rebuild_gate0_jp が **generated を "2026-08-03" にハードコード**していたため、
        #   再実行しても去年の日付を名乗り**盤が永久に緑で固定**されていた（実行日を書くよう直した）。
        #   ⚠auto は False のまま——**母集団の更新には EDINET鍵が要る**（run_gate0_jp_local.py）。
        #     rebuild_gate0_jp は凍結スナップショットの**再ランク**であって母集団の再取得ではない。
        ("gate0jp", "日本株門0",               "年1",     430,
         json_field("gate0_jp_queue.json", "generated") or git_date("gate0_jp_queue.json"),
         "python3 night/rebuild_gate0_jp.py --write（**再ランクのみ**。母集団の更新は "
         "run_gate0_jp_local.py＝EDINET_API_KEY が要る）", "key"),
        # 2026-08-10: 錨に **生成印(generated)** を優先させた（git コミット日は最後の手段）。
        #   あわせて auto=**True**——実測では companyfacts.zip を使っておらず
        #   （`grep zipfile night/backtest_core.py` は0件・per-CIK APIと独自キャッシュ）、
        #   「資源制約で自動化できない」は**一度も試していない**の言い換えだった。
        # v9.9.131: **人の決定(state.json)の鮮度**。株数・目標ウェイト・売却記録・検証履歴・
        #   点灯日・個別枠は 2026-08-10 まで localStorage が正本で repo にコピーが無く、
        #   **消えたら復元手段がゼロ**だった。repo へ移したが、門はブラウザから repo へ書けないので
        #   「人が書き出してコミットする」経路になる＝**書き出し忘れが唯一の穴**。
        #   だから盤で測る——auto は False（人の手が要る作業だと明示する）。
        #   savedAt が null（未初期化）なら日付が取れず state=unknown ＝「健全と読まない」側に落ちる。
        ("state",   "人の決定の書き出し(state.json)", "月次", 40,
         (json_field("state.json", "savedAt") or "")[:10] or None,
         "門の🏦保有「📤 state.json」→ repo直下へ置いてコミット（検査 python3 night/validate_state.py）", False),
        # 2026-09-29: **前向きの検定**（事前登録どおり毎月・判定に不使用。mw は eknzbh の 19e8ce23、nx は b8579d18 で登録）。
        #   錨は出力の generated（道具が毎回その日に書く）。⚠ generated は月を1つも取れない実行でも動くので、
        #   『走るが月を取れない』は上の FORWARD_WATCH の見張りが別に見る。
        #   ⚠ 書き手は ops.yml だけ——手元で回した出力をコミットすると、固定した月が割れる。
        ("mwforward", "前向きの検定（mw・8本）", "月1", 40,
         json_field("out/mw_forward.json", "generated"),
         "ops.yml の forward ジョブ（毎月2日 23:17 UTC・落ちたら3日に予備・凍結の検査 check_forward_frozen が通ったときだけ・"
         "結果は他の成果と別のコミットで先に push）／手動 python3 night/mw_forward.py update"
         "（手元の出力はコミットしない＝書き手は CI だけ）", True),
        ("nxforward", "前向きの検定（nx・8本）", "月1", 40,
         json_field("out/nx_forward.json", "generated"),
         "ops.yml の forward ジョブ（毎月2日 23:17 UTC・落ちたら3日に予備・凍結の検査が通ったときだけ・10月は投信の選び直しで"
         "約30分）／手動 python3 night/nx_forward.py --update（手元の出力はコミットしない）", True),
        # 年1の手作業: SEC 版（H7）の組入れ。**期限はその年の11月2日の ops より前**——その回で7月が
        #   『経過4か月＞3』として欠測に固定され、以後1か月ずつ失われる（戻せない）。錨は最新の組入れの年の
        #   7月1日なので、期限410日で翌年の8月16日から ⚠（欠測の固定まで約2.5か月の余裕）。
        ("mwformsec", "前向きの検定 SEC版の組み直し", "年1(7-10月)", 410,
         mw_formation_anchor(),
         "手動（CI外・その年の11月2日の ops より前に）: 7月以降に out/_mw_cache/ へ sec_companyfacts.zip"
         "（SEC の一括 companyfacts.zip・repo 直下の門0用とは別のパス）と sec_company_tickers.json"
         "（https://www.sec.gov/files/company_tickers.json・道具は自分で取らない）を置き直す → "
         "python3 night/mw_forward.py form_sec 〈年〉 → out/mw_forward_sec_formation_〈年〉.json をコミット"
         "（一度だけ。回し直すと、取り込んだ後の月の持ち物が後のデータで変わる）", False),
        ("backtest","疑似バックテスト",        "年1",     430,
         max((json_field(os.path.relpath(f, BASE), "generated")
              or git_date(os.path.relpath(f, BASE)) or "" for f in
              glob.glob(os.path.join(BASE, "out", "backtest_*.json"))), default=None) or None,
         "gate0.yml（年1・7月）／手動 python3 night/backtest_core.py", True),
    ]
    rows = []
    for id_, name, cad, due, last, how, auto in items:
        days = None
        if last:
            try:
                y, m, d = map(int, last[:10].split("-"))
                days = max(0, (today - date(y, m, d)).days)  # コミットTZ(+0900)でUTC日付を跨ぐと負になるため0で床
            except Exception:
                days = None
        state = "unknown" if days is None else ("due" if days > due else "ok")
        # 2026-08-10: **鍵待ち(auto=="key")の作業を「停止疑い」と同じ赤にしない。**
        #   鍵が無いのは*止まった*のではなく*まだ始めていない*——両方を同じ色にすると
        #   盤が常時⚠になり、**本当に止まった作業がその中に埋もれる**
        #   （鳴りすぎる警報は鳴らないのと同じ）。別の状態として出す。
        #   ⚠**健全と読ませない**ためにラベルは残す＝「穴を明示する」の作法。
        if state == "due" and auto == "key":
            state = "nokey"
        # 2026-09-29: 前向きの検定は日付が期限内でも、固定される前の欠測の芽（上の FORWARD_WATCH）で ⚠ にする。
        #   理由は `how` の先頭に書く——⚙自動化タブのカード・📋今日・Issue（notify_issues）がどれも `how` を出すので、
        #   門や他の道具を変えずに「なぜ⚠か」と「何をすればよいか」が届く。
        watch = forward_watch(*FORWARD_WATCH[id_]) if id_ in FORWARD_WATCH else None
        if watch:
            if state == "ok":
                state = "due"
            how = ("⚠ 見張り: " + "／".join(watch[:3]) + (f" ほか{len(watch) - 3}件" if len(watch) > 3 else "")
                   + " → 取れない理由を確かめる（配信元の遅れなら次の2日の定期実行が取り直す）。"
                   + FORWARD_RERUN_HINT.get(id_, "")
                   + "3か月を超えた月は欠測として固定され戻せない｜" + how)
        row = {"id": id_, "name": name, "cadence": cad, "due_days": due,
               "last": last, "days": days, "state": state, "how": how, "auto": auto,
               # 2026-08-17(ユーザー指示「説明がないせいでなにがなにをしているのか分からない」):
               #   カードは `how`（回し方＝コマンド）しか出しておらず、**何をしているか**が無かった。
               #   WHAT に「何をする／止まると何が起きる」を持たせ、門は出すだけにする。
               #   ⚠ 説明が無い項は **null** にして門が「説明がまだ書かれていない」と出す
               #     ——空文字で埋めると「説明が無い」と「説明が空」が区別できなくなる（ルール7）。
               "what": WHAT.get(id_)}
        if watch is not None:
            row["watch"] = watch
        rows.append(row)
    # 人のやるべきこと（宿題・決断待ち・機械で測れない定期ルーチン）は todo_list.json が正本。
    # 盤と同じJSONに同梱して門が1回のfetchで両方読めるようにする（v9.9.83）
    todos = None
    try:
        todos = json.load(open(os.path.join(BASE, "todo_list.json"), encoding="utf-8"))
    except Exception:
        pass
    return {"asof": today.isoformat(), "items": rows, "todos": todos,
            "note": "state=due は「期限日数を超えて止まっている」の機械判定。"
                    "unknown は日付が取れない＝健全と読まないこと。"
                    "**nokey は鍵待ち**（止まったのではなく、まだ始めていない）——"
                    "健全ではないが『止まった』とも違うので別の色で出す"}


def main():
    out = build()
    p = os.path.join(BASE, "out", "ops_status.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n_due = sum(1 for r in out["items"] if r["state"] == "due")
    n_unk = sum(1 for r in out["items"] if r["state"] == "unknown")
    n_key = sum(1 for r in out["items"] if r["state"] == "nokey")
    print(f"運用サイクル {len(out['items'])}本: 期限内 {len(out['items'])-n_due-n_unk-n_key}"
          f" / 停止疑い {n_due} / 鍵待ち {n_key} / 不明 {n_unk}")
    # 2026-08-17: **説明の無い作業を黙って通さない。** 盤に項を足すのは1行だが、
    #   WHAT を書き忘れると門のカードが「説明がまだ書かれていない」のまま出る——
    #   check_mobile_fit のタブ一覧と同じ「足し忘れが静かに残る」型なので、ここでも数える。
    #   ⚠ 落としはしない（説明の欠落で運用の盤を赤くすると、本当の停止がその中に埋もれる）。
    no_what = [r["id"] for r in out["items"] if not r.get("what")]
    if no_what:
        print(f"  ⚠ 説明(WHAT)が無い作業 {len(no_what)}本: {' '.join(no_what)}"
              f"  → night/ops_status.py の WHAT に「何をする／止まると何が起きる」を書くこと")
    for r in out["items"]:
        mark = {"ok": "🟢", "due": "⚠", "unknown": "？", "nokey": "🔑"}[r["state"]]
        ago = "" if r["days"] is None else f"（{r['days']}日前・期限{r['due_days']}日）"
        print(f"  {mark} {r['name']:<14}（{r['cadence']}）最終 {r['last'] or '不明'}{ago}")
        for w in r.get("watch") or []:
            print(f"      ⚠ 見張り: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
