# HANDOFF — CCF Ω 壊れない複利の門

作成: 2026-09-18 / 目的: GitLab移設後の遡及検証を GitHub へ反映するための引き継ぎ

---

## 0. 最初に読むこと — 系譜が3つに割れている

**「GitHubが止まっていて GitLab が進んでいる」という単純な話ではない。** 実測した現状は3系統:

| 系統 | 最終更新 | 中身 |
|---|---|---|
| **GitHub `main`** (`33448e4`) | 2026-08-24 | ここで停止。以降1コミットも入っていない |
| **GitHub `claude/gate-site-7xxoql`** | **2026-09-18（今日）** | main より **19コミット先行**。ETFの歴史検証・v9.9.171→174・並走ブランチ第五/第六回の取り込み。`claude/cowork-history-verification-t3jdzv`（18コミット）を**包含する上位集合** |
| **GitLab `yu-group5324737/ccfgate2` `main`** (`e0fce2cd`) | 2026-09-17 | 門の**遡及検証（規約v1/v2 の out-of-sample）**・`night/` 189本増・`.gitlab-ci.yml` |

**つまり GitHub への push は今も動いている**（ブランチに今日の日付のコミットがある）。止まっているのは `main` へのマージだけ。2026-08-24 に記録された403（`remote: Claude doesn't have GitHub access to touchme1956/ccf-gate for your organization`）は、少なくとも今は解消しているように見える。

### ⚠ 最重要: 同じ変更が両側で二重に実装され、版番号が食い違っている

| | GitHub `gate-site-7xxoql` | GitLab `main` |
|---|---|---|
| 席 10→5・城50→30・網50→70 | **v9.9.171**（`3dd5499`・09-18） | **v9.9.174**（`7c22008a`・09-17） |
| 門外例外を按分から降ろす | v9.9.171 に同梱（5社） | v9.9.175（`adb6bc4e`・6社） |

**意味的に同じ変更が、別の版番号で、別のリポジトリに、独立に入っている。** 何も考えずにマージすると版番号が壊れる。GitHub側は `adb9f1c` で「v9.9.171→v9.9.174 へ繰り下げ」を既にやっているので、**GitHub側の繰り下げ後の番号（174）が GitLab と一致する** — ここは偶然そろっている。門外例外の社数が **5社 vs 6社** で食い違う点だけは、マージ時に必ず突き合わせること。

---

## 1. 反映の順序（この順でやる）

系譜が3つある以上、順序を間違えると解決済みの作業を捨てる。過去に `git stash pop` で解決を落とした事故があるので、機械的なマージはしない。

### Step 1 — GitHub 内部を先に片付ける

GitLab を持ち込む前に、GitHub 側の先行ブランチを `main` に落とす。

```bash
cd /path/to/ccf-gate
git fetch origin
git log --oneline origin/claude/gate-site-7xxoql ^origin/main   # 19件のはず
git checkout main
git merge --ff-only origin/claude/gate-site-7xxoql   # ff可能なら一発
git push origin main
```

`--ff-only` が通らない場合は分岐しているので、`git log --oneline origin/main ^origin/claude/gate-site-7xxoql` で main 側にだけある commit を確認してから判断する。

**残る並走ブランチ**（`main` に未収載のもの、2026-09-18時点の実測）:

| ブランチ | main より先行 | 最終 |
|---|---|---|
| `claude/gate-site-7xxoql` | 19 | 2026-09-18 |
| `claude/cowork-history-verification-t3jdzv` | 18 | 2026-09-18（gate-site が包含） |
| `claude/future-stock-return-gate-lzm5li` | 43 | 2026-07-27 |
| `claude/portfolio-holdings-simplify-bm8xvk` | 20 | 2026-08-04 |
| `claude/gate-site-7xxoql` 以外の09-18系 | — | — |
| `claude/mon-ui-improvement-dm1r51` | 7 | 2026-08-24（gate-site が取込済） |
| `claude/session-2724ac` | 6 | 2026-07-26 |
| `claude/compound-median-15-percent-analysis-qozjps` | 5 | 2026-08-18 |
| `claude/code-review-investment-tools-d5443h` | 3 | — |
| `claude/historical-ticker-validation-6aho7f` | 3 | — |
| `claude/limit-securities-to-10-4rx358` | 3 | （gate-site が取込済） |
| `claude/market-cap-performance-ceiling-rwyt8e` | 2 | （gate-site が取込済） |
| `copilot-ui-improve` | 2 | — |
| `claude/button-ui-design-improvements-v185dd` | 1 | — |
| `claude/cooling-explanation-enmvsk` | 1 | — |
| `claude/narrow-purchases-five-stocks-vutxfl` | 1 | （gate-site が取込済） |

