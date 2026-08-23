# Plan完了に向けた残作業補足

**作成日:** 2026-08-24 JST
**対象:** `plan.md`「実発注・再起動耐性の完了」
**文書の役割:** 実装後に残っている検証、外部acceptance、証跡保存、完了判定を一つの手順にまとめる。

## 1. 結論

現時点の正確な判定は、**実装本体はほぼ完成しているが、Planは未完了**である。

完了を阻んでいる必須条件は次の二系統であり、両方を**同一の最終コード状態**で満たす必要がある。

1. 最新状態でのdifferentialを含むoffline full gate成功
2. OANDA practice市場が取引可能な時間帯での3通貨ペア実注文acceptance成功

read-only practice integrationの`16 passed`は重要な接続実績だが、注文作成・取消・約定・closeの実証にはならない。また、実注文acceptanceだけ成功してもoffline full gateが失敗していればPlan完了ではない。

## 2. 判定に使用する証跡の優先順位

監査資料には調査時点の設計課題、実装途中の評価、過去のテスト成功数が混在している。完了判定では次の順序を採用する。

1. この文書に従って最終コード状態で新たに取得する実行結果
2. 今回提示された最新の実行事実
3. `thorough-review-2026-08-23-de20497.md`などの実装後監査
4. `audit-findings.md`、`final-audit-report.md`、`practice-exception-handling-thorough-investigation.md`などの実装前・設計時監査

過去資料にある「production ready」「offline/differential成功」は、その後の変更と未実施のpractice mutation acceptanceを含まないため、Planの完了証跡として単独では使用しない。

## 3. 現在の証跡スナップショット

### 3.1 今回提示された最新の実行事実

| 項目 | 状態 | 判定 |
| --- | --- | --- |
| OANDA注文payload、typed submission result | 実装済み | コード実装は完了扱い |
| checkpoint、write-ahead journal、再起動reconciliation | 実装済み | コード実装は完了扱い |
| transient retry、quarantine、冪等close reporting | 実装済み | コード実装は完了扱い |
| practice acceptance CLIと安全ゲート | 実装済み | コード実装は完了扱い |
| practice read-only integration | 実接続で`16 passed` | 接続・照会gateは成功実績あり |
| practice実注文acceptance | `USD_JPY is not tradeable`で最初のsubmit前に停止 | 未完了 |
| 成功レポート | `runtime/practice-acceptance-report.json`なし | 未完了 |
| 最終offline full gate | `1 failed, 365 passed, 3 skipped, 16 deselected` | 未完了 |
| その後のfocused修正 | focused testは成功、full gate未再実行 | 未完了 |
| 当時のdifferential残差 | EUR/USDの浮動小数表現差1件、OANDA wire contract差6件 | 解消または明示承認が必要 |

### 3.2 補足資料作成時のworking tree確認

2026-08-24 01:07 JSTの読み取り確認では、次の状態だった。

- `runtime/practice-acceptance-report.json`は存在しない。
- working treeにはdifferential harness、golden、allowlist、関連文書の大きな未コミット変更がある。
- `tests/differential/intentional_deltas.json`は、提示された実行時点の空配列から変更され、50件の候補が記録されている。
- differential scenarioは41件存在する。
- この補足資料作成時には、その変更後のfull gateを再実行していない。

したがって、「残差7件を処理すれば自動的に完了」とは扱わない。現在のallowlist 50件、41 scenario、golden/manifestを一つの検証対象として再監査し、stale・過剰許可・未説明差分がない状態で全gateを通す必要がある。

## 4. 完了までのゲート

| Gate | 必須結果 | 現状 |
| --- | --- | --- |
| G0 最終スナップショット固定 | 一連の検証中にコード、test、golden、allowlistを変更しない | 未実施 |
| G1 Differential | current/golden比較とbaseline provenanceがすべて終了コード0 | 未確認 |
| G2 Offline full | pytest、Ruff、compileall、console smokeがすべて終了コード0 | 未確認 |
| G3 Practice read-only | 最新コードで`16 passed`、終了コード0 | 過去実績あり、最終状態での再確認待ち |
| G4 Practice mutation | 9 matrix entryが成功し、CLI終了コード0 | 市場休場で未実施 |
| G5 Cleanup・成果物 | owned pending/open差分0、成功report生成 | 未実施 |
| G6 最終記録 | 実行日時、コード状態、非secretのaccount識別、ID、cleanup結果を保存 | 未実施 |

