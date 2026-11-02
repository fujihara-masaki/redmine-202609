# Redmine read-only issue exporter

Redmine REST APIを使い、指定プロジェクトのチケット一覧をCSV/JSONへ保存する、障害管理業務向けの読み取り専用CLIです。認証確認、project確認、一覧出力だけを提供します。対象環境のRedmineバージョン、独自改修、権限、公開API、カスタム項目は、実機で確認した範囲を除き**未確認**です。

## 安全上の境界

- 実装済みAPIは `GET /users/current.json`、`GET /issues.json`、`GET /projects/{id_or_identifier}.json` だけです。変更、作成、削除、コメント、ウォッチャー操作、任意パス実行はありません。
- APIキーは `REDMINE_API_KEY` または非表示プロンプトからだけ取得し、引数・URL・TOMLには保存しません。送信先は `X-Redmine-API-Key` ヘッダーです。
- CLIがGET専用でも、**APIキー自体のRedmine上の権限は縮小されません**。専用ユーザー、最小権限、対象プロジェクトの制限は管理者が行ってください。
- HTTPSと証明書検証を必須とし、リダイレクトには追従しません。エラーにレスポンス本文、ヘッダー、キーを表示しません。
- 公開リポジトリです。実URL、キー、社内チケット、実レスポンス、ログ、エクスポートをコミットしないでください。

## 必要環境とインストール

Python 3.11以上、`requests >=2.31,<3` を使用します。テストは `pytest >=8,<9` です。

### Windows PowerShell 5.1

初回導入・再起動・コード更新・GUI照合は
[Windows 11 QUICK2確認runbook](docs/windows-quick2-verification-runbook.md)、
日常起動とVPN接続後の明示的なSystemプロキシ選択は
[Windows起動補助の手順](docs/windows-proxy-launcher.md) を使用してください。

```powershell
& .\scripts\Invoke-RedmineReadonly.ps1 -Command check -ProxyMode Inherit
$checkExit = $LASTEXITCODE
if ($checkExit -ne 0) { throw "check failed; stop" }
```

Inheritは従来のRequests設定を保持します。Systemを明示した場合だけ、対象API URLの
Windows/.NET選択とRequestsの実効選択をキー入力前に照合します。プロキシは実行中だけ設定・復元し、
OSや永続環境は変更しません。wrapperは配置場所のvenv/configを選びます。
activateは不要ですが、.ps1の実行ポリシーは適用されるため会社の署名・配布方針に従ってください。

出力先はrepository外の、承認されたアクセス制御・保管期限・バックアップ方針を持つフォルダを指定します。

## 設定とネットワーク

`config.example.toml` をローカルの `config.toml` にコピーします。`base_url` はサブパス（例: `/redmine`）を含められ、API URLでも保持されます。URLのユーザー情報、クエリ、フラグメント、HTTPは拒否します。

社内CAはPEMファイルの承認済みパスを `ca_bundle` に設定します。検証無効化の設定はありません。プロキシはrequests標準の `HTTPS_PROXY` と、必要なら `NO_PROXY` 環境変数を利用します。プロキシURLに認証情報を直接残す運用は避け、組織の資格情報管理手順に従ってください。

VPN接続後にシステム側の選択を使う場合は、上記起動補助手順のSystemを明示してください。
NO_PROXY等と選択が競合すれば停止し、設定を勝手に解除しません。

## コマンド

`check` は設定検証後に現在ユーザーを確認し、成功可否、ユーザーID、存在する場合だけloginを表示します。メールや全レスポンスは表示・保存しません。

`resolve-project` は一時scriptや任意API呼び出しを使わず、identifierまたは数値IDに対応する
最小限のproject情報（数値ID、identifier、name）だけを表示します。

```powershell
.\.venv\Scripts\redmine-readonly.exe --config config.toml resolve-project --project sample-project
```

