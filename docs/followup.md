# PR-2: フォロー判定・ローカルレビュー出力

## 業務条件と有効化

QUICK2の正式名称「発見日」は障害を検知・発見した日付。発見日当日を0日とした暦日差が、
障害区分の日数設定以上で、取得した**現在の**ステータスが未完了なら「対象」。CSVの「〇」は
U+3007で、この条件だけを示す。期限違反、承認不備、完了への変更可否は判定しない。
90日を3か月、180日を6か月へ読み替えず、休日・営業日補正もしない。
「到達日を迎える月」に対象とする月次判定、期限延長、期限後完了の評価、承認確認は後続。

`export --followup-config <path>` だけが有効化条件。basic/extended、JST列と独立して併用できる。
指定しない場合は既存CSV/JSON/metadata/エラー条件を維持する。`--as-of YYYY-MM-DD` はこの機能との
併用だけ許可する。フォロー指定時の `--status` は既定 `*` のみで、他の指定は認証前に停止する。
通常exportのstatus指定は従来どおり。project/tracker/子projectの既存指定を使い、直近90/180日等の
取得制限を追加せず、ID昇順の全ページ取得後に全行を判定する。

基準日を省略した場合、実行開始時にJST固定UTC+09:00の当日を一度だけ確定し全行へ共有する。
過去の `--as-of` は現在取得した状態の計算基準日を変更するもので、過去のステータスを復元しない。
発見日は日付だけで時差変換せず、created_on/start_date/updated_on等で代用しない。

## ローカル設定

接続設定とは別に `followup-rules.example.toml` を `followup-rules.toml` へコピーし、利用者が
管理者確認済みの実値へ変更する。101、102、5は**仮のID**で、実環境の値ではない。

```toml
schema_version = 1

[fields]
incident_type_custom_field_id = 101
discovered_on_custom_field_id = 102

[statuses]
completed_ids = [5]

[threshold_days]
"非影響" = 90
"軽障害" = 90
"中障害" = 180
"重障害" = 180
```

区分名はAPI文字列との完全一致。空白除去、曖昧一致、推測、既定日数はない。
schema_version=整数1、全必須キー、未知キー、テーブル/配列/値型を厳格に検証する。
2つのIDは異なる正整数、completed_idsは空でない正整数配列、threshold_daysは空でないテーブルで、
空または空白だけでない区分名と正整数日数を要求する。整数にbooleanは含めない。
設定不備、基準日不正、オプション不整合はAPIキー入力・通信・完成出力より前に停止する。
エラーに設定内容や不明なキー名・値を表示しない。

`followup*.toml` はexample以外Git対象外。実ルールはこの名前またはrepository外へ置く。
別名の実運用ファイルをrepository内へ保存しない。実URL、キー、実設定、チケット、応答、exportを
公開repository/PRへ貼らない。QUICK2の実フィールドID、完了ID、実区分値、可視性、型は未確認。

Python CLIのルール相対パスは呼出元のカレントディレクトリ基準。
Windows起動補助の `-FollowupConfig` は既存ConfigPathと同じ**repository基準**で絶対パスも可。
wrapperはパス存在・組合せ・日付の形を事前検証し、TOML内容はPython CLIで一度読み込む。
起動補助は汎用引数を持たず、Inherit/Systemのproxy事前照合、一時設定・復元とcleanup契約を維持する。

## 判定の優先順位

1. status.idが欠損・不正（bool、0以下、文字列等）なら `invalid_status`、判定不能。
2. 有効IDがcompleted_ids内なら `completed`、対象外。発見日未入力でも判定不能にしない。
3. その他の有効IDは未完了。区分の入力不備、未定義区分なら判定不能。
4. 発見日の入力不備、実在しない日付、厳密なYYYY-MM-DD以外、未来日なら判定不能。
5. 必要な到達日計算が範囲外なら `date_out_of_range`、その行だけ判定不能。
6. 経過日数 >= 設定日数なら対象、それ未満なら対象外。

