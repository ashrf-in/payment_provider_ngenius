import logging
import re
from difflib import SequenceMatcher

from markupsafe import Markup

from odoo import SUPERUSER_ID, _, api, fields, models, Command
from odoo.exceptions import UserError
from odoo.tools import formatLang


_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _register_hook(self):
        result = super()._register_hook()
        model_cls = type(self)
        if getattr(model_cls, '_vendor_bill_ai_runtime_wrapped', False):
            return result

        original_get_edi_decoder = model_cls._get_edi_decoder
        original_needs_auto_extract = getattr(model_cls, '_needs_auto_extract', None)

        @api.model
        def _vendor_bill_ai_runtime_get_edi_decoder(move, file_data, new=False):
            decoder_info = move._vendor_bill_ai_get_decoder_info(file_data)
            if decoder_info:
                return decoder_info
            return original_get_edi_decoder(move, file_data, new)

        def _vendor_bill_ai_runtime_needs_auto_extract(move, new_document=False):
            move.ensure_one()
            if move._vendor_bill_ai_should_disable_auto_extract():
                return False
            if original_needs_auto_extract:
                return original_needs_auto_extract(move, new_document)
            return False

        model_cls._get_edi_decoder = _vendor_bill_ai_runtime_get_edi_decoder
        model_cls._needs_auto_extract = _vendor_bill_ai_runtime_needs_auto_extract
        model_cls._vendor_bill_ai_runtime_wrapped = True
        return result

    vendor_bill_ai_state = fields.Selection(
        [
            ('not_requested', 'Not Requested'),
            ('queued', 'Queued'),
            ('processing', 'Processing'),
            ('applied', 'Applied'),
            ('warning', 'Applied With Warning'),
            ('error', 'Failed'),
        ],
        string='Vendor Bill AI State',
        default='not_requested',
        copy=False,
        readonly=True,
    )
    vendor_bill_ai_message = fields.Text(string='Vendor Bill AI Message', copy=False, readonly=True)
    vendor_bill_ai_result = fields.Json(string='Vendor Bill AI Result', copy=False, readonly=True)
    vendor_bill_ai_confidence = fields.Float(string='Vendor Bill AI Confidence', copy=False, readonly=True)
    vendor_bill_ai_last_run = fields.Datetime(string='Vendor Bill AI Last Run', copy=False, readonly=True)
    vendor_bill_ai_attachment_checksum = fields.Char(string='Vendor Bill AI Attachment Checksum', copy=False, readonly=True)
    vendor_bill_ai_can_parse = fields.Boolean(compute='_compute_vendor_bill_ai_can_parse')

    @api.depends('move_type', 'state', 'message_main_attachment_id', 'company_id.vendor_bill_ai_mode')
    def _compute_vendor_bill_ai_can_parse(self):
        service = self.env['account.vendor.bill.ai.service']
        for move in self:
            company = move._vendor_bill_ai_company()
            move.vendor_bill_ai_can_parse = (
                move.is_purchase_document(include_receipts=True)
                and move.state == 'draft'
                and move._vendor_bill_ai_has_supported_main_attachment()
                and company.vendor_bill_ai_mode != 'disabled'
                and move._vendor_bill_ai_can_replace_lines()
                and service.has_data_transfer_consent(company)
                and service.is_configured(company)
            )

    def _vendor_bill_ai_company(self):
        self.ensure_one()
        return self.company_id or self.env.company

    def _vendor_bill_ai_has_supported_main_attachment(self):
        self.ensure_one()
        attachment = self.message_main_attachment_id
        return bool(attachment and self._vendor_bill_ai_is_supported_attachment(attachment))

    def _vendor_bill_ai_is_supported_attachment(self, attachment):
        mimetype = attachment.mimetype or ''
        name = (attachment.name or '').lower()
        return mimetype == 'application/pdf' or mimetype.startswith('image/') or name.endswith(('.pdf', '.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff'))

    def _vendor_bill_ai_can_replace_lines(self):
        self.ensure_one()
        lines = self.invoice_line_ids.filtered(lambda line: line.display_type == 'product')
        return not lines or all(lines.mapped('is_imported'))

    def _vendor_bill_ai_is_auto_enabled(self):
        self.ensure_one()
        company = self._vendor_bill_ai_company()
        service = self.env['account.vendor.bill.ai.service']
        return (
            company.vendor_bill_ai_mode == 'auto'
            and self.is_purchase_document(include_receipts=True)
            and service.has_data_transfer_consent(company)
            and service.is_configured(company)
        )

    def action_vendor_bill_ai_parse(self):
        self.ensure_one()
        if not self._vendor_bill_ai_has_supported_main_attachment():
            raise UserError(_('Attach a PDF or image to the vendor bill before parsing it with AI.'))
        if self.state != 'draft' or not self.is_purchase_document(include_receipts=True):
            raise UserError(_('Only draft vendor bills can be parsed with AI.'))
        if not self._vendor_bill_ai_can_replace_lines():
            raise UserError(_('This bill already contains manual invoice lines. Remove them before reparsing with AI.'))

        self._vendor_bill_ai_process(force=True, replace_lines=True, raise_on_error=True)
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_vendor_bill_ai_parse_batch(self):
        moves = self.filtered(lambda move: move.vendor_bill_ai_can_parse)
        if not moves:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Vendor Bill AI Parser'),
                    'message': _('No eligible draft vendor bills with supported attachments were found.'),
                    'type': 'warning',
                    'sticky': False,
                },
            }

        moves._vendor_bill_ai_enqueue_parse(force=True, replace_lines=True)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Vendor Bill AI Parser'),
                'message': _('Queued AI parsing for %(count)s vendor bills.', count=len(moves)),
                'type': 'info',
                'sticky': False,
            },
        }

    def _vendor_bill_ai_enqueue_parse(self, force=False, replace_lines=False):
        moves = self.filtered(lambda move: move._vendor_bill_ai_has_supported_main_attachment())
        if not moves:
            return

        moves.write({
            'vendor_bill_ai_state': 'queued',
            'vendor_bill_ai_message': False,
        })
        move_ids = moves.ids

        @self.env.cr.postcommit.add
        def _process_vendor_bill_ai_queue():
            with self.env.registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                queued_moves = env['account.move'].browse(move_ids).exists()
                for move in queued_moves:
                    move._vendor_bill_ai_process(force=force, replace_lines=replace_lines, raise_on_error=False)
                    cr.commit()

    def _vendor_bill_ai_process(self, force=False, replace_lines=False, raise_on_error=False):
        self.ensure_one()
        try:
            self._vendor_bill_ai_check_preconditions()
            attachment = self.message_main_attachment_id
            if (
                not force
                and self.vendor_bill_ai_attachment_checksum
                and self.vendor_bill_ai_attachment_checksum == attachment.checksum
                and self.vendor_bill_ai_state in ('applied', 'warning')
            ):
                return False

            self.write({
                'vendor_bill_ai_state': 'processing',
                'vendor_bill_ai_message': False,
            })

            result = self.env['account.vendor.bill.ai.service'].parse_bill(self, attachment)
            warnings = self._vendor_bill_ai_apply_result(result, replace_lines=replace_lines)
            warnings.extend(result.get('warnings', []))
            warnings = [warning for warning in warnings if warning]
            state = 'warning' if warnings or self._vendor_bill_ai_is_below_threshold(result) else 'applied'
            status_message = '\n'.join(dict.fromkeys(warnings)) or False

            self.write({
                'vendor_bill_ai_state': state,
                'vendor_bill_ai_message': status_message,
                'vendor_bill_ai_result': result,
                'vendor_bill_ai_confidence': result.get('confidence') or 0.0,
                'vendor_bill_ai_last_run': fields.Datetime.now(),
                'vendor_bill_ai_attachment_checksum': attachment.checksum,
            })
            self._vendor_bill_ai_log_success(result, warnings)
            return True
        except Exception as error:
            message = error.args[0] if error.args else str(error)
            if not isinstance(error, UserError):
                _logger.exception('Vendor bill AI parsing failed on move %s', self.id)
            self.write({
                'vendor_bill_ai_state': 'error',
                'vendor_bill_ai_message': message,
                'vendor_bill_ai_last_run': fields.Datetime.now(),
            })
            if raise_on_error:
                if isinstance(error, UserError):
                    raise
                raise UserError(message) from error
            return False

    def _vendor_bill_ai_check_preconditions(self):
        self.ensure_one()
        service = self.env['account.vendor.bill.ai.service']
        company = self._vendor_bill_ai_company()
        if not self.is_purchase_document(include_receipts=True):
            raise UserError(_('Only vendor bills and vendor receipts can be parsed with AI.'))
        if self.state != 'draft':
            raise UserError(_('Only draft vendor bills can be parsed with AI.'))
        if not self._vendor_bill_ai_has_supported_main_attachment():
            raise UserError(_('Attach a supported PDF or image before parsing this vendor bill.'))
        if not service.has_data_transfer_consent(company):
            raise UserError(_('Enable external AI data transfer consent in Accounting settings before parsing vendor bills.'))
        if not service.is_configured(company):
            raise UserError(_('Configure the Vendor Bill AI Parser settings and API key before parsing bills.'))

    def _vendor_bill_ai_is_below_threshold(self, result):
        confidence = result.get('confidence')
        return bool(confidence and confidence < self._vendor_bill_ai_company().vendor_bill_ai_confidence_threshold)

    def _vendor_bill_ai_apply_result(self, result, replace_lines=False):
        warnings = []
        partner = self._vendor_bill_ai_get_or_create_partner(result.get('vendor') or {})
        currency = self._vendor_bill_ai_get_currency(result.get('currency'))
        partner_bank = self._vendor_bill_ai_get_partner_bank(partner, result.get('vendor') or {}) if partner else False
        po_references = result.get('purchase_order_references') or []

        if result.get('document_type') == 'vendor_credit_note' and self.move_type == 'in_invoice':
            self.move_type = 'in_refund'

        with self._get_edi_creation() as move_form:
            if partner:
                move_form.partner_id = partner
            if currency and move_form.currency_id != currency:
                move_form.currency_id = currency
            if result.get('invoice_date'):
                move_form.invoice_date = result['invoice_date']
            if result.get('due_date'):
                move_form.invoice_date_due = result['due_date']
            if result.get('invoice_number'):
                move_form.ref = result['invoice_number']
            if result.get('payment_reference'):
                move_form.payment_reference = result['payment_reference']
            if po_references:
                move_form.invoice_origin = ', '.join(po_references)
            if partner_bank and 'partner_bank_id' in move_form._fields:
                move_form.partner_bank_id = partner_bank

            if replace_lines and result.get('lines'):
                move_form.invoice_line_ids = [
                    Command.clear(),
                    *(Command.create({'name': line_vals['description']}) for line_vals in result['lines'])
                ]
            elif result.get('lines'):
                warnings.append(_('Existing imported lines were preserved because line replacement was not requested.'))

        if replace_lines and result.get('lines'):
            with self._get_edi_creation() as move_form:
                created_lines = move_form.invoice_line_ids[-len(result['lines']):]
                for line, parsed_line in zip(created_lines, result['lines'], strict=True):
                    self._vendor_bill_ai_apply_line(line, parsed_line)

        if po_references:
            self._find_and_set_purchase_orders(
                po_references,
                partner.id if partner else self.partner_id.id,
                result.get('totals', {}).get('total') or self.amount_total,
                from_ocr=True,
                timeout=4,
            )

        warnings.extend(self._vendor_bill_ai_validate_totals(result))
        if not partner:
            warnings.append(_('The parser could not match a vendor in Odoo.'))
        return warnings

    def _vendor_bill_ai_apply_line(self, line, parsed_line):
        product = self._vendor_bill_ai_get_product(parsed_line)
        if product:
            line.product_id = product
        elif hasattr(line, '_onchange_name_predictive'):
            line._onchange_name_predictive()

        quantity = parsed_line.get('quantity') or 1.0
        subtotal = parsed_line.get('subtotal')
        unit_price = parsed_line.get('unit_price')
        if unit_price is None and subtotal is not None:
            unit_price = subtotal / quantity if quantity else subtotal
        if unit_price is None:
            unit_price = 0.0

        line.write({
            'name': parsed_line['description'],
            'quantity': quantity,
            'price_unit': unit_price,
        })

        matched_taxes = self._vendor_bill_ai_get_taxes(line, parsed_line)
        if matched_taxes:
            line.tax_ids = [Command.set(matched_taxes.ids)]

        if not line.account_id:
            account = self._vendor_bill_ai_get_account(line)
            if account:
                line.account_id = account

        line.is_imported = True

    def _vendor_bill_ai_get_or_create_partner(self, vendor_values):
        company = self._vendor_bill_ai_company()
        name = vendor_values.get('name')
        vat = self._vendor_bill_ai_normalize_identifier(vendor_values.get('vat'))
        email = vendor_values.get('email')

        partner = self._vendor_bill_ai_find_partner(vat=vat, email=email, name=name)
        if partner or not company.vendor_bill_ai_auto_create_vendor:
            return partner

        if not (name or vat):
            return False

        return self.env['res.partner'].with_context(mail_create_nosubscribe=True).create({
            'name': name or vat,
            'vat': vat or False,
            'email': email or False,
            'phone': vendor_values.get('phone') or False,
            'supplier_rank': 1,
            'company_id': company.id,
        })

    def _vendor_bill_ai_find_partner(self, vat=False, email=False, name=False):
        Partner = self.env['res.partner']
        domain = [*Partner._check_company_domain(self._vendor_bill_ai_company())]

        if vat:
            exact = Partner.search(domain + [('vat', '=ilike', vat)], limit=1)
            if exact:
                return exact
            possible_partners = Partner.search(domain + [('vat', '!=', False)], limit=200)
            for partner in possible_partners:
                if self._vendor_bill_ai_normalize_identifier(partner.vat) == vat:
                    return partner

        if email:
            partner = Partner.search(domain + [('email', '=ilike', email)], order='supplier_rank desc', limit=1)
            if partner:
                return partner

        if not name:
            return False

        partner = Partner.search(domain + [('name', '=ilike', name)], order='supplier_rank desc', limit=1)
        if partner:
            return partner

        tokens = [token for token in re.split(r'\W+', name.lower()) if len(token) >= 3]
        if not tokens:
            return False
        candidates = Partner.search(domain + [('supplier_rank', '>', 0), ('name', 'ilike', tokens[0])], limit=50)
        scored_candidates = sorted(
            ((candidate, SequenceMatcher(None, name.lower(), (candidate.name or '').lower()).ratio()) for candidate in candidates),
            key=lambda candidate: candidate[1],
            reverse=True,
        )
        if scored_candidates and scored_candidates[0][1] >= 0.85:
            return scored_candidates[0][0]
        return False

    def _vendor_bill_ai_get_partner_bank(self, partner, vendor_values):
        company = self._vendor_bill_ai_company()
        iban = self._vendor_bill_ai_normalize_identifier(vendor_values.get('iban'))
        if not partner or not iban or 'res.partner.bank' not in self.env.registry:
            return False
        bank_model = self.env['res.partner.bank'].with_context({
            key: value for key, value in self.env.context.items()
            if key != 'default_journal_id'
        })
        bank = bank_model.search([
            *bank_model._check_company_domain(company),
            ('acc_number', '=ilike', iban),
        ], limit=1)
        if bank:
            return bank
        return bank_model.create({
            'partner_id': partner.id,
            'acc_number': iban,
            'company_id': company.id,
            'currency_id': self.currency_id.id,
        })

    def _vendor_bill_ai_get_currency(self, currency_value):
        if not currency_value:
            return False
        Currency = self.env['res.currency'].with_context(active_test=False)
        for operator in ('=ilike', 'ilike'):
            currency = Currency.search([
                '|', '|',
                ('name', operator, currency_value),
                ('symbol', operator, currency_value),
                ('currency_unit_label', operator, currency_value),
            ], limit=1)
            if currency:
                return currency
        return False

    def _vendor_bill_ai_get_product(self, parsed_line):
        product_code = parsed_line.get('product_code')
        description = parsed_line.get('description')
        Product = self.env['product.product']

        if product_code:
            product = Product.search(['|', ('default_code', '=ilike', product_code), ('barcode', '=ilike', product_code)], limit=1)
            if product:
                return product

        if 'product.supplierinfo' in self.env.registry and self.partner_id and (product_code or description):
            supplierinfo_domain = [('partner_id', 'child_of', self.partner_id.ids)]
            if product_code:
                supplierinfo_domain = ['&', *supplierinfo_domain, ('product_code', '=ilike', product_code)]
            elif description:
                supplierinfo_domain = ['&', *supplierinfo_domain, ('product_name', 'ilike', description)]
            supplierinfo = self.env['product.supplierinfo'].search(supplierinfo_domain, limit=1)
            if supplierinfo and supplierinfo.product_tmpl_id.product_variant_id:
                return supplierinfo.product_tmpl_id.product_variant_id

        if description:
            product = Product.search([('name', '=ilike', description)], limit=1)
            if product:
                return product
            product = Product.search([('name', 'ilike', description)], limit=1)
            if product:
                return product
        return False

    def _vendor_bill_ai_get_taxes(self, line, parsed_line):
        company = self._vendor_bill_ai_company()
        tax_commands = self.env['account.tax']
        for parsed_tax in parsed_line.get('taxes') or []:
            rate = parsed_tax.get('rate')
            if rate is None:
                continue
            if hasattr(line, '_predict_specific_tax'):
                predicted = line._predict_specific_tax(line.move_id, line.name, line.partner_id, 'percent', rate, 'purchase')
                if predicted:
                    predicted_taxes = self.env['account.tax'].browse(predicted)
                    if predicted_taxes:
                        tax_commands |= predicted_taxes
                        continue
            domain = [
                *self.env['account.tax']._check_company_domain(company),
                ('type_tax_use', '=', 'purchase'),
                ('amount_type', '=', 'percent'),
                ('amount', '>=', rate - 0.0001),
                ('amount', '<=', rate + 0.0001),
            ]
            tax_candidates = self.env['account.tax'].search(domain)
            if parsed_tax.get('name'):
                named_candidates = tax_candidates.filtered(lambda tax: parsed_tax['name'].lower() in (tax.name or '').lower())
                if named_candidates:
                    tax_candidates = named_candidates
            if parsed_tax.get('price_included'):
                included_candidates = tax_candidates.filtered('price_include')
                if included_candidates:
                    tax_candidates = included_candidates
            if tax_candidates:
                tax_commands |= tax_candidates[:1]
        return tax_commands

    def _vendor_bill_ai_get_account(self, line):
        if line.account_id:
            return line.account_id
        if hasattr(line, '_predict_account'):
            predicted_account_id = line._predict_account()
            if predicted_account_id:
                return self.env['account.account'].browse(predicted_account_id)
        return self.env['account.account'].search([
            *self.env['account.account']._check_company_domain(self._vendor_bill_ai_company()),
            ('internal_group', '=', 'expense'),
            ('deprecated', '=', False),
        ], limit=1)

    def _vendor_bill_ai_validate_totals(self, result):
        warnings = []
        totals = result.get('totals') or {}
        line_count = len(result.get('lines') or []) or 1
        tolerance = max(self.currency_id.rounding * line_count, 0.05)

        expected_total = totals.get('total')
        if expected_total is not None and abs(self.amount_total - expected_total) > tolerance:
            warnings.append(_(
                'The parsed total %(expected)s does not match the generated bill total %(actual)s.',
                expected=formatLang(self.env, expected_total, currency_obj=self.currency_id),
                actual=formatLang(self.env, self.amount_total, currency_obj=self.currency_id),
            ))

        expected_untaxed = totals.get('untaxed')
        if expected_untaxed is not None and abs(self.amount_untaxed - expected_untaxed) > tolerance:
            warnings.append(_(
                'The parsed untaxed amount %(expected)s does not match the generated untaxed amount %(actual)s.',
                expected=formatLang(self.env, expected_untaxed, currency_obj=self.currency_id),
                actual=formatLang(self.env, self.amount_untaxed, currency_obj=self.currency_id),
            ))
        return warnings

    def _vendor_bill_ai_log_success(self, result, warnings):
        self.ensure_one()
        summary = [_('Vendor Bill AI parser updated this bill from the main attachment.')]
        if self.partner_id:
            summary.append(_('Vendor: %s', self.partner_id.display_name))
        if self.ref:
            summary.append(_('Vendor Reference: %s', self.ref))
        if result.get('totals', {}).get('total') is not None:
            summary.append(_('Parsed Total: %s', formatLang(self.env, result['totals']['total'], currency_obj=self.currency_id)))
        if warnings:
            summary.append(_('Warnings: %s', '; '.join(dict.fromkeys(warnings))))
        self._track_set_author(self.env.ref('base.partner_root'))
        self.message_post(body=Markup('<br/>').join(summary))

    def _vendor_bill_ai_normalize_identifier(self, value):
        if not value:
            return False
        return re.sub(r'[^A-Z0-9]', '', value.upper())

    def _needs_auto_extract(self, new_document=False):
        self.ensure_one()
        if self._vendor_bill_ai_should_disable_auto_extract():
            return False
        parent = super()
        if hasattr(parent, '_needs_auto_extract'):
            return parent._needs_auto_extract(new_document)
        return False

    def _vendor_bill_ai_should_disable_auto_extract(self):
        self.ensure_one()
        return self._vendor_bill_ai_is_auto_enabled()

    @api.model
    def _get_import_file_type(self, file_data):
        mimetype = file_data.get('mimetype') or ''
        name = (file_data.get('name') or '').lower()
        if mimetype.startswith('image/') or name.endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff')):
            if mimetype.endswith('png') or name.endswith('.png'):
                return 'png'
            if mimetype.endswith('jpeg') or mimetype.endswith('jpg') or name.endswith(('.jpg', '.jpeg')):
                return 'jpg'
            return 'image'
        return super()._get_import_file_type(file_data)

    @api.model
    def _import_vendor_bill_ai(self, invoice, file_data, new=False):
        if invoice.invoice_line_ids:
            return invoice._reason_cannot_decode_has_invoice_lines()
        if not invoice._vendor_bill_ai_is_auto_enabled():
            return invoice.env._('Automatic AI parsing does not apply to this document.')

        invoice.with_context(skip_vendor_bill_ai_autoparse=True)._message_set_main_attachment_id(
            file_data['attachment'],
            force=True,
            filter_xml=False,
        )
        invoice._vendor_bill_ai_process(force=True, replace_lines=True, raise_on_error=False)
        return False

    @api.model
    def _vendor_bill_ai_get_decoder_info(self, file_data):
        company = self.company_id or self.env.company
        service = self.env['account.vendor.bill.ai.service']
        if (
            company.vendor_bill_ai_mode == 'auto'
            and service.has_data_transfer_consent(company)
            and service.is_configured(company)
            and file_data.get('attachment')
            and file_data.get('import_file_type') in {'pdf', 'jpg', 'png', 'image'}
        ):
            return {
                'decoder': self._import_vendor_bill_ai,
                'priority': 30 if file_data.get('import_file_type') == 'pdf' else 25,
            }
        return None

    def _get_edi_decoder(self, file_data, new=False):
        decoder_info = self._vendor_bill_ai_get_decoder_info(file_data)
        if decoder_info:
            return decoder_info
        return super()._get_edi_decoder(file_data, new)