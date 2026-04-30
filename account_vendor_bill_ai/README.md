# Vendor Bill AI Parser

Community-ready Odoo 19 addon for parsing vendor bill attachments with external AI providers.

## Compatibility

- Odoo 19 Community
- Odoo 19 Enterprise

The addon depends only on `account`.
If optional OCR addons such as `account_invoice_extract` are present, this module keeps priority for its own automatic AI parsing flow when enabled.

## Python Dependencies

- `requests`
- `PyPDF2`
- `python-dateutil` package providing the `dateutil` module

## Installation

1. Place the addon in your Odoo addons path.
2. Ensure the Python dependencies are installed on the server.
3. Update the apps list.
4. Install `account_vendor_bill_ai`.

## Configuration

1. Open Accounting settings.
2. Enable `AI Vendor Bill Parser`.
3. Choose the provider and model.
4. Enter the provider API key.
5. Confirm the external data transfer consent option.
6. Choose manual or automatic parsing mode.

## Deployment

Upgrade the module after each code change:

```bash
sudo systemctl stop odoo
sudo -u odoo /usr/bin/python3 /usr/bin/odoo --config /etc/odoo/odoo.conf -d <database> -u account_vendor_bill_ai --stop-after-init --http-port=8071
sudo systemctl start odoo
```

## Notes

- Automatic parsing uses the standard Odoo 19 accounting attachment import hooks available in Community.
- The addon stores its own API key in `account_vendor_bill_ai.api_key` and does not require any Enterprise AI settings module.
- When optional Enterprise OCR modules are installed, this addon suppresses OCR auto-extract for bills handled by Vendor Bill AI auto mode.