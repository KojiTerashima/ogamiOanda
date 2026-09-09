# 旧資産のアーカイブ方針

[索引](README.md) / [移行マップ](migration-map.md)

## 通常の参照範囲

現行プログラムは `src/ogami_oanda/`、現行検証は `tests/`、説明書は本索引配下です。
`archive/retired/` は旧実装の手動ツールと過去の文書を圧縮保管する場所です。
AGENTS.mdで通常の読込・検索・展開・実行を対象外とし、`.rgignore` でも検索から除外します。
Gitにはアーカイブと一覧を追跡し、保管自体を `.gitignore` で隠しません。

これはアクセス制御ではありません。明示パス、`rg --no-ignore`、`git grep`、他のエディタや
エージェントは設定を回避できるため、作業規約と圧縮保管を併用します。
旧版の調査・復元を依頼された場合、または具体的な比較作業で必要な場合だけ一覧から辿ります。

例外として `archive/classPositionForTest.py` は `classPositionControl.py` がimportしています。
現役の互換依存なのでその場所と検索可視性を維持し、retiredへは移していません。
同様にルートの17個の互換/比較用Pythonファイルも維持しています。

## 2026-09-09の整理

保存基準は整理開始時のGitコミットです。正確なコミットと各ファイルの元パス・理由・サイズ・
モード・SHA-256は、明示的な履歴調査時に [manifest.json](../archive/retired/manifest.json) を参照してください。

| 圧縮ファイル | 内容 | ファイル数 |
| --- | --- | --- |
| `archive/retired/legacy-programs-2026-09-09.tar.gz` | 既存archiveの未使用15ファイル、ルートの未参照Python 11ファイル、旧参考データ2ファイル | 28 |
| `archive/retired/historical-docs-2026-09-09.tar.gz` | 日付付き完了記録2件と、過去の計画/設計書4件 | 6 |

退役したルートPythonは `ForTestOandaClass.py`, `SAMPLE_tokens.py`, `fFlagInspection.py`,
`fPredictTurn.py`, `tmp_rank_line_result.py` と6個の `test_*.py` です。
旧参考データは `Ref_file.txt` と `トレードJson.txt` です。
import、リテラルの動的import、参照文字列、現行テストの依存を調査し、依存閉包の外にあるものを選びました。
リポジトリ外からこれらを直接呼び出す運用までは検出できないため、復元可能な形で保管しています。

維持した移行資料は `architecture-migration.md`, `migration-map.md`, `differential-verification.md` です。
過去の文書内に書かれたパスやコマンドは当時の記録として保存し、現行の手順に読み替えません。

## 内容の保持と伏字

31ファイルは保存前後でバイト単位に一致します。次の3ファイルは既存の機密らしい値を
そのまま複製しないため、圧縮前に該当文字列のみ伏字にしました。

| 元ファイル | 伏字の対象 |
| --- | --- |
| `SAMPLE_tokens.py` | 通知先webhook URL 2箇所 |
| `archive/practice/Practice_python.py` | アクセストークン形式の値1箇所 |
| `トレードJson.txt` | 口座ID形式の値1箇所 |

一覧の `original_sha256` は整理前、`sha256` は保存内容のハッシュです。
`redactions` が空であれば両者は一致し、空でない場合は対象種類と件数を記録しています。
実設定 `config/settings.yaml` とローカル `tokens.py` は読み取り・複製・保管の対象外です。
伏字化は過去のGit履歴の書き換えや認証情報の失効を意味しません。

## 一覧確認・検証・復元

アーカイブ調査が必要なときだけ、リポジトリルートから実行します。
一覧確認と整合性検証は旧コードを実行しません。

```sh
python3 scripts/check_documentation.py --archives
tar -tzf archive/retired/legacy-programs-2026-09-09.tar.gz
```

展開先は既存作業を上書きしない新しい一時ディレクトリにします。

```sh
restore_dir=$(mktemp -d /tmp/ogami-legacy-review.XXXXXX)
tar -xzf archive/retired/legacy-programs-2026-09-09.tar.gz -C "$restore_dir"
```

文書を調べる場合も新しい空ディレクトリへ `historical-docs-2026-09-09.tar.gz` を展開します。
メンバー名は元のリポジトリ相対パスです。両バンドルを同じ空の復元先に展開すると当時の相対配置を再現できます。
旧スクリプトにはimport時に外部処理を行うものや未完成の構文を含むものがあります。
展開は実行許可を意味しません。比較に戻す場合は現行の互換依存・設定注入・オフライン契約を先に整えます。
伏字化した値は復元しません。

## 今後の退役条件

- src、互換起動口、tests、設定/ドキュメント内の参照と動的読込を確認する。
- 現行比較テストの依存は移動しない。名前や更新日の古さだけで決めない。
- 元パス・理由・ハッシュ・必要な伏字差分を記録し、圧縮内容の検証後に元パスを整理する。
- 現行索引のリンク、ソース参照一覧、検索除外、該当オフライン契約を確認する。

## 整理時の検証結果（2026-09-09）

- `python3 scripts/check_documentation.py --archives`: ローカルリンク、現行88 Pythonファイルと戦略YAML、712定義の参照、34保存メンバーのパス・モード・SHA-256が一致。
- 検査スクリプトは一時コピーで定義欠落・リンク切れ・ハッシュ破損を与えると失敗することも確認。
- 通常の `rg --files` はretiredを表示せず、現役の `archive/classPositionForTest.py` とruntimeの3 Pythonファイルは表示。bytecodeは表示しない。
- `ruff check src tests scripts`、`compileall -q src tests scripts`、CLIのoffline smokeは成功。
- 現行src、保持したルートPython、現役archive依存、既存テストのPythonは整理前とバイト一致。
- 全非integrationテストは整理前後とも **644 passed / 2 failed / 4 skipped / 16 deselected**。追加失敗なし。

検証環境のvenvには `pytz` がなかったため、そのままでは3件の収集エラーでした。
比較実行時だけ、システムに既存の `pytz` を一時ディレクトリ経由のPYTHONPATHで提供しました。
ネットワーク取得、依存定義変更、タイムゾーン処理のスタブ化は行っていません。
通常環境の準備手順は [テストガイド](../tests/README.md) を参照してください。

既存の失敗2件は次のとおりで、今回の整理でテストを緩和したり期待値を更新したりしていません。

| テスト | 整理前からの失敗理由 |
| --- | --- |
| `test_wall_clock_and_loop_sleep_are_confined_to_runtime_infrastructure` | `infrastructure/logging/daily_file.py` の `datetime.now` 2箇所がruntime限定規約に違反 |
| `test_current_runner_matches_checked_in_golden_traces` | goldenのPython版メタデータ不一致: 検証環境3.12.3、保存メタデータ3.12.5 |

旧コミット再実行を伴うbaseline replayと、認証付きintegration・practice受入・live操作は実行していません。
全テスト合格や外部運用受入完了を示す記録ではありません。
