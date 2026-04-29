-- (unused / to be deleted)
-- 作成日: 2026-04-26
-- ============================================================

-- 新居の物品管理テーブル
-- 配置箇所・更新サイクル・費用を一元管理する

CREATE TABLE IF NOT EXISTS household_items (
    id              SERIAL PRIMARY KEY,
    client_id       INTEGER REFERENCES clients(id) ON DELETE CASCADE,

    -- 基本情報
    name            VARCHAR(200)    NOT NULL,
    category        VARCHAR(50)     NOT NULL,
    -- category: 家電 | 家具 | 消耗品 | 衣類・寝具 | 日用品 | 食器・調理器具 | その他

    status          VARCHAR(20)     NOT NULL DEFAULT 'planned',
    -- status: owned（所持済）| planned（購入予定）| disposed（処分済）

    -- 配置
    location        VARCHAR(50)     NOT NULL,
    -- location: main（メインルーム）| kitchen（キッチン）| washroom（洗面所）
    --           | toilet（トイレ）| entrance（玄関）| closet（クローゼット）
    sub_location    VARCHAR(100),
    -- サブ配置: 「シンク下」「棚上段」など自由記述

    -- 数量・金額
    quantity        INTEGER         NOT NULL DEFAULT 1 CHECK (quantity > 0),
    purchase_price  FLOAT           NOT NULL DEFAULT 0 CHECK (purchase_price >= 0),
    purchase_date   DATE,

    -- 更新管理
    renewal_months  INTEGER         NOT NULL DEFAULT 0 CHECK (renewal_months >= 0),
    -- 0 = 交換不要（耐久財など）
    -- N = N ヶ月ごとに更新
    -- next_renewal_date は purchase_date + renewal_months で都度計算

    lifespan_months INTEGER,
    -- 耐用期間（主に家電・家具などの耐久財に使用）

    -- メタ
    notes           TEXT,
    is_essential    BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP       NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_household_items_client   ON household_items(client_id);
CREATE INDEX IF NOT EXISTS idx_household_items_location ON household_items(location);
CREATE INDEX IF NOT EXISTS idx_household_items_status   ON household_items(status);
CREATE INDEX IF NOT EXISTS idx_household_items_category ON household_items(category);

-- 更新日時の自動設定（PostgreSQL トリガー）
CREATE OR REPLACE FUNCTION update_household_items_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_household_items_updated_at ON household_items;
CREATE TRIGGER trg_household_items_updated_at
    BEFORE UPDATE ON household_items
    FOR EACH ROW
    EXECUTE FUNCTION update_household_items_updated_at();

-- ============================================================
-- ロールバック（必要な場合）
-- DROP TABLE IF EXISTS household_items CASCADE;
-- DROP FUNCTION IF EXISTS update_household_items_updated_at CASCADE;
-- ============================================================
