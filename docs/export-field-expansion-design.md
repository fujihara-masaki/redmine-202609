# export項目の段階的拡張設計

## PR-1.2の境界

既定 `basic` は従来の8 JSON項目・12 CSV列を変えない。明示 `--fields extended` のみ、一覧
`GET /issues.json` の同じ応答から次の固定10項目を積極選択する。profileはAPI parameterではなく、
個別issue GET、追加include、参照先取得は行わない。完全なissue objectは保持せず、未知の親子キー、
description、custom_fields、journals、watchers、attachments、relationsを保存しない。

| field | 非null値の許可shape |
| --- | --- |
| priority / author / category / fixed_version | 正の整数id、返却時だけstring/null name |
| parent | 正の整数idだけ |
| start_date / due_date | 実在する `YYYY-MM-DD` または空文字 |
| done_ratio | boolでない0..100の整数 |
| estimated_hours | boolでない0以上の有限JSON数値（丸めない） |
| is_private | JSON boolean |

参照nameは最大4096文字で、超過値を切り捨てない。型・値異常はfield名と固定理由だけのAppErrorで
停止し、元値やissue IDをエラーへ含めない。この検証はextendedだけに適用しbasicを変えない。
authorは個人識別情報となり得て、category/version nameも業務情報になり得るため、extendedは
対象範囲と保存を承認した利用者だけが選ぶopt-inである。

## 欠損、null、出力

元応答にキーがなければJSONキーを作らず、キーがありnullならnullを残し、非null値は検証後に
元のJSON型で残す。false、0、0.0、日付空文字を欠損にしない。欠損理由を権限、未設定、対象環境の
非対応等と推測せず、別APIから補完しない。

CSVはbasic 12列、basic+JST 14列を維持する。extendedはその後へ次を固定順で加え、0件・全欠損でも
26列（JST併用28列）を出す。

`priority_id, priority_name, author_id, author_name, category_id, category_name, fixed_version_id,
fixed_version_name, parent_id, start_date, due_date, done_ratio, estimated_hours, is_private`

CSVの文字列には共通 `csv_safe` を使い、booleanは小文字true/falseとする。CSVでは欠損/null/空文字が
空欄へ収束するため、区別にはJSONを使う。created/updated raw日時と任意JST列は従来どおりで、日付だけの
start/due dateは変換しない。

## metadataと完全性

extendedだけ `field_profile=extended`, `export_schema=extended-v1`, 固定順
`selected_extended_fields`、各固定fieldの `missing_count/null_count/value_count` を追加する。
value_countは「非null値が返り検証を通った」件数で、業務上の有意な設定済み値という意味ではない。
日付空文字もvalueで、各fieldの3件数合計はissue_countに一致する。0件は全て0であり、対応有無の
証拠にはしない。集計に値、ID一覧、未知fieldを含めず、実環境集計もpublic repositoryへ貼らない。
ページ処理中に選択・集計し、不正値や取得失敗時はwrite/publishへ進まないため既存runを保持する。

## 標準資料と対象環境の制約

候補はRedmine公式 REST Issues wiki と公式source
`app/views/issues/index.api.rsb`（GitHub master）を参照対象とした。確認日2026-10-02には、この作業環境の
web取得がHTTP 401となり内容・commitを再取得できなかったため、特定versionでの網羅性を主張しない。
作成・更新APIの入力parameterを一覧GETの出力保証とは扱わない。QUICK2での存在、型、空表現、ロール・
project別可視性、GUIとの業務対応は未確認である。マージ後の承認済み少数件確認で、metadata上返却された
項目だけをGUIと照合する。取得完了と個々の業務的妥当性確認は別の判定である。

## 後続段階

description、custom_fields、本文、個別issue情報はPR-1.2に含めない。PR-2第一段階では、明示
followup-configの指定時だけ、設定した障害区分・発見日の2カスタム項目をIDで限定選択する。
未知項目・付随キー・配列/object全体は保存せず、入力状態と派生結果を分離する。
単一文字列を初版とし、完了優先の暦日判定、固定CSV9列、JSON schema v1、rules/input SHA-256を
[フォロー設計](followup.md)に定義する。既定basic/extendedには追加せず、既存JST列とも独立する。
発見日は検知・発見の日付で、90/180日到達の未完了を〇とする。月次・延長・承認評価は後続。
実ID、区分値、型、可視性、機密区分はQUICK2手動受入でローカル確認する。
一般的な変更候補、二者レビュー、再取得差分検証も後続計画に残す。journals、relations、attachments、
watchers等の新endpoint/includeも負荷・権限を別レビューし、汎用path/methodや全項目探索は導入しない。
