# Windows 11 QUICK2 読み取り専用確認 runbook

この文書は、承認されたQUICK2環境に対し、Windows 11 / PowerShell / Python
3.12系で読み取り専用CLIを確認する手順である。画面やAPIの実値、URL、APIキー、
project情報、issue情報は、このpublic repository、GitHubのissue/PR、テスト、ログへ
転記しない。コマンド中の例示値は架空であり、実行時は組織の承認済み値に置き換える。

日常の起動・VPN接続後のSystem指定・ExecutionPolicy・終了コードは
[Windows起動補助の手順](windows-proxy-launcher.md) を参照する。正式対応はPowerShell 5.1。
利用者の既存CLIでは手動プロキシ指定で認証・extended出力・GUI照合の成功が報告された。
今回の新しい起動補助でのQUICK2実機確認は未実施である。

## 1. 初回セットアップ

PowerShellでcloneし、`main` とHEADを記録する。作業開始時点の承認済みcommitかも確認する。

```powershell
git clone <承認済みrepository URL> redmine-readonly
if ($LASTEXITCODE -ne 0) { throw "setup check failed; stop" }
Set-Location -LiteralPath redmine-readonly -ErrorAction Stop
git switch main
if ($LASTEXITCODE -ne 0) { throw "setup check failed; stop" }
git status --short --branch
if ($LASTEXITCODE -ne 0) { throw "setup check failed; stop" }
git rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw "setup check failed; stop" }
py -3.12 --version
if ($LASTEXITCODE -ne 0) { throw "setup check failed; stop" }
```

venv activationはExecutionPolicyの影響を受け得るため必須にしない。以降は実行ファイルを
直接指定する。

```powershell
py -3.12 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "setup check failed; stop" }
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
if ($LASTEXITCODE -ne 0) { throw "setup check failed; stop" }
.\.venv\Scripts\python.exe -m pytest
if ($LASTEXITCODE -ne 0) { throw "setup check failed; stop" }
.\.venv\Scripts\ruff.exe check .
if ($LASTEXITCODE -ne 0) { throw "setup check failed; stop" }
.\.venv\Scripts\ruff.exe format --check .
if ($LASTEXITCODE -ne 0) { throw "setup check failed; stop" }
.\.venv\Scripts\python.exe -m compileall -q src tests
if ($LASTEXITCODE -ne 0) { throw "setup check failed; stop" }
if (Test-Path -LiteralPath config.toml) { throw "config already exists; do not overwrite" }
Copy-Item -LiteralPath config.example.toml -Destination config.toml -ErrorAction Stop
git check-ignore config.toml
git status --short
if ($LASTEXITCODE -ne 0) { throw "setup check failed; stop" }
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
Remove-Variable data -ErrorAction SilentlyContinue
$data = Get-Content -LiteralPath "$run\issues.json" -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
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
New-Item -ItemType Directory -Force -Path $out -ErrorAction Stop | Out-Null
.\.venv\Scripts\redmine-readonly.exe --config config.toml export `
  --project <確認済み数値ID> --output-dir $out
if ($LASTEXITCODE -ne 0) {
  throw "export failed; do not inspect an older run"
}
$jsonPath = '<今回成功時にCLIが表示したJSONパス>'
$run = Split-Path -Parent $jsonPath
Remove-Variable data -ErrorAction SilentlyContinue
$data = Get-Content -LiteralPath "$run\issues.json" -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
$data.metadata | Format-List
Get-Item -LiteralPath "$run\issues.csv", "$run\issues.json" -ErrorAction Stop
```

APIアクセスの成功、CSV/JSON両方の生成、`issue_count`、`pages`、`conditions` を確認する。
BOMなしUTF-8 JSONは必ず `Get-Content -Encoding UTF8` で読む。exportが失敗した場合は停止し、
過去のrunを今回の結果として検証してはならない。今回表示されたJSONパスを明示する。ファイル確認の失敗はAPI export成功とは別に扱う。

## 6. 子project確認

既定では子projectを明示的に除外し、API条件は `subproject_id=!*` となる。
`--include-subprojects` 指定時だけ `subproject_id=*` となる。

GUIの親project画面が子projectのissueも表示していると、既定CLIの結果は0件またはGUIより
少数になり得る。まずJSON/CSVのproject列とGUI側のproject別件数を確認し、承認範囲内で
次を試す。

```powershell
.\.venv\Scripts\redmine-readonly.exe --config config.toml export `
  --project <確認済み数値ID> --include-subprojects --output-dir $out
if ($LASTEXITCODE -ne 0) {
  throw "export failed; do not inspect an older run"
}
$jsonPath = '<今回成功時にCLIが表示したJSONパス>'
$run = Split-Path -Parent $jsonPath
Remove-Variable data -ErrorAction SilentlyContinue
$data = Get-Content -LiteralPath "$run\issues.json" -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
```

