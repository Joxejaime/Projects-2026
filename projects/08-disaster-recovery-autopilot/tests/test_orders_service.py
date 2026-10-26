import json
import urllib.error
import urllib.request

import psycopg
import pytest

from .helpers import post_order

pytestmark = pytest.mark.postgres


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode()


def test_orders_are_stored_with_their_items_and_counted(orders_service):
    post_order(orders_service, qty=3, price=250)
    assert json.loads(get(orders_service + "/orders/count")[1]) == {"orders": 1}
    assert json.loads(get(orders_service + "/healthz")[1]) == {"status": "ok", "orders": 1}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"sku": "", "qty": 1, "price_cents": 1},
        {"sku": "a", "qty": 0, "price_cents": 1},
        {"sku": "a", "qty": 1, "price_cents": -1},
        {"sku": "a", "qty": "2", "price_cents": 1},
    ],
)
def test_bad_orders_are_rejected(orders_service, body):
    req = urllib.request.Request(orders_service + "/orders", data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req, timeout=5)
    assert err.value.code == 400


def test_dropping_the_tables_makes_the_service_unhealthy_with_the_reason(orders_service, db_url):
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("DROP TABLE order_items, orders")
    status, body = get(orders_service + "/healthz")
    assert status == 503 and "table orders is missing" in body
    assert "orders_data_healthy 0" in get(orders_service + "/metrics")[1]


def test_metrics_report_healthy_data(orders_service):
    status, body = get(orders_service + "/metrics")
    assert status == 200 and "orders_data_healthy 1" in body