完了一覧以外の全ステータス許可リストは不要。「その他」等の未設定区分は判定不能。
判定は選択入力・検証済みルール・確定基準日だけを受け取る純粋関数で、通信から分離する。
通信、JSON、ページング、既存extended/JST検証、構造・安全上の長さ違反は全体失敗。
これらを業務上の判定不能へ置き換えない。選択文字列4096文字、custom_fields配列および
選択複数値配列10000要素を上限とし、超過を切り捨てない。custom_fields自体が配列でない場合や
要素が正整数IDを持つobjectでない場合も全体失敗。安全検証は完了行にも適用する。
選択していない項目の値や未知の付随キーは検証・保存対象へ追加しない。

## JSON schema v1

従来のissueキーは維持し、フォロー指定時だけ各issueへ `followup_inputs` と `followup` を追加する。
選択元の入力を計算値で上書きしない。カスタム項目は名前・配列順ではなく設定IDで選ぶ。

```json
{
  "followup_inputs": {
    "status_id": {"state": "value", "value": 1},
    "incident_type": {"custom_field_id": 101, "state": "value", "value": "軽障害"},
    "discovered_on": {"custom_field_id": 102, "state": "value", "value": "2026-07-25"}
  },
  "followup": {
    "as_of": "2026-10-23",
    "threshold_days": 90,
    "elapsed_days": 90,
    "threshold_date": "2026-10-23",
    "target": true,
    "result": "target",
    "reason": "threshold_reached"
  }
}
```

このJSONは架空の説明用断片。status_idは有効な正整数ならvalue、それ以外は
`{"state":"invalid"}`。各カスタム項目はcustom_field_idと次の状態を持つ。

| state | 意味・valueの保存 |
| --- | --- |
| missing | 項目またはvalueキー欠損。valueキーなし |
| null | 明示null。value:nullを保存 |
| empty | 空文字。value:""を保存 |
| value | 単一の非空文字列をそのまま保存。区分未定義・日付不正は判定段階で識別 |
| unsupported | 数値・boolは有限のJSONスカラーとして元型でvalueを保存。object等はvalueキーなし |
| multiple_values | 配列。内容を保存・連結しない（空配列も同じ） |
| duplicate | 選択ID重複。先頭値を採らずvalueキーなし |

配列・object・未知付随キー・未選択CF・完全なissueを保存しない。複数値・重複の個別内容を
復元するschemaではない。カスタム項目名も保存しない。

targetは対象true、対象外false、判定不能null。resultは `target / not_target / indeterminate`。
reasonは次の固定コードで、不明値や例外全文を含めない。

| reason | 意味 |
| --- | --- |
| invalid_status | ステータスID欠損・不正 |
| completed | 現在完了 |
| incident_type_{missing,null,empty,unsupported,multiple_values,duplicate} | 障害区分の入力状態 |
| unknown_incident_type | 日数ルール未定義の区分 |
| discovered_on_{missing,null,empty,unsupported,multiple_values,duplicate} | 発見日の入力状態 |
| discovered_on_invalid_date | 発見日が実在するYYYY-MM-DD以外 |
| discovered_on_future | 発見日が基準日より未来 |
| date_out_of_range | 到達日の演算が日付範囲外 |
| threshold_reached | 設定日数以上経過、現在未完了 |
| below_threshold | 設定日数未到達、現在未完了 |

上から優先して返す。完了/不正statusなら計算欄はnull、区分ルール確定後はthreshold_days、
発見日解析後はelapsed_days（未来日は負数もあり）、到達日計算成功後はthreshold_dateを残す。
未来日では到達日を計算しない。確定できない値はnullで、経過0日は数値0として残す。

## CSV

既存列（basic/JST/extended）の**後**へ固定順で次の9列を追加し、0件も同じヘッダーを出す。

```text
incident_type,discovered_on,followup_as_of,followup_threshold_days,followup_elapsed_days,followup_threshold_date,followup_target,followup_result,followup_reason
```

incident_type/discovered_onは選択文字列（emptyを含む）、unsupported等は空欄。
followup_targetは対象だけ「〇」、それ以外空欄。followup_resultは対象/対象外/判定不能、
followup_reasonは上記コードに対応する固定の日本語説明。未知の区分文字列はincident_typeに残るが
理由へ埋め込まない。未確定の数値・日付は空欄、0は0。全追加文字列にも共通csv_safeを適用し、
UTF-8 BOM、引用符・改行を維持する。JSON原文字列は変更しないため安全化されたCSVとは表現が異なる。

## metadata、識別と公開

