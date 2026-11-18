# Court Booking Service - Backend

A high-performance backend for managing physical sports venues, courts, reservations, and bookings built with **Python 3.11+**, **FastAPI**, **SQLAlchemy 2.0**, and **PostgreSQL 15**.

---

## 🏛 Layered Architecture

The application strictly follows a clean layered architecture:

```
Backend/app/
├── models/                     # SQLAlchemy 2.0 Declarative Models
│   ├── venue.py                # Venue model (table: venues)
│   ├── court.py                # Court model (table: courts)
│   ├── reservations.py         # Reservation model (table: reservations)
│   └── user.py                 # User model (table: users)
│
├── schemas/                    # Pydantic v2 Request & Response Schemas
│   ├── venue.py                # VenueCreate, VenueUpdate, VenueResponse
│   ├── court.py                # CourtCreate, CourtUpdate, CourtResponse, CourtDetailResponse
│   ├── auth.py                 # Token, UserLogin, UserPublic, AuthResponse
│   └── user.py                 # UserRegister
│
├── repositories/               # Database Persistence & Query Layer
│   ├── venue_repository.py     # Venue CRUD & reservation dependency checks
│   └── court_repository.py     # Court CRUD & reservation dependency checks
│
├── services/                   # Business Logic & Validation Layer
│   ├── venue_service.py        # Venue business logic & validations
│   └── court_service.py        # Court business logic & validations
│
├── routers/                    # FastAPI API Endpoints
│   ├── venue.py                # Venue REST endpoints (/api/v1/venues)
│   └── court.py                # Court REST endpoints (/api/v1/courts)
│
├── auth/                       # Authentication & Authorization
│   ├── router.py               # Auth endpoints (/api/v1/auth)
│   └── dependencies.py         # get_current_user, require_role, require_roles
│
├── core/
│   ├── db.py                   # SQLAlchemy engine, session maker, get_db
│   ├── config.py               # Environment configuration
│   └── security.py             # Password hashing (bcrypt) & JWT issuance
│
├── database/
│   └── connection.py           # Database connection re-exports
│
└── main.py                     # FastAPI application entrypoint & router registry
```

---

## 🔐 Authorization & Role-Based Access Control (RBAC)

The system supports three user roles:
- **`ADMIN`**: Full administrative management. Can create, update, deactivate, and view venues and courts.
- **`STAFF`**: Facility staff. Can view venues and courts, but cannot create, update, or deactivate them.
- **`MEMBER`**: Regular sports club member. Can view active venues and courts, but cannot view inactive facilities or manage them.
- **Unauthenticated**: Returns `401 Unauthorized`.

### Permissions Matrix

| Endpoint | Method | MEMBER | STAFF | ADMIN |
|---|---|:---:|:---:|:---:|
| `/api/v1/venues` | POST | ❌ 403 | ❌ 403 | ✅ 201 |
| `/api/v1/venues` | GET | ✅ (Active only) | ✅ (All) | ✅ (All) |
| `/api/v1/venues/{id}` | GET | ✅ (Active only) | ✅ (All) | ✅ (All) |
| `/api/v1/venues/{id}` | PATCH | ❌ 403 | ❌ 403 | ✅ 200 |
| `/api/v1/venues/{id}` | DELETE | ❌ 403 | ❌ 403 | ✅ 204 |
| `/api/v1/courts` | POST | ❌ 403 | ❌ 403 | ✅ 201 |
| `/api/v1/courts` | GET | ✅ (Active only) | ✅ (All) | ✅ (All) |
| `/api/v1/courts/{id}` | GET | ✅ (Active only) | ✅ (All) | ✅ (All) |
| `/api/v1/courts/{id}` | PATCH | ❌ 403 | ❌ 403 | ✅ 200 |
| `/api/v1/courts/{id}` | DELETE | ❌ 403 | ❌ 403 | ✅ 204 |

---

## 🏟 Venue Management Endpoints

All venue endpoints are prefixed with `/api/v1/venues`.