G0からG6までがすべて成功した場合だけPlan完了とする。

## 5. 残作業A: Differential残差とgoldenを確定する

### 5.1 既知7差分の扱い

提示された最後の失敗時点では、次の差分が確認されていた。

- EUR/USDの浮動小数表現差: 1件
- OANDA公式wire contractへ変更したpayload差: 6件

浮動小数差は、発生源を確認してから次のいずれかに分類する。

- 通貨ペア精度で意味が同一なら、値の生成・mapping境界でdomain精度を適用する。
- 実際の計算意味が異なるなら、実装差として原因を修正する。
- 差を隠すだけの全体的な丸め、wildcard、広いsubtree許可は使用しない。

wire contract差はlegacyへ戻さない。MARKETの`timeInForce=FOK`とtop-level `price`省略、LIMIT/STOPの`timeInForce=GTC`はOANDA仕様準拠の意図的変更として、scenario、JSON pointer、旧値、新値、技術的理由、文書参照、期限を限定して記録する。

### 5.2 現在のallowlist再監査

現在の`intentional_deltas.json`は既知7差分より広い50件になっているため、各entryについて次を確認する。

- 一意の`delta_id`がある。
- 一つのscenarioと一つの絶対JSON pointerに限定されている。
- baseline/currentの値または正確なcanonical hashが固定されている。
- 安全性または設計上の意図が説明され、関連文書へ到達できる。
- expiryが妥当で、期限切れ・stale・未使用entryがない。
- productionの不具合やrunnerの誤差をallowlistで隠していない。
- golden更新が差分調査より先に行われていない。

### 5.3 Differential gate

allowlist、scenario、runner、golden、manifestに変更があるため、fast gateだけでなくbaseline provenance gateも必須とする。

```sh
.venv/bin/python -m pytest -q tests/differential/test_harness_contract.py
.venv/bin/python tests/differential/cli.py compare-current --all
.venv/bin/python -m pytest -q tests/differential/test_current_against_golden.py

.venv/bin/python tests/differential/cli.py verify-baseline \
  --all \
  --legacy-ref eff331c2367570dcb8bc35a323a382e8255eda7b

.venv/bin/python -m pytest -q \
  tests/differential/test_baseline_reproducibility.py \
  --run-baseline-replay \
  -m baseline_replay
```

受入条件は、全commandが終了コード0で、unexpected mismatch、stale allowlist、manifest hash不一致、baseline再現性エラーがないこと。失敗時は`build/differential/<scenario-id>/diff.json`の最初のunexpected pointerから調査する。

## 6. 残作業B: 最新状態のoffline full gateを通す

### 6.1 実行前記録

working treeがdirtyなため、HEADだけでは実行対象を識別できない。開始前に少なくとも次を受入記録へ保存する。

```sh
date '+%Y-%m-%d %H:%M:%S %Z'
git branch --show-current
git rev-parse HEAD
git status --short
git diff --stat
```

検証開始後は、G5までコード、test、scenario、golden、allowlistを変更しない。修正した場合は影響するfocused testだけで完了とせず、G1からやり直す。

### 6.2 Full gate

G1成功後にPlan記載の全体gateを実行する。

```sh
.venv/bin/python -m pytest --collect-only -q
.venv/bin/python -m pytest -q -m "not integration"
.venv/bin/python -m ruff check src tests
.venv/bin/python -m compileall -q src tests
.venv/bin/ogami-oanda-live --help
.venv/bin/ogami-oanda-live --offline-smoke --dry-run --once
```

受入条件は次のとおり。

- 全commandが終了コード0
- pytestに`failed`または`error`がない
- skip/deselectは意図したintegration/baseline gateだけで、理由を記録できる
- Ruffはissue 0
- compileallはerror 0
- console scriptがimport/entrypoint errorなく起動する
- offline smokeから実broker mutationが到達不能

テスト数はsuite拡張で変わるため、`365 passed`の固定再現ではなく、最新収集数と実行結果をそのまま記録する。

## 7. 残作業C: 市場再開後のpractice read-only確認

