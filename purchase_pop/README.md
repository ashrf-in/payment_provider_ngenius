# Point of Purchase (POP)

Touch-friendly point of purchase ordering system for Odoo 19, designed to streamline supplier ordering with a modern, responsive interface.

## Summary

The Point of Purchase module provides a dedicated terminal-style interface for inventory and purchase managers to quickly create and manage supplier orders. Integrated directly with Odoo's Purchase and Stock modules, it offers a touch-optimized experience suitable for warehouse tablets and desktop terminals alike.

## Key Features

- **Touch-Friendly Interface**: Optimized OWL-based terminal for fast product selection and ordering.
- **Supplier Integration**: Seamlessly pulls vendor-specific pricing and minimum quantities from Odoo Supplier Info.
- **Real-Time Inventory**: View current stock levels and inventory availability directly within the POP terminal.
- **Purchase Automation**: Automatically generates and confirms Purchase Orders (POs) and incoming receipts.
- **Order History**: Track past POP orders and their corresponding Odoo Purchase Orders.
- **Product Filtering**: Advanced filtering by category, search term, and vendor.
- **Responsive Design**: Works perfectly on desktops, tablets, and mobile devices.

## Installation

1. Copy the `purchase_pop` folder into your Odoo addons directory.
2. Restart your Odoo server.
3. Activate the Developer Mode in Odoo.
4. Go to **Apps** > **Update Apps List**.
5. Search for "Point of Purchase" and click **Activate**.

## Configuration

### Allowed Categories
To restrict the products visible in the POP terminal:
1. Go to **Point of Purchase** > **Configuration** > **Settings**.
2. Under the **Allowed POP Categories** field, select the product categories you want to make available in the terminal.
3. If left empty, all purchaseable products will be visible.

## Usage

### Accessing the Terminal
1. Navigate to the **Point of Purchase** app from the Odoo main dashboard.
2. Click on the **Terminal** menu item to launch the touch interface.

### Creating an Order
1. Select a **Vendor** from the top dropdown.
2. (Optional) Select a **Warehouse** for delivery.
3. Browse products using the category sidebar or the search bar.
4. Click on products to add them to your basket.
5. Adjust quantities using the integrated numpad.
6. Click **Confirm Order** to generate the Purchase Order in Odoo.

## Credits

### Author
- **Ashraf Ali** - [www.ashrf.in](https://www.ashrf.in)
- Location: Dubai, UAE

## License

This module is licensed under the **LGPL-3** license.
