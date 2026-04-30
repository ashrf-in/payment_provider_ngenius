# Part of Odoo. See LICENSE file for full copyright and licensing details.

import ipaddress
import re
from urllib.parse import urlparse

from werkzeug.urls import url_encode

from odoo import _, models
from odoo.exceptions import ValidationError
from odoo.tools.urls import urljoin as url_join

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_provider_ngenius import const
from odoo.addons.payment_provider_ngenius import utils as ngenius_utils
from odoo.addons.payment_provider_ngenius.controllers.main import NGeniusController

_logger = get_payment_logger(__name__, const.SENSITIVE_KEYS)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _get_specific_rendering_values(self, processing_values):
        """Override of payment to return N-Genius-specific rendering values.

        Note: self.ensure_one() from `_get_processing_values`

        :param dict processing_values: The generic processing values of the transaction
        :return: The dict of provider-specific rendering values
        :rtype: dict
        """
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != 'ngenius':
            return res

        # Create N-Genius order
        order_data = self._ngenius_create_order()
        
        # Parse the payment URL to extract base and params for form redirect
        from werkzeug.urls import url_parse
        parsed = url_parse(order_data['payment_url'])
        params = parsed.decode_query()
        base_url = parsed.replace(query='').to_url()
        
        return {
            'api_url': base_url,
            'api_params': params,
        }

    def _ngenius_create_order(self):
        """Create an N-Genius order for the transaction.

        :return: The order data from N-Genius
        :rtype: dict
        :raise ValidationError: If order creation fails
        """
        self.ensure_one()

        access_token = self.provider_id._ngenius_get_access_token()
        outlet_ref = ngenius_utils.get_outlet_ref(self.provider_id.sudo())
        endpoint = const.ORDER_ENDPOINT.format(outlet_ref=outlet_ref)

        # Prepare order payload
        billing_address = ngenius_utils.include_billing_address(self)
        amount_minor = payment_utils.to_minor_currency_units(
            self.amount,
            self.currency_id,
            arbitrary_decimal_number=const.CURRENCY_DECIMALS.get(self.currency_id.name, 2),
        )

        # Sanitize reference: N-Genius only accepts [a-zA-Z0-9\-]{1,37}
        sanitized_reference = re.sub(r'[^a-zA-Z0-9\-]', '-', self.reference)[:37]

        # Build redirect URL that includes the Odoo transaction reference
        base_url = self.provider_id.get_base_url()
        parsed_base_url = urlparse(base_url)
        hostname = parsed_base_url.hostname or ''
        try:
            is_loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            is_loopback = hostname == 'localhost'

        if hostname == 'localhost' or is_loopback:
            raise ValidationError(_(
                "N-Genius: The Odoo base URL '%(base_url)s' cannot be used as a payment return "
                "URL. Configure a non-local hostname in Settings > Technical > System "
                "Parameters (`web.base.url`) or use a public tunnel/domain.",
                base_url=base_url,
            ))

        redirect_url = f"{base_url}{NGeniusController._return_url}?{url_encode({'reference': self.reference})}"

        payload = {
            'action': 'PURCHASE',
            'amount': {
                'currencyCode': self.currency_id.name,
                'value': amount_minor,
            },
            'merchantAttributes': {
                'redirectUrl': redirect_url,
                'skipConfirmationPage': True,
            },
            'merchantOrderReference': sanitized_reference,
        }

        if self.partner_email:
            payload['emailAddress'] = self.partner_email.strip()
        if billing_address:
            payload['billingAddress'] = billing_address


        response_data = self.provider_id._ngenius_make_request(
            'POST', endpoint, data=payload, access_token=access_token
        )

        # Store the N-Genius order reference on the transaction
        order_ref = response_data.get('reference', '')
        if order_ref:
            self.provider_reference = order_ref

        # Extract payment URL from response
        links = response_data.get('_links', {})
        payment_link = links.get('payment', {}).get('href', '')
        
        if not payment_link:
            raise ValidationError(_("N-Genius: No payment link received from API"))


        
        return {
            'reference': order_ref,
            'payment_url': payment_link,
        }

    @staticmethod
    def _ngenius_get_order_payments(order_data):
        """Return the payments embedded in an order payload."""
        payments = order_data.get('_embedded', {}).get('payment', [])
        return payments if isinstance(payments, list) else []

    @staticmethod
    def _ngenius_get_payment_from_order_data(order_data):
        """Return the first payment object from an order or a payment-shaped payload."""
        payments = PaymentTransaction._ngenius_get_order_payments(order_data)
        if payments:
            return payments[0]

        if order_data.get('orderReference') and order_data.get('amount'):
            return order_data

        return {}

    @staticmethod
    def _ngenius_get_refund_link_from_payment_data(payment_data):
        """Return the refund link from a payment payload when available."""
        refund_link = payment_data.get('_links', {}).get(const.REFUND_REL, {}).get('href')
        if refund_link:
            return refund_link

        payment_self_href = payment_data.get('_links', {}).get('self', {}).get('href', '')
        purchase_id = payment_data.get('purchaseData', {}).get('id')
        if payment_self_href and purchase_id:
            return f"{payment_self_href}/purchases/{purchase_id}/refund"

        capture_id = payment_data.get('captureData', {}).get('id')
        if payment_self_href and capture_id:
            return f"{payment_self_href}/captures/{capture_id}/refund"

        return ''

    @staticmethod
    def _ngenius_get_void_link_from_payment_data(payment_data):
        """Return the void link from a payment payload when available."""
        return payment_data.get('_links', {}).get('cnp:cancel', {}).get('href', '')

    @staticmethod
    def _ngenius_get_refund_link_from_order_data(order_data):
        """Return the documented refund link from the order's payment object."""
        for payment in PaymentTransaction._ngenius_get_order_payments(order_data):
            refund_link = PaymentTransaction._ngenius_get_refund_link_from_payment_data(payment)
            if refund_link:
                return refund_link

        return ''

    @staticmethod
    def _ngenius_get_latest_refund(payment):
        """Return the latest embedded refund entry from a payment payload."""
        refunds = payment.get('_embedded', {}).get(const.REFUND_REL, [])
        return refunds[-1] if refunds else {}

    @staticmethod
    def _ngenius_extract_reference_from_href(href):
        """Extract the trailing resource identifier from an API href."""
        return href.rstrip('/').rsplit('/', 1)[-1] if href else ''

    def _send_payment_request(self):
        """Override of `payment` to send a payment request to N-Genius."""
        if self.provider_code != 'ngenius':
            return super()._send_payment_request()

        # For N-Genius, the order is created in _get_specific_processing_values
        # and the user is redirected to N-Genius payment page
        pass

    def _send_refund_request(self):
        """Override of `payment` to send a refund request to N-Genius."""
        if self.provider_code != 'ngenius':
            return super()._send_refund_request()

        access_token = self.provider_id._ngenius_get_access_token()
        outlet_ref = ngenius_utils.get_outlet_ref(self.provider_id.sudo())

        # Retrieve the order to discover the provider-managed refund URI.
        order_ref = self.source_transaction_id.provider_reference
        if not order_ref:
            raise ValidationError(_("N-Genius: Missing order reference for refund."))

        # Fetch order details to get payment reference
        order_endpoint = const.ORDER_DETAIL_ENDPOINT.format(
            outlet_ref=outlet_ref, order_ref=order_ref
        )
        order_data = self.provider_id._ngenius_make_request(
            'GET', order_endpoint, access_token=access_token
        )

        operation_method = ''
        operation_endpoint = ''
        for payment in self._ngenius_get_order_payments(order_data):
            payment_data = payment
            payment_self_href = payment.get('_links', {}).get('self', {}).get('href')
            if payment_self_href:
                payment_data = self.provider_id._ngenius_make_request(
                    'GET', payment_self_href, access_token=access_token
                )

            refund_endpoint = self._ngenius_get_refund_link_from_payment_data(payment_data)
            if refund_endpoint and payment_data.get('purchaseData', {}).get('displayRefund', True):
                operation_method = 'POST'
                operation_endpoint = refund_endpoint
                break

            void_endpoint = self._ngenius_get_void_link_from_payment_data(payment_data)
            if void_endpoint and payment_data.get('purchaseData', {}).get('displayVoid'):
                operation_method = 'PUT'
                operation_endpoint = void_endpoint
                break

        if not operation_endpoint:
            raise ValidationError(_(
                "N-Genius: This transaction is not refundable yet. The payment must expose a "
                "refund or reversal action before a refund can be requested."
            ))

        amount_minor = payment_utils.to_minor_currency_units(
            -self.amount,  # Refund amount is negative
            self.currency_id,
            arbitrary_decimal_number=const.CURRENCY_DECIMALS.get(self.currency_id.name, 2),
        )

        request_kwargs = {'access_token': access_token}
        if operation_method == 'POST':
            request_kwargs['data'] = {
                'amount': {'currencyCode': self.currency_id.name, 'value': amount_minor}
            }

        refund_data = self.provider_id._ngenius_make_request(
            operation_method,
            operation_endpoint,
            **request_kwargs,
        )

        # Process refund response
        payment_data = {
            'reference': self.reference,
            'order_data': refund_data,
        }
        self._process('ngenius', payment_data)

    def _search_by_reference(self, provider_code, payment_data):
        """Override of payment to find the transaction based on N-Genius data.

        :param str provider_code: The code of the provider that handled the transaction
        :param dict payment_data: The payment data sent by the provider
        :return: The transaction if found
        :rtype: payment.transaction
        """
        if provider_code != 'ngenius':
            return super()._search_by_reference(provider_code, payment_data)

        reference = payment_data.get('reference')
        if not reference:
            _logger.warning("N-Genius: Received data with missing merchant reference")
            return self

        tx = self.search([('reference', '=', reference), ('provider_code', '=', 'ngenius')])
        if not tx:
            _logger.warning("N-Genius: No transaction found matching reference %s", reference)

        return tx

    def _extract_amount_data(self, payment_data):
        """Override of payment to extract the amount and currency from the payment data."""
        if self.provider_code != 'ngenius':
            return super()._extract_amount_data(payment_data)

        order_data = payment_data.get('order_data', {})
        payment = self._ngenius_get_payment_from_order_data(order_data)

        if not payment:
            if self.operation == 'refund':
                return None
            return {'amount': 0, 'currency_code': ''}

        if self.operation == 'refund':
            amount_data = self._ngenius_get_latest_refund(payment).get('amount', {})
            if not amount_data:
                return None
        else:
            amount_data = payment.get('amount', {})

        amount_minor = amount_data.get('value', 0)

        amount = payment_utils.to_major_currency_units(
            amount_minor,
            self.currency_id,
            arbitrary_decimal_number=const.CURRENCY_DECIMALS.get(self.currency_id.name, 2),
        )

        return {
            'amount': amount,
            'currency_code': amount_data.get('currencyCode', '').upper(),
            'precision_digits': const.CURRENCY_DECIMALS.get(self.currency_id.name, 2),
        }

    def _apply_updates(self, payment_data):
        """Override of `payment` to update the transaction based on the payment data."""
        if self.provider_code != 'ngenius':
            return super()._apply_updates(payment_data)

        order_data = payment_data.get('order_data', {})
        payment = self._ngenius_get_payment_from_order_data(order_data)

        if self.operation == 'refund':
            if not payment:
                self._set_error(_("N-Genius: Missing payment data in refund response."))
                return

            refund = self._ngenius_get_latest_refund(payment)
            payment_state = payment.get('state', '')
            refund_reference = self._ngenius_extract_reference_from_href(
                refund.get('_links', {}).get('self', {}).get('href', '')
            )
            if not refund_reference and payment_state in ('REVERSED', 'CANCELLED'):
                refund_reference = self._ngenius_extract_reference_from_href(
                    payment.get('_links', {}).get('self', {}).get('href', '')
                ) or payment.get('reference', '')
            if refund_reference:
                self.provider_reference = refund_reference

            refund_state = refund.get('state', '')
            if (
                refund_state in const.REFUND_DONE_STATES
                or payment_state in const.REFUND_DONE_STATES
                or payment_state in ('REVERSED', 'CANCELLED')
            ):
                self._set_done()
                self.env.ref('payment.cron_post_process_payment_tx')._trigger()
            elif refund_state in const.REFUND_PENDING_STATES:
                self._set_pending()
            elif refund_state in const.REFUND_ERROR_STATES:
                self._set_error(_("The refund did not go through. Please try again."))
            else:
                _logger.warning(
                    "N-Genius: Received unknown refund state refund=%s payment=%s",
                    refund_state,
                    payment_state,
                )
                self._set_error(_("The refund did not go through. Please try again."))
            return

        self.provider_reference = order_data.get('reference', '')

        # Extract payment state
        payments = self._ngenius_get_order_payments(order_data)

        # Get order-level state as fallback
        order_state = order_data.get('state', '')
        

        
        if payments:
            payment = payments[0]
            state = payment.get('state', '')
            

            
            # Check for 3DS authentication result
            three_ds = payment.get('3ds2') or payment.get('3ds', {})
            if three_ds:
                # 3DS was attempted - check the ECI (Electronic Commerce Indicator)
                # ECI is the TRUE indicator of authentication level:
                # - ECI 05 (Visa) / 02 (Mastercard) = Fully Authenticated (issuer liability)
                # - ECI 06 (Visa) / 01 (Mastercard) = Attempted but NOT authenticated (merchant liability)
                # - ECI 07 (Visa) / 00 (Mastercard) = Not enrolled / not authenticated

                three_ds_eci = three_ds.get('eci', '')
                three_ds_summary = three_ds.get('summaryText') or three_ds.get('transStatus', '')
                

                
                # Only ECI 05 (Visa) or 02 (Mastercard) = fully authenticated
                # All other ECI values should fail per user requirement
                authenticated_eci_values = ('05', '02')
                
                if three_ds_eci and three_ds_eci not in authenticated_eci_values:
                    _logger.warning(
                        "N-Genius: 3DS ECI %s indicates NOT fully authenticated. Summary: %s", 
                        three_ds_eci, three_ds_summary
                    )
                    self._set_error(_(
                        "3DS authentication required but not completed (ECI: %s). %s", 
                        three_ds_eci, three_ds_summary or "Please try again with 3DS authentication."
                    ))
                    return
            
            # Check authResponse for non-00 result codes
            auth_response = payment.get('authResponse', {})
            result_code = auth_response.get('resultCode', '')
            if result_code and result_code != '00':
                result_message = auth_response.get('resultMessage', 'Authentication failed')
                _logger.warning("N-Genius: Auth failed with code %s: %s", result_code, result_message)
                self._set_error(_("Payment authentication failed: %s", result_message))
                return
            
            # Map N-Genius state to Odoo state using STATUS_MAPPING
            # Only explicit success states should mark as done
            if state in const.STATUS_MAPPING['done']:
                self._set_done()
            elif state in const.STATUS_MAPPING['authorized']:
                self._set_authorized()
            elif state in const.STATUS_MAPPING['draft']:
                self._set_pending()
            elif state in const.STATUS_MAPPING['pending']:
                self._set_pending()
            elif state in const.STATUS_MAPPING['cancel']:
                self._set_canceled()
            elif state in const.STATUS_MAPPING['error']:
                error_msg = auth_response.get('resultMessage', 'Payment failed or was declined')
                self._set_error(_("Payment failed: %s", error_msg))
            else:
                # Unknown state - treat as error for safety
                _logger.warning("N-Genius: Received unknown payment state: %s", state)
                self._set_error(_("Payment was not completed. State: %s", state))
        else:
            # No payments - check order state (3DS might have failed before payment creation)
            _logger.warning("N-Genius: No payments in order, checking order state: %s", order_state)
            
            # Only explicit success states should pass
            if order_state in const.ORDER_STATUS_MAPPING.get('done', ()):
                self._set_done()
            elif order_state in const.ORDER_STATUS_MAPPING.get('pending', ()):
                self._set_pending()
            elif order_state in const.ORDER_STATUS_MAPPING.get('cancel', ()):
                self._set_canceled()
            else:
                # No payments and not explicitly successful = failed
                _logger.warning("N-Genius: Order has no payments, state: %s - marking as error", order_state)
                self._set_error(_("Payment was not completed. Please try again."))



