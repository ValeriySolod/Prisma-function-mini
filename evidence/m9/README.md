# Historical PRISMA date-filter evidence captured before M.9 realignment

## Product boundary

This evidence was originally captured for the former M.9 date-filter increment.
After the authoritative roadmap realignment, date filtering is M.10 and this
directory remains historical evidence for that work.

Mini automates only the PRISMA `Start of Auction` date range. It does not set a
PRISMA Capacity filter. The booked-capacity rule belongs to local CSV processing
and may use only an explicitly verified authoritative CSV field and semantics.
No CSV field or capacity semantics are approved by this DOM evidence.

## Confirmed observations

- The start-date input exposes `data-testid="startOfAuctionFrom"`,
  `name="startOfAuctionFrom"`, placeholder `DD.MM.YYYY      HH:mm`,
  `data-test-error="false"`, displayed value `01.07.2026      06:00`, and
  PRISMA ISO value `2026-07-01T04:00:00.000Z`.
- The end-date input exposes `data-testid="startOfAuctionTo"`,
  `name="startOfAuctionTo"`, the same placeholder and error state, displayed
  value `21.07.2026      06:00`, and PRISMA ISO value
  `2026-07-21T04:00:00.000Z`.
- PRISMA is authoritative for displayed date/time and time-zone behavior. Mini
  must not add Windows-local, Europe/Kyiv, or independently inferred time-zone
  conversion.
- The captures do not establish the accepted control interaction, Apply action,
  or an observable successfully applied date-range state.

The confirmed controls and their observed attributes are preserved verbatim in
both HTML files. M.10 automation remains blocked at the Apply boundary.

## Remaining sanitized capture

From the authenticated PRISMA auction-reporting page, use browser developer
tools and choose **Copy outerHTML** for:

1. The complete action element used to apply the entered date range.
2. The smallest complete post-Apply element that proves the applied start and
   end values and successful applied state. If those facts appear in separate
   elements, copy each complete element.

Also record the exact interaction accepted by each date control (typing,
calendar selection, confirmation, or blur) and whether Apply causes navigation,
an in-page update, or another observable event. Do not include cookies, tokens,
credentials, account identifiers, personal data, complete sensitive URLs, or
auction-result data. Do not replace attributes with invented placeholders; if
an attribute contains sensitive data, remove that complete attribute and note
the removal separately.

CSV-download controls and download completion evidence belong to M.11, not M.10.
