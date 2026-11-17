/**
 * The wording of the demand notice made by the Legal Recovery guide. It is plain text so that a lawyer can edit it without touching any code.
 * Fields in { } are filled from the form. {{STATEMENT}} and {{ENCLOSURES}} are filled by the server: the statement of account and the list of papers.
 * Rules the server enforces (so keep to them when editing): no legal section or Act, no threat or accusation, no sum of money typed into the wording.
 * TODO: verify - this wording has not been reviewed by a lawyer.
 */
export const NOTICE_TEMPLATE = `Date: {date}
To: {buyer_name}
{buyer_address}

From: {seller_name}
{seller_address}

Subject: Payment due against invoice {invoice_number} dated {invoice_date}

1. We supplied {description} to you and raised invoice {invoice_number} dated {invoice_date}.
2. The payment fell due on {due_date} and has not been received in full.

{{STATEMENT}}

3. Please pay the balance due within {days} days of receiving this notice, or reply in writing saying what you dispute.

{{ENCLOSURES}}

Yours faithfully,
{seller_name}
This is a draft to be reviewed before sending.`;

export type NoticeFields = {
  date: string;
  buyer_name: string;
  buyer_address: string;
  seller_name: string;
  seller_address: string;
  invoice_number: string;
  invoice_date: string;
  due_date: string;
  description: string;
  days: string;
};

/** Fills the { } fields. The two {{ }} marks are left for the server. */
export function renderNotice(f: NoticeFields): string {
  return NOTICE_TEMPLATE.replace(/\{([a-z_]+)\}/g, (whole, key: string) => (key in f ? (f as Record<string, string>)[key] : whole));
}
