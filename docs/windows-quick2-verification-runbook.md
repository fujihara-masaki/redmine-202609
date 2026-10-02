# Windows 11 QUICK2 読み取り専用確認 runbook

この文書は、承認されたQUICK2環境に対し、Windows 11 / PowerShell / Python
3.12系で読み取り専用CLIを確認する手順である。画面やAPIの実値、URL、APIキー、
project情報、issue情報は、このpublic repository、GitHubのissue/PR、テスト、ログへ
転記しない。コマンド中の例示値は架空であり、実行時は組織の承認済み値に置き換える。

## 1. 初回セットアップ

PowerShellでcloneし、`main` とHEADを記録する。作業開始時点の承認済みcommitかも確認する。

```powershell
git clone <承認済みrepository URL> redmine-readonly
Set-Location redmine-readonly
git switch main
git status --short --branch
git rev-parse HEAD
py -3.12 --version
```

venv activationはExecutionPolicyの影響を受け得るため必須にしない。以降は実行ファイルを
直接指定する。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\python.exe -m compileall -q src tests
Copy-Item config.example.toml config.toml
git check-ignore config.toml
git status --short
```

`git check-ignore` が `config.toml` を表示し、`git status --short` に現れないことを
確認する。APIキーはconfig、CLI引数、PowerShell履歴へ保存しない。CLIがTTYで求める
非表示プロンプトを基本とする。

```powershell
.\.venv\Scripts\redmine-readonly.exe --config config.toml check
```

## 2. PC再起動後・新しいPowerShellでの再開

repositoryと `.venv` が残っていれば、**毎回venvを作り直す必要はない**。ディレクトリへ
移動し、直接 `.venv\Scripts\python.exe` または
`.venv\Scripts\redmine-readonly.exe` を呼ぶ。依存定義またはPython環境を更新した場合だけ、
必要に応じてinstallをやり直す。

PowerShell変数は通常セッションをまたいで永続化されない。既存exportを確認するときも、
新しいセッションごとに承認済みパスを再設定する。

```powershell
Set-Location <repositoryのローカルパス>
$run = "<承認済みrunディレクトリ>"
$data = Get-Content "$run\issues.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$data.metadata
```

`$run`、`$data`、一時的な環境変数はPC再起動やPowerShell終了で失われる。永続化のために
秘密や実データをprofile、script、repositoryへ書き込まない。

## 3. `check`

```powershell
.\.venv\Scripts\redmine-readonly.exe --config config.toml check
# Redmine API key: （非表示で入力）
# OK: authenticated (user_id=<数値>, login=<loginが返る場合のみ>)
```

失敗時は次の順に切り分ける。エラー本文をそのままGitHubへ貼らず、秘密を除いた分類だけを
共有する。

- 401: キーの有効性、入力ミス、対象環境を管理者と確認する。
- 403: ユーザー権限、REST API利用可否、対象範囲を管理者と確認する。
- 404: `base_url` のRedmineサブパスを含む位置を確認する。
- redirect拒否: HTTP/HTTPS、末尾やサブパス、proxyの転送先を確認する。自動追従はしない。
- non-JSON: SSO/login HTMLやproxyエラーの可能性を確認する。
- TLS/CA: 証明書名、有効期限、社内CA bundleの承認済みパス、proxyを確認する。
  `verify=False` による回避はしない。

実URL、APIキー、その一部、レスポンス本文をGitHubへ投稿しない。

## 4. project確認

本手順では対象projectの取り違えを避けるため、まず専用のGETだけを使うコマンドでidentifierと
数値IDの対応を確認し、exportには確認済みの数値IDを使用する。実機確認では、親projectのみの
取得と子projectを含む取得で件数が異なることを確認した。identifier指定の可否は、この確認結果
だけでは判断しておらず、すべてのRedmine環境に共通する挙動とも断定しない。

```powershell
.\.venv\Scripts\redmine-readonly.exe --config config.toml resolve-project --project <承認済みidentifier>
# numeric_project_id: <数値>
# identifier: <identifier>
# name: <名称>
```

出力をrepositoryへ保存しない。以後の `export --project` には確認した数値IDを指定する。

## 5. 0件または小規模projectでのテスト

最初は、閲覧が承認済みで0件または十分小さいprojectを使う。出力先はrepository外とする。

```powershell
$out = "<repository外の承認済み出力先>"
New-Item -ItemType Directory -Force -Path $out | Out-Null
$beforeRuns = @(
  Get-ChildItem $out -Directory -Filter "run-*" |
    Select-Object -ExpandProperty FullName
)
.\.venv\Scripts\redmine-readonly.exe --config config.toml export `
  --project <確認済み数値ID> --output-dir $out
if ($LASTEXITCODE -ne 0) {
  throw "export failed; do not inspect an older run"
}
$afterRuns = @(
  Get-ChildItem $out -Directory -Filter "run-*" |
    Select-Object -ExpandProperty FullName
)
$newRuns = @($afterRuns | Where-Object { $_ -notin $beforeRuns })
if ($newRuns.Count -ne 1) {
  throw "could not uniquely identify the run created by this export"
}
$run = $newRuns[0]
$data = Get-Content "$run\issues.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$data.metadata | Format-List
Get-Item "$run\issues.csv", "$run\issues.json"
```

