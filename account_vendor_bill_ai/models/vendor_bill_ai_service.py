import base64
import io
import json
import logging
import re

import requests
from PyPDF2 import PdfReader

from odoo import _, models
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


class AccountVendorBillAIService(models.AbstractModel):
    _name = 'account.vendor.bill.ai.service'
    _description = 'Vendor Bill AI Service'

    def has_data_transfer_consent(self, company):
        return bool(company.vendor_bill_ai_data_transfer_consent)

    def is_configured(self, company):
        provider = company.vendor_bill_ai_provider or 'openai'
        api_key = self._get_api_key(company, provider, raise_if_missing=False)
        if not api_key:
            return False
        if provider == 'openai_compatible' and not company.vendor_bill_ai_base_url:
            return False
        return True

    def parse_bill(self, move, attachment):
        company = move.company_id or move.env.company
        settings = self._get_runtime_settings(company)
        system_prompt, user_prompt = self._build_prompts(move)
        schema = self._get_json_schema()
        payload = self._call_provider(settings, attachment, system_prompt, user_prompt, schema)
        result = self._coerce_payload(payload)
        return self._normalize_payload(result)

    def _get_runtime_settings(self, company):
        provider = company.vendor_bill_ai_provider or 'openai'
        api_key = self._get_api_key(company, provider, raise_if_missing=True)
        base_url = company.vendor_bill_ai_base_url or False
        if provider == 'openai_compatible' and not base_url:
            raise UserError(_('An OpenAI-compatible base URL is required.'))
        if provider == 'openai':
            base_url = 'https://api.openai.com/v1'

        return {
            'provider': provider,
            'api_key': api_key,
            'base_url': base_url,
            'model': company.vendor_bill_ai_model or self._get_default_model(provider),
            'timeout': company.vendor_bill_ai_timeout or 90,
        }

    def _get_api_key(self, company, provider, raise_if_missing=False):
        icp = self.env['ir.config_parameter'].sudo()
        api_key = icp.get_param('account_vendor_bill_ai.api_key')
        if not api_key and raise_if_missing:
            if provider == 'openai_compatible':
                raise UserError(_('No API key set for the OpenAI-compatible vendor bill parser.'))
            if provider == 'google':
                raise UserError(_('No Google Gemini API key set for the vendor bill parser.'))
            raise UserError(_('No OpenAI API key set for the vendor bill parser.'))
        return api_key

    def _get_default_model(self, provider):
        return {
            'openai': 'gpt-4.1-mini',
            'openai_compatible': 'gpt-4.1-mini',
            'google': 'gemini-2.5-pro',
        }[provider]

    def _build_prompts(self, move):
        company = move.company_id
        system_prompt = "\n".join(part for part in [
            'You extract structured accounting data from vendor bills for Odoo.',
            'Return JSON only. Do not wrap the answer in markdown.',
            'Never invent vendors, amounts, dates, taxes, bank accounts, or purchase order references.',
            'Omit fields that are not visible or not reliable enough to extract.',
            'Use plain decimal numbers without currency symbols.',
            'Use ISO dates in YYYY-MM-DD format.',
            'Set document_type to vendor_credit_note only when the document is clearly a supplier credit note.',
            'Lines must cover the bill contents. If detailed lines are unreadable, return one summary line using the best visible untaxed amount.',
            'subtotal must be tax-exclusive. total should be tax-inclusive when visible.',
            'unit_price should be tax-exclusive when derivable from the document.',
            'taxes.rate must be the percentage value, for example 15 for 15%.',
            'confidence must be a number between 0 and 1.',
            company.vendor_bill_ai_extra_instructions or '',
        ] if part)
        user_prompt = "\n".join([
            f'Company name: {company.name}',
            f'Company country code: {company.country_id.code or ""}',
            f'Company currency: {company.currency_id.name}',
            'Parse the attached supplier-side payable document for an Odoo vendor bill draft.',
            'Prioritize vendor identity, vendor invoice number, document dates, currency, purchase order references, totals, and line items.',
            'Do not transform the business meaning of the document.',
        ])
        return system_prompt, user_prompt

    def _get_json_schema(self):
        return {
            'type': 'object',
            'properties': {
                'document_type': {'type': 'string'},
                'vendor': {
                    'type': 'object',
                    'properties': {
                        'name': {'type': 'string'},
                        'vat': {'type': 'string'},
                        'email': {'type': 'string'},
                        'phone': {'type': 'string'},
                        'iban': {'type': 'string'},
                    },
                    'additionalProperties': False,
                },
                'invoice_number': {'type': 'string'},
                'invoice_date': {'type': 'string'},
                'due_date': {'type': 'string'},
                'currency': {'type': 'string'},
                'payment_reference': {'type': 'string'},
                'purchase_order_references': {
                    'type': 'array',
                    'items': {'type': 'string'},
                },
                'totals': {
                    'type': 'object',
                    'properties': {
                        'untaxed': {'type': 'number'},
                        'tax': {'type': 'number'},
                        'total': {'type': 'number'},
                    },
                    'additionalProperties': False,
                },
                'lines': {
                    'type': 'array',
                    'items': {
                        'type': 'object',
                        'properties': {
                            'description': {'type': 'string'},
                            'product_code': {'type': 'string'},
                            'quantity': {'type': 'number'},
                            'unit_price': {'type': 'number'},
                            'subtotal': {'type': 'number'},
                            'total': {'type': 'number'},
                            'taxes': {
                                'type': 'array',
                                'items': {
                                    'type': 'object',
                                    'properties': {
                                        'name': {'type': 'string'},
                                        'rate': {'type': 'number'},
                                        'price_included': {'type': 'boolean'},
                                    },
                                    'additionalProperties': False,
                                },
                            },
                        },
                        'additionalProperties': False,
                    },
                },
                'confidence': {'type': 'number'},
                'warnings': {
                    'type': 'array',
                    'items': {'type': 'string'},
                },
            },
            'additionalProperties': False,
        }

    def _call_provider(self, settings, attachment, system_prompt, user_prompt, schema):
        provider = settings['provider']
        if provider == 'google':
            return self._call_google(settings, attachment, system_prompt, user_prompt, schema)
        if provider == 'openai_compatible':
            return self._call_openai_compatible(settings, attachment, system_prompt, user_prompt, schema)
        return self._call_openai_responses(settings, attachment, system_prompt, user_prompt, schema)

    def _call_openai_compatible(self, settings, attachment, system_prompt, user_prompt, schema):
        try:
            return self._call_openai_responses(settings, attachment, system_prompt, user_prompt, schema)
        except UserError as error:
            if (attachment.mimetype or '').startswith('image/'):
                return self._call_openai_chat(settings, attachment, system_prompt, user_prompt)
            extracted_text = self._extract_pdf_text(attachment.raw)
            if extracted_text:
                return self._call_openai_chat(settings, None, system_prompt, f'{user_prompt}\n\nDocument text:\n{extracted_text}')
            raise UserError(_(
                '%(message)s\n\nThe selected OpenAI-compatible endpoint must support the OpenAI Responses API with file inputs, or the PDF must contain extractable text for fallback parsing.',
                message=error.args[0],
            ))

    def _call_openai_responses(self, settings, attachment, system_prompt, user_prompt, schema):
        content = [
            {'type': 'input_text', 'text': user_prompt},
            self._build_openai_attachment_part(attachment),
        ]
        body = {
            'model': settings['model'],
            'store': False,
            'input': [
                {
                    'role': 'system',
                    'content': [{'type': 'input_text', 'text': system_prompt}],
                },
                {
                    'role': 'user',
                    'content': content,
                },
            ],
            'text': {
                'format': {
                    'type': 'json_schema',
                    'name': 'vendor_bill_payload',
                    'schema': schema,
                    'strict': False,
                },
            },
        }
        response = self._request_json(
            method='post',
            url=f"{settings['base_url'].rstrip('/')}/responses",
            headers={
                'Authorization': f"Bearer {settings['api_key']}",
                'Content-Type': 'application/json',
            },
            body=body,
            timeout=settings['timeout'],
        )
        return self._extract_openai_responses_text(response)

    def _call_openai_chat(self, settings, attachment, system_prompt, user_prompt):
        user_content = [{'type': 'text', 'text': user_prompt}]
        if attachment is not None:
            user_content.append({
                'type': 'image_url',
                'image_url': {
                    'url': f"data:{attachment.mimetype};base64,{base64.b64encode(attachment.raw).decode()}"
                },
            })
        body = {
            'model': settings['model'],
            'temperature': 0,
            'response_format': {'type': 'json_object'},
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_content},
            ],
        }
        response = self._request_json(
            method='post',
            url=f"{settings['base_url'].rstrip('/')}/chat/completions",
            headers={
                'Authorization': f"Bearer {settings['api_key']}",
                'Content-Type': 'application/json',
            },
            body=body,
            timeout=settings['timeout'],
        )
        try:
            choice = response['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError) as error:
            raise UserError(_('The AI provider returned no usable completion payload.')) from error

        if isinstance(choice, list):
            choice = ''.join(part.get('text', '') for part in choice if isinstance(part, dict))
        return choice

    def _call_google(self, settings, attachment, system_prompt, user_prompt, schema):
        body = {
            'systemInstruction': {
                'parts': [{'text': system_prompt}],
            },
            'contents': [{
                'role': 'user',
                'parts': [
                    {'text': user_prompt},
                    {
                        'inline_data': {
                            'mime_type': attachment.mimetype,
                            'data': base64.b64encode(attachment.raw).decode(),
                        },
                    },
                ],
            }],
            'generationConfig': {
                'temperature': 0,
                'responseMimeType': 'application/json',
                'responseJsonSchema': schema,
            },
        }
        response = self._request_json(
            method='post',
            url=f"https://generativelanguage.googleapis.com/v1beta/models/{settings['model']}:generateContent",
            headers={'x-goog-api-key': settings['api_key']},
            body=body,
            timeout=settings['timeout'],
        )
        return self._extract_google_text(response)

    def _build_openai_attachment_part(self, attachment):
        file_data = base64.b64encode(attachment.raw).decode()
        file_uri = f'data:{attachment.mimetype};base64,{file_data}'
        if (attachment.mimetype or '').startswith('image/'):
            return {
                'type': 'input_image',
                'image_url': file_uri,
                'detail': 'high',
            }
        return {
            'type': 'input_file',
            'filename': attachment.name or 'vendor_bill.pdf',
            'file_data': file_uri,
        }

    def _extract_openai_responses_text(self, response):
        if response.get('output_text'):
            return response['output_text']
        for item in response.get('output', []):
            if item.get('type') == 'message':
                for content in item.get('content', []):
                    if content.get('text'):
                        return content['text']
            if item.get('text'):
                return item['text']
        raise UserError(_('The AI provider returned no structured output.'))

    def _extract_google_text(self, response):
        for candidate in response.get('candidates', []):
            for part in candidate.get('content', {}).get('parts', []):
                if part.get('text'):
                    return part['text']
        raise UserError(_('Google Gemini returned no structured output.'))

    def _request_json(self, method, url, headers, body, timeout):
        try:
            response = requests.request(method=method, url=url, headers=headers, json=body, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException as error:
            raise UserError(self._format_http_error(error)) from error

        try:
            return response.json()
        except ValueError as error:
            raise UserError(_('The AI provider returned invalid JSON.')) from error

    def _format_http_error(self, error):
        response = getattr(error, 'response', None)
        if response is None:
            return str(error)
        try:
            payload = response.json()
        except ValueError:
            return response.text or str(error)

        if isinstance(payload, list) and payload:
            payload = payload[0]
        if isinstance(payload, dict):
            if isinstance(payload.get('error'), dict) and payload['error'].get('message'):
                return payload['error']['message']
            if payload.get('message'):
                return payload['message']
        return json.dumps(payload)

    def _coerce_payload(self, payload):
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except json.JSONDecodeError as error:
                _logger.warning('Vendor bill AI returned a non-JSON payload: %s', payload)
                raise UserError(_('The AI provider returned a payload that is not valid JSON.')) from error
        raise UserError(_('The AI provider returned an unsupported payload type.'))

    def _normalize_payload(self, data):
        vendor = data.get('vendor') if isinstance(data.get('vendor'), dict) else {}
        totals = data.get('totals') if isinstance(data.get('totals'), dict) else {}
        warnings = [self._clean_text(warning) for warning in data.get('warnings', []) if self._clean_text(warning)]
        normalized = {
            'document_type': (data.get('document_type') or 'vendor_bill').strip().lower(),
            'vendor': {
                'name': self._clean_text(vendor.get('name')),
                'vat': self._clean_text(vendor.get('vat')),
                'email': self._clean_text(vendor.get('email')),
                'phone': self._clean_text(vendor.get('phone')),
                'iban': self._clean_text(vendor.get('iban')),
            },
            'invoice_number': self._clean_text(data.get('invoice_number')),
            'invoice_date': self._parse_date(data.get('invoice_date')),
            'due_date': self._parse_date(data.get('due_date')),
            'currency': self._clean_text(data.get('currency')),
            'payment_reference': self._clean_text(data.get('payment_reference')),
            'purchase_order_references': [
                ref for ref in (self._clean_text(value) for value in data.get('purchase_order_references', [])) if ref
            ],
            'totals': {
                'untaxed': self._parse_float(totals.get('untaxed')),
                'tax': self._parse_float(totals.get('tax')),
                'total': self._parse_float(totals.get('total')),
            },
            'confidence': self._clamp_confidence(data.get('confidence')),
            'warnings': warnings,
        }
        normalized['lines'] = self._normalize_lines(data.get('lines') or [], normalized)
        return normalized

    def _normalize_lines(self, lines, normalized_payload):
        normalized_lines = []
        for line in lines:
            if not isinstance(line, dict):
                continue
            description = self._clean_text(line.get('description')) or self._clean_text(line.get('product_code'))
            quantity = self._parse_float(line.get('quantity')) or 1.0
            quantity = abs(quantity) if quantity else 1.0
            subtotal = self._parse_float(line.get('subtotal'))
            unit_price = self._parse_float(line.get('unit_price'))
            total = self._parse_float(line.get('total'))
            if unit_price is None and subtotal is not None:
                unit_price = subtotal / quantity if quantity else subtotal
            if subtotal is None and unit_price is not None:
                subtotal = unit_price * quantity
            taxes = []
            for tax in line.get('taxes', []):
                if not isinstance(tax, dict):
                    continue
                rate = self._parse_float(tax.get('rate'))
                if rate is None:
                    continue
                taxes.append({
                    'name': self._clean_text(tax.get('name')),
                    'rate': rate,
                    'price_included': bool(tax.get('price_included')),
                })
            if not description and subtotal is None and total is None:
                continue
            normalized_lines.append({
                'description': description or _('Imported Vendor Bill Line'),
                'product_code': self._clean_text(line.get('product_code')),
                'quantity': quantity,
                'unit_price': unit_price,
                'subtotal': subtotal,
                'total': total,
                'taxes': taxes,
            })

        if normalized_lines:
            return normalized_lines

        untaxed_amount = normalized_payload['totals']['untaxed']
        total_amount = normalized_payload['totals']['total']
        tax_amount = normalized_payload['totals']['tax']
        base_amount = untaxed_amount if untaxed_amount is not None else total_amount
        if base_amount is None:
            raise UserError(_('The AI parser could not extract any usable invoice lines or totals.'))

        summary_line = {
            'description': normalized_payload['invoice_number'] or normalized_payload['vendor']['name'] or _('Imported Vendor Bill'),
            'product_code': False,
            'quantity': 1.0,
            'unit_price': base_amount,
            'subtotal': base_amount,
            'total': total_amount if total_amount is not None else base_amount,
            'taxes': [],
        }
        if tax_amount and untaxed_amount:
            summary_line['taxes'] = [{
                'name': _('Derived tax'),
                'rate': round((tax_amount / untaxed_amount) * 100, 6),
                'price_included': False,
            }]
        normalized_payload['warnings'].append(_('The AI parser returned no detailed lines, so a summary line was generated.'))
        return [summary_line]

    def _extract_pdf_text(self, raw_bytes):
        if not raw_bytes:
            return ''
        try:
            reader = PdfReader(io.BytesIO(raw_bytes))
        except Exception:
            return ''

        texts = []
        for page in reader.pages[:10]:
            try:
                texts.append(page.extract_text() or '')
            except Exception:
                continue
        text = '\n'.join(filter(None, texts)).strip()
        return text[:50000]

    def _parse_float(self, value):
        if value in (None, False, ''):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = re.sub(r'[^0-9,.-]', '', value.strip())
            if not cleaned:
                return None
            if ',' in cleaned and '.' in cleaned:
                if cleaned.rfind(',') > cleaned.rfind('.'):
                    cleaned = cleaned.replace('.', '').replace(',', '.')
                else:
                    cleaned = cleaned.replace(',', '')
            elif cleaned.count(',') == 1 and cleaned.count('.') == 0:
                cleaned = cleaned.replace(',', '.')
            else:
                cleaned = cleaned.replace(',', '')
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None

    def _parse_date(self, value):
        if not value:
            return False
        if hasattr(value, 'isoformat'):
            try:
                return value.isoformat()
            except Exception:
                return False
        text = str(value).strip()
        if not text:
            return False
        for dayfirst in (False, True):
            try:
                from dateutil import parser as date_parser
                return date_parser.parse(text, fuzzy=False, dayfirst=dayfirst).date().isoformat()
            except Exception:
                continue
        return False

    def _clean_text(self, value):
        if value in (None, False):
            return False
        text = str(value).strip()
        return text or False

    def _clamp_confidence(self, value):
        number = self._parse_float(value)
        if number is None:
            return False
        return max(0.0, min(1.0, number))