"""A single durable project ledger: reserve atomically, retain unknown charges."""

from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, insert, or_, select, update

from debug_rag.errors import RagError
from debug_rag.storage.sqlite import ApiCall

PRICING = {
    "provider": "deepseek",
    "model": "deepseek-flash",
    "currency": "CNY",
    "input_per_million": "2",
    "output_per_million": "8",
    "verified_on": "2026-11-02",
    "valid_through": "2026-11-08",
    "source": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
    "method": "peak cache-miss upper bound; not a provider invoice",
}
SHANGHAI = ZoneInfo("Asia/Shanghai")
UNRESOLVED = ("reserved", "unknown", "needs_review")


def now_shanghai():
    return datetime.now(SHANGHAI)


def units(prompt_tokens: int, completion_tokens: int, pricing: dict | None = None) -> int:
    pricing = PRICING if pricing is None else pricing
    return int(
        (
            prompt_tokens * Decimal(pricing["input_per_million"])
            + completion_tokens * Decimal(pricing["output_per_million"])
        ).to_integral_value(rounding=ROUND_CEILING)
    )


def counted(month):
    # Unresolved older calls still reserve money in every subsequent month.
    return or_(ApiCall.month == month, ApiCall.status.in_(UNRESOLVED))


class BudgetLedger:
    def __init__(self, engine, limit_cny: Decimal):
        self.engine, self.limit = engine, int(limit_cny * 1_000_000)

    def summary(self) -> dict:
        month = now_shanghai().strftime("%Y-%m")
        with self.engine.connect() as connection:
            total = connection.scalar(
                select(func.coalesce(func.sum(ApiCall.charged_units), 0)).where(counted(month))
            )
            pending = connection.scalar(
                select(func.coalesce(func.sum(ApiCall.charged_units), 0)).where(
                    ApiCall.status.in_(UNRESOLVED)
                )
            )
            count = connection.scalar(
                select(func.count()).select_from(ApiCall).where(counted(month))
            )
        return {
            "month": month,
            "timezone": "Asia/Shanghai",
            "limit_cny": str(Decimal(self.limit) / 1_000_000),
            "accounted_upper_bound_cny": str(Decimal(total) / 1_000_000),
            "unresolved_reserved_cny": str(Decimal(pending) / 1_000_000),
            "remaining_cny": str(Decimal(max(0, self.limit - total)) / 1_000_000),
            "recorded_calls": count,
            "pricing": PRICING,
        }

    def reserve(
        self, model: str, purpose: str, max_input: int, max_output: int, *, pricing=None
    ) -> str:
        now = now_shanghai()
        pricing = dict(PRICING if pricing is None else pricing)
        try:
            rate_in = Decimal(pricing["input_per_million"])
            rate_out = Decimal(pricing["output_per_million"])
            valid = (
                pricing["currency"] == "CNY"
                and bool(pricing["provider"])
                and pricing["model"] == model
                and rate_in.is_finite()
                and rate_in > 0
                and rate_out.is_finite()
                and rate_out >= 0
                and date.fromisoformat(pricing["verified_on"])
                <= now.date()
                <= date.fromisoformat(pricing["valid_through"])
            )
        except (ValueError, KeyError, TypeError, ArithmeticError):
            valid = False
        if not valid:
            raise RagError(
                "pricing_not_verified", "模型价格记录已过期或不匹配，请核对官方价格后更新。", 409
            )
        if (now + timedelta(minutes=2)).month != now.month:
            raise RagError(
                "budget_month_boundary", "月末交界前两分钟暂停模型调用，请稍后重试。", 429
            )
        reserved = units(max_input, max_output, pricing)
        call_id, month = uuid4().hex, now.strftime("%Y-%m")
        with self.engine.begin() as connection:
            # Serializes all processes using this SQLite ledger, not just one Python lock.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            if connection.scalar(
                select(func.count()).select_from(ApiCall).where(ApiCall.status == "needs_review")
            ):
                raise RagError("budget_needs_review", "存在异常用量记录，核对前暂停模型调用。", 429)
            spent = connection.scalar(
                select(func.coalesce(func.sum(ApiCall.charged_units), 0)).where(counted(month))
            )
            if spent + reserved > self.limit:
                raise RagError(
                    "monthly_budget_exceeded", "项目月预算剩余额度不足，未调用模型。", 429
                )
            connection.execute(
                insert(ApiCall).values(
                    call_id=call_id,
                    month=month,
                    provider=pricing["provider"],
                    purpose=purpose,
                    requested_model=model,
                    status="reserved",
                    reserved_units=reserved,
                    charged_units=reserved,
                    pricing=pricing,
                )
            )
        return call_id

    def settle(
        self,
        call_id: str,
        usage: dict | None,
        served_model: str | None,
        max_input: int,
        max_output: int,
    ):
        prompt = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        completion = usage.get("completion_tokens") if isinstance(usage, dict) else None
        known = type(prompt) is int and type(completion) is int and prompt >= 0 and completion >= 0
        with self.engine.begin() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            row = (
                connection.execute(select(ApiCall.__table__).where(ApiCall.call_id == call_id))
                .mappings()
                .one()
            )
            if row["status"] != "reserved":
                raise RagError("ledger_already_settled", "费用预留记录已处理。", 409)
            charge = units(prompt, completion, row["pricing"]) if known else row["reserved_units"]
            overflow = known and (prompt > max_input or completion > max_output)
            status = "needs_review" if overflow else ("settled_upper_bound" if known else "unknown")
            connection.execute(
                update(ApiCall)
                .where(ApiCall.call_id == call_id)
                .values(
                    status=status,
                    charged_units=max(charge, row["reserved_units"]) if overflow else charge,
                    prompt_tokens=prompt if known else None,
                    completion_tokens=completion if known else None,
                    served_model=served_model[:150] if isinstance(served_model, str) else None,
                )
            )
        if overflow:
            raise RagError(
                "provider_usage_out_of_bounds", "供应商用量超出预留范围，已保留额度并暂停调用。"
            )

    def unknown(self, call_id):
        with self.engine.begin() as connection:
            connection.execute(
                update(ApiCall)
                .where(ApiCall.call_id == call_id, ApiCall.status == "reserved")
                .values(status="unknown")
            )
