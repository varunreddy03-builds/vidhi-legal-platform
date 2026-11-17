"""A sample matter so a new person can try VIDHI without their own papers. Everything in it is invented and says so; it is an ordinary matter that can be opened,
searched, analysed and deleted like any other. One per organisation: asking again returns the one that exists."""

import io

from fastapi import APIRouter, Depends
from starlette.datastructures import UploadFile

from lib.auth import audit, current_user, now
from lib.db import db
from models.schemas import Matter
from routers.documents import upload_document

router = APIRouter(tags=["demo"])

TITLE = "SAMPLE: Rao v. Kulkarni Traders (fictional)"
PARTIES = "Meera Rao (fictional); Kulkarni Traders Pvt Ltd (fictional)"
DESCRIPTION = "A practice matter made by VIDHI. Every name, date, place and amount in it is invented. Delete it whenever you like."
FILENAME = "sample-letter-fictional.txt"
LETTER = """SAMPLE DOCUMENT - FICTIONAL. Every name, date, place and amount below is invented for practice. It is not a real letter.

Date: 12 March 2026
From: Meera Rao, 14 Garden Lane, Sampletown
To: Kulkarni Traders Pvt Ltd, 7 Market Street, Sampletown

Subject: Payment for goods supplied under invoice SMP-0042

1. On 3 February 2026 I supplied 40 sample chairs to your shop at 7 Market Street under invoice SMP-0042 for Rs 48,000.
2. Your manager, Mr Arun Kulkarni, confirmed by message on 5 February 2026 that the chairs had arrived in good condition.
3. You paid Rs 20,000 on 20 February 2026. The balance of Rs 28,000 has not been paid.
4. I ask you to pay Rs 28,000 within 15 days of receiving this letter, or to tell me in writing what you dispute.

Yours faithfully,
Meera Rao
"""


@router.post("/demo/sample")
async def make_sample(user: dict = Depends(current_user)):
    org = user["organization_id"]
    existing = await db.matters.find_one({"organization_id": org, "is_sample": True})
    if existing:
        return {"matter_id": existing["id"], "created": False}
    matter = Matter(organization_id=org, title=TITLE, description=DESCRIPTION, parties=PARTIES, created_by=user["id"])
    doc = matter.model_dump() | {"is_sample": True}
    await db.matters.insert_one(doc)
    await upload_document(matter.id, UploadFile(file=io.BytesIO(LETTER.encode("utf-8")), filename=FILENAME), user)
    await audit(user, "SAMPLE_MATTER_CREATED", matter_id=matter.id, detail=now().date().isoformat())
    return {"matter_id": matter.id, "created": True}