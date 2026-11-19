from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass
class PaymentResult:
    success: bool
    status: str
    provider_transaction_id: str | None
    error_message: str | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class RefundResult:
    success: bool
    status: str
    refund_transaction_id: str | None
    error_message: str | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)


class BasePaymentProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the payment provider."""

    @abstractmethod
    def initiate_payment(
        self,
        amount: Decimal,
        currency: str,
        payment_reference: str,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentResult:
        """Initiate payment with provider."""

    @abstractmethod
    def verify_payment(
        self,
        provider_transaction_id: str,
    ) -> PaymentResult:
        """Verify payment status with provider."""

    @abstractmethod
    def refund_payment(
        self,
        provider_transaction_id: str,
        amount: Decimal,
        currency: str,
        idempotency_key: str | None = None,
        reason: str | None = None,
    ) -> RefundResult:
        """Process refund with provider."""