`gate-site-7xxoql` の `70ebc8a`「残る並走9本の triage も」に、どれを捨てるかの判断が既に書かれている。**先にそれを読む。**

### Step 2 — GitLab を GitHub に足す

GitLab `main` は GitHub の `33448e4` を祖先に持つ（最古 `c21f602` から SHA が一致する同一系譜）。ただし Step 1 で GitHub `main` が先へ進むと、**そこで初めて分岐する**。fast-forward ではなくマージになる。

```bash
git remote add gitlab <GitLabのURL>
git fetch gitlab
git merge-base --is-ancestor 33448e4 gitlab/main && echo "同一系譜を確認"

git checkout main
git merge gitlab/main
```

**衝突が出る場所（予測）:**

| ファイル | 理由 | 解き方 |
|---|---|---|
| `index.html` | 両側で v9.9.171〜177 を独立に実装 | **中身で突き合わせる。** 席5・城30/網70 は同じ。門外例外の社数（5 vs 6）を確認 |
| `CLAUDE.md` | 両側で追記。過去の解決は「**上位集合を採る**」 | GitLab側15,032行 / GitHub側12,944行。行数の多い方＝上位集合を採る |
| `gate_exceptions.json` / `gate_exclusions.json` | GitLab側で `gate_exclusions.json` を新設し、`gate_exceptions.json` の items を空にして `retired_2026_09_18` へ退避 | GitLab側の設計を採る（新しい） |
| `out/*.json` | 両側で再生成 | **どちらも古い可能性がある。** マージ後に再生成する（下記 Step 3） |
| `.github/workflows/` vs `.gitlab-ci.yml` | 別ファイルなので衝突しない | 両方残る。ただし Step 3 の注意を読む |

### Step 3 — マージ後に必ずやる

1. **生成物の再生成** — v9.9.171 移植後に重みが変わったのに `out/*.json` が古いまま（CLAUDE.md 14721–14723行）。
   ```bash
   node night/score_all.js
   python3 make_kanshi.py
   python3 night/net_plan.py
   ```
   これを回すまで**台帳の値と門の判定が食い違う**。
2. **CI の二重起動を止める** — GitLab側は `[read-only]` タグで `market` / `score` / `shadow` を skip する設計。**GitHub Actions 側にはその仕組みが無い**ので、`.github/workflows/market.yml` 等が古い前提で無条件に回る。どちらを生かすか決める。
3. **サイトの配信確認** — `gate-site-7xxoql` の `7467165`「CIを止めていたのは `NOW` という名前の固定日1行だった」。同じ地雷が踏まれていないか、`touchme1956.github.io/ccf-gate/index.html` の表示日付で確認する。

### Step 4 — もし403が再発したら

```bash
git bundle create ccfgate-$(date +%Y%m%d).bundle 33448e4..main
```
生成した `.bundle` を人が受け取り、認可のある環境で `git fetch ./ccfgate-*.bundle main:refs/heads/from-gitlab` → `git merge --ff-only` → `push`。過去に102→111→114コミットで3回この手を使っている。

---

## 2. 遡及検証の中身と結論（GitLab側）← 反映したい本体

2013年ビンテージの原本読解による out-of-sample テスト。**規約v1 → 規約v2 の2本立て**で実施し、どちらも棄却された。

### 2-1. 規約v1（2026-09-16〜17）

| 項目 | 値 |
|---|---|
| 母集団 | 一度も読んでいない417社 |
| 標本 | 無作為200社・SEED 20260916・指紋 `8c53232185f856f6` |
| 事前登録 | `out/retro_omega_prereg_v11.json`（標本を引く**前**にコミット: `1fd10a36`） |
| 第0段 | irr一致 18/20 = 0.900、引用の逐語照合 40/40 |
| 撃った内容 | 盲検irrのAUCを `tr_cagr >= 0.15` に当てる。線0.61 / alpha 0.05 |
| **結果** | **n=200・AUC 0.5068・p 0.448・AUC_max 0.7949・tau_b 0.0168** |
| 刻み別当たり率 | 50(177社) 0.192 / 70(16社) 0.250 / 85(2社) 0.500 / **100(5社) 0.000** |
| in-sample比較 | 2013既読249社では AUC 0.6599・p<0.0001 → **効果は約1/10** |
| 判定 | 事前登録v11 第2項が発火 →「**門を予測器として使うことを棄却する**」 |

