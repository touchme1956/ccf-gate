#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/today.py — **「今日、何をすればいいか」を一枚にする**（2026-08-11新設）

■ なぜ要るか（利用者の言葉: 「今だと分かりにくくて毎日何をすればいいか分からない」）
  この台帳の検出器は毎日走って正しい答えを出し、コミットまでされ、**そして誰も読まない**。
  実測でそれが起きていた例——
    ・out/wacc_drift.json が `stale:true` で発火中なのに、読む先が index.html にも通知にも**ゼロ**
    ・out/todo_audit.json は ci.yml が毎日作ってコミットするのに、**消費者がゼロ**
    ・out/kessan/ の要審査14社（🟢投下可の KLAC を含む）が、門2審査の待ち行列に**流れていない**
  情報が足りないのではなく、**一箇所に集まっていない**。この道具はそれを集めるだけで、
  **新しい判定を一つも作らない**。

■ ⚠ この道具は判定を持たない（表示専用）
  Ω・採点式・刻み・重み・四関門・堀の関門70・売却規律S1/S2/S3・配分・別枠85 のどれにも触らない。
  出すのは out/today.json と画面だけ。**買付にも売却にも一切使わない。**
  期限の判定は `night/ops_status.py` の build() を**そのまま呼ぶ**（二重実装を作らない・v9.9.65）。

■ ★この道具の本体は「読めなかったものを出す」ところ
  2026-08-11 の精査で、このパイプラインの通知(`notify_issues.py`)は
  **out/ を全部消しても「✓ 行動が要ることは無い」と印字して exit 0** になることが実測で判った。
  第四の関門も同じで、pending.json のキーを `items`→`rows` に**改称するだけ**で
  VRSK が投下可に入り HWM が落ちる（実測）。
  ＝**盲目のときに「異常なし」に倒れる**（fail-open）。
  だからこの道具は必ず `blind`（読めなかった入力）を数え、**0件のときは「N本すべて読めた」と明示**する。
  「測っていない」と「測って問題なし」を取り違えないため（絶対のルール7の親戚）。

■ 段
  now     いま止まっている／壊れている（赤）
  today   今日見るもの
  month   今月やること
  waiting 待ち（引き金つき）——**件数を減らすことは目的ではない**
  blind   読めなかった入力（★必ず出す）

使い方:
  python3 night/today.py            画面に出す
  python3 night/today.py --json     out/today.json を書く
