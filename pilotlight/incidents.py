"""DynamoDB incident record helpers. Table: pk incident_id."""
import datetime

import boto3
from boto3.dynamodb.conditions import Attr

from .config import AWS_REGION, INCIDENTS_TABLE

table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(INCIDENTS_TABLE)


def get(incident_id: str) -> dict | None:
    return table.get_item(Key={"incident_id": incident_id}).get("Item")


def put(item: dict) -> None:
    table.put_item(Item=item)


def update(incident_id: str, **fields) -> None:
    names = {f"#{k}": k for k in fields}
    values = {f":{k}": v for k, v in fields.items()}
    table.update_item(Key={"incident_id": incident_id},
        UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in fields),
        ExpressionAttributeNames=names, ExpressionAttributeValues=values)


def _scan(filter_expr) -> list[dict]:
    items, kwargs = [], {"FilterExpression": filter_expr}
    while True:
        r = table.scan(**kwargs)
        items += r["Items"]
        if "LastEvaluatedKey" not in r:
            return items
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def latest_open(alarm_name: str | None = None, within_minutes: int | None = None) -> dict | None:
    """Most recent open incident, optionally for one alarm and started within a window."""
    expr = Attr("status").eq("open")
    if alarm_name:
        expr &= Attr("alarm_name").eq(alarm_name)
    if within_minutes:
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=within_minutes)
        expr &= Attr("started_at").gte(cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"))
    items = _scan(expr)
    return max(items, key=lambda i: i["started_at"]) if items else None


def by_contact(contact_id: str) -> dict | None:
    items = _scan(Attr("contact_id").eq(contact_id))
    return items[0] if items else None
