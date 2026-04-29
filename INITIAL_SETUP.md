# 初期設定ガイド — hayato / 2026年4月

## 1. 収支計算（給与明細の推定）

### 月次給与内訳

| 項目 | 金額 | 備考 |
|------|------|------|
| **額面月収** | **312,000円** | 初任給ベース |
| 健康保険料 | ▲ 16,336円 | 協会けんぽ大阪 10.21%、標準報酬320,000 |
| 厚生年金 | ▲ 29,280円 | 18.3%、標準報酬320,000 |
| 雇用保険 | ▲ 1,872円 | 0.6% |
| 所得税（源泉） | ▲ 5,220円 | DC控除後・扶養0人・住民税は2年目から |
| 住民税 | 0円 | 2027年6月から天引き開始 |
| **税社保後手取り** | **259,292円** | |
| 企業型DC（自己拠出） | ▲ 25,000円 | 給与天引き・全額所得控除済み |
| 持株会 | ▲ 50,000円 | 給与天引き |
| 社宅使用料 | ▲ 8,980円 | 給与天引き想定 |
| **楽天銀行着金額** | **175,312円** | ≒ 175,000円 |

> **1年目の特典:** 住民税ゼロ。2027年6月から月約+15,000-18,000円の負担増になるため早めの認識を。

### 月次予算（着金後）

| 区分 | カテゴリ | 予算 | 備考 |
|------|---------|------|------|
| **投資** | NISA（楽天カード） | 100,000 | 翌月引き落とし |
| **固定費** | 食費 | 22,000 | 自炊中心 |
| | 外食・飲み | 18,000 | 4〜6月は +7,000（新歓・懇親会） |
| | 光熱費（水道・ガス・電気） | 10,000 | インターネット無料 |
| | AI（Gemini/Claude/OpenAI） | 8,100 | Gemini 2,900 + Claude 2,500 + OAI 2,700 |
| | マッチングアプリ | 4,000 | Pairs等 月額想定 |
| | 美容・医療 | 15,000 | 脱毛割月+肌治療+歯クリーニング |
| | 日用品 | 5,000 | |
| | 交通（プライベート） | 3,000 | 通勤は会社負担 |
| | 衣類・その他 | 5,000 | |
| **合計支出** | | **190,100** | |
| **月次収支** | | **▲15,100** | 4〜6月は貯蓄から補填、ボーナスで回収 |

> **4〜6月の対処:** 現在の50万未満の貯蓄から補填。7月夏賞与（推定150,000〜200,000円）で回収する計画。

### ボーナス見込み

| 時期 | 推定金額 | 備考 |
|------|---------|------|
| 2026年7月（夏） | 150,000〜200,000円 | 初年度・在職4ヶ月按分 |
| 2026年12月（冬） | 400,000〜500,000円 | 在職10ヶ月按分 |
| **年間合計** | **550,000〜700,000円** | 保守的試算 |
| 持株会ボーナス追加 | ▲100,000×2回 | 通常5万→ボーナス月15万の追加分 |

---

## 2. アカウント設定（口座・科目）

UIの **Journal → Transaction → 口座管理** または API `POST /accounts/` から入力。

### 資産口座（account_type: `asset`）

| 口座名 | 初期残高 | expected_return | 備考 |
|-------|---------|----------------|------|
| 楽天銀行 | **実際の残高を入力** | 0.1% | 生活費・緊急予備費の拠点 |
| 楽天証券 NISA | 100,000 | 6.0% | オルカン長期期待収益率 |
| NTT企業型DC | 25,000 | 7.0% | S&P500長期期待収益率 |
| NTT持株会 | 50,000 | 4.0% | NTT株（通信セクター）|

> 楽天証券NISAとDC・持株の残高は「4月分が入金済みの場合」の目安。入金タイミングに合わせて調整。

### 収益口座（account_type: `income`）

| 口座名 | 備考 |
|-------|------|
| 給与収入 | 毎月の収入取引の相手科目 |
| 賞与 | ボーナス取引用 |
| 持株奨励金 | 10%奨励金の計上用 |