"""
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, 'night'))

AS_JSON = '--json' in sys.argv[1:]
TODAY = datetime.date.today()

# 読む入力。**読めなかったら blind に積む**（黙って空扱いにしない）。
# 4つ目は「この道具が実際に依存しているキー」——**JSONとして読めても、そのキーが無ければ blind**。
# ⚠ここが要る理由: 2026-08-11 の実測で、pending.json のキーを `items`→`rows` に**改称するだけ**で
#   第四の関門が全社通過になり VRSK が投下可に入った。ファイルは読めるので「壊れた」ように見えない。
#   ＝**読めた／読めないの二値では捕まらない**ので、依存するキーの実在まで見る。
SRC = [
    ('score_all', 'out/score_all.json', '採点と四関門の結果', None),
    ('validate_fail', 'out/validate_fail.json', '納品検査のFAIL', 'items'),
    ('pending', 'out/pending.json', '未完了の重大事象', 'items'),
    ('stale_bs', 'out/stale_bs.json', '期末後の貸借対照表', 'items'),
    ('promotion_ready', 'out/promotion_ready.json', '繰り上がりの作業リスト', 'rows'),
    ('events', 'out/events_watch.json', '8-K警報', 'alerts'),
    ('earnings', 'out/next_earnings.json', '次回決算', 'items'),
    ('wacc', 'out/wacc_drift.json', 'WACCの乖離', 'gate'),
    ('todo_audit', 'out/todo_audit.json', 'やることリストの点検', 'checked'),
    ('exception_watch', 'out/exception_watch.json', '門外例外の監視', 'rows'),
    ('myrule', 'out/irr85_myrule.json', 'あなたの選定ルール', 'items'),
    ('mech_diff', 'out/irr85_mech_diff.json', '機構文の年次diff', 'items'),
    ('mech_diff70', 'out/irr70_mech_diff.json', '機構文の年次diff(irr=70)', 'items'),
    ('kessan', 'out/kessan_flags.json', '四半期点検の旗', 'items'),
    ('profiles_ja', 'out/profiles_ja_audit.json', '事業説明の日本語要約の被覆', 'counts'),
    ('freshness', 'out/freshness.json', '中身と入力の鮮度', 'rows'),
    ('ci_health', 'out/ci_health.json', '自動化そのものの健康診断', 'rows'),
]


def days_since(s):
    """YYYY-MM-DD からの経過日数。取れなければ None（0 と読まない＝ルール7）"""
    try:
        y, m, d = map(int, str(s)[:10].split('-'))
        return max(0, (TODAY - datetime.date(y, m, d)).days)
    except Exception:
        return None


def item(k, level, title, why, how, src):
    return dict(k=k, level=level, title=title, why=why, how=how, src=src)


def build():
    data, blind = {}, []
    for key, path, label, need in SRC:
        try:
            with open(path, encoding='utf-8') as f:
                d = json.load(f)
        except Exception as e:
            data[key] = None
            blind.append(dict(key=key, path=path, label=label, why=type(e).__name__))
            continue
        if need is not None and not (isinstance(d, dict) and need in d):
            # JSONとしては読めたが、この道具が依存するキーが無い＝**中身は測れていない**
            data[key] = None
            blind.append(dict(key=key, path=path, label=label,
                              why='期待したキー "%s" が無い（あるのは %s）'
                                  % (need, ','.join(list(d)[:6]) if isinstance(d, dict) else type(d).__name__)))
            continue
        if need is None and not isinstance(d, list):
            data[key] = None
            blind.append(dict(key=key, path=path, label=label,
                              why='配列のはずが %s' % type(d).__name__))
            continue
        data[key] = d

    now, today, month, waiting = [], [], [], []
    sa = data.get('score_all') if isinstance(data.get('score_all'), list) else []
    byT = {r.get('t'): r for r in sa}
    buy = [r['t'] for r in sa if r.get('buy')]
    nxt = [r['t'] for r in sa if r.get('quali') and not r.get('buy')]

    # ── 回転盤（期限の判定は ops_status.build() をそのまま呼ぶ。ここで新しい線を作らない）──
    ops = None
    try:
        import ops_status
        ops = ops_status.build()
    except Exception as e:
        blind.append(dict(key='ops_status', path='night/ops_status.py',
                          label='運用サイクルの回転盤', why=type(e).__name__))
    for r in ((ops or {}).get('items') or []):
        st = r.get('state')
        if st == 'due':
            now.append(item('ops:' + r['id'], 'now', '止まっている疑い: ' + r['name'],
                            '最終 %s（%s日前・期限%s日）' % (r.get('last') or '不明', r.get('days'), r['due_days']),
                            r.get('how') or '', '回転盤'))
        elif st == 'unknown':
            now.append(item('ops:' + r['id'], 'now', '回っているか判らない: ' + r['name'],
                            '最終実行の日付が取れない＝**健全と読まないこと**', r.get('how') or '', '回転盤'))
        elif st == 'nokey':
            month.append(item('key:' + r['id'], 'month', '鍵待ちで始まっていない: ' + r['name'],
                              '止まったのではなく、まだ始めていない', r.get('how') or '', '回転盤'))

    # ── 投下可・次点に納品検査FAIL（席に着いている社の根拠に穴）──
    vfi = ((data.get('validate_fail') or {}).get('items')) or {}
    if isinstance(vfi, dict):
        for t in buy + nxt:
            if t in vfi:
                v = vfi[t] or {}
                now.append(item('vf:' + t, 'now', '納品検査FAIL: %s（%s）' % (t, '投下可' if t in buy else '次点'),
                                '%d件 — %s' % (v.get('n') or 0, (v.get('fails') or [''])[0][:70]),
                                'python3 night/validate_packs.py ' + t, '納品検査'))

    # ── 判定圏の要修正（点検 err＝検算しても消えない種類の破損）──
    for r in sa:
        if (r.get('audE') or 0) > 0 and (r.get('s') or 0) >= 72:
            now.append(item('err:' + str(r.get('t')), 'now', '点検の要修正: ' + str(r.get('t')),
                            'Ω%.1f・要修正 %d件' % (r.get('s') or 0, r['audE']),
                            'node night/audit_gate.js --t ' + str(r.get('t')), '全件点検'))

    # ── WACC の乖離（実測で発火中なのに、これまで読む先が一つも無かった）──
    w = data.get('wacc') or {}
    if w.get('stale'):
        g = w.get('gate') or {}
        now.append(item('wacc', 'now', 'WACC が更新どき',
                        '市場 %s%% vs 門 %s%%（乖離 %s > 刻み %s）'
                        % ((w.get('market') or {}).get('rfr'), g.get('html'), w.get('drift'), g.get('step')),
                        '✎採点機の WACC 欄を更新（規約の変更ではなく入力の更新）', 'wacc_drift'))

    # ── 自動化そのものが「走って失敗した」か（2026-08-18新設）──
    #   ⚠ 回転盤(ops_status)は**成果物の日付しか見ていない**ので、
    #   workflow が走って失敗しても「止まっている疑い」としか言えない。直し方がまったく違うのに。
    #   実測(2026-08-18): market.yml は 8/14・8/17 に走り、採取もパック反映も**全部成功**して
    #   コミットまで作ったのに `git push` が `! [rejected] main -> main` で弾かれ、
    #   **70ファイル分の成果が runner ごと捨てられた**。盤の表示は「止まっている疑い」だった。
    ch = data.get('ci_health') or {}
    for r in (ch.get('rows') or []):
        if r.get('conclusion') != 'failure':
            continue
        st = r.get('failed_steps')
        detail = '直近の実行(%s)が失敗' % (r.get('at') or '?')
        if st:
            detail += '——落ちたステップ: ' + ' / '.join(st)
        elif st is None and r.get('run_id'):
            detail += '（ステップ名は読めなかった）'
        now.append(item('ci:' + str(r.get('wf')), 'now',
                        '走って失敗している: ' + str(r.get('wf')),
                        detail,
                        (r.get('url') or 'GitHub Actions のログを見る')
                        + '　⚠『止まっている』ではなく『走って失敗』——直し方が違う', 'ci_health'))

    # ── 機構文が消えた（irr の根拠そのもの）──
    #   ⚠**70 も同じ重さで見る**（2026-09-19に配線）。実測(shadow_irr_step)で
    #   判定圏の 70→50 は投下可を10社→5社にする一方、50→70 も 85→70 も0社しか動かさない
    #   ＝コストは 70→50 の一方向。85 だけ見張って 70 を見ないのは非対称だった。
    for rung, key in (('85', 'mech_diff'), ('70', 'mech_diff70')):
        for t in ((data.get(key) or {}).get('gone') or []):
            now.append(item('mech%s:%s' % (rung, t), 'now', '機構文が消えた/書き換わった: ' + str(t),
                            'irr=%s の根拠の引用が最新の原本に無い' % rung,
                            'python3 night/irr85_mech_diff.py --rung %s --t %s' % (rung, t), '機構diff'))

    # ── あなたの選定ルール（irr=85）: 未決の分岐と新着 ──
    mr = data.get('myrule') or {}
    for t, v in ((mr.get('items') or {}) if isinstance(mr.get('items'), dict) else {}).items():
        if isinstance(v, dict) and v.get('undecided'):
            now.append(item('irr85und:' + t, 'now', '未決の分岐に当たった: ' + t,
                            ' '.join(str(v['undecided']).split())[:120],
                            'python3 night/irr85_myrule.py', 'あなたのルール'))
    for t in (mr.get('new') or []):
        today.append(item('irr85new:' + str(t), 'today', 'irr=85 の新着: ' + str(t),
                          'あなたの選定ルール（営利率11.89 / FCF転換0.639 / 成長1.76）で採点し直す',
                          'python3 night/irr85_myrule.py', 'あなたのルール'))

    # ── 事業説明の日本語要約（v9.9.154・2026-08-18新設。表示専用・判定には一切使わない）──
    #   門は Ω・堀・E[r] という**評価**を全部出すのに、「何をしている会社か」は英文のままだった。
    #   新しく審査した社／原本が新しくなった社は**訳が無いまま静かに増える**ので、ここへ出す。
    #   ⚠ 材料なし18社は出さない——原本の英文も台帳の日本語根拠も無く、
    #      作業として渡しても書けない（憶測で書かせないための穴の明示は --audit の側）。
    pj = data.get('profiles_ja') or {}
    for r in (pj.get('todo') or []):
        st = str(r.get('state') or '')
        month.append(item('pja:' + str(r.get('t')), 'month',
                          ('事業説明の日本語要約が無い: ' if st == '未訳'
                           else '事業説明の素材が変わった（訳が古い）: ') + str(r.get('nm') or r.get('t')),
                          '素材=' + str(r.get('kind') or '?') + '（原本の英文 or 台帳の日本語根拠）',
                          'python3 night/profiles_ja.py --next 12 → 要約を書いて --add', '日本語要約'))

    # ── 中身と入力の鮮度（2026-08-17新設）──
    #   回転盤は**日付しか見ていない**ので「日付は動いたが中身/入力が死んでいる」は🟢に見える。
    #   ⚠ CIでは落とさない作業リストなので、ここに出さないと**CIログの中だけで完結する**
    fr = data.get('freshness') or {}
    for r in (fr.get('rows') or []):
        for f in (r.get('flags') or []):
            month.append(item('fresh:' + str(r.get('id')) + ':' + f[:12], 'month',
                              '中身/入力が前進していない: ' + str(r.get('name')), f,
                              'python3 night/check_freshness.py', '鮮度'))
    # **測れないものは健全と読まない**（ルール7）——数だけ出して、内訳は器で見る
    nun = fr.get('n_unmeasurable')
    if nun:
        month.append(item('fresh:unmeasurable', 'month',
                          '鮮度を測れない錨が %d件' % nun,
                          '「測っていない」であって「測って問題なし」ではない',
                          'python3 night/check_freshness.py', '鮮度'))

    # ── 四半期点検の要審査（2026-08-11: 待ち行列に流れていなかった穴を塞いだ・v9.9.140）──
    #   ⚠「点検不能（20-F/40-F発行体）」は**採取の穴であって会社の異常ではない**ので段を分ける。
    kf = data.get('kessan') or {}
    for t, v in ((kf.get('items') or {}) if isinstance(kf.get('items'), dict) else {}).items():
        if not v.get('need'):
            continue
        vd = str(v.get('verdict') or '')
        where = '🟢投下可' if t in buy else ('🔵次点' if t in nxt else '')
        if '点検不能' in vd:
            month.append(item('kes:' + t, 'month', '四半期点検が不能: %s %s' % (t, where),
                              vd[:90] + '（採取の穴＝再審査では直らない）',
                              'kessan_checklist.md §C の手動確認', '四半期点検'))
        elif v.get('superseded'):
            # ★2026-08-12: パックの原本が既にこの四半期を含む＝空振りの可能性が高い。
            #   **消さずに「今月」へ落とす**（要審査を異常なしに書き換えると
            #   『測っていない』と『測って問題なし』の取り違えを自分で作る）。
            month.append(item(
                'kes:' + t, 'month', '四半期点検で要審査: %s %s（空振りの可能性）' % (t, where),
                vd[:70] + '  ★パックの原本が既にこの四半期を含む（期末%s ≥ 四半期末%s）'
                % (v.get('pack_report'), v.get('qend')),
                '既に審査済かを _meta.kenshi で確かめる。新規事象なら門2再審査へ', '四半期点検'))
        else:
            (today if where else month).append(
                item('kes:' + t, 'today' if where else 'month',
                     '四半期点検で要審査: %s %s' % (t, where), vd[:100],
                     '⚙自動化タブの「審査」で門2再審査／night/enqueue_reaudit.py で順位を見る', '四半期点検'))
    for u in (kf.get('unparsed') or []):
        blind.append(dict(key='kessan:' + str(u.get('t')), path=str(u.get('path')),
                          label='四半期点検の判定', why=str(u.get('why'))))

    # ── 8-K警報 ──
    ev = data.get('events') or {}
    for a in (ev.get('alerts') or []):
        today.append(item('alert:%s:%s' % (a.get('t'), a.get('date')), 'today',
                          '8-K警報: %s（%s）' % (a.get('t'), a.get('date')),
                          ' / '.join(a.get('flags') or a.get('items') or []),
                          '⚙自動化タブの「審査」で門2再審査の依頼文を作る', '8-K監視'))
    for e in (ev.get('errors') or []):
        blind.append(dict(key='events:' + str(e.get('t') or '?'), path='out/events_watch.json',
                          label='8-K監視の取得失敗', why=str(e.get('why') or e)[:80]))

    # ── 決算（3日以内）──
    for e in ((data.get('earnings') or {}).get('items') or []):
        try:
            y, m, dd = map(int, str(e.get('date'))[:10].split('-'))
            ahead = (datetime.date(y, m, dd) - TODAY).days
        except Exception:
            continue
        if 0 <= ahead <= 3:
            who = '保有' if e.get('hold') else ('監視' if e.get('elite') else '')
            today.append(item('earn:' + str(e.get('t')), 'today',
                              '決算: %s（%s）%s' % (e.get('t'), e.get('date'), who),
                              '本日' if ahead == 0 else '%d日後' % ahead,
                              '発表後に python3 kessan_check.py（判定は警報のみ・株価は使わない）', '決算カレンダー'))

    # ── 門外例外の見張り（あなたが門の外で買っている社）──
    for r in ((data.get('exception_watch') or {}).get('rows') or []):
        v = str(r.get('verdict') or '')
        if ('悪化' in v) or ('線の上' in v):
            today.append(item('exc:' + str(r.get('t')), 'today', '門外例外の見張り: ' + str(r.get('t')),
                              v, 'python3 night/watch_exceptions.py', '例外監視'))

    # ── 今月の作業リスト ──
    for r in (((data.get('promotion_ready') or {}).get('rows')) or [])[:3]:
        month.append(item('pr:' + str(r.get('t')), 'month',
                          '根拠を埋めれば席に着く: %s（繰り上がり%s番目）' % (r.get('t'), r.get('rank')),
                          'Ω%.1f・納品検査FAIL %s件' % (r.get('s') or 0, r.get('vFail')),
                          'python3 night/validate_packs.py ' + str(r.get('t')), '繰り上がり'))
    ta = data.get('todo_audit') or {}
    n_ta = sum(len(ta.get(k) or []) for k in ('resolved', 'drifted', 'duplicates', 'gate_exception_mismatch'))
    if n_ta:
        month.append(item('todoaudit', 'month', 'やることリストの点検で %d件' % n_ta,
                          '解決済みなのに未完のまま／件数のずれ／重複／例外との食い違い',
                          'python3 night/audit_todo.py', 'todo点検'))
    month.append(item('dca', 'month', '今月の買付（DCA）',
                      '🛒買付順位の「今月の入金額」に金額を入れると注文書が出る',
                      '🛒買付順位タブ → 📋今月の注文書', '月次'))

    # ── 待ち。**件数を減らすことは目的ではないが、誰がやるかで分けないと人が消化できない** ──
    #   2026-08-18(ユーザー「まちおおすぎない？消化しきれない」)——実測で
    #   総127→137件を2日で足しており、**足す速さが消す速さを上回っていた**。
    #   だが中身を数えると **83件のうち人がやるのは30件で、手を動かせるのは5件**だった。
    #   残りは (a)原本読解＝**頼んだときにセッションで審査する**（日次Routineは2026-09-23に停止） (b)採取器・検査器のバグ＝実装
    #   (c)データ経路が無い＝**「終わる」ことがない立ち位置の記録**。
    #   → `owner` で割り、**人のものだけ名前を出す**。他は数だけ。**リストからは何も消していない**。
    for t in (((ops or {}).get('todos') or {}).get('items') or []):
        if not t.get('done'):
            waiting.append(dict(k='todo:' + str(t.get('id')), kind=t.get('kind') or '',
                                title=t.get('title') or '', due=t.get('due'),
                                owner=t.get('owner') or '人',
                                tickers=t.get('tickers') or []))

    return dict(
        generated=TODAY.isoformat(),
        note=('「今日、何をすればいいか」だけを集めた表示専用の在庫。**判定には一切使わない**——'
              'Ω・四関門・売却規律・配分のどれにも触れない。期限の判定は ops_status.build() を'
              'そのまま呼ぶ（二重実装を作らない）。**blind（読めなかった入力）を必ず出す**のがこの道具の本体で、'
              '盲目のときに「異常なし」へ倒れる fail-open を画面の側で塞ぐためにある。'),
        buy=buy, next=nxt,
        counts=dict(now=len(now), today=len(today), month=len(month),
                    waiting=len(waiting), blind=len(blind), src=len(SRC) + 1),
        now=now, today=today, month=month, waiting=waiting, blind=blind)


def main():
    o = build()
    c = o['counts']
    print('■ 📋 今日')
    print('  投下可 %d社: %s' % (len(o['buy']), ' '.join(o['buy'])))
    print()
    for key, label in (('now', 'いま止まっている／壊れている'), ('today', '今日見るもの'), ('month', '今月')):
        rows = o[key]
        print('  【%s】%d件' % (label, len(rows)))
        for r in rows:
            print('    ・%s' % r['title'])
            if r['why']:
                print('        %s' % ' '.join(str(r['why']).split())[:110])
            if r['how']:
                print('        → %s' % ' '.join(str(r['how']).split())[:110])
        if not rows:
            print('    （なし）')
        print()
    # 誰がやるかで割る。**人のものだけ名前を出す**——他を並べても人は消化できないから
    todo_tk = {w['k'][5:]: w.get('tickers') for w in o['waiting']
               if w['k'].startswith('todo:') and w.get('tickers')}
    own = {}
    for w in o['waiting']:
        own.setdefault(w.get('owner') or '人', []).append(w)
    mine = own.get('人', [])
    hands = [w for w in mine if w['kind'] == '宿題']          # 今すぐ手を動かせる
    dec_live = [w for w in mine if w['kind'] == '決断待ち' and w['title'].startswith('【今日効く】')]
    dec_dorm = [w for w in mine if w['kind'] == '決断待ち' and not w['title'].startswith('【今日効く】')]
    rest = [w for w in mine if w['kind'] not in ('宿題', '決断待ち')]
    print('  【あなたの手を動かすもの】%d件' % len(hands))
    for w in hands:
        print('    ・' + w['title'][:78])
    # 決断は**毎日は出さない**。名前を毎日並べると読み飛ばす訓練になるだけで、
    #   それが「消化しきれない」の正体だった。決断に要るのは日次の注意ではなく**定期の棚卸し**で、
    #   その仕組みは既にリストにある（定期(手動)『決断待ちの棚卸し（四半期）』）。
    print('  【あなたの決断】今日 判定を動かす %d件 ／ 休眠(引き金つき) %d件 ／ 定期・予約 %d件'
          % (len(dec_live), len(dec_dorm), len(rest)))
    print('     → 名前は ⚙自動化タブ／`python3 night/today.py --json`。'
          '**毎日は読まない**——四半期の「決断待ちの棚卸し」でまとめて見る')
    # ⚠「待ち行列が消化する」は**銘柄を名指ししたものだけ**。名指ししていないものは
    #   どの queue にも流れない——ラベルを貼っただけで消化されるわけではない（2026-08-18 の実測で0件だった）
    rev = own.get('審査', [])
    rev_q = [w for w in rev if (todo_tk.get(w['k'][5:]) if w['k'].startswith('todo:') else None)]
    print('  【人がやらないもの】 審査 %d件（うち %d件は待ち行列へ流れている／残り %d件は銘柄を名指ししていないので流れない）'
          % (len(rev), len(rev_q), len(rev) - len(rev_q)))
    print('                       実装 %d件 ／ 測れない範囲 %d件（＝「終わる」ことがない立ち位置の記録）'
          % (len(own.get('道具', [])), len(own.get('穴', []))))
    print('     ※リストからは何も消していない。**誰がやるかで割っただけ**'
          '（todo_list.json の owner）。件数を減らすこと自体は目的ではない')
    print()
    # ★ここがこの道具の本体
    if o['blind']:
        print('  【⚠ 読めなかった入力】%d件 — **この分は「異常なし」ではなく「測っていない」**' % c['blind'])
        for b in o['blind']:
            print('    ・%s（%s）… %s' % (b['label'], b['path'], b['why']))
    else:
        print('  【読めなかった入力】0件 — 入力 %d本すべて読めた（＝上の「なし」は本物）' % c['src'])

    if AS_JSON:
        # 空書き込みの検問（audit_stale_bs:243 と同じ言葉）——錨が読めていないなら書かない。
        # 検査の不在を「異常なし」と偽らないため。
        if not isinstance(o['buy'], list) or not o['buy']:
            print('\n⚠ out/score_all.json が読めない／投下可が空。**today.json を書き換えない**'
                  '（空で上書きすると、この画面が「今日やることはありません」と嘘をつく）')
            return 1
        p = 'out/today.json'
        json.dump(o, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('\n→ %s' % p)
    return 0


if __name__ == '__main__':
    sys.exit(main())
