# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.addons.payment.const import SENSITIVE_KEYS as PAYMENT_SENSITIVE_KEYS

SENSITIVE_KEYS = {'api_key', 'access_token', 'apiKey', 'Authorization'}
PAYMENT_SENSITIVE_KEYS.update(SENSITIVE_KEYS)  # Add N-Genius-specific keys to the global set.

# N-Genius API Configuration
API_URL_SANDBOX = 'https://api-gateway.sandbox.ngenius-payments.com'
API_URL_LIVE = 'https://api-gateway.ngenius-payments.com'
AUTH_ENDPOINT = '/identity/auth/access-token'
ORDER_ENDPOINT = '/transactions/outlets/{outlet_ref}/orders'
ORDER_DETAIL_ENDPOINT = '/transactions/outlets/{outlet_ref}/orders/{order_ref}'
REFUND_REL = 'cnp:refund'
REFUND_DONE_STATES = ('SUCCESS', 'REFUNDED', 'PARTIALLY_REFUNDED')
REFUND_PENDING_STATES = ('PENDING', 'IN_PROGRESS')
REFUND_ERROR_STATES = ('FAILED', 'ERROR')

# The codes of the payment methods to activate when N-Genius is activated.
DEFAULT_PAYMENT_METHOD_CODES = {
    # Primary payment methods.
    'card',
}

# Mapping of transaction states to N-Genius payment states.
# See N-Genius API documentation for exhaustive state list.
STATUS_MAPPING = {
    'draft': ('STARTED',),
    'pending': ('STARTED', 'AWAITING_3DS_ENROLLMENT', 'AWAIT_3DS', 'PENDING'),
    'authorized': ('AUTHORISED',),
    'done': ('PURCHASED', 'CAPTURED'),
    'cancel': ('CANCELLED', 'ABANDONED'),
    'error': ('FAILED', 'DECLINED', 'REVERSED', '3DS_FAILED', 'AUTHENTICATION_FAILED'),
}

# Order-level states (different from payment states)
ORDER_STATUS_MAPPING = {
    'pending': ('PENDING', 'STARTED', 'AWAIT_3DS'),
    'done': ('PURCHASED', 'CAPTURED'),
    'cancel': ('CANCELLED', 'ABANDONED', 'EXPIRED'),
    'error': ('FAILED',),
}

# Events which are handled by the webhook.
HANDLED_WEBHOOK_EVENTS = [
    'PURCHASED',
    'CAPTURED',
    'REFUNDED',
    'CANCELLED',
    'FAILED',
]
REFUND_WEBHOOK_EVENTS = ('REFUNDED', 'PARTIALLY_REFUNDED')

# Currency code to minor units multiplier (N-Genius uses minor units)
# Most currencies use 100 (e.g., USD cents, EUR cents, AED fils)
# Exceptions are listed below
CURRENCY_DECIMALS = {
    # Zero decimal currencies
    'BIF': 0,
    'CLP': 0,
    'DJF': 0,
    'GNF': 0,
    'JPY': 0,
    'KMF': 0,
    'KRW': 0,
    'MGA': 0,
    'PYG': 0,
    'RWF': 0,
    'UGX': 0,
    'VND': 0,
    'VUV': 0,
    'XAF': 0,
    'XOF': 0,
    'XPF': 0,
    # Three decimal currencies
    'BHD': 3,
    'JOD': 3,
    'KWD': 3,
    'OMR': 3,
    'TND': 3,
}

