# Court Booking Backend
## System Design Document

**Project:** Community Sports Court Booking System  
**Backend Stack:** Python 3.11, FastAPI, SQLAlchemy 2, PostgreSQL 15  
**Database Migration:** Alembic  
**Testing:** Pytest  
**Code Quality:** Ruff and mypy  
**Containerization:** Docker and Docker Compose  
**Payment Method:** Google Pay (through a supported payment provider)

---

# 1. Project Overview

The Court Booking Backend is a reservation management system for a community sports club that operates multiple sports courts across different venues.

The primary purpose of the system is to allow members to discover available courts, reserve courts temporarily, confirm bookings through payment, and manage their existing reservations.

The system also provides staff with weekly court utilization reports to help them monitor how effectively the club's facilities are being used.

The main problem this system addresses is double-booking, where multiple members attempt to reserve the same court for overlapping time periods.

The backend must guarantee that a court cannot have overlapping active reservations, even when multiple booking requests arrive simultaneously.

The system will use a two-step booking process:

1. Temporary reservation (Hold).
2. Booking confirmation after successful payment.

Unconfirmed reservations will automatically expire so that they cannot permanently prevent other members from booking a court.

---

# 2. Project Objectives

The main objectives are:

1. Allow members to register and authenticate securely.
2. Allow members to browse venues and available sports courts.
3. Allow members to temporarily reserve available courts.
4. Allow members to confirm reservations through Google Pay.
5. Support individual and weekly recurring bookings.
6. Prevent multiple members from booking the same court at overlapping times.
7. Allow members to cancel their bookings.
8. Apply the club's cancellation and refund policy.
9. Enforce a maximum of three active future bookings per member.
10. Allow members to view their booking history and current booking status.
11. Allow authorized staff to view weekly court utilization.
12. Provide a reliable, secure, and maintainable backend.

---

# 3. User Roles and Permissions

The system will initially support two main roles.

## 3.1 Member

Members are authenticated users who can:

- Register an account.
- Log in and log out.
- View available venues and courts.
- Check court availability.
- Create temporary reservations.
- Complete payments using Google Pay.
- Confirm reservations.
- Create weekly recurring bookings.
- View their upcoming bookings.
- View their booking history.
- Cancel their bookings.
- View payment and refund status.

A member cannot:

- Access another member's private booking information.
- Access staff reports.
- Manage venues or courts.
- Override booking restrictions.
- Create more than three active future bookings.

## 3.2 Staff

Staff members are responsible for monitoring the sports facilities.

They can:

- View weekly court utilization.
- View booking statistics.
- View court occupancy information.
- View reservation information required for operational purposes.

Staff members cannot access administrative functionality unless additional permissions are introduced.

---

# 4. Functional Requirements

## FR-01: User Registration

The system must allow new members to register.

Required information:

- Full name.
- Email address.
- Password.

The system must:

- Validate registration information.
- Prevent duplicate email registrations.
- Hash passwords before storing them.
- Store the user's role.
- Create the member account.

## FR-02: Authentication

Members must authenticate before accessing protected booking functionality.

The system will use JWT-based authentication.

Authentication requirements:

- Login using email and password.
- Generate access tokens.
- Validate access tokens.
- Protect private endpoints.
- Enforce role-based authorization.

Passwords must never be stored as plain text.

## FR-03: Court Discovery and Availability

Members must be able to browse available courts across different venues.

The availability system must consider:

- Existing confirmed bookings.
- Active temporary holds.
- Expired holds.
- Court operating hours.
- Court availability.
- Peak and off-peak pricing.

Members must not be able to reserve courts outside their operating hours.

## FR-04: Temporary Reservation

Members must first create a temporary reservation before confirming a booking.

Endpoint:

`POST /holds`

The request contains:

- Court ID.
- Start time.
- End time.

The backend must:

1. Authenticate the member.
2. Validate the requested time period.
3. Check the member's booking limit.
4. Check court availability.
5. Calculate the applicable price.
6. Create a temporary hold.
7. Set an expiration timestamp.
8. Return the hold information.

**Hold expiration policy:**

The initial assumption is that temporary holds expire after 10 minutes.

This duration will be configurable.

If payment is not completed before expiration, the hold becomes expired and the court becomes available again.

The expiration process must work even if a background cleanup worker is temporarily unavailable.

