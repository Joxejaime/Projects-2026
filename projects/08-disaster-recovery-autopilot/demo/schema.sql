-- Orders: the demo service's data. Two tables plus one business rule that no health check sees:
-- an order's total_cents must equal the sum of qty * price_cents over its items.
CREATE TABLE IF NOT EXISTS orders (
    id          bigserial PRIMARY KEY,
    total_cents bigint NOT NULL CHECK (total_cents >= 0),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS order_items (
    id          bigserial PRIMARY KEY,
    order_id    bigint NOT NULL REFERENCES orders (id),
    sku         text NOT NULL,
    qty         integer NOT NULL CHECK (qty > 0),
    price_cents bigint NOT NULL CHECK (price_cents >= 0)
);