本手順では対象projectの取り違えを避けるため、`resolve-project` でidentifierと数値IDの対応を
確認し、その数値IDを `export --project` に指定します。実機確認では、親projectのみの取得と
子projectを含む取得で件数が異なることを確認しました。identifier指定の可否は、この確認結果
だけでは判断しておらず、すべてのRedmine環境に共通する挙動とも断定しません。

`export` の `--project` と `--output-dir` は必須です。既定条件は全ステータス (`--status '*'` / `status_id=*`、完了を含む)、子プロジェクト除外 (`subproject_id=!*`)、ID昇順です。対象環境で確認済みのステータスID等に限定する場合は `--status`、子プロジェクトを含めるには `--include-subprojects`、トラッカー絞り込みには数値IDの `--tracker` を明示します。

指定した出力先の下に、実行ごとの一意な `run-<UTC日時>-<ランダムID>` ディレクトリを作り、その中へ `issues.csv` と `issues.json` をまとめます。最初は同じ出力先内の未完成を示す `.pending-*` ディレクトリへ両方を書き込み、両方が成功した後だけ完成runとして名前を変更します。このため途中失敗を完成runとして公開せず、同時実行や既存runとのファイル混在・上書きを避けます。失敗した一時ディレクトリは削除されます。

JSONは開始・終了日時、抽出条件、件数、ページ数と選択項目の元のJSON型を保持します。CSVはUTF-8 BOM付きで、未設定値、カンマ、引用符、改行、日本語をCSV規則で扱います。Excelの数式注入対策として、空白類に続く `=`, `+`, `-`, `@` で始まる**文字列**には先頭へ `'` を追加します。このためCSV上の値は変化します。表計算ソフトやインポート機能ごとの差、別の危険な解釈を完全には防げないため、信頼できない値を含むファイルを開く際は保護ビュー等も使用してください。JSONは変更しません。

`created_on` / `updated_on` は常にAPIのraw ISO 8601値を保持します。
`--include-jst-columns` を明示した場合だけ、比較表示用の `created_on_jst` /
`updated_on_jst` (`UTC+09:00`) をCSVとJSONへ追加します。raw列は置換しません。flagなしの
basic schemaは従来どおりです。

### 出力field profile

`export --fields basic|extended` はローカルの出力選択で、既定は従来互換の `basic` です。
`extended` は、承認済みの対象・保存先について利用者が明示的に選ぶopt-inです。author等は
個人を識別し得て、category/fixed_versionのnameも業務情報になり得ます。

`extended` はbasicに `priority`, `author`, `category`, `fixed_version`, `parent`,
`start_date`, `due_date`, `done_ratio`, `estimated_hours`, `is_private` の固定10項目だけを
追加します。APIにないキーはJSONでも省略し、明示nullはnull、0/0.0/false/日付の空文字は
値として保持します。CSVでは欠損・null・空文字はいずれも空欄になり得るため、区別にはJSONを
使います。`--include-jst-columns` は独立して併用でき、日付だけのstart/due dateはJST変換しません。

extended CSVは既存12列（JST指定時は直後に既存2列）の後へ、`priority_id`,
`priority_name`, `author_id`, `author_name`, `category_id`, `category_name`,
`fixed_version_id`, `fixed_version_name`, `parent_id`, `start_date`, `due_date`,
`done_ratio`, `estimated_hours`, `is_private` の順で追加します。0件でも26列（JST併用は28列）です。
JSON metadataにはprofile/schema、固定選択項目、各項目のmissing/null/value件数だけを追加します。
valueは「非nullで検証に合格した応答」であり、業務上設定済みという意味ではありません。
返らない値の原因を推測・補完せず、0件から対象環境の対応有無を判断しません。

この切替は `/issues.json` の検索条件、呼出回数、includeを変更しません。API応答自体には保存対象外の
情報が含まれ得ます。description、journals等、個別issue取得は引き続き対象外です。
カスタム項目は、次のフォロー指定時だけ設定した2項目を限定選択します。

