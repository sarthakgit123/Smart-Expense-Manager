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

## 🧪 Running Tests

Execute Django's automated test suite to verify database models, signals, and security rules:
```bash
python manage.py test
```

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for details.
