from unittest.mock import patch

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.account.tests.test_account_incoming_supplier_invoice import TestAccountInvoiceImportMixin
from odoo.addons.account_vendor_bill_ai.models.account_move import AccountMove
from odoo.addons.account_vendor_bill_ai.models.vendor_bill_ai_service import AccountVendorBillAIService
from odoo.exceptions import UserError
from odoo.tests import tagged


@tagged('post_install', '-at_install')
class TestVendorBillAI(AccountTestInvoicingCommon, TestAccountInvoiceImportMixin):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.company_data['company']
        cls.purchase_journal = cls.company_data['default_journal_purchase']
        cls.company.write({
            'vendor_bill_ai_mode': 'manual',
            'vendor_bill_ai_provider': 'openai',
            'vendor_bill_ai_data_transfer_consent': True,
            'vendor_bill_ai_auto_create_vendor': True,
            'vendor_bill_ai_confidence_threshold': 0.5,
        })
        cls.env['ir.config_parameter'].sudo().set_param('account_vendor_bill_ai.api_key', 'test-api-key')
        cls.purchase_tax = cls.env['account.tax'].create({
            'name': 'Vendor AI 10%',
            'amount': 10.0,
            'amount_type': 'percent',
            'type_tax_use': 'purchase',
            'company_id': cls.company.id,
            'price_include': False,
        })

    def _make_attachment(self, res_model=False, res_id=False, name='vendor_bill.pdf'):
        pdf_vals = self._get_dummy_pdf_vals()
        return self.env['ir.attachment'].create({
            'name': name,
            'raw': pdf_vals['raw'],
            'mimetype': pdf_vals['mimetype'],
            'res_model': res_model or False,
            'res_id': res_id or 0,
        })

    def _sample_payload(self):
        return {
            'document_type': 'vendor_bill',
            'vendor': {
                'name': 'ACME Supplies',
                'vat': 'BE0123456789',
                'email': 'ap@acme.test',
            },
            'invoice_number': 'INV-2026-001',
            'invoice_date': '2026-04-01',
            'due_date': '2026-04-30',
            'currency': self.company.currency_id.name,
            'payment_reference': 'RF18539007547034',
            'purchase_order_references': ['PO0001'],
            'totals': {
                'untaxed': 100.0,
                'tax': 10.0,
                'total': 110.0,
            },
            'lines': [{
                'description': 'Consulting services',
                'quantity': 1.0,
                'unit_price': 100.0,
                'subtotal': 100.0,
                'total': 110.0,
                'taxes': [{
                    'name': self.purchase_tax.name,
                    'rate': 10.0,
                    'price_included': False,
                }],
            }],
            'confidence': 0.92,
            'warnings': [],
        }

    def test_manual_parse_applies_header_and_lines(self):
        move = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'journal_id': self.purchase_journal.id,
        })
        attachment = self._make_attachment(res_model='account.move', res_id=move.id)
        move.with_context(skip_vendor_bill_ai_autoparse=True)._message_set_main_attachment_id(attachment, force=True, filter_xml=False)

        with patch.object(AccountVendorBillAIService, 'parse_bill', return_value=self._sample_payload()):
            action = move.action_vendor_bill_ai_parse()

        move.invalidate_recordset()
        self.assertEqual(action['tag'], 'reload')
        self.assertEqual(move.vendor_bill_ai_state, 'applied')
        self.assertEqual(move.partner_id.name, 'ACME Supplies')
        self.assertEqual(move.ref, 'INV-2026-001')
        self.assertEqual(str(move.invoice_date), '2026-04-01')
        self.assertEqual(str(move.invoice_date_due), '2026-04-30')
        self.assertEqual(move.payment_reference, 'RF18539007547034')
        self.assertAlmostEqual(move.amount_total, 110.0, places=2)
        product_lines = move.invoice_line_ids.filtered(lambda line: line.display_type == 'product')
        self.assertEqual(len(product_lines), 1)
        self.assertEqual(product_lines.name, 'Consulting services')
        self.assertTrue(product_lines.account_id)
        self.assertEqual(product_lines.tax_ids, self.purchase_tax)

    def test_journal_attachment_import_uses_ai_decoder(self):
        self.company.vendor_bill_ai_mode = 'auto'
        attachment = self._make_attachment()

        with patch.object(AccountVendorBillAIService, 'parse_bill', return_value=self._sample_payload()):
            invoices = self.purchase_journal.with_context(default_move_type='in_invoice')._create_document_from_attachment(attachment.ids)

        self.assertEqual(len(invoices), 1)
        bill = invoices[0]
        self.assertEqual(bill.vendor_bill_ai_state, 'applied')
        self.assertEqual(bill.message_main_attachment_id, attachment)
        self.assertEqual(bill.ref, 'INV-2026-001')
        self.assertTrue(bill.invoice_line_ids.filtered(lambda line: line.display_type == 'product'))

    def test_register_as_main_attachment_queues_auto_parse(self):
        self.company.vendor_bill_ai_mode = 'auto'
        move = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'journal_id': self.purchase_journal.id,
        })
        attachment = self._make_attachment(res_model='account.move', res_id=move.id)

        attachment.register_as_main_attachment(force=True)
        move.invalidate_recordset()

        self.assertEqual(move.message_main_attachment_id, attachment)
        self.assertEqual(move.vendor_bill_ai_state, 'queued')

    def test_register_as_main_attachment_replaces_lines_when_bill_is_empty(self):
        self.company.vendor_bill_ai_mode = 'auto'
        move = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'journal_id': self.purchase_journal.id,
        })
        attachment = self._make_attachment(res_model='account.move', res_id=move.id)

        with patch.object(AccountMove, '_vendor_bill_ai_enqueue_parse', autospec=True) as enqueue_parse:
            attachment.register_as_main_attachment(force=True)

        self.assertEqual(move.message_main_attachment_id, attachment)
        self.assertEqual(enqueue_parse.call_args.kwargs['replace_lines'], True)

    def test_manual_parse_requires_data_transfer_consent(self):
        self.company.vendor_bill_ai_data_transfer_consent = False
        move = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'journal_id': self.purchase_journal.id,
        })
        attachment = self._make_attachment(res_model='account.move', res_id=move.id)
        move.with_context(skip_vendor_bill_ai_autoparse=True)._message_set_main_attachment_id(attachment, force=True, filter_xml=False)

        with self.assertRaisesRegex(UserError, 'data transfer consent'):
            move.action_vendor_bill_ai_parse()

        move.invalidate_recordset()
        self.assertFalse(move.vendor_bill_ai_can_parse)

    def test_parse_creates_partner_bank_with_default_journal_context(self):
        payload = self._sample_payload()
        payload['vendor'] = {
            **payload['vendor'],
            'iban': 'BE12539007547035',
        }
        move = self.env['account.move'].with_context(default_journal_id=self.purchase_journal.id).create({
            'move_type': 'in_invoice',
            'journal_id': self.purchase_journal.id,
        })
        attachment = self._make_attachment(res_model='account.move', res_id=move.id)
        move.with_context(skip_vendor_bill_ai_autoparse=True)._message_set_main_attachment_id(attachment, force=True, filter_xml=False)

        with patch.object(AccountVendorBillAIService, 'parse_bill', return_value=payload):
            move.with_context(default_journal_id=self.purchase_journal.id).action_vendor_bill_ai_parse()

        move.invalidate_recordset()
        self.assertEqual(move.vendor_bill_ai_state, 'applied')
        self.assertEqual(move.partner_bank_id.acc_number, 'BE12539007547035')