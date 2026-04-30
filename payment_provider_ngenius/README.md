# N-Genius Payment Provider for Odoo

Accept online card payments in Odoo with N-Genius Online by Network International.

This module adds N-Genius as a payment provider in Odoo so customers can pay through a secure hosted payment page, while your team manages payment activity directly from Odoo.

## What This Module Is For

If your business uses N-Genius and you want to offer it as a payment option in Odoo, this module gives you a ready-to-use connection between your website checkout and your N-Genius account.

It is built for merchants who want a simple payment experience for customers and an easy payment management flow for internal teams.

## Main Benefits

- Offer N-Genius as a payment option on checkout
- Let customers pay on a secure hosted payment page
- Keep payment status in sync with Odoo
- Support test and live environments
- Process full refunds from Odoo
- Reduce manual payment follow-up for your team

## Customer Experience

When a customer selects N-Genius during checkout, they are redirected to the N-Genius payment page to complete the payment securely. After payment, they are sent back to your Odoo website and the order payment status is updated accordingly.

This means card details are handled on the N-Genius side, giving customers a familiar and trusted payment experience.

## Odoo Experience

From Odoo, your team can:

- enable or disable the provider
- switch between sandbox and production
- monitor payment progress
- see successful and failed transactions
- issue full refunds when available

## Key Features

- N-Genius payment provider for Odoo 19
- Secure hosted checkout flow
- Support for common card payments
- Automatic payment status updates
- Full refund support
- Sandbox and production configuration
- Easy setup from the Odoo payment provider screen

## Best For

- online stores running on Odoo
- businesses already using N-Genius Online
- merchants who want a secure redirect payment flow
- teams who want payment operations handled inside Odoo

## Simple Setup

1. Install the module in Odoo.
2. Open the N-Genius payment provider settings.
3. Add your API key and outlet reference.
4. Choose test mode or live mode.
5. Configure the N-Genius webhook in the merchant portal to point to your Odoo endpoint:
   `https://<your-odoo-domain>/payment/ngenius/webhook`
6. Use an HTTPS endpoint, configure a custom header key and value in both N-Genius and Odoo, and complete N-Genius webhook whitelisting for sandbox/live.
7. Publish the provider and start accepting payments.

## Requirements

- Odoo 19.0
- an active N-Genius account
- N-Genius credentials for your business account

## Notes

- The module uses a hosted payment page for a safer customer checkout journey.
- Full refunds are supported.
- Sandbox mode is available for testing before going live.
- Automatic backend status updates depend on a working N-Genius webhook configuration.
- The module validates webhook custom headers, but it does not currently decrypt encrypted webhook payloads from the optional N-Genius webhook-encryption feature.

## Support

- Author: Ashraf
- Website: [www.ashrf.in](https://www.ashrf.in)
- Support: [connect@ashrf.in](mailto:connect@ashrf.in)

## License

This module is released under LGPL-3. See `LICENSE` for details.