### PR-2: フォロー判定・ローカルレビュー出力

`export --followup-config followup-rules.toml` を明示した場合だけ、障害区分と**発見日**から
全行を判定します。発見日は障害を検知・発見した日付で、created_on等で代用しません。
「〇」は設定日数以上が発見日から経過し、現在未完了の意味です。非影響・軽障害90日、
中障害・重障害180日が初期例で、90/180日ちょうどから対象です。
期限違反、承認不備、完了への変更可否は判定しません。月次判定とは異なる暦日の日数判定です。

接続configと別の `followup-rules.example.toml` を `followup-rules.toml` にコピーし、
実フィールドID2つ、完了ID、APIの正確な区分値をローカル設定します。101、102、5は仮のIDです。
実ルールはGit対象外の `followup*.toml` またはrepository外へ置きます。
`--as-of YYYY-MM-DD` はフォロー指定時だけ使用でき、省略時は実行開始時のJST当日で固定します。
過去基準日も取得した現在状態についての計算で、過去の状態復元ではありません。
フォロー指定時のstatusは `*` のみ。basic/extended、JST列、tracker/子project指定と併用できます。

```powershell
.\.venv\Scripts\redmine-readonly.exe --config config.toml export `
  --project 123 --output-dir 'C:\ApprovedData\RedmineExports' `
  --followup-config followup-rules.toml --as-of 2026-10-23

& .\scripts\Invoke-RedmineReadonly.ps1 -Command export -ProxyMode Inherit `
  -Project '123' -OutputDir 'C:\ApprovedData\RedmineExports' `
  -FollowupConfig 'followup-rules.toml' -AsOf '2026-10-23'
if ($LASTEXITCODE -ne 0) { throw 'export failed; stop before inspection' }
```

上は架空値です。Pythonの相対ルールパスはcwd基準、Windows起動補助はrepository基準です。
全行を同じCSV/JSONへ保存し、対象外・判定不能も落としません。判定不能があっても正常保存なら終了0、
完了表示に全3件数を表示します。設定・取得・保存失敗は終了2、完成runへの一括公開は従来どおりです。
完了行は発見日欠損でも対象外を優先し、未完了の未定義区分や不正入力は理由付き判定不能です。
入力と派生結果、固定CSV9列、ハッシュ仕様、優先順位と手動受入は
[フォローschema・受入手順](docs/followup.md)を参照してください。

ページングでは `limit`, `offset`, `total_count` を検査し、サーバーが要求より少ないページを返しても実返却数で進めます。重複ID、件数変化、早すぎる空ページ、offset不一致、途中失敗、上限到達時は完成出力を書きません。ただし件数一致は取得中の同時更新を含むトランザクション的な完全スナップショットを保証しません。

## 標準仕様と実環境確認

標準Redmine REST APIのうち、「安全上の境界」に列挙した3種類のGETエンドポイントと、issuesのフィルター・ページングを前提にしています。一方、対象環境のバージョンや改修により、利用可否、フィルター構文、上限、返却項目、権限挙動が異なる可能性があります。`docs/quick2-verification-checklist.md` に従い確認してください。

標準10項目とフォロー用2項目以外のカスタム項目や本文は後続範囲です。段階案は
[export項目の拡張設計](docs/export-field-expansion-design.md)を参照してください。
利用者から既存CLIの手動プロキシ指定でextended取得・GUI照合成功の報告があります。
フォローの実ID・実区分値・QUICK2実機受入は未確認です。実装とHTTPモック試験の完了は、
実機受入合格を意味しません。GUI照合は利用者がローカルで実施します。

## 開発

```bash
python -m pip install -e '.[test]'
python -m pytest
```

テストは偽セッションだけを使い、実環境へ接続しません。今後の計画と非対象範囲は `docs/implementation-plan.md` を参照してください。
