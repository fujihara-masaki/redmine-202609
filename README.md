# Redmine read-only issue exporter

Redmine REST APIを使い、指定プロジェクトのチケット一覧をCSV/JSONへ保存する、障害管理業務向けの読み取り専用CLIです。PR-1では認証確認と一覧出力だけを提供します。対象環境のRedmineバージョン、独自改修、権限、公開API、カスタム項目は**未確認**です。

## 安全上の境界

- 実装済みAPIは `GET /users/current.json` と `GET /issues.json` だけです。変更、作成、削除、コメント、ウォッチャー操作、任意パス実行はありません。
- APIキーは `REDMINE_API_KEY` または非表示プロンプトからだけ取得し、引数・URL・TOMLには保存しません。送信先は `X-Redmine-API-Key` ヘッダーです。
- CLIがGET専用でも、**APIキー自体のRedmine上の権限は縮小されません**。専用ユーザー、最小権限、対象プロジェクトの制限は管理者が行ってください。
- HTTPSと証明書検証を必須とし、リダイレクトには追従しません。エラーにレスポンス本文、ヘッダー、キーを表示しません。
- 公開リポジトリです。実URL、キー、社内チケット、実レスポンス、ログ、エクスポートをコミットしないでください。

## 必要環境とインストール

Python 3.11以上、`requests >=2.31,<3` を使用します。テストは `pytest >=8,<9` です。

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
Copy-Item config.example.toml config.toml
$env:REDMINE_API_KEY = Read-Host "API key" -MaskInput
redmine-readonly --config config.toml check
redmine-readonly --config config.toml export --project sample-project --output-dir "D:\Approved\RedmineExports"
Remove-Item Env:REDMINE_API_KEY
```

出力先はリポジトリ外の、組織に承認されたアクセス制御・保管期限・バックアップ方針を持つフォルダを指定します。共有端末や同期対象フォルダを安易に使わないでください。

## 設定とネットワーク

`config.example.toml` をローカルの `config.toml` にコピーします。`base_url` はサブパス（例: `/redmine`）を含められ、API URLでも保持されます。URLのユーザー情報、クエリ、フラグメント、HTTPは拒否します。

社内CAはPEMファイルの承認済みパスを `ca_bundle` に設定します。検証無効化の設定はありません。プロキシはrequests標準の `HTTPS_PROXY` と、必要なら `NO_PROXY` 環境変数を利用します。プロキシURLに認証情報を直接残す運用は避け、組織の資格情報管理手順に従ってください。

```powershell
$env:HTTPS_PROXY = "http://proxy.example.invalid:8080"
$env:NO_PROXY = "localhost,127.0.0.1"
```

## コマンド

`check` は設定検証後に現在ユーザーを確認し、成功可否、ユーザーID、存在する場合だけloginを表示します。メールや全レスポンスは表示・保存しません。

`export` の `--project` と `--output-dir` は必須です。既定条件は全ステータス (`--status '*'` / `status_id=*`、完了を含む)、子プロジェクト除外 (`subproject_id=!*`)、ID昇順です。対象環境で確認済みのステータスID等に限定する場合は `--status`、子プロジェクトを含めるには `--include-subprojects`、トラッカー絞り込みには数値IDの `--tracker` を明示します。

指定した出力先の下に、実行ごとの一意な `run-<UTC日時>-<ランダムID>` ディレクトリを作り、その中へ `issues.csv` と `issues.json` をまとめます。最初は同じ出力先内の未完成を示す `.pending-*` ディレクトリへ両方を書き込み、両方が成功した後だけ完成runとして名前を変更します。このため途中失敗を完成runとして公開せず、同時実行や既存runとのファイル混在・上書きを避けます。失敗した一時ディレクトリは削除されます。

JSONは開始・終了日時、抽出条件、件数、ページ数と選択項目の元のJSON型を保持します。CSVはUTF-8 BOM付きで、未設定値、カンマ、引用符、改行、日本語をCSV規則で扱います。Excelの数式注入対策として、空白類に続く `=`, `+`, `-`, `@` で始まる**文字列**には先頭へ `'` を追加します。このためCSV上の値は変化します。表計算ソフトやインポート機能ごとの差、別の危険な解釈を完全には防げないため、信頼できない値を含むファイルを開く際は保護ビュー等も使用してください。JSONは変更しません。

ページングでは `limit`, `offset`, `total_count` を検査し、サーバーが要求より少ないページを返しても実返却数で進めます。重複ID、件数変化、早すぎる空ページ、offset不一致、途中失敗、上限到達時は完成出力を書きません。ただし件数一致は取得中の同時更新を含むトランザクション的な完全スナップショットを保証しません。

## 標準仕様と実環境確認

標準Redmine REST APIで一般に提供される上記2エンドポイントと、issuesのフィルター・ページングを前提にしています。一方、対象環境のバージョンや改修により、利用可否、フィルター構文、上限、返却項目、権限挙動が異なる可能性があります。`docs/quick2-verification-checklist.md` に従い確認してください。

カスタム項目は今回保存しません。管理者と項目の必要性を合意し、テスト環境で `/issues/{id}.json?include=...` 等の対象環境が公開する仕様とレスポンスから項目ID、名称、型、複数値、権限による可視性を確認してください。実データをリポジトリへ貼らず、必要性判明後に許可リスト方式の項目指定を追加します。

## 開発

```bash
python -m pip install -e '.[test]'
python -m pytest
```

テストは偽セッションだけを使い、実環境へ接続しません。今後の計画と非対象範囲は `docs/implementation-plan.md` を参照してください。