Availability and booking operations must independently recognize expired holds.

## FR-05: Payment and Booking Confirmation

The system will use Google Pay as its intended digital wallet payment method.

Google Pay integration will use a compatible payment service provider (PSP) or payment gateway.

Google Pay provides the payment credential/token, while the payment provider processes the actual transaction.

The payment process will work as follows:

1. A member creates a temporary hold.
2. The frontend presents Google Pay as a payment option.
3. The member selects Google Pay and authorizes payment.
4. Google Pay returns a payment token to the frontend.
5. The frontend sends the payment information to the backend.
6. The backend communicates with the payment provider.
7. The payment provider processes the transaction.
8. The backend verifies the payment result.
9. The booking is confirmed if payment succeeds.
10. The member receives booking confirmation.

The backend must never trust a payment-success message supplied directly by the frontend.

Payment status must be verified through the payment provider's trusted server-side response or webhook.

### Confirmation Endpoint

`POST /holds/{id}/confirm`

The endpoint must:

- Verify ownership of the hold.
- Check whether the hold has expired.
- Verify payment status.
- Prevent duplicate confirmation.
- Create or associate the confirmed booking.
- Return the existing booking if the same confirmation is retried.

### Payment States

Initial payment states:

- PENDING
- SUCCESSFUL
- FAILED
- REFUNDED
- PARTIALLY_REFUNDED

### Booking States

Initial booking states:

- HELD
- CONFIRMED
- CANCELLED
- EXPIRED

Payment and booking statuses must be managed separately.

A failed payment must not create a confirmed booking.

If payment succeeds but booking confirmation fails, the system must support safe retries and payment reconciliation.

The implementation will use a mock payment provider during development and testing. Production integration will use a supported Google Pay payment provider.

## FR-06: Booking Cancellation

Endpoint:

`POST /bookings/{id}/cancel`

Members can cancel their confirmed bookings.

The refund policy is:

| Cancellation time | Refund |
|---|---|
| At least 24 hours before booking | 100% |
| Less than 24 hours before booking | 0% |

The backend will calculate the refund automatically using the booking's start time and the venue's timezone.

The cancellation operation must:

1. Authenticate the member.
2. Verify booking ownership.
3. Check booking status.
4. Calculate the refund eligibility.
5. Update booking status.
6. Initiate a refund when eligible.
7. Record the refund result.

External payment operations must be handled safely so that a failed refund attempt does not leave the database in an inconsistent state.

## FR-07: Weekly Recurring Bookings

Members must be able to reserve the same court for a particular day and time across multiple weeks.

Example:

- Court: Court A.
- Day: Saturday.
- Start: 10:00 AM.
- End: 11:00 AM.
- Duration: 8 weeks.

The backend will generate individual booking occurrences for the requested weeks.

Each occurrence must independently satisfy:

- Court availability.
- Member booking limits.
- Operating hours.
- Pricing rules.

### Recurring Booking Policy

The initial design uses an all-or-nothing approach.

If one requested occurrence is unavailable, the entire recurring booking request will be rejected.

No partial recurring reservations should remain in the database.

Each occurrence counts as an individual active future booking toward the three-booking limit.

Members can view their recurring booking series and cancel individual occurrences or the remaining series, subject to the cancellation policy.

## FR-08: Member Booking History

Members must be able to view their bookings.

The information should include:

- Booking ID.
- Venue.
- Court.
- Booking date.
- Start time.
- End time.
- Booking status.
- Payment status.
- Amount paid.
- Refund status, if applicable.

Members must only access their own booking information.

## FR-09: Weekly Court Utilization

Authorized staff must be able to view weekly court utilization.

The report should include:

- Venue.
- Court.
- Total operating hours.
- Total booked hours.
- Total available hours.
- Utilization percentage.
- Number of confirmed bookings.

Utilization will be calculated using:

Utilization Percentage = (Confirmed Booked Hours / Total Operating Hours) × 100

Cancelled and expired bookings will not count as utilized hours.

Active temporary holds will be reported separately and will not count as confirmed utilization.

---

# 5. Non-Functional Requirements

## NFR-01: Security

The system must:

- Hash passwords securely.
- Use JWT authentication.
- Implement role-based access control.
- Validate all incoming requests.
- Protect sensitive payment information.
- Prevent unauthorized booking access.
- Use environment variables for secrets.
- Validate payment provider webhooks.
- Apply appropriate request rate limits.

