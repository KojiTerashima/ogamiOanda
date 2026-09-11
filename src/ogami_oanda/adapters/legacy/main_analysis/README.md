# main原文の互換実行器

利用方法・データ契約・更新・検証は[main解析ガイド](../../../../../docs/main-analysis.md)を参照してください。

| ファイル | 責務 |
| --- | --- |
| `source.py`, `loader.py` | mainディレクトリの直接読み込みと評価専用のimport・時刻・出力・外部依存の変換 |
| `inputs.py`, `session.py` | 入力変換、評価状態、元オブジェクトの寿命管理 |
| `analysis.py` | 解析のみの窓口 `analyze` |
| `orders.py` | 注文候補のみの窓口 `build_order_candidates` |
| `values.py` | 元オブジェクトから返却可能な値への変換 |
| `backend.py` | original用のdomainポート実装、各段階の組み合わせ |

原文の公開関数を変更せず、その関数が要求するクラスと引数をこのadapter内で用意します。
注文候補の型とIntent変換はdomainに置きます。原文を同梱せず、mainの秘密設定も読み込みません。
