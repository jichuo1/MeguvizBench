import json
import sys


def apply_requests(balances, requests):
    receipts = {}
    responses = []
    for request in requests:
        account, amount, key = request["account"], request["amount"], request["key"]
        if account not in balances:
            response = {"status": "unknown_account"}
        elif type(amount) is not int or amount <= 0:
            response = {"status": "invalid_amount"}
        elif key in receipts:
            original_amount, original_response = receipts[key]
            response = original_response if amount == original_amount else {"status": "conflict"}
        elif balances[account] < amount:
            response = {"status": "insufficient"}
        else:
            balances[account] -= amount
            response = {"status": "ok", "balance": balances[account]}
            receipts[key] = (amount, response)
        responses.append(response)
    return {"balances": balances, "responses": responses}


data = json.load(sys.stdin)
json.dump(apply_requests(data["balances"], data["requests"]), sys.stdout)
