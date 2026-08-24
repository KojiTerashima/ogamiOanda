# Plan完了受入記録

**判定:** COMPLETE
**対象Plan:** `plan.md`「実発注・再起動耐性の完了」
**補足手順:** `docs/plan-completion-remaining-work-2026-08-24.md`
**完了日時:** 2026-08-24 21:27 JST

## 1. 検証対象

| 項目 | 値 |
| --- | --- |
| Branch | `feat/live-order-completion` |
| Tested HEAD | `d005de45d1f32931ada4eef2878729702cdcdaf9` |
| Differential baseline | `eff331c2367570dcb8bc35a323a382e8255eda7b` |
| Differential scenario | 41 |
| Intentional delta | 50 |
| Practice account alias | `practice` |
| Practice account hash | `569940e62a7199f5ca14ee20` |
| 成功report | `runtime/practice-acceptance-report.json` |

検証中のworking treeには無関係な未追跡`.vscode/`だけが存在した。コード、test、scenario、golden、allowlistはG0からG5まで変更していない。

## 2. G1 Differential

| Gate | 結果 |
| --- | --- |
| Harness contract | `36 passed` |
| Current vs golden CLI | 41 scenarioすべて`current ok` |
| Current vs golden pytest | `1 passed` |
| Baseline provenance CLI | 41 scenarioすべて`baseline ok` |
| Baseline reproducibility | `4 passed, 1 deselected` |

unexpected mismatch、stale allowlist、manifest hash不一致、baseline再現性エラーは発生しなかった。

## 3. G2 Offline full gate

| Gate | 結果 |
| --- | --- |
| Collect-only | `460 tests collected` |
| Offline pytest | `440 passed, 4 skipped, 16 deselected` |
| Skip理由 | 明示実行が必要な`baseline_replay` 4件 |
| Deselect理由 | credentialが必要な`integration` 16件 |
| Ruff | `All checks passed!` |
| Compileall | 終了コード0 |
| Console help | 終了コード0 |
| Offline smoke | `accepted=0 rejected=0 skipped=- plans=- accepted_names=- rejected_reasons=-` |

## 4. G3 OANDA practice read-only integration

practice environmentとcredential設定を確認し、注文mutationを行わないintegration matrixを実行した。

```text
16 passed in 6.25s
```

内訳はaccount/capability・pending/open照会1件、USD_JPY/EUR_USD/AUD_USD quote 3件、3 pair × M5/H1/M30/S5 candle 12件である。

## 5. G4 Practice実注文acceptance

専用CLIの全安全gateを有効にし、report先を明示して実行した。CLIは成功pathを完了し、`runtime/practice-acceptance-report.json`へ`success=true`を保存した。成功pathのentrypoint return codeは0である。

reportの機械検証結果:

```text
report_exists=True
success=True
account_hash_matches=True
operation_count=9
matrix_complete=True
all_cleaned=True
pending_ids_complete=True
market_trade_ids_complete=True
error_present=False
```

### 5.1 Operation matrix

| Pair | Order type | Order ID | Trade ID | Cleaned up |
| --- | --- | ---: | ---: | --- |
| USD_JPY | LIMIT | 24410 | - | true |
| USD_JPY | STOP | 24412 | - | true |
| USD_JPY | MARKET | 24414 | 24415 | true |
| EUR_USD | LIMIT | 24422 | - | true |
| EUR_USD | STOP | 24424 | - | true |
| EUR_USD | MARKET | 24426 | 24427 | true |
| AUD_USD | LIMIT | 24434 | - | true |
| AUD_USD | STOP | 24436 | - | true |
| AUD_USD | MARKET | 24438 | 24439 | true |

各LIMIT/STOPは作成後にPENDINGを確認して取消した。各MARKETはtrade OPENを確認してcloseした。

## 6. G5 Cleanup独立照会

acceptance CLI終了後、別のread-only queryでbroker状態とreport内IDを再確認した。

```text
pending_count=0
open_trade_count=0
cancelled_order_count=6
closed_trade_count=3
cleanup_verified=True
```

開始時baselineはpending/openともに0であり、終了時差分も0である。未解決orphan、cleanup不明、owned pending/openはない。

## 7. Security記録

- account IDとaccess tokenはtracked fileおよび本記録へ保存していない。
- accountの識別には非可逆hashだけを使用した。
- 検証途中に使用したpractice tokenは再発行済みである。
- 最終tokenはmode 600のgitignored一時ファイル経由でprocess environmentにだけ読み込んだ。
- `runtime/practice-acceptance-report.json`はaccount hash、broker ID、cleanup結果だけを保持し、tokenを含まない。

## 8. 完了チェックリスト

- [x] Differential fast gate成功
- [x] Baseline provenance/reproducibility成功
- [x] 最新コードでoffline pytest failure 0
- [x] Ruff、compileall、console smoke成功
- [x] Practice read-only integration `16 passed`
- [x] Practice acceptance CLI成功path・終了コード0
- [x] USD_JPYのLIMIT/STOP/MARKET lifecycle成功
- [x] EUR_USDのLIMIT/STOP/MARKET lifecycle成功
- [x] AUD_USDのLIMIT/STOP/MARKET lifecycle成功
- [x] LIMIT/STOP 6件が全てCANCELLED
- [x] MARKET trade 3件が全てCLOSED
- [x] 終了時pending/open差分0
- [x] 成功report生成、`success=true`
- [x] 全9 operationの`cleaned_up=true`
- [x] 未解決orphan、cleanup不明、主要PENDINGなし

## 9. 完了宣言

最新コード状態でdifferential provenanceを含むoffline full gate、OANDA practice read-only integration（16 passed）、USD_JPY/EUR_USD/AUD_USDのLIMIT/STOP作成取消およびMARKET open/close acceptanceを完了した。Practice acceptanceは成功path・終了コード0、9 entry全件cleanup済みで、終了時pending/open差分は0、成功reportは`runtime/practice-acceptance-report.json`に保存済みである。
