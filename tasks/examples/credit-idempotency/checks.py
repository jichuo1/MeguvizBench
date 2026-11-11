def evaluate(artifact, run):
    def check(balances, requests, remaining, responses):
        payload = {
            "balances": balances,
            "requests": [{"account": account, "key": key, "amount": amount} for account, key, amount in requests],
        }
        expected = {"balances": remaining, "responses": responses}
        actual = run(payload)
        if not isinstance(actual, dict) or actual != expected:
            return False
        return all(type(value) is int for value in actual["balances"].values()) and all(
            "balance" not in item or type(item["balance"]) is int for item in actual["responses"]
        )

    def receipt(balance):
        return {"status": "ok", "balance": balance}

    return {
        "first_spend": check({"a": 8}, [("a", "x", 3)], {"a": 5}, [receipt(5)]),
        "exact_balance": check({"a": 5}, [("a", "x", 5)], {"a": 0}, [receipt(0)]),
        "duplicate_no_charge": check({"a": 9}, [("a", "x", 3)] * 2, {"a": 6}, [receipt(6), receipt(6)]),
        "original_receipt": check(
            {"a": 10}, [("a", "x", 2), ("a", "y", 1), ("a", "x", 2)], {"a": 7}, [receipt(8), receipt(7), receipt(8)],
        ),
        "changed_amount_conflict": check(
            {"a": 10}, [("a", "x", 2), ("a", "x", 3)], {"a": 8}, [receipt(8), {"status": "conflict"}],
        ),
        "account_key_scope": check({"a": 5, "b": 7}, [("a", "x", 3), ("b", "x", 3)], {"a": 2, "b": 4}, [receipt(2), receipt(4)]),
        "failed_key_reusable": check(
            {"a": 4}, [("a", "x", 5), ("a", "x", 2)], {"a": 2}, [{"status": "insufficient"}, receipt(2)],
        ),
        "amount_validation": check(
            {"a": 10}, [("a", "x", value) for value in [True, 0, -1, 2.5, "2"]], {"a": 10}, [{"status": "invalid_amount"}] * 5,
        ),
        "unknown_account": check({"a": 10}, [("missing", "x", 3)], {"a": 10}, [{"status": "unknown_account"}]),
        "no_requests": check({"a": 10}, [], {"a": 10}, []),
    }