### 2-2. 規約v2（2026-09-17）

v1の穴だけを8点埋めた改訂版（刻み 100/85/70/50/null は不変）:
① mech に F=転換費用 / G=規制・免許・フランチャイズ を追加 ②「向き」を判定規則化 ③ 射程が全社に及ばないときは一段下げる ④ 矛盾する記述は**弱い方を採る** ⑤ 100にも機構と引用を要求 ⑥ 顧客が複数社を認定済みなら85に採らない ⑦ 50とnullの境目を定義 ⑧ tense を廃止

汚染防止として「v2の変更は1つ残らず、読み手が結末を見る**前**に書いた申し送りに紐づける」を自ら課している（200社中155社の `_why` が規約の穴に触れていた）。

| 項目 | 値 |
|---|---|
| 母集団 | v1の200社と既読640社を除いた**残り全部 217社**（**無作為抽出をしない**＝標本を選ぶ余地を残さない） |
| 標本 | n=215（`BB`・`MGA` は原本が引けず）・指紋 `bf916424262a5f14`・11班・盲検 |
| 事前登録 | `out/retro_omega_prereg_v12.json`（`42586174`）＋ `_v12_amend1.json`（`c6b10d0d`） |
| 第0段 | irr一致 **19/20 = 0.950**、mech一致 19/20、逐語照合 40/40。割れたのは `AES` 1社 |
| 撃った内容 | v1と同一（AUC / `tr_cagr>=0.15` / 線0.61 / alpha 0.05 / NPERM 2000 / PERM_SEED 712 / MIN_N 100）。定数が事前登録とずれたら**撃たずに止まる** fail-closed |
| **結果** | **n=214・AUC 0.460452・p_AUC 1.0・AUC_max 0.689189・tau_b −0.120259・p_tau 0.938** |
| 刻み別当たり率 | 50(200社) **0.185** / 70(11社) **0/11 = 0.000** / 85(3社) **0/3 = 0.000** / 100 **0社**（v2では一度も置かれなかった） |
| 基準率 | 0.1729 |
| mech内訳 | A1 / B7 / C1 / D2 / **E0** / **F6** / **G12**、「なし」186。F・Gが付いた18社のうち**9社は射程・矛盾の条文で50に下げられた** |
| v1近似（F/G→50） | AUC 0.485876 → **新設した機構が予測に寄与した形跡は無い** |
| 判定 | **「越えなかった」**（n=214≥100・AUC_max 0.689≥0.61 なので「測れなかった」ではない） |

### 2-3. 確定結論

出典: `out/retro_pillars_auc_2013_result.json` の `_oos2` ブロック（commit `91be85a6`）

- 合わせた irr≥70: **5/37 = 0.135**（合わせた基準率 76/414 = 0.184）→ **床より上と言われた群が基準率を下回った**
- irr=100: v1標本内 0/4・標本外 0/5・v2では0社 → **0/9**
- 逐語:

> **規約を直しても効かなかった。2013年ビンテージについて、この門を予測器として使うことの棄却が確定した**

**書けないこととして明記されていること**（引き継ぐ側が誤読しないように）:

- 「堀は無い」とは言っていない
- 2015・2018 ビンテージは撃っていない
- 214社中37社は15%を超えている。**超える社は在る。この門がそれを事前に指せないだけ**

**次の方針**（すべて新しい事前登録が要る）:

1. 第0段に「分散の線」を足す
2. 的を上振れから**下振れ（恒久毀損の回避）**へ替え、上場廃止企業を母集団に入れる
3. **⚠ 規約v3 は作らない** —「効くまで規約をいじる」ことになるため

### 2-4. 撃つ前に記録された懸念（`a168f1f0`）

第0段は通ったが、その高い一致は**刻みが50に潰れていること**で説明がつく、と結末を見る前に記録している。甲は50が19社、乙は**20社全部が50**。矛盾ありの判定が甲16/20・乙16/20で**全件で弱い方が採られた**。

> 10-K の Competition 節は定型文として必ず `highly competitive` と書く。したがって「矛盾したら弱い方」はほぼ常に発火する

さらに `amend1` に「**一致だけを見る第0段は、常に50を返す規約でも20/20になる**」という穴を追記している。

### 2-5. 門への反映状況