### 7.1 推奨時間帯

2026-08-24（月）の理論上の市場再開は06:05 JST以降である。ただし開始直後は`tradeable=false`、spread安全上限超過、一部pairの開始遅延があり得る。

- 最短候補: 06:15 JST以降
- 推奨: 07:00 JST以降
- 最終判断: OANDAがUSD_JPY、EUR_USD、AUD_USDの全てを`tradeable`として返し、spreadが設定上限内であること

時刻だけを根拠に安全gateを迂回してはならない。

### 7.2 Read-only integration

```sh
OGAMI_OANDA_RUN_INTEGRATION=1 \
OGAMI_OANDA_INTEGRATION_CONFIG=config/settings.yaml \
.venv/bin/python -m pytest -q tests/integration
```

必須結果は終了コード0かつ`16 passed`。内訳はaccount/capability・pending/open照会1件、3 pair quote 3件、3 pair × M5/H1/M30/S5 candle 12件である。

この時点で次も確認する。

- 読み込んだaccountのenvironmentが`practice`
- account ID/tokenが空でない
- 実行logや保存資料にtokenを残していない
- 実注文acceptance開始前のpending order/open tradeが0

既存pending/openがある場合は、acceptance CLIに削除させる目的で続行しない。所有者と用途を確認し、別作業として安全に解消する。

## 8. 残作業D: Practice実注文acceptanceを実行する

### 8.1 注意

このcommandはOANDA practice口座へ実際に注文を送る。MARKETでは小額のspread損失が発生し得る。実行対象は必ずpractice accountとし、account IDを設定値と照合してから実行する。

### 8.2 実行command

成功成果物をPlan指定先へ固定するため、`--report`を省略しない。

```sh
OGAMI_OANDA_ENABLE_PRACTICE_ORDERS=1 \
.venv/bin/ogami-oanda-practice-acceptance \
  --config config/settings.yaml \
  --account practice \
  --execute-practice-orders \
  --confirm-account-id '<practice-account-id>' \
  --accept-small-loss \
  --report runtime/practice-acceptance-report.json
```

`<practice-account-id>`は設定中のpractice account IDと完全一致させる。tokenやその他のsecretをcommand、report、受入記録へ記載しない。

### 8.3 Preflight受入条件

最初のsubmitより前に全3 pairについて次が成立する必要がある。

- brokerが返したaccount IDが確認対象と一致
- hedging要件を満たす
- baseline pending orderが0
- baseline open tradeが0
- `tradeable=true`
- spreadがpairごとの安全上限以下
- minimum trade sizeが1以上かつCLIの安全上限1 unit以下
- minimum trade sizeがbroker maximum以下

一つでも満たさない場合は非zero終了が正しい。安全gateを緩和せず、条件が整ってから再実行する。

### 8.4 必須の9 matrix entry

「9操作」は3 pair × 3 order typeのacceptance entryを指す。各entryは次のlifecycle全体を成功させる。

| Pair | LIMIT | STOP | MARKET |
| --- | --- | --- | --- |
| USD_JPY | create → PENDING確認 → cancel → cleanup確認 | create → PENDING確認 → cancel → cleanup確認 | open → OPEN確認 → close → cleanup確認 |
| EUR_USD | create → PENDING確認 → cancel → cleanup確認 | create → PENDING確認 → cancel → cleanup確認 | open → OPEN確認 → close → cleanup確認 |
| AUD_USD | create → PENDING確認 → cancel → cleanup確認 | create → PENDING確認 → cancel → cleanup確認 | open → OPEN確認 → close → cleanup確認 |

LIMIT/STOPが取消前に予期せずfillした場合、CLIはそのtradeのcleanupを試みたうえでworkflowを失敗扱いにする。cleanupできても、そのrunは成功acceptanceとして数えず、原因を確認して最初から再実行する。

### 8.5 終了条件

次をすべて満たすこと。

- CLI終了コード0
- reportの`success`が`true`
- reportの`operations`が9件
- pairごとにLIMIT/STOP/MARKETが各1件
- LIMIT/STOPに作成した`order_id`が記録されている
- MARKETに作成した`trade_id`が記録されている
- 全entryの`cleaned_up`が`true`
- 終了時pending集合と開始時baselineの差分が0
- 終了時open trade集合と開始時baselineの差分が0
- cleanup不明、owned orphan、未解決requestがない

