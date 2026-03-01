// ============================================
// NEXUS SHOP - Main JavaScript File
// ============================================

// Global variables
let currentUserLoggedIn = false;
let currentUserBalance = 0;

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    console.log('NEXUS SHOP loaded successfully!');
    
    // Check login status from Flask variables passed from template
    if (typeof userLoggedIn !== 'undefined') {
        currentUserLoggedIn = userLoggedIn;
        console.log('User logged in:', currentUserLoggedIn);
    }
    
    if (typeof userBalance !== 'undefined') {
        currentUserBalance = userBalance;
        console.log('User balance:', currentUserBalance);
    }
    
    // Alternative check: Look for user elements in the DOM
    if (!currentUserLoggedIn) {
        // Double-check by looking for user-welcome element
        const userWelcome = document.querySelector('.user-welcome');
        if (userWelcome) {
            currentUserLoggedIn = true;
            console.log('User detected via DOM element');
            
            // Get balance from display if not set
            if (currentUserBalance === 0) {
                const balanceDisplay = document.querySelector('.balance-display');
                if (balanceDisplay) {
                    const balanceText = balanceDisplay.textContent;
                    const balanceMatch = balanceText.match(/\$([0-9.]+)/);
                    if (balanceMatch) {
                        currentUserBalance = parseFloat(balanceMatch[1]);
                    }
                }
            }
        }
    }
    
    // Initialize product cards
    initializeProductCards();
    
    // Log login status for debugging
    console.log('Final login status:', currentUserLoggedIn);
    console.log('Final balance:', currentUserBalance);
});

// ============================================
// PRODUCT CARD FUNCTIONS
// ============================================

// Initialize product cards (disable if out of stock)
function initializeProductCards() {
    const productCards = document.querySelectorAll('.product-card');
    
    productCards.forEach(card => {
        const stockElement = card.querySelector('.stock-value');
        const buyButton = card.querySelector('.buy-btn');
        const quantityInput = card.querySelector('.quantity-input');
        const minusBtn = card.querySelector('.minus');
        const plusBtn = card.querySelector('.plus');
        
        if (stockElement) {
            const stock = parseInt(stockElement.textContent);
            
            if (stock === 0) {
                // Disable buy button
                if (buyButton) {
                    buyButton.disabled = true;
                    buyButton.style.opacity = '0.5';
                    buyButton.style.cursor = 'not-allowed';
                    buyButton.title = 'Out of stock';
                }
                
                // Disable quantity controls
                if (quantityInput) {
                    quantityInput.disabled = true;
                }
                if (minusBtn) minusBtn.disabled = true;
                if (plusBtn) plusBtn.disabled = true;
            }
        }
    });
}

// Increment quantity
function incrementQuantity(type) {
    const input = document.getElementById(`quantity-${type}`);
    if (!input) return;
    
    let value = parseInt(input.value);
    const max = parseInt(input.max) || 10;
    
    if (value < max) {
        input.value = value + 1;
    }
}

// Decrement quantity
function decrementQuantity(type) {
    const input = document.getElementById(`quantity-${type}`);
    if (!input) return;
    
    let value = parseInt(input.value);
    const min = parseInt(input.min) || 1;
    
    if (value > min) {
        input.value = value - 1;
    }
}

// ============================================
// PURCHASE FUNCTIONS
// ============================================

// Buy product function - Fixed login check
async function buyProduct(service, type) {
    console.log('Buy button clicked');
    console.log('Current login status:', currentUserLoggedIn);
    
    // Check if user is logged in - multiple checks
    if (!currentUserLoggedIn) {
        // Double-check by looking for user element
        const userWelcome = document.querySelector('.user-welcome');
        if (userWelcome) {
            // User is actually logged in, update the variable
            currentUserLoggedIn = true;
            console.log('Login status updated to true via DOM check');
        } else {
            // Really not logged in
            showNotification('Please login first', 'error');
            setTimeout(() => {
                window.location.href = '/login';
            }, 1500);
            return;
        }
    }

    // Get quantity
    const quantityInput = document.getElementById(`quantity-${type}`);
    if (!quantityInput) return;
    
    const quantity = parseInt(quantityInput.value);
    
    // Check stock
    const stockElement = document.getElementById(`${type}-stock`);
    const currentStock = parseInt(stockElement.textContent);

    if (quantity > currentStock) {
        showNotification(`Only ${currentStock} accounts available`, 'error');
        return;
    }

    // Show loading overlay
    showLoadingOverlay(true);

    try {
        console.log('Sending purchase request for:', service, quantity);
        
        const response = await fetch('/buy_account', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                service: service,
                quantity: quantity
            })
        });

        const data = await response.json();
        console.log('Purchase response:', data);

        if (data.error) {
            showNotification(data.error, 'error');
        } else {
            // Update stock display
            stockElement.textContent = currentStock - quantity;
            
            // Update balance
            if (data.new_balance !== undefined) {
                updateBalanceDisplay(data.new_balance);
                currentUserBalance = data.new_balance;
            }
            
            // Show success message with account details in notification
            if (data.accounts && data.accounts.length > 0) {
                showPurchaseSuccess(data.accounts, data.service, quantity, data.total_price);
            }
            
            // Add to order history
            addToOrderHistory(data);
            
            // Re-initialize product cards
            initializeProductCards();
        }
    } catch (error) {
        console.error('Error:', error);
        showNotification('An error occurred. Please try again.', 'error');
    } finally {
        showLoadingOverlay(false);
    }
}