APIアクセスの成功、CSV/JSON両方の生成、`issue_count`、`pages`、`conditions` を確認する。
BOMなしUTF-8 JSONは必ず `Get-Content -Encoding UTF8` で読む。exportが失敗した場合は停止し、
過去のrunを今回の結果として検証してはならない。前後のrun一覧の差分が一意でない場合も停止する。

## 6. 子project確認

既定では子projectを明示的に除外し、API条件は `subproject_id=!*` となる。
`--include-subprojects` 指定時だけ `subproject_id=*` となる。

GUIの親project画面が子projectのissueも表示していると、既定CLIの結果は0件またはGUIより
少数になり得る。まずJSON/CSVのproject列とGUI側のproject別件数を確認し、承認範囲内で
次を試す。

```powershell
$beforeRuns = @(
  Get-ChildItem $out -Directory -Filter "run-*" |
    Select-Object -ExpandProperty FullName
)
.\.venv\Scripts\redmine-readonly.exe --config config.toml export `
  --project <確認済み数値ID> --include-subprojects --output-dir $out
if ($LASTEXITCODE -ne 0) {
  throw "export failed; do not inspect an older run"
}
$afterRuns = @(
  Get-ChildItem $out -Directory -Filter "run-*" |
    Select-Object -ExpandProperty FullName
)
$newRuns = @($afterRuns | Where-Object { $_ -notin $beforeRuns })
if ($newRuns.Count -ne 1) {
  throw "could not uniquely identify the run created by this export"
}
$run = $newRuns[0]
$data = Get-Content "$run\issues.json" -Raw -Encoding UTF8 | ConvertFrom-Json
```

親・子合計、project別件数、複数ページ時の `pages` をGUIと照合する。GUIの絞り込み条件と
CLIの全status条件が同じかも確認する。

## 7. export後の確認

```powershell
$run = "<承認済みrunディレクトリ>"
$data = Get-Content "$run\issues.json" -Raw -Encoding UTF8 | ConvertFrom-Json

$data.metadata | Format-List
$data.issues | Group-Object { $_.project.name } | Select-Object Name, Count
$data.issues | Group-Object { $_.status.name } | Select-Object Name, Count
$data.issues | Group-Object { $_.tracker.name } | Select-Object Name, Count
($data.issues | Where-Object { $null -eq $_.assigned_to.id }).Count
$data.issues | Select-Object -First 5
$data.issues | Select-Object -Last 5
```

横幅のためプロパティが隠れる場合は、行を限定して縦表示する。

```powershell
$data.issues | Select-Object -First 3 | Format-List *
```

## 8. UTC raw値とJST表示

`created_on` / `updated_on` は監査用にAPIのISO 8601 raw値を保持する。GUIがローカル時間を
表示する場合、見た目が異なっても同じ時刻を指し得る。PowerShellで個別にJSTへ変換する例:

```powershell
$jst = [System.TimeZoneInfo]::FindSystemTimeZoneById("Tokyo Standard Time")
$raw = [DateTimeOffset]::Parse($data.issues[0].created_on)
[System.TimeZoneInfo]::ConvertTime($raw, $jst).ToString("yyyy-MM-dd HH:mm:ss zzz")
```

CLIで比較用列が必要な場合だけ `--include-jst-columns` を付ける。raw列を置換せず、JSONと
CSVへ `created_on_jst` / `updated_on_jst` (`YYYY-MM-DD HH:MM:SS +09:00`) を追加する。

```powershell
$beforeRuns = @(
  Get-ChildItem $out -Directory -Filter "run-*" |
    Select-Object -ExpandProperty FullName
)
.\.venv\Scripts\redmine-readonly.exe --config config.toml export `
  --project <確認済み数値ID> --include-jst-columns --output-dir $out
if ($LASTEXITCODE -ne 0) {
  throw "export failed; do not inspect an older run"
}
$afterRuns = @(
  Get-ChildItem $out -Directory -Filter "run-*" |
    Select-Object -ExpandProperty FullName
)
$newRuns = @($afterRuns | Where-Object { $_ -notin $beforeRuns })
if ($newRuns.Count -ne 1) {
  throw "could not uniquely identify the run created by this export"
}
$run = $newRuns[0]
$data = Get-Content "$run\issues.json" -Raw -Encoding UTF8 | ConvertFrom-Json
```

