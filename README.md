# Apparatus Inventory Tracker

Track Normal Unit Stocking (NUS) inventory for Structural (Type 1 & 2) and Wildland (Type 3–6) fire engines.  
Includes individual user logins and works on iPhone via Safari (add to Home Screen).

## Features

- **User logins** — each person signs in with their own account; actions are tagged with their name
- **Admin / User roles** — admins manage users and can delete apparatus
- **Per-truck inventory** — create a profile for each apparatus; inventory is seeded from the correct NUS standard
- **Live tracking** — update quantities vs required NUS levels
- **Dashboard** — % complete, incomplete items, Core shortages
- **Notifications** — alerts when checks find incomplete inventory
- **Export** — download any truck’s inventory as CSV

## Quick Start (computer)

```bash
cd truck_inventory_app
pip install streamlit pandas openpyxl bcrypt
streamlit run app.py
```

Open the URL shown (usually http://localhost:8501).

### Default login
| Username | Password   | Role  |
|----------|------------|-------|
| admin    | admin123   | admin |

**Change the admin password immediately** after first login (User Management → Change Your Password).

---

## Using on iPhone

This is a **web app**. You do not install it from the App Store. You open it in Safari and can pin it to your Home Screen so it feels like an app.

### Option A — Same Wi‑Fi as the computer running the app (simplest for testing)

1. On the computer, start the app:
   ```bash
   streamlit run app.py --server.address 0.0.0.0
   ```
2. Note the computer’s local IP address (e.g. `192.168.1.45`). On Mac: System Settings → Network. On Windows: `ipconfig`.
3. On your iPhone (same Wi‑Fi), open **Safari** and go to:
   ```
   http://192.168.1.45:8501
   ```
   (use your computer’s IP)
4. Sign in with your username and password.
5. **Add to Home Screen** (so it opens like an app):
   - Tap the **Share** button (square with arrow)
   - Scroll and tap **Add to Home Screen**
   - Name it “Apparatus Inventory” (or whatever you like) → Add
6. Open it from the Home Screen icon anytime you’re on the same network.

### Option B — Access from anywhere (recommended for real use)

Deploy the app to a free/cheap host so it has a public HTTPS URL. Then open that URL in Safari on any phone and Add to Home Screen.

**Easy free option — Streamlit Community Cloud**

1. Create a free account at https://share.streamlit.io
2. Put this folder in a GitHub repository (or upload the files)
3. Deploy from Streamlit Cloud → it gives you a URL like `https://your-app.streamlit.app`
4. Open that URL in Safari on your iPhone → Share → **Add to Home Screen**

**Other hosts that work well:** Railway, Render, Fly.io, a small VPS, or your department’s internal server.

Once it has an HTTPS URL, everyone with a login can use it from any iPhone, iPad, or computer.

---

## Creating additional users

1. Sign in as **admin**
2. Go to **User Management**
3. Create users with username, display name, password, and role (`user` or `admin`)
4. Users can sign in and update inventory; only admins manage users and delete apparatus

---

## Data files

| File | Purpose |
|------|---------|
| `inventory.db` | SQLite database (users, trucks, inventory, notifications) — created automatically |
| `structural_nus.xlsx` | Type 1 & 2 NUS standard |
| `wildland_nus.xlsx` | Type 3–6 NUS standard |

Back up `inventory.db` regularly.

---

## Notes

- “Mark All Full” sets every item’s current quantity = required NUS quantity
- Logging an inventory check creates a notification if anything is short
- All quantity changes and checks are recorded with the signed-in user’s name
- Change the default admin password as soon as possible