## NFR-02: Concurrency Safety

The system must prevent double-booking under concurrent requests.

Multiple users may attempt to reserve the same court and time simultaneously.

The database must guarantee that only one overlapping active reservation can exist for a particular court.

PostgreSQL exclusion constraints using GiST indexes and range types will be considered the primary protection mechanism.

The application must also handle database constraint violations gracefully.

## NFR-03: Booking Limit

A member can have at most three active future bookings.

For this initial design:

- Confirmed future bookings count toward the limit.
- Active temporary holds also count toward the limit.
- Expired and cancelled reservations do not count.
- Recurring booking occurrences count individually.

The limit must be enforced inside database transactions to prevent concurrent requests from bypassing it.

## NFR-04: Idempotency

A client may retry a request because of a timeout or network failure.

Repeating the same confirmation request must never create another booking or duplicate payment.

The backend will use:

- Unique hold identifiers.
- Idempotency keys.
- Database transactions.
- Unique payment references.
- Payment provider idempotency support.

Repeated confirmation requests for an already-confirmed hold must return the same logical booking result.

## NFR-05: Transaction Integrity

A failed multi-step database operation must not leave partial state.

The system will use SQLAlchemy database transactions.

For example, recurring booking creation must either:

- Successfully create every requested occurrence; or
- Roll back the entire database operation.

External services such as payment providers cannot participate in PostgreSQL transactions.

Therefore, external payment operations will use idempotency, payment records, webhook processing, and reconciliation or compensation mechanisms.

## NFR-06: Maintainability

The backend will use a modular architecture.

Business logic will be separated from API routes, database models, and request schemas.

Code must pass:

- Ruff linting.
- mypy type checking.
- pytest automated tests.

Inline type-checking and linting suppressions will not be used.

## NFR-07: Deployment

The complete system must run using:

`docker compose up`

The application, PostgreSQL database, and required supporting services must be configured through Docker Compose.

Database migrations must be managed through Alembic.

---

# 6. Database Design

The initial database will use PostgreSQL 15.

The following tables are proposed.

## 6.1 Users

Stores member and staff information.

Fields:

- id
- full_name
- email
- password_hash
- role
- is_active
- created_at
- updated_at

## 6.2 Venues

Stores sports club locations.

Fields:

- id
- name
- address
- timezone
- opening_time
- closing_time
- created_at

## 6.3 Courts

Stores individual sports courts.

Fields:

- id
- venue_id
- name
- sport_type
- is_active
- created_at

## 6.4 Pricing Rules

Stores peak and off-peak pricing.

Fields:

- id
- court_id
- pricing_type
- start_time
- end_time
- day_of_week
- hourly_rate
- effective_from
- effective_until

The pricing system must support different prices for peak and off-peak periods.

The booking will store a price snapshot so that future pricing changes do not modify existing booking prices.

## 6.5 Holds

Stores temporary court reservations.

Fields:

- id
- user_id
- court_id
- start_time
- end_time
- expires_at
- status
- idempotency_key
- created_at

## 6.6 Bookings

Stores confirmed reservations.

Fields:

- id
- user_id
- court_id
- hold_id
- start_time
- end_time
- total_price
- status
- created_at
- cancelled_at

## 6.7 Payments

Stores payment transaction information.

Fields:

- id
- booking_id
- hold_id
- provider
- provider_transaction_id
- amount
- currency
- status
- payment_reference
- created_at
- updated_at

Sensitive payment credentials must not be stored in this table.

## 6.8 Recurring Series

Stores recurring booking information.

Fields:

- id
- user_id
- court_id
- day_of_week
- start_time
- end_time
- recurrence_start_date
- recurrence_end_date
- status
- created_at

## 6.9 Booking Occurrences

Stores individual occurrences belonging to a recurring series.

Fields:

- id
- recurring_series_id
- booking_id
- occurrence_date
- status

## 6.10 Idempotency Records

Stores request idempotency information.

Fields:

- id
- user_id
- idempotency_key
- request_hash
- response_reference
- created_at

The idempotency key must be unique within its appropriate user and operation scope.

---

# 7. API Design

The system will expose RESTful HTTP endpoints.

