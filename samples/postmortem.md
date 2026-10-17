# Incident Postmortem — INC-20261017-1002

## Summary

The checkout API experienced a sustained outage from 10:02 to 10:08 UTC on 2026-10-17. All checkout requests returned 502 errors with PaymentTimeout. The root cause was the SSM parameter `/pilotlight/checkout/fail_mode` being set to `on` at 09:59 by user `demo-admin`. The parameter was reverted to `off` at 10:06 after verbal confirmation from the on-call engineer.

## Impact

- **Duration:** 6 minutes
- **Error count:** 212 five-hundred errors
- **Affected service:** checkout-api
- **Customer impact:** All checkout attempts failed during the window

## Timeline (UTC)

| Time | Event |
|------|-------|
| 09:59 | SSM parameter `fail_mode` changed from `off` to `on` by `demo-admin` |
| 10:02 | CloudWatch alarm `pilotlight-checkout-5xx` entered ALARM state |
| 10:02 | Incident Lambda created INC-20261017-1002 |
| 10:02 | Pilot Light called on-call engineer (Alex Chen) |
| 10:03 | Agent delivered briefing |
| 10:04 | Engineer asked "what changed?" — agent returned SSM parameter change |
| 10:04 | Engineer asked for runbook — agent returned remediation steps |
| 10:05 | Engineer requested revert of fail_mode |
| 10:06 | Engineer confirmed — agent reverted fail_mode to `off` |
| 10:08 | Error rate returned to zero, alarm returned to OK |

## Root Cause

The checkout Lambda handler reads the SSM parameter `/pilotlight/checkout/fail_mode` every 2 seconds. When this parameter is set to `on`, the handler immediately returns a 502 error with a PaymentTimeout message and emits a custom CloudWatch metric. There is no circuit breaker, rate limiting, or gradual degradation — the flag is a hard kill switch that fails 100% of requests.

The parameter was changed by `demo-admin` at 09:59. There is no validation or confirmation step on SSM parameter changes, and no automated check that setting this parameter to `on` will cause a full outage.

## Resolution

The on-call engineer verbally confirmed the revert action. Pilot Light set the SSM parameter back to `off`. Errors stopped within 30 seconds.

## Action Items

| ID | Action | Owner | Priority |
|----|--------|-------|----------|
| 1 | Add a circuit breaker to the checkout handler so a single bad flag does not fail 100% of requests. When fail_mode is on, the handler should fail a configurable percentage of requests (default 0%) rather than all of them, and emit a warning metric before errors spike. | TBD | P1 |
| 2 | Add a unit test that verifies the checkout handler behavior when fail_mode is on and off, including the metric emission and the error response format. | TBD | P1 |
| 3 | Add an SSM parameter change notification (SNS or EventBridge rule) that alerts the team channel when any pilotlight parameter is modified, before an outage occurs. | TBD | P2 |
