# Windows PowerShell 5.1 起動補助とVPN接続後の手順

正式な対象はWindows PowerShell 5.1。PowerShell 7の実行結果は5.1の検証結果と区別する。
初回導入・コード更新・GUI照合は[既存runbook](windows-quick2-verification-runbook.md)を参照する。
日常起動は `scripts/Invoke-RedmineReadonly.ps1` を `&` で呼ぶ。dot-sourceしない。

## 初回・再起動・更新の違い

初回だけvenvを作り、依存を導入し、存在しないconfigをひな型から作る。PC再起動後も
既存venvと接続確認済みconfigを使用する。configを再コピー・上書きしない。
コード更新はrunbookの停止条件付きgit/依存/テスト手順で行う。起動補助は自動git pull、
pip install、テスト、venv activation、config作成を実行しない。

wrapperは自分の配置場所からrepositoryを確定し、そこの `.venv\Scripts\python.exe` と
`config.toml` を使う。カレントディレクトリの別venv/configやグローバルPythonへは切り替えない。
明示した `ConfigPath` の相対パスもrepository基準。絶対パスも使用できる。
カレントディレクトリは変更しない。`OutputDir` は空でない絶対パスでrepository外を指定する。
日本語、空白、丸括弧、末尾区切りを含むパスはnative引数へ渡す前に正規化する。
exportのprojectには確認済み数値IDを推奨する。project要素は既存resolveと同じ検証に限定する。

venvをactivateしなくても **.ps1にはExecutionPolicyが適用される**。

```powershell
Get-ExecutionPolicy -List
$PSVersionTable.PSVersion
```

会社の署名、実行許可、配布方針に従う。実行できなければ管理者に署名や配布方法を確認する。
管理ポリシーを迂回する起動方法やExecutionPolicy Bypass/Unrestrictedを標準手順にしない。

## モードと日常実行

`Inherit` が既定。プロキシ環境を変更せず、PACを追加評価せず、従来のRequests選択を使う。
**直接接続の強制ではない**。失敗しても自動でSystemへ切り替えない。

`System` は明示時だけ。VPNなどの接続状態を整えてから実行し、一回の実行中はネットワークと
configを変更しない。各起動のコマンドに応じてWindows/.NETの `GetSystemWebProxy().GetProxy()` を
評価する。checkはusers/current、exportはissues、resolve-projectは対象projectのURLで、
Redmineサブパスを維持する。checkで選んだプロキシをexportへ使い回さない。

```powershell
& .\scripts\Invoke-RedmineReadonly.ps1 -Command check -ProxyMode Inherit
$checkExit = $LASTEXITCODE
if ($checkExit -ne 0) { throw "check failed; stop" }

& .\scripts\Invoke-RedmineReadonly.ps1 -Command check -ProxyMode System
$checkExit = $LASTEXITCODE
if ($checkExit -ne 0) { throw "check failed; stop" }

# 完全な架空値。承認済み対象へ置き換える。
& .\scripts\Invoke-RedmineReadonly.ps1 -Command resolve-project -ProxyMode System -Project sample-project
$resolveExit = $LASTEXITCODE
if ($resolveExit -ne 0) { throw "resolve failed; stop before export" }

# 別ディレクトリからも、このrepositoryのvenv/configを使う。
& 'C:\ApprovedTools\redmine-readonly\scripts\Invoke-RedmineReadonly.ps1' -Command check -ProxyMode System
$checkExit = $LASTEXITCODE
if ($checkExit -ne 0) { throw "check failed; stop" }
```

APIキー入力は既存CLIの非表示プロンプトまたは既存環境変数方式を使う。
wrapper/helperはAPIキーを読み取らず、引数・ファイル・ログへ転記しない。

```powershell
# 完全な架空値。実行前に承認済みの対象・保存先へ置き換える。
$options = @{
    Command            = 'export'
    ProxyMode          = 'System'
    Project            = '123'
    OutputDir          = 'C:\ApprovedData\RedmineExports'
    Fields             = 'extended'
    IncludeSubprojects = $true
    IncludeJstColumns  = $true
    Status             = '*'
    # Tracker          = 2  # 必要時だけ承認済み数値IDを指定
}
& .\scripts\Invoke-RedmineReadonly.ps1 @options
$exportExit = $LASTEXITCODE
if ($exportExit -ne 0) {
    throw '実行に失敗しました。結果の照合には進まないでください'
}
```

`Command` はcheck / resolve-project / export、`ProxyMode` はInherit / System、
`Fields` はbasic / extended（既定basic）。Projectは後二者で必須、OutputDirはexportで必須。
Fields、OutputDir、Status、Tracker、二つのIncludeスイッチはexportだけで使う。
Statusは既定 `*`、Trackerは省略可能な正整数。checkへProject、他コマンドへexport専用引数を
明示すると停止する。APIキー、URL、PAC、プロキシURI、任意実行先・任意CLI引数のパラメータはない。

## 判定・競合・終了コード

| システム判定 | 起動前の照合 |
| --- | --- |
| PROXY | 絶対HTTP/HTTPS URI、ホスト・ポート、userinfo/query/fragment/制御文字/不要pathがないことを検証し、HTTPS_PROXYへ一時指定。そのvenvのRequestsが選ぶプロキシとの一致を要求 |
| DIRECT | Requestsも対象URLにプロキシを選ばないことを要求。既存設定と競合すれば停止 |
| null・例外・不正・非対応 | 判定失敗として停止。DIRECTへ置き換えない |