### 1. Create Venue
- **Endpoint**: `POST /api/v1/venues`
- **Authorization**: `ADMIN` only
- **Validation**:
  - `name`: Non-empty string (max 100 chars).
  - `address`: Optional string (max 255 chars).
  - `timezone`: Valid IANA timezone string (e.g. `"Africa/Addis_Ababa"`).
  - `opening_time`: Daily opening time (`HH:MM:SS`).
  - `closing_time`: Daily closing time (`HH:MM:SS`). Must be strictly later than `opening_time`.
- **Request Body**:
```json
{
  "name": "Bole Sports Club",
  "address": "Bole Medhanialem, Addis Ababa",
  "timezone": "Africa/Addis_Ababa",
  "opening_time": "06:00:00",
  "closing_time": "22:00:00"
}
```
- **Response** (`201 Created`):
```json
{
  "id": "e4b6c310-9c0b-4ef8-bb6d-6bb9bd380a11",
  "name": "Bole Sports Club",
  "address": "Bole Medhanialem, Addis Ababa",
  "timezone": "Africa/Addis_Ababa",
  "opening_time": "06:00:00",
  "closing_time": "22:00:00",
  "is_active": true,
  "created_at": "2026-11-14T01:00:00Z"
}
```

### 2. Get All Venues
- **Endpoint**: `GET /api/v1/venues`
- **Authorization**: `ADMIN`, `STAFF`, `MEMBER`
- **Query Parameters**:
  - `active_only` (bool, default `true`): When called by Staff/Admin, allows viewing inactive venues if set to `false`. Members always only see active venues.
- **Response** (`200 OK`):
```json
[
  {
    "id": "e4b6c310-9c0b-4ef8-bb6d-6bb9bd380a11",
    "name": "Bole Sports Club",
    "address": "Bole Medhanialem, Addis Ababa",
    "timezone": "Africa/Addis_Ababa",
    "opening_time": "06:00:00",
    "closing_time": "22:00:00",
    "is_active": true,
    "created_at": "2026-11-14T01:00:00Z"
  }
]
```

### 3. Get Venue by ID
- **Endpoint**: `GET /api/v1/venues/{venue_id}`
- **Authorization**: `ADMIN`, `STAFF`, `MEMBER`
- **Response** (`200 OK`):
```json
{
  "id": "e4b6c310-9c0b-4ef8-bb6d-6bb9bd380a11",
  "name": "Bole Sports Club",
  "address": "Bole Medhanialem, Addis Ababa",
  "timezone": "Africa/Addis_Ababa",
  "opening_time": "06:00:00",
  "closing_time": "22:00:00",
  "is_active": true,
  "created_at": "2026-11-14T01:00:00Z"
}
```
- **Error**: `404 Not Found` if venue does not exist or if an inactive venue is queried by a Member.

### 4. Update Venue
- **Endpoint**: `PATCH /api/v1/venues/{venue_id}`
- **Authorization**: `ADMIN` only
- **Request Body** (all fields optional):
```json
{
  "name": "Bole Premier Sports Arena",
  "address": "Cameroon St, Addis Ababa",
  "closing_time": "23:00:00"
}
```
- **Response** (`200 OK`):
```json
{
  "id": "e4b6c310-9c0b-4ef8-bb6d-6bb9bd380a11",
  "name": "Bole Premier Sports Arena",
  "address": "Cameroon St, Addis Ababa",
  "timezone": "Africa/Addis_Ababa",
  "opening_time": "06:00:00",
  "closing_time": "23:00:00",
  "is_active": true,
  "created_at": "2026-11-14T01:00:00Z"
}
```

### 5. Deactivate Venue
- **Endpoint**: `DELETE /api/v1/venues/{venue_id}`
- **Authorization**: `ADMIN` only
- **Behavior**: Soft-deletes the venue (`is_active = FALSE`).
- **Protection**: Rejects deactivation with `409 Conflict` if any court within the venue has active future reservations (`HELD` or `CONFIRMED` status with `end_at > now()`). Historical booking and reservation records are preserved.
- **Response**: `204 No Content`

