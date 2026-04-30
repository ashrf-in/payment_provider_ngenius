from odoo import models


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def register_as_main_attachment(self, force=True):
        super().register_as_main_attachment(force=force)
        if self.env.context.get('skip_vendor_bill_ai_autoparse'):
            return

        move_attachments = self.filtered(lambda attachment: attachment.res_model == 'account.move')
        for move in self.env['account.move'].browse(move_attachments.mapped('res_id')).exists():
            if move._vendor_bill_ai_is_auto_enabled() and move._vendor_bill_ai_has_supported_main_attachment():
                move._vendor_bill_ai_enqueue_parse(force=False, replace_lines=move._vendor_bill_ai_can_replace_lines())