RequestsのSessionの環境設定取得・select_proxyを内部helperで再利用する。独自NO_PROXYパーサーは
使わない。NO_PROXY、ALL_PROXY、HTTP_PROXY、HTTPS_PROXY、大文字/小文字、Windows側の設定取得の
影響は実効選択で照合する。NO_PROXYを削除・設定せず、全プロキシを一括解除せず、trust_envや
CA設定を変えない。HTTPプロキシをHTTPSプロキシへ書き換えず、loopbackだけで可否を決めない。

方式Bを採用し、現在のPowerShell **Process** のHTTPS_PROXYだけを一時設定してtry/finallyで
元の存在状態と値へ戻す。固定Pythonと固定構造の引数配列をProcessStartInfoへ渡し、3つのコンソールハンドルを
継承して非表示入力を継続するため。.NET Framework用に各引数をWindows CRT規則でquoteし、
command shellは介さない。
User/Machine環境変数、Windowsプロキシ設定、レジストリ、VPN、Zscalerは変更しない。
実行中は同じPowerShellから他の処理を並行起動しない。捕捉できる例外・中断でも復元を試みるが、
強制終了やOS障害までfinallyの完了を保証しない。復元失敗は値を表示しない警告で通知する。

| 終了コード | 意味 |
| --- | --- |
| 既存CLIのコード | 実行直後のコードを保持。CLI失敗をcleanup成功で0へ変えない |
| 3 | wrapper入力・セットアップ・判定・整合性・起動の失敗。API実行へ進まない |
| 4 | cleanup失敗。CLIも非0ならそのCLIコードを優先し、cleanup警告を併記 |

PowerShellの引数bindingや実行ポリシーによる拒否は、wrapper本体へ入る前のPowerShellエラーである。
事前確認はURL/config path/proxy URIやhelper例外全文を表示しない。診断はモード、DIRECT/PROXY、
固定エラー分類だけ。既存CLIの認証ユーザー、project、成功時のファイルパス表示は維持し、
別ログへ複製しない。直接接続や別プロキシへの自動再試行はない。

認証、CAエラー、設定競合は管理者へ確認する。APIキー、実URL、PAC URL、実プロキシアドレスや
実データをGitHubへ貼らない。Zscaler停止、VPNルート変更、証明書検証無効化を対処方法にしない。
プロキシ資格情報の保存・Windows資格情報の新しい自動送信・NTLM/Kerberosライブラリは対象外。

## 今回の結果の読み込み

wrapperは呼び出し元の `$run` / `$data` を更新せず、結果を開かない。
export失敗時は停止する。成功時にCLIが表示した **今回のJSONパス** を明示指定する。
更新日時順で最新runを選ばない。新しいPowerShellセッションでは変数を再設定する。

```powershell
# 今回成功時のJSON: 表示のパスに置き換える（例は架空）。
$jsonPath = 'C:\ApprovedData\RedmineExports\run-example\issues.json'
Remove-Variable data -ErrorAction SilentlyContinue
try {
    $jsonText = Get-Content -LiteralPath $jsonPath -Raw -Encoding UTF8 -ErrorAction Stop
    $data = $jsonText | ConvertFrom-Json -ErrorAction Stop
    $run = Split-Path -Parent $jsonPath
    Get-Item -LiteralPath (Join-Path $run 'issues.csv'), $jsonPath -ErrorAction Stop
} catch {
    throw 'export成功後のファイル確認に失敗。件数・GUI照合には進まないでください'
}
$data.metadata
```

CSV/JSON生成、basic/extended、JST、上限、ページング、run公開は従来CLIに委譲する。
新しい出力ファイルや成功runは作らない。GUI照合はrunbookの条件・型・件数の確認に進む。

## 根拠・限界・検証

利用者の既存CLIでの報告では、VPN接続中にRequestsがプロキシを選ばずtimeoutとなり、
Windows/.NETが対象URLに選んだプロキシを手動で一時指定するとcheckとextended/JST/子project包含の
exportが成功し、CSV/JSON・GUI照合も確認された。これは今回の新スクリプトの実機確認ではない。
VPN製品/Zscalerの不具合、常にプロキシ必須、別ネットワークへの同一設定適用は断定しない。

OSによるPAC取得・評価、DNS通信が起きる場合がある。System事前確認は完全オフラインではなく、
Requests timeoutはPAC評価全体の時間上限ではない。helper自体はHTTP要求を送信しない。
ブラウザとの完全一致、PAC全候補・failover、実行中VPN切替、複雑なURL/queryごとのルール、
すべてのVPN/Zscaler構成は保証しない。リクエストごとの判定が必要なPACは別途設計対象。

追加PythonテストはHTTPを拒否してURL・URI・Requests実効選択を検査する。
`tests/windows/launcher.Tests.ps1` は追加依存なし。Windows CIでは `shell: powershell` で
Desktop 5.1を要求して実スクリプト/内部関数を実行し、件数不足やskipだけの成功を拒否する。
CIの一時venvは導入済みpackage/Requestsを再利用し、fixture内だけのsource参照を設定する。
テスト中の追加pip installやネットワーク取得は不要で、利用者の起動時依存も増やさない。
PACと本体CLIを架空境界へ差し替え、専用子プロセスで実引数・環境・stdout/stderr・復元・終了を検査する。

```powershell
& .\tests\windows\launcher.Tests.ps1
if (-not $?) { throw 'Windows launcher tests failed' }
```

QUICK2実機確認は未実施。マージ後は承認済み少数件で、5.1の対話コンソールでのgetpass、
本物のCtrl+C、実際のPAC/CA/プロキシ認証条件、実行後の復元を確認する。
模擬中断やfake CLIの成功を、それらの実機確認の代わりにしない。