---

## 🏸 Court Management Endpoints

All court endpoints are prefixed with `/api/v1/courts`.

### 1. Create Court
- **Endpoint**: `POST /api/v1/courts`
- **Authorization**: `ADMIN` only
- **Validation**:
  - `venue_id`: Associated venue UUID. Target venue must exist and must be active.
  - `name`: Non-empty string (max 100 chars). Court name must be unique within the venue (case-insensitive).
  - `sport_type`: Non-empty string (e.g., Tennis, Basketball, Squash, Padel).
- **Request Body**:
```json
{
  "venue_id": "e4b6c310-9c0b-4ef8-bb6d-6bb9bd380a11",
  "name": "Center Court",
  "sport_type": "Tennis"
}
```
- **Response** (`201 Created`):
```json
{
  "id": "f5c7d421-0d1c-5fa9-cc7e-7cc0ce491b22",
  "venue_id": "e4b6c310-9c0b-4ef8-bb6d-6bb9bd380a11",
  "name": "Center Court",
  "sport_type": "Tennis",
  "is_active": true,
  "created_at": "2026-11-14T01:05:00Z"
}
```
- **Errors**:
  - `400 Bad Request`: If target venue is inactive.
  - `404 Not Found`: If target venue does not exist.
  - `409 Conflict`: If a court with the same name already exists in the venue.

### 2. Get All Courts
- **Endpoint**: `GET /api/v1/courts`
- **Authorization**: `ADMIN`, `STAFF`, `MEMBER`
- **Optional Query Filters**:
  - `venue_id` (UUID): Filter by associated venue.
  - `sport_type` (str): Filter by sport type (case-insensitive).
  - `active_only` (bool, default `true`): Staff/Admin can view inactive courts when set to `false`.
- **Response** (`200 OK`):
```json
[
  {
    "id": "f5c7d421-0d1c-5fa9-cc7e-7cc0ce491b22",
    "venue_id": "e4b6c310-9c0b-4ef8-bb6d-6bb9bd380a11",
    "name": "Center Court",
    "sport_type": "Tennis",
    "is_active": true,
    "created_at": "2026-11-14T01:05:00Z"
  }
]
```

### 3. Get Court by ID
- **Endpoint**: `GET /api/v1/courts/{court_id}`
- **Authorization**: `ADMIN`, `STAFF`, `MEMBER`
- **Description**: Returns court details along with its associated venue object.
- **Response** (`200 OK`):
```json
{
  "id": "f5c7d421-0d1c-5fa9-cc7e-7cc0ce491b22",
  "venue_id": "e4b6c310-9c0b-4ef8-bb6d-6bb9bd380a11",
  "name": "Center Court",
  "sport_type": "Tennis",
  "is_active": true,
  "created_at": "2026-11-14T01:05:00Z",
  "venue": {
    "id": "e4b6c310-9c0b-4ef8-bb6d-6bb9bd380a11",
    "name": "Bole Sports Club",
    "address": "Bole Medhanialem, Addis Ababa",
    "timezone": "Africa/Addis_Ababa",
    "opening_time": "06:00:00",
    "closing_time": "22:00:00",
    "is_active": true,
    "created_at": "2026-11-14T01:00:00Z"
  }
}
```
- **Error**: `404 Not Found` if court does not exist or if inactive court is queried by a Member.

### 4. Update Court
- **Endpoint**: `PATCH /api/v1/courts/{court_id}`
- **Authorization**: `ADMIN` only
- **Validation**:
  - If `venue_id` is changed, the new venue must exist and must be active.
  - If `name` or `venue_id` is updated, court name must remain unique in the target venue.
