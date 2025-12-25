# Sample CSV Files for Asset Management System

このディレクトリには、システムのインポート機能をテストするためのサンプルCSVファイルが含まれています。

## Files

### sample_moneyforward.csv
MoneyForward形式のCSVサンプルです。
- 列: 日付、内容、金額（円）、保有金融機関、大項目、中項目、メモ
- 収入、支出、振替の各種取引を含んでいます

### sample_bank_statement.csv
銀行明細形式のCSVサンプルです。
- 列: 取引日、摘要、出金額、入金額、残高
- 一般的な銀行口座の入出金記録フォーマット

## Usage

1. Streamlit UIの **Import** ページを開く
2. CSVファイルをアップロード
3. アカウント名を入力（任意）
4. **Import** ボタンをクリック

システムは自動的にCSV形式を検出し、適切なパーサーを使用します。
