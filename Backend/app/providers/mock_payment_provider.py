import uuid
from decimal import Decimal
from typing import Any

from app.providers.base import BasePaymentProvider, PaymentResult, RefundResult


class MockPaymentProvider(BasePaymentProvider):
    """Mock payment provider for development and automated testing.

    Simulates payment initiation, verification, and refunds without
    connecting to real payment gateways or claiming to process real
    Google Pay transactions.
    """

    def __init__(self) -> None:
        self.default_payment_outcome: str = "SUCCESS"
        self.next_payment_outcome: str | None = None
        self.next_payment_error: str | None = None

        self.default_refund_outcome: str = "REFUNDED"
        self.next_refund_outcome: str | None = None
        self.next_refund_error: str | None = None

        self.should_return_invalid_response: bool = False
        self._transactions: dict[str, dict[str, Any]] = {}
        self._refund_idempotency_keys: dict[str, RefundResult] = {}
        self._refund_attempts: dict[str, int] = {}
        self.refund_calls_count: int = 0
        self.simulate_duplicate_refund_error: bool = False

    @property
    def provider_name(self) -> str:
        return "MOCK"

    def set_next_payment_outcome(
        self, status: str, error_message: str | None = None
    ) -> None:
        self.next_payment_outcome = status
        self.next_payment_error = error_message

    def set_next_refund_outcome(
        self, status: str, error_message: str | None = None
    ) -> None:
        self.next_refund_outcome = status
        self.next_refund_error = error_message

    def set_transaction_status(
        self, provider_transaction_id: str, status: str
    ) -> None:
        if provider_transaction_id in self._transactions:
            self._transactions[provider_transaction_id]["status"] = status

    def reset(self) -> None:
        self.default_payment_outcome = "SUCCESS"
        self.next_payment_outcome = None
        self.next_payment_error = None
        self.default_refund_outcome = "REFUNDED"
        self.next_refund_outcome = None
        self.next_refund_error = None
        self.should_return_invalid_response = False
        self._transactions.clear()
        self._refund_idempotency_keys.clear()
        self._refund_attempts.clear()
        self.refund_calls_count = 0
        self.simulate_duplicate_refund_error = False

    def initiate_payment(
        self,
        amount: Decimal,
        currency: str,
        payment_reference: str,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentResult:
        if self.should_return_invalid_response:
            return PaymentResult(
                success=False,
                status="INVALID",
                provider_transaction_id=None,
                error_message="Invalid response from payment provider",
                raw_response={"error": "Malformed response"},
            )

        outcome = self.next_payment_outcome or self.default_payment_outcome
        error_msg = self.next_payment_error
        self.next_payment_outcome = None
        self.next_payment_error = None

        txn_id = f"mock_txn_{uuid.uuid4().hex}"

        self._transactions[txn_id] = {
            "amount": amount,
            "currency": currency,
            "payment_reference": payment_reference,
            "status": outcome,
            "idempotency_key": idempotency_key,
            "metadata": metadata or {},
        }

        if outcome == "SUCCESS":
            return PaymentResult(
                success=True,
                status="SUCCESS",
                provider_transaction_id=txn_id,
                raw_response={
                    "provider": "MOCK",
                    "transaction_id": txn_id,
                    "status": "SUCCESS",
                    "amount": str(amount),
                    "currency": currency,
                },
            )
        elif outcome in ["PENDING", "PROCESSING"]:
            return PaymentResult(
                success=False,
                status=outcome,
                provider_transaction_id=txn_id,
                error_message=error_msg or f"Payment {outcome.lower()} with mock provider",
                raw_response={
                    "provider": "MOCK",
                    "transaction_id": txn_id,
                    "status": outcome,
                },
            )
        else:
            return PaymentResult(
                success=False,
                status="FAILED",
                provider_transaction_id=txn_id,
                error_message=error_msg or "Payment simulated as failed by mock provider",
                raw_response={
                    "provider": "MOCK",
                    "transaction_id": txn_id,
                    "status": "FAILED",
                },
            )

    def verify_payment(self, provider_transaction_id: str) -> PaymentResult:
        if self.should_return_invalid_response:
            return PaymentResult(
                success=False,
                status="INVALID",
                provider_transaction_id=provider_transaction_id,
                error_message="Invalid response from payment provider during verification",
                raw_response={"error": "Malformed response"},
            )

        txn = self._transactions.get(provider_transaction_id)
        if txn is None:
            return PaymentResult(
                success=False,
                status="FAILED",
                provider_transaction_id=provider_transaction_id,
                error_message="Transaction not found in mock provider",
                raw_response={"error": "Transaction not found"},
            )

        status = txn["status"]
        is_success = status == "SUCCESS"
        return PaymentResult(
            success=is_success,
            status=status,
            provider_transaction_id=provider_transaction_id,
            error_message=None if is_success else f"Payment status is {status}",
            raw_response={
                "provider": "MOCK",
                "transaction_id": provider_transaction_id,
                "status": status,
                "amount": str(txn["amount"]),
                "currency": txn["currency"],
            },
        )

    def refund_payment(
        self,
        provider_transaction_id: str,
        amount: Decimal,
        currency: str,
        idempotency_key: str | None = None,
        reason: str | None = None,
    ) -> RefundResult:
        self.refund_calls_count += 1

        if idempotency_key is not None:
            self._refund_attempts[idempotency_key] = (
                self._refund_attempts.get(idempotency_key, 0) + 1
            )
            if idempotency_key in self._refund_idempotency_keys:
                if self.simulate_duplicate_refund_error:
                    return RefundResult(
                        success=False,
                        status="FAILED",
                        refund_transaction_id=None,
                        error_message="Duplicate refund request rejected by provider",
                        raw_response={
                            "error": "DUPLICATE_REQUEST",
                            "idempotency_key": idempotency_key,
                        },
                    )
                # Return cached refund result for idempotent retry without creating duplicate provider txn
                return self._refund_idempotency_keys[idempotency_key]

        if self.should_return_invalid_response:
            return RefundResult(
                success=False,
                status="FAILED",
                refund_transaction_id=None,
                error_message="Invalid response from payment provider during refund",
                raw_response={"error": "Malformed response"},
            )

        outcome = self.next_refund_outcome or self.default_refund_outcome
        error_msg = self.next_refund_error
        self.next_refund_outcome = None
        self.next_refund_error = None

        refund_id = f"mock_rfnd_{uuid.uuid4().hex}"

        if outcome == "REFUNDED":
            if provider_transaction_id in self._transactions:
                self._transactions[provider_transaction_id]["status"] = "REFUNDED"
            result = RefundResult(
                success=True,
                status="REFUNDED",
                refund_transaction_id=refund_id,
                raw_response={
                    "provider": "MOCK",
                    "refund_id": refund_id,
                    "status": "REFUNDED",
                    "amount": str(amount),
                    "currency": currency,
                },
            )
            if idempotency_key is not None:
                self._refund_idempotency_keys[idempotency_key] = result
            return result
        elif outcome == "REFUND_PENDING":
            if provider_transaction_id in self._transactions:
                self._transactions[provider_transaction_id]["status"] = "REFUND_PENDING"
            result = RefundResult(
                success=True,
                status="REFUND_PENDING",
                refund_transaction_id=refund_id,
                error_message=error_msg or "Refund is pending provider processing",
                raw_response={
                    "provider": "MOCK",
                    "refund_id": refund_id,
                    "status": "REFUND_PENDING",
                },
            )
            if idempotency_key is not None:
                self._refund_idempotency_keys[idempotency_key] = result
            return result
        elif outcome == "DUPLICATE":
            return RefundResult(
                success=False,
                status="FAILED",
                refund_transaction_id=None,
                error_message=error_msg or "Duplicate refund request rejected by provider",
                raw_response={
                    "provider": "MOCK",
                    "status": "DUPLICATE",
                },
            )
        else:
            return RefundResult(
                success=False,
                status="FAILED",
                refund_transaction_id=None,
                error_message=error_msg or "Refund rejected by mock provider",
                raw_response={
                    "provider": "MOCK",
                    "status": "FAILED",
                },
            )


# Global default instance
_default_mock_provider = MockPaymentProvider()


def get_payment_provider() -> BasePaymentProvider:
    return _default_mock_provider
