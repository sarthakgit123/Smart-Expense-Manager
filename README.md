# 💸 Smart Expense Manager

A full-stack, enterprise-grade personal finance application built with **Django** and **Django REST Framework**, featuring real-time automated budget alerts, minimal obsidian dark theme UI, comprehensive category management, interactive analytics, and Google OAuth 2.0.

[![Django](https://img.shields.io/badge/Django-6.0+-092E20?style=for-the-badge&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/Django_REST_Framework-3.14+-red?style=for-the-badge&logo=django&logoColor=white)](https://www.django-rest-framework.org/)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Render](https://img.shields.io/badge/Render-46E3B7?style=for-the-badge&logo=render&logoColor=white)](https://render.com/)

---

## 🌐 Live Demo

🔗 **Live Deployment:** [finance-tracker-0oc7.onrender.com](https://finance-tracker-0oc7.onrender.com)

---

## ✨ Key Features

### 🎨 Modern Minimal Obsidian Dark Theme
- **Obsidian Palette:** Deep canvas (`#090a0f`), sleek surface cards (`#11131a`), glassmorphic borders, and vibrant accents (Indigo, Emerald, Rose, Amber).
- **Interactive Visualizations:** Dynamic Chart.js charts for category spending breakdowns (Pie) and monthly Income vs Expense tracking (Bar).
- **Smooth UX:** Responsive mobile navigation, feedback toasts, empty-state guidance, and safety confirmation modals for deletions.

### 🚨 Real-Time Automated Budget Alerts
- **Signal-Driven Notifications:** Django signals (`post_save` / `post_delete`) continuously evaluate spending limits across all categories in real-time.
- **Instant Email Dispatch:** When category spending crosses the monthly limit, an automated alert email is instantly dispatched to the user's registered address.
- **Anti-Spam & Self-Healing:** Integrated alert dampening prevents duplicate email spam per billing cycle while automatically resetting if transactions are edited or refunded below the threshold.
- **Flexible SMTP Provider Support:** Pre-configured for Brevo (Sendinblue), Gmail App Passwords, and SendGrid relays.

### 🏷️ Category Management & Out-of-the-Box Defaults
- **18 Pre-Seeded Default Categories:** Ready-to-use global categories covering essential expense streams (*Groceries, Utilities, Housing, Dining Out, Entertainment, Travel, Health & Fitness, Subscriptions, Shopping, etc.*) and income sources (*Salary, Freelance, Investments, Gifts, etc.*).
- **Custom Category Creation:** Create, edit, and organize custom categories with automatic type isolation.
- **Safe Cascading:** Category deletions safely reassign transactions to uncategorized without losing historical records.

### 📊 Financial Dashboard & Excel Export
- **Live Summary Metrics:** Total Income, Total Expense, Net Savings, and real-time Budget Utilization progress bars.
- **Monthly Reports:** Deep-dive into monthly financial summaries with date-range filters.
- **Excel Report Generator:** Export full monthly statements directly into `.xlsx` spreadsheets using OpenPyXL.

### 🔒 Enterprise Security & IDOR Hardening
- **Access Control:** All class-based views and API endpoints are strictly protected with authentication mixins and permissions.
- **IDOR Protection:** Cross-user data isolation ensures users can only access or modify their own transactions, budgets, and categories.
- **Google OAuth 2.0 Integration:** Secure social authentication with auto-signup and auto-connect.
- **Strong Password Validation:** Enforces Django's comprehensive password security validators during registration.

---

## 🛠️ Tech Stack

- **Backend:** Python 3.10+, Django 6.0+, Django REST Framework (DRF)
- **Database:** PostgreSQL (Production) / SQLite (Local Development)
- **Authentication:** Django Auth + `django-allauth` (Google OAuth 2.0)
- **Frontend:** Django Templates, Tailwind-inspired Minimal CSS, Chart.js, FontAwesome
- **Email Delivery:** Brevo SMTP / SendGrid / Django SMTP Relay
- **Export Utility:** OpenPyXL (Excel `.xlsx` Export)
- **Deployment:** Render / Gunicorn / WhiteNoise

---

## 📂 Project Structure

```text
Smart-Expense-Manager/
│
├── accounts/                   # User authentication, dashboard views, & utils
│   ├── models.py               # User Profile & account models
│   ├── views.py                # Dashboard, CRUD CBVs, & Excel export logic
│   ├── utils.py                # Email dispatchers & budget evaluation signals
│   └── urls.py                 # Accounts routing & auth URLs
│
├── transactions/               # Transaction, Category, & Budget core
│   ├── models.py               # Category, Transaction, Budget & post_save signals
│   ├── views.py                # DRF API ViewSets
│   ├── serializers.py          # DRF Serializers with IDOR validations
│   └── migrations/
│       └── 0004_seed_default_categories.py  # Default categories migration
│
├── finance_tracker/            # Project root settings & WSGI/ASGI
│   ├── settings.py             # Environment-aware configuration
│   └── urls.py                 # Master URL configuration
│
├── templates/                  # Obsidian Dark Theme Templates
│   ├── base.html               # Base layout, navbar, & shared styling
│   └── accounts/
│       ├── dashboard.html      # Main dashboard with charts & budget widgets
│       ├── monthly_report.html # Monthly analytics & export
│       ├── categories.html     # Category list & management
│       ├── transaction_form.html
│       ├── budget_form.html
│       └── ...
│
├── static/                     # Static CSS / JS / Favicon assets
├── requirements.txt            # Project dependencies
├── .env.example                # Sample environment configuration
└── manage.py
```

---

## ⚙️ Quickstart & Local Setup

### 1. Clone the Repository
```bash
git clone https://github.com/sarthakgit123/Smart-Expense-Manager.git
cd Smart-Expense-Manager
```

### 2. Create and Activate Virtual Environment
```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Create a `.env` file in the root directory (or copy from `.env.example`):
```env
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost

# Database (leave blank to use local SQLite)
DATABASE_URL=

# Google OAuth (Optional)
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Email Configuration (Brevo SMTP Example)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp-relay.brevo.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-brevo-login@smtp-brevo.com
EMAIL_HOST_PASSWORD=your-brevo-smtp-key
DEFAULT_FROM_EMAIL=your-verified-email@example.com
```

### 5. Run Migrations & Seed Default Categories
```bash
python manage.py migrate
```

### 6. Create Superuser (Optional)
```bash
python manage.py createsuperuser
```

### 7. Launch Development Server
```bash
python manage.py runserver
```
Visit **`http://127.0.0.1:8000/`** in your browser.

---

## 📧 Email Configuration Options

### Option A: Brevo (Sendinblue) SMTP
1. Sign up at [Brevo](https://www.brevo.com/) and go to **SMTP & API**.
2. Generate an SMTP key and configure:
   ```env
   EMAIL_HOST=smtp-relay.brevo.com
   EMAIL_PORT=587
   EMAIL_USE_TLS=True
   EMAIL_HOST_USER=your_smtp_login
   EMAIL_HOST_PASSWORD=xsmtpsib-...
   DEFAULT_FROM_EMAIL=your_email@gmail.com
   ```

### Option B: Gmail App Password
1. In Google Account settings, enable **2-Step Verification** > **App Passwords**.
2. Generate a password for `SmartExpenseManager`:
   ```env
   EMAIL_HOST=smtp.gmail.com
   EMAIL_PORT=587
   EMAIL_USE_TLS=True
   EMAIL_HOST_USER=your_gmail@gmail.com
   EMAIL_HOST_PASSWORD=xxxx-xxxx-xxxx-xxxx
   DEFAULT_FROM_EMAIL=your_gmail@gmail.com
   ```

---

## Telegram expense bot (n8n)

The Django API accepts Telegram events only when n8n sends the shared secret in
the `X-N8N-Secret` header. Generate a long random secret and configure the same
value as `N8N_WEBHOOK_SECRET` in Django and n8n. Do not put it in a workflow
message or commit it to source control. `TELEGRAM_LINK_CODE_TTL_MINUTES` controls
the one-time linking code lifetime (default: 10 minutes).

### Django and deployment setup

Add these variables to the deployment environment (and to local `.env` for
development):

```env
N8N_WEBHOOK_SECRET=<long-random-shared-secret>
TELEGRAM_LINK_CODE_TTL_MINUTES=10
TELEGRAM_BOT_USERNAME=<bot username from @BotFather, without @>
TIME_ZONE=Asia/Kolkata
```

`TELEGRAM_BOT_USERNAME` adds an "Open @bot in Telegram" button to the linking
page. `TIME_ZONE` decides what "today" means for Telegram entries that have no
date. A **Telegram** link in the navbar opens the linking page, where users can
also **unlink** their Telegram account. Telegram links, link codes (view-only)
and processed messages are visible in the Django admin. All variables are
listed in `.env.example`.

Run `python manage.py migrate` during deployment, then restart the web service.
Users link from the authenticated `/accounts/telegram/` page: generate a code,
then send `/link CODE` to the Telegram bot. Codes expire, can only be used once,
and cannot transfer a Telegram account already linked to another Django user.

### Recommended: one chat endpoint

n8n forwards every Telegram text message to a single endpoint and sends the
returned `reply_text` back to the chat. Django handles parsing, commands,
linking and duplicate protection.

`POST /api/telegram/message/` with header `X-N8N-Secret` and JSON body:

```json
{
  "telegram_user_id": 123456789,
  "message_id": 42,
  "text": "spent 250 on groceries yesterday",
  "telegram_username": "optional_username"
}
```

Map `telegram_user_id` from `message.from.id`, `message_id` from
`message.message_id`, `text` from `message.text`, and `telegram_username` from
`message.from.username`.

The endpoint returns HTTP 200 for anything a user can send, so the workflow can
always reply:

```json
{ "ok": true, "action": "transaction_created", "reply_text": "✅ Expense of ₹250 logged\n…", "transaction": { … } }
```

`action` is one of `transaction_created`, `duplicate`, `linked`, `link_error`,
`not_linked`, `inactive`, `parse_error`, `help`, `summary`, `budget`, `recent`,
`categories`, `undo` or `unknown_command`. A 401 means the secret is wrong; a
400 means `telegram_user_id` or `message_id` is malformed.

**What users can send**

| Message | Result |
| --- | --- |
| `250 groceries` | Expense ₹250 in Groceries, dated today |
| `spent 1,200 on petrol yesterday` | Expense in Transportation & Fuel, dated yesterday |
| `+5000 salary` / `received 5000 salary` | Income in Salary |
| `2.5k rent 01/11` · `₹99 netflix 2026-11-02` | `k` suffix, ₹/rs, DD/MM or YYYY-MM-DD dates |
| `/link CODE` or `/start CODE` | Link the account (the website's **Link instantly** button sends `/start CODE` automatically) |
| `/summary` · `/summary last` | Income, expenses, net and top categories for this month or last month |
| `/budget` | Each budget's spending, with 🟢 🟠 🔴 status |
| `/recent` | Last 5 transactions |
| `/categories` | Categories that can be used |
| `/undo` | Deletes the last transaction added from Telegram (a retried `/undo` is ignored) |
| `/help` | Usage help |

Categories are matched by name ("groceries"), by a word in the name ("food"
matches "Food & Dining"), or by common aliases ("swiggy", "uber", "netflix",
"petrol", and so on). The user's own categories come first. Unmatched expenses
go to **Miscellaneous** and unmatched income goes to **Other Income**. Expense
replies also include the category's budget status.

### Structured endpoints (optional)

These are useful when n8n parses the message itself (for example with an AI
node). Send JSON requests with `X-N8N-Secret: <same shared secret>`:

| Operation | Request |
| --- | --- |
| Confirm `/link CODE` | `POST /api/telegram/link/` with `telegram_user_id`, `telegram_username` (optional), and `code` |
| Add income or expense | `POST /api/telegram/expense/` with `telegram_user_id`, Telegram `message_id`, `amount`, and `transaction_type` (`IN` or `EX`); optionally `category_name`, `description`, and `date` (`YYYY-MM-DD`) |
| List categories | `GET /api/telegram/categories/?telegram_user_id=...` with optional `type=IN` or `type=EX` |

Use `message.message_id` from the Telegram trigger as `message_id`, and the
sender's numeric `message.from.id` as `telegram_user_id`. Do not accept either
identity from user-entered message text. Duplicate message IDs for the same
Telegram user return a successful duplicate response without creating another
transaction. Categories resolve to that user's categories or the global
defaults, and expenses continue through the existing budget alert signal.
Transactions with no matching optional category are saved without a category.

The separate `POST /api/telegram/link/generate/` endpoint uses the logged-in
Django session and CSRF protection; the web page is the recommended user flow.

---

## 🧪 Running Tests

Execute Django's automated test suite to verify database models, signals, and security rules:
```bash
python manage.py test
```

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for details.
