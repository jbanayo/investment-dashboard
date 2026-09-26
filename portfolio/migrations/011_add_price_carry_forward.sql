ALTER TABLE instruments ADD COLUMN carry_forward_price INTEGER NOT NULL DEFAULT 0
    CHECK (carry_forward_price IN (0, 1));