### 費用口座（account_type: `expense`）— 予算付き

| 口座名 | 月次予算（budget_limit） |
|-------|----------------------|
| 食費 | 22,000 |
| 外食・飲み | 18,000 |
| 光熱費 | 10,000 |
| AI・サブスク | 8,100 |
| 美容・医療 | 15,000 |
| マッチング | 4,000 |
| 日用品 | 5,000 |
| 交通費（私用） | 3,000 |
| 衣類・その他 | 5,000 |

---

## 3. Capsules（積立枠）設定

UIの **Strategy → Capsules** から入力（リファクタリング後）または **Journal → Capsules** から入力。

| 名前 | 目標金額 | 月次積立 | 現在残高 | 用途・備考 |
|-----|---------|---------|---------|---------|
| 緊急予備費 | 525,000 | 10,000 | 0 | 着金3ヶ月分（175,000×3）。ボーナスで一気に積む |
| 美容医療積立 | 200,000 | 5,000 | 0 | 大型施術（レーザー等）の前払い・一括払いバッファ |
| 婚活・出会い資金 | 300,000 | 5,000 | 0 | プレミアムプラン切替・デート費・婚活イベント |
| 旅行・レジャー | 150,000 | 3,000 | 0 | 年1〜2回の国内旅行想定 |

> **緊急予備費の優先度が最高。** 現在の貯蓄50万未満が「実質の緊急予備費」の役割を果たしているが、正式に口座管理することで使途を明確化する。夏ボーナスで一気に目標額に近づける想定。

---

## 4. Life Events（ライフイベント）設定

UIの **Strategy → Simulation** の左パネルから「ライフイベント追加」で入力。

| イベント名 | 目標日 | 目標金額 | 優先度 | 根拠・備考 |
|----------|-------|---------|-------|----------|
| 結婚 | 2031-03-31 | 3,000,000 | 1（高） | 32歳を仮目安。式・披露宴250万+新婚旅行50万。ご祝儀で一部回収見込み |
| 住宅取得頭金 | 2035-06-30 | 5,000,000 | 2（中） | 36歳目安。大阪市内 4000〜5000万円物件の10〜15%頭金 |
| 育児・教育準備 | 2033-03-31 | 2,000,000 | 3（低） | 33歳目安。出産費・育休期間の生活費バッファ・乳児用品 |

> **注:** ライフイベントはあくまで仮目標。本配属・交際状況によって随時更新してください。

---

## 5. MCP サーバー設定ファイルの更新

以下のファイルを手動で更新する（`AssetManagement/mcp/data/` 以下）。

### `portfolio.json` の変更箇所

```json
{
  "profile": {
    "take_home": 175000     // 210000 → 175000（楽天銀行着金実額）
  },
  "emergency_fund": {
    "target": 525000,       // 270000 → 525000（着金3ヶ月分に修正）
    "current": 0,           // 実際の緊急予備費残高に更新
    "monthly_contribution": 10000,
    "target_date": "2027-03-31"  // 延長（ボーナス活用で1年弱で達成見込み）
  }
}
```

### `budget.json` の変更箇所

```json
{
  "take_home": 175000,    // 210000 → 175000
  "items": [
    { "category": "食費",            "planned": 22000 },
    { "category": "外食・飲み",      "planned": 18000 },
    { "category": "光熱費",          "planned": 10000 },
    { "category": "AI・サブスク",    "planned": 8100  },
    { "category": "美容・医療",      "planned": 15000 },
    { "category": "マッチング",      "planned": 4000  },
    { "category": "日用品・消耗品",  "planned": 5000  },
    { "category": "交通費（私用）",  "planned": 3000  },
    { "category": "衣類・その他",    "planned": 5000  },
    { "category": "積立NISA",        "planned": 100000 },
    { "category": "企業型DC（マッチング）", "planned": 25000 },
    { "category": "NTT持株会",       "planned": 50000 }
  ]
}
```

---

## 6. API curl コマンド（バックエンドが起動中の場合）

