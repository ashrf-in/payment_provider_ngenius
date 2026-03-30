# -*- coding: utf-8 -*-

from odoo import fields, models

class ResCompany(models.Model):
    _inherit = 'res.company'

    pop_category_ids = fields.Many2many(
        'product.category',
        'company_pop_category_rel',
        'company_id',
        'category_id',
        string='Allowed POP Categories',
        help="Select Master Categories for the POP terminal. Their child categories will be listed."
    )
