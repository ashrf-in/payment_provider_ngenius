from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    vendor_bill_ai_mode = fields.Selection(
        [
            ('disabled', 'Do not parse'),
            ('manual', 'Parse on demand only'),
            ('auto', 'Parse automatically'),
        ],
        string='Vendor Bill AI Parsing',
        default='manual',
    )
    vendor_bill_ai_provider = fields.Selection(
        [
            ('openai', 'OpenAI'),
            ('openai_compatible', 'OpenAI-compatible'),
            ('google', 'Google Gemini'),
        ],
        string='Vendor Bill AI Provider',
        default='openai',
    )
    vendor_bill_ai_model = fields.Char(
        string='Vendor Bill AI Model',
        help='Leave empty to use the provider default model.',
    )
    vendor_bill_ai_base_url = fields.Char(
        string='OpenAI-compatible Base URL',
        help='Full API base URL for custom OpenAI-compatible providers, for example https://host.example/v1.',
    )
    vendor_bill_ai_data_transfer_consent = fields.Boolean(
        string='External AI Data Transfer Consent',
        help='Enable only after confirming that vendor bill attachments and extracted accounting data may be sent to the configured external AI provider.',
    )
    vendor_bill_ai_auto_create_vendor = fields.Boolean(
        string='Auto-create Vendors',
        default=True,
        help='Create a supplier automatically when the parser finds a vendor that does not exist yet.',
    )
    vendor_bill_ai_confidence_threshold = fields.Float(
        string='Minimum Confidence Threshold',
        default=0.65,
        help='Below this threshold the bill is still filled, but the result is flagged for review.',
    )
    vendor_bill_ai_timeout = fields.Integer(
        string='Vendor Bill AI Timeout',
        default=90,
        help='HTTP timeout in seconds for parser requests.',
    )
    vendor_bill_ai_extra_instructions = fields.Text(
        string='Extra Parser Instructions',
        help='Optional company-specific instructions appended to the parser prompt.',
    )