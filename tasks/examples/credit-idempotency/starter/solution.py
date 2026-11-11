import json
import sys


def apply_requests(balances, requests):
    responses = []
    for request in requests:
        account, amount = request["account"], request["amount"]
        if account not in balances:
            response = {"status": "unknown_account"}
        elif type(amount) is not int or amount <= 0:
            response = {"status": "invalid_amount"}
        elif balances[account] < amount:
            response = {"status": "insufficient"}
        else:
            balances[account] -= amount
            response = {"status": "ok", "balance": balances[account]}
        responses.append(response)
    return {"balances": balances, "responses": responses}


data = json.load(sys.stdin)
json.dump(apply_requests(data["balances"], data["requests"]), sys.stdout)
