# Call Transcript — INC-20261017-1002

**Duration:** 4 minutes 12 seconds
**Participants:** Pilot Light (agent), Alex Chen (on-call engineer)

---

**Pilot Light:** This is Pilot Light, your incident response agent. The checkout API is returning a high rate of five hundred errors. In the last ten minutes there have been two hundred twelve errors, all PaymentTimeout from the checkout handler. The SSM parameter fail_mode was changed from off to on three minutes before the errors started. A runbook for this alarm is available. Would you like the logs, what changed, or the runbook?

**Alex Chen:** What changed?

**Pilot Light:** The parameter slash pilotlight slash checkout slash fail_mode was changed from off to on at nine fifty-nine AM by user demo-admin. No other configuration changes were found in the last hour.

**Alex Chen:** What does the runbook say about this?

**Pilot Light:** The runbook says: if fail_mode is set to on, revert it to off, then confirm the checkout errors metric returns to zero within two minutes. If errors continue after reverting, page the payments team.

**Alex Chen:** OK revert it.

**Pilot Light:** I will set the SSM parameter slash pilotlight slash checkout slash fail_mode from on to off. This is the revert fail mode action on the approved list. I need you to say confirm before I run it.

**Alex Chen:** Confirm.

**Pilot Light:** Done. fail_mode is now set to off. Errors should drop within about thirty seconds. Watch the PilotLight CheckoutErrors metric to verify. Would you like me to page a teammate, or is there anything else?

**Alex Chen:** No that's it. But we should really add a circuit breaker to the checkout handler so a bad flag doesn't take down the whole service. And we need a test that catches this. Can you note that?

**Pilot Light:** Noted. I have logged two action items: add a circuit breaker to the checkout handler, and add a test for the fail mode behavior. Is there anything else before I end the call?

**Alex Chen:** No, thanks. End the call.

**Pilot Light:** Ending the call. A postmortem will be drafted and placed in your Box incident folder. Goodbye.
