"""DynamoDB timeline helpers. Table: pk incident_id, sk ts (ISO with milliseconds)."""
import datetime

import boto3
from boto3.dynamodb.conditions import Key

from .config import AWS_REGION, TIMELINE_TABLE

table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(TIMELINE_TABLE)


def add(incident_id: str, type_: str, text: str, at: datetime.datetime | None = None) -> None:
    at = at or datetime.datetime.now(datetime.timezone.utc)
    ts = at.astimezone(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    table.put_item(Item={"incident_id": incident_id, "ts": ts, "type": type_, "text": text})


def list_all(incident_id: str) -> list[dict]:
    items, kwargs = [], {"KeyConditionExpression": Key("incident_id").eq(incident_id)}
    while True:
        r = table.query(**kwargs)
        items += r["Items"]
        if "LastEvaluatedKey" not in r:
            return items
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