// Show loading overlay
function showLoadingOverlay(show) {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
        overlay.style.display = show ? 'flex' : 'none';
    }
}

// Update balance display
function updateBalanceDisplay(newBalance) {
    const balanceDisplay = document.querySelector('.balance-display');
    if (balanceDisplay) {
        balanceDisplay.innerHTML = `<i class="fas fa-wallet"></i> Balance: $${newBalance.toFixed(2)}`;
    }
}

// Show purchase success with copy options
function showPurchaseSuccess(accounts, service, quantity, totalPrice) {
    // Create a custom notification with copy options
    const container = document.getElementById('notificationContainer');
    if (!container) return;
    
    // Remove existing notifications
    const existingNotifications = container.querySelectorAll('.notification');
    existingNotifications.forEach(notif => notif.remove());
    
    // Create notification element
    const notification = document.createElement('div');
    notification.className = 'notification notification-success purchase-success';
    
    // Create accounts HTML
    let accountsHTML = '';
    accounts.forEach((account, index) => {
        accountsHTML += `
            <div class="purchase-account-item">
                <div class="purchase-account-header">
                    <strong>Account #${index + 1}</strong>
                    <button class="copy-account-btn-mini" onclick='copyToClipboard("${escapeHtml(account.pipe_format)}")'>
                        <i class="fas fa-copy"></i>
                    </button>
                </div>
                <div class="purchase-account-details" onclick='copyToClipboard("${escapeHtml(account.pipe_format)}")'>
                    ${escapeHtml(account.pipe_format.substring(0, 50))}...
                </div>
            </div>
        `;
    });
    
    notification.innerHTML = `
        <div class="purchase-success-header">
            <i class="fas fa-check-circle"></i>
            <span>Purchase Successful!</span>
            <button class="close-notification" onclick="this.parentElement.parentElement.remove()">×</button>
        </div>
        <div class="purchase-success-body">
            <div class="purchase-summary">
                <p><strong>Service:</strong> ${escapeHtml(service)}</p>
                <p><strong>Quantity:</strong> ${quantity}</p>
                <p><strong>Total:</strong> $${totalPrice.toFixed(2)}</p>
            </div>
            <div class="purchase-accounts">
                ${accountsHTML}
            </div>
            <div class="purchase-actions">
                <button class="copy-all-btn-small" onclick='copyAllAccountsFromList(${JSON.stringify(accounts.map(a => a.pipe_format))})'>
                    <i class="fas fa-copy"></i> Copy All Accounts
                </button>
            </div>
        </div>
    `;
    
    container.appendChild(notification);
    
    // Auto remove after 10 seconds
    setTimeout(() => {
        if (notification.parentElement) {
            notification.remove();
        }
    }, 10000);
}

// Copy all accounts from list
function copyAllAccountsFromList(accounts) {
    let allAccountsText = '';
    accounts.forEach((account, index) => {
        allAccountsText += `Account #${index + 1}:\n${account}\n\n`;
    });
    
    copyToClipboard(allAccountsText);
}

// ============================================
// CLIPBOARD FUNCTIONS
// ============================================

// Copy to clipboard function
function copyToClipboard(text) {
    // Decode HTML entities if present
    const textarea = document.createElement('textarea');
    textarea.innerHTML = text;
    const cleanText = textarea.value;
    
    navigator.clipboard.writeText(cleanText).then(() => {
        showNotification('✅ Copied to clipboard!', 'success');
    }).catch(err => {
        console.error('Failed to copy: ', err);
        showNotification('❌ Failed to copy', 'error');
    });
}