**遡及検証は門を一切動かしていない。** oos/oos2 の全コミットは `[read-only]` または `[oos*]` タグ付き。`_oos2` ブロックの結論は「棄却が確定した」で止まり、判定・配分の変更は一つも書かれていない。

同日 2026-09-17 の 21:53〜23:17 に門は4回変わったが（v9.9.174〜177）、**いずれも「ユーザー明示指示」が理由で、検証には一言も言及していない**。4本とも「Ω・採点式・刻み・重み・四関門・堀の関門70・売却規律S1/S2/S3・Tierの段・1銘柄上限8% は不変」と明記。

---

## 3. GitHub側にだけある歴史検証（重複して作らないこと）

`claude/cowork-history-verification-t3jdzv` / `gate-site-7xxoql` に、**ETF側の歴史検証が既に入っている。**

| ファイル | 中身 |
|---|---|
| `night/etf_beat_spy.py`（189行・新設） | S&P500に勝ったETFを**楽天の全取扱742本**で測る |
| `out/etf_beat_spy.json`（9,752行） | 上の結果。母集団は `out/broker_lineup.json`。**生存バイアスは構造的**（償還・取扱終了は最初から居ない）と自己申告済み。窓ごとに `spy` / `spy_maxdd` / `yrs` / `n` / `beat_n` / `beat_share` と全行 |
| `out/etf_profiles.json`（226行増） | ETFのプロファイル採取 |

実測例（`2006-08` 窓・19.92年・n=108）: SPY 11.18%/年・最大DD −50.8%。**勝ったのは20/108 = 18.5%**。SMH 19.93%（DD −57.0%）、VGT 16.89%（DD −50.6%）。

> **同じ測定をやり直す前に必ず `out/etf_beat_spy.json` を開くこと。** 742本・複数窓で既に測ってある。

関連コミット: `ad34ac2`（ETF測定の新設）／`b1421ef`（網ミックス4案の過去リターン比較・反証2班で全行一致・**以前のB/A数字は再現不能で撤回**）／`f92d5b9`（AIRR採取・設計攻撃が当初の枠組み2本を折り再定礎）

---

## 4. 移設後に増えたファイル（GitLab側）

### `night/` — 189本増（削除は0。GitLab 543本 / GitHub 354本）

遡及検証の中核:

| パス | 中身 |
|---|---|
| `night/retro_oos2_shoot.py` | 規約v2 OOSを撃つ本体（510行）。汚染ゲート・名簿突合・第0段ゲート・煙試験11本 |
| `night/retro_oos2_packet.py` | 規約v2の盲検パケット生成（`IRR_RUBRIC_V2`） |
| `night/retro_oos2_readlist.py` | 規約v2の標本（残り全部）を引く |
| `night/retro_oos_{shoot,packet,readlist}.py` | 同じ3点の規約v1版 |
| `night/retro_pillars_auc.py` | AUC・置換検定の実体（oos2はここから import＝二重実装しない） |
| `night/retro_delivery_check.py` | 納品/パケットの検問（`--deep` で原本キャッシュに逐語照合） |
| `night/RUNBOOK_retro_read.md` | 読解の手順書 |

その他の群: `night/spy20_*.py`（34本・20年でS&P500を超える銘柄の検証）／`night/irr70_15_*`・`irr70_blind_*`・`irr70_react_*`（約100本）／`night/etf_*`／`night/net10_*`（12本）／`night/inventory_catalog.py`・`pt_audit.py`・`claude_md_stale.py`・`audit_silent_default.py`

### `out/` — 遡及検証関連で36本以上

`retro_oos2_result_2013.json`（結果本体）／`retro_oos2_read_2013.json`（215社の盲検読解）／`retro_oos_result_2013.json`／`retro_irr_rubric_v2_draft.json`（規約v2草案）／`retro_omega_prereg.json`〜`_v12`・`_v12_amend1`（事前登録10本）／`retro_pillars_auc_2013_result.json`／`out/spy20_*`（34本）

> ⚠ `out/` は直下だけで1,400件超あり**総数は未確定**。マージ後に `git diff --stat 33448e4..main -- out/` で確定させる。

### ルート

`.gitlab-ci.yml`（1,192行・新設）／`gate_exclusions.json`（「門は🟢だが買わない」置き場・v9.9.172で新設）

### 追加されたCIジョブ（`.gitlab-ci.yml`・題名のタグで発火）