- **Request Body** (all fields optional):
```json
{
  "name": "Court 1 - Covered",
  "sport_type": "Tennis",
  "venue_id": "e4b6c310-9c0b-4ef8-bb6d-6bb9bd380a11"
}
```
- **Response** (`200 OK`):
```json
{
  "id": "f5c7d421-0d1c-5fa9-cc7e-7cc0ce491b22",
  "venue_id": "e4b6c310-9c0b-4ef8-bb6d-6bb9bd380a11",
  "name": "Court 1 - Covered",
  "sport_type": "Tennis",
  "is_active": true,
  "created_at": "2026-11-14T01:05:00Z"
}
```

### 5. Deactivate Court
- **Endpoint**: `DELETE /api/v1/courts/{court_id}`
- **Authorization**: `ADMIN` only
- **Behavior**: Soft-deletes the court (`is_active = FALSE`).
- **Protection**: Rejects deactivation with `409 Conflict` if the court has active future reservations (`HELD` or `CONFIRMED` status with `end_at > now()`).
- **Response**: `204 No Content`

---

## 📅 Court Availability Management

Check whether a court is available for a requested date and time interval, including peak/off-peak pricing calculations, operating hours verification, hold expiration synchronization, and conflict detection.

### Check Court Availability
- **Endpoints**:
  - `GET /courts/{court_id}/availability`
  - `GET /api/v1/courts/{court_id}/availability`
- **Authorization**: Public / Member
- **Interval Convention**: `[start_at, end_at)` (half-open, adjacent bookings are allowed).

#### Query Parameters
| Parameter | Type | Required | Description | Example |
|---|---|:---:|---|---|
| `start_at` | string (ISO 8601 with timezone) | Yes | Requested reservation start timestamp | `2026-11-20T09:00:00+03:00` |
| `end_at` | string (ISO 8601 with timezone) | Yes | Requested reservation end timestamp | `2026-11-20T10:00:00+03:00` |

#### Example Request
```http
GET /courts/f5c7d421-0d1c-5fa9-cc7e-7cc0ce491b22/availability?start_at=2026-11-20T09:00:00%2B03:00&end_at=2026-11-20T10:00:00%2B03:00 HTTP/1.1
Host: localhost:8000
```

#### Example Successful Response (`200 OK` - Available)
```json
{
  "court_id": "f5c7d421-0d1c-5fa9-cc7e-7cc0ce491b22",
  "venue_id": "e4b6c310-9c0b-4ef8-bb6d-6bb9bd380a11",
  "available": true,
  "requested_interval": {
    "start_at": "2026-11-20T09:00:00+03:00",
    "end_at": "2026-11-20T10:00:00+03:00"
  },
  "pricing": {
    "currency": "ETB",
    "total_price": 500.00,
    "segments": [
      {
        "pricing_type": "OFF_PEAK",
        "start_at": "2026-11-20T09:00:00+03:00",
        "end_at": "2026-11-20T10:00:00+03:00",
        "hourly_rate": 500.00,
        "subtotal": 500.00
      }
    ]
  },
  "message": "Court is available for the requested time."
}
```

#### Example Unavailable Responses (`200 OK` - Unavailable)
When the court is already reserved:
```json
{
  "court_id": "f5c7d421-0d1c-5fa9-cc7e-7cc0ce491b22",
  "available": false,
  "message": "Court is already reserved for the requested time."
}
```
When the requested time is outside venue operating hours:
```json
{
  "court_id": "f5c7d421-0d1c-5fa9-cc7e-7cc0ce491b22",
  "available": false,
  "message": "Requested time falls outside venue operating hours."
}
```
When the court or venue is inactive:
```json
{
  "court_id": "f5c7d421-0d1c-5fa9-cc7e-7cc0ce491b22",
  "available": false,
  "message": "Court is inactive."
}
```

#### Error Responses
- **`400 Bad Request`**: Invalid date/time range:
  - `End time must be later than start time` (when `end_at <= start_at`).
  - `Reservation start time must be in the future` (when `start_at <= now()`).
- **`404 Not Found`**:
  - `Court not found` (when `court_id` does not exist).
