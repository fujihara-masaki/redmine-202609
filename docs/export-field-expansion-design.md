# export項目の段階的拡張設計

## 目的と前提

現在のJSONに選択するbasic項目は `id`, `subject`, `project`, `tracker`, `status`,
`assigned_to`, `created_on`, `updated_on` である。CSVは参照項目をID/name列へ展開する。
本設計は、それ以外のQUICK2/Redmineデータを、データ最小化、後方互換性、読み取り専用境界を
保って段階的に追加するための案であり、このPRでは追加項目を実装しない。

標準Redmineの一般的なREST API仕様を候補発見の出発点とするが、対象QUICK2のバージョン、
独自改修、権限、設定、実レスポンスでの存在や型は未確認である。候補を「必ず存在する項目」と
扱わず、秘密を含まない検証記録と管理者承認を経て許可リストへ加える。

## A. `/issues.json` 一覧レスポンスで得られる可能性がある標準項目

一般的なRedmineの候補を次のように分類し、対象環境の架空/検証用projectで一覧レスポンスを
確認してから採用する。

| 分類 | 候補 | 想定する表現と確認点 |
| --- | --- | --- |
| 参照 | `priority`, `author`, `category`, `fixed_version`, `parent` | ID/name等のshape、未設定時の省略/null、権限による差 |
| 日付 | `start_date`, `due_date` | 日付だけか日時か、未設定値。JST日時変換の対象にしない |
| 進捗・工数 | `done_ratio`, `estimated_hours` | 数値型、null、小数、権限、業務上の機密区分 |
| フラグ | `is_private` | boolean型、private issue自体の可視権限 |

採用時は項目ごとに必要性、型、最大サイズ、欠損時表現、CSV式対策、JSON型保持、権限別結果を
テストする。実レスポンスをfixtureにコピーせず、完全な架空データを作る。

## B. `description` など本文系

本文は大容量かつ個人情報、障害詳細、ログ、秘密情報を含む可能性が高い。basicへ無条件に
追加しない。必要性、閲覧者、保存先、保持期限、マスキング可否、最大サイズを別レビューし、
明示opt-inの専用profileまたは本文専用exportとする。コンソール、エラー、metadataへ本文を
出さない。CSVセルの改行・式注入対策だけでは情報管理上十分ではない。

## C. `custom_fields`

独自項目は存在する可能性があるが、実field名や実値をrepositoryへ記録しない。対象環境ごとに
管理者が次を棚卸しする。

- custom field ID（設定上の安定キー候補）と表示name（改名可能性を考慮）
- value type（文字列、数値、日付、真偽、列挙、ユーザー参照等）
- 単一値か複数値か、および空値/欠損の区別
- ロール、project、issue visibilityによる可視性
- 個人情報・認証情報・業務秘密等の機密区分と保持期限

実装する場合は**IDの許可リスト方式**を基本とし、未知のfieldを自動収集しない。JSONでは
型、ID、承認済み表示名、単一/複数値を曖昧にしない構造を定義する。CSVでは列名衝突を避ける
安定キーを使い、複数値は順序、区切り、escapingを仕様化する（安易な可変列や暗黙joinを
避ける）。許可項目が見えない場合は空値と権限不足を混同しない検証・警告方針も決める。

## D. 個別issue GETや`include`が必要になり得る項目

`journals`, `relations`, `attachments`, `watchers` 等は、Redmineのバージョンや権限により
個別issue API、`include`、別endpointを必要とし得る。一覧の1リクエスト/ページとは件数、
負荷、権限、機密性、ページング、失敗時の完全性が異なるため、basic一覧exportから分離する。

導入前に対象環境の公式/管理者情報と実機で、endpoint、GETだけで得られる範囲、N+1負荷、
レート制限、最大件数、可視性、attachmentsのバイナリを取得しない方針を確認する。新endpointは
個別PRで固定パスとしてレビューし、汎用path/method機能にはしない。このPRではいずれも追加しない。

## E. 出力profile案と移行

後続PRでは次のような固定profileを検討する。

- `--fields basic`: 現行最小項目。既定のままとし、列順・JSON schemaを維持する。
- `--fields extended`: 対象環境で確認・承認した標準追加項目だけの固定許可リスト。
- custom fields: field ID許可リストを別の明示opt-in設定にする。
- 本文: profileからも独立した明示opt-inとし、承認済み用途だけにする。

既存利用者を壊さないため、新項目はbasicへ暗黙追加しない。profile名、schema version、選択項目を
metadataへ記録する案を検討し、CSV/JSONのgolden test、欠損/型違い、機密非表示、最大サイズ、
旧basic完全一致をCIで検証する。導入順は標準の低機密・小容量項目、承認済みcustom field、
本文/個別issue情報の順とし、各段階を独立PRにする。
