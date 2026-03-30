/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";

class PurchasePopAction extends Component {
    static template = "purchase_pop.PurchasePopAction";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this._searchTimer = null;
        this._touchStartX = 0;
        this._historyCache = {};
        this._categoryTree = [];
        this._categoryMap = {};

        this.state = useState({
            loading: true,
            loadingProducts: false,
            submitting: false,

            vendors: [],
            categories: [],
            warehouses: [],
            totalProducts: 0,
            currency: {},

            selectedVendorId: false,
            selectedCategoryId: false,
            selectedWarehouseId: false,
            search: "",

            editableOrders: [],
            selectedOrderId: false,

            products: [],

            orderLines: [],
            note: "",
            selectedLineId: false,
            numpadTempValue: "",
            swipedLineId: false,

            lastConfirmedPO: null,
            showConfirmDialog: false,

            // Mobile & display
            fullscreen: false,
            showMobileSidebar: false,
            showMobileBasket: false,

            // Category tree
            expandedCategoryIds: [],

            // Product history tooltip
            hoveredProductId: false,
            historyData: null,
            historyLoading: false,
        });

        onWillStart(async () => {
            const data = await this.orm.call("purchase.pop.order", "get_pop_bootstrap_data", []);
            this.state.vendors = data.vendors || [];
            this.state.categories = data.categories || [];
            this.state.warehouses = data.warehouses || [];
            this.state.totalProducts = data.total_products || 0;
            this.state.currency = data.currency || {};
            if (this.state.warehouses.length === 1) {
                this.state.selectedWarehouseId = this.state.warehouses[0].id;
            }
            this._buildCategoryTree();
            // Auto-expand root categories
            this.state.expandedCategoryIds = this._categoryTree.map(c => c.id);
            await this.loadProducts();
            this.state.loading = false;
        });

        onMounted(() => {
            this._onKeyDown = this._handleKeyDown.bind(this);
            document.addEventListener('keydown', this._onKeyDown);
        });

