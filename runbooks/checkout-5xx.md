# Runbook: Checkout API 5xx spike
Service: checkout-api | Alarm: pilotlight-checkout-5xx | Severity: sev2

## Symptoms
Checkout requests return 502. Logs show PaymentTimeout errors.

## Likely causes
1. The fail_mode feature flag was turned on (most common, check first).
2. The payment provider is degraded.

## Remediation
1. Check SSM parameter /pilotlight/checkout/fail_mode. If it is "on", revert it to "off".
2. Confirm the CheckoutErrors metric returns to zero within two minutes.
3. If errors continue, page the payments team.

## Escalation
Secondary on-call: payments team lead.
