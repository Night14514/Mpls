# Layer Architecture for Security Implementation

## Layer Separation Strategy

### 1. Application Layer (handlers/ + relay/)
**Purpose**: UI routing, Telegram API integration
**Protection Level**: Low (keep readable for maintenance)
**Files**:
- handlers/*.py (all UI routing)
- relay/*.py (Telegram integration)
- keyboards.py (UI components)
- states.py (FSM states)

### 2. Business Logic Layer (services/ + core/)
**Purpose**: Critical business algorithms, financial operations
**Protection Level**: CRITICAL (maximum protection)
**Files**:
- core/order_engine.py (CRITICAL - compile + encrypt)
- services/order_service.py (CRITICAL - compile + encrypt)
- services/crypto_payment.py (CRITICAL - compile + encrypt)
- services/stars_payment.py (CRITICAL - compile + encrypt)
- services/balance_service.py (CRITICAL - compile + encrypt)
- services/product_service.py (HIGH - compile)
- services/user_service.py (HIGH - compile)
- services/promo_service.py (HIGH - compile)

### 3. Data Layer (db/ + models/)
**Purpose**: Database abstraction, data models
**Protection Level**: MEDIUM (obfuscate + encrypt strings)
**Files**:
- db/connection.py (obfuscate + encrypt)
- models.py (keep structure, encrypt sensitive fields)

### 4. Security Layer (security/)
**Purpose**: Protection mechanisms, integrity verification
**Protection Level**: HIGH (obfuscate + encrypt)
**Files**:
- security/integrity.py (obfuscate + encrypt)
- security/encryption.py (obfuscate + encrypt)
- security/anti_debug.py (obfuscate + encrypt)

### 5. Configuration Layer
**Purpose**: Application configuration
**Protection Level**: LOW (environment variables)
**Files**:
- config.py (keep readable, use env vars)
- utils.py (obfuscate business utilities)

## Critical Module Extraction

### Extracted Business Core (NEW)

I'll create a new `business_core/` directory to hold the most critical business logic:

```
business_core/
├── __init__.py
├── order_lifecycle.py       # Extracted from core/order_engine.py
├── payment_processor.py     # Extracted from services/*_payment.py
├── balance_operations.py     # Extracted from services/balance_service.py
├── admin_workflow.py         # Extracted from handlers/admin.py
└── pricing_engine.py         # Extracted from various services
```

## Dependency Injection Pattern

To enable dynamic loading and better separation:

```python
# business_core/interface.py
from abc import ABC, abstractmethod

class IOrderService(ABC):
    @abstractmethod
    async def create_order(self, user_id: int, product_id: int, price: float):
        pass

class IPaymentService(ABC):
    @abstractmethod
    async def process_payment(self, order_id: int, payment_data: dict):
        pass
```

## Module Reorganization Plan

### Phase 1: Extract Critical Business Logic
1. Create `business_core/` directory
2. Extract critical algorithms from existing modules
3. Create interface definitions
4. Maintain backward compatibility

### Phase 2: Refactor for Dependency Injection
1. Create abstract interfaces
2. Implement concrete classes in business_core/
3. Update handlers to use interfaces
4. Maintain existing functionality

### Phase 3: Prepare for Compilation
1. Ensure all imports are explicit
2. Remove circular dependencies
3. Add type hints for Cython
4. Create separate entry points

## Compatibility Layer

To ensure zero functional changes:

```python
# services/order_service.py (compatibility wrapper)
from business_core.order_lifecycle import OrderLifecycle

class OrderService:
    """Compatibility wrapper for existing code"""
    
    @classmethod
    async def create_order(cls, *args, **kwargs):
        return await OrderLifecycle.create_order(*args, **kwargs)
```

## Implementation Plan

### Step 1: Create Business Core Structure
### Step 2: Extract Critical Algorithms
### Step 3: Create Compatibility Wrappers
### Step 4: Test Functionality
### Step 5: Prepare for Cython Compilation
