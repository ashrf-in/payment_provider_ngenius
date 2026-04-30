# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json
import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.logging import get_payment_logger
from odoo.addons.payment_provider_ngenius import const
from odoo.addons.payment_provider_ngenius import utils as ngenius_utils
from odoo.addons.payment_provider_ngenius.controllers.main import NGeniusController

_logger = get_payment_logger(__name__, const.SENSITIVE_KEYS)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    @staticmethod
    def _ngenius_extract_error_details(response):
        """Return a concise API error payload for logs and validation messages."""
        if response is None:
            return ''

        try:
            payload = response.json()
        except ValueError:
            return (response.text or '').strip()[:500]

        if isinstance(payload, dict):
            for key in ('errors', 'error', 'violations'):
                value = payload.get(key)
                if value:
                    if isinstance(value, list):
                        messages = [
                            item.get('localizedMessage') or item.get('message') or str(item)
                            for item in value
                        ]
                        return '; '.join(filter(None, messages))[:500]
                    if isinstance(value, dict):
                        return (
                            value.get('localizedMessage')
                            or value.get('message')
                            or json.dumps(value, sort_keys=True)
                        )[:500]
                    return str(value)[:500]

            for key in ('message', 'detail', 'error_description'):
                value = payload.get(key)
                if value:
                    return str(value)[:500]

        return json.dumps(payload, sort_keys=True)[:500]

    code = fields.Selection(
        selection_add=[('ngenius', "N-Genius")], ondelete={'ngenius': 'set default'})
    ngenius_api_key = fields.Char(
        string="API Key",
        help="The API key for N-Genius authentication",
        required_if_provider='ngenius',
        copy=False,
        groups='base.group_system',
    )
    ngenius_outlet_ref = fields.Char(
        string="Outlet Reference",
        help="The outlet reference ID from your N-Genius account",
        required_if_provider='ngenius',
        copy=False,
    )
    ngenius_webhook_header_name = fields.Char(
        string="Webhook Header Name",
        help="Optional custom header name configured on the N-Genius webhook.",
        copy=False,
    )
    ngenius_webhook_header_value = fields.Char(
        string="Webhook Header Value",
        help="Optional custom header value configured on the N-Genius webhook.",
        copy=False,
        groups='base.group_system',
    )

    # === COMPUTE METHODS === #

    def _compute_feature_support_fields(self):
        """Override of `payment` to enable additional features."""
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == 'ngenius').update({
            'support_manual_capture': False,
            'support_refund': 'full_only',
            'support_tokenization': False,
        })

    # === CONSTRAINT METHODS === #

    @api.constrains('state', 'ngenius_api_key', 'ngenius_outlet_ref')
    def _check_ngenius_credentials(self):
        """Check that N-Genius credentials are valid when enabling the provider."""
        for provider in self:
            if provider.code == 'ngenius' and provider.state == 'enabled':
                if not provider.ngenius_api_key or not provider.ngenius_outlet_ref:
                    raise ValidationError(_(
                        "You must configure both API Key and Outlet Reference before enabling "
                        "the N-Genius payment provider."
                    ))

    @api.constrains('ngenius_webhook_header_name', 'ngenius_webhook_header_value')
    def _check_ngenius_webhook_header(self):
        """Ensure the optional webhook header configuration is complete."""
        for provider in self.filtered(lambda p: p.code == 'ngenius'):
            if bool(provider.ngenius_webhook_header_name) != bool(provider.ngenius_webhook_header_value):
                raise ValidationError(_(
                    "N-Genius webhook header name and value must either both be set or both be empty."
                ))

    # === CRUD METHODS === #

    def _get_default_payment_method_codes(self):
        """Override of `payment` to return the default payment method codes."""
        self.ensure_one()
        if self.code != 'ngenius':
            return super()._get_default_payment_method_codes()
        return const.DEFAULT_PAYMENT_METHOD_CODES

    # === BUSINESS METHODS - PAYMENT FLOW === #

    def _ngenius_get_api_url(self):
        """Return the appropriate API URL based on the provider state.

        :return: The API base URL
        :rtype: str
        """
        self.ensure_one()
        return const.API_URL_SANDBOX if self.state == 'test' else const.API_URL_LIVE

    def _ngenius_get_access_token(self):
        """Get an access token from N-Genius API.

        :return: The access token
        :rtype: str
        :raise ValidationError: If authentication fails
        """
        self.ensure_one()
        
        api_url = self._ngenius_get_api_url()
        endpoint = f"{api_url}{const.AUTH_ENDPOINT}"
        api_key = ngenius_utils.get_api_key(self.sudo())

        headers = {
            'Authorization': f'Basic {api_key}',
            'Content-Type': 'application/vnd.ni-identity.v1+json',
            'Accept': 'application/vnd.ni-identity.v1+json',
        }

        try:

            response = requests.post(
                endpoint,
                json={'realmName': 'ni'},
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()

            return data.get('access_token')
        except requests.exceptions.HTTPError as error:
            error_details = self._ngenius_extract_error_details(error.response)
            if error_details:
                _logger.exception(
                    "Unable to authenticate with N-Genius: %s. Response: %s",
                    error, error_details,
                )
                raise ValidationError(_(
                    "N-Genius: Unable to authenticate. %(details)s",
                    details=error_details,
                )) from error

            _logger.exception("Unable to authenticate with N-Genius: %s", error)
            raise ValidationError(_(
                "N-Genius: Unable to authenticate. Please check your API credentials."
            )) from error
        except requests.exceptions.RequestException as error:
            _logger.exception("Unable to authenticate with N-Genius: %s", error)
            raise ValidationError(_(
                "N-Genius: Unable to authenticate. Please check your API credentials."
            )) from error

    def _ngenius_make_request(self, method, endpoint, data=None, access_token=None):
        """Make an API request to N-Genius.

        :param str method: The HTTP method (GET, POST, etc.)
        :param str endpoint: The API endpoint
        :param dict data: The request payload
        :param str access_token: Optional access token (will fetch if not provided)
        :return: The response data
        :rtype: dict
        :raise ValidationError: If the request fails
        """
        self.ensure_one()
        
        if not access_token:
            access_token = self._ngenius_get_access_token()

        api_url = self._ngenius_get_api_url()
        url = endpoint if endpoint.startswith(('http://', 'https://')) else f"{api_url}{endpoint}"

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/vnd.ni-payment.v2+json',
            'Accept': 'application/vnd.ni-payment.v2+json',
        }

        try:

            response = requests.request(
                method, url, json=data, headers=headers, timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as error:
            error_details = self._ngenius_extract_error_details(error.response)
            if error_details:
                _logger.exception(
                    "N-Genius API request failed: %s. Response: %s",
                    error, error_details,
                )
                raise ValidationError(_(
                    "N-Genius: API request failed. %(details)s",
                    details=error_details,
                )) from error

            _logger.exception("N-Genius API request failed: %s", error)
            raise ValidationError(_(
                "N-Genius: API request failed. Please check your configuration."
            )) from error
        except requests.exceptions.RequestException as error:
            _logger.exception("N-Genius API request failed: %s", error)
            raise ValidationError(_(
                "N-Genius: API request failed. Please check your configuration."
            )) from error