| ジョブ | タグ | 何を回すか |
|---|---|---|
| `retro-oos2-list` | `[oos2list]` | 規約v2の標本を引く。`n<100` なら事前登録v12により止まる |
| `retro-oos2-read` | `[oos2read]` | 盲検パケット生成（煙試験→名簿指紋→禁止リスト読み上げ→パケット） |
| `retro-oos2-shoot` | `[oos2shoot]` | **規約v2を撃つ**。`--selftest` が落ちたら本番を撃たない |
| `retro-oos-*` | `[oos*]` | 同じ3点の規約v1版 |
| `retro-oos-check` | `[ooscheck]` | 標本の ticker と原本の CIK が同じ会社を指しているかを数える |
| `market` / `score` / `shadow` | — | 題名に `[read-only]` があれば**飛ばす** |

---

## 5. 引き継ぐ側が最初に直すもの（未解決）

| # | 内容 | 場所 |
|---|---|---|
| 1 | **CLAUDE.md が 2026-09-13 で止まっている。oos / oos2 / 規約v2 の記述は全15,032行のどこにも無い**（全文検索で0件）。記録は `out/*.json` とコミットメッセージにしかない | CLAUDE.md |
| 2 | **v9.9.171 移植後の生成物が未再生成** — 重みが変わったのに `out/*.json` が古い | CLAUDE.md 14721–14723 |
| 3 | **第0段の門に穴** — 一致率だけを見るので「常に50を返す退化した規約」でも20/20で通る | `_v12_amend1.json` |
| 4 | **ticker→CIK の取り違え** — `SGI` に割り当てられた CIK 1206264 の10-Kはマットレスの会社だった。同じ対応表 `out/retro_cohort_2013.json` は**2013既読249社にも使われている**ため既存結果にも波及しうる。`retro-oos-check` で数えたが**件数がrepoに残っていない** | 班9の申し送り |
| 5 | **`pt` の二重定義** — 米国 `gate0_v8_5.py:447`（小数0〜1）と日本 `rebuild_gate0_jp.py:73`（百分率0〜約41）が同じ列名で約41倍のスケール差 | 両ファイル |
| 6 | **窓が満期でない社** — v1で7社（APYX 7.59 / BTU 9.34 / DBD 3.01 / EAF 8.34 / GNK 12.09 / PRPO 9.18 / RIOT 10.43）、v2で4社（EXE / HWM / PAYD / SD） | 結果JSON |
| 7 | **別ビンテージ未実施** — 2015 / 2018 は撃っていない。v10診断では 2013×2018 の tr_cagr が Spearman 0.845 で独立検証にならない可能性が高い | — |
| 8 | **バッチ表・原本URLは CI の artifacts にしかない**（repo未収載・1か月で期限切れ） | `.gitlab-ci.yml` |
| 9 | **門外例外が 5社（GitHub v9.9.171）と 6社（GitLab v9.9.175: VRSK/WST/ENTG/MKSI/TDG/BWXT）で食い違う** | マージ時に突合 |

**このHANDOFF.md自体が #1 の穴を埋める。** マージ後に CLAUDE.md からここへリンクを張ること。

---

## 6. 確認できていないこと

- `out/` の GitLabのみファイルの**総数は未確定**（1,400件超で列挙し切れず）
- `out/retro_oos2_read_2013.json`（215社の読解行そのもの）は未開封。集計値は結果ファイル経由
- `out/retro_omega_prereg_v12.json` / `_v12_amend1.json` の全文は未開封
- `.gitlab-ci.yml` の 501〜930行は未読（1〜500・931〜1192のみ）
- CIジョブのログ未確認 — `retro-oos-check`（ticker/CIK の一致件数）、`retro-oos2-shoot`
- **GitHub側の並走ブランチ29本のうち、`gate-site-7xxoql` が取り込んでいない9本の中身**は未確認。`70ebc8a` の triage 記録を先に読むこと
- **GitHub への push が現在通るかは未検証**（読み取りが通ることと、`main` へのブランチに今日の日付があることまでしか確認していない）

---

## 付録: 「stage N: 分割して積む」コミットの意味

2026-09-17 16:14〜17:14 に並ぶ `[skip ci] stage 1/5〜9` は、web UIの分割アップロードではない。`out/retro_oos2_read_2013.json` が MCP の1リクエストに収まらないため `_stage/oos2_read.part` へ632行ずつ分割投入し、最終コミットで本来のパスへ移した作業の痕跡（`9dde4196`:「内容は一字も変えない」）。間に挟まる `stage N fix: 転記の1文字を戻す` はその転記で混入したバックスラッシュ等の修正。**中身の変更ではないので、読むときは最終形だけ見ればよい。**