// Escape HTML special characters
function escapeHtml(unsafe) {
    if (!unsafe) return '';
    return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// ============================================
// ORDER HISTORY FUNCTIONS
// ============================================

// Add to order history
function addToOrderHistory(data) {
    const tbody = document.getElementById('order-history-body');
    if (!tbody) return;
    
    // Remove "no orders" row if exists
    const noOrdersRow = tbody.querySelector('.no-orders');
    if (noOrdersRow && noOrdersRow.parentElement === tbody) {
        tbody.innerHTML = '';
    }
    
    // Add each purchased account to history
    if (data.accounts && data.accounts.length > 0) {
        data.accounts.forEach(account => {
            const row = document.createElement('tr');
            
            // Safely escape the pipe format
            const escapedPipeFormat = escapeHtml(account.pipe_format);
            const previewText = account.pipe_format.length > 30 ? 
                account.pipe_format.substring(0, 30) + '...' : 
                account.pipe_format;
            
            row.innerHTML = `
                <td><span class="status-badge status-completed">Completed</span></td>
                <td>
                    <div class="account-details" onclick='copyToClipboard("${escapedPipeFormat}")' title="Click to copy">
                        ${escapeHtml(previewText)}
                        <i class="fas fa-copy copy-icon"></i>
                    </div>
                </td>
                <td>${escapeHtml(data.service)}</td>
                <td>$${(data.total_price / data.quantity).toFixed(2)}</td>
                <td>${new Date().toLocaleString()}</td>
                <td>
                    <button class="copy-btn-small" onclick='copyToClipboard("${escapedPipeFormat}")'>
                        <i class="fas fa-copy"></i>
                    </button>
                </td>
            `;
            
            tbody.insertBefore(row, tbody.firstChild);
        });
    }
}

// ============================================
// NOTIFICATION FUNCTIONS
// ============================================

// Show notification
function showNotification(message, type) {
    const container = document.getElementById('notificationContainer');
    if (!container) return;
    
    // Remove existing notifications
    const existingNotifications = container.querySelectorAll('.notification:not(.purchase-success)');
    existingNotifications.forEach(notif => notif.remove());
    
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    
    let icon = 'fa-info-circle';
    if (type === 'success') icon = 'fa-check-circle';
    if (type === 'error') icon = 'fa-exclamation-circle';
    
    notification.innerHTML = `
        <i class="fas ${icon}"></i>
        <span>${escapeHtml(message)}</span>
    `;
    
    container.appendChild(notification);
    
    // Remove after 3 seconds
    setTimeout(() => {
        if (notification.parentElement) {
            notification.remove();
        }
    }, 3000);
}

// ============================================
// UTILITY FUNCTIONS
// ============================================

// Generate transaction ID
function generateTransactionId() {
    return 'TXN' + Date.now().toString(36).toUpperCase();
}
// View order details
async function viewOrderDetails(orderId) {
    try {
        const response = await fetch(`/api/order/${orderId}`);
        const data = await response.json();
        
        if (data.error) {
            showNotification(data.error, 'error');
            return;
        }
        
        // Show order details in notification
        let accountsText = '';
        data.accounts.forEach((account, index) => {
            accountsText += `Account #${index + 1}:\n${account}\n\n`;
        });
        
        const notification = document.createElement('div');
        notification.className = 'notification notification-info order-details';
        notification.innerHTML = `
            <div class="order-details-header">
                <i class="fas fa-shopping-bag"></i>
                <span>Order #${orderId}</span>
                <button class="close-notification" onclick="this.parentElement.parentElement.remove()">×</button>
            </div>
            <div class="order-details-body">
                <p><strong>Service:</strong> ${escapeHtml(data.service)}</p>
                <p><strong>Quantity:</strong> ${data.quantity}</p>
                <p><strong>Total:</strong> $${data.total_price.toFixed(2)}</p>
                <p><strong>Date:</strong> ${new Date(data.created_at).toLocaleString()}</p>
                <div class="order-accounts">
                    <strong>Accounts:</strong>
                    <pre>${escapeHtml(accountsText)}</pre>
                </div>
                <button class="copy-all-btn-small" onclick='copyToClipboard(${JSON.stringify(accountsText)})'>
                    <i class="fas fa-copy"></i> Copy All
                </button>
            </div>
        `;
        
        document.getElementById('notificationContainer').appendChild(notification);
        
    } catch (error) {
        console.error('Error:', error);
        showNotification('Failed to load order details', 'error');
    }
}