The following four endpoints are fixed by the assignment and must retain their exact paths.

## 7.1 Authentication

| Method | Endpoint | Description |
|---|---|---|
| POST | /auth/register | Register a member |
| POST | /auth/login | Authenticate a member |
| GET | /auth/me | Get authenticated user |

## 7.2 Court Availability

| Method | Endpoint | Description |
|---|---|---|
| GET | /courts | List courts |
| GET | /courts/{id} | Get court details |
| GET | /courts/{id}/availability | Check availability |

## 7.3 Holds

| Method | Endpoint | Description |
|---|---|---|
| POST | /holds | Create temporary reservation |
| GET | /holds/{id} | View hold status |
| POST | /holds/{id}/confirm | Confirm reservation |

## 7.4 Bookings

| Method | Endpoint | Description |
|---|---|---|
| GET | /members/me/bookings | View member bookings |
| GET | /bookings/{id} | View booking details |
| POST | /bookings/{id}/cancel | Cancel booking |

## 7.5 Payments

| Method | Endpoint | Description |
|---|---|---|
| POST | /payments | Initiate payment |
| GET | /payments/{id} | Check payment status |
| POST | /payments/webhook | Receive verified provider events |

## 7.6 Recurring Bookings

| Method | Endpoint | Description |
|---|---|---|
| POST | /recurring-bookings | Create weekly recurring booking |
| GET | /recurring-bookings/{id} | View recurring series |
| DELETE | /recurring-bookings/{id} | Cancel remaining series |

## 7.7 Staff Reports

| Method | Endpoint | Description |
|---|---|---|
| GET | /staff/reports/utilization | Weekly court utilization |

All protected endpoints must require authentication and appropriate authorization.

---

# 8. Booking Lifecycle

The booking lifecycle will follow these states:

```text
              MEMBER SELECTS COURT
                       |
                       v
                 CHECK AVAILABILITY
                       |
                       v
                 CREATE HOLD
                       |
                       v
                     HELD
                       |
                 PAYMENT STARTED
                       |
                +------+------+
                |             |
                v             v
          PAYMENT SUCCESS  PAYMENT FAILED
                |             |
                v             v
          CONFIRM BOOKING   HOLD REMAINS
                |           UNTIL EXPIRY
                v             |
            CONFIRMED         v
                          HOLD EXPIRED
```

A confirmed booking can later transition to CANCELLED.

An unconfirmed hold can transition to EXPIRED.

Expired holds must no longer prevent other members from reserving the same time slot.

---

# 9. Concurrency and Double-Booking Prevention

Preventing double-booking is a primary system guarantee.

The application will not rely exclusively on checking availability in Python.

The primary protection will be implemented at the PostgreSQL database level.

The proposed approach is:

1. Represent booking periods using PostgreSQL time ranges.
2. Use a GiST exclusion constraint to prevent overlapping active reservations for the same court.
3. Use `btree_gist` to support equality checks on court identifiers.
4. Include active holds and confirmed bookings in the conflict-prevention strategy.
5. Handle expired holds transactionally.
6. Return an appropriate conflict response when a reservation cannot be created.

Conceptually:

```sql
EXCLUDE USING GIST (
    court_id WITH =,
    booking_period WITH &&
)
WHERE (status IN ('HELD', 'CONFIRMED'));
```

The final database implementation must account for expired holds before attempting a new reservation.

The system will also use independent database sessions in concurrency tests.

The target is to prove that only one request can successfully reserve an overlapping court period, even when many requests arrive simultaneously.

---

# 10. Idempotency and Retry Safety

Network failures may cause clients to retry requests.

For example:

1. A member submits a confirmation request.
2. The backend confirms the booking.
3. The response is lost.
4. The member retries the request.

The system must return the existing booking instead of creating another one.

Idempotency will be implemented using unique request keys and database constraints.

Payment requests must also use the payment provider's idempotency capabilities.

The system must distinguish between:

- A new confirmation request.
- A repeated confirmation request.
- A request with the same key but different information.

Requests with conflicting reuse of an idempotency key must be rejected.

---

# 11. Transaction Management

SQLAlchemy transactions will be used for operations involving multiple database changes.

Examples include:

- Creating a booking.
- Confirming a hold.
- Creating recurring booking occurrences.
- Cancelling a booking.
- Recording payment results.