- **`422 Unprocessable Content`**: Invalid query parameters or unsupported booking interval:
  - `Missing timezone information` (when timestamps lack timezone offset).
  - `No valid pricing rule found for the requested court and time interval` (when pricing rules are missing or expired).
  - `Venue operating schedule is unsupported` (when overnight operating schedule `opening_time >= closing_time` is configured).

---

## ⚠️ HTTP Status Code Mapping

| Status Code | Meaning | Example Scenario |
|---|---|---|
| `200 OK` | Successful retrieval or update | Venue or court details returned / updated |
| `201 Created` | Successful creation | New venue or court created |
| `204 No Content` | Successful deactivation | Venue or court soft-deleted |
| `400 Bad Request` | Invalid input or business logic violation | Target venue is inactive; opening_time >= closing_time |
| `401 Unauthorized` | Missing or invalid authentication token | No Bearer token provided or token expired |
| `403 Forbidden` | Insufficient permissions | Member or Staff attempting to create/modify venues or courts |
| `404 Not Found` | Resource not found | Invalid venue_id or court_id |
| `409 Conflict` | Conflicting or duplicate resource | Duplicate court name in venue; active future reservations exist |
| `422 Unprocessable` | Schema validation error | Malformed UUID; invalid IANA timezone; empty string |
| `500 Server Error` | Unexpected internal server error | Internal uncaught database error |

---

## 🧪 Running the Tests

The test suite runs against an isolated PostgreSQL test database (`court_booking_service_test_db`) using a non-destructive transaction savepoint rollback mechanism. Every individual test executes within its own savepoint and rolls back immediately upon completion, guaranteeing that no test data is ever persisted.

### Run All Tests
```bash
cd Backend
.venv/bin/pytest
```

### Run Tests with Verbose Output
```bash
cd Backend
.venv/bin/pytest -v
```

### Run Venue Tests Only
```bash
cd Backend
.venv/bin/pytest tests/unit/test_venue.py -v
```

### Run Court Tests Only
```bash
cd Backend
.venv/bin/pytest tests/unit/test_court.py -v
```

### Run Court Availability Tests Only
```bash
cd Backend
.venv/bin/pytest tests/unit/test_availability.py -v
```

### Run Concurrency Tests Only
```bash
cd Backend
.venv/bin/pytest tests/concurrency/ -v
```

---

## 📖 Interactive API Documentation

When the FastAPI server is running:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **OpenAPI JSON**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)


---

# 🏷 Peak & Off-Peak Pricing Management (Module 1)

The backend provides a complete configurable pricing management engine allowing administrators to define court prices based on the day of the week, time of day, and effective calendar dates.

## Pricing Features & Capabilities

- **Peak vs. Off-Peak Classification:** Classify court hours into `PEAK` or `OFF_PEAK`.
- **Per-Court Custom Schedules:** Different courts can maintain completely independent pricing tiers.
- **Day-of-Week Specificity:** Rules can target specific days (`0=Monday` to `6=Sunday`) or apply to all days (`null`). Day-specific rules override general rules.
- **Overnight & Midnight-Crossing Schedules:** Pricing rules and booking requests that span across midnight (e.g., `22:00` to `06:00` or spanning from Sunday evening into Monday morning) are automatically split and mapped to their corresponding schedules.
- **Venue Timezone Context:** All scheduling and boundary calculations are evaluated against the venue's configured IANA timezone (default `Africa/Addis_Ababa`).
- **Precision Decimal Arithmetic:** All monetary rates and totals are computed using Python's `Decimal` with two-decimal-place rounding (`0.01`), eliminating floating-point errors.
- **Immutable Price Snapshots:** Upon confirmation, the exact total price and currency are snapshotted onto the `bookings` record (`bookings.total_price`, `bookings.currency`). Future modifications or deactivations of pricing rules will never alter historical booking prices.
- **Audit Preservation:** Rule deletions perform soft-deactivation (`is_active = False`) to preserve complete audit history.

## Pricing Calculation Engine Workflow