> **前提:** バックエンドが `http://localhost:8000` で起動、認証トークンを取得済み。
> `TOKEN` を実際のJWTトークンに置き換えて実行。

### アカウント作成

```bash
BASE="http://localhost:8000"
TOKEN="YOUR_JWT_TOKEN"

# 資産口座
curl -s -X POST "$BASE/accounts/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"楽天銀行","account_type":"asset","balance":350000,"expected_return":0.1}'

curl -s -X POST "$BASE/accounts/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"楽天証券 NISA","account_type":"asset","balance":100000,"expected_return":6.0}'

curl -s -X POST "$BASE/accounts/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"NTT企業型DC","account_type":"asset","balance":25000,"expected_return":7.0}'

curl -s -X POST "$BASE/accounts/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"NTT持株会","account_type":"asset","balance":50000,"expected_return":4.0}'

# 収益口座
curl -s -X POST "$BASE/accounts/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"給与収入","account_type":"income","balance":0}'

curl -s -X POST "$BASE/accounts/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"賞与","account_type":"income","balance":0}'

curl -s -X POST "$BASE/accounts/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"持株奨励金","account_type":"income","balance":0}'

# 費用口座（予算付き）
for row in \
  '{"name":"食費","budget_limit":22000}' \
  '{"name":"外食・飲み","budget_limit":18000}' \
  '{"name":"光熱費","budget_limit":10000}' \
  '{"name":"AI・サブスク","budget_limit":8100}' \
  '{"name":"美容・医療","budget_limit":15000}' \
  '{"name":"マッチング","budget_limit":4000}' \
  '{"name":"日用品","budget_limit":5000}' \
  '{"name":"交通費（私用）","budget_limit":3000}' \
  '{"name":"衣類・その他","budget_limit":5000}'; do
  curl -s -X POST "$BASE/accounts/" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$(echo $row | python3 -c "import sys,json; d=json.load(sys.stdin); d['account_type']='expense'; d['balance']=0; print(json.dumps(d, ensure_ascii=False))")"
done
```

### Capsules 作成

```bash
curl -s -X POST "$BASE/capsules/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"緊急予備費","target_amount":525000,"monthly_contribution":10000,"current_balance":0}'

curl -s -X POST "$BASE/capsules/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"美容医療積立","target_amount":200000,"monthly_contribution":5000,"current_balance":0}'

curl -s -X POST "$BASE/capsules/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"婚活・出会い資金","target_amount":300000,"monthly_contribution":5000,"current_balance":0}'

curl -s -X POST "$BASE/capsules/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"旅行・レジャー","target_amount":150000,"monthly_contribution":3000,"current_balance":0}'
```

### Life Events 作成

```bash
curl -s -X POST "$BASE/life-events/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"結婚","target_date":"2031-03-31","target_amount":3000000,"priority":1,"note":"式+新婚旅行。ご祝儀で一部回収見込み"}'

curl -s -X POST "$BASE/life-events/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"住宅取得頭金","target_date":"2035-06-30","target_amount":5000000,"priority":2,"note":"大阪市内マンション 4000〜5000万円物件の10〜15%頭金"}'

curl -s -X POST "$BASE/life-events/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"育児・教育準備","target_date":"2033-03-31","target_amount":2000000,"priority":3,"note":"出産費・育休期間生活費バッファ・乳児用品"}'
```

---

## 7. 注意事項・今後の更新タイミング

| タイミング | 更新内容 |
|----------|---------|
| 毎月末 | 各口座の実残高を更新（楽天銀行・NISA・DC・持株） |
| 毎月末 | Journal で当月の取引を入力 → Auto-Process でCapsule残高更新 |
| 2026年7月（夏ボーナス後） | 楽天銀行残高更新、緊急予備費Capsule一括積立 |
| 2026年12月（冬ボーナス後） | 同上 + Life Event の進捗確認 |
| 2027年6月 | 住民税天引き開始 → take_home を ▲15,000〜18,000円 修正 |
| 本配属後（6月） | 残業代・手当が確定 → 予算を実態値に調整 |
| 交際が進んだとき | 結婚・住宅イベントの目標日・金額を更新 |
