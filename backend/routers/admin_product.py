"""The operator's product numbers (Admin console > Product): runs, run time, failures and the wrong-result rate for each tool. Counters only, no person and no text (lib/product_stats.py lists exactly what is kept).
The same guard as every admin route is declared here too: routes added to another router do not inherit it."""

from fastapi import APIRouter, Depends, Query

from lib import product_stats
from lib.platform import require_platform_admin

admin_router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_platform_admin)])


@admin_router.get("/product")
async def product_numbers(days: int = Query(default=28, ge=1, le=400)):
    return await product_stats.report(days)
