# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'N-Genius Payment Provider',
    'version': '19.0.1.1.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'summary': "Accept online payments with N-Genius by Network International.",
    'description': """
N-Genius Payment Provider for Odoo
==================================

Accept online payments in Odoo with N-Genius Online by Network International.

This module adds N-Genius as a payment option in Odoo and gives merchants a
simple way to offer a secure hosted payment flow to customers.

Features:
- Secure hosted checkout experience
- Sandbox and production environments
- Automatic payment status updates in Odoo
- Full refund support from Odoo

Requires an active N-Genius merchant account from Network International and
valid credentials.
    """,
    'depends': ['payment', 'account_payment'],
    'data': [
        'views/payment_provider_views.xml',
        'views/payment_ngenius_templates.xml',
        'data/account_payment_method_data.xml',
        'data/payment_provider_data.xml',
    ],
    'author': 'Ashraf',
    'website': 'https://www.ashrf.in',
    'maintainer': 'Ashraf',
    'support': 'connect@ashrf.in',
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
    'images': [
        'static/description/thumb.png',
        'static/description/main_screenshot.png',
        'static/description/config_screenshot.png',
        'static/description/checkout_screenshot.png',
    ],
}
