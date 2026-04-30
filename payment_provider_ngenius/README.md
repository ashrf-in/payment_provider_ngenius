# N-Genius Payment Provider for Odoo

Accept online card payments in Odoo with N-Genius Online by Network International.

This module adds N-Genius as a native payment provider in Odoo 19 and connects checkout, payment verification, and refunds to a hosted N-Genius payment flow. Customers are redirected to N-Genius to complete payment, while Odoo keeps the transaction lifecycle visible in the back office.

## Who This Module Is For

Use this module if you already have an N-Genius merchant account and want to:

- offer N-Genius on Odoo checkout
- avoid handling card details on your Odoo website
- keep payment and refund activity inside Odoo
- run the same integration in sandbox and production

## What The Module Does

- adds N-Genius as an Odoo payment provider
- creates PURCHASE orders through the N-Genius API
- redirects customers to the N-Genius hosted payment page
- verifies the final order status when the customer returns to Odoo
- processes webhook notifications and refreshes transaction data from N-Genius
- supports full refunds from Odoo when the payment exposes a refund or reversal action
- optionally sends the customer's billing address when Odoo partner data is complete
- optionally validates a custom webhook header configured in N-Genius

## Supported Features

- Hosted redirect checkout
- Card payments
- Sandbox and production environments
- Automatic transaction updates
- Full refunds only
- Optional webhook header validation
- Strict 3-D Secure result handling

## Key Benefits For Merchants

- Keep checkout connected to a well-known hosted payment flow
- Track provider references and payment state changes inside Odoo
- Reduce manual payment verification with return and webhook refresh logic
- Handle supported refund operations without leaving Odoo
- Use the same integration pattern in sandbox before switching to production

## Not Supported

- Tokenization or saved cards
- Manual capture
- Partial refunds
- Encrypted webhook payloads

## How The Payment Flow Works

1. The customer selects N-Genius during checkout.
2. Odoo creates a PURCHASE order in N-Genius for the transaction amount and currency.
3. The customer is redirected to the hosted N-Genius payment page.
4. After payment, N-Genius redirects the customer back to Odoo.
5. Odoo fetches the authoritative order details from N-Genius and updates the transaction status.
6. N-Genius webhooks provide backend confirmation for payment and refund events.

## How Refunds Work

The module supports full refunds only.

When a refund is requested from Odoo, the module retrieves the N-Genius order, inspects the available payment actions, and uses the provider-managed refund endpoint when available. If the payment is still in a reversible state, it can use the available void or reversal action instead.

## Transaction Visibility In Odoo

Payment activity stays in Odoo's standard payment transaction records.

- The N-Genius order reference is stored on the transaction.
- Return and webhook events both refresh the transaction from authoritative order data.
- Refund operations create the expected Odoo payment transaction trail for follow-up and reconciliation.
- Success, pending, cancelled, and failed outcomes are mapped back into Odoo transaction states.

## 3-D Secure Handling

When N-Genius returns 3DS data, the module accepts only fully authenticated ECI results:

- `05` for Visa
- `02` for Mastercard

Attempted or not fully authenticated ECI results are treated as failed authentication and the transaction is marked as an error.

## Requirements

- Odoo 19.0
- An active N-Genius merchant account
- An N-Genius API key from a service account
- A valid N-Genius outlet reference
- A public Odoo base URL reachable over HTTPS
- Webhook whitelisting or approval completed in N-Genius when required
- Matching currencies between Odoo and your N-Genius outlet configuration

## Installation And Configuration

1. Install the module in your Odoo database.
2. Go to Accounting > Configuration > Payment Providers and open N-Genius.
3. Enter the API Key.
4. Enter the Outlet Reference.
5. Set the provider to Test for sandbox or Enabled for production.
6. Publish the provider when you are ready to use it on checkout.
7. Configure the webhook URL in N-Genius:
   `https://<your-odoo-domain>/payment/ngenius/webhook`
8. If you protect the webhook with a custom header, enter the same header name and value in Odoo.
9. Make sure `web.base.url` points to a public domain, not `localhost` or a loopback address.

## Configuration Checklist

Before going live, verify the following:

- The provider is published on the intended website or checkout flow.
- The configured outlet supports the currencies you sell in Odoo.
- Your public domain is reachable by both customers and N-Genius callbacks.
- The webhook endpoint is configured in N-Genius and any required whitelisting is complete.
- The optional custom webhook header matches exactly on both sides.
- A full sandbox payment has been completed and returned to Odoo successfully.

## Important Operational Notes

- The module uses a hosted payment page. Card data is handled by N-Genius, not by Odoo.
- The return URL must use a public hostname. The module blocks localhost and loopback URLs, and N-Genius sandbox commonly rejects them.
- Automatic backend updates depend on a working webhook configuration.
- The module expects standard JSON webhook payloads. If encrypted webhooks are enabled in N-Genius, this module will not decrypt them unless it is extended.
- Billing address data is only sent when the partner record includes a name, street, city, and country.
- N-Genius can reject order creation when the transaction currency is not enabled on the configured outlet.

## Included Endpoints

- Return URL: `/payment/ngenius/return`
- Webhook URL: `/payment/ngenius/webhook`

## Dependencies

- `payment`
- `account_payment`

## FAQ

### Does this module keep card details inside Odoo?

No. Customers are redirected to the hosted N-Genius payment page, so card entry happens on the provider side.

### Can I test before going live?

Yes. The provider works in Odoo test mode and uses the N-Genius sandbox API when the provider is set to `Test`.

### Does it support partial refunds?

No. The current implementation supports full refunds only.

### Why would order creation fail even with valid credentials?

One common cause is a currency mismatch between the Odoo transaction and the currencies enabled on the configured N-Genius outlet.

### Does it support encrypted webhook payloads?

No. The current implementation expects standard JSON webhook payloads.

## Support

- Author: Ashraf
- Website: [www.ashrf.in](https://www.ashrf.in)
- Support: [connect@ashrf.in](mailto:connect@ashrf.in)

## License

This module is licensed under LGPL-3. See [LICENSE](LICENSE).
