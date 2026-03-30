# -*- coding: utf-8 -*-

{
    'name': 'Point of Purchase',
    'version': '19.0.1.1.0',
    'category': 'Inventory/Point of Purchase',
    'summary': 'Touch-friendly point of purchase ordering for suppliers.',
    'author': 'Ashraf Ali',
    'website': 'https://www.ashrf.in',
    'depends': ['purchase_stock', 'web'],
    'data': [
        'security/ir.model.access.csv',
        'security/ir_rules.xml',
        'data/purchase_pop_data.xml',
        'views/res_config_settings_views.xml',
        'views/purchase_pop_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'purchase_pop/static/src/js/purchase_pop_action.js',
            'purchase_pop/static/src/xml/purchase_pop_action.xml',
            'purchase_pop/static/src/scss/purchase_pop.scss',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}