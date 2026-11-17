# Payments: what exists, what was deliberately left out, and what the owner must decide

## What exists
* **Monthly Pro** through Stripe, Razorpay (UPI, cards, netbanking) and PayPal (US dollars). The server owns every price; the browser never sends one.
* **Yearly Pro (optional).** It exists only when `PRO_PRICE_YEARLY_AMOUNT` is set (and `PRO_PRICE_USD_YEARLY` for PayPal; without it PayPal does not offer the yearly plan). Settings then shows a Monthly / Yearly choice. Receipts and emails say "month" or "year" correctly. No price is assumed; the numbers in `.env` are yours to decide.
* **Refund records** (admin console, Payments tab). VIDHI does **not** move money. You refund in Stripe, Razorpay or PayPal first, then record it: the payment shows what was refunded (partial or full, never more than was paid, safe if two people record at once), the customer gets a plain confirmation email (no tax wording), and the audit log keeps who recorded it and why. An optional "move the organisation to Free now" switch exists. Cancel the subscription in the provider's dashboard as well, or the customer is charged again.
* **Price structure by country** (`lib/pricing.py`, admin console `/admin/pricing`): currencies INR, USD, AED, GBP, SGD with reserved setting names. Only India is open for sale; the table says plainly which countries are not live and that their settings do nothing yet.

## Deliberately NOT built, and why
* **GST or any tax** is not calculated, collected, shown or invoiced anywhere. Whether VIDHI must charge it, at what rate, how invoices must look, and whether prices are tax-inclusive are decisions for the owner and an accountant, and the payment amounts the providers charge would have to match them. Receipts say nothing about tax. Placeholders for the GST number exist only on the legal pages (`BUSINESS_GSTIN`, format check only).
* **Coupons and discount codes.** The amount a customer pays each period is set at the provider when the subscription starts (Stripe price, Razorpay plan, PayPal plan). A discount therefore needs a decision first: first period only, or every period? percent or fixed? can it stack with the yearly plan? is it created in VIDHI or in each provider's own coupon/offer feature (the safer route, since the provider then charges the right amount)? Until that is decided a coupon box would either charge the wrong amount or do nothing, so none is shown.
* **Automatic provider refunds.** Calling each provider's refund API needs to be verified against their sandboxes (for example, where a subscription charge's payment id lives differs by provider and API version), and needs a refund policy (who may refund, within how many days, partial or full). A wrong automatic refund moves real money, so the recorded-after-the-fact route above is what ships.
* **Switching plans mid-subscription** (monthly to yearly): refused while a subscription is active ("already an active Pro subscription"). Cancel, let it end, then choose the other plan.

## Decisions for the owner (please answer; each unlocks work)
1. Yearly price (INR, and USD for PayPal), or no yearly plan.
2. GST: is VIDHI registered or required to be? Prices tax-inclusive or added on top? Do customers need tax invoices? (Ask an accountant.)
3. Coupons: the rules in the list above, and whether to use the providers' own coupon or offer features.
4. Refund policy in words (window, partial refunds, effect on Pro). Then it can go into the Terms page for a lawyer to review, and the refund process can be automated and tested against the sandboxes.
5. Which countries to open next, and the currency and price for each (each needs its law library and a lawyer: see `docs/ARCHITECTURE_DECISIONS.md`).