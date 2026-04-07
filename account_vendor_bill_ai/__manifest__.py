# -*- coding: utf-8 -*-

{
    'name': 'Vendor Bill AI Parser',
    'version': '19.0.1.1.1',
    'category': 'Accounting/Accounting',
    'summary': 'Parse vendor bill PDFs and images with external AI providers',
    'description': """
Vendor Bill AI Parser
=====================

Parse supplier invoices from PDF and image attachments with a configured external
AI provider, then fill draft Odoo vendor bills with the extracted accounting data.

Key behavior:
- manual or automatic parsing modes
- OpenAI, OpenAI-compatible, and Google Gemini provider support
- optional vendor auto-creation and partner bank capture
- confidence scoring and warning messages for review

Important:
- this module sends attached vendor bill documents and extracted accounting data
  to the configured external AI provider
- users must opt in from Accounting settings before parsing is enabled
- an active external AI account and API key are required
""",
    'depends': ['account'],
    'external_dependencies': {
        'python': ['requests', 'PyPDF2', 'python-dateutil'],
    },
    'data': [
        'views/account_move_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'images': ['static/description/banner.png'],
    'installable': True,
    'author': 'Ashraf Ali',
    'maintainer': 'Ashraf Ali',
    'website': 'https://ashrf.in',
    'support': 'contact@ashrf.in',
    'license': 'LGPL-3',
}