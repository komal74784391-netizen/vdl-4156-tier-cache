"""Tiered cache partitioning for multi-tenant cloud databases.

Reference implementation accompanying the SIGMOD 2025 paper.
"""

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class TenantProfile:
    tenant_id: str
    working_set_pages: int
    priority: float = 1.0
    borrow_limit: int = 0


@dataclass
class TierConfig:
    total_pages: int
    reserved_fraction: float = 0.65
    borrow_fraction: float = 0.20
    shared_fraction: float = 0.15


class TieredCachePartitioner:
    """Split the buffer cache into reserved, borrowable and shared tiers."""

    def __init__(self, config: TierConfig):
        self.config = config
        self._reserved: Dict[str, int] = {}
        self._borrowed: Dict[str, int] = {}

    def plan(self, tenants: List[TenantProfile]) -> Dict[str, int]:
        reserved_pool = int(self.config.total_pages * self.config.reserved_fraction)
        borrow_pool = int(self.config.total_pages * self.config.borrow_fraction)
        shared_pool = self.config.total_pages - reserved_pool - borrow_pool

        demand = sum(max(t.working_set_pages, 1) * t.priority for t in tenants)
        allocation: Dict[str, int] = {}
        for tenant in tenants:
            share = max(tenant.working_set_pages, 1) * tenant.priority / demand
            alloc = min(tenant.working_set_pages, int(reserved_pool * share))
            allocation[tenant.tenant_id] = max(alloc, 8)
            self._reserved[tenant.tenant_id] = allocation[tenant.tenant_id]

        remaining = borrow_pool
        candidates = sorted(tenants, key=lambda t: t.priority, reverse=True)
        for tenant in candidates:
            if remaining <= 0:
                break
            extra = min(tenant.borrow_limit, remaining, 256)
            if extra <= 0:
                continue
            allocation[tenant.tenant_id] += extra
            self._borrowed[tenant.tenant_id] = extra
            remaining -= extra

        if remaining > 0 and tenants:
            allocation[tenants[0].tenant_id] += remaining
        allocation["__shared__"] = shared_pool
        return allocation

    def reclaim(self, tenant_id: str) -> int:
        """Return borrowed pages when a tenant becomes idle."""
        pages = self._borrowed.pop(tenant_id, 0)
        if pages:
            self._reserved[tenant_id] = max(self._reserved.get(tenant_id, 0) - pages, 0)
        return pages