        onWillUnmount(() => {
            document.removeEventListener('keydown', this._onKeyDown);
            document.body.classList.remove('o_pop_fullscreen');
        });
    }

    // ── Keyboard Shortcuts ──

    _handleKeyDown(ev) {
        // Only handle when our component is active
        if (!document.querySelector('.o_purchase_pop')) return;

        // F2 → focus search
        if (ev.key === 'F2') {
            ev.preventDefault();
            const input = document.querySelector('.o_purchase_pop input[type="search"]');
            if (input) input.focus();
            return;
        }

        // Escape → close dialogs / deselect / close mobile panels
        if (ev.key === 'Escape') {
            ev.preventDefault();
            if (this.state.showConfirmDialog) {
                this.state.showConfirmDialog = false;
            } else if (this.state.selectedLineId) {
                this.applyNumpadValue();
            } else if (this.state.showMobileSidebar || this.state.showMobileBasket) {
                this.closeMobileOverlays();
            } else if (this.state.hoveredProductId) {
                this.state.hoveredProductId = false;
                this.state.historyData = null;
            }
            return;
        }

        // Don't capture Enter/shortcuts when typing in inputs
        if (ev.target.closest('input, textarea, select')) return;

        // Enter → confirm dialog or open it
        if (ev.key === 'Enter') {
            ev.preventDefault();
            if (this.state.showConfirmDialog && !this.state.submitting) {
                this.confirmOrder();
            } else if (this.state.orderLines.length && !this.state.showConfirmDialog) {
                this.requestConfirm();
            }
            return;
        }
    }

    // ── Category Tree ──

    _buildCategoryTree() {
        const cats = this.state.categories;
        const catMap = {};
        const roots = [];

        for (const cat of cats) {
            catMap[cat.id] = { ...cat, children: [], depth: 0 };
        }
        for (const cat of cats) {
            if (cat.parent_id && catMap[cat.parent_id]) {
                catMap[cat.parent_id].children.push(catMap[cat.id]);
            } else {
                roots.push(catMap[cat.id]);
            }
        }
        const setDepth = (node, depth) => {
            node.depth = depth;
            node.children.forEach(c => setDepth(c, depth + 1));
        };
        roots.forEach(r => setDepth(r, 0));

        this._categoryTree = roots;
        this._categoryMap = catMap;
    }

    get visibleCategories() {
        const result = [];
        const expanded = this.state.expandedCategoryIds;
        const traverse = (nodes) => {
            for (const node of nodes) {
                result.push(node);
                if (node.children.length && expanded.includes(node.id)) {
                    traverse(node.children);
                }
            }
        };
        traverse(this._categoryTree || []);
        return result;
    }

    toggleCategoryExpand(ev, catId) {
        ev.stopPropagation();
        const idx = this.state.expandedCategoryIds.indexOf(catId);
        if (idx >= 0) {
            this.state.expandedCategoryIds.splice(idx, 1);
        } else {
            this.state.expandedCategoryIds.push(catId);
        }
    }

    // ── Product History ──

    async onProductMouseEnter(productId) {
        this.state.hoveredProductId = productId;
        if (this._historyCache[productId]) {
            this.state.historyData = this._historyCache[productId];
            return;
        }
        this.state.historyLoading = true;
        try {
            const data = await this.orm.call(
                "purchase.pop.order",
                "get_product_purchase_history",
                [productId]
            );
            this._historyCache[productId] = data;
            if (this.state.hoveredProductId === productId) {
                this.state.historyData = data;
            }
        } finally {
            this.state.historyLoading = false;
        }
    }

    onProductMouseLeave() {
        this.state.hoveredProductId = false;
        this.state.historyData = null;
    }

    // ── Currency ──

    formatCurrency(amount) {
        const cur = this.state.currency;
        if (!cur || !cur.symbol) return amount.toFixed(2);
        const formatted = amount.toFixed(cur.decimal_places ?? 2);
        return cur.position === 'before'
            ? `${cur.symbol}\u00A0${formatted}`
            : `${formatted}\u00A0${cur.symbol}`;
    }

    // ── Getters ──

    getBasketQty(productId) {
        const line = this.state.orderLines.find((l) => l.product_id === productId);
        return line ? line.qty : 0;
    }

    getSelectedLineQty() {
        if (!this.state.selectedLineId) return 0;
        const line = this.state.orderLines.find(l => l.product_id === this.state.selectedLineId);
        return line ? line.qty : 0;
    }

    get totalItems() {
        return this.state.orderLines.reduce((sum, l) => sum + l.qty, 0);
    }

    get totalAmount() {
        return this.state.orderLines.reduce((sum, l) => sum + (l.qty * (l.price || 0)), 0);
    }

    get selectedVendorName() {
        if (!this.state.selectedVendorId) return '';
        const vendor = this.state.vendors.find(v => v.id === this.state.selectedVendorId);
        return vendor ? vendor.display_name : '';
    }

    get selectedWarehouseName() {
        if (!this.state.selectedWarehouseId) return '';
        const wh = this.state.warehouses.find(w => w.id === this.state.selectedWarehouseId);
        return wh ? wh.name : '';
    }

    get hasMinQtyWarnings() {
        return this.state.orderLines.some(l => l.min_qty > 0 && l.qty < l.min_qty);
    }

    // ── Data Loading ──

    async loadProducts() {
        this.state.loadingProducts = true;
        try {
            this.state.products = await this.orm.call(
                "purchase.pop.order",
                "get_pop_products",
                [
                    this.state.selectedVendorId || false,
                    this.state.selectedCategoryId || false,
                    this.state.search.trim() || false,
                    this.state.selectedWarehouseId || false,
                ]
            );
        } finally {
            this.state.loadingProducts = false;
        }
    }

    async selectCategory(categoryId) {
        this.state.selectedCategoryId = categoryId;
        this.state.showMobileSidebar = false;
        await this.loadProducts();
    }

    async onVendorChange(ev) {
        const vendorId = parseInt(ev.target.value, 10) || false;
        this.state.selectedVendorId = vendorId;
        this.state.selectedOrderId = false;
        this.state.editableOrders = [];
        
        await this.loadProducts();
        if (vendorId) {
            this.state.editableOrders = await this.orm.call("purchase.pop.order", "get_editable_orders", [vendorId]);
        }
        
        for (const line of this.state.orderLines) {
            const product = this.state.products.find(p => p.id === line.product_id);
            if (product) {
                line.price = product.price ?? 0;
                line.has_vendor_price = product.has_vendor_price;
                line.min_qty = product.min_qty ?? 0;
            }
        }
    }

    async onOrderChange(ev) {
        const orderId = parseInt(ev.target.value, 10) || false;
        this.state.selectedOrderId = orderId;
        this.clearBasket();

        if (!orderId) {
            return;
        }

        const lines = await this.orm.call("purchase.pop.order", "get_order_lines", [orderId]);
        const order = this.state.editableOrders.find(o => o.id === orderId);
        
        for (const line of lines) {
            const product = this.state.products.find(p => p.id === line.product_id);
            this.state.orderLines.push({
                product_id: line.product_id,
                name: line.name || (product ? product.name : ''),
                default_code: product ? product.default_code || "" : "",
                min_qty: product ? product.min_qty || 0 : 0,
                has_vendor_price: product ? product.has_vendor_price : false,
                qty_available: product ? product.qty_available || 0 : 0,
                qty: line.qty,
                qty_received: line.qty_received || 0,
                uom_name: product ? product.uom_name : '',
                price: line.price,
            });
        }
    }

    async onWarehouseChange(ev) {
        this.state.selectedWarehouseId = parseInt(ev.target.value, 10) || false;
        await this.loadProducts();
    }

    onSearchInput(ev) {
        this.state.search = ev.target.value;
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(() => this.loadProducts(), 350);
    }

    async onSearchKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            clearTimeout(this._searchTimer);
            await this.loadProducts();
        }
    }

    // ── Basket ──

    addProduct(product) {
        const existing = this.state.orderLines.find((l) => l.product_id === product.id);
        if (existing) {
            existing.qty += 1;
            this.selectLine(product.id, true);
            return;
        }
        this.state.orderLines.push({
            product_id: product.id,
            name: product.name,
            default_code: product.default_code || "",
            min_qty: product.min_qty || 0,
            has_vendor_price: product.has_vendor_price,
            qty_available: product.qty_available || 0,
            qty: product.min_qty > 1 ? product.min_qty : 1,
            uom_name: product.uom_name,
            price: product.price || 0,
        });
        this.selectLine(product.id, true);
    }

    selectLine(productId, fresh = false) {
        this.state.swipedLineId = false;
        if (this.state.selectedLineId === productId && !fresh) {
            this.state.selectedLineId = false;
            this.state.numpadTempValue = "";
            return;
        }
        this.state.selectedLineId = productId;
        const line = this.state.orderLines.find(l => l.product_id === productId);
        this.state.numpadTempValue = fresh ? "" : (line ? line.qty.toString() : "");
    }

    removeLine(productId) {
        const idx = this.state.orderLines.findIndex((l) => l.product_id === productId);
        if (idx !== -1) {
            const line = this.state.orderLines[idx];
            if (line.qty_received > 0) {
                this.notification.add(`Cannot remove product that has already been partially received.`, { type: "warning" });
                this.state.swipedLineId = false;
                return;
            }
            this.state.orderLines.splice(idx, 1);
            if (this.state.selectedLineId === productId) {
                this.state.selectedLineId = false;
                this.state.numpadTempValue = "";
            }
            if (this.state.swipedLineId === productId) {
                this.state.swipedLineId = false;
            }
        }
    }

    clearBasket() {
        this.state.orderLines.splice(0);
        this.state.note = "";
        this.state.selectedLineId = false;
        this.state.numpadTempValue = "";
        this.state.swipedLineId = false;
    }

    // ── Swipe Gestures ──

    onLineTouchStart(ev) {
        this._touchStartX = ev.touches[0].clientX;
    }

    onLineTouchEnd(ev, productId) {
        const deltaX = ev.changedTouches[0].clientX - this._touchStartX;
        if (deltaX < -60) {
            this.state.swipedLineId = productId;
        } else if (deltaX > 40) {
            this.state.swipedLineId = false;
        }
    }

    // ── Numpad ──

    onNumpadPress(key) {
        if (!this.state.selectedLineId) return;
        const line = this.state.orderLines.find(l => l.product_id === this.state.selectedLineId);
        if (!line) return;

        if (key === 'BACKSPACE') {
             this.state.numpadTempValue = this.state.numpadTempValue.slice(0, -1);
        } else if (key === '+1' || key === '-1') {
             let cur = parseFloat(this.state.numpadTempValue || line.qty || 0);
             if (key === '+1') cur += 1;
             if (key === '-1') cur -= 1;
             
             if (cur < (line.qty_received || 0)) {
                 cur = line.qty_received || 0;
             } else if (cur < 0) {
                 cur = 0;
             }
             this.state.numpadTempValue = cur.toString();
        } else if (key === '.') {
             // Only allow one decimal point
             if (!this.state.numpadTempValue.includes('.')) {
                 this.state.numpadTempValue += this.state.numpadTempValue.length ? '.' : '0.';
             }
        } else {
             this.state.numpadTempValue += key;
        }

        const newQty = parseFloat(this.state.numpadTempValue);
        line.qty = isNaN(newQty) ? 0 : newQty;
    }

    applyNumpadValue() {
         if (!this.state.selectedLineId) return;
         const line = this.state.orderLines.find(l => l.product_id === this.state.selectedLineId);
         if (line && line.qty < (line.qty_received || 0)) {
             line.qty = line.qty_received;
             this.notification.add(`Cannot reduce below received quantity (${line.qty_received}).`, { type: "warning" });
         } else if (line && line.qty <= 0) {
             this.removeLine(this.state.selectedLineId);
         }
         this.state.selectedLineId = false;
         this.state.numpadTempValue = "";
    }

    // ── Confirm Flow ──

    requestConfirm() {
        this.state.orderLines = this.state.orderLines.filter(l => l.qty > 0);
        if (!this.state.selectedVendorId) {
            this.notification.add("Please select a supplier.", { type: "warning" });
            return;
        }
        if (!this.state.orderLines.length) {
            this.notification.add("Add at least one product.", { type: "warning" });
            return;
        }
        this.state.showConfirmDialog = true;
    }

    cancelConfirmDialog() {
        this.state.showConfirmDialog = false;
    }

    async confirmOrder() {
        this.state.showConfirmDialog = false;
        this.state.submitting = true;
        try {
            const rpcMethod = this.state.selectedOrderId ? "action_update_from_ui" : "action_confirm_from_ui";
            const rpcArgs = this.state.selectedOrderId
                ? [this.state.selectedOrderId, this.state.orderLines, this.state.note || false, this.state.selectedWarehouseId || false]
                : [this.state.selectedVendorId, this.state.orderLines, this.state.note || false, this.state.selectedWarehouseId || false];

            const result = await this.orm.call("purchase.pop.order", rpcMethod, rpcArgs);
            
            this.state.lastConfirmedPO = {
                id: result.purchase_order_id,
                name: result.purchase_order_name,
                popId: result.pop_order_id,
            };
            this.clearBasket();
            const actionText = this.state.selectedOrderId ? "updated" : "confirmed";
            this.notification.add(`Purchase order ${result.purchase_order_name} ${actionText}.`, { type: "success" });
            
            // Wipe editable orders so they refresh cleanly next pull
            if (this.state.selectedOrderId) {
                this.state.selectedOrderId = false;
                if (this.state.selectedVendorId) {
                    this.state.editableOrders = await this.orm.call("purchase.pop.order", "get_editable_orders", [this.state.selectedVendorId]);
                }
            }
        } catch (e) {
            this.notification.add(e.message || e.data?.message || "Failed to process purchase order.", { type: "danger" });
        } finally {
            this.state.submitting = false;
        }
    }

    async openLastPO() {
        if (!this.state.lastConfirmedPO) return;
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "purchase.order",
            res_id: this.state.lastConfirmedPO.id,
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    dismissConfirmBanner() {
        this.state.lastConfirmedPO = null;
    }

    // ── Fullscreen ──

    toggleFullscreen() {
        this.state.fullscreen = !this.state.fullscreen;
        document.body.classList.toggle('o_pop_fullscreen', this.state.fullscreen);
    }

    // ── Mobile Toggles ──

    toggleMobileSidebar() {
        this.state.showMobileSidebar = !this.state.showMobileSidebar;
        this.state.showMobileBasket = false;
    }

    toggleMobileBasket() {
        this.state.showMobileBasket = !this.state.showMobileBasket;
        this.state.showMobileSidebar = false;
    }

    closeMobileOverlays() {
        this.state.showMobileSidebar = false;
        this.state.showMobileBasket = false;
    }

    goHome() {
        document.body.classList.remove('o_pop_fullscreen');
        this.actionService.doAction("menu");
    }
}

registry.category("actions").add("purchase_pop_action", PurchasePopAction);