A database operation must either complete successfully or roll back its database changes.

For external payment operations, the system will use a reliable integration strategy rather than assuming that a database rollback can reverse an external transaction.

Payment webhooks must be authenticated, processed idempotently, and recorded.

The system must support reconciliation when a payment succeeds but the corresponding booking update fails.

---

# 12. Pricing Strategy

Venues can have different peak and off-peak pricing.

The pricing service will calculate the total booking price using:

- Court.
- Venue.
- Booking date.
- Start time.
- End time.
- Applicable pricing rules.

A booking that crosses peak and off-peak periods must be priced according to the applicable rate for each period.

All prices will be stored using an exact decimal monetary representation rather than floating-point numbers.

The transaction currency will be configurable and must be supported by the selected payment provider.

---

# 13. Security and Authorization

The system will implement role-based access control.

Members can only manage their own bookings and payments.

Staff members can access authorized reporting endpoints.

The system will also implement:

- Secure password hashing.
- JWT validation.
- Input validation.
- SQL injection protection through SQLAlchemy.
- Rate limiting.
- Secure environment configuration.
- Payment webhook signature verification.
- Ownership checks.
- Protection against unauthorized access to other members' information.

---

# 14. Assumptions

The original task does not define every business rule.

The following assumptions will guide the initial implementation.

| Area | Assumption |
|---|---|
| User registration | Members register using name, email, and password. |
| Authentication | JWT-based authentication. |
| User roles | Member and staff. |
| Hold duration | 10 minutes, configurable. |
| Booking limit | Three active future bookings per member. |
| Hold limit | Active holds count toward the member's booking limit. |
| Recurrence | Weekly recurrence for a defined date range. |
| Recurring failures | All-or-nothing creation. |
| Payment | Google Pay through a supported payment provider. |
| Development payments | Mock payment provider. |
| Cancellation | Full refund at least 24 hours before the booking. |
| Late cancellation | No refund. |
| Pricing | Peak and off-peak pricing. |
| Time storage | UTC timestamps with venue-local scheduling rules. |
| Database | PostgreSQL 15. |
| Deployment | Docker Compose. |

---

# 15. Open Questions for the Client

The following questions should be clarified before production implementation.

### Booking Rules

1. Is the 10-minute hold duration acceptable?
2. Can members book multiple different courts on the same day?
3. Should members be allowed to book courts at different venues?
4. Should the maximum of three bookings include temporary holds?
5. How far into the future can members make reservations?

### Recurring Bookings

6. How many weeks can a recurring booking continue?
7. Should a recurring booking fail completely if one occurrence is unavailable?
8. Can members cancel individual occurrences?
9. Can staff modify recurring bookings?

### Payments

10. Which payment service provider will process Google Pay transactions?
11. Does the selected provider support the club's country and transaction currency?
12. Should payment be captured immediately or authorized first?
13. What should happen when payment succeeds but booking confirmation fails?
14. Should refunds be processed automatically?

### Pricing

15. Are peak and off-peak periods configured per venue or per court?
16. Can prices vary depending on the day of the week?
17. Can prices change during holidays?

### Staff

18. Can staff cancel or modify member bookings?
19. Should staff see member information in utilization reports?
20. Should utilization reports include temporary holds?

These questions will be revisited as the client clarifies requirements.

---

# 16. Alternatives Conside
red and Rejected

## 16.1 SQLite Instead of PostgreSQL

Rejected because PostgreSQL provides stronger concurrency capabilities, exclusion constraints, range types, and transaction support needed for reliable court reservations.

## 16.2 Application-Level Availability Checks Only

Rejected because simultaneous requests can pass the same availability check before either request creates a reservation.

Database-level constraints provide stronger protection.

## 16.3 Permanent Reservations Without Holds

Rejected because members could reserve courts without completing payment.

Temporary holds ensure that unsuccessful reservations eventually release their slots.

## 16.4 One-Day Hold Expiration

Rejected because a one-day reservation could unnecessarily prevent other members from accessing a court.

A shorter configurable expiration period is more appropriate.

## 16.5 Microservices Architecture

Rejected for the initial implementation.

A modular monolithic architecture is easier to maintain, test, deploy, and reason about transactionally for this project.

## 16.6 Direct Payment Credential Processing

Rejected because the backend should not directly handle or store sensitive card credentials.

