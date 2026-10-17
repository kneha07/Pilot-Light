# Runbook: Checkout API payment errors
Service: checkout-api | Alarm: pilotlight-checkout-5xx | Severity: sev2

## Symptoms
Checkout requests return 502. Logs show PaymentError: the payment provider rejects requests.

## Likely causes
1. A recent payment configuration change (most common, check first).
2. The payment provider is degraded.

## Remediation
1. Check what changed. If the payment configuration was changed, roll it back.
2. Confirm checkout errors return to zero within two minutes.
3. If errors continue, page the payments team.

## Escalation
Secondary on-call: payments team lead.
