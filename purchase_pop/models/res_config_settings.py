# -*- coding: utf-8 -*-

from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pop_category_ids = fields.Many2many(
        related='company_id.pop_category_ids',
        readonly=False,
        string="Allowed POP Categories"
    )