成功reportの内容は次で確認する。

```sh
.venv/bin/python -m json.tool runtime/practice-acceptance-report.json
```

reportが存在しても`success=false`、operation不足、`cleaned_up=false`があれば未完了である。逆にCLI終了コード0でもreportを保存・保全できなければ証跡不足として未完了にする。

## 9. 失敗時の分岐

| 失敗 | 対応 | 再実行条件 |
| --- | --- | --- |
| `is not tradeable` | submit前の安全停止として記録し、待機 | 3 pair全てがtradeable |
| spread上限超過 | 上限を緩めず待機 | 全pairが安全上限内 |
| 既存pending/openあり | 自動cleanup対象にしない | 所有者確認後、baseline 0 |
| minimum units超過 | units上限を安易に引き上げない | broker ruleと損失上限を別途再評価 |
| UNKNOWN/timeout | blind resubmitしない | transaction/query照合とowned resource cleanup確認後 |
| cleanup失敗・不明 | Plan完了を宣言しない | pending/openをread-only照会し、残存0を確認後 |
| differential mismatch | golden/allowlistを直ちに広げない | 最初のunexpected pointerの原因解明後 |
| offline test失敗 | focused成功だけで閉じない | 修正後にG1・G2を再実行 |

## 10. 最終受入記録

秘密情報を含めず、少なくとも次を一つの記録へ残す。

| 項目 | 記録内容 |
| --- | --- |
| 実行日時 | JST、read-onlyとmutationの双方 |
| コード状態 | branch、HEAD、dirty status/diff stat |
| Differential | scenario数、allowlist数、各command結果 |
| Offline full | collect数、passed/failed/skipped/deselected、Ruff、compileall、smoke |
| Account | `practice` aliasと非可逆account hash。生account ID/tokenは記録しない |
| Read-only | `16 passed`、終了コード0 |
| Mutation | 9 entry、order/trade ID、各cleanup結果、終了コード0 |
| 最終差分 | pending order差分0、open trade差分0 |
| 成果物 | `runtime/practice-acceptance-report.json` |

実注文acceptance後にコード、test、golden、allowlistを変更した場合、そのacceptanceが変更箇所と無関係であることを推測で済ませない。原則としてoffline gateを再実行し、注文境界・acceptance workflowに影響する変更ならread-onlyおよびmutation acceptanceも再実行する。

## 11. 完了チェックリスト

- [ ] Differential fast gateが全て終了コード0
- [ ] Baseline provenance/reproducibility gateが終了コード0
- [ ] 最新コードでoffline pytestがfailure 0
- [ ] Ruff、compileall、console smokeが終了コード0
- [ ] 最新コードでpractice read-only integrationが`16 passed`
- [ ] Practice acceptance CLIが終了コード0
- [ ] USD_JPYのLIMIT/STOP/MARKET lifecycleが成功
- [ ] EUR_USDのLIMIT/STOP/MARKET lifecycleが成功
- [ ] AUD_USDのLIMIT/STOP/MARKET lifecycleが成功
- [ ] LIMIT/STOPが全て取消済み
- [ ] MARKET tradeが全てclose済み
- [ ] 終了時pending/open差分が0
- [ ] `runtime/practice-acceptance-report.json`が存在し、`success=true`
- [ ] 全9 operationの`cleaned_up=true`
- [ ] 未解決orphan、cleanup不明、主要PENDINGがない
- [ ] 非secretの最終受入記録を保存した

## 12. 完了宣言の文面

全チェック完了後は、次の要素を含めて完了を宣言する。

> 最新コード状態でdifferential provenanceを含むoffline full gate、OANDA practice read-only integration（16 passed）、USD_JPY/EUR_USD/AUD_USDのLIMIT/STOP作成取消およびMARKET open/close acceptanceを完了した。Practice acceptanceは終了コード0、9 entry全件cleanup済みで、終了時pending/open差分は0、成功reportは`runtime/practice-acceptance-report.json`に保存済みである。

いずれか一つでも未達の場合は、「実装本体はほぼ完成、最終offline整合またはpractice実注文acceptanceが未完了」と表現し、Plan完了とは宣言しない。
