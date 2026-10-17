"""Thin CloudWatch Logs helpers. CloudWatch Logs is the event store in the event account,
where DynamoDB, S3 writes, and CloudWatch metrics are blocked by the organization policy."""
import json
import threading
import time

import boto3

from .config import AWS_REGION

logs = boto3.client("logs", region_name=AWS_REGION)
_known_streams: set[tuple[str, str]] = set()
_lock = threading.Lock()


def ensure_stream(group: str, stream: str) -> None:
    if (group, stream) in _known_streams:
        return
    try:
        logs.create_log_stream(logGroupName=group, logStreamName=stream)
    except logs.exceptions.ResourceAlreadyExistsException:
        pass
    _known_streams.add((group, stream))


def put(group: str, stream: str, messages: list[str], timestamp_ms: int | None = None) -> None:
    if not messages:
        return
    ts = timestamp_ms or int(time.time() * 1000)
    with _lock:
        ensure_stream(group, stream)
        logs.put_log_events(logGroupName=group, logStreamName=stream,
                            logEvents=[{"timestamp": ts, "message": m} for m in messages])


def put_json(group: str, stream: str, record: dict) -> None:
    put(group, stream, [json.dumps(record)])


def read_stream(group: str, stream: str) -> list[dict]:
    """All events in a stream, oldest first."""
    events, kwargs = [], {"logGroupName": group, "logStreamName": stream, "startFromHead": True}
    while True:
        try:
            r = logs.get_log_events(**kwargs)
        except logs.exceptions.ResourceNotFoundException:
            return events
        events += r["events"]
        if r["nextForwardToken"] == kwargs.get("nextToken"):
            return events
        kwargs["nextToken"] = r["nextForwardToken"]


def newest(group: str, stream: str, limit: int = 1) -> list[dict]:
    """The newest N events in a stream, oldest first, in one call (no full-stream read)."""
    try:
        return logs.get_log_events(logGroupName=group, logStreamName=stream, startFromHead=False, limit=limit)["events"]
    except logs.exceptions.ResourceNotFoundException:
        return []


def recent(group: str, seconds: int, pattern: str = "") -> list[dict]:
    """Events from the last N seconds across all streams in a group."""
    start = int((time.time() - seconds) * 1000)
    events, kwargs = [], {"logGroupName": group, "startTime": start}
    if pattern:
        kwargs["filterPattern"] = pattern
    while True:
        r = logs.filter_log_events(**kwargs)
        events += r["events"]
        if "nextToken" not in r:
            return events
        kwargs["nextToken"] = r["nextToken"]


class BufferedShipper:
    """Batches log lines and ships them once per interval so request handling never waits on AWS."""

    def __init__(self, group: str, stream: str, interval: float = 0.5):
        self.group, self.stream, self.interval = group, stream, interval
        self._buf: list[dict] = []
        self._buf_lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    def log(self, message: str) -> None:
        with self._buf_lock:
            self._buf.append({"timestamp": int(time.time() * 1000), "message": message})

    def _run(self) -> None:
        while True:
            time.sleep(self.interval)
            with self._buf_lock:
                batch, self._buf = self._buf, []
            if batch:
                try:
                    with _lock:
                        ensure_stream(self.group, self.stream)
                        logs.put_log_events(logGroupName=self.group, logStreamName=self.stream, logEvents=batch)
                except Exception as e:  # never crash the service over log shipping
                    print(f"[shipper] failed to ship {len(batch)} events: {e}")
