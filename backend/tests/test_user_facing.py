"""Phase 2: what users are shown. Errors are plain language, prices come from the server."""


def test_packages_endpoint_requires_login_and_owns_the_price(anon, user_a):
    assert anon.get("/payments/packages").status_code == 401
    pkgs = user_a.get("/payments/packages").json()
    pro = next(p for p in pkgs if p["id"] == "vidhi_pro")
    assert isinstance(pro["amount"], (int, float)) and pro["amount"] > 0
    assert pro["currency"].isalpha() and len(pro["currency"]) == 3


def test_ai_failure_shows_a_plain_message_not_the_raw_error(user_a):
    # The test server runs with a dummy model key, so this call genuinely fails inside the provider
    # client - exactly the situation that used to put the raw exception text in front of the user.
    r = user_a.post("/research", json={"question": "What is the limitation period for recovery of money?"})
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail == "Our AI service is busy or unavailable right now. Please try again in a minute."
    for leak in ("dummy", "Traceback", "Error", "Exception", "401", "http"):
        assert leak not in detail


def test_verify_citation_is_a_lookup_so_it_never_depends_on_the_ai(user_a):
    # Not in the library -> honestly UNVERIFIED; no AI call, so no 502 and no "opinion".
    r = user_a.post("/verify-citation", json={"citation": "Section 138, Negotiable Instruments Act"})
    assert r.status_code == 200
    body = r.json()
    assert body["verification_status"] == "UNVERIFIED" and "not in the verified law library" in body["notes"]