Google Pay will be integrated through a compatible payment service provider.

---

# 17. Testing Strategy

Automated tests will be written using pytest.

The testing strategy will cover unit, integration, and concurrency tests.

### Authentication Tests

- Successful registration.
- Duplicate email registration.
- Invalid credentials.
- Unauthorized access.
- Role-based authorization.

### Booking Tests

- Successful hold creation.
- Hold expiration.
- Booking confirmation.
- Cancellation.
- Booking ownership.
- Maximum three active future bookings.

### Concurrency Tests

- Two members requesting the same court and time simultaneously.
- Multiple simultaneous requests for the same court.
- Expired hold followed by a new reservation.
- Concurrent requests attempting to exceed the member booking limit.

### Idempotency Tests

- Repeated confirmation request.
- Confirmation after successful payment.
- Duplicate payment requests.
- Reuse of an idempotency key with different request data.

### Recurring Booking Tests

- Successful recurring reservation.
- Unavailable occurrence.
- Atomic rollback when one occurrence fails.
- Booking limit enforcement across occurrences.

### Payment Tests

- Successful payment.
- Failed payment.
- Duplicate payment notification.
- Refund eligibility.
- Refund failure and retry.

### Transaction Tests

- Database failure during booking confirmation.
- Database failure during recurring booking creation.
- Rollback of incomplete database operations.

### Utilization Tests

- Correct weekly utilization calculation.
- Exclusion of cancelled bookings.
- Exclusion of expired holds.
- Staff-only report access.

---

# 18. Project Structure

The proposed backend structure is:

```text
court-booking-backend/
│
├── app/
│   ├── main.py
│   │
│   ├── core/
│   │   ├── config.py
│   │   ├── database.py
│   │   └── security.py
│   │
│   ├── models/
│   │   ├── user.py
│   │   ├── venue.py
│   │   ├── court.py
│   │   ├── hold.py
│   │   ├── booking.py
│   │   ├── payment.py
│   │   └── recurring.py
│   │
│   ├── schemas/
│   │
│   ├── api/
│   │   └── routes/
│   │
│   ├── services/
│   │   ├── booking_service.py
│   │   ├── hold_service.py
│   │   ├── payment_service.py
│   │   ├── pricing_service.py
│   │   ├── recurring_service.py
│   │   └── utilization_service.py
│   │
│   └── workers/
│       └── hold_expiration.py
│
├── alembic/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── concurrency/
│
├── .github/
│   └── workflows/
│       └── ci.yml
│
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── README.md
├── DESIGN.md
└── LIMITATIONS.md
```

---

# 19. Development and Delivery Plan

The project will be implemented incrementally.

| Phase | Description | Deliverable |
|---|---|---|
| 1 | Requirements analysis and system design | DESIGN.md |
| 2 | Database schema and migrations | Database implementation |
| 3 | FastAPI and Docker configuration | Running backend |
| 4 | Registration and authentication | Authentication module |
| 5 | Court discovery and availability | Court module |
| 6 | Temporary holds | Hold module |
| 7 | Confirmation and concurrency protection | Booking module |
| 8 | Google Pay payment integration | Payment module |
| 9 | Cancellation and refunds | Cancellation module |
| 10 | Weekly recurring bookings | Recurring module |
| 11 | Weekly utilization reports | Reporting module |
| 12 | Automated testing | Complete test suite |
| 13 | Documentation and CI | README, LIMITATIONS, GitHub Actions |
| 14 | Final demonstration | Live walkthrough and video |

---

# 20. Success Criteria

The project will be considered successful when:

1. Members can register and authenticate.
2. Members can discover available courts.
3. Members can create temporary reservations.
4. Unconfirmed reservations expire automatically.
5. Members can confirm bookings after successful payment.
6. Google Pay can be integrated through the selected payment provider.
7. Members can cancel bookings according to the refund policy.
8. Members can create weekly recurring bookings.
9. No member can exceed three active future bookings.
10. Courts cannot be double-booked under concurrent requests.
11. Retrying a confirmation request does not create duplicate bookings.
12. Failed database operations do not leave partial state.
13. Staff can view weekly court utilization.
14. Automated tests prove the critical system guarantees.
15. Ruff and mypy checks pass.
16. The complete application runs using Docker Compose.

---

**End of Design Document**