## 9. PR-1.2更新後のextended少数件確認

既存利用者は作業場所と未整理変更を先に確認し、変更があれば更新せず整理担当へ相談する。
既存venvを作り直さず、接続確認済み `config.toml` をひな型で上書きしない。

```powershell
Set-Location <repositoryのローカルパス>
git status --short --branch
if (git status --porcelain) { throw "uncommitted changes: stop before update" }
git switch main
git pull --ff-only
git status --short --branch
# pyproject.toml等が更新され、必要な場合だけ依存を更新する。
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest
if ($LASTEXITCODE -ne 0) { throw "local tests failed; do not access QUICK2" }
```

次は完全な架空値である。`Read-Host "..."` の引用文字列はprompt表示であって値ではないため、ここでは
誤認しにくい直接代入を示す。実行前に承認済み数値project IDとrepository外の保存先へ置き換え、
対象範囲、author等の追加情報の保存、アクセス制御・保持期限の承認を確認する。

```powershell
# 例示値。実行前に承認済みの値へ置き換える。
$projectId = "123"
$out = "C:\ApprovedData\RedmineExports"
$beforeRuns = @(Get-ChildItem -LiteralPath $out -Directory -Filter "run-*" -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty FullName)

.\.venv\Scripts\redmine-readonly.exe `
  --config .\config.toml `
  export `
  --project $projectId `
  --include-subprojects `
  --fields extended `
  --include-jst-columns `
  --output-dir $out
$exportExit = $LASTEXITCODE
if ($exportExit -ne 0) { throw "export failed; do not inspect an older run" }

$afterRuns = @(Get-ChildItem -LiteralPath $out -Directory -Filter "run-*" -ErrorAction Stop |
  Select-Object -ExpandProperty FullName)
$newRuns = @($afterRuns | Where-Object { $_ -notin $beforeRuns })
if ($newRuns.Count -ne 1) { throw "could not uniquely identify this export run" }
$run = $newRuns[0]
Remove-Variable data -ErrorAction SilentlyContinue
try {
  $jsonText = Get-Content -LiteralPath (Join-Path $run "issues.json") -Raw -Encoding UTF8 -ErrorAction Stop
  $data = $jsonText | ConvertFrom-Json -ErrorAction Stop
} catch {
  throw "JSON read/parse failed; stop before counts or GUI comparison"
}
```

0件、全欠損、一部/全部の非null返却を混同しない。`value_count` は非null応答数（空の日付文字列を含む）で
「業務値が設定済み」の件数ではない。missingの原因も推測しない。集計自体をpublic GitHubへ貼らない。

```powershell
if ($data.metadata.field_profile -ne "extended") { throw "unexpected field profile" }
$data.metadata.issue_count
$data.metadata.extended_field_availability.PSObject.Properties | ForEach-Object {
  $counts = $_.Value
  [PSCustomObject]@{
    Field = $_.Name
    Missing = $counts.missing_count
    Null = $counts.null_count
    Value = $counts.value_count
    TotalMatches = (($counts.missing_count + $counts.null_count + $counts.value_count) -eq $data.metadata.issue_count)
  }
} | Format-Table -AutoSize
```

返却されたfieldだけ承認済み少数件でGUIと照合する。取得が完了したことと、値の業務的妥当性確認は
別に記録する。`created_on_jst` / `updated_on_jst` はraw日時の比較表示だが、`start_date` / `due_date`
は日付だけでJST変換対象ではない。basicとextendedを別時刻に実行すると同時更新・増減があり得るため、
過去の固定件数を無条件の期待値にせず、比較時刻と検索条件を確認する。QUICK2 extended確認は本PR時点で
未実施である。

## 10. 終了・情報管理

APIキーはファイルへ保存せず、環境変数を一時利用した場合は削除する。exportはrepository外の
承認済み・アクセス制御済みの場所だけに置き、実データ、スクリーンショット、一時検証scriptを
commitしない。

```powershell
Remove-Item Env:REDMINE_API_KEY -ErrorAction SilentlyContinue
git status --short
```

最後の出力が空であることを確認する。意図しないファイルがあれば、内容をGitHubへ送る前に
ローカルで安全に除去する。
