# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request
from odoo.tools import mute_logger

from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_provider_ngenius import const

_logger = get_payment_logger(__name__, const.SENSITIVE_KEYS)


class NGeniusController(http.Controller):
    _return_url = '/payment/ngenius/return'
    _webhook_url = '/payment/ngenius/webhook'

    @staticmethod
    def _get_ngenius_provider_from_event(event):
        """Return the provider matching the webhook's outlet reference."""
        outlet_ref = event.get('outletId') or event.get('order', {}).get('outletId')
        if not outlet_ref:
            return request.env['payment.provider']

        return request.env['payment.provider'].sudo().search([
            ('code', '=', 'ngenius'),
            ('ngenius_outlet_ref', '=', outlet_ref),
        ], limit=1)

    @staticmethod
    def _is_webhook_authorized(provider_sudo):
        """Validate the optional custom webhook header configured on the provider."""
        header_name = provider_sudo.ngenius_webhook_header_name
        header_value = provider_sudo.ngenius_webhook_header_value
        if not header_name and not header_value:
            return True

        return request.httprequest.headers.get(header_name) == header_value

    @staticmethod
    def _get_latest_refund_reference(order_data):
        """Extract the latest refund identifier from the webhook order payload."""
        payments = order_data.get('_embedded', {}).get('payment', [])
        if not payments:
            return ''

        refunds = payments[0].get('_embedded', {}).get(const.REFUND_REL, [])
        if not refunds:
            return ''

        refund_href = refunds[-1].get('_links', {}).get('self', {}).get('href', '')
        return refund_href.rstrip('/').rsplit('/', 1)[-1] if refund_href else ''

    @http.route(_return_url, type='http', methods=['GET'], auth='public', csrf=False)
    def ngenius_return(self, **data):
        """Process the payment data sent by N-Genius after redirection from payment.

        :param dict data: The payment data, including the reference and order ref.
        """
        # Get transaction reference from URL (we included it in the redirect URL)
        reference = data.get('reference')
        order_ref = data.get('ref')  # N-Genius order reference
        
        # Find transaction by reference or by provider_reference (order ref)
        tx_sudo = None
        if reference:
            tx_sudo = request.env['payment.transaction'].sudo().search([
                ('reference', '=', reference),
                ('provider_code', '=', 'ngenius'),
            ], limit=1)
        
        if not tx_sudo and order_ref:
            tx_sudo = request.env['payment.transaction'].sudo().search([
                ('provider_reference', '=', order_ref),
                ('provider_code', '=', 'ngenius'),
            ], limit=1)
        
        if not tx_sudo:
            _logger.warning("N-Genius: No transaction found for reference=%s, order_ref=%s", reference, order_ref)
            with mute_logger('werkzeug'):
                return request.redirect('/payment/status')
        
        # Fetch order details from N-Genius API
        try:
            order_ref_to_fetch = order_ref or tx_sudo.provider_reference
            if order_ref_to_fetch:
                access_token = tx_sudo.provider_id._ngenius_get_access_token()
                outlet_ref = tx_sudo.provider_id.ngenius_outlet_ref
                endpoint = const.ORDER_DETAIL_ENDPOINT.format(
                    outlet_ref=outlet_ref, order_ref=order_ref_to_fetch
                )
                order_data = tx_sudo.provider_id._ngenius_make_request(
                    'GET', endpoint, access_token=access_token
                )
                
                # Process the payment data
                payment_data = {
                    'reference': tx_sudo.reference,
                    'order_data': order_data,
                }
                tx_sudo._process('ngenius', payment_data)
            else:
                _logger.warning("N-Genius: No order reference to fetch - cannot verify payment")
                tx_sudo._set_error("Payment could not be verified - no order reference")
        except ValidationError as e:
            _logger.exception("Failed to process the return from N-Genius")
            tx_sudo._set_error(str(e))
        except Exception as e:
            _logger.exception("Unexpected error processing N-Genius return")
            tx_sudo._set_error("Payment processing failed: %s" % str(e))

        # Redirect the user to the status page
        with mute_logger('werkzeug'):
            return request.redirect('/payment/status')

    @http.route(_webhook_url, type='http', methods=['POST'], auth='public', csrf=False)
    def ngenius_webhook(self):
        """Process the payment data sent by N-Genius to the webhook.

        :return: An empty string to acknowledge the notification.
        :rtype: str
        """
        event = request.get_json_data() or {}

        try:
            event_name = event.get('eventName', '')
            if event_name and event_name not in const.HANDLED_WEBHOOK_EVENTS:
                _logger.info(
                    "N-Genius: Received unlisted webhook event %s; processing order status anyway",
                    event_name,
                )

            provider_sudo = self._get_ngenius_provider_from_event(event)
            if not provider_sudo:
                _logger.warning("N-Genius: No provider found for webhook event %s", event_name)
                return request.make_json_response('')

            if not self._is_webhook_authorized(provider_sudo):
                _logger.warning("N-Genius: Rejected webhook with invalid custom header")
                return request.make_json_response({'error': 'forbidden'}, status=403)

            order_data = event.get('order') or {}
            order_ref = order_data.get('reference')
            if not order_ref:
                _logger.warning("N-Genius: Webhook event %s has no order reference", event_name)
                return request.make_json_response('')

            tx_domain = [('provider_code', '=', 'ngenius')]
            if event_name in const.REFUND_WEBHOOK_EVENTS:
                refund_ref = self._get_latest_refund_reference(order_data)
                if not refund_ref:
                    _logger.warning("N-Genius: Refund webhook has no refund reference for order %s", order_ref)
                    return request.make_json_response('')

                tx_domain.append(('provider_reference', '=', refund_ref))
            else:
                tx_domain.append(('provider_reference', '=', order_ref))

            tx_sudo = request.env['payment.transaction'].sudo().search(tx_domain, limit=1)
            if not tx_sudo:
                _logger.warning(
                    "N-Genius: No transaction found for webhook event=%s order_ref=%s",
                    event_name,
                    order_ref,
                )
                return request.make_json_response('')

            endpoint = const.ORDER_DETAIL_ENDPOINT.format(
                outlet_ref=provider_sudo.ngenius_outlet_ref,
                order_ref=order_ref,
            )
            authoritative_order_data = provider_sudo._ngenius_make_request('GET', endpoint)

            payment_data = {
                'reference': tx_sudo.reference,
                'order_data': authoritative_order_data,
            }
            tx_sudo._process('ngenius', payment_data)
        except ValidationError:
            _logger.exception("Unable to process the webhook; skipping to acknowledge")
        except Exception:
            _logger.exception("Unexpected error while processing the webhook; acknowledging")
        
        return request.make_json_response('')
