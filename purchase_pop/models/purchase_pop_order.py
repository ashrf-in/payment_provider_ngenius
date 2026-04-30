# -*- coding: utf-8 -*-

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class PurchasePopOrder(models.Model):
    _name = 'purchase.pop.order'
    _description = 'Point of Purchase Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(required=True, copy=False, default='New', tracking=True)
    partner_id = fields.Many2one('res.partner', string='Vendor', required=True, tracking=True, index=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company.id, index=True)
    currency_id = fields.Many2one('res.currency', compute='_compute_currency_id', store=True, readonly=True)
    date_order = fields.Datetime(default=fields.Datetime.now, required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancel', 'Cancelled'),
    ], default='draft', required=True, tracking=True)
    note = fields.Text()
    order_line_ids = fields.One2many('purchase.pop.order.line', 'order_id', string='Lines', copy=False)
    purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order', copy=False, readonly=True, tracking=True)
    amount_total = fields.Monetary(compute='_compute_amount_total', store=True)
    line_count = fields.Integer(compute='_compute_line_count')

    @api.depends('purchase_order_id.amount_total', 'order_line_ids.price_subtotal')
    def _compute_amount_total(self):
        for order in self:
            if order.purchase_order_id:
                order.amount_total = order.purchase_order_id.amount_total
            else:
                order.amount_total = sum(order.order_line_ids.mapped('price_subtotal'))

    @api.depends('company_id', 'purchase_order_id.currency_id')
    def _compute_currency_id(self):
        for order in self:
            order.currency_id = order.purchase_order_id.currency_id or order.company_id.currency_id

    @api.depends('order_line_ids')
    def _compute_line_count(self):
        for order in self:
            order.line_count = len(order.order_line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('purchase.pop') or 'New'
        return super().create(vals_list)

    def action_cancel(self):
        for order in self:
            if order.state == 'confirmed' and order.purchase_order_id:
                raise UserError(
                    _('Cannot cancel POP order %s: it is linked to purchase order %s. Cancel the purchase order first.')
                    % (order.name, order.purchase_order_id.name)
                )
            order.state = 'cancel'

    def action_open_purchase_order(self):
        self.ensure_one()
        if not self.purchase_order_id:
            raise UserError(_('This POP order is not linked to a purchase order yet.'))
        return {
            'type': 'ir.actions.act_window',
            'name': self.purchase_order_id.name,
            'res_model': 'purchase.order',
            'res_id': self.purchase_order_id.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def action_print_receipt_order(self):
        self.ensure_one()
        if not self.purchase_order_id:
            raise UserError(_('This POP order is not linked to a purchase order yet.'))
        return self._get_receipt_report_action(self.purchase_order_id)

    @api.model
    def action_print_receipt_order_from_purchase_order(self, purchase_order_id):
        purchase_order = self.env['purchase.order'].browse(purchase_order_id).exists()
        if not purchase_order:
            raise UserError(_('Purchase order not found.'))
        return self._get_receipt_report_action(purchase_order)

    # -------------------------------------------------------------------------
    # RPC methods called from the POP terminal OWL component
    # -------------------------------------------------------------------------

    @api.model
    def get_pop_bootstrap_data(self):
        company = self.env.company
        currency = company.currency_id
        vendors = self.env['res.partner'].search_read(
            [('supplier_rank', '>', 0), ('parent_id', '=', False), ('active', '=', True)],
            ['id', 'name', 'display_name'],
            order='name',
            limit=500,
        )
        categories = self._get_purchaseable_categories()
        # Use a direct count to avoid inflated totals from parent category rollups
        product_domain = [('purchase_ok', '=', True), ('active', '=', True)]
        allowed_parent_cats = company.pop_category_ids
        if allowed_parent_cats:
            allowed_child_cats = self.env['product.category'].search([('id', 'child_of', allowed_parent_cats.ids)])
            product_domain.append(('categ_id', 'in', allowed_child_cats.ids))
        total_products = self.env['product.product'].search_count(product_domain)
        warehouses = self.env['stock.warehouse'].search_read(
            [('company_id', '=', company.id)],
            ['id', 'name', 'code'],
            order='sequence, name',
        )
        return {
            'vendors': vendors,
            'categories': categories,
            'total_products': total_products,
            'warehouses': warehouses,
            'currency': {
                'id': currency.id,
                'symbol': currency.symbol,
                'position': currency.position,
                'decimal_places': currency.decimal_places,
            },
        }

    @api.model
    def get_pop_products(self, partner_id=False, category_id=False, search_term=False, warehouse_id=False):
        company = self.env.company
        partner = self.env['res.partner'].browse(partner_id).exists() if partner_id else self.env['res.partner']
        domain = [('purchase_ok', '=', True), ('active', '=', True)]
        
        allowed_parent_cats = company.pop_category_ids
        if allowed_parent_cats:
            allowed_child_cats = self.env['product.category'].search([('id', 'child_of', allowed_parent_cats.ids)])
            domain.append(('categ_id', 'in', allowed_child_cats.ids))
            
        if category_id:
            # Include the selected category and all its children for intuitive filtering
            all_cat_ids = self.env['product.category'].search([('id', 'child_of', category_id)]).ids
            domain.append(('categ_id', 'in', all_cat_ids))
        if search_term and search_term.strip():
            term = search_term.strip()
            domain += ['|', '|', '|',
                       ('name', 'ilike', term),
                       ('default_code', 'ilike', term),
                       ('barcode', '=', term),
                       ('description_purchase', 'ilike', term)]
        products = self.env['product.product'].search(domain, order='default_code, name', limit=300)
        if warehouse_id:
            products = products.with_context(warehouse=warehouse_id)
        today = fields.Date.context_today(self)
        partner_root = partner.commercial_partner_id if partner else self.env['res.partner']
        items = []
        for product in products:
            seller = product.with_company(company)._select_seller(
                partner_id=partner_root,
                quantity=1.0,
                date=today,
                uom_id=product.uom_id,
            ) if partner_root else self.env['product.supplierinfo']
            if seller:
                price = seller.currency_id._convert(
                    seller.price_discounted,
                    company.currency_id,
                    company,
                    today,
                )
                min_qty = seller.min_qty
            else:
                # Fall back to standard_price expressed in company currency
                price = product.cost_currency_id._convert(
                    product.standard_price,
                    company.currency_id,
                    company,
                    today,
                ) if product.cost_currency_id else product.standard_price
                min_qty = 0.0
            items.append({
                'id': product.id,
                'tmpl_id': product.product_tmpl_id.id,
                'name': product.display_name,
                'default_code': product.default_code or '',
                'barcode': product.barcode or '',
                'category_id': product.categ_id.id,
                'category_name': product.categ_id.complete_name,
                'uom_name': product.uom_id.display_name,
                'uom_id': product.uom_id.id,
                'min_qty': min_qty,
                'has_vendor_price': bool(seller),
                'qty_available': product.qty_available,
                'price': price,
            })
        return items

    @api.model
    def action_confirm_from_ui(self, partner_id, lines, note=False, warehouse_id=False):
        partner = self.env['res.partner'].browse(partner_id).exists()
        if not partner:
            raise UserError(_('Select a vendor before confirming the POP order.'))
        if not lines:
            raise UserError(_('Add at least one product before confirming the POP order.'))

        # Aggregate and validate lines before creating any record
        aggregated_lines = {}
        for line in lines:
            product_id = int(line.get('product_id', 0) or 0)
            quantity = float(line.get('qty', 0) or 0)
            if not product_id or quantity <= 0:
                continue
            aggregated_lines[product_id] = aggregated_lines.get(product_id, 0.0) + quantity

        if not aggregated_lines:
            raise UserError(_('Add at least one product with a positive quantity.'))

        products = self.env['product.product'].browse(list(aggregated_lines)).exists()
        if not products:
            raise UserError(_('No valid products were found to generate a purchase order.'))

        # Use sudo for purchase.order because purchase users have "confirm" workflow
        # but may lack create rights on purchase.order via standard ACL.
        PurchaseOrder = self.env['purchase.order'].sudo()
        po_line_model = self.env['purchase.order.line'].sudo()

        po_vals = {
            'partner_id': partner.id,
            'company_id': self.env.company.id,
            'note': note or False,
        }
        if warehouse_id:
            warehouse = self.env['stock.warehouse'].browse(warehouse_id).exists()
            if warehouse:
                po_vals['picking_type_id'] = warehouse.in_type_id.id
        purchase_order = PurchaseOrder.create(po_vals)

        line_commands = []
        for product in products:
            quantity = aggregated_lines[product.id]
            line_commands.append(Command.create(
                po_line_model._prepare_purchase_order_line(
                    product,
                    quantity,
                    product.uom_id,
                    purchase_order.company_id,
                    partner,
                    purchase_order,
                )
            ))

        purchase_order.write({'order_line': line_commands})

        # Confirm purchase order — creates incoming receipt via purchase_stock
        purchase_order.button_confirm()

        # Create the POP audit record NOW that the PO is confirmed
        pop_order = self.create({
            'partner_id': partner.id,
            'company_id': self.env.company.id,
            'date_order': fields.Datetime.now(),
            'note': note or False,
            'state': 'confirmed',
            'purchase_order_id': purchase_order.id,
        })
        # Backfill audit lines from the confirmed PO lines
        audit_lines = [
            Command.create({
                'product_id': po_line.product_id.id,
                'name': po_line.name,
                'product_qty': po_line.product_qty,
                'product_uom_id': po_line.product_uom_id.id,
                'price_unit': po_line.price_unit,
                'purchase_line_id': po_line.id,
            })
            for po_line in purchase_order.order_line.filtered(lambda l: not l.display_type)
        ]
        if audit_lines:
            pop_order.write({'order_line_ids': audit_lines})
        # Stamp origin on the PO so it links back to the POP reference
        purchase_order.sudo().write({'origin': pop_order.name})
        return {
            'pop_order_id': pop_order.id,
            'purchase_order_id': purchase_order.id,
            'purchase_order_name': purchase_order.name,
            'purchase_order_state': purchase_order.state,
        }

    @api.model
    def get_editable_orders(self, partner_id):
        partner = self.env['res.partner'].browse(partner_id).exists()
        if not partner:
            return []
            
        orders = self.env['purchase.order'].search([
            ('partner_id', 'child_of', partner.commercial_partner_id.id),
            ('company_id', '=', self.env.company.id),
            ('state', 'in', ['draft', 'sent', 'purchase']),
            ('receipt_status', 'in', [False, 'pending', 'partial']),
        ], order='id desc', limit=50)
        
        return [{
            'id': order.id,
            'name': order.name,
            'state': order.state,
            'amount_total': order.amount_total,
            'date_order': order.date_order.strftime('%Y-%m-%d') if order.date_order else '',
            'receipt_status': order.receipt_status or 'pending',
        } for order in orders]

    @api.model
    def get_order_lines(self, order_id):
        order = self.env['purchase.order'].browse(order_id).exists()
        if not order:
            return []
            
        lines = []
        for line in order.order_line.filtered(lambda l: not l.display_type):
            lines.append({
                'id': line.id,
                'product_id': line.product_id.id,
                'qty': line.product_qty,
                'qty_received': line.qty_received,
                'price': line.price_unit,
                'name': line.name,
            })
        return lines

    @api.model
    def action_update_from_ui(self, order_id, lines, note=False, warehouse_id=False):
        order = self.env['purchase.order'].sudo().browse(order_id).exists()
        if not order:
            raise UserError(_('Order not found.'))

        aggregated_lines = {}
        for line in lines:
            product_id = int(line.get('product_id', 0) or 0)
            quantity = float(line.get('qty', 0) or 0)
            if not product_id or quantity <= 0:
                continue
            aggregated_lines[product_id] = aggregated_lines.get(product_id, 0.0) + quantity

        # Update existing lines
        for po_line in order.order_line.filtered(lambda l: not l.display_type):
            pid = po_line.product_id.id
            if pid in aggregated_lines:
                new_qty = aggregated_lines[pid]
                if new_qty < po_line.qty_received:
                    raise UserError(_("You cannot reduce the quantity of %s below the received quantity (%s).", po_line.product_id.display_name, po_line.qty_received))
                po_line.product_qty = new_qty
                del aggregated_lines[pid]
            else:
                if po_line.qty_received > 0:
                    raise UserError(_("You cannot remove %s because it has already been partially received.", po_line.product_id.display_name))
                if order.state in ['draft', 'sent']:
                    po_line.unlink()
                else:
                    po_line.product_qty = 0

        # Create new lines
        if aggregated_lines:
            products = self.env['product.product'].browse(list(aggregated_lines)).exists()
            line_commands = []
            for product in products:
                quantity = aggregated_lines[product.id]
                line_commands.append(Command.create(
                    self.env['purchase.order.line'].sudo()._prepare_purchase_order_line(
                        product, quantity, product.uom_id, order.company_id, order.partner_id, order
                    )
                ))
            order.write({'order_line': line_commands})

        if warehouse_id and order.state in ['draft', 'sent']:
            warehouse = self.env['stock.warehouse'].browse(warehouse_id).exists()
            if warehouse:
                order.picking_type_id = warehouse.in_type_id.id
                
        if note:
            order.note = note

        # Create audit record
        pop_order = self.create({
            'partner_id': order.partner_id.id,
            'company_id': order.company_id.id,
            'date_order': fields.Datetime.now(),
            'note': note or False,
            'state': 'confirmed',
            'purchase_order_id': order.id,
        })
        audit_lines = [
            Command.create({
                'product_id': po_line.product_id.id,
                'name': po_line.name,
                'product_qty': po_line.product_qty,
                'product_uom_id': po_line.product_uom_id.id,
                'price_unit': po_line.price_unit,
                'purchase_line_id': po_line.id,
            })
            for po_line in order.order_line.filtered(lambda l: not l.display_type)
        ]
        if audit_lines:
            pop_order.write({'order_line_ids': audit_lines})

        order.write({'origin': (order.origin + ', ' + pop_order.name) if order.origin else pop_order.name})

        return {
            'pop_order_id': pop_order.id,
            'purchase_order_id': order.id,
            'purchase_order_name': order.name,
            'purchase_order_state': order.state,
            'receipt_order_count': len(self._get_receipt_orders(order)),
            'receipt_order_count': len(self._get_receipt_orders(order)),
        }

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    @api.model
    def _get_receipt_orders(self, purchase_order):
        return purchase_order.picking_ids.filtered(
            lambda picking: picking.picking_type_code == 'incoming' and picking.state != 'cancel'
        )

    @api.model
    def _get_receipt_report_action(self, purchase_order):
        pickings = self._get_receipt_orders(purchase_order)
        if not pickings:
            raise UserError(_('No receipt orders are available for purchase order %s.') % purchase_order.name)

        active_pickings = pickings.filtered(lambda picking: picking.state != 'done')
        if active_pickings:
            return self.env.ref('stock.action_report_picking').report_action(active_pickings)
        return self.env.ref('stock.action_report_delivery').report_action(pickings)

    @api.model
    def _get_purchaseable_categories(self):
        """Return all categories that have purchaseable products, not just leaf
        nodes, so the sidebar is useful when product hierarchy has depth."""
        domain = [('purchase_ok', '=', True), ('active', '=', True)]
        allowed_parent_cats = self.env.company.pop_category_ids
        if allowed_parent_cats:
            allowed_child_cats = self.env['product.category'].search([('id', 'child_of', allowed_parent_cats.ids)])
            domain.append(('categ_id', 'in', allowed_child_cats.ids))

        groups = self.env['product.product']._read_group(
            domain,
            ['categ_id'],
            ['__count'],
        )
        category_direct_counts = {cat.id: count for cat, count in groups if cat}
        if not category_direct_counts:
            return []
        # Expand to include ancestors so parent-category filtering is useful
        all_cats = self.env['product.category'].browse(list(category_direct_counts))
        # Build map: category_id -> cumulative count (children roll up)
        cumulative = dict(category_direct_counts)
        for cat in all_cats:
            parent = cat.parent_id
            while parent:
                cumulative[parent.id] = cumulative.get(parent.id, 0) + category_direct_counts.get(cat.id, 0)
                parent = parent.parent_id
                
        search_domain = [('id', 'in', list(cumulative))]
        if allowed_parent_cats:
            search_domain.append(('id', 'child_of', allowed_parent_cats.ids))
            
        categories = self.env['product.category'].search(search_domain, order='complete_name')
        return [
            {
                'id': cat.id,
                'name': cat.name,
                'complete_name': cat.complete_name,
                'parent_id': cat.parent_id.id if cat.parent_id else False,
                'product_count': cumulative.get(cat.id, 0),
                'has_children': bool(cat.child_id),
            }
            for cat in categories
        ]

    @api.model
    def get_product_purchase_history(self, product_id):
        """Return last 5 confirmed purchase order lines for the given product."""
        POLine = self.env['purchase.order.line'].sudo()
        lines = POLine.search([
            ('product_id', '=', product_id),
            ('state', 'in', ['purchase', 'done']),
            ('company_id', '=', self.env.company.id),
        ], order='id desc', limit=5)
        history = []
        for line in lines:
            history.append({
                'date': line.order_id.date_order.strftime('%Y-%m-%d') if line.order_id.date_order else '',
                'vendor': line.order_id.partner_id.display_name,
                'qty': line.product_qty,
                'price': line.price_unit,
                'uom': line.product_uom_id.display_name,
                'po_name': line.order_id.name,
            })
        return {
            'product_id': product_id,
            'history': history,
            'last_date': history[0]['date'] if history else False,
            'last_price': history[0]['price'] if history else 0,
            'last_vendor': history[0]['vendor'] if history else '',
        }


class PurchasePopOrderLine(models.Model):
    _name = 'purchase.pop.order.line'
    _description = 'Point of Purchase Order Line'
    _order = 'id'

    order_id = fields.Many2one('purchase.pop.order', required=True, ondelete='cascade', index=True)
    purchase_line_id = fields.Many2one('purchase.order.line', string='Purchase Order Line', readonly=True, ondelete='set null')
    product_id = fields.Many2one('product.product', required=True, readonly=True)
    name = fields.Text(required=True, readonly=True)
    product_qty = fields.Float(string='Quantity', required=True, digits='Product Unit', readonly=True)
    product_uom_id = fields.Many2one('uom.uom', string='Unit', required=True, readonly=True)
    currency_id = fields.Many2one(related='order_id.currency_id', string='Currency', readonly=True)
    price_unit = fields.Float(string='Unit Price', digits='Product Price', readonly=True)
    price_subtotal = fields.Monetary(compute='_compute_price_subtotal', store=True)

    @api.depends('product_qty', 'price_unit')
    def _compute_price_subtotal(self):
        for line in self:
            line.price_subtotal = line.product_qty * line.price_unit