1. Retrieve all candidate active rules covering the local calendar dates of the requested interval.
2. Identify boundary transition points:
   - Requested start and end times in local venue time.
   - Every midnight (`00:00:00`) between start and end dates.
   - Rule start and end time boundaries falling within the booking window.
3. For each continuous interval segment:
   - Sample the midpoint datetime, determine the local calendar date and day of week.
   - Match candidate rules.
   - Disallow intervals with zero covering rules (HTTP `422 Unprocessable Content`).
   - Disallow intervals with ambiguous conflicting rules (HTTP `422 Unprocessable Content`).
   - Calculate segment duration in fractional hours and subtotal: `(hourly_rate * hours).quantize(Decimal("0.01"))`.
4. Merge contiguous adjacent segments sharing identical pricing types and hourly rates.
5. Aggregate segment subtotals into `total_price` and return a detailed `PricingBreakdown`.

---

# 🛡 Member Booking Limit Enforcement (Module 2)

To maintain fair facility access, each club member is restricted to a maximum of **THREE (3) active future bookings** at any given time.

## Booking Count Rules

### What Counts:
1. **Confirmed Future Bookings:** Confirmed bookings whose `end_at` timestamp is in the future.
2. **Active Temporary Holds:** Unexpired temporary holds (`status="HELD"`) whose `expires_at` timestamp is in the future.

### What Does NOT Count:
- **Expired Holds:** Holds whose expiration timestamp has elapsed. Stale holds are transitioned to `EXPIRED` before limit evaluation.
- **Cancelled Bookings:** Any booking or hold marked `CANCELLED`.
- **Completed Past Bookings:** Confirmed bookings whose `end_at` is in the past.
- **Failed Booking Attempts:** Any rolled-back or uncompleted transactions.

The central `reservations` table is the single source of truth for all active occupancy and lifecycle tracking.

## Concurrency Protection & Locking Strategy

To prevent race conditions where a member sends simultaneous requests to bypass the limit:
1. **Per-Member Transaction Lock:** A member-specific lock is acquired immediately before checking active reservations:
   - Row-level lock: `SELECT id FROM users WHERE id = :user_id FOR UPDATE`
   - Transaction-scoped PostgreSQL advisory lock: `SELECT pg_advisory_xact_lock(:lock_id)`
2. **Atomic Verification & Creation:**
   - Outdated member holds are expired.
   - Active reservations are counted.
   - If count reaches or exceeds 3, HTTP `409 Conflict` is returned immediately.
   - Court row is locked and checked for court-level double bookings.
   - Reservation and hold records are created within the same atomic transaction.
   - Commit releases both member and court locks.
3. **Double-Count Prevention on Confirmation:** When confirming a hold, the hold's own reservation is excluded from the pre-check so it is not double-counted.

---

# 📡 API Reference & Example Payloads

## 1. Pricing Management Endpoints

### Create Pricing Rule (Admin Only)
- **Method / Endpoint:** `POST /pricing-rules` or `POST /api/v1/pricing-rules`
- **Request Body:**
```json
{
  "court_id": "8c6b45a0-6f78-43d9-9524-7667bf91d09e",
  "pricing_type": "PEAK",
  "start_time": "12:00:00",
  "end_time": "18:00:00",
  "day_of_week": 0,
  "hourly_rate": "600.00",
  "currency": "ETB",
  "effective_from": "2026-01-01",
  "effective_until": "2026-12-31"
}
```
- **Response (`201 Created`):**
```json
{
  "id": "e44d5671-5079-4592-802c-7b0bfe9873d1",
  "court_id": "8c6b45a0-6f78-43d9-9524-7667bf91d09e",
  "pricing_type": "PEAK",
  "start_time": "12:00:00",
  "end_time": "18:00:00",
  "day_of_week": 0,
  "hourly_rate": "600.00",
  "currency": "ETB",
  "effective_from": "2026-01-01",
  "effective_until": "2026-12-31",
  "is_active": true,
  "created_at": "2026-11-18T20:00:00Z"
}
```