従来metadataの意味を維持し、フォロー指定時だけ `metadata.followup` を追加する。
schema_version=1、as_of、timezone（JST固定・暦日・現在状態という説明）、rules_sha256、
input_sha256、counts（target/not_target/indeterminate）を持つ。全3件数合計＝issue_count＝CSV/JSON行数。

rules_sha256は、一度読み込み実際に検証・使用したルールファイルの**生バイト列**のSHA-256。
コメント、改行、空白の変更でも変わる。ルール内容やパス自体はmetadataへ保存しない。
input_sha256は保存済みissue順で組み立てた
`[{"issue_id": issue["id"], "inputs": issue["followup_inputs"]}, ...]` に対し、Pythonの
`json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)`
をUTF-8化したバイト列のSHA-256。0件は同じ方法で `[]` をハッシュする。
保存した許可済み入力だけから再計算でき、元の全応答・未選択データ・APIキー・本文・取得時刻を含めない。
unsupported/duplicate等で破棄した内容の差はこのハッシュで検知できない。
これは同時更新に対するトランザクション保証や承認署名ではない。

同じ選択入力・ルール・基準日なら判定と根拠が一致する。取得時刻・run名の一致は要求しない。
対象外・判定不能も同じissues.csv/issues.jsonへ全件保存する。判定不能があっても両ファイルの
保存に成功すれば終了0で、通常の完了表示に全3件数を表示する。設定・取得・保存失敗は終了2。
`.pending-*` で両ファイル作成後だけ完成runへ一括公開し、途中失敗を公開せず既存runを保持する。

## 手動受入（未実施）

実装・HTTPモック試験の成功はQUICK2実機の受入合格を意味しない。ローカルの承認済み記録に
実施者・条件・コードSHA・時刻・結果を残す。実データをGitHubへ提出する必要はない。

1. 管理者と実フィールドID2つ、完了ステータスID、APIの実区分文字列、型・可視性を確認し、
   ローカルルールを設定する。既存接続configは上書きしない。
2. 閲覧・保存を承認した少数件、親/子project範囲とtrackerを選ぶ。GUIとJSONで発見日・区分・
   現在状態を照合する。発見日とcreated/start/updatedを取り違えない。
3. 同じ明示基準日で89/90/91日、179/180/181日、完了かつ発見日欠損、未来日、未定義区分、
   入力欠損の標本を確認する。90/180日ちょうどの未完了だけ〇、判定不能理由が正しいことを確認する。
4. 今回のrunだけを特定し、CSV/JSONの判定・件数とmetadata合計を照合する。失敗時は過去runを
   今回の出力として扱わない。CSVの文字列保護と0日表示も確認する。
5. Windows Desktop PowerShell 5.1で依存なしハーネス
   `& .\tests\windows\launcher.Tests.ps1` を実行し、Inherit/Systemそれぞれで下の例を試す。
   別cwdからの相対ルールパス、日本語・空白を含むパス、環境変数の復元を確認する。
6. QUICK2の実機結果、Windowsでのmock結果、Linux自動試験結果を分けて記録する。

```powershell
# 架空のパス・project。承認済みの値に置き換える。
& 'C:\ApprovedTools\redmine-readonly\scripts\Invoke-RedmineReadonly.ps1' `
  -Command export -ProxyMode Inherit -Project '123' `
  -OutputDir 'C:\ApprovedData\RedmineExports' `
  -FollowupConfig 'followup-rules.toml' -AsOf '2026-10-23' `
  -Fields extended -IncludeJstColumns
if ($LASTEXITCODE -ne 0) { throw 'export failed; stop before inspection' }
# 組織の接続手順に従い、同じ引数で -ProxyMode System も確認する。
```

## 後続範囲

一般的な変更候補、dry-run変更案、二者レビュー、再取得差分検証は元のPR-2計画に残す。
今回の実装はフォロー判定とローカルレビュー出力に限定する。対象だけの別ファイル、GUI、通知、
ウォッチャー追加、ステータス変更、汎用ルールエンジン、オフライン再判定コマンドは追加しない。
GETはusers/current、issues一覧、既存project確認のみ。個別issue、custom_fields定義、issue_statuses、
新include、POST/PUT/PATCH/DELETE、任意path/methodを追加しない。