親・子合計、project別件数、複数ページ時の `pages` をGUIと照合する。GUIの絞り込み条件と
CLIの全status条件が同じかも確認する。

## 7. export後の確認

```powershell
$run = "<承認済みrunディレクトリ>"
Remove-Variable data -ErrorAction SilentlyContinue
$data = Get-Content -LiteralPath "$run\issues.json" -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop

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
.\.venv\Scripts\redmine-readonly.exe --config config.toml export `
  --project <確認済み数値ID> --include-jst-columns --output-dir $out
if ($LASTEXITCODE -ne 0) {
  throw "export failed; do not inspect an older run"
}
$jsonPath = '<今回成功時にCLIが表示したJSONパス>'
$run = Split-Path -Parent $jsonPath
Remove-Variable data -ErrorAction SilentlyContinue
$data = Get-Content -LiteralPath "$run\issues.json" -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
```

## 9. コード更新後のextended少数件確認

既存利用者は作業場所と未整理変更を先に確認し、変更があれば更新せず整理担当へ相談する。
既存venvを作り直さず、接続確認済み `config.toml` をひな型で上書きしない。

```powershell
# 例示値。実際のrepositoryのローカルパスへ置き換える。
$repo = "C:\ApprovedTools\redmine-readonly"
Set-Location -LiteralPath $repo -ErrorAction Stop
$worktree = @(git status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "git status failed; stop before update" }
git status --short --branch
if ($LASTEXITCODE -ne 0) { throw "git status failed; stop before update" }
if ($worktree.Count -ne 0) { throw "uncommitted changes: stop before update" }
git switch main
if ($LASTEXITCODE -ne 0) { throw "git switch main failed; stop before update" }
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw "git pull --ff-only failed; do not test or access QUICK2" }
git status --short --branch
if ($LASTEXITCODE -ne 0) { throw "git status after update failed; stop" }
$updatedBranch = git branch --show-current
if ($LASTEXITCODE -ne 0) { throw "could not record updated branch; stop" }
$updatedHead = git rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw "could not record updated HEAD; stop" }
"Updated branch: $updatedBranch"
"Updated HEAD: $updatedHead"

# 更新内容を確認し、pyproject.toml等の依存定義が変わった場合だけtrueにする。
$updateDependencies = $false
if ($updateDependencies) {
  .\.venv\Scripts\python.exe -m pip install -e ".[test]"
  if ($LASTEXITCODE -ne 0) { throw "dependency update failed; do not access QUICK2" }
}

# pip installの要否にかかわらず、既存venvで以下をすべて実行する。
.\.venv\Scripts\python.exe -m pytest
if ($LASTEXITCODE -ne 0) { throw "local tests failed; do not access QUICK2" }
.\.venv\Scripts\ruff.exe check .
if ($LASTEXITCODE -ne 0) { throw "Ruff check failed; do not access QUICK2" }
.\.venv\Scripts\ruff.exe format --check .
if ($LASTEXITCODE -ne 0) { throw "Ruff format check failed; do not access QUICK2" }
.\.venv\Scripts\python.exe -m compileall -q src tests
if ($LASTEXITCODE -ne 0) { throw "compileall failed; do not access QUICK2" }
```

上のpip installは常時実行する指示ではない。更新前後の依存定義を確認し、依存更新が必要な場合だけ
実行するコマンド例である。不要ならその2行を飛ばし、既存venvをそのまま使う。どのnative commandも
直後の `$LASTEXITCODE` を確認し、失敗を後続commandの成功で上書きしない。いずれかが失敗した場合は
そこで停止し、接続確認やexportへ進まない。接続確認済み `config.toml` はコピー・再作成しない。

依存更新・検査が成功したら、[起動補助手順のexport例](windows-proxy-launcher.md)を使う。
VPN接続状態を整え、承認済み数値project ID・repository外の保存先・extended保存の承認を確認する。
成功時に表示された今回のJSONパスを明示し、古いdataをクリアしてUTF8で読む。
wrapperは呼び出し元のrun/dataを更新しない。失敗時は照合へ進まない。

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
過去の固定件数を無条件の期待値にせず、比較時刻と検索条件を確認する。利用者の既存CLIの
extended成功報告と、今回wrapperの未実施の実機確認は区別する。

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
