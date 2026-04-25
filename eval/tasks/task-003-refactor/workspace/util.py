"""Helpers for filtering and normalizing user records."""


def process_admins(users):
    result = []
    for user in users:
        if not user.get("active"):
            continue
        if user.get("role") != "admin":
            continue
        record = {
            "id": user["id"],
            "name": user["name"].strip().title(),
            "email": user["email"].lower(),
        }
        result.append(record)
    return result


def process_managers(users):
    result = []
    for user in users:
        if not user.get("active"):
            continue
        if user.get("role") != "manager":
            continue
        record = {
            "id": user["id"],
            "name": user["name"].strip().title(),
            "email": user["email"].lower(),
        }
        result.append(record)
    return result


def process_engineers(users):
    result = []
    for user in users:
        if not user.get("active"):
            continue
        if user.get("role") != "engineer":
            continue
        record = {
            "id": user["id"],
            "name": user["name"].strip().title(),
            "email": user["email"].lower(),
        }
        result.append(record)
    return result
