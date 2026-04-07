from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    vendor_bill_ai_mode = fields.Selection(related='company_id.vendor_bill_ai_mode', readonly=False)
    vendor_bill_ai_provider = fields.Selection(related='company_id.vendor_bill_ai_provider', readonly=False)
    vendor_bill_ai_model = fields.Char(related='company_id.vendor_bill_ai_model', readonly=False)
    vendor_bill_ai_base_url = fields.Char(related='company_id.vendor_bill_ai_base_url', readonly=False)
    vendor_bill_ai_data_transfer_consent = fields.Boolean(related='company_id.vendor_bill_ai_data_transfer_consent', readonly=False)
    vendor_bill_ai_auto_create_vendor = fields.Boolean(related='company_id.vendor_bill_ai_auto_create_vendor', readonly=False)
    vendor_bill_ai_confidence_threshold = fields.Float(related='company_id.vendor_bill_ai_confidence_threshold', readonly=False)
    vendor_bill_ai_timeout = fields.Integer(related='company_id.vendor_bill_ai_timeout', readonly=False)
    vendor_bill_ai_extra_instructions = fields.Text(related='company_id.vendor_bill_ai_extra_instructions', readonly=False)
    vendor_bill_ai_api_key = fields.Char(
        string='Vendor Bill AI API Key',
        config_parameter='account_vendor_bill_ai.api_key',
        readonly=False,
        groups='base.group_system',
        help='Shared API key for the selected provider. If empty, standard OpenAI and Google providers fall back to the existing AI module keys when available.',
    )