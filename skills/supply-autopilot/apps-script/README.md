# Setting up the Google Sheet (5 minutes)

1. Create a new Google Sheet. Name it "Office supplies".
2. **Extensions > Apps Script.** Delete the starter code, paste all of
   `Code.gs`, and click Save.
3. Reload the sheet. A **Supply Autopilot** menu appears.
4. **Supply Autopilot > Set up this sheet.** Google asks you to authorize the
   script the first time (it needs the sheet, and Gmail to send you the
   digest). This creates five tabs:
   - **Settings**: headcount, guests this period, safety stock, reorder point.
     The cart link and estimated total appear here after each refresh.
   - **Inventory**: one row per item. Paste an Amazon product link (or ASIN)
     in "Link or ASIN" and the script finds the ASIN. "Scales with" says
     whether an item is used by everyone each week, owned one per teammate,
     or given one per guest. Gray columns are calculated.
   - **Vendors**: preferred and backup vendor for each category.
   - **Office fixes**: things that aren't working and their fix, owner and
     status. Starts with the entryway example.
   - **Order log**: a running history.
5. Replace the sample rows with your real items, then **Refresh order**.
6. Optional: **Turn on the Monday email** sends the order summary every
   Monday at 8 AM.

## Weekly routine

1. Update "On hand" (on a phone, in the Sheets app, takes two minutes). For a
   team-wide count or snack requests, link a Google Form to the sheet.
2. Update "Guests this period" if there are onsites or an event.
3. **Refresh order**, open the Amazon cart link, check it, check out.
4. Paste the "Other vendors" list from the email into Claude in Chrome.
   It fills those carts and stops. You check out.
5. **Log the order as placed.** Everything you just bought moves into the
   "On order" column, so next week's refresh won't order it again.
6. When the boxes arrive: **Mark everything on order as arrived**. It moves
   "On order" onto the shelf ("On hand").

The script never purchases anything.
