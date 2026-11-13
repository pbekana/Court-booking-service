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

---

## 📖 Interactive API Documentation

When the FastAPI server is running:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **OpenAPI JSON**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)