### Preview Booking Pricing
- **Method / Endpoint:** `POST /pricing/preview` or `POST /api/v1/pricing/preview`
- **Request Body:**
```json
{
  "court_id": "8c6b45a0-6f78-43d9-9524-7667bf91d09e",
  "start_at": "2026-06-01T07:00:00Z",
  "end_at": "2026-06-01T11:00:00Z"
}
```
- **Response (`200 OK`):**
```json
{
  "currency": "ETB",
  "total_price": "1800.00",
  "segments": [
    {
      "pricing_type": "OFF_PEAK",
      "start_at": "2026-06-01T07:00:00Z",
      "end_at": "2026-06-01T09:00:00Z",
      "hourly_rate": "300.00",
      "subtotal": "600.00"
    },
    {
      "pricing_type": "PEAK",
      "start_at": "2026-06-01T09:00:00Z",
      "end_at": "2026-06-01T11:00:00Z",
      "hourly_rate": "600.00",
      "subtotal": "1200.00"
    }
  ]
}
```

### Retrieve Pricing Rules
- `GET /pricing-rules?court_id={id}&active_only=true`
- `GET /pricing-rules/{id}`
- `GET /courts/{court_id}/pricing-rules`

### Update Pricing Rule (Admin Only)
- **Method / Endpoint:** `PUT /pricing-rules/{id}`
- **Request Body:**
```json
{
  "hourly_rate": "750.00",
  "pricing_type": "PEAK"
}
```

### Delete/Deactivate Pricing Rule (Admin Only)
- **Method / Endpoint:** `DELETE /pricing-rules/{id}`
- **Response (`200 OK`):**
```json
{
  "message": "Pricing rule deleted successfully"
}
```

---

## 2. Member Booking Limit Endpoints

### Get Member Booking Limit Status
- **Method / Endpoint:** `GET /members/me/booking-limit` or `GET /api/v1/members/me/booking-limit`
- **Headers:** `Authorization: Bearer <token>`
- **Response (`200 OK`):**
```json
{
  "success": true,
  "data": {
    "booking_limit": 3,
    "active_bookings": 2,
    "remaining_bookings": 1,
    "active_reservations": [
      {
        "id": "2b9da137-7097-4b67-93c6-e91845187768",
        "court_id": "8c6b45a0-6f78-43d9-9524-7667bf91d09e",
        "start_at": "2026-11-20T10:00:00Z",
        "end_at": "2026-11-20T11:00:00Z",
        "status": "CONFIRMED",
        "expires_at": null
      },
      {
        "id": "e98e2170-07bf-44e2-89dc-5f0ab22be269",
        "court_id": "8c6b45a0-6f78-43d9-9524-7667bf91d09e",
        "start_at": "2026-11-21T14:00:00Z",
        "end_at": "2026-11-21T15:00:00Z",
        "status": "HELD",
        "expires_at": "2026-11-18T20:45:00Z"
      }
    ]
  }
}
```

### Limit Exceeded Response (`409 Conflict`)
When a member attempts to create a hold or booking while having 3 active reservations:
```json
{
  "success": false,
  "message": "You have reached the maximum limit of 3 active future bookings.",
  "data": {
    "booking_limit": 3,
    "active_bookings": 3,
    "remaining_bookings": 0
  }
}
```

### Create Recurring Series (Member Limit Enforced)
- **Method / Endpoint:** `POST /recurring-series` or `POST /api/v1/recurring-series`
- **Request Body:**
```json
{
  "court_id": "8c6b45a0-6f78-43d9-9524-7667bf91d09e",
  "day_of_week": 2,
  "start_time": "14:00:00",
  "end_time": "15:00:00",
  "recurrence_start_date": "2026-12-01",
  "recurrence_end_date": "2026-12-15"
}
```
If the requested occurrences plus existing active reservations exceed 3, the transaction rejects with `409 Conflict` leaving no orphaned records